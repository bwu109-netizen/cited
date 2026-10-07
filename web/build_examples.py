"""Build the three pre-computed examples on the home page (PRD P1 M2).

The model replies are the cached eval1 DeepSeek replies (salt "eval1"); verification is re-run with the
current product rules (R1-R6). Any prompt not in the cache would be a real call, charged to the same
$20 ledger. The pages referenced by the result are kept so the page drawer works without a download.

  .venv/bin/python -m web.build_examples
"""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from earnings_agent import config  # noqa: E402
from earnings_agent.budget import Budget  # noqa: E402
from earnings_agent.parse import load_doc_pages  # noqa: E402
from earnings_agent.pipeline import extract  # noqa: E402
from web.core import payload  # noqa: E402

EXAMPLES = [("us", "TSLA", "2026Q2"), ("a", "601857", "2025FY"), ("hk", "01810", "2026H1")]
OUT = Path(__file__).resolve().parent / "examples"


def main():
    OUT.mkdir(exist_ok=True)
    budget = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD)
    before = budget.status()["spent"]
    for m, c, p in EXAMPLES:
        res = extract(m, c, p, providers=["deepseek"], budget=budget, salt="eval1")
        res["_pages"] = load_doc_pages(res["doc"])
        pl = payload(res)
        pl["example"] = True
        pl["from_cache"] = res["llm"]["from_cache"]
        (OUT / f"{m}_{c}.json").write_text(json.dumps(pl, ensure_ascii=False, indent=1, default=str))
        print(m, c, pl["counts"], "core", pl["core_counts"], "cached" if pl["from_cache"] else "NEW CALL",
              f"pages kept {len(pl['pages'])}")
    print(f"ledger: ${budget.status()['spent'] - before:.4f} spent by this build")


if __name__ == "__main__":
    main()
