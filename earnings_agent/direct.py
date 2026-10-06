"""Direct-ask control cell (docs/eval_design.md §3): the whole parsed report + one chat-style question.

No page selection, no JSON, no unit conversion by the model, no verification, no follow-up.
The free-text answer is turned into numbers on the scoring side by parse_answer(): a cheap model copies
numbers out of the ANSWER (never the report), and code checks every copied number really is in the answer.
"""
import re

from .periods import cumulative_type, parse_period
from .templates import FIELDS
from .textnorm import for_numbers, nfkc
from .units import UnitError, currency_code, digits_of, to_value

# Same definitions as the pipeline (extract.FIELD_DEFS / metrics_spec §2), worded as a person would ask,
# without the JSON mechanics (raw_value / components / derivation).
DIRECT_DEFS = {
    "revenue": {
        "a": "合并利润表的“营业收入”（不是“营业总收入”）",
        "hk": "合并损益表的收入总额（包括“其他”分部的收入）；如果是银行，用扣除预期信贷损失之前的营业收益净额",
        "us": "利润表的 Total net sales / Total revenues；如果是银行，用 reported 口径的 Total net revenue（不是 managed basis）",
    },
    "net_income_parent": "归属于母公司所有者的净利润合计（包括永续债等其他权益工具持有者应占，不包括非控股权益；不要扣非，不要经调整口径）",
    "eps_basic": "基本每股收益（每普通股）",
    "gross_profit": "毛利（报表上的毛利行；如果报表没有毛利行，请用营业收入减营业成本给出毛利，并说明是这样算的）",
    "operating_cash_flow": "经营活动产生的现金流量净额",
    "net_interest_income": "净利息收入",
    "ppop": "拨备前利润（报告有明示就用明示的数；没有的话，请用扣除信贷损失前的收入减去营业支出计算，并说明怎么算的）",
    "insurance_revenue": "保险服务收入（新准则）",
    "insurance_service_result": "保险服务业绩（新准则）",
}
DIRECT_NAMES = {"revenue": "营业收入", "net_income_parent": "归母净利润", "eps_basic": "基本每股收益",
                "gross_profit": "毛利", "operating_cash_flow": "经营活动现金流量净额", "net_interest_income": "净利息收入",
                "ppop": "拨备前利润", "insurance_revenue": "保险服务收入", "insurance_service_result": "保险服务业绩"}
CUM_WORDS = {"Q": "三个月", "H": "六个月（上半年）", "YTD": "九个月（年初至今）", "FY": "全年"}


def build_direct_prompt(doc, template, pages):
    """Returns (system, user). No system prompt: a plain chat question after the pasted report."""
    part = parse_period(doc["period"])[1]
    cum = cumulative_type(part)
    lines = []
    for i, f in enumerate(FIELDS[template], 1):
        d = DIRECT_DEFS[f]
        d = d[doc["market"]] if isinstance(d, dict) else d
        lines.append(f"{i}. {DIRECT_NAMES[f]}：{d}")
    body = "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)
    q_note = ("如果报告同时披露了单季（最近三个月）的数字，也请一并给出，并分别注明是单季还是累计。"
              if cum != "Q" else "")
    user = f"""以下是 {doc.get('name')}（{doc['code']}）的《{doc['title']}》全文，按页标注了页码。

{body}

---

请根据上面这份报告回答：截至 {doc['period_end']} 的{CUM_WORDS[cum]}，以下指标分别是多少？

{chr(10).join(lines)}

{q_note}请给出报告中的原始数字，按报告的写法和单位（例如“401,243 人民币百万元”），不要四舍五入或换算。报告里没有的指标请直接说没有。"""
    return "", user


PARSER_SYSTEM = """你是一个解析器。你只看给定的“回答文本”，把其中每个指标的数字原样抄出来。
硬性规则：
1. 只能使用回答文本里出现的内容，不要使用任何其他知识，不要计算，不要换算，不要补全。
2. raw_value 必须逐字照抄回答里的数字串（含千分位逗号、小数点、括号、负号）。
3. raw_unit / raw_currency 照抄回答里紧挨着这个数字的单位词和币种词（例如“人民币百万元”“亿元”“百万美元”“元/股”）。
4. negative：回答是否表明这个数是负数（例如写了“亏损”“净流出”“负”“(…)”）。
5. quote：照抄回答里包含这个数字的那一句或那一行。
6. 只要回答给了这个指标在这个期间的数字，status 就填 "answered"——即使回答同时附带了说明、保留意见或口径解释
   （例如“报告未单独列示归属于母公司的净利润，Net income 为 29,789”也算 answered，抄 29,789）。
   回答没有给出数字的，填 "not_answered"；回答明确说报告里没有这个数的，填 "not_disclosed"；
   同一指标同一期间给了多个互相矛盾的数或区间，填 "ambiguous"。
只输出一个 JSON 对象。"""


def build_parser_prompt(answer, doc, template):
    part = parse_period(doc["period"])[1]
    cum = cumulative_type(part)
    wanted = [f"- {f}（{DIRECT_NAMES[f]}）：period_type={cum}（累计）"
              + ("；如果回答也给了单季，再加一条 period_type=Q" if cum != "Q" else "") for f in FIELDS[template]]
    user = f"""需要解析的指标（field 名称）：
{chr(10).join(wanted)}

输出格式：
{{"items": [{{"field": "", "period_type": "Q|H|YTD|FY", "status": "answered|not_answered|not_disclosed|ambiguous",
  "raw_value": "", "raw_unit": "", "raw_currency": "", "negative": false, "quote": ""}}]}}

=== 回答文本开始 ===
{answer}
=== 回答文本结束 ==="""
    return PARSER_SYSTEM, user


def _in_answer(raw, answer):
    num = digits_of(raw)
    return re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d]|\.\d)", for_numbers(answer)) is not None


def interpret_parsed(parsed, answer, market):
    """Code-side checks on the parser output. Returns list of predictions:
    {field, period_type, value, currency, raw_value, raw_unit, quote, status, problems}."""
    out = []
    for it in (parsed or {}).get("items") or []:
        rec = {k: it.get(k) for k in ("field", "period_type", "raw_value", "raw_unit", "raw_currency", "quote")}
        rec["status"] = it.get("status") or "answered"
        rec["value"], rec["currency"], rec["problems"] = None, None, []
        if rec["status"] == "answered":
            raw = nfkc(str(it.get("raw_value") or ""))
            try:
                if not _in_answer(raw, answer):  # parser must not invent numbers
                    rec["problems"].append("解析出的数字不在回答文本里")
                    rec["status"] = "parser_error"
                else:
                    value, mult, kind, tol = to_value(raw, it.get("raw_unit") or it.get("raw_currency") or "元")
                    if it.get("negative") and value > 0:
                        value = -value
                    rec["value"], rec["tolerance"] = value, tol
                    rec["currency"] = currency_code(it.get("raw_currency"), it.get("raw_unit"), market)
            except UnitError as e:
                rec["problems"].append(f"单位/数字无法解析：{e}")
                rec["status"] = "parser_error"
        out.append(rec)
    return out
