"""Copy the evaluation numbers the site shows into web/eval_numbers.json (PRD §11.3).

Every number is computed by the same code that writes docs/eval_results.md (eval/analysis.py on the score
files), and carries the section of eval_results.md it appears in. The site reads nothing else.

  .venv/bin/python -m web.build_eval_numbers
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from analysis import three_metrics  # noqa: E402

OUT = ROOT / "data" / "eval"


def load(name):
    return json.loads((OUT / name).read_text())


def rows(sc, cell, markets=None):
    return [r for rep in sc["detail"] if not markets or rep["report"].split(":")[0] in markets
            for r in rep["rows"].get(cell, [])]


def tier(sc, cell, markets=None):
    rs = rows(sc, cell, markets)
    flags = any(k in cell for k in ("pipeline", "verified"))
    m = three_metrics(rs, flags)
    out = {"items": len(rs), "strict": sum(r["strict"] for r in rs), "strict_acc": sum(r["strict"] for r in rs) / len(rs),
           "silent": m["silent"], "silent_rate": m["silent_rate"], "workload": m["workload"],
           "errors": m["errors"], "flagged": m["flagged"]}
    if flags:
        out.update(recall=m["flag_recall"], recall_no_c4=m["flag_recall_no_c4"], false_alarm=m["false_alarm_share"])
    return out


def main():
    frozen, hold, fable = load("eval1/scores.json"), load("hold1/scores.json"), load("eval1/scores_fable.json")
    data = {
        "source": "docs/eval_results.md",
        "frozen_eval1": {"section": "§1.1", "label_zh": "eval1 全量三地 · 冻结版 · DeepSeek · 60 份",
                         "label_en": "eval1, all three markets · frozen rules · DeepSeek · 60 filings",
                         "tiers": {c: tier(frozen, c) for c in ("ds_simple", "ds_direct", "ds_pipeline")}},
        "recall_by_market": {"section": "§1.2b", "label_zh": "流水线 · 冻结版", "label_en": "Pipeline · frozen rules",
                             "us_a": tier(frozen, "ds_pipeline", {"us", "a"}),
                             "hk": tier(frozen, "ds_pipeline", {"hk"})},
        "holdout": {"section": "§3", "label_zh": "留出集 · 40 份美股 + A 股 · 修订版规则 · DeepSeek",
                    "label_en": "Holdout · 40 US + A-share filings · revised rules · DeepSeek",
                    "tiers": {c: tier(hold, c) for c in ("ds_simple", "ds_direct", "ds_pipeline", "ds_verified")}},
        "fable": {"section": "§1.5", "label_zh": "Fable 5.1 · 9 份小样本 · 冻结版", "label_en": "Fable 5.1 · 9-filing sample · frozen rules",
                  "tiers": {c: tier(fable, c) for c in ("fable_direct", "fable_pipeline", "ds_direct", "ds_pipeline")}},
    }
    path = Path(__file__).resolve().parent / "eval_numbers.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    h = data["holdout"]["tiers"]["ds_pipeline"]
    print(f"holdout pipeline strict {h['strict_acc']:.3f} workload {h['workload']:.3f} silent {h['silent']}")
    f = data["frozen_eval1"]["tiers"]
    print({k: round(v["strict_acc"], 3) for k, v in f.items()})
    print("HK recall", data["recall_by_market"]["hk"]["recall"], data["recall_by_market"]["hk"]["recall_no_c4"],
          "US/A", data["recall_by_market"]["us_a"]["recall"], data["recall_by_market"]["us_a"]["recall_no_c4"])


if __name__ == "__main__":
    main()
