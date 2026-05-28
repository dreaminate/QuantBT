"""v1.0 · mainnet 7 项防御层测试。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.security.mainnet_guards import (
    MainnetGuardConfig,
    MainnetGuardError,
    MainnetGuardsService,
    derive_user_key,
    totp_generate_secret,
    totp_otpauth_uri,
    totp_verify,
)


@pytest.fixture
def svc(tmp_path: Path) -> MainnetGuardsService:
    os.environ["QUANTBT_MASTER_KEY"] = "test_master_key_64_chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    return MainnetGuardsService(tmp_path / "guards.db")


# ============================================================
# Per-user key derivation
# ============================================================


def test_per_user_key_deterministic_for_same_user():
    os.environ["QUANTBT_MASTER_KEY"] = "k1" * 32
    k1 = derive_user_key("u1")
    k2 = derive_user_key("u1")
    assert k1 == k2


def test_per_user_key_different_for_different_users():
    os.environ["QUANTBT_MASTER_KEY"] = "k1" * 32
    k1 = derive_user_key("u1")
    k2 = derive_user_key("u2")
    assert k1 != k2


def test_per_user_key_different_when_master_changes():
    os.environ["QUANTBT_MASTER_KEY"] = "a" * 32
    k1 = derive_user_key("u1")
    os.environ["QUANTBT_MASTER_KEY"] = "b" * 32
    k2 = derive_user_key("u1")
    assert k1 != k2


# ============================================================
# TOTP (RFC 6238)
# ============================================================


def test_totp_secret_base32():
    secret = totp_generate_secret()
    assert len(secret) >= 32  # 20 bytes base32 ≥ 32 chars


def test_totp_otpauth_uri_format():
    secret = totp_generate_secret()
    uri = totp_otpauth_uri(secret, account="alice@example.com")
    assert uri.startswith("otpauth://totp/QuantBT:")
    assert f"secret={secret}" in uri
    assert "issuer=QuantBT" in uri


def test_totp_verify_correct_code():
    """生成一个 valid 6 位码并校验。"""
    import hashlib, hmac, base64
    secret = totp_generate_secret()
    pad = (8 - len(secret) % 8) % 8
    secret_bytes = base64.b32decode(secret + "=" * pad)
    ts = int(time.time()) // 30
    h = hmac.new(secret_bytes, ts.to_bytes(8, "big"), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    token = (int.from_bytes(h[o:o + 4], "big") & 0x7FFFFFFF) % 1_000_000
    code = f"{token:06d}"
    assert totp_verify(secret, code) is True


def test_totp_verify_wrong_code():
    secret = totp_generate_secret()
    assert totp_verify(secret, "000000") is False or totp_verify(secret, "999999") is False


def test_totp_rejects_non_6digit():
    secret = totp_generate_secret()
    assert totp_verify(secret, "abc") is False
    assert totp_verify(secret, "12345") is False  # 5 digit
    assert totp_verify(secret, "1234567") is False


# ============================================================
# Service: IP whitelist
# ============================================================


def test_ip_check_rejects_when_no_whitelist(svc):
    assert svc.check_ip("u1", "1.2.3.4") is False


def test_ip_check_allows_exact_match(svc):
    cfg = MainnetGuardConfig(user_id="u1", trusted_ips=["1.2.3.4", "5.6.7.8"])
    svc.upsert_config(cfg)
    assert svc.check_ip("u1", "1.2.3.4") is True
    assert svc.check_ip("u1", "5.6.7.8") is True
    assert svc.check_ip("u1", "9.9.9.9") is False


def test_ip_check_allows_wildcard_prefix(svc):
    cfg = MainnetGuardConfig(user_id="u1", trusted_ips=["1.2.3.*"])
    svc.upsert_config(cfg)
    assert svc.check_ip("u1", "1.2.3.4") is True
    assert svc.check_ip("u1", "1.2.3.99") is True
    assert svc.check_ip("u1", "1.2.4.0") is False


# ============================================================
# Service: TOTP
# ============================================================


def test_enable_totp_returns_secret_and_uri(svc):
    secret, uri = svc.enable_totp("u1")
    assert len(secret) >= 32
    assert "otpauth://" in uri
    cfg = svc.get_config("u1")
    assert cfg.totp_enabled is True
    assert cfg.totp_secret_encrypted is not None


def test_totp_encrypted_storage_round_trip(svc):
    """加密存储 → service 自己 decrypt → 验证 code。"""
    secret_raw, _ = svc.enable_totp("u1")
    # 用 raw secret 生成 code
    import hashlib, hmac, base64
    pad = (8 - len(secret_raw) % 8) % 8
    s = base64.b32decode(secret_raw + "=" * pad)
    ts = int(time.time()) // 30
    h = hmac.new(s, ts.to_bytes(8, "big"), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    token = (int.from_bytes(h[o:o + 4], "big") & 0x7FFFFFFF) % 1_000_000
    code = f"{token:06d}"
    # service decrypt 后验证
    assert svc.verify_totp("u1", code) is True


def test_verify_totp_returns_false_when_not_enabled(svc):
    assert svc.verify_totp("u1", "000000") is False


# ============================================================
# Service: daily limits + audit
# ============================================================


def test_daily_usage_starts_zero(svc):
    usage = svc.get_today_usage("u1")
    assert usage["operations_today"] == 0
    assert usage["notional_today_usdt"] == 0.0


def test_audit_log_appends(svc):
    svc.log_operation("u1", "place_order", venue="binance", symbol="BTCUSDT",
                       side="buy", notional_usdt=50.0, source_ip="1.2.3.4", result="ok")
    log = svc.list_audit_log("u1")
    assert len(log) == 1
    assert log[0]["operation"] == "place_order"
    assert log[0]["result"] == "ok"


def test_daily_usage_after_log(svc):
    svc.log_operation("u1", "place_order", notional_usdt=100, result="ok")
    svc.log_operation("u1", "place_order", notional_usdt=200, result="ok")
    svc.log_operation("u1", "place_order", notional_usdt=999, result="rejected")  # 不计
    usage = svc.get_today_usage("u1")
    assert usage["operations_today"] == 2
    assert usage["notional_today_usdt"] == 300.0


def test_check_daily_limit_within(svc):
    ok, _ = svc.check_within_daily_limit("u1", 100.0)
    assert ok is True


def test_check_daily_limit_exceeded_notional(svc):
    cfg = MainnetGuardConfig(user_id="u1", daily_notional_limit_usdt=100)
    svc.upsert_config(cfg)
    ok, reason = svc.check_within_daily_limit("u1", 200.0)
    assert ok is False
    assert "名义价值" in reason or "notional" in reason.lower()


def test_check_daily_limit_exceeded_operations(svc):
    cfg = MainnetGuardConfig(user_id="u1", daily_operation_limit=2)
    svc.upsert_config(cfg)
    svc.log_operation("u1", "place_order", notional_usdt=10, result="ok")
    svc.log_operation("u1", "place_order", notional_usdt=10, result="ok")
    ok, reason = svc.check_within_daily_limit("u1", 5.0)
    assert ok is False
    assert "次" in reason or "operation" in reason.lower()


# ============================================================
# Service: assert_mainnet_allowed (综合校验)
# ============================================================


def test_assert_mainnet_rejects_no_whitelist_ip(svc):
    with pytest.raises(MainnetGuardError, match="IP"):
        svc.assert_mainnet_allowed(
            "u1", source_ip="1.2.3.4", totp_code=None,
            password_verified=True, operation="place_order",
        )


def test_assert_mainnet_rejects_wrong_ip(svc):
    cfg = MainnetGuardConfig(user_id="u1", trusted_ips=["10.0.0.1"])
    svc.upsert_config(cfg)
    with pytest.raises(MainnetGuardError, match="IP"):
        svc.assert_mainnet_allowed("u1", source_ip="1.2.3.4", totp_code=None,
                                    password_verified=True, operation="place_order")


def test_assert_mainnet_rejects_missing_totp(svc):
    cfg = MainnetGuardConfig(user_id="u1", trusted_ips=["1.2.3.4"])
    svc.upsert_config(cfg)
    svc.enable_totp("u1")  # totp_enabled=True
    with pytest.raises(MainnetGuardError, match="TOTP"):
        svc.assert_mainnet_allowed("u1", source_ip="1.2.3.4", totp_code=None,
                                    password_verified=True, operation="place_order")


def test_assert_mainnet_rejects_password_not_verified(svc):
    cfg = MainnetGuardConfig(user_id="u1", trusted_ips=["1.2.3.4"], totp_enabled=False)
    svc.upsert_config(cfg)
    with pytest.raises(MainnetGuardError, match="密码"):
        svc.assert_mainnet_allowed("u1", source_ip="1.2.3.4", totp_code=None,
                                    password_verified=False, operation="place_order")


def test_assert_mainnet_passes_when_all_satisfied(svc):
    cfg = MainnetGuardConfig(user_id="u1", trusted_ips=["1.2.3.4"], totp_enabled=False)
    svc.upsert_config(cfg)
    # 不应 raise
    svc.assert_mainnet_allowed("u1", source_ip="1.2.3.4", totp_code=None,
                                password_verified=True, operation="place_order",
                                notional_usdt=10.0)


def test_audit_log_records_rejection_reason(svc):
    try:
        svc.assert_mainnet_allowed("u1", source_ip="1.2.3.4", totp_code=None,
                                    password_verified=True, operation="place_order")
    except MainnetGuardError:
        pass
    log = svc.list_audit_log("u1")
    assert len(log) >= 1
    assert log[0]["result"] == "rejected"
    assert "ip_not_whitelisted" in (log[0]["error"] or "")
