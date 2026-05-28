"""M6 · Purged k-fold + Embargo + Walk-forward (López de Prado)。

为什么自写：mlfinlab 是付费包；这里 < 200 行覆盖核心语义：
- **Purged k-fold**：把训练集按时间排序，先做常规 k-fold，再把和测试集时间重合的
  训练样本剔除（避免标签泄漏）。
- **Embargo**：在测试集前后再多剔除 `embargo_pct * len(samples)` 条样本。
- **Walk-forward**：滚动训练 + 不重叠测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd


@dataclass
class FoldSplit:
    train_idx: np.ndarray
    test_idx: np.ndarray
    fold_index: int


def purged_kfold(
    times: pd.Series,
    n_splits: int = 5,
    embargo_pct: float = 0.01,
    t1: pd.Series | None = None,
) -> Iterator[FoldSplit]:
    """生成 Purged k-fold + Embargo 的 train/test indices。

    `times` 必须是按时间排序的 datetime-like Series；index 是样本编号。

    v0.8.7.1 学术 audit (patch1 §G.a #3 / §G.d):
    若提供 `t1` (每样本 label 结束时间)，会额外 purge train 中 t1 跨过 test 区间
    的样本（López de Prado 2018 §7.4.1）。t1 默认 None 时退化为旧行为。
    """

    if n_splits < 2:
        raise ValueError("n_splits 必须 >= 2")
    n_samples = len(times)
    indices = np.arange(n_samples)
    fold_size = n_samples // n_splits
    embargo = int(n_samples * embargo_pct)
    times_arr = np.asarray(times)
    t1_arr = np.asarray(t1) if t1 is not None else None

    for k in range(n_splits):
        start = k * fold_size
        end = (k + 1) * fold_size if k < n_splits - 1 else n_samples
        test_idx = indices[start:end]
        # 基础 train: 去除 test + embargo 窗
        base_left = indices[: max(0, start - embargo)]
        base_right = indices[min(n_samples, end + embargo) :]
        train_idx = np.concatenate([base_left, base_right])

        # 若有 t1，去除 train 中 t1 落入 test 时间区间的样本
        if t1_arr is not None and len(test_idx) > 0:
            test_t0 = times_arr[test_idx[0]]
            test_t1 = times_arr[test_idx[-1]]
            # train 样本的 (t0, t1) 与 test 的 (test_t0, test_t1) 不能重叠
            keep_mask = np.ones(len(train_idx), dtype=bool)
            for i, tr in enumerate(train_idx):
                tr_t0 = times_arr[tr]
                tr_t1 = t1_arr[tr]
                # 重叠条件：tr_t0 <= test_t1 AND tr_t1 >= test_t0
                if tr_t0 <= test_t1 and tr_t1 >= test_t0:
                    keep_mask[i] = False
            train_idx = train_idx[keep_mask]

        yield FoldSplit(train_idx=train_idx, test_idx=test_idx, fold_index=k)


def walk_forward(
    n_samples: int,
    train_size: int,
    test_size: int,
    step: int | None = None,
    embargo: int = 0,
) -> Iterator[FoldSplit]:
    """滚动窗口 walk-forward。

    train_size + embargo + test_size 必须 <= n_samples，否则第一个 fold 之外无效。
    """

    step = step or test_size
    fold = 0
    start = 0
    while start + train_size + embargo + test_size <= n_samples:
        train_end = start + train_size
        test_start = train_end + embargo
        test_end = test_start + test_size
        train_idx = np.arange(start, train_end)
        test_idx = np.arange(test_start, test_end)
        yield FoldSplit(train_idx=train_idx, test_idx=test_idx, fold_index=fold)
        fold += 1
        start += step


__all__ = ["FoldSplit", "purged_kfold", "walk_forward"]
