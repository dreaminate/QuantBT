"""数据平台 v2 · 字段目录（一等公民）。

合并多个 ``DatasetSource``（inventory 为主、registry 为辅）作为真相源，对外提供：
- ``list_datasets`` / ``dataset_columns``：有哪些数据集、各自真实列。
- ``available_fields``：当前（可按 enabled 源过滤的）"可用字段宇宙"（canonical + freeform）。
- ``resolve``：某个 field_id 由哪个源/数据集/原始列提供。
- ``load_panel``：按 ``FieldRequirement`` 把多数据集拼成一个 ``WidePanel``（量化流程入口）。

源开关过滤通过 ``source_filter`` 回调注入；默认放行全部源。

实现要点（经两轮对抗式复核加固）：
- 读盘后 key 规范化：时间列(timestamp/trade_date/end_date/...)→ts、symbol 列(ts_code/...)→symbol、
  单 symbol 文件从 ``FileRef.symbol`` 注入；ts 统一转 Datetime(us,UTC)，**兼容 Date/naive/tz-aware/
  字符串/整数 epoch/紧凑 YYYYMMDD，且任何解析失败都不抛**（坏文件被跳过，不整批 abort panel）。
- 每个子表按 (ts,symbol) 去重，防止财报重述等"同键多行"在 join 时行扇出。
- freeform 字段 id 用合法标识符（``{source}__{col}``）；映射后落到结构键的字段被防御性跳过。
- amount 派生按行 coalesce（兼顾"部分缺失"）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from ..data_quality import DatasetRegistry
from ..universe.resolver import AsOf, as_of_bound  # R28 双时态 as_of_known 复用单一 as-of 边界
from .canonical import CANONICAL, CanonicalRegistry
from .contract import DatasetInfo, FieldRequirement, PanelResult, WidePanel
from .mapping import FieldMappingStore
from .sources import DatasetSource, RegistryDatasetSource, is_official_source

# ts/symbol 是 join 键，market/interval 是元数据 —— 不计入"字段宇宙"。
# known_at 是 R28 双时态 first-seen 属性轴（非字段、非身份键）—— 同样剔出字段宇宙，绝不当因子暴露。
_STRUCTURAL = {"ts", "symbol", "market", "interval", "known_at"}

SourceFilter = Callable[[str, str | None], bool]  # (source_name, market) -> 是否启用

# ============================================================
# C-S11-PIT-ENFORCE · confirmatory 取数物化硬门（GOAL §11 line1759）
# ============================================================
# GOAL §11 可证伪验收：「无 PIT 语义的数据进入 confirmatory validation → 拒」。
# 真前视面在 _materialize_sub：as_of_known 给定但某数据集**无 known_at 列** → 静默落到现行视图
# （keep="last"），调用方以为做了 PIT 折叠、实拿到含未来重述的当前视图 = 前视。confirmatory run
# 绝不能吃这口静默 fall-through。本门让 load_panel 在 confirmatory 上下文下 fail-closed：
#   ① as_of_known 未 pin（无知识时点）→ 拒；② 解析到零数据集 → 拒；③ 任一贡献数据集无 known_at 轴
#   （静默落空）→ 拒。非 confirmatory（None/research/backtest/...）逐字现状，向后兼容、不误伤探索。
# 单一源：confirmatory 的判定值镜像 research_os.market_data_contract.ValidationUseContext
# .CONFIRMATORY_VALIDATION（字符串 "confirmatory_validation"）；field_catalog 是低层数据脊梁
# （"模块永不 import connector"），同理不引重量级 research_os 包，按值镜像（与 codegen 镜像 load_panel
# 折叠语义同一手法），canonical 仍在那枚枚举。
_CONFIRMATORY_CONTEXT = "confirmatory_validation"

# 单点可逆：中心整合跑全量后若某 confirmatory 取数路径破基线 → 翻 False 全局回退（无需改门/调用点）。
ENFORCE_CONFIRMATORY_PANEL_PIT = True


class ConfirmatoryPanelRejected(RuntimeError):
    """confirmatory 取数缺 PIT —— 未 pin as_of_known / 零数据集 / 无 known_at 轴（静默落空=前视·GOAL §11 line1759）。"""


def _is_confirmatory(use_context: object) -> bool:
    """归一 use_context（Enum/str/None）→ 是否 confirmatory（单一源 = ValidationUseContext.CONFIRMATORY_VALIDATION 值）。"""
    if use_context is None:
        return False
    return str(getattr(use_context, "value", use_context)) == _CONFIRMATORY_CONTEXT

_NON_IDENT = re.compile(r"[^0-9A-Za-z_]+")

# 磁盘真实列名 → 规范键（首个命中）。财报的 end_date/ann_date 排在通用 date 之前，避免选错时间轴；
# close_time 等不在候选内，不会被误选为 ts。
_TS_CANDIDATES = ("ts", "timestamp", "trade_date", "end_date", "ann_date", "datetime", "date", "cal_date", "nav_date", "time")
_SYMBOL_CANDIDATES = ("symbol", "ts_code", "security", "code")

_INT_TYPES = {pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64}


def _ident(value: str) -> str:
    """把任意来源名/列名压成合法 Python 标识符片段（供 freeform 字段 id 用）。"""
    s = _NON_IDENT.sub("_", str(value)).strip("_")
    if not s:
        return "x"
    if s[0].isdigit():
        s = "_" + s
    return s


@dataclass
class FieldEntry:
    field_id: str
    is_freeform: bool
    source_name: str
    dataset_id: str
    raw_column: str


@dataclass
class FieldUniverse:
    market: str
    canonical: dict[str, FieldEntry] = field(default_factory=dict)
    freeform: dict[str, FieldEntry] = field(default_factory=dict)

    def ids(self) -> list[str]:
        return [*self.canonical.keys(), *self.freeform.keys()]

    def to_dict(self) -> dict[str, list[dict]]:
        def _dump(d: dict[str, FieldEntry]) -> list[dict]:
            return [
                {"field_id": e.field_id, "source": e.source_name, "dataset_id": e.dataset_id, "raw_column": e.raw_column}
                for e in d.values()
            ]

        return {"canonical": _dump(self.canonical), "freeform": _dump(self.freeform)}


class FieldCatalog:
    def __init__(
        self,
        registry: DatasetRegistry | None = None,
        *,
        sources: list[DatasetSource] | None = None,
        canonical: CanonicalRegistry | None = None,
        mapping: FieldMappingStore | None = None,
        source_filter: SourceFilter | None = None,
    ) -> None:
        srcs: list[DatasetSource] = list(sources) if sources else []
        if registry is not None:
            srcs.append(RegistryDatasetSource(registry))
        self._sources = srcs
        self._canonical = canonical or CANONICAL
        self._mapping = mapping
        self._source_filter: SourceFilter = source_filter or (lambda _s, _m: True)

    # ---- 数据集枚举 ---------------------------------------------------------

    def _all_datasets(self) -> list[DatasetInfo]:
        out: dict[str, DatasetInfo] = {}
        for src in self._sources:
            for ds in src.list_datasets():
                existing = out.get(ds.dataset_id)
                if existing is None:
                    out[ds.dataset_id] = ds
                else:
                    # 同 id 多源：保留先到者(inventory 为主)，但 union 列集避免静默丢列
                    for c in ds.columns:
                        if c not in existing.columns:
                            existing.columns.append(c)
        return list(out.values())

    def list_datasets(
        self, *, market: str | None = None, interval: str | None = None, enabled_only: bool = True
    ) -> list[DatasetInfo]:
        out: list[DatasetInfo] = []
        for ds in self._all_datasets():
            if market is not None and ds.market != market:
                continue
            if interval is not None and ds.interval is not None and ds.interval != interval:
                continue
            if enabled_only and not self._source_filter(ds.source_name, ds.market):
                continue
            out.append(ds)
        return out

    def dataset_columns(self, dataset_id: str) -> list[str]:
        for ds in self._all_datasets():
            if ds.dataset_id == dataset_id:
                return ds.columns
        return []

    # ---- 字段分类 -----------------------------------------------------------

    def _classify(self, ds: DatasetInfo, raw_column: str) -> FieldEntry:
        data_kind = ds.data_kind or "ohlcv"
        # 官方源 = 白名单(tushare/binance/crawler_*)；user_/upload/自定义 DIY/custom 等一律按用户
        official = is_official_source(ds.source_name)
        # 1) 显式映射覆盖优先（用户/Agent 指定的 id 原样用）
        if self._mapping is not None:
            override = self._mapping.get(ds.source_name, data_kind).get(raw_column)
            if override is not None:
                fid, is_free = override
                return FieldEntry(fid, is_free, ds.source_name, ds.dataset_id, raw_column)
        # 2) canonical 词典解析；官方提供的字段一律加 official_ 前缀，与用户同名字段区分、绝不撞名
        canon = self._canonical.resolve(raw_column, ds.market)
        if canon is not None:
            fid = f"official_{canon}" if official else canon
            return FieldEntry(fid, False, ds.source_name, ds.dataset_id, raw_column)
        # 3) freeform：官方 → official_<source>__<col>；用户 → <source>__<col>（均带源命名空间，防同名列撞名）
        if official:
            fid = f"official_{_ident(ds.source_name)}__{_ident(raw_column)}"
        else:
            fid = f"{_ident(ds.source_name)}__{_ident(raw_column)}"
        return FieldEntry(fid, True, ds.source_name, ds.dataset_id, raw_column)

    def _universe_from_datasets(self, datasets: list[DatasetInfo], market: str) -> FieldUniverse:
        universe = FieldUniverse(market=market)
        for ds in datasets:
            for col in ds.columns:
                if col in _STRUCTURAL:
                    continue
                entry = self._classify(ds, col)
                # 防御：映射后落到结构键(如恶意/手滑把列映射成 'ts')的字段，不能进宇宙，
                # 否则 load_panel 里 alias 成 'ts'/'symbol' 会与 join 键重名抛 DuplicateError。
                if entry.field_id in _STRUCTURAL:
                    continue
                bucket = universe.freeform if entry.is_freeform else universe.canonical
                bucket.setdefault(entry.field_id, entry)
        return universe

    def available_fields(
        self, market: str, *, interval: str | None = None, enabled_only: bool = True
    ) -> FieldUniverse:
        datasets = self.list_datasets(market=market, interval=interval, enabled_only=enabled_only)
        return self._universe_from_datasets(datasets, market)

    def resolve(
        self, field_id: str, market: str, *, interval: str | None = None, enabled_only: bool = True
    ) -> FieldEntry | None:
        universe = self.available_fields(market, interval=interval, enabled_only=enabled_only)
        return universe.canonical.get(field_id) or universe.freeform.get(field_id)

    # ---- 装载 panel（量化流程入口）-----------------------------------------

    def load_panel(
        self,
        req: FieldRequirement,
        *,
        enabled_only: bool = True,
        as_of_known: AsOf | None = None,
        keep_known_at_axis: bool = False,
        use_context: object = None,
    ) -> PanelResult:
        """装载 panel（量化流程入口）。R28 双时态：

        - ``as_of_known`` 给定 → 各数据集先按 ``known_at <= as_of_known`` 过滤，再同 (ts,symbol)
          取最新已知重述（= 重述 as-of 点查）。None → 当前全知视图（``keep="last"``），逐字现状
          不变（守 ``test_data_contract.py:139`` 折叠契约）。
        - ``keep_known_at_axis=True``（Stage②）→ 保留 known_at 轴、不折叠（end_date×known_at 双轴
          长表，单财报集重述时间线分析用）。诚实限界：多数据集双轴对齐 ill-defined（各表重述
          known_at 不齐），仅对单数据集需求语义干净。
        - ``use_context``（C-S11-PIT-ENFORCE）：标 ``confirmatory_validation`` 时 fail-closed —— 未 pin
          ``as_of_known`` / 零数据集 / 任一数据集无 known_at 轴（静默落空=前视）→ raise
          ``ConfirmatoryPanelRejected``（GOAL §11 line1759）。缺省 None / 其它 → 逐字现状（向后兼容）。
          返回的 ``pit_filter_applied`` / ``pit_missing_known_at`` 是显式 PIT 物化证据（不挪用 has_known_at_axis）。
        """

        datasets = self.list_datasets(market=req.market, interval=req.interval, enabled_only=enabled_only)
        universe = self._universe_from_datasets(datasets, req.market)
        ds_index = {ds.dataset_id: ds for ds in datasets}

        resolved: dict[str, FieldEntry] = {}
        for fid in req.all_ids():
            entry = universe.canonical.get(fid) or universe.freeform.get(fid)
            if entry is not None:
                resolved[fid] = entry

        by_dataset: dict[str, list[FieldEntry]] = {}
        for entry in resolved.values():
            by_dataset.setdefault(entry.dataset_id, []).append(entry)

        want_known = as_of_known is not None or keep_known_at_axis
        subs: list[pl.DataFrame] = []
        manifest: dict[str, str] = {}
        any_known_axis = False
        contributing = 0                       # 真贡献字段进 panel 的数据集数（confirmatory 零数据集→拒）
        missing_known_at: list[str] = []       # 请求 as_of_known 但无 known_at 轴（静默落空=前视面）的 dataset_id
        for dataset_id, entries in by_dataset.items():
            ds = ds_index.get(dataset_id)
            if ds is None:
                continue
            needed = {e.raw_column for e in entries}
            frame = _read_dataset(ds, needed, req.symbols, extra_cols=("known_at",) if want_known else ())
            if frame is None or frame.is_empty():
                continue
            cols = frame.columns
            select = [pl.col("ts"), pl.col("symbol")]
            seen_fids: set[str] = set()
            for e in entries:
                # 防御：跳过结构键/重复 field_id，避免 alias 重名触发 polars DuplicateError
                if e.field_id in _STRUCTURAL or e.field_id in seen_fids:
                    continue
                if e.raw_column in cols:
                    select.append(pl.col(e.raw_column).alias(e.field_id))
                    manifest[e.field_id] = e.source_name
                    seen_fids.add(e.field_id)
            if len(select) <= 2:
                continue
            contributing += 1
            # C-S11-PIT-ENFORCE：请求 PIT 折叠(as_of_known) 但本数据集无 known_at 轴 → _materialize_sub
            # 会静默落到现行视图（前视面）。记下来供 confirmatory 硬门 + pit_filter_applied 证据（绝不静默放过）。
            if as_of_known is not None and "known_at" not in cols:
                missing_known_at.append(dataset_id)
            sub = _materialize_sub(frame, select, as_of_known, keep_known_at_axis)
            if want_known and keep_known_at_axis and "known_at" in sub.columns:
                any_known_axis = True
            subs.append(sub)

        # C-S11-PIT-ENFORCE：confirmatory 取数硬门——在返回 panel 前 fail-closed 拒非 PIT（look-ahead 红线）。
        pit_filter_applied = as_of_known is not None and contributing > 0 and not missing_known_at
        if _is_confirmatory(use_context) and ENFORCE_CONFIRMATORY_PANEL_PIT:
            self._reject_nonpit_confirmatory(as_of_known, contributing, missing_known_at, req)

        panel = _join_on_keys(subs)

        # amount 派生：兼容裸名(用户源 close/volume)与官方前缀(official_close/official_volume)
        if req.derive:
            for _pfx in ("", "official_"):
                c, v, a = f"{_pfx}close", f"{_pfx}volume", f"{_pfx}amount"
                if not {c, v}.issubset(panel.columns):
                    continue
                if a not in panel.columns:
                    panel = panel.with_columns((pl.col(c) * pl.col(v)).alias(a))
                    manifest.setdefault(a, "derived")
                else:
                    panel = panel.with_columns(pl.coalesce([pl.col(a), pl.col(c) * pl.col(v)]).alias(a))

        present = {
            c for c in panel.columns if panel.height > 0 and panel.get_column(c).null_count() < panel.height
        }
        missing = [fid for fid in req.canonical_ids if fid not in present]
        optional_missing = [fid for fid in req.optional_ids if fid not in present]
        return PanelResult(
            panel=panel,
            manifest=manifest,
            missing=missing,
            optional_missing=optional_missing,
            row_count=panel.height,
            as_of_known=as_of_known,
            has_known_at_axis=any_known_axis,
            pit_filter_applied=pit_filter_applied,
            pit_missing_known_at=tuple(missing_known_at),
        )

    @staticmethod
    def _reject_nonpit_confirmatory(
        as_of_known: AsOf | None,
        contributing: int,
        missing_known_at: list[str],
        req: FieldRequirement,
    ) -> None:
        """confirmatory 取数缺 PIT → raise（GOAL §11 line1759·look-ahead 红线·RULES.project §5）。"""
        if as_of_known is None:
            raise ConfirmatoryPanelRejected(
                f"confirmatory 取数（market={req.market} interval={req.interval}）必须 pin as_of_known"
                "（PIT 知识时点）→ 拒裸全知视图（无知识时点=前视·GOAL §11 line1759）"
            )
        if contributing == 0:
            raise ConfirmatoryPanelRejected(
                f"confirmatory 取数（market={req.market} interval={req.interval}）解析到零数据集 —— "
                "无可核验 PIT，fail-closed 拒（绝不放行不可核验数据进 confirmatory validation·GOAL §11）"
            )
        if missing_known_at:
            raise ConfirmatoryPanelRejected(
                f"confirmatory 取数：数据集 {sorted(missing_known_at)} 无 known_at 轴，as_of_known 静默落空 "
                "= 拿到含未来重述的现行视图（前视）→ 拒（GOAL §11 line1759·无 PIT 语义不得进 confirmatory）"
            )


def _materialize_sub(
    frame: pl.DataFrame,
    select: list[pl.Expr],
    as_of_known: AsOf | None,
    keep_known_at_axis: bool,
) -> pl.DataFrame:
    """把单数据集 frame 物化成 sub（R28 双时态折叠分叉）。

    - 无 known_at 列 或 不要双时态 → 现行 keep="last"（同 (ts,symbol) 取最新写入），逐字不变。
    - as_of_known → 先按 known_at<=as_of_known 过滤，再同 (ts,symbol) 取 known_at 最大者（=该时点
      最新已知重述），known_at 折叠后 drop（panel 保持 ts×symbol 宽表契约）。
    - keep_known_at_axis → 保留 known_at 轴、不折叠（双轴长表）。
    """

    want_known = as_of_known is not None or keep_known_at_axis
    if not (want_known and "known_at" in frame.columns):
        return frame.select(select).unique(subset=["ts", "symbol"], keep="last", maintain_order=True)
    select_kn = [*select, pl.col("known_at")]
    fr = frame
    if as_of_known is not None:
        fr = fr.filter(pl.col("known_at") <= as_of_bound(as_of_known, fr.schema["known_at"]))
    if keep_known_at_axis:
        return fr.select(select_kn)
    return (
        fr.select(select_kn)
        .sort("known_at")
        .unique(subset=["ts", "symbol"], keep="last", maintain_order=True)
        .drop("known_at")
    )


def _read_file(path: str) -> pl.DataFrame | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        if p.suffix.lower() == ".parquet":
            return pl.read_parquet(p)
        return pl.read_csv(p, try_parse_dates=True)
    except Exception:  # noqa: BLE001
        return None


def _read_dataset(
    ds: DatasetInfo,
    needed_raw: set[str],
    symbols: list[str] | None,
    extra_cols: tuple[str, ...] = (),
) -> pl.DataFrame | None:
    frames: list[pl.DataFrame] = []
    for fref in ds.files:
        df = _read_file(fref.path)
        if df is None or df.is_empty():
            continue
        try:
            df = _normalize_disk_keys(df, fref.symbol)
        except Exception:  # noqa: BLE001 - 单个坏文件的 key 规范化失败不应整批 abort panel
            continue
        if "ts" not in df.columns or "symbol" not in df.columns:
            continue
        keep = list(
            dict.fromkeys(
                ["ts", "symbol", *[c for c in needed_raw if c in df.columns], *[c for c in extra_cols if c in df.columns]]
            )
        )
        df = df.select(keep)
        if symbols:
            df = df.filter(pl.col("symbol").is_in(symbols))
        frames.append(df)
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]
    return pl.concat(frames, how="diagonal_relaxed")


def _normalize_disk_keys(df: pl.DataFrame, file_symbol: str | None) -> pl.DataFrame:
    """磁盘真实列名 → ts/symbol，并统一 dtype。"""
    lower = {c.lower(): c for c in df.columns}
    if "ts" not in df.columns:
        for cand in _TS_CANDIDATES:
            if cand in lower and lower[cand] != "ts":
                df = df.rename({lower[cand]: "ts"})
                break
    if "symbol" not in df.columns:
        for cand in _SYMBOL_CANDIDATES:
            if cand in lower:
                df = df.rename({lower[cand]: "symbol"})
                break
    if "symbol" not in df.columns and file_symbol is not None:
        df = df.with_columns(pl.lit(file_symbol).alias("symbol"))
    return _normalize_key_dtypes(df)


def _normalize_key_dtypes(df: pl.DataFrame) -> pl.DataFrame:
    """symbol→String、ts→Datetime(us, UTC)；兼容 Date/naive/tz-aware/字符串/整数 epoch/紧凑 YYYYMMDD。

    任何解析失败都不抛（返回原 df 或尽力转换），由调用方按"ts 缺失/无效"跳过该文件。
    """
    if "symbol" in df.columns:
        df = df.with_columns(pl.col("symbol").cast(pl.String, strict=False))
    if "ts" not in df.columns:
        return df
    try:
        return df.with_columns(_ts_to_utc(df.get_column("ts")).alias("ts"))
    except Exception:  # noqa: BLE001
        return df


def _ts_to_utc(s: pl.Series) -> pl.Series:
    dt = s.dtype
    if dt == pl.Date:
        return s.cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
    if isinstance(dt, pl.Datetime):
        if dt.time_zone is None:
            return s.cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
        return s.cast(pl.Datetime("us", dt.time_zone)).dt.convert_time_zone("UTC")
    if dt in _INT_TYPES:
        mx = s.abs().max()
        if mx is None:
            return s.cast(pl.Datetime("us", "UTC"), strict=False)
        if 10_000_000 <= int(mx) < 100_000_000:  # 紧凑 YYYYMMDD
            return s.cast(pl.String).str.to_datetime(format="%Y%m%d", time_unit="us", strict=False).dt.replace_time_zone("UTC")
        unit = "ns" if mx >= 10**18 else "us" if mx >= 10**15 else "ms" if mx >= 10**12 else "s"
        return s.cast(pl.Datetime(unit)).cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
    # 字符串/其它：用 eager Series 形式解析（兼容 polars 1.40 的"tz in data + no format"）
    ss = s.cast(pl.String, strict=False).str.replace("Z", "+00:00")
    try:
        return ss.str.to_datetime(format="%Y%m%d", time_unit="us", strict=True).dt.replace_time_zone("UTC")
    except Exception:  # noqa: BLE001 - 非紧凑日期，走通用解析
        pass
    parsed = ss.str.to_datetime(time_unit="us", strict=False)
    if isinstance(parsed.dtype, pl.Datetime) and parsed.dtype.time_zone is not None:
        return parsed.dt.convert_time_zone("UTC")
    return parsed.dt.replace_time_zone("UTC")


def _join_on_keys(subs: list[pl.DataFrame]) -> WidePanel:
    if not subs:
        return pl.DataFrame()
    keys = pl.concat([s.select(["ts", "symbol"]) for s in subs], how="vertical_relaxed").unique()
    panel = keys
    for sub in subs:
        panel = panel.join(sub, on=["ts", "symbol"], how="left")
    return panel.sort(["symbol", "ts"]) if {"symbol", "ts"}.issubset(panel.columns) else panel


__all__ = ["FieldCatalog", "DatasetInfo", "FieldEntry", "FieldUniverse", "SourceFilter"]
