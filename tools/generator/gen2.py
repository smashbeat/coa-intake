"""coa-intake v2 corpus generator. Runs inside the coa-gen-env image.

python3 gen2.py OUTDIR --seed N [--only ID,ID]

Writes OUTDIR/samples and OUTDIR/hidden: <id>.pdf, <id>.spec.json, <id>.truth.json, plus OUTDIR/manifest.json.
Truth comes from the certificate model and policy v2, never from reading the rendered file.
Four supplier houses, each with its own fonts, labels, layout and production route.
"""
from __future__ import annotations
import argparse, copy, datetime as dt, io, json, os, random, shutil, subprocess, tempfile, unicodedata
from decimal import Decimal, ROUND_HALF_UP

import pikepdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

LETTER = (612.0, 792.0)
A4 = (595.0, 842.0)

FONT_FILES = {
    "Liberation": ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    "DejaVuSerif": ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    "Carlito": ("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
                "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"),
    "Roboto": ("/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Regular.ttf",
               "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Bold.ttf"),
    "OpenSans": ("/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf",
                 "/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"),
}
for fam, (reg, bold) in FONT_FILES.items():
    pdfmetrics.registerFont(TTFont(fam, reg))
    pdfmetrics.registerFont(TTFont(fam + "-Bold", bold))
STAMP_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ------------------------------------------------------------------ policy v2 (truth side)

def norm(s):
    return "".join(unicodedata.normalize("NFKC", s).casefold().split())


UNIT_FACTOR = {norm(u): Decimal(f) for u, f in
               (("ppm", "1"), ("mg/kg", "1"), ("µg/g", "1"), ("ppb", "0.001"), ("µg/kg", "0.001"), ("%", "10000"))}


def convert(value: Decimal, unit, house_unit):
    """Value in the house unit, or None when the table cannot convert (policy 6)."""
    u = norm(unit) if unit else None
    h = norm(house_unit) if house_unit else None
    if u is None or u == h:
        return value
    if u in UNIT_FACTOR and h in UNIT_FACTOR:
        return value * UNIT_FACTOR[u] / UNIT_FACTOR[h]
    return None


def decimals(limit_text: str) -> int:
    return len(limit_text.split(".")[1]) if "." in limit_text else 0


def round_to(v: Decimal, places: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


ND_WORDS = ("nd", "notdetected", "<loq", "blq")


def evaluate(result, unit, test, loq):
    """True/False = meets/does not meet; None = no result (policy 6 and 7)."""
    lim = test["limit"]
    t = lim["type"]
    r = result.strip()
    low = r.lower()
    if t == "report":
        return True
    if t == "conforms":
        return low.startswith("conform") or low.startswith("compl") or low in ("pass", "passes")
    if t == "absent":
        return any(low.startswith(p) for p in ("absent", "not detected", "nd", "negative"))
    if norm(r) in ND_WORDS:
        if loq is None:
            return None
        r, unit = "<" + loq[0], loq[1]
    lt = r.startswith("<")
    try:
        v = Decimal(r.lstrip("<").strip())
    except Exception:
        return False
    v = convert(v, unit, test["unit"])
    if v is None:
        return None
    if t == "max":
        return round_to(v, decimals(lim["max"])) <= Decimal(lim["max"])
    if lt:
        return False
    if t == "min":
        return round_to(v, decimals(lim["min"])) >= Decimal(lim["min"])
    lo, hi = Decimal(lim["min"]), Decimal(lim["max"])
    return lo <= round_to(v, decimals(lim["min"])) and round_to(v, decimals(lim["max"])) <= hi


def disposition(spec, lot):
    """lot: truth lot plus '_loq' {row index: (value, unit)}."""
    received = dt.date.fromisoformat(spec["received"])
    d = lot["retest_date"] or lot["expiry_date"]
    if d and dt.date.fromisoformat(d) <= received:
        return "reject"
    failing = missing = False
    for test in spec["tests"]:
        names = {norm(n) for n in test["names"]}
        idx = next((i for i, row in enumerate(lot["results"]) if norm(row["test"]) in names), None)
        if idx is None:
            missing = True
            continue
        row = lot["results"][idx]
        if row["result"] is None:
            missing = True
            continue
        ok = evaluate(row["result"], row["unit"], test, lot["_loq"].get(idx))
        if ok is None:
            missing = True
        elif not ok:
            failing = True
    return "reject" if failing else "incomplete" if missing else "accept"


# ------------------------------------------------------------------ catalogue

MATERIALS = [
    ("Ascorbic Acid USP", "Fine powder"),
    ("Zinc Citrate Trihydrate", "Granular"),
    ("Magnesium Bisglycinate", "Powder"),
    ("Cholecalciferol 100,000 IU/g", "Powder"),
    ("Ferrous Bisglycinate Chelate", "Powder"),
    ("Pyridoxine Hydrochloride USP", "Crystalline powder"),
    ("Calcium Carbonate (Precipitated)", "Powder"),
]

D = Decimal


def num(lo, hi, places):
    def f(rnd):
        return str(round_to(D(str(rnd.uniform(lo, hi))), places))
    return f


def choice(*xs):
    return lambda rnd: rnd.choice(xs)


# name, aliases, limit type, limit params (strings), house unit, passing result generator (house unit), kind
TESTS = [
    ("Appearance", ["Description"], "report", {}, None,
     choice("White to off-white powder", "Off-white powder", "White crystalline powder", "Fine white powder"), "text"),
    ("Identification (IR)", ["Identity (FTIR)", "Identification"], "conforms", {}, None,
     choice("Conforms", "Complies", "Conforms to reference"), "text"),
    ("Assay (on dried basis)", ["Assay", "Assay (HPLC)"], "range", {"min": "98.0", "max": "101.5"}, "%",
     num(98.4, 101.1, 1), "num"),
    ("Loss on drying", ["LOD"], "max", {"max": "0.5"}, "%", num(0.05, 0.42, 2), "num"),
    ("Residue on ignition", ["Sulfated ash"], "max", {"max": "0.10"}, "%", num(0.01, 0.08, 2), "num"),
    ("Lead (Pb)", ["Lead", "Pb"], "max", {"max": "1.0"}, "ppm", num(0.05, 0.6, 2), "metal"),
    ("Arsenic (As)", ["Arsenic", "As"], "max", {"max": "1.0"}, "ppm", num(0.05, 0.6, 2), "metal"),
    ("Cadmium (Cd)", ["Cadmium", "Cd"], "max", {"max": "0.5"}, "ppm", num(0.01, 0.3, 2), "metal"),
    ("Mercury (Hg)", ["Mercury", "Hg"], "max", {"max": "0.1"}, "ppm", num(0.005, 0.06, 3), "metal"),
    ("Total aerobic microbial count", ["TAMC", "Total plate count"], "max", {"max": "1000"}, "cfu/g",
     choice("<10", "<100", "40", "120", "230"), "micro"),
    ("Total yeast and mold", ["TYMC", "Yeasts and moulds"], "max", {"max": "100"}, "cfu/g",
     choice("<10", "20", "35"), "micro"),
    ("Escherichia coli (10 g)", ["E. coli (10 g)"], "absent", {}, None, choice("Absent", "Negative"), "text"),
    ("Salmonella spp. (25 g)", ["Salmonella (25 g)"], "absent", {}, None, choice("Absent", "Not detected"), "text"),
    ("Particle size (through 80 mesh)", ["Mesh (80)"], "min", {"min": "95.0"}, "%", num(96.0, 99.8, 1), "num"),
    ("Bulk density", ["Bulk density (untapped)"], "range", {"min": "0.45", "max": "0.75"}, "g/mL",
     num(0.5, 0.7, 2), "num"),
    ("pH (1% solution)", ["pH"], "range", {"min": "5.5", "max": "7.5"}, None, num(5.8, 7.2, 1), "num"),
]
TEST_BY_NAME = {t[0]: t for t in TESTS}
METALS = [t[0] for t in TESTS if t[6] == "metal"]

HOUSES = {
    "hengxin": dict(
        name="Hengxin Nutrition Co., Ltd.", address="No. 88 Keyuan Road, Suzhou, Jiangsu 215000, China",
        font="Liberation", size=LETTER, date_style="iso", multi="columns",
        lot_label="Batch No.", mfg_label="Date of Manufacture", retest_label="Re-test Date", expiry_label="Expiry Date",
        product_label="Product Name", cols=[("Test Item", "test", 165), ("Standard", "spec", 120),
                                            ("Result", "result", 95), ("Unit", "unit", 55)],
        spec_style="sym", extras=[("Date of Issue", "issue"), ("Quantity", "qty")],
        meta={"Producer": "ReportLab PDF Library - www.reportlab.com", "Creator": "Hengxin LIMS QC-Report 5.1"}),
    "nordvik": dict(
        name="Nordvik Ingredients AS", address="Industriveien 12, 1385 Asker, Norway",
        font="DejaVuSerif", size=A4, date_style="dmy", multi="sections",
        lot_label="Lot No.", mfg_label="Manufacture Date", retest_label="Retest Date", expiry_label="Expiry Date",
        product_label="Product", cols=[("Parameter", "test", 175), ("Result", "result_unit", 120),
                                       ("Specification", "spec", 140)],
        spec_style="maxmin", extras=[("Issued", "issue"), ("Storage", "storage")],
        meta={"Creator": "PScript5.dll Version 5.2.2", "Title": "Microsoft Word - CoA"}),
    "pradesh": dict(
        name="Pradesh Phytochem Pvt. Ltd.", address="Plot 14, MIDC Bhosari, Pune 411026, India",
        font="Carlito", size=LETTER, date_style="mdy", multi="pages",
        lot_label="Lot Number", mfg_label="Mfg. Date", retest_label="Retest Date", expiry_label="Exp. Date",
        product_label="Name of Product", cols=[("Test", "test", 150), ("Specification", "spec", 120),
                                                ("Result", "result", 80), ("Unit", "unit", 50), ("LOQ", "loq", 60)],
        spec_style="nmt", extras=[("Analysis Date", "issue"), ("Pack Size", "qty")],
        meta={"Creator": "Canon iR-ADV C5535", "Producer": "Adobe PSL 1.3e for Canon"}),
    "bluewater": dict(
        name="Bluewater Biochem Inc.", address="4120 Commerce Dr, Reno, NV 89502, USA",
        font="Roboto", size=LETTER, date_style="mdy", multi="sections",
        lot_label="Lot #", mfg_label="Manufactured", retest_label="Retest By", expiry_label="Expires",
        product_label="Material", cols=[("Analysis", "test", 170), ("Limit", "spec", 120), ("Result", "result", 95),
                                        ("Units", "unit", 55)],
        spec_style="nmt", extras=[("Release Date", "issue")],
        meta={"Producer": "ReportLab PDF Library - www.reportlab.com", "Creator": "QCForms 3.2"}),
}


def fmt_date(d: dt.date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "dmy":
        return d.strftime("%d-%b-%Y")
    return d.strftime("%B %d, %Y")


def supplier_spec(test, unit_shown, style):
    """The supplier's own specification text, in the unit the certificate prints."""
    name, _, t, p, hu, _, _ = test
    def conv(x):
        if unit_shown and hu and norm(unit_shown) != norm(hu) and norm(unit_shown) in UNIT_FACTOR:
            v = D(x) * UNIT_FACTOR[norm(hu)] / UNIT_FACTOR[norm(unit_shown)]
            return format(v.normalize(), "f")
        return x
    u = f" {unit_shown}" if unit_shown else ""
    if t == "max":
        return {"sym": f"≤ {conv(p['max'])}{u}", "maxmin": f"max. {conv(p['max'])}{u}"}.get(style, f"NMT {conv(p['max'])}{u}")
    if t == "min":
        return {"sym": f"≥ {conv(p['min'])}{u}", "maxmin": f"min. {conv(p['min'])}{u}"}.get(style, f"NLT {conv(p['min'])}{u}")
    if t == "range":
        sep = {"sym": " ~ ", "maxmin": " - "}.get(style, " to ")
        return f"{p['min']}{sep}{p['max']}{u}"
    if t == "absent":
        return {"sym": "Negative/10 g" if "10 g" in name else "Negative/25 g"}.get(style, "Absent")
    if t == "conforms":
        return "Conforms to standard" if style == "sym" else "Conforms"
    return "Report" if style != "sym" else "/"


# ------------------------------------------------------------------ certificate model

class Cert:
    """Everything that is printed, and the truth derived from it."""

    def __init__(self, cid, house, rnd, n_lots, features, route):
        self.id, self.house, self.rnd, self.features, self.route = cid, HOUSES[house], rnd, set(features), route
        self.house_key = house
        self.material = rnd.choice(MATERIALS)
        self.received = dt.date(2026, 10, rnd.randint(6, 20))
        names = [t[0] for t in TESTS]
        must = []
        if self.features & {"units", "units_bad", "nd_loq_col", "nd_loq_note", "nd_no_loq", "nd_loq_high",
                            "round_metal"}:
            must += rnd.sample(METALS, 2)
        if "round_min" in self.features:
            must.append("Particle size (through 80 mesh)")
        if "round_range" in self.features:
            must.append("pH (1% solution)")
        if "wrap" in self.features:
            must.append("Appearance")
        rest = [n for n in names if n not in must]
        chosen = set(must + rnd.sample(rest, max(0, rnd.randint(7, 10) - len(must))))
        self.tests = [TEST_BY_NAME[n] for n in names if n in chosen]
        self.spec = {"material": self.material[0], "received": self.received.isoformat(),
                     "tests": [{"names": [t[0]] + t[1], "limit": {"type": t[2], **t[3]}, "unit": t[4]}
                               for t in self.tests]}
        self.notes = []          # printed note lines under the table
        self.revisions = []      # {"rev": n, "lot": i, "kind": "result"|"date", "row": j, "value": str, ...}
        self.loq_col = "loq" in [c[1] for c in self.house["cols"]]
        self.lots = [self._make_lot(k) for k in range(n_lots)]
        self.issue = self.received - dt.timedelta(days=rnd.randint(20, 60))

    def _make_lot(self, k):
        rnd = self.rnd
        mfg = dt.date(2026, rnd.randint(2, 8), rnd.randint(1, 28)) + dt.timedelta(days=7 * k)
        retest = rnd.random() < 0.65
        d2 = mfg + dt.timedelta(days=rnd.choice([365, 540, 730]))
        rows = []
        for t in self.tests:
            res = t[5](rnd)
            rows.append({"t": t, "test": t[0], "result": res, "unit": t[4], "spec_unit": t[4],
                         "marker": None, "loq": None})
        return {"lot_number": f"{rnd.choice('LBP')}{rnd.randint(100000, 999999)}", "mfg": mfg,
                "retest": d2 if retest else None, "expiry": None if retest else d2, "rows": rows}

    # truth -------------------------------------------------------
    def truth(self):
        out = {"lots": []}
        for li, lot in enumerate(self.lots):
            lot = copy.deepcopy(lot)
            revs = sorted((r for r in self.revisions if r["lot"] == li), key=lambda r: r["rev"])
            for r in revs:          # ascending, so the highest revision is applied last and wins
                if r["kind"] == "result":
                    lot["rows"][r["row"]]["result"] = r["value"]
                elif r["kind"] == "retest":
                    lot["retest"] = r["value"]
            rows, loq = [], {}
            shared = self.house["multi"] == "columns" and len(self.lots) > 1
            for j, row in enumerate(lot["rows"]):
                spec_text = self.lots[0]["rows"][j]["spec_text"] if shared else row["spec_text"]
                rows.append({"test": row["test"], "result": row["result"], "unit": row["unit"],
                             "specification": spec_text})
                if row["loq"]:
                    loq[j] = row["loq"]
            for note in self.notes:
                if note.get("loq_for") is not None and note["lot"] in (None, li):
                    loq[note["loq_for"]] = note["loq"]
            entry = {"material": self.material[0], "supplier": self.house["name"],
                     "lot_number": lot["lot_number"], "manufacture_date": lot["mfg"].isoformat(),
                     "retest_date": lot["retest"].isoformat() if lot["retest"] else None,
                     "expiry_date": lot["expiry"].isoformat() if lot["expiry"] else None,
                     "results": rows, "_loq": loq}
            entry["disposition"] = disposition(self.spec, entry)
            del entry["_loq"]
            out["lots"].append(entry)
        return out


# ------------------------------------------------------------------ features (rules A to F, plus v1 routes)

def apply_features(c: Cert):
    rnd, f = c.rnd, c.features
    lot0 = c.lots[0]
    metal_rows = lambda lot: [j for j, r in enumerate(lot["rows"]) if r["t"][6] == "metal"]
    if "alias" in f:                                     # rule 6 names
        for lot in c.lots:
            for j, r in enumerate(lot["rows"]):
                if r["t"][1] and (j % 2 == 0):
                    r["test"] = r["t"][1][0]
        # all lots of one certificate print the same names
        for lot in c.lots[1:]:
            for j, r in enumerate(lot["rows"]):
                r["test"] = lot0["rows"][j]["test"]
    if "units" in f or "round_metal" in f:               # rule 6 units and rounding on a metal
        j = metal_rows(lot0)[0]
        # µ only where the file keeps it as text: scans, outlines and redistilled files lose or blur it
        unit = rnd.choice(["mg/kg", "ppb", "µg/kg"]) if c.route in ("digital", "form", "form_mismatch") \
            else rnd.choice(["mg/kg", "ppb"])
        if "units" not in f:
            unit = "ppm"
        for lot in c.lots:
            r = lot["rows"][j]
            lim = D(r["t"][3]["max"])
            if "round_metal" in f and lot is lot0:
                v = lim + (D("0.05") if "round_fail" in f else D("0.04"))
            else:
                v = D(r["result"])
            shown = v * UNIT_FACTOR[norm("ppm")] / UNIT_FACTOR[norm(unit)]
            r["result"] = format(shown.normalize(), "f") if unit in ("ppb", "µg/kg") else str(v)
            r["unit"] = unit
            r["spec_unit"] = unit
    if "units_bad" in f:                                 # unconvertible unit: no result
        j = metal_rows(lot0)[-1]
        lots = c.lots if c.house["multi"] == "columns" else [lot0]
        for lot in lots:
            lot["rows"][j]["unit"] = "mg/L"
            lot["rows"][j]["spec_unit"] = "mg/L"
    if "round_min" in f:
        j = next(j for j, r in enumerate(lot0["rows"]) if r["test"].startswith("Particle") or r["t"][0].startswith("Particle"))
        lot0["rows"][j]["result"] = "94.96" if "round_fail" not in f else "94.94"
    if "round_range" in f:
        j = next(j for j, r in enumerate(lot0["rows"]) if r["t"][0].startswith("pH"))
        lot0["rows"][j]["result"] = "7.54" if "round_fail" not in f else "7.55"
    if f & {"nd_loq_col", "nd_loq_note", "nd_no_loq", "nd_loq_high"}:   # rule 7 detection limits
        js = metal_rows(lot0)
        for lot in c.lots:
            for j in js:
                lot["rows"][j]["result"] = rnd.choice(["ND", "Not detected", "<LOQ", "BLQ"]) if j == js[0] else lot["rows"][j]["result"]
        j = js[0]
        unit = lot0["rows"][j]["unit"] or "ppm"
        if "result_unit" in [k for _, k, _ in c.house["cols"]] or c.house["multi"] == "columns":
            for lot in c.lots:
                lot["rows"][j]["unit"] = None
        lim = D(lot0["rows"][j]["t"][3]["max"])
        hi = lim * 2 * UNIT_FACTOR[norm("ppm")] / UNIT_FACTOR[norm(unit)] if norm(unit) in UNIT_FACTOR else lim * 2
        lo = D("0.05") * UNIT_FACTOR[norm("ppm")] / UNIT_FACTOR[norm(unit)] if norm(unit) in UNIT_FACTOR else D("0.05")
        loq_val = format((hi if "nd_loq_high" in f else lo).normalize(), "f")
        if "nd_loq_col" in f and c.loq_col:
            for lot in c.lots:
                lot["rows"][j]["loq"] = (loq_val, unit)
        elif "nd_loq_note" in f or "nd_loq_high" in f or ("nd_loq_col" in f and not c.loq_col):
            name = lot0["rows"][j]["test"]
            c.notes.append({"text": f"LOQ for {name}: {loq_val} {unit}", "loq_for": j, "loq": (loq_val, unit),
                            "lot": None})
    if "marker" in f:                                     # rule 4 marks
        j = next(j for j, r in enumerate(lot0["rows"]) if r["t"][6] in ("num", "metal", "micro") and
                 not r["result"].startswith("<") and r["loq"] is None and norm(r["result"]) not in ND_WORDS)
        mark = "*" if c.route in SCAN_ROUTES | {"form", "form_mismatch"} or rnd.random() < 0.5 else "sup"
        lot0["rows"][j]["marker"] = mark
        c.notes.append({"text": ("* " if mark == "*" else "a ") + "Result confirmed by retest.", "loq_for": None,
                        "lot": 0, "sup": mark == "sup"})
    if "fail" in f:
        cand = [j for j, r in enumerate(lot0["rows"]) if r["t"][2] in ("max", "range", "min") and
                r["loq"] is None and norm(r["result"]) not in ND_WORDS and r["unit"] == r["t"][4]]
        j = rnd.choice(cand)
        r = lot0["rows"][j]
        t, p = r["t"][2], r["t"][3]
        if t == "max":
            r["result"] = str(round_to(D(p["max"]) * D("1.6"), decimals(p["max"]) + 1))
        elif t == "min":
            r["result"] = str(round_to(D(p["min"]) * D("0.9"), decimals(p["min"])))
        else:
            r["result"] = str(round_to(D(p["max"]) * D("1.03"), decimals(p["max"])))
    if "missing" in f:
        j = rnd.choice([j for j, r in enumerate(lot0["rows"]) if r["t"][2] in ("report", "conforms", "absent")]
                       or [0])
        lot0["rows"][j]["result"] = None
    if "wrap" in f:
        j = next(j for j, r in enumerate(lot0["rows"]) if r["t"][0] == "Appearance")
        for lot in c.lots:
            lot["rows"][j]["result"] = rnd.choice(["White to off-white crystalline powder, odourless",
                                                   "Fine white free-flowing powder with faint odour"])
    if "stamp_retest" in f and lot0["retest"] is None:
        lot0["retest"], lot0["expiry"] = lot0["expiry"], None
    if "expired" in f:                                    # rule 8 receipt date
        lot0["mfg"] = dt.date(2024, rnd.randint(3, 9), rnd.randint(1, 28))
        lot0["retest"] = c.received - dt.timedelta(days=rnd.choice([0, 3, 40]))
        lot0["expiry"] = None
    if "rev_extends" in f:                                # expired lot, revision extends the retest date
        lot0["mfg"] = dt.date(2024, rnd.randint(3, 9), rnd.randint(1, 28))
        lot0["retest"] = c.received - dt.timedelta(days=rnd.randint(5, 60))
        lot0["expiry"] = None
        c.revisions.append({"rev": 2, "lot": 0, "kind": "retest", "value": c.received + dt.timedelta(days=365),
                            "why": "Retest date extended after re-analysis"})
    if "rev_result" in f or "rev_twice" in f:             # rule 5 revisions of a result
        li = len(c.lots) - 1 if len(c.lots) > 1 and rnd.random() < 0.6 else 0
        lot = c.lots[li]
        cand = [j for j, r in enumerate(lot["rows"]) if r["t"][6] in ("num", "metal") and r["loq"] is None and
                norm(r["result"] or "") not in ND_WORDS and not (r["result"] or "<").startswith("<") and
                r["marker"] is None and r["unit"] == r["t"][4]]
        j = rnd.choice(cand)
        r = lot["rows"][j]
        t, p = r["t"][2], r["t"][3]
        good = r["result"]
        if t == "max":
            bad = str(round_to(D(p["max"]) * D("1.4"), max(decimals(p["max"]), 1)))
        elif t == "min":
            bad = str(round_to(D(p["min"]) * D("0.9"), max(decimals(p["min"]), 1)))
        else:
            bad = str(round_to(D(p["max"]) * D("1.02"), max(decimals(p["max"]), 1)))
        # the original prints the failing value; the revision corrects it
        r["result"] = bad
        if "rev_twice" in f:
            mid = str(round_to(D(good) * D("1.1"), max(decimals(good), 1))) if "." in good else good
            c.revisions.append({"rev": 2, "lot": li, "kind": "result", "row": j, "value": mid})
            c.revisions.append({"rev": 3, "lot": li, "kind": "result", "row": j, "value": good})
        else:
            c.revisions.append({"rev": 2, "lot": li, "kind": "result", "row": j, "value": good})
    for lot in c.lots:
        for r in lot["rows"]:
            r["spec_text"] = supplier_spec(r["t"], r["spec_unit"], c.house["spec_style"])


# ------------------------------------------------------------------ drawing

class Pen:
    """Top-left coordinates over a reportlab canvas, one house font family."""

    def __init__(self, path, house, size=None):
        self.size = size or house["size"]
        self.c = rl_canvas.Canvas(path, pagesize=self.size, invariant=1)
        self.font = house["font"]
        self.w, self.h = self.size
        self.y = 54
        self.page_no = 1

    def text(self, x, s, size=10, bold=False, y=None, color=(0, 0, 0), align="left", sup=None, fill=None):
        yy = self.y if y is None else y
        f = self.font + ("-Bold" if bold else "")
        self.c.setFont(f, size)
        self.c.setFillColorRGB(*(fill or color))
        if align == "center":
            x = x - pdfmetrics.stringWidth(s, f, size) / 2
        self.c.drawString(x, self.h - yy, s)
        if sup:
            sw = pdfmetrics.stringWidth(s, f, size)
            self.c.setFont(f, size * 0.6)
            self.c.drawString(x + sw + 0.5, self.h - yy + size * 0.38, sup)
        self.c.setFillColorRGB(0, 0, 0)
        return yy

    def width(self, s, size=10, bold=False):
        return pdfmetrics.stringWidth(s, self.font + ("-Bold" if bold else ""), size)

    def line(self, x0, x1, y=None, width=0.6):
        yy = self.y if y is None else y
        self.c.setLineWidth(width)
        self.c.line(x0, self.h - yy, x1, self.h - yy)

    def image(self, im, x, y, w, h):
        self.c.drawImage(ImageReader(im), x, self.h - y - h, w, h, mask="auto")

    def new_page(self, size=None):
        self.c.showPage()
        if size:
            self.size = size
            self.c.setPageSize(size)
            self.w, self.h = size
        self.y = 54
        self.page_no += 1

    def save(self):
        self.c.showPage()
        self.c.save()


def wrap(pen, s, w, size):
    words, lines, cur = s.split(" "), [], ""
    for word in words:
        cand = (cur + " " + word).strip()
        if pen.width(cand, size) <= w - 6 or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def draw_header(pen, c: Cert, continued=False, revision=None):
    h = c.house
    k = c.house_key
    title = "CERTIFICATE OF ANALYSIS"
    if revision:
        title += f", REVISION {revision}"
    elif continued:
        title += " (continued)"
    if k == "hengxin":
        pen.text(54, h["name"], 14, bold=True); pen.y += 13
        pen.text(54, h["address"], 8.5); pen.y += 24
        pen.text(pen.w / 2, title, 13, bold=True, align="center"); pen.y += 7
        pen.line(54, pen.w - 54, width=1.2); pen.y += 2.5; pen.line(54, pen.w - 54, width=0.4); pen.y += 20
    elif k == "nordvik":
        pen.text(54, h["name"], 16, bold=True); pen.y += 14
        pen.text(54, h["address"], 8.5); pen.y += 6
        pen.line(54, pen.w - 54, width=0.8); pen.y += 20
        pen.text(54, title.title().replace("Of", "of"), 12, bold=True); pen.y += 20
    elif k == "pradesh":
        pen.text(pen.w / 2, h["name"].upper(), 15, bold=True, align="center"); pen.y += 14
        pen.text(pen.w / 2, h["address"], 9, align="center"); pen.y += 24
        pen.text(pen.w / 2, title, 13, bold=True, align="center"); pen.y += 3
        tw = pen.width(title, 13, True)
        pen.line(pen.w / 2 - tw / 2, pen.w / 2 + tw / 2, width=0.8); pen.y += 22
    else:
        pen.text(54, h["name"], 13, bold=True); pen.y += 12
        pen.text(54, h["address"], 8.5); pen.y += 22
        pen.text(54, ("Certificate of Analysis / QC Release" if not (continued or revision) else title.title()),
                 12, bold=True); pen.y += 8
        pen.line(54, pen.w - 54, width=0.5); pen.y += 18


def label_value(pen, label, value, x=54, vx=None, size=10):
    vx = vx or x + 120
    pen.text(x, label + ":", size, bold=True)
    if value is not None:
        pen.text(vx, value, size)
    pen.y += 14


def lot_dates(c, lot, override=None):
    o = override or {}
    retest = o.get("retest", lot["retest"])
    ds = c.house["date_style"]
    if retest:
        return c.house["retest_label"], fmt_date(retest, ds) if isinstance(retest, dt.date) else retest
    return c.house["expiry_label"], fmt_date(lot["expiry"], ds)


def draw_identity_single(pen, c, lot, with_product=True, override=None):
    h = c.house
    ds = h["date_style"]
    if with_product:
        label_value(pen, h["product_label"], c.material[0])
    lv = (override or {}).get("lot_number", lot["lot_number"])
    label_value(pen, h["lot_label"], lv)
    label_value(pen, h["mfg_label"], (override or {}).get("mfg", fmt_date(lot["mfg"], ds)))
    lab, val = lot_dates(c, lot, override)
    label_value(pen, lab, val)


def draw_extras(pen, c):
    for label, kind in c.house["extras"]:
        v = {"issue": fmt_date(c.issue, c.house["date_style"]), "qty": f"{c.rnd.choice([25, 50, 200, 500])} kg",
             "storage": "Store below 25 °C in a dry place"}[kind]
        label_value(pen, label, v)


def cell_text(row, key, lot_rows=None):
    if key == "test":
        return row["test"], None
    if key == "spec":
        return row["spec_text"], None
    if key == "result":
        return (row["result"] or ""), row["marker"]
    if key == "unit":
        return (row["unit"] or ""), None
    if key == "result_unit":
        res = row["result"] or ""
        if row["marker"] and row["unit"]:
            return res, row["marker"] + "|" + row["unit"]
        return (res + (" " + row["unit"] if row["unit"] and res else "")), row["marker"]
    if key == "loq":
        return (f"{row['loq'][0]} {row['loq'][1]}" if row["loq"] else ""), None
    raise KeyError(key)


def draw_table(pen, c, cols, rows_of, n_rows, page_bottom, on_new_page, size=9.5, lh=12, order_reverse=False,
               break_at=None):
    """cols: [(header, width, getter(i) -> (text, marker))]. Breaks across pages at page_bottom."""
    x0 = 54
    total = sum(w for _, w, _ in cols)

    def header():
        x = x0
        for head, w, _ in cols:
            pen.text(x + 3, head, size, bold=True)
            x += w
        pen.y += 5
        pen.line(x0, x0 + total, width=0.8)
        pen.y += lh + 1

    header()
    for i in range(n_rows):
        cells = [g(i) for _, _, g in cols]
        depth = max(len(wrap(pen, t, w, size)) for (t, _), (_, w, _) in zip(cells, cols))
        if pen.y + depth * lh > page_bottom or (break_at and i == break_at):
            on_new_page()
            header()
        x = x0
        placements = []
        for (text, mark), (_, w, _) in zip(cells, cols):
            for k, piece in enumerate(wrap(pen, text, w, size)):
                placements.append((x + 3, pen.y + k * lh, piece, mark if k == 0 else None))
            x += w
        if order_reverse:
            placements = list(reversed(placements))
            for px, py, piece, mark in placements:     # each word emitted separately, last word first
                words, cx = piece.split(" "), px
                spots = []
                for wd in words:
                    spots.append((cx, wd))
                    cx += pen.width(wd + " ", size)
                for sx, wd in reversed(spots):
                    pen.text(sx, wd, size, y=py)
        else:
            for px, py, piece, mark in placements:
                if mark and "|" in mark:               # marker then unit, e.g. "0.42* mg/kg"
                    m, unit = mark.split("|")
                    if m == "sup":
                        pen.text(px, piece, size, y=py, sup="a")
                        pen.text(px + pen.width(piece, size) + 8, unit, size, y=py)
                    else:
                        pen.text(px, f"{piece}{m} {unit}", size, y=py)
                elif mark == "sup":
                    pen.text(px, piece, size, y=py, sup="a")
                elif mark:
                    pen.text(px, piece + mark, size, y=py)
                else:
                    pen.text(px, piece, size, y=py)
        pen.y += (depth - 1) * lh + 4
        pen.line(x0, x0 + total, width=0.3)
        pen.y += lh


def draw_notes(pen, c, lot_index=None):
    lines = [n for n in c.notes if n.get("lot") in (None, lot_index) or lot_index is None]
    if not lines:
        return
    pen.y += 4
    for n in lines:
        if n.get("sup"):
            pen.text(54, "a", 6.5, y=pen.y - 3)
            pen.text(59, n["text"][2:], 8.5)
        else:
            pen.text(54, ("Note: " if not n["text"].startswith("*") else "") + n["text"], 8.5)
        pen.y += 11


def amendment_block(pen, c):
    revs = sorted(c.revisions, key=lambda r: (r["rev"], r["lot"]))
    if not revs:
        return
    pen.y += 10
    pen.text(54, "Amendments", 10, bold=True); pen.y += 14
    for r in revs:
        lot = c.lots[r["lot"]]
        if r["kind"] == "result":
            row = lot["rows"][r["row"]]
            val = r["value"] + (f" {row['unit']}" if row["unit"] else "")
            what = f"{row['test']} result revised to {val}"
        else:
            what = f"{c.house['retest_label']} revised to {fmt_date(r['value'], c.house['date_style'])}"
        pen.text(54, f"Revision {r['rev']} ({fmt_date(c.issue + dt.timedelta(days=7 * r['rev']), c.house['date_style'])}),"
                     f" {c.house['lot_label']} {lot['lot_number']}: {what}.", 8.5)
        pen.y += 12


def draw_footer(pen, c):
    pen.y += 16
    signer = {"hengxin": "QA Manager: Li Wei", "nordvik": "Approved: Kari Solberg, Quality Assurance",
              "pradesh": "Checked by: QC Officer        Approved by: QA Head", "bluewater": "Released by: QC Release"}[c.house_key]
    pen.text(54, signer, 9); pen.y += 12
    pen.text(54, "This certificate was generated electronically and is valid without signature.", 7.5)


def result_cols(c, lot):
    cols = []
    for head, key, w in c.house["cols"]:
        if key == "loq" and not any(r["loq"] for r in lot["rows"]):
            continue
        cols.append((head, w, (lambda key: (lambda i: cell_text(lot["rows"][i], key)))(key)))
    return cols


def render(c: Cert, path, variant=None):
    """Draw the certificate with reportlab. variant: dict of drawing switches for routes."""
    v = variant or {}
    h = c.house
    pen = Pen(path, h, v.get("size"))
    bottom = v.get("page_bottom", pen.h - 70)
    ds = h["date_style"]

    state = {"lot": c.lots[0]}

    def new_page(rev=None, fresh=False):
        pen.new_page(v.get("cont_size"))
        if v.get("pre"):
            v["pre"](pen)
        draw_header(pen, c, continued=rev is None and not fresh, revision=rev)
        if rev is None and not fresh:
            lots = c.lots if h["multi"] == "columns" and len(c.lots) > 1 else [state["lot"]]
            pen.text(54, f"{h['lot_label']}: " + ", ".join(l["lot_number"] for l in lots), 9.5, bold=True)
            pen.y += 18

    if v.get("pre"):
        v["pre"](pen)
    draw_header(pen, c)
    stamp_ref = v.get("stamp_ref")             # ("lot"|"retest", stamp text)
    if h["multi"] == "columns" and len(c.lots) > 1:
        label_value(pen, h["product_label"], c.material[0])
        draw_extras(pen, c)
        pen.y += 4
        x = 54
        heads = [h["lot_label"], h["mfg_label"], "Re-test / Expiry"]
        for k, head in enumerate(heads):
            pen.text(x + [0, 110, 250][k], head, 9.5, bold=True)
        pen.y += 4; pen.line(54, 470, width=0.5); pen.y += 13
        for lot in c.lots:
            lab, val = lot_dates(c, lot)
            pen.text(54, lot["lot_number"], 9.5); pen.text(164, fmt_date(lot["mfg"], ds), 9.5)
            pen.text(304, f"{val} ({'re-test' if lot['retest'] else 'expiry'})", 9.5)
            pen.y += 13
        pen.y += 10
        rows0 = c.lots[0]["rows"]
        cols = [(h["cols"][0][0], 150, lambda i: (rows0[i]["test"], None)),
                (h["cols"][1][0], 110, lambda i: (rows0[i]["spec_text"], None))]
        for li, lot in enumerate(c.lots):
            cols.append((lot["lot_number"], 230 // len(c.lots) + 20,
                         (lambda lot: (lambda i: cell_text(lot["rows"][i], "result_unit")))(lot)))
        draw_table(pen, c, cols, None, len(rows0), bottom, new_page, order_reverse=v.get("scramble"),
                   break_at=len(rows0) // 2 + 1 if v.get("split") else None)
        draw_notes(pen, c)
    else:
        for li, lot in enumerate(c.lots):
            state["lot"] = lot
            if li > 0:
                if h["multi"] == "pages":
                    new_page(fresh=True)
                else:
                    pen.y += 16
                    if pen.y > bottom - 200:
                        new_page()
            if li == 0 or h["multi"] == "pages":
                label_value(pen, h["product_label"], c.material[0])
            if stamp_ref and li == 0:
                kind, _ = stamp_ref
                ov = {"lot_number": "see stamp"} if kind == "lot" else {"retest": "see stamp"}
                draw_identity_single(pen, c, lot, with_product=False, override=ov)
            else:
                draw_identity_single(pen, c, lot, with_product=False)
            if li == 0:
                draw_extras(pen, c)
            pen.y += 8
            draw_table(pen, c, result_cols(c, lot), None, len(lot["rows"]), bottom, new_page,
                       order_reverse=v.get("scramble"),
                       break_at=len(lot["rows"]) // 2 + 1 if v.get("split") and li == len(c.lots) - 1 else None)
            draw_notes(pen, c, li)
    if c.revisions and v.get("revisions") == "block":
        amendment_block(pen, c)
    draw_footer(pen, c)
    if c.revisions and v.get("revisions") == "page":
        by_lot = {}
        for r in sorted(c.revisions, key=lambda r: r["rev"]):
            by_lot.setdefault((r["lot"], r["rev"]), []).append(r)
        for (li, rev), rs in sorted(by_lot.items(), key=lambda kv: kv[0][1]):
            lot = copy.deepcopy(c.lots[li])
            ov = {}
            for r in rs:
                if r["kind"] == "result":
                    lot["rows"][r["row"]]["result"] = r["value"]
                else:
                    ov["retest"] = r["value"]
                    lot["retest"] = r["value"]
            new_page(rev=rev)
            pen.text(54, f"This revision replaces the values below for {h['lot_label']} {lot['lot_number']}.", 9)
            pen.y += 18
            label_value(pen, h["product_label"], c.material[0])
            draw_identity_single(pen, c, lot, with_product=False)
            pen.y += 8
            draw_table(pen, c, result_cols(c, lot), None, len(lot["rows"]), bottom, new_page)
            draw_footer(pen, c)
    if v.get("post"):
        v["post"](pen)
    pen.save()
    return pen


# ------------------------------------------------------------------ production routes

SCAN_ROUTES = {"scan_ocr", "scan_wrong_ocr", "scan_no_ocr", "scan_rotated"}


def set_meta(path, meta):
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for k, val in meta.items():
            pdf.docinfo[pikepdf.Name("/" + k)] = val
        pdf.save(path)


def rasterize(pdf_path, dpi=300, color=False):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png"] + ([] if color else ["-gray"]) +
                       [pdf_path, os.path.join(td, "p")], check=True)
        return [Image.open(os.path.join(td, f)).copy() for f in sorted(os.listdir(td))]


def scan_sim(im, rnd):
    im = im.convert("L")
    im = im.rotate(rnd.uniform(-0.5, 0.5), resample=Image.BICUBIC, expand=False, fillcolor=250)
    noisy = Image.effect_noise(im.size, 7).convert("L")
    im = Image.blend(im, noisy, 0.07)
    return im.filter(ImageFilter.GaussianBlur(0.45))


def jpeg_bytes(im, q=82):
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=q)
    return b.getvalue()


def image_pdf(images, path, page_size, rotate=0):
    cv = rl_canvas.Canvas(path, pagesize=page_size, invariant=1)
    for im in images:
        w, h = page_size
        if im.width > im.height and w < h:
            w, h = h, w
            cv.setPageSize((w, h))
        if rotate:
            cv.setPageSize((h, w))
            cv.drawImage(ImageReader(io.BytesIO(jpeg_bytes(im))), 0, 0, h, w)
        else:
            cv.drawImage(ImageReader(io.BytesIO(jpeg_bytes(im))), 0, 0, w, h)
        cv.showPage()
    cv.save()
    if rotate:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for p in pdf.pages:
                p.Rotate = rotate
            pdf.save(path)


def ocr_layer(src, dst):
    subprocess.run(["ocrmypdf", "-q", "--output-type", "pdf", "--optimize", "0", "-l", "eng", src, dst],
                   check=True)


def replace_page_images(path, images):
    """Swap each page's scanned image for another raster of the same size (OCR layer stays)."""
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for page, im in zip(pdf.pages, images):
            for name, xo in page.Resources.XObject.items():
                if xo.get("/Subtype") == "/Image":
                    xo.write(jpeg_bytes(im), filter=pikepdf.Name.DCTDecode)
                    xo.Width, xo.Height = im.width, im.height
                    xo.ColorSpace = pikepdf.Name.DeviceGray
                    xo.BitsPerComponent = 8
                    for k in ("/DecodeParms", "/SMask"):
                        if k in xo:
                            del xo[k]
        pdf.save(path)


def stamp_image(text, rnd):
    font = ImageFont.truetype(STAMP_FONT, 44)
    tw = int(font.getlength(text)) + 50
    im = Image.new("RGBA", (tw, 100), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([3, 3, tw - 4, 96], outline=(150, 20, 30, 230), width=5)
    d.text((24, 22), text, fill=(150, 20, 30, 230), font=font)
    return im.rotate(rnd.uniform(-4, 4), expand=True, resample=Image.BICUBIC)


def freetext_correction(path, page_index, rect, text):
    """An opaque FreeText annotation over a printed value, as a reviewer's correction."""
    x0, y0, x1, y1 = rect
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[page_index]
        ap = pikepdf.Stream(pdf, (f"q 1 1 1 rg 0 0 {x1 - x0:.2f} {y1 - y0:.2f} re f 0 0 0.6 rg BT /Helv 9.5 Tf 2 "
                                  f"{(y1 - y0) * 0.28:.2f} Td ({text}) Tj ET Q").encode())
        ap.Type = pikepdf.Name.XObject
        ap.Subtype = pikepdf.Name.Form
        ap.BBox = [0, 0, x1 - x0, y1 - y0]
        ap.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
            Encoding=pikepdf.Name.WinAnsiEncoding)))
        annot = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.FreeText, Rect=[x0, y0, x1, y1],
            Contents=pikepdf.String(text), DA=pikepdf.String("0 0 0.6 rg /Helv 9.5 Tf"), F=4,
            T=pikepdf.String("QA reviewer"), AP=pikepdf.Dictionary(N=ap)))
        if "/Annots" not in page:
            page.Annots = pdf.make_indirect(pikepdf.Array())
        page.Annots.append(annot)
        pdf.save(path)


def find_word(path, word, page_index=0, occurrence=-1):
    """Position of a printed string, in PDF user space (bottom-left origin)."""
    import fitz
    doc = fitz.open(path)
    page = doc[page_index]
    hits = page.search_for(word)
    r = hits[occurrence]
    h = page.rect.height
    return (r.x0, h - r.y1, r.x1, h - r.y0)


def build_form(c: Cert, path, mismatch):
    """A fillable form (reportlab AcroForm): identity and results are field values with appearances."""
    h = c.house
    pen = Pen(path, h)
    draw_header(pen, c)
    lot = c.lots[0]
    form = pen.c.acroForm
    ds = h["date_style"]

    def field(label, name, value, x=54, w=210):
        pen.text(x, label + ":", 10, bold=True)
        form.textfield(name=name, value=value, x=x + 120, y=pen.h - pen.y - 4, width=w, height=15,
                       fontName="Helvetica", fontSize=10, borderWidth=0.5, borderColor=None,
                       fillColor=None, textColor=None, forceBorder=False)
        pen.y += 19

    field(h["product_label"], "product", c.material[0], w=260)
    field(h["lot_label"], "lot", lot["lot_number"])
    field(h["mfg_label"], "mfg", fmt_date(lot["mfg"], ds))
    lab, val = lot_dates(c, lot)
    field(lab, "d2", val)
    draw_extras(pen, c)
    pen.y += 10
    x0 = 54
    heads = [("Analysis", 0), ("Limit", 175), ("Result", 300), ("Units", 400)]
    for head, dx in heads:
        pen.text(x0 + dx + 3, head, 9.5, bold=True)
    pen.y += 5; pen.line(x0, x0 + 470, width=0.8); pen.y += 14
    for i, r in enumerate(lot["rows"]):
        pen.text(x0 + 3, r["test"], 9.5)
        pen.text(x0 + 178, r["spec_text"], 9.5)
        wide = len(r["result"] or "") > 12
        form.textfield(name=f"result_{i}", value=(r["result"] or "") + ("*" if r["marker"] else ""), x=x0 + 300, y=pen.h - pen.y - 4,
                       width=170 if wide else 95, height=14, fontName="Helvetica", fontSize=9.5, borderWidth=0.4,
                       borderColor=None, fillColor=None, textColor=None, forceBorder=False)
        if not wide:
            pen.text(x0 + 403, r["unit"] or "", 9.5)
        pen.y += 18
    draw_notes(pen, c)
    draw_footer(pen, c)
    pen.save()
    if mismatch:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for annot in pdf.pages[0].get("/Annots", []):
                name = str(annot.get("/T", ""))
                v = str(annot.get("/V", ""))
                if name.startswith("result_") and v.replace(".", "").isdigit():
                    annot.V = pikepdf.String(str(round_to(D(v) * 3 + 1, 2)))
                if name == "lot":
                    annot.V = pikepdf.String(lot["lot_number"][0] + "000000")
            if "/AcroForm" in pdf.Root:
                pdf.Root.AcroForm.NeedAppearances = False
            pdf.save(path)


def produce(c: Cert, path, rnd):
    """Render the certificate through its production route. Returns notes for the manifest."""
    route = c.route
    h = c.house
    td = tempfile.mkdtemp()
    base = os.path.join(td, "base.pdf")
    variant = {"revisions": c.revision_style} if c.revisions else {}
    note = route
    if "continuation" in c.features:
        variant["split"] = True
        if "a4_continuation" in c.features:
            variant["cont_size"] = LETTER if h["size"] == A4 else A4
    if "scramble" in c.features:
        variant["scramble"] = True
    if "watermark" in c.features:
        def pre(pen):
            pen.c.saveState()
            pen.c.setFillColorRGB(0.86, 0.86, 0.86)
            pen.c.setFont(h["font"] + "-Bold", 120)
            pen.c.translate(pen.w / 2, pen.h / 2)
            pen.c.rotate(35)
            pen.c.drawCentredString(0, -40, "COPY")
            pen.c.restoreState()
        variant["pre"] = pre
    stamp = None
    if "stamp_lot" in c.features or "stamp_retest" in c.features:
        lot = c.lots[0]
        if "stamp_lot" in c.features:
            stamp = ("lot", f"LOT {lot['lot_number']}")
        else:
            d = lot["retest"] or lot["expiry"]
            stamp = ("retest", f"RETEST {d.strftime('%d %b %Y').upper()}")
        variant["stamp_ref"] = stamp
        simg = stamp_image(stamp[1], rnd)
        # the stamp goes on page 1 next to the identity block: drawn through 'pre' on the first page only
        prev = variant.get("pre")
        state = {"done": False}

        def pre_stamp(pen, simg=simg, prev=prev):
            if prev:
                prev(pen)
            if not state["done"]:
                state["done"] = True
                w = simg.width * 0.36
                pen.image(simg, pen.w - 54 - w, 112, w, simg.height * 0.36)
        variant["pre"] = pre_stamp
    if "white_decoy" in c.features:
        decoy = f"{c.lots[0]['lot_number'][0]}{rnd.randint(100000, 999999)}"

        def post(pen, decoy=decoy):
            pen.text(54, f"{h['lot_label']}: {decoy}", 9, y=pen.h - 40, fill=(1, 1, 1))
        variant["post"] = post
        note += f" white decoy lot {decoy}"

    if route == "form" or route == "form_mismatch":
        build_form(c, path, mismatch=route == "form_mismatch")
        set_meta(path, h["meta"])
        shutil.rmtree(td)
        return note
    render(c, base, variant)
    if route == "digital":
        shutil.copy(base, path)
        set_meta(path, h["meta"])
    elif route == "distilled":
        subprocess.run(["gs", "-q", "-o", path, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6", base], check=True)
        set_meta(path, {k: v for k, v in h["meta"].items() if k != "Producer"})
    elif route == "outlined":
        subprocess.run(["gs", "-q", "-o", path, "-sDEVICE=pdfwrite", "-dNoOutputFonts", base], check=True)
        set_meta(path, {"Creator": "Adobe Illustrator 27.0 (Windows)"})
    elif route in SCAN_ROUTES:
        raws = rasterize(base)
        seeds = [rnd.random() for _ in raws]
        pages = [scan_sim(im, random.Random(sd)) for im, sd in zip(raws, seeds)]
        size = c.house["size"]
        if route == "scan_rotated":
            # fed sideways: the page displays turned a quarter, as the scanner wrote it
            pages = [im.rotate(90, expand=True) for im in pages]
            image_pdf(pages, path, (size[1], size[0]))
            set_meta(path, h["meta"])
        elif route == "scan_no_ocr":
            image_pdf(pages, path, size)
            set_meta(path, h["meta"])
        else:
            if route == "scan_wrong_ocr":
                wrong = copy.deepcopy(c)
                for lot in wrong.lots:
                    for r in lot["rows"]:
                        if r["result"] and any(ch.isdigit() for ch in r["result"]) and rnd.random() < 0.6:
                            r["result"] = r["result"].translate(str.maketrans("0123456789", "8765432109"))
                wbase = os.path.join(td, "wrong.pdf")
                render(wrong, wbase, variant)
                ocr_src = [scan_sim(im, random.Random(sd)) for im, sd in zip(rasterize(wbase), seeds)]
                note += ": OCR layer read from altered values; the image is right"
            else:
                ocr_src = pages
            img = os.path.join(td, "img.pdf")
            image_pdf(ocr_src, img, size)
            set_meta(img, h["meta"])
            ocr_layer(img, path)
            if route == "scan_wrong_ocr":
                replace_page_images(path, pages)
    else:
        raise ValueError(route)
    if "annot_correction" in c.features:
        lot = c.lots[0]
        cand = [r for r in lot["rows"] if r["result"] and r["result"].replace(".", "").isdigit() and not r["marker"]]
        r = rnd.choice(cand)
        true = r["result"]
        # the printed value is wrong; draw the certificate again with it, then correct it with the annotation
        wrong = str(round_to(D(true) * 10 + 1, max(decimals(true), 1)))
        r["result"] = wrong
        render(c, base, variant)
        shutil.copy(base, path)
        set_meta(path, h["meta"])
        x0, y0, x1, y1 = find_word(path, wrong)
        r["result"] = true
        freetext_correction(path, 0, (x0 - 2, y0 - 2.5, x0 + 70, y1 + 2), true)
        note += f": printed {wrong} corrected by annotation to {true} for {r['test']}"
    shutil.rmtree(td)
    return note


# ------------------------------------------------------------------ corpus

SAMPLES = [
    # id, house, route, lots, features
    ("s01", "hengxin", "digital", 2, {"alias"}),
    ("s02", "nordvik", "distilled", 2, {"units", "round_metal"}),
    ("s03", "pradesh", "scan_ocr", 1, {"nd_loq_col"}),
    ("s04", "bluewater", "form", 1, {"expired"}),
    ("s05", "hengxin", "digital", 1, {"rev_result", "rev_block", "continuation"}),
    ("s06", "nordvik", "distilled", 1, {"marker", "nd_loq_note"}),
    ("s07", "pradesh", "scan_ocr", 2, {"stamp_lot", "round_range"}),
]
HIDDEN = [
    ("h01", "hengxin", "digital", 3, {"alias", "units", "round_metal", "continuation"}),
    ("h02", "hengxin", "digital", 1, {"rev_twice", "rev_block", "fail"}),
    ("h03", "hengxin", "digital", 2, {"nd_loq_note", "rev_result", "rev_page"}),
    ("h04", "pradesh", "outlined", 1, {"alias", "round_min"}),
    ("h05", "hengxin", "digital", 1, {"white_decoy", "expired"}),
    ("h06", "hengxin", "digital", 2, {"marker", "units_bad"}),
    ("h07", "hengxin", "digital", 1, {"annot_correction", "nd_loq_high"}),
    ("h08", "hengxin", "digital", 2, {"scramble", "round_range", "round_fail"}),
    ("h09", "nordvik", "distilled", 3, {"alias", "nd_no_loq"}),
    ("h10", "nordvik", "distilled", 2, {"rev_extends", "rev_page"}),
    ("h11", "nordvik", "distilled", 1, {"units", "round_metal", "round_fail", "marker"}),
    ("h12", "nordvik", "distilled", 2, {"continuation", "a4_continuation", "nd_loq_note", "wrap"}),
    ("h13", "nordvik", "outlined", 1, {"rev_result", "rev_block", "alias"}),
    ("h14", "nordvik", "distilled", 1, {"watermark", "missing", "alias"}),
    ("h15", "nordvik", "distilled", 2, {"stamp_retest", "expired"}),
    ("h16", "pradesh", "scan_wrong_ocr", 1, {"nd_loq_col", "round_min"}),
    ("h17", "pradesh", "scan_no_ocr", 2, {"alias", "units", "round_metal"}),
    ("h18", "pradesh", "scan_rotated", 1, {"stamp_lot", "fail"}),
    ("h19", "pradesh", "scan_ocr", 2, {"rev_result", "rev_block", "nd_loq_col"}),
    ("h20", "pradesh", "scan_ocr", 1, {"expired", "wrap"}),
    ("h21", "pradesh", "scan_no_ocr", 1, {"marker", "round_range"}),
    ("h22", "pradesh", "scan_wrong_ocr", 2, {"units", "units_bad"}),
    ("h23", "bluewater", "form_mismatch", 1, {"alias", "round_metal"}),
    ("h24", "bluewater", "form", 1, {"nd_loq_note", "marker"}),
    ("h25", "bluewater", "scan_ocr", 1, {"rev_extends", "rev_block"}),
    ("h26", "bluewater", "digital", 2, {"units", "nd_loq_high"}),
    ("h27", "bluewater", "outlined", 1, {"stamp_retest", "round_min", "round_fail"}),
    ("h28", "bluewater", "form_mismatch", 1, {"missing", "units"}),
    ("h29", "bluewater", "digital", 1, {"scramble", "rev_twice", "rev_block"}),
    ("h30", "bluewater", "digital", 2, {"watermark", "alias", "wrap", "continuation"}),
]


def build(entry, rnd, outdir):
    cid, house, route, n_lots, feats = entry
    c = Cert(cid, house, rnd, n_lots, feats, route)
    c.revision_style = "page" if "rev_page" in feats else "block"
    apply_features(c)
    path = os.path.join(outdir, f"{cid}.pdf")
    note = produce(c, path, rnd)
    truth = c.truth()
    with open(os.path.join(outdir, f"{cid}.spec.json"), "w") as f:
        json.dump(c.spec, f, indent=1, ensure_ascii=False)
    with open(os.path.join(outdir, f"{cid}.truth.json"), "w") as f:
        json.dump(truth, f, indent=1, ensure_ascii=False)
    return {"id": cid, "house": house, "route": route, "features": sorted(feats), "notes": note,
            "lots": len(truth["lots"]), "dispositions": [l["disposition"] for l in truth["lots"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    manifest = {"samples": [], "hidden": []}
    for group, entries in (("samples", SAMPLES), ("hidden", HIDDEN)):
        d = os.path.join(a.outdir, group)
        os.makedirs(d, exist_ok=True)
        for e in entries:
            rnd = random.Random(f"{a.seed}-{e[0]}")   # each certificate has its own stream
            if only and e[0] not in only:
                continue
            manifest[group].append(build(e, rnd, d))
    with open(os.path.join(a.outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    for group in manifest:
        for m in manifest[group]:
            print(m["id"], m["house"], m["route"], m["dispositions"], m["features"])


if __name__ == "__main__":
    main()
