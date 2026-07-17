"""真 ERC（等风险贡献）solver · 独立模块（金融数学 kernel P0-A #8）。

**为何独立成模块**：命门指纹要抓「实现漂移」。``inspect.getsource(fn)`` 只取函数体、**不含**
模块级 import（``from scipy.linalg import cho_solve`` 等），故改 import 来源能悄改 solver 行为
而不触发 staleness（codex floor R1 #6）。把 solver 整体隔离到本模块 → ``spine_binding`` 指纹整个
模块文本（imports + 全部函数）→ 改任一 import/global/函数都触发 staleness。``inverse_volatility``
（对角 oracle）**留在 optimizers.py**、不进本模块——oracle 与 solver 两条独立代码路径。

数学：真 ERC = 唯一凸问题 min_{y>0} ½yᵀRy − (1/N)Σlog y_i（R=D⁻¹ΣD⁻¹ 相关矩阵）之解，映回
x=D⁻¹y、w=x/1ᵀx（Maillard-Roncalli-Teïletche 2010；Newton 见 Spinu 2013 / Griveau-Billion-
Richard-Roncalli 2013）。相关空间 damped Newton（Cholesky 解方向·Armijo 保正线搜·近解 f 平坦时
回退到「降 E_RC 即接受」·codex floor R2 #5）。数学口径 + fail-closed 经 codex/GPT-5.6-sol 授权裁决
（D-MATH-DECIDER）+ 两轮跨厂商 floor 复审（R1 6 洞 + R2 7 洞逐修）。

**scale-safe 关键（codex floor R2 #1）**：相关矩阵按**逐元素** R_ij=Σ_ij/(σ_iσ_j) 构造，**不**除
全局 max 方差——后者在强异方差（diag 跨 1e308）下会把小 off-diagonal 下溢成零、solver 悄解错问题
且有损后置检查看不到。逐元素归一每项按自身尺度、小相关不丢；后置 RC 复核在**相关空间**（无损）。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.linalg import LinAlgError, cho_factor, cho_solve


class ERCError(ValueError):
    """ERC solver fail-closed 错误：非法协方差 / 不收敛 / 权重下溢——绝不静默返回近似或等权。"""


# 硬接受地板：rc_tolerance（默认 1e-8）是收敛【目标】；个别良态矩阵因舍入不可达 1e-8，但只要 E_RC≤
# 此地板即视为可接受 ERC（命门 dense-RC 对账容差同 1e-6）。停滞短路 + 后置门都以此为准（codex R3 #1）。
_HARD_RC_FLOOR = 1e-6


def _cov_to_correlation_strict(sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """严格 scale-safe 协方差→相关矩阵（fail-closed；**不复用** optimizers._cov_to_corr）。

    **逐元素** R_ij=Σ_ij/(σ_iσ_j)（codex floor R2 #1）：每项按自身 σ_iσ_j 归一，故强异方差下小
    off-diagonal 不被全局尺度吞（旧「除全局 max 方差」会把 2e-16/1e308→0、丢真相关、solver 解错）。
    σ_iσ_j 对有限 SPD 恒有限（≤max(Σ_ii,Σ_jj)），无溢出。对称性在**相关尺度**逐元素检查（=相对）。
    返回 (corr, d)：corr=单位对角相关阵、d=原始 σ 向量（映回 w=D⁻¹y 用）。调用方已验 finite/real/方差>0。
    """

    n = sigma.shape[0]
    d = np.sqrt(np.diag(sigma))
    corr = sigma / np.outer(d, d)  # 逐元素归一（scale-safe·小相关不丢）
    np.fill_diagonal(corr, 1.0)
    asym = np.abs(corr - corr.T)
    np.fill_diagonal(asym, 0.0)
    max_asym = float(np.max(asym))
    if max_asym > 1e-10:
        raise ERCError(f"协方差非对称（相关尺度 {max_asym:.2e}>1e-10）")
    corr = 0.5 * (corr + corr.T)
    np.fill_diagonal(corr, 1.0)
    eig = np.linalg.eigvalsh(corr)
    lam_min, lam_max = float(eig[0]), float(eig[-1])
    guard = max(1e-12, 100.0 * n * float(np.finfo(float).eps)) * max(lam_max, 1.0)
    if lam_min <= guard:
        raise ERCError(
            f"相关矩阵非正定/近秩亏 λ_min={lam_min:.3e} ≤ {guard:.3e}（拒绝 clip/jitter/shrink）"
        )
    return corr, d


def _erc_newton_solve(
    corr: np.ndarray, *, rc_tolerance: float, max_iterations: int
) -> tuple[np.ndarray, int, float]:
    """相关空间凸对数障碍 damped Newton：min_{y>0} ½yᵀRy − (1/N)Σlog y_i。

    严格凸（∇²f=R+diag(b/y²)≻0），唯一内点解。方向由 Cholesky 解 H·p=−g（禁显式逆）；保正步长
    t_pos=min(1,0.99·min_{p_i<0}(−y_i/p_i)) 起，Armijo 回溯至 f 充分下降。**近解 f 平坦回退**（codex
    floor R2 #5）：Armijo 找不到 f 下降步时，若某保正步降 E_RC 则接受（避免良态 SPD 上卡在 ~2e-8）。
    收敛判据 = 相对风险贡献离散 E_RC=max|N·y_i(Ry)_i/(yᵀRy)−1|≤rc_tolerance（尺度不变）。不收敛即 raise。
    """

    n = corr.shape[0]
    b = 1.0 / n
    if max_iterations < 1:
        raise ERCError(f"max_iterations={max_iterations} < 1——无迭代预算无法收敛")
    total = float(np.sum(corr))
    if not (total > 0 and np.isfinite(total)):
        raise ERCError("相关矩阵行和非正——无法初始化")
    y = np.full(n, 1.0 / math.sqrt(total))
    e_rc = math.inf
    prev_e_rc = math.inf
    stall = 0

    def _f(yv: np.ndarray) -> float:
        return 0.5 * float(yv @ corr @ yv) - b * float(np.sum(np.log(yv)))

    def _e_rc_of(yv: np.ndarray) -> float:
        ryv = corr @ yv
        vv = float(yv @ ryv)
        if not (vv > 0 and np.isfinite(vv)):
            return math.inf
        return float(np.max(np.abs(n * (yv * ryv) / vv - 1.0)))

    for it in range(1, max_iterations + 1):
        g = corr @ y - b / y
        hess = corr + np.diag(b / (y * y))
        try:
            factor = cho_factor(hess, check_finite=True)
            p = cho_solve(factor, -g, check_finite=True)
        except (LinAlgError, ValueError) as exc:  # 非有限/非正定 → fail-closed
            raise ERCError(f"Newton Hessian 分解失败 @ iter {it}: {exc}") from exc
        neg = p < 0
        t_pos = min(1.0, 0.99 * float(np.min(-y[neg] / p[neg]))) if np.any(neg) else 1.0
        f0 = _f(y)
        g_dot_p = float(g @ p)
        e_rc_cur = _e_rc_of(y)
        stepped = False
        t = t_pos
        for _bt in range(50):  # Armijo on f（全局收敛）
            y_new = y + t * p
            if np.all(y_new > 0):
                f_new = _f(y_new)
                if np.isfinite(f_new) and f_new <= f0 + 1e-4 * t * g_dot_p:
                    y = y_new
                    stepped = True
                    break
            t *= 0.5
        if not stepped:  # f 近解平坦 → 回退：接受降 E_RC 的保正步（codex floor R2 #5）
            t = t_pos
            for _bt in range(50):
                y_cand = y + t * p
                if np.all(y_cand > 0) and _e_rc_of(y_cand) < e_rc_cur:
                    y = y_cand
                    stepped = True
                    break
                t *= 0.5
        if not stepped:
            if e_rc_cur <= _HARD_RC_FLOOR:  # 线搜停滞但已达硬地板·可接受返回（codex floor R6）
                return y, it, e_rc_cur
            raise ERCError(f"line search 停滞且 E_RC={e_rc_cur:g}>硬地板 {_HARD_RC_FLOOR:g} @ iter {it}")
        e_rc = _e_rc_of(y)
        if not np.isfinite(e_rc):
            raise ERCError("yᵀRy 非正——数值失效")
        if e_rc <= rc_tolerance:
            return y, it, e_rc
        # 停滞短路【仅在已达硬接受地板 1e-6 时】才返回（codex floor R3 #1）：否则早期 Armijo 非单调进展
        # 会把仍远离解的大残差矩阵误判为地板、过早返回 → 后置门 raise → 误拒可解 SPD（实证某矩阵早停
        # E_RC=10 却 14 迭代能收 1.6e-9）。E_RC>1e-6 时不停摆、继续迭代到预算耗尽（真不收敛才 raise）。
        if e_rc <= _HARD_RC_FLOOR and e_rc >= prev_e_rc * (1.0 - 1e-3):  # 已达地板且 <0.1% 改善
            stall += 1
            if stall >= 2:
                return y, it, e_rc  # 地板内停滞：返回·交后置门（1e-8 目标对个别矩阵因舍入不可达）
        else:
            stall = 0
        prev_e_rc = e_rc
    # 预算耗尽：已达硬地板即可接受返回（codex floor R6·rc_tolerance 是 best-effort 目标·硬保证=1e-6）；
    # 否则真不收敛 raise。使每条终止路径（收敛/停滞/线搜停滞/预算耗尽）都对硬地板同一裁定。
    if e_rc <= _HARD_RC_FLOOR:
        return y, max_iterations, e_rc
    raise ERCError(f"{max_iterations} 次迭代未达硬地板 {_HARD_RC_FLOOR:g}（最终 {e_rc:g}）")


def _erc_normalize_logdomain(y: np.ndarray, d: np.ndarray) -> np.ndarray:
    """log 域归一化 w ∝ D⁻¹y=y/σ（softmax 减最大值防上/下溢；下溢成零即 raise，绝不设 1e-9 floor）。"""

    ell = np.log(y) - np.log(d)
    ell = ell - float(np.max(ell))
    ex = np.exp(ell)
    s = float(np.sum(ex))
    if not (s > 0 and np.isfinite(s)):
        raise ERCError("归一化分母非正/非有限")
    w = ex / s
    if np.any(w <= 0) or not np.all(np.isfinite(w)):
        raise ERCError("权重下溢为零/非有限——拒绝（不设 1e-9 floor）")
    return w


def equal_risk_contribution(
    cov: pd.DataFrame, *, rc_tolerance: float = 1e-8, max_iterations: int = 100
) -> dict[str, float]:
    """真 Equal-Risk-Contribution（等风险贡献 / true risk parity）· long-only 全额投资。

    各标的对组合方差贡献相等：RC_i = w_i(Σw)_i/(wᵀΣw) = 1/N ∀i。见模块 docstring 的凸化 + 映回。
    **契约**（codex floor R4 #2）：``rc_tolerance`` 是收敛【目标】（默认 1e-8）；**硬保证** = 返回权重
    E_RC≤``_HARD_RC_FLOOR``（1e-6·个别良态矩阵因舍入不可达更紧目标·仍远优于命门 1e-6 精度）。
    fail-closed（codex floor R1 #3）：非 DataFrame / 非方阵 / index≠columns / 重复 label / **复数**（不丢
    虚部）/ 非有限 / 方差非正 / ``rc_tolerance`` 非正 → raise（**N=1 也全验**，只有真正 0×0 才返回 {}）；非
    SPD/近秩亏/超硬地板不收敛/权重下溢 → raise。后置 RC 复核【返回权重 w 本身】（codex R4 #1·非中间 y）。
    """

    if not isinstance(cov, pd.DataFrame):
        raise ERCError("cov 须为 pandas DataFrame")
    # rc_tolerance 契约（codex floor R4 #2 / R5 #3）：须有限正数（拒 0/负/NaN/非数值/**bool**——bool 是
    # int 子类会绕过 isinstance）。它是**收敛目标·仅能收紧到硬地板以下**；**硬保证**恒为返回
    # E_RC≤_HARD_RC_FLOOR（1e-6）——loose rc_tolerance 被夹到硬地板（见下 solve_tol），故不改可交付质量。
    if isinstance(rc_tolerance, bool) or not (
        isinstance(rc_tolerance, (int, float)) and math.isfinite(rc_tolerance) and rc_tolerance > 0.0
    ):
        raise ERCError(f"rc_tolerance 须有限正数（非 bool）: {rc_tolerance!r}")
    if cov.shape[0] != cov.shape[1]:
        raise ERCError(f"cov 非方阵 shape={cov.shape}（1×0 等非方阵拒绝）")
    syms = list(cov.columns)
    n = len(syms)
    if n == 0:
        return {}
    if list(cov.index) != syms:
        raise ERCError("cov index 与 columns 顺序/集合不一致")
    if len(set(syms)) != n:
        raise ERCError("存在重复标的 label")
    raw = cov.loc[syms, syms].values
    if np.iscomplexobj(raw):
        raise ERCError("cov 含复数——拒绝（不丢弃虚部）")
    sigma = np.asarray(raw, dtype=float)
    if not np.all(np.isfinite(sigma)):
        raise ERCError("cov 含非有限元素")
    if np.any(np.diag(sigma) <= 0):
        raise ERCError("方差非严格正")
    if n == 1:
        return {syms[0]: 1.0}
    corr, d = _cov_to_correlation_strict(sigma)
    # 求解目标 = min(rc_tolerance, 硬地板)（codex floor R5 #1）：loose rc_tolerance（如 1.0）不得让 solver
    # 早停于 E_RC>1e-6 而后置门误拒可解矩阵；tight rc_tolerance 则更严格（不达时 stall 兜底到硬地板）。
    solve_tol = min(float(rc_tolerance), _HARD_RC_FLOOR)
    y, _iters, e_rc = _erc_newton_solve(
        corr, rc_tolerance=solve_tol, max_iterations=max_iterations
    )
    w = _erc_normalize_logdomain(y, d)
    # 后置 fail-closed：sum=1 / 全正 + 校验【返回权重 w 本身】的 RC（codex floor R4 #1：不是 solver 的
    # y-based e_rc——log 域 softmax 归一有舍入·两者仅在精确算术相等·个别极端矩阵 w 的 E_RC 会超 y 的）。
    # u=σ⊙w∝y·尺度消去避 wᵀΣw 溢出：rc_i(w)=w_i(Σw)_i/(wᵀΣw)=u_i(Ru)_i/(uᵀRu)（R 逐元素相关·无损）。
    if abs(float(np.sum(w)) - 1.0) > 1e-9:
        raise ERCError(f"sum(w)={float(np.sum(w)):.3e} 偏离 1")
    if np.any(w <= 0) or not np.all(np.isfinite(w)):
        raise ERCError("权重非严格正/非有限")
    u = d * w
    ru = corr @ u
    vu = float(u @ ru)
    if not (vu > 0 and np.isfinite(vu)):
        raise ERCError("uᵀRu 非正/非有限")
    e_rc_w = float(np.max(np.abs(n * (u * ru) / vu - 1.0)))
    if e_rc_w > _HARD_RC_FLOOR:
        raise ERCError(f"返回权重 RC 后置校验失败 E_RC={e_rc_w:.3e}（softmax 归一舍入超地板 {_HARD_RC_FLOOR:g}）")
    return dict(zip(syms, w.tolist()))
