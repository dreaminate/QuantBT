"""M9.1 · 回测撮合 venue。

支持模式：
- `next_bar_open`：保守 / 默认，下单立刻被下一根 bar 的 open 价成交（无滑点扣减）
- `vwap`：用区间 VWAP 成交
- `limit_sim`：限价订单根据下一根 bar 的 high/low 是否触及来判定成交

三档成本模型预设由调用方传入（GOAL §M9.2）。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import polars as pl

from .base import (
    Balance,
    CancelAck,
    ExecutionAuditLog,
    ExecutionVenue,
    Order,
    OrderAck,
    OrderSide,
    OrderStatus,
    Position,
)


MatchingMode = Literal["next_bar_open", "vwap", "limit_sim"]


@dataclass
class BacktestCostModel:
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    stamp_duty_bps: float = 0.0  # 仅 A股卖出
    transfer_fee_bps: float = 0.0
    funding_bps_per_8h: float = 0.0
    side_aware: bool = True


@dataclass
class _BookedOrder:
    order: Order
    accepted_at_idx: int
    status: OrderStatus = "new"
    filled_qty: float = 0.0
    average_price: float = 0.0


class BacktestVenue(ExecutionVenue):
    """事件驱动 + 向量化两栖：策略调 place_order 后由 driver 调用 `step()` 触发撮合。"""

    name = "backtest"

    def __init__(
        self,
        prices: pl.DataFrame,
        cost_model: BacktestCostModel | None = None,
        matching: MatchingMode = "next_bar_open",
        cash: float = 1_000_000.0,
        audit: ExecutionAuditLog | None = None,
        required_fields: set[str] | None = None,
    ) -> None:
        # 数据平台 v2：默认仍要 OHLCV（向后兼容），但可由调用方按 FieldRequirement 配置所需字段。
        # 不在 venue 内反向依赖 FieldCatalog —— prices 由上游(load_panel 等)组装好后传入。
        needed = required_fields or {"ts", "symbol", "open", "high", "low", "close"}
        missing = sorted(needed - set(prices.columns))
        if missing:
            raise ValueError(f"prices 缺少必需字段: {missing}（需 {sorted(needed)}）")
        self._prices = prices.sort(["ts", "symbol"])
        self._cost = cost_model or BacktestCostModel()
        self._mode: MatchingMode = matching
        self._cash = cash
        self._positions: dict[str, Position] = {}
        self._open_orders: dict[str, _BookedOrder] = {}
        self._timestamps: list = list(self._prices.get_column("ts").unique().to_list())
        self._cursor: int = 0
        self._audit = audit or ExecutionAuditLog()

    @property
    def audit(self) -> ExecutionAuditLog:
        return self._audit

    def place_order(self, order: Order) -> OrderAck:
        oid = str(uuid.uuid4())
        booked = _BookedOrder(order=order, accepted_at_idx=self._cursor)
        self._open_orders[oid] = booked
        ack = OrderAck(order_id=oid, client_order_id=order.client_order_id, status="new")
        self._audit.log("place", {"order_id": oid, "order": order.to_dict()})
        return ack

    def cancel_order(self, order_id: str) -> CancelAck:
        booked = self._open_orders.pop(order_id, None)
        if booked is not None:
            booked.status = "canceled"
        self._audit.log("cancel", {"order_id": order_id})
        return CancelAck(order_id=order_id)

    def get_position(self, symbol: str) -> Position:
        return self._positions.get(symbol, Position(symbol=symbol, quantity=0.0))

    def get_balance(self) -> dict[str, Balance]:
        return {"USDT": Balance(asset="USDT", free=self._cash)}

    def step(self) -> list[dict]:
        """让一个 bar 过去；尝试撮合所有 open orders。返回本步成交报告。"""

        if self._cursor + 1 >= len(self._timestamps):
            return []
        next_ts = self._timestamps[self._cursor + 1]
        snapshot = self._prices.filter(pl.col("ts") == next_ts)
        index = {row["symbol"]: row for row in snapshot.to_dicts()}
        reports: list[dict] = []
        for oid, booked in list(self._open_orders.items()):
            bar = index.get(booked.order.symbol)
            if bar is None:
                continue
            executed_price = self._match(booked.order, bar)
            if executed_price is None:
                continue
            qty = booked.order.quantity
            side: OrderSide = booked.order.side
            cost = self._cost_for_trade(side, qty, executed_price)
            signed_qty = qty if side == "buy" else -qty
            self._cash -= signed_qty * executed_price + cost
            pos = self._positions.get(booked.order.symbol) or Position(symbol=booked.order.symbol, quantity=0.0)
            new_qty = pos.quantity + signed_qty
            if new_qty == 0:
                self._positions.pop(booked.order.symbol, None)
            else:
                avg = (pos.entry_price * pos.quantity + signed_qty * executed_price) / new_qty if new_qty else 0
                self._positions[booked.order.symbol] = Position(
                    symbol=booked.order.symbol,
                    quantity=new_qty,
                    entry_price=avg,
                    mark_price=executed_price,
                )
            booked.status = "filled"
            booked.filled_qty = qty
            booked.average_price = executed_price
            reports.append(
                {
                    "order_id": oid,
                    "symbol": booked.order.symbol,
                    "side": side,
                    "filled_qty": qty,
                    "fill_price": executed_price,
                    "commission": cost,
                    "status": booked.status,
                    "ts": next_ts,
                }
            )
            self._audit.log("fill", reports[-1])
            del self._open_orders[oid]
        self._cursor += 1
        return reports

    def replay(self) -> Iterable[dict]:
        while self._cursor + 1 < len(self._timestamps):
            yield from self.step()

    def _match(self, order: Order, bar: dict) -> float | None:
        if order.order_type == "market":
            return float(bar["open"])
        if order.order_type in {"limit", "limit_maker"} and order.price is not None:
            if order.side == "buy" and float(bar["low"]) <= order.price:
                return order.price
            if order.side == "sell" and float(bar["high"]) >= order.price:
                return order.price
            return None
        if order.order_type in {"stop_market", "stop_loss", "take_profit"} and order.stop_price is not None:
            if order.side == "buy" and float(bar["high"]) >= order.stop_price:
                return float(bar["open"])
            if order.side == "sell" and float(bar["low"]) <= order.stop_price:
                return float(bar["open"])
            return None
        if order.order_type == "next_bar_open":  # type: ignore[comparison-overlap]
            return float(bar["open"])
        # 默认按下一 bar open 兜底
        return float(bar["open"])

    def _cost_for_trade(self, side: OrderSide, qty: float, price: float) -> float:
        notional = qty * price
        commission = notional * self._cost.commission_bps * 1e-4
        slippage = notional * self._cost.slippage_bps * 1e-4
        stamp = notional * self._cost.stamp_duty_bps * 1e-4 if side == "sell" else 0.0
        transfer = notional * self._cost.transfer_fee_bps * 1e-4
        return commission + slippage + stamp + transfer


__all__ = ["BacktestCostModel", "BacktestVenue", "MatchingMode"]
