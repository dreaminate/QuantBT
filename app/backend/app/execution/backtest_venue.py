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
from typing import Any, Literal

import numpy as np
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
        # `_impact_adv/_impact_sigma`=终端标量（显式口径=所传值；自估=全样本，仅作 ts=None 回退）；
        # `_impact_asof`=扩张窗 as-of 映射 {symbol: {ts: (adv_{t⁻}, σ_{t⁻})}}（replay 每笔成交无泄露查找）。
        self._impact_adv: dict[str, float] = {}
        self._impact_sigma: dict[str, float] = {}
        self._impact_asof: dict[str, dict[Any, tuple[float, float]]] = {}
        self._impact_mode: str | None = None              # "explicit" | "expanding" | None
        self._impact_warmup_fills: int = 0                # 计数：warmup 期不计冲击的成交（诚实披露）
        self._impact_warmup_warned: bool = False
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
            # 传 next_ts → 冲击走扩张窗 as-of（仅用 <next_ts 的流动性/σ，无前视泄露）。逐成分一次算（避免
            # 重算令 warmup 计数器双增）；cost=total，breakdown 附进报告供下游真归因（impact 不混入 commission）。
            breakdown = self._cost_breakdown(side, qty, executed_price, booked.order.symbol, ts=next_ts)
            cost = breakdown["total"]
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
                    "commission": cost,            # 向后兼容=total（含 impact）；逐成分见 cost_breakdown
                    "cost_breakdown": breakdown,    # 诚实归因：commission/slippage/stamp_duty/transfer/impact/total
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

        **优先用调用方显式传入的点位无泄露 ADV/σ**（绕开自估）；未传则自估改用**扩张窗 as-of**
        （仅用成交前历史 `F_{t⁻}` 估 ADV/σ，**无前视泄露**——见 finding「扩张窗 as-of 无泄露自估」推导）：
        终端全样本标量仅作 ts=None 回退，replay 每笔成交走 `_impact_asof[symbol][ts]`。无 volume → raise
        （不假绿灯）。自估 emit informational warning（早期估计噪声 + warmup 不计冲击已披露 = 用户自负）。
        """
        if self._cost.impact_adv is not None:
            # 显式无泄露口径：用调用方提供的（点位无泄露是其数据管线责任，不触发自估 warning）。
            self._impact_mode = "explicit"
            self._impact_adv = {str(k): float(v) for k, v in self._cost.impact_adv.items()}
            self._impact_sigma = {str(k): float(v) for k, v in (self._cost.impact_sigma or {}).items()}
            return
        self._impact_mode = "expanding"
        warnings.warn(
            "BacktestCostModel.impact_coef>0 且未传显式 ADV/σ → 自估改用**扩张窗 as-of**（仅用成交前历史 "
            "F_{t⁻} 估 ADV/σ），**无前视泄露**（早期成交不再被未来流动性稀释、追加未来 bar 不改早期冲击）。"
            "代价：① 早期估计样本少、噪声大；② warmup（prior 历史不足）的成交不计冲击、已计数披露"
            "（venue._impact_warmup_fills）。要稳态点位口径请传 BacktestCostModel.impact_adv/impact_sigma。",
            stacklevel=2,
        )
        if "volume" not in self._prices.columns:
            raise ValueError(
                "BacktestCostModel.impact_coef>0（平方根市场冲击）需 prices 含 'volume' 列估 ADV——"
                "缺则无法估冲击，绝不静默当 0 冲击（不假绿灯）。请补 volume 或关闭 impact_coef。"
            )
        # ts 为 datetime → 按**日**聚合 volume（日内 1m/1h 的 vol.mean 是每 bar 量、非日 ADV，
        # 会把参与率抬高 √(bars/日)、高估冲击）；int ts → 退化为每期量（中低频日频假设）。
        ts_temporal = bool(self._prices.schema["ts"].is_temporal())
        for sym, sub in self._prices.group_by("symbol"):
            symbol = str(sym[0] if isinstance(sym, tuple) else sym)
            sub = sub.sort("ts")
            vol_all = sub.get_column("volume").drop_nulls()
            # —— 终端全样本标量（ts=None 回退；序列末无未来 ⇒ 非泄露）——
            if ts_temporal:
                daily_vol = sub.group_by(pl.col("ts").dt.date()).agg(pl.col("volume").sum()).get_column("volume").drop_nulls()
                adv = float(daily_vol.mean()) if daily_vol.len() > 0 else 0.0
            else:
                adv = float(vol_all.mean()) if vol_all.len() > 0 else 0.0
            closes_nn = sub.get_column("close").drop_nulls()
            if closes_nn.len() >= 3:
                rets_nn = closes_nn.pct_change().drop_nulls()
                sigma = float(rets_nn.std(ddof=1)) if rets_nn.len() >= 2 else 0.0
            else:
                sigma = 0.0
            self._impact_adv[symbol] = adv if math.isfinite(adv) else 0.0
            self._impact_sigma[symbol] = sigma if math.isfinite(sigma) else 0.0
            # —— 扩张窗 as-of 映射（每 bar 仅用 F_{t⁻}）——
            self._impact_asof[symbol] = self._build_asof_impact(sub, ts_temporal)

    @staticmethod
    def _build_asof_impact(sub: "pl.DataFrame", ts_temporal: bool) -> dict[Any, tuple[float, float]]:
        """per-symbol 扩张窗 as-of：bar t 的 (ADV_{t⁻}, σ_{t⁻}) 仅用严格早于 t 的数据。

        ADV：datetime 按**日**聚合后取「严格早于当日的已完成日」均量（当日不计入）；int ts 取「早于本 bar
        的各期」均量。σ：取「于 <t 实现」的 close 收益样本 std（ddof=1，bar t 只用 r_1..r_{t-1}）。
        prior 不足（首日 / <2 收益）→ NaN（warmup，由 `_cost_for_trade` 计数不计冲击）。
        """
        ts_list = sub.get_column("ts").to_list()
        close = np.asarray(sub.get_column("close").to_list(), dtype=float)
        vol = np.asarray(sub.get_column("volume").to_list(), dtype=float)
        L = len(ts_list)
        # —— prior ADV per bar ——
        adv_bar = np.full(L, np.nan)
        if ts_temporal:
            dates = [t.date() if hasattr(t, "date") else t for t in ts_list]
            daily: dict[Any, float] = {}
            for d, v in zip(dates, vol):
                daily[d] = daily.get(d, 0.0) + (float(v) if math.isfinite(v) else 0.0)
            date_order = list(daily.keys())                       # ts 已排序 ⇒ 日有序
            daily_vals = np.array([daily[d] for d in date_order], dtype=float)
            csum = np.concatenate([[0.0], np.cumsum(daily_vals)])
            prior_adv_for_date = {date_order[k]: (csum[k] / k if k > 0 else np.nan) for k in range(len(date_order))}
            adv_bar = np.array([prior_adv_for_date[d] for d in dates], dtype=float)
        else:
            vfin = np.where(np.isfinite(vol), vol, 0.0)
            csum = np.concatenate([[0.0], np.cumsum(vfin)])       # csum[j]=sum(vol[:j])
            for j in range(1, L):
                adv_bar[j] = csum[j] / j                          # 早于本 bar 的各期均量
        # —— prior σ per bar（扩张窗 std, ddof=1, 仅用 <t 实现的收益）——
        rets = np.full(L, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            rets[1:] = close[1:] / close[:-1] - 1.0               # rets[i] 于 bar i 收盘实现
        fin = np.isfinite(rets)
        r0 = np.where(fin, rets, 0.0)
        cnt = np.cumsum(fin.astype(float))                        # cnt[k]=#finite in rets[0..k]
        s1, s2 = np.cumsum(r0), np.cumsum(r0 * r0)
        sigma_bar = np.full(L, np.nan)
        for j in range(L):
            p = j - 1                                             # bar j 仅用 rets[0..j-1]
            if p < 0:
                continue
            c = cnt[p]
            if c >= 2:
                var = (s2[p] - s1[p] * s1[p] / c) / (c - 1)
                sigma_bar[j] = math.sqrt(var) if var > 0 else 0.0
        return {ts_list[j]: (float(adv_bar[j]), float(sigma_bar[j])) for j in range(L)}

    def _impact_inputs(self, symbol: str, ts: Any) -> tuple[float, float, bool]:
        """解析本笔成交的 (ADV, σ, is_warmup)。**warmup 判定纯由 F_{t⁻} prefix 驱动、绝不看全样本/未来**
        （否则早期成交的 skip/charge 裁决会依赖 ≥t 数据 = 前视泄露，评审 PROBE H）。

        - explicit → 调用方点位标量（其无泄露责任）。
        - expanding + 指定 ts：仅用该 ts 的 as-of（F_{t⁻}）；估不出（NaN/ADV≤0 或 σ=NaN）→ warmup
          （不看未来、不静默 0）。**ts 不在 as-of map（无 F_{t⁻} 估计）→ 也走 warmup，绝不回退到泄露的
          终端全样本标量**。
        - ts=None（无时间上下文，汇总/直接调用）→ 终端全样本标量（序列末无未来 ⇒ 非泄露）；其 ADV≤0
          的 fail-fast 在 `_cost_for_trade` 下游（保「启用却全样本无量」的不假绿灯硬停）。
        """
        if self._impact_mode == "explicit":
            return self._impact_adv.get(symbol, 0.0), self._impact_sigma.get(symbol, 0.0), False
        if ts is None:
            return self._impact_adv.get(symbol, 0.0), self._impact_sigma.get(symbol, 0.0), False
        asof = self._impact_asof.get(symbol, {})
        if ts not in asof:
            # 该 ts 无 F_{t⁻} 估计 → warmup-披露（绝不静默用全样本终端值=泄露）
            return float("nan"), float("nan"), True
        adv, sigma = asof[ts]
        # ADV 或 σ 任一不可从 F_{t⁻} 估出（NaN / ADV≤0 / σ=NaN）即 warmup——σ=0.0 有限=退化无波动、
        # 合法 0 冲击，与「估不出」区分；绝不悄悄按 σ=0 偷算 0 冲击。
        if math.isfinite(adv) and adv > 0.0 and math.isfinite(sigma):
            return adv, sigma, False
        return adv, sigma, True

    def _note_impact_warmup(self) -> None:
        """warmup 期成交不计冲击的诚实披露：计数 + 一次性 warning（绝不偷看未来补估、绝不静默假装 0）。"""
        self._impact_warmup_fills += 1
        if not self._impact_warmup_warned:
            self._impact_warmup_warned = True
            warnings.warn(
                "平方根冲击扩张窗自估：部分早期成交处于 warmup（prior 流动性/σ 历史不足）→ 该笔**不计冲击**"
                "（绝不偷看未来 bar 补估、绝不静默假装 0 成本）。这些笔冲击成本被低估、已计数"
                "（venue._impact_warmup_fills）。要全程计冲击请传显式点位 ADV/σ 或预热足够历史。",
                stacklevel=3,
            )

    def _cost_breakdown(self, side: OrderSide, qty: float, price: float, symbol: str | None = None,
                        ts: Any = None) -> dict[str, float]:
        """逐成分成本（诚实归因·不假绿灯）：`commission`/`slippage`/`stamp_duty`/`transfer`/`impact` + `total`。

        **impact 单列、绝不并入 commission**——下游可真做成本归因/TCA（市场冲击不会被误读成手续费）。
        fill 报告的 `commission` 顶层字段保留=`total`（含 impact）仅向后兼容旧消费者（cost_drift 取总实现成本）；
        要逐成分一律读 `cost_breakdown`。各成分非负、求和==total（测试守恒）。
        """
        notional = qty * price
        commission = notional * self._cost.commission_bps * 1e-4
        slippage = notional * self._cost.slippage_bps * 1e-4
        stamp = notional * self._cost.stamp_duty_bps * 1e-4 if side == "sell" else 0.0
        transfer = notional * self._cost.transfer_fee_bps * 1e-4
        impact = 0.0
        if self._cost.impact_coef > 0.0 and symbol is not None:
            # 扩张窗 as-of：本笔成交 ts 处仅用 F_{t⁻} 的 ADV/σ（无前视）；ts=None→终端标量回退。
            adv, sigma, is_warmup = self._impact_inputs(symbol, ts)
            if is_warmup:
                # warmup：prior 历史不足、无 leak-free 估计 → 本笔不计冲击（计数+披露，绝不偷看未来补）。
                self._note_impact_warmup()
            else:
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
        return {"commission": commission, "slippage": slippage, "stamp_duty": stamp,
                "transfer": transfer, "impact": impact,
                "total": commission + slippage + stamp + transfer + impact}

    def _cost_for_trade(self, side: OrderSide, qty: float, price: float, symbol: str | None = None,
                        ts: Any = None) -> float:
        """本笔成交总成本（=逐成分 total，向后兼容标量入口）。逐成分见 `_cost_breakdown`。"""
        return self._cost_breakdown(side, qty, price, symbol, ts)["total"]


__all__ = ["BacktestCostModel", "BacktestVenue", "MatchingMode"]
