"""Binance Vision connector · 历史压缩包数据。

复用现有 `binance_vision_pull.py` 的 fetch 路径（按 day zip → CSV → DataFrame），
不重复实现。对 connector 抽象层只暴露简洁的 fetch_ohlcv。
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from .. import binance_vision_pull as bvp
from .base import (
    ConnectorCapability,
    ConnectorHealth,
    DataConnector,
    FetchRequest,
    FetchResult,
    enforce_unified_schema,
    make_fetch_result,
)


_VISION_INTERVALS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
_VISION_MARKETS = ("binance_spot", "binanceusdm", "binancecm")


def _to_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


class BinanceVisionConnector(DataConnector):
    def __init__(self, asset_kind: str = "binanceusdm") -> None:
        self._asset_kind = asset_kind

    def describe(self) -> ConnectorCapability:
        return ConnectorCapability(
            name=f"binance_vision::{self._asset_kind}",
            label="Binance Vision (历史压缩包)",
            asset_class="crypto_perp" if self._asset_kind == "binanceusdm" else "crypto_spot",
            supported_markets=(self._asset_kind,),
            supported_intervals=_VISION_INTERVALS,
            supported_data_kinds=("ohlcv", "funding_rate", "agg_trades", "metrics"),
            auth_mode="none",
            rate_limit_per_minute=None,
            realtime=False,
            note="data.binance.vision 公开 zip；T+1 历史数据",
        )

    def health_check(self) -> ConnectorHealth:
        t0 = time.perf_counter()
        try:
            import requests

            resp = requests.head(bvp.VISION_BASE, timeout=5)
            latency = (time.perf_counter() - t0) * 1000
            ok = resp.status_code < 500
            return ConnectorHealth(
                name=f"binance_vision::{self._asset_kind}",
                ok=ok,
                checked_at_utc=datetime.now(UTC).isoformat(),
                latency_ms=latency,
                detail=f"HEAD {bvp.VISION_BASE} → {resp.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                name=f"binance_vision::{self._asset_kind}",
                ok=False,
                checked_at_utc=datetime.now(UTC).isoformat(),
                latency_ms=0.0,
                detail=f"unreachable: {exc}",
            )

    def fetch(self, request: FetchRequest) -> FetchResult:
        if request.data_kind != "ohlcv":
            raise NotImplementedError(f"binance_vision connector 当前只支持 ohlcv（请求 {request.data_kind}）")
        start = _to_date(request.start) or date(2020, 1, 1)
        end = _to_date(request.end) or date.today()
        df = self._fetch_klines(request.symbol, request.interval, start, end)
        if df is None or df.is_empty():
            return make_fetch_result(enforce_unified_schema(pl.DataFrame()), source_name=self.describe().name)
        normalized = df.rename({"open_time": "ts"}).with_columns(
            [
                pl.col("ts").cast(pl.Datetime("us", "UTC"), strict=False),
                pl.lit(request.symbol).alias("symbol"),
                pl.lit(self._asset_kind).alias("market"),
                pl.lit(request.interval).alias("interval"),
            ]
        )
        return make_fetch_result(normalized, source_name=self.describe().name)

    def _fetch_klines(self, symbol: str, interval: str, start: date, end: date) -> pl.DataFrame:
        kind_map = {
            "binance_spot": "vision_spot_klines",
            "binancecm": "vision_cm_klines",
            "binanceusdm": "vision_klines",
        }
        disk_kind = kind_map.get(self._asset_kind, "vision_klines")
        spec = bvp._build_vision_registry().get(disk_kind)
        if spec is None:
            return pl.DataFrame()
        frames: list[pl.DataFrame] = []
        current = start
        while current <= end:
            try:
                url = bvp._daily_zip_url(spec, symbol.upper(), interval, current)
                raw = bvp._download_zip(url)
                csv = bvp._read_first_csv_from_zip(raw)
                day_df = bvp._vision_kline_csv_to_ohlcv(csv, symbol.upper())
            except Exception:  # noqa: BLE001
                day_df = pl.DataFrame()
            if day_df is not None and day_df.height:
                frames.append(day_df)
            current = date.fromordinal(current.toordinal() + 1)
        if not frames:
            return pl.DataFrame()
        return pl.concat(frames, how="diagonal_relaxed")


__all__ = ["BinanceVisionConnector"]
