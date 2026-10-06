"""Find and download the source report for (market, code, period). Logic ported from scripts/*.py.

Each fetcher returns a dict:
  market, code, name, period, period_end (nominal ISO date), fiscal_year_end (MM-DD),
  doc_kind (e.g. '10-Q', '半年度报告', '業績公告', '中期報告'), title, url, path, filed,
  industry {source, code, name}, extra {...}
"""
import html
import json
import re
from datetime import date, datetime, timedelta

from .http import SEC, WEB, cached_download, cached_json
from .periods import parse_period, period_end

PERIODIC_FORMS = ("10-Q", "10-K", "20-F", "40-F")
FP_OF = {"Q1": "Q1", "Q2": "Q2", "H1": "Q2", "Q3": "Q3", "FY": "FY"}


# ---------------------------------------------------------------- US (SEC EDGAR)

def sec_submissions(cik):
    return cached_json(("sec-sub", cik), lambda: SEC.get(f"https://data.sec.gov/submissions/CIK{cik}.json").json())


def sec_companyfacts(cik):
    return cached_json(("sec-cf", cik),
                       lambda: SEC.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json())


def sec_cik(ticker):
    tickers = cached_json(("sec-tickers",), lambda: SEC.get("https://www.sec.gov/files/company_tickers.json").json())
    for row in tickers.values():
        if row["ticker"].upper() == ticker.upper():
            return f"{int(row['cik_str']):010d}"
    raise LookupError(f"ticker {ticker} not found in SEC company_tickers.json")


def fetch_us(code, period, download=True):
    year, part = parse_period(period)
    cik = sec_cik(code)
    sub = sec_submissions(cik)
    cf = sec_companyfacts(cik)
    # accession -> (fy, fp, form) from the facts the filing itself reported
    meta = {}
    for tag in cf["facts"].get("us-gaap", {}).values():
        for unit in tag["units"].values():
            for f in unit:
                if f.get("form") in PERIODIC_FORMS:
                    meta.setdefault(f["accn"], (f.get("fy"), f.get("fp"), f["form"]))
    want_fp = FP_OF[part]
    accns = [a for a, (fy, fp, _) in meta.items() if fy == year and fp == want_fp]
    r = sub["filings"]["recent"]
    idx = [i for i, a in enumerate(r["accessionNumber"]) if a in accns and r["form"][i] in PERIODIC_FORMS]
    # "recent" holds only the last 1,000 filings; frequent issuers (e.g. banks filing 424B2s daily) push
    # their 10-Qs into the older pages listed under filings.files
    for extra in ([] if idx else sub["filings"].get("files", [])):
        r = cached_json(("sec-sub-page", extra["name"]),
                        lambda n=extra["name"]: SEC.get(f"https://data.sec.gov/submissions/{n}").json(), daily=False)
        idx = [i for i, a in enumerate(r["accessionNumber"]) if a in accns and r["form"][i] in PERIODIC_FORMS]
        if idx:
            break
    if not idx:
        # companyfacts may lack a filing's XBRL (seen: Citigroup 2026 10-Qs): fall back to the report date
        fye = sub.get("fiscalYearEnd") or "1231"
        nominal = period_end(period, f"{fye[:2]}-{fye[2:]}")
        r = sub["filings"]["recent"]
        idx = [i for i, f in enumerate(r["form"]) if f in PERIODIC_FORMS and r["reportDate"][i]
               and abs((date.fromisoformat(r["reportDate"][i]) - nominal).days) <= 10
               and (f in ("10-K", "20-F", "40-F")) == (part == "FY")]
    if not idx:
        raise LookupError(f"no {want_fp} FY{year} periodic filing for {code} (CIK {cik}) in SEC filings")
    i = min(idx, key=lambda k: r["filingDate"][k])  # original, not later amendments
    accn = r["accessionNumber"][i]
    url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{r['primaryDocument'][i]}")
    path = cached_download(SEC, url, f"us/{code}", f"{accn}_{r['primaryDocument'][i]}") if download else None
    fye = sub.get("fiscalYearEnd") or "1231"
    return {
        "market": "us", "code": code.upper(), "name": sub["name"], "period": period,
        "period_end": r["reportDate"][i], "fiscal_year_end": f"{fye[:2]}-{fye[2:]}",
        "doc_kind": r["form"][i], "title": f"{r['form'][i]} {r['reportDate'][i]}", "url": url, "path": str(path) if path else None,
        "filed": r["filingDate"][i],
        "industry": {"source": "SEC SIC", "code": sub.get("sic"), "name": sub.get("sicDescription")},
        "extra": {"cik": cik, "accession": accn},
    }


# ---------------------------------------------------------------- A-share (cninfo)

A_CATEGORY = {"H1": "category_bndbg_szsh", "Q2": "category_bndbg_szsh", "Q1": "category_yjdbg_szsh",
              "Q3": "category_sjdbg_szsh", "FY": "category_ndbg_szsh"}
A_SKIP = ("摘要", "英文", "取消", "已取消")


def cninfo_org(code):
    rows = cached_json(("cninfo-org", code), lambda: WEB.post(
        "http://www.cninfo.com.cn/new/information/topSearch/query", data={"keyWord": code, "maxNum": 5}).json(),
        daily=False)
    for x in rows:
        if x["code"] == code:
            return x
    raise LookupError(f"cninfo: no orgId for {code}")


def cninfo_industry(code):
    import akshare as ak

    def fetch():
        df = ak.stock_profile_cninfo(symbol=code)
        row = df.iloc[0]
        return {"name": str(row.get("所属行业", "")), "company": str(row.get("公司名称", ""))}
    return cached_json(("cninfo-profile", code), fetch, daily=False)


def fetch_a(code, period, download=True):
    year, part = parse_period(period)
    org = cninfo_org(code)
    column = "szse" if code.startswith(("0", "3")) else "sse"
    data = dict(pageNum=1, pageSize=30, column=column, tabName="fulltext", plate="", stock=f"{code},{org['orgId']}",
                searchkey="", secid="", category=A_CATEGORY[part] + ";", trade="",
                seDate=f"{year}-01-01~{year + 1}-12-31", sortName="", sortType="", isHLtitle="true")
    anns = cached_json(("cninfo-q", code, period), lambda: WEB.post(
        "http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data).json().get("announcements") or [])
    def title(a):  # some titles carry spaces ("2025 年半年度报告") or highlight tags
        return re.sub(r"<[^>]+>|\s+", "", a["announcementTitle"])
    # "2025年半年度报告" / "2025 年…" / "工商银行2025半年度报告" (no 年)
    year_re = re.compile(rf"(?<!\d){year}(?!\d)")
    cands = [a for a in anns if year_re.search(title(a)) and not any(k in title(a) for k in A_SKIP)]
    if not cands:
        raise LookupError(f"cninfo: no {period} report for {code}; titles seen: {[a['announcementTitle'] for a in anns][:6]}")
    a = cands[0]  # newest first: a 更新后/修订 version wins over the original
    url = "http://static.cninfo.com.cn/" + a["adjunctUrl"]
    path = cached_download(WEB, url, f"a/{code}", a["adjunctUrl"].split("/")[-1]) if download else None
    ind = cninfo_industry(code)
    title = re.sub(r"<[^>]+>", "", a["announcementTitle"])
    return {
        "market": "a", "code": code, "name": a.get("secName") or ind.get("company"), "period": period,
        "period_end": period_end(period).isoformat(), "fiscal_year_end": "12-31",
        "doc_kind": "定期报告", "title": title, "url": url, "path": str(path) if path else None,
        "filed": datetime.fromtimestamp(a["announcementTime"] / 1000).date().isoformat(),
        "industry": {"source": "cninfo 证监会行业", "code": None, "name": ind.get("name")},
        "extra": {"orgId": org["orgId"]},
    }


# ---------------------------------------------------------------- HK (HKEXnews)

HKEX = "https://www1.hkexnews.hk"
HK_RESULT_CAT = {"H1": "中期業績", "Q2": "中期業績", "FY": "末期業績", "Q1": "季度業績", "Q3": "季度業績"}
HK_REPORT_CAT = {"H1": "中期", "Q2": "中期", "FY": "年報"}


def hk_stock_id(code):
    def fetch():
        r = WEB.get(f"{HKEX}/search/prefix.do", params=dict(callback="callback", lang="ZH", type="A", name=code,
                                                              market="SEHK"))
        body = json.loads(r.text[r.text.index("(") + 1: r.text.rindex(")")])
        return next(x for x in body["stockInfo"] if x["code"] == code)
    return cached_json(("hk-sid", code), fetch, daily=False)


def hk_profile(code):
    import akshare as ak

    def fetch():
        row = ak.stock_hk_company_profile_em(symbol=code).iloc[0]
        return {"industry": row.get("所属行业"), "fye": row.get("年结日") or "12-31", "name": row.get("公司名称")}
    return cached_json(("hk-profile", code), fetch, daily=False)


def hk_search(sid, t1code, t2gcode=-2, t2code=-2, year=None):
    p = dict(sortDir=0, sortByOptions="DateTime", category=0, market="SEHK", stockId=sid, documentType=-1,
             fromDate=f"{year - 1}0101", toDate=f"{year + 1}1231", title="", searchType=1, t1code=t1code,
             t2Gcode=t2gcode, t2code=t2code, rowRange=100, lang="zh")

    def fetch():
        d = WEB.get(f"{HKEX}/search/titleSearchServlet.do", params=p).json()
        rows = json.loads(d["result"]) if d.get("result") and d["result"] != "null" else []
        for x in rows:
            x["LONG_TEXT"] = html.unescape(x["LONG_TEXT"])
            x["TITLE"] = html.unescape(x["TITLE"])
        return rows
    return cached_json(("hk-search", p), fetch)


def _hk_date(s):
    return datetime.strptime(s, "%d/%m/%Y %H:%M").date()


def fetch_hk(code, period, download=True):
    year, part = parse_period(period)
    prof = hk_profile(code)
    pend = period_end(period, prof["fye"])
    sid = hk_stock_id(code)["stockId"]

    def in_window(row, days):
        d = _hk_date(row["DATE_TIME"])
        return pend < d <= pend + timedelta(days=days)

    anns = [r for r in hk_search(sid, 10000, 3, year=year)
            if HK_RESULT_CAT[part] in r["LONG_TEXT"] and in_window(r, 150)]
    parts = []
    if anns:
        first_day = min(_hk_date(r["DATE_TIME"]) for r in anns)
        same_day = sorted([r for r in anns if _hk_date(r["DATE_TIME"]) == first_day],
                          key=lambda r: datetime.strptime(r["DATE_TIME"], "%d/%m/%Y %H:%M"))
        # some issuers split one results announcement into several PDFs ("第一部分" / "第二部分" / "Part 1")
        # ...or put the full statements in a second same-day document (e.g. HKEX: announcement at 12:00,
        # condensed financial statements at 16:45): merge every same-day results document
        multi = [r for r in same_day if re.search(r"第[一二三四五六]部|Part\s*\d", r["TITLE"], re.I)] or same_day
        if len(multi) > 1:
            multi.sort(key=lambda r: (_part_no(r["TITLE"]), r["DATE_TIME"]))
            row, parts = multi[0], multi
        else:
            row = same_day[0]
        kind = "業績公告"
    else:
        reports = [r for r in hk_search(sid, 40000, year=year)
                   if part in HK_REPORT_CAT and HK_REPORT_CAT[part] in r["LONG_TEXT"] and in_window(r, 200)]
        if not reports:
            raise LookupError(f"HKEXnews: no results announcement or report for {code} {period} (period end {pend})")
        row, kind = sorted(reports, key=lambda r: _hk_date(r["DATE_TIME"]))[0], "中期報告/年報"
    url = HKEX + row["FILE_LINK"]
    path = cached_download(WEB, url, f"hk/{code}", url.split("/")[-1]) if download else None
    part_paths = []
    for r in parts:
        u = HKEX + r["FILE_LINK"]
        part_paths.append({"title": r["TITLE"], "url": u,
                           "path": str(cached_download(WEB, u, f"hk/{code}", u.split("/")[-1])) if download else None})
    return {
        "market": "hk", "code": code, "name": prof.get("name"), "period": period, "period_end": pend.isoformat(),
        "fiscal_year_end": prof["fye"], "doc_kind": kind, "title": row["TITLE"], "url": url, "path": str(path) if path else None,
        "filed": _hk_date(row["DATE_TIME"]).isoformat(),
        "industry": {"source": "东财港股 所属行业", "code": None, "name": prof.get("industry")},
        "extra": {"stockId": sid, "category": row["LONG_TEXT"]},
        "parts": part_paths,  # non-empty when the announcement is split over several PDFs (merged on parse)
    }


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}


def _part_no(title):
    m = re.search(r"第([一二三四五六])部", title) or re.search(r"Part\s*(\d)", title, re.I)
    if not m:
        return 99
    return _CN_NUM.get(m.group(1)) or int(m.group(1))


FETCHERS = {"us": fetch_us, "a": fetch_a, "hk": fetch_hk}


def fetch_report(market, code, period, download=True):
    """download=False only resolves which document it would be (no file fetched; 'path' is None)."""
    return FETCHERS[market](code, period, download=download)
