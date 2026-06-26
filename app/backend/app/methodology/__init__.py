"""方法学控制面（GOAL §10）——6 档验证严格度旋钮 + 真实状态限制门。

系统**提供**给 user 运行时选的 6 档（strict/standard/loose/exploratory/custom/user_waived），
**不替用户拍**。身份/记录复用 `app.lineage.spine`（`MethodologyChoiceRecord` + 标签阶梯），
与 `spine_gate` 互补不替换：放宽档一律不得触及强标签（含 evidence_sufficient）。
"""

from __future__ import annotations

from .control_plane import (
    ALL_TIER_VALUES,
    DISCLOSURE,
    RELAXED_TIERS,
    RIGOROUS_TIERS,
    TIER_PROFILES,
    MethodologyDecision,
    MethodologyTier,
    TierProfile,
    assert_label_honest_for_export,
    build_methodology_choice,
    constrain_promotion,
    documentation_gaps,
    effective_label,
    production_eligible,
    runtime_environment_ceiling,
    tier_of,
    validate_profiles,
)

__all__ = [
    "MethodologyTier",
    "RELAXED_TIERS",
    "RIGOROUS_TIERS",
    "ALL_TIER_VALUES",
    "TierProfile",
    "TIER_PROFILES",
    "MethodologyDecision",
    "DISCLOSURE",
    "build_methodology_choice",
    "constrain_promotion",
    "effective_label",
    "assert_label_honest_for_export",
    "production_eligible",
    "runtime_environment_ceiling",
    "documentation_gaps",
    "tier_of",
    "validate_profiles",
]
