from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.research_os.goal_coverage import GoalEntrypointCoverageRecord
from app.research_os.platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REF_PREFIXES,
    SPECIFIC_REQUIRED_REFS,
)
from app.research_os.platform_row_producers import (
    PlatformRowProducerRegistry,
    PlatformRowProductionError,
    platform_row_source_state,
)
from app.research_os.platform_row_sources import (
    PersistentPlatformRowSourceRegistry,
    PlatformRowSourceError,
    register_platform_row_source_producers,
)


OWNER = "owner-platform-source"
ROW = "M1-M2"
COVERAGE_REF = "goal_entrypoint_coverage:platform-source-m1-m2"
RAG_REF = "ragdoc_platform_source_m1_m2"


def _specifics() -> dict[str, str]:
    return {
        key: f"{SPECIFIC_REF_PREFIXES[key][0]}{OWNER}:{key}"
        for key in SPECIFIC_REQUIRED_REFS[ROW]
    }


def _coverage() -> GoalEntrypointCoverageRecord:
    return GoalEntrypointCoverageRecord(
        coverage_ref=COVERAGE_REF,
        entry_source="api",
        entrypoint_ref="api:platform-source:m1-m2",
        goal_sections=("§14",),
        qro_refs=(f"qro:{OWNER}:m1-m2",),
        research_graph_command_refs=(f"rgcmd:{OWNER}:m1-m2",),
        compiler_ir_refs=(f"compiler_ir:{OWNER}:m1-m2",),
        compiler_pass_refs=(f"compiler_pass:{OWNER}:m1-m2",),
        evidence_refs=(f"evidence:{OWNER}:m1-m2",),
        validation_refs=(f"goal_validation_receipt:{OWNER}:m1-m2",),
        permission_refs=(f"permission:{OWNER}:m1-m2",),
        replay_refs=(f"replay:{OWNER}:m1-m2",),
        lifecycle_refs=(f"lifecycle:{OWNER}:m1-m2",),
        recorded_by=OWNER,
    )


def _rag_document(coverage: GoalEntrypointCoverageRecord):
    return SimpleNamespace(
        document_id=RAG_REF,
        source_id=f"platform_source_lineage:{ROW}",
        source_kind="server_derived_platform_source_lineage",
        version="platform_source_lineage.v1." + "a" * 64,
        projection="research",
        evidence_label="candidate_context",
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            permission_tags=("platform_source_lineage",),
        ),
        metadata={
            "platform_capability": {
                "schema_version": 1,
                "m_row": ROW,
                "source_coverage_ref": COVERAGE_REF,
                "qro_ref": coverage.qro_refs[0],
                "research_graph_ref": coverage.research_graph_command_refs[0],
                "lifecycle_ref": coverage.lifecycle_refs[0],
                "governance_ref": coverage.validation_refs[0],
                "math_spine_ref": f"math_spine_chain:{OWNER}:m1-m2",
                "evidence_refs": list(coverage.evidence_refs),
                "specific_refs": _specifics(),
            }
        },
    )


class _Entrypoints:
    def __init__(self, coverage: GoalEntrypointCoverageRecord) -> None:
        self.coverage_record = coverage
        self.accepted = True

    def coverage(self, coverage_ref: str, *, owner: str):
        assert coverage_ref == COVERAGE_REF
        assert owner == OWNER
        return self.coverage_record

    def validate_real_backing(self, coverage):
        assert coverage is self.coverage_record
        return SimpleNamespace(accepted=self.accepted)


class _RAG:
    def __init__(self, document) -> None:
        self.document = document

    def document_for_owner(
        self,
        document_id: str,
        *,
        owner_user_id: str,
        require_current: bool,
    ):
        assert document_id == RAG_REF
        assert owner_user_id == OWNER
        assert require_current is True
        return self.document


class _TypedSources:
    def __init__(self) -> None:
        self.revision = "v1"
        self.linkage_errors: tuple[str, ...] = ()

    def resolve_state(self, field, ref, *, owner_user_id, record):
        assert owner_user_id == OWNER
        assert ref in {
            str(record.qro_ref),
            str(record.research_graph_ref),
            str(record.lifecycle_ref),
            str(record.governance_ref),
            str(record.rag_ref),
            str(record.math_spine_ref),
            *record.evidence_refs,
            *(item.ref for item in record.specific_refs),
        }
        return platform_row_source_state(
            source_kind=f"typed:{field}",
            source_ref=ref,
            state_payload={
                "owner_user_id": owner_user_id,
                "field": field,
                "ref": ref,
                "revision": self.revision,
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
        assert owner_user_id == OWNER
        assert source_coverage.coverage_ref == COVERAGE_REF
        assert rag_document.document_id == record.rag_ref
        return self.linkage_errors


def _registry(tmp_path):
    coverage = _coverage()
    entrypoints = _Entrypoints(coverage)
    rag = _RAG(_rag_document(coverage))
    sources = _TypedSources()
    registry = PersistentPlatformRowSourceRegistry(
        tmp_path / "platform_row_sources.jsonl",
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=sources,
    )
    return registry, entrypoints, rag, sources


def _record(registry: PersistentPlatformRowSourceRegistry):
    return registry.record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        source_coverage_ref=COVERAGE_REF,
        rag_ref=RAG_REF,
    )


def test_platform_row_source_certifies_reloads_and_revalidates_current_state(tmp_path):
    registry, entrypoints, rag, sources = _registry(tmp_path)

    first = _record(registry)
    assert _record(registry) == first
    assert first.row_revision == 1
    assert first.resolved_row.production_ref.startswith("platform_row_production:")
    assert registry.resolve_current_row(ROW, owner_user_id=OWNER) == first.resolved_row
    assert registry.source_coverage_ref(ROW, owner_user_id=OWNER) == COVERAGE_REF
    assert registry.current_certifications(owner_user_id=OWNER) == (first,)

    reloaded = PersistentPlatformRowSourceRegistry(
        registry.path,
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=sources,
    )
    assert reloaded.certification(
        first.certification_ref,
        owner_user_id=OWNER,
    ) == first
    assert reloaded.resolve_current_row(ROW, owner_user_id=OWNER) == first.resolved_row

    sources.revision = "v2"
    with pytest.raises(PlatformRowSourceError, match="drifted"):
        reloaded.resolve_current_row(ROW, owner_user_id=OWNER)


def test_platform_row_source_rejects_unbacked_recombined_and_inexact_metadata(tmp_path):
    registry, entrypoints, rag, sources = _registry(tmp_path)

    entrypoints.accepted = False
    with pytest.raises(PlatformRowSourceError, match="not strictly backed"):
        _record(registry)
    entrypoints.accepted = True

    sources.linkage_errors = ("qro and domain source are recombined",)
    with pytest.raises(PlatformRowSourceError, match="recombined"):
        _record(registry)
    sources.linkage_errors = ()

    del rag.document.metadata["platform_capability"]["specific_refs"][
        "regime_scenario_ref"
    ]
    with pytest.raises(PlatformRowSourceError, match="specific refs are inexact"):
        _record(registry)


def test_platform_row_source_rejects_caller_shaped_rag_without_reserved_provenance(
    tmp_path,
):
    registry, _entrypoints, rag, _sources = _registry(tmp_path)
    rag.document.source_kind = "user_supplied_document"

    with pytest.raises(PlatformRowSourceError, match="server-derived provenance"):
        _record(registry)

    assert not registry.path.exists()


def test_platform_row_source_rolls_back_first_file_on_directory_fsync_failure(
    tmp_path,
    monkeypatch,
):
    registry, _entrypoints, _rag, _sources = _registry(tmp_path)
    calls = 0
    original = registry._fsync_parent

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("directory fsync failed")
        return original()

    monkeypatch.setattr(registry, "_fsync_parent", fail_once)
    with pytest.raises(OSError, match="directory fsync failed"):
        _record(registry)
    assert not registry.path.exists()
    assert registry.current_certifications(owner_user_id=OWNER) == ()


def test_platform_row_source_rejects_persisted_hash_tampering(tmp_path):
    registry, entrypoints, rag, sources = _registry(tmp_path)
    _record(registry)
    [row] = [
        json.loads(line)
        for line in registry.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    row["record_hash"] = "sha256:" + "0" * 64
    registry.path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted platform row source"):
        PersistentPlatformRowSourceRegistry(
            registry.path,
            entrypoint_registry=entrypoints,
            rag_index=rag,
            source_resolver=sources,
        )


def test_platform_row_source_registers_all_rows_but_missing_sources_stay_red(tmp_path):
    registry, _entrypoints, _rag, _sources = _registry(tmp_path)
    producers = PlatformRowProducerRegistry()

    register_platform_row_source_producers(producers, registry)

    assert producers.registered_rows == REQUIRED_PLATFORM_ROWS
    with pytest.raises(PlatformRowProductionError, match="unavailable for M3"):
        producers.resolve_row("M3", owner_user_id=OWNER)
