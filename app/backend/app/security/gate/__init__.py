"""Agent OS 脊柱 06 · 安全门 deny-by-default + 交易所侧硬墙（T-018）。

脊柱里唯一一道「动真钱/不可逆/外部可见」的硬墙。5 不变量：Rule-of-Two / deny-by-default 策略门接全
所有执行路径(M17) / 密钥永不进 LLM(JIT broker) / 防重放 nonce / 分级威胁模型 + 交易所侧真硬墙。
"""

from __future__ import annotations

from .account_halt import (
    AccountHaltBatch,
    AccountHaltEvidence,
    AccountHaltError,
    AccountHaltSnapshot,
    PersistentAccountHaltBarrier,
)
from .broker import CapabilityToken, KeyBroker, Lease
from .enforcer import OrderGuard
from .ingest import Attestation, IngestResult, isolated_ingest, sanity_check
from .nonce import NonceLedger
from .policy import (
    TCB_DISCLOSURE,
    OrderGated,
    PolicyDecision,
    PolicyGate,
    TrustTier,
    classify,
    evaluate,
    gate_hash,
)

__all__ = [
    "Attestation",
    "AccountHaltBatch",
    "AccountHaltEvidence",
    "AccountHaltError",
    "AccountHaltSnapshot",
    "CapabilityToken",
    "IngestResult",
    "KeyBroker",
    "Lease",
    "NonceLedger",
    "OrderGated",
    "OrderGuard",
    "PolicyDecision",
    "PolicyGate",
    "PersistentAccountHaltBarrier",
    "TCB_DISCLOSURE",
    "TrustTier",
    "classify",
    "evaluate",
    "gate_hash",
    "isolated_ingest",
    "sanity_check",
]
