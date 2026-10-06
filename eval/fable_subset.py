"""Select the 9-report Claude Fable 5.1 subset: stratified random sampling, fixed seed. Frozen rule.

Rule (docs/eval_design.md §4.4):
  - per market (us / a / hk), 3 reports
  - strata = (template, reporting currency) taken from eval/config candidates
  - rng = random.Random(SEED); strata are sorted by key, then shuffled with rng; take the first 3 strata
    (if a market has fewer than 3 strata, go round the shuffled list again)
  - inside a stratum, pick one company with rng.choice over the stratum's codes sorted ascending,
    never picking the same company twice
  - document length plays no part
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261006
PER_MARKET = 3


def currency(r):
    if r["market"] == "a":
        return "CNY"
    if r["code"] == "02888":  # Chinese version prints only "百萬元"; USD per the English report (eval_design §1.4)
        return "USD"
    return r.get("bench_currency") or r.get("currency_guess")


def select(rows, seed=SEED, per_market=PER_MARKET):
    rng = random.Random(seed)
    picked = []
    for market in ("us", "a", "hk"):
        strata = {}
        for r in rows:
            if r["market"] == market and r.get("ok"):
                strata.setdefault((r["template"], currency(r)), []).append(r["code"])
        keys = sorted(strata)
        rng.shuffle(keys)
        chosen, i = [], 0
        while len(chosen) < per_market:
            key = keys[i % len(keys)]
            pool = sorted(c for c in strata[key] if c not in chosen)
            if pool:
                chosen.append(rng.choice(pool))
                picked.append({"market": market, "code": chosen[-1], "stratum": list(key)})
            i += 1
    return picked


if __name__ == "__main__":
    rows = json.loads((ROOT / "data/output/eval_candidates.json").read_text())
    sel = select(rows)
    (ROOT / "eval/fable_subset.json").write_text(json.dumps({"seed": SEED, "subset": sel}, ensure_ascii=False, indent=1))
    for s in sel:
        print(s)
