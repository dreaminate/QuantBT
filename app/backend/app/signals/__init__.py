"""M7 · 信号融合：方向 / 幅度 / 置信度 / 风险状态四元组。"""

from __future__ import annotations

from .core import (
    FactorAttribution,
    Signal,
    SignalDirection,
    apply_regime_gating,
    calibrate_confidence,
    confidence_threshold_filter,
    conformal_abstain_gate,
    fuse_signals,
)

__all__ = [
    "FactorAttribution",
    "Signal",
    "SignalDirection",
    "apply_regime_gating",
    "calibrate_confidence",
    "confidence_threshold_filter",
    "conformal_abstain_gate",
    "fuse_signals",
]
