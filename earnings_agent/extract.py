"""Model extraction: build the prompt from the selected pages, call the LLM (cached), return raw items.
The model copies numbers and units verbatim; it never converts or computes."""
import json

from .periods import cumulative_type, parse_period
from .templates import FIELDS

FIELD_DEFS = {
    "revenue": {
        "a": "合并利润表“营业收入”行（不要用“营业总收入”）。银行：合并利润表“营业收入”行。",
        "hk": "合并损益表的收入总额行（收入/營業額/Revenue，包括“其他”分部收入的合计）。"
              "银行：扣除预期信贷损失之前的营业收益净额（报告常称“收入”或“未扣除预期信贷损失…之营业收益净额”），"
              "不要用扣除预期信贷损失之后的营业收益净额。",
        "us": "利润表 Total net sales / Total revenues / Revenues 合计行。银行：Total net revenue（reported 口径，"
              "不要 managed basis / FTE 口径）。",
    },
    "net_income_parent": "归属于母公司所有者的净利润合计（A股“归属于母公司股东的净利润”；IFRS “本公司权益持有人/股东应占”；"
                         "US GAAP “Net income attributable to <公司>”/Net income）。若报告再拆分出普通股股东应占与其他权益工具"
                         "（永续债、优先股等）持有者应占，此字段取合计，另把普通股股东应占填到 net_income_common。"
                         "若报表没有“母公司所有者合计”这一行、只分列普通股股东和其他权益持有人，则 derivation=derived，"
                         "components 列出这些分项（sign 都为 +1），不要只填普通股股东那一项。不要扣非。不要把非控股权益算进去。",
    "net_income_common": "（可选）普通股股东应占净利润，仅当报告单独列示时填写。",
    "eps_basic": "基本每股收益（每普通股）。若报告同时列示每 ADS，另填 eps_basic_per_ads。",
    "eps_basic_per_ads": "（可选）每 ADS 基本每股收益，仅当报告列示时填写。",
    "weighted_avg_shares_basic": "计算基本每股收益所用的普通股加权平均股数（与 eps_basic 同期间）。raw_unit 填适用于股数的单位"
                                 "（例如“股”“千股”“百万股”“shares in thousands”），不要填金额的单位。原文没有就不填。",
    "gross_profit": "报表上明确列示的毛利行（毛利/Gross profit/Gross margin）。若报表没有毛利行，不要自己计算，"
                    "改为抽取 cost_of_revenue。",
    "cost_of_revenue": "营业成本/销售成本/Cost of revenue 合计行（A股为“营业成本”，不含税金及附加）。"
                       "当报表没有毛利行时必须抽取。",
    "operating_cash_flow": "合并现金流量表“经营活动产生的现金流量净额”（扣除已付税项后的净额行）。",
    "net_interest_income": "净利息收入/利息净收入/Net interest income（不要 FTE 口径）。",
    "ppop": "拨备前利润。若报告明示（拨备前利润/Pre-provision profit），直接抽取，derivation=reported。"
            "否则 derivation=derived，value 留空，在 components 里列出组成项（sign 表示加或减：+1/-1；"
            "raw_value 仍照抄原文，括号也照抄，代码按 sign 和绝对值计算）："
            "A股 = 营业收入(+) − 税金及附加(−) − 业务及管理费(−) − 其他业务成本(−)；"
            "港股/美股 = 扣除信贷损失前的收入(+) − 营业支出总额(−，不含信用减值/预期信贷损失)。",
    "insurance_revenue": "保险服务收入（IFRS 17/新准则）。没有则不填。",
    "insurance_service_result": "保险服务业绩（报告明示时）。没有则不填。",
}

SYSTEM = """你是卖方研究员的财报数据抽取助手。只根据给定页面抽取，绝不编造。
硬性规则：
1. raw_value 必须逐字照抄页面上的数字字符串（包括千分位逗号、括号、负号、小数位），不换算、不四舍五入、不改单位。
2. raw_unit 照抄该数字所在表格或段落声明的单位（例如“人民币百万元”“千元”“元”“$ in millions”“元/股”“%”）。
   raw_currency 照抄币种字样（例如“人民币”“美元”“US$”“HK$”）；页面没写币种就填页面上能看到的最接近的字样，例如“元”。
3. page 填数字所在页的 [PAGE n] 编号。quote 必须是包含该数字的**一整行**原文，逐字复制：表格行要保留该行的
   所有列（包括同一行里其他期间的数字和附注号），不要删减、不要拼接多行、不要改写。若该行没有行名
   （例如合计行），就复制整行数字。
4. 只抽目标报告期的数。上年同期等对比数不要抽。若原文同时披露单季与累计（三个月 vs 六个月/九个月），两个都抽，
   period_type 分别为 Q 与 H（六个月）或 YTD（九个月）；全年为 FY。
5. quote、raw_unit、raw_currency 保持原文字形：原文是繁体就用繁体，不要转成简体。
6. 期末余额类数字（总资产、存款余额、资本充足率、不良率等时点数）period_type 填 PIT，period_start 留空。
7. 做不到的字段不要填，不要编。
只输出一个 JSON 对象。"""


def period_instructions(doc):
    """Tell the model which period columns to extract: cumulative always, the single quarter when shown."""
    part = parse_period(doc["period"])[1]
    cum = cumulative_type(part)
    cum_months = {"Q": 3, "H": 6, "YTD": 9, "FY": 12}[cum]
    lines = [f"每个字段要抽的期间（都以 {doc['period_end']} 结束；上年同期不要）："
             f"\n- 累计 {cum_months} 个月：period_type={cum}"]
    if cum != "Q":
        lines.append("- 单季（最近三个月）：period_type=Q —— 只要原文表格里有“三个月/本报告期/本季度/Three Months Ended”这一列"
                     "就必须同时抽出，和累计数各一条")
    lines.append("现金流量表通常只有累计数，这种情况只抽累计。")
    return "\n".join(lines)


def build_prompt(doc, template, pages, selected):
    fields = FIELDS[template] + ["net_income_common", "eps_basic_per_ads", "weighted_avg_shares_basic"]
    if template == "general":
        fields.append("cost_of_revenue")
    defs = []
    for f in fields:
        d = FIELD_DEFS[f]
        if isinstance(d, dict):
            d = d[doc["market"]]
        defs.append(f"- {f}: {d}")
    by_num = {p["page"]: p["text"] for p in pages}
    body = "\n\n".join(f"[PAGE {n}]\n{by_num[n]}" for n in selected)
    schema = {
        "business_summary": "一句话概括公司主营业务",
        "items": [{
            "field": "字段名", "raw_value": "照抄的数字", "raw_unit": "照抄的单位", "raw_currency": "照抄的币种字样",
            "period_type": "Q|H|YTD|FY|PIT", "period_start": "YYYY-MM-DD", "period_end": "YYYY-MM-DD",
            "page": 0, "quote": "照抄原文", "derivation": "reported|derived",
            "components": [{"name": "组成项名称", "sign": 1, "raw_value": "", "raw_unit": "", "raw_currency": "",
                            "page": 0, "quote": ""}],
        }],
        "industry_metrics": [{
            "name": "指标名", "rationale": "为什么这个指标对这家公司重要（1-2句）", "raw_value": "", "raw_unit": "",
            "raw_currency": "", "period_type": "Q|H|YTD|FY|PIT", "period_start": "", "period_end": "", "page": 0, "quote": "",
        }],
    }
    user = f"""公司：{doc.get('name')}（{doc['market'].upper()} {doc['code']}）
文件：{doc['title']}（{doc['doc_kind']}），目标报告期：{doc['period']}，期末日：{doc['period_end']}
行业模板：{template}

{period_instructions(doc)}

需要抽取的字段（字段名 + 口径）：
{chr(10).join(defs)}

另外：根据公司业务，从页面中提出 3-6 个行业特色指标（industry_metrics），每个都要给理由、页码和原文引用，
数字同样照抄、不换算。不要把上面的核心字段重复放进 industry_metrics。

输出 JSON 格式：
{json.dumps(schema, ensure_ascii=False, indent=1)}

以下是报告页面（已规范化）：
{body}"""
    return SYSTEM, user


def build_followup_prompt(doc, template, pages, selected, missing):
    """Same pages and instructions, asking once more only for the (field, period_type) pairs that were missing."""
    system, user = build_prompt(doc, template, pages, selected)
    names = {"Q": "单季（三个月）", "H": "半年累计", "YTD": "年初至今累计", "FY": "全年"}
    ask = "\n".join(f"- {f}，period_type={t}（{names.get(t, t)}）" for f, t in missing)
    user += f"""

=== 补问 ===
上一轮回答缺少下面这些字段/期间。请只针对它们再看一遍页面，按同样的 JSON 格式只返回 items
（industry_metrics 返回空数组）。如果页面里确实没有，就不要填，并在 "not_found" 数组里写明字段名和原因。
{ask}"""
    return system, user
