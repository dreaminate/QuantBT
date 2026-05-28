"""v0.8.3.1 hotfix · SafeKey 扩展检查范围。

旧实现只挡含 "withdraw" 子串的字段。新实现：
  - 资金外流类 (withdraw / internalTransfer / universalTransfer) → raise
  - margin 借贷 → warn
  - ipRestrict=false → warn
返回 detail 含 permission_state / warnings / ip_restricted。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.execution.binance_client import BinanceClient, BinanceCredentials, BinanceWithdrawPermissionError


def _client(payload: dict) -> BinanceClient:
    c = BinanceClient(
        BinanceCredentials(api_key="k", api_secret="s", network="testnet"),
        product="usdm_futures",
    )
    # 拦截 _signed 直接返回 payload，避免真发请求
    c._signed = MagicMock(return_value=payload)  # type: ignore[assignment]
    c.sync_time = MagicMock(return_value=0)  # type: ignore[assignment]
    return c


def test_safekey_passes_clean_key():
    c = _client({
        "ipRestrict": True,
        "enableWithdrawals": False,
        "enableInternalTransfer": False,
        "enableUniversalTransfer": False,
        "enableMargin": False,
        "enableFutures": True,
        "enableReading": True,
    })
    result = c.assert_safe_startup()
    assert result["ok"] is True
    assert result["warnings"] == []
    assert result["ip_restricted"] is True
    assert result["permission_state"]["enableWithdrawals"] is False


def test_safekey_raises_on_withdraw_enabled():
    c = _client({"enableWithdrawals": True, "enableFutures": True})
    with pytest.raises(BinanceWithdrawPermissionError, match="enableWithdrawals"):
        c.assert_safe_startup()


def test_safekey_raises_on_internal_transfer_enabled():
    """旧实现漏：'internalTransfer' 字段里 'withdraw' 子串不存在 → 不报。新实现必拦。"""

    c = _client({"enableInternalTransfer": True, "enableWithdrawals": False})
    with pytest.raises(BinanceWithdrawPermissionError, match="enableInternalTransfer"):
        c.assert_safe_startup()


def test_safekey_raises_on_universal_transfer_enabled():
    c = _client({"enableUniversalTransfer": True, "enableWithdrawals": False})
    with pytest.raises(BinanceWithdrawPermissionError, match="enableUniversalTransfer"):
        c.assert_safe_startup()


def test_safekey_warns_but_passes_on_margin_enabled():
    c = _client({
        "ipRestrict": True,
        "enableWithdrawals": False,
        "enableMargin": True,
        "enableFutures": True,
    })
    result = c.assert_safe_startup()
    assert result["ok"] is True
    assert any("margin" in w.lower() for w in result["warnings"])


def test_safekey_warns_on_no_ip_restriction():
    c = _client({
        "ipRestrict": False,
        "enableWithdrawals": False,
        "enableFutures": True,
    })
    result = c.assert_safe_startup()
    assert result["ok"] is True
    assert result["ip_restricted"] is False
    assert any("iprestrict" in w.lower() or "ip" in w.lower() for w in result["warnings"])


def test_safekey_aggregates_multiple_drain_keys_in_error():
    c = _client({
        "enableWithdrawals": True,
        "enableInternalTransfer": True,
    })
    with pytest.raises(BinanceWithdrawPermissionError) as exc:
        c.assert_safe_startup()
    msg = str(exc.value)
    assert "enableWithdrawals" in msg
    assert "enableInternalTransfer" in msg


def test_safekey_ip_keys_missing_returns_null():
    """有些 endpoint 不带 ipRestrict 字段 → ip_restricted 应为 None 而非 False。"""

    c = _client({"enableWithdrawals": False, "enableFutures": True})
    result = c.assert_safe_startup()
    assert result["ip_restricted"] is None
    # 没 ipRestrict 字段时也不应产生 ip warning
    assert not any("iprestrict" in w.lower() for w in result["warnings"])
