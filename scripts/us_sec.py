"""US feasibility: download latest periodic report from SEC EDGAR + same-period XBRL companyfacts, cross-check.

Usage: SEC_USER_AGENT="Your Name your@email" .venv/bin/python scripts/us_sec.py
SEC requires a descriptive User-Agent with contact info and <= 10 requests/sec.
"""
import json
import os
from datetime import date

from common import RAW, RateLimitedSession, dump_json, find_in_text, html_to_text, save

UA = os.environ.get("SEC_USER_AGENT", "earnings-agent-feasibility admin@example.com")
S = RateLimitedSession(max_per_sec=8, user_agent=UA)  # stay under SEC's 10 req/s

COMPANIES = [
    {"ticker": "AAPL", "cik": "0000320193", "industry": "消费电子"},
    {"ticker": "JPM", "cik": "0000019617", "industry": "银行"},
    {"ticker": "BABA", "cik": "0001577552", "industry": "互联网/电商 (FPI, 20-F)"},
]
PERIODIC = ("10-Q", "10-K", "20-F")

# Candidate us-gaap tags per target field, in priority order.
TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenuesNetOfInterestExpense"],
    "net_income_parent": ["NetIncomeLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "gross_profit": ["GrossProfit"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
}


def latest_periodic(cik):
    sub = S.get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    r = sub["filings"]["recent"]
    for i, form in enumerate(r["form"]):
        if form in PERIODIC:
            return {k: r[k][i] for k in ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument")}
    raise RuntimeError("no periodic filing in recent list")


def duration_days(f):
    if "start" not in f:
        return 0
    return (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days


def facts_for_filing(cf, accn, report_date):
    """Pick, for each target field, the facts reported in this filing for the period ending report_date."""
    ug = cf["facts"].get("us-gaap", {})
    out = {}
    for field, tags in TAGS.items():
        for tag in tags:
            if tag not in ug:
                continue
            rows = []
            for unit, facts in ug[tag]["units"].items():
                for f in facts:
                    if f.get("accn") == accn and f["end"] == report_date:
                        rows.append({"tag": tag, "unit": unit, "val": f["val"], "start": f.get("start"),
                                     "end": f["end"], "days": duration_days(f), "fp": f.get("fp"), "frame": f.get("frame")})
            if rows:
                out[field] = sorted(rows, key=lambda x: (x["unit"], x["days"]))
                break
    return out


def main():
    results = []
    for c in COMPANIES:
        rec = {"ticker": c["ticker"], "industry": c["industry"]}
        try:
            filing = latest_periodic(c["cik"])
            rec["filing"] = filing
            accn_nodash = filing["accessionNumber"].replace("-", "")
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(c['cik'])}/{accn_nodash}/"
                   f"{filing['primaryDocument']}")
            resp = S.get(url)
            resp.raise_for_status()
            path = save(RAW / "us" / f"{c['ticker']}_{filing['form']}_{filing['reportDate']}.htm", resp.content)
            rec["doc"] = {"url": url, "path": str(path), "bytes": len(resp.content), "format": "HTML (inline XBRL)"}
            text = html_to_text(resp.content.decode("utf-8", "ignore"))

            cf = S.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c['cik']}.json").json()
            facts = facts_for_filing(cf, filing["accessionNumber"], filing["reportDate"])
            # derive gross profit when not tagged (e.g. BABA): Revenues - CostOfRevenue
            if "gross_profit" not in facts:
                derivable = "CostOfRevenue" in cf["facts"]["us-gaap"]
                rec["gross_profit_note"] = "GrossProfit 未打标签" + ("，可由 Revenues - CostOfRevenue 推导" if derivable else "")
            rec["facts"] = facts
            # cross-check: does each structured value appear in the report text (any common scaling)?
            checks = {}
            for field, rows in facts.items():
                for r in rows:
                    hits = find_in_text(r["val"], text, scales=(1,) if "shares" in r["unit"] else (1, 1e3, 1e6))
                    checks[f"{field}|{r['unit']}|{r['days']}d"] = {"val": r["val"], "found_as": hits[:3]}
            rec["text_check"] = checks
            rec["ok"] = True
        except Exception as e:  # record, don't hide
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False, indent=1, default=str)[:4000])
    dump_json(results, RAW / "us" / "results.json")


if __name__ == "__main__":
    main()
