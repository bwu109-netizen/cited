# 通用提示词 / Universal prompt

- `universal_prompt_zh.md`、`universal_prompt_en.md`：同一份提示词的中英文版。网页核验页的“复制通用提示词”按钮按界面语言复制其中一份（文件内容原样复制，所以文件里只放提示词本身）。
- 用法：在任意 AI 里上传财报 PDF，贴上提示词；把回答整段贴回核验页。核验页会取回答里第一个 ```json 代码块，忽略后面的表格；`status` 为 `not_disclosed` 的条目单独列出，不算解析失败。
- 口径与 `docs/metrics_spec.md` 一致；页码是 PDF 页序号（从 1 开始），与核验层的页码定义相同。

评估情况：
- 由评估里“专业直接问 + 核验层”（R3，`earnings_agent/direct.py` 的 `build_verified_prompt`）改写而来。R3 在 DeepSeek 留出集上的严格正确率为 97.1%（美股 + A 股 205 条，输入是解析后的文本，见 `docs/eval_results.md` §3）。
- 通用版改了输出格式（直接输出 JSON，不再经过解析模型），本身没有单独评估；其他模型都未经评估。
