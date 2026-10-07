"""Language audit: in each interface language, open every page and list visible text in the other language.

- EN mode: any Chinese character is reported, except inside elements marked data-orig (company names, filing
  titles, quotes, page text, units as printed, pasted answers) — the original wording.
- ZH mode: English words are reported, except proper names and terms on ALLOW, upper-case codes (tickers,
  acronyms), tokens with digits or dashes (model ids, periods) and the same data-orig elements.
Pages: analyze, examples, each example result (auxiliary rows open, one source page open), compare, verify
(with the prompt shown), method; desktop width. Screenshots go to docs/web_shots/lang/ (not committed).

Needs a running app (default http://localhost:8517/) and Google Chrome; only tornado (ships with Streamlit).
  .venv/bin/python -m web.lang_audit [url]
Exit code 1 when anything is found.
"""
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from tornado.websocket import websocket_connect

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8517/"
OUT = Path(__file__).resolve().parents[1] / "docs" / "web_shots" / "lang"
CHROME = os.environ.get("CHROME") or next((p for p in (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "") if p and os.path.exists(p)), "google-chrome")
PORT = 9334
FR = "document.querySelector('iframe[data-testid=\"stCustomComponentV1\"]').contentDocument"

ALLOW = {w.lower() for w in """
DeepSeek OpenAI Claude Gemini Anthropic Google Qwen Alibaba Cloud Model Studio Kimi Moonshot GLM Zhipu Other compatible
OpenAI-compatible API key KEY JSON PDF CSV SEC XBRL EDGAR HKEXnews cninfo GitHub GPT EPS ADS AI Earnings Verifier MIT
Fable DeepSeek-flash FY YTD TTM IFRS GAAP companyfacts Markdown sk Base URL prompts docs md eval_results eval_design
in millions per share Doubao Tesla Inc PetroChina Xiaomi Apple Microsoft NVDA MSFT AIoT IoT eval
""".split()}

COLLECT = r"""
(function () {
  var d = %s, out = [];
  function skip(el) {
    for (; el && el.nodeType === 1; el = el.parentElement) {
      if (el.hasAttribute('data-orig') || el.matches('.quote, .pagetext, script, style, mark')) return true;
      var cs = d.defaultView.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return true;
    }
    return false;
  }
  var w = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT), n;
  while ((n = w.nextNode())) { var t = n.nodeValue.trim(); if (t && n.parentElement.tagName !== 'TEXTAREA' && !skip(n.parentElement)) out.push(t); }
  d.querySelectorAll('input[placeholder], textarea[placeholder]').forEach(function (e) {
    if (!skip(e)) out.push(e.getAttribute('placeholder'));
  });
  return out;
})()
""" % FR

CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
WORD = re.compile(r"[A-Za-z][A-Za-z_'\-]*")


def foreign(texts, lang):
    hits = []
    for t in texts:
        if lang == "en":
            if CJK.search(t):
                hits.append(t)
        else:
            bad = [w for w in WORD.findall(t)
                   if w.lower() not in ALLOW and not w.isupper() and not re.search(r"[\d\-_]", w) and len(w) > 1]
            if bad:
                hits.append(f"{t}   ← {', '.join(sorted(set(bad)))}")
    return sorted(set(hits))


class CDP:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, method, **params):
        self.n += 1
        my = self.n
        await self.ws.write_message(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.read_message())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")


async def wait_for(cdp, expr, secs=60):
    for _ in range(secs * 2):
        try:
            if await cdp.js(expr):
                return
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError("timeout: " + expr)


async def click(cdp, sel):
    ok = await cdp.js(f"(function(){{var e={FR}.querySelector({sel!r}); if(!e) return false; e.click(); return true;}})()")
    await asyncio.sleep(0.8)
    return ok


async def audit(cdp):
    OUT.mkdir(parents=True, exist_ok=True)
    await cdp.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
    report = {}
    for lang in ("zh", "en"):
        await cdp.call("Page.navigate", url=URL)
        await wait_for(cdp, f"!!document.querySelector('iframe[data-testid=\"stCustomComponentV1\"]') && !!{FR}.querySelector('.shell')")
        await asyncio.sleep(2)
        cur = await cdp.js(f"{FR}.querySelector('[data-act=\"lang\"] b').textContent")
        if (cur == "中") != (lang == "zh"):
            await click(cdp, '[data-act="lang"]')
        examples = await cdp.js(f"Array.from({FR}.querySelectorAll('[data-ex]')).map(e => e.dataset.ex)") or []
        steps = [("analyze", ['.side-nav [data-go="analyze"]']), ("examples", ['.side-nav [data-go="examples"]'])]
        if not examples:
            await click(cdp, '.side-nav [data-go="examples"]')
            examples = await cdp.js(f"Array.from({FR}.querySelectorAll('[data-ex]')).map(e => e.dataset.ex)") or []
        for ex in examples:
            steps.append((f"example_{ex}", ['.side-nav [data-go="examples"]', f'[data-ex="{ex}"]', '[data-act="aux"]', "a.pg[data-item]"]))
        steps += [("compare", ['.side-nav [data-go="compare"]']),
                  ("verify", ['.side-nav [data-go="verify"]', '[data-act="show-prompt"]']),
                  ("method", ['.side-nav [data-go="method"]'])]
        for name, clicks in steps:
            await click(cdp, '[data-act="close"]')
            for sel in clicks:
                await click(cdp, sel)
            texts = await cdp.js(COLLECT) or []
            hits = foreign(texts, lang)
            report[f"{lang}:{name}"] = hits
            r = await cdp.call("Page.captureScreenshot", format="png")
            (OUT / f"{lang}_{name}.png").write_bytes(base64.b64decode(r["data"]))
            print(f"[{lang}] {name}: {len(hits)} finding(s)")
            for h in hits:
                print("    ", h[:160])
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return sum(len(v) for v in report.values())


async def main():
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--hide-scrollbars",
                             "--user-data-dir=/tmp/lang-audit-chrome", "--no-first-run", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = [t for t in tabs if t["type"] == "page"][0]
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        ws = await websocket_connect(page["webSocketDebuggerUrl"], max_message_size=200 * 1024 * 1024)
        cdp = CDP(ws)
        await cdp.call("Page.enable")
        n = await audit(cdp)
    finally:
        proc.terminate()
    print(f"total findings: {n}  (report: {OUT / 'report.json'})")
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    asyncio.run(main())
