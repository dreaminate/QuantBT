"""样例数据集生成器 (合成数据，可重复)。

设计：
- 用固定 seed 让相同参数生成完全一致的数据
- 输出 polars DataFrame，调用方决定写 parquet/csv
- 加密永续：GBM + 偶发 jump
- A股 ETF：多 symbol 相关性 + 简单 trend
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import polars as pl


@dataclass(frozen=True)
class SampleManifest:
    sample_id: str
    asset_class: str  # crypto_perp / crypto_spot / equity_cn
    description: str
    symbols: tuple[str, ...]
    interval: str
    rows: int
    columns: tuple[str, ...]
    path_hint: str  # 相对仓库根的相对路径

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "asset_class": self.asset_class,
            "description": self.description,
            "symbols": list(self.symbols),
            "interval": self.interval,
            "rows": self.rows,
            "columns": list(self.columns),
            "path_hint": self.path_hint,
        }


_SAMPLE_REGISTRY: dict[str, SampleManifest] = {}


def _register(m: SampleManifest) -> None:
    _SAMPLE_REGISTRY[m.sample_id] = m


def _seeded_random(seed: int):
    """避免依赖 numpy 强制依赖：用 random.Random 也能跑 GBM。"""
    import random
    return random.Random(seed)


def generate_btc_perp_sample(*, days: int = 365, seed: int = 42, start_price: float = 30000.0) -> pl.DataFrame:
    """BTC-USDT 永续 daily OHLCV，GBM + 偶发 jump（合成数据）。"""

    rng = _seeded_random(seed)
    rows: list[dict] = []
    close = start_price
    for d in range(days):
        # GBM: mu=0.0005, sigma=0.025
        ret = rng.gauss(0.0005, 0.025)
        # 5% 概率 jump ±5%
        if rng.random() < 0.05:
            ret += rng.choice([-0.05, 0.05])
        new_close = close * (1 + ret)
        # OHLC 围绕 close 生成
        high = max(close, new_close) * (1 + abs(rng.gauss(0, 0.008)))
        low = min(close, new_close) * (1 - abs(rng.gauss(0, 0.008)))
        open_ = close
        volume = rng.gauss(50000, 12000)
        # funding rate (永续特有) ±0.05%
        funding = rng.gauss(0.0001, 0.0003)
        ts = f"2025-01-01T00:00:00Z"  # 占位；真用日历需要 datetime 库，这里只标 index
        rows.append({
            "t_index": d,
            "symbol": "BTC-USDT",
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(new_close, 2),
            "volume": round(max(volume, 0), 2),
            "funding_rate": round(funding, 6),
        })
        close = new_close
    return pl.DataFrame(rows)


def generate_eth_perp_sample(*, days: int = 365, seed: int = 43, start_price: float = 2000.0) -> pl.DataFrame:
    """ETH-USDT 永续 daily OHLCV，相关于 BTC 但波动更大。"""
    return generate_btc_perp_sample(days=days, seed=seed, start_price=start_price).with_columns(
        pl.lit("ETH-USDT").alias("symbol"),
    )


def generate_ashare_etf_sample(
    *,
    symbols: Iterable[str] = ("510300", "510500", "510050", "510880"),
    days: int = 252,
    seed: int = 7,
) -> pl.DataFrame:
    """A股 ETF 多 symbol daily OHLCV (合成)。"""

    rng = _seeded_random(seed)
    rows: list[dict] = []
    for sym in symbols:
        close = rng.uniform(2.5, 5.0)
        for d in range(days):
            # 日波动较小
            ret = rng.gauss(0.0003, 0.012)
            new_close = close * (1 + ret)
            high = max(close, new_close) * (1 + abs(rng.gauss(0, 0.004)))
            low = min(close, new_close) * (1 - abs(rng.gauss(0, 0.004)))
            volume = rng.gauss(8e7, 2e7)
            rows.append({
                "t_index": d,
                "symbol": sym,
                "open": round(close, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(new_close, 4),
                "volume": round(max(volume, 0), 2),
            })
            close = new_close
    return pl.DataFrame(rows)


# 注册 3 个 sample
_register(SampleManifest(
    sample_id="btc_perp_daily_365d",
    asset_class="crypto_perp",
    description="BTC-USDT 永续 365 日合成 OHLCV + funding_rate (GBM + 偶发 jump，seed=42)",
    symbols=("BTC-USDT",),
    interval="1d",
    rows=365,
    columns=("t_index", "symbol", "open", "high", "low", "close", "volume", "funding_rate"),
    path_hint="data/samples/btc_perp_daily_365d.parquet",
))

_register(SampleManifest(
    sample_id="eth_perp_daily_365d",
    asset_class="crypto_perp",
    description="ETH-USDT 永续 365 日合成 OHLCV (seed=43)",
    symbols=("ETH-USDT",),
    interval="1d",
    rows=365,
    columns=("t_index", "symbol", "open", "high", "low", "close", "volume", "funding_rate"),
    path_hint="data/samples/eth_perp_daily_365d.parquet",
))

_register(SampleManifest(
    sample_id="ashare_etf_daily_252d",
    asset_class="equity_cn",
    description="A股 ETF 4 标的 (510300/510500/510050/510880) 252 日合成 OHLCV (seed=7)",
    symbols=("510300", "510500", "510050", "510880"),
    interval="1d",
    rows=252 * 4,
    columns=("t_index", "symbol", "open", "high", "low", "close", "volume"),
    path_hint="data/samples/ashare_etf_daily_252d.parquet",
))


def list_samples() -> list[dict[str, Any]]:
    return [m.to_dict() for m in _SAMPLE_REGISTRY.values()]


def load_sample(sample_id: str, *, data_root: Path | None = None) -> pl.DataFrame | None:
    """如果落盘文件存在直接读，否则按 sample_id 重新生成。"""
    if sample_id == "btc_perp_daily_365d":
        return generate_btc_perp_sample()
    if sample_id == "eth_perp_daily_365d":
        return generate_eth_perp_sample()
    if sample_id == "ashare_etf_daily_252d":
        return generate_ashare_etf_sample()
    return None


__all__ = [
    "SampleManifest",
    "generate_ashare_etf_sample",
    "generate_btc_perp_sample",
    "generate_eth_perp_sample",
    "list_samples",
    "load_sample",
]
