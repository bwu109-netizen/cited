from decimal import Decimal

import pytest

from earnings_agent.units import UnitError, currency_code, parse_raw_value, to_value, unit_multiplier


@pytest.mark.parametrize("raw,expected", [
    ("401,243", Decimal("401243")),
    ("(2,353)", Decimal("-2353")),
    ("−4,672,487", Decimal("-4672487")),
    ("-0.76", Decimal("-0.76")),
    ("90,703,260,964.48", Decimal("90703260964.48")),
    ("１２.６３９", Decimal("12.639")),  # full-width digits
])
def test_parse_raw_value(raw, expected):
    assert parse_raw_value(raw) == expected


@pytest.mark.parametrize("unit,mult,kind", [
    ("元", 1, "amount"),
    ("千元", 10 ** 3, "amount"),
    ("人民币千元", 10 ** 3, "amount"),
    ("RMB'000", 10 ** 3, "amount"),
    ("万元", 10 ** 4, "amount"),
    ("人民币百万元", 10 ** 6, "amount"),
    ("人民幣百萬元", 10 ** 6, "amount"),  # traditional
    ("百万美元", 10 ** 6, "amount"),
    ("$ in millions", 10 ** 6, "amount"),
    ("US$m", 10 ** 6, "amount"),
    ("亿元", 10 ** 8, "amount"),
    ("億元", 10 ** 8, "amount"),
    ("US$ billions", 10 ** 9, "amount"),
    ("元/股", 1, "per_share"),
    ("每股人民幣元", 1, "per_share"),
    ("%", 1, "ratio"),
    ("个百分点", 1, "ratio"),
])
def test_unit_multiplier(unit, mult, kind):
    m, k = unit_multiplier(unit)
    assert m == mult and k == kind


def test_unknown_unit_is_rejected():
    with pytest.raises(UnitError):
        unit_multiplier("furlongs")
    with pytest.raises(UnitError):
        unit_multiplier("")


def test_to_value_and_tolerance():
    value, mult, kind, tol = to_value("401,243", "人民幣百萬元")
    assert value == 401_243_000_000 and tol == 500_000  # half of the last shown digit
    value, _, _, tol = to_value("12.639", "元/股")
    assert value == 12.639 and abs(tol - 0.0005) < 1e-12
    value, _, _, _ = to_value("(237,044)", "$ in millions")
    assert value == -237_044_000_000


@pytest.mark.parametrize("cur,unit,market,code", [
    ("人民幣", "", "hk", "CNY"),
    ("US$", "", "us", "USD"),
    ("", "$ in millions", "us", "USD"),
    ("HK$", "", "hk", "HKD"),
    ("港元", "", "hk", "HKD"),
    ("元", "元", "a", "CNY"),     # bare 元 in an A-share report
    ("元", "元", "hk", None),     # ...but not assumed elsewhere
])
def test_currency_code(cur, unit, market, code):
    assert currency_code(cur, unit, market) == code


def test_sec_per_share_header():
    assert unit_multiplier("per-share amounts") == (1, "per_share")


@pytest.mark.parametrize("unit", ["in millions, except per share data", "(In millions, except per-share amounts)",
                                  "人民币百万元，每股数据除外", "（人民幣百萬元，另有指明者除外）"])
def test_except_clause_does_not_make_amounts_per_share(unit):
    assert unit_multiplier(unit) == (10 ** 6, "amount")
