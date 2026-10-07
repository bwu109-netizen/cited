"""The page is one Streamlit custom component (web/ui). It sends events; jobs run in background threads
that only mutate a plain dict in session state; a fragment re-renders the component every second while
something runs. Pattern from tea-review-insight (src/web_app.py).

Events: lang, nav, analyze, upload, stop, compare, compare_upload, verify, page, reset, ack.
The visitor's API key travels inside the event and lives only in this session's memory.
"""
from __future__ import annotations

import base64
import io
import json
import threading
import time
import warnings
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

warnings.filterwarnings("ignore")

from earnings_agent.llm_client import PROVIDERS, LLMError  # noqa: E402
from earnings_agent.periods import cumulative_type, parse_period  # noqa: E402
from earnings_agent.verify import verify_report  # noqa: E402

from . import core, fx, paste  # noqa: E402

HERE = Path(__file__).resolve().parent
_component = components.declare_component("earnings_checker", path=str(HERE / "ui"))
EXAMPLES = {p.stem: json.loads(p.read_text()) for p in sorted((HERE / "examples").glob("*.json"))}
EVAL = json.loads((HERE / "eval_numbers.json").read_text())
GITHUB = "https://github.com/"  # set at deploy time (PRD §14: repo name confirmed before pushing)

PAGE_CSS = """<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer {display:none !important;}
html, body, .stApp, [data-testid="stAppViewContainer"] {background:#0d0e11 !important; overflow:hidden !important;}
[data-testid="stMainBlockContainer"], .block-container {padding:0 !important; max-width:100% !important;}
iframe[data-testid="stCustomComponentV1"] {position:fixed; inset:0; width:100vw !important; height:100vh !important; height:100dvh !important; border:0; z-index:5;}
[data-stale="true"] {opacity:1 !important; transition:none !important;}
</style>"""


# ---------------------------------------------------------------- helpers

def _err_kind(msg):
    low = msg.lower()
    if "http 401" in low or "http 403" in low or "api key" in low or "key is empty" in low or "unauthorized" in low:
        return "key"
    if "http 404" in low or "model" in low and "not" in low:
        return "model"
    if "base url is empty" in low:
        return "base"
    if "http 402" in low or "http 429" in low or "quota" in low or "balance" in low or "rate limit" in low:
        return "quota"
    return "general"


def _render_page(ctx, n):
    """PNG (base64) of page n when the source is a PDF on disk; None otherwise (SEC HTML, uploads)."""
    doc = ctx["doc"]
    pg = next((p for p in ctx["pages"] if p["page"] == n), None)
    if pg is None:
        return None
    parts = [p["path"] for p in doc.get("parts") or []] or [doc.get("path")]
    path = parts[(pg.get("part") or 1) - 1] if parts else None
    if not path or not str(path).lower().endswith(".pdf"):
        return None
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            im = pdf.pages[(pg.get("part_page") or n) - 1].to_image(resolution=110).original
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None


def _new_job(kind):
    jid = st.session_state.get("job", {}).get("id", 0) + 1
    return dict(id=jid, kind=kind, status="running", stage=1, stop=False, error=None, error_kind=None,
                tokens=0, cost=0.0, t0=time.time(), result=None, rows=None, meta=None)


# ---------------------------------------------------------------- single analysis

def _single(job, ev, pdf_bytes=None):
    market, code, period = ev["market"], ev["code"].strip(), ev["period"]
    try:
        if pdf_bytes is None:
            job["stage"] = 1
            ctx = core.fetch_ctx(market, code, period)
        else:
            job["stage"] = 2
            ctx = core.upload_ctx(market, code, period, pdf_bytes)
        job["stage"] = 2
        job["meta"] = {"pages": len(ctx["pages"]), "title": ctx["doc"].get("title"), "name": ctx["doc"].get("name"),
                       "selected": len(ctx["selected"]), "template": ctx["template"]}
        job["_ctx"] = ctx
        client = core.client_for(ev)
        res = core.run_pipeline(ctx, client, job)
        job["result"] = core.payload(res)
        job["status"] = "done"
    except core.FetchError as e:
        msg = str(e)
        job.update(status="fetch_failed", error=msg, error_kind="scanned" if msg == "scanned" else "fetch")
    except core.Stopped:
        job.update(status="stopped")
    except (LLMError, RuntimeError, KeyError, ValueError) as e:
        job.update(status="error", error=str(e)[:400], error_kind=_err_kind(str(e)))


# ---------------------------------------------------------------- compare

def _compare_row(job, row, ev, pdf_bytes=None):
    row.update(status="running", error=None)
    try:
        ctx = (core.upload_ctx(row["market"], row["code"], ev["period"], pdf_bytes) if pdf_bytes
               else core.fetch_ctx(row["market"], row["code"], ev["period"]))
        res = core.run_pipeline(ctx, core.client_for(ev), job)
        pl = core.payload(res)
        cum = cumulative_type(parse_period(ev["period"])[1])
        cells = {}
        for it in pl["items"]:
            if not it["aux"] and it["ptype"] == cum and it["field"] not in cells:
                cells[it["field"]] = it
        listing = fx.LISTING_CCY[row["market"]]
        rates = {}
        for it in cells.values():
            ccy = it.get("currency")
            if ccy and ccy not in rates:
                rates[ccy] = fx.rate(ccy, listing, pl["doc"]["period_end"] or "")
        row.update(status="done", name=pl["doc"].get("name"), template=pl["template"], counts=pl["counts"],
                   period_end=pl["doc"]["period_end"], title=pl["doc"]["title"], cells=cells, rates=rates,
                   listing=listing, result=pl)
    except core.FetchError as e:
        row.update(status="fetch_failed", error=str(e)[:300])
    except core.Stopped:
        row.update(status="stopped")
    except (LLMError, RuntimeError, KeyError, ValueError) as e:
        row.update(status="error", error=str(e)[:300], error_kind=_err_kind(str(e)))


def _compare(job, ev):
    for row in job["rows"]:
        if job["stop"]:
            row["status"] = "stopped"
            continue
        _compare_row(job, row, ev)
        if row.get("error_kind") in ("key", "model", "base"):  # same key / model for every row: stop here
            job.update(error=row["error"], error_kind=row["error_kind"])
            for rest in job["rows"]:
                if rest["status"] == "queued":
                    rest["status"] = "skipped"
            break
    job["status"] = "done"


# ---------------------------------------------------------------- verify (no model)

def _verify(job, ev, pdf_bytes):
    market, period, code = ev["market"], ev["period"], (ev.get("code") or "").strip()
    try:
        ctx = core.upload_ctx(market, code, period, pdf_bytes, with_benchmark=market in ("us", "a") and bool(code))
        if ev.get("template") in ("general", "bank", "insurance"):
            ctx["template"] = ev["template"]
        cum = cumulative_type(parse_period(period)[1])
        parsed = paste.parse(ev.get("text") or "", cum, ctx["doc"]["period_end"], ev.get("mapping") or None)
        if parsed["needs_mapping"]:
            job.update(status="needs_mapping", result={"columns": parsed["columns"], "roles": parsed["roles"]})
            return
        items, _, _, _ = verify_report(parsed["items"], [], ctx["pages"], ctx["doc"], ctx["template"],
                                       ctx["benchmarks"], ctx["prior"])
        paste.mark_no_source(items)
        res = {"doc": ctx["doc"], "template": ctx["template"], "items": items, "industry_metrics": [],
               "pages_total": len(ctx["pages"]), "pages_sent": [], "llm": {}, "_pages": ctx["pages"]}
        pl = core.payload(res)
        did_c4 = bool(ctx["benchmarks"])
        pl["verify"] = {"bad_rows": parsed["bad"], "format": parsed["format"], "c4": did_c4,
                        "c4_reason": None if did_c4 else ("hk" if market == "hk" else "no_code" if not code else "no_data"),
                        "n_rows": len(parsed["items"]) + len(parsed["bad"])}
        job["_ctx"] = ctx
        job.update(result=pl, status="done")
    except core.FetchError as e:
        job.update(status="fetch_failed", error=str(e), error_kind="scanned" if str(e) == "scanned" else "pdf")
    except Exception as e:  # noqa: BLE001  (pure code: report any failure instead of crashing the page)
        job.update(status="error", error=str(e)[:400], error_kind="general")


# ---------------------------------------------------------------- events

def _b64(s):
    return base64.b64decode(s.split(",", 1)[-1]) if s else None


def _handle(ev):
    ss = st.session_state
    if not isinstance(ev, dict) or ev.get("id", 0) <= ss.handled:
        return False
    ss.handled = ev["id"]
    typ = ev.get("type")
    if typ == "lang":
        ss.lang = ev.get("lang", "zh")
    elif typ in ("analyze", "upload"):
        job = _new_job("single")
        job["query"] = {k: ev.get(k) for k in ("market", "code", "period", "provider", "model")}
        ss.job, ss.page_view = job, None
        threading.Thread(target=_single, daemon=True, args=(job, ev, _b64(ev.get("pdf")) if typ == "upload" else None)).start()
    elif typ == "compare":
        job = _new_job("compare")
        job["rows"] = [{"market": r["market"], "code": r["code"].strip(), "status": "queued"} for r in ev["rows"]][:10]
        job["query"] = {"period": ev["period"], "provider": ev.get("provider")}
        ss.job, ss.compare_ev = job, {k: v for k, v in ev.items() if k != "rows"}
        threading.Thread(target=_compare, daemon=True, args=(job, ev)).start()
    elif typ == "compare_upload" and ss.get("job", {}).get("kind") == "compare":
        job, i = ss.job, int(ev["index"])
        job["status"] = "running"
        prev = dict(ss.get("compare_ev") or {}, key=ev.get("key") or (ss.get("compare_ev") or {}).get("key"))

        def run():
            _compare_row(job, job["rows"][i], prev, _b64(ev.get("pdf")))
            job["status"] = "done"
        threading.Thread(target=run, daemon=True).start()
    elif typ == "verify":
        job = _new_job("verify")
        ss.job, ss.page_view = job, None
        threading.Thread(target=_verify, daemon=True, args=(job, ev, _b64(ev.get("pdf")))).start()
    elif typ == "stop" and ss.get("job"):
        ss.job["stop"] = True
    elif typ == "page":
        ctx = ss.get("job", {}).get("_ctx")
        n = int(ev.get("n", 0))
        if ctx:
            text = next((p["text"] for p in ctx["pages"] if p["page"] == n), None)
            ss.page_view = {"n": n, "total": len(ctx["pages"]), "text": text, "img": _render_page(ctx, n),
                            "job": ss.job["id"]}
    elif typ == "reset":
        ss.job = {"id": ss.get("job", {}).get("id", 0), "status": "idle"}
        ss.page_view = None
    return typ != "ack"


def main():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    ss = st.session_state
    ss.setdefault("handled", 0)
    ss.setdefault("job", {"id": 0, "status": "idle"})
    ss.setdefault("lang", "zh")
    ss.setdefault("page_view", None)
    running = ss.job.get("status") == "running"
    cfg = {"providers": {k: {"label": v["label"], "model": v.get("model", ""), "key_url": v.get("key_url", ""),
                             "base": bool(v.get("base_url"))} for k, v in PROVIDERS.items()},
           "examples": EXAMPLES, "eval": EVAL, "github": GITHUB}

    def ui_body():
        job = ss.job
        public = {k: v for k, v in job.items() if not k.startswith("_") and k not in ("t0",)}
        public["elapsed"] = round(time.time() - job["t0"], 1) if job.get("t0") else None
        ev = _component(cfg=cfg, job=public, page_view=ss.page_view, handled=ss.handled, lang=ss.lang,
                        key="earnings_checker", default=None)
        if _handle(ev) or (running and job.get("status") != "running"):
            st.rerun()

    st.fragment(run_every=1.0 if running else None)(ui_body)()
