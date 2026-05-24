from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from .paths import RUN_ROOT


RUN_SERIES_COLUMNS = {
    "equity": "equity",
    "drawdown": "drawdown",
    "turnover": "turnover",
    "net_return": "net_return",
    "gross_return": "gross_return",
    "funding_return": "funding_return",
    "fee_cost": "fee_cost",
    "strategy_return": "net_return",
    "benchmark_return": "benchmark_return",
    "alpha": "alpha",
    "beta": "beta",
    "sharpe": "sharpe",
    "sortino": "sortino",
    "information_ratio": "information_ratio",
    "volatility": "volatility",
    "benchmark_volatility": "benchmark_volatility",
    "max_drawdown": "max_drawdown",
}

TABLE_FILE_NAMES = {
    "portfolio": "portfolio.csv",
    "trades": "trades.csv",
    "positions": "positions.csv",
}


@dataclass
class LoadedRun:
    run_id: str
    manifest: dict[str, Any]
    portfolio: pl.DataFrame
    trades: pl.DataFrame
    positions: pl.DataFrame
    report_markdown: str
    source_code: str
    attribution: pl.DataFrame
    log_entries: list[dict[str, str]]


def run_dir(run_id: str) -> Path:
    return RUN_ROOT / run_id


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def _load_csv(path: Path) -> pl.DataFrame:
    if not path.exists():
        return pl.DataFrame()
    return pl.read_csv(path, try_parse_dates=True)


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number != number:  # NaN
        return None
    return number


def _read_log_entries(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split(" - ", 2)
        if len(parts) == 3:
            entries.append({"timestamp": parts[0], "level": parts[1], "message": parts[2]})
        else:
            entries.append({"timestamp": "", "level": "", "message": line})
    return entries


def load_run(run_id: str) -> LoadedRun:
    root = run_dir(run_id)
    manifest_path = root / "run.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"run.json 不存在: {manifest_path}")
    return LoadedRun(
        run_id=run_id,
        manifest=_read_json(manifest_path),
        portfolio=_load_csv(root / TABLE_FILE_NAMES["portfolio"]),
        trades=_load_csv(root / TABLE_FILE_NAMES["trades"]),
        positions=_load_csv(root / TABLE_FILE_NAMES["positions"]),
        report_markdown=_read_text(root / "report.md"),
        source_code=_read_text(root / "strategy.py"),
        attribution=_load_csv(root / "attribution.csv"),
        log_entries=_read_log_entries(root / "backtest.log"),
    )


def _manifest_run_id(path: Path, manifest: dict[str, Any]) -> str:
    return str(manifest.get("run_id") or path.name)


def _manifest_strategy_name(path: Path, manifest: dict[str, Any]) -> str:
    return str(manifest.get("strategy_name") or manifest.get("strategy_id") or path.name)


def _build_run_summary_from_manifest(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    run_id = _manifest_run_id(path, manifest)
    metric = lambda *keys: _metric_value(manifest, *keys)
    overall = {
        "total_return": metric("returns", "total_return"),
        "annualized_return": metric("annualized_return"),
        "sharpe": metric("sharpe"),
        "max_drawdown": metric("drawdown", "max_drawdown"),
        "win_rate": metric("trade_win_rate", "win_rate"),
        "turnover": metric("turnover"),
        "avg_turnover": metric("avg_turnover", "turnover"),
        "fee_cost": metric("fee_cost"),
        "funding_return": metric("funding_return"),
    }
    return {
        "run_id": run_id,
        "strategy_name": _manifest_strategy_name(path, manifest),
        "strategy_id": manifest.get("strategy_id", run_id),
        "started_at": manifest.get("started_at", ""),
        "status": manifest.get("status", "completed"),
        "record_name": manifest.get("record_name"),
        "favorite": bool(manifest.get("favorite")),
        "strategy_mode": manifest.get("strategy_mode"),
        "strategy_ref": manifest.get("strategy_ref"),
        "strategy_script_path": str(path / "strategy.py"),
        "strategy_script_name": "strategy.py" if (path / "strategy.py").exists() else None,
        "artifact_dir": str(path),
        "overall": overall,
        "in_sample": manifest.get("in_sample") or {},
        "out_of_sample": manifest.get("out_of_sample") or overall,
        "cost_breakdown": manifest.get("cost_breakdown") or {},
        "dataset_versions": manifest.get("dataset_versions") or {},
        "universe_snapshot_id": manifest.get("universe_snapshot_id"),
        "stock_pool_id": manifest.get("stock_pool_id"),
        "temporary_symbols_count": manifest.get("temporary_symbols_count"),
        "top_n": manifest.get("top_n"),
        "ranking_metric": manifest.get("ranking_metric"),
        "resolved_candidate_count": manifest.get("resolved_candidate_count"),
        "instrument_type": manifest.get("instrument_type"),
        "market": manifest.get("market"),
        "frequency": manifest.get("frequency"),
        "execution_profile": manifest.get("execution_profile"),
        "execution_model": manifest.get("execution_model"),
        "benchmark": manifest.get("benchmark"),
        "requested_neutralization": manifest.get("requested_neutralization"),
        "resolved_neutralization": manifest.get("resolved_neutralization"),
        "neutralization": manifest.get("neutralization"),
        "unit_handling": manifest.get("unit_handling"),
        "pasteurization": manifest.get("pasteurization"),
        "model_used": bool(manifest.get("model_used", False)),
        "tearsheet_available": (path / "tearsheet.html").exists(),
        "data_coverage_summary": manifest.get("data_coverage_summary", {}),
        "returns": metric("returns", "total_return"),
        "turnover": metric("turnover"),
        "margin": metric("margin"),
        "pnl": metric("pnl"),
        "drawdown": metric("drawdown", "max_drawdown"),
        "fitness": metric("fitness"),
        "sharpe": metric("sharpe"),
        "book_size": metric("book_size"),
        "long_count": metric("long_count"),
        "short_count": metric("short_count"),
        "annualized_return": metric("annualized_return"),
        "alpha": metric("alpha"),
        "beta": metric("beta"),
        "win_rate": metric("trade_win_rate", "win_rate"),
        "sortino": metric("sortino"),
        "information_ratio": metric("information_ratio"),
        "volatility": metric("volatility"),
        "benchmark_volatility": metric("benchmark_volatility"),
        "profit_loss_ratio": metric("profit_loss_ratio"),
        "avg_daily_return": metric("avg_daily_return"),
        "daily_win_rate": metric("daily_win_rate"),
        "trade_count": metric("trade_count"),
        "analysis_start": manifest.get("analysis_start"),
        "analysis_end": manifest.get("analysis_end"),
        "duration_seconds": metric("duration_seconds"),
    }


def _collect_manifest_rows() -> list[dict[str, Any]]:
    if not RUN_ROOT.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(RUN_ROOT.iterdir()):
        if not path.is_dir():
            continue
        manifest_path = path / "run.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = _read_json(manifest_path)
        except Exception:
            continue
        rows.append(_build_run_summary_from_manifest(path, manifest))
    return rows


def list_runs() -> list[dict[str, Any]]:
    rows = _collect_manifest_rows()
    rows.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    return rows


def _csv_row_count(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def build_artifact_stats(run_id: str) -> dict[str, Any]:
    root = run_dir(run_id)
    mapping = {
        "run": "run.json",
        "portfolio": "portfolio.csv",
        "trades": "trades.csv",
        "positions": "positions.csv",
        "report": "report.md",
        "tearsheet": "tearsheet.html",
        "strategy": "strategy.py",
        "log": "backtest.log",
        "attribution": "attribution.csv",
    }
    stats: dict[str, Any] = {}
    for name, file_name in mapping.items():
        path = root / file_name
        stats[name] = {
            "artifact_name": name,
            "available": path.exists(),
            "file_path": str(path) if path.exists() else None,
            "file_size_bytes": path.stat().st_size if path.exists() else None,
            "row_count": _csv_row_count(path) if path.exists() and path.suffix.lower() == ".csv" else None,
        }
    return stats


def _frame_to_rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
    if frame.height == 0:
        return []
    return frame.to_dicts()


def _table_dtype(dtype: pl.DataType) -> str:
    if dtype.is_numeric():
        return "number"
    if dtype.base_type() in {pl.Date, pl.Datetime, pl.Time}:
        return "datetime"
    return "string"


def _columns_payload(frame: pl.DataFrame) -> list[dict[str, Any]]:
    if frame.height == 0 and not frame.columns:
        return []
    schema = frame.schema
    return [{"key": name, "label": name, "dtype": _table_dtype(schema[name])} for name in frame.columns]


def _date_column(frame: pl.DataFrame) -> str | None:
    for column in ("execution_timestamp", "timestamp", "trade_date", "date", "ann_date", "cal_date"):
        if column in frame.columns:
            return column
    return None


def _apply_table_filters(
    frame: pl.DataFrame,
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
) -> pl.DataFrame:
    if frame.height == 0:
        return frame
    date_column = _date_column(frame)
    if start_ts and date_column:
        frame = frame.filter(pl.col(date_column).cast(pl.Utf8) >= start_ts)
    if end_ts and date_column:
        frame = frame.filter(pl.col(date_column).cast(pl.Utf8) <= end_ts)
    if symbol and "symbol" in frame.columns:
        frame = frame.filter(pl.col("symbol").cast(pl.Utf8).str.to_uppercase() == symbol.upper())
    if side and "trade_side" in frame.columns:
        frame = frame.filter(pl.col("trade_side").cast(pl.Utf8).str.to_lowercase() == side.lower())
    return frame


def _sort_table(frame: pl.DataFrame, sort: str | None, order: str) -> pl.DataFrame:
    if frame.height == 0 or not sort or sort not in frame.columns:
        return frame
    descending = order == "desc"
    return frame.sort(sort, descending=descending)


def load_table_response(
    run_id: str,
    table_name: str,
    *,
    limit: int = 200,
    offset: int = 0,
    sort: str | None = None,
    order: str = "desc",
    start_ts: str | None = None,
    end_ts: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
) -> dict[str, Any]:
    if table_name not in TABLE_FILE_NAMES:
        raise ValueError(f"未知 table: {table_name}")
    frame = _load_csv(run_dir(run_id) / TABLE_FILE_NAMES[table_name])
    available = frame.height > 0
    frame = _apply_table_filters(frame, start_ts=start_ts, end_ts=end_ts, symbol=symbol, side=side)
    if not sort:
        sort = "execution_timestamp" if "execution_timestamp" in frame.columns else _date_column(frame)
    frame = _sort_table(frame, sort, order)
    total_rows = frame.height
    paged = frame.slice(offset, limit)
    return {
        "table_name": table_name,
        "available": available,
        "columns": _columns_payload(frame),
        "rows": _frame_to_rows(paged),
        "total_rows": total_rows,
    }


def _load_series_file(run_id: str, series_name: str) -> list[dict[str, Any]]:
    path = run_dir(run_id) / "series" / f"{series_name}.csv"
    frame = _load_csv(path)
    if frame.height == 0 or "timestamp" not in frame.columns or "value" not in frame.columns:
        return []
    return [{"timestamp": row["timestamp"], "value": _safe_number(row["value"])} for row in frame.to_dicts()]


def _compute_drawdown_series(frame: pl.DataFrame) -> pl.DataFrame:
    if "drawdown" in frame.columns or "equity" not in frame.columns:
        return frame
    running_max: list[float] = []
    current = 0.0
    for raw in frame["equity"].to_list():
        value = _safe_number(raw) or 0.0
        current = max(current, value)
        running_max.append(current if current else 1.0)
    drawdown = [((_safe_number(value) or 0.0) / peak - 1) if peak else 0.0 for value, peak in zip(frame["equity"].to_list(), running_max, strict=False)]
    return frame.with_columns(pl.Series("drawdown", drawdown))


def _compute_max_drawdown_series(frame: pl.DataFrame) -> pl.DataFrame:
    if "max_drawdown" in frame.columns:
        return frame
    if "drawdown" not in frame.columns:
        frame = _compute_drawdown_series(frame)
    running_min: list[float] = []
    current = 0.0
    for raw in frame["drawdown"].to_list():
        value = _safe_number(raw) or 0.0
        current = min(current, value)
        running_min.append(current)
    return frame.with_columns(pl.Series("max_drawdown", running_min))


def _daily_trade_flow(frame: pl.DataFrame, side_match: str) -> list[dict[str, Any]]:
    if frame.height == 0 or "execution_timestamp" not in frame.columns or "turnover" not in frame.columns:
        return []
    filtered = frame
    if "trade_side" in filtered.columns:
        filtered = filtered.filter(pl.col("trade_side").cast(pl.Utf8).str.to_lowercase().str.contains(side_match))
    if filtered.height == 0:
        return []
    grouped = (
        filtered.with_columns(pl.col("execution_timestamp").cast(pl.Utf8).str.slice(0, 10).alias("trade_day"))
        .group_by("trade_day")
        .agg(pl.col("turnover").sum().alias("value"))
        .sort("trade_day")
    )
    return [{"timestamp": row["trade_day"], "value": _safe_number(row["value"])} for row in grouped.to_dicts()]


def load_series_response(run_id: str, series_name: str, segment: str = "overall") -> dict[str, Any]:
    run = load_run(run_id)
    if series_name == "daily_buy":
        points = _daily_trade_flow(run.trades, "buy")
    elif series_name == "daily_sell":
        points = _daily_trade_flow(run.trades, "sell")
    else:
        points = _load_series_file(run_id, series_name)
        if not points:
            frame = run.portfolio
            if series_name == "drawdown":
                frame = _compute_drawdown_series(frame)
            if series_name == "max_drawdown":
                frame = _compute_max_drawdown_series(frame)
            column = RUN_SERIES_COLUMNS.get(series_name, series_name)
            date_column = _date_column(frame)
            if date_column and column in frame.columns:
                points = [
                    {"timestamp": row[date_column], "value": _safe_number(row[column])}
                    for row in frame.select([date_column, column]).to_dicts()
                ]
    return {
        "run_id": run_id,
        "series": series_name,
        "segment": segment,
        "available": bool(points),
        "points": points,
    }


def _series_available(run: LoadedRun) -> dict[str, bool]:
    available = {name: False for name in list(RUN_SERIES_COLUMNS) + ["daily_buy", "daily_sell"]}
    for name in list(available):
        available[name] = bool(load_series_response(run.run_id, name)["points"])
    return available


def _metric_value(manifest: dict[str, Any], *keys: str) -> Any:
    metrics = manifest.get("metrics") or {}
    for key in keys:
        if key in metrics and metrics[key] not in (None, ""):
            return metrics[key]
        if key in manifest and manifest[key] not in (None, ""):
            return manifest[key]
    return None


def get_run_detail(run_id: str) -> dict[str, Any]:
    from .jq_overview_metrics import compute_jq_overview_metrics

    run = load_run(run_id)
    stats = build_artifact_stats(run_id)
    manifest = run.manifest
    return {
        "run_id": manifest.get("run_id", run_id),
        "strategy_name": manifest.get("strategy_name", run_id),
        "strategy_id": manifest.get("strategy_id", run_id),
        "started_at": manifest.get("started_at", ""),
        "status": manifest.get("status", "completed"),
        "record_name": manifest.get("record_name"),
        "strategy_mode": manifest.get("strategy_mode"),
        "strategy_ref": manifest.get("strategy_ref"),
        "strategy_script_path": str(run_dir(run_id) / "strategy.py"),
        "strategy_script_name": "strategy.py" if run.source_code else None,
        "artifact_dir": str(run_dir(run_id)),
        "metrics": manifest.get("metrics") or {},
        "jq_overview_metrics": compute_jq_overview_metrics(run),
        "report_markdown": run.report_markdown,
        "config_snapshot": manifest.get("config_snapshot"),
        "artifacts": {},
        "artifact_stats": stats,
        "data_dependencies": manifest.get("data_dependencies", []),
        "produced_outputs": manifest.get("produced_outputs", []),
        "component_runs": manifest.get("component_runs", []),
        "series_available": _series_available(run),
        "oos_periods": int((manifest.get("out_of_sample") or {}).get("periods", 0) or 0),
        "market": manifest.get("market"),
        "frequency": manifest.get("frequency"),
        "benchmark": manifest.get("benchmark"),
        "model_used": bool(manifest.get("model_used", False)),
        "tearsheet_available": stats["tearsheet"]["available"],
        "data_coverage_summary": manifest.get("data_coverage_summary", {}),
        "returns": _metric_value(manifest, "returns", "total_return"),
        "turnover": _metric_value(manifest, "turnover"),
        "margin": _metric_value(manifest, "margin"),
        "pnl": _metric_value(manifest, "pnl"),
        "drawdown": _metric_value(manifest, "drawdown", "max_drawdown"),
        "fitness": _metric_value(manifest, "fitness"),
        "sharpe": _metric_value(manifest, "sharpe"),
        "book_size": _metric_value(manifest, "book_size"),
        "long_count": _metric_value(manifest, "long_count"),
        "short_count": _metric_value(manifest, "short_count"),
        "annualized_return": _metric_value(manifest, "annualized_return"),
        "alpha": _metric_value(manifest, "alpha"),
        "beta": _metric_value(manifest, "beta"),
        "win_rate": _metric_value(manifest, "trade_win_rate", "win_rate"),
        "sortino": _metric_value(manifest, "sortino"),
        "information_ratio": _metric_value(manifest, "information_ratio"),
        "volatility": _metric_value(manifest, "volatility"),
        "benchmark_volatility": _metric_value(manifest, "benchmark_volatility"),
        "profit_loss_ratio": _metric_value(manifest, "profit_loss_ratio"),
        "avg_daily_return": _metric_value(manifest, "avg_daily_return"),
        "daily_win_rate": _metric_value(manifest, "daily_win_rate"),
        "trade_count": _metric_value(manifest, "trade_count"),
        "analysis_start": manifest.get("analysis_start"),
        "analysis_end": manifest.get("analysis_end"),
        "duration_seconds": _metric_value(manifest, "duration_seconds"),
    }


def _value_for_sort(row: dict[str, Any], field: str) -> Any:
    if field in row:
        return row.get(field)
    overall = row.get("overall") or {}
    if isinstance(overall, dict) and field in overall:
        return overall.get(field)
    return None


def _numeric_filter_matches(row: dict[str, Any], field: str, operator: str, value: float, value_to: float | None) -> bool:
    current = _value_for_sort(row, field)
    number = _safe_number(current)
    if number is None:
        return False
    if operator == ">":
        return number > value
    if operator == ">=":
        return number >= value
    if operator == "<":
        return number < value
    if operator == "<=":
        return number <= value
    if operator == "=":
        return number == value
    if operator == "between" and value_to is not None:
        low = min(value, value_to)
        high = max(value, value_to)
        return low <= number <= high
    return True


def delete_run(run_id: str) -> None:
    """删除实验目录（与 quant1 删除行为对齐，仅限 RUN_ROOT 下）。"""
    import shutil

    root = run_dir(run_id)
    if not root.exists():
        raise FileNotFoundError(f"run 不存在: {run_id}")
    shutil.rmtree(root)


def query_runs(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request = payload or {}
    rows = _collect_manifest_rows()
    search = str(request.get("search") or "").strip().lower()
    status = str(request.get("status") or "").strip().lower()
    market = str(request.get("market") or "").strip().lower()
    frequency = str(request.get("frequency") or "").strip().lower()
    benchmark = str(request.get("benchmark") or "").strip().lower()
    strategy_mode = str(request.get("strategy_mode") or "").strip().lower()
    dataset_version = str(request.get("dataset_version") or "").strip().lower()
    universe_snapshot_id = str(request.get("universe_snapshot_id") or "").strip().lower()
    favorite_only = bool(request.get("favorite_only"))
    model_used = request.get("model_used")
    numeric_filters = list(request.get("numeric_filters") or [])

    filtered: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            str(
                row.get(key) or ""
            )
            for key in ("run_id", "strategy_name", "strategy_id", "record_name", "market", "frequency", "benchmark")
        ).lower()
        if search and search not in haystack:
            continue
        if status and str(row.get("status") or "").lower() != status:
            continue
        if market and str(row.get("market") or "").lower() != market:
            continue
        if frequency and str(row.get("frequency") or "").lower() != frequency:
            continue
        if benchmark and str(row.get("benchmark") or "").lower() != benchmark:
            continue
        if strategy_mode and str(row.get("strategy_mode") or "").lower() != strategy_mode:
            continue
        if dataset_version:
            dv = row.get("dataset_versions") or {}
            if isinstance(dv, dict):
                val_set = {str(v).strip().lower() for v in dv.values() if v is not None and str(v).strip()}
                if dataset_version not in val_set:
                    continue
            else:
                continue
        if universe_snapshot_id and str(row.get("universe_snapshot_id") or "").lower() != universe_snapshot_id:
            continue
        if favorite_only and not bool(row.get("favorite")):
            continue
        if model_used is not None and bool(row.get("model_used")) is not bool(model_used):
            continue
        if any(
            not _numeric_filter_matches(
                row,
                str(item.get("field") or ""),
                str(item.get("operator") or ""),
                float(item.get("value")),
                float(item["value_to"]) if item.get("value_to") is not None else None,
            )
            for item in numeric_filters
            if item.get("field") and item.get("operator") and item.get("value") is not None
        ):
            continue
        filtered.append(row)

    sort_by = str(request.get("sort_by") or "started_at")
    sort_order = str(request.get("sort_order") or "desc").lower()
    reverse = sort_order != "asc"
    filtered.sort(key=lambda item: (_value_for_sort(item, sort_by) is None, _value_for_sort(item, sort_by)), reverse=reverse)

    limit = max(int(request.get("limit") or 200), 1)
    offset = max(int(request.get("offset") or 0), 0)
    page_rows = filtered[offset : offset + limit]

    def distinct_values(field: str) -> list[str]:
        values = {str(item.get(field)).strip() for item in rows if item.get(field) not in (None, "")}
        return sorted(values)

    def distinct_dataset_versions() -> list[str]:
        out: set[str] = set()
        for item in rows:
            dv = item.get("dataset_versions") or {}
            if isinstance(dv, dict):
                for v in dv.values():
                    if v is not None and str(v).strip():
                        out.add(str(v).strip())
        return sorted(out)

    return {
        "rows": page_rows,
        "total_rows": len(filtered),
        "available_filters": {
            "status": distinct_values("status"),
            "market": distinct_values("market"),
            "frequency": distinct_values("frequency"),
            "benchmark": distinct_values("benchmark"),
            "strategy_mode": distinct_values("strategy_mode"),
            "dataset_version": distinct_dataset_versions(),
            "universe_snapshot_id": distinct_values("universe_snapshot_id"),
        },
    }


def compare_runs(run_ids: list[str]) -> dict[str, Any]:
    target_ids = {run_id for run_id in run_ids if run_id}
    rows = [row for row in _collect_manifest_rows() if row.get("run_id") in target_ids]
    rows.sort(key=lambda item: run_ids.index(str(item.get("run_id"))))
    return {"runs": rows}


def load_compare_series_response(run_ids: list[str], series_name: str, segment: str = "overall") -> dict[str, Any]:
    summaries = {str(item.get("run_id")): item for item in _collect_manifest_rows()}
    runs: list[dict[str, Any]] = []
    for run_id in run_ids:
        summary = summaries.get(run_id)
        series_payload = load_series_response(run_id, series_name, segment)
        runs.append(
            {
                "run_id": run_id,
                "strategy_name": summary.get("strategy_name") if summary else run_id,
                "available": series_payload.get("available", False),
                "points": series_payload.get("points", []),
            }
        )
    return {
        "series": series_name,
        "segment": segment,
        "runs": runs,
    }


def get_run_logs(run_id: str, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    run = load_run(run_id)
    return {
        "entries": run.log_entries[offset : offset + limit],
        "total": len(run.log_entries),
    }


def get_run_source(run_id: str) -> dict[str, Any]:
    run = load_run(run_id)
    return {
        "file_name": "strategy.py",
        "content": run.source_code or "# 未提供 strategy.py\n",
    }


def get_run_attribution(run_id: str) -> dict[str, Any]:
    run = load_run(run_id)
    if run.attribution.height == 0:
        return {
            "run_id": run_id,
            "available": False,
            "method": "file",
            "summary": {},
            "rows": [],
            "message": "未提供 attribution.csv",
        }
    return {
        "run_id": run_id,
        "available": True,
        "method": "file",
        "summary": {"row_count": run.attribution.height},
        "rows": run.attribution.to_dicts(),
    }


def artifact_download_path(run_id: str, artifact_name: str) -> Path:
    mapping = {
        "run": "run.json",
        "portfolio": "portfolio.csv",
        "trades": "trades.csv",
        "positions": "positions.csv",
        "report": "report.md",
        "tearsheet": "tearsheet.html",
        "strategy": "strategy.py",
        "log": "backtest.log",
        "attribution": "attribution.csv",
    }
    file_name = mapping.get(artifact_name)
    if file_name is None:
        raise ValueError(f"未知 artifact: {artifact_name}")
    return run_dir(run_id) / file_name


def export_path(run_id: str, export_type: str) -> Path:
    mapping = {
        "nav": "portfolio.csv",
        "positions": "positions.csv",
        "trades": "trades.csv",
        "metrics": "run.json",
    }
    file_name = mapping.get(export_type)
    if file_name is None:
        raise ValueError(f"未知 export 类型: {export_type}")
    return run_dir(run_id) / file_name
