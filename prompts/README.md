# Universal prompt

- `universal_prompt_zh.md`, `universal_prompt_en.md`: the same prompt in Chinese and English. The "copy universal prompt" button on the site's Verify page copies one of them, following the interface language (the file content is copied as is, so the files contain only the prompt itself).
- Usage: upload the filing PDF to any AI and paste the prompt; paste the whole reply back into the Verify page. The Verify page takes the first ```json code block of the reply and ignores the table after it; items whose `status` is `not_disclosed` are listed separately and do not count as parse failures.
- Definitions follow `docs/metrics_spec.md`; the page is the PDF page index (counted from 1), the same page definition as the verification layer.
- The English prompt keeps a few Chinese line names (for example "营业收入" vs "营业总收入", "人民币百万元") on purpose: they are the literal wording printed in A-share and Hong Kong filings that the model has to find and copy.

Evaluation status:
- Adapted from the "expert direct question + verification layer" tier in the evaluation (R3, `build_verified_prompt` in `earnings_agent/direct.py`). R3 scored 97.1% strict accuracy on the DeepSeek holdout (205 US + A-share rows, parsed text as input; see `docs/eval_results.md` §3).
- The universal version changes the output format (JSON directly, no parser model in between) and has not been evaluated on its own; other models have not been evaluated.
