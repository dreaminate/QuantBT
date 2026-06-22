"""M9.1 · Paper venue（A股 + 加密通用）。

跟 BacktestVenue 一样的撮合逻辑，但用真实"当前 bar"（外部喂入）而不是预先 batch。
也就是说：策略每 N 秒收到一根 bar，喂给 paper venue，paper venue 撮合开 orders。

A股 paper trading 唯一与回测的差异：每日 mark-to-market 后将权益快照写到本地 SQLite
或 JSONL，供前端"PAPER"标签展示。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from .backtest_venue import BacktestCostModel
from .base import (
    Balance,
    CancelAck,
    ExecutionAuditLog,
    ExecutionVenue,
    Order,
    OrderAck,
    Position,
)


@dataclass
class PaperEquitySnapshot:
    taken_at_utc: str
    cash: float
    positions_value: float
    total_equity: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaperVenue(ExecutionVenue):
    name = "paper"

    def __init__(
        self,
        cash: float = 1_000_000.0,
        cost_model: BacktestCostModel | None = None,
        equity_log_path: Path | None = None,
        audit: ExecutionAuditLog | None = None,
    ) -> None:
        self._cash = cash
        self._cost = cost_model or BacktestCostModel()
        self._positions: dict[str, Position] = {}
        self._open_orders: dict[str, Order] = {}
        self._equity_log = equity_log_path
        self._audit = audit or ExecutionAuditLog()

    @property
    def audit(self) -> ExecutionAuditLog:
        return self._audit

    def place_order(self, order: Order) -> OrderAck:
        oid = str(uuid.uuid4())
        self._open_orders[oid] = order
        self._audit.log("paper_place", {"order_id": oid, "order": order.to_dict()})
        return OrderAck(order_id=oid, client_order_id=order.client_order_id, status="new")

    def cancel_order(self, order_id: str) -> CancelAck:
        self._open_orders.pop(order_id, None)
        self._audit.log("paper_cancel", {"order_id": order_id})
        return CancelAck(order_id=order_id)

    def get_position(self, symbol: str) -> Position:
        return self._positions.get(symbol, Position(symbol=symbol, quantity=0.0))

    def get_balance(self) -> dict[str, Balance]:
        return {"CASH": Balance(asset="CASH", free=self._cash)}

    def reset_simulation_state(self, cash: float) -> None:
        """【模拟】回放重置：清持仓/挂单、复位现金、清空 equity_log 文件。

        仅供模拟台回放幂等重跑（prime_run）——把 venue 复位到「刚注册」态，使重复 prime 产同一序列。
        非下单路径、无 live 语义。审计 log 保留（append-only 不抹），只重置可计算的模拟态。
        """

        self._cash = cash
        self._positions.clear()
        self._open_orders.clear()
        if self._equity_log and self._equity_log.exists():
            self._equity_log.write_text("", encoding="utf-8")  # 清空旧净值，避免跨次/跨重启串行拼接
        self._audit.log("paper_sim_reset", {"cash": cash, "simulated": True})

    def seed_position(self, symbol: str, quantity: float, entry_price: float) -> None:
        """【模拟】直接建仓种子：为 paper 回放注入初始持仓，扣减对应现金。

        ⚠️ 这是模拟台回放的建仓引子，**非下单路径**（绝不经 OrderGuard/券商，也无 live 语义）——
        故意不走 place_order：① 这是合成持仓引子非真实订单意图；② 避免污染绕门审计（place_order
        调用点白名单是治理不变量，模拟引子不应进白名单）。后续 mark_to_market 即反映此持仓盈亏。
        """

        if quantity == 0:
            return
        self._cash -= quantity * entry_price
        self._positions[symbol] = Position(
            symbol=symbol, quantity=quantity, entry_price=entry_price, mark_price=entry_price
        )
        self._audit.log("paper_seed_position", {
            "symbol": symbol, "quantity": quantity, "entry_price": entry_price,
            "simulated": True, "note": "回放建仓引子（非下单、非 live）",
        })

    def feed_bar(self, bar: dict) -> list[dict]:
        """喂一根 bar，撮合 open_orders。bar 至少含 symbol/open/high/low/close/ts。"""

        if not {"symbol", "open", "high", "low", "close"}.issubset(bar):
            raise ValueError("bar 字段不全")
        reports: list[dict] = []
        for oid, order in list(self._open_orders.items()):
            if order.symbol != bar["symbol"]:
                continue
            executed = self._match(order, bar)
            if executed is None:
                continue
            qty = order.quantity
            notional = qty * executed
            cost = notional * (self._cost.commission_bps + self._cost.slippage_bps) * 1e-4
            signed = qty if order.side == "buy" else -qty
            self._cash -= signed * executed + cost
            pos = self._positions.get(order.symbol) or Position(symbol=order.symbol, quantity=0.0)
            new_qty = pos.quantity + signed
            if new_qty == 0:
                self._positions.pop(order.symbol, None)
            else:
                avg = (pos.entry_price * pos.quantity + signed * executed) / new_qty
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=new_qty,
                    entry_price=avg,
                    mark_price=executed,
                )
            reports.append(
                {
                    "order_id": oid,
                    "symbol": order.symbol,
                    "side": order.side,
                    "filled_qty": qty,
                    "fill_price": executed,
                    "commission": cost,
                    "status": "filled",
                    "ts": bar.get("ts"),
                }
            )
            self._audit.log("paper_fill", reports[-1])
            del self._open_orders[oid]
        return reports

    def mark_to_market(self, marks: dict[str, float]) -> PaperEquitySnapshot:
        positions_value = 0.0
        for sym, pos in self._positions.items():
            mark = marks.get(sym, pos.mark_price)
            self._positions[sym] = Position(
                symbol=sym, quantity=pos.quantity, entry_price=pos.entry_price, mark_price=mark
            )
            positions_value += pos.quantity * mark
        snap = PaperEquitySnapshot(
            taken_at_utc=datetime.now(UTC).isoformat(),
            cash=self._cash,
            positions_value=positions_value,
            total_equity=self._cash + positions_value,
        )
        if self._equity_log:
            self._equity_log.parent.mkdir(parents=True, exist_ok=True)
            with self._equity_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(snap.to_dict(), ensure_ascii=False) + "\n")
        return snap

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
        return float(bar["open"])


__all__ = ["PaperEquitySnapshot", "PaperVenue"]
