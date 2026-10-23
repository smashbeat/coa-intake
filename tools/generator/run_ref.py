"""Run the reference on a corpus dir (samples/ and hidden/) and compare with truth. In-container."""
import json, os, subprocess, sys, time
sys.path.insert(0, "/work")
from compare import compare_files
root, only = sys.argv[1], (sys.argv[2].split(",") if len(sys.argv) > 2 else None)
bad = 0
for group in ("samples", "hidden"):
    d = os.path.join(root, group)
    for f in sorted(os.listdir(d)):
        if not f.endswith(".pdf"):
            continue
        cid = f[:-4]
        if only and cid not in only:
            continue
        out = f"/tmp/{cid}.out.json"
        t = time.time()
        p = subprocess.run(["python3", "/work/solution/intake.py", os.path.join(d, f), os.path.join(d, cid + ".spec.json"), out],
                           capture_output=True, text=True, timeout=300)
        el = time.time() - t
        diffs = compare_files(out, os.path.join(d, cid + ".truth.json")) if p.returncode == 0 else [p.stderr[-400:]]
        bad += bool(diffs)
        print(f"{cid} {'PASS' if not diffs else 'FAIL'} {el:.0f}s " + "; ".join(diffs[:4]), flush=True)
print("failed:", bad)
