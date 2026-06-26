"""② 容量 → sizing 诚实上限（卡 aa13c3b0 · §3 度量接生产路径）。

把 `factor_factory.lifecycle_metrics.strategy_capacity` 的容量度量转成 **sizing 仓位上限决策**。
altitude = portfolio/sizing（**非** factor_factory——容量**公式**留 lifecycle_metrics 单一源，
「allowed=min(proposed, capacity)」是配置/动作层决策，和 optimizers/constraints 同居）。

命门（诚实 · 安全 · 数学↔实现一致）：
- **硬上限仅 status=ok ∧ 真实 Y（impact_coef 显式给）∧ 容量有限正 才 binding**：占位 Y(0.1) 与显式
  Y=0.1 的容量**数值完全相同**（test_factor_lifecycle_metrics 第 252 行证），故 placeholder **必在
  call-site 由 `impact_coef is None` 捕获**、绝不从 CapacityEstimate 的值反推。
- **Y 占位 → 只示意（allowed=proposed）+ 诚实标，绝不编造硬上限**（GOAL §3 / 卡红线「容量缺绝不编造」）。
- **no_edge（α≤0）= 真实「无正 edge」负面发现**（非数据缺失），单独**响亮** reason；默认研究态**不自动清仓**
  （自动清仓=方法学决策，§0/§7 + GOAL §9「系统替 user 选方法学松紧→拒」）；`mode="production"` 可**显式**
  fail-closed（allowed=0）——机制提供、默认不强加（是否生产 fail-closed 仍属 [需拍板] follow-on）。
- **容量 cap 绝不接 `approval/hard_limits`** 真钱单笔安全 cap（§5 不同范畴：那是 fail-closed 真钱护栏，
  此为研究/配置层 alpha 容量；纠缠 = 削弱 §5 安全不变量、停工级）。
- **拥挤绝不进 sizing**：签名**无** crowding 入参 + 运行期**拒** `CrowdingAdvisory`（类型层隔离，R15/④）。
- **单位/周期一致性**：`proposed_notional` 必须与 ADV **同单位同周期**（容量「单位同 ADV」、α 与 τ/σ/ADV
  同周期）——无法数值校验，文档 + note 强调；`participation_at_cap` 暴露 + 超合理参与带告警
  （finding：容量仅在合理参与率区间可信）。

复用 `strategy_capacity` 单一公式源、**不重造**容量数学、**不引入新公式** → 无新 MathematicalArtifact。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..factor_factory.lifecycle_metrics import CrowdingAdvisory, strategy_capacity

# 参与率告警阈（advisory·不是门）：在 cap 处的单期 ADV 参与率 > 此值 → 容量可信度下降警示。
# 锁定不暴露入参（与度量层锁定口径同纪律）。
_PARTICIPATION_WARN = 0.10

SizingMode = Literal["research", "production"]
SizingReason = Literal[
    "ok_bound",            # status=ok + 真 Y + proposed>capacity → 硬上限生效
    "ok_within_capacity",  # status=ok + 真 Y + proposed≤capacity → 无需缩仓
    "placeholder_advisory",# Y 占位 → 仅示意、绝不硬卡
    "no_edge",             # α≤0 → 无正 edge（研究态不清仓 / production fail-closed）
    "invalid",             # 容量参数无效 → 无法计算
    "capacity_degenerate", # status=ok 但容量非有限/≤0（近零 τ 致发散）→ 不作硬上限
]


@dataclass(frozen=True)
class CapacitySizingDecision:
    """容量 → sizing 上限决策（**诚实**：binding 只在数据驱动正容量、proposed 超容量时为真）。"""

    proposed_notional: float        # 调用方拟投金额（单位/周期须同 ADV）
    capacity: float                 # 来自 CapacityEstimate.capacity（0=no_edge；NaN=invalid）
    allowed_notional: float         # 实施决策后的金额（binding 时 ≤ proposed；advisory 时 = proposed）
    binding: bool                   # cap 是否真缩小了 proposed（仅数据驱动硬上限 / production fail-closed）
    capacity_status: str            # 透传 CapacityEstimate.status（ok/no_edge/invalid）
    is_placeholder_capacity: bool   # Y 占位 → 容量仅示意（绝不硬卡）
    reason: SizingReason
    mode: SizingMode
    participation_at_cap: float     # 在 allowed 处的单期 ADV 参与率 turnover·allowed/adv（NaN=不可算）
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


def _reject_crowding(**kwargs) -> None:
    """类型层隔离（R19/④）：sizing 绝不接拥挤——任一入参是 `CrowdingAdvisory` 即响亮拒绝。

    这是 belt-and-suspenders；真正的隔离是**结构性**的（签名里根本没有 crowding/level/haircut 入参，
    见 test 的签名锁）。运行期再设一道防伪，使「把拥挤喂进 sizing」数学上不可能静默发生。
    """

    for name, val in kwargs.items():
        if isinstance(val, CrowdingAdvisory):
            raise TypeError(
                f"capacity_sizing_cap 拒收拥挤咨询（参数 {name}=CrowdingAdvisory）：拥挤绝不进 sizing "
                "减仓路径（GOAL §3 / R19 类型层隔离）。拥挤只进呈现层（factor_advisory）。"
            )


def capacity_sizing_cap(
    proposed_notional: float,
    *,
    gross_alpha: float,
    turnover: float,
    adv: float,
    volatility: float,
    impact_coef: float | None = None,
    mode: SizingMode = "research",
) -> CapacitySizingDecision:
    """把容量度量转成 sizing 上限决策。**硬上限仅数据驱动正容量 + proposed 超容量才生效。**

    `proposed_notional`：拟投金额（**须同 ADV 单位/周期**）。`gross_alpha/turnover/adv/volatility`：喂
    `strategy_capacity` 的同周期参数。`impact_coef`(Y)：省略=占位（容量仅示意、绝不硬卡）；显式给=数据驱动
    （方可 binding）。`mode`：`research`(默认)=no_edge/invalid 不强卡（只示意+响亮标）；`production`=
    no_edge/invalid **fail-closed**（allowed=0）。

    返回 `CapacitySizingDecision`。`binding=True` 仅当：① ok+真 Y+proposed>capacity（硬上限至容量）；
    或 ② production 模式下 no_edge/invalid fail-closed。**占位 Y 在任何模式都不 binding**（绝不编造硬上限）。
    """

    _reject_crowding(
        proposed_notional=proposed_notional, gross_alpha=gross_alpha, turnover=turnover,
        adv=adv, volatility=volatility, impact_coef=impact_coef,
    )
    if mode not in ("research", "production"):
        raise ValueError(f"未知 mode={mode!r}（仅 research/production）")

    # placeholder 必在 call-site 捕获（值无法区分占位-0.1 与显式-0.1）。
    y_is_placeholder = impact_coef is None
    est = strategy_capacity(gross_alpha, turnover, adv, volatility, impact_coef=impact_coef)
    cap = float(est.capacity)
    proposed = float(proposed_notional)

    allowed = proposed         # 默认 advisory：不动 proposed
    binding = False
    notes: list[str] = []
    reason: SizingReason

    if est.status == "ok":
        if y_is_placeholder:
            reason = "placeholder_advisory"
            notes.append(
                f"容量用占位 Y 估（示意 {cap:.3g}）、非数据驱动 → **仅示意上限、绝不硬卡**；"
                "接真实冲击系数 impact_coef 后方可 binding（卡红线：容量缺绝不编造硬上限）"
            )
        elif not math.isfinite(cap) or cap <= 0.0:
            reason = "capacity_degenerate"
            notes.append(
                f"status=ok 但容量={cap:.3g} 非有限/≤0（疑近零 τ 致 1/τ³ 发散）→ 不作硬上限、仅示意"
                "（绝不在无意义 cap 上 binding）"
            )
        else:
            # 数据驱动正容量：唯一会硬卡的格。
            if proposed > cap:
                allowed = cap
                binding = True
                reason = "ok_bound"
                notes.append(f"AUM {proposed:.3g} > 容量 {cap:.3g}（数据驱动 Y）→ 硬上限至容量")
            else:
                reason = "ok_within_capacity"
                notes.append(f"AUM {proposed:.3g} ≤ 容量 {cap:.3g} → 无需缩仓")
    elif est.status == "no_edge":
        reason = "no_edge"
        notes.append("α_gross≤0：无正 edge、无正盈利容量（**真实负面发现**，非数据缺失）")
        if mode == "production":
            allowed = 0.0
            binding = True
            notes.append("production 模式 fail-closed → allowed=0（无 edge 不进生产仓位）")
        else:
            notes.append(
                "研究态：**默认不自动清仓**（自动清仓=方法学决策、系统无权替 user 定，[需拍板] follow-on）；"
                "production 模式可显式 fail-closed"
            )
    else:  # invalid
        reason = "invalid"
        notes.append("容量参数无效（τ/σ/ADV/Y≤0 或非有限）→ 无法计算容量（≠容量为 0）")
        if mode == "production":
            allowed = 0.0
            binding = True
            notes.append("production 模式 fail-closed → allowed=0（容量不可计算不进生产仓位）")
        else:
            notes.append("研究态：不强卡（容量不可计算≠容量为 0；绝不编造硬上限）")

    # 透传容量度量自身的诚实告警（占位/自检偏差等），不吞。
    notes.extend(est.warnings)

    participation = (
        turnover * allowed / adv
        if (math.isfinite(adv) and adv > 0 and math.isfinite(allowed) and math.isfinite(turnover))
        else float("nan")
    )
    if math.isfinite(participation) and participation > _PARTICIPATION_WARN:
        notes.append(
            f"在 allowed 处单期 ADV 参与率 {participation:.1%} > {_PARTICIPATION_WARN:.0%}："
            "超合理参与带、sqrt 冲击容量可信度下降（finding 适用域）"
        )

    return CapacitySizingDecision(
        proposed_notional=proposed,
        capacity=cap,
        allowed_notional=float(allowed),
        binding=binding,
        capacity_status=est.status,
        is_placeholder_capacity=y_is_placeholder,
        reason=reason,
        mode=mode,
        participation_at_cap=float(participation),
        notes=tuple(notes),
    )


__all__ = [
    "CapacitySizingDecision",
    "SizingMode",
    "SizingReason",
    "capacity_sizing_cap",
]
