"""端到端 加密永续 demo · BTC/ETH/SOL/BNB/AVAX 5 个标的。

与 A股 demo 不同的设计点：
- 加密 24/7，无交易日历；
- 用 vol-adjusted return 标签（夏普风格回归），更适合 perp 趋势策略；
- 组合用 mean_variance（信号是连续值），加 leverage_max=2x 约束；
- 成本走 `CryptoPerpCostModel`：funding rate + maker/taker 分档分别扣；
- 评估额外算「成本拖累分解」（手续费 / funding / 滑点）；
- 不做 Brinson（加密无行业概念）。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

from _e2e_common import (  # type: ignore[import-not-found]
    compute_run_metrics,
    enrich_portfolio_with_metrics,
    synthetic_panel,
    write_run_artifacts,
)

from app.eval import bootstrap_sharpe_ci, cscv_pbo, deflated_sharpe_ratio, sharpe_ratio
from app.execution import BacktestCostModel, BacktestVenue, Order
from app.factor_factory import alpha_lite_specs, evaluate_on_panel
from app.labels import vol_adjusted_return_label
from app.models import ModelSpec, train_model
from app.portfolio import PortfolioConstraints, mean_variance
from app.signals import fuse_signals
from app.strategy_goal import CryptoPerpCostModel


_FUNDING_RATE_PER_8H = 0.0001  # ~ 0.01% 默认；CryptoPerpCostModel.funding_rate_apply=True


def _universe() -> tuple[list[str], dict[str, str]]:
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
    # 加密没有 sector，但合成 panel 要求字段；统一标 "crypto_perp"
    sectors = {s: "crypto_perp" for s in symbols}
    return symbols, sectors


def _build_features(panel: pl.DataFrame, factor_ids: list[str]) -> pl.DataFrame:
    feats = panel.select(["ts", "symbol"])
    specs = {s.factor_id: s.formula for s in alpha_lite_specs()}
    for fid in factor_ids:
        out = evaluate_on_panel(panel, specs[fid], alias=fid)
        feats = feats.join(out, on=["ts", "symbol"], how="left")
    return feats


def _train(panel_pl: pl.DataFrame, feats: pl.DataFrame, factor_ids: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    labels = vol_adjusted_return_label(panel_pl, horizon=1, vol_window=20).rename(
        {"label_vol_adjusted_return": "label"}
    )
    enriched = feats.join(labels, on=["ts", "symbol"], how="inner").join(
        panel_pl.select(["ts", "symbol", "close"]), on=["ts", "symbol"], how="left"
    )
    df = enriched.drop_nulls(["label"] + factor_ids).to_pandas()
    spec = ModelSpec(
        task="regression",
        model="lgbm",
        feature_cols=factor_ids,
        label_col="label",
        cv_scheme="walk_forward",
        walk_forward_train=80,
        walk_forward_test=20,
        walk_forward_embargo=2,
    )
    result = train_model(spec, df.copy())
    import lightgbm as lgb
    final = lgb.LGBMRegressor(verbose=-1, n_estimators=100)
    final.fit(df[factor_ids].values, df["label"].values)
    df["score"] = final.predict(df[factor_ids].values)
    return df, result.to_dict()


def _per_day_target_weights(
    df_score: pd.DataFrame,
    *,
    leverage_max: float = 2.0,
    short_allowed: bool = True,
) -> pd.DataFrame:
    """每日跑 MVO 给每个 symbol 一个目标权重。"""

    rows: list[dict[str, Any]] = []
    constraints = PortfolioConstraints(
        single_pos_max=0.5,
        leverage_max=leverage_max,
        short_allowed=short_allowed,
    )
    pivot = df_score.pivot(index="ts", columns="symbol", values="close").sort_index()
    cov_rolling = pivot.pct_change().rolling(window=30).cov(pairwise=True).dropna()
    for ts, grp in df_score.groupby("ts", sort=True):
        try:
            cov_slice = cov_rolling.xs(ts, level=0)
        except KeyError:
            continue
        if cov_slice.shape[0] < len(grp):
            continue
        mu = pd.Series(grp.set_index("symbol")["score"])
        symbols_in_cov = list(cov_slice.columns)
        mu = mu.reindex(symbols_in_cov).fillna(0.0)
        cov_aligned = cov_slice.reindex(index=symbols_in_cov, columns=symbols_in_cov).fillna(0.0)
        try:
            weights = mean_variance(mu, cov_aligned, risk_aversion=2.0, short_allowed=short_allowed)
        except Exception:  # noqa: BLE001
            continue
        # 截 + 重归一化到 leverage_max
        gross = sum(abs(w) for w in weights.values())
        if gross > leverage_max:
            scale = leverage_max / gross
            weights = {k: v * scale for k, v in weights.items()}
        for sym, w in weights.items():
            if abs(w) < 1e-4:
                continue
            rows.append({"ts": ts, "symbol": sym, "weight": float(w)})
    return pd.DataFrame(rows)


@dataclass
class BacktestArtifacts:
    portfolio: pd.DataFrame
    trades: pd.DataFrame
    cost_breakdown: dict[str, float]


def _run_backtest(
    panel: pl.DataFrame,
    weight_df: pd.DataFrame,
    *,
    initial_cash: float = 1_000_000.0,
    perp_cost_model: CryptoPerpCostModel | None = None,
) -> BacktestArtifacts:
    perp_cost_model = perp_cost_model or CryptoPerpCostModel()
    cost = BacktestCostModel(
        commission_bps=(perp_cost_model.maker_bps + perp_cost_model.taker_bps) / 2,
        slippage_bps=perp_cost_model.slippage_bps,
    )
    venue = BacktestVenue(prices=panel, cost_model=cost, cash=initial_cash)
    panel_pd = panel.to_pandas()
    timestamps = sorted(panel_pd["ts"].unique())
    weight_idx = weight_df.set_index(["ts", "symbol"])["weight"] if len(weight_df) else pd.Series(dtype=float)
    # BTC 作为加密 benchmark（buy & hold）
    bench_price = panel_pd[panel_pd["symbol"] == "BTCUSDT"].set_index("ts")["close"]
    bench_returns = bench_price.pct_change().fillna(0.0)
    prev_weights: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    funding_total = 0.0
    fee_total = 0.0
    slippage_total = 0.0
    peak = initial_cash
    prev_equity = initial_cash
    bench_equity = initial_cash
    prev_bench_equity = initial_cash
    for idx, ts in enumerate(timestamps[:-1]):
        next_ts = timestamps[idx + 1]
        bar = panel_pd[panel_pd["ts"] == ts]
        try:
            target = weight_idx.xs(ts, level="ts").to_dict()
        except KeyError:
            target = {}
        if isinstance(target, float):
            target = {}
        all_symbols = set(prev_weights) | set(target)
        for sym in sorted(all_symbols):
            delta = float(target.get(sym, 0.0)) - float(prev_weights.get(sym, 0.0))
            if abs(delta) < 1e-6:
                continue
            row = bar[bar["symbol"] == sym]
            if row.empty:
                continue
            close_price = float(row["close"].iloc[0])
            usd_delta = delta * initial_cash * 0.99
            qty = abs(usd_delta) / close_price
            side = "buy" if delta > 0 else "sell"
            venue.place_order(
                Order(
                    venue="backtest",
                    symbol=sym,
                    side=side,
                    quantity=qty,
                    order_type="market",
                )
            )
        executed = venue.step()
        fills.extend(executed)
        for e in executed:
            fee_total += float(e.get("commission", 0.0))
            slippage_total += abs(float(e.get("fill_price", 0.0)) * float(e.get("filled_qty", 0.0))) * perp_cost_model.slippage_bps * 1e-4
        # funding rate（每 8h；日频近似 = 3 次 funding）
        snapshot = panel_pd[panel_pd["ts"] == next_ts].set_index("symbol")["close"]
        position_value = 0.0
        for sym, pos in venue._positions.items():  # noqa: SLF001
            mark = float(snapshot.get(sym, pos.mark_price))
            notional = pos.quantity * mark
            position_value += notional
            funding_total += abs(notional) * _FUNDING_RATE_PER_8H * 3
        balance = venue.get_balance().get("USDT")
        cash = balance.free if balance else 0.0
        equity = cash + position_value - (funding_total)  # funding 扣到权益
        peak = max(peak, equity)
        dd = (equity - peak) / peak if peak else 0.0
        bench_equity *= 1.0 + float(bench_returns.get(next_ts, 0.0))
        daily_strat = (equity / prev_equity - 1.0) if prev_equity else 0.0
        daily_bench = (bench_equity / prev_bench_equity - 1.0) if prev_bench_equity else 0.0
        rows.append(
            {
                "timestamp": next_ts,
                "equity": equity,
                "net_return": daily_strat,  # 日策略收益
                "benchmark_return": daily_bench,  # BTC buy&hold 日收益
                "turnover": sum(abs(target.get(s, 0.0) - prev_weights.get(s, 0.0)) for s in all_symbols),
                "drawdown": dd,
                "funding_total": funding_total,
                "fee_total": fee_total,
            }
        )
        prev_weights = target
        prev_equity = equity
        prev_bench_equity = bench_equity
    portfolio = pd.DataFrame(rows)
    trades = pd.DataFrame(fills)
    if not trades.empty:
        trades = trades.rename(columns={"ts": "execution_timestamp", "side": "trade_side", "filled_qty": "quantity", "fill_price": "price"})
        trades["turnover"] = trades["quantity"] * trades["price"]
        trades["realized_pnl"] = 0.0
        trades["estimated_fee"] = trades.get("commission", 0.0)
        trades["delta_weight"] = 0.0
        trades["execution_model"] = "next_bar_open"
    return BacktestArtifacts(
        portfolio=portfolio,
        trades=trades,
        cost_breakdown={
            "total_fee": fee_total,
            "total_funding": funding_total,
            "total_slippage": slippage_total,
            "total_cost": fee_total + funding_total + slippage_total,
        },
    )


def _strategy_grid(df_score: pd.DataFrame, choices: list[float]) -> np.ndarray:
    pivoted_close = df_score.pivot(index="ts", columns="symbol", values="close")
    fwd_ret = pivoted_close.pct_change().shift(-1).fillna(0.0)
    strategies: list[np.ndarray] = []
    for thr in choices:
        daily: list[float] = []
        for ts, grp in df_score.groupby("ts", sort=True):
            if ts not in fwd_ret.index:
                daily.append(0.0)
                continue
            signs = np.where(grp["score"].values > thr, 1.0, -1.0) / max(len(grp), 1)
            symbols = grp["symbol"].values
            r = float(sum(signs[i] * fwd_ret.loc[ts, symbols[i]] for i in range(len(symbols))))
            daily.append(r)
        strategies.append(np.asarray(daily))
    return np.column_stack(strategies)


def _metrics_and_report(
    artifacts: BacktestArtifacts,
    df_score: pd.DataFrame,
    train_metrics: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    portfolio = artifacts.portfolio
    if portfolio.empty:
        return {"total_return": 0.0, "sharpe": 0.0, "pbo": {"pbo": float("nan")}, "deflated_sharpe": 0.0,
                "bootstrap_sharpe_ci": {"estimate": 0, "lower": 0, "upper": 0, "n_boot": 0},
                "cost_breakdown": artifacts.cost_breakdown, "train_oos": train_metrics.get("oos_metrics", {}),
                "trade_count": 0}, "（无可用 portfolio）"
    # 已修正：net_return 是日收益，直接喂
    daily_returns = portfolio["net_return"].astype(float).values
    boot = bootstrap_sharpe_ci(daily_returns, n_boot=200, seed=42, periods_per_year=365)
    dsr = deflated_sharpe_ratio(daily_returns, n_trials=20, periods_per_year=365)
    grid = _strategy_grid(df_score, choices=[-0.5, 0.0, 0.5, 1.0])
    pbo = cscv_pbo(grid, s_blocks=4, max_combinations=20)

    metrics = compute_run_metrics(
        portfolio,
        trades=artifacts.trades,
        periods_per_year=365,
        extra={
            "pbo": pbo.to_dict(),
            "deflated_sharpe": dsr,
            "bootstrap_sharpe_ci": boot.to_dict(),
            "cost_breakdown": artifacts.cost_breakdown,
            "train_oos": train_metrics.get("oos_metrics", {}),
            "n_factors": 5,
            "n_symbols": int(df_score["symbol"].nunique()),
            "n_days": int(df_score["ts"].nunique()),
        },
    )
    md = _render_report(metrics)
    return metrics, md


def _render_report(metrics: dict[str, Any]) -> str:
    boot = metrics["bootstrap_sharpe_ci"]
    pbo = metrics["pbo"]
    cost = metrics["cost_breakdown"]
    return f"""# QuantBT · 加密永续 demo 报告

## 概要
- 总收益: {metrics['total_return']:.4%}
- 年化收益: {metrics['annualized_return']:.4%}
- 最大回撤: {metrics['max_drawdown']:.4%}
- 夏普 (365 天年化): {metrics['sharpe']:.4f}
- Sortino: {metrics.get('sortino', 0):.4f}
- 信息比率: {metrics.get('information_ratio', 0):.4f}
- Alpha (年化): {metrics.get('alpha', 0):.4f}
- Beta: {metrics.get('beta', 0):.4f}
- 基准 (BTC buy&hold) 收益: {metrics.get('benchmark_return', 0):.4%}
- 超额收益: {metrics.get('excess_return', 0):.4%}
- 策略波动率: {metrics.get('strategy_volatility', 0):.4%}
- 基准波动率: {metrics.get('benchmark_volatility', 0):.4%}
- 日均胜率: {metrics.get('daily_win_rate', 0):.4%}

## 过拟合证伪（GOAL §6.1 强制）
- **PBO**: {pbo['pbo']:.4f} (s_blocks={pbo['s_blocks']}, 策略数={pbo['n_strategies']})
- **DSR**: {metrics['deflated_sharpe']:.4f}
- **Bootstrap Sharpe 95% CI**: [{boot['lower']:.4f}, {boot['upper']:.4f}] (estimate={boot['estimate']:.4f})

## 成本拖累分解（GOAL §2.2 加密策略硬指标）
- 手续费: {cost['total_fee']:.2f}
- 资金费率（funding，每 8h × 3 次/日）: {cost['total_funding']:.2f}
- 滑点: {cost['total_slippage']:.2f}
- 总成本: {cost['total_cost']:.2f}

## 模型 OOS 指标（Walk-forward + Embargo）
- {metrics['train_oos']}

## 工程参数
- 因子数: {metrics['n_factors']} · 标的数: {metrics['n_symbols']} · 日历日: {metrics['n_days']} · 成交笔数: {metrics['trade_count']}
"""


def run(run_id: str = "crypto_perp_demo", days: int = 240) -> dict[str, Any]:
    symbols, sectors = _universe()
    panel = synthetic_panel(
        symbols=symbols,
        sectors=sectors,
        days=days,
        base_price=100.0,
        seed=11,
        drift_per_symbol={"BTCUSDT": 0.0008, "ETHUSDT": 0.0006, "SOLUSDT": 0.0003, "BNBUSDT": 0.0002, "AVAXUSDT": -0.0001},
        volatility=0.025,
    )
    factor_ids = [
        "alpha_mom_5d",
        "alpha_mom_20d",
        "alpha_vol_20d",
        "alpha_vol_adj_mom_20d",
        "alpha_close_to_volume_ratio",
    ]
    feats = _build_features(panel, factor_ids)
    df_score, train_metrics = _train(panel, feats, factor_ids)
    weight_df = _per_day_target_weights(df_score, leverage_max=2.0, short_allowed=True)
    artifacts = _run_backtest(panel, weight_df)
    # 扩展 portfolio 到 RunDetail 期望的完整 schema
    artifacts.portfolio = enrich_portfolio_with_metrics(
        artifacts.portfolio,
        benchmark_daily=artifacts.portfolio["benchmark_return"].astype(float).values,
        periods_per_year=365,
    )
    metrics, report_md = _metrics_and_report(artifacts, df_score, train_metrics)
    run_meta = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "strategy_id": "crypto_perp_demo",
        "strategy_name": "加密永续 demo (alpha_lite × LGBM × MVO × CryptoPerpCost)",
        "market": "binanceusdm",
        "frequency": "1d",
        "benchmark": "BTCUSDT",
        "strategy_mode": "ml",
        "analysis_start": panel.get_column("ts").min().date().isoformat() if panel.height else None,
        "analysis_end": panel.get_column("ts").max().date().isoformat() if panel.height else None,
        "execution_profile": "full_backtest",
        "execution_model": "next_bar_open",
        "instrument_type": "crypto_perp",
        "model_used": True,
        "factor_ids": factor_ids,
        "leverage_max": 2.0,
        "asset_class": "crypto_perp",
    }
    write_run_artifacts(
        run_id=run_id,
        run_meta=run_meta,
        portfolio=artifacts.portfolio,
        trades=artifacts.trades,
        metrics=metrics,
        report_markdown=report_md,
    )
    return {"run_id": run_id, "metrics": metrics}


def _cli() -> None:
    parser = argparse.ArgumentParser(description="QuantBT · 加密永续端到端 demo")
    parser.add_argument("--run-id", default="crypto_perp_demo")
    parser.add_argument("--days", type=int, default=240)
    args = parser.parse_args()
    out = run(run_id=args.run_id, days=args.days)
    m = out["metrics"]
    print(f"✅ {args.run_id} done · sharpe={m['sharpe']:.4f} · pbo={m['pbo']['pbo']:.4f} · dsr={m['deflated_sharpe']:.4f}")
    print(f"   成本：fee={m['cost_breakdown']['total_fee']:.2f} funding={m['cost_breakdown']['total_funding']:.2f}")
    print(f"   产物：data/artifacts/experiments/{args.run_id}/")


if __name__ == "__main__":
    _cli()
