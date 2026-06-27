"""Paper trading 调度器 + 工厂。

GOAL §M9.4 A股 paper trading：用回测同一套撮合器 + 实时 bar 驱动 + 每日 MTM。
"""

from __future__ import annotations

from .desk import (
    AShareLiveForbidden,
    FrozenRiskGate,
    PaperDeskService,
    PaperRunNotFound,
    PromotionGate,
    RiskGateMutationForbidden,
)
from .replay_provider import BUNDLED_SAMPLE_SOURCE, BUNDLED_SOURCE, MIXED_REPLAY_SOURCE, ReplayBarProvider, SIMULATED_SOURCE
from .scheduler import PaperScheduler, PaperSchedulerConfig
from .testnet_provider import (
    BinanceTestnetBarProvider,
    TESTNET_REALTIME_SOURCE,
    TESTNET_SOURCE,
    TESTNET_UNAVAILABLE_SOURCE,
    TestnetBarProvider,
    make_binance_testnet_provider,
    make_testnet_provider,
)

__all__ = [
    "AShareLiveForbidden",
    "BinanceTestnetBarProvider",
    "BUNDLED_SAMPLE_SOURCE",
    "BUNDLED_SOURCE",
    "FrozenRiskGate",
    "MIXED_REPLAY_SOURCE",
    "PaperDeskService",
    "PaperRunNotFound",
    "PaperScheduler",
    "PaperSchedulerConfig",
    "PromotionGate",
    "ReplayBarProvider",
    "RiskGateMutationForbidden",
    "SIMULATED_SOURCE",
    "TESTNET_REALTIME_SOURCE",
    "TESTNET_SOURCE",
    "TESTNET_UNAVAILABLE_SOURCE",
    "TestnetBarProvider",
    "make_binance_testnet_provider",
    "make_testnet_provider",
]
