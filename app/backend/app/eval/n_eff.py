"""N_eff · 有效独立试验数（收益序列相关聚类）—— 试验账本算法层（T-015，接 T-013 一本账）。

为什么要它（R8/R19 + dossier §7）：honest-N 名义计数（distinct config_hash）会被「换等价
公式」撑大——`a*2` 与 `a+a` 是两个 config_hash（N_observed +2），但收益序列几乎相同、是
【同一个】有效试验。N_eff 用收益相关聚类把它们聚回一簇，给 DSR 通缩一个【不被等价写法稀释】
的有效 N。

诚实边界（裁决永远说「证据充分/不足」，绝不说「精确」）：
- N_eff 是**启发式、对阈值敏感、可被低报放水**的旋钮——故报【区间】[low, high] 非单点，
  并锁定口径版本（`NEFF_CONFIG_VERSION`），不可由请求参数随意改（防放水）。
- N_observed 本身只是真值下界（隐式试验不可观测，见 T-013 ledger）；N_eff 是它之上的进一步
  收缩估计，**同样是下界性质的启发式**。
- 不实现 ONC 全套 SOTA（dossier §7：ONC 缺独立复现、超参敏感）——只做「层次聚类 + 报敏感性
  区间 + 锁定口径」的保守版。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage as _hclust
from scipy.spatial.distance import squareform

# 口径版本：聚类法/阈值/区间宽度锁这里，改口径 = 升版本，不被请求参数覆盖（防放水）。
NEFF_CONFIG_VERSION = "v1"
_CORR_THRESHOLD = 0.7          # |相关| ≥ 0.7 视为同簇（中心点）
_THRESHOLD_BAND = 0.1          # 敏感性区间：阈值 ±0.1 给 low/high
_LINKAGE = "average"

_DISCLAIMER = (
    "有效独立 N 不可观测；此为收益相关聚类的启发式下界、对阈值敏感、可被低报放水，"
    "故报区间非精确计数。"
)


@dataclass
class NEffResult:
    point: int          # 中心阈值下的簇数 = N_eff 点估计
    low: int            # 更少簇（更低 N_eff）→ DSR 通缩不足端
    high: int           # 更多簇（更高 N_eff）→ DSR 通缩过度端
    n_observed: int     # distinct config 名义计数
    method: str
    is_heuristic: bool
    disclaimer: str

    def to_dict(self) -> dict:
        return asdict(self)


def _cluster_count(corr: np.ndarray, threshold: float, n: int) -> int:
    """给定相关阵与阈值，返回层次聚类簇数。阈值越高 → 合并越少 → 簇越多（N_eff 越大）。"""

    if n <= 1:
        return n
    dist = 1.0 - np.abs(corr)
    np.fill_diagonal(dist, 0.0)
    dist = np.nan_to_num(dist, nan=1.0)        # 常量列/无相关 → 距离 1 → 自成一簇
    dist = np.clip((dist + dist.T) / 2.0, 0.0, None)   # 对称化，去浮点不对称
    condensed = squareform(dist, checks=False)
    z = _hclust(condensed, method=_LINKAGE)
    labels = fcluster(z, t=1.0 - threshold, criterion="distance")
    return int(len(set(labels)))


def n_eff_from_matrix(returns_matrix: np.ndarray) -> NEffResult:
    """从 (T × N) 收益矩阵（每列一条试验的逐期收益）算 N_eff 区间。

    口径锁定（`NEFF_CONFIG_VERSION`）：阈值 0.7、区间 ±0.1、average linkage——不可由调用方改。
    """

    rm = np.asarray(returns_matrix, dtype=float)
    if rm.ndim != 2 or rm.shape[1] == 0:
        return NEffResult(0, 0, 0, 0, f"hierarchical/{_LINKAGE}@{_CORR_THRESHOLD}",
                          True, _DISCLAIMER)
    n = rm.shape[1]
    if n == 1:
        return NEffResult(1, 1, 1, 1, f"hierarchical/{_LINKAGE}@{_CORR_THRESHOLD}",
                          True, _DISCLAIMER)

    corr = np.corrcoef(rm, rowvar=False)
    corr = np.atleast_2d(corr)
    point = _cluster_count(corr, _CORR_THRESHOLD, n)
    # 阈值更低 → 合并更多 → 更少簇 = low；阈值更高 → 合并更少 → 更多簇 = high。
    low = _cluster_count(corr, max(0.0, _CORR_THRESHOLD - _THRESHOLD_BAND), n)
    high = _cluster_count(corr, min(1.0, _CORR_THRESHOLD + _THRESHOLD_BAND), n)
    lo, hi = min(low, high), max(low, high)
    return NEffResult(
        point=point, low=lo, high=hi, n_observed=n,
        method=f"hierarchical/{_LINKAGE}@{_CORR_THRESHOLD}",
        is_heuristic=True, disclaimer=_DISCLAIMER,
    )


__all__ = ["NEFF_CONFIG_VERSION", "NEffResult", "n_eff_from_matrix"]
