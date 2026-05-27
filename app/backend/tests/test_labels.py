from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.labels import (
    excess_return_label,
    meta_label,
    raw_return_label,
    triple_barrier_label,
    vol_adjusted_return_label,
    xs_rank_label,
)
from app.labels.core import label_stats


def _panel() -> pl.DataFrame:
    rows = []
    base = datetime(2024, 1, 1, tzinfo=UTC)
    for sid in range(3):
        prev = 10.0 + sid
        for i in range(60):
            wiggle = ((i + sid * 7) % 11 - 5) * 0.05
            close = prev + wiggle
            rows.append({"ts": base + timedelta(days=i), "symbol": f"S{sid}", "close": close})
            prev = close
    return pl.DataFrame(rows)


def _benchmark() -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [{"ts": base + timedelta(days=i), "close": 100 + (i % 7) * 0.1} for i in range(60)]
    return pl.DataFrame(rows)


def test_raw_return_label() -> None:
    df = raw_return_label(_panel(), horizon=1)
    assert "label_raw_return" in df.columns
    # 最后一行 forward = null
    last = df.sort(["symbol", "ts"]).group_by("symbol", maintain_order=True).tail(1)
    assert last["label_raw_return"].null_count() == last.height


def test_excess_return_label() -> None:
    df = excess_return_label(_panel(), _benchmark(), horizon=1)
    assert "label_excess_return" in df.columns
    assert df.drop_nulls("label_excess_return").height > 0


def test_xs_rank_label_in_unit_interval() -> None:
    df = xs_rank_label(_panel(), horizon=1)
    nonnull = df.drop_nulls("label_xs_rank")
    assert nonnull.height > 0
    assert nonnull["label_xs_rank"].max() <= 1.0
    assert nonnull["label_xs_rank"].min() >= 0.0


def test_vol_adjusted_label_finite() -> None:
    df = vol_adjusted_return_label(_panel(), horizon=1, vol_window=10)
    nonnull = df.drop_nulls("label_vol_adjusted_return")
    assert nonnull.height > 0


def test_triple_barrier_label_classes() -> None:
    panel = _panel()
    out = triple_barrier_label(panel, take_profit_sigma=1.5, stop_loss_sigma=1.5, max_holding_days=8, vol_window=10)
    assert {"label_triple_barrier", "hit_horizon", "return_at_hit"}.issubset(out.columns)
    nonnull = out.drop_nulls("label_triple_barrier")
    assert nonnull.height > 0
    classes = set(nonnull["label_triple_barrier"].to_list())
    assert classes.issubset({-1, 0, 1})


def test_meta_label_aligns_direction() -> None:
    panel = _panel()
    tb = triple_barrier_label(panel, take_profit_sigma=1.5, stop_loss_sigma=1.5, max_holding_days=5, vol_window=10)
    dirs = tb.select(["ts", "symbol"]).with_columns(pl.lit(1).cast(pl.Int8).alias("direction"))
    meta = meta_label(tb, dirs)
    assert "label_meta" in meta.columns
    assert meta["label_meta"].drop_nulls().is_in([0, 1]).all()


def test_label_stats_triple_barrier_shares_sum_to_one() -> None:
    panel = _panel()
    tb = triple_barrier_label(panel, take_profit_sigma=1.5, stop_loss_sigma=1.5, max_holding_days=8, vol_window=10)
    stats = label_stats(tb.drop_nulls("label_triple_barrier"), "label_triple_barrier")
    total = (stats.positive_share or 0) + (stats.negative_share or 0) + (stats.timeout_share or 0)
    assert 0.99 <= total <= 1.01


def test_missing_columns_raise() -> None:
    with pytest.raises(ValueError, match="label"):
        raw_return_label(pl.DataFrame({"ts": [1], "x": [2]}))
