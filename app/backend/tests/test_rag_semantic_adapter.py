from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.research_os.asset_rag import (
    AssetRAGDocument,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    RAGProjection,
    RAGQueryContext,
)
from app.research_os.goal_coverage import GoalCoverageDecision
from app.research_os.goal_semantic_adapters import RAGConformanceSectionAdapter
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    goal_section_semantic_proof_identity,
)


OWNER = "user:rag-semantic"
COVERAGE_REF = "goal_entrypoint_coverage:rag-semantic"


def _document(*, version: str = "v1", title: str = "Momentum evidence") -> AssetRAGDocument:
    return AssetRAGDocument(
        source_id="research:momentum",
        version=version,
        title=title,
        body="Momentum evidence remains candidate context for this research workflow.",
        projection=RAGProjection.RESEARCH,
        asset_ref="asset:momentum",
        permission=RAGPermission(
            allowed_users=(OWNER,),
            allowed_desks=("research",),
            allowed_assets=("asset:momentum",),
            permission_tags=("research.read",),
        ),
        applicability="candidate research context only",
        source_kind="EvidenceSpan",
    )


class _Entrypoints:
    def __init__(self, usage_id: str) -> None:
        self.record = SimpleNamespace(
            coverage_ref=COVERAGE_REF,
            entry_source="agent_shell",
            entrypoint_ref="agent_shell:api.agent.chat",
            goal_sections=("§0", "§1", "§5", "§7", "§8"),
            evidence_refs=(f"rag_usage:{usage_id}", "evidence:agent-turn"),
        )

    def coverage(self, ref: str, *, owner: str):
        if ref != COVERAGE_REF or owner != OWNER:
            raise KeyError(ref)
        return self.record

    def validate_real_backing(self, record):
        assert record is self.record
        return GoalCoverageDecision(True, ())


def _usage(index: PersistentResearchAssetRAGIndex):
    context = RAGQueryContext(
        user_id=OWNER,
        desk="research",
        visible_asset_refs=("asset:momentum",),
        permission_tags=("research.read",),
        actor="agent",
    )
    hits = index.retrieve_for_owner(
        "momentum evidence",
        owner_user_id=OWNER,
        context=context,
    )
    return index.record_usage_for_owner(
        owner_user_id=OWNER,
        agent_id="agent:research",
        workflow_ref="agentwf_current",
        tool_call_ref="agentwf_current:rag_context",
        query="momentum evidence",
        context=context,
        hits=hits,
        purpose="agent shell research context",
    )


def _proof(index: PersistentResearchAssetRAGIndex, usage) -> GoalSectionSemanticProofRecord:
    receipt = index.validate_current_usage(usage.usage_id, owner_user_id=OWNER)
    conformance_ref = (
        f"rag_conformance:{usage.usage_id}:{receipt.query_digest}:{receipt.context_digest}"
    )
    document_refs = tuple(
        f"rag_document:{item.document_id}:{item.source_id}@{item.version}"
        for item in usage.returned_documents
    )
    data = {
        "section": "§5",
        "subject_ref": f"goal_section:§5:rag_usage:{usage.usage_id}",
        "producer_refs": document_refs,
        "store_refs": (
            usage.usage_id,
            *(item.document_id for item in usage.returned_documents),
        ),
        "consumer_refs": (usage.workflow_ref, usage.tool_call_ref),
        "gate_verdict_refs": (conformance_ref,),
        "test_refs": (
            conformance_ref,
            *(f"rag_current_document:{item.document_id}" for item in usage.returned_documents),
        ),
        "entrypoint_coverage_refs": (COVERAGE_REF,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return GoalSectionSemanticProofRecord(**data)


def test_current_agent_workflow_rag_usage_exactly_proves_section_five(tmp_path) -> None:
    index = PersistentResearchAssetRAGIndex(tmp_path / "rag.jsonl")
    index.add_for_owner(_document(), owner_user_id=OWNER)
    usage = _usage(index)
    adapter = RAGConformanceSectionAdapter(_Entrypoints(usage.usage_id), index)

    decision = adapter.validate(_proof(index, usage), owner=OWNER)

    assert decision.accepted, decision.violations


def test_document_drift_recombination_and_cross_owner_fail_closed(tmp_path) -> None:
    index = PersistentResearchAssetRAGIndex(tmp_path / "rag.jsonl")
    first = index.add_for_owner(_document(), owner_user_id=OWNER)
    usage = _usage(index)
    proof = _proof(index, usage)
    adapter = RAGConformanceSectionAdapter(_Entrypoints(usage.usage_id), index)
    index.add_for_owner(
        _document(version="v2", title="Momentum evidence v2"),
        owner_user_id=OWNER,
        supersedes_document_id=first.document_id,
    )

    drift = adapter.validate(proof, owner=OWNER)
    recombined = adapter.validate(
        replace(proof, producer_refs=(*proof.producer_refs, "rag_document:unrelated:v9")),
        owner=OWNER,
    )
    foreign = adapter.validate(proof, owner="user:foreign")

    assert not drift.accepted
    assert any("stale" in item.message for item in drift.violations)
    assert not recombined.accepted
    assert any(item.field == "producer_refs" for item in recombined.violations)
    assert not foreign.accepted
    assert any("absent for owner" in item.message for item in foreign.violations)
