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


_SAFE = {
    "ipRestrict": True,
    "enableReading": True,
    "enableFutures": True,
    "enableWithdrawals": False,
    "enableInternalTransfer": False,
    "permitsUniversalTransfer": False,
}


def _client(payload: dict) -> BinanceClient:
    c = BinanceClient(
        BinanceCredentials(api_key="k", api_secret="s", network="mainnet"),
        product="usdm_futures",
    )
    # 拦截 _signed 直接返回 payload，避免真发请求
    c._signed = MagicMock(return_value=payload)  # type: ignore[assignment]
    c.sync_time = MagicMock(return_value=0)  # type: ignore[assignment]
    return c


def test_safekey_passes_clean_key():
    c = _client({
        **_SAFE,
        "enableMargin": False,
    })
    result = c.assert_safe_startup()
    assert result["ok"] is True
    assert result["warnings"] == []
    assert result["ip_restricted"] is True
    assert result["permission_state"]["enableWithdrawals"] is False


def test_safekey_raises_on_withdraw_enabled():
    c = _client({**_SAFE, "enableWithdrawals": True})
    with pytest.raises(BinanceWithdrawPermissionError, match="enableWithdrawals"):
        c.assert_safe_startup()


def test_safekey_raises_on_internal_transfer_enabled():
    """旧实现漏：'internalTransfer' 字段里 'withdraw' 子串不存在 → 不报。新实现必拦。"""

    c = _client({**_SAFE, "enableInternalTransfer": True})
    with pytest.raises(BinanceWithdrawPermissionError, match="enableInternalTransfer"):
        c.assert_safe_startup()


def test_safekey_raises_on_universal_transfer_enabled():
    c = _client({**_SAFE, "permitsUniversalTransfer": True})
    with pytest.raises(BinanceWithdrawPermissionError, match="permitsUniversalTransfer"):
        c.assert_safe_startup()


def test_safekey_warns_but_passes_on_margin_enabled():
    c = _client({
        **_SAFE,
        "enableMargin": True,
    })
    result = c.assert_safe_startup()
    assert result["ok"] is True
    assert any("margin" in w.lower() for w in result["warnings"])


def test_safekey_warns_on_no_ip_restriction():
    c = _client({**_SAFE, "ipRestrict": False})
    with pytest.raises(PermissionError, match="ipRestrict"):
        c.assert_safe_startup()


def test_safekey_aggregates_multiple_drain_keys_in_error():
    c = _client({**_SAFE, "enableWithdrawals": True, "enableInternalTransfer": True})
    with pytest.raises(BinanceWithdrawPermissionError) as exc:
        c.assert_safe_startup()
    msg = str(exc.value)
    assert "enableWithdrawals" in msg
    assert "enableInternalTransfer" in msg


@pytest.mark.parametrize("field", tuple(_SAFE))
def test_safekey_missing_or_non_boolean_required_field_fails_closed(field):
    missing = dict(_SAFE)
    missing.pop(field)
    with pytest.raises(PermissionError, match=field):
        _client(missing).assert_safe_startup()

    non_boolean = {**_SAFE, field: int(_SAFE[field])}
    with pytest.raises(PermissionError, match=field):
        _client(non_boolean).assert_safe_startup()


def test_fix_api_trade_cannot_substitute_for_futures_permission():
    c = _client({**_SAFE, "enableFutures": False, "enableFixApiTrade": True})
    with pytest.raises(PermissionError, match="enableFutures"):
        c.assert_safe_startup()
