"""Currency conversion for the Compare page (metrics_spec currency rules 2-3).

Source: 国家外汇管理局 人民币汇率中间价 (State Administration of Foreign Exchange, RMB central parity),
via AKShare `currency_boc_safe` (CNY per 100 units of USD / HKD ...). Only the period-end rate is used:
the last published rate on or before the period end. Every converted figure carries source, date and type.
"""
from __future__ import annotations

import functools
import time

SOURCE_ZH = "国家外汇管理局 人民币汇率中间价"
SOURCE_EN = "SAFE RMB central parity rate"
LISTING_CCY = {"us": "USD", "hk": "HKD", "a": "CNY"}


@functools.lru_cache(maxsize=1)
def _table(_day):
    import akshare as ak

    df = ak.currency_boc_safe()
    df = df[["日期", "美元", "港元"]].dropna()
    df["日期"] = df["日期"].astype(str)
    return df.sort_values("日期")


def _cny_per(ccy, on):
    """CNY per 1 unit of ccy on the last publication date <= on. Returns (rate, date) or (None, None)."""
    if ccy == "CNY":
        return 1.0, on
    col = {"USD": "美元", "HKD": "港元"}.get(ccy)
    if col is None:
        return None, None
    df = _table(time.strftime("%Y-%m-%d"))
    row = df[df["日期"] <= on].tail(1)
    if row.empty:
        return None, None
    return float(row[col].iloc[0]) / 100.0, row["日期"].iloc[0]


def rate(src, dst, on):
    """Units of dst per 1 unit of src at period end `on` (YYYY-MM-DD).
    Returns {"rate", "date", "type", "source_zh", "source_en"} or None when a rate is missing."""
    if src == dst:
        return {"rate": 1.0, "date": on, "type": "none", "source_zh": "", "source_en": ""}
    try:
        a, da = _cny_per(src, on)
        b, db = _cny_per(dst, on)
    except Exception:  # noqa: BLE001  (source unreachable: show "rate missing", never guess)
        return None
    if not a or not b:
        return None
    return {"rate": a / b, "date": min(da, db), "type": "period_end", "source_zh": SOURCE_ZH,
            "source_en": SOURCE_EN}
