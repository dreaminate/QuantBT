"""§9 · StrategyBook typed 对象——组合意图/多腿 long·short/约束/成本/回测计划。

为什么这一层存在（GOAL §9 + §2 策略台 + §11 跨市场资本账 + 决策 R13）：
- 策略台产出 StrategyBook：**引用** factor/signal/model id（不写 factor formula，§2 可证伪验收），
  多腿 long/short，绑 payoff、hedge ratio、资本账（capital accounting）、风险度量、回测计划。
- **short intent ≠ runtime 可执行 short**（§9 红线 + §12 执行边界）：StrategyBook 可以表达
  short 意图与 short expected PnL（研究层），但能否被 runtime 当**可执行 short**，取决于
  InstrumentSpec / venue / borrow / margin / regulation —— 缺则拒。这正是 §9 可证伪验收
  「StrategyBook short intent 被 runtime 当作可执行 short 且缺 borrow/margin/venue 检查 → 拒」。
- **A股禁空头侧**（决策 R13=B：融券池小/T+1/涨跌停，做空近不可行）+ **A股永不实盘**
  （项目红线）：A股 StrategyBook 的 short 腿在执行门**硬拒、不可被 requirement 字段绕过**。

诚实边界（RULES §3）：
- 本模块的执行门是 **typed 守门**，**不下单、不是 OrderGuard**：它只判定「这个 book 的 short 腿
  够不够格被 runtime 当可执行 short」，真正下单仍只经 OrderGuard（D-PERM 唯一入口，另一张卡接线）。
- payoff/hedge_ratio/expected_pnl 都是**参数/绑定**，不是新数学推导；无新公式 → 不造
  MathematicalArtifact（仅留 `theory_binding_ref` 前向槽，按 §9 spine 可后续绑定）。
- **复用** strategy_goal.Constraints（既有约束类型，单一源·不另造第三个 Constraints）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..lineage.ids import content_hash
from ..strategy_goal import Constraints

# A股标记集（决策 R13 + 项目红线 A股永不实盘）：命中即 short 腿执行门硬拒。
# canonical token = "equity_cn"（对齐 strategy_goal.AssetClass），并接受常见别名。
_A_SHARE_MARKERS = frozenset({"equity_cn", "a_share", "ashare", "cn_equity", "china_equity", "a股"})

LegSide = Literal["long", "short"]
AssetKind = Literal["signal", "factor", "factor_set", "model"]
PayoffKind = Literal[
    "directional", "long_short_spread", "market_neutral", "option_payoff", "carry", "custom"
]
LifecycleState = Literal[
    "idea", "draft", "specified", "backtest_candidate", "validation",
    "paper_candidate", "approved", "monitored", "retired",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_a_share(asset_class: str) -> bool:
    return (asset_class or "").strip().casefold() in _A_SHARE_MARKERS


class StrategyBookError(ValueError):
    """StrategyBook typed 契约不完整（缺 payoff/资本账/引用资产未登记），不可晋级。"""


class StrategyBookExecutionError(StrategyBookError):
    """short intent 被当可执行 short 但缺 borrow/margin/venue/instrument/regulation（§9 红线）。"""


class PayoffSpec(BaseModel):
    """payoff 绑定（含 hedge ratio 与 expected PnL；支持 short expected PnL）。

    都是**参数/绑定**，不是新公式（不造 MathematicalArtifact）。`theory_binding_ref` 是 §9
    Mathematical Spine 的前向槽：若 payoff 真有数学推导，后续绑 TheoryImplementationBinding。
    """

    kind: PayoffKind
    description: str = Field(..., min_length=8, description="payoff 结构的可读说明（多空价差/方向/期权…）")
    hedge_ratio: float | None = Field(None, description="对冲比例（long-short spread 等需要）")
    expected_pnl_bps: float | None = Field(None, description="预期 PnL（bps）")
    expected_short_pnl_bps: float | None = Field(None, description="short 腿预期 PnL（bps）；§9 short expected PnL")
    theory_binding_ref: str | None = Field(None, description="§9 spine 前向槽：TheoryImplementationBinding 引用")


class CapitalAccount(BaseModel):
    """资本账（capital accounting）——§11 跨市场资本账字段。

    硬不变量：gross_exposure ≥ |net_exposure|（敞口会计恒真，违则是脏账，拒）。
    """

    base_currency: str = Field(..., min_length=1, description="记账本币（如 USD/USDT/CNY）")
    gross_exposure: float = Field(..., ge=0.0, description="总敞口 Σ|w|")
    net_exposure: float = Field(..., description="净敞口 Σw（可正可负）")
    leverage: float = Field(..., gt=0.0, description="总杠杆")
    capital_allocation: float = Field(..., gt=0.0, description="分配资本（本币名义）")
    financing_cost_bps: float = Field(0.0, ge=0.0, description="融资成本 bps")
    collateral: float | None = Field(None, ge=0.0, description="抵押品")
    margin_requirement: float | None = Field(None, ge=0.0, description="保证金要求")

    @model_validator(mode="after")
    def _check_exposure(self) -> "CapitalAccount":
        if self.gross_exposure + 1e-9 < abs(self.net_exposure):
            raise ValueError(
                f"资本账脏账：gross_exposure({self.gross_exposure}) 不能小于 |net_exposure|({abs(self.net_exposure)})"
            )
        return self


class ShortExecutionRequirement(BaseModel):
    """short 腿被 runtime 当**可执行 short** 的执行要件（§9/§12）。

    `is_satisfied()` 要求五项齐全：InstrumentSpec 引用 / venue / borrow 可借 / margin / regulation 放行。
    缺任一 → `missing()` 列出 → 执行门拒。本对象只承载「要件够不够」，**不代表已下单**。
    """

    instrument_spec_ref: str | None = Field(None, description="InstrumentSpec 引用（合约/标的声明）")
    venue: str | None = Field(None, description="可执行 venue（交易场所）")
    borrow_available: bool = Field(False, description="是否可借券/可融券")
    borrow_rate_bps_per_day: float | None = Field(None, ge=0.0, description="借券费率 bps/日")
    margin_ref: str | None = Field(None, description="保证金规格引用")
    margin_ratio: float | None = Field(None, ge=0.0, description="保证金比例")
    regulation_ok: bool = Field(False, description="监管/合规是否放行该 short")
    permission_ref: str | None = Field(None, description="执行权限引用")

    def missing(self) -> list[str]:
        miss: list[str] = []
        if not self.instrument_spec_ref:
            miss.append("InstrumentSpec")
        if not self.venue:
            miss.append("venue")
        if not self.borrow_available:
            miss.append("borrow")
        if self.margin_ref is None and self.margin_ratio is None:
            miss.append("margin")
        if not self.regulation_ok:
            miss.append("regulation")
        return miss

    def is_satisfied(self) -> bool:
        return not self.missing()


class StrategyLeg(BaseModel):
    """一条腿：**引用** factor/signal/model id（不写 formula，§2），long 或 short。

    short 腿默认 `intent_only=True`（研究意图，非 runtime 订单）；要被当可执行 short，须配
    `short_exec` 且过执行门。`asset_ref` 是被引用资产的 id（如 sig::… / factor_id / model_id）。
    """

    asset_ref: str = Field(..., min_length=1, description="被引用资产 id（signal/factor/factor_set/model）")
    asset_kind: AssetKind
    side: LegSide
    weight: float = Field(..., description="目标权重（可正可负；side 是方向的权威标记）")
    notional: float | None = Field(None, description="名义金额（本币）")
    intent_only: bool = Field(True, description="是否仅为研究意图（非 runtime 订单）；short 默认 True")
    short_exec: ShortExecutionRequirement | None = Field(None, description="short 腿执行要件（仅 short 有意义）")


class StrategyBook(BaseModel):
    """StrategyBook typed 契约（§9）——多腿组合意图 + payoff + 约束 + 资本账 + 回测计划。

    身份 `book_id` 内容寻址自**结构性**字段（asset_class/legs/payoff/capital_account/constraints），
    刻意排除 name/description（改名不算新 book），复用单一哈希族 lineage.content_hash（不另造）。
    """

    name: str = Field(..., min_length=1, max_length=120)
    owner: str = Field("system", description="所属（actor）")
    asset_class: str = Field(..., min_length=1, description="资产类（equity_cn/crypto_perp/futures/options…，宽域）")
    legs: list[StrategyLeg] = Field(..., min_length=1, description="多腿（至少一腿）")
    payoff: PayoffSpec | None = Field(None, description="payoff 绑定；缺则不可晋级")
    constraints: Constraints = Field(default_factory=Constraints, description="组合约束（复用 strategy_goal.Constraints）")
    capital_account: CapitalAccount | None = Field(None, description="资本账绑定；缺则不可晋级")
    risk_measures: dict[str, float] = Field(default_factory=dict, description="风险度量（如 var_95/ann_vol/max_dd）")
    linked_assets: list[str] = Field(default_factory=list, description="登记的引用资产 id（run_config 注入用）")
    backtest_plan_ref: str | None = Field(None, description="回测计划引用")
    lifecycle_state: LifecycleState = "draft"
    description: str = ""
    book_id: str = Field("", description="内容寻址身份；留空则按结构字段自动计算")
    created_at_utc: str = Field(default_factory=_now)

    @model_validator(mode="after")
    def _fill_book_id(self) -> "StrategyBook":
        if not self.book_id:
            structural = {
                "asset_class": self.asset_class,
                "legs": [leg.model_dump(mode="json") for leg in self.legs],
                "payoff": self.payoff.model_dump(mode="json") if self.payoff else None,
                "capital_account": (
                    self.capital_account.model_dump(mode="json") if self.capital_account else None
                ),
                "constraints": self.constraints.model_dump(mode="json"),
            }
            self.book_id = "book_" + content_hash(structural)[:10]
        return self

    # ----------------------------- 查询 -----------------------------
    def short_legs(self) -> list[StrategyLeg]:
        return [leg for leg in self.legs if leg.side == "short"]

    def referenced_assets(self) -> list[str]:
        return sorted({leg.asset_ref for leg in self.legs})

    def executable_short_legs(self) -> list[StrategyLeg]:
        """要件齐全且非 A股 的 short 腿（正路径用；A股 short 永不在内，R13）。"""

        if _is_a_share(self.asset_class):
            return []
        return [
            leg for leg in self.short_legs()
            if leg.short_exec is not None and leg.short_exec.is_satisfied()
        ]

    # ----------------------------- 门 -----------------------------
    def assert_promotable(self) -> None:
        """晋级门（typed 契约完整性，§9 + §1）。违一条即 StrategyBookError，绝不静默放过。

          · 缺 payoff 绑定 → 拒（§9）。
          · 缺资本账（capital accounting）绑定 → 拒（§9）。
          · 引用资产未登记进 linked_assets（run_config 无法注入）→ 拒（§1 可证伪验收）。
        """

        if self.payoff is None:
            raise StrategyBookError("StrategyBook 缺 payoff 绑定，不可晋级（§9）")
        if self.capital_account is None:
            raise StrategyBookError("StrategyBook 缺资本账（capital accounting）绑定，不可晋级（§9）")
        linked = set(self.linked_assets)
        unlisted = [a for a in self.referenced_assets() if a not in linked]
        if unlisted:
            raise StrategyBookError(
                f"StrategyBook 引用资产但未登记进 linked_assets（run_config 无法注入）：{unlisted}（§1）"
            )

    def assert_runtime_executable(self) -> None:
        """**执行门（§9 红线）**：short intent ≠ runtime 可执行 short。

        逐条 short 腿判定，违一条即 StrategyBookExecutionError：
          · A股 short → 硬拒（R13 禁空头侧 + 项目红线 A股永不实盘），**不可被 requirement 绕过**。
          · 缺 short_exec → 拒（InstrumentSpec/venue/borrow/margin/regulation 全缺）。
          · short_exec 不齐全 → 拒，并列出缺项（borrow/margin/venue…）。
        全过（或无 short 腿）→ 不 raise。**注意：过门 ≠ 已下单**——真实下单仍只走 OrderGuard
        （唯一入口，本方法不绕过、不替代；runtime 接线是另一张卡）。
        """

        a_share = _is_a_share(self.asset_class)
        for leg in self.short_legs():
            if a_share:
                raise StrategyBookExecutionError(
                    f"A股 StrategyBook short 腿 {leg.asset_ref!r} 不可执行："
                    "A股禁空头侧（R13：融券近不可行）+ A股永不实盘（项目红线），不可绕过"
                )
            req = leg.short_exec
            if req is None:
                raise StrategyBookExecutionError(
                    f"short 腿 {leg.asset_ref!r} 缺执行要件（InstrumentSpec/venue/borrow/margin/regulation 全缺）："
                    "short intent ≠ 可执行 short（§9 红线）"
                )
            miss = req.missing()
            if miss:
                raise StrategyBookExecutionError(
                    f"short 腿 {leg.asset_ref!r} 不可执行：缺 {miss}"
                    "（short intent ≠ 可执行 short，§9 红线；真实下单仍须经 OrderGuard）"
                )


__all__ = [
    "AssetKind",
    "CapitalAccount",
    "LegSide",
    "LifecycleState",
    "PayoffKind",
    "PayoffSpec",
    "ShortExecutionRequirement",
    "StrategyBook",
    "StrategyBookError",
    "StrategyBookExecutionError",
    "StrategyLeg",
]
