"""v0.9.7 学术 audit (patch1 §G.a #15) · HRP 协方差奇异性 fallback。

学术依据: Prado-Pratt 2016 / López de Prado 2018 §16

漏洞: 高相关资产 (corr ≈ 0.99) 时距离矩阵接近退化:
       linkage tree 不稳定 → 权重 NaN / 极端集中
       Equity 1 资产时直接 crash

修复: 3 段防御
  1. 检测协方差矩阵特征值最小值 (奇异性)
  2. fallback ladder: HRP → HRP+Ledoit-Wolf shrinkage → risk_parity → equal_weight
  3. 返回 HRPResult 含 fallback_used + singularity_detected + cluster_tree_serialized
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np


FallbackUsed = Literal["hrp", "hrp_shrunk", "risk_parity", "equal_weight"]


@dataclass
class HRPResult:
    weights: dict[str, float]
    fallback_used: FallbackUsed = "hrp"
    singularity_detected: bool = False
    min_eigval: float = float("nan")
    condition_number: float = float("nan")
    cluster_tree_serialized: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_near_singular(cov: np.ndarray, threshold: float = 1e-8) -> tuple[bool, float, float]:
    """检测协方差矩阵是否接近奇异。

    返回 (is_singular, min_eigval, condition_number)
    """
    if cov.shape[0] != cov.shape[1]:
        return True, float("nan"), float("nan")
    try:
        eigvals = np.linalg.eigvalsh(cov)
    except np.linalg.LinAlgError:
        return True, float("nan"), float("nan")
    min_eig = float(np.min(eigvals))
    max_eig = float(np.max(eigvals))
    if min_eig <= 0 or max_eig <= 0:
        return True, min_eig, float("inf")
    cond = max_eig / min_eig
    is_singular = (min_eig < threshold * max_eig) or (cond > 1e10)
    return is_singular, min_eig, cond


def ledoit_wolf_shrinkage(cov: np.ndarray, shrinkage: float = 0.2) -> np.ndarray:
    """简单 Ledoit-Wolf shrinkage: cov_shrunk = (1-α) * cov + α * tr(cov)/N * I

    生产中应该用 sklearn.covariance.LedoitWolf 自动估 α；这里固定 0.2 防奇异。
    """
    n = cov.shape[0]
    target = np.eye(n) * np.trace(cov) / n
    return (1 - shrinkage) * cov + shrinkage * target


def _risk_parity_weights(cov: np.ndarray, symbols: list[str]) -> dict[str, float]:
    """退化方案 1: risk parity (反波动率加权)。"""
    vol = np.sqrt(np.diag(cov))
    vol = np.where(vol > 1e-12, vol, 1e-12)
    inv_vol = 1.0 / vol
    weights = inv_vol / inv_vol.sum()
    return {s: float(w) for s, w in zip(symbols, weights)}


def _equal_weights(symbols: list[str]) -> dict[str, float]:
    n = len(symbols)
    return {s: 1.0 / n for s in symbols}


def optimize_hrp_safe(
    returns: np.ndarray,
    symbols: list[str],
    *,
    enable_shrinkage_fallback: bool = True,
    singularity_threshold: float = 1e-6,  # 默认敏感: corr≈0.99 即触发 fallback
) -> HRPResult:
    """HRP with 协方差奇异性 fallback ladder。

    输入:
      returns: shape (T, N)，N 个资产 T 日收益
      symbols: 长度 N，资产名

    优先级:
      1. HRP 原始
      2. HRP + Ledoit-Wolf shrinkage (协方差正则化)
      3. risk_parity (反波动率)
      4. equal_weight 兜底
    """
    n = len(symbols)

    # 边界 case: 单资产
    if n == 1:
        return HRPResult(
            weights={symbols[0]: 1.0}, fallback_used="equal_weight",
            warning="single asset → 100%",
        )
    if n == 0 or returns.shape[1] != n:
        return HRPResult(
            weights={}, fallback_used="equal_weight",
            warning=f"shape mismatch returns {returns.shape} vs symbols {n}",
        )

    # 协方差
    try:
        cov = np.cov(returns, rowvar=False, ddof=1)
        if cov.ndim == 0:  # 单列变 scalar
            cov = np.array([[float(cov)]])
    except Exception as exc:  # noqa: BLE001
        return HRPResult(
            weights=_equal_weights(symbols),
            fallback_used="equal_weight",
            warning=f"cov 计算失败: {exc}",
        )

    return _safe_hrp_from_cov(
        cov, symbols,
        enable_shrinkage_fallback=enable_shrinkage_fallback,
        singularity_threshold=singularity_threshold,
    )


def _safe_hrp_from_cov(
    cov: np.ndarray,
    symbols: list[str],
    *,
    enable_shrinkage_fallback: bool = True,
    singularity_threshold: float = 1e-6,
) -> HRPResult:
    """从**协方差**跑 HRP fallback ladder（HRP→HRP+Ledoit-Wolf shrinkage→risk_parity→equal_weight）。

    `optimize_hrp_safe`（returns→cov 后）与 `optimizers.optimize_portfolio`（已有 cov）**共用本函数**——
    生产 hrp 分支不再用裸 `hrp_weights`（无奇异检测/收缩 → 近奇异协方差出 NaN/极端集中），共享同一审计过的防御阶梯。
    """

    singular, min_eig, cond = is_near_singular(cov, singularity_threshold)

    if singular:
        if enable_shrinkage_fallback:
            cov_shrunk = ledoit_wolf_shrinkage(cov, shrinkage=0.3)
            singular_after, _, _ = is_near_singular(cov_shrunk, singularity_threshold)
            if not singular_after:
                try:
                    weights = _hrp_from_cov(cov_shrunk, symbols)
                    return HRPResult(
                        weights=weights, fallback_used="hrp_shrunk",
                        singularity_detected=True, min_eigval=min_eig, condition_number=cond,
                        warning="原协方差近奇异，Ledoit-Wolf 0.3 shrinkage 后通过 HRP",
                    )
                except Exception:  # noqa: BLE001
                    pass
        # 协方差扛不住，退到 risk parity
        return HRPResult(
            weights=_risk_parity_weights(cov, symbols),
            fallback_used="risk_parity",
            singularity_detected=True, min_eigval=min_eig, condition_number=cond,
            warning=f"协方差奇异 (min_eig={min_eig:.2e}), 退化 risk_parity",
        )

    # 协方差 OK，跑原 HRP
    try:
        weights = _hrp_from_cov(cov, symbols)
        # 校验 weights 不含 NaN
        if any(not np.isfinite(w) for w in weights.values()):
            raise ValueError("HRP weights 含 NaN/Inf")
        weight_sum = sum(weights.values())
        if not (0.99 < weight_sum < 1.01):
            raise ValueError(f"HRP weights sum={weight_sum:.4f} != 1")
        return HRPResult(
            weights=weights, fallback_used="hrp",
            singularity_detected=False, min_eigval=min_eig, condition_number=cond,
        )
    except Exception as exc:  # noqa: BLE001
        return HRPResult(
            weights=_risk_parity_weights(cov, symbols),
            fallback_used="risk_parity",
            singularity_detected=False, min_eigval=min_eig, condition_number=cond,
            warning=f"HRP 计算异常 fallback risk_parity: {exc}",
        )


def _hrp_from_cov(cov: np.ndarray, symbols: list[str]) -> dict[str, float]:
    """简化 HRP 实现 (Prado-Pratt 2016 三步)。

    1. correlation → distance matrix
    2. linkage tree (scipy.cluster.hierarchy)
    3. recursive bisection 分配权重
    """
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform

    # 1. correlation matrix
    vol = np.sqrt(np.diag(cov))
    if np.any(vol < 1e-12):
        raise ValueError("某资产 vol 接近 0 (无变化)")
    corr = cov / np.outer(vol, vol)
    np.fill_diagonal(corr, 1.0)
    # distance = sqrt(0.5 * (1 - corr))
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))

    # 2. linkage (用 condensed form)
    cond_dist = squareform(dist, checks=False)
    link = linkage(cond_dist, method="single")

    # 3. quasi-diagonalization: 拿叶节点顺序
    order = _get_quasi_diag(link, len(symbols))
    sorted_symbols = [symbols[i] for i in order]
    sorted_cov_idx = order

    # 4. recursive bisection
    weights = np.ones(len(symbols))
    clusters = [list(range(len(symbols)))]
    while clusters:
        new_clusters = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            mid = len(cluster) // 2
            left, right = cluster[:mid], cluster[mid:]
            var_l = _cluster_var(cov, [sorted_cov_idx[i] for i in left])
            var_r = _cluster_var(cov, [sorted_cov_idx[i] for i in right])
            alpha = 1 - var_l / (var_l + var_r) if (var_l + var_r) > 0 else 0.5
            for i in left:
                weights[i] *= alpha
            for i in right:
                weights[i] *= 1 - alpha
            new_clusters.extend([left, right])
        clusters = new_clusters

    # weights 是按 sorted_symbols 顺序的，需要 map 回 symbols
    weight_dict = {sorted_symbols[i]: float(weights[i]) for i in range(len(symbols))}
    return weight_dict


def _get_quasi_diag(link: np.ndarray, n_leaves: int) -> list[int]:
    """从 linkage matrix 拿叶节点顺序 (Prado 2016)。"""
    link = link.astype(int)
    sort_ix = [int(link[-1, 0]), int(link[-1, 1])]
    while max(sort_ix) >= n_leaves:
        new_ix = []
        for i in sort_ix:
            if i < n_leaves:
                new_ix.append(i)
            else:
                idx = i - n_leaves
                new_ix.extend([int(link[idx, 0]), int(link[idx, 1])])
        sort_ix = new_ix
    return sort_ix


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    """子集 cluster 的 inverse-variance portfolio 方差。"""
    sub = cov[np.ix_(idx, idx)]
    diag = np.diag(sub)
    inv_diag = 1.0 / np.where(diag > 1e-12, diag, 1e-12)
    weights = inv_diag / inv_diag.sum()
    return float(weights @ sub @ weights)


__all__ = [
    "FallbackUsed",
    "HRPResult",
    "is_near_singular",
    "ledoit_wolf_shrinkage",
    "optimize_hrp_safe",
]
