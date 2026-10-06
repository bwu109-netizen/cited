"""Render data/output/eval_candidates.json as the markdown tables of docs/eval_design.md §1."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET = {"us": "美股", "a": "A 股", "hk": "港股"}
TEMPLATE = {"general": "通用", "bank": "银行", "insurance": "保险"}


def currency(r):
    if r["market"] == "a":
        return "CNY"
    return r.get("bench_currency") or r.get("currency_guess") or "?"


def unit_short(units):
    if not units:
        return "（未自动识别）"
    u = units[0]
    return u if len(u) <= 28 else u[:28] + "…"


def main():
    rows = json.loads((ROOT / "data/output/eval_candidates.json").read_text())
    out = []
    for m in ("us", "a", "hk"):
        rs = [r for r in rows if r.get("market") == m]
        out += [f"### {MARKET[m]}（{len(rs)} 家）", "",
                "| 代码 | 公司 | 目标期间 | 原文 | 页数 | 模板 | 币种 | 单位（自动识别） | 盈/亏 | 上一期 | 选它的理由 |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            if not r.get("ok"):
                out.append(f"| {r['code']} | | {r.get('period')} | **失败**：{r.get('error', '')[:80]} | | | | | | | {r.get('reason')} |")
                continue
            ni = r.get("net_income")
            pl = "—" if ni is None else ("亏损" if ni < 0 else "盈利")
            prior = r.get("prior") or {}
            out.append(f"| {r['code']} | {r['name']} | {r['period']} | {r['doc_kind']}（{r['filed']}） | {r['pages']} | "
                       f"{TEMPLATE.get(r['template'], r['template'])} | {currency(r)} | {unit_short(r.get('units'))} | {pl} | "
                       f"{prior.get('period', '**未找到**')} | {r['reason']} |")
        ok = [r for r in rs if r.get("ok")]
        out += ["", "覆盖：" + "，".join(f"{TEMPLATE[k]} {v}" for k, v in Counter(r["template"] for r in ok).items())
                + f"；亏损 {sum(1 for r in ok if (r.get('net_income') or 0) < 0)} 家"
                + f"；币种 " + "，".join(f"{k} {v}" for k, v in Counter(currency(r) for r in ok).items()), ""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
