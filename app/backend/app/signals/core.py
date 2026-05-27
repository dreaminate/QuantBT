"""M7 · 信号融合实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel, Field
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


SignalDirection = Literal["long", "short", "flat"]
Regime = Literal["bull", "bear", "range", "crisis"]


class FactorAttribution(BaseModel):
    factor_id: str
    contribution: float = Field(..., description="对最终信号的贡献度 (-1..1)")
    note: str = ""


class Signal(BaseModel):
    ts: datetime
    symbol: str
    direction: SignalDirection
    magnitude: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    regime: Regime = "range"
    contributing_factors: list[FactorAttribution] = []


def fuse_signals(
    predictions: pl.DataFrame,
    *,
    score_col: str = "score",
    direction_threshold: float = 0.0,
    long_only: bool = False,
) -> pl.DataFrame:
    """把模型分数列 → (direction, magnitude, confidence) 三元组。

    简化映射：
    - direction = sign(score - threshold)；long_only=True 时空头映射为 flat
    - magnitude = clip(|score - threshold|, 0, 1)
    - confidence = sigmoid(2 * (score - threshold))   # 概率风格
    """

    if score_col not in predictions.columns:
        raise ValueError(f"predictions 缺少列 {score_col}")
    df = predictions.with_columns(
        ((pl.col(score_col) - direction_threshold).abs().clip(0.0, 1.0)).alias("magnitude"),
        (1 / (1 + (-2 * (pl.col(score_col) - direction_threshold)).exp())).alias("confidence"),
    )
    direction = pl.when(pl.col(score_col) > direction_threshold).then(pl.lit("long"))
    if long_only:
        direction = direction.otherwise(pl.lit("flat"))
    else:
        direction = direction.when(pl.col(score_col) < direction_threshold).then(pl.lit("short")).otherwise(pl.lit("flat"))
    return df.with_columns(direction.alias("direction"))


def apply_regime_gating(
    signals: pl.DataFrame,
    regimes: pl.DataFrame,
    *,
    rules: dict[str, Iterable[str]] | None = None,
) -> pl.DataFrame:
    """根据 regime 关掉某些 direction。

    `rules`: {regime: {允许的 direction 集合}}。例如：
        {"bear": {"short", "flat"}, "bull": {"long", "flat"}, "crisis": {"flat"}}
    """

    default_rules = {
        "bull": {"long", "flat"},
        "bear": {"short", "flat"},
        "range": {"long", "short", "flat"},
        "crisis": {"flat"},
    }
    rules_map: dict[str, set[str]] = {k: set(v) for k, v in (rules or default_rules).items()}
    merged = signals.join(regimes, on="ts", how="left")
    if "regime" not in merged.columns:
        return signals
    keep = []
    for row in merged.iter_rows(named=True):
        regime = row.get("regime") or "range"
        allowed = rules_map.get(regime, {"long", "short", "flat"})
        d = row.get("direction") if row.get("direction") in allowed else "flat"
        keep.append(d)
    return merged.with_columns(pl.Series("direction", keep))


def confidence_threshold_filter(signals: pl.DataFrame, min_confidence: float = 0.55) -> pl.DataFrame:
    """低置信度直接打成 flat / magnitude=0，避免过度交易。"""

    return signals.with_columns(
        pl.when(pl.col("confidence") < min_confidence).then(pl.lit("flat")).otherwise(pl.col("direction")).alias("direction"),
        pl.when(pl.col("confidence") < min_confidence).then(0.0).otherwise(pl.col("magnitude")).alias("magnitude"),
    )


def calibrate_confidence(
    scores: np.ndarray,
    outcomes: np.ndarray,
    method: Literal["isotonic", "platt"] = "isotonic",
) -> np.ndarray:
    """把模型 score 校准成概率口径 0..1（Platt scaling / isotonic）。"""

    scores = np.asarray(scores).ravel()
    outcomes = np.asarray(outcomes).astype(int)
    if method == "isotonic":
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(scores, outcomes)
        return np.clip(ir.predict(scores), 0.0, 1.0)
    lr = LogisticRegression()
    lr.fit(scores.reshape(-1, 1), outcomes)
    return np.clip(lr.predict_proba(scores.reshape(-1, 1))[:, 1], 0.0, 1.0)


__all__ = [
    "FactorAttribution",
    "Signal",
    "SignalDirection",
    "apply_regime_gating",
    "calibrate_confidence",
    "confidence_threshold_filter",
    "fuse_signals",
]
