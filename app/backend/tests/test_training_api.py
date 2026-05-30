"""模型中心 · 训练台 REST 端点测试（TestClient）。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_training_models_endpoint() -> None:
    r = client.get("/api/training/models")
    assert r.status_code == 200
    cards = r.json()
    keys = {c["key"] for c in cards}
    assert {"lgbm", "xgboost", "tft", "lstm"} <= keys
    xgb = next(c for c in cards if c["key"] == "xgboost")
    assert xgb["family"] == "ml"
    assert "param_schema" in xgb and "available" in xgb


def test_training_datasets_endpoint() -> None:
    r = client.get("/api/training/datasets")
    assert r.status_code == 200
    ds = r.json()
    assert any(d["dataset_id"] == "demo_ashare_xsec" for d in ds)
    assert all("feature_cols" in d for d in ds)


def test_training_codegen_preview() -> None:
    r = client.post(
        "/api/training/codegen",
        json={"model": "xgboost", "task": "regression", "feature_cols": ["f_mom5"], "label_col": "label"},
    )
    assert r.status_code == 200
    code = r.json()["code"]
    assert "train_model" in code and "emit" in code


def test_training_codegen_tft_now_runnable() -> None:
    # TFT 纯 torch 模板已落地 → codegen 生成 train_dl 代码
    r = client.post(
        "/api/training/codegen",
        json={"model": "tft", "task": "regression", "feature_cols": ["f_mom5"]},
    )
    assert r.status_code == 200
    assert "arch='tft'" in r.json()["code"]


def test_training_submit_and_poll_succeeds() -> None:
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "api-xgb",
            "model": "xgboost",
            "task": "regression",
            "dataset_id": "demo_ashare_xsec",
            "feature_cols": ["f_mom5", "f_mom20", "f_vol20", "f_value"],
            "label_col": "label",
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    final = None
    for _ in range(60):
        jr = client.get(f"/api/training/jobs/{job_id}")
        assert jr.status_code == 200
        final = jr.json()
        if final["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert final and final["status"] == "succeeded", final
    assert "r2" in final["metrics"]
    assert job_id in {j["job_id"] for j in client.get("/api/training/jobs").json()}


def test_training_model_detail_has_body() -> None:
    r = client.get("/api/training/models/lstm")
    assert r.status_code == 200
    assert "## L1" in r.json()["body"]
    assert client.get("/api/training/models/nope").status_code == 404


def test_training_agent_context_endpoint() -> None:
    r = client.get("/api/training/agent_context")
    assert r.status_code == 200
    assert "只能" in r.json()["system_prompt"]


def test_training_add_model_roundtrip() -> None:
    from app.models.card_loader import DEFAULT_CARDS_DIR
    from app.models.catalog import reload_catalog

    key = "api_test_tabnet"
    path = DEFAULT_CARDS_DIR / f"{key}.md"
    if path.exists():  # 防御：上次被 kill 的 run 可能留下残卡 → 先清，保证幂等
        path.unlink()
        reload_catalog()
    try:
        r = client.post(
            "/api/training/models",
            json={"key": key, "family": "dl", "display_name": "TabNet(测试)", "tasks": ["regression"], "description": "agent 搜来的新模型"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["runnable"] is False
        assert key in {c["key"] for c in client.get("/api/training/models").json()}
    finally:
        if path.exists():
            path.unlink()
        reload_catalog()


def test_training_submit_bad_dataset() -> None:
    r = client.post(
        "/api/training/jobs",
        json={"model": "xgboost", "task": "regression", "dataset_id": "nope", "feature_cols": ["f_mom5"]},
    )
    assert r.status_code == 400
