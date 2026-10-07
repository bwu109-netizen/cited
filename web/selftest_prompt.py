"""Self-test of the universal prompt (prompts/) on the dev set: DeepSeek reply -> Verify page parser -> verification.

The DeepSeek API takes no PDF upload, so the report goes in as parsed page text marked [PAGE n] (n = PDF page
index), the same input the evaluation used. The reply is then handled exactly as on the Verify page:
web.paste.parse (whole reply pasted) and earnings_agent.verify.verify_report. Spend goes to the evaluation ledger.

  .venv/bin/python -m web.selftest_prompt [zh|en]
"""
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

from earnings_agent import config  # noqa: E402
from earnings_agent.budget import Budget  # noqa: E402
from earnings_agent.llm_client import cached_complete_text  # noqa: E402
from earnings_agent.periods import cumulative_type, parse_period  # noqa: E402
from earnings_agent.pipeline import prepare  # noqa: E402
from earnings_agent.verify import verify_report  # noqa: E402

from . import paste  # noqa: E402

DEV = [("a", "600519", "2026H1"), ("us", "AAPL", "2026Q3"), ("hk", "00700", "2026H1")]
ROOT = Path(__file__).resolve().parents[1]
INTRO = {"zh": "以下是报告全文，按 PDF 页标注（[PAGE n] 就是 PDF 第 n 页）：",
         "en": "The full report follows, marked by PDF page ([PAGE n] is PDF page n):"}


def main(lang="zh"):
    prompt = (ROOT / "prompts" / f"universal_prompt_{lang}.md").read_text()
    budget = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD)
    out_dir = ROOT / "data" / "selftest"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok_all = True
    for m, c, p in DEV:
        ctx = prepare(m, c, p)
        body = "\n\n".join(f"[PAGE {pg['page']}]\n{pg['text']}" for pg in ctx["pages"])
        user = f"{prompt}\n\n---\n\n{INTRO[lang]}\n\n{body}"
        rec = cached_complete_text("", user, providers=["deepseek"], budget=budget, label=f"prompt-selftest:{c}:{lang}",
                                   salt="universal-prompt-v1")
        reply = rec["data"]
        cum = cumulative_type(parse_period(p)[1])
        parsed = paste.parse(reply, cum, ctx["doc"]["period_end"])
        items, _, dropped, _ = verify_report(parsed["items"], [], ctx["pages"], ctx["doc"], ctx["template"],
                                             ctx["benchmarks"], ctx.get("prior"))
        paste.mark_no_source(items)
        complete = parsed["format"] == "json" and not parsed["bad"] and parsed["items"]
        ok_all &= bool(complete)
        (out_dir / f"{c}_{lang}.json").write_text(json.dumps(
            {"reply": reply, "parsed": parsed, "verified": items}, ensure_ascii=False, indent=1, default=str))
        print(f"== {m} {c} {p} ({ctx['template']}) cost ${rec.get('cost_usd') or 0:.4f}"
              f"{' (cached)' if rec.get('from_cache') else ''}")
        print(f"   format={parsed['format']} items={len(parsed['items'])} bad={len(parsed['bad'])} "
              f"absent={[(a['field'], a['period_type']) for a in parsed['absent']]} dropped={len(dropped)}")
        for b in parsed["bad"]:
            print(f"   BAD #{b['line']}: {b['why']}")
        print("   status:", dict(Counter(it.get("status") for it in items)))
        for it in items:
            if it.get("status") == "❌":
                print(f"   ❌ {it['field']} {it['period_type']} {it.get('category')}: {(it.get('reasons') or [''])[0][:90]}")
    print("all replies parsed completely:", ok_all)
    print(budget.status())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "zh")
