"""Result-page extras: prior-year figures, year-on-year changes, ratios, the conclusion area and highlights.

- Prior-year (comparative) figures: the core extraction prompt deliberately skips them, so one extra model call
  copies them from the same pages. Every copied number then passes the core C1–C3 checks
  (earnings_agent.verify.check_number) and must end about one year before the current period; anything else is
  dropped and listed in the run log.
- Year-on-year changes, gross / net margins and the conclusion sentence are computed here, in code.
- Highlights are written by the model, in Chinese and English in one call, from the result table only (no filing
  text). Code keeps a point only if, in both languages,
  every number in it appears in that table or in the code-computed figures, its pages are pages of those
  figures, and it has no advice, forecast or praise words. Dropped points go to the run log.
"""
from __future__ import annotations

import json
import re
from datetime import date

from earnings_agent.periods import parse_period, period_end
from earnings_agent.verify import check_number

PER_SHARE = {"eps_basic", "eps_basic_per_ads"}
FLOW_ORDER = ["revenue", "net_income_parent", "gross_profit", "operating_cash_flow", "eps_basic",
              "net_interest_income", "ppop", "insurance_revenue", "insurance_service_result",
              "cost_of_revenue", "net_income_common"]

# ---------------------------------------------------------------- units and periods (display)

SCALE = {1: ("", ""), 1e3: ("千", "thousands"), 1e4: ("万", "ten-thousands"), 1e6: ("百万", "millions"),
         1e8: ("亿", "hundred-millions"), 1e9: ("十亿", "billions")}
CUR = {"USD": ("美元", "USD"), "CNY": ("人民币", "RMB"), "HKD": ("港元", "HKD"), "EUR": ("欧元", "EUR"),
       "JPY": ("日元", "JPY"), "GBP": ("英镑", "GBP"), "TWD": ("新台币", "TWD"), "SGD": ("新加坡元", "SGD")}


def unit_label(currency, mult, per_share):
    """('百万美元', 'USD millions') / ('美元/股', 'USD per share'); None when the currency is unknown."""
    cz, ce = CUR.get(currency or "", (None, None))
    if not cz:
        return None
    if per_share:
        return f"{cz}/股", f"{ce} per share"
    sz, se = SCALE.get(float(mult or 1), (None, None))
    if sz is None:
        return None
    return f"{sz}{cz}", (f"{ce} {se}" if se else ce)


CAL_PART = {"Q1": ("第一季度", "Q1"), "Q2": ("第二季度", "Q2"), "H1": ("上半年", "H1"), "Q3": ("第三季度", "Q3"),
            "FY": ("全年", "FY")}


def period_label(doc):
    """{'zh', 'en', 'fiscal'}: 'FY2026 Q3（财年）' when the fiscal year does not follow the calendar."""
    try:
        y, part = parse_period(doc["period"])
        fiscal = abs((date.fromisoformat(doc["period_end"]) - period_end(doc["period"])).days) > 15
    except (KeyError, ValueError, TypeError):
        return {"zh": doc.get("period") or "", "en": doc.get("period") or "", "fiscal": False}
    if fiscal:
        tail = "" if part == "FY" else f" {part}"
        return {"zh": f"FY{y}{tail}（财年）", "en": f"FY{y}{tail} (fiscal)", "fiscal": True}
    zh, en = CAL_PART[part]
    return {"zh": f"{y} 年{zh}", "en": f"FY{y}" if part == "FY" else f"{en} {y}", "fiscal": False}


# ---------------------------------------------------------------- prior-year figures (one model call + C1–C3)

COMP_SYSTEM = """你是财报数据抽取助手。只根据给定页面，抄写指定指标的“上年同期”（对比期）数字，绝不编造、不计算。
硬性规则：
1. raw_value 逐字照抄页面上的数字字符串（千分位、括号、负号、小数位都保留），不换算、不四舍五入。
2. raw_unit 照抄该数字所在表格或段落声明的单位；raw_currency 照抄币种字样。
3. page 填 [PAGE n] 的 n；quote 复制包含该数字的一整行原文，逐字照抄，不删减、不改写。
4. period_end 填上年同期的期末日（YYYY-MM-DD），period_type 与本期相同。
5. 页面上找不到的，不要填，把字段名写进 not_found。
只输出一个 JSON 对象。"""


def _days(a, b):
    try:
        return (date.fromisoformat(a) - date.fromisoformat(b)).days
    except (TypeError, ValueError):
        return None


def comparative_prompt(ctx, items):
    """items: verified current items. Asks for the same rows' prior-year column."""
    wanted = [i for i in items if i.get("field") in FLOW_ORDER and i.get("period_type") != "PIT"]
    lines = []
    for i in wanted:
        if i.get("derivation") == "derived" and i.get("components"):
            continue  # derived values: their components (e.g. cost_of_revenue) are asked for instead
        lines.append(f"- {i['field']}，period_type={i['period_type']}：本期（截至 {i.get('period_end')}）为 "
                     f"{i.get('raw_value')}，第 {i.get('page_used') or i.get('page')} 页，原文行：{i.get('quote') or ''}")
    by_num = {p["page"]: p["text"] for p in ctx["pages"]}
    body = "\n\n".join(f"[PAGE {n}]\n{by_num[n]}" for n in ctx["selected"] if n in by_num)
    schema = {"items": [{"field": "", "period_type": "", "period_end": "YYYY-MM-DD", "raw_value": "", "raw_unit": "",
                         "raw_currency": "", "page": 0, "quote": ""}], "not_found": [""]}
    user = f"""公司：{ctx['doc'].get('name')}，文件：{ctx['doc'].get('title')}

请抄出下面每一项的上年同期数字（通常就在本期数字同一行的对比列里）：
{chr(10).join(lines)}

输出 JSON 格式：
{json.dumps(schema, ensure_ascii=False)}

以下是报告页面：
{body}"""
    return COMP_SYSTEM, user


def check_comparatives(data, ctx, items):
    """Keep a returned prior-year number only if it passes C1–C3 and ends ~1 year before the current one."""
    market = ctx["doc"]["market"]
    cur = {(i["field"], i["period_type"]): i for i in items}
    kept, rejected = [], []
    for r in (data or {}).get("items") or []:
        key = (r.get("field"), r.get("period_type"))
        now = cur.get(key)
        if not now or not r.get("raw_value"):
            rejected.append({"field": key[0], "ptype": key[1], "why": "不是要的指标或期间"})
            continue
        gap = _days(now.get("period_end"), r.get("period_end"))
        if gap is None or not 350 <= gap <= 380:
            rejected.append({"field": key[0], "ptype": key[1], "why": f"期末日 {r.get('period_end')} 不是上年同期"})
            continue
        res = check_number(dict(r), ctx["pages"], market)
        if not (res["c1"] and res["c2"] and res["c3"]):
            rejected.append({"field": key[0], "ptype": key[1], "why": "；".join(res["reasons"]) or "未通过核验"})
            continue
        kept.append({"field": key[0], "ptype": key[1], "period_end": r.get("period_end"), "raw": r.get("raw_value"),
                     "unit": r.get("raw_unit"), "value": res["value"], "multiplier": float(res["multiplier"]),
                     "currency": res.get("currency"), "page": res["page_used"], "quote": r.get("quote")})
    seen, out = set(), []
    for k in kept:  # first one wins
        if (k["field"], k["ptype"]) not in seen:
            seen.add((k["field"], k["ptype"]))
            out.append(k)
    return {"items": out, "rejected": rejected, "not_found": (data or {}).get("not_found") or []}


def comparatives(ctx, res, complete):
    """complete(system, user) -> parsed JSON. Returns check_comparatives() output."""
    items = [i for i in res["items"] if i.get("status") in ("✅", "⚠️", "❌")]
    system, user = comparative_prompt(ctx, items)
    return check_comparatives(complete(system, user), ctx, items)


# ---------------------------------------------------------------- year-on-year, ratios, conclusion (code)

def _fmt_num(v, mult):
    x = v / float(mult or 1)
    return f"{x:,.0f}" if abs(x) >= 100 or float(x).is_integer() else f"{x:,.2f}"


def yoy(cur_value, prev_value):
    """(pct or None, note) — no percentage when the prior value is zero or negative."""
    if cur_value is None or prev_value is None:
        return None, "missing"
    if prev_value <= 0:
        return None, "prior_not_positive"
    return (cur_value - prev_value) / prev_value, None


def enrich(pl, res):
    """Add yoy to payload items, ratios, conclusion and key cards. pl = core.payload output."""
    comps = (res.get("comparatives") or {}).get("items") or []
    prior = {(c["field"], c["ptype"]): c for c in comps}
    # code-derived prior gross profit (A-share style): revenue − |cost of revenue|
    for (f, t), c in list(prior.items()):
        if f == "cost_of_revenue" and ("revenue", t) in prior and ("gross_profit", t) not in prior:
            r = prior[("revenue", t)]
            prior[("gross_profit", t)] = {"field": "gross_profit", "ptype": t, "raw": None, "derived": True,
                                          "value": r["value"] - abs(c["value"]), "multiplier": r["multiplier"],
                                          "page": c["page"], "currency": r.get("currency")}
    for it in pl["items"]:
        p = prior.get((it["field"], it["ptype"]))
        it["yoy"] = None
        if not p:
            continue
        pct, note = (None, "current_flagged") if it["status"] == "❌" else yoy(it.get("value"), p["value"])
        it["yoy"] = {"pct": pct, "note": note, "prev_raw": p["raw"] or _fmt_num(p["value"], p.get("multiplier")),
                     "prev_value": p["value"], "prev_page": p.get("page"), "prev_derived": bool(p.get("derived"))}
    cur = {(i["field"], i["ptype"]): i for i in pl["items"] if i["status"] != "❌"}
    ratios = []
    for t in sorted({i["ptype"] for i in pl["items"]}, key=lambda x: ["Q", "H", "YTD", "FY"].index(x) if x in ["Q", "H", "YTD", "FY"] else 9):
        rev = cur.get(("revenue", t))
        if not rev or not rev.get("value") or rev["value"] <= 0:
            continue
        for key, num_f in (("gross_margin", "gross_profit"), ("net_margin", "net_income_parent")):
            num = cur.get((num_f, t))
            if not num or num.get("value") is None:
                continue
            now = num["value"] / rev["value"]
            pr, pn = prior.get(("revenue", t)), prior.get((num_f, t))
            prev = pn["value"] / pr["value"] if pr and pn and pr["value"] > 0 else None
            ratios.append({"key": key, "ptype": t, "value": now, "prev": prev,
                           "change_pp": (now - prev) * 100 if prev is not None else None,
                           "pages": sorted({x for x in (rev.get("page"), num.get("page")) if x})})
    pl["ratios"] = ratios
    core_items = [i for i in pl["items"] if not i["aux"]]
    pl["summary"] = {"n": len(core_items),
                     "ok": sum(1 for i in core_items if i["status"] == "✅"),
                     "warn": sum(1 for i in core_items if i["status"] == "⚠️"),
                     "bad": [{"field": i["field"], "name_zh": i["name_zh"], "name_en": i["name_en"], "ptype": i["ptype"]}
                             for i in core_items if i["status"] == "❌"]}
    part = pl["doc"]["period"][4:] if pl["doc"].get("period") else ""
    has_q = any(i["ptype"] == "Q" for i in core_items)
    t = "Q" if part in ("Q1", "Q2", "Q3") and has_q else pl["cum"]
    cards = []
    for f in ("revenue", "net_income_parent", "gross_margin", "eps_basic"):
        if f == "gross_margin":
            r = next((x for x in ratios if x["key"] == "gross_margin" and x["ptype"] == t), None)
            if r:
                cards.append({"key": f, "ptype": t, "ratio": r})
            continue
        it = next((i for i in core_items if i["field"] == f and i["ptype"] == t), None)
        if it:
            cards.append({"key": f, "ptype": t, "field": f, "raw": it["raw"], "unit_zh": it.get("unit_zh"),
                          "unit_en": it.get("unit_en"), "status": it["status"], "yoy": it.get("yoy"), "page": it["page"]})
    pl["cards"] = cards
    # only when the prior-year call ran (single analysis, examples); compare rows and Verify have none
    pl["comparatives_log"] = {"kept": len(comps), "rejected": res["comparatives"].get("rejected") or [],
                              "not_found": res["comparatives"].get("not_found") or [],
                              "error": res["comparatives"].get("error")} if res.get("comparatives") else None
    pl["doc"]["period_label"] = period_label(pl["doc"])
    return pl


# ---------------------------------------------------------------- highlights (model writes, code checks)

PTYPE_WORDS = {"zh": {"Q": "单季", "H": "上半年累计", "YTD": "前三季度累计", "FY": "全年"},
               "en": {"Q": "quarter", "H": "six months", "YTD": "nine months", "FY": "full year"}}
RATIO_NAMES = {"gross_margin": ("毛利率", "Gross margin"), "net_margin": ("归母净利率", "Net margin (attributable)")}

HL_SYSTEM = """根据给定的结果表写 3–5 条业绩要点，每条同时写中文版 text_zh 和英文版 text_en（两版意思相同）。
Write 3–5 results highlights from the given result table, each in Chinese (text_zh) and English (text_en).
硬性规则 / Hard rules:
1. 只能使用 facts_zh / facts_en 里的数字，原样照抄给出的写法（千分位、小数位、百分号都照抄）。
   Use only numbers from the facts, written exactly as given.
2. 不许自己计算任何数字：不算差额、倍数、占比、增速，也不换算单位（例如不能把百万写成亿）。
   Do not calculate anything (no differences, multiples, shares, growth rates) and do not convert units.
3. 每条在 pages 里写出所用数字的页码（取自 facts 的 page / prior_page / pages）。
   List the page numbers of the figures used in pages.
4. 可以描述增减方向和幅度。You may describe direction and size of changes.
5. 禁止买卖或投资建议、对未来的预测或推测、评价性形容词（如强劲、亮眼、出色、疲软、惨淡、超预期）。
   No advice, no forecasts or speculation, no evaluative adjectives (strong, robust, impressive, solid, weak, beat, miss...).
6. 只描述事实，不解释原因。State facts only, no causes.
只输出 JSON / Output JSON only: {"points": [{"text_zh": "", "text_en": "", "pages": [0]}]}"""

BANNED = re.compile(
    r"建议|买入|卖出|增持|减持|持有|目标价|预计|预期|预测|有望|将会|看好|看空|强劲|亮眼|出色|优异|稳健|疲软|惨淡|"
    r"超预期|不及预期|靓丽|喜人|\b(buy|sell|hold|overweight|underweight|outperform|underperform|target price|"
    r"recommend\w*|expect\w*|forecast\w*|predict\w*|outlook|will|likely|should|strong\w*|robust|impressive|"
    r"solid|weak\w*|disappoint\w*|beat|miss\w*|stellar|healthy|remarkabl\w*)\b", re.I)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _pct(x, signed=True):
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def _change_words(x, lang, unit="%"):
    """Direction in words, magnitude unsigned: '增长 25.5%' / 'down 4.9%' / '持平' (x in % or points)."""
    if round(abs(x), 1) == 0:
        return "持平" if lang == "zh" else "flat"
    up = x > 0
    if unit == "pp":
        return (f"{'增加' if up else '减少'} {abs(x):.1f} 个百分点" if lang == "zh"
                else f"{'up' if up else 'down'} {abs(x):.1f} percentage points")
    return f"{'增长' if up else '下降'} {abs(x):.1f}%" if lang == "zh" else f"{'up' if up else 'down'} {abs(x):.1f}%"


def facts(pl, lang):
    out = []
    zh = lang == "zh"
    for it in pl["items"]:
        if it["aux"] or it["status"] == "❌" or it.get("raw") is None and it.get("value") is None:
            continue
        unit = (it.get("unit_zh") if zh else it.get("unit_en")) or it.get("unit") or ""
        y = it.get("yoy") or {}
        f = {"metric": it["name_zh"] if zh else it["name_en"], "period": PTYPE_WORDS[lang].get(it["ptype"], it["ptype"]),
             "value": f"{it['raw'] or _fmt_num(it['value'], 1)} {unit}".strip(), "page": it["page"]}
        if y.get("prev_raw"):
            f.update(prior_value=f"{y['prev_raw']} {unit}".strip(), prior_page=y.get("prev_page"))
        if y.get("pct") is not None:
            f["yoy"] = _change_words(y["pct"] * 100, lang)
        out.append(f)
    for r in pl.get("ratios") or []:
        f = {"metric": RATIO_NAMES[r["key"]][0 if zh else 1], "period": PTYPE_WORDS[lang].get(r["ptype"], r["ptype"]),
             "value": _pct(r["value"], False), "pages": r["pages"], "computed_by_code": True}
        if r["prev"] is not None:
            f["prior_value"] = _pct(r["prev"], False)
            f["change"] = _change_words(r["change_pp"], lang, "pp")
        out.append(f)
    return out


def _allowed(fs, doc):
    allowed, pages = set(), set()
    for f in fs:
        for k in ("value", "prior_value", "yoy", "change", "period"):
            for n in NUM.findall(str(f.get(k) or "")):
                allowed.add(n.replace(",", ""))
        pages |= {p for p in [f.get("page"), f.get("prior_page")] + list(f.get("pages") or []) if p}
    for n in NUM.findall(f"{doc.get('period') or ''} {(doc.get('period_label') or {}).get('zh', '')}"):
        allowed.add(n.replace(",", ""))
    return allowed, pages


def _problem(text, pg, allowed, pages):
    """None, or the reason as (zh, en)."""
    bad_nums = [n for n in NUM.findall(text) if n.replace(",", "") not in allowed]
    if not text:
        return "缺少一种语言的文字", "missing in one language"
    if bad_nums:
        return "数字不在结果表里：" + "、".join(bad_nums), "numbers not in the result table: " + ", ".join(bad_nums)
    if not pg:
        return "没有页码", "no page given"
    if any(x not in pages for x in pg):
        bad = [str(x) for x in pg if x not in pages]
        return "页码不是结果表里的页码：" + "、".join(bad), "pages not in the result table: " + ", ".join(bad)
    m = BANNED.search(text)
    if m:
        return "含有评价、预测或建议用语：" + m.group(0), "evaluative, forecast or advice wording: " + m.group(0)
    return None


def check_points(points, fs, doc):
    """Keep a point only if both language versions pass: numbers from the facts, valid pages, no banned words."""
    allowed, pages = _allowed(fs, doc)
    kept, dropped = [], []
    for p in points or []:
        p = p or {}
        try:
            pg = [int(x) for x in (p.get("pages") or [])]
        except (TypeError, ValueError):
            pg = []
        zh, en = str(p.get("text_zh") or "").strip(), str(p.get("text_en") or "").strip()
        why = _problem(zh, pg, allowed, pages) or _problem(en, pg, allowed, pages)
        (dropped if why else kept).append({"text_zh": zh, "text_en": en, "pages": pg,
                                           **({"why_zh": why[0], "why_en": why[1]} if why else {})})
    return kept[:5], dropped


def highlights(pl, complete):
    """complete(system, user) -> parsed JSON. One call, both languages. Returns {"points", "dropped"}."""
    fz, fe = facts(pl, "zh"), facts(pl, "en")
    if not fz:
        return {"points": [], "dropped": []}
    d = pl["doc"]
    user = (f"公司 / Company：{d.get('name')}；报告期 / period：{d['period_label']['zh']} / {d['period_label']['en']}，"
            f"截至 / ended {d.get('period_end')}\n\nfacts_zh:\n{json.dumps(fz, ensure_ascii=False, indent=1)}"
            f"\n\nfacts_en:\n{json.dumps(fe, ensure_ascii=False, indent=1)}")
    data = complete(HL_SYSTEM, user)
    kept, dropped = check_points((data or {}).get("points"), fz + fe, d)
    return {"points": kept, "dropped": dropped}


if __name__ == "__main__":  # self-check of the code-side rules
    assert unit_label("USD", 1e6, False) == ("百万美元", "USD millions")
    assert unit_label("USD", 1e6, True) == ("美元/股", "USD per share")
    assert unit_label("CNY", 1e6, False)[0] == "百万人民币"
    assert period_label({"period": "2026Q3", "period_end": "2026-05-28"})["zh"] == "FY2026 Q3（财年）"
    assert period_label({"period": "2026H1", "period_end": "2026-06-30"})["zh"] == "2026 年上半年"
    assert yoy(110, 100)[0] == 0.1 and yoy(5, -2) == (None, "prior_not_positive")
    fs = [{"metric": "营业收入", "period": "单季", "value": "9,301 百万美元", "prior_value": "6,811 百万美元",
           "yoy": _change_words(36.6, "zh"), "page": 5, "prior_page": 5}]
    assert _change_words(-4.94, "en") == "down 4.9%" and _change_words(0.01, "zh") == "持平"
    en = "Quarterly revenue was 9,301 USD millions, up 36.6% year on year."
    k, d = check_points([{"text_zh": "单季营业收入 9,301 百万美元，同比增长 36.6%。", "text_en": en, "pages": [5]},
                         {"text_zh": "营业收入约 93 亿美元。", "text_en": en, "pages": [5]},
                         {"text_zh": "单季营业收入同比增长 36.6%。", "text_en": en + " A strong quarter.", "pages": [5]},
                         {"text_zh": "单季营业收入 9,301 百万美元。", "text_en": en, "pages": [7]}], fs, {"period": "2026Q3"})
    assert [p["text_zh"][:6] for p in k] == ["单季营业收入"] and len(d) == 3, (k, d)
    print("insights self-check OK")
