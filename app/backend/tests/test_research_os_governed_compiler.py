from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    ActorSource,
    CompilerArtifactRecord,
    CompilerIRRecord,
    CompilerPassRecord,
    ConsistencyStatus,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    MathematicalSpineChainRecord,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentMathematicalSpineChainRegistry,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphStore,
    RuntimeStatus,
    validate_compiler_artifact,
    validate_compiler_ir,
    validate_compiler_pass,
)


def _math_chain(**overrides) -> MathematicalSpineChainRecord:
    data = {
        "chain_ref": "math_spine_chain:btc_momentum:v1",
        "data_semantics_ref": "dataset_semantics:btc_1d",
        "factor_ref": "factor:momentum_20d",
        "model_ref": "model:momentum_classifier:v1",
        "forecast_ref": "forecast:btc_momentum:v1",
        "signal_contract_ref": "signal_contract:btc_momentum:v1",
        "strategy_book_ref": "strategy_book:btc_momentum:v1",
        "portfolio_policy_ref": "portfolio_policy:btc_momentum:v1",
        "risk_policy_ref": "risk_policy:btc_momentum:v1",
        "execution_policy_ref": "execution_policy:paper_btc:v1",
        "backtest_run_ref": "backtest_run:bt1",
        "attribution_ref": "attribution:bt1",
        "monitor_ref": "monitor:weekly_btc_momentum",
        "theory_binding_refs": ("tbind:momentum",),
        "consistency_check_refs": ("ccheck:momentum",),
        "methodology_choice_ref": "mchoice:standard",
        "responsibility_boundary_ref": "resp:standard",
        "evidence_refs": ("evidence:bt1",),
        "validation_refs": ("pytest:test_governed_compiler",),
        "consistency_verdict": ConsistencyStatus.ACCEPTED,
        "target_runtime": RuntimeStatus.PAPER,
        "recorded_by": "u1",
    }
    data.update(overrides)
    return MathematicalSpineChainRecord(**data)


def _client_with_compiler_store(tmp_path, monkeypatch):
    store = PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl")
    coverage_store = PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl")
    chain_store = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")
    chain_store.record_chain(_math_chain())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", store)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", chain_store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store


def _ir(**overrides) -> CompilerIRRecord:
    data = {
        "ir_ref": "compiler_ir:strategy:001",
        "source_qro_refs": ("qro:strategy-book:001",),
        "graph_command_refs": ("rgcmd:strategy-save",),
        "canonical_command_refs": ("command:strategy-save",),
        "node_refs": ("node:signal", "node:backtest"),
        "edge_refs": ("edge:signal-to-backtest",),
        "artifact_refs": ("artifact:strategy.py",),
        "theory_binding_refs": ("tbind:momentum",),
        "consistency_check_refs": ("ccheck:momentum",),
        "evidence_refs": ("evidence:strategy-save",),
        "validation_refs": ("pytest:strategy-save",),
        "permission_ref": "permission:ide.strategy.write",
        "deterministic_run_plan_ref": "runplan:strategy:001",
        "rollback_ref": "rollback:strategy:001",
        "environment_lock_ref": "env:poetry-lock",
        "target_runtime": RuntimeStatus.OFFLINE,
        "compiler_version": "governed-compiler-ir.v1",
        "mock_profile": "none",
    }
    data.update(overrides)
    return CompilerIRRecord(**data)


def _compiler_pass(**overrides) -> CompilerPassRecord:
    data = {
        "pass_ref": "compiler_pass:strategy:001",
        "pass_name": "strategy_book_to_deterministic_run_plan",
        "input_ir_refs": (),
        "output_ir_ref": "compiler_ir:strategy:001",
        "input_qro_refs": ("qro:strategy-book:001",),
        "graph_command_refs": ("rgcmd:strategy-save",),
        "canonical_command_refs": ("command:strategy-save",),
        "actor": "dreaminate",
        "actor_source": ActorSource.USER_MANUAL,
        "entry_source": EntrySource.IDE,
        "permission_ref": "permission:ide.strategy.write",
        "tool_record_refs": ("tool:compiler",),
        "evidence_refs": ("evidence:strategy-save",),
        "validation_refs": ("pytest:strategy-save",),
        "deterministic_run_plan_ref": "runplan:strategy:001",
        "rollback_ref": "rollback:strategy:001",
    }
    data.update(overrides)
    return CompilerPassRecord(**data)


def _artifact(**overrides) -> CompilerArtifactRecord:
    data = {
        "artifact_ref": "compiler_artifact:strategy:001",
        "artifact_kind": "deterministic_run_plan_manifest",
        "source_ir_refs": ("compiler_ir:strategy:001",),
        "compiler_pass_refs": ("compiler_pass:strategy:001",),
        "graph_command_refs": ("rgcmd:strategy-save",),
        "canonical_command_refs": ("command:strategy-save",),
        "deterministic_run_plan_ref": "runplan:strategy:001",
        "environment_lock_ref": "env:poetry-lock",
        "permission_ref": "permission:ide.strategy.write",
        "output_contract_ref": "contract:deterministic-run-plan:v1",
        "manifest_hash": "sha256:compiler-manifest",
        "evidence_refs": ("evidence:strategy-save",),
        "validation_refs": ("pytest:strategy-save",),
        "mathematical_spine_chain_refs": ("math_spine_chain:btc_momentum:v1",),
        "target_runtime": RuntimeStatus.OFFLINE,
        "compiler_version": "governed-compiler-ir.v1",
        "mock_profile": "none",
        "executable": False,
    }
    data.update(overrides)
    return CompilerArtifactRecord(**data)


def _graph_qro(**overrides) -> QRORecord:
    data = {
        "qro_type": QROType.STRATEGY_BOOK,
        "owner": "u1",
        "actor": ActorSource.USER_MANUAL,
        "input_contract": {"strategy_id": "strategy_demo", "code_hash": "hash_code"},
        "output_contract": {"strategy_book_ref": "strategy:demo"},
        "market": "crypto",
        "universe": "BTCUSDT",
        "horizon": "30d",
        "frequency": "1d",
        "lineage": ("ide", "strategy", "save"),
        "implementation_hash": "strategy:hash_code",
        "assumptions": ("strategy source was saved before compiler pass",),
        "known_limits": ("unit fixture only",),
        "failure_modes": ("compiler pass can omit required validation refs",),
        "validation_plan": ("run compile_qro endpoint",),
        "definition_status": DefinitionStatus.IMPLEMENTED,
        "evidence_status": EvidenceStatus.EXPLORATORY,
        "runtime_status": RuntimeStatus.OFFLINE,
        "evidence_refs": ("evidence:strategy-save",),
        "permission": "permission:ide.strategy.write",
        "allowed_environment": RuntimeStatus.OFFLINE,
    }
    data.update(overrides)
    return QRORecord(**data)


def _graph_command(qro: QRORecord, **overrides) -> ResearchGraphCommand:
    data = {
        "source": EntrySource.IDE,
        "command_type": "upsert_qro",
        "actor_source": ActorSource.USER_MANUAL,
        "actor": "u1",
        "payload": {"qro": qro},
        "evidence_refs": ("graph:evidence:strategy-save",),
        "tool_record_refs": ("tool:ide-save",),
    }
    data.update(overrides)
    return ResearchGraphCommand(**data)


def _payload(record) -> dict:
    return record.__dict__.copy()


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def test_compiler_ir_requires_qro_graph_command_command_evidence_and_validation_refs():
    decision = validate_compiler_ir(
        _ir(
            source_qro_refs=(),
            graph_command_refs=(),
            canonical_command_refs=(),
            evidence_refs=(),
            validation_refs=(),
        )
    )
    assert not decision.accepted
    assert _codes(decision) == {"compiler_required_ref_missing"}
    assert {violation.field for violation in decision.violations} >= {
        "source_qro_refs",
        "graph_command_refs",
        "canonical_command_refs",
        "evidence_refs",
        "validation_refs",
    }


def test_compiler_pass_rejects_direct_graph_mutation_permission_bypass_and_raw_llm_ir():
    decision = validate_compiler_pass(
        _compiler_pass(
            direct_graph_mutation=True,
            bypassed_permission=True,
            raw_llm_output_embedded_as_ir=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "compiler_pass_direct_graph_mutation",
        "compiler_pass_bypassed_permission",
        "compiler_pass_raw_llm_output_as_ir",
    }


def test_compiler_artifact_requires_manifest_refs_and_rejects_fake_codegen():
    decision = validate_compiler_artifact(
        _artifact(
            source_ir_refs=(),
            compiler_pass_refs=(),
            canonical_command_refs=(),
            evidence_refs=(),
            validation_refs=(),
            mathematical_spine_chain_refs=(),
            artifact_kind="strategy_source",
            executable=True,
            contains_source_code=True,
            raw_llm_output_embedded=True,
            plaintext_secret_embedded=True,
            silent_mock_fallback=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "compiler_required_ref_missing",
        "compiler_artifact_source_generation_not_implemented",
        "compiler_artifact_executable_not_supported",
        "compiler_artifact_contains_source_code",
        "compiler_artifact_raw_llm_output",
        "compiler_artifact_plaintext_secret",
        "compiler_artifact_silent_mock_fallback",
    }
    assert {violation.field for violation in decision.violations} >= {
        "source_ir_refs",
        "compiler_pass_refs",
        "canonical_command_refs",
        "evidence_refs",
        "validation_refs",
        "mathematical_spine_chain_refs",
    }


def test_persistent_compiler_store_replays_ir_and_pass(tmp_path):
    path = tmp_path / "compiler_ir.jsonl"
    store = PersistentCompilerIRStore(path)
    store.record_ir(_ir())
    store.record_pass(_compiler_pass())

    reloaded = PersistentCompilerIRStore(path)
    assert reloaded.ir("compiler_ir:strategy:001").source_qro_refs == ("qro:strategy-book:001",)
    assert reloaded.compiler_pass("compiler_pass:strategy:001").output_ir_ref == "compiler_ir:strategy:001"


def test_persistent_compiler_store_replays_artifact_manifest(tmp_path):
    path = tmp_path / "compiler_ir.jsonl"
    store = PersistentCompilerIRStore(path)
    store.record_ir(_ir())
    store.record_pass(_compiler_pass())
    store.record_artifact(_artifact())

    reloaded = PersistentCompilerIRStore(path)
    assert reloaded.artifact("compiler_artifact:strategy:001").source_ir_refs == ("compiler_ir:strategy:001",)
    assert reloaded.artifact("compiler_artifact:strategy:001").mathematical_spine_chain_refs == (
        "math_spine_chain:btc_momentum:v1",
    )
    assert reloaded.artifacts()[0].executable is False


def test_persistent_compiler_store_rejects_artifact_for_unrecorded_ir_or_pass(tmp_path):
    store = PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl")

    with pytest.raises(ValueError, match="source_ir_ref"):
        store.record_artifact(_artifact())

    assert not store.path.exists()


def test_persistent_compiler_store_rejects_pass_for_unknown_output_ir(tmp_path):
    store = PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl")

    with pytest.raises(ValueError, match="output_ir_ref"):
        store.record_pass(_compiler_pass())

    assert not store.path.exists()


def test_compiler_api_records_summary(tmp_path, monkeypatch):
    client, _store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        ir = client.post("/api/research-os/compiler/ir", json=_payload(_ir()))
        assert ir.status_code == 200
        assert ir.json() == {"ir_ref": "compiler_ir:strategy:001", "recorded_by": "u1"}

        compiler_pass = client.post("/api/research-os/compiler/passes", json=_payload(_compiler_pass()))
        assert compiler_pass.status_code == 200
        assert compiler_pass.json()["output_ir_ref"] == "compiler_ir:strategy:001"
        assert compiler_pass.json()["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
        [coverage] = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
        assert coverage.entry_source == "ide"
        assert coverage.entrypoint_ref == "compiler_pass:strategy_book_to_deterministic_run_plan"
        assert coverage.compiler_ir_refs == ("compiler_ir:strategy:001",)
        assert coverage.compiler_pass_refs == ("compiler_pass:strategy:001",)

        summary = client.get("/api/research-os/compiler/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["user"] == "u1"
        assert body["ir_total"] == 1
        assert body["pass_total"] == 1
        assert body["artifact_total"] == 0
        assert body["irs"][0]["canonical_command_refs"] == ["command:strategy-save"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_records_artifact_manifest(tmp_path, monkeypatch):
    client, _store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/compiler/ir", json=_payload(_ir())).status_code == 200
        assert client.post("/api/research-os/compiler/passes", json=_payload(_compiler_pass())).status_code == 200

        artifact = client.post("/api/research-os/compiler/artifacts", json=_payload(_artifact()))
        assert artifact.status_code == 200, artifact.text
        artifact_body = artifact.json()
        assert artifact_body["artifact_ref"] == "compiler_artifact:strategy:001"
        assert artifact_body["artifact_kind"] == "deterministic_run_plan_manifest"
        assert artifact_body["source_ir_refs"] == ["compiler_ir:strategy:001"]
        assert artifact_body["compiler_pass_refs"] == ["compiler_pass:strategy:001"]
        assert artifact_body["mathematical_spine_chain_refs"] == ["math_spine_chain:btc_momentum:v1"]
        assert artifact_body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
        assert artifact_body["executable"] is False
        assert artifact_body["recorded_by"] == "u1"

        pass_coverage, artifact_coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
        assert pass_coverage.entrypoint_ref == "compiler_pass:strategy_book_to_deterministic_run_plan"
        assert artifact_coverage.entrypoint_ref == "compiler_artifact:deterministic_run_plan_manifest"
        assert artifact_coverage.lifecycle_refs == (
            "compiler_artifact:strategy:001",
            "math_spine_chain:btc_momentum:v1",
        )
        assert artifact_coverage.replay_refs[-1] == "replay:compiler_artifact:compiler_artifact:strategy:001"
        assert artifact_coverage.compiler_ir_refs == ("compiler_ir:strategy:001",)
        assert artifact_coverage.compiler_pass_refs == ("compiler_pass:strategy:001",)

        summary = client.get("/api/research-os/compiler/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["artifact_total"] == 1
        assert body["artifacts"][0]["manifest_hash"] == "sha256:compiler-manifest"
        assert body["artifacts"][0]["mathematical_spine_chain_refs"] == ["math_spine_chain:btc_momentum:v1"]
        assert body["artifacts"][0]["executable"] is False
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_codegen_claim_without_persisting_artifact(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/compiler/ir", json=_payload(_ir())).status_code == 200
        assert client.post("/api/research-os/compiler/passes", json=_payload(_compiler_pass())).status_code == 200
        rejected = client.post(
            "/api/research-os/compiler/artifacts",
            json=_payload(_artifact(artifact_kind="executable_strategy", executable=True, contains_source_code=True)),
        )
        assert rejected.status_code == 422
        assert "compiler_artifact_source_generation_not_implemented" in rejected.json()["detail"]
        reloaded = PersistentCompilerIRStore(store.path)
        assert reloaded.artifacts() == []
        assert len(main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_unknown_mathematical_spine_chain_without_partial_artifact(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/compiler/ir", json=_payload(_ir())).status_code == 200
        assert client.post("/api/research-os/compiler/passes", json=_payload(_compiler_pass())).status_code == 200

        rejected = client.post(
            "/api/research-os/compiler/artifacts",
            json=_payload(_artifact(mathematical_spine_chain_refs=("math_spine_chain:missing",))),
        )
        assert rejected.status_code == 422
        assert "mathematical_spine_chain_ref" in rejected.json()["detail"]
        assert store.artifacts() == []
        assert len(main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_artifact_rejects_silent_mock_ir_coverage_without_partial_write(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        store.record_ir(_ir(mock_profile="silent"))
        store.record_pass(_compiler_pass())

        rejected = client.post("/api/research-os/compiler/artifacts", json=_payload(_artifact()))
        assert rejected.status_code == 422
        assert "goal_entrypoint_silent_mock_fallback" in rejected.json()["detail"]
        assert store.artifacts() == []
        assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_compile_qro_records_ir_and_pass_from_research_graph(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    graph_store = ResearchGraphStore()
    qro = _graph_qro()
    command_id = graph_store.apply(_graph_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph_store)
    try:
        response = client.post(
            "/api/research-os/compiler/compile_qro",
            json={
                "qro_id": qro.qro_id,
                "validation_refs": ["pytest:test_compiler_compile_qro"],
                "environment_lock_ref": "env:test-lock",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_qro_ref"] == qro.qro_id
        assert body["graph_command_refs"] == [command_id]

        [ir] = store.irs()
        [compiler_pass] = store.passes()
        [coverage] = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
        assert body["entrypoint_coverage_ref"] == coverage.coverage_ref
        assert ir.source_qro_refs == (qro.qro_id,)
        assert ir.graph_command_refs == (command_id,)
        assert ir.canonical_command_refs == (f"research_graph_command:{command_id}",)
        assert ir.validation_refs == ("pytest:test_compiler_compile_qro",)
        assert ir.environment_lock_ref == "env:test-lock"
        assert compiler_pass.output_ir_ref == ir.ir_ref
        assert compiler_pass.input_qro_refs == (qro.qro_id,)
        assert compiler_pass.tool_record_refs[-1] == "api:compile_qro"
        assert coverage.entry_source == "ide"
        assert coverage.qro_refs == (qro.qro_id,)
        assert coverage.research_graph_command_refs == (command_id,)
        assert coverage.compiler_ir_refs == (ir.ir_ref,)
        assert coverage.compiler_pass_refs == (compiler_pass.pass_ref,)
        assert coverage.evidence_refs == ir.evidence_refs
        assert coverage.validation_refs == ir.validation_refs
        assert coverage.permission_refs == (ir.permission_ref,)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_compile_qro_rejects_unknown_qro_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    try:
        response = client.post(
            "/api/research-os/compiler/compile_qro",
            json={
                "qro_id": "qro_missing",
                "validation_refs": ["pytest:compile"],
                "environment_lock_ref": "env:test-lock",
            },
        )
        assert response.status_code == 422
        assert "not present in Research Graph commands" in response.json()["detail"]
        assert not store.path.exists()
        assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_compile_qro_rejects_missing_evidence_without_partial_write(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    graph_store = ResearchGraphStore()
    qro = _graph_qro(evidence_refs=())
    graph_store.apply(_graph_command(qro, evidence_refs=()))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph_store)
    try:
        response = client.post(
            "/api/research-os/compiler/compile_qro",
            json={
                "qro_id": qro.qro_id,
                "validation_refs": ["pytest:compile"],
                "environment_lock_ref": "env:test-lock",
            },
        )
        assert response.status_code == 422
        assert "evidence_refs" in response.json()["detail"]
        assert not store.path.exists()
        assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_compile_qro_rejects_silent_mock_coverage_without_partial_write(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    graph_store = ResearchGraphStore()
    qro = _graph_qro(mock_profile="silent")
    graph_store.apply(_graph_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph_store)
    try:
        response = client.post(
            "/api/research-os/compiler/compile_qro",
            json={
                "qro_id": qro.qro_id,
                "validation_refs": ["pytest:compile"],
                "environment_lock_ref": "env:test-lock",
            },
        )
        assert response.status_code == 422
        assert "goal_entrypoint_silent_mock_fallback" in response.json()["detail"]
        assert not store.path.exists()
        assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_invalid_ir_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/compiler/ir",
            json=_payload(_ir(source_qro_refs=(), graph_command_refs=(), canonical_command_refs=())),
        )
        assert rejected.status_code == 422
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_unsafe_pass_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/compiler/ir", json=_payload(_ir())).status_code == 200
        rejected = client.post(
            "/api/research-os/compiler/passes",
            json=_payload(
                _compiler_pass(
                    direct_graph_mutation=True,
                    bypassed_permission=True,
                    raw_llm_output_embedded_as_ir=True,
                )
            ),
        )
        assert rejected.status_code == 422
        reloaded = PersistentCompilerIRStore(store.path)
        assert [record.pass_ref for record in reloaded.passes()] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_silent_mock_pass_coverage_without_persisting_pass(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/compiler/ir", json=_payload(_ir(mock_profile="silent"))).status_code == 200
        rejected = client.post("/api/research-os/compiler/passes", json=_payload(_compiler_pass()))
        assert rejected.status_code == 422
        assert "goal_entrypoint_silent_mock_fallback" in rejected.json()["detail"]
        assert store.passes() == []
        assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_persistent_compiler_store_rejects_malformed_history(tmp_path):
    path = tmp_path / "compiler_ir.jsonl"
    path.write_text(
        '{"schema_version":1,"event_type":"compiler_ir_recorded","ir":{"ir_ref":"bad"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted Governed Compiler row"):
        PersistentCompilerIRStore(path)
