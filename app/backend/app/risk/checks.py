"""M9.3 · 风控检查与 Kill Switch。

对齐 GOAL §M9.3 E 的硬约束：
- pre-trade：单笔金额上限 / minNotional / 肥手指偏离 / 黑名单
- run-time：单日下单笔数上限 / 单日亏损上限 / 持仓集中度 / 异常行情熔断 / 强平距离
- Kill Switch：一键撤所有 + 平所有
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable, Iterable, Mapping

from ..execution.base import ExecutionVenue, Order, Position
from ..execution.emergency import EmergencyHaltContext


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


@dataclass(frozen=True)
class EquitySnapshot:
    """Fresh account-equity observation used to prove monitor readiness."""

    equity: float
    observed_at_utc: str
    source_ref: str


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
        numeric = [order.quantity]
        numeric.extend(
            value
            for value in (order.price, order.stop_price, order.take_profit_price, order.leverage)
            if value is not None
        )
        if not all(math.isfinite(float(value)) for value in numeric):
            raise PreTradeError("订单数值必须为有限数")
        if order.quantity <= 0 or (order.price is not None and order.price <= 0):
            raise PreTradeError("订单数量和显式价格必须为正数")
        if order.symbol.upper() in {s.upper() for s in self._limits.blacklist_symbols}:
            raise PreTradeError(f"{order.symbol} 在黑名单")
        notional = order.quantity * (order.price or 0)
        if notional > self._limits.per_order_max_usdt:
            raise PreTradeError(
                f"单笔名义 {notional:.2f} > 上限 {self._limits.per_order_max_usdt} USDT"
            )
        mark = self._mark(order.symbol)
        if mark is not None and (not math.isfinite(float(mark)) or float(mark) <= 0):
            raise PreTradeError("mark price 必须为有限正数")
        if mark and order.price and abs(order.price - mark) / mark > self._limits.fat_finger_pct:
            raise PreTradeError(
                f"肥手指：限价 {order.price} 偏离 mark {mark} 超过 {self._limits.fat_finger_pct*100:.2f}%"
            )


class RiskMonitor:
    """运行期监控 + 日志。pre_trade 在下单前调；at_trade / post_trade 由 ExecutionVenue feedback。"""

    def __init__(
        self,
        limits: RiskLimits,
        get_equity: Callable[[], float | EquitySnapshot] | None = None,
        *,
        max_snapshot_age_s: float = 60.0,
    ) -> None:
        self._limits = limits
        self._pre = PreTradeCheck(limits)
        self._state = DailyState(day=datetime.now(UTC).date())
        self._equity_provider_bound = get_equity is not None
        self._get_equity = get_equity or (lambda: 0.0)
        self._max_snapshot_age_s = float(max_snapshot_age_s)
        self._alerts: list[_AlertRecord] = []
        self._lock = threading.RLock()  # re-entrant; on_fill→_pause→_record_alert 路径需要
        self._paused: bool = False

    @property
    def state(self) -> DailyState:
        return self._state

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def active(self) -> bool:
        """Whether a fresh, finite, source-bound account snapshot is available."""

        return self.readiness()[0]

    def readiness(self) -> tuple[bool, str | None]:
        if not self._equity_provider_bound:
            return False, "risk monitor has no account equity provider"
        try:
            snapshot = self._get_equity()
        except Exception as exc:  # noqa: BLE001 - readiness is a fail-closed probe.
            return False, f"account equity provider failed: {type(exc).__name__}"
        if not isinstance(snapshot, EquitySnapshot):
            return False, "account equity provider did not return a source-bound EquitySnapshot"
        if not snapshot.source_ref.strip():
            return False, "account equity snapshot has no source_ref"
        try:
            equity = float(snapshot.equity)
            observed_at = datetime.fromisoformat(snapshot.observed_at_utc)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            return False, "account equity snapshot is malformed"
        if not math.isfinite(equity) or equity <= 0:
            return False, "account equity snapshot must be finite and positive"
        age_s = (datetime.now(UTC) - observed_at.astimezone(UTC)).total_seconds()
        if age_s < -5:
            return False, "account equity snapshot timestamp is in the future"
        if age_s > self._max_snapshot_age_s:
            return False, f"account equity snapshot is stale ({age_s:.1f}s)"
        return True, None

    def _current_equity(self) -> float:
        raw = self._get_equity()
        return float(raw.equity if isinstance(raw, EquitySnapshot) else raw)

    def pre_trade(self, order: Order, *, mark_price: float | None = None) -> None:
        if self._paused:
            raise PreTradeError("RiskMonitor 已暂停（kill switch / daily loss / daily count）")
        current_equity = self._current_equity()
        self._state.reset_if_new_day(current_equity)
        if self._state.starting_equity <= 0 and math.isfinite(current_equity) and current_equity > 0:
            self._state.starting_equity = current_equity
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

    def __init__(
        self,
        venues: Iterable[ExecutionVenue] = (),
        *,
        venue_provider: Callable[[], Iterable[ExecutionVenue]] | None = None,
    ) -> None:
        self._venues = list(venues)
        self._venue_provider = venue_provider

    def _current_venues(self) -> list[ExecutionVenue]:
        if self._venue_provider is None:
            return list(self._venues)
        return list(self._venue_provider())

    def snapshot_venues(self) -> tuple[ExecutionVenue, ...]:
        """Freeze one venue set so actions and status use the same accounts."""

        return tuple(self._current_venues())

    @staticmethod
    def venue_names(venues: Iterable[ExecutionVenue]) -> tuple[str, ...]:
        return tuple(str(getattr(venue, "name", "") or "").strip() for venue in venues)

    @property
    def active_venue_names(self) -> tuple[str, ...]:
        return self.venue_names(self._current_venues())

    @staticmethod
    def _stage(
        *,
        ok: bool,
        actions: list[dict[str, Any]] | None = None,
        verified_noop: bool = False,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": bool(ok),
            "verified_noop": bool(verified_noop),
            "actions": list(actions or ()),
            "error": error,
        }

    def trigger(
        self,
        *,
        close_positions: bool = True,
        venues: Iterable[ExecutionVenue] | None = None,
        halt_contexts: Mapping[str, EmergencyHaltContext] | None = None,
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        name_counts: dict[str, int] = {}
        selected_venues = list(venues) if venues is not None else self._current_venues()
        for index, venue in enumerate(selected_venues):
            venue_name = str(getattr(venue, "name", "") or "").strip()
            name_counts[venue_name] = name_counts.get(venue_name, 0) + 1
            result_key = venue_name or f"__unnamed_{index}"
            if name_counts[venue_name] > 1:
                result_key = f"{result_key}#{name_counts[venue_name]}"

            cancel_fn = getattr(venue, "emergency_cancel_all", None)
            if not callable(cancel_fn):
                cancel_stage = self._stage(ok=False, error="emergency_cancel_all capability is missing")
            else:
                try:
                    out = cancel_fn()
                    if not isinstance(out, dict):
                        cancel_stage = self._stage(ok=False, error="emergency_cancel_all returned an invalid result")
                    else:
                        actions = out.get("actions")
                        valid_actions = isinstance(actions, list) and all(
                            isinstance(item, dict) for item in actions
                        )
                        verified_noop = out.get("verified_noop") is True
                        structurally_valid = valid_actions and bool(actions or verified_noop)
                        cancel_stage = self._stage(
                            ok=bool(out.get("ok")) and structurally_valid,
                            actions=actions if valid_actions else [],
                            verified_noop=verified_noop and not actions,
                            error=(
                                str(out.get("error") or "") or None
                                if structurally_valid
                                else "emergency_cancel_all did not provide actions or a verified no-op"
                            ),
                        )
                except Exception as exc:  # noqa: BLE001
                    cancel_stage = self._stage(ok=False, error=f"emergency_cancel_all failed: {exc}")

            halt_context: EmergencyHaltContext | None = None
            reconciliation_stage = self._stage(ok=True, verified_noop=True)
            if halt_contexts is not None:
                account_ref = str(getattr(venue, "account_ref", "") or "").strip()
                halt_context = halt_contexts.get(account_ref)
                reconcile_fn = getattr(venue, "reconcile_emergency_actions_for_halt", None)
                if not account_ref or halt_context is None:
                    reconciliation_stage = self._stage(
                        ok=False,
                        error="durable emergency HALT context is missing for venue account",
                    )
                elif not callable(reconcile_fn):
                    reconciliation_stage = self._stage(
                        ok=False,
                        error="durable emergency reconciliation capability is missing",
                    )
                else:
                    try:
                        reconciled = reconcile_fn(halt_context)
                        if not isinstance(reconciled, tuple) or any(
                            not isinstance(item, dict) for item in reconciled
                        ):
                            raise TypeError("emergency reconciliation returned an invalid result")
                        reconciliation_stage = self._stage(
                            ok=True,
                            actions=list(reconciled),
                            verified_noop=not reconciled,
                        )
                    except Exception as exc:  # noqa: BLE001
                        reconciliation_stage = self._stage(
                            ok=False,
                            error=f"emergency action reconciliation failed: {exc}",
                        )

            discovery_stage = self._stage(ok=True, verified_noop=True)
            close_stage = {
                **self._stage(ok=True, verified_noop=True),
                "requested": bool(close_positions),
            }
            if close_positions:
                list_fn = getattr(venue, "list_open_positions", None)
                close_fn = getattr(venue, "close_open_position", None)
                positions: list[Position] = []
                if not callable(list_fn):
                    discovery_stage = self._stage(ok=False, error="list_open_positions capability is missing")
                else:
                    try:
                        raw_positions = list_fn()
                        if not isinstance(raw_positions, list) or any(
                            not isinstance(position, Position) for position in raw_positions
                        ):
                            discovery_stage = self._stage(
                                ok=False,
                                error="list_open_positions returned an invalid result",
                            )
                        else:
                            positions = [position for position in raw_positions if position.quantity != 0]
                            discovery_stage = self._stage(
                                ok=True,
                                actions=[
                                    {
                                        "symbol": position.symbol,
                                        "quantity": position.quantity,
                                    }
                                    for position in positions
                                ],
                                verified_noop=not positions,
                            )
                    except Exception as exc:  # noqa: BLE001
                        discovery_stage = self._stage(ok=False, error=f"list_open_positions failed: {exc}")

                if not discovery_stage["ok"]:
                    close_stage = {
                        **self._stage(ok=False, error="position discovery failed; close stage not executed"),
                        "requested": True,
                    }
                elif positions and not callable(close_fn):
                    close_stage = {
                        **self._stage(ok=False, error="close_open_position capability is missing"),
                        "requested": True,
                    }
                elif positions:
                    close_actions: list[dict[str, Any]] = []
                    close_errors: list[str] = []
                    for position in positions:
                        try:
                            if halt_contexts is not None:
                                contextual_close = getattr(
                                    venue,
                                    "close_open_position_for_halt",
                                    None,
                                )
                                if halt_context is None or not callable(contextual_close):
                                    raise PermissionError(
                                        "durable emergency close context/capability is unavailable"
                                    )
                                raw_close = contextual_close(position, halt_context)
                            else:
                                raw_close = close_fn(position)
                            if not isinstance(raw_close, dict):
                                raise TypeError("close_open_position returned a non-object result")
                            close_actions.append(
                                {
                                    "symbol": position.symbol,
                                    "quantity": position.quantity,
                                    "ack": raw_close,
                                }
                            )
                        except Exception as exc:  # noqa: BLE001
                            close_errors.append(f"{position.symbol}: {exc}")
                    close_stage = {
                        **self._stage(
                            ok=not close_errors,
                            actions=close_actions,
                            error="; ".join(close_errors) or None,
                        ),
                        "requested": True,
                    }

            verify_fn = getattr(venue, "verify_emergency_flat", None)
            if not callable(verify_fn):
                flat_verification_stage = {
                    **self._stage(ok=False, error="verify_emergency_flat capability is missing"),
                    "proof": None,
                }
            else:
                try:
                    proof = verify_fn(close_positions=close_positions)
                    if not isinstance(proof, dict):
                        raise TypeError("verify_emergency_flat returned a non-object result")
                    normal_refs = proof.get("normal_open_order_refs")
                    algo_refs = proof.get("algo_open_order_refs")
                    open_positions = proof.get("open_positions")
                    if not isinstance(normal_refs, list) or any(
                        not isinstance(ref, str) or not ref for ref in normal_refs
                    ):
                        raise ValueError("flat proof has invalid normal_open_order_refs")
                    if not isinstance(algo_refs, list) or any(
                        not isinstance(ref, str) or not ref for ref in algo_refs
                    ):
                        raise ValueError("flat proof has invalid algo_open_order_refs")
                    if not isinstance(open_positions, list) or any(
                        not isinstance(item, dict)
                        or not str(item.get("symbol") or "").strip()
                        or type(item.get("quantity")) not in {int, float}
                        or not math.isfinite(float(item["quantity"]))
                        or float(item["quantity"]) == 0
                        for item in open_positions
                    ):
                        raise ValueError("flat proof has invalid open_positions")
                    expected_clean = not normal_refs and not algo_refs and (
                        not close_positions or not open_positions
                    )
                    proof_ok = proof.get("ok") is True and expected_clean
                    flat_verification_stage = {
                        **self._stage(
                            ok=proof_ok,
                            verified_noop=proof_ok,
                            error=(
                                None
                                if proof_ok
                                else "fresh emergency verification still contains exposure or did not attest ok"
                            ),
                        ),
                        "proof": proof,
                    }
                except Exception as exc:  # noqa: BLE001
                    flat_verification_stage = {
                        **self._stage(ok=False, error=f"verify_emergency_flat failed: {exc}"),
                        "proof": None,
                    }

            venue_ok = bool(
                cancel_stage["ok"]
                and reconciliation_stage["ok"]
                and discovery_stage["ok"]
                and close_stage["ok"]
                and flat_verification_stage["ok"]
            )
            results[result_key] = {
                "venue_name": venue_name,
                "ok": venue_ok,
                "cancel": cancel_stage,
                "emergency_reconciliation": reconciliation_stage,
                "position_discovery": discovery_stage,
                "close": close_stage,
                "flat_verification": flat_verification_stage,
            }
        return results


__all__ = [
    "DailyState",
    "EquitySnapshot",
    "KillSwitch",
    "PreTradeCheck",
    "PreTradeError",
    "RiskLimits",
    "RiskMonitor",
]
