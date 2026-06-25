"""M9.2 · 三档成本预设 → 回测引擎成本模型（**opt-in size-aware 平方根冲击**）。

把 §M1 的三档声明式成本预设（`EquityCostModel` / `CryptoSpotCostModel` /
`CryptoPerpCostModel`，见 `strategy_goal.py`）转成回测引擎实际消费的
`BacktestCostModel`，并把 **R18 平方根市场冲击**做成**显式 opt-in**——让生产回测**可以**
size-aware（大资金不再系统性过优），但**默认仍关**。

GOAL §10「方法学松紧 = 用户」+ 本卡红线（e2afc5c2）:
- **绝不强制翻生产默认**:预设 `impact_model` 默认 `"linear"` → 本转换出的冲击项**恒 0**
  （production 默认逐位不变、向后兼容）。启用 size-aware 冲击须用户**两个显式动作**:
  ① 预设 `impact_model="sqrt"`;② 调用方传冲击系数 `impact_coef`(Y)。缺一即不启用/报错。
- **不替用户拍方法学**:Y(冲击系数)**无万能默认**——须用户/校准提供（GOAL §10 + finding
  `sqrt-impact-backtest-cost.md`）。本模块**绝不**烤死一个 Y 当默认。δ=0.5 是 R18 锁定的
  文献默认（`impact.IMPACT_DELTA`），随转换自动流入、无需调用方给。
- **不假绿灯/不静默**:`impact_model="sqrt"` 却没给 Y → **raise**（绝不静默当 0 冲击让回测
  只剩平成本、看起来便宜=假绿灯）；给了 Y 却预设非 `"sqrt"` → **raise**（诚实拒绝口径不一致，
  不偷偷把冲击塞进一个没声明 sqrt 的预设）。

**只有 `"sqrt"` 有实现**:`impact_model ∈ {"fixed","linear","orderbook"}` 这几档在本仓库
**无对应冲击公式实现**（R18 只建了平方根这一条，本卡红线「无新公式→复用已建 sqrt-impact 不另造」）;
本转换对它们一律产**冲击项=0 的平成本模型**（不静默假装有线性/常数冲击）。

**消费现状（诚实·不过 claim）**:本转换是**库级 opt-in seam**。当前生产 run 管线**尚未**把
StrategyGoal 的成本预设接到 `BacktestVenue`（grep: `BacktestVenue(` 仅 `backtest_venue.py`
自身构造）——producer wiring 是另一条线 / follow-on（碰 main.py/run 管线超出本卡领地）。
本模块**不暗示**已被生产 run 详情消费;它把现状里「预设 `impact_model='sqrt'` 是个谁也不读的
死字段」修成「一条诚实、可证伪、默认关的 opt-in 通路」。

冲击的无泄露流动性口径(ADV/σ)由 `BacktestCostModel` / `BacktestVenue` 已建逻辑承担:
调用方传**点位无泄露** `impact_adv`/`impact_sigma`(推荐、绕开自估、不触发前视 warning),
或留空走 venue 的**扩张窗 as-of 自估**(无前视、warmup 不计冲击已披露;卡 d9bf88b1)。
本模块**不碰**那条自估路、只透传口径。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .backtest_venue import BacktestCostModel
from .impact import IMPACT_DELTA

if TYPE_CHECKING:  # 仅类型:避免 import 期把 M1 config 拉进 M9 执行包的导入面
    from ..strategy_goal import CostModel


__all__ = ["to_backtest_cost_model", "backtest_cost_model_for"]


def _resolve_impact_coef(impact_model: str, impact_coef: float | None) -> float:
    """opt-in 合同(诚实·不静默):返回喂给 `BacktestCostModel.impact_coef` 的值。

    | 预设 impact_model | 调用方 impact_coef | 结果 |
    |---|---|---|
    | 非 "sqrt"(默认 linear 等) | None | 0.0(冲击关·生产默认) |
    | 非 "sqrt" | 给了(任意) | **raise**(口径不一致:给系数却没声明 sqrt) |
    | "sqrt" | None | **raise**(声明 sqrt 却没给 Y → 否则静默 0 冲击=假绿灯) |
    | "sqrt" | 正有限数 | 该 Y(启用 size-aware 冲击) |
    | "sqrt" | 0/负/非有限 | **raise**(无效 Y;要关请把 impact_model 设回非 sqrt 或传 None) |
    """
    wants_sqrt = impact_model == "sqrt"
    if impact_coef is None:
        if wants_sqrt:
            raise ValueError(
                "成本预设 impact_model='sqrt' 但未传 impact_coef(Y)——平方根冲击须冲击系数、"
                "无万能默认(GOAL §10:方法学松紧=用户、须用户/校准给)。要启用请传正 Y;"
                "要关请把 impact_model 设回非 'sqrt'。绝不静默当 0 冲击(那是假绿灯)。"
            )
        return 0.0
    # impact_coef 给了 → 必须是为了 sqrt、且是有效正数
    if not wants_sqrt:
        raise ValueError(
            f"传了 impact_coef={impact_coef} 但预设 impact_model='{impact_model}'≠'sqrt'——"
            "本转换仅 R18 平方根冲击有实现(无新公式)。要启用 size-aware 冲击请把预设 "
            "impact_model 设成 'sqrt';不启用请不要传 impact_coef。"
        )
    if not math.isfinite(impact_coef) or impact_coef <= 0.0:
        raise ValueError(
            f"impact_coef(Y)={impact_coef} 无效——须正有限数。不启用冲击请传 impact_coef=None "
            "(而非 0/负)。"
        )
    return float(impact_coef)


def to_backtest_cost_model(
    preset: "CostModel",
    *,
    impact_coef: float | None = None,
    impact_adv: dict[str, float] | None = None,
    impact_sigma: dict[str, float] | None = None,
) -> BacktestCostModel:
    """三档声明式成本预设 → 回测引擎 `BacktestCostModel`(opt-in 平方根冲击·默认关)。

    `preset`:`EquityCostModel` / `CryptoSpotCostModel` / `CryptoPerpCostModel` 实例(§M1)。
    `impact_coef`(Y):**None=冲击关(生产默认、向后兼容)**;传正数则**仅当**预设 impact_model='sqrt'
        时启用 R18 平方根冲击(否则 raise)。无万能默认、须用户/校准给(GOAL §10)。
    `impact_adv`/`impact_sigma`:**点位无泄露**的 per-symbol ADV/σ(推荐;绕开 venue 自估、不触发
        前视 warning)。留空 → venue 扩张窗 as-of 自估(无前视、warmup 披露)。**本模块只透传、不估。**

    **费率口径映射(保守·已文档化)**:
    - 加密(spot/perp)用 **taker**(主动成交)费率作 `commission_bps`——回测默认 next-bar-open/市价
      撮合是 taker 口径(不建模 maker 排队优先级),taker 更保守;spot 另按 `bnb_discount` 折让。
    - perp 的 **funding / borrow 是持仓期成本、不属 per-fill 成本**(且 `BacktestCostModel.
      funding_bps_per_8h` 当前 `_cost_breakdown` 未消费),本转换**不伪造**funding 数、置 0;
      `funding_rate_apply` 的处置属持仓成本另一条路,不在 per-fill 转换内 claim。
    - A股映射 commission/stamp(卖出)/transfer/slippage 直传(语义对齐)。
    """
    # 延迟 import:避免 M9 执行包导入期就拉 M1 config(保持导入面干净;调用时才需要)
    from ..strategy_goal import (
        CryptoPerpCostModel,
        CryptoSpotCostModel,
        EquityCostModel,
    )

    impact_model = getattr(preset, "impact_model", "linear")
    resolved_coef = _resolve_impact_coef(impact_model, impact_coef)

    if isinstance(preset, EquityCostModel):
        commission_bps = float(preset.commission_bps)
        slippage_bps = float(preset.slippage_bps)
        stamp_duty_bps = float(preset.stamp_duty_bps)   # 仅卖出(BacktestCostModel 同语义)
        transfer_fee_bps = float(preset.transfer_fee_bps)
    elif isinstance(preset, CryptoSpotCostModel):
        commission_bps = float(preset.taker_bps) * (1.0 - float(preset.bnb_discount))
        slippage_bps = float(preset.slippage_bps)
        stamp_duty_bps = 0.0
        transfer_fee_bps = 0.0
    elif isinstance(preset, CryptoPerpCostModel):
        commission_bps = float(preset.taker_bps)
        slippage_bps = float(preset.slippage_bps)
        stamp_duty_bps = 0.0
        transfer_fee_bps = 0.0
        # funding/borrow:持仓期成本,见 docstring——不在此伪造
    else:
        raise TypeError(
            f"不支持的成本预设类型 {type(preset).__name__}——"
            "须 EquityCostModel / CryptoSpotCostModel / CryptoPerpCostModel(§M1)。"
        )

    return BacktestCostModel(
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        stamp_duty_bps=stamp_duty_bps,
        transfer_fee_bps=transfer_fee_bps,
        funding_bps_per_8h=0.0,
        side_aware=True,
        impact_coef=resolved_coef,          # 0.0=关(默认);>0 仅 sqrt opt-in 时
        impact_delta=IMPACT_DELTA,          # δ=0.5 R18 锁定文献默认(自动流入)
        impact_adv=impact_adv,              # 点位无泄露口径透传(留空走 venue 自估)
        impact_sigma=impact_sigma,
    )


def backtest_cost_model_for(
    asset_class: str,
    *,
    impact_model: str | None = None,
    impact_coef: float | None = None,
    impact_adv: dict[str, float] | None = None,
    impact_sigma: dict[str, float] | None = None,
) -> BacktestCostModel:
    """便捷入口:按 asset_class 取**该档默认预设**(§M1 单一默认源、不复制默认值)→ 转 `BacktestCostModel`。

    `asset_class`:`"equity_cn"` / `"crypto_spot"` / `"crypto_perp"`。
    `impact_model`:覆盖默认预设的 impact_model(默认 None=用预设自带默认 'linear'=冲击关);
        要 opt-in size-aware 须设 `"sqrt"` **且**给 `impact_coef`(同 `to_backtest_cost_model` 合同)。
    其余参数同 `to_backtest_cost_model`。
    """
    from ..strategy_goal import (
        CryptoPerpCostModel,
        CryptoSpotCostModel,
        EquityCostModel,
    )

    builders = {
        "equity_cn": EquityCostModel,
        "crypto_spot": CryptoSpotCostModel,
        "crypto_perp": CryptoPerpCostModel,
    }
    cls = builders.get(asset_class)
    if cls is None:
        raise ValueError(
            f"asset_class='{asset_class}' 无对应三档成本预设——"
            "须 equity_cn / crypto_spot / crypto_perp。"
        )
    preset = cls() if impact_model is None else cls(impact_model=impact_model)
    return to_backtest_cost_model(
        preset,
        impact_coef=impact_coef,
        impact_adv=impact_adv,
        impact_sigma=impact_sigma,
    )
