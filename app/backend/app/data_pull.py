from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import requests

from .paths import DATA_ROOT
from .schemas import BinanceFullPullRequest, DataPullRequest


ProgressCallback = Callable[[int, str, str, dict[str, Any] | None], None]
CancelCheck = Callable[[], bool]

BINANCE_BASE_URL = "https://fapi.binance.com"

MARKET_LABELS = {
    "stocks_cn": "A股",
    "stocks_hk": "港股",
    "stocks_us": "美股",
    "indices_cn": "A股指数",
    "funds_cn": "公募基金",
    "bonds_cn": "债券",
    "binanceusdm": "Binance USDM",
}

DEFAULT_INTERVAL_BY_MARKET = {
    "stocks_cn": "1d",
    "stocks_hk": "1d",
    "stocks_us": "1d",
    "indices_cn": "1d",
    "funds_cn": "1d",
    "bonds_cn": "1d",
    "binanceusdm": "1h",
}

BINANCE_KIND_OPTIONS = [
    "exchange_info",
    "klines",
    # Vision — USDM 日频 (data/futures/um/daily)
    "vision_klines",
    "vision_agg_trades",
    "vision_trades",
    "vision_mark_price_klines",
    "vision_index_price_klines",
    "vision_premium_index_klines",
    "vision_metrics",
    "vision_book_depth",
    "vision_um_book_ticker",
    "vision_funding_monthly",
    # Vision — CM 日频 / 月频 (data/futures/cm)
    "vision_cm_klines",
    "vision_cm_agg_trades",
    "vision_cm_trades",
    "vision_cm_mark_price_klines",
    "vision_cm_index_price_klines",
    "vision_cm_premium_index_klines",
    "vision_cm_metrics",
    "vision_cm_book_depth",
    "vision_cm_book_ticker",
    "vision_cm_liquidation_snapshot",
    "vision_cm_funding_monthly",
    # Vision — 现货日频 (data/spot/daily)
    "vision_spot_klines",
    "vision_spot_agg_trades",
    "vision_spot_trades",
    # Vision — 期权指标日频 (data/option/daily)
    "vision_option_bvol_index",
    "vision_option_eoh_summary",
    # REST FAPI
    "agg_trades",
    "funding_rate",
    "open_interest_hist",
    "taker_buy_sell_volume",
]

INTERVAL_KINDS = {
    "klines",
    "vision_klines",
    "vision_cm_klines",
    "vision_spot_klines",
    "vision_mark_price_klines",
    "vision_index_price_klines",
    "vision_premium_index_klines",
    "vision_cm_mark_price_klines",
    "vision_cm_index_price_klines",
    "vision_cm_premium_index_klines",
    "open_interest_hist",
    "taker_buy_sell_volume",
}

BINANCE_KINDS_NEED_INTERVAL = frozenset(
    {
        "klines",
        "vision_klines",
        "vision_cm_klines",
        "vision_spot_klines",
        "vision_mark_price_klines",
        "vision_index_price_klines",
        "vision_premium_index_klines",
        "vision_cm_mark_price_klines",
        "vision_cm_index_price_klines",
        "vision_cm_premium_index_klines",
        "open_interest_hist",
        "taker_buy_sell_volume",
    }
)

# Vision 日 K zip（与 binance_vision_pull.VISION_DAILY_KLINE_INTERVALS 一致）
VISION_DAILY_KLINE_INTERVAL_KINDS = frozenset(
    {
        "vision_klines",
        "vision_cm_klines",
        "vision_spot_klines",
        "vision_mark_price_klines",
        "vision_index_price_klines",
        "vision_premium_index_klines",
        "vision_cm_mark_price_klines",
        "vision_cm_index_price_klines",
        "vision_cm_premium_index_klines",
    }
)

BINANCE_OI_TAKER_PERIODS = frozenset({"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"})

# data/option/daily 下符号集（与 Vision 目录一致，极少变更）
OPTION_BVOL_VISION_SYMBOLS = ("BTCBVOLUSDT", "ETHBVOLUSDT")
OPTION_EOH_VISION_SYMBOLS = ("BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "XRPUSDT")

DATE_COLUMNS = (
    "timestamp",
    "execution_timestamp",
    "trade_date",
    "ann_date",
    "end_date",
    "cal_date",
    "list_date",
)

def list_markets() -> list[dict[str, Any]]:
    return [{"market": key, "label": value} for key, value in MARKET_LABELS.items()]


def list_data_kind_options(market: str | None = None) -> list[dict[str, Any]]:
    """Tushare 选项与 quant1 一致（积分门槛、接口权限）；Binance 仍为本地静态列表。"""
    files = scan_data_files()
    overview = build_data_overview(files)
    stats_map: dict[tuple[str, str], int] = {}
    for item in overview:
        key = (item["market"], item["data_kind"])
        stats_map[key] = stats_map.get(key, 0) + int(item.get("row_count") or 0)

    results: list[dict[str, Any]] = []
    try:
        from .tushare_quant1.tushare_provider import list_tushare_kind_options as q_tushare_kinds

        for row in q_tushare_kinds(market):
            sc = stats_map.get((row["market"], row["data_kind"]), 0)
            results.append(
                {
                    **row,
                    "stats_count": sc,
                    "label": row.get("label") or row["data_kind"],
                }
            )
    except Exception:
        pass
    if market is None or market == "binanceusdm":
        for data_kind in BINANCE_KIND_OPTIONS:
            sc = stats_map.get(("binanceusdm", data_kind), 0)
            results.append(
                {
                    "market": "binanceusdm",
                    "data_kind": data_kind,
                    "api_name": data_kind,
                    "label": data_kind,
                    "required_points": 0,
                    "effective_points_ceiling": None,
                    "supports_symbols": data_kind != "exchange_info",
                    "supports_date_range": data_kind != "exchange_info",
                    "independent_permission": True,
                    "stats_count": sc,
                    "needs_binance_interval": data_kind in BINANCE_KINDS_NEED_INTERVAL,
                }
            )
    return results


def parse_symbols(raw: list[str]) -> list[str]:
    symbols: list[str] = []
    for item in raw:
        for chunk in str(item).replace("，", ",").split(","):
            value = chunk.strip().upper()
            if value:
                symbols.append(value)
    return list(dict.fromkeys(symbols))


def to_yyyymmdd(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).replace("-", "")[:8]


def maybe_iso(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def detect_date_column(columns: list[str]) -> str | None:
    for column in DATE_COLUMNS:
        if column in columns:
            return column
    return None


def file_path_for_dataset(market: str, data_kind: str, symbol: str | None = None, interval: str | None = None) -> Path:
    base = DATA_ROOT / market / data_kind
    if interval:
        base = base / interval
    if symbol:
        return base / f"{symbol}.csv"
    return base / "dataset.csv"


def crypto_data_root() -> Path:
    return DATA_ROOT / "market" / "crypto"


def file_path_for_crypto_dataset(
    data_kind: str,
    symbol: str | None = None,
    interval: str | None = None,
) -> Path:
    """Binance 落盘统一使用 DATA_ROOT/market/crypto/...（API market 仍为 binanceusdm）。"""
    base = crypto_data_root() / data_kind
    if interval:
        base = base / interval
    if symbol:
        return base / f"{symbol.upper()}.csv"
    return base / "dataset.csv"


def _catalog_inventory_path() -> Path:
    return DATA_ROOT / "catalog" / "inventory.json"


def _load_catalog_inventory() -> dict[str, Any]:
    path = _catalog_inventory_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_path_by_file_id(file_id: str) -> Path | None:
    for item in _load_catalog_inventory().get("files") or []:
        if item.get("file_id") == file_id:
            fp = item.get("file_path")
            if fp:
                p = Path(fp)
                if p.is_file():
                    return p
    return None


def resolve_preview_path(
    *,
    file_id: str | None = None,
    market: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
    data_kind: str | None = None,
) -> Path:
    if file_id:
        resolved = _resolve_path_by_file_id(file_id)
        if resolved is not None:
            root = DATA_ROOT.resolve()
            if not str(resolved.resolve()).startswith(str(root)):
                raise FileNotFoundError(file_id)
            return resolved
        path = (DATA_ROOT / file_id).resolve()
        if not str(path).startswith(str(DATA_ROOT.resolve())):
            raise FileNotFoundError(file_id)
        return path
    if not market or not data_kind:
        raise FileNotFoundError("缺少 file_id 或 market/data_kind")
    if market == "binanceusdm":
        return file_path_for_crypto_dataset(data_kind, symbol=symbol, interval=interval)
    return file_path_for_dataset(market, data_kind, symbol=symbol, interval=interval)


def load_csv(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, try_parse_dates=True)


def save_csv(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(path)


def csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


_TS_COL_CANDIDATES = (
    "date",
    "datetime",
    "timestamp",
    "time",
    "ts",
    "trade_date",
    "ann_date",
    "end_date",
    "publish_date",
    "record_date",
    "cal_date",
    "nav_date",
)


def _detect_timestamp_column(columns: list[str]) -> str | None:
    lowered = {c.lower(): c for c in columns}
    for candidate in _TS_COL_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _normalize_csv_stat_cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    return s or None


def _csv_date_range_stats(path: Path) -> dict[str, Any]:
    """对时间列做 min/max，避免未排序 CSV 首末行误判（如 end 显示为 1999）。"""
    if not path.exists():
        return {"row_count": 0, "start": None, "end": None}
    try:
        lf = pl.scan_csv(str(path))
        columns = lf.collect_schema().names()
    except Exception:
        return {"row_count": csv_row_count(path), "start": None, "end": None}
    ts_col = _detect_timestamp_column(columns)
    if ts_col is None:
        try:
            n = int(pl.scan_csv(str(path)).select(pl.len()).collect().item())
        except Exception:
            n = csv_row_count(path)
        return {"row_count": n, "start": None, "end": None}
    try:
        agg = (
            pl.scan_csv(str(path))
            .select(
                pl.col(ts_col).min().alias("start"),
                pl.col(ts_col).max().alias("end"),
                pl.len().alias("row_count"),
            )
            .collect()
        )
    except Exception:
        return {"row_count": csv_row_count(path), "start": None, "end": None}
    if agg.height == 0:
        return {"row_count": 0, "start": None, "end": None}
    row = agg.to_dicts()[0]
    return {
        "row_count": int(row.get("row_count") or 0),
        "start": _normalize_csv_stat_cell(row.get("start")),
        "end": _normalize_csv_stat_cell(row.get("end")),
    }


def _dataset_file_row_count(path: Path) -> int:
    if path.suffix.lower() == ".parquet":
        try:
            return int(pl.scan_parquet(str(path)).select(pl.len()).collect().item())
        except Exception:
            return 0
    return csv_row_count(path)


def _json_get(url: str, params: dict[str, Any] | None = None) -> Any:
    return _http_get_json(url, params or {})


def _http_get_json(url: str, params: dict[str, Any], timeout: int = 60, max_retries: int = 6) -> Any:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                time.sleep(min(2.0**attempt, 30.0))
                continue
            if response.status_code >= 500:
                time.sleep(min(1.5**attempt, 20.0))
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(min(1.2**attempt, 15.0))
    if last_err:
        raise last_err
    raise RuntimeError("HTTP request failed")


def _filter_frame_dates(frame: pl.DataFrame, start_iso: str | None, end_iso: str | None) -> pl.DataFrame:
    if frame.height == 0:
        return frame
    date_column = detect_date_column(frame.columns)
    if not date_column:
        return frame
    expr = pl.lit(True)
    if start_iso:
        expr = expr & (pl.col(date_column).cast(pl.Utf8).str.slice(0, 10) >= start_iso)
    if end_iso:
        expr = expr & (pl.col(date_column).cast(pl.Utf8).str.slice(0, 10) <= end_iso)
    return frame.filter(expr)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_z_to_ms(text: str) -> int:
    t = str(text).strip()
    if not t:
        return 0
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _day_bounds_ms(start_yyyy_mm_dd: str, end_yyyy_mm_dd: str) -> tuple[int, int]:
    s = datetime.strptime(start_yyyy_mm_dd[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    e = datetime.strptime(end_yyyy_mm_dd[:10], "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(days=1)
    return int(s.timestamp() * 1000), int(e.timestamp() * 1000) - 1


def _max_ts_ms_from_frame(data_kind: str, df: pl.DataFrame) -> int | None:
    del data_kind
    if df.height == 0 or "timestamp" not in df.columns:
        return None
    mx = df["timestamp"].max()
    if mx is None:
        return None
    return _iso_z_to_ms(str(mx))


def _merge_binance_dedupe(data_kind: str, old: pl.DataFrame | None, new: pl.DataFrame) -> pl.DataFrame:
    if old is None or old.height == 0:
        return new
    if new.height == 0:
        return old
    # diagonal_relaxed：容忍新旧文件列集/列类型演进（如 klines 从 8 列升到 12 列），按并集对齐、缺列填 null。
    merged = pl.concat([old, new], how="diagonal_relaxed")
    if data_kind == "agg_trades":
        return merged.unique(subset=["aggregate_trade_id"], keep="last").sort("timestamp")
    if data_kind in ("klines", "funding_rate", "open_interest_hist", "taker_buy_sell_volume"):
        return merged.unique(subset=["timestamp"], keep="last").sort("timestamp")
    return merged


def _window_binance_fapi(
    payload: DataPullRequest,
    data_kind: str,
    target_path: Path,
) -> tuple[int, int] | None:
    now_ms = _now_ms()
    incremental = payload.refresh_mode == "incremental"
    has_file = target_path.exists() and csv_row_count(target_path) > 0

    if incremental and has_file:
        old = load_csv(target_path)
        mx = _max_ts_ms_from_frame(data_kind, old)
        if mx is None:
            lo = 1568563200000
        else:
            lo = mx + 1
        if payload.full_history:
            hi = now_ms
        elif payload.start and payload.end:
            _, hi = _day_bounds_ms(str(payload.start), str(payload.end))
            hi = min(hi, now_ms)
        else:
            hi = now_ms
        if lo > hi:
            return None
        return (lo, hi)

    if payload.full_history:
        lo, hi = 1568563200000, now_ms
    elif payload.start and payload.end:
        lo, hi = _day_bounds_ms(str(payload.start), str(payload.end))
        hi = min(hi, now_ms)
    else:
        lo, hi = 1568563200000, now_ms
    if lo > hi:
        return None
    return (lo, hi)


def _fetch_klines_paginated(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    is_cancelled: CancelCheck | None,
) -> pl.DataFrame:
    rows_raw: list[Any] = []
    cur = start_ms
    while cur <= end_ms:
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        batch = _http_get_json(
            f"{BINANCE_BASE_URL}/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": 1500, "startTime": cur, "endTime": end_ms},
        )
        if not batch:
            break
        rows_raw.extend(batch)
        last_open = int(batch[-1][0])
        if last_open >= end_ms or len(batch) < 1500:
            break
        cur = last_open + 1
        time.sleep(0.06)
    return _normalize_binance_rows("klines", rows_raw, symbol=symbol)


def _fetch_agg_trades_paginated(
    symbol: str,
    start_ms: int,
    end_ms: int,
    is_cancelled: CancelCheck | None,
) -> pl.DataFrame:
    rows_raw: list[Any] = []
    cur = start_ms
    while cur <= end_ms:
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        batch = _http_get_json(
            f"{BINANCE_BASE_URL}/fapi/v1/aggTrades",
            {"symbol": symbol, "limit": 1000, "startTime": cur, "endTime": end_ms},
        )
        if not batch:
            break
        rows_raw.extend(batch)
        last_t = int(batch[-1]["T"])
        if last_t >= end_ms or len(batch) < 1000:
            break
        cur = last_t + 1
        time.sleep(0.06)
    return _normalize_binance_rows("agg_trades", rows_raw, symbol=symbol)


def _fetch_funding_paginated(
    symbol: str,
    start_ms: int,
    end_ms: int,
    is_cancelled: CancelCheck | None,
) -> pl.DataFrame:
    rows_raw: list[Any] = []
    cur = start_ms
    while cur <= end_ms:
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        batch = _http_get_json(
            f"{BINANCE_BASE_URL}/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": 1000, "startTime": cur, "endTime": end_ms},
        )
        if not batch:
            break
        rows_raw.extend(batch)
        last_ft = int(batch[-1]["fundingTime"])
        if last_ft >= end_ms or len(batch) < 1000:
            break
        cur = last_ft + 1
        time.sleep(0.06)
    return _normalize_binance_rows("funding_rate", rows_raw, symbol=symbol)


def _fetch_open_interest_paginated(
    symbol: str,
    period: str,
    start_ms: int,
    end_ms: int,
    is_cancelled: CancelCheck | None,
) -> pl.DataFrame:
    rows_raw: list[Any] = []
    cur = start_ms
    while cur <= end_ms:
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        batch = _http_get_json(
            f"{BINANCE_BASE_URL}/futures/data/openInterestHist",
            {
                "symbol": symbol,
                "period": period,
                "limit": 500,
                "startTime": cur,
                "endTime": end_ms,
            },
        )
        if not batch:
            break
        rows_raw.extend(batch)
        last_ts = int(batch[-1]["timestamp"])
        if last_ts >= end_ms or len(batch) < 500:
            break
        cur = last_ts + 1
        time.sleep(0.08)
    return _normalize_binance_rows("open_interest_hist", rows_raw, symbol=symbol)


def _fetch_taker_paginated(
    symbol: str,
    period: str,
    start_ms: int,
    end_ms: int,
    is_cancelled: CancelCheck | None,
) -> pl.DataFrame:
    rows_raw: list[Any] = []
    cur = start_ms
    while cur <= end_ms:
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        batch = _http_get_json(
            f"{BINANCE_BASE_URL}/futures/data/takerBuySellVol",
            {
                "symbol": symbol,
                "period": period,
                "limit": 500,
                "startTime": cur,
                "endTime": end_ms,
            },
        )
        if not batch:
            break
        rows_raw.extend(batch)
        last_ts = int(batch[-1]["timestamp"])
        if last_ts >= end_ms or len(batch) < 500:
            break
        cur = last_ts + 1
        time.sleep(0.08)
    return _normalize_binance_rows("taker_buy_sell_volume", rows_raw, symbol=symbol)


def validate_data_pull_request(payload: DataPullRequest) -> None:
    from .symbol_pools import load_symbol_pool_symbols

    options = [k for k in list_data_kind_options(payload.market) if k["data_kind"] == payload.data_kind]
    if not options:
        raise RuntimeError(f"Unsupported data_kind for this market: {payload.data_kind}")
    meta = options[0]
    supports_symbols = bool(meta.get("supports_symbols", True))
    supports_date_range = bool(meta.get("supports_date_range", True))
    if payload.symbol_mode == "stock_pool":
        if not payload.stock_pool_id:
            raise RuntimeError("pool_id is required when symbol_source is pool.")
        syms = load_symbol_pool_symbols(payload.stock_pool_id, payload.market)
        if not syms:
            raise RuntimeError("Selected pool has no symbols.")
    elif payload.symbol_mode == "preset":
        if not (payload.preset_name or "").strip():
            raise RuntimeError("preset_name is required when symbol_source is preset.")
    elif payload.symbol_mode == "manual" and supports_symbols:
        if not parse_symbols(payload.symbols):
            raise RuntimeError("At least one symbol is required for manual input.")
    if not payload.full_history and supports_date_range:
        if not payload.start or not payload.end:
            raise RuntimeError("Start and End are required unless pulling full available history.")
        if str(payload.start) > str(payload.end):
            raise RuntimeError("Start must be on or before End.")
    if payload.market == "binanceusdm" and str(payload.data_kind).startswith("vision_"):
        if payload.full_history or not payload.start or not payload.end:
            raise RuntimeError("Vision 数据需填写开始与结束日期（不支持无日期 full history）。")
    if payload.market == "binanceusdm" and payload.data_kind in ("open_interest_hist", "taker_buy_sell_volume"):
        iv = payload.interval or DEFAULT_INTERVAL_BY_MARKET["binanceusdm"]
        if iv not in BINANCE_OI_TAKER_PERIODS:
            raise RuntimeError(
                f"open_interest_hist / taker_buy_sell_volume 的 period 必须是: {sorted(BINANCE_OI_TAKER_PERIODS)}"
            )
    if payload.market == "binanceusdm" and payload.data_kind in VISION_DAILY_KLINE_INTERVAL_KINDS:
        from .binance_vision_pull import VISION_DAILY_KLINE_INTERVALS

        iv = payload.interval or DEFAULT_INTERVAL_BY_MARKET["binanceusdm"]
        if iv not in VISION_DAILY_KLINE_INTERVALS:
            raise RuntimeError(f"该 Vision 日 K 周期必须是: {sorted(VISION_DAILY_KLINE_INTERVALS)}")


def pull_tushare_dataset(
    payload: DataPullRequest,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> dict[str, Any]:
    """与 quant1 相同的 Tushare 拉取：TokenPool、批次、并发、parquet、catalog。"""
    from .tushare_quant1.tushare_provider import run_tushare_data_pull
    from .tushare_quant1 import qb_project_paths

    paths = qb_project_paths()

    def progress_adapter(stage_key: str, message: str, *, percent: int | None = None, stats: dict[str, Any] | None = None) -> None:
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        if progress:
            pct = max(0, min(100, int(percent or 0)))
            progress(pct, stage_key, message, stats or {})

    start = None if payload.full_history else to_yyyymmdd(payload.start)
    end = None if payload.full_history else to_yyyymmdd(payload.end)
    refresh = "incremental" if payload.refresh_mode == "incremental" else "full"

    result = run_tushare_data_pull(
        paths,
        market=payload.market,
        data_kind=payload.data_kind,
        symbol_mode=payload.symbol_mode,
        symbols=payload.symbols or [],
        stock_pool_id=payload.stock_pool_id,
        preset_name=payload.preset_name,
        start=start,
        end=end,
        refresh_mode=refresh,
        full_history=payload.full_history,
        progress_callback=progress_adapter,
    )
    result = dict(result)
    result["written_files"] = list(result.get("written_file_paths") or [])
    return result


def _normalize_binance_rows(data_kind: str, rows: Any, symbol: str | None = None) -> pl.DataFrame:
    if data_kind == "exchange_info":
        payload = rows.get("symbols", []) if isinstance(rows, dict) else []
        return pl.DataFrame(
            [
                {
                    "symbol": item.get("symbol"),
                    "status": item.get("status"),
                    "base_asset": item.get("baseAsset"),
                    "quote_asset": item.get("quoteAsset"),
                }
                for item in payload
            ]
        )
    if data_kind == "klines":
        return pl.DataFrame(
            [
                {
                    "timestamp": datetime.fromtimestamp(item[0] / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "close_time": datetime.fromtimestamp(item[6] / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                    # 数据平台 v2：保留 12 列 kline 的全部字段（成交额/笔数/主动买入量额）
                    "quote_volume": float(item[7]) if len(item) > 7 else 0.0,
                    "trade_count": int(item[8]) if len(item) > 8 else 0,
                    "taker_buy_volume": float(item[9]) if len(item) > 9 else 0.0,
                    "taker_buy_quote_volume": float(item[10]) if len(item) > 10 else 0.0,
                    "symbol": symbol,
                }
                for item in rows
            ]
        )
    if data_kind == "agg_trades":
        return pl.DataFrame(
            [
                {
                    "aggregate_trade_id": item.get("a"),
                    "price": float(item.get("p", 0)),
                    "quantity": float(item.get("q", 0)),
                    "timestamp": datetime.fromtimestamp(item.get("T", 0) / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                    "is_buyer_maker": bool(item.get("m")),
                    "symbol": symbol,
                }
                for item in rows
            ]
        )
    if data_kind == "funding_rate":
        return pl.DataFrame(
            [
                {
                    "symbol": item.get("symbol"),
                    "funding_rate": float(item.get("fundingRate", 0)),
                    "mark_price": float(item.get("markPrice", 0)),
                    "timestamp": datetime.fromtimestamp(item.get("fundingTime", 0) / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                }
                for item in rows
            ]
        )
    if data_kind == "open_interest_hist":
        return pl.DataFrame(
            [
                {
                    "symbol": item.get("symbol"),
                    "sum_open_interest": float(item.get("sumOpenInterest", 0)),
                    "sum_open_interest_value": float(item.get("sumOpenInterestValue", 0)),
                    "timestamp": datetime.fromtimestamp(item.get("timestamp", 0) / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                }
                for item in rows
            ]
        )
    if data_kind == "taker_buy_sell_volume":
        return pl.DataFrame(
            [
                {
                    "symbol": symbol,
                    "buy_sell_ratio": float(item.get("buySellRatio", 0)),
                    "buy_vol": float(item.get("buyVol", 0)),
                    "sell_vol": float(item.get("sellVol", 0)),
                    "timestamp": datetime.fromtimestamp(item.get("timestamp", 0) / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                }
                for item in rows
            ]
        )
    return pl.DataFrame()


def _resolve_usdt_perpetual_trading_symbols() -> list[str]:
    payload = _json_get(f"{BINANCE_BASE_URL}/fapi/v1/exchangeInfo")
    out: list[str] = []
    for item in payload.get("symbols", []):
        if str(item.get("contractType", "")).upper() != "PERPETUAL":
            continue
        if str(item.get("quoteAsset", "")).upper() != "USDT":
            continue
        if str(item.get("status", "")).upper() != "TRADING":
            continue
        sym = item.get("symbol")
        if sym:
            out.append(str(sym).upper())
    return sorted(out)


def _resolve_cm_perpetual_trading_symbols() -> list[str]:
    payload = _json_get("https://dapi.binance.com/dapi/v1/exchangeInfo")
    out: list[str] = []
    for item in payload.get("symbols", []):
        if str(item.get("contractStatus", "")).upper() != "TRADING":
            continue
        if str(item.get("contractType", "")).upper() != "PERPETUAL":
            continue
        sym = item.get("symbol")
        if sym:
            out.append(str(sym).upper())
    return sorted(out)


def _resolve_spot_usdt_trading_symbols() -> list[str]:
    payload = _json_get("https://api.binance.com/api/v3/exchangeInfo")
    out: list[str] = []
    for item in payload.get("symbols", []):
        if str(item.get("status", "")).upper() != "TRADING":
            continue
        if str(item.get("quoteAsset", "")).upper() != "USDT":
            continue
        sym = item.get("symbol")
        if sym:
            out.append(str(sym).upper())
    return sorted(out)


def _resolve_symbols_for_binance_pull(data_kind: str) -> list[str]:
    if data_kind == "vision_option_bvol_index":
        return list(OPTION_BVOL_VISION_SYMBOLS)
    if data_kind == "vision_option_eoh_summary":
        return list(OPTION_EOH_VISION_SYMBOLS)
    if data_kind.startswith("vision_cm_"):
        return _resolve_cm_perpetual_trading_symbols()
    if data_kind.startswith("vision_spot_"):
        return _resolve_spot_usdt_trading_symbols()
    return _resolve_usdt_perpetual_trading_symbols()


def pull_binance_dataset(
    payload: DataPullRequest,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> dict[str, Any]:
    from .binance_vision_pull import (
        VISION_DAILY_ZIP_KINDS,
        pull_vision_daily_zip_for_data_kind,
        pull_vision_funding_monthly_range,
    )

    if payload.symbol_mode == "stock_pool":
        from .symbol_pools import load_symbol_pool_symbols

        symbols = load_symbol_pool_symbols(payload.stock_pool_id or "", payload.market)
    elif payload.symbol_mode == "all" and payload.data_kind not in ("exchange_info",):
        symbols = _resolve_symbols_for_binance_pull(payload.data_kind)
    else:
        symbols = parse_symbols(payload.symbols)

    if payload.data_kind == "exchange_info":
        raw = _json_get(f"{BINANCE_BASE_URL}/fapi/v1/exchangeInfo")
        frame = _normalize_binance_rows(payload.data_kind, raw)
        target = file_path_for_crypto_dataset("exchange_info")
        save_csv(frame, target)
        if progress:
            progress(100, "complete", "Binance 拉取完成", {"written_files": 1})
        return {"written_files": [str(target)]}

    interval = payload.interval or DEFAULT_INTERVAL_BY_MARKET["binanceusdm"]

    vision_kind = payload.data_kind
    if vision_kind in VISION_DAILY_ZIP_KINDS:
        start_d = date.fromisoformat(str(payload.start)[:10])
        end_d = date.fromisoformat(str(payload.end)[:10])
        vision_written: set[str] = set()
        for index, symbol in enumerate(symbols, start=1):
            if is_cancelled and is_cancelled():
                raise RuntimeError("任务已取消。")
            if progress:
                pct = min(95, math.floor(index / max(len(symbols), 1) * 90))
                progress(pct, vision_kind, f"Vision {vision_kind} {symbol} ({index}/{len(symbols)})", {"current_symbol": symbol})
            paths = pull_vision_daily_zip_for_data_kind(
                data_kind=vision_kind,
                symbol=symbol,
                interval=interval,
                start_day=start_d,
                end_day=end_d,
                progress=progress,
                is_cancelled=is_cancelled,
            )
            vision_written.update(paths)
        out_vis = sorted(vision_written)
        if progress:
            progress(100, "complete", f"Vision {vision_kind} 完成", {"written_files": len(out_vis)})
        return {"written_files": out_vis}

    if payload.data_kind in ("vision_funding_monthly", "vision_cm_funding_monthly"):
        start_d = date.fromisoformat(str(payload.start)[:10])
        end_d = date.fromisoformat(str(payload.end)[:10])
        product = "um" if payload.data_kind == "vision_funding_monthly" else "cm"
        fund_written: set[str] = set()
        for index, symbol in enumerate(symbols, start=1):
            if is_cancelled and is_cancelled():
                raise RuntimeError("任务已取消。")
            if progress:
                pct = min(95, math.floor(index / max(len(symbols), 1) * 90))
                progress(
                    pct,
                    payload.data_kind,
                    f"Vision funding {symbol} ({index}/{len(symbols)})",
                    {"current_symbol": symbol},
                )
            fund_written.update(
                pull_vision_funding_monthly_range(
                    symbol=symbol,
                    start_day=start_d,
                    end_day=end_d,
                    progress=progress,
                    is_cancelled=is_cancelled,
                    product=product,
                    data_kind=payload.data_kind,
                )
            )
        out_f = sorted(fund_written)
        if progress:
            progress(100, "complete", "Vision fundingRate 完成", {"written_files": len(out_f)})
        return {"written_files": out_f}

    written_files: list[str] = []
    start_iso = maybe_iso(to_yyyymmdd(payload.start)) if payload.start else None
    end_iso = maybe_iso(to_yyyymmdd(payload.end)) if payload.end else None

    for index, symbol in enumerate(symbols, start=1):
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        if progress:
            pct = min(95, math.floor(index / max(len(symbols), 1) * 90))
            progress(pct, "pull_binance", f"正在拉取 {symbol} ({index}/{len(symbols)})", {"current_symbol": symbol})

        path_interval: str | None = interval
        if payload.data_kind == "funding_rate":
            path_interval = None
        elif payload.data_kind in ("klines", "open_interest_hist", "taker_buy_sell_volume"):
            path_interval = interval

        target = file_path_for_crypto_dataset(
            payload.data_kind,
            symbol=symbol,
            interval=path_interval,
        )

        win = _window_binance_fapi(payload, payload.data_kind, target)
        if win is None:
            continue
        lo, hi = win

        if payload.data_kind == "klines":
            new_frame = _fetch_klines_paginated(symbol, interval, lo, hi, is_cancelled)
        elif payload.data_kind == "agg_trades":
            new_frame = _fetch_agg_trades_paginated(symbol, lo, hi, is_cancelled)
        elif payload.data_kind == "funding_rate":
            new_frame = _fetch_funding_paginated(symbol, lo, hi, is_cancelled)
        elif payload.data_kind == "open_interest_hist":
            new_frame = _fetch_open_interest_paginated(symbol, interval, lo, hi, is_cancelled)
        elif payload.data_kind == "taker_buy_sell_volume":
            new_frame = _fetch_taker_paginated(symbol, interval, lo, hi, is_cancelled)
        else:
            raise RuntimeError(f"暂不支持的 Binance data_kind: {payload.data_kind}")

        new_frame = _filter_frame_dates(new_frame, start_iso, end_iso)

        if payload.refresh_mode == "incremental" and target.exists() and csv_row_count(target) > 0:
            old_frame = load_csv(target)
            merged = _merge_binance_dedupe(payload.data_kind, old_frame, new_frame)
            save_csv(merged, target)
        else:
            save_csv(new_frame, target)
        written_files.append(str(target))

    if progress:
        progress(100, "complete", "Binance 拉取完成", {"written_files": len(written_files)})
    return {"written_files": written_files}


# ============================================================
# C-S11-PIT-ENFORCE · 真 data-pull 路径 confirmatory PIT 硬门（GOAL §11 line1759）
# ============================================================
# GOAL §11 可证伪验收：「无 PIT 语义的数据进入 confirmatory validation → 拒」。
# 现状死接线：execute_data_pull 不带 use_context、不校验 PIT —— confirmatory run 可拉无
# known_at/effective_at/bitemporal 语义的数据进证实性验证 = 前视（look-ahead 红线，RULES.project §5）。
# 本门补这一段：标 confirmatory 的拉取，其声明的每条数据集语义必须过 market_data_contract 的
# CONFIRMATORY_VALIDATION 校验（带 known_at/effective_at/PIT 规则）；否则【在任何拉取/落盘之前】
# fail-closed raise —— 不静默放行、不假装过滤。
#
# 边界（扩展不替换·向后兼容·诚实不假装）：
# - **单一源复用** research_os.market_data_contract.validate_dataset_semantics（PIT 契约校验器），
#   绝不另造第二套 PIT 规则（懒导入，沿用本模块既有 lazy-import 惯例，免模块装载期耦合）。
# - use_context 缺省 None / research / backtest / paper / ... → advisory no-op（既有拉取一字不改）。
# - 零声明数据集 + confirmatory → 拒（无可核验 = fail-closed；绝不放行「不可核验」数据进 confirmatory，
#   守 HONESTY：库超前数据时拒不可核验，不假装 pass）。
# - 诚实限界：本门校验【声明的 PIT 语义 ref 在场】，不解析 ref 到真 schema（那是 SA-1 ref-resolution
#   另卡）；物理 known_at 轴的强制在 field_catalog.load_panel / training.codegen 的取数层（互补）。

# confirmatory PIT 门是否默认强制。单点可逆：中心整合跑全量后若某 confirmatory 拉取路径破基线 →
# 翻 False 全局回退 advisory（无需改门 / 改调用点）。enforce=True 是 §11 终态（GOAL line1759「拒」）。
ENFORCE_DATA_PULL_CONFIRMATORY_PIT = True


class ConfirmatoryPITRejected(RuntimeError):
    """confirmatory 数据拉取缺 PIT 语义（known_at/effective_at/bitemporal）→ 拒（look-ahead 红线·GOAL §11 line1759）。"""


def _pit_context_value(use_context: Any) -> str:
    """归一 use_context（Enum/str/None）→ 字符串值（单一源 = ValidationUseContext 的 .value）。"""
    if use_context is None:
        return ""
    return str(getattr(use_context, "value", use_context))


def enforce_confirmatory_pit(
    use_context: Any,
    datasets: Iterable[Any] | None,
    *,
    enforce: bool = ENFORCE_DATA_PULL_CONFIRMATORY_PIT,
    context: str = "data pull",
) -> list[Any]:
    """confirmatory 数据拉取的 PIT 硬门（复用 validate_dataset_semantics·绝不重造 PIT 规则）。

    confirmatory 且 enforce → 每条数据集语义必须过 CONFIRMATORY_VALIDATION 校验（带
    known_at/effective_at/PIT 规则）；任一缺 → raise ``ConfirmatoryPITRejected``。零声明数据集亦拒
    （无可核验 = fail-closed）。非 confirmatory / enforce=False → advisory no-op（返 ``[]``，向后兼容）。

    ``datasets`` 元素可为 ``DatasetSemanticsRecord`` 或其 ``to_dict()`` 形态（经
    ``dataset_semantics_record_from_dict`` 解析）。返回各数据集的 ``MarketDataDecision``（均放行时）。
    """
    from .research_os.market_data_contract import (  # 单一 PIT 契约源（复用·懒导入免装载期耦合）
        DatasetSemanticsRecord,
        ValidationUseContext,
        dataset_semantics_record_from_dict,
        validate_dataset_semantics,
    )

    confirmatory = ValidationUseContext.CONFIRMATORY_VALIDATION.value
    if not enforce or _pit_context_value(use_context) != confirmatory:
        return []  # 非 confirmatory / 门未启用：不强制（向后兼容·不误伤探索与既有拉取）

    records = [
        rec if isinstance(rec, DatasetSemanticsRecord) else dataset_semantics_record_from_dict(rec)
        for rec in (datasets or [])
    ]
    if not records:
        raise ConfirmatoryPITRejected(
            f"[{context}] confirmatory 数据拉取未声明任何数据集语义 —— 无 PIT(known_at/effective_at) 可核验，"
            "fail-closed 拒（绝不放行不可核验数据进 confirmatory validation·GOAL §11 line1759）"
        )

    decisions: list[Any] = []
    violations: list[str] = []
    for rec in records:
        decision = validate_dataset_semantics(rec, use_context=confirmatory)
        decisions.append(decision)
        if not decision.accepted:
            violations.extend(f"{rec.dataset_ref}:{v.code}" for v in decision.violations)
    if violations:
        raise ConfirmatoryPITRejected(
            f"[{context}] confirmatory 数据缺 PIT 语义 → 拒（look-ahead 红线·GOAL §11 line1759）: "
            + "; ".join(violations)
        )
    return decisions


def execute_data_pull(
    payload: DataPullRequest,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
    *,
    use_context: Any = None,
    dataset_semantics: Iterable[Any] | None = None,
) -> dict[str, Any]:
    # C-S11-PIT-ENFORCE：confirmatory run 在【任何拉取/落盘之前】先过 PIT 硬门（拒非 PIT·look-ahead 红线）。
    # 缺省 use_context=None → no-op，既有调用方（jobs.py 等）行为逐字不变（向后兼容）。
    enforce_confirmatory_pit(
        use_context,
        dataset_semantics,
        context=f"data pull {payload.market}/{payload.data_kind}",
    )
    validate_data_pull_request(payload)
    if progress:
        progress(1, "prepare", "准备任务参数...", {"market": payload.market, "data_kind": payload.data_kind})
    if payload.market == "binanceusdm":
        return pull_binance_dataset(payload, progress=progress, is_cancelled=is_cancelled)
    return pull_tushare_dataset(payload, progress=progress, is_cancelled=is_cancelled)


def _data_request_for_binance_full_kind(
    data_kind: str,
    *,
    vision_start: str,
    vision_end: str,
    default_interval: str,
) -> DataPullRequest:
    if data_kind == "exchange_info":
        return DataPullRequest(
            market="binanceusdm",
            data_kind=data_kind,
            symbol_mode="all",
            symbols=[],
            refresh_mode="full",
            full_history=False,
        )
    if str(data_kind).startswith("vision_"):
        iv = default_interval if data_kind in BINANCE_KINDS_NEED_INTERVAL else None
        return DataPullRequest(
            market="binanceusdm",
            data_kind=data_kind,
            symbol_mode="all",
            symbols=[],
            refresh_mode="full",
            full_history=False,
            start=vision_start,
            end=vision_end,
            interval=iv,
        )
    iv = default_interval if data_kind in BINANCE_KINDS_NEED_INTERVAL else None
    return DataPullRequest(
        market="binanceusdm",
        data_kind=data_kind,
        symbol_mode="all",
        symbols=[],
        refresh_mode="full",
        full_history=True,
        interval=iv,
    )


def execute_binance_full_pull(
    options: BinanceFullPullRequest | None = None,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> dict[str, Any]:
    """按 BINANCE_KIND_OPTIONS 顺序依次全量拉取（REST 用 full_history；Vision 用起止日期）。"""
    opt = options or BinanceFullPullRequest()
    end = opt.vision_end
    if not end:
        end = datetime.now(tz=UTC).date().isoformat()
    kinds = list(BINANCE_KIND_OPTIONS)
    n = len(kinds)
    written_all: list[str] = []
    per_kind: list[dict[str, Any]] = []
    if progress:
        progress(0, "prepare", f"一键全量：共 {n} 类", {"total_kinds": n})
    for i, kind in enumerate(kinds):
        if is_cancelled and is_cancelled():
            raise RuntimeError("任务已取消。")
        lo = int(i * 100 / n)
        hi = int((i + 1) * 100 / n)

        def seg_progress(pct: int, stage: str, message: str, stats: dict[str, Any] | None = None) -> None:
            if not progress:
                return
            seg = lo + int(max(0, min(100, pct)) * (hi - lo) / 100)
            st = dict(stats or {})
            st.setdefault("current_kind", kind)
            st.setdefault("kind_index", i + 1)
            st.setdefault("total_kinds", n)
            progress(seg, stage, f"[{i + 1}/{n} {kind}] {message}", st)

        sub = _data_request_for_binance_full_kind(
            kind,
            vision_start=opt.vision_start,
            vision_end=end,
            default_interval=opt.default_interval,
        )
        out = execute_data_pull(sub, progress=seg_progress, is_cancelled=is_cancelled)
        files = list(out.get("written_files") or [])
        written_all.extend(files)
        per_kind.append({"data_kind": kind, "written_files": files})
    if progress:
        progress(100, "complete", "一键全量完成", {"total_kinds": n})
    return {"written_files": written_all, "per_kind": per_kind, "kinds_total": n}


def _scan_csv_entry(relative: Path, path: Path) -> dict[str, Any] | None:
    parts = list(relative.parts)
    if len(parts) < 2:
        return None
    if parts[0] == "market" and len(parts) >= 3 and parts[1] == "crypto":
        if "latest" in parts:
            try:
                li = parts.index("latest")
            except ValueError:
                li = -1
            if li >= 3:
                data_kind = parts[2]
                interval = parts[3] if li >= 4 else None
                sym_raw = next((p for p in parts if p.startswith("symbol=")), "")
                symbol_key = sym_raw.split("=", 1)[1] if sym_raw else None
                return {
                    "file_id": relative.as_posix(),
                    "market": "binanceusdm",
                    "interval": interval,
                    "data_kind": data_kind,
                    "symbol_key": symbol_key,
                    "partition": interval or symbol_key or "dataset",
                    "formats": ["csv"],
                    "preferred_format": "csv",
                    "file_path": str(path),
                    "row_count": csv_row_count(path),
                    "start": None,
                    "end": None,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
                }
        if len(parts) == 4 and path.suffix.lower() == ".csv" and path.name != "dataset.csv":
            return {
                "file_id": relative.as_posix(),
                "market": "binanceusdm",
                "interval": None,
                "data_kind": parts[2],
                "symbol_key": path.stem,
                "partition": path.stem,
                "formats": ["csv"],
                "preferred_format": "csv",
                "file_path": str(path),
                "row_count": csv_row_count(path),
                "start": None,
                "end": None,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
            }
        if len(parts) >= 5 and path.suffix.lower() == ".csv":
            return {
                "file_id": relative.as_posix(),
                "market": "binanceusdm",
                "interval": parts[3],
                "data_kind": parts[2],
                "symbol_key": path.stem if path.name != "dataset.csv" else None,
                "partition": parts[3] if len(parts) >= 4 else path.stem,
                "formats": ["csv"],
                "preferred_format": "csv",
                "file_path": str(path),
                "row_count": csv_row_count(path),
                "start": None,
                "end": None,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
            }
        if len(parts) >= 4 and path.name == "dataset.csv":
            return {
                "file_id": relative.as_posix(),
                "market": "binanceusdm",
                "interval": None,
                "data_kind": parts[2],
                "symbol_key": None,
                "partition": "dataset",
                "formats": ["csv"],
                "preferred_format": "csv",
                "file_path": str(path),
                "row_count": csv_row_count(path),
                "start": None,
                "end": None,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
            }
        return None
    # quant1 布局：data/market/<market>/<data_kind>/latest/...（A 股/港股等），此前误 return None 导致浏览器扫不到落盘文件
    if parts[0] == "market" and len(parts) >= 5 and parts[1] != "crypto" and parts[3] == "latest":
        market_name = parts[1]
        data_kind = parts[2]
        symbol_key: str | None = None
        for p in parts:
            if p.startswith("symbol="):
                symbol_key = p.split("=", 1)[1].strip()
                break
        if symbol_key is None and path.name not in ("dataset.csv", "data.csv"):
            symbol_key = path.stem
        stats = _csv_date_range_stats(path)
        return {
            "file_id": relative.as_posix(),
            "market": market_name,
            "interval": None,
            "data_kind": data_kind,
            "symbol_key": symbol_key,
            "partition": ("/".join(parts[4:-1]) if len(parts) > 5 else None) or (symbol_key or "latest"),
            "formats": ["csv"],
            "preferred_format": "csv",
            "file_path": str(path),
            "row_count": stats["row_count"],
            "start": stats["start"],
            "end": stats["end"],
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
        }
    # 旧版：data/market/<market>/<interval>/<symbol>.csv
    if parts[0] == "market" and len(parts) == 4 and parts[1] != "crypto":
        from .tushare_quant1.market_data import SUPPORTED_INTERVALS

        if parts[2] in SUPPORTED_INTERVALS.get(parts[1], set()):
            stats = _csv_date_range_stats(path)
            return {
                "file_id": relative.as_posix(),
                "market": parts[1],
                "interval": parts[2],
                "data_kind": "ohlcv",
                "symbol_key": path.stem,
                "partition": parts[2],
                "formats": ["csv"],
                "preferred_format": "csv",
                "file_path": str(path),
                "row_count": stats["row_count"],
                "start": stats["start"],
                "end": stats["end"],
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
            }
        return None
    if parts[0] == "market":
        return None
    if parts[0] == "binanceusdm" and len(parts) >= 3:
        market = "binanceusdm"
        data_kind = parts[1]
        interval = parts[2] if len(parts) >= 4 else None
        symbol_key = path.stem if path.name != "dataset.csv" else None
        return {
            "file_id": relative.as_posix(),
            "market": market,
            "interval": interval if len(parts) >= 4 else None,
            "data_kind": data_kind,
            "symbol_key": symbol_key,
            "partition": interval or symbol_key or "dataset",
            "formats": ["csv"],
            "preferred_format": "csv",
            "file_path": str(path),
            "row_count": csv_row_count(path),
            "start": None,
            "end": None,
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
        }
    if len(parts) < 3:
        return None
    market = parts[0]
    data_kind = parts[1]
    interval = parts[2] if len(parts) >= 4 else None
    symbol_key = path.stem if path.name != "dataset.csv" else None
    return {
        "file_id": relative.as_posix(),
        "market": market,
        "interval": interval if len(parts) >= 4 else None,
        "data_kind": data_kind,
        "symbol_key": symbol_key,
        "partition": interval or symbol_key or "dataset",
        "formats": ["csv"],
        "preferred_format": "csv",
        "file_path": str(path),
        "row_count": csv_row_count(path),
        "start": None,
        "end": None,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
    }


def _preview_meta_from_relative(relative: Path, path: Path) -> dict[str, Any]:
    parts = list(relative.parts)
    if len(parts) >= 3 and parts[0] == "market" and parts[1] == "crypto":
        if "latest" in parts:
            try:
                li = parts.index("latest")
            except ValueError:
                li = -1
            if li >= 3:
                data_kind = parts[2]
                interval = parts[3] if li >= 4 else None
                sym_raw = next((p for p in parts if p.startswith("symbol=")), "")
                sym = sym_raw.split("=", 1)[1] if sym_raw else path.stem
                return {
                    "market": "binanceusdm",
                    "data_kind": data_kind,
                    "interval": interval,
                    "symbol_key": sym,
                    "partition": interval or sym,
                }
        if len(parts) == 4 and path.suffix.lower() == ".csv" and path.name != "dataset.csv":
            return {
                "market": "binanceusdm",
                "data_kind": parts[2],
                "interval": None,
                "symbol_key": path.stem,
                "partition": path.stem,
            }
        if len(parts) >= 5 and path.suffix.lower() == ".csv":
            return {
                "market": "binanceusdm",
                "data_kind": parts[2],
                "interval": parts[3],
                "symbol_key": path.stem if path.name != "dataset.csv" else None,
                "partition": parts[3] or path.stem,
            }
        if len(parts) >= 4 and path.name == "dataset.csv":
            return {
                "market": "binanceusdm",
                "data_kind": parts[2],
                "interval": None,
                "symbol_key": None,
                "partition": "dataset",
            }
    if parts[0] == "binanceusdm" and len(parts) >= 3:
        return {
            "market": "binanceusdm",
            "data_kind": parts[1],
            "interval": parts[2] if len(parts) >= 4 else None,
            "symbol_key": path.stem if path.name != "dataset.csv" else None,
            "partition": (parts[2] if len(parts) >= 4 else None) or path.stem,
        }
    return {
        "market": parts[0],
        "data_kind": parts[1] if len(parts) > 1 else "",
        "interval": parts[2] if len(parts) >= 4 else None,
        "symbol_key": path.stem if path.name != "dataset.csv" else None,
        "partition": (parts[2] if len(parts) >= 4 else None) or path.stem,
    }


def scan_data_files() -> list[dict[str, Any]]:
    """合并 quant1 catalog（parquet）与旧版扁平 csv 扫描。"""
    by_key: dict[str, dict[str, Any]] = {}
    inv = _load_catalog_inventory()
    for item in inv.get("files") or []:
        fp = item.get("file_path")
        if not fp:
            continue
        path = Path(fp)
        if not path.is_file() or "artifacts" in path.parts:
            continue
        try:
            path.relative_to(DATA_ROOT.resolve())
        except ValueError:
            continue
        key = str(path.resolve())
        row = dict(item)
        row.setdefault("row_count", _dataset_file_row_count(path))
        row.setdefault("updated_at", datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"))
        by_key[key] = row

    if DATA_ROOT.exists():
        for path in sorted(DATA_ROOT.rglob("*.csv")):
            if "artifacts" in path.parts:
                continue
            k = str(path.resolve())
            if k in by_key:
                continue
            relative = path.relative_to(DATA_ROOT)
            row = _scan_csv_entry(relative, path)
            if row:
                by_key[k] = row
    return list(by_key.values())


def build_data_overview(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for item in files:
        key = (item["market"], item["interval"], item["data_kind"])
        row = grouped.setdefault(
            key,
            {
                "market": item["market"],
                "interval": item["interval"],
                "data_kind": item["data_kind"],
                "file_count": 0,
                "symbol_count": 0,
                "row_count": 0,
                "start": None,
                "end": None,
                "updated_at": item["updated_at"],
                "formats": ["csv"],
                "_symbols": set(),
            },
        )
        row["file_count"] += 1
        row["row_count"] += item.get("row_count") or 0
        if item.get("symbol_key"):
            row["_symbols"].add(item["symbol_key"])
        st, en = item.get("start"), item.get("end")
        if st:
            row["start"] = st if row["start"] is None else min(row["start"], st)
        if en:
            row["end"] = en if row["end"] is None else max(row["end"], en)
        if item.get("updated_at") and item["updated_at"] > row["updated_at"]:
            row["updated_at"] = item["updated_at"]
    results = []
    for row in grouped.values():
        row["symbol_count"] = len(row.pop("_symbols"))
        results.append(row)
    return sorted(results, key=lambda item: (item["market"], item["data_kind"], item["interval"] or ""))


def preview_data_file(
    *,
    file_id: str | None = None,
    market: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
    data_kind: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    path = resolve_preview_path(file_id=file_id, market=market, interval=interval, symbol=symbol, data_kind=data_kind)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() == ".parquet":
        frame = pl.read_parquet(path).head(limit)
        fmt = "parquet"
        formats = ["parquet"]
    else:
        frame = load_csv(path).head(limit)
        fmt = "csv"
        formats = ["csv"]
    relative = path.relative_to(DATA_ROOT)
    meta = _preview_meta_from_relative(relative, path)
    resolved_id = file_id
    if resolved_id is None:
        sp = str(path.resolve())
        for item in _load_catalog_inventory().get("files") or []:
            if item.get("file_path") and str(Path(item["file_path"]).resolve()) == sp:
                resolved_id = item.get("file_id")
                break
        if resolved_id is None:
            resolved_id = relative.as_posix()
    return {
        "file_id": resolved_id,
        "market": meta["market"],
        "interval": meta.get("interval"),
        "data_kind": meta["data_kind"],
        "symbol_key": meta.get("symbol_key"),
        "partition": meta.get("partition"),
        "format": fmt,
        "file_path": str(path),
        "row_count": _dataset_file_row_count(path),
        "start": None,
        "end": None,
        "available_formats": formats,
        "columns": frame.columns,
        "rows": frame.to_dicts(),
    }
