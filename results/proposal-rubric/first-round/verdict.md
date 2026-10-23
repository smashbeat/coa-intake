Problem statement: The agent writes a command-line tool, `/app/intake/intake.py IN.pdf SPEC.json OUT.json`. It reads one supplier certificate of analysis (CoA) in PDF form plus the house specification for that material, and writes JSON containing every lot's identity fields, every result row and a disposition (accept, reject or hold), as defined by a nine-rule policy file. The PDFs are synthetic. They come from four supplier styles and several production routes: native ReportLab exports, Ghostscript outline conversions, OCRmyPDF scans with an imperfect text layer, image-only scans in fonts the container doesn't have, a rotated scan, and fillable forms whose stored values differ from what they print. Some contain traps: white text, watermarks, scrambled text order, image stamps that carry lot numbers or new dates, correction notes drawn over values, continuation pages and revision blocks. The policy covers revision precedence, test synonyms, ND/<LOQ handling, unit conversion with half-up rounding to the house limit's decimals, footnote marks, and rejecting lots whose retest or expiry date falls on or before receipt. The agent gets 7 samples with expected output. Grading uses 30 hidden certificates, each compared exactly after NFKC normalisation, case folding and whitespace removal. The reward is 1 only if all 30 pass.

**Verifiable**

Positives:
- The expected output comes from the generator that drew each certificate, not from the reference tool, so ground truth isn't contaminated by a solver's errors.
- Comparison is exact after a simple, stated normalisation. No LLM judge is involved.
- The tool runs as `nobody` with `/tests` locked to root, under a timeout, and stray processes are killed between certificates. That is a sound anti-tampering design.
- The whole process is deterministic: fixed PDFs, fixed expected JSON, one test per certificate.

Negatives:
- Ground truth is "what prints on the page", and the generator knows that by construction. But the grader can only be fair if every printed value is unambiguous at the rendered resolution. If a degraded scan makes an `O`/`0` or `l`/`1` in a lot code genuinely unreadable, the generator's answer is right and no reader could reproduce it. The reference passing 185/185 is good evidence against this, but only for the reference's own pipeline.

Judgement: Accept

**Well-specified**

Positives:
- A written nine-rule policy defines fields, precedence, conversion, rounding and disposition. The proposal gives worked examples (149 ppb vs. 155 ppb against 0.15 ppm).
- String normalisation is stated, so formatting slack is explicit.
- Seven samples show the output schema and most rules.

Negatives:
- The hidden set is defined only as "other certificates from the same kinds of sources." The agent has to infer the generator's distribution from 7 samples. Any hidden feature that the samples don't show and the policy doesn't spell out becomes a guessing game. Examples include an unlisted synonym for a test name, a new way a stamp carries a date, or how a wrapped cell joins. Whether test synonyms are enumerated in the spec or left to domain knowledge matters a great deal and isn't clear here.
- The task is built on a long tail of interacting cases: revision over continuation, LOQ from a column vs. from a note, stamp vs. typed date, form value vs. appearance. The rubric warns that tasks like this are prone to specification gaps, because every corner case the verifier exercises must be documented.
- Two reasonable people writing verifiers from `policy.md` alone could disagree on edge interactions, such as a revision to a row on a continuation page that renames the test. Whether they would depends on policy wording I can't see.

Judgement: Uncertain

**Solvable**

Positives:
- A reference solution exists and reads all 30 hidden certificates plus 185/185 across five generator seeds. The slowest certificate takes 18 seconds against a 120-second limit.
- The approach (render, detect orientation, Tesseract, fuse with the text layer by ink coverage, vote over crops, then a column-based parser) uses only standard tools that the container ships with.

Negatives:
- The reference was written by someone with full knowledge of the generator. It may be tuned to the exact fonts, layouts and trap shapes in ways an outsider working from 7 samples can't discover.
- The OCR fusion, multi-crop voting, form-appearance checks and policy engine add up to a lot of code. "A few hours for an expert who knows the approach" is plausible but borderline.

Judgement: Accept

**Difficult**

Positives:
- Reading what actually prints on a PDF is a real, hard engineering problem that document-AI practitioners face. The cases include adversarial text layers, outline-only pages, scans with no text layer, form appearance streams, image stamps and rotation. Building OCR/text-layer fusion that gets every digit right across 30 documents requires genuine expertise.
- Requiring all 30 certificates to be perfect means a 98%-per-document tool still fails about half the time, so sloppy solutions don't pass.

Negatives:
- The author says it directly: "no single step is hard, and one missed rule fails the certificate," and "the difficulty is completeness." That matches the rubric's rejection pattern for tasks that are hard mainly because of how many corner cases must be handled.
- The policy half is undergraduate-level logic (rounding, unit conversion, date comparison, precedence). On its own it adds volume, not depth.
- Some traps, such as white text, a form value that differs from its appearance, and scrambled text order, are designed to be adversarial. They are plausible in the real world but lean toward a gotcha checklist.
- The all-or-nothing reward over 30 documents can make the task feel hard mostly because of compounding per-document error rates rather than any single deep insight.

On balance, the reading half carries real, expert-level difficulty, and the policy half carries breadth. Reviewers could reasonably disagree on whether that combination is "hard for a good reason."

Judgement: Uncertain

**Interesting**

Positives:
- This is a very realistic, economically valuable workflow. Incoming-material CoA review is mandatory under cGMP for supplements and pharmaceuticals (for example, 21 CFR 111 and 211), and companies pay people and vendors to automate it.
- Robust PDF and scan extraction is a widely felt pain point.

Negatives:
- The data is synthetic, so the value depends on how faithfully the generator models real supplier documents. The proposal argues each case is modelled on real receiving-desk material, which is credible.

Judgement: Strong Accept

**Outcome-verified**

Positives:
- Only the output JSON is graded. Any method is allowed (any OCR approach, any parsing strategy).
- The constraints (120-second limit, shipped software only, runs as an unprivileged user) are mechanical and exist to prevent cheating or to keep conditions realistic.

Negatives:
- The output schema has to match the policy's exact keys, but it seems modest in size and the samples demonstrate it.

Judgement: Strong Accept

**Final analysis**

This is a polished, realistic proposal with a strong verification design, ground truth that comes from the generator, and a reference solution validated across several seeds. Its weak point is the one the author is open about: the stated source of difficulty is completeness across many individually easy rules, multiplied by an all-30 reward. That pattern is close to what the rubric cautions against. It also raises the specification risk that hidden certificates exercise interactions the agent can't infer from 7 samples and the policy.

The document-reading half is genuinely hard and expert-flavoured. Getting every printed digit right across rotated, font-less scans, misleading text layers, form appearance streams and image stamps is not course-project work, and it is a fair reason to argue the task is hard. Whether that is enough to outweigh the "breadth of corner cases" framing is a judgement call for the human auditors. Two other points need human checks:
- whether `policy.md` really pins down every interaction the hidden set exercises;
- whether the task overlaps existing TB document-extraction or OCR tasks (no accepted-task list was included with this proposal, so I couldn't check).

Decision: Uncertain
