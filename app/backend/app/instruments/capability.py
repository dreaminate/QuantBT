"""§11 · MarketCapabilityMatrix——每标的/市场的能力（live 权限/可执行性/数据可得）。

为什么这一层存在（GOAL §11 + §12 执行边界 + RULES.project A股永不实盘 + 决策 D-PERM）：
- §11 要求 MarketCapabilityMatrix 记录每 (asset_class, market) 的：research/backtest/paper/
  testnet/live 可达 + long/short/leverage/options/margin/borrow 能力 + data/cost_model/
  execution 可得 + permission_requirement。研究侧放开、执行侧硬锁的边界落在这张表的 live 门。
- 可证伪验收（§11 + 本卡）：**缺 live 权限仍尝试 live → 拒**；**A股 live = 恒拒**（永不实盘）。

A股 live 恒拒的**单一源**（RULES.project 单一锚点 + 不另造）：
- live 是否被禁，**复用 `security.gate.policy.classify`**（执行权限分级的权威源）——A股/equity/CN
  token → 恒 `TrustTier.PAPER`（永不 live）。本模块**不重写**一套 A股 marker，避免「第二本账」
  与执行门漂移。`live_forbidden()` 即 `classify(...) == PAPER`。
- 硬恒拒**不可被 `live=True` 标志位绕过**：哪怕记录被伪造成 live=True + 权限齐 + execution
  available，`assert_can_execute("live")` 仍先过 `live_forbidden` 硬墙拒（MUT 删此墙即被测试抓红）。

诚实边界（RULES §3）：
- 过本能力门 **≠ 已下单**。真实下单的唯一硬墙是 OrderGuard（D-PERM 唯一入口）+ 交易所侧远程
  信任域；本表是**研究/能力层**的 deny-by-default 门，不绕 OrderGuard、不持 key、不发单。
- 未登记的 (asset_class, market) → deny-by-default（缺记录 = 缺权限 = 拒），不静默放行未知市场。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..lineage.ids import content_hash
from ..security.gate.policy import TrustTier, classify

ExecEnv = Literal["research", "backtest", "paper", "testnet", "live"]
CapAction = Literal["long", "short", "leverage", "options", "margin", "borrow"]
Availability = Literal["available", "partial", "unavailable"]


class MarketCapabilityError(ValueError):
    """能力门拒绝（缺 live 权限 / A股 live 恒拒 / 能力未开放 / 未登记市场 deny-by-default）。"""


def live_forbidden(asset_class: str, market: str = "") -> bool:
    """该 (asset_class[, market]) 是否 live 恒拒——**单一源** security.gate.policy.classify。

    classify 在 is_live=True 时唯一返回 PAPER 的分支就是 A股/equity/CN token；其余（crypto…）
    返回 CRYPTO_LIVE。故 `classify(token, True) == PAPER` ⟺ 「此市场 live 恒拒」。
    asset_class 是主信号（region-encoded，如 equity_cn）；market 仅作补充 token 一并喂入，
    只会**增加**命中机会、绝不放松（A股双保险：'equity' 与 'cn' 各自独立触发 PAPER）。
    """

    token = f"{asset_class or ''} {market or ''}".strip()
    return classify(token, is_live=True) == TrustTier.PAPER


class MarketCapability(BaseModel):
    """一条 (asset_class, market) 能力记录（§11 字段全 typed）。

    `live` 是**声明的** live 权限位；**有效** live 权限还要过 `live_forbidden` 硬墙
    （`effective_live_permission()` 诚实给出真相：声明 live 但市场恒拒 → 实际 False）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    asset_class: str = Field(..., min_length=1, description="§0 资产类 token（equity_cn/crypto_perp/futures…）")
    instrument_type: str = Field(..., min_length=1, description="标的类型（spot/perp/option/future/bond…）")
    market: str = Field("", description="市场/场所 region key（CN/US/BINANCE/CME…）")
    # 可达环境（§11）
    research: bool = Field(True, description="可研究")
    backtest: bool = Field(True, description="可回测")
    paper: bool = Field(True, description="可模拟盘")
    testnet: bool = Field(False, description="可测试网（假钱真发交易所）")
    live: bool = Field(False, description="声明的 live 权限（有效性还过 live_forbidden 硬墙）")
    # 能力（§11）
    long: bool = Field(True, description="可做多")
    short: bool = Field(False, description="可做空")
    leverage: bool = Field(False, description="可加杠杆")
    options: bool = Field(False, description="支持期权")
    margin: bool = Field(False, description="支持保证金")
    borrow: bool = Field(False, description="可借券/可融")
    # 可得性（§11）
    data_availability: Availability = Field("unavailable", description="数据可得")
    cost_model_availability: Availability = Field("unavailable", description="成本模型可得")
    execution_availability: Availability = Field("unavailable", description="执行可得")
    permission_requirement: str | None = Field(None, description="live 所需权限标识（如 binance_trade_key）；缺则 deny")
    capability_id: str = Field("", description="内容寻址身份；留空自动计算")

    @model_validator(mode="after")
    def _fill_id(self) -> "MarketCapability":
        if not self.capability_id:
            key = self.model_dump(mode="json", exclude={"capability_id"})
            self.capability_id = "cap_" + content_hash(key)[:12]
        return self

    # ----- 诚实派生 -----
    def is_live_forbidden(self) -> bool:
        return live_forbidden(self.asset_class, self.market)

    def effective_live_permission(self) -> bool:
        """实际 live 权限：声明 live 且**非**恒拒市场。声明 live 但 A股/equity → 诚实给 False。"""

        return self.live and not self.is_live_forbidden()

    # ----- 门 -----
    def assert_can_execute(
        self, env: ExecEnv, *, granted_permissions: frozenset[str] | set[str] = frozenset()
    ) -> None:
        """可达环境门（deny-by-default）。违一条即 MarketCapabilityError，绝不静默放行。

        env == "live"（顺序即优先级）：
          1. **硬恒拒墙**：`live_forbidden` → 拒（A股/equity 永不实盘·RULES.project；单一源
             classify）。**不可被 live=True / 权限 / execution_availability 绕过**（MUT 删此墙即红）。
          2. 缺 live 权限：`live=False` → 拒（§11「缺 live 权限仍尝试 live → 拒」）。
          3. 权限要件未授予：`permission_requirement` 不在 granted_permissions → 拒。
          4. execution_availability=="unavailable" → 拒（无执行通道）。
        其他 env：对应可达位为 False → 拒。
        **过门 ≠ 已下单**：真实下单仍只走 OrderGuard（唯一入口）+ 交易所硬墙。
        """

        if env == "live":
            if self.is_live_forbidden():
                raise MarketCapabilityError(
                    f"{self.asset_class}/{self.market or '*'} live 恒拒："
                    "A股/equity 永不实盘（RULES.project）；单一源 security.gate.classify→PAPER，不可绕过"
                )
            if not self.live:
                raise MarketCapabilityError(
                    f"{self.asset_class}/{self.market or '*'} 未授予 live 权限，拒绝 live"
                    "（§11：缺 live 权限仍尝试 live → 拒）"
                )
            if self.permission_requirement and self.permission_requirement not in set(granted_permissions):
                raise MarketCapabilityError(
                    f"live 需权限 {self.permission_requirement!r} 未授予（deny-by-default）"
                )
            if self.execution_availability == "unavailable":
                raise MarketCapabilityError(
                    f"{self.asset_class}/{self.market or '*'} execution_availability=unavailable，无 live 执行通道"
                )
            return

        flag = {
            "research": self.research,
            "backtest": self.backtest,
            "paper": self.paper,
            "testnet": self.testnet,
        }[env]
        if not flag:
            raise MarketCapabilityError(
                f"{self.asset_class}/{self.market or '*'} 环境 {env} 能力未开放"
            )

    def assert_supports(self, *actions: CapAction) -> None:
        """能力门（§11 long/short/leverage/options/margin/borrow）。缺任一即拒。"""

        flags = {
            "long": self.long, "short": self.short, "leverage": self.leverage,
            "options": self.options, "margin": self.margin, "borrow": self.borrow,
        }
        missing = [a for a in actions if not flags[a]]
        if missing:
            raise MarketCapabilityError(
                f"{self.asset_class}/{self.market or '*'} 不支持能力 {missing}（§11 capability matrix）"
            )


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


class MarketCapabilityMatrix(BaseModel):
    """MarketCapabilityMatrix（§11）——按 (asset_class, market) 索引能力记录 + deny-by-default 门。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    entries: list[MarketCapability] = Field(default_factory=list)

    def _key(self, asset_class: str, market: str = "") -> tuple[str, str]:
        return (_norm(asset_class), _norm(market))

    def register(self, cap: MarketCapability) -> MarketCapability:
        """登记/覆盖一条能力（同 key 覆盖为新世代）。返回登记的记录。"""

        k = self._key(cap.asset_class, cap.market)
        self.entries = [e for e in self.entries if self._key(e.asset_class, e.market) != k]
        self.entries.append(cap)
        return cap

    def get(self, asset_class: str, market: str = "") -> MarketCapability:
        """取 (asset_class, market) 记录——**未登记即 deny-by-default 拒**（缺记录=缺权限）。"""

        k = self._key(asset_class, market)
        for e in self.entries:
            if self._key(e.asset_class, e.market) == k:
                return e
        raise MarketCapabilityError(
            f"未登记的市场 ({asset_class}, {market or '*'})：deny-by-default（缺记录=缺权限，拒）"
        )

    def assert_can_execute(
        self, asset_class: str, market: str = "", *, env: ExecEnv,
        granted_permissions: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        """查表 + 过门（未登记 → 拒；A股 live → 恒拒；缺 live 权限 → 拒）。"""

        self.get(asset_class, market).assert_can_execute(env, granted_permissions=granted_permissions)


__all__ = [
    "Availability",
    "CapAction",
    "ExecEnv",
    "MarketCapability",
    "MarketCapabilityError",
    "MarketCapabilityMatrix",
    "live_forbidden",
]
