I've built the intake tool at `/app/intake/intake.py`. It produces exactly the expected output on all 7 sample certificates. It also passes on about 250 test certificates I generated myself, with one exception noted at the end.

Those generated certificates copy the four sample suppliers' layouts with random materials, tests, lots and dates. They cover scans of every layout (with and without a text layer, skewed, blurred, upside-down and sideways), stamps that the "see stamp" label points to, and corrections pasted over values. They also include hidden or white text, form fields whose stored value differs from what's shown, revision pages and amendment blocks, and tables that run onto a second page. Since I wrote the generator from the samples, they show what the tool handles, not how it will score on your certificates.

Runtime is about 0.4 s for digital certificates and 4–17 s for scans, against the 120 s limit. After 60 s it stops re-checking scanned text, as a safety margin. On any internal error it still writes a valid `{"lots": []}`.

**How it reads "what prints":**
- Annotations and form fields without the print flag are discarded; everything that prints is merged into the page and read as shown.
- Text is kept only if it actually shows in the rendered page. White text, text hidden in the file, text off the page and text covered by a later box are ignored; where a correction is placed over a value, the correction wins.
- Pages are turned to whatever orientation makes the text upright.
- Word exports turn special characters like `° ≤ ≥ µ ± –` into codes that can't be read as text. The tool identifies them from their printed shapes instead.

**Scanned pages:**
- The tool does its own OCR and ignores any existing text layer, which can be wrong (sample s07's layer reads `0:33` for `0.33`).
- Each cell is read three ways and the reading that best fits the printed letter shapes is kept. Stamps in a box are read separately, and small raised note marks are removed.
- Tesseract cannot output `≤ ≥ µ`, so those are recognised from their shapes.
- Names that differ only by OCR look-alikes (e.g. `lodide` vs `Iodide`) are matched to the house spec's material and test names or to the four known suppliers.

**Gaps:**
- **Stamps over table values:** a coloured stamp printed directly on top of table values still garbles those cells. This is the one case that still fails, and it is constructed: I placed a stamp over the Unit column myself; s07's stamp sits in empty space.
- **Hengxin font:** the real scan font (Pradesh's) was tested only on the two samples under extra skew, blur and compression (all passed). Hengxin specs use `≤`/`≥`/`~`; if those certificates are ever scanned, reading those symbols is the shakiest part.
- **Judgement calls:**
  - A test name must match a house name exactly, per the policy, so "Lead (Pb) (ICP)" won't match "Lead (Pb)".
  - A text result such as "Complies" under a numeric limit counts as no result, giving `incomplete` rather than `reject`.
  - Comma decimals (`0,05`) are read as numbers.

`/app/intake/glyphrefs.npz` sits next to the script and holds the character shapes used for that recognition. If it's missing it is rebuilt from the installed fonts in under a second.
