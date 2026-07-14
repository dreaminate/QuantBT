from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.asset_rag import AssetRAGDocument, RAGPermission
from app.research_os.goal_coverage import GoalEntrypointCoverageRecord
from app.research_os.platform_coverage import PlatformCapabilityRecord
from app.research_os.platform_row_producers import (
    PlatformRowSourceState,
    ResolvedPlatformRow,
)
from app.research_os.platform_row_sources import PlatformRowSourceCertification
from app.research_os.platform_source_lineage_core import (
    PlatformSourceLineageCoreCommitError,
    PlatformSourceLineageFinalizationResult,
)


OWNER = "owner:platform-source-lineage-api"


@pytest.fixture(autouse=True)
def _clear_auth_override():
    yield
    main.app.dependency_overrides.pop(require_user_dependency, None)


def _client() -> TestClient:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=OWNER,
        username="platform-source-lineage-owner",
    )
    return TestClient(main.app)


class _CurrentRowRegistry:
    def __init__(self) -> None:
        self._current: dict[tuple[str, str], ResolvedPlatformRow] = {}
        self.resolve_calls: list[tuple[str, str]] = []

    def install(self, certification: PlatformRowSourceCertification) -> None:
        self._current[(certification.owner_user_id, certification.m_row)] = (
            certification.resolved_row
        )

    def resolve_current_row(
        self,
        m_row: str,
        *,
        owner_user_id: str,
    ) -> ResolvedPlatformRow:
        self.resolve_calls.append((owner_user_id, m_row))
        try:
            return self._current[(owner_user_id, m_row)]
        except KeyError:
            raise KeyError("platform row source is unavailable for owner") from None


def _success_result(
    *,
    owner_user_id: str,
    m_row: str,
    anchor_ref: str,
) -> PlatformSourceLineageFinalizationResult:
    row_token = m_row.lower().replace("-", "_")
    coverage_ref = f"goal_entrypoint_coverage:{row_token}:source"
    rag_ref = f"ragdoc_{row_token}_source"
    source_state = PlatformRowSourceState(
        source_kind="qro_ref",
        source_ref=f"qro:{row_token}",
        state_hash="sha256:" + "a" * 64,
    )
    record = PlatformCapabilityRecord(
        m_row=m_row,
        qro_ref=source_state.source_ref,
        research_graph_ref=f"rgcmd_{row_token}",
        lifecycle_ref=f"lifecycle:{row_token}",
        governance_ref=f"goal_validation_receipt:{row_token}",
        rag_ref=rag_ref,
        math_spine_ref=f"math_spine_chain:{row_token}",
        evidence_refs=(f"evidence:{row_token}",),
    )
    resolved_row = ResolvedPlatformRow(
        production_ref=f"platform_row_production:{row_token}",
        owner_user_id=owner_user_id,
        m_row=m_row,
        producer_ref=f"platform_source_lineage:{row_token}:v1",
        record=record,
        source_states=(source_state,),
    )
    certification = PlatformRowSourceCertification(
        certification_ref=f"platform_row_source_certification:{row_token}",
        owner_user_id=owner_user_id,
        m_row=m_row,
        row_revision=2,
        previous_certification_ref=(
            f"platform_row_source_certification:{row_token}:previous"
        ),
        source_coverage_ref=coverage_ref,
        rag_ref=rag_ref,
        resolved_row=resolved_row,
    )
    coverage = GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source="api",
        entrypoint_ref=f"api:test.platform_source_lineage.{row_token}",
        goal_sections=("§14",),
        qro_refs=(source_state.source_ref,),
        research_graph_command_refs=(record.research_graph_ref or "",),
        compiler_ir_refs=(f"compiler_ir:{row_token}",),
        compiler_pass_refs=(f"compiler_pass:{row_token}",),
        evidence_refs=record.evidence_refs,
        validation_refs=(record.governance_ref or "",),
        permission_refs=(f"permission:{row_token}",),
        replay_refs=(f"replay:{row_token}",),
        recorded_by=owner_user_id,
    )
    rag_document = AssetRAGDocument(
        source_id=f"platform_source_lineage:{m_row}",
        version="v1",
        title=f"Current source lineage for {m_row}",
        body=f"Server-derived lineage for {anchor_ref}.",
        projection="ResearchRAG",
        asset_ref=source_state.source_ref,
        permission=RAGPermission(allowed_users=(owner_user_id,)),
        applicability="current platform source-lineage proof",
        source_kind="server_derived_platform_source_lineage",
        evidence_label="proof_backed",
        document_id=rag_ref,
    )
    return PlatformSourceLineageFinalizationResult(
        business_coverage_ref=f"goal_entrypoint_coverage:{row_token}:business",
        coverage=coverage,
        rag_document=rag_document,
        certification=certification,
        preexisting_source_states=(
            PlatformRowSourceState(
                source_kind="anchor_ref",
                source_ref=anchor_ref,
                state_hash="sha256:" + "b" * 64,
            ),
        ),
    )


class _SuccessfulFinalizer:
    def __init__(self, registry: _CurrentRowRegistry) -> None:
        self._registry = registry
        self.calls: list[dict[str, str]] = []

    def record_current(self, **kwargs: str) -> PlatformSourceLineageFinalizationResult:
        self.calls.append(dict(kwargs))
        result = _success_result(**kwargs)
        self._registry.install(result.certification)
        return result


@pytest.mark.parametrize(
    ("m_row", "anchor_ref"),
    (
        ("M1-M2", "hypothesis_card:api-test"),
        ("M15", "desk_topology_receipt:api-test"),
        ("M21", "governed_asset:strategy_template:api-test"),
    ),
)
def test_platform_source_lineage_api_accepts_only_anchor_and_returns_current_summary(
    monkeypatch,
    m_row: str,
    anchor_ref: str,
) -> None:
    registry = _CurrentRowRegistry()
    finalizer = _SuccessfulFinalizer(registry)
    monkeypatch.setattr(main, "PLATFORM_ROW_SOURCE_REGISTRY", registry)
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_FINALIZER", finalizer)

    response = _client().post(
        f"/api/research-os/platform/source_lineage/{m_row}/current",
        json={"anchor_ref": anchor_ref},
    )

    assert response.status_code == 200, response.text
    assert finalizer.calls == [
        {
            "owner_user_id": OWNER,
            "m_row": m_row,
            "anchor_ref": anchor_ref,
        }
    ]
    assert registry.resolve_calls == [(OWNER, m_row)]
    body = response.json()
    assert body["m_row"] == m_row
    assert body["anchor_ref"] == anchor_ref
    assert body["certification_ref"].startswith(
        "platform_row_source_certification:"
    )
    assert body["row_revision"] == 2
    assert body["previous_certification_ref"].endswith(":previous")
    assert body["record"]["m_row"] == m_row
    assert body["source_states"][0]["source_kind"] == "qro_ref"
    assert body["preexisting_source_states"] == [
        {
            "source_kind": "anchor_ref",
            "source_ref": anchor_ref,
            "state_hash": "sha256:" + "b" * 64,
        }
    ]
    assert body["current"] is True
    assert body["current_error"] is None
    assert body["coverage_persisted"] is True
    assert body["rag_persisted"] is True
    assert body["row_source_persisted"] is True
    assert body["row_source_certified"] is True


def test_platform_source_lineage_api_rejects_caller_proof_fields_before_finalizer(
    monkeypatch,
) -> None:
    registry = _CurrentRowRegistry()
    finalizer = _SuccessfulFinalizer(registry)
    monkeypatch.setattr(main, "PLATFORM_ROW_SOURCE_REGISTRY", registry)
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_FINALIZER", finalizer)

    response = _client().post(
        "/api/research-os/platform/source_lineage/M15/current",
        json={
            "anchor_ref": "desk_topology_receipt:api-test",
            "qro_ref": "qro:caller-forged",
            "research_graph_ref": "rgcmd_caller_forged",
            "source_coverage_ref": "goal_entrypoint_coverage:caller-forged",
            "rag_ref": "ragdoc_caller_forged",
            "certification_ref": "platform_row_source_certification:caller-forged",
        },
    )

    assert response.status_code == 422, response.text
    assert "payload must contain exactly: anchor_ref" in response.text
    assert finalizer.calls == []
    assert registry.resolve_calls == []


@pytest.mark.parametrize("m_row", ("M22", "m15", "M1"))
def test_platform_source_lineage_api_rejects_noncanonical_rows_before_finalizer(
    monkeypatch,
    m_row: str,
) -> None:
    registry = _CurrentRowRegistry()
    finalizer = _SuccessfulFinalizer(registry)
    monkeypatch.setattr(main, "PLATFORM_ROW_SOURCE_REGISTRY", registry)
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_FINALIZER", finalizer)

    response = _client().post(
        f"/api/research-os/platform/source_lineage/{m_row}/current",
        json={"anchor_ref": "business_anchor:api-test"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "m_row is not a canonical platform row"
    assert finalizer.calls == []
    assert registry.resolve_calls == []


@pytest.mark.parametrize(
    (
        "coverage_persisted",
        "rag_persisted",
        "row_source_persisted",
    ),
    (
        (True, False, False),
        (True, True, True),
    ),
)
def test_platform_source_lineage_api_preserves_observed_commit_state_including_ack_loss(
    monkeypatch,
    coverage_persisted: bool,
    rag_persisted: bool,
    row_source_persisted: bool,
) -> None:
    class _FailingFinalizer:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def record_current(self, **kwargs: str):
            self.calls.append(dict(kwargs))
            raise PlatformSourceLineageCoreCommitError(
                "simulated post-write acknowledgement loss",
                coverage_persisted=coverage_persisted,
                rag_persisted=rag_persisted,
                row_source_persisted=row_source_persisted,
            )

    finalizer = _FailingFinalizer()
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_FINALIZER", finalizer)

    response = _client().post(
        "/api/research-os/platform/source_lineage/M21/current",
        json={"anchor_ref": "governed_asset:strategy_template:api-test"},
    )

    assert response.status_code == 409, response.text
    assert finalizer.calls == [
        {
            "owner_user_id": OWNER,
            "m_row": "M21",
            "anchor_ref": "governed_asset:strategy_template:api-test",
        }
    ]
    assert response.json()["detail"] == {
        "message": "platform source-lineage finalization is incomplete",
        "coverage_persisted": coverage_persisted,
        "rag_persisted": rag_persisted,
        "row_source_persisted": row_source_persisted,
        "row_source_certified": row_source_persisted,
    }
