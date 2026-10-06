"""CLI: python -m earnings_agent extract --market a|hk|us --code 600519 --period 2026H1"""
import argparse
import sys
import warnings

warnings.filterwarnings("ignore")


def _fmt(v):
    return "" if v is None else f"{v:,.4f}".rstrip("0").rstrip(".")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="earnings_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="extract + verify core fields of one report")
    ex.add_argument("--market", required=True, choices=["a", "hk", "us"])
    ex.add_argument("--code", required=True, help="600519 / 00700 / AAPL")
    ex.add_argument("--period", required=True, help="2026H1 / 2026Q1 / 2026Q3 / 2026FY (fiscal year)")
    ex.add_argument("--no-llm-cache", action="store_true", help="ignore cached model replies")
    args = ap.parse_args(argv)

    from .pipeline import extract

    r = extract(args.market, args.code, args.period, use_llm_cache=not args.no_llm_cache)
    d = r["doc"]
    print(f"{d['name']} {d['code']} {d['period']} | {d['doc_kind']}: {d['title']} | 模板 {r['template']}")
    print(f"页面 {len(r['pages_sent'])}/{r['pages_total']} 送模型；{r['llm']['provider']}/{r['llm']['model']} "
          f"tokens={r['llm']['usage']} cost=${r['llm']['cost_usd']} cache={r['llm']['from_cache']}")
    for it in r["items"] + r["industry_metrics"]:
        print(f"{it['status']} {it['field']:<28} {it.get('period_type') or '':<4} {it.get('raw_value') or '':>20} "
              f"{it.get('raw_unit') or '':<14} → {_fmt(it.get('value')):>22} {it.get('currency') or '':<4} "
              f"p{it.get('page_used') or it.get('page') or ''} {'；'.join(it.get('reasons') or [])}")
    print("结果：", r["output_path"])


if __name__ == "__main__":
    sys.exit(main())
