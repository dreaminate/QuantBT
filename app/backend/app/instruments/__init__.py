"""§11 · 多资产标的接入本体（greenfield）—— capability 层。

- `capability.py` — MarketCapabilityMatrix：每 (asset_class, market) 的可达环境/能力/可得性 +
  live 门（缺 live 权限 → 拒；A股 live = 恒拒，单一源 security.gate.classify）。

标的 typed 本体（InstrumentSpec / 每资产类 typed 合约 / 跨币种结算门 / parse_instrument_spec /
FxConversion）+ AssetClass 全资产目录已**上移 research_os 作单一源**（C-S11）：typed 合约在
`research_os.market_data_contract`（与 LIVE flat InstrumentSpec 同模块单一源），AssetClass 在
`research_os.asset_class`。本包不再 re-export spec（orphan instruments/spec.py 已删）。

live 恒拒复用 security.gate.classify（执行权限单一源）。过本层门 ≠ 已下单——真实下单仍只走 OrderGuard。
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

__all__ = [
    "Availability",
    "CapAction",
    "ExecEnv",
    "MarketCapability",
    "MarketCapabilityError",
    "MarketCapabilityMatrix",
    "live_forbidden",
]
