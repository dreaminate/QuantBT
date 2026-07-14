from __future__ import annotations

import inspect

import pytest

from app.agent.orchestrator.roles import (
    ROLE_BACKTEST,
    ROLE_COORDINATOR,
    ROLE_DATA,
    ROLE_FACTOR,
    ROLE_MODEL,
    ROLE_REPORTER,
    ROLE_RISK,
    ROLE_SIGNAL,
    ROLE_STRATEGYBOOK,
    ROLE_VERIFIER,
)
from app.agent.orchestrator.task_router import (
    PRODUCTION_COORDINATOR_TASK_ID,
    route_production_agent_task,
)


@pytest.mark.parametrize(
    ("prompt", "expected_role"),
    [
        ("检查 dataset schema 和 PIT 约束", ROLE_DATA),
        ("构造一个质量因子并计算 IC", ROLE_FACTOR),
        ("训练横截面排序模型", ROLE_MODEL),
        ("定义交易信号契约", ROLE_SIGNAL),
        ("设置组合权重与仓位约束", ROLE_STRATEGYBOOK),
        ("跑 walk-forward 回测", ROLE_BACKTEST),
        ("检查最大回撤与风险限额", ROLE_RISK),
        ("写一份研究报告", ROLE_REPORTER),
    ],
)
def test_server_router_selects_task_specific_role(prompt: str, expected_role: str):
    route = route_production_agent_task(prompt)

    assert route.selected_roles == (ROLE_COORDINATOR, expected_role)
    specialist = route.todos[-1]
    assert specialist.role == expected_role
    assert route.dependencies[specialist.todo_id] == [PRODUCTION_COORDINATOR_TASK_ID]
    assert route.primary_task_id == specialist.todo_id


def test_multi_intent_route_builds_parallel_specialists_then_reporter():
    route = route_production_agent_task(
        "检查数据 PIT，构造因子，训练模型，跑回测，评估风险并生成报告"
    )

    assert route.selected_roles == (
        ROLE_COORDINATOR,
        ROLE_DATA,
        ROLE_FACTOR,
        ROLE_MODEL,
        ROLE_BACKTEST,
        ROLE_RISK,
        ROLE_REPORTER,
    )
    ids = {todo.role: todo.todo_id for todo in route.todos}
    for role in (ROLE_DATA, ROLE_FACTOR, ROLE_MODEL, ROLE_BACKTEST, ROLE_RISK):
        assert route.dependencies[ids[role]] == [ids[ROLE_COORDINATOR]]
    assert route.dependencies[ids[ROLE_REPORTER]] == [
        ids[ROLE_DATA],
        ids[ROLE_FACTOR],
        ids[ROLE_MODEL],
        ids[ROLE_BACKTEST],
        ids[ROLE_RISK],
    ]
    assert route.primary_task_id == ids[ROLE_REPORTER]


def test_explicit_independent_review_binds_exactly_one_server_selected_subject():
    route = route_production_agent_task("对因子回测做独立复核")
    ids = {todo.role: todo.todo_id for todo in route.todos}

    assert route.selected_roles == (
        ROLE_COORDINATOR,
        ROLE_FACTOR,
        ROLE_BACKTEST,
        ROLE_VERIFIER,
    )
    assert route.dependencies[ids[ROLE_VERIFIER]] == [ids[ROLE_BACKTEST]]
    assert route.primary_task_id == ids[ROLE_VERIFIER]


def test_unknown_intent_stays_coordinator_only_and_role_is_not_a_caller_parameter():
    route = route_production_agent_task("请帮我看看这个想法")

    assert route.selected_roles == (ROLE_COORDINATOR,)
    assert route.dependencies == {PRODUCTION_COORDINATOR_TASK_ID: []}
    assert "role" not in inspect.signature(route_production_agent_task).parameters


def test_controlled_desk_and_asset_context_are_fallback_inputs_not_role_names():
    desk_route = route_production_agent_task("检查当前对象", desk="factor_desk")
    asset_route = route_production_agent_task(
        "检查当前对象", visible_asset_refs=("qro:model:ranker-v2",)
    )

    assert desk_route.selected_roles == (ROLE_COORDINATOR, ROLE_FACTOR)
    assert desk_route.basis == {ROLE_FACTOR: ("desk_context",)}
    assert asset_route.selected_roles == (ROLE_COORDINATOR, ROLE_MODEL)
    assert asset_route.basis == {ROLE_MODEL: ("asset_ref",)}


def test_route_is_deterministic_but_preserves_original_instruction_case():
    left = route_production_agent_task("Run BACKTEST for Model V2")
    right = route_production_agent_task("Run BACKTEST for Model V2")

    assert left.route_digest == right.route_digest
    assert left.dependencies == right.dependencies
    assert set(left.instructions.values()) == {"Run BACKTEST for Model V2"}


def test_empty_task_is_rejected():
    with pytest.raises(ValueError, match="user_input"):
        route_production_agent_task("   ")
