# 冻结清单

> 状态：见 `eval/FROZEN.json`（由 `python eval/check_frozen.py --write` 生成，记录 git commit 号和每个文件的 sha256）。
> 之后每次运行评估前，都先执行 `python eval/check_frozen.py`。任何一个冻结文件变了就拒绝运行。规则修订后重跑，必须用 `--revision "原因"` 显式登记，并按 eval_design §7.2 同时报告修订前后两套结果。

- 冻结 commit：`（冻结时填写）`
- 冻结时间：`（冻结时填写）`

## 1. 冻结的文件

| 类别 | 文件 | 冻结的内容 |
|---|---|---|
| 评估输入 | `eval/config.json` | 60 份报告（市场、代码、目标期间、上一期）、四格的模型与参数、运行 id |
| | `eval/fable_subset.json`、`eval/fable_subset.py` | Fable 9 份子集及抽样规则（种子 20261006） |
| | `eval/stability_subset.json`、`eval/stability_subset.py` | 稳定性 15 份子集及抽样规则（种子 20261007） |
| 提示词 | `earnings_agent/extract.py` | 流水线抽取提示词（SYSTEM、FIELD_DEFS、期间说明）和补问提示词 |
| | `earnings_agent/direct.py` | 专业直接问的提问模板（DIRECT_DEFS）、**简单直接问的一句话问题（SIMPLE_QUESTION）**、回答解析器提示词、解析结果的代码核对 |
| 核验与规则 | `earnings_agent/verify.py` | C1–C4、状态、失败分类、应有期间（漏抽）规则 |
| | `earnings_agent/sanity.py` | 合理性检查 §7.3 |
| | `earnings_agent/units.py`、`textnorm.py`、`periods.py`、`templates.py` | 单位/币种解析、规范化（NFKC、繁转简）、期间判定、行业模板判定 |
| 模型看到什么、和什么比 | `earnings_agent/parse.py`、`locate.py`、`sources.py` | 文档获取、分页、页面定位（决定送给模型的页） |
| | `earnings_agent/benchmark.py` | 自动标准答案（XBRL / AKShare）的取法 |
| | `earnings_agent/pipeline.py` | 流水线步骤顺序、补问一次 |
| 模型调用与费用 | `earnings_agent/config.py` | 模型 ID、推理强度、价格表、预算上限 $20 |
| | `earnings_agent/llm_client.py`、`anthropic_batch.py`、`budget.py` | 调用参数（temperature、max_tokens）、Batch 流程、硬上限 |
| 评分 | `eval/score.py` | 答案键构建、严格/大致两档、编造判定、标出率（含/去 C4） |
| | `eval/score_eval.py` | 每份报告的评分条目集合、待人工核对条目、争议行判定 |
| 运行 | `eval/run_eval.py` | 运行顺序、三档 DeepSeek、稳定性、Fable 两批及提交前核算、冻结检查 |
| 书面规则 | `docs/metrics_spec.md`（v0.3）、`docs/eval_design.md`（v0.2） | 口径与评估设计 |

## 2. 冻结的参数（来自 `eval/config.json` 和代码）

| 格 | 模型 | 推理强度 | temperature | max_tokens | 调用方式 | 失败时 |
|---|---|---|---|---|---|---|
| DeepSeek × 流水线 | `deepseek-flash` | low | 0 | 16,000 | 同步 | **不回退**到其他服务商；JSON 非法时重试 1 次 |
| DeepSeek × 专业直接问 | `deepseek-flash` | low | 0 | 16,000 | 同步 | 不回退 |
| DeepSeek × 简单直接问 | `deepseek-flash` | low | 0 | 16,000 | 同步 | 不回退 |
| Fable × 直接问 | `claude-fable-5-1` | 默认（high） | 不传 | 32,000 | Message Batches，**第 1 批** | 提交前精确核算，放不下就停 |
| Fable × 流水线 | `claude-fable-5-1` | 默认（high） | 不传（API 默认） | 32,000 | Message Batches，**第 2 批**（直接问结算后）；补问为第 3 批 | 同上；补问放不下则不补问，记漏抽 |
| 直接问回答解析（评估开销） | `deepseek-flash` | low | 0 | 16,000 | 同步 | 不回退 |

- **运行 id**：主评估 `eval1`；稳定性 `eval1`、`eval2`、`eval3`（`eval1` 即主评估那次），三档都做。运行 id 写入本地缓存键，所以重复跑必定真的重新调用模型。
- **预算**：`EVAL_BUDGET_USD=20`，账本 `data/eval/spend_ledger.jsonl`。开发集验证的花费也已计入这个账本。

## 3. 不冻结的文件（不影响结果）

- `eval/review_table.py`、`eval/review_table_template.html`：核对表的展示。核对结果本身作为人工答案键保存，答案键一旦生成即冻结（见第 4 节）。
- `eval/dev_report.py`、`scripts/*`：报告排版、开发期脚本。
- `tests/*`：测试可以增加，但不能改动被测的冻结文件。

## 4. 冻结之后才产生、产生后即冻结的东西

- **港股人工答案键**：你在核对表里导出的 JSON，导出后提交，记录 commit。
- **美股/A 股争议行的裁决**：同上。
- **评估原始输出**：`data/eval/eval1/…`（模型回复缓存和每份结果 JSON）。不入 git，但在最终报告里给出文件清单和 sha256。

## 5. 冻结前确认（2026-10-06，均已确认）

- [x] 专业直接问的提示词（`docs/direct_prompt.md`），“如果是银行……”保留
- [x] 加简单直接问第三档
- [x] Fable max_tokens 32k，按格分两批
- [x] `eval/config.json` 里 60 份的目标期间和上一期
