from __future__ import annotations

import json

import pytest

from app.research_os.asset_rag import (
    AssetRAGDocument,
    AssetRAGError,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    RAGProjection,
    RAGQueryContext,
)


def _document(
    *,
    version: str = "v1",
    allowed_users: tuple[str, ...] = ("user-id-1",),
    permission_tags: tuple[str, ...] = ("research.read",),
    title: str = "Momentum evidence",
) -> AssetRAGDocument:
    return AssetRAGDocument(
        source_id="research:momentum",
        version=version,
        title=title,
        body="Momentum evidence remains candidate context for a research workflow.",
        projection=RAGProjection.RESEARCH,
        asset_ref="asset:momentum",
        permission=RAGPermission(
            allowed_users=allowed_users,
            allowed_desks=("research",),
            allowed_assets=("asset:momentum",),
            permission_tags=permission_tags,
        ),
        applicability="candidate research context only",
        source_kind="EvidenceSpan",
        metadata={"source_ref": "source:momentum"},
    )


def _context(
    *,
    user_id: str = "user-id-1",
    permission_tags: tuple[str, ...] = ("research.read",),
    actor: str = "agent",
) -> RAGQueryContext:
    return RAGQueryContext(
        user_id=user_id,
        desk="research",
        visible_asset_refs=("asset:momentum",),
        permission_tags=permission_tags,
        actor=actor,
    )


def _record_current_usage(
    index: PersistentResearchAssetRAGIndex,
    *,
    owner: str = "user-id-1",
):
    context = _context(user_id=owner)
    hits = index.retrieve_for_owner(
        "momentum evidence",
        owner_user_id=owner,
        context=context,
    )
    assert len(hits) == 1
    return index.record_usage_for_owner(
        owner_user_id=owner,
        agent_id="agent:research",
        workflow_ref="workflow:research-1",
        tool_call_ref="tool-call:rag-1",
        query="momentum evidence",
        context=context,
        hits=hits,
        purpose="research context assembly",
    )


def test_schema_v1_rows_are_compatibility_readable_but_quarantined_from_owner_proof(tmp_path):
    path = tmp_path / "research_asset_rag.jsonl"
    legacy = PersistentResearchAssetRAGIndex(path)
    legacy.add(_document())

    reloaded = PersistentResearchAssetRAGIndex(path)

    assert reloaded.legacy_quarantined_count == 2
    assert reloaded.retrieve("momentum evidence", context=_context())
    assert reloaded.owned_documents(owner_user_id="user-id-1") == []
    assert (
        reloaded.retrieve_for_owner(
            "momentum evidence",
            owner_user_id="user-id-1",
            context=_context(),
        )
        == []
    )


def test_owner_envelope_allows_same_document_id_for_two_owners_but_rejects_username_mixup(tmp_path):
    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    document = _document(allowed_users=("user-id-1", "user-id-2"))

    first = index.add_for_owner(document, owner_user_id="user-id-1")
    second = index.add_for_owner(document, owner_user_id="user-id-2")

    assert first.document_id == second.document_id
    assert (
        index.document_for_owner(document.document_id, owner_user_id="user-id-1")
        == document
    )
    assert (
        index.document_for_owner(document.document_id, owner_user_id="user-id-2")
        == document
    )
    with pytest.raises(AssetRAGError, match="stable owner_user_id"):
        index.retrieve_for_owner(
            "momentum",
            owner_user_id="user-id-1",
            context=_context(user_id="alice-display-name"),
        )
    with pytest.raises(KeyError):
        index.document_for_owner(document.document_id, owner_user_id="user-id-3")


def test_current_usage_exactly_binds_owner_workflow_query_context_documents_and_permissions(tmp_path):
    path = tmp_path / "research_asset_rag.jsonl"
    index = PersistentResearchAssetRAGIndex(path)
    document = index.add_for_owner(_document(), owner_user_id="user-id-1")
    usage = _record_current_usage(index)

    receipt = index.validate_current_usage(usage.usage_id, owner_user_id="user-id-1")

    assert receipt.accepted
    assert receipt.violations == ()
    assert receipt.owner_user_id == "user-id-1"
    assert receipt.workflow_ref == "workflow:research-1"
    assert receipt.tool_call_ref == "tool-call:rag-1"
    assert receipt.query_digest.startswith("ragquery_")
    assert receipt.context_digest.startswith("ragctx_")
    assert receipt.returned_document_ids == (document.document_id,)
    assert receipt.visible_asset_refs == ("asset:momentum",)
    assert receipt.candidate_context_only
    assert receipt.plaintext_secret_free

    reloaded = PersistentResearchAssetRAGIndex(path)
    assert reloaded.validate_current_usage(
        usage.usage_id,
        owner_user_id="user-id-1",
    ).accepted
    with pytest.raises(KeyError):
        reloaded.strict_usage_for_owner(usage.usage_id, owner_user_id="user-id-2")


def test_supersession_and_permission_change_invalidate_prior_usage(tmp_path):
    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    first = index.add_for_owner(_document(), owner_user_id="user-id-1")
    usage = _record_current_usage(index)
    second = _document(
        version="v2",
        permission_tags=("research.read", "restricted"),
        title="Momentum evidence v2",
    )

    other_process = PersistentResearchAssetRAGIndex(index.path)
    other_process.add_for_owner(
        second,
        owner_user_id="user-id-1",
        supersedes_document_id=first.document_id,
    )

    receipt = index.validate_current_usage(usage.usage_id, owner_user_id="user-id-1")
    assert not receipt.accepted
    assert f"rag_usage_document_not_current:{first.document_id}" in receipt.violations
    assert (
        index.retrieve_for_owner(
            "momentum evidence",
            owner_user_id="user-id-1",
            context=_context(),
        )
        == []
    )
    assert index.retrieve_for_owner(
        "momentum evidence",
        owner_user_id="user-id-1",
        context=_context(permission_tags=("research.read", "restricted")),
    )[0].document_id == second.document_id


def test_plaintext_secret_query_is_rejected(tmp_path):
    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    index.add_for_owner(_document(), owner_user_id="user-id-1")

    with pytest.raises(AssetRAGError, match="plaintext secret"):
        index.retrieve_for_owner(
            "api_key=sk-1234567890abcdef",
            owner_user_id="user-id-1",
            context=_context(),
        )


def test_disk_replay_is_idempotent_and_source_version_collision_fails_closed(tmp_path):
    path = tmp_path / "research_asset_rag.jsonl"
    first_process = PersistentResearchAssetRAGIndex(path)
    second_process = PersistentResearchAssetRAGIndex(path)
    document = _document()
    first_process.add_for_owner(document, owner_user_id="user-id-1")

    replayed = second_process.add_for_owner(
        _document(),
        owner_user_id="user-id-1",
    )

    assert replayed.document_id == document.document_id
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["schema_version"] == 2
    conflicting = _document(title="Changed content under the same source version")
    with pytest.raises(AssetRAGError, match="identity collision"):
        second_process.add_for_owner(
            conflicting,
            owner_user_id="user-id-1",
            supersedes_document_id=document.document_id,
        )
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_persisted_vector_tampering_is_rejected_with_exact_row_location(tmp_path):
    path = tmp_path / "research_asset_rag.jsonl"
    index = PersistentResearchAssetRAGIndex(path)
    index.add_for_owner(_document(), owner_user_id="user-id-1")
    row = json.loads(path.read_text(encoding="utf-8"))
    row["dense_vector"]["source_hash"] = "tampered"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(
        AssetRAGError,
        match=r"invalid persisted Research Asset RAG row at .*:1",
    ):
        PersistentResearchAssetRAGIndex(path)
