"""Refuse to run the evaluation if any frozen file changed since eval/FROZEN.json was written.

  python eval/check_frozen.py --write     # at freeze time: record sha256 of every frozen file + git commit
  python eval/check_frozen.py             # before every run: exit 1 if anything differs
  python eval/check_frozen.py --revision "reason"   # allowed re-run after a rule change (§7.2): logs it
  --manifest eval/FROZEN_REV1.json   # any of the above against another manifest (revised rules, §10)

eval/FROZEN.json is the frozen v1 manifest (git tag eval-frozen-v1). It keeps checking only the files it
recorded; files added later (revisions) are listed in FROZEN and recorded in the revised manifest.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = [
    # inputs
    "eval/config.json", "eval/fable_subset.json", "eval/stability_subset.json", "eval/holdout_config.json",
    "eval/fable_subset.py", "eval/stability_subset.py",
    # prompts
    "earnings_agent/extract.py", "earnings_agent/direct.py", "earnings_agent/direct_verify.py",
    # verification, sanity checks, units, periods, templates
    "earnings_agent/verify.py", "earnings_agent/sanity.py", "earnings_agent/units.py",
    "earnings_agent/textnorm.py", "earnings_agent/periods.py", "earnings_agent/templates.py",
    # what the model sees and what it is compared with
    "earnings_agent/parse.py", "earnings_agent/locate.py", "earnings_agent/sources.py",
    "earnings_agent/benchmark.py", "earnings_agent/pipeline.py",
    # model calls, parameters, prices, budget
    "earnings_agent/config.py", "earnings_agent/llm_client.py", "earnings_agent/anthropic_batch.py",
    "earnings_agent/budget.py",
    # scoring and running
    "eval/score.py", "eval/score_eval.py", "eval/run_eval.py",
    # rules as written
    "docs/metrics_spec.md", "docs/eval_design.md",
]
MANIFEST = ROOT / (sys.argv[sys.argv.index("--manifest") + 1] if "--manifest" in sys.argv else "eval/FROZEN.json")


def digest(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def main():
    if "--write" in sys.argv:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--"] + FROZEN, cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        if dirty:
            sys.exit(f"frozen files have uncommitted changes, commit first:\n{dirty}")
        MANIFEST.write_text(json.dumps({"commit": commit, "frozen_at": datetime.now(timezone.utc).isoformat(),
                                        "files": {p: digest(p) for p in FROZEN}, "revisions": []}, indent=1))
        print(f"frozen at {commit} -> {MANIFEST.relative_to(ROOT)}")
        return
    m = json.loads(MANIFEST.read_text())
    changed = [p for p, h in m["files"].items() if not (ROOT / p).exists() or digest(p) != h]
    if not changed:
        print(f"OK: matches freeze {m['commit'][:10]} ({MANIFEST.name})")
        return
    if "--revision" in sys.argv:
        reason = sys.argv[sys.argv.index("--revision") + 1]
        m["revisions"].append({"at": datetime.now(timezone.utc).isoformat(), "reason": reason, "changed": changed,
                               "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                                        text=True).stdout.strip()})
        MANIFEST.write_text(json.dumps(m, indent=1))
        print(f"REVISION logged ({len(changed)} files): results must be reported next to the frozen ones (§7.2)")
        return
    sys.exit("REFUSED: frozen files changed since freeze:\n  " + "\n  ".join(changed))


if __name__ == "__main__":
    main()
