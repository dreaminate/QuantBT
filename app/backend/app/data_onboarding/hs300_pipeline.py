"""HS300 十年日频真数据管线：staging 缓存 → canonical panel → DatasetVersion → 签名证据链。

编排顺序（对应 GOAL §11/§16 与 perf-harness 验收契约）：

    load_members / load_list_dates      # 成员与上市日全部来自 staging 的真实 Tushare 响应
    → assemble_panel                    # raw OHLCV canonical 面板（绝不做复权——复权唯一
                                        #   落点在 factor_factory/panel_source，本层只交 raw）
    → preflight_report                  # 镜像 harness 面板门逐项自检，fail 即拒签
    → register_panel                    # DatasetRegistry.register(require_provenance=True)
                                        #   → DatasetVersion + 不可变 manifest + lineage
    → build_chain                       # 签名 universe snapshot(v2, 携上市日) + provenance receipt

诚实边界：本模块产出的是「可被 harness 验收的证据链文件」，不是绿灯本身——
harness 侧 authority root 未 pin 时依然是 KNOWN_RUN_GAP（独立复审步骤，数据方不自铸）。

密钥红线：HMAC key 只流经 hs300_provenance.sign_payload；本模块不打印、不落盘、
不把 key 放进任何返回值或异常文本。
"""

from __future__ import annotations

import bisect
import hashlib
import math
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry, GERule

from . import hs300_provenance as prov

CANONICAL_COLUMNS = ["ts", "symbol", "open", "high", "low", "close", "volume"]


def _compact(date_iso: str) -> str:
    return date_iso.replace("-", "")


def _iso(date_compact: str) -> str:
    return f"{date_compact[0:4]}-{date_compact[4:6]}-{date_compact[6:8]}"


def load_members(staging_dir: str | Path, snapshot_yyyymm: str) -> list[str]:
    """某月 index_weight 快照的成分（排序去重）。快照缺失/为空即拒。"""
    path = Path(staging_dir) / "index_weight" / f"{snapshot_yyyymm}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"index_weight 快照缺失: {path}")
    frame = pl.read_parquet(path)
    members = sorted(set(frame.get_column("con_code").drop_nulls().to_list()))
    if not members:
        raise ValueError(f"index_weight 快照为空: {path}")
    return members


def load_list_dates(staging_dir: str | Path, symbols: list[str]) -> dict[str, str]:
    """成员上市日（ISO YYYY-MM-DD），源 = stock_basic L+D 两态合并；缺一个即拒。"""
    frames = []
    for status in ("L", "D"):
        path = Path(staging_dir) / f"stock_basic_{status}.parquet"
        if path.is_file():
            frames.append(pl.read_parquet(path, columns=["ts_code", "list_date"]))
    if not frames:
        raise FileNotFoundError(f"stock_basic parquet 缺失于 {staging_dir}")
    basic = pl.concat(frames)
    mapping = dict(
        zip(
            basic.get_column("ts_code").to_list(),
            basic.get_column("list_date").to_list(),
        )
    )
    missing = [s for s in symbols if not mapping.get(s)]
    if missing:
        raise KeyError(
            f"stock_basic 缺 {len(missing)} 个成员的上市日(如 {missing[:3]})"
        )
    return {s: _iso(str(mapping[s])) for s in symbols}


def assemble_panel(
    staging_dir: str | Path,
    *,
    members: list[str],
    start_date: str,
    end_date: str,
) -> pl.DataFrame:
    """staging daily/*.parquet → canonical raw OHLCV 面板。

    确定性：固定文件序、固定排序 (symbol, ts)、固定 dtype——同输入两次调用逐字节同帧。
    staging 内同 (symbol, trade_date) 重复视为源损坏，直接拒（不静默去重）。
    """
    start_c, end_c = _compact(start_date), _compact(end_date)
    member_set = set(members)
    frames = []
    for path in sorted((Path(staging_dir) / "daily").glob("*.parquet")):
        chunk = pl.read_parquet(
            path, columns=["ts_code", "trade_date", "open", "high", "low", "close", "vol"]
        ).filter(
            pl.col("ts_code").is_in(list(member_set))
            & (pl.col("trade_date") >= start_c)
            & (pl.col("trade_date") <= end_c)
        )
        if chunk.height:
            frames.append(chunk)
    if not frames:
        raise ValueError("staging 中没有任何 daily bar 命中成员×窗口")
    panel = (
        pl.concat(frames)
        .rename({"ts_code": "symbol", "vol": "volume"})
        .with_columns(
            pl.col("trade_date")
            .str.strptime(pl.Datetime("us"), "%Y%m%d")
            .dt.replace_time_zone("UTC")
            .alias("ts")
        )
        .select(CANONICAL_COLUMNS)
        .with_columns(
            [
                pl.col(column).cast(pl.Float64, strict=False)
                for column in ("open", "high", "low", "close", "volume")
            ]
        )
        .sort(["symbol", "ts"])
        .rechunk()
    )
    duplicates = panel.height - panel.select(
        pl.struct(["symbol", "ts"]).n_unique()
    ).item()
    if duplicates:
        raise ValueError(f"staging 含 {duplicates} 条重复 (symbol, trade_date)——源损坏,拒组面板")
    return panel


def preflight_report(
    frame: pl.DataFrame,
    list_dates: dict[str, str],
    *,
    required_symbol_count: int = 300,
    min_trading_days: int = 2400,
    min_span_days: int = 3650,
    coverage_ratio: float = 0.80,
    first_bar_lag_days: int = 10,
) -> dict[str, Any]:
    """镜像 harness `_validate_hs300_panel` 的逐项自检（诊断态：跑全部项不早退）。

    任一项 fail → ok=False。签名前必须 ok=True，防止把注定被拒的链签出去。
    """
    checks: dict[str, dict[str, Any]] = {}

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    work = frame.with_columns(pl.col("ts").dt.date().alias("__d"))
    symbols = sorted(work.get_column("symbol").unique().to_list())
    _check(
        "symbol_count",
        len(symbols) == required_symbol_count,
        f"{len(symbols)} vs required {required_symbol_count}",
    )
    dup = work.height - work.select(pl.struct(["__d", "symbol"]).n_unique()).item()
    _check("no_duplicate_day_symbol", dup == 0, f"duplicates={dup}")
    weekend = work.select((pl.col("__d").dt.weekday() > 5).sum()).item()
    _check("no_weekend_bars", weekend == 0, f"weekend_rows={weekend}")
    nulls = sum(work.get_column(c).null_count() for c in CANONICAL_COLUMNS)
    _check("no_nulls", nulls == 0, f"nulls={nulls}")
    nonfinite = sum(
        work.select((~pl.col(c).is_finite()).sum()).item()
        for c in ("open", "high", "low", "close", "volume")
    )
    _check("all_finite", nonfinite == 0, f"non_finite={nonfinite}")
    bad_ohlc = work.select(
        (
            (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
            | (pl.col("volume") < 0)
            | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
        ).sum()
    ).item()
    _check("ohlcv_invariants", bad_ohlc == 0, f"violating_rows={bad_ohlc}")

    trading_dates = sorted(work.get_column("__d").unique().to_list())
    _check(
        "min_trading_days",
        len(trading_dates) >= min_trading_days,
        f"{len(trading_dates)} vs min {min_trading_days}",
    )
    span = (trading_dates[-1] - trading_dates[0]).days if trading_dates else 0
    _check("min_span_days", span >= min_span_days, f"{span} vs min {min_span_days}")

    per_symbol = work.group_by("symbol").agg(
        pl.col("__d").n_unique().alias("days"),
        pl.col("__d").min().alias("first_bar"),
    )
    bars_before_listing: list[str] = []
    coverage_failures: list[dict[str, Any]] = []
    lag_failures: list[str] = []
    missing_list_date: list[str] = []
    coverage_table: list[dict[str, Any]] = []
    for row in per_symbol.iter_rows(named=True):
        symbol = row["symbol"]
        raw = list_dates.get(symbol)
        if raw is None:
            missing_list_date.append(symbol)
            continue
        listed = datetime.strptime(raw, "%Y-%m-%d").date()
        start_index = bisect.bisect_left(trading_dates, listed)
        expected = len(trading_dates) - start_index
        ratio = (row["days"] / expected) if expected > 0 else float("nan")
        coverage_table.append(
            {"symbol": symbol, "list_date": raw, "days": row["days"],
             "expected": expected, "ratio": round(ratio, 4)}
        )
        if row["first_bar"] < listed:
            bars_before_listing.append(symbol)
        if expected <= 0 or row["days"] < math.ceil(expected * coverage_ratio):
            coverage_failures.append(
                {"symbol": symbol, "days": row["days"], "expected": expected}
            )
        if start_index > 0 and expected > 0:
            cutoff = trading_dates[
                min(start_index + first_bar_lag_days - 1, len(trading_dates) - 1)
            ]
            if row["first_bar"] > cutoff:
                lag_failures.append(symbol)
    _check("list_dates_complete", not missing_list_date, f"missing={missing_list_date[:5]}")
    _check("no_bars_before_listing", not bars_before_listing, f"{bars_before_listing[:5]}")
    _check(
        "since_listing_coverage",
        not coverage_failures,
        f"failures={coverage_failures[:5]}",
    )
    _check("first_bar_lag", not lag_failures, f"{lag_failures[:5]}")

    coverage_table.sort(key=lambda item: item["ratio"])
    return {
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "worst_coverage": coverage_table[:10],
        "trading_days": len(trading_dates),
        "span_days": span,
        "symbols": len(symbols),
        "rows": frame.height,
    }


def register_panel(
    frame: pl.DataFrame,
    *,
    registry_path: str | Path,
    panel_path: str | Path,
    dataset_id: str = "hs300_daily_10y",
    source_ref: str = "tushare://daily",
    secret_ref: str = "keyring://quantbt/tushare",
    ingestion_skill_version: str = "tushare@1.4.29",
    known_at_utc: str | None = None,
    effective_at_utc: str | None = None,
):
    """写 panel parquet 并 DatasetRegistry.register(require_provenance=True)。

    GE 规则 = 5 个 distinct (column, not_null)（harness registry 契约要求 ≥5 distinct
    passing data tests）；metadata 按 harness 契约三键。
    """
    panel_file = Path(panel_path)
    panel_file.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(panel_file)
    now_iso = datetime.now(UTC).isoformat()
    fetch_result = replace(
        make_wide_fetch_result(frame, source_name="tushare"),
        source_ref=source_ref,
        ingestion_skill_version=ingestion_skill_version,
        secret_ref=secret_ref,
        known_at_utc=known_at_utc or now_iso,
        effective_at_utc=effective_at_utc or frame.get_column("ts").max().isoformat(),
    )
    registry = DatasetRegistry(Path(registry_path))
    return registry.register(
        dataset_id,
        fetch_result,
        file_paths=[str(panel_file)],
        rules=[
            GERule(column=column, rule_type="not_null")
            for column in ("open", "high", "low", "close", "volume")
        ],
        metadata={
            "market": "stocks_cn",
            "interval": "1d",
            "data_kind": "ohlcv",
        },
        source_ref=source_ref,
        ingestion_skill_version=ingestion_skill_version,
        secret_ref=secret_ref,
        known_at_utc=fetch_result.known_at_utc,
        effective_at_utc=fetch_result.effective_at_utc,
        require_provenance=True,
    )


def build_chain(
    staging_dir: str | Path,
    *,
    registry_path: str | Path,
    panel_path: str | Path,
    out_dir: str | Path,
    key: str,
    root_id: str,
    key_id: str,
    snapshot_yyyymm: str,
    start_date: str,
    end_date: str,
    as_of_date: str,
    dataset_id: str = "hs300_daily_10y",
    ingestion_skill_version: str = "tushare@1.4.29",
    preflight_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """staging → preflight → register → 签名 universe + receipt。返回 refs（不含 key）。"""
    members = load_members(staging_dir, snapshot_yyyymm)
    list_dates = load_list_dates(staging_dir, members)
    frame = assemble_panel(
        staging_dir, members=members, start_date=start_date, end_date=end_date
    )
    report = preflight_report(frame, list_dates, **(preflight_kwargs or {}))
    if not report["ok"]:
        failing = {
            name: item for name, item in report["checks"].items() if not item["ok"]
        }
        raise ValueError(f"preflight 未过,拒签: {failing}")
    version = register_panel(
        frame,
        registry_path=registry_path,
        panel_path=panel_path,
        dataset_id=dataset_id,
        ingestion_skill_version=ingestion_skill_version,
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    universe_payload = prov.build_universe_payload(
        root_id, key_id, as_of_date, members, list_dates
    )
    universe_path = prov.write_signed_json(out / "universe.json", universe_payload, key)
    universe_snapshot_sha256 = hashlib.sha256(universe_path.read_bytes()).hexdigest()
    manifest_sha256 = hashlib.sha256(
        Path(version.manifest_path).read_bytes()
    ).hexdigest()
    receipt_payload = prov.build_receipt_payload(
        root_id=root_id,
        key_id=key_id,
        dataset_id=version.dataset_id,
        dataset_version=version.version_id,
        dataset_record_sha256=hashlib.sha256(
            prov.canonical_payload_bytes(version.to_dict())
        ).hexdigest(),
        dataset_frame_sha256=version.sha256,
        manifest_sha256=manifest_sha256,
        source_name=version.source_name,
        source_ref=version.source_ref,
        ingestion_skill_version=version.ingestion_skill_version,
        market=version.metadata["market"],
        interval=version.metadata["interval"],
        data_kind=version.metadata["data_kind"],
        universe_snapshot_sha256=universe_snapshot_sha256,
        loaded_panel_sha256=prov.loaded_panel_sha256(frame),
        row_count=version.row_count,
        coverage_start_utc=version.coverage_start_utc,
        coverage_end_utc=version.coverage_end_utc,
        attested_at_utc=datetime.now(UTC).isoformat(),
    )
    receipt_path = prov.write_signed_json(out / "provenance.json", receipt_payload, key)
    return {
        "dataset_id": version.dataset_id,
        "dataset_version_ref": version.version_id,
        "panel_path": str(panel_path),
        "registry_path": str(registry_path),
        "manifest_path": str(version.manifest_path),
        "receipt_path": str(receipt_path),
        "universe_path": str(universe_path),
        "manifest_sha256": manifest_sha256,
        "universe_snapshot_sha256": universe_snapshot_sha256,
        "loaded_panel_sha256": receipt_payload["loaded_panel_sha256"],
        "dataset_frame_sha256": version.sha256,
        "rows": version.row_count,
        "preflight": report,
    }


__all__ = [
    "CANONICAL_COLUMNS",
    "load_members",
    "load_list_dates",
    "assemble_panel",
    "preflight_report",
    "register_panel",
    "build_chain",
]
