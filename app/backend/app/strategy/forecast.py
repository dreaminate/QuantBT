"""§9 · Forecast typed 对象——模型输出 typed，**经 Signal Contract** 才转成 Signal。

为什么这一层存在（GOAL §9 + §1 语义边界 + 决策 R17/R18）：
- 模型「本体」(.pt/.pkl…) 进 Model Registry；模型「输出」(预测序列/截面打分) 是 **Forecast**。
- Forecast **不是裸数字直接进信号层**：它必须先经 `factor_factory.signal_contract`
  登记成一条 Signal Contract（范畴门 + 血统门 + 泄露声明门 R18），才允许转成
  `signals.core.Signal`。这正是 §1 可证伪验收「Signal 未绑定 Signal Contract → 拒」。
- 本模块只建 **Forecast 本体 typed 契约 + Forecast→SignalContract→Signal 绑定**，
  **复用**既有 signal_contract（不改）、signals/core（不改）。绝不重造信号契约或 Signal。

诚实边界（RULES §3）：
- 本绑定门是 **范畴/血统/泄露声明 + 内容寻址一致性 + 过期** 这几道 typed 门，**不**对
  Forecast「是不是真 alpha」下任何定性判断（那是评测/审查台的事）。措辞绝不出现「可信」。
- 算术表达式信号走 `factor_factory.expression` 直接入库（R17），**不经** Forecast 这条路；
  本模块只管「ML/DL 模型输出 → 信号」这一条。
- 本模块**不下单、不接 runtime**（OrderGuard 红线在 execution；runtime 执行接线是另一张卡）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..factor_factory.signal_contract import (
    LeakageDeclaration,
    SignalContract,
    SignalContractRegistry,
    compute_signal_id,
)
from ..signals.core import FactorAttribution, Regime, Signal, SignalDirection

# Forecast 的输出口径（dimension/量纲标签）——与 signal_contract.output_kind 同义域。
# 不穷举死所有口径（保持开放），仅给出常见 typed 取值，未知口径用字符串本身承载。
ForecastKind = Literal["xs_score", "seq_pred", "prob", "point", "class_proba", "rank"]

SourceLib = Literal["ml", "dl"]


class ForecastError(ValueError):
    """Forecast→Signal 绑定被拒（裸输出未绑契约 / 孤儿绑定 / 伪绑定 / 已过期）。"""


class Forecast(BaseModel):
    """一条模型输出的 typed 契约（量纲 / 方向 / 置信度 / 过期 都 typed）。

    身份不在本体里——本体在 Model Registry（`model_ref` 回指）。Forecast 只承载「这次输出」
    的 typed 字段，并通过 `register_contract` 把自己登记成一条 Signal Contract（拿到
    `signal_contract_id`）。**没有 signal_contract_id 的 Forecast = 裸输出，不得进信号层。**
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str = Field(..., min_length=1, description="标的代码")
    model_ref: str = Field(..., min_length=1,
        description="回指 Model Registry 里的模型本体（.pt/.pkl…）；血统门要求像本体文件")
    source_lib: SourceLib = Field(..., description="ml | dl（算术不走 Forecast，直接表达式入库）")
    output_kind: str = Field(..., min_length=1, description="输出口径 xs_score/seq_pred/prob…（量纲标签，入契约身份）")
    horizon: int = Field(..., gt=0, description="预测视野（天），入契约身份")
    value: float = Field(..., description="模型原始输出（score/prob/point…）")
    unit: str = Field("", description="量纲诚实标注（如 zscore/prob/ret_bps）；空=未标，不假装有量纲")
    direction: SignalDirection | None = Field(None, description="显式方向；None 则按 value 与阈值 sign 推导")
    direction_threshold: float = Field(0.0, description="推导方向/幅度用的决策阈值（与 value 同量纲）")
    magnitude: float | None = Field(None, ge=0.0, le=1.0, description="显式幅度；None 则按 |value−阈值| clip 推导")
    confidence: float = Field(..., ge=0.0, le=1.0, description="模型自报/校准后的置信度 0..1")
    event_time: datetime = Field(..., description="known_at：该输出何时可知（PIT）")
    effective_at: datetime = Field(..., description="该输出从何时起生效")
    valid_until: datetime | None = Field(None, description="过期时刻；None=不设过期")
    # 泄露防护自报声明（R18）——register_contract 时强制 OOF+purge+embargo 齐全才能登记。
    leakage: LeakageDeclaration = Field(default_factory=LeakageDeclaration)
    # 绑定后的 Signal Contract id（content-addressed）；None = 未绑 = 裸 Forecast。
    signal_contract_id: str | None = Field(None, description="绑定的 Signal Contract id；None=裸输出未绑")

    @field_validator("leakage", mode="before")
    @classmethod
    def _coerce_leakage(cls, v: Any) -> LeakageDeclaration:
        if isinstance(v, LeakageDeclaration):
            return v
        return LeakageDeclaration.from_dict(v)

    @model_validator(mode="after")
    def _check_time_order(self) -> "Forecast":
        if self.valid_until is not None and self.valid_until <= self.effective_at:
            raise ValueError("Forecast.valid_until 必须晚于 effective_at（过期时刻不能早于生效时刻）")
        return self

    # ----- typed 派生（量纲/方向/幅度），与 signals.fuse_signals 同 sign/clip 约定 -----
    def derived_direction(self) -> SignalDirection:
        """显式 direction 优先；否则按 value 与阈值的 sign 推导（与 fuse_signals 同约定）。"""

        if self.direction is not None:
            return self.direction
        delta = self.value - self.direction_threshold
        if delta > 0:
            return "long"
        if delta < 0:
            return "short"
        return "flat"

    def derived_magnitude(self) -> float:
        """显式 magnitude 优先；否则 clip(|value−阈值|, 0, 1)。"""

        if self.magnitude is not None:
            return self.magnitude
        return float(min(max(abs(self.value - self.direction_threshold), 0.0), 1.0))

    def is_expired(self, as_of: datetime) -> bool:
        """as_of 是否已越过 valid_until（无 valid_until → 永不过期）。"""

        return self.valid_until is not None and as_of > self.valid_until

    def compute_contract_id(self) -> str:
        """按本 Forecast 的 typed 字段算出它**应有**的 Signal Contract id（内容寻址，复用单一哈希族）。"""

        return compute_signal_id(
            source_lib=self.source_lib,
            model_ref=self.model_ref,
            output_kind=self.output_kind,
            horizon=self.horizon,
        )

    def register_contract(
        self,
        registry: SignalContractRegistry,
        *,
        name: str,
        author: str = "system",
        description: str = "",
    ) -> SignalContract:
        """把本 Forecast 登记成一条 Signal Contract（复用既有登记表，**不重造**）。

        登记会触发 signal_contract 的三道门（范畴门 ml/dl、血统门 model_ref 像本体、
        泄露声明门 OOF+purge+embargo 齐全）。登记成功后把 `signal_contract_id` 写回本对象。
        登记失败（SignalContractError）原样抛出——绝不静默放过裸/孤儿/未声明泄露的输出。
        """

        contract = registry.register(
            name=name,
            source_lib=self.source_lib,
            model_ref=self.model_ref,
            output_kind=self.output_kind,
            horizon=self.horizon,
            leakage=self.leakage,
            author=author,
            description=description,
        )
        self.signal_contract_id = contract.signal_id
        return contract


def bind_forecast_to_signal(
    forecast: Forecast,
    registry: SignalContractRegistry,
    *,
    ts: datetime | None = None,
    regime: Regime = "range",
) -> Signal:
    """Forecast → **Signal Contract** → Signal（§9 唯一合规路径；任何一道门不过即拒）。

    门（顺序即优先级，违一条即 ForecastError）：
      1. 裸输出门：`signal_contract_id` 为空 → 拒（模型输出未绑 Signal Contract，不得进信号层）。
      2. 孤儿门：`signal_contract_id` 未在 `registry` 登记 → 拒（悬空绑定）。
      3. 伪绑定门：按 Forecast 字段重算的契约 id ≠ 登记契约 id → 拒（内容寻址一致性，防伪造绑定）。
      4. 过期门：as_of(ts) 已越过 `valid_until` → 拒（过期输出不得产 live Signal）。
    全过 → 产出 `signals.core.Signal`，并把契约 ref（sig::…）写进 contributing_factors 谱系回指。

    本函数**不下单**：产出的 Signal 是研究层信号；short 方向的 Signal 合法（研究层），但
    StrategyBook 的 short intent 能否被 runtime 当可执行 short，由 strategy_book 的执行门管，
    最终下单仍只走 OrderGuard（另一张卡接线）。
    """

    as_of = ts if ts is not None else forecast.effective_at

    # 门 1：裸输出未绑契约 → 拒（§1/§9 可证伪验收的核心红门）。
    if not forecast.signal_contract_id:
        raise ForecastError(
            "模型输出（Forecast）未绑 Signal Contract，不得进信号层："
            "请先 register_contract 登记（R17/§9）——裸输出直进信号层即范畴/血统越界"
        )

    # 门 2：孤儿绑定（id 不在登记表）→ 拒。
    try:
        contract = registry.get(forecast.signal_contract_id)
    except KeyError as exc:
        raise ForecastError(
            f"Forecast.signal_contract_id={forecast.signal_contract_id!r} 未在 Signal Contract "
            "登记表登记（孤儿绑定，悬空信号）"
        ) from exc

    # 门 3：伪绑定（字段口径与登记契约不一致）→ 拒。
    expected = forecast.compute_contract_id()
    if expected != contract.signal_id:
        raise ForecastError(
            "Forecast 字段口径与登记契约不一致（伪绑定）：按 source_lib/model_ref/output_kind/horizon "
            f"重算应为 {expected!r}，登记契约为 {contract.signal_id!r}"
        )

    # 门 4：过期输出不得产 live Signal。
    if forecast.is_expired(as_of):
        raise ForecastError(
            f"Forecast 已过期（valid_until={forecast.valid_until}，as_of={as_of}），不得产生 live Signal"
        )

    direction = forecast.derived_direction()
    magnitude = forecast.derived_magnitude()
    # 谱系回指：贡献度带方向符号（long=+，short=−，flat=0），factor_id 指向契约 ref（sig::…）。
    signed = magnitude if direction == "long" else (-magnitude if direction == "short" else 0.0)
    return Signal(
        ts=as_of,
        symbol=forecast.symbol,
        direction=direction,
        magnitude=magnitude,
        confidence=forecast.confidence,
        regime=regime,
        contributing_factors=[
            FactorAttribution(
                factor_id=contract.signal_ref,
                contribution=signed,
                note="Forecast→SignalContract→Signal（经契约登记，非裸输出）",
            )
        ],
    )


__all__ = [
    "Forecast",
    "ForecastError",
    "ForecastKind",
    "SourceLib",
    "bind_forecast_to_signal",
]
