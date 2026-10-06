"""Select the 15-report stability subset (DeepSeek cells): same stratified rule as fable_subset.py,
seed 20261007, 5 per market. Frozen; document length plays no part."""
import json
from pathlib import Path

from fable_subset import select

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261007

if __name__ == "__main__":
    rows = json.loads((ROOT / "data/output/eval_candidates.json").read_text())
    sel = select(rows, seed=SEED, per_market=5)
    (ROOT / "eval/stability_subset.json").write_text(json.dumps({"seed": SEED, "subset": sel}, ensure_ascii=False, indent=1))
    for s in sel:
        print(s)
