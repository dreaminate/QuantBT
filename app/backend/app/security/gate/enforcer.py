"""OrderGuard · 所有执行路径必经的会话外硬墙（T-018 / spine 06，补洞 1=M17 同形）。

包住任意 venue 的 place_order，强制 S0 分级 → S1 防重放 → S2 deny-by-default 策略门 → S3 升级人在环
→ S4 JIT lease（**只有走到这里才 fetch 真 key**）→ S5 提交 → S6 审计 → S7 焚 lease。
任一 S1/S2/S3 失败 → 不进 S4 → key 永不被取出 → **agent 注入成功也下不了单**（INV-3 命门）。
四条 venue（paper/binance_um/generic/relay）共用同一个门 = 一个会话外门、非四套局部检查（T10/M17）。
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from .broker import CapabilityToken, KeyBroker
from .ingest import Attestation
from .nonce import NonceLedger
from .policy import OrderGated, PolicyDecision, PolicyGate, TrustTier, _verdict_text, evaluate, gate_hash


class OrderGuard:
    def __init__(
        self,
        inner_venue: Any,
        *,
        gate: PolicyGate,
        broker: KeyBroker | None = None,
        capability: CapabilityToken | None = None,
        nonce_ledger: NonceLedger | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._inner = inner_venue
        self._gate = gate
        self._broker = broker
        self._cap = capability
        self._nonce = nonce_ledger
        self._on_event = on_event

    @classmethod
    def wrap(cls, venue: Any, **kwargs: Any) -> "OrderGuard":
        return cls(venue, **kwargs)

    def _emit(self, event: str, decision: PolicyDecision, **extra: Any) -> None:
        if self._on_event is not None:
            self._on_event(event, {"decision": decision.model_dump(), "tier": self._gate.tier.value, **extra})

    def place_order(
        self,
        order: Any,
        *,
        nonce: str | None = None,
        attestation: Attestation | None = None,
        drawdown_now: float = 0.0,
        ref_price: float | None = None,
    ) -> Any:
        """门控上下文走【可信调用方显式入参】，**绝不**从 order.extra 取（复核 #15：extra 是 agent/
        信号侧不可信输入，从中读 attestation_ok/action 等于让注入单自报「已授权」）。
        action 取自【capability】（可信签发），非订单。
        """

        action = self._cap.action if self._cap is not None else "request_live_order"
        attestation_ok = bool(attestation is not None and attestation.passed)

        # S1 防重放。复核 #4/#12/#16：CRYPTO_LIVE 强制 nonce + ledger，缺即 fail-closed（不静默放过重放面）。
        if self._gate.tier == TrustTier.CRYPTO_LIVE and (self._nonce is None or not nonce):
            d = PolicyDecision(allow=False, tier=self._gate.tier, violations=["nonce_required_on_live"],
                               verdict_text=_verdict_text(False, self._gate.tier, ["nonce_required_on_live"], False))
            self._emit("ORDER_DENIED", d)
            raise OrderGated(d)
        if self._nonce is not None and nonce:
            if not self._nonce.check_and_consume(str(nonce), context=getattr(order, "symbol", "")):
                d = PolicyDecision(
                    allow=False, tier=self._gate.tier, violations=["replay_rejected"],
                    verdict_text=_verdict_text(False, self._gate.tier, ["replay_rejected"], False),
                )
                self._emit("REPLAY_REJECTED", d, nonce=nonce)
                raise OrderGated(d)

        # S2/S3 策略门（deny-by-default + 升级）。
        decision = evaluate(self._gate, order, action=action,
                            attestation_ok=attestation_ok, drawdown_now=drawdown_now,
                            ref_price=ref_price)
        if not decision.allow:
            self._emit("ORDER_DENIED", decision)
            raise OrderGated(decision)            # 不进 S4 → key 永不取出

        # S3.5 capability 必须绑定【本门】（复核 #3）：用旧/松门签的 capability 取不到本门的 key。
        if self._broker is not None and self._cap is not None:
            if self._cap.gate_ref != gate_hash(self._gate):
                d = PolicyDecision(allow=False, tier=self._gate.tier, violations=["capability_gate_mismatch"],
                                   verdict_text=_verdict_text(False, self._gate.tier, ["capability_gate_mismatch"], False))
                self._emit("ORDER_DENIED", d)
                raise OrderGated(d)

        # S4 JIT lease（只有放行才取 key）。
        lease = None
        if self._broker is not None and self._cap is not None:
            lease = self._broker.issue(self._cap)
        try:
            # S5 提交：把 lease.record（broker 发的 JIT key）交给 venue 签名——lease 是【唯一】key 通道
            # （复核 #2）。venue 不支持 lease 入参时退化为自取（生产 venue 重构为只认 lease 是 deferred 接线项）。
            ack = self._submit(order, lease)
        finally:
            if lease is not None:                 # S7 用完即焚
                self._broker.revoke(lease)
        self._emit("ORDER_GATED", decision)       # S6 审计
        return ack

    def _submit(self, order: Any, lease: Any) -> Any:
        inner = self._inner.place_order
        if lease is not None and _accepts_lease(inner):
            # venue 接受 lease → lease 是唯一 key 通道。**不**包 try/except TypeError：
            # 提交期 venue 内部的真实 TypeError（如 POST 后 None 下标/序列化 bug）必须原样上抛，
            # 绝不能被误当成「venue 不支持 lease」吞掉、再无 lease 重试——那会同时掩盖真 bug 并对
            # lease-only 生产 venue 触发误导性 PermissionError（交易所侧可能已有真实持仓）。
            return inner(order, lease=lease)
        return inner(order)                        # venue 不收 lease（生产重构 deferred）或本次无 lease


def _accepts_lease(func: Callable[..., Any]) -> bool:
    """前置探测 venue.place_order 是否接受 lease 关键字（签名含 'lease' 形参或 **kwargs）。

    取代旧的「try inner(order, lease=lease) → except TypeError 退化自取」：那种写法无法区分
    「签名不收 lease」与「lease-接受型 venue 提交期内部抛 TypeError」，会把后者的真实 bug 吞掉。
    签名不可探测时（极少数 C 实现 / 无 __signature__）保守视为接受——让调用按真实签名失败而非静默退化。
    """

    try:
        params = inspect.signature(func).parameters.values()
    except (ValueError, TypeError):
        return True
    return any(p.name == "lease" or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


__all__ = ["OrderGuard"]
