"""因子收益归因（returns-based factor attribution）—— 北极星 pipeline「归因」阶段。

组合实现收益 r_t 对 K 个因子收益时序回归（含截距）：r_t = α + Σ_k β_k F_{k,t} + ε_t。
分解：contrib_k = β̂_k·Σ_t F_{k,t}；specific = T·α̂ + Σ_t ε̂_t。
**命门加总恒等式**：Σ_k contrib_k + specific ≡ Σ_t r_t（逐位，纯代数；见 finding 推导）。

诚实（不假绿灯）：样本不足（T<K+2）→ insufficient、不出 β；共线（rank<K+1）→ collinear、不报不可识别 β；
近共线（cond 高）→ ok + warning（β 不稳）；非有限行剔除并披露。低 R² 如实报（收益多由特异驱动、非「已归因」）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np

_COND_WARN = 1e8        # condition number 阈值：满秩但超此 → β 不稳 warning
_EPS = 1e-12


@dataclass(frozen=True)
class AttributionResult:
    factor_contributions: dict[str, float]   # 各因子累计收益贡献 β̂_k·ΣF_k
    specific_contribution: float             # 特异（截距+残差）：T·α̂+Σε̂
    total_return: float                      # 组合总收益 Σr_t（== Σcontrib + specific，命门）
    betas: dict[str, float]                  # 因子暴露 β̂（collinear/insufficient 时空）
    alpha: float                             # 截距 α̂（insufficient 时 nan）
    r_squared: float                         # 因子解释占比（无定义→nan）
    status: Literal["ok", "insufficient", "collinear"]
    n_obs: int                               # 剔非有限后有效样本
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def factor_return_attribution(
    portfolio_returns: Sequence[float],
    factor_returns: dict[str, Sequence[float]],
) -> AttributionResult:
    """把组合实现收益分解为各因子贡献 + 特异收益（命门加总恒等式）。

    `portfolio_returns`/`factor_returns[k]` 等长（excess 或 raw 由调用方定，方法学不替拍）；不等长 → raise。
    """
    names = list(factor_returns.keys())
    k_fac = len(names)
    y_raw = np.asarray(list(portfolio_returns), dtype=float)
    n_raw = int(y_raw.size)
    # 长度契约：所有因子序列须与组合等长（否则归因对齐无意义）。
    for nm in names:
        if len(factor_returns[nm]) != n_raw:
            raise ValueError(f"factor_returns[{nm!r}] 长度 {len(factor_returns[nm])} ≠ 组合 {n_raw}（归因须等长对齐）")

    f_raw = (np.column_stack([np.asarray(list(factor_returns[nm]), dtype=float) for nm in names])
             if k_fac else np.empty((n_raw, 0)))
    # 非有限行整行剔除（保对齐）；披露剔除数。
    finite = np.isfinite(y_raw) & (np.isfinite(f_raw).all(axis=1) if k_fac else np.ones(n_raw, dtype=bool))
    y = y_raw[finite]
    f = f_raw[finite]
    n = int(y.size)
    n_dropped = n_raw - n
    warns: list[str] = []
    if n_dropped:
        warns.append(f"剔除 {n_dropped} 个非有限行（保对齐）")
    total = float(np.sum(y))

    def _abstain(status: str, extra: str) -> AttributionResult:
        return AttributionResult(
            factor_contributions={}, specific_contribution=total, total_return=total,
            betas={}, alpha=float("nan"), r_squared=float("nan"), status=status,  # type: ignore[arg-type]
            n_obs=n, warnings=tuple(warns + [extra]),
        )

    # 样本不足：需 ≥1 残差自由度 → n ≥ K+2。
    if n < k_fac + 2:
        return _abstain("insufficient", f"样本不足 n={n} < K+2={k_fac + 2}：回归无自由度、不出 β（证据不足）")

    x = np.column_stack([np.ones(n), f]) if k_fac else np.ones((n, 1))
    # 共线：rank<K+1 → β 不可识别，绝不报噪声 β。
    rank = int(np.linalg.matrix_rank(x))
    if rank < k_fac + 1:
        return _abstain("collinear", f"设计阵秩 {rank} < K+1={k_fac + 1}：因子共线/常数列，β 不可识别")
    cond = float(np.linalg.cond(x))
    if cond > _COND_WARN:
        warns.append(f"condition number {cond:.2e} 高：近共线、β̂ 不稳（解释占比仍可信，单因子归因谨慎）")

    beta_full, *_ = np.linalg.lstsq(x, y, rcond=None)
    alpha = float(beta_full[0])
    betas_arr = beta_full[1:] if k_fac else np.empty(0)
    resid = y - x @ beta_full
    # contrib_k = β̂_k·ΣF_k（独立于 specific 的公式 → 加总恒等式有真牙：contrib 算错则 Σ≠total）。
    fac_sum = f.sum(axis=0) if k_fac else np.empty(0)
    contributions = {names[i]: float(betas_arr[i] * fac_sum[i]) for i in range(k_fac)}
    # specific = T·α̂ + Σε̂（截距+残差），独立公式；与 Σcontrib 之和 ≡ total（命门）。
    specific = float(n * alpha + np.sum(resid))
    # R²：因子解释占比；SS_tot≈0（常数收益）→ 无定义。
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > _EPS else float("nan")
    if not np.isfinite(r2):
        warns.append("R² 无定义（收益近无波动）")

    return AttributionResult(
        factor_contributions=contributions,
        specific_contribution=specific,
        total_return=total,
        betas={names[i]: float(betas_arr[i]) for i in range(k_fac)},
        alpha=alpha,
        r_squared=r2,
        status="ok",
        n_obs=n,
        warnings=tuple(warns),
    )


__all__ = ["AttributionResult", "factor_return_attribution"]
