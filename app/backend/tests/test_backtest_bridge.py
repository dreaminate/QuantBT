"""训练台产物 → 回测 兼容性测试。

验证"训练台训出来的模型能不能在回测里用"：
- ML(.pkl) 与 DL(.pt) 模型都能经 backtest_job 跑出 equity/metrics
- scores_to_weights 的 top-N / long-short / NaN warmup 行为
- REST POST /api/training/jobs/{id}/backtest 端到端
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.training import TrainingRequest, TrainingService
from app.training.backtest_bridge import backtest_job, backtest_trained_model, scores_to_weights
from app.training.datasets import FEATURES, load_training_panel

client = TestClient(app)


# ─────────── scores_to_weights ───────────

def test_scores_to_weights_top_n_long_only() -> None:
    ts = pd.date_range("2024-01-01", periods=2, freq="D")
    scores = pd.DataFrame(
        [[0.5, 0.1, 0.9, 0.3], [0.2, 0.8, 0.4, 0.6]],
        index=ts, columns=["A", "B", "C", "D"],
    )
    w = scores_to_weights(scores, top_n=2, long_short=False)
    assert w.loc[ts[0], "C"] == pytest.approx(0.5)  # top-2 = C(0.9), A(0.5)
    assert w.loc[ts[0], "A"] == pytest.approx(0.5)
    assert w.loc[ts[0], "B"] == 0.0
    assert w.sum(axis=1).round(6).eq(1.0).all()


def test_scores_to_weights_long_short() -> None:
    ts = pd.date_range("2024-01-01", periods=1, freq="D")
    scores = pd.DataFrame([[0.9, 0.5, 0.1, 0.3]], index=ts, columns=["A", "B", "C", "D"])
    w = scores_to_weights(scores, top_n=1, long_short=True)
    assert w.loc[ts[0], "A"] > 0  # 多最高分
    assert w.loc[ts[0], "C"] < 0  # 空最低分
    assert w.sum(axis=1).round(6).eq(0.0).all()  # 多空中性


def test_scores_to_weights_nan_rows_zero() -> None:
    ts = pd.date_range("2024-01-01", periods=2, freq="D")
    scores = pd.DataFrame([[np.nan, np.nan], [0.5, 0.2]], index=ts, columns=["A", "B"])
    w = scores_to_weights(scores, top_n=1)
    assert (w.loc[ts[0]] == 0.0).all()  # 全 NaN 行 → 空仓，不报错


# ─────────── ML 模型 → 回测 ───────────

def test_backtest_ml_model(tmp_path: Path) -> None:
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")
    job = svc.train_now(
        TrainingRequest(
            name="bt-xgb", model="xgboost", task="regression",
            feature_cols=FEATURES, label_col="label", n_splits=4,
            hyperparams={"n_estimators": 40, "max_depth": 3},
        ),
        panel,
    )
    assert job.status == "succeeded", job.error
    result = backtest_job(job.artifact_dir, panel, feature_cols=FEATURES)
    assert len(result["equity_curve"]) > 0
    assert "sharpe" in result["metrics"]
    assert float(result["equity_curve"].iloc[-1]) > 0  # 净值为正


# ─────────── DL 模型(.pt) → 回测 ───────────

def test_backtest_dl_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("torch")
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")
    job = svc.train_now(
        TrainingRequest(
            name="bt-lstm", model="lstm", task="regression",
            feature_cols=FEATURES, label_col="label", symbol_col="symbol",
            hyperparams={"max_epochs": 2, "lookback": 8, "hidden_size": 8, "batch_size": 32},
        ),
        panel,
    )
    assert job.status == "succeeded", job.error
    # .pt 模型经 predict_with 跑回测（warmup 行 NaN → 该日空仓，不应崩）
    result = backtest_job(job.artifact_dir, panel, feature_cols=FEATURES, symbol_col="symbol")
    assert len(result["equity_curve"]) > 0
    assert float(result["equity_curve"].iloc[-1]) > 0


def test_backtest_missing_price_col_raises(tmp_path: Path) -> None:
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")
    job = svc.train_now(
        TrainingRequest(name="m", model="lgbm", task="regression", feature_cols=FEATURES, label_col="label", n_splits=4),
        panel,
    )
    with pytest.raises(ValueError, match="缺列"):
        backtest_trained_model(
            Path(job.artifact_dir) / "model.pkl",
            panel.drop(columns=["close"]),
            feature_cols=FEATURES,
        )


# ─────────── REST 端到端 ───────────

def test_backtest_endpoint(tmp_path: Path) -> None:
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "bt-api", "model": "xgboost", "task": "regression",
            "dataset_id": "demo_ashare_xsec",
            "feature_cols": FEATURES, "label_col": "label",
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    job_id = r.json()["job_id"]
    for _ in range(120):
        if client.get(f"/api/training/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    bt = client.post(f"/api/training/jobs/{job_id}/backtest", json={"top_n": 5})
    assert bt.status_code == 200, bt.text
    body = bt.json()
    assert body["job_id"] == job_id
    assert "sharpe" in body["metrics"]
    assert isinstance(body["equity_curve"], list) and len(body["equity_curve"]) > 0


def test_backtest_endpoint_unknown_job() -> None:
    assert client.post("/api/training/jobs/nope/backtest").status_code == 404


# ─────────── OOS（样本外）回测 ───────────

def test_oos_fraction_subsets_dates(tmp_path: Path) -> None:
    """oos_fraction=0.3 → 只回测末尾 ~30% 的交易日，n_days 显著小于全段。"""
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")  # 240 天
    job = svc.train_now(
        TrainingRequest(
            name="oos", model="xgboost", task="regression",
            feature_cols=FEATURES, label_col="label", n_splits=4,
            hyperparams={"n_estimators": 40, "max_depth": 3},
        ),
        panel,
    )
    full = backtest_job(job.artifact_dir, panel, feature_cols=FEATURES)
    oos = backtest_job(job.artifact_dir, panel, feature_cols=FEATURES, oos_fraction=0.3)
    assert oos["n_days"] < full["n_days"]
    assert oos["n_days"] == pytest.approx(240 * 0.3, abs=3)
    assert oos["oos_cutoff"] is not None


def test_oos_fraction_validation(tmp_path: Path) -> None:
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")
    job = svc.train_now(
        TrainingRequest(name="m", model="lgbm", task="regression", feature_cols=FEATURES, label_col="label", n_splits=4),
        panel,
    )
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="oos_fraction"):
            backtest_job(job.artifact_dir, panel, feature_cols=FEATURES, oos_fraction=bad)


def test_cross_dataset_oos_feature_compat() -> None:
    """跨数据集 OOS：两个内置 demo 用同一套 FEATURES，可互相做样本外。"""
    a = load_training_panel("demo_ashare_xsec")
    b = load_training_panel("demo_crypto_ts")
    assert set(FEATURES) <= set(a.columns) and set(FEATURES) <= set(b.columns)


def test_backtest_feature_mismatch_raises(tmp_path: Path) -> None:
    """回测数据集缺模型所需特征列 → 明确报错（而非 predict 崩）。"""
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")
    job = svc.train_now(
        TrainingRequest(name="m", model="lgbm", task="regression", feature_cols=FEATURES, label_col="label", n_splits=4),
        panel,
    )
    with pytest.raises(ValueError, match="缺模型所需特征列"):
        backtest_job(job.artifact_dir, panel.drop(columns=[FEATURES[0]]), feature_cols=FEATURES)


def test_endpoint_oos_cross_dataset(tmp_path: Path) -> None:
    """REST：训于 A股 demo，回测换到 crypto demo → is_cross_dataset=True, is_oos=True。"""
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "oos-api", "model": "xgboost", "task": "regression",
            "dataset_id": "demo_ashare_xsec", "feature_cols": FEATURES, "label_col": "label",
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    job_id = r.json()["job_id"]
    for _ in range(120):
        if client.get(f"/api/training/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    bt = client.post(f"/api/training/jobs/{job_id}/backtest", json={"dataset_id": "demo_crypto_ts", "top_n": 3})
    assert bt.status_code == 200, bt.text
    body = bt.json()
    assert body["is_cross_dataset"] is True
    assert body["is_oos"] is True
    assert body["dataset_id"] == "demo_crypto_ts"
    assert body["train_dataset"] == "demo_ashare_xsec"


def test_endpoint_oos_fraction(tmp_path: Path) -> None:
    """REST：同数据集 + oos_fraction → is_oos=True, oos_cutoff 非空。"""
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "oosf-api", "model": "xgboost", "task": "regression",
            "dataset_id": "demo_ashare_xsec", "feature_cols": FEATURES, "label_col": "label",
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    job_id = r.json()["job_id"]
    for _ in range(120):
        if client.get(f"/api/training/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    bt = client.post(f"/api/training/jobs/{job_id}/backtest", json={"oos_fraction": 0.3})
    assert bt.status_code == 200, bt.text
    body = bt.json()
    assert body["is_oos"] is True
    assert body["oos_cutoff"] is not None
    assert body["n_days"] < 240


# ─────────── 严格无泄露 walk-forward（train 前段 / OOS 后段互补）───────────

def test_slice_front_dates_keeps_front_only() -> None:
    """_slice_front_dates(train_fraction=0.7) 只保留前 70% 交易日，与后段零重叠。"""
    from app.training.service import _slice_front_dates

    panel = load_training_panel("demo_ashare_xsec")  # 240 天
    all_dates = set(panel["ts"].unique())
    front = _slice_front_dates(panel, "ts", 0.7)
    front_dates = set(front["ts"].unique())
    back_dates = all_dates - front_dates
    assert len(front_dates) == pytest.approx(240 * 0.7, abs=2)
    assert max(front_dates) < min(back_dates)  # 严格时间切分，无交叠


def test_slice_front_dates_validation() -> None:
    from app.training.service import _slice_front_dates

    panel = load_training_panel("demo_ashare_xsec")
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="train_fraction"):
            _slice_front_dates(panel, "ts", bad)


def test_strict_walkforward_zero_leakage(tmp_path: Path) -> None:
    """训练只用前 70% 交易日 → 训练日期与回测后 30% 日期零重叠（无泄露）。"""
    from app.training.service import _slice_front_dates

    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    panel = load_training_panel("demo_ashare_xsec")
    job = svc.train_now(
        TrainingRequest(
            name="wf", model="xgboost", task="regression",
            feature_cols=FEATURES, label_col="label", n_splits=4,
            train_fraction=0.7,
            hyperparams={"n_estimators": 40, "max_depth": 3},
        ),
        panel,
    )
    assert job.status == "succeeded", job.error
    train_dates = set(_slice_front_dates(panel, "ts", 0.7)["ts"].unique())
    oos = backtest_job(job.artifact_dir, panel, feature_cols=FEATURES, oos_fraction=0.3)
    assert oos["oos_cutoff"] is not None
    assert pd.Timestamp(oos["oos_cutoff"]) > pd.Timestamp(max(train_dates))  # 零重叠


def test_endpoint_strict_oos_autopairs(tmp_path: Path) -> None:
    """REST：train_fraction=0.7 训练后，回测不传 oos_fraction → 自动后 30%，strict_oos=True。"""
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "wf-api", "model": "xgboost", "task": "regression",
            "dataset_id": "demo_ashare_xsec", "feature_cols": FEATURES, "label_col": "label",
            "train_fraction": 0.7,
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    job_id = r.json()["job_id"]
    for _ in range(120):
        if client.get(f"/api/training/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    bt = client.post(f"/api/training/jobs/{job_id}/backtest", json={"top_n": 5})  # 不传 oos_fraction
    assert bt.status_code == 200, bt.text
    body = bt.json()
    assert body["strict_oos"] is True
    assert body["is_oos"] is True
    assert body["train_fraction"] == 0.7
    assert body["oos_cutoff"] is not None
    assert body["n_days"] == pytest.approx(240 * 0.3, abs=4)
