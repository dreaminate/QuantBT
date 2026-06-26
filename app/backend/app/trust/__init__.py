"""§13 信任层硬约束门（greenfield）—— 目标是【恰当依赖】(R24)，不是信任最大化。

GOAL §13 的诚实契约落成可核查的后端硬门，四块增量（收编只读已建件·不重造）：
  ① 诚实硬约束门  不伪造 proof_backed/evidence_sufficient/production_ready·不冒充理论↔实现一致·
                  单人模式不声明组织独立（强标签真假【委派】spine_gate/methodology 裁定·本层只核声明↔裁定一致）。
  ② waiver-safety 边界门 = 命门  不得让 secret/OrderGuard/kill switch/no-silent-mock 被 waiver 绕过
                  （fail-closed·撞即 raise SafetyWaiverError）。user 可为研究松紧自负其责，安全不变量不可弃权。
  ③ 反谄媚门      不顺从 user wishful thinking 输出强结论；遇稳赢/越级实盘/忽略成本/N/泄露 → 给缺口+证据+下一步。
  ④ 弱点一等呈现门 风险/缺口/弱点默认可见绝不淡化隐藏（R25）+ 不隐藏 user waiver。

外加：ResponsibilityDisclosureRecord（user 承担风险留痕·责任边界披露）、用户自主门（不替 user 拍板）。

身份单一源（S4）：复用 `lineage.ids` / `lineage.spine.MethodologyChoiceRecord` / `methodology` / `spine_gate`，
绝不另造。不接 main.py（接线是中心/下游另卡）。
"""

from __future__ import annotations

from .responsibility import ResponsibilityDisclosureRecord
from .trust_constraints import (
    AGENT_DECIDED_FOR_USER,
    ANTI_SYC_DISCLOSURE,
    CONCLUSION_STRENGTHS,
    FAKE_CONSISTENCY,
    FAKE_ORG_INDEPENDENCE,
    FAKE_STRONG_LABEL,
    INCOMPLETE_RESPONSIBILITY,
    INV_KILL_SWITCH,
    INV_NO_SILENT_MOCK,
    INV_ORDER_GUARD,
    INV_SECRET,
    MISSING_RESPONSIBILITY,
    SAFETY_INVARIANTS,
    SAFETY_WAIVER_BYPASS,
    STRENGTH_EXPLORATORY,
    STRENGTH_STRONG,
    STRENGTH_TENTATIVE,
    SYCOPHANTIC_STRONG_CONCLUSION,
    WAIVER_HIDDEN,
    WAIVER_SAFETY_DISCLOSURE,
    WEAKNESS_HIDDEN,
    AgentConclusion,
    AntiSycophancyDecision,
    DisclosureManifest,
    SafetyWaiverError,
    TrustClaim,
    TrustContext,
    TrustDecision,
    TrustRejected,
    TrustValidation,
    TrustViolation,
    WaiverRequest,
    WaiverSafetyDecision,
    assert_safety_invariants_intact,
    check_anti_sycophancy,
    check_honesty_constraints,
    check_responsibility,
    check_user_autonomy,
    check_weakness_disclosure,
    collect_waived_targets,
    evaluate_trust,
    evaluate_waiver_safety,
    gate_anti_sycophancy,
    gate_waiver_safety,
    map_target_to_safety_invariant,
    require_trustworthy,
)

__all__ = [
    "ResponsibilityDisclosureRecord",
    # 安全不变量 / 命门
    "INV_SECRET",
    "INV_ORDER_GUARD",
    "INV_KILL_SWITCH",
    "INV_NO_SILENT_MOCK",
    "SAFETY_INVARIANTS",
    "WAIVER_SAFETY_DISCLOSURE",
    "map_target_to_safety_invariant",
    "WaiverRequest",
    "WaiverSafetyDecision",
    "SafetyWaiverError",
    "collect_waived_targets",
    "evaluate_waiver_safety",
    "assert_safety_invariants_intact",
    "gate_waiver_safety",
    # 反谄媚
    "STRENGTH_STRONG",
    "STRENGTH_TENTATIVE",
    "STRENGTH_EXPLORATORY",
    "CONCLUSION_STRENGTHS",
    "ANTI_SYC_DISCLOSURE",
    "AgentConclusion",
    "AntiSycophancyDecision",
    "check_anti_sycophancy",
    "gate_anti_sycophancy",
    # 弱点披露
    "DisclosureManifest",
    "check_weakness_disclosure",
    # 诚实硬约束
    "TrustClaim",
    "check_honesty_constraints",
    # 用户自主 / 责任
    "check_user_autonomy",
    "check_responsibility",
    # 违规码
    "FAKE_STRONG_LABEL",
    "FAKE_CONSISTENCY",
    "FAKE_ORG_INDEPENDENCE",
    "WEAKNESS_HIDDEN",
    "WAIVER_HIDDEN",
    "AGENT_DECIDED_FOR_USER",
    "MISSING_RESPONSIBILITY",
    "INCOMPLETE_RESPONSIBILITY",
    "SAFETY_WAIVER_BYPASS",
    "SYCOPHANTIC_STRONG_CONCLUSION",
    # 通用裁定结构 + 聚合
    "TrustViolation",
    "TrustDecision",
    "TrustValidation",
    "TrustRejected",
    "TrustContext",
    "evaluate_trust",
    "require_trustworthy",
]
