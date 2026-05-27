from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.models import (
    ModelSpec,
    purged_kfold,
    train_model,
    walk_forward,
)


def _synthetic_dataset(n: int = 500, seed: int = 0) -> pd.DataFrame:
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


def test_purged_kfold_no_overlap() -> None:
    times = pd.Series([datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(50)])
    splits = list(purged_kfold(times, n_splits=5, embargo_pct=0.02))
    assert len(splits) == 5
    for s in splits:
        assert len(set(s.train_idx).intersection(s.test_idx)) == 0


def test_walk_forward_yields_disjoint_test_windows() -> None:
    splits = list(walk_forward(n_samples=200, train_size=100, test_size=20, step=20))
    assert len(splits) >= 4
    test_sets = [set(s.test_idx.tolist()) for s in splits]
    for i in range(len(test_sets) - 1):
        assert not (test_sets[i] & test_sets[i + 1])


def test_train_regression_lgbm_returns_metrics(tmp_path: Path) -> None:
    df = _synthetic_dataset(400)
    spec = ModelSpec(
        task="regression",
        model="lgbm",
        feature_cols=["f1", "f2"],
        label_col="label_reg",
        cv_scheme="purged_kfold",
        n_splits=5,
    )
    result = train_model(spec, df, artifact_dir=tmp_path)
    assert "mse" in result.oos_metrics
    assert result.oos_metrics["r2"] > 0  # 信号有效
    assert len(result.fold_metrics) == 5
    assert result.artifact_path and Path(result.artifact_path).exists()


def test_train_classification_lgbm_returns_auc(tmp_path: Path) -> None:
    df = _synthetic_dataset(400)
    spec = ModelSpec(
        task="classification",
        model="lgbm",
        feature_cols=["f1", "f2"],
        label_col="label_cls",
        cv_scheme="walk_forward",
        walk_forward_train=150,
        walk_forward_test=50,
        walk_forward_embargo=5,
    )
    result = train_model(spec, df, artifact_dir=tmp_path)
    assert result.oos_metrics["accuracy"] > 0.55
    assert result.feature_importance is not None
    assert set(result.feature_importance.keys()) == {"f1", "f2"}


def test_train_with_sklearn_baseline(tmp_path: Path) -> None:
    df = _synthetic_dataset(300)
    spec = ModelSpec(
        task="classification",
        model="sklearn_logreg",
        feature_cols=["f1", "f2"],
        label_col="label_cls",
        cv_scheme="purged_kfold",
        n_splits=4,
    )
    result = train_model(spec, df, artifact_dir=tmp_path)
    assert result.oos_metrics["accuracy"] > 0.6
    assert result.artifact_path and Path(result.artifact_path).exists()


def test_empty_features_rejected() -> None:
    with pytest.raises(ValueError, match="feature_cols"):
        train_model(ModelSpec(task="regression", feature_cols=[]), pd.DataFrame())
