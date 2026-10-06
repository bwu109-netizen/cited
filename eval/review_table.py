"""Build the HK answer-key review table (docs/eval_design.md §2.3) as one self-contained HTML file.

Each row = one scoring item (company, field, period). It shows the candidate values from the evaluation
runs and from the structured source (without saying where each came from, sorted by value), the lines
around the number on the report page, and a link to that PDF page. The reviewer picks a candidate,
rejects all, types a corrected value, or marks "not in report". Progress lives in localStorage and can be
exported / imported as JSON or CSV.

Usage:
  python eval/review_table.py --demo            # dev-set HK reports (data/output/hk_*_2026H1.json)
  python eval/review_table.py RUN_JSON ...      # evaluation outputs (after the frozen runs)
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from earnings_agent.parse import load_doc_pages  # noqa: E402
from earnings_agent.textnorm import for_numbers  # noqa: E402
from earnings_agent.units import digits_of  # noqa: E402

FIELD_NAMES = {"revenue": "营业收入", "net_income_parent": "归母净利润", "eps_basic": "基本每股收益",
               "gross_profit": "毛利", "operating_cash_flow": "经营现金流净额", "net_interest_income": "净利息收入",
               "ppop": "拨备前利润", "insurance_revenue": "保险服务收入", "insurance_service_result": "保险服务业绩"}
# short definitions for the reviewer (metrics_spec.md §2), not the model-prompt wording
REVIEW_DEFS = {
    "revenue": {"general": "利润表收入总额行（收入/營業額/Revenue），含“其他”分部；不是经调整口径。",
                "bank": "扣除预期信贷损失之前的营业收益净额（汇丰称“收入”）；不是扣 ECL 之后的数。",
                "insurance": "利润表收入总额行；新准则下没有总额行时可标“原文没有”。"},
    "net_income_parent": "归属于母公司所有者的净利润合计（含永续债等其他权益持有人，不含非控股权益）；不扣非、不经调整。",
    "eps_basic": "每普通股基本盈利（报告口径，不是经调整）。",
    "gross_profit": "利润表上的毛利行；没有毛利行时为收入 − 销售成本。",
    "operating_cash_flow": "经营活动现金流量净额（扣除已付税项后的净额行）。",
    "net_interest_income": "净利息收入 / 淨利息收益。",
    "ppop": "拨备前利润 = 扣信贷损失前的收入 − 营业支出总额（不含信贷减值）；报告明示时以明示为准。",
    "insurance_revenue": "保险服务收入（IFRS 17）。",
    "insurance_service_result": "保险服务业绩（IFRS 17）。",
}
PERIOD_NAMES = {"Q": "单季", "H": "半年", "YTD": "年初至今", "FY": "全年"}
SCORED = list(FIELD_NAMES)


def _num_pattern(raw):
    """Regex matching the digits of raw with optional thousands separators, for highlighting."""
    d = digits_of(raw)
    intpart, _, frac = d.partition(".")
    body = ",?".join(re.escape(c) for c in intpart)
    if frac:
        body += r"\." + re.escape(frac)
    return re.compile(r"(?<![\d.])\(?" + body + r"\)?(?![\d])")


def find_snippet(pages, raw, page_hint=None, context=3):
    """Lines around the first occurrence of raw's digits; prefer page_hint. Returns dict or None."""
    try:
        num = digits_of(raw)
    except Exception:
        return None
    pat = re.compile(r"(?<![\d.])" + re.escape(num) + r"(?![\d]|\.\d)")
    order = sorted(pages, key=lambda p: (p["page"] != page_hint, p["page"]))
    for p in order:
        lines = p["text"].split("\n")
        for i, line in enumerate(lines):
            if pat.search(for_numbers(line)):
                lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                return {"page": p["page"], "part": p.get("part", 1), "part_page": p.get("part_page", p["page"]),
                        "lines": lines[lo:hi], "hit": i - lo}
    return None


def candidates_from_pipeline(result):
    """(field, period_type) -> list of candidate dicts from one pipeline output JSON."""
    out = {}
    for it in result["items"]:
        if it["field"] not in SCORED or it.get("value") is None:
            continue
        raw, page = it.get("raw_value"), it.get("page_used") or it.get("page")
        if not raw and it.get("derivation") == "derived":
            comps = it.get("components") or []
            parts = []
            for k, c in enumerate(comps):
                op = "−" if float(c.get("sign", 1)) < 0 else "+"
                parts.append((op + " " if k else ("− " if op == "−" else "")) + str(c.get("raw_value")).strip("()"))
            unit = comps[0].get("raw_unit", "") if comps else ""
            label = f"推导：{' '.join(parts)} {unit}".strip() if comps else f"推导：{it.get('formula', '')}"
            if not comps and it["field"] == "gross_profit":  # code-derived: revenue − |cost of revenue|
                rev = next((x for x in result["items"] if x["field"] == "revenue"
                            and x.get("period_type") == it["period_type"]), None)
                cost = next((x for x in result["items"] if x["field"] == "cost_of_revenue"
                             and x.get("period_type") == it["period_type"]), None)
                if rev and cost:
                    label = (f"推导：营业收入 {rev.get('raw_value')} − 营业成本 {str(cost.get('raw_value')).strip('()')} "
                             f"{cost.get('raw_unit') or ''}").strip()
                    comps = [cost]
            # point the snippet at the first component's line in the report
            raw = comps[0].get("raw_value") if comps else None
            page = (comps[0].get("page_used") or comps[0].get("page")) if comps else page
        else:
            label = f"{raw} {it.get('raw_unit') or ''}".strip()
        out.setdefault((it["field"], it["period_type"]), []).append(
            {"value": it["value"], "currency": it.get("currency"), "label": label, "raw": raw,
             "page": page, "derived": it.get("derivation") == "derived"})
    return out


def candidates_from_direct(parsed):
    out = {}
    for it in parsed or []:
        if it.get("value") is None or it.get("field") not in SCORED:
            continue
        label = f"{it.get('raw_value')} {it.get('raw_unit') or it.get('raw_currency') or ''}".strip()
        out.setdefault((it["field"], it["period_type"]), []).append(
            {"value": it["value"], "currency": it.get("currency"), "label": label, "raw": it.get("raw_value"),
             "page": None, "derived": False})
    return out


def candidates_from_key(key_items):
    """Automatic answer key value shown as one more (unlabelled) candidate on dispute rows."""
    return {(k["field"], k["ptype"]): [{"value": k["value"], "currency": k.get("currency"), "label": None,
                                         "raw": None, "page": None, "derived": False}] for k in key_items}


def candidates_from_benchmark(result):
    out = {}
    if result.get("benchmark_invalid"):  # currency-converted source: not a valid candidate
        return out
    for b in result.get("benchmarks") or []:
        if b["field"] in SCORED:
            out.setdefault((b["field"], b["period_type"]), []).append(
                {"value": b["value"], "currency": b.get("currency"), "label": None, "raw": None, "page": None,
                 "derived": False})
    return out


def merge_candidates(lists, tol_rel=1e-9):
    """Union of candidates; equal values (within the larger rounding tolerance) are merged."""
    merged = []
    for c in (c for lst in lists for c in lst):
        same = next((m for m in merged if abs(m["value"] - c["value"]) <= max(1e-6, tol_rel * abs(m["value"]))
                     or (m.get("raw") and c.get("raw") and digits_of(m["raw"]) == digits_of(c["raw"])
                         and abs(m["value"] - c["value"]) <= 0.01 * abs(m["value"]))), None)
        if same:
            same["votes"] += 1
            for k in ("label", "raw", "page"):
                same[k] = same[k] or c[k]
        else:
            merged.append(dict(c, votes=1))
    return sorted(merged, key=lambda m: m["value"])


def fmt_base(v, cur):
    if v is None:
        return ""
    if abs(v) >= 1000:
        return f"{v:,.0f} {cur or ''}".strip()
    return f"{v:,.4f}".rstrip("0").rstrip(".") + f" {cur or ''}".rstrip()


def build_rows(reports):
    """reports: list of {"result": pipeline/eval JSON, "candidate_sets": [dict (field, ptype) -> [cand]]}"""
    rows = []
    for rep in reports:
        r = rep["result"]
        doc = r["doc"]
        pages = load_doc_pages(doc)
        part_urls = [p["url"] for p in doc.get("parts") or []] or [doc["url"]]
        if rep.get("only") is not None:
            keys = sorted({tuple(k) for k in rep["only"]}, key=lambda k: (SCORED.index(k[0]), k[1]))
        else:
            keys = sorted({k for cs in rep["candidate_sets"] for k in cs} |
                          {(i["field"], i["period_type"]) for i in r["items"] if i["field"] in SCORED},
                          key=lambda k: (SCORED.index(k[0]), k[1]))
        for field, ptype in keys:
            cands = merge_candidates([cs.get((field, ptype), []) for cs in rep["candidate_sets"]])
            for c in cands:
                raw = c.get("raw")
                if not raw:  # structured-source value: search the document for its digits at common scales
                    for scale in (1, 1e3, 1e6, 1e8, 1e9):
                        v = abs(c["value"]) / scale
                        for txt in (f"{v:,.0f}", f"{v:,.2f}", f"{v:,.3f}"):
                            if find_snippet(pages, txt, c.get("page")):
                                raw = txt
                                break
                        if raw:
                            break
                snip = find_snippet(pages, raw, c.get("page")) if raw else None
                if snip:
                    snip["url"] = part_urls[min(snip["part"], len(part_urls)) - 1] + f"#page={snip['part_page']}"
                    snip["hl"] = _num_pattern(raw).pattern
                c["snippet"] = snip
                c["display"] = c.get("label") or (raw and f"{raw}（按原文写法）") or "（原文未找到此数）"
                c["base"] = fmt_base(c["value"], c.get("currency"))
            d = REVIEW_DEFS[field]
            d = d.get(r.get("template", "general"), d["general"]) if isinstance(d, dict) else d
            rows.append({
                "id": f"{doc['market']}:{doc['code']}:{doc['period']}:{field}:{ptype}",
                "company": f"{doc['name']}（{doc['code']}）", "report": doc["title"], "period": doc["period"],
                "period_end": doc["period_end"], "doc_url": part_urls[0],
                "field": field, "field_name": FIELD_NAMES[field], "ptype": ptype,
                "ptype_name": PERIOD_NAMES.get(ptype, ptype),
                "definition": d,
                "candidates": cands, "agree": len(cands) == 1 and cands[0]["votes"] > 1,
                "kind": (rep.get("kinds") or {}).get((field, ptype), "review"),
            })
    # inside a company: rows where every source agrees first (quick confirmations), then the rest
    order = {}
    for i, row in enumerate(rows):
        order.setdefault(row["company"], i)
    rows.sort(key=lambda r: (order[r["company"]], not r["agree"], SCORED.index(r["field"]), r["ptype"]))
    return rows


TEMPLATE = (Path(__file__).parent / "review_table_template.html").read_text


def render(rows, title, table_id):
    data = json.dumps({"id": table_id, "title": title, "rows": rows}, ensure_ascii=False)
    return TEMPLATE().replace("/*__DATA__*/null", data).replace("__TITLE__", html.escape(title))


def eval_rows(run):
    """Rows the reviewer must decide: every HK item, US/A items with no automatic truth, and disputes."""
    sys.path.insert(0, str(ROOT / "eval"))
    from score_eval import DS_CELLS, analyse

    cfg = json.loads((ROOT / "eval" / "config.json").read_text())
    reports = []
    for x in analyse(run, cfg["reports"]):
        outs, ctx = x["outputs"], x["ctx"]
        pipe = outs.get("ds_pipeline") or {"items": [], "benchmarks": ctx["benchmarks"], "benchmark_invalid": None}
        sets = [candidates_from_pipeline(pipe)] + [candidates_from_direct((outs.get(c) or {}).get("parsed"))
                                                   for c in DS_CELLS if c != "ds_pipeline"]
        kinds = {tuple(it): "pending" for it in x["pending"]}
        if ctx["doc"]["market"] == "hk":
            sets.append(candidates_from_benchmark(pipe))  # Eastmoney, unless the EPS probe says converted
        disputed = [d["item"] for d in x["disputes"]]
        if disputed:
            sets.append(candidates_from_key([k for k in x["key"] if (k["field"], k["ptype"]) in disputed]))
            kinds.update({tuple(it): "dispute" for it in disputed})
        only = [tuple(i) for i in x["pending"]] + [tuple(i) for i in disputed]
        if not only:
            continue
        result = dict(pipe, doc=ctx["doc"], template=ctx["template"])
        reports.append({"result": result, "candidate_sets": sets, "only": only, "kinds": kinds})
    return build_rows(reports)


def demo():
    reports = []
    for f in sorted((ROOT / "data/output").glob("hk_*_2026H1.json")):
        r = json.loads(f.read_text())
        reports.append({"result": r, "candidate_sets": [candidates_from_pipeline(r), candidates_from_benchmark(r)]})
    return build_rows(reports)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="eval1", help="evaluation run id (data/eval/<run>)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.demo:
        rows, tid, title = demo(), "hk-demo-dev3", "港股标准答案核对表（演示：开发集 3 家）"
        out = Path(a.out or ROOT / "data/review/hk_answer_key_demo.html")
    else:
        rows, tid, title = eval_rows(a.run), f"answer-key-{a.run}", f"标准答案核对表（{a.run}：港股全部 + 美股/A 股待定与争议）"
        out = Path(a.out or ROOT / f"data/review/answer_key_{a.run}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(rows, title, tid))
    print(f"{len(rows)} rows -> {out}")
