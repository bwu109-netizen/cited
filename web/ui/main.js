/* Cited — single-page UI inside one Streamlit component.
   Layout and visuals follow docs/stitch (dark screens); every number and claim comes from the job result,
   the pre-computed examples or eval_numbers.json (docs/eval_results.md). PRD: docs/PRD_web.md. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ bridge
  var evt = 0, gotRender = false, bigEventId = 0;
  function post(type, data) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data || {}), "*");
  }
  function send(type, data) {
    evt += 1;
    post("streamlit:setComponentValue", { value: Object.assign({ id: evt, type: type }, data || {}), dataType: "json" });
    return evt;
  }
  function setHeight() {
    var h = 800;
    try { h = window.parent.innerHeight || h; } catch (e) { /* cross-origin fallback */ }
    post("streamlit:setFrameHeight", { height: h });
  }
  window.addEventListener("message", function (e) {
    if (e.data && e.data.type === "streamlit:render") { gotRender = true; onRender(e.data.args || {}); }
  });
  (function ready() {
    if (gotRender) return;
    post("streamlit:componentReady", { apiVersion: 1 });
    setTimeout(ready, 400);
  })();
  try { window.parent.addEventListener("resize", function () { setHeight(); render(); }); } catch (e) { /* ignore */ }

  // ------------------------------------------------------------------ state
  var S = {
    cfg: null, job: { status: "idle" }, pageView: null, lang: "zh", view: "analyze", menu: false,
    example: null,                       // key of the example being shown
    form: { market: "hk", code: "", period: "2026H1", provider: "deepseek", model: "", base_url: "", key: "", showKey: false },
    touched: false,
    cmp: { rows: [{ market: "us", code: "" }, { market: "a", code: "" }, { market: "hk", code: "" }], period: "2026H1", ccy: "orig", open: null },
    ver: { market: "us", period: "2026Q2", code: "", template: "auto", text: "", pdf: null, pdfName: "", pdfSize: 0, mapping: {} },
    upload: null,                         // {name, data} for the fetch-failed fallback
    drawer: null,                         // {src: "example"|"job", n, item}
    auxOpen: false, openQuotes: {}, openComps: {},
    log: [], lastStage: null, lastJobId: null, renderedSig: "",
    side: true,                           // left sidebar open (desktop); remembered in this browser
    hist: null, histCur: null,            // id of the saved result being shown from this browser's list
    saved: {}, provOpen: false, panelHidden: false
  };
  try { S.side = localStorage.getItem("cited-side") !== "0"; } catch (e) { /* default open */ }

  // ------------------------------------------------------------------ results kept in this browser only
  // Finished single analyses are kept in localStorage (never sent anywhere). Page texts referenced by the
  // result are included, so the source-page panel works offline (text only, no page image).
  // ponytail: 20 entries, oldest dropped first when the browser quota is hit
  var HIST_KEY = "cited-history", HIST_MAX = 20, TAB = Math.random().toString(36).slice(2, 8);
  function histLoad() { try { return JSON.parse(localStorage.getItem(HIST_KEY) || "[]") || []; } catch (e) { return []; } }
  function histSave(list) {
    while (list.length) { try { localStorage.setItem(HIST_KEY, JSON.stringify(list)); return; } catch (e) { list.pop(); } }
    try { localStorage.removeItem(HIST_KEY); } catch (e) { /* storage unavailable */ }
  }
  function histAdd(job) {
    var r = job.result, q = job.query || {}, id = TAB + "-" + job.id;
    var list = histLoad().filter(function (h) { return h.id !== id; });
    list.unshift({ id: id, ts: Date.now(), market: r.doc.market || q.market, code: r.doc.code || q.code, period: q.period || "", name: r.doc.name || "", counts: r.counts, result: r });
    histSave(list.slice(0, HIST_MAX));
    return id;
  }
  function histGet(id) {
    if (S.histCur && S.histCur.id === id) return S.histCur;
    S.histCur = histLoad().filter(function (h) { return h.id === id; })[0] || null;
    return S.histCur;
  }

  // ------------------------------------------------------------------ theme (light / dark)
  // Default follows the system (prefers-color-scheme); an explicit choice is remembered in this browser.
  var THEME_KEY = "cited-theme";
  function savedTheme() { try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; } }
  function systemTheme() { try { return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"; } catch (e) { return "dark"; } }
  function applyTheme(th) { S.theme = th; document.documentElement.setAttribute("data-theme", th); }
  applyTheme(savedTheme() || systemTheme());
  try {
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () {
      if (!savedTheme()) { applyTheme(systemTheme()); render(); }
    });
  } catch (e) { /* old browsers: keep the initial theme */ }

  // ------------------------------------------------------------------ i18n
  var T = {
    brand: ["有据", "Cited"],
    theme_to_light: ["切换到浅色", "Switch to light mode"], theme_to_dark: ["切换到深色", "Switch to dark mode"],
    nav_examples: ["示例", "Examples"], nav_analyze: ["分析", "Analyze"], nav_compare: ["批量对比", "Compare"],
    nav_verify: ["核验", "Verify"], nav_method: ["方法与评估", "Method"],
    hero_sub: ["美股、A 股、港股定期报告：抽取核心财务数字，附页码和原文，用代码核验，可疑的标红。",
      "US, A-share and HK filings: core figures with page and quote, checked by code, suspicious ones in red."],
    ex_title: ["示例结果", "Example results"], ex_back: ["返回示例", "Back to examples"],
    ex_note: ["示例为预跑结果：模型回复来自评估时的缓存，核验按当前规则重新运行。示例里的条数是结果表里的条数，不是评估指标。",
      "Pre-computed: model replies cached from the evaluation, checks re-run with the current rules. Counts are rows in the result table, not evaluation metrics."],
    ex_open: ["查看完整结果", "Open full result"], ex_tag: ["示例为预跑结果", "Pre-computed example"],
    how_title: ["怎么做的", "How it works"],
    how1_t: ["下载并定位报表页", "Fetch and locate statement pages"],
    how1_d: ["从 SEC EDGAR、巨潮资讯、HKEXnews 取原文，找到利润表、现金流量表所在页。", "Fetches the filing from SEC EDGAR, cninfo or HKEXnews and finds the income and cash-flow statement pages."],
    how2_t: ["模型照抄数字和原文", "The model copies numbers and quotes"],
    how2_d: ["模型只抄写原文的数字、单位、页码和整行引用，不做换算。", "The model only copies the number, unit, page and the full source line; it does no conversion."],
    how3_t: ["代码换算和核验", "Code converts and checks"],
    how3_d: ["单位换算、引用和数字是否在页上、合理性检查都由代码完成，不过的标红。", "Unit conversion, whether quote and number are on the page, and consistency checks run in code; failures are red."],
    eval_title: ["评估摘要", "Evaluation summary"],
    eval_strict: ["流水线严格正确率（留出集）", "Pipeline strict accuracy (holdout)"],
    eval_work: ["需要人工复核的条目比例", "Share of rows flagged for review"],
    eval_silent: ["给了数但错了、且没被标出的条目", "Wrong numbers that were not flagged"],
    eval_note: ["出处：docs/eval_results.md §3。专业写法的直接问在同一样本上严格正确率为 {d}，更高；流水线的不同在于每个数都有页码和原文，可疑的数会被标出。",
      "Source: docs/eval_results.md §3. A carefully worded direct question to the same model scored {d} strict accuracy on the same sample, higher; the pipeline differs in giving every number a page and a quote and flagging suspicious ones."],
    caveat: ["核验只能确认数字在原文里、单位对、和其他数自洽，不能确认它就是你要的指标；未标红不等于正确。",
      "Checks confirm a number is in the filing, in the right unit and consistent, not that it is the metric you asked for. Not flagged does not mean correct."],
    nokey_cta: ["没有 API key？看示例结果", "No API key? See example results"],
    verify_cta: ["已有其他 AI 的结果？去核验", "Have another AI's answer? Verify it"],
    about_eyebrow: ["关于有据", "ABOUT CITED"],
    sb_new: ["新分析", "New analysis"], sb_recent: ["最近的结果", "Recent results"], sb_local: ["仅保存在本机浏览器", "Kept only in this browser"],
    sb_empty: ["还没有结果。分析完成后会出现在这里。", "No results yet. Finished analyses appear here."], sb_clear: ["清空", "Clear"],
    sb_collapse: ["收起侧栏", "Collapse sidebar"], sb_expand: ["展开侧栏", "Expand sidebar"],
    key_none: ["未填写 API key", "No API key entered"], key_set: ["{p} key 已填 · 刷新页面即清空", "{p} key entered · cleared on reload"],
    a_q: ["分析哪一份财报？", "Which filing should we check?"],
    run_main: ["正在分析，结果会显示在这里。", "Analyzing; the result will appear here."], run_show: ["查看进度", "Show progress"],
    pn_checks: ["本次做的检查", "Checks in this run"], pn_hk_c4: ["港股没有可靠的结构化数据，这一项不做。", "HK has no reliable structured data; skipped."],
    h_saved: ["保存在本机浏览器 · {t}", "Saved in this browser · {t}"],
    status_bad: ["需要复核", "Needs review"], status_warn: ["无可比数据", "No external figure"], status_ok: ["通过核验", "Passed checks"],
    col_status: ["状态", "Status"], col_metric: ["指标", "Metric"], col_value: ["数值", "Value"], col_unit: ["单位", "Unit"],
    col_period: ["期间", "Period"], col_page: ["页码", "Page"], col_quote: ["原文引用", "Quote"],
    p_Q: ["单季", "Quarter"], p_H: ["半年", "Six months"], p_YTD: ["年初至今", "Year to date"], p_FY: ["全年", "Full year"], p_PIT: ["时点", "Point in time"],
    t_general: ["通用", "General"], t_bank: ["银行", "Bank"], t_insurance: ["保险", "Insurance"],
    r_pages: ["共 {a} 页 · 送给模型 {b} 页", "{a} pages · {b} sent to the model"], r_cost: ["本次花费 ≈ ${c}", "Cost ≈ ${c}"],
    r_end: ["期末日", "Period end"], r_source: ["原文", "Source"], r_template: ["模板", "Template"],
    r_core: ["核心指标", "Core metrics"], r_core_sub: ["需要复核的在最前；点页码看原文那一页", "Rows that need review come first; click a page number to open that page"],
    r_aux: ["辅助字段", "Auxiliary fields"], r_aux_sub: ["普通股股东应占、营业成本、加权股数等；会核验，但不是核心指标", "Net income to common, cost of revenue, share count…; checked, but not core metrics"],
    r_aux_bad: ["其中 {n} 条需要复核", "{n} need review"],
    r_metrics: ["行业指标", "Industry metrics"], r_metrics_sub: ["只核验了出处和单位（C1–C3），没有外部数据比对", "Only source and unit checked (C1–C3); no external comparison"],
    r_export_csv: ["导出 CSV", "Export CSV"], r_export_json: ["导出 JSON", "Export JSON"],
    r_followup: ["有 {n} 项没取到（已补问一次），在表中标为“未取得”。", "{n} items could not be extracted (asked once more) and are marked \"not found\"."],
    r_notfound: ["未取得", "Not found"], r_derived: ["推导", "Derived"], r_components: ["组成项", "Components"],
    r_more: ["展开", "More"], r_less: ["收起", "Less"], r_bench: ["结构化数据", "Structured data"],
    r_uploaded: ["上传的 PDF", "Uploaded PDF"],
    d_title: ["原文页", "Source page"], d_page: ["第 {n} 页 / 共 {t} 页", "Page {n} of {t}"],
    d_loading: ["正在载入这一页……", "Loading this page…"], d_textonly: ["这一页只保留了解析出的文字。", "Only the parsed text of this page is kept."],
    d_open: ["打开原文", "Open source"],
    // analyze
    f_market: ["市场", "MARKET"], f_code: ["代码", "TICKER"], f_period: ["报告期", "PERIOD"],
    f_provider: ["模型服务商", "PROVIDER"], f_model: ["模型", "MODEL"], f_base: ["Base URL", "Base URL"], f_key: ["API KEY", "API KEY"],
    m_us: ["美股", "US"], m_a: ["A 股", "A-share"], m_hk: ["港股", "HK"],
    ph_us: ["例如 AAPL", "e.g. AAPL"], ph_a: ["例如 600519", "e.g. 600519"], ph_hk: ["例如 00700（自动补齐 5 位）", "e.g. 00700 (padded to 5 digits)"],
    period_help: ["报告期按公司自己的财年标注：例如 MSFT 的 2026FY 截至 2026 年 6 月，NVDA 的 2027Q2 截至 2026 年 7 月。", "Periods use the company's own fiscal year: MSFT 2026FY ends June 2026, NVDA 2027Q2 ends July 2026."],
    key_hint: ["支持 DeepSeek、OpenAI、Claude、Gemini 等 · key 只在本次使用，不保存", "Works with DeepSeek, OpenAI, Claude, Gemini and more · the key is used for this run only and never stored"],
    key_how: ["如何获取 {p} key", "How to get a {p} key"], model_change: ["模型 {m} · 更换", "Model {m} · change"],
    model_default: ["默认：{m}", "Default: {m}"], model_need: ["这个服务商需要填写模型名", "This provider needs a model name"],
    start: ["开始分析", "Start"], err_code: ["请填代码", "Enter a ticker"], err_key: ["请填 API key", "Enter an API key"], err_base: ["请填 Base URL", "Enter the base URL"],
    // progress
    run_title: ["执行进度", "Progress"], run_stop: ["停止", "Stop"], run_edit: ["修改条件", "Edit"],
    run_tokens: ["已用 tokens {t} · 花费 ≈ ${c}", "Tokens {t} · cost ≈ ${c}"],
    s1: ["获取报告", "Fetch report"], s2: ["解析与定位", "Parse and locate"], s3: ["模型抽取", "Model extraction"], s4: ["代码换算与核验", "Convert and check"], s5: ["补问缺失期间", "Ask once more for missing periods"],
    s1_d: ["从 {src} 下载定期报告", "Downloading the filing from {src}"], s2_d: ["共 {p} 页，定位到 {s} 页报表页；行业模板：{t}", "{p} pages, {s} statement pages located; template: {t}"],
    s3_d: ["{m} 照抄数字、单位、页码和原文", "{m} copies numbers, units, pages and quotes"], s4_d: ["C1–C4 + 合理性检查，纯代码", "C1–C4 + consistency checks, code only"],
    s5_d: ["只在缺少应有期间时触发，最多一次", "Only when an expected period is missing; at most once"],
    st_done: ["完成", "Done"], st_now: ["进行中", "Running"], st_wait: ["等待", "Waiting"], st_skip: ["未触发", "Not needed"],
    run_log: ["运行记录", "Run log"], run_log_note: ["时间为本机时间；只记录真实发生的步骤。", "Local time; only steps that actually happened."],
    // failures
    ff_title: ["没有拿到这份报告", "Couldn't fetch this report"], ff_reason: ["原因：{r}", "Reason: {r}"],
    ff_not_found: ["在 {src} 没有找到这一期定期报告。可能是代码或报告期不对，或者这一期还没披露。", "No periodic report for this period was found on {src}. The ticker or period may be wrong, or it isn't published yet."],
    ff_network: ["访问 {src} 失败，可能被限速或拒绝（网站部署在海外服务器上）。", "Couldn't reach {src}; it may be throttling or refusing the server (the site runs overseas)."],
    ff_detail: ["技术信息：{d}", "Technical detail: {d}"],
    ff_retry: ["重新获取", "Try again"], ff_drop: ["把财报 PDF 拖到这里，或点击选择文件", "Drop the filing PDF here, or click to choose"],
    ff_drop_sub: ["上传后从“解析与定位”继续；文件只用于本次分析，解析后删除临时文件。", "Continues from \"parse and locate\"; the file is used for this analysis only and the temp file is deleted after parsing."],
    ff_choose: ["选择 PDF", "Choose PDF"], ff_go: ["用这个 PDF 继续", "Continue with this PDF"],
    faq_t: ["常见问题", "FAQ"],
    faq1_q: ["为什么会下载失败？", "Why can a download fail?"],
    faq1_a: ["网站部署在海外服务器上，巨潮资讯、HKEXnews、东财可能对海外访问限速或拒绝；也可能是这一期报告还没披露，或标题和预期不同。上传 PDF 可以继续。", "The site runs on overseas servers; cninfo, HKEXnews and Eastmoney may throttle or refuse them. The report may also not be published yet, or titled differently than expected. Uploading the PDF continues the run."],
    faq2_q: ["支持扫描版 PDF 吗？", "Are scanned PDFs supported?"],
    faq2_a: ["不支持。取不到文字层的 PDF 无法抽取和核验，会直接提示。", "No. A PDF without a text layer cannot be extracted or checked; you'll see a message."],
    faq3_q: ["上传的文件会怎样处理？", "What happens to an uploaded file?"],
    faq3_a: ["写入服务器临时文件解析后立即删除；文字内容送给你选的模型服务商做抽取（核验页不调用任何模型）。", "It is written to a temp file on the server, parsed, and the file is deleted right away; the text goes to the model provider you chose for extraction (the Verify page calls no model)."],
    scanned: ["这份 PDF 取不到文字（可能是扫描件），无法抽取和核验。", "No text could be read from this PDF (likely a scan); it cannot be extracted or checked."],
    e_key: ["服务商拒绝了这个 key。请检查 key 或换服务商。", "The provider rejected this key. Check the key or switch provider."],
    e_model: ["服务商找不到这个模型名。请检查模型名。", "The provider doesn't recognise this model name."],
    e_base: ["请填写 Base URL。", "Enter the base URL."], e_quota: ["服务商返回余额不足或限流。请稍后再试。", "The provider reports no balance or a rate limit. Try again later."],
    e_general: ["运行出错", "The run failed"], e_detail: ["服务商返回：{m}", "Provider returned: {m}"],
    e_stopped: ["已停止。", "Stopped."], e_again: ["返回修改", "Back to the form"],
    // compare
    c_q: ["对比哪几家公司？", "Which companies should we compare?"],
    c_ccy_hint: ["结果可在原币种和上市地货币之间切换；换算用国家外汇管理局人民币汇率中间价的期末汇率，取不到汇率就不换算。银行没有毛利行，毛利列写“不适用”。",
      "Results switch between reporting and listing currency; conversion uses SAFE RMB central parity at period end, and nothing is converted without a rate. Banks have no gross-profit line (N/A)."],
    c_lead: ["多家公司同一报告期，口径统一的对比表。最多 10 家；服务商和 key 与单家分析共用。", "Several companies, one period, aligned definitions. Up to 10; provider and key are shared with Analyze."],
    c_rows: ["公司", "Companies"], c_add: ["添加一家", "Add a company"], c_run: ["开始对比", "Compare"],
    c_ccy_orig: ["原币种", "As reported"], c_ccy_local: ["上市地货币", "Listing currency"],
    c_fx_none: ["原币种：不换算。", "As reported: no conversion."],
    c_fx_rate: ["{p}：{r}（{src}，{d}，期末汇率）", "{p}: {r} ({src}, {d}, period-end rate)"],
    c_fx_missing: ["汇率缺失，未换算", "Rate missing, not converted"],
    c_na: ["不适用", "N/A"], c_bank_na: ["银行不适用", "N/A for banks"],
    c_col_co: ["公司", "Company"], c_col_status: ["核验状态", "Checks"],
    c_click: ["点格子打开这家公司的完整结果。", "Click a cell to open that company's full result."],
    c_failed: ["没拿到：{r}", "Not fetched: {r}"], c_upload_row: ["上传 PDF", "Upload PDF"],
    c_queued: ["排队中", "Queued"],
    // verify
    v_title: ["核验别的 AI 给的数", "Check figures from any AI"], v_sub: ["不需要 key，不调用任何模型，纯代码检查。", "No key, no model: code-only checks."],
    v_lead: ["上传财报 PDF，粘贴 AI 按通用提示词给出的结果（JSON 或表格）。纯代码检查：C1–C3 + 合理性检查；美股和 A 股填了代码、能取到结构化数据时加 C4。",
      "Upload the filing PDF and paste an AI's answer (JSON or a table). Code-only checks: C1–C3 + consistency; C4 too for US and A-share when a ticker is given and structured data is available."],
    v_pdf: ["原始财报 PDF", "Filing PDF"], v_paste: ["粘贴 AI 的结果", "Paste the AI's answer"],
    v_copy: ["复制通用提示词", "Copy the universal prompt"], v_copied: ["已复制", "Copied"],
    v_copy_fail: ["复制失败，请在下方手动选择复制", "Copy failed; select the text below and copy it"],
    v_howto: ["用法：在任意 AI（GPT、Claude、DeepSeek、豆包等）里上传财报 + 贴提示词 → 把它的回答整段贴回这里核验。",
      "How to use: in any AI (GPT, Claude, DeepSeek, Doubao…) upload the filing and paste the prompt → paste its whole reply back here."],
    v_prompt_eval: ["提示词由评估中的 R3 写法改成：R3 在 DeepSeek 上的留出集严格正确率为 {p}（美股 + A 股，输入为解析文本）；这份通用版本身和其他模型都未经评估。",
      "Adapted from the R3 wording in the evaluation: R3 scored {p} strict accuracy on the DeepSeek holdout (US + A-share, parsed-text input). This universal version itself, and other models, are not evaluated."],
    v_absent: ["AI 标明原文没有：{l}", "The AI says these are not in the report: {l}"],
    v_fmt_json: ["JSON", "JSON"], v_fmt_table: ["表格", "Table"], v_fmt_wait: ["等待输入", "Waiting for input"],
    v_ph: ["粘贴 AI 的回答……\n\n表格示例：\n| 指标 | 数值 | 单位 | 期间 | 页码 | 原文 |\n|---|---|---|---|---|---|\n| 营业收入 | 28,236 | in millions | 单季 | 5 | Total revenues 28,236 22,496 50,623 41,831 |\n\nJSON 示例：\n{\"items\": [{\"field\": \"revenue\", \"raw_value\": \"28,236\", \"raw_unit\": \"in millions\", \"raw_currency\": \"$\", \"period_type\": \"Q\", \"page\": 5, \"quote\": \"Total revenues 28,236 ...\"}]}",
      "Paste the AI's answer…\n\nTable example:\n| Metric | Value | Unit | Period | Page | Quote |\n|---|---|---|---|---|---|\n| Revenue | 28,236 | in millions | Q | 5 | Total revenues 28,236 22,496 50,623 41,831 |\n\nJSON example:\n{\"items\": [{\"field\": \"revenue\", \"raw_value\": \"28,236\", \"raw_unit\": \"in millions\", \"raw_currency\": \"$\", \"period_type\": \"Q\", \"page\": 5, \"quote\": \"Total revenues 28,236 ...\"}]}"],
    v_meta: ["报告信息", "About the filing"], v_code_opt: ["代码（可选，美股 / A 股用于 C4）", "Ticker (optional; enables C4 for US / A-share)"],
    v_tpl: ["行业模板", "Template"], v_tpl_auto: ["自动判定", "Auto"],
    v_run: ["开始核验", "Run checks"], v_need_pdf: ["请上传 PDF", "Upload a PDF"], v_need_text: ["请粘贴结果", "Paste an answer"],
    v_chars: ["{n} 字符", "{n} chars"], v_no_upload_store: ["PDF 写入服务器临时文件解析后立即删除；不发给任何模型服务商。", "The PDF is parsed from a temp file on the server that is deleted right away; nothing is sent to any model provider."],
    v_checks_c4: ["本次检查：C1–C4 + 合理性检查", "Checks run: C1–C4 + consistency"],
    v_checks_noc4_hk: ["本次检查：C1–C3 + 合理性检查；未做 C4（港股没有可靠的结构化数据）", "Checks run: C1–C3 + consistency; no C4 (no reliable structured data for HK)"],
    v_checks_noc4_code: ["本次检查：C1–C3 + 合理性检查；未做 C4（未填代码）", "Checks run: C1–C3 + consistency; no C4 (no ticker given)"],
    v_checks_noc4_data: ["本次检查：C1–C3 + 合理性检查；未做 C4（没取到这一期的结构化数据）", "Checks run: C1–C3 + consistency; no C4 (no structured data for this period)"],
    v_badrows: ["第 {l} 行无法解析，未参与核验", "Rows {l} could not be parsed and were not checked"],
    v_unparsed: ["无法解析的行", "Unparsed rows"], v_again: ["核验另一份", "Check another"],
    v_map_t: ["认不出表头，请对应各列", "Header not recognised: map the columns"], v_map_go: ["按这个对应重新核验", "Re-run with this mapping"],
    role_field: ["指标", "Metric"], role_raw_value: ["数值", "Value"], role_raw_unit: ["单位", "Unit"], role_raw_currency: ["币种", "Currency"],
    role_period_type: ["期间", "Period"], role_page: ["页码", "Page"], role_quote: ["原文", "Quote"], role_none: ["忽略", "Ignore"],
    v_nosource: ["无出处", "No source"],
    // method
    mt_src: ["本页数字全部来自 docs/eval_results.md。", "Every number on this page comes from docs/eval_results.md."],
    mt_toc: ["本页目录", "On this page"], mt_eval: ["评估", "Evaluation"],
    mt_prompt: ["通用提示词", "Universal prompt"],
    mt_prompt_d1: ["核验页可以复制一份通用提示词（中英文两版，在仓库 prompts/ 目录），在任何 AI 里和财报一起使用，再把回答贴回核验页。它要求每个数给出页码和原文整行，原文没有的指标明确写“原文没有”，输出 JSON 加一张可读表格。",
      "The Verify page offers a universal prompt (Chinese and English, in the repository's prompts/ folder) to use with any AI together with the filing; paste the reply back into Verify. It asks for a page and the full source line for every number, an explicit \"not disclosed\" where the report has no such line, and JSON plus a readable table."],
    mt_prompt_d2: ["它由评估中“专业直接问 + 核验层”（R3）的提问改写而来。R3 在 DeepSeek 留出集上的严格正确率为 {p}（美股 + A 股 {n} 条，输入是解析后的文本，不是上传 PDF）。通用版改了输出格式，本身没有单独评估；其他模型（GPT、Claude、豆包等）都未经评估。",
      "It is adapted from the question of the \"direct question + verification\" tier (R3). R3 scored {p} strict accuracy on the DeepSeek holdout (US + A-share, {n} rows, parsed text as input, not an uploaded PDF). The universal version changes the output format and has not been evaluated on its own; other models (GPT, Claude, Doubao…) are not evaluated."],
    mt_lead: ["在 DeepSeek 上，专业写法的直接问严格正确率最高。流水线的价值在于每个数都有页码和原文，可疑的数被标出来，需要人工复核的范围能缩小。本页如实列出三档对比和局限。",
      "On DeepSeek, a carefully worded direct question had the highest strict accuracy. The pipeline's value is that every number has a page and a quote and suspicious numbers are flagged, narrowing what a person must re-check. This page lists the comparison and the limits as measured."],
    mt_main: ["三档对比（冻结版，主结果）", "Three tiers (frozen rules, main result)"],
    mt_hold: ["留出集（修订版规则，40 份美股 + A 股）", "Holdout (revised rules, 40 US + A-share filings)"],
    mt_hold_note: ["修订是看过 eval1 结果之后做的；留出集用于检验修订，跑之前冻结规则、跑完不再改。港股留出集没有评分。核验档（专业直接问 + 核验层）是看过结果后提出的新设计。",
      "Revisions were made after seeing eval1; the holdout tests them, with rules frozen before the run and unchanged after. The HK holdout was not scored. The verified tier (direct question + verification layer) is a design proposed after seeing results."],
    th_tier: ["档", "Tier"], th_strict: ["严格正确", "Strict accuracy"], th_silent: ["静默错误", "Silent errors"], th_work: ["复核工作量", "Review workload"], th_recall: ["标记召回率（含 C4 / 去 C4）", "Flag recall (with / without C4)"],
    tier_ds_simple: ["简单直接问", "Simple direct question"], tier_ds_direct: ["专业直接问", "Expert direct question"],
    tier_ds_pipeline: ["流水线", "Pipeline"], tier_ds_verified: ["专业直接问 + 核验层", "Direct question + verification"],
    tier_fable_direct: ["Fable 直接问", "Fable direct"], tier_fable_pipeline: ["Fable 流水线", "Fable pipeline"],
    silent_def: ["静默错误：给了数但错了，并且没被标出（条数 / 占全部条目）。复核工作量：被标出的条目占比。直接问没有标记机制。",
      "Silent error: a wrong number that was not flagged (count / share of all rows). Review workload: share of rows flagged. Direct questions have no flagging."],
    mt_items: ["{n} 条", "{n} rows"], mt_noflag: ["无标记机制", "No flagging"],
    mt_mk: ["标记召回率分市场", "Flag recall by market"], mt_mk_note: ["美股 + A 股和港股分开展示，不合并成一个数。", "Shown separately for US + A-share and HK, never merged."],
    mt_usa: ["美股 + A 股", "US + A-share"], mt_hk: ["港股", "Hong Kong"], mt_lower: ["较低", "Lower"],
    mt_withc4: ["含 C4", "With C4"], mt_noc4: ["去 C4", "Without C4"],
    mt_usa_why: ["C4 与 SEC XBRL / 东财比对，而评分的标准答案也来自这些数据，所以“含 C4”有循环，同时给出去 C4 的数。", "C4 compares with SEC XBRL / Eastmoney, the same data the answer key comes from, so \"with C4\" is circular; the without-C4 number is shown too."],
    mt_hk_why1: ["港股没有可靠的结构化数据可比，C4 基本不起作用。", "HK has no reliable structured data to compare against, so C4 barely works."],
    mt_hk_why2: ["港股错误主要来自以“仙 / 美分”列示的 EPS。产品已修复（R6），但港股没有留出集，未经验证，也不进入任何评估数字。", "Most HK errors came from EPS reported in cents. The product now fixes this (R6), but HK has no holdout, so it is unvalidated and in no evaluation number."],
    mt_hk_errs: ["{e} 个错误中被标出 {f} 个", "{f} of {e} errors flagged"],
    mt_fable: ["Fable 5.1（9 份小样本，仅作参考）", "Fable 5.1 (9-filing sample, reference only)"],
    mt_fable_note: ["同一 9 份报告、同一组条目上与 DeepSeek 并列；样本太小，不能单独下结论。", "Side by side with DeepSeek on the same 9 filings and rows; too small a sample to conclude on its own."],
    mt_checks: ["核验层检查什么", "What the checks do"],
    c1_t: ["C1 引用在页上", "C1 Quote on page"], c1_d: ["模型给的整行引用能否在它说的那一页（±1 页）找到；允许 PDF 换行造成的拆分。", "Can the model's quoted line be found on the page it named (±1 page), allowing for PDF line breaks?"],
    c2_t: ["C2 数字在页上", "C2 Number on page"], c2_d: ["数字本身是否逐字出现在那一页的文字里；改一位数就会失败。", "Does the number itself appear verbatim in that page's text? Changing one digit fails."],
    c3_t: ["C3 单位与币种", "C3 Unit and currency"], c3_d: ["单位、币种能否解析；每股指标不继承表头的“百万”；仙 / 美分按 0.01 换算。", "Do unit and currency parse? Per-share figures never inherit a table's \"millions\"; cents convert at 0.01."],
    c4_t: ["C4 结构化数据比对", "C4 Structured data"], c4_d: ["美股比 SEC XBRL，A 股比东财，按末位精度容差。港股不做。", "US vs SEC XBRL, A-share vs Eastmoney, within rounding of the last printed digit. Not for HK."],
    sx_t: ["S1–S5 合理性检查", "S1–S5 Consistency"], sx_d: ["毛利 ≤ 营收、归母 ≥ 普通股（有永续债时）、推导值 = 明示值、EPS × 股数 ≈ 净利润、单季 + 上季累计 ≈ 累计。", "Gross ≤ revenue, parent ≥ common (with perpetuals), derived = disclosed, EPS × shares ≈ net income, quarter + prior cumulative ≈ cumulative."],
    mt_limits: ["局限", "Limitations"],
    l1_t: ["不检查指标是否真的存在", "Doesn't check that the metric exists"],
    l1_d: ["核验只能确认数字在原文里、单位对、自洽，不能确认它就是要的指标。人工标“原文没有”的 12 项中，流水线给出数字 3 次，一次也没被标出。", "Checks confirm a number is in the filing and consistent, not that it is the metric asked for. Of 12 items marked \"not in the filing\", the pipeline gave a number 3 times and flagged none."],
    l2_t: ["未标红不等于正确", "Not flagged ≠ correct"], l2_d: ["港股的标记召回率明显更低；美股和 A 股去 C4 后召回率也会下降。", "Flag recall is clearly lower for HK; for US and A-share it drops without C4."],
    l3_t: ["输入是解析文本，不是 PDF", "Input is parsed text, not the PDF"], l3_d: ["所有档拿到的都是同一份解析文字；扫描件无法处理。", "Every tier saw the same parsed text; scanned PDFs can't be handled."],
    l4_t: ["主结论基于 DeepSeek", "Main results are DeepSeek"], l4_d: ["Fable 只有 9 份；港股留出集未评；修订是看过结果后做的。", "Fable has only 9 filings; the HK holdout was not scored; revisions were made after seeing results."],
    mt_links: ["评估设计", "Evaluation design"], mt_links2: ["评估结果", "Evaluation results"],
    gh: ["GitHub", "GitHub"]
  };
  function t(k, v) {
    var row = T[k]; var s = row ? row[S.lang === "zh" ? 0 : 1] : k;
    if (v) Object.keys(v).forEach(function (n) { s = s.split("{" + n + "}").join(v[n]); });
    return s;
  }
  function L(zh, en) { return S.lang === "zh" ? zh : en; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function pct(x, d) { if (x == null) return "—"; var s = (100 * x).toFixed(d == null ? 1 : d); return s.replace(/\.0$/, "") + "%"; }

  // ------------------------------------------------------------------ icons (inline SVG, stroke)
  function ic(name, cls) {
    var p = {
      shield: '<path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
      check: '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
      x: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
      warn: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.01"/>',
      info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>',
      arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>', down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
      ext: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/>',
      left: '<path d="M15 6l-6 6 6 6"/>', right: '<path d="M9 6l6 6-6 6"/>', close: '<path d="M6 6l12 12M18 6L6 18"/>',
      play: '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l5 3.5-5 3.5z"/>', stop: '<circle cx="12" cy="12" r="9"/><rect x="9" y="9" width="6" height="6"/>',
      upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/>',
      file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>', lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
      eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
      eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 6.1A10 10 0 0112 6c6.5 0 10 6 10 6a17 17 0 01-3 3.6M6.6 6.6A17 17 0 002 12s3.5 6 10 6a9.8 9.8 0 004.5-1.1"/>',
      plus: '<path d="M12 5v14M5 12h14"/>', trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
      grid: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
      term: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10l3 2-3 2M13 15h4"/>',
      side: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
      menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
      sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
      moon: '<path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z"/>', code: '<path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/>', refresh: '<path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7"/>'
    }[name] || "";
    return '<svg class="icon ' + (cls || "") + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + p + "</svg>";
  }

  // ------------------------------------------------------------------ formatting
  var CUR_SYM = { USD: "$", CNY: "¥", HKD: "HK$" };
  function scaled(v, ccy, perShare) {
    if (v == null || isNaN(v)) return "—";
    var sym = ccy ? (CUR_SYM[ccy] || ccy + " ") : "", a = Math.abs(v), s = v < 0 ? "-" : "";
    if (perShare) return s + sym + a.toLocaleString("en-US", { maximumFractionDigits: 4 });
    if (S.lang === "zh") {
      if (a >= 1e8) return s + sym + (a / 1e8).toLocaleString("en-US", { maximumFractionDigits: 2 }) + " 亿";
      if (a >= 1e4) return s + sym + (a / 1e4).toLocaleString("en-US", { maximumFractionDigits: 2 }) + " 万";
    } else {
      if (a >= 1e9) return s + sym + (a / 1e9).toLocaleString("en-US", { maximumFractionDigits: 2 }) + "B";
      if (a >= 1e6) return s + sym + (a / 1e6).toLocaleString("en-US", { maximumFractionDigits: 2 }) + "M";
    }
    return s + sym + a.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  function isPerShare(f) { return f === "eps_basic" || f === "eps_basic_per_ads"; }
  function ptype(p) { return T["p_" + p] ? t("p_" + p) : (p || ""); }
  function tplName(x) { return T["t_" + x] ? t("t_" + x) : x; }
  function mtext(x, k) { return (S.lang === "zh" ? x[k + "_zh"] : x[k + "_en"]) || x[k] || ""; }
  function mname(it) { return S.lang === "zh" ? it.name_zh : it.name_en; }
  function stClass(s) { return s === "❌" ? "bad" : s === "⚠️" ? "warn" : s === "✅" ? "ok" : "grey"; }
  function stBadge(s) {
    var k = stClass(s), lab = { bad: t("status_bad"), warn: t("status_warn"), ok: t("status_ok") }[k] || "—";
    var i = { bad: "x", warn: "warn", ok: "check" }[k] || "info";
    return '<span class="badge ' + k + '">' + ic(i, "sm") + esc(lab) + "</span>";
  }
  function stIcon(s) {
    var k = stClass(s);
    return '<span class="tx-' + k + '" title="' + esc({ bad: t("status_bad"), warn: t("status_warn"), ok: t("status_ok") }[k] || "") + '">' + ic({ bad: "x", warn: "warn", ok: "check" }[k] || "info", "sm") + "</span>";
  }
  function srcName(m) { return { us: "SEC EDGAR", a: L("巨潮资讯", "cninfo"), hk: "HKEXnews" }[m] || ""; }
  function mkName(m) { return t("m_" + m); }
  function money(c) { return c == null ? "—" : Number(c).toFixed(c < 0.01 ? 4 : 3); }

  // ------------------------------------------------------------------ render entry
  function onRender(a) {
    S.cfg = a.cfg || S.cfg;
    var prevJob = S.job;
    S.job = a.job || { status: "idle" };
    S.pageView = a.page_view || null;
    if (a.lang && !S._langSet) { S.lang = a.lang; S._langSet = true; }
    if (typeof a.handled === "number") {
      evt = Math.max(evt, a.handled);
      if (bigEventId && a.handled >= bigEventId) { bigEventId = 0; send("ack"); }
    }
    trackLog(prevJob);
    var J = S.job;
    if (J.kind === "single" && J.status === "done" && J.result && !S.saved[J.id]) { S.saved[J.id] = histAdd(J); S.histCur = null; }
    if (S.job.kind && S.job.id !== S.lastJobId && S.job.status !== "idle") {
      S.lastJobId = S.job.id;
      S.view = { single: "analyze", compare: "compare", verify: "verify" }[S.job.kind] || S.view;
      S.drawer = null; S.hist = null; S.panelHidden = false;
    }
    setHeight();
    var sig = JSON.stringify([S.job, S.pageView && S.pageView.n, S.pageView && !!S.pageView.img, S.lang]);
    if (sig !== S.renderedSig || !document.getElementById("app").innerHTML) { S.renderedSig = sig; render(); }
  }

  function trackLog(prev) {
    var j = S.job;
    if (!j || !j.kind || j.kind === "verify") return;
    if (prev && prev.id !== j.id) { S.log = []; S.lastStage = null; }
    var now = new Date().toTimeString().slice(0, 8);
    if (j.stage && j.stage !== S.lastStage && j.status === "running") {
      if (S.lastStage) S.log.push({ t: now, k: "s" + S.lastStage, done: true });
      S.log.push({ t: now, k: "s" + j.stage });
      S.lastStage = j.stage;
    }
    if (j.status !== "running" && S.lastStage) {
      S.log.push({ t: now, k: j.status });
      S.lastStage = null;
    }
  }

  function go(view) {
    S.view = view; S.menu = false; S.drawer = null;
    if (view !== "analyze") S.hist = null;
    S.scrollTop0 = true;
    render();
  }

  function render() {
    if (!S.cfg) return;
    var v = S.view, body = "";
    if (v === "examples") body = examples();
    else if (v === "example") body = example();
    else if (v === "analyze") body = analyze();
    else if (v === "compare") body = compare();
    else if (v === "verify") body = verify();
    else if (v === "method") body = method();
    var pn = panel();
    var html = '<div class="shell' + (S.side ? "" : " side-off") + (S.menu ? " menu-open" : "") + (pn ? " has-panel" : "") + '">' + sidebar() +
      '<div class="scrim side-scrim" data-act="menu"></div><main class="workspace" id="main">' + topbar() + body + "</main>" +
      (pn ? '<div class="scrim panel-scrim" data-act="' + (S.drawer ? "close" : "panel-hide") + '"></div><aside class="panel">' + pn + "</aside>" : "") + "</div>";
    var app = document.getElementById("app");
    var keep = captureFocus(), m = document.getElementById("main"), top = m && !S.scrollTop0 ? m.scrollTop : 0;
    S.scrollTop0 = false;
    app.innerHTML = html;
    document.getElementById("main").scrollTop = top;
    restoreFocus(keep);
    bind();
  }
  function captureFocus() {
    var a = document.activeElement;
    if (!a || !a.id) return null;
    return { id: a.id, s: a.selectionStart, e: a.selectionEnd };
  }
  function restoreFocus(k) {
    if (!k) return;
    var el = document.getElementById(k.id);
    if (!el) return;
    el.focus();
    try { if (k.s != null) el.setSelectionRange(k.s, k.e); } catch (e) { /* selects */ }
  }

  // ------------------------------------------------------------------ chrome
  function sidebar() {
    var tabs = [["analyze", "nav_analyze", "play"], ["compare", "nav_compare", "grid"], ["verify", "nav_verify", "term"], ["method", "nav_method", "info"], ["examples", "nav_examples", "file"]];
    var on = S.view === "example" ? "examples" : S.view;
    var list = histLoad(), p = S.cfg.providers[S.form.provider] || {};
    var recent = list.length ? list.map(function (h) {
      var c = h.counts || {};
      return '<a class="hist' + (S.hist === h.id || (!S.hist && S.view === "analyze" && S.saved[S.job.id] === h.id) ? " on" : "") + '" data-hist="' + esc(h.id) + '"><span class="hn">' + esc(h.name || h.code) + '</span><span class="hm mono">' + esc(h.code) + " · " + esc(h.period) +
        (c["❌"] ? ' · <span class="tx-bad">' + c["❌"] + "</span>" : "") + "</span></a>";
    }).join("") : '<div class="hint" style="padding:4px 10px">' + t("sb_empty") + "</div>";
    return '<aside class="side"><div class="side-top"><a class="brand" data-act="new"><span class="logo">' + ic("shield") + "</span>" + t("brand") + '<span class="ver">v0.1</span></a>' +
      '<button class="icon-btn" data-act="side" aria-label="' + t("sb_collapse") + '" title="' + t("sb_collapse") + '">' + ic("side", "sm") + "</button></div>" +
      '<button class="new-btn" data-act="new">' + ic("plus", "sm") + t("sb_new") + "</button>" +
      '<nav class="side-nav">' + tabs.map(function (x) { return '<a data-go="' + x[0] + '" class="' + (on === x[0] ? "on" : "") + '">' + ic(x[2], "sm") + t(x[1]) + "</a>"; }).join("") + "</nav>" +
      '<div class="side-sec"><div class="side-lbl"><span>' + t("sb_recent") + "</span>" + (list.length ? '<button data-act="hist-clear">' + t("sb_clear") + "</button>" : "") + '</div><div class="side-note">' + ic("lock", "sm") + t("sb_local") + "</div>" + recent + "</div>" +
      '<div class="side-bottom"><a class="keystat" data-go="analyze"><span class="kdot' + (S.form.key ? " on" : "") + '"></span>' + (S.form.key ? t("key_set", { p: esc(p.label || S.form.provider) }) : t("key_none")) + "</a>" +
      '<div class="side-btns"><button class="chip-btn" data-act="theme" aria-label="' + (S.theme === "light" ? t("theme_to_dark") : t("theme_to_light")) + '" title="' + (S.theme === "light" ? t("theme_to_dark") : t("theme_to_light")) + '">' + ic(S.theme === "light" ? "moon" : "sun", "sm") + "</button>" +
      '<button class="chip-btn" data-act="lang"><b>' + (S.lang === "zh" ? "中" : "EN") + "</b> / " + (S.lang === "zh" ? "EN" : "中") + "</button>" +
      '<a class="chip-btn" href="' + esc(S.cfg.github) + '" target="_blank" rel="noopener">' + ic("code", "sm") + "GitHub</a></div></div></aside>";
  }
  function caveat() { return '<p class="caveat">' + t("caveat") + "</p>"; }
  // shown on phones, and on desktop when the sidebar is collapsed
  function topbar() {
    return '<div class="topbar"><button class="icon-btn" data-act="' + (S.side ? "menu" : "side") + '" aria-label="' + t("sb_expand") + '">' + ic("side", "sm") + "</button>" +
      '<a class="brand" data-act="new"><span class="logo">' + ic("shield") + "</span>" + t("brand") + "</a>" +
      '<button class="icon-btn" data-act="new" aria-label="' + t("sb_new") + '" style="margin-left:auto">' + ic("plus", "sm") + "</button></div>";
  }

  // ------------------------------------------------------------------ P1 home
  function exKeys() { return ["us_TSLA", "a_601857", "hk_01810"].filter(function (k) { return S.cfg.examples[k]; }); }
  function coreRows(r) {
    var want = ["revenue", "net_income_parent", "eps_basic"], out = [];
    want.forEach(function (f) {
      var c = r.items.filter(function (i) { return i.field === f && !i.aux && i.value != null; });
      var it = c.find(function (i) { return i.ptype === r.cum; }) || c[0];
      if (it) out.push(it);
    });
    return out;
  }
  function examples() {
    var cards = exKeys().map(function (k) {
      var r = S.cfg.examples[k], d = r.doc;
      var auxBad = r.items.filter(function (i) { return i.aux && i.status === "❌"; })[0];
      return '<div class="ex-card" data-ex="' + k + '"><div class="top"><div><div class="tick">' + esc(d.name) + "</div>" +
        '<div class="faint mono" style="font-size:12px;margin-top:4px">' + esc(d.code) + " · " + mkName(d.market) + " · " + esc(d.title) + "</div></div>" +
        '<span class="pill">' + t("ex_tag") + "</span></div>" +
        "<div>" + coreRows(r).map(function (i) {
          return '<div class="ex-row"><span class="muted">' + esc(mname(i)) + " · " + ptype(i.ptype) + '</span><span class="v">' + esc(i.raw) +
            "<small>" + esc(i.unit || "") + " · p." + esc(i.page) + "</small></span></div>";
        }).join("") + "</div>" +
        (auxBad ? '<div class="ex-flag">' + ic("x", "sm") + " " + esc(mname(auxBad)) + "（" + ptype(auxBad.ptype) + "）：" + esc(S.lang === "zh" ? auxBad.reason_zh : auxBad.reason_en).slice(0, 90) + "</div>" : "") +
        '<div style="display:flex;gap:6px;flex-wrap:wrap">' + ["❌", "⚠️", "✅"].map(function (s) {
          return '<span class="badge ' + stClass(s) + '">' + { bad: t("status_bad"), warn: t("status_warn"), ok: t("status_ok") }[stClass(s)] + " " + r.counts[s] + "</span>";
        }).join("") + "</div>" +
        '<button class="btn ghost sm" style="width:100%">' + t("ex_open") + " " + ic("arrow", "sm") + "</button></div>";
    }).join("");
    return '<div class="wrap pt"><h1 class="ptitle">' + t("ex_title") + '</h1><p class="hint" style="max-width:760px;margin:6px 0 0">' + t("ex_note") + "</p>" +
      '<div class="grid3" style="margin-top:24px">' + cards + "</div></div>";
  }
  // former home page, now the lower part of the analyze form page
  // the former home page, now the top of the method page
  function about() {
    var ev = S.cfg.eval, h = ev.holdout.tiers, p = h.ds_pipeline;
    return '<section class="msec" id="m-about"><h2>' + t("about_eyebrow") + '</h2><p class="lead">' + t("hero_sub") + "</p>" +
      '<div class="steps3"><div><div class="n">01</div><h3>' + t("how1_t") + "</h3><p>" + t("how1_d") + '</p></div><div><div class="n">02</div><h3>' + t("how2_t") + "</h3><p>" + t("how2_d") + '</p></div><div><div class="n">03</div><h3>' + t("how3_t") + "</h3><p>" + t("how3_d") + "</p></div></div></section>" +
      '<section class="msec" id="m-summary"><div class="card" style="padding:32px"><div class="section-head"><div><div class="eyebrow">' + esc(L(ev.holdout.label_zh, ev.holdout.label_en)) + "</div><h2>" + t("eval_title") + "</h2></div></div>" +
      '<div class="grid3"><div><div class="big ok">' + pct(p.strict_acc) + '</div><div class="kpi-cap">' + t("eval_strict") + '</div></div>' +
      '<div><div class="big">' + pct(p.workload) + '</div><div class="kpi-cap">' + t("eval_work") + "</div></div>" +
      '<div><div class="big">' + p.silent + '<span style="font-size:22px;color:var(--muted)"> / ' + p.items + '</span></div><div class="kpi-cap">' + t("eval_silent") + '</div><div class="hint">' + (function () { var hk = ev.recall_by_market.hk, e = hk.errors, u = e - Math.round((hk.recall || 0) * e);
        return L("美股 + A 股留出集；港股 " + e + " 个错误中 " + u + ' 个未被标出，见<a class="link" data-toc="m-mk">下文分市场的召回率</a>',
                 "US + A-share holdout; in HK, " + u + " of " + e + ' errors were not flagged; see <a class="link" data-toc="m-mk">flag recall by market</a> below'); })() + "</div></div></div>" +
      '<p class="src">' + t("eval_note", { d: pct(h.ds_direct.strict_acc) }) + "</p></div></section>";
  }


  // ------------------------------------------------------------------ result component (R0 / R1 / R2)
  function result(r, src) {
    var d = r.doc, c = r.counts;
    var core = r.items.filter(function (i) { return !i.aux; }), aux = r.items.filter(function (i) { return i.aux; });
    var head = '<div class="r0"><div><div class="eyebrow">' + (r.example ? t("ex_tag") : r.uploaded ? t("r_uploaded") : srcName(d.market)) + "</div>" +
      "<h1>" + esc(d.name) + '</h1><div class="tags"><span class="pill">' + esc(d.code) + '</span><span class="pill">' + esc(d.doc_kind || "") + '</span><span class="pill">' + mkName(d.market) + '</span><span class="pill">' + t("r_template") + "：" + tplName(r.template) + "</span></div>" +
      '<div class="meta"><span>' + t("r_end") + " <b>" + esc(d.period_end) + "</b></span><span>" + esc(d.title) + "</span><span>" + t("r_pages", { a: "<b>" + r.pages_total + "</b>", b: "<b>" + r.pages_sent + "</b>" }) + "</span>" +
      (r.cost != null ? "<span>" + t("r_cost", { c: money(r.cost) }) + "</span>" : "") + "</div></div>" +
      '<div style="display:flex;gap:10px;flex-wrap:wrap">' + (d.url ? '<a class="btn ghost sm" href="' + esc(d.url) + '" target="_blank" rel="noopener">' + t("r_source") + " " + ic("ext", "sm") + "</a>" : "") +
      '<button class="btn ghost sm" data-act="csv">' + t("r_export_csv") + '</button><button class="btn ghost sm" data-act="json">' + t("r_export_json") + "</button></div></div>";
    var sums = '<div class="sumcards">' + [["bad", "❌", "x"], ["warn", "⚠️", "warn"], ["ok", "✅", "check"]].map(function (x) {
      return '<div class="sumcard ' + x[0] + '"><div class="ic">' + ic(x[2]) + '</div><div><div class="lab">' + t("status_" + x[0]) + '</div><div class="num">' + c[x[1]] + "</div></div></div>";
    }).join("") + "</div>";
    var fu = r.followup && r.followup.asked && r.followup.asked.length ? r.items.filter(function (i) { return i.category === "漏抽"; }).length : 0;
    var table = '<div class="tbl-card"><div class="tbl-head"><div><h2>' + t("r_core") + '</h2><div class="hint">' + t("r_core_sub") + "</div></div>" +
      (fu ? '<span class="badge warn">' + t("r_followup", { n: fu }) + "</span>" : "") + "</div>" + rtable(core, src) +
      (aux.length ? '<button class="aux-toggle" data-act="aux"><span><b style="color:var(--text)">' + t("r_aux") + "</b> · " + t("r_aux_sub") + (r.aux_bad ? ' · <span class="tx-bad">' + t("r_aux_bad", { n: r.aux_bad }) + "</span>" : "") + "</span><span>" + (S.auxOpen ? t("r_less") : t("r_more")) + "</span></button>" +
        (S.auxOpen ? rtable(aux, src) : "") : "") + "</div>" + caveat();
    var m = (r.metrics || []).length ? '<section class="section"><div class="section-head"><div><h2 style="font-size:22px">' + t("r_metrics") + '</h2><div class="hint">' + t("r_metrics_sub") + '</div></div></div><div class="metric-grid">' +
      r.metrics.map(function (x) {
        return '<div class="metric"><div style="display:flex;justify-content:space-between;gap:8px"><span class="lbl" style="letter-spacing:.02em">' + esc(mtext(x, "name")) + "</span>" + stBadge(x.status) + '</div><div class="v">' + esc(x.raw) + "<small>" + esc(x.unit || "") + '</small></div><div class="hint">' + esc(mtext(x, "rationale")) + "</div>" +
          (x.page ? '<a class="pg" data-page="' + x.page + '" data-src="' + src + '">p.' + x.page + " " + ic("ext", "sm") + "</a>" : "") + "</div>";
      }).join("") + "</div></section>" : "";
    return head + sums + table + m;
  }
  function rtable(items, src) {
    return '<div class="scrollx"><table class="res"><thead><tr><th>' + t("col_status") + "</th><th>" + t("col_metric") + '</th><th style="text-align:right">' + t("col_value") + "</th><th>" + t("col_period") + "</th><th>" + t("col_page") + "</th><th>" + t("col_quote") + "</th></tr></thead><tbody>" +
      items.map(function (it, k) {
        var id = it.field + "_" + it.ptype, reason = S.lang === "zh" ? it.reason_zh : it.reason_en;
        var val = it.value == null ? '<span class="faint">' + t("r_notfound") + "</span>" :
          '<div class="main">' + esc(it.raw) + '</div><div class="conv">' + esc(it.unit || "") + " → " + scaled(it.value, it.currency, isPerShare(it.field)) + "</div>";
        var comps = it.derived && it.components.length ? '<button class="more" data-comp="' + id + '">' + t("r_components") + " " + (S.openComps[id] ? "▴" : "▾") + "</button>" +
          (S.openComps[id] ? '<div class="comps">' + it.components.map(function (c) {
            return "<div><span>" + esc(c.name) + " " + (c.ok ? '<span class="tx-ok">✓</span>' : '<span class="tx-bad">✕</span>') + '</span><span class="mono">' + esc(c.raw) + " " + (c.page ? '<a class="pg" data-page="' + c.page + '" data-src="' + src + '">p.' + c.page + "</a>" : "") + "</span></div>";
          }).join("") + "</div>" : "") : "";
        return '<tr class="' + (it.status === "❌" ? "is-bad" : "") + '"><td>' + stBadge(it.status) + "</td>" +
          '<td><div class="mname">' + esc(mname(it)) + (it.derived ? ' <span class="pill" style="height:20px">' + t("r_derived") + "</span>" : "") + "<small>" + esc(S.lang === "zh" ? it.name_en : it.name_zh) + "</small></div>" +
          (reason ? '<div class="reason ' + stClass(it.status) + '">' + esc(reason) + "</div>" : "") + comps + "</td>" +
          '<td class="num">' + val + "</td>" +
          '<td><span class="mono" style="font-size:12.5px">' + ptype(it.ptype) + '</span><div class="faint mono" style="font-size:11px">' + esc(it.period_end || "") + "</div></td>" +
          "<td>" + (it.page ? '<a class="pg" data-page="' + it.page + '" data-src="' + src + '" data-item="' + id + '">p.' + it.page + " " + ic("ext", "sm") + "</a>" : '<span class="faint">—</span>') + "</td>" +
          "<td>" + (it.quote ? '<div class="quote' + (S.openQuotes[id] ? " open" : "") + '">' + esc(it.quote) + "</div>" + (it.quote.length > 90 ? '<button class="more" data-quote="' + id + '">' + (S.openQuotes[id] ? t("r_less") : t("r_more")) + "</button>" : "") : '<span class="faint">—</span>') + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }
  function curResult(src) {
    if (src === "example") return S.cfg.examples[S.example];
    if (src === "hist") { var h = histGet(S.hist); return h && h.result; }
    if (src === "job") return S.job.result;
    if (src && src.indexOf("cmp") === 0) { var r = S.job.rows && S.job.rows[+src.slice(3)]; return r && r.result; }
    return null;
  }

  // drawer
  function drawer() {
    var D = S.drawer;
    if (!D) return "";
    var r = curResult(D.src);
    if (!r) return "";
    var it = D.item ? r.items.find(function (i) { return i.field + "_" + i.ptype === D.item; }) : null;
    var text = r.pages && r.pages[String(D.n)], img = null, loading = false;
    if (D.src === "job" && S.pageView && S.pageView.n === D.n) { text = S.pageView.text || text; img = S.pageView.img; }
    else if (D.src === "job") loading = true;
    var avail = Object.keys(r.pages || {}).map(Number).sort(function (a, b) { return a - b; });
    var live = D.src === "job";
    var prev = live ? (D.n > 1 ? D.n - 1 : null) : avail.filter(function (n) { return n < D.n; }).pop();
    var next = live ? (D.n < r.pages_total ? D.n + 1 : null) : avail.filter(function (n) { return n > D.n; })[0];
    var hl = it ? it.raw : null;
    var focus = it ? '<div class="focus"><div class="row">' + stBadge(it.status) + '<b style="font-size:16px">' + esc(mname(it)) + '</b><span class="mono muted">' + ptype(it.ptype) + '</span><span class="mono" style="margin-left:auto;font-size:18px;font-weight:650">' + esc(it.raw) + " <small class='faint'>" + esc(it.unit || "") + "</small></span></div>" +
      ((S.lang === "zh" ? it.reason_zh : it.reason_en) ? '<div class="reason ' + stClass(it.status) + '">' + esc(S.lang === "zh" ? it.reason_zh : it.reason_en) + "</div>" : "") +
      (it.bench && it.bench.value != null ? '<div class="hint" style="margin-top:6px">' + t("r_bench") + "：" + esc(it.bench.source || "") + " " + esc(it.bench.field || "") + " = " + Number(it.bench.value).toLocaleString("en-US") + "</div>" : "") + "</div>" : "";
    return '<div class="dh"><span class="round">' + ic("file") + "</span><div><h3>" + t("d_title") + '</h3><div class="hint">' + esc(D.src === "job" && S.job.kind === "verify" && S.ver.pdfName ? S.ver.pdfName : r.doc.name + " · " + r.doc.title) + "</div></div>" +
      '<div class="pager"><button data-dpage="' + (prev || "") + '"' + (prev ? "" : " disabled") + ">" + ic("left", "sm") + "</button><span>" + t("d_page", { n: D.n, t: r.pages_total || "?" }) + '</span><button data-dpage="' + (next || "") + '"' + (next ? "" : " disabled") + ">" + ic("right", "sm") + "</button></div>" +
      (r.doc.url ? '<a class="round" href="' + esc(r.doc.url) + '" target="_blank" rel="noopener" title="' + t("d_open") + '">' + ic("ext", "sm") + "</a>" : "") +
      '<button class="round" data-act="close" aria-label="close">' + ic("close", "sm") + "</button></div>" +
      '<div class="db">' + focus + (img ? '<img class="pageimg" alt="page ' + D.n + '" src="data:image/png;base64,' + img + '">' : "") +
      (text ? '<div class="pagetext">' + highlight(text, hl, it && it.status === "❌") + "</div>" : '<div class="hint">' + (loading ? t("d_loading") : "—") + "</div>") +
      (!live && text ? '<div class="hint">' + t("d_textonly") + "</div>" : "") + "</div>";
  }
  function highlight(text, raw, bad) {
    var h = esc(text);
    if (!raw) return h;
    var digits = String(raw).replace(/[^\d.]/g, "");
    if (!digits) return h;
    var pat = digits.split("").map(function (ch) { return ch === "." ? "\\." : ch; }).join("[,\\s]?");
    try {
      return h.replace(new RegExp("(^|[^\\d.])(" + pat + ")(?![\\d])", "g"), function (m, a, b) { return a + '<mark class="' + (bad ? "bad" : "") + '">' + b + "</mark>"; });
    } catch (e) { return h; }
  }

  function example() {
    var r = S.cfg.examples[S.example];
    if (!r) { S.view = "examples"; return examples(); }
    return '<div class="wrap"><div class="runbar"><button class="btn ghost sm" data-go="examples">' + ic("left", "sm") + t("ex_back") + '</button><span class="hint">' + t("ex_note") + "</span></div>" + result(r, "example") + "</div>";
  }

  // ------------------------------------------------------------------ P2 analyze
  var PERIODS = ["2027Q2", "2027Q1", "2026FY", "2026Q3", "2026H1", "2026Q2", "2026Q1", "2025FY", "2025Q3", "2025H1", "2025Q2", "2025Q1", "2024FY"];
  function periodLabel(p) {
    var part = p.slice(4), y = p.slice(0, 4);
    var zh = { FY: "年报", H1: "中期报告", Q1: "一季度", Q2: "二季度（累计半年）", Q3: "三季度（累计九个月）" }[part];
    var en = { FY: "annual", H1: "interim", Q1: "Q1", Q2: "Q2 (six months)", Q3: "Q3 (nine months)" }[part];
    return y + part + " · " + L(zh, en);
  }
  function provOpts(sel) {
    return Object.keys(S.cfg.providers).map(function (k) {
      return '<option value="' + k + '"' + (k === sel ? " selected" : "") + ">" + esc(S.cfg.providers[k].label) + (k === "deepseek" ? L("（默认）", " (default)") : "") + "</option>";
    }).join("");
  }
  function formErrors() {
    var f = S.form, p = S.cfg.providers[f.provider] || {}, e = {};
    if (!f.code.trim()) e.code = t("err_code");
    if (!f.key.trim()) e.key = t("err_key");
    if (!p.base && f.provider === "custom" && !f.base_url.trim()) e.base = t("err_base");
    if (!p.model && !f.model.trim()) e.model = t("model_need");
    return e;
  }
  // provider + key on one row; model (and base URL) only when the provider has no default, or on request
  function keyFields(f) {
    var p = S.cfg.providers[f.provider] || {}, e = S.touched ? formErrors() : {};
    var showModel = !p.model || f.provider === "custom" || S.provOpen || e.model || e.base;
    return '<div class="keyrow"><div class="field"><label>' + t("f_provider") + '</label><select class="input" id="f-provider">' + provOpts(f.provider) + "</select></div>" +
      '<div class="field"><label>' + t("f_key") + '</label><div class="pw"><input class="input' + (e.key ? " err" : "") + '" id="f-key" type="' + (f.showKey ? "text" : "password") + '" value="' + esc(f.key) + '" placeholder="sk-…" autocomplete="off"><button data-act="eye" aria-label="show key">' + ic(f.showKey ? "eyeoff" : "eye") + '</button></div><div class="errtx">' + (e.key || "") + "</div></div></div>" +
      (showModel ? '<div class="keyrow"><div class="field"><label>' + t("f_model") + '</label><input class="input' + (e.model ? " err" : "") + '" id="f-model" value="' + esc(f.model) + '" placeholder="' + esc(p.model ? t("model_default", { m: p.model }) : t("model_need")) + '"><div class="errtx">' + (e.model || "") + "</div></div>" +
        (f.provider === "custom" ? '<div class="field"><label>' + t("f_base") + '</label><input class="input' + (e.base ? " err" : "") + '" id="f-base" value="' + esc(f.base_url) + '" placeholder="https://…/v1"><div class="errtx">' + (e.base || "") + "</div></div>" : "<div></div>") + "</div>" : "") +
      '<div class="keyhint"><span>' + ic("lock", "sm") + t("key_hint") + "</span><span class=\"kh-r\">" +
      (p.model && !showModel ? '<button class="link" data-act="prov">' + t("model_change", { m: esc(p.model) }) + "</button>" : "") +
      (p.key_url ? '<a class="link" href="' + esc(p.key_url) + '" target="_blank" rel="noopener">' + t("key_how", { p: esc(p.label) }) + " ↗</a>" : "") + "</span></div>";
  }
  function analyze() {
    var j = S.job;
    if (S.hist) {
      var h = histGet(S.hist);
      if (h) return '<div class="wrap"><div class="runbar"><span style="width:9px;height:9px;border-radius:50%;background:var(--faint)"></span><div class="what">' + mkName(h.market) + " · " + esc(h.code) + " · " + esc(h.period) + '</div><span class="hint">' + t("h_saved", { t: new Date(h.ts).toLocaleString(S.lang === "zh" ? "zh-CN" : "en-US") }) + "</span></div>" + result(h.result, "hist") + "</div>";
      S.hist = null;
    }
    if (j.kind === "single" && j.status !== "idle") {
      if (j.status === "running") return '<div class="wrap">' + runbar(false) + '<div class="card run-wait"><span class="live"></span><p>' + t("run_main") + "</p>" + (S.panelHidden ? '<button class="btn ghost sm" data-act="panel-show">' + t("run_show") + "</button>" : "") + "</div></div>";
      if (j.status === "fetch_failed") return '<div class="wrap">' + fetchFailed() + "</div>";
      if (j.status === "error" || j.status === "stopped") return '<div class="wrap">' + runError() + "</div>";
      if (j.status === "done" && j.result) return '<div class="wrap">' + runbar(true) + result(j.result, "job") + "</div>";
    }
    var f = S.form, e = S.touched ? formErrors() : {};
    return '<div class="stage"><h1 class="stage-title">' + t("a_q") + "</h1>" +
      '<div class="card stage-card"><div class="field"><label>' + t("f_market") + '</label><div class="seg">' + ["us", "hk", "a"].map(function (m) { return '<button data-market="' + m + '" class="' + (f.market === m ? "on" : "") + '">' + mkName(m) + "</button>"; }).join("") + "</div></div>" +
      '<div class="grid2"><div class="field"><label>' + t("f_code") + '</label><input class="input' + (e.code ? " err" : "") + '" id="f-code" value="' + esc(f.code) + '" placeholder="' + t("ph_" + f.market) + '" autocomplete="off"><div class="errtx">' + (e.code || "") + "</div></div>" +
      '<div class="field"><label>' + t("f_period") + '<span class="faint" title="' + esc(t("period_help")) + '">?</span></label><select class="input" id="f-period">' + PERIODS.map(function (x) { return '<option value="' + x + '"' + (x === f.period ? " selected" : "") + ">" + periodLabel(x) + "</option>"; }).join("") + "</select></div></div>" +
      keyFields(f) +
      '<button class="btn primary block" data-act="start"' + (S.touched && Object.keys(formErrors()).length ? " disabled" : "") + ">" + ic("play") + t("start") + "</button>" +
      '<div class="hint">' + t("period_help") + "</div></div>" +
      '<div class="stage-links"><a class="stage-link" data-go="examples">' + t("nokey_cta") + ' →</a><a class="stage-link" data-go="verify">' + t("verify_cta") + " →</a></div></div>";
  }
  function runbar(done) {
    var j = S.job, q = j.query || {}, m = j.meta || {};
    var dot = j.status === "done" ? "var(--ok)" : "var(--bad)";
    return '<div class="runbar"><span class="' + (done ? "" : "live") + '" style="' + (done ? "width:9px;height:9px;border-radius:50%;background:" + dot : "") + '"></span><div class="what">' + mkName(q.market || "us") + " · " + esc((q.code || "").toUpperCase()) + (m.name && m.name !== q.code ? "（" + esc(m.name) + "）" : "") + " · " + esc(q.period || "") + " · " + esc((S.cfg.providers[q.provider] || {}).label || q.provider || "") + "</div>" +
      '<span class="pill">' + t("run_tokens", { t: (j.tokens || 0).toLocaleString("en-US"), c: money(j.cost || 0) }) + "</span>" +
      '<div style="margin-left:auto;display:flex;gap:10px">' + (done ? '<button class="btn ghost sm" data-act="reset">' + t("run_edit") + "</button>" : '<button class="btn ghost sm" data-act="stop">' + ic("stop", "sm") + t("run_stop") + "</button>") + "</div></div>";
  }
  function panel() {
    if (S.drawer) return drawer();
    var j = S.job;
    if (S.view === "analyze" && !S.hist && j.kind === "single" && j.status === "running" && !S.panelHidden) return progressPanel();
    return "";
  }
  function progressPanel() {
    var j = S.job, q = j.query || {}, m = j.meta || {}, st = j.stage || 1;
    var prov = (S.cfg.providers[q.provider] || {}).label || q.provider;
    var steps = [1, 2, 3, 4, 5].map(function (n) {
      var state = n < st ? "done" : n === st ? "now" : "wait";
      if (n === 5 && st < 5 && st >= 4) state = "wait";
      var d = { 1: t("s1_d", { src: srcName(q.market) }), 2: m.pages ? t("s2_d", { p: m.pages, s: m.selected, t: tplName(m.template) }) : "", 3: t("s3_d", { m: prov + (q.model ? " / " + q.model : "") }), 4: t("s4_d"), 5: t("s5_d") }[n];
      var lab = { done: t("st_done"), now: t("st_now"), wait: n === 5 ? t("st_skip") : t("st_wait") }[state];
      return '<div class="step ' + state + '"><span class="ring">' + (state === "done" ? ic("check") : state === "now" ? "" : '<span class="mono">' + n + "</span>") + "</span><div><h4>" + n + ". " + t("s" + n) + "</h4><p>" + esc(d) + "</p></div>" +
        '<span class="st badge ' + (state === "done" || state === "now" ? "ok" : "grey") + '">' + lab + "</span></div>";
    }).join("");
    // the checks run in stage 4; C4 is never run for HK
    var cst = st < 4 ? "wait" : st === 4 ? "now" : "done";
    var checks = ["c1", "c2", "c3", "c4", "sx"].map(function (k) {
      var skip = k === "c4" && q.market === "hk", state = skip ? "skip" : cst;
      var lab = { done: t("st_done"), now: t("st_now"), wait: t("st_wait"), skip: t("st_skip") }[state];
      return '<div class="chk ' + state + '"><div><h4>' + t(k + "_t") + "</h4><p>" + (skip ? t("pn_hk_c4") : t(k + "_d")) + '</p></div><span class="badge ' + (state === "done" || state === "now" ? "ok" : "grey") + '">' + lab + "</span></div>";
    }).join("");
    var pctv = Math.min(100, Math.round(((st - 1) / 4) * 100));
    var log = S.log.map(function (x) { return "<div>[" + x.t + "] <b>" + esc(T[x.k] ? t(x.k) : x.k) + "</b>" + (x.done ? " · " + t("st_done") : "") + "</div>"; }).join("");
    return '<div class="dh"><div><h3>' + t("run_title") + '</h3><div class="hint">' + mkName(q.market || "us") + " · " + esc((q.code || "").toUpperCase()) + " · " + esc(q.period || "") + '</div></div><span class="pill" style="margin-left:auto">' + st + " / 5</span>" +
      '<button class="round" data-act="panel-hide" aria-label="close">' + ic("close", "sm") + "</button></div>" +
      '<div class="db"><div class="progress"><div style="width:' + pctv + '%"></div></div><div class="steps">' + steps + "</div>" +
      '<div class="lbl">' + t("pn_checks") + '</div><div class="chks">' + checks + "</div>" +
      '<div class="lbl">' + t("run_log") + '</div><div class="log">' + log + '</div><p class="hint">' + t("run_log_note") + "</p></div>";
  }
  function fetchFailed() {
    var j = S.job, q = j.query || {};
    if (j.error_kind === "scanned") return runbar(true) + '<div class="alert"><span class="ic">' + ic("x") + "</span><div><h3>" + t("scanned") + '</h3></div><button class="btn ghost sm act" data-act="reset">' + t("e_again") + "</button></div>";
    var up = S.upload;
    return '<div class="alert"><span class="ic">' + ic("x") + "</span><div><h3>" + t("ff_title") + "：" + mkName(q.market) + " " + esc(q.code) + " " + esc(q.period) + "</h3><p>" + (function () { var e = String(j.error || ""), k = e.split("|")[0], d = e.indexOf("|") >= 0 ? e.slice(e.indexOf("|") + 1) : e; return (T["ff_" + k] ? t("ff_" + k, { src: srcName(q.market) }) : t("ff_reason", { r: esc(d) })) + '<br><span class="mono faint" style="font-size:11.5px">' + t("ff_detail", { d: esc(d) }) + "</span>"; })() + '</p></div><button class="btn ghost sm act" data-act="retry">' + ic("refresh", "sm") + t("ff_retry") + "</button></div>" +
      '<div class="split" style="margin-top:24px"><div class="card"><div class="drop" id="drop1">' + '<div class="circle">' + ic("upload") + "</div><h3 style='font-size:20px'>" + (up ? esc(up.name) : t("ff_drop")) + '</h3><p class="hint" style="max-width:460px;margin:8px auto 18px">' + t("ff_drop_sub") + "</p>" +
      '<input type="file" id="file1" accept="application/pdf" class="hidden"><div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap"><button class="btn ghost" data-act="pick1">' + ic("file", "sm") + t("ff_choose") + '</button><button class="btn primary" data-act="upload"' + (up ? "" : " disabled") + ">" + t("ff_go") + "</button></div></div>" +
      (S.form.key ? "" : '<div style="margin-top:20px">' + keyFields(S.form) + "</div>") + "</div>" +
      '<div class="card faq"><h2 style="margin-bottom:10px">' + t("faq_t") + "</h2>" + [1, 2, 3].map(function (n) { return "<details" + (n === 1 ? " open" : "") + "><summary>" + t("faq" + n + "_q") + "<span>▾</span></summary><p>" + t("faq" + n + "_a") + "</p></details>"; }).join("") + "</div></div>";
  }
  function runError() {
    var j = S.job;
    var title = j.status === "stopped" ? t("e_stopped") : T["e_" + j.error_kind] ? t("e_" + j.error_kind) : t("e_general");
    return runbar(true) + '<div class="alert"><span class="ic">' + ic(j.status === "stopped" ? "info" : "x") + "</span><div><h3>" + title + "</h3>" + (j.error ? "<p class='mono' style='font-size:12px'>" + t("e_detail", { m: esc(j.error) }) + "</p>" : "") +
      '</div><button class="btn primary sm act" data-act="reset">' + t("e_again") + "</button></div>";
  }

  // ------------------------------------------------------------------ P3 compare
  var CMP_FIELDS = ["revenue", "net_income_parent", "gross_profit", "operating_cash_flow", "eps_basic"];
  var CMP_NAMES = { revenue: ["营业收入", "Revenue"], net_income_parent: ["归母净利润", "Net income attrib."], gross_profit: ["毛利", "Gross profit"], operating_cash_flow: ["经营现金流", "Operating cash flow"], eps_basic: ["基本 EPS", "Basic EPS"] };
  function compare() {
    var j = S.job, c = S.cmp;
    if (j.kind === "compare" && j.rows && j.status !== "idle") {
      if (c.open != null) {
        var rr = j.rows[c.open];
        return '<div class="wrap"><div class="runbar"><button class="btn ghost sm" data-act="cmp-back">' + ic("left", "sm") + L("返回对比表", "Back to comparison") + "</button></div>" + (rr && rr.result ? result(rr.result, "cmp" + c.open) : "") + "</div>";
      }
      return '<div class="wrap pt">' + cmpTable() + "</div>";
    }
    var e = S.touched ? formErrors() : {};
    var rows = c.rows.map(function (r, i) {
      return '<div class="rowedit"><select class="input" data-cmarket="' + i + '">' + ["us", "a", "hk"].map(function (m) { return '<option value="' + m + '"' + (r.market === m ? " selected" : "") + ">" + mkName(m) + "</option>"; }).join("") + "</select>" +
        '<input class="input" id="c-code-' + i + '" data-ccode="' + i + '" value="' + esc(r.code) + '" placeholder="' + t("ph_" + r.market) + '"><button class="round" data-cdel="' + i + '" aria-label="remove">' + ic("trash", "sm") + "</button></div>";
    }).join("");
    var ok = c.rows.some(function (r) { return r.code.trim(); }) && !e.key && !e.model && !e.base;
    return '<div class="stage"><h1 class="stage-title">' + t("c_q") + "</h1>" +
      '<div class="card stage-card"><div class="field"><label>' + t("c_rows") + '</label><div style="display:flex;flex-direction:column;gap:10px">' + rows + "</div>" +
      (c.rows.length < 10 ? '<button class="btn ghost sm" style="align-self:flex-start" data-act="cadd">' + ic("plus", "sm") + t("c_add") + "</button>" : "") + "</div>" +
      '<div class="field"><label>' + t("f_period") + '</label><select class="input" id="c-period">' + PERIODS.map(function (x) { return '<option value="' + x + '"' + (x === c.period ? " selected" : "") + ">" + periodLabel(x) + "</option>"; }).join("") + "</select></div>" +
      keyFields(S.form) +
      '<button class="btn primary block" data-act="cmp-run"' + (S.touched && !ok ? " disabled" : "") + ">" + ic("play") + t("c_run") + "</button>" +
      '<div class="hint">' + t("c_lead") + " " + t("c_ccy_hint") + "</div></div></div>";
  }
  function fxFor(row, it) {
    var r = row.rates && it.currency ? row.rates[it.currency] : null;
    return r;
  }
  function cmpTable() {
    var j = S.job, c = S.cmp, running = j.status === "running";
    var pairs = {};
    var body = j.rows.map(function (row, i) {
      var name = '<div class="co"><span class="av">' + esc(row.name && !/^\d/.test(row.name) ? row.name.slice(0, 1) : mkName(row.market).slice(0, 1)) + '</span><div><b>' + esc(row.name || row.code) + '</b><div class="faint mono" style="font-size:11px">' + esc(row.code) + " · " + mkName(row.market) + (row.template ? " · " + tplName(row.template) : "") + "</div></div></div>";
      if (row.status !== "done") {
        var msg = row.status === "running" ? '<span class="pill"><span class="live" style="width:7px;height:7px"></span>' + t("st_now") + "</span>" : row.status === "queued" ? '<span class="pill">' + t("c_queued") + "</span>" :
          row.status === "fetch_failed" ? '<span class="tx-bad">' + t("c_failed", { r: esc(String(row.error || "").split("|").pop()) }) + '</span> <input type="file" accept="application/pdf" class="hidden" id="cf-' + i + '"><button class="btn ghost sm" data-cup="' + i + '">' + ic("upload", "sm") + t("c_upload_row") + "</button>" :
          row.status === "skipped" ? '<span class="faint">' + L("未运行（同一个 key 已被拒绝）", "Not run (the same key was rejected)") + "</span>" :
          '<span class="tx-bad">' + esc(row.status === "stopped" ? t("e_stopped") : (T["e_" + row.error_kind] ? t("e_" + row.error_kind) : t("e_general") + " " + (row.error || ""))) + "</span>";
        return "<tr><td>" + name + '</td><td colspan="6">' + msg + "</td></tr>";
      }
      var cells = CMP_FIELDS.map(function (f) {
        var it = row.cells[f];
        if (!it) return '<td class="faint">' + (f === "gross_profit" && row.template !== "general" ? t("c_bank_na") : "—") + "</td>";
        var conv = c.ccy === "local" && it.currency && it.currency !== row.listing;
        var fx = conv ? fxFor(row, it) : null, v = it.value, ccy = it.currency, sub = esc(it.raw) + " " + esc(it.unit || "");
        if (conv && fx) { v = it.value * fx.rate; ccy = row.listing; pairs[it.currency + "→" + row.listing] = fx; sub = L("原 ", "orig ") + scaled(it.value, it.currency, isPerShare(f)) + " × " + fx.rate.toFixed(4); }
        else if (conv) sub = '<span class="tx-warn">' + t("c_fx_missing") + "</span>";
        return '<td class="cell" data-copen="' + i + '"><div class="v">' + scaled(v, ccy, isPerShare(f)) + " " + stIcon(it.status) + '</div><div class="sub">' + sub + "</div></td>";
      }).join("");
      var cnt = row.counts || {};
      return "<tr><td>" + name + "</td>" + cells + '<td><div style="display:flex;gap:4px;flex-wrap:wrap"><span class="badge bad">' + (cnt["❌"] || 0) + '</span><span class="badge warn">' + (cnt["⚠️"] || 0) + '</span><span class="badge ok">' + (cnt["✅"] || 0) + "</span></div></td></tr>";
    }).join("");
    var fxs = Object.keys(pairs).map(function (p) { var x = pairs[p]; return t("c_fx_rate", { p: "<b>" + p + "</b>", r: "<b>" + x.rate.toFixed(4) + "</b>", src: L(x.source_zh, x.source_en), d: x.date }); }).join(" · ");
    var banner = j.error_kind && j.status === "done" ? '<div class="alert"><span class="ic">' + ic("x") + "</span><div><h3>" + (T["e_" + j.error_kind] ? t("e_" + j.error_kind) : t("e_general")) + '</h3><p class="mono" style="font-size:12px">' + t("e_detail", { m: esc(j.error || "") }) + '</p></div><button class="btn primary sm act" data-act="reset">' + t("e_again") + "</button></div>" : "";
    return banner + '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:28px"><div class="seg" style="min-width:300px">' +
      '<button data-ccy="orig" class="' + (c.ccy === "orig" ? "on" : "") + '">' + t("c_ccy_orig") + '</button><button data-ccy="local" class="' + (c.ccy === "local" ? "on" : "") + '">' + t("c_ccy_local") + "</button></div>" +
      '<div style="display:flex;gap:10px">' + (running ? '<button class="btn ghost sm" data-act="stop">' + ic("stop", "sm") + t("run_stop") + "</button>" : '<button class="btn ghost sm" data-act="cmp-csv">' + t("r_export_csv") + '</button><button class="btn ghost sm" data-act="reset">' + t("run_edit") + "</button>") + "</div></div>" +
      '<div class="fxstrip">' + ic("info", "sm") + (c.ccy === "orig" ? t("c_fx_none") : fxs || t("c_fx_none")) + "</div>" +
      '<div class="tbl-card"><div class="scrollx"><table class="cmp"><thead><tr><th>' + t("c_col_co") + "</th>" + CMP_FIELDS.map(function (f) { return "<th>" + L(CMP_NAMES[f][0], CMP_NAMES[f][1]) + "</th>"; }).join("") + "<th>" + t("c_col_status") + "</th></tr></thead><tbody>" + body + '</tbody></table></div><p class="hint" style="padding:0 16px">' + t("c_click") + " " + L("每格显示累计期（与报告期一致）的数。", "Each cell shows the cumulative period of the chosen report.") + "</p></div>" + caveat();
  }

  // ------------------------------------------------------------------ P4 verify
  function fmtDetect(s) { s = (s || "").trim(); if (!s) return null; return /^[\[{`]/.test(s) ? "json" : "table"; }
  function verify() {
    var j = S.job, v = S.ver;
    var head = '<div class="stage wide"><h1 class="stage-title">' + t("v_title") + '</h1><p class="hint" style="margin:-6px 0 0;text-align:center">' + t("v_sub") + "</p>";
    if (j.kind === "verify" && j.status === "running") return '<div class="wrap"><div class="runbar"><span class="live"></span><div class="what">' + esc(v.pdfName) + "</div></div></div>";
    if (j.kind === "verify" && j.status === "done" && j.result) return '<div class="wrap">' + verifyResult(j.result) + "</div>";
    if (j.kind === "verify" && (j.status === "error" || j.status === "fetch_failed")) {
      head += '<div class="alert" style="width:100%;max-width:1040px"><span class="ic">' + ic("x") + "</span><div><h3>" + (j.error_kind === "scanned" ? t("scanned") : t("e_general")) + "</h3><p class='mono' style='font-size:12px'>" + esc(j.error || "") + "</p></div></div>";
    }
    var mapping = "";
    if (j.kind === "verify" && j.status === "needs_mapping" && j.result) {
      var cols = j.result.columns, roles = j.result.roles;
      mapping = '<div class="card" style="width:100%;max-width:1040px"><h2>' + t("v_map_t") + '</h2><div class="grid4" style="margin-top:14px">' + cols.map(function (c, i) {
        var cur = v.mapping[String(i)] || roles[i] || "";
        return '<div class="field"><label>' + esc(c) + '</label><select class="input" data-map="' + i + '">' + ["", "field", "raw_value", "raw_unit", "raw_currency", "period_type", "page", "quote"].map(function (r) {
          return '<option value="' + r + '"' + (r === cur ? " selected" : "") + ">" + t(r ? "role_" + r : "role_none") + "</option>";
        }).join("") + "</select></div>";
      }).join("") + '</div><button class="btn primary" style="margin-top:16px" data-act="ver-run">' + t("v_map_go") + "</button></div>";
    }
    var fmt = fmtDetect(v.text);
    var can = v.pdf && v.text.trim();
    var prompt = (S.cfg.prompts || {})[S.lang] || "";
    var strip = prompt ? '<div class="card pstrip"><div class="pstrip-row"><div><p>' + t("v_howto") + '</p><p class="hint">' + t("v_prompt_eval", { p: pct(S.cfg.eval.holdout.tiers.ds_verified.strict_acc) }) + "</p></div>" +
      '<div class="pstrip-btns"><button class="btn primary sm" data-act="copy-prompt">' + ic(S.copied === "ok" ? "check" : "file", "sm") + (S.copied === "ok" ? t("v_copied") : t("v_copy")) + "</button>" +
      '<button class="btn ghost sm" data-act="show-prompt" aria-label="show prompt">' + (S.showPrompt ? "▴" : "▾") + "</button></div></div>" +
      (S.copied === "fail" ? '<div class="hint tx-warn">' + t("v_copy_fail") + "</div>" : "") +
      (S.showPrompt || S.copied === "fail" ? '<textarea class="input mono" id="v-prompt" readonly spellcheck="false">' + esc(prompt) + "</textarea>" : "") + "</div>" : "";
    return head + strip + mapping +'<div class="grid2 vgrid"><div class="card" style="display:flex;flex-direction:column;gap:18px"><h2><span class="pill" style="margin-right:8px">1</span>' + t("v_pdf") + "</h2>" +
      '<div class="drop" id="drop2"><div class="circle">' + ic("upload") + "</div><h3>" + (v.pdf ? esc(v.pdfName) + ' <span class="faint mono" style="font-size:12px">' + (v.pdfSize / 1048576).toFixed(1) + " MB</span>" : t("ff_drop")) + '</h3><input type="file" id="file2" accept="application/pdf" class="hidden"><button class="btn ghost sm" style="margin-top:12px" data-act="pick2">' + ic("file", "sm") + t("ff_choose") + "</button></div>" +
      '<div class="note">' + ic("lock", "sm") + t("v_no_upload_store") + "</div>" +
      '<div class="lbl">' + t("v_meta") + '</div><div class="field"><label>' + t("f_market") + '</label><div class="seg">' + ["us", "hk", "a"].map(function (m) { return '<button data-vmarket="' + m + '" class="' + (v.market === m ? "on" : "") + '">' + mkName(m) + "</button>"; }).join("") + "</div></div>" +
      '<div class="grid2"><div class="field"><label>' + t("f_period") + '</label><select class="input" id="v-period">' + PERIODS.map(function (p) { return '<option value="' + p + '"' + (p === v.period ? " selected" : "") + ">" + periodLabel(p) + "</option>"; }).join("") + "</select></div>" +
      '<div class="field"><label>' + t("v_tpl") + '</label><select class="input" id="v-tpl">' + ["auto", "general", "bank", "insurance"].map(function (x) { return '<option value="' + x + '"' + (x === v.template ? " selected" : "") + ">" + (x === "auto" ? t("v_tpl_auto") : tplName(x)) + "</option>"; }).join("") + "</select></div></div>" +
      '<div class="field"><label>' + t("v_code_opt") + '</label><input class="input" id="v-code" value="' + esc(v.code) + '" placeholder="' + t("ph_" + v.market) + '"></div></div>' +
      '<div class="card" style="display:flex;flex-direction:column;gap:14px"><h2><span class="pill" style="margin-right:8px">2</span>' + t("v_paste") + "</h2>" +
      '<div style="display:flex;gap:6px">' + ["json", "table"].map(function (k) { return '<span class="badge ' + (fmt === k ? "ok" : "grey") + '">' + t("v_fmt_" + k) + "</span>"; }).join("") + (fmt ? "" : '<span class="badge grey">' + t("v_fmt_wait") + "</span>") + "</div>" +
      '<textarea class="input" id="v-text" spellcheck="false" placeholder="' + esc(t("v_ph")) + '">' + esc(v.text) + '</textarea><div class="hint" style="text-align:right">' + t("v_chars", { n: v.text.length.toLocaleString("en-US") }) + "</div>" +
      '<button class="btn primary block" data-act="ver-run"' + (can ? "" : " disabled") + ">" + ic("play") + t("v_run") + "</button>" +
      (!can ? '<div class="hint">' + (!v.pdf ? t("v_need_pdf") : t("v_need_text")) + "</div>" : "") + "</div></div>" +
      '<p class="hint" style="max-width:1040px;margin:0">' + t("v_lead") + "</p></div>";
  }
  var FIELD_NAMES = { revenue: ["营业收入", "Revenue"], net_income_parent: ["归母净利润", "Net income attributable"], eps_basic: ["基本每股收益", "Basic EPS"],
    gross_profit: ["毛利", "Gross profit"], operating_cash_flow: ["经营活动现金流量净额", "Operating cash flow"], net_interest_income: ["净利息收入", "Net interest income"],
    ppop: ["拨备前利润", "Pre-provision profit"], insurance_revenue: ["保险服务收入", "Insurance revenue"], insurance_service_result: ["保险服务业绩", "Insurance service result"],
    cost_of_revenue: ["营业成本", "Cost of revenue"] };
  function fieldName(f) { var n = FIELD_NAMES[f]; return n ? L(n[0], n[1]) : f; }
  // the component runs in an iframe: the async clipboard API may be blocked there, so fall back to a hidden
  // textarea + execCommand, and if both fail show the prompt for manual copying
  function copyPrompt() {
    var text = (S.cfg.prompts || {})[S.lang] || "";
    function done(ok) { S.copied = ok ? "ok" : "fail"; render(); if (ok) setTimeout(function () { if (S.copied === "ok") { S.copied = null; render(); } }, 2000); }
    function legacy() {
      var ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      done(ok);
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { done(true); }, legacy);
      else legacy();
    } catch (e) { legacy(); }
  }
  function verifyResult(r) {
    var vx = r.verify || {}, c = r.counts;
    var checks = vx.c4 ? t("v_checks_c4") : t("v_checks_noc4_" + (vx.c4_reason === "hk" ? "hk" : vx.c4_reason === "no_code" ? "code" : "data"));
    var bad = vx.bad_rows || [], absent = vx.absent || [];
    var absentLine = absent.length ? '<p class="hint" style="margin:14px 2px 0">' + t("v_absent", { l: absent.map(function (a) { return esc(fieldName(a.field)) + (a.period_type ? "（" + ptype(a.period_type) + "）" : "") + (a.note ? "：" + esc(a.note) : ""); }).join("；") }) + "</p>" : "";
    return '<div class="runbar"><span style="width:9px;height:9px;border-radius:50%;background:var(--ok)"></span><div class="what">' + esc(S.ver.pdfName) + ' <span class="pill">' + r.pages_total + L(" 页", " pages") + "</span></div>" +
      '<span class="hint">' + checks + '</span><div style="margin-left:auto;display:flex;gap:10px"><button class="btn ghost sm" data-act="csv">' + t("r_export_csv") + '</button><button class="btn primary sm" data-act="reset">' + t("v_again") + "</button></div></div>" +
      '<div class="grid4" style="margin-top:20px">' + [["bad", "❌", "x"], ["warn", "⚠️", "warn"], ["ok", "✅", "check"]].map(function (x) {
        return '<div class="sumcard ' + x[0] + '"><div class="ic">' + ic(x[2]) + '</div><div><div class="lab">' + t("status_" + x[0]) + '</div><div class="num">' + c[x[1]] + "</div></div></div>";
      }).join("") + '<div class="sumcard"><div class="ic" style="background:var(--surface-2);color:var(--muted)">' + ic("warn") + '</div><div><div class="lab muted">' + t("v_unparsed") + '</div><div class="num">' + bad.length + "</div></div></div></div>" +
      (bad.length ? '<div class="alert" style="margin-top:20px"><span class="ic" style="background:var(--warn-soft);color:var(--warn)">' + ic("warn") + "</span><div><h3>" + t("v_badrows", { l: bad.map(function (b) { return b.line; }).join(", ") }) + "</h3>" + bad.map(function (b) { return '<p class="mono" style="font-size:12px">#' + b.line + " · " + esc(b.why) + (b.text ? " · " + esc(b.text) : "") + "</p>"; }).join("") + "</div></div>" : "") + absentLine +
      '<div class="tbl-card"><div class="tbl-head"><h2>' + t("r_core") + '</h2><span class="hint">' + t("r_core_sub") + "</span></div>" + rtable(r.items, "job") + "</div>" + caveat();
  }

  // ------------------------------------------------------------------ P5 method
  function method() {
    var E = S.cfg.eval, F = E.frozen_eval1.tiers, H = E.holdout.tiers, M = E.recall_by_market, FB = E.fable.tiers;
    function row(k, x) {
      var flags = x.recall != null;
      return "<tr><td><b>" + t("tier_" + k) + "</b><small>" + t("mt_items", { n: x.items }) + "</small></td><td>" + pct(x.strict_acc) + "</td><td>" + x.silent + "<small>" + pct(x.silent_rate) + "</small></td><td>" + (flags ? pct(x.workload) : "0") + "</td><td>" + (flags ? pct(x.recall) + " / " + pct(x.recall_no_c4) : '<span class="faint" style="font-size:12px">' + t("mt_noflag") + "</span>") + "</td></tr>";
    }
    function tbl(tiers, keys) {
      return '<div class="tbl-card" style="padding:12px"><div class="scrollx"><table class="mtx"><thead><tr><th>' + t("th_tier") + "</th><th>" + t("th_strict") + "</th><th>" + t("th_silent") + "</th><th>" + t("th_work") + "</th><th>" + t("th_recall") + "</th></tr></thead><tbody>" + keys.map(function (k) { return row(k, tiers[k]); }).join("") + "</tbody></table></div></div>";
    }
    function mk(x, title, tone, why) {
      var col = tone === "ok" ? "var(--accent-text)" : "var(--warn)";
      return '<div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><h2>' + title + "</h2>" + (tone !== "ok" ? '<span class="badge warn">' + t("mt_lower") + "</span>" : "") + '</div><div class="grid2" style="margin-top:18px"><div class="card tight" style="background:var(--surface-2)"><div class="lbl">' + t("mt_withc4") + '</div><div class="big" style="font-size:48px;color:' + col + '">' + pct(x.recall) + '</div></div><div class="card tight" style="background:var(--surface-2)"><div class="lbl">' + t("mt_noc4") + '</div><div class="big" style="font-size:48px">' + pct(x.recall_no_c4) + "</div></div></div>" +
        '<p class="hint" style="margin:14px 0 6px">' + t("mt_hk_errs", { e: x.errors, f: Math.round((x.recall || 0) * x.errors) }) + "</p>" + why.map(function (w) { return '<p class="muted" style="margin:6px 0 0;font-size:13px">' + w + "</p>"; }).join("") + "</div>";
    }
    var mods = [["C1", "c1"], ["C2", "c2"], ["C3", "c3"], ["C4", "c4"], ["S1–S5", "sx"]].map(function (m) { return '<div class="mod"><div class="k">' + m[0] + "</div><h3>" + t(m[1] + "_t") + "</h3><p>" + t(m[1] + "_d") + "</p></div>"; }).join("");
    var toc = [["m-about", t("about_eyebrow")], ["m-summary", t("eval_title")], ["m-main", t("mt_main")], ["m-hold", t("mt_hold")], ["m-mk", t("mt_mk")], ["m-fable", t("mt_fable")], ["m-checks", t("mt_checks")], ["m-prompt", t("mt_prompt")], ["m-limits", t("mt_limits")]];
    var R3 = H.ds_verified;
    return '<div class="wrap pt mlayout"><article class="mbody">' + about() +
      '<section class="msec" id="m-eval"><div class="card" style="display:flex;gap:16px">' + ic("info") + '<p style="margin:0" class="muted">' + t("mt_lead") + " " + t("mt_src") + "</p></div></section>" +
      '<section class="section" id="m-main"><div class="section-head"><div><div class="eyebrow">' + esc(L(E.frozen_eval1.label_zh, E.frozen_eval1.label_en)) + "</div><h2>" + t("mt_main") + '</h2></div><span class="hint">docs/eval_results.md ' + E.frozen_eval1.section + "</span></div>" + tbl(F, ["ds_simple", "ds_direct", "ds_pipeline"]) + '<p class="src">' + t("silent_def") + "</p></section>" +
      '<section class="section" id="m-hold"><div class="section-head"><div><div class="eyebrow">' + esc(L(E.holdout.label_zh, E.holdout.label_en)) + "</div><h2>" + t("mt_hold") + '</h2></div><span class="hint">docs/eval_results.md ' + E.holdout.section + "</span></div>" + tbl(H, ["ds_simple", "ds_direct", "ds_pipeline", "ds_verified"]) + '<p class="src">' + t("mt_hold_note") + "</p></section>" +
      '<section class="section" id="m-mk"><div class="section-head"><div><div class="eyebrow">' + esc(L(M.label_zh, M.label_en)) + "</div><h2>" + t("mt_mk") + '</h2></div><span class="hint">' + t("mt_mk_note") + " · docs/eval_results.md " + M.section + "</span></div>" +
      '<div class="grid2">' + mk(M.us_a, t("mt_usa"), "ok", [t("mt_usa_why")]) + mk(M.hk, t("mt_hk"), "warn", [t("mt_hk_why1"), t("mt_hk_why2")]) + "</div></section>" +
      '<section class="section" id="m-fable"><div class="section-head"><div><div class="eyebrow">' + esc(L(E.fable.label_zh, E.fable.label_en)) + "</div><h2>" + t("mt_fable") + '</h2></div><span class="hint">docs/eval_results.md ' + E.fable.section + "</span></div>" + tbl(FB, ["fable_direct", "fable_pipeline", "ds_direct", "ds_pipeline"]) + '<p class="src">' + t("mt_fable_note") + "</p></section>" +
      '<section class="section" id="m-checks"><div class="section-head"><div><h2>' + t("mt_checks") + '</h2></div></div><div class="grid3">' + mods + "</div></section>" +
      '<section class="section" id="m-prompt"><div class="section-head"><div><h2>' + t("mt_prompt") + '</h2></div><a class="link" data-go="verify">' + t("nav_verify") + ' →</a></div><div class="card"><p style="margin:0">' + t("mt_prompt_d1") + '</p><p class="muted" style="margin:10px 0 0">' + t("mt_prompt_d2", { p: pct(R3.strict_acc), n: R3.items }) + "</p></div></section>" +
      '<section class="section" id="m-limits"><div class="section-head"><div><h2>' + t("mt_limits") + '</h2></div></div><div class="card"><div class="lim">' + [1, 2, 3, 4].map(function (n) { return '<div><span class="n">' + n + "</span><div><h4>" + t("l" + n + "_t") + "</h4><p>" + t("l" + n + "_d") + "</p></div></div>"; }).join("") + "</div>" +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:24px"><a class="btn ghost sm" href="' + esc(S.cfg.github) + '" target="_blank" rel="noopener">' + ic("code", "sm") + " GitHub</a><span class='pill'>docs/eval_design.md · " + t("mt_links") + "</span><span class='pill'>docs/eval_results.md · " + t("mt_links2") + "</span></div></div></section></article>" +
      '<nav class="mtoc"><div class="lbl">' + t("mt_toc") + "</div>" + toc.map(function (x) { return '<a data-toc="' + x[0] + '">' + x[1] + "</a>"; }).join("") + "</nav></div>";
  }

  // ------------------------------------------------------------------ exports
  function download(name, text, type) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  function csvCell(v) { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function exportResult(r, kind) {
    var d = r.doc, base = d.market + "_" + d.code + "_" + d.period;
    if (kind === "json") return download(base + ".json", JSON.stringify(r, null, 1), "application/json");
    var head = ["status", "field", "metric_zh", "metric_en", "period_type", "period_end", "raw_value", "unit", "value", "currency", "page", "quote", "category", "reason_zh", "reason_en", "auxiliary"];
    var lines = [head.join(",")].concat(r.items.map(function (i) {
      return [i.status, i.field, i.name_zh, i.name_en, i.ptype, i.period_end, i.raw, i.unit, i.value, i.currency, i.page, i.quote, i.category, i.reason_zh, i.reason_en, i.aux].map(csvCell).join(",");
    }));
    download(base + ".csv", "﻿" + lines.join("\n"), "text/csv");
  }
  function exportCompare() {
    var j = S.job, head = ["company", "code", "market", "field", "raw_value", "unit", "value", "currency", "status", "listing_currency", "fx_rate", "fx_date", "fx_type", "fx_source", "value_listing"];
    var lines = [head.join(",")];
    j.rows.forEach(function (row) {
      if (row.status !== "done") return;
      CMP_FIELDS.forEach(function (f) {
        var it = row.cells[f]; if (!it) return;
        var fx = fxFor(row, it);
        lines.push([row.name, row.code, row.market, f, it.raw, it.unit, it.value, it.currency, it.status, row.listing, fx ? fx.rate : "", fx ? fx.date : "", fx ? fx.type : "", fx ? fx.source_zh : "", fx && it.value != null ? it.value * fx.rate : ""].map(csvCell).join(","));
      });
    });
    download("compare_" + (j.query || {}).period + ".csv", "﻿" + lines.join("\n"), "text/csv");
  }

  // ------------------------------------------------------------------ events
  function readPdf(file, cb) {
    if (!file) return;
    var fr = new FileReader();
    fr.onload = function () { cb({ name: file.name, size: file.size, data: fr.result }); };
    fr.readAsDataURL(file);
  }
  function wireDrop(id, inputId, cb) {
    var d = document.getElementById(id), inp = document.getElementById(inputId);
    if (inp) inp.onchange = function () { readPdf(inp.files[0], cb); };
    if (!d) return;
    d.ondragover = function (e) { e.preventDefault(); d.classList.add("over"); };
    d.ondragleave = function () { d.classList.remove("over"); };
    d.ondrop = function (e) { e.preventDefault(); d.classList.remove("over"); readPdf(e.dataTransfer.files[0], cb); };
  }
  function keyPayload() {
    var f = S.form;
    return { provider: f.provider, model: f.model.trim(), base_url: f.base_url.trim(), key: f.key.trim(), lang: S.lang };
  }
  function bind() {
    var app = document.getElementById("app");
    app.onclick = onClick;
    function on(id, ev, fn) { var el = document.getElementById(id); if (el) el[ev] = fn; }
    on("f-code", "oninput", function (e) { S.form.code = e.target.value; refreshStart(); });
    on("f-key", "oninput", function (e) { S.form.key = e.target.value; refreshStart(); });
    on("f-model", "oninput", function (e) { S.form.model = e.target.value; refreshStart(); });
    on("f-base", "oninput", function (e) { S.form.base_url = e.target.value; refreshStart(); });
    on("f-period", "onchange", function (e) { S.form.period = e.target.value; });
    on("f-provider", "onchange", function (e) { S.form.provider = e.target.value; S.form.key = ""; S.form.model = ""; S.form.base_url = ""; render(); });
    on("f-code", "onblur", function (e) { if (S.form.market === "hk" && /^\d{1,4}$/.test(e.target.value.trim())) { S.form.code = ("00000" + e.target.value.trim()).slice(-5); render(); } });
    on("c-period", "onchange", function (e) { S.cmp.period = e.target.value; });
    on("v-period", "onchange", function (e) { S.ver.period = e.target.value; });
    on("v-tpl", "onchange", function (e) { S.ver.template = e.target.value; });
    on("v-code", "oninput", function (e) { S.ver.code = e.target.value; });
    on("v-text", "oninput", function (e) {
      S.ver.text = e.target.value;
      if ((fmtDetect(S.ver.text) || "") !== (S._lastFmt || "") || !!S.ver.text.trim() !== !!S._hadText) { S._lastFmt = fmtDetect(S.ver.text); S._hadText = !!S.ver.text.trim(); render(); }
    });
    document.querySelectorAll("[data-ccode]").forEach(function (el) { el.oninput = function () { S.cmp.rows[+el.dataset.ccode].code = el.value; }; });
    document.querySelectorAll("[data-cmarket]").forEach(function (el) { el.onchange = function () { S.cmp.rows[+el.dataset.cmarket].market = el.value; render(); }; });
    document.querySelectorAll("[data-map]").forEach(function (el) { el.onchange = function () { S.ver.mapping[el.dataset.map] = el.value; }; });
    wireDrop("drop1", "file1", function (f) { S.upload = f; render(); });
    wireDrop("drop2", "file2", function (f) { S.ver.pdf = f.data; S.ver.pdfName = f.name; S.ver.pdfSize = f.size; render(); });
    document.querySelectorAll("[data-cup]").forEach(function (b) {
      var i = b.dataset.cup, inp = document.getElementById("cf-" + i);
      inp.onchange = function () { readPdf(inp.files[0], function (f) { bigEventId = send("compare_upload", Object.assign({ index: +i, pdf: f.data }, keyPayload())); }); };
    });
  }
  function refreshStart() {
    if (!S.touched) return;
    var b = document.querySelector('[data-act="start"]'); if (b) b.disabled = Object.keys(formErrors()).length > 0;
  }
  function onClick(e) {
    var el = e.target.closest("[data-go],[data-act],[data-hist],[data-toc],[data-ex],[data-page],[data-dpage],[data-market],[data-vmarket],[data-ccy],[data-copen],[data-cdel],[data-quote],[data-comp],[data-cup]");
    if (!el) return;
    var d = el.dataset;
    if (d.go) { go(d.go); return; }
    if (d.toc) { var sec = document.getElementById(d.toc); if (sec) sec.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (d.hist) {
      S.menu = false; S.drawer = null; S.auxOpen = false; S.view = "analyze"; S.scrollTop0 = true;
      S.hist = d.hist === S.saved[S.job.id] ? null : d.hist;   // the live result keeps its page images
      render(); return;
    }
    if (d.ex) { S.example = d.ex; S.auxOpen = false; go("example"); return; }
    if (d.page) { S.drawer = { src: d.src, n: +d.page, item: d.item || null }; if (d.src === "job") send("page", { n: +d.page }); render(); return; }
    if (d.dpage) { if (!d.dpage) return; S.drawer.n = +d.dpage; S.drawer.item = null; if (S.drawer.src === "job") send("page", { n: +d.dpage }); render(); return; }
    if (d.market) { S.form.market = d.market; render(); return; }
    if (d.vmarket) { S.ver.market = d.vmarket; render(); return; }
    if (d.ccy) { S.cmp.ccy = d.ccy; render(); return; }
    if (d.copen) { S.cmp.open = +d.copen; S.auxOpen = false; S.scrollTop0 = true; render(); return; }
    if (d.cdel) { S.cmp.rows.splice(+d.cdel, 1); if (!S.cmp.rows.length) S.cmp.rows.push({ market: "us", code: "" }); render(); return; }
    if (d.quote) { S.openQuotes[d.quote] = !S.openQuotes[d.quote]; render(); return; }
    if (d.comp) { S.openComps[d.comp] = !S.openComps[d.comp]; render(); return; }
    if (d.cup) { var inp = document.getElementById("cf-" + d.cup); if (inp) inp.click(); return; }
    var a = d.act;
    if (a === "theme") {
      var th = S.theme === "light" ? "dark" : "light";
      try { localStorage.setItem(THEME_KEY, th); } catch (e) { /* private mode: applies for this visit only */ }
      applyTheme(th); render(); return;
    }
    if (a === "lang") { S.lang = S.lang === "zh" ? "en" : "zh"; send("lang", { lang: S.lang }); render(); }
    else if (a === "menu") { S.menu = !S.menu; render(); }
    else if (a === "side") { S.side = !S.side; S.menu = false; try { localStorage.setItem("cited-side", S.side ? "1" : "0"); } catch (e2) { /* this visit only */ } render(); }
    else if (a === "new") {
      S.hist = null; S.drawer = null; S.touched = false;
      if (S.job.kind === "single" && S.job.status !== "running") { send("reset"); S.job = { status: "idle" }; }
      go("analyze");
    }
    else if (a === "hist-clear") { try { localStorage.removeItem(HIST_KEY); } catch (e3) { /* nothing stored */ } S.hist = null; S.histCur = null; render(); }
    else if (a === "prov") { S.provOpen = !S.provOpen; render(); }
    else if (a === "show-prompt") { S.showPrompt = !S.showPrompt; render(); }
    else if (a === "copy-prompt") { copyPrompt(); }
    else if (a === "panel-hide") { S.panelHidden = true; render(); }
    else if (a === "panel-show") { S.panelHidden = false; render(); }
    else if (a === "eye") { S.form.showKey = !S.form.showKey; render(); }
    else if (a === "start") {
      S.touched = true;
      if (Object.keys(formErrors()).length) { render(); return; }
      S.log = []; S.lastStage = null;
      send("analyze", Object.assign({ market: S.form.market, code: S.form.code.trim(), period: S.form.period }, keyPayload()));
    }
    else if (a === "retry") { S.log = []; send("analyze", Object.assign({ market: S.form.market, code: S.form.code.trim(), period: S.form.period }, keyPayload())); }
    else if (a === "pick1") { document.getElementById("file1").click(); }
    else if (a === "pick2") { document.getElementById("file2").click(); }
    else if (a === "upload") {
      if (!S.upload) return;
      S.touched = true;
      if (formErrors().key) { render(); return; }
      var q = S.job.query || S.form;
      bigEventId = send("upload", Object.assign({ market: q.market, code: q.code, period: q.period, pdf: S.upload.data }, keyPayload()));
      S.upload = null;
    }
    else if (a === "stop") { send("stop"); }
    else if (a === "reset") { S.cmp.open = null; send("reset"); S.job = { status: "idle" }; render(); }
    else if (a === "aux") { S.auxOpen = !S.auxOpen; render(); }
    else if (a === "close") { S.drawer = null; render(); }
    else if (a === "csv" || a === "json") { var r = S.view === "example" ? S.cfg.examples[S.example] : S.view === "compare" ? curResult("cmp" + S.cmp.open) : S.hist ? curResult("hist") : S.job.result; if (r) exportResult(r, a); }
    else if (a === "cmp-csv") { exportCompare(); }
    else if (a === "cmp-back") { S.cmp.open = null; render(); }
    else if (a === "cadd") { if (S.cmp.rows.length < 10) S.cmp.rows.push({ market: "us", code: "" }); render(); }
    else if (a === "cmp-run") {
      S.touched = true;
      var e2 = formErrors();
      var rows = S.cmp.rows.filter(function (r) { return r.code.trim(); });
      if (!rows.length || e2.key || e2.model || e2.base) { render(); return; }
      S.cmp.open = null;
      send("compare", Object.assign({ rows: rows, period: S.cmp.period }, keyPayload()));
    }
    else if (a === "ver-run") {
      if (!S.ver.pdf || !S.ver.text.trim()) return;
      bigEventId = send("verify", { pdf: S.ver.pdf, text: S.ver.text, market: S.ver.market, period: S.ver.period, code: S.ver.code.trim(), template: S.ver.template, mapping: S.ver.mapping });
    }
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && S.drawer) { S.drawer = null; render(); } });
})();
