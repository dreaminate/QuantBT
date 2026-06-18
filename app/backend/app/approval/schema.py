"""审批门 schema + 异常（T-019 / spine 07 §3.2）。

把裸状态翻转升级成带审批门的状态机。三要件（晋升 staging/production 必齐）：独立验证记录 +
approver≠creator + 多证据三角快照。缺任一即拒绝并返【缺口清单】，绝不进 pending。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

GateChannel = Literal["exploratory", "confirmatory"]
ActionKind = Literal["promote_staging", "promote_production", "live_order", "transfer",
                     "leverage_up", "data_delete", "stop_loss", "risk_reduction", "add_position"]
GateDecision = Literal["pending", "approved", "rejected", "timed_out"]
TimeoutDefault = Literal["default_reject", "default_allow", "escalate"]

MONEY_ACTIONS = frozenset({"live_order", "transfer", "leverage_up", "promote_production", "add_position"})


class ApproverEqualsCreator(Exception):
    """approver == creator：防自审（R7 生成≠验证不可自我满足）。"""


class GateStateError(Exception):
    """对非法状态的门做非法转移（如 approve 一个非 pending 门）。"""


class EmptyReason(Exception):
    """confirmatory 审批理由空/纯套话（反敷衍）。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class EvidenceSnapshot:
    config_hash: str
    dataset_version: str
    n_eff: int                      # honest-N 有效试验数（不可手填改小）
    n_trials_raw: int
    dsr: float
    pbo: float
    bootstrap_ci: tuple[float, float]
    bootstrap_estimate: float = 0.0
    champion_challenger: dict[str, Any] = field(default_factory=dict)
    returns_sha256: str = ""
    triangle_aligned: bool = False
    applicability_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bootstrap_ci"] = list(self.bootstrap_ci)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "EvidenceSnapshot | None":
        if not d:
            return None
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        data = {k: v for k, v in d.items() if k in known}
        if "bootstrap_ci" in data and isinstance(data["bootstrap_ci"], list):
            data["bootstrap_ci"] = tuple(data["bootstrap_ci"])
        return cls(**data)


@dataclass
class ApprovalGate:
    gate_id: str
    model_id: str
    version: int
    from_stage: str
    to_stage: str
    channel: GateChannel
    action_kind: ActionKind
    created_by: str
    created_at_utc: str = field(default_factory=_now)
    verification_record_id: str | None = None    # (a) 独立验证官记录（部件12=T-020 产）
    approver: str | None = None                   # (b) approver != created_by（硬约束）
    evidence: dict[str, Any] | None = None        # (c) EvidenceSnapshot.to_dict()
    idempotency_key: str = ""
    sla_deadline_utc: str | None = None
    on_timeout: TimeoutDefault = "escalate"
    escalate_to: str | None = None
    decision: GateDecision = "pending"
    decision_reason: str | None = None
    risk_restated: str | None = None
    decided_at_utc: str | None = None
    gap_list: list[str] = field(default_factory=list)
    side_effect_executed: bool = False
    side_effect_ref: str | None = None
    nist_phase: str = "MEASURE"                   # R6：非合规宣称
    verdict_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ApprovalGate":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class GateRejection:
    """promote 被拒（不翻 stage）：带缺口清单返调用方。"""

    gate_id: str
    model_id: str
    version: int
    to_stage: str
    gap_list: list[str]
    decision: GateDecision = "rejected"
    verdict_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ActionKind", "ApprovalGate", "ApproverEqualsCreator", "EmptyReason", "EvidenceSnapshot",
    "GateChannel", "GateDecision", "GateRejection", "GateStateError", "MONEY_ACTIONS", "TimeoutDefault",
]
