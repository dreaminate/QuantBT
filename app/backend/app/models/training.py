"""M6 · 模型训练 orchestrator。

最小可用版本（默认走 LightGBM；可降级到 sklearn）：
- `train_model(spec)` 接受 ModelSpec → 走 purged k-fold 或 walk-forward → 返回 TrainResult
- 内置任务：classification / regression / lambdarank
- 输出 OOS metrics + per-fold metrics + model artifact (joblib pickle) + feature importance
"""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    log_loss,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

from .purged_cv import FoldSplit, purged_kfold, walk_forward


TaskType = Literal["classification", "regression", "lambdarank"]
CVScheme = Literal["purged_kfold", "walk_forward"]
ModelKind = Literal["lgbm", "sklearn_logreg", "sklearn_rf"]


@dataclass
class ModelSpec:
    task: TaskType
    model: ModelKind = "lgbm"
    feature_cols: list[str] = field(default_factory=list)
    label_col: str = "label"
    cv_scheme: CVScheme = "purged_kfold"
    n_splits: int = 5
    embargo_pct: float = 0.01
    walk_forward_train: int = 252
    walk_forward_test: int = 63
    walk_forward_embargo: int = 5
    hyperparams: dict[str, Any] = field(default_factory=dict)
    group_col: str | None = None  # for lambdarank


@dataclass
class FoldMetrics:
    fold_index: int
    n_train: int
    n_test: int
    metrics: dict[str, float]


@dataclass
class TrainResult:
    spec: dict[str, Any]
    oos_metrics: dict[str, float]
    fold_metrics: list[dict[str, Any]]
    feature_importance: dict[str, float] | None
    artifact_path: str | None
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_artifact(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _make_model(spec: ModelSpec, n_train: int) -> Any:
    import lightgbm as lgb
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LogisticRegression

    params = dict(spec.hyperparams)
    if spec.model == "lgbm":
        if spec.task == "classification":
            return lgb.LGBMClassifier(**{"verbose": -1, "n_estimators": 100, **params})
        if spec.task == "regression":
            return lgb.LGBMRegressor(**{"verbose": -1, "n_estimators": 100, **params})
        if spec.task == "lambdarank":
            return lgb.LGBMRanker(**{"verbose": -1, "n_estimators": 100, **params})
    if spec.model == "sklearn_logreg":
        return LogisticRegression(max_iter=300, **params)
    if spec.model == "sklearn_rf":
        if spec.task == "classification":
            return RandomForestClassifier(n_estimators=100, **params)
        return RandomForestRegressor(n_estimators=100, **params)
    raise ValueError(f"未知模型/任务组合: {spec.model}/{spec.task}")


def _evaluate_split(
    spec: ModelSpec,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray | None,
) -> dict[str, float]:
    out: dict[str, float] = {}
    if spec.task == "classification":
        out["accuracy"] = float(accuracy_score(y_true, y_pred))
        if y_proba is not None and len(np.unique(y_true)) == 2:
            try:
                out["roc_auc"] = float(roc_auc_score(y_true, y_proba))
                out["log_loss"] = float(log_loss(y_true, y_proba))
            except ValueError:
                pass
    else:
        out["mse"] = float(mean_squared_error(y_true, y_pred))
        out["r2"] = float(r2_score(y_true, y_pred))
        # Sharpe-like 指标：把 y_pred 当作信号 vs y_true 当作 forward return
        if y_pred.std() > 0:
            signal = (y_pred - y_pred.mean()) / y_pred.std()
            ret = (signal * y_true).mean()
            sd = (signal * y_true).std()
            out["sharpe_proxy"] = float(ret / sd * np.sqrt(252)) if sd > 0 else 0.0
    return out


def train_model(
    spec: ModelSpec,
    panel: pd.DataFrame,
    artifact_dir: Path | None = None,
) -> TrainResult:
    """端到端训练：panel 必须含 spec.feature_cols + label_col + 时间索引（按 ts 排序）。"""

    if not spec.feature_cols:
        raise ValueError("ModelSpec.feature_cols 不能为空")
    df = panel.copy()
    df = df.sort_values("ts").reset_index(drop=True)
    # 用 DataFrame 而非 .values 传给 LGBM，消除 "X does not have valid feature names" warning
    X = df[spec.feature_cols]
    y = df[spec.label_col].values
    times = df["ts"]
    splitter = list(_split_iter(spec, n_samples=len(df), times=times))
    if not splitter:
        raise ValueError("无可用的 CV split（数据量太小或参数过严）")
    t0 = time.perf_counter()
    folds: list[FoldMetrics] = []
    accumulated_pred: list[np.ndarray] = []
    accumulated_true: list[np.ndarray] = []
    feature_imp_sum: np.ndarray | None = None
    last_model: Any = None
    for split in splitter:
        model = _make_model(spec, len(split.train_idx))
        fit_kwargs: dict[str, Any] = {}
        if spec.task == "lambdarank" and spec.group_col and spec.group_col in df.columns:
            group_train = df.iloc[split.train_idx].groupby(spec.group_col).size().tolist()
            fit_kwargs["group"] = group_train
        X_train = X.iloc[split.train_idx]
        X_test = X.iloc[split.test_idx]
        model.fit(X_train, y[split.train_idx], **fit_kwargs)
        if spec.task == "classification":
            y_pred = model.predict(X_test)
            y_proba = (
                model.predict_proba(X_test)[:, 1]
                if hasattr(model, "predict_proba")
                else None
            )
        else:
            y_pred = model.predict(X_test)
            y_proba = None
        metrics = _evaluate_split(spec, y[split.test_idx], y_pred, y_proba)
        folds.append(FoldMetrics(split.fold_index, len(split.train_idx), len(split.test_idx), metrics))
        accumulated_pred.append(y_pred)
        accumulated_true.append(y[split.test_idx])
        if hasattr(model, "feature_importances_"):
            imps = np.asarray(model.feature_importances_, dtype=float)
            feature_imp_sum = imps if feature_imp_sum is None else feature_imp_sum + imps
        last_model = model
    oos_pred = np.concatenate(accumulated_pred)
    oos_true = np.concatenate(accumulated_true)
    oos_metrics = _evaluate_split(spec, oos_true, oos_pred, None)
    feature_importance = None
    if feature_imp_sum is not None:
        averaged = feature_imp_sum / max(len(folds), 1)
        feature_importance = dict(zip(spec.feature_cols, averaged.tolist()))
    artifact_path: str | None = None
    if artifact_dir is not None and last_model is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        target = artifact_dir / "model.pkl"
        with target.open("wb") as fh:
            pickle.dump(last_model, fh)
        artifact_path = str(target)
    return TrainResult(
        spec=asdict(spec),
        oos_metrics=oos_metrics,
        fold_metrics=[asdict(f) for f in folds],
        feature_importance=feature_importance,
        artifact_path=artifact_path,
        elapsed_seconds=time.perf_counter() - t0,
    )


def _split_iter(spec: ModelSpec, n_samples: int, times: pd.Series):
    if spec.cv_scheme == "purged_kfold":
        return purged_kfold(times, n_splits=spec.n_splits, embargo_pct=spec.embargo_pct)
    if spec.cv_scheme == "walk_forward":
        return walk_forward(
            n_samples=n_samples,
            train_size=spec.walk_forward_train,
            test_size=spec.walk_forward_test,
            embargo=spec.walk_forward_embargo,
        )
    raise ValueError(f"未知 cv_scheme: {spec.cv_scheme}")


__all__ = ["FoldMetrics", "ModelSpec", "TrainResult", "train_model"]
