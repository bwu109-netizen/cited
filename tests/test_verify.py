from earnings_agent.verify import BAD, FOUND, OK, check_number, number_on_page, quote_on_page, verify_report

PAGE = """簡明綜合收益表
截至六月三十日止六個月
人民幣百萬元
收入 2 204,785 184,504 401,243 364,526
毛利 118,433 105,013 229,698 205,506
本公司權益持有人 56,022 55,628 114,115 103,449"""
PAGES = [{"page": 1, "text": "目錄"}, {"page": 2, "text": PAGE}, {"page": 3, "text": "其他 12,345"}]
DOC = {"market": "hk", "period_end": "2026-06-30", "period": "2026H1"}


def item(**kw):
    base = {"field": "revenue", "raw_value": "401,243", "raw_unit": "人民幣百萬元", "raw_currency": "人民幣",
            "period_type": "H", "period_start": "2026-01-01", "period_end": "2026-06-30", "page": 2,
            "quote": "收入 2 204,785 184,504 401,243 364,526"}
    base.update(kw)
    return base


def test_quote_exact_fuzzy_and_script_insensitive():
    assert quote_on_page("收入 2 204,785 184,504 401,243 364,526", PAGE) == (True, 1.0)
    ok, r = quote_on_page("本公司权益持有人 56,022 55,628 114,115 103,449", PAGE)  # simplified transcription
    assert ok and r == 1.0
    ok, r = quote_on_page("收入：204,785 184,504 401,243 364,526", PAGE)  # colon added, note number dropped
    assert ok and 0.9 <= r < 1.0
    assert not quote_on_page("完全無關的一句話 999", PAGE)[0]


def test_number_must_be_whole_number():
    assert number_on_page("401,243", PAGE)
    assert not number_on_page("01,243", PAGE)      # part of a larger number
    assert not number_on_page("401,24", PAGE)


def test_one_digit_changed_in_quote_is_fabrication():
    """Model alters one digit in both value and quote: the quote still fuzzily matches (>=0.90),
    but the number is not on the page -> ❌ 数字编造."""
    bad = item(raw_value="401,248", quote="收入 2 204,785 184,504 401,248 364,526")
    r = check_number(bad, PAGES, "hk")
    assert r["c1"] is True and r["quote_ratio"] >= 0.90   # fuzzy quote match alone would let it through
    assert r["c2"] is False
    assert r["category"] == "数字编造"
    items, _, _, _ = verify_report([bad], [], PAGES, DOC, "general", [])
    assert items[0]["status"] == BAD and items[0]["category"] == "数字编造"


def test_number_on_wrong_page_is_page_error():
    r = check_number(item(raw_value="12,345", quote="其他 12,345", page=2), PAGES, "hk")
    assert r["c2"] is False or r["page_used"] == 3
    assert any("3" in x for x in r["reasons"])


def test_status_with_and_without_benchmark():
    bench = [{"field": "revenue", "period_type": "H", "period_end": "2026-06-30", "value": 401_243e6,
              "currency": None, "source": "t", "source_field": "营运收入"}]
    items, _, _, _ = verify_report([item()], [], PAGES, DOC, "general", bench)
    assert items[0]["status"] == OK
    items, _, _, _ = verify_report([item()], [], PAGES, DOC, "general", [])
    assert items[0]["status"] == FOUND
    wrong = [dict(bench[0], value=396_431e6)]
    items, _, _, _ = verify_report([item()], [], PAGES, DOC, "general", wrong)
    assert items[0]["status"] == BAD and items[0]["category"] == "口径"


def test_unit_error_caught_by_benchmark():
    bench = [{"field": "revenue", "period_type": "H", "period_end": "2026-06-30", "value": 401_243e6,
              "currency": None, "source": "t", "source_field": "营运收入"}]
    items, _, _, _ = verify_report([item(raw_unit="人民幣千元")], [], PAGES, DOC, "general", bench)
    assert items[0]["status"] == BAD and items[0]["category"] == "单位"


def test_period_compared_by_type():
    bench = [{"field": "revenue", "period_type": "Q", "period_end": "2026-06-30", "value": 204_785e6,
              "currency": None, "source": "t", "source_field": "x"},
             {"field": "revenue", "period_type": "H", "period_end": "2026-06-30", "value": 401_243e6,
              "currency": None, "source": "t", "source_field": "x"}]
    q = item(raw_value="204,785", period_type="Q", period_start="2026-04-01")
    items, _, _, _ = verify_report([q, item()], [], PAGES, DOC, "general", bench)
    rev = [i for i in items if i["field"] == "revenue"]
    assert [i["status"] for i in rev] == [OK, OK]
    # the report shows a Q column, so Q net income / EPS (and the required H fields) are expected too
    missing = {(i["field"], i["period_type"]) for i in items if i.get("category") == "漏抽"}
    assert {("net_income_parent", "Q"), ("eps_basic", "Q"), ("operating_cash_flow", "H")} <= missing
    # model labels the 6-month figure as a quarter (dates say 6 months): period type fixed from dates
    mislabeled = item(period_type="Q")
    items, _, _, _ = verify_report([mislabeled], [], PAGES, DOC, "general", bench)
    assert items[0]["period_type"] == "H" and items[0]["status"] == OK


def test_quote_split_across_pdf_lines_is_accepted_but_number_still_exact():
    # label and numbers land on non-adjacent lines in the PDF text layer
    page = "1.归属于母公司股东的净利润(净亏损以“—”号填列)\n2.少数股东损益\n43,284,002 30,485,139"
    ok, r = quote_on_page("1.归属于母公司股东的净利润(净亏损以“—”号填列) 43,284,002 30,485,139", page)
    assert ok and r == 0.99
    assert not number_on_page("43,284,003", page)


def test_derived_components_use_sign_and_magnitude():
    page = "營業收入 178,181\n稅金及附加 (1,508)\n業務及管理費 (52,912)\n其他業務成本 (3,787)"
    pages = [{"page": 1, "text": page}]
    comp = lambda n, v: {"name": n, "sign": 1 if n == "營業收入" else -1, "raw_value": v, "raw_unit": "人民币百万元",
                         "raw_currency": "人民币", "page": 1, "quote": f"{n} {v}"}
    ppop = {"field": "ppop", "derivation": "derived", "period_type": "H", "period_start": "2026-01-01",
            "period_end": "2026-06-30", "page": 1, "quote": "",
            "components": [comp("營業收入", "178,181"), comp("稅金及附加", "(1,508)"),
                           comp("業務及管理費", "(52,912)"), comp("其他業務成本", "(3,787)")]}
    items, _, _, _ = verify_report([ppop], [], pages, dict(DOC, market="a"), "bank", [])
    assert items[0]["value"] == (178_181 - 1_508 - 52_912 - 3_787) * 1e6
    assert items[0]["status"] == FOUND


def test_gross_profit_derived_from_parenthesised_cost():
    page = "Revenue 1,023,670\nCost of revenue (616,136)"
    pages = [{"page": 1, "text": page}]
    base = {"raw_unit": "in millions", "raw_currency": "RMB", "period_type": "FY", "period_start": "2025-04-01",
            "period_end": "2026-03-31", "page": 1}
    rev = dict(base, field="revenue", raw_value="1,023,670", quote="Revenue 1,023,670")
    cost = dict(base, field="cost_of_revenue", raw_value="(616,136)", quote="Cost of revenue (616,136)")
    doc = {"market": "us", "period_end": "2026-03-31", "period": "2026FY"}
    items, _, _, _ = verify_report([rev, cost], [], pages, doc, "general", [])
    gp = next(i for i in items if i["field"] == "gross_profit")
    assert gp["value"] == 407_534e6


def test_quote_ignores_currency_symbols_and_paraphrase_category():
    page = "Mac®\n 10,352 8,046 27,137 24,982"
    ok, _ = quote_on_page("$ 10,352 $ 8,046 $ 27,137 $ 24,982", page)
    assert ok
    # number on the page but the quote is something else entirely -> 引用改写, not 数字编造
    r = check_number({"field": "x", "raw_value": "10,352", "raw_unit": "in millions", "raw_currency": "$",
                      "page": 1, "quote": "Mac net sales grew strongly to 10,352 this quarter"},
                     [{"page": 1, "text": page}], "us")
    assert r["c2"] and not r["c1"] and r["category"] == "引用改写"
