"""Stooq public daily OHLCV connector.

Stooq exposes no-auth CSV daily bars. This connector keeps it read-only and
normalizes the response into the shared market-data connector contract.
"""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime
from typing import Any

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


_BASE_URL = "https://stooq.com/q/d/l/"
_SUPPORTED_INTERVALS = {"d", "1d", "day", "daily"}


def _stooq_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().lower()
    if not value:
        raise ValueError("stooq connector requires symbol")
    return value


def _stooq_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y%m%d")


def _float_or_zero(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _date_to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    text = str(value or "").strip()
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)


class StooqConnector(DataConnector):
    def __init__(self, session: requests.Session | None = None, base_url: str = _BASE_URL) -> None:
        self._http = session or requests.Session()
        self._base_url = base_url

    def describe(self) -> ConnectorCapability:
        return ConnectorCapability(
            name="stooq",
            label="Stooq public daily bars",
            asset_class="custom",
            supported_markets=("stooq",),
            supported_intervals=("1d",),
            supported_data_kinds=("ohlcv",),
            auth_mode="none",
            rate_limit_per_minute=60,
            realtime=False,
            note="No-auth public CSV daily bars; license/TOS remains a DataSourceAsset responsibility.",
        )

    def health_check(self) -> ConnectorHealth:
        params = {"s": "aapl.us", "i": "d", "d1": "20200102", "d2": "20200102"}
        t0 = time.perf_counter()
        try:
            response = self._http.get(self._base_url, params=params, timeout=5)
            response.raise_for_status()
            ok = "Date,Open,High,Low,Close,Volume" in response.text
            return ConnectorHealth(
                name="stooq",
                ok=ok,
                checked_at_utc=datetime.now(UTC).isoformat(),
                latency_ms=(time.perf_counter() - t0) * 1000,
                detail="daily CSV reachable" if ok else "daily CSV response missing expected header",
            )
        except Exception as exc:  # noqa: BLE001 - health status only.
            return ConnectorHealth(
                name="stooq",
                ok=False,
                checked_at_utc=datetime.now(UTC).isoformat(),
                latency_ms=0.0,
                detail=f"Stooq REST error: {exc}",
            )

    def fetch(self, request: FetchRequest) -> FetchResult:
        if request.data_kind != "ohlcv":
            raise NotImplementedError(f"stooq connector does not support data_kind={request.data_kind}")
        if str(request.interval or "").strip().lower() not in _SUPPORTED_INTERVALS:
            raise NotImplementedError("stooq connector supports daily interval only")

        params: dict[str, Any] = {"s": _stooq_symbol(request.symbol), "i": "d"}
        start = _stooq_date(request.start)
        end = _stooq_date(request.end)
        if start:
            params["d1"] = start
        if end:
            params["d2"] = end
        response = self._http.get(self._base_url, params=params, timeout=15)
        response.raise_for_status()
        frame = self._parse_csv(response.text, symbol=str(request.symbol), interval="1d")
        return make_wide_fetch_result(frame, source_name="stooq")

    def _parse_csv(self, text: str, *, symbol: str, interval: str) -> pl.DataFrame:
        body = str(text or "").strip()
        if not body or body.lower().startswith("no data"):
            return pl.DataFrame()
        raw = pl.read_csv(io.StringIO(body))
        if raw.is_empty():
            return pl.DataFrame()
        required = {"Date", "Open", "High", "Low", "Close", "Volume"}
        missing = required - set(raw.columns)
        if missing:
            raise ValueError(f"stooq CSV missing columns: {sorted(missing)}")
        rows = [
            {
                "ts": _date_to_utc(row["Date"]),
                "symbol": symbol.upper(),
                "market": "stooq",
                "interval": interval,
                "open": _float_or_zero(row["Open"]),
                "high": _float_or_zero(row["High"]),
                "low": _float_or_zero(row["Low"]),
                "close": _float_or_zero(row["Close"]),
                "volume": _float_or_zero(row["Volume"]),
                "amount": 0.0,
            }
            for row in raw.iter_rows(named=True)
        ]
        return pl.DataFrame(rows)


__all__ = ["StooqConnector"]
