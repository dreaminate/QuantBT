"""R4 · CPCV (Combinatorial Purged Cross-Validation, López de Prado 2018 AFML Ch.12)。

扩展 `purged_cv.py`（purged k-fold + embargo + walk-forward）：把单条 OOS 路径升级为**组合式多路径**——
N 个时间连续 group 每次选 k 个作 test（C(N,k) 组合，train 经 purge+embargo），重组出 **φ=C(N−1,k−1)** 条
「各覆盖全时间线一次」的回测路径 → 给单策略一个 OOS 性能**分布**（非单点），暴露过拟合方差。

设计/推导见 `dev/research/findings/dreaminate/cpcv.md`。

**治理（R4=B · 命门）**：
- **CPCV 真实市场优越性未确立**（仅合成 Heston 占优）→ 作 walk-forward 的**双轨稳健性证据**，
  **绝不**自动判「CPCV 赢」；调用方选 cv_scheme，本模块只给机制 + 诚实分布。
- **φ 条路径 ≠ φ 个策略**：单策略 OOS 路径分布**绝不冒充策略数喂 PBO**（PBO 列须 distinct strategy/config，
  单策略 PBO 恒 N/A）。多路径分布喂 DSR 取**保守分位**（q05/min，非均值/最优）。
- **CPCV 只隔离索引**：scaler/特征选择/target encoding/调参必须每折内 fit，否则路径重建再对也只是把
  泄露预测拼漂亮（R5 用法 caveat）。
- **embargo 语义 = AFML（test 后）**，与 purged_kfold 两侧 embargo 不同（已先定、写进测试）；k=1 与
  purged_kfold **结构等价**（φ=1）但不声称字节等价。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..eval.dsr import sharpe_ratio

MAX_CPCV_COMBINATIONS = 20_000   # C(N,k) 爆炸护栏：超则 raise，绝不静默采样（否则 φ 公式失效）

# R4=B 诚实边界（机器可钉死、不仅活在 docstring）：CPCV 真实市场优越性**未确立**（仅合成 Heston 占优）。
# 作 walk-forward 的双轨稳健性证据，**绝不**自动判「CPCV 赢」。测试断言此常量为 False，防未来散文被悄抹。
CPCV_REALWORLD_SUPERIORITY_ESTABLISHED = False
CPCV_DUAL_TRACK_CAVEAT = (
    "CPCV 给组合式 OOS 路径分布（合成环境更强，真实市场占优未确立）；walk-forward 是部署形态证据。"
    "二者分歧时不得自动判 CPCV 赢——并陈、由用户拍。CPCV 只隔离索引，scaler/特征选择/调参须每折内 fit。"
)


@dataclass
class CPCVSplit:
    train_idx: np.ndarray
    test_idx: np.ndarray
    test_groups: tuple[int, ...]      # 本组合作 test 的 group id
    combination_index: int


def n_cpcv_combinations(n_groups: int, k_test_groups: int) -> int:
    """组合数 C(N, k)。"""
    return math.comb(n_groups, k_test_groups)


def n_cpcv_paths(n_groups: int, k_test_groups: int) -> int:
    """回测路径数 φ = C(N−1, k−1) = k·C(N,k)/N（双计数恒等）。"""
    return math.comb(n_groups - 1, k_test_groups - 1)


def _group_assignment(n_samples: int, n_groups: int) -> np.ndarray:
    """把 0..n_samples−1 按时间序切成 n_groups 个连续 group（size 差 ≤1，np.array_split 口径）。"""
    return np.concatenate([np.full(len(part), g, dtype=int)
                           for g, part in enumerate(np.array_split(np.arange(n_samples), n_groups))])


def _validate(n_samples: int, n_groups: int, k_test_groups: int, times: pd.Series | None,
              t1: pd.Series | None, max_combinations: int) -> None:
    if n_groups < 2:
        raise ValueError(f"n_groups 须 ≥2，得 {n_groups}")
    if not (1 <= k_test_groups < n_groups):
        raise ValueError(f"k_test_groups 须 ∈[1, n_groups)，得 {k_test_groups}（k≥N 则无 train）")
    if n_samples < n_groups:
        raise ValueError(f"样本数 {n_samples} < n_groups {n_groups}（每 group 须 ≥1 样本）")
    if times is not None:
        tv = np.asarray(times)
        if len(tv) > 1 and np.any(tv[1:] < tv[:-1]):
            raise ValueError("times 必须按时间升序排列")
    if t1 is not None and times is not None and len(t1) != len(times):
        raise ValueError(f"t1 长度 {len(t1)} ≠ times 长度 {len(times)}")
    _guard_combinations(n_groups, k_test_groups, max_combinations)


def _guard_combinations(n_groups: int, k_test_groups: int, max_combinations: int) -> None:
    """组合爆炸护栏（cpcv_splits / build_path_matrix 共用）：超则 raise，**绝不静默采样**。"""
    n_comb = n_cpcv_combinations(n_groups, k_test_groups)
    if n_comb > max_combinations:
        raise ValueError(
            f"C({n_groups},{k_test_groups})={n_comb} > max_combinations {max_combinations}：组合爆炸。"
            "调小 n_groups/k 或显式提高上限——**绝不静默采样**（会让 φ=C(N−1,k−1) 路径公式失效）"
        )


def cpcv_splits(
    times: pd.Series,
    n_groups: int = 6,
    k_test_groups: int = 2,
    embargo_pct: float = 0.01,
    t1: pd.Series | None = None,
    *,
    max_combinations: int = MAX_CPCV_COMBINATIONS,
) -> list[CPCVSplit]:
    """生成全部 C(N,k) 个 CPCV 组合的 train/test 索引（purge + AFML embargo）。

    `times` 升序 datetime-like；`t1` 每样本 label 结束时间（沿用 purged_cv 的标签重叠 purge 口径）。
    purge **逐 test group 段判**（绝不用全局 min..max 合区间，否则误删非连续 test group 中间的合法 train）。
    """

    times_arr = np.asarray(times)
    n_samples = len(times_arr)
    if embargo_pct < 0:
        raise ValueError(f"embargo_pct 须 ≥0，得 {embargo_pct}（负值非法，绝不静默当 0）")
    _validate(n_samples, n_groups, k_test_groups, times, t1, max_combinations)
    group_of = _group_assignment(n_samples, n_groups)
    indices = np.arange(n_samples)
    embargo = int(n_samples * embargo_pct)
    t1_arr = np.asarray(t1) if t1 is not None else times_arr   # 无 t1 → 标签区间退化为点 [t,t]

    splits: list[CPCVSplit] = []
    for ci, test_groups in enumerate(combinations(range(n_groups), k_test_groups)):
        test_mask = np.isin(group_of, test_groups)
        test_idx = indices[test_mask]
        train_candidate = indices[~test_mask]
        keep = np.ones(len(train_candidate), dtype=bool)
        # 逐 test group 段：purge 标签重叠 + embargo（test 后窗）
        for g in test_groups:
            g_samples = indices[group_of == g]
            g_start, g_end = int(g_samples[0]), int(g_samples[-1])
            test_t0 = times_arr[g_start]
            test_t1 = t1_arr[g_samples].max()
            for i, tr in enumerate(train_candidate):
                if not keep[i]:
                    continue
                tr_t0, tr_t1 = times_arr[tr], t1_arr[tr]
                # 标签区间重叠（inclusive，沿用 purged_cv 口径）
                if tr_t0 <= test_t1 and tr_t1 >= test_t0:
                    keep[i] = False
                # AFML embargo：test group 后 embargo 窗内（位置）剔除
                elif embargo > 0 and g_end < tr <= g_end + embargo:
                    keep[i] = False
        train_idx = train_candidate[keep]
        if train_idx.size == 0:
            raise ValueError(f"组合 {ci}（test groups {test_groups}）purge+embargo 后 train 为空——参数过激进")
        splits.append(CPCVSplit(train_idx=train_idx, test_idx=test_idx,
                                test_groups=tuple(test_groups), combination_index=ci))
    return splits


def build_path_matrix(n_groups: int, k_test_groups: int, *,
                      max_combinations: int = MAX_CPCV_COMBINATIONS) -> np.ndarray:
    """path_matrix[g, p] = 第 p 次把 group g 放进 test 的 combo_id（shape N×φ）。第 p 列 = 第 p 条路径。"""
    if n_groups < 2 or not (1 <= k_test_groups < n_groups):
        raise ValueError(f"n_groups≥2 且 k∈[1,n_groups)，得 n_groups={n_groups} k={k_test_groups}")
    _guard_combinations(n_groups, k_test_groups, max_combinations)   # 同 cpcv_splits 护栏，绝不 hang/OOM
    combos = list(combinations(range(n_groups), k_test_groups))
    phi = n_cpcv_paths(n_groups, k_test_groups)
    mat = np.empty((n_groups, phi), dtype=int)
    for g in range(n_groups):
        occ = [ci for ci, c in enumerate(combos) if g in c]
        if len(occ) != phi:                       # 不变量自检（理论恒成立，防回归）
            raise AssertionError(f"group {g} 出现 {len(occ)} 次 ≠ φ={phi}")
        mat[g, :] = occ
    return mat


def assemble_cpcv_paths(
    per_combo_values: list[np.ndarray],
    n_samples: int,
    n_groups: int,
    k_test_groups: int,
) -> list[np.ndarray]:
    """把 C(N,k) 个组合的逐样本 OOS 值重组成 φ 条「各覆盖全样本一次」的路径。

    `per_combo_values[ci]` = 长 n_samples 数组，组合 ci 的 test 样本处填 OOS 值（非 test 处任意/NaN）。
    返回 φ 个长 n_samples 数组（路径 p 上 group g 的值取自 path_matrix[g,p] 组合）。
    """

    if len(per_combo_values) != n_cpcv_combinations(n_groups, k_test_groups):
        raise ValueError("per_combo_values 长度须 = C(N,k)")
    if any(len(v) != n_samples for v in per_combo_values):
        raise ValueError("per_combo_values 各数组长度须 = n_samples（否则路径重建下标错位）")
    group_of = _group_assignment(n_samples, n_groups)
    mat = build_path_matrix(n_groups, k_test_groups)
    phi = mat.shape[1]
    paths: list[np.ndarray] = []
    for p in range(phi):
        path = np.full(n_samples, np.nan, dtype=float)
        for g in range(n_groups):
            sel = group_of == g
            path[sel] = np.asarray(per_combo_values[mat[g, p]], dtype=float)[sel]
        paths.append(path)
    return paths


def cpcv_metric_distribution(
    per_combo_returns: list[np.ndarray],
    n_samples: int,
    n_groups: int,
    k_test_groups: int,
    *,
    metric: Callable[[np.ndarray], float] | None = None,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """φ 条路径上各算一次 metric（默认年化 Sharpe）→ 返回**诚实分布**（非单点）。

    命门：绝不把分布压成漂亮单点；gate 应取保守分位（q05/min）。单策略**绝不**把 φ 路径当策略数喂 PBO。
    返回 dict 恒含全 key（min/q05/q25/median/q75/q95/max/frac_le_0/n_paths/n_paths_dropped/insufficient）——
    insufficient=True 时统计量为 NaN（形状对称，下游 .get('q05') 绝不把「全坏」误读成 0）。
    **饿死路径**（含 NaN = 调用方漏填 test 单元）记 NaN 剔除、计入 n_paths_dropped（可见非静默），
    **绝不**伪造成 0.0 污染 q05/min。`frac_le_0` 仅在 finite 路径上算；零波动退化路径 Sharpe=0 计入「≤0」（保守）。
    """

    paths = assemble_cpcv_paths(per_combo_returns, n_samples, n_groups, k_test_groups)
    fn = metric or (lambda r: sharpe_ratio(r, periods_per_year))
    # **命门**：未完整覆盖的路径（含 NaN = 调用方漏填 test 单元/饿死组合）记 NaN 剔除——**绝不**让默认
    # Sharpe 把空序列吞成假 0.0 污染保守分位 q05/min；剔除但**可见**（n_paths_dropped），非静默吞。
    raw = np.asarray([np.nan if np.any(np.isnan(p)) else float(fn(p)) for p in paths], dtype=float)
    finite = raw[np.isfinite(raw)]
    n_dropped = int(len(paths) - finite.size)
    keys = ("min", "q05", "q25", "median", "q75", "q95", "max", "frac_le_0")
    base = {"n_paths": int(len(paths)), "n_paths_dropped": n_dropped, "values": raw.tolist()}
    if finite.size == 0:
        # 形状对称：insufficient 分支也带全 key（=NaN），下游 .get('q05') 绝不把「全坏」误读成 0。
        return {**base, "insufficient": True, **{k: float("nan") for k in keys}}
    return {
        **base, "insufficient": False,
        "min": float(np.min(finite)), "q05": float(np.quantile(finite, 0.05)),
        "q25": float(np.quantile(finite, 0.25)), "median": float(np.median(finite)),
        "q75": float(np.quantile(finite, 0.75)), "q95": float(np.quantile(finite, 0.95)),
        "max": float(np.max(finite)),
        # frac_le_0 仅在 finite 路径上算；零波动退化路径 Sharpe=0 计入「≤0」（保守，docstring 已注）。
        "frac_le_0": float(np.mean(finite <= 0.0)),
    }


__all__ = [
    "CPCVSplit",
    "CPCV_DUAL_TRACK_CAVEAT",
    "CPCV_REALWORLD_SUPERIORITY_ESTABLISHED",
    "MAX_CPCV_COMBINATIONS",
    "assemble_cpcv_paths",
    "build_path_matrix",
    "cpcv_metric_distribution",
    "cpcv_splits",
    "n_cpcv_combinations",
    "n_cpcv_paths",
]
