"""No-cycle full-product GOAL entrypoint attestation and staged producer.

The producer accepts only an owner.  It derives every proof reference from
current owner-scoped registries, preflights all six entry sources before the
first write, and persists an explicit append-only stage sequence.  A terminal
full-product aggregate is written only after all six derived coverages pass the
dedicated attestation validator.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json, content_hash
from .compiler import (
    COMPILER_IR_PROOF_CODEC,
    COMPILER_PASS_PROOF_CODEC,
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
    validate_compiler_ir,
    validate_compiler_pass,
)
from .goal_coverage import (
    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
    validate_goal_entrypoint_coverage,
)
from .goal_entrypoint_aggregate import (
    GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC,
    GoalEntrypointAggregateRecord,
)
from .goal_entrypoint_lineage_aggregate import (
    GoalEntrypointLineageAggregateRecord,
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .goal_proof_ledger import GoalProofLedger, ProofBundle
from .goal_proof_records import (
    ATOMIC_PROOF_BUNDLE_REQUIRED,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    ProofRecordCodec,
    decode_proof_record_head,
    typed_proof_record_member,
)
from .goal_semantics import PersistentGoalSectionSemanticProofRegistry
from .goal_validation_receipts import (
    GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
    validate_goal_validation_receipt_shape,
)


LEGACY_FULL_PRODUCT_ATTESTATION_VERSION = (
    "goal_full_product_entrypoint_attestation.v1"
)
FULL_PRODUCT_ATTESTATION_VERSION = "goal_full_product_entrypoint_attestation.v2"
FULL_PRODUCT_COMPILER_VERSION = "goal-full-product-entrypoint.v1"
FULL_PRODUCT_VALIDATOR_IDENTIFIER = (
    "runtime_validator:goal_full_product_entrypoint_v1"
)
FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER = (
    "runtime_validator:goal_full_product_attestation_registry_v1"
)
LOGICAL_TYPE_FULL_PRODUCT_ATTESTATION = "goal.full_product_attestation"


def _stable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _stable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    payload = canonical_json(_stable(value)).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _entry_source(record: Any) -> str:
    value = getattr(record, "entry_source", "")
    return str(getattr(value, "value", value) or "")


def _owner(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("GOAL full-product entrypoint owner is required")
    return owner


def _decision_codes(decision: Any) -> str:
    codes = sorted(
        {
            str(getattr(item, "code", "validation_failed") or "validation_failed")
            for item in tuple(getattr(decision, "violations", ()) or ())
        }
    )
    return ",".join(codes) or "validation_failed"


def _atomic_rewrite_attestation_rows(
    path: Path,
    rows: tuple[dict[str, Any], ...],
) -> None:
    """Replace the attestation ledger with one fsynced canonical JSONL snapshot."""

    temp_path: str | None = None
    temp_fd, temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        os.fchmod(temp_fd, 0o600)
        with os.fdopen(temp_fd, "wb") as fh:
            for row in rows:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    + b"\n"
                )
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
        temp_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.close(temp_fd)
        except OSError:
            pass
        raise
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class GoalFullProductViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class GoalFullProductDecision:
    accepted: bool
    violations: tuple[GoalFullProductViolation, ...]


@dataclass(frozen=True)
class GoalFullProductClosureSnapshot:
    """Server-resolved promotion closure bound into every terminal candidate."""

    lifecycle_refs: tuple[str, ...]
    rdp_refs: tuple[str, ...]
    promotion_receipt_ref: str


@dataclass(frozen=True)
class GoalFullProductEntrypointAttestation:
    """Content-bound proof input for one derived terminal entrypoint row."""

    attestation_ref: str
    owner_user_id: str
    entry_source: str
    base_coverage_ref: str
    base_coverage_digest: str
    lineage_aggregate_ref: str
    lineage_coverage_refs: tuple[str, ...]
    semantic_proof_refs: tuple[str, ...]
    section_snapshot_refs: tuple[str, ...]
    qro_refs: tuple[str, ...]
    research_graph_command_refs: tuple[str, ...]
    permission_ref: str
    lifecycle_refs: tuple[str, ...]
    rdp_refs: tuple[str, ...]
    promotion_receipt_ref: str
    derived_entrypoint_ref: str
    derived_ir_ref: str
    derived_pass_ref: str
    derived_coverage_ref: str
    attestation_version: str = FULL_PRODUCT_ATTESTATION_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "attestation_ref",
            "owner_user_id",
            "entry_source",
            "base_coverage_ref",
            "base_coverage_digest",
            "lineage_aggregate_ref",
            "permission_ref",
            "promotion_receipt_ref",
            "derived_entrypoint_ref",
            "derived_ir_ref",
            "derived_pass_ref",
            "derived_coverage_ref",
            "attestation_version",
        ):
            object.__setattr__(
                self,
                field_name,
                str(getattr(self, field_name) or "").strip(),
            )
        for field_name in (
            "lineage_coverage_refs",
            "semantic_proof_refs",
            "section_snapshot_refs",
            "qro_refs",
            "research_graph_command_refs",
            "lifecycle_refs",
            "rdp_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(
                    str(ref or "").strip()
                    for ref in tuple(getattr(self, field_name) or ())
                ),
            )

    @property
    def canonical_attestation_ref(self) -> str:
        payload = asdict(self)
        payload.pop("attestation_ref", None)
        return "goal_full_product_entrypoint_attestation:" + content_hash(payload)


def goal_full_product_entrypoint_attestation_from_dict(
    data: dict[str, Any],
) -> GoalFullProductEntrypointAttestation:
    attestation_version = (
        LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
        if "attestation_version" not in data
        else str(data.get("attestation_version") or "")
    )
    return GoalFullProductEntrypointAttestation(
        attestation_ref=str(data.get("attestation_ref") or ""),
        owner_user_id=str(data.get("owner_user_id") or ""),
        entry_source=str(data.get("entry_source") or ""),
        base_coverage_ref=str(data.get("base_coverage_ref") or ""),
        base_coverage_digest=str(data.get("base_coverage_digest") or ""),
        lineage_aggregate_ref=str(data.get("lineage_aggregate_ref") or ""),
        lineage_coverage_refs=tuple(data.get("lineage_coverage_refs") or ()),
        semantic_proof_refs=tuple(data.get("semantic_proof_refs") or ()),
        section_snapshot_refs=tuple(data.get("section_snapshot_refs") or ()),
        qro_refs=tuple(data.get("qro_refs") or ()),
        research_graph_command_refs=tuple(
            data.get("research_graph_command_refs") or ()
        ),
        permission_ref=str(data.get("permission_ref") or ""),
        lifecycle_refs=tuple(data.get("lifecycle_refs") or ()),
        rdp_refs=tuple(data.get("rdp_refs") or ()),
        promotion_receipt_ref=str(data.get("promotion_receipt_ref") or ""),
        derived_entrypoint_ref=str(data.get("derived_entrypoint_ref") or ""),
        derived_ir_ref=str(data.get("derived_ir_ref") or ""),
        derived_pass_ref=str(data.get("derived_pass_ref") or ""),
        derived_coverage_ref=str(data.get("derived_coverage_ref") or ""),
        attestation_version=attestation_version,
    )


GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC = ProofRecordCodec[
    GoalFullProductEntrypointAttestation
](
    logical_type=LOGICAL_TYPE_FULL_PRODUCT_ATTESTATION,
    record_type=GoalFullProductEntrypointAttestation,
    decode=goal_full_product_entrypoint_attestation_from_dict,
    logical_ref=lambda record: record.attestation_ref,
    owner=lambda record: record.owner_user_id,
)


@dataclass(frozen=True)
class GoalFullProductSnapshot:
    """Read-only preflight snapshot used to derive all six candidates."""

    owner_user_id: str
    lineage_aggregate: GoalEntrypointLineageAggregateRecord
    base_coverages: tuple[GoalEntrypointCoverageRecord, ...]
    semantic_proofs: tuple[Any, ...]
    section_coverages: tuple[Any, ...]
    section_snapshot_refs: tuple[str, ...]
    compiler_irs: tuple[CompilerIRRecord, ...]
    closure: GoalFullProductClosureSnapshot


@dataclass(frozen=True)
class GoalFullProductCandidate:
    attestation: GoalFullProductEntrypointAttestation
    validation_receipt: GoalValidationReceipt
    compiler_ir: CompilerIRRecord
    compiler_pass: CompilerPassRecord
    coverage: GoalEntrypointCoverageRecord


class GoalFullProductCommitStage(str, Enum):
    PREFLIGHT = "preflight"
    ATTESTATION = "attestation"
    VALIDATION_RECEIPT = "validation_receipt"
    COMPILER_IR = "compiler_ir"
    COMPILER_PASS = "compiler_pass"
    COVERAGE = "coverage"
    COVERAGE_VALIDATION = "coverage_validation"
    FINAL_AGGREGATE = "final_aggregate"


@dataclass(frozen=True)
class GoalFullProductSourceCommit:
    entry_source: str
    attestation_ref: str
    validation_ref: str
    compiler_ir_ref: str
    compiler_pass_ref: str
    coverage_ref: str
    completed_stages: tuple[str, ...]


@dataclass(frozen=True)
class GoalFullProductCommitResult:
    sources: tuple[GoalFullProductSourceCommit, ...]
    final_aggregate_ref: str


class GoalFullProductCommitError(RuntimeError):
    """Honest forward-only failure with the last attempted durable stage."""

    def __init__(
        self,
        *,
        entry_source: str,
        stage: GoalFullProductCommitStage,
        completed_stages: tuple[str, ...],
        cause: Exception,
        compensation_attempted: bool = False,
        compensation_verified: bool = False,
        state_unchanged: bool = True,
        compensation_error: Exception | None = None,
    ) -> None:
        self.entry_source = str(entry_source or "")
        self.stage = stage
        self.completed_stages = tuple(completed_stages)
        self.cause = cause
        self.compensation_attempted = bool(compensation_attempted)
        self.compensation_verified = bool(compensation_verified)
        self.state_unchanged = bool(state_unchanged)
        self.compensation_error = compensation_error
        # Backward compatibility for callers that still project ``compensated``.
        # Forward-only commits never report compensation unless it was both
        # attempted and independently verified.
        self.compensated = self.compensation_verified
        compensation_status = "compensation=not_attempted"
        if self.compensation_attempted:
            compensation_status = (
                "compensation=verified"
                if self.compensation_verified
                else "compensation=unverified"
            )
        if compensation_error is not None:
            compensation_status += (
                f":{type(compensation_error).__name__}:{compensation_error}"
            )
        super().__init__(
            "GOAL full-product entrypoint commit failed "
            f"source={self.entry_source or 'all'} stage={stage.value}: "
            f"{type(cause).__name__}: {cause}; {compensation_status}; "
            f"state_unchanged={str(self.state_unchanged).lower()}"
        )


class PersistentGoalFullProductEntrypointAttestationRegistry:
    """Append-only attestations plus the dedicated current-state validator."""

    def __init__(
        self,
        path: str | Path,
        *,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        lineage_aggregate_registry: PersistentGoalEntrypointLineageAggregateRegistry,
        semantic_proof_registry: PersistentGoalSectionSemanticProofRegistry,
        section_coverage_registry: PersistentGoalSectionCoverageRegistry,
        compiler_store: PersistentCompilerIRStore,
        validation_receipt_registry: PersistentGoalValidationReceiptRegistry,
        closure_resolver: Callable[
            [str, tuple[Any, ...]], GoalFullProductClosureSnapshot
        ],
        proof_ledger: GoalProofLedger | None = None,
        legacy_read_only: bool = False,
    ) -> None:
        if not callable(closure_resolver):
            raise TypeError("GOAL full-product closure_resolver must be callable")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._process_lock = threading.RLock()
        self._entrypoint_registry = entrypoint_registry
        self._lineage_aggregate_registry = lineage_aggregate_registry
        self._semantic_proof_registry = semantic_proof_registry
        self._section_coverage_registry = section_coverage_registry
        self._compiler_store = compiler_store
        self._validation_receipt_registry = validation_receipt_registry
        self._closure_resolver = closure_resolver
        self._proof_projection = (
            GoalProofRecordProjection(proof_ledger)
            if proof_ledger is not None
            else None
        )
        self._legacy_read_only = bool(legacy_read_only)
        self._proof_head_types: dict[tuple[str, str], str] = {}
        self._records: dict[
            tuple[str, str], GoalFullProductEntrypointAttestation
        ] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()
        self._overlay_canonical_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        with self._current_read_boundary():
            return self._legacy_quarantined_count

    def _entrypoint_records_snapshot(
        self,
        *,
        owner: str,
    ) -> tuple[GoalEntrypointCoverageRecord, ...]:
        """Read one exact proof snapshot, or explicit no-ledger history."""

        if bool(
            getattr(
                self._entrypoint_registry,
                "canonical_projection_available",
                False,
            )
        ):
            canonical_records = getattr(
                self._entrypoint_registry,
                "canonical_records",
                None,
            )
            if not callable(canonical_records):
                raise TypeError(
                    "GOAL entrypoint registry lacks canonical proof reads"
                )
            return tuple(canonical_records(owner=owner))
        return tuple(self._entrypoint_registry.records(owner=owner))

    def _compiler_records_snapshot(
        self,
        *,
        owner: str,
    ) -> tuple[tuple[CompilerIRRecord, ...], tuple[CompilerPassRecord, ...]]:
        """Read IR/pass records from one canonical compiler snapshot.

        The JSONL branch is an explicit compatibility mode for callers that
        did not configure a proof ledger.  A ledger-configured store never
        falls back to its legacy projection.
        """

        if getattr(self._compiler_store, "_proof_projection", None) is not None:
            canonical_records = getattr(
                self._compiler_store,
                "canonical_records",
                None,
            )
            if not callable(canonical_records):
                raise TypeError("Governed Compiler lacks canonical proof reads")
            snapshot = canonical_records(owner=owner)
            return tuple(snapshot.irs), tuple(snapshot.passes)
        return (
            tuple(self._compiler_store.irs(owner=owner)),
            tuple(self._compiler_store.passes(owner=owner)),
        )

    def _current_entrypoint_coverage(
        self,
        coverage_ref: str,
        *,
        owner: str,
    ) -> GoalEntrypointCoverageRecord:
        records = self._entrypoint_records_snapshot(owner=owner)
        for record in records:
            if record.coverage_ref == coverage_ref:
                return record
        raise KeyError(coverage_ref)

    def _current_compiler_ir(
        self,
        ir_ref: str,
        *,
        owner: str,
    ) -> CompilerIRRecord:
        irs, _passes = self._compiler_records_snapshot(owner=owner)
        for record in irs:
            if record.ir_ref == ir_ref:
                return record
        raise KeyError(ir_ref)

    def _current_compiler_pass(
        self,
        pass_ref: str,
        *,
        owner: str,
    ) -> CompilerPassRecord:
        _irs, passes = self._compiler_records_snapshot(owner=owner)
        for record in passes:
            if record.pass_ref == pass_ref:
                return record
        raise KeyError(pass_ref)

    @staticmethod
    def _terminal_refs_rejected(
        refs: tuple[str, ...],
        *,
        coverage_by_ref: dict[str, GoalEntrypointCoverageRecord],
        context: str,
    ) -> None:
        for coverage_ref in refs:
            try:
                coverage = coverage_by_ref[coverage_ref]
            except KeyError as exc:
                raise ValueError(
                    f"{context} references non-canonical entrypoint coverage "
                    f"{coverage_ref}"
                ) from exc
            if bool(coverage.claims_full_product_entrypoint):
                raise ValueError(
                    f"{context} cannot depend on terminal full-product coverage "
                    f"{coverage_ref}"
                )

    @staticmethod
    def _legacy_v1_row_is_well_formed(row: dict[str, Any]) -> bool:
        """Recognize only the prior v1 envelope before quarantining it."""

        if row.get("schema_version") != 2:
            return False
        if row.get("event_type") != "goal_full_product_attestation_recorded":
            return False
        raw = row.get("attestation")
        if not isinstance(raw, dict):
            return False
        version = (
            LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
            if "attestation_version" not in raw
            else raw.get("attestation_version")
        )
        if version != LEGACY_FULL_PRODUCT_ATTESTATION_VERSION:
            return False

        scalar_fields = (
            "attestation_ref",
            "owner_user_id",
            "entry_source",
            "base_coverage_ref",
            "base_coverage_digest",
            "lineage_aggregate_ref",
            "permission_ref",
            "derived_entrypoint_ref",
            "derived_ir_ref",
            "derived_pass_ref",
            "derived_coverage_ref",
        )
        sequence_fields = (
            "lineage_coverage_refs",
            "semantic_proof_refs",
            "section_snapshot_refs",
            "qro_refs",
            "research_graph_command_refs",
        )
        required_fields = {*scalar_fields, *sequence_fields}
        allowed_fields = {*required_fields, "attestation_version"}
        if set(raw) not in (required_fields, allowed_fields):
            return False
        if any(
            not isinstance(raw.get(field_name), str)
            or not raw[field_name]
            or raw[field_name] != raw[field_name].strip()
            for field_name in scalar_fields
        ):
            return False
        for field_name in sequence_fields:
            values = raw.get(field_name)
            if (
                not isinstance(values, list)
                or not values
                or any(
                    not isinstance(ref, str)
                    or not ref
                    or ref != ref.strip()
                    for ref in values
                )
                or len(values) != len(set(values))
            ):
                return False
        if len(raw["lineage_coverage_refs"]) != len(REQUIRED_ENTRY_SOURCES):
            return False
        if len(raw["semantic_proof_refs"]) != len(REQUIRED_GOAL_SECTIONS):
            return False
        if len(raw["section_snapshot_refs"]) != len(REQUIRED_GOAL_SECTIONS):
            return False
        legacy_identity_payload = {
            field_name: raw[field_name]
            for field_name in (*scalar_fields, *sequence_fields)
            if field_name != "attestation_ref"
        }
        legacy_identity_payload["attestation_version"] = (
            LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
        )
        canonical_legacy_ref = (
            "goal_full_product_entrypoint_attestation:"
            + content_hash(legacy_identity_payload)
        )
        return (
            raw["owner_user_id"] == row.get("owner_user_id")
            and raw["entry_source"] in REQUIRED_ENTRY_SOURCES
            and raw["attestation_ref"] == canonical_legacy_ref
        )

    @staticmethod
    def _v2_row_is_well_formed(row: dict[str, Any]) -> bool:
        if row.get("schema_version") != 2:
            return False
        if row.get("event_type") != "goal_full_product_attestation_recorded":
            return False
        raw = row.get("attestation")
        if not isinstance(raw, dict):
            return False
        expected_fields = {
            item.name for item in fields(GoalFullProductEntrypointAttestation)
        }
        if set(raw) != expected_fields:
            return False
        sequence_fields = {
            "lineage_coverage_refs",
            "semantic_proof_refs",
            "section_snapshot_refs",
            "qro_refs",
            "research_graph_command_refs",
            "lifecycle_refs",
            "rdp_refs",
        }
        for field_name in expected_fields - sequence_fields:
            value = raw.get(field_name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                return False
        for field_name in sequence_fields:
            values = raw.get(field_name)
            if (
                not isinstance(values, (list, tuple))
                or not values
                or any(
                    not isinstance(ref, str)
                    or not ref
                    or ref != ref.strip()
                    for ref in values
                )
            ):
                return False
        return (
            raw["attestation_version"] == FULL_PRODUCT_ATTESTATION_VERSION
            and raw["owner_user_id"] == row.get("owner_user_id")
        )

    @staticmethod
    def _section_snapshot_ref(owner: str, record: Any) -> str:
        return "goal_section_coverage_snapshot:" + content_hash(
            {
                "owner_user_id": owner,
                "section_coverage": _stable(record),
            }
        )

    @staticmethod
    def _validated_closure_snapshot(
        value: Any,
    ) -> GoalFullProductClosureSnapshot:
        if type(value) is not GoalFullProductClosureSnapshot:
            raise TypeError(
                "GOAL full-product closure_resolver must return "
                "GoalFullProductClosureSnapshot"
            )

        for field_name in ("lifecycle_refs", "rdp_refs"):
            refs = getattr(value, field_name)
            if not isinstance(refs, tuple):
                raise TypeError(
                    f"GOAL full-product closure {field_name} must be an exact tuple"
                )
            if not refs:
                raise ValueError(
                    f"GOAL full-product closure {field_name} must be non-empty"
                )
            if any(
                not isinstance(ref, str) or not ref or ref != ref.strip()
                for ref in refs
            ):
                raise ValueError(
                    f"GOAL full-product closure {field_name} contains an invalid ref"
                )
            if len(refs) != len(set(refs)):
                raise ValueError(
                    f"GOAL full-product closure {field_name} contains duplicate refs"
                )

        receipt_ref = value.promotion_receipt_ref
        if (
            not isinstance(receipt_ref, str)
            or not receipt_ref
            or receipt_ref != receipt_ref.strip()
        ):
            raise ValueError(
                "GOAL full-product closure promotion_receipt_ref must be a "
                "non-empty exact ref"
            )
        all_refs = (*value.lifecycle_refs, *value.rdp_refs, receipt_ref)
        if len(all_refs) != len(set(all_refs)):
            raise ValueError(
                "GOAL full-product closure refs must be globally unique"
            )
        return value

    def build_current_snapshot(
        self,
        *,
        owner_user_id: str,
    ) -> GoalFullProductSnapshot:
        """Read one dependency-fresh current snapshot at the proof-head boundary."""

        with self._current_read_boundary():
            return self._build_current_snapshot_unlocked(
                owner_user_id=owner_user_id
            )

    def _build_current_snapshot_unlocked(
        self,
        *,
        owner_user_id: str,
    ) -> GoalFullProductSnapshot:
        """Preflight current persisted partial aggregate and exact §0-§17 heads."""

        owner = _owner(owner_user_id)
        entrypoint_records = self._entrypoint_records_snapshot(owner=owner)
        coverage_by_ref = {
            record.coverage_ref: record for record in entrypoint_records
        }
        if len(coverage_by_ref) != len(entrypoint_records):
            raise ValueError(
                "GOAL canonical entrypoint coverage snapshot has duplicate refs"
            )
        lineage_snapshot = (
            self._lineage_aggregate_registry._current_snapshot_from_records(
                owner=owner,
                records=entrypoint_records,
            )
        )
        current = lineage_snapshot.aggregate
        try:
            persisted = self._lineage_aggregate_registry.aggregate(
                current.aggregate_ref,
                owner_user_id=owner,
            )
        except KeyError as exc:
            raise ValueError(
                "current GOAL entrypoint lineage aggregate is not persisted"
            ) from exc
        aggregate_violations = (
            self._lineage_aggregate_registry._validate_against_current_snapshot(
                persisted,
                owner=owner,
                current_snapshot=lineage_snapshot,
            )
        )
        if aggregate_violations:
            raise ValueError(";".join(aggregate_violations))

        base_coverages = lineage_snapshot.coverages
        if tuple(item.coverage_ref for item in base_coverages) != (
            persisted.coverage_refs
        ):
            raise ValueError("GOAL lineage aggregate coverage order is not current")
        for coverage in base_coverages:
            if bool(coverage.claims_full_product_entrypoint):
                raise ValueError(
                    "GOAL lineage aggregate contains terminal full-product coverage"
                )

        if self._semantic_proof_registry.registered_sections != tuple(
            REQUIRED_GOAL_SECTIONS
        ):
            raise ValueError(
                "GOAL full-product preflight requires registered semantic adapters "
                "for exact §0-§17 coverage"
            )

        semantic_proofs: list[Any] = []
        section_coverages: list[Any] = []
        section_snapshot_refs: list[str] = []
        for section in REQUIRED_GOAL_SECTIONS:
            proofs = self._semantic_proof_registry.records(
                owner=owner,
                section=section,
            )
            if not proofs:
                raise ValueError(
                    f"GOAL full-product preflight is missing semantic proof {section}"
                )
            proof = proofs[-1]
            self._terminal_refs_rejected(
                tuple(proof.entrypoint_coverage_refs),
                coverage_by_ref=coverage_by_ref,
                context=f"semantic proof {section}",
            )
            proof_decision = self._semantic_proof_registry.validate_real_backing(
                proof,
                owner=owner,
            )
            if not proof_decision.accepted:
                raise ValueError(
                    f"GOAL semantic proof {section} is not strict: "
                    + _decision_codes(proof_decision)
                )
            if (
                proof.recorded_by != owner
                or proof.section != section
                or not bool(proof.claims_section_complete)
                or tuple(proof.unverified_residuals)
            ):
                raise ValueError(
                    f"GOAL semantic proof {section} is not an exact complete owner head"
                )

            try:
                section_record = self._section_coverage_registry.coverage(
                    section,
                    owner=owner,
                )
            except KeyError as exc:
                raise ValueError(
                    f"GOAL full-product preflight is missing section coverage {section}"
                ) from exc
            self._terminal_refs_rejected(
                tuple(section_record.entrypoint_wiring_refs),
                coverage_by_ref=coverage_by_ref,
                context=f"section coverage {section}",
            )
            if tuple(section_record.semantic_proof_refs) != (proof.proof_ref,):
                raise ValueError(
                    f"GOAL section coverage {section} does not bind the exact "
                    "current semantic proof head"
                )
            if not bool(section_record.full_entrypoint_wired):
                raise ValueError(
                    f"GOAL section coverage {section} is not fully wired"
                )
            section_decision = self._section_coverage_registry.validate_real_backing(
                section_record,
                owner=owner,
            )
            if not section_decision.accepted:
                raise ValueError(
                    f"GOAL section coverage {section} is not strict: "
                    + _decision_codes(section_decision)
                )
            semantic_proofs.append(proof)
            section_coverages.append(section_record)
            section_snapshot_refs.append(
                self._section_snapshot_ref(owner, section_record)
            )

        manifest_decision = self._section_coverage_registry.validate_real_manifest(
            claims_full_product_implementation=True,
            owner=owner,
        )
        if not manifest_decision.accepted:
            raise ValueError(
                "GOAL full-product section manifest is not strict: "
                + _decision_codes(manifest_decision)
            )

        # The resolver is a server-owned capability, not a request input.  It is
        # intentionally called only after every §0-§17 semantic proof and its
        # section head have passed strict current-state validation.
        closure = self._validated_closure_snapshot(
            self._closure_resolver(owner, tuple(semantic_proofs))
        )
        compiler_irs, _compiler_passes = self._compiler_records_snapshot(
            owner=owner
        )

        return GoalFullProductSnapshot(
            owner_user_id=owner,
            lineage_aggregate=persisted,
            base_coverages=base_coverages,
            semantic_proofs=tuple(semantic_proofs),
            section_coverages=tuple(section_coverages),
            section_snapshot_refs=tuple(section_snapshot_refs),
            compiler_irs=compiler_irs,
            closure=closure,
        )

    @staticmethod
    def _derivation_seed(
        *,
        owner: str,
        source: str,
        base_coverage_ref: str,
        base_coverage_digest: str,
        lineage_aggregate_ref: str,
        lineage_coverage_refs: tuple[str, ...],
        semantic_proof_refs: tuple[str, ...],
        section_snapshot_refs: tuple[str, ...],
        qro_refs: tuple[str, ...],
        graph_refs: tuple[str, ...],
        permission_ref: str,
        lifecycle_refs: tuple[str, ...],
        rdp_refs: tuple[str, ...],
        promotion_receipt_ref: str,
    ) -> str:
        return content_hash(
            {
                "owner_user_id": owner,
                "entry_source": source,
                "base_coverage_ref": base_coverage_ref,
                "base_coverage_digest": base_coverage_digest,
                "lineage_aggregate_ref": lineage_aggregate_ref,
                "lineage_coverage_refs": lineage_coverage_refs,
                "semantic_proof_refs": semantic_proof_refs,
                "section_snapshot_refs": section_snapshot_refs,
                "qro_refs": qro_refs,
                "research_graph_command_refs": graph_refs,
                "permission_ref": permission_ref,
                "lifecycle_refs": lifecycle_refs,
                "rdp_refs": rdp_refs,
                "promotion_receipt_ref": promotion_receipt_ref,
                "attestation_version": FULL_PRODUCT_ATTESTATION_VERSION,
            }
        )

    def _build_attestation(
        self,
        *,
        snapshot: GoalFullProductSnapshot,
        base: GoalEntrypointCoverageRecord,
    ) -> GoalFullProductEntrypointAttestation:
        owner = snapshot.owner_user_id
        source = _entry_source(base)
        if source not in REQUIRED_ENTRY_SOURCES:
            raise ValueError(f"unknown GOAL entry source {source}")
        if base.recorded_by != owner or bool(base.claims_full_product_entrypoint):
            raise ValueError("base coverage must be owner-bound and non-terminal")
        if len(base.permission_refs) != 1:
            raise ValueError(
                "base coverage requires exactly one permission ref for derived compiler lineage"
            )
        base_digest = _sha256(base)
        semantic_refs = tuple(proof.proof_ref for proof in snapshot.semantic_proofs)
        seed = self._derivation_seed(
            owner=owner,
            source=source,
            base_coverage_ref=base.coverage_ref,
            base_coverage_digest=base_digest,
            lineage_aggregate_ref=snapshot.lineage_aggregate.aggregate_ref,
            lineage_coverage_refs=snapshot.lineage_aggregate.coverage_refs,
            semantic_proof_refs=semantic_refs,
            section_snapshot_refs=snapshot.section_snapshot_refs,
            qro_refs=base.qro_refs,
            graph_refs=base.research_graph_command_refs,
            permission_ref=base.permission_refs[0],
            lifecycle_refs=snapshot.closure.lifecycle_refs,
            rdp_refs=snapshot.closure.rdp_refs,
            promotion_receipt_ref=snapshot.closure.promotion_receipt_ref,
        )
        entrypoint_ref = f"goal_full_product_entrypoint:{source}:{seed}"
        ir_ref = f"compiler_ir:goal_full_product_entrypoint:{source}:{seed}"
        pass_ref = f"compiler_pass:goal_full_product_entrypoint:{source}:{seed}"
        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=REQUIRED_GOAL_SECTIONS,
            qro_refs=base.qro_refs,
            research_graph_command_refs=base.research_graph_command_refs,
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        provisional = GoalFullProductEntrypointAttestation(
            attestation_ref="",
            owner_user_id=owner,
            entry_source=source,
            base_coverage_ref=base.coverage_ref,
            base_coverage_digest=base_digest,
            lineage_aggregate_ref=snapshot.lineage_aggregate.aggregate_ref,
            lineage_coverage_refs=snapshot.lineage_aggregate.coverage_refs,
            semantic_proof_refs=semantic_refs,
            section_snapshot_refs=snapshot.section_snapshot_refs,
            qro_refs=base.qro_refs,
            research_graph_command_refs=base.research_graph_command_refs,
            permission_ref=base.permission_refs[0],
            lifecycle_refs=snapshot.closure.lifecycle_refs,
            rdp_refs=snapshot.closure.rdp_refs,
            promotion_receipt_ref=snapshot.closure.promotion_receipt_ref,
            derived_entrypoint_ref=entrypoint_ref,
            derived_ir_ref=ir_ref,
            derived_pass_ref=pass_ref,
            derived_coverage_ref=coverage_ref,
        )
        return GoalFullProductEntrypointAttestation(
            **{
                **asdict(provisional),
                "attestation_ref": provisional.canonical_attestation_ref,
            }
        )

    def _evidence_pairs(
        self,
        *,
        attestation: GoalFullProductEntrypointAttestation,
    ) -> tuple[tuple[str, str], ...]:
        # The canonical attestation ref already content-binds the base coverage
        # digest, aggregate, semantic proofs, section snapshots, QROs, graph
        # commands, server-resolved lifecycle/RDP/promotion closure, and derived
        # refs.  Citing those inputs individually here would turn content labels
        # into apparent evidence.  The independently persisted attestation is
        # the sole terminal evidence object.
        return ((attestation.attestation_ref, _sha256(attestation)),)

    def _candidate(
        self,
        *,
        snapshot: GoalFullProductSnapshot,
        base: GoalEntrypointCoverageRecord,
    ) -> GoalFullProductCandidate:
        attestation = self._build_attestation(snapshot=snapshot, base=base)
        evidence_pairs = self._evidence_pairs(
            attestation=attestation,
        )
        evidence_refs = tuple(ref for ref, _digest in evidence_pairs)
        evidence_digests = tuple(digest for _ref, digest in evidence_pairs)
        provisional_receipt = GoalValidationReceipt(
            validation_ref="",
            owner_user_id=snapshot.owner_user_id,
            subject_qro_refs=base.qro_refs,
            graph_command_refs=base.research_graph_command_refs,
            validator_identifiers=(
                FULL_PRODUCT_VALIDATOR_IDENTIFIER,
                FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER,
            ),
            test_identifiers=(
                "runtime_check:goal_full_product_entrypoint_preflight_v1",
            ),
            outcome=GoalValidationOutcome.PASSED,
            evidence_refs=evidence_refs,
            evidence_digests=evidence_digests,
            residuals=(),
        )
        receipt = GoalValidationReceipt(
            **{
                **asdict(provisional_receipt),
                "validation_ref": provisional_receipt.canonical_validation_ref,
            }
        )
        canonical_refs = (
            f"entrypoint:{attestation.derived_entrypoint_ref}",
            attestation.attestation_ref,
        )
        run_plan_ref = (
            "deterministic_run_plan:goal_full_product_entrypoint:"
            f"{attestation.entry_source}:"
            f"{attestation.derived_ir_ref.rsplit(':', 1)[-1]}"
        )
        rollback_ref = (
            "rollback:goal_full_product_entrypoint:"
            f"{attestation.entry_source}:"
            f"{attestation.derived_ir_ref.rsplit(':', 1)[-1]}"
        )
        ir = CompilerIRRecord(
            ir_ref=attestation.derived_ir_ref,
            source_qro_refs=base.qro_refs,
            graph_command_refs=base.research_graph_command_refs,
            canonical_command_refs=canonical_refs,
            node_refs=(
                *base.qro_refs,
                f"entrypoint:{attestation.derived_entrypoint_ref}",
                attestation.attestation_ref,
            ),
            edge_refs=(),
            artifact_refs=(),
            theory_binding_refs=(),
            consistency_check_refs=(),
            evidence_refs=evidence_refs,
            validation_refs=(receipt.validation_ref,),
            permission_ref=attestation.permission_ref,
            deterministic_run_plan_ref=run_plan_ref,
            rollback_ref=rollback_ref,
            environment_lock_ref=(
                "environment_lock:goal_full_product_entrypoint_v1"
            ),
            owner=snapshot.owner_user_id,
            target_runtime="offline",
            compiler_version=FULL_PRODUCT_COMPILER_VERSION,
            mock_profile="none",
        )
        compiler_pass = CompilerPassRecord(
            pass_ref=attestation.derived_pass_ref,
            pass_name="goal_full_product_entrypoint_attestation",
            input_ir_refs=base.compiler_ir_refs,
            output_ir_ref=ir.ir_ref,
            input_qro_refs=base.qro_refs,
            graph_command_refs=base.research_graph_command_refs,
            canonical_command_refs=canonical_refs,
            actor=snapshot.owner_user_id,
            actor_source="agent",
            entry_source=attestation.entry_source,
            permission_ref=attestation.permission_ref,
            tool_record_refs=(
                attestation.derived_entrypoint_ref,
                attestation.attestation_ref,
            ),
            evidence_refs=evidence_refs,
            validation_refs=(receipt.validation_ref,),
            deterministic_run_plan_ref=run_plan_ref,
            rollback_ref=rollback_ref,
        )
        coverage = GoalEntrypointCoverageRecord(
            coverage_ref=attestation.derived_coverage_ref,
            entry_source=attestation.entry_source,
            entrypoint_ref=attestation.derived_entrypoint_ref,
            goal_sections=REQUIRED_GOAL_SECTIONS,
            qro_refs=base.qro_refs,
            research_graph_command_refs=base.research_graph_command_refs,
            compiler_ir_refs=(ir.ir_ref,),
            compiler_pass_refs=(compiler_pass.pass_ref,),
            evidence_refs=evidence_refs,
            validation_refs=(receipt.validation_ref,),
            permission_refs=(attestation.permission_ref,),
            replay_refs=(
                *(
                    f"replay:research_graph:{ref}"
                    for ref in base.research_graph_command_refs
                ),
                f"replay:compiler_ir:{ir.ir_ref}",
                f"replay:compiler_pass:{compiler_pass.pass_ref}",
            ),
            canonical_command_refs=canonical_refs,
            lifecycle_refs=attestation.lifecycle_refs,
            rdp_refs=attestation.rdp_refs,
            recorded_by=snapshot.owner_user_id,
            claims_full_product_entrypoint=True,
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )
        ir_decision = validate_compiler_ir(ir)
        pass_decision = validate_compiler_pass(compiler_pass)
        coverage_decision = validate_goal_entrypoint_coverage(coverage)
        if not ir_decision.accepted:
            raise ValueError(
                "derived full-product compiler IR is invalid: "
                + _decision_codes(ir_decision)
            )
        if not pass_decision.accepted:
            raise ValueError(
                "derived full-product compiler pass is invalid: "
                + _decision_codes(pass_decision)
            )
        if not coverage_decision.accepted:
            raise ValueError(
                "derived full-product coverage is invalid: "
                + _decision_codes(coverage_decision)
            )
        if coverage.coverage_ref != goal_entrypoint_coverage_identity(
            entry_source=coverage.entry_source,
            entrypoint_ref=coverage.entrypoint_ref,
            goal_sections=coverage.goal_sections,
            qro_refs=coverage.qro_refs,
            research_graph_command_refs=coverage.research_graph_command_refs,
            compiler_ir_refs=coverage.compiler_ir_refs,
            compiler_pass_refs=coverage.compiler_pass_refs,
        ):
            raise ValueError("derived full-product coverage identity mismatch")
        compiler_ir_by_ref = {
            record.ir_ref: record for record in snapshot.compiler_irs
        }
        for input_ir_ref in compiler_pass.input_ir_refs:
            if input_ir_ref not in compiler_ir_by_ref:
                raise ValueError(
                    f"base compiler IR {input_ir_ref} is not canonical current"
                )
        return GoalFullProductCandidate(
            attestation=attestation,
            validation_receipt=receipt,
            compiler_ir=ir,
            compiler_pass=compiler_pass,
            coverage=coverage,
        )

    def prepare_current_all(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[GoalFullProductCandidate, ...]:
        """Derive all six candidates from one preflight snapshot, without writes."""

        with self._current_read_boundary():
            return self._prepare_current_all_unlocked(
                owner_user_id=owner_user_id
            )

    def _prepare_current_all_unlocked(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[GoalFullProductCandidate, ...]:
        snapshot = self._build_current_snapshot_unlocked(
            owner_user_id=owner_user_id
        )
        candidates = tuple(
            self._candidate(snapshot=snapshot, base=base)
            for base in snapshot.base_coverages
        )
        if tuple(item.attestation.entry_source for item in candidates) != tuple(
            REQUIRED_ENTRY_SOURCES
        ):
            raise ValueError("derived full-product candidate source order mismatch")
        return candidates

    def prepare_current_source(
        self,
        *,
        owner_user_id: str,
        entry_source: str,
    ) -> GoalFullProductCandidate:
        """Derive one candidate; proof refs are never accepted from a caller."""

        with self._current_read_boundary():
            return self._prepare_current_source_unlocked(
                owner_user_id=owner_user_id,
                entry_source=entry_source,
            )

    def _prepare_current_source_unlocked(
        self,
        *,
        owner_user_id: str,
        entry_source: str,
    ) -> GoalFullProductCandidate:
        source = str(entry_source or "").strip()
        if source not in REQUIRED_ENTRY_SOURCES:
            raise ValueError(f"unknown GOAL entry source {source}")
        candidates = self._prepare_current_all_unlocked(
            owner_user_id=owner_user_id
        )
        return next(
            item for item in candidates if item.attestation.entry_source == source
        )

    def _shape_violations(
        self,
        record: GoalFullProductEntrypointAttestation,
        *,
        owner_user_id: str,
    ) -> tuple[GoalFullProductViolation, ...]:
        owner = _owner(owner_user_id)
        violations: list[GoalFullProductViolation] = []

        def add(code: str, message: str, field: str, ref: str = "") -> None:
            violations.append(
                GoalFullProductViolation(code, message, field=field, ref=ref)
            )

        if record.owner_user_id != owner:
            add(
                "goal_full_product_attestation_owner_mismatch",
                "attestation owner envelope must match owner_user_id",
                "owner_user_id",
                record.attestation_ref,
            )
        if record.entry_source not in REQUIRED_ENTRY_SOURCES:
            add(
                "goal_full_product_attestation_source_unknown",
                "attestation entry source is not canonical",
                "entry_source",
                record.entry_source,
            )
        if record.attestation_version != FULL_PRODUCT_ATTESTATION_VERSION:
            add(
                "goal_full_product_attestation_version_unsupported",
                "attestation version is unsupported",
                "attestation_version",
                record.attestation_ref,
            )
        if record.attestation_ref != record.canonical_attestation_ref:
            add(
                "goal_full_product_attestation_identity_mismatch",
                "attestation ref must content-bind all current proof inputs",
                "attestation_ref",
                record.attestation_ref,
            )
        cardinalities = (
            ("lineage_coverage_refs", len(REQUIRED_ENTRY_SOURCES)),
            ("semantic_proof_refs", len(REQUIRED_GOAL_SECTIONS)),
            ("section_snapshot_refs", len(REQUIRED_GOAL_SECTIONS)),
        )
        for field_name, expected in cardinalities:
            values = tuple(getattr(record, field_name))
            if len(values) != expected:
                add(
                    "goal_full_product_attestation_cardinality_mismatch",
                    f"{field_name} must contain {expected} exact current refs",
                    field_name,
                    record.attestation_ref,
                )
            if len(values) != len(set(values)):
                add(
                    "goal_full_product_attestation_duplicate_ref",
                    f"{field_name} cannot contain duplicate refs",
                    field_name,
                    record.attestation_ref,
                )
            if any(not ref for ref in values):
                add(
                    "goal_full_product_attestation_empty_ref",
                    f"{field_name} cannot contain empty refs",
                    field_name,
                    record.attestation_ref,
                )
        for field_name in ("lifecycle_refs", "rdp_refs"):
            values = tuple(getattr(record, field_name))
            if not values:
                add(
                    "goal_full_product_attestation_closure_ref_missing",
                    f"{field_name} must contain server-resolved closure refs",
                    field_name,
                    record.attestation_ref,
                )
            if any(not ref for ref in values):
                add(
                    "goal_full_product_attestation_empty_ref",
                    f"{field_name} cannot contain empty refs",
                    field_name,
                    record.attestation_ref,
                )
            if len(values) != len(set(values)):
                add(
                    "goal_full_product_attestation_duplicate_ref",
                    f"{field_name} cannot contain duplicate refs",
                    field_name,
                    record.attestation_ref,
                )
        closure_refs = (
            *record.lifecycle_refs,
            *record.rdp_refs,
            record.promotion_receipt_ref,
        )
        if len(closure_refs) != len(set(closure_refs)):
            add(
                "goal_full_product_attestation_duplicate_ref",
                "attestation closure refs must be globally unique",
                "promotion_closure",
                record.attestation_ref,
            )
        for field_name in (
            "base_coverage_ref",
            "base_coverage_digest",
            "lineage_aggregate_ref",
            "qro_refs",
            "research_graph_command_refs",
            "permission_ref",
            "promotion_receipt_ref",
            "derived_entrypoint_ref",
            "derived_ir_ref",
            "derived_pass_ref",
            "derived_coverage_ref",
        ):
            if not getattr(record, field_name):
                add(
                    "goal_full_product_attestation_required_field_missing",
                    "attestation requires base, aggregate, proof, and derived refs",
                    field_name,
                    record.attestation_ref,
                )
        return tuple(violations)

    def prepare_attestation_candidate(
        self,
        record: GoalFullProductEntrypointAttestation,
        *,
        owner_user_id: str,
    ) -> GoalFullProductEntrypointAttestation:
        """Validate one deterministic attestation candidate without writing it."""

        violations = self._shape_violations(
            record,
            owner_user_id=owner_user_id,
        )
        if violations:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in violations
                )
            )
        return record

    @staticmethod
    def _cached_canonical_record(
        registry: Any,
        record: Any,
        *,
        owner: str,
        logical_ref: str,
        codec: ProofRecordCodec[Any],
        bucket_name: str,
    ) -> bool:
        """Check the exact projection loaded at the current read boundary."""

        candidate = getattr(registry, "_delegate", registry)
        if getattr(candidate, "_proof_projection", None) is None:
            return False
        if getattr(candidate, "_proof_head_types", {}).get(
            (owner, logical_ref)
        ) != codec.logical_type:
            return False
        return getattr(candidate, bucket_name, {}).get(
            (owner, logical_ref)
        ) == record

    def validate_current(
        self,
        record: GoalFullProductEntrypointAttestation,
        *,
        owner_user_id: str,
    ) -> GoalFullProductDecision:
        """Validate against dependency and attestation views from one boundary."""

        with self._current_read_boundary():
            return self._validate_current_unlocked(
                record,
                owner_user_id=owner_user_id,
            )

    def _validate_current_unlocked(
        self,
        record: GoalFullProductEntrypointAttestation,
        *,
        owner_user_id: str,
    ) -> GoalFullProductDecision:
        owner = _owner(owner_user_id)
        violations = list(
            self._shape_violations(record, owner_user_id=owner)
        )
        try:
            expected = self._prepare_current_source_unlocked(
                owner_user_id=owner,
                entry_source=record.entry_source,
            ).attestation
        except Exception as exc:  # noqa: BLE001 - attestation validation fails closed.
            violations.append(
                GoalFullProductViolation(
                    "goal_full_product_attestation_current_snapshot_unavailable",
                    f"current snapshot validation raised {type(exc).__name__}",
                    field="attestation_ref",
                    ref=record.attestation_ref,
                )
            )
        else:
            for item in fields(record):
                field_name = item.name
                if getattr(record, field_name) != getattr(expected, field_name):
                    violations.append(
                        GoalFullProductViolation(
                            "goal_full_product_attestation_not_current",
                            "attestation field differs from the deterministic "
                            "current owner/source derivation",
                            field=field_name,
                            ref=record.attestation_ref,
                        )
                    )
        if self._proof_projection is not None and not self._cached_canonical_record(
            self,
            record,
            owner=owner,
            logical_ref=record.attestation_ref,
            codec=GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
            bucket_name="_records",
        ):
            violations.append(
                GoalFullProductViolation(
                    "goal_full_product_attestation_not_canonical_current",
                    "attestation is not the exact current SQLite proof head",
                    field="attestation_ref",
                    ref=record.attestation_ref,
                )
            )
        return GoalFullProductDecision(not violations, tuple(violations))

    def validate_full_product_coverage(
        self,
        record: GoalEntrypointCoverageRecord,
        *,
        owner_user_id: str | None = None,
    ) -> GoalFullProductDecision:
        """Dedicated resolver hook rejecting forged markers and recombination."""

        with self._current_read_boundary():
            return self._validate_full_product_coverage_unlocked(
                record,
                owner_user_id=owner_user_id,
            )

    def _validate_full_product_coverage_unlocked(
        self,
        record: GoalEntrypointCoverageRecord,
        *,
        owner_user_id: str | None = None,
    ) -> GoalFullProductDecision:
        owner = _owner(owner_user_id or record.recorded_by)
        violations: list[GoalFullProductViolation] = []

        def add(code: str, message: str, field: str, ref: str = "") -> None:
            violations.append(
                GoalFullProductViolation(code, message, field=field, ref=ref)
            )

        if record.recorded_by != owner:
            add(
                "goal_full_product_coverage_owner_mismatch",
                "coverage owner must match the resolver owner",
                "recorded_by",
                record.coverage_ref,
            )
        if not bool(record.claims_full_product_entrypoint):
            add(
                "goal_full_product_coverage_claim_missing",
                "dedicated validator accepts only terminal full-product rows",
                "claims_full_product_entrypoint",
                record.coverage_ref,
            )
        for field_name in ("lifecycle_refs", "rdp_refs"):
            if not tuple(getattr(record, field_name, ()) or ()):
                add(
                    "goal_full_product_closure_ref_missing",
                    "terminal full-product coverage requires lifecycle and RDP closure refs",
                    field_name,
                    record.coverage_ref,
                )
        try:
            expected = self._prepare_current_source_unlocked(
                owner_user_id=owner,
                entry_source=_entry_source(record),
            )
        except Exception as exc:  # noqa: BLE001 - coverage validation fails closed.
            add(
                "goal_full_product_coverage_current_snapshot_unavailable",
                f"current candidate derivation raised {type(exc).__name__}",
                "coverage_ref",
                record.coverage_ref,
            )
            return GoalFullProductDecision(False, tuple(violations))

        if record != expected.coverage:
            add(
                "goal_full_product_coverage_recombined_or_stale",
                "coverage does not equal the deterministic current candidate",
                "coverage_ref",
                record.coverage_ref,
            )
        try:
            persisted_attestation = self._attestation_unlocked(
                expected.attestation.attestation_ref,
                owner_user_id=owner,
            )
        except KeyError:
            add(
                "goal_full_product_attestation_unknown",
                "coverage receipt does not resolve to a persisted attestation",
                "evidence_refs",
                expected.attestation.attestation_ref,
            )
        else:
            attestation_decision = self._validate_current_unlocked(
                persisted_attestation,
                owner_user_id=owner,
            )
            violations.extend(attestation_decision.violations)
            if persisted_attestation != expected.attestation:
                add(
                    "goal_full_product_attestation_recombined",
                    "persisted attestation differs from the expected source candidate",
                    "attestation_ref",
                    persisted_attestation.attestation_ref,
                )

        try:
            receipt = self._validation_receipt_registry.receipt(
                expected.validation_receipt.validation_ref,
                owner_user_id=owner,
            )
        except KeyError:
            add(
                "goal_full_product_validation_receipt_unknown",
                "dedicated full-product receipt is not persisted",
                "validation_refs",
                expected.validation_receipt.validation_ref,
            )
        else:
            receipt_decision = (
                self._validation_receipt_registry.validate_validation_ref(
                    receipt.validation_ref,
                    owner_user_id=owner,
                    subject_qro_refs=record.qro_refs,
                    graph_command_refs=record.research_graph_command_refs,
                )
            )
            if not receipt_decision.accepted:
                add(
                    "goal_full_product_validation_receipt_invalid",
                    "receipt does not bind the exact current QRO/graph sets",
                    "validation_refs",
                    receipt.validation_ref,
                )
            if receipt != expected.validation_receipt:
                add(
                    "goal_full_product_validation_receipt_recombined",
                    "receipt differs from deterministic attestation evidence",
                    "validation_refs",
                    receipt.validation_ref,
                )
            if FULL_PRODUCT_VALIDATOR_IDENTIFIER not in receipt.validator_identifiers:
                add(
                    "goal_full_product_validator_marker_missing",
                    "receipt lacks the dedicated full-product validator identifier",
                    "validator_identifiers",
                    receipt.validation_ref,
                )
            if tuple(record.validation_refs) != (receipt.validation_ref,):
                add(
                    "goal_full_product_validation_ref_set_mismatch",
                    "coverage must cite exactly its deterministic dedicated receipt",
                    "validation_refs",
                    record.coverage_ref,
                )

        try:
            compiler_irs, compiler_passes = self._compiler_records_snapshot(
                owner=owner
            )
        except Exception as exc:  # noqa: BLE001 - canonical read fails closed.
            add(
                "goal_full_product_compiler_snapshot_unavailable",
                f"canonical compiler snapshot raised {type(exc).__name__}",
                "compiler_ir_refs",
                expected.compiler_ir.ir_ref,
            )
            compiler_irs = ()
            compiler_passes = ()
        ir_by_ref = {item.ir_ref: item for item in compiler_irs}
        pass_by_ref = {item.pass_ref: item for item in compiler_passes}
        persisted_ir = ir_by_ref.get(expected.compiler_ir.ir_ref)
        if persisted_ir is None:
            add(
                "goal_full_product_compiler_ir_unknown",
                "derived compiler IR is not a canonical current record",
                "compiler_ir_refs",
                expected.compiler_ir.ir_ref,
            )
        else:
            if persisted_ir != expected.compiler_ir:
                add(
                    "goal_full_product_compiler_ir_recombined",
                    "persisted compiler IR differs from deterministic candidate",
                    "compiler_ir_refs",
                    persisted_ir.ir_ref,
                )
        persisted_pass = pass_by_ref.get(expected.compiler_pass.pass_ref)
        if persisted_pass is None:
            add(
                "goal_full_product_compiler_pass_unknown",
                "derived compiler pass is not a canonical current record",
                "compiler_pass_refs",
                expected.compiler_pass.pass_ref,
            )
        else:
            if persisted_pass != expected.compiler_pass:
                add(
                    "goal_full_product_compiler_pass_recombined",
                    "persisted compiler pass differs from deterministic candidate",
                    "compiler_pass_refs",
                    persisted_pass.pass_ref,
                )
        if self._proof_projection is not None:
            canonical_checks = (
                (
                    self,
                    expected.attestation,
                    "goal_full_product_attestation_not_canonical_current",
                    "attestation_ref",
                    expected.attestation.attestation_ref,
                    GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
                    "_records",
                ),
                (
                    self._validation_receipt_registry,
                    expected.validation_receipt,
                    "goal_full_product_validation_receipt_not_canonical_current",
                    "validation_refs",
                    expected.validation_receipt.validation_ref,
                    GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
                    "_records",
                ),
                (
                    self._compiler_store,
                    expected.compiler_ir,
                    "goal_full_product_compiler_ir_not_canonical_current",
                    "compiler_ir_refs",
                    expected.compiler_ir.ir_ref,
                    COMPILER_IR_PROOF_CODEC,
                    "_irs",
                ),
                (
                    self._compiler_store,
                    expected.compiler_pass,
                    "goal_full_product_compiler_pass_not_canonical_current",
                    "compiler_pass_refs",
                    expected.compiler_pass.pass_ref,
                    COMPILER_PASS_PROOF_CODEC,
                    "_passes",
                ),
                (
                    self._entrypoint_registry,
                    expected.coverage,
                    "goal_full_product_coverage_not_canonical_current",
                    "coverage_ref",
                    expected.coverage.coverage_ref,
                    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                    "_records",
                ),
            )
            for (
                registry,
                candidate,
                code,
                field_name,
                ref,
                codec,
                bucket_name,
            ) in canonical_checks:
                if not self._cached_canonical_record(
                    registry,
                    candidate,
                    owner=owner,
                    logical_ref=ref,
                    codec=codec,
                    bucket_name=bucket_name,
                ):
                    add(
                        code,
                        "terminal full-product proof member is not the exact "
                        "current SQLite head",
                        field_name,
                        ref,
                    )
        return GoalFullProductDecision(not violations, tuple(violations))

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> GoalFullProductEntrypointAttestation:
        if row.get("schema_version") != 2:
            raise ValueError(
                "GOAL full-product attestations require schema_version=2"
            )
        if row.get("event_type") != "goal_full_product_attestation_recorded":
            raise ValueError("unknown GOAL full-product attestation event_type")
        if not self._v2_row_is_well_formed(row):
            raise ValueError("malformed GOAL full-product v2 attestation event")
        owner = _owner(row.get("owner_user_id"))
        raw = row.get("attestation")
        if not isinstance(raw, dict):
            raise ValueError(
                "GOAL full-product attestation event is missing attestation"
            )
        record = goal_full_product_entrypoint_attestation_from_dict(raw)
        decision = (
            self._validate_current_unlocked(record, owner_user_id=owner)
            if persist
            else GoalFullProductDecision(
                not self._shape_violations(record, owner_user_id=owner),
                self._shape_violations(record, owner_user_id=owner),
            )
        )
        if not decision.accepted:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        key = (owner, record.attestation_ref)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("GOAL full-product attestation identity collision")
            return existing
        if persist:
            self._append(row)
        self._records[key] = record
        return record

    def _append(self, row: dict[str, Any]) -> None:
        self._require_legacy_write_allowed()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["attestation"]
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        existing_record = existing.get("attestation")
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id")
                            == row.get("owner_user_id")
                            and isinstance(existing_record, dict)
                            and existing_record.get("attestation_ref")
                            == incoming.get("attestation_ref")
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                "GOAL full-product attestation identity collision "
                                f"at {self._path}:{line_no}"
                            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError(
                            "GOAL full-product attestation row must be an object"
                        )
                    raw = row.get("attestation")
                    if not isinstance(raw, dict):
                        raise ValueError(
                            "GOAL full-product attestation event is missing attestation"
                        )
                    version = (
                        LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
                        if "attestation_version" not in raw
                        else raw.get("attestation_version")
                    )
                    if version == LEGACY_FULL_PRODUCT_ATTESTATION_VERSION:
                        if not self._legacy_v1_row_is_well_formed(row):
                            raise ValueError(
                                "malformed legacy GOAL full-product attestation"
                            )
                        self._legacy_quarantined_count += 1
                        continue
                    if version != FULL_PRODUCT_ATTESTATION_VERSION:
                        raise ValueError(
                            "unknown GOAL full-product attestation version"
                        )
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        "invalid persisted GOAL full-product attestation at "
                        f"{self._path}:{line_no}"
                    ) from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._records = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    def _overlay_canonical_unlocked(self) -> None:
        if self._proof_projection is None:
            self._proof_head_types = {}
            return
        canonical_by_type, self._proof_head_types = (
            self._proof_projection.decode_many_with_index(
                GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC
            )
        )
        for record in canonical_by_type[LOGICAL_TYPE_FULL_PRODUCT_ATTESTATION]:
            owner = _owner(record.owner_user_id)
            key = (owner, record.attestation_ref)
            existing = self._records.get(key)
            if existing is not None and existing != record:
                raise ValueError(
                    "canonical GOAL full-product attestation collides with "
                    f"legacy record for owner/ref {owner!r}/"
                    f"{record.attestation_ref!r}"
                )
            self._apply_row(self._event(record), persist=False)

    def _require_legacy_write_allowed(self) -> None:
        if self._legacy_read_only:
            raise RuntimeError(
                f"{ATOMIC_PROOF_BUNDLE_REQUIRED}: "
                "GOAL full-product attestation legacy JSONL is read-only"
            )

    @contextmanager
    def _attestation_file_lock(self):
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

    def refresh(self) -> None:
        """Reload the current durable attestation projection under its file lock."""

        with self._process_lock:
            with self._attestation_file_lock():
                self._refresh_from_disk_unlocked()
            self._overlay_canonical_unlocked()

    def _refresh_current_dependencies(self) -> None:
        """Refresh every durable view used by current-attestation validation."""

        for store in (
            self._validation_receipt_registry,
            self._compiler_store,
            self._entrypoint_registry,
            self._lineage_aggregate_registry,
            self._semantic_proof_registry,
            self._section_coverage_registry,
        ):
            refresh = getattr(store, "refresh", None)
            if callable(refresh):
                refresh()

    @contextmanager
    def _current_read_boundary(self):
        """Linearize dependency refresh, projection replay, and current read."""

        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            self._refresh_current_dependencies()
            with self._process_lock:
                with self._attestation_file_lock():
                    self._refresh_from_disk_unlocked()
                    self._overlay_canonical_unlocked()
                    yield

    @staticmethod
    def _event(
        record: GoalFullProductEntrypointAttestation,
    ) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "event_type": "goal_full_product_attestation_recorded",
            "owner_user_id": record.owner_user_id,
            "attestation": asdict(record),
        }

    def record_attestation(
        self,
        record: GoalFullProductEntrypointAttestation,
    ) -> GoalFullProductEntrypointAttestation:
        self._require_legacy_write_allowed()
        _owner(record.owner_user_id)
        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            self._refresh_current_dependencies()
            return self._record_attestation_locked(record)

    def _record_attestation_locked(
        self,
        record: GoalFullProductEntrypointAttestation,
    ) -> GoalFullProductEntrypointAttestation:
        """Persist after the caller has entered the shared proof-head boundary."""

        with self._process_lock:
            with self._attestation_file_lock():
                self._refresh_from_disk_unlocked()
            return self._apply_row(self._event(record), persist=True)

    def _attestation_unlocked(
        self,
        attestation_ref: str,
        *,
        owner_user_id: str,
    ) -> GoalFullProductEntrypointAttestation:
        owner = _owner(owner_user_id)
        ref = str(attestation_ref or "").strip()
        if self._proof_projection is not None:
            current_type = self._proof_head_types.get((owner, ref))
            if (
                current_type is not None
                and current_type != LOGICAL_TYPE_FULL_PRODUCT_ATTESTATION
            ):
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_FULL_PRODUCT_ATTESTATION!r}"
                )
        return self._records[(owner, ref)]

    def attestation(
        self,
        attestation_ref: str,
        *,
        owner_user_id: str,
    ) -> GoalFullProductEntrypointAttestation:
        with self._current_read_boundary():
            return self._attestation_unlocked(
                attestation_ref,
                owner_user_id=owner_user_id,
            )

    def _records_unlocked(
        self,
        *,
        owner_user_id: str,
    ) -> list[GoalFullProductEntrypointAttestation]:
        owner = _owner(owner_user_id)
        return [
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == owner
        ]

    def records(
        self,
        *,
        owner_user_id: str,
    ) -> list[GoalFullProductEntrypointAttestation]:
        with self._current_read_boundary():
            return self._records_unlocked(owner_user_id=owner_user_id)

    def current_records_with_decisions(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[
        tuple[
            GoalFullProductEntrypointAttestation,
            GoalFullProductDecision,
        ],
        ...,
    ]:
        """Return persisted rows and current decisions from one proof-head view."""

        owner = _owner(owner_user_id)
        with self._current_read_boundary():
            return tuple(
                (
                    record,
                    self._validate_current_unlocked(
                        record,
                        owner_user_id=owner,
                    ),
                )
                for record in self._records_unlocked(owner_user_id=owner)
            )

    def rollback_exact_attestation(
        self,
        record: GoalFullProductEntrypointAttestation,
        *,
        dependent_refs: tuple[str, ...],
    ) -> bool:
        """Remove one exact attestation after callers prove dependents are absent."""

        self._require_legacy_write_allowed()
        owner = _owner(record.owner_user_id)
        dependencies = tuple(str(ref or "").strip() for ref in dependent_refs)
        if any(not ref for ref in dependencies):
            raise ValueError(
                "GOAL full-product attestation rollback dependent_refs must be "
                "non-empty refs"
            )
        if dependencies:
            raise ValueError(
                "GOAL full-product attestation rollback refused because live "
                "records reference it: "
                + ",".join(dependencies)
            )

        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            with self._process_lock, self._attestation_file_lock():
                self._refresh_from_disk_unlocked()
                key = (owner, record.attestation_ref)
                persisted = self._records.get(key)
                if persisted is None:
                    foreign_matches = tuple(
                        candidate
                        for (_candidate_owner, candidate_ref), candidate in (
                            self._records.items()
                        )
                        if candidate_ref == record.attestation_ref
                    )
                    if foreign_matches:
                        raise ValueError(
                            "GOAL full-product attestation rollback owner identity "
                            "mismatch"
                        )
                    return False
                if persisted != record:
                    raise ValueError(
                        "GOAL full-product attestation rollback identity mismatch"
                    )
                expected = json.loads(
                    json.dumps(
                        self._event(record),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                rows: list[dict[str, Any]] = []
                if self._path.exists():
                    with self._path.open("r", encoding="utf-8") as fh:
                        rows = [json.loads(line) for line in fh if line.strip()]
                if sum(row == expected for row in rows) != 1:
                    raise ValueError(
                        "GOAL full-product attestation rollback exact persisted "
                        "event is not unique"
                    )
                retained = tuple(row for row in rows if row != expected)
                _atomic_rewrite_attestation_rows(self._path, retained)
                self._refresh_from_disk_unlocked()
                return True

    def is_canonical_current(
        self,
        record: GoalFullProductEntrypointAttestation,
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        """Return whether ``record`` is the exact live SQLite proof head."""

        if self._proof_projection is None:
            return False
        if owner_user_id is not None and _owner(owner_user_id) != _owner(
            record.owner_user_id
        ):
            return False
        return self._proof_projection.is_exact_current(
            record,
            codec=GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
        )


class GoalFullProductEntrypointProducer:
    """Preflight-all, forward-resumable terminal producer."""

    def __init__(
        self,
        *,
        attestation_registry: PersistentGoalFullProductEntrypointAttestationRegistry,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        compiler_store: PersistentCompilerIRStore,
        validation_receipt_registry: PersistentGoalValidationReceiptRegistry,
        terminal_aggregate_registry: Any,
        proof_ledger: GoalProofLedger | None = None,
    ) -> None:
        self._attestation_registry = attestation_registry
        self._entrypoint_registry = entrypoint_registry
        self._compiler_store = compiler_store
        self._validation_receipt_registry = validation_receipt_registry
        self._terminal_aggregate_registry = terminal_aggregate_registry
        self._proof_ledger = proof_ledger
        self._process_lock = threading.RLock()
        if proof_ledger is not None:
            self._require_atomic_ledger_composition(proof_ledger)

    @staticmethod
    def _registry_proof_ledger(registry: Any) -> GoalProofLedger | None:
        candidate = getattr(registry, "_delegate", registry)
        projection = getattr(candidate, "_proof_projection", None)
        ledger = getattr(projection, "ledger", None)
        return ledger if isinstance(ledger, GoalProofLedger) else None

    def _require_atomic_ledger_composition(
        self,
        proof_ledger: GoalProofLedger,
    ) -> None:
        for label, registry in (
            ("attestation", self._attestation_registry),
            ("entrypoint coverage", self._entrypoint_registry),
            ("compiler", self._compiler_store),
            ("validation receipt", self._validation_receipt_registry),
            ("terminal aggregate", self._terminal_aggregate_registry),
        ):
            if self._registry_proof_ledger(registry) is not proof_ledger:
                raise TypeError(
                    "GOAL full-product atomic producer requires one shared proof "
                    f"ledger across the {label} registry"
                )

    @staticmethod
    def _exact_present(loader: Any, expected: Any, *, label: str) -> bool:
        try:
            observed = loader()
        except (KeyError, LookupError):
            return False
        if observed != expected:
            raise ValueError(f"{label} persisted identity mismatch")
        return True

    def _refresh_views(self) -> None:
        for store in (
            self._validation_receipt_registry,
            self._compiler_store,
            self._entrypoint_registry,
            self._attestation_registry._lineage_aggregate_registry,
            self._attestation_registry._semantic_proof_registry,
            self._attestation_registry._section_coverage_registry,
            self._attestation_registry,
            self._terminal_aggregate_registry,
        ):
            refresh = getattr(store, "refresh", None)
            if callable(refresh):
                refresh()

    def _candidate_presence(
        self,
        candidate: GoalFullProductCandidate,
        *,
        owner: str,
    ) -> dict[str, bool]:
        return {
            GoalFullProductCommitStage.ATTESTATION.value: self._exact_present(
                lambda: self._attestation_registry.attestation(
                    candidate.attestation.attestation_ref,
                    owner_user_id=owner,
                ),
                candidate.attestation,
                label="full-product attestation",
            ),
            GoalFullProductCommitStage.VALIDATION_RECEIPT.value: self._exact_present(
                lambda: self._validation_receipt_registry.receipt(
                    candidate.validation_receipt.validation_ref,
                    owner_user_id=owner,
                ),
                candidate.validation_receipt,
                label="full-product validation receipt",
            ),
            GoalFullProductCommitStage.COMPILER_IR.value: self._exact_present(
                lambda: self._attestation_registry._current_compiler_ir(
                    candidate.compiler_ir.ir_ref,
                    owner=owner,
                ),
                candidate.compiler_ir,
                label="full-product compiler IR",
            ),
            GoalFullProductCommitStage.COMPILER_PASS.value: self._exact_present(
                lambda: self._attestation_registry._current_compiler_pass(
                    candidate.compiler_pass.pass_ref,
                    owner=owner,
                ),
                candidate.compiler_pass,
                label="full-product compiler pass",
            ),
            GoalFullProductCommitStage.COVERAGE.value: self._exact_present(
                lambda: self._attestation_registry._current_entrypoint_coverage(
                    candidate.coverage.coverage_ref,
                    owner=owner,
                ),
                candidate.coverage,
                label="full-product entrypoint coverage",
            ),
        }

    def _commit_error(
        self,
        *,
        entry_source: str,
        stage: GoalFullProductCommitStage,
        completed_stages: tuple[str, ...],
        cause: Exception,
        candidates: tuple[GoalFullProductCandidate, ...],
        initial: dict[str, dict[str, bool]],
        owner: str,
    ) -> GoalFullProductCommitError:
        state_unchanged = False
        try:
            self._refresh_views()
            current = {
                candidate.attestation.entry_source: self._candidate_presence(
                    candidate,
                    owner=owner,
                )
                for candidate in candidates
            }
            state_unchanged = current == initial
        except Exception:  # noqa: BLE001 - failed observation is not unchanged.
            state_unchanged = False
        return GoalFullProductCommitError(
            entry_source=entry_source,
            stage=stage,
            completed_stages=completed_stages,
            cause=cause,
            compensation_attempted=False,
            compensation_verified=False,
            state_unchanged=state_unchanged,
        )

    def record_current_all(
        self,
        *,
        owner_user_id: str,
    ) -> GoalFullProductCommitResult:
        owner = _owner(owner_user_id)
        with self._process_lock:
            try:
                with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
                    if self._proof_ledger is not None:
                        return self._record_current_all_atomic_locked(owner=owner)
                    return self._record_current_all_locked(owner=owner)
            except GoalFullProductCommitError:
                raise
            except Exception as exc:  # noqa: BLE001 - lock/setup failure is preflight.
                raise GoalFullProductCommitError(
                    entry_source="",
                    stage=GoalFullProductCommitStage.PREFLIGHT,
                    completed_stages=(),
                    cause=exc,
                ) from exc

    def _validate_atomic_candidate(
        self,
        candidate: GoalFullProductCandidate,
        *,
        owner: str,
    ) -> GoalFullProductCandidate:
        if not isinstance(candidate, GoalFullProductCandidate):
            raise TypeError("GOAL full-product atomic candidate type mismatch")
        attestation = self._attestation_registry.prepare_attestation_candidate(
            candidate.attestation,
            owner_user_id=owner,
        )
        receipt = candidate.validation_receipt
        receipt_decision = validate_goal_validation_receipt_shape(receipt)
        if not receipt_decision.accepted:
            raise ValueError(
                "derived full-product validation receipt is invalid: "
                + _decision_codes(receipt_decision)
            )
        if (
            receipt.owner_user_id != owner
            or receipt.outcome != GoalValidationOutcome.PASSED.value
            or tuple(receipt.residuals)
            or receipt.validation_ref != receipt.canonical_validation_ref
            or tuple(receipt.subject_qro_refs) != tuple(attestation.qro_refs)
            or tuple(receipt.graph_command_refs)
            != tuple(attestation.research_graph_command_refs)
            or tuple(receipt.evidence_refs) != (attestation.attestation_ref,)
            or tuple(receipt.evidence_digests) != (_sha256(attestation),)
        ):
            raise ValueError(
                "derived full-product validation receipt is recombined"
            )
        ir_decision = validate_compiler_ir(candidate.compiler_ir)
        pass_decision = validate_compiler_pass(candidate.compiler_pass)
        if not ir_decision.accepted:
            raise ValueError(
                "derived full-product compiler IR is invalid: "
                + _decision_codes(ir_decision)
            )
        if not pass_decision.accepted:
            raise ValueError(
                "derived full-product compiler pass is invalid: "
                + _decision_codes(pass_decision)
            )
        coverage = self._entrypoint_registry.prepare_record_candidate(
            candidate.coverage
        )
        if (
            attestation.owner_user_id != owner
            or receipt.owner_user_id != owner
            or candidate.compiler_ir.owner != owner
            or candidate.compiler_pass.actor != owner
            or coverage.recorded_by != owner
        ):
            raise ValueError("derived full-product candidate owner mismatch")
        if (
            attestation.derived_ir_ref != candidate.compiler_ir.ir_ref
            or attestation.derived_pass_ref != candidate.compiler_pass.pass_ref
            or attestation.derived_coverage_ref != coverage.coverage_ref
            or tuple(candidate.compiler_ir.validation_refs)
            != (receipt.validation_ref,)
            or tuple(candidate.compiler_pass.validation_refs)
            != (receipt.validation_ref,)
            or tuple(coverage.validation_refs) != (receipt.validation_ref,)
            or tuple(candidate.compiler_ir.evidence_refs)
            != (attestation.attestation_ref,)
            or tuple(candidate.compiler_pass.evidence_refs)
            != (attestation.attestation_ref,)
            or tuple(coverage.evidence_refs) != (attestation.attestation_ref,)
            or candidate.compiler_pass.output_ir_ref != candidate.compiler_ir.ir_ref
            or tuple(coverage.compiler_ir_refs) != (candidate.compiler_ir.ir_ref,)
            or tuple(coverage.compiler_pass_refs)
            != (candidate.compiler_pass.pass_ref,)
        ):
            raise ValueError("derived full-product candidate lineage is recombined")
        return candidate

    def _atomic_bundle(
        self,
        *,
        owner: str,
        candidates: tuple[GoalFullProductCandidate, ...],
        terminal: GoalEntrypointAggregateRecord,
    ) -> ProofBundle:
        members = []
        for candidate in candidates:
            attestation = candidate.attestation
            receipt = candidate.validation_receipt
            compiler_ir = candidate.compiler_ir
            compiler_pass = candidate.compiler_pass
            coverage = candidate.coverage
            if {
                attestation.owner_user_id,
                receipt.owner_user_id,
                compiler_ir.owner,
                compiler_pass.actor,
                coverage.recorded_by,
            } != {owner}:
                raise ValueError(
                    "GOAL full-product atomic bundle cannot span owners"
                )
            members.extend(
                (
                    typed_proof_record_member(
                        attestation,
                        codec=GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
                    ),
                    typed_proof_record_member(
                        receipt,
                        codec=GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
                        depends_on=(attestation.attestation_ref,),
                    ),
                    typed_proof_record_member(
                        compiler_ir,
                        codec=COMPILER_IR_PROOF_CODEC,
                        depends_on=(
                            attestation.attestation_ref,
                            receipt.validation_ref,
                        ),
                    ),
                    typed_proof_record_member(
                        compiler_pass,
                        codec=COMPILER_PASS_PROOF_CODEC,
                        depends_on=(
                            attestation.attestation_ref,
                            receipt.validation_ref,
                            compiler_ir.ir_ref,
                        ),
                    ),
                    typed_proof_record_member(
                        coverage,
                        codec=GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                        depends_on=(
                            attestation.attestation_ref,
                            receipt.validation_ref,
                            compiler_ir.ir_ref,
                            compiler_pass.pass_ref,
                        ),
                    ),
                )
            )
        expected_coverage_refs = tuple(
            candidate.coverage.coverage_ref for candidate in candidates
        )
        if (
            terminal.recorded_by != owner
            or tuple(terminal.coverage_refs) != expected_coverage_refs
        ):
            raise ValueError(
                "GOAL full-product terminal aggregate is recombined"
            )
        members.append(
            typed_proof_record_member(
                terminal,
                codec=GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC,
                depends_on=tuple(terminal.coverage_refs),
            )
        )
        expected_count = len(REQUIRED_ENTRY_SOURCES) * 5 + 1
        if len(members) != expected_count:
            raise ValueError("GOAL full-product atomic bundle member count mismatch")
        refs = tuple(member.logical_ref for member in members)
        if len(refs) != len(set(refs)):
            raise ValueError("GOAL full-product atomic bundle ref collision")
        return ProofBundle(
            owner=owner,
            subject=f"goal_full_product_bundle:{terminal.aggregate_ref}",
            members=tuple(members),
            metadata={
                "aggregate_ref": terminal.aggregate_ref,
                "entry_sources": list(REQUIRED_ENTRY_SOURCES),
                "member_count": expected_count,
            },
        )

    @staticmethod
    def _atomic_completed_stages() -> tuple[str, ...]:
        return tuple(
            stage.value
            for stage in (
                GoalFullProductCommitStage.ATTESTATION,
                GoalFullProductCommitStage.VALIDATION_RECEIPT,
                GoalFullProductCommitStage.COMPILER_IR,
                GoalFullProductCommitStage.COMPILER_PASS,
                GoalFullProductCommitStage.COVERAGE,
                GoalFullProductCommitStage.COVERAGE_VALIDATION,
            )
        )

    def _record_current_all_atomic_locked(
        self,
        *,
        owner: str,
    ) -> GoalFullProductCommitResult:
        assert self._proof_ledger is not None
        try:
            before_digest = self._proof_ledger.current(owner=owner).head_digest
            self._refresh_views()
            candidates = tuple(
                self._validate_atomic_candidate(candidate, owner=owner)
                for candidate in (
                    self._attestation_registry._prepare_current_all_unlocked(
                        owner_user_id=owner
                    )
                )
            )
            if tuple(
                candidate.attestation.entry_source for candidate in candidates
            ) != tuple(REQUIRED_ENTRY_SOURCES):
                raise ValueError(
                    "GOAL full-product atomic candidate source order mismatch"
                )
            terminal = self._terminal_aggregate_registry.prepare_from_coverages(
                tuple(candidate.coverage for candidate in candidates),
                owner_user_id=owner,
            )
            bundle = self._atomic_bundle(
                owner=owner,
                candidates=candidates,
                terminal=terminal,
            )
            if self._proof_ledger.current(owner=owner).head_digest != before_digest:
                raise ValueError(
                    "GOAL proof heads changed while preparing the atomic bundle"
                )
        except Exception as exc:  # noqa: BLE001 - preserve preflight failure.
            raise GoalFullProductCommitError(
                entry_source="",
                stage=GoalFullProductCommitStage.PREFLIGHT,
                completed_stages=(),
                cause=exc,
            ) from exc

        try:
            committed_bundle = self._proof_ledger.commit(bundle)
        except Exception as exc:  # noqa: BLE001 - one SQL transaction or uncertainty.
            state_unchanged = False
            try:
                state_unchanged = (
                    self._proof_ledger.current(owner=owner).head_digest
                    == before_digest
                )
            except Exception:  # noqa: BLE001 - observation failure is uncertain.
                state_unchanged = False
            raise GoalFullProductCommitError(
                entry_source="",
                stage=GoalFullProductCommitStage.FINAL_AGGREGATE,
                completed_stages=(),
                cause=exc,
                state_unchanged=state_unchanged,
            ) from exc

        completed_stages = self._atomic_completed_stages()
        try:
            expected_refs = {member.logical_ref for member in bundle.members}
            if {head.logical_ref for head in committed_bundle.heads} != expected_refs:
                raise ValueError(
                    "GOAL full-product commit returned an incomplete proof bundle"
                )
            committed_by_ref = {
                head.logical_ref: head for head in committed_bundle.heads
            }
            validation_snapshot = self._proof_ledger.current(owner=owner)
            validation_by_ref = {
                head.logical_ref: head for head in validation_snapshot.heads
            }
            if any(
                validation_by_ref.get(logical_ref) != committed_by_ref[logical_ref]
                for logical_ref in expected_refs
            ):
                raise ValueError(
                    "GOAL full-product proof bundle is not one exact current "
                    "ledger generation"
                )
            typed_records: dict[str, tuple[Any, ProofRecordCodec[Any]]] = {
                terminal.aggregate_ref: (
                    terminal,
                    GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC,
                )
            }
            for candidate in candidates:
                typed_records.update(
                    {
                        candidate.attestation.attestation_ref: (
                            candidate.attestation,
                            GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
                        ),
                        candidate.validation_receipt.validation_ref: (
                            candidate.validation_receipt,
                            GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
                        ),
                        candidate.compiler_ir.ir_ref: (
                            candidate.compiler_ir,
                            COMPILER_IR_PROOF_CODEC,
                        ),
                        candidate.compiler_pass.pass_ref: (
                            candidate.compiler_pass,
                            COMPILER_PASS_PROOF_CODEC,
                        ),
                        candidate.coverage.coverage_ref: (
                            candidate.coverage,
                            GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                        ),
                    }
                )
            if set(typed_records) != expected_refs:
                raise ValueError(
                    "GOAL full-product typed proof map is incomplete"
                )
            for logical_ref, (expected_record, codec) in typed_records.items():
                decoded = decode_proof_record_head(
                    validation_by_ref[logical_ref],
                    codec=codec,
                )
                if decoded != expected_record:
                    raise ValueError(
                        "GOAL full-product canonical record projection mismatch"
                    )
            self._refresh_views()
            entrypoint_projection = getattr(
                self._entrypoint_registry,
                "_delegate",
                self._entrypoint_registry,
            )
            projected_records: dict[str, Any] = {
                **{
                    ref: record
                    for (record_owner, ref), record in (
                        self._attestation_registry._records.items()
                    )
                    if record_owner == owner
                },
                **{
                    ref: record
                    for (record_owner, ref), record in (
                        self._validation_receipt_registry._records.items()
                    )
                    if record_owner == owner
                },
                **{
                    ref: record
                    for (record_owner, ref), record in self._compiler_store._irs.items()
                    if record_owner == owner
                },
                **{
                    ref: record
                    for (record_owner, ref), record in self._compiler_store._passes.items()
                    if record_owner == owner
                },
                **{
                    ref: record
                    for (record_owner, ref), record in (
                        entrypoint_projection._records.items()
                    )
                    if record_owner == owner
                },
                **{
                    ref: record
                    for (record_owner, ref), record in (
                        self._terminal_aggregate_registry._records.items()
                    )
                    if record_owner == owner
                },
            }
            if any(
                projected_records.get(logical_ref) != expected_record
                for logical_ref, (expected_record, _codec) in typed_records.items()
            ):
                raise ValueError(
                    "GOAL full-product canonical registry projection is incomplete"
                )
            source_results: list[GoalFullProductSourceCommit] = []
            for candidate in candidates:
                source_results.append(
                    GoalFullProductSourceCommit(
                        entry_source=candidate.attestation.entry_source,
                        attestation_ref=candidate.attestation.attestation_ref,
                        validation_ref=candidate.validation_receipt.validation_ref,
                        compiler_ir_ref=candidate.compiler_ir.ir_ref,
                        compiler_pass_ref=candidate.compiler_pass.pass_ref,
                        coverage_ref=candidate.coverage.coverage_ref,
                        completed_stages=completed_stages,
                    )
                )
            final_snapshot = self._proof_ledger.current(owner=owner)
            if final_snapshot.head_digest != validation_snapshot.head_digest:
                raise ValueError(
                    "GOAL proof heads changed during canonical projection validation"
                )
        except Exception as exc:  # noqa: BLE001 - committed but not proven usable.
            raise GoalFullProductCommitError(
                entry_source="",
                stage=GoalFullProductCommitStage.FINAL_AGGREGATE,
                completed_stages=completed_stages,
                cause=exc,
                state_unchanged=False,
            ) from exc
        return GoalFullProductCommitResult(
            sources=tuple(source_results),
            final_aggregate_ref=terminal.aggregate_ref,
        )

    def _record_current_all_locked(
        self,
        *,
        owner: str,
    ) -> GoalFullProductCommitResult:
        try:
            self._refresh_views()
            candidates = tuple(
                self._attestation_registry._prepare_current_all_unlocked(
                    owner_user_id=owner
                )
            )
            initial = {
                candidate.attestation.entry_source: self._candidate_presence(
                    candidate,
                    owner=owner,
                )
                for candidate in candidates
            }
        except Exception as exc:  # noqa: BLE001 - preserve exact preflight failure.
            raise GoalFullProductCommitError(
                entry_source="",
                stage=GoalFullProductCommitStage.PREFLIGHT,
                completed_stages=(),
                cause=exc,
            ) from exc

        committed: list[GoalFullProductSourceCommit] = []
        for candidate in candidates:
            source = candidate.attestation.entry_source
            stages: list[str] = []
            stage = GoalFullProductCommitStage.ATTESTATION
            try:
                if not initial[source][stage.value]:
                    self._attestation_registry.record_attestation(
                        candidate.attestation
                    )
                stages.append(stage.value)
                stage = GoalFullProductCommitStage.VALIDATION_RECEIPT
                if not initial[source][stage.value]:
                    self._validation_receipt_registry.record_receipt(
                        candidate.validation_receipt
                    )
                stages.append(stage.value)
                stage = GoalFullProductCommitStage.COMPILER_IR
                if not initial[source][stage.value]:
                    self._compiler_store.record_ir(candidate.compiler_ir)
                stages.append(stage.value)
                stage = GoalFullProductCommitStage.COMPILER_PASS
                if not initial[source][stage.value]:
                    self._compiler_store.record_pass(candidate.compiler_pass)
                stages.append(stage.value)
                stage = GoalFullProductCommitStage.COVERAGE
                if not initial[source][stage.value]:
                    recorded_coverage = self._entrypoint_registry.record_coverage(
                        candidate.coverage
                    )
                else:
                    recorded_coverage = candidate.coverage
                stages.append(stage.value)
                stage = GoalFullProductCommitStage.COVERAGE_VALIDATION
                decision = (
                    self._attestation_registry._validate_full_product_coverage_unlocked(
                        recorded_coverage,
                        owner_user_id=owner,
                    )
                )
                if not decision.accepted:
                    raise ValueError(
                        ";".join(
                            f"{item.code}:{item.field}:{item.ref}"
                            for item in decision.violations
                        )
                    )
                stages.append(stage.value)
            except Exception as exc:  # noqa: BLE001 - report exact partial stage.
                raise self._commit_error(
                    entry_source=source,
                    stage=stage,
                    completed_stages=tuple(stages),
                    cause=exc,
                    candidates=candidates,
                    initial=initial,
                    owner=owner,
                ) from exc
            committed.append(
                GoalFullProductSourceCommit(
                    entry_source=source,
                    attestation_ref=candidate.attestation.attestation_ref,
                    validation_ref=candidate.validation_receipt.validation_ref,
                    compiler_ir_ref=candidate.compiler_ir.ir_ref,
                    compiler_pass_ref=candidate.compiler_pass.pass_ref,
                    coverage_ref=candidate.coverage.coverage_ref,
                    completed_stages=tuple(stages),
                )
            )

        if tuple(item.entry_source for item in committed) != tuple(
            REQUIRED_ENTRY_SOURCES
        ):
            exc = ValueError(
                "terminal aggregate requires six validated source commits"
            )
            raise self._commit_error(
                entry_source="",
                stage=GoalFullProductCommitStage.FINAL_AGGREGATE,
                completed_stages=tuple(
                    stage
                    for item in committed
                    for stage in item.completed_stages
                ),
                cause=exc,
                candidates=candidates,
                initial=initial,
                owner=owner,
            ) from exc
        try:
            self._refresh_views()
            final_candidates = (
                self._attestation_registry._prepare_current_all_unlocked(
                    owner_user_id=owner
                )
            )
            expected_refs = tuple(
                candidate.coverage.coverage_ref
                for candidate in final_candidates
            )
            committed_refs = tuple(item.coverage_ref for item in committed)
            if committed_refs != expected_refs:
                raise ValueError(
                    "current proof heads changed during the cross-ledger commit"
            )
            for coverage_ref in committed_refs:
                coverage = self._attestation_registry._current_entrypoint_coverage(
                    coverage_ref,
                    owner=owner,
                )
                decision = (
                    self._attestation_registry._validate_full_product_coverage_unlocked(
                        coverage,
                        owner_user_id=owner,
                    )
                )
                if not decision.accepted:
                    raise ValueError(
                        ";".join(
                            f"{item.code}:{item.field}:{item.ref}"
                            for item in decision.violations
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - final gate fails closed.
            raise self._commit_error(
                entry_source="",
                stage=GoalFullProductCommitStage.FINAL_AGGREGATE,
                completed_stages=tuple(
                    stage
                    for item in committed
                    for stage in item.completed_stages
                ),
                cause=exc,
                candidates=candidates,
                initial=initial,
                owner=owner,
            ) from exc
        try:
            terminal_candidate = self._terminal_aggregate_registry.build_current(
                owner_user_id=owner
            )
            terminal = self._terminal_aggregate_registry.record_current(
                owner_user_id=owner
            )
        except Exception as exc:  # noqa: BLE001 - preserve aggregate failure.
            terminal = None
            if "terminal_candidate" in locals():
                try:
                    refresh_terminal = getattr(
                        self._terminal_aggregate_registry,
                        "refresh",
                        None,
                    )
                    if callable(refresh_terminal):
                        refresh_terminal()
                    persisted_terminal = self._terminal_aggregate_registry.aggregate(
                        terminal_candidate.aggregate_ref,
                        owner_user_id=owner,
                    )
                    violations = self._terminal_aggregate_registry.validate_current(
                        persisted_terminal,
                        owner_user_id=owner,
                    )
                    if persisted_terminal == terminal_candidate and not violations:
                        terminal = persisted_terminal
                except Exception:  # noqa: BLE001 - recovery must fail closed.
                    pass
            if terminal is None:
                raise self._commit_error(
                    entry_source="",
                    stage=GoalFullProductCommitStage.FINAL_AGGREGATE,
                    completed_stages=tuple(
                        completed_stage
                        for item in committed
                        for completed_stage in item.completed_stages
                    ),
                    cause=exc,
                    candidates=candidates,
                    initial=initial,
                    owner=owner,
                ) from exc
        return GoalFullProductCommitResult(
            sources=tuple(committed),
            final_aggregate_ref=str(terminal.aggregate_ref),
        )


__all__ = [
    "FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER",
    "FULL_PRODUCT_ATTESTATION_VERSION",
    "FULL_PRODUCT_COMPILER_VERSION",
    "FULL_PRODUCT_VALIDATOR_IDENTIFIER",
    "GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC",
    "GoalFullProductCandidate",
    "GoalFullProductClosureSnapshot",
    "GoalFullProductCommitError",
    "GoalFullProductCommitResult",
    "GoalFullProductCommitStage",
    "GoalFullProductDecision",
    "GoalFullProductEntrypointAttestation",
    "GoalFullProductEntrypointProducer",
    "GoalFullProductSnapshot",
    "GoalFullProductSourceCommit",
    "GoalFullProductViolation",
    "LEGACY_FULL_PRODUCT_ATTESTATION_VERSION",
    "LOGICAL_TYPE_FULL_PRODUCT_ATTESTATION",
    "PersistentGoalFullProductEntrypointAttestationRegistry",
    "goal_full_product_entrypoint_attestation_from_dict",
]
