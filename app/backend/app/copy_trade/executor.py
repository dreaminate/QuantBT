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
from .beta import CopyTradeBetaService, IdempotencyViolation, apply_follower_leverage_cap
from .gate_binding import follower_gate, follower_tier, live_requires_deps, relay_nonce
from .service import CopyTradeService, Follower, Signal


logger = logging.getLogger(__name__)


def _fail_closed_decision(tier: TrustTier) -> PolicyDecision:
    """D-T021-3：真钱档门依赖（broker/nonce）缺失时的 fail-closed 裁决（拒单、不取 key）。"""

    v = ["live_deps_unavailable_fail_closed"]
    return PolicyDecision(allow=False, tier=tier, violations=v,
                          verdict_text=_verdict_text(False, tier, v, False))


class VenueFactory(Protocol):
    """构造 follower 自己的 BinanceVenue。注入式，方便测试 mock。"""

    def __call__(self, follower: Follower, keystore: SecureKeystore) -> ExecutionVenue | None: ...


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

    def _place(self, venue: ExecutionVenue, order: Order, signal: Signal, f: Follower) -> Any:
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
        )
        return guarded.place_order(order, nonce=nonce, ref_price=ref_price)

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

        # 2. key 存在性预检（master 永远拿不到 follower key）。
        #    T-022：注入 broker 时走 broker.has_key（不返回 key 本体）→ relayer 不再 self-fetch；
        #    否则退化到既有 keystore.fetch（向后兼容无 broker 的调用/测试）。
        if self._broker is not None:
            if not self._broker.has_key(f.binance_keystore_name):
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
        )
        try:
            rm.pre_trade(order, mark_price=signal.price)
        except Exception as exc:  # noqa: BLE001
            self._ct.record_execution(
                signal.signal_id, f.follower_id, "rejected", error=f"risk: {exc}",
            )
            return {"follower_id": f.follower_id, "status": "rejected", "reason": str(exc)}

        # 5. 真下单（生产：必经会话外硬墙 OrderGuard；门拒 → rejected 不下单、不取 key）
        try:
            ack = self._place(venue, order, signal, f)
        except OrderGated as gated:
            self._ct.record_execution(
                signal.signal_id, f.follower_id, "rejected",
                error="gate: " + "; ".join(gated.decision.violations),
            )
            return {"follower_id": f.follower_id, "status": "rejected",
                    "reason": "; ".join(gated.decision.violations),
                    "verdict_text": gated.decision.verdict_text}
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
        }


__all__ = ["SignalRelayer", "VenueFactory"]
