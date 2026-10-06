"""Verification layer: pure code, no model calls. See docs/metrics_spec.md §7.

C1 quote is on the page (exact, else fuzzy >= 0.90; ±1 page allowed but flagged)
C2 the number itself appears EXACTLY on that page's normalized text (not just in the model's quote)
C3 unit and currency parse
C4 converted value matches the benchmark within rounding tolerance
"""
import re
from datetime import date
from difflib import SequenceMatcher

from .textnorm import for_match, for_numbers
from .units import UnitError, currency_code, digits_of, to_value

OK, FOUND, BAD = "✅", "⚠️", "❌"
FUZZY_MIN = 0.90
PER_SHARE_FIELDS = {"eps_basic", "eps_basic_per_ads"}


# ---------------------------------------------------------------- primitives

def fuzzy_ratio(needle, hay):
    """Best similarity of `needle` against any same-length window of `hay` (both already normalized)."""
    if not needle:
        return 0.0
    if needle in hay:
        return 1.0
    n = len(needle)
    if n > len(hay):
        return SequenceMatcher(None, needle, hay, autojunk=False).ratio()
    step = max(1, n // 8)
    best, best_i = 0.0, 0
    for i in range(0, len(hay) - n + 1, step):
        r = SequenceMatcher(None, needle, hay[i:i + n], autojunk=False).quick_ratio()
        if r > best:
            best, best_i = r, i
    # refine around the best coarse window with the exact ratio
    lo, hi = max(0, best_i - step), min(len(hay) - n, best_i + step)
    best = 0.0
    for i in range(lo, hi + 1):
        best = max(best, SequenceMatcher(None, needle, hay[i:i + n], autojunk=False).ratio())
    return best


def segments_on_page(q, t, max_pieces=3, min_piece=4):
    """Can normalized quote q be cut into <= max_pieces pieces that each occur verbatim in t?
    PDF tables often put a row label and its numbers on different text lines; the model quotes them as one row."""
    pieces, rest = 0, q
    while rest:
        pieces += 1
        if pieces > max_pieces:
            return False
        for i in range(len(rest), min_piece - 1, -1):
            if rest[:i] in t:
                rest = rest[i:]
                break
        else:
            return False
    return True


# currency symbols are presentation: SEC tables put "$" in its own cell on some rows only
_CURRENCY_SYMBOLS = re.compile(r"(?:us|hk|nt|a|c|s)?\$|[¥￥€£]")


def quote_on_page(quote, page_text):
    """Return (passed, ratio). ratio 1.0 = exact, 0.99 = verbatim pieces split across lines, else fuzzy."""
    q = _CURRENCY_SYMBOLS.sub("", for_match(quote))
    t = _CURRENCY_SYMBOLS.sub("", for_match(page_text))
    if not q:
        return False, 0.0
    if q in t:
        return True, 1.0
    if segments_on_page(q, t):
        return True, 0.99
    r = fuzzy_ratio(q, t)
    return r >= FUZZY_MIN, r


def number_on_page(raw_value, page_text):
    """Exact whole-number match of the bare digits of raw_value in the page text."""
    num = digits_of(raw_value)
    pat = r"(?<![\d.])" + re.escape(num) + r"(?![\d]|\.\d)"
    return re.search(pat, for_numbers(page_text)) is not None


def number_split_on_page(raw_value, page_text):
    """Number present only once whitespace/newlines inside it are removed: a PDF extraction artefact."""
    num = digits_of(raw_value)
    squashed = re.sub(r"\s+", "", for_numbers(page_text))
    return re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d]|\.\d)", squashed) is not None


# ---------------------------------------------------------------- one raw number

def check_number(item, pages, market):
    """Run C1-C3 on one raw item (field or component). Returns a dict of results."""
    by_num = {p["page"]: p["text"] for p in pages}
    res = {"c1": False, "c2": False, "c3": False, "reasons": [], "category": None, "page_used": None}
    try:
        page = int(item.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    quote, raw = item.get("quote") or "", item.get("raw_value") or ""

    # C3 units first (needed for value)
    try:
        value, mult, kind, tol = to_value(raw, item.get("raw_unit"))
        res.update(value=value, multiplier=mult, unit_kind=kind, tolerance=tol, c3=True)
        cur = currency_code(item.get("raw_currency"), item.get("raw_unit"), market)
        res["currency"] = cur
        # industry metrics may be counts (users, GWh); core money fields must have a currency
        no_currency_ok = str(item.get("field", "")).startswith("industry:") or item.get("field") == "weighted_avg_shares_basic"
        if kind != "ratio" and cur is None and not no_currency_ok:
            res["c3"] = False
            res["reasons"].append(f"币种无法识别：{item.get('raw_currency')!r}/{item.get('raw_unit')!r}")
        if item.get("field") in PER_SHARE_FIELDS and mult != 1:
            res["c3"] = False
            res["reasons"].append(f"每股数据的单位倍数应为 1，得到 {mult}（{item.get('raw_unit')!r}）")
    except UnitError as e:
        res["reasons"].append(f"单位/数字无法解析：{e}")
    if not res["c3"]:
        res["category"] = "单位"

    # C1 quote on claimed page, else ±1 page
    tried = [page, page - 1, page + 1]
    for p in tried:
        if p in by_num:
            ok, ratio = quote_on_page(quote, by_num[p])
            if ok:
                res.update(c1=True, page_used=p, quote_ratio=round(ratio, 3))
                if p != page:
                    res["reasons"].append(f"引用在第 {p} 页而不是模型给的第 {page} 页")
                    res["page_off"] = True
                break
    if not res["c1"]:
        res["quote_ratio"] = round(quote_on_page(quote, by_num.get(page, ""))[1], 3) if page in by_num else 0.0
        other = [p for p, t in by_num.items() if p not in tried and quote_on_page(quote, t)[0]]
        if other:
            res["reasons"].append(f"引用不在第 {page} 页（±1），而在第 {other[:3]} 页")
            res["category"] = res["category"] or "页码错"
        else:
            res["reasons"].append(f"引用在全文找不到（第 {page} 页最高相似度 {res['quote_ratio']}）")

    # C2 exact number on the page where the quote was found (or the claimed page)
    check_page = res["page_used"] or page
    try:
        res["c2"] = check_page in by_num and number_on_page(raw, by_num[check_page])
    except UnitError:
        res["c2"] = False
    if not res["c2"] and raw:
        try:
            elsewhere = [p for p, t in by_num.items() if p != check_page and number_on_page(raw, t)]
            split = check_page in by_num and number_split_on_page(raw, by_num[check_page])
        except UnitError:
            elsewhere, split = [], False
        if split:
            res["reasons"].append(f"数字 {raw} 在第 {check_page} 页被 PDF 抽字拆开")
            res["category"] = res["category"] or "解析问题"
        elif elsewhere:
            res["reasons"].append(f"数字 {raw} 不在第 {check_page} 页，但在第 {elsewhere[:5]} 页")
            res["category"] = res["category"] or "页码错"
        else:
            res["reasons"].append(f"数字 {raw} 在全文任何页都找不到")
            res["category"] = "数字编造"
    if not res["c1"] and res["category"] is None:
        res["category"] = "引用改写"  # the number is on the page; only the quote was paraphrased
    return res


# ---------------------------------------------------------------- benchmark comparison

def _close(a, b, tol):
    return abs(a - b) <= tol + 1e-9 * abs(b)


def _same_end(a, b, days=7):
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days) <= days
    except (TypeError, ValueError):
        return False


def compare_benchmark(field, period_type, period_end, value, tol, currency, benchmarks, bench_invalid):
    """Return (state, info) where state in {'match', 'mismatch', 'none', 'invalid'}."""
    cands = [b for b in benchmarks if b["field"] == field and _same_end(b["period_end"], period_end)]
    same_type = [b for b in cands if b["period_type"] == period_type]
    if bench_invalid and same_type:
        return "invalid", {"benchmark": same_type[0], "reason": bench_invalid}
    if currency:
        cur_ok = [b for b in same_type if b["currency"] in (None, currency)]
        if same_type and not cur_ok:
            return "mismatch", {"benchmark": same_type[0], "category": "口径",
                                "reason": f"标准答案币种 {same_type[0]['currency']} ≠ 原文币种 {currency}"}
        same_type = cur_ok
    if not same_type:
        return "none", {}
    b = same_type[0]
    if _close(value, b["value"], tol):
        return "match", {"benchmark": b}
    # classify the mismatch
    other_type = [x for x in cands if x["period_type"] != period_type and _close(value, x["value"], tol)]
    if other_type:
        return "mismatch", {"benchmark": b, "category": "期间",
                            "reason": f"抽取值等于标准答案的 {other_type[0]['period_type']} 期间值"}
    for k in (3, 4, 6, 8, -3, -4, -6, -8):
        if b["value"] and _close(value * 10 ** k, b["value"], abs(b["value"]) * 1e-6 + tol * 10 ** k):
            return "mismatch", {"benchmark": b, "category": "单位", "reason": f"差 10^{k} 倍"}
    if b["value"] and _close(-value, b["value"], tol):
        return "mismatch", {"benchmark": b, "category": "口径", "reason": "符号相反"}
    return "mismatch", {"benchmark": b, "category": "口径",
                        "reason": f"抽取 {value:,.4f} vs 标准答案 {b['value']:,.4f}（{b['source_field']}）"}


# ---------------------------------------------------------------- whole report

def _eps_probe(items, benchmarks, market):
    """HK benchmarks carry no trustworthy currency: if benchmark EPS / report EPS is not ~1, the source
    converted currencies and none of its numbers are a valid answer."""
    if market != "hk":
        return None
    for it in items:
        if it["field"] == "eps_basic" and it.get("value") and it.get("c3"):
            b = [x for x in benchmarks if x["field"] == "eps_basic" and x["period_type"] == it["period_type"]]
            if b and b[0]["value"]:
                ratio = b[0]["value"] / it["value"]
                if abs(ratio - 1) > 0.02:
                    return (f"标准答案疑似已换算币种（东财 EPS {b[0]['value']} / 原文 EPS {it['value']} = {ratio:.4f}），"
                            f"属口径差异，不参与核对")
                return None
    return None


REQUIRED = {"general": ["revenue", "net_income_parent", "eps_basic", "operating_cash_flow"],
            "bank": ["revenue", "net_income_parent", "eps_basic", "operating_cash_flow", "net_interest_income", "ppop"],
            "insurance": ["revenue", "net_income_parent", "eps_basic", "operating_cash_flow"]}
FLOW_FIELDS_WITH_Q = ["revenue", "net_income_parent", "eps_basic"]


def expected_pairs(items, benchmarks, template, doc):
    """(field, period_type) pairs a complete extraction must contain:
    - every required field for the report's cumulative period;
    - every core field/period the benchmark has;
    - the single quarter (Q) of revenue / net income / EPS when the income statement itself shows a Q column,
      i.e. Q and cumulative revenue were read from the same page (a Q figure that only appears in a summary
      or in narrative text does not imply a full quarterly statement)."""
    from .periods import cumulative_type, parse_period
    from .templates import FIELDS

    cum = cumulative_type(parse_period(doc["period"])[1])
    exp = {(f, cum) for f in REQUIRED[template]}
    exp |= {(b["field"], b["period_type"]) for b in benchmarks
            if b["field"] in FIELDS[template] and _same_end(b["period_end"], doc["period_end"])}
    page_of = lambda t: next((it.get("page_used") for it in items
                              if it.get("field") == "revenue" and it.get("period_type") == t and it.get("c2")), None)
    if cum != "Q" and page_of("Q") is not None and page_of("Q") == page_of(cum):
        exp |= {(f, "Q") for f in FLOW_FIELDS_WITH_Q}
    return exp


def missing_pairs(items, benchmarks, template, doc):
    have = {(it.get("field"), it.get("period_type")) for it in items}
    # a derived gross profit counts; cost_of_revenue alone is fine when gross is not on the statement
    return sorted(p for p in expected_pairs(items, benchmarks, template, doc) if p not in have)


def status_of(r, bench_state):
    if not (r["c1"] and r["c2"] and r["c3"]):
        return BAD
    if bench_state == "match":
        return OK
    if bench_state == "mismatch":
        return BAD
    return FOUND


def verify_report(raw_items, raw_metrics, pages, doc, template, benchmarks, prior=None):
    """Return verified core items, industry metrics and dropped (comparative/duplicate) items.
    prior: structured cumulative values of the previous quarter-end (for the Q + prior ≈ YTD check)."""
    from .sanity import apply_sanity
    from .periods import type_from_days
    from .templates import FIELDS

    market, target_end = doc["market"], doc["period_end"]
    kept, dropped, seen = [], [], set()

    def normalize_period(it):
        notes = []
        if it.get("period_type") == "PIT":  # point-in-time balance: no duration to check
            it["period_start"] = None
            return notes
        s, e = it.get("period_start"), it.get("period_end")
        try:
            days = (date.fromisoformat(e) - date.fromisoformat(s)).days
            t = type_from_days(days)
            if it.get("period_type") != t:
                notes.append(f"模型标的期间类型 {it.get('period_type')} 与起止日期（{days} 天）不符，按日期改为 {t}")
                it["period_type"] = t
        except (TypeError, ValueError):
            pass
        return notes

    for it in raw_items:
        it = dict(it)
        notes = normalize_period(it)
        if not _same_end(it.get("period_end"), target_end):
            it["drop_reason"] = f"期末 {it.get('period_end')} 不是目标期末 {target_end}（对比期或其他期间）"
            dropped.append(it)
            continue
        key = (it.get("field"), it.get("period_type"))
        if key in seen:
            it["drop_reason"] = "重复"
            dropped.append(it)
            continue
        seen.add(key)
        it["notes"] = notes
        kept.append(it)

    # C1-C3 per item (and per component of derived items)
    for it in kept:
        if it.get("derivation") == "derived" and it.get("components"):
            comps = []
            for c in it["components"]:
                c = dict(c, field=it["field"] + ":" + str(c.get("name")))
                c.update(check_number(c, pages, market))
                comps.append(c)
            it["components"] = comps
            good = all(c["c1"] and c["c2"] and c["c3"] for c in comps)
            it.update(c1=good, c2=good, c3=good,
                      reasons=[f"组成项 {c['name']}：{'；'.join(c['reasons'])}" for c in comps if c["reasons"]],
                      category=next((c["category"] for c in comps if c["category"]), None))
            if good:
                curs = {c.get("currency") for c in comps}
                # sign says add/subtract; costs are often printed in parentheses, so use the magnitude
                it["value"] = sum((1 if float(c.get("sign", 1)) >= 0 else -1) * abs(c["value"]) for c in comps)
                it["tolerance"] = sum(c["tolerance"] for c in comps)
                it["currency"] = curs.pop() if len(curs) == 1 else None
                it["page_used"] = comps[0]["page_used"]
        else:
            it.update(check_number(it, pages, market))

    # derive gross profit (A-share style) when the statement has no gross-profit line
    if template == "general":
        types_with_gp = {it["period_type"] for it in kept if it["field"] == "gross_profit"}
        for cost in [it for it in kept if it["field"] == "cost_of_revenue"]:
            rev = next((x for x in kept if x["field"] == "revenue" and x["period_type"] == cost["period_type"]), None)
            if cost["period_type"] in types_with_gp or not rev:
                continue
            good = all(x.get(k) for x in (rev, cost) for k in ("c1", "c2", "c3"))
            gp = {"field": "gross_profit", "period_type": cost["period_type"], "period_end": cost["period_end"],
                  "derivation": "derived", "raw_value": None, "raw_unit": None,
                  "formula": "revenue − |cost_of_revenue|", "c1": good, "c2": good, "c3": good,
                  "reasons": [] if good else ["组成项（营业收入或营业成本）未通过核验"],
                  "category": None if good else (rev.get("category") or cost.get("category")),
                  "page": cost.get("page"), "quote": None, "notes": []}
            if good:
                # cost lines are printed positive (A-share) or in parentheses (US/HK): subtract the magnitude
                gp.update(value=rev["value"] - abs(cost["value"]), cost_used=abs(cost["value"]),
                          tolerance=rev["tolerance"] + cost["tolerance"],
                          currency=rev.get("currency"), page_used=cost.get("page_used"))
            kept.append(gp)

    bench_invalid = _eps_probe(kept, benchmarks, market)

    # C4 + status
    for it in kept:
        state, info = ("none", {})
        if it.get("c3") and it.get("value") is not None:
            state, info = compare_benchmark(it["field"], it["period_type"], it["period_end"], it["value"],
                                            it.get("tolerance", 0), it.get("currency"), benchmarks, bench_invalid)
        it["benchmark"] = info.get("benchmark")
        it["benchmark_state"] = state
        if state == "mismatch":
            it["reasons"].append("标准答案不一致：" + info["reason"])
            it["category"] = it.get("category") or info["category"]
            # main net income vs ordinary-shareholder benchmark (HK source)
            if it["field"] == "net_income_parent":
                common = next((x for x in kept if x["field"] == "net_income_common"
                               and x["period_type"] == it["period_type"] and x.get("value") is not None), None)
                if common and _close(common["value"], info["benchmark"]["value"], common.get("tolerance", 0)):
                    it["reasons"].append("标准答案等于普通股股东应占口径（net_income_common）")
                    it["category"] = "口径"
        elif state == "invalid":
            it["reasons"].append(info["reason"])
        it["status"] = status_of(it, state)

    # plausibility checks (pure code): a failure turns the item ❌ / 口径/推导
    # a currency-converted structured source (EPS probe) is no good for the Q + prior check either
    apply_sanity(kept, pages, doc, template, [] if bench_invalid else (prior or []))

    # expected (field, period) pairs that nothing was extracted for
    for f, ptype in missing_pairs(kept, benchmarks, template, doc):
        b = next((x for x in benchmarks if x["field"] == f and x["period_type"] == ptype
                  and _same_end(x["period_end"], target_end)), None)
        why = (f"标准答案有 {ptype} 期间的值 {b['value']:,.4f}，模型没有抽取" if b
               else f"按报告期应有 {ptype} 期间的值，模型没有抽取")
        kept.append({"field": f, "period_type": ptype, "period_end": target_end, "status": BAD, "category": "漏抽",
                     "benchmark": b, "benchmark_state": "missing", "reasons": [why],
                     "c1": False, "c2": False, "c3": False, "notes": []})

    metrics = []
    for m in raw_metrics:
        m = dict(m, field="industry:" + str(m.get("name")))
        normalize_period(m)
        m.update(check_number(m, pages, market))
        m["benchmark_state"] = "none"
        m["status"] = status_of(m, "none")
        metrics.append(m)
    return kept, metrics, dropped, bench_invalid
