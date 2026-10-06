"""extract = fetch -> parse -> locate -> template -> model -> unit conversion -> verify.

Split into prepare() (everything before the model call) and finish() (verification, optional
follow-up, output), so the same steps serve synchronous calls and Anthropic batches.
"""
import json
import time

from . import config
from .benchmark import get_benchmark, get_prior
from .extract import build_followup_prompt, build_prompt
from .llm_client import cached_complete_json
from .locate import select_pages
from .parse import load_doc_pages
from .sources import fetch_report
from .templates import choose_template
from .verify import verify_report


def _sum_usage(recs):
    keys = ("input_tokens", "cached_input_tokens", "output_tokens")
    u = {k: sum((r.get("usage") or {}).get(k, 0) for r in recs) for k in keys}
    u["model"] = recs[0].get("model")
    return u


def prepare(market, code, period):
    doc = fetch_report(market, code, period)
    pages = load_doc_pages(doc)
    selected, groups = select_pages(pages)
    by_num = {p["page"]: p["text"] for p in pages}
    template, tnotes = choose_template(doc["industry"], [by_num[n] for n in groups.get("income", [])[:2]])
    benchmarks, bench_err = get_benchmark(doc, template)
    prior = get_prior(doc, template)
    system, user = build_prompt(doc, template, pages, selected)
    return {"doc": doc, "pages": pages, "selected": selected, "groups": groups, "template": template,
            "tnotes": tnotes, "benchmarks": benchmarks, "bench_err": bench_err, "prior": prior,
            "system": system, "user": user, "t0": time.time()}


def verify(ctx, raw_items, raw_metrics):
    return verify_report(raw_items, raw_metrics, ctx["pages"], ctx["doc"], ctx["template"],
                         ctx["benchmarks"], ctx["prior"])


def missing_after(ctx, rec):
    data = rec.get("data") or {}
    items, _, _, _ = verify(ctx, list(data.get("items") or []), data.get("industry_metrics") or [])
    return [(i["field"], i["period_type"]) for i in items if i.get("category") == "漏抽"]


def followup_prompt(ctx, missing):
    return build_followup_prompt(ctx["doc"], ctx["template"], ctx["pages"], ctx["selected"], missing)


def finish(ctx, rec, followup=None, missing=None, out_path=None):
    """rec: reply to the extraction prompt; followup: reply to the follow-up prompt (or None)."""
    data = rec.get("data") or {}
    raw_items, raw_metrics = list(data.get("items") or []), data.get("industry_metrics") or []
    calls = [rec]
    fu_info = None
    if followup is not None:
        calls.append(followup)
        extra = (followup.get("data") or {}).get("items") or []
        raw_items += extra
        fu_info = {"asked": missing, "returned": len(extra), "not_found": (followup.get("data") or {}).get("not_found")}
    items, metrics, dropped, bench_invalid = verify(ctx, raw_items, raw_metrics)
    for it in items:
        if missing and (it["field"], it.get("period_type")) in missing and it.get("category") != "漏抽":
            it.setdefault("notes", []).append("补问后取得")
    by_num = {p["page"]: p["text"] for p in ctx["pages"]}
    result = {
        "doc": ctx["doc"], "template": ctx["template"], "template_notes": ctx["tnotes"],
        "pages_total": len(ctx["pages"]), "pages_sent": ctx["selected"], "page_groups": ctx["groups"],
        "chars_sent": sum(len(by_num[n]) for n in ctx["selected"]),
        "prompt_size": {"system_chars": len(ctx["system"]), "user_chars": len(ctx["user"])},
        "business_summary": data.get("business_summary"),
        "items": items, "industry_metrics": metrics, "dropped": dropped,
        "benchmarks": ctx["benchmarks"], "benchmark_error": ctx["bench_err"], "benchmark_invalid": bench_invalid,
        "prior": ctx["prior"], "followup": fu_info,
        "llm": {"provider": rec.get("provider"), "model": rec.get("model"), "calls": len(calls),
                "usage": _sum_usage(calls), "cost_usd": sum(c.get("cost_usd") or 0 for c in calls),
                "from_cache": all(c.get("from_cache") for c in calls),
                "errors": [c.get("error") for c in calls if c.get("error")]},
        "elapsed_sec": round(time.time() - ctx["t0"], 1),
    }
    d = ctx["doc"]
    out = out_path or config.OUTPUT_DIR / f"{d['market']}_{d['code']}_{d['period']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    result["output_path"] = str(out)
    return result


def extract(market, code, period, use_llm_cache=True, providers=None, budget=None, salt="", out_path=None):
    """Synchronous run (DeepSeek / Gemini / any client in llm_client)."""
    ctx = prepare(market, code, period)
    label = f"pipeline:{market}:{code}:{period}"
    rec = cached_complete_json(ctx["system"], ctx["user"], providers=providers, use_cache=use_llm_cache,
                               budget=budget, label=label, salt=salt)
    missing = missing_after(ctx, rec)
    followup = None
    if missing:  # ask once more for the missing pairs only; still missing afterwards = 漏抽
        fs, fu = followup_prompt(ctx, missing)
        followup = cached_complete_json(fs, fu, providers=providers, use_cache=use_llm_cache, budget=budget,
                                        label=label + ":followup", salt=salt)
    return finish(ctx, rec, followup, missing, out_path)
