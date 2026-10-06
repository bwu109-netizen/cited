"""Dev-set validation of the evaluation machinery (before freezing).

- DeepSeek pipeline + DeepSeek direct-ask on all 9 dev reports
- Claude Fable 5.1 pipeline + direct-ask on the single shortest dev report, through the Message Batches API
- every paid call goes through the $20 ledger (data/eval/spend_ledger.jsonl)
Writes data/eval/dev/<cell>/<market>_<code>.json and docs/eval_dev_results.md.
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from earnings_agent import config  # noqa: E402
from earnings_agent.anthropic_batch import run_batch  # noqa: E402
from earnings_agent.budget import Budget  # noqa: E402
from earnings_agent.direct import build_direct_prompt, build_parser_prompt, interpret_parsed  # noqa: E402
from earnings_agent.llm_client import cached_complete_json, cached_complete_text  # noqa: E402
from earnings_agent.pipeline import finish, followup_prompt, missing_after, prepare  # noqa: E402
from score import answer_key, direct_preds, pipeline_preds, score_items, summarize  # noqa: E402

DEV = [("us", "AAPL", "2026Q3"), ("us", "JPM", "2026Q2"), ("us", "BABA", "2026FY"),
       ("a", "600519", "2026H1"), ("a", "300750", "2026H1"), ("a", "600036", "2026H1"),
       ("hk", "00700", "2026H1"), ("hk", "03690", "2026H1"), ("hk", "00005", "2026H1")]
RUN = "dev1"
OUT = ROOT / "data" / "eval" / "dev"
DS = ["deepseek"]  # no silent fallback to another provider inside an evaluation cell
FABLE_MAX_TOKENS = 32000


def parse_direct(answer, ctx, budget, label):
    ps, pu = build_parser_prompt(answer, ctx["doc"], ctx["template"])
    prec = cached_complete_json(ps, pu, providers=DS, budget=budget, label=label + ":parse", salt=RUN)
    return interpret_parsed(prec["data"], answer, ctx["doc"]["market"]), prec


def ds_cells(ctx, budget):
    d = ctx["doc"]
    tag = f"{d['market']}_{d['code']}"
    label = f"{RUN}:{d['market']}:{d['code']}"
    # pipeline
    rec = cached_complete_json(ctx["system"], ctx["user"], providers=DS, budget=budget, label=label + ":pipe", salt=RUN)
    missing = missing_after(ctx, rec)
    fu = None
    if missing:
        fs, fu_user = followup_prompt(ctx, missing)
        fu = cached_complete_json(fs, fu_user, providers=DS, budget=budget, label=label + ":pipe-fu", salt=RUN)
    pipe = finish(ctx, rec, fu, missing, OUT / "ds_pipeline" / f"{tag}.json")
    # direct ask
    s, u = build_direct_prompt(d, ctx["template"], ctx["pages"])
    ans = cached_complete_text(s, u, providers=DS, budget=budget, label=label + ":direct", salt=RUN)
    parsed, prec = parse_direct(ans["data"], ctx, budget, label)
    direct = {"doc": d, "template": ctx["template"], "answer": ans["data"], "parsed": parsed,
              "llm": {k: ans.get(k) for k in ("provider", "model", "usage", "cost_usd", "from_cache")},
              "parser_llm": {k: prec.get(k) for k in ("model", "usage", "cost_usd", "from_cache")}}
    (OUT / "ds_direct").mkdir(parents=True, exist_ok=True)
    (OUT / "ds_direct" / f"{tag}.json").write_text(json.dumps(direct, ensure_ascii=False, indent=1, default=str))
    return pipe, direct


def fable_cells(ctx, budget):
    d = ctx["doc"]
    tag = f"{d['market']}_{d['code']}"
    s, u = build_direct_prompt(d, ctx["template"], ctx["pages"])
    reqs = [{"custom_id": f"pipe-{d['code']}", "system": ctx["system"], "user": ctx["user"],
             "max_tokens": FABLE_MAX_TOKENS, "mode": "json", "salt": RUN},
            {"custom_id": f"direct-{d['code']}", "system": s, "user": u, "max_tokens": FABLE_MAX_TOKENS,
             "mode": "text", "salt": RUN}]
    res = run_batch(reqs, budget, label=f"{RUN}-fable-{d['code']}-r1")
    rec = res[f"pipe-{d['code']}"]
    missing = missing_after(ctx, rec) if rec.get("data") else []
    fu = None
    if missing:
        fs, fu_user = followup_prompt(ctx, missing)
        fu = run_batch([{"custom_id": f"pipefu-{d['code']}", "system": fs, "user": fu_user,
                         "max_tokens": FABLE_MAX_TOKENS, "mode": "json", "salt": RUN}],
                       budget, label=f"{RUN}-fable-{d['code']}-fu")[f"pipefu-{d['code']}"]
    pipe = finish(ctx, rec, fu, missing, OUT / "fable_pipeline" / f"{tag}.json")
    ans = res[f"direct-{d['code']}"]
    parsed, prec = parse_direct(ans["data"] or "", ctx, budget, f"{RUN}:fable:{d['code']}")
    direct = {"doc": d, "template": ctx["template"], "answer": ans["data"], "parsed": parsed,
              "llm": {k: ans.get(k) for k in ("provider", "model", "usage", "cost_usd", "from_cache", "error")},
              "parser_llm": {k: prec.get(k) for k in ("model", "usage", "cost_usd", "from_cache")}}
    (OUT / "fable_direct").mkdir(parents=True, exist_ok=True)
    (OUT / "fable_direct" / f"{tag}.json").write_text(json.dumps(direct, ensure_ascii=False, indent=1, default=str))
    return pipe, direct


def main():
    budget = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD)
    manual = json.loads((ROOT / "eval" / "dev_answer_key.json").read_text())
    print("budget before:", budget.status(), flush=True)
    results = {"ds_pipeline": [], "ds_direct": [], "fable_pipeline": [], "fable_direct": []}
    ctxs = {}
    for m, c, p in DEV:
        print(f"=== {m} {c} {p}", flush=True)
        ctx = prepare(m, c, p)
        ctxs[c] = ctx
        key = answer_key(ctx, manual)
        pipe, direct = ds_cells(ctx, budget)
        results["ds_pipeline"].append((ctx, key, score_items(key, pipeline_preds(pipe), ctx["pages"]), pipe))
        results["ds_direct"].append((ctx, key, score_items(key, direct_preds(direct["parsed"]), ctx["pages"]), direct))
        print("   spent so far:", round(budget.status()["spent"], 4), flush=True)
    # Fable: the shortest dev report by full-text length
    shortest = min(DEV, key=lambda t: sum(len(pg["text"]) for pg in ctxs[t[1]]["pages"]))
    ctx = ctxs[shortest[1]]
    key = answer_key(ctx, manual)
    tag = f"{ctx['doc']['market']}_{ctx['doc']['code']}"
    if "--reuse-fable" in sys.argv:  # keep the already-paid batch results (scored with the current scorer)
        print(f"=== Fable: reusing saved results for {shortest}", flush=True)
        pipe = json.loads((OUT / "fable_pipeline" / f"{tag}.json").read_text())
        direct = json.loads((OUT / "fable_direct" / f"{tag}.json").read_text())
    else:
        print(f"=== Fable batch test on {shortest}", flush=True)
        pipe, direct = fable_cells(ctx, budget)
    results["fable_pipeline"].append((ctx, key, score_items(key, pipeline_preds(pipe), ctx["pages"]), pipe))
    results["fable_direct"].append((ctx, key, score_items(key, direct_preds(direct["parsed"]), ctx["pages"]), direct))
    print("budget after:", budget.status(), flush=True)
    (OUT / "summary.json").write_text(json.dumps(
        {cell: [{"doc": f"{c['doc']['market']}:{c['doc']['code']}", "rows": rows,
                 "cost": (r.get("llm") or {}).get("cost_usd"),
                 "parser_cost": (r.get("parser_llm") or {}).get("cost_usd")} for c, k, rows, r in v]
         for cell, v in results.items()}, ensure_ascii=False, indent=1, default=str))
    print("wrote", OUT / "summary.json")


if __name__ == "__main__":
    main()
