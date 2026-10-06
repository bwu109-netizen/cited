"""Period labels: '2026H1', '2026Q1', '2026Q3', '2026FY' (fiscal year = the year the fiscal year ends)."""
import calendar
import re
from datetime import date


def parse_period(label):
    m = re.fullmatch(r"(\d{4})(H1|Q1|Q2|Q3|FY)", label.upper())
    if not m:
        raise ValueError(f"period must look like 2026H1 / 2026Q1 / 2026Q3 / 2026FY, got {label!r}")
    return int(m.group(1)), m.group(2)


def _shift_month_end(d, months):
    y, m = d.year, d.month + months
    while m <= 0:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, calendar.monthrange(y, m)[1])


def period_end(label, fye_mmdd="12-31"):
    """Nominal period end for a company whose fiscal year ends on fye_mmdd (e.g. '03-31')."""
    year, part = parse_period(label)
    mm, dd = map(int, fye_mmdd.split("-"))
    fye = date(year, mm, dd)
    back = {"FY": 0, "Q3": -3, "H1": -6, "Q2": -6, "Q1": -9}[part]
    return _shift_month_end(fye, back) if back else fye


def cumulative_type(part):
    """Period type of the cumulative (year-to-date) figures in a report for this period."""
    return {"Q1": "Q", "H1": "H", "Q2": "H", "Q3": "YTD", "FY": "FY"}[part]


def type_from_days(days):
    if days <= 100:
        return "Q"
    if 170 <= days <= 190:
        return "H"
    if 350 <= days <= 371:
        return "FY"
    return "YTD"
