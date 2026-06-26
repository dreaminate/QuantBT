"""治理脊柱（Governance Spine · GOAL §8）——§8 硬不变量统一核查门所在包。

本包**只**装 §8「治理脊柱」七条硬不变量的**统一聚合核查门**（`spine_invariants`）。它收编只读
各已建 enforcement（A-CMD / Orchestrator / EventProjector / call_record / keystore / credential_pool），
把分散的 §8 判定聚合成一道可证伪总门——任一硬不变量违反 → 拒。

注意命名：本包是 §8 **治理脊柱**（agent / canvas / secret / event 一脉），与 §6 **数学脊柱**
（`lineage/spine*`：TheoryClaim⇒MathematicalArtifact / TIB⇒ConsistencyCheck）是两条不同的脊柱，
互不重造；§8 里数学一脉、approver≠creator、LLMCallRecord 必填等由各自已建门 enforce（详见
`spine_invariants` 模块 docstring 的范围说明）。
"""

from __future__ import annotations

from .spine_invariants import (
    CLAUSES,
    ENFORCEMENT_BINDINGS,
    INV_AGENT_ACTION,
    INV_AGENT_CODE_CHANGE,
    INV_AGENT_DATA_ACCESS,
    INV_AGENT_PLAN,
    INV_CANVAS_MUTATION,
    INV_ROLE_AGENT_ACTION,
    INV_SECRET_PLAINTEXT,
    AgentActionEvidence,
    CodeChangeEvidence,
    ClauseResult,
    DataAccessEvidence,
    EnforcementBinding,
    GovernanceSpineGate,
    GovernanceSpineViolation,
    RoleActionEvidence,
    SecretSurfaceEvidence,
    SpineEvidence,
    SpineVerdict,
    check_agent_action,
    check_agent_code_change,
    check_agent_data_access,
    check_agent_plan,
    check_canvas_mutation,
    check_role_agent_action,
    check_secret_plaintext,
)

__all__ = [
    "CLAUSES",
    "ENFORCEMENT_BINDINGS",
    "INV_AGENT_ACTION",
    "INV_AGENT_CODE_CHANGE",
    "INV_AGENT_DATA_ACCESS",
    "INV_AGENT_PLAN",
    "INV_CANVAS_MUTATION",
    "INV_ROLE_AGENT_ACTION",
    "INV_SECRET_PLAINTEXT",
    "AgentActionEvidence",
    "CodeChangeEvidence",
    "ClauseResult",
    "DataAccessEvidence",
    "EnforcementBinding",
    "GovernanceSpineGate",
    "GovernanceSpineViolation",
    "RoleActionEvidence",
    "SecretSurfaceEvidence",
    "SpineEvidence",
    "SpineVerdict",
    "check_agent_action",
    "check_agent_code_change",
    "check_agent_data_access",
    "check_agent_plan",
    "check_canvas_mutation",
    "check_role_agent_action",
    "check_secret_plaintext",
]
