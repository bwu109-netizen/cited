"""Check the proposed evaluation companies before committing to them (no model calls).

For each candidate: resolve + download the target report, parse it, find the income-statement pages,
detect template / reporting unit / currency, read profit-or-loss sign from the structured source, and
resolve (without downloading) the previous report. Writes data/output/eval_candidates.json and
prints a table for docs/eval_design.md.
"""
import json
import re
import sys
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from earnings_agent.benchmark import get_benchmark  # noqa: E402
from earnings_agent.locate import select_pages  # noqa: E402
from earnings_agent.parse import load_doc_pages  # noqa: E402
from earnings_agent.periods import parse_period  # noqa: E402
from earnings_agent.sources import fetch_report  # noqa: E402
from earnings_agent.templates import choose_template  # noqa: E402
from earnings_agent.textnorm import nfkc  # noqa: E402
from earnings_agent.units import currency_code  # noqa: E402

# (market, code, target period, short reason)
CANDIDATES = [
    # ---- US
    ("us", "MSFT", "2026FY", "软件；6 月财年 10-K"),
    ("us", "NVDA", "2027Q2", "半导体；1 月财年，FY 标签跨自然年"),
    ("us", "AMZN", "2026Q2", "电商/云；无毛利行"),
    ("us", "KO", "2025FY", "消费品；10-K 年报"),
    ("us", "PFE", "2026Q2", "医药"),
    ("us", "CVX", "2026Q2", "能源（原选 XOM：2026 年改为新控股公司 CIK，上一期 10-Q 在旧 CIK 下，换掉）"),
    ("us", "TSLA", "2026Q2", "汽车"),
    ("us", "INTC", "2026Q2", "半导体；近年亏损"),
    ("us", "RIVN", "2026Q2", "电动车；亏损"),
    ("us", "UBER", "2026Q2", "平台"),
    ("us", "SNAP", "2026Q2", "互联网；以千美元列报、亏损"),
    ("us", "BAC", "2026Q2", "银行"),
    ("us", "WFC", "2026Q2", "银行"),
    ("us", "USB", "2026Q2", "银行（原选 C：2026 年 10-Q 在 companyfacts 里没有 XBRL，无自动标准答案，换掉）"),
    ("us", "MET", "2026Q2", "寿险"),
    ("us", "PGR", "2026Q2", "财险"),
    ("us", "AIG", "2026Q2", "保险"),
    ("us", "PDD", "2025FY", "中概股 20-F；人民币"),
    ("us", "BIDU", "2025FY", "中概股 20-F；人民币"),
    ("us", "NIO", "2025FY", "中概股 20-F；人民币、亏损"),
    # ---- A-share
    ("a", "002594", "2026H1", "汽车"),
    ("a", "000333", "2026H1", "家电"),
    ("a", "601857", "2025FY", "能源；年报（长文档）"),
    ("a", "600900", "2026Q1", "电力；一季报（短文档）"),
    ("a", "601012", "2026H1", "光伏；亏损"),
    ("a", "688981", "2026H1", "科创板半导体；千元"),
    ("a", "600276", "2026H1", "医药"),
    ("a", "603288", "2026Q1", "食品；一季报"),
    ("a", "000002", "2026H1", "地产；亏损"),
    ("a", "000725", "2026H1", "面板"),
    ("a", "002475", "2026H1", "消费电子制造"),
    ("a", "601888", "2026H1", "免税零售"),
    ("a", "002714", "2026H1", "养殖"),
    ("a", "601899", "2026H1", "矿业"),
    ("a", "601398", "2025FY", "银行；年报、百万元"),
    ("a", "000001", "2026Q1", "银行；一季报"),
    ("a", "002142", "2026H1", "银行"),
    ("a", "601318", "2026H1", "保险（新准则）"),
    ("a", "601628", "2026H1", "寿险"),
    ("a", "601601", "2026H1", "保险"),
    # ---- HK
    ("hk", "01810", "2026H1", "消费电子；人民币千元"),
    ("hk", "09618", "2026H1", "电商；人民币"),
    ("hk", "00941", "2026H1", "电信；人民币"),
    ("hk", "02331", "2026H1", "运动服饰；人民币"),
    ("hk", "09868", "2026H1", "电动车；亏损"),
    ("hk", "09660", "2026H1", "智驾芯片；亏损"),
    ("hk", "01024", "2026H1", "短视频；人民币"),
    ("hk", "00992", "2027Q1", "PC；3 月财年、美元、季度业绩"),
    ("hk", "01910", "2026H1", "消费品；美元"),
    ("hk", "00388", "2026H1", "交易所；港币"),
    ("hk", "00001", "2026H1", "综合企业；港币"),
    ("hk", "00002", "2026H1", "公用事业；港币"),
    ("hk", "00016", "2026FY", "地产；6 月财年年度业绩、港币"),
    ("hk", "02388", "2026H1", "银行；港币"),
    ("hk", "02888", "2026H1", "银行；美元"),
    ("hk", "03328", "2026H1", "银行；人民币"),
    ("hk", "01299", "2026H1", "寿险；美元"),
    ("hk", "02378", "2026H1", "寿险；美元"),
    ("hk", "06060", "2026H1", "互联网保险；人民币"),
    ("hk", "02328", "2026H1", "财险；人民币"),
]

UNIT_PATTERNS = [
    r"百萬美元|千美元|百萬港元|千港元|港幣百萬元|港幣千元|人民幣百萬元|人民幣千元|人民币百万元|人民币千元",
    r"以(?:人民[幣币]|港[元幣币]|美元)(?:列示|為單位|为单位)",
    r"(?:US|HK)\$\s?(?:million|m\b|'000)|RMB\s?(?:million|'000)",
    r"(?:单位|單位)\s*[:：]?\s*(?:人民[币幣]|港[元币幣]|美元)?\s*(?:千元|百万元|百萬元|万元|萬元|亿元|億元|元)",
    r"(?:人民[币幣]|港[元币幣]|港币|美元|RMB|HK\$|US\$)\s*(?:千元|百万元|百萬元|万元|萬元|亿元|億元|元|'000|million|thousand)",
    r"(?:千元|百万元|百萬元)\s*(?:人民[币幣]|港[元币幣]|美元)",
    r"(?:in|In|IN)\s+(?:millions|thousands|billions)[^\n)]{0,40}",
    r"\((?:RMB|US\$|HK\$|\$)\s*in\s+(?:millions|thousands)[^)]*\)",
]


def prior_candidates(market, period, quarterly):
    year, part = parse_period(period)
    if part == "FY":
        if market == "us":
            return [f"{year}Q3"] if quarterly else [f"{year - 1}FY"]
        if market == "a":
            return [f"{year}Q3"]
        return [f"{year}Q3", f"{year}H1", f"{year - 1}FY"]
    if part == "Q1":
        return [f"{year - 1}FY"]
    if part in ("H1", "Q2"):
        return [f"{year}Q1", f"{year - 1}FY"]
    return [f"{year}{'H1' if market != 'us' else 'Q2'}"]


def detect_unit(pages, numbers):
    found = []
    for n in numbers:
        t = nfkc(pages[n - 1]["text"])
        for pat in UNIT_PATTERNS:
            for m in re.finditer(pat, t):
                s = m.group(0).strip()
                if s not in found:
                    found.append(s)
    return found[:3]


def main():
    only = set(sys.argv[1:])
    out_path = ROOT / "data" / "output" / "eval_candidates.json"
    done = {}
    if out_path.exists():
        done = {(r["market"], r["code"]): r for r in json.loads(out_path.read_text())}
    rows = []
    for market, code, period, reason in CANDIDATES:
        if only and code not in only:
            rows.append(done.get((market, code)) or {"market": market, "code": code})
            continue
        if (market, code) in done and done[(market, code)].get("ok") and not only:
            rows.append(done[(market, code)])
            continue
        rec = {"market": market, "code": code, "period": period, "reason": reason}
        print(f"=== {market} {code} {period}", flush=True)
        try:
            doc = fetch_report(market, code, period)
            pages = load_doc_pages(doc)
            sel, groups = select_pages(pages)
            inc = groups.get("income", [])[:2]
            template, tnotes = choose_template(doc["industry"], [pages[n - 1]["text"] for n in inc])
            bench, berr = get_benchmark(doc, template)
            nib = next((b for b in bench if b["field"] == "net_income_parent"
                        and b["period_type"] in ("H", "YTD", "FY", "Q")), None)
            ni = nib["value"] if nib else None
            units = detect_unit(pages, inc + groups.get("highlights", [])[:1])
            cur = next((currency_code(u, u, market) for u in units if currency_code(u, u, market)), None)
            if cur is None:  # e.g. "(以人民幣列示)" sits on the page but not next to the unit
                txt = nfkc("\n".join(pages[n - 1]["text"] for n in inc))
                for word, code_ in (("人民幣", "CNY"), ("人民币", "CNY"), ("港元", "HKD"), ("港幣", "HKD"), ("美元", "USD")):
                    if word in txt:
                        cur = code_
                        break
            rec.update(ok=True, name=doc["name"], parts=len(doc.get("parts") or []), income_pages=inc, doc_kind=doc["doc_kind"], title=doc["title"], filed=doc["filed"],
                       period_end=doc["period_end"], url=doc["url"], pages=len(pages),
                       chars=sum(len(p["text"]) for p in pages), sent_chars=sum(len(pages[n - 1]["text"]) for n in sel),
                       template=template, template_notes=tnotes, industry=doc["industry"],
                       units=units, currency_guess=cur, net_income=ni, bench_currency=(nib or {}).get("currency"), bench_fields=len(bench), bench_error=berr)
            prior = None
            quarterly = doc["doc_kind"] in ("10-K",)
            for pp in prior_candidates(market, period, quarterly):
                try:
                    pd = fetch_report(market, code, pp, download=False)
                    prior = {"period": pp, "title": pd["title"], "filed": pd["filed"], "url": pd["url"]}
                    break
                except Exception as e:
                    rec.setdefault("prior_errors", []).append(f"{pp}: {type(e).__name__}: {str(e)[:120]}")
            rec["prior"] = prior
        except Exception as e:
            rec.update(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}", trace=traceback.format_exc()[-800:])
        print(f"   {rec.get('ok')} {rec.get('template')} {rec.get('units')} {rec.get('currency_guess')} "
              f"NI={rec.get('net_income')} prior={(rec.get('prior') or {}).get('period')} {rec.get('error', '')}",
              flush=True)
        rows.append(rec)
        out_path.write_text(json.dumps(rows + [r for r in done.values() if (r['market'], r['code']) not in
                                               {(x['market'], x['code']) for x in rows}],
                                       ensure_ascii=False, indent=1, default=str))
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
