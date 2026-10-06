"""extract = fetch -> parse -> locate -> template -> model -> unit conversion -> verify."""
import json
import time

from . import config
from .benchmark import get_benchmark, get_prior
from .extract import run_extraction, run_followup
from .locate import select_pages
from .parse import load_pages
from .sources import fetch_report
from .templates import choose_template
from .verify import verify_report


def _sum_usage(recs):
    keys = ("input_tokens", "cached_input_tokens", "output_tokens")
    u = {k: sum((r.get("usage") or {}).get(k, 0) for r in recs) for k in keys}
    u["model"] = recs[0].get("model")
    return u


def extract(market, code, period, use_llm_cache=True):
    t0 = time.time()
    doc = fetch_report(market, code, period)
    pages = load_pages(doc["path"])
    selected, groups = select_pages(pages)
    by_num = {p["page"]: p["text"] for p in pages}
    template, tnotes = choose_template(doc["industry"], [by_num[n] for n in groups.get("income", [])[:2]])
    benchmarks, bench_err = get_benchmark(doc, template)
    prior = get_prior(doc, template)
    llm, prompt_size = run_extraction(doc, template, pages, selected, use_cache=use_llm_cache)
    data = llm["data"] or {}
    raw_items, raw_metrics = list(data.get("items") or []), data.get("industry_metrics") or []
    items, metrics, dropped, bench_invalid = verify_report(raw_items, raw_metrics, pages, doc, template,
                                                           benchmarks, prior)
    calls, followup = [llm], None
    missing = [(i["field"], i["period_type"]) for i in items if i.get("category") == "漏抽"]
    if missing:  # ask once more for the missing pairs only; still missing afterwards = 漏抽
        f = run_followup(doc, template, pages, selected, missing, use_cache=use_llm_cache)
        calls.append(f)
        extra = (f["data"] or {}).get("items") or []
        followup = {"asked": missing, "returned": len(extra), "not_found": (f["data"] or {}).get("not_found")}
        items, metrics, dropped, bench_invalid = verify_report(raw_items + extra, raw_metrics, pages, doc, template,
                                                               benchmarks, prior)
        for it in items:
            if (it["field"], it.get("period_type")) in missing and it.get("category") != "漏抽":
                it.setdefault("notes", []).append("补问后取得")
    result = {
        "doc": doc, "template": template, "template_notes": tnotes,
        "pages_total": len(pages), "pages_sent": selected, "page_groups": groups,
        "chars_sent": sum(len(by_num[n]) for n in selected), "prompt_size": prompt_size,
        "business_summary": data.get("business_summary"),
        "items": items, "industry_metrics": metrics, "dropped": dropped,
        "benchmarks": benchmarks, "benchmark_error": bench_err, "benchmark_invalid": bench_invalid, "prior": prior,
        "followup": followup,
        "llm": {"provider": llm.get("provider"), "model": llm.get("model"), "calls": len(calls),
                "usage": _sum_usage(calls), "cost_usd": sum(c.get("cost_usd") or 0 for c in calls),
                "from_cache": all(c.get("from_cache") for c in calls)},
        "elapsed_sec": round(time.time() - t0, 1),
    }
    out = config.OUTPUT_DIR / f"{market}_{code}_{period}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    result["output_path"] = str(out)
    return result
