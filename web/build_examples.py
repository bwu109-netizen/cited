"""Build the three pre-computed examples on the home page (PRD P1 M2).

The model replies are the cached eval1 DeepSeek replies (salt "eval1"); verification is re-run with the
current product rules (R1-R6). Industry-metric names and rationales (free text written by the model, in
whatever language it chose) are then written in both Chinese and English by one small DeepSeek call per
example, so the page shows them in the interface language; numbers and quotes are untouched.
Any extraction prompt not in the cache would be a real call, charged to the same $20 ledger. The pages referenced by the result are kept so the page drawer works without a download.

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

TRANSLATE = """下面是一份财报抽取结果里的“行业指标”列表，每项有 name（指标名）和 rationale（为什么重要）。
请把每项的 name 和 rationale 分别写成中文和英文，意思不变，不增减信息，不要改动其中的数字。
只输出 JSON：{"items": [{"i": 0, "name_zh": "", "rationale_zh": "", "name_en": "", "rationale_en": ""}]}"""

EXAMPLES = [("us", "TSLA", "2026Q2"), ("a", "601857", "2025FY"), ("hk", "01810", "2026H1")]
OUT = Path(__file__).resolve().parent / "examples"


def bilingual(pl):
    import os

    from dotenv import load_dotenv

    from earnings_agent.llm_client import make_client

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    ms = pl["metrics"]
    if not ms:
        return
    client = make_client("deepseek", os.environ["DEEPSEEK_API_KEY"])
    src = json.dumps([{"i": k, "name": m["name"], "rationale": m["rationale"]} for k, m in enumerate(ms)],
                     ensure_ascii=False)
    data, usage = client.complete_json(TRANSLATE, src)
    for it in data.get("items") or []:
        m = ms[int(it["i"])]
        for k in ("name_zh", "rationale_zh", "name_en", "rationale_en"):
            m[k] = it.get(k) or m.get(k.split("_")[0])
    pl["metrics_translated"] = {"model": usage.get("model"), "note": "name / rationale only; numbers and quotes untouched"}


def main():
    OUT.mkdir(exist_ok=True)
    budget = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD)
    before = budget.status()["spent"]
    for m, c, p in EXAMPLES:
        res = extract(m, c, p, providers=["deepseek"], budget=budget, salt="eval1")
        res["_pages"] = load_doc_pages(res["doc"])
        pl = payload(res)
        bilingual(pl)
        pl["example"] = True
        pl["from_cache"] = res["llm"]["from_cache"]
        (OUT / f"{m}_{c}.json").write_text(json.dumps(pl, ensure_ascii=False, indent=1, default=str))
        print(m, c, pl["counts"], "core", pl["core_counts"], "cached" if pl["from_cache"] else "NEW CALL",
              f"pages kept {len(pl['pages'])}")
    print(f"ledger: ${budget.status()['spent'] - before:.4f} spent by this build")


if __name__ == "__main__":
    main()
