"""真 Ledoit-Wolf (2004) 协方差收缩 + 诚实固定-α · 独立模块（金融数学 kernel P0-A #8 续）。

修理论↔实现 mislabel（同 risk_parity/ERC 一类）：`hrp_audit.ledoit_wolf_shrinkage(cov,α=0.2)` 实为
**固定 α** ridge `(1-α)cov+α·tr(cov)/N·I`（docstring 自承「生产应 sklearn 自动估 α·这里固定 0.2」）。
真 Ledoit-Wolf 2004（"A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices"·JMVA
88(2):365-411）从 **raw returns** 解析估**最优**收缩强度 δ*，朝 scaled-identity 目标 μI 收缩：

    Σ* = (1−δ*)·S + δ*·μI,   S=XᵀX/T (MLE·非 ddof=1),  μ=tr(S)/N,  δ*=min(1, π̂/(T·γ̂))
    π̂=(1/T)Σ_t‖x_tx_tᵀ−S‖²_F,   γ̂=‖S−μI‖²_F

**codex/GPT-5.6-sol 授权数学裁决（D-MATH-DECIDER）**：公开 `ledoit_wolf` 用 classic/sklearn 口径
δ*=min(1,π̂/(Tγ̂))——**不**偷偷塞 ρ̂-corrected 式（后者 δ 差 ~0.047·非舍入·是另一 artifact）。impl
委托 `sklearn.covariance.LedoitWolf`（BSD·requirements 已声明·LW-2004 权威参考·shrinks 向 μI·手写
LW 与其数值到 1e-16 一致），命门 oracle 手写 outer-product 路径（另一条独立代码路径·见 binding）。
诚实命名：固定-α → `constant_shrinkage`；真 LW → `ledoit_wolf(returns)`；旧错标名 `ledoit_wolf_shrinkage`
保 DeprecationWarning shim（扩展不替换·出 __all__）。fail-closed：非法 returns/T<2/μ=0/非 SPD → raise。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.covariance import LedoitWolf


class CovarianceEstimationError(ValueError):
    """协方差估计 fail-closed 错误：非法 returns / 非有限 / T<2 / μ=0 / 非 SPD——绝不静默兜底或用坏协方差续算。"""


@dataclass(frozen=True)
class LedoitWolfResult:
    """真 LW 结果：covariance=Σ*（收缩后·well-conditioned）、shrinkage=δ*∈[0,1]、location=样本均值。"""

    covariance: np.ndarray
    shrinkage: float
    location: np.ndarray


def constant_shrinkage(cov: np.ndarray, *, alpha: float = 0.2) -> np.ndarray:
    """固定-α ridge 收缩 (1-α)·cov + α·tr(cov)/N·I 朝缩放单位阵——**非 Ledoit-Wolf**（α 不随数据自适应）。

    诚实名（原错标 `ledoit_wolf_shrinkage`）。要**最优数据驱动** δ* 用 :func:`ledoit_wolf`（从 returns 估）。
    fail-closed：α∉[0,1]/非数值/bool / cov 非方阵/非有限 → raise。
    """

    if isinstance(alpha, bool) or not (
        isinstance(alpha, (int, float)) and np.isfinite(alpha) and 0.0 <= alpha <= 1.0
    ):
        raise CovarianceEstimationError(f"alpha 须 [0,1] 有限数（非 bool）: {alpha!r}")
    c = np.asarray(cov, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1]:
        raise CovarianceEstimationError(f"cov 须方阵: shape={getattr(c, 'shape', None)}")
    if not np.all(np.isfinite(c)):
        raise CovarianceEstimationError("cov 含非有限元素")
    n = c.shape[0]
    target = np.eye(n) * (np.trace(c) / n)
    return (1.0 - alpha) * c + alpha * target


def _validate_returns(returns: np.ndarray, assume_centered: bool) -> tuple[np.ndarray, np.ndarray, int, int]:
    """returns fail-closed 校验 + 中心化。非 2D/复数/非有限/T<2/N<1 → raise。返回 (R, Xc, T, N)。"""

    raw = np.asarray(returns)
    if np.iscomplexobj(raw):
        raise CovarianceEstimationError("returns 含复数——拒绝")
    r = np.asarray(raw, dtype=float)
    if r.ndim != 2:
        raise CovarianceEstimationError(f"returns 须 2D (T×N): ndim={r.ndim}")
    t_obs, n_assets = r.shape
    if t_obs < 2:
        raise CovarianceEstimationError(f"T={t_obs} < 2：协方差估计需 ≥2 观测")
    if n_assets < 1:
        raise CovarianceEstimationError(f"N={n_assets} < 1")
    if not np.all(np.isfinite(r)):
        raise CovarianceEstimationError("returns 含非有限元素")
    if assume_centered:
        xc = r
    else:
        # scale-safe 中心化（codex floor5 #1）：先减 per-column 参考行 r[0]（去大常数）再减小残差的均值——
        # 避 `r.mean` 对大均值列 sum 溢出成 inf（`(r-r[0])-mean(r-r[0])` ≡ r-mean(r)·数学等价·数值 scale-safe）。
        d = r - r[0]
        xc = d - d.mean(axis=0)
    return r, xc, t_obs, n_assets


def ledoit_wolf(returns: np.ndarray, *, assume_centered: bool = False) -> LedoitWolfResult:
    """真 Ledoit-Wolf (2004) scaled-identity 收缩：Σ*=(1−δ*)S+δ*μI·δ*=min(1,π̂/(Tγ̂)) 数据驱动最优。

    impl 委托 sklearn.covariance.LedoitWolf（wrapper 先做 scale-safe centering·sklearn 在无量纲空间跑·
    covariance 逐元素乘回 scale²〔`(cov*scale)*scale`·避中间 scale² 上溢误拒可表示结果〕·δ* 尺度不变）。**契约**：δ* 是数据驱动最优（非固定 α）；δ*>0 时 Σ* 数学保证
    SPD（S 与 μI 的凸组合·λ_min≥δ*μ>0·含 T<N 秩亏 S 被正则化）；**δ*=0 时 Σ*=S 可能秩亏（如 T=2 对映
    或特定 T<N）→ 无条件 Cholesky fail-closed raise**（绝不返回非 SPD 协方差）。fail-closed：非法 returns/
    μ=0/scale² 下溢上溢/非有限/非 SPD → raise。
    命门绑定 + 独立手写 oracle 对账见 ``hrp_shrinkage_binding.py``。
    """

    r, xc, t_obs, n_assets = _validate_returns(returns, assume_centered)
    # location = per-column 均值·由 scale-safe xc 反推（r[0]−xc[0] ≡ 列均值·避 r.mean 大均值 sum 溢出·codex floor5 #1）
    location = np.zeros(n_assets) if assume_centered else r[0] - xc[0]
    # scale-safe：按最大幅度缩放已中心化 Xc → sklearn 无量纲空间跑 → covariance 乘回 scale²（δ* 尺度不变）
    scale = float(np.max(np.abs(xc)))
    if not (scale > 0 and np.isfinite(scale)):
        raise CovarianceEstimationError("中心化后 returns 全零/非有限（μ=0）——无法估计")
    xs = xc / scale
    fitted = LedoitWolf(store_precision=False, assume_centered=True).fit(xs)
    delta = float(fitted.shrinkage_)
    # 逐元素乘回 scale²：`(cov_dim*scale)*scale` 与无量纲 cov_dim(≲1) 交错·避免 `scale*scale` 中间上溢误拒
    # 可表示结果（codex floor3 #1：scale²=inf 不代表最终 Σ* 不可表示·如 δ*=1 时 Σ*=μ_dim·scale²·I 可能有限）。
    # 真不可表示（Σ* 溢出 inf / 分解溢出）由下方对称化后有限性 + Cholesky 因子有限性兜底 raise。
    with np.errstate(over="ignore", invalid="ignore"):  # 极端尺度中间可上溢→inf（预期 fail-closed 路·下方有限性检查兜底 raise·抑噪警）
        cov = (np.asarray(fitted.covariance_, dtype=float) * scale) * scale
    # 后置 fail-closed
    if not np.isfinite(delta) or not (-1e-12 <= delta <= 1.0 + 1e-12):
        raise CovarianceEstimationError(f"δ*={delta} 非有限/超 [0,1]")
    delta = min(1.0, max(0.0, delta))
    cov = 0.5 * cov + 0.5 * cov.T  # 对称化·overflow-safe（先各半再加·避 cov+cov.T 中间 2× 溢出成 inf·codex floor3 #1）
    if cov.shape != (n_assets, n_assets) or not np.all(np.isfinite(cov)):  # 对称化后再查（含 rescale/对称化溢出）
        raise CovarianceEstimationError(f"Σ* shape={getattr(cov, 'shape', None)}/非有限（rescale/对称化溢出或 sklearn 异常）")
    # 无条件 Cholesky（codex floor2 #1）：δ*=0 时 Σ*=S 可能秩亏（T=2 对映 / 特定 T<N → LW δ*=0 却 S 奇异），
    # 仅在 δ*>0 时查会漏返回非 SPD 协方差·违 fail-closed SPD 契约。SPD=估计器可用性硬门·恒查（δ*>0 well-cond 秒过）。
    try:
        chol = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError as exc:
        raise CovarianceEstimationError(
            f"Σ* 非 SPD（δ*={delta:.3e}·秩亏 S 未被收缩正则化〔δ*=0〕或浮点失效）: {exc}"
        ) from exc
    if not np.all(np.isfinite(chol)):  # Cholesky 因子非有限（极端尺度·cov 有限但分解溢出·codex floor3 #1）→ fail-closed
        raise CovarianceEstimationError(f"Σ* Cholesky 因子非有限（δ*={delta:.3e}·极端尺度分解溢出）")
    return LedoitWolfResult(covariance=cov, shrinkage=delta, location=location)


# 兼容 shim（codex 裁·扩展不替换）：旧错标名保留、DeprecationWarning、**出 __all__**。
def ledoit_wolf_shrinkage(cov: np.ndarray, shrinkage: float = 0.2) -> np.ndarray:
    """DEPRECATED·**非 Ledoit-Wolf**：固定-α 兼容别名（原错标名）。用 :func:`constant_shrinkage` 或真 :func:`ledoit_wolf`。"""

    warnings.warn(
        "ledoit_wolf_shrinkage 是固定-α（非真 Ledoit-Wolf）·已弃用；用 constant_shrinkage(cov,alpha=) "
        "或真 ledoit_wolf(returns)",
        DeprecationWarning,
        stacklevel=2,
    )
    return constant_shrinkage(cov, alpha=shrinkage)


__all__ = ["CovarianceEstimationError", "LedoitWolfResult", "constant_shrinkage", "ledoit_wolf"]
