"""HK feasibility: latest results announcement + interim/annual report PDF from HKEXnews (披露易)
+ AKShare (Eastmoney HK F10) statements, cross-check.

Usage: .venv/bin/python scripts/hk_hkexnews.py
"""
import html
import json

import akshare as ak

from common import BROWSER_UA, RAW, RateLimitedSession, dump_json, find_in_text, is_text_pdf, pdf_profile, save

S = RateLimitedSession(max_per_sec=2, user_agent=BROWSER_UA)
BASE = "https://www1.hkexnews.hk"

COMPANIES = [
    {"code": "00700", "name": "腾讯控股", "industry": "互联网"},
    {"code": "03690", "name": "美团-W", "industry": "本地生活/外卖"},
    {"code": "00005", "name": "汇丰控股", "industry": "银行"},
]
# Eastmoney STD_ITEM_NAME candidates per target field (bank & non-bank templates differ)
ITEMS = {
    # 营运收入 = 营业额 + 其他营业收入; Tencent's reported 收入 equals 营运收入, not 营业额.
    # Banks: 经营收入总额 is net operating income AFTER expected credit losses (HSBC), not the headline 收入.
    "revenue": ["营运收入", "营业额", "经营收入总额", "营业收入"],
    "net_income_parent": ["股东应占溢利", "本公司拥有人应占溢利", "归属于母公司股东的利润"],
    "eps_basic": ["每股基本盈利", "基本每股收益"],
    "gross_profit": ["毛利"],
    "operating_cash_flow": ["经营业务现金净额", "经营活动产生的现金流量净额"],
}


def stock_id(code):
    r = S.get(f"{BASE}/search/prefix.do", params=dict(callback="callback", lang="ZH", type="A", name=code, market="SEHK"))
    body = json.loads(r.text[r.text.index("(") + 1: r.text.rindex(")")])
    return next(x["stockId"] for x in body["stockInfo"] if x["code"] == code)


def search(sid, t1code, t2gcode=-2, t2code=-2):
    p = dict(sortDir=0, sortByOptions="DateTime", category=0, market="SEHK", stockId=sid, documentType=-1,
             fromDate="20250101", toDate="20261231", title="", searchType=1, t1code=t1code, t2Gcode=t2gcode,
             t2code=t2code, rowRange=50, lang="zh")
    d = S.get(f"{BASE}/search/titleSearchServlet.do", params=p).json()
    rows = json.loads(d["result"]) if d.get("result") and d["result"] != "null" else []
    for x in rows:
        x["LONG_TEXT"] = html.unescape(x["LONG_TEXT"])
    return rows


def download(row, code, tag):
    url = BASE + row["FILE_LINK"]
    resp = S.get(url)
    resp.raise_for_status()
    path = save(RAW / "hk" / f"{code}_{tag}_{url.split('/')[-1]}", resp.content)
    n_pages, chars, text = pdf_profile(path)
    return {"title": row["TITLE"], "category": row["LONG_TEXT"], "date": row["DATE_TIME"], "url": url,
            "path": str(path), "bytes": len(resp.content), "pages": n_pages, "chars_first_pages": chars[:5],
            "type": "文字版PDF" if is_text_pdf(chars) else "疑似扫描版PDF"}, text


def em_fields(code, period):
    out = {}
    for sheet in ("利润表", "现金流量表"):
        df = ak.stock_financial_hk_report_em(stock=code, symbol=sheet, indicator="报告期")
        df = df[df["REPORT_DATE"].astype(str).str.startswith(period)]
        names = dict(zip(df["STD_ITEM_NAME"], df["AMOUNT"]))
        out.setdefault("_items_" + sheet, list(names))
        for field, cands in ITEMS.items():
            for c in cands:
                if c in names and field not in out:
                    out[field] = {"item": c, "val": float(names[c])}
    return out


def main():
    results = []
    for c in COMPANIES:
        rec = {k: c[k] for k in ("code", "name", "industry")}
        try:
            sid = stock_id(c["code"])
            reports = search(sid, 40000)  # 財務報表/ESG
            report = next(r for r in reports if ("中期" in r["LONG_TEXT"] or "年報" in r["LONG_TEXT"]))
            rec["report"], text_r = download(report, c["code"], "report")
            # results announcements (業績公告) usually come out weeks before the full report
            anns = [r for r in search(sid, 10000, 3) if "業績" in r["LONG_TEXT"]]
            rec["results_announcements"] = [{"date": r["DATE_TIME"], "title": r["TITLE"], "cat": r["LONG_TEXT"]} for r in anns[:4]]
            text_a = ""
            if anns:
                rec["announcement"], text_a = download(anns[0], c["code"], "ann")
            period = "2026-06-30" if "中期" in report["LONG_TEXT"] else "2025-12-31"
            rec["period"] = period
            rec["structured"] = em_fields(c["code"], period)
            checks = {}
            for field in ITEMS:
                if field in rec["structured"]:
                    v = rec["structured"][field]["val"]
                    scales = (1,) if field == "eps_basic" else (1, 1e3, 1e6)
                    dec = (2, 3, 4) if field == "eps_basic" else (0,)
                    checks[field] = {"val": v,
                                     "in_report": find_in_text(v, text_r, scales=scales, decimals=dec)[:3],
                                     "in_announcement": find_in_text(v, text_a, scales=scales, decimals=dec)[:3] if text_a else None}
                else:
                    checks[field] = "AKShare 无此科目"
            rec["text_check"] = checks
            rec["ok"] = True
        except Exception as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    dump_json(results, RAW / "hk" / "results.json")


if __name__ == "__main__":
    main()
