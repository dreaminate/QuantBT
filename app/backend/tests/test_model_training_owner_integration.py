"""Owner-isolation regression tests for the training -> model-governance seam."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import app.training.service as training_service_module
from app.research_os import (
    ModelRecertificationRecord,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
)
from app.training import TrainingRequest, TrainingService
from app.training.schema_drift import compute_dataset_schema, schema_change_event_ref


def _request(features: list[str] | None = None) -> TrainingRequest:
    return TrainingRequest(
        name="owner-scoped-training",
        model="ridge",
        task="regression",
        feature_cols=list(features or ["f1", "f2"]),
        label_col="label",
        n_splits=2,
        dataset_id="dataset:owner-training",
    )


def _panel(features: list[str] | None = None) -> pd.DataFrame:
    names = list(features or ["f1", "f2"])
    payload: dict[str, object] = {
        "ts": pd.date_range("2025-01-01", periods=8, freq="D", tz="UTC"),
        "label": [float(index) / 10 for index in range(8)],
    }
    for offset, name in enumerate(names):
        payload[name] = [float(index + offset) for index in range(8)]
    return pd.DataFrame(payload)


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "model_governance.jsonl"
    )
    service = TrainingService(
        root=tmp_path / "training_runs",
        model_governance_registry=governance,
    )

    def fake_result(_request, _code, _panel, job_dir: Path):
        artifact = job_dir / "model.pkl"
        artifact.write_bytes(b"owner-scoped-model-artifact")
        return {
            "oos_metrics": {"r2": 0.25},
            "fold_metrics": [],
            "artifact_path": str(artifact),
        }

    def fake_inspection(_artifact_path: Path, *, expected_hash: str):
        return {
            "inspection_ref": "artifact_inspection:owner-training:v1",
            "inspection_mode": "metadata_only_no_deserialize",
            "inspector_ref": "training_artifact_inspector:v1",
            "checks": ["content_hash", "pickle_metadata"],
            "limitations": ["not_deserialized"],
            "artifact_hash": expected_hash,
        }

    monkeypatch.setattr(service, "_resolve_result", fake_result)
    monkeypatch.setattr(
        training_service_module,
        "inspect_artifact_in_subprocess",
        fake_inspection,
    )
    return service, governance


def test_training_records_exact_owner_and_server_actor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, governance = _service(tmp_path, monkeypatch)

    job = service.train_now(
        _request(),
        _panel(),
        owner_user_id=" alice ",
    )

    assert job.status == "succeeded", job.error
    passport = governance.passport(
        job.model_passport_ref,
        owner_user_id="alice",
    )
    inspection = governance.artifact_inspections(owner_user_id="alice")[0]
    assert passport.owner_user_id == "alice"
    assert passport.recorded_by == "training_service"
    assert inspection.owner_user_id == "alice"
    assert inspection.recorded_by == "training_service"

    rows = [
        json.loads(line)
        for line in governance.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["owner_user_id"] for row in rows} == {"alice"}
    assert {row["recorded_by"] for row in rows} == {"training_service"}


@pytest.mark.parametrize(
    "invoke",
    [
        lambda service: service.submit(_request(), _panel()),
        lambda service: service.train_now(_request(), _panel()),
        lambda service: service.submit_code("code", "", _panel()),
        lambda service: service.train_now_code("code", "", _panel()),
    ],
)
def test_governed_public_training_seams_reject_missing_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invoke,
) -> None:
    service, governance = _service(tmp_path, monkeypatch)

    with pytest.raises(
        ValueError,
        match="owner_user_id is required for training model identity",
    ):
        invoke(service)

    assert service.list_jobs() == []
    assert not governance.path.exists()


def test_schema_baseline_and_governance_writes_do_not_cross_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, governance = _service(tmp_path, monkeypatch)

    alice = service.train_now(
        _request(["f1", "f2"]),
        _panel(["f1", "f2"]),
        owner_user_id="alice",
    )
    bob = service.train_now(
        _request(["f1", "f2", "f3"]),
        _panel(["f1", "f2", "f3"]),
        owner_user_id="bob",
    )
    alice_passport = governance.passports(owner_user_id="alice")[0]
    bob_passport = governance.passports(owner_user_id="bob")[0]
    alice_next_fingerprint = compute_dataset_schema(
        _panel(["f1", "f2", "f3"]),
        ["f1", "f2", "f3"],
        "label",
    ).fingerprint
    alice_change_ref = schema_change_event_ref(
        "model_type_card:ridge",
        alice_passport.dataset_schema_fingerprint,
        alice_next_fingerprint,
    )
    governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=bob_passport.model_version_ref,
            model_passport_ref=bob_passport.passport_id,
            trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
            change_event_ref=alice_change_ref,
            evidence_refs=("validation_dossier:bob-only",),
            decision="accepted",
            recorded_by="bob-reviewer",
            owner_user_id="bob",
        ),
        owner_user_id="bob",
        recorded_by="bob-reviewer",
    )
    alice_changed = service.train_now(
        _request(["f1", "f2", "f3"]),
        _panel(["f1", "f2", "f3"]),
        owner_user_id="alice",
    )

    assert alice.status == "succeeded", alice.error
    assert bob.status == "succeeded", bob.error
    assert alice_changed.status == "failed"
    assert alice_changed.error.startswith("DataSchemaRecertificationRequired")
    assert len(governance.passports(owner_user_id="alice")) == 1
    assert len(governance.passports(owner_user_id="bob")) == 1
    assert all(
        record.owner_user_id == "alice"
        for record in governance.artifact_inspections(owner_user_id="alice")
    )
    assert all(
        record.owner_user_id == "bob"
        for record in governance.artifact_inspections(owner_user_id="bob")
    )


def test_async_submit_preserves_owner_through_governance_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, governance = _service(tmp_path, monkeypatch)

    queued = service.submit(
        _request(),
        _panel(),
        owner_user_id="async-owner",
    )
    service.wait_all(timeout=10)
    finished = service.get_job(queued.job_id)

    assert finished.status == "succeeded", finished.error
    passport = governance.passport(
        finished.model_passport_ref,
        owner_user_id="async-owner",
    )
    assert passport.owner_user_id == "async-owner"
    assert passport.recorded_by == "training_service"


def test_ungoverned_execution_still_requires_stable_model_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TrainingService(root=tmp_path / "training_runs")

    def fake_result(_request, _code, _panel, job_dir: Path):
        artifact = job_dir / "model.pkl"
        artifact.write_bytes(b"ungoverned-model-artifact")
        return {
            "oos_metrics": {"r2": 0.1},
            "fold_metrics": [],
            "artifact_path": str(artifact),
        }

    monkeypatch.setattr(service, "_resolve_result", fake_result)
    monkeypatch.setattr(
        training_service_module,
        "inspect_artifact_in_subprocess",
        lambda _artifact_path, *, expected_hash: {
            "inspection_ref": "artifact_inspection:ungoverned:v1",
            "inspection_mode": "metadata_only_no_deserialize",
            "inspector_ref": "training_artifact_inspector:v1",
            "checks": ["content_hash"],
            "limitations": [],
            "artifact_hash": expected_hash,
        },
    )

    job = service.train_now(
        _request(),
        _panel(),
        owner_user_id="ungoverned-owner",
    )

    assert job.status == "succeeded", job.error
