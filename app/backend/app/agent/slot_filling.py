"""M14 · 自然语言 → StrategyGoal 槽位补全。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..strategy_goal import (
    Constraints,
    CryptoPerpCostModel,
    CryptoSpotCostModel,
    EquityCostModel,
    EvaluationWindow,
    StrategyGoal,
)


_HORIZON_MAP = {
    "日内": "intraday",
    "日频": "daily",
    "周频": "weekly",
    "月频": "monthly",
}


_OBJECTIVE_MAP = {
    "夏普": "max_sharpe",
    "sharpe": "max_sharpe",
    "calmar": "max_calmar",
    "卡玛": "max_calmar",
    "信息比": "info_ratio",
    "ir": "info_ratio",
    "回撤": "min_drawdown",
    "sortino": "max_sortino",
}


class StrategyGoalSlotFiller:
    """开发期 / 备用：用关键词 + regex 补全 StrategyGoal。

    生产可换成 LLM tool-calling；这里保证即使没有真 LLM，QuantBT 也能完成核心
    『自然语言 → StrategyGoal』链路。
    """

    def fill(self, text: str, *, name: str | None = None) -> StrategyGoal:
        text_low = text.lower()
        asset_class = self._guess_asset_class(text, text_low)
        horizon = self._first_match(text, _HORIZON_MAP) or "daily"
        objective = self._first_match(text_low, _OBJECTIVE_MAP) or "max_sharpe"
        constraints = self._guess_constraints(text)
        cost_model: Any
        benchmark: str
        if asset_class == "equity_cn":
            cost_model = EquityCostModel()
            benchmark = "000300.SH"
            constraints.leverage_max = 1.0
        elif asset_class == "crypto_perp":
            cost_model = CryptoPerpCostModel()
            benchmark = "BTC-USDT"
        else:
            cost_model = CryptoSpotCostModel()
            benchmark = "BTC-USDT"
        return StrategyGoal(
            name=name or f"{asset_class}_{horizon}",
            asset_class=asset_class,  # type: ignore[arg-type]
            objective=objective,  # type: ignore[arg-type]
            horizon=horizon,  # type: ignore[arg-type]
            benchmark=benchmark,
            constraints=constraints,
            cost_model=cost_model,
            evaluation_window=EvaluationWindow(
                backtest_start=date(2018, 1, 1),
                backtest_end=date(2025, 12, 31),
            ),
            description=text[:200],
        )

    @staticmethod
    def _guess_asset_class(raw: str, lower: str) -> str:
        if any(k in lower for k in ("永续", "perp", "futures")):
            return "crypto_perp"
        if any(k in lower for k in ("加密", "btc", "binance", "crypto")):
            return "crypto_spot"
        if any(k in lower for k in ("a股", "沪深", "中证", "etf", "stock")):
            return "equity_cn"
        return "mixed"

    @staticmethod
    def _first_match(text: str, mapping: dict[str, str]) -> str | None:
        for key, value in mapping.items():
            if key in text:
                return value
        return None

    def _guess_constraints(self, text: str) -> Constraints:
        c = Constraints()
        dd = self._first_float(text, r"(?:回撤|max_dd)\D*([0-9]+(?:\.[0-9]+)?)%?")
        if dd:
            c.max_dd = dd / 100 if dd > 1 else dd
        single = self._first_float(text, r"(?:单标的|单仓|single_pos)\D*([0-9]+(?:\.[0-9]+)?)%?")
        if single:
            c.single_pos_max = single / 100 if single > 1 else single
        leverage = self._first_float(text, r"(?:杠杆|leverage)\D*([0-9]+(?:\.[0-9]+)?)x?")
        if leverage:
            c.leverage_max = leverage
        if "做空" in text or "long-short" in text.lower():
            c.short_allowed = True
        return c

    @staticmethod
    def _first_float(text: str, pattern: str) -> float | None:
        m = re.search(pattern, text)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None


__all__ = ["StrategyGoalSlotFiller"]
