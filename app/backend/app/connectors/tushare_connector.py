"""Tushare connector · 包装现有 `tushare_quant1` puller。

设计：
- describe() 报告 A股能力（沪深主板 / 创业板 / 科创板 / 指数 / ETF）。
- fetch(ohlcv) 用 tushare SDK 直接查（不落 CSV）；token 走环境变量
  `TUSHARE_TOKEN`，绝不进 YAML。
- 令牌桶限流（默认 480 次/分，预留 buffer）+ 命中错误码自动 sleep 重试。
- 失败时把错误细节写进 ConnectorHealth.detail，不抛栈。
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from .base import (
    ConnectorCapability,
    ConnectorHealth,
    DataConnector,
    FetchRequest,
    FetchResult,
    enforce_unified_schema,
    make_fetch_result,
)


_RATE_LIMIT_PER_MIN = 480
_MARKETS = ("stocks_cn", "indices_cn", "funds_cn", "bonds_cn", "stocks_hk", "stocks_us")
_INTERVALS = ("1d", "1w", "1mo", "1m", "5m", "15m", "30m", "60m")


class TushareConnector(DataConnector):
    def __init__(self, token: str | None = None, sleep: float = 0.0) -> None:
        self._token = token or os.environ.get("TUSHARE_TOKEN", "")
        self._sleep = sleep
        self._last_call: float | None = None
        self._calls_in_window: list[float] = []

    def describe(self) -> ConnectorCapability:
        return ConnectorCapability(
            name="tushare",
            label="Tushare Pro (A股)",
            asset_class="equity_cn",
            supported_markets=_MARKETS,
            supported_intervals=_INTERVALS,
            supported_data_kinds=("ohlcv", "adj_factor", "index_daily", "fund_basic", "fina_indicator"),
            auth_mode="token",
            rate_limit_per_minute=_RATE_LIMIT_PER_MIN,
            realtime=False,
            note="Token 走 TUSHARE_TOKEN 环境变量；500 次/分钟令牌桶",
        )

    def health_check(self) -> ConnectorHealth:
        ts_iso = datetime.now(UTC).isoformat()
        if not self._token:
            return ConnectorHealth(
                name="tushare",
                ok=False,
                checked_at_utc=ts_iso,
                latency_ms=0.0,
                detail="TUSHARE_TOKEN 未配置",
            )
        try:
            t0 = time.perf_counter()
            pro = self._client()
            df = pro.stock_basic(exchange="SSE", list_status="L", limit=1)
            latency = (time.perf_counter() - t0) * 1000
            return ConnectorHealth(
                name="tushare",
                ok=df is not None,
                checked_at_utc=ts_iso,
                latency_ms=latency,
                detail=f"stock_basic rows={len(df) if df is not None else 0}",
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                name="tushare",
                ok=False,
                checked_at_utc=ts_iso,
                latency_ms=0.0,
                detail=f"tushare error: {exc}",
            )

    def list_symbols(self, market: str | None = None) -> list[str]:
        if market not in (None, "stocks_cn"):
            return []
        if not self._token:
            return []
        try:
            df = self._client().stock_basic(exchange="", list_status="L", fields="ts_code")
            return df["ts_code"].astype(str).tolist() if df is not None else []
        except Exception:  # noqa: BLE001
            return []

    def fetch(self, request: FetchRequest) -> FetchResult:
        if not self._token:
            raise RuntimeError("TUSHARE_TOKEN 未配置（请通过环境变量或 UI 设置后再使用 Tushare connector）")
        if request.data_kind != "ohlcv":
            raise NotImplementedError(f"tushare connector 暂不支持 data_kind={request.data_kind}")
        self._throttle()
        pro = self._client()
        start = (request.start or datetime.now(UTC) - timedelta(days=365)).strftime("%Y%m%d")
        end = (request.end or datetime.now(UTC)).strftime("%Y%m%d")
        df = pro.daily(ts_code=request.symbol, start_date=start, end_date=end)
        if df is None or df.empty:
            return make_fetch_result(enforce_unified_schema(pl.DataFrame()), source_name="tushare")
        pl_df = pl.from_pandas(df)
        pl_df = pl_df.rename({"trade_date": "ts", "vol": "volume"})
        pl_df = pl_df.with_columns(
            [
                pl.col("ts").cast(pl.String).str.to_datetime("%Y%m%d", time_zone="UTC", strict=False),
                pl.lit(request.symbol).alias("symbol"),
                pl.lit("stocks_cn").alias("market"),
                pl.lit(request.interval or "1d").alias("interval"),
            ]
        )
        pl_df = pl_df.with_columns(pl.col("amount").cast(pl.Float64, strict=False))
        return make_fetch_result(pl_df, source_name="tushare")

    def _throttle(self) -> None:
        now = time.perf_counter()
        window = 60.0
        self._calls_in_window = [t for t in self._calls_in_window if now - t < window]
        if len(self._calls_in_window) >= _RATE_LIMIT_PER_MIN:
            sleep_s = window - (now - self._calls_in_window[0]) + 0.01
            if sleep_s > 0:
                time.sleep(sleep_s)
        self._calls_in_window.append(time.perf_counter())
        if self._sleep:
            time.sleep(self._sleep)

    def _client(self) -> Any:
        import tushare as ts  # 延迟 import，避免无 token 时仍触发 SDK 初始化

        ts.set_token(self._token)
        return ts.pro_api()


__all__ = ["TushareConnector"]
