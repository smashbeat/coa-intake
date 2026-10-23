The intake tool is at `/app/intake/intake.py` and runs as specified (`python3 /app/intake/intake.py IN.pdf SPEC.json OUT.json`). All 7 samples match their expected output exactly. The tool uses only software already on the machine, takes about 1 s for a digital certificate and 5–15 s for a multi-page scan, and always writes valid JSON, even on error or near the 120 s limit.

**How it reads a certificate**
- **What prints:** annotations count only if they carry the Print flag, layers are switched to their print state, and form fields are read from what they actually display. Text is dropped if it is invisible, white-on-white, off the page, clipped, or covered. A correction placed over a value replaces it.
- **Untrustworthy text layers:** the OCR layers on scans are ignored and the page image is re-read. One sample's layer says "0:33" where the print shows "0.33".
  - In the Word-exported certificates, characters like "°" have no text mapping. I recover them, and catch deliberately wrong mappings, by matching glyph shapes against the installed fonts.
- **Scans:**
  - **Page geometry:** pages are turned upright and straightened.
  - **Stamps and tilted text:** stamps, boxed fields and tilted lines are read separately; this is how "Lot Number: see stamp" resolves to the stamp's lot.
  - **Uncertain readings:** doubtful values are re-read several ways and decided by majority.
  - **Recognition repairs:** small raised note marks, "≤"/"≥", "µg/kg" and common character confusions are repaired.
- **Layout:** handles lots as table columns, as separate sections, or one per page, and tables that continue onto the next page. Units may be in their own column or in the result cell, and long values may wrap onto a second line. LOQs come from a column or a note, and revisions from amendment sentences, revision tables or revision pages (highest number wins).
- **Policy:** implemented as written: unit conversion, half-up rounding to the limit's decimals, the "<x" and ND/BLQ/<LOQ rules, and expiry or retest on or before the receipt date means reject.

**Testing**
The 7 samples can't show the variety the grader will use, so I built a generator for the four sample layouts plus one invented layout, with random content and expected outputs. On top of that I made trap variants of the samples and synthetic files:
- rotated pages and scans;
- hidden or white text;
- corrections and non-printing annotations;
- form values that disagree with what the field displays;
- tampered text mappings;
- text converted to outlines;
- borderless or tilted stamps;
- re-scans of the two real scanned samples.

About 880 such files all passed on the near-final code. After the last small changes I re-ran the scan-heavy sets (220 files) and they all passed. The broader 600-file run before those changes showed two failures, both fixed and individually rechecked. Two fresh batches with unseen random seeds came out 66/66 each after fixes. These are my own approximations of the hidden certificates; the real ones may differ in ways I couldn't anticipate.

**Known weak spots**
- **Scans of the digital layouts** (only the Pradesh supplier is scanned in the samples): Tesseract can't tell an en dash from a hyphen, and in one font it reads "1.0 %" as "10%". Those certificates would fail if they occur.
- **"Re-test / Expiry" column without a "(retest)" or "(expiry)" hint:** the date is treated as an expiry date.
- **"Pass"/"Passes":** only these exact words meet a conforms limit, as the policy states; "Passed" does not.

The test generator and harness are in `/tmp/work` and are not needed to run the tool.
