from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.strategy_goal import (
    PRESETS,
    Constraints,
    CryptoPerpCostModel,
    CryptoSpotCostModel,
    EquityCostModel,
    EvaluationWindow,
    StrategyGoal,
)


def _eval_window() -> EvaluationWindow:
    return EvaluationWindow(
        backtest_start=date(2020, 1, 1),
        backtest_end=date(2024, 12, 31),
    )


def test_a_share_preset_round_trip(tmp_path: Path) -> None:
    goal = PRESETS["a_share_weekly_top_decile"]
    out = tmp_path / "goal.yaml"
    goal.save_yaml(out)
    loaded = StrategyGoal.from_yaml(out)
    assert loaded.asset_class == "equity_cn"
    assert isinstance(loaded.cost_model, EquityCostModel)
    assert loaded.cost_model.stamp_duty_bps == pytest.approx(10.0)
    assert loaded.constraints.leverage_max == 1.0


def test_crypto_perp_round_trip(tmp_path: Path) -> None:
    goal = PRESETS["crypto_perp_trend_daily"]
    out = tmp_path / "goal.yaml"
    goal.save_yaml(out)
    loaded = StrategyGoal.from_yaml(out)
    assert loaded.asset_class == "crypto_perp"
    assert isinstance(loaded.cost_model, CryptoPerpCostModel)
    assert loaded.cost_model.funding_rate_apply is True


def test_dict_dispatches_cost_model() -> None:
    data = {
        "name": "spot demo",
        "asset_class": "crypto_spot",
        "horizon": "daily",
        "benchmark": "BTC-USDT",
        "cost_model": {"maker_bps": 7.5, "taker_bps": 10.0},
        "evaluation_window": {
            "backtest_start": "2022-01-01",
            "backtest_end": "2024-01-01",
        },
    }
    goal = StrategyGoal.model_validate(data)
    assert isinstance(goal.cost_model, CryptoSpotCostModel)
    assert goal.cost_model.maker_bps == pytest.approx(7.5)


def test_a_share_rejects_live_crypto() -> None:
    with pytest.raises(ValueError, match="live_crypto"):
        StrategyGoal(
            name="bad",
            asset_class="equity_cn",
            execution_mode="live_crypto",
            cost_model=EquityCostModel(),
            evaluation_window=_eval_window(),
        )


def test_a_share_forces_leverage_one() -> None:
    with pytest.raises(ValueError, match="leverage_max"):
        StrategyGoal(
            name="bad",
            asset_class="equity_cn",
            cost_model=EquityCostModel(),
            constraints=Constraints(leverage_max=2.0),
            evaluation_window=_eval_window(),
        )


def test_custom_python_requires_path() -> None:
    with pytest.raises(ValueError, match="custom_python_path"):
        StrategyGoal(
            name="bad",
            asset_class="crypto_spot",
            objective="custom_python",
            cost_model=CryptoSpotCostModel(),
            evaluation_window=_eval_window(),
        )


def test_cost_model_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="CryptoPerpCostModel"):
        StrategyGoal(
            name="bad",
            asset_class="crypto_perp",
            cost_model=CryptoSpotCostModel(),
            evaluation_window=_eval_window(),
        )


def test_evaluation_window_range_validated() -> None:
    with pytest.raises(ValueError, match="backtest_end"):
        EvaluationWindow(
            backtest_start=date(2024, 1, 1),
            backtest_end=date(2023, 1, 1),
        )
