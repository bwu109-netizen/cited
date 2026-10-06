from earnings_agent.textnorm import for_match, for_numbers, nfkc


def test_nfkc_fixes_kangxi_radicals_and_fullwidth():
    # HSBC's PDF emits Kangxi radicals instead of normal CJK characters
    assert nfkc("⺟公司普通股股東 2026年6⽉30⽇") == "母公司普通股股東 2026年6月30日"
    assert nfkc("（１２，３４５）") == "(12,345)"


def test_for_match_strips_space_unifies_dash_and_script():
    assert for_match("經營活動 所得 現金流量淨額 –5") == for_match("经营活动所得现金流量净额 -5")
    assert for_match("Total  Net\nSales") == "totalnetsales"


def test_for_numbers_drops_thousands_separators_but_keeps_cells_apart():
    t = for_numbers("收入 401,243 364,526 10%")
    assert "401243 364526" in t
    assert for_numbers("1,234,567.89") == "1234567.89"
