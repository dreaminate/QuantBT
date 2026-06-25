"""Agent Orchestrator · Plan 形态产物 + 完成/代码改动/方法学的可证伪门（GOAL §7）。

GOAL §7 Plan 形态产出：todo / dependencies / risk list / acceptance gates / cross-desk handoff plan /
rollback points。以及若干可证伪验收：

- AgentPlan 缺 todo / dependencies / acceptance gates → **保持 draft**（不是拒——是不准晋升为可执行）。
- Agent 声称完成但工具记录缺失 → **拒**。
- AgentCodeChange 缺 diff / test result / rollback point → **拒**。
- Agent 替 user 拍板方法学松紧 → **拒**（只记 MethodologyChoiceRecord·决定权属 user）。

本模块只放这些**数据 + 门**，不碰调度（在 orchestrator.py）。每个门配「种坏门必抓」的单测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...qro.envelope import (
    ACTOR_AGENT,
    ACTOR_CLASSES,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_USER_CONFIRMED_AGENT,
    ACTOR_USER_MANUAL,
)

PLAN_DRAFT = "draft"
PLAN_READY = "ready"


class PlanError(RuntimeError):
    pass


class AgentCodeChangeError(RuntimeError):
    """AgentCodeChange 缺 diff / test result / rollback point → 拒（GOAL §7）。"""


class AgentCompletionError(RuntimeError):
    """Agent 声称完成但工具记录缺失 → 拒（GOAL §7）。"""


class MethodologyAutonomyError(RuntimeError):
    """Agent 替 user 拍板方法学松紧 → 拒（GOAL §7：只记 MethodologyChoiceRecord，决定权属 user）。"""


@dataclass(frozen=True)
class AgentTodo:
    todo_id: str
    description: str
    role: str
    deps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.todo_id or not self.description or not self.role:
            raise PlanError("AgentTodo 需 todo_id / description / role 三者非空")


@dataclass(frozen=True)
class AcceptanceGate:
    gate_id: str
    description: str
    falsifiable_check: str   # 该 gate 怎么被证伪（GOAL：可证伪验收·非空）

    def __post_init__(self) -> None:
        if not self.gate_id or not self.description or not self.falsifiable_check:
            raise PlanError("AcceptanceGate 需 gate_id / description / falsifiable_check 三者非空")


@dataclass
class AgentPlan:
    """Plan 形态产物（GOAL §7）。缺 todo/dependencies/acceptance gates → status 维持 draft。

    `dependencies` 是 todo 间的依赖边（todo_id → 依赖的 todo_id 列表）；这套依赖就是后续冻结成
    deterministic DAG 的边（orchestrator 据此建 DAGTask.deps）。`status` 只有过 `validate()` 且齐全
    才可能是 ready——晋升为可执行（dispatch）只认 ready。
    """

    goal: str
    todos: list[AgentTodo] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    risk_list: list[str] = field(default_factory=list)
    acceptance_gates: list[AcceptanceGate] = field(default_factory=list)
    cross_desk_handoff_plan: list[dict[str, Any]] = field(default_factory=list)
    rollback_points: list[str] = field(default_factory=list)
    status: str = PLAN_DRAFT
    draft_reason: str = ""

    def validate(self) -> "AgentPlan":
        """GOAL §7：缺 todo / dependencies / acceptance gates → 保持 draft（不抛·不晋升）。

        注：`dependencies` 视为「依赖关系已被显式声明」——空 todo 谈不上依赖，故空 todos 直接 draft；
        有 todos 但 `dependencies` 未声明（连「无依赖」都没显式给）→ draft。risk_list / rollback_points
        缺失记进 draft_reason 但**不**单独压成 draft（GOAL §7 只点名 todo/deps/gates 三者为晋升前提）。
        """

        missing: list[str] = []
        if not self.todos:
            missing.append("todo")
        if not self.dependencies:
            missing.append("dependencies")
        if not self.acceptance_gates:
            missing.append("acceptance_gates")
        # 依赖必须指向真实 todo（悬空依赖 = 计划不自洽 → draft）。
        todo_ids = {t.todo_id for t in self.todos}
        dangling = sorted(
            {d for deps in self.dependencies.values() for d in deps if d not in todo_ids}
            | {k for k in self.dependencies if k not in todo_ids}
        )
        if dangling:
            missing.append(f"dangling_deps={dangling}")
        if missing:
            self.status = PLAN_DRAFT
            self.draft_reason = f"缺 {missing}——AgentPlan 保持 draft（GOAL §7），不晋升为可执行"
        else:
            self.status = PLAN_READY
            self.draft_reason = ""
        return self

    @property
    def is_ready(self) -> bool:
        return self.status == PLAN_READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "todos": [t.__dict__ for t in self.todos],
            "dependencies": self.dependencies,
            "risk_list": self.risk_list,
            "acceptance_gates": [g.__dict__ for g in self.acceptance_gates],
            "cross_desk_handoff_plan": self.cross_desk_handoff_plan,
            "rollback_points": self.rollback_points,
            "status": self.status,
            "draft_reason": self.draft_reason,
        }


@dataclass(frozen=True)
class AgentCodeChange:
    """Repair / 代码工程产物（GOAL §7）：缺 diff / test result / rollback point → 拒（构造期即拦）。"""

    path: str
    diff: str
    test_result: str
    rollback_point: str
    theory_implementation_binding: str = ""   # 声称按理论实现却缺 TIB → 另由 orchestrator 判（见下）
    claims_theory_backed: bool = False

    def __post_init__(self) -> None:
        missing = [
            name for name, val in (
                ("diff", self.diff),
                ("test_result", self.test_result),
                ("rollback_point", self.rollback_point),
            )
            if not str(val or "").strip()
        ]
        if missing:
            raise AgentCodeChangeError(
                f"AgentCodeChange 缺 {missing}——GOAL §7：代码改动必须带 diff / test result / rollback point → 拒"
            )
        # GOAL §7：声称按理论实现却缺 TheoryImplementationBinding → 拒。
        if self.claims_theory_backed and not str(self.theory_implementation_binding or "").strip():
            raise AgentCodeChangeError(
                "AgentCodeChange 声称按理论实现却缺 TheoryImplementationBinding——GOAL §7 → 拒"
            )


@dataclass(frozen=True)
class AgentCompletion:
    """Agent 完成声明（GOAL §7：声称完成但工具记录缺失 → 拒）。

    `requires_tool_evidence` 默认 True：大多数 role 完成须有工具证据（读资产/跑验证/产物）。
    纯对话类（如简单澄清）可显式 False——但那时 claims_complete 也不该附带「已执行」语义。
    """

    role: str
    claims_complete: bool
    tool_records: tuple[str, ...] = ()
    requires_tool_evidence: bool = True

    def __post_init__(self) -> None:
        if self.claims_complete and self.requires_tool_evidence and not self.tool_records:
            raise AgentCompletionError(
                f"role {self.role!r} 声称完成但工具记录缺失——GOAL §7：声称完成但工具记录缺失 → 拒"
            )


# —— 方法学放权：决定权属 user（GOAL §7：Agent 替 user 拍板方法学松紧 → 拒）——

# 谁可拍板方法学松紧：只有 user 本人手动 / user 显式确认过的 agent 动作；纯 agent / 调度 agent 不行。
_METHODOLOGY_DECIDERS: frozenset[str] = frozenset({ACTOR_USER_MANUAL, ACTOR_USER_CONFIRMED_AGENT})
_METHODOLOGY_FORBIDDEN: frozenset[str] = frozenset({ACTOR_AGENT, ACTOR_SCHEDULED_AGENT})


@dataclass(frozen=True)
class MethodologyChoiceRecord:
    """方法学放权记录（GOAL §7 / §1 MethodologyChoiceRecord）——展示代价 + 推荐路径 + 责任边界。

    `decided_by` ∈ 四类 actor；`apply` 时若是 agent/scheduled_agent 自己拍 → 拒（决定权属 user）。
    Agent 的本分：填 cost / recommended_path / responsibility_boundary，把决定权留给 user。
    """

    choice: str                       # 要松哪条方法学（如「跳过严格数学证明」「放松 PBO 阈值」）
    cost: str                         # 代价（GOAL §7：展示代价）
    recommended_path: str             # 推荐路径
    responsibility_boundary: str      # 责任边界
    decided_by: str = ACTOR_AGENT     # 谁拍的（默认 agent 提出·未决）
    decision: str = "pending"         # pending / accepted / rejected

    def __post_init__(self) -> None:
        if self.decided_by not in ACTOR_CLASSES:
            raise MethodologyAutonomyError(
                f"MethodologyChoiceRecord.decided_by 非四类 actor：{self.decided_by!r}"
            )
        if not (self.choice and self.cost and self.recommended_path and self.responsibility_boundary):
            raise PlanError(
                "MethodologyChoiceRecord 需 choice / cost / recommended_path / responsibility_boundary 全非空"
                "（GOAL §7：Agent 展示代价 / 推荐路径 / 责任边界）"
            )


def assert_methodology_user_decided(record: MethodologyChoiceRecord) -> None:
    """方法学放权的执行门（GOAL §7：Agent 替 user 拍板方法学松紧 → 拒）。

    只有 user 手动 / user 确认过的 agent 动作可 accept 一条方法学松紧；纯 agent / 调度 agent 自拍 → 拒。
    种坏门必抓：把 decided_by 置 `agent` 且 decision=`accepted` 拿来执行 → 此门必抛。
    """

    if record.decision == "accepted" and record.decided_by not in _METHODOLOGY_DECIDERS:
        raise MethodologyAutonomyError(
            f"方法学松紧由 {record.decided_by!r} 拍板——GOAL §7：Agent 替 user 拍板方法学松紧 → 拒。"
            "Agent 只能记 MethodologyChoiceRecord（代价/推荐/责任边界）并请 user 拍板。"
        )
    if record.decided_by in _METHODOLOGY_FORBIDDEN and record.decision != "pending":
        raise MethodologyAutonomyError(
            f"{record.decided_by!r} 不能给方法学松紧下 {record.decision!r} 终裁——决定权属 user（GOAL §7）"
        )


__all__ = [
    "PLAN_DRAFT",
    "PLAN_READY",
    "PlanError",
    "AgentCodeChangeError",
    "AgentCompletionError",
    "MethodologyAutonomyError",
    "AgentTodo",
    "AcceptanceGate",
    "AgentPlan",
    "AgentCodeChange",
    "AgentCompletion",
    "MethodologyChoiceRecord",
    "assert_methodology_user_decided",
]
