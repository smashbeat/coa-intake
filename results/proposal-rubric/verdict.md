Problem statement: The agent must write a command-line tool, `/app/intake/intake.py IN.pdf SPEC.json OUT.json`. It reads a supplier's certificate of analysis (CoA) PDF and the house specification for that material, then writes structured JSON: each lot's identity fields, every test result row, and a disposition (accepted, rejected or held). A nine-rule policy file defines the fields and the disposition. The PDFs come from four synthetic "supplier styles" and several production routes:

- native ReportLab exports
- Ghostscript output converted to outlines (no text layer)
- OCRmyPDF scans whose OCR layer may be wrong
- image-only scans, some rotated
- fillable forms whose stored value differs from what prints
- documents with white or hidden text, watermarks, stamp images, correction overlays, multi-lot layouts, continuation pages, and revision or amendment blocks

The tool has to read what actually prints, not just the text layer. It then applies the policy: revisions with the highest number winning, test-name synonyms from the spec, unit conversion with half-up rounding to the precision of the house limit, ND/<LOQ handling, footnote stripping, and rejection on expiry/retest dates. The agent gets 7 worked samples. Grading uses 30 hidden certificates drawn from the same generator, each scored all-or-nothing, and the reward is 1 only if all 30 pass.

**Verifiable**

Positives:
- The output is structured JSON compared field by field with a documented normalization (NFKC, casefold, whitespace removal). Nothing is subjective and no LLM judge is used.
- The expected output comes from the generator's ground truth, not from the reference tool, so the reference's OCR quirks don't leak into the answer key.
- The isolation is sound. The tool runs as `nobody`, `/tests` is root-only, stray processes are killed between certificates, and there is a per-certificate timeout.
- Tesseract and rendering are deterministic for fixed inputs and a fixed container, so re-running the verifier should give the same result.

Negatives:
- Because the ground truth comes from the generator, every hidden certificate must actually be legible enough for the printed value to be recovered without ambiguity. Two cases need checking: a degraded scan where a "1" and a "7" are truly indistinguishable, and a correction overlay that partly hides the original value. In either case the verifier would be "correct" against an answer no reader could reach. The reference scoring 185/185 across five seeds is strong evidence this doesn't happen in practice, but the author should be sure the generator can't produce such cases.
- The agent's tool is run under a 120 s limit on possibly different hardware. Since the reference's worst case is 18 s, this is comfortable.

Judgement: Strong Accept

**Well-specified**

Positives:
- The rules live in a single policy document, and the proposal's examples (149 ppb vs 155 ppb against 0.15 ppm, LOQ printed vs not printed, revision numbering, continuation pages) suggest the policy is concrete and testable.
- "Value is what prints on the page, read upright" is a clear principle that settles all the text-layer-versus-render conflicts in one stroke.
- The output keys and comparison normalization are stated.

Negatives:
- The hidden set "combines two to four rules with a route the samples show separately." That is fine in principle, but it means the agent must generalize from 7 samples to combinations it has never seen. Every interaction has to be decided by the policy text, not by the generator's conventions. Some interactions could easily be underdetermined:
  - Does a stamp-image retest date count as a "revision" with a number?
  - What happens when an amendment block revises a row that a continuation page also repeats?
  - Does a correction note drawn over a value interact with revision numbering?
- Layout semantics such as "a correction note drawn over a value replaces it" need a precise definition: which value does a note apply to, and how does the reader know?
- The task stacks many distinct phenomena: white text, watermarks, scrambled order, outline fonts, form-appearance mismatch, rotation, stamps, overlays, synonyms, units, LOQ, footnotes, revisions, continuations, multi-lot layouts and four supplier styles. That is close to the "hard primarily because of many corner cases" failure mode the rubric warns about. Counting against that worry: each item is a real-world reading problem, not an arbitrary rule, and the set is bounded by a nine-rule policy.
- The bar is all 30 certificates passing with every field correct. Any leftover ambiguity in the policy becomes a guaranteed failure, so the policy has to be airtight.

Judgement: Accept (contingent on the policy really pinning down rule interactions; auditors should read `policy.md` against the hidden combinations carefully)

**Solvable**

Positives:
- A reference implementation exists. It is described concretely (render plus Tesseract OSD plus OCR, a text layer trusted only where the render has ink, multi-crop voting for uncertain digits, column-position table parsing, revision collection and application).
- It scores 30/30 on the hidden set and 185/185 across five generator seeds, with a large timing margin.
- Everything needed (Tesseract, a renderer, PDF libraries) ships in the container.

Negatives:
- The rubric says an expert who knows the approach should be able to implement it in a few hours. A robust OCR-plus-voting reader, a layout-aware table parser and the policy engine together are probably a long day or more of work for an expert, even with the approach known. It is borderline, but the 8-hour agent budget is consistent with it.
- The 185/185 result is on the author's own generator. That shows the reference matches the generator, not that a reasonable independent reading of the policy does. This matters more for well-specification than for solvability.

Judgement: Accept

**Difficult**

Positives:
- This is real, hard document engineering. The agent has to stop trusting the PDF text layer and build a render-first pipeline that reconciles OCR with embedded text, handles pages with no text layer and rotated pages, and reads stamp images.
- The scans use fonts the container doesn't have, which blocks template matching.
- Exact-match grading on numbers and lot codes makes OCR error rates matter a great deal. A pipeline that is 99% accurate per field will fail somewhere across 30 multi-lot certificates.
- On top of the reading, the agent must parse tables by column position across four layouts and apply revision, unit and rounding logic correctly.
- Experienced document-AI or IDP engineers find this kind of work genuinely hard. Frontier agents will tend to take the text layer at face value and fail on the adversarial routes.

Negatives:
- Part of the difficulty is volume: many distinct traps, each individually manageable. Reviewers may see the hidden-text, watermark and white-text traps as a checklist rather than deep difficulty.
- Requiring all 30 to pass amplifies small, uninteresting OCR misreads into total failure. That measures robustness, which is legitimate, but it can make the task feel brittle rather than hard.

Judgement: Accept

**Interesting**

Positives:
- CoA intake is a real, paid job in regulated supplement and pharma manufacturing (cGMP incoming-material verification). Automating it reliably has clear economic value.
- More broadly, getting exact extraction from messy real-world PDFs is one of the most common commercial document-AI problems.
- The "text layer lies" theme is a real and underappreciated failure mode.

Negatives:
- The documents are synthetic. Some reviewers will ask whether the four supplier styles carry over to real CoAs, but the production routes are realistic.

Judgement: Strong Accept

**Outcome-verified**

Positives:
- Only the output JSON is graded. The agent can choose any approach: OCR engine, heuristics, text-layer use, whatever works.
- The only constraints are mechanistic: the shipped software and the time limit.

Negatives:
- None significant. The policy dictates output semantics, not process.

Judgement: Strong Accept

**Final analysis**

This is a well-built, realistic, outcome-verified task with a deterministic, ground-truth-backed verifier and a strong reference result (185/185 across seeds). The difficulty is real: reading what actually prints, rather than what a PDF library extracts, across adversarial but realistic production routes, then applying a non-trivial policy with exact numeric rules.

The main risks are about specification and difficulty character, not viability:

1. **Corner-case accumulation.** The number of distinct traps puts the task near the "hard because of many corner cases" boundary.
2. **Rule interactions.** Rules that the 7 samples show only separately must be fully settled by `policy.md`, or the all-30 bar turns any ambiguity into certain failure.
3. **Implementation size.** The reference implementation is likely more than "a few hours" even for an expert.

None of these is disqualifying. They are what the Phase 2 implementation review will need to check.

Decision: Accept
