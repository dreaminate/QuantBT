"""Bulk data from data.binance.vision → market/crypto p2-style paths.

Supports daily zips under:
- data/futures/um/daily (USDM)
- data/futures/cm/daily (coin-margined)
- data/spot/daily
- data/option/daily (BVOLIndex, EOHSummary)
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import polars as pl
import requests

from .paths import DATA_ROOT

VISION_BASE = "https://data.binance.vision"
CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[int, str, str, dict[str, Any] | None], None]

# Path prefixes (https://data.binance.vision/?prefix=data/)
UM_DAILY = "data/futures/um/daily"
CM_DAILY = "data/futures/cm/daily"
SPOT_DAILY = "data/spot/daily"
OPTION_DAILY = "data/option/daily"


@dataclass(frozen=True)
class VisionDailySpec:
    """Daily zip under {path_prefix}/{vision_folder}/{symbol}/[interval]/..."""

    vision_folder: str
    file_infix: str
    needs_interval: bool
    disk_kind: str
    path_prefix: str = UM_DAILY


def _build_vision_registry() -> dict[str, VisionDailySpec]:
    r: dict[str, VisionDailySpec] = {
        "vision_klines": VisionDailySpec("klines", "klines", True, "klines", UM_DAILY),
        "vision_agg_trades": VisionDailySpec("aggTrades", "aggTrades", False, "vision_agg_trades", UM_DAILY),
        "vision_trades": VisionDailySpec("trades", "trades", False, "vision_trades", UM_DAILY),
        "vision_mark_price_klines": VisionDailySpec(
            "markPriceKlines", "markPriceKlines", True, "vision_mark_price_klines", UM_DAILY
        ),
        "vision_index_price_klines": VisionDailySpec(
            "indexPriceKlines", "indexPriceKlines", True, "vision_index_price_klines", UM_DAILY
        ),
        "vision_premium_index_klines": VisionDailySpec(
            "premiumIndexKlines", "premiumIndexKlines", True, "vision_premium_index_klines", UM_DAILY
        ),
        "vision_metrics": VisionDailySpec("metrics", "metrics", False, "vision_metrics", UM_DAILY),
        "vision_book_depth": VisionDailySpec("bookDepth", "bookDepth", False, "vision_book_depth", UM_DAILY),
        "vision_um_book_ticker": VisionDailySpec("bookTicker", "bookTicker", False, "vision_um_book_ticker", UM_DAILY),
        "vision_cm_klines": VisionDailySpec("klines", "klines", True, "vision_cm_klines", CM_DAILY),
        "vision_cm_agg_trades": VisionDailySpec("aggTrades", "aggTrades", False, "vision_cm_agg_trades", CM_DAILY),
        "vision_cm_trades": VisionDailySpec("trades", "trades", False, "vision_cm_trades", CM_DAILY),
        "vision_cm_mark_price_klines": VisionDailySpec(
            "markPriceKlines", "markPriceKlines", True, "vision_cm_mark_price_klines", CM_DAILY
        ),
        "vision_cm_index_price_klines": VisionDailySpec(
            "indexPriceKlines", "indexPriceKlines", True, "vision_cm_index_price_klines", CM_DAILY
        ),
        "vision_cm_premium_index_klines": VisionDailySpec(
            "premiumIndexKlines", "premiumIndexKlines", True, "vision_cm_premium_index_klines", CM_DAILY
        ),
        "vision_cm_metrics": VisionDailySpec("metrics", "metrics", False, "vision_cm_metrics", CM_DAILY),
        "vision_cm_book_depth": VisionDailySpec("bookDepth", "bookDepth", False, "vision_cm_book_depth", CM_DAILY),
        "vision_cm_book_ticker": VisionDailySpec("bookTicker", "bookTicker", False, "vision_cm_book_ticker", CM_DAILY),
        "vision_cm_liquidation_snapshot": VisionDailySpec(
            "liquidationSnapshot", "liquidationSnapshot", False, "vision_cm_liquidation_snapshot", CM_DAILY
        ),
        "vision_spot_klines": VisionDailySpec("klines", "klines", True, "vision_spot_klines", SPOT_DAILY),
        "vision_spot_agg_trades": VisionDailySpec("aggTrades", "aggTrades", False, "vision_spot_agg_trades", SPOT_DAILY),
        "vision_spot_trades": VisionDailySpec("trades", "trades", False, "vision_spot_trades", SPOT_DAILY),
        "vision_option_bvol_index": VisionDailySpec("BVOLIndex", "BVOLIndex", False, "vision_option_bvol_index", OPTION_DAILY),
        "vision_option_eoh_summary": VisionDailySpec("EOHSummary", "EOHSummary", False, "vision_option_eoh_summary", OPTION_DAILY),
    }
    return r


VISION_REGISTRY: dict[str, VisionDailySpec] = _build_vision_registry()

# 兼容旧代码：仅 UM 日频（不含 bookTicker）
VISION_DAILY: dict[str, VisionDailySpec] = {
    k: VISION_REGISTRY[k]
    for k in (
        "vision_klines",
        "vision_agg_trades",
        "vision_trades",
        "vision_mark_price_klines",
        "vision_index_price_klines",
        "vision_premium_index_klines",
        "vision_metrics",
        "vision_book_depth",
    )
}

VISION_DAILY_ZIP_KINDS: frozenset[str] = frozenset(VISION_REGISTRY.keys())


VISION_DAILY_KLINE_INTERVALS = frozenset(
    {"1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}
)


def _daterange_inclusive(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _months_inclusive(start: date, end: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    end_ym = (end.year, end.month)
    while (y, m) <= end_ym:
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _daily_zip_url(spec: VisionDailySpec, symbol: str, interval: str | None, day: date) -> str:
    d = day.strftime("%Y-%m-%d")
    sym = quote(symbol, safe="")
    pp = spec.path_prefix.strip("/")
    base = f"{VISION_BASE}/{pp}/{spec.vision_folder}/"
    if spec.needs_interval:
        if not interval:
            raise ValueError(f"{spec.vision_folder} 需要 interval")
        iv = quote(interval, safe="")
        fname = f"{sym}-{iv}-{d}.zip"
        return f"{base}{sym}/{iv}/{fname}"
    fname = f"{sym}-{spec.file_infix}-{d}.zip"
    return f"{base}{sym}/{fname}"


def _monthly_funding_url(symbol: str, year: int, month: int, *, product: str = "um") -> str:
    sym = quote(symbol, safe="")
    ym = f"{year}-{month:02d}"
    fname = f"{sym}-fundingRate-{ym}.zip"
    return f"{VISION_BASE}/data/futures/{product}/monthly/fundingRate/{sym}/{fname}"


def _download_zip(url: str, timeout: int = 120) -> bytes:
    r = requests.get(url, timeout=timeout)
    if r.status_code == 404:
        raise FileNotFoundError(url)
    r.raise_for_status()
    return r.content


def _read_first_csv_from_zip(raw: bytes) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            return pl.DataFrame()
        with zf.open(names[0]) as fh:
            return pl.read_csv(fh, try_parse_dates=False)


def _ms_to_iso_z(ms: Any) -> str:
    try:
        v = int(float(ms))
        return datetime.fromtimestamp(v / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return ""


def _vision_kline_csv_to_ohlcv(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    if df.height == 0:
        return pl.DataFrame(
            schema={
                "timestamp": pl.Utf8,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "close_time": pl.Utf8,
                "symbol": pl.Utf8,
            }
        )
    ren = {c: c.strip().lower().replace(" ", "_") for c in df.columns}
    d = df.rename(ren)
    ot_c = "open_time" if "open_time" in d.columns else d.columns[0]
    rows: list[dict[str, Any]] = []
    for row in d.iter_rows(named=True):
        o = row.get(ot_c)
        ct_raw = row.get("close_time")
        rows.append(
            {
                "timestamp": _ms_to_iso_z(o),
                "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0),
                "low": float(row.get("low") or 0),
                "close": float(row.get("close") or 0),
                "volume": float(row.get("volume") or 0),
                "close_time": _ms_to_iso_z(ct_raw) if ct_raw is not None else "",
                "symbol": symbol,
            }
        )
    return pl.DataFrame(rows)


def _dedupe_time_key(df: pl.DataFrame, time_col: str) -> pl.DataFrame:
    if df.height == 0 or time_col not in df.columns:
        return df
    return df.unique(subset=[time_col], keep="last").sort(time_col)


def _reload_partition_csv(path: Path) -> pl.DataFrame | None:
    """回读已写的 p2 年分区做增量 merge（修多日同年 reload-merge schema bug）。

    `timestamp` / `_ts_iso` 落盘时是 ISO Z 字符串（见 `_ms_to_iso_z`）。回读必须
    `try_parse_dates=False`，否则 polars 把这些字符串列推断成 Datetime('μs','UTC')，
    与新解析的 String timestamp 在 `pl.concat(how="vertical")` 处
    `SchemaError: type String is incompatible with Datetime`（多日同年第 2 天起必崩）。
    保持 String 既修崩、也避免 write_csv 把时间戳重写成非 ISO 格式。
    """
    if not path.exists():
        return None
    return pl.read_csv(path, try_parse_dates=False)


def _merge_by_timestamp_iso(existing: pl.DataFrame | None, new: pl.DataFrame) -> pl.DataFrame:
    if existing is None or existing.height == 0:
        return new
    if new.height == 0:
        return existing
    merged = pl.concat([existing, new], how="vertical")
    return merged.unique(subset=["timestamp"], keep="last").sort("timestamp")


def _p2_year_path(disk_kind: str, interval: str | None, symbol: str, year: int, sub: str = "data.csv") -> Path:
    p = DATA_ROOT / "market" / "crypto" / disk_kind
    if interval:
        p = p / interval
    p = p / "latest" / f"symbol={symbol.upper()}" / f"year={year}" / sub
    return p


def pull_vision_klines_date_range(
    *,
    symbol: str,
    interval: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
    registry_key: str = "vision_klines",
) -> list[str]:
    spec = VISION_REGISTRY[registry_key]
    return _pull_vision_kline_like(
        spec=spec,
        symbol=symbol,
        interval=interval,
        start_day=start_day,
        end_day=end_day,
        progress=progress,
        is_cancelled=is_cancelled,
        stage=registry_key,
    )


def _pull_vision_kline_like(
    *,
    spec: VisionDailySpec,
    symbol: str,
    interval: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None,
    is_cancelled: CancelCheck | None,
    stage: str,
) -> list[str]:
    written: set[str] = set()
    days = _daterange_inclusive(start_day, end_day)
    total = max(len(days), 1)
    for i, day in enumerate(days, start=1):
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        url = _daily_zip_url(spec, symbol, interval, day)
        try:
            raw = _download_zip(url)
        except (FileNotFoundError, requests.RequestException):
            continue
        vdf = _read_first_csv_from_zip(raw)
        frame = _vision_kline_csv_to_ohlcv(vdf, symbol)
        if frame.height == 0:
            continue
        frame = frame.with_columns(pl.col("timestamp").str.slice(0, 4).alias("_yr"))
        for ystr in frame["_yr"].unique().drop_nulls().to_list():
            part = frame.filter(pl.col("_yr") == ystr).drop("_yr")
            try:
                y = int(str(ystr))
            except ValueError:
                continue
            path = _p2_year_path(spec.disk_kind, interval, symbol, y)
            prev = _reload_partition_csv(path)
            merged = _merge_by_timestamp_iso(prev, part)
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.write_csv(path)
            written.add(str(path))
        if progress:
            pct = min(95, int(i / total * 90))
            progress(pct, stage, f"{symbol} {day.isoformat()} ({i}/{total})", {"current_symbol": symbol})
    return sorted(written)


def pull_vision_mark_index_premium_klines(
    *,
    data_kind: str,
    symbol: str,
    interval: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> list[str]:
    if data_kind not in VISION_REGISTRY:
        raise ValueError(data_kind)
    spec = VISION_REGISTRY[data_kind]
    if interval not in VISION_DAILY_KLINE_INTERVALS:
        raise ValueError(f"Vision 日 K 仅支持周期: {sorted(VISION_DAILY_KLINE_INTERVALS)}")
    return _pull_vision_kline_like(
        spec=spec,
        symbol=symbol,
        interval=interval,
        start_day=start_day,
        end_day=end_day,
        progress=progress,
        is_cancelled=is_cancelled,
        stage=data_kind,
    )


def _normalize_agg_trades_vision(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """Binance Vision aggTrades CSV: Aggregate tradeId, Price, Quantity, First, Last, Timestamp, ..."""
    if df.height == 0:
        return pl.DataFrame(
            schema={
                "aggregate_trade_id": pl.Int64,
                "price": pl.Float64,
                "quantity": pl.Float64,
                "timestamp": pl.Utf8,
                "symbol": pl.Utf8,
            }
        )
    cols = list(df.columns)
    lower = [str(c).strip().lower().replace(" ", "_") for c in cols]
    id_col = cols[0]
    price_col = next((cols[i] for i, n in enumerate(lower) if n == "price"), cols[1] if len(cols) > 1 else cols[0])
    qty_col = next((cols[i] for i, n in enumerate(lower) if n == "quantity"), cols[2] if len(cols) > 2 else cols[0])
    ts_col = next((cols[i] for i, n in enumerate(lower) if n == "timestamp"), cols[min(5, len(cols) - 1)])
    out = pl.DataFrame(
        {
            "aggregate_trade_id": df[id_col].cast(pl.Int64, strict=False),
            "price": df[price_col].cast(pl.Float64, strict=False).fill_null(0.0),
            "quantity": df[qty_col].cast(pl.Float64, strict=False).fill_null(0.0),
            "timestamp": df[ts_col].map_elements(lambda x: _ms_to_iso_z(x), return_dtype=pl.Utf8),
            "symbol": pl.lit(symbol),
        }
    )
    return _dedupe_time_key(out, "timestamp")


def _merge_concat_dedupe_cols(existing: pl.DataFrame | None, new: pl.DataFrame, key_cols: list[str]) -> pl.DataFrame:
    if existing is None or existing.height == 0:
        if key_cols and all(c in new.columns for c in key_cols):
            return new.unique(subset=key_cols, keep="last")
        return new
    if new.height == 0:
        return existing
    merged = pl.concat([existing, new], how="vertical")
    if key_cols and all(c in merged.columns for c in key_cols):
        return merged.unique(subset=key_cols, keep="last").sort(key_cols[0])
    return merged.unique(maintain_order=True)


def pull_vision_agg_trades_date_range(
    *,
    symbol: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
    registry_key: str = "vision_agg_trades",
) -> list[str]:
    spec = VISION_REGISTRY[registry_key]
    written: set[str] = set()
    days = _daterange_inclusive(start_day, end_day)
    total = max(len(days), 1)
    for i, day in enumerate(days, start=1):
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        url = _daily_zip_url(spec, symbol, None, day)
        try:
            raw = _download_zip(url)
        except (FileNotFoundError, requests.RequestException):
            continue
        vdf = _read_first_csv_from_zip(raw)
        frame = _normalize_agg_trades_vision(vdf, symbol)
        if frame.height == 0:
            continue
        frame = frame.with_columns(pl.col("timestamp").str.slice(0, 4).alias("_yr"))
        for ystr in frame["_yr"].unique().drop_nulls().to_list():
            part = frame.filter(pl.col("_yr") == ystr).drop("_yr")
            try:
                y = int(str(ystr))
            except ValueError:
                continue
            path = _p2_year_path(spec.disk_kind, None, symbol, y)
            prev = _reload_partition_csv(path)
            keys = [c for c in ("aggregate_trade_id", "timestamp") if c in (prev.columns if prev is not None else part.columns)]
            if not keys:
                keys = ["timestamp"]
            merged = _merge_concat_dedupe_cols(prev, part, keys)
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.write_csv(path)
            written.add(str(path))
        if progress:
            pct = min(95, int(i / total * 90))
            progress(pct, registry_key, f"{symbol} {day.isoformat()} ({i}/{total})", {"current_symbol": symbol})
    return sorted(written)


def _raw_plus_symbol(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    if df.height == 0:
        return pl.DataFrame({"symbol": [symbol]})
    out = df.with_columns(pl.lit(symbol).alias("symbol"))
    return out


def _first_time_col(df: pl.DataFrame) -> str | None:
    for c in df.columns:
        cl = str(c).strip().lower().replace(" ", "_")
        if cl in ("timestamp", "time", "open_time", "fundingtime", "funding_time"):
            return str(c)
    return str(df.columns[0]) if df.columns else None


def pull_vision_trades_or_metrics_or_book_depth(
    *,
    data_kind: str,
    symbol: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> list[str]:
    if data_kind not in VISION_REGISTRY:
        raise ValueError(data_kind)
    spec = VISION_REGISTRY[data_kind]
    written: set[str] = set()
    days = _daterange_inclusive(start_day, end_day)
    total = max(len(days), 1)
    for i, day in enumerate(days, start=1):
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        url = _daily_zip_url(spec, symbol, None, day)
        try:
            raw = _download_zip(url)
        except (FileNotFoundError, requests.RequestException):
            continue
        vdf = _read_first_csv_from_zip(raw)
        if vdf.height == 0:
            continue
        tcol = _first_time_col(vdf)
        frame = _raw_plus_symbol(vdf, symbol)
        if tcol and tcol in frame.columns:
            frame = frame.with_columns(
                pl.col(tcol).map_elements(lambda x: _ms_to_iso_z(x), return_dtype=pl.Utf8).alias("_ts_iso")
            ).with_columns(pl.col("_ts_iso").str.slice(0, 4).alias("_yr"))
        else:
            frame = frame.with_columns(
                pl.lit(str(day.year)).alias("_yr"),
                pl.lit("").cast(pl.Utf8).alias("_ts_iso"),
            )
        for ystr in frame["_yr"].unique().drop_nulls().to_list():
            chunk = frame.filter(pl.col("_yr") == ystr).drop("_yr")
            try:
                y = int(str(ystr))
            except ValueError:
                continue
            path = _p2_year_path(spec.disk_kind, None, symbol, y)
            prev = _reload_partition_csv(path)
            keys = ["_ts_iso"] if "_ts_iso" in chunk.columns and chunk["_ts_iso"].str.len_chars().max() > 0 else []
            merged = _merge_concat_dedupe_cols(prev, chunk, keys)
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.write_csv(path)
            written.add(str(path))
        if progress:
            pct = min(95, int(i / total * 90))
            progress(pct, data_kind, f"{symbol} {day.isoformat()} ({i}/{total})", {"current_symbol": symbol})
    return sorted(written)


def pull_vision_funding_monthly_range(
    *,
    symbol: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
    product: str = "um",
    data_kind: str = "vision_funding_monthly",
) -> list[str]:
    """Monthly fundingRate zips → <disk_kind> / latest / symbol= / year= / data.csv"""
    written: set[str] = set()
    months = _months_inclusive(start_day, end_day)
    total = max(len(months), 1)
    disk_kind = data_kind
    for i, (year, month) in enumerate(months, start=1):
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        url = _monthly_funding_url(symbol, year, month, product=product)
        try:
            raw = _download_zip(url)
        except (FileNotFoundError, requests.RequestException):
            continue
        vdf = _read_first_csv_from_zip(raw)
        if vdf.height == 0:
            continue
        tcol = _first_time_col(vdf)
        frame = _raw_plus_symbol(vdf, symbol)
        if tcol and tcol in frame.columns:
            frame = frame.with_columns(
                pl.col(tcol).map_elements(lambda x: _ms_to_iso_z(x), return_dtype=pl.Utf8).alias("_ts_iso")
            )
        path = _p2_year_path(disk_kind, None, symbol, year)
        prev = _reload_partition_csv(path)
        keys = ["_ts_iso"] if "_ts_iso" in frame.columns else []
        merged = _merge_concat_dedupe_cols(prev, frame, keys)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged.write_csv(path)
        written.add(str(path))
        if progress:
            pct = min(95, int(i / total * 90))
            progress(
                pct,
                data_kind,
                f"{symbol} {year}-{month:02d} ({i}/{total})",
                {"current_symbol": symbol},
            )
    return sorted(written)


def pull_vision_daily_zip_for_data_kind(
    *,
    data_kind: str,
    symbol: str,
    interval: str,
    start_day: date,
    end_day: date,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> list[str]:
    """Dispatch daily Vision zip pulls by registry key (UM/CM/Spot/Option)."""
    spec = VISION_REGISTRY[data_kind]
    if spec.needs_interval:
        if spec.vision_folder == "klines":
            return pull_vision_klines_date_range(
                symbol=symbol,
                interval=interval,
                start_day=start_day,
                end_day=end_day,
                progress=progress,
                is_cancelled=is_cancelled,
                registry_key=data_kind,
            )
        if spec.vision_folder in ("markPriceKlines", "indexPriceKlines", "premiumIndexKlines"):
            return pull_vision_mark_index_premium_klines(
                data_kind=data_kind,
                symbol=symbol,
                interval=interval,
                start_day=start_day,
                end_day=end_day,
                progress=progress,
                is_cancelled=is_cancelled,
            )
        raise RuntimeError(f"未处理的 interval Vision 类型: {data_kind}")
    if spec.vision_folder == "aggTrades":
        return pull_vision_agg_trades_date_range(
            symbol=symbol,
            start_day=start_day,
            end_day=end_day,
            progress=progress,
            is_cancelled=is_cancelled,
            registry_key=data_kind,
        )
    return pull_vision_trades_or_metrics_or_book_depth(
        data_kind=data_kind,
        symbol=symbol,
        start_day=start_day,
        end_day=end_day,
        progress=progress,
        is_cancelled=is_cancelled,
    )
