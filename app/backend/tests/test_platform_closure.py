from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import stat
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cross_process_lock import CrossProcessLockTimeout, acquire_exclusive_fd
from app.lineage.ids import content_hash
from app.research_os import platform_closure as platform_closure_module
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    PersistentGoalSectionSemanticProofRegistry,
    goal_section_semantic_proof_identity,
)
from app.research_os.platform_closure import (
    PLATFORM_CLOSURE_ENTRYPOINT_REF,
    PLATFORM_CLOSURE_GOAL_SECTIONS,
    PersistentPlatformClosureRegistry,
    PlatformClosureCommitUncertain,
    PlatformClosureError,
    PlatformClosureRDPState,
    PlatformClosureSectionAdapter,
    platform_closure_rdp_state,
    platform_closure_semantic_material,
)
from app.research_os.platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REF_PREFIXES,
    SPECIFIC_REQUIRED_REFS,
    PersistentPlatformCoverageRegistry,
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_row_producers import (
    ResolvedPlatformRow,
    platform_row_source_state,
    resolved_platform_row,
)
from app.research_os.platform_row_sources import PersistentPlatformRowSourceRegistry
from app.research_os.rdp import PersistentRDPStore, RDPManifest


def _slug(row: str) -> str:
    return row.replace("-", "_")


def _record_rdp_manifest_after_lock_probe(
    rdp_path_text: str,
    raw_manifest: dict,
    owner_user_id: str,
    start_gate,
    probe_done,
    initially_blocked,
    initially_acquired,
    finished,
) -> None:
    """Child-process probe used to prove the closure keeps the RDP lock."""

    if not start_gate.wait(5.0):
        raise RuntimeError("RDP lock probe was never released")
    rdp_path = Path(rdp_path_text)
    lock_path = rdp_path.with_name(f".{rdp_path.name}.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    held = None
    try:
        try:
            held = acquire_exclusive_fd(fd, timeout_seconds=0.0)
        except CrossProcessLockTimeout:
            initially_blocked.set()
            probe_done.set()
            held = acquire_exclusive_fd(fd, timeout_seconds=5.0)
        else:
            initially_acquired.set()
            probe_done.set()
    finally:
        probe_done.set()
        if held is not None:
            held.release()
        os.close(fd)
    store = PersistentRDPStore(rdp_path)
    store.record_manifest(
        RDPManifest(**raw_manifest),
        owner_user_id=owner_user_id,
        recorded_by=owner_user_id,
    )
    finished.set()


class _OwnerResolver:
    def __init__(self, owner: str | None = None) -> None:
        self.owner = owner

    def for_owner(self, owner: str):
        return _OwnerResolver(owner)

    def _owned(self, ref: str) -> bool:
        return bool(self.owner and self.owner in str(ref or ""))

    def has_qro(self, ref):
        return self._owned(ref)

    def has_research_graph_command(self, ref):
        return self._owned(ref)

    def has_lifecycle_record(self, ref):
        return self._owned(ref) or str(ref or "").startswith("rdp_")

    def has_governance_record(self, ref):
        return self._owned(ref)

    def has_rag_asset(self, ref):
        return self._owned(ref)

    def has_math_spine_chain(self, ref):
        return self._owned(ref)

    def has_math_spine_member(self, chain_ref, member_type, ref):
        del member_type
        return self._owned(chain_ref) and self._owned(ref)

    def has_platform_evidence(self, record, ref):
        return self._owned(ref) and _slug(str(record.m_row)) in str(ref)

    def has_platform_specific_ref(self, key, ref, record):
        del key
        return self._owned(ref) and _slug(str(record.m_row)) in str(ref)

    def platform_linkage_violations(self, record):
        row = _slug(str(record.m_row))
        if row not in str(record.qro_ref) or row not in str(record.research_graph_ref):
            return (("qro_ref", str(record.qro_ref), "row lineage mismatch"),)
        return ()


def _manifest(
    owner: str,
    *,
    suffix: str = "v1",
    rdp_package_id: str | None = None,
) -> tuple[PlatformCapabilityRecord, ...]:
    selected_rdp = rdp_package_id or _rdp_manifest(f"fixture-{owner}").package_id
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        slug = _slug(row)
        specifics = tuple(
            PlatformSpecificRef(
                key=key,
                ref=f"{SPECIFIC_REF_PREFIXES[key][0]}{owner}:{slug}:{suffix}",
            )
            for key in SPECIFIC_REQUIRED_REFS[row]
        )
        records.append(
            PlatformCapabilityRecord(
                m_row=row,
                qro_ref=f"qro:{owner}:{slug}:{suffix}",
                research_graph_ref=f"rgcmd:{owner}:{slug}:{suffix}",
                lifecycle_ref=(
                    selected_rdp
                    if row == "M18"
                    else f"lifecycle:{owner}:{slug}:{suffix}"
                ),
                governance_ref=f"governance:{owner}:{slug}:{suffix}",
                rag_ref=f"rag:{owner}:{slug}:{suffix}",
                math_spine_ref=f"math:{owner}:{slug}:{suffix}",
                evidence_refs=(f"audit:{owner}:{slug}:{suffix}",),
                specific_refs=specifics,
            )
        )
    return tuple(records)


def _coverage_for_record(
    owner: str,
    record: PlatformCapabilityRecord,
    *,
    rdp_refs: tuple[str, ...] | None = None,
) -> GoalEntrypointCoverageRecord:
    row = str(getattr(record.m_row, "value", record.m_row))
    slug = _slug(row)
    ir_ref = f"compiler_ir:{owner}:{slug}:source"
    pass_ref = f"compiler_pass:{owner}:{slug}:source"
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source="api",
        entrypoint_ref=f"api:platform.row.{slug}",
        goal_sections=PLATFORM_CLOSURE_GOAL_SECTIONS,
        qro_refs=(str(record.qro_ref),),
        research_graph_command_refs=(str(record.research_graph_ref),),
        compiler_ir_refs=(ir_ref,),
        compiler_pass_refs=(pass_ref,),
    )
    selected_rdps = (
        ((str(record.lifecycle_ref),) if row == "M18" else ())
        if rdp_refs is None
        else rdp_refs
    )
    return GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source="api",
        entrypoint_ref=f"api:platform.row.{slug}",
        goal_sections=PLATFORM_CLOSURE_GOAL_SECTIONS,
        qro_refs=(str(record.qro_ref),),
        research_graph_command_refs=(str(record.research_graph_ref),),
        compiler_ir_refs=(ir_ref,),
        compiler_pass_refs=(pass_ref,),
        evidence_refs=tuple(record.evidence_refs),
        validation_refs=(f"goal_validation_receipt:{owner}:{slug}:source",),
        permission_refs=(f"permission:{owner}:{slug}:source",),
        replay_refs=(
            f"replay:research_graph:{record.research_graph_ref}",
            f"replay:compiler_ir:{ir_ref}",
            f"replay:compiler_pass:{pass_ref}",
        ),
        canonical_command_refs=(str(record.research_graph_ref),),
        lifecycle_refs=(str(record.lifecycle_ref),),
        rdp_refs=selected_rdps,
        recorded_by=owner,
        silent_mock_fallback_used=False,
        raw_payload_persisted=False,
    )


def _resolved_manifest(
    owner: str,
    records: tuple[PlatformCapabilityRecord, ...],
    *,
    source_revision: str = "v1",
) -> tuple[ResolvedPlatformRow, ...]:
    resolved = []
    for record in records:
        row = str(getattr(record.m_row, "value", record.m_row))
        refs = (
            str(record.qro_ref),
            str(record.research_graph_ref),
            str(record.lifecycle_ref),
            str(record.governance_ref),
            str(record.rag_ref),
            str(record.math_spine_ref),
            *record.evidence_refs,
            *(item.ref for item in record.specific_refs),
        )
        coverage = _coverage_for_record(owner, record)
        resolved.append(
            resolved_platform_row(
                owner_user_id=owner,
                m_row=row,
                producer_ref=f"platform_row_producer:{row}:test",
                record=record,
                source_states=(
                    *tuple(
                        platform_row_source_state(
                        source_kind=f"test_source:{index}",
                        source_ref=ref,
                        state_payload={
                            "owner": owner,
                            "row": row,
                            "ref": ref,
                            "source_revision": source_revision,
                        },
                    )
                    for index, ref in enumerate(refs)
                    ),
                    platform_row_source_state(
                        source_kind="goal_entrypoint_coverage",
                        source_ref=coverage.coverage_ref,
                        state_payload=asdict(coverage),
                    ),
                ),
            )
        )
    return tuple(resolved)


def _closure_registry(
    path,
    platform,
    *,
    resolve_current_manifest,
    resolve_current_manifest_unlocked=None,
    resolve_current_coverage=None,
    resolve_linked_rdp=None,
):
    rdp_path = path.parent / "rdp_manifests.jsonl"
    rdp_store = PersistentRDPStore(rdp_path)
    for owner in ("owner-a", "owner-b"):
        rdp_store.record_manifest(
            _rdp_manifest(f"fixture-{owner}"),
            owner_user_id=owner,
            recorded_by=owner,
        )

    record_projection_by_owner: dict[str, bool] = {}

    def resolve_rows(owner: str) -> tuple[ResolvedPlatformRow, ...]:
        value = resolve_current_manifest(owner)
        if all(isinstance(item, ResolvedPlatformRow) for item in value):
            record_projection_by_owner[owner] = False
            return value
        record_projection_by_owner[owner] = True
        return _resolved_manifest(owner, value)

    def resolve_rows_unlocked(
        owner: str,
        journal_records: tuple[PlatformCapabilityRecord, ...],
    ) -> tuple[ResolvedPlatformRow, ...]:
        if record_projection_by_owner.get(owner):
            return _resolved_manifest(owner, journal_records)
        return resolve_rows(owner)

    def resolve_coverage(owner: str, coverage_ref: str) -> GoalEntrypointCoverageRecord:
        if resolve_current_coverage is not None:
            return resolve_current_coverage(owner, coverage_ref)
        matches = tuple(
            coverage
            for coverage in (
                _coverage_for_record(owner, record)
                for record in platform.records(owner_user_id=owner)
            )
            if coverage.coverage_ref == coverage_ref
        )
        if len(matches) != 1:
            raise KeyError(coverage_ref)
        return matches[0]

    def resolve_rdp(owner: str, package_id: str) -> PlatformClosureRDPState:
        if resolve_linked_rdp is not None:
            return resolve_linked_rdp(owner, package_id)
        manifest = rdp_store.manifest(package_id, owner_user_id=owner)
        return platform_closure_rdp_state(
            package_id=manifest.package_id,
            manifest_payload=manifest.to_open_dict(),
        )

    return PersistentPlatformClosureRegistry(
        path,
        platform,
        resolve_current_manifest=resolve_rows,
        resolve_current_manifest_unlocked=(
            resolve_current_manifest_unlocked or resolve_rows_unlocked
        ),
        resolve_current_coverage=resolve_coverage,
        entrypoint_ledger_path=path.parent / "goal_entrypoint_coverage.jsonl",
        rdp_path=rdp_path,
        resolve_linked_rdp=resolve_rdp,
    )


def _registries(tmp_path, *, owner: str = "owner-a"):
    proof_head_path = tmp_path / "goal_entrypoint_coverage.jsonl"
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
        proof_head_ledger_path=proof_head_path,
    )
    platform.record_manifest(_manifest(owner), owner_user_id=owner)
    closure = _closure_registry(
        tmp_path / "closures.jsonl",
        platform,
        resolve_current_manifest=lambda selected_owner: tuple(
            platform.records(owner_user_id=selected_owner)
        ),
    )
    return platform, closure


class _AtomicEntrypoints:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.coverages: dict[tuple[str, str], GoalEntrypointCoverageRecord] = {}

    def add(self, coverage: GoalEntrypointCoverageRecord) -> None:
        self.coverages[(coverage.recorded_by, coverage.coverage_ref)] = coverage

    def coverage(self, coverage_ref: str, *, owner: str):
        return self.coverages[(owner, coverage_ref)]

    def validate_real_backing(self, coverage):
        return SimpleNamespace(
            accepted=self.coverages.get(
                (coverage.recorded_by, coverage.coverage_ref)
            )
            == coverage
        )


class _AtomicRAG:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], SimpleNamespace] = {}

    def add(self, owner: str, document: SimpleNamespace) -> None:
        self.documents[(owner, document.document_id)] = document

    def document_for_owner(
        self,
        document_id: str,
        *,
        owner_user_id: str,
        require_current: bool,
    ):
        assert require_current is True
        return self.documents[(owner_user_id, document_id)]


class _AtomicTypedSources:
    def resolve_state(self, field, ref, *, owner_user_id, record):
        del record
        return platform_row_source_state(
            source_kind=f"typed:{field}",
            source_ref=ref,
            state_payload={
                "owner_user_id": owner_user_id,
                "field": field,
                "ref": ref,
            },
        )

    def linkage_violations(
        self,
        record,
        *,
        owner_user_id,
        source_coverage,
        rag_document,
    ):
        del record, owner_user_id, source_coverage, rag_document
        return ()


def _atomic_row_inputs(
    owner: str,
    base: PlatformCapabilityRecord,
    *,
    suffix: str,
) -> tuple[GoalEntrypointCoverageRecord, SimpleNamespace]:
    row = str(getattr(base.m_row, "value", base.m_row))
    slug = _slug(row)
    coverage = _coverage_for_record(owner, base)
    rag_ref = f"ragdoc:{owner}:{slug}:{suffix}"
    document = SimpleNamespace(
        document_id=rag_ref,
        source_id=f"platform_source_lineage:{row}",
        source_kind="server_derived_platform_source_lineage",
        version="platform_source_lineage.v1." + hashlib.sha256(
            f"{owner}:{row}:{suffix}".encode("utf-8")
        ).hexdigest(),
        projection="research",
        evidence_label="candidate_context",
        permission=SimpleNamespace(
            allowed_users=(owner,),
            permission_tags=("platform_source_lineage",),
        ),
        metadata={
            "platform_capability": {
                "schema_version": 1,
                "m_row": row,
                "source_coverage_ref": coverage.coverage_ref,
                "qro_ref": coverage.qro_refs[0],
                "research_graph_ref": coverage.research_graph_command_refs[0],
                "lifecycle_ref": coverage.lifecycle_refs[0],
                "governance_ref": coverage.validation_refs[0],
                "math_spine_ref": base.math_spine_ref,
                "evidence_refs": list(coverage.evidence_refs),
                "specific_refs": {
                    item.key: item.ref for item in base.specific_refs
                },
            }
        },
    )
    return coverage, document


def _atomic_section14_system(tmp_path) -> SimpleNamespace:
    owner = "owner-a"
    proof_head_path = tmp_path / "goal_entrypoint_coverage.jsonl"
    entrypoints = _AtomicEntrypoints(proof_head_path)
    rag = _AtomicRAG()
    typed = _AtomicTypedSources()
    rows = PersistentPlatformRowSourceRegistry(
        tmp_path / "platform_row_sources.jsonl",
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=typed,
    )
    initial_records: dict[str, PlatformCapabilityRecord] = {}
    for base in _manifest(owner):
        row = str(getattr(base.m_row, "value", base.m_row))
        coverage, document = _atomic_row_inputs(owner, base, suffix="v1")
        entrypoints.add(coverage)
        rag.add(owner, document)
        certification = rows.record_current(
            owner_user_id=owner,
            m_row=row,
            source_coverage_ref=coverage.coverage_ref,
            rag_ref=document.document_id,
        )
        initial_records[row] = certification.resolved_row.record

    def current_rows(selected_owner: str) -> tuple[ResolvedPlatformRow, ...]:
        return tuple(
            rows.resolve_current_row(row, owner_user_id=selected_owner)
            for row in REQUIRED_PLATFORM_ROWS
        )

    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
        proof_head_ledger_path=proof_head_path,
    )
    platform.record_manifest(
        tuple(resolved.record for resolved in current_rows(owner)),
        owner_user_id=owner,
    )
    closure = _closure_registry(
        tmp_path / "closures.jsonl",
        platform,
        resolve_current_manifest=current_rows,
        resolve_current_manifest_unlocked=(
            rows.resolve_current_rows_from_journal_unlocked
        ),
        resolve_current_coverage=lambda selected_owner, coverage_ref: (
            entrypoints.coverage(coverage_ref, owner=selected_owner)
        ),
    )
    return SimpleNamespace(
        owner=owner,
        proof_head_path=proof_head_path,
        entrypoints=entrypoints,
        rag=rag,
        typed=typed,
        rows=rows,
        platform=platform,
        closure=closure,
        initial_records=initial_records,
    )


def test_platform_closure_requires_explicit_lock_safe_manifest_resolver(tmp_path):
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    with pytest.raises(
        TypeError,
        match="resolve_current_manifest_unlocked must be callable",
    ):
        PersistentPlatformClosureRegistry(
            tmp_path / "closures.jsonl",
            platform,
            resolve_current_manifest=lambda owner: _resolved_manifest(
                owner,
                _manifest(owner),
            ),
            resolve_current_manifest_unlocked=None,
            resolve_current_coverage=lambda _owner, _ref: None,
            entrypoint_ledger_path=tmp_path / "goal_entrypoint_coverage.jsonl",
            rdp_path=tmp_path / "rdp_manifests.jsonl",
            resolve_linked_rdp=lambda _owner, _package: None,
        )


def test_platform_closure_durable_boundaries_use_lock_safe_row_journal_projection(
    tmp_path,
    monkeypatch,
):
    system = _atomic_section14_system(tmp_path)
    original_append = system.closure._atomic_append

    class PoisonTypedResolver:
        def resolve_state(self, *args, **kwargs):
            raise AssertionError("durable boundary re-entered typed source resolution")

        def linkage_violations(self, *args, **kwargs):
            raise AssertionError("durable boundary re-entered typed source resolution")

    def poison_after_public_preflight(row, *, precommit_assertion):
        original_resolver = system.rows._resolver
        system.rows._resolver = PoisonTypedResolver()
        try:
            return original_append(row, precommit_assertion=precommit_assertion)
        finally:
            system.rows._resolver = original_resolver

    monkeypatch.setattr(system.closure, "_atomic_append", poison_after_public_preflight)
    receipt = system.closure.record_current(system.owner)

    assert receipt.owner_user_id == system.owner
    assert tuple(item.m_row for item in receipt.snapshot.rows) == REQUIRED_PLATFORM_ROWS
    assert system.closure.validate_current(
        receipt.receipt_ref,
        owner_user_id=system.owner,
    ).accepted


def test_platform_closure_never_returns_success_after_typed_source_return_drift(
    tmp_path,
    monkeypatch,
):
    system = _atomic_section14_system(tmp_path)
    original_append = system.closure._atomic_append

    class DriftedTypedResolver:
        def resolve_state(self, field, ref, *, owner_user_id, record):
            del record
            return platform_row_source_state(
                source_kind=f"typed:{field}",
                source_ref=ref,
                state_payload={
                    "owner_user_id": owner_user_id,
                    "field": field,
                    "ref": ref,
                    "revision": "drifted-after-public-preflight",
                },
            )

        def linkage_violations(self, *args, **kwargs):
            del args, kwargs
            return ()

    def drift_after_public_preflight(row, *, precommit_assertion):
        system.rows._resolver = DriftedTypedResolver()
        return original_append(row, precommit_assertion=precommit_assertion)

    monkeypatch.setattr(system.closure, "_atomic_append", drift_after_public_preflight)
    with pytest.raises(
        PlatformClosureCommitUncertain,
        match="typed source state changed before return",
    ):
        system.closure.record_current(system.owner)

    assert system.closure.path.exists()
    persisted_row = json.loads(
        system.closure.path.read_text(encoding="utf-8").splitlines()[-1]
    )
    persisted_ref = persisted_row["receipt"]["receipt_ref"]
    assert not system.closure.validate_current(
        persisted_ref,
        owner_user_id=system.owner,
    ).accepted


def _rdp_manifest(suffix: str, *, question: str | None = None) -> RDPManifest:
    return RDPManifest(
        research_question=question or f"platform closure RDP {suffix}",
        graph_refs=(f"rg:platform:{suffix}",),
        data_refs=(f"dataset:platform:{suffix}",),
        dataset_version_refs=(f"dataset_version:platform:{suffix}",),
        market_data_use_validation_refs=(f"market_data_use:platform:{suffix}",),
        ingestion_skill_refs=(f"ingestion_skill:platform:{suffix}",),
        mathematical_refs=(f"math:platform:{suffix}",),
        theory_binding_refs=(f"theory_binding:platform:{suffix}",),
        consistency_check_refs=(f"consistency_check:platform:{suffix}",),
        asset_refs=(f"asset:platform:{suffix}",),
        code_refs=(f"code:platform:{suffix}",),
        environment_lock_ref=f"environment_lock:platform:{suffix}",
        reproducibility_command=f"quantbt reproduce platform-{suffix}",
        artifact_hash=f"sha256:platform:{suffix}",
        test_refs=(f"test:platform:{suffix}",),
        run_refs=(f"run:platform:{suffix}",),
        honest_n_refs=(f"honest_n:platform:{suffix}",),
        cost_and_execution_assumptions=(f"costs:platform:{suffix}",),
        known_limits=(f"known_limit:platform:{suffix}",),
        unverified_residuals=(f"residual:platform:{suffix}",),
        verifier_verdict_ref=f"verdict:platform:{suffix}",
        compiler_artifact_refs=(f"compiler_artifact:platform:{suffix}",),
        mathematical_spine_chain_refs=(f"math_spine_chain:platform:{suffix}",),
        goal_entrypoint_coverage_refs=(f"goal_entrypoint_coverage:platform:{suffix}",),
    )


def _legacy_v1_rdp_manifest_payload(manifest: RDPManifest) -> dict:
    legacy_fields = {
        "research_question",
        "graph_refs",
        "data_refs",
        "dataset_version_refs",
        "market_data_use_validation_refs",
        "ingestion_skill_refs",
        "mathematical_refs",
        "theory_binding_refs",
        "consistency_check_refs",
        "methodology_choice_refs",
        "responsibility_refs",
        "asset_refs",
        "code_refs",
        "environment_lock_ref",
        "reproducibility_command",
        "artifact_hash",
        "test_refs",
        "run_refs",
        "honest_n_refs",
        "cost_and_execution_assumptions",
        "attribution_refs",
        "known_limits",
        "unverified_residuals",
        "verifier_verdict_ref",
        "compiler_artifact_refs",
        "mathematical_spine_chain_refs",
        "goal_entrypoint_coverage_refs",
        "approval_ref",
        "deployment_refs",
        "monitor_refs",
        "rollback_plan_ref",
        "retire_plan_ref",
        "target_runtime",
        "llm_call_refs",
        "source_file_refs",
        "package_id",
        "manifest_version",
    }
    payload = {
        key: value
        for key, value in manifest.to_open_dict().items()
        if key in legacy_fields
    }
    payload["manifest_version"] = "rdp.v2"
    payload["package_id"] = "rdp_" + content_hash(
        {
            "manifest_version": payload["manifest_version"],
            "research_question": payload["research_question"],
            "graph_refs": payload["graph_refs"],
            "asset_refs": payload["asset_refs"],
            "artifact_hash": payload["artifact_hash"],
            "market_data_use_validation_refs": payload[
                "market_data_use_validation_refs"
            ],
            "compiler_artifact_refs": payload["compiler_artifact_refs"],
            "mathematical_spine_chain_refs": payload[
                "mathematical_spine_chain_refs"
            ],
            "goal_entrypoint_coverage_refs": payload[
                "goal_entrypoint_coverage_refs"
            ],
            "run_refs": payload["run_refs"],
        }
    )
    return payload


def _rdp_states(
    store: PersistentRDPStore,
    owner_user_id: str,
) -> tuple[PlatformClosureRDPState, ...]:
    return tuple(
        sorted(
            (
                platform_closure_rdp_state(
                    package_id=manifest.package_id,
                    manifest_payload=manifest.to_open_dict(),
                )
                for manifest in store.manifests(owner_user_id=owner_user_id)
            ),
            key=lambda state: state.package_id,
        )
    )


def _rebind_resolved_row(
    row: ResolvedPlatformRow,
    *,
    source_states,
) -> ResolvedPlatformRow:
    return resolved_platform_row(
        owner_user_id=row.owner_user_id,
        m_row=row.m_row,
        producer_ref=row.producer_ref,
        record=row.record,
        source_states=tuple(source_states),
    )


def _closure_content_hash(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _legacy_v4_row_from_v5(row: dict) -> dict:
    migrated = json.loads(json.dumps(row))
    snapshot = migrated["receipt"]["snapshot"]
    snapshot.pop("source_bindings")
    snapshot["manifest_hash"] = _closure_content_hash(
        {key: value for key, value in snapshot.items() if key != "manifest_hash"}
    )
    receipt = migrated["receipt"]
    receipt["receipt_version"] = "platform_closure_receipt.v3"
    receipt["receipt_ref"] = "platform_closure_receipt:" + hashlib.sha256(
        json.dumps(
            {
                "owner_user_id": receipt["owner_user_id"],
                "owner_revision": receipt["owner_revision"],
                "previous_receipt_ref": receipt["previous_receipt_ref"],
                "snapshot": snapshot,
                "receipt_version": receipt["receipt_version"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    migrated["schema_version"] = 4
    migrated["record_hash"] = _closure_content_hash(
        {key: value for key, value in migrated.items() if key != "record_hash"}
    )
    return migrated


def test_platform_closure_binds_all_exact_rows_hashes_verdict_and_reloads_current(tmp_path):
    platform, closure = _registries(tmp_path)

    receipt = closure.record_current("owner-a")
    assert receipt == closure.record_current("owner-a")
    assert receipt.owner_revision == 1
    assert receipt.snapshot.required_rows == REQUIRED_PLATFORM_ROWS
    assert tuple(row.m_row for row in receipt.snapshot.rows) == REQUIRED_PLATFORM_ROWS
    assert tuple(
        binding.m_row for binding in receipt.snapshot.source_bindings
    ) == REQUIRED_PLATFORM_ROWS
    assert len(
        {binding.source_coverage_ref for binding in receipt.snapshot.source_bindings}
    ) == len(REQUIRED_PLATFORM_ROWS)
    assert all(
        binding.source_coverage_hash.startswith("sha256:")
        for binding in receipt.snapshot.source_bindings
    )
    assert len({row.record_hash for row in receipt.snapshot.rows}) == len(REQUIRED_PLATFORM_ROWS)
    assert all(row.record_hash.startswith("sha256:") for row in receipt.snapshot.rows)
    assert len({row.production_ref for row in receipt.snapshot.rows}) == len(
        REQUIRED_PLATFORM_ROWS
    )
    assert all(
        row.production_ref.startswith("platform_row_production:")
        for row in receipt.snapshot.rows
    )
    assert receipt.snapshot.strict_manifest_accepted is True
    assert receipt.snapshot.strict_manifest_verdict_hash.startswith("sha256:")
    assert receipt.snapshot.source_manifest_event_hash.startswith("sha256:")
    assert receipt.snapshot.manifest_hash.startswith("sha256:")
    assert tuple(rdp.package_id for rdp in receipt.snapshot.rdps) == (
        _rdp_manifest("fixture-owner-a").package_id,
    )
    assert all(rdp.manifest_hash.startswith("sha256:") for rdp in receipt.snapshot.rdps)
    assert closure.validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted
    assert closure.current_receipt(owner_user_id="owner-a") == receipt
    assert closure.current_row(
        "M14",
        owner_user_id="owner-a",
        receipt_ref=receipt.receipt_ref,
    ) == next(row for row in receipt.snapshot.rows if row.m_row == "M14")
    selected = closure.current_rows(
        owner_user_id="owner-a",
        m_rows=("M13", "M14", "M15", "M18"),
    )
    assert tuple(row.m_row for row in selected) == ("M13", "M14", "M15", "M18")
    with pytest.raises(ValueError, match="unique"):
        closure.current_rows(owner_user_id="owner-a", m_rows=("M14", "M14"))
    with pytest.raises(ValueError, match="unknown"):
        closure.current_row("M22", owner_user_id="owner-a")

    [persisted] = [
        json.loads(line)
        for line in closure.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert persisted["schema_version"] == 5
    assert persisted["owner_user_id"] == "owner-a"
    assert persisted["ledger_revision"] == 1
    assert persisted["owner_revision"] == 1
    assert persisted["record_hash"].startswith("sha256:")
    assert len(persisted["receipt"]["snapshot"]["rows"]) == len(REQUIRED_PLATFORM_ROWS)
    assert len(persisted["receipt"]["snapshot"]["source_bindings"]) == len(
        REQUIRED_PLATFORM_ROWS
    )

    reloaded = _closure_registry(
        closure.path,
        platform,
        resolve_current_manifest=lambda owner: tuple(platform.records(owner_user_id=owner)),
    )
    assert reloaded.receipt(receipt.receipt_ref, owner_user_id="owner-a") == receipt
    assert reloaded.validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted


def test_platform_closure_runs_strict_resolver_before_platform_and_rdp_journal_locks(
    tmp_path,
    monkeypatch,
):
    platform, closure = _registries(tmp_path)
    lock_state = {"platform": False, "rdp": False}
    original_platform_lock = closure._platform_exclusive_lock
    original_rdp_lock = closure._rdp_exclusive_lock
    original_validate = platform.validate_manifest

    @contextmanager
    def tracked_platform_lock():
        with original_platform_lock():
            lock_state["platform"] = True
            try:
                yield
            finally:
                lock_state["platform"] = False

    @contextmanager
    def tracked_rdp_lock():
        with original_rdp_lock():
            lock_state["rdp"] = True
            try:
                yield
            finally:
                lock_state["rdp"] = False

    def validate_without_journal_recursion(records, *, owner_user_id):
        assert lock_state == {"platform": False, "rdp": False}
        return original_validate(records, owner_user_id=owner_user_id)

    monkeypatch.setattr(closure, "_platform_exclusive_lock", tracked_platform_lock)
    monkeypatch.setattr(closure, "_rdp_exclusive_lock", tracked_rdp_lock)
    monkeypatch.setattr(platform, "validate_manifest", validate_without_journal_recursion)

    receipt = closure.record_current("owner-a")
    assert receipt.owner_revision == 1


def test_platform_closure_ignores_unrelated_owner_rdp_append_and_unicode_reload(
    tmp_path,
):
    owner = "owner-a"
    rdp_store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    first_manifest = _rdp_manifest("v1")
    rdp_store.record_manifest(first_manifest, owner_user_id=owner, recorded_by=owner)
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    manifest = _manifest(owner, rdp_package_id=first_manifest.package_id)
    unicode_evidence = f"audit:{owner}:{_slug(REQUIRED_PLATFORM_ROWS[0])}:v1:\u2028:\u2029"
    manifest = (
        replace(manifest[0], evidence_refs=(unicode_evidence,)),
        *manifest[1:],
    )
    platform.record_manifest(manifest, owner_user_id=owner)

    def resolve_rows(selected_owner: str) -> tuple[ResolvedPlatformRow, ...]:
        return _resolved_manifest(
            selected_owner,
            tuple(platform.records(owner_user_id=selected_owner)),
        )

    def resolve_coverage(selected_owner: str, coverage_ref: str):
        matches = tuple(
            coverage
            for coverage in (
                _coverage_for_record(selected_owner, record)
                for record in platform.records(owner_user_id=selected_owner)
            )
            if coverage.coverage_ref == coverage_ref
        )
        if len(matches) != 1:
            raise KeyError(coverage_ref)
        return matches[0]

    def resolve_rdp(selected_owner: str, package_id: str):
        selected = rdp_store.manifest(package_id, owner_user_id=selected_owner)
        return platform_closure_rdp_state(
            package_id=selected.package_id,
            manifest_payload=selected.to_open_dict(),
        )

    closure = PersistentPlatformClosureRegistry(
        tmp_path / "closures.jsonl",
        platform,
        resolve_current_manifest=resolve_rows,
        resolve_current_manifest_unlocked=lambda selected_owner, journal_records: (
            _resolved_manifest(selected_owner, journal_records)
        ),
        resolve_current_coverage=resolve_coverage,
        entrypoint_ledger_path=tmp_path / "goal_entrypoint_coverage.jsonl",
        rdp_path=rdp_store.path,
        resolve_linked_rdp=resolve_rdp,
    )
    first = closure.record_current(owner)
    assert tuple(item.package_id for item in first.snapshot.rdps) == (
        first_manifest.package_id,
    )

    question = "external RDP with U+2028 \u2028 and U+2029 \u2029 remains one JSONL row"
    second_manifest = _rdp_manifest("v2", question=question)
    external = PersistentRDPStore(rdp_store.path)
    external.record_manifest(second_manifest, owner_user_id=owner, recorded_by=owner)

    second = closure.record_current(owner)
    assert second == first
    assert tuple(item.package_id for item in second.snapshot.rdps) == (
        first_manifest.package_id,
    )
    assert closure.validate_current(first.receipt_ref, owner_user_id=owner).accepted
    assert rdp_store.manifest(second_manifest.package_id, owner_user_id=owner).research_question == question

    reloaded = PersistentPlatformClosureRegistry(
        closure.path,
        platform,
        resolve_current_manifest=resolve_rows,
        resolve_current_manifest_unlocked=lambda selected_owner, journal_records: (
            _resolved_manifest(selected_owner, journal_records)
        ),
        resolve_current_coverage=resolve_coverage,
        entrypoint_ledger_path=tmp_path / "goal_entrypoint_coverage.jsonl",
        rdp_path=rdp_store.path,
        resolve_linked_rdp=resolve_rdp,
    )
    assert reloaded.current_receipt(owner_user_id=owner) == second
    assert (
        reloaded.current_receipt(owner_user_id=owner)
        .snapshot.rows[0]
        .record.evidence_refs
        == (unicode_evidence,)
    )


def test_platform_closure_detects_source_state_drift_with_unchanged_outward_refs(tmp_path):
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    records = _manifest("owner-a")
    platform.record_manifest(records, owner_user_id="owner-a")
    revision = {"value": "v1"}
    closure = _closure_registry(
        tmp_path / "closures.jsonl",
        platform,
        resolve_current_manifest=lambda owner: _resolved_manifest(
            owner,
            records,
            source_revision=revision["value"],
        ),
    )

    receipt = closure.record_current("owner-a")
    revision["value"] = "v2"

    decision = closure.validate_current(
        receipt.receipt_ref,
        owner_user_id="owner-a",
    )
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {
        "platform_closure_current_state_drifted"
    }


def test_platform_closure_fails_closed_on_missing_duplicate_placeholder_and_torn_resolution(tmp_path):
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    current = _manifest("owner-a")
    platform.record_manifest(current, owner_user_id="owner-a")

    missing = _closure_registry(
        tmp_path / "missing.jsonl",
        platform,
        resolve_current_manifest=lambda owner: current[:-1],
    )
    with pytest.raises(PlatformClosureError, match="exactly cover"):
        missing.record_current("owner-a")
    assert not missing.path.exists()

    duplicate_rows = current[:-1] + (current[0],)
    duplicate = _closure_registry(
        tmp_path / "duplicate.jsonl",
        platform,
        resolve_current_manifest=lambda owner: duplicate_rows,
    )
    with pytest.raises(PlatformClosureError, match="exactly cover"):
        duplicate.record_current("owner-a")
    assert not duplicate.path.exists()

    placeholder_manifest = (
        replace(current[0], qro_ref="qro:placeholder:owner-a:M1_M2"),
        *current[1:],
    )
    placeholder = _closure_registry(
        tmp_path / "placeholder.jsonl",
        platform,
        resolve_current_manifest=lambda owner: tuple(placeholder_manifest),
    )
    with pytest.raises(PlatformClosureError, match="could not be resolved"):
        placeholder.record_current("owner-a")
    assert not placeholder.path.exists()

    calls = 0

    def changing(owner: str):
        nonlocal calls
        calls += 1
        return current if calls == 1 else _manifest(owner, suffix="v2")

    torn_coverages = {
        coverage.coverage_ref: coverage
        for record in (*current, *_manifest("owner-a", suffix="v2"))
        for coverage in (_coverage_for_record("owner-a", record),)
    }

    torn = _closure_registry(
        tmp_path / "torn.jsonl",
        platform,
        resolve_current_manifest=changing,
        resolve_current_coverage=lambda _owner, ref: torn_coverages[ref],
    )
    with pytest.raises(PlatformClosureError, match="disk-current"):
        torn.record_current("owner-a")
    assert not torn.path.exists()

    rdp_calls = 0
    second_rdp = PlatformClosureRDPState(
        package_id=_rdp_manifest("fixture-owner-a").package_id,
        manifest_hash="sha256:" + "f" * 64,
    )

    def changing_rdp(owner: str, package_id: str):
        nonlocal rdp_calls
        rdp_calls += 1
        if rdp_calls == 1:
            manifest = _rdp_manifest(f"fixture-{owner}")
            assert package_id == manifest.package_id
            return platform_closure_rdp_state(
                package_id=manifest.package_id,
                manifest_payload=manifest.to_open_dict(),
            )
        assert package_id == second_rdp.package_id
        return second_rdp

    torn_rdp = _closure_registry(
        tmp_path / "torn_rdp.jsonl",
        platform,
        resolve_current_manifest=lambda owner: current,
        resolve_linked_rdp=changing_rdp,
    )
    with pytest.raises(PlatformClosureError, match="RDP backing changed"):
        torn_rdp.record_current("owner-a")
    assert rdp_calls == 2
    assert not torn_rdp.path.exists()


def test_platform_closure_detects_record_drift_and_isolates_owner_lineages(tmp_path):
    platform, closure = _registries(tmp_path)
    platform.record_manifest(_manifest("owner-b"), owner_user_id="owner-b")
    first = closure.record_current("owner-a")
    foreign = closure.record_current("owner-b")

    assert first.receipt_ref != foreign.receipt_ref
    with pytest.raises(KeyError, match="not recorded for owner"):
        closure.receipt(first.receipt_ref, owner_user_id="owner-b")

    platform.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    decision = closure.validate_current(first.receipt_ref, owner_user_id="owner-a")
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {
        "platform_closure_current_state_drifted"
    }
    with pytest.raises(PlatformClosureError, match="disk-current strict backing"):
        closure.current_row("M14", owner_user_id="owner-a")

    second = closure.record_current("owner-a")
    assert second.owner_revision == 2
    assert second.previous_receipt_ref == first.receipt_ref
    assert second.snapshot.manifest_hash != first.snapshot.manifest_hash
    assert closure.validate_current(second.receipt_ref, owner_user_id="owner-a").accepted
    old = closure.validate_current(first.receipt_ref, owner_user_id="owner-a")
    assert "platform_closure_receipt_not_head" in {item.code for item in old.violations}


def test_platform_closure_unrelated_same_owner_rdp_does_not_drift_exact_lineage(tmp_path):
    _platform, closure = _registries(tmp_path)
    receipt = closure.record_current("owner-a")
    manifest = _rdp_manifest(
        "drift-v2",
        question="unrelated owner RDP must not invalidate exact closure lineage",
    )
    PersistentRDPStore(closure.rdp_path).record_manifest(
        manifest,
        owner_user_id="owner-a",
        recorded_by="owner-a",
    )

    decision = closure.validate_current(receipt.receipt_ref, owner_user_id="owner-a")
    assert decision.accepted
    updated = closure.record_current("owner-a")
    assert updated == receipt
    assert manifest.package_id not in {
        item.package_id for item in updated.snapshot.rdps
    }


def test_platform_closure_linked_rdp_change_requires_same_row_coverage_revision(tmp_path):
    platform, closure = _registries(tmp_path)
    first = closure.record_current("owner-a")
    second_manifest = _rdp_manifest("linked-v2")
    PersistentRDPStore(closure.rdp_path).record_manifest(
        second_manifest,
        owner_user_id="owner-a",
        recorded_by="owner-a",
    )
    platform.record_manifest(
        _manifest(
            "owner-a",
            suffix="v2",
            rdp_package_id=second_manifest.package_id,
        ),
        owner_user_id="owner-a",
    )

    second = closure.record_current("owner-a")
    assert second.owner_revision == first.owner_revision + 1
    assert second.previous_receipt_ref == first.receipt_ref
    assert tuple(rdp.package_id for rdp in second.snapshot.rdps) == (
        second_manifest.package_id,
    )
    m18_binding = next(
        binding
        for binding in second.snapshot.source_bindings
        if binding.m_row == "M18"
    )
    assert tuple(rdp.package_id for rdp in m18_binding.rdps) == (
        second_manifest.package_id,
    )


def test_platform_closure_rejects_missing_recombined_and_hash_drifted_coverage(
    tmp_path,
):
    owner = "owner-a"
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    records = _manifest(owner)
    platform.record_manifest(records, owner_user_id=owner)
    rows = _resolved_manifest(owner, records)
    coverages = {
        coverage.coverage_ref: coverage
        for coverage in (_coverage_for_record(owner, record) for record in records)
    }

    missing = _closure_registry(
        tmp_path / "missing_coverage.jsonl",
        platform,
        resolve_current_manifest=lambda _owner: rows,
        resolve_current_coverage=lambda _owner, _ref: (_ for _ in ()).throw(
            KeyError("missing source coverage")
        ),
    )
    with pytest.raises(PlatformClosureError, match="could not be resolved"):
        missing.record_current(owner)

    first_states = list(rows[0].source_states)
    second_coverage_state = next(
        state
        for state in rows[1].source_states
        if state.source_kind == "goal_entrypoint_coverage"
    )
    first_states = [
        second_coverage_state
        if state.source_kind == "goal_entrypoint_coverage"
        else state
        for state in first_states
    ]
    recombined_rows = (
        _rebind_resolved_row(rows[0], source_states=first_states),
        *rows[1:],
    )
    recombined = _closure_registry(
        tmp_path / "recombined_coverage.jsonl",
        platform,
        resolve_current_manifest=lambda _owner: recombined_rows,
        resolve_current_coverage=lambda _owner, ref: coverages[ref],
    )
    with pytest.raises(PlatformClosureError, match="stale or recombined"):
        recombined.record_current(owner)

    drifted_states = [
        replace(state, state_hash="sha256:" + "0" * 64)
        if state.source_kind == "goal_entrypoint_coverage"
        else state
        for state in rows[0].source_states
    ]
    hash_drifted_rows = (
        _rebind_resolved_row(rows[0], source_states=drifted_states),
        *rows[1:],
    )
    hash_drifted = _closure_registry(
        tmp_path / "hash_drifted_coverage.jsonl",
        platform,
        resolve_current_manifest=lambda _owner: hash_drifted_rows,
        resolve_current_coverage=lambda _owner, ref: coverages[ref],
    )
    with pytest.raises(PlatformClosureError, match="stale or recombined"):
        hash_drifted.record_current(owner)

    m18_index = REQUIRED_PLATFORM_ROWS.index("M18")
    m18_row = rows[m18_index]
    missing_rdp_coverage = replace(
        _coverage_for_record(owner, m18_row.record),
        rdp_refs=(),
    )
    missing_rdp_states = [
        platform_row_source_state(
            source_kind="goal_entrypoint_coverage",
            source_ref=missing_rdp_coverage.coverage_ref,
            state_payload=asdict(missing_rdp_coverage),
        )
        if state.source_kind == "goal_entrypoint_coverage"
        else state
        for state in m18_row.source_states
    ]
    missing_rdp_rows = (
        *rows[:m18_index],
        _rebind_resolved_row(m18_row, source_states=missing_rdp_states),
        *rows[m18_index + 1 :],
    )
    missing_rdp = _closure_registry(
        tmp_path / "missing_m18_rdp.jsonl",
        platform,
        resolve_current_manifest=lambda _owner: missing_rdp_rows,
        resolve_current_coverage=lambda _owner, ref: (
            missing_rdp_coverage
            if ref == missing_rdp_coverage.coverage_ref
            else coverages[ref]
        ),
    )
    with pytest.raises(PlatformClosureError, match="M18 source coverage"):
        missing_rdp.record_current(owner)


def test_platform_closure_rejects_foreign_and_hash_recombined_linked_rdp(tmp_path):
    owner = "owner-a"
    foreign_manifest = _rdp_manifest("foreign-owner-only")
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    records = _manifest(owner, rdp_package_id=foreign_manifest.package_id)
    platform.record_manifest(records, owner_user_id=owner)
    foreign = _closure_registry(
        tmp_path / "foreign.jsonl",
        platform,
        resolve_current_manifest=lambda selected_owner: _resolved_manifest(
            selected_owner,
            tuple(platform.records(owner_user_id=selected_owner)),
        ),
    )
    PersistentRDPStore(foreign.rdp_path).record_manifest(
        foreign_manifest,
        owner_user_id="owner-b",
        recorded_by="owner-b",
    )
    with pytest.raises(PlatformClosureError, match="could not be resolved for owner"):
        foreign.record_current(owner)

    platform.record_manifest(_manifest(owner, suffix="v2"), owner_user_id=owner)
    wrong_hash = _closure_registry(
        tmp_path / "wrong_hash.jsonl",
        platform,
        resolve_current_manifest=lambda selected_owner: _resolved_manifest(
            selected_owner,
            tuple(platform.records(owner_user_id=selected_owner)),
        ),
        resolve_linked_rdp=lambda _owner, package_id: PlatformClosureRDPState(
            package_id=package_id,
            manifest_hash="sha256:" + "f" * 64,
        ),
    )
    with pytest.raises(PlatformClosureError, match="disk-current owner revisions"):
        wrong_hash.record_current(owner)


def test_platform_closure_skips_valid_quarantined_v1_and_rejects_malformed_v2(
    tmp_path,
):
    owner = "owner-a"
    rdp_path = tmp_path / "rdp_manifests.jsonl"
    legacy = _rdp_manifest("legacy-v1")
    legacy_row = {
        "schema_version": 1,
        "event_type": "rdp_manifest_recorded",
        "has_user_waiver": False,
        "manifest": _legacy_v1_rdp_manifest_payload(legacy),
    }
    rdp_path.write_text(
        json.dumps(legacy_row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rdp_store = PersistentRDPStore(rdp_path)
    current = _rdp_manifest("current-v2")
    rdp_store.record_manifest(current, owner_user_id=owner, recorded_by=owner)
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    records = _manifest(owner, rdp_package_id=current.package_id)
    platform.record_manifest(records, owner_user_id=owner)

    def resolve_coverage(selected_owner: str, coverage_ref: str):
        matches = tuple(
            coverage
            for coverage in (
                _coverage_for_record(selected_owner, record)
                for record in platform.records(owner_user_id=selected_owner)
            )
            if coverage.coverage_ref == coverage_ref
        )
        if len(matches) != 1:
            raise KeyError(coverage_ref)
        return matches[0]

    def resolve_rdp(selected_owner: str, package_id: str):
        selected = rdp_store.manifest(package_id, owner_user_id=selected_owner)
        return platform_closure_rdp_state(
            package_id=selected.package_id,
            manifest_payload=selected.to_open_dict(),
        )

    closure = PersistentPlatformClosureRegistry(
        tmp_path / "closures.jsonl",
        platform,
        resolve_current_manifest=lambda selected_owner: _resolved_manifest(
            selected_owner,
            tuple(platform.records(owner_user_id=selected_owner)),
        ),
        resolve_current_manifest_unlocked=lambda selected_owner, journal_records: (
            _resolved_manifest(selected_owner, journal_records)
        ),
        resolve_current_coverage=resolve_coverage,
        entrypoint_ledger_path=tmp_path / "goal_entrypoint_coverage.jsonl",
        rdp_path=rdp_path,
        resolve_linked_rdp=resolve_rdp,
    )

    receipt = closure.record_current(owner)
    assert tuple(item.package_id for item in receipt.snapshot.rdps) == (
        current.package_id,
    )

    poison = {
        "schema_version": 2,
        "event_type": "rdp_manifest_recorded",
        "owner_user_id": owner,
        "recorded_by": owner,
        "has_user_waiver": False,
        "manifest": {"package_id": "rdp_skeletal"},
    }
    with rdp_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(poison, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    with pytest.raises(PlatformClosureError, match="could not be resolved"):
        closure.record_current(owner)


def test_platform_closure_holds_rdp_lock_through_commit_and_ignores_unrelated_writer(
    tmp_path,
    monkeypatch,
):
    _platform, closure = _registries(tmp_path)
    manifest = _rdp_manifest(
        "concurrent-v2",
        question="concurrent RDP write after closure commit",
    )
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    probe_done = context.Event()
    initially_blocked = context.Event()
    initially_acquired = context.Event()
    finished = context.Event()
    child = context.Process(
        target=_record_rdp_manifest_after_lock_probe,
        args=(
            str(closure.rdp_path),
            manifest.to_open_dict(),
            "owner-a",
            start_gate,
            probe_done,
            initially_blocked,
            initially_acquired,
            finished,
        ),
    )
    original_append = closure._atomic_append

    def append_while_writer_probes(commit_row, *, precommit_assertion):
        start_gate.set()
        assert probe_done.wait(5.0), "child RDP lock probe timed out"
        assert initially_blocked.is_set(), "RDP writer acquired before closure commit"
        assert not initially_acquired.is_set()
        original_append(
            commit_row,
            precommit_assertion=precommit_assertion,
        )

    monkeypatch.setattr(closure, "_atomic_append", append_while_writer_probes)
    child.start()
    try:
        receipt = closure.record_current("owner-a")
        assert receipt.owner_revision == 1
        assert finished.wait(5.0), "RDP writer did not make progress after closure commit"
    finally:
        child.join(timeout=5.0)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5.0)

    assert child.exitcode == 0
    assert len(closure.path.read_text(encoding="utf-8").splitlines()) == 1
    decision = closure.validate_current(receipt.receipt_ref, owner_user_id="owner-a")
    assert decision.accepted


def test_platform_closure_apply_failure_writes_no_partial_row_and_retry_is_singleton(
    tmp_path,
    monkeypatch,
):
    platform, closure = _registries(tmp_path)
    first = closure.record_current("owner-a")
    before = closure.path.read_bytes()
    platform_before = platform.path.read_bytes()
    rdp_before = closure.rdp_path.read_bytes()
    platform.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    platform_after_manifest_change = platform.path.read_bytes()
    original_apply = closure._apply_row

    def fail_new_row(row):
        if row.get("owner_revision") == 2:
            raise RuntimeError("injected closure apply failure")
        return original_apply(row)

    monkeypatch.setattr(closure, "_apply_row", fail_new_row)
    with pytest.raises(RuntimeError, match="injected closure apply failure"):
        closure.record_current("owner-a")
    assert closure.path.read_bytes() == before
    assert platform_before != platform_after_manifest_change
    assert platform.path.read_bytes() == platform_after_manifest_change
    assert closure.rdp_path.read_bytes() == rdp_before

    monkeypatch.setattr(closure, "_apply_row", original_apply)
    second = closure.record_current("owner-a")
    assert second.owner_revision == 2
    assert second.previous_receipt_ref == first.receipt_ref
    assert closure.record_current("owner-a") == second
    assert len(closure.path.read_text(encoding="utf-8").splitlines()) == 2


def test_platform_closure_directory_fsync_failure_restores_exact_bytes_and_retry(
    tmp_path,
    monkeypatch,
):
    platform, closure = _registries(tmp_path)
    first = closure.record_current("owner-a")
    before = closure.path.read_bytes()
    platform_before = platform.path.read_bytes()
    rdp_before = closure.rdp_path.read_bytes()
    platform.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    platform_after_manifest_change = platform.path.read_bytes()
    real_fsync = platform_closure_module.os.fsync
    failed = False

    def fail_first_directory_fsync(fd):
        nonlocal failed
        if not failed and stat.S_ISDIR(os.fstat(fd).st_mode):
            failed = True
            raise OSError("injected closure directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(platform_closure_module.os, "fsync", fail_first_directory_fsync)
    with pytest.raises(OSError, match="injected closure directory fsync failure"):
        closure.record_current("owner-a")
    assert failed
    assert closure.path.read_bytes() == before
    assert platform_before != platform_after_manifest_change
    assert platform.path.read_bytes() == platform_after_manifest_change
    assert closure.rdp_path.read_bytes() == rdp_before

    monkeypatch.setattr(platform_closure_module.os, "fsync", real_fsync)
    second = closure.record_current("owner-a")
    assert second.owner_revision == 2
    assert second.previous_receipt_ref == first.receipt_ref
    assert closure.record_current("owner-a") == second
    assert len(closure.path.read_text(encoding="utf-8").splitlines()) == 2


def test_platform_closure_replace_then_error_restores_exact_bytes_and_retry(
    tmp_path,
    monkeypatch,
):
    platform, closure = _registries(tmp_path)
    first = closure.record_current("owner-a")
    before = closure.path.read_bytes()
    rdp_before = closure.rdp_path.read_bytes()
    platform.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    platform_before_failure = platform.path.read_bytes()
    real_replace = platform_closure_module.os.replace
    failed = False

    def replace_then_raise(source, target):
        nonlocal failed
        real_replace(source, target)
        if not failed and Path(target) == closure.path:
            failed = True
            raise OSError("injected closure replace-after-effect failure")

    monkeypatch.setattr(platform_closure_module.os, "replace", replace_then_raise)
    with pytest.raises(OSError, match="injected closure replace-after-effect failure"):
        closure.record_current("owner-a")
    assert failed
    assert closure.path.read_bytes() == before
    assert platform.path.read_bytes() == platform_before_failure
    assert closure.rdp_path.read_bytes() == rdp_before

    monkeypatch.setattr(platform_closure_module.os, "replace", real_replace)
    second = closure.record_current("owner-a")
    assert second.owner_revision == 2
    assert second.previous_receipt_ref == first.receipt_ref
    assert closure.record_current("owner-a") == second
    assert len(closure.path.read_text(encoding="utf-8").splitlines()) == 2


def test_platform_closure_first_replace_then_error_removes_new_file_and_retries(
    tmp_path,
    monkeypatch,
):
    platform, closure = _registries(tmp_path)
    platform_before = platform.path.read_bytes()
    rdp_before = closure.rdp_path.read_bytes()
    real_replace = platform_closure_module.os.replace
    failed = False

    def replace_then_raise(source, target):
        nonlocal failed
        real_replace(source, target)
        if not failed and Path(target) == closure.path:
            failed = True
            raise OSError("injected first closure replace-after-effect failure")

    monkeypatch.setattr(platform_closure_module.os, "replace", replace_then_raise)
    with pytest.raises(OSError, match="injected first closure replace-after-effect failure"):
        closure.record_current("owner-a")
    assert failed
    assert not closure.path.exists()
    assert platform.path.read_bytes() == platform_before
    assert closure.rdp_path.read_bytes() == rdp_before

    monkeypatch.setattr(platform_closure_module.os, "replace", real_replace)
    first = closure.record_current("owner-a")
    assert first.owner_revision == 1
    assert first.previous_receipt_ref == ""
    assert closure.record_current("owner-a") == first
    assert len(closure.path.read_text(encoding="utf-8").splitlines()) == 1


def test_platform_closure_append_normalizes_missing_terminal_newline(tmp_path):
    platform, closure = _registries(tmp_path)
    first = closure.record_current("owner-a")
    closure.path.write_bytes(closure.path.read_bytes().rstrip(b"\n"))

    platform.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    second = closure.record_current("owner-a")

    assert second.owner_revision == first.owner_revision + 1
    reloaded = _closure_registry(
        closure.path,
        platform,
        resolve_current_manifest=lambda owner: tuple(
            platform.records(owner_user_id=owner)
        ),
    )
    assert reloaded.current_receipt(owner_user_id="owner-a") == second


def test_platform_closure_rejects_cross_process_staleness_and_a_b_a_journal_regression(tmp_path):
    platform, closure = _registries(tmp_path)
    first = closure.record_current("owner-a")

    external = PersistentPlatformCoverageRegistry(
        platform.path,
        resolver=_OwnerResolver(),
    )
    external.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    with pytest.raises(PlatformClosureError, match="disk-current"):
        closure.current_receipt(owner_user_id="owner-a")
    stale = closure.validate_current(first.receipt_ref, owner_user_id="owner-a")
    assert not stale.accepted
    assert {item.code for item in stale.violations} == {
        "platform_closure_current_state_drifted"
    }

    refreshed = PersistentPlatformCoverageRegistry(
        platform.path,
        resolver=_OwnerResolver(),
    )
    a_b_a_closure = _closure_registry(
        tmp_path / "a_b_a_closures.jsonl",
        refreshed,
        resolve_current_manifest=lambda owner: tuple(
            refreshed.records(owner_user_id=owner)
        ),
    )
    current_b = a_b_a_closure.record_current("owner-a")
    assert current_b.snapshot.rows[0].record.evidence_refs[0].endswith(":v2")

    # The fresh platform registry now rejects an A-B-A replay before mutating
    # its cache; closure must continue to resolve the disk-current B receipt.
    with pytest.raises(ValueError, match="stale platform coverage manifest replay"):
        refreshed.record_manifest(_manifest("owner-a"), owner_user_id="owner-a")
    assert refreshed.records(owner_user_id="owner-a")[0].evidence_refs[0].endswith(":v2")
    assert a_b_a_closure.record_current("owner-a") == current_b


def test_platform_closure_quarantines_legacy_but_rejects_hash_tampering_and_partial_rows(tmp_path):
    legacy_path = tmp_path / "legacy.jsonl"
    legacy_path.write_text(
        json.dumps({"schema_version": 1, "event_type": "platform_closure_recorded"}) + "\n",
        encoding="utf-8",
    )
    platform = PersistentPlatformCoverageRegistry(
        tmp_path / "platform.jsonl",
        resolver=_OwnerResolver(),
    )
    platform.record_manifest(_manifest("owner-a"), owner_user_id="owner-a")
    closure = _closure_registry(
        legacy_path,
        platform,
        resolve_current_manifest=lambda owner: tuple(platform.records(owner_user_id=owner)),
    )
    assert closure.legacy_quarantined_count == 1
    closure.record_current("owner-a")

    lines = legacy_path.read_text(encoding="utf-8").splitlines()
    persisted = json.loads(lines[-1])
    persisted["record_hash"] = "sha256:" + "0" * 64
    legacy_path.write_text(lines[0] + "\n" + json.dumps(persisted) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid persisted platform closure row"):
        _closure_registry(
            legacy_path,
            platform,
            resolve_current_manifest=lambda owner: tuple(platform.records(owner_user_id=owner)),
        )

    partial_path = tmp_path / "partial.jsonl"
    partial_path.write_text('{"schema_version":4', encoding="utf-8")
    with pytest.raises(ValueError, match="partial/corrupt platform closure row"):
        _closure_registry(
            partial_path,
            platform,
            resolve_current_manifest=lambda owner: tuple(platform.records(owner_user_id=owner)),
        )


def test_platform_closure_schema_v5_continues_valid_v4_chain_but_never_serves_v4_head(
    tmp_path,
):
    platform, closure = _registries(tmp_path)
    closure.record_current("owner-a")
    [current_row] = [
        json.loads(line)
        for line in closure.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    legacy_row = _legacy_v4_row_from_v5(current_row)
    closure.path.write_text(
        json.dumps(legacy_row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    migrated = _closure_registry(
        closure.path,
        platform,
        resolve_current_manifest=lambda owner: tuple(
            platform.records(owner_user_id=owner)
        ),
    )
    assert migrated.legacy_quarantined_count == 1
    with pytest.raises(KeyError, match="no current receipt"):
        migrated.current_receipt(owner_user_id="owner-a")

    receipt = migrated.record_current("owner-a")
    assert receipt.owner_revision == 2
    assert receipt.previous_receipt_ref == legacy_row["receipt"]["receipt_ref"]
    rows = [
        json.loads(line)
        for line in closure.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["schema_version"] for row in rows] == [4, 5]
    assert [row["ledger_revision"] for row in rows] == [1, 2]
    assert rows[1]["previous_record_hash"] == rows[0]["record_hash"]
    assert migrated.current_receipt(owner_user_id="owner-a") == receipt


class _StrictEntrypointResolver:
    def __init__(
        self,
        *,
        owner: str,
        qro_refs: frozenset[str],
        graph_refs: frozenset[str],
        ir_refs: frozenset[str],
        pass_refs: frozenset[str],
        evidence_refs: frozenset[str],
        lifecycle_refs: frozenset[str],
        rdp_refs: frozenset[str],
        bound_owner: str | None = None,
        reject_linkage: bool = False,
    ) -> None:
        self.owner = owner
        self.qro_refs = qro_refs
        self.graph_refs = graph_refs
        self.ir_refs = ir_refs
        self.pass_refs = pass_refs
        self.evidence_refs = evidence_refs
        self.lifecycle_refs = lifecycle_refs
        self.rdp_refs = rdp_refs
        self.bound_owner = bound_owner
        self.reject_linkage = reject_linkage

    def for_owner(self, owner: str):
        return _StrictEntrypointResolver(
            owner=self.owner,
            qro_refs=self.qro_refs,
            graph_refs=self.graph_refs,
            ir_refs=self.ir_refs,
            pass_refs=self.pass_refs,
            evidence_refs=self.evidence_refs,
            lifecycle_refs=self.lifecycle_refs,
            rdp_refs=self.rdp_refs,
            bound_owner=owner,
            reject_linkage=self.reject_linkage,
        )

    def _matches(self, actual: str, expected: frozenset[str]) -> bool:
        return self.bound_owner == self.owner and actual in expected

    def has_qro(self, ref: str) -> bool:
        return self._matches(ref, self.qro_refs)

    def has_research_graph_command(self, ref: str) -> bool:
        return self._matches(ref, self.graph_refs)

    def has_compiler_ir(self, ref: str) -> bool:
        return self._matches(ref, self.ir_refs)

    def has_compiler_pass(self, ref: str) -> bool:
        return self._matches(ref, self.pass_refs)

    def has_evidence(self, ref: str) -> bool:
        return self._matches(ref, self.evidence_refs)

    def has_lifecycle_record(self, ref: str) -> bool:
        return self._matches(ref, self.lifecycle_refs)

    def has_rdp(self, ref: str) -> bool:
        return self._matches(ref, self.rdp_refs)

    def entrypoint_linkage_violations(self, record):
        if self.reject_linkage:
            return (("validation_refs", record.coverage_ref, "forced strict linkage rejection"),)
        if (
            self.bound_owner != self.owner
            or record.recorded_by != self.owner
            or record.entry_source != "api"
            or "§14" not in tuple(record.goal_sections)
            or not all(
                ref.startswith("goal_validation_receipt:")
                for ref in record.validation_refs
            )
        ):
            return (
                (
                    "validation_refs",
                    ",".join(record.validation_refs),
                    "platform row source lineage is incoherent",
                ),
            )
        return ()


def _semantic_proof(material, *, coverage_refs: tuple[str, ...], owner: str = "owner-a"):
    fields = dict(
        section="§14",
        subject_ref=material.subject_ref,
        producer_refs=material.producer_refs,
        store_refs=material.store_refs,
        consumer_refs=material.consumer_refs,
        gate_verdict_refs=material.gate_verdict_refs,
        test_refs=material.test_refs,
        entrypoint_coverage_refs=coverage_refs,
        recorded_by=owner,
        claims_section_complete=True,
        unverified_residuals=(),
    )
    return GoalSectionSemanticProofRecord(
        proof_ref=goal_section_semantic_proof_identity(**fields),
        **fields,
    )


def test_platform_closure_section_adapter_requires_all_current_row_source_lineages(tmp_path):
    platform, closure = _registries(tmp_path)
    receipt = closure.record_current("owner-a")
    coverages: list[GoalEntrypointCoverageRecord] = []
    validations: list[str] = []
    ir_refs: set[str] = set()
    pass_refs: set[str] = set()
    for row, binding in zip(
        receipt.snapshot.rows,
        receipt.snapshot.source_bindings,
        strict=True,
    ):
        slug = _slug(row.m_row)
        ir_ref = f"compiler_ir:owner-a:{slug}:source"
        pass_ref = f"compiler_pass:owner-a:{slug}:source"
        validation_ref = f"goal_validation_receipt:owner-a:{slug}:source"
        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source="api",
            entrypoint_ref=f"api:platform.row.{slug}",
            goal_sections=PLATFORM_CLOSURE_GOAL_SECTIONS,
            qro_refs=(str(row.record.qro_ref),),
            research_graph_command_refs=(str(row.record.research_graph_ref),),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        coverages.append(
            GoalEntrypointCoverageRecord(
                coverage_ref=coverage_ref,
                entry_source="api",
                entrypoint_ref=f"api:platform.row.{slug}",
                goal_sections=PLATFORM_CLOSURE_GOAL_SECTIONS,
                qro_refs=(str(row.record.qro_ref),),
                research_graph_command_refs=(str(row.record.research_graph_ref),),
                compiler_ir_refs=(ir_ref,),
                compiler_pass_refs=(pass_ref,),
                evidence_refs=tuple(row.record.evidence_refs),
                validation_refs=(validation_ref,),
                permission_refs=(f"permission:owner-a:{slug}:source",),
                replay_refs=(
                    f"replay:research_graph:{row.record.research_graph_ref}",
                    f"replay:compiler_ir:{ir_ref}",
                    f"replay:compiler_pass:{pass_ref}",
                ),
                canonical_command_refs=(str(row.record.research_graph_ref),),
                lifecycle_refs=(str(row.record.lifecycle_ref),),
                rdp_refs=tuple(rdp.package_id for rdp in binding.rdps),
                recorded_by="owner-a",
                silent_mock_fallback_used=False,
                raw_payload_persisted=False,
            )
        )
        validations.append(validation_ref)
        ir_refs.add(ir_ref)
        pass_refs.add(pass_ref)
    resolver = _StrictEntrypointResolver(
        owner="owner-a",
        qro_refs=frozenset(str(row.record.qro_ref) for row in receipt.snapshot.rows),
        graph_refs=frozenset(str(row.record.research_graph_ref) for row in receipt.snapshot.rows),
        ir_refs=frozenset(ir_refs),
        pass_refs=frozenset(pass_refs),
        evidence_refs=frozenset(
            ref for row in receipt.snapshot.rows for ref in row.record.evidence_refs
        ),
        lifecycle_refs=frozenset(str(row.record.lifecycle_ref) for row in receipt.snapshot.rows),
        rdp_refs=frozenset(rdp.package_id for rdp in receipt.snapshot.rdps),
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl",
        resolver=resolver,
    )
    for coverage in coverages:
        entrypoints.record_coverage(coverage)
    coverage_refs = tuple(coverage.coverage_ref for coverage in coverages)

    class _CurrentSources:
        drift = False
        substitute_coverage = False

        def source_coverage_ref(self, row, *, owner_user_id):
            assert owner_user_id == "owner-a"
            index = REQUIRED_PLATFORM_ROWS.index(str(row))
            if self.substitute_coverage and index == 0:
                return coverage_refs[1]
            return coverage_refs[index]

        def resolve_current_row(self, row, *, owner_user_id):
            assert owner_user_id == "owner-a"
            state = receipt.snapshot.rows[REQUIRED_PLATFORM_ROWS.index(str(row))]
            return SimpleNamespace(
                production_ref=(
                    "platform_row_production:" + "f" * 64
                    if self.drift and str(row) == REQUIRED_PLATFORM_ROWS[0]
                    else state.production_ref
                ),
                record=state.record,
            )

    sources = _CurrentSources()
    adapter = PlatformClosureSectionAdapter(entrypoints, closure, sources)
    material = platform_closure_semantic_material(
        receipt,
        coverage_refs=coverage_refs,
        validation_refs=tuple(validations),
    )
    proof = _semantic_proof(material, coverage_refs=coverage_refs)
    assert adapter.validate(proof, owner="owner-a").accepted

    sources.drift = True
    assert not adapter.validate(proof, owner="owner-a").accepted
    sources.drift = False
    sources.substitute_coverage = True
    assert not adapter.validate(proof, owner="owner-a").accepted
    sources.substitute_coverage = False

    wrong_owner = adapter.validate(proof, owner="owner-b")
    assert not wrong_owner.accepted
    entrypoints.set_ref_resolver(
        _StrictEntrypointResolver(
            owner="owner-a",
            qro_refs=resolver.qro_refs,
            graph_refs=resolver.graph_refs,
            ir_refs=resolver.ir_refs,
            pass_refs=resolver.pass_refs,
            evidence_refs=resolver.evidence_refs,
            lifecycle_refs=resolver.lifecycle_refs,
            rdp_refs=resolver.rdp_refs,
            reject_linkage=True,
        )
    )
    assert not adapter.validate(proof, owner="owner-a").accepted
    entrypoints.set_ref_resolver(resolver)

    platform.record_manifest(_manifest("owner-a", suffix="v2"), owner_user_id="owner-a")
    stale = adapter.validate(proof, owner="owner-a")
    assert not stale.accepted
    assert any("no longer current" in item.message for item in stale.violations)

    recombined = replace(
        proof,
        entrypoint_coverage_refs=(coverage_refs[1], coverage_refs[0], *coverage_refs[2:]),
    )
    assert not adapter.validate(recombined, owner="owner-a").accepted


def test_platform_closure_endpoint_appends_only_the_closure_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app import main

    _platform, closure = _registries(tmp_path)

    class _ForbiddenDerivedStore:
        def __getattr__(self, name):
            raise AssertionError(f"platform closure endpoint touched derived store: {name}")

    monkeypatch.setattr(main, "PLATFORM_CLOSURE_REGISTRY", closure)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", _ForbiddenDerivedStore())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", _ForbiddenDerivedStore())
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", _ForbiddenDerivedStore())
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", _ForbiddenDerivedStore())
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="owner-a",
        user_id="owner-a",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/goal/platform_closure/current"
        )
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "receipt_ref",
        "source_manifest_event_hash",
        "manifest_hash",
        "platform_row_total",
        "rdp_manifest_total",
        "rdp_package_ids",
        "recorded_by",
    }
    assert body["rdp_package_ids"] == [_rdp_manifest("fixture-owner-a").package_id]
    assert len(closure.path.read_text(encoding="utf-8").splitlines()) == 1


def test_platform_closure_paused_append_blocks_cross_instance_row_source_mutation(
    tmp_path,
    monkeypatch,
):
    system = _atomic_section14_system(tmp_path)
    owner = system.owner
    entrypoints = system.entrypoints
    rag = system.rag
    typed = system.typed
    rows = system.rows
    closure = system.closure
    external_rows = PersistentPlatformRowSourceRegistry(
        rows.path,
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=typed,
    )

    target_row = REQUIRED_PLATFORM_ROWS[0]
    replacement_base = _manifest(owner, suffix="v2")[0]
    replacement_coverage, replacement_document = _atomic_row_inputs(
        owner,
        replacement_base,
        suffix="v2",
    )
    entrypoints.add(replacement_coverage)
    rag.add(owner, replacement_document)

    append_paused = threading.Event()
    release_append = threading.Event()
    mutation_started = threading.Event()
    mutation_finished = threading.Event()
    final_same_generation_asserted = threading.Event()
    original_append = closure._atomic_append
    original_verified_head = closure._verified_head_unlocked
    closure_results: list = []
    mutation_results: list = []
    failures: list[BaseException] = []

    def paused_append(row, *, precommit_assertion):
        append_paused.set()
        assert release_append.wait(5.0)
        return original_append(
            row,
            precommit_assertion=precommit_assertion,
        )

    def tracked_verified_head(*args, **kwargs):
        result = original_verified_head(*args, **kwargs)
        if closure.path.exists():
            final_same_generation_asserted.set()
        return result

    monkeypatch.setattr(closure, "_atomic_append", paused_append)
    monkeypatch.setattr(closure, "_verified_head_unlocked", tracked_verified_head)

    def record_closure() -> None:
        try:
            closure_results.append(closure.record_current(owner))
        except BaseException as exc:  # noqa: BLE001 - thread evidence is asserted below.
            failures.append(exc)

    def mutate_source() -> None:
        mutation_started.set()
        try:
            mutation_results.append(
                external_rows.record_current(
                    owner_user_id=owner,
                    m_row=target_row,
                    source_coverage_ref=replacement_coverage.coverage_ref,
                    rag_ref=replacement_document.document_id,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence is asserted below.
            failures.append(exc)
        finally:
            mutation_finished.set()

    closure_thread = threading.Thread(target=record_closure, daemon=True)
    closure_thread.start()
    assert append_paused.wait(5.0)
    mutation_thread = threading.Thread(target=mutate_source, daemon=True)
    mutation_thread.start()
    assert mutation_started.wait(1.0)
    assert not mutation_finished.wait(0.2)

    release_append.set()
    closure_thread.join(5.0)
    mutation_thread.join(5.0)
    assert not closure_thread.is_alive()
    assert not mutation_thread.is_alive()
    assert failures == []
    assert len(closure_results) == 1
    assert len(mutation_results) == 1
    assert final_same_generation_asserted.is_set()
    receipt = closure_results[0]
    assert receipt.snapshot.rows[0].record == system.initial_records[target_row]
    assert not closure.validate_current(
        receipt.receipt_ref,
        owner_user_id=owner,
    ).accepted
    with pytest.raises(PlatformClosureError, match="disk-current owner-scoped"):
        closure.record_current(owner)


def test_section14_semantic_append_is_one_generation_against_source_mutation(
    tmp_path,
    monkeypatch,
):
    system = _atomic_section14_system(tmp_path)
    owner = system.owner
    receipt = system.closure.record_current(owner)
    coverage_refs = tuple(
        binding.source_coverage_ref for binding in receipt.snapshot.source_bindings
    )
    validation_refs = tuple(
        ref
        for coverage_ref in coverage_refs
        for ref in system.entrypoints.coverage(
            coverage_ref,
            owner=owner,
        ).validation_refs
    )
    material = platform_closure_semantic_material(
        receipt,
        coverage_refs=coverage_refs,
        validation_refs=validation_refs,
    )
    proof = _semantic_proof(
        material,
        coverage_refs=coverage_refs,
        owner=owner,
    )
    adapter = PlatformClosureSectionAdapter(
        system.entrypoints,
        system.closure,
        system.rows,
    )
    semantic = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "goal_semantics.jsonl",
        system.entrypoints,
        adapters={"§14": adapter},
    )
    external_rows = PersistentPlatformRowSourceRegistry(
        system.rows.path,
        entrypoint_registry=system.entrypoints,
        rag_index=system.rag,
        source_resolver=system.typed,
    )
    target_row = REQUIRED_PLATFORM_ROWS[0]
    replacement_coverage, replacement_document = _atomic_row_inputs(
        owner,
        _manifest(owner, suffix="semantic-v2")[0],
        suffix="semantic-v2",
    )
    system.entrypoints.add(replacement_coverage)
    system.rag.add(owner, replacement_document)

    append_paused = threading.Event()
    release_append = threading.Event()
    mutation_started = threading.Event()
    mutation_finished = threading.Event()
    original_append = semantic._append_event
    recorded: list[GoalSectionSemanticProofRecord] = []
    failures: list[BaseException] = []

    def paused_append(row, *, precommit_assertion):
        append_paused.set()
        assert release_append.wait(5.0)
        return original_append(
            row,
            precommit_assertion=precommit_assertion,
        )

    monkeypatch.setattr(semantic, "_append_event", paused_append)

    def record_semantic() -> None:
        try:
            recorded.append(semantic.record_proof(proof))
        except BaseException as exc:  # noqa: BLE001 - thread evidence is asserted below.
            failures.append(exc)

    def mutate_source() -> None:
        mutation_started.set()
        try:
            external_rows.record_current(
                owner_user_id=owner,
                m_row=target_row,
                source_coverage_ref=replacement_coverage.coverage_ref,
                rag_ref=replacement_document.document_id,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence is asserted below.
            failures.append(exc)
        finally:
            mutation_finished.set()

    semantic_thread = threading.Thread(target=record_semantic, daemon=True)
    semantic_thread.start()
    assert append_paused.wait(5.0)
    mutation_thread = threading.Thread(target=mutate_source, daemon=True)
    mutation_thread.start()
    assert mutation_started.wait(1.0)
    assert not mutation_finished.wait(0.2)

    release_append.set()
    semantic_thread.join(5.0)
    mutation_thread.join(5.0)
    assert not semantic_thread.is_alive()
    assert not mutation_thread.is_alive()
    assert failures == []
    assert recorded == [proof]
    assert semantic.proof(proof.proof_ref, owner=owner) == proof
    assert not adapter.validate(proof, owner=owner).accepted


def test_platform_closure_same_thread_source_mutation_fails_before_append(
    tmp_path,
    monkeypatch,
):
    system = _atomic_section14_system(tmp_path)
    owner = system.owner
    external_rows = PersistentPlatformRowSourceRegistry(
        system.rows.path,
        entrypoint_registry=system.entrypoints,
        rag_index=system.rag,
        source_resolver=system.typed,
    )
    replacement_coverage, replacement_document = _atomic_row_inputs(
        owner,
        _manifest(owner, suffix="same-thread-v2")[0],
        suffix="same-thread-v2",
    )
    system.entrypoints.add(replacement_coverage)
    system.rag.add(owner, replacement_document)
    original_append = system.closure._atomic_append
    original_bytes = (
        system.closure.path.read_bytes() if system.closure.path.exists() else b""
    )

    def mutate_before_append(row, *, precommit_assertion=None):
        external_rows.record_current(
            owner_user_id=owner,
            m_row=REQUIRED_PLATFORM_ROWS[0],
            source_coverage_ref=replacement_coverage.coverage_ref,
            rag_ref=replacement_document.document_id,
        )
        if precommit_assertion is None:
            return original_append(row)
        return original_append(
            row,
            precommit_assertion=precommit_assertion,
        )

    monkeypatch.setattr(system.closure, "_atomic_append", mutate_before_append)
    with pytest.raises(PlatformClosureError, match="durable precommit"):
        system.closure.record_current(owner)
    assert (
        system.closure.path.read_bytes() if system.closure.path.exists() else b""
    ) == original_bytes


def test_section14_semantic_same_thread_source_mutation_fails_before_append(
    tmp_path,
    monkeypatch,
):
    system = _atomic_section14_system(tmp_path)
    owner = system.owner
    receipt = system.closure.record_current(owner)
    coverage_refs = tuple(
        binding.source_coverage_ref for binding in receipt.snapshot.source_bindings
    )
    validation_refs = tuple(
        ref
        for coverage_ref in coverage_refs
        for ref in system.entrypoints.coverage(
            coverage_ref,
            owner=owner,
        ).validation_refs
    )
    material = platform_closure_semantic_material(
        receipt,
        coverage_refs=coverage_refs,
        validation_refs=validation_refs,
    )
    proof = _semantic_proof(material, coverage_refs=coverage_refs, owner=owner)
    semantic = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "goal_semantics.jsonl",
        system.entrypoints,
        adapters={
            "§14": PlatformClosureSectionAdapter(
                system.entrypoints,
                system.closure,
                system.rows,
            )
        },
    )
    external_rows = PersistentPlatformRowSourceRegistry(
        system.rows.path,
        entrypoint_registry=system.entrypoints,
        rag_index=system.rag,
        source_resolver=system.typed,
    )
    replacement_coverage, replacement_document = _atomic_row_inputs(
        owner,
        _manifest(owner, suffix="semantic-same-thread-v2")[0],
        suffix="semantic-same-thread-v2",
    )
    system.entrypoints.add(replacement_coverage)
    system.rag.add(owner, replacement_document)
    original_append = semantic._append_event
    original_bytes = semantic.path.read_bytes() if semantic.path.exists() else b""

    def mutate_before_append(row, *, precommit_assertion=None):
        external_rows.record_current(
            owner_user_id=owner,
            m_row=REQUIRED_PLATFORM_ROWS[0],
            source_coverage_ref=replacement_coverage.coverage_ref,
            rag_ref=replacement_document.document_id,
        )
        if precommit_assertion is None:
            return original_append(row)
        return original_append(
            row,
            precommit_assertion=precommit_assertion,
        )

    monkeypatch.setattr(semantic, "_append_event", mutate_before_append)
    with pytest.raises(ValueError, match="append boundary"):
        semantic.record_proof(proof)
    assert (semantic.path.read_bytes() if semantic.path.exists() else b"") == original_bytes


def test_platform_closure_http_same_thread_source_mutation_is_not_200(
    tmp_path,
    monkeypatch,
):
    from fastapi.testclient import TestClient

    from app import main

    system = _atomic_section14_system(tmp_path)
    owner = system.owner
    external_rows = PersistentPlatformRowSourceRegistry(
        system.rows.path,
        entrypoint_registry=system.entrypoints,
        rag_index=system.rag,
        source_resolver=system.typed,
    )
    replacement_coverage, replacement_document = _atomic_row_inputs(
        owner,
        _manifest(owner, suffix="http-same-thread-v2")[0],
        suffix="http-same-thread-v2",
    )
    system.entrypoints.add(replacement_coverage)
    system.rag.add(owner, replacement_document)
    original_append = system.closure._atomic_append
    original_bytes = (
        system.closure.path.read_bytes() if system.closure.path.exists() else b""
    )

    def mutate_before_append(row, *, precommit_assertion=None):
        external_rows.record_current(
            owner_user_id=owner,
            m_row=REQUIRED_PLATFORM_ROWS[0],
            source_coverage_ref=replacement_coverage.coverage_ref,
            rag_ref=replacement_document.document_id,
        )
        if precommit_assertion is None:
            return original_append(row)
        return original_append(
            row,
            precommit_assertion=precommit_assertion,
        )

    monkeypatch.setattr(system.closure, "_atomic_append", mutate_before_append)
    monkeypatch.setattr(main, "PLATFORM_CLOSURE_REGISTRY", system.closure)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username=owner,
        user_id=owner,
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/goal/platform_closure/current"
        )
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert response.status_code == 422, response.text
    assert "durable precommit" in response.text
    assert (
        system.closure.path.read_bytes() if system.closure.path.exists() else b""
    ) == original_bytes
