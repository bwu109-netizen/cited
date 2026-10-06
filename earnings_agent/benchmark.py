"""Standard answers (benchmarks) per market. Each returns a list of
{field, period_type, period_end, value, currency, source, source_field, note}.
currency None = source does not state it reliably (checked later with the EPS probe)."""
from datetime import date

from .http import cached_json
from .periods import cumulative_type, parse_period, type_from_days
from .sources import sec_companyfacts

# ---------------------------------------------------------------- US

US_TAGS = {
    "general": {
        "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
        "gross_profit": ["GrossProfit"],
    },
    "bank": {
        "revenue": ["RevenuesNetOfInterestExpense", "Revenues"],
        "net_interest_income": ["InterestIncomeExpenseNet"],
    },
    "insurance": {"revenue": ["Revenues"]},
    "_all": {
        "net_income_parent": ["NetIncomeLoss"],
        "eps_basic": ["EarningsPerShareBasic"],
        "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
        "net_income_common": ["NetIncomeLossAvailableToCommonStockholdersBasic"],
    },
}


def us_benchmark(doc, template):
    cf = sec_companyfacts(doc["extra"]["cik"])
    ug = cf["facts"].get("us-gaap", {})
    accn, end = doc["extra"]["accession"], doc["period_end"]
    tags = dict(US_TAGS["_all"], **US_TAGS.get(template, {}))
    out = []
    for field, cands in tags.items():
        for tag in cands:
            rows = []
            for unit, facts in ug.get(tag, {}).get("units", {}).items():
                for f in facts:
                    if f.get("accn") == accn and f["end"] == end and "start" in f:
                        days = (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
                        rows.append({"field": field, "period_type": type_from_days(days), "period_end": end,
                                     "value": float(f["val"]), "currency": unit.split("/")[0],
                                     "source": "SEC companyfacts", "source_field": tag, "note": None})
            if rows:
                out.extend(rows)
                break
    # some filers stopped tagging NetIncomeLoss (seen: AIG 2026, NIO 20-F): parent = ProfitLoss − NCI
    if not any(r["field"] == "net_income_parent" for r in out):
        def facts_of(tag):
            res = {}
            for unit, facts in ug.get(tag, {}).get("units", {}).items():
                for f in facts:
                    if f.get("accn") == accn and f["end"] == end and "start" in f:
                        res[(unit, f["start"])] = float(f["val"])
            return res
        total, nci = facts_of("ProfitLoss"), facts_of("NetIncomeLossAttributableToNoncontrollingInterest")
        for (unit, start), v in total.items():
            if (unit, start) in nci:
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                out.append({"field": "net_income_parent", "period_type": type_from_days(days), "period_end": end,
                            "value": v - nci[(unit, start)], "currency": unit.split("/")[0],
                            "source": "SEC companyfacts",
                            "source_field": "ProfitLoss − NetIncomeLossAttributableToNoncontrollingInterest",
                            "note": "NetIncomeLoss 未打标签，按 XBRL 推导"})
    return out


# ---------------------------------------------------------------- A-share (AKShare / Eastmoney)

def _em_a(symbol, kind):
    import akshare as ak

    fn = {"profit": ak.stock_profit_sheet_by_report_em, "cash": ak.stock_cash_flow_sheet_by_report_em,
          "profit_q": ak.stock_profit_sheet_by_quarterly_em}[kind]

    def fetch():
        df = fn(symbol=symbol)
        df["REPORT_DATE"] = df["REPORT_DATE"].astype(str).str[:10]
        return df.where(df.notna(), None).to_dict("records")
    return cached_json(("em-a", symbol, kind), fetch)


def a_benchmark(doc, template):
    code = doc["code"]
    symbol = ("SZ" if code.startswith(("0", "3")) else "BJ" if code.startswith(("4", "8")) else "SH") + code
    end = doc["period_end"]
    ptype = cumulative_type(parse_period(doc["period"])[1])
    prof = next((r for r in _em_a(symbol, "profit") if r["REPORT_DATE"] == end), None)
    cash = next((r for r in _em_a(symbol, "cash") if r["REPORT_DATE"] == end), None)
    out = []

    def add(field, val, src, ptype_=ptype, note=None):
        if val is not None:
            out.append({"field": field, "period_type": ptype_, "period_end": end, "value": float(val),
                        "currency": "CNY", "source": "AKShare 东财 A股报表", "source_field": src, "note": note})
    if prof:
        add("revenue", prof.get("OPERATE_INCOME"), "OPERATE_INCOME")
        add("net_income_parent", prof.get("PARENT_NETPROFIT"), "PARENT_NETPROFIT")
        add("eps_basic", prof.get("BASIC_EPS"), "BASIC_EPS")
        if template == "general" and prof.get("OPERATE_INCOME") is not None and prof.get("OPERATE_COST") is not None:
            add("gross_profit", prof["OPERATE_INCOME"] - prof["OPERATE_COST"], "OPERATE_INCOME-OPERATE_COST")
            add("cost_of_revenue", prof["OPERATE_COST"], "OPERATE_COST")
        if template == "bank":
            add("net_interest_income", prof.get("INTEREST_NI"), "INTEREST_NI")
    if cash:
        add("operating_cash_flow", cash.get("NETCASH_OPERATE"), "NETCASH_OPERATE")
    if ptype in ("H", "YTD", "FY") and parse_period(doc["period"])[1] != "H1":
        # single-quarter figures (Q3 report's 本报告期) from the quarterly sheet
        try:
            q = next((r for r in _em_a(symbol, "profit_q") if r["REPORT_DATE"] == end), None)
        except Exception:
            q = None
        if q:
            add("revenue", q.get("OPERATE_INCOME"), "quarterly OPERATE_INCOME", "Q")
            add("net_income_parent", q.get("PARENT_NETPROFIT"), "quarterly PARENT_NETPROFIT", "Q")
    return out


# ---------------------------------------------------------------- HK (AKShare / Eastmoney HK F10)

HK_ITEMS = {
    "general": {"revenue": "营运收入", "gross_profit": "毛利"},
    "bank": {"net_interest_income": "净利息收入"},  # 经营收入总额 is AFTER expected credit losses: not our revenue
    "insurance": {},
    "_all": {"net_income_parent": "股东应占溢利", "eps_basic": "每股基本盈利", "operating_cash_flow": "经营业务现金净额"},
}


def _em_hk(code, sheet):
    import akshare as ak

    def fetch():
        df = ak.stock_financial_hk_report_em(stock=code, symbol=sheet, indicator="报告期")
        df["REPORT_DATE"] = df["REPORT_DATE"].astype(str).str[:10]
        return df[["REPORT_DATE", "STD_ITEM_NAME", "AMOUNT"]].to_dict("records")
    return cached_json(("em-hk", code, sheet), fetch)


def hk_benchmark(doc, template):
    end = doc["period_end"]
    ptype = cumulative_type(parse_period(doc["period"])[1])
    items = {}
    for sheet in ("利润表", "现金流量表"):
        for r in _em_hk(doc["code"], sheet):
            if r["REPORT_DATE"] == end and r["AMOUNT"] is not None:
                items[r["STD_ITEM_NAME"]] = r["AMOUNT"]
    want = dict(HK_ITEMS["_all"], **HK_ITEMS.get(template, {}))
    out = []
    for field, item in want.items():
        if item in items:
            out.append({"field": field, "period_type": ptype, "period_end": end, "value": float(items[item]),
                        "currency": None, "source": "AKShare 东财港股报表", "source_field": item,
                        "note": "东财不标注可信币种；用 EPS 探针判断是否被换算"})
    return out


def get_benchmark(doc, template):
    fn = {"us": us_benchmark, "a": a_benchmark, "hk": hk_benchmark}[doc["market"]]
    try:
        return fn(doc, template), None
    except Exception as e:  # benchmark is optional: record why it is missing
        return [], f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- previous cumulative (for Q + prior ≈ YTD)

def _months_back(iso, months):
    from .periods import _shift_month_end
    return _shift_month_end(date.fromisoformat(iso), -months).isoformat()


def us_prior(doc, template):
    """Cumulative values ending at the previous quarter, sharing this filing's cumulative start date."""
    cf = sec_companyfacts(doc["extra"]["cik"])
    ug = cf["facts"].get("us-gaap", {})
    accn, end = doc["extra"]["accession"], doc["period_end"]
    tags = dict(US_TAGS["_all"], **US_TAGS.get(template, {}))
    out = []
    for field in ("revenue", "net_income_parent", "gross_profit", "net_interest_income", "operating_cash_flow"):
        for tag in tags.get(field, []):
            facts = [(u, f) for u, fs in ug.get(tag, {}).get("units", {}).items() for f in fs if "start" in f]
            cum = [f for _, f in facts if f.get("accn") == accn and f["end"] == end
                   and type_from_days((date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days) != "Q"]
            if not cum:
                continue
            start = cum[0]["start"]
            prev = [(u, f) for u, f in facts if f["start"] == start and f["end"] < end]
            if prev:
                u, f = max(prev, key=lambda x: x[1]["end"])
                out.append({"field": field, "period_end": f["end"], "value": float(f["val"]),
                            "currency": u.split("/")[0], "source": f"SEC companyfacts {tag}"})
            break
    return out


def a_prior(doc, template):
    code = doc["code"]
    symbol = ("SZ" if code.startswith(("0", "3")) else "BJ" if code.startswith(("4", "8")) else "SH") + code
    if doc["period_end"][5:] == "03-31":
        return []
    prev_end = _months_back(doc["period_end"], 3)
    prof = next((r for r in _em_a(symbol, "profit") if r["REPORT_DATE"] == prev_end), None)
    cash = next((r for r in _em_a(symbol, "cash") if r["REPORT_DATE"] == prev_end), None)
    out = []
    for field, row, key in (("revenue", prof, "OPERATE_INCOME"), ("net_income_parent", prof, "PARENT_NETPROFIT"),
                            ("net_interest_income", prof, "INTEREST_NI"), ("operating_cash_flow", cash, "NETCASH_OPERATE")):
        if row and row.get(key) is not None:
            out.append({"field": field, "period_end": prev_end, "value": float(row[key]), "currency": "CNY",
                        "source": f"AKShare 东财 {key}"})
    return out


def hk_prior(doc, template):
    prev_end = _months_back(doc["period_end"], 3)
    items = {}
    for sheet in ("利润表", "现金流量表"):
        for r in _em_hk(doc["code"], sheet):
            if r["REPORT_DATE"] == prev_end and r["AMOUNT"] is not None:
                items[r["STD_ITEM_NAME"]] = r["AMOUNT"]
    want = dict(HK_ITEMS["_all"], **HK_ITEMS.get(template, {}))
    return [{"field": f, "period_end": prev_end, "value": float(items[i]), "currency": None,
             "source": f"AKShare 东财港股 {i}"} for f, i in want.items() if i in items and f != "eps_basic"]


def get_prior(doc, template):
    fn = {"us": us_prior, "a": a_prior, "hk": hk_prior}[doc["market"]]
    try:
        return fn(doc, template)
    except Exception:  # prior values only feed an optional check
        return []
