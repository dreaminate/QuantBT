"""训练台模型 → 回测 桥接。

回答"训练台训出来的模型能不能在回测里用"：能。本模块把训练产物（.pkl ML / .pt DL）
接进一条标准回测链：

    predict_with(artifact) → 每日截面打分 → top-N 等权(或多空)权重
    → shift(1) 防前视（今日权重用昨日收盘信号）→ 逐日组合收益 → 指标 + 净值曲线

设计为纯库（numpy/pandas，零 examples 依赖、零 torch 主进程导入；DL 经 predict_with 子逻辑）。
返回 dict：{equity_curve, returns, weights, metrics}，可直接喂 REST / 落 run 产物。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .lib import predict_with


def scores_to_weights(
    scores: pd.DataFrame,
    *,
    top_n: int = 5,
    long_short: bool = False,
) -> pd.DataFrame:
    """每日截面分数 → 权重矩阵（index=ts, columns=symbol）。

    - long_only：每日取分数最高的 top_n，等权（和=1）。
    - long_short：多头 top_n 等权 + 空头 bottom_n 等权（和=0，多空中性）。
    - 全 NaN（或有效标的不足）的日 → 当日空仓（全 0），不报错。
    """
    w = pd.DataFrame(0.0, index=scores.index, columns=scores.columns)
    for ts, row in scores.iterrows():
        valid = row.dropna()
        if valid.empty:
            continue
        k = min(top_n, len(valid))
        if k <= 0:
            continue
        longs = valid.nlargest(k).index
        if long_short:
            shorts = valid.nsmallest(k).index
            # 避免多空重叠（标的太少时）
            shorts = [s for s in shorts if s not in set(longs)]
            if longs.size:
                w.loc[ts, longs] = 1.0 / len(longs)
            if shorts:
                w.loc[ts, shorts] = -1.0 / len(shorts)
        else:
            w.loc[ts, longs] = 1.0 / len(longs)
    return w


def _metrics_from_returns(returns: np.ndarray, *, periods_per_year: int = 252) -> dict[str, float]:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return {"total_return": 0.0, "annualized_return": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "volatility": 0.0, "win_rate": 0.0}
    equity = np.cumprod(1.0 + r)
    total = float(equity[-1] - 1.0)
    ann = float((equity[-1]) ** (periods_per_year / len(r)) - 1.0) if len(r) > 0 else 0.0
    sd = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    sharpe = float(np.mean(r) / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.min(equity / peak - 1.0))
    return {
        "total_return": total,
        "annualized_return": ann,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "volatility": sd * math.sqrt(periods_per_year),
        "win_rate": float(np.mean(r > 0)),
    }


def backtest_trained_model(
    artifact_path: str | Path,
    panel: pd.DataFrame,
    *,
    feature_cols: list[str],
    ts_col: str = "ts",
    symbol_col: str = "symbol",
    price_col: str = "close",
    top_n: int = 5,
    long_short: bool = False,
    periods_per_year: int = 252,
    oos_fraction: float | None = None,
) -> dict[str, Any]:
    """用已训练模型在 panel 上跑回测。

    panel 需含 ts_col / symbol_col / price_col + feature_cols。返回 dict：
        {equity_curve(pd.Series), returns(pd.Series), weights(pd.DataFrame), metrics(dict),
         n_days, n_symbols, model_artifact, oos_cutoff}

    ``oos_fraction``：取最后这一比例的**日期**做样本外回测（0<frac<=1）。例如 0.3 =
    只回测末尾 30% 的交易日。None = 全段。注意：是否真"样本外"取决于训练是否见过这些日期。
    """
    missing = [c for c in (ts_col, symbol_col, price_col) if c not in panel.columns]
    if missing:
        raise ValueError(f"回测面板缺列: {missing}（需要 ts/symbol/price）")
    miss_feat = [c for c in feature_cols if c not in panel.columns]
    if miss_feat:
        raise ValueError(f"回测数据集缺模型所需特征列: {miss_feat}（须与训练特征同名）")
    if not feature_cols:
        raise ValueError("feature_cols 不能为空")

    df = panel.copy()
    oos_cutoff: str | None = None
    if oos_fraction is not None:
        if not (0.0 < oos_fraction <= 1.0):
            raise ValueError("oos_fraction 必须在 (0, 1] 区间")
        uniq_dates = np.sort(df[ts_col].unique())
        if len(uniq_dates) >= 2 and oos_fraction < 1.0:
            cut_idx = int(len(uniq_dates) * (1.0 - oos_fraction))
            cut_idx = min(max(cut_idx, 0), len(uniq_dates) - 1)
            cutoff = uniq_dates[cut_idx]
            df = df[df[ts_col] >= cutoff].copy()
            oos_cutoff = str(pd.Timestamp(cutoff))
    # 1) 模型打分（DL 的 warmup 行为 NaN，会被 scores_to_weights 当日跳过）
    df["_score"] = predict_with(artifact_path, df, feature_cols)

    # 2) 透视成 ts × symbol 的分数 / 价格矩阵
    scores = df.pivot_table(index=ts_col, columns=symbol_col, values="_score", aggfunc="last").sort_index()
    prices = df.pivot_table(index=ts_col, columns=symbol_col, values=price_col, aggfunc="last").sort_index()
    prices = prices.reindex(columns=scores.columns)

    # 3) 每日权重；shift(1) → 今日用昨日收盘的信号持仓（防前视）
    weights = scores_to_weights(scores, top_n=top_n, long_short=long_short).shift(1).fillna(0.0)

    # 4) 标的日收益 → 组合日收益
    asset_rets = prices.pct_change().fillna(0.0)
    port_rets = (weights * asset_rets).sum(axis=1)

    equity = (1.0 + port_rets).cumprod()
    metrics = _metrics_from_returns(port_rets.to_numpy(), periods_per_year=periods_per_year)
    return {
        "equity_curve": equity,
        "returns": port_rets,
        "weights": weights,
        "metrics": metrics,
        "n_days": int(scores.shape[0]),
        "n_symbols": int(scores.shape[1]),
        "model_artifact": str(artifact_path),
        "oos_cutoff": oos_cutoff,
    }


def backtest_job(
    artifact_dir: str | Path,
    panel: pd.DataFrame,
    *,
    feature_cols: list[str],
    symbol_col: str = "symbol",
    **kwargs: Any,
) -> dict[str, Any]:
    """便捷入口：给训练 job 的 artifact_dir，自动找 model.pkl / model.pt。"""
    d = Path(artifact_dir)
    pkl, pt = d / "model.pkl", d / "model.pt"
    artifact = pkl if pkl.exists() else pt
    if not artifact.exists():
        raise FileNotFoundError(f"job 目录无模型产物(model.pkl/.pt): {d}")
    return backtest_trained_model(
        artifact, panel, feature_cols=feature_cols, symbol_col=symbol_col, **kwargs
    )


__all__ = ["backtest_job", "backtest_trained_model", "scores_to_weights"]
