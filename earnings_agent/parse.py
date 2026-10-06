"""Turn a downloaded report into numbered "pages" of NFKC-normalized text (cached as JSON).

PDF: one page per physical PDF page (1-based).
HTML (SEC filings): split at the filing's own page breaks (CSS page-break / break-before), which
follow the printed pages and section starts; if a filing has none, fall back to ~6000-char chunks.
"""
import hashlib
import html as htmllib
import json
import re
from pathlib import Path

from . import config
from .textnorm import nfkc

_PAGE_BREAK = re.compile(
    r"<[^>]+style=\"[^\"]*(?:page-break-(?:before|after)\s*:\s*always|break-(?:before|after)\s*:\s*page)[^\"]*\"[^>]*>",
    re.I)


def _cache_path(path):
    h = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    d = config.CACHE_DIR / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{Path(path).stem}_{h}.json"


def pdf_pages(path):
    import pdfplumber

    out = []
    with pdfplumber.open(str(path)) as pdf:
        for i, p in enumerate(pdf.pages, 1):
            out.append({"page": i, "text": nfkc(p.extract_text() or "")})
    return out


def _html_fragment_to_text(fragment):
    f = re.sub(r"(?is)<(script|style|ix:header)\b.*?</\1>", " ", fragment)
    f = re.sub(r"(?i)</(tr|p|div|h[1-6]|li|table)>|<br\s*/?>", "\n", f)
    f = re.sub(r"(?i)</t[dh]>", " ", f)
    f = re.sub(r"(?s)<[^>]+>", "", f)
    f = htmllib.unescape(f)
    f = re.sub(r"[ \t\xa0]+", " ", f)
    # SEC tables put "$" and ")" / "%" in their own cells: glue them back to the number
    f = re.sub(r"\(\s+(?=\d)", "(", f)
    f = re.sub(r"(?<=\d)\s+\)", ")", f)
    f = re.sub(r"\n\s*\n+", "\n", f)
    return nfkc(f).strip()


def html_pages(path, chunk=6000):
    raw = Path(path).read_bytes().decode("utf-8", "ignore")
    raw = re.sub(r"(?is)<ix:header\b.*?</ix:header>", " ", raw)
    parts = _PAGE_BREAK.split(raw)
    texts = [_html_fragment_to_text(p) for p in parts]
    texts = [t for t in texts if t]
    if len(texts) < 3:  # no page breaks: fixed-size chunks on line boundaries
        full = "\n".join(texts)
        texts, cur = [], ""
        for line in full.split("\n"):
            if len(cur) + len(line) > chunk and cur:
                texts.append(cur)
                cur = ""
            cur += line + "\n"
        if cur:
            texts.append(cur)
    return [{"page": i, "text": t} for i, t in enumerate(texts, 1)]


def load_doc_pages(doc):
    """Pages of a fetched report; multi-part announcements are concatenated with continuous page numbers
    (each page also keeps its part index and page-within-part)."""
    parts = [p["path"] for p in doc.get("parts") or []] or [doc["path"]]
    out = []
    for k, path in enumerate(parts, 1):
        for pg in load_pages(path):
            out.append({"page": len(out) + 1, "text": pg["text"], "part": k, "part_page": pg["page"]})
    return out


def load_pages(path):
    cp = _cache_path(path)
    if cp.exists():
        return json.loads(cp.read_text())
    suffix = Path(path).suffix.lower()
    pages = pdf_pages(path) if suffix == ".pdf" else html_pages(path)
    cp.write_text(json.dumps(pages, ensure_ascii=False))
    return pages
