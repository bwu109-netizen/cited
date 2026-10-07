# 冻结清单

> 状态：见 `eval/FROZEN.json`（由 `python eval/check_frozen.py --write` 生成，记录 git commit 号和每个文件的 sha256）。
> 之后每次运行评估前，都先执行 `python eval/check_frozen.py`。任何一个冻结文件变了就拒绝运行。规则修订后重跑，必须用 `--revision "原因"` 显式登记，并按 eval_design §7.2 同时报告修订前后两套结果。

- 冻结 commit：`b282e43`（重写后 `e8bff82`）（清单 `eval/FROZEN.json` 提交于 `e7bced2`（重写后 `b33e0a6`）；git 标签 `eval-frozen-v1` 指向 `cba5dba`（重写后 `f4a187e`），它只多改了核对表的展示，冻结文件与 `b282e43`（重写后 `e8bff82`） 相同）
- 冻结时间：2026-10-06 22:23 UTC
- 冻结版的运行位置：工作树 `.worktrees/frozen-v1`（`git worktree add --detach .worktrees/frozen-v1 eval-frozen-v1`；`data/` 下的 cache、eval、raw、output 用软链接指回主目录，共用缓存和同一本 $20 账本）。主目录已经包含修订（§6），**冻结版的 Fable 两批和港股核对后的冻结版评分都必须在这个工作树里跑**。

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

## 6. 修订版冻结（eval_design §10）

- 看过冻结版结果之后登记了三处修订 R1–R3，见 `docs/eval_design.md` §10.2。登记方式：在主目录运行 `python eval/check_frozen.py --revision "…"`，修订会追加到 `eval/FROZEN.json` 的 `revisions` 里。
- 修订后的规则另外冻结在 `eval/FROZEN_REV1.json`（`python eval/check_frozen.py --manifest eval/FROZEN_REV1.json --write`）。主目录的 `eval/run_eval.py` 只认这份清单。
- 修订版新增的冻结文件：
  - `eval/holdout_config.json`：留出集名单；
  - `earnings_agent/direct_verify.py`：R3 的核验层接口。
- 修订版冻结之后跑的：
  - `eval1_rev1`：复用 eval1 的回复，重新核验和评分，并跑 R3 新档；
  - `hold1`：留出集四档。
  跑完不再改。
- 修订版冻结 commit：见 `eval/FROZEN_REV1.json` 的 `commit` 字段。
- **第二次修订冻结（取代 REV1）**：登记 R4、R5 之后，修订版重新冻结在 `eval/FROZEN_REV2.json`，主目录的 `run_eval.py` 改认这份清单。`FROZEN_REV1.json` 保留作为记录。修订版 eval1 和留出集都用 REV2 的规则（R1–R5）。
- **R6（产品专用，2026-10-06）**：仙 / 美分换算，提交在 REV2 之后。它不属于任何评估规则，主目录因此不再通过 REV2 检查。修订版评估的规则保存在标签 `eval-revised-v2`，冻结版保存在 `eval-frozen-v1`。

## 7. 历史改写（2026-10-07，推送到 GitHub 之前）

### 7.1 为什么改写

公开仓库不应包含两类文件：
- Stitch 原型截图：含编造数字；
- `data/review/hk_answer_key_demo.html`：港股核对表示例，含财报原文片段。

这两类文件在早期提交里出现过，所以用 `git filter-branch --index-filter` 从所有提交里删除了它们，**其他内容一个字节都没变**。

### 7.2 改写的影响

- 从 `75ef327` 起的提交哈希都变了，下表是对照。
- 两个标签 `eval-frozen-v1`、`eval-revised-v2` 已移到改写后的对应提交。
- 冻结清单里记录的是每个冻结文件的 sha256，不受影响：在改写后的标签上运行 `python eval/check_frozen.py`（或带 `--manifest`）仍然通过。
- 文档里引用的旧哈希都注明了“重写后”的新哈希。
- JSON 冻结清单保留原 `commit` 字段，另加 `commit_rewritten` 字段。

### 7.3 第二次改写（2026-10-07，提交作者）

- 本地 git 用户原来是机器名，GitHub 无法关联到账号。现在把全部提交的作者和提交者改为 Boxiao Wu（GitHub noreply 地址，关联到 bwu109-netizen），每个提交信息末尾统一为一行 `Co-authored-by: Claude <noreply@anthropic.com>`。
- 文件内容没有任何变化，所以哈希再次全部改变。
- 两个标签都已移到新提交，并以新作者重新签注。
- 文档里的“重写后”和 JSON 里的 `commit_rewritten` 都已更新为最终哈希。

### 7.4 哈希对照（原始 → 第一次改写 → 第二次改写 = 当前）

| 原始 | 第一次改写 | 当前 | 提交说明 |
|---|---|---|---|
| `9ed1abd` | `9ed1abd` | `7ca721a` | Phase 0: data source feasibility scripts and findings |
| `50e41a1` | `50e41a1` | `d43d989` | Phase 1/1.5: extraction pipeline, verification layer, sanity checks |
| `bdcd278` | `bdcd278` | `aae9197` | Phase 2 design: eval_design.md, 60-company candidate check, fetch/locate |
| `75ef327` | `e150e5e` | `9e74cd3` | Phase 2 prep: budget plan, frozen subsets, spend cap, HK review table |
| `cc96dd7` | `a4964b0` | `4b4e9c7` | Remove unused preview launch config |
| `33562e4` | `f5d2491` | `eca6ac4` | Direct-ask cell, answer parser, scorer, Anthropic batch client; dev vali |
| `b282e43` | `d560e2c` | `e8bff82` | Eval runner: simple direct-ask cell, three-tier DeepSeek, Fable split by |
| `e7bced2` | `8b742a7` | `b33e0a6` | Freeze evaluation rules (eval/FROZEN.json) |
| `cba5dba` | `7856b69` | `f4a187e` | Review table: show revenue/cost components for code-derived gross profit |
| `886f98b` | `327c3c7` | `eb778f5` | Revisions R1-R3 after frozen eval1 (eval_design §10); holdout list; anal |
| `36edcd6` | `1e224c3` | `a18de16` | Log revisions R1-R3 against frozen v1; freeze revised rules (eval/FROZEN |
| `7c11143` | `fb426a9` | `c62e2cf` | R2: withdraw bundled 'dollars'=USD rule (out of the approved scope); re- |
| `ef602c5` | `7df5621` | `6eacfb0` | Re-freeze revised rules after withdrawing the out-of-scope R2 add-on |
| `0ec1d14` | `ec57ec8` | `6e261b7` | Draft docs/eval_results.md: frozen results with new metrics, false-alarm |
| `8be8268` | `ade3814` | `3f2c7ac` | Revisions R4 (bare 'dollars' = USD in US filings) and R5 (S5 prior ignor |
| `3b8ffee` | `1aa6912` | `4ba384e` | Freeze revised rules R1-R5 (eval/FROZEN_REV2.json) |
| `f7fe10a` | `4b0241e` | `168d3c5` | eval_results.md: Fable costs, revised eval1 (R1-R5 + R3 cell), holdout f |
| `b171cc7` | `029ba50` | `11491d4` | Manual answer key from the review export (128 pick, 6 edit, 12 na) |
| `22968a4` | `6210498` | `6f91004` | eval_results.md: full three-market eval1 (frozen + revised) with HK manu |
| `58ce693` | `bbe59f3` | `61965b9` | R6 (product only): per-share figures in 仙 / cents / 美分 convert at 0.01;  |
| `235fab5` | `1d0b737` | `1a25532` | PRD draft: verification page (no key, no model calls) |
| `16c1e49` | `ee61529` | `f835029` | PRD_web.md (5 pages, verify page merged); web/CLAUDE.md with Ponytail ru |
| `730c344` | `7020206` | `d83bd18` | PRD_web: visual tokens from the Stitch reference (visual only), general  |
| `c633e5e` | `314dcf0` | `e79cbd8` | Web app (phase 4): Streamlit custom component, 5 pages, examples, eval n |
| `d472046` | `6d071d9` | `a828416` | Web: plain-language fetch-failure reasons |
| `395f8a5` | `58c51b5` | `6174ea2` | Rename to 有据 / Cited; HK unflagged note on home; industry metrics in the |
| `—` | `e97a0fb` | `3fdc06d` | Record the pre-publication history rewrite: old->new commit table (eval/ |

