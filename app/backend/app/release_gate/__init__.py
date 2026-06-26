"""发版门禁套件 · §16 工程标准作不可绕的 release gate（GOAL §16 + §0 · 卡 D-RELEASE-GATE）。

晋级/发版前，把 GOAL §16「工程标准」逐条核成硬门——任一缺 → 拒发版。本包【不重造】已建门，
而是把它们【收编只读·聚合】成单一 release gate（spine 一致性 / LLM 准入 / dataset 版本 / RDP /
Verifier / Approval），再补一条全仓原无的 §16 Mock 诚实门（no silent mock fallback / no template
false success）。

单一源（RULES §1）：一致性判定走 `lineage.spine_gate.evaluate_promotion`、LLMCallRecord 必填走
`llm.call_record.REQUIRED_FIELDS`、§17 走 `delivery.rdp_gate.validate_rdp`——本包只聚合不另造。

诚实边界：本包只核查【声明的治理工件是否齐全自洽】，不在 main.py 接发版编排（中心/下游另卡）。
"""

from __future__ import annotations

from .mock_honesty import (
    EXECUTION_MODES,
    GRADE_DRAFT,
    GRADE_EXPLORATORY,
    GRADE_NONE,
    GRADE_PAPER,
    GRADE_PRODUCTION,
    MODE_FALLBACK,
    MODE_LIVE,
    MODE_MOCK,
    MODE_TEMPLATE,
    RESULT_GRADES,
    BlockViolation,
    ExecutionBlock,
    MockHonestyError,
    check_execution_block,
    check_execution_blocks,
)
from .release_gate import (
    GATE_APPROVAL,
    GATE_DATASET_VERSION,
    GATE_LLM_GATEWAY,
    GATE_METHODOLOGY_CHOICE,
    GATE_MOCK_HONESTY,
    GATE_RDP,
    GATE_SPINE_CONSISTENCY,
    GATE_VERIFIER,
    USER_WAIVED_LABELS,
    ReleaseCandidate,
    ReleaseGateOutcome,
    ReleaseRejected,
    ReleaseValidation,
    collect_honest_gaps,
    evaluate_release,
    gate_approval,
    gate_dataset_version,
    gate_llm_gateway,
    gate_methodology_choice,
    gate_mock_honesty,
    gate_rdp,
    gate_spine_consistency,
    gate_verifier,
    require_releasable,
)

__all__ = [
    # mock_honesty
    "EXECUTION_MODES",
    "RESULT_GRADES",
    "MODE_LIVE",
    "MODE_MOCK",
    "MODE_FALLBACK",
    "MODE_TEMPLATE",
    "GRADE_PRODUCTION",
    "GRADE_PAPER",
    "GRADE_EXPLORATORY",
    "GRADE_DRAFT",
    "GRADE_NONE",
    "ExecutionBlock",
    "BlockViolation",
    "MockHonestyError",
    "check_execution_block",
    "check_execution_blocks",
    # release_gate
    "GATE_MOCK_HONESTY",
    "GATE_DATASET_VERSION",
    "GATE_SPINE_CONSISTENCY",
    "GATE_METHODOLOGY_CHOICE",
    "GATE_LLM_GATEWAY",
    "GATE_VERIFIER",
    "GATE_APPROVAL",
    "GATE_RDP",
    "USER_WAIVED_LABELS",
    "ReleaseGateOutcome",
    "ReleaseValidation",
    "ReleaseRejected",
    "ReleaseCandidate",
    "gate_mock_honesty",
    "gate_dataset_version",
    "gate_spine_consistency",
    "gate_methodology_choice",
    "gate_llm_gateway",
    "gate_verifier",
    "gate_approval",
    "gate_rdp",
    "collect_honest_gaps",
    "evaluate_release",
    "require_releasable",
]
