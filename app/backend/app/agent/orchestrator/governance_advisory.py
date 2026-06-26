"""§8 治理脊柱硬不变量门 → Agent Orchestrator 的 advisory 接线。

`app/governance/spine_invariants.py` 提供的 `GovernanceSpineGate` 聚合 GOAL §8 七条硬不变量。
本模块把它接到 orchestrator 的 Review 形态：调用方显式构造 `SpineEvidence`，本层委派门裁定，
再投影一枚可见事件并返回结构化 `GovernanceAdvisory`。

advisory-first：
- 七条硬不变量违反只标记 `flagged = not verdict.allowed`，不阻断现有 plan / dispatch / replay / repair。
- 判定零重写：裁决全权委派 `GovernanceSpineGate.evaluate`。
- 事件和 `to_dict()` 只暴露 clause id、bool 和计数；不暴露 evidence surface、verdict_text、violation 文本。

secret 命门：
- 当前 `GovernanceSpineGate.evaluate` 对 secret 违反返回 `SpineVerdict(allowed=False)`，不 raise。
- 若未来底层 fail-closed 抛出 `SecretLeakError`，本层不吞，投 `FailureDetected` 且只投不变量名后原样 re-raise。

本层不从 role agent 自由文本抽取 §8 evidence；free-text → `SpineEvidence` 是上游另卡。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...governance import (
    GovernanceSpineGate,
    INV_SECRET_PLAINTEXT,
    SpineEvidence,
    SpineVerdict,
)
from ...llm.call_record import SecretLeakError
from .events import (
    EV_FAILURE_DETECTED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EventProjector,
    WorkflowEvent,
)
from .roles import ROLE_VERIFIER, UnknownRoleError, get_role

GOVERNANCE_ADVISORY_SOURCE = "governance_advisory_s8"

__all__ = [
    "GOVERNANCE_ADVISORY_SOURCE",
    "GovernanceAdvisory",
    "summarize_governance_for_event",
    "run_governance_advisory",
]


@dataclass
class GovernanceAdvisory:
    """一条 §8 治理脊柱 advisory 裁决结果。"""

    verdict: SpineVerdict
    flagged: bool
    event: WorkflowEvent
    role: str = ""
    node_ref: str = ""
    advisory: bool = field(default=True)

    @property
    def allowed(self) -> bool:
        return self.verdict.allowed

    @property
    def violated_clauses(self) -> tuple[str, ...]:
        return tuple(c.clause for c in self.verdict.clauses if c.checked and not c.passed)

    @property
    def checked_clauses(self) -> tuple[str, ...]:
        return self.verdict.checked_clauses

    @property
    def skipped_clauses(self) -> tuple[str, ...]:
        return self.verdict.skipped_clauses

    @property
    def verdict_text(self) -> str:
        """完整裁决文仅供进程内读详，不进入事件或序列化面。"""

        return self.verdict.verdict_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisory": self.advisory,
            "flagged": self.flagged,
            "role": self.role,
            "node_ref": self.node_ref,
            "allowed": self.verdict.allowed,
            "violated_clauses": list(self.violated_clauses),
            "checked_clauses": list(self.verdict.checked_clauses),
            "skipped_clauses": list(self.verdict.skipped_clauses),
            "event_kind": self.event.kind,
        }


def summarize_governance_for_event(verdict: SpineVerdict, *, node_ref: str = "") -> dict[str, Any]:
    """把治理脊柱裁决摘成可见事件 data。

    只投结构化 token，避免把 evidence surface、verdict_text、violation/matched 文本塞进事件流。
    """

    violated = [c.clause for c in verdict.clauses if c.checked and not c.passed]
    return {
        "challenge_source": GOVERNANCE_ADVISORY_SOURCE,
        "advisory": True,
        "flagged": not verdict.allowed,
        "allowed": verdict.allowed,
        "violated_clauses": violated,
        "checked_clauses": list(verdict.checked_clauses),
        "skipped_clauses": list(verdict.skipped_clauses),
        "n_checked": len(verdict.checked_clauses),
        "n_violated": len(violated),
        "node_ref": node_ref,
    }


def _role_desk(role: str) -> str:
    try:
        return get_role(role).home_desk
    except UnknownRoleError:
        return ""


def run_governance_advisory(
    evidence: SpineEvidence,
    projector: EventProjector,
    *,
    gate: GovernanceSpineGate | None = None,
    role: str = ROLE_VERIFIER,
    node_id: str = "",
    node_ref: str = "",
) -> GovernanceAdvisory:
    """对一包 `SpineEvidence` 跑治理脊柱 advisory。"""

    gate = gate if gate is not None else GovernanceSpineGate()
    desk = _role_desk(role)
    try:
        verdict = gate.evaluate(evidence)
    except SecretLeakError:
        projector.emit(
            EV_FAILURE_DETECTED,
            {
                "reason": "secret_plaintext_hard_stop",
                "refused_invariants": [INV_SECRET_PLAINTEXT],
                "advisory": False,
                "challenge_source": GOVERNANCE_ADVISORY_SOURCE,
            },
            role=role,
            desk=desk,
            node_id=node_id,
        )
        raise

    event = projector.emit(
        EV_VERIFIER_CHALLENGE_RAISED,
        summarize_governance_for_event(verdict, node_ref=node_ref),
        role=role,
        desk=desk,
        node_id=node_id,
    )
    return GovernanceAdvisory(
        verdict=verdict,
        flagged=not verdict.allowed,
        event=event,
        role=role,
        node_ref=node_ref,
    )
