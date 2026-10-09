# Data source feasibility check (phase 0)

Checked on 2026-10-06. The scripts are in `scripts/`; raw files and result JSON are in `data/raw/{us,a,hk}/` (gitignored). Chinese terms are kept where they are field or line names in the sources.

```bash
.venv/bin/python scripts/us_sec.py          # SEC_USER_AGENT="name email" overrides the default UA
.venv/bin/python scripts/a_share_cninfo.py
.venv/bin/python scripts/hk_hkexnews.py
```

## 1. Overview: market × source × feasibility × pitfalls

| Market | Use | Source / endpoint | Feasible | Main pitfalls |
|---|---|---|---|---|
| US | Filing | SEC EDGAR `data.sec.gov/submissions/CIK##########.json` → `www.sec.gov/Archives/edgar/data/{cik}/{accn}/{primaryDocument}` | ✅ 3/3 | Requires a User-Agent with contact details; rate limit 10 requests/s (the scripts stay at 8/s). The filing is inline-XBRL HTML and large (JPM 10-Q 11.5 MB). JPM's `recent` list has many 424B2 filings, so filter by form. Foreign private issuers (BABA) file quarterly results as 6-K press releases, not 10-Q |
| US | Structured | SEC XBRL `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | ✅ 10-Q/10-K/20-F; ⚠️ not FPI quarterly results | The same field uses different tags at different companies (revenue: AAPL `RevenueFromContractWithCustomerExcludingAssessedTax`, JPM `RevenuesNetOfInterestExpense`, BABA `Revenues`). In a 10-Q the same tag has both a single-quarter and a year-to-date fact, told apart by start/end; the cash flow statement is year-to-date only. The bank (JPM) has no GrossProfit; BABA has no GrossProfit tag either (derive Revenues − CostOfRevenue). **BABA's 6-K quarterly results have had no XBRL since 2021**, so the latest quarter is unavailable. BABA has both CNY and USD convenience-translation values; EPS is per ordinary share (1 ADS = 8 shares) |
| A-shares | Filing | cninfo: `/new/information/topSearch/query` for the orgId → `/new/hisAnnouncement/query` (filtered by the periodic-report category) → `static.cninfo.com.cn/{adjunctUrl}` | ✅ 3/3 | Undocumented internal endpoints; parameters may change. The same result set contains "summary", "English version" and "correction" documents, so filter by title. Shenzhen titles do not carry the company name (CATL's is just "2026年半年度报告"). `column` must be sse/szse by exchange |
| A-shares | Structured | AKShare `stock_profit_sheet_by_report_em` / `stock_cash_flow_sheet_by_report_em` (data from Eastmoney F10) | ✅ 3/3 | Slow: every call pages through the full history, about 20–25 s per statement. Units are always yuan, but the filings differ (Moutai in yuan, CATL in **thousand yuan**, China Merchants Bank in **million yuan**). Moutai has `TOTAL_OPERATE_INCOME` (营业总收入, total operating revenue, including interest income of its finance company) ≠ `OPERATE_INCOME` (营业收入, revenue); analysts often use total operating revenue, so one definition must be chosen. A-share income statements **have no gross profit line**: derive revenue − cost of revenue; banks have no cost of revenue, so gross profit does not apply. AKShare is a third-party wrapper and breaks when Eastmoney changes its endpoints |
| Hong Kong | Filing | HKEXnews: `/search/prefix.do` for the stockId → `/search/titleSearchServlet.do` (t1code=40000 financial statements; t1code=10000 & t2Gcode=3 results announcements) → PDF | ✅ 3/3 | Also undocumented endpoints. **Results announcements come 2–4 weeks before the interim / annual report** (Meituan announcement 08-28 vs interim report 09-29), so results reviews should use the announcement. Category text is HTML-escaped and must be unescaped. PDFs are in traditional Chinese. **Text extracted from HSBC's PDF contains Kangxi radicals (⺟, ⽇); without NFKC normalisation "母公司" (parent company) cannot be found** |
| Hong Kong | Structured | AKShare `stock_financial_hk_report_em` (Eastmoney Hong Kong F10, long table `STD_ITEM_NAME`/`AMOUNT`) | ⚠️ works for non-banks; big pitfalls for banks | Line items follow Eastmoney's standardised definitions, not the company's: Tencent `营业额` 396,431 ≠ the report's "收入" (revenue) 401,243 (Eastmoney moves the "other" segment 4,812 into `其他营业收入`; use `营运收入`). **HSBC's figures were converted into RMB by Eastmoney at about 6.8109**, yet the `CURRENCY` field says HKD (Tencent also says HKD, but is actually RMB), so that field cannot be used. HSBC's `经营收入总额` is the "net operating income" after expected credit losses, 35,389, not the headline "revenue" 37,742. No currency or unit metadata |
| Hong Kong (alternative) | Structured | SEC companyfacts (`ifrs-full`), only for companies that also file with the SEC (e.g. HSBC CIK 1089113) | ⚠️ annual only | HSBC has only 20-F annual data, no interim data. `ProfitLossAttributableToOwnersOfParent` stops at 2022 (reason not investigated) |

## 2. Per-company notes

"Filing check" means the structured value, scaled by common units, was searched for automatically in the filing text. Everything listed below matched; mismatches are stated with the reason. In addition, the context of 1–2 numbers per company was checked by hand (e.g. AAPL "Total net sales 109,417", HSBC "母公司普通股股东" (ordinary shareholders of the parent) 14,626).

### US (SEC; HTML filings are all text, no scans)

| Company | Industry | Filing | Period | Structured fields (unit) | Filing check |
|---|---|---|---|---|---|
| AAPL | Consumer electronics | 10-Q `aapl-20260627.htm`, 1.0 MB HTML | FY26 Q3 (ended 2026-06-27), single quarter + 9 months | Revenue, NetIncomeLoss, basic EPS, GrossProfit, operating cash flow (USD; EPS in USD/share) | All 5 fields matched: revenue 109,417, net income 29,789, EPS 2.03, gross profit 54,770, operating cash flow (9 months) 116,996 (USD millions) |
| JPM | Bank | 10-Q `jpm-20260630.htm`, 11.5 MB HTML | 2026 Q2, single quarter + six months | `RevenuesNetOfInterestExpense`, NetIncomeLoss, EPS, operating cash flow; **no gross profit** | 4 fields matched: Total net revenue 57,347, net income 21,155, EPS 7.71, operating cash flow (six months) −237,044. Note that 57,347 carries footnote (e) and the managed-basis figure sits next to it; do not take the wrong one |
| BABA | Internet | 20-F `baba-20260331.htm`, 11.7 MB HTML | FY2026 (ended 2026-03-31) | Revenues, NetIncomeLoss, EPS, operating cash flow (one set each in CNY and USD); **no GrossProfit tag** | All matched: revenue 1,023,670, net income 103,592, EPS 5.70 (per ordinary share), operating cash flow 76,213 (RMB millions). Derived gross profit: 1,023,670 − 616,136 = 407,534. **The 6-K for the latest quarter (June 2026) has no XBRL**; AKShare Hong Kong 09988 has the 2026-06-30 figures, but they were not checked against a filing this time |

### A-shares (cninfo PDFs are all text: pages 2–5 have 400–1,200 characters each; page 1 is the cover with very little text)

| Company | Industry | Filing | Period | Structured fields (AKShare/Eastmoney, unit: yuan) | Filing check |
|---|---|---|---|---|---|
| Kweichow Moutai 600519 | Baijiu | 2026 interim report, 110 pages, 0.8 MB, text | 2026H1 | Total operating revenue, revenue, cost of revenue, net income attributable, basic EPS, operating cash flow; 203 columns in the income statement | All matched exactly in yuan: revenue 90,703,260,964.48, total operating revenue 92,278,072,083.21, net income attributable 44,516,880,421.86, EPS 35.57, operating cash flow 70,690,750,119.06. Gross profit is derived; the filing has no such line |
| CATL 300750 | Batteries | 2026 interim report, 182 pages, 1.6 MB, text | 2026H1 | As above | All matched; the filing's unit is **thousand yuan**: revenue 276,916,580, cost of revenue 210,654,890, net income attributable 43,284,002, EPS 9.51, operating cash flow 60,216,851 |
| China Merchants Bank 600036 | Bank | 2026 interim report, 246 pages, 2.6 MB, text | 2026H1 | Revenue, net income attributable, EPS, operating cash flow; **total operating revenue and cost of revenue are empty; gross profit does not apply** | All matched; the filing's unit is **million yuan**: revenue 178,181, net income attributable 76,445, EPS 2.98, operating cash flow 304,611 |

### Hong Kong (HKEXnews PDFs are all text; the cover page has 0 characters)

| Company | Industry | Filing | Period | Structured fields (AKShare/Eastmoney) | Filing check |
|---|---|---|---|---|---|
| Tencent 00700 | Internet | Interim results announcement (08-12, 50 pages) and 2026 interim report (08-25, 122 pages, 5.5 MB) | 2026H1 | 营业额, 营运收入, 毛利, 股东应占溢利, 每股基本盈利, 经营业务现金净额 (RMB; currency field wrongly says HKD) | All matched after switching to `营运收入` (RMB millions): revenue 401,243, gross profit 229,698, net income attributable 114,115, EPS 12.639, operating cash flow 154,061. `营业额` 396,431 is not in the filing |
| Meituan 03690 | Local services | Interim results announcement (08-28, 41 pages) and 2026 interim report (09-29, 129 pages, 4.4 MB) | 2026H1 | As above | All matched; the filing's unit is **RMB thousands**: revenue 195,681,950, gross profit 61,064,869, net income attributable −4,672,487, EPS −0.76, operating cash flow 2,719,085 |
| HSBC 00005 | Bank | 2026 interim results announcement (08-04, 26 pages) and 2026 interim report (08-21, 123 pages, 7.2 MB) | 2026H1 | 经营收入总额, 股东应占溢利, 每股基本盈利, 经营业务现金净额; **no gross profit** | **Automatic check 0/4.** Manual check: Eastmoney's value = filing USD × 6.8109: net income attributable 99,616.2 / 6.8109 = 14,626 ✓, EPS 5.789 / 6.8109 = 0.85 ✓, operating cash flow 556,872.8 / 6.8109 = 81,762 ✓; 经营收入总额 → 35,389 = "net operating income" (after ECL), not "revenue" 37,742. Conclusion: the numbers themselves reconcile, but the currency was converted and the definition differs |

## 3. Conclusions and recommendation

1. **Getting filings: feasible in all three markets; all are text PDFs or HTML, none of the 9 companies has a scanned filing.** The US uses EDGAR's official API (stable, documented). A-shares use cninfo and Hong Kong uses HKEXnews, both internal JSON endpoints of the websites: usable but undocumented, so endpoint changes need monitoring and retries. Hong Kong results reviews should fetch the **results announcement** rather than wait for the interim / annual report.
2. **Structured reference answers:**
   - US: SEC companyfacts as the reference (10-K/10-Q/20-F). Needs a "field → candidate tags" mapping and Q vs year-to-date told apart by duration. Quarterly figures of FPIs (like BABA) have no XBRL; they can only be parsed from the 6-K press release, or taken from Eastmoney data for the Hong Kong secondary listing.
   - A-shares: the AKShare Eastmoney endpoints work and match to the cent in yuan. They need caching (slow) and a single revenue definition (total operating revenue or revenue).
   - Hong Kong: the AKShare Eastmoney endpoint can be a **reference** only, not the answer. Line items are standardised, the currency may be converted (HSBC) and the currency field is unreliable. Recommendation: ① for non-banks prefer `营运收入`; ② check each company's reporting currency and use the EPS ratio to detect conversion; ③ the parsed filing value is final, Eastmoney is only a cross-check.
3. **Which fields apply by industry:** gross profit does not apply to banks (JPM, China Merchants Bank, HSBC). A-shares and BABA need revenue − cost of revenue. The schema should make gross profit nullable and use industry templates (banks: net interest income, pre-provision profit, etc.).
4. **Units and currencies must be handled per company:** units differ even within a market (yuan / thousand yuan / million yuan; RMB millions / RMB thousands), so extraction must read the unit declared in the table header. Hong Kong PDFs need NFKC normalisation before extraction.

## 4. Not done / not verified

- BABA's latest quarter (June 2026): no XBRL on the SEC. AKShare 09988 has the data (revenue 268,953, net income attributable 10,614, RMB millions), but the matching 6-K was not downloaded and checked this time.
- HSBC: no unconverted Hong Kong structured data source was found. The SEC has only 20-F annual data, no interim data.
- The official cninfo data service (webapi.cninfo.com.cn, registration token required) and HKEX's paid data products were not tested.
- No structured extraction of filing tables was done, only the check "does the value appear in the filing text". That step is left to the next phase.
