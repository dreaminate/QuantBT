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

【幸存者边界·双资产纪律】本管线产出的 panel = **as-of 当期 300 成分 × 十年窗口**，
语义是「读性能基准面」，带幸存者选择（成分本身按 as-of 快照取）——它**不是**无幸存者
偏差的研究 universe，禁止喂 confirmatory validation / 回测选股。无偏研究面 =
历史成分并集（~622 只含退市，staging 已含全量 daily+adj_factor）作为**独立
dataset_id 的第二资产**交付，survivorship_rule_ref 显式区分两者（见任务卡 39d08df8）。

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
    codes = basic.get_column("ts_code").to_list()
    dates = basic.get_column("list_date").to_list()
    mapping: dict[str, str] = {}
    conflicts: list[str] = []
    for code, raw in zip(codes, dates):
        if code in mapping and mapping[code] != raw:
            conflicts.append(code)
        mapping[code] = raw
    if conflicts:
        raise ValueError(f"stock_basic L/D 上市日冲突,fail-closed: {conflicts[:5]}")
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

    if frame.is_empty():
        return {
            "ok": False,
            "checks": {"non_empty": {"ok": False, "detail": "panel is empty"}},
            "worst_coverage": [],
            "trading_days": 0,
            "span_days": 0,
            "symbols": 0,
            "rows": 0,
        }
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
    dataset_id: str = "hs300_daily_10y_readbench_cohort",
    source_ref: str = "tushare://daily",
    secret_ref: str = "keyring://quantbt/tushare",
    ingestion_skill_version: str | None = None,
    known_at_utc: str | None = None,
    effective_at_utc: str | None = None,
):
    """写 panel parquet 并 DatasetRegistry.register(require_provenance=True)。

    GE 规则 = 5 个 distinct (column, not_null)（harness registry 契约要求 ≥5 distinct
    passing data tests）；metadata 按 harness 契约三键。
    """
    if ingestion_skill_version is None:
        # 从真实安装版本派生,防链记录与运行环境漂移(硬编码=provenance 漂移向量)
        import tushare as _ts

        ingestion_skill_version = f"tushare@{_ts.__version__}"
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
            # 语义标记进签名制品(additive,harness 白名单校验容忍):
            # 基准面 = as-of 当期成分,带幸存者选择,禁喂 confirmatory research。
            "panel_semantics": "benchmark_only_current_cohort",
            "survivorship": "biased_as_of_cohort",
            "research_use": "forbidden_confirmatory",
            "volume_unit": "lot_100_shares",
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
    dataset_id: str = "hs300_daily_10y_readbench_cohort",
    ingestion_skill_version: str | None = None,
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
    "HFQ_HARD_BAND",
    "HFQ_DIAGNOSTIC_BAND",
    "assemble_research_tables",
    "build_research_asset",
    "load_union_members",
    "research_quality_report",
    "load_members",
    "load_list_dates",
    "assemble_panel",
    "preflight_report",
    "register_panel",
    "build_chain",
]


# ── 研究面资产(第二资产):历史成分并集,无幸存者选择 ────────────────────────────
#
# 与基准面(readbench cohort)的分界:研究面 = index_weight 全史并集(~622 只,含退市/
# 已调出),raw bars + adj_factor + suspend_d 三表分离,禁 pre-join 复权(复权唯一落点
# 仍在 factor_factory/panel_source)。质量门内嵌卡 39d08df8 的两根探针:
#   #6 adj_factor look-ahead:每根 bar 必须有同日复权因子(左连零缺失)——因子日期
#      被前移/错位(种已知坏)必在此炸;
#   #7 停牌伪 bar:bar 日不得与「有记录的全天停牌日」相交——在已记录停牌日伪造
#      bar(种已知坏)必在此炸。诚实边界:Tushare suspend_d 早年记录不完整,
#      记录缺席≠未停牌,本门只在正向(有记录处)有牙。
# 复权因子的诚实模型(2026-07 真实 union 实测,证据见 evidence 包):
# - factor 在 A股不单调:缩股/重述/僵尸股双口径翻转都真实存在(532 处 >1e-4 回撤,
#   零舍入噪声级)——但翻转集中在停牌无 bar 日,对 bar 连接后的消费者不可见;
# - 质量门因此定在【bar 日 hfq 连续性】:hfq_ret = (close×factor) 的日收益。
#   真实极值 = +306%(盐湖股份 2021-08-10 恢复上市首日,无涨跌幅限制)、-79%/-63%
#   (退市整理期);99.99% 分位=0.20(涨跌停带)。硬门 3.5 抓十倍级 factor 错位/损坏,
#   >0.30 事件计数作诊断细节供复核。检测下限如实声明:3.5 倍以下的内部 factor
#   损坏本层不抓(涨跌停带内无法与真实行情区分),归跨源对账(后续工作)。

HFQ_HARD_BAND = 3.5
HFQ_DIAGNOSTIC_BAND = 0.30


def load_union_members(staging_dir: str | Path) -> list[str]:
    """历史成分并集(pull 时由全史 index_weight 快照聚合写入)。"""
    path = Path(staging_dir) / "member_union.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"member_union 缺失(先跑 pull): {path}")
    members = sorted(set(pl.read_parquet(path).get_column("ts_code").to_list()))
    if not members:
        raise ValueError("member_union 为空")
    return members


def _read_staged_kind(
    staging_dir: str | Path, kind: str, columns: list[str],
    *, members: set[str], start_c: str, end_c: str,
) -> pl.DataFrame:
    frames = []
    for path in sorted((Path(staging_dir) / kind).glob("*.parquet")):
        chunk = pl.read_parquet(path, columns=columns).filter(
            pl.col("ts_code").is_in(list(members))
            & (pl.col("trade_date") >= start_c)
            & (pl.col("trade_date") <= end_c)
        )
        if chunk.height:
            frames.append(chunk)
    if not frames:
        return pl.DataFrame(schema={c: pl.Utf8 for c in columns})
    return pl.concat(frames)


def assemble_research_tables(
    staging_dir: str | Path,
    *,
    members: list[str],
    start_date: str,
    end_date: str,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """union 三表:bars(canonical OHLCV) / factors(symbol,ts,adj_factor) / suspensions。"""
    start_c, end_c = _compact(start_date), _compact(end_date)
    member_set = set(members)
    bars = assemble_panel(
        staging_dir, members=members, start_date=start_date, end_date=end_date
    )
    factors = (
        _read_staged_kind(
            staging_dir, "adj_factor", ["ts_code", "trade_date", "adj_factor"],
            members=member_set, start_c=start_c, end_c=end_c,
        )
        .rename({"ts_code": "symbol"})
        .with_columns(
            pl.col("trade_date").str.strptime(pl.Datetime("us"), "%Y%m%d")
            .dt.replace_time_zone("UTC").alias("ts"),
            pl.col("adj_factor").cast(pl.Float64, strict=False),
        )
        .select(["symbol", "ts", "adj_factor"])
        .sort(["symbol", "ts"])
        .rechunk()
    )
    dup_f = factors.height - factors.select(pl.struct(["symbol", "ts"]).n_unique()).item()
    if dup_f:
        raise ValueError(f"adj_factor 含 {dup_f} 条重复 (symbol, ts)——源损坏")
    suspension_dir = Path(staging_dir) / "suspend_d"
    if suspension_dir.is_dir():
        suspensions = (
            _read_staged_kind(
                staging_dir, "suspend_d",
                ["ts_code", "trade_date", "suspend_timing", "suspend_type"],
                members=member_set, start_c=start_c, end_c=end_c,
            )
            .rename({"ts_code": "symbol"})
            .with_columns(
                pl.col("trade_date").str.strptime(pl.Datetime("us"), "%Y%m%d")
                .dt.replace_time_zone("UTC").alias("ts"),
            )
            .select(["symbol", "ts", "suspend_timing", "suspend_type"])
            .unique(subset=["symbol", "ts", "suspend_type"], keep="first",
                    maintain_order=True)
            .sort(["symbol", "ts"])
            .rechunk()
        )
    else:
        raise FileNotFoundError(f"suspend_d staging 缺失(先跑 pull): {suspension_dir}")
    return bars, factors, suspensions


def research_quality_report(
    bars: pl.DataFrame,
    factors: pl.DataFrame,
    suspensions: pl.DataFrame,
    *,
    current_members: set[str] | None = None,
    hfq_hard_band: float = HFQ_HARD_BAND,
) -> dict[str, Any]:
    """研究面质量门(诊断态跑全项)。含探针 #6(因子同日覆盖)与 #7(停牌伪 bar)。"""
    checks: dict[str, dict[str, Any]] = {}

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    dup_b = bars.height - bars.select(pl.struct(["symbol", "ts"]).n_unique()).item()
    _check("bars_no_duplicates", dup_b == 0, f"duplicates={dup_b}")
    weekend = bars.select((pl.col("ts").dt.date().dt.weekday() > 5).sum()).item()
    _check("bars_no_weekend", weekend == 0, f"weekend_rows={weekend}")
    bad_ohlc = bars.select(
        (
            (pl.col("open") <= 0) | (pl.col("high") <= 0) | (pl.col("low") <= 0)
            | (pl.col("close") <= 0) | (pl.col("volume") < 0)
            | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
        ).sum()
    ).item()
    _check("bars_ohlcv_invariants", bad_ohlc == 0, f"violating_rows={bad_ohlc}")

    # 探针 #6:每根 bar 必有同日因子(look-ahead/错位种坏必炸)
    joined = bars.join(factors, on=["symbol", "ts"], how="left")
    missing_factor = joined.get_column("adj_factor").null_count()
    _check(
        "factor_same_day_coverage",
        missing_factor == 0,
        f"bars_without_same_day_factor={missing_factor}",
    )
    nonpos = factors.select((pl.col("adj_factor") <= 0).sum()).item()
    _check("factor_positive", nonpos == 0, f"non_positive={nonpos}")
    hfq = (
        joined.sort(["symbol", "ts"])
        .with_columns(
            (
                (pl.col("close") * pl.col("adj_factor"))
                / (
                    pl.col("close").shift(1).over("symbol")
                    * pl.col("adj_factor").shift(1).over("symbol")
                )
                - 1.0
            ).alias("__hfq_ret")
        )
        .drop_nulls("__hfq_ret")
    )
    gross = hfq.select((pl.col("__hfq_ret").abs() > hfq_hard_band).sum()).item()
    diagnostic = hfq.select(
        (pl.col("__hfq_ret").abs() > HFQ_DIAGNOSTIC_BAND).sum()
    ).item()
    _check(
        "hfq_continuity_no_gross_spikes",
        gross == 0,
        f"abs_hfq_ret>{hfq_hard_band}={gross}; diagnostic>{HFQ_DIAGNOSTIC_BAND}="
        f"{diagnostic}(真实无涨跌幅事件会计入,供复核非判罚)",
    )

    # 探针 #7:bar 不得落在「有记录的全天停牌日」(伪 bar 种坏必炸;记录缺席≠未停牌)
    full_day_suspensions = suspensions.filter(
        (pl.col("suspend_type") == "S") & pl.col("suspend_timing").is_null()
    ).select(["symbol", "ts"])
    conflicts = bars.join(full_day_suspensions, on=["symbol", "ts"], how="inner").height
    _check(
        "no_bars_on_recorded_suspension_days",
        conflicts == 0,
        f"bars_on_recorded_full_day_suspensions={conflicts}",
    )

    union_symbols = set(bars.get_column("symbol").unique().to_list())
    if current_members is not None:
        beyond_current = len(union_symbols - set(current_members))
        _check(
            "survivorship_free_union",
            beyond_current > 0,
            f"union_members_beyond_current_snapshot={beyond_current}",
        )
    return {
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "bars_rows": bars.height,
        "factor_rows": factors.height,
        "suspension_rows": suspensions.height,
        "union_symbols": len(union_symbols),
    }


def build_research_asset(
    staging_dir: str | Path,
    *,
    registry_path: str | Path,
    out_dir: str | Path,
    snapshot_yyyymm: str,
    start_date: str,
    end_date: str,
    dataset_id: str = "hs300_research_universe_10y",
    source_ref: str = "tushare://daily",
    secret_ref: str = "keyring://quantbt/tushare",
    ingestion_skill_version: str | None = None,
) -> dict[str, Any]:
    """研究面资产:union 三表 → 质量门(探针 #6/#7)→ DatasetVersion(3 文件 manifest)。"""
    if ingestion_skill_version is None:
        import tushare as _ts

        ingestion_skill_version = f"tushare@{_ts.__version__}"
    members = load_union_members(staging_dir)
    current = set(load_members(staging_dir, snapshot_yyyymm))
    bars, factors, suspensions = assemble_research_tables(
        staging_dir, members=members, start_date=start_date, end_date=end_date
    )
    report = research_quality_report(bars, factors, suspensions, current_members=current)
    if not report["ok"]:
        failing = {k: v for k, v in report["checks"].items() if not v["ok"]}
        raise ValueError(f"研究面质量门未过,拒注册: {failing}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bars_path = out / "bars.parquet"
    factors_path = out / "adj_factors.parquet"
    suspensions_path = out / "suspensions.parquet"
    bars.write_parquet(bars_path)
    factors.write_parquet(factors_path)
    suspensions.write_parquet(suspensions_path)
    now_iso = datetime.now(UTC).isoformat()
    fetch_result = replace(
        make_wide_fetch_result(bars, source_name="tushare"),
        source_ref=source_ref,
        ingestion_skill_version=ingestion_skill_version,
        secret_ref=secret_ref,
        known_at_utc=now_iso,
        effective_at_utc=bars.get_column("ts").max().isoformat(),
    )
    registry = DatasetRegistry(Path(registry_path))
    version = registry.register(
        dataset_id,
        fetch_result,
        file_paths=[str(bars_path), str(factors_path), str(suspensions_path)],
        rules=[
            GERule(column=column, rule_type="not_null")
            for column in ("open", "high", "low", "close", "volume")
        ],
        metadata={
            "market": "stocks_cn",
            "interval": "1d",
            "data_kind": "ohlcv",
            "panel_semantics": "research_universe_union",
            "survivorship": "union_includes_delisted",
            "research_use": "pit_discipline_required",
            "adjustment_policy": "raw_plus_adj_factor_no_prejoin",
            "suspension_record_completeness": "positive_only_early_years_incomplete",
            "volume_unit": "lot_100_shares",
        },
        source_ref=source_ref,
        ingestion_skill_version=ingestion_skill_version,
        secret_ref=secret_ref,
        known_at_utc=fetch_result.known_at_utc,
        effective_at_utc=fetch_result.effective_at_utc,
        require_provenance=True,
    )
    return {
        "dataset_id": version.dataset_id,
        "dataset_version_ref": version.version_id,
        "manifest_path": str(version.manifest_path),
        "bars_path": str(bars_path),
        "factors_path": str(factors_path),
        "suspensions_path": str(suspensions_path),
        "quality": report,
    }
