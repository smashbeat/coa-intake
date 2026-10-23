#!/usr/bin/env python3
"""Collect trial evidence from Harbor job folders into results/, restoring Harbor's secret scrubbing.

    python3 tools/collect_results.py JOBS_DIR results/ JOB_NAME[=label] ...

For every trial of each job: result.json, verifier/reward.txt, verifier/reward_details.json (if any),
verifier/ctrf.json, and the agent's final message. Harbor replaces each `--ae` value with `[REDACTED]` in
the files it writes to the host; two of ours are the string `1`, so every digit 1 reads `[REDACTED]`. The
copies written here substitute it back, which is exact because nothing else writes that marker. A summary
table is written to results/summary.md.
"""

import json
import re
import shutil
import sys
from pathlib import Path


def restore(text: str) -> str:
    return text.replace("[REDACTED]", "1")


def final_message(agent_dir: Path) -> str:
    for name in ("codex.txt", "claude-code.txt"):
        f = agent_dir / name
        if f.exists():
            txt = restore(f.read_text(errors="replace"))
            if name == "codex.txt":
                msgs = re.findall(r'"type":"agent_message","text":"((?:[^"\\]|\\.)*)"', txt)
            else:
                msgs = re.findall(r'"result":"((?:[^"\\]|\\.)*)"', txt)
            return json.loads('"' + msgs[-1] + '"') if msgs else ""
    return ""


def main():
    jobs_dir, out_dir, specs = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    rows = []
    for spec in specs:
        job, _, label = spec.partition("=")
        label = label or job
        for trial in sorted((jobs_dir / job).glob("*/")):
            if not (trial / "result.json").exists():
                continue
            dest = out_dir / label / trial.name
            dest.mkdir(parents=True, exist_ok=True)
            result = json.loads(restore((trial / "result.json").read_text()))
            (dest / "result.json").write_text(json.dumps(result, indent=2))
            for rel in ("verifier/reward.txt", "verifier/reward_details.json", "verifier/ctrf.json"):
                src = trial / rel
                if src.exists():
                    (dest / Path(rel).name).write_text(restore(src.read_text(errors="replace")))
            msg = final_message(trial / "agent")
            (dest / "agent_final_message.md").write_text(msg + "\n")
            reward = (trial / "verifier/reward.txt").read_text().strip() if (trial / "verifier/reward.txt").exists() else ""
            exc = (result.get("exception_info") or {}).get("exception_type")
            ctrf = trial / "verifier/ctrf.json"
            tests = ""
            if ctrf.exists():
                s = json.loads(restore(ctrf.read_text()))["results"]["summary"]
                tests = f"{s['passed']}/{s['tests']}"
            started, finished = result.get("started_at", ""), result.get("finished_at", "")
            rows.append((label, trial.name, restore(reward), tests, exc or "", started[:19], finished[:19]))
    lines = ["| Job | Trial | Reward | Checks | Exception | Started | Finished |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |" for r in rows]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
