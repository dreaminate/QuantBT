"""M9.1 · 执行抽象基类。

把"回测撮合"与"实盘下单"统一到同一份接口背后，让回测策略迁移到 paper / live
不用改业务代码。GOAL §M9.1 的伪代码在此具体化。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


OrderSide = Literal["buy", "sell"]
OrderType = Literal[
    "market",
    "limit",
    "limit_maker",       # post-only
    "stop_loss",
    "stop_loss_limit",
    "take_profit",
    "take_profit_limit",
    "stop_market",
    "trailing_stop_market",
    "oco",
]
TimeInForce = Literal["GTC", "IOC", "FOK", "PO"]
OrderStatus = Literal["new", "partially_filled", "filled", "canceled", "rejected", "expired"]


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
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
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

    def stream_executions(self) -> AsyncIterator[ExecutionReport]:  # pragma: no cover - 默认未实现
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        return {"venue": self.name, "ok": True, "checked_at_utc": datetime.now(UTC).isoformat()}


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
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "TimeInForce",
]
