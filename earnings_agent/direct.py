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


SIMPLE_QUESTION = "请告诉我这份报告期内的营业收入、归母净利润、基本每股收益、毛利、经营活动现金流量净额分别是多少"


def build_simple_prompt(doc, pages):
    """'Simple' direct ask (eval_design §3.5): same report text and preamble as build_direct_prompt, but the
    question is one plain sentence — no definitions, no period wording, no request for original numbers.
    Identical for every company and template (banks are asked the same five items)."""
    body = "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)
    user = f"""以下是 {doc.get('name')}（{doc['code']}）的《{doc['title']}》全文，按页标注了页码。

{body}

---

{SIMPLE_QUESTION}"""
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
                    value, mult, kind, tol = to_value(raw, it.get("raw_unit") or it.get("raw_currency") or "元",
                                                       per_share=it.get("field") == "eps_basic")
                    if it.get("negative") and value > 0:
                        value = -value
                    rec["value"], rec["tolerance"] = value, tol
                    rec["currency"] = currency_code(it.get("raw_currency"), it.get("raw_unit"), market)
            except UnitError as e:
                rec["problems"].append(f"单位/数字无法解析：{e}")
                rec["status"] = "parser_error"
        out.append(rec)
    return out


# ---------------------------------------------------------------- revision R3: direct ask + verification layer
# A new cell designed after the frozen results were seen (eval_design §10). Same question as the professional
# direct ask, plus one closing sentence asking for the page and the source line of every number; the parsed
# answer then goes through the pipeline's own verification (C1–C4 + sanity checks + flag rule).

SOURCE_REQUEST = ("每个数字请同时给出它在报告中的页码（即 [PAGE n] 里的 n）和包含这个数字的原文句子或表格行（逐字照抄）；"
                  "如果某个数是你计算出来的，请说明用了哪几个原文数字，并分别给出它们的页码和原文。")


def build_verified_prompt(doc, template, pages):
    system, user = build_direct_prompt(doc, template, pages)
    return system, user + SOURCE_REQUEST


PARSER_SYSTEM_VERIFIED = PARSER_SYSTEM.replace("只输出一个 JSON 对象。", """7. page：回答为这个数字给出的页码（整数）；没给就填 0。
8. source_quote：回答为这个数字给出的“报告原文”句子或表格行，逐字照抄回答里的这段文字；没给就留空。
9. computed：回答是否说明这个数是自己计算出来的（例如“营业收入减营业成本”）。是的话，把回答里列出的
   每个计算用到的原文数字放进 components（name、sign：加为 1、减为 -1、raw_value、raw_unit、raw_currency、page、source_quote，
   同样逐字照抄回答）。
只输出一个 JSON 对象。""")


def build_verified_parser_prompt(answer, doc, template):
    _, user = build_parser_prompt(answer, doc, template)
    user = user.replace(
        '"raw_value": "", "raw_unit": "", "raw_currency": "", "negative": false, "quote": ""}]}',
        '"raw_value": "", "raw_unit": "", "raw_currency": "", "negative": false, "quote": "",\n'
        '  "page": 0, "source_quote": "", "computed": false,\n'
        '  "components": [{"name": "", "sign": 1, "raw_value": "", "raw_unit": "", "raw_currency": "", "page": 0,'
        ' "source_quote": ""}]}]}')
    return PARSER_SYSTEM_VERIFIED, user


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _signed(raw, negative):
    raw = nfkc(str(raw or "")).strip()
    if negative and raw and not re.match(r"^[(\-−–—]", raw):
        return "-" + raw
    return raw


def verified_raw_items(parsed, answer, doc):
    """Parser output -> raw items in the pipeline's extraction format, ready for verify.verify_report.
    Only numbers that really are in the answer pass (as in interpret_parsed). Page and source line come from
    the answer; the verification layer then checks them against the report itself."""
    items, notes = [], []
    for it in (parsed or {}).get("items") or []:
        if (it.get("status") or "answered") != "answered":
            continue
        raw = _signed(it.get("raw_value"), it.get("negative"))
        try:
            if not raw or not _in_answer(raw, answer):
                notes.append(f"{it.get('field')}/{it.get('period_type')}：解析出的数字不在回答文本里，丢弃")
                continue
        except UnitError:
            notes.append(f"{it.get('field')}/{it.get('period_type')}：数字无法解析，丢弃")
            continue
        base = {"field": it.get("field"), "period_type": it.get("period_type"), "period_start": None,
                "period_end": doc["period_end"], "raw_value": raw,
                "raw_unit": it.get("raw_unit") or it.get("raw_currency") or "",
                "raw_currency": it.get("raw_currency") or "", "page": _int(it.get("page")),
                "quote": it.get("source_quote") or "", "derivation": "reported", "answer_quote": it.get("quote")}
        comps = [c for c in it.get("components") or [] if c.get("raw_value")]
        if it.get("computed") and comps:
            base.update(derivation="derived", value_as_answered=raw, components=[
                {"name": c.get("name"), "sign": c.get("sign", 1), "raw_value": nfkc(str(c.get("raw_value"))),
                 "raw_unit": c.get("raw_unit") or base["raw_unit"],
                 "raw_currency": c.get("raw_currency") or base["raw_currency"],
                 "page": _int(c.get("page")), "quote": c.get("source_quote") or ""} for c in comps])
        elif it.get("computed"):
            base["computed_without_inputs"] = True
        items.append(base)
    return items, notes
