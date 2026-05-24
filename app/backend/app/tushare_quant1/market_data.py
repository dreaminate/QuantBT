from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from .project_paths import ProjectPaths


SUPPORTED_MARKETS = {"binanceusdm", "stocks_us", "stocks_cn", "stocks_hk"}
SUPPORTED_INTERVALS = {
    "binanceusdm": {"1m", "5m", "15m", "30m", "1h", "4h", "1d"},
    "stocks_us": {"1m", "5m", "15m", "30m", "1h", "1d"},
    "stocks_cn": {"1m", "5m", "15m", "30m", "1h", "1d"},
    "stocks_hk": {"1m", "5m", "15m", "30m", "1h", "1d"},
}
SUPPORTED_DATA_KINDS = {"ohlcv", "order_book"}
SUPPORTED_FORMATS = {"csv", "parquet"}
MARKET_ALIASES = {
    "binanceusdm": "binanceusdm",
    "binance_usdm": "binanceusdm",
    "stocksus": "stocks_us",
    "stocks_us": "stocks_us",
    "stockscn": "stocks_cn",
    "stocks_cn": "stocks_cn",
    "stockshk": "stocks_hk",
    "stocks_hk": "stocks_hk",
}


@dataclass(frozen=True)
class MarketDataPathInfo:
    resolved_path: str
    exists: bool
    symbol_input: str
    symbol_key: str
    market: str
    interval: str
    data_kind: str
    format: str


def normalize_market(value: str | None) -> str:
    raw = str(value or "binanceusdm").strip().lower().replace("-", "_")
    market = MARKET_ALIASES.get(raw) or MARKET_ALIASES.get(raw.replace("_", ""))
    if market is not None:
        return market
    raise ValueError(f"Unsupported market `{value}`. Supported markets: {sorted(SUPPORTED_MARKETS)}")


def normalize_interval(market: str, value: str | None) -> str:
    interval = str(value or "1h").strip().lower()
    supported = SUPPORTED_INTERVALS.get(market, set())
    if interval not in supported:
        raise ValueError(f"Unsupported interval `{value}` for market `{market}`. Supported intervals: {sorted(supported)}")
    return interval


def normalize_data_kind(value: str | None) -> str:
    data_kind = str(value or "ohlcv").strip().lower()
    if data_kind not in SUPPORTED_DATA_KINDS:
        raise ValueError(f"Unsupported data_kind `{value}`. Supported values: {sorted(SUPPORTED_DATA_KINDS)}")
    return data_kind


def normalize_preferred_format(value: str | None) -> str:
    preferred_format = str(value or "parquet").strip().lower()
    if preferred_format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format `{value}`. Supported values: {sorted(SUPPORTED_FORMATS)}")
    return preferred_format


def normalize_symbol_key(market: str, symbol: str) -> str:
    symbol_input = str(symbol or "").strip().upper()
    if not symbol_input:
        raise ValueError("Symbol is required.")
    if market == "binanceusdm":
        normalized = symbol_input
        if ":" in normalized:
            normalized = normalized.split(":", maxsplit=1)[0]
        if "/" in normalized:
            normalized = normalized.split("/", maxsplit=1)[0]
        if normalized.endswith("USDT") and len(normalized) > 4:
            normalized = normalized[:-4]
        normalized = normalized.strip()
    elif market in {"stocks_us", "stocks_cn", "stocks_hk"}:
        normalized = (
            symbol_input.replace(" ", "")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
        )
    else:
        raise ValueError(f"Unsupported market `{market}`.")
    if not normalized:
        raise ValueError(f"Could not normalize symbol `{symbol}` for market `{market}`.")
    return normalized


def resolve_market_data_path(
    paths: ProjectPaths,
    *,
    market: str | None = None,
    interval: str | None = None,
    symbol: str,
    data_kind: str | None = None,
    preferred_format: str | None = None,
) -> MarketDataPathInfo:
    market_key = normalize_market(market)
    interval_key = normalize_interval(market_key, interval)
    data_kind_key = normalize_data_kind(data_kind)
    format_key = normalize_preferred_format(preferred_format)
    symbol_key = normalize_symbol_key(market_key, symbol)
    resolved = paths.market_data_file(market_key, interval_key, symbol_key, file_format=format_key)
    return MarketDataPathInfo(
        resolved_path=str(resolved),
        exists=resolved.exists(),
        symbol_input=symbol,
        symbol_key=symbol_key,
        market=market_key,
        interval=interval_key,
        data_kind=data_kind_key,
        format=format_key,
    )


def load_market_csv(
    paths: ProjectPaths,
    *,
    market: str | None = None,
    interval: str | None = None,
    symbol: str,
    data_kind: str | None = None,
) -> pl.DataFrame:
    """Load market data for a single symbol.

    ``ohlcv`` uses the legacy flat layout:
    ``data/market/<market>/<interval>/<symbol>.parquet``.

    ``order_book`` uses the dataset layout under:
    ``data/market/<market>/order_book/latest/...``.
    Preferred partition contract is
    ``interval=<interval>/symbol=<symbol>/data.parquet``.
    """
    market_key = normalize_market(market)
    interval_key = normalize_interval(market_key, interval)
    data_kind_key = normalize_data_kind(data_kind)
    symbol_key = normalize_symbol_key(market_key, symbol)
    if data_kind_key != "order_book":
        info = resolve_market_data_path(
            paths,
            market=market_key,
            interval=interval_key,
            symbol=symbol,
            data_kind=data_kind_key,
            preferred_format="parquet",
        )
        if not info.exists:
            raise FileNotFoundError(
                f"Market Parquet `{info.symbol_key}` does not exist for {info.market}/{info.interval}: {info.resolved_path}"
            )
        return pl.read_parquet(info.resolved_path)

    latest_dir = paths.market_dataset_latest_dir(market_key, "order_book")
    candidate_paths: list[Path] = [
        paths.market_dataset_partition_file(market_key, "order_book", f"interval={interval_key}", f"symbol={symbol_key}"),
        paths.market_dataset_partition_file(market_key, "order_book", f"symbol={symbol_key}", f"interval={interval_key}"),
        latest_dir / f"{symbol_key}.parquet",
    ]
    files: list[str] = []
    for candidate in candidate_paths:
        if candidate.exists():
            files.append(str(candidate))
    if not files:
        candidate_dirs = [
            paths.market_dataset_partition_dir(market_key, "order_book", f"interval={interval_key}", f"symbol={symbol_key}"),
            paths.market_dataset_partition_dir(market_key, "order_book", f"symbol={symbol_key}", f"interval={interval_key}"),
        ]
        for directory in candidate_dirs:
            if directory.exists():
                files.extend(str(path) for path in directory.rglob("*.parquet"))
    if not files and latest_dir.exists():
        symbol_marker = f"symbol={symbol_key}".lower()
        interval_marker = f"interval={interval_key}".lower()
        for path in latest_dir.rglob("*.parquet"):
            normalized_parts = [part.lower() for part in path.parts]
            if symbol_marker in normalized_parts and interval_marker in normalized_parts:
                files.append(str(path))
    if not files:
        raise FileNotFoundError(
            f"Order book dataset `{symbol_key}` does not exist for {market_key}/{interval_key}: {latest_dir}"
        )
    return pl.scan_parquet(sorted(set(files)), hive_partitioning=True).collect()


def list_market_symbols(
    paths: ProjectPaths,
    *,
    market: str | None = None,
    interval: str | None = None,
    data_kind: str | None = None,
    preferred_format: str | None = None,
) -> list[str]:
    market_key = normalize_market(market)
    interval_key = normalize_interval(market_key, interval)
    normalize_data_kind(data_kind)
    format_key = normalize_preferred_format(preferred_format)
    directory = paths.market_data_dir(market_key, interval_key)
    if not directory.exists():
        return []
    suffix = f".{format_key}"
    return sorted(path.stem for path in directory.iterdir() if path.is_file() and path.suffix.lower() == suffix)


load_market_ohlcv = load_market_csv
