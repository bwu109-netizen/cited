你会收到一份上市公司的定期报告（年报、中报、季报或业绩公告，通常是 PDF）。请从报告里抄出下面这些核心财务数字。每个数都要给出页码和原文整行，以便事后逐条核对。

## 一、先判断公司类型

- 银行：利润表有“利息净收入 / 净利息收入 / Net interest income”行，且没有“营业成本 / 销售成本 / Cost of revenue”行。
- 保险：利润表有“保险服务收入 / Insurance revenue / 已赚保费”行，且没有营业成本行。保险集团即使合并了银行，也按保险。
- 其他公司都按一般企业。

## 二、要抄的指标和口径

一般企业抄 1–5；银行抄 1、2、3、5、6、7；保险抄 1、2、3、5、8、9。

1. `revenue` 营业收入
   - A 股：合并利润表的“营业收入”行，不是“营业总收入”。
   - 港股：合并损益表的收入总额行，包括“其他”分部的收入。银行用扣除预期信贷损失之前的营业收益净额。
   - 美股：利润表的 Total net sales / Total revenues / Revenues。银行用 reported 口径的 Total net revenue，不用 managed basis。
2. `net_income_parent` 归属于母公司所有者的净利润：包括永续债等其他权益工具持有者应占，不包括非控股权益。不要扣非，不要经调整口径。美股取 Net income attributable to [公司]。
3. `eps_basic` 基本每股收益：每普通股，不是每 ADS。照抄小数位数。
4. `gross_profit` 毛利（只限一般企业）：报表有毛利行就照抄。没有毛利行但有营业成本行时，用营业收入减营业成本（不扣税金及附加），按第四节写成计算值。两者都没有就写“原文没有”。
5. `operating_cash_flow` 经营活动产生的现金流量净额：合并现金流量表的净额行。港股如果把“经营产生的现金”和“已付税项”分开列示，取扣税后的净额。
6. `net_interest_income` 净利息收入（银行）：美股银行不用 FTE 口径。
7. `ppop` 拨备前利润（银行）：报告明示就照抄。没有明示时，用扣除信贷损失前的收入减营业支出（不含信用减值和资产减值损失），写成计算值。
8. `insurance_revenue` 保险服务收入（保险，新准则）。旧准则公司写“原文没有”。
9. `insurance_service_result` 保险服务业绩（保险）：报告明示就照抄，否则写“原文没有”。

通用规则：
- 一律取合并报表、法定口径（GAAP / IFRS / 中国会计准则）。
- 不取非公认会计准则、经调整、管理口径、固定汇率口径的数。
- 不取外币便利折算的金额。

## 三、期间

- 取报告本期的数，不要取上年同期。
- 每个指标都要给累计期间：
  - 年报：全年 `FY`；
  - 中报：六个月 `H`；
  - 三季报：九个月 `YTD`；
  - 一季报：三个月 `Q`。
- 报告同时披露单季（最近三个月）的数时，再给一条单季 `Q`。
- 经营现金流在季报、中报里一般只有累计数，照实标注，不要标成单季。

## 四、硬性规则

1. 数字照抄报告原文的写法：千分位、小数位、括号、负号都保留。不要四舍五入，不要换算单位或币种，不要自己改正负号。
2. 单位照抄这个数所在表格或段落声明的单位，例如“人民币百万元”“千元”“RMB'000”“$ in millions”“元/股”。币种照抄原文字样。
3. 页码填 PDF 文件的页序号：从 1 开始数的第几页，不是页面上印的页码。
4. 原文引用逐字照抄包含这个数字的那一整行（表格行或句子），不要改写、不要缩写、不要翻译。
5. 原文没有的指标，`status` 写 `not_disclosed`，数值留空，并在 `note` 里说明原因。不许估算，不许用别的指标代替：营业利润不是毛利，保险收入也不是总收入。
6. 如果一个数是你算出来的（例如营业收入减营业成本）：
   - `derivation` 写 `derived`；
   - `raw_value` 写计算结果；
   - 每个用到的原文数字放进 `components`，各自带页码和原文整行。
7. 不确定的数不要编。宁可写 `not_disclosed` 并说明，也不要给一个找不到出处的数。

## 五、输出格式

先输出一个 JSON 代码块，紧接着输出一张给人看的 Markdown 表格。除此之外不要写别的内容。

```json
{
  "company": "公司名",
  "period_end": "2026-06-30",
  "template": "general",
  "items": [
    {
      "field": "revenue",
      "period_type": "H",
      "status": "reported",
      "raw_value": "401,243",
      "raw_unit": "人民币百万元",
      "raw_currency": "人民币",
      "page": 17,
      "quote": "收入 401,243 364,526 10%",
      "derivation": "reported",
      "components": [],
      "note": ""
    },
    {
      "field": "gross_profit",
      "period_type": "H",
      "status": "reported",
      "raw_value": "64,988,562",
      "raw_unit": "千元",
      "raw_currency": "人民币",
      "page": 67,
      "quote": "",
      "derivation": "derived",
      "components": [
        {"name": "营业收入", "sign": 1, "raw_value": "371,281,245", "raw_unit": "千元", "raw_currency": "人民币", "page": 67, "quote": "营业收入 371,281,245 …"},
        {"name": "营业成本", "sign": -1, "raw_value": "306,292,683", "raw_unit": "千元", "raw_currency": "人民币", "page": 67, "quote": "营业成本 306,292,683 …"}
      ],
      "note": "报表无毛利行，按营业收入减营业成本计算"
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
      "note": "原文没有：现金流量表只披露六个月累计数"
    }
  ]
}
```

字段取值：
- `field`：只能用上面九个英文 key 之一。
- `period_type`：`Q`、`H`、`YTD`、`FY` 之一。
- `status`：`reported`（给出了数）或 `not_disclosed`（原文没有）。
- `template`：`general`、`bank`、`insurance` 之一。

表格列：指标 | 期间 | 数值 | 单位 | 页码 | 原文。原文没有的指标，数值一栏写“原文没有”。
