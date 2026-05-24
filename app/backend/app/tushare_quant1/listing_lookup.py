"""Resolve listing / inception dates from locally cached Tushare basic tables."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl

from .project_paths import ProjectPaths

# One HTTP call: avoid requesting more than ~25 years of daily bars at once (Tushare row limits).
TUSHARE_MAX_CALENDAR_SPAN_DAYS = 4000


def _parse_date_cell(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return datetime.strptime(text[:8], "%Y%m%d").date()
        except ValueError:
            pass
    norm = text.replace("/", "-")[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(norm, fmt).date()
        except ValueError:
            continue
    return None


def _looks_like_cn_index_ts(ts_code: str) -> bool:
    u = ts_code.upper()
    return u.endswith(".SH") or u.endswith(".SZ") or u.endswith(".CSI")


def _scan_basic_for_list_date(paths: ProjectPaths, market: str, data_kind: str, ts_code: str) -> date | None:
    latest = paths.market_dataset_latest_dir(market, data_kind)
    if not latest.exists():
        return None
    files = sorted({*latest.rglob("*.csv"), *latest.rglob("*.parquet")})
    if not files:
        return None
    want = ts_code.strip().upper()
    date_cols = ("list_date", "trade_date", "base_date", "publish_date")
    code_cols = ("ts_code", "symbol", "index_code")
    for path in files:
        try:
            if path.suffix.lower() == ".csv":
                frame = pl.read_csv(path, try_parse_dates=True)
            else:
                frame = pl.read_parquet(path)
        except Exception:  # noqa: BLE001
            continue
        if frame.is_empty():
            continue
        lower = {str(c).lower(): c for c in frame.columns}
        code_col = next((lower[c] for c in code_cols if c in lower), None)
        if code_col is None:
            continue
        date_col = next((lower[c] for c in date_cols if c in lower), None)
        if date_col is None:
            continue
        hit = frame.filter(pl.col(code_col).cast(pl.Utf8).str.to_uppercase() == want)
        if hit.is_empty():
            continue
        raw = hit.select(pl.col(date_col).min()).item()
        parsed = _parse_date_cell(raw)
        if parsed is not None:
            return parsed
    return None


def lookup_ts_list_date(paths: ProjectPaths, market: str, ts_code: str) -> date | None:
    """Best-effort listing / base date for a Tushare ``ts_code`` from local CSV/parquet under ``latest``."""
    ts = ts_code.strip()
    if not ts:
        return None
    order: list[tuple[str, str]] = []
    if market == "stocks_cn" and _looks_like_cn_index_ts(ts):
        order.append(("indices_cn", "index_basic"))
    if market == "indices_cn":
        order.append(("indices_cn", "index_basic"))
    if market == "stocks_cn":
        order.append(("stocks_cn", "stock_basic"))
    elif market == "stocks_hk":
        order.append(("stocks_hk", "hk_basic"))
    elif market == "stocks_us":
        order.append(("stocks_us", "us_basic"))
    elif market != "indices_cn":
        order.append((market, "stock_basic"))
    seen: set[tuple[str, str]] = set()
    for m, dk in order:
        key = (m, dk)
        if key in seen:
            continue
        seen.add(key)
        d = _scan_basic_for_list_date(paths, m, dk, ts)
        if d is not None:
            return d
    return None


def chunk_yyyymmdd_window(start_key: str, end_key: str, *, max_days: int = TUSHARE_MAX_CALENDAR_SPAN_DAYS) -> list[tuple[str, str]]:
    """Split [start_key, end_key] into contiguous YYYYMMDD windows of at most ``max_days`` calendar days."""
    try:
        s = datetime.strptime(start_key, "%Y%m%d").date()
        e = datetime.strptime(end_key, "%Y%m%d").date()
    except ValueError:
        return [(start_key, end_key)]
    if s > e:
        return [(start_key, end_key)]
    out: list[tuple[str, str]] = []
    cur = s
    while cur <= e:
        span_end = min(date.fromordinal(cur.toordinal() + max_days - 1), e)
        out.append((cur.strftime("%Y%m%d"), span_end.strftime("%Y%m%d")))
        cur = date.fromordinal(span_end.toordinal() + 1)
    return out
