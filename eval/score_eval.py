"""Score an evaluation run and work out what needs human review.

Item set per report (eval_design §2.1): required fields x cumulative period, plus Q when the income
statement shows a Q column (verify.expected_pairs on the DeepSeek pipeline output), plus every item the
automatic key has, plus gross profit / insurance items that any cell answered.

Truth: US / A-share automatic key (XBRL / AKShare) + eval/answer_key_manual.json (HK and everything the
reviewer decided). An item without truth is "pending review" and is not scored yet.
Disputes: automatic truth exists, but >= 2 of the 3 DeepSeek cells agree on another value.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from earnings_agent.pipeline import prepare  # noqa: E402
from earnings_agent.templates import FIELDS  # noqa: E402
from earnings_agent.verify import expected_pairs  # noqa: E402
from score import answer_key, direct_preds, pipeline_preds, score_items, summarize  # noqa: E402

OUT = ROOT / "data" / "eval"
MANUAL = ROOT / "eval" / "answer_key_manual.json"
DS_CELLS = ["ds_simple", "ds_direct", "ds_pipeline"]
OPTIONAL = {"gross_profit", "insurance_revenue", "insurance_service_result"}


def load(run, cell, market, code):
    p = OUT / run / cell / f"{market}_{code}.json"
    return json.loads(p.read_text()) if p.exists() else None


def cell_preds(cell, obj):
    if obj is None:
        return {}
    return pipeline_preds(obj) if "pipeline" in cell else direct_preds(obj["parsed"])


def item_set(ctx, outputs, key):
    tpl = ctx["template"]
    pipe = outputs.get("ds_pipeline")
    items = set(expected_pairs(pipe["items"] if pipe else [], ctx["benchmarks"], tpl, ctx["doc"]))
    items |= {(k["field"], k["ptype"]) for k in key}
    cum = next((p for f, p in items if p != "Q"), None)
    for cell, obj in outputs.items():
        for (f, p), pr in cell_preds(cell, obj).items():
            if f in OPTIONAL and f in FIELDS[tpl] and p in (cum, "Q") and pr.get("value") is not None:
                if p == "Q" and (f, "Q") not in items and ("revenue", "Q") not in items:
                    continue
                items.add((f, p))
    return sorted(items, key=lambda x: (FIELDS[tpl].index(x[0]) if x[0] in FIELDS[tpl] else 99, x[1]))


def same(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9 * abs(b)


def analyse(run, cfg_reports, cells=DS_CELLS):
    manual = json.loads(MANUAL.read_text()) if MANUAL.exists() else {}
    per_report = []
    for r in cfg_reports:
        outputs = {c: load(run, c, r["market"], r["code"]) for c in cells}
        if not any(outputs.values()):
            continue
        ctx = prepare(r["market"], r["code"], r["period"])
        key = answer_key(ctx, manual)
        key_by = {(k["field"], k["ptype"]): k for k in key}
        items = item_set(ctx, outputs, key)
        preds = {c: cell_preds(c, o) for c, o in outputs.items()}
        disputes, pending = [], []
        for it in items:
            k = key_by.get(it)
            if k is None:
                pending.append(it)
                continue
            vals = [preds[c].get(it, {}).get("value") for c in cells]
            for v in vals:
                if v is not None and not same(v, k["value"], k["tol"]) and \
                        sum(same(w, v, k["tol"]) for w in vals) >= 2 and "人工" not in k["source"]:
                    disputes.append({"item": it, "truth": k["value"], "majority": v})
                    break
        scored_key = [k for k in key if (k["field"], k["ptype"]) in items]
        rows = {c: score_items(scored_key, preds[c], ctx["pages"]) for c in cells}
        per_report.append({"report": r, "ctx": ctx, "outputs": outputs, "key": scored_key, "items": items,
                           "pending": pending, "disputes": disputes, "rows": rows})
    return per_report


def score_run(run, cfg_reports=None):
    cfg = json.loads((ROOT / "eval" / "config.json").read_text())
    reps = analyse(run, cfg_reports or cfg["reports"])
    summary = {"run": run, "reports": len(reps),
               "pending_review": sum(len(x["pending"]) for x in reps),
               "disputes": sum(len(x["disputes"]) for x in reps), "cells": {}}
    for c in DS_CELLS:
        rows = [row for x in reps for row in x["rows"][c]]
        summary["cells"][c] = summarize(rows, pipeline="pipeline" in c)
    detail = [{"report": f"{x['report']['market']}:{x['report']['code']}", "items": x["items"],
               "pending": x["pending"], "disputes": x["disputes"],
               "rows": {c: x["rows"][c] for c in DS_CELLS}} for x in reps]
    (OUT / run / "scores.json").write_text(json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False,
                                                       indent=1, default=str))
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return reps
