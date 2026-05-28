"""v0.8.8 · 安全阶梯测试 (W9)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.trading.safety import (
    LADDER_ORDER,
    PROMOTION_REQ_ORDERS,
    SafetyService,
    SafetyServiceError,
)


@pytest.fixture
def svc(tmp_path: Path) -> SafetyService:
    return SafetyService(tmp_path / "safety.db")


# ============================================================
# SafeKey wizard
# ============================================================


def test_safekey_passes_clean_config(svc: SafetyService):
    rec = svc.record_safekey_check(
        "u1", "hash1",
        enable_withdrawals=False,
        enable_internal_transfer=False,
        enable_universal_transfer=False,
        enable_futures=True,
        ip_restricted=True,
    )
    assert rec.passed is True
    assert rec.failures == []


def test_safekey_fails_withdraw_enabled(svc: SafetyService):
    rec = svc.record_safekey_check("u1", "h", enable_withdrawals=True)
    assert rec.passed is False
    assert any("enableWithdrawals" in f for f in rec.failures)


def test_safekey_fails_internal_transfer(svc: SafetyService):
    rec = svc.record_safekey_check(
        "u1", "h",
        enable_withdrawals=False,
        enable_internal_transfer=True,
    )
    assert rec.passed is False


def test_safekey_warns_margin_enabled(svc: SafetyService):
    rec = svc.record_safekey_check(
        "u1", "h",
        enable_withdrawals=False,
        enable_margin=True,
    )
    assert rec.passed is True
    assert any("margin" in w.lower() for w in rec.warnings)


def test_safekey_warns_no_ip_restriction(svc: SafetyService):
    rec = svc.record_safekey_check(
        "u1", "h",
        enable_withdrawals=False,
        ip_restricted=False,
    )
    assert rec.passed is True
    assert any("ip" in w.lower() for w in rec.warnings)


def test_safekey_get_latest_persists(svc: SafetyService):
    # 同 user_id 的 key_id_hash UNIQUE：测试覆盖更新一条
    rec = svc.record_safekey_check("u1", "h_only", enable_withdrawals=False)
    svc.record_safekey_check("u1", "h_only", enable_withdrawals=False)  # 更新
    latest = svc.get_latest_safekey("u1")
    assert latest is not None
    assert latest.key_id_hash == "h_only"


def test_safekey_get_latest_none_when_no_record(svc: SafetyService):
    assert svc.get_latest_safekey("u_never") is None


# ============================================================
# Testnet matrix
# ============================================================


def test_matrix_default_all_not_attempted(svc: SafetyService):
    state = svc.get_matrix("u1")
    assert state.total_count == 12
    assert state.completed_count == 0
    assert all(c.status == "not_attempted" for c in state.cells)


def test_matrix_record_ok_attempt(svc: SafetyService):
    svc.record_matrix_attempt("u1", "limit", "buy",
                               place_ok=True, query_ok=True, cancel_ok=True, reconcile_ok=True)
    state = svc.get_matrix("u1")
    assert state.completed_count == 1
    limit_buy = next(c for c in state.cells if c.order_type == "limit" and c.side == "buy")
    assert limit_buy.status == "ok"


def test_matrix_record_failed_attempt(svc: SafetyService):
    svc.record_matrix_attempt("u1", "stop_market", "sell",
                               place_ok=True, query_ok=False, cancel_ok=True, reconcile_ok=True,
                               error_code="-2010")
    state = svc.get_matrix("u1")
    cell = next(c for c in state.cells if c.order_type == "stop_market" and c.side == "sell")
    assert cell.status == "failed"
    assert cell.error_code == "-2010"


def test_matrix_completion_pct(svc: SafetyService):
    # 完成 6 / 12 = 50%
    for ot, side in [("limit", "buy"), ("limit", "sell"), ("market", "buy"), ("market", "sell"),
                      ("stop_market", "buy"), ("stop_market", "sell")]:
        svc.record_matrix_attempt("u1", ot, side,
                                   place_ok=True, query_ok=True, cancel_ok=True, reconcile_ok=True)
    state = svc.get_matrix("u1")
    assert state.completed_count == 6
    assert state.completion_pct == 50.0


# ============================================================
# Live ladder
# ============================================================


def test_ladder_starts_at_level_0(svc: SafetyService):
    state = svc.get_ladder("u1")
    assert state.current_level == "level_0"
    assert state.successful_orders_at_level == 0


def test_ladder_cannot_promote_without_safekey(svc: SafetyService):
    state = svc.get_ladder("u1")
    assert state.can_promote is False
    with pytest.raises(SafetyServiceError):
        svc.promote_level("u1")


def test_ladder_can_promote_l0_to_l1_with_safekey_only(svc: SafetyService):
    svc.record_safekey_check("u1", "h", enable_withdrawals=False)
    state = svc.get_ladder("u1")
    assert state.safekey_passed is True
    assert state.can_promote is True
    new_state = svc.promote_level("u1")
    assert new_state.current_level == "level_1"


def test_ladder_promote_l1_to_l2_requires_testnet_matrix_full(svc: SafetyService):
    svc.record_safekey_check("u1", "h", enable_withdrawals=False)
    svc.promote_level("u1")  # → level_1
    state = svc.get_ladder("u1")
    assert state.current_level == "level_1"
    # 还没 testnet matrix 100% → 不可晋级 level_2
    assert state.can_promote is False
    # 完成全部 12 cell
    for ot, side in [(t, s) for t in ["limit", "market", "stop_market", "take_profit",
                                        "stop_loss", "trailing_stop_market"] for s in ["buy", "sell"]]:
        svc.record_matrix_attempt("u1", ot, side,
                                   place_ok=True, query_ok=True, cancel_ok=True, reconcile_ok=True)
    state = svc.get_ladder("u1")
    assert state.testnet_matrix_passed is True
    assert state.can_promote is True
    new_state = svc.promote_level("u1")
    assert new_state.current_level == "level_2"


def test_ladder_demote_blocks_promotion_24h(svc: SafetyService):
    svc.record_safekey_check("u1", "h", enable_withdrawals=False)
    svc.promote_level("u1")  # → level_1
    state = svc.demote("u1", "kill_switch triggered")
    assert state.current_level == "level_0"
    assert state.blocked_reason == "kill_switch triggered"
    assert state.promotion_blocked_until_utc is not None
    # blocked → 即使 SafeKey/matrix 通过也不能立刻晋级
    assert state.can_promote is False


def test_record_successful_order_increments_counter(svc: SafetyService):
    svc.record_safekey_check("u1", "h", enable_withdrawals=False)
    svc.promote_level("u1")
    c1 = svc.record_successful_order("u1")
    c2 = svc.record_successful_order("u1")
    assert c1 == 1 and c2 == 2


# ============================================================
# Promotion 配置
# ============================================================


def test_ladder_order_has_6_levels():
    assert len(LADDER_ORDER) == 6
    assert LADDER_ORDER[0] == "level_0"
    assert LADDER_ORDER[-1] == "level_5"


def test_promotion_req_orders_monotonic():
    """高级别要求订单数应该 >= 低级别。"""
    vals = [PROMOTION_REQ_ORDERS[lv] for lv in LADDER_ORDER]
    assert vals == sorted(vals)
