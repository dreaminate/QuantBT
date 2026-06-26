"""A4 · 策略台后端模块（候选池 handoff，止于模拟盘）。

§9 typed 契约：Forecast（模型输出→Signal Contract→Signal）+ StrategyBook（多腿组合意图/
payoff/资本账/short intent≠可执行 short）。详见 forecast.py / strategy_book.py。
"""

from .candidate_pool import CandidatePoolStore, HandoffRejected
from .forecast import (
    Forecast,
    ForecastError,
    ForecastKind,
    SourceLib,
    bind_forecast_to_signal,
)
from .strategy_book import (
    CapitalAccount,
    PayoffSpec,
    ShortExecutionRequirement,
    StrategyBook,
    StrategyBookError,
    StrategyBookExecutionError,
    StrategyLeg,
)

__all__ = [
    "CandidatePoolStore",
    "CapitalAccount",
    "Forecast",
    "ForecastError",
    "ForecastKind",
    "HandoffRejected",
    "PayoffSpec",
    "ShortExecutionRequirement",
    "SourceLib",
    "StrategyBook",
    "StrategyBookError",
    "StrategyBookExecutionError",
    "StrategyLeg",
    "bind_forecast_to_signal",
]
