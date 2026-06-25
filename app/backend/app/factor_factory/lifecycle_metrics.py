"""§3 · 因子机构级生命周期度量（衰减半衰期 / 容量 / 因子族 / 拥挤）。

GOAL §3「机构级因子生命周期（衰减/拥挤/容量/因子族/退役，跨策略复用的独立资产）」。
设计/推导见 `dev/research/findings/dreaminate/factor-lifecycle-institutional.md`。本模块是**度量层**——
产出喂 `lifecycle.py` 状态机 / sizing 的输入；扩展不替换（lifecycle.py toy 五态机不动）。

**命门（correctness · 数学↔实现一致 · 不假绿灯）**：
- **半衰期绝不 clip ρ**：ρ≥1（爆炸/非平稳）/ρ≤0（反转）须诚实判 undefined/no_persistence，**绝不**夹逼成
  看似正常的有限半衰期喂退役（理论对实现跑偏=全盘皆输）。
- **容量 α 与 τ/σ/ADV 必须同周期**；α≤0→容量 0（no_edge）；τ=0/σ=0/ADV=0→invalid，**绝不返普通数值**。
- **因子族复用 n_eff 锁定聚类口径**（同一 |corr|≥0.7 合并），`n_families==n_eff.point` 交叉校验（绑 honest-N）。
- **拥挤=定性咨询，结构上无任何减仓/动作字段**（GOAL §3「加密拥挤数据不足→只定性警示、禁自动减仓」，
  R19）；`missing ≠ 拥挤 0`（数据不足→data_status=insufficient，绝不编码成 none）；要减仓须人工批准
  policy adapter、**绝不**在本模块暗加。

文献锚：AR(1) 持久性半衰期（标准 mean-reversion）；sqrt 市场冲击 Almgren/Kyle（R18 δ=0.5）；
因子去重相关聚类（López de Prado / R21）；honest-N 聚类口径（R8/R19，`eval/n_eff.py`）。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np

from ..eval.n_eff import _CORR_THRESHOLD, _LINKAGE, NEFF_CONFIG_VERSION, _cluster_labels

_EPS = 1e-12
DEFAULT_IMPACT_COEF = 0.1   # sqrt-impact 系数 Y（无量纲，用户/数据应提供；默认占位、用即告警）
_CAPACITY_DELTA = 0.5       # R18 锁定：平方根冲击 δ=0.5 窄带（不暴露为入参，防口径漂移）
# AR(1) 近单位根边界：ρ̂>此值 = local-to-unity，OLS 推断不可靠、半衰期弱识别 → 判 unstable，
# **绝不对随机游走发 status=ok**（命门：机器可读门不假绿灯）。代价：真 ρ∈(0.95,1) 的高持久因子也被
# 判 unstable（诚实——其半衰期 CI 本就跨 ~8 到 ∞、不可靠）。这是诚实下界、非精确分类（用户可看 ρ̂/h 自判）。
_UNIT_ROOT_BOUNDARY = 0.95
# 拥挤等级阈值（锁定·不暴露入参，防放水压低 elevated 警示——与 n_eff/factor_families 锁定口径同纪律）。
_CROWD_ELEVATED_CORR = 0.7
_CROWD_WATCH_CORR = 0.4


# ===========================================================================
# ① 衰减半衰期（AR(1) 持久性）
# ===========================================================================


@dataclass(frozen=True)
class DecayEstimate:
    rho: float                  # AR(1) 持久性系数（NaN=不可估）
    half_life: float            # ln(0.5)/ln(ρ)；inf=不衰减；NaN=undefined/反转
    status: Literal["ok", "no_decay", "reversal", "no_persistence", "undefined", "unstable", "insufficient"]
    n_obs: int                  # 估计用的 AR(1) 配对样本数（=有限 IC 滞后对数，跨 NaN 缺口的对已丢）
    method: str = "ar1"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def ic_decay_half_life(ic_series: np.ndarray, *, min_periods: int = 30) -> DecayEstimate:
    """从 IC 时序估 AR(1) 持久性半衰期 h=ln(0.5)/ln(ρ)。**绝不 clip ρ**（ρ≥1/≤0 诚实判异常）。

    短样本 OLS 偏 ρ 向下（local-to-unity）→ ρ 置信区间跨 0 或 1 判 unstable（不作硬退役依据）。
    """

    arr = np.asarray(ic_series, dtype=float)
    # **绝不先 arr[isfinite] 压扁**（会把 NaN 缺口两侧拼成 1 期 AR(1) 样本、污染 ρ）：在原时间轴建滞后对，
    # 只丢 (t−1,t) 任一端非有限的对（保对齐，codex 顾问 P2）。
    x_full, y_full = arr[:-1], arr[1:]
    pair_mask = np.isfinite(x_full) & np.isfinite(y_full)
    x, y = x_full[pair_mask], y_full[pair_mask]
    n_pairs = int(x.size)
    if n_pairs < min_periods:
        return DecayEstimate(float("nan"), float("nan"), "insufficient", n_pairs,
                             warnings=(f"有效滞后对不足 {n_pairs}<{min_periods}（跨 NaN 缺口的对已丢）",))
    if float(np.var(x)) < _EPS:
        return DecayEstimate(float("nan"), float("nan"), "insufficient", n_pairs,
                             warnings=("lagged IC 方差≈0，ρ 不可识别",))
    # OLS y = c + ρ·x（含截距，等价去均值）
    xm, ym = x.mean(), y.mean()
    sxx = float(np.sum((x - xm) ** 2))
    rho = float(np.sum((x - xm) * (y - ym)) / sxx)
    resid = y - (ym + rho * (x - xm))
    dof = n_pairs - 2
    se = math.sqrt(float(np.sum(resid ** 2)) / dof / sxx) if dof > 0 and sxx > 0 else float("inf")
    ci_lo, ci_hi = rho - 1.96 * se, rho + 1.96 * se
    warns: list[str] = []
    # 异常区（绝不 clip）
    if rho >= 1.0:
        return DecayEstimate(rho, float("inf"), "no_decay", n_pairs,
                             warnings=("ρ≥1：非平稳/爆炸，无有限衰减半衰期",))
    if rho <= 0.0:
        if rho <= -1.0:
            return DecayEstimate(rho, float("nan"), "undefined", n_pairs,
                                 warnings=(f"ρ={rho:.3f}≤−1：非平稳震荡",))
        # −1<ρ≤0：仅当 ρ̂ **显著**<0（CI 整体 <0）才判 reversal（反持久/震荡）；CI 含 0 → ρ̂ 与 0 不可辨 →
        # **no_persistence**（IC 无显著自相关=不可由自身过去预测，**非反转、非持久**）。诚实：绝不把 ρ̂≈0 的
        # 白噪 IC 过claim 成「反转」（reversal 是 anti-persistent 的实质结论、须显著负方可下）。
        if ci_hi >= 0.0:
            return DecayEstimate(rho, float("nan"), "no_persistence", n_pairs,
                                 warnings=(f"ρ̂={rho:.3f}（95% CI [{ci_lo:.3f},{ci_hi:.3f}] 含 0）：IC 无显著自相关、"
                                           "无持久性（非反转/非持久），半衰期不适用",))
        return DecayEstimate(rho, float("nan"), "reversal", n_pairs,
                             warnings=(f"ρ̂={rho:.3f}（CI 上界 {ci_hi:.3f}<0）：显著反持久/震荡，正向持久半衰期不适用",))
    # 0<ρ<1：有限半衰期
    h = math.log(0.5) / math.log(rho)
    status: str = "ok"
    if ci_lo <= 0.0 or ci_hi >= 1.0 or rho > _UNIT_ROOT_BOUNDARY:
        status = "unstable"
        warns.append(
            f"ρ̂={rho:.3f} 近单位根(>{_UNIT_ROOT_BOUNDARY})或 CI 跨 0/1：local-to-unity 弱识别、OLS 推断不可靠，"
            "半衰期不作硬退役依据（机器门绝不对随机游走发 ok；ρ̂/h 仍返供人工自判）"
        )
    return DecayEstimate(rho, float(h), status, n_pairs, warnings=tuple(warns))  # type: ignore[arg-type]


# ===========================================================================
# ② 容量（sqrt 市场冲击 δ=0.5）
# ===========================================================================


@dataclass(frozen=True)
class CapacityEstimate:
    capacity: float             # 容量（金额，单位同 ADV）；0=no_edge；NaN=invalid
    status: Literal["ok", "no_edge", "invalid"]
    method: str
    params: dict[str, float] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def strategy_capacity(
    gross_alpha: float,
    turnover: float,
    adv: float,
    volatility: float,
    *,
    impact_coef: float | None = None,
) -> CapacityEstimate:
    """sqrt 市场冲击容量 C=(ADV/τ)·(α/(τYσ))^(1/δ)；δ=0.5（R18 锁定）→ C=ADV·α²/(τ³Y²σ²)。

    **δ=0.5 锁定不暴露入参**（R18「平方根冲击 δ=0.5 窄带」；若可调则 cost(C)≈α 自检对错 δ 循环无效）。
    **α 与 τ/σ/ADV 须同周期**（年化 α 配日频 cost=错）。α≤0→容量 0（no_edge）；τ/σ/ADV/Y≤0→invalid（绝不返普通数值）。
    `impact_coef`(Y) **须用户/数据提供**；省略则用占位 0.1 + **诚实告警**（绝不让占位冒充数据驱动容量）。回代 cost(C)≈α 自检。
    """

    delta = _CAPACITY_DELTA
    y_is_placeholder = impact_coef is None
    Y = DEFAULT_IMPACT_COEF if y_is_placeholder else impact_coef
    params = {"turnover": turnover, "adv": adv, "volatility": volatility, "impact_coef": Y, "delta": delta}
    method = f"sqrt_impact@δ={delta}"
    if not all(math.isfinite(v) for v in (gross_alpha, turnover, adv, volatility, Y)):
        return CapacityEstimate(float("nan"), "invalid", method, params, ("含非有限参数",))
    if turnover <= 0 or adv <= 0 or volatility <= 0 or Y <= 0:
        return CapacityEstimate(float("nan"), "invalid", method, params, ("τ/σ/ADV/Y 须 >0（冲击模型不适用）",))
    placeholder_warn: tuple[str, ...] = (
        ("impact_coef(Y) 用占位默认 0.1、非数据估计——容量量级仅示意，须接真实冲击系数",) if y_is_placeholder else ()
    )
    if gross_alpha <= 0:
        return CapacityEstimate(0.0, "no_edge", method, params, ("α_gross≤0：无 edge，无正盈利容量",) + placeholder_warn)
    capacity = (adv / turnover) * (gross_alpha / (turnover * Y * volatility)) ** (1.0 / delta)
    # 自检：cost(C) 回代应≈α
    cost = turnover * Y * volatility * (turnover * capacity / adv) ** delta
    warns = placeholder_warn
    if abs(cost - gross_alpha) > 1e-6 * max(1.0, abs(gross_alpha)):
        warns = warns + (f"自检偏差 cost(C)={cost:.3g} vs α={gross_alpha:.3g}（实现疑漂）",)
    return CapacityEstimate(float(capacity), "ok", method, params, warns)


# ===========================================================================
# ③ 因子族（R21 去重 · 复用 n_eff 锁定聚类口径）
# ===========================================================================


@dataclass(frozen=True)
class FactorFamilies:
    labels: tuple[int, ...]     # 每个因子的族 id（membership 才重要，编号无意义）
    n_families: int             # 有效独立因子数（= n_eff cluster count，交叉校验）
    n_factors: int
    corr_threshold: float
    method: str
    config_version: str

    def to_dict(self) -> dict:
        return asdict(self)


def factor_families(returns_matrix: np.ndarray) -> FactorFamilies:
    """收益相关聚类把等价/高相关因子坍缩成族（R21 去重）。复用 n_eff 锁定口径 → n_families==n_eff.point。

    **阈值锁定不可调（防放水，RULES.project「honest-N 不可手动改小」的因子族层）**：用 n_eff 的 `_CORR_THRESHOLD`，
    **刻意不暴露 corr_threshold 入参**——调用方若能改阈值，就能在不同聚类规则下放水、且静默破坏
    `n_families==n_eff.point` 交叉校验（n_eff 仍锁 0.7）。改口径=升 NEFF_CONFIG_VERSION，不是请求参数。
    """

    rm = np.asarray(returns_matrix, dtype=float)
    method = f"hierarchical/{_LINKAGE}@{_CORR_THRESHOLD}"
    if rm.ndim != 2 or rm.shape[1] == 0:
        return FactorFamilies((), 0, 0, _CORR_THRESHOLD, method, NEFF_CONFIG_VERSION)
    n = rm.shape[1]
    if n == 1:
        return FactorFamilies((0,), 1, 1, _CORR_THRESHOLD, method, NEFF_CONFIG_VERSION)
    corr = np.atleast_2d(np.corrcoef(rm, rowvar=False))
    labels = _cluster_labels(corr, _CORR_THRESHOLD, n)
    return FactorFamilies(tuple(int(x) for x in labels), int(len(set(labels))), n,
                          _CORR_THRESHOLD, method, NEFF_CONFIG_VERSION)


# ===========================================================================
# ④ 拥挤（定性咨询 · GOAL §3 禁自动减仓）
# ===========================================================================


@dataclass(frozen=True)
class CrowdingAdvisory:
    """拥挤**定性咨询**——刻意**只含咨询字段**（level/data_status/evidence），**绝无** reduce_position/
    haircut/multiplier/trade_action/target_weight：GOAL §3「加密拥挤数据不足→只定性警示、禁自动减仓」。
    sizing 模块不接受本类型；要减仓须人工批准 policy adapter、绝不在此暗加。
    """

    level: Literal["none", "watch", "elevated"]
    data_status: Literal["ok", "partial", "insufficient"]
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def crowding_advisory(*, basket_correlation: float | None = None, data_complete: bool = False) -> CrowdingAdvisory:
    """产拥挤定性咨询。数据不足（默认）→ data_status=insufficient + level=watch（**绝不** none：missing≠不拥挤）。

    数据完整且拥挤篮相关性有效时：|corr|≥0.7→elevated；≥0.4→watch；否则 none。全程**只咨询、绝不产动作**。
    **等级阈值锁定不暴露入参**（防放水压低 elevated 警示——与 n_eff/factor_families 锁定口径同纪律）。
    """

    # 注意 `is None` 与 isfinite 分开判：basket_correlation=0.0 是**有效零相关测量**（无拥挤），
    # 绝不能被 `or float("nan")` 的 falsy 陷阱当成 missing（codex 顾问 P2：missing≠crowding 0 的反向）。
    if not data_complete or basket_correlation is None or not math.isfinite(basket_correlation):
        return CrowdingAdvisory(
            level="watch", data_status="insufficient",
            evidence=("拥挤数据不足（加密碎片化/篮未验证）→ 仅定性、绝不自动减仓；missing≠不拥挤",),
        )
    c = abs(float(basket_correlation))
    if c > 1.0 + 1e-9:   # 越界相关 = 上游脏值（坏数据不得编码成可信 ok，同 missing≠0 精神）
        return CrowdingAdvisory("watch", "insufficient",
                                (f"相关系数越界 |corr|={c:.2f}>1：疑上游脏值，仅定性留意",))
    if c >= _CROWD_ELEVATED_CORR:
        return CrowdingAdvisory("elevated", "ok", (f"与拥挤篮 |corr|={c:.2f}≥{_CROWD_ELEVATED_CORR}：拥挤升高（仅警示）",))
    if c >= _CROWD_WATCH_CORR:
        return CrowdingAdvisory("watch", "ok", (f"与拥挤篮 |corr|={c:.2f}∈[{_CROWD_WATCH_CORR},{_CROWD_ELEVATED_CORR})：留意",))
    return CrowdingAdvisory("none", "ok", (f"与拥挤篮 |corr|={c:.2f}<{_CROWD_WATCH_CORR}：无显著拥挤证据",))


__all__ = [
    "CapacityEstimate",
    "CrowdingAdvisory",
    "DEFAULT_IMPACT_COEF",
    "DecayEstimate",
    "FactorFamilies",
    "crowding_advisory",
    "factor_families",
    "ic_decay_half_life",
    "strategy_capacity",
]
