"""R4 CPCV 消费——模型 OOS 主指标在 φ 路径上的分布（路径稳健性·report-only）对抗测试。

门必抓：
- **判别器**：强信号 → r2 路径分布高且稳；噪声（label 独立于特征）→ r2≈0/负、过拟合脆弱性可见（强≫噪声）。
  路径重组错位会让强信号 r2 崩 → 此判别器抓。
- **φ 路径数**：n_paths == C(N-1,k-1)。分位序 min≤q05≤median≤max。
- **不假绿灯**：非回归 → unsupported_task（不伪造）；样本不足 → insufficient；确定性（random_state 固定）。
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app.models.cpcv import n_cpcv_paths
from app.models.training import ModelSpec, cpcv_oos_metric_distribution


def _panel(n: int = 360, seed: int = 0, signal: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    y = (0.6 * f1 - 0.4 * f2 + rng.normal(size=n, scale=0.2)) if signal else rng.normal(size=n)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame({"ts": [base + timedelta(days=i) for i in range(n)], "f1": f1, "f2": f2, "label": y})


def _spec() -> ModelSpec:
    return ModelSpec(task="regression", model="ridge", feature_cols=["f1", "f2"], label_col="label")


def test_cpcv_strong_signal_high_stable_r2():
    """强信号 → r2 路径分布高且稳（mean 高、q05 高、frac_below_0≈0）；n_paths==φ。"""
    d = cpcv_oos_metric_distribution(_spec(), _panel(signal=True), n_groups=6, k_test_groups=2)
    assert d["status"] == "ok" and d["metric"] == "r2"
    assert d["n_paths"] == n_cpcv_paths(6, 2)
    assert d["mean"] > 0.5 and d["q05"] > 0.3 and d["frac_below_0"] == 0.0


def test_cpcv_noise_fragile_and_discriminates_from_signal():
    """**判别器**：噪声 label → r2 路径分布≈0/负（过拟合脆弱性可见）；强信号 ≫ 噪声（路径重组对齐才成立）。"""
    noise = cpcv_oos_metric_distribution(_spec(), _panel(signal=False), n_groups=6, k_test_groups=2)
    strong = cpcv_oos_metric_distribution(_spec(), _panel(signal=True), n_groups=6, k_test_groups=2)
    assert noise["status"] == "ok"
    assert noise["mean"] < 0.1 and noise["q05"] < 0.05            # 噪声无 OOS 解释力
    assert strong["mean"] - noise["mean"] > 0.4                   # 真判别（重组错位→强信号 r2 崩→此断言挂）
    assert strong["q05"] > noise["q05"]


def test_cpcv_path_count_is_phi_across_configs():
    for n_g, k in [(6, 2), (5, 2), (8, 3)]:
        d = cpcv_oos_metric_distribution(_spec(), _panel(n=480), n_groups=n_g, k_test_groups=k)
        assert d["status"] == "ok" and d["n_paths"] == n_cpcv_paths(n_g, k), f"N={n_g} k={k}"


def test_cpcv_quantile_ordering():
    d = cpcv_oos_metric_distribution(_spec(), _panel(), n_groups=6, k_test_groups=2)
    assert d["min"] <= d["q05"] <= d["median"] <= d["max"]


def test_cpcv_unsupported_task_honest_no_fake_metric():
    """非回归（分类/排序）→ unsupported_task、分布字段 NaN（绝不用 r2 对它们发假信号·不假绿灯）。"""
    d = cpcv_oos_metric_distribution(
        ModelSpec(task="classification", model="sklearn_rf", feature_cols=["f1", "f2"]),
        _panel(), n_groups=6, k_test_groups=2,
    )
    assert d["status"] == "unsupported_task" and not math.isfinite(d["q05"])


def test_cpcv_insufficient_samples_abstains():
    d = cpcv_oos_metric_distribution(_spec(), _panel(n=10), n_groups=6, k_test_groups=2)
    assert d["status"] == "insufficient" and not math.isfinite(d["mean"])


def _panel_clf(n: int = 360, seed: int = 0, signal: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    if signal:
        p = 1.0 / (1.0 + np.exp(-(3.0 * f1 - 2.0 * f2)))      # 可分：label 由特征驱动
        y = (rng.uniform(size=n) < p).astype(int)
    else:
        y = rng.integers(0, 2, size=n)                        # 噪声：label 独立于特征
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame({"ts": [base + timedelta(days=i) for i in range(n)], "f1": f1, "f2": f2, "label": y})


def _spec_clf() -> ModelSpec:
    return ModelSpec(task="classification", model="sklearn_logreg", feature_cols=["f1", "f2"], label_col="label")


def test_cpcv_classification_strong_high_auc_and_baseline():
    """二分类 CPCV：强分类器 → roc_auc 路径分布高（mean 高、q05 高、min≥baseline=0.5）；metric/baseline 正确。"""
    d = cpcv_oos_metric_distribution(_spec_clf(), _panel_clf(signal=True), n_groups=6, k_test_groups=2)
    assert d["status"] == "ok" and d["metric"] == "roc_auc" and d["baseline"] == 0.5
    assert d["n_paths"] == n_cpcv_paths(6, 2)
    assert d["mean"] > 0.8 and d["q05"] > 0.65 and d["min"] >= 0.5 and d["max"] <= 1.0


def test_cpcv_classification_noise_near_half_discriminates():
    """**判别器**：噪声 label（独立于特征）→ roc_auc≈0.5（无判别力）；强 ≫ 噪声（proba 路径重组对齐才成立）。"""
    noise = cpcv_oos_metric_distribution(_spec_clf(), _panel_clf(signal=False), n_groups=6, k_test_groups=2)
    strong = cpcv_oos_metric_distribution(_spec_clf(), _panel_clf(signal=True), n_groups=6, k_test_groups=2)
    assert noise["status"] == "ok" and abs(noise["mean"] - 0.5) < 0.12     # 噪声 auc 围绕 0.5
    assert strong["mean"] - noise["mean"] > 0.25                            # 真判别（proba 重组错位→强 auc 崩→此挂）


def test_cpcv_multiclass_unsupported_honest():
    """多分类（>2 类）→ unsupported_task（roc_auc 需二分类·绝不发假指标）。"""
    p = _panel_clf(signal=True)
    p = p.assign(label=np.tile([0, 1, 2], len(p) // 3 + 1)[: len(p)])      # 3 类
    d = cpcv_oos_metric_distribution(_spec_clf(), p, n_groups=6, k_test_groups=2)
    assert d["status"] == "unsupported_task" and not math.isfinite(d["q05"])


def test_cpcv_regression_baseline_is_zero():
    d = cpcv_oos_metric_distribution(_spec(), _panel(), n_groups=6, k_test_groups=2)
    assert d["baseline"] == 0.0 and d["metric"] == "r2"


def test_train_model_cpcv_optin_default_off_and_on():
    """**opt-in 集成·默认关不改行为**：compute_cpcv 默认 False → TrainResult.cpcv_distribution=None；
    True → 产 report-only 分布写进结果（随 result.json 流到 verdict/UI）。asdict JSON-safe。"""
    from dataclasses import asdict as _asdict
    import json as _json

    from app.models.training import train_model

    r_off = train_model(
        ModelSpec(task="regression", model="ridge", feature_cols=["f1", "f2"], label_col="label", n_splits=4),
        _panel(),
    )
    assert r_off.cpcv_distribution is None                       # 默认关：不算、不假绿灯
    r_on = train_model(
        ModelSpec(task="regression", model="ridge", feature_cols=["f1", "f2"], label_col="label",
                  n_splits=4, compute_cpcv=True, cpcv_n_groups=5, cpcv_k_test=2),
        _panel(),
    )
    assert r_on.cpcv_distribution is not None
    assert r_on.cpcv_distribution["status"] == "ok" and r_on.cpcv_distribution["metric"] == "r2"
    assert r_on.cpcv_distribution["n_paths"] == n_cpcv_paths(5, 2)
    _json.dumps(_asdict(r_on))                                   # 结果整体 JSON-safe（含 cpcv_distribution）


def test_cpcv_deterministic_and_json_safe():
    d1 = cpcv_oos_metric_distribution(_spec(), _panel(seed=1), n_groups=6, k_test_groups=2)
    d2 = cpcv_oos_metric_distribution(_spec(), _panel(seed=1), n_groups=6, k_test_groups=2)
    assert d1["mean"] == d2["mean"] and d1["q05"] == d2["q05"]    # random_state 固定 → 确定性
    json.dumps(d1)
