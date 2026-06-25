"""因子收益归因 —— 消费侧报告构建器（组合台 / 归因报告端点用）。

`eval/attribution.py` 的 `factor_return_attribution` 是纯 math 件（命门加总恒等式 + 诚实
abstain），本模块把它接到消费侧：接真组合实现收益 + 用户所选因子收益矩阵 → 调 math →
产出 **JSON-safe** 报告（各因子贡献 + 特异 + R² + 加总恒等式自检 + 诚实 evidence_state + 单一源
note）。端点（main.py，由中心补一条薄路由）只需一行调本构建器，与现有
`get_run_attribution_response` 同范式。

不假绿灯（§0/§13 信任层）——本模块硬约束：
- abstain（insufficient / collinear）→ evidence_state 落 "insufficient"/"collinear"、**绝不给出 β**
  （math 件已 betas={}，此处不二次编造）。
- 低 R²（status=ok 但解释占比低 / 无定义）→ evidence_state 落 "specific_driven"、**绝不标 "已归因"**
  （收益主要由特异 / 未建模部分驱动）。explanatory power ≠ 策略质量：解释占比高也只落中性、不上成功绿
  （前端映射守，镜像 ColdStartStat 先例）。
- note 为**合规措辞单一源**（前端原样渲染、不二次拼措辞，防绕过 R7 措辞门）。

方法学不替拍（§0 user methodology autonomy）：因子集（factor_set_label）、收益口径（return_basis：
excess/raw）、回归窗（regression_window：full/rolling）由调用方（= 用户）定，本模块**原样回显**、
不替选。`low_explained_floor` 仅是「解释占比低」的**呈现启发阈值**（加弱点警示、绝不阻断 / 不伪造），
用户可覆盖。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .attribution import factor_return_attribution

# 加总恒等式数值容差（与 test_attribution 命门同口径）。
_IDENTITY_TOL_REL = 1e-9
_IDENTITY_TOL_ABS = 1e-12
# 「因子解释占比低」呈现默认阈值（启发式·非裁决·用户可覆盖）。
_DEFAULT_LOW_EXPLAINED_FLOOR = 0.30


def _jsonable(x: float) -> float | None:
    """非有限（nan/inf）→ None，保证严格 JSON 安全（前端不必处理 NaN 字面量）。"""
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def _round_map(d: dict[str, float], ndigits: int = 12) -> dict[str, float | None]:
    return {k: _jsonable(round(v, ndigits)) for k, v in d.items()}


def build_factor_attribution_report(
    portfolio_returns: Sequence[float],
    factor_returns: dict[str, Sequence[float]],
    *,
    factor_set_label: str | None = None,
    return_basis: str | None = None,
    regression_window: str | None = None,
    low_explained_floor: float = _DEFAULT_LOW_EXPLAINED_FLOOR,
) -> dict[str, Any]:
    """组合实现收益 + 因子收益矩阵 → 因子归因消费报告（JSON-safe，不假绿灯）。

    `portfolio_returns` / `factor_returns[k]` 等长（口径 excess/raw 由调用方定）；不等长 → math 件 raise。
    `low_explained_floor` 仅驱动「解释占比低」弱点警示，绝不阻断 / 不伪造绿灯。
    """
    res = factor_return_attribution(portfolio_returns, factor_returns)

    contributions = _round_map(res.factor_contributions)
    betas = _round_map(res.betas)
    specific = _jsonable(res.specific_contribution)
    total = _jsonable(res.total_return)
    r2 = _jsonable(res.r_squared)
    alpha = _jsonable(res.alpha)

    # 消费层加总恒等式自检（命门绑到端点输出）：Σcontrib + specific ?= total，逐位。
    recomposed = sum(res.factor_contributions.values()) + res.specific_contribution
    residual = recomposed - res.total_return
    tol = _IDENTITY_TOL_REL * max(1.0, abs(res.total_return)) + _IDENTITY_TOL_ABS
    identity_holds = math.isfinite(residual) and abs(residual) <= tol

    evidence_state, note = _evidence(res.status, res.r_squared, res.n_obs, len(factor_returns), low_explained_floor)

    return {
        "available": True,
        "status": res.status,
        "evidence_state": evidence_state,
        "factor_contributions": contributions,
        "specific_contribution": specific,
        "total_return": total,
        "betas": betas,
        "alpha": alpha,
        "r_squared": r2,
        "n_obs": res.n_obs,
        "identity": {
            "recomposed": _jsonable(round(recomposed, 12)),
            "residual": _jsonable(residual),
            "holds": bool(identity_holds),
        },
        "methodology": {
            "factor_set_label": factor_set_label,
            "return_basis": return_basis,
            "regression_window": regression_window,
            "low_explained_floor": low_explained_floor,
        },
        "note": note,
        "warnings": list(res.warnings),
    }


def _evidence(
    status: str, r2: float, n_obs: int, k_fac: int, floor: float
) -> tuple[str, str]:
    """math status + R² → 诚实 evidence_state + 单一源 note（R7-safe·无绝对化措辞）。

    绝不把 abstain / 低 R² 包装成「已归因」绿灯。
    """
    if status == "insufficient":
        return (
            "insufficient",
            f"样本不足（有效 n={n_obs} < K+2={k_fac + 2}）：因子回归无自由度、未给出 β —— "
            "证据不足，不归因到因子（先验断言，未经检验）。",
        )
    if status == "collinear":
        return (
            "collinear",
            "因子共线 / 设计阵秩亏：β 不可识别，未给出因子 β —— 证据不足（请检查所选因子集是否重复 / 线性相关）。",
        )
    # status == "ok"
    if r2 is None or not math.isfinite(r2):
        return (
            "specific_driven",
            "R² 无定义（组合收益近无波动）：因子解释占比无法估计，贡献仍按加总恒等式分解、但不标已归因。",
        )
    pct = r2 * 100.0
    if r2 < floor:
        return (
            "specific_driven",
            f"因子解释占比 {pct:.1f}%（低于呈现阈值 {floor * 100:.0f}%）：组合收益主要由特异 / 未建模部分驱动，"
            "未达可解释归因门槛 —— 不标已归因（阈值为呈现启发，可按方法学调整）。",
        )
    return (
        "factor_explained",
        f"因子解释占比 {pct:.1f}%：各因子贡献见分解，剩余归特异部分。适用域取决于所选因子集与收益口径"
        "（用户方法学）；解释占比为因子模型对已实现收益的拟合度、非策略质量结论。",
    )


__all__ = ["build_factor_attribution_report"]
