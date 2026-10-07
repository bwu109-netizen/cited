"""Score the 9 Fable reports with the FROZEN v1 scorer (imports the eval-frozen-v1 worktree code).
The item set and answer key are those of the frozen scorer on the same 9 reports; the three DeepSeek tiers
are scored alongside on exactly the same items for comparison. Writes data/eval/eval1/scores_fable.json."""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
MAIN = Path(__file__).resolve().parents[1]
W = MAIN / ".worktrees" / "frozen-v1"
sys.path.insert(0, str(W))
sys.path.insert(0, str(W / "eval"))

import earnings_agent  # noqa: E402
import score_eval  # noqa: E402
from score import summarize  # noqa: E402

assert earnings_agent.__file__.startswith(str(W)) and score_eval.__file__.startswith(str(W)), "must use frozen code"
CELLS = ["ds_simple", "ds_direct", "ds_pipeline", "fable_direct", "fable_pipeline"]


def main():
    cfg = json.loads((W / "eval" / "config.json").read_text())
    pick = {(s["market"], s["code"]) for s in json.loads((W / "eval" / "fable_subset.json").read_text())["subset"]}
    reps = score_eval.analyse("eval1", [r for r in cfg["reports"] if (r["market"], r["code"]) in pick], CELLS)
    summary = {"run": "eval1", "subset": "fable", "reports": len(reps),
               "pending_review": sum(len(x["pending"]) for x in reps), "cells": {}}
    for c in CELLS:
        summary["cells"][c] = summarize([row for x in reps for row in x["rows"][c]], pipeline="pipeline" in c)
    detail = [{"report": f"{x['report']['market']}:{x['report']['code']}", "items": x["items"], "pending": x["pending"],
               "disputes": x["disputes"], "rows": {c: x["rows"][c] for c in CELLS}} for x in reps]
    (MAIN / "data" / "eval" / "eval1" / "scores_fable.json").write_text(
        json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
