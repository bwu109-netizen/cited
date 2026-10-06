"""Industry template (general / bank / insurance): industry code first, statement structure as cross-check."""
import re

from .textnorm import for_match

FIELDS = {
    "general": ["revenue", "net_income_parent", "eps_basic", "gross_profit", "operating_cash_flow"],
    "bank": ["revenue", "net_income_parent", "eps_basic", "operating_cash_flow", "net_interest_income", "ppop"],
    "insurance": ["revenue", "net_income_parent", "eps_basic", "operating_cash_flow", "insurance_revenue",
                  "insurance_service_result"],
}
# optional sub-fields / derivation inputs the model may also return
AUX_FIELDS = ["net_income_common", "eps_basic_per_ads", "cost_of_revenue", "weighted_avg_shares_basic"]


def template_from_code(industry):
    src, code, name = industry.get("source", ""), str(industry.get("code") or ""), industry.get("name") or ""
    if "SIC" in src and code.isdigit():
        c = int(code)
        if c in (6021, 6022, 6029, 6035, 6036):
            return "bank"
        if 6311 <= c <= 6399 or c == 6411:
            return "insurance"
        return "general"
    if re.search(r"货币金融服务|^银行|銀行", name):
        return "bank"
    if re.search(r"保险|保險", name):
        return "insurance"
    return "general" if name else None


# patterns are matched against for_match() text, which is lowercase simplified Chinese
_NII = re.compile(r"利息净收入|净利息收入|净利息收益|netinterestincome")
_COST = re.compile(r"营业成本|销售成本|收入成本|costofrevenue|costofsales|costofgoodssold|totalcostofsales")
_INS = re.compile(r"保险服务收入|已赚保费|insurancerevenue|netpremiumsearned")


def template_from_structure(statement_pages):
    """statement_pages: texts of the pages located as the income statement."""
    t = for_match("\n".join(statement_pages))
    if not t:
        return None
    # banks (e.g. bancassurance groups) also show insurance lines, so test bank first
    if _NII.search(t) and not _COST.search(t):
        return "bank"
    if _INS.search(t) and not _COST.search(t):
        return "insurance"
    if _COST.search(t):
        return "general"
    return None


def choose_template(industry, statement_pages):
    by_code = template_from_code(industry)
    by_struct = template_from_structure(statement_pages)
    if by_code and by_struct and by_code != by_struct:
        return by_struct, {"template_conflict": f"行业代码判为 {by_code}，报表结构判为 {by_struct}，按报表结构"}
    return by_struct or by_code or "general", {}
