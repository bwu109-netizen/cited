"""Pick the pages worth sending to the model: financial statements, key-figure tables, MD&A."""
import math
import re

from . import config
from .textnorm import _T2S, for_match

GROUPS = {
    "income": [r"合并利润表", r"合併利潤表", r"綜合損益表", r"综合损益表", r"綜合收益表", r"综合收益表", r"損益表",
               r"收益表", r"利润表", r"statementsofoperations", r"statementsofincome", r"incomestatement",
               r"statementofincome", r"statementofprofitorloss", r"consolidatedstatementsofcomprehensiveincome"],
    "cashflow": [r"现金流量表", r"現金流量表", r"statementsofcashflows", r"statementofcashflows", r"cashflowstatement",
                 r"经营活动产生的现金流量净额", r"經營活動(所得|產生)的?現金(流量)?淨額", r"營業活動產生之現金淨額",
                 r"netcash(provided|used|generated)", r"經營活動", r"经营活动"],
    "highlights": [r"主要会计数据和财务指标", r"主要會計數據", r"财务摘要", r"財務摘要", r"财务概要", r"財務概要", r"業績摘要",
                   r"业绩摘要", r"financialhighlights", r"selectedfinancialdata", r"financialsummary", r"keyfinancial",
                   r"同比變動", r"同比变动"],
    "eps": [r"基本每股收益", r"每股基本盈利", r"每股盈利", r"每股收益", r"basicearningspershare", r"earningspershare",
            r"basic"],
    "mdna": [r"管理层讨论与分析", r"管理層討論及分析", r"management'?sdiscussionandanalysis", r"业务回顾", r"業務回顧",
             r"经营情况讨论", r"分部", r"segment", r"业务概要", r"業務概要", r"经营情况", r"運營資料", r"运营数据",
             r"净息差", r"淨息差", r"不良贷款率", r"netinterestmargin", r"毛利率", r"grossmargin"],
    "bank": [r"利息净收入", r"净利息收入", r"淨利息收入", r"netinterestincome", r"拨备前", r"撥備前", r"preprovision",
             r"信用减值损失", r"預期信貸損失", r"provisionforcreditlosses", r"业务及管理费", r"營業支出"],
}
# for_match() text is lowercase simplified Chinese: normalize the patterns the same way
GROUPS = {g: [_T2S.convert(p).lower() for p in pats] for g, pats in GROUPS.items()}
PICKS = {"income": 3, "cashflow": 2, "highlights": 3, "eps": 2, "mdna": 4, "bank": 2}
BIG_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+")


def score_pages(pages):
    scores = []
    for p in pages:
        t = for_match(p["text"])
        dens = math.log1p(len(BIG_NUMBER.findall(p["text"])))
        head = t[:400]  # statement titles sit at the top of the page; notes merely mention them
        s = {}
        for g, pats in GROUPS.items():
            hits = sum(len(re.findall(pat, t)) for pat in pats)
            hits += 5 * sum(len(re.findall(pat, head)) for pat in pats)
            s[g] = hits * (0.3 + dens)  # TOC pages mention every title but carry few numbers
        scores.append(s)
    return scores


def select_pages(pages, budget=None, template_hint=None):
    """Return (selected page numbers sorted, {group: [pages]}). Statement pages also pull in the next page,
    since statements often continue."""
    budget = budget or config.PAGE_CHAR_BUDGET
    scores = score_pages(pages)
    by_num = {p["page"]: p for p in pages}
    chosen, groups = [], {}
    order = ["income", "highlights", "cashflow", "eps", "bank", "mdna"]
    for g in order:
        ranked = sorted(range(len(pages)), key=lambda i: scores[i][g], reverse=True)
        top = [pages[i]["page"] for i in ranked[:PICKS[g]] if scores[i][g] > 0]
        groups[g] = top
        for n in top:
            for m in ([n, n + 1] if g in ("income", "cashflow") else [n]):
                if m in by_num and m not in chosen:
                    chosen.append(m)
    sel, used = [], 0
    for n in chosen:  # priority order = order of groups above
        size = len(by_num[n]["text"])
        if used + size > budget:
            continue
        sel.append(n)
        used += size
    return sorted(sel), groups
