"""Scoring (docs/eval_design.md §6): answer key, two-tier correctness, fabrication, flag metrics.

answer_key(ctx, manual)          -> list of truth items {field, ptype, value, currency, strict_tol, source}
score_items(key, preds, pages)   -> per-item rows
summarize(rows)                  -> metrics for one cell
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from earnings_agent.templates import FIELDS  # noqa: E402
from earnings_agent.textnorm import for_numbers  # noqa: E402
from earnings_agent.units import UnitError, digits_of, to_value  # noqa: E402

APPROX_REL = 0.01
SCALES = (1, 1e3, 1e4, 1e6, 1e8, 1e9)
PER_SHARE = {"eps_basic"}


def _doc_numbers(pages):
    """Set of every whole number string in the document (thousands separators removed)."""
    nums = set()
    for p in pages:
        nums.update(re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d])", for_numbers(p["text"])))
    return nums


def printed_tolerances(value, field, doc_nums):
    """Half-unit tolerances of every printed representation of `value` found in the document."""
    out = []
    scales = (1,) if field in PER_SHARE else SCALES
    for s in scales:
        v = abs(value) / s
        for d in range(0, 5 if field in PER_SHARE else 4):
            txt = f"{v:.{d}f}"
            sig = len(txt.replace(".", "").lstrip("0"))
            if sig < (2 if field in PER_SHARE else 4):
                continue
            if txt in doc_nums and abs(float(txt) * s - abs(value)) <= 0.5 * 10 ** -d * s + 1e-9 * abs(value):
                out.append((0.5 * 10 ** -d * s, f"{txt} × {s:g}"))
    return out


def answer_key(ctx, manual):
    doc, template = ctx["doc"], ctx["template"]
    fields = FIELDS[template]
    key = {}
    if doc["market"] in ("us", "a"):
        for b in ctx["benchmarks"]:
            if b["field"] in fields and b["period_end"][:7] == doc["period_end"][:7]:
                key.setdefault((b["field"], b["period_type"]),  # first currency listed = reporting currency
                               {"field": b["field"], "ptype": b["period_type"], "value": b["value"],
                                "currency": b.get("currency"), "source": f"{b['source']} {b['source_field']}",
                                "tol": None})
    for m in manual.get(f"{doc['market']}:{doc['code']}:{doc['period']}", []):
        k = (m["field"], m["ptype"])
        if m.get("na"):
            key.pop(k, None)
            continue
        value, _, _, tol = to_value(m["raw"], m["unit"])
        key[k] = {"field": m["field"], "ptype": m["ptype"], "value": value, "currency": m["currency"],
                  "source": "人工" + (f"（{m['note']}）" if m.get("note") else ""), "tol": m.get("tol") or tol}
    nums = _doc_numbers(ctx["pages"])
    for it in key.values():
        reps = printed_tolerances(it["value"], it["field"], nums)
        it["printed_as"] = [r[1] for r in reps]
        if it["tol"] is None:
            it["tol"] = max([r[0] for r in reps]) if reps else 5e-6 * abs(it["value"])
    return sorted(key.values(), key=lambda x: (fields.index(x["field"]), x["ptype"]))


def in_document(pred, doc_nums):
    """Is the predicted number (as written, or any scaled rendering) somewhere in the report?"""
    raw = pred.get("raw_value")
    if raw:
        try:
            if digits_of(raw) in doc_nums:
                return True
        except UnitError:
            pass
    v = pred.get("value")
    if v is None:
        return False
    return bool(printed_tolerances(v, pred.get("field", ""), doc_nums)) or any(
        f"{abs(v) / s:.{d}f}" in doc_nums for s in SCALES for d in range(0, 3) if abs(v) / s >= 100)


def score_items(key, preds, pages):
    """preds: {(field, ptype): {value, currency, raw_value, status?, flagged?, flagged_no_c4?, ...}}"""
    nums = _doc_numbers(pages)
    rows = []
    for t in key:
        p = preds.get((t["field"], t["ptype"]))
        row = {"field": t["field"], "ptype": t["ptype"], "truth": t["value"], "truth_currency": t["currency"],
               "truth_source": t["source"], "strict_tol": t["tol"], "printed_as": t.get("printed_as"),
               "pred": None, "pred_currency": None, "pred_raw": None, "answered": False,
               "strict": False, "approx": False, "fabricated": False, "note": ""}
        if p and p.get("value") is not None:
            row.update(pred=p["value"], pred_currency=p.get("currency"), pred_raw=p.get("raw_value"), answered=True)
            if t["currency"] and p.get("currency") and p["currency"] != t["currency"]:
                row["note"] = f"币种不同：{p['currency']} vs {t['currency']}"
            else:
                diff = abs(p["value"] - t["value"])
                row["strict"] = diff <= t["tol"] + 1e-9 * abs(t["value"])
                row["approx"] = diff <= APPROX_REL * abs(t["value"])
            if not row["approx"]:
                row["fabricated"] = not in_document(dict(p, field=t["field"]), nums)
        elif p:
            row["note"] = p.get("status") or "未作答"
        for k in ("status", "category", "flagged", "flagged_no_c4"):
            if p and k in p:
                row[k] = p[k]
        rows.append(row)
    return rows


def pipeline_preds(result):
    preds = {}
    for it in result["items"]:
        key = (it["field"], it.get("period_type"))
        if key in preds and preds[key].get("value") is not None:
            continue
        no_c4 = (not (it.get("c1") and it.get("c2") and it.get("c3"))) or bool(it.get("sanity")) \
            or it.get("category") == "漏抽"
        preds[key] = {"value": it.get("value"), "currency": it.get("currency"), "raw_value": it.get("raw_value"),
                      "status": it.get("status"), "category": it.get("category"),
                      "flagged": it.get("status") == "❌", "flagged_no_c4": no_c4}
    return preds


def direct_preds(parsed):
    preds = {}
    for it in parsed:
        key = (it.get("field"), it.get("period_type"))
        if key in preds and preds[key].get("value") is not None:
            continue
        preds[key] = it
    return preds


def summarize(rows, pipeline=False):
    n = len(rows)
    answered = [r for r in rows if r["answered"]]
    wrong = [r for r in rows if not r["strict"]]
    s = {"items": n, "strict": sum(r["strict"] for r in rows), "approx": sum(r["approx"] for r in rows),
         "answered": len(answered), "fabricated": sum(r["fabricated"] for r in answered), "wrong": len(wrong)}
    s["strict_acc"] = s["strict"] / n if n else None
    s["approx_acc"] = s["approx"] / n if n else None
    s["fab_rate"] = s["fabricated"] / len(answered) if answered else None
    if pipeline:
        flagged = [r for r in rows if r.get("flagged")]
        s["wrong_flagged"] = sum(1 for r in wrong if r.get("flagged"))
        s["wrong_flagged_no_c4"] = sum(1 for r in wrong if r.get("flagged_no_c4"))
        s["flag_recall"] = s["wrong_flagged"] / len(wrong) if wrong else None
        s["flag_recall_no_c4"] = s["wrong_flagged_no_c4"] / len(wrong) if wrong else None
        s["false_alarm"] = sum(1 for r in flagged if r["strict"]) / len(flagged) if flagged else None
        s["silent_errors"] = sum(1 for r in wrong if not r.get("flagged") and r["answered"])
    return s
