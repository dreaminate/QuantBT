from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.research_os.platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REQUIRED_REFS,
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_source_lineage_core import (
    PlatformSourceLineagePolicyResolution,
)
from app.research_os.platform_source_lineage_policy_router import (
    PlatformSourceLineagePolicyRouter,
)


def _resolution(row: str) -> PlatformSourceLineagePolicyResolution:
    return PlatformSourceLineagePolicyResolution(
        m_row=row,
        anchor_ref=f"anchor:{row}",
        qro_ref=f"qro:{row}",
        business_entry_source="api",
        business_entrypoint_ref=f"api:platform:{row}",
        lifecycle_ref=f"lifecycle:{row}",
        math_spine_ref=f"math:{row}",
        specific_refs=tuple(
            PlatformSpecificRef(key=key, ref=f"{key}:{row}")
            for key in SPECIFIC_REQUIRED_REFS[row]
        ),
        primary_rag_asset_ref=f"asset:{row}",
    )


class _Resolver:
    def __init__(self, row: str) -> None:
        self.row = row
        self.calls: list[tuple[str, str, str]] = []

    def resolve(self, *, owner_user_id: str, m_row: str, anchor_ref: str):
        self.calls.append((owner_user_id, m_row, anchor_ref))
        return replace(_resolution(self.row), anchor_ref=anchor_ref)

    def semantic_violations(self, resolution, **kwargs):
        self.calls.append(
            (
                kwargs["owner_user_id"],
                resolution.m_row,
                kwargs["capability_record"].qro_ref,
            )
        )
        return (f"semantic:{self.row}",)


def _router() -> tuple[PlatformSourceLineagePolicyRouter, dict[str, _Resolver]]:
    resolvers = {row: _Resolver(row) for row in REQUIRED_PLATFORM_ROWS}
    return PlatformSourceLineagePolicyRouter(resolvers), resolvers


def _capability(row: str) -> PlatformCapabilityRecord:
    resolution = _resolution(row)
    return PlatformCapabilityRecord(
        m_row=row,
        qro_ref=resolution.qro_ref,
        research_graph_ref=f"rgcmd:{row}",
        lifecycle_ref=resolution.lifecycle_ref,
        governance_ref=f"goal_validation_receipt:{row}",
        rag_ref=f"rag:{row}",
        math_spine_ref=resolution.math_spine_ref,
        evidence_refs=(f"evidence:{row}",),
        specific_refs=resolution.specific_refs,
    )


def test_router_requires_every_canonical_row_and_dispatches_exactly() -> None:
    router, resolvers = _router()

    assert router.registered_rows == REQUIRED_PLATFORM_ROWS
    result = router.resolve(
        owner_user_id="owner-a",
        m_row="M13",
        anchor_ref="anchor:current-m13",
    )
    assert result.m_row == "M13"
    assert result.anchor_ref == "anchor:current-m13"
    assert resolvers["M13"].calls == [
        ("owner-a", "M13", "anchor:current-m13")
    ]
    assert all(not value.calls for row, value in resolvers.items() if row != "M13")

    violations = router.semantic_violations(
        result,
        owner_user_id="owner-a",
        business_coverage=SimpleNamespace(coverage_ref="coverage:m13"),
        capability_record=_capability("M13"),
        rag_document=SimpleNamespace(document_id="rag:M13"),
    )
    assert violations == ("semantic:M13",)


def test_router_rejects_missing_invalid_and_cross_row_resolvers() -> None:
    with pytest.raises(ValueError, match="exact canonical row set"):
        PlatformSourceLineagePolicyRouter(
            {row: _Resolver(row) for row in REQUIRED_PLATFORM_ROWS[:-1]}
        )

    bad = {row: _Resolver(row) for row in REQUIRED_PLATFORM_ROWS}
    bad["M9"] = SimpleNamespace(resolve=lambda **_kwargs: None)
    with pytest.raises(TypeError, match="required methods"):
        PlatformSourceLineagePolicyRouter(bad)

    router, resolvers = _router()
    resolvers["M9"].row = "M10"
    with pytest.raises(ValueError, match="returned a different row"):
        router.resolve(
            owner_user_id="owner-a",
            m_row="M9",
            anchor_ref="anchor:m9",
        )

    with pytest.raises(ValueError, match="capability row mismatch"):
        router.semantic_violations(
            _resolution("M9"),
            owner_user_id="owner-a",
            business_coverage=SimpleNamespace(),
            capability_record=_capability("M10"),
            rag_document=SimpleNamespace(),
        )


@pytest.mark.parametrize("bad_row", ("", " M9", "M9 ", "M99", "m9"))
def test_router_rejects_noncanonical_row_text(bad_row: str) -> None:
    router, _resolvers = _router()
    with pytest.raises(ValueError, match="canonical exact"):
        router.resolve(
            owner_user_id="owner-a",
            m_row=bad_row,
            anchor_ref="anchor",
        )
