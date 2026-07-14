from __future__ import annotations

from dataclasses import replace

import pytest

from app.research_os.platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REF_PREFIXES,
    SPECIFIC_REQUIRED_REFS,
    PersistentPlatformCoverageRegistry,
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_row_producers import (
    PlatformRowProducerRegistry,
    PlatformRowProductionError,
    ProducerBoundPlatformRefResolver,
    platform_row_source_state,
    resolved_platform_row,
)


OWNER = "owner-platform"


def _slug(row: str) -> str:
    return row.replace("-", "_")


def _record(row: str, *, suffix: str = "v1") -> PlatformCapabilityRecord:
    slug = _slug(row)
    return PlatformCapabilityRecord(
        m_row=row,
        qro_ref=f"qro:{OWNER}:{slug}:{suffix}",
        research_graph_ref=f"rgcmd:{OWNER}:{slug}:{suffix}",
        lifecycle_ref=f"lifecycle:{OWNER}:{slug}:{suffix}",
        governance_ref=f"governance:{OWNER}:{slug}:{suffix}",
        rag_ref=f"rag:{OWNER}:{slug}:{suffix}",
        math_spine_ref=f"math:{OWNER}:{slug}:{suffix}",
        evidence_refs=(f"audit:{OWNER}:{slug}:{suffix}",),
        specific_refs=tuple(
            PlatformSpecificRef(
                key=key,
                ref=f"{SPECIFIC_REF_PREFIXES[key][0]}{OWNER}:{slug}:{suffix}",
            )
            for key in SPECIFIC_REQUIRED_REFS[row]
        ),
    )


def _refs(record: PlatformCapabilityRecord) -> tuple[str, ...]:
    return (
        str(record.qro_ref),
        str(record.research_graph_ref),
        str(record.lifecycle_ref),
        str(record.governance_ref),
        str(record.rag_ref),
        str(record.math_spine_ref),
        *record.evidence_refs,
        *(item.ref for item in record.specific_refs),
    )


def _producer(row: str, *, suffix: str = "v1"):
    def produce(owner: str):
        assert owner == OWNER
        record = _record(row, suffix=suffix)
        return resolved_platform_row(
            owner_user_id=owner,
            m_row=row,
            producer_ref=f"platform_row_producer:{row}:v1",
            record=record,
            source_states=tuple(
                platform_row_source_state(
                    source_kind=f"typed_source:{index}",
                    source_ref=ref,
                    state_payload={"owner": owner, "row": row, "ref": ref},
                )
                for index, ref in enumerate(_refs(record))
            ),
        )

    return produce


def _registry() -> PlatformRowProducerRegistry:
    return PlatformRowProducerRegistry(
        {row: _producer(row) for row in REQUIRED_PLATFORM_ROWS}
    )


class _BaseResolver:
    def for_owner(self, owner: str):
        if owner != OWNER:
            raise ValueError("owner mismatch")
        return self

    @staticmethod
    def _owned(ref: str) -> bool:
        return OWNER in str(ref)

    has_qro = _owned
    has_research_graph_command = _owned
    has_lifecycle_record = _owned
    has_governance_record = _owned
    has_rag_asset = _owned
    has_math_spine_chain = _owned
    has_evidence = _owned

    def has_math_spine_member(self, chain_ref: str, _member_type: str, ref: str) -> bool:
        return self._owned(chain_ref) and self._owned(ref)

    @staticmethod
    def platform_linkage_violations(_record):
        return ()


def test_server_derived_manifest_resolves_all_rows_twice_in_canonical_order():
    registry = _registry()

    records = registry.resolve_current_manifest(OWNER)

    assert tuple(str(record.m_row) for record in records) == REQUIRED_PLATFORM_ROWS
    assert registry.registered_rows == REQUIRED_PLATFORM_ROWS


def test_server_derived_manifest_rejects_missing_unstable_and_unbound_sources():
    missing = PlatformRowProducerRegistry(
        {row: _producer(row) for row in REQUIRED_PLATFORM_ROWS[:-1]}
    )
    with pytest.raises(PlatformRowProductionError, match="missing row producers"):
        missing.resolve_current_manifest(OWNER)

    calls = 0

    def unstable(owner: str):
        nonlocal calls
        calls += 1
        return _producer("M1-M2", suffix=f"v{calls}")(owner)

    unstable_registry = PlatformRowProducerRegistry({"M1-M2": unstable})
    with pytest.raises(PlatformRowProductionError, match="changed during resolution"):
        unstable_registry.resolve_row("M1-M2", owner_user_id=OWNER)

    record = _record("M1-M2")
    unbound = resolved_platform_row(
        owner_user_id=OWNER,
        m_row="M1-M2",
        producer_ref="platform_row_producer:M1-M2:v1",
        record=record,
        source_states=(
            platform_row_source_state(
                source_kind="typed_source:qro",
                source_ref=str(record.qro_ref),
                state_payload={"qro": record.qro_ref},
            ),
        ),
    )
    unbound_registry = PlatformRowProducerRegistry({"M1-M2": lambda _owner: unbound})
    with pytest.raises(PlatformRowProductionError, match="not_content_bound"):
        unbound_registry.resolve_row("M1-M2", owner_user_id=OWNER)


def test_producer_bound_resolver_rejects_same_owner_recombination_and_records_once(tmp_path):
    producers = _registry()
    resolver = ProducerBoundPlatformRefResolver(_BaseResolver(), producers)
    store = PersistentPlatformCoverageRegistry(
        tmp_path / "platform_manifest.jsonl",
        resolver=resolver,
    )

    recorded = producers.record_current_manifest(store, owner_user_id=OWNER)
    assert tuple(str(item.m_row) for item in recorded) == REQUIRED_PLATFORM_ROWS
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == 1

    bound = resolver.for_owner(OWNER)
    current = recorded[0]
    assert bound.has_platform_common_ref("qro_ref", str(current.qro_ref), current)
    recombined = replace(current, lifecycle_ref=recorded[1].lifecycle_ref)
    assert not bound.has_platform_common_ref(
        "qro_ref",
        str(recombined.qro_ref),
        recombined,
    )
    assert bound.platform_linkage_violations(recombined)


def test_producer_bound_common_refs_use_current_typed_source_states_not_legacy_base():
    class LegacyBaseCannotResolveTypedCommonRefs(_BaseResolver):
        @staticmethod
        def _owned(_ref: str) -> bool:
            return False

    producers = _registry()
    bound = ProducerBoundPlatformRefResolver(
        LegacyBaseCannotResolveTypedCommonRefs(),
        producers,
    ).for_owner(OWNER)
    current = producers.resolve_row("M12", owner_user_id=OWNER).record

    for field_name in (
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "rag_ref",
        "math_spine_ref",
    ):
        assert bound.has_platform_common_ref(
            field_name,
            str(getattr(current, field_name)),
            current,
        )

    assert not bound.has_platform_common_ref(
        "lifecycle_ref",
        "lifecycle:owner-platform:M12:unrelated",
        current,
    )
