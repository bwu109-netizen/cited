"""A-share feasibility: latest periodic report PDF from cninfo (巨潮资讯) + AKShare (Eastmoney F10) statements, cross-check.

Usage: .venv/bin/python scripts/a_share_cninfo.py
"""
import json

import akshare as ak

from common import BROWSER_UA, RAW, RateLimitedSession, dump_json, find_in_text, is_text_pdf, pdf_profile, save

S = RateLimitedSession(max_per_sec=2, user_agent=BROWSER_UA)

COMPANIES = [
    {"code": "600519", "name": "贵州茅台", "industry": "白酒", "column": "sse", "em": "SH600519"},
    {"code": "300750", "name": "宁德时代", "industry": "动力电池", "column": "szse", "em": "SZ300750"},
    {"code": "600036", "name": "招商银行", "industry": "银行", "column": "sse", "em": "SH600036"},
]
PERIODIC_CATEGORIES = "category_ndbg_szsh;category_bndbg_szsh;category_sjdbg_szsh;category_yjdbg_szsh;"


def org_id(code):
    r = S.post("http://www.cninfo.com.cn/new/information/topSearch/query", data={"keyWord": code, "maxNum": 5})
    return next(x["orgId"] for x in r.json() if x["code"] == code)


def latest_report(c, org):
    data = dict(pageNum=1, pageSize=30, column=c["column"], tabName="fulltext", plate="", stock=f"{c['code']},{org}",
                searchkey="", secid="", category=PERIODIC_CATEGORIES, trade="", seDate="2025-01-01~2026-12-31",
                sortName="", sortType="", isHLtitle="true")
    anns = S.post("http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data).json()["announcements"] or []
    # skip 摘要 / 英文版 / 更正 — we want the full Chinese report
    full = [a for a in anns if not any(k in a["announcementTitle"] for k in ("摘要", "英文", "取消", "更正"))]
    return full[0]


def em_fields(symbol, report_date):
    """Pull target fields from Eastmoney (via AKShare) income + cash-flow statements for one report date."""
    p = ak.stock_profit_sheet_by_report_em(symbol=symbol)
    cfs = ak.stock_cash_flow_sheet_by_report_em(symbol=symbol)
    p = p[p["REPORT_DATE"].astype(str).str.startswith(report_date)].iloc[0]
    cfs = cfs[cfs["REPORT_DATE"].astype(str).str.startswith(report_date)].iloc[0]
    g = lambda row, k: (None if k not in row.index or row[k] != row[k] else float(row[k]))  # NaN -> None
    out = {
        "report_type": p["REPORT_TYPE"], "currency": p.get("CURRENCY"), "unit": "元",
        "TOTAL_OPERATE_INCOME(营业总收入)": g(p, "TOTAL_OPERATE_INCOME"),
        "OPERATE_INCOME(营业收入)": g(p, "OPERATE_INCOME"),
        "OPERATE_COST(营业成本)": g(p, "OPERATE_COST"),
        "PARENT_NETPROFIT(归母净利润)": g(p, "PARENT_NETPROFIT"),
        "BASIC_EPS(基本每股收益)": g(p, "BASIC_EPS"),
        "NETCASH_OPERATE(经营现金流净额)": g(cfs, "NETCASH_OPERATE"),
        "n_income_cols": len(p.index), "n_cashflow_cols": len(cfs.index),
    }
    if out["OPERATE_INCOME(营业收入)"] and out["OPERATE_COST(营业成本)"]:
        out["gross_profit_derived(营业收入-营业成本)"] = out["OPERATE_INCOME(营业收入)"] - out["OPERATE_COST(营业成本)"]
    return out


def main():
    results = []
    for c in COMPANIES:
        rec = {k: c[k] for k in ("code", "name", "industry")}
        try:
            org = org_id(c["code"])
            a = latest_report(c, org)
            url = "http://static.cninfo.com.cn/" + a["adjunctUrl"]
            resp = S.get(url)
            resp.raise_for_status()
            path = save(RAW / "a" / f"{c['code']}_{a['adjunctUrl'].split('/')[-1]}", resp.content)
            n_pages, chars, text = pdf_profile(path)
            rec["doc"] = {"title": a["announcementTitle"], "url": url, "path": str(path), "bytes": len(resp.content),
                          "pages": n_pages, "chars_first_pages": chars[:5],
                          "type": "文字版PDF" if is_text_pdf(chars) else "疑似扫描版PDF"}
            # 半年报 -> 06-30, 一季报 -> 03-31, 三季报 -> 09-30, 年报 -> 12-31
            t = a["announcementTitle"]
            year = t[t.index("20"):t.index("20") + 4]
            mmdd = "06-30" if "半年" in t else "03-31" if ("一季" in t or "第一季" in t) else "09-30" if "三季" in t else "12-31"
            rec["period"] = f"{year}-{mmdd}"
            rec["structured"] = em_fields(c["em"], rec["period"])
            checks = {}
            for k, v in rec["structured"].items():
                if isinstance(v, float):
                    scales = (1,) if "EPS" in k else (1, 1e3, 1e4, 1e6, 1e8)
                    checks[k] = {"val": v, "found_as": find_in_text(v, text, scales=scales, decimals=(2,) if "EPS" in k else (0, 2))[:3]}
            rec["text_check"] = checks
            rec["ok"] = True
        except Exception as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    dump_json(results, RAW / "a" / "results.json")


if __name__ == "__main__":
    main()
