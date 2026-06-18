"""LeasedBinanceVenue · INV-3 lease-唯一-key venue 外壳（T-022 / spine 06 §4）。

T-021 把 deny-by-default 策略门接进 relay（INV-2/M17 生产强制），但生产 binance venue 仍在工厂
self-fetch key（构造即持 creds）。本外壳关掉 self-fetch：**构造时不持任何 key**，下单时只认 OrderGuard
S4 发的 JIT lease，从 `lease.record` 现造 creds+client+真 venue 签名提交，用完即弃——真 key 只在
`place_order` 那一刻活在后端内存（INV-3：无 lease = 无 key = 下不了单）。

既有 BinanceUMFuturesVenue / BinanceSpotVenue / BinanceClient **完全不动**（成为本外壳按需实例化的内核），
故既有实盘签名逻辑零改动、零回归面；本外壳是纯新增（additive）。

诚实 TCB 边界（设计 §7-5）：broker / 本外壳都在属主机内存里——lease 把 key 暴露窗口从"venue 全生命周期"
收窄到"单次 place_order"，**抬高代价、非干净修复**；被攻破属主机时短时 lease 仍可被截。
"""

from __future__ import annotations

from typing import Any

from .base import Balance, CancelAck, ExecutionAuditLog, ExecutionVenue, Order, OrderAck, Position
from .binance_client import BinanceClient, BinanceCredentials, BinanceNetwork, BinanceProduct

_NO_LEASE = "lease-only venue 必须经 OrderGuard 提供 JIT lease（INV-3：无 lease=无 key=不下单/不查私有端点）"


class LeasedBinanceVenue(ExecutionVenue):
    name = "leased_binance"

    def __init__(
        self,
        *,
        product: BinanceProduct,
        network: BinanceNetwork = "testnet",
        max_leverage: int = 5,
        audit: ExecutionAuditLog | None = None,
    ) -> None:
        self._product: BinanceProduct = product
        self._network: BinanceNetwork = network
        self._max_leverage = max_leverage
        self._audit = audit or ExecutionAuditLog()

    # ── 内核按需实例化（key 只在此刻现身）──
    def _kernel(self, lease: Any) -> ExecutionVenue:
        if lease is None:
            raise PermissionError(_NO_LEASE)
        cred = BinanceCredentials.from_record(lease.record, self._network)  # lease.record = JIT key 记录
        client = BinanceClient(cred, product=self._product)
        if self._product == "usdm_futures":
            from .binance_um_futures import BinanceUMFuturesVenue
            return BinanceUMFuturesVenue(client, max_leverage=self._max_leverage, audit=self._audit)
        from .binance_spot import BinanceSpotVenue
        return BinanceSpotVenue(client, audit=self._audit)

    def _public_client(self) -> BinanceClient:
        # 公共端点无需 key：空 creds 仅用于拼 base_url。
        cred = BinanceCredentials(api_key="", api_secret="", network=self._network)
        return BinanceClient(cred, product=self._product)

    # ── 唯一 key 通道：place_order 必须带 lease ──
    def place_order(self, order: Order, *, lease: Any = None) -> OrderAck:
        return self._kernel(lease).place_order(order)

    def get_mark_price(self, symbol: str) -> float | None:
        """门前名义额核验用的【可信公共】mark（无需 key）；失败/无价 → None（门 fail-safe deny）。"""

        try:
            client = self._public_client()
            sym = symbol.upper()
            if self._product == "usdm_futures":
                data = client.public("GET", "/fapi/v1/premiumIndex", {"symbol": sym})
                mark = float((data or {}).get("markPrice", 0) or 0)
            else:
                data = client.public("GET", "/api/v3/ticker/price", {"symbol": sym})
                mark = float((data or {}).get("price", 0) or 0)
            return mark if mark > 0 else None
        except Exception:  # noqa: BLE001  公共取价失败不放行——交给门 deny-by-default
            return None

    # ── 其余私有端点同样只认 lease（不在 relay 热路径，但保持「无 lease 无 key」不变量）──
    def cancel_order(self, order_id: str, *, lease: Any = None) -> CancelAck:
        return self._kernel(lease).cancel_order(order_id)

    def get_position(self, symbol: str, *, lease: Any = None) -> Position:
        return self._kernel(lease).get_position(symbol)

    def get_balance(self, *, lease: Any = None) -> dict[str, Balance]:
        return self._kernel(lease).get_balance()


__all__ = ["LeasedBinanceVenue"]
