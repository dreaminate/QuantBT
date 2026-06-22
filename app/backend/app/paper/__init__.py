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
from .replay_provider import ReplayBarProvider, SIMULATED_SOURCE
from .scheduler import PaperScheduler, PaperSchedulerConfig

__all__ = [
    "AShareLiveForbidden",
    "FrozenRiskGate",
    "PaperDeskService",
    "PaperRunNotFound",
    "PaperScheduler",
    "PaperSchedulerConfig",
    "PromotionGate",
    "ReplayBarProvider",
    "RiskGateMutationForbidden",
    "SIMULATED_SOURCE",
]
