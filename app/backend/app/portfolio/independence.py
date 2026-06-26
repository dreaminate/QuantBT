"""③ 因子族 → 组合「独立 bet」计数（卡 aa13c3b0 · §3 度量接生产路径）。

组合持仓跨**几个独立族**？同族因子不重复计独立性（R21 去重）。**复用单一锁定口径**
`eval.n_eff.n_eff_from_matrix`（与 `factor_factory.factor_families` 共用同一 `_cluster_labels @0.7`）——
绝不重造聚类、绝不暴露阈值入参（RULES.project「honest-N 不可手动改小」的组合层）。**返回 `NEffResult`**
（带 low/high 敏感性区间 + disclaimer），不新造冗余计数类型、不丢区间诚实度。

命门：
- 这是**去重 bet 计数**（point = 独立族数 = n_eff.point），**不是**风险加权 effective-number-of-bets：
  5 族但 99% 风险压一族**仍报 5**（honest_limit）。要风险加权 ENB 是**新公式**、需 MathematicalArtifact +
  会与锁定 n_eff 口径漂移——本卡**不引入**（无新公式则不强造）。
- **零权因子非 bet**：按 `weights` 剔零权列后再计数（剔零权=`weights` 的**唯一**用途；绝不用权重大小做
  HHI / 设 tiny-weight 阈值——那是另一套口径）。
- **绝不喂 DSR 的 `honest_n`**：那是过拟合通缩保守端兜底（honest-N 不可改小），本计数是**呈现 descriptor**、
  非 deflation floor。两者别串。
- **收益矩阵须 PIT 正确**（逐 bet 的 as-of-known 已实现收益）：含 look-ahead 会偏置族计数（调用方负责，
  同 `portfolio.gate.portfolio_net_returns` 的对齐纪律）。
"""

from __future__ import annotations

import numpy as np

from ..eval.n_eff import NEffResult, n_eff_from_matrix


def independent_bet_count(
    returns_matrix: np.ndarray,
    weights: np.ndarray | list[float] | None = None,
) -> NEffResult:
    """组合持仓的独立 bet 数 = `n_eff_from_matrix(持仓列)`（去重族计数，带敏感性区间）。

    `returns_matrix`：(T × N) 逐 bet 已实现收益（每列一条 bet/因子）。`weights`：与列对齐的权重；非 None 时
    **剔零权列**（零权=非持仓 bet），再对剩余列计独立族。`weights=None` → 全列计入。

    返回 `NEffResult`：`.point`=独立族数（同族坍缩）、`.low/.high`=阈值 ±0.1 敏感性区间、`.n_observed`=参与
    计数的持仓 bet 数（名义）、`.disclaimer`=启发式下界声明。**point ≡ factor_families(held).n_families ≡
    n_eff_from_matrix(held).point**（同一锁定口径，交叉校验）。
    """

    rm = np.asarray(returns_matrix, dtype=float)
    if rm.ndim != 2 or rm.shape[1] == 0:
        return n_eff_from_matrix(rm)   # 退化交给单一源 n_eff 诚实处理（0 列→0）

    if weights is not None:
        w = np.asarray(weights, dtype=float)
        if w.shape[0] != rm.shape[1]:
            raise ValueError(
                f"weights 长度 {w.shape[0]} 与收益矩阵列数 {rm.shape[1]} 不匹配（须逐列对齐）"
            )
        held = np.abs(w) > 0.0        # 非零权=持仓 bet（剔零权列）
        rm = rm[:, held]
        if rm.shape[1] == 0:
            return n_eff_from_matrix(rm)   # 全零权 → 0 个独立 bet

    return n_eff_from_matrix(rm)


__all__ = ["independent_bet_count"]
