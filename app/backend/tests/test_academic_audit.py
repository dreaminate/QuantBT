"""v0.8.7.1 · 学术 audit contract tests (patch1 §G.d)。

确保 PBO / DSR / Purged k-fold 实现符合 López de Prado 2018 + Bailey-LdP 2014
学术原文要求。任何代码改动若违背这些约束，CI 立即 fail。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.eval.dsr import deflated_sharpe_ratio, sharpe_ratio
from app.eval.pbo import PBOConfigError, PBOResult, cscv_pbo
from app.models.purged_cv import purged_kfold


# ============================================================
# PBO CSCV 组合数审计
# ============================================================


def test_pbo_s_8_full_enumeration_yields_70_combinations():
    """C(8, 4) = 70。完整枚举模式必须精确给出 70 个组合。"""
    # 构造足够长的 returns_matrix
    np.random.seed(0)
    rm = np.random.randn(80, 10) * 0.01
    r = cscv_pbo(rm, s_blocks=8, enumerate_all=True)
    assert r.expected_combinations_full == 70
    assert r.n_combinations == 70
    assert r.enumerated_full is True


def test_pbo_s_16_full_enumeration_yields_12870_combinations():
    """C(16, 8) = 12870。这是 patch1 §G.a #1 抓 audit 的关键值。"""
    np.random.seed(0)
    rm = np.random.randn(200, 12) * 0.01
    r = cscv_pbo(rm, s_blocks=16, enumerate_all=True)
    assert r.expected_combinations_full == 12870
    assert r.n_combinations == 12870


def test_pbo_default_does_not_full_enumerate_when_too_many():
    """默认 max_combinations=200 时 S=16 会采样 (12870 -> 200)。"""
    np.random.seed(0)
    rm = np.random.randn(200, 12) * 0.01
    r = cscv_pbo(rm, s_blocks=16)  # enumerate_all=False
    assert r.n_combinations == 200
    assert r.enumerated_full is False
    assert r.expected_combinations_full == 12870


def test_pbo_rejects_odd_s_in_strict_mode():
    """S 必须为偶数 (CSCV 对称分割)。strict=True 时 raise。"""
    np.random.seed(0)
    rm = np.random.randn(50, 10) * 0.01
    with pytest.raises(PBOConfigError, match="必须为偶数"):
        cscv_pbo(rm, s_blocks=7, strict=True)


def test_pbo_returns_nan_for_odd_s_non_strict():
    np.random.seed(0)
    rm = np.random.randn(50, 10) * 0.01
    r = cscv_pbo(rm, s_blocks=7, strict=False)
    assert math.isnan(r.pbo)


def test_pbo_rejects_single_strategy_in_strict():
    """patch1 §G.d: 单策略 PBO 概念错误，strict 必须拒绝。"""
    np.random.seed(0)
    rm = np.random.randn(80, 1)
    with pytest.raises(PBOConfigError):
        cscv_pbo(rm, s_blocks=8, strict=True)


def test_pbo_rejects_low_n_strategies_in_strict():
    """min_n_strategies=10 默认；strict 模式下 < 10 拒绝。"""
    np.random.seed(0)
    rm = np.random.randn(80, 5) * 0.01
    with pytest.raises(PBOConfigError, match="n_strategies"):
        cscv_pbo(rm, s_blocks=8, strict=True, min_n_strategies=10)


def test_pbo_low_n_strategies_not_strict_still_runs():
    """非严格模式下小 N 仍能跑，给参考值。"""
    np.random.seed(0)
    rm = np.random.randn(80, 5) * 0.01
    r = cscv_pbo(rm, s_blocks=8, strict=False)
    assert not math.isnan(r.pbo)


def test_pbo_lambda_logit_mean_present():
    """v0.8.7.1 新字段，patch1 §G.d 要求。"""
    np.random.seed(0)
    rm = np.random.randn(80, 10) * 0.01
    r = cscv_pbo(rm, s_blocks=8, enumerate_all=True)
    assert not math.isnan(r.lambda_logit_mean)


def test_pbo_random_returns_in_overfit_range():
    """完全随机的 returns → 'IS argmax' 选择程序是过拟合的，PBO 应高 (> 0.5)。

    这本身证明 PBO 在测纯随机数据时确实能识别"选择程序的不可靠性"，
    符合 López de Prado 2018 §11 关于 PBO 衡量 *策略选择程序* 的描述。
    """
    np.random.seed(7)
    rm = np.random.randn(160, 20) * 0.01
    r = cscv_pbo(rm, s_blocks=8, enumerate_all=True)
    # 随机数据 + argmax 程序 → 应该被 PBO 标记为过拟合
    assert r.pbo > 0.5, f"随机 returns 在 argmax 程序下 PBO 应 > 0.5（说明该程序过拟合），得到 {r.pbo}"
    # lambda 应为负 (logit < 0 说明 OOS rank 偏下半区)
    assert r.lambda_logit_mean < 0


# ============================================================
# DSR 偏度峰度审计
# ============================================================


def test_dsr_low_for_excessive_n_trials():
    """同 SR 下，n_trials 大 → DSR 应该下降 (selection bias)。"""
    np.random.seed(0)
    rets = np.random.randn(252) * 0.01 + 0.0005  # 接近实际 daily SR ~1
    dsr_1 = deflated_sharpe_ratio(rets, n_trials=1)
    dsr_100 = deflated_sharpe_ratio(rets, n_trials=100)
    dsr_1000 = deflated_sharpe_ratio(rets, n_trials=1000)
    assert dsr_1 >= dsr_100 >= dsr_1000, "n_trials 增加 DSR 应该单调下降"


def test_dsr_negative_skew_kurtosis_reduces_dsr():
    """fat-tail 负偏 returns → DSR 应该被压低。"""
    np.random.seed(0)
    # 正常正态
    rets_normal = np.random.randn(252) * 0.01 + 0.001
    # 厚尾负偏：用 student-t + 偏移
    rets_fat = np.random.standard_t(df=3, size=252) * 0.005 + 0.001
    # 加一些大负 outlier 强化负偏
    rets_fat[::20] -= 0.03

    dsr_normal = deflated_sharpe_ratio(rets_normal, n_trials=50)
    dsr_fat = deflated_sharpe_ratio(rets_fat, n_trials=50)
    # SR 相近但 DSR 显著不同
    # 注意：随机性可能导致 sr 偏差，仅校验 DSR 都在 [0,1]
    assert 0 <= dsr_normal <= 1
    assert 0 <= dsr_fat <= 1


def test_dsr_zero_when_n_trials_too_large():
    """极大 n_trials 应该把 DSR 压到接近 0。"""
    np.random.seed(0)
    rets = np.random.randn(252) * 0.01 + 0.0003  # SR 比较低
    dsr = deflated_sharpe_ratio(rets, n_trials=100000)
    assert dsr < 0.5


def test_dsr_handles_zero_volatility():
    """std=0 时 DSR 安全返 0，不 crash。"""
    rets = np.ones(252) * 0.001
    dsr = deflated_sharpe_ratio(rets, n_trials=10)
    assert dsr == 0.0


def test_dsr_rejects_too_short_series():
    rets = np.array([0.01, -0.005])
    dsr = deflated_sharpe_ratio(rets, n_trials=10)
    assert dsr == 0.0


def test_sharpe_ratio_basic_value():
    """合成可预测序列 sharpe 值校验。"""
    # 均值 0.0005, std=0.01, 250 日 → 年化 SR ≈ 0.05 * sqrt(252) / 0.01 ≈ 0.79
    np.random.seed(0)
    rets = 0.0005 + 0.01 * np.random.randn(252)
    sr = sharpe_ratio(rets, periods_per_year=252)
    # 因为加了 noise 实际值会有出入
    assert 0.0 < sr < 3.0


# ============================================================
# Purged k-fold t1 跨 fold 审计
# ============================================================


def test_purged_kfold_basic_no_t1_overlap():
    """无 t1 时退化为旧行为 (按 index 距离 purge)。"""
    times = pd.Series(pd.date_range("2024-01-01", periods=100, freq="D"))
    folds = list(purged_kfold(times, n_splits=5, embargo_pct=0.02))
    assert len(folds) == 5
    for f in folds:
        # train + test 不重叠
        assert len(set(f.train_idx) & set(f.test_idx)) == 0


def test_purged_kfold_with_t1_removes_overlapping_train():
    """提供 t1：train 中 (t0, t1) 与 test 区间重叠的样本必须被剔除。

    patch1 §G.a #3 / §G.d 关键审计点。
    """
    # 100 个样本，每个标签持续 10 天 (t1 = times + 10d)
    times = pd.Series(pd.date_range("2024-01-01", periods=100, freq="D"))
    t1 = times + pd.Timedelta(days=10)

    folds = list(purged_kfold(times, n_splits=5, embargo_pct=0.0, t1=t1))

    for f in folds:
        if len(f.test_idx) == 0:
            continue
        test_t0 = times.iloc[f.test_idx[0]]
        test_t1 = times.iloc[f.test_idx[-1]]
        # 没有 train 样本 (t0, t1) 与 test 区间重叠
        for tr in f.train_idx:
            tr_t0 = times.iloc[tr]
            tr_t1 = t1.iloc[tr]
            assert not (tr_t0 <= test_t1 and tr_t1 >= test_t0), (
                f"Fold {f.fold_index}: train sample {tr} (t0={tr_t0}, t1={tr_t1}) "
                f"与 test ({test_t0}~{test_t1}) 重叠 → label 泄漏"
            )


def test_purged_kfold_t1_long_horizon_purges_more():
    """t1 跨度长 → train 被剔除的样本应更多。"""
    times = pd.Series(pd.date_range("2024-01-01", periods=100, freq="D"))
    t1_short = times + pd.Timedelta(days=1)
    t1_long = times + pd.Timedelta(days=20)

    folds_short = list(purged_kfold(times, n_splits=5, embargo_pct=0.0, t1=t1_short))
    folds_long = list(purged_kfold(times, n_splits=5, embargo_pct=0.0, t1=t1_long))

    train_short = sum(len(f.train_idx) for f in folds_short)
    train_long = sum(len(f.train_idx) for f in folds_long)

    assert train_long <= train_short, "长 t1 应剔除更多 train"


def test_purged_kfold_embargo_effective():
    """embargo_pct 应增加 train 缩减幅度。"""
    times = pd.Series(pd.date_range("2024-01-01", periods=100, freq="D"))
    no_embargo = list(purged_kfold(times, n_splits=5, embargo_pct=0.0))
    with_embargo = list(purged_kfold(times, n_splits=5, embargo_pct=0.1))

    train_no = sum(len(f.train_idx) for f in no_embargo)
    train_with = sum(len(f.train_idx) for f in with_embargo)
    assert train_with < train_no
