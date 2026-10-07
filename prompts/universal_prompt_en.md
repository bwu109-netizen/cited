You will receive a listed company's periodic report (annual, interim or quarterly report, or results announcement, usually a PDF). Copy out the core financial figures below. Give the page and the full source line for every number, so that each one can be checked afterwards.

## 1. Decide the company type first

- Bank: the income statement has a "Net interest income" line and no "Cost of revenue / Cost of sales" line.
- Insurer: the income statement has an "Insurance revenue / Net premiums earned" line and no cost-of-revenue line. An insurance group that also owns a bank is still an insurer.
- Every other company is general.

## 2. Metrics and definitions

General companies: items 1–5. Banks: 1, 2, 3, 5, 6, 7. Insurers: 1, 2, 3, 5, 8, 9.

1. `revenue`
   - China A-shares: the "营业收入" line of the consolidated income statement, not "营业总收入".
   - Hong Kong: the total revenue line of the consolidated income statement, including revenue of the "other" segment. For banks, net operating income before expected credit losses.
   - US: Total net sales / Total revenues / Revenues. For banks, reported Total net revenue, not the managed basis.
2. `net_income_parent`: net income attributable to owners of the parent. Include holders of perpetual bonds and other equity instruments; exclude non-controlling interests. No "excluding non-recurring items" figures and no adjusted figures. US: Net income attributable to [Company].
3. `eps_basic`: basic earnings per ordinary share, not per ADS. Keep the printed decimals.
4. `gross_profit` (general companies only):
   - Copy the gross profit line if there is one.
   - If there is no gross profit line but there is a cost of revenue line, compute revenue minus cost of revenue (do not deduct business taxes and surcharges) and report it as a computed value (section 4).
   - If neither exists, report it as not disclosed.
5. `operating_cash_flow`: net cash from operating activities, consolidated cash flow statement. Where "cash generated from operations" and "tax paid" are shown separately, take the net line after tax.
6. `net_interest_income` (banks): for US banks, not the FTE basis.
7. `ppop` pre-provision profit (banks): copy it if the report states it. Otherwise compute revenue before credit losses minus operating expenses (excluding credit and asset impairment losses), as a computed value.
8. `insurance_revenue` (insurers, IFRS 17 / new CAS 25). Not disclosed under the old standard.
9. `insurance_service_result` (insurers): copy it if stated, otherwise not disclosed.

General rules:
- Always consolidated, statutory figures (GAAP / IFRS / Chinese accounting standards).
- No non-GAAP, adjusted, managed-basis or constant-currency figures.
- No convenience translations into another currency.

## 3. Periods

- Take the current reporting period, never the prior-year comparative.
- Give the cumulative period for every metric:
  - annual report: full year `FY`;
  - interim: six months `H`;
  - nine-month report: `YTD`;
  - first-quarter report: three months `Q`.
- If the report also discloses the latest three months on their own, add a second row with `Q`.
- Operating cash flow is usually cumulative only in interim and quarterly reports; label it as printed, never as `Q`.

## 4. Hard rules

1. Copy numbers exactly as printed: keep thousands separators, decimals, brackets and minus signs. No rounding, no unit or currency conversion, no sign changes of your own.
2. Copy the unit declared for the table or paragraph the number sits in, e.g. "人民币百万元", "RMB'000", "$ in millions", "per share". Copy the currency wording as printed.
3. The page is the PDF page index: count from 1. It is not the page number printed on the page.
4. The quote is the full line that contains the number (table row or sentence), copied verbatim. Do not rewrite, shorten or translate it.
5. If the report does not contain a metric:
   - set `status` to `not_disclosed`, leave the value empty and say why in `note`;
   - never estimate, and never substitute another line: operating profit is not gross profit, and insurance revenue is not total revenue.
6. If you computed a number (e.g. revenue minus cost of revenue):
   - set `derivation` to `derived` and put the result in `raw_value`;
   - list every source number used in `components`, each with its page and full source line.
7. Do not make up a number you are unsure of. Prefer `not_disclosed` with a reason over a number without a source.

## 5. Output format

Output one JSON code block, followed by one Markdown table for people to read. Nothing else.

```json
{
  "company": "Company name",
  "period_end": "2026-06-30",
  "template": "general",
  "items": [
    {
      "field": "revenue",
      "period_type": "Q",
      "status": "reported",
      "raw_value": "28,236",
      "raw_unit": "in millions",
      "raw_currency": "$",
      "page": 5,
      "quote": "Total revenues 28,236 22,496 50,623 41,831",
      "derivation": "reported",
      "components": [],
      "note": ""
    },
    {
      "field": "gross_profit",
      "period_type": "H",
      "status": "reported",
      "raw_value": "9,471",
      "raw_unit": "in millions",
      "raw_currency": "$",
      "page": 5,
      "quote": "",
      "derivation": "derived",
      "components": [
        {"name": "Total revenues", "sign": 1, "raw_value": "50,623", "raw_unit": "in millions", "raw_currency": "$", "page": 5, "quote": "Total revenues 28,236 22,496 50,623 41,831"},
        {"name": "Total cost of revenues", "sign": -1, "raw_value": "41,152", "raw_unit": "in millions", "raw_currency": "$", "page": 5, "quote": "Total cost of revenues 23,485 18,618 41,152 34,800"}
      ],
      "note": "format example for a computed value; compute only when the statement has no gross profit line"
    },
    {
      "field": "operating_cash_flow",
      "period_type": "Q",
      "status": "not_disclosed",
      "raw_value": null,
      "raw_unit": "",
      "raw_currency": "",
      "page": null,
      "quote": "",
      "derivation": "reported",
      "components": [],
      "note": "not in the report: the cash flow statement shows six months only"
    }
  ]
}
```

Allowed values:
- `field`: one of the nine keys above.
- `period_type`: `Q`, `H`, `YTD` or `FY`.
- `status`: `reported` (a number is given) or `not_disclosed`.
- `template`: `general`, `bank` or `insurance`.

Table columns: Metric | Period | Value | Unit | Page | Source line. For metrics that are not disclosed, write "not disclosed" as the value.
