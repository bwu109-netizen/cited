"""docs/eval_dev_results.md from data/eval/dev/summary.json (eval/run_dev.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from earnings_agent import config  # noqa: E402
from earnings_agent.budget import Budget  # noqa: E402
from score import summarize  # noqa: E402

CELLS = [("ds_pipeline", "DeepSeek × 流水线"), ("ds_direct", "DeepSeek × 直接问"),
         ("fable_pipeline", "Fable 5.1 × 流水线"), ("fable_direct", "Fable 5.1 × 直接问")]
FN = {"revenue": "营收", "net_income_parent": "归母", "eps_basic": "EPS", "gross_profit": "毛利",
      "operating_cash_flow": "经营现金流", "net_interest_income": "净利息收入", "ppop": "拨备前利润"}


def pct(x):
    return "—" if x is None else f"{100 * x:.0f}%"


def fmt(v):
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.4f}".rstrip("0").rstrip(".")


def main():
    S = json.loads((ROOT / "data/eval/dev/summary.json").read_text())
    st = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD).status()
    out = ["# 开发集验证结果（第 2 阶段评估机制，冻结前）", "",
           "由 `eval/run_dev.py` + `eval/dev_report.py` 生成。DeepSeek 两格跑开发集全部 9 份；Fable 5.1 两格只跑最短的 1 份，"
           "用来测试 Batch 客户端。全部费用记入 $20 账本。", "",
           f"**账本**：已花 ${st['spent']:.4f}，未结预留 ${st['reserved']:.4f}，剩余 ${st['left']:.4f}（上限 ${st['cap']:.0f}）。", "",
           "## 1. 四格汇总", "",
           "| 格 | 份数 | 评分条目 | 严格正确 | 大致正确 | 作答 | 数字编造率 | 错误被标出（含 C4 / 去 C4） | 误报率 | 静默错误 | 每份成本 | 解析成本/份 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for cell, name in CELLS:
        reps = S.get(cell) or []
        rows = [r for rep in reps for r in rep["rows"]]
        if not reps:
            continue
        s = summarize(rows, pipeline="pipeline" in cell)
        cost = sum(rep["cost"] or 0 for rep in reps) / len(reps)
        pc = [rep["parser_cost"] for rep in reps if rep.get("parser_cost") is not None]
        flag = (f"{s['wrong_flagged']}/{s['wrong']} / {s['wrong_flagged_no_c4']}/{s['wrong']}" if "pipeline" in cell
                else "不适用")
        out.append(f"| {name} | {len(reps)} | {s['items']} | {s['strict']}（{pct(s['strict_acc'])}） | "
                   f"{s['approx']}（{pct(s['approx_acc'])}） | {s['answered']} | {pct(s['fab_rate'])} | {flag} | "
                   f"{pct(s.get('false_alarm')) if 'pipeline' in cell else '不适用'} | "
                   f"{s.get('silent_errors', '不适用')} | ${cost:.4f} | {'$%.4f' % (sum(pc) / len(pc)) if pc else '—'} |")
    out += ["", "注：Fable 两格只有 1 份报告，数字只用于确认机制能跑通，不能和 9 份的数字比较。", ""]

    # same report, all four cells
    fab = S.get("fable_pipeline") or []
    if fab:
        doc = fab[0]["doc"]
        out += [f"## 2. 同一份报告的四格对比（{doc}，Fable 只跑了这一份）", "",
                "| 字段 | 期间 | 标准答案 | DS 流水线 | DS 直接问 | Fable 流水线 | Fable 直接问 |", "|---|---|---|---|---|---|---|"]
        by_cell = {}
        for cell, _ in CELLS:
            rep = next((r for r in S.get(cell, []) if r["doc"] == doc), None)
            by_cell[cell] = {(x["field"], x["ptype"]): x for x in (rep["rows"] if rep else [])}
        for k, t in by_cell["ds_pipeline"].items():
            cells = []
            for cell, _ in CELLS:
                x = by_cell[cell].get(k)
                if not x:
                    cells.append("—")
                    continue
                mark = "✓" if x["strict"] else ("≈" if x["approx"] else "✗")
                cells.append(f"{mark} {fmt(x['pred'])}" + (f"（{x.get('status')}）" if x.get("status") else ""))
            out.append(f"| {FN.get(k[0], k[0])} | {k[1]} | {fmt(t['truth'])} | " + " | ".join(cells) + " |")
        out += ["", "✓ 严格正确；≈ 仅大致正确（误差 ≤ 1%）；✗ 错误或未作答。流水线括号内是核验状态。", ""]

    # every wrong item
    out += ["## 3. 全部错误条目（按严格档）", ""]
    for cell, name in CELLS:
        bad = [(rep["doc"], r) for rep in S.get(cell, []) for r in rep["rows"] if not r["strict"]]
        out += [f"### {name}：{len(bad)} 条", ""]
        if not bad:
            out += ["无。", ""]
            continue
        out += ["| 报告 | 字段 | 期间 | 标准答案 | 预测 | 大致正确 | 编造 | 状态 | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
        for doc, r in bad:
            out.append(f"| {doc} | {FN.get(r['field'], r['field'])} | {r['ptype']} | {fmt(r['truth'])} {r['truth_currency'] or ''} | "
                       f"{fmt(r['pred'])} {r['pred_currency'] or ''}{' (' + str(r['pred_raw']) + ')' if r.get('pred_raw') else ''} | "
                       f"{'是' if r['approx'] else '否'} | {'是' if r['fabricated'] else ''} | "
                       f"{(r.get('status') or '') + ' ' + (r.get('category') or '')} | {r.get('note') or ''} |")
        out.append("")
    (ROOT / "docs" / "eval_dev_results.md").write_text("\n".join(out))
    print("wrote docs/eval_dev_results.md")


if __name__ == "__main__":
    main()
