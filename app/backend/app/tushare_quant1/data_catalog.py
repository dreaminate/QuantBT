from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from .market_data import MARKET_ALIASES, SUPPORTED_INTERVALS, normalize_symbol_key
from .project_paths import ProjectPaths


CATALOG_VERSION = 3
IGNORED_FILE_STEMS = {"fetch_failures"}
TIMESTAMP_COLUMN_CANDIDATES = (
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


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug.strip("._") or "preset"


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return None
    # ``datetime`` is a subclass of ``date``; Polars min/max may return ``date`` or ``datetime``.
    if isinstance(value, date):
        return value.isoformat()
    return value


def _min_optional(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _max_optional(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _detect_timestamp_column(columns: list[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in TIMESTAMP_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _csv_file_stats(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        timestamp_column = _detect_timestamp_column(columns)
        row_count = 0
        start: str | None = None
        end: str | None = None
        for row in reader:
            row_count += 1
            if timestamp_column is None:
                continue
            value = row.get(timestamp_column)
            if value is None or value == "":
                continue
            if start is None:
                start = value
            end = value
    return {"row_count": row_count, "start": start, "end": end, "columns": columns}


def _parquet_file_stats(path: Path) -> dict[str, Any]:
    schema = pl.read_parquet_schema(path)
    columns = list(schema.keys())
    timestamp_column = _detect_timestamp_column(columns)
    expressions: list[pl.Expr] = [pl.len().alias("row_count")]
    if timestamp_column is not None:
        expressions.extend([pl.col(timestamp_column).min().alias("start"), pl.col(timestamp_column).max().alias("end")])
    stats = pl.scan_parquet(str(path)).select(expressions).collect()
    row = stats.to_dicts()[0] if stats.height > 0 else {"row_count": 0, "start": None, "end": None}
    return {
        "row_count": int(row.get("row_count") or 0),
        "start": _normalize_cell(row.get("start")),
        "end": _normalize_cell(row.get("end")),
        "columns": columns,
    }


def inspect_market_data_file(path: Path, file_format: str) -> dict[str, Any]:
    if file_format == "csv":
        return _csv_file_stats(path)
    if file_format == "parquet":
        return _parquet_file_stats(path)
    raise ValueError(f"Unsupported file format `{file_format}`.")


def _inventory_payload(paths: ProjectPaths) -> dict[str, Any]:
    inventory_path = paths.data_catalog_inventory_file
    if not inventory_path.exists():
        return {"catalog_version": CATALOG_VERSION, "generated_at": None, "overview": [], "files": []}
    return json.loads(inventory_path.read_text(encoding="utf-8"))


def _normalize_market(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower().replace("-", "_")
    return MARKET_ALIASES.get(raw) or MARKET_ALIASES.get(raw.replace("_", "")) or raw


def _normalize_interval(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _normalize_data_kind(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _file_id_for_path(paths: ProjectPaths, path: Path) -> str:
    relative = path.relative_to(paths.root).as_posix()
    return hashlib.sha1(relative.encode("utf-8")).hexdigest()[:16]


def _partition_string(parts: list[str]) -> str:
    return "/".join(parts)


def _build_legacy_file_item(
    paths: ProjectPaths,
    *,
    market: str,
    interval: str,
    symbol_key: str,
    format_paths: dict[str, Path],
) -> dict[str, Any]:
    preferred_format = "parquet" if "parquet" in format_paths else "csv"
    preferred_path = format_paths[preferred_format]
    stats = inspect_market_data_file(preferred_path, preferred_format)
    return {
        "file_id": _file_id_for_path(paths, preferred_path),
        "market": market,
        "interval": interval,
        "data_kind": "ohlcv",
        "symbol_key": symbol_key,
        "partition": f"interval={interval}/symbol={symbol_key}",
        "formats": sorted(format_paths.keys()),
        "preferred_format": preferred_format,
        "file_path": str(preferred_path),
        "row_count": stats["row_count"],
        "start": stats["start"],
        "end": stats["end"],
        "columns": stats.get("columns") or [],
        "updated_at": max(_mtime_iso(path) for path in format_paths.values()),
    }


def _scan_legacy_market(paths: ProjectPaths, market: str, interval: str) -> list[dict[str, Any]]:
    directory = paths.market_data_dir(market, interval)
    if not directory.exists():
        return []
    symbol_files: dict[str, dict[str, Path]] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        file_format = path.suffix.lower().lstrip(".")
        if file_format not in {"csv", "parquet"} or path.stem.lower() in IGNORED_FILE_STEMS:
            continue
        # 浏览/预览：同时收录 csv 与 parquet，避免仅磁盘仍为 csv 时列表为空；同 stem 时 preferred 见 _build_legacy_file_item。
        symbol_files.setdefault(path.stem, {})[file_format] = path
    return [
        _build_legacy_file_item(paths, market=market, interval=interval, symbol_key=symbol_key, format_paths=format_paths)
        for symbol_key, format_paths in sorted(symbol_files.items())
    ]


def _scan_dataset_market(paths: ProjectPaths, market: str, data_kind: str) -> list[dict[str, Any]]:
    latest_dir = paths.market_dataset_latest_dir(market, data_kind)
    if not latest_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    discovered = sorted({*latest_dir.rglob("*.csv"), *latest_dir.rglob("*.parquet")})
    for path in discovered:
        relative_parent = path.parent.relative_to(latest_dir)
        partition_parts = [part for part in relative_parent.parts if part]
        partition_map: dict[str, str] = {}
        for part in partition_parts:
            if "=" not in part:
                continue
            key, value = part.split("=", maxsplit=1)
            partition_map[key] = value
        fmt = "csv" if path.suffix.lower() == ".csv" else "parquet"
        stats = inspect_market_data_file(path, fmt)
        items.append(
            {
                "file_id": _file_id_for_path(paths, path),
                "market": market,
                "interval": partition_map.get("interval"),
                "data_kind": data_kind,
                "symbol_key": partition_map.get("symbol"),
                "partition": _partition_string(partition_parts),
                "formats": [fmt],
                "preferred_format": fmt,
                "file_path": str(path),
                "row_count": stats["row_count"],
                "start": stats["start"],
                "end": stats["end"],
                "columns": stats.get("columns") or [],
                "updated_at": _mtime_iso(path),
            }
        )
    return items


def load_data_catalog(paths: ProjectPaths, *, rebuild_if_missing: bool = False) -> dict[str, Any]:
    if rebuild_if_missing and not paths.data_catalog_inventory_file.exists():
        rebuild_data_catalog(paths)
    return _inventory_payload(paths)


def clear_data_presets(paths: ProjectPaths, *, source: str | None = None) -> None:
    for path in paths.data_catalog_presets.glob("*.json"):
        if source is None:
            path.unlink(missing_ok=True)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source") == source:
            path.unlink(missing_ok=True)


def list_data_presets(paths: ProjectPaths) -> list[dict[str, Any]]:
    presets: list[dict[str, Any]] = []
    if not paths.data_catalog_presets.exists():
        return presets
    for path in sorted(paths.data_catalog_presets.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        normalized_market = _normalize_market(payload.get("market")) or str(payload.get("market") or "")
        symbols = sorted(dict.fromkeys(str(item).strip().upper() for item in payload.get("symbols") or [] if str(item).strip()))
        presets.append(
            {
                "preset_name": str(payload.get("preset_name") or "").strip(),
                "market": normalized_market,
                "symbols": symbols,
                "symbol_count": len(symbols),
                "source": payload.get("source"),
                "imported_at": payload.get("imported_at"),
            }
        )
    return presets


def rebuild_data_catalog(paths: ProjectPaths) -> dict[str, Any]:
    paths.ensure()
    file_items: list[dict[str, Any]] = []
    for market_dir in (sorted(paths.data_market.iterdir()) if paths.data_market.exists() else []):
        if not market_dir.is_dir():
            continue
        market = market_dir.name
        legacy_intervals = SUPPORTED_INTERVALS.get(market, set())
        for child in sorted(market_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name in legacy_intervals:
                file_items.extend(_scan_legacy_market(paths, market, child.name))
                continue
            if (child / "latest").exists():
                file_items.extend(_scan_dataset_market(paths, market, child.name))

    overview_map: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    symbol_sets: dict[tuple[str, str | None, str], set[str]] = {}
    for item in file_items:
        key = (item["market"], item.get("interval"), item["data_kind"])
        symbol_sets.setdefault(key, set())
        if item.get("symbol_key"):
            symbol_sets[key].add(str(item["symbol_key"]))
        overview = overview_map.setdefault(
            key,
            {
                "market": item["market"],
                "interval": item.get("interval"),
                "data_kind": item["data_kind"],
                "file_count": 0,
                "symbol_count": 0,
                "row_count": 0,
                "start": None,
                "end": None,
                "updated_at": None,
                "formats": set(),
            },
        )
        overview["file_count"] += 1
        overview["row_count"] += int(item["row_count"] or 0)
        overview["start"] = _min_optional(overview["start"], item.get("start"))
        overview["end"] = _max_optional(overview["end"], item.get("end"))
        overview["updated_at"] = _max_optional(overview["updated_at"], item.get("updated_at"))
        overview["formats"].update(item.get("formats") or [])

    overview_items = []
    for key, item in overview_map.items():
        item["symbol_count"] = len(symbol_sets.get(key, set()))
        overview_items.append({**item, "formats": sorted(item["formats"])})
    overview_items.sort(key=lambda item: (item["market"], item.get("interval") or "", item["data_kind"]))
    file_items.sort(key=lambda item: (item["market"], item.get("interval") or "", item["data_kind"], item["partition"], item["file_id"]))

    payload = {
        "catalog_version": CATALOG_VERSION,
        "generated_at": _utc_now(),
        "overview": overview_items,
        "files": file_items,
    }
    paths.data_catalog_inventory_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return payload


def list_data_overview(paths: ProjectPaths) -> list[dict[str, Any]]:
    return load_data_catalog(paths, rebuild_if_missing=True).get("overview") or []


def list_data_files(
    paths: ProjectPaths,
    *,
    market: str | None = None,
    interval: str | None = None,
    data_kind: str | None = None,
) -> list[dict[str, Any]]:
    catalog = load_data_catalog(paths, rebuild_if_missing=True)
    files = catalog.get("files") or []
    market_key = _normalize_market(market)
    interval_key = _normalize_interval(interval)
    data_kind_key = _normalize_data_kind(data_kind)
    result = []
    for item in files:
        if market_key and item["market"] != market_key:
            continue
        if interval_key and (item.get("interval") or "") != interval_key:
            continue
        if data_kind_key and item["data_kind"] != data_kind_key:
            continue
        result.append(item)
    return result


def _preview_frame(path: Path, file_format: str, limit: int) -> pl.DataFrame:
    if file_format == "csv":
        return pl.read_csv(path, try_parse_dates=True, n_rows=limit)
    if file_format == "parquet":
        return pl.scan_parquet(str(path)).limit(limit).collect()
    raise ValueError(f"Unsupported file format `{file_format}`.")


def get_data_preview(
    paths: ProjectPaths,
    *,
    file_id: str | None = None,
    market: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
    data_kind: str | None = None,
    file_format: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    matched = None
    if file_id:
        matched = next((item for item in list_data_files(paths) if item["file_id"] == file_id), None)
        if matched is None:
            raise FileNotFoundError(f"Could not find local data file `{file_id}`.")
    else:
        market_key = _normalize_market(market) or "binanceusdm"
        interval_key = _normalize_interval(interval) or "1h"
        data_kind_key = _normalize_data_kind(data_kind) or "ohlcv"
        symbol_key = normalize_symbol_key(market_key, str(symbol or ""))
        matched = next(
            (
                item
                for item in list_data_files(paths, market=market_key, interval=interval_key, data_kind=data_kind_key)
                if item.get("symbol_key") == symbol_key
            ),
            None,
        )
        if matched is None:
            raise FileNotFoundError(f"Could not find local market data for {market_key}/{interval_key}/{symbol_key}.")

    preview_format = file_format or matched["preferred_format"]
    if preview_format not in matched["formats"]:
        raise FileNotFoundError(
            f"Format `{preview_format}` is not available for `{matched['file_id']}`. Available: {matched['formats']}"
        )
    path = Path(matched["file_path"])
    if preview_format != matched["preferred_format"]:
        path = path.with_suffix(f".{preview_format}")
    if not path.exists():
        raise FileNotFoundError(f"Could not find preview source `{path}`.")
    frame = _preview_frame(path, preview_format, limit)
    return {
        **matched,
        "format": preview_format,
        "available_formats": matched["formats"],
        "columns": frame.columns,
        "rows": [{key: _normalize_cell(value) for key, value in row.items()} for row in frame.to_dicts()],
    }
