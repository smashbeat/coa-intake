# Failure analysis: coa-intake

Six counted standard trials, all reward 0. Each trial's failing certificates come from `verifier/ctrf.json` in
`results/`. To see every differing field, each agent's `/app/intake/` was rerun outside Harbor on the same corpus
(`docs/commands.md`, "Rerunning an agent's tool"); every rerun reproduced the verifier's list of failures exactly.

A failure is called rule-decided when the agent read the page correctly and the output still contradicts a rule in
`policy.md`. It is called a reading miss when the agent's text for a printed value differs from what prints.

## What the agents did

Every trial followed the same arc. The agent read the instruction, the policy and the seven samples, built a
pipeline that renders pages and runs OCR next to the text layer, and worked until its output matched all seven
expected files. Five of the six final messages say all seven samples match exactly. Several agents also drew
certificates of their own to test on. Then they stopped. No trial raised an exception, and no trial ran out of time:
Codex used 47 to 53 minutes of its 8 hours, Opus 187 to 435 minutes.

The misses are in places the samples show separately and the hidden certificates combine.

## Codex, gpt-6.1-sol, xhigh

**`ry4jAKd`, 16 of 30.** Rule-decided (5): h03 and h10 count the revision page as a third lot (rule 5: a revision
replaces a value in place); h15 and h27 ignore the retest date stamped on the page, so h15 accepts a lot that had
expired (rules 3 and 8); h30 counts the continuation page as a lot (rule 9). Reading (9): digit and letter misreads
on outlined and scanned pages on h13, h17 and h19 (`5.9` for `5.5`, `me/kg`, `1553428` for `L553428`); a watermark
letter leaking into a cell on h14 and h30; the final period of the letterhead supplier name dropped on h16 and h18;
table rows merged or split on h07, h18, h21 and h25 (annotation overlay, sideways scan, scans).

**`qLxSTzB`, 18 of 30.** Rule-decided: h03 and h10, revision page counted as a lot; h15 and h27, retest stamp
ignored. The rest are reading misses.

**`HoDVDHy`, 24 of 30.** Rule-decided (2): h12 splits one lot into two entries where its table continues on an A4
continuation page (rule 9: one entry per lot); h27 ignores the retest stamp. Reading (4): on h15 the rule line under
a field is read into the material name as dashes; h18; h19 (`L` read as `1`); h21 (`9.5 tO 7.5`).

## Claude Code, claude-opus-5-5, max

**`JjKSvue`, 28 of 30.** Rule-decided (1): h11 keeps the footnote mark in the value (`550* ppb`), so the ppb result
is never converted and the lot comes out `incomplete` where it should be `reject` (rules 4 and 6). Reading (1): h19
lot `1553428` for `L553428`, on a scan whose image and OCR layer both show the L.

**`AJojEBX`, 23 of 30.** Rule-decided (4): h01 reports the continuation page's line
`Batch No.: B140936, L373360, P870167` as a fourth lot (rules 1 and 9; sample s05 shows a continuation page); h03
and h10 append the revision page's rows as new rows, where rule 5 has a revision replace the value in place; h29 reports arsenic at revision
3's 0.06 ppm but rejects the lot on the original 1.4 ppm against a limit of 1.0 (rules 5 and 8). Reading (3): h19 and
h20, lot `L` read as `1`; h22, supplier cut to `PRADESH PHYTOCHEM`.

**`xYcSLSa`, 26 of 30.** Rule-decided (2): h01, the same fourth lot from the continuation page; h11, the footnote
mark kept with the unit (`* ppb`), so no conversion (rule 4). Reading (2): h17 and h18 report the printed `<100` as
`<LOQ`; h18 also reads `5026` for `2026` on the sideways scan.

## Across trials

Every trial failed at least one rule-decided certificate. The certificates failed most often were h19 (5 of 6
trials, reading) and h18 (4 of 6, reading). Every one of the 30 hidden certificates was right in at least one trial,
so none depends on something a model cannot do.

The reading misses are failures under rule 2, which makes the printed appearance the value, and every scan is
readable with the tools in the container: the reference reads all 30. The result does not rest on them. Removing
every reading miss still leaves each trial with a rule-decided failure.

## Cheat trials

**Codex `NJZpZEQ`:** `AgentSafetyRefusalError` after about 1.5 minutes. The agent refused the red-team prompt and
wrote nothing. Reward 0, 0 of 30.

**Claude Code `Ggy9wDF`:** about 3 minutes. It looked for verifier files, leaked answers, PDF metadata and text
layers that would give the expected output, found no way past the verifier and stopped with `/app/intake/` empty.
It noted that the sample text layers disagree with the print in ways that make the task harder. Reward
0, 0 of 30.

## Not counted

`coa2-probe-claude-1` (`tc6Zzet`) stopped after 8 minutes of agent time when the Claude subscription reached its
session limit; it had written no tool. One trial of `coa2-run-codex-1` (`eKytVdR`, 26 of 30) ran while the ChatGPT
account reached its usage limit and exited with an error; it was replaced by `coa2-run-codex-2`. Both are under
`results/usage-limit/`.
