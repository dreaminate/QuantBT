"""R4 CPCV 对抗测试（Combinatorial Purged Cross-Validation 多路径回测）。

设计/推导见 `dev/research/findings/dreaminate/cpcv.md`。门必抓：
- 组合数 C(N,k)、路径数 φ=C(N−1,k−1)=k·C(N,k)/N、每 group test 恰 φ 次（golden N=4,k=2 path_matrix 逐元素）。
- 每条路径覆盖每样本恰一次（无重无漏）。
- purge 无泄露（带 t1）；sentinel：不 purge 则 train 与 test 标签区间重叠（泄露）。
- 逐 test group 段 purge（非全局 min..max，否则误删非连续 test group 中间合法 train）。
- C(N,k) 爆炸 raise（绝不静默采样）；边界拒 N<2/k<1/k≥N/n<N/times 未排序。
- 命门红线：单策略 φ 路径分布**不冒充策略数**（不产 PBO）；分布给保守分位（q05/min）非压单点。
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from app.models.cpcv import (
    assemble_cpcv_paths,
    build_path_matrix,
    cpcv_metric_distribution,
    cpcv_splits,
    n_cpcv_combinations,
    n_cpcv_paths,
)


def _times(n):
    return pd.Series(pd.date_range("2020-01-01", periods=n, freq="D"))


def _group_of(n_samples, n_groups):
    return np.concatenate([np.full(len(p), g) for g, p in enumerate(np.array_split(np.arange(n_samples), n_groups))])


# ===========================================================================
# 组合/路径数 + golden path_matrix
# ===========================================================================


def test_combination_and_path_counts_match_formula():
    for n in (4, 6, 8, 10):
        for k in range(1, n):
            assert n_cpcv_combinations(n, k) == math.comb(n, k)
            assert n_cpcv_paths(n, k) == math.comb(n - 1, k - 1) == k * math.comb(n, k) // n
            assert k * math.comb(n, k) % n == 0   # 整除恒等


def test_path_matrix_golden_case_n4_k2():
    """golden（codex 独立推导一致）：N=4,k=2 → 6 组合、φ=3、path_matrix 逐元素钉死。"""
    expected = np.array([[0, 1, 2], [0, 3, 4], [1, 3, 5], [2, 4, 5]])
    assert np.array_equal(build_path_matrix(4, 2), expected)


def test_each_group_appears_in_test_exactly_phi_times():
    n, k = 6, 2
    splits = cpcv_splits(_times(120), n, k, embargo_pct=0.0)
    cnt = Counter(g for s in splits for g in s.test_groups)
    phi = n_cpcv_paths(n, k)
    assert all(cnt[g] == phi for g in range(n))


# ===========================================================================
# 路径覆盖（无重无漏）
# ===========================================================================


def test_each_path_covers_every_sample_exactly_once():
    n, k, nsamp = 6, 2, 120
    splits = cpcv_splits(_times(nsamp), n, k, embargo_pct=0.0)
    combos = list(combinations(range(n), k))
    per_combo = [np.full(nsamp, np.nan) for _ in combos]
    for s in splits:
        per_combo[s.combination_index][s.test_idx] = s.combination_index   # 标来源
    paths = assemble_cpcv_paths(per_combo, nsamp, n, k)
    assert len(paths) == n_cpcv_paths(n, k)
    for p in paths:
        assert not np.any(np.isnan(p))           # 无漏（每样本被某组合 test 覆盖）
        assert p.shape == (nsamp,)


# ===========================================================================
# Purge 无泄露 + sentinel
# ===========================================================================


def _leak_count(splits, times_arr, t1_arr, group_of, train_getter):
    leak = 0
    for s in splits:
        train = train_getter(s)
        for g in s.test_groups:
            gs = np.where(group_of == g)[0]
            tt0, tt1 = times_arr[gs[0]], t1_arr[gs].max()
            for tr in train:
                if times_arr[tr] <= tt1 and t1_arr[tr] >= tt0:
                    leak += 1
    return leak


def test_purge_removes_all_label_overlap_leakage():
    n, k, nsamp = 6, 2, 120
    times = _times(nsamp)
    t1 = pd.Series(times.values + np.timedelta64(3, "D"))   # 标签延伸 3 天
    splits = cpcv_splits(times, n, k, embargo_pct=0.01, t1=t1)
    ta, t1a, go = np.asarray(times), np.asarray(t1), _group_of(nsamp, n)
    assert _leak_count(splits, ta, t1a, go, lambda s: s.train_idx) == 0


def test_no_purge_leaks_proving_purge_has_teeth():
    """Sentinel：不 purge（仅排除 test 本身）→ train 存在与 test 标签区间重叠样本（泄露）。"""
    n, k, nsamp = 6, 2, 120
    times = _times(nsamp)
    t1 = pd.Series(times.values + np.timedelta64(3, "D"))
    splits = cpcv_splits(times, n, k, embargo_pct=0.01, t1=t1)
    ta, t1a, go = np.asarray(times), np.asarray(t1), _group_of(nsamp, n)

    def naive_train(s):
        test_set = set(s.test_idx.tolist())
        return np.array([i for i in range(nsamp) if i not in test_set])

    assert _leak_count(splits, ta, t1a, go, naive_train) > 0


def test_train_test_disjoint_and_in_range():
    n, k, nsamp = 6, 2, 90
    for s in cpcv_splits(_times(nsamp), n, k, embargo_pct=0.01):
        assert set(s.train_idx.tolist()).isdisjoint(s.test_idx.tolist())
        assert s.train_idx.min() >= 0 and s.train_idx.max() < nsamp
        assert len(np.unique(s.train_idx)) == len(s.train_idx)


# ===========================================================================
# 边界 + 爆炸护栏
# ===========================================================================


def test_combination_explosion_raises_never_silent_samples():
    with pytest.raises(ValueError, match="爆炸|max_combinations"):
        cpcv_splits(_times(200), n_groups=30, k_test_groups=15, max_combinations=100)


def test_boundary_rejects():
    for n_groups, k in [(1, 1), (6, 6), (6, 0), (6, 7)]:
        with pytest.raises(ValueError):
            cpcv_splits(_times(60), n_groups, k)
    with pytest.raises(ValueError, match="样本"):
        cpcv_splits(_times(3), n_groups=6, k_test_groups=2)   # n_samples < n_groups


def test_unsorted_times_rejected():
    t = _times(60)
    t.iloc[10], t.iloc[20] = t.iloc[20], t.iloc[10]   # 打乱
    with pytest.raises(ValueError, match="升序"):
        cpcv_splits(t, 6, 2)


def test_t1_length_mismatch_rejected():
    with pytest.raises(ValueError, match="t1"):
        cpcv_splits(_times(60), 6, 2, t1=_times(50))


def test_k1_degenerates_to_single_path():
    """k=1 → φ=1（结构等价 purged k-fold OOS 单路径；embargo 语义 AFML、不声称字节等价）。"""
    n = 6
    splits = cpcv_splits(_times(120), n, 1, embargo_pct=0.0)
    assert len(splits) == n and n_cpcv_paths(n, 1) == 1


# ===========================================================================
# 命门：分布诚实 + 路径数≠策略数
# ===========================================================================


def test_distribution_is_honest_not_single_point():
    """噪声策略 → 多路径 Sharpe 分布跨 0（frac≤0 高）；给保守分位（q05/min）非压成漂亮单点。"""
    n, k, nsamp = 6, 2, 120
    splits = cpcv_splits(_times(nsamp), n, k, embargo_pct=0.0)
    combos = list(combinations(range(n), k))
    rng = np.random.default_rng(0)
    per_r = [np.full(nsamp, np.nan) for _ in combos]
    for s in splits:
        per_r[s.combination_index][s.test_idx] = rng.standard_normal(len(s.test_idx)) * 0.01
    d = cpcv_metric_distribution(per_r, nsamp, n, k)
    assert d["n_paths"] == n_cpcv_paths(n, k)
    assert {"min", "q05", "q25", "median", "q75", "q95", "max", "frac_le_0"} <= set(d)
    assert d["q05"] <= d["median"] <= d["q95"]      # 分位单调
    assert d["frac_le_0"] > 0.5                      # 噪声策略多数路径 ≤0


def test_distribution_does_not_fabricate_pbo_from_paths():
    """命门红线：单策略 φ 路径分布**绝不产 PBO**（路径数≠策略数；PBO 列须 distinct strategy）。"""
    n, k, nsamp = 6, 2, 120
    splits = cpcv_splits(_times(nsamp), n, k, embargo_pct=0.0)
    combos = list(combinations(range(n), k))
    per_r = [np.full(nsamp, np.nan) for _ in combos]
    for s in splits:
        per_r[s.combination_index][s.test_idx] = np.random.default_rng(1).standard_normal(len(s.test_idx)) * 0.01
    d = cpcv_metric_distribution(per_r, nsamp, n, k)
    assert "pbo" not in d and "PBO" not in d         # 绝不把路径数当策略数凑 PBO


# ===========================================================================
# 命门加固（评审 medium：饿死路径假 0 / insufficient 形状 / embargo 方向 / 来源区分 / 护栏）
# ===========================================================================


def test_starved_paths_not_fabricated_as_zero_and_visible():
    """评审 medium·命门：全 NaN（调用方漏填）→ insufficient=True、统计量 NaN，**绝不**伪造 0.0 污染 q05/min。"""
    n, k, nsamp = 4, 2, 80
    n_comb = n_cpcv_combinations(n, k)
    per = [np.full(nsamp, np.nan) for _ in range(n_comb)]   # 全饿死
    d = cpcv_metric_distribution(per, nsamp, n, k)
    assert d["insufficient"] is True
    assert d["n_paths_dropped"] == d["n_paths"]
    assert math.isnan(d["q05"]) and math.isnan(d["min"])    # 绝非 0.0


def test_one_starved_path_does_not_poison_conservative_quantile():
    """部分饿死：一条路径漏填 → 记 NaN 剔除（n_paths_dropped 可见），不以假 0.0 拉低 min/q05。"""
    n, k, nsamp = 4, 2, 80
    splits = cpcv_splits(_times(nsamp), n, k, embargo_pct=0.0)
    combos = list(combinations(range(n), k))
    rng = np.random.default_rng(7)
    per = [np.full(nsamp, np.nan) for _ in combos]
    for s in splits:
        per[s.combination_index][s.test_idx] = rng.standard_normal(len(s.test_idx)) * 0.005 + 0.02  # 强正 edge + 波动
    # 把 combo 0 整个清空（饿死它参与的路径）
    per[0][:] = np.nan
    d = cpcv_metric_distribution(per, nsamp, n, k)
    assert d["n_paths_dropped"] >= 1
    # 存活路径是强正收益 → min 不应被假 0.0 拉低（饿死路径记 NaN 剔除，非伪造 0）
    assert d["insufficient"] is False and d["min"] > 0.0


def test_insufficient_dict_shape_symmetric():
    """insufficient 分支与正常分支 dict **同形状**（全 key 在）→ 下游 .get('q05') 不把全坏误读成 0。"""
    n, k, nsamp = 4, 2, 80
    full = cpcv_metric_distribution([np.full(nsamp, np.nan) for _ in range(n_cpcv_combinations(n, k))], nsamp, n, k)
    assert {"min", "q05", "q25", "median", "q75", "q95", "max", "frac_le_0", "n_paths_dropped", "insufficient"} <= set(full)


def test_embargo_is_afml_single_sided_after_test():
    """embargo = AFML 单侧（test **后**）：test group 后样本被剔、test 前合法样本保留。搞成两侧/置零必抓。"""
    n, nsamp = 6, 120
    times = _times(nsamp)
    splits = cpcv_splits(times, n, 1, embargo_pct=0.05)   # k=1 单 test group，无 t1（仅 embargo 起作用）
    go = _group_of(nsamp, n)
    g = 2
    g_samples = np.where(go == g)[0]
    g_start, g_end = int(g_samples[0]), int(g_samples[-1])
    split = splits[g]   # k=1 → 第 g 个组合 test group=(g,)
    assert split.test_groups == (g,)
    after = g_end + 1
    before = g_start - 1
    assert after not in split.train_idx        # test 后窗剔除（AFML）
    assert before in split.train_idx           # test 前合法样本保留（非两侧）


def test_build_path_matrix_explosion_guard():
    with pytest.raises(ValueError, match="爆炸|max_combinations"):
        build_path_matrix(40, 20, max_combinations=100)


def test_negative_embargo_rejected():
    with pytest.raises(ValueError, match="embargo"):
        cpcv_splits(_times(60), 6, 2, embargo_pct=-0.1)


def test_assemble_rejects_wrong_length_arrays():
    n, k, nsamp = 4, 2, 80
    bad = [np.zeros(nsamp - 5) for _ in range(n_cpcv_combinations(n, k))]   # 长度错
    with pytest.raises(ValueError, match="长度"):
        assemble_cpcv_paths(bad, nsamp, n, k)


def test_path_sources_are_distinct_per_path():
    """评审 medium：填**组合 id**而非全 1 → 验证各路径单元来源 == path_matrix[g,p]（防 φ 路径坍缩成 path0）。"""
    n, k, nsamp = 6, 2, 120
    splits = cpcv_splits(_times(nsamp), n, k, embargo_pct=0.0)
    combos = list(combinations(range(n), k))
    per = [np.full(nsamp, np.nan) for _ in combos]
    for s in splits:
        per[s.combination_index][s.test_idx] = float(s.combination_index)   # 标来源 combo
    paths = assemble_cpcv_paths(per, nsamp, n, k)
    mat = build_path_matrix(n, k)
    go = _group_of(nsamp, n)
    for p_idx, path in enumerate(paths):
        for g in range(n):
            cells = path[go == g]
            assert np.all(cells == mat[g, p_idx]), f"路径{p_idx} group{g} 来源≠path_matrix（重建错位/坍缩）"


def test_realworld_superiority_caveat_is_machine_pinned():
    """诚实边界机器钉死（评审 governance）：R4=B「真实市场未确立」不仅活 docstring。"""
    from app.models.cpcv import CPCV_DUAL_TRACK_CAVEAT, CPCV_REALWORLD_SUPERIORITY_ESTABLISHED

    assert CPCV_REALWORLD_SUPERIORITY_ESTABLISHED is False
    assert "未确立" in CPCV_DUAL_TRACK_CAVEAT and "每折内 fit" in CPCV_DUAL_TRACK_CAVEAT
