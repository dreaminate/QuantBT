"""M6+ 训练台 · 模型目录 catalog + XGBoost 接入测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.models import (
    MODEL_CATALOG,
    ModelSpec,
    get_model_card,
    list_model_cards,
    model_catalog_summary,
    train_model,
)
from app.models.catalog import is_dl_model


def _synthetic_dataset(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    noise = rng.normal(size=n, scale=0.3)
    y_reg = 0.6 * f1 - 0.4 * f2 + noise
    y_cls = (y_reg > 0).astype(int)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ts": [base + timedelta(days=i) for i in range(n)],
            "f1": f1,
            "f2": f2,
            "label_reg": y_reg,
            "label_cls": y_cls,
        }
    )


# ───────────────────────── catalog ─────────────────────────


def test_catalog_has_ml_and_dl_families() -> None:
    ml = {c.key for c in list_model_cards(family="ml")}
    dl = {c.key for c in list_model_cards(family="dl")}
    assert {"lgbm", "xgboost", "sklearn_logreg", "sklearn_rf"} <= ml
    assert {"tft", "lstm"} <= dl
    assert ml.isdisjoint(dl)


def test_catalog_dl_cards_need_torch_and_tensorboard() -> None:
    for key in ("tft", "lstm"):
        card = get_model_card(key)
        assert card.needs_dl is True
        assert card.tensorboard is True
        assert card.requires_import == "torch"
        assert is_dl_model(key) is True


def test_catalog_xgboost_is_available_ml_no_dl() -> None:
    card = get_model_card("xgboost")
    assert card.family == "ml"
    assert card.needs_dl is False
    assert card.is_available() is True  # xgboost 已装
    assert "lambdarank" not in card.tasks  # 排序留给 lgbm


def test_catalog_get_unknown_raises() -> None:
    with pytest.raises(KeyError, match="未知模型"):
        get_model_card("nope")


def test_catalog_summary_is_json_friendly() -> None:
    summary = model_catalog_summary()
    assert len(summary) == len(MODEL_CATALOG)
    sample = next(c for c in summary if c["key"] == "tft")
    assert isinstance(sample["tasks"], list)
    assert "available" in sample
    assert "param_schema" in sample and "max_epochs" in sample["param_schema"]


def test_catalog_filter_by_task() -> None:
    cls_models = {c.key for c in list_model_cards(task="classification")}
    assert "xgboost" in cls_models
    assert "sklearn_logreg" in cls_models
    # 回归专属不应出现在分类清单
    forecasting = {c.key for c in list_model_cards(task="forecasting")}
    assert "tft" in forecasting and "lgbm" not in forecasting


# ───────────────────────── xgboost 训练 ─────────────────────────


def test_train_regression_xgboost(tmp_path: Path) -> None:
    df = _synthetic_dataset(400)
    spec = ModelSpec(
        task="regression",
        model="xgboost",
        feature_cols=["f1", "f2"],
        label_col="label_reg",
        cv_scheme="purged_kfold",
        n_splits=5,
        hyperparams={"n_estimators": 80, "max_depth": 4},
    )
    result = train_model(spec, df, artifact_dir=tmp_path)
    assert "r2" in result.oos_metrics
    assert result.oos_metrics["r2"] > 0  # 信号有效
    assert len(result.fold_metrics) == 5
    assert result.feature_importance is not None
    assert set(result.feature_importance) == {"f1", "f2"}
    assert result.artifact_path and Path(result.artifact_path).exists()


def test_train_classification_xgboost(tmp_path: Path) -> None:
    df = _synthetic_dataset(400)
    spec = ModelSpec(
        task="classification",
        model="xgboost",
        feature_cols=["f1", "f2"],
        label_col="label_cls",
        cv_scheme="walk_forward",
        walk_forward_train=150,
        walk_forward_test=50,
        walk_forward_embargo=5,
        hyperparams={"n_estimators": 80, "max_depth": 4},
    )
    result = train_model(spec, df, artifact_dir=tmp_path)
    assert result.oos_metrics["accuracy"] > 0.55


def test_train_xgboost_is_deterministic(tmp_path: Path) -> None:
    df = _synthetic_dataset(300, seed=7)
    spec = ModelSpec(
        task="regression",
        model="xgboost",
        feature_cols=["f1", "f2"],
        label_col="label_reg",
        n_splits=4,
        hyperparams={"n_estimators": 60},
    )
    r1 = train_model(spec, df)
    r2 = train_model(spec, df)
    assert r1.oos_metrics["mse"] == pytest.approx(r2.oos_metrics["mse"], rel=1e-9)


def test_xgboost_lambdarank_rejected() -> None:
    df = _synthetic_dataset(120)
    spec = ModelSpec(
        task="lambdarank",
        model="xgboost",
        feature_cols=["f1", "f2"],
        label_col="label_cls",
        n_splits=3,
    )
    with pytest.raises(ValueError, match="lambdarank"):
        train_model(spec, df)
