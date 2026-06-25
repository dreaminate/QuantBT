"""M6 · 模型训练 orchestrator。

最小可用版本（默认走 LightGBM；可降级到 sklearn）：
- `train_model(spec)` 接受 ModelSpec → 走 purged k-fold 或 walk-forward → 返回 TrainResult
- 内置任务：classification / regression / lambdarank
- 输出 OOS metrics + per-fold metrics + model artifact (joblib pickle) + feature importance
"""

from __future__ import annotations

import json
import math
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

from .cpcv import assemble_cpcv_paths, cpcv_splits
from .purged_cv import FoldSplit, purged_kfold, walk_forward


TaskType = Literal["classification", "regression", "lambdarank"]
CVScheme = Literal["purged_kfold", "walk_forward"]
ModelKind = Literal[
    "lgbm",
    "xgboost",
    "catboost",
    "sklearn_logreg",
    "sklearn_rf",
    "extra_trees",
    "ridge",
    "lasso",
    "elastic_net",
]


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
    # OOS 拼接预测，供训练台评价图（ROC/PR/预测-实际散点/残差）。
    # {"y_true":[...], "y_pred":[...], "y_proba":[...]?}
    oos_predictions: dict[str, Any] | None = None
    # 学习曲线（DL 路径填 train/val loss；树模型一般为空）。
    curves: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_artifact(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _make_model(spec: ModelSpec, n_train: int) -> Any:
    import lightgbm as lgb
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        ExtraTreesRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
    )
    from sklearn.linear_model import ElasticNet, Lasso, LogisticRegression, Ridge

    params = dict(spec.hyperparams)
    if spec.model == "lgbm":
        if spec.task == "classification":
            return lgb.LGBMClassifier(**{"verbose": -1, "n_estimators": 100, **params})
        if spec.task == "regression":
            return lgb.LGBMRegressor(**{"verbose": -1, "n_estimators": 100, **params})
        if spec.task == "lambdarank":
            return lgb.LGBMRanker(**{"verbose": -1, "n_estimators": 100, **params})
    if spec.model == "xgboost":
        import xgboost as xgb

        # 固定 random_state + 单线程默认，保证 demo/CI 可复现
        base = {"n_estimators": 200, "random_state": 42, "n_jobs": 0, **params}
        if spec.task == "classification":
            return xgb.XGBClassifier(**base)
        if spec.task == "regression":
            return xgb.XGBRegressor(**base)
        # 排序任务暂不走 xgboost（group/qid 接口差异），由 lgbm 承担
        raise ValueError("xgboost 暂不支持 lambdarank，请用 model='lgbm'")
    if spec.model == "sklearn_logreg":
        return LogisticRegression(max_iter=300, **params)
    if spec.model == "sklearn_rf":
        if spec.task == "classification":
            return RandomForestClassifier(n_estimators=100, random_state=42, **params)
        return RandomForestRegressor(n_estimators=100, random_state=42, **params)
    if spec.model == "extra_trees":
        if spec.task == "classification":
            return ExtraTreesClassifier(n_estimators=200, random_state=42, **params)
        return ExtraTreesRegressor(n_estimators=200, random_state=42, **params)
    if spec.model == "catboost":
        from catboost import CatBoostClassifier, CatBoostRegressor

        base = {"iterations": 300, "random_seed": 42, "verbose": False, "allow_writing_files": False, **params}
        return (CatBoostClassifier if spec.task == "classification" else CatBoostRegressor)(**base)
    # 线性族（回归）：catalog 把它们的 tasks 限定为 regression
    if spec.model == "ridge":
        return Ridge(random_state=42, **params)
    if spec.model == "lasso":
        return Lasso(random_state=42, **params)
    if spec.model == "elastic_net":
        return ElasticNet(random_state=42, **params)
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
    accumulated_proba: list[np.ndarray | None] = []
    feature_imp_sum: np.ndarray | None = None
    last_model: Any = None
    for split in splitter:
        model, y_pred, y_proba = _fit_predict_fold(spec, df, X, y, split.train_idx, split.test_idx)
        metrics = _evaluate_split(spec, y[split.test_idx], y_pred, y_proba)
        folds.append(FoldMetrics(split.fold_index, len(split.train_idx), len(split.test_idx), metrics))
        accumulated_pred.append(y_pred)
        accumulated_true.append(y[split.test_idx])
        accumulated_proba.append(y_proba)
        if hasattr(model, "feature_importances_"):
            imps = np.asarray(model.feature_importances_, dtype=float)
            feature_imp_sum = imps if feature_imp_sum is None else feature_imp_sum + imps
        last_model = model
    oos_pred = np.concatenate(accumulated_pred)
    oos_true = np.concatenate(accumulated_true)
    oos_metrics = _evaluate_split(spec, oos_true, oos_pred, None)
    oos_predictions: dict[str, Any] = {
        "y_true": oos_true.tolist(),
        "y_pred": oos_pred.tolist(),
    }
    if accumulated_proba and all(p is not None for p in accumulated_proba):
        oos_predictions["y_proba"] = np.concatenate(accumulated_proba).tolist()  # type: ignore[arg-type]
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
        oos_predictions=oos_predictions,
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


def _fit_predict_fold(
    spec: ModelSpec,
    df: pd.DataFrame,
    X: pd.DataFrame,
    y: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
) -> tuple[Any, np.ndarray, np.ndarray | None]:
    """单折 fit→predict（从 train_model 主循环抽出·行为不变）。返回 (model, y_pred, y_proba)。

    lambdarank 的 group + classification 的 proba 分支原样保留——train_model 与 CPCV 评估共用此原语，
    保证两路 fit/predict 口径单一源、不漂。
    """
    model = _make_model(spec, len(train_idx))
    fit_kwargs: dict[str, Any] = {}
    if spec.task == "lambdarank" and spec.group_col and spec.group_col in df.columns:
        fit_kwargs["group"] = df.iloc[train_idx].groupby(spec.group_col).size().tolist()
    model.fit(X.iloc[train_idx], y[train_idx], **fit_kwargs)
    X_test = X.iloc[test_idx]
    if spec.task == "classification":
        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else None
    else:
        y_pred = model.predict(X_test)
        y_proba = None
    return model, y_pred, y_proba


def cpcv_oos_metric_distribution(
    spec: ModelSpec,
    panel: pd.DataFrame,
    *,
    n_groups: int = 6,
    k_test_groups: int = 2,
    embargo_pct: float = 0.01,
) -> dict[str, Any]:
    """R4 CPCV 消费：模型 OOS 主指标在 φ 条组合路径上的**分布**（路径稳健性·report-only）。

    每条 CPCV 路径覆盖全样本一次 → 对每路径算模型 OOS 主指标 → 分布（mean/std/保守分位 q05/min/median/max/
    frac_below_0）。**保守分位/路径方差 = 过拟合脆弱度信号**：q05≪mean 或方差大 = OOS 表现高度依赖具体切分
    （split-fragile，过拟合嫌疑）。**report-only**：不接 gate、不替方法学拍板（接 gate 的阈值/口径属用户，见卡 861182e6）。

    诚实（不假绿灯）：样本/组数不足 → status='insufficient'、不出分布；非有限路径指标剔除并披露。
    **任务白名单**：regression→**r2**（无需 proba）；二分类→**roc_auc**（重组 proba 路径）；多分类/lambdarank/
    无 predict_proba 模型 → unsupported_task（绝不发假指标）。`baseline`=无技能参照（r2:0 / auc:0.5），q05/median 对
    baseline 判脆弱。**Sharpe/DSR 口径**需 prediction→收益转换（=用户方法学决策）属 follow-on，本件用模型自身 OOS 指标避开。
    **report-only**：不接 gate、不替方法学拍板（接 gate 的阈值/口径属用户，见卡 861182e6）。复用 `_fit_predict_fold`
    （与 train_model 同口径）+ cpcv.py 的 splits/assemble（已验证）。
    """
    task = spec.task
    if task == "regression":
        metric_key, baseline = "r2", 0.0
    elif task == "classification":
        metric_key, baseline = "roc_auc", 0.5
    else:
        return {"status": "unsupported_task", "metric": None, "n_paths": 0, "n_groups": n_groups,
                "k_test_groups": k_test_groups, "reason": f"CPCV 路径分布暂不支持 task={task}（lambdarank 排序需 group 重组）",
                **{k: float("nan") for k in ("mean", "std", "q05", "min", "median", "max", "frac_below_0", "baseline")}}
    base = {"status": "ok", "n_paths": 0, "metric": metric_key, "baseline": baseline,
            "n_groups": n_groups, "k_test_groups": k_test_groups}
    _NAN = {k: float("nan") for k in ("mean", "std", "q05", "min", "median", "max", "frac_below_0")}

    def _insufficient(reason: str) -> dict[str, Any]:
        return {**base, "status": "insufficient", "reason": reason, **_NAN}

    def _unsupported(reason: str) -> dict[str, Any]:
        return {**base, "status": "unsupported_task", "reason": reason, **_NAN}

    df = panel.copy().sort_values("ts").reset_index(drop=True)
    X = df[spec.feature_cols]
    y = df[spec.label_col].values
    times = df["ts"]
    n = len(df)
    is_clf = task == "classification"
    if is_clf and len(np.unique(y[np.isfinite(np.asarray(y, dtype=float))])) != 2:
        return _unsupported("分类 CPCV 仅二分类（roc_auc 需 2 类）；多分类不支持")

    if n_groups < 2 or not (1 <= k_test_groups < n_groups):
        return _insufficient(f"非法分组 n_groups={n_groups} k={k_test_groups}")
    if n < n_groups * 3:
        return _insufficient(f"样本不足 n={n} < n_groups*3={n_groups * 3}（每组至少几个样本才可拟合/评估）")

    try:
        splits = cpcv_splits(times, n_groups=n_groups, k_test_groups=k_test_groups, embargo_pct=embargo_pct)
    except ValueError as exc:
        return _insufficient(f"CPCV split 失败：{exc}")

    # 每组合：在其 test 段 fit→predict，填入全长数组（test 处填值、其余 NaN）供路径重组。
    # 分类用 proba（roc_auc 输入），回归用 pred；分类同时留 pred 供 _evaluate_split 二类校验。
    per_combo_pred: list[np.ndarray] = []
    per_combo_proba: list[np.ndarray] = []
    for sp in splits:
        _, y_pred, y_proba = _fit_predict_fold(spec, df, X, y, sp.train_idx, sp.test_idx)
        if is_clf and y_proba is None:
            return _unsupported("模型无 predict_proba、无法算 roc_auc 路径分布")
        fp = np.full(n, np.nan, dtype=float)
        fp[sp.test_idx] = np.asarray(y_pred, dtype=float)
        per_combo_pred.append(fp)
        if is_clf:
            fpr = np.full(n, np.nan, dtype=float)
            fpr[sp.test_idx] = np.asarray(y_proba, dtype=float)
            per_combo_proba.append(fpr)

    pred_paths = assemble_cpcv_paths(per_combo_pred, n, n_groups, k_test_groups)
    proba_paths = (assemble_cpcv_paths(per_combo_proba, n, n_groups, k_test_groups)
                   if is_clf else [None] * len(pred_paths))
    # 每路径覆盖全样本一次 → 对全样本 y_true 算 OOS 主指标（分类传 proba 路径算 roc_auc）。
    path_metrics: list[float] = []
    for path_pred, path_proba in zip(pred_paths, proba_paths):
        if not np.all(np.isfinite(path_pred)):
            continue                                    # 理论上路径全覆盖；防御：非有限路径剔除
        m = _evaluate_split(spec, y, path_pred, path_proba)
        v = m.get(metric_key)
        if isinstance(v, (int, float)) and math.isfinite(v):
            path_metrics.append(float(v))
    arr = np.asarray(path_metrics, dtype=float)
    if arr.size == 0:
        return _insufficient("无有效路径指标（全非有限）")
    return {
        **base, "status": "ok", "n_paths": int(arr.size), "n_paths_total": len(pred_paths),
        "mean": float(np.mean(arr)), "std": float(np.std(arr, ddof=1) if arr.size > 1 else 0.0),
        "q05": float(np.quantile(arr, 0.05)), "min": float(np.min(arr)),
        "median": float(np.median(arr)), "max": float(np.max(arr)),
        "frac_below_0": float(np.mean(arr < 0.0)),          # r2<0=劣于均值；auc 用 baseline=0.5 判（见 q05/median）
    }


__all__ = ["FoldMetrics", "ModelSpec", "TrainResult", "cpcv_oos_metric_distribution", "train_model"]
