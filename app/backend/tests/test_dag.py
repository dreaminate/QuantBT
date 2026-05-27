from __future__ import annotations

import time

import pytest

from app.dag import DAGDefinition, DAGTask, register_op, run_dag


@register_op("test.echo")
def _echo(*, context, value):
    context.setdefault("calls", []).append(value)
    return value


@register_op("test.boom")
def _boom(*, context):  # noqa: ARG001
    raise RuntimeError("boom")


@register_op("test.slow")
def _slow(*, context, seconds=0.5):  # noqa: ARG001
    time.sleep(seconds)
    return "ok"


def test_dag_topological_execution() -> None:
    dag = DAGDefinition(
        name="t",
        tasks=[
            DAGTask(id="a", op="test.echo", params={"value": 1}),
            DAGTask(id="b", op="test.echo", params={"value": 2}, deps=["a"]),
            DAGTask(id="c", op="test.echo", params={"value": 3}, deps=["b", "a"]),
        ],
    )
    context = {}
    result = run_dag(dag, context=context)
    assert result.succeeded
    assert context["calls"] == [1, 2, 3]


def test_dag_retries_and_eventual_failure() -> None:
    dag = DAGDefinition(
        name="r",
        tasks=[DAGTask(id="a", op="test.boom", retries=2, retry_backoff_seconds=0.01)],
    )
    result = run_dag(dag)
    assert not result.succeeded
    assert result.tasks[0].status == "failed"
    assert result.tasks[0].attempts == 3


def test_dag_dependency_skip_when_upstream_fails() -> None:
    dag = DAGDefinition(
        name="s",
        tasks=[
            DAGTask(id="a", op="test.boom"),
            DAGTask(id="b", op="test.echo", params={"value": 1}, deps=["a"]),
        ],
    )
    result = run_dag(dag)
    statuses = {t.task_id: t.status for t in result.tasks}
    assert statuses["a"] == "failed"
    assert statuses["b"] == "skipped"


def test_dag_timeout_kills_task() -> None:
    dag = DAGDefinition(
        name="to",
        tasks=[DAGTask(id="slow", op="test.slow", params={"seconds": 1.0}, timeout_seconds=0.1)],
    )
    result = run_dag(dag)
    assert result.tasks[0].status == "timeout"


def test_dag_cycle_detected() -> None:
    dag = DAGDefinition(
        name="cycle",
        tasks=[
            DAGTask(id="a", op="test.echo", params={"value": 1}, deps=["b"]),
            DAGTask(id="b", op="test.echo", params={"value": 2}, deps=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="循环依赖"):
        run_dag(dag)


def test_dag_yaml_round_trip() -> None:
    yaml_text = """
name: daily
schedule: "0 17 * * 1-5"
tasks:
  - id: pull
    op: test.echo
    params: {value: 99}
  - id: trans
    op: test.echo
    params: {value: 100}
    deps: [pull]
"""
    dag = DAGDefinition.from_yaml(yaml_text)
    assert dag.name == "daily"
    assert dag.schedule == "0 17 * * 1-5"
    assert {t.id for t in dag.tasks} == {"pull", "trans"}


def test_dag_sla_violation_flagged() -> None:
    dag = DAGDefinition(
        name="sla",
        tasks=[DAGTask(id="s", op="test.slow", params={"seconds": 0.1}, sla_seconds=0.01)],
    )
    result = run_dag(dag)
    assert result.tasks[0].sla_violated
