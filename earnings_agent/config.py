"""Settings loaded from the project-root .env (never committed)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / "data" / "cache"        # downloaded documents, API listings, parsed pages, LLM replies
OUTPUT_DIR = ROOT / "data" / "output"      # one JSON per extraction run
for d in (CACHE_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---- LLM ------------------------------------------------------------------
# Dev default is DeepSeek; Gemini is the fallback when DeepSeek has no key or fails.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()
LLM_FALLBACK_PROVIDER = os.getenv("LLM_FALLBACK_PROVIDER", "gemini").lower()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")  # deepseek-chat is no longer listed by /models
DEEPSEEK_EFFORT = os.getenv("DEEPSEEK_EFFORT", "low")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-3.8-flash").split(",")
    if m.strip()
]

API_KEYS = {"deepseek": DEEPSEEK_API_KEY, "gemini": GEMINI_API_KEY}

# USD per 1M tokens, checked 2026-10-06 on the providers' pricing pages.
# DeepSeek: peak = Mon-Fri 01:00-04:00 and 06:00-10:00 UTC (Chinese public holidays not modelled), off-peak = half.
PRICES = {
    "deepseek-flash": {"peak": {"input_hit": 0.006, "input_miss": 0.30, "output": 1.20},
                       "offpeak": {"input_hit": 0.003, "input_miss": 0.15, "output": 0.60}},
    "deepseek-v4-pro": {"peak": {"input_hit": 0.044, "input_miss": 1.32, "output": 3.96},
                        "offpeak": {"input_hit": 0.022, "input_miss": 0.66, "output": 1.98}},
    "gemini-3.5-flash-lite": {"flat": {"input_hit": 0.03, "input_miss": 0.30, "output": 2.50}},
    "gemini-3.5-flash": {"flat": {"input_hit": 0.15, "input_miss": 1.50, "output": 9.00}},
    "gemini-3.8-flash": {"flat": {"input_hit": 0.075, "input_miss": 0.75, "output": 3.75}},
}

# ---- data sources -----------------------------------------------------------
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "earnings-agent-feasibility admin@example.com")
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Max characters of page text sent to the model per report.
PAGE_CHAR_BUDGET = int(os.getenv("PAGE_CHAR_BUDGET", "90000"))


def provider_order():
    """Providers to try, in order, skipping any without a key."""
    order = [LLM_PROVIDER] + [p for p in (LLM_FALLBACK_PROVIDER,) if p != LLM_PROVIDER]
    return [p for p in order if API_KEYS.get(p)]
