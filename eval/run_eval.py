"""Evaluation runner (docs/eval_design.md). Refuses to run unless eval/check_frozen.py passes.

  python eval/run_eval.py ds --run eval1                      # 3 DeepSeek cells on all 60 reports
  python eval/run_eval.py ds --run eval2 --subset stability    # stability repeats (eval2, eval3)
  python eval/run_eval.py fable --cell direct                  # Fable direct-ask batch (9 reports)
  python eval/run_eval.py fable --cell pipeline                # Fable pipeline batch (+ follow-up batch)
  python eval/run_eval.py score --run eval1                    # score against the automatic answer key

Revised rules (eval_design §10, manifest eval/FROZEN_REV2.json; the frozen v1 rules run from the git tag
eval-frozen-v1, see eval/FROZEN.md):
  python eval/run_eval.py ds --run eval1_rev1 --salt eval1     # re-verify eval1 replies (cache) + new cell
  python eval/run_eval.py ds --run hold1 --config eval/holdout_config.json   # holdout: previous periods
  python eval/run_eval.py score --run hold1 --config eval/holdout_config.json --markets us,a

Cells: ds_pipeline, ds_direct (professional direct ask), ds_simple (simple direct ask),
       ds_verified (professional direct ask + verification layer, revision R3),
       fable_direct, fable_pipeline. Every paid call goes through the $20 ledger.
"""
import argparse
import json
import subprocess
import sys
import threading
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from earnings_agent import config  # noqa: E402
from earnings_agent.anthropic_batch import batch_price, count_tokens, run_batch  # noqa: E402
from earnings_agent.budget import Budget, BudgetExceeded  # noqa: E402
from earnings_agent.direct import (build_direct_prompt, build_parser_prompt, build_simple_prompt,  # noqa: E402
                                   build_verified_parser_prompt, build_verified_prompt, interpret_parsed)
from earnings_agent.direct_verify import verify_direct_answer  # noqa: E402
from earnings_agent.llm_client import cached_complete_json, cached_complete_text  # noqa: E402
from earnings_agent.pipeline import finish, followup_prompt, missing_after, prepare  # noqa: E402

CFG = json.loads((ROOT / "eval" / "config.json").read_text())
MANIFEST = "eval/FROZEN_REV2.json"
DS_CELLS = ["ds_pipeline", "ds_direct", "ds_simple", "ds_verified"]
DS = ["deepseek"]
OUT = ROOT / "data" / "eval"
FABLE_MAX_TOKENS = CFG["cells"]["fable_pipeline"]["max_tokens"]
STOP = threading.Event()


def check_frozen():
    r = subprocess.run([sys.executable, str(ROOT / "eval" / "check_frozen.py"), "--manifest", MANIFEST],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        sys.exit("frozen check failed: refusing to run")


def reports(subset=None):
    rows = CFG["reports"]
    if subset:
        pick = {(s["market"], s["code"]) for s in json.loads((ROOT / CFG[f"{subset}_subset"]).read_text())["subset"]}
        rows = [r for r in rows if (r["market"], r["code"]) in pick]
    return rows


def tag(d):
    return f"{d['market']}_{d['code']}"


def save(run, cell, d, obj):
    p = OUT / run / cell / f"{tag(d)}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def ask_and_parse(run, cell, ctx, system, user, budget, label):
    """run here is the cache salt (the run whose replies are reused)."""
    ans = cached_complete_text(system, user, providers=DS, budget=budget, label=f"{label}:{cell}", salt=run)
    ps, pu = build_parser_prompt(ans["data"], ctx["doc"], ctx["template"])
    prec = cached_complete_json(ps, pu, providers=DS, budget=budget, label=f"{label}:{cell}:parse", salt=run)
    return {"doc": ctx["doc"], "template": ctx["template"], "answer": ans["data"],
            "parsed": interpret_parsed(prec["data"], ans["data"], ctx["doc"]["market"]),
            "llm": {k: ans.get(k) for k in ("provider", "model", "usage", "cost_usd", "from_cache")},
            "parser_llm": {k: prec.get(k) for k in ("model", "usage", "cost_usd", "from_cache")}}


def ds_report(r, run, budget, salt=None, cells=DS_CELLS):
    """run = output directory; salt = cache salt (defaults to run). With salt=eval1 and run=eval1_rev1 the
    eval1 model replies are reused from the cache and only re-verified / re-scored under the revised rules;
    prompts that did not exist in eval1 (the new cell, a changed follow-up) are real new calls."""
    if STOP.is_set():
        return r["code"], "skipped (stopped)"
    salt = salt or run
    ctx = prepare(r["market"], r["code"], r["period"])
    d = ctx["doc"]
    label = f"{run}:{d['market']}:{d['code']}"
    done = []
    # pipeline
    if "ds_pipeline" in cells and not (OUT / run / "ds_pipeline" / f"{tag(d)}.json").exists():
        rec = cached_complete_json(ctx["system"], ctx["user"], providers=DS, budget=budget, label=label + ":pipe",
                                   salt=salt)
        missing = missing_after(ctx, rec)
        fu = None
        if missing:
            fs, fu_user = followup_prompt(ctx, missing)
            fu = cached_complete_json(fs, fu_user, providers=DS, budget=budget, label=label + ":pipe-fu", salt=salt)
        finish(ctx, rec, fu, missing, OUT / run / "ds_pipeline" / f"{tag(d)}.json")
        done.append("pipeline")
    # professional direct ask
    if "ds_direct" in cells and not (OUT / run / "ds_direct" / f"{tag(d)}.json").exists():
        s, u = build_direct_prompt(d, ctx["template"], ctx["pages"])
        save(run, "ds_direct", d, ask_and_parse(salt, "ds_direct", ctx, s, u, budget, label))
        done.append("direct")
    # simple direct ask
    if "ds_simple" in cells and not (OUT / run / "ds_simple" / f"{tag(d)}.json").exists():
        s, u = build_simple_prompt(d, ctx["pages"])
        save(run, "ds_simple", d, ask_and_parse(salt, "ds_simple", ctx, s, u, budget, label))
        done.append("simple")
    # professional direct ask + verification layer (revision R3)
    if "ds_verified" in cells and not (OUT / run / "ds_verified" / f"{tag(d)}.json").exists():
        s, u = build_verified_prompt(d, ctx["template"], ctx["pages"])
        ans = cached_complete_text(s, u, providers=DS, budget=budget, label=f"{label}:ds_verified", salt=salt)
        ps, pu = build_verified_parser_prompt(ans["data"], d, ctx["template"])
        prec = cached_complete_json(ps, pu, providers=DS, budget=budget, label=f"{label}:ds_verified:parse",
                                    salt=salt)
        ver = verify_direct_answer(ctx, prec["data"], ans["data"])
        save(run, "ds_verified", d, dict(ver, doc=d, template=ctx["template"], answer=ans["data"],
                                         parser_output=prec["data"], benchmarks=ctx["benchmarks"],
                                         llm={k: ans.get(k) for k in ("provider", "model", "usage", "cost_usd",
                                                                      "from_cache")},
                                         parser_llm={k: prec.get(k) for k in ("model", "usage", "cost_usd",
                                                                              "from_cache")}))
        done.append("verified")
    return r["code"], ",".join(done) or "already done"


def run_ds(run, subset, workers, salt=None, cells=DS_CELLS):
    budget = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD)
    rows = reports(subset)
    print(f"{run} (cache salt {salt or run}): {len(rows)} reports x {cells}; budget {budget.status()}", flush=True)
    errors = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(ds_report, r, run, budget, salt, cells): r for r in rows}
        for f in as_completed(futs):
            r = futs[f]
            try:
                code, what = f.result()
                print(f"  {r['market']} {code}: {what}  spent=${budget.status()['spent']:.3f}", flush=True)
            except BudgetExceeded as e:
                STOP.set()
                errors[r["code"]] = f"BudgetExceeded: {e}"
                print(f"  STOP — budget: {e}", flush=True)
            except Exception as e:
                errors[r["code"]] = f"{type(e).__name__}: {e}"
                (OUT / run / "errors").mkdir(parents=True, exist_ok=True)
                (OUT / run / "errors" / f"{r['market']}_{r['code']}.txt").write_text(traceback.format_exc())
                print(f"  {r['market']} {r['code']}: ERROR {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"done; errors: {len(errors)}; budget {budget.status()}", flush=True)


def run_fable(cell, run="eval1"):
    """Two batches by cell (§4.5): direct first, settle, then pipeline (+ its follow-up batch).
    Each batch is checked exactly against the remaining budget before submission; if it does not fit,
    nothing is submitted and the run stops."""
    budget = Budget(config.EVAL_LEDGER, config.EVAL_BUDGET_USD)
    rows = reports("fable")
    ctxs = {r["code"]: prepare(r["market"], r["code"], r["period"]) for r in rows}
    reqs = []
    for code, ctx in ctxs.items():
        if cell == "direct":
            s, u = build_direct_prompt(ctx["doc"], ctx["template"], ctx["pages"])
            reqs.append({"custom_id": f"direct-{code}", "system": s, "user": u, "max_tokens": FABLE_MAX_TOKENS,
                         "mode": "text", "salt": run})
        else:
            reqs.append({"custom_id": f"pipe-{code}", "system": ctx["system"], "user": ctx["user"],
                         "max_tokens": FABLE_MAX_TOKENS, "mode": "json", "salt": run})
    price = batch_price("claude-fable-5-1")
    worst = sum(count_tokens("claude-fable-5-1", q["system"], q["user"]) * price["input_miss"]
                + q["max_tokens"] * price["output"] for q in reqs) / 1e6
    st = budget.status()
    print(f"fable {cell}: {len(reqs)} requests, exact worst case ${worst:.2f}; budget left ${st['left']:.2f}", flush=True)
    if worst > st["left"]:
        sys.exit(f"STOP: worst case ${worst:.2f} > left ${st['left']:.2f}. Not submitted — ask the user.")
    res = run_batch(reqs, budget, label=f"{run}-fable-{cell}")
    if cell == "direct":
        for code, ctx in ctxs.items():
            ans = res[f"direct-{code}"]
            ps, pu = build_parser_prompt(ans.get("data") or "", ctx["doc"], ctx["template"])
            prec = cached_complete_json(ps, pu, providers=DS, budget=budget, label=f"{run}:fable:{code}:parse", salt=run)
            save(run, "fable_direct", ctx["doc"], {
                "doc": ctx["doc"], "template": ctx["template"], "answer": ans.get("data"),
                "parsed": interpret_parsed(prec["data"], ans.get("data") or "", ctx["doc"]["market"]),
                "llm": {k: ans.get(k) for k in ("provider", "model", "usage", "cost_usd", "from_cache", "error")},
                "parser_llm": {k: prec.get(k) for k in ("model", "usage", "cost_usd", "from_cache")}})
    else:
        fu_reqs, missing_by = [], {}
        for code, ctx in ctxs.items():
            rec = res[f"pipe-{code}"]
            missing = missing_after(ctx, rec) if rec.get("data") else []
            if missing:
                fs, fu_user = followup_prompt(ctx, missing)
                missing_by[code] = missing
                fu_reqs.append({"custom_id": f"pipefu-{code}", "system": fs, "user": fu_user,
                                "max_tokens": FABLE_MAX_TOKENS, "mode": "json", "salt": run})
        fu_res = {}
        if fu_reqs:
            worst = sum(count_tokens("claude-fable-5-1", q["system"], q["user"]) * price["input_miss"]
                        + q["max_tokens"] * price["output"] for q in fu_reqs) / 1e6
            st = budget.status()
            print(f"fable follow-up: {len(fu_reqs)} requests, worst ${worst:.2f}; left ${st['left']:.2f}", flush=True)
            if worst > st["left"]:
                print("follow-up does not fit the budget: not submitted; missing items stay 漏抽 (§4.5)", flush=True)
            else:
                fu_res = run_batch(fu_reqs, budget, label=f"{run}-fable-pipeline-fu")
        for code, ctx in ctxs.items():
            finish(ctx, res[f"pipe-{code}"], fu_res.get(f"pipefu-{code}"), missing_by.get(code),
                   OUT / run / "fable_pipeline" / f"{tag(ctx['doc'])}.json")
    print("budget after:", budget.status(), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ds", "fable", "score"])
    ap.add_argument("--run", default="eval1")
    ap.add_argument("--subset", choices=["stability", "fable"], default=None)
    ap.add_argument("--cell", choices=["direct", "pipeline"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--config", default="eval/config.json", help="report list (eval/holdout_config.json for the holdout)")
    ap.add_argument("--salt", default=None, help="cache salt; reuse another run's model replies (eval1_rev1 -> eval1)")
    ap.add_argument("--cells", default=",".join(DS_CELLS))
    ap.add_argument("--markets", default="us,a,hk", help="score only these markets")
    a = ap.parse_args()
    check_frozen()
    global CFG
    CFG = json.loads((ROOT / a.config).read_text())
    cells = a.cells.split(",")
    if a.mode == "ds":
        run_ds(a.run, a.subset, a.workers, a.salt, cells)
    elif a.mode == "fable":
        sys.exit("Fable runs with the frozen v1 rules: run it from the eval-frozen-v1 worktree (eval/FROZEN.md)")
    else:
        from score_eval import score_run
        score_run(a.run, [r for r in CFG["reports"] if r["market"] in a.markets.split(",")], cells=cells)


if __name__ == "__main__":
    main()
