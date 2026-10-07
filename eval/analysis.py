"""Analysis on top of a scores.json (not frozen: it only reads frozen outputs, never changes a score).

- three_metrics(rows, flags): silent-error rate, review workload, flag recall — for every tier
  (direct-ask tiers have no flags: all their errors are silent, workload 0, recall 0)
- false_alarms(run, cell, detail): pipeline ❌ that were strict-correct, counted by the check that fired
- stability(runs, cell, reports): agreement across repeated runs
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "eval"
FLAGGED_CELLS = ("pipeline", "verified")


def has_flags(cell):
    return any(k in cell for k in FLAGGED_CELLS)


def three_metrics(rows, flags):
    """Definitions (eval_design §10.1):
    error         = not strict-correct (unanswered counts as an error)
    silent error  = answered with a wrong number and not flagged ❌ (an empty answer is visible, not silent)
    silent rate   = silent errors / all scored items
    workload      = flagged items / all scored items (what an analyst must re-check)
    flag recall   = flagged errors / all errors"""
    n = len(rows)
    flagged = [r for r in rows if flags and r.get("flagged")]
    wrong = [r for r in rows if not r["strict"]]
    silent = [r for r in wrong if r["answered"] and not (flags and r.get("flagged"))]
    out = {"items": n, "errors": len(wrong), "flagged": len(flagged), "silent": len(silent),
           "silent_rate": len(silent) / n if n else None,
           "workload": len(flagged) / n if n else None,
           "flag_recall": (sum(1 for r in wrong if flags and r.get("flagged")) / len(wrong)) if wrong else None,
           "false_alarm_share": (sum(1 for r in flagged if r["strict"]) / len(flagged)) if flagged else None}
    if flags:
        nc4 = [r for r in rows if r.get("flagged_no_c4")]
        out["flagged_no_c4"] = len(nc4)
        out["flag_recall_no_c4"] = (sum(1 for r in wrong if r.get("flagged_no_c4")) / len(wrong)) if wrong else None
        out["silent_no_c4"] = sum(1 for r in wrong if r["answered"] and not r.get("flagged_no_c4"))
    return out


# ---------------------------------------------------------------- what made an item ❌

SANITY_NAMES = [
    (r"毛利 .* 大于营业收入|营业成本为负数", "S1 毛利≤营收/成本≥0"),
    (r"拨备前利润 .* 大于营业收入", "S1b 拨备前利润≤营收"),
    (r"归母合计|疑似只取了普通股口径", "S2 归母≥普通股"),
    (r"推导值 .* 与报告明示的数不一致", "S3 推导值=明示值"),
    (r"EPS × 加权股数", "S4 EPS×股数≈净利润"),
    (r"单季 .* 累计", "S5 单季+上季累计≈累计"),
]


def triggers(it):
    """Every check that failed on a ❌ item."""
    if it.get("category") == "漏抽":
        return ["漏抽"]
    t = []
    comp = it.get("derivation") == "derived" and it.get("components")
    for k, name in (("c1", "C1 引用在页上"), ("c2", "C2 数字在页上"), ("c3", "C3 单位/币种")):
        if comp:
            if not all(c.get(k) for c in it["components"]):
                t.append(name + "（组成项）")
        elif not it.get(k):
            t.append(name)
    if it.get("benchmark_state") == "mismatch":
        t.append("C4 标准答案")
    for reason in it.get("sanity") or []:
        t.append(next((n for p, n in SANITY_NAMES if re.search(p, reason)), "S? " + reason[:20]))
    for reason in it.get("reasons") or []:
        if "回答给出的计算结果" in reason:
            t.append("R3 计算结果≠组成项重算")
    return t or ["（未识别）"]


def first_item(items, field, ptype):
    """Same choice as score.pipeline_preds: the first item with a value, else the first item."""
    cand = [i for i in items if i.get("field") == field and i.get("period_type") == ptype]
    return next((i for i in cand if i.get("value") is not None), cand[0] if cand else None)


def false_alarms(run, cell, detail):
    """For every strict-correct item that was flagged ❌: which checks fired."""
    rows_out = []
    for rep in detail:
        market, code = rep["report"].split(":")
        p = OUT / run / cell / f"{market}_{code}.json"
        if not p.exists():
            continue
        items = json.loads(p.read_text())["items"]
        for r in rep["rows"].get(cell, []):
            if r.get("flagged") and r["strict"]:
                it = first_item(items, r["field"], r["ptype"])
                rows_out.append({"report": rep["report"], "field": r["field"], "ptype": r["ptype"],
                                 "triggers": triggers(it) if it else ["（找不到条目）"],
                                 "category": it.get("category") if it else None,
                                 "reasons": (it.get("reasons") or [])[:3] if it else []})
    any_count = Counter(t for x in rows_out for t in x["triggers"])
    sole = Counter(x["triggers"][0] for x in rows_out if len(x["triggers"]) == 1)
    return {"n": len(rows_out), "by_trigger": dict(any_count.most_common()), "sole": dict(sole.most_common()),
            "items": rows_out}


def all_flag_triggers(run, cell, reports):
    """Every ❌ in a run's outputs (scored or not), counted by trigger: where the review work comes from."""
    c = Counter()
    n = 0
    for market, code in reports:
        p = OUT / run / cell / f"{market}_{code}.json"
        if not p.exists():
            continue
        for it in json.loads(p.read_text())["items"]:
            if it.get("status") == "❌":
                n += 1
                c.update(triggers(it))
    return {"n": n, "by_trigger": dict(c.most_common())}


# ---------------------------------------------------------------- stability

def stability(scores_by_run, cell):
    """scores_by_run: {run: scores.json dict}. Items keyed by (report, field, ptype); only items scored in
    every run are compared."""
    rows = {}
    for run, sc in scores_by_run.items():
        for rep in sc["detail"]:
            for r in rep["rows"].get(cell, []):
                rows.setdefault((rep["report"], r["field"], r["ptype"]), {})[run] = r
    runs = list(scores_by_run)
    common = {k: v for k, v in rows.items() if len(v) == len(runs)}
    reports = sorted({k[0] for k in common})

    def same_value(a, b):
        if a["pred"] is None or b["pred"] is None:
            return a["pred"] is None and b["pred"] is None
        return abs(a["pred"] - b["pred"]) <= a["strict_tol"] + 1e-9 * abs(a["truth"])

    agree = sum(1 for v in common.values() if all(same_value(v[runs[0]], v[r]) for r in runs[1:]))
    strict_by_run = {r: sum(v[r]["strict"] for v in common.values()) for r in runs}
    correctness_flip = sum(1 for v in common.values() if len({v[r]["strict"] for r in runs}) > 1)
    out = {"reports": len(reports), "items": len(common), "value_agreement": agree / len(common) if common else None,
           "strict_by_run": strict_by_run, "correctness_flips": correctness_flip}
    if has_flags(cell):
        out["status_flips"] = sum(1 for v in common.values() if len({v[r].get("status") for r in runs}) > 1)
        out["missing_by_run"] = {r: sum(1 for v in common.values() if v[r].get("category") == "漏抽") for r in runs}
    else:
        out["unanswered_by_run"] = {r: sum(1 for v in common.values() if not v[r]["answered"]) for r in runs}
    return out
