from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from conftest import build_verified_spine_chain
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.lineage.ids import content_hash
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
    PersistentGoalValidationReceiptRegistry,
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
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver


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
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    store = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validation_store = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    chain_store, chain, _ledger = build_verified_spine_chain(tmp_path, _math_chain())
    store._test_chain_ref = chain.chain_ref
    store._test_chain_store = chain_store
    store._test_spine_closure = chain_store.verified_chain_record_refs(
        chain.chain_ref,
        owner="u1",
    )
    store._test_proof_ledger = proof_ledger
    store._test_coverage_store = coverage_store
    store._test_validation_store = validation_store
    monkeypatch.setattr(main, "COMPILER_IR_STORE", store)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validation_store)
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
        "owner": "dreaminate",
        "target_runtime": RuntimeStatus.OFFLINE,
        "compiler_version": "governed-compiler-ir.v1",
        "mock_profile": "none",
    }
    data.update(overrides)
    return CompilerIRRecord(**data)


def _verified_ir(store, **overrides) -> CompilerIRRecord:
    closure = store._test_spine_closure
    return _ir(
        theory_binding_refs=closure.theory_binding_refs,
        consistency_check_refs=closure.consistency_check_refs,
        mathematical_spine_chain_refs=(store._test_chain_ref,),
        owner="u1",
        **overrides,
    )


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
        "owner": "dreaminate",
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


def _configure_compiler_resolver(store, graph_store) -> None:
    evidence_store = main._active_entrypoint_evidence_registry()

    def lifecycle_loader(ref: str, owner: str):
        matches = []
        try:
            matches.append(store.canonical_artifact(ref, owner=owner))
        except KeyError:
            pass
        try:
            matches.append(store._test_chain_store.verified_chain(ref, owner=owner))
        except (KeyError, ValueError):
            pass
        if len(matches) != 1:
            raise LookupError("test compiler lifecycle ref is missing or ambiguous")
        return matches[0]

    store._test_coverage_store.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph_store,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=store._test_chain_store,
            compiler_store=store,
            goal_validation_receipt_registry=store._test_validation_store,
            platform_source_evidence_registry=evidence_store,
            lifecycle_loaders=(lifecycle_loader,),
        )
    )


def _compile_qro_through_api(client, store, monkeypatch, *, qro=None):
    graph_store = ResearchGraphStore()
    qro = qro or _graph_qro(
        theory_implementation_binding=(
            store._test_spine_closure.theory_binding_refs[0]
        )
    )
    command_id = graph_store.apply(_graph_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph_store)
    _configure_compiler_resolver(store, graph_store)
    response = client.post(
        "/api/research-os/compiler/compile_qro",
        json={
            "qro_id": qro.qro_id,
            "graph_command_refs": [command_id],
        },
    )
    assert response.status_code == 200, response.text
    canonical = store.canonical_records(owner="u1")
    assert len(canonical.irs) == 1
    assert len(canonical.passes) == 1
    [coverage] = store._test_coverage_store.records(owner="u1")
    return SimpleNamespace(
        response=response,
        qro=qro,
        command_id=command_id,
        graph_store=graph_store,
        ir=canonical.irs[0],
        compiler_pass=canonical.passes[0],
        coverage=coverage,
    )


def _artifact_for_compile(compiled, store, **overrides) -> CompilerArtifactRecord:
    data = {
        "artifact_ref": "",
        "source_ir_refs": (compiled.ir.ir_ref,),
        "compiler_pass_refs": (compiled.compiler_pass.pass_ref,),
        "graph_command_refs": compiled.ir.graph_command_refs,
        "canonical_command_refs": compiled.ir.canonical_command_refs,
        "deterministic_run_plan_ref": compiled.ir.deterministic_run_plan_ref,
        "environment_lock_ref": compiled.ir.environment_lock_ref,
        "permission_ref": compiled.ir.permission_ref,
        "evidence_refs": compiled.ir.evidence_refs,
        "validation_refs": compiled.ir.validation_refs,
        "mathematical_spine_chain_refs": (store._test_chain_ref,),
        "owner": "u1",
        "target_runtime": compiled.ir.target_runtime,
        "compiler_version": compiled.ir.compiler_version,
        "mock_profile": compiled.ir.mock_profile,
    }
    data.update(overrides)
    return _artifact(**data)


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


def test_canonical_compiler_reads_exclude_legacy_jsonl_rows(tmp_path):
    path = tmp_path / "compiler_ir.jsonl"
    legacy = PersistentCompilerIRStore(path)
    legacy.record_ir(_ir(owner="u1"))
    legacy.record_pass(_compiler_pass(actor="u1"))

    store = PersistentCompilerIRStore(
        path,
        proof_ledger=GoalProofLedger(tmp_path / "goal_proof_ledger"),
        legacy_read_only=True,
    )

    assert len(store.irs(owner="u1")) == 1
    assert len(store.passes(owner="u1")) == 1
    canonical = store.canonical_records(owner="u1")
    assert canonical.owner == "u1"
    assert canonical.irs == ()
    assert canonical.passes == ()
    assert canonical.artifacts == ()
    with pytest.raises(KeyError):
        store.canonical_ir("compiler_ir:strategy:001", owner="u1")
    with pytest.raises(KeyError):
        store.canonical_compiler_pass(
            "compiler_pass:strategy:001",
            owner="u1",
        )


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


def test_persistent_compiler_store_isolates_same_refs_by_owner(tmp_path):
    path = tmp_path / "compiler_ir.jsonl"
    store = PersistentCompilerIRStore(path)
    for owner in ("alice", "bob"):
        store.record_ir(_ir(owner=owner))
        store.record_pass(_compiler_pass(actor=owner))
        store.record_artifact(_artifact(owner=owner))
    store.record_ir(_ir(owner="alice"))
    store.record_pass(_compiler_pass(actor="alice"))
    store.record_artifact(_artifact(owner="alice"))

    assert store.ir("compiler_ir:strategy:001", owner="alice").owner == "alice"
    assert store.ir("compiler_ir:strategy:001", owner="bob").owner == "bob"
    assert store.compiler_pass("compiler_pass:strategy:001", owner="alice").actor == "alice"
    assert store.artifact("compiler_artifact:strategy:001", owner="bob").owner == "bob"
    with pytest.raises(ValueError, match="owner-ambiguous"):
        store.ir("compiler_ir:strategy:001")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 6

    reloaded = PersistentCompilerIRStore(path)
    assert len(reloaded.irs(owner="alice")) == 1
    assert len(reloaded.irs(owner="bob")) == 1
    assert reloaded.legacy_quarantined_counts() == {
        "irs": 0,
        "passes": 0,
        "artifacts": 0,
    }


def test_persistent_compiler_store_quarantines_valid_v1_history(tmp_path):
    path = tmp_path / "compiler_ir.jsonl"
    legacy_ir = _payload(_ir(owner=""))
    legacy_ir["target_runtime"] = "offline"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "compiler_ir_recorded",
                "ir": legacy_ir,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = PersistentCompilerIRStore(path)

    assert store.irs() == []
    assert store.legacy_quarantined_counts()["irs"] == 1


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


def test_compiler_api_rejects_direct_ir_and_pass_without_proof_writes(
    tmp_path,
    monkeypatch,
):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    before = store._test_proof_ledger.current(owner="u1")
    try:
        ir = client.post(
            "/api/research-os/compiler/ir",
            json=_payload(_verified_ir(store)),
        )
        compiler_pass = client.post(
            "/api/research-os/compiler/passes",
            json=_payload(_compiler_pass(actor="u1")),
        )

        assert ir.status_code == 422
        assert ir.json()["detail"] == (
            "direct compiler IR proof writes are disabled; use "
            "/api/research-os/compiler/compile_qro"
        )
        assert compiler_pass.status_code == 422
        assert compiler_pass.json()["detail"] == (
            "direct compiler pass proof writes are disabled; use "
            "/api/research-os/compiler/compile_qro"
        )
        after = store._test_proof_ledger.current(owner="u1")
        assert after.head_digest == before.head_digest
        assert after.heads == before.heads
        canonical = store.canonical_records(owner="u1")
        assert canonical.irs == ()
        assert canonical.passes == ()
        assert canonical.artifacts == ()
        assert store._test_coverage_store.records(owner="u1") == []

        summary = client.get("/api/research-os/compiler/summary")
        assert summary.status_code == 200
        assert summary.json() == {
            "user": "u1",
            "ir_total": 0,
            "pass_total": 0,
            "artifact_total": 0,
            "irs": [],
            "passes": [],
            "artifacts": [],
        }
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_records_artifact_manifest(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        compiled = _compile_qro_through_api(client, store, monkeypatch)
        artifact = client.post(
            "/api/research-os/compiler/artifacts",
            json={
                "source_ir_refs": [compiled.ir.ir_ref],
                "compiler_pass_refs": [compiled.compiler_pass.pass_ref],
            },
        )
        assert artifact.status_code == 200, artifact.text
        artifact_body = artifact.json()
        expected_artifact_ref = artifact_body["artifact_ref"]
        assert artifact_body["artifact_ref"] == expected_artifact_ref
        assert artifact_body["artifact_kind"] == "deterministic_run_plan_manifest"
        assert artifact_body["source_ir_refs"] == [compiled.ir.ir_ref]
        assert artifact_body["compiler_pass_refs"] == [
            compiled.compiler_pass.pass_ref
        ]
        assert artifact_body["mathematical_spine_chain_refs"] == [
            store._test_chain_ref
        ]
        assert artifact_body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
        assert artifact_body["executable"] is False
        assert artifact_body["recorded_by"] == "u1"
        canonical_artifact = store.canonical_artifact(
            expected_artifact_ref,
            owner="u1",
        )
        assert canonical_artifact.output_contract_ref == (
            "qro_output_contract:"
            + content_hash(
                {
                    "qro_ref": compiled.qro.qro_id,
                    "output_contract": compiled.qro.output_contract,
                }
            )
        )
        assert canonical_artifact.manifest_hash.startswith("sha256:")
        assert canonical_artifact.evidence_refs == compiled.ir.evidence_refs
        assert canonical_artifact.validation_refs == compiled.ir.validation_refs

        coverage_by_entrypoint = {
            record.entrypoint_ref: record
            for record in store._test_coverage_store.records(owner="u1")
        }
        pass_coverage = coverage_by_entrypoint["compile_qro:ide"]
        artifact_coverage = coverage_by_entrypoint[
            "compiler_artifact:deterministic_run_plan_manifest"
        ]
        assert pass_coverage.entrypoint_ref == "compile_qro:ide"
        assert artifact_coverage.entrypoint_ref == "compiler_artifact:deterministic_run_plan_manifest"
        assert artifact_coverage.lifecycle_refs == (
            expected_artifact_ref,
            store._test_chain_ref,
        )
        assert artifact_coverage.replay_refs == (
            f"replay:research_graph:{compiled.command_id}",
            f"replay:compiler_ir:{compiled.ir.ir_ref}",
            f"replay:compiler_pass:{compiled.compiler_pass.pass_ref}",
        )
        assert artifact_coverage.compiler_ir_refs == (compiled.ir.ir_ref,)
        assert artifact_coverage.compiler_pass_refs == (
            compiled.compiler_pass.pass_ref,
        )

        canonical = store.canonical_records(owner="u1")
        assert canonical.irs == (compiled.ir,)
        assert canonical.passes == (compiled.compiler_pass,)
        assert canonical.artifacts == (canonical_artifact,)
        assert store.canonical_ir(compiled.ir.ir_ref, owner="u1") == compiled.ir
        assert store.canonical_compiler_pass(
            compiled.compiler_pass.pass_ref,
            owner="u1",
        ) == compiled.compiler_pass
        assert store.canonical_artifact(
            expected_artifact_ref,
            owner="u1",
        ) == canonical_artifact

        summary = client.get("/api/research-os/compiler/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["artifact_total"] == 1
        assert body["artifacts"][0]["manifest_hash"] == canonical_artifact.manifest_hash
        assert body["artifacts"][0]["mathematical_spine_chain_refs"] == [
            store._test_chain_ref
        ]
        assert body["artifacts"][0]["executable"] is False
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_codegen_claim_without_persisting_artifact(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        compiled = _compile_qro_through_api(client, store, monkeypatch)
        before = store._test_proof_ledger.current(owner="u1")
        rejected = client.post(
            "/api/research-os/compiler/artifacts",
            json={
                "source_ir_refs": [compiled.ir.ir_ref],
                "compiler_pass_refs": [compiled.compiler_pass.pass_ref],
                "artifact_kind": "executable_strategy",
                "executable": True,
                "contains_source_code": True,
            },
        )
        assert rejected.status_code == 422
        assert "caller-authored proof fields are forbidden" in rejected.json()["detail"]
        after = store._test_proof_ledger.current(owner="u1")
        assert after.head_digest == before.head_digest
        assert after.heads == before.heads
        assert store.canonical_records(owner="u1").artifacts == ()
        assert len(store._test_coverage_store.records(owner="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_caller_manifest_and_contract_without_writes(
    tmp_path,
    monkeypatch,
):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        compiled = _compile_qro_through_api(client, store, monkeypatch)
        payload = {
            "source_ir_refs": [compiled.ir.ir_ref],
            "compiler_pass_refs": [compiled.compiler_pass.pass_ref],
            "manifest_hash": "sha256:caller-forged",
            "output_contract_ref": "output_contract:caller-forged",
        }
        before = store._test_proof_ledger.current(owner="u1")

        rejected = client.post(
            "/api/research-os/compiler/artifacts",
            json=payload,
        )

        assert rejected.status_code == 422
        assert "caller-authored proof fields are forbidden" in rejected.json()["detail"]
        after = store._test_proof_ledger.current(owner="u1")
        assert after.head_digest == before.head_digest
        assert after.heads == before.heads
        assert store.canonical_records(owner="u1").artifacts == ()
        assert len(store._test_coverage_store.records(owner="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_api_rejects_unknown_mathematical_spine_chain_without_partial_artifact(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        compiled = _compile_qro_through_api(client, store, monkeypatch)
        before = store._test_proof_ledger.current(owner="u1")

        rejected = client.post(
            "/api/research-os/compiler/artifacts",
            json={
                "source_ir_refs": [compiled.ir.ir_ref],
                "compiler_pass_refs": [compiled.compiler_pass.pass_ref],
                "mathematical_spine_chain_refs": ["math_spine_chain:missing"],
            },
        )
        assert rejected.status_code == 422
        assert "caller-authored proof fields are forbidden" in rejected.json()["detail"]
        after = store._test_proof_ledger.current(owner="u1")
        assert after.head_digest == before.head_digest
        assert after.heads == before.heads
        assert store.canonical_records(owner="u1").artifacts == ()
        assert len(store._test_coverage_store.records(owner="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_artifact_rejects_noncanonical_source_without_partial_write(
    tmp_path,
    monkeypatch,
):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        compiled = _compile_qro_through_api(client, store, monkeypatch)
        before = store._test_proof_ledger.current(owner="u1")
        rejected = client.post(
            "/api/research-os/compiler/artifacts",
            json={
                "source_ir_refs": ["compiler_ir:missing"],
                "compiler_pass_refs": [compiled.compiler_pass.pass_ref],
            },
        )
        assert rejected.status_code == 422
        assert "canonical current proof heads" in rejected.json()["detail"]
        after = store._test_proof_ledger.current(owner="u1")
        assert after.head_digest == before.head_digest
        assert after.heads == before.heads
        assert store.canonical_records(owner="u1").artifacts == ()
        assert len(store._test_coverage_store.records(owner="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_compile_qro_records_ir_and_pass_from_research_graph(tmp_path, monkeypatch):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    try:
        compiled = _compile_qro_through_api(client, store, monkeypatch)
        body = compiled.response.json()
        qro = compiled.qro
        command_id = compiled.command_id
        ir = compiled.ir
        compiler_pass = compiled.compiler_pass
        coverage = compiled.coverage
        assert body["source_qro_ref"] == qro.qro_id
        assert body["graph_command_refs"] == [command_id]
        assert body["entrypoint_coverage_ref"] == coverage.coverage_ref
        assert ir.source_qro_refs == (qro.qro_id,)
        assert ir.graph_command_refs == (command_id,)
        assert ir.canonical_command_refs == (
            f"research_graph_command:{command_id}",
            "entrypoint:compile_qro:ide",
        )
        assert len(ir.validation_refs) == 1
        receipt_ref = ir.validation_refs[0]
        assert receipt_ref.startswith("goal_validation_receipt:")
        receipt_decision = main.GOAL_VALIDATION_RECEIPT_REGISTRY.validate_validation_ref(
            receipt_ref,
            owner_user_id="u1",
            subject_qro_refs=(qro.qro_id,),
            graph_command_refs=(command_id,),
        )
        assert receipt_decision.accepted, receipt_decision.violations
        assert ir.environment_lock_ref.startswith("environment_lock:compile_qro:")
        assert compiler_pass.output_ir_ref == ir.ir_ref
        assert compiler_pass.input_qro_refs == (qro.qro_id,)
        assert compiler_pass.tool_record_refs == (
            "api:compile_qro",
            "compile_qro:ide",
            "tool:ide-save",
        )
        assert coverage.entry_source == "ide"
        assert coverage.qro_refs == (qro.qro_id,)
        assert coverage.research_graph_command_refs == (command_id,)
        assert coverage.compiler_ir_refs == (ir.ir_ref,)
        assert coverage.compiler_pass_refs == (compiler_pass.pass_ref,)
        assert coverage.evidence_refs == ir.evidence_refs
        assert coverage.validation_refs == ir.validation_refs
        assert coverage.permission_refs == (ir.permission_ref,)

        summary = client.get("/api/research-os/compiler/summary")
        assert summary.status_code == 200
        assert summary.json()["ir_total"] == 1
        assert summary.json()["pass_total"] == 1
        assert summary.json()["artifact_total"] == 0
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_compiler_compile_qro_rejects_caller_authority_without_proof_writes(
    tmp_path,
    monkeypatch,
):
    client, store = _client_with_compiler_store(tmp_path, monkeypatch)
    graph_store = ResearchGraphStore()
    qro = _graph_qro()
    command_id = graph_store.apply(_graph_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph_store)
    _configure_compiler_resolver(store, graph_store)
    before = store._test_proof_ledger.current(owner="u1")
    try:
        response = client.post(
            "/api/research-os/compiler/compile_qro",
            json={
                "qro_id": qro.qro_id,
                "graph_command_refs": [command_id],
                "entrypoint_ref": "caller:entrypoint",
                "actor_source": "system",
                "goal_sections": ["§0", "§17"],
                "validation_refs": ["validation:caller-passed"],
                "environment_lock_ref": "env:caller",
                "permission_ref": "permission:caller",
                "theory_binding_refs": ["binding:caller"],
                "consistency_check_refs": ["check:caller"],
                "mathematical_spine_chain_refs": ["spine:caller"],
            },
        )

        assert response.status_code == 422
        assert "caller-authored proof fields are forbidden" in response.json()[
            "detail"
        ]
        after = store._test_proof_ledger.current(owner="u1")
        assert after.head_digest == before.head_digest
        assert after.heads == before.heads
        assert store.canonical_records(owner="u1").irs == ()
        assert store.canonical_records(owner="u1").passes == ()
        assert store._test_coverage_store.records(owner="u1") == []
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
            },
        )
        assert response.status_code == 422
        assert "goal_entrypoint_silent_mock_fallback" in response.json()["detail"]
        assert not store.path.exists()
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
