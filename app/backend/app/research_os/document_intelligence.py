"""GOAL §6 document intelligence and evidence-span contracts."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..lineage.ids import content_hash


_LOCAL_TEXT_PARSER_ID = "local_text_markdown_no_network_v1"
_LOCAL_HTML_PARSER_ID = "local_html_snapshot_no_network_v1"
_LOCAL_PDF_LAYOUT_PARSER_ID = "local_pdf_pymupdf_layout_no_network_v1"
_LOCAL_PDF_TEXT_FALLBACK_PARSER_ID = "local_pdf_pypdf_text_no_network_v1"
_LOCAL_PDF_OCR_PARSER_ID = "local_pdf_tesseract_ocr_no_network_v1"
_LOCAL_TEXT_MIME_BY_SUFFIX = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".rst": "text/x-rst",
}
_LOCAL_HTML_SUFFIXES = {".html", ".htm"}
_LOCAL_PDF_SUFFIX = ".pdf"
_SOURCE_URL_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "access_key",
    "authorization",
    "auth",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
)
_SENSITIVE_PATH_NAMES = {
    ".env",
    ".env.local",
    "credentials",
    "credential",
    "secrets",
    "secret",
    "tokens",
    "token",
    "id_rsa",
    "id_ed25519",
}
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


@dataclass(frozen=True)
class DocumentIntelligenceViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class DocumentIntelligenceDecision:
    accepted: bool
    violations: tuple[DocumentIntelligenceViolation, ...]


@dataclass(frozen=True)
class SourceDocumentIntakeRecord:
    source_ref: str
    quarantine_ref: str | None
    parser_sandbox_ref: str | None
    mime_magic_check_ref: str | None
    source_hash: str | None
    license_rights_ref: str | None
    no_network_parser: bool
    untrusted_data_boundary_ref: str | None


@dataclass(frozen=True)
class EvidenceSpanRecord:
    span_ref: str
    source_id: str
    doc_version_id: str
    parser_run_id: str
    block_id: str
    page: int | None
    quoted_excerpt_hash: str | None
    parser_confidence: float
    span_support_verification_ref: str | None
    verified: bool


@dataclass(frozen=True)
class ExtractedResearchClaim:
    claim_ref: str
    claim_kind: str
    evidence_span_refs: tuple[str, ...]
    confirmatory_use: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_span_refs", _tuple(self.evidence_span_refs))


@dataclass(frozen=True)
class PrivilegedToolUseRequest:
    request_ref: str
    source_document_ref: str
    direct_document_payload: bool
    schema_constrained_artifact_ref: str | None


@dataclass(frozen=True)
class LocalDocumentBlock:
    block_id: str
    page: int
    section: str
    char_start: int
    char_end: int
    text: str
    quoted_excerpt_hash: str
    layout_bbox: tuple[float, float, float, float] | None = None
    layout_block_index: int | None = None
    layout_kind: str | None = None


@dataclass(frozen=True)
class LocalDocumentParseResult:
    source_path: str
    doc_version_id: str
    parser_run_id: str
    mime_magic_check_ref: str
    source: SourceDocumentIntakeRecord
    spans: tuple[EvidenceSpanRecord, ...]
    blocks: tuple[LocalDocumentBlock, ...]
    source_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "spans", tuple(self.spans))
        object.__setattr__(self, "blocks", tuple(self.blocks))


def validate_source_document_intake(source: SourceDocumentIntakeRecord) -> DocumentIntelligenceDecision:
    violations: list[DocumentIntelligenceViolation] = []
    for field_name in (
        "quarantine_ref",
        "parser_sandbox_ref",
        "mime_magic_check_ref",
        "source_hash",
        "license_rights_ref",
        "untrusted_data_boundary_ref",
    ):
        if not _present(getattr(source, field_name)):
            violations.append(
                DocumentIntelligenceViolation(
                    "source_intake_missing_safety_ref",
                    "source intake requires quarantine, sandbox, magic check, hash, rights, and untrusted-data boundary",
                    field=field_name,
                    ref=source.source_ref,
                )
            )
    if not source.no_network_parser:
        violations.append(
            DocumentIntelligenceViolation(
                "source_parser_network_enabled",
                "document parser must not perform network access",
                field="no_network_parser",
                ref=source.source_ref,
            )
        )
    return DocumentIntelligenceDecision(accepted=not violations, violations=tuple(violations))


def validate_evidence_span(span: EvidenceSpanRecord) -> DocumentIntelligenceDecision:
    violations: list[DocumentIntelligenceViolation] = []
    for field_name in (
        "source_id",
        "doc_version_id",
        "parser_run_id",
        "block_id",
        "quoted_excerpt_hash",
    ):
        if not _present(getattr(span, field_name)):
            violations.append(
                DocumentIntelligenceViolation(
                    "evidence_span_missing_required_ref",
                    "EvidenceSpan requires source, version, parser, block, and quoted excerpt hash",
                    field=field_name,
                    ref=span.span_ref,
                )
            )
    if span.page is None:
        violations.append(
            DocumentIntelligenceViolation(
                "evidence_span_missing_location",
                "EvidenceSpan requires a page/location anchor",
                field="page",
                ref=span.span_ref,
            )
        )
    if span.verified and not _present(span.span_support_verification_ref):
        violations.append(
            DocumentIntelligenceViolation(
                "verified_span_missing_support_record",
                "verified EvidenceSpan requires span-support verification record",
                field="span_support_verification_ref",
                ref=span.span_ref,
            )
        )
    return DocumentIntelligenceDecision(accepted=not violations, violations=tuple(violations))


def validate_extracted_claim(
    claim: ExtractedResearchClaim,
    *,
    spans: tuple[EvidenceSpanRecord, ...],
) -> DocumentIntelligenceDecision:
    violations: list[DocumentIntelligenceViolation] = []
    span_by_ref = {span.span_ref: span for span in spans}
    if not claim.evidence_span_refs:
        violations.append(
            DocumentIntelligenceViolation(
                "extracted_claim_missing_evidence_span",
                "extracted strategy/model claims require EvidenceSpan refs",
                field="evidence_span_refs",
                ref=claim.claim_ref,
            )
        )
    for span_ref in claim.evidence_span_refs:
        span = span_by_ref.get(str(span_ref))
        if span is None:
            violations.append(
                DocumentIntelligenceViolation(
                    "extracted_claim_unknown_evidence_span",
                    "extracted claim references an unknown EvidenceSpan",
                    field="evidence_span_refs",
                    ref=claim.claim_ref,
                )
            )
            continue
        if claim.confirmatory_use and not span.verified:
            violations.append(
                DocumentIntelligenceViolation(
                    "unverified_span_used_for_confirmatory_claim",
                    "unverified EvidenceSpan cannot enter confirmatory validation",
                    field="confirmatory_use",
                    ref=claim.claim_ref,
                )
            )
    return DocumentIntelligenceDecision(accepted=not violations, violations=tuple(violations))


def validate_privileged_tool_use(request: PrivilegedToolUseRequest) -> DocumentIntelligenceDecision:
    violations: list[DocumentIntelligenceViolation] = []
    if request.direct_document_payload:
        violations.append(
            DocumentIntelligenceViolation(
                "document_payload_direct_privileged_tool_use",
                "PDF/webpage content must not directly trigger privileged tools",
                field="direct_document_payload",
                ref=request.request_ref,
            )
        )
    if not _present(request.schema_constrained_artifact_ref):
        violations.append(
            DocumentIntelligenceViolation(
                "privileged_tool_missing_schema_artifact",
                "privileged tools may consume only schema-constrained artifacts",
                field="schema_constrained_artifact_ref",
                ref=request.request_ref,
            )
        )
    return DocumentIntelligenceDecision(accepted=not violations, violations=tuple(violations))


def validate_document_intelligence(
    *,
    sources: tuple[SourceDocumentIntakeRecord, ...] = (),
    spans: tuple[EvidenceSpanRecord, ...] = (),
    claims: tuple[ExtractedResearchClaim, ...] = (),
    tool_requests: tuple[PrivilegedToolUseRequest, ...] = (),
) -> DocumentIntelligenceDecision:
    violations: list[DocumentIntelligenceViolation] = []
    for source in sources:
        violations.extend(validate_source_document_intake(source).violations)
    for span in spans:
        violations.extend(validate_evidence_span(span).violations)
    for claim in claims:
        violations.extend(validate_extracted_claim(claim, spans=spans).violations)
    for request in tool_requests:
        violations.extend(validate_privileged_tool_use(request).violations)
    return DocumentIntelligenceDecision(accepted=not violations, violations=tuple(violations))


def parse_local_text_document(
    source_path: str,
    *,
    root: str | Path,
    source_ref: str | None = None,
    source_url: str | None = None,
    allowed_url_hosts: tuple[str, ...] = (),
    license_rights_ref: str | None = None,
    max_bytes: int = 1_000_000,
    max_pages: int = 100,
) -> LocalDocumentParseResult:
    """Parse a local UTF-8 text/Markdown or PDF document into safe evidence spans.

    The parser deliberately does not fetch URLs or execute document content.
    It accepts only relative paths under ``root`` and treats all parsed text as
    untrusted candidate evidence until later validation promotes it.
    """

    if not _present(license_rights_ref):
        raise ValueError("license_rights_ref is required for local document parsing")
    path = _safe_local_document_path(root, source_path)
    suffix = path.suffix.lower()
    mime = _LOCAL_TEXT_MIME_BY_SUFFIX.get(suffix)
    if suffix == _LOCAL_PDF_SUFFIX:
        mime = "application/pdf"
    if suffix in _LOCAL_HTML_SUFFIXES:
        mime = "text/html"
    if mime is None:
        raise ValueError("local document parser supports only UTF-8 text/Markdown/PDF/HTML sources")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("local document is empty")
    if size > max_bytes:
        raise ValueError("local document exceeds parser size limit")
    raw = path.read_bytes()
    parser_id = _LOCAL_TEXT_PARSER_ID
    untrusted_boundary_ref = "untrusted_data:document_intelligence_local_parser:v1"
    stable_source_url: str | None = None
    if suffix == _LOCAL_PDF_SUFFIX:
        if source_url:
            raise ValueError("source_url is accepted only for HTML/web snapshot parsing")
        if not raw.startswith(b"%PDF-"):
            raise ValueError("local PDF magic check failed")
        mime_magic_check_ref = "mime:application/pdf:suffix:.pdf:magic:%PDF"
        parser_id, blocks = _local_pdf_document_blocks(path, source_hash=_sha256_bytes(raw), max_pages=max_pages)
    else:
        if b"\x00" in raw:
            raise ValueError("local document contains NUL bytes and is not text")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("local document must be valid UTF-8 text") from exc
        if not text.strip():
            raise ValueError("local document contains no parseable text")
        if suffix in _LOCAL_HTML_SUFFIXES:
            stable_source_url = _validate_web_snapshot_url(source_url, allowed_url_hosts=allowed_url_hosts)
            parser_id = _LOCAL_HTML_PARSER_ID
            untrusted_boundary_ref = "untrusted_data:document_intelligence_html_snapshot_parser:v1"
            host = urlparse(stable_source_url).hostname or ""
            mime_magic_check_ref = f"mime:text/html:suffix:{suffix}:utf8_no_nul:url_host:{host}"
            visible_text = _html_snapshot_visible_text(text)
            blocks = _local_document_blocks(visible_text, source_hash=_sha256_bytes(raw))
        else:
            if source_url:
                raise ValueError("source_url is accepted only for HTML/web snapshot parsing")
            mime_magic_check_ref = f"mime:{mime}:suffix:{suffix}:utf8_no_nul"
            blocks = _local_document_blocks(text, source_hash=_sha256_bytes(raw))

    root_path = Path(root).resolve()
    relative_path = path.relative_to(root_path).as_posix()
    source_hash = _sha256_bytes(raw)
    stable_source_ref = str(source_ref or "").strip() or "source_doc:" + content_hash(
        {"path": relative_path, "source_url": stable_source_url, "source_hash": source_hash}
    )
    doc_version_id = "doc_version:" + content_hash(
        {"source_ref": stable_source_ref, "source_hash": source_hash}
    )
    parser_run_id = "parser_run:" + content_hash(
        {
            "source_ref": stable_source_ref,
            "doc_version_id": doc_version_id,
            "parser": parser_id,
        }
    )
    source = SourceDocumentIntakeRecord(
        source_ref=stable_source_ref,
        quarantine_ref=("quarantine:web_snapshot:" if stable_source_url else "quarantine:local:") + content_hash(
            {"source_ref": stable_source_ref, "source_url": stable_source_url, "source_hash": source_hash}
        ),
        parser_sandbox_ref=f"parser_sandbox:{parser_id}",
        mime_magic_check_ref=mime_magic_check_ref,
        source_hash=source_hash,
        license_rights_ref=license_rights_ref,
        no_network_parser=True,
        untrusted_data_boundary_ref=untrusted_boundary_ref,
    )

    spans = tuple(
        EvidenceSpanRecord(
            span_ref="span:" + content_hash(
                {
                    "source_ref": stable_source_ref,
                    "doc_version_id": doc_version_id,
                    "parser_run_id": parser_run_id,
                    "block_id": block.block_id,
                    "quoted_excerpt_hash": block.quoted_excerpt_hash,
                }
            ),
            source_id=stable_source_ref,
            doc_version_id=doc_version_id,
            parser_run_id=parser_run_id,
            block_id=block.block_id,
            page=block.page,
            quoted_excerpt_hash=block.quoted_excerpt_hash,
            parser_confidence=0.99,
            span_support_verification_ref="span_support:" + content_hash(
                {
                    "source_hash": source_hash,
                    "quoted_excerpt_hash": block.quoted_excerpt_hash,
                    "page": block.page,
                    "char_start": block.char_start,
                    "char_end": block.char_end,
                    "layout_bbox": block.layout_bbox,
                    "layout_block_index": block.layout_block_index,
                    "layout_kind": block.layout_kind,
                }
            ),
            verified=True,
        )
        for block in blocks
    )
    return LocalDocumentParseResult(
        source_path=relative_path,
        doc_version_id=doc_version_id,
        parser_run_id=parser_run_id,
        mime_magic_check_ref=mime_magic_check_ref,
        source=source,
        spans=spans,
        blocks=blocks,
        source_url=stable_source_url,
    )


def parse_local_document(
    source_path: str,
    *,
    root: str | Path,
    source_ref: str | None = None,
    source_url: str | None = None,
    allowed_url_hosts: tuple[str, ...] = (),
    license_rights_ref: str | None = None,
    max_bytes: int = 1_000_000,
    max_pages: int = 100,
) -> LocalDocumentParseResult:
    return parse_local_text_document(
        source_path,
        root=root,
        source_ref=source_ref,
        source_url=source_url,
        allowed_url_hosts=allowed_url_hosts,
        license_rights_ref=license_rights_ref,
        max_bytes=max_bytes,
        max_pages=max_pages,
    )


def _safe_local_document_path(root: str | Path, source_path: str) -> Path:
    raw = str(source_path or "").strip()
    if not raw:
        raise ValueError("source_path is required")
    if "\x00" in raw:
        raise ValueError("source_path contains NUL byte")
    requested = Path(raw)
    if requested.is_absolute():
        raise ValueError("source_path must be relative to project root")
    if any(part in ("..", "") for part in requested.parts):
        raise ValueError("source_path must not contain path traversal")
    for part in requested.parts:
        lower = part.lower()
        if lower.startswith(".") or lower in _SENSITIVE_PATH_NAMES or Path(lower).suffix in _SENSITIVE_SUFFIXES:
            raise ValueError("source_path points at a hidden or sensitive path")

    root_path = Path(root).resolve()
    candidate = root_path / requested
    if _has_symlink_between(candidate, root_path):
        raise ValueError("source_path must not traverse symlinks")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("source_path escapes project root") from exc
    if not resolved.exists():
        raise ValueError("source_path does not exist")
    if not resolved.is_file():
        raise ValueError("source_path must point to a file")
    return resolved


def _has_symlink_between(candidate: Path, root: Path) -> bool:
    current = candidate
    while True:
        if current.exists() and current.is_symlink():
            return True
        if current == root:
            return False
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_web_snapshot_url(source_url: str | None, *, allowed_url_hosts: tuple[str, ...]) -> str:
    raw = str(source_url or "").strip()
    if not raw:
        raise ValueError("source_url is required for HTML/web snapshot parsing")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("source_url must use https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("source_url must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("source_url must not include credentials")
    sensitive_url_text = f"{parsed.path}?{parsed.query}".lower()
    if any(marker in sensitive_url_text for marker in _SOURCE_URL_SECRET_MARKERS):
        raise ValueError("source_url must not include tokens, passwords, or secret query/path markers")
    allowed = tuple(str(item).strip().lower().lstrip(".") for item in allowed_url_hosts if str(item).strip())
    if not allowed:
        raise ValueError("allowed_url_hosts is required for HTML/web snapshot parsing")
    if not any(host == item or host.endswith(f".{item}") for item in allowed):
        raise ValueError("source_url host is not in allowed_url_hosts")
    return raw


class _VisibleHTMLTextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "caption",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001, ARG002
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and lowered in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth == 0 and lowered in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_snapshot_visible_text(html: str) -> str:
    parser = _VisibleHTMLTextExtractor()
    parser.feed(html)
    parser.close()
    visible = parser.text()
    visible = re.sub(r"[ \t\r\f\v]+", " ", visible)
    lines = [line.strip() for line in visible.splitlines()]
    collapsed_lines: list[str] = []
    last_blank = False
    for line in lines:
        if not line:
            if not last_blank:
                collapsed_lines.append("")
            last_blank = True
            continue
        collapsed_lines.append(line)
        last_blank = False
    text = "\n".join(collapsed_lines).strip()
    if not text:
        raise ValueError("HTML/web snapshot contains no parseable visible text")
    return text


def _local_document_blocks(text: str, *, source_hash: str, max_chars: int = 1_200) -> tuple[LocalDocumentBlock, ...]:
    return _local_document_blocks_for_page(text, source_hash=source_hash, page=1, max_chars=max_chars)


def _local_document_blocks_for_page(
    text: str,
    *,
    source_hash: str,
    page: int,
    max_chars: int = 1_200,
) -> tuple[LocalDocumentBlock, ...]:
    blocks: list[LocalDocumentBlock] = []
    current_lines: list[str] = []
    current_start: int | None = None
    offset = 0

    def flush(end_offset: int) -> None:
        nonlocal current_lines, current_start
        if current_start is None:
            return
        raw_block = "".join(current_lines)
        stripped = raw_block.strip()
        if stripped:
            block_start = current_start + (len(raw_block) - len(raw_block.lstrip()))
            block_end = end_offset - (len(raw_block) - len(raw_block.rstrip()))
            _append_block_chunks(
                blocks,
                stripped,
                source_hash=source_hash,
                page=page,
                char_start=block_start,
                char_end=block_end,
                max_chars=max_chars,
            )
        current_lines = []
        current_start = None

    for line in text.splitlines(keepends=True):
        if line.strip():
            if current_start is None:
                current_start = offset
            current_lines.append(line)
        else:
            flush(offset)
        offset += len(line)
    flush(len(text))

    if not blocks:
        raise ValueError("local document produced no evidence blocks")
    return tuple(blocks)


def _local_pdf_document_blocks(
    path: Path,
    *,
    source_hash: str,
    max_pages: int,
) -> tuple[str, tuple[LocalDocumentBlock, ...]]:
    try:
        return _local_pdf_layout_document_blocks(path, source_hash=source_hash, max_pages=max_pages)
    except ImportError:
        try:
            return _local_pdf_text_fallback_document_blocks(path, source_hash=source_hash, max_pages=max_pages)
        except ValueError as exc:
            if "no extractable text" in str(exc):
                return _local_pdf_ocr_document_blocks(path, source_hash=source_hash, max_pages=max_pages)
            raise
    except ValueError as exc:
        if "no extractable text" in str(exc):
            return _local_pdf_ocr_document_blocks(path, source_hash=source_hash, max_pages=max_pages)
        raise


def _local_pdf_layout_document_blocks(
    path: Path,
    *,
    source_hash: str,
    max_pages: int,
) -> tuple[str, tuple[LocalDocumentBlock, ...]]:
    try:
        import fitz
    except ImportError as exc:
        raise exc

    try:
        document = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001 - PDF parser errors vary by PyMuPDF version.
        raise ValueError("local PDF could not be parsed") from exc
    try:
        if getattr(document, "is_encrypted", False) or getattr(document, "needs_pass", False):
            raise ValueError("encrypted PDFs are not accepted by the local parser")
        page_count = int(getattr(document, "page_count", len(document)))
        if page_count > max_pages:
            raise ValueError("local PDF exceeds parser page limit")

        blocks: list[LocalDocumentBlock] = []
        for page_index in range(page_count):
            page = document.load_page(page_index)
            try:
                raw_blocks = page.get_text("blocks", sort=True) or []
            except Exception as exc:  # noqa: BLE001 - extraction errors vary by backend.
                raise ValueError(f"local PDF page {page_index + 1} layout extraction failed") from exc
            for raw_index, raw_block in enumerate(raw_blocks):
                if len(raw_block) < 5:
                    continue
                block_type = raw_block[6] if len(raw_block) > 6 else 0
                if block_type not in (0, "text"):
                    continue
                text = str(raw_block[4] or "")
                if not text.strip():
                    continue
                bbox = tuple(round(float(v), 2) for v in raw_block[:4])
                _append_block_chunks(
                    blocks,
                    text,
                    source_hash=f"{source_hash}:page:{page_index + 1}:layout_block:{raw_index}",
                    page=page_index + 1,
                    char_start=0,
                    char_end=len(text),
                    max_chars=1_200,
                    layout_bbox=bbox,  # type: ignore[arg-type]
                    layout_block_index=raw_index,
                    layout_kind="pdf_text_block",
                )
        if not blocks:
            raise ValueError("local PDF produced no extractable text")
        return _LOCAL_PDF_LAYOUT_PARSER_ID, tuple(blocks)
    finally:
        document.close()


def _local_pdf_text_fallback_document_blocks(
    path: Path,
    *,
    source_hash: str,
    max_pages: int,
) -> tuple[str, tuple[LocalDocumentBlock, ...]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency exists in the bundled runtime.
        raise ValueError("pypdf is required for local PDF text extraction") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - PDF parser errors vary by pypdf version.
        raise ValueError("local PDF could not be parsed") from exc
    if getattr(reader, "is_encrypted", False):
        raise ValueError("encrypted PDFs are not accepted by the local parser")
    if len(reader.pages) > max_pages:
        raise ValueError("local PDF exceeds parser page limit")

    blocks: list[LocalDocumentBlock] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - PDF extraction errors vary by backend.
            raise ValueError(f"local PDF page {index} text extraction failed") from exc
        if text.strip():
            blocks.extend(
                _local_document_blocks_for_page(
                    text,
                    source_hash=f"{source_hash}:page:{index}",
                    page=index,
                )
            )
    if not blocks:
        raise ValueError("local PDF produced no extractable text")
    return _LOCAL_PDF_TEXT_FALLBACK_PARSER_ID, tuple(blocks)


def _local_pdf_ocr_document_blocks(
    path: Path,
    *,
    source_hash: str,
    max_pages: int,
) -> tuple[str, tuple[LocalDocumentBlock, ...]]:
    if not shutil.which("tesseract"):
        raise ValueError("tesseract is required for local PDF OCR extraction")
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency exists in the bundled runtime.
        raise ValueError("PyMuPDF is required for local PDF OCR rendering") from exc

    try:
        document = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001 - PDF parser errors vary by PyMuPDF version.
        raise ValueError("local PDF could not be parsed for OCR") from exc
    try:
        if getattr(document, "is_encrypted", False) or getattr(document, "needs_pass", False):
            raise ValueError("encrypted PDFs are not accepted by the local parser")
        page_count = int(getattr(document, "page_count", len(document)))
        if page_count > max_pages:
            raise ValueError("local PDF exceeds parser page limit")

        blocks: list[LocalDocumentBlock] = []
        with tempfile.TemporaryDirectory(prefix="qbt-doc-ocr-") as temp_dir:
            temp_root = Path(temp_dir)
            for page_index in range(page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = temp_root / f"page-{page_index + 1}.png"
                pixmap.save(str(image_path))
                text = _run_tesseract_ocr(image_path)
                if not text.strip():
                    continue
                rect = page.rect
                _append_block_chunks(
                    blocks,
                    text,
                    source_hash=f"{source_hash}:page:{page_index + 1}:ocr",
                    page=page_index + 1,
                    char_start=0,
                    char_end=len(text),
                    max_chars=1_200,
                    layout_bbox=(0.0, 0.0, round(float(rect.width), 2), round(float(rect.height), 2)),
                    layout_block_index=0,
                    layout_kind="pdf_ocr_page",
                )
        if not blocks:
            raise ValueError("local PDF OCR produced no extractable text")
        return _LOCAL_PDF_OCR_PARSER_ID, tuple(blocks)
    finally:
        document.close()


def _run_tesseract_ocr(image_path: Path) -> str:
    command = ["tesseract", str(image_path), "stdout", "--psm", "6"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("local PDF OCR timed out") from exc
    if completed.returncode != 0:
        raise ValueError("local PDF OCR failed")
    return completed.stdout


def _append_block_chunks(
    blocks: list[LocalDocumentBlock],
    text: str,
    *,
    source_hash: str,
    page: int,
    char_start: int,
    char_end: int,
    max_chars: int,
    layout_bbox: tuple[float, float, float, float] | None = None,
    layout_block_index: int | None = None,
    layout_kind: str | None = None,
) -> None:
    chunk_start = 0
    while chunk_start < len(text):
        chunk = text[chunk_start: chunk_start + max_chars].strip()
        if chunk:
            absolute_start = char_start + chunk_start
            absolute_end = min(char_start + chunk_start + len(chunk), char_end)
            quoted_hash = _sha256_text(chunk)
            blocks.append(
                LocalDocumentBlock(
                    block_id="block:" + content_hash(
                        {
                            "source_hash": source_hash,
                            "index": len(blocks),
                            "char_start": absolute_start,
                            "char_end": absolute_end,
                            "quoted_excerpt_hash": quoted_hash,
                            "layout_bbox": layout_bbox,
                            "layout_block_index": layout_block_index,
                            "layout_kind": layout_kind,
                        }
                    ),
                    page=page,
                    section=_section_label(chunk),
                    char_start=absolute_start,
                    char_end=absolute_end,
                    text=chunk,
                    quoted_excerpt_hash=quoted_hash,
                    layout_bbox=layout_bbox,
                    layout_block_index=layout_block_index,
                    layout_kind=layout_kind,
                )
            )
        chunk_start += max_chars


def _section_label(text: str) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if first_line.startswith("#"):
        label = first_line.lstrip("#").strip()
        if label:
            return label[:120]
    return first_line[:120]


_EVENT_RECORD_TYPES: dict[str, tuple[str, type[Any]]] = {
    "source_intake_recorded": ("source", SourceDocumentIntakeRecord),
    "evidence_span_recorded": ("span", EvidenceSpanRecord),
    "extracted_claim_recorded": ("claim", ExtractedResearchClaim),
    "privileged_tool_request_recorded": ("tool_request", PrivilegedToolUseRequest),
}


def _event_row(event_type: str, field_name: str, record: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_type": event_type,
        field_name: _json_value(record),
    }


def _require_record_ref(field_name: str, value: str | None) -> None:
    if not _present(value):
        raise ValueError(f"{field_name} is required")


class PersistentDocumentIntelligenceStore:
    """Append-only JSONL store for schema-constrained document evidence records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sources: dict[str, SourceDocumentIntakeRecord] = {}
        self._spans: dict[str, EvidenceSpanRecord] = {}
        self._claims: dict[str, ExtractedResearchClaim] = {}
        self._tool_requests: dict[str, PrivilegedToolUseRequest] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - startup must expose the bad row.
                    raise ValueError(f"invalid persisted Document Intelligence row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported Document Intelligence schema_version")
        event_type = str(row.get("event_type") or "")
        spec = _EVENT_RECORD_TYPES.get(event_type)
        if spec is None:
            raise ValueError(f"unknown Document Intelligence event_type={event_type!r}")
        field_name, record_type = spec
        raw = row.get(field_name)
        if not isinstance(raw, dict):
            raise ValueError(f"Document Intelligence event missing {field_name}")
        record = record_type(**raw)
        if isinstance(record, SourceDocumentIntakeRecord):
            self._record_source(record, persist=persist)
        elif isinstance(record, EvidenceSpanRecord):
            self._record_span(record, persist=persist)
        elif isinstance(record, ExtractedResearchClaim):
            self._record_claim(record, persist=persist)
        elif isinstance(record, PrivilegedToolUseRequest):
            self._record_tool_request(record, persist=persist)
        else:
            raise ValueError(f"unsupported Document Intelligence record type {type(record).__name__}")

    def record_source(self, source: SourceDocumentIntakeRecord) -> SourceDocumentIntakeRecord:
        return self._record_source(source, persist=True)

    def _record_source(self, source: SourceDocumentIntakeRecord, *, persist: bool) -> SourceDocumentIntakeRecord:
        _require_record_ref("source_ref", source.source_ref)
        decision = validate_source_document_intake(source)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._sources[source.source_ref] = source
        if persist:
            self._append_event(_event_row("source_intake_recorded", "source", source))
        return source

    def record_span(self, span: EvidenceSpanRecord) -> EvidenceSpanRecord:
        return self._record_span(span, persist=True)

    def _record_span(self, span: EvidenceSpanRecord, *, persist: bool) -> EvidenceSpanRecord:
        _require_record_ref("span_ref", span.span_ref)
        decision = validate_evidence_span(span)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        if span.source_id not in self._sources:
            raise ValueError(f"EvidenceSpan source_id {span.source_id!r} is not recorded")
        self._spans[span.span_ref] = span
        if persist:
            self._append_event(_event_row("evidence_span_recorded", "span", span))
        return span

    def record_claim(self, claim: ExtractedResearchClaim) -> ExtractedResearchClaim:
        return self._record_claim(claim, persist=True)

    def _record_claim(self, claim: ExtractedResearchClaim, *, persist: bool) -> ExtractedResearchClaim:
        _require_record_ref("claim_ref", claim.claim_ref)
        decision = validate_extracted_claim(claim, spans=tuple(self._spans.values()))
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._claims[claim.claim_ref] = claim
        if persist:
            self._append_event(_event_row("extracted_claim_recorded", "claim", claim))
        return claim

    def record_tool_request(self, request: PrivilegedToolUseRequest) -> PrivilegedToolUseRequest:
        return self._record_tool_request(request, persist=True)

    def _record_tool_request(
        self,
        request: PrivilegedToolUseRequest,
        *,
        persist: bool,
    ) -> PrivilegedToolUseRequest:
        _require_record_ref("request_ref", request.request_ref)
        decision = validate_privileged_tool_use(request)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        if request.source_document_ref not in self._sources:
            raise ValueError(f"tool request source_document_ref {request.source_document_ref!r} is not recorded")
        self._tool_requests[request.request_ref] = request
        if persist:
            self._append_event(_event_row("privileged_tool_request_recorded", "tool_request", request))
        return request

    def source(self, source_ref: str) -> SourceDocumentIntakeRecord:
        return self._sources[source_ref]

    def span(self, span_ref: str) -> EvidenceSpanRecord:
        return self._spans[span_ref]

    def claim(self, claim_ref: str) -> ExtractedResearchClaim:
        return self._claims[claim_ref]

    def tool_request(self, request_ref: str) -> PrivilegedToolUseRequest:
        return self._tool_requests[request_ref]

    def sources(self) -> list[SourceDocumentIntakeRecord]:
        return list(self._sources.values())

    def spans(self) -> list[EvidenceSpanRecord]:
        return list(self._spans.values())

    def claims(self) -> list[ExtractedResearchClaim]:
        return list(self._claims.values())

    def tool_requests(self) -> list[PrivilegedToolUseRequest]:
        return list(self._tool_requests.values())


def _decision_message(decision: DocumentIntelligenceDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "document intelligence rejected"


__all__ = [
    "DocumentIntelligenceDecision",
    "DocumentIntelligenceViolation",
    "EvidenceSpanRecord",
    "ExtractedResearchClaim",
    "LocalDocumentBlock",
    "LocalDocumentParseResult",
    "PersistentDocumentIntelligenceStore",
    "PrivilegedToolUseRequest",
    "SourceDocumentIntakeRecord",
    "parse_local_document",
    "parse_local_text_document",
    "validate_document_intelligence",
    "validate_evidence_span",
    "validate_extracted_claim",
    "validate_privileged_tool_use",
    "validate_source_document_intake",
]
