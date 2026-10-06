"""Text normalization shared by parsing and verification."""
import re
import unicodedata

from opencc import OpenCC

_T2S = OpenCC("t2s")

# minus/dash variants -> ASCII hyphen-minus
_DASHES = dict.fromkeys(map(ord, "−–—‐‑‒―﹣－"), "-")
# CJK punctuation NFKC leaves alone -> ASCII equivalents
_PUNCT = {ord("、"): ",", ord("。"): ".", ord("「"): '"', ord("」"): '"', ord("『"): '"', ord("』"): '"',
          ord("‘"): "'", ord("’"): "'", ord("“"): '"', ord("”"): '"'}


def nfkc(text):
    """NFKC fixes full-width chars and the Kangxi radicals some HK PDFs emit (⺟ -> 母, ⽇ -> 日)."""
    return unicodedata.normalize("NFKC", text or "")


def for_match(text):
    """Aggressive form for quote matching: NFKC, traditional -> simplified Chinese (models often transcribe
    HK filings into simplified), unified dashes/punctuation, no whitespace, lowercase."""
    t = _T2S.convert(nfkc(text)).translate(_DASHES).translate(_PUNCT)
    return re.sub(r"\s+", "", t).lower()


def for_numbers(text):
    """Form for exact number search: NFKC, unified dashes, thousands separators removed, whitespace kept
    (so adjacent table cells stay separate numbers)."""
    t = nfkc(text).translate(_DASHES)
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
