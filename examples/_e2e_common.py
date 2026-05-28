"""端到端 demo 共用工具：合成 panel + 写标准 run 目录 + 指标后处理。

两个 demo（A股 / 加密永续）共享：
- `synthetic_panel(...)` 产生 deterministic 多 symbol panel + sector
- `enrich_portfolio_with_metrics(...)` 把 daily 收益序列扩展成 RunDetail 期望的
  alpha/beta/sharpe/sortino/IR/volatility... 完整列
- `compute_run_metrics(...)` 计算 run.json metrics 全集
- `write_run_artifacts(...)` 把 portfolio / trades / metrics / report.md 落到
  `data/artifacts/experiments/{run_id}/`（兼容现有 RunDetailPage 期望格式）
"""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

# 让 demo 脚本直接跑时也能 import app.*
BACKEND_DIR = Path(__file__).resolve().parents[1] / "app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def project_run_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "artifacts" / "experiments"


# ----- 合成 panel -----

def synthetic_panel(
    *,
    symbols: list[str],
    sectors: dict[str, str] | None = None,
    days: int = 240,
    start: datetime | None = None,
    base_price: float = 10.0,
    seed: int = 7,
    drift_per_symbol: dict[str, float] | None = None,
    volatility: float = 0.02,
) -> pl.DataFrame:
    """生成 (ts, symbol, market, interval, open, high, low, close, volume, amount, sector)
    panel；deterministic（同 seed 同输出）。
    """

    rng = np.random.default_rng(seed)
    start_dt = start or datetime(2023, 1, 1, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for sid, symbol in enumerate(symbols):
        sector = (sectors or {}).get(symbol, "tech")
        drift = (drift_per_symbol or {}).get(symbol, 0.0003 * (sid % 5 - 2))
        prev = base_price * (1 + sid * 0.1)
        for i in range(days):
            ts = start_dt + timedelta(days=i)
            shock = rng.normal(loc=drift, scale=volatility)
            close = prev * (1 + shock)
            high = max(prev, close) * (1 + abs(rng.normal(scale=0.005)))
            low = min(prev, close) * (1 - abs(rng.normal(scale=0.005)))
            volume = float(rng.integers(800_000, 1_500_000))
            rows.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "market": "stocks_cn",
                    "interval": "1d",
                    "open": prev,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": volume * close,
                    "sector": sector,
                }
            )
            prev = close
    return pl.DataFrame(rows).sort(["symbol", "ts"])


# ----- 标准 run 目录写盘 -----

def _to_iso(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.astimezone(UTC).isoformat()
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.isoformat()
    return str(ts)


def enrich_portfolio_with_metrics(
    portfolio: pd.DataFrame,
    benchmark_daily: pd.Series | list[float] | None = None,
    *,
    periods_per_year: int = 252,
    risk_free_daily: float = 0.0,
) -> pd.DataFrame:
    """把 daily 收益序列扩展成 RunDetail 期望的完整列。

    入参 portfolio 必须含：
        timestamp, equity, net_return (日策略收益), benchmark_return (日基准收益), drawdown, turnover

    填充列：alpha, beta, sharpe, sortino, information_ratio, volatility,
            benchmark_volatility, max_drawdown（与 quant1-demo 同 schema）

    每一行的滚动指标基于「截至当行」的累计样本（per-row, expanding window）。
    """

    df = portfolio.copy().reset_index(drop=True)
    n = len(df)
    if n == 0:
        for col in (
            "alpha", "beta", "sharpe", "sortino", "information_ratio",
            "volatility", "benchmark_volatility", "max_drawdown",
        ):
            if col not in df.columns:
                df[col] = []
        return df

    if benchmark_daily is None and "benchmark_return" in df.columns:
        benchmark_daily = df["benchmark_return"].astype(float).values
    bench = np.asarray(benchmark_daily if benchmark_daily is not None else [0.0] * n, dtype=float)
    strat = df["net_return"].astype(float).values

    alphas = np.zeros(n)
    betas = np.zeros(n)
    sharpes = np.zeros(n)
    sortinos = np.zeros(n)
    irs = np.zeros(n)
    vols = np.zeros(n)
    bvols = np.zeros(n)
    max_dds = np.zeros(n)

    eq = df["equity"].astype(float).values
    # 滚动最大回撤
    peak = eq[0]
    for i in range(n):
        peak = max(peak, eq[i])
        max_dds[i] = eq[i] / peak - 1.0 if peak else 0.0

    for i in range(1, n):
        s = strat[: i + 1] - risk_free_daily
        b = bench[: i + 1] - risk_free_daily
        # 波动率 (annualized)
        if len(s) >= 2:
            s_std = float(np.std(s, ddof=1))
            b_std = float(np.std(b, ddof=1))
            vols[i] = s_std * math.sqrt(periods_per_year)
            bvols[i] = b_std * math.sqrt(periods_per_year)
            s_mean = float(np.mean(s))
            sharpes[i] = (s_mean / s_std) * math.sqrt(periods_per_year) if s_std > 0 else 0.0
            downside = s[s < 0]
            d_std = float(np.std(downside, ddof=1)) if len(downside) >= 2 else 0.0
            sortinos[i] = (s_mean / d_std) * math.sqrt(periods_per_year) if d_std > 0 else 0.0
            # alpha / beta via OLS（cov / var）
            if b_std > 0:
                cov = float(np.cov(s, b, ddof=1)[0][1])
                betas[i] = cov / float(np.var(b, ddof=1))
                alphas[i] = (s_mean - betas[i] * float(np.mean(b))) * periods_per_year
            # 信息比率 (annualized excess / tracking error)
            excess = s - b
            ex_std = float(np.std(excess, ddof=1))
            if ex_std > 0:
                irs[i] = (float(np.mean(excess)) / ex_std) * math.sqrt(periods_per_year)

    df["alpha"] = alphas
    df["beta"] = betas
    df["sharpe"] = sharpes
    df["sortino"] = sortinos
    df["information_ratio"] = irs
    df["volatility"] = vols
    df["benchmark_volatility"] = bvols
    if "max_drawdown" not in df.columns or df["max_drawdown"].isna().all():
        df["max_drawdown"] = max_dds
    return df


def compute_run_metrics(
    portfolio: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    *,
    periods_per_year: int = 252,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 enriched portfolio 构造 run.json.metrics 全集（含 alpha/beta/sortino/IR…）。"""

    if len(portfolio) == 0:
        return dict(extra or {})

    daily_strat = portfolio["net_return"].astype(float).values
    daily_bench = (
        portfolio["benchmark_return"].astype(float).values
        if "benchmark_return" in portfolio.columns
        else np.zeros(len(portfolio))
    )
    cum_strat = float(np.prod(1.0 + daily_strat) - 1.0)
    cum_bench = float(np.prod(1.0 + daily_bench) - 1.0)
    n = len(portfolio)
    ann_strat = (1.0 + cum_strat) ** (periods_per_year / max(n, 1)) - 1.0 if n > 0 else 0.0
    last = portfolio.iloc[-1].to_dict()
    max_dd = float(portfolio["max_drawdown"].min()) if "max_drawdown" in portfolio.columns else 0.0

    # 信息比率 / 波动率 / sharpe / sortino 用全量样本（不是 last row 的累计）
    s = daily_strat
    b = daily_bench
    excess = s - b
    s_std = float(np.std(s, ddof=1)) if len(s) > 1 else 0.0
    b_std = float(np.std(b, ddof=1)) if len(b) > 1 else 0.0
    ex_std = float(np.std(excess, ddof=1)) if len(excess) > 1 else 0.0
    s_mean = float(np.mean(s))
    sharpe = (s_mean / s_std) * math.sqrt(periods_per_year) if s_std > 0 else 0.0
    downside = s[s < 0]
    d_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (s_mean / d_std) * math.sqrt(periods_per_year) if d_std > 0 else 0.0
    ir = (float(np.mean(excess)) / ex_std) * math.sqrt(periods_per_year) if ex_std > 0 else 0.0
    vol_ann = s_std * math.sqrt(periods_per_year)
    bvol_ann = b_std * math.sqrt(periods_per_year)
    # alpha / beta（与基准回归）
    if b_std > 0:
        cov = float(np.cov(s, b, ddof=1)[0][1])
        beta = cov / float(np.var(b, ddof=1))
        alpha_ann = (s_mean - beta * float(np.mean(b))) * periods_per_year
    else:
        beta = 0.0
        alpha_ann = 0.0
    # 胜率 / 盈亏次数 / 盈亏比
    win_days = int((s > 0).sum())
    daily_win_rate = win_days / max(n, 1)
    profit_count = loss_count = 0
    pl_ratio = 0.0
    if trades is not None and len(trades) > 0 and "realized_pnl" in trades.columns:
        pnls = pd.to_numeric(trades["realized_pnl"], errors="coerce").fillna(0.0)
        profit_count = int((pnls > 0).sum())
        loss_count = int((pnls < 0).sum())
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        if len(losses) > 0 and float(losses.abs().mean()) > 0:
            pl_ratio = float(wins.mean() / losses.abs().mean()) if len(wins) > 0 else 0.0
    # 退化：trade-level pnl 全 0 时改用 daily 维度（demo 的 BacktestVenue 没逐单 mark）
    if profit_count + loss_count == 0:
        profit_count = int((s > 0).sum())
        loss_count = int((s < 0).sum())
        wins_d = s[s > 0]
        losses_d = s[s < 0]
        if len(losses_d) > 0 and float(np.abs(np.mean(losses_d))) > 0 and len(wins_d) > 0:
            pl_ratio = float(np.mean(wins_d) / np.abs(np.mean(losses_d)))
    trade_win_rate = profit_count / max(profit_count + loss_count, 1) if (profit_count + loss_count) > 0 else daily_win_rate

    out: dict[str, Any] = {
        "total_return": cum_strat,
        "annualized_return": ann_strat,
        "strategy_annual_return": ann_strat,
        "benchmark_return": cum_bench,
        "excess_return": (1.0 + cum_strat) / (1.0 + cum_bench) - 1.0 if cum_bench != -1 else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "information_ratio": ir,
        "alpha": alpha_ann,
        "beta": beta,
        "max_drawdown": max_dd,
        "volatility": vol_ann,
        "strategy_volatility": vol_ann,
        "benchmark_volatility": bvol_ann,
        "win_rate": trade_win_rate,
        "daily_win_rate": daily_win_rate,
        "trade_win_rate": trade_win_rate,
        "profit_loss_ratio": pl_ratio,
        "profit_count": profit_count,
        "loss_count": loss_count,
        "trade_count": int(len(trades)) if trades is not None else 0,
        "avg_daily_return": s_mean,
        "avg_daily_excess_return": float(np.mean(excess)) if len(excess) else 0.0,
        "excess_sharpe_ratio": ir,
    }
    if extra:
        out.update(extra)
    return out


def write_run_artifacts(
    *,
    run_id: str,
    run_meta: dict[str, Any],
    portfolio: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: dict[str, Any],
    report_markdown: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """落到 data/artifacts/experiments/{run_id}/，按现有 RunDetailPage 期望的列名。"""

    root = project_run_root() / run_id
    root.mkdir(parents=True, exist_ok=True)

    portfolio = portfolio.copy()
    if "timestamp" in portfolio.columns:
        portfolio["timestamp"] = portfolio["timestamp"].map(_to_iso)
    portfolio.to_csv(root / "portfolio.csv", index=False)

    trades = trades.copy()
    if "execution_timestamp" in trades.columns:
        trades["execution_timestamp"] = trades["execution_timestamp"].map(_to_iso)
    trades.to_csv(root / "trades.csv", index=False)

    run_json = {
        "run_id": run_id,
        "started_at": run_meta.get("started_at_utc") or datetime.now(UTC).isoformat(),
        "status": "completed",
        **run_meta,
        "metrics": metrics,
    }
    (root / "run.json").write_text(json.dumps(run_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "report.md").write_text(report_markdown, encoding="utf-8")

    for name, content in (extra_files or {}).items():
        (root / name).write_text(content, encoding="utf-8")
    return root


__all__ = [
    "BACKEND_DIR",
    "compute_run_metrics",
    "enrich_portfolio_with_metrics",
    "project_run_root",
    "synthetic_panel",
    "write_run_artifacts",
]
