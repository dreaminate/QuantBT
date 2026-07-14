from __future__ import annotations

import json
import threading

import pytest

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


def _update(
    *,
    owner: str = "u1",
    update_ref: str = "ingestion:update:refresh",
    dataset_ref: str = "dataset:refresh",
) -> IngestionSkillUpdateRecord:
    return IngestionSkillUpdateRecord(
        update_ref=update_ref,
        skill_ref="skill:rest",
        skill_version="v1",
        source_ref="datasource:rest",
        secret_ref="secretref:rest:read",
        dataset_version_ref=dataset_ref,
        checksum=f"sha256:{dataset_ref}",
        lineage_ref=f"lineage:{dataset_ref}",
        quality_verdict_ref="quality:pass",
        known_at_ref="known_at:ingest_time",
        effective_at_ref="effective_at:bar_close",
        recorded_by=owner,
    )


def _template_asset(**overrides) -> GovernedAssetRecord:
    data = {
        "asset_ref": "template:btc_momentum_v1",
        "asset_type": "StrategyTemplate",
        "category": AssetCategory.TEMPLATE,
        "lifecycle_state": LifecycleState.SPECIFIED,
        "evidence_refs": ("source:datasets.templates:btc_momentum_v1",),
        "validation_plan_ref": "validation:template_contract:btc_momentum_v1",
        "promotion_history": (),
        "display_label": "MOCK · TEMPLATE · crypto_perp",
        "mock_label_ref": "mock_label:template:btc_momentum_v1",
        "asset_category_ref": "asset_category:crypto_perp:btc_momentum_v1",
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


def test_example_asset_requires_typed_mock_and_asset_category_refs():
    decision = validate_governed_asset(
        _template_asset(mock_label_ref=None, asset_category_ref=None, display_label="")
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "example_asset_missing_mock_label_ref",
        "example_asset_missing_asset_category_ref",
        "example_asset_missing_visible_label",
    }


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
            recorded_by="u1",
            evidence_refs=("connector_check:001",),
        ),
        owner_user_id="u1",
    )

    reloaded = PersistentAssetLifecycleRegistry(path)
    update = reloaded.ingestion_skill_update(
        "ingestion:update:001",
        owner_user_id="u1",
    )
    assert update.dataset_version_ref == "dataset_version:001"
    assert update.evidence_refs == ("connector_check:001",)


def test_persistent_asset_lifecycle_registry_isolates_owner_and_quarantines_v1(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    legacy = {
        "schema_version": 1,
        "event_type": "ingestion_skill_update_recorded",
        "ingestion_skill_update": {
            "update_ref": "legacy:update",
            "skill_ref": "legacy:skill",
            "skill_version": "v1",
            "dataset_version_ref": "dataset:legacy",
            "checksum": "sha256:legacy",
            "lineage_ref": "lineage:legacy",
            "quality_verdict_ref": "quality:legacy",
            "recorded_by": "legacy-name",
        },
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    registry = PersistentAssetLifecycleRegistry(path)
    assert registry.legacy_quarantined_count == 1
    assert registry.ingestion_skill_updates(owner_user_id="u1") == []
    with pytest.raises(KeyError):
        registry.ingestion_skill_update("legacy:update", owner_user_id="legacy-name")

    def record(owner: str, dataset: str):
        return registry.record_ingestion_skill_update(
            IngestionSkillUpdateRecord(
                update_ref="shared:update",
                skill_ref="skill:rest",
                skill_version="v1",
                source_ref="datasource:rest",
                secret_ref="secretref:rest:read",
                dataset_version_ref=dataset,
                checksum=f"sha256:{dataset}",
                lineage_ref=f"lineage:{dataset}",
                quality_verdict_ref="quality:pass",
                known_at_ref="known_at:ingest_time",
                effective_at_ref="effective_at:bar_close",
                recorded_by=owner,
            ),
            owner_user_id=owner,
        )

    first = record("u1", "dataset:u1")
    second = record("u2", "dataset:u2")
    assert registry.ingestion_skill_update(
        first.update_ref,
        owner_user_id="u1",
    ).dataset_version_ref == "dataset:u1"
    assert registry.ingestion_skill_update(
        second.update_ref,
        owner_user_id="u2",
    ).dataset_version_ref == "dataset:u2"
    with pytest.raises(ValueError, match="recorded_by"):
        registry.record_ingestion_skill_update(first, owner_user_id="u2")


def test_persistent_asset_lifecycle_exact_retry_is_cross_instance_idempotent(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    first = PersistentAssetLifecycleRegistry(path)
    second = PersistentAssetLifecycleRegistry(path)
    record = IngestionSkillUpdateRecord(
        update_ref="ingestion:update:concurrent",
        skill_ref="skill:rest",
        skill_version="v1",
        source_ref="datasource:rest",
        secret_ref="secretref:rest:read",
        dataset_version_ref="dataset:concurrent",
        checksum="sha256:concurrent",
        lineage_ref="lineage:concurrent",
        quality_verdict_ref="quality:pass",
        known_at_ref="known_at:ingest_time",
        effective_at_ref="effective_at:bar_close",
        recorded_by="u1",
    )
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def write(registry: PersistentAssetLifecycleRegistry) -> None:
        try:
            barrier.wait(timeout=5)
            registry.record_ingestion_skill_update(record, owner_user_id="u1")
        except BaseException as exc:  # noqa: BLE001 - collect worker failure.
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(registry,)) for registry in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["schema_version"] == 2
    assert rows[0]["owner_user_id"] == "u1"


def test_peer_append_becomes_visible_to_already_open_registry(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    first = PersistentAssetLifecycleRegistry(path)
    second = PersistentAssetLifecycleRegistry(path)
    record = _update()

    second.record_ingestion_skill_update(record, owner_user_id="u1")

    assert first.ingestion_skill_update(
        record.update_ref,
        owner_user_id="u1",
    ) == record


def test_corruption_and_deletion_after_startup_fail_closed(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    record = _update()
    registry.record_ingestion_skill_update(record, owner_user_id="u1")

    original = path.read_text(encoding="utf-8")
    path.write_text(original + "not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid persisted"):
        registry.ingestion_skill_update(record.update_ref, owner_user_id="u1")

    path.write_text(original, encoding="utf-8")
    path.unlink()
    with pytest.raises(ValueError, match="history is missing"):
        registry.ingestion_skill_update(record.update_ref, owner_user_id="u1")


def test_exact_retry_after_delete_and_restart_fails_closed(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    record = _update()
    PersistentAssetLifecycleRegistry(path).record_ingestion_skill_update(
        record,
        owner_user_id="u1",
    )
    marker = path.with_suffix(path.suffix + ".history")
    assert marker.is_file()
    path.unlink()

    with pytest.raises(ValueError, match="history is missing"):
        PersistentAssetLifecycleRegistry(path)


def test_missing_marker_cannot_reanchor_replaced_valid_history(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    registry.record_ingestion_skill_update(_update(), owner_user_id="u1")
    marker = path.with_suffix(path.suffix + ".history")
    marker.unlink()

    # Replace the journal with another structurally valid row while the anchor
    # is absent; restart must reject before it can mint a new marker.
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    row["ingestion_skill_update"]["update_ref"] = "ingestion:update:forged"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="history marker is missing"):
        PersistentAssetLifecycleRegistry(path)


def test_stale_marker_accepts_only_valid_append_suffix_and_advances(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    registry.record_ingestion_skill_update(
        _update(update_ref="ingestion:update:first", dataset_ref="dataset:first"),
        owner_user_id="u1",
    )
    marker = path.with_suffix(path.suffix + ".history")
    stale_marker = marker.read_bytes()
    registry.record_ingestion_skill_update(
        _update(update_ref="ingestion:update:second", dataset_ref="dataset:second"),
        owner_user_id="u1",
    )
    marker.write_bytes(stale_marker)

    reopened = PersistentAssetLifecycleRegistry(path)
    assert len(reopened.ingestion_skill_updates(owner_user_id="u1")) == 2
    assert json.loads(marker.read_text(encoding="utf-8"))["row_count"] == 2


def test_duplicate_exact_persisted_row_is_rejected(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    record = _update()
    registry.record_ingestion_skill_update(record, owner_user_id="u1")
    encoded = path.read_text(encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)

    with pytest.raises(ValueError, match="invalid persisted"):
        registry.ingestion_skill_update(record.update_ref, owner_user_id="u1")


def test_concurrent_list_and_write_use_stable_snapshots(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for index in range(20):
                registry.record_ingestion_skill_update(
                    _update(
                        update_ref=f"ingestion:update:{index}",
                        dataset_ref=f"dataset:{index}",
                    ),
                    owner_user_id="u1",
                )
        except BaseException as exc:  # noqa: BLE001 - thread probe captures failures.
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    while thread.is_alive():
        try:
            list(registry.ingestion_skill_updates(owner_user_id="u1"))
        except BaseException as exc:  # noqa: BLE001 - thread probe captures failures.
            errors.append(exc)
            break
    thread.join(timeout=10)

    assert errors == []
    assert len(registry.ingestion_skill_updates(owner_user_id="u1")) == 20


def test_governed_example_asset_persists_replays_and_is_owner_scoped(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    record = _template_asset()
    registry.record_governed_asset(record, owner_user_id="u1")

    reopened = PersistentAssetLifecycleRegistry(path)
    assert reopened.governed_asset(record.asset_ref, owner_user_id="u1") == record
    assert (
        reopened.governed_asset_by_mock_label_ref(
            str(record.mock_label_ref), owner_user_id="u1"
        )
        == record
    )
    assert (
        reopened.governed_asset_by_category_ref(
            str(record.asset_category_ref), owner_user_id="u1"
        )
        == record
    )
    with pytest.raises(KeyError):
        reopened.governed_asset(record.asset_ref, owner_user_id="u2")


def test_governed_example_asset_rejection_writes_no_partial_row(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    with pytest.raises(ValueError, match="example_asset_missing_mock_label_ref"):
        registry.record_governed_asset(
            _template_asset(mock_label_ref=None),
            owner_user_id="u1",
        )
    assert not path.exists() or path.read_text(encoding="utf-8") == ""
    assert registry.governed_assets(owner_user_id="u1") == []


def test_governed_example_asset_exact_retry_and_conflicting_ref_fail_closed(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    first = PersistentAssetLifecycleRegistry(path)
    second = PersistentAssetLifecycleRegistry(path)
    record = _template_asset()
    assert first.record_governed_asset(record, owner_user_id="u1") == record
    assert second.record_governed_asset(record, owner_user_id="u1") == record
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    with pytest.raises(ValueError, match="mock_label_ref identity collision"):
        second.record_governed_asset(
            _template_asset(
                asset_ref="template:other",
                asset_category_ref="asset_category:crypto_perp:other",
            ),
            owner_user_id="u1",
        )
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
