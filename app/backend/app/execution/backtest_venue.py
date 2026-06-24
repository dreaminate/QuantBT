"""M9.1 · 回测撮合 venue。

支持模式：
- `next_bar_open`：保守 / 默认，下单立刻被下一根 bar 的 open 价成交（无滑点扣减）
- `vwap`：用区间 VWAP 成交
- `limit_sim`：限价订单根据下一根 bar 的 high/low 是否触及来判定成交

三档成本模型预设由调用方传入（GOAL §M9.2）。
"""

from __future__ import annotations

import math
import uuid
import warnings
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
from .impact import IMPACT_DELTA, square_root_impact_fraction


MatchingMode = Literal["next_bar_open", "vwap", "limit_sim"]


@dataclass
class BacktestCostModel:
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    stamp_duty_bps: float = 0.0  # 仅 A股卖出
    transfer_fee_bps: float = 0.0
    funding_bps_per_8h: float = 0.0
    side_aware: bool = True
    # R18 平方根市场冲击（size-aware）：默认 0=关 → 冲击项恒 0、现有回测字节不变（向后兼容）。
    # 启用（>0）须 prices 含 volume 列估 ADV（否则 init raise，绝不静默当 0 冲击=假绿灯）。
    impact_coef: float = 0.0           # Y：冲击系数（无量纲，用户/校准提供）
    impact_delta: float = IMPACT_DELTA  # δ=0.5 锁定（R18 窄带；改离须显式）
    # **前视泄露处置（look-ahead 红线 · 用户拍板项 RULES §7）**：自估 ADV/σ 用**全样本**（含未来 bar），
    # 启用即 emit 响亮 warning（残余从文档升到代码可见、标清用户自负）。要无泄露：调用方传**点位无泄露**的
    # per-symbol ADV/σ（绕开自估、不触发 warning）。滚动无泄露自估属 P2（见 finding）。
    impact_adv: dict[str, float] | None = None      # 显式 per-symbol ADV（点位无泄露，用户提供）
    impact_sigma: dict[str, float] | None = None    # 显式 per-symbol σ（同上）


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
        # R18 平方根冲击：启用时预算 per-symbol ADV(均量) + σ(close 收益 std)。无 volume → raise（不假绿灯）。
        self._impact_adv: dict[str, float] = {}
        self._impact_sigma: dict[str, float] = {}
        if self._cost.impact_coef > 0.0:
            self._precompute_impact_stats()

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
            cost = self._cost_for_trade(side, qty, executed_price, booked.order.symbol)
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

    def _precompute_impact_stats(self) -> None:
        """启用平方根冲击时备 per-symbol ADV + σ。

        **优先用调用方显式传入的点位无泄露 ADV/σ**（绕开自估前视）；未传则**全样本自估**（ADV=均日量、
        σ=close 收益 std）并 emit **响亮 warning**（自估含前视、回测偏乐观、启用即用户自负——look-ahead
        红线的 §7 拍板项处置）。无 volume → raise（不假绿灯）。滚动无泄露自估属 P2（finding）。
        """
        if self._cost.impact_adv is not None:
            # 显式无泄露口径：用调用方提供的（点位无泄露是其数据管线责任，不触发自估前视 warning）。
            self._impact_adv = {str(k): float(v) for k, v in self._cost.impact_adv.items()}
            self._impact_sigma = {str(k): float(v) for k, v in (self._cost.impact_sigma or {}).items()}
            return
        warnings.warn(
            "BacktestCostModel.impact_coef>0 且未传显式 ADV/σ → 自估用**全样本**(含未来 bar)估 ADV/σ，"
            "构成**前视泄露**：启用 impact 的回测成本偏乐观（早期成交参与率被未来流动性稀释）。"
            "active/默认路径(impact_coef=0)不受影响。要无泄露请传 BacktestCostModel.impact_adv/impact_sigma"
            "(点位口径)。启用自估=用户选择/自负。滚动无泄露自估见 P2 卡。",
            stacklevel=2,
        )
        if "volume" not in self._prices.columns:
            raise ValueError(
                "BacktestCostModel.impact_coef>0（平方根市场冲击）需 prices 含 'volume' 列估 ADV——"
                "缺则无法估冲击，绝不静默当 0 冲击（不假绿灯）。请补 volume 或关闭 impact_coef。"
            )
        # ts 为 datetime → 先按**日**聚合 volume（日内 1m/1h 数据 vol.mean 是每 bar 量、非日 ADV，
        # 会把参与率抬高 √(bars/日)、高估冲击）；int ts → 退化为每期量（中低频日频假设，见 finding 残余）。
        ts_temporal = bool(self._prices.schema["ts"].is_temporal())
        for sym, sub in self._prices.group_by("symbol"):
            symbol = str(sym[0] if isinstance(sym, tuple) else sym)
            if ts_temporal:
                daily_vol = sub.group_by(pl.col("ts").dt.date()).agg(pl.col("volume").sum()).get_column("volume").drop_nulls()
                adv = float(daily_vol.mean()) if daily_vol.len() > 0 else 0.0
            else:
                vol = sub.get_column("volume").drop_nulls()
                adv = float(vol.mean()) if vol.len() > 0 else 0.0
            closes = sub.sort("ts").get_column("close").drop_nulls()
            if closes.len() >= 3:
                rets = closes.pct_change().drop_nulls()
                sigma = float(rets.std(ddof=1)) if rets.len() >= 2 else 0.0
            else:
                sigma = 0.0
            self._impact_adv[symbol] = adv if math.isfinite(adv) else 0.0
            self._impact_sigma[symbol] = sigma if math.isfinite(sigma) else 0.0

    def _cost_for_trade(self, side: OrderSide, qty: float, price: float, symbol: str | None = None) -> float:
        notional = qty * price
        commission = notional * self._cost.commission_bps * 1e-4
        slippage = notional * self._cost.slippage_bps * 1e-4
        stamp = notional * self._cost.stamp_duty_bps * 1e-4 if side == "sell" else 0.0
        transfer = notional * self._cost.transfer_fee_bps * 1e-4
        impact = 0.0
        if self._cost.impact_coef > 0.0 and symbol is not None:
            adv = self._impact_adv.get(symbol, 0.0)
            sigma = self._impact_sigma.get(symbol, 0.0)
            # **不假绿灯·fail-fast**：冲击启用却对要成交的 symbol 估不出有效 ADV（volume 全 0/null/NaN）
            # → raise，绝不静默当 0 冲击让回测只剩平成本（那正是本选项要防的假绿灯）。
            if not (math.isfinite(adv) and adv > 0.0):
                raise ValueError(
                    f"symbol={symbol} ADV={adv} 无效（volume 全 0/null/NaN）——平方根冲击启用却无法估，"
                    "绝不静默当 0 冲击（不假绿灯）。请补该 symbol 有效 volume 或关闭 impact_coef。"
                )
            participation = qty / adv   # 本笔成交量 / 日均成交量(ADV)
            impact = notional * square_root_impact_fraction(
                participation, sigma, self._cost.impact_coef, self._cost.impact_delta
            )
        return commission + slippage + stamp + transfer + impact


__all__ = ["BacktestCostModel", "BacktestVenue", "MatchingMode"]
