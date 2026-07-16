"""M9.3 · Binance REST 客户端共享层。

不引 python-binance / binance-connector，直接 HMAC-SHA256 签名 + requests。这样：
- 依赖最少
- API key/secret 永远走 SecureKeystore，签名时再 in-memory 解出，不进日志

GOAL §M9.3 关键保护：
- **启动时**必须校验 API key **无 withdraw 权限** → 否则 raise PermissionError
- IP 白名单告警（非阻断，给提示）
- testnet/mainnet 明确分网络
- 校时 (`/api/v3/time`)
- `recvWindow` 默认 5000ms
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Literal

import requests

from ..security.keystore import KeystoreRecord


logger = logging.getLogger(__name__)


BinanceNetwork = Literal["mainnet", "testnet"]
BinanceProduct = Literal["spot", "usdm_futures"]


BASE_URLS: dict[tuple[BinanceProduct, BinanceNetwork], str] = {
    ("spot", "mainnet"): "https://api.binance.com",
    ("spot", "testnet"): "https://testnet.binance.vision",
    ("usdm_futures", "mainnet"): "https://fapi.binance.com",
    ("usdm_futures", "testnet"): "https://testnet.binancefuture.com",
}

# Binance documents API-key permission inspection under the Wallet API, not
# under the USD-M Futures REST base.  Keep this explicit so a futures client
# cannot silently fall back to an undocumented ``/fapi/.../permissions`` path.
WALLET_MAINNET_BASE_URL = "https://api.binance.com"


@dataclass
class BinanceCredentials:
    api_key: str
    api_secret: str
    network: BinanceNetwork = "testnet"

    @classmethod
    def from_record(cls, record: KeystoreRecord, network: BinanceNetwork = "testnet") -> "BinanceCredentials":
        return cls(api_key=record.api_key, api_secret=record.api_secret, network=network)

    def __repr__(self) -> str:  # 防明文：repr / str 永不暴露 api_key / api_secret
        return (
            f"BinanceCredentials(network={self.network!r}, api_key=<redacted>, "
            f"api_secret=<redacted>)"
        )

    __str__ = __repr__


class BinanceWithdrawPermissionError(PermissionError):
    """API key 检测到资金外流类权限 → 立即停。

    v0.8.3.1 起拦截范围扩展到 withdraw / internalTransfer / universalTransfer 三类。
    """


class BinanceAPIError(RuntimeError):
    """Structured Binance HTTP/API rejection after a response was received."""

    def __init__(self, *, status_code: int, code: int | None, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_sent = True
        super().__init__(
            f"Binance API error status={status_code} code={code if code is not None else 'unknown'} "
            f"msg={message or '<missing>'}"
        )


# 高风险但 trading-only key 可能合理开启的权限：警告但不拦截
_HIGH_RISK_KEYWORDS = ("margin",)


class BinanceClient:
    def __init__(
        self,
        credentials: BinanceCredentials,
        product: BinanceProduct,
        session: requests.Session | None = None,
        recv_window_ms: int = 5_000,
    ) -> None:
        self._cred = credentials
        self._product: BinanceProduct = product
        self._http = session or requests.Session()
        self._recv = recv_window_ms
        self._base = BASE_URLS[(product, credentials.network)]
        self._time_offset_ms = 0

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def network(self) -> BinanceNetwork:
        return self._cred.network

    @property
    def product(self) -> BinanceProduct:
        return self._product

    def sync_time(self) -> int:
        url = self._base + ("/fapi/v1/time" if self._product == "usdm_futures" else "/api/v3/time")
        r = self._http.get(url, timeout=5)
        r.raise_for_status()
        server_ms = int(r.json()["serverTime"])
        local_ms = int(time.time() * 1000)
        self._time_offset_ms = server_ms - local_ms
        return self._time_offset_ms

    def assert_safe_startup(self) -> dict[str, Any]:
        """读 apiRestrictions / apiKey permissions，分级校验:

        - 资金外流类（withdraw / internalTransfer / universalTransfer）→ raise
        - margin 借贷类 → 仅 warn，记入返回的 warnings 列表
        - ipRestrict=false → warn（推荐用户加 IP 白名单）

        v0.8.3.1 hotfix：旧实现只匹配 "withdraw" 子串，漏掉 internalTransfer / universalTransfer
        / margin / ipRestrict 等关键 surface。
        """

        if self._cred.network != "mainnet":
            raise PermissionError(
                "Binance futures testnet has no documented API-key permission endpoint; "
                "permission safety cannot be verified and automatic trading activation is denied"
            )

        try:
            self.sync_time()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Binance 校时失败：%s", exc)
        path = "/sapi/v1/account/apiRestrictions"
        payload = self._signed("GET", path, {}, base_url=WALLET_MAINNET_BASE_URL)
        if not isinstance(payload, dict):
            raise ValueError("Binance API-key permission endpoint returned a non-object")
        warnings: list[str] = []
        permission_state: dict[str, bool] = {}
        for raw_key, raw_val in payload.items():
            if isinstance(raw_val, bool):
                permission_state[raw_key] = raw_val
            if isinstance(raw_val, bool) and any(
                kw in str(raw_key).lower() for kw in _HIGH_RISK_KEYWORDS
            ) and raw_val:
                warnings.append(f"{raw_key}=True（margin 借贷开启，被攻破时可能放大损失）")

        required_exact: dict[str, bool] = {
            "ipRestrict": True,
            "enableReading": True,
            "enableWithdrawals": False,
            "enableInternalTransfer": False,
            "permitsUniversalTransfer": False,
            (
                "enableFutures"
                if self._product == "usdm_futures"
                else "enableSpotAndMarginTrading"
            ): True,
        }
        missing_or_invalid = [
            key
            for key, expected in required_exact.items()
            if key not in payload
            or not isinstance(payload.get(key), bool)
            or payload.get(key) is not expected
        ]
        drain_fields = {
            "enableWithdrawals",
            "enableInternalTransfer",
            "permitsUniversalTransfer",
        }
        drain_enabled = [
            key for key in drain_fields if payload.get(key) is True
        ]
        if drain_enabled:
            raise BinanceWithdrawPermissionError(
                f"Binance {self._product} API key 含资金外流权限 [{', '.join(sorted(drain_enabled))}]，拒绝启动。"
            )
        if missing_or_invalid:
            expected = ", ".join(
                f"{key}={value}" for key, value in required_exact.items()
            )
            raise PermissionError(
                "Binance API-key permission proof is incomplete or mismatched: "
                f"{', '.join(sorted(missing_or_invalid))}; required {expected}"
            )
        ip_restricted = True

        return {
            "ok": True,
            "network": self._cred.network,
            "product": self._product,
            "permission_state": permission_state,
            "warnings": warnings,
            "ip_restricted": ip_restricted,
            "raw": payload,
        }

    def signed(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._signed(method, path, params or {})

    def public(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._base + path
        r = self._http.request(method, url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _signed(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        *,
        base_url: str | None = None,
    ) -> Any:
        ts_ms = int(time.time() * 1000) + self._time_offset_ms
        full_params = {**params, "timestamp": ts_ms, "recvWindow": self._recv}
        qs = urllib.parse.urlencode(full_params, doseq=True)
        signature = hmac.new(
            self._cred.api_secret.encode("utf-8"),
            qs.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = (base_url or self._base) + path
        headers = {"X-MBX-APIKEY": self._cred.api_key}
        send_params = {**full_params, "signature": signature}
        r = self._http.request(method, url, params=send_params if method == "GET" else None,
                               data=send_params if method != "GET" else None,
                               headers=headers, timeout=10)
        status_code = r.status_code if isinstance(r.status_code, int) else 0
        if status_code >= 400:
            try:
                error_payload = r.json()
            except Exception:  # noqa: BLE001
                error_payload = {}
            code_raw = error_payload.get("code") if isinstance(error_payload, dict) else None
            try:
                code = int(code_raw) if code_raw is not None else None
            except (TypeError, ValueError):
                code = None
            message = (
                str(error_payload.get("msg") or "")
                if isinstance(error_payload, dict)
                else ""
            )
            raise BinanceAPIError(status_code=status_code, code=code, message=message)
        r.raise_for_status()
        return r.json()


__all__ = [
    "BASE_URLS",
    "BinanceClient",
    "BinanceCredentials",
    "BinanceAPIError",
    "BinanceNetwork",
    "BinanceProduct",
    "BinanceWithdrawPermissionError",
    "WALLET_MAINNET_BASE_URL",
]
