"""端到端 A股 ML demo · 一键串通 QuantBT 全栈。

跑这个脚本会做什么：

1. 合成 30 只 A股标的的 240 个交易日 panel（deterministic seed=7）
2. 用 `factor_factory` 算 5 个 alpha_lite 因子
3. `labels.xs_rank_label` 生成截面排名标签（learning-to-rank 风格）
4. `models.train_model` 跑 LGBM regressor + Purged k-fold + Embargo
5. `signals.fuse_signals` + long_only + confidence threshold
6. 每日选 top-5 → `portfolio.hrp_weights` 做权重
7. `execution.BacktestVenue` 逐日撮合（real cost_model）
8. `eval.cscv_pbo / deflated_sharpe_ratio / bootstrap_sharpe_ci`
9. `eval.brinson_attribution` 算 sector 维度归因
10. 落到 `data/artifacts/experiments/{run_id}/` 标准目录，含 report.md

不依赖 Tushare / 外部网络；任何 dev 环境都能跑。
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

# 这些 import 走 _e2e_common 里塞进 sys.path 的 backend
from app.eval import (
    bootstrap_sharpe_ci,
    brinson_attribution,
    cscv_pbo,
    deflated_sharpe_ratio,
    sharpe_ratio,
)
from app.execution import BacktestCostModel, BacktestVenue, Order
from app.factor_factory import alpha_lite_specs, evaluate_on_panel
from app.labels import xs_rank_label
from app.models import ModelSpec, train_model
from app.portfolio import PortfolioConstraints, hrp_weights
from app.signals import confidence_threshold_filter, fuse_signals


_SECTORS = ["tech", "finance", "consumer", "energy", "healthcare"]


def _symbol_universe(n_symbols: int = 30) -> tuple[list[str], dict[str, str]]:
    symbols = [f"SH{600000 + i:06d}" for i in range(n_symbols)]
    sectors = {s: _SECTORS[i % len(_SECTORS)] for i, s in enumerate(symbols)}
    return symbols, sectors


# ----- 步骤 2-3：特征 + 标签 -----

def _build_feature_panel(panel: pl.DataFrame, factor_ids: list[str]) -> pl.DataFrame:
    feats = panel.select(["ts", "symbol"])
    specs = {s.factor_id: s.formula for s in alpha_lite_specs()}
    for fid in factor_ids:
        formula = specs[fid]
        out = evaluate_on_panel(panel, formula, alias=fid)
        feats = feats.join(out, on=["ts", "symbol"], how="left")
    return feats


def _attach_labels(panel: pl.DataFrame, feats: pl.DataFrame, horizon: int = 5) -> pl.DataFrame:
    labels = xs_rank_label(panel, horizon=horizon).rename({"label_xs_rank": "label"})
    enriched = feats.join(labels, on=["ts", "symbol"], how="inner")
    # 保留 close / sector，供下游 HRP / Brinson 用
    keep_cols = panel.select(["ts", "symbol", "close", "sector"])
    return enriched.join(keep_cols, on=["ts", "symbol"], how="left")


# ----- 步骤 4：训练 -----

def _train(panel_df: pl.DataFrame, feature_cols: list[str]) -> tuple[pd.DataFrame, Any]:
    df = panel_df.drop_nulls(["label"] + feature_cols).to_pandas()
    spec = ModelSpec(
        task="regression",
        model="lgbm",
        feature_cols=feature_cols,
        label_col="label",
        cv_scheme="purged_kfold",
        n_splits=5,
        embargo_pct=0.02,
    )
    result = train_model(spec, df.copy())
    # 用全数据拟合一个最终模型给"未来日"预测
    import lightgbm as lgb
    final_model = lgb.LGBMRegressor(verbose=-1, n_estimators=100)
    final_model.fit(df[feature_cols].values, df["label"].values)
    df["score"] = final_model.predict(df[feature_cols].values)
    return df, result


# ----- 步骤 5-6：信号 → 组合权重 -----

def _per_day_weights(
    panel_with_score: pd.DataFrame,
    *,
    top_n: int = 5,
    confidence_min: float = 0.55,
) -> pd.DataFrame:
    """每日选 top_n，用 HRP 算权重。返回 (ts, symbol, weight)。"""

    rows: list[dict[str, Any]] = []
    by_ts = panel_with_score.groupby("ts", sort=True)
    panel_pl = pl.from_pandas(panel_with_score)
    fused = fuse_signals(panel_pl, score_col="score", long_only=True)
    fused = confidence_threshold_filter(fused, min_confidence=confidence_min).to_pandas()
    for ts, grp in by_ts:
        grp = grp.merge(fused[["ts", "symbol", "direction", "confidence"]], on=["ts", "symbol"], how="left")
        grp = grp[grp["direction"] == "long"]
        if len(grp) == 0:
            continue
        top = grp.nlargest(top_n, "score")
        if len(top) < 2:
            for _, r in top.iterrows():
                rows.append({"ts": ts, "symbol": r["symbol"], "weight": 1.0})
            continue
        history_window = panel_with_score[panel_with_score["ts"] <= ts].tail(60 * top_n)
        cov_df = (
            history_window.pivot(index="ts", columns="symbol", values="close")
            .pct_change()
            .reindex(columns=top["symbol"].tolist())
            .dropna(how="all")
            .cov()
            .fillna(0.0)
        )
        if cov_df.empty or (cov_df.shape[0] != cov_df.shape[1]):
            equal_w = 1.0 / max(len(top), 1)
            for _, r in top.iterrows():
                rows.append({"ts": ts, "symbol": r["symbol"], "weight": equal_w})
            continue
        try:
            weights = hrp_weights(cov_df)
        except Exception:  # noqa: BLE001
            weights = {s: 1.0 / len(top) for s in top["symbol"]}
        for sym, w in weights.items():
            if w > 0:
                rows.append({"ts": ts, "symbol": sym, "weight": float(w)})
    return pd.DataFrame(rows)


# ----- 步骤 7：回测 -----

@dataclass
class BacktestArtifacts:
    portfolio: pd.DataFrame
    trades: pd.DataFrame
    benchmark: pd.DataFrame  # 等权全宇宙基准


def _run_backtest(
    panel: pl.DataFrame,
    weight_df: pd.DataFrame,
    *,
    initial_cash: float = 1_000_000.0,
) -> BacktestArtifacts:
    cost = BacktestCostModel(commission_bps=2.5, slippage_bps=5.0, stamp_duty_bps=10.0)
    venue = BacktestVenue(prices=panel, cost_model=cost, cash=initial_cash)
    panel_pd = panel.to_pandas()
    timestamps = sorted(panel_pd["ts"].unique())
    weight_df_idx = weight_df.set_index(["ts", "symbol"])["weight"] if len(weight_df) else pd.Series(dtype=float)
    bench_returns = (
        panel_pd.pivot(index="ts", columns="symbol", values="close").pct_change().mean(axis=1).fillna(0.0)
    )
    rows: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    bench_equity = initial_cash
    peak = initial_cash
    prev_equity = initial_cash
    prev_bench_equity = initial_cash
    for idx, ts in enumerate(timestamps[:-1]):
        next_ts = timestamps[idx + 1]
        bar = panel_pd[panel_pd["ts"] == ts]
        try:
            target = weight_df_idx.xs(ts, level="ts").to_dict()
        except KeyError:
            target = {}
        if isinstance(target, float):
            target = {}
        # 把 prev_weights 与 target 比较，下 buy / sell orders
        all_symbols = set(prev_weights) | set(target)
        for sym in sorted(all_symbols):
            delta = float(target.get(sym, 0.0)) - float(prev_weights.get(sym, 0.0))
            if abs(delta) < 1e-6:
                continue
            row = bar[bar["symbol"] == sym]
            if row.empty:
                continue
            close_price = float(row["close"].iloc[0])
            usd_delta = delta * initial_cash * 0.99  # 留 1% 现金缓冲
            qty = abs(usd_delta) / close_price
            if qty <= 0:
                continue
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
        # 累计 fills
        fills.extend(executed)
        balance = venue.get_balance().get("USDT")
        cash = balance.free if balance else 0.0
        position_value = 0.0
        snapshot = panel_pd[panel_pd["ts"] == next_ts].set_index("symbol")["close"]
        for sym in venue._positions:  # noqa: SLF001
            pos = venue._positions[sym]  # noqa: SLF001
            mark = snapshot.get(sym, pos.mark_price)
            position_value += pos.quantity * float(mark)
        equity = cash + position_value
        bench_equity *= 1 + bench_returns.loc[next_ts]
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        daily_strat = (equity / prev_equity - 1.0) if prev_equity else 0.0
        daily_bench = (bench_equity / prev_bench_equity - 1.0) if prev_bench_equity else 0.0
        rows.append(
            {
                "timestamp": next_ts,
                "equity": equity,
                # 注意：以下两个是「日收益」(GOAL/RunDetail 期望)，不是累计
                "net_return": daily_strat,
                "benchmark_return": daily_bench,
                "turnover": sum(abs(target.get(s, 0.0) - prev_weights.get(s, 0.0)) for s in all_symbols),
                "drawdown": dd,
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
    bench_df = pd.DataFrame({"timestamp": timestamps, "benchmark_return": [
        (bench_equity / initial_cash) - 1 if t == timestamps[-1] else None for t in timestamps
    ]})
    return BacktestArtifacts(portfolio=portfolio, trades=trades, benchmark=bench_df)


# ----- 步骤 8-9：评估 + 归因 -----

def _strategy_grid(panel_with_score: pd.DataFrame, choices: list[int]) -> np.ndarray:
    """构造 (T, N) 多策略 returns 矩阵给 CSCV 用。

    每列 = "每日 top-K 等权" 这种策略；K 取 choices 中的不同值。
    """

    pivoted_close = panel_with_score.pivot(index="ts", columns="symbol", values="close")
    forward_returns = pivoted_close.pct_change().shift(-1).fillna(0.0)
    strategies: list[np.ndarray] = []
    for k in choices:
        daily: list[float] = []
        for ts, grp in panel_with_score.groupby("ts", sort=True):
            top = grp.nlargest(k, "score")["symbol"].tolist()
            if not top:
                daily.append(0.0)
                continue
            r = float(forward_returns.loc[ts, top].mean()) if ts in forward_returns.index else 0.0
            daily.append(r)
        strategies.append(np.asarray(daily))
    return np.column_stack(strategies)


def _brinson_panels(
    panel: pl.DataFrame,
    weight_df: pd.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    panel_pd = panel.to_pandas()
    panel_pd["return"] = (
        panel_pd.sort_values(["symbol", "ts"]).groupby("symbol")["close"].pct_change().fillna(0.0)
    )
    # 组合 panel：与 weight_df 对齐 sector + return
    port = weight_df.merge(panel_pd[["ts", "symbol", "return", "sector"]], on=["ts", "symbol"])
    # 基准 panel：等权全宇宙
    bench_rows: list[dict[str, Any]] = []
    n_symbols = panel_pd["symbol"].nunique()
    base_weight = 1.0 / n_symbols
    for ts, grp in panel_pd.groupby("ts"):
        for _, r in grp.iterrows():
            bench_rows.append({"ts": ts, "symbol": r["symbol"], "weight": base_weight, "return": r["return"], "sector": r["sector"]})
    return pl.from_pandas(port), pl.from_pandas(pd.DataFrame(bench_rows))


def _metrics_and_report(
    artifacts: BacktestArtifacts,
    panel_with_score: pd.DataFrame,
    panel: pl.DataFrame,
    weight_df: pd.DataFrame,
    train_metrics: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    portfolio = artifacts.portfolio
    # net_return 已经是日收益（修复后），直接喂给所有评估
    daily_returns = portfolio["net_return"].astype(float).values
    boot = bootstrap_sharpe_ci(daily_returns, n_boot=200, seed=42)
    dsr = deflated_sharpe_ratio(daily_returns, n_trials=30)
    grid = _strategy_grid(panel_with_score, choices=[3, 5, 8, 10, 15])
    pbo = cscv_pbo(grid, s_blocks=4, max_combinations=40)
    port_panel, bench_panel = _brinson_panels(panel, weight_df)
    brinson = brinson_attribution(port_panel, bench_panel, group_col="sector")

    # compute_run_metrics 走 _e2e_common，统一口径
    base = compute_run_metrics(
        portfolio,
        trades=artifacts.trades,
        periods_per_year=252,
        extra={
            "pbo": pbo.to_dict(),
            "deflated_sharpe": dsr,
            "bootstrap_sharpe_ci": boot.to_dict(),
            "brinson_total": brinson.total,
            "train_oos": train_metrics.get("oos_metrics", {}),
            "n_factors": 5,
            "n_symbols": int(panel_with_score["symbol"].nunique()),
            "n_days": int(panel_with_score["ts"].nunique()),
        },
    )
    md = _render_report(base)
    return base, md


def _render_report(metrics: dict[str, Any]) -> str:
    boot = metrics["bootstrap_sharpe_ci"]
    pbo = metrics["pbo"]
    brinson = metrics["brinson_total"]
    return f"""# QuantBT · A股 ML demo 报告

## 概要
- 总收益: {metrics['total_return']:.4%}
- 年化收益: {metrics['annualized_return']:.4%}
- 最大回撤: {metrics['max_drawdown']:.4%}
- 夏普: {metrics['sharpe']:.4f}
- Sortino: {metrics.get('sortino', 0):.4f}
- 信息比率: {metrics.get('information_ratio', 0):.4f}
- Alpha (年化): {metrics.get('alpha', 0):.4f}
- Beta: {metrics.get('beta', 0):.4f}
- 基准收益: {metrics.get('benchmark_return', 0):.4%}
- 超额收益: {metrics.get('excess_return', 0):.4%}
- 策略波动率: {metrics.get('strategy_volatility', 0):.4%}
- 基准波动率: {metrics.get('benchmark_volatility', 0):.4%}
- 日均胜率: {metrics.get('daily_win_rate', 0):.4%}

## 过拟合证伪（GOAL §6.1 强制）
- **PBO**: {pbo['pbo']:.4f} (s_blocks={pbo['s_blocks']}, 策略数={pbo['n_strategies']})
- **DSR**: {metrics['deflated_sharpe']:.4f}
- **Bootstrap Sharpe 95% CI**: [{boot['lower']:.4f}, {boot['upper']:.4f}] (estimate={boot['estimate']:.4f})

## Brinson 行业归因
- Allocation: {brinson['allocation']:.6f}
- Selection: {brinson['selection']:.6f}
- Interaction: {brinson['interaction']:.6f}
- 主动收益: {brinson['active_return']:.6f}

## 模型 OOS 指标（Purged k-fold + Embargo）
- {metrics['train_oos']}

## 工程参数
- 因子数: {metrics['n_factors']} · 标的数: {metrics['n_symbols']} · 日历日: {metrics['n_days']} · 成交笔数: {metrics['trade_count']}
"""


# ----- 入口 -----

def run(
    run_id: str = "a_share_ml_demo",
    days: int = 240,
    top_n: int = 5,
    panel: "pl.DataFrame | None" = None,
    *,
    strategy_name: str | None = None,
) -> dict[str, Any]:
    """合成 panel by default；如 panel 入参非空则用之（task 34 真数据走这条）。"""
    if panel is None:
        symbols, sectors = _symbol_universe(30)
        panel = synthetic_panel(symbols=symbols, sectors=sectors, days=days, seed=7)
    factor_ids = [
        "alpha_mom_5d",
        "alpha_mom_20d",
        "alpha_vol_20d",
        "alpha_sma_dev_20d",
        "alpha_amount_zscore_20d",
    ]
    feats = _build_feature_panel(panel, factor_ids)
    panel_with_label = _attach_labels(panel, feats, horizon=5)
    df_with_score, train_result = _train(panel_with_label, factor_ids)
    weight_df = _per_day_weights(df_with_score, top_n=top_n)
    artifacts = _run_backtest(panel, weight_df)
    # 把 portfolio 扩展成完整 schema（alpha/beta/sharpe/sortino/IR/volatility 滚动列）
    artifacts.portfolio = enrich_portfolio_with_metrics(
        artifacts.portfolio,
        benchmark_daily=artifacts.portfolio["benchmark_return"].astype(float).values,
        periods_per_year=252,
    )
    metrics, report_md = _metrics_and_report(
        artifacts, df_with_score, panel, weight_df, train_metrics=train_result.to_dict()
    )
    run_meta = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "strategy_id": run_id,
        "strategy_name": strategy_name or "A股 ML demo (alpha_lite × LGBM × HRP × Brinson)",
        "market": "stocks_cn",
        "frequency": "1d",
        "benchmark": "synthetic_equal_weight",
        "strategy_mode": "ml",
        "analysis_start": panel.get_column("ts").min().date().isoformat() if panel.height else None,
        "analysis_end": panel.get_column("ts").max().date().isoformat() if panel.height else None,
        "execution_profile": "full_backtest",
        "execution_model": "next_bar_open",
        "instrument_type": "equity_cn",
        "model_used": True,
        "factor_ids": factor_ids,
        "top_n": top_n,
        "asset_class": "equity_cn",
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
    parser = argparse.ArgumentParser(description="QuantBT · A股 ML 端到端 demo")
    parser.add_argument("--run-id", default="a_share_ml_demo")
    parser.add_argument("--days", type=int, default=240)
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()
    out = run(run_id=args.run_id, days=args.days, top_n=args.top_n)
    metrics = out["metrics"]
    print(f"✅ {args.run_id} done · sharpe={metrics['sharpe']:.4f} · pbo={metrics['pbo']['pbo']:.4f} · dsr={metrics['deflated_sharpe']:.4f}")
    print(f"   产物：data/artifacts/experiments/{args.run_id}/")


if __name__ == "__main__":
    _cli()
