"""Plausibility checks, incl. regression tests with the two wrong values phase 1 only caught by hand."""
from earnings_agent.sanity import apply_sanity
from earnings_agent.verify import BAD, FOUND, verify_report

DOC_HK = {"market": "hk", "period_end": "2026-06-30", "period": "2026H1"}


def it(field, value, ptype="H", **kw):
    d = {"field": field, "period_type": ptype, "value": value, "tolerance": 0.5e6, "status": FOUND,
         "reasons": [], "category": None}
    d.update(kw)
    return d


# ---- regression: HSBC net income (phase 1, rounds 3-4) -----------------------------------------
HSBC_PAGE = {"page": 10, "text": "除稅後利潤 15,321 12,441\n應佔:\n– 母公司普通股股東 14,626 11,510\n"
                                 "– 其他權益持有人 633 547\n– 非控股股東權益 62 384"}


def test_regression_hsbc_ordinary_shareholders_taken_as_parent_total():
    wrong = [it("net_income_parent", 14_626e6, page_used=10), it("net_income_common", 14_626e6, page_used=10)]
    apply_sanity(wrong, [HSBC_PAGE], DOC_HK, "bank", [])
    assert wrong[0]["status"] == BAD and wrong[0]["category"] == "口径/推导"


def test_hsbc_fixed_value_passes():
    right = [it("net_income_parent", 15_259e6, page_used=10), it("net_income_common", 14_626e6, page_used=10)]
    apply_sanity(right, [HSBC_PAGE], DOC_HK, "bank", [])
    assert right[0]["status"] == FOUND


def test_parent_below_common_flagged_only_when_other_equity_holders_exist():
    page = {"page": 1, "text": "Attributable to: ordinary shareholders 120\nother equity holders 5"}
    items = [it("net_income_parent", 100e6, page_used=1), it("net_income_common", 120e6, page_used=1)]
    apply_sanity(items, [page], DOC_HK, "general", [])
    assert items[0]["status"] == BAD
    # US GAAP without perpetuals: ordinary > parent can be legitimate (BABA FY2026: 105,904 vs 103,592)
    page = {"page": 1, "text": "Net income attributable to ordinary shareholders 105,904"}
    items = [it("net_income_parent", 103_592e6, page_used=1), it("net_income_common", 105_904e6, page_used=1)]
    apply_sanity(items, [page], DOC_HK, "general", [])
    assert items[0]["status"] == FOUND


# ---- regression: derived values with the sign bug (CMB ppop, BABA gross profit) -------------------
def test_regression_cmb_ppop_double_counted_costs():
    # pre-fix: 178,181 + 1,508 + 52,912 + 3,787 = 236,388 (should be 119,974)
    items = [it("revenue", 178_181e6), it("ppop", 236_388e6, derivation="derived")]
    apply_sanity(items, [], {"market": "a", "period_end": "2026-06-30", "period": "2026H1"}, "bank", [])
    assert items[1]["status"] == BAD and items[1]["category"] == "口径/推导"


def test_regression_baba_gross_profit_added_cost():
    # pre-fix: 1,023,670 − (−616,136) = 1,639,806 (should be 407,534)
    items = [it("revenue", 1_023_670e6, "FY"),
             it("gross_profit", 1_639_806e6, "FY", derivation="derived", cost_used=-616_136e6)]
    apply_sanity(items, [], {"market": "us", "period_end": "2026-03-31", "period": "2026FY"}, "general", [])
    assert items[1]["status"] == BAD
    assert len(items[1]["sanity"]) == 2  # gross > revenue AND negative cost used


def test_regression_end_to_end_through_verify_with_prefix_sign_logic():
    """Feed the raw components exactly as the model gave them; the derived value must come out right and pass."""
    page = {"page": 1, "text": "Revenue 1,023,670\nCost of revenue (616,136)"}
    base = {"raw_unit": "in millions", "raw_currency": "RMB", "period_type": "FY", "period_start": "2025-04-01",
            "period_end": "2026-03-31", "page": 1}
    raw = [dict(base, field="revenue", raw_value="1,023,670", quote="Revenue 1,023,670"),
           dict(base, field="cost_of_revenue", raw_value="(616,136)", quote="Cost of revenue (616,136)")]
    items, _, _, _ = verify_report(raw, [], [page], {"market": "us", "period_end": "2026-03-31", "period": "2026FY"},
                                   "general", [])
    gp = next(i for i in items if i["field"] == "gross_profit")
    assert gp["value"] == 407_534e6 and gp["status"] != BAD


# ---- derived vs disclosed ------------------------------------------------------------------------
def test_derived_value_must_match_disclosed_total():
    pages = [{"page": 18, "text": "Pre-provision profit 30,031 675 30,706"}]
    ok = [it("revenue", 57_347e6, "Q"), it("ppop", 30_031e6, "Q", derivation="derived")]
    apply_sanity(ok, pages, DOC_HK, "bank", [])
    assert ok[1]["status"] == FOUND
    bad = [it("revenue", 57_347e6, "Q"), it("ppop", 27_000e6, "Q", derivation="derived")]
    apply_sanity(bad, pages, DOC_HK, "bank", [])
    assert bad[1]["status"] == BAD


# ---- EPS x shares --------------------------------------------------------------------------------
def test_eps_times_shares_order_of_magnitude():
    good = [it("eps_basic", 2.03, "Q"), it("weighted_avg_shares_basic", 14_656_110e3, "Q"),
            it("net_income_parent", 29_789e6, "Q")]
    apply_sanity(good, [], DOC_HK, "general", [])
    assert good[0]["status"] == FOUND
    # shares unit misread (thousands taken as units) -> off by 1000x
    bad = [it("eps_basic", 2.03, "Q"), it("weighted_avg_shares_basic", 14_656_110, "Q"),
           it("net_income_parent", 29_789e6, "Q")]
    apply_sanity(bad, [], DOC_HK, "general", [])
    assert bad[0]["status"] == BAD


# ---- quarter + previous cumulative ≈ YTD ---------------------------------------------------------
def test_quarter_plus_prior_equals_ytd():
    prior = [{"field": "revenue", "period_end": "2026-03-28", "value": 254_940e6}]
    good = [it("revenue", 109_417e6, "Q"), it("revenue", 364_357e6, "YTD")]
    apply_sanity(good, [], DOC_HK, "general", prior)
    assert all(i["status"] == FOUND for i in good)
    # quarter column mixed up with the prior-year quarter
    bad = [it("revenue", 94_036e6, "Q"), it("revenue", 364_357e6, "YTD")]
    apply_sanity(bad, [], DOC_HK, "general", prior)
    assert all(i["status"] == BAD for i in bad)
