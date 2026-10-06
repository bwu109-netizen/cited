"""Estimate token use and cost of the 4-cell evaluation from the real candidate documents.

Inputs: data/output/eval_candidates.json (run scripts/eval_candidates.py first) and the dev-set outputs
(for measured tokens/char and output sizes). Prices: official pages, checked 2026-10-06 (USD / 1M tokens).
All assumptions are listed in ASSUMPTIONS and printed with the result.
"""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# measured on the dev set with deepseek-flash (input tokens / prompt chars)
TOK_PER_CHAR = {"a": 0.56, "hk": 0.64, "us": 0.30}
ASSUMPTIONS = {
    "pipeline_prompt_overhead_tokens": 3000,     # instructions + JSON schema (dev: ~2.5-3k)
    "pipeline_out_cheap": 5000,                  # dev mean ≈ 4.9k incl. reasoning (effort=low)
    "pipeline_out_strong": 12000,                # adaptive thinking at default effort: assume ~2.5x
    "followup_rate": 0.25,                       # share of reports that need the follow-up ask
    "direct_question_tokens": 600,
    "direct_out_cheap": 4000,
    "direct_out_strong": 10000,
    "strong_tokenizer_factor": 1.3,              # Claude 4.7+ tokenizer ≈ +30% tokens (Anthropic pricing page)
    "parser_in": 3000, "parser_out": 1000,       # free-text -> JSON parse of a direct answer, cheap model
}
PRICES = {  # input, output, cache-read; (threshold, input, output) for long-context tiers
    "deepseek-flash (peak)": {"in": 0.30, "out": 1.20, "cache": 0.006},
    "claude-fable-5-1": {"in": 10.0, "out": 50.0, "cache": 0.25},
    "claude-opus-5-5": {"in": 4.0, "out": 20.0, "cache": 0.20},
    "gemini-3.1-pro-preview": {"in": 2.0, "out": 12.0, "cache": 0.20, "long": (200_000, 4.0, 18.0)},
    "gpt-6-astra": {"in": 10.0, "out": 50.0, "cache": 1.0, "long": (272_000, 20.0, 75.0)},
}
N_MAIN = 60
STABILITY_SUBSET = 15
STABILITY_EXTRA_RUNS = 2


def cost(model, tin, tout):
    p = PRICES[model]
    i, o = p["in"], p["out"]
    if "long" in p and tin > p["long"][0]:
        _, i, o = p["long"]
    return (tin * i + tout * o) / 1e6


def main():
    rows = [r for r in json.loads((ROOT / "data/output/eval_candidates.json").read_text()) if r.get("ok")]
    if not rows:
        sys.exit("no candidate data")
    A = ASSUMPTIONS
    docs = []
    for r in rows:
        k = TOK_PER_CHAR[r["market"]]
        docs.append({"code": r["code"], "market": r["market"],
                     "full": r["chars"] * k + A["direct_question_tokens"],
                     "pipe": r["sent_chars"] * k + A["pipeline_prompt_overhead_tokens"]})
    full = [d["full"] for d in docs]
    print(f"{len(docs)} docs; full-doc tokens (deepseek tokenizer): mean {statistics.mean(full):,.0f}, "
          f"median {statistics.median(full):,.0f}, max {max(full):,.0f} ({max(docs, key=lambda d: d['full'])['code']})")
    print(f"pipeline input tokens: mean {statistics.mean(d['pipe'] for d in docs):,.0f}")

    def per_doc(model, cell):
        strong = not model.startswith("deepseek")
        f = A["strong_tokenizer_factor"] if model.startswith("claude") else 1.0
        tot = 0.0
        for d in docs:
            if cell == "pipeline":
                tin, tout = d["pipe"] * f, A["pipeline_out_strong" if strong else "pipeline_out_cheap"]
                c = cost(model, tin, tout) * (1 + A["followup_rate"])
            else:
                tin, tout = d["full"] * f, A["direct_out_strong" if strong else "direct_out_cheap"]
                c = cost(model, tin, tout) + cost("deepseek-flash (peak)", A["parser_in"], A["parser_out"])
            tot += c
        return tot / len(docs)

    print("\nUSD per report (no provider cache) | 60 reports x1 | stability 15 x2 extra | cell total")
    for model in PRICES:
        for cell in ("pipeline", "direct"):
            c = per_doc(model, cell)
            main_c, stab = c * N_MAIN, c * STABILITY_SUBSET * STABILITY_EXTRA_RUNS
            print(f"{model:24s} {cell:8s} {c:8.4f} | {main_c:8.2f} | {stab:7.2f} | {main_c + stab:8.2f}")
    print("\nassumptions:", json.dumps(A, ensure_ascii=False))


if __name__ == "__main__":
    main()
