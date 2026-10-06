"""Run the extraction pipeline on the 9 development companies, then build docs/phase1_results.md."""
import json
import sys
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from earnings_agent.pipeline import extract  # noqa: E402
from phase1_report import RUNS, main as build_report  # noqa: E402


def run():
    no_cache = "--no-llm-cache" in sys.argv
    for m, c, p in RUNS:
        print(f"=== {m} {c} {p}", flush=True)
        try:
            r = extract(m, c, p, use_llm_cache=not no_cache)
            st = [i["status"] for i in r["items"]]
            print(f"   ✅{st.count('✅')} ⚠️{st.count('⚠️')} ❌{st.count('❌')}  {r['llm']['usage']}  ${r['llm']['cost_usd']}")
        except Exception as e:
            err = ROOT / "data" / "output" / f"{m}_{c}_{p}.error.txt"
            err.write_text(traceback.format_exc())
            print(f"   FAILED: {type(e).__name__}: {e}")
    build_report()


if __name__ == "__main__":
    run()
