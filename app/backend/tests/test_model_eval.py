"""训练评价图数据源 + REST 端点测试。"""

from __future__ import annotations

import time

import numpy as np
from fastapi.testclient import TestClient

from app.eval.model_eval import build_eval_charts, summarize_metrics
from app.main import app

client = TestClient(app)


def test_build_charts_regression() -> None:
    result = {
        "spec": {"task": "regression"},
        "oos_metrics": {"r2": 0.4, "mse": 0.1},
        "feature_importance": {"f1": 0.7, "f2": 0.3},
        "oos_predictions": {"y_true": list(range(20)), "y_pred": [x + 0.1 for x in range(20)]},
        "fold_metrics": [{"fold_index": 0, "metrics": {"r2": 0.3}}, {"fold_index": 1, "metrics": {"r2": 0.5}}],
        "curves": {},
    }
    charts = build_eval_charts(result)
    ids = {c["id"] for c in charts}
    assert "feature_importance" in ids
    assert "pred_vs_actual" in ids and "residual" in ids
    assert "fold_metrics" in ids
    fi = next(c for c in charts if c["id"] == "feature_importance")
    assert fi["kind"] == "bar" and fi["labels"][0] == "f1"  # 按重要度降序


def test_build_charts_classification_roc() -> None:
    rng = np.random.default_rng(0)
    n = 100
    y_true = (rng.random(n) > 0.5).astype(int).tolist()
    y_proba = [0.5 + 0.3 * (yt - 0.5) + rng.normal(0, 0.1) for yt in y_true]
    result = {
        "spec": {"task": "classification"},
        "oos_metrics": {"accuracy": 0.7},
        "oos_predictions": {"y_true": y_true, "y_pred": [int(p > 0.5) for p in y_proba], "y_proba": y_proba},
    }
    charts = build_eval_charts(result)
    roc = next((c for c in charts if c["id"] == "roc"), None)
    assert roc is not None and roc["kind"] == "line"
    assert "AUC=" in roc["title"]


def test_build_charts_dl_learning_curve() -> None:
    result = {
        "spec": {"task": "regression"},
        "oos_metrics": {"r2": 0.2},
        "curves": {"train_loss": [1.0, 0.5, 0.3], "val_loss": [1.1, 0.6, 0.4]},
        "oos_predictions": {"y_true": [1, 2, 3], "y_pred": [1.1, 1.9, 3.1]},
    }
    charts = build_eval_charts(result)
    lc = next(c for c in charts if c["id"] == "learning_curve")
    assert len(lc["series"]) == 2
    assert summarize_metrics(result) == {"r2": 0.2}


def test_build_charts_empty_result() -> None:
    assert build_eval_charts({}) == []


def test_eval_endpoint_after_training() -> None:
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "eval-xgb", "model": "xgboost", "task": "regression",
            "dataset_id": "demo_ashare_xsec",
            "feature_cols": ["f_mom5", "f_mom20", "f_vol20", "f_value"], "label_col": "label",
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    job_id = r.json()["job_id"]
    for _ in range(60):
        if client.get(f"/api/training/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    ev = client.get(f"/api/training/jobs/{job_id}/eval")
    assert ev.status_code == 200
    body = ev.json()
    assert body["status"] == "succeeded"
    ids = {c["id"] for c in body["charts"]}
    assert "feature_importance" in ids  # xgboost 有重要度
    assert "r2" in body["metrics"]


def test_eval_endpoint_unknown_job() -> None:
    assert client.get("/api/training/jobs/nope/eval").status_code == 404
