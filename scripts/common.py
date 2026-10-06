"""Shared helpers for phase-0 feasibility scripts (rate-limited HTTP, text extraction, number matching)."""
import io
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class RateLimitedSession(requests.Session):
    """requests.Session that never exceeds `max_per_sec` requests per second."""

    def __init__(self, max_per_sec, user_agent):
        super().__init__()
        self.min_interval = 1.0 / max_per_sec
        self._last = 0.0
        self.headers["User-Agent"] = user_agent

    def request(self, *args, **kwargs):
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        kwargs.setdefault("timeout", 60)
        return super().request(*args, **kwargs)


def save(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&")
            .replace("&#8212;", "—").replace("&#8217;", "'"))
    return re.sub(r"\s+", " ", text)


def pdf_profile(path, max_pages=None):
    """Return (n_pages, chars_per_page_on_sampled_pages, full_text)."""
    import pdfplumber

    texts = []
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for p in pages:
            # NFKC: some HK PDFs (e.g. HSBC) emit Kangxi radicals (⺟ ⽇) instead of normal CJK chars
            texts.append(unicodedata.normalize("NFKC", p.extract_text() or ""))
    sample = [len(t) for t in texts[:20]]
    return n, sample, "\n".join(texts)


def is_text_pdf(char_counts):
    """Heuristic: a scanned PDF has (near) zero extractable characters on most pages."""
    if not char_counts:
        return False
    return sum(1 for c in char_counts if c > 200) / len(char_counts) > 0.5


def number_variants(value, scales=(1, 1e3, 1e6, 1e8, 1e9), decimals=(0, 1, 2)):
    """Formatted renderings of `value` at several scales, for searching inside report text."""
    out = set()
    for s in scales:
        v = value / s
        for d in decimals:
            if abs(v) < 1 and d == 0:
                continue
            for txt in (f"{abs(v):,.{d}f}", f"{abs(v):.{d}f}"):
                if len(txt.replace(",", "").replace(".", "")) >= 3:
                    out.add(txt)
    return out


def find_in_text(value, text, **kw):
    """Return the variants of `value` that appear in `text` as whole numbers."""
    hits = []
    for v in number_variants(value, **kw):
        if re.search(r"(?<![\d.,])" + re.escape(v) + r"(?![\d]|[.,]\d)", text):
            hits.append(v)
    return sorted(hits, key=len, reverse=True)


def dump_json(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
