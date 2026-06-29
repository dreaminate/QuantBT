"""§0/§11 · 资产类目录 + typed 合约 enums 的【单一定义源】。

为什么独立成一个纯 Literal 模块（RULES.project「单一源锚点」）：
- §0 全资产目录 `AssetClass` 只此一份定义。下游窄枚举 `strategy_goal.AssetClass`
  （成本模型派发: equity_cn/crypto_spot/crypto_perp/mixed）必须是本目录的**子集**
  （扩展不替换 · test_asset_class_single_source 把这条钉成机器可证不变量）。
- 纯 `typing.Literal`、零额外 import → 任何层（market_data_contract / 未来 typed 本体）
  都能引它而不引入 import 环。

注：`equity_cn` 是 region-encoded token——A 股的 live 恒拒由 capability.live_forbidden 经
security.gate.classify 单一源判定（含 "equity"/"cn" 即恒 paper），不在本枚举里硬编。
"""

from __future__ import annotations

from typing import Literal

# §0 全资产目录 token。与 strategy_goal.AssetClass（窄·成本模型派发）**token 兼容且为其超集**
# （扩展不替换：在此补全 §0 目录，不改既有窄枚举）。
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

# 结构判别式（discriminator）：typed 合约子类按此派发有哪些 typed 字段。
SpecKind = Literal[
    "equity", "bond", "future", "option", "fx", "commodity",
    "crypto_spot", "crypto_perp", "generic",
]

# 各资产类 typed 合约取值域（可证伪门：value 提供时必 ∈ 域，否则拒）。
Settlement = Literal["physical", "cash"]
ExerciseStyle = Literal["european", "american", "bermudan"]
OptionType = Literal["call", "put"]
DayCount = Literal["ACT/360", "ACT/365", "30/360", "ACT/ACT"]


__all__ = [
    "AssetClass",
    "DayCount",
    "ExerciseStyle",
    "OptionType",
    "SpecKind",
    "Settlement",
]
