"""§11 · 多资产标的接入本体（greenfield）。

两件 typed 本体（GOAL §11 + §0 全公开二级市场）：
- `spec.py` — InstrumentSpec：每资产类 typed 合约（期权 expiry/strike/multiplier/settlement·
  期货 roll/settlement·债 duration/convexity/day_count·FX base/quote/rollover·商品 storage/
  seasonality）+ 跨币种结算门（缺 base currency / FX conversion → 拒）。
- `capability.py` — MarketCapabilityMatrix：每 (asset_class, market) 的可达环境/能力/可得性 +
  live 门（缺 live 权限 → 拒；A股 live = 恒拒，单一源 security.gate.classify）。

身份复用 lineage.ids（content_hash 单一哈希族）；live 恒拒复用 security.gate.classify（执行权限
单一源）。下游 `instrument_spec_ref`（strategy_book.ShortExecutionRequirement / Forecast）用
`InstrumentSpec.spec_ref` 回填。过本层门 ≠ 已下单——真实下单仍只走 OrderGuard。
"""

from .capability import (
    Availability,
    CapAction,
    ExecEnv,
    MarketCapability,
    MarketCapabilityError,
    MarketCapabilityMatrix,
    live_forbidden,
)
from .spec import (
    AnyInstrumentSpec,
    AssetClass,
    BondSpec,
    CommoditySpec,
    CrossCurrencyError,
    CryptoPerpSpec,
    CryptoSpotSpec,
    DayCount,
    EquitySpec,
    ExerciseStyle,
    FutureSpec,
    FxConversion,
    FxSpec,
    GenericInstrumentSpec,
    InstrumentSpec,
    InstrumentSpecError,
    OptionSpec,
    OptionType,
    Settlement,
    SpecKind,
    parse_instrument_spec,
)

__all__ = [
    "AnyInstrumentSpec",
    "AssetClass",
    "Availability",
    "BondSpec",
    "CapAction",
    "CommoditySpec",
    "CrossCurrencyError",
    "CryptoPerpSpec",
    "CryptoSpotSpec",
    "DayCount",
    "EquitySpec",
    "ExecEnv",
    "ExerciseStyle",
    "FutureSpec",
    "FxConversion",
    "FxSpec",
    "GenericInstrumentSpec",
    "InstrumentSpec",
    "InstrumentSpecError",
    "MarketCapability",
    "MarketCapabilityError",
    "MarketCapabilityMatrix",
    "OptionSpec",
    "OptionType",
    "Settlement",
    "SpecKind",
    "live_forbidden",
    "parse_instrument_spec",
]
