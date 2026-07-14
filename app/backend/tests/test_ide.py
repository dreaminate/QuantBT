"""IDE · 沙箱 + 策略 CRUD + 运行 落地测试。"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.llm_client import LLMResponse
from app.ide.sandbox import run_user_strategy
from app.ide.service import IDEError, IDEService, validate_strategy_inputs
from app.lineage.ids import canonical_json, content_hash
from app.research_os import (
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    ResearchGraphStore,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver


def _patch_goal_proof_stores(main, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    graph = ResearchGraphStore()
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)


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


def test_run_strategy_persists_pre_run_section9_evidence_ref(svc):
    svc.save_strategy(
        "alice",
        "run_with_section9",
        "quantbt.emit_result({'x': 1})",
    )

    run = svc.run_strategy(
        "alice",
        "run_with_section9",
        section9_evidence_ref="s9snap_exact",
    )

    assert run.section9_evidence_ref == "s9snap_exact"
    assert svc.get_run(run.run_id).section9_evidence_ref == "s9snap_exact"
    assert svc.list_runs("alice")[0].section9_evidence_ref == "s9snap_exact"


def test_save_strategy_validates_name(svc):
    with pytest.raises(IDEError):
        svc.save_strategy("alice", "bad name with spaces", "print(1)")


def test_save_strategy_validates_asset_class(svc):
    with pytest.raises(IDEError):
        svc.save_strategy("alice", "x", "print(1)", asset_class="forex")


def test_save_strategy_uses_shared_pure_validator(svc, monkeypatch):
    import app.ide.service as ide_service

    calls = []
    real_validator = ide_service.validate_strategy_inputs

    def recording_validator(owner_username, name, code, **kwargs):  # noqa: ANN001
        calls.append((owner_username, name, code, kwargs))
        return real_validator(owner_username, name, code, **kwargs)

    monkeypatch.setattr(ide_service, "validate_strategy_inputs", recording_validator)

    saved = svc.save_strategy(
        "alice",
        "shared_validator",
        "print(1)",
        asset_class="equity_cn",
        description="validated once",
    )

    assert saved.name == "shared_validator"
    assert calls == [
        (
            "alice",
            "shared_validator",
            "print(1)",
            {"asset_class": "equity_cn", "description": "validated once"},
        )
    ]


@pytest.mark.parametrize(
    ("owner_username", "name", "code", "asset_class", "description"),
    [
        ("alice", "bad name", "print(1)", "crypto_perp", ""),
        ("alice", "bad_code", 0, "crypto_perp", ""),
        ("alice", "bad_asset", "print(1)", [], ""),
        ("alice", "bad_description", "print(1)", "crypto_perp", 0),
    ],
)
def test_invalid_strategy_input_leaves_projection_and_version_tables_empty(
    svc,
    owner_username,
    name,
    code,
    asset_class,
    description,
):
    with pytest.raises(IDEError):
        validate_strategy_inputs(
            owner_username,
            name,
            code,
            asset_class=asset_class,
            description=description,
        )
    with pytest.raises(IDEError):
        svc.save_strategy(
            owner_username,
            name,
            code,
            asset_class=asset_class,
            description=description,
        )

    with svc._conn() as conn:  # noqa: SLF001 - prove both SQLite tables stayed empty.
        assert conn.execute("SELECT COUNT(*) FROM i_strategies").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM i_strategy_versions").fetchone()[0] == 0


def test_save_strategy_rolls_back_projection_and_version_on_transaction_failure(
    svc,
    monkeypatch,
):
    original_record_version = svc._record_version_locked  # noqa: SLF001

    def fail_after_version_insert(conn, **kwargs):  # noqa: ANN001
        original_record_version(conn, **kwargs)
        raise RuntimeError("injected failure after version insert")

    monkeypatch.setattr(svc, "_record_version_locked", fail_after_version_insert)

    with pytest.raises(RuntimeError, match="injected failure"):
        svc.save_strategy("alice", "atomic_save", "print(1)")

    with svc._conn() as conn:  # noqa: SLF001 - prove the transaction left no partial row.
        assert conn.execute("SELECT COUNT(*) FROM i_strategies").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM i_strategy_versions").fetchone()[0] == 0


def test_save_strategy_update_in_place(svc):
    s1 = svc.save_strategy("alice", "v1", "print(1)")
    s2 = svc.save_strategy("alice", "v1", "print(2)")
    assert s1.strategy_id == s2.strategy_id
    assert s2.code == "print(2)"


def test_save_strategy_identical_retry_keeps_projection_and_single_version(svc):
    refs = ["market_data_use:ide:accepted"]
    first = svc.save_strategy(
        "alice",
        "idempotent_save",
        "print(1)",
        asset_class="equity_cn",
        description="exact draft",
        market_data_use_validation_refs=refs,
    )
    restarted = IDEService(svc._db, run_root=svc._run_root)  # noqa: SLF001
    retried = restarted.save_strategy(
        "alice",
        "idempotent_save",
        "print(1)",
        asset_class="equity_cn",
        description="exact draft",
        market_data_use_validation_refs=refs,
    )

    assert retried == first
    assert len(restarted.list_versions("alice", "idempotent_save")) == 1


def test_save_strategy_changed_content_appends_one_version_then_reuses_it(svc):
    first = svc.save_strategy("alice", "one_edit", "print(1)")
    changed = svc.save_strategy("alice", "one_edit", "print(2)")
    retried = svc.save_strategy("alice", "one_edit", "print(2)")

    assert changed.strategy_id == first.strategy_id
    assert retried == changed
    versions = svc.list_versions("alice", "one_edit")
    assert len(versions) == 2
    assert len({version.version_id for version in versions}) == 2


def test_save_strategy_identical_concurrent_retries_append_one_version(svc):
    workers = 8
    barrier = Barrier(workers)

    def save():
        barrier.wait()
        return svc.save_strategy(
            "alice",
            "concurrent_save",
            "print(1)",
            description="same concurrent draft",
            market_data_use_validation_refs=["market_data_use:ide:accepted"],
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _index: save(), range(workers)))

    assert len({result.strategy_id for result in results}) == 1
    assert len({result.updated_at_utc for result in results}) == 1
    assert len(svc.list_versions("alice", "concurrent_save")) == 1


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


def test_run_strategy_freezes_canonical_source_run_artifacts(svc):
    code = (
        "quantbt.emit_result({"
        "'equity_curve': ["
        "{'t': '2026-01-01', 'equity': 1.0, 'net_return': 0.0, 'benchmark_return': 0.0},"
        "{'t': '2026-01-02', 'equity': 1.1, 'net_return': 0.1, 'benchmark_return': 0.05}],"
        "'metadata': {'market': 'crypto_perp', 'frequency': '1d'},"
        "'metrics': {'sharpe': 1.25}"
        "})"
    )
    strategy = svc.save_strategy("alice", "source_snapshot", code)

    run = svc.run_strategy("alice", "source_snapshot", owner_user_id="usr_stable_1")

    assert run.status == "ok"
    assert svc.run_root == svc._run_root  # noqa: SLF001 - prove the public projection is exact.
    run_dir = svc.run_root / run.run_id
    assert (run_dir / "strategy.py").read_bytes() == code.encode("utf-8")
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    manifest_bytes = (run_dir / "run.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    portfolio_bytes = (run_dir / "portfolio.csv").read_bytes()

    assert manifest_bytes == (canonical_json(manifest) + "\n").encode("utf-8")
    assert manifest["artifact_version"] == "ide.source_run.v1"
    assert manifest["owner_user_id"] == "usr_stable_1"
    assert manifest["strategy_id"] == strategy.strategy_id
    assert manifest["source"]["kind"] == "ide_sandbox"
    assert manifest["source"]["ide_run_id"] == run.run_id
    assert manifest["source"]["owner_user_id"] == "usr_stable_1"
    assert manifest["source"]["strategy_code_content_hash"] == content_hash(code)
    assert manifest["source"]["result_content_hash"] == content_hash(result)
    assert manifest["source"]["strategy_file_sha256"] == (
        "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest()
    )
    assert manifest["source"]["portfolio_file_sha256"] == (
        "sha256:" + hashlib.sha256(portfolio_bytes).hexdigest()
    )
    assert portfolio_bytes.decode("utf-8") == (
        "timestamp,equity,net_return,benchmark_return,drawdown\n"
        "2026-01-01,1.0,0.0,0.0,0.0\n"
        "2026-01-02,1.1,0.1,0.05,0.0\n"
    )


def test_run_strategy_snapshot_survives_current_strategy_edit_and_restart(svc):
    original = "quantbt.emit_result({'equity_curve': [{'t': 'd1', 'equity': 1}]})"
    svc.save_strategy("alice", "immutable_source", original)
    run = svc.run_strategy("alice", "immutable_source", owner_user_id="u1")
    run_dir = svc.run_root / run.run_id
    before = {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()}

    svc.save_strategy(
        "alice",
        "immutable_source",
        "quantbt.emit_result({'equity_curve': [{'t': 'changed', 'equity': 9}]})",
    )
    restarted = IDEService(svc._db, run_root=svc.run_root)  # noqa: SLF001

    assert restarted.get_run(run.run_id).status == "ok"
    assert (run_dir / "strategy.py").read_text(encoding="utf-8") == original
    assert {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()} == before


def test_run_strategy_source_snapshot_failure_is_fail_closed(svc, monkeypatch):
    svc.save_strategy("alice", "snapshot_failure", "quantbt.emit_result({'x': 1})")

    def fail_snapshot(**_kwargs):
        raise OSError("injected disk failure")

    monkeypatch.setattr(svc, "_persist_source_snapshot", fail_snapshot)
    run = svc.run_strategy("alice", "snapshot_failure", owner_user_id="u1")
    run_dir = svc.run_root / run.run_id

    assert run.status == "failed"
    assert run.error == "source snapshot persistence failed: OSError: injected disk failure"
    assert not (run_dir / "run.json").exists()
    assert not (run_dir / "strategy.py").exists()
    assert not (run_dir / "portfolio.csv").exists()
    assert not (run_dir / "result.json").exists()


def test_run_strategy_direct_service_owner_fallback_is_explicit(svc):
    svc.save_strategy("alice", "owner_fallback", "quantbt.emit_result({})")
    run = svc.run_strategy("alice", "owner_fallback")
    manifest = json.loads((svc.run_root / run.run_id / "run.json").read_text(encoding="utf-8"))

    assert manifest["owner_user_id"] == "alice"
    assert manifest["source"]["owner_user_id"] == "alice"


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
    _patch_goal_proof_stores(main, tmp_path, monkeypatch)
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


def test_ide_api_locally_available_paths_write_coverage_and_formal_promote_fails_closed(
    ide_api,
    monkeypatch,
):
    client, main = ide_api
    secret = "SECRET_SHOULD_NOT_ENTER_IDE_GOAL_COVERAGE"
    validation_ref = "market_data_use:ide:accepted"
    monkeypatch.setattr(
        main,
        "_ide_strategy_market_data_use_validation_refs",
        lambda payload, *, owner_user_id, operation, fallback_refs=None: (validation_ref,),  # noqa: ARG005
    )
    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None, **_kwargs: _IDECompleteLLM())
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
    graph_count_before_promote = len(main.RESEARCH_GRAPH_STORE.commands())
    coverage_count_before_promote = len(
        main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    )
    promoted = client.post(
        f"/api/ide/runs/{run.json()['run_id']}/promote",
        json={"record_name": f"record {secret}", "market_data_use_validation_refs": [validation_ref]},
    )
    assert promoted.status_code == 400, promoted.text
    assert "formal IDE promotion requires rdp_package_id" in promoted.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == graph_count_before_promote
    assert (
        len(main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records())
        == coverage_count_before_promote
    )
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

    responses = [saved.json(), run.json(), completed.json()]
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


def test_ide_run_owner_resolves_section9_snapshot_before_sandbox_and_binds_qro(
    ide_api,
    monkeypatch,
):
    client, main = ide_api
    validation_ref = "market_data_use:ide:accepted"
    monkeypatch.setattr(
        main,
        "_ide_strategy_market_data_use_validation_refs",
        lambda payload, *, owner_user_id, operation, fallback_refs=None: (validation_ref,),  # noqa: ARG005
    )
    saved = client.post(
        "/api/ide/strategies",
        json={
            "name": "section9_bound",
            "asset_class": "crypto_perp",
            "code": "quantbt.emit_result({'ok': 1})",
            "market_data_use_validation_refs": [validation_ref],
        },
    )
    assert saved.status_code == 200, saved.text
    strategy_id = saved.json()["strategy_id"]

    class _Registry:
        def snapshot(self, snapshot_ref, *, owner_user_id):  # noqa: ANN001
            assert snapshot_ref == "s9snap_exact"
            assert owner_user_id == "u_alice"
            return SimpleNamespace(source_strategy_ref=strategy_id)

    monkeypatch.setattr(main, "SECTION9_EVIDENCE_REGISTRY", _Registry())
    response = client.post(
        "/api/ide/strategies/section9_bound/run",
        json={
            "market_data_use_validation_refs": [validation_ref],
            "section9_evidence_ref": "s9snap_exact",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["section9_evidence_ref"] == "s9snap_exact"
    command = next(
        item
        for item in main.RESEARCH_GRAPH_STORE.commands()
        if item.command_id == response.json()["research_graph_command_id"]
    )
    assert command.payload["qro"].input_contract["section9_evidence_ref"] == "s9snap_exact"


def test_ide_run_rejects_section9_snapshot_for_another_strategy_before_sandbox(
    ide_api,
    monkeypatch,
):
    client, main = ide_api
    validation_ref = "market_data_use:ide:accepted"
    monkeypatch.setattr(
        main,
        "_ide_strategy_market_data_use_validation_refs",
        lambda payload, *, owner_user_id, operation, fallback_refs=None: (validation_ref,),  # noqa: ARG005
    )
    saved = client.post(
        "/api/ide/strategies",
        json={
            "name": "section9_mismatch",
            "asset_class": "crypto_perp",
            "code": "quantbt.emit_result({'ok': 1})",
            "market_data_use_validation_refs": [validation_ref],
        },
    )
    assert saved.status_code == 200, saved.text
    monkeypatch.setattr(
        main,
        "SECTION9_EVIDENCE_REGISTRY",
        SimpleNamespace(
            snapshot=lambda snapshot_ref, *, owner_user_id: SimpleNamespace(  # noqa: ARG005
                source_strategy_ref="stg_other"
            )
        ),
    )
    before = len(main.IDE_SERVICE.list_runs("alice"))
    response = client.post(
        "/api/ide/strategies/section9_mismatch/run",
        json={
            "market_data_use_validation_refs": [validation_ref],
            "section9_evidence_ref": "s9snap_wrong",
        },
    )
    assert response.status_code == 422
    assert len(main.IDE_SERVICE.list_runs("alice")) == before
