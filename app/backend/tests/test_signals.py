from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from app.signals import (
    FactorAttribution,
    Signal,
    apply_regime_gating,
    calibrate_confidence,
    confidence_threshold_filter,
    fuse_signals,
)


def _scores() -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [
        {"ts": base, "symbol": "X", "score": 0.7},
        {"ts": base, "symbol": "Y", "score": -0.5},
        {"ts": base + timedelta(days=1), "symbol": "X", "score": 0.05},
    ]
    return pl.DataFrame(rows)


def test_signal_schema_validates() -> None:
    sig = Signal(
        ts=datetime(2024, 1, 1, tzinfo=UTC),
        symbol="X",
        direction="long",
        magnitude=0.5,
        confidence=0.7,
        contributing_factors=[FactorAttribution(factor_id="mom20", contribution=0.4)],
    )
    assert sig.regime == "range"
    with pytest.raises(ValueError):
        Signal(ts=datetime.now(UTC), symbol="A", direction="long", magnitude=1.5, confidence=0.5)


def test_fuse_signals_produces_direction_magnitude_confidence() -> None:
    df = fuse_signals(_scores())
    assert {"direction", "magnitude", "confidence"}.issubset(df.columns)
    rows = df.to_dicts()
    assert rows[0]["direction"] == "long"
    assert rows[1]["direction"] == "short"
    assert rows[2]["direction"] == "long"
    assert all(0 <= r["confidence"] <= 1 for r in rows)


def test_fuse_long_only_drops_shorts() -> None:
    df = fuse_signals(_scores(), long_only=True)
    rows = df.to_dicts()
    assert rows[1]["direction"] == "flat"


def test_regime_gating_drops_long_in_bear() -> None:
    sig = fuse_signals(_scores())
    regimes = pl.DataFrame({"ts": sig["ts"].unique().to_list(), "regime": ["bear", "bull"]})
    gated = apply_regime_gating(sig, regimes)
    # 第一天 bear，long 应被打成 flat；short 保留
    first_day = gated.filter(pl.col("ts") == sig["ts"][0]).sort("symbol").to_dicts()
    assert first_day[0]["direction"] == "flat"  # X (long → bear → flat)
    assert first_day[1]["direction"] == "short"  # Y (short → bear → 允许)


def test_confidence_threshold_filter_zeroes_low_confidence() -> None:
    sig = fuse_signals(_scores())
    out = confidence_threshold_filter(sig, min_confidence=0.7)
    rows = out.to_dicts()
    assert all(r["magnitude"] == 0.0 or r["confidence"] >= 0.7 for r in rows)


def test_calibrate_confidence_isotonic_outputs_in_unit_interval() -> None:
    rng = np.random.default_rng(0)
    scores = rng.normal(size=200)
    outcomes = (scores + rng.normal(scale=0.3, size=200) > 0).astype(int)
    calibrated = calibrate_confidence(scores, outcomes, method="isotonic")
    assert calibrated.min() >= 0.0
    assert calibrated.max() <= 1.0


def test_calibrate_confidence_platt_outputs_in_unit_interval() -> None:
    rng = np.random.default_rng(1)
    scores = rng.normal(size=200)
    outcomes = (scores > 0).astype(int)
    calibrated = calibrate_confidence(scores, outcomes, method="platt")
    assert calibrated.min() >= 0.0
    assert calibrated.max() <= 1.0
