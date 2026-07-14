from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.research_os.asset_lifecycle import (
    GovernedAssetRecord,
    PersistentAssetLifecycleRegistry,
)
from app.research_os.teaching_assets import PersistentTeachingAssetRegistry


OWNER = "teaching-owner"


def _lifecycle(tmp_path, *, owner: str = OWNER, category: str = "tutorial"):
    store = PersistentAssetLifecycleRegistry(tmp_path / "lifecycle.jsonl")
    asset = GovernedAssetRecord(
        asset_ref=f"lesson:{owner}:{category}",
        asset_type="Lesson",
        category=category,
        lifecycle_state="linked",
        evidence_refs=("evidence:lesson-source",),
        validation_plan_ref="validation:lesson",
        promotion_history=(),
        display_label="TUTORIAL - evidence and weaknesses visible",
        mock_label_ref=f"mock_label:{owner}:{category}",
        asset_category_ref=f"asset_category:{owner}:{category}",
    )
    return store, store.record_governed_asset(asset, owner_user_id=owner)


def test_teaching_bundle_is_owner_scoped_restart_safe_and_idempotent(tmp_path) -> None:
    lifecycle, asset = _lifecycle(tmp_path)
    path = tmp_path / "teaching.jsonl"
    store = PersistentTeachingAssetRegistry(path, lifecycle_registry=lifecycle)
    first = store.record_bundle(
        owner_user_id=OWNER,
        governed_asset_ref=asset.asset_ref,
        title="Read the evidence before using the example",
        weakness_refs=("weakness:small-sample", "weakness:cost-model"),
        evidence_refs=("evidence:tutorial-run", "evidence:tutorial-review"),
    )
    repeated = store.record_bundle(
        owner_user_id=OWNER,
        governed_asset_ref=asset.asset_ref,
        title="Read the evidence before using the example",
        weakness_refs=("weakness:small-sample", "weakness:cost-model"),
        evidence_refs=("evidence:tutorial-run", "evidence:tutorial-review"),
    )
    assert repeated == first
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    restarted = PersistentTeachingAssetRegistry(path, lifecycle_registry=lifecycle)
    assert restarted.tutorial_asset(
        first.tutorial.tutorial_asset_ref, owner_user_id=OWNER
    ) == first.tutorial
    assert restarted.weakness_disclosure(
        first.weakness.weakness_disclosure_ref, owner_user_id=OWNER
    ).visible_by_default is True
    assert restarted.teaching_evidence(
        first.evidence.teaching_evidence_ref, owner_user_id=OWNER
    ) == first.evidence
    with pytest.raises(KeyError):
        restarted.tutorial_asset(
            first.tutorial.tutorial_asset_ref, owner_user_id="foreign"
        )


def test_teaching_bundle_rejects_non_teaching_lifecycle_category(tmp_path) -> None:
    lifecycle, asset = _lifecycle(tmp_path, category="user_asset")
    store = PersistentTeachingAssetRegistry(
        tmp_path / "teaching.jsonl", lifecycle_registry=lifecycle
    )
    with pytest.raises(ValueError, match="category"):
        store.record_bundle(
            owner_user_id=OWNER,
            governed_asset_ref=asset.asset_ref,
            title="Not a tutorial",
            weakness_refs=("weakness:any",),
            evidence_refs=("evidence:any",),
        )


def test_teaching_bundle_detects_persisted_tampering(tmp_path) -> None:
    lifecycle, asset = _lifecycle(tmp_path)
    path = tmp_path / "teaching.jsonl"
    store = PersistentTeachingAssetRegistry(path, lifecycle_registry=lifecycle)
    store.record_bundle(
        owner_user_id=OWNER,
        governed_asset_ref=asset.asset_ref,
        title="Tamper test",
        weakness_refs=("weakness:any",),
        evidence_refs=("evidence:any",),
    )
    row = json.loads(path.read_text(encoding="utf-8"))
    row["bundle"]["weakness"]["visible_by_default"] = False
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted teaching asset event"):
        PersistentTeachingAssetRegistry(path, lifecycle_registry=lifecycle)


def test_teaching_bundle_concurrent_same_record_has_one_durable_event(tmp_path) -> None:
    lifecycle, asset = _lifecycle(tmp_path)
    path = tmp_path / "teaching.jsonl"
    stores = [
        PersistentTeachingAssetRegistry(path, lifecycle_registry=lifecycle)
        for _ in range(4)
    ]

    def record(store):
        return store.record_bundle(
            owner_user_id=OWNER,
            governed_asset_ref=asset.asset_ref,
            title="Concurrent lesson",
            weakness_refs=("weakness:concurrency",),
            evidence_refs=("evidence:concurrency",),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(record, stores))

    assert len({item.tutorial.tutorial_asset_ref for item in results}) == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert len(
        PersistentTeachingAssetRegistry(
            path, lifecycle_registry=lifecycle
        ).bundles(owner_user_id=OWNER)
    ) == 1
