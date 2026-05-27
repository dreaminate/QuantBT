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


@dataclass
class BinanceCredentials:
    api_key: str
    api_secret: str
    network: BinanceNetwork = "testnet"

    @classmethod
    def from_record(cls, record: KeystoreRecord, network: BinanceNetwork = "testnet") -> "BinanceCredentials":
        return cls(api_key=record.api_key, api_secret=record.api_secret, network=network)


class BinanceWithdrawPermissionError(PermissionError):
    """API key 检测到 withdraw 权限 → 立即停。"""


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
        """读 apiRestrictions / apiKey permissions，若有 withdraw 立即 raise。"""

        try:
            self.sync_time()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Binance 校时失败：%s", exc)
        path = (
            "/fapi/v1/apiKey/permissions"
            if self._product == "usdm_futures"
            else "/sapi/v1/account/apiRestrictions"
        )
        payload = self._signed("GET", path, {})
        withdraw_keys = [k for k in payload if "withdraw" in str(k).lower()]
        for key in withdraw_keys:
            if bool(payload.get(key)):
                raise BinanceWithdrawPermissionError(
                    f"Binance {self._product} API key 含 {key}=True，拒绝启动。"
                    " 请到 Binance 网页 → API 管理 → 编辑限制 → 取消 withdraw / universal-transfer 权限后重启。"
                )
        return {"ok": True, "network": self._cred.network, "product": self._product, "raw": payload}

    def signed(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._signed(method, path, params or {})

    def public(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._base + path
        r = self._http.request(method, url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
        ts_ms = int(time.time() * 1000) + self._time_offset_ms
        full_params = {**params, "timestamp": ts_ms, "recvWindow": self._recv}
        qs = urllib.parse.urlencode(full_params, doseq=True)
        signature = hmac.new(
            self._cred.api_secret.encode("utf-8"),
            qs.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = self._base + path
        headers = {"X-MBX-APIKEY": self._cred.api_key}
        send_params = {**full_params, "signature": signature}
        r = self._http.request(method, url, params=send_params if method == "GET" else None,
                               data=send_params if method != "GET" else None,
                               headers=headers, timeout=10)
        if r.status_code == 429 or r.status_code == 418:
            sleep_s = 60
            logger.warning("Binance 限流 %d，sleep %ds", r.status_code, sleep_s)
            time.sleep(sleep_s)
        r.raise_for_status()
        return r.json()


__all__ = [
    "BASE_URLS",
    "BinanceClient",
    "BinanceCredentials",
    "BinanceNetwork",
    "BinanceProduct",
    "BinanceWithdrawPermissionError",
]
