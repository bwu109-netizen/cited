"""Glue between the web app and earnings_agent (imported, never modified).

- The visitor's own key builds the LLM client; replies are NOT written to the shared disk cache.
- Uploaded PDFs are parsed straight from a temp file (no parse cache) and the file is deleted afterwards.
- `payload()` turns a pipeline result into the plain dict the UI renders (R0 / R1 / R2 / page texts).
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone

from earnings_agent.benchmark import get_benchmark, get_prior
from earnings_agent.extract import build_followup_prompt, build_prompt
from earnings_agent.llm_client import LLMError, cost_usd, make_client
from earnings_agent.locate import select_pages
from earnings_agent.parse import load_doc_pages, pdf_pages
from earnings_agent.periods import cumulative_type, parse_period, period_end
from earnings_agent.pipeline import finish
from earnings_agent.sources import fetch_report
from earnings_agent.templates import AUX_FIELDS, FIELDS, choose_template
from earnings_agent.verify import verify_report

from . import insights

NAMES = {  # field -> (zh, en)
    "revenue": ("营业收入", "Revenue"), "net_income_parent": ("归母净利润", "Net income attributable"),
    "eps_basic": ("基本每股收益", "Basic EPS"), "gross_profit": ("毛利", "Gross profit"),
    "operating_cash_flow": ("经营活动现金流量净额", "Operating cash flow"),
    "net_interest_income": ("净利息收入", "Net interest income"), "ppop": ("拨备前利润", "Pre-provision profit"),
    "insurance_revenue": ("保险服务收入", "Insurance revenue"),
    "insurance_service_result": ("保险服务业绩", "Insurance service result"),
    "net_income_common": ("普通股股东应占净利润", "Net income to common shareholders"),
    "eps_basic_per_ads": ("每 ADS 基本收益", "Basic EPS per ADS"), "cost_of_revenue": ("营业成本", "Cost of revenue"),
    "weighted_avg_shares_basic": ("加权平均股数", "Weighted average shares"),
}


class FetchError(RuntimeError):
    pass


class Stopped(RuntimeError):
    pass


# ---------------------------------------------------------------- context (everything before the model call)

def _ctx(doc, pages):
    """Same steps as earnings_agent.pipeline.prepare, from already-loaded pages."""
    if not pages or not any(p["text"].strip() for p in pages):
        raise FetchError("scanned")
    selected, groups = select_pages(pages)
    by_num = {p["page"]: p["text"] for p in pages}
    template, tnotes = choose_template(doc.get("industry") or {}, [by_num[n] for n in groups.get("income", [])[:2]])
    try:
        benchmarks, bench_err = get_benchmark(doc, template)
    except Exception as e:  # noqa: BLE001  (no structured data: items stay ⚠️)
        benchmarks, bench_err = [], str(e)
    prior = get_prior(doc, template) if doc.get("extra") is not None else []
    system, user = build_prompt(doc, template, pages, selected)
    return {"doc": doc, "pages": pages, "selected": selected, "groups": groups, "template": template,
            "tnotes": tnotes, "benchmarks": benchmarks, "bench_err": bench_err, "prior": prior,
            "system": system, "user": user, "t0": time.time()}


def fetch_ctx(market, code, period):
    import requests

    try:
        doc = fetch_report(market, code, period)
        pages = load_doc_pages(doc)
    except requests.RequestException as e:
        raise FetchError("network|" + str(e)[:200])
    except Exception as e:  # noqa: BLE001  (source had no matching filing, or an unexpected listing format)
        msg = str(e)[:200]
        kind = "network" if any(k in msg for k in ("403", "429", "Timeout", "timed out", "Connection")) else "not_found"
        raise FetchError(f"{kind}|{type(e).__name__}: {msg}")
    return _ctx(doc, pages)


def doc_meta(market, code, period):
    """Filing metadata without downloading (needed for C4); a minimal doc when the source is unreachable."""
    try:
        doc = fetch_report(market, code, period, download=False)
        doc["path"] = None
        return doc
    except Exception:  # noqa: BLE001
        return {"market": market, "code": code, "name": code, "period": period,
                "period_end": period_end(period).isoformat(), "title": "PDF", "doc_kind": "upload",
                "industry": {}, "extra": None, "url": None, "path": None}


def upload_ctx(market, code, period, pdf_bytes, with_benchmark=True):
    """Pages from an uploaded PDF: parsed from a temp file that is deleted right away (no cache)."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)
        pages = pdf_pages(path)
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"pdf: {str(e)[:200]}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    doc = doc_meta(market, code, period) if (with_benchmark and code) else {
        "market": market, "code": code or "", "name": code or "PDF", "period": period,
        "period_end": period_end(period).isoformat(), "title": "PDF", "doc_kind": "upload",
        "industry": {}, "extra": None, "url": None, "path": None}
    doc["uploaded"] = True
    if market == "hk":  # HK structured data may be currency-converted: no C4 on uploads either
        doc["extra"] = None
    ctx = _ctx(doc, [{"page": p["page"], "text": p["text"]} for p in pages])
    if market == "hk" or not code:
        ctx["benchmarks"], ctx["prior"] = [], []
    return ctx


# ---------------------------------------------------------------- model calls

def client_for(ev):
    return make_client(ev.get("provider") or "deepseek", ev.get("key") or "", ev.get("model") or "",
                       ev.get("base_url") or "")


def call(client, system, user, job):
    if job.get("stop"):
        raise Stopped()
    last = None
    for _ in range(2):  # one retry when the reply is not valid JSON (same rule as the pipeline)
        t0 = datetime.now(timezone.utc)
        try:
            data, usage = client.complete_json(system, user)
        except LLMError as e:
            last = e
            if "valid JSON" not in str(e):
                raise
            continue
        c = cost_usd(usage, t0) or 0.0
        job["tokens"] = job.get("tokens", 0) + usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        job["cost"] = job.get("cost", 0.0) + c
        return {"data": data, "usage": usage, "cost_usd": c, "provider": client.name,
                "model": usage.get("model", client.model)}
    raise last


# Industry-metric names and rationales in both interface languages, so switching language needs no model call.
METRICS_NOTE = ("\n\n另外：industry_metrics 每一项除 name、rationale 外，再给中英文两版：name_zh、name_en、rationale_zh、"
                "rationale_en（意思相同；raw_value、raw_unit、quote 仍逐字照抄原文）。")


def run_pipeline(ctx, client, job, lang="zh"):
    """extract -> verify -> one follow-up for missing periods -> verify. Returns the finish() result.
    The only web-side prompt change: industry-metric names and rationales in Chinese and English."""
    job["stage"] = 3
    rec = call(client, ctx["system"], ctx["user"] + METRICS_NOTE, job)
    rec["lang"] = lang
    job["stage"] = 4
    data = rec.get("data") or {}
    items, _, _, _ = verify_report(list(data.get("items") or []), data.get("industry_metrics") or [], ctx["pages"],
                                   ctx["doc"], ctx["template"], ctx["benchmarks"], ctx["prior"])
    missing = [(i["field"], i["period_type"]) for i in items if i.get("category") == "漏抽"]
    fu = None
    if missing:
        job["stage"] = 5
        fs, fu_user = build_followup_prompt(ctx["doc"], ctx["template"], ctx["pages"], ctx["selected"], missing)
        fu = call(client, fs, fu_user, job)
    out = os.path.join(tempfile.gettempdir(), f"ea_{os.getpid()}_{time.time_ns()}.json")
    try:
        from pathlib import Path
        res = finish(ctx, rec, fu, missing, Path(out))
        res["_pages"] = ctx["pages"]
        res["_lang"] = lang
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    return res


# ---------------------------------------------------------------- payload for the UI

def _num(v):
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.4g}"


def _src(b):
    s = (b or {}).get("source") or ""
    return ("SEC XBRL", "SEC XBRL") if "SEC" in s else ("东财数据", "Eastmoney data") if s else ("结构化数据", "structured data")


SANITY_EN = [("毛利", "Gross profit is larger than revenue, or the cost used is negative."),
             ("拨备前利润", "Pre-provision profit is larger than revenue."),
             ("归母合计", "Parent net income vs ordinary shareholders check failed."),
             ("疑似只取了普通股口径", "Looks like only the ordinary-shareholder line was taken."),
             ("推导值", "Derived value differs from the total disclosed in the filing."),
             ("EPS", "EPS × weighted shares is far from net income (order of magnitude)."),
             ("单季", "Quarter + previous cumulative does not add up to the cumulative figure.")]


def _reason(it, market):
    """One sentence (zh, en) for ❌ / ⚠️ rows; product wording, numbers formatted."""
    cat, reasons, st = it.get("category"), it.get("reasons") or [], it.get("status")
    raw = it.get("raw_value") or ""
    b = it.get("benchmark") or {}
    if st == "⚠️":
        if market == "hk":
            return ("港股没有可靠的结构化数据：出处和单位已核验，没有外部数字可比。",
                    "HK has no reliable structured data: source and unit checked, no external figure to compare.")
        return ("出处和单位已核验，没有取到可比的结构化数据。",
                "Source and unit checked; no structured figure available to compare.")
    if st != "❌":
        return ("", "")
    fixed = {
        "数字编造": (f"数字 {raw} 在全文任何一页都找不到。", f"The number {raw} does not appear anywhere in the filing."),
        "页码错": ("数字在原文里，但不在给出的那一页。", "The number is in the filing, but not on the page given."),
        "引用改写": ("数字在那一页上，但引用句不是逐字原文。", "The number is on the page, but the quote is not verbatim."),
        "单位": ("单位或币种无法解析。", "The unit or currency could not be parsed."),
        "解析问题": ("数字在 PDF 抽出的文字里被拆开了。", "The number is split across lines in the PDF text."),
        "漏抽": ("按报告期应有这一项，但没有取到（已补问一次）。", "Expected for this period, but not extracted (asked once more)."),
        "无出处": ("没有给页码或原文引用，无法核对出处。", "No page or quote was given, so the source cannot be checked."),
    }
    if it.get("sanity"):
        txt = it["sanity"][0]
        en = next((e for k, e in SANITY_EN if k in txt), "Fails a consistency check.")
        return "合理性检查：" + txt, en
    if b and it.get("benchmark_state") == "mismatch" and cat in ("口径", "期间", "单位", None):
        zs, es = _src(b)
        extra = next((r.split("：", 1)[1] for r in reasons if r.startswith("标准答案不一致：")), "")
        tail_zh = "（符号相反）" if "符号相反" in extra else "（差 10 的整数次幂倍）" if "倍" in extra and "10^" in extra \
            else "（等于另一期间的值）" if cat == "期间" else ""
        tail_en = " (opposite sign)" if "符号相反" in extra else " (off by a power of ten)" if "10^" in extra \
            else " (matches another period)" if cat == "期间" else ""
        return (f"与 {zs} 不一致：原文 {_num(it.get('value'))}，{zs} {_num(b.get('value'))}{tail_zh}。",
                f"Differs from {es}: filing {_num(it.get('value'))} vs {es} {_num(b.get('value'))}{tail_en}.")
    if cat in fixed:
        return fixed[cat]
    return (reasons[0] if reasons else "未通过核验。", "Failed a check.")


def _unit(it):
    """Display unit (zh, en) from the parsed multiplier and currency; None keeps the unit as printed."""
    mult = it.get("multiplier")
    if mult is None and it.get("components"):
        mult = (it["components"][0] or {}).get("multiplier")
    per_share = it.get("field") in insights.PER_SHARE
    lab = insights.unit_label(it.get("currency"), mult, per_share)
    if lab:
        return lab
    if it.get("unit_kind") == "ratio":
        return "%", "%"
    sz, se = insights.SCALE.get(float(mult or 1), (None, None))
    return (sz, se) if sz else (None, None)


def _item(it, market):
    zh_name, en_name = NAMES.get(it["field"], (it["field"], it["field"]))
    uz, ue = _unit(it)
    zh, en = _reason(it, market)
    page = it.get("page_used") or it.get("page")
    b = it.get("benchmark") or None
    return {
        "field": it["field"], "name_zh": zh_name, "name_en": en_name, "aux": it["field"] in AUX_FIELDS,
        "ptype": it.get("period_type"), "period_end": it.get("period_end"),
        "raw": it.get("raw_value"), "unit": it.get("raw_unit"), "currency_raw": it.get("raw_currency"),
        "unit_zh": uz, "unit_en": ue,
        "value": it.get("value"), "currency": it.get("currency"), "page": page, "quote": it.get("quote"),
        "status": it.get("status"), "category": it.get("category"), "reason_zh": zh, "reason_en": en,
        "reasons": it.get("reasons") or [], "derived": it.get("derivation") == "derived",
        "formula": it.get("formula"),
        "components": [{"name": c.get("name"), "raw": c.get("raw_value"), "unit": c.get("raw_unit"),
                        "page": c.get("page_used") or c.get("page"), "quote": c.get("quote"),
                        "ok": bool(c.get("c1") and c.get("c2") and c.get("c3"))} for c in it.get("components") or []],
        "bench": {"value": b.get("value"), "source": b.get("source"), "field": b.get("source_field")} if b else None,
    }


ORDER = {"❌": 0, "⚠️": 1, "✅": 2}


def payload(res, pages_texts=True):
    doc, market = res["doc"], res["doc"]["market"]
    tpl = res["template"]
    core = FIELDS[tpl]
    items = [_item(i, market) for i in res["items"]]
    items.sort(key=lambda x: (ORDER.get(x["status"], 3), x["aux"],
                              core.index(x["field"]) if x["field"] in core else 99, x["ptype"] != "Q"))
    lang = (res.get("llm") or {}).get("lang") or res.get("_lang")
    metrics = [{"name": m.get("name"), "rationale": m.get("rationale"), "lang": lang, "raw": m.get("raw_value"),
                **{k: m.get(k) for k in ("name_zh", "name_en", "rationale_zh", "rationale_en") if m.get(k)},
                "unit": m.get("raw_unit"), "unit_zh": _unit(m)[0], "unit_en": _unit(m)[1],
                "ptype": m.get("period_type"), "page": m.get("page_used") or m.get("page"),
                "quote": m.get("quote"), "status": m.get("status"),
                "reason_zh": (m.get("reasons") or [""])[0]} for m in res.get("industry_metrics") or []]
    pages = {}
    if pages_texts:
        want = {i["page"] for i in items if i["page"]} | {c["page"] for i in items for c in i["components"] if c["page"]} \
            | {m["page"] for m in metrics if m["page"]} \
            | {c["page"] for c in (res.get("comparatives") or {}).get("items") or [] if c.get("page")}
        by = {p["page"]: p["text"] for p in res.get("_pages", [])}
        pages = {str(n): by[n] for n in sorted(want) if n in by}
    counts = {k: sum(1 for i in items if i["status"] == k) for k in ("❌", "⚠️", "✅")}
    llm = res.get("llm") or {}
    out = {
        "doc": {k: doc.get(k) for k in ("market", "code", "name", "period", "period_end", "title", "doc_kind",
                                        "filed", "url")},
        "uploaded": bool(doc.get("uploaded")), "template": tpl,
        "pages_total": res.get("pages_total"), "pages_sent": len(res.get("pages_sent") or []),
        "cost": llm.get("cost_usd"), "model": llm.get("model"), "provider": llm.get("provider"),
        "followup": res.get("followup"), "counts": counts,
        "core_counts": {k: sum(1 for i in items if i["status"] == k and not i["aux"]) for k in ("❌", "⚠️", "✅")},
        "aux_bad": sum(1 for i in items if i["status"] == "❌" and i["aux"]),
        "items": items, "metrics": metrics, "pages": pages,
        "cum": cumulative_type(parse_period(doc["period"])[1]),
    }
    return insights.enrich(out, res)


def extras(ctx, res, client, job):
    """Prior-year figures (one call, C1–C3 checked) before payload(); errors never break the result."""
    job["stage"] = 6
    try:
        res["comparatives"] = insights.comparatives(ctx, res, lambda s, u: call(client, s, u, job)["data"])
    except LLMError as e:
        res["comparatives"] = {"items": [], "rejected": [], "error": str(e)[:200]}


def add_highlights(pl, client, job):
    try:
        pl["highlights"] = insights.highlights(pl, lambda s, u: call(client, s, u, job)["data"])
    except LLMError as e:
        pl["highlights"] = {"points": [], "dropped": [], "error": str(e)[:200]}
    return pl
