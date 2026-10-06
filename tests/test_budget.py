import pytest

from earnings_agent.budget import Budget, BudgetExceeded


def test_reserve_settle_and_cap(tmp_path):
    b = Budget(tmp_path / "ledger.jsonl", 1.0)
    with b.reserve(0.6, "a") as settle:
        assert b.status()["reserved"] == pytest.approx(0.6)
        settle(0.25)
    st = b.status()
    assert st["spent"] == pytest.approx(0.25) and st["reserved"] == 0 and st["left"] == pytest.approx(0.75)
    with pytest.raises(BudgetExceeded):
        with b.reserve(0.8, "too big"):
            pass
    assert b.status()["spent"] == pytest.approx(0.25)  # nothing charged for the refused call


def test_failed_call_keeps_worst_case(tmp_path):
    b = Budget(tmp_path / "ledger.jsonl", 1.0)
    with pytest.raises(RuntimeError):
        with b.reserve(0.3, "boom"):
            raise RuntimeError("network")
    assert b.status()["spent"] == pytest.approx(0.3)


def test_cap_survives_restart(tmp_path):
    p = tmp_path / "ledger.jsonl"
    with Budget(p, 1.0).reserve(0.9, "x") as settle:
        settle(0.9)
    with pytest.raises(BudgetExceeded):
        with Budget(p, 1.0).reserve(0.2, "y"):
            pass
