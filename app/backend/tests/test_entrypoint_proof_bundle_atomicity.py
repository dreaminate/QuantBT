from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.entrypoint_evidence import (
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
)
from app.research_os.goal_proof_ledger import (
    GoalProofConflictError,
    GoalProofLedger,
    InvalidationTarget,
)
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    RuntimeStatus,
)


OWNER = "owner:entrypoint-proof-bundle-atomicity"
ENTRYPOINT_REF = "api:test.entrypoint-proof-bundle-atomicity"


@dataclass(frozen=True)
class _Stores:
    root: Path
    ledger: GoalProofLedger
    graph: PersistentResearchGraphStore
    compiler: PersistentCompilerIRStore
    validations: PersistentGoalValidationReceiptRegistry
    evidence: PersistentEntrypointEvidenceRegistry
    coverage: PersistentGoalEntrypointCoverageRegistry


def _open_stores(
    root: Path,
    *,
    fault_injector=None,
) -> _Stores:
    ledger = GoalProofLedger(root / "goal_proof_ledger", fault_injector=fault_injector)
    graph = PersistentResearchGraphStore(root / "research_graph.jsonl")
    compiler = PersistentCompilerIRStore(
        root / "compiler.jsonl",
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        root / "validation_receipts.jsonl",
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        root / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        root / "entrypoint_coverage.jsonl",
        proof_ledger=ledger,
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
    return _Stores(
        root=root,
        ledger=ledger,
        graph=graph,
        compiler=compiler,
        validations=validations,
        evidence=evidence,
        coverage=coverage,
    )


def _install(monkeypatch: pytest.MonkeyPatch, stores: _Stores) -> None:
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", stores.graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", stores.compiler)
    monkeypatch.setattr(
        main,
        "GOAL_VALIDATION_RECEIPT_REGISTRY",
        stores.validations,
    )
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", stores.evidence)
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        stores.coverage,
    )


def _record_qro(stores: _Stores) -> tuple[QRORecord, ResearchGraphCommand]:
    qro = QRORecord(
        qro_type=QROType.QUANT_INTENT,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={"request_ref": "request:atomic-entrypoint:v1"},
        output_contract={"result_ref": "result:atomic-entrypoint:v1"},
        market="crypto",
        universe="BTCUSDT",
        horizon="1d",
        frequency="1m",
        lineage=("request:atomic-entrypoint:v1",),
        implementation_hash="implementation:atomic-entrypoint:v1",
        assumptions=("The fixture is offline and deterministic.",),
        known_limits=("The fixture does not execute a trade.",),
        failure_modes=("The atomic SQLite transaction can fail.",),
        validation_plan=("Reopen the exact five proof heads.",),
        evidence_refs=("evidence:atomic-entrypoint:v1",),
        permission="research.atomic_entrypoint:user_manual",
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=(ENTRYPOINT_REF,),
        timestamp="2026-07-14T00:00:00+00:00",
    )
    assert stores.graph.apply(command) == command.command_id
    return qro, command


def _compile(qro: QRORecord, command: ResearchGraphCommand) -> dict[str, str]:
    return main._compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command.command_id,
        actor=OWNER,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref=ENTRYPOINT_REF,
        pass_name="atomic_entrypoint_qro_to_ir",
        validation_refs=("validation:atomic-entrypoint:v1",),
        evidence_refs=qro.evidence_refs,
        environment_lock_ref="env:atomic-entrypoint:offline:v1",
        permission_ref=qro.permission,
        deterministic_run_plan_ref="runplan:atomic-entrypoint:v1",
        rollback_ref="rollback:atomic-entrypoint:v1",
        tool_record_refs=(ENTRYPOINT_REF,),
        goal_sections=("§0", "§1", "§8"),
    )


def _legacy_bytes(stores: _Stores) -> dict[Path, bytes]:
    paths = (
        stores.compiler.path,
        stores.validations.path,
        stores.evidence.path,
        stores.coverage.path,
    )
    return {path: path.read_bytes() if path.exists() else b"" for path in paths}


def _assert_complete_current_bundle(stores: _Stores, refs: dict[str, str]) -> None:
    [receipt] = stores.validations.receipts(owner_user_id=OWNER)
    [evidence] = stores.evidence.evidences(owner_user_id=OWNER)
    [ir] = stores.compiler.irs(owner=OWNER)
    [compiler_pass] = stores.compiler.passes(owner=OWNER)
    [coverage] = stores.coverage.records(owner=OWNER)
    assert refs == {
        "compiler_ir_ref": ir.ir_ref,
        "compiler_pass_ref": compiler_pass.pass_ref,
        "entrypoint_coverage_ref": coverage.coverage_ref,
    }
    assert evidence.validation_ref == receipt.validation_ref
    assert evidence.compiler_ir_ref == ir.ir_ref
    assert evidence.compiler_pass_ref == compiler_pass.pass_ref
    assert evidence.coverage_ref == coverage.coverage_ref
    assert stores.evidence.validate_current(
        evidence,
        owner_user_id=OWNER,
    ).accepted
    assert stores.coverage.validate_real_backing(coverage).accepted
    heads = stores.ledger.current(owner=OWNER).heads
    assert len(heads) == 5
    assert len({head.bundle_id for head in heads}) == 1
    assert {head.logical_ref for head in heads} == {
        receipt.validation_ref,
        evidence.evidence_ref,
        ir.ir_ref,
        compiler_pass.pass_ref,
        coverage.coverage_ref,
    }


def test_entrypoint_bundle_commits_five_heads_and_never_writes_legacy_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = _open_stores(tmp_path / "success")
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    before = _legacy_bytes(stores)

    refs = _compile(qro, command)

    _assert_complete_current_bundle(stores, refs)
    assert _legacy_bytes(stores) == before
    assert stores.ledger.verify().ok


def test_identical_qro_new_command_stales_old_evidence_and_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = _open_stores(tmp_path / "graph-head-freshness")
    _install(monkeypatch, stores)
    qro, command_a = _record_qro(stores)
    _compile(qro, command_a)
    [evidence_a] = stores.evidence.evidences(owner_user_id=OWNER)
    [coverage_a] = stores.coverage.records(owner=OWNER)
    assert stores.evidence.validate_current(
        evidence_a,
        owner_user_id=OWNER,
    ).accepted
    assert stores.coverage.validate_real_backing(coverage_a).accepted

    command_b = replace(
        command_a,
        timestamp="2026-07-14T00:00:01+00:00",
        command_id="",
    )
    assert command_b.command_id != command_a.command_id
    assert stores.graph.apply(command_b) == command_b.command_id
    owner_resolver = stores.coverage._resolver.for_owner(OWNER)
    assert owner_resolver.has_research_graph_command(command_a.command_id) is False
    assert owner_resolver.has_research_graph_command(command_b.command_id) is True

    stale_evidence = stores.evidence.validate_current(
        evidence_a,
        owner_user_id=OWNER,
    )
    assert not stale_evidence.accepted
    assert "entrypoint_evidence_source_resolution_failed" in {
        item.code for item in stale_evidence.violations
    }
    stale_coverage = stores.coverage.validate_real_backing(coverage_a)
    assert not stale_coverage.accepted
    assert any(
        item.code == "goal_entrypoint_linkage_invalid"
        and "current QRO projection head" in item.message
        for item in stale_coverage.violations
    )

    refs_b = _compile(qro, command_b)
    evidence_b = next(
        record
        for record in stores.evidence.evidences(owner_user_id=OWNER)
        if record.research_graph_ref == command_b.command_id
    )
    coverage_b = next(
        record
        for record in stores.coverage.records(owner=OWNER)
        if record.research_graph_command_refs == (command_b.command_id,)
    )
    assert refs_b["entrypoint_coverage_ref"] == coverage_b.coverage_ref
    assert stores.evidence.validate_current(
        evidence_b,
        owner_user_id=OWNER,
    ).accepted
    assert stores.coverage.validate_real_backing(coverage_b).accepted


def test_entrypoint_bundle_sqlite_failure_leaves_no_partial_head_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed = {"value": True}

    def fail(cutpoint: str) -> None:
        if armed["value"] and cutpoint == "before_sqlite_commit":
            armed["value"] = False
            raise RuntimeError("injected entrypoint SQLite failure")

    stores = _open_stores(tmp_path / "fault", fault_injector=fail)
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    before = _legacy_bytes(stores)

    with pytest.raises(RuntimeError, match="injected entrypoint SQLite failure"):
        _compile(qro, command)

    assert stores.ledger.current(owner=OWNER).heads == ()
    assert stores.compiler.irs(owner=OWNER) == []
    assert stores.validations.receipts(owner_user_id=OWNER) == []
    assert stores.evidence.evidences(owner_user_id=OWNER) == ()
    assert stores.coverage.records(owner=OWNER) == []
    assert _legacy_bytes(stores) == before

    refs = _compile(qro, command)
    _assert_complete_current_bundle(stores, refs)


def test_entrypoint_bundle_repairs_mirror_pending_and_proves_exact_heads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed = {"value": True}

    def fail(cutpoint: str) -> None:
        if armed["value"] and cutpoint == "after_sqlite_commit":
            armed["value"] = False
            raise RuntimeError("injected entrypoint mirror failure")

    stores = _open_stores(tmp_path / "mirror-pending", fault_injector=fail)
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    before = _legacy_bytes(stores)

    refs = _compile(qro, command)

    _assert_complete_current_bundle(stores, refs)
    assert stores.ledger.verify().ok
    assert _legacy_bytes(stores) == before


def test_entrypoint_bundle_postcommit_validation_failure_is_typed_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = _open_stores(tmp_path / "postcommit-validation")
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    validate_real_backing = stores.coverage.validate_real_backing

    def reject_after_commit(record):
        if stores.ledger.current(owner=OWNER).heads:
            return SimpleNamespace(
                accepted=False,
                violations=(
                    SimpleNamespace(
                        code="injected_postcommit_rejection",
                        field="coverage_ref",
                        ref=record.coverage_ref,
                    ),
                ),
            )
        return validate_real_backing(record)

    monkeypatch.setattr(
        stores.coverage,
        "validate_real_backing",
        reject_after_commit,
    )

    with pytest.raises(main._CanonicalGoalProofCommitUncertainError) as caught:
        _compile(qro, command)

    assert caught.value.result.owner == OWNER
    assert caught.value.result.subject.startswith("entrypoint_proof:")
    assert "injected_postcommit_rejection" in str(caught.value.cause)
    assert len(stores.ledger.current(owner=OWNER).heads) == 5

    monkeypatch.setattr(
        stores.coverage,
        "validate_real_backing",
        validate_real_backing,
    )
    [ir] = stores.compiler.irs(owner=OWNER)
    [compiler_pass] = stores.compiler.passes(owner=OWNER)
    [coverage] = stores.coverage.records(owner=OWNER)
    _assert_complete_current_bundle(
        stores,
        {
            "compiler_ir_ref": ir.ir_ref,
            "compiler_pass_ref": compiler_pass.pass_ref,
            "entrypoint_coverage_ref": coverage.coverage_ref,
        },
    )


def test_compile_qro_http_boundary_reports_postcommit_uncertainty_as_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = _open_stores(tmp_path / "postcommit-http")
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    validate_real_backing = stores.coverage.validate_real_backing

    def reject_after_commit(record):
        if stores.ledger.current(owner=OWNER).heads:
            return SimpleNamespace(
                accepted=False,
                violations=(
                    SimpleNamespace(
                        code="injected_postcommit_rejection",
                        field="coverage_ref",
                        ref=record.coverage_ref,
                    ),
                ),
            )
        return validate_real_backing(record)

    monkeypatch.setattr(
        stores.coverage,
        "validate_real_backing",
        reject_after_commit,
    )

    with pytest.raises(main.HTTPException) as caught:
        main.research_os_compiler_compile_qro(
            payload={
                "qro_id": qro.qro_id,
                "graph_command_refs": [command.command_id],
            },
            user=SimpleNamespace(user_id=OWNER, username="entrypoint-owner"),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["canonical_write_committed"] is True
    assert caught.value.detail["retry_required"] is True
    assert len(stores.ledger.current(owner=OWNER).heads) == 5


def test_canonical_bundle_rejects_record_owner_and_unknown_dependency_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = _open_stores(tmp_path / "owner-envelope")
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    refs = _compile(qro, command)
    [ir] = stores.compiler.irs(owner=OWNER)
    before = stores.ledger.current(owner=OWNER)

    with pytest.raises(ValueError, match="every typed record owner"):
        main._commit_canonical_goal_proof_bundle(
            owner=OWNER,
            subject="test:owner-envelope",
            records=((replace(ir, owner="owner:other"), main.COMPILER_IR_PROOF_CODEC),),
            registries=(stores.compiler,),
            metadata={"schema_version": "test.owner-envelope.v1"},
        )
    with pytest.raises(ValueError, match="dependency keys are not members"):
        main._commit_canonical_goal_proof_bundle(
            owner=OWNER,
            subject="test:unknown-dependency-key",
            records=((ir, main.COMPILER_IR_PROOF_CODEC),),
            registries=(stores.compiler,),
            metadata={"schema_version": "test.unknown-dependency-key.v1"},
            external_dependencies={"compiler_ir:not-a-member": (ir.ir_ref,)},
        )

    after = stores.ledger.current(owner=OWNER)
    assert after.head_digest == before.head_digest
    _assert_complete_current_bundle(stores, refs)


def test_entrypoint_bundle_replay_and_invalidation_are_all_or_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "replay"
    stores = _open_stores(root)
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    refs = _compile(qro, command)
    _assert_complete_current_bundle(stores, refs)

    reopened = _open_stores(root)
    _install(monkeypatch, reopened)
    _assert_complete_current_bundle(reopened, refs)
    heads = reopened.ledger.current(owner=OWNER).heads
    target = next(
        head for head in heads if head.logical_ref == refs["compiler_pass_ref"]
    )
    invalidated = reopened.ledger.invalidate(
        owner=OWNER,
        subject=target.subject,
        operation_id="invalidate:atomic-entrypoint:v1",
        targets=(InvalidationTarget.from_head(target),),
        reason="test exact dependency cascade",
    )
    assert set(invalidated.affected_refs) == {
        head.logical_ref for head in heads
    }
    assert reopened.ledger.current(owner=OWNER).heads == ()
    assert reopened.compiler.irs(owner=OWNER) == []
    assert reopened.validations.receipts(owner_user_id=OWNER) == []
    assert reopened.evidence.evidences(owner_user_id=OWNER) == ()
    assert reopened.coverage.records(owner=OWNER) == []


def test_entrypoint_bundle_rejects_same_ref_payload_recombination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = _open_stores(tmp_path / "collision")
    _install(monkeypatch, stores)
    qro, command = _record_qro(stores)
    refs = _compile(qro, command)
    [ir] = stores.compiler.irs(owner=OWNER)
    before = stores.ledger.current(owner=OWNER)
    changed = replace(ir, rollback_ref="rollback:recombined")

    with pytest.raises(GoalProofConflictError, match="different payload"):
        main._commit_canonical_goal_proof_bundle(
            owner=OWNER,
            subject=before.heads[0].subject,
            records=((changed, main.COMPILER_IR_PROOF_CODEC),),
            registries=(stores.compiler,),
            metadata={"schema_version": "test.recombined.v1"},
        )

    after = stores.ledger.current(owner=OWNER)
    assert after.head_digest == before.head_digest
    _assert_complete_current_bundle(stores, refs)
