"""Build docs/phase1_results.md from data/output/*.json (run the 9 extractions first).

Manual review notes (why each ❌ happened, after reading the page) live in docs/phase1_review_notes.md
and are inlined verbatim, so the auto tables can be regenerated without losing them.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = [("us", "AAPL", "2026Q3"), ("us", "JPM", "2026Q2"), ("us", "BABA", "2026FY"),
        ("a", "600519", "2026H1"), ("a", "300750", "2026H1"), ("a", "600036", "2026H1"),
        ("hk", "00700", "2026H1"), ("hk", "03690", "2026H1"), ("hk", "00005", "2026H1")]
CORE_ORDER = ["revenue", "net_income_parent", "eps_basic", "gross_profit", "operating_cash_flow",
              "net_interest_income", "ppop", "insurance_revenue", "insurance_service_result",
              "net_income_common", "eps_basic_per_ads", "cost_of_revenue", "weighted_avg_shares_basic"]


def fmt(v, digits=4):
    if v is None:
        return ""
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.{digits}f}".rstrip("0").rstrip(".")


def cell(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def main():
    results = []
    for m, c, p in RUNS:
        f = ROOT / "data" / "output" / f"{m}_{c}_{p}.json"
        results.append((m, c, p, json.loads(f.read_text()) if f.exists() else None))

    out = ["# 第 1 阶段结果：抽取 + 核验（开发集 9 家）", "",
           "由 `scripts/phase1_report.py` 根据 `data/output/*.json` 生成；人工复核说明见第 3 节。"
           "口径见 `docs/metrics_spec.md` v0.3（含合理性检查和缺期间补问）。", ""]

    # ---- summary
    out += ["## 1. 总览", "",
            "| 公司 | 原文 | 模板 | 送模型页数 | 核心字段 ✅/⚠️/❌ | 行业指标 ⚠️/❌ | 模型（调用次数） | 输入 tokens（缓存命中） | 输出 tokens | 成本 USD |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    tot = Counter()
    for m, c, p, r in results:
        if r is None:
            out.append(f"| {m}:{c} {p} | **未跑通** | | | | | | | | |")
            continue
        core = [i for i in r["items"] if i["field"] in CORE_ORDER[:9]]
        cs = Counter(i["status"] for i in core)
        ms = Counter(i["status"] for i in r["industry_metrics"])
        u, l = r["llm"]["usage"] or {}, r["llm"]
        tot.update({"in": u.get("input_tokens", 0), "hit": u.get("cached_input_tokens", 0),
                    "out": u.get("output_tokens", 0)})
        tot["cost"] += l.get("cost_usd") or 0
        for k in ("✅", "⚠️", "❌"):
            tot["core" + k] += cs[k]
        d = r["doc"]
        out.append(f"| {d['name']} {c} {p} | {d['doc_kind']}：{cell(d['title'])} | {r['template']} | "
                   f"{len(r['pages_sent'])}/{r['pages_total']} | {cs['✅']}/{cs['⚠️']}/{cs['❌']} | "
                   f"{ms['⚠️']}/{ms['❌']} | {l['model']}（{l.get('calls', 1)}） | {u.get('input_tokens', 0):,}（{u.get('cached_input_tokens', 0):,}） | "
                   f"{u.get('output_tokens', 0):,} | {l.get('cost_usd') or 0:.4f} |")
    out += [f"| **合计** | | | | {tot['core✅']}/{tot['core⚠️']}/{tot['core❌']} | | | "
            f"{tot['in']:,}（{tot['hit']:,}） | {tot['out']:,} | {tot['cost']:.4f} |", "",
            "成本按调用时刻的 DeepSeek 峰谷价格计算（价格表见 `earnings_agent/config.py`，2026-10-06 取自官网）；"
            "重跑命中本地缓存不再产生费用。核心字段计数只含模板核心字段（不含 net_income_common 等子字段和推导中间项）。", ""]

    # ---- per company
    out += ["## 2. 逐家明细", ""]
    for m, c, p, r in results:
        if r is None:
            out += [f"### {m}:{c} {p}", "", "未跑通：没有输出文件。", ""]
            continue
        d = r["doc"]
        out += [f"### {d['name']}（{m.upper()} {c}，{p}）", "",
                f"- 原文：{d['doc_kind']} [{cell(d['title'])}]({d['url']})，发布 {d['filed']}，期末 {d['period_end']}",
                f"- 模板：{r['template']}（行业：{d['industry'].get('source')} = {d['industry'].get('name')} "
                f"{d['industry'].get('code') or ''}）{'；' + json.dumps(r['template_notes'], ensure_ascii=False) if r['template_notes'] else ''}",
                f"- 送模型页：{r['pages_sent']}（{r['chars_sent']:,} 字符）",
                f"- 补问：{'无' if not r.get('followup') else '问 ' + str(r['followup']['asked']) + '，返回 ' + str(r['followup']['returned']) + ' 条；not_found=' + json.dumps(r['followup'].get('not_found'), ensure_ascii=False)}",
                f"- 标准答案：{(r['benchmarks'] or [{}])[0].get('source', '无')}"
                f"{'；获取失败：' + r['benchmark_error'] if r['benchmark_error'] else ''}"
                f"{'；**' + r['benchmark_invalid'] + '**' if r['benchmark_invalid'] else ''}", "",
                "| 字段 | 期间 | 原文数字 | 原文单位 | 换算后 | 币种 | 页 | 标准答案 | 状态 | 原因 |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        items = sorted(r["items"], key=lambda i: (CORE_ORDER.index(i["field"]) if i["field"] in CORE_ORDER else 99,
                                                   i.get("period_type") or ""))
        for i in items:
            b = i.get("benchmark") or {}
            raw = i.get("raw_value") or (i.get("formula") if i.get("derivation") == "derived" else "")
            if i.get("components"):
                raw = " ".join(f"{'+' if float(x.get('sign', 1)) > 0 else '−'}{x.get('raw_value')}" for x in i["components"])
            cat = f"**{i['category']}**：" if i["status"] == "❌" and i.get("category") else ""
            out.append(f"| {i['field']}{'（推导）' if i.get('derivation') == 'derived' else ''} | {i.get('period_type') or ''} | "
                       f"{cell(raw)} | {cell(i.get('raw_unit'))} | {fmt(i.get('value'))} | {i.get('currency') or ''} | "
                       f"{i.get('page_used') or i.get('page') or ''} | {fmt(b.get('value'))} {cell(b.get('source_field'))} | "
                       f"{i['status']} | {cat}{cell('；'.join(i.get('reasons') or []))} |")
        out += ["", "行业特色指标：", "",
                "| 指标 | 期间 | 原文数字 | 单位 | 页 | 状态 | 理由 | 核验说明 |", "|---|---|---|---|---|---|---|---|"]
        for i in r["industry_metrics"]:
            cat = f"**{i['category']}**：" if i["status"] == "❌" and i.get("category") else ""
            out.append(f"| {cell(i['field'][9:])} | {i.get('period_type') or ''} | {cell(i.get('raw_value'))} | "
                       f"{cell(i.get('raw_unit'))} | {i.get('page_used') or i.get('page') or ''} | {i['status']} | "
                       f"{cell(i.get('rationale'))} | {cat}{cell('；'.join(i.get('reasons') or []))} |")
        if r["dropped"]:
            out += ["", f"丢弃的条目（对比期/重复）：{len(r['dropped'])} 条"]
        out.append("")

    notes = ROOT / "docs" / "phase1_review_notes.md"
    out += ["## 3. ❌ 人工复核与归类", ""]
    out += [notes.read_text().strip() if notes.exists() else "（尚未写复核说明）", ""]
    (ROOT / "docs" / "phase1_results.md").write_text("\n".join(out))
    print("wrote docs/phase1_results.md")


if __name__ == "__main__":
    sys.exit(main())
