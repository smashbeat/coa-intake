# coa-intake: a Terminal-Bench task that two frontier agents fail

One original Terminal-Bench 3 task, built with Harbor 0.24.0 against `harbor-framework/terminal-bench-3`.
Claude Code on Opus 5.5 and Codex on GPT-6.1 Sol, both at their highest effort setting, fail three standard
trials each and score zero on a cheat trial. This is the hand-built task that led to
[task-factory](https://github.com/smashbeat/task-factory), which generates tasks of this kind from a domain
described as data and audits each one for quality, difficulty and fairness.

Author: Alessandro Grassi (smashbeat73@gmail.com, GitHub `smashbeat`).

## The task

A supplement or pharmaceutical manufacturer receives a certificate of analysis (CoA) with every lot of raw
material: the supplier's lab report, with the lot number, dates, and each test's result and limit. Most arrive as
PDFs, some made by lab software and many printed, stamped and scanned. Someone at the receiving desk copies the
values into the quality system and decides whether each lot is accepted, rejected or held.

The agent builds that intake tool. It reads one certificate PDF and the house specification and writes every
lot's identity fields, every result row and a disposition, as a nine-rule policy defines them. Seven sample
certificates come with their expected output. The verifier runs the tool on 30 hidden certificates from the same
four suppliers and production routes: born-digital PDFs, PDFs re-made through Ghostscript, text converted to
outlines, scans with a correct OCR layer, a wrong one or none, a sideways scan, fillable forms whose stored
values differ from what prints, stamps and drawn-over corrections. Each certificate must be right in every
field. No LLM is involved in grading.

Task directory: [`tasks/coa-intake`](tasks/coa-intake). Its [README](tasks/coa-intake/README.md) has the
difficulty, solution and verification explanations.

## Results

| Run | Agent | Model, effort | Reward | Certificates correct |
|---|---|---|---|---|
| standard ×3 | codex | gpt-6.1-sol, xhigh | 0, 0, 0 | 16, 18, 24 of 30 |
| standard ×3 | claude-code | claude-opus-5-5, max | 0, 0, 0 | 28, 23, 26 of 30 |
| cheat | codex | gpt-6.1-sol, xhigh | 0 | 0 of 30 (refused the prompt) |
| cheat | claude-code | claude-opus-5-5, max | 0 | 0 of 30 (probed, found nothing, wrote no tool) |
| oracle | | | 1 | 30 of 30 |
| nop | | | 0 | 0 of 30 |

Codex trials took 47 to 53 minutes and Opus trials 3 to 7 hours. Two further runs are not counted: an Opus
trial stopped after 10 minutes when the subscription reached its session limit, and a Codex trial stopped
partway when the ChatGPT account reached its usage limit. The Codex run was replaced by a full trial.

Every standard trial failed at least one certificate that a written rule decides, with the page read
correctly:

| Certificate | What the agent did | Rule |
|---|---|---|
| h03, h10 | added the revision page's rows, or counted the revision page as a lot | 5: the highest-numbered revision replaces the value in place |
| h29 | reported arsenic at revision 3's 0.06 ppm but rejected the lot on the original 1.4 ppm | 5 and 8 |
| h15, h27 | ignored the retest date stamped on the page; on h15 an expired lot was accepted | 3 and 8 |
| h01 | reported the continuation page's line `Batch No.: B140936, L373360, P870167` as a fourth lot | 1 and 9 (sample s05 shows a continuation page) |
| h12, h30 | split one lot into two entries where its table continues on the next page | 9: one entry per lot |
| h11 | kept the footnote mark with the unit (`* ppb`), so the result was never converted | 4 and 6 |

Codex missed rule-decided certificates in all three trials, Opus in all three. The other misses are
misreadings, such as `1553428` for the lot `L553428` on a scan whose image and OCR layer both show the L.
Every hidden certificate was read correctly by at least one of the six trials, so none is beyond reach.

The reference tool reads all 30 hidden certificates, and all 37 certificates of each of five generator seeds
(185 of 185), with the slowest at 18 seconds against the 120-second limit.

All 28 static checks, the Docker build, oracle and nop pass on `terminal-bench-3` main (e67a2cb7). The
implementation rubric (`harbor check`, 36 criteria, LLM-judged) was run eight times on the submitted task, four
with Claude Opus 5.5 as the judge and four with Claude Sonnet 5, the model the repository's CI uses for its hosted
review; all eight passed every criterion that applies ([`results/rubric/`](results/rubric/)). The task proposal
rubric returned Accept ([`results/proposal-rubric/`](results/proposal-rubric/)). The commands, and the earlier
judge rounds that led to the final README wording, are in [`docs/commands.md`](docs/commands.md). Each trial's
failures are listed in [`docs/failure-analysis.md`](docs/failure-analysis.md).

## Repository layout

| Path | Contents |
|---|---|
| `tasks/coa-intake/` | the task: instruction, task.toml, environment (policy, samples), solution, tests (hidden certificates, expected output, comparison), README |
| `tools/generator/` | the task's sources: `gen2.py` (draws a corpus for a seed), `policy.md`, `compare.py`, the reference split into `solution/` parts, `gen-env/` (the generator image), `assemble.sh` (writes the task directory), `run_ref.py` and `run_agent.py` (run the reference or an agent's tool on a corpus outside Harbor) |
| `tools/collect_results.py` | copies trial evidence out of Harbor job folders into `results/`, restoring Harbor's scrubbing |
| `results/` | per-trial `result.json`, `reward.txt`, `ctrf.json` and the agent's final message for every run; `summary.md`; `commit.txt`, the git tree of the submitted task; `usage-limit/`, the two uncounted trials; `static-checks.txt`; `rubric/`; `proposal-rubric/`; `reference/`, the reference on generator seeds 1 to 5; `frozen-tree.sha256`, the task tree the trials ran on |
| `docs/commands.md` | every command and configuration used, and how Harbor's trial files should be read |
| `docs/failure-analysis.md` | each trial's failures, rule-decided and reading, and the cheat trials |

## Reproducing

From a clone of `harbor-framework/terminal-bench-3` with `tasks/coa-intake` copied in, the commands in
`docs/commands.md` run the checks, the oracle and nop, the standard trials and the cheat trials. Agents were
authenticated with subscriptions (ChatGPT login for Codex, an OAuth token from `claude setup-token` for Claude
Code), so no API key appears anywhere in this repository. Harbor replaces every `--ae` value with `[REDACTED]` in
the files it writes to the host, and two of ours are the string `1`; `docs/commands.md` explains the substitution
and `tools/collect_results.py` applies it when it builds `results/`.

## How it was built

An earlier task of mine (capsule-batch-planner) did not survive a careful review: its failures rested on a decision
the instruction did not state. This task was designed the other way round: every rule that decides a certificate
is written in the policy, and the difficulty is applying all of them to documents that arrive in every format a
supplier uses. The first version had 20 hidden certificates that shared one layout, font set and producer string;
Opus solved it on its third trial by recognising the generator and rebuilding it. The present version removes that fingerprint, uses four
supplier styles with fonts the container does not have, writes the reading rule as a principle, and adds rules
for rounding, unit conversion, test-name aliases, limits of quantitation, numbered revisions and expired lots.

The task was built with Claude Code and Codex under the author's direction. The author chose the domain, the
document routes and the rules, ran every trial and judged every iteration. The code, generator, tests,
instruction and these documents were written by Claude Code and reviewed by the author.
