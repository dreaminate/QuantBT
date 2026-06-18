"""Agent OS 脊柱 04 · 可证伪假设卡 + 预注册 + confirmatory/exploratory（T-017，P2 不挡探索）。"""

from __future__ import annotations

from .card import CardFrozenError, CardTamperError, HypothesisCard, compute_content_hash
from .falsifiability import FalsifiabilityVerdict, assess_falsifiability
from .gate import GateDecision, can_touch_final_oos
from .lineage_hook import LineageHook
from .store import FreezeRejected, HypothesisCardStore, PromoteRejected

__all__ = [
    "CardFrozenError",
    "CardTamperError",
    "FalsifiabilityVerdict",
    "FreezeRejected",
    "GateDecision",
    "HypothesisCard",
    "HypothesisCardStore",
    "LineageHook",
    "PromoteRejected",
    "assess_falsifiability",
    "can_touch_final_oos",
    "compute_content_hash",
]
