"""Write docs/eval_results.md from the score files (eval_design §10.4). Not frozen: layout only.

Inputs (all must already exist; nothing here calls a model or changes a score):
  data/eval/eval1/scores.json            frozen v1 scoring (run in .worktrees/frozen-v1)
  data/eval/eval2|eval3/scores.json      frozen v1 scoring of the stability repeats
  data/eval/eval1_rev1/scores.json       revised rules on the eval1 replies + the R3 cell
  data/eval/hold1/scores.json            holdout, revised rules, US/A only
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from analysis import all_flag_triggers, false_alarms, has_flags, stability, three_metrics  # noqa: E402

OUT = ROOT / "data" / "eval"
NAMES = {"ds_simple": "简单直接问", "ds_direct": "专业直接问", "ds_pipeline": "流水线",
         "ds_verified": "专业直接问 + 核验层（R3）", "fable_direct": "Fable 直接问", "fable_pipeline": "Fable 流水线"}
ORDER = ["ds_simple", "ds_direct", "ds_pipeline", "ds_verified"]


def load(run):
    p = OUT / run / "scores.json"
    return json.loads(p.read_text()) if p.exists() else None


def pct(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f}%"


def boot_ci(detail, cell, key="strict", n=1000, seed=20261006):
    """95% CI of accuracy, resampling whole reports (items within a report are not independent)."""
    per = [(sum(r[key] for r in rep["rows"].get(cell, [])), len(rep["rows"].get(cell, []))) for rep in detail]
    per = [x for x in per if x[1]]
    if not per:
        return None, None
    rnd = random.Random(seed)
    accs = []
    for _ in range(n):
        s = [per[rnd.randrange(len(per))] for _ in per]
        accs.append(sum(a for a, _ in s) / sum(b for _, b in s))
    accs.sort()
    return accs[int(0.025 * n)], accs[int(0.975 * n) - 1]


def cell_cost(run, cell):
    """Per-report cost of producing the answer (direct-ask parser calls are evaluation overhead, §6)."""
    costs, parser = [], []
    for p in sorted((OUT / run / cell).glob("*.json")):
        o = json.loads(p.read_text())
        costs.append((o.get("llm") or {}).get("cost_usd") or 0)
        parser.append((o.get("parser_llm") or {}).get("cost_usd") or 0)
    if not costs:
        return None
    s = sorted(costs)
    return {"n": len(costs), "mean": sum(costs) / len(costs), "median": s[len(s) // 2], "max": s[-1],
            "parser_total": sum(parser)}


def rows_of(sc, cell, markets=None):
    return [r for rep in sc["detail"] if not markets or rep["report"].split(":")[0] in markets
            for r in rep["rows"].get(cell, [])]


def main_table(sc, run, cells, markets=None):
    det = [d for d in sc["detail"] if not markets or d["report"].split(":")[0] in markets]
    head = ("| 档 | 条目 | 严格正确（95% CI） | 大致正确 | 编造率 | 静默错误率 | 复核工作量 | 标记召回率（含 C4 / 去 C4） "
            "| ❌ 中误报占比 | 每份成本（均值 / 中位 / 最大） |\n|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for c in cells:
        rows = [r for rep in det for r in rep["rows"].get(c, [])]
        if not rows:
            continue
        m = three_metrics(rows, has_flags(c))
        n = len(rows)
        strict = sum(r["strict"] for r in rows)
        approx = sum(r["approx"] for r in rows)
        answered = [r for r in rows if r["answered"]]
        fab = sum(r["fabricated"] for r in answered)
        lo, hi = boot_ci(det, c)
        rec = (f"{pct(m['flag_recall'])} / {pct(m.get('flag_recall_no_c4'))}" if has_flags(c) else "0（无标记机制）")
        cost = cell_cost(run, c)
        cost_s = f"${cost['mean']:.4f} / ${cost['median']:.4f} / ${cost['max']:.4f}" if cost else "—"
        lines.append(f"| {NAMES[c]} | {n} | {strict}（{pct(strict / n)}；{pct(lo)}–{pct(hi)}） | {approx}（{pct(approx / n)}） "
                     f"| {fab}/{len(answered)}（{pct(fab / len(answered) if answered else None)}） "
                     f"| {m['silent']}（{pct(m['silent_rate'])}） | {m['flagged']}（{pct(m['workload'])}） | {rec} "
                     f"| {pct(m['false_alarm_share']) if has_flags(c) else '—'} | {cost_s} |")
    return "\n".join(lines)


def by_market(sc, cells):
    lines = ["| 市场 | " + " | ".join(NAMES[c] for c in cells) + " |", "|---" * (len(cells) + 1) + "|"]
    for mk, label in (("us", "美股"), ("a", "A 股"), ("hk", "港股")):
        cols = []
        for c in cells:
            rows = rows_of(sc, c, {mk})
            cols.append(f"{sum(r['strict'] for r in rows)}/{len(rows)}（{pct(sum(r['strict'] for r in rows) / len(rows))}）"
                        if rows else "待核对")
        lines.append(f"| {label} | " + " | ".join(cols) + " |")
    return "\n".join(lines)


def errors_list(sc, cells):
    lines = ["| 报告 | 档 | 字段 | 期间 | 标准答案 | 预测 | 状态/分类 | 说明 |", "|---|---|---|---|---|---|---|---|"]
    for rep in sc["detail"]:
        for c in cells:
            for r in rep["rows"].get(c, []):
                if not r["strict"]:
                    pred = "—" if r["pred"] is None else f"{r['pred']:,.4g}"
                    st = " ".join(x for x in (r.get("status"), r.get("category")) if x) or "—"
                    lines.append(f"| {rep['report']} | {NAMES[c]} | {r['field']} | {r['ptype']} | {r['truth']:,.4g} "
                                 f"| {pred} | {st} | {r.get('note') or ''} |")
    return "\n".join(lines)


def fa_section(run, sc, cell):
    fa = false_alarms(run, cell, sc["detail"])
    if not fa["n"]:
        return f"{NAMES[cell]}：没有误报。"
    t = ["| 触发的检查 | 误报条目中触发次数 | 其中为唯一触发 |", "|---|---|---|"]
    for k, v in fa["by_trigger"].items():
        t.append(f"| {k} | {v} | {fa['sole'].get(k, 0)} |")
    items = "\n".join(f"- {x['report']} {x['field']} {x['ptype']}：{'、'.join(x['triggers'])}"
                      f"（{'；'.join(x['reasons'])[:160]}）" for x in fa["items"])
    return f"{NAMES[cell]}：误报 {fa['n']} 条。\n\n" + "\n".join(t) + "\n\n<details><summary>逐条</summary>\n\n" + \
        items + "\n\n</details>"


def all_flags_section(run, cell, reports):
    a = all_flag_triggers(run, cell, reports)
    t = [f"{NAMES[cell]}（{run}，全部 ❌ {a['n']} 条，含尚无标准答案的）：", "", "| 触发的检查 | 次数 |", "|---|---|"]
    t += [f"| {k} | {v} |" for k, v in a["by_trigger"].items()]
    return "\n".join(t)


def stability_section():
    runs = {r: load(r) for r in ("eval1", "eval2", "eval3")}
    if not all(runs.values()):
        return "（稳定性评分尚未全部生成。）"
    lines = ["| 档 | 报告 | 条目 | 三次数值全一致 | 严格正确（eval1 / eval2 / eval3） | 对错翻转条目 | 状态翻转 / 漏答或漏抽（三次） |",
             "|---|---|---|---|---|---|---|"]
    for c in ("ds_simple", "ds_direct", "ds_pipeline"):
        s = stability(runs, c)
        extra = (f"{s['status_flips']} / {'、'.join(str(v) for v in s['missing_by_run'].values())}" if has_flags(c)
                 else f"— / {'、'.join(str(v) for v in s['unanswered_by_run'].values())}")
        lines.append(f"| {NAMES[c]} | {s['reports']} | {s['items']} | {pct(s['value_agreement'])} "
                     f"| {' / '.join(str(v) for v in s['strict_by_run'].values())} | {s['correctness_flips']} | {extra} |")
    return "\n".join(lines) + ("\n\n只比较三次都有标准答案的条目（目前是美股和 A 股的自动答案；港股核对后补上）。"
                               "稳定性只在冻结版规则下测。")


def section_frozen():
    sc = load("eval1")
    pend = sc["summary"]["pending_review"]
    reports = [tuple(d["report"].split(":")) for d in sc["detail"]]
    return f"""## 1. 冻结版主结果（DeepSeek，60 份）

> **暂定**：港股核对表尚未导回，目前只评了有自动标准答案的条目（美股和 A 股）。待人工核对的条目有 {pend} 条，争议行有 {sc['summary']['disputes']} 条（NIO）。港股核对完成后，冻结版评分会在冻结工作树里重跑，本节随之更新。Fable 9 份尚未运行（§1.5）。

指标定义见 eval_design §6 和 §10.1：

- 静默错误：给了数但错了，并且没被标 ❌；
- 复核工作量：❌ 条目 / 全部条目；
- 标记召回率：被 ❌ 的错误 / 全部错误。

直接问没有标记机制。“去 C4”是指不用标准答案比对的核验，因为美股和 A 股的 C4 与标准答案同源，存在循环。

### 1.1 主表

{main_table(sc, "eval1", ["ds_simple", "ds_direct", "ds_pipeline"])}

### 1.2 分市场（严格正确）

{by_market(sc, ["ds_simple", "ds_direct", "ds_pipeline"])}

### 1.3 流水线 ❌ 误报分析（只分析，不改规则）

{fa_section("eval1", sc, "ds_pipeline")}

全部 ❌ 的来源：

{all_flags_section("eval1", "ds_pipeline", reports)}

### 1.4 稳定性（15 份 × 每份共 3 次）

{stability_section()}

### 1.5 Fable 5.1（9 份小样本，补充参考）

尚未运行。按决定，等港股核对完成后用冻结版规则分两批提交（先直接问，结算后再提交流水线），每批提交前精确核算剩余预算。

### 1.6 全部错误条目（冻结版）

{errors_list(sc, ["ds_simple", "ds_direct", "ds_pipeline"])}
"""


def section_revisions():
    fz, rv = load("eval1"), load("eval1_rev1")
    design = (ROOT / "docs" / "eval_design.md").read_text()
    rev_tbl = design[design.index("### 10.2"):design.index("### 10.3")]
    manifest = json.loads((ROOT / "eval" / "FROZEN.json").read_text())
    log = "\n".join(f"- {r['at'][:19]} UTC，commit `{r['commit'][:10]}`：{r['reason']}（改动文件 {len(r['changed'])} 个）"
                    for r in manifest.get("revisions", []))
    rev1 = json.loads((ROOT / "eval" / "FROZEN_REV1.json").read_text()) if (ROOT / "eval" / "FROZEN_REV1.json").exists() else {}
    body = f"""## 2. 修订记录（看过冻结版结果之后）

下面的内容摘自 eval_design §10.2，是那里的原文。

{rev_tbl.replace('### 10.2', '### 2.1', 1)}
**登记日志**（`eval/FROZEN.json` → `revisions`）：

{log or '（尚未登记）'}

修订版规则冻结于 commit `{(rev1.get('commit') or '—')[:10]}`（`eval/FROZEN_REV1.json`，{(rev1.get('frozen_at') or '')[:19]} UTC）。
"""
    if rv:
        body += f"""
### 2.2 eval1 上冻结版与修订版并列（同一批模型回复）

冻结版（主结果）：

{main_table(fz, "eval1", ["ds_simple", "ds_direct", "ds_pipeline"])}

修订版（R1 + R2；R3 新档只有修订版）：

{main_table(rv, "eval1_rev1", ORDER)}

> **R3 那一档是看过结果之后设计的新档，单独标注。** 它在 eval1 上的数字不能用来证明修订有效，要看 §3 的留出集。

修订版流水线的误报：

{fa_section("eval1_rev1", rv, "ds_pipeline")}

R3 新档的误报：

{fa_section("eval1_rev1", rv, "ds_verified")}
"""
    return body


def section_holdout():
    sc = load("hold1")
    if not sc:
        return "## 3. 留出集结果（四档，DeepSeek）\n\n尚未运行。\n"
    cfg = json.loads((ROOT / "eval" / "holdout_config.json").read_text())
    return f"""## 3. 留出集结果（四档，DeepSeek，修订版规则）

60 家公司各自的上一期报告（`eval/holdout_config.json`）。规则在运行前冻结（`eval/FROZEN_REV1.json`），跑完没有再改。**只评美股和 A 股**（{len(sc['detail'])} 份），用自动标准答案；港股照跑但不评分。美股和 A 股里没有自动答案的条目（{sc['summary']['pending_review']} 条）也不评。

{main_table(sc, "hold1", ORDER)}

分市场（严格正确）：

{by_market(sc, ORDER)}

流水线（修订版）的误报：

{fa_section("hold1", sc, "ds_pipeline")}

专业直接问 + 核验层的误报：

{fa_section("hold1", sc, "ds_verified")}

全部 ❌ 的来源（含港股和无答案条目）：

{all_flags_section("hold1", "ds_pipeline", [(r['market'], r['code']) for r in cfg['reports']])}

{all_flags_section("hold1", "ds_verified", [(r['market'], r['code']) for r in cfg['reports']])}

<details><summary>全部错误条目（留出集）</summary>

{errors_list(sc, ORDER)}

</details>
"""


LIMITS = """## 4. 局限

- **以 DeepSeek 为主**：主结论基于 DeepSeek 的 60 份。Fable 只有 9 份，是小样本补充，不能单独下结论。
- **输入是解析后的文本，不是 PDF**：所有档拿到的都是同一份 pdfplumber/HTML 解析文本。真实用户可能直接上传 PDF，PDF 的版面信息可能帮助或干扰模型，本评估不涉及。
- **港股留出集没有评分**：港股没有可靠的自动标准答案，为避免再做一轮人工核对，留出集只评美股和 A 股，所以修订在港股上是否有效没有验证。冻结版的港股结果依赖人工核对。
- **修订是看过结果之后做的**：R1、R2 是针对 eval1 暴露的问题改的，R3 是看到结果后提出的新设计。它们在 eval1 上的改善是自证的，只有留出集的结果才算证据。
- **美股和 A 股的 C4 存在循环**：C4 用的就是作为标准答案的 XBRL/AKShare，所以同时报告了去 C4 的标记召回率。
- 稳定性只测了 DeepSeek，15 份，每份共 3 次。
"""


def replacement_table():
    d = (ROOT / "docs" / "eval_design.md").read_text()
    s = d.index("| 候选 | 替换为 |")
    return "## 附：名单替换留痕\n\n" + d[s:d.index("\n\n", s)] + "\n\n留出集没有替换（`eval/holdout_config.json` 的 `unavailable` 为空时）。\n"


def main():
    parts = ["# 第 2 阶段评估结果\n\n> 由 `eval/results_report.py` 生成。各节顺序：冻结版主结果 → 修订记录 → 留出集 → 局限。\n",
             section_frozen(), section_revisions(), section_holdout(), LIMITS, replacement_table()]
    (ROOT / "docs" / "eval_results.md").write_text("\n".join(parts))
    print("wrote docs/eval_results.md")


if __name__ == "__main__":
    main()
