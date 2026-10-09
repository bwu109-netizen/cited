# Metrics spec v0.3

> English translation of the Chinese original, content unchanged. The evaluation froze the Chinese text: it is
> kept verbatim in the git tags `eval-frozen-v1` and `eval-revised-v2` (`git show eval-frozen-v1:docs/metrics_spec.md`).
> Chinese terms are kept where they are the literal line names in filings.

This document defines what the phase 1 extraction pipeline extracts, under which definitions, how each figure is recorded and how it is verified.
Rules must work for any company and must not special-case the development set (9 companies). Wherever a rule "depends on the company", it is written so that it can be derived from the statement structure or from public classification codes.

---

## 1. Industry templates

Every company is assigned a template before extraction. Templates differ in their core fields.

| Template | Rule (in order; stop at the first match) |
|---|---|
| Bank `bank` | ① Industry code: SEC SIC 6021/6022/6029/6035/6036, or CSRC industry J66 (monetary and financial services), or HKEX / Hang Seng industry "Banks"; ② statement structure: the consolidated income statement has a "利息净收入 / 净利息收入 / Net interest income" line and **no** "营业成本 / 销售成本 / Cost of revenue" line |
| Insurance `insurance` | ① Industry code: SIC 6311–6399/6411, or CSRC J68 (insurance), or HKEX / Hang Seng "Insurance"; ② statement structure: the income statement has an "保险服务收入 / Insurance revenue / 已赚保费 / Net premiums earned" line |
| General `general` | All other companies |

- The industry code takes precedence; the statement structure is the fallback and a cross-check. On conflict: if the industry code clearly says bank or insurance, follow the code (v0.3 change: insurance groups such as Ping An consolidate a bank, so their income statement has net interest income and no cost of revenue and would be misread as a bank by structure). If the code says general or is missing, follow the structure. Every conflict is recorded in `template_conflict`.
- Securities firms, trusts and diversified financials are `general` for now; phase 1 has no separate template for them, and the result carries a `template_note`.
- The template is decided by code, never by the model.

### Core fields by template

| Field key | Meaning | general | bank | insurance |
|---|---|---|---|---|
| `revenue` | Revenue | ✅ | ✅ (definition in 2.1) | ✅ |
| `net_income_parent` | Net income attributable to the parent | ✅ | ✅ | ✅ |
| `eps_basic` | Basic earnings per share | ✅ | ✅ | ✅ |
| `gross_profit` | Gross profit | ✅ may be empty | ✗ not extracted | ✗ not extracted |
| `operating_cash_flow` | Net cash from operating activities | ✅ | ✅ | ✅ |
| `net_interest_income` | Net interest income | — | ✅ | — |
| `ppop` | Pre-provision profit | — | ✅ | — |
| `insurance_revenue` | Insurance revenue | — | — | ✅ (may be empty; under the new standards IFRS 17 / CAS 25) |
| `insurance_service_result` | Insurance service result | — | — | ✅ may be empty |

Operating cash flow says little about banks and insurers, but it is still extracted so that it can be compared with the reference answer.

---

## 2. Field definitions (three markets)

General principles:
- Use **consolidated** statements and **statutory** figures (reported / GAAP / IFRS). Do not use non-GAAP, adjusted, managed-basis (managed basis / FTE) or constant-currency figures.
- Do not use figures "excluding non-recurring items" (扣非).
- Do not use convenience-translation amounts in another currency.

### 2.1 Revenue `revenue`

| Market | general | bank | insurance |
|---|---|---|---|
| A-shares | The "**营业收入**" line of the consolidated income statement; **not "营业总收入"** (total operating revenue, which includes interest income of finance subsidiaries and the like; for example the two differ for Kweichow Moutai) | The "营业收入" line of the consolidated income statement. For A-share banks this line is already before credit impairment losses | The "营业收入" line of the consolidated income statement |
| Hong Kong | The total revenue line of the consolidated income statement ("收入 / 營業額 / Revenue"), **including revenue of the "other" segment**. Corresponds to Eastmoney's "营运收入", not Eastmoney's "营业额" | Net operating income **before expected credit losses**, e.g. HSBC's "未扣除预期信贷损失及其他信贷减值准备变动之营业收益净额" (the "revenue" of the report). Not the "net operating income" after ECL | The total revenue line of the income statement; if there is no total line under the new standards it may be empty, with `insurance_revenue` as the main figure |
| US | Income statement Total net sales / Total revenues / Revenues | Total net revenue (net of interest expense), reported basis, not managed basis | Total revenues |

### 2.2 Net income attributable to the parent `net_income_parent`

- Definition: net income attributable to owners of the parent (A-shares "归属于母公司股东的净利润", IFRS "Profit attributable to owners/shareholders of the parent", US GAAP "Net income attributable to [Company]").
- If the report splits owners of the parent further into "ordinary shareholders" and "holders of other equity instruments" (perpetual bonds, preference shares, AT1, e.g. HSBC), the main field takes the **total**, and the optional sub-field `net_income_common` (attributable to ordinary shareholders) is extracted as well.
  - Eastmoney's Hong Kong data gives HSBC on the ordinary-shareholder basis. In verification, if the main field does not match but `net_income_common` does, this is recorded as a "definition" difference.
- US: us-gaap `NetIncomeLoss` (i.e. attributable to the parent), not `NetIncomeLossAvailableToCommonStockholdersBasic`.

### 2.3 Basic earnings per share `eps_basic`

- Definition: basic earnings per **ordinary share**, in the reporting currency.
- Depositary receipt (ADS/ADR) issuers: the main field is per ordinary share. If the report also discloses per-ADS figures, extract the optional sub-field `eps_basic_per_ads` and record the ratio (e.g. 1 ADS = 8 shares).
- The period must match net income. In quarterly reports, single-quarter and year-to-date EPS are two different numbers.
- Hong Kong reports often have 3 decimals (e.g. Tencent 12.639); copy as printed, no rounding.

### 2.4 Gross profit `gross_profit` (general only; may be empty)

| Case | Rule |
|---|---|
| The statement has a gross profit line (common in Hong Kong and US: "毛利 / Gross profit / Gross margin") | Copy it, `derivation = "reported"` |
| No gross profit line, but a cost of revenue line (common in A-shares) | Derived by code: `revenue − cost_of_revenue`, `derivation = "derived"`. The model also extracts `cost_of_revenue` (A-shares "营业成本", excluding taxes and surcharges). Taxes and surcharges are not deducted |
| Neither (e.g. companies presenting expenses by nature) | `null`, with the reason |

### 2.5 Net cash from operating activities `operating_cash_flow`

- Definition: "经营活动产生的现金流量净额 / Net cash from operating activities" in the consolidated cash flow statement.
- Quarterly and interim reports usually give year-to-date figures only. Label the period as printed; do not label it as a single quarter.
- Some Hong Kong companies show "cash generated from operations" and "tax paid" separately; take the **net line after tax**.

### 2.6 Bank fields

| Field | Definition |
|---|---|
| `net_interest_income` | 净利息收入 / 利息净收入 / Net interest income (US banks: net interest income, not the FTE basis) |
| `ppop` pre-provision profit | Prefer the "拨备前利润 / Pre-provision profit" stated in the report (e.g. JPM), `derivation = "reported"`. If not stated, derived by code: `revenue (before ECL) − total operating expenses` (excluding credit impairment and asset impairment losses), `derivation = "derived"`, with the components recorded. A-share formula: `营业收入 − 税金及附加 − 业务及管理费 − 其他业务成本` (revenue − taxes and surcharges − business and administrative expenses − other operating costs). The model only extracts the components and does not compute |

### 2.7 Insurance fields

| Field | Definition |
|---|---|
| `insurance_revenue` | Insurance revenue (IFRS 17 / new CAS 25). Companies under the old standards: null; "已赚保费" (net premiums earned) can be extracted as an industry metric instead |
| `insurance_service_result` | Insurance service result = insurance revenue − insurance service expenses ± net reinsurance result; copy it if stated, otherwise null |

Value of new business, embedded value, combined ratio and similar go into industry metrics (section 5), not core fields.

---

## 3. Periods

Every number must carry a period, made of three parts:

| Field | Values | Notes |
|---|---|---|
| `period_type` | `Q` single quarter / `H` six months / `YTD` year to date (9 months and other non-half-year cumulative periods) / `FY` full year / `PIT` point in time | Six-month figures of interim reports are `H`, not `YTD`. Nine-month figures of Q3 reports are `YTD`; the three-month figures of the third quarter are `Q`. **`PIT` (point in time) is for period-end balances**: total assets, deposits / loans, capital adequacy ratio, NPL ratio, cash balance, etc.; `period_start` is empty and `period_end` is the balance-sheet date |
| `period_start`, `period_end` | ISO dates | Read from the column header, e.g. "截至二零二六年六月三十日止六个月" (six months ended 30 June 2026) → 2026-01-01 ~ 2026-06-30 |
| `fiscal_label` | e.g. `2026H1`, `FY2026Q3`, `FY2026` | Follows the company's fiscal year. For companies whose fiscal year differs from the calendar year (AAPL September, BABA March) the label uses the company's own fiscal year; comparisons use start / end |

- The command-line `--period` is the target reporting period, e.g. `2026H1`, `2026Q3`, `2026FY`. A report shows several periods at once (single quarter + cumulative, current + prior year). The model must label every number's period and **only target-period numbers are results**; comparative figures may be extracted but are labelled `comparative`.
- **When both single-quarter and cumulative figures are disclosed, extract both**: when the filing discloses both (US 10-Q three months / six or nine months, A-share Q3 reports "本报告期" and "年初至报告期末", Hong Kong quarterly announcements three and six months), extract both numbers, labelled `Q` and `YTD` (`H` for six months). Verification matches the reference answer by `period_type` + `period_end`; a single-quarter number is never compared with a cumulative reference.
- Single-quarter numbers are not derived by code by subtracting cumulative figures (phase 1 does no cross-period arithmetic). They are, however, checked for consistency against the prior quarter-end cumulative figure from the structured source (§7.3 item 5).
- **Ask once more for missing periods**: code computes the "expected" (field, period) pairs from the reporting period: the cumulative period of the required fields; the periods present in the reference answer; and, when the income statement itself has a single-quarter column (single-quarter and cumulative revenue on the same page), the single quarter of revenue, net income attributable and EPS. A single-quarter number that appears only in a summary or in text does not trigger this. Pairs missing from the first reply are asked for once more with the same pages, only the missing ones; still missing after that, they are recorded as ❌ missing. Tokens and cost of the follow-up count towards that report.

---

## 4. Units and currencies

### 4.1 Units

- The model **copies the number string as printed** (`raw_value`, e.g. `"(2,353)"`, `"90,703,260,964.48"`, `"12.639"`) and the unit declared for the table or paragraph containing it (`raw_unit`, e.g. `"人民币百万元"`, `"千元"`, `"RMB'000"`, `"$ in millions"`, `"元/股"`). The model does no conversion or sign handling.
- Code is responsible for:
  1. parsing `raw_value`: removing thousands separators, turning brackets or a leading "−/–/—" into a negative number, keeping the original number of decimals (used for the error tolerance);
  2. parsing `raw_unit` → multiplier: 元 / US$ / HK$ = 1, 千元 / '000 / thousands = 1e3, 万元 = 1e4, 百万 / millions / m = 1e6, 亿元 = 1e8, 十亿 / billions / bn = 1e9; the multiplier of per-share amounts is 1;
  3. output `value` = raw value × multiplier, i.e. in units of one reporting-currency unit.
- Wording outside the unit table → parsing fails, status ❌, reason "unit"; no guessing.

### 4.2 Currency

1. **Storage and verification always use the reporting currency of the filing, without conversion.** `currency` is the ISO code of the reporting currency (CNY / USD / HKD …). For example Tencent and Meituan are CNY, HSBC is USD, BABA is CNY (USD convenience translations in the 20-F are ignored). The currency is read from the unit declaration in the filing ("人民币百万元" → CNY) and mapped by code; the model copies the currency wording as printed. ← **only this item is implemented in phase 1**
2. For display and cross-company comparison, figures can be converted into the listing currency: USD for US, HKD for Hong Kong, CNY for A-shares. (web phase)
3. Converted figures must carry `fx_rate`, `fx_source` (e.g. PBOC central parity, HKMA, Federal Reserve H.10), `fx_date` and `fx_basis` (`period_end` rate / `period_avg` average rate). By convention, income statement and cash flow use the period average rate and the balance sheet uses the period-end rate. The original-currency value is always kept, and the display can switch back at any time. (web phase)

- When the reference answer's currency differs from the reporting currency (e.g. Eastmoney converted HSBC into RMB), the verification layer **does not convert the reference back**; it records a "definition" difference with the reason, so that no "verified" status is built on a guessed exchange rate. In that case the reference answer is treated as unusable: a number that passes the filing checks (C1–C3) is recorded as ⚠️ found in the filing only, not ❌ — the reference is wrong, not the extraction.

---

## 5. Industry metrics

- Based on the company's business and the report, the model proposes 3–6 industry metrics, for example:
  - baijiu: share of direct-sales revenue
  - banks: net interest margin, NPL ratio, provision coverage, core tier 1 capital ratio
  - internet: segment revenue, MAU
  - insurance: value of new business, combined ratio
- Each metric has the same format as the core fields (number as printed, unit, currency or "%", period, page, quote), plus `rationale` (why this metric matters for the company, 1–2 sentences).
- For ratios (%, x, bp) `raw_unit` is copied and code does not convert.
- Industry metrics usually have no reference answer; the best status is ⚠️ found in the filing only.

---

## 6. Extraction output JSON (one entry per number)

```json
{
  "field": "revenue",
  "is_core": true,
  "raw_value": "401,243",
  "raw_unit": "人民币百万元",
  "raw_currency": "人民币",
  "period_type": "H",
  "period_start": "2026-01-01",
  "period_end": "2026-06-30",
  "comparative": false,
  "page": 17,
  "quote": "收入 401,243 364,526 10%",
  "derivation": "reported",
  "components": null,
  "rationale": null
}
```

Code adds these fields: `value`, `unit_multiplier`, `currency` (ISO), `status`, `status_reason`, `failure_category`, `benchmark` (the reference value, its source and field name).

Page definition:
- PDF: the physical page index counted from 1, not the page number printed in the footer.
- HTML: the number of the "page" cut out by section.

`quote` is one sentence or one table row of the filing that contains the number.

---

## 7. Verification layer (code only)

Each number is checked against these four items:

| # | Check | Rule |
|---|---|---|
| C1 | Quote on the page | Page text and quote are both normalised: NFKC, traditional → simplified Chinese (OpenCC t2s; models often copy traditional Hong Kong text as simplified), all whitespace removed, full-width / half-width punctuation and all kinds of dashes or minus signs unified. Currency symbols ($, US$, HK$, ¥, €, £) are removed before matching, because SEC tables print $ on some rows only. First an exact substring match; then a quote made of up to 3 verbatim pieces is allowed (PDF tables split the row label and its numbers into different lines); only then a fuzzy match (sliding window, similarity ≥ 0.90). Neighbouring pages ±1 are also searched; a hit on a neighbouring page is recorded as a page offset, C1 still passes, with the extra reason "wrong page" |
| C2 | Number on the page (exact) | `raw_value` must appear **exactly** in the normalised text of that page (the page where C1 matched), not only in the model's quote. Before comparing, thousands separators, brackets and minus signs are removed and only the digit string is kept, which must be a whole number: no digit directly before or after it. C1's fuzzy match only confirms that the quote is roughly on the page; the number itself must match exactly. This prevents a model from changing one digit and still passing with a sentence similarity ≥ 0.90. No exact match on the page but a match on another page → "wrong page"; no match anywhere → "fabricated number" |
| C3 | Unit parses | `raw_unit` maps to a multiplier and `raw_currency` maps to an ISO currency |
| C4 | Matches the reference answer | When a reference exists, compare `value`. Tolerance = half a unit of the last significant digit printed (e.g. 401,243 in millions → ±0.5 million; EPS 2.98 → ±0.005), plus a relative error of 1e-9 |

### Status

| Status | Condition |
|---|---|
| ✅ verified | C1, C2, C3 pass and C4 passes |
| ⚠️ found in the filing only | C1, C2, C3 pass but there is no reference answer (industry metrics, field missing from the reference) |
| ❌ does not match or not found | any item fails, or a consistency check (§7.3) fails |

The status of a derived field (`derivation = "derived"`) is the worst status among its components; the derived value is then compared with the reference answer (C4).

### ❌ reason categories `failure_category`

| Category | Examples |
|---|---|
| Unit | Unit string cannot be parsed; wrong multiplier (thousands taken as units) |
| Definition | Took total operating revenue instead of revenue; the reference is revenue after ECL; the reference currency was converted |
| Period | Took the single quarter instead of the cumulative figure, or the prior year |
| Wrong page | The quote is on another page (beyond ±1) |
| Fabricated number | The number is on no page of the filing (even if the quote passed the fuzzy match) |
| Rewritten quote | The number is on that page, but the quote is not verbatim (rewritten, text added or removed), C1 fails |
| Missing | An expected (field, period) was still not extracted after the follow-up question |
| Definition / derivation | A consistency check fails (§7.3), e.g. wrong sign in a derivation, wrong attribution basis |
| Parsing problem | PDF text extraction lost or displaced characters, so the correct number in the filing cannot be matched |

Code gives an initial category by rule, for example: C1 fails but matches on another page → wrong page; the number is nowhere in the filing → fabricated number; the number is on the page but the quote differs → rewritten quote. A human reviewer may change the category in the result document with a note.

### 7.3 Consistency checks (code only)

Run after C1–C4; any failure turns the number into ❌ with the category "definition / derivation". Each check runs only when all its inputs exist; otherwise it is skipped.

| # | Check | Rule | Flagged on |
|---|---|---|---|
| 1 | Gross profit ≤ revenue; cost of revenue used for a derived gross profit ≥ 0 | Same period, allowing the rounding of both figures | Gross profit |
| 1b | Pre-provision profit ≤ revenue (banks) | As above | Pre-provision profit |
| 2 | Parent total ≥ attributable to ordinary shareholders (only when perpetual bonds etc. exist) | Checked only when the page with the ordinary-shareholder line also lists other equity holders (perpetual bonds, preference shares, AT1 …): it fails if the parent total is smaller than, or equal to (suspected ordinary-shareholder basis only), the ordinary-shareholder figure. Not checked without other equity holders — under US GAAP the ordinary-shareholder figure can legitimately exceed the parent figure (e.g. BABA FY2026 105,904 vs 103,592, mezzanine equity adjustment) | Net income attributable |
| 3 | Derived value = stated value | For derived pre-provision profit, gross profit or parent total: if the filing has a line with the same name (e.g. "拨备前利润", "Pre-provision profit", "毛利"), at least one number on that line, scaled by common units, must be within 0.5% of the derived value | Derived value |
| 4 | EPS × weighted average shares ≈ net income attributable | Fails outside [0.5, 2]; only catches order-of-magnitude errors. The denominator prefers the ordinary-shareholder figure. Share count is extracted by the model (`weighted_avg_shares_basic`); skipped if not extracted | EPS |
| 5 | Single quarter + prior quarter-end cumulative ≈ current cumulative | The prior quarter-end cumulative figure comes from the structured source (US companyfacts with the same fiscal-year start, A-share / Hong Kong Eastmoney prior quarter-end), tolerance 0.2% + rounding. Only additive fields are checked (revenue, net income attributable, gross profit, net interest income, operating cash flow); EPS is not additive and is not checked. Skipped when the structured source is judged to be currency-converted | Both the single-quarter and the cumulative number |

---

## 8. Reference answer (benchmark) sources

| Market | Source | Field mapping |
|---|---|---|
| US | SEC companyfacts (us-gaap, matched by accession and period_end, with Q/H/YTD/FY told apart by duration) | revenue: list of candidate tags (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenuesNetOfInterestExpense` …); `NetIncomeLoss`; `EarningsPerShareBasic`; `GrossProfit`; `NetCashProvidedByUsedInOperatingActivities`; `InterestIncomeExpenseNet`. Only the unit of the reporting currency is used |
| A-shares | AKShare Eastmoney: `OPERATE_INCOME`, `PARENT_NETPROFIT`, `BASIC_EPS`, `NETCASH_OPERATE`, `OPERATE_COST` (for deriving gross profit) | Unit: yuan |
| Hong Kong | AKShare Eastmoney Hong Kong F10: `营运收入`, `股东应占溢利`, `每股基本盈利`, `毛利`, `经营业务现金净额` | Eastmoney's "currency" field is not reliable. EPS is used as a probe: if the ratio of Eastmoney EPS to filing EPS clearly differs from 1, the reference is judged to be converted, and all Hong Kong reference values of that company are downgraded to a "definition" difference and take no part in ✅ |

The reference answer is "one answer", not the truth. When it conflicts with the filing and the filing checks (C1–C3) pass, the result document lists the conflict for a human to judge.

---

## 9. Confirmed decisions (2026-10-06)

1. The main net-income-attributable field is the total for owners of the parent (including holders of other equity instruments); the ordinary-shareholder figure is the sub-field `net_income_common`.
2. Hong Kong: prefer the results announcement; if not found, use the interim or annual report; the result records which file was used.
3. US bank revenue uses reported Total net revenue.
4. A-share gross profit = revenue − cost of revenue, without deducting taxes and surcharges.
