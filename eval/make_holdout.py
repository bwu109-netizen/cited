"""Build eval/holdout_config.json (eval_design §10.3): the previous-period report of every evaluation
company (config.json "prior_period"), fetched and parsed here so any report that cannot be obtained is
known before the holdout freeze. Nothing about the holdout reports' results is looked at."""
import json
import sys
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from earnings_agent.pipeline import prepare  # noqa: E402


def main():
    cfg = json.loads((ROOT / "eval" / "config.json").read_text())
    rows, problems = [], []
    for r in cfg["reports"]:
        h = {"market": r["market"], "code": r["code"], "period": r["prior_period"], "name": r["name"],
             "eval1_period": r["period"]}
        try:
            ctx = prepare(r["market"], r["code"], r["prior_period"])
            d = ctx["doc"]
            h.update(template=ctx["template"], title=d["title"], pages=len(ctx["pages"]),
                     chars=sum(len(p["text"]) for p in ctx["pages"]),
                     benchmark_items=len([b for b in ctx["benchmarks"] if b["period_end"][:7] == d["period_end"][:7]]))
            print(f"{r['market']} {r['code']} {r['prior_period']}: {d['title']} pages={h['pages']} "
                  f"chars={h['chars']} template={h['template']} bench={h['benchmark_items']}", flush=True)
        except Exception as e:
            h["error"] = f"{type(e).__name__}: {e}"
            problems.append(h)
            print(f"{r['market']} {r['code']} {r['prior_period']}: ERROR {h['error'][:200]}", flush=True)
            traceback.print_exc()
        rows.append(h)
    out = {"version": "holdout-2026-10-06", "note": "previous period of every eval1 company; DeepSeek only; "
           "scored on US/A (automatic key), HK not scored", "reports": [x for x in rows if "error" not in x],
           "unavailable": problems}
    (ROOT / "eval" / "holdout_config.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(out['reports'])} usable, {len(problems)} unavailable")


if __name__ == "__main__":
    main()
