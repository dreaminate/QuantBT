"""v0.8.9 · Copy-trade beta + idempotency + follower override 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.copy_trade.beta import (
    BETA_FOLLOWER_QUOTA,
    BETA_MASTER_QUOTA,
    CopyTradeBetaService,
    IdempotencyViolation,
    apply_follower_leverage_cap,
)


@pytest.fixture
def svc(tmp_path: Path) -> CopyTradeBetaService:
    return CopyTradeBetaService(tmp_path / "ct_beta.db")


# ============================================================
# Idempotency (核心: signal_id + follower_id 唯一)
# ============================================================


def test_first_dispatch_succeeds(svc: CopyTradeBetaService):
    rec = svc.record_dispatch("sig_1", "f_1", "m_1")
    assert rec.idempotency_key == "sig_1::f_1"
    assert rec.clamped is False


def test_duplicate_dispatch_raises(svc: CopyTradeBetaService):
    svc.record_dispatch("sig_1", "f_1", "m_1")
    with pytest.raises(IdempotencyViolation):
        svc.record_dispatch("sig_1", "f_1", "m_1")


def test_same_signal_different_followers_ok(svc: CopyTradeBetaService):
    svc.record_dispatch("sig_1", "f_1", "m_1")
    svc.record_dispatch("sig_1", "f_2", "m_1")
    svc.record_dispatch("sig_1", "f_3", "m_1")
    # 3 个 follower 都能 dispatch 同一 signal


def test_is_dispatched_check(svc: CopyTradeBetaService):
    assert svc.is_dispatched("sig_1", "f_1") is False
    svc.record_dispatch("sig_1", "f_1", "m_1")
    assert svc.is_dispatched("sig_1", "f_1") is True


def test_list_dispatches_for_follower(svc: CopyTradeBetaService):
    svc.record_dispatch("sig_1", "f_1", "m_1")
    svc.record_dispatch("sig_2", "f_1", "m_1")
    svc.record_dispatch("sig_3", "f_2", "m_1")  # 不同 follower
    rs = svc.list_dispatches("f_1")
    assert len(rs) == 2


# ============================================================
# Follower leverage hard cap (核心 patch1 §G.a #12)
# ============================================================


def test_leverage_no_clamp_when_under_cap():
    applied, clamped = apply_follower_leverage_cap(master_leverage=2.0, follower_max_leverage=5.0)
    assert applied == 2.0
    assert clamped is False


def test_leverage_clamps_when_over_cap():
    """master 发 10x，follower cap 2x → 必须截到 2x。"""
    applied, clamped = apply_follower_leverage_cap(master_leverage=10.0, follower_max_leverage=2.0)
    assert applied == 2.0
    assert clamped is True


def test_leverage_no_follower_cap_uses_master():
    applied, clamped = apply_follower_leverage_cap(master_leverage=5.0, follower_max_leverage=None)
    assert applied == 5.0
    assert clamped is False


def test_leverage_zero_follower_cap_treated_as_none():
    applied, clamped = apply_follower_leverage_cap(master_leverage=5.0, follower_max_leverage=0)
    assert applied == 5.0
    assert clamped is False


def test_leverage_master_none_returns_none():
    applied, clamped = apply_follower_leverage_cap(master_leverage=None, follower_max_leverage=2.0)
    assert applied is None
    assert clamped is False


def test_dispatch_records_clamp_flag(svc: CopyTradeBetaService):
    rec = svc.record_dispatch(
        "sig_1", "f_1", "m_1",
        master_leverage=10.0, follower_applied_leverage=2.0, clamped=True,
    )
    assert rec.clamped is True
    assert rec.master_leverage == 10.0
    assert rec.follower_applied_leverage == 2.0


# ============================================================
# Beta gate (5 master / 50 follower)
# ============================================================


def test_quotas_set_to_5_and_50():
    assert BETA_MASTER_QUOTA == 5
    assert BETA_FOLLOWER_QUOTA == 50


def test_first_master_application_enabled(svc: CopyTradeBetaService):
    s = svc.apply_for_beta("u1", "master")
    assert s.status == "enabled"
    assert s.quota_limit == 5
    assert svc.is_beta_enabled("u1", "master") is True


def test_master_quota_5_then_waitlist(svc: CopyTradeBetaService):
    for i in range(5):
        s = svc.apply_for_beta(f"m_{i}", "master")
        assert s.status == "enabled"
    s_6 = svc.apply_for_beta("m_overflow", "master")
    assert s_6.status == "waitlist"
    assert svc.is_beta_enabled("m_overflow", "master") is False


def test_follower_quota_50_then_waitlist(svc: CopyTradeBetaService):
    for i in range(50):
        svc.apply_for_beta(f"f_{i}", "follower")
    s_overflow = svc.apply_for_beta("f_51", "follower")
    assert s_overflow.status == "waitlist"


def test_apply_same_user_idempotent(svc: CopyTradeBetaService):
    svc.apply_for_beta("u1", "master")
    s2 = svc.apply_for_beta("u1", "master")
    assert s2.status == "enabled"


def test_get_beta_status_none(svc: CopyTradeBetaService):
    assert svc.get_beta_status("never_applied", "master") is None


def test_waitlist_summary(svc: CopyTradeBetaService):
    svc.apply_for_beta("u1", "master")
    svc.apply_for_beta("u2", "follower")
    summary = svc.waitlist_summary()
    assert summary["master"]["enabled"] >= 1
    assert summary["master"]["quota"] == 5
    assert summary["follower"]["enabled"] >= 1
    assert summary["follower"]["quota"] == 50


def test_invalid_role_raises(svc: CopyTradeBetaService):
    with pytest.raises(ValueError):
        svc.apply_for_beta("u1", "evil_role")
