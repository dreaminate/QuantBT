"""§13 信任层硬约束门 → Agent Orchestrator 的 **advisory** 接线（GOAL §13 信任层 + §7 Review 形态）。

第八波建的 `app/trust/`（trust_constraints 反谄媚 / 诚实硬约束 / 弱点一等呈现 / waiver-safety 命门）
此前未接 orchestrator —— agent 产出（研究结论 / 推荐 / review）没经 §13 检查。本模块把 trust 门作
**advisory** 接进 orchestrator 的 Review 路径：把一条 `TrustContext`（描述待审产出的 §13 姿态）交给
trust 门裁定，裁决经一枚可见事件投影 + attach 进结构化 `TrustAdvisory` 结果。

advisory-first（本波纪律）：
- 诚实 / 反谄媚 / 弱点披露 / 责任 / 用户自主等**软门**：只**标记**（`flagged = not ok`）+ 投影
  `VerifierChallengeRaised`，**绝不阻断** orchestrator 主流程（不 raise·不改既有 DAG / dispatch 行为）。
  硬卡 agent = 后续显式决策（本波非目标）。
- **判定零重写**：全部委派 `app.trust.evaluate_trust`（reuse·不重造任何裁定逻辑）。本层只接线 + 投影。

命门例外（**不在此削弱**·复用 trust 命门）：
- §13 命门「secret / OrderGuard / kill switch / no-silent-mock 绝不被 waiver 绕过」是 fail-closed 硬墙。
  若待审产出路径带 waiver 触及安全不变量，`evaluate_trust` 内部 `raise SafetyWaiverError` —— 本层**不吞**
  这个异常（吞掉 = 把硬墙降级成 advisory = 削弱命门）。投影一枚 `FailureDetected`（**只投不变量名·不投
  原始 target 文本**，免回显 user 自由文本 / 潜在 secret）后**原样 re-raise**。安全不变量不在 advisory 域。

诚实限界（本层**不**做什么）：
- **不**从 role agent 的自由文本产出里自动抽取 §13 姿态（那需脆弱启发式 + 有越权重判风险）。本层吃的是
  调用方（Review-form agent / 后续 main.py 接线）显式构造的结构化 `TrustContext`。free-text → TrustContext
  的映射是上游的事，不在本卡（诚实残余·上报中心）。
- **不**接 main.py（中心 / 下游另卡）；**不**碰 trust/ 门内部 / GovernedToolDispatcher（与 §13 无关）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...trust import (
    SafetyWaiverError,
    TrustContext,
    TrustValidation,
    evaluate_trust,
)
from .events import (
    EV_FAILURE_DETECTED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EventProjector,
    WorkflowEvent,
)
from .roles import ROLE_VERIFIER, UnknownRoleError, get_role

# 事件 data 里给 §13 advisory 裁决打的来源标签 —— 与 admit_verifier_challenge（独立性挑战）同走
# VerifierChallengeRaised，但 `challenge_source` 区分两类挑战（内容诚实 vs 结构独立性）。
TRUST_ADVISORY_SOURCE = "trust_advisory_s13"

__all__ = [
    "TRUST_ADVISORY_SOURCE",
    "TrustAdvisory",
    "summarize_trust_for_event",
    "safety_bypass_invariants",
    "run_trust_advisory",
]


@dataclass
class TrustAdvisory:
    """一条 §13 信任层 advisory 裁决结果（Review 形态产物）。

    `validation`：完整 trust 裁决（**零重写**·全委派 `evaluate_trust`）。`flagged`：advisory 标记位
    （= `not validation.ok`）—— advisory-first 只标记不阻断，调用方据此决定是否在 UI 高亮 / 请 user 复核。
    `event`：投影出的 `VerifierChallengeRaised` 可见事件（已过可见性边界）。
    """

    validation: TrustValidation
    flagged: bool
    event: WorkflowEvent
    role: str = ""
    target_ref: str = ""
    advisory: bool = field(default=True)  # 永真：本结果是 advisory（软标记·非硬拦）。

    @property
    def ok(self) -> bool:
        return self.validation.ok

    @property
    def violation_codes(self) -> tuple[str, ...]:
        return self.validation.violation_codes

    @property
    def rejected_gate_ids(self) -> tuple[str, ...]:
        return tuple(d.gate_id for d in self.validation.rejections)

    @property
    def reason_text(self) -> str:
        return self.validation.reason_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisory": self.advisory,
            "flagged": self.flagged,
            "role": self.role,
            "target_ref": self.target_ref,
            "validation": self.validation.to_dict(),
            "event_kind": self.event.kind,
        }


def summarize_trust_for_event(validation: TrustValidation, *, target_ref: str = "") -> dict[str, Any]:
    """把 trust 裁决摘成**可见事件 data**（GOAL §7 可见性边界友好）。

    只投**结构化 token**（violation_codes / gate_ids / 计数 / 布尔）+ 调用方给的 target_ref —— 绝不把门的
    自由文本 verdict / user_pressure 原文塞进可见事件（事件流保持精简且不回显 user 自由文本）。完整
    verdict 文本仍在 `TrustAdvisory.validation` 里供调用方 attach。
    """

    return {
        "challenge_source": TRUST_ADVISORY_SOURCE,
        "advisory": True,
        "flagged": not validation.ok,
        "ok": validation.ok,
        "violation_codes": list(validation.violation_codes),
        "rejected_gates": [d.gate_id for d in validation.rejections],
        "n_decisions": len(validation.decisions),
        "waiver_safety_ok": validation.waiver_safety.ok,
        "permitted_waivers": len(validation.waiver_safety.permitted_targets),
        "target_ref": target_ref,
    }


def safety_bypass_invariants(exc: SafetyWaiverError) -> list[str]:
    """从命门异常里抽**去重排序的安全不变量名**（secret / order_guard / kill_switch / no_silent_mock）。

    刻意**只**返不变量名、**不**返原始 waiver target 文本 —— 那是 user/agent 自由文本，可能夹带 secret，
    不进可见事件（命门触发也守可见性边界）。
    """

    return sorted({inv for _target, inv in exc.decision.refused_safety_targets})


def _role_desk(role: str) -> str:
    try:
        return get_role(role).home_desk
    except UnknownRoleError:
        return ""


def run_trust_advisory(
    ctx: TrustContext,
    projector: EventProjector,
    *,
    role: str = ROLE_VERIFIER,
    node_id: str = "",
    target_ref: str = "",
) -> TrustAdvisory:
    """对一条待审产出（`ctx` 描述其 §13 姿态）跑信任层 advisory（核心接线·纯函数·与 orchestrator 解耦）。

    流程：`evaluate_trust(ctx)` 全权裁定 → 软门只标记 + 投影 `VerifierChallengeRaised` + 返 `TrustAdvisory`。
    命门（waiver 触安全不变量）：`evaluate_trust` raise `SafetyWaiverError` → 投影 `FailureDetected`
    （只投不变量名）后**原样 re-raise**（不削弱·不吞）。
    """

    desk = _role_desk(role)
    try:
        validation = evaluate_trust(ctx)
    except SafetyWaiverError as exc:
        # 命门 fail-closed（§13）：不吞·不降级成 advisory。投影后 re-raise。
        projector.emit(
            EV_FAILURE_DETECTED,
            {
                "reason": "safety_waiver_bypass",
                "refused_invariants": safety_bypass_invariants(exc),
                "advisory": False,  # 命门是硬拒·非 advisory（安全不变量不在可弃权域）。
                "challenge_source": TRUST_ADVISORY_SOURCE,
            },
            role=role,
            desk=desk,
            node_id=node_id,
        )
        raise

    event = projector.emit(
        EV_VERIFIER_CHALLENGE_RAISED,
        summarize_trust_for_event(validation, target_ref=target_ref),
        role=role,
        desk=desk,
        node_id=node_id,
    )
    return TrustAdvisory(
        validation=validation,
        flagged=not validation.ok,
        event=event,
        role=role,
        target_ref=target_ref,
    )
