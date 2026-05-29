"""M2 · regime 检测器测试（合成序列，确定性）。"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from app.regime import RegimeConfig, detect_regime, regime_summary
from app.signals.core import apply_regime_gating


def _ts(n: int) -> list[datetime]:
    base = datetime(2024, 1, 1)
    return [base + timedelta(days=i) for i in range(n)]


def _ohlc(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": _ts(len(closes)),
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
        }
    )


def _top_regime(res: pl.DataFrame, tail: int) -> str:
    counts = regime_summary(res.tail(tail))
    return max(counts, key=counts.get)


def test_uptrend_is_bull() -> None:
    closes = [100.0 * (1.01**i) for i in range(80)]
    res = detect_regime(_ohlc(closes))
    assert _top_regime(res, 40) == "bull"
    last = res.tail(1).to_dicts()[0]
    assert last["regime"] == "bull"
    assert last["plus_di"] > last["minus_di"]


def test_downtrend_is_bear() -> None:
    closes = [100.0 * (0.99**i) for i in range(80)]
    res = detect_regime(_ohlc(closes))
    assert _top_regime(res, 40) == "bear"
    last = res.tail(1).to_dicts()[0]
    assert last["regime"] == "bear"
    assert last["minus_di"] > last["plus_di"]


def test_choppy_is_range() -> None:
    closes = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(80)]
    res = detect_regime(_ohlc(closes))
    tail = res.tail(40)["regime"].to_list()
    assert _top_regime(res, 40) == "range"
    assert "crisis" not in tail


def test_crisis_on_vol_spike() -> None:
    # 110 根极平静（微幅交替）+ 末端一次大跳 → 波动聚集判 crisis。
    calm = [100.0 + (0.05 if i % 2 == 0 else 0.0) for i in range(110)]
    spike = [calm[-1] * 1.3, calm[-1] * 1.3 * 0.82]
    res = detect_regime(_ohlc(calm + spike))
    regimes = res["regime"].to_list()
    assert "crisis" in regimes
    assert "crisis" in res.tail(2)["regime"].to_list()


def test_config_threshold_tunable() -> None:
    # 极高的 crisis_z + adx_trend → 任何序列都退化为 range（阈值确实生效）。
    closes = [100.0 * (1.01**i) for i in range(80)]
    cfg = RegimeConfig(adx_trend=999.0, crisis_z=999.0)
    res = detect_regime(_ohlc(closes), config=cfg)
    assert set(res["regime"].to_list()) == {"range"}


def test_empty_input() -> None:
    empty = pl.DataFrame(schema={"ts": pl.Datetime("us"), "high": pl.Float64, "low": pl.Float64, "close": pl.Float64})
    res = detect_regime(empty)
    assert res.height == 0
    assert {"ts", "regime", "adx", "plus_di", "minus_di", "vol_z"}.issubset(res.columns)
    assert regime_summary(res) == {}


def test_missing_column_raises() -> None:
    df = pl.DataFrame({"ts": _ts(3), "high": [1.0, 2, 3], "close": [1.0, 2, 3]})  # 缺 low
    with pytest.raises(ValueError, match="low"):
        detect_regime(df)


def test_zero_price_no_nan_cascade() -> None:
    # 复核 blocker：prev_close=0 曾 → ret=inf → vol=NaN → NaN>crisis_z 误判整段 crisis。
    closes = [100.0 * (1.002**i) for i in range(130)]
    closes[60] = 0.0  # 停牌/坏 tick/0 打印
    res = detect_regime(_ohlc(closes))
    assert not res["vol_z"].is_nan().any()        # 无 NaN 残留
    assert not res["vol_z"].is_infinite().any()   # 无 inf 残留
    assert "crisis" not in res.tail(20)["regime"].to_list()  # 远离 0 的尾段不再被错标 crisis


def test_warmup_forces_range() -> None:
    # 复核 high：从第 0 根就强趋势，前 2n-1=27 根必须全 range（Wilder 未收敛不臆造趋势）。
    closes = [100.0 * (1.02**i) for i in range(40)]
    res = detect_regime(_ohlc(closes))
    assert set(res.head(27)["regime"].to_list()) == {"range"}  # warmup 区全 range
    assert "bull" in res["regime"].to_list()                   # 收敛后仍能判 bull


def test_feeds_regime_gating() -> None:
    # 输出可直接喂 M7：bull 区间内 short 信号被关成 flat。
    closes = [100.0 * (1.01**i) for i in range(80)]
    res = detect_regime(_ohlc(closes))
    regimes = res.select(["ts", "regime"])
    last_ts = res.tail(10)["ts"].to_list()
    signals = pl.DataFrame(
        {"ts": last_ts, "symbol": ["X"] * 10, "direction": ["short"] * 10}
    )
    gated = apply_regime_gating(signals, regimes)
    assert gated.height == 10
    assert "flat" in gated["direction"].to_list()  # bull 把 short 关掉
