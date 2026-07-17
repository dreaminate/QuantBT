"""v0.9.7 学术 audit (patch1 §G.a #15) · HRP 协方差奇异性 fallback。

学术依据: Prado-Pratt 2016 / López de Prado 2018 §16

漏洞: 高相关资产 (corr ≈ 0.99) 时距离矩阵接近退化:
       linkage tree 不稳定 → 权重 NaN / 极端集中
       Equity 1 资产时直接 crash

修复: 3 段防御
  1. 检测协方差矩阵特征值最小值 (奇异性)
  2. fallback ladder: HRP → HRP+Ledoit-Wolf shrinkage → inverse_volatility（反波动率·非真 ERC）；空/单资产走 equal_weight
  3. 返回 HRPResult 含 fallback_used + singularity_detected + cluster_tree_serialized
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

from ._lw_shrinkage import (
    CovarianceEstimationError,
    LedoitWolfResult,
    _validate_returns,  # 输入契约 fail-closed（codex floor2 #2·非法 returns 不得伪装成权重）
    constant_shrinkage,
    ledoit_wolf,
    ledoit_wolf_shrinkage,  # 兼容 shim re-export（out of __all__·DeprecationWarning·固定-α 非真 LW）
)


FallbackUsed = Literal["hrp", "hrp_shrunk", "inverse_volatility", "equal_weight"]


@dataclass
class HRPResult:
    weights: dict[str, float]
    fallback_used: FallbackUsed = "hrp"
    singularity_detected: bool = False
    min_eigval: float = float("nan")  # **无量纲空间**（xc/cscale 归一后·raw ≈ min_eigval × normalization_scale²·codex floor5 #3）
    condition_number: float = float("nan")  # 条件数尺度不变（raw 与归一同值·无单位）
    normalization_scale: float = float("nan")  # cscale = max|xc|（诊断的无量纲化尺度·codex floor5 #3·min_eigval 的 raw 换算因子²）
    lw_shrinkage: float = float("nan")  # 真 Ledoit-Wolf 数据驱动 δ*（hrp_shrunk 路径填·非固定 α·尺度不变）
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
    if not np.all(np.isfinite(cov)):  # 非有限（NaN/inf）协方差 → fail-closed 视奇异·绝不当健康（codex floor3 #3）
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


def _inverse_volatility_weights(cov: np.ndarray, symbols: list[str]) -> dict[str, float]:
    """退化方案：inverse-volatility（反波动率 w∝1/σ·**仅用对角·非真 risk parity/ERC**——不含相关性·codex floor4 #4）。"""
    vol = np.sqrt(np.diag(cov))
    vol = np.where(vol > 1e-12, vol, 1e-12)
    inv_vol = 1.0 / vol
    weights = inv_vol / inv_vol.sum()
    return {s: float(w) for s, w in zip(symbols, weights)}


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

    优先级 (fallback ladder·全局尺度归一后计算·权重尺度不变):
      1. HRP 原始（协方差良态）
      2. HRP + Ledoit-Wolf shrinkage（近奇异 → 数据驱动 δ* 正则化）
      3. inverse_volatility（反波动率 w∝1/σ·**非真 risk parity/ERC**·仍近奇异时降级）
    （空组合 / 单资产走 equal_weight 短路返回）
    """
    n = len(symbols)
    arr = np.asarray(returns)

    # 输入契约 fail-closed（codex floor2 #2）：非法 returns（NaN/inf/复数/T<2/N<1/非 2D/列数≠symbols）
    # 绝不伪装成 inverse-vol 权重续算。空组合（0 资产·0 列）= 合法 no-op → {}。区别于"合法有限非零但近奇异
    # 数据"（走下方 fallback ladder 优雅降级）——input-contract 违反 vs 合法数据的估计器退化。
    if n == 0 and arr.ndim == 2 and arr.shape[1] == 0:
        return HRPResult(weights={}, fallback_used="equal_weight", warning="empty portfolio")
    r, xc, _t, _n = _validate_returns(returns, assume_centered=False)  # 非法 → CovarianceEstimationError（传播·不吞）
    if r.shape[1] != n:
        raise CovarianceEstimationError(f"returns 列数 {r.shape[1]} ≠ symbols {n}")
    # symbol 身份 fail-closed（codex floor4 #3）：唯一 + 非空 str（None/""/纯空白 → dict 键塌缩·不可哈希 → raw TypeError）。
    for s in symbols:
        if not isinstance(s, str) or not s.strip() or s != s.strip():
            raise CovarianceEstimationError(f"symbol 须非空 str 且无首尾空白（防 None/空/纯空白/别名塌缩·不可哈希）: {s!r}")
    if len(set(symbols)) != n:  # 重复/非唯一 → dict 塌缩·权重不和 1
        raise CovarianceEstimationError(f"symbols 含重复/非唯一: {symbols}")
    # 零方差 fail-closed（codex floor3 #2）：全零/常数 returns（中心化 scale=0·μ=0·零方差）→ 无法估协方差·
    # 绝不经单资产分支 / fallback 关路伪装成权重（放两条短路前·_validate_returns 只查格式·够不着 μ=0）。
    cscale = float(np.max(np.abs(xc)))
    if not (cscale > 0.0 and np.isfinite(cscale)):
        raise CovarianceEstimationError("returns 全零/常数（中心化 scale=0·μ=0·零方差）——无法估协方差")

    # 边界 case: 单资产（契约已过）
    if n == 1:
        return HRPResult(
            weights={symbols[0]: 1.0}, fallback_used="equal_weight",
            warning="single asset → 100%",
        )

    # 全局尺度归一（codex floor4 #2）：HRP/inverse-vol/LW 的权重与 δ* 对正全局尺度不变——在无量纲 xn=xc/cscale
    # 上算 np.cov/奇异性/LW/HRP，消 raw 单位 overflow（大尺度 np.cov→inf 误 raise）与 underflow（小尺度 vol 触
    # 1e-12 地板→伪等权）。返回权重与 raw 恒等；诊断（min_eig/cond）在无量纲空间（cond 尺度不变·min_eig 无量纲·诚实报）。
    xn = xc / cscale
    # 动态范围 fail-closed（codex floor5 #2）：全局 cscale 归一把远小于 max 尺度（比值≲1e-12）的非常数列压到 vol
    # 精度地板下/下溢成 0 → inverse-vol 触地板 / HRP corr 失真出伪权重（非静默错权）。检出即 raise。
    # （全动态范围保真 HRP〔per-column log-space 协方差〕登记 follow-on；此处 fail-closed 守 correctness。）
    col_scale = np.max(np.abs(xc), axis=0)
    col_vol_n = np.std(xn, axis=0)
    if np.any((col_scale > 0.0) & (col_vol_n <= 1e-12)):
        raise CovarianceEstimationError(
            "returns 列间尺度差过大（全局归一后某非常数列 vol 压至精度地板下）——请分组/标准化后再估（动态范围失真）"
        )

    # 协方差（无量纲空间）
    try:
        cov = np.cov(xn, rowvar=False, ddof=1)
        if cov.ndim == 0:  # 单列变 scalar
            cov = np.array([[float(cov)]])
    except Exception as exc:  # noqa: BLE001
        raise CovarianceEstimationError(f"np.cov 计算失败: {exc}") from exc  # 不吞成等权（codex floor3 #3）
    if not np.all(np.isfinite(cov)):  # 防御·非有限 fail-closed（归一后近不可达·非当健康·codex floor3 #3）
        raise CovarianceEstimationError("np.cov 非有限——无法估")

    singular, min_eig, cond = is_near_singular(cov, singularity_threshold)

    if singular:
        if enable_shrinkage_fallback:
            # 合法数据近奇异 → 真 LW 正则化。LW RAISE（μ=0 全零/δ*=0 秩亏/scale 溢/非 SPD）=数据退化到无法
            # 估协方差 → 传播（不吞成 inverse-vol 伪权重·codex floor2 #2）。"LW 成功但 Σ* 仍近奇异"→ 下方 inverse_volatility。
            lw = ledoit_wolf(xn)  # 真 Ledoit-Wolf·喂无量纲 xn（δ* 尺度不变·与 raw 恒等）；退化数据 raise 传播
            cov_shrunk, lw_delta = lw.covariance, lw.shrinkage
            singular_after, _, _ = is_near_singular(cov_shrunk, singularity_threshold)
            if not singular_after:
                try:
                    weights = _hrp_from_cov(cov_shrunk, symbols)
                    return HRPResult(
                        weights=weights, fallback_used="hrp_shrunk",
                        singularity_detected=True, min_eigval=min_eig, condition_number=cond, normalization_scale=cscale,
                        lw_shrinkage=lw_delta,
                        warning=f"原协方差近奇异，Ledoit-Wolf estimated δ*={lw_delta:.4f} 后通过 HRP",
                    )
                except Exception:  # noqa: BLE001
                    pass
        # 协方差扛不住，退到 inverse-volatility（**非真 risk parity/ERC**·仅反波动率·codex floor4 #4）
        return HRPResult(
            weights=_inverse_volatility_weights(cov, symbols),
            fallback_used="inverse_volatility",
            singularity_detected=True, min_eigval=min_eig, condition_number=cond, normalization_scale=cscale,
            warning=f"协方差奇异 (min_eig={min_eig:.2e}), 退化 inverse_volatility（反波动率·非真 ERC）",
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
            singularity_detected=False, min_eigval=min_eig, condition_number=cond, normalization_scale=cscale,
        )
    except Exception as exc:  # noqa: BLE001
        return HRPResult(
            weights=_inverse_volatility_weights(cov, symbols),
            fallback_used="inverse_volatility",
            singularity_detected=False, min_eigval=min_eig, condition_number=cond, normalization_scale=cscale,
            warning=f"HRP 计算异常 fallback inverse_volatility: {exc}",
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
    "CovarianceEstimationError",
    "FallbackUsed",
    "HRPResult",
    "LedoitWolfResult",
    "constant_shrinkage",
    "is_near_singular",
    "ledoit_wolf",
    "optimize_hrp_safe",
]
# 注：``ledoit_wolf_shrinkage``（固定-α·**非真 LW**）保留可 direct import（DeprecationWarning shim·
# 自 _lw_shrinkage re-export）但**出 __all__**——诚实降级旧错标名（codex floor 裁·扩展不替换）。
