"""Revision R3 (eval_design §10): run the pipeline's verification layer on a parsed direct-ask answer.

Same verify_report as the pipeline (C1–C4, sanity checks, expected-period / 漏抽 rule, ❌ = flagged).
No follow-up question: the direct ask is asked once. The verification layer only adds flags: the value
that is scored is always the number the answer gave (converted to base units by code, as for the
other direct-ask cells).
"""
from .direct import verified_raw_items
from .units import UnitError, to_value
from .verify import PER_SHARE_FIELDS, verify_report


def _answered_value(it):
    try:
        v, _, _, tol = to_value(it["value_as_answered"], it["raw_unit"], per_share=it["field"] in PER_SHARE_FIELDS)
        return v, tol
    except UnitError:
        return None, 0.0


def verify_direct_answer(ctx, parsed, answer):
    raw_items, notes = verified_raw_items(parsed, answer, ctx["doc"])
    items, _, dropped, bench_invalid = verify_report(raw_items, [], ctx["pages"], ctx["doc"], ctx["template"],
                                                     ctx["benchmarks"], ctx["prior"])
    for it in items:
        if it.get("computed_without_inputs") and it.get("status") == "❌" and not it.get("c2"):
            it["category"] = "计算值无出处"  # the answer computed it but named no source numbers
        if it.get("derivation") == "derived" and it.get("value_as_answered"):
            said, said_tol = _answered_value(it)
            recomputed = it.get("value")
            if said is None or recomputed is None or \
                    abs(said - recomputed) > said_tol + it.get("tolerance", 0) + 1e-9 * abs(recomputed):
                it.setdefault("reasons", []).append(
                    f"回答给出的计算结果 {it['value_as_answered']} 与按组成项重算的值 {recomputed} 不一致")
                it["status"], it["category"] = "❌", it.get("category") or "口径/推导"
            it["value_recomputed"], it["value"] = recomputed, said
    return {"items": items, "dropped": dropped, "benchmark_invalid": bench_invalid, "parse_notes": notes}
