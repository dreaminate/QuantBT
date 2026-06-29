"""Research Asset RAG autosync producer helpers (GOAL §5 · C-S5-RAG-AUTOSYNC).

These tests pin the contract of the registry->RAG document builders in
``app.research_os.asset_rag``:
- a factor / model / signal / strategy registry object produces the correct
  AssetRAGDocument projection with source_id + version + owner-scoped permission;
- retrieval isolation can never silently widen (越权不返);
- raw model artifacts / raw strategy source code are never copied into the body;
- plaintext credentials are rejected through the helper path.

The factor and signal cases use the REAL registry classes so field drift is
caught. The model passport and strategy draft use duck-typed stand-ins that
mirror the real field names — this keeps the suite inside the asset_rag lib
domain (PARALLEL-SAFE; it does not import the ide/ or model_governance/ heavy
paths). Mirrored classes:
    ModelGovernancePassport @ app/research_os/model_governance.py:166
    StrategyFile            @ app/ide/service.py:31
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.factor_factory.registry import Factor
from app.factor_factory.signal_contract import LeakageDeclaration, SignalContract
from app.research_os import (
    AssetRAGError,
    RAGPermission,
    RAGProjection,
    RAGQueryContext,
    ResearchAssetRAGIndex,
    build_factor_rag_document,
    build_model_rag_document,
    build_signal_rag_document,
    build_strategy_rag_document,
)


@dataclass
class _FakePassport:
    """Duck-typed stand-in for ModelGovernancePassport (read fields only)."""

    model_version_ref: str = "model:gbdt_xs:v3"
    passport_id: str = "model_passport_abc123"
    model_risk_tier: str = "tier_2"
    materiality: str = "medium"
    intended_use: tuple = ("xs ranking on liquid universe",)
    prohibited_use: tuple = ("no leverage sizing",)
    dataset_refs: tuple = ("dsver:train-2023",)
    feature_refs: tuple = ("feat:mom_20",)
    label_refs: tuple = ("label:fwd_ret_5",)
    training_code_hash: str = "hash:traincode"
    validation_dossier_ref: str = "dossier:val1"
    target_runtime: str = "OFFLINE"


@dataclass
class _FakeStrategy:
    """Duck-typed stand-in for StrategyFile (read fields only)."""

    strategy_id: str = "strat_btc_mom"
    owner_username: str = "u1"
    name: str = "BTC momentum book"
    code: str = "def alpha():\n    return SECRET_PROPRIETARY_FORMULA"
    asset_class: str = "crypto_perp"
    description: str = "Daily BTC momentum with embargoed signal blending."
    updated_at_utc: str = "2026-06-29T00:00:00+00:00"
    market_data_use_validation_refs: list = field(default_factory=lambda: ["mdu:val1"])


def _factor(**overrides) -> Factor:
    data = {
        "factor_id": "mom_20",
        "formula": "close / delay(close, 20) - 1",
        "version": 2,
        "author": "u1",
        "description": "20-day momentum factor",
        "lifecycle_state": "QUALIFIED",
        "params": {"window": 20},
    }
    data.update(overrides)
    return Factor(**data)


def _signal(**overrides) -> SignalContract:
    data = {
        "signal_id": "sigid_abc",
        "name": "gbdt xs rank",
        "source_lib": "ml",
        "model_ref": "gbdt_xs_rank_v3.pkl",
        "output_kind": "xs_score",
        "horizon": 5,
        "leakage": LeakageDeclaration(oof=True, purge=True, embargo=True, embargo_days=2),
        "author": "u1",
        "description": "cross-sectional rank signal",
    }
    data.update(overrides)
    return SignalContract(**data)


def _ctx(asset_ref: str, *, user_id: str = "u1", desk: str = "factor", **overrides) -> RAGQueryContext:
    data = {
        "user_id": user_id,
        "desk": desk,
        "visible_asset_refs": (asset_ref,),
        "permission_tags": (),
    }
    data.update(overrides)
    return RAGQueryContext(**data)


# --------------------------------------------------------------------------
# Per-asset projection + source/version + retrievability
# --------------------------------------------------------------------------


def test_factor_helper_builds_factor_projection_source_version_and_retrieves():
    doc = build_factor_rag_document(_factor())  # owner defaults to factor.author
    assert doc.projection_value == "FactorRAG"
    assert doc.source_id == "factor:mom_20:v2"
    assert doc.version == "2"
    assert doc.asset_ref == "factor:mom_20"
    assert doc.permission.allowed_users == ("u1",)
    assert doc.evidence_label == "candidate_context"
    assert "verdict" in doc.applicability  # candidate context, never a system verdict

    index = ResearchAssetRAGIndex()
    index.add(doc)
    hits = index.retrieve(
        "momentum Formula",
        context=_ctx("factor:mom_20", desk="factor"),
        projections=(RAGProjection.FACTOR,),
    )
    assert len(hits) == 1
    assert hits[0].source_id == "factor:mom_20:v2"
    assert hits[0].version == "2"
    assert hits[0].projection == "FactorRAG"


def test_signal_helper_builds_signal_projection_and_references_model_body_only():
    doc = build_signal_rag_document(_signal())  # owner defaults to contract.author
    assert doc.projection_value == "SignalRAG"
    assert doc.source_id == "sig::sigid_abc"
    # content-addressed signal: version falls back to the signal_id identity
    assert doc.version == "sigid_abc"
    assert doc.asset_ref == "sig::sigid_abc"
    assert doc.permission.allowed_users == ("u1",)
    # the model body is referenced only (model_ref), never indexed as content
    assert doc.metadata["model_ref"] == "gbdt_xs_rank_v3.pkl"
    assert doc.metadata["leakage_declared"] is True

    index = ResearchAssetRAGIndex()
    index.add(doc)
    hits = index.retrieve(
        "rank signal",
        context=_ctx("sig::sigid_abc", desk="signal"),
        projections=(RAGProjection.SIGNAL,),
    )
    assert len(hits) == 1
    assert hits[0].projection == "SignalRAG"
    assert hits[0].version == "sigid_abc"


def test_model_helper_builds_model_projection_and_requires_owner():
    passport = _FakePassport()
    # passport carries no owner field: owner must be supplied -> empty is rejected
    with pytest.raises(AssetRAGError):
        build_model_rag_document(passport)

    doc = build_model_rag_document(passport, owner="u1")
    assert doc.projection_value == "ModelRAG"
    assert doc.source_id == "model:gbdt_xs:v3"
    assert doc.version == "model_passport_abc123"
    assert doc.asset_ref == "model:gbdt_xs:v3"
    assert doc.permission.allowed_users == ("u1",)
    assert doc.metadata["training_code_hash"] == "hash:traincode"

    index = ResearchAssetRAGIndex()
    index.add(doc)
    hits = index.retrieve(
        "passport ranking",
        context=_ctx("model:gbdt_xs:v3", desk="model"),
        projections=(RAGProjection.MODEL,),
    )
    assert len(hits) == 1
    assert hits[0].projection == "ModelRAG"


def test_strategy_helper_excludes_raw_code_but_keeps_description():
    strat = _FakeStrategy()
    doc = build_strategy_rag_document(strat)  # owner defaults to owner_username
    assert doc.projection_value == "StrategyRAG"
    assert doc.source_id == "strategy:strat_btc_mom"
    assert doc.version == "2026-06-29T00:00:00+00:00"
    assert doc.permission.allowed_users == ("u1",)
    # raw strategy source code is NEVER copied into the index (only a hash)
    assert "SECRET_PROPRIETARY_FORMULA" not in doc.body
    assert "SECRET_PROPRIETARY_FORMULA" not in str(doc.metadata)
    assert doc.metadata["code_hash"]
    # the human description/rationale IS indexed (GOAL §5)
    assert "momentum" in doc.body.lower()

    index = ResearchAssetRAGIndex()
    index.add(doc)
    hits = index.retrieve(
        "momentum",
        context=_ctx("strategy:strat_btc_mom", desk="strategy"),
        projections=(RAGProjection.STRATEGY,),
    )
    assert len(hits) == 1
    assert hits[0].projection == "StrategyRAG"


# --------------------------------------------------------------------------
# Permission isolation (security invariant — 越权不返)
# --------------------------------------------------------------------------


def test_autosync_default_permission_is_owner_scoped_and_isolates():
    index = ResearchAssetRAGIndex()
    index.add(build_factor_rag_document(_factor()))  # owner u1 / desk factor / asset factor:mom_20

    # owner on the right desk with the asset visible -> returned
    assert index.retrieve("momentum", context=_ctx("factor:mom_20", desk="factor"))
    # a different user -> not returned
    assert not index.retrieve("momentum", context=_ctx("factor:mom_20", user_id="u2", desk="factor"))
    # a different desk -> not returned
    assert not index.retrieve("momentum", context=_ctx("factor:mom_20", desk="model"))
    # asset not in the caller's visible set -> not returned
    assert not index.retrieve("momentum", context=_ctx("factor:other", desk="factor"))


def test_autosync_explicit_permission_is_used_verbatim_with_tag_gate():
    perm = RAGPermission(
        allowed_users=("u1", "u2"),
        allowed_desks=("factor",),
        allowed_assets=("factor:mom_20",),
        permission_tags=("research.read",),
    )
    doc = build_factor_rag_document(_factor(), permission=perm)
    assert doc.permission.allowed_users == ("u1", "u2")
    assert doc.permission.permission_tags == ("research.read",)

    index = ResearchAssetRAGIndex()
    index.add(doc)
    # u2 is now allowed but must carry the capability tag
    assert index.retrieve(
        "momentum",
        context=_ctx("factor:mom_20", user_id="u2", desk="factor", permission_tags=("research.read",)),
    )
    # without the tag the doc stays hidden even for an allowed user/desk
    assert not index.retrieve(
        "momentum",
        context=_ctx("factor:mom_20", user_id="u2", desk="factor", permission_tags=()),
    )


def test_autosync_rejects_empty_owner_permission_hole():
    # no author on the object and no owner passed -> reject (never allowed_users=("",))
    with pytest.raises(AssetRAGError):
        build_factor_rag_document(_factor(author=""))


def test_autosync_rejects_plaintext_secret_through_helper_path():
    # secrets must never reach the RAG body/metadata even via extra_metadata
    with pytest.raises(AssetRAGError):
        build_factor_rag_document(
            _factor(),
            extra_metadata={"api_key": "sk-live-1234567890abcdef"},
        )


# --------------------------------------------------------------------------
# Projection mapping sentinel (mutation target) + cross-projection lane
# --------------------------------------------------------------------------


def test_autosync_projection_mapping_is_pinned_per_asset_type():
    # Swapping any builder's projection in asset_rag.py (e.g. factor -> ModelRAG)
    # makes this assertion go red. This is the autosync mutation sentinel.
    assert build_factor_rag_document(_factor()).projection_value == "FactorRAG"
    assert build_signal_rag_document(_signal()).projection_value == "SignalRAG"
    assert build_model_rag_document(_FakePassport(), owner="u1").projection_value == "ModelRAG"
    assert build_strategy_rag_document(_FakeStrategy()).projection_value == "StrategyRAG"


def test_autosync_projection_filter_keeps_assets_in_their_lane():
    index = ResearchAssetRAGIndex()
    index.add(build_factor_rag_document(_factor()))
    ctx = _ctx("factor:mom_20", desk="factor")
    assert index.retrieve("momentum", context=ctx, projections=(RAGProjection.FACTOR,))
    # the same factor must not surface under a different desk's projection filter
    assert not index.retrieve("momentum", context=ctx, projections=(RAGProjection.MODEL,))
