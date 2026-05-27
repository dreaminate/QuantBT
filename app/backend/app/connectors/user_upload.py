"""DIY 数据源 · 用户拖拽 zip/tar.gz/csv/parquet 上传后注册成 dataset。

不真起 HTTP；这个 connector 只接受"上传后落盘的本地文件"（前端调
`/api/data/upload` 把文件保存到 `data/raw/uploads/{upload_id}/`，再把
`upload_id` 传给本 connector），把它转成 UnifiedOHLCV。

字段映射：用户在 UI 完成"原始列 → 统一列"的拖拽，写出一份 `mapping.json`
落在同目录；本 connector 读这份映射执行。
"""

from __future__ import annotations

import json
import tarfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel

from .base import (
    ConnectorCapability,
    DataConnector,
    FetchRequest,
    FetchResult,
    enforce_unified_schema,
    make_fetch_result,
)


class UploadFieldMapping(BaseModel):
    ts: str
    symbol: str | None = None
    open: str | None = None
    high: str | None = None
    low: str | None = None
    close: str
    volume: str | None = None
    amount: str | None = None
    market: str = "custom"
    interval: str = "1d"
    ts_unit: Literal["s", "ms", "us", "iso", "date"] = "iso"
    symbol_constant: str | None = None  # 文件只对应一个 symbol 时


class UploadDatasetRegistration(BaseModel):
    upload_id: str
    files: list[str]
    mapping: UploadFieldMapping


class UserUploadConnector(DataConnector):
    """从一个上传目录读 csv/parquet/zip/tar，按 mapping 转成 UnifiedOHLCV。"""

    def __init__(self, registration: UploadDatasetRegistration, upload_root: Path) -> None:
        self._reg = registration
        self._root = upload_root

    def describe(self) -> ConnectorCapability:
        return ConnectorCapability(
            name=f"upload::{self._reg.upload_id}",
            label=f"上传数据集 {self._reg.upload_id}",
            asset_class="custom",
            supported_markets=(self._reg.mapping.market,),
            supported_intervals=(self._reg.mapping.interval,),
            supported_data_kinds=("ohlcv",),
            auth_mode="none",
            rate_limit_per_minute=None,
            realtime=False,
            note=f"{len(self._reg.files)} 文件",
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        rows: list[dict[str, Any]] = []
        for relative in self._reg.files:
            path = self._root / self._reg.upload_id / relative
            rows.extend(self._read_one(path))
        df = pl.DataFrame(rows) if rows else pl.DataFrame()
        df = self._apply_mapping(df)
        if request.symbol:
            df = df.filter(pl.col("symbol") == request.symbol)
        if request.start:
            df = df.filter(pl.col("ts") >= request.start.replace(tzinfo=UTC))
        if request.end:
            df = df.filter(pl.col("ts") <= request.end.replace(tzinfo=UTC))
        return make_fetch_result(df, source_name=f"upload::{self._reg.upload_id}")

    def list_symbols(self, market: str | None = None) -> list[str]:  # noqa: ARG002
        symbols: set[str] = set()
        for relative in self._reg.files:
            path = self._root / self._reg.upload_id / relative
            for record in self._read_one(path):
                sym = record.get(self._reg.mapping.symbol) if self._reg.mapping.symbol else None
                if sym:
                    symbols.add(str(sym))
        if not symbols and self._reg.mapping.symbol_constant:
            symbols.add(self._reg.mapping.symbol_constant)
        return sorted(symbols)

    def _read_one(self, path: Path) -> Iterable[dict[str, Any]]:
        if not path.exists():
            return []
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pl.read_csv(path).to_dicts()
        if suffix == ".tsv":
            return pl.read_csv(path, separator="\t").to_dicts()
        if suffix == ".parquet":
            return pl.read_parquet(path).to_dicts()
        if suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        if suffix == ".zip":
            return self._read_zip(path)
        if suffix in {".tar", ".gz", ".tgz"} or path.name.endswith(".tar.gz"):
            return self._read_tar(path)
        return []

    def _read_zip(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                with zf.open(member) as fh:
                    if member.endswith(".csv"):
                        rows.extend(pl.read_csv(fh).to_dicts())
                    elif member.endswith(".parquet"):
                        rows.extend(pl.read_parquet(fh).to_dicts())
        return rows

    def _read_tar(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with tarfile.open(path) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                name = member.name
                if name.endswith(".csv"):
                    rows.extend(pl.read_csv(fh.read()).to_dicts())
                elif name.endswith(".parquet"):
                    rows.extend(pl.read_parquet(fh.read()).to_dicts())
        return rows

    def _apply_mapping(self, df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return enforce_unified_schema(df)
        m = self._reg.mapping
        select_exprs: list[pl.Expr] = []
        # ts handling
        ts_col = pl.col(m.ts) if m.ts in df.columns else pl.lit(None)
        if m.ts_unit == "iso":
            ts_expr = ts_col.cast(pl.String).str.to_datetime(time_zone="UTC", strict=False)
        elif m.ts_unit == "date":
            ts_expr = ts_col.cast(pl.String).str.to_datetime(format="%Y-%m-%d", time_zone="UTC", strict=False)
        elif m.ts_unit == "s":
            ts_expr = (ts_col.cast(pl.Float64) * 1_000_000).cast(pl.Datetime("us", "UTC"))
        elif m.ts_unit == "ms":
            ts_expr = (ts_col.cast(pl.Float64) * 1_000).cast(pl.Datetime("us", "UTC"))
        else:  # us
            ts_expr = ts_col.cast(pl.Datetime("us", "UTC"))
        select_exprs.append(ts_expr.alias("ts"))
        # symbol
        if m.symbol and m.symbol in df.columns:
            select_exprs.append(pl.col(m.symbol).cast(pl.String).alias("symbol"))
        elif m.symbol_constant:
            select_exprs.append(pl.lit(m.symbol_constant).alias("symbol"))
        else:
            select_exprs.append(pl.lit("UNKNOWN").alias("symbol"))
        select_exprs.append(pl.lit(m.market).alias("market"))
        select_exprs.append(pl.lit(m.interval).alias("interval"))
        # ohlcv
        for tgt in ("open", "high", "low", "close", "volume", "amount"):
            src = getattr(m, tgt)
            if src and src in df.columns:
                select_exprs.append(pl.col(src).cast(pl.Float64, strict=False).alias(tgt))
            else:
                default = 0.0 if tgt in {"volume", "amount"} else None
                select_exprs.append(pl.lit(default).cast(pl.Float64).alias(tgt))
        out = df.select(select_exprs)
        return enforce_unified_schema(out)


def write_registration(root: Path, registration: UploadDatasetRegistration) -> Path:
    target_dir = root / registration.upload_id
    target_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "upload_id": registration.upload_id,
        "files": registration.files,
        "mapping": registration.mapping.model_dump(),
        "registered_at_utc": datetime.now(UTC).isoformat(),
    }
    (target_dir / "registration.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return target_dir / "registration.json"


def load_registration(path: Path) -> UploadDatasetRegistration:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    mapping = UploadFieldMapping.model_validate(data["mapping"])
    return UploadDatasetRegistration(
        upload_id=data["upload_id"],
        files=data["files"],
        mapping=mapping,
    )


__all__ = [
    "UploadDatasetRegistration",
    "UploadFieldMapping",
    "UserUploadConnector",
    "load_registration",
    "write_registration",
]
