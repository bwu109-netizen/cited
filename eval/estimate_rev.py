"""Cost estimate before the revised runs (eval_design §10.3): eval1_rev1 new calls + holdout (4 cells) on
DeepSeek, and the exact worst case of the two frozen Fable batches still to come (count_tokens is free).
DeepSeek estimates scale each company's actual eval1 cost by document size (no provider-cache discount)."""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from earnings_agent import config  # noqa: E402
from earnings_agent.budget import Budget  # noqa: E402

OUT = ROOT / "data" / "eval"


def cost(obj):
    c = (obj.get("llm") or {}).get("cost_usd") or 0
    return c + ((obj.get("parser_llm") or {}).get("cost_usd") or 0)


def main():
    cfg = json.loads((ROOT / "eval" / "config.json").read_text())
    hold = {(r["market"], r["code"]): r for r in json.loads((ROOT / "eval" / "holdout_config.json").read_text())["reports"]}
    eval1_chars = json.loads((ROOT / "data" / "eval" / "eval1_doc_chars.json").read_text())
    tot = {"rev1_verified": 0.0, "hold_pipeline": 0.0, "hold_direct": 0.0, "hold_simple": 0.0, "hold_verified": 0.0}
    for r in cfg["reports"]:
        t = f"{r['market']}_{r['code']}"
        c = {cell: cost(json.loads((OUT / "eval1" / cell / f"{t}.json").read_text()))
             for cell in ("ds_pipeline", "ds_direct", "ds_simple")}
        # no provider-cache discount: price the simple ask like the professional one (same input)
        direct_nc = max(c["ds_direct"], c["ds_simple"])
        tot["rev1_verified"] += 1.3 * direct_nc
        h = hold.get((r["market"], r["code"]))
        if h:
            k = h["chars"] / max(1, eval1_chars[t])
            tot["hold_pipeline"] += c["ds_pipeline"] * max(1.0, k ** 0.5)  # pipeline sees selected pages only
            tot["hold_direct"] += direct_nc * k
            tot["hold_simple"] += direct_nc * k
            tot["hold_verified"] += 1.3 * direct_nc * k
    ds_total = sum(tot.values())
    st = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD).status()
    print(json.dumps({k: round(v, 3) for k, v in tot.items()}, indent=1))
    print(f"DeepSeek estimate total ${ds_total:.2f}; budget left ${st['left']:.2f}")
    return ds_total


if __name__ == "__main__":
    main()
