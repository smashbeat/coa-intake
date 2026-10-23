I've built the intake tool at `/app/intake/intake.py`, and it gets all seven sample certificates exactly right. It's a single self-contained file that uses only software already in the container (PyMuPDF, OpenCV, the tesseract command line). It runs in 1–8 s per sample; the slowest case I measured was a 5-page scan at about 16 s, and it scales back its OCR work if it ever gets close to the 120 s limit.

**How it reads a certificate**
- **Only what prints.** It records exactly what MuPDF draws in print mode, so non-printing or hidden annotations and non-printing layers drop out. It also drops glyphs that can't be seen: invisible OCR layers, white-on-white or clipped text, text covered by a correction box, struck-through values, and watermarks.
- **"The print is right."** Form-field values that differ from what the field displays are ignored, as are OCR text layers. Symbols whose text mapping is missing or lying (such as `≤` or `°`) are identified from the glyph shape instead.
- **Scans.** It does its own OCR rather than trusting the embedded OCR layer, which in s07 says `0:33` where the page prints `0.33`. It detects page orientation, straightens the scan and removes table lines, reads each page three ways and votes. Tilted stamps such as `LOT P351323` are found and re-read separately, and "see stamp" labels resolve to the stamp's value.
- **Layout.** It handles key-value headers, results tables (including one column per lot), separate lot tables, stacked lots, one lot per page, continuation pages, wrapped cells, note marks, and LOQ given in a column or a note.
- **Revisions and evaluation.** Revisions can come from an amendment block, a revision page or a revision table; the highest number wins. Unit conversion, rounding and the disposition rules follow `/app/policy.md`.

**Testing**
Because the graded certificates are unseen, I wrote a generator that mimics the four sample suppliers, plus a randomized generic layout. It adds the traps the policy describes: correction overlays, decoy text, annotations, form-value mismatches, rotations, watermarks, stamps tilted up to 20°, revisions, scans with and without OCR layers, and multi-page or multi-lot certificates. The final run passed 513 of 515 certificates, and a fresh batch of 60 passed 60/60. The two failures are deliberately extreme scans (200 dpi, heavy blur) where tesseract can't read bold labels; the real sample scans are much cleaner.

**Choices where the policy is open**
- A non-numeric result against a numeric limit (e.g. "Complies" for lead) counts as no result, so the lot is incomplete rather than rejected.
- If a certificate prints both a retest and an expiry date, both are output.
- An OCR-read name that is nearly identical to the house material name, a house test alias, or one of the four known suppliers is replaced with that spelling.
- Tables are assumed to put a wrapped cell's text on its first line, as in the samples. Without row lines, other vertical alignments could mis-assign the wrapped text.
