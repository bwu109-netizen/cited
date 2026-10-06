from earnings_agent.templates import choose_template

BANKLIKE = "合并利润表\n利息净收入 100\n保险服务收入 50\n营业利润 30"


def test_insurer_owning_a_bank_keeps_insurance_template():
    tpl, notes = choose_template({"source": "cninfo 证监会行业", "name": "保险业"}, [BANKLIKE])
    assert tpl == "insurance" and "template_conflict" in notes


def test_structure_decides_when_code_is_general_or_missing():
    assert choose_template({"source": "x", "name": "综合"}, [BANKLIKE])[0] == "bank"
    assert choose_template({}, ["营业收入 10\n营业成本 5"])[0] == "general"


def test_bank_code():
    assert choose_template({"source": "SEC SIC", "code": "6021"}, ["Revenue 1"])[0] == "bank"
