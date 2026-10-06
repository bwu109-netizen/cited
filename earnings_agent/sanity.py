"""Plausibility checks on verified items (pure code, no model). See docs/metrics_spec.md §7.3.

A failed check turns the item ❌ with category "口径/推导". Checks only fire when every input they need
is present; otherwise they are skipped silently (a missing input is reported elsewhere).
"""
import re

from .textnorm import for_numbers

BAD = "❌"
CATEGORY = "口径/推导"

# lines that state a disclosed total for a field we may have derived
DISCLOSED_LABELS = {
    "ppop": [r"拨备前利润", r"撥備前利潤", r"拨备前营业利润", r"pre-?provision (?:operating )?profit"],
    "gross_profit": [r"^\s*毛利(?![率潤润])", r"^\s*gross (?:profit|margin)(?! percentage| %)"],
    "net_income_parent": [r"归属于(?:母公司|本行|本公司)(?:所有者|股东)的净利润", r"本公司(?:擁有人|权益持有人|權益持有人)應佔",
                          r"attributable to (?:owners|shareholders|equity holders) of the (?:parent|company)"],
}
# attribution lines that mean "owners of the parent" > "ordinary shareholders"
OTHER_EQUITY = re.compile(r"其他權益持有人|其他权益持有人|其他权益工具持有者|永续债持有|永續債持有|优先股股东|優先股股東|"
                          r"other equity holders|preference shareholders|perpetual", re.I)
NUM = re.compile(r"\(?-?\d+(?:\.\d+)?\)?")
SCALES = (1, 1e3, 1e4, 1e6, 1e8, 1e9)
ADDITIVE = ("revenue", "net_income_parent", "gross_profit", "net_interest_income", "operating_cash_flow")


def _flag(it, reason):
    it.setdefault("reasons", []).append("合理性检查：" + reason)
    it.setdefault("sanity", []).append(reason)
    it["status"] = BAD
    it["category"] = CATEGORY


def _ok(it, name):
    it.setdefault("sanity_passed", []).append(name)


def _get(items, field, ptype):
    return next((x for x in items if x.get("field") == field and x.get("period_type") == ptype
                 and x.get("value") is not None), None)


def _numbers(line):
    out = []
    for m in NUM.findall(line):
        neg = m.startswith("(") or m.startswith("-")
        try:
            v = float(m.strip("()").lstrip("-"))
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def disclosed_values(pages, field):
    """Numbers on lines that start with / contain a disclosed-total label for `field`."""
    pats = [re.compile(p, re.I | re.M) for p in DISCLOSED_LABELS.get(field, [])]
    found = []
    for p in pages:
        for line in for_numbers(p["text"]).split("\n"):
            if any(pt.search(line) for pt in pats):
                nums = [n for n in _numbers(line) if abs(n) >= 100]  # skip note numbers / percentages
                if nums:
                    found.append((p["page"], line.strip()[:120], nums[:6]))
    return found


def _matches_any(value, nums, rel=0.005):
    return any(abs(n * s - value) <= rel * abs(value) for n in nums for s in SCALES)


def apply_sanity(items, pages, doc, template, prior):
    types = {x.get("period_type") for x in items}
    for t in types:
        rev = _get(items, "revenue", t)

        # 1. gross profit <= revenue; the cost used in the derivation must be >= 0
        gp = _get(items, "gross_profit", t)
        if gp and rev and gp["value"] > rev["value"] + gp.get("tolerance", 0) + rev.get("tolerance", 0):
            _flag(gp, f"毛利 {gp['value']:,.0f} 大于营业收入 {rev['value']:,.0f}")
        elif gp and rev:
            _ok(gp, "毛利≤营收")
        if gp and gp.get("cost_used") is not None and gp["cost_used"] < 0:
            _flag(gp, f"推导毛利时使用的营业成本为负数 {gp['cost_used']:,.0f}")

        # 1b. (banks) pre-provision profit <= revenue
        pp = _get(items, "ppop", t)
        if pp and rev and pp["value"] > rev["value"] + pp.get("tolerance", 0) + rev.get("tolerance", 0):
            _flag(pp, f"拨备前利润 {pp['value']:,.0f} 大于营业收入 {rev['value']:,.0f}")
        elif pp and rev:
            _ok(pp, "拨备前利润≤营收")

        # 2. only when the report lists other equity holders (perpetuals, preference, AT1): owners of the
        #    parent must exceed ordinary shareholders. Without them US GAAP can legitimately show ordinary >
        #    parent (e.g. mezzanine-equity adjustments), so no check.
        ni, common = _get(items, "net_income_parent", t), _get(items, "net_income_common", t)
        if ni and common:
            tol = ni.get("tolerance", 0) + common.get("tolerance", 0)
            page_txt = next((p["text"] for p in pages if p["page"] == common.get("page_used")), "")
            if OTHER_EQUITY.search(page_txt):
                if ni["value"] < common["value"] - tol:
                    _flag(ni, f"归母合计 {ni['value']:,.0f} 小于普通股股东应占 {common['value']:,.0f}")
                elif abs(ni["value"] - common["value"]) <= tol:
                    _flag(ni, "报告列示了其他权益持有人（永续债/优先股等）应占，但归母合计等于普通股股东应占，"
                              "疑似只取了普通股口径")
                else:
                    _ok(ni, "归母>普通股（有其他权益持有人）")

        # 3. derived value vs a disclosed total of the same field
        for f in ("ppop", "gross_profit", "net_income_parent"):
            it = _get(items, f, t)
            if not it or it.get("derivation") != "derived" or it.get("status") == BAD:
                continue
            found = disclosed_values(pages, f)
            if found and not any(_matches_any(it["value"], nums) for _, _, nums in found):
                pg, line, _ = found[0]
                _flag(it, f"推导值 {it['value']:,.0f} 与报告明示的数不一致（第 {pg} 页：{line}）")
            elif found:
                _ok(it, "推导值=明示值")

        # 4. EPS x weighted shares ~ net income (order of magnitude only)
        eps, sh = _get(items, "eps_basic", t), _get(items, "weighted_avg_shares_basic", t)
        base = common or ni
        if eps and sh and base and base["value"] and eps["value"]:
            ratio = eps["value"] * sh["value"] / base["value"]
            if not 0.5 <= ratio <= 2.0:
                _flag(eps, f"EPS × 加权股数 / 净利润 = {ratio:.3g}，数量级不符")
            else:
                _ok(eps, f"EPS×股数/净利润={ratio:.3f}")

    # 5. single quarter + previous cumulative ≈ year-to-date
    for f in ADDITIVE:
        q = _get(items, f, "Q")
        cum = next((x for x in items if x.get("field") == f and x.get("period_type") in ("H", "YTD", "FY")
                    and x.get("value") is not None), None)
        prev = next((p for p in prior if p["field"] == f), None)
        if not (q and cum and prev):
            continue
        tol = q.get("tolerance", 0) + cum.get("tolerance", 0) + 0.002 * abs(cum["value"])
        gap = q["value"] + prev["value"] - cum["value"]
        if abs(gap) > tol:
            msg = (f"单季 {q['value']:,.0f} + 截至 {prev['period_end']} 累计 {prev['value']:,.0f} "
                   f"≠ {cum['period_type']} {cum['value']:,.0f}（差 {gap:,.0f}）")
            _flag(q, msg)
            _flag(cum, msg)
        else:
            _ok(q, "单季+上季末累计≈累计")
            _ok(cum, "单季+上季末累计≈累计")
