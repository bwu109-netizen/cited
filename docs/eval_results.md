# 第 2 阶段评估结果

> 由 `eval/results_report.py` 生成。各节顺序：冻结版主结果 → 修订记录 → 留出集 → 局限。

## 1. 冻结版主结果（DeepSeek，60 份）

> **暂定**：港股核对表尚未导回，目前只评了有自动标准答案的条目（美股和 A 股）。待人工核对的条目有 144 条，争议行有 1 条（NIO）。港股核对完成后，冻结版评分会在冻结工作树里重跑，本节随之更新。Fable 9 份尚未运行（§1.5）。

指标定义见 eval_design §6 和 §10.1：

- 静默错误：给了数但错了，并且没被标 ❌；
- 复核工作量：❌ 条目 / 全部条目；
- 标记召回率：被 ❌ 的错误 / 全部错误。

直接问没有标记机制。“去 C4”是指不用标准答案比对的核验，因为美股和 A 股的 C4 与标准答案同源，存在循环。

### 1.1 主表

| 档 | 条目 | 严格正确（95% CI） | 大致正确 | 编造率 | 静默错误率 | 复核工作量 | 标记召回率（含 C4 / 去 C4） | ❌ 中误报占比 | 每份成本（均值 / 中位 / 最大） |
|---|---|---|---|---|---|---|---|---|---|
| 简单直接问 | 246 | 228（92.7%；88.2%–96.8%） | 228（92.7%） | 0/229（0.0%） | 1（0.4%） | 0（0.0%） | 0（无标记机制） | — | $0.0011 / $0.0009 / $0.0024 |
| 专业直接问 | 246 | 242（98.4%；96.0%–100.0%） | 242（98.4%） | 0/242（0.0%） | 0（0.0%） | 0（0.0%） | 0（无标记机制） | — | $0.0140 / $0.0131 / $0.0419 |
| 流水线 | 246 | 229（93.1%；89.3%–96.7%） | 229（93.1%） | 0/238（0.0%） | 0（0.0%） | 38（15.4%） | 100.0% / 94.1% | 55.3% | $0.0048 / $0.0044 / $0.0082 |

### 1.2 分市场（严格正确）

| 市场 | 简单直接问 | 专业直接问 | 流水线 |
|---|---|---|---|
| 美股 | 134/145（92.4%） | 141/145（97.2%） | 130/145（89.7%） |
| A 股 | 94/101（93.1%） | 101/101（100.0%） | 99/101（98.0%） |
| 港股 | 待核对 | 待核对 | 待核对 |

### 1.3 流水线 ❌ 误报分析（只分析，不改规则）

流水线：误报 21 条。

| 触发的检查 | 误报条目中触发次数 | 其中为唯一触发 |
|---|---|---|
| C3 单位/币种 | 17 | 17 |
| S5 单季+上季累计≈累计 | 4 | 4 |

<details><summary>逐条</summary>

- us:AMZN net_income_parent H：S5 单季+上季累计≈累计（合理性检查：单季 62,647,000,000 + 截至 2025-09-30 累计 21,187,000,000 ≠ H 92,902,000,000（差 -9,068,000,000））
- us:AMZN net_income_parent Q：S5 单季+上季累计≈累计（合理性检查：单季 62,647,000,000 + 截至 2025-09-30 累计 21,187,000,000 ≠ H 92,902,000,000（差 -9,068,000,000））
- us:AMZN operating_cash_flow H：S5 单季+上季累计≈累计（合理性检查：单季 45,387,000,000 + 截至 2025-09-30 累计 35,525,000,000 ≠ H 71,419,000,000（差 9,493,000,000））
- us:AMZN operating_cash_flow Q：S5 单季+上季累计≈累计（合理性检查：单季 45,387,000,000 + 截至 2025-09-30 累计 35,525,000,000 ≠ H 71,419,000,000（差 9,493,000,000））
- us:CVX net_income_parent H：C3 单位/币种（币种无法识别：'dollars'/'Millions of dollars'）
- us:CVX net_income_parent Q：C3 单位/币种（币种无法识别：'dollars'/'Millions of dollars'）
- us:CVX eps_basic H：C3 单位/币种（币种无法识别：'dollars'/'per-share amounts'）
- us:CVX eps_basic Q：C3 单位/币种（币种无法识别：'dollars'/'per-share amounts'）
- us:CVX operating_cash_flow H：C3 单位/币种（币种无法识别：'dollars'/'Millions of dollars'）
- us:BAC revenue H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC revenue Q：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_income_parent H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_income_parent Q：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC operating_cash_flow H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_interest_income H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_interest_income Q：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:AIG revenue H：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG revenue Q：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG net_income_parent H：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG net_income_parent Q：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG operating_cash_flow H：C3 单位/币种（币种无法识别：'dollars'/'in millions'）

</details>

全部 ❌ 的来源：

流水线（eval1，全部 ❌ 87 条，含尚无标准答案的）：

| 触发的检查 | 次数 |
|---|---|
| C3 单位/币种 | 55 |
| C4 标准答案 | 13 |
| 漏抽 | 11 |
| S5 单季+上季累计≈累计 | 6 |
| S4 EPS×股数≈净利润 | 4 |
| C1 引用在页上 | 2 |
| C2 数字在页上 | 2 |
| C3 单位/币种（组成项） | 2 |
| S3 推导值=明示值 | 2 |

### 1.4 稳定性（15 份 × 每份共 3 次）

| 档 | 报告 | 条目 | 三次数值全一致 | 严格正确（eval1 / eval2 / eval3） | 对错翻转条目 | 状态翻转 / 漏答或漏抽（三次） |
|---|---|---|---|---|---|---|
| 简单直接问 | 10 | 58 | 100.0% | 52 / 52 / 52 | 0 | — / 6、6、6 |
| 专业直接问 | 10 | 58 | 96.6% | 58 / 58 / 56 | 2 | — / 0、0、0 |
| 流水线 | 10 | 58 | 96.6% | 56 / 56 / 58 | 2 | 2 / 0、0、0 |

只比较三次都有标准答案的条目（目前是美股和 A 股的自动答案；港股核对后补上）。稳定性只在冻结版规则下测。

### 1.5 Fable 5.1（9 份小样本，补充参考）

尚未运行。按决定，等港股核对完成后用冻结版规则分两批提交（先直接问，结算后再提交流水线），每批提交前精确核算剩余预算。

### 1.6 全部错误条目（冻结版）

| 报告 | 档 | 字段 | 期间 | 标准答案 | 预测 | 状态/分类 | 说明 |
|---|---|---|---|---|---|---|---|
| us:AMZN | 简单直接问 | net_income_parent | FY | 1.353e+11 | — | — |  |
| us:AMZN | 简单直接问 | operating_cash_flow | FY | 1.614e+11 | — | — |  |
| us:AMZN | 专业直接问 | net_income_parent | FY | 1.353e+11 | — | — |  |
| us:AMZN | 专业直接问 | operating_cash_flow | FY | 1.614e+11 | — | — |  |
| us:AMZN | 流水线 | net_income_parent | FY | 1.353e+11 | — | ❌ 漏抽 | ❌ |
| us:AMZN | 流水线 | operating_cash_flow | FY | 1.614e+11 | — | ❌ 漏抽 | ❌ |
| us:CVX | 专业直接问 | revenue | H | 1.148e+11 | — | ambiguous | ambiguous |
| us:CVX | 专业直接问 | revenue | Q | 6.72e+10 | — | ambiguous | ambiguous |
| us:CVX | 流水线 | revenue | H | 1.148e+11 | 1.187e+11 | ❌ 口径/推导 |  |
| us:CVX | 流水线 | revenue | Q | 6.72e+10 | 7.006e+10 | ❌ 口径/推导 |  |
| us:INTC | 流水线 | eps_basic | H | -2.89 | — | ❌ 单位 | ❌ |
| us:INTC | 流水线 | eps_basic | Q | -2.16 | — | ❌ 单位 | ❌ |
| us:BAC | 简单直接问 | net_income_parent | H | 1.766e+10 | — | ambiguous | ambiguous |
| us:BAC | 简单直接问 | net_income_parent | Q | 9.074e+09 | — | ambiguous | ambiguous |
| us:BAC | 简单直接问 | net_interest_income | H | 3.174e+10 | — | not_answered | not_answered |
| us:BAC | 简单直接问 | net_interest_income | Q | 1.6e+10 | — | not_answered | not_answered |
| us:BAC | 流水线 | eps_basic | H | 2.35 | — | ❌ 单位 | ❌ |
| us:BAC | 流水线 | eps_basic | Q | 1.22 | — | ❌ 单位 | ❌ |
| us:WFC | 简单直接问 | net_interest_income | H | 2.441e+10 | — | not_answered | not_answered |
| us:WFC | 简单直接问 | net_interest_income | Q | 1.232e+10 | — | — |  |
| us:WFC | 流水线 | eps_basic | H | 3.64 | 3.64e+06 | ❌ 口径/推导 |  |
| us:WFC | 流水线 | eps_basic | Q | 2.02 | 2.02e+06 | ❌ 口径/推导 |  |
| us:USB | 简单直接问 | net_interest_income | H | 8.624e+09 | — | not_answered | not_answered |
| us:USB | 简单直接问 | net_interest_income | Q | 4.361e+09 | — | not_answered | not_answered |
| us:USB | 流水线 | eps_basic | H | 2.53 | 2.53e+06 | ❌ 口径/推导 |  |
| us:USB | 流水线 | eps_basic | Q | 1.35 | 1.35e+06 | ❌ 口径/推导 |  |
| us:AIG | 流水线 | eps_basic | H | 3.21 | 3.21e+06 | ❌ 单位 |  |
| us:AIG | 流水线 | eps_basic | Q | 1.79 | 1.79e+06 | ❌ 单位 |  |
| us:NIO | 简单直接问 | net_income_parent | FY | -1.496e+10 | -1.557e+10 | answered |  |
| us:NIO | 流水线 | net_income_parent | FY | -1.496e+10 | -1.557e+10 | ❌ 口径 |  |
| a:601857 | 简单直接问 | revenue | Q | 6.952e+11 | — | — |  |
| a:601857 | 简单直接问 | net_income_parent | Q | 3.102e+10 | — | — |  |
| a:601398 | 简单直接问 | revenue | Q | 1.982e+11 | — | — |  |
| a:601398 | 简单直接问 | net_income_parent | Q | 9.865e+10 | — | — |  |
| a:601398 | 简单直接问 | net_interest_income | FY | 6.351e+11 | — | not_answered | not_answered |
| a:601398 | 流水线 | revenue | Q | 1.982e+11 | — | ❌ 漏抽 | ❌ |
| a:601398 | 流水线 | net_income_parent | Q | 9.865e+10 | — | ❌ 漏抽 | ❌ |
| a:000001 | 简单直接问 | net_interest_income | Q | 2.208e+10 | — | not_answered | not_answered |
| a:002142 | 简单直接问 | net_interest_income | H | 2.939e+10 | — | not_answered | not_answered |

## 2. 修订记录（看过冻结版结果之后）

下面的内容摘自 eval_design §10.2，是那里的原文。

### 2.1 登记的修订（R1–R3）

| 编号 | 改了什么 | 为什么改 | 由哪些条目触发 | 文件 |
|---|---|---|---|---|
| R1 | 美股标准答案：非年报（10-Q）里 12 个月期间的 XBRL 事实是滚动 12 个月（TTM）数，不再当作 FY 条目 | 冻结版把 AMZN 10-Q 现金流量表里的 TTM 列当成了 FY 标准答案，于是 FY 成了“应有期间”，三档都被判漏答或漏抽 | AMZN 2026Q2：归母净利润 FY、经营现金流 FY，三档各 2 条 | `earnings_agent/benchmark.py` |
| R2 | 每股指标（EPS）不继承表头的金额单位（百万/千），倍数固定为 1。这类表头的写法有 “in millions, except per share amounts”“Dollars and Shares in Millions”，以及只抄到 “Except Per Share Amounts” 的情况。“per common share” 也识别为每股单位。（第一版修订冻结 `886f98b` 曾附带“美股表头里单独的 dollars 识别为 USD”。误报分析显示，它会同时消掉流水线 21 条误报里的 17 条，影响的远不止 EPS，超出了这次授权的范围，所以在留出集运行之前撤回，见 §10.2 末尾。）仙、美分等真正的每股单位仍须能单独解析，不会被当成 1 倍 | 冻结版流水线把 EPS 当成“百万美元”，换算后差 10⁶ 倍或被判单位无法解析 | INTC、BAC、WFC、USB、AIG 的 EPS Q 和 H，共 10 条，全部是流水线 | `earnings_agent/units.py`、`verify.py`、`direct.py`（解析时同样按每股处理） |
| R3 | **新增一档“专业直接问 + 核验层”**（只跑 DeepSeek）：<br>① 提示词就是专业直接问的提示词，末尾加一句，要求每个数字给出页码和原文句子；如果是算出来的，给出所用原文数字的页码和原文。<br>② 解析器多抄三项：页码、原文句子、是否为计算值及其组成项。<br>③ 解析结果交给流水线**同一套**核验 `verify_report`（C1–C4 + 合理性检查 + 应有期间/漏抽），❌ 即标记。<br>④ 不补问。<br>⑤ 计分用的仍是回答给出的数字，核验层只负责加标记。计算值的组成项重算后与回答不一致的，标 ❌ | 看到“专业直接问准确率高，但没有标记机制”后提出的新设计 | ——（新设计，不是由具体条目触发） | `earnings_agent/direct.py`（`build_verified_prompt` 等）、`earnings_agent/direct_verify.py` |

**R3 是看到评估结果后才提出的新设计，单独标注**，不能当作冻结时就计划好的一档。

**修订版怎么产生**：

- `eval1_rev1` 用 `--salt eval1` 复用 eval1 的模型回复（本地缓存），只重新核验、重新评分。
- 只有 eval1 里没出现过的提示词才会真正调用模型：一是 R3 新档的 60 次提问加 60 次解析；二是因为 R1 改了“应有期间”，补问内容不同的那几份要重新补问。这部分成本单独列出。
- 评分条目集合仍由冻结的三档决定（`score_eval.item_set` 只看三档），所以修订版和冻结版比的是同一组条目，只是 R1 去掉了 AMZN 那几条。

**发现但未修订的问题**（不在本次登记的修订范围内，留待决定）：

- **单独的 “dollars” 不识别为币种**（候选修订，未授权）：美股表头写 “Millions of dollars”“Dollars in millions” 时，币种无法识别，C3 判 ❌，而数字本身是对的。冻结版流水线的 21 条误报里有 17 条是这个原因（CVX、BAC、AIG）。R2 修好 AIG、USB、WFC 的 EPS 倍数以后，AIG 的 EPS 仍会因为币种被标 ❌，变成“答对但被标记”。
  - 撤回经过：曾作为 R2 的附带修改，进入第一版修订冻结 `886f98b`。在留出集运行之前撤回，重新冻结；用第一版冻结跑出的 eval1_rev1 结果作废重跑（只是重新核验，不花钱）。

- 港股 EPS 用“仙”或“美仙/美分”列示时，单位无法解析，流水线判 C3 ❌。R2 有意不碰它，因为“仙”是 0.01 倍，不能当 1 倍处理。
- “分人民幣”被当成 1 倍，冻结版就是这样。


**登记日志**（`eval/FROZEN.json` → `revisions`）：

- 2026-10-07T01:36:39 UTC，commit `886f98b158`：R1 AMZN TTM 不算 FY；R2 每股指标不继承表头单位（附：美股单独 dollars=USD）；R3 新增专业直接问+核验层（看过结果后的新设计）。冻结版仍是主结果，修订版并列（eval_design §10）（改动文件 7 个）
- 2026-10-07T01:38:46 UTC，commit `7c11143f23`：更正：撤回第一版修订冻结（886f98b）中 R2 附带的“美股单独 dollars=USD”，它超出授权范围（会改变所有美股金额字段的 C3，消掉 21 条误报中的 17 条）。在留出集运行前撤回并重新冻结；用 886f98b 跑出的 eval1_rev1 作废重跑（改动文件 7 个）

修订版规则冻结于 commit `7c11143f23`（`eval/FROZEN_REV1.json`，2026-10-07T01:38:46 UTC）。

**修订过程中的更正**：第一版修订冻结 `886f98b` 在 R2 里附带了“美股单独 dollars=USD”。这条超出了授权范围：它会改变全部美股金额字段的 C3，消掉冻结版 21 条误报中的 17 条。所以在留出集运行之前撤回，重新冻结（`7c11143`）。用第一版冻结跑出的 eval1_rev1 已作废重跑。

**误报分析中新发现、未修订的问题**（只记录，不改规则）：

- 单独的 “dollars” 不识别为币种：冻结版误报的主因（17/21），见上文。
- AMZN 的 4 条 S5 误报（“单季 + 上季末累计 ≈ 累计”）。原因与 R1 相同：`benchmark.us_prior` 从 10-Q 里取累计期起点时，取到了 TTM 事实的起点，于是“上季末累计”用错了期间。R1 只授权修正标准答案（评分），没有覆盖合理性检查的取数，所以这 4 条在修订版里仍然是误报。
- R1 的附带影响：AMZN 去掉 FY 条目后，评分器认定的“累计期间”变成 H。直接问给出的 AMZN 毛利（H）因此进入评分条目；AMZN 没有毛利的 XBRL，所以这一条记为待核对，不评分。

### 2.2 eval1 上冻结版与修订版并列（同一批模型回复）

冻结版（主结果）：

| 档 | 条目 | 严格正确（95% CI） | 大致正确 | 编造率 | 静默错误率 | 复核工作量 | 标记召回率（含 C4 / 去 C4） | ❌ 中误报占比 | 每份成本（均值 / 中位 / 最大） |
|---|---|---|---|---|---|---|---|---|---|
| 简单直接问 | 246 | 228（92.7%；88.2%–96.8%） | 228（92.7%） | 0/229（0.0%） | 1（0.4%） | 0（0.0%） | 0（无标记机制） | — | $0.0011 / $0.0009 / $0.0024 |
| 专业直接问 | 246 | 242（98.4%；96.0%–100.0%） | 242（98.4%） | 0/242（0.0%） | 0（0.0%） | 0（0.0%） | 0（无标记机制） | — | $0.0140 / $0.0131 / $0.0419 |
| 流水线 | 246 | 229（93.1%；89.3%–96.7%） | 229（93.1%） | 0/238（0.0%） | 0（0.0%） | 38（15.4%） | 100.0% / 94.1% | 55.3% | $0.0048 / $0.0044 / $0.0082 |

修订版（R1 + R2；R3 新档只有修订版）：

| 档 | 条目 | 严格正确（95% CI） | 大致正确 | 编造率 | 静默错误率 | 复核工作量 | 标记召回率（含 C4 / 去 C4） | ❌ 中误报占比 | 每份成本（均值 / 中位 / 最大） |
|---|---|---|---|---|---|---|---|---|---|
| 简单直接问 | 244 | 228（93.4%；88.9%–97.5%） | 228（93.4%） | 0/229（0.0%） | 1（0.4%） | 0（0.0%） | 0（无标记机制） | — | $0.0011 / $0.0009 / $0.0024 |
| 专业直接问 | 244 | 242（99.2%；97.5%–100.0%） | 242（99.2%） | 0/242（0.0%） | 0（0.0%） | 0（0.0%） | 0（无标记机制） | — | $0.0140 / $0.0131 / $0.0419 |
| 流水线 | 244 | 239（98.0%；95.4%–100.0%） | 239（98.0%） | 0/242（0.0%） | 0（0.0%） | 30（12.3%） | 100.0% / 80.0% | 83.3% | $0.0048 / $0.0043 / $0.0082 |

> **R3 那一档是看过结果之后设计的新档，单独标注。** 它在 eval1 上的数字不能用来证明修订有效，要看 §3 的留出集。

修订版流水线的误报：

流水线：误报 25 条。

| 触发的检查 | 误报条目中触发次数 | 其中为唯一触发 |
|---|---|---|
| C3 单位/币种 | 21 | 21 |
| S5 单季+上季累计≈累计 | 4 | 4 |

<details><summary>逐条</summary>

- us:AMZN net_income_parent H：S5 单季+上季累计≈累计（合理性检查：单季 62,647,000,000 + 截至 2025-09-30 累计 21,187,000,000 ≠ H 92,902,000,000（差 -9,068,000,000））
- us:AMZN net_income_parent Q：S5 单季+上季累计≈累计（合理性检查：单季 62,647,000,000 + 截至 2025-09-30 累计 21,187,000,000 ≠ H 92,902,000,000（差 -9,068,000,000））
- us:AMZN operating_cash_flow H：S5 单季+上季累计≈累计（合理性检查：单季 45,387,000,000 + 截至 2025-09-30 累计 35,525,000,000 ≠ H 71,419,000,000（差 9,493,000,000））
- us:AMZN operating_cash_flow Q：S5 单季+上季累计≈累计（合理性检查：单季 45,387,000,000 + 截至 2025-09-30 累计 35,525,000,000 ≠ H 71,419,000,000（差 9,493,000,000））
- us:CVX net_income_parent H：C3 单位/币种（币种无法识别：'dollars'/'Millions of dollars'）
- us:CVX net_income_parent Q：C3 单位/币种（币种无法识别：'dollars'/'Millions of dollars'）
- us:CVX eps_basic H：C3 单位/币种（币种无法识别：'dollars'/'per-share amounts'）
- us:CVX eps_basic Q：C3 单位/币种（币种无法识别：'dollars'/'per-share amounts'）
- us:CVX operating_cash_flow H：C3 单位/币种（币种无法识别：'dollars'/'Millions of dollars'）
- us:BAC revenue H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC revenue Q：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_income_parent H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_income_parent Q：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC eps_basic H：C3 单位/币种（币种无法识别：'Dollars'/'per common share'）
- us:BAC eps_basic Q：C3 单位/币种（币种无法识别：'Dollars'/'per common share'）
- us:BAC operating_cash_flow H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_interest_income H：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:BAC net_interest_income Q：C3 单位/币种（币种无法识别：'Dollars'/'Dollars in millions'）
- us:AIG revenue H：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG revenue Q：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG net_income_parent H：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG net_income_parent Q：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions'）
- us:AIG eps_basic H：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions, except per common share data'）
- us:AIG eps_basic Q：C3 单位/币种（币种无法识别：'dollars'/'dollars in millions, except per common share data'）
- us:AIG operating_cash_flow H：C3 单位/币种（币种无法识别：'dollars'/'in millions'）

</details>

R3 新档的误报：

专业直接问 + 核验层（R3）：没有误报。

## 3. 留出集结果（四档，DeepSeek）

尚未运行。

## 4. 局限

- **以 DeepSeek 为主**：主结论基于 DeepSeek 的 60 份。Fable 只有 9 份，是小样本补充，不能单独下结论。
- **输入是解析后的文本，不是 PDF**：所有档拿到的都是同一份 pdfplumber/HTML 解析文本。真实用户可能直接上传 PDF，PDF 的版面信息可能帮助或干扰模型，本评估不涉及。
- **港股留出集没有评分**：港股没有可靠的自动标准答案，为避免再做一轮人工核对，留出集只评美股和 A 股，所以修订在港股上是否有效没有验证。冻结版的港股结果依赖人工核对。
- **修订是看过结果之后做的**：R1、R2 是针对 eval1 暴露的问题改的，R3 是看到结果后提出的新设计。它们在 eval1 上的改善是自证的，只有留出集的结果才算证据。
- **美股和 A 股的 C4 存在循环**：C4 用的就是作为标准答案的 XBRL/AKShare，所以同时报告了去 C4 的标记召回率。
- 稳定性只测了 DeepSeek，15 份，每份共 3 次。

## 附：名单替换留痕

| 候选 | 替换为 | 原因 | 时间 |
|---|---|---|---|
| C（Citigroup，银行） | USB（U.S. Bancorp，银行） | 2026 年 10-Q 存在，但 SEC companyfacts 没有这些申报的 XBRL，因此没有自动标准答案 | 冻结前，2026-10-06 |
| XOM（ExxonMobil，能源） | CVX（Chevron，能源） | 2026 年改由新控股公司（新 CIK 0002115436）申报，上一期 10-Q 在旧 CIK 下，按现有逻辑拿不到上一期 | 冻结前，2026-10-06 |

留出集没有替换（`eval/holdout_config.json` 的 `unavailable` 为空时）。
