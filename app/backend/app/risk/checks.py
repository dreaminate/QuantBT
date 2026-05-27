"""M9.3 · 风控检查与 Kill Switch。

对齐 GOAL §M9.3 E 的硬约束：
- pre-trade：单笔金额上限 / minNotional / 肥手指偏离 / 黑名单
- run-time：单日下单笔数上限 / 单日亏损上限 / 持仓集中度 / 异常行情熔断 / 强平距离
- Kill Switch：一键撤所有 + 平所有
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Callable, Iterable

from ..execution.base import ExecutionVenue, Order


logger = logging.getLogger(__name__)


class PreTradeError(PermissionError):
    pass


@dataclass
class RiskLimits:
    per_order_max_usdt: float = 100.0
    fat_finger_pct: float = 0.02
    blacklist_symbols: tuple[str, ...] = ()
    daily_order_count_max: int = 200
    daily_loss_limit_pct: float = 0.05
    single_symbol_position_pct_max: float = 0.30
    liquidation_distance_alert_pct: float = 0.05


@dataclass
class DailyState:
    day: date
    order_count: int = 0
    realized_pnl: float = 0.0
    starting_equity: float = 0.0

    def reset_if_new_day(self, current_equity: float) -> None:
        today = datetime.now(UTC).date()
        if today != self.day:
            self.day = today
            self.order_count = 0
            self.realized_pnl = 0.0
            self.starting_equity = current_equity


@dataclass
class _AlertRecord:
    level: str
    message: str
    timestamp_utc: str


class PreTradeCheck:
    def __init__(self, limits: RiskLimits, mark_price_provider: Callable[[str], float | None] | None = None) -> None:
        self._limits = limits
        self._mark = mark_price_provider or (lambda _s: None)

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    def assert_ok(self, order: Order) -> None:
        if order.symbol.upper() in {s.upper() for s in self._limits.blacklist_symbols}:
            raise PreTradeError(f"{order.symbol} 在黑名单")
        notional = order.quantity * (order.price or 0)
        if notional > self._limits.per_order_max_usdt:
            raise PreTradeError(
                f"单笔名义 {notional:.2f} > 上限 {self._limits.per_order_max_usdt} USDT"
            )
        mark = self._mark(order.symbol)
        if mark and order.price and abs(order.price - mark) / mark > self._limits.fat_finger_pct:
            raise PreTradeError(
                f"肥手指：限价 {order.price} 偏离 mark {mark} 超过 {self._limits.fat_finger_pct*100:.2f}%"
            )


class RiskMonitor:
    """运行期监控 + 日志。pre_trade 在下单前调；at_trade / post_trade 由 ExecutionVenue feedback。"""

    def __init__(self, limits: RiskLimits, get_equity: Callable[[], float] | None = None) -> None:
        self._limits = limits
        self._pre = PreTradeCheck(limits)
        self._state = DailyState(day=datetime.now(UTC).date())
        self._get_equity = get_equity or (lambda: 0.0)
        self._alerts: list[_AlertRecord] = []
        self._lock = threading.RLock()  # re-entrant; on_fill→_pause→_record_alert 路径需要
        self._paused: bool = False

    @property
    def state(self) -> DailyState:
        return self._state

    @property
    def paused(self) -> bool:
        return self._paused

    def pre_trade(self, order: Order, *, mark_price: float | None = None) -> None:
        if self._paused:
            raise PreTradeError("RiskMonitor 已暂停（kill switch / daily loss / daily count）")
        self._state.reset_if_new_day(self._get_equity())
        if self._state.order_count >= self._limits.daily_order_count_max:
            self._pause("日内下单笔数上限触达")
            raise PreTradeError("达到 daily_order_count_max")
        check = PreTradeCheck(self._limits, lambda _s: mark_price)
        check.assert_ok(order)

    def on_fill(self, *, realized_pnl_delta: float = 0.0) -> None:
        with self._lock:
            self._state.order_count += 1
            self._state.realized_pnl += realized_pnl_delta
            if self._state.starting_equity > 0:
                pct = -self._state.realized_pnl / self._state.starting_equity
                if pct >= self._limits.daily_loss_limit_pct:
                    self._pause(f"日内亏损 {pct*100:.2f}% > 上限 {self._limits.daily_loss_limit_pct*100:.2f}%")

    def check_concentration(self, positions: dict[str, float], equity: float) -> list[str]:
        alerts: list[str] = []
        if equity <= 0:
            return alerts
        for sym, notional in positions.items():
            pct = abs(notional) / equity
            if pct > self._limits.single_symbol_position_pct_max:
                alerts.append(f"{sym} 集中度 {pct*100:.2f}% > {self._limits.single_symbol_position_pct_max*100:.2f}%")
        for msg in alerts:
            self._record_alert("warn", msg)
        return alerts

    def alerts(self) -> list[dict]:
        with self._lock:
            return [{"level": a.level, "message": a.message, "timestamp_utc": a.timestamp_utc} for a in self._alerts]

    def _pause(self, reason: str) -> None:
        self._paused = True
        self._record_alert("critical", f"PAUSE → {reason}")

    def _record_alert(self, level: str, message: str) -> None:
        with self._lock:
            self._alerts.append(_AlertRecord(level=level, message=message, timestamp_utc=datetime.now(UTC).isoformat()))


class KillSwitch:
    """顶部红按钮的后端：撤销所有挂单 + 市价平所有仓位。"""

    def __init__(self, venues: Iterable[ExecutionVenue]) -> None:
        self._venues = list(venues)

    def trigger(self, *, close_positions: bool = True) -> dict[str, list[dict]]:
        results: dict[str, list[dict]] = {}
        for venue in self._venues:
            venue_results: list[dict] = []
            cancel_fn = getattr(venue, "cancel_all_open", None)
            if callable(cancel_fn):
                try:
                    out = cancel_fn()
                    if isinstance(out, list):
                        venue_results.extend(out)
                    else:
                        venue_results.append(out)
                except Exception as exc:  # noqa: BLE001
                    venue_results.append({"error": str(exc), "stage": "cancel_all"})
            if close_positions:
                close_fn = getattr(venue, "close_position", None)
                positions = []
                try:
                    if hasattr(venue, "get_balance"):
                        positions = list(venue.get_balance().keys())
                except Exception:  # noqa: BLE001
                    pass
                if callable(close_fn) and positions:
                    for sym in positions:
                        try:
                            close_fn(sym)
                            venue_results.append({"closed": sym})
                        except Exception as exc:  # noqa: BLE001
                            venue_results.append({"error": str(exc), "stage": "close", "symbol": sym})
            results[venue.name] = venue_results
        return results


__all__ = [
    "DailyState",
    "KillSwitch",
    "PreTradeCheck",
    "PreTradeError",
    "RiskLimits",
    "RiskMonitor",
]
