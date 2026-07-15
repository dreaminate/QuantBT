"""v0.9.7 学术 audit (patch1 §G.a #6, #7) · dataset_version 内容不可变 + FactorRegistry 绑 dataset。

学术依据: López de Prado 2018 §1 "Same dataset_version + same code → same result"

漏洞 #7: dataset_version 命名不可变但内容可被外部覆盖 (重跑 connector 同 version_id)，
         无法在事后 audit "我跑的 run 用的 dataset 是不是真的没变"。
漏洞 #6: FactorRegistry 只用 factor_id 主键，同 expression 在两个 dataset 上计算
         结果完全不同但 registry 看不出。

修复:
- DatasetManifest 加 SHA-256 hash per file
- create_version() 算每文件 hash 落 manifest
- verify_version() 重算 hash vs manifest，不匹配 raise
- FactorBinding (factor_id, dataset_id, dataset_version) 三元组主键
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class DatasetIntegrityError(Exception):
    """dataset_version 内容被外部修改 → 任何复现都不可信。"""


@dataclass
class FileEntry:
    relative_path: str
    sha256: str
    size_bytes: int
    row_count: int | None = None


@dataclass
class DatasetManifest:
    dataset_id: str
    version: str
    files: list[FileEntry] = field(default_factory=list)
    created_at_utc: str = ""
    total_size_bytes: int = 0
    total_row_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "files": [asdict(f) for f in self.files],
            "created_at_utc": self.created_at_utc,
            "total_size_bytes": self.total_size_bytes,
            "total_row_count": self.total_row_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetManifest":
        files = [FileEntry(**f) for f in (data.get("files") or [])]
        return cls(
            dataset_id=data["dataset_id"],
            version=data["version"],
            files=files,
            created_at_utc=data.get("created_at_utc", ""),
            total_size_bytes=data.get("total_size_bytes", 0),
            total_row_count=data.get("total_row_count"),
        )


def _sha256_file(path: Path, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _count_rows_safe(path: Path) -> int | None:
    """轻量 row count: parquet 用 metadata，csv 数行。失败返 None。"""
    try:
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq
            return int(pq.read_metadata(str(path)).num_rows)
        if path.suffix in (".csv", ".tsv"):
            with path.open("rb") as f:
                return sum(1 for _ in f) - 1  # 减表头
    except Exception:  # noqa: BLE001
        return None
    return None


def create_manifest(
    dataset_id: str,
    version: str,
    root_dir: Path,
    *,
    glob_pattern: str = "*",
    recursive: bool = True,
    created_at_utc: str = "",
) -> DatasetManifest:
    """扫 root_dir 下匹配 glob 的文件，算 sha256 + 写 manifest。"""
    if not root_dir.exists():
        raise FileNotFoundError(f"root_dir 不存在: {root_dir}")
    pattern = "**/" + glob_pattern if recursive else glob_pattern
    files = sorted(root_dir.glob(pattern))  # 按 path 排序保证 hash 顺序无关
    entries: list[FileEntry] = []
    total_bytes = 0
    total_rows = 0
    has_rows = False
    for f in files:
        if not f.is_file():
            continue
        rel = f.relative_to(root_dir).as_posix()
        size = f.stat().st_size
        sha = _sha256_file(f)
        rows = _count_rows_safe(f)
        if rows is not None:
            has_rows = True
            total_rows += rows
        entries.append(FileEntry(relative_path=rel, sha256=sha, size_bytes=size, row_count=rows))
        total_bytes += size
    return DatasetManifest(
        dataset_id=dataset_id,
        version=version,
        files=entries,
        created_at_utc=created_at_utc,
        total_size_bytes=total_bytes,
        total_row_count=total_rows if has_rows else None,
    )


def write_manifest(manifest: DatasetManifest, manifest_path: Path) -> None:
    """落 manifest.json 到磁盘 (v0.9.7 防覆盖：同 version 已存在但 hash 不同 → raise)。"""
    if manifest_path.exists():
        try:
            old_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            old = DatasetManifest.from_dict(old_data)
        except Exception as exc:  # noqa: BLE001
            raise DatasetIntegrityError(f"现有 manifest 解析失败: {exc}") from exc
        if old.dataset_id == manifest.dataset_id and old.version == manifest.version:
            # 同 (dataset_id, version) → 新 files 必须 hash 完全匹配
            old_hashes = {f.relative_path: f.sha256 for f in old.files}
            for f in manifest.files:
                if f.relative_path in old_hashes and old_hashes[f.relative_path] != f.sha256:
                    raise DatasetIntegrityError(
                        f"dataset_id={manifest.dataset_id} version={manifest.version} "
                        f"已存在但 {f.relative_path} sha256 不一致 "
                        f"(old={old_hashes[f.relative_path][:8]}.. new={f.sha256[:8]}..)"
                        f"。 dataset_version 内容必须不可变 "
                        f"(López de Prado 2018 §1) - 要更新数据请创建新 version。"
                    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def verify_manifest_obj(manifest: DatasetManifest, root_dir: Path) -> tuple[bool, list[str]]:
    """对【已解析】的 ``DatasetManifest`` 对象逐条重算磁盘文件 hash vs 记录，不匹配返 mismatch 列表。

    单快照约定：调用方把 manifest 只解析【一次】，再把【同一】对象同时喂给覆盖/路径门与本 per-file
    sha256 门 → 两门之间不再有「二次读盘 manifest」的窗口。这正是 split-snapshot 攻击的解药：覆盖门
    读快照 A、哈希门重开读快照 B，中途 swap manifest 让被删 entry 的篡改文件既过覆盖又逃哈希 —— 单快照
    下无从下手（见 ``factor_factory.panel_source._verify_real_manifest``）。哈希单源 ``_sha256_file``。
    """
    mismatches: list[str] = []
    for entry in manifest.files:
        f = root_dir / entry.relative_path
        if not f.exists():
            mismatches.append(f"{entry.relative_path}: 文件丢失")
            continue
        actual_sha = _sha256_file(f)
        if actual_sha != entry.sha256:
            mismatches.append(
                f"{entry.relative_path}: sha256 mismatch "
                f"(manifest={entry.sha256[:8]}.. actual={actual_sha[:8]}..)"
            )
    return len(mismatches) == 0, mismatches


def verify_manifest(manifest_path: Path, root_dir: Path) -> tuple[bool, list[str]]:
    """重算磁盘文件 hash vs manifest 记录，不匹配返 mismatch 列表。

    = 读盘+解析 manifest 一次 → 委托 ``verify_manifest_obj``（既有签名/行为逐字节保留，现有 caller 无感）。
    需要「覆盖门 + 哈希门共用同一次读盘快照」的调用方（如 F3 读侧 ``panel_source._verify_real_manifest``）
    应自行把 manifest 解析一次再直接调 ``verify_manifest_obj``，绝不经本函数二次读盘（防 split-snapshot）。
    """
    if not manifest_path.exists():
        return False, ["manifest.json 不存在"]
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = DatasetManifest.from_dict(data)
    except Exception as exc:  # noqa: BLE001
        return False, [f"manifest 解析失败: {exc}"]
    return verify_manifest_obj(manifest, root_dir)


# ============================================================
# FactorBinding (patch1 §G.a #6)
# ============================================================


@dataclass(frozen=True)
class FactorBinding:
    """同一 factor expression 在不同 dataset 上算出来是不同的因子。

    Registry 必须用 (factor_id, dataset_id, dataset_version) 三元组主键，
    不能只用 factor_id。
    """

    factor_id: str
    expression: str
    dataset_id: str
    dataset_version: str
    universe_snapshot_id: str | None = None

    @property
    def composite_key(self) -> str:
        u = self.universe_snapshot_id or "all"
        return f"{self.factor_id}::{self.dataset_id}::{self.dataset_version}::{u}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "DatasetIntegrityError",
    "DatasetManifest",
    "FactorBinding",
    "FileEntry",
    "create_manifest",
    "verify_manifest",
    "verify_manifest_obj",
    "write_manifest",
]
