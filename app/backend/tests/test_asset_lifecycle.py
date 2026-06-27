from __future__ import annotations

from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    IngestionSkillUpdateRecord,
    LifecycleState,
    LifecycleTransitionRequest,
    PersistentAssetLifecycleRegistry,
    RetiredAssetUseRequest,
    validate_asset_lifecycle,
    validate_governed_asset,
    validate_ingestion_skill_update,
    validate_lifecycle_transition,
    validate_retired_asset_use,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _asset(**overrides) -> GovernedAssetRecord:
    data = {
        "asset_ref": "strategy_book:momentum:v1",
        "asset_type": "StrategyBook",
        "category": AssetCategory.USER_ASSET,
        "lifecycle_state": LifecycleState.VALIDATION_DOSSIER,
        "evidence_refs": ("validation:001",),
        "validation_plan_ref": "validation_plan:001",
        "promotion_history": ("promotion:research_to_validation",),
    }
    data.update(overrides)
    return GovernedAssetRecord(**data)


def test_formal_asset_requires_category_lifecycle_and_evidence():
    decision = validate_governed_asset(
        _asset(category=None, lifecycle_state=None, evidence_refs=())
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "asset_missing_category",
        "asset_missing_lifecycle_state",
        "asset_missing_evidence_refs",
    }


def test_demo_or_template_cannot_become_production_without_promotion_record():
    decision = validate_governed_asset(
        _asset(
            category=AssetCategory.PRODUCTION_ASSET,
            source_category=AssetCategory.DEMO,
            promotion_history=(),
        )
    )
    assert not decision.accepted
    assert "template_or_demo_promoted_without_record" in _codes(decision)


def test_retired_asset_requires_reason_and_cannot_be_default_for_new_run():
    asset_decision = validate_governed_asset(
        _asset(lifecycle_state=LifecycleState.RETIRED, retire_reason=None)
    )
    use_decision = validate_retired_asset_use(
        RetiredAssetUseRequest(
            request_ref="use:retired",
            asset_ref="factor:retired",
            new_run_ref="run:new",
            default_reference=True,
        )
    )
    assert not asset_decision.accepted
    assert not use_decision.accepted
    assert "retired_asset_missing_retire_reason" in _codes(asset_decision)
    assert "retired_asset_default_referenced_by_new_run" in _codes(use_decision)


def test_ingestion_skill_update_requires_dataset_version_checksum_and_lineage():
    decision = validate_ingestion_skill_update(
        IngestionSkillUpdateRecord(
            update_ref="ingestion:update:001",
            skill_ref="skill:csv",
            skill_version="v2",
            source_ref=None,
            secret_ref=None,
            dataset_version_ref=None,
            checksum=None,
            lineage_ref=None,
            quality_verdict_ref=None,
            known_at_ref=None,
            effective_at_ref=None,
        )
    )
    assert not decision.accepted
    assert "ingestion_update_missing_dataset_version_lineage" in _codes(decision)


def test_runtime_transition_requires_promotion_approval_and_evidence():
    decision = validate_lifecycle_transition(
        LifecycleTransitionRequest(
            request_ref="transition:runtime",
            asset_ref="strategy:001",
            from_state=LifecycleState.PAPER_CANDIDATE,
            to_state=LifecycleState.APPROVED_RUNTIME,
            promotion_record_ref=None,
            approval_ref=None,
            evidence_refs=(),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "runtime_transition_missing_promotion_or_approval",
        "runtime_transition_missing_evidence",
    }


def test_proof_backed_and_user_waived_assets_require_consistency_and_responsibility():
    decision = validate_governed_asset(
        _asset(
            display_label="proof_backed",
            consistency_check_ref=None,
            methodology_choice_ref="choice:user_waived",
            responsibility_boundary_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "proof_backed_asset_missing_consistency_check",
        "methodology_choice_missing_responsibility_boundary",
    }


def test_complete_lifecycle_contract_accepts_governed_asset_update_and_transition():
    decision = validate_asset_lifecycle(
        (_asset(consistency_check_ref="consistency:001", display_label="evidence_sufficient"),),
        ingestion_updates=(
            IngestionSkillUpdateRecord(
                update_ref="ingestion:update:001",
                skill_ref="skill:rest",
                skill_version="v1",
                source_ref="datasource:rest",
                secret_ref="secretref:rest:read",
                dataset_version_ref="dataset_version:001",
                checksum="sha256:abc",
                lineage_ref="lineage:001",
                quality_verdict_ref="quality:pass",
                known_at_ref="known_at:ingest_time",
                effective_at_ref="effective_at:bar_close",
            ),
        ),
        retired_use_requests=(
            RetiredAssetUseRequest(
                request_ref="use:retired:override",
                asset_ref="factor:retired",
                new_run_ref="run:001",
                default_reference=True,
                override_ref="explicit_override:001",
            ),
        ),
        transitions=(
            LifecycleTransitionRequest(
                request_ref="transition:runtime",
                asset_ref="strategy:001",
                from_state=LifecycleState.PAPER_CANDIDATE,
                to_state=LifecycleState.APPROVED_RUNTIME,
                promotion_record_ref="promotion:001",
                approval_ref="approval:001",
                evidence_refs=("validation:001",),
            ),
        ),
    )
    assert decision.accepted
    assert decision.violations == ()


def test_persistent_asset_lifecycle_registry_replays_ingestion_updates(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    registry.record_ingestion_skill_update(
        IngestionSkillUpdateRecord(
            update_ref="ingestion:update:001",
            skill_ref="skill:rest",
            skill_version="v1",
            source_ref="datasource:rest",
            secret_ref="secretref:rest:read",
            dataset_version_ref="dataset_version:001",
            checksum="sha256:abc",
            lineage_ref="lineage:001",
            quality_verdict_ref="quality:pass",
            known_at_ref="known_at:ingest_time",
            effective_at_ref="effective_at:bar_close",
            evidence_refs=("connector_check:001",),
        )
    )

    reloaded = PersistentAssetLifecycleRegistry(path)
    update = reloaded.ingestion_skill_update("ingestion:update:001")
    assert update.dataset_version_ref == "dataset_version:001"
    assert update.evidence_refs == ("connector_check:001",)
