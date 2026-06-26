"""§11 · InstrumentSpec typed 本体——每资产类 typed 合约声明（多资产 greenfield）。

为什么这一层存在（GOAL §0 多资产范围 + §11 数据层与标的接入 + 决策 S1-S4）：
- §0 已决：QuantBT 面向**所有公开二级市场**（股票/指数/ETF/基金/债券/利率/外汇/期货/商品/
  期权/加密现货·永续·期权/宏观·链上·另类·自定义）。要跨资产保持「同一资产引用 + 同一血统」，
  每个**可交易标的**必须有一份 typed 合约声明，把该资产类的结构性语义钉成机器可读字段。
- §11 给了每资产类的语义清单（期权 expiry/strike/multiplier/settlement·期货 roll/settlement·
  债 duration/convexity/day_count·FX base/quote/rollover·商品 storage/delivery/seasonality）。
  本模块把这些落成 typed 子类，缺关键字段即在构造期拒（可证伪门，不静默放过半成品 spec）。

身份单一源（RULES.project + 决策 S1）：`spec_id` 内容寻址自**结构性**字段，复用 lineage.ids
.content_hash（同一哈希族 16 位），刻意排除装饰字段（name/description）——改名不算新标的。
**绝不另造第二套哈希。**

诚实边界（RULES §3）：
- InstrumentSpec 只承载**合约条款**（expiry/strike/multiplier/coupon/roll…），**不**算 Greeks /
  IV surface / 久期数值推导——那是定价/风险引擎（另一层），本模块绝不声称能定价。Greeks/久期
  等只留**值字段或 ref 槽**（声明值，非新公式），无新公式 → 不造 MathematicalArtifact，只留
  `theory_binding_ref` 前向槽（§9 spine 后续绑定）。
- 跨币种结算（§11 跨市场资本账）只判「声明够不够」：缺 base currency / 缺 FX conversion 即拒
  （`assert_currency_settleable`），**不**自己取汇率、不下单。
- 宏观/链上/另类/自定义**数据**是 Observable/Dataset（数据层），不是可交易标的——不强造 spec。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ..lineage.ids import content_hash

# §0 全资产目录 token。与 strategy_goal.AssetClass（窄·成本模型派发: equity_cn/crypto_spot/
# crypto_perp/mixed）**token 兼容且为其超集**（扩展不替换：在新模块补全 §0 目录，不改既有窄枚举）。
# 注：`equity_cn` 是 region-encoded token——A股的 live 恒拒由 capability.live_forbidden 经
# security.gate.classify 单一源判定（含 "equity"/"cn" 即恒 paper），不在本枚举里硬编。
AssetClass = Literal[
    "equity",        # 股票（泛，非 A股）
    "equity_cn",     # A股（region-encoded：live 恒拒，单一源 classify）
    "index",         # 指数（多为标的物，亦可建 ref spec）
    "etf",           # ETF
    "fund",          # 基金
    "bond",          # 债券
    "rate",          # 利率
    "fx",            # 外汇
    "futures",       # 期货
    "commodity",     # 商品
    "options",       # 期权（标的为股票/指数/期货…）
    "crypto_spot",   # 加密现货
    "crypto_perp",   # 加密永续
    "crypto_option", # 加密期权
    "macro",         # 宏观数据（Observable，非可交易标的）
    "onchain",       # 链上数据（Observable）
    "alt",           # 另类数据（Observable）
    "custom",        # 用户自定义
    "mixed",         # 组合/跨类
]

SpecKind = Literal[
    "equity", "bond", "future", "option", "fx", "commodity",
    "crypto_spot", "crypto_perp", "generic",
]

Settlement = Literal["physical", "cash"]
ExerciseStyle = Literal["european", "american", "bermudan"]
OptionType = Literal["call", "put"]
DayCount = Literal["ACT/360", "ACT/365", "30/360", "ACT/ACT"]


class InstrumentSpecError(ValueError):
    """InstrumentSpec typed 契约不完整 / 资产类不匹配 / 解析失败（构造期拒，绝不静默放过）。"""


class CrossCurrencyError(InstrumentSpecError):
    """跨币种结算缺 base currency / FX conversion / 桥接不匹配（§11 跨市场资本账可证伪门）。"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ════════════════════════════════════════════════════════════════════
# 跨币种结算（§11 跨市场资本账：base currency + FX conversion）
# ════════════════════════════════════════════════════════════════════
class FxConversion(BaseModel):
    """一条币种换算声明（base ↔ quote）——`assert_currency_settleable` 的桥接凭据。

    诚实：本对象只**声明**换算来源/口径（rate_source 必填），是否真取到汇率、用哪个时点，
    由数据层落实；本模块绝不自己取汇率。`conversion_rate` 是可选钉值（缺则按 rate_source 实时取）。
    """

    base_currency: str = Field(..., min_length=1, description="记账本币（账户/组合 base）")
    quote_currency: str = Field(..., min_length=1, description="标的计价币（instrument quote）")
    rate_source: str = Field(..., min_length=1, description="汇率来源/口径（如 ecb_daily / binance_spot）——必填，缺则无据")
    conversion_rate: float | None = Field(None, gt=0, description="钉死的换算率（可选；缺则按 rate_source 实时取）")
    as_of: datetime | None = Field(None, description="该换算率的 as-of 时点（PIT）")

    def assert_bridges(self, quote: str, base: str) -> None:
        """校验本换算确实桥接 quote↔base（无序对匹配；汇率可逆，方向不挑）。不匹配即拒。"""

        declared = {self.base_currency.strip().upper(), self.quote_currency.strip().upper()}
        wanted = {(quote or "").strip().upper(), (base or "").strip().upper()}
        if declared != wanted:
            raise CrossCurrencyError(
                f"FX conversion 桥接不匹配：声明 {sorted(declared)}，需要 {sorted(wanted)}"
            )


# ════════════════════════════════════════════════════════════════════
# InstrumentSpec 基类（共享身份 / PIT / 血统 / 跨币种门）
# ════════════════════════════════════════════════════════════════════
class InstrumentSpec(BaseModel):
    """可交易标的的 typed 合约基类——共享身份、PIT、血统、跨币种结算门。

    身份 `spec_id` 内容寻址自结构性字段（spec_kind/symbol/asset_class/market/quote_currency +
    各子类 typed 字段），排除装饰字段（name/description/时间戳）。`spec_ref` 即下游
    `instrument_spec_ref`（strategy_book.ShortExecutionRequirement / Forecast）回填用的字符串。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 子类用 Literal 覆盖此处的 ALLOWED_ASSET_CLASSES（空集=不限）。
    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset()

    spec_kind: SpecKind = Field(..., description="结构判别式（discriminator）：决定有哪些 typed 字段")
    symbol: str = Field(..., min_length=1, description="标的代码（如 510300.SH / BTC-USDT / ES）")
    asset_class: AssetClass = Field(..., description="§0 资产类 token")
    quote_currency: str = Field(..., min_length=1, description="标的计价/结算币（如 CNY/USD/USDT）")
    market: str = Field("", description="市场/场所 region key（如 CN/US/BINANCE/CME）——matrix 寻址 + 诚实标注")
    exchange: str | None = Field(None, description="交易所")
    calendar_ref: str | None = Field(None, description="交易日历引用（exchange calendar）")
    # PIT / 血统（§11）——本 spec 版本何时可知/生效 + 回指数据层血统。
    known_at: datetime | None = Field(None, description="known_at：本 spec 版本何时可知（PIT；公司行动/合约变更）")
    effective_at: datetime | None = Field(None, description="effective_at：本 spec 何时起生效")
    source_lineage_ref: str | None = Field(None, description="回指数据层 dataset/lineage（source lineage）")
    theory_binding_ref: str | None = Field(None, description="§9 spine 前向槽：TheoryImplementationBinding 引用（无新公式则空）")
    name: str = Field("", description="可读名（装饰，不入身份）")
    description: str = Field("", description="说明（装饰，不入身份）")
    spec_id: str = Field("", description="内容寻址身份；留空则按结构字段自动计算")
    created_at_utc: str = Field(default_factory=_now_iso)

    @model_validator(mode="after")
    def _finalize(self) -> "InstrumentSpec":
        allowed = type(self).ALLOWED_ASSET_CLASSES
        if allowed and self.asset_class not in allowed:
            raise InstrumentSpecError(
                f"{type(self).__name__} 的 asset_class 必须 ∈ {sorted(allowed)}，得到 {self.asset_class!r}"
            )
        if not self.spec_id:
            structural = self.model_dump(
                mode="json",
                exclude={"name", "description", "spec_id", "created_at_utc"},
            )
            self.spec_id = "instr_" + content_hash(structural)[:12]
        return self

    @property
    def spec_ref(self) -> str:
        """下游 `instrument_spec_ref` 回填用字符串（= spec_id；非空即可被 strategy_book 引用门接受）。"""

        return self.spec_id

    # ----- 跨币种结算门（§11 跨市场资本账可证伪验收：缺 base currency / FX conversion → 拒）-----
    def needs_fx(self, base_currency: str | None) -> bool:
        """本标的相对账户 base currency 是否需要换汇（计价币 ≠ base 即需要）。"""

        if not base_currency or not str(base_currency).strip():
            return True  # 连 base 都没有 → 必然需要先有 base 才能谈
        return self.quote_currency.strip().upper() != base_currency.strip().upper()

    def assert_currency_settleable(
        self, *, base_currency: str | None, conversion: FxConversion | None = None
    ) -> None:
        """跨币种结算可证伪门（§11）。违一条即 CrossCurrencyError，绝不静默放过脏账。

          · 缺 base currency（账户本币未声明）→ 拒（无法记账）。
          · 计价币 ≠ base 且缺 FX conversion → 拒（缺 currency conversion）。
          · 提供了 conversion 但桥接不上（币对不匹配）→ 拒（伪换算）。
          · 计价币 == base（同币种）→ 放（无需换汇）。
        """

        if not base_currency or not str(base_currency).strip():
            raise CrossCurrencyError(
                f"标的 {self.symbol!r}（计价 {self.quote_currency}）跨币种结算缺 base currency："
                "账户本币未声明，无法记账（§11 跨市场资本账）"
            )
        qc = self.quote_currency.strip().upper()
        bc = base_currency.strip().upper()
        if qc == bc:
            return
        if conversion is None:
            raise CrossCurrencyError(
                f"跨币种 {qc}->{bc} 缺 FX conversion（标的 {self.symbol!r}）：缺 currency conversion，拒（§11）"
            )
        conversion.assert_bridges(quote=qc, base=bc)


# ════════════════════════════════════════════════════════════════════
# 每资产类 typed 子类（§11 语义 → typed 字段）
# ════════════════════════════════════════════════════════════════════
class EquitySpec(InstrumentSpec):
    """股票/指数/ETF/基金（cash equity-like）。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset(
        {"equity", "equity_cn", "index", "etf", "fund"}
    )
    spec_kind: Literal["equity"] = "equity"
    lot_size: int = Field(1, gt=0, description="最小交易单位（A股=100）")
    is_etf: bool = Field(False, description="是否 ETF")
    underlying_index_ref: str | None = Field(None, description="跟踪指数引用（ETF/指数衍生）")
    board: str | None = Field(None, description="板块（主板/科创板/创业板…）")


class BondSpec(InstrumentSpec):
    """债券/利率（§11：duration/convexity/yield curve/accrued interest/coupon/maturity/day count）。

    duration/convexity 是**声明值**（风险度量字段），非本模块推导的新公式。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"bond", "rate"})
    spec_kind: Literal["bond"] = "bond"
    coupon_rate: float = Field(..., ge=0, description="票息率（年化比率；零息=0）")
    maturity: datetime = Field(..., description="到期日（maturity）")
    day_count: DayCount = Field(..., description="计息基准（day count）")
    face_value: float = Field(100.0, gt=0, description="面值")
    coupon_frequency: int = Field(2, ge=0, description="年付息次数（0=零息）")
    duration: float | None = Field(None, ge=0, description="久期（声明值；modified/Macaulay）")
    convexity: float | None = Field(None, description="凸性（声明值）")
    accrued_interest: float | None = Field(None, ge=0, description="应计利息（声明值）")
    yield_curve_ref: str | None = Field(None, description="收益率曲线引用")


class FutureSpec(InstrumentSpec):
    """期货（§11：roll rule/margin/settlement/contract multiplier/delivery/continuous contract）。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"futures", "commodity", "rate"})
    spec_kind: Literal["future"] = "future"
    expiry: datetime = Field(..., description="合约到期日")
    contract_multiplier: float = Field(..., gt=0, description="合约乘数")
    settlement: Settlement = Field(..., description="交割方式（physical/cash）")
    roll_rule: str = Field(..., min_length=1, description="移仓规则（如 n_days_before_expiry:5 / volume_oi_switch）")
    delivery: str | None = Field(None, description="交割说明")
    margin_requirement: float | None = Field(None, ge=0, description="保证金要求（比率或名义）")
    continuous_contract_rule: str | None = Field(None, description="连续合约构造（panama/ratio/none）")
    underlying_ref: str | None = Field(None, description="标的物引用")


class OptionSpec(InstrumentSpec):
    """期权（§11：expiry/strike/contract multiplier/settlement/exercise style/assignment/margin）。

    可证伪门（§11）：**expiry/strike/contract_multiplier/settlement 四者缺一即构造期拒**
    （required field + Field(gt=0)；MUT 把任一改为可选即被 test_instrument_spec 抓红）。
    Greeks / IV surface / term structure 是**定价/风险引擎**产物（运行期），不在合约 spec 里——
    本模块绝不算它们（诚实边界），只钉合约条款。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"options", "crypto_option"})
    spec_kind: Literal["option"] = "option"
    expiry: datetime = Field(..., description="到期日（必填·缺即拒）")
    strike: float = Field(..., gt=0, description="行权价（必填·>0·缺即拒）")
    contract_multiplier: float = Field(..., gt=0, description="合约乘数（必填·>0·缺即拒）")
    settlement: Settlement = Field(..., description="交割方式 physical/cash（必填·缺即拒）")
    exercise_style: ExerciseStyle = Field(..., description="行权方式（european/american/bermudan）")
    option_type: OptionType = Field(..., description="call/put")
    underlying_ref: str = Field(..., min_length=1, description="标的物引用（必填）")
    margin_requirement: float | None = Field(None, ge=0, description="保证金要求（卖方）")


class FxSpec(InstrumentSpec):
    """外汇（§11：base/quote/rollover/funding/holiday calendar/conversion rate）。

    quote_currency（基类）= quote_ccy（_finalize 强制一致），保证跨币种门口径不裂。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"fx"})
    spec_kind: Literal["fx"] = "fx"
    base_ccy: str = Field(..., min_length=3, max_length=3, description="基准货币（如 EUR）")
    quote_ccy: str = Field(..., min_length=3, max_length=3, description="计价货币（如 USD）")
    rollover: bool = Field(True, description="是否隔夜滚动（rollover/swap 适用）")
    funding_basis: str | None = Field(None, description="融资/掉期基准（funding）")
    holiday_calendar_ref: str | None = Field(None, description="假期日历引用")
    pip_size: float = Field(0.0001, gt=0, description="最小报价变动（pip）")

    @model_validator(mode="before")
    @classmethod
    def _sync_quote_ccy(cls, data: Any) -> Any:
        # FX 计价币 == quote_ccy。用 mode="before" 在字段校验前对齐，避免与基类 _finalize
        # （算 spec_id）的 after-validator 次序耦合（顺序无关，spec_id 必含正确 quote_currency）。
        if isinstance(data, dict):
            qq = str(data.get("quote_ccy", "")).strip().upper()
            if qq:
                existing = str(data.get("quote_currency", "")).strip().upper()
                if existing and existing != qq:
                    raise InstrumentSpecError(
                        f"FxSpec quote_currency({existing}) 必须 == quote_ccy({qq})"
                    )
                data = {**data, "quote_currency": qq}
        return data


class CommoditySpec(InstrumentSpec):
    """商品（§11：storage/delivery/contract spec/seasonality/calendar spread）。

    商品多为期货载体：要 roll/连续合约用 FutureSpec(asset_class=commodity)；要 storage/季节性
    等商品专属字段用本类。两者按需选，文档化（不强制单选，避免误伤）。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"commodity"})
    spec_kind: Literal["commodity"] = "commodity"
    contract_multiplier: float = Field(..., gt=0, description="合约乘数")
    settlement: Settlement = Field("physical", description="交割方式")
    expiry: datetime | None = Field(None, description="到期日（现货商品可空）")
    storage_cost_bps: float | None = Field(None, ge=0, description="仓储成本 bps（storage）")
    delivery: str | None = Field(None, description="交割说明")
    seasonality: str | None = Field(None, description="季节性模式描述/引用")
    calendar_spread_ref: str | None = Field(None, description="跨期价差引用（calendar spread）")
    grade: str | None = Field(None, description="品级/质量（contract spec）")
    underlying_ref: str | None = Field(None, description="标的物引用")


class CryptoSpotSpec(InstrumentSpec):
    """加密现货。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"crypto_spot"})
    spec_kind: Literal["crypto_spot"] = "crypto_spot"
    base_asset: str | None = Field(None, description="基础资产（如 BTC）")
    min_qty: float = Field(0.0, ge=0, description="最小下单量")
    tick_size: float = Field(0.0, ge=0, description="最小价格变动")


class CryptoPerpSpec(InstrumentSpec):
    """加密永续（funding/margin/leverage 语义；唯一可达 live 的资产类之一）。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"crypto_perp"})
    spec_kind: Literal["crypto_perp"] = "crypto_perp"
    base_asset: str | None = Field(None, description="基础资产（如 BTC）")
    contract_multiplier: float = Field(1.0, gt=0, description="合约乘数")
    funding_interval_hours: int = Field(8, gt=0, description="资金费率结算间隔（小时）")
    funding_rate_ref: str | None = Field(None, description="资金费率来源引用")
    margin_requirement: float | None = Field(None, ge=0, description="保证金要求")
    max_leverage: float | None = Field(None, gt=0, description="最大杠杆（合约规则）")


class GenericInstrumentSpec(InstrumentSpec):
    """自定义/未知可交易标的（§0「用户自定义」+「可以添加新内容」）。

    诚实：本类**无资产类专属 typed 门**，只承载自定义属性——不假装有期权/期货那样的结构校验。
    扩展点：新资产类应优先建专属子类（带 typed 门），GenericInstrumentSpec 是兜底不是默认。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset()  # 不限
    spec_kind: Literal["generic"] = "generic"
    attributes: dict[str, Any] = Field(default_factory=dict, description="自定义属性（无专属门）")


# ──────────────────────────────────────────────────────────────────
# 判别式联合 + 解析工厂（显式可证伪门：缺必填字段 → InstrumentSpecError）
# ──────────────────────────────────────────────────────────────────
ConcreteInstrumentSpec = Union[
    EquitySpec, BondSpec, FutureSpec, OptionSpec, FxSpec,
    CommoditySpec, CryptoSpotSpec, CryptoPerpSpec, GenericInstrumentSpec,
]
AnyInstrumentSpec = Annotated[ConcreteInstrumentSpec, Field(discriminator="spec_kind")]
_SPEC_ADAPTER: TypeAdapter[InstrumentSpec] = TypeAdapter(AnyInstrumentSpec)


def _summarize_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc or '<root>'}: {err.get('msg', '')}")
    return "; ".join(parts) or str(exc)


def parse_instrument_spec(data: dict[str, Any]) -> InstrumentSpec:
    """从 dict 解析 typed InstrumentSpec（按 spec_kind 判别）。

    这是**显式可证伪门**：任一子类必填字段缺失/非法 → 统一抛 InstrumentSpecError（含缺项 loc）。
    期权缺 expiry/strike/contract_multiplier/settlement 走这里即拒（§11 可证伪验收）。
    """

    if not isinstance(data, dict) or not data.get("spec_kind"):
        raise InstrumentSpecError("parse_instrument_spec 需 dict 且含判别式 spec_kind")
    try:
        return _SPEC_ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise InstrumentSpecError(
            f"InstrumentSpec({data.get('spec_kind')}) 解析失败（缺/非法字段）：{_summarize_validation_error(exc)}"
        ) from exc


__all__ = [
    "AnyInstrumentSpec",
    "AssetClass",
    "BondSpec",
    "CommoditySpec",
    "CrossCurrencyError",
    "CryptoPerpSpec",
    "CryptoSpotSpec",
    "DayCount",
    "EquitySpec",
    "ExerciseStyle",
    "FutureSpec",
    "FxConversion",
    "FxSpec",
    "GenericInstrumentSpec",
    "InstrumentSpec",
    "InstrumentSpecError",
    "OptionSpec",
    "OptionType",
    "Settlement",
    "SpecKind",
    "parse_instrument_spec",
]
