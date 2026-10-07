"""Regression tests for the rule revisions logged after the frozen eval1 run (eval_design §10).
Each case is the eval1 item that exposed the bug, cut down to what the rule needs."""
from decimal import Decimal

import pytest

from earnings_agent import benchmark
from earnings_agent.direct import build_verified_parser_prompt, build_verified_prompt, verified_raw_items
from earnings_agent.units import UnitError, currency_code, to_value
from earnings_agent.verify import check_number, verify_report


# ---------------------------------------------------------------- R1: TTM facts in a 10-Q are not FY

def _fake_facts(accn, end):
    def fact(start, val):
        return {"accn": accn, "end": end, "start": start, "val": val, "form": "10-Q"}
    return {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            fact("2026-01-01", 30_000), fact("2025-07-01", 161_403)]}},  # 6 months + trailing 12 months
        "NetIncomeLoss": {"units": {"USD": [fact("2026-04-01", 18_000), fact("2026-01-01", 35_000),
                                            fact("2025-07-01", 135_281)]}},
    }}}


def _doc(period, end="2026-06-30"):
    return {"market": "us", "code": "AMZN", "period": period, "period_end": end,
            "extra": {"cik": "x", "accession": "A1"}}


def test_r1_quarterly_filing_drops_trailing_twelve_months(monkeypatch):
    monkeypatch.setattr(benchmark, "sec_companyfacts", lambda cik: _fake_facts("A1", "2026-06-30"))
    rows = benchmark.us_benchmark(_doc("2026Q2"), "general")
    assert {(r["field"], r["period_type"]) for r in rows} == {
        ("operating_cash_flow", "H"), ("net_income_parent", "Q"), ("net_income_parent", "H")}


def test_r1_annual_filing_keeps_fy(monkeypatch):
    monkeypatch.setattr(benchmark, "sec_companyfacts", lambda cik: _fake_facts("A1", "2026-06-30"))
    rows = benchmark.us_benchmark(_doc("2026FY"), "general")
    assert ("operating_cash_flow", "FY") in {(r["field"], r["period_type"]) for r in rows}


# ---------------------------------------------------------------- R2: per-share units

@pytest.mark.parametrize("unit", [
    "in millions, except per share amounts",                 # WFC
    "Dollars and Shares in Millions, Except Per Share Data",  # USB
    "dollars in millions, except per common share data",      # AIG
    "Except Per Share Amounts",                               # INTC (was: unknown unit)
    "per common share",                                       # BAC (was: unknown unit)
    "in millions",                                            # bare table header
    "元/股", "人民币元", "per share",
])
def test_r2_per_share_never_inherits_the_amount_scale(unit):
    value, mult, kind, tol = to_value("2.02", unit, per_share=True)
    assert (value, mult, kind) == (2.02, 1, "per_share")
    assert tol == pytest.approx(0.005)


@pytest.mark.parametrize("unit", ["仙", "美分"])
def test_r2_cents_never_read_as_one(unit):
    # cents are a real per-share unit (×0.01): R2 must never silently read them as ×1
    # (until R6 they raised UnitError; since R6 they convert at 0.01)
    assert to_value("31.5", unit, per_share=True)[1] != 1


def test_r2_amounts_unchanged():
    assert to_value("2.02", "in millions")[0] == 2_020_000


# ---------------------------------------------------------------- R4: bare "dollars" in US filings

@pytest.mark.parametrize("unit", ["Millions of dollars", "Dollars in millions", "dollars in millions, except per share"])
def test_r4_bare_dollars_is_usd_in_us_filings(unit):  # CVX, BAC, AIG
    assert currency_code("dollars", unit, "us") == "USD"


def test_r4_only_us_market():
    assert currency_code("dollars", "dollars", "hk") is None and currency_code("", "dollars", "a") is None


# ---------------------------------------------------------------- R5: S5 prior ignores TTM

def test_r5_prior_start_ignores_trailing_twelve_months(monkeypatch):
    accn, end = "A2", "2026-06-30"
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"accn": accn, "end": end, "start": "2025-07-01", "val": 135_281},   # TTM listed first (AMZN)
        {"accn": accn, "end": end, "start": "2026-01-01", "val": 35_000},    # six months
        {"accn": accn, "end": end, "start": "2026-04-01", "val": 18_000},
        {"accn": "A1", "end": "2026-03-31", "start": "2026-01-01", "val": 17_000},   # Q1 = prior cumulative
        {"accn": "A0", "end": "2025-09-30", "start": "2025-07-01", "val": 21_187},   # wrong prior via TTM start
    ]}}}}}
    monkeypatch.setattr(benchmark, "sec_companyfacts", lambda cik: facts)
    doc = {"market": "us", "code": "AMZN", "period": "2026Q2", "period_end": end, "extra": {"cik": "x", "accession": accn}}
    prior = benchmark.us_prior(doc, "general")
    assert [(p["field"], p["period_end"], p["value"]) for p in prior] == [("net_income_parent", "2026-03-31", 17_000)]


def test_r2_eps_item_passes_c3():
    page = {"page": 5, "text": "Earnings per common share 2.02 1.95\nDiluted 2.01"}
    item = {"field": "eps_basic", "raw_value": "2.02", "raw_unit": "in millions, except per share amounts",
            "raw_currency": "$", "page": 5, "quote": "Earnings per common share 2.02 1.95"}
    res = check_number(item, [page], "us")
    assert res["c1"] and res["c2"] and res["c3"] and res["value"] == 2.02


# ---------------------------------------------------------------- R3: direct ask + verification layer

DOC = {"market": "a", "code": "000001", "name": "测试公司", "title": "2026 年半年度报告", "period": "2026H1",
       "period_end": "2026-06-30", "doc_kind": "半年报"}
PAGES = [{"page": 1, "text": "目录"},
         {"page": 7, "text": "合并利润表\n一、营业收入 1,234,567 1,100,000\n减：营业成本 734,567 700,000\n"
                             "归属于母公司股东的净利润 88,888 80,000\n基本每股收益（元/股） 0.45 0.40"},
         {"page": 9, "text": "经营活动产生的现金流量净额 99,999 90,000"}]


def test_r3_prompt_is_direct_prompt_plus_one_sentence():
    from earnings_agent.direct import SOURCE_REQUEST, build_direct_prompt
    s1, u1 = build_direct_prompt(DOC, "general", PAGES)
    s2, u2 = build_verified_prompt(DOC, "general", PAGES)
    assert s1 == s2 and u2 == u1 + SOURCE_REQUEST
    ps, pu = build_verified_parser_prompt("回答", DOC, "general")
    assert "source_quote" in ps and "source_quote" in pu


ANSWER = """营业收入 1,234,567 元（第 7 页：“一、营业收入 1,234,567 1,100,000”）
归母净利润 88,889 元（第 7 页）
毛利 500,000 元，由营业收入 1,234,567 减营业成本 734,567 计算（第 7 页）"""


def _parsed():
    return {"items": [
        {"field": "revenue", "period_type": "H", "status": "answered", "raw_value": "1,234,567", "raw_unit": "元",
         "raw_currency": "元", "page": 7, "source_quote": "一、营业收入 1,234,567 1,100,000"},
        {"field": "net_income_parent", "period_type": "H", "status": "answered", "raw_value": "88,889",
         "raw_unit": "元", "raw_currency": "元", "page": 7, "source_quote": ""},
        {"field": "gross_profit", "period_type": "H", "status": "answered", "raw_value": "500,000", "raw_unit": "元",
         "raw_currency": "元", "computed": True, "components": [
            {"name": "营业收入", "sign": 1, "raw_value": "1,234,567", "page": 7, "source_quote": "一、营业收入 1,234,567"},
            {"name": "营业成本", "sign": -1, "raw_value": "734,567", "page": 7, "source_quote": "减：营业成本 734,567"}]},
        {"field": "eps_basic", "period_type": "H", "status": "answered", "raw_value": "0.46", "raw_unit": "元/股"},
    ]}


def test_r3_only_numbers_present_in_the_answer_survive():
    items, notes = verified_raw_items(_parsed(), ANSWER, DOC)
    assert {i["field"] for i in items} == {"revenue", "net_income_parent", "gross_profit"}  # 0.46 not in answer
    assert any("eps_basic" in n for n in notes)


def test_r3_verification_flags_what_it_cannot_confirm():
    from earnings_agent.direct_verify import verify_direct_answer
    ctx = {"doc": DOC, "pages": PAGES, "template": "general", "benchmarks": [], "prior": []}
    out = verify_direct_answer(ctx, _parsed(), ANSWER)
    by = {(i["field"], i["period_type"]): i for i in out["items"]}
    assert by[("revenue", "H")]["c1"] and by[("revenue", "H")]["c2"]
    ni = by[("net_income_parent", "H")]
    assert ni["status"] == "❌" and ni["category"] == "数字编造" and ni["value"] == 88_889  # one digit changed
    gp = by[("gross_profit", "H")]
    assert gp["status"] != "❌" and gp["value"] == 500_000 and gp["value_recomputed"] == 500_000
    assert by[("eps_basic", "H")]["category"] == "漏抽"  # dropped by the answer check -> required but missing


def test_r3_wrong_arithmetic_is_flagged_but_scored_as_answered():
    from earnings_agent.direct_verify import verify_direct_answer
    parsed = _parsed()
    parsed["items"][2]["raw_value"] = "510,000"
    answer = ANSWER.replace("毛利 500,000", "毛利 510,000")
    ctx = {"doc": DOC, "pages": PAGES, "template": "general", "benchmarks": [], "prior": []}
    gp = next(i for i in verify_direct_answer(ctx, parsed, answer)["items"] if i["field"] == "gross_profit")
    assert gp["status"] == "❌" and gp["value"] == 510_000 and gp["value_recomputed"] == 500_000


def test_verify_report_signature_unchanged():
    # the verified cell must use the pipeline's verification unchanged
    items, metrics, dropped, inv = verify_report([], [], PAGES, DOC, "general", [], [])
    assert all(i["category"] == "漏抽" for i in items)


# ---------------------------------------------------------------- R6: per-share figures in cents (product only)

@pytest.mark.parametrize("raw,unit,value,cur", [
    ("70.40", "仙", 0.704, None),             # 02331: 70.40 仙 = 0.704 元
    ("70.40", "每股（人民幣仙）", 0.704, "CNY"),
    ("151.6", "美仙", 1.516, "USD"),          # 02888
    ("41.21", "US cents", 0.4121, "USD"),     # 01299
    ("37.9", "美分", 0.379, "USD"),           # 02378
    ("(5.04)", "US cents per share", -0.0504, "USD"),  # 00992 loss
    ("12.3", "港仙", 0.123, "HKD"),
])
def test_r6_cents(raw, unit, value, cur):
    v, mult, kind, tol = to_value(raw, unit, per_share=True)
    assert v == pytest.approx(value) and kind == "per_share" and mult == Decimal("0.01")
    assert tol == pytest.approx(0.5 * 10 ** -len(raw.strip("()").split(".")[1]) * 0.01)
    assert currency_code("", unit, "hk") == cur


def test_r6_yuan_and_dollars_unchanged():
    assert to_value("0.704", "元/股", per_share=True)[0] == 0.704
    assert to_value("2.02", "per share", per_share=True)[0] == 2.02
