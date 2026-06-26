"""Document Intelligence 摄入安全栈 —— 对象 + 内容寻址金库 + 编排（GOAL §6·安全优先第一切片）。

GOAL §6「文档内容作为 untrusted data 进入系统」。本模块把 §6 的 Source intake 安全门串成
fail-closed 流水线，按 §6 给定顺序：

    raw vault → quarantine → parser sandbox（mime/magic · URL allowlist · size/page/compression
    limits · no network parser · source hash · license/rights record）

切片边界（先安全后抽取·TASK 非目标）：本卡只立摄入安全边界 + SourceDocument/DocumentVersion +
source hash + license record；EvidenceSpan / DocumentBlock / TableArtifact / ExtractedStrategySpec
等结构化抽取 = 明确标注的 follow-on。

身份哈希纪律（对齐 `training/artifact_trust.py` + 单一身份源红线）：
  - `content_sha256` = 文档字节的完整 256-bit sha256 = 内容地址 / 完整性键 / §6「source hash」
    （tamper-evident，改一字节即变）。
  - `source_id` / `doc_version_id` / `content_id` = 复用 `lineage.ids.content_hash`（16 位·单一
    身份源·展示与索引用），绝不另造哈希族。安全绑定永远用完整 sha256，不用 16 位截断。
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 单一身份源红线：复用 ids.content_hash / HASH_LEN，绝不另造哈希族（与 artifact_trust 同纪律）。
from ..lineage.ids import HASH_LEN, content_hash
from .safety import (
    MAGIC_HEAD_BYTES,
    DocumentIntakeError,
    IntakeLimits,
    assert_mime_matches_extension,
    assert_url_allowed,
    check_size,
    inspect_archive_safety,
)
from .sandbox import OfflineDocumentParser, ParsedDocument, SafeDocumentParser

# ── 落盘常量 ──────────────────────────────────────────────────────────────────
_DOC_SCHEMA = "document-intake-v1"
RAW_VAULT_DIRNAME = "raw"            # 内容寻址原件库（不可变·记录「到底来了什么」·审计）
QUARANTINE_DIRNAME = "quarantine"    # 隔离区（外来文档先落此·绝不直接信任·解析只读这里）
REGISTRY_FILENAME = "documents.jsonl"  # append-only 版本登记（prev_hash 链·过门后才入账）
VAULT_STORE_DIRNAME = "_documents"   # data_root 下的金库子目录约定（对齐 artifact_trust 落点约定）
GENESIS_HASH = "0" * HASH_LEN        # prev_hash 链创世（与全库 HASH_LEN 对齐）


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ══ 对象模型（GOAL §6 Document Intelligence Plane 第一切片） ═══════════════════
@dataclass(frozen=True)
class LicenseRecord:
    """license / rights record（验收 #5：合规可追溯·必须在场）。

    `license` 非空是硬要求 —— 不知道也要【显式】填 "unknown"（可审计的刻意选择），绝不静默
    伪造许可。rights_holder / source_url / retrieved_at 补全溯源链。
    """

    license: str                       # 例 "CC-BY-4.0" / "arXiv-nonexclusive" / "unknown"（须显式）
    rights_holder: str = "unknown"
    source_url: str = ""
    retrieved_at_utc: str = ""
    attribution: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not (self.license or "").strip():
            raise DocumentIntakeError(
                "摄入安全门#5（license/rights）：LicenseRecord.license 为空 → 拒。"
                "许可未知也须显式填 'unknown'（可审计），绝不静默伪造 / 留空（合规红线）。"
            )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceDocument:
    """一个逻辑来源（一篇论文 / 文章）。`source_hash` = 其规范（首）版本字节的完整 sha256。"""

    source_id: str          # ids.content_hash（16 位·单一身份源）
    source_hash: str        # 完整 256-bit sha256（首版字节·内容地址）
    title: str
    origin: str             # URL 或本地路径标签（溯源）
    license: LicenseRecord
    created_at_utc: str = field(default_factory=_now)

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["license"] = self.license.to_payload()
        return d


@dataclass(frozen=True)
class DocumentVersion:
    """一个来源的具体版本（过完摄入安全门、入账的那份）。"""

    doc_version_id: str     # ids.content_hash（16 位）
    source_id: str
    content_sha256: str     # 完整 256-bit sha256（本版字节·= source hash·安全绑定键）
    content_id: str         # ids.content_hash（16 位·展示 / 索引）
    filename: str
    declared_format: str    # 嗅探校验后的真实格式（非仅凭扩展名）
    n_bytes: int
    n_pages: int
    parser_name: str
    license: LicenseRecord
    raw_vault_path: str
    quarantine_path: str
    created_at_utc: str = field(default_factory=_now)

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["license"] = self.license.to_payload()
        return d


@dataclass(frozen=True)
class IntakePolicy:
    """摄入策略：限额 + URL allowlist（默认空 = 任何 URL 来源都拒，白名单制）。"""

    limits: IntakeLimits = field(default_factory=IntakeLimits)
    url_allowlist: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class IntakeResult:
    """摄入成功产物：来源 + 版本 + 沙箱解析结果 + 隔离 / 原件库路径（供审计 / 测试断言隔离真生效）。"""

    source: SourceDocument
    version: DocumentVersion
    parsed: ParsedDocument
    raw_vault_path: str
    quarantine_path: str


# ══ 版本登记账：append-only JSONL + prev_hash 链（mirror ArtifactTrustStore·tamper-evident） ══
class DocumentRegistry:
    """过门后的 DocumentVersion 登记（append-only·prev_hash 链防事后篡改·内容寻址）。

    复用 artifact_trust 同款链式设计（`ids.content_hash` 算行指纹·GENESIS·容忍末尾坏行），
    但这是【文档】侧独立账，绝不与 honest-N Ledger / artifact 信任账混账。
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()
        self._next_seq, self._last_hash = self._scan_tail()

    def _read_records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 容忍崩溃中途写坏的（通常末尾）行，不让一行炸全账
        return out

    def _scan_tail(self) -> tuple[int, str]:
        last_hash, next_seq = GENESIS_HASH, 0
        for rec in self._read_records():
            last_hash, next_seq = rec["row_hash"], rec["seq"] + 1
        return next_seq, last_hash

    @staticmethod
    def _row_hash(seq: int, prev_hash: str, record: dict[str, Any]) -> str:
        return content_hash({"seq": seq, "prev_hash": prev_hash, "record": record})

    def register(self, version: DocumentVersion) -> DocumentVersion:
        """把【过完摄入安全门】的版本入账（append-only）。"""
        payload = version.to_payload()
        with self._lock:
            seq = self._next_seq
            prev = self._last_hash
            row_hash = self._row_hash(seq, prev, payload)
            line = {"seq": seq, "prev_hash": prev, "row_hash": row_hash, "record": payload}
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()
            self._next_seq, self._last_hash = seq + 1, row_hash
        return version

    def list_versions(self) -> list[dict[str, Any]]:
        return [rec["record"] for rec in self._read_records()]

    def find_by_content_sha256(self, content_sha256: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for rec in self._read_records():
            r = rec.get("record")
            if isinstance(r, dict) and r.get("content_sha256") == content_sha256:
                latest = r
        return latest

    def verify_chain(self) -> tuple[bool, list[str]]:
        """重算 prev_hash 链，检出对登记文件的事后篡改 / 链断。返回 (intact, issues)。"""
        issues: list[str] = []
        prev, expect_seq = GENESIS_HASH, 0
        for rec in self._read_records():
            if rec.get("seq") != expect_seq:
                issues.append(f"seq 跳号：期望 {expect_seq} 实得 {rec.get('seq')}")
                return False, issues
            if rec.get("prev_hash") != prev:
                issues.append(f"seq={rec.get('seq')} prev_hash 断裂")
                return False, issues
            if self._row_hash(rec["seq"], rec["prev_hash"], rec["record"]) != rec.get("row_hash"):
                issues.append(f"seq={rec['seq']} row_hash 与内容不符 → 检出该行被篡改")
                return False, issues
            prev, expect_seq = rec["row_hash"], expect_seq + 1
        return True, issues


# ══ 金库：raw vault + quarantine + registry ════════════════════════════════════
class DocumentVault:
    """内容寻址文档金库：`raw/`（不可变原件·审计）+ `quarantine/`（隔离区·解析只读此）+ 登记账。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._raw = self._root / RAW_VAULT_DIRNAME
        self._quarantine = self._root / QUARANTINE_DIRNAME
        self._raw.mkdir(parents=True, exist_ok=True)
        self._quarantine.mkdir(parents=True, exist_ok=True)
        self.registry = DocumentRegistry(self._root / REGISTRY_FILENAME)

    @property
    def raw_dir(self) -> Path:
        return self._raw

    @property
    def quarantine_dir(self) -> Path:
        return self._quarantine

    def store_raw(self, data: bytes, content_sha256: str) -> Path:
        """把原件按 sha256 内容寻址落进 raw vault（分片目录避免单目录爆量·不可变·幂等）。"""
        shard = self._raw / content_sha256[:2]
        shard.mkdir(parents=True, exist_ok=True)
        dest = shard / content_sha256
        if not dest.exists():  # 内容寻址 → 同内容只存一份（幂等）
            dest.write_bytes(data)
        return dest

    def stage_quarantine(self, data: bytes, content_sha256: str, suffix: str) -> Path:
        """把外来字节落进隔离区（绝不直接信任原件路径·后续解析只读这里）。返回隔离区路径。"""
        safe_suffix = suffix if suffix and len(suffix) <= 16 else ""
        dest = self._quarantine / f"{content_sha256}{safe_suffix}"
        dest.write_bytes(data)
        return dest


def vault_under(data_root: str | Path) -> DocumentVault:
    """解析 `<data_root>/_documents/` 文档金库（落点约定·对齐 artifact_trust.store_under 风格）。"""
    return DocumentVault(Path(data_root) / VAULT_STORE_DIRNAME)


# ══ 编排：fail-closed 摄入流水线（每道门违即 raise·绝不静默放行） ═══════════════
def _looks_like_url(origin: str) -> bool:
    o = (origin or "").strip().lower()
    return o.startswith(("http://", "https://")) or "://" in o


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def intake_document(
    *,
    vault: DocumentVault,
    filename: str,
    license: LicenseRecord,
    data: bytes | None = None,
    path: str | Path | None = None,
    origin: str = "",
    title: str = "",
    policy: IntakePolicy | None = None,
    parser: OfflineDocumentParser | None = None,
) -> IntakeResult:
    """把一份外来文档过完整摄入安全门后入金库。任一门不过 → `DocumentIntakeError`（fail-closed）。

    顺序严格对齐 GOAL §6（raw vault → quarantine → sandbox）：
      0. 入参校验（filename / 二选一 data|path / license 在场）。
      1. URL 门（origin 是 URL 时）：scheme / 私网 / allowlist（防 SSRF·验收 #2）。
      2. size 门（超 max_bytes 拒·先于落盘·防超大文件 DoS·验收 #3）。
      3. raw vault：原件按 sha256 内容寻址落盘（审计「来了什么」·= source hash·验收 #5）。
      4. quarantine：外来字节落隔离区，【后续只读隔离副本】（绝不信任原件路径·验收 #4）。
      5. mime/magic 门：嗅探真实格式 vs 扩展名（防伪装·验收 #1）。
      6. archive 门：zip/OOXML 容器查解压比 / 条目 / 解压量（防 zip bomb·验收 #3）。
      7. license 门：rights record 在场（验收 #5）。
      8. sandbox 解析：no-network 内解析 + 页数限额（防外联 / 页炸弹·验收 #2/#3）。
      9. 入账：DocumentVersion 进 append-only registry（过门后才信任·provenance）。
    """
    policy = policy or IntakePolicy()
    limits = policy.limits

    # —— 0. 入参校验 ——
    if not (filename or "").strip():
        raise DocumentIntakeError("摄入：filename 不可为空（需扩展名做 mime 校验）。")
    if (data is None) == (path is None):
        raise DocumentIntakeError("摄入：data 与 path 必须【二选一】提供（不可都给 / 都不给）。")
    if not isinstance(license, LicenseRecord):  # license 在场（验收 #5·结构上前置）
        raise DocumentIntakeError("摄入安全门#5（license/rights）：必须提供 LicenseRecord → 拒。")

    # —— 1. URL 门（origin 是 URL）：防 SSRF / 外联 ——
    if _looks_like_url(origin):
        assert_url_allowed(origin, allowlist=policy.url_allowlist)

    # —— 2. size 门：先于落盘拒超大（path 走 stat 预检，绝不先把 DoS 文件读进内存）——
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise DocumentIntakeError(f"摄入：path 不是文件：{p}")
        check_size(p.stat().st_size, limits)  # 预检（防超大文件读爆内存）
        data = p.read_bytes()
    assert data is not None
    check_size(len(data), limits)

    # —— 3. raw vault：内容寻址落原件（审计·source hash）——
    content_sha256 = _sha256_hex(data)
    raw_path = vault.store_raw(data, content_sha256)

    # —— 4. quarantine：落隔离区，后续【只读隔离副本】（绝不信任原件路径）——
    suffix = Path(filename).suffix.lower()
    quarantine_path = vault.stage_quarantine(data, content_sha256, suffix)
    untrusted_bytes = quarantine_path.read_bytes()  # 隔离副本 = 后续所有不可信处理的唯一来源

    # —— 5. mime/magic 门：防伪装扩展名 ——
    sniffed_format = assert_mime_matches_extension(
        filename=filename, head=untrusted_bytes[:MAGIC_HEAD_BYTES]
    )

    # —— 6. archive 门：防 zip bomb ——
    inspect_archive_safety(untrusted_bytes, limits)

    # —— 7. license 门：rights record 在场（__post_init__ 已挡空 license；此处复述语义）——
    #    （license 为 LicenseRecord 实例已在步 0 校验；构造时即拒空许可。）

    # —— 8. sandbox 解析：no-network + 页数限额（解析只读隔离副本·凭据无处可入）——
    safe_parser = SafeDocumentParser(parser, limits=limits)
    parsed = safe_parser.parse(untrusted_bytes, declared_format=sniffed_format)

    # —— 9. 入账：过门后才信任，DocumentVersion 进 append-only registry ——
    source_id = content_hash({"schema": _DOC_SCHEMA, "origin": origin, "content_sha256": content_sha256})
    content_id = content_hash({"schema": _DOC_SCHEMA, "content_sha256": content_sha256})
    doc_version_id = content_hash(
        {"schema": _DOC_SCHEMA, "source_id": source_id, "content_sha256": content_sha256}
    )
    source = SourceDocument(
        source_id=source_id,
        source_hash=content_sha256,
        title=title or filename,
        origin=origin,
        license=license,
    )
    version = DocumentVersion(
        doc_version_id=doc_version_id,
        source_id=source_id,
        content_sha256=content_sha256,
        content_id=content_id,
        filename=filename,
        declared_format=sniffed_format,
        n_bytes=len(untrusted_bytes),
        n_pages=parsed.n_pages,
        parser_name=parsed.parser_name,
        license=license,
        raw_vault_path=str(raw_path),
        quarantine_path=str(quarantine_path),
    )
    vault.registry.register(version)

    return IntakeResult(
        source=source,
        version=version,
        parsed=parsed,
        raw_vault_path=str(raw_path),
        quarantine_path=str(quarantine_path),
    )


__all__ = [
    "QUARANTINE_DIRNAME",
    "RAW_VAULT_DIRNAME",
    "REGISTRY_FILENAME",
    "VAULT_STORE_DIRNAME",
    "DocumentIntakeError",
    "DocumentRegistry",
    "DocumentVault",
    "DocumentVersion",
    "IntakePolicy",
    "IntakeResult",
    "LicenseRecord",
    "SourceDocument",
    "intake_document",
    "vault_under",
]
