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


def conformal_abstain_gate(
    signals: pl.DataFrame,
    *,
    conformal_band: float,
    score_col: str = "score",
    direction_threshold: float = 0.0,
) -> pl.DataFrame:
    """R23 conformal 弃权门：预测区间 [score±q̂] 跨决策阈值 → 方向不可辨 → **弃权**（flat/magnitude=0）。

    **理论（split-conformal 消费侧）**：q̂=`conformal_band` 是模型残差 (1−α) 预测区间半宽，故真值 ∈
    [score−q̂, score+q̂] 覆盖≥1−α。当 |score − direction_threshold| ≤ q̂ 时该区间**含阈值** → 在 1−α 置信下
    无法判定真值落阈值哪侧 → 方向纯属噪声、**弃权**（direction=flat、magnitude=0、`abstained=True`）。诚实
    「不对噪声下单」、不假信号。

    **q̂ 来源（诚实·不过claim）**：本门**设计**消费 `model_eval.conformal_prediction_band` 的 `band_half_width`
    （量纲同义=对预测/score 的残差区间半宽，已有测试核语义一致）；但**生产信号管线尚未自动串接**——调用方须
    自行传入 q̂（卡 92a2182f ① 库就绪、生产 wiring=follow-on）。绝不暗示已闭环。

    `conformal_band` ≤ 0 → 不弃权（abstained 全 False，向后兼容）；缺 `score_col` → raise（不静默放过：弃权
    判定必须用**原始 score** 量纲与阈值比，confidence 的 sigmoid 已失真不可代）。`abstained` 列 additive。
    """
    if conformal_band <= 0.0:
        return signals.with_columns(pl.lit(False).alias("abstained"))
    if score_col not in signals.columns:
        raise ValueError(
            f"signals 缺少列 {score_col!r}：conformal 弃权需原始 score（与阈值同量纲）判预测区间是否跨阈值，"
            "绝不用 confidence/magnitude 代（sigmoid/clip 已失真）。"
        )
    abstain = (pl.col(score_col) - direction_threshold).abs() <= conformal_band
    return signals.with_columns(
        abstain.alias("abstained"),
        pl.when(abstain).then(pl.lit("flat")).otherwise(pl.col("direction")).alias("direction"),
        pl.when(abstain).then(0.0).otherwise(pl.col("magnitude")).alias("magnitude"),
    )


def compose_signal_pipeline(
    predictions: pl.DataFrame,
    *,
    regimes: pl.DataFrame | None = None,
    score_col: str = "score",
    direction_threshold: float = 0.0,
    long_only: bool = False,
    min_confidence: float = 0.55,
    conformal_band: float = 0.0,
    regime_rules: dict[str, Iterable[str]] | None = None,
) -> pl.DataFrame:
    """信号层【唯一规范组合器】：fuse → regime gating → confidence filter → conformal abstain 按序施加全部安全门。

    **为何需要它（不假信号）**：四个 transform 各自单测齐全、各自导出，但**无任何强制**调用方按序全跑——
    任意调用方可只挑 `fuse_signals` 就直发方向信号、跳过 regime 关停 / 低置信打平 / 区间跨阈弃权（=对噪声下单）。
    本组合器是那条**不可绕过的安全路径**：任何要把模型分变可交易信号的生产路径都应走它，而非自己拼 transform。

    **顺序无关于最终结果、但固定规范顺序便于审计**：下游每个门只把信号**降级为 flat/magnitude=0**（绝不升级
    方向），且各门作用于**稳定输入列**（regime/confidence/score）、flat 为吸收态——故 `direction=flat ⟺
    任一门触发`，与施加顺序无关；magnitude=0 ⟺ 任一门触发。本组合器固定 fuse→regime→confidence→abstain。

    参数（松紧=用户方法学·本组合器只串接不强加阈值）：
    - `regimes=None`（默认）→ 跳过 regime gating（无 regime 数据不臆造）；给则按 `regime_rules`（缺用默认规则）关停。
    - `min_confidence`（默认 0.55，沿用 `confidence_threshold_filter` 口径）：低于则 flat/mag=0。
    - `conformal_band ≤ 0`（默认）→ **不弃权**（向后兼容）；>0 时为模型残差 (1−α) 区间半宽 q̂（量纲同 score），
      `|score−threshold| ≤ q̂` 的样本方向不可辨 → 弃权。q̂ 来源（应取自 `model_eval.conformal_prediction_band`）/α=用户方法学。
    返回带 `direction/magnitude/confidence/abstained` 的 DataFrame（additive，不破输入列）。
    """

    df = fuse_signals(
        predictions, score_col=score_col, direction_threshold=direction_threshold, long_only=long_only,
    )
    if regimes is not None:
        df = apply_regime_gating(df, regimes, rules=regime_rules)
    df = confidence_threshold_filter(df, min_confidence=min_confidence)
    df = conformal_abstain_gate(
        df, conformal_band=conformal_band, score_col=score_col, direction_threshold=direction_threshold,
    )
    return df


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
    "compose_signal_pipeline",
    "confidence_threshold_filter",
    "conformal_abstain_gate",
    "fuse_signals",
]
