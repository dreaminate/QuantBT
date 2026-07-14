from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
)
from app.research_os.lifecycle_transition import (
    PersistentLifecycleTransitionRegistry,
    REQUIRED_LIFECYCLE_ASSET_TYPES,
)
from app.research_os.goal_coverage import GoalCoverageDecision
from app.research_os.goal_semantic_adapters import LifecycleClosureSectionAdapter
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    goal_section_semantic_proof_identity,
)


OWNER = "user:lifecycle"

_GOAL_LIFECYCLE_ASSET_TYPES = {
    "StrategyBook",
    "ResearchAsset",
    "DataSourceAsset",
    "Integration",
    "IngestionSkill",
    "Dataset",
    "Observable",
    "MathematicalSpine",
    "TheoryImplementationBinding",
    "LLMProvider",
    "ModelRoutingPolicy",
    "Factor",
    "Model",
    "Signal",
    "PortfolioPolicy",
    "RiskPolicy",
    "ExecutionPolicy",
    "Experiment",
    "Run",
}


def _asset(ref: str, asset_type: str, state: LifecycleState) -> GovernedAssetRecord:
    return GovernedAssetRecord(
        asset_ref=ref,
        asset_type=asset_type,
        category=AssetCategory.USER_ASSET,
        lifecycle_state=state,
        evidence_refs=(f"evidence:{ref}",),
        validation_plan_ref=f"validation_plan:{ref}",
        promotion_history=(),
    )


def test_required_lifecycle_types_cover_every_goal_family() -> None:
    assert REQUIRED_LIFECYCLE_ASSET_TYPES == _GOAL_LIFECYCLE_ASSET_TYPES


class _Assets:
    def __init__(self) -> None:
        self.by_owner: dict[tuple[str, str], GovernedAssetRecord] = {}

    def add(self, owner: str, asset: GovernedAssetRecord) -> None:
        self.by_owner[(owner, asset.asset_ref)] = asset

    def __call__(self, owner: str, ref: str) -> GovernedAssetRecord:
        return self.by_owner[(owner, ref)]


def _refs(owner: str, kind: str, ref: str) -> bool:
    return owner == OWNER and ref.startswith(f"{kind}:")


def _seed_complete(assets: _Assets) -> dict[str, tuple[GovernedAssetRecord, GovernedAssetRecord]]:
    pairs = {}
    for index, asset_type in enumerate(sorted(REQUIRED_LIFECYCLE_ASSET_TYPES)):
        before = _asset(f"asset:{index}:v1", asset_type, LifecycleState.DRAFT)
        after = _asset(f"asset:{index}:v2", asset_type, LifecycleState.SPECIFIED)
        assets.add(OWNER, before)
        assets.add(OWNER, after)
        pairs[f"logical:{index}"] = (before, after)
    return pairs


def _record_complete(registry, pairs):
    records = []
    for logical, (before, after) in pairs.items():
        records.append(
            registry.record_transition(
                owner_user_id=OWNER,
                logical_asset_ref=logical,
                before_asset_ref=before.asset_ref,
                after_asset_ref=after.asset_ref,
                evidence_refs=(f"evidence:{logical}",),
            )
        )
    return records


def test_complete_current_lifecycle_receipt_replays_and_revalidates(tmp_path) -> None:
    assets = _Assets()
    pairs = _seed_complete(assets)
    path = tmp_path / "lifecycle_transitions.jsonl"
    registry = PersistentLifecycleTransitionRegistry(
        path,
        asset_loader=assets,
        ref_validator=_refs,
    )
    transitions = _record_complete(registry, pairs)

    receipt = registry.record_current_receipt(owner_user_id=OWNER)

    assert registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted
    assert set(receipt.asset_types) == set(REQUIRED_LIFECYCLE_ASSET_TYPES)
    assert len(receipt.transition_refs) == len(REQUIRED_LIFECYCLE_ASSET_TYPES)
    reloaded = PersistentLifecycleTransitionRegistry(
        path,
        asset_loader=assets,
        ref_validator=_refs,
    )
    assert reloaded.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    assert reloaded.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:0",
        before_asset_ref=pairs["logical:0"][0].asset_ref,
        after_asset_ref=pairs["logical:0"][1].asset_ref,
        evidence_refs=("evidence:logical:0",),
    ) == transitions[0]


def test_asset_drift_and_new_head_make_old_receipt_red(tmp_path) -> None:
    assets = _Assets()
    pairs = _seed_complete(assets)
    registry = PersistentLifecycleTransitionRegistry(
        tmp_path / "transitions.jsonl",
        asset_loader=assets,
        ref_validator=_refs,
    )
    _record_complete(registry, pairs)
    receipt = registry.record_current_receipt(owner_user_id=OWNER)
    current = pairs["logical:0"][1]
    assets.add(
        OWNER,
        replace(current, evidence_refs=("evidence:changed-current-content",)),
    )

    decision = registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER)

    assert not decision.accepted
    assert any("asset_drift" in item for item in decision.violations)


def test_two_registries_replay_heads_before_writes_validation_and_snapshot(
    tmp_path,
) -> None:
    assets = _Assets()
    v1 = _asset("asset:shared:v1", "StrategyBook", LifecycleState.DRAFT)
    v2 = _asset("asset:shared:v2", "StrategyBook", LifecycleState.SPECIFIED)
    v3 = _asset("asset:shared:v3", "StrategyBook", LifecycleState.LINKED)
    stale_alternative = _asset(
        "asset:shared:stale-alternative",
        "StrategyBook",
        LifecycleState.SPECIFIED,
    )
    for asset in (v1, v2, v3, stale_alternative):
        assets.add(OWNER, asset)
    path = tmp_path / "shared-transitions.jsonl"
    first = PersistentLifecycleTransitionRegistry(
        path,
        asset_loader=assets,
        ref_validator=_refs,
        required_asset_types=frozenset({"StrategyBook"}),
    )
    stale = PersistentLifecycleTransitionRegistry(
        path,
        asset_loader=assets,
        ref_validator=_refs,
        required_asset_types=frozenset({"StrategyBook"}),
    )
    initial = first.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:shared",
        before_asset_ref=v1.asset_ref,
        after_asset_ref=v2.asset_ref,
        evidence_refs=("evidence:shared:v2",),
    )
    old_receipt = first.record_current_receipt(owner_user_id=OWNER)

    assert stale.validate_current(
        old_receipt.receipt_ref,
        owner_user_id=OWNER,
    ).accepted
    latest = first.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:shared",
        before_asset_ref=v2.asset_ref,
        after_asset_ref=v3.asset_ref,
        evidence_refs=("evidence:shared:v3",),
    )

    stale_decision = stale.validate_current(
        old_receipt.receipt_ref,
        owner_user_id=OWNER,
    )
    assert not stale_decision.accepted
    assert "lifecycle_transition_heads_changed" in stale_decision.violations
    with pytest.raises(ValueError, match="before asset is not the current head"):
        stale.record_transition(
            owner_user_id=OWNER,
            logical_asset_ref="logical:shared",
            before_asset_ref=v1.asset_ref,
            after_asset_ref=stale_alternative.asset_ref,
            evidence_refs=("evidence:shared:stale",),
        )

    current_receipt = stale.record_current_receipt(owner_user_id=OWNER)
    snapshot = first.current_closure_snapshot(
        current_receipt.receipt_ref,
        owner_user_id=OWNER,
    )
    assert snapshot.receipt == current_receipt
    assert snapshot.transitions == (latest,)
    assert snapshot.before_assets == (v2,)
    assert snapshot.after_assets == (v3,)
    assert initial.transition_ref in {
        item.transition_ref for item in first.transitions(owner_user_id=OWNER)
    }


def test_missing_family_cross_owner_and_mixed_head_fail_closed(tmp_path) -> None:
    assets = _Assets()
    before = _asset("asset:one:v1", "StrategyBook", LifecycleState.DRAFT)
    after = _asset("asset:one:v2", "StrategyBook", LifecycleState.SPECIFIED)
    assets.add(OWNER, before)
    assets.add(OWNER, after)
    registry = PersistentLifecycleTransitionRegistry(
        tmp_path / "transitions.jsonl",
        asset_loader=assets,
        ref_validator=_refs,
    )
    registry.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:one",
        before_asset_ref=before.asset_ref,
        after_asset_ref=after.asset_ref,
        evidence_refs=("evidence:one",),
    )

    with pytest.raises(ValueError, match="asset_type_missing"):
        registry.record_current_receipt(owner_user_id=OWNER)
    with pytest.raises(KeyError):
        registry.transition(
            registry._heads[(OWNER, "logical:one")],
            owner_user_id="user:other",
        )
    unrelated = _asset("asset:unrelated:v2", "StrategyBook", LifecycleState.SPECIFIED)
    assets.add(OWNER, unrelated)
    with pytest.raises(ValueError, match="not the current head"):
        registry.record_transition(
            owner_user_id=OWNER,
            logical_asset_ref="logical:one",
            before_asset_ref=unrelated.asset_ref,
            after_asset_ref=after.asset_ref,
            evidence_refs=("evidence:mixed",),
        )


def test_retired_default_use_without_override_blocks_receipt(tmp_path) -> None:
    assets = _Assets()
    before = _asset("asset:retire:v1", "StrategyBook", LifecycleState.DEMOTED)
    after = replace(
        _asset("asset:retire:v2", "StrategyBook", LifecycleState.RETIRED),
        retire_reason="superseded",
    )
    assets.add(OWNER, before)
    assets.add(OWNER, after)
    registry = PersistentLifecycleTransitionRegistry(
        tmp_path / "transitions.jsonl",
        asset_loader=assets,
        ref_validator=_refs,
        usage_loader=lambda _owner, _asset: (("run:new", True, None),),
        required_asset_types=frozenset({"StrategyBook"}),
    )
    registry.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:retire",
        before_asset_ref=before.asset_ref,
        after_asset_ref=after.asset_ref,
        evidence_refs=("evidence:retirement",),
    )

    with pytest.raises(ValueError, match="retired_default_use"):
        registry.record_current_receipt(owner_user_id=OWNER)


def test_runtime_transition_requires_real_promotion_approval_and_legacy_is_quarantined(
    tmp_path,
) -> None:
    assets = _Assets()
    before = _asset("asset:runtime:v1", "StrategyBook", LifecycleState.PAPER_CANDIDATE)
    after = _asset("asset:runtime:v2", "StrategyBook", LifecycleState.APPROVED_RUNTIME)
    assets.add(OWNER, before)
    assets.add(OWNER, after)
    path = tmp_path / "transitions.jsonl"
    path.write_text(json.dumps({"schema_version": 1, "event_type": "legacy"}) + "\n")
    registry = PersistentLifecycleTransitionRegistry(
        path,
        asset_loader=assets,
        ref_validator=_refs,
        required_asset_types=frozenset({"StrategyBook"}),
    )

    assert registry.legacy_quarantined_count == 1
    with pytest.raises(ValueError, match="requires promotion and approval"):
        registry.record_transition(
            owner_user_id=OWNER,
            logical_asset_ref="logical:runtime",
            before_asset_ref=before.asset_ref,
            after_asset_ref=after.asset_ref,
            evidence_refs=("evidence:runtime",),
        )
    accepted = registry.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:runtime",
        before_asset_ref=before.asset_ref,
        after_asset_ref=after.asset_ref,
        promotion_record_ref="promotion:runtime",
        approval_ref="approval:runtime",
        evidence_refs=("evidence:runtime",),
    )
    assert accepted.to_state == LifecycleState.APPROVED_RUNTIME.value


def test_transition_rejects_cross_type_assets_and_historical_type_drift(
    tmp_path,
) -> None:
    assets = _Assets()
    before = _asset("asset:type:v1", "StrategyBook", LifecycleState.DRAFT)
    cross_type_after = _asset(
        "asset:type:cross",
        "Run",
        LifecycleState.SPECIFIED,
    )
    valid_after = _asset(
        "asset:type:v2",
        "StrategyBook",
        LifecycleState.SPECIFIED,
    )
    for asset in (before, cross_type_after, valid_after):
        assets.add(OWNER, asset)
    registry = PersistentLifecycleTransitionRegistry(
        tmp_path / "type-transitions.jsonl",
        asset_loader=assets,
        ref_validator=_refs,
        required_asset_types=frozenset({"StrategyBook"}),
    )

    with pytest.raises(ValueError, match="same asset_type"):
        registry.record_transition(
            owner_user_id=OWNER,
            logical_asset_ref="logical:type",
            before_asset_ref=before.asset_ref,
            after_asset_ref=cross_type_after.asset_ref,
            evidence_refs=("evidence:type:cross",),
        )

    registry.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:type",
        before_asset_ref=before.asset_ref,
        after_asset_ref=valid_after.asset_ref,
        evidence_refs=("evidence:type:valid",),
    )
    receipt = registry.record_current_receipt(owner_user_id=OWNER)
    assets.add(OWNER, replace(valid_after, asset_type="Run"))

    decision = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
    )
    assert not decision.accepted
    assert any(
        violation.startswith("asset_type_changed:")
        for violation in decision.violations
    )
    with pytest.raises(ValueError, match="asset_type_changed"):
        registry.current_closure_snapshot(
            receipt.receipt_ref,
            owner_user_id=OWNER,
        )


def _seed_transition_history(path, assets: _Assets):
    first = _asset("asset:history:v1", "StrategyBook", LifecycleState.DRAFT)
    second = _asset(
        "asset:history:v2",
        "StrategyBook",
        LifecycleState.SPECIFIED,
    )
    third = _asset("asset:history:v3", "StrategyBook", LifecycleState.LINKED)
    for asset in (first, second, third):
        assets.add(OWNER, asset)
    registry = PersistentLifecycleTransitionRegistry(
        path,
        asset_loader=assets,
        ref_validator=_refs,
        required_asset_types=frozenset({"StrategyBook"}),
    )
    registry.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:history",
        before_asset_ref=first.asset_ref,
        after_asset_ref=second.asset_ref,
        evidence_refs=("evidence:history:v2",),
    )
    registry.record_transition(
        owner_user_id=OWNER,
        logical_asset_ref="logical:history",
        before_asset_ref=second.asset_ref,
        after_asset_ref=third.asset_ref,
        evidence_refs=("evidence:history:v3",),
    )
    receipt = registry.record_current_receipt(owner_user_id=OWNER)
    return registry, receipt


@pytest.mark.parametrize("mutation", ("truncate", "replace", "reorder"))
def test_history_anchor_rejects_prefix_change_on_restart(
    tmp_path,
    mutation: str,
) -> None:
    assets = _Assets()
    path = tmp_path / f"history-restart-{mutation}.jsonl"
    _registry, _receipt = _seed_transition_history(path, assets)
    rows = path.read_text(encoding="utf-8").splitlines()
    if mutation == "truncate":
        changed = rows[1:]
    elif mutation == "replace":
        replacement = json.loads(rows[0])
        replacement["transition"]["evidence_refs"] = ["evidence:forged"]
        changed = [json.dumps(replacement), *rows[1:]]
    else:
        changed = [rows[1], rows[0], *rows[2:]]
    path.write_text("\n".join(changed) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        PersistentLifecycleTransitionRegistry(
            path,
            asset_loader=assets,
            ref_validator=_refs,
            required_asset_types=frozenset({"StrategyBook"}),
        )


def test_history_anchor_rejects_prefix_truncation_in_live_registry(tmp_path) -> None:
    assets = _Assets()
    path = tmp_path / "history-live-truncation.jsonl"
    registry, receipt = _seed_transition_history(path, assets)
    rows = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(rows[1:]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        registry.validate_current(
            receipt.receipt_ref,
            owner_user_id=OWNER,
        )


def test_lifecycle_receipt_semantic_adapter_requires_exact_current_material(tmp_path) -> None:
    assets = _Assets()
    pairs = _seed_complete(assets)
    registry = PersistentLifecycleTransitionRegistry(
        tmp_path / "transitions.jsonl",
        asset_loader=assets,
        ref_validator=_refs,
    )
    _record_complete(registry, pairs)
    receipt = registry.record_current_receipt(owner_user_id=OWNER)
    coverage_ref = "goal_entrypoint_coverage:lifecycle-current"
    coverage = SimpleNamespace(
        coverage_ref=coverage_ref,
        entry_source="api",
        entrypoint_ref="api:goal.lifecycle.closure",
        goal_sections=("§3",),
        validation_refs=(receipt.receipt_ref, "goal_validation_receipt:compiler"),
    )

    class _Entrypoints:
        def coverage(self, ref, *, owner):
            if ref != coverage_ref or owner != OWNER:
                raise KeyError(ref)
            return coverage

        def validate_real_backing(self, record):
            return GoalCoverageDecision(record is coverage, ())

    adapter = LifecycleClosureSectionAdapter(_Entrypoints(), registry)
    data = {
        "section": "§3",
        "subject_ref": f"goal_section:§3:lifecycle_receipt:{receipt.receipt_ref}",
        "producer_refs": receipt.transition_refs,
        "store_refs": (receipt.receipt_ref, *receipt.current_asset_refs),
        "consumer_refs": tuple(
            f"lifecycle_current:{ref}" for ref in receipt.current_asset_refs
        ),
        "gate_verdict_refs": (receipt.receipt_ref,),
        "test_refs": (
            receipt.receipt_ref,
            *(f"lifecycle_transition_check:{ref}" for ref in receipt.transition_refs),
        ),
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    proof = GoalSectionSemanticProofRecord(**data)

    accepted = adapter.validate(proof, owner=OWNER)
    recombined = adapter.validate(
        replace(proof, store_refs=(*proof.store_refs, "asset:unrelated")),
        owner=OWNER,
    )

    assert accepted.accepted, accepted.violations
    assert not recombined.accepted
    assert any(item.field == "store_refs" for item in recombined.violations)
