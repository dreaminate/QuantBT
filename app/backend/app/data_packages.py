"""数据平台 v2 · 官方数据更新通道（服务端基础）。

网站是官方数据的源头（跑官方拉取）。客户端（Win/Mac 软件）不各自去捅 Tushare/Binance，
而是从这里以**版本化 zip 包**下载官方数据库更新。

**与软件更新分两条线**：
- 软件更新 = 换二进制/版本（PyInstaller 包），低频，走安装器/自动更新器。
- 数据更新 = 官方库新数据，本模块负责：`manifest`（清单 + 每文件指纹 + 数据版本号）→
  客户端比对本地指纹算增量 → 下载（全量或按文件增量）→ 解压进本地数据湖 → 重建目录。
两者各自版本号（manifest.data_version vs app 版本），互不绑定。

只打包**官方源**文件（tushare/binance/crawler_*）；用户自带源数据不下发。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .field_catalog.sources import _infer_source, is_official_source


def _rel(file_path: str, root: Path) -> str | None:
    try:
        return Path(file_path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _is_official(market: str | None, file_path: str) -> bool:
    # 白名单：只有归到官方源(tushare/binance/crawler_*)才下发；custom/unknown/用户源一律不打包
    return is_official_source(_infer_source(market, file_path))


def official_manifest(catalog_files: list[dict], root: Path | str) -> dict[str, Any]:
    """从 inventory 文件清单挑出官方文件，产出可下发的 manifest（含每文件指纹 + 数据版本号）。"""
    root = Path(root)
    items: list[dict[str, Any]] = []
    for it in catalog_files:
        fp = it.get("file_path")
        if not fp or not _is_official(it.get("market"), fp):
            continue
        rel = _rel(fp, root)
        if rel is None:
            continue
        items.append(
            {
                "path": rel,
                "source": _infer_source(it.get("market"), fp),
                "market": it.get("market"),
                "data_kind": it.get("data_kind"),
                "interval": it.get("interval"),
                "symbol": it.get("symbol_key"),
                "columns": it.get("columns") or [],
                "row_count": it.get("row_count"),
                # 指纹：updated_at + row_count，客户端据此判断某文件是否需要重下（无需逐文件 hash）
                "fingerprint": f"{it.get('updated_at')}|{it.get('row_count')}",
                "updated_at": it.get("updated_at"),
            }
        )
    items.sort(key=lambda x: x["path"])
    fp_blob = "\n".join(f"{x['path']}|{x['fingerprint']}" for x in items)
    data_version = hashlib.sha256(fp_blob.encode("utf-8")).hexdigest()[:16]
    return {
        "channel": "official-data",  # 与"软件更新"通道区分
        "data_version": data_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "file_count": len(items),
        "files": items,
    }


def build_package_zip(
    catalog_files: list[dict],
    root: Path | str,
    out_zip: Path | str,
    *,
    rel_paths: list[str] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把官方数据打成 zip（含 manifest.json）。

    rel_paths=None → 全量；否则只打这些相对路径（客户端按 manifest 算出的增量清单）。
    manifest 可传入预构造的（避免重复排序/哈希）。返回打进去的 manifest 子集。
    """
    root = Path(root)
    manifest = manifest or official_manifest(catalog_files, root)
    if rel_paths is not None:
        want = set(rel_paths)
        selected = [f for f in manifest["files"] if f["path"] in want]
    else:
        selected = manifest["files"]
    sub_manifest = {**manifest, "files": selected, "partial": rel_paths is not None}
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(sub_manifest, ensure_ascii=False, indent=2))
        for f in selected:
            abs_p = root / f["path"]
            if abs_p.exists():
                z.write(abs_p, arcname=f["path"])
    return sub_manifest


__all__ = ["official_manifest", "build_package_zip"]
