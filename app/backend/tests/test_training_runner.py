"""训练台核心 · 代码 runner + codegen + 模型组合 + DL(真 torch 子进程)测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.training import (
    TrainingRequest,
    TrainingService,
    predict_with,
    run_code,
    spec_to_code,
)


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
        }
    )


def _svc(tmp_path: Path) -> TrainingService:
    return TrainingService(root=tmp_path / "training_runs", timeout=300)


# ───────────────── run_code（全功率进程） ─────────────────


def test_run_code_emit_roundtrip(tmp_path: Path) -> None:
    code = (
        "from app.training.lib import emit\n"
        "emit({'oos_metrics': {'r2': 0.42}, 'artifact_path': None})\n"
    )
    res = run_code(code, tmp_path / "job", timeout=120)
    assert res.ok
    assert res.emit["oos_metrics"]["r2"] == 0.42


def test_run_code_failure_captured(tmp_path: Path) -> None:
    res = run_code("raise RuntimeError('boom')\n", tmp_path / "job", timeout=120)
    assert not res.ok
    assert res.returncode != 0
    assert "boom" in res.stderr


def test_run_code_can_pick_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    code = (
        "from app.training.lib import emit, pick_device\n"
        "emit({'oos_metrics': {}, 'device': pick_device()})\n"
    )
    res = run_code(code, tmp_path / "job", timeout=120)
    assert res.ok
    assert res.emit["device"] == "cpu"


# ───────────────── codegen：ML 也能当代码跑 ─────────────────


def test_codegen_ml_runs_as_process(tmp_path: Path) -> None:
    spec = {
        "model": "xgboost",
        "task": "regression",
        "feature_cols": ["f1", "f2"],
        "label_col": "label",
        "n_splits": 4,
        "hyperparams": {"n_estimators": 50, "max_depth": 3},
    }
    code = spec_to_code(spec)
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    _panel().to_parquet(job_dir / "panel.parquet")
    res = run_code(
        code, job_dir, env_extra={"QUANTBT_PANEL_PATH": str(job_dir / "panel.parquet")}, timeout=300
    )
    assert res.ok, res.stderr[-800:]
    assert "r2" in res.emit["oos_metrics"]
    assert (job_dir / "model.pkl").exists()


# ───────────────── 自由代码任务（service） ─────────────────


def test_service_code_path_succeeds(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    code = (
        "import os, pandas as pd\n"
        "from app.training.lib import emit\n"
        "panel = pd.read_parquet(os.environ['QUANTBT_PANEL_PATH'])\n"
        "emit({'oos_metrics': {'rows': float(len(panel))}, 'artifact_path': None})\n"
    )
    job = svc.train_now_code("custom", code, _panel())
    assert job.status == "succeeded", job.error
    assert job.family == "code"
    assert job.metrics["rows"] == 360.0
    assert job.run_id and job.experiment_id


# ───────────────── 模型组合：输出 → 输入 ─────────────────


def test_predict_with_then_feed_as_feature(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    # 训 A（xgboost），拿到 artifact
    a = svc.train_now(
        TrainingRequest(
            name="A",
            model="xgboost",
            task="regression",
            feature_cols=["f1", "f2"],
            n_splits=4,
            hyperparams={"n_estimators": 40},
        ),
        _panel(),
    )
    artifact = str(Path(a.artifact_dir) / "model.pkl")
    panel = _panel()
    preds = predict_with(artifact, panel, ["f1", "f2"])
    assert len(preds) == len(panel)
    assert np.isfinite(preds).all()


def test_service_input_models_composition(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    a = svc.train_now(
        TrainingRequest(
            name="A",
            model="xgboost",
            task="regression",
            feature_cols=["f1", "f2"],
            n_splits=4,
            hyperparams={"n_estimators": 40},
        ),
        _panel(),
    )
    artifact = str(Path(a.artifact_dir) / "model.pkl")
    # 训 B（lgbm），把 A 的输出当输入特征
    b = svc.train_now(
        TrainingRequest(
            name="B",
            model="lgbm",
            task="regression",
            feature_cols=["f1", "f2"],
            n_splits=4,
            input_models=[{"artifact_path": artifact, "feature_cols": ["f1", "f2"], "as_col": "a_pred"}],
        ),
        _panel(),
    )
    assert b.status == "succeeded", b.error
    result = json.loads((Path(b.artifact_dir) / "result.json").read_text(encoding="utf-8"))
    # B 确实用到了 A 的输出列
    assert "a_pred" in result["feature_importance"]


# ───────────────── DL：真 torch LSTM 子进程 ─────────────────


def test_service_dl_lstm_trains_in_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("torch")
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")  # CI 稳定，避 MPS flaky
    svc = _svc(tmp_path)
    job = svc.train_now(
        TrainingRequest(
            name="lstm-demo",
            model="lstm",
            task="regression",
            feature_cols=["f1", "f2"],
            label_col="label",
            hyperparams={
                "max_epochs": 3,
                "lookback": 10,
                "hidden_size": 8,
                "batch_size": 32,
            },
        ),
        _panel(400),
    )
    assert job.status == "succeeded", job.error
    assert job.family == "dl"
    result = json.loads((Path(job.artifact_dir) / "result.json").read_text(encoding="utf-8"))
    assert len(result["curves"]["train_loss"]) == 3  # 学习曲线
    assert len(result["curves"]["val_loss"]) == 3
    assert result["device"] == "cpu"
    assert "r2" in result["oos_metrics"]
    assert (Path(job.artifact_dir) / "model.pt").exists()  # checkpoint
