"""M9.1 · 执行抽象基类。

把"回测撮合"与"实盘下单"统一到同一份接口背后，让回测策略迁移到 paper / live
不用改业务代码。GOAL §M9.1 的伪代码在此具体化。
"""

from __future__ import annotations

import hashlib
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from ..lineage.ids import canonical_json


OrderSide = Literal["buy", "sell"]
OrderType = Literal[
    "market",
    "limit",
    "limit_maker",       # post-only
    "stop_loss",
    "stop_loss_limit",
    "take_profit",
    "take_profit_market",
    "take_profit_limit",
    "stop_market",
    "trailing_stop_market",
    "oco",
]
TimeInForce = Literal["GTC", "IOC", "FOK", "PO"]
OrderStatus = Literal["new", "partially_filled", "filled", "canceled", "rejected", "expired"]


def canonical_raw_event_hash(raw: dict[str, Any]) -> str:
    """Full SHA-256 digest of the exact canonical raw venue payload."""

    if not isinstance(raw, dict) or not raw:
        raise ValueError("raw venue payload must be a nonempty object")
    return "sha256:" + hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()


@dataclass
class Order:
    venue: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = "market"
    price: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    time_in_force: TimeInForce = "GTC"
    reduce_only: bool = False
    close_position: bool = False
    leverage: float | None = None
    client_order_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderAck:
    order_id: str
    client_order_id: str | None
    accepted_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: OrderStatus = "new"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CancelAck:
    order_id: str
    canceled_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    side: OrderSide | None = None

    @property
    def notional(self) -> float:
        return self.quantity * self.mark_price


@dataclass
class Balance:
    asset: str
    free: float
    locked: float = 0.0

    @property
    def total(self) -> float:
        return self.free + self.locked


@dataclass
class ExecutionReport:
    order_id: str
    symbol: str
    side: OrderSide
    filled_qty: float
    cumulative_filled_qty: float
    fill_price: float
    commission: float
    commission_asset: str
    status: OrderStatus
    # Some venues (notably Binance USD-M futures) report realized PnL per
    # trade.  Keep the value separate from commission and carry an explicit
    # completeness bit: zero is a valid realized-PnL value and must not be
    # confused with "the venue did not provide this field".
    realized_pnl_delta: float = 0.0
    realized_pnl_complete: bool = False
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)
    client_order_id: str | None = None
    source_event_ref: str = ""
    raw_event_hash: str = ""


@dataclass(frozen=True)
class OrderExecutionObservation:
    """Authoritative order-lifecycle snapshot, separate from economic fills."""

    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    requested_qty: float
    cumulative_filled_qty: float
    observed_at_utc: str
    source_event_ref: str
    raw_event_hash: str
    raw: dict[str, Any] = field(default_factory=dict)


class ExecutionVenue(ABC):
    """所有 venue (Backtest / Paper / Binance Spot / Binance Futures / DIY) 共用接口。"""

    name: str

    @abstractmethod
    def place_order(self, order: Order) -> OrderAck: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> CancelAck: ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position: ...

    @abstractmethod
    def get_balance(self) -> dict[str, Balance]: ...

    def list_open_positions(self) -> list[Position]:
        """Return executable open positions for emergency closure.

        Balance keys are not position symbols. Venues must implement this
        explicitly before they can participate in a close-position KillSwitch.
        """

        raise NotImplementedError(f"{self.name} does not implement emergency position discovery")

    def emergency_cancel_all(self) -> dict[str, Any]:
        """Cancel open orders and explicitly attest a verified no-op when none exist."""

        raise NotImplementedError(f"{self.name} does not implement emergency cancellation")

    def close_open_position(self, position: Position) -> dict[str, Any]:
        """Close one discovered position with a venue-native reduce-only action."""

        raise NotImplementedError(f"{self.name} does not implement emergency position closure")

    def verify_emergency_flat(self, *, close_positions: bool = True) -> dict[str, Any]:
        """Fresh proof after emergency actions.

        Implementations must cover every venue-native open-order family and,
        when ``close_positions`` is true, all executable positions.
        """

        raise NotImplementedError(f"{self.name} does not implement emergency flat verification")

    def stream_executions(self) -> AsyncIterator[ExecutionReport]:  # pragma: no cover - 默认未实现
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        """Return a venue-native, freshly observed health result.

        A generic success here would let a venue that never contacted its
        account or transport look connected.  Concrete venues must implement
        their own check before any caller can use it as connectivity evidence.
        """

        raise NotImplementedError(f"{self.name} does not implement a venue-native health check")


class ExecutionAuditLog:
    """所有 order/ack/execution 都过一遍审计日志，便于 §M9.3 复盘。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def log(self, kind: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(
                {"kind": kind, "logged_at_utc": datetime.now(UTC).isoformat(), "payload": payload}
            )

    def export(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


__all__ = [
    "Balance",
    "CancelAck",
    "ExecutionAuditLog",
    "ExecutionReport",
    "ExecutionVenue",
    "Order",
    "OrderAck",
    "OrderExecutionObservation",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "TimeInForce",
    "canonical_raw_event_hash",
]
