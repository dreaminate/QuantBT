"""训练台执行层 TrainingService + emit 协议测试（ML 路径，torch 无关）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.training import TrainingRequest, TrainingService, format_emit, parse_emit


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
    job = svc.train_now(_req(), _panel())
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
    job = svc.train_now(_req(name="lineage-run"), _panel())
    assert job.experiment_id and job.run_id
    run = svc._runs.get_run(job.run_id)
    assert run.status == "succeeded"
    assert run.tags.get("kind") == "training"
    versions = svc._models.list_versions("xgboost")
    assert len(versions) >= 1
    assert versions[-1].source_run_id == job.run_id


def test_train_now_classification(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.train_now(
        _req(task="classification", label_col="label_cls", cv_scheme="purged_kfold"),
        _panel(),
    )
    assert job.status == "succeeded"
    assert "accuracy" in job.metrics


# ───────────────── 异步提交 ─────────────────


def test_submit_async_completes(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    job = svc.submit(_req(), _panel())
    assert job.status in ("queued", "running")
    svc.wait_all(timeout=60)
    final = svc.get_job(job.job_id)
    assert final.status == "succeeded"
    assert final.job_id in {j.job_id for j in svc.list_jobs()}


# ───────────────── 校验 & 失败兜底 ─────────────────


def test_unknown_model_rejected(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        _svc(tmp_path).train_now(_req(model="does_not_exist"), _panel())


def test_unsupported_task_rejected(tmp_path: Path) -> None:
    # xgboost 不支持 lambdarank（catalog 已收敛）
    with pytest.raises(ValueError, match="不支持任务"):
        _svc(tmp_path).train_now(_req(task="lambdarank"), _panel())


def test_empty_features_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="feature_cols"):
        _svc(tmp_path).train_now(_req(feature_cols=[]), _panel())


def test_failed_training_marks_job_not_raises(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    # label 列不存在 → train_model 内部抛错 → job 落 failed，不冒泡
    bad = _panel().drop(columns=["label"])
    job = svc.train_now(_req(), bad)
    assert job.status == "failed"
    assert job.error
    # 失败的 run 也落 M12
    if job.run_id:
        assert svc._runs.get_run(job.run_id).status == "failed"
