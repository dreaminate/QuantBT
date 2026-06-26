"""Document Intelligence 抽取层 —— 解析产物 typed + EvidenceSpan + ExtractionRun + 抽取声明（GOAL §6 续）。

摄入安全栈（`safety` / `intake` / `sandbox`）已立 raw vault → quarantine → no-network 沙箱 +
`OfflineDocumentParser` 抽象 + stub。本模块接 §6【抽取层】，建在 stub 抽象上（真 PDF / OOXML
解析库 = 用户选型，抽取逻辑 + EvidenceSpan 结构【独立于真解析器】）：

  - 解析产物 typed：`DocumentBlock` / `TableArtifact` / `FormulaArtifact` / `ReferenceArtifact`
    （从沙箱解析器输出结构化；位置 page/bbox/section/char_span 可追溯）。
  - `EvidenceSpan`：抽取片段 → source doc / version / parser run / block / 位置 的可追溯证据跨度。
    晋级资产引 `evidence_ref`。缺任一追溯键即【拒】（孤儿 EvidenceSpan 必拒）。
  - span-support 验证：把 reader（untrusted）声称的引文【对回源 block 复算哈希】——引文不在所称
    位置即 `challenged`，不进 confirmatory（GOAL §6「span 未过 span-support verification → challenged」）。
  - `ExtractionRun`：抽取一次落账（append-only 哈希链·内容寻址 run_id·可 replay）。
  - `ExtractedStrategySpec` / `ExtractedModelClaim`：抽取出的策略 / 模型声明，硬标【抽取自文档·
    未验证残余】（抽取 ≠ 已验证·不假绿灯；不得展示为 proof-backed / evidence-sufficient / production-ready）。

安全 / 复用纪律（扩展不替换·不绕安全门）：
  - 抽取【全程经沙箱】：block 抽取在 `safety.no_network()` 内跑 + 过 `check_pages` 限额门（复用，
    不改安全门）——解析器 / 抽取器任何联网尝试 → `DocumentIntakeError`（no-network 红线）。
  - 单一身份源：`span_id` / `block_id` / `run_id` 等一律 `lineage.ids.content_hash`（16 位），绝不
    另造哈希族；安全绑定仍用上游完整 `content_sha256`。
  - `ExtractionRun` 落账走【本模块自有】append-only 哈希链账（mirror `intake.DocumentRegistry`），
    刻意【不】混进 honest-N `lineage.ledger.Ledger`（那是试验计数账，kind 不含 extraction，混账会
    虚高 honest-N）——与 intake「文档侧独立账·绝不与 honest-N 混账」同纪律。

诚实边界：本层只产【抽取自文档·未验证】产物。是否进 confirmatory 取决于 span-support 验证 +
下游验证 dossier（非本层职责）。`FormulaArtifact` 只是「文档里出现了公式」的原样记录，【不是】
经数学验证的 `MathematicalArtifact`（无新公式 → 不强造数学产物）。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

# 单一身份源红线：复用 ids.content_hash / canonical_json / HASH_LEN，绝不另造哈希族。
from ..lineage.ids import HASH_LEN, canonical_json, content_hash
# 复用安全门（只复用·不改）：no-network 沙箱 + 页数限额 + 限额配置 + 统一异常基类。
from .safety import DocumentIntakeError, IntakeLimits, check_pages, no_network
from .sandbox import OfflineDocumentParser, ParsedDocument, StubOfflineParser

# ── 常量 ──────────────────────────────────────────────────────────────────────
EXTRACTION_SCHEMA = "document-extraction-v1"
GENESIS_HASH = "0" * HASH_LEN
EXTRACTION_REGISTRY_FILENAME = "extraction_runs.jsonl"  # ExtractionRun append-only 哈希链账

# 抽取声明的【唯一】合法验证态（本层永远只产「未验证」——晋级是下游的事，本层不发绿灯）。
EXTRACTED_UNVERIFIED = "extracted_unverified"
# 诚实免责（硬标在每个抽取声明上）。守门测试断言其在场 + 含「未验证」marker。
EXTRACTED_DISCLOSURE = (
    "抽取自文档·未验证残余：本声明仅由文档抽取得到，未经任何假设检验 / 复现 / 回测 / 数学验证。"
    "不得展示为 proof-backed / evidence-sufficient / production-ready；进入 confirmatory 前须通过 "
    "span-support 验证与下游验证 dossier（非本抽取层职责）。"
)

# block 类型白名单（解析产物结构化口径）。
BlockType = Literal[
    "heading", "paragraph", "table", "formula", "reference", "caption", "list", "other"
]
ALLOWED_BLOCK_TYPES: frozenset[str] = frozenset(
    {"heading", "paragraph", "table", "formula", "reference", "caption", "list", "other"}
)

# span-support 验证态。GOAL §6：未过验证 → challenged，不进 confirmatory。
SpanStatus = Literal["unverified", "supported", "challenged", "refuted"]
ALLOWED_SPAN_STATUSES: frozenset[str] = frozenset(
    {"unverified", "supported", "challenged", "refuted"}
)


class DocumentExtractionError(DocumentIntakeError):
    """抽取层校验失败：孤儿 EvidenceSpan（缺追溯）/ 抽取声明缺证据或未标未验证 / 抽取器越安全门 等。

    继承 `DocumentIntakeError`（扩展不替换）——既有 `except DocumentIntakeError` 调用方仍能捕获，
    又让本层测试可断言更具体的子类。fail-closed：过不了校验即【显式 raise·绝不静默放行】。
    """


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _nonempty(value: str | None, *, field_name: str, ctx: str) -> str:
    if not (value or "").strip():
        raise DocumentExtractionError(
            f"{ctx}：追溯键 {field_name} 为空 → 拒（孤儿产物不可追溯·抽取≠已验证）。"
        )
    return value  # type: ignore[return-value]


# ══ 位置（page / bbox / section / char_span·至少一个定位器在场） ═══════════════════
@dataclass(frozen=True)
class BlockPosition:
    """抽取片段在源文档中的位置（GOAL §6 EvidenceSpan：page / bbox / section / char_span）。

    至少一个定位器必须在场（否则无法追溯回原文位置 → 孤儿）。`char_span` = `[start, end)` 字符偏移
    （半开区间），是 span-support 复算的锚点（精确、可机器复核）。

    char_span 的【两级寻址】口径（关键·避免误用）：
      - `DocumentBlock.position.char_span` = 块在【规范化文档全文】里的偏移（doc-relative）。
      - `EvidenceSpan.position.char_span`   = 引文在【其 block.text 内】的偏移（block-relative；整块 =
        `(0, len(block.text))`）。这样 span-support 复算【只需该 block】即可机器复核（本地、tamper-evident）；
        要还原文档级偏移 = `block.position.char_span[0] + span.position.char_span[0]`。用 `EvidenceSpan.from_block`
        构造可免手算（杜绝把 doc-relative 偏移误当 block-relative 的脚枪）。
    """

    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    section: str = ""
    char_span: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.page is not None and self.page < 0:
            raise DocumentExtractionError(f"BlockPosition.page={self.page} < 0 → 拒。")
        if self.bbox is not None and len(self.bbox) != 4:
            raise DocumentExtractionError(f"BlockPosition.bbox 须 4 元组，得 {self.bbox!r} → 拒。")
        if self.char_span is not None:
            if len(self.char_span) != 2:
                raise DocumentExtractionError(
                    f"BlockPosition.char_span 须 (start, end)，得 {self.char_span!r} → 拒。"
                )
            start, end = self.char_span
            if not (isinstance(start, int) and isinstance(end, int)) or start < 0 or end < start:
                raise DocumentExtractionError(
                    f"BlockPosition.char_span={self.char_span!r} 非法（须 0<=start<=end 整数）→ 拒。"
                )
        if not self.has_locator:
            raise DocumentExtractionError(
                "BlockPosition 无任何定位器（page / bbox / section / char_span 全缺）→ 拒"
                "（抽取片段必须可追溯回原文位置·孤儿即拒）。"
            )

    @property
    def has_locator(self) -> bool:
        return (
            self.page is not None
            or self.bbox is not None
            or bool((self.section or "").strip())
            or self.char_span is not None
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "section": self.section,
            "char_span": list(self.char_span) if self.char_span is not None else None,
        }


# ══ 解析产物（从沙箱解析器输出·typed·content-addressed） ═══════════════════════════
@dataclass(frozen=True)
class RawBlock:
    """解析器原样输出的一块（pre-typed）：类型 + 文本 + 位置。由沙箱抽取器产，绝不直接信任。"""

    block_type: BlockType
    text: str
    position: BlockPosition

    def __post_init__(self) -> None:
        if self.block_type not in ALLOWED_BLOCK_TYPES:
            raise DocumentExtractionError(
                f"RawBlock.block_type={self.block_type!r} 不在 {sorted(ALLOWED_BLOCK_TYPES)} → 拒。"
            )


@dataclass(frozen=True)
class DocumentBlock:
    """一块结构化解析产物（GOAL §6 DocumentBlock）。`block_id` 内容寻址·绑定 doc/version/parser run。

    `text_hash` = 块文本的内容指纹（tamper-evident·EvidenceSpan 复算锚点之一）。
    """

    block_id: str           # content_hash（绑 doc_version_id + parser_run_id + 位置 + 文本）
    source_id: str
    doc_version_id: str
    parser_run_id: str
    block_type: BlockType
    position: BlockPosition
    text: str
    text_hash: str          # content_hash(text)

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        doc_version_id: str,
        parser_run_id: str,
        raw: RawBlock,
    ) -> "DocumentBlock":
        _nonempty(source_id, field_name="source_id", ctx="DocumentBlock")
        _nonempty(doc_version_id, field_name="doc_version_id", ctx="DocumentBlock")
        _nonempty(parser_run_id, field_name="parser_run_id", ctx="DocumentBlock")
        text_hash = content_hash(raw.text)
        block_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "block",
                "doc_version_id": doc_version_id,
                "parser_run_id": parser_run_id,
                "block_type": raw.block_type,
                "position": raw.position.to_payload(),
                "text_hash": text_hash,
            }
        )
        return cls(
            block_id=block_id,
            source_id=source_id,
            doc_version_id=doc_version_id,
            parser_run_id=parser_run_id,
            block_type=raw.block_type,
            position=raw.position,
            text=raw.text,
            text_hash=text_hash,
        )

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["position"] = self.position.to_payload()
        return d


@dataclass(frozen=True)
class TableArtifact:
    """表格解析产物（GOAL §6 TableArtifact）。`rows` = 行→单元格的二维原样文本（结构保真·非语义）。"""

    artifact_id: str
    block_id: str
    source_id: str
    doc_version_id: str
    parser_run_id: str
    n_rows: int
    n_cols: int
    rows: tuple[tuple[str, ...], ...]
    position: BlockPosition
    caption: str = ""

    @classmethod
    def create(
        cls,
        *,
        block: DocumentBlock,
        rows: Sequence[Sequence[str]],
        caption: str = "",
    ) -> "TableArtifact":
        norm = tuple(tuple(str(c) for c in row) for row in rows)
        n_rows = len(norm)
        n_cols = max((len(r) for r in norm), default=0)
        artifact_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "table",
                "block_id": block.block_id,
                "rows": [list(r) for r in norm],
                "caption": caption,
            }
        )
        return cls(
            artifact_id=artifact_id,
            block_id=block.block_id,
            source_id=block.source_id,
            doc_version_id=block.doc_version_id,
            parser_run_id=block.parser_run_id,
            n_rows=n_rows,
            n_cols=n_cols,
            rows=norm,
            position=block.position,
            caption=caption,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "block_id": self.block_id,
            "source_id": self.source_id,
            "doc_version_id": self.doc_version_id,
            "parser_run_id": self.parser_run_id,
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "rows": [list(r) for r in self.rows],
            "position": self.position.to_payload(),
            "caption": self.caption,
        }


@dataclass(frozen=True)
class FormulaArtifact:
    """公式解析产物（GOAL §6 FormulaArtifact）。

    诚实：这是「文档里【出现了】一个公式」的【原样】记录（representation = as-found 文本 / LaTeX），
    【不是】经数学验证的 `MathematicalArtifact`（无适用域 / 推导 / 反例 / 验证计划）。要把它升成
    数学产物须走 §6 Mathematical Research Layer（本层不强造·见模块 docstring）。
    """

    artifact_id: str
    block_id: str
    source_id: str
    doc_version_id: str
    parser_run_id: str
    representation: str         # as-found 公式文本 / LaTeX（原样·未经语义解析）
    position: BlockPosition
    note: str = (
        "抽取自文档的公式原样记录·未经数学验证：非 MathematicalArtifact（无适用域 / 推导 / 验证计划）。"
    )

    @classmethod
    def create(
        cls,
        *,
        block: DocumentBlock,
        representation: str,
    ) -> "FormulaArtifact":
        _nonempty(representation, field_name="representation", ctx="FormulaArtifact")
        artifact_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "formula",
                "block_id": block.block_id,
                "representation": representation,
            }
        )
        return cls(
            artifact_id=artifact_id,
            block_id=block.block_id,
            source_id=block.source_id,
            doc_version_id=block.doc_version_id,
            parser_run_id=block.parser_run_id,
            representation=representation,
            position=block.position,
        )

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["position"] = self.position.to_payload()
        return d


@dataclass(frozen=True)
class ReferenceArtifact:
    """文献引用解析产物（GOAL §6 ReferenceArtifact）。`raw_citation` = as-found 引用字符串（未解析）。"""

    artifact_id: str
    block_id: str
    source_id: str
    doc_version_id: str
    parser_run_id: str
    raw_citation: str
    position: BlockPosition

    @classmethod
    def create(
        cls,
        *,
        block: DocumentBlock,
        raw_citation: str,
    ) -> "ReferenceArtifact":
        _nonempty(raw_citation, field_name="raw_citation", ctx="ReferenceArtifact")
        artifact_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "reference",
                "block_id": block.block_id,
                "raw_citation": raw_citation,
            }
        )
        return cls(
            artifact_id=artifact_id,
            block_id=block.block_id,
            source_id=block.source_id,
            doc_version_id=block.doc_version_id,
            parser_run_id=block.parser_run_id,
            raw_citation=raw_citation,
            position=block.position,
        )

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["position"] = self.position.to_payload()
        return d


# ══ EvidenceSpan（可追溯证据跨度·孤儿即拒·span-support 复算可揪伪造） ═══════════════
@dataclass(frozen=True)
class SpanSupportVerification:
    """span-support 验证结果（GOAL §6 EvidenceSpan.span_support_verification）。

    `status`：unverified（未验）/ supported（引文复算命中源 block）/ challenged（不命中·疑伪造）/
    refuted（明确反证）。诚实措辞：说的是「引文是否复算命中所称位置」，不说「内容真实 / 可信」。
    """

    status: SpanStatus = "unverified"
    method: str = ""
    reason: str = ""
    verifier: str = ""
    checked_at_utc: str = ""

    def __post_init__(self) -> None:
        if self.status not in ALLOWED_SPAN_STATUSES:
            raise DocumentExtractionError(
                f"SpanSupportVerification.status={self.status!r} 不在 {sorted(ALLOWED_SPAN_STATUSES)} → 拒。"
            )

    @property
    def is_supported(self) -> bool:
        return self.status == "supported"

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceSpan:
    """抽取片段 → 源文档的可追溯证据跨度（GOAL §6·必含字段全在场）。

    GOAL §6 EvidenceSpan 必含：source_id / doc_version_id / parser_run_id / block_id /
    page·bbox·section·char_span（= `position`）/ quoted_excerpt_hash / parser_confidence /
    span_support_verification（= `support`）。任一追溯键缺失 → 孤儿 → 【拒】（验收 #1）。

    `span_id` 内容寻址，【刻意排除 `support`】——验证态可变（unverified→supported/challenged），但
    span 身份由【不可变定位 + 引文哈希】决定（验证前后是【同一条】span）。`quoted_excerpt_hash` =
    引文的内容指纹（tamper-evident）；`quoted_excerpt` 可选存（许可 / 隐私下可只留哈希）。
    """

    span_id: str
    source_id: str
    doc_version_id: str
    parser_run_id: str
    block_id: str
    position: BlockPosition
    quoted_excerpt_hash: str
    parser_confidence: float
    support: SpanSupportVerification = field(default_factory=SpanSupportVerification)
    quoted_excerpt: str = ""

    def __post_init__(self) -> None:
        # —— 追溯键硬校验（孤儿 EvidenceSpan 必拒·验收 #1）——
        _nonempty(self.source_id, field_name="source_id", ctx="EvidenceSpan")
        _nonempty(self.doc_version_id, field_name="doc_version_id", ctx="EvidenceSpan")
        _nonempty(self.parser_run_id, field_name="parser_run_id", ctx="EvidenceSpan")
        _nonempty(self.block_id, field_name="block_id", ctx="EvidenceSpan")
        _nonempty(self.quoted_excerpt_hash, field_name="quoted_excerpt_hash", ctx="EvidenceSpan")
        if not isinstance(self.position, BlockPosition) or not self.position.has_locator:
            raise DocumentExtractionError(
                "EvidenceSpan.position 无定位器（page/bbox/section/char_span 全缺）→ 拒"
                "（片段必须可追溯回原文位置·孤儿即拒）。"
            )
        if not (0.0 <= float(self.parser_confidence) <= 1.0):
            raise DocumentExtractionError(
                f"EvidenceSpan.parser_confidence={self.parser_confidence!r} 须 ∈ [0,1] → 拒。"
            )
        # —— 引文 / 哈希内部一致性（存了引文就必须与哈希自洽，杜绝「哈希对不上引文」）——
        if self.quoted_excerpt and content_hash(self.quoted_excerpt) != self.quoted_excerpt_hash:
            raise DocumentExtractionError(
                "EvidenceSpan.quoted_excerpt 与 quoted_excerpt_hash 不一致 → 拒（引文 / 哈希自相矛盾）。"
            )

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        doc_version_id: str,
        parser_run_id: str,
        block_id: str,
        position: BlockPosition,
        quoted_excerpt: str,
        parser_confidence: float,
        store_excerpt: bool = True,
    ) -> "EvidenceSpan":
        """从引文构造 span：算 `quoted_excerpt_hash`，content-address `span_id`（排除验证态）。

        `store_excerpt=False` → 只留哈希不留原文（许可 / 隐私场景；span-support 仍能对回源 block 复算）。
        """
        excerpt_hash = content_hash(quoted_excerpt)
        span_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "evidence_span",
                "source_id": source_id,
                "doc_version_id": doc_version_id,
                "parser_run_id": parser_run_id,
                "block_id": block_id,
                "position": position.to_payload(),
                "quoted_excerpt_hash": excerpt_hash,
                "parser_confidence": round(float(parser_confidence), 6),
            }
        )
        return cls(
            span_id=span_id,
            source_id=source_id,
            doc_version_id=doc_version_id,
            parser_run_id=parser_run_id,
            block_id=block_id,
            position=position,
            quoted_excerpt_hash=excerpt_hash,
            parser_confidence=float(parser_confidence),
            support=SpanSupportVerification(),
            quoted_excerpt=quoted_excerpt if store_excerpt else "",
        )

    @classmethod
    def from_block(
        cls,
        block: "DocumentBlock",
        *,
        start: int = 0,
        end: int | None = None,
        parser_confidence: float = 1.0,
        store_excerpt: bool = True,
    ) -> "EvidenceSpan":
        """从一个 `DocumentBlock` 的【block-relative】子区间构造 span（默认整块）——免手算·杜绝脚枪。

        引文 = `block.text[start:end]`；char_span = `(start, end)`（block-relative）；同时携 block 的
        page / section（doc 级粗定位）。这样建出的 span 必然能被 `verify_span_support` 在该 block 上复算命中
        （正路径不误伤）。追溯键（source/version/parser_run/block_id）全自 block 取，绝不留空。
        """
        text = block.text
        end_idx = len(text) if end is None else end
        if not (0 <= start <= end_idx <= len(text)):
            raise DocumentExtractionError(
                f"EvidenceSpan.from_block：子区间 [{start}:{end_idx}) 越界 block.text(len={len(text)}) → 拒。"
            )
        position = BlockPosition(
            char_span=(start, end_idx),
            page=block.position.page,
            section=block.position.section,
        )
        return cls.create(
            source_id=block.source_id,
            doc_version_id=block.doc_version_id,
            parser_run_id=block.parser_run_id,
            block_id=block.block_id,
            position=position,
            quoted_excerpt=text[start:end_idx],
            parser_confidence=parser_confidence,
            store_excerpt=store_excerpt,
        )

    @property
    def is_supported(self) -> bool:
        return self.support.is_supported

    def to_payload(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "source_id": self.source_id,
            "doc_version_id": self.doc_version_id,
            "parser_run_id": self.parser_run_id,
            "block_id": self.block_id,
            "position": self.position.to_payload(),
            "quoted_excerpt_hash": self.quoted_excerpt_hash,
            "parser_confidence": self.parser_confidence,
            "span_support_verification": self.support.to_payload(),
            "quoted_excerpt": self.quoted_excerpt,
        }


def verify_span_support(
    span: EvidenceSpan,
    blocks_by_id: Mapping[str, DocumentBlock],
    *,
    verifier: str = "char-span-rehash-v0",
) -> EvidenceSpan:
    """span-support 验证：把 span 声称的引文【对回源 block 复算哈希】，命中 → supported，否则 challenged。

    这是抗伪造核心（reader 不可信）：reader 声称「block B 的 char_span [s,e) 处引文 = X」，本函数取
    `block.text[s:e]` 复算哈希比对 `quoted_excerpt_hash`——伪造（位置 / 内容对不上）即 `challenged`，
    不进 confirmatory（GOAL §6）。返回【替换了 `support` 的同一条 span】（span_id 不变）。

    诚实边界：验证的是「引文是否复算命中所称位置」，不对文档内容真伪 / 论断对错下结论。
    """
    now = _now()
    block = blocks_by_id.get(span.block_id)
    if block is None:
        return replace(
            span,
            support=SpanSupportVerification(
                status="challenged",
                method="char-span-rehash",
                reason=f"span 引用的 block_id={span.block_id} 不在本次抽取产物中 → 不可复算（疑悬挂引用）。",
                verifier=verifier,
                checked_at_utc=now,
            ),
        )
    # 跨文档 / 跨解析运行的 block 引用 = 伪造面（reader 拿别的文档的块充当本文档证据）。
    if block.doc_version_id != span.doc_version_id or block.parser_run_id != span.parser_run_id:
        return replace(
            span,
            support=SpanSupportVerification(
                status="challenged",
                method="char-span-rehash",
                reason="span 的 doc_version_id / parser_run_id 与所引 block 不一致 → 跨文档伪造面。",
                verifier=verifier,
                checked_at_utc=now,
            ),
        )

    char_span = span.position.char_span
    if char_span is not None:
        start, end = char_span
        actual = block.text[start:end]
        ok = content_hash(actual) == span.quoted_excerpt_hash
        reason = (
            "char_span 处文本复算哈希命中 quoted_excerpt_hash。"
            if ok
            else f"char_span[{start}:{end}] 处文本复算哈希与 quoted_excerpt_hash 不符 → 引文不在所称位置。"
        )
    else:
        # 无 char_span：退化为「引文哈希须命中 block 内某子串」（仅当存了引文原文才可判；否则无法复算）。
        if span.quoted_excerpt:
            ok = span.quoted_excerpt in block.text
            reason = (
                "无 char_span，退化子串包含校验命中。"
                if ok
                else "无 char_span，退化子串包含校验未命中 → 引文不在 block 内。"
            )
        else:
            return replace(
                span,
                support=SpanSupportVerification(
                    status="challenged",
                    method="char-span-rehash",
                    reason="无 char_span 且未存引文原文 → 无法对回源复算 → 保守判 challenged。",
                    verifier=verifier,
                    checked_at_utc=now,
                ),
            )

    return replace(
        span,
        support=SpanSupportVerification(
            status="supported" if ok else "challenged",
            method="char-span-rehash",
            reason=reason,
            verifier=verifier,
            checked_at_utc=now,
        ),
    )


# ══ 抽取声明（策略 / 模型·硬标【抽取自文档·未验证】·缺证据即拒） ═══════════════════
def _validate_extracted_claim(
    *,
    evidence_refs: Sequence[str],
    verification_status: str,
    disclosure: str,
    ctx: str,
) -> None:
    """抽取声明的共用硬校验（验收 #2·诚实·抽取≠已验证·不假绿灯）。

    ① evidence_refs 非空（缺 EvidenceSpan → 拒·GOAL「ExtractedStrategySpec 缺 EvidenceSpan → 拒」）。
    ② verification_status 必须恰为 `extracted_unverified`（本层永不发其它绿灯态·杜绝假已验证）。
    ③ disclosure 在场且含「未验证」marker（必须显式诚实标注·不得静默升格）。
    """
    if not evidence_refs:
        raise DocumentExtractionError(
            f"{ctx}：evidence_refs 为空 → 拒（抽取声明必须引 ≥1 条 EvidenceSpan·缺证据即孤儿）。"
        )
    if any(not (r or "").strip() for r in evidence_refs):
        raise DocumentExtractionError(
            f"{ctx}：evidence_refs 含空引用 → 拒（证据引用须为非空 span_id）。"
        )
    if verification_status != EXTRACTED_UNVERIFIED:
        raise DocumentExtractionError(
            f"{ctx}：verification_status={verification_status!r} 非法 → 拒。抽取层只产 "
            f"{EXTRACTED_UNVERIFIED!r}（抽取≠已验证·不得在抽取层标 validated / proof-backed / "
            "production-ready·晋级走下游验证 dossier）。"
        )
    if "未验证" not in (disclosure or ""):
        raise DocumentExtractionError(
            f"{ctx}：disclosure 缺失或未含「未验证」诚实 marker → 拒（不假绿灯·须显式标抽取自文档·未验证）。"
        )


@dataclass(frozen=True)
class ExtractedStrategySpec:
    """从文档抽取出的策略声明（GOAL §6 ExtractedStrategySpec）·硬标【抽取自文档·未验证残余】。

    缺 EvidenceSpan → 拒；`verification_status` 恒为 `extracted_unverified`（本层不发绿灯）；带不可
    去除的 `disclosure`。它【可】继续研究 / 试验 / 回测，但【不得】展示为 proof-backed /
    evidence-sufficient / production-ready（GOAL §6）。是否够格进 confirmatory 见 `confirmatory_ready`。
    """

    spec_id: str
    extraction_run_id: str
    source_id: str
    doc_version_id: str
    title: str
    summary: str
    evidence_refs: tuple[str, ...]
    verification_status: str = EXTRACTED_UNVERIFIED
    disclosure: str = EXTRACTED_DISCLOSURE

    def __post_init__(self) -> None:
        _validate_extracted_claim(
            evidence_refs=self.evidence_refs,
            verification_status=self.verification_status,
            disclosure=self.disclosure,
            ctx="ExtractedStrategySpec",
        )

    @classmethod
    def create(
        cls,
        *,
        extraction_run_id: str,
        source_id: str,
        doc_version_id: str,
        title: str,
        summary: str,
        evidence_refs: Sequence[str],
    ) -> "ExtractedStrategySpec":
        refs = tuple(evidence_refs)
        spec_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "extracted_strategy_spec",
                "doc_version_id": doc_version_id,
                "title": title,
                "summary": summary,
                "evidence_refs": sorted(refs),
            }
        )
        return cls(
            spec_id=spec_id,
            extraction_run_id=extraction_run_id,
            source_id=source_id,
            doc_version_id=doc_version_id,
            title=title,
            summary=summary,
            evidence_refs=refs,
        )

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence_refs"] = list(self.evidence_refs)
        return d


@dataclass(frozen=True)
class ExtractedModelClaim:
    """从文档抽取出的模型声明（GOAL §6 ExtractedModelClaim）·硬标【抽取自文档·未验证残余】。

    例「论文称模型 X 在样本 Y 上 Sharpe=Z」——这是【文档这么说】，不是【我们验证过】。缺 EvidenceSpan
    → 拒；`verification_status` 恒为 `extracted_unverified`；带不可去除 `disclosure`。
    """

    claim_id: str
    extraction_run_id: str
    source_id: str
    doc_version_id: str
    claim_text: str
    evidence_refs: tuple[str, ...]
    verification_status: str = EXTRACTED_UNVERIFIED
    disclosure: str = EXTRACTED_DISCLOSURE

    def __post_init__(self) -> None:
        _validate_extracted_claim(
            evidence_refs=self.evidence_refs,
            verification_status=self.verification_status,
            disclosure=self.disclosure,
            ctx="ExtractedModelClaim",
        )

    @classmethod
    def create(
        cls,
        *,
        extraction_run_id: str,
        source_id: str,
        doc_version_id: str,
        claim_text: str,
        evidence_refs: Sequence[str],
    ) -> "ExtractedModelClaim":
        refs = tuple(evidence_refs)
        claim_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "extracted_model_claim",
                "doc_version_id": doc_version_id,
                "claim_text": claim_text,
                "evidence_refs": sorted(refs),
            }
        )
        return cls(
            claim_id=claim_id,
            extraction_run_id=extraction_run_id,
            source_id=source_id,
            doc_version_id=doc_version_id,
            claim_text=claim_text,
            evidence_refs=refs,
        )

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence_refs"] = list(self.evidence_refs)
        return d


def confirmatory_ready(
    evidence_refs: Sequence[str],
    spans_by_id: Mapping[str, EvidenceSpan],
) -> bool:
    """抽取声明是否够格进 confirmatory：当且仅当它引的【每一条】span 都已 span-support `supported`。

    GOAL §6「span 存在但未通过 span-support verification → 标 challenged / 不进 confirmatory」。
    任一 span 缺失 / unverified / challenged / refuted → 返回 False（保守·不假绿灯）。
    """
    if not evidence_refs:
        return False
    for ref in evidence_refs:
        span = spans_by_id.get(ref)
        if span is None or not span.is_supported:
            return False
    return True


# ══ 沙箱 block 抽取（全程经 no-network 沙箱·不绕安全门·验收 #3） ═══════════════════
@runtime_checkable
class DocumentBlockExtractor(Protocol):
    """block 抽取器协议：是 `OfflineDocumentParser`（产 `ParsedDocument` 喂限额门），并额外产 `RawBlock`。

    真 PDF / OOXML 解析库（用户选型）实现本协议后，由 `SandboxedBlockExtractor` 包进 no-network 沙箱。
    本卡只提供离线 `StubBlockExtractor`（文本格式 char_span 精确·二进制格式诚实留白）。
    """

    name: str
    version: str

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument: ...

    def extract_blocks(self, data: bytes, *, declared_format: str) -> Sequence[RawBlock]: ...


# 文本族格式：stub 能精确切块 + 给真 char_span（span-support 复算因此货真价实）。
_TEXT_FORMATS: frozenset[str] = frozenset({"text", "html", "rtf", "unknown"})


class StubBlockExtractor(StubOfflineParser):
    """默认离线 block 抽取器：复用 `StubOfflineParser`（页数 + no-network 契约）+ 文本切块。

    诚实：
      - 文本族（text/html/...）：UTF-8 解码（errors=replace·确定性），按空行切段，给【精确 char_span】
        ——这让 EvidenceSpan span-support 复算【货真价实】（不是占位）。轻量启发标 heading（`#` 开头）/
        table（每行含 `|`）/ formula（`$...$` / `\\(`）/ reference（`[n]` 开头）。
      - 二进制族（pdf/ooxml/ole/...）：【不伪造块】——返回空 + 诚实留白（真结构抽取须真解析库·用户选型）。
    """

    name = "stub-block-extractor-v0"
    version = "v0"
    _MAX_DECODE_BYTES = 8 * 1024 * 1024  # 再保险：即便 size 门放过也不无界解码

    def extract_blocks(self, data: bytes, *, declared_format: str) -> Sequence[RawBlock]:
        if declared_format not in _TEXT_FORMATS:
            return ()  # 二进制：不伪造块（真解析库职责·诚实留白）
        text = data[: self._MAX_DECODE_BYTES].decode("utf-8", errors="replace")
        blocks: list[RawBlock] = []
        cursor = 0
        # 按空行切段，char_span 用切前文本的真实偏移（半开区间）。
        for chunk in text.split("\n\n"):
            start = text.find(chunk, cursor) if chunk else -1
            if not chunk.strip():
                cursor += len(chunk) + 2
                continue
            if start < 0:
                start = cursor
            end = start + len(chunk)
            cursor = end + 2
            blocks.append(
                RawBlock(
                    block_type=self._classify(chunk),
                    text=chunk,
                    position=BlockPosition(char_span=(start, end), section=""),
                )
            )
        return tuple(blocks)

    @staticmethod
    def _classify(chunk: str) -> BlockType:
        stripped = chunk.strip()
        lines = [ln for ln in stripped.splitlines() if ln.strip()]
        if stripped.startswith("#"):
            return "heading"
        if lines and all("|" in ln for ln in lines):
            return "table"
        if ("$" in stripped and stripped.count("$") >= 2) or "\\(" in stripped:
            return "formula"
        if stripped.startswith("[") and "]" in stripped[:6]:
            return "reference"
        return "paragraph"


@dataclass(frozen=True)
class ParseExtractionProducts:
    """沙箱抽取一遍的结构化产物：解析结果 + parser_run_id + typed blocks/artifacts。"""

    parsed: ParsedDocument
    parser_run_id: str
    blocks: tuple[DocumentBlock, ...]
    tables: tuple[TableArtifact, ...]
    formulas: tuple[FormulaArtifact, ...]
    references: tuple[ReferenceArtifact, ...]


class SandboxedBlockExtractor:
    """把任意 `DocumentBlockExtractor` 包进 no-network 沙箱 + 页数限额（mirror `sandbox.SafeDocumentParser`）。

    `extract` 全程在 `safety.no_network()` 内跑解析 + 切块 —— 抽取器任何联网尝试 → `DocumentIntakeError`
    （no-network 红线·验收 #3「抽取经 sandbox 不绕安全门」）。解析后过 `check_pages` 限额门（页炸弹）。
    `parser_run_id` 内容寻址（绑 content_sha256 + 解析器身份 + 格式）——同输入同 run（可 replay）。
    """

    def __init__(
        self,
        extractor: DocumentBlockExtractor | None = None,
        *,
        limits: IntakeLimits | None = None,
    ) -> None:
        self._extractor: DocumentBlockExtractor = extractor or StubBlockExtractor()
        self._limits = limits or IntakeLimits()

    @property
    def extractor_name(self) -> str:
        return self._extractor.name

    @property
    def extractor_version(self) -> str:
        return getattr(self._extractor, "version", "v0")

    def parser_run_id(
        self, *, doc_version_id: str, content_sha256: str, declared_format: str
    ) -> str:
        return content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "parser_run",
                "doc_version_id": doc_version_id,
                "content_sha256": content_sha256,
                "parser_name": self._extractor.name,
                "parser_version": self.extractor_version,
                "declared_format": declared_format,
            }
        )

    def extract(
        self,
        data: bytes,
        *,
        declared_format: str,
        source_id: str,
        doc_version_id: str,
        content_sha256: str,
    ) -> ParseExtractionProducts:
        """在 no-network 沙箱内解析 + 切块；联网尝试 → 拒；页数超限 → 拒。产 typed blocks/artifacts。"""
        _nonempty(source_id, field_name="source_id", ctx="SandboxedBlockExtractor")
        _nonempty(doc_version_id, field_name="doc_version_id", ctx="SandboxedBlockExtractor")
        _nonempty(content_sha256, field_name="content_sha256", ctx="SandboxedBlockExtractor")
        with no_network():
            parsed = self._extractor.parse(data, declared_format=declared_format)
            raw_blocks = tuple(self._extractor.extract_blocks(data, declared_format=declared_format))
        if not isinstance(parsed, ParsedDocument):
            raise DocumentExtractionError(
                f"抽取器 {self._extractor.name!r} parse 返回非 ParsedDocument（{type(parsed)!r}）→ 拒。"
            )
        check_pages(parsed.n_pages, self._limits)  # 页炸弹限额（复用安全门）

        parser_run_id = self.parser_run_id(
            doc_version_id=doc_version_id,
            content_sha256=content_sha256,
            declared_format=declared_format,
        )
        blocks: list[DocumentBlock] = []
        tables: list[TableArtifact] = []
        formulas: list[FormulaArtifact] = []
        references: list[ReferenceArtifact] = []
        for raw in raw_blocks:
            if not isinstance(raw, RawBlock):
                raise DocumentExtractionError(
                    f"抽取器 {self._extractor.name!r} 产出非 RawBlock（{type(raw)!r}）→ 拒（schema 约束）。"
                )
            block = DocumentBlock.create(
                source_id=source_id,
                doc_version_id=doc_version_id,
                parser_run_id=parser_run_id,
                raw=raw,
            )
            blocks.append(block)
            # typed 专项产物（从 block 派生·linked by block_id）。
            if raw.block_type == "table":
                rows = tuple(
                    tuple(cell.strip() for cell in ln.split("|"))
                    for ln in raw.text.splitlines()
                    if ln.strip()
                )
                tables.append(TableArtifact.create(block=block, rows=rows))
            elif raw.block_type == "formula":
                formulas.append(
                    FormulaArtifact.create(block=block, representation=raw.text.strip())
                )
            elif raw.block_type == "reference":
                references.append(
                    ReferenceArtifact.create(block=block, raw_citation=raw.text.strip())
                )
        return ParseExtractionProducts(
            parsed=parsed,
            parser_run_id=parser_run_id,
            blocks=tuple(blocks),
            tables=tuple(tables),
            formulas=tuple(formulas),
            references=tuple(references),
        )


# ══ ExtractionRun + 落账（append-only 哈希链·mirror intake.DocumentRegistry·不混 honest-N） ══
@dataclass(frozen=True)
class ExtractionRun:
    """一次抽取的落账记录（GOAL §6 ExtractionRun）·内容寻址 run_id·可 replay。

    `run_id` = content_hash(抽取【输入】：doc_version + content_sha256 + parser_run + 抽取器身份)，
    【刻意排除】产物 id 列表与时间戳 —— 同输入必同 run_id（replay 命中即返存量·不重复落账）。
    """

    run_id: str
    source_id: str
    doc_version_id: str
    content_sha256: str
    parser_run_id: str
    parser_name: str
    extractor_name: str
    extractor_version: str
    block_ids: tuple[str, ...]
    table_ids: tuple[str, ...]
    formula_ids: tuple[str, ...]
    reference_ids: tuple[str, ...]
    evidence_span_ids: tuple[str, ...]
    strategy_spec_ids: tuple[str, ...]
    model_claim_ids: tuple[str, ...]
    created_at_utc: str = field(default_factory=_now)
    note: str = ""

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        doc_version_id: str,
        content_sha256: str,
        parser_run_id: str,
        parser_name: str,
        extractor_name: str,
        extractor_version: str,
        block_ids: Sequence[str] = (),
        table_ids: Sequence[str] = (),
        formula_ids: Sequence[str] = (),
        reference_ids: Sequence[str] = (),
        evidence_span_ids: Sequence[str] = (),
        strategy_spec_ids: Sequence[str] = (),
        model_claim_ids: Sequence[str] = (),
        note: str = "",
    ) -> "ExtractionRun":
        _nonempty(source_id, field_name="source_id", ctx="ExtractionRun")
        _nonempty(doc_version_id, field_name="doc_version_id", ctx="ExtractionRun")
        _nonempty(content_sha256, field_name="content_sha256", ctx="ExtractionRun")
        _nonempty(parser_run_id, field_name="parser_run_id", ctx="ExtractionRun")
        run_id = content_hash(
            {
                "schema": EXTRACTION_SCHEMA,
                "kind": "extraction_run",
                "doc_version_id": doc_version_id,
                "content_sha256": content_sha256,
                "parser_run_id": parser_run_id,
                "extractor_name": extractor_name,
                "extractor_version": extractor_version,
            }
        )
        return cls(
            run_id=run_id,
            source_id=source_id,
            doc_version_id=doc_version_id,
            content_sha256=content_sha256,
            parser_run_id=parser_run_id,
            parser_name=parser_name,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            block_ids=tuple(block_ids),
            table_ids=tuple(table_ids),
            formula_ids=tuple(formula_ids),
            reference_ids=tuple(reference_ids),
            evidence_span_ids=tuple(evidence_span_ids),
            strategy_spec_ids=tuple(strategy_spec_ids),
            model_claim_ids=tuple(model_claim_ids),
            note=note,
        )

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        for k in (
            "block_ids", "table_ids", "formula_ids", "reference_ids",
            "evidence_span_ids", "strategy_spec_ids", "model_claim_ids",
        ):
            d[k] = list(getattr(self, k))
        return d


class ExtractionLedger:
    """ExtractionRun append-only 哈希链账（mirror `intake.DocumentRegistry`·prev_hash 链·内容寻址·幂等）。

    刻意【独立于】honest-N `lineage.ledger.Ledger`：那本是试验计数账（kind ∈ backtest/train/...，靠
    config_hash 计 honest-N），抽取运行【不是】试验，混进去会虚高 honest-N（作弊面）。与 intake「文档侧
    独立账·绝不与 honest-N 混账」同纪律。复用 `ids.content_hash` 算行指纹（不另造哈希族）。

    `record` 按 `run_id` 内容寻址幂等：同输入再抽 → 命中存量（hit=True·不重复 append），兑现 replay。
    `verify_chain` 重算 prev_hash 链揪事后篡改（诚实：只防篡改·不保证内容真实）。
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
                continue  # 容忍崩溃残尾行，不让一行炸全账（同 intake/ledger 纪律）
        return out

    def _scan_tail(self) -> tuple[int, str]:
        last_hash, next_seq = GENESIS_HASH, 0
        for rec in self._read_records():
            last_hash, next_seq = rec["row_hash"], rec["seq"] + 1
        return next_seq, last_hash

    @staticmethod
    def _row_hash(seq: int, prev_hash: str, record: dict[str, Any]) -> str:
        return content_hash({"seq": seq, "prev_hash": prev_hash, "record": record})

    def get(self, run_id: str) -> dict[str, Any] | None:
        """按 run_id 取最近一次落账记录（replay 查证）。"""
        found: dict[str, Any] | None = None
        for rec in self._read_records():
            r = rec.get("record")
            if isinstance(r, dict) and r.get("run_id") == run_id:
                found = r
        return found

    def record(self, run: ExtractionRun) -> tuple[ExtractionRun, bool]:
        """落账（append-only）。同 run_id 已在账 → 返存量 + hit=True（不重复 append·replay 幂等）。"""
        with self._lock:
            for rec in self._read_records():
                r = rec.get("record")
                if isinstance(r, dict) and r.get("run_id") == run.run_id:
                    return run, True
            payload = run.to_payload()
            seq = self._next_seq
            prev = self._last_hash
            row_hash = self._row_hash(seq, prev, payload)
            line = {"seq": seq, "prev_hash": prev, "row_hash": row_hash, "record": payload}
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()
            self._next_seq, self._last_hash = seq + 1, row_hash
            return run, False

    def list_runs(self) -> list[dict[str, Any]]:
        return [rec["record"] for rec in self._read_records()]

    def verify_chain(self) -> tuple[bool, list[str]]:
        """重算 prev_hash 链，检出对落账文件的事后篡改 / 链断。返回 (intact, issues)。"""
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


# ══ Reader（untrusted）协议 + 编排 ══════════════════════════════════════════════
@dataclass(frozen=True)
class ReaderProposal:
    """Reader（untrusted）提案：候选 EvidenceSpan + 抽取声明。绝不直接信任 —— span 须经 span-support 验证、
    声明的 evidence_refs 须指向本次真实产出的 span（编排层校验）。"""

    evidence_spans: tuple[EvidenceSpan, ...] = ()
    strategy_specs: tuple[ExtractedStrategySpec, ...] = ()
    model_claims: tuple[ExtractedModelClaim, ...] = ()


@runtime_checkable
class DocumentReader(Protocol):
    """Reader 协议（GOAL §6「Reader 抽结构化证据·privileged tool-holder 只消费 schema 约束产物」）。

    Reader = untrusted（真实现常为 LLM / 规则引擎，用户 / 下游选型）。它【只能】产 schema 约束的提案，
    编排层负责验证（span-support + evidence_refs 指向真实 span），过不了即降级 / 拒。
    """

    def read(
        self,
        blocks: Sequence[DocumentBlock],
        *,
        source_id: str,
        doc_version_id: str,
        parser_run_id: str,
    ) -> ReaderProposal: ...


@dataclass(frozen=True)
class ExtractionResult:
    """`run_extraction` 产物：落账 run + 全部 typed 产物 + 验证后的 span + 抽取声明。"""

    run: ExtractionRun
    parser_run_id: str
    parsed: ParsedDocument
    blocks: tuple[DocumentBlock, ...]
    tables: tuple[TableArtifact, ...]
    formulas: tuple[FormulaArtifact, ...]
    references: tuple[ReferenceArtifact, ...]
    evidence_spans: tuple[EvidenceSpan, ...]
    strategy_specs: tuple[ExtractedStrategySpec, ...]
    model_claims: tuple[ExtractedModelClaim, ...]
    recorded: bool  # True=本次新落账；False=replay 命中存量

    def confirmatory_ready_spec_ids(self) -> tuple[str, ...]:
        """够格进 confirmatory 的策略声明 id（其所引 span 全部 supported）。"""
        spans_by_id = {s.span_id: s for s in self.evidence_spans}
        return tuple(
            spec.spec_id
            for spec in self.strategy_specs
            if confirmatory_ready(spec.evidence_refs, spans_by_id)
        )


def run_extraction(
    *,
    data: bytes,
    declared_format: str,
    source_id: str,
    doc_version_id: str,
    content_sha256: str,
    extractor: DocumentBlockExtractor | None = None,
    reader: DocumentReader | None = None,
    ledger: ExtractionLedger | None = None,
    limits: IntakeLimits | None = None,
) -> ExtractionResult:
    """端到端抽取一遍：沙箱切块 → typed 产物 → （可选 reader 提案 → span-support 验证）→ 落账。

    安全 / 诚实纪律：
      - block 抽取全程经 `SandboxedBlockExtractor`（no-network + 页数限额）——不绕安全门（验收 #3）。
      - reader 提案【不可信】：每条 span 经 `verify_span_support` 对回源 block 复算（伪造 → challenged）；
        每个抽取声明的 `evidence_refs` 必须指向本次真实产出的 span，否则 → 拒（悬挂引用 = 伪造面）。
      - `ExtractionRun` 内容寻址落账（同输入 replay 命中存量·不重复入账·验收 #4）。
    """
    sx = SandboxedBlockExtractor(extractor, limits=limits)
    products = sx.extract(
        data,
        declared_format=declared_format,
        source_id=source_id,
        doc_version_id=doc_version_id,
        content_sha256=content_sha256,
    )
    blocks_by_id = {b.block_id: b for b in products.blocks}

    verified_spans: tuple[EvidenceSpan, ...] = ()
    strategy_specs: tuple[ExtractedStrategySpec, ...] = ()
    model_claims: tuple[ExtractedModelClaim, ...] = ()
    if reader is not None:
        proposal = reader.read(
            products.blocks,
            source_id=source_id,
            doc_version_id=doc_version_id,
            parser_run_id=products.parser_run_id,
        )
        verified_spans = tuple(
            verify_span_support(span, blocks_by_id) for span in proposal.evidence_spans
        )
        span_ids = {s.span_id for s in verified_spans}
        # 抽取声明的证据引用必须指向本次真实产出的 span（悬挂 / 伪造引用 → 拒）。
        for spec in proposal.strategy_specs:
            _assert_refs_resolve(spec.evidence_refs, span_ids, ctx=f"ExtractedStrategySpec {spec.spec_id}")
        for claim in proposal.model_claims:
            _assert_refs_resolve(claim.evidence_refs, span_ids, ctx=f"ExtractedModelClaim {claim.claim_id}")
        strategy_specs = tuple(proposal.strategy_specs)
        model_claims = tuple(proposal.model_claims)

    run = ExtractionRun.create(
        source_id=source_id,
        doc_version_id=doc_version_id,
        content_sha256=content_sha256,
        parser_run_id=products.parser_run_id,
        parser_name=products.parsed.parser_name,
        extractor_name=sx.extractor_name,
        extractor_version=sx.extractor_version,
        block_ids=[b.block_id for b in products.blocks],
        table_ids=[t.artifact_id for t in products.tables],
        formula_ids=[f.artifact_id for f in products.formulas],
        reference_ids=[r.artifact_id for r in products.references],
        evidence_span_ids=[s.span_id for s in verified_spans],
        strategy_spec_ids=[s.spec_id for s in strategy_specs],
        model_claim_ids=[c.claim_id for c in model_claims],
        note=products.parsed.extraction_note,
    )
    recorded = True
    if ledger is not None:
        run, hit = ledger.record(run)
        recorded = not hit

    return ExtractionResult(
        run=run,
        parser_run_id=products.parser_run_id,
        parsed=products.parsed,
        blocks=products.blocks,
        tables=products.tables,
        formulas=products.formulas,
        references=products.references,
        evidence_spans=verified_spans,
        strategy_specs=strategy_specs,
        model_claims=model_claims,
        recorded=recorded,
    )


def _assert_refs_resolve(refs: Iterable[str], span_ids: set[str], *, ctx: str) -> None:
    missing = [r for r in refs if r not in span_ids]
    if missing:
        raise DocumentExtractionError(
            f"{ctx}：evidence_refs 含本次抽取未产出的 span_id {missing} → 拒"
            "（悬挂 / 伪造证据引用·抽取声明只能引本次真实产出的可追溯 span）。"
        )


__all__ = [
    "ALLOWED_BLOCK_TYPES",
    "ALLOWED_SPAN_STATUSES",
    "EXTRACTED_DISCLOSURE",
    "EXTRACTED_UNVERIFIED",
    "EXTRACTION_REGISTRY_FILENAME",
    "EXTRACTION_SCHEMA",
    "BlockPosition",
    "DocumentBlock",
    "DocumentBlockExtractor",
    "DocumentExtractionError",
    "DocumentReader",
    "EvidenceSpan",
    "ExtractedModelClaim",
    "ExtractedStrategySpec",
    "ExtractionLedger",
    "ExtractionResult",
    "ExtractionRun",
    "FormulaArtifact",
    "ParseExtractionProducts",
    "RawBlock",
    "ReaderProposal",
    "ReferenceArtifact",
    "SandboxedBlockExtractor",
    "SpanSupportVerification",
    "StubBlockExtractor",
    "TableArtifact",
    "confirmatory_ready",
    "run_extraction",
    "verify_span_support",
]
