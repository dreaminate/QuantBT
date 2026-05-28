"""Copy trade · master signal + follower 真 Binance 下单 + 私域 invite。

设计：
- master：任何用户都可以注册成 master，公开 metrics + 风控参数
- follower：订阅 master 时填自己的 binance keystore name + 投入额 + 单 follower 风控
- signal：master 一键发单（symbol+side+qty+price），后台 relay 到所有 active follower
- relay：每个 follower 都过 RiskMonitor.pre_trade，通过后调 follower **自己的** BinanceVenue
- 私域：master 可设 invite_only=True，订阅前必须先用 invite_code redeem

执行隔离：follower API key 永远走自己的 keystore，master 永远拿不到。
"""

from __future__ import annotations

from .executor import SignalRelayer, VenueFactory
from .service import (
    CopyTradeError,
    CopyTradeService,
    Execution,
    Follower,
    Master,
    Signal,
    init_copy_trade_db,
)

__all__ = [
    "CopyTradeError",
    "CopyTradeService",
    "Execution",
    "Follower",
    "Master",
    "Signal",
    "SignalRelayer",
    "VenueFactory",
    "init_copy_trade_db",
]
