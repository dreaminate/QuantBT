"""Durable source selections for server-derived GOAL section 14 rows.

This ledger never creates platform capability evidence.  It selects one
already-persisted, strictly backed section-14 entrypoint lineage and one current
RAG document whose metadata identifies the real upstream objects for a row.
An injected source resolver must read every referenced object from its typed
store and return a content-bound state.  Recording and every later lookup run
that resolver twice; missing getters, drift, recombination, or stale coverage
fail closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol

from ..cross_process_lock import acquire_exclusive_fd
from .goal_coverage import strict_current_entrypoint_coverage
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REQUIRED_REFS,
    PlatformCapabilityRecord,
    PlatformSpecificRef,
    platform_capability_record_from_dict,
    platform_capability_record_to_dict,
    validate_platform_capability,
)
from .platform_row_producers import (
    PlatformRowProductionError,
    PlatformRowSourceState,
    ResolvedPlatformRow,
    resolved_platform_row,
    validate_resolved_platform_row,
)
from .ref_resolution import is_placeholder_ref


PLATFORM_ROW_SOURCE_SCHEMA_VERSION = 1
PLATFORM_ROW_SOURCE_CERTIFICATION_VERSION = "platform_row_source_certification.v1"
_EVENT_TYPE = "platform_row_source_certified"
_METADATA_KEY = "platform_capability"
_RESERVED_SOURCE_ID_PREFIX = "platform_source_lineage:"
_RESERVED_SOURCE_KIND = "server_derived_platform_source_lineage"
_RESERVED_SOURCE_VERSION_PREFIX = "platform_source_lineage.v1."


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(child) for child in value]
    return value


def _content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner or owner != value or any(ord(char) < 32 for char in owner):
        raise ValueError("owner_user_id must be a stable non-empty exact string")
    if is_placeholder_ref(owner):
        raise ValueError("owner_user_id cannot contain placeholder material")
    return owner


def _row(value: Any) -> str:
    row = _text(getattr(value, "value", value))
    if row not in REQUIRED_PLATFORM_ROWS:
        raise ValueError("m_row is not a canonical platform row")
    return row


def _valid_sha256(value: Any) -> bool:
    token = _text(value).lower()
    return (
        token.startswith("sha256:")
        and len(token) == 71
        and all(char in "0123456789abcdef" for char in token[7:])
    )


def _enum_text(value: Any) -> str:
    return _text(getattr(value, "value", value))


class PlatformRowSourceError(PlatformRowProductionError):
    """A real current source selection could not be certified or resolved."""


class PlatformRowSourceCommitUncertain(PlatformRowSourceError):
    """A source event was replaced but durable rollback could not be proved."""


class PlatformTypedSourceResolver(Protocol):
    """Read one exact current object from a typed store and hash its payload."""

    def resolve_state(
        self,
        field: str,
        ref: str,
        *,
        owner_user_id: str,
        record: PlatformCapabilityRecord,
    ) -> PlatformRowSourceState: ...

    def linkage_violations(
        self,
        record: PlatformCapabilityRecord,
        *,
        owner_user_id: str,
        source_coverage: Any,
        rag_document: Any,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class PlatformRowSourceCertification:
    certification_ref: str
    owner_user_id: str
    m_row: str
    row_revision: int
    previous_certification_ref: str
    source_coverage_ref: str
    rag_ref: str
    resolved_row: ResolvedPlatformRow
    certification_version: str = PLATFORM_ROW_SOURCE_CERTIFICATION_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "certification_ref",
            "owner_user_id",
            "m_row",
            "previous_certification_ref",
            "source_coverage_ref",
            "rag_ref",
            "certification_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))

    @property
    def canonical_certification_ref(self) -> str:
        return "platform_row_source_certification:" + hashlib.sha256(
            _canonical_json(
                {
                    "owner_user_id": self.owner_user_id,
                    "m_row": self.m_row,
                    "row_revision": self.row_revision,
                    "previous_certification_ref": self.previous_certification_ref,
                    "source_coverage_ref": self.source_coverage_ref,
                    "rag_ref": self.rag_ref,
                    "resolved_row": _resolved_row_to_dict(self.resolved_row),
                    "certification_version": self.certification_version,
                }
            ).encode("utf-8")
        ).hexdigest()


def _source_state_to_dict(state: PlatformRowSourceState) -> dict[str, str]:
    return asdict(state)


def _source_state_from_dict(value: Any) -> PlatformRowSourceState:
    if not isinstance(value, dict) or set(value) != {
        "source_kind",
        "source_ref",
        "state_hash",
    }:
        raise ValueError("platform row source state has an inexact schema")
    return PlatformRowSourceState(**value)


def _resolved_row_to_dict(value: ResolvedPlatformRow) -> dict[str, Any]:
    return {
        "production_ref": value.production_ref,
        "owner_user_id": value.owner_user_id,
        "m_row": value.m_row,
        "producer_ref": value.producer_ref,
        "record": platform_capability_record_to_dict(value.record),
        "source_states": [_source_state_to_dict(item) for item in value.source_states],
    }


def _resolved_row_from_dict(value: Any) -> ResolvedPlatformRow:
    expected = {
        "production_ref",
        "owner_user_id",
        "m_row",
        "producer_ref",
        "record",
        "source_states",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("resolved platform row has an inexact schema")
    if not isinstance(value["record"], dict) or not isinstance(
        value["source_states"], list
    ):
        raise ValueError("resolved platform row payload is invalid")
    return ResolvedPlatformRow(
        production_ref=value["production_ref"],
        owner_user_id=value["owner_user_id"],
        m_row=value["m_row"],
        producer_ref=value["producer_ref"],
        record=platform_capability_record_from_dict(value["record"]),
        source_states=tuple(
            _source_state_from_dict(item) for item in value["source_states"]
        ),
    )


def _certification_to_dict(value: PlatformRowSourceCertification) -> dict[str, Any]:
    return {
        "certification_ref": value.certification_ref,
        "owner_user_id": value.owner_user_id,
        "m_row": value.m_row,
        "row_revision": value.row_revision,
        "previous_certification_ref": value.previous_certification_ref,
        "source_coverage_ref": value.source_coverage_ref,
        "rag_ref": value.rag_ref,
        "resolved_row": _resolved_row_to_dict(value.resolved_row),
        "certification_version": value.certification_version,
    }


def _certification_from_dict(value: Any) -> PlatformRowSourceCertification:
    expected = {
        "certification_ref",
        "owner_user_id",
        "m_row",
        "row_revision",
        "previous_certification_ref",
        "source_coverage_ref",
        "rag_ref",
        "resolved_row",
        "certification_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("platform row source certification has an inexact schema")
    return PlatformRowSourceCertification(
        certification_ref=value["certification_ref"],
        owner_user_id=value["owner_user_id"],
        m_row=value["m_row"],
        row_revision=value["row_revision"],
        previous_certification_ref=value["previous_certification_ref"],
        source_coverage_ref=value["source_coverage_ref"],
        rag_ref=value["rag_ref"],
        resolved_row=_resolved_row_from_dict(value["resolved_row"]),
        certification_version=value["certification_version"],
    )


def _validate_certification(value: PlatformRowSourceCertification) -> None:
    owner = _owner(value.owner_user_id)
    row = _row(value.m_row)
    if value.certification_version != PLATFORM_ROW_SOURCE_CERTIFICATION_VERSION:
        raise ValueError("platform row source certification version is unsupported")
    if type(value.row_revision) is not int or value.row_revision <= 0:
        raise ValueError("platform row source row_revision must be positive")
    if (value.row_revision == 1) != (not value.previous_certification_ref):
        raise ValueError("platform row source previous certification chain is invalid")
    if not value.source_coverage_ref or not value.rag_ref:
        raise ValueError("platform row source coverage and RAG refs are required")
    if is_placeholder_ref(value.source_coverage_ref) or is_placeholder_ref(value.rag_ref):
        raise ValueError("platform row source refs cannot contain placeholder material")
    violations = validate_resolved_platform_row(
        value.resolved_row,
        owner_user_id=owner,
        m_row=row,
    )
    if violations:
        raise ValueError(";".join(violations))
    if value.certification_ref != value.canonical_certification_ref:
        raise ValueError("platform row source certification identity mismatch")


def _apply_journal_row_to_projection(
    row: Any,
    *,
    records: dict[tuple[str, str], PlatformRowSourceCertification],
    heads: dict[tuple[str, str], PlatformRowSourceCertification],
    last_ledger_revision: int,
    last_record_hash: str,
) -> tuple[int, str]:
    """Validate one event and advance a caller-owned journal projection."""

    expected = {
        "schema_version",
        "event_type",
        "ledger_revision",
        "previous_record_hash",
        "owner_user_id",
        "m_row",
        "row_revision",
        "certification",
        "record_hash",
    }
    if not isinstance(row, dict) or set(row) != expected:
        raise ValueError("platform row source event has an inexact schema")
    if (
        row["schema_version"] != PLATFORM_ROW_SOURCE_SCHEMA_VERSION
        or row["event_type"] != _EVENT_TYPE
    ):
        raise ValueError("platform row source event version/type is unsupported")
    ledger_revision = row["ledger_revision"]
    if type(ledger_revision) is not int or ledger_revision != last_ledger_revision + 1:
        raise ValueError("platform row source ledger revision is discontinuous")
    if row["previous_record_hash"] != last_record_hash:
        raise ValueError("platform row source previous record hash mismatch")
    body = {key: value for key, value in row.items() if key != "record_hash"}
    expected_hash = _content_hash(body)
    if row["record_hash"] != expected_hash:
        raise ValueError("platform row source record hash mismatch")
    certification = _certification_from_dict(row["certification"])
    _validate_certification(certification)
    owner = _owner(row["owner_user_id"])
    m_row = _row(row["m_row"])
    key = (owner, m_row)
    previous = heads.get(key)
    expected_revision = 1 if previous is None else previous.row_revision + 1
    if (
        certification.owner_user_id != owner
        or certification.m_row != m_row
        or row["row_revision"] != expected_revision
        or certification.row_revision != expected_revision
        or certification.previous_certification_ref
        != ("" if previous is None else previous.certification_ref)
    ):
        raise ValueError("platform row source owner/row revision chain mismatch")
    record_key = (owner, certification.certification_ref)
    existing = records.get(record_key)
    if existing is not None and existing != certification:
        raise ValueError("platform row source certification identity collision")
    records[record_key] = certification
    heads[key] = certification
    return ledger_revision, expected_hash


class PersistentPlatformRowSourceRegistry:
    """Hash-chained source selections that re-resolve every current object."""

    def __init__(
        self,
        path: str | Path,
        *,
        entrypoint_registry: Any,
        rag_index: Any,
        source_resolver: PlatformTypedSourceResolver,
    ) -> None:
        if not callable(getattr(source_resolver, "resolve_state", None)):
            raise TypeError("source_resolver.resolve_state is required")
        if not callable(getattr(source_resolver, "linkage_violations", None)):
            raise TypeError("source_resolver.linkage_violations is required")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._entrypoints = entrypoint_registry
        entrypoint_path = getattr(entrypoint_registry, "path", None)
        self._proof_head_ledger_path = (
            None
            if entrypoint_path is None
            else Path(entrypoint_path).expanduser().absolute()
        )
        self._rag = rag_index
        self._resolver = source_resolver
        self._thread_lock = threading.RLock()
        self._records: dict[tuple[str, str], PlatformRowSourceCertification] = {}
        self._heads: dict[tuple[str, str], PlatformRowSourceCertification] = {}
        self._last_ledger_revision = 0
        self._last_record_hash = ""
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @contextmanager
    def _proof_head_boundary(self) -> Iterator[None]:
        """Take the composed GOAL proof head before the row-source journal."""

        if self._proof_head_ledger_path is None:
            yield
            return
        with acquire_goal_proof_head_lock(self._proof_head_ledger_path):
            yield

    def _reset(self) -> None:
        self._records = {}
        self._heads = {}
        self._last_ledger_revision = 0
        self._last_record_hash = ""

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        for line_no, line in enumerate(
            self._path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                self._apply_row(row)
            except Exception as exc:
                raise ValueError(
                    f"invalid persisted platform row source at {self._path}:{line_no}"
                ) from exc

    def _apply_row(self, row: Any) -> None:
        self._last_ledger_revision, self._last_record_hash = (
            _apply_journal_row_to_projection(
                row,
                records=self._records,
                heads=self._heads,
                last_ledger_revision=self._last_ledger_revision,
                last_record_hash=self._last_record_hash,
            )
        )

    def resolve_current_rows_from_journal_unlocked(
        self,
        owner_user_id: str,
        registered_records: tuple[PlatformCapabilityRecord, ...],
    ) -> tuple[ResolvedPlatformRow, ...]:
        """Read exact certified heads without taking locks or resolving typed stores.

        The platform-closure commit path calls this only while it already holds
        the shared GOAL proof-head lock plus the platform and RDP journal locks.
        Taking this registry's public lock there can deadlock with a concurrent
        typed-source reader that holds the row-source lock and is waiting for
        the RDP lock.  The shared proof-head lock excludes row-source writers,
        so a complete hash-chain parse is the lock-safe disk-current projection.
        """

        owner = _owner(owner_user_id)
        if not isinstance(registered_records, tuple) or any(
            not isinstance(record, PlatformCapabilityRecord)
            for record in registered_records
        ):
            raise TypeError(
                "registered_records must be tuple[PlatformCapabilityRecord, ...]"
            )
        if not self._path.exists():
            raise PlatformRowSourceError("platform row source journal is absent")
        records: dict[tuple[str, str], PlatformRowSourceCertification] = {}
        heads: dict[tuple[str, str], PlatformRowSourceCertification] = {}
        last_ledger_revision = 0
        last_record_hash = ""
        for line_no, line in enumerate(
            self._path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                last_ledger_revision, last_record_hash = (
                    _apply_journal_row_to_projection(
                        row,
                        records=records,
                        heads=heads,
                        last_ledger_revision=last_ledger_revision,
                        last_record_hash=last_record_hash,
                    )
                )
            except Exception as exc:
                raise PlatformRowSourceError(
                    f"invalid persisted platform row source at {self._path}:{line_no}"
                ) from exc
        missing = tuple(
            row for row in REQUIRED_PLATFORM_ROWS if (owner, row) not in heads
        )
        if missing:
            raise PlatformRowSourceError(
                "platform row source journal is missing certified rows: "
                + ",".join(missing)
            )
        resolved_rows = tuple(
            heads[(owner, row)].resolved_row for row in REQUIRED_PLATFORM_ROWS
        )
        if tuple(item.record for item in resolved_rows) != registered_records:
            raise PlatformRowSourceError(
                "certified platform rows do not match the disk-current platform manifest"
            )
        return resolved_rows

    @staticmethod
    def _coverage_sections(coverage: Any) -> tuple[str, ...]:
        return tuple(_enum_text(item) for item in getattr(coverage, "goal_sections", ()))

    def _derive(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        source_coverage_ref: str,
        rag_ref: str,
    ) -> ResolvedPlatformRow:
        owner = _owner(owner_user_id)
        row = _row(m_row)
        coverage_ref = _text(source_coverage_ref)
        rag_document_ref = _text(rag_ref)
        if not coverage_ref or not rag_document_ref:
            raise PlatformRowSourceError("source coverage and RAG refs are required")
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoints,
                coverage_ref,
                owner=owner,
            )
            backing = self._entrypoints.validate_real_backing(coverage)
        except Exception as exc:
            raise PlatformRowSourceError(
                f"platform row source coverage could not be resolved: {type(exc).__name__}"
            ) from exc
        if not bool(getattr(backing, "accepted", False)):
            raise PlatformRowSourceError("platform row source coverage is not strictly backed")
        if (
            _text(getattr(coverage, "recorded_by", "")) != owner
            or "§14" not in self._coverage_sections(coverage)
            or bool(getattr(coverage, "silent_mock_fallback_used", False))
            or bool(getattr(coverage, "raw_payload_persisted", False))
        ):
            raise PlatformRowSourceError("platform row source coverage policy is invalid")
        qro_refs = tuple(_text(ref) for ref in getattr(coverage, "qro_refs", ()))
        graph_refs = tuple(
            _text(ref)
            for ref in getattr(coverage, "research_graph_command_refs", ())
        )
        lifecycle_refs = tuple(
            _text(ref) for ref in getattr(coverage, "lifecycle_refs", ())
        )
        validation_refs = tuple(
            _text(ref) for ref in getattr(coverage, "validation_refs", ())
        )
        evidence_refs = tuple(
            _text(ref) for ref in getattr(coverage, "evidence_refs", ())
        )
        governance_refs = tuple(
            ref for ref in validation_refs if ref.startswith("goal_validation_receipt:")
        )
        if (
            len(qro_refs) != 1
            or len(graph_refs) != 1
            or len(lifecycle_refs) != 1
            or len(governance_refs) != 1
            or len(governance_refs) != len(set(governance_refs))
            or not evidence_refs
            or len(evidence_refs) != len(set(evidence_refs))
        ):
            raise PlatformRowSourceError(
                "platform row source coverage must bind one QRO, graph, lifecycle, "
                "GOAL receipt, and a unique evidence set"
            )
        try:
            rag_document = self._rag.document_for_owner(
                rag_document_ref,
                owner_user_id=owner,
                require_current=True,
            )
        except Exception as exc:
            raise PlatformRowSourceError(
                f"platform row RAG document could not be resolved: {type(exc).__name__}"
            ) from exc
        if (
            _text(getattr(rag_document, "source_id", ""))
            != f"{_RESERVED_SOURCE_ID_PREFIX}{row}"
            or _text(getattr(rag_document, "source_kind", ""))
            != _RESERVED_SOURCE_KIND
            or not _text(getattr(rag_document, "version", "")).startswith(
                _RESERVED_SOURCE_VERSION_PREFIX
            )
            or _enum_text(getattr(rag_document, "projection", "")) != "research"
            or _text(getattr(rag_document, "evidence_label", ""))
            != "candidate_context"
        ):
            raise PlatformRowSourceError(
                "platform row RAG document lacks reserved server-derived provenance"
            )
        permission = getattr(rag_document, "permission", None)
        if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
            raise PlatformRowSourceError("platform row RAG document owner permission is absent")
        if "platform_source_lineage" not in tuple(
            getattr(permission, "permission_tags", ()) or ()
        ):
            raise PlatformRowSourceError(
                "platform row RAG document lacks source-lineage permission provenance"
            )
        metadata = getattr(rag_document, "metadata", None)
        capability = metadata.get(_METADATA_KEY) if isinstance(metadata, dict) else None
        expected_metadata = {
            "schema_version",
            "m_row",
            "source_coverage_ref",
            "qro_ref",
            "research_graph_ref",
            "lifecycle_ref",
            "governance_ref",
            "math_spine_ref",
            "evidence_refs",
            "specific_refs",
        }
        if not isinstance(capability, dict) or set(capability) != expected_metadata:
            raise PlatformRowSourceError("platform row RAG metadata has an inexact schema")
        specifics = capability["specific_refs"]
        if not isinstance(specifics, dict) or set(specifics) != set(
            SPECIFIC_REQUIRED_REFS[row]
        ):
            raise PlatformRowSourceError("platform row RAG specific refs are inexact")
        expected_values = {
            "schema_version": 1,
            "m_row": row,
            "source_coverage_ref": coverage_ref,
            "qro_ref": qro_refs[0],
            "research_graph_ref": graph_refs[0],
            "lifecycle_ref": lifecycle_refs[0],
            "governance_ref": governance_refs[0],
            "evidence_refs": list(evidence_refs),
        }
        for key, expected in expected_values.items():
            if capability.get(key) != expected:
                raise PlatformRowSourceError(
                    f"platform row RAG metadata {key} does not match source coverage"
                )
        math_spine_ref = _text(capability.get("math_spine_ref"))
        if not math_spine_ref:
            raise PlatformRowSourceError("platform row math spine ref is required")
        record = PlatformCapabilityRecord(
            m_row=row,
            qro_ref=qro_refs[0],
            research_graph_ref=graph_refs[0],
            lifecycle_ref=lifecycle_refs[0],
            governance_ref=governance_refs[0],
            rag_ref=rag_document_ref,
            math_spine_ref=math_spine_ref,
            evidence_refs=evidence_refs,
            specific_refs=tuple(
                PlatformSpecificRef(key=key, ref=_text(specifics[key]))
                for key in SPECIFIC_REQUIRED_REFS[row]
            ),
        )
        shape = validate_platform_capability(record)
        if not shape.accepted:
            raise PlatformRowSourceError(
                ";".join(f"{item.code}:{item.field}" for item in shape.violations)
            )
        fields_and_refs = (
            ("qro_ref", _text(record.qro_ref)),
            ("research_graph_ref", _text(record.research_graph_ref)),
            ("lifecycle_ref", _text(record.lifecycle_ref)),
            ("governance_ref", _text(record.governance_ref)),
            ("rag_ref", _text(record.rag_ref)),
            ("math_spine_ref", _text(record.math_spine_ref)),
            *(("evidence_ref", ref) for ref in record.evidence_refs),
            *((item.key, item.ref) for item in record.specific_refs),
        )
        source_states: list[PlatformRowSourceState] = []
        for field, ref in fields_and_refs:
            try:
                state = self._resolver.resolve_state(
                    field,
                    ref,
                    owner_user_id=owner,
                    record=record,
                )
            except Exception as exc:
                raise PlatformRowSourceError(
                    f"platform typed source {field} could not be resolved: "
                    f"{type(exc).__name__}"
                ) from exc
            if not isinstance(state, PlatformRowSourceState) or state.source_ref != ref:
                raise PlatformRowSourceError(
                    f"platform typed source {field} returned an invalid state"
                )
            source_states.append(state)
        coverage_state = PlatformRowSourceState(
            source_kind="goal_entrypoint_coverage",
            source_ref=coverage_ref,
            state_hash=_content_hash(_jsonable(coverage)),
        )
        if not _valid_sha256(coverage_state.state_hash):
            raise PlatformRowSourceError("platform coverage state hash is invalid")
        source_states.append(coverage_state)
        linkage = tuple(
            self._resolver.linkage_violations(
                record,
                owner_user_id=owner,
                source_coverage=coverage,
                rag_document=rag_document,
            )
            or ()
        )
        if linkage:
            raise PlatformRowSourceError(";".join(_text(item) for item in linkage))
        resolved = resolved_platform_row(
            owner_user_id=owner,
            m_row=row,
            producer_ref=f"platform_row_source_registry:{row}:v1",
            record=record,
            source_states=tuple(source_states),
        )
        violations = validate_resolved_platform_row(
            resolved,
            owner_user_id=owner,
            m_row=row,
        )
        if violations:
            raise PlatformRowSourceError(";".join(violations))
        return resolved

    def _resolve_twice(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        source_coverage_ref: str,
        rag_ref: str,
    ) -> ResolvedPlatformRow:
        first = self._derive(
            owner_user_id=owner_user_id,
            m_row=m_row,
            source_coverage_ref=source_coverage_ref,
            rag_ref=rag_ref,
        )
        second = self._derive(
            owner_user_id=owner_user_id,
            m_row=m_row,
            source_coverage_ref=source_coverage_ref,
            rag_ref=rag_ref,
        )
        if first != second:
            raise PlatformRowSourceError(
                "platform row typed sources changed during resolution"
            )
        return first

    def record_current(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        source_coverage_ref: str,
        rag_ref: str,
    ) -> PlatformRowSourceCertification:
        with self._proof_head_boundary():
            return self._record_current_under_proof_head(
                owner_user_id=owner_user_id,
                m_row=m_row,
                source_coverage_ref=source_coverage_ref,
                rag_ref=rag_ref,
            )

    def _record_current_under_proof_head(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        source_coverage_ref: str,
        rag_ref: str,
    ) -> PlatformRowSourceCertification:
        owner = _owner(owner_user_id)
        row = _row(m_row)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            resolved = self._resolve_twice(
                owner_user_id=owner,
                m_row=row,
                source_coverage_ref=source_coverage_ref,
                rag_ref=rag_ref,
            )
            previous = self._heads.get((owner, row))
            if (
                previous is not None
                and previous.source_coverage_ref == _text(source_coverage_ref)
                and previous.rag_ref == _text(rag_ref)
                and previous.resolved_row == resolved
            ):
                return previous
            revision = 1 if previous is None else previous.row_revision + 1
            previous_ref = "" if previous is None else previous.certification_ref
            blank = PlatformRowSourceCertification(
                certification_ref="",
                owner_user_id=owner,
                m_row=row,
                row_revision=revision,
                previous_certification_ref=previous_ref,
                source_coverage_ref=_text(source_coverage_ref),
                rag_ref=_text(rag_ref),
                resolved_row=resolved,
            )
            certification = PlatformRowSourceCertification(
                certification_ref=blank.canonical_certification_ref,
                owner_user_id=owner,
                m_row=row,
                row_revision=revision,
                previous_certification_ref=previous_ref,
                source_coverage_ref=blank.source_coverage_ref,
                rag_ref=blank.rag_ref,
                resolved_row=resolved,
            )
            _validate_certification(certification)
            body = {
                "schema_version": PLATFORM_ROW_SOURCE_SCHEMA_VERSION,
                "event_type": _EVENT_TYPE,
                "ledger_revision": self._last_ledger_revision + 1,
                "previous_record_hash": self._last_record_hash,
                "owner_user_id": owner,
                "m_row": row,
                "row_revision": revision,
                "certification": _certification_to_dict(certification),
            }
            event = {**body, "record_hash": _content_hash(body)}
            self._atomic_append(event)
            self._apply_row(event)
            return certification

    def certification(
        self,
        certification_ref: str,
        *,
        owner_user_id: str,
    ) -> PlatformRowSourceCertification:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._records[(owner, _text(certification_ref))]
            except KeyError:
                raise KeyError(
                    "platform row source certification is not recorded for owner"
                ) from None

    def current_certifications(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[PlatformRowSourceCertification, ...]:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return tuple(
                self._heads[(owner, row)]
                for row in REQUIRED_PLATFORM_ROWS
                if (owner, row) in self._heads
            )

    def resolve_current_row(
        self,
        m_row: str,
        *,
        owner_user_id: str,
    ) -> ResolvedPlatformRow:
        owner = _owner(owner_user_id)
        row = _row(m_row)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                certification = self._heads[(owner, row)]
            except KeyError:
                raise PlatformRowSourceError(
                    f"platform row source certification is unavailable for {row}"
                ) from None
            resolved = self._resolve_twice(
                owner_user_id=owner,
                m_row=row,
                source_coverage_ref=certification.source_coverage_ref,
                rag_ref=certification.rag_ref,
            )
            if resolved != certification.resolved_row:
                raise PlatformRowSourceError(
                    f"platform row source certification drifted for {row}"
                )
            return resolved

    def source_coverage_ref(
        self,
        m_row: str,
        *,
        owner_user_id: str,
    ) -> str:
        owner = _owner(owner_user_id)
        row = _row(m_row)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._heads[(owner, row)].source_coverage_ref
            except KeyError:
                raise KeyError(
                    f"platform row source certification is unavailable for {row}"
                ) from None

    def _atomic_append(self, row: dict[str, Any]) -> None:
        original_exists = self._path.exists()
        original = self._path.read_bytes() if original_exists else b""
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        payload = original + separator + (_canonical_json(row) + "\n").encode("utf-8")
        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            dir=self._path.parent,
        )
        temp = Path(raw_temp)
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            fd = -1
            os.replace(temp, self._path)
            replaced = True
            self._fsync_parent()
        except Exception as exc:
            if replaced:
                try:
                    self._restore(original_exists=original_exists, original=original)
                except Exception as recovery_exc:
                    raise PlatformRowSourceCommitUncertain(
                        "platform row source append failed and rollback is uncertain"
                    ) from recovery_exc
            raise exc
        finally:
            if fd >= 0:
                os.close(fd)
            temp.unlink(missing_ok=True)

    def _restore(self, *, original_exists: bool, original: bytes) -> None:
        if not original_exists:
            self._path.unlink(missing_ok=True)
            self._fsync_parent()
            return
        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{self._path.name}.restore.",
            dir=self._path.parent,
        )
        temp = Path(raw_temp)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            fd = -1
            os.replace(temp, self._path)
            self._fsync_parent()
        finally:
            if fd >= 0:
                os.close(fd)
            temp.unlink(missing_ok=True)

    def _fsync_parent(self) -> None:
        fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def register_platform_row_source_producers(
    producer_registry: Any,
    source_registry: PersistentPlatformRowSourceRegistry,
) -> None:
    """Register all canonical rows against one current source registry."""

    for row in REQUIRED_PLATFORM_ROWS:
        producer_registry.register(
            row,
            lambda owner, selected_row=row: source_registry.resolve_current_row(
                selected_row,
                owner_user_id=owner,
            ),
        )


__all__ = [
    "PLATFORM_ROW_SOURCE_CERTIFICATION_VERSION",
    "PLATFORM_ROW_SOURCE_SCHEMA_VERSION",
    "PersistentPlatformRowSourceRegistry",
    "PlatformRowSourceCertification",
    "PlatformRowSourceCommitUncertain",
    "PlatformRowSourceError",
    "PlatformTypedSourceResolver",
    "register_platform_row_source_producers",
]
