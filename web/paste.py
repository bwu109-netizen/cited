"""P4 Verify page: turn another AI's pasted answer (JSON or a table) into raw items for
earnings_agent.verify.verify_report. Pure code, no model calls.

Accepted:
- JSON: {"items": [...]} or a bare list, items in the pipeline extraction format
  (field, raw_value, raw_unit, raw_currency, period_type, period_end, page, quote[, derivation, components]).
  The whole reply of the universal prompt (prompts/) can be pasted: the first ```json block is used and the
  readable table after it is ignored. Items with status "not_disclosed" are listed as absent, not as errors.
- Tables: Markdown (| a | b |) or tab-separated (copied from a web page). Columns are recognised from the
  header row; unknown columns can be mapped by the user (`mapping`: {column index: role}).
Rows that cannot be parsed are returned separately with their line number, never dropped silently.
"""
from __future__ import annotations

import json
import re

from earnings_agent.textnorm import nfkc
from earnings_agent.units import UnitError, digits_of

# metric name (lower-case, NFKC) -> field
FIELD_ALIASES = {
    "revenue": ["营业收入", "收入", "营收", "營業收入", "營業額", "收益", "revenue", "revenues", "total revenues",
                "total revenue", "net sales", "total net sales", "net revenue", "total net revenue"],
    "net_income_parent": ["归母净利润", "归属于母公司股东的净利润", "归属于母公司所有者的净利润", "本公司拥有人应占溢利",
                          "net income attributable", "net income attributable to parent", "net income",
                          "profit attributable to owners", "profit attributable to equity holders"],
    "eps_basic": ["基本每股收益", "每股收益", "基本eps", "eps", "basic eps", "basic earnings per share",
                  "earnings per share basic"],
    "gross_profit": ["毛利", "毛利润", "gross profit", "gross margin"],
    "operating_cash_flow": ["经营活动现金流量净额", "经营活动产生的现金流量净额", "经营现金流", "operating cash flow",
                            "net cash provided by operating activities", "net cash from operating activities", "cfo"],
    "net_interest_income": ["净利息收入", "利息净收入", "net interest income"],
    "ppop": ["拨备前利润", "pre-provision profit", "ppop"],
    "insurance_revenue": ["保险服务收入", "insurance revenue"],
    "insurance_service_result": ["保险服务业绩", "insurance service result"],
    "cost_of_revenue": ["营业成本", "cost of revenue", "cost of revenues", "cost of sales"],
}
_ALIAS = {nfkc(a).lower(): f for f, names in FIELD_ALIASES.items() for a in names}
_ALIAS.update({f: f for f in FIELD_ALIASES})

PERIOD_ALIASES = {
    "Q": ["q", "单季", "单季度", "三个月", "本季度", "quarter", "three months", "3m", "3 months"],
    "H": ["h", "h1", "半年", "六个月", "上半年", "中期", "six months", "6m", "half year", "6 months"],
    "YTD": ["ytd", "年初至今", "九个月", "前三季度", "nine months", "9m", "9 months"],
    "FY": ["fy", "全年", "年度", "十二个月", "full year", "year", "12m", "annual"],
    "PIT": ["pit", "时点", "期末"],
}
_PERIOD = {a: p for p, names in PERIOD_ALIASES.items() for a in names}

# header word -> role
ROLE_WORDS = {
    "field": ["指标", "科目", "项目", "metric", "item", "field", "line item"],
    "raw_value": ["数值", "提取数值", "数字", "金额", "value", "amount", "figure", "raw_value"],
    "raw_unit": ["单位", "报告单位", "unit", "units", "raw_unit"],
    "raw_currency": ["币种", "货币", "currency", "raw_currency"],
    "period_type": ["期间", "期间类型", "period", "period type", "period_type"],
    "page": ["页码", "出现页码", "页", "page", "page no", "page number"],
    "quote": ["原文", "原文句子", "原文引用", "引用", "quote", "source", "source quote", "source text"],
}
_ROLE = {nfkc(w).lower(): r for r, words in ROLE_WORDS.items() for w in words}
ROLES = list(ROLE_WORDS)


def field_of(name):
    t = nfkc(str(name or "")).strip().lower()
    t = re.sub(r"[（(].*?[)）]", "", t).strip()  # "营业收入（单季）" -> "营业收入"
    return _ALIAS.get(t)


def period_of(text, default):
    t = nfkc(str(text or "")).strip().lower()
    if not t:
        return default
    if t in _PERIOD:
        return _PERIOD[t]
    for a, p in sorted(_PERIOD.items(), key=lambda x: -len(x[0])):
        if len(a) > 2 and a in t:
            return p
    return None


def _page(v):
    m = re.search(r"\d+", str(v or ""))
    return int(m.group(0)) if m else 0


def _split_row(line):
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_rule(cells):
    return all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c)


_FENCED_JSON = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n\s*```", re.S)


def json_block(text):
    """The JSON part of a pasted reply: the first fenced block that looks like JSON, else the text itself."""
    for m in _FENCED_JSON.finditer(text or ""):
        body = m.group(1).strip()
        if body[:1] in "[{":
            return body
    return (text or "").strip()


def detect(text):
    t = (text or "").strip()
    if not t:
        return "empty"
    if t[0] in "[{" or t.startswith("```") or json_block(t)[:1] in "[{":
        return "json"
    return "table"


def header_roles(cells):
    return [_ROLE.get(nfkc(c).strip().lower()) for c in cells]


def parse(text, cum, period_end_iso, mapping=None):
    """Returns {"items": raw items, "bad": [{"line", "text", "why"}], "columns": [...], "roles": [...],
    "format": "json"|"table"|"empty", "needs_mapping": bool}."""
    kind = detect(text)
    out = {"items": [], "bad": [], "absent": [], "columns": [], "roles": [], "format": kind, "needs_mapping": False}
    if kind == "empty":
        return out
    if kind == "json":
        s = json_block(text).strip("`")
        s = re.sub(r"^json\s*", "", s)
        try:
            data = json.loads(s)
        except json.JSONDecodeError as e:
            out["bad"].append({"line": e.lineno, "text": "", "why": f"JSON 无法解析：{e.msg}"})
            return out
        rows = data.get("items") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            out["bad"].append({"line": 1, "text": "", "why": "JSON 里没有 items 列表"})
            return out
        for k, r in enumerate(rows, 1):
            _add(out, k, json.dumps(r, ensure_ascii=False)[:160] if isinstance(r, dict) else str(r)[:160],
                 r if isinstance(r, dict) else None, cum, period_end_iso)
        return out
    lines = [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if ln.strip()]
    if not lines:
        return out
    head_n, head = lines[0]
    cells = _split_row(head)
    roles = header_roles(cells)
    if mapping:
        roles = [mapping.get(str(i), roles[i] if i < len(roles) else None) for i in range(len(cells))]
    out["columns"], out["roles"] = cells, roles
    if "field" not in roles or "raw_value" not in roles:
        out["needs_mapping"] = True
        return out
    for n, ln in lines[1:]:
        c = _split_row(ln)
        if _is_rule(c):
            continue
        if len(c) != len(cells):
            out["bad"].append({"line": n, "text": ln[:160], "why": f"列数 {len(c)} 与表头 {len(cells)} 不一致"})
            continue
        r = {roles[i]: c[i] for i in range(len(cells)) if roles[i]}
        _add(out, n, ln[:160], r, cum, period_end_iso)
    return out


def _add(out, line, text, r, cum, period_end_iso):
    if r is None:
        out["bad"].append({"line": line, "text": text, "why": "不是一个对象"})
        return
    field = r.get("field") if r.get("field") in FIELD_ALIASES else field_of(r.get("field") or r.get("metric"))
    if not field:
        out["bad"].append({"line": line, "text": text, "why": f"指标名无法识别：{r.get('field') or r.get('metric')!r}"})
        return
    raw = str(r.get("raw_value") if r.get("raw_value") is not None else r.get("value") or "").strip()
    if str(r.get("status") or "").lower() == "not_disclosed" or nfkc(raw).lower() in ("原文没有", "not disclosed"):
        out["absent"].append({"line": line, "field": field, "period_type": period_of(r.get("period_type") or r.get("period"), cum),
                              "note": str(r.get("note") or "")[:200]})
        return
    try:
        digits_of(raw)
    except UnitError:
        out["bad"].append({"line": line, "text": text, "why": f"数值不是数字：{raw!r}"})
        return
    ptype = period_of(r.get("period_type") or r.get("period"), cum)
    if ptype is None:
        out["bad"].append({"line": line, "text": text, "why": f"期间无法识别：{r.get('period_type')!r}"})
        return
    item = {"field": field, "raw_value": raw, "raw_unit": str(r.get("raw_unit") or r.get("unit") or ""),
            "raw_currency": str(r.get("raw_currency") or r.get("currency") or ""), "period_type": ptype,
            "period_start": None, "period_end": r.get("period_end") or period_end_iso,
            "page": _page(r.get("page")), "quote": str(r.get("quote") or ""),
            "derivation": r.get("derivation") or "reported", "_line": line}
    if r.get("components"):
        item["components"] = r["components"]
    out["items"].append(item)


def mark_no_source(items):
    """After verification: an item that came without page or quote is '无出处' (no source), not 数字编造 etc."""
    for it in items:
        if it.get("status") == "❌" and it.get("category") != "漏抽" and (not it.get("page") or not it.get("quote")):
            it["category"] = "无出处"
    return items


if __name__ == "__main__":  # self-check
    md = """| 指标 | 数值 | 单位 | 期间 | 页码 | 原文 |
|---|---|---|---|---|---|
| 营业收入 | 28,236 | in millions | 单季 | 5 | Total revenues 28,236 |
| 研发支出 | 1,040 | in millions | 单季 | | |
| 归母净利润 | abc | in millions | 单季 | 5 | x |
| 毛利 | 4,751 | in millions | 单季 |"""
    r = parse(md, "H", "2026-06-30")
    assert [i["field"] for i in r["items"]] == ["revenue"], r
    assert [b["line"] for b in r["bad"]] == [4, 5, 6], r["bad"]
    j = parse('{"items":[{"field":"eps_basic","raw_value":"0.34","raw_unit":"per share","period_type":"Q","page":5,'
              '"quote":"Basic $ 0.34"}]}', "H", "2026-06-30")
    assert j["items"][0]["field"] == "eps_basic" and not j["bad"]
    assert parse("| a | b |\n|---|---|\n| 1 | 2 |", "H", "x")["needs_mapping"]
    # a whole reply to the universal prompt: prose, a ```json block, then a readable table
    reply = ('Here are the figures.\n\n```json\n{"items":[{"field":"revenue","period_type":"Q","status":"reported",'
             '"raw_value":"28,236","raw_unit":"in millions","raw_currency":"$","page":5,"quote":"Total revenues 28,236"},'
             '{"field":"operating_cash_flow","period_type":"Q","status":"not_disclosed","raw_value":null,'
             '"note":"six months only"}]}\n```\n\n| 指标 | 期间 | 数值 |\n|---|---|---|\n| 营业收入 | 单季 | 28,236 |')
    u = parse(reply, "H", "2026-06-30")
    assert u["format"] == "json" and [i["field"] for i in u["items"]] == ["revenue"] and not u["bad"], u
    assert [(a["field"], a["period_type"]) for a in u["absent"]] == [("operating_cash_flow", "Q")], u["absent"]
    print("paste self-check OK")
