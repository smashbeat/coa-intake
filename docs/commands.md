# Commands and configurations: coa-intake

All runs used Harbor 0.24.0 with the Docker environment on macOS (Docker Desktop, 8 GB, 6 CPUs). Agents
authenticated with subscriptions, not API keys: Codex through ChatGPT login (`CODEX_FORCE_AUTH_JSON=1`), Claude Code
through an OAuth token from `claude setup-token` (`CLAUDE_FORCE_OAUTH=1`). Trials ran on the task directory as
`assemble.sh` wrote it for generator seed 1; the checksums of that tree are in `results/frozen-tree.sha256`.
Since then the task directory has changed in five places, none of which an agent or the verifier reads differently:
the README was added, a stale `tests/__pycache__/` was deleted, `author_organization` was added to `task.toml`,
the canary comment was added to `solution/intake.py`, and both Dockerfiles pin `python:3.13-slim-bookworm` by the
digest of the local image every trial was built from (`sha256:73aa5fae...`). Oracle and nop were rerun after
those changes.

## Static checks

From a clone of `harbor-framework/terminal-bench-3` main with the task copied to `tasks/coa-intake`:

```bash
for s in scripts/checks/check-*.sh; do bash "$s" tasks/coa-intake; done
```

`check-task-fields.sh` needs Python 3.11+ for `tomllib`; macOS ships 3.9, so `python3` was pointed at Homebrew's
3.13. `check-image-digests.sh` needs `dockerfile-pin`, which CI installs from a checksummed Linux release; it was
run that way in a `linux/amd64` Alpine container with the repository mounted read-only:

```bash
wget -qO /tmp/dp.tgz https://github.com/azu/dockerfile-pin/releases/download/v1.5.0/dockerfile-pin_linux_amd64.tar.gz
echo "88845bfbe4918596f00eb77ebeec8a0826026c9b24bcc83053cae48402e95ea6  /tmp/dp.tgz" | sha256sum -c
tar -xzf /tmp/dp.tgz -C /tmp dockerfile-pin
PATH=/tmp:$PATH bash scripts/checks/check-image-digests.sh tasks/coa-intake
```

The outcome of every check is in `results/static-checks.txt`.

## Implementation rubric

```bash
harbor check tasks/coa-intake -r docs/prompts/task-implementation.toml \
  --agent claude-code --model anthropic/claude-opus-5-5 -k 4 -n 2 --job-name coa2-check-final-opus \
  --ae CLAUDE_FORCE_OAUTH=1 --ae CLAUDE_CODE_OAUTH_TOKEN="$(cat <token file>)"

harbor check tasks/coa-intake -r docs/prompts/task-implementation.toml \
  --agent claude-code --model anthropic/claude-sonnet-5 -k 4 -n 1 --job-name coa2-check-final-sonnet \
  --ae CLAUDE_FORCE_OAUTH=1 --ae CLAUDE_CODE_OAUTH_TOKEN="$(cat <token file>)"
```

`-k 4` runs the judge four times in one job and writes the verdicts as `results[0..3]` of
`jobs/<job>/check_report.json`. `results/rubric/<model>-run-N.json` is each valid verdict and `console-*.txt` the
console output of each job. Sonnet 5 is the model the repository's CI uses for its hosted review (`review_model` in
`.github/harbor-run-defaults.yml`).

Some judge runs end without a verdict: Opus twice wrote a report Harbor could not parse (`Invalid \uXXXX escape`),
and Sonnet, in seven of its fourteen runs across the rounds, finished its review without writing
`/app/check-result.json`. Those runs are not verdicts on
the task. They were replaced until each judge had four valid verdicts; the Sonnet replacements came from a second job
(`coa2-check-final-sonnet-2`, `-k 2 -n 1`).

Two earlier rounds are kept under `results/rubric/earlier/`. In round 1 all four Opus verdicts failed one criterion,
`difficulty_explanation_quality`, because the task README's Difficulty explanation quoted agent trial results; those
were moved to this README. Round 2 passed every criterion (four Opus verdicts, two Sonnet; a third Sonnet run was discarded because the
README changed while it ran). The task proposal rubric (below) then judged the
difficulty Uncertain, quoting a sentence that described each step as easy, and the Difficulty explanation was
rewritten to lead with the reading problem. Round 3, the eight verdicts above, ran on the README as submitted. The
README is not part of the agent's environment or the verifier, so none of this changes a trial.

## Task proposal rubric

`docs/prompts/task-proposal.md` is the prompt maintainers give an LLM to judge a task idea before it is built. It was
run with Claude Opus 5.5 through the Claude Code CLI, with the task instruction and the README's overview, difficulty,
solution and verification sections appended as the proposal:

```bash
{ cat docs/prompts/task-proposal.md; echo "# Task proposal to evaluate"; cat tasks/coa-intake/instruction.md;
  awk '/^## Overview/,/^## Relevant experience/' tasks/coa-intake/README.md; } | claude -p --model opus
```

The prompt as sent and the verdict (Accept) are in `results/proposal-rubric/`; the earlier run (Uncertain) is in
`results/proposal-rubric/first-round/`.

## Oracle and nop

```bash
harbor run -p tasks/coa-intake --agent oracle --env docker --yes --job-name coa2-oracle-main
harbor run -p tasks/coa-intake --agent nop --env docker --yes --job-name coa2-nop-main
```

## Standard trials (/run equivalent), three per agent

One Harbor job ran at a time. The counted Codex trials came from three jobs:

```bash
harbor run -p tasks/coa-intake --agent codex --model openai/gpt-6.1-sol --env docker --yes \
  --ae CODEX_FORCE_AUTH_JSON=1 --ak reasoning_effort=xhigh --job-name coa2-probe-codex-1

harbor run -p tasks/coa-intake --agent codex --model openai/gpt-6.1-sol --env docker --yes \
  --ae CODEX_FORCE_AUTH_JSON=1 --ak reasoning_effort=xhigh -k 2 --n-concurrent 2 --job-name coa2-run-codex-1

harbor run -p tasks/coa-intake --agent codex --model openai/gpt-6.1-sol --env docker --yes \
  --ae CODEX_FORCE_AUTH_JSON=1 --ak reasoning_effort=xhigh --job-name coa2-run-codex-2
```

and the counted Claude Code trials from two:

```bash
harbor run -p tasks/coa-intake --agent claude-code --model anthropic/claude-opus-5-5 --env docker --yes \
  --ae CLAUDE_FORCE_OAUTH=1 --ae CLAUDE_CODE_OAUTH_TOKEN="$(cat <token file>)" \
  --ae CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 --ak reasoning_effort=max --job-name coa2-probe-claude-2

harbor run -p tasks/coa-intake --agent claude-code --model anthropic/claude-opus-5-5 --env docker --yes \
  --ae CLAUDE_FORCE_OAUTH=1 --ae CLAUDE_CODE_OAUTH_TOKEN="$(cat <token file>)" \
  --ae CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 --ak reasoning_effort=max -k 2 --n-concurrent 2 --job-name coa2-run-claude-1
```

Harbor resolves `claude-opus-5.5` as `anthropic/claude-opus-5-5`. `CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000`
matches `.github/harbor-run-defaults.yml`.

Two trials are not counted and are kept under `results/usage-limit/`. `coa2-probe-claude-1` (same command as
`coa2-probe-claude-2`) stopped after 8 minutes of agent time when the Claude subscription reached its session limit,
before the agent had written anything. One of the two trials of `coa2-run-codex-1` (`eKytVdR`) ran while the
ChatGPT account reached its usage limit and exited with an error; `coa2-run-codex-2` replaced it. Both scored 0.

## Cheat trials (/cheat equivalent), one per agent

The CI cheat command appends `docs/prompts/hack-trial-prompt.md` to the task instruction; Harbor does the same with
`--extra-instruction-path`:

```bash
harbor run -p tasks/coa-intake --agent codex --model openai/gpt-6.1-sol --env docker --yes \
  --ae CODEX_FORCE_AUTH_JSON=1 --ak reasoning_effort=xhigh \
  --extra-instruction-path docs/prompts/hack-trial-prompt.md --job-name coa2-cheat-codex-1

harbor run -p tasks/coa-intake --agent claude-code --model anthropic/claude-opus-5-5 --env docker --yes \
  --ae CLAUDE_FORCE_OAUTH=1 --ae CLAUDE_CODE_OAUTH_TOKEN="$(cat <token file>)" \
  --ae CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 --ak reasoning_effort=max \
  --extra-instruction-path docs/prompts/hack-trial-prompt.md --job-name coa2-cheat-claude-1
```

## Reading the trial files

Harbor replaces every `--ae` value with `[REDACTED]` in the files it writes to the host; two of ours are the string
`1`, so every digit 1 in `result.json`, `reward.txt`, `ctrf.json`, transcripts and artifacts reads `[REDACTED]` on
disk. Verifiers ran on the unscrubbed copies inside Docker. `tools/collect_results.py` restores the digit when it
builds `results/`:

```bash
python3 tools/collect_results.py <harbor clone>/jobs results \
  coa2-probe-codex-1=codex-standard coa2-run-codex-1=codex-standard coa2-run-codex-2=codex-standard \
  coa2-probe-claude-1=claude-standard coa2-probe-claude-2=claude-standard coa2-run-claude-1=claude-standard \
  coa2-cheat-codex-1=codex-cheat coa2-cheat-claude-1=claude-cheat coa2-oracle-1=oracle coa2-nop-1=nop
```

The two usage-limit trials were then moved to `results/usage-limit/` and their rows in `results/summary.md`
labelled as not counted.

## Rerunning an agent's tool outside Harbor

The verifier reports which certificates failed but not every differing field. To see the full difference, the
agent's `/app/intake/` directory (saved by Harbor as the trial's artifact) was run in the task image against the
corpus the generator wrote, and compared with `compare.py`, the verifier's own comparison:

```bash
docker build -t coa2-task-env tasks/coa-intake/environment
docker run --rm -v "$PWD/tools/generator:/work" -v <artifact dir>:/op coa2-task-env python3 /work/run_agent.py /work/out1
```

`run_agent.py` runs `/op/intake.py` on every certificate of the corpus and prints each difference.
Every local rerun reproduced the verifier's failures exactly.

## Regenerating the task

```bash
docker build -t coa-gen-env tools/generator/gen-env
cd tools/generator && bash assemble.sh 1 ../../tasks/coa-intake
```

`gen2.py` draws the corpus for a seed (7 samples and 30 hidden certificates, with their specifications and
expected output) into `out<seed>/`; `assemble.sh` copies it with `policy.md`, `compare.py` and the reference into
the task directory. Regenerating seed 1 this way reproduces every specification, expected output, sample
expectation and text file of the submitted task exactly. The PDFs are not byte-identical: ReportLab writes fresh
object names and timestamps, and a scan's OCR layer can come out differently. The reference still reads all 37
regenerated certificates correctly. The PDFs in `tasks/coa-intake` are the ones the trials ran on. `manifest-seed1.json` lists each certificate's supplier, route, features and dispositions. The
reference is `solution/intake.py`, the concatenation of `_head.py`, `_words_v2.py` and
`_parse.py`. `run_ref.py` runs it on a corpus and compares with the expected output:

```bash
docker run --rm -v "$PWD/tools/generator:/work" coa2-task-env python3 /work/run_ref.py /work/out1
```

Seeds 1 to 5 pass 37 of 37 each; the logs are in `results/reference/`.
