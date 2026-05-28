"""一键导出"我的所有数据" (GOAL §13.6 最后一项)。

打包内容：
- data/datasets/ · data/factors/ · data/experiments/ · data/audit/
- data/artifacts/experiments/ 标准 run 目录（用户产出的所有回测）
- connectors/ 用户自定义 YAML connector
- ~/.quantbt/secrets.yaml.template 复制，原 secrets.yaml **不导出** (含敏感)

输出：tar.gz 流（适合 FastAPI StreamingResponse 大文件场景）
"""

from __future__ import annotations

import io
import os
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


_DEFAULT_INCLUDES = (
    "datasets",
    "factors",
    "experiments",
    "audit",
    "artifacts",
    "connectors",
)
_EXCLUDE_NAMES = {
    "secrets.yaml",
    "keystore_index.json",
    ".cache",
    "__pycache__",
    "raw",  # 加密 vision zip 太大；export 默认排除
}


def _should_include(path: Path) -> bool:
    return not any(part in _EXCLUDE_NAMES for part in path.parts)


def iter_export_files(data_root: Path, includes: Iterable[str] = _DEFAULT_INCLUDES) -> Iterator[tuple[Path, str]]:
    """yield (绝对路径, tar 内 arcname)。"""

    data_root = data_root.resolve()
    for top in includes:
        base = data_root / top
        if not base.exists():
            continue
        if base.is_file():
            if _should_include(base):
                yield base, str(base.relative_to(data_root.parent))
            continue
        for path in base.rglob("*"):
            if path.is_file() and _should_include(path):
                arcname = str(path.relative_to(data_root.parent))
                yield path, arcname


def export_tar_gz_stream(
    data_root: Path,
    *,
    includes: Iterable[str] = _DEFAULT_INCLUDES,
    chunk_size: int = 1024 * 256,
) -> Iterator[bytes]:
    """流式生成 tar.gz；适合 FastAPI StreamingResponse。"""

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        manifest_lines: list[str] = [f"# QuantBT export at {datetime.now(UTC).isoformat()}"]
        for path, arcname in iter_export_files(data_root, includes):
            try:
                tar.add(path, arcname=arcname, recursive=False)
                manifest_lines.append(f"{path.stat().st_size}\t{arcname}")
            except Exception as exc:  # noqa: BLE001
                manifest_lines.append(f"# SKIP {arcname}: {exc}")
        manifest = "\n".join(manifest_lines).encode("utf-8")
        info = tarfile.TarInfo("MANIFEST.txt")
        info.size = len(manifest)
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, io.BytesIO(manifest))
    buf.seek(0)
    while True:
        chunk = buf.read(chunk_size)
        if not chunk:
            return
        yield chunk


def estimate_export_size(data_root: Path, includes: Iterable[str] = _DEFAULT_INCLUDES) -> dict[str, int]:
    """给 UI 显示"export 会有多大"的预估。"""

    total = 0
    file_count = 0
    by_section: dict[str, int] = {}
    for path, arcname in iter_export_files(data_root, includes):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total += size
        file_count += 1
        section = arcname.split(os.sep)[1] if os.sep in arcname else "root"
        by_section[section] = by_section.get(section, 0) + size
    return {"total_bytes": total, "file_count": file_count, "by_section": by_section}


__all__ = ["estimate_export_size", "export_tar_gz_stream", "iter_export_files"]
