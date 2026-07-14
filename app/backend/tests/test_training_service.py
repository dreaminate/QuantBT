"""训练台执行层 TrainingService + emit 协议测试（ML 路径，torch 无关）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.experiments.store import ModelRegistry
from app.research_os import PersistentModelGovernanceRegistry
from app.training import TrainingRequest, TrainingService, format_emit, parse_emit
from app.training.lib import load_model


_OWNER_USER_ID = "test-owner"


def _panel(n: int = 360, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    y = 0.6 * f1 - 0.4 * f2 + rng.normal(size=n, scale=0.3)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ts": [base + timedelta(days=i) for i in range(n)],
            "f1": f1,
            "f2": f2,
            "label": y,
            "label_cls": (y > 0).astype(int),
        }
    )


def _svc(tmp_path: Path) -> TrainingService:
    return TrainingService(root=tmp_path / "training_runs")


def _req(**kw) -> TrainingRequest:
    base = dict(
        name="t",
        model="xgboost",
        task="regression",
        feature_cols=["f1", "f2"],
        label_col="label",
        n_splits=4,
        hyperparams={"n_estimators": 60, "max_depth": 3},
    )
    base.update(kw)
    return TrainingRequest(**base)


# ───────────────── emit 协议 ─────────────────


def test_emit_roundtrip() -> None:
    payload = {"oos_metrics": {"r2": 0.5}, "curves": {"train_loss": [1.0, 0.5]}}
    line = format_emit(payload)
    assert parse_emit(f"noise\n{line}\nmore noise") == payload


def test_emit_takes_last_record() -> None:
    a = format_emit({"v": 1})
    b = format_emit({"v": 2})
    assert parse_emit(f"{a}\n{b}")["v"] == 2


def test_emit_none_when_absent() -> None:
    assert parse_emit("just\nlogs\n") is None


# ───────────────── ML 训练（同步） ─────────────────


def test_train_now_ml_succeeds_and_persists(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(_req(), _panel(), owner_user_id=_OWNER_USER_ID)
    assert job.status == "succeeded"
    assert job.family == "ml"
    assert "r2" in job.metrics
    assert job.elapsed_seconds is not None and job.elapsed_seconds >= 0
    # 产物落盘
    job_dir = Path(job.artifact_dir)
    assert (job_dir / "spec.json").exists()
    assert (job_dir / "result.json").exists()
    assert (job_dir / "model.pkl").exists()


def test_train_now_registers_m12_lineage(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(
        _req(name="lineage-run"),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert job.experiment_id and job.run_id
    run = svc._runs.get_run(job.run_id)
    assert run.status == "succeeded"
    assert run.tags.get("kind") == "training"
    versions = svc._models.list_versions("xgboost", owner_user_id=_OWNER_USER_ID)
    assert len(versions) >= 1
    assert versions[-1].source_run_id == job.run_id


def test_train_now_registers_model_passport_and_validation_dossier(tmp_path: Path) -> None:
    governance = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    model_registry = ModelRegistry(tmp_path / "experiments", model_governance_registry=governance)
    svc = TrainingService(
        root=tmp_path / "training_runs",
        model_registry=model_registry,
        model_governance_registry=governance,
    )

    job = svc.train_now(
        _req(name="governed-lineage", dataset_id="dataset:unit-test"),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )

    assert job.status == "succeeded"
    assert job.model_version is not None
    assert job.model_passport_ref
    assert job.validation_dossier_ref == f"validation_dossier:{job.job_id}"
    version = model_registry.list_versions("xgboost", owner_user_id=_OWNER_USER_ID)[-1]
    assert version.model_passport_ref == job.model_passport_ref
    assert version.validation_dossier_ref == job.validation_dossier_ref
    passport = governance.passport(
        job.model_passport_ref,
        owner_user_id=_OWNER_USER_ID,
    )
    assert passport.model_version_ref == f"model_version:xgboost:v{version.version}"
    assert passport.training_run_ref == f"training_run:{job.run_id}"
    assert passport.dataset_refs == ("dataset:unit-test",)
    dossier_path = Path(job.artifact_dir) / "validation_dossier.json"
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    assert dossier["validation_dossier_ref"] == job.validation_dossier_ref
    assert dossier["artifact_hash"].startswith("sha256:")
    assert dossier["artifact_inspection_ref"].startswith("artifact_inspection:")
    inspection_path = Path(job.artifact_dir) / "artifact_inspection.json"
    inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
    assert inspection["inspection_ref"] == dossier["artifact_inspection_ref"]
    assert inspection["process_isolation"] == "subprocess"
    assert inspection["inspection_mode"] == "metadata_only_no_deserialize"
    assert inspection["deserialize_executed"] is False
    assert governance.artifact_inspections(
        owner_user_id=_OWNER_USER_ID,
    )[0].inspection_ref == dossier["artifact_inspection_ref"]


def test_pickle_loader_rejects_artifact_without_validation_dossier(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(
        _req(name="loader-no-dossier"),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    artifact = Path(job.artifact_dir) / "model.pkl"
    (Path(job.artifact_dir) / "validation_dossier.json").unlink()

    with pytest.raises(ValueError, match="validation_dossier"):
        load_model(artifact)


def test_pickle_loader_rejects_artifact_hash_mismatch(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(
        _req(name="loader-hash-mismatch"),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    artifact_dir = Path(job.artifact_dir)
    dossier_path = artifact_dir / "validation_dossier.json"
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    dossier["artifact_hash"] = "sha256:bad"
    dossier_path.write_text(json.dumps(dossier), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact_hash"):
        load_model(artifact_dir / "model.pkl")


def test_pickle_loader_rejects_artifact_without_sandbox_inspection(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(
        _req(name="loader-no-inspection"),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    artifact_dir = Path(job.artifact_dir)
    (artifact_dir / "artifact_inspection.json").unlink()

    with pytest.raises(ValueError, match="artifact_inspection"):
        load_model(artifact_dir / "model.pkl")


def test_train_now_classification(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(
        _req(task="classification", label_col="label_cls", cv_scheme="purged_kfold"),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert job.status == "succeeded"
    assert "accuracy" in job.metrics


# ───────────────── 异步提交 ─────────────────


def test_submit_async_completes(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.submit(_req(), _panel(), owner_user_id=_OWNER_USER_ID)
    assert job.status in ("queued", "running")
    svc.wait_all(timeout=60)
    final = svc.get_job(job.job_id)
    assert final.status == "succeeded"
    assert final.job_id in {j.job_id for j in svc.list_jobs()}


# ───────────────── 校验 & 失败兜底 ─────────────────


def test_unknown_model_rejected(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        _svc(tmp_path).train_now(
            _req(model="does_not_exist"),
            _panel(),
            owner_user_id=_OWNER_USER_ID,
        )


def test_unsupported_task_rejected(tmp_path: Path) -> None:
    # xgboost 不支持 lambdarank（catalog 已收敛）
    with pytest.raises(ValueError, match="不支持任务"):
        _svc(tmp_path).train_now(
            _req(task="lambdarank"),
            _panel(),
            owner_user_id=_OWNER_USER_ID,
        )


def test_empty_features_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="feature_cols"):
        _svc(tmp_path).train_now(
            _req(feature_cols=[]),
            _panel(),
            owner_user_id=_OWNER_USER_ID,
        )


def test_failed_training_marks_job_not_raises(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    # label 列不存在 → train_model 内部抛错 → job 落 failed，不冒泡
    bad = _panel().drop(columns=["label"])
    job = svc.train_now(_req(), bad, owner_user_id=_OWNER_USER_ID)
    assert job.status == "failed"
    assert job.error
    # 失败的 run 也落 M12
    if job.run_id:
        assert svc._runs.get_run(job.run_id).status == "failed"
