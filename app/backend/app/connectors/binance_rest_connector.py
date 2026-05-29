"""Binance 公开 REST · 实时 OHLCV + 资金费率（免认证）。

用 `httpx` 风格的同步 requests，弥补 Vision T+1 的延迟。
- /api/v3/klines (Spot)
- /fapi/v1/klines (USDM)
- /fapi/v1/fundingRate
- /fapi/v1/premiumIndex (实时资金费率)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Literal

import polars as pl
import requests

from .base import (
    ConnectorCapability,
    ConnectorHealth,
    DataConnector,
    FetchRequest,
    FetchResult,
    make_wide_fetch_result,
)


_SPOT_BASE = "https://api.binance.com"
_USDM_BASE = "https://fapi.binance.com"
_INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M")
_MAX_LIMIT = 1500


class BinanceRESTConnector(DataConnector):
    def __init__(
        self,
        market: Literal["binance_spot", "binanceusdm"] = "binanceusdm",
        session: requests.Session | None = None,
    ) -> None:
        self._market = market
        self._http = session or requests.Session()

    def describe(self) -> ConnectorCapability:
        return ConnectorCapability(
            name=f"binance_rest::{self._market}",
            label="Binance 公开 REST (实时)",
            asset_class="crypto_perp" if self._market == "binanceusdm" else "crypto_spot",
            supported_markets=(self._market,),
            supported_intervals=_INTERVALS,
            supported_data_kinds=("ohlcv", "funding_rate"),
            auth_mode="none",
            rate_limit_per_minute=1200,
            realtime=True,
            note="weight-based limit 1200/min；WS 实时见 binance_ws_streamer",
        )

    def health_check(self) -> ConnectorHealth:
        url = f"{self._base()}/api/v3/time" if self._market == "binance_spot" else f"{self._base()}/fapi/v1/time"
        t0 = time.perf_counter()
        try:
            r = self._http.get(url, timeout=5)
            r.raise_for_status()
            latency = (time.perf_counter() - t0) * 1000
            return ConnectorHealth(
                name=f"binance_rest::{self._market}",
                ok=True,
                checked_at_utc=datetime.now(UTC).isoformat(),
                latency_ms=latency,
                detail=f"serverTime={r.json().get('serverTime')}",
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                name=f"binance_rest::{self._market}",
                ok=False,
                checked_at_utc=datetime.now(UTC).isoformat(),
                latency_ms=0.0,
                detail=f"REST error: {exc}",
            )

    def fetch(self, request: FetchRequest) -> FetchResult:
        if request.data_kind == "ohlcv":
            df = self._fetch_klines(request)
        elif request.data_kind == "funding_rate":
            df = self._fetch_funding(request)
        else:
            raise NotImplementedError(f"binance_rest connector 暂不支持 {request.data_kind}")
        # 数据平台 v2：保留宽字段落盘；OHLCV 兼容视图在消费侧用 to_ohlcv_view 投影。
        return make_wide_fetch_result(df, source_name=f"binance_rest::{self._market}")

    def _base(self) -> str:
        return _USDM_BASE if self._market == "binanceusdm" else _SPOT_BASE

    def _fetch_klines(self, request: FetchRequest) -> pl.DataFrame:
        path = "/api/v3/klines" if self._market == "binance_spot" else "/fapi/v1/klines"
        params: dict[str, Any] = {
            "symbol": request.symbol.upper(),
            "interval": request.interval,
            "limit": _MAX_LIMIT,
        }
        if request.start:
            params["startTime"] = int(request.start.replace(tzinfo=UTC).timestamp() * 1000)
        if request.end:
            params["endTime"] = int(request.end.replace(tzinfo=UTC).timestamp() * 1000)
        url = self._base() + path
        rows: list[dict[str, Any]] = []
        cursor = params.get("startTime")
        for _ in range(50):  # safety bound
            if cursor is not None:
                params["startTime"] = cursor
            r = self._http.get(url, params=params, timeout=15)
            if r.status_code == 429 or r.status_code == 418:
                time.sleep(60)
                continue
            r.raise_for_status()
            chunk = r.json()
            if not chunk:
                break
            for k in chunk:
                rows.append(
                    {
                        "ts": datetime.fromtimestamp(k[0] / 1000, tz=UTC),
                        "symbol": request.symbol.upper(),
                        "market": self._market,
                        "interval": request.interval,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "amount": float(k[7]) if len(k) > 7 else 0.0,
                        "trade_count": int(k[8]) if len(k) > 8 else 0,
                        "taker_buy_volume": float(k[9]) if len(k) > 9 else 0.0,
                        "taker_buy_quote_volume": float(k[10]) if len(k) > 10 else 0.0,
                    }
                )
            if len(chunk) < _MAX_LIMIT:
                break
            cursor = int(chunk[-1][0]) + 1
            if request.end and cursor >= int(request.end.replace(tzinfo=UTC).timestamp() * 1000):
                break
        return pl.DataFrame(rows) if rows else pl.DataFrame()

    def _fetch_funding(self, request: FetchRequest) -> pl.DataFrame:
        if self._market != "binanceusdm":
            raise NotImplementedError("funding_rate 仅 USDM 永续")
        url = self._base() + "/fapi/v1/fundingRate"
        params: dict[str, Any] = {"symbol": request.symbol.upper(), "limit": 1000}
        if request.start:
            params["startTime"] = int(request.start.replace(tzinfo=UTC).timestamp() * 1000)
        if request.end:
            params["endTime"] = int(request.end.replace(tzinfo=UTC).timestamp() * 1000)
        r = self._http.get(url, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json()
        if not payload:
            return pl.DataFrame()
        # 数据平台 v2：资金费率独立成表，保留原生列 funding_rate / mark_price，不再伪造成 OHLC。
        rows = [
            {
                "ts": datetime.fromtimestamp(item["fundingTime"] / 1000, tz=UTC),
                "symbol": item["symbol"],
                "market": self._market,
                "interval": "8h",
                "funding_rate": float(item.get("fundingRate", 0)),
                "mark_price": float(item.get("markPrice", 0)),
            }
            for item in payload
        ]
        return pl.DataFrame(rows)


__all__ = ["BinanceRESTConnector"]
