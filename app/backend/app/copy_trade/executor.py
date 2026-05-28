"""Signal relayer：master 发单 → 给所有 active follower 跑 risk check 再下到自己的 BinanceVenue。

设计要点 (GOAL §M9.3 重申)：
- 每个 follower 走**自己的** keystore + 自己的 BinanceVenue（master 永远拿不到 follower key）
- 下单前必走 RiskMonitor.pre_trade（单笔上限 / 黑名单 / 肥手指 / 日内笔数 / 日内亏损）
- 任何失败 → record execution `rejected/failed` + audit log；继续 relay 给其他 follower
- 不联实盘的环境 (no keystore key)：fallback skip 但仍记录 execution 为 'skipped'，UI 可见

执行流程：
1. master 发 signal → `relay_signal(signal_id)` 触发
2. 取该 master 所有 active follower
3. 每个 follower:
   a. 拿 follower.binance_keystore_name 从 SecureKeystore 取 key (无 key → skip)
   b. 构造 BinanceCredentials → BinanceClient → BinanceVenue (sp ot/futures 看 asset_class)
   c. RiskMonitor.pre_trade(order) — 校验单笔 / 日内笔数
   d. venue.place_order(order)
   e. record_execution(filled / placed / rejected / failed)
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ..execution.base import ExecutionVenue, Order
from ..risk import RiskLimits, RiskMonitor
from ..security.keystore import KeystoreError, SecureKeystore
from .service import CopyTradeService, Follower, Signal


logger = logging.getLogger(__name__)


class VenueFactory(Protocol):
    """构造 follower 自己的 BinanceVenue。注入式，方便测试 mock。"""

    def __call__(self, follower: Follower, keystore: SecureKeystore) -> ExecutionVenue | None: ...


class SignalRelayer:
    """无状态：每次 relay 调一次 venue_factory + risk monitor。"""

    def __init__(
        self,
        copy_trade: CopyTradeService,
        keystore: SecureKeystore,
        venue_factory: VenueFactory,
    ) -> None:
        self._ct = copy_trade
        self._keystore = keystore
        self._make_venue = venue_factory

    def relay(self, signal: Signal) -> list[dict[str, Any]]:
        """relay 单个 signal 到所有 active follower。返回每个 follower 的执行结果摘要。"""

        results: list[dict[str, Any]] = []
        followers = self._ct.list_followers(signal.master_id, active_only=True)
        for f in followers:
            try:
                result = self._relay_to_one(signal, f)
            except Exception as exc:  # noqa: BLE001
                logger.exception("relay 失败 follower=%s", f.follower_id)
                self._ct.record_execution(
                    signal.signal_id, f.follower_id, "failed", error=f"{type(exc).__name__}: {exc}",
                )
                result = {"follower_id": f.follower_id, "status": "failed", "error": str(exc)}
            results.append(result)
        return results

    def _relay_to_one(self, signal: Signal, f: Follower) -> dict[str, Any]:
        # 1. follower 没填 keystore 名字 → skip
        if not f.binance_keystore_name:
            self._ct.record_execution(signal.signal_id, f.follower_id, "skipped", error="no keystore configured")
            return {"follower_id": f.follower_id, "status": "skipped", "reason": "no_keystore"}

        # 2. 取 follower 自己的 key（master 永远拿不到）
        try:
            self._keystore.fetch(f.binance_keystore_name)
        except KeystoreError as exc:
            self._ct.record_execution(signal.signal_id, f.follower_id, "skipped", error=f"keystore miss: {exc}")
            return {"follower_id": f.follower_id, "status": "skipped", "reason": "keystore_miss"}

        # 3. 构造 follower 的 venue（mock 时由 venue_factory 注入）
        venue = self._make_venue(f, self._keystore)
        if venue is None:
            self._ct.record_execution(signal.signal_id, f.follower_id, "skipped", error="venue unavailable")
            return {"follower_id": f.follower_id, "status": "skipped", "reason": "venue_unavailable"}

        # 4. 根据 follower 风控构造 RiskMonitor，pre_trade 校验
        limits = RiskLimits(
            per_order_max_usdt=f.per_order_max_usdt,
            daily_loss_limit_pct=f.daily_loss_limit_pct,
        )
        rm = RiskMonitor(limits)
        order = Order(
            venue=getattr(venue, "name", "binance"),
            symbol=signal.symbol,
            side=signal.side,
            quantity=signal.quantity,
            order_type=signal.order_type,
            price=signal.price,
        )
        try:
            rm.pre_trade(order, mark_price=signal.price)
        except Exception as exc:  # noqa: BLE001
            self._ct.record_execution(
                signal.signal_id, f.follower_id, "rejected", error=f"risk: {exc}",
            )
            return {"follower_id": f.follower_id, "status": "rejected", "reason": str(exc)}

        # 5. 真下单
        try:
            ack = venue.place_order(order)
        except Exception as exc:  # noqa: BLE001
            self._ct.record_execution(signal.signal_id, f.follower_id, "failed", error=str(exc))
            return {"follower_id": f.follower_id, "status": "failed", "reason": str(exc)}

        status = "placed"
        if (ack.status or "").lower() == "filled":
            status = "filled"
        self._ct.record_execution(
            signal.signal_id, f.follower_id, status,  # type: ignore[arg-type]
            venue_order_id=ack.order_id,
        )
        return {
            "follower_id": f.follower_id,
            "status": status,
            "venue_order_id": ack.order_id,
        }


__all__ = ["SignalRelayer", "VenueFactory"]
