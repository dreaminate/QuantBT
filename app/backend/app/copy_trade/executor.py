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
import hashlib
from typing import Any, Protocol

from ..execution.base import ExecutionVenue, Order
from ..risk import RiskLimits, RiskMonitor
from ..security.gate.broker import KeyBroker
from ..security.gate.enforcer import OrderGuard
from ..security.gate.nonce import NonceLedger
from ..security.gate.policy import (
    OrderGated,
    PolicyDecision,
    TrustTier,
    _verdict_text,
    gate_hash,
)
from ..security.keystore import KeystoreError, SecureKeystore
from ..security.mainnet_guards import MainnetGuardError, MainnetGuardsService
from .beta import CopyTradeBetaService, IdempotencyViolation, apply_follower_leverage_cap
from .gate_binding import follower_gate, follower_tier, live_requires_deps, relay_nonce
from .service import CopyTradeService, Follower, Signal
from .formal_execution import CopyTradeFormalError, PreparedCopyTradeExecution


logger = logging.getLogger(__name__)


def copy_trade_quota_reservation_ref(
    signal_id: str,
    follower_id: str,
    client_order_id: str,
) -> str:
    """Canonical quota identity shared by the hot path and crash recovery."""

    values = tuple(str(value or "").strip() for value in (signal_id, follower_id, client_order_id))
    if not all(values):
        raise ValueError("copy-trade quota identity requires signal, follower, and client order refs")
    return "mainnet_quota_" + hashlib.sha256("::".join(values).encode("utf-8")).hexdigest()


def _fail_closed_decision(tier: TrustTier) -> PolicyDecision:
    """D-T021-3：真钱档门依赖（broker/nonce）缺失时的 fail-closed 裁决（拒单、不取 key）。"""

    v = ["live_deps_unavailable_fail_closed"]
    return PolicyDecision(allow=False, tier=tier, violations=v,
                          verdict_text=_verdict_text(False, tier, v, False))


class VenueFactory(Protocol):
    """构造 follower 自己的 BinanceVenue。注入式，方便测试 mock。"""

    def __call__(self, follower: Follower, keystore: SecureKeystore) -> ExecutionVenue | None: ...


class MainnetReadinessProvider(Protocol):
    """Authoritative process readiness used before any live-order sensitive surface."""

    def __call__(self) -> bool: ...


class SignalRelayer:
    """无状态：每次 relay 调一次 venue_factory + risk monitor。

    v0.8.9 · 注入 CopyTradeBetaService 后，下单路径强制走两道真金白银护栏：
    - 幂等：同一 (signal_id, follower_id) 已下发过则跳过，绝不重复下单（防信号重发/网络重试）
    - 杠杆硬截断：master 信号杠杆被 follower 自己的 max_leverage 上限截断后才落到 venue
    beta 缺省为 None 仅为向后兼容旧调用 / 单测；生产必须注入。
    """

    def __init__(
        self,
        copy_trade: CopyTradeService,
        keystore: SecureKeystore,
        venue_factory: VenueFactory,
        beta: CopyTradeBetaService | None = None,
        *,
        enforce_gate: bool = False,
        broker: KeyBroker | None = None,
        nonce_ledger: NonceLedger | None = None,
        on_gate_event: Any = None,
        formal_coordinator: Any = None,
        mainnet_guards: MainnetGuardsService | None = None,
        mainnet_readiness_provider: MainnetReadinessProvider | None = None,
    ) -> None:
        self._ct = copy_trade
        self._keystore = keystore
        self._make_venue = venue_factory
        self._beta = beta
        # T-021 生产接线：enforce_gate=True 时所有下单热路径必经 OrderGuard（INV-2/M17 命门）。
        # 缺省 False 仅为向后兼容既有调用/单测（763 基线）；**生产 main.py 必须置 True 并注入 broker+nonce**。
        self._enforce_gate = enforce_gate
        self._broker = broker
        self._nonce_ledger = nonce_ledger
        self._on_gate_event = on_gate_event
        self._formal = formal_coordinator
        self._mainnet_guards = mainnet_guards
        self._mainnet_readiness_provider = mainnet_readiness_provider

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

    def _place(
        self,
        venue: ExecutionVenue,
        order: Order,
        signal: Signal,
        f: Follower,
        *,
        prepared: PreparedCopyTradeExecution | None = None,
        before_lease: Any = None,
        before_submit: Any = None,
    ) -> Any:
        """下单提交点。enforce_gate=False → 原样直发（向后兼容）；True → 必经 OrderGuard。

        OrderGuard 顺序：S1 防重放 → S2 deny-by-default 策略门 → S4 JIT lease → S5 提交。
        任一前置失败 raise OrderGated（由 _relay_to_one 记 rejected），key 永不取出。

        T-021 交付 INV-2/M17（会话外硬墙接全 relay 路径）+ INV-4（防重放）+ fail-closed。
        T-022 交付 INV-3 lease-唯一-key 通道：注入 broker 时，OrderGuard S4 发 JIT lease →
        `_submit(order, lease)` → LeasedBinanceVenue 从 lease 现造 creds 签名（venue 构造时不持 key）。
        真 key 只在放行后那一刻现身后端内存；门拒/缺 lease → venue 拿不到 key → 下不了单（INV-3 命门）。
        """

        if not self._enforce_gate:
            # T-025 #3：闭「向后兼容陷阱」——直发路径仅限非真钱（testnet/paper）。真钱档(CRYPTO_LIVE)
            # 即便 enforce_gate=False 也绝不裸发（生产恒 enforce_gate=True，此为纵深防御，防误配旁路真钱）。
            if live_requires_deps(follower_tier(f)):
                raise OrderGated(_fail_closed_decision(follower_tier(f)))
            return venue.place_order(order)                 # 向后兼容路径（测试/旧调用，仅非真钱）

        tier = follower_tier(f)
        gate = follower_gate(f, signal, tier=tier)
        # D-T021-3 fail-closed：真钱档防重放台缺失即拒，绝不裸放（nonce 台宕机时不放真钱单）。
        # broker/lease 是 INV-3 增强（见 _place docstring 的残余说明），非真钱放行前置——不并入 fail-closed。
        if live_requires_deps(tier) and self._nonce_ledger is None:
            raise OrderGated(_fail_closed_decision(tier))

        cap = None
        if self._broker is not None:                       # 注入 broker 时走 JIT lease（T-022 生产已注入 ORDER_BROKER；无 broker 仅旧调用/单测兼容）
            cap = self._broker.issue_capability(
                action="request_live_order", gate_ref=gate_hash(gate),
                keystore_name=f.binance_keystore_name,
                account_identity_ref=f.account_binding_ref or None,
                owner_user_id=f.user_id,
                # This flag is derived from the trusted persisted follower
                # tier, never from signal/order payloads.  Mainnet cannot
                # degrade into the testnet-compatible unfenced path.
                requires_halt_fence=(tier == TrustTier.CRYPTO_LIVE),
            )
        nonce = relay_nonce(signal.signal_id, f.follower_id) if self._nonce_ledger is not None else None
        # 复核 fix B：market 单 order.price=None，非 PAPER 门会判 notional_unverifiable 全拒。
        # 从【可信 venue 侧】取 mark 作名义额核验入参（绝不读 signal/extra 自报价，防投毒）；
        # 不改 order.price（venue 会把 price 发交易所污染市价单）。取不到 mark → 门 deny-by-default（fail-safe）。
        ref_price = order.price
        if ref_price is None:
            ref_price = self._trusted_mark(venue, order.symbol)
        guarded = OrderGuard.wrap(
            venue, gate=gate, broker=self._broker, capability=cap,
            nonce_ledger=self._nonce_ledger, on_event=self._on_gate_event,
            before_lease=before_lease, before_submit=before_submit,
        )
        return guarded.place_order(
            order,
            nonce=nonce,
            attestation=prepared.attestation if prepared is not None else None,
            drawdown_now=prepared.reservation.drawdown_now if prepared is not None else 0.0,
            daily_turnover_so_far=(
                prepared.reservation.daily_turnover_before if prepared is not None else 0.0
            ),
            ref_price=(prepared.reservation.trusted_mark_price if prepared is not None else ref_price),
        )

    @staticmethod
    def _trusted_mark(venue: ExecutionVenue, symbol: str) -> float | None:
        """从 venue 侧取可信 mark 价（市价单名义额核验用）。失败/无价 → None（门 fail-safe deny）。

        优先用 lease-free 的 `get_mark_price`（公共端点，T-022 lease-only venue 在 lease 之前也能核名义额）；
        无此方法的（legacy venue / mock）退化到 get_position.mark_price。
        """

        getter = getattr(venue, "get_mark_price", None)
        if callable(getter):
            try:
                m = getter(symbol)
                return float(m) if m and float(m) > 0 else None
            except Exception:  # noqa: BLE001
                return None
        try:
            pos = venue.get_position(symbol)
            mark = float(getattr(pos, "mark_price", 0) or 0)
            return mark if mark > 0 else None
        except Exception:  # noqa: BLE001  取价失败不放行——交给门 deny-by-default
            return None

    def _relay_to_one(self, signal: Signal, f: Follower) -> dict[str, Any]:
        # 0. 幂等护栏：同一 (signal, follower) 已下发过 → 直接跳过，绝不重复下单
        #    （防 master 信号重发 / 网络重试导致同一笔被打两次真金白银）
        if self._beta is not None and self._beta.is_dispatched(signal.signal_id, f.follower_id):
            self._ct.record_execution(
                signal.signal_id, f.follower_id, "skipped",
                error="duplicate dispatch (idempotent skip)",
            )
            return {"follower_id": f.follower_id, "status": "skipped", "reason": "duplicate"}

        # 1. follower 没填 keystore 名字 → skip
        if not f.binance_keystore_name:
            self._ct.record_execution(signal.signal_id, f.follower_id, "skipped", error="no keystore configured")
            return {"follower_id": f.follower_id, "status": "skipped", "reason": "no_keystore"}

        tier = follower_tier(f)
        if tier == TrustTier.CRYPTO_LIVE:
            # Fail closed before any credential lookup or venue construction.  A
            # missing live dependency must not materialize a key as a side effect
            # of discovering that the order cannot be submitted safely.
            if self._nonce_ledger is None or self._broker is None:
                decision = _fail_closed_decision(tier)
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    "rejected",
                    error="gate: " + "; ".join(decision.violations),
                )
                return {
                    "follower_id": f.follower_id,
                    "status": "rejected",
                    "reason": "; ".join(decision.violations),
                    "verdict_text": decision.verdict_text,
                }
            if self._formal is None:
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    "rejected",
                    error="formal execution coordinator unavailable",
                )
                return {
                    "follower_id": f.follower_id,
                    "status": "rejected",
                    "reason": "formal_execution_unavailable",
                }
            try:
                mainnet_ready = (
                    self._mainnet_readiness_provider is not None
                    and self._mainnet_readiness_provider() is True
                )
            except Exception:  # noqa: BLE001 - readiness uncertainty must fail closed.
                mainnet_ready = False
            if not mainnet_ready:
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    "rejected",
                    error="mainnet reconciliation readiness unavailable",
                )
                return {
                    "follower_id": f.follower_id,
                    "status": "rejected",
                    "reason": "mainnet_reconciliation_unavailable_fail_closed",
                }

        # 2. key 存在性预检（master 永远拿不到 follower key）。
        #    T-022：注入 broker 时走 broker.has_key（不返回 key 本体）→ relayer 不再 self-fetch；
        #    否则退化到既有 keystore.fetch（向后兼容无 broker 的调用/测试）。
        if self._broker is not None:
            if not self._broker.has_key(
                f.binance_keystore_name,
                owner_user_id=f.user_id,
            ):
                self._ct.record_execution(signal.signal_id, f.follower_id, "skipped", error="keystore miss")
                return {"follower_id": f.follower_id, "status": "skipped", "reason": "keystore_miss"}
        else:
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
        # 杠杆硬截断：master 信号杠杆 → follower 自己的 max_leverage 上限（spot/无杠杆 → None 透传）
        applied_leverage, leverage_clamped = apply_follower_leverage_cap(signal.leverage, f.max_leverage)
        # 复核 fix A：现货无杠杆概念——leverage=None 会被实盘门判 leverage_unspecified 全拒。
        # 现货显式声明 1x（满足「实盘须声明杠杆」且绝不放真杠杆；期货仍需显式 cap，None→门拒不变）。
        order_leverage = applied_leverage
        master = self._ct.get_master(signal.master_id)
        if order_leverage is None and master is not None and master.asset_class == "crypto_spot":
            order_leverage = 1.0
        order = Order(
            venue=getattr(venue, "name", "binance"),
            symbol=signal.symbol,
            side=signal.side,
            quantity=signal.quantity,
            order_type=signal.order_type,
            price=signal.price,
            leverage=order_leverage,
            client_order_id=(
                "qbt-" + hashlib.sha256(
                    f"{signal.signal_id}::{f.follower_id}".encode("utf-8")
                ).hexdigest()[:28]
            ),
        )
        prepared: PreparedCopyTradeExecution | None = None
        if tier == TrustTier.CRYPTO_LIVE:
            try:
                prepared = self._formal.prepare(
                    follower=f,
                    signal=signal,
                    order=order,
                    actor="copy_trade_signal_relayer",
                )
            except CopyTradeFormalError as exc:
                self._formal.abort_pre_submit(
                    follower=f,
                    signal=signal,
                    reason_ref="formal_pre_submit_reject_" + hashlib.sha256(
                        str(exc).encode("utf-8")
                    ).hexdigest(),
                )
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    "rejected",
                    error=f"formal: {exc}",
                )
                return {"follower_id": f.follower_id, "status": "rejected", "reason": str(exc)}
            except Exception as exc:  # noqa: BLE001 - persistence errors fail closed before venue access.
                reason_ref = "formal_pre_submit_failure_" + hashlib.sha256(
                    type(exc).__name__.encode("utf-8")
                ).hexdigest()
                try:
                    self._formal.abort_pre_submit(
                        follower=f,
                        signal=signal,
                        reason_ref=reason_ref,
                    )
                except Exception as abort_exc:  # noqa: BLE001
                    logger.critical(
                        "formal pre-submit abort persistence failed signal=%s follower=%s: %s",
                        signal.signal_id,
                        f.follower_id,
                        abort_exc,
                    )
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    "failed",
                    error=f"formal_pre_submit_failed:{type(exc).__name__}",
                )
                return {
                    "follower_id": f.follower_id,
                    "status": "failed",
                    "reason": "formal_pre_submit_failed",
                }
        else:
            try:
                trusted_mark = signal.price if signal.price is not None else self._trusted_mark(venue, order.symbol)
                rm.pre_trade(order, mark_price=trusted_mark)
            except Exception as exc:  # noqa: BLE001
                self._ct.record_execution(
                    signal.signal_id, f.follower_id, "rejected", error=f"risk: {exc}",
                )
                return {"follower_id": f.follower_id, "status": "rejected", "reason": str(exc)}

        quota_ref = ""
        quota_reserved = False
        venue_attempted = False

        def _quota_denied(code: str) -> OrderGated:
            decision = PolicyDecision(
                allow=False,
                tier=tier,
                violations=[code],
                verdict_text=_verdict_text(False, tier, [code], False),
            )
            return OrderGated(decision)

        def _before_lease(_order: Order, _decision: PolicyDecision) -> None:
            nonlocal quota_ref, quota_reserved
            if tier != TrustTier.CRYPTO_LIVE:
                return
            if self._mainnet_guards is None:
                raise _quota_denied("mainnet_quota_guard_unavailable")
            if self._mainnet_guards.get_config(f.user_id).require_password_per_order:
                raise _quota_denied("standing_auto_copy_authorization_required")
            quota_ref = copy_trade_quota_reservation_ref(
                signal.signal_id,
                f.follower_id,
                str(order.client_order_id or ""),
            )
            try:
                self._mainnet_guards.reserve_operation(
                    f.user_id,
                    "copy_trade_live_order",
                    reservation_ref=quota_ref,
                    notional_usdt=(prepared.reservation.notional_usdt if prepared is not None else 0.0),
                )
            except MainnetGuardError as exc:
                raise _quota_denied("mainnet_daily_quota_rejected") from exc
            quota_reserved = True

        def _before_submit(_order: Order, _decision: PolicyDecision) -> None:
            nonlocal venue_attempted
            # This callback is invoked by the venue only after position-mode /
            # margin / leverage preflight and immediately before the exact
            # order POST.  Persist uncertainty first, then cross the boundary.
            if prepared is not None:
                self._formal.mark_order_request_started(prepared)
            # The venue has not been attempted until the durable boundary
            # marker succeeds. A marker failure is therefore a definitive
            # pre-submit reject, not an unqueryable outcome-unknown order.
            venue_attempted = True

        def _finish_quota(*, result: str, error: str | None = None) -> None:
            nonlocal quota_reserved
            if not quota_reserved or self._mainnet_guards is None:
                return
            if result == "rejected":
                self._mainnet_guards.release_operation(quota_ref, error=error or "pre_submit_rejected")
            else:
                self._mainnet_guards.settle_operation(
                    quota_ref,
                    venue=getattr(venue, "name", None),
                    symbol=order.symbol,
                    side=order.side,
                    result=result,
                    error=error,
                )
            quota_reserved = False

        # 5. 真下单（生产：必经会话外硬墙 OrderGuard；门拒 → rejected 不下单、不取 key）
        try:
            ack = self._place(
                venue,
                order,
                signal,
                f,
                prepared=prepared,
                before_lease=_before_lease,
                before_submit=_before_submit,
            )
        except OrderGated as gated:
            try:
                _finish_quota(result="rejected", error=";".join(gated.decision.violations))
            except Exception:  # noqa: BLE001 - quota stays reserved and fail-safe on settlement outage.
                logger.critical("mainnet quota release failed", exc_info=True)
            formal_refs: dict[str, str] = {}
            if prepared is not None:
                formal_refs = self._formal.record_failure(
                    prepared,
                    reason_ref="order_guard_reject_" + hashlib.sha256(
                        str(gated.decision.model_dump()).encode("utf-8")
                    ).hexdigest(),
                    definitive_reject=True,
                    actor="copy_trade_signal_relayer",
                )
            self._ct.record_execution(
                signal.signal_id, f.follower_id, "rejected",
                error="gate: " + "; ".join(gated.decision.violations),
            )
            return {"follower_id": f.follower_id, "status": "rejected",
                    "reason": "; ".join(gated.decision.violations),
                    "verdict_text": gated.decision.verdict_text, **formal_refs}
        except Exception as exc:  # noqa: BLE001
            definitive_pre_submit_reject = not venue_attempted
            try:
                _finish_quota(
                    result="outcome_unknown" if venue_attempted else "rejected",
                    error=type(exc).__name__,
                )
            except Exception:  # noqa: BLE001 - pending reservation remains counted fail-safe.
                logger.critical("mainnet quota finalization failed", exc_info=True)
            formal_refs = {}
            if prepared is not None:
                formal_refs = self._formal.record_failure(
                    prepared,
                    reason_ref=(
                        "pre_submit_reject_" if definitive_pre_submit_reject else "submission_unknown_"
                    ) + hashlib.sha256(
                        type(exc).__name__.encode("utf-8")
                    ).hexdigest(),
                    definitive_reject=definitive_pre_submit_reject,
                    actor="copy_trade_signal_relayer",
                )
            execution_status = (
                "failed"
                if prepared is None
                else "outcome_unknown"
                if venue_attempted
                else "rejected"
            )
            self._ct.record_execution(
                signal.signal_id,
                f.follower_id,
                execution_status,
                error=str(exc),
            )
            return {
                "follower_id": f.follower_id,
                "status": execution_status,
                "reason": str(exc),
                **formal_refs,
            }

        try:
            _finish_quota(result="submitted")
        except Exception:  # noqa: BLE001 - ack is real; leave reserved quota counted and continue formal recording.
            logger.critical("mainnet quota settlement after venue ack failed", exc_info=True)

        status = "placed"
        formal_refs: dict[str, str] = {}
        if prepared is not None:
            try:
                formal_refs = self._formal.record_success(
                    prepared,
                    ack=ack,
                    actor="copy_trade_signal_relayer",
                )
            except Exception as exc:  # noqa: BLE001
                logger.critical(
                    "venue ack 已返回但 formal outcome 持久化失败 signal=%s follower=%s: %s",
                    signal.signal_id,
                    f.follower_id,
                    exc,
                )
                durable = self._formal.durable_outcome_after_projection_failure(prepared)
                durable_status = durable.pop("formal_status", "outcome_unknown")
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    durable_status,
                    venue_order_id=ack.order_id,
                    error=f"formal_outcome_persistence_failed:{type(exc).__name__}",
                )
                return {
                    "follower_id": f.follower_id,
                    "status": durable_status,
                    "venue_order_id": ack.order_id,
                    "reason": "formal_projection_pending",
                    **{key: value for key, value in durable.items() if value},
                }
            formal_status = formal_refs.pop("formal_status", "placed")
            formal_reason = formal_refs.pop("formal_reason", None)
            if formal_status in {"rejected", "outcome_unknown", "needs_reconcile"}:
                self._ct.record_execution(
                    signal.signal_id,
                    f.follower_id,
                    formal_status,
                    venue_order_id=ack.order_id or None,
                    error=formal_reason or ("venue rejected order" if formal_status == "rejected" else None),
                )
                result = {
                    "follower_id": f.follower_id,
                    "status": formal_status,
                    "venue_order_id": ack.order_id,
                    **formal_refs,
                }
                if formal_reason:
                    result["reason"] = formal_reason
                return result
        self._ct.record_execution(
            signal.signal_id, f.follower_id, status,  # type: ignore[arg-type]
            venue_order_id=ack.order_id,
        )
        # 下单成功后落幂等记录（带杠杆截断审计）。并发竞态下 UNIQUE 约束兜底，
        # 已成交订单不因记账冲突回滚，仅记 CRITICAL 供复盘。
        if self._beta is not None:
            try:
                self._beta.record_dispatch(
                    signal.signal_id, f.follower_id, signal.master_id,
                    master_leverage=signal.leverage,
                    follower_applied_leverage=applied_leverage,
                    clamped=leverage_clamped,
                )
            except IdempotencyViolation:
                logger.critical(
                    "幂等竞态：signal=%s follower=%s 已下单但 dispatch 记录冲突（疑似并发重复下发）",
                    signal.signal_id, f.follower_id,
                )
        return {
            "follower_id": f.follower_id,
            "status": status,
            "venue_order_id": ack.order_id,
            "leverage": applied_leverage,
            "leverage_clamped": leverage_clamped,
            **formal_refs,
        }


__all__ = ["SignalRelayer", "VenueFactory", "copy_trade_quota_reservation_ref"]
