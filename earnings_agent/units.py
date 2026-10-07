"""Parse model-copied raw numbers and unit strings. All conversion happens here, never in the model."""
import re
from decimal import Decimal, InvalidOperation

from .textnorm import nfkc

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


class UnitError(ValueError):
    pass


def digits_of(raw_value):
    """The bare number string as it must appear in the document: '(2,353)' -> '2353', '-0.76' -> '0.76'."""
    t = nfkc(raw_value).replace(",", "").replace(" ", "")
    m = _NUM_RE.search(t)
    if not m:
        raise UnitError(f"no number in {raw_value!r}")
    return m.group(0)


def parse_raw_value(raw_value):
    """'(2,353)' -> Decimal('-2353'); '−4,672,487' -> Decimal('-4672487'); keeps decimals as written."""
    t = nfkc(raw_value).strip()
    neg = bool(re.match(r"^\(.*\)$", t)) or bool(re.match(r"^[-−–—]", t))
    try:
        d = Decimal(digits_of(t))
    except InvalidOperation:
        raise UnitError(f"bad number {raw_value!r}")
    return -d if neg else d


def decimals_of(raw_value):
    s = digits_of(raw_value)
    return len(s.split(".")[1]) if "." in s else 0


# order matters: longer/more specific tokens first
_SCALES = [
    (r"十亿|billions?|\bbn\b", Decimal(10) ** 9),
    (r"亿|億", Decimal(10) ** 8),
    (r"千万|千萬", Decimal(10) ** 7),
    (r"百万|百萬|millions?|\bmn\b|\bmm\b|\$m\b|\bm\b", Decimal(10) ** 6),
    (r"万|萬", Decimal(10) ** 4),
    (r"千|thousands?|'000|’000|\bk\b", Decimal(10) ** 3),
]
_RATIO = re.compile(r"%|％|百分点|个百分点|percentage point|\bpp\b|\bbps?\b|基点|倍|\btimes\b|\bx\b")
_PER_SHARE = re.compile(r"/股|每股|per[ -]share|/share|per[ -]ads|/ads")
_BASE = re.compile(r"元|圆|\$|usd|rmb|cny|hkd|dollars?|户|人|家|个|辆|台|吨|千瓦时|gwh|mwh|kwh|users?|accounts?|股|份")


def unit_multiplier(raw_unit):
    """Return (multiplier, kind) with kind in {'amount', 'per_share', 'ratio'}; raise UnitError if unknown."""
    u = nfkc(raw_unit or "").strip().lower()
    if not u:
        raise UnitError("empty unit")
    # table headers like "in millions, except per share data" / "人民币百万元，每股数据除外":
    # the exception clause does not describe this number's unit
    u = re.sub(r"except\b.*$", "", u)
    u = re.sub(r"[^,，;；(（]*除外.*$", "", u).strip(" ,，;；(（)）") or u
    if _RATIO.search(u):
        return Decimal(1), "ratio"
    if _PER_SHARE.search(u):
        return Decimal(1), "per_share"
    for pat, mult in _SCALES:
        if re.search(pat, u):
            return mult, "amount"
    if _BASE.search(u):
        return Decimal(1), "amount"
    raise UnitError(f"unknown unit {raw_unit!r}")


_PER_SHARE_WORDS = re.compile(r"/股|每股|per[ -](?:common |ordinary )?(?:share|ads)|/share|/ads")
_SCALE_WORDS = re.compile(r"十亿|亿|億|千万|千萬|百万|百萬|万|萬|千|billions?|millions?|thousands?|\bbn\b|\bmn\b|\bmm\b|"
                          r"'000|’000|\bin\b|\bof\b|\band\b|\bshares?\b|\bdata\b|\bamounts?\b|except\b|除外|[,，;；()（）]")


def per_share_multiplier(raw_unit):
    """Revision R2 (eval_design §10): the unit of a per-share figure. Table headers such as
    "in millions, except per share amounts" or "Dollars and Shares in Millions" describe the table's
    amounts, not its per-share rows, so their amount scale is never inherited (multiplier 1).
    Anything else (e.g. cents: 仙 / 美分) still has to parse on its own."""
    u = nfkc(raw_unit or "").strip().lower()
    if not u:
        raise UnitError("empty unit")
    if _PER_SHARE_WORDS.search(u):
        return Decimal(1), "per_share"
    rest = _SCALE_WORDS.sub(" ", u).strip()
    if not rest or _BASE.search(rest) or currency_code(rest, "", "us") or currency_code(rest, "", "a"):
        return Decimal(1), "per_share"
    raise UnitError(f"unknown per-share unit {raw_unit!r}")


_CURRENCIES = [
    (r"港元|港币|港幣|hk\$|hkd", "HKD"),
    (r"美元|us\$|usd|u\.s\. dollars?|\$", "USD"),
    (r"人民币|人民幣|rmb|cny|renminbi", "CNY"),
    (r"欧元|eur|€", "EUR"),
    (r"英镑|gbp|£", "GBP"),
    (r"日元|jpy|円", "JPY"),
]
# Bare "元" means the listing market's home currency (A-share reports: CNY).
_MARKET_DEFAULT_YUAN = {"a": "CNY", "hk": None, "us": None}


def currency_code(raw_currency, raw_unit="", market=""):
    """ISO code from the currency words the model copied (falls back to the unit string)."""
    for text in (raw_currency, raw_unit):
        t = nfkc(text or "").lower()
        for pat, code in _CURRENCIES:
            if re.search(pat, t):
                return code
    for text in (raw_currency, raw_unit):
        if "元" in nfkc(text or "") and _MARKET_DEFAULT_YUAN.get(market):
            return _MARKET_DEFAULT_YUAN[market]
    return None


def to_value(raw_value, raw_unit, per_share=False):
    """Return (value as float in base units, multiplier, kind, tolerance in base units).
    per_share=True for per-share fields (EPS): see per_share_multiplier (revision R2)."""
    mult, kind = per_share_multiplier(raw_unit) if per_share else unit_multiplier(raw_unit)
    v = parse_raw_value(raw_value)
    tol = Decimal(5) * Decimal(10) ** (-(decimals_of(raw_value) + 1)) * mult
    return float(v * mult), mult, kind, float(tol)
