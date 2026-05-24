from __future__ import annotations

from itertools import combinations
from math import isfinite
from typing import Iterable, Sequence


FIBONACCI_LEVEL_RATIOS: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)
_TOLERANCE = 1e-9


def fibonacci_retracement_levels(
    high: float,
    low: float,
    ratios: Sequence[float] = FIBONACCI_LEVEL_RATIOS,
) -> list[float]:
    """Return retracement entry prices measured down from ``high``."""
    high_value = _finite_float(high, "high")
    low_value = _finite_float(low, "low")
    span = high_value - low_value
    return [high_value - span * _finite_float(ratio, "ratio") for ratio in ratios]


def risk_reward_ratio(entry_price: float, stop_loss: float, take_profit: float) -> float:
    """Return profit per unit of downside risk for one order level."""
    entry = _finite_float(entry_price, "entry_price")
    stop = _finite_float(stop_loss, "stop_loss")
    target = _finite_float(take_profit, "take_profit")
    risk = entry - stop
    if risk <= 0:
        raise ValueError("entry_price must be above stop_loss")
    return (target - entry) / risk


def optimize_fib_orders(
    *,
    entry_prices: Sequence[float],
    stop_loss: float,
    take_profits: float | Sequence[float],
    risk_budget: float,
    per_level_caps: float | Sequence[float],
    capital_budget: float | None = None,
    solver: str = "python",
) -> dict[str, object]:
    """Maximize expected take-profit dollars subject to risk/capital budgets."""
    entries = [_finite_float(value, "entry_price") for value in entry_prices]
    stop = _finite_float(stop_loss, "stop_loss")
    budget = max(0.0, _finite_float(risk_budget, "risk_budget"))
    targets = _expand_float_list(take_profits, len(entries), "take_profits")
    caps = _expand_float_list(per_level_caps, len(entries), "per_level_caps")
    capital = None if capital_budget is None else max(0.0, _finite_float(capital_budget, "capital_budget"))

    active_levels: list[dict[str, object]] = []
    filtered_levels: list[dict[str, object]] = []

    for index, (entry, target, cap) in enumerate(zip(entries, targets, caps, strict=True)):
        reason = _filter_reason(entry, stop, target, cap)
        row = {
            "original_index": index,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
            "max_quantity": max(0.0, cap),
        }
        if reason is not None:
            filtered_levels.append({**row, "reason": reason})
            continue

        risk_per_unit = entry - stop
        profit_per_unit = target - entry
        active_levels.append(
            {
                **row,
                "risk_per_unit": risk_per_unit,
                "profit_per_unit": profit_per_unit,
                "risk_reward_ratio": profit_per_unit / risk_per_unit,
                "quantity": 0.0,
            }
        )

    if not active_levels:
        return _result("infeasible", solver, active_levels, filtered_levels)

    if budget <= _TOLERANCE or (capital is not None and capital <= _TOLERANCE):
        return _result("optimal_zero", solver, active_levels, filtered_levels)

    quantities = _solve_allocation(
        risks=[float(row["risk_per_unit"]) for row in active_levels],
        costs=[float(row["entry_price"]) for row in active_levels],
        profits=[float(row["profit_per_unit"]) for row in active_levels],
        caps=[float(row["max_quantity"]) for row in active_levels],
        risk_budget=budget,
        capital_budget=capital,
    )

    for row, quantity in zip(active_levels, quantities, strict=True):
        row["quantity"] = quantity

    return _result("optimal", solver, active_levels, filtered_levels)


def optimize_fib_orders_from_swing(
    *,
    high: float,
    low: float,
    stop_loss: float,
    take_profits: float | Sequence[float],
    risk_budget: float,
    per_level_caps: float | Sequence[float],
    capital_budget: float | None = None,
    ratios: Sequence[float] = FIBONACCI_LEVEL_RATIOS,
    solver: str = "python",
) -> dict[str, object]:
    """Build Fibonacci entries from a swing high/low, then optimize sizing."""
    ratio_values = [_finite_float(ratio, "ratio") for ratio in ratios]
    entries = fibonacci_retracement_levels(high, low, ratio_values)
    result = optimize_fib_orders(
        entry_prices=entries,
        stop_loss=stop_loss,
        take_profits=take_profits,
        risk_budget=risk_budget,
        per_level_caps=per_level_caps,
        capital_budget=capital_budget,
        solver=solver,
    )
    for key in ("levels", "filtered_levels"):
        for row in result[key]:  # type: ignore[index]
            index = int(row["original_index"])
            row["fib_ratio"] = ratio_values[index]
    return result


def _filter_reason(entry: float, stop: float, target: float, cap: float) -> str | None:
    if entry <= 0:
        return "non_positive_entry_price"
    if cap <= 0:
        return "non_positive_cap"
    if entry <= stop:
        return "entry_not_above_stop_loss"
    if target <= entry:
        return "take_profit_not_above_entry_price"
    return None


def _solve_allocation(
    *,
    risks: Sequence[float],
    costs: Sequence[float],
    profits: Sequence[float],
    caps: Sequence[float],
    risk_budget: float,
    capital_budget: float | None,
) -> list[float]:
    variable_count = len(risks)
    constraints: list[tuple[list[float], float]] = [(list(risks), risk_budget)]
    if capital_budget is not None:
        constraints.append((list(costs), capital_budget))

    for index, cap in enumerate(caps):
        upper = [0.0] * variable_count
        upper[index] = 1.0
        constraints.append((upper, cap))

        lower = [0.0] * variable_count
        lower[index] = -1.0
        constraints.append((lower, 0.0))

    candidates = [[0.0] * variable_count]
    for active in combinations(constraints, variable_count):
        matrix = [row[:] for row, _ in active]
        vector = [bound for _, bound in active]
        point = _solve_square(matrix, vector)
        if point is not None:
            candidates.append(point)

    best = [0.0] * variable_count
    best_profit = float("-inf")
    for point in candidates:
        normalized = [_clean_quantity(value, cap) for value, cap in zip(point, caps, strict=True)]
        if not _is_feasible(normalized, constraints):
            continue
        objective = sum(quantity * profit for quantity, profit in zip(normalized, profits, strict=True))
        if objective > best_profit + _TOLERANCE:
            best = normalized
            best_profit = objective
    return best


def _solve_square(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [rhs] for row, rhs in zip(matrix, vector, strict=True)]

    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= _TOLERANCE:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]

        pivot_value = augmented[column][column]
        for item in range(column, size + 1):
            augmented[column][item] /= pivot_value

        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) <= _TOLERANCE:
                continue
            for item in range(column, size + 1):
                augmented[row][item] -= factor * augmented[column][item]

    return [augmented[row][size] for row in range(size)]


def _is_feasible(point: Sequence[float], constraints: Sequence[tuple[Sequence[float], float]]) -> bool:
    for coeffs, bound in constraints:
        lhs = sum(coef * value for coef, value in zip(coeffs, point, strict=True))
        if lhs > bound + 1e-7:
            return False
    return True


def _clean_quantity(value: float, cap: float) -> float:
    if abs(value) <= _TOLERANCE:
        return 0.0
    if abs(value - cap) <= _TOLERANCE:
        return cap
    return value


def _result(
    status: str,
    requested_solver: str,
    levels: list[dict[str, object]],
    filtered_levels: list[dict[str, object]],
) -> dict[str, object]:
    total_risk = sum(float(row["quantity"]) * float(row["risk_per_unit"]) for row in levels)
    total_cost = sum(float(row["quantity"]) * float(row["entry_price"]) for row in levels)
    total_profit = sum(float(row["quantity"]) * float(row["profit_per_unit"]) for row in levels)
    return {
        "status": status,
        "solver": "python-enumeration" if requested_solver in {"python", "auto"} else requested_solver,
        "active_level_count": len(levels),
        "selected_level_count": sum(1 for row in levels if float(row["quantity"]) > _TOLERANCE),
        "levels": levels,
        "filtered_levels": filtered_levels,
        "total_risk": total_risk,
        "total_cost": total_cost,
        "total_profit": total_profit,
    }


def _expand_float_list(value: float | Sequence[float], length: int, name: str) -> list[float]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be numeric, not text")
    if isinstance(value, Iterable):
        out = [_finite_float(item, name) for item in value]
        if len(out) != length:
            raise ValueError(f"{name} length must match entry_prices length")
        return out
    return [_finite_float(value, name)] * length


def _finite_float(value: float, name: str) -> float:
    out = float(value)
    if not isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


__all__ = [
    "FIBONACCI_LEVEL_RATIOS",
    "fibonacci_retracement_levels",
    "optimize_fib_orders",
    "optimize_fib_orders_from_swing",
    "risk_reward_ratio",
]
