from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from app.research_os.compiler import (
    CompilerArtifactRecord,
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    RiskConsentEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphError,
    ResearchGraphStore,
    RuntimeStatus,
)


def _qro(ref: str, *, version: int = 1, implementation_hash: str = "impl:v1") -> QRORecord:
    return QRORecord(
        qro_id=ref,
        qro_type=QROType.QUANT_INTENT,
        owner="u1",
        actor=ActorSource.USER_MANUAL,
        input_contract={"intent_ref": ref},
        output_contract={"result_ref": f"result:{ref}:{version}"},
        market="crypto",
        universe="BTCUSDT",
        horizon="1d",
        frequency="1m",
        lineage=("api", ref),
        implementation_hash=implementation_hash,
        assumptions=("unit fixture",),
        known_limits=("unit fixture",),
        failure_modes=("forced failure",),
        validation_plan=("pytest",),
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
        version=version,
    )


def _graph_command(qro: QRORecord, *, timestamp: str) -> ResearchGraphCommand:
    return ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor="u1",
        payload={"qro": qro},
        evidence_refs=(f"evidence:{qro.qro_id}:{qro.version}",),
        tool_record_refs=("api:test.rollback",),
        timestamp=timestamp,
    )


def _ir(ref: str) -> CompilerIRRecord:
    return CompilerIRRecord(
        ir_ref=ref,
        source_qro_refs=(f"qro:{ref}",),
        graph_command_refs=(f"rgcmd:{ref}",),
        canonical_command_refs=(f"command:{ref}",),
        node_refs=(f"node:{ref}",),
        edge_refs=(),
        artifact_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        evidence_refs=(f"evidence:{ref}",),
        validation_refs=(f"pytest:{ref}",),
        permission_ref="permission:test",
        deterministic_run_plan_ref=f"runplan:{ref}",
        rollback_ref=f"rollback:{ref}",
        environment_lock_ref="env:test",
        owner="u1",
    )


def _compiler_pass(ref: str, ir: CompilerIRRecord, *, inputs: tuple[str, ...] = ()) -> CompilerPassRecord:
    return CompilerPassRecord(
        pass_ref=ref,
        pass_name="test_compile",
        input_ir_refs=inputs,
        output_ir_ref=ir.ir_ref,
        input_qro_refs=ir.source_qro_refs,
        graph_command_refs=ir.graph_command_refs,
        canonical_command_refs=ir.canonical_command_refs,
        actor="u1",
        actor_source=ActorSource.USER_MANUAL,
        entry_source=EntrySource.API,
        permission_ref=ir.permission_ref,
        tool_record_refs=("api:test.rollback",),
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        rollback_ref=ir.rollback_ref,
    )


def _artifact(ref: str, ir: CompilerIRRecord, compiler_pass: CompilerPassRecord) -> CompilerArtifactRecord:
    return CompilerArtifactRecord(
        artifact_ref=ref,
        artifact_kind="deterministic_run_plan_manifest",
        source_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        graph_command_refs=ir.graph_command_refs,
        canonical_command_refs=ir.canonical_command_refs,
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        environment_lock_ref=ir.environment_lock_ref,
        permission_ref=ir.permission_ref,
        output_contract_ref="contract:test",
        manifest_hash=f"hash:{ref}",
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        mathematical_spine_chain_refs=("math:test",),
        owner="u1",
    )


def _coverage(ref: str, *, entrypoint: str | None = None) -> GoalEntrypointCoverageRecord:
    entrypoint_ref = entrypoint or f"api:test.{ref}"
    values = {
        "entry_source": EntrySource.API,
        "entrypoint_ref": entrypoint_ref,
        "goal_sections": ("§0", "§1", "§8"),
        "qro_refs": (f"qro:{ref}",),
        "research_graph_command_refs": (f"rgcmd:{ref}",),
        "compiler_ir_refs": (f"ir:{ref}",),
        "compiler_pass_refs": (f"pass:{ref}",),
    }
    return GoalEntrypointCoverageRecord(
        coverage_ref=goal_entrypoint_coverage_identity(**values),
        **values,
        evidence_refs=(f"evidence:{ref}",),
        validation_refs=(f"pytest:{ref}",),
        permission_refs=("permission:test",),
        replay_refs=(f"replay:{ref}",),
        recorded_by="u1",
    )


def test_in_memory_graph_rollback_is_disabled_and_preserves_history():
    store = ResearchGraphStore()
    prior = _graph_command(_qro("qro:target"), timestamp="2026-01-01T00:00:00+00:00")
    current = _graph_command(
        _qro("qro:target", version=2, implementation_hash="impl:v2"),
        timestamp="2026-01-02T00:00:00+00:00",
    )
    unrelated = _graph_command(_qro("qro:unrelated"), timestamp="2026-01-03T00:00:00+00:00")
    for command in (prior, current, unrelated):
        store.apply(command)

    with pytest.raises(ResearchGraphError, match="append-only; rollback is unsupported"):
        store.rollback_exact_command(current)

    assert store.qro("qro:target") == current.payload["qro"]
    assert store.qro("qro:unrelated") == unrelated.payload["qro"]
    assert store.commands() == [prior, current, unrelated]


def test_persistent_graph_rollback_is_disabled_and_preserves_durable_history(tmp_path):
    path = tmp_path / "graph.jsonl"
    store = PersistentResearchGraphStore(path)
    prior = _graph_command(_qro("qro:target"), timestamp="2026-01-01T00:00:00+00:00")
    current = _graph_command(
        _qro("qro:target", version=2, implementation_hash="impl:v2"),
        timestamp="2026-01-02T00:00:00+00:00",
    )
    unrelated = _graph_command(_qro("qro:unrelated"), timestamp="2026-01-03T00:00:00+00:00")
    store.apply(prior)
    store.apply(current)
    store.apply(unrelated)
    before = path.read_bytes()
    with pytest.raises(ResearchGraphError, match="append-only; rollback is unsupported"):
        store.rollback_exact_command(current)
    assert path.read_bytes() == before

    reopened = PersistentResearchGraphStore(path)
    assert reopened.commands() == [prior, current, unrelated]
    assert reopened.qro("qro:target") == current.payload["qro"]
    assert reopened.qro("qro:unrelated") == unrelated.payload["qro"]
    assert current.command_id in path.read_text(encoding="utf-8")


def test_compiler_rollback_ir_only_reopens_without_target_and_preserves_racing_append(tmp_path):
    path = tmp_path / "compiler.jsonl"
    store = PersistentCompilerIRStore(path)
    target = _ir("ir:target")
    unrelated = _ir("ir:unrelated")
    store.record_ir(target)
    other_writer = PersistentCompilerIRStore(path)
    barrier = Barrier(2)

    def append_unrelated():
        barrier.wait()
        return other_writer.record_ir(unrelated)

    def rollback_target():
        barrier.wait()
        return store.rollback_exact_bundle(ir=target)

    with ThreadPoolExecutor(max_workers=2) as pool:
        append_future = pool.submit(append_unrelated)
        rollback_future = pool.submit(rollback_target)
        assert append_future.result() == unrelated
        assert rollback_future.result() is True

    reopened = PersistentCompilerIRStore(path)
    assert reopened.irs(owner="u1") == [unrelated]
    assert reopened.passes(owner="u1") == []
    assert target.ir_ref not in path.read_text(encoding="utf-8")
    assert reopened.rollback_exact_bundle(ir=target) is False


def test_compiler_rollback_exact_bundle_reopens_without_ir_or_pass(tmp_path):
    path = tmp_path / "compiler.jsonl"
    store = PersistentCompilerIRStore(path)
    target_ir = _ir("ir:target")
    target_pass = _compiler_pass("pass:target", target_ir)
    store.record_ir(target_ir)
    store.record_pass(target_pass)

    assert store.rollback_exact_bundle(ir=target_ir, compiler_pass=target_pass) is True

    reopened = PersistentCompilerIRStore(path)
    assert reopened.irs(owner="u1") == []
    assert reopened.passes(owner="u1") == []
    raw = path.read_text(encoding="utf-8")
    assert target_ir.ir_ref not in raw
    assert target_pass.pass_ref not in raw


def test_compiler_rollback_refuses_identity_mismatch_dependent_pass_and_artifact(tmp_path):
    mismatch_store = PersistentCompilerIRStore(tmp_path / "mismatch.jsonl")
    target_ir = _ir("ir:target")
    target_pass = _compiler_pass("pass:target", target_ir)
    mismatch_store.record_ir(target_ir)
    mismatch_store.record_pass(target_pass)
    with pytest.raises(ValueError, match="IR identity mismatch"):
        mismatch_store.rollback_exact_bundle(
            ir=replace(target_ir, permission_ref="permission:different"),
            compiler_pass=target_pass,
        )

    pass_store = PersistentCompilerIRStore(tmp_path / "dependent-pass.jsonl")
    target_ir = _ir("ir:pass-target")
    target_pass = _compiler_pass("pass:pass-target", target_ir)
    output_ir = _ir("ir:dependent-output")
    dependent_pass = _compiler_pass(
        "pass:dependent",
        output_ir,
        inputs=(target_ir.ir_ref,),
    )
    for ir in (target_ir, output_ir):
        pass_store.record_ir(ir)
    pass_store.record_pass(target_pass)
    pass_store.record_pass(dependent_pass)
    with pytest.raises(ValueError, match="dependent passes"):
        pass_store.rollback_exact_bundle(ir=target_ir, compiler_pass=target_pass)

    artifact_store = PersistentCompilerIRStore(tmp_path / "dependent-artifact.jsonl")
    target_ir = _ir("ir:artifact-target")
    target_pass = _compiler_pass("pass:artifact-target", target_ir)
    artifact_store.record_ir(target_ir)
    artifact_store.record_pass(target_pass)
    artifact_store.record_artifact(_artifact("artifact:dependent", target_ir, target_pass))
    with pytest.raises(ValueError, match="artifacts reference"):
        artifact_store.rollback_exact_bundle(ir=target_ir, compiler_pass=target_pass)


def test_coverage_rollback_reopens_exactly_and_preserves_racing_unrelated_append(tmp_path):
    path = tmp_path / "coverage.jsonl"
    store = PersistentGoalEntrypointCoverageRegistry(path)
    target = _coverage("target")
    unrelated = _coverage("unrelated")
    store.record_coverage(target)
    other_writer = PersistentGoalEntrypointCoverageRegistry(path)
    barrier = Barrier(2)

    def append_unrelated():
        barrier.wait()
        return other_writer.record_coverage(unrelated)

    def rollback_target():
        barrier.wait()
        return store.rollback_exact_coverage(target)

    with ThreadPoolExecutor(max_workers=2) as pool:
        append_future = pool.submit(append_unrelated)
        rollback_future = pool.submit(rollback_target)
        assert append_future.result() == unrelated
        assert rollback_future.result() is True

    reopened = PersistentGoalEntrypointCoverageRegistry(path)
    assert reopened.records(owner="u1") == [unrelated]
    assert target.coverage_ref not in path.read_text(encoding="utf-8")
    assert reopened.rollback_exact_coverage(target) is False

    store.record_coverage(target)
    with pytest.raises(ValueError, match="identity mismatch"):
        store.rollback_exact_coverage(
            replace(target, evidence_refs=("evidence:different",))
        )


class _NoConsentRows:
    def source_coverage(self, _ref):
        raise KeyError

    def source_coverage_for_owner(self, _ref, _owner):
        raise KeyError

    def source_coverages(self, *, owner=None):
        return []


def test_risk_consent_wrapper_delegates_non_reserved_rollback_and_refuses_reserved(tmp_path):
    delegate = PersistentGoalEntrypointCoverageRegistry(tmp_path / "coverage.jsonl")
    wrapper = RiskConsentEntrypointCoverageRegistry(
        delegate,
        _NoConsentRows(),
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
    )
    normal = _coverage("normal")
    delegate.record_coverage(normal)
    assert wrapper.rollback_exact_coverage(normal) is True

    reserved = _coverage(
        "reserved",
        entrypoint="api:copy_trade.risk_consents.confirm",
    )
    with pytest.raises(ValueError, match="SQLite transaction"):
        wrapper.rollback_exact_coverage(reserved)


def test_rollback_rewrites_leave_valid_jsonl_rows(tmp_path):
    path = tmp_path / "coverage.jsonl"
    store = PersistentGoalEntrypointCoverageRegistry(path)
    target = _coverage("target")
    retained = _coverage("retained")
    store.record_coverage(target)
    store.record_coverage(retained)
    assert store.rollback_exact_coverage(target) is True
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["entrypoint_coverage"]["coverage_ref"] == retained.coverage_ref
