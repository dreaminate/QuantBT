"""数据平台 v2 · 数据集来源（DatasetSource）。

FieldCatalog 合并多个 ``DatasetSource``：
- ``InventoryDatasetSource``（**主**）：读 ``data/catalog/inventory.json``（官方拉数落盘的真相），
  按 (source, market, interval, data_kind) 把 per-symbol 文件聚成一个逻辑数据集。
- ``RegistryDatasetSource``（辅）：读 ``DatasetRegistry``（爬虫 ``register_official_dataset`` /
  wide-parquet 注册的数据集，带显式 source_name）。

source 归属（位置感知）：磁盘布局是 ``data/market/<market>/<source?>/<data_kind>/...``，真 source 只可能
出现在 ``market`` 段之后的固定位；只有该定位段以 user_/crawler_ 开头(或 upload)才判用户/爬虫源，
否则按 market 约定归到官方源——避免把 home 目录(/Users/user_x)或 data_kind 名误判成源。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..data_quality import DatasetRegistry
from .contract import DatasetInfo, FileRef

_logger = logging.getLogger(__name__)

# inventory 期望版本（与 tushare_quant1/data_catalog.CATALOG_VERSION 对齐）；低于此或缺 columns 即重建。
_EXPECTED_CATALOG_VERSION = 3

# market 命名归一：现代 Binance 落盘目录段是字面量 "crypto"，但源开关/字段宇宙/前端按 "binanceusdm" 查询。
_MARKET_ALIASES = {"crypto": "binanceusdm"}

# market → 官方源名 约定（位置感知未命中用户/爬虫段时的兜底归属）
_OFFICIAL_BY_MARKET = {
    "stocks_cn": "tushare",
    "indices_cn": "tushare",
    "funds_cn": "tushare",
    "bonds_cn": "tushare",
    "binanceusdm": "binance",
    "binance_spot": "binance",
    "crypto": "binance",
}


def _normalize_market(market: str | None) -> str | None:
    if market is None:
        return None
    return _MARKET_ALIASES.get(str(market), str(market))


@runtime_checkable
class DatasetSource(Protocol):
    def list_datasets(self) -> list[DatasetInfo]: ...


class RegistryDatasetSource:
    """从 DatasetRegistry 取每个 dataset_id 的最新版本。"""

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry

    def list_datasets(self) -> list[DatasetInfo]:
        latest: dict[str, DatasetInfo] = {}
        seen_at: dict[str, str] = {}
        for v in self._registry.list_versions():
            prev = seen_at.get(v.dataset_id)
            if prev is not None and v.fetched_at_utc < prev:  # append-only：并列时间戳后写入即最新
                continue
            seen_at[v.dataset_id] = v.fetched_at_utc
            meta = v.metadata or {}
            latest[v.dataset_id] = DatasetInfo(
                dataset_id=v.dataset_id,
                source_name=v.source_name,
                market=_normalize_market(meta.get("market")),
                interval=meta.get("interval"),
                data_kind=meta.get("data_kind"),
                columns=list(meta.get("columns") or []),
                files=[FileRef(p) for p in (v.file_paths or [])],
            )
        return list(latest.values())


class InventoryDatasetSource:
    """从 inventory.json 把 per-symbol 文件聚成 (source,market,interval,data_kind) 数据集。"""

    def __init__(self, inventory_path: Path | str, *, rebuild: Callable[[], None] | None = None) -> None:
        self._path = Path(inventory_path)
        self._rebuild = rebuild

    def _maybe_rebuild(self) -> None:
        if self._rebuild is None:
            return
        try:
            self._rebuild()
        except Exception:  # noqa: BLE001 - 保持韧性，但留诊断面包屑（区分"无数据"与"重建失败"）
            _logger.warning("inventory rebuild 失败（字段宇宙可能为空）", exc_info=True)

    def _load_payload(self) -> dict | None:
        if not self._path.exists():
            self._maybe_rebuild()
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _logger.warning("inventory.json 解析失败: %s", self._path, exc_info=True)
            return None
        # 版本感知重建：旧版(无 columns / version 落后)会让字段宇宙静默为空 → 主动重建一次
        files = payload.get("files") or []
        stale = payload.get("catalog_version", 0) < _EXPECTED_CATALOG_VERSION or any(
            "columns" not in item for item in files
        )
        if stale and self._rebuild is not None:
            self._maybe_rebuild()
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return payload
        return payload

    def list_datasets(self) -> list[DatasetInfo]:
        payload = self._load_payload()
        if not payload:
            return []
        groups: dict[tuple, DatasetInfo] = {}
        for item in payload.get("files") or []:
            fp = item.get("file_path")
            if not fp:
                continue
            market = _normalize_market(item.get("market"))
            interval = item.get("interval")
            data_kind = item.get("data_kind") or "ohlcv"
            source = _infer_source(market, fp)
            key = (source, market, interval, data_kind)
            di = groups.get(key)
            if di is None:
                did = "__".join(str(x) for x in (source, market, data_kind, interval) if x)
                di = DatasetInfo(dataset_id=did, source_name=source, market=market, interval=interval, data_kind=data_kind, columns=[], files=[])
                groups[key] = di
            for c in item.get("columns") or []:
                if c not in di.columns:
                    di.columns.append(c)
            di.files.append(FileRef(fp, item.get("symbol_key")))
        return list(groups.values())


def _infer_source(market: str | None, file_path: str) -> str:
    """位置感知：只看 ``market`` 段之后的定位段判用户/爬虫源，否则按 market 约定归官方。"""
    parts = list(Path(str(file_path)).parts)
    if "market" in parts:
        i = parts.index("market")
        if i + 2 < len(parts):  # parts[i+1]=市场目录, parts[i+2]=源(intake) 或 data_kind(connector)
            cand = parts[i + 2].lower()
            if cand.startswith("crawler_") or cand.startswith("user_"):
                return cand
            if cand in ("uploads", "upload"):
                return "user_upload"
    return _OFFICIAL_BY_MARKET.get(str(market), str(market) if market else "unknown")


__all__ = ["DatasetSource", "RegistryDatasetSource", "InventoryDatasetSource"]
