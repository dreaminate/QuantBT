"""M1 · StrategyGoal — 把"我想做什么策略"标准化成机器可读的目标函数。

参见 QuantBT-GOAL.md §M1。所有字段对齐 GOAL 描述，并加上以下落地工程约束：

- A股 (`equity_cn`) 不可设 `execution_mode=live_crypto`；live_crypto 仅对加密生效。
- `objective=custom_python` 时必须给出 `custom_python_path`（指向已注册的目标函数）。
- `cost_model` 提供 A股 / 加密 spot / 加密 perp 三套预设，加密 perp 必须含资金费率字段。
- 全部支持 YAML round-trip 与 OpenAPI 自动生成（FastAPI/Agent 共用）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


AssetClass = Literal["equity_cn", "crypto_spot", "crypto_perp", "mixed"]
Objective = Literal[
    "max_sharpe",
    "max_sortino",
    "max_calmar",
    "min_drawdown",
    "info_ratio",
    "custom_python",
]
Horizon = Literal["intraday", "daily", "weekly", "monthly"]
ExecutionMode = Literal["research", "backtest", "paper", "live_crypto"]


class Constraints(BaseModel):
    """组合层硬/软约束。任何超出的求解器都应拒绝或截断。"""

    turnover_max: float | None = Field(None, ge=0, description="日换手率上限，例如 0.3 表示 30%")
    single_pos_max: float = Field(0.10, gt=0, le=1.0, description="单标的权重上限")
    sector_cap: float | None = Field(None, gt=0, le=1.0, description="单行业/板块上限")
    var_max: float | None = Field(None, gt=0, description="参数化 VaR 上限（例如 0.03）")
    max_dd: float | None = Field(None, gt=0, lt=1.0, description="允许的最大回撤")
    leverage_max: float = Field(1.0, gt=0, description="总杠杆上限；A股强制 1.0")
    short_allowed: bool = False


class EquityCostModel(BaseModel):
    """A股标准成本模型（参数化，单位均为比率）。"""

    commission_bps: float = Field(2.5, ge=0, description="佣金双边 bps")
    stamp_duty_bps: float = Field(10.0, ge=0, description="印花税卖出 bps")
    transfer_fee_bps: float = Field(0.1, ge=0, description="过户费双边 bps")
    slippage_bps: float = Field(5.0, ge=0, description="基础滑点 bps")
    impact_model: Literal["fixed", "linear", "sqrt"] = "linear"


class CryptoSpotCostModel(BaseModel):
    maker_bps: float = Field(10.0, ge=0)
    taker_bps: float = Field(10.0, ge=0)
    bnb_discount: float = Field(0.0, ge=0, le=0.5, description="BNB 抵扣折扣，0~0.5")
    slippage_bps: float = Field(3.0, ge=0)
    impact_model: Literal["fixed", "linear", "sqrt", "orderbook"] = "linear"


class CryptoPerpCostModel(BaseModel):
    maker_bps: float = Field(2.0, ge=0)
    taker_bps: float = Field(4.0, ge=0)
    funding_rate_apply: bool = Field(True, description="是否计入每 8h 资金费率（必须）")
    funding_rate_source: Literal["historical", "live"] = "historical"
    borrow_bps_per_day: float = Field(0.0, ge=0)
    slippage_bps: float = Field(2.0, ge=0)
    impact_model: Literal["fixed", "linear", "sqrt", "orderbook"] = "linear"


CostModel = EquityCostModel | CryptoSpotCostModel | CryptoPerpCostModel


class EvaluationWindow(BaseModel):
    backtest_start: date
    backtest_end: date
    walk_forward_train_days: int = Field(252, gt=0)
    walk_forward_test_days: int = Field(63, gt=0)
    embargo_days: int = Field(5, ge=0, description="Purged k-fold 的 embargo")
    random_seed: int = 42

    @model_validator(mode="after")
    def _check_range(self) -> "EvaluationWindow":
        if self.backtest_end <= self.backtest_start:
            raise ValueError("backtest_end 必须晚于 backtest_start")
        return self


class EconomicMechanism(BaseModel):
    """因果优先的可证伪经济故事（T-017 / spine 04 §3.2）。dossier §5.4：引导写故事 + 人工审阅，
    不自动跑因果发现算法（PC/LiNGAM 在金融观察序列不可靠，dossier §7 降权）。"""

    risk_premium_or_bias: str = Field(..., min_length=12,
        description="赌哪个风险溢价 / 行为偏差（如 动量=处置效应+反应不足）")
    causal_chain: str = Field(..., min_length=12,
        description="一句话因果链：X 驱动 → Y 错价 → 我们收割 Z")
    confounder_concerns: list[str] = Field(default_factory=list,
        description="混杂/对撞担忧（可空，但空会在裁决里降信心）")


class FalsifiableTriplet(BaseModel):
    """冻结 confirmatory 卡时强制非空的三必填（探索期可空，P2 不挡）。"""

    economic_mechanism: EconomicMechanism
    falsification_condition: str = Field(..., min_length=12,
        description="若 X 则该效应应消失/反号（必须含一个可观测、独立于结果的判据）")
    stop_rule: str = Field(..., min_length=8,
        description="停机规则：达到什么条件就停（回撤/样本/时段/失效信号）")


class StrategyGoal(BaseModel):
    """完整的策略目标——Agent / UI / YAML 三处共用同一份 schema。"""

    name: str = Field(..., min_length=1, max_length=120)
    asset_class: AssetClass
    objective: Objective = "max_sharpe"
    horizon: Horizon = "daily"
    capacity_usd: float = Field(1_000_000.0, gt=0, description="目标管理规模上限（USDT/USD）")
    benchmark: str = Field("000300.SH", description="基准代码；A股常用 000300.SH，加密 BTC-USDT")
    constraints: Constraints = Field(default_factory=Constraints)
    cost_model: CostModel
    evaluation_window: EvaluationWindow
    execution_mode: ExecutionMode = "research"
    universe_id: str | None = None
    custom_python_path: str | None = None
    description: str | None = None
    # T-017 三必填可证伪三元组：默认 None → 探索不挡（P2）；强制只在 card.freeze() 发生，不在此校验。
    falsifiable: FalsifiableTriplet | None = None

    @model_validator(mode="before")
    @classmethod
    def _dispatch_cost_model(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return _coerce_cost_model(data)
        return data

    @model_validator(mode="after")
    def _consistency(self) -> "StrategyGoal":
        if self.execution_mode == "live_crypto" and self.asset_class == "equity_cn":
            raise ValueError("A股不允许 live_crypto 模式（A股最多到 paper trading）")
        if self.asset_class == "equity_cn" and self.constraints.leverage_max != 1.0:
            raise ValueError("A股策略 leverage_max 必须为 1.0")
        if self.objective == "custom_python" and not self.custom_python_path:
            raise ValueError("objective=custom_python 时必须提供 custom_python_path")
        if self.asset_class == "crypto_perp" and not isinstance(self.cost_model, CryptoPerpCostModel):
            raise ValueError("crypto_perp 必须使用 CryptoPerpCostModel（含资金费率）")
        if self.asset_class == "crypto_spot" and not isinstance(self.cost_model, CryptoSpotCostModel):
            raise ValueError("crypto_spot 必须使用 CryptoSpotCostModel")
        if self.asset_class == "equity_cn" and not isinstance(self.cost_model, EquityCostModel):
            raise ValueError("equity_cn 必须使用 EquityCostModel")
        return self

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

    def save_yaml(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_yaml(), encoding="utf-8")
        return target

    @classmethod
    def from_yaml(cls, source: str | Path) -> "StrategyGoal":
        if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
            text = Path(source).read_text(encoding="utf-8")
        else:
            text = str(source)
        data = yaml.safe_load(text)
        return cls.model_validate(_coerce_cost_model(data))


def _coerce_cost_model(data: dict[str, Any]) -> dict[str, Any]:
    """YAML 不带 discriminator，按 asset_class 决定 cost_model 类型。"""

    if not isinstance(data, dict) or "asset_class" not in data:
        return data
    out = dict(data)
    cost = out.get("cost_model")
    if isinstance(cost, dict):
        asset = out["asset_class"]
        if asset == "equity_cn":
            out["cost_model"] = EquityCostModel.model_validate(cost)
        elif asset == "crypto_spot":
            out["cost_model"] = CryptoSpotCostModel.model_validate(cost)
        elif asset == "crypto_perp":
            out["cost_model"] = CryptoPerpCostModel.model_validate(cost)
    return out


PRESETS: dict[str, StrategyGoal] = {
    "a_share_weekly_top_decile": StrategyGoal(
        name="A股周频选股 Top 10%",
        asset_class="equity_cn",
        objective="info_ratio",
        horizon="weekly",
        capacity_usd=5_000_000.0,
        benchmark="000300.SH",
        constraints=Constraints(turnover_max=0.3, single_pos_max=0.05, max_dd=0.20),
        cost_model=EquityCostModel(),
        evaluation_window=EvaluationWindow(
            backtest_start=date(2018, 1, 1),
            backtest_end=date(2025, 12, 31),
        ),
        description="aiquantclaw 风格 · 截面排序选股",
    ),
    "crypto_perp_trend_daily": StrategyGoal(
        name="加密永续日频趋势",
        asset_class="crypto_perp",
        objective="max_calmar",
        horizon="daily",
        capacity_usd=200_000.0,
        benchmark="BTC-USDT",
        constraints=Constraints(
            turnover_max=0.5,
            single_pos_max=0.20,
            max_dd=0.30,
            leverage_max=3.0,
            short_allowed=True,
        ),
        cost_model=CryptoPerpCostModel(),
        evaluation_window=EvaluationWindow(
            backtest_start=date(2021, 1, 1),
            backtest_end=date(2025, 12, 31),
        ),
        description="资金费率成本入账 · 永续多空",
    ),
}


__all__ = [
    "AssetClass",
    "Constraints",
    "CostModel",
    "CryptoPerpCostModel",
    "CryptoSpotCostModel",
    "EconomicMechanism",
    "EquityCostModel",
    "EvaluationWindow",
    "ExecutionMode",
    "FalsifiableTriplet",
    "Horizon",
    "Objective",
    "PRESETS",
    "StrategyGoal",
]
