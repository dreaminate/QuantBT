from __future__ import annotations

import csv
import json
import os
import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = Path(os.getenv("QUANT1_DEMO_SOURCE_RUN", r"D:\1Codeprojects\quant1\data\artifacts\experiments\2a1846f4dd2841acb353d60ee8a9fc11"))
TARGET_RUN = PROJECT_ROOT / "data" / "artifacts" / "experiments" / "quant1-demo"

TRADE_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - \w+ - order UserOrder\(\{.*?'price': (?P<price>[-\d.eE]+), .*?'action': '(?P<action>[^']+)', 'security': '(?P<security>[^']+)', 'side': '(?P<side>[^']+)'.*?\}\) trade price: (?P<trade_price>[-\d.eE]+), amount: (?P<filled>[-\d.eE]+), commission: (?P<commission>[-\d.eE]+)"
)


def normalize_symbol(symbol: str, market: str) -> str:
    text = str(symbol).upper()
    if market == "binanceusdm" and text == "BTC":
        return "BTCUSDT"
    return text


def iso_utc(ts: str) -> str:
    return ts.replace(" ", "T") + "+00:00"


def drawdown_series(values: list[float]) -> list[float]:
    peak = values[0] if values else 1.0
    rows: list[float] = []
    for value in values:
        peak = max(peak, value)
        rows.append((value / peak) - 1.0 if peak else 0.0)
    return rows


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not SOURCE_RUN.exists():
        raise FileNotFoundError(
            "quant1 demo source run not found. Set QUANT1_DEMO_SOURCE_RUN to regenerate this demo from another checkout."
        )

    metrics_payload = json.loads((SOURCE_RUN / "metrics.json").read_text(encoding="utf-8"))
    equity_payload = json.loads((SOURCE_RUN / "equity_curve.json").read_text(encoding="utf-8"))
    rolling_payload = json.loads((SOURCE_RUN / "rolling_series.json").read_text(encoding="utf-8"))
    daily_payload = json.loads((SOURCE_RUN / "daily_portfolios.json").read_text(encoding="utf-8"))

    if TARGET_RUN.exists():
        shutil.rmtree(TARGET_RUN)
    TARGET_RUN.mkdir(parents=True, exist_ok=True)

    simulation = metrics_payload.get("simulation") or {}
    overall = metrics_payload.get("overall") or {}
    in_sample = metrics_payload.get("in_sample") or {}
    out_of_sample = metrics_payload.get("out_of_sample") or {}
    cost_breakdown = metrics_payload.get("cost_breakdown") or {}
    market = str(simulation.get("market") or "binanceusdm")
    frequency = str(simulation.get("frequency") or "1d")
    benchmark = str(simulation.get("benchmark") or "BTCUSDT")

    manifest = {
        "run_id": "quant1-demo",
        "strategy_id": Path(str(metrics_payload.get("strategy_script_name") or "quant1_demo")).stem,
        "strategy_name": "Quant1 Demo: Kronos Crypto",
        "started_at": equity_payload["timestamps"][0],
        "status": "completed",
        "record_name": "Quant1 演示样例",
        "market": market,
        "frequency": frequency,
        "benchmark": benchmark,
        "strategy_mode": metrics_payload.get("strategy_mode"),
        "strategy_ref": metrics_payload.get("strategy_script_name"),
        "analysis_start": simulation.get("analysis_start") or metrics_payload.get("analysis_window", {}).get("start"),
        "analysis_end": simulation.get("analysis_end") or metrics_payload.get("analysis_window", {}).get("end"),
        "execution_profile": simulation.get("execution_profile"),
        "execution_model": metrics_payload.get("execution_model"),
        "instrument_type": simulation.get("instrument_type"),
        "model_used": True,
        "metrics": {
            "total_return": overall.get("total_return"),
            "annualized_return": overall.get("annualized_return"),
            "max_drawdown": -abs(float(overall.get("max_drawdown", 0.0))),
            "sharpe": overall.get("sharpe"),
            "sortino": overall.get("sortino"),
            "alpha": overall.get("alpha"),
            "beta": overall.get("beta"),
            "trade_count": overall.get("trade_count"),
            "win_rate": overall.get("win_rate"),
            "trade_win_rate": overall.get("trade_win_rate"),
            "volatility": overall.get("volatility"),
            "benchmark_volatility": overall.get("benchmark_volatility"),
            "information_ratio": overall.get("information_ratio"),
            "profit_loss_ratio": overall.get("profit_loss_ratio"),
            "avg_daily_return": overall.get("avg_daily_return"),
            "daily_win_rate": overall.get("daily_win_rate"),
            "benchmark_return": overall.get("benchmark_return"),
            "funding_return": cost_breakdown.get("funding_return"),
            "fee_cost": cost_breakdown.get("fee_cost"),
            "net_return": cost_breakdown.get("net_return"),
        },
        "overall": overall,
        "in_sample": in_sample,
        "out_of_sample": out_of_sample,
        "cost_breakdown": cost_breakdown,
        "data_coverage_summary": {
            "source_run": str(SOURCE_RUN),
            "conversion_note": "Converted from quant1 metrics.json / equity_curve.json / rolling_series.json / daily_portfolios.json / backtest.log",
            "trades_positions_status": "best_effort_converted",
        },
        "component_runs": [],
        "produced_outputs": [],
        "data_dependencies": [],
    }
    (TARGET_RUN / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    equity_values = [float(value) for value in equity_payload["equity"]]
    benchmark_values = [float(value) for value in equity_payload["benchmark"]]
    timestamps = list(equity_payload["timestamps"])
    first_benchmark = benchmark_values[0] if benchmark_values else 1.0
    drawdowns = drawdown_series(equity_values)

    daily_index = {str(item["timestamp"]): item for item in daily_payload}
    portfolio_rows: list[dict[str, object]] = []
    for idx, timestamp in enumerate(timestamps):
        daily_row = daily_index.get(timestamp, {})
        portfolio_rows.append(
            {
                "timestamp": timestamp,
                "equity": equity_values[idx],
                "net_return": safe_float(rolling_payload["strategy_return"][idx]),
                "benchmark_return": ((benchmark_values[idx] / first_benchmark) - 1.0) if first_benchmark else 0.0,
                "turnover": float(overall.get("avg_turnover", 0.0)),
                "drawdown": drawdowns[idx],
                "alpha": safe_float(rolling_payload["alpha"][idx]),
                "beta": safe_float(rolling_payload["beta"][idx]),
                "sharpe": safe_float(rolling_payload["sharpe"][idx]),
                "sortino": safe_float(rolling_payload["sortino"][idx]),
                "information_ratio": safe_float(rolling_payload["information_ratio"][idx]),
                "volatility": safe_float(rolling_payload["volatility"][idx]),
                "benchmark_volatility": safe_float(rolling_payload["benchmark_volatility"][idx]),
                "max_drawdown": -abs(safe_float(rolling_payload["max_drawdown"][idx])),
                "funding_return": float(daily_row.get("funding_return", 0.0) or 0.0),
                "fee_cost": float(daily_row.get("fee_cost", 0.0) or 0.0),
            }
        )
    write_csv(
        TARGET_RUN / "portfolio.csv",
        [
            "timestamp",
            "equity",
            "net_return",
            "benchmark_return",
            "turnover",
            "drawdown",
            "alpha",
            "beta",
            "sharpe",
            "sortino",
            "information_ratio",
            "volatility",
            "benchmark_volatility",
            "max_drawdown",
            "funding_return",
            "fee_cost",
        ],
        portfolio_rows,
    )

    avg_cost_by_ts: dict[str, float] = {}
    positions_rows: list[dict[str, object]] = []
    for item in daily_payload:
        timestamp = str(item["timestamp"])
        total_value = float(item.get("total_value", 0.0) or 0.0)
        funding_return = float(item.get("funding_return", 0.0) or 0.0)
        positions = item.get("positions") or {}
        for raw_symbol, payload in positions.items():
            symbol = normalize_symbol(raw_symbol, market)
            avg_cost = float(payload.get("avg_cost", 0.0) or 0.0)
            avg_cost_by_ts[timestamp] = avg_cost
            market_value = float(payload.get("value", 0.0) or 0.0)
            positions_rows.append(
                {
                    "execution_timestamp": timestamp,
                    "symbol": symbol,
                    "row_kind": "holding",
                    "quantity": float(payload.get("amount", 0.0) or 0.0),
                    "close_price": float(payload.get("price", 0.0) or 0.0),
                    "market_value": market_value,
                    "pnl": float(payload.get("pnl", 0.0) or 0.0),
                    "side": payload.get("side", "long"),
                    "weight": (market_value / total_value) if total_value else 0.0,
                    "selected_period_return": ((float(payload.get("price", 0.0) or 0.0) / avg_cost) - 1.0) if avg_cost else 0.0,
                    "gross_contribution": (float(payload.get("pnl", 0.0) or 0.0) / total_value) if total_value else 0.0,
                    "funding_contribution": (funding_return / total_value) if total_value else 0.0,
                }
            )
        available_cash = float(item.get("available_cash", 0.0) or 0.0)
        if available_cash:
            positions_rows.append(
                {
                    "execution_timestamp": timestamp,
                    "symbol": "CASH",
                    "row_kind": "cash",
                    "quantity": 1.0,
                    "close_price": available_cash,
                    "market_value": available_cash,
                    "pnl": 0.0,
                    "side": "long",
                    "weight": (available_cash / total_value) if total_value else 0.0,
                    "selected_period_return": 0.0,
                    "gross_contribution": 0.0,
                    "funding_contribution": 0.0,
                }
            )
    write_csv(
        TARGET_RUN / "positions.csv",
        [
            "execution_timestamp",
            "symbol",
            "row_kind",
            "quantity",
            "close_price",
            "market_value",
            "pnl",
            "side",
            "weight",
            "selected_period_return",
            "gross_contribution",
            "funding_contribution",
        ],
        positions_rows,
    )

    trade_rows: list[dict[str, object]] = []
    for line in (SOURCE_RUN / "backtest.log").read_text(encoding="utf-8").splitlines():
        match = TRADE_PATTERN.match(line)
        if not match:
            continue
        timestamp = iso_utc(match.group("ts"))
        price = float(match.group("trade_price"))
        quantity = float(match.group("filled"))
        commission = float(match.group("commission"))
        action = match.group("action")
        symbol = normalize_symbol(match.group("security"), market)
        avg_cost = avg_cost_by_ts.get(timestamp, float(match.group("price")))
        turnover = price * quantity
        trade_rows.append(
            {
                "execution_timestamp": timestamp,
                "symbol": symbol,
                "trade_side": "buy" if action == "open" else "sell",
                "quantity": quantity,
                "price": price,
                "turnover": turnover,
                "realized_pnl": 0.0 if action == "open" else (price - avg_cost) * quantity,
                "estimated_fee": commission,
                "delta_weight": (turnover / daily_index.get(timestamp, {}).get("total_value", 1.0)) if daily_index.get(timestamp, {}).get("total_value") else 0.0,
                "execution_model": metrics_payload.get("execution_model"),
                "fee_rate": (commission / turnover) if turnover else 0.0,
                "estimated_slippage": 0.0,
            }
        )
    write_csv(
        TARGET_RUN / "trades.csv",
        [
            "execution_timestamp",
            "symbol",
            "trade_side",
            "quantity",
            "price",
            "turnover",
            "realized_pnl",
            "estimated_fee",
            "delta_weight",
            "execution_model",
            "fee_rate",
            "estimated_slippage",
        ],
        trade_rows,
    )

    shutil.copy2(SOURCE_RUN / "strategy.py", TARGET_RUN / "strategy.py")
    shutil.copy2(SOURCE_RUN / "report.md", TARGET_RUN / "report.md")
    shutil.copy2(SOURCE_RUN / "backtest.log", TARGET_RUN / "backtest.log")

    print(f"converted quant1 demo -> {TARGET_RUN}")


if __name__ == "__main__":
    main()
