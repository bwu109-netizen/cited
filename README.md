# 有据 / Cited

从美股、A 股、港股的定期报告里抽取核心财务数字（营业收入、归母净利润、基本 EPS、毛利、经营现金流；银行、保险另有模板），每个数字附页码和原文引用，再用纯代码核验，把可疑的数标红。

Core figures from US, A-share and HK filings, each with its page and verbatim quote, checked by code; suspicious ones are flagged in red.

- 线上地址：https://boxiao-cited.streamlit.app/
- 示例和核验页不需要 API key；单家分析和批量对比用你自己的 key（默认 DeepSeek，支持多家服务商）

## 它做什么，不做什么

1. **下载并定位**：从 SEC EDGAR、巨潮资讯、HKEXnews 取原文，找到报表所在页。
2. **照抄**：模型只抄写原文的数字、单位、页码和整行引用，不做换算。
3. **代码核验**：
   - C1 引用在页上；
   - C2 数字逐字在页上；
   - C3 单位和币种可解析；
   - C4 与 SEC XBRL / 东财比对（仅美股和 A 股）；
   - S1–S5 合理性检查。

   核验不过的标红并给出一句话原因。

核验只能确认数字在原文里、单位对、和其他数自洽，**不能确认它就是你要的指标**。未标红不等于正确。

## 评估（全部数字见 [docs/eval_results.md](docs/eval_results.md)）

在 DeepSeek 上做了三档对比：简单直接问 / 专业直接问 / 流水线，并在 60 份评估集和 60 份留出集上评分。

- **专业写法的直接问严格正确率最高**：eval1 全量三地为 97.1%，流水线为 92.6%。
- 流水线的不同在于每个数都有页码和原文，可疑的数被标出：
  - 美股 + A 股留出集上，流水线严格正确 96.1%，需要复核的条目占 4.9%，205 条中给了错数且没被标出的为 0 条；
  - 港股的标记召回率明显更低：冻结版 10 个错误中 3 个未被标出，因为港股没有可靠的结构化数据可比。
- 局限：
  - 以 DeepSeek 为主，Fable 只有 9 份小样本；
  - 输入是解析文本，不是 PDF；
  - 港股留出集未评分；
  - 修订是看过结果之后做的，冻结与修订的过程见 [docs/eval_design.md](docs/eval_design.md) §10。

## 通用提示词

[`prompts/`](prompts/) 里有一份中英文两版的通用提示词，可以在任何 AI（GPT、Claude、DeepSeek、豆包等）里使用。
- 用法：上传财报，贴上提示词，再把 AI 的回答整段贴回网页的核验页，用代码核对每个数。
- 要求：每个数给出 PDF 页序号和原文整行；原文没有的指标写 `not_disclosed`，不许估算；输出 JSON 加一张可读表格。

评估情况：
- 它由评估里“专业直接问 + 核验层”（R3）的提问改写而来。R3 在 DeepSeek 留出集上的严格正确率为 97.1%（美股 + A 股 205 条，输入是解析后的文本，见 [docs/eval_results.md](docs/eval_results.md) §3）。
- 通用版改了输出格式，本身没有单独评估；其他模型都未经评估。

## 本地运行

```bash
python3.9 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

命令行抽取一份财报（用 `.env` 里的 key，模板见 `.env.example`）：

```bash
.venv/bin/python -m earnings_agent extract --market hk --code 00700 --period 2026H1
```

## 目录

| 路径 | 内容 |
|---|---|
| `earnings_agent/` | 抽取流水线与核验层（取数、解析、定位、提示词、单位换算、C1–C4、合理性检查） |
| `eval/` | 评估：名单、冻结清单、评分、分析 |
| `web/` | 网页：一个 Streamlit 自定义组件（`web/ui/`，无构建步骤）+ Python 侧（任务线程、核验页解析、汇率、示例） |
| `docs/` | 口径定义、评估设计与结果、网页 PRD、设计系统 |
| `tests/` | 单元测试 |

## 设计过程

PRD（[docs/PRD_web.md](docs/PRD_web.md)）→ Stitch 原型（只借视觉；原型中编造的数字和功能未采用，截图不入库）→ Streamlit 自定义组件实现。页面上的评估数字只来自 `docs/eval_results.md`。

## 许可

MIT
