from __future__ import annotations

import pytest

from app.research_os import (
    AssetRAGDocument,
    AssetRAGError,
    RAGPermission,
    RAGProjection,
    RAGQueryContext,
    ResearchAssetRAGIndex,
)


def _doc(**overrides) -> AssetRAGDocument:
    data = {
        "source_id": "asset:btc-momentum",
        "version": "v1",
        "title": "BTC momentum strategy evidence",
        "body": "BTCUSDT daily momentum backtest uses dataset_version dsver:btc-2023 and TheoryImplementationBinding tbind_mom.",
        "projection": RAGProjection.STRATEGY,
        "asset_ref": "qro:btc-momentum",
        "permission": RAGPermission(allowed_users=("u1",), allowed_desks=("strategy",), allowed_assets=("qro:btc-momentum",)),
        "applicability": "crypto daily research and paper only",
        "source_kind": "ValidationDossier",
        "metadata": {"dataset_version": "dsver:btc-2023"},
        "evidence_label": "candidate_context",
    }
    data.update(overrides)
    return AssetRAGDocument(**data)


def _ctx(**overrides) -> RAGQueryContext:
    data = {
        "user_id": "u1",
        "desk": "strategy",
        "visible_asset_refs": ("qro:btc-momentum",),
        "permission_tags": (),
    }
    data.update(overrides)
    return RAGQueryContext(**data)


def test_retrieval_returns_source_version_permission_and_applicability():
    index = ResearchAssetRAGIndex()
    index.add(_doc())
    hits = index.retrieve("BTC momentum dataset_version", context=_ctx(), projections=(RAGProjection.STRATEGY,))
    assert len(hits) == 1
    hit = hits[0]
    assert hit.source_id == "asset:btc-momentum"
    assert hit.version == "v1"
    assert hit.timestamp
    assert hit.permission["allowed_desks"] == ("strategy",)
    assert hit.applicability == "crypto daily research and paper only"
    assert hit.context_role == "candidate_context"


def test_retrieval_respects_user_desk_asset_and_permission_tag_scope():
    index = ResearchAssetRAGIndex()
    index.add(_doc(permission=RAGPermission(
        allowed_users=("u1",),
        allowed_desks=("strategy",),
        allowed_assets=("qro:btc-momentum",),
        permission_tags=("research.read",),
    )))
    assert index.retrieve("BTC", context=_ctx(permission_tags=("research.read",)))
    assert not index.retrieve("BTC", context=_ctx(user_id="u2", permission_tags=("research.read",)))
    assert not index.retrieve("BTC", context=_ctx(desk="model", permission_tags=("research.read",)))
    assert not index.retrieve("BTC", context=_ctx(visible_asset_refs=("qro:other",), permission_tags=("research.read",)))
    assert not index.retrieve("BTC", context=_ctx(permission_tags=()))


def test_secret_ref_metadata_is_allowed_but_plaintext_secret_is_rejected():
    AssetRAGDocument(
        source_id="secretref:binance",
        version="v1",
        title="Binance SecretRef status",
        body="SecretRef exists, scope=read_market_data, last_test=ok.",
        projection=RAGProjection.DATA,
        asset_ref="qro:btc-momentum",
        permission=RAGPermission(allowed_users=("u1",), allowed_desks=("data",), allowed_assets=("qro:btc-momentum",)),
        applicability="connection metadata only",
        source_kind="SecretRefStatus",
        metadata={"secret_ref": "sec_binance", "scope": "read_market_data", "last_test": "ok"},
    )
    with pytest.raises(AssetRAGError):
        _doc(metadata={"api_key_plaintext": "sk-live-1234567890abcdef"})
    with pytest.raises(AssetRAGError):
        _doc(body="api_key=sk-live-1234567890abcdef")


def test_user_waived_methodology_cannot_be_indexed_as_strong_evidence():
    with pytest.raises(AssetRAGError):
        _doc(methodology_path="user_waived_theory", evidence_label="evidence_sufficient")
    doc = _doc(methodology_path="user_waived_theory", evidence_label="user_waived")
    assert doc.evidence_label == "user_waived"


def test_agent_usage_records_hit_source_version_for_user_inspection():
    index = ResearchAssetRAGIndex()
    index.add(_doc())
    hit = index.retrieve("TheoryImplementationBinding", context=_ctx())[0]
    usage = index.record_agent_usage(agent_id="agent:verifier", hit=hit, purpose="consistency review")
    assert usage.source_id == hit.source_id
    assert usage.version == hit.version
    assert index.agent_usage(source_id=hit.source_id) == [usage]


def test_projection_filter_keeps_bottom_layer_unified_but_desk_specific():
    index = ResearchAssetRAGIndex()
    index.add(_doc(projection=RAGProjection.MATH, title="Momentum formula", body="TheoryImplementationBinding for momentum math"))
    index.add(_doc(
        source_id="run:bt1",
        version="v1",
        projection=RAGProjection.RUN,
        title="Backtest run",
        body="Backtest run metrics and verifier verdict",
    ))
    math_hits = index.retrieve("momentum", context=_ctx(), projections=(RAGProjection.MATH,))
    assert [h.projection for h in math_hits] == ["MathRAG"]
    run_hits = index.retrieve("Backtest", context=_ctx(), projections=(RAGProjection.RUN,))
    assert [h.projection for h in run_hits] == ["RunRAG"]
