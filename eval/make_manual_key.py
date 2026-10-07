"""Convert the review-table export into eval/answer_key_manual.json (the format score.answer_key reads).

- pick: the reviewer chose a candidate (value already in base units). The printed raw string is not part of
  the export, so the entry carries the value in base units plus an explicit strict tolerance computed with the
  frozen rule used for automatic answers (score.printed_tolerances: half a unit of the last printed digit of
  any printed representation found in the document; 5e-6 relative if none) — the same rule, applied the same way.
- edit: the reviewer typed raw value + unit -> passed through unchanged (frozen to_value gives the tolerance).
- na: "原文没有/不适用" -> {"na": true}: answer_key drops the item from scoring (eval_design §6, set S).

  python eval/make_manual_key.py data/review/answer_key_eval1_answers.json
"""
import json
import sys
import warnings
from decimal import Decimal
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from earnings_agent.pipeline import prepare  # noqa: E402
from score import _doc_numbers, printed_tolerances  # noqa: E402


def main(src):
    exp = json.loads(Path(src).read_text())
    out, nums = {}, {}
    for rid, a in sorted(exp["answers"].items()):
        market, code, period, field, ptype = rid.split(":")
        rep = f"{market}:{code}:{period}"
        note = a.get("comment")
        if a["decision"] == "na":
            e = {"field": field, "ptype": ptype, "na": True}
        elif a["decision"] == "edit":
            e = {"field": field, "ptype": ptype, "raw": a["raw"], "unit": a["unit"], "currency": a.get("currency")}
        else:
            if rep not in nums:
                nums[rep] = _doc_numbers(prepare(market, code, period)["pages"])
            v = a["value"]
            reps = printed_tolerances(v, field, nums[rep])
            e = {"field": field, "ptype": ptype, "raw": format(Decimal(repr(v)).normalize(), "f"), "unit": "元",
                 "currency": a.get("currency"),
                 "tol": max(r[0] for r in reps) if reps else 5e-6 * abs(v),
                 "printed_as": [r[1] for r in reps]}
            note = note or f"核对表候选 {a.get('k')}"
        if note:
            e["note"] = note
        e["decision"] = a["decision"]
        out.setdefault(rep, []).append(e)
    dst = ROOT / "eval" / "answer_key_manual.json"
    dst.write_text(json.dumps({"_source": {"file": str(Path(src).name), "table": exp.get("table"),
                                           "exported_at": exp.get("exported_at"), "rows": len(exp["answers"])},
                               **out}, ensure_ascii=False, indent=1))
    n = sum(len(v) for v in out.values())
    print(f"wrote {dst.relative_to(ROOT)}: {n} entries in {len(out)} reports")


if __name__ == "__main__":
    main(sys.argv[1])
