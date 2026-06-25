from __future__ import annotations

import importlib
import json as _json
import logging
import math
import os
import queue
import shutil
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

import polars as pl

from .data_catalog import list_data_files, list_data_presets, rebuild_data_catalog
from .default_tokens import TUSHARE_DEFAULT_TOKENS
from .listing_lookup import (
    TUSHARE_MAX_CALENDAR_SPAN_DAYS,
    chunk_yyyymmdd_window,
    lookup_ts_list_date,
)
from .market_data import normalize_symbol_key
from .project_paths import ProjectPaths
from .stock_pools import resolve_stock_pool

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tushare tier constraints (2000 <= points < 5000)
# ---------------------------------------------------------------------------
TUSHARE_MIN_POINTS_BASELINE = 2000
TUSHARE_RATE_LIMITS_BY_TIER: dict[int, int] = {
    2000: 200,   # 200 RPM
    5000: 500,   # 500 RPM
}
DAILY_PER_API_LIMIT = 100_000   # 2000-pt tier: 100k calls/day per API
DAILY_PER_API_SOFT_CEILING = int(DAILY_PER_API_LIMIT * 0.95)

# Validation caching
TOKEN_CACHE_TTL_SECONDS = 3600.0          # in-memory TTL (1 h)
DISK_CACHE_TTL_SECONDS = 86400.0          # disk cache TTL (24 h)

# Retry / cooldown
MAX_RETRIES = 3
RETRY_DELAYS = [2.0, 8.0, 30.0]          # exponential backoff per attempt
TOKEN_COOLDOWN_SECONDS = 60.0             # per-token cooldown after rate-limit error
CROSS_SECTION_SYMBOL_THRESHOLD = 200

_SECRETS_RELATIVE = Path("config") / "secrets" / "tushare_tokens.json"
_DISK_CACHE_RELATIVE = Path("data") / ".cache" / "tushare_token_status.json"
_DAILY_USAGE_DIR_RELATIVE = Path("data") / ".cache"
_CROSS_SECTION_STATE_PREFIX = "tushare_cross_section_dates"


def _rate_limit_for_points(points: int) -> int:
    for threshold in sorted(TUSHARE_RATE_LIMITS_BY_TIER.keys(), reverse=True):
        if points >= threshold:
            return TUSHARE_RATE_LIMITS_BY_TIER[threshold]
    return 80


FetchMode = Literal["static", "range", "symbol_range", "trade_date_range"]
ProgressCallback = Callable[..., None]
DATE_COLUMN_CANDIDATES = (
    "trade_date",
    "ann_date",
    "end_date",
    "publish_date",
    "record_date",
    "cal_date",
    "nav_date",
    "list_date",
    "date",
    "datetime",
    "timestamp",
)
DEFAULT_INDEX_MARKETS = (
    {"market": "SSE"},
    {"market": "SZSE"},
    {"market": "CSI"},
    {"market": "SW"},
)
_RUNTIME_PRICE_SOURCE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "stocks_cn": ("daily", "pro_bar"),
    "stocks_hk": ("hk_daily",),
    "stocks_us": ("us_daily", "us_daily_adj"),
}
_RUNTIME_ADJ_FACTOR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "stocks_cn": ("adj_factor",),
    "stocks_hk": ("hk_adjfactor",),
    "stocks_us": ("us_adjfactor",),
}
# 原始**未复权**价源：必须乘 adj_factor 复权后才可落盘（否则除权跳变=假收益，违 RULES『未复权价喂成交层即停工』）。
# 已复权源（如 us_daily_adj·名含 _adj）绝不再乘 adj_factor（否则双重复权=新 correctness bug）。
_RAW_PRICE_SOURCES: frozenset[str] = frozenset({"daily", "pro_bar", "hk_daily", "us_daily"})


@dataclass(frozen=True)
class TushareDatasetSpec:
    market: str
    data_kind: str
    api_name: str
    label: str
    required_points: int
    fetch_mode: FetchMode
    supports_symbols: bool
    supports_date_range: bool
    partition_by: tuple[str, ...]
    symbol_field: str = "ts_code"
    trade_date_field: str = "trade_date"
    start_field: str = "start_date"
    end_field: str = "end_date"
    independent_permission: bool = False
    request_variants: tuple[dict[str, Any], ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)
    unique_keys: tuple[str, ...] = ()
    cross_section_symbol_threshold: int | None = None


@dataclass(frozen=True)
class TokenStatus:
    slot: int
    token_mask: str
    points: int
    expires_at: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class TokenValidationResult:
    configured_slots: int
    healthy_tokens: tuple[TokenStatus, ...]
    failed_tokens: tuple[TokenStatus, ...]

    @property
    def effective_points_ceiling(self) -> int | None:
        if not self.healthy_tokens:
            return None
        return min(item.points for item in self.healthy_tokens)

    @property
    def healthy_points(self) -> list[int]:
        return [item.points for item in self.healthy_tokens]


@dataclass
class PullBatch:
    spec: TushareDatasetSpec
    params: dict[str, Any]
    label: str
    symbol_filter: tuple[str, ...] = ()


@dataclass
class TokenClient:
    slot: int
    token: str
    token_mask: str
    points: int
    expires_at: str | None
    ts_module: Any
    pro_client: Any
    request_timestamps: deque[float] = field(default_factory=deque)
    api_calls: Counter[str] = field(default_factory=Counter)
    daily_api_calls: Counter[str] = field(default_factory=Counter)
    consecutive_errors: int = 0
    cooldown_until: float = 0.0

    @property
    def is_cooling_down(self) -> bool:
        return time.monotonic() < self.cooldown_until

    def enter_cooldown(self, seconds: float = TOKEN_COOLDOWN_SECONDS) -> None:
        self.cooldown_until = time.monotonic() + seconds
        _log.warning("Token slot %d (%s) entering %.0fs cooldown.", self.slot, self.token_mask, seconds)

    @property
    def rpm_limit(self) -> int:
        return _rate_limit_for_points(self.points)

    @property
    def rpm_headroom(self) -> int:
        """How many more requests can be made in the current 60s window."""
        now = time.monotonic()
        while self.request_timestamps and now - self.request_timestamps[0] >= 60.0:
            self.request_timestamps.popleft()
        return max(0, self.rpm_limit - len(self.request_timestamps))

    def call(self, api_name: str, params: dict[str, Any]) -> Any:
        self._wait_for_slot()
        try:
            if api_name == "pro_bar":
                payload = self.ts_module.pro_bar(api=self.pro_client, **params)
            else:
                payload = self.pro_client.query(api_name, **params)
            self.consecutive_errors = 0
        except Exception as exc:
            self.consecutive_errors += 1
            if _is_rate_limit_error(str(exc)):
                self.enter_cooldown()
            raise
        self.request_timestamps.append(time.monotonic())
        self.api_calls[api_name] += 1
        self.daily_api_calls[api_name] += 1
        return payload

    def _wait_for_slot(self) -> None:
        now = time.monotonic()
        while self.request_timestamps and now - self.request_timestamps[0] >= 60.0:
            self.request_timestamps.popleft()
        if len(self.request_timestamps) < self.rpm_limit:
            return
        sleep_for = 60.0 - (now - self.request_timestamps[0])
        if sleep_for > 0:
            time.sleep(sleep_for)
        now = time.monotonic()
        while self.request_timestamps and now - self.request_timestamps[0] >= 60.0:
            self.request_timestamps.popleft()


# ---------------------------------------------------------------------------
# TokenPool -- smart multi-token dispatcher (replaces TushareScheduler)
# ---------------------------------------------------------------------------

class TokenPool:
    """Thread-safe token pool with smart dispatch, cooldown, and daily-limit awareness."""

    def __init__(self, clients: list[TokenClient]) -> None:
        if not clients:
            raise ValueError("At least one healthy Tushare token is required.")
        self.clients = clients
        self._lock = threading.Lock()
        self._last_flush: float = time.monotonic()

    def pick_client(self, api_name: str | None = None) -> TokenClient:
        """Pick the best available client: not cooling, not daily-exhausted, most RPM headroom."""
        with self._lock:
            candidates = [
                c for c in self.clients
                if not c.is_cooling_down
                and (api_name is None or c.daily_api_calls[api_name] < DAILY_PER_API_SOFT_CEILING)
            ]
            if not candidates:
                candidates = sorted(self.clients, key=lambda c: c.cooldown_until)
            return min(candidates, key=lambda c: len(c.request_timestamps))

    def call(self, api_name: str, **params: Any) -> Any:
        """Backward-compatible call used in the sequential pull path."""
        client = self.pick_client(api_name)
        return client.call(api_name, params)

    def api_calls_by_token(self) -> dict[str, dict[str, int]]:
        return {
            client.token_mask: dict(sorted(client.api_calls.items()))
            for client in self.clients
        }

    def daily_usage_summary(self) -> dict[str, Any]:
        """Return a summary of daily API usage across all tokens."""
        by_slot: dict[str, Any] = {}
        for c in self.clients:
            by_slot[str(c.slot)] = {
                "token_mask": c.token_mask,
                "total": sum(c.daily_api_calls.values()),
                "by_api": dict(sorted(c.daily_api_calls.items())),
                "consecutive_errors": c.consecutive_errors,
                "is_cooling_down": c.is_cooling_down,
            }
        return {"date": date.today().isoformat(), "by_slot": by_slot}

    def flush_daily_usage(self, *, force: bool = False) -> None:
        """Write daily usage to disk (at most every 60 s unless forced)."""
        now = time.monotonic()
        if not force and now - self._last_flush < 60.0:
            return
        self._last_flush = now
        today = date.today().strftime("%Y%m%d")
        cache_dir = _project_root() / _DAILY_USAGE_DIR_RELATIVE
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"tushare_daily_usage_{today}.json"
        try:
            path.write_text(
                _json.dumps(self.daily_usage_summary(), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            _log.warning("Could not write daily usage to %s", path)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _mask_token(token: str) -> str:
    compact = token.strip()
    if len(compact) <= 8:
        return f"slot-{compact or 'empty'}"
    return f"{compact[:4]}...{compact[-4:]}"


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date_like(value: Any) -> datetime | None:
    text = _normalize_text(value)
    if text is None:
        return None
    for pattern in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_yyyymmdd(value: str | None) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    parsed = _parse_date_like(text)
    if parsed is not None:
        return parsed.strftime("%Y%m%d")
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    raise ValueError(f"Unsupported date value `{value}`.")


def _frame_to_records(frame: Any) -> list[dict[str, Any]]:
    if isinstance(frame, pl.DataFrame):
        return frame.to_dicts()
    if hasattr(frame, "to_dict"):
        try:
            return list(frame.to_dict(orient="records"))
        except TypeError:
            pass
    if isinstance(frame, list):
        return [dict(item) for item in frame]
    raise TypeError(f"Unsupported frame type `{type(frame)}`.")


def _to_polars_frame(frame: Any) -> pl.DataFrame:
    if isinstance(frame, pl.DataFrame):
        return frame
    records = _frame_to_records(frame)
    return pl.DataFrame(records) if records else pl.DataFrame()


def _extract_token_points(frame: Any) -> tuple[int, str | None]:
    records = _frame_to_records(frame)
    total_points = 0.0
    expires_at: datetime | None = None
    for row in records:
        for key, value in row.items():
            key_text = str(key).lower()
            if "积分" in str(key) or "point" in key_text:
                try:
                    total_points += float(value)
                except (TypeError, ValueError):
                    continue
            if "到期" in str(key) or "expire" in key_text:
                parsed = _parse_date_like(value)
                if parsed is not None and (expires_at is None or parsed > expires_at):
                    expires_at = parsed
    return int(math.floor(total_points)), expires_at.isoformat() if expires_at else None


def _load_tushare_module() -> Any:
    try:
        return importlib.import_module("tushare")
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("tushare is not installed. Run `pip install tushare` before pulling data.") from exc


TUSHARE_DATASET_SPECS: tuple[TushareDatasetSpec, ...] = (
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="stock_basic",
        api_name="stock_basic",
        label="Stock Basic",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        request_variants=({"list_status": "L"}, {"list_status": "D"}, {"list_status": "P"}),
        unique_keys=("ts_code",),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="trade_cal",
        api_name="trade_cal",
        label="Trade Calendar",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        default_params={"exchange": "SSE"},
        unique_keys=("exchange", "cal_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="new_share",
        api_name="new_share",
        label="IPO New Share",
        required_points=120,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "ipo_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="daily",
        api_name="daily",
        label="Stocks Daily",
        required_points=120,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="weekly",
        api_name="weekly",
        label="Stocks Weekly",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="monthly",
        api_name="monthly",
        label="Stocks Monthly",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="pro_bar",
        api_name="pro_bar",
        label="Stocks Pro Bar",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        default_params={"adj": "qfq"},
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="daily_basic",
        api_name="daily_basic",
        label="Stocks Daily Basic",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="adj_factor",
        api_name="adj_factor",
        label="Stocks Adj Factor",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="stk_limit",
        api_name="stk_limit",
        label="Stock Limit Prices",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="suspend_d",
        api_name="suspend_d",
        label="Stock Suspend Daily",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date", "suspend_timing"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="moneyflow",
        api_name="moneyflow",
        label="Money Flow",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="top_list",
        api_name="top_list",
        label="Top List",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="top_inst",
        api_name="top_inst",
        label="Top Institution",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date", "exalter"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="margin",
        api_name="margin",
        label="Margin Summary",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("trade_date", "exchange_id"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="margin_detail",
        api_name="margin_detail",
        label="Margin Detail",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="repurchase",
        api_name="repurchase",
        label="Repurchase",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="block_trade",
        api_name="block_trade",
        label="Block Trade",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date", "price", "vol"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="stk_holdernumber",
        api_name="stk_holdernumber",
        label="Holder Number",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="stk_holdertrade",
        api_name="stk_holdertrade",
        label="Holder Trade",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "holder_name"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="hk_hold",
        api_name="hk_hold",
        label="HK Hold",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="income",
        api_name="income",
        label="Income Statement",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date", "report_type"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="balancesheet",
        api_name="balancesheet",
        label="Balance Sheet",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date", "report_type"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="cashflow",
        api_name="cashflow",
        label="Cashflow",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date", "report_type"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="forecast",
        api_name="forecast",
        label="Forecast",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="express",
        api_name="express",
        label="Express",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="dividend",
        api_name="dividend",
        label="Dividend",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "record_date", "ex_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="fina_indicator",
        api_name="fina_indicator",
        label="Financial Indicator",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="fina_audit",
        api_name="fina_audit",
        label="Financial Audit",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="fina_mainbz",
        api_name="fina_mainbz",
        label="Main Business",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "end_date", "bz_item"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="disclosure_date",
        api_name="disclosure_date",
        label="Disclosure Date",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "end_date", "ann_date"),
    ),
    TushareDatasetSpec(
        market="stocks_cn",
        data_kind="share_float",
        api_name="share_float",
        label="Share Float",
        required_points=3000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "float_date"),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_basic",
        api_name="index_basic",
        label="Index Basic",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        request_variants=DEFAULT_INDEX_MARKETS,
        unique_keys=("ts_code",),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_daily",
        api_name="index_daily",
        label="Index Daily",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_weekly",
        api_name="index_weekly",
        label="Index Weekly",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_monthly",
        api_name="index_monthly",
        label="Index Monthly",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_weight",
        api_name="index_weight",
        label="Index Weight",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("index_code", "trade_date", "con_code"),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_classify",
        api_name="index_classify",
        label="Index Classify",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        default_params={"src": "SW2021"},
        unique_keys=("index_code",),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_member_all",
        api_name="index_member_all",
        label="Index Member All",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        default_params={"is_new": "Y"},
        unique_keys=("index_code", "con_code", "in_date"),
    ),
    TushareDatasetSpec(
        market="indices_cn",
        data_kind="index_dailybasic",
        api_name="index_dailybasic",
        label="Index Daily Basic",
        required_points=4000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_basic",
        api_name="fund_basic",
        label="Fund Basic",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        request_variants=({"market": "E"}, {"market": "O"}),
        unique_keys=("ts_code",),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_company",
        api_name="fund_company",
        label="Fund Company",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        unique_keys=("name",),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_nav",
        api_name="fund_nav",
        label="Fund NAV",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "end_date", "ann_date"),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_daily",
        api_name="fund_daily",
        label="Fund Daily",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_div",
        api_name="fund_div",
        label="Fund Dividend",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "ann_date", "ex_date"),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_portfolio",
        api_name="fund_portfolio",
        label="Fund Portfolio",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "end_date", "symbol"),
    ),
    TushareDatasetSpec(
        market="funds_cn",
        data_kind="fund_adj",
        api_name="fund_adj",
        label="Fund Adj",
        required_points=5000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="cb_basic",
        api_name="cb_basic",
        label="Convertible Bond Basic",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        unique_keys=("ts_code",),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="cb_issue",
        api_name="cb_issue",
        label="Convertible Bond Issue",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "ann_date"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="cb_daily",
        api_name="cb_daily",
        label="Convertible Bond Daily",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="cb_share",
        api_name="cb_share",
        label="Convertible Bond Share",
        required_points=2000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "publish_date", "end_date"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="repo_daily",
        api_name="repo_daily",
        label="Repo Daily",
        required_points=2000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="bc_otcqt",
        api_name="bc_otcqt",
        label="Bond OTC Quote",
        required_points=500,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date", "update_time"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="bc_bestotcqt",
        api_name="bc_bestotcqt",
        label="Bond Best OTC Quote",
        required_points=500,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "trade_date", "update_time"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="cb_call",
        api_name="cb_call",
        label="Convertible Bond Call",
        required_points=5000,
        fetch_mode="range",
        supports_symbols=False,
        supports_date_range=True,
        partition_by=("year",),
        unique_keys=("ts_code", "ann_date", "call_date"),
    ),
    TushareDatasetSpec(
        market="bonds_cn",
        data_kind="cb_rate",
        api_name="cb_rate",
        label="Convertible Bond Rate",
        required_points=5000,
        fetch_mode="symbol_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "rate_date"),
    ),
    TushareDatasetSpec(
        market="stocks_hk",
        data_kind="hk_basic",
        api_name="hk_basic",
        label="Hong Kong Stock Basic",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        unique_keys=("ts_code",),
    ),
    TushareDatasetSpec(
        market="stocks_hk",
        data_kind="hk_daily",
        api_name="hk_daily",
        label="Hong Kong Daily",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_hk",
        data_kind="hk_adjfactor",
        api_name="hk_adjfactor",
        label="Hong Kong Adj Factor",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_us",
        data_kind="us_basic",
        api_name="us_basic",
        label="US Stock Basic",
        required_points=2000,
        fetch_mode="static",
        supports_symbols=False,
        supports_date_range=False,
        partition_by=(),
        unique_keys=("ts_code",),
    ),
    TushareDatasetSpec(
        market="stocks_us",
        data_kind="us_daily",
        api_name="us_daily",
        label="US Daily",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_us",
        data_kind="us_daily_adj",
        api_name="us_daily_adj",
        label="US Daily Adjusted",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
    TushareDatasetSpec(
        market="stocks_us",
        data_kind="us_adjfactor",
        api_name="us_adjfactor",
        label="US Adj Factor",
        required_points=2000,
        fetch_mode="trade_date_range",
        supports_symbols=True,
        supports_date_range=True,
        partition_by=("symbol", "year"),
        unique_keys=("ts_code", "trade_date"),
        cross_section_symbol_threshold=CROSS_SECTION_SYMBOL_THRESHOLD,
    ),
)


_TOKEN_VALIDATION_CACHE: tuple[float, TokenValidationResult] | None = None


def _is_rate_limit_error(message: str) -> bool:
    """Detect any Tushare rate-limit error (data APIs and user() alike)."""
    lower = message.lower()
    return any(p in lower for p in (
        "最多访问", "频次", "rate limit", "too many", "每分钟", "抱歉您每分钟", "50次", "50 times",
    ))


def _project_root() -> Path:
    from ..paths import PROJECT_ROOT

    return PROJECT_ROOT


def _token_slots() -> list[str]:
    """Load tokens with priority: QUANT1_TUSHARE_TOKENS > TUSHARE_TOKEN > secrets 文件 > 内置默认。"""
    raw = os.environ.get("QUANT1_TUSHARE_TOKENS", "").strip()
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    single = os.environ.get("TUSHARE_TOKEN", "").strip()
    if single:
        return [t.strip() for t in single.split(",") if t.strip()]
    secrets_path = _project_root() / _SECRETS_RELATIVE
    if secrets_path.exists():
        try:
            data = _json.loads(secrets_path.read_text(encoding="utf-8-sig"))
            tokens = data.get("tokens", [])
            out = [t.strip() for t in tokens if isinstance(t, str) and t.strip()]
            if out:
                return out
        except Exception:  # noqa: BLE001
            _log.warning("Failed to read %s, falling back to default tokens.", secrets_path)
    return [t for t in TUSHARE_DEFAULT_TOKENS if t.strip()]


# ---------------------------------------------------------------------------
# Disk cache helpers for token validation results
# ---------------------------------------------------------------------------

def _disk_cache_path() -> Path:
    return _project_root() / _DISK_CACHE_RELATIVE


def _write_disk_cache(result: TokenValidationResult) -> None:
    """Persist validation result to disk so subsequent runs skip user()."""
    path = _disk_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "validated_at_iso": datetime.now(UTC).isoformat(),
        "validated_at_epoch": time.time(),
        "configured_slots": result.configured_slots,
        "tokens": [
            {
                "slot": ts.slot,
                "token_mask": ts.token_mask,
                "points": ts.points,
                "expires_at": ts.expires_at,
                "healthy": ts.error is None,
                "error": ts.error,
            }
            for ts in (*result.healthy_tokens, *result.failed_tokens)
        ],
    }
    try:
        path.write_text(_json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.warning("Could not write disk cache to %s", path)


def _read_disk_cache() -> TokenValidationResult | None:
    """Load cached validation from disk if it's younger than DISK_CACHE_TTL_SECONDS."""
    path = _disk_cache_path()
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    epoch = data.get("validated_at_epoch", 0)
    if time.time() - epoch > DISK_CACHE_TTL_SECONDS:
        return None
    healthy: list[TokenStatus] = []
    failed: list[TokenStatus] = []
    for tok in data.get("tokens", []):
        ts = TokenStatus(
            slot=tok["slot"],
            token_mask=tok["token_mask"],
            points=tok["points"],
            expires_at=tok.get("expires_at"),
            error=tok.get("error"),
        )
        if tok.get("healthy"):
            healthy.append(ts)
        else:
            failed.append(ts)
    if not healthy:
        return None
    return TokenValidationResult(
        configured_slots=data.get("configured_slots", len(healthy) + len(failed)),
        healthy_tokens=tuple(healthy),
        failed_tokens=tuple(failed),
    )


# ---------------------------------------------------------------------------
# Token validation (minimises user() calls via in-memory + disk cache)
# ---------------------------------------------------------------------------

def validate_tushare_tokens(*, force_refresh: bool = False) -> TokenValidationResult:
    global _TOKEN_VALIDATION_CACHE

    # 1) In-memory cache (within process lifetime)
    if not force_refresh and _TOKEN_VALIDATION_CACHE is not None:
        cached_at, cached_value = _TOKEN_VALIDATION_CACHE
        if time.monotonic() - cached_at <= TOKEN_CACHE_TTL_SECONDS:
            return cached_value

    slots = _token_slots()
    configured = [(idx + 1, tok.strip()) for idx, tok in enumerate(slots) if tok.strip()]
    if not configured:
        result = TokenValidationResult(configured_slots=len(slots), healthy_tokens=(), failed_tokens=())
        _TOKEN_VALIDATION_CACHE = (time.monotonic(), result)
        return result

    # 2) Disk cache -- avoids calling user() unless truly stale (>24 h)
    if not force_refresh:
        disk_result = _read_disk_cache()
        if disk_result is not None:
            _log.info("Using disk-cached token validation (%d healthy).", len(disk_result.healthy_tokens))
            _TOKEN_VALIDATION_CACHE = (time.monotonic(), disk_result)
            return disk_result

    # 3) Fresh validation via user() -- at most once per token per day
    _log.info("Calling tushare user() for %d token(s).", len(configured))
    ts_module = _load_tushare_module()
    healthy: list[TokenStatus] = []
    failed: list[TokenStatus] = []
    for slot, token in configured:
        token_mask = _mask_token(token)
        try:
            pro_client = ts_module.pro_api(token)
            user_frame = pro_client.user(token=token)
            points, expires_at = _extract_token_points(user_frame)
            if points >= TUSHARE_MIN_POINTS_BASELINE:
                healthy.append(TokenStatus(slot=slot, token_mask=token_mask, points=points, expires_at=expires_at))
            else:
                failed.append(TokenStatus(
                    slot=slot, token_mask=token_mask, points=points, expires_at=expires_at,
                    error=f"Points {points} below baseline {TUSHARE_MIN_POINTS_BASELINE}.",
                ))
        except Exception as exc:  # noqa: BLE001
            failed.append(TokenStatus(slot=slot, token_mask=token_mask, points=0, error=str(exc)))

    result = TokenValidationResult(
        configured_slots=len(slots),
        healthy_tokens=tuple(healthy),
        failed_tokens=tuple(failed),
    )

    # If user() failed for all tokens due to rate limit, try disk cache as fallback
    if not result.healthy_tokens and result.failed_tokens:
        if all(_is_rate_limit_error(f.error or "") for f in result.failed_tokens):
            disk_fallback = _read_disk_cache()
            if disk_fallback is not None:
                _log.warning("user() rate-limited for all tokens; using stale disk cache.")
                _TOKEN_VALIDATION_CACHE = (time.monotonic(), disk_fallback)
                return disk_fallback

    if result.healthy_tokens:
        _write_disk_cache(result)

    _TOKEN_VALIDATION_CACHE = (time.monotonic(), result)
    return result


def get_tushare_dataset_specs(market: str | None = None) -> list[TushareDatasetSpec]:
    specs = list(TUSHARE_DATASET_SPECS)
    if market is None:
        return specs
    return [spec for spec in specs if spec.market == market]


def get_enabled_tushare_dataset_specs(
    market: str | None = None,
    *,
    validation: TokenValidationResult | None = None,
) -> list[TushareDatasetSpec]:
    validation_result = validation or validate_tushare_tokens()
    ceiling = validation_result.effective_points_ceiling
    if ceiling is None:
        return []
    return [
        spec
        for spec in get_tushare_dataset_specs(market)
        if not spec.independent_permission and spec.required_points <= ceiling
    ]


def list_tushare_kind_options(market: str | None = None) -> list[dict[str, Any]]:
    validation = validate_tushare_tokens()
    ceiling = validation.effective_points_ceiling
    options = []
    for spec in get_enabled_tushare_dataset_specs(market, validation=validation):
        options.append(
            {
                "market": spec.market,
                "data_kind": spec.data_kind,
                "api_name": spec.api_name,
                "label": spec.label,
                "required_points": spec.required_points,
                "effective_points_ceiling": ceiling,
                "supports_symbols": spec.supports_symbols,
                "supports_date_range": spec.supports_date_range,
                "independent_permission": spec.independent_permission,
            }
        )
    return options


def _build_pool(validation: TokenValidationResult) -> TokenPool:
    if not validation.healthy_tokens:
        details = "; ".join(
            f"slot {f.slot} ({f.token_mask}): {f.error or f'{f.points} pts'}" for f in validation.failed_tokens
        )
        if not details.strip():
            details = "no non-empty token found"
        raise RuntimeError(
            "No healthy Tushare tokens. "
            + details
            + f". Each token must pass tushare.user() and have >= {TUSHARE_MIN_POINTS_BASELINE} points. "
            + "Set QUANT1_TUSHARE_TOKENS or TUSHARE_TOKEN, or create config/secrets/tushare_tokens.json."
        )
    ts_module = _load_tushare_module()
    slots = _token_slots()
    clients = [
        TokenClient(
            slot=item.slot,
            token=slots[item.slot - 1].strip(),
            token_mask=item.token_mask,
            points=item.points,
            expires_at=item.expires_at,
            ts_module=ts_module,
            pro_client=ts_module.pro_api(slots[item.slot - 1].strip()),
        )
        for item in validation.healthy_tokens
    ]
    return TokenPool(clients)


# Backward-compatible alias
_build_scheduler = _build_pool
TushareScheduler = TokenPool


def _resolve_manual_symbols(symbols: list[str]) -> list[str]:
    return sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})


def _resolve_preset_symbols(paths: ProjectPaths, market: str, preset_name: str | None) -> list[str]:
    preset_key = _normalize_text(preset_name)
    if preset_key is None:
        return []
    for item in list_data_presets(paths):
        if item["market"] == market and item["preset_name"] == preset_key:
            return _resolve_manual_symbols(item.get("symbols") or [])
    resolved = resolve_stock_pool(paths, preset_name=preset_key, market=market)
    if resolved is None:
        return []
    return _resolve_manual_symbols(list(resolved.get("symbols") or []))


def _resolve_stock_pool_symbols(paths: ProjectPaths, market: str, stock_pool_id: str | None) -> list[str]:
    resolved = resolve_stock_pool(paths, pool_id=stock_pool_id, market=market)
    if resolved is None:
        return []
    return _resolve_manual_symbols(list(resolved.get("symbols") or []))


def _resolver_batches_for_market(market: str) -> list[PullBatch]:
    if market == "stocks_cn":
        spec = next(spec for spec in TUSHARE_DATASET_SPECS if spec.data_kind == "stock_basic")
        return [PullBatch(spec=spec, params={"list_status": status}, label=f"stock_basic:{status}") for status in ("L", "D", "P")]
    if market == "stocks_hk":
        spec = next(spec for spec in TUSHARE_DATASET_SPECS if spec.data_kind == "hk_basic")
        return [PullBatch(spec=spec, params={}, label="hk_basic")]
    if market == "stocks_us":
        spec = next(spec for spec in TUSHARE_DATASET_SPECS if spec.data_kind == "us_basic")
        return [PullBatch(spec=spec, params={}, label="us_basic")]
    if market == "indices_cn":
        spec = next(spec for spec in TUSHARE_DATASET_SPECS if spec.data_kind == "index_basic")
        return [PullBatch(spec=spec, params=dict(params), label=f"index_basic:{params['market']}") for params in DEFAULT_INDEX_MARKETS]
    if market == "funds_cn":
        spec = next(spec for spec in TUSHARE_DATASET_SPECS if spec.data_kind == "fund_basic")
        return [PullBatch(spec=spec, params={"market": market_key}, label=f"fund_basic:{market_key}") for market_key in ("E", "O")]
    if market == "bonds_cn":
        spec = next(spec for spec in TUSHARE_DATASET_SPECS if spec.data_kind == "cb_basic")
        return [PullBatch(spec=spec, params={}, label="cb_basic")]
    raise ValueError(f"Unsupported Tushare market `{market}`.")


def _extract_symbols_from_frame(frame: Any) -> list[str]:
    rows = _frame_to_records(frame)
    symbols = []
    for row in rows:
        symbol = _normalize_text(row.get("ts_code"))
        if symbol:
            symbols.append(symbol.upper())
    return sorted(set(symbols))


def _resolve_all_symbols(paths: ProjectPaths, scheduler: TushareScheduler, market: str) -> list[str]:
    del paths
    symbols: list[str] = []
    for batch in _resolver_batches_for_market(market):
        frame = scheduler.call(batch.spec.api_name, **batch.params)
        symbols.extend(_extract_symbols_from_frame(frame))
    return sorted(set(symbols))


def _resolve_symbols(
    paths: ProjectPaths,
    scheduler: TushareScheduler,
    market: str,
    symbol_mode: str,
    symbols: list[str],
    stock_pool_id: str | None,
    preset_name: str | None,
) -> list[str]:
    if symbol_mode == "manual":
        return _resolve_manual_symbols(symbols)
    if symbol_mode == "stock_pool":
        return _resolve_stock_pool_symbols(paths, market, stock_pool_id)
    if symbol_mode == "preset":
        return _resolve_preset_symbols(paths, market, preset_name)
    if symbol_mode == "all":
        return _resolve_all_symbols(paths, scheduler, market)
    raise ValueError(f"Unsupported symbol mode `{symbol_mode}`.")


def _find_latest_end(
    paths: ProjectPaths,
    market: str,
    data_kind: str,
    symbol_key: str | None,
    *,
    interval: str | None = None,
) -> date | None:
    """Latest end date in catalog for ``market``/``data_kind`` (and optional ``interval``).

    For Binance ``klines``, pass ``interval`` (e.g. ``4h``) so incremental pulls for one
    timeframe are not skipped just because another interval (e.g. ``1d``) is already current.
    """
    latest: date | None = None
    for item in list_data_files(paths, market=market, interval=interval, data_kind=data_kind):
        item_symbol = item.get("symbol_key")
        if symbol_key is not None and item_symbol != symbol_key:
            continue
        candidate = _parse_date_like(item.get("end"))
        if candidate is None:
            continue
        value = candidate.date()
        if latest is None or value > latest:
            latest = value
    return latest


def _cross_section_state_path(paths: ProjectPaths, market: str, data_kind: str) -> Path:
    return paths.data / ".cache" / f"{_CROSS_SECTION_STATE_PREFIX}_{market}_{data_kind}.json"


def _read_completed_trade_dates(paths: ProjectPaths, market: str, data_kind: str) -> set[str]:
    path = _cross_section_state_path(paths, market, data_kind)
    if not path.exists():
        return set()
    try:
        payload = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    return {
        date_key
        for date_key in payload.get("completed_trade_dates", [])
        if isinstance(date_key, str) and len(date_key) == 8 and date_key.isdigit()
    }


def _write_completed_trade_dates(paths: ProjectPaths, market: str, data_kind: str, trade_dates: set[str]) -> None:
    path = _cross_section_state_path(paths, market, data_kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "market": market,
        "data_kind": data_kind,
        "updated_at": datetime.now(UTC).isoformat(),
        "completed_trade_dates": sorted(trade_dates),
    }
    path.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _record_completed_trade_dates(paths: ProjectPaths, market: str, data_kind: str, trade_dates: list[str]) -> None:
    normalized = {
        date_key
        for date_key in trade_dates
        if isinstance(date_key, str) and len(date_key) == 8 and date_key.isdigit()
    }
    if not normalized:
        return
    completed = _read_completed_trade_dates(paths, market, data_kind)
    completed.update(normalized)
    _write_completed_trade_dates(paths, market, data_kind, completed)


def _clear_completed_trade_dates(paths: ProjectPaths, market: str, data_kind: str) -> None:
    path = _cross_section_state_path(paths, market, data_kind)
    if path.exists():
        path.unlink()


def _today_yyyymmdd() -> str:
    return datetime.now(UTC).date().strftime("%Y%m%d")


def _calendar_days_between(start_key: str, end_key: str) -> list[str]:
    try:
        start_d = datetime.strptime(start_key, "%Y%m%d").date()
        end_d = datetime.strptime(end_key, "%Y%m%d").date()
    except ValueError:
        return []
    if start_d > end_d:
        return []
    values: list[str] = []
    current = start_d
    while current <= end_d:
        values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def _date_window_for_request(
    paths: ProjectPaths,
    spec: TushareDatasetSpec,
    symbol_key: str | None,
    start: str | None,
    end: str | None,
    refresh_mode: str,
    full_history: bool = False,
    limit_calendar_span: bool = True,
) -> tuple[str | None, str | None]:
    if full_history:
        end_key = _coerce_yyyymmdd(end) or _today_yyyymmdd()
        end_d = datetime.strptime(end_key, "%Y%m%d").date()
        api_floor = end_d - timedelta(days=TUSHARE_MAX_CALENDAR_SPAN_DAYS) if limit_calendar_span else date(1990, 1, 1)
        if refresh_mode == "incremental":
            latest_end = _find_latest_end(paths, spec.market, spec.data_kind, symbol_key)
            if latest_end is not None:
                inc_start = latest_end + timedelta(days=1)
                if inc_start > end_d:
                    return None, None
                return inc_start.strftime("%Y%m%d"), end_key
        raw_list = lookup_ts_list_date(paths, spec.market, symbol_key) if symbol_key else None
        raw_start = raw_list or date(1990, 1, 1)
        start_d = max(raw_start, api_floor)
        if start_d > end_d:
            return None, None
        return start_d.strftime("%Y%m%d"), end_key

    start_key = _coerce_yyyymmdd(start)
    end_key = _coerce_yyyymmdd(end)
    if refresh_mode != "incremental" or start_key is not None:
        return start_key, end_key
    latest_end = _find_latest_end(paths, spec.market, spec.data_kind, symbol_key)
    if latest_end is None:
        return start_key, end_key
    return (latest_end + timedelta(days=1)).strftime("%Y%m%d"), end_key


def _resolve_trade_dates(
    paths: ProjectPaths,
    scheduler: TushareScheduler,
    *,
    market: str,
    start_key: str,
    end_key: str,
) -> list[str]:
    del paths
    trade_dates: set[str] = set()

    def _accumulate_calendar_rows(frame: Any) -> None:
        for row in _frame_to_records(frame):
            date_key = _coerce_yyyymmdd(row.get("cal_date") or row.get("trade_date"))
            if date_key is not None:
                trade_dates.add(date_key)

    if market == "stocks_cn":
        for chunk_start, chunk_end in chunk_yyyymmdd_window(start_key, end_key):
            frame = scheduler.call(
                "trade_cal",
                exchange="SSE",
                is_open="1",
                start_date=chunk_start,
                end_date=chunk_end,
            )
            _accumulate_calendar_rows(frame)
        return sorted(trade_dates)

    if market == "stocks_hk":
        for chunk_start, chunk_end in chunk_yyyymmdd_window(start_key, end_key):
            frame = scheduler.call(
                "hk_tradecal",
                is_open="1",
                start_date=chunk_start,
                end_date=chunk_end,
            )
            _accumulate_calendar_rows(frame)
        return sorted(trade_dates)

    if market == "stocks_us":
        for chunk_start, chunk_end in chunk_yyyymmdd_window(start_key, end_key):
            frame = scheduler.call(
                "us_tradecal",
                is_open="1",
                start_date=chunk_start,
                end_date=chunk_end,
            )
            _accumulate_calendar_rows(frame)
        return sorted(trade_dates)

    return _calendar_days_between(start_key, end_key)


def _should_use_trade_date_batches(
    spec: TushareDatasetSpec,
    *,
    symbol_mode: str,
    resolved_symbols: list[str],
) -> bool:
    if spec.fetch_mode != "trade_date_range":
        return False
    if symbol_mode == "all":
        return True
    threshold = spec.cross_section_symbol_threshold
    if threshold is None:
        return False
    return len(resolved_symbols) > threshold


def _build_symbol_range_batches(
    paths: ProjectPaths,
    spec: TushareDatasetSpec,
    *,
    resolved_symbols: list[str],
    start: str | None,
    end: str | None,
    refresh_mode: str,
    full_history: bool,
    variants: tuple[dict[str, Any], ...],
) -> list[PullBatch]:
    batches: list[PullBatch] = []
    for symbol in resolved_symbols:
        start_key, end_key = _date_window_for_request(paths, spec, symbol, start, end, refresh_mode, full_history)
        if not start_key or not end_key:
            continue
        date_chunks = (
            chunk_yyyymmdd_window(start_key, end_key)
            if spec.supports_date_range
            else [(start_key, end_key)]
        )
        for chunk_start, chunk_end in date_chunks:
            for variant in variants:
                params = {**spec.default_params, **variant, spec.symbol_field: symbol}
                if spec.supports_date_range:
                    params[spec.start_field] = chunk_start
                    params[spec.end_field] = chunk_end
                batches.append(
                    PullBatch(
                        spec=spec,
                        params=params,
                        label=f"{spec.data_kind}:{symbol}:{chunk_start}->{chunk_end}",
                    )
                )
    return batches


def _build_trade_date_batches(
    paths: ProjectPaths,
    spec: TushareDatasetSpec,
    scheduler: TushareScheduler,
    *,
    resolved_symbols: list[str],
    filter_symbols: bool,
    start: str | None,
    end: str | None,
    refresh_mode: str,
    full_history: bool,
    variants: tuple[dict[str, Any], ...],
) -> list[PullBatch]:
    start_key, end_key = _date_window_for_request(
        paths,
        spec,
        None,
        start,
        end,
        refresh_mode,
        full_history,
        limit_calendar_span=False,
    )
    if not start_key or not end_key:
        return []
    trade_dates = _resolve_trade_dates(paths, scheduler, market=spec.market, start_key=start_key, end_key=end_key)
    if refresh_mode == "incremental" and not filter_symbols:
        completed_dates = _read_completed_trade_dates(paths, spec.market, spec.data_kind)
        trade_dates = [date_key for date_key in trade_dates if date_key not in completed_dates]
    symbol_filter = tuple(resolved_symbols) if filter_symbols else ()
    batches: list[PullBatch] = []
    for trade_date in trade_dates:
        for variant in variants:
            params = {**spec.default_params, **variant, spec.trade_date_field: trade_date}
            batches.append(
                PullBatch(
                    spec=spec,
                    params=params,
                    label=f"{spec.data_kind}:{trade_date}",
                    symbol_filter=symbol_filter,
                )
            )
    return batches


def _build_batches(
    paths: ProjectPaths,
    spec: TushareDatasetSpec,
    scheduler: TushareScheduler,
    *,
    symbol_mode: str,
    symbols: list[str],
    stock_pool_id: str | None,
    preset_name: str | None,
    start: str | None,
    end: str | None,
    refresh_mode: str,
    full_history: bool = False,
) -> list[PullBatch]:
    variants = spec.request_variants or ({},)
    batches: list[PullBatch] = []
    if spec.fetch_mode == "static":
        for variant in variants:
            params = {**spec.default_params, **variant}
            batches.append(PullBatch(spec=spec, params=params, label=f"{spec.data_kind}:{variant or 'all'}"))
        return batches

    if spec.fetch_mode == "range":
        start_key, end_key = _date_window_for_request(paths, spec, None, start, end, refresh_mode, full_history)
        if not start_key or not end_key:
            return []
        date_chunks = (
            chunk_yyyymmdd_window(start_key, end_key)
            if spec.supports_date_range
            else [(start_key, end_key)]
        )
        for chunk_start, chunk_end in date_chunks:
            for variant in variants:
                params = {**spec.default_params, **variant}
                if spec.supports_date_range:
                    params[spec.start_field] = chunk_start
                    params[spec.end_field] = chunk_end
                batches.append(
                    PullBatch(
                        spec=spec,
                        params=params,
                        label=f"{spec.data_kind}:{chunk_start}->{chunk_end}",
                    )
                )
        return batches

    resolved_symbols = _resolve_symbols(paths, scheduler, spec.market, symbol_mode, symbols, stock_pool_id, preset_name)
    if spec.fetch_mode == "trade_date_range" and _should_use_trade_date_batches(
        spec,
        symbol_mode=symbol_mode,
        resolved_symbols=resolved_symbols,
    ):
        return _build_trade_date_batches(
            paths,
            spec,
            scheduler,
            resolved_symbols=resolved_symbols,
            filter_symbols=symbol_mode != "all",
            start=start,
            end=end,
            refresh_mode=refresh_mode,
            full_history=full_history,
            variants=variants,
        )
    return _build_symbol_range_batches(
        paths,
        spec,
        resolved_symbols=resolved_symbols,
        start=start,
        end=end,
        refresh_mode=refresh_mode,
        full_history=full_history,
        variants=variants,
    )


def _detect_year_column(columns: list[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in DATE_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    return None


# R28 双时态：first-seen 写层身份属性列（D-AXIS=A 写层 owns）。非身份键，是属性。
KNOWN_AT_COLUMN = "known_at"


def _spec_needs_known_at(spec: TushareDatasetSpec) -> bool:
    """财报/披露类 spec（unique_keys 含 ann_date）才需 first-seen known_at 轴。

    daily 等行情表 unique_keys=(ts_code,trade_date) 不含 ann_date → 不造 known_at、走原路径。
    """

    return "ann_date" in spec.unique_keys


def _derive_known_at(frame: pl.DataFrame) -> pl.DataFrame:
    """给财报行派生 first-seen known_at = ann_date；脏/空 ann_date → 落写入日期下界。

    R28 / GOAL §8：Tushare f_ann_date 脏数据（复用 ann_date / null / 不可解析）→ 落 first-seen
    （写入当日，永不泄漏未来）。幂等：已存在的非空 known_at 原样保留，不被新派生值覆盖
    （existing CSV 读回的历史 first-seen 守住；keep-first 在 _upsert_partition 再兜一层）。
    """

    if frame.is_empty():
        return frame
    today = _utc_now().date()
    if "ann_date" in frame.columns:
        ann = pl.col("ann_date").cast(pl.Utf8).str.strip_chars()
        ann_date = pl.coalesce(
            [
                ann.str.to_date(format="%Y%m%d", strict=False),
                ann.str.to_date(format="%Y-%m-%d", strict=False),
            ]
        )
    else:
        ann_date = pl.lit(None, dtype=pl.Date)
    derived = pl.coalesce([ann_date, pl.lit(today, dtype=pl.Date)])
    if KNOWN_AT_COLUMN in frame.columns:
        existing = pl.col(KNOWN_AT_COLUMN).cast(pl.Date, strict=False)
        derived = pl.coalesce([existing, derived])
    return frame.with_columns(derived.alias(KNOWN_AT_COLUMN))


def _prepare_frame_for_write(spec: TushareDatasetSpec, frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    working = frame
    if "symbol" in spec.partition_by and spec.symbol_field in working.columns and "symbol" not in working.columns:
        working = working.with_columns(pl.col(spec.symbol_field).cast(pl.Utf8).alias("symbol"))
    if "year" in spec.partition_by and "year" not in working.columns:
        date_column = _detect_year_column(working.columns)
        if date_column is not None:
            working = working.with_columns(pl.col(date_column).cast(pl.Utf8).str.slice(0, 4).alias("year"))
    # R28：财报类落 first-seen known_at（行情类不受影响）。year 分区仍按 ann_date（既有），互不干扰。
    if _spec_needs_known_at(spec):
        working = _derive_known_at(working)
    return working


def _apply_batch_symbol_filter(batch: PullBatch, frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or not batch.symbol_filter:
        return frame
    symbol_col = next(
        (
            column
            for column in (batch.spec.symbol_field, "ts_code", "symbol", "security")
            if column in frame.columns
        ),
        None,
    )
    if symbol_col is None:
        return frame
    return frame.filter(
        pl.col(symbol_col).cast(pl.Utf8).str.to_uppercase().is_in(list(batch.symbol_filter))
    )


def _batch_materialize_symbols(batch: PullBatch) -> tuple[str, ...]:
    if batch.symbol_filter:
        return tuple(
            str(symbol).strip().upper()
            for symbol in batch.symbol_filter
            if str(symbol).strip()
        )
    if not batch.spec.supports_symbols:
        return ()
    raw = batch.params.get(batch.spec.symbol_field)
    if raw is None or not str(raw).strip():
        return ()
    return (str(raw).strip().upper(),)


def _sort_columns(frame: pl.DataFrame) -> list[str]:
    return [column for column in ("symbol", "ts_code", "trade_date", "ann_date", "end_date", "publish_date", "known_at") if column in frame.columns]


def _partition_path(paths: ProjectPaths, spec: TushareDatasetSpec, row_frame: pl.DataFrame) -> Path:
    if not spec.partition_by:
        return paths.market_dataset_partition_file(spec.market, spec.data_kind)
    parts = [f"{column}={row_frame.item(0, column)}" for column in spec.partition_by]
    return paths.market_dataset_partition_file(spec.market, spec.data_kind, *parts)


def _upsert_partition(path: Path, frame: pl.DataFrame, unique_keys: tuple[str, ...]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        try:
            existing = pl.read_csv(path, try_parse_dates=True)
        except Exception:  # noqa: BLE001
            existing = pl.DataFrame()
        combined = pl.concat([existing, frame], how="diagonal_relaxed") if existing.height else frame
    else:
        combined = frame
    # known_at 是属性列、非身份键：从 dedup 子集剔除（防御未来误入 unique_keys）。
    dedupe_keys = [key for key in unique_keys if key in combined.columns and key != KNOWN_AT_COLUMN]
    if KNOWN_AT_COLUMN in combined.columns and dedupe_keys:
        # R28 双时态：同身份多 known_at 取最早（keep-first）= first-seen own + re-backfill 不推进。
        # 不同 ann_date 的重述身份不同 → 各自成行保留；同 ann_date 脏重述 → 守住首披 known_at。
        combined = combined.sort(KNOWN_AT_COLUMN, nulls_last=True).unique(
            subset=dedupe_keys, keep="first", maintain_order=True
        )
    elif dedupe_keys:
        combined = combined.unique(subset=dedupe_keys, keep="last", maintain_order=True)  # 行情类原行为
    else:
        combined = combined.unique(keep="last", maintain_order=True)  # 原行为
    sort_cols = _sort_columns(combined)
    if sort_cols:
        combined = combined.sort(sort_cols)
    combined.write_csv(path)
    return int(combined.height)


def _write_dataset_frame(paths: ProjectPaths, spec: TushareDatasetSpec, frame: pl.DataFrame) -> set[str]:
    prepared = _prepare_frame_for_write(spec, frame)
    if prepared.is_empty():
        return set()
    if not spec.partition_by:
        target = _partition_path(paths, spec, prepared)
        _upsert_partition(target, prepared, spec.unique_keys)
        return {str(target)}
    written: set[str] = set()
    for part in prepared.partition_by(list(spec.partition_by), maintain_order=True):
        target = _partition_path(paths, spec, part)
        _upsert_partition(target, part, spec.unique_keys)
        written.add(str(target))
    return written


def _clear_dataset(paths: ProjectPaths, market: str, data_kind: str) -> None:
    target = paths.market_dataset_dir(market, data_kind)
    if target.exists():
        shutil.rmtree(target)


def _read_market_dataset_frame(paths: ProjectPaths, market: str, data_kind: str) -> pl.DataFrame:
    latest_dir = paths.market_dataset_latest_dir(market, data_kind)
    if not latest_dir.exists():
        return pl.DataFrame()
    csv_files = sorted(latest_dir.rglob("*.csv"))
    if csv_files:
        parts: list[pl.DataFrame] = []
        for fp in csv_files:
            try:
                parts.append(pl.read_csv(fp, try_parse_dates=True))
            except Exception:  # noqa: BLE001
                continue
        if not parts:
            return pl.DataFrame()
        return pl.concat(parts, how="diagonal_relaxed")
    pq_files = [str(p) for p in latest_dir.rglob("*.parquet")]
    if not pq_files:
        return pl.DataFrame()
    return pl.scan_parquet(pq_files, hive_partitioning=True).collect()


def _first_populated_dataset(
    paths: ProjectPaths,
    market: str,
    candidates: tuple[str, ...],
) -> tuple[str | None, pl.DataFrame]:
    for data_kind in candidates:
        frame = _read_market_dataset_frame(paths, market, data_kind)
        if not frame.is_empty():
            return data_kind, frame
    return None, pl.DataFrame()


def _date_expr(frame: pl.DataFrame, column: str) -> pl.Expr:
    dtype = frame.schema.get(column)
    if dtype == pl.Date:
        return pl.col(column)
    if isinstance(dtype, pl.Datetime):
        return pl.col(column).dt.date()
    if dtype in (pl.Int32, pl.Int64):
        return (
            pl.col(column)
            .cast(pl.Utf8)
            .str.zfill(8)
            .str.strptime(pl.Date, "%Y%m%d", strict=False)
        )
    raw = pl.col(column).cast(pl.Utf8)
    return pl.coalesce(
        raw.str.strptime(pl.Date, "%Y%m%d", strict=False),
        raw.str.strptime(pl.Date, "%Y-%m-%d", strict=False),
    )


def _prepare_runtime_price_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame()
    symbol_col = next((column for column in ("symbol", "ts_code", "security") if column in frame.columns), None)
    date_col = next((column for column in ("trade_date", "date", "cal_date", "nav_date", "timestamp", "datetime") if column in frame.columns), None)
    if symbol_col is None or date_col is None or "close" not in frame.columns:
        return pl.DataFrame()
    metric_sources = {
        "open": ("open",),
        "high": ("high",),
        "low": ("low",),
        "close": ("close",),
        "volume": ("volume", "vol"),
        "amount": ("amount",),
    }
    expressions: list[pl.Expr] = [
        pl.col(symbol_col).cast(pl.Utf8).str.to_uppercase().alias("symbol"),
        _date_expr(frame, date_col).alias("timestamp"),
    ]
    for output, candidates in metric_sources.items():
        source = next((column for column in candidates if column in frame.columns), None)
        if source is not None:
            expressions.append(pl.col(source).cast(pl.Float64).alias(output))
    prepared = frame.select(expressions)
    if "volume" not in prepared.columns:
        prepared = prepared.with_columns(pl.lit(0.0).alias("volume"))
    return prepared.unique(subset=["symbol", "timestamp"], keep="last", maintain_order=True).sort(["symbol", "timestamp"])


def _prepare_adjustment_factor_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame()
    symbol_col = next((column for column in ("symbol", "ts_code", "security") if column in frame.columns), None)
    date_col = next((column for column in ("trade_date", "date", "timestamp", "datetime") if column in frame.columns), None)
    factor_col = next(
        (
            column
            for column in ("adj_factor", "qfq_factor", "hfq_factor", "cum_adj_factor", "factor")
            if column in frame.columns
        ),
        None,
    )
    if symbol_col is None or date_col is None or factor_col is None:
        return pl.DataFrame()
    return (
        frame.select(
            pl.col(symbol_col).cast(pl.Utf8).str.to_uppercase().alias("symbol"),
            _date_expr(frame, date_col).alias("timestamp"),
            pl.col(factor_col).cast(pl.Float64).alias("adj_factor"),
        )
        .unique(subset=["symbol", "timestamp"], keep="last", maintain_order=True)
        .sort(["symbol", "timestamp"])
    )


def _merge_runtime_adjustment_factor(
    price_frame: pl.DataFrame,
    adj_frame: pl.DataFrame,
    *,
    apply_adjustment: bool = False,
) -> pl.DataFrame:
    """把 adj_factor 真**乘进** OHLC（后复权连续价 qfq），杜绝『未复权价喂回测/成交层』(RULES 停工红线)。

    数学（qfq·recent-preserving）：每 symbol 按 timestamp 升序，qfq(t)=adj_factor(t)/adj_factor(T)，T=该 symbol
    最新交易日；P_adj=P_raw·qfq（open/high/low/close），volume 反向 V_adj=V_raw/qfq（守 P·V 值不变）。除权除息日的
    价格跳变被归一消除 → IC/回测看到的收益=纯价格 alpha、不含股本结构跳变。

    `apply_adjustment`（调用方据价源是否**原始未复权**[_RAW_PRICE_SOURCES]决定）：
    - True + adj_frame 非空 → 乘 adj 复权。
    - True + adj_frame 空 → **raise**（原始未复权源缺 adj：绝不写未复权价喂成交层·不假绿）。
    - False（价源已复权，如 us_daily_adj）→ 原样返回，**绝不再乘 adj**（防双重复权）。
    join 后个别行缺 adj（adj 覆盖不全）→ 该 symbol 内 forward/backward fill（adj_factor 累积、事件间稳定）。
    """

    if price_frame.is_empty():
        return price_frame
    if not apply_adjustment:
        return price_frame.sort(["symbol", "timestamp"])
    if adj_frame.is_empty():
        raise ValueError(
            "原始未复权价源缺 adj_factor：拒绝写未复权价喂回测/成交层（RULES 停工红线·未复权价即假收益）"
        )
    merged = price_frame.join(adj_frame, on=["symbol", "timestamp"], how="left").sort(["symbol", "timestamp"])
    # 缺 adj 行（adj 覆盖不全）→ symbol 内前向后向填充（累积因子事件间稳定）；仍全空 symbol 极罕见 → 留 null 由下游暴露。
    merged = merged.with_columns(
        pl.col("adj_factor").forward_fill().backward_fill().over("symbol")
    )
    qfq = pl.col("adj_factor") / pl.col("adj_factor").last().over("symbol")  # 末值=最新日因子（已按 timestamp 升序）
    adjust_exprs = [
        (pl.col(col) * qfq).alias(col)
        for col in ("open", "high", "low", "close")
        if col in merged.columns
    ]
    if "volume" in merged.columns:
        adjust_exprs.append((pl.col("volume") / qfq).alias("volume"))
    merged = merged.with_columns(adjust_exprs)
    return merged.drop("adj_factor").sort(["symbol", "timestamp"])


def _write_runtime_market_bars(
    paths: ProjectPaths,
    *,
    market: str,
    interval: str,
    frame: pl.DataFrame,
) -> list[str]:
    if frame.is_empty():
        return []
    written: list[str] = []
    for part in frame.partition_by(["symbol"], maintain_order=True):
        symbol = str(part.item(0, "symbol"))
        target = paths.market_data_file(market, interval, normalize_symbol_key(market, symbol), file_format="csv")
        target.parent.mkdir(parents=True, exist_ok=True)
        part.drop("symbol").write_csv(target)
        written.append(str(target))
    return written


def _write_partitioned_runtime_dataset(
    paths: ProjectPaths,
    *,
    market: str,
    data_kind: str,
    frame: pl.DataFrame,
    partition_by: tuple[str, ...],
    unique_keys: tuple[str, ...],
) -> list[str]:
    if frame.is_empty():
        return []
    written: list[str] = []
    for part in frame.partition_by(list(partition_by), maintain_order=True):
        target = paths.market_dataset_partition_file(
            market,
            data_kind,
            *[f"{column}={part.item(0, column)}" for column in partition_by],
        )
        _upsert_partition(target, part, unique_keys)
        written.append(str(target))
    return written


def _prepare_daily_basic_compat_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame()
    symbol_col = next((column for column in ("symbol", "ts_code", "security") if column in frame.columns), None)
    date_col = next((column for column in ("trade_date", "date", "timestamp", "datetime") if column in frame.columns), None)
    if symbol_col is None or date_col is None:
        return pl.DataFrame()
    compat_map = {
        "turnover_ratio": ("turnover_ratio", "turnover_rate", "turnover"),
        "pe": ("pe", "pe_ttm"),
        "pb": ("pb", "pb_ratio"),
        "total_mv": ("total_mv", "market_cap"),
        "circ_mv": ("circ_mv", "circulating_market_cap", "float_mv"),
    }
    expressions: list[pl.Expr] = [
        pl.col(symbol_col).cast(pl.Utf8).str.to_uppercase().alias("symbol"),
        _date_expr(frame, date_col).alias("timestamp"),
    ]
    populated_metrics = 0
    for output, candidates in compat_map.items():
        source = next((column for column in candidates if column in frame.columns), None)
        if source is None:
            continue
        expressions.append(pl.col(source).cast(pl.Float64).alias(output))
        populated_metrics += 1
    if populated_metrics == 0:
        return pl.DataFrame()
    prepared = frame.select(expressions).with_columns(pl.col("timestamp").dt.year().cast(pl.Utf8).alias("year"))
    return prepared.unique(subset=["symbol", "timestamp"], keep="last", maintain_order=True).sort(["symbol", "timestamp"])


def _filter_runtime_symbols(frame: pl.DataFrame, symbols: list[str] | None) -> pl.DataFrame:
    if frame.is_empty() or not symbols or "symbol" not in frame.columns:
        return frame
    normalized = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not normalized:
        return frame
    return frame.filter(pl.col("symbol").cast(pl.Utf8).str.to_uppercase().is_in(normalized))


def _materialize_tushare_runtime_assets(
    paths: ProjectPaths,
    *,
    market: str,
    symbols: list[str] | None,
) -> dict[str, Any]:
    if market not in _RUNTIME_PRICE_SOURCE_CANDIDATES:
        return {}
    runtime: dict[str, Any] = {
        "ohlcv": {"written": [], "source": None},
        "adj_factor": {"available": False, "source": None},
        "daily_basic": {"written": [], "source": None, "status": "not_applicable"},
    }
    price_source, price_raw = _first_populated_dataset(paths, market, _RUNTIME_PRICE_SOURCE_CANDIDATES[market])
    price_frame = _filter_runtime_symbols(_prepare_runtime_price_frame(price_raw), symbols)
    adj_source, adj_raw = _first_populated_dataset(paths, market, _RUNTIME_ADJ_FACTOR_CANDIDATES.get(market, ()))
    adj_frame = _filter_runtime_symbols(_prepare_adjustment_factor_frame(adj_raw), symbols)
    if not price_frame.is_empty():
        # 源感知复权：原始未复权源（_RAW_PRICE_SOURCES）必须乘 adj 复权后才落盘；已复权源绝不再乘（防双重复权）。
        apply_adjustment = price_source in _RAW_PRICE_SOURCES
        price_frame = _merge_runtime_adjustment_factor(price_frame, adj_frame, apply_adjustment=apply_adjustment)
        runtime["ohlcv"] = {
            "source": price_source,
            "written": _write_runtime_market_bars(paths, market=market, interval="1d", frame=price_frame),
        }
    runtime["adj_factor"] = {"available": not adj_frame.is_empty(), "source": adj_source}

    if market in {"stocks_us", "stocks_hk"}:
        basic_source, basic_raw = _first_populated_dataset(paths, market, _RUNTIME_PRICE_SOURCE_CANDIDATES[market])
        basic_frame = _filter_runtime_symbols(_prepare_daily_basic_compat_frame(basic_raw), symbols)
        if not basic_frame.is_empty():
            runtime["daily_basic"] = {
                "source": basic_source,
                "written": _write_partitioned_runtime_dataset(
                    paths,
                    market=market,
                    data_kind="daily_basic",
                    frame=basic_frame,
                    partition_by=("symbol", "year"),
                    unique_keys=("symbol", "timestamp"),
                ),
                "status": "materialized",
            }
        elif market == "stocks_hk":
            runtime["daily_basic"] = {
                "source": basic_source,
                "written": [],
                "status": "unsupported_by_public_fields",
            }
        else:
            runtime["daily_basic"] = {
                "source": basic_source,
                "written": [],
                "status": "missing_source_fields",
            }
    return runtime


def _serialize_failed_tokens(items: tuple[TokenStatus, ...]) -> list[dict[str, Any]]:
    return [
        {
            "slot": item.slot,
            "token_mask": item.token_mask,
            "points": item.points,
            "expires_at": item.expires_at,
            "error": item.error,
        }
        for item in items
    ]


def run_tushare_data_pull(
    paths: ProjectPaths,
    *,
    market: str,
    data_kind: str,
    symbol_mode: str,
    symbols: list[str] | None = None,
    stock_pool_id: str | None = None,
    preset_name: str | None = None,
    start: str | None = None,
    end: str | None = None,
    refresh_mode: str = "incremental",
    full_history: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    symbols = symbols or []

    def report(stage_key: str, message: str, *, percent: int | None = None, stats: dict[str, Any] | None = None) -> None:
        if progress_callback is None:
            return
        progress_callback(stage_key, message, percent=percent, stats=stats)

    report("prepare_request", f"Preparing {market}/{data_kind} request.", percent=5)
    validation = validate_tushare_tokens(force_refresh=False)
    pool = _build_pool(validation)
    _log.info(
        "Token pool ready: %d clients, combined RPM %d.",
        len(pool.clients),
        sum(c.rpm_limit for c in pool.clients),
    )
    report(
        "validate_tokens",
        f"Healthy tokens: {len(validation.healthy_tokens)}/{validation.configured_slots}.",
        percent=15,
        stats={
            "tokens_total": validation.configured_slots,
            "tokens_healthy": len(validation.healthy_tokens),
            "healthy_token_points": validation.healthy_points,
        },
    )

    enabled_specs = get_enabled_tushare_dataset_specs(market, validation=validation)
    spec = next((item for item in enabled_specs if item.data_kind == data_kind), None)
    if spec is None:
        available = [item.data_kind for item in enabled_specs]
        raise ValueError(
            f"Dataset `{data_kind}` is not enabled for market `{market}` with effective points ceiling "
            f"{validation.effective_points_ceiling}. Available: {available}"
        )

    skipped_by_permission = [
        item.data_kind
        for item in get_tushare_dataset_specs(market)
        if item.required_points > (validation.effective_points_ceiling or 0)
    ]
    report(
        "resolve_permissions",
        f"Effective points ceiling is {validation.effective_points_ceiling}.",
        percent=25,
        stats={
            "effective_points_ceiling": validation.effective_points_ceiling,
            "datasets_enabled": [item.data_kind for item in enabled_specs],
            "skipped_by_permission": skipped_by_permission,
        },
    )

    batches = _build_batches(
        paths,
        spec,
        pool,
        symbol_mode=symbol_mode,
        symbols=symbols,
        stock_pool_id=stock_pool_id,
        preset_name=preset_name,
        start=start,
        end=end,
        refresh_mode=refresh_mode,
        full_history=full_history,
    )
    report(
        "resolve_targets",
        f"Resolved {len(batches)} batches for {data_kind}.",
        percent=35,
        stats={"total_batches": len(batches), "symbol_mode": symbol_mode},
    )

    if refresh_mode == "full" and batches:
        _clear_dataset(paths, market, data_kind)
        _clear_completed_trade_dates(paths, market, data_kind)

    written_files: set[str] = set()
    failed_batches: list[dict[str, Any]] = []
    total_rows_written = 0
    total_batches = len(batches)
    retries_triggered = 0
    completed_trade_dates_by_dataset: dict[tuple[str, str], set[str]] = {}
    use_concurrent = len(pool.clients) > 1 and total_batches > 1

    if use_concurrent:
        import queue as queue_module

        # Queue items are (PullBatch, attempt_number)
        work_queue: queue.Queue[tuple[PullBatch, int] | None] = queue_module.Queue()
        for batch in batches:
            work_queue.put((batch, 0))
        for _ in pool.clients:
            work_queue.put(None)

        batch_results: list[tuple[PullBatch, pl.DataFrame]] = []
        batch_errors: list[dict[str, Any]] = []
        completed_count = [0]
        retries_count = [0]
        concurrent_lock = threading.Lock()

        def _worker(_pool: TokenPool) -> None:
            while True:
                raw_item = work_queue.get()
                if raw_item is None:
                    break
                batch_item, attempt = raw_item
                client = _pool.pick_client(batch_item.spec.api_name)
                try:
                    raw_frame = client.call(batch_item.spec.api_name, batch_item.params)
                    frame = _apply_batch_symbol_filter(batch_item, _to_polars_frame(raw_frame))
                    with concurrent_lock:
                        if batch_item.spec.fetch_mode == "trade_date_range" and not batch_item.symbol_filter:
                            trade_date = _coerce_yyyymmdd(batch_item.params.get(batch_item.spec.trade_date_field))
                            if trade_date is not None:
                                completed_trade_dates_by_dataset.setdefault(
                                    (batch_item.spec.market, batch_item.spec.data_kind),
                                    set(),
                                ).add(trade_date)
                        if not frame.is_empty():
                            batch_results.append((batch_item, frame))
                        completed_count[0] += 1
                        done = completed_count[0]
                except Exception as exc:  # noqa: BLE001
                    if _is_rate_limit_error(str(exc)) and attempt < MAX_RETRIES:
                        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                        _log.info("Rate-limited on %s (attempt %d), retrying in %.0fs.", batch_item.label, attempt + 1, delay)
                        time.sleep(delay)
                        work_queue.put((batch_item, attempt + 1))
                        with concurrent_lock:
                            retries_count[0] += 1
                        continue
                    with concurrent_lock:
                        batch_errors.append({
                            "label": batch_item.label, "params": batch_item.params,
                            "error": str(exc), "attempts": attempt + 1,
                        })
                        completed_count[0] += 1
                        done = completed_count[0]
                pct = 35 if total_batches == 0 else min(80, 35 + int(round((done / total_batches) * 45)))
                report(
                    "pull_batches",
                    f"Pulling {batch_item.label} ({done}/{total_batches}) [{client.token_mask}]",
                    percent=pct,
                    stats={
                        "current_dataset": batch_item.spec.data_kind,
                        "current_batch": done,
                        "total_batches": total_batches,
                        "failed_batches": len(batch_errors),
                        "healthy_tokens": len(pool.clients),
                        "concurrent_workers": len(pool.clients),
                        "retries": retries_count[0],
                    },
                )

        worker_threads = [
            threading.Thread(target=_worker, args=(pool,), daemon=True)
            for _ in pool.clients
        ]
        for t in worker_threads:
            t.start()
        for t in worker_threads:
            t.join()

        failed_batches.extend(batch_errors)
        retries_triggered = retries_count[0]
        report("write_csv", f"Writing {len(batch_results)} result frames.", percent=85)
        for batch, frame in batch_results:
            written_files.update(_write_dataset_frame(paths, batch.spec, frame))
            total_rows_written += int(frame.height)
    else:
        for index, batch in enumerate(batches, start=1):
            stage_percent = 35 if total_batches == 0 else min(80, 35 + int(round((index / total_batches) * 45)))
            report(
                "pull_batches",
                f"Pulling {batch.label} ({index}/{total_batches}).",
                percent=stage_percent,
                stats={
                    "current_dataset": batch.spec.data_kind,
                    "current_batch": index,
                    "total_batches": total_batches,
                    "failed_batches": len(failed_batches),
                    "healthy_tokens": len(validation.healthy_tokens),
                },
            )
            last_exc: Exception | None = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    raw_frame = pool.call(batch.spec.api_name, **batch.params)
                    frame = _apply_batch_symbol_filter(batch, _to_polars_frame(raw_frame))
                    last_exc = None
                    if batch.spec.fetch_mode == "trade_date_range" and not batch.symbol_filter:
                        trade_date = _coerce_yyyymmdd(batch.params.get(batch.spec.trade_date_field))
                        if trade_date is not None:
                            completed_trade_dates_by_dataset.setdefault(
                                (batch.spec.market, batch.spec.data_kind),
                                set(),
                            ).add(trade_date)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if _is_rate_limit_error(str(exc)) and attempt < MAX_RETRIES:
                        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                        _log.info("Rate-limited on %s (attempt %d), retrying in %.0fs.", batch.label, attempt + 1, delay)
                        time.sleep(delay)
                        retries_triggered += 1
                        continue
                    break
            if last_exc is not None:
                failed_batches.append({"label": batch.label, "params": batch.params, "error": str(last_exc)})
                continue
            if frame.is_empty():
                continue
            report(
                "write_csv",
                f"Writing CSV partitions for {batch.label}.",
                percent=min(90, stage_percent + 5),
                stats={
                    "current_dataset": batch.spec.data_kind,
                    "current_batch": index,
                    "total_batches": total_batches,
                    "failed_batches": len(failed_batches),
                },
            )
            written_files.update(_write_dataset_frame(paths, batch.spec, frame))
            total_rows_written += int(frame.height)

    for (completed_market, completed_kind), trade_dates in completed_trade_dates_by_dataset.items():
        _record_completed_trade_dates(paths, completed_market, completed_kind, sorted(trade_dates))

    pool.flush_daily_usage(force=True)
    _log.info(
        "Pull complete: %d rows, %d files, %d retries, %d failed batches. Usage: %s",
        total_rows_written, len(written_files), retries_triggered, len(failed_batches),
        {c.token_mask: sum(c.daily_api_calls.values()) for c in pool.clients},
    )

    materialize_symbols = sorted(
        {
            symbol
            for batch in batches
            for symbol in _batch_materialize_symbols(batch)
        }
    )
    report("materialize_runtime", "Materializing runtime-compatible data assets.", percent=92)
    runtime_assets = _materialize_tushare_runtime_assets(
        paths,
        market=market,
        symbols=materialize_symbols or None,
    )

    report("rebuild_catalog", "Rebuilding data catalog.", percent=95)
    catalog_payload = rebuild_data_catalog(paths)
    report("finalize", "Finalizing job result.", percent=99)

    return {
        "market": market,
        "data_kind": data_kind,
        "tokens_total": validation.configured_slots,
        "tokens_healthy": len(validation.healthy_tokens),
        "healthy_token_points": validation.healthy_points,
        "healthy_tokens": [
            {
                "slot": item.slot,
                "token_mask": item.token_mask,
                "points": item.points,
                "expires_at": item.expires_at,
            }
            for item in validation.healthy_tokens
        ],
        "failed_tokens": _serialize_failed_tokens(validation.failed_tokens),
        "effective_points_ceiling": validation.effective_points_ceiling,
        "datasets_enabled": [item.data_kind for item in enabled_specs],
        "datasets_written": [data_kind] if written_files else [],
        "files_written": len(written_files),
        "written_file_paths": sorted(written_files),
        "rows_written": total_rows_written,
        "api_calls_by_token": pool.api_calls_by_token(),
        "retries_triggered": retries_triggered,
        "failed_batches": failed_batches,
        "completed_trade_dates": sorted(
            completed_trade_dates_by_dataset.get((market, data_kind), set())
        ),
        "skipped_by_permission": skipped_by_permission,
        "runtime_assets": runtime_assets,
        "catalog_version": int(catalog_payload.get("catalog_version") or 1),
    }
