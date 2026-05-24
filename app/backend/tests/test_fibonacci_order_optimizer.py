from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fibonacci_order_optimizer import (  # noqa: E402
    FIBONACCI_LEVEL_RATIOS,
    fibonacci_retracement_levels,
    optimize_fib_orders,
    optimize_fib_orders_from_swing,
)


def _rows_by_index(result: dict[str, object]) -> dict[int, dict[str, object]]:
    return {
        int(row["original_index"]): row
        for row in result["levels"]  # type: ignore[index]
    }


def test_zero_risk_budget_returns_zero_allocation() -> None:
    result = optimize_fib_orders(
        entry_prices=[95.0, 90.0],
        stop_loss=80.0,
        take_profits=[104.0, 100.0],
        risk_budget=0.0,
        per_level_caps=[10.0, 10.0],
    )
    assert result["status"] == "optimal_zero"
    assert result["total_profit"] == pytest.approx(0.0)
    assert result["total_risk"] == pytest.approx(0.0)
    assert all(row["quantity"] == pytest.approx(0.0) for row in result["levels"])  # type: ignore[index]


def test_invalid_levels_are_filtered_and_valid_level_is_kept() -> None:
    result = optimize_fib_orders(
        entry_prices=[95.0, 80.0, 70.0, -5.0],
        stop_loss=80.0,
        take_profits=[100.0, 90.0, 90.0, 10.0],
        risk_budget=100.0,
        per_level_caps=[10.0, 10.0, 10.0, 10.0],
        solver="python",
    )
    assert result["active_level_count"] == 1
    assert result["selected_level_count"] == 1
    assert result["total_risk"] == pytest.approx(100.0)
    assert result["total_profit"] == pytest.approx((100.0 / 15.0) * 5.0)
    assert [item["reason"] for item in result["filtered_levels"]] == [  # type: ignore[index]
        "entry_not_above_stop_loss",
        "entry_not_above_stop_loss",
        "non_positive_entry_price",
    ]


def test_single_constraint_solution_matches_profit_per_risk_order() -> None:
    result = optimize_fib_orders(
        entry_prices=[95.0, 90.0],
        stop_loss=80.0,
        take_profits=[104.0, 100.0],
        risk_budget=150.0,
        per_level_caps=[10.0, 10.0],
        solver="python",
    )
    rows = _rows_by_index(result)
    assert rows[1]["quantity"] == pytest.approx(10.0)
    assert rows[0]["quantity"] == pytest.approx(50.0 / 15.0)
    assert result["total_risk"] == pytest.approx(150.0)
    assert result["total_profit"] == pytest.approx((10.0 * 10.0) + ((50.0 / 15.0) * 9.0))


def test_two_constraint_python_solver_matches_manual_corner_solution() -> None:
    result = optimize_fib_orders(
        entry_prices=[60.0, 100.0],
        stop_loss=50.0,
        take_profits=[65.0, 120.0],
        risk_budget=100.0,
        per_level_caps=[10.0, 10.0],
        capital_budget=400.0,
        solver="python",
    )
    rows = _rows_by_index(result)
    assert result["solver"] == "python-enumeration"
    assert rows[0]["quantity"] == pytest.approx(5.0)
    assert rows[1]["quantity"] == pytest.approx(1.0)
    assert result["total_risk"] == pytest.approx(100.0)
    assert result["total_cost"] == pytest.approx(400.0)
    assert result["total_profit"] == pytest.approx(45.0)


def test_optimize_from_swing_uses_fibonacci_ratios() -> None:
    ratios = FIBONACCI_LEVEL_RATIOS[:3]
    result = optimize_fib_orders_from_swing(
        high=100.0,
        low=80.0,
        stop_loss=78.0,
        take_profits=105.0,
        risk_budget=30.0,
        per_level_caps=2.0,
        capital_budget=180.0,
        ratios=ratios,
        solver="python",
    )
    expected_entries = fibonacci_retracement_levels(100.0, 80.0, ratios)
    rows = result["levels"]  # type: ignore[index]
    assert [row["entry_price"] for row in rows] == pytest.approx(expected_entries)
    assert [row["fib_ratio"] for row in rows] == pytest.approx(list(ratios))
