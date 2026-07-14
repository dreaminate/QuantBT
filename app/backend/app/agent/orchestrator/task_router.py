"""Server-derived production task routing for the Agent Orchestrator.

The client supplies research text and optional desk/asset context, never an
authoritative role.  This module maps those inputs through a controlled,
deterministic vocabulary into the existing 12-role registry and emits a DAG
shape.  It does not call an LLM and does not claim semantic certainty: unclear
requests stay with the coordinator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ...graph.research_graph import (
    DESK_BACKTEST,
    DESK_DATA,
    DESK_EXECUTION,
    DESK_FACTOR,
    DESK_MODEL,
    DESK_RESEARCH,
    DESK_SIGNAL,
    DESK_STRATEGY,
)
from ...lineage.ids import content_hash
from .plan import AgentTodo
from .roles import (
    ROLE_BACKTEST,
    ROLE_COORDINATOR,
    ROLE_DATA,
    ROLE_FACTOR,
    ROLE_LITERATURE,
    ROLE_MATH,
    ROLE_MODEL,
    ROLE_REPORTER,
    ROLE_RISK,
    ROLE_SIGNAL,
    ROLE_STRATEGYBOOK,
    ROLE_VERIFIER,
    get_role,
)


PRODUCTION_COORDINATOR_TASK_ID = "coordinator-turn"

_SPECIALIST_ORDER = (
    ROLE_LITERATURE,
    ROLE_MATH,
    ROLE_DATA,
    ROLE_FACTOR,
    ROLE_MODEL,
    ROLE_SIGNAL,
    ROLE_STRATEGYBOOK,
    ROLE_BACKTEST,
    ROLE_RISK,
    ROLE_REPORTER,
    ROLE_VERIFIER,
)

_INTENT_MARKERS: dict[str, tuple[str, ...]] = {
    ROLE_LITERATURE: ("论文", "文献", "研报", "literature", "paper", "citation"),
    ROLE_MATH: ("数学", "公式", "定理", "推导", "derive", "derivation", "theorem"),
    ROLE_DATA: (
        "数据",
        "字段",
        "数据源",
        "映射",
        "dataset",
        "schema",
        "mapping",
        "point-in-time",
        "pit",
    ),
    ROLE_FACTOR: ("因子", "因子集", "factor", "factor set", "ic"),
    ROLE_MODEL: ("模型", "训练", "model", "training", "registry"),
    ROLE_SIGNAL: ("信号", "signal"),
    ROLE_STRATEGYBOOK: (
        "策略簿",
        "组合",
        "仓位",
        "权重",
        "strategybook",
        "portfolio",
        "position",
    ),
    ROLE_BACKTEST: (
        "回测",
        "反证",
        "backtest",
        "walk-forward",
        "pbo",
        "cpcv",
        "bootstrap",
    ),
    ROLE_RISK: ("风险", "回撤", "限额", "risk", "drawdown", "var", "kill switch"),
    ROLE_REPORTER: ("报告", "总结", "汇报", "report", "write-up", "writeup"),
    # Explicit independence language only. Plain “验证” remains backtest/research work.
    ROLE_VERIFIER: ("独立复核", "独立验证", "对抗复核", "verifier", "independent review"),
}

_DESK_FALLBACK_ROLE = {
    DESK_RESEARCH: ROLE_LITERATURE,
    DESK_DATA: ROLE_DATA,
    DESK_FACTOR: ROLE_FACTOR,
    DESK_MODEL: ROLE_MODEL,
    DESK_SIGNAL: ROLE_SIGNAL,
    DESK_STRATEGY: ROLE_STRATEGYBOOK,
    DESK_BACKTEST: ROLE_BACKTEST,
    DESK_EXECUTION: ROLE_RISK,
}

_ASSET_HINT_ROLE = {
    "dataset": ROLE_DATA,
    "data": ROLE_DATA,
    "factor": ROLE_FACTOR,
    "model": ROLE_MODEL,
    "signal": ROLE_SIGNAL,
    "strategy": ROLE_STRATEGYBOOK,
    "portfolio": ROLE_STRATEGYBOOK,
    "run": ROLE_BACKTEST,
    "backtest": ROLE_BACKTEST,
    "risk": ROLE_RISK,
    "report": ROLE_REPORTER,
}

_ROLE_DESCRIPTION = {
    ROLE_COORDINATOR: "scope and coordinate the authenticated research request",
    ROLE_LITERATURE: "retrieve and assess candidate literature evidence",
    ROLE_MATH: "derive or check the requested mathematical claim",
    ROLE_DATA: "inspect the requested data contract and point-in-time constraints",
    ROLE_FACTOR: "develop or validate the requested factor work",
    ROLE_MODEL: "develop or assess the requested model work",
    ROLE_SIGNAL: "develop or inspect the requested signal contract",
    ROLE_STRATEGYBOOK: "develop or inspect the requested StrategyBook and portfolio constraints",
    ROLE_BACKTEST: "run or design the requested backtest and falsification work",
    ROLE_RISK: "assess the requested risk and execution constraints",
    ROLE_REPORTER: "report the requested research result without upgrading evidence status",
    ROLE_VERIFIER: "independently challenge one server-selected upstream result",
}


def _marker_matches(text: str, marker: str) -> bool:
    if marker.isascii() and len(marker) <= 3:
        return re.search(rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])", text) is not None
    return marker in text


def _asset_roles(asset_refs: Iterable[str]) -> set[str]:
    roles: set[str] = set()
    for raw_ref in asset_refs:
        ref = str(raw_ref or "").strip().lower()
        if not ref:
            continue
        tokens = {token for token in re.split(r"[^a-z0-9_]+", ref) if token}
        for hint, role in _ASSET_HINT_ROLE.items():
            if hint in tokens:
                roles.add(role)
    return roles


def _task_id(role: str) -> str:
    if role == ROLE_COORDINATOR:
        return PRODUCTION_COORDINATOR_TASK_ID
    return f"production-agent-turn:{role}"


@dataclass(frozen=True)
class ProductionAgentTaskRoute:
    todos: tuple[AgentTodo, ...]
    dependencies: dict[str, list[str]]
    instructions: dict[str, str]
    selected_roles: tuple[str, ...]
    primary_task_id: str
    route_digest: str
    basis: dict[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        todo_ids = {todo.todo_id for todo in self.todos}
        if self.primary_task_id not in todo_ids:
            raise ValueError("production route primary task must exist in todos")
        if tuple(todo.role for todo in self.todos) != self.selected_roles:
            raise ValueError("production route roles must match todo order")
        for todo in self.todos:
            get_role(todo.role)
            if todo.todo_id not in self.dependencies:
                raise ValueError("production route must declare every dependency list")


def route_production_agent_task(
    user_input: str,
    *,
    desk: str = "",
    visible_asset_refs: Iterable[str] = (),
) -> ProductionAgentTaskRoute:
    """Derive a deterministic role DAG without accepting a caller-supplied role.

    Lexical intent is authoritative for routing.  If it yields no specialist,
    the controlled desk/asset mappings may select one fallback specialist;
    otherwise the request remains coordinator-only.  Multiple explicit intents
    become sibling role nodes.  A requested reporter waits for all builder
    roles; an explicit verifier reviews exactly one deterministic builder so the
    existing independent-review binding remains content-bound.
    """

    instruction = str(user_input or "").strip()
    if not instruction:
        raise ValueError("user_input is required for production task routing")
    text = instruction.lower()

    matched: dict[str, tuple[str, ...]] = {}
    for role in _SPECIALIST_ORDER:
        markers = tuple(
            marker
            for marker in _INTENT_MARKERS[role]
            if _marker_matches(text, marker.lower())
        )
        if markers:
            matched[role] = markers

    asset_roles = _asset_roles(visible_asset_refs)
    for role in _SPECIALIST_ORDER:
        if role in asset_roles and role not in matched:
            matched[role] = ("asset_ref",)

    if not matched:
        fallback = _DESK_FALLBACK_ROLE.get(str(desk or "").strip().lower())
        if fallback:
            matched[fallback] = ("desk_context",)

    roles = (ROLE_COORDINATOR, *(role for role in _SPECIALIST_ORDER if role in matched))
    coordinator_id = _task_id(ROLE_COORDINATOR)
    dependencies: dict[str, list[str]] = {coordinator_id: []}
    todos = [
        AgentTodo(
            todo_id=coordinator_id,
            description=_ROLE_DESCRIPTION[ROLE_COORDINATOR],
            role=ROLE_COORDINATOR,
        )
    ]

    builder_roles = [
        role
        for role in roles
        if role not in {ROLE_COORDINATOR, ROLE_REPORTER, ROLE_VERIFIER}
    ]
    for role in roles[1:]:
        task_id = _task_id(role)
        if role == ROLE_REPORTER:
            deps = [_task_id(item) for item in builder_roles] or [coordinator_id]
        elif role == ROLE_VERIFIER:
            # One exact upstream subject is required by the content-bound review kernel.
            subject_role = builder_roles[-1] if builder_roles else ROLE_COORDINATOR
            deps = [_task_id(subject_role)]
        else:
            deps = [coordinator_id]
        dependencies[task_id] = deps
        todos.append(
            AgentTodo(
                todo_id=task_id,
                description=_ROLE_DESCRIPTION[role],
                role=role,
                deps=tuple(deps),
            )
        )

    if ROLE_VERIFIER in roles:
        primary_role = ROLE_VERIFIER
    elif ROLE_REPORTER in roles:
        primary_role = ROLE_REPORTER
    elif len(roles) > 1:
        primary_role = roles[-1]
    else:
        primary_role = ROLE_COORDINATOR

    basis = {role: matched[role] for role in _SPECIALIST_ORDER if role in matched}
    return ProductionAgentTaskRoute(
        todos=tuple(todos),
        dependencies=dependencies,
        instructions={todo.todo_id: instruction for todo in todos},
        selected_roles=tuple(roles),
        primary_task_id=_task_id(primary_role),
        route_digest=content_hash(
            {
                "selected_roles": roles,
                "dependencies": dependencies,
                "basis": basis,
            }
        ),
        basis=basis,
    )


__all__ = [
    "PRODUCTION_COORDINATOR_TASK_ID",
    "ProductionAgentTaskRoute",
    "route_production_agent_task",
]
