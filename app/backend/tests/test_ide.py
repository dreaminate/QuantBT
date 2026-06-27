"""IDE · 沙箱 + 策略 CRUD + 运行 落地测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.llm_client import LLMResponse
from app.ide.sandbox import run_user_strategy
from app.ide.service import IDEError, IDEService
from app.research_os import (
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    ResearchGraphStore,
)


# ============================================================
# sandbox 单元测试
# ============================================================


def test_sandbox_emit_result():
    r = run_user_strategy("print('hi'); quantbt.emit_result({'a': 1, 'b': 'x'})")
    assert r.exit_code == 0
    assert r.user_result == {"a": 1, "b": "x"}
    assert "hi" in r.stdout


def test_sandbox_blocks_socket():
    r = run_user_strategy(
        "import socket\n"
        "try:\n    socket.socket()\nexcept PermissionError as e:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_subprocess():
    r = run_user_strategy(
        "import subprocess\n"
        "try:\n    subprocess.run(['ls'])\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_os_system():
    r = run_user_strategy(
        "import os\n"
        "try:\n    os.system('ls')\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_chdir():
    r = run_user_strategy(
        "import os\n"
        "try:\n    os.chdir('/')\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_wallclock_timeout():
    r = run_user_strategy("while True: pass", timeout_s=2.0)
    assert r.timed_out is True
    assert r.duration_s < 5.0


def test_sandbox_nonzero_exit_collected():
    r = run_user_strategy("raise ValueError('oops')")
    assert r.exit_code != 0
    assert "ValueError" in r.stderr
    assert r.error is not None


def test_sandbox_passes_data_dir_env(tmp_path):
    r = run_user_strategy(
        "import os; quantbt.emit_result({'dd': os.environ.get('DATA_DIR')})",
        extra_env={"DATA_DIR": "/tmp/x", "SECRET_KEY": "nope"},
    )
    # DATA_DIR 透传 / SECRET_KEY 不透传
    assert r.user_result == {"dd": "/tmp/x"}


# ============================================================
# IDEService CRUD
# ============================================================


@pytest.fixture
def svc(tmp_path: Path) -> IDEService:
    return IDEService(tmp_path / "ide.db", run_root=tmp_path / "runs")


def test_save_and_get_strategy(svc):
    s = svc.save_strategy("alice", "momentum_v1", "print(1)")
    assert s.owner_username == "alice"
    assert s.name == "momentum_v1"
    fetched = svc.get_strategy("alice", "momentum_v1")
    assert fetched.code == "print(1)"


def test_save_strategy_persists_market_data_use_validation_refs(svc):
    refs = ["market_data_use:ide:accepted"]
    s = svc.save_strategy(
        "alice",
        "with_market_data_use",
        "print(1)",
        market_data_use_validation_refs=refs,
    )

    assert s.market_data_use_validation_refs == refs
    assert svc.get_strategy("alice", "with_market_data_use").market_data_use_validation_refs == refs
    listed = svc.list_strategies("alice")
    assert listed[0].market_data_use_validation_refs == refs


def test_run_strategy_persists_market_data_use_validation_refs(svc):
    refs = ["market_data_use:ide_run:accepted"]
    svc.save_strategy(
        "alice",
        "run_with_market_data_use",
        "quantbt.emit_result({'x': 1})",
        market_data_use_validation_refs=refs,
    )

    run = svc.run_strategy("alice", "run_with_market_data_use")

    assert run.market_data_use_validation_refs == refs
    assert svc.get_run(run.run_id).market_data_use_validation_refs == refs
    assert svc.list_runs("alice")[0].market_data_use_validation_refs == refs


def test_save_strategy_validates_name(svc):
    with pytest.raises(IDEError):
        svc.save_strategy("alice", "bad name with spaces", "print(1)")


def test_save_strategy_validates_asset_class(svc):
    with pytest.raises(IDEError):
        svc.save_strategy("alice", "x", "print(1)", asset_class="forex")


def test_save_strategy_update_in_place(svc):
    s1 = svc.save_strategy("alice", "v1", "print(1)")
    s2 = svc.save_strategy("alice", "v1", "print(2)")
    assert s1.strategy_id == s2.strategy_id
    assert s2.code == "print(2)"


def test_save_strategy_owner_namespace(svc):
    # 两个用户可以同名
    a = svc.save_strategy("alice", "v1", "print('a')")
    b = svc.save_strategy("bob", "v1", "print('b')")
    assert a.strategy_id != b.strategy_id


def test_list_strategies_only_own(svc):
    svc.save_strategy("alice", "a1", "print(1)")
    svc.save_strategy("alice", "a2", "print(2)")
    svc.save_strategy("bob", "b1", "print(3)")
    assert {x.name for x in svc.list_strategies("alice")} == {"a1", "a2"}
    assert [x.name for x in svc.list_strategies("bob")] == ["b1"]


def test_delete_strategy(svc):
    svc.save_strategy("alice", "v1", "print(1)")
    svc.delete_strategy("alice", "v1")
    with pytest.raises(IDEError):
        svc.get_strategy("alice", "v1")


def test_delete_strategy_missing_404(svc):
    with pytest.raises(IDEError):
        svc.delete_strategy("alice", "nope")


# ============================================================
# IDE run
# ============================================================


def test_run_strategy_emit_result(svc):
    svc.save_strategy("alice", "good", "quantbt.emit_result({'sharpe': 1.5})")
    run = svc.run_strategy("alice", "good")
    assert run.status == "ok"
    assert run.exit_code == 0
    assert "sharpe" in run.result_keys


def test_run_strategy_failure(svc):
    svc.save_strategy("alice", "bad", "raise RuntimeError('boom')")
    run = svc.run_strategy("alice", "bad")
    assert run.status == "failed"
    assert run.error is not None
    assert "RuntimeError" in run.stderr_excerpt or "boom" in run.stderr_excerpt


def test_run_strategy_lists_recent(svc):
    svc.save_strategy("alice", "good", "quantbt.emit_result({'x': 1})")
    svc.run_strategy("alice", "good")
    svc.run_strategy("alice", "good")
    runs = svc.list_runs("alice")
    assert len(runs) == 2
    assert all(r.status == "ok" for r in runs)


def test_get_run_artifact_result(svc):
    svc.save_strategy("alice", "x", "quantbt.emit_result({'ret': 0.1})")
    run = svc.run_strategy("alice", "x")
    art = svc.get_run_artifact(run.run_id, "result")
    assert art["body"] == {"ret": 0.1}


def test_get_run_artifact_stdout(svc):
    svc.save_strategy("alice", "x", "print('hello world'); quantbt.emit_result({})")
    run = svc.run_strategy("alice", "x")
    art = svc.get_run_artifact(run.run_id, "stdout")
    assert "hello world" in art["body"]


def test_get_run_artifact_invalid_kind(svc):
    svc.save_strategy("alice", "x", "quantbt.emit_result({})")
    run = svc.run_strategy("alice", "x")
    with pytest.raises(IDEError):
        svc.get_run_artifact(run.run_id, "binary")


# ============================================================
# IDE API GOAL entrypoint coverage
# ============================================================


class _IDECompleteLLM:
    provider = "test"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse(content="quantbt.emit_result({'ok': 1})")


@pytest.fixture
def ide_api(tmp_path: Path, monkeypatch):  # noqa: ANN001
    import app.main as main

    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="alice",
        user_id="u_alice",
    )
    monkeypatch.setattr(main, "IDE_SERVICE", IDEService(tmp_path / "ide_api.db", run_root=tmp_path / "ide_runs"))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    monkeypatch.setattr(main, "LEDGER", None)
    monkeypatch.setattr(main, "RETURNS_STORE", None)
    real_promote = main.promote_ide_run

    def _promote_tmp_root(**kwargs):  # noqa: ANN003
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp_root)
    try:
        yield TestClient(main.app), main
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


def test_ide_api_success_paths_write_goal_entrypoint_coverage_without_raw_payload(ide_api, monkeypatch):
    client, main = ide_api
    secret = "SECRET_SHOULD_NOT_ENTER_IDE_GOAL_COVERAGE"
    validation_ref = "market_data_use:ide:accepted"
    monkeypatch.setattr(
        main,
        "_ide_strategy_market_data_use_validation_refs",
        lambda payload, *, operation, fallback_refs=None: (validation_ref,),  # noqa: ARG005
    )
    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None: _IDECompleteLLM())
    strategy_code = (
        f"# {secret}\n"
        "quantbt.emit_result({'equity_curve': ["
        "{'t': '2024-01-01', 'equity': 1.0},"
        "{'t': '2024-01-02', 'equity': 1.02}"
        "], 'metadata': {'market': 'crypto_perp', 'frequency': '1d', 'benchmark': 'BTC-USDT'}})"
    )

    saved = client.post(
        "/api/ide/strategies",
        json={
            "name": "coverage_strategy",
            "asset_class": "crypto_perp",
            "code": strategy_code,
            "description": f"description {secret}",
            "market_data_use_validation_refs": [validation_ref],
        },
    )
    assert saved.status_code == 200, saved.text
    run = client.post(
        "/api/ide/strategies/coverage_strategy/run",
        json={"market_data_use_validation_refs": [validation_ref]},
    )
    assert run.status_code == 200, run.text
    promoted = client.post(
        f"/api/ide/runs/{run.json()['run_id']}/promote",
        json={"record_name": f"record {secret}", "market_data_use_validation_refs": [validation_ref]},
    )
    assert promoted.status_code == 200, promoted.text
    completed = client.post(
        "/api/ide/ai_complete",
        json={
            "mode": "write",
            "prompt": f"write strategy {secret}",
            "context_code": f"context {secret}",
            "market_data_use_validation_refs": [validation_ref],
        },
    )
    assert completed.status_code == 200, completed.text

    responses = [saved.json(), run.json(), promoted.json(), completed.json()]
    for body in responses:
        assert body["qro_id"]
        assert body["research_graph_command_id"]
        assert body["compiler_ir_ref"]
        assert body["compiler_pass_ref"]
        assert body["entrypoint_coverage_ref"]

    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    assert {(record.entry_source, record.entrypoint_ref) for record in coverages} == {
        ("ide", "ide:strategy.save"),
        ("ide", "ide:strategy.run"),
        ("ide", "ide:run.promote"),
        ("ide", "ide:ai_complete"),
    }
    for record in coverages:
        assert record.qro_refs
        assert record.research_graph_command_refs
        assert record.compiler_ir_refs
        assert record.compiler_pass_refs
        assert record.evidence_refs
        assert record.validation_refs
        assert record.permission_refs
        assert record.replay_refs

    persisted = str(coverages)
    for command in main.RESEARCH_GRAPH_STORE.commands():
        persisted += str(command.payload)
    for ir in main.COMPILER_IR_STORE.irs():
        persisted += str(ir)
    for compiler_pass in main.COMPILER_IR_STORE.passes():
        persisted += str(compiler_pass)
    assert secret not in persisted
    assert "quantbt.emit_result" not in persisted
    assert "write strategy" not in persisted
    assert "context " not in persisted


def test_ide_api_unknown_market_data_ref_rejects_before_goal_coverage_write(ide_api):
    client, main = ide_api

    response = client.post(
        "/api/ide/strategies",
        json={
            "name": "bad_refs",
            "asset_class": "crypto_perp",
            "code": "quantbt.emit_result({})",
            "market_data_use_validation_refs": ["market_data_use:unknown"],
        },
    )

    assert response.status_code == 422
    assert "unknown market data use validation" in response.text
    assert main.RESEARCH_GRAPH_STORE.commands() == []
    assert main.COMPILER_IR_STORE.irs() == []
    assert main.COMPILER_IR_STORE.passes() == []
    assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
