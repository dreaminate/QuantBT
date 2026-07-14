"""Durable, owner-scoped current closure proof for GOAL section 12.

The execution-boundary ledgers remain the canonical producers.  This module
does not place an order, call a venue, read a secret, or manufacture missing
execution evidence.  It resolves one exact intent -> promotion ->
materialization -> connectivity -> safety -> capability -> submit request ->
submission -> venue event -> reconciliation chain and writes a content-bound
receipt only when that complete chain is current for one owner.

The receipt proves local durable execution-boundary lineage.  It deliberately
does not claim that testnet, live, CI, production, or an external venue is
available merely because refs were recorded.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .execution_boundary import (
    ExecutionOrderIntentRecord,
    ExecutionOrderMaterializationRecord,
    ExecutionOrderSubmissionRecord,
    ExecutionReconciliationActionRecord,
    ExecutionReconciliationRecord,
    ExecutionSubmitRequestRecord,
    ExecutionVenueCapabilityRecord,
    ExecutionVenueConnectivityCheckRecord,
    ExecutionVenueEventRecord,
    ExecutionVenueSafetyAttestationRecord,
    PersistentExecutionOrderIntentRegistry,
    PersistentExecutionOrderMaterializationRegistry,
    PersistentExecutionOrderSubmissionRegistry,
    PersistentExecutionReconciliationActionRegistry,
    PersistentExecutionReconciliationRegistry,
    PersistentExecutionSubmitRequestRegistry,
    PersistentExecutionVenueCapabilityRegistry,
    PersistentExecutionVenueConnectivityCheckRegistry,
    PersistentExecutionVenueEventRegistry,
    PersistentExecutionVenueSafetyAttestationRegistry,
    PersistentRuntimePromotionRegistry,
    PersistentUserRiskChoiceRegistry,
    RuntimePromotionRecord,
    UserRiskChoiceRecord,
    validate_execution_order_intent,
    validate_execution_order_materialization,
    validate_execution_order_submission,
    validate_execution_reconciliation,
    validate_execution_reconciliation_action,
    validate_execution_submit_request,
    validate_execution_venue_capability,
    validate_execution_venue_connectivity_check,
    validate_execution_venue_event,
    validate_execution_venue_safety_attestation,
    validate_runtime_promotion_record,
    validate_user_risk_choice,
)
from .goal_coverage import strict_current_entrypoint_lookup
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)
from .ref_resolution import is_placeholder_ref


EXECUTION_CLOSURE_SCHEMA_VERSION = 2
EXECUTION_CLOSURE_RECEIPT_VERSION = "execution_closure_receipt.v1"
EXECUTION_CLOSURE_ENTRYPOINT_REF = "api:goal.execution_closure.current"

_TERMINAL_RECONCILIATION_STATUSES = frozenset(
    {"reconciled", "closed_no_fill", "closed_partial_fill"}
)
_CURRENT_SUBMISSION_STATUSES = frozenset({"accepted", "rejected"})
_FRESH_COMPONENT_KINDS = frozenset(
    {"venue_connectivity_check", "venue_safety_attestation", "venue_capability"}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(item for raw in values if (item := _text(raw)))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable(value: Any) -> Any:
    if hasattr(value, "value"):
        return _stable(value.value)
    if is_dataclass(value):
        return _stable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    return value


def _state_hash(value: Any) -> str:
    return "sha256:" + _sha256(_stable(value))


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner or owner != value or any(ord(char) < 32 for char in owner):
        raise ValueError("owner_user_id must be a stable non-empty exact string")
    if is_placeholder_ref(owner):
        raise ValueError("owner_user_id cannot contain a placeholder token")
    return owner


def _real_ref(value: Any, *, field: str) -> str:
    ref = _text(value)
    if not ref:
        raise ValueError(f"{field} is required")
    if is_placeholder_ref(ref):
        raise ValueError(
            f"{field} cannot be synthetic, fixture, test-only, placeholder, or goal-closure material"
        )
    return ref


def _exact_unique(values: tuple[str, ...], *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    normalized = _refs(values)
    if (not allow_empty and not normalized) or len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must be an exact unique ref set")
    for ref in normalized:
        _real_ref(ref, field=field)
    return tuple(sorted(normalized))


def _aware_time(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    return parsed.astimezone(UTC)


def _record_ref(record: Any) -> str:
    field_by_type = (
        (ExecutionOrderIntentRecord, "order_intent_ref"),
        (RuntimePromotionRecord, "runtime_promotion_ref"),
        (ExecutionOrderMaterializationRecord, "materialization_ref"),
        (ExecutionVenueConnectivityCheckRecord, "venue_connectivity_check_ref"),
        (ExecutionVenueSafetyAttestationRecord, "venue_safety_attestation_ref"),
        (ExecutionVenueCapabilityRecord, "venue_capability_ref"),
        (ExecutionSubmitRequestRecord, "submit_request_ref"),
        (ExecutionOrderSubmissionRecord, "submission_ref"),
        (ExecutionVenueEventRecord, "venue_event_ref"),
        (ExecutionReconciliationRecord, "reconciliation_ref"),
        (ExecutionReconciliationActionRecord, "action_ref"),
        (UserRiskChoiceRecord, "choice_ref"),
    )
    for record_type, field in field_by_type:
        if isinstance(record, record_type):
            value = _text(getattr(record, field, ""))
            if value:
                return value
            break
    raise ValueError("execution closure component has no stable record ref")


def _reject_placeholder_material(value: Any, *, field: str) -> None:
    stable = _stable(value)

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str) and is_placeholder_ref(item):
            raise ValueError(f"{path} contains banned placeholder material")

    visit(stable, field)


@dataclass(frozen=True)
class ExecutionClosureViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class ExecutionClosureDecision:
    accepted: bool
    violations: tuple[ExecutionClosureViolation, ...]


class ExecutionClosureError(ValueError):
    """A current owner-scoped execution chain could not be proved."""


class ExecutionClosureCommitUncertain(ExecutionClosureError):
    """The receipt file was replaced but directory durability was not confirmed."""


@dataclass(frozen=True)
class ExecutionClosureComponentState:
    component_kind: str
    component_ref: str
    created_at_utc: str
    state_hash: str

    def __post_init__(self) -> None:
        for name in ("component_kind", "component_ref", "created_at_utc", "state_hash"):
            object.__setattr__(self, name, _text(getattr(self, name)))


@dataclass(frozen=True)
class ExecutionClosureSnapshot:
    owner_user_id: str
    order_flow_ref: str
    freshness_policy_ref: str
    evidence_ttl_seconds: float
    evaluated_at_utc: str
    runtime: str
    asset_class: str
    instrument_ref: str
    venue_ref: str
    submission_status: str
    reconciliation_status: str
    components: tuple[ExecutionClosureComponentState, ...]

    def __post_init__(self) -> None:
        for name in (
            "owner_user_id",
            "order_flow_ref",
            "freshness_policy_ref",
            "evaluated_at_utc",
            "runtime",
            "asset_class",
            "instrument_ref",
            "venue_ref",
            "submission_status",
            "reconciliation_status",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "evidence_ttl_seconds", float(self.evidence_ttl_seconds))
        object.__setattr__(
            self,
            "components",
            tuple(sorted(self.components, key=lambda item: (item.component_kind, item.component_ref))),
        )


@dataclass(frozen=True)
class ExecutionClosureReceipt:
    receipt_ref: str
    owner_user_id: str
    order_intent_ref: str
    runtime_promotion_ref: str
    order_materialization_ref: str
    venue_connectivity_check_ref: str
    venue_safety_attestation_ref: str
    venue_capability_ref: str
    submit_request_ref: str
    submission_ref: str
    venue_event_refs: tuple[str, ...]
    reconciliation_ref: str
    reconciliation_action_refs: tuple[str, ...]
    user_risk_choice_ref: str | None
    snapshot: ExecutionClosureSnapshot
    receipt_version: str = EXECUTION_CLOSURE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for name in (
            "receipt_ref",
            "owner_user_id",
            "order_intent_ref",
            "runtime_promotion_ref",
            "order_materialization_ref",
            "venue_connectivity_check_ref",
            "venue_safety_attestation_ref",
            "venue_capability_ref",
            "submit_request_ref",
            "submission_ref",
            "reconciliation_ref",
            "receipt_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "venue_event_refs", tuple(sorted(_refs(self.venue_event_refs))))
        object.__setattr__(
            self,
            "reconciliation_action_refs",
            tuple(sorted(_refs(self.reconciliation_action_refs))),
        )
        object.__setattr__(
            self,
            "user_risk_choice_ref",
            _text(self.user_risk_choice_ref) or None,
        )

    @property
    def canonical_receipt_ref(self) -> str:
        return execution_closure_receipt_identity(
            owner_user_id=self.owner_user_id,
            order_intent_ref=self.order_intent_ref,
            runtime_promotion_ref=self.runtime_promotion_ref,
            order_materialization_ref=self.order_materialization_ref,
            venue_connectivity_check_ref=self.venue_connectivity_check_ref,
            venue_safety_attestation_ref=self.venue_safety_attestation_ref,
            venue_capability_ref=self.venue_capability_ref,
            submit_request_ref=self.submit_request_ref,
            submission_ref=self.submission_ref,
            venue_event_refs=self.venue_event_refs,
            reconciliation_ref=self.reconciliation_ref,
            reconciliation_action_refs=self.reconciliation_action_refs,
            user_risk_choice_ref=self.user_risk_choice_ref,
            snapshot=self.snapshot,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class ExecutionClosureSemanticMaterial:
    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]


@dataclass(frozen=True)
class _ExecutionBacking:
    order_intents: PersistentExecutionOrderIntentRegistry
    runtime_promotions: PersistentRuntimePromotionRegistry
    materializations: PersistentExecutionOrderMaterializationRegistry
    connectivity_checks: PersistentExecutionVenueConnectivityCheckRegistry
    safety_attestations: PersistentExecutionVenueSafetyAttestationRegistry
    capabilities: PersistentExecutionVenueCapabilityRegistry
    submit_requests: PersistentExecutionSubmitRequestRegistry
    submissions: PersistentExecutionOrderSubmissionRegistry
    venue_events: PersistentExecutionVenueEventRegistry
    reconciliations: PersistentExecutionReconciliationRegistry
    reconciliation_actions: PersistentExecutionReconciliationActionRegistry
    user_risk_choices: PersistentUserRiskChoiceRegistry


def execution_closure_receipt_identity(
    *,
    owner_user_id: str,
    order_intent_ref: str,
    runtime_promotion_ref: str,
    order_materialization_ref: str,
    venue_connectivity_check_ref: str,
    venue_safety_attestation_ref: str,
    venue_capability_ref: str,
    submit_request_ref: str,
    submission_ref: str,
    venue_event_refs: tuple[str, ...],
    reconciliation_ref: str,
    reconciliation_action_refs: tuple[str, ...],
    user_risk_choice_ref: str | None,
    snapshot: ExecutionClosureSnapshot,
    receipt_version: str = EXECUTION_CLOSURE_RECEIPT_VERSION,
) -> str:
    return "execution_closure_receipt:" + content_hash(
        {
            "owner_user_id": _text(owner_user_id),
            "order_intent_ref": _text(order_intent_ref),
            "runtime_promotion_ref": _text(runtime_promotion_ref),
            "order_materialization_ref": _text(order_materialization_ref),
            "venue_connectivity_check_ref": _text(venue_connectivity_check_ref),
            "venue_safety_attestation_ref": _text(venue_safety_attestation_ref),
            "venue_capability_ref": _text(venue_capability_ref),
            "submit_request_ref": _text(submit_request_ref),
            "submission_ref": _text(submission_ref),
            "venue_event_refs": tuple(sorted(_refs(venue_event_refs))),
            "reconciliation_ref": _text(reconciliation_ref),
            "reconciliation_action_refs": tuple(sorted(_refs(reconciliation_action_refs))),
            "user_risk_choice_ref": _text(user_risk_choice_ref) or None,
            "snapshot": asdict(snapshot),
            "receipt_version": _text(receipt_version),
        }
    )


def _component_from_dict(value: Any) -> ExecutionClosureComponentState:
    expected = {"component_kind", "component_ref", "created_at_utc", "state_hash"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("execution closure component has an inexact field set")
    return ExecutionClosureComponentState(**value)


def execution_closure_snapshot_from_dict(value: Any) -> ExecutionClosureSnapshot:
    expected = {
        "owner_user_id",
        "order_flow_ref",
        "freshness_policy_ref",
        "evidence_ttl_seconds",
        "evaluated_at_utc",
        "runtime",
        "asset_class",
        "instrument_ref",
        "venue_ref",
        "submission_status",
        "reconciliation_status",
        "components",
    }
    if not isinstance(value, dict) or set(value) != expected or not isinstance(value["components"], list):
        raise ValueError("execution closure snapshot has an inexact field set")
    return ExecutionClosureSnapshot(
        owner_user_id=value["owner_user_id"],
        order_flow_ref=value["order_flow_ref"],
        freshness_policy_ref=value["freshness_policy_ref"],
        evidence_ttl_seconds=value["evidence_ttl_seconds"],
        evaluated_at_utc=value["evaluated_at_utc"],
        runtime=value["runtime"],
        asset_class=value["asset_class"],
        instrument_ref=value["instrument_ref"],
        venue_ref=value["venue_ref"],
        submission_status=value["submission_status"],
        reconciliation_status=value["reconciliation_status"],
        components=tuple(_component_from_dict(item) for item in value["components"]),
    )


def execution_closure_receipt_from_dict(value: Any) -> ExecutionClosureReceipt:
    expected = {
        "receipt_ref",
        "owner_user_id",
        "order_intent_ref",
        "runtime_promotion_ref",
        "order_materialization_ref",
        "venue_connectivity_check_ref",
        "venue_safety_attestation_ref",
        "venue_capability_ref",
        "submit_request_ref",
        "submission_ref",
        "venue_event_refs",
        "reconciliation_ref",
        "reconciliation_action_refs",
        "user_risk_choice_ref",
        "snapshot",
        "receipt_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("execution closure receipt has an inexact field set")
    return ExecutionClosureReceipt(
        receipt_ref=value["receipt_ref"],
        owner_user_id=value["owner_user_id"],
        order_intent_ref=value["order_intent_ref"],
        runtime_promotion_ref=value["runtime_promotion_ref"],
        order_materialization_ref=value["order_materialization_ref"],
        venue_connectivity_check_ref=value["venue_connectivity_check_ref"],
        venue_safety_attestation_ref=value["venue_safety_attestation_ref"],
        venue_capability_ref=value["venue_capability_ref"],
        submit_request_ref=value["submit_request_ref"],
        submission_ref=value["submission_ref"],
        venue_event_refs=tuple(value["venue_event_refs"]),
        reconciliation_ref=value["reconciliation_ref"],
        reconciliation_action_refs=tuple(value["reconciliation_action_refs"]),
        user_risk_choice_ref=value["user_risk_choice_ref"],
        snapshot=execution_closure_snapshot_from_dict(value["snapshot"]),
        receipt_version=value["receipt_version"],
    )


def validate_execution_closure_receipt_shape(
    receipt: ExecutionClosureReceipt,
) -> ExecutionClosureDecision:
    violations: list[ExecutionClosureViolation] = []
    if receipt.receipt_version != EXECUTION_CLOSURE_RECEIPT_VERSION:
        violations.append(
            ExecutionClosureViolation(
                "execution_closure_receipt_version_unsupported",
                "execution closure receipt version is unsupported",
                field="receipt_version",
                ref=receipt.receipt_ref,
            )
        )
    for field in (
        "receipt_ref",
        "owner_user_id",
        "order_intent_ref",
        "runtime_promotion_ref",
        "order_materialization_ref",
        "venue_connectivity_check_ref",
        "venue_safety_attestation_ref",
        "venue_capability_ref",
        "submit_request_ref",
        "submission_ref",
        "venue_event_refs",
        "reconciliation_ref",
    ):
        if not getattr(receipt, field):
            violations.append(
                ExecutionClosureViolation(
                    "execution_closure_receipt_required_field_missing",
                    "execution closure receipt requires every formal execution-chain ref",
                    field=field,
                    ref=receipt.receipt_ref,
                )
            )
    if receipt.snapshot.owner_user_id != receipt.owner_user_id:
        violations.append(
            ExecutionClosureViolation(
                "execution_closure_receipt_owner_mismatch",
                "receipt and snapshot owner must match exactly",
                field="owner_user_id",
                ref=receipt.receipt_ref,
            )
        )
    try:
        _real_ref(receipt.snapshot.freshness_policy_ref, field="snapshot.freshness_policy_ref")
        _aware_time(receipt.snapshot.evaluated_at_utc, field="snapshot.evaluated_at_utc")
        if (
            not math.isfinite(receipt.snapshot.evidence_ttl_seconds)
            or receipt.snapshot.evidence_ttl_seconds <= 0
        ):
            raise ValueError("snapshot.evidence_ttl_seconds must be finite and positive")
    except ValueError as exc:
        violations.append(
            ExecutionClosureViolation(
                "execution_closure_freshness_policy_invalid",
                str(exc),
                field="snapshot",
                ref=receipt.receipt_ref,
            )
        )
    all_refs = (
        receipt.order_intent_ref,
        receipt.runtime_promotion_ref,
        receipt.order_materialization_ref,
        receipt.venue_connectivity_check_ref,
        receipt.venue_safety_attestation_ref,
        receipt.venue_capability_ref,
        receipt.submit_request_ref,
        receipt.submission_ref,
        *receipt.venue_event_refs,
        receipt.reconciliation_ref,
        *receipt.reconciliation_action_refs,
        *([receipt.user_risk_choice_ref] if receipt.user_risk_choice_ref else []),
    )
    if len(all_refs) != len(set(all_refs)):
        violations.append(
            ExecutionClosureViolation(
                "execution_closure_receipt_duplicate_ref",
                "execution closure dependencies must be exact unique refs",
                field="dependency_refs",
                ref=receipt.receipt_ref,
            )
        )
    for ref in all_refs:
        if not _text(ref) or is_placeholder_ref(_text(ref)):
            violations.append(
                ExecutionClosureViolation(
                    "execution_closure_receipt_placeholder_ref",
                    "execution closure cannot bind synthetic, fixture, test-only, placeholder, or goal-closure refs",
                    field="dependency_refs",
                    ref=_text(ref),
                )
            )
    component_keys = {(item.component_kind, item.component_ref) for item in receipt.snapshot.components}
    if not receipt.snapshot.components or len(component_keys) != len(receipt.snapshot.components):
        violations.append(
            ExecutionClosureViolation(
                "execution_closure_component_set_inexact",
                "execution closure components must be non-empty and uniquely keyed",
                field="components",
                ref=receipt.receipt_ref,
            )
        )
    if receipt.receipt_ref and receipt.receipt_ref != receipt.canonical_receipt_ref:
        violations.append(
            ExecutionClosureViolation(
                "execution_closure_receipt_identity_mismatch",
                "receipt_ref must content-bind owner, exact refs, and current component states",
                field="receipt_ref",
                ref=receipt.receipt_ref,
            )
        )
    return ExecutionClosureDecision(not violations, tuple(violations))


class PersistentExecutionClosureRegistry:
    """Schema-v2 hash/revision-chained closure ledger over exact backing stores."""

    _REGISTRY_FIELDS: tuple[tuple[str, type[Any]], ...] = (
        ("order_intents", PersistentExecutionOrderIntentRegistry),
        ("runtime_promotions", PersistentRuntimePromotionRegistry),
        ("materializations", PersistentExecutionOrderMaterializationRegistry),
        ("connectivity_checks", PersistentExecutionVenueConnectivityCheckRegistry),
        ("safety_attestations", PersistentExecutionVenueSafetyAttestationRegistry),
        ("capabilities", PersistentExecutionVenueCapabilityRegistry),
        ("submit_requests", PersistentExecutionSubmitRequestRegistry),
        ("submissions", PersistentExecutionOrderSubmissionRegistry),
        ("venue_events", PersistentExecutionVenueEventRegistry),
        ("reconciliations", PersistentExecutionReconciliationRegistry),
        ("reconciliation_actions", PersistentExecutionReconciliationActionRegistry),
        ("user_risk_choices", PersistentUserRiskChoiceRegistry),
    )

    def __init__(
        self,
        path: str | Path,
        *,
        order_intents: PersistentExecutionOrderIntentRegistry,
        runtime_promotions: PersistentRuntimePromotionRegistry,
        materializations: PersistentExecutionOrderMaterializationRegistry,
        connectivity_checks: PersistentExecutionVenueConnectivityCheckRegistry,
        safety_attestations: PersistentExecutionVenueSafetyAttestationRegistry,
        capabilities: PersistentExecutionVenueCapabilityRegistry,
        submit_requests: PersistentExecutionSubmitRequestRegistry,
        submissions: PersistentExecutionOrderSubmissionRegistry,
        venue_events: PersistentExecutionVenueEventRegistry,
        reconciliations: PersistentExecutionReconciliationRegistry,
        reconciliation_actions: PersistentExecutionReconciliationActionRegistry,
        user_risk_choices: PersistentUserRiskChoiceRegistry,
        evidence_ttl_seconds: float = 900.0,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        ttl = float(evidence_ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("evidence_ttl_seconds must be finite and positive")
        self._evidence_ttl_seconds = ttl
        self._freshness_policy_ref = "execution_closure_freshness_policy:" + content_hash(
            {
                "policy_version": "v1",
                "evidence_ttl_seconds": self._evidence_ttl_seconds,
                "fresh_component_kinds": tuple(sorted(_FRESH_COMPONENT_KINDS)),
            }
        )
        supplied = locals()
        paths: dict[str, Path] = {}
        for name, expected_type in self._REGISTRY_FIELDS:
            registry = supplied[name]
            if not isinstance(registry, expected_type):
                raise TypeError(f"{name} must be {expected_type.__name__}")
            registry_path = getattr(registry, "_path", None)
            if registry_path is None:
                raise ValueError(f"{name} must use a durable path")
            paths[name] = Path(registry_path)
        resolved_paths = {name: path.resolve() for name, path in paths.items()}
        if len(set(resolved_paths.values())) != len(resolved_paths):
            raise ValueError("execution closure backing ledgers must use distinct durable paths")
        if self._path.resolve() in set(resolved_paths.values()):
            raise ValueError("execution closure ledger path must be distinct from every backing ledger")
        self._registry_paths = paths
        self._registries = {
            name: supplied[name]
            for name, _expected_type in self._REGISTRY_FIELDS
        }
        self._receipts: dict[tuple[str, str], ExecutionClosureReceipt] = {}
        self._heads: dict[tuple[str, str], ExecutionClosureReceipt] = {}
        self._last_revision = 0
        self._last_record_hash: str | None = None
        self._legacy_quarantined_count = 0
        self._corrupt_quarantined_count = 0
        self._poisoned = False
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        self._refresh()
        return self._legacy_quarantined_count

    @property
    def corrupt_quarantined_count(self) -> int:
        self._refresh()
        return self._corrupt_quarantined_count

    @property
    def poisoned(self) -> bool:
        self._refresh()
        return self._poisoned

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @contextmanager
    def _shared_backing_snapshot(self) -> Iterator[dict[Path, str | None]]:
        with ExitStack() as stack:
            optional_paths = {
                self._registry_paths["reconciliation_actions"],
                self._registry_paths["user_risk_choices"],
            }
            digests: dict[Path, str | None] = {}
            for name, path in sorted(
                self._registry_paths.items(),
                key=lambda item: str(item[1]),
            ):
                snapshot_token = getattr(
                    self._registries[name],
                    "snapshot_token",
                    None,
                )
                if callable(snapshot_token):
                    digests[path] = str(snapshot_token())
                    continue
                if not path.exists():
                    if path in optional_paths:
                        digests[path] = None
                        continue
                    raise ExecutionClosureError(f"execution backing ledger is missing: {path.name}")
                fh = stack.enter_context(path.open("rb"))
                fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
                stack.callback(fcntl.flock, fh.fileno(), fcntl.LOCK_UN)
                digests[path] = "sha256:" + hashlib.sha256(fh.read()).hexdigest()
            yield digests

    @contextmanager
    def _locked_backing(self) -> Iterator[_ExecutionBacking]:
        """Clone one stable backing snapshot, then hold its shared file locks.

        Execution-boundary writers take a process lock before their file lock.
        Cloning while already holding file locks would invert that order and
        deadlock with an in-process append.  The before/after digest protocol
        avoids that inversion: any append during cloning changes a digest and
        forces a retry; once equal, the final shared locks remain held through
        receipt resolution and append.
        """

        for _attempt in range(3):
            with self._shared_backing_snapshot() as before:
                baseline = dict(before)
            clones: dict[str, Any] = {}
            for name, expected_type in self._REGISTRY_FIELDS:
                snapshot_clone = getattr(
                    self._registries[name],
                    "snapshot_clone",
                    None,
                )
                clones[name] = (
                    snapshot_clone()
                    if callable(snapshot_clone)
                    else expected_type(self._registry_paths[name])
                )
            with self._shared_backing_snapshot() as after:
                if baseline != after:
                    continue
                yield _ExecutionBacking(**clones)
            with self._shared_backing_snapshot() as post:
                if baseline != post:
                    raise ExecutionClosureCommitUncertain(
                        "execution backing ledgers changed while closure was being committed"
                    )
                return
        raise ExecutionClosureError("execution backing ledgers changed during current snapshot")

    def _reset(self) -> None:
        self._receipts.clear()
        self._heads.clear()
        self._last_revision = 0
        self._last_record_hash = None
        self._legacy_quarantined_count = 0
        self._corrupt_quarantined_count = 0
        self._poisoned = False

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _refresh(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        chain_broken = False
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self._corrupt_quarantined_count += 1
                self._poisoned = True
                chain_broken = True
                continue
            if not isinstance(row, dict) or row.get("schema_version") != EXECUTION_CLOSURE_SCHEMA_VERSION:
                self._legacy_quarantined_count += 1
                continue
            if chain_broken:
                self._corrupt_quarantined_count += 1
                self._poisoned = True
                continue
            try:
                self._apply_row(row)
            except Exception:
                self._corrupt_quarantined_count += 1
                self._poisoned = True
                chain_broken = True

    def _apply_row(self, row: dict[str, Any]) -> ExecutionClosureReceipt:
        expected_fields = {
            "schema_version",
            "event_type",
            "owner_user_id",
            "revision",
            "previous_record_hash",
            "record_hash",
            "execution_closure",
        }
        if set(row) != expected_fields:
            raise ValueError("execution closure row has an inexact field set")
        if row["event_type"] != "execution_closure_receipt_recorded":
            raise ValueError("unsupported execution closure event type")
        revision = row["revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision != self._last_revision + 1:
            raise ValueError("execution closure revision chain is discontinuous")
        if row["previous_record_hash"] != self._last_record_hash:
            raise ValueError("execution closure previous_record_hash mismatch")
        unsigned = dict(row)
        supplied_hash = _text(unsigned.pop("record_hash"))
        expected_hash = "sha256:" + _sha256(unsigned)
        if supplied_hash != expected_hash:
            raise ValueError("execution closure record_hash mismatch")
        owner = _owner(row["owner_user_id"])
        receipt = execution_closure_receipt_from_dict(row["execution_closure"])
        if receipt.owner_user_id != owner:
            raise ValueError("execution closure owner envelope mismatch")
        decision = validate_execution_closure_receipt_shape(receipt)
        if not decision.accepted:
            raise ValueError(
                "invalid execution closure receipt: "
                + ",".join(item.code for item in decision.violations)
            )
        key = (owner, receipt.receipt_ref)
        existing = self._receipts.get(key)
        if existing is not None and existing != receipt:
            raise ValueError("execution closure receipt identity collision")
        self._receipts[key] = receipt
        self._heads[(owner, receipt.order_intent_ref)] = receipt
        self._last_revision = revision
        self._last_record_hash = supplied_hash
        return receipt

    def _restore_original(self, *, original_exists: bool, original: bytes) -> None:
        if original_exists:
            fd, raw_restore = tempfile.mkstemp(
                prefix=f".{self._path.name}.restore.",
                dir=self._path.parent,
            )
            restore_path = Path(raw_restore)
            try:
                os.fchmod(fd, 0o600)
                handle = os.fdopen(fd, "wb", closefd=True)
                fd = -1
                with handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(restore_path, self._path)
            finally:
                if fd >= 0:
                    os.close(fd)
                restore_path.unlink(missing_ok=True)
        else:
            self._path.unlink(missing_ok=True)
        dir_fd = os.open(
            self._path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _atomic_append(self, receipt: ExecutionClosureReceipt) -> tuple[bool, bytes]:
        unsigned = {
            "schema_version": EXECUTION_CLOSURE_SCHEMA_VERSION,
            "event_type": "execution_closure_receipt_recorded",
            "owner_user_id": receipt.owner_user_id,
            "revision": self._last_revision + 1,
            "previous_record_hash": self._last_record_hash,
            "execution_closure": asdict(receipt),
        }
        row = {**unsigned, "record_hash": "sha256:" + _sha256(unsigned)}
        original_exists = self._path.exists()
        original = self._path.read_bytes() if original_exists else b""
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        encoded = original + separator + _canonical_json(row).encode("utf-8") + b"\n"
        fd, raw_temp = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        temp_path = Path(raw_temp)
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            handle = os.fdopen(fd, "wb", closefd=True)
            fd = -1
            with handle as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, self._path)
            replaced = True
            dir_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            except OSError as exc:
                raise ExecutionClosureCommitUncertain(
                    "execution closure directory fsync failed; append was rolled back"
                ) from exc
            finally:
                os.close(dir_fd)
        except Exception:
            if replaced:
                try:
                    self._restore_original(
                        original_exists=original_exists,
                        original=original,
                    )
                except Exception as recovery_exc:
                    raise ExecutionClosureCommitUncertain(
                        "execution closure append failed and durable rollback is uncertain"
                    ) from recovery_exc
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            temp_path.unlink(missing_ok=True)
        return original_exists, original

    @staticmethod
    def _latest(records: list[Any], selected: Any, *, label: str) -> None:
        if not records:
            raise ExecutionClosureError(f"no current {label} records exist for this flow")
        latest = records[-1]
        if _record_ref(latest) != _record_ref(selected):
            raise ExecutionClosureError(f"selected {label} is stale for this execution flow")

    @staticmethod
    def _journal_records(registry: Any, *, label: str) -> list[Any]:
        """Return durable append order; caller timestamps never define currentness."""

        records = getattr(registry, "_records", None)
        if not isinstance(records, dict):
            raise ExecutionClosureError(
                f"{label} registry does not expose its durable append-order index"
            )
        return list(records.values())

    @staticmethod
    def _owned(record: Any, owner: str, *, label: str) -> None:
        if _text(getattr(record, "recorded_by", "")) != owner:
            raise ExecutionClosureError(f"{label} owner does not match receipt owner")
        _reject_placeholder_material(record, field=label)
        _real_ref(_record_ref(record), field=f"{label}.ref")

    def _fresh(self, record: Any, *, label: str, as_of: datetime) -> None:
        created = _aware_time(record.created_at_utc, field=f"{label}.created_at_utc")
        age = (as_of - created).total_seconds()
        if age < 0:
            raise ExecutionClosureError(f"{label} timestamp is in the future")
        if label in _FRESH_COMPONENT_KINDS and age > self._evidence_ttl_seconds:
            raise ExecutionClosureError(f"{label} evidence is stale")

    @staticmethod
    def _decision(decision: Any, *, label: str) -> None:
        if not bool(getattr(decision, "accepted", False)):
            codes = ",".join(item.code for item in getattr(decision, "violations", ()))
            raise ExecutionClosureError(f"{label} validation rejected: {codes}")

    def _resolve_snapshot(
        self,
        *,
        backing: _ExecutionBacking,
        owner: str,
        order_intent_ref: str,
        runtime_promotion_ref: str,
        order_materialization_ref: str,
        venue_connectivity_check_ref: str,
        venue_safety_attestation_ref: str,
        venue_capability_ref: str,
        submit_request_ref: str,
        submission_ref: str,
        venue_event_refs: tuple[str, ...],
        reconciliation_ref: str,
        reconciliation_action_refs: tuple[str, ...],
        user_risk_choice_ref: str | None,
        as_of: datetime,
        snapshot_evaluated_at_utc: str | None = None,
    ) -> ExecutionClosureSnapshot:
        refs = {
            "order_intent_ref": _real_ref(order_intent_ref, field="order_intent_ref"),
            "runtime_promotion_ref": _real_ref(runtime_promotion_ref, field="runtime_promotion_ref"),
            "order_materialization_ref": _real_ref(order_materialization_ref, field="order_materialization_ref"),
            "venue_connectivity_check_ref": _real_ref(
                venue_connectivity_check_ref, field="venue_connectivity_check_ref"
            ),
            "venue_safety_attestation_ref": _real_ref(
                venue_safety_attestation_ref, field="venue_safety_attestation_ref"
            ),
            "venue_capability_ref": _real_ref(venue_capability_ref, field="venue_capability_ref"),
            "submit_request_ref": _real_ref(submit_request_ref, field="submit_request_ref"),
            "submission_ref": _real_ref(submission_ref, field="submission_ref"),
            "reconciliation_ref": _real_ref(reconciliation_ref, field="reconciliation_ref"),
        }
        event_refs = _exact_unique(venue_event_refs, field="venue_event_refs")
        action_refs = _exact_unique(
            reconciliation_action_refs,
            field="reconciliation_action_refs",
            allow_empty=True,
        )
        intent = backing.order_intents.intent(refs["order_intent_ref"])
        promotion = backing.runtime_promotions.promotion(refs["runtime_promotion_ref"])
        materialization = backing.materializations.materialization(refs["order_materialization_ref"])
        connectivity = backing.connectivity_checks.check(refs["venue_connectivity_check_ref"])
        safety = backing.safety_attestations.attestation(refs["venue_safety_attestation_ref"])
        capability = backing.capabilities.capability(refs["venue_capability_ref"])
        submit_request = backing.submit_requests.request(refs["submit_request_ref"])
        submission = backing.submissions.submission(refs["submission_ref"])
        events = tuple(backing.venue_events.event(ref) for ref in event_refs)
        reconciliation = backing.reconciliations.reconciliation(refs["reconciliation_ref"])
        actions = tuple(backing.reconciliation_actions.action(ref) for ref in action_refs)

        components: list[tuple[str, Any]] = [
            ("order_intent", intent),
            ("runtime_promotion", promotion),
            ("order_materialization", materialization),
            ("venue_connectivity_check", connectivity),
            ("venue_safety_attestation", safety),
            ("venue_capability", capability),
            ("submit_request", submit_request),
            ("submission", submission),
            *(("venue_event", event) for event in events),
            ("reconciliation", reconciliation),
            *(("reconciliation_action", action) for action in actions),
        ]
        for label, record in components:
            self._owned(record, owner, label=label)
            self._fresh(record, label=label, as_of=as_of)

        self._decision(validate_execution_order_intent(intent), label="order_intent")
        self._decision(validate_runtime_promotion_record(promotion), label="runtime_promotion")
        self._decision(
            validate_execution_order_materialization(
                materialization,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                order_intent=intent,
                runtime_promotion=promotion,
            ),
            label="order_materialization",
        )
        self._decision(
            validate_execution_venue_connectivity_check(
                connectivity,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                order_intent=intent,
                runtime_promotion=promotion,
            ),
            label="venue_connectivity_check",
        )
        self._decision(
            validate_execution_venue_safety_attestation(
                safety,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_venue_connectivity_check_refs={connectivity.venue_connectivity_check_ref},
                order_intent=intent,
                runtime_promotion=promotion,
                venue_connectivity_check=connectivity,
            ),
            label="venue_safety_attestation",
        )
        self._decision(
            validate_execution_venue_capability(
                capability,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_venue_safety_attestation_refs={safety.venue_safety_attestation_ref},
                order_intent=intent,
                runtime_promotion=promotion,
                venue_safety_attestation=safety,
            ),
            label="venue_capability",
        )
        self._decision(
            validate_execution_submit_request(
                submit_request,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_order_materialization_refs={materialization.materialization_ref},
                known_venue_capability_refs={capability.venue_capability_ref},
                order_intent=intent,
                runtime_promotion=promotion,
                order_materialization=materialization,
                venue_capability=capability,
            ),
            label="submit_request",
        )
        self._decision(
            validate_execution_order_submission(
                submission,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_order_materialization_refs={materialization.materialization_ref},
                known_venue_capability_refs={capability.venue_capability_ref},
                known_submit_request_refs={submit_request.submit_request_ref},
                order_intent=intent,
                runtime_promotion=promotion,
                order_materialization=materialization,
                venue_capability=capability,
                submit_request=submit_request,
            ),
            label="submission",
        )
        for event in events:
            self._decision(
                validate_execution_venue_event(
                    event,
                    known_order_intent_refs={intent.order_intent_ref},
                    known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                    known_submission_refs={submission.submission_ref},
                    submission=submission,
                ),
                label="venue_event",
            )
        self._decision(
            validate_execution_reconciliation(
                reconciliation,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_venue_event_refs=set(event_refs),
                known_submission_refs={submission.submission_ref},
                submission=submission,
                venue_events=events,
            ),
            label="reconciliation",
        )
        for action in actions:
            self._decision(
                validate_execution_reconciliation_action(
                    action,
                    known_reconciliation_refs={reconciliation.reconciliation_ref},
                    action_required_by_ref={
                        reconciliation.reconciliation_ref: reconciliation.action_required
                    },
                ),
                label="reconciliation_action",
            )

        runtime = _text(getattr(promotion.target_runtime, "value", promotion.target_runtime)).lower()
        if runtime not in {"paper", "testnet", "live"} or _text(
            getattr(intent.runtime, "value", intent.runtime)
        ).lower() != runtime:
            raise ExecutionClosureError("order intent and runtime promotion must share paper/testnet/live runtime")
        if materialization.materialization_status != "materialized" or not materialization.materialize_enabled:
            raise ExecutionClosureError("closure requires a completed materialized order envelope")
        if connectivity.connectivity_status != "accepted":
            raise ExecutionClosureError("closure requires accepted venue connectivity evidence")
        if safety.attestation_status != "accepted":
            raise ExecutionClosureError("closure requires accepted venue safety evidence")
        if capability.capability_status != "ready" or not capability.can_submit_orders:
            raise ExecutionClosureError("closure requires a ready guarded venue capability")
        if submit_request.submit_request_status != "ready":
            raise ExecutionClosureError("closure requires a ready submit request envelope")
        if not submission.submit_enabled or submission.submission_status not in _CURRENT_SUBMISSION_STATUSES:
            raise ExecutionClosureError("closure requires a submitted order with accepted/rejected acknowledgement")
        if reconciliation.status not in _TERMINAL_RECONCILIATION_STATUSES or reconciliation.action_required:
            raise ExecutionClosureError("closure requires terminal reconciliation with no open action")
        if set(event_refs) != set(reconciliation.event_refs):
            raise ExecutionClosureError("receipt venue_event_refs must exactly equal reconciliation.event_refs")
        submission_events = tuple(
            event
            for event in backing.venue_events.events()
            if event.submission_ref == submission.submission_ref
        )
        if any(_text(event.recorded_by) != owner for event in submission_events):
            raise ExecutionClosureError("submission has a cross-owner venue event")
        observed_event_refs = {event.venue_event_ref for event in submission_events}
        if set(event_refs) != observed_event_refs:
            raise ExecutionClosureError(
                "submission has venue events that are not included in the selected reconciliation"
            )
        if actions:
            raise ExecutionClosureError("terminal reconciliation cannot carry reconciliation actions")
        observed_actions = tuple(
            action
            for action in backing.reconciliation_actions.actions()
            if action.reconciliation_ref == reconciliation.reconciliation_ref
        )
        if any(_text(action.recorded_by) != owner for action in observed_actions):
            raise ExecutionClosureError("reconciliation has a cross-owner action")
        if observed_actions:
            raise ExecutionClosureError("terminal reconciliation has unexpected recorded actions")

        common_fields = (
            "permission_gate_ref",
            "order_guard_ref",
            "idempotency_key",
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        )
        for field in common_fields:
            values = {
                _text(getattr(record, field, ""))
                for record in (
                    intent,
                    promotion,
                    materialization,
                    connectivity,
                    safety,
                    capability,
                    submit_request,
                    submission,
                )
            }
            if len(values) != 1 or "" in values:
                raise ExecutionClosureError(f"execution invariant {field} must be non-empty and exact across chain")

        if runtime == "live":
            if not user_risk_choice_ref:
                raise ExecutionClosureError("live closure requires an owner-scoped user risk choice")
            risk_choice = backing.user_risk_choices.choice_for_owner(
                _real_ref(user_risk_choice_ref, field="user_risk_choice_ref"), owner
            )
            _reject_placeholder_material(risk_choice, field="user_risk_choice")
            self._decision(validate_user_risk_choice(risk_choice), label="user_risk_choice")
            if risk_choice.runtime_request_ref != promotion.request_ref:
                raise ExecutionClosureError("user risk choice runtime request does not match promotion")
            if risk_choice.asset_class != promotion.asset_class:
                raise ExecutionClosureError("user risk choice asset class does not match promotion")
            if risk_choice.responsibility_boundary_ref != promotion.responsibility_boundary_ref:
                raise ExecutionClosureError("user risk choice responsibility boundary does not match promotion")
            if promotion.subject_ref and risk_choice.subject_ref != promotion.subject_ref:
                raise ExecutionClosureError("user risk choice subject does not match promotion")
            matching_risk_choices = [
                item
                for item in self._journal_records(
                    backing.user_risk_choices,
                    label="user_risk_choice",
                )
                if _text(getattr(item, "owner_user_id", "")) == owner
                if item.runtime_request_ref == promotion.request_ref
                and item.subject_ref == risk_choice.subject_ref
                and item.asset_class == promotion.asset_class
            ]
            self._latest(matching_risk_choices, risk_choice, label="user_risk_choice")
            components.append(("user_risk_choice", risk_choice))
        elif user_risk_choice_ref:
            raise ExecutionClosureError("paper/testnet closure cannot launder an unrelated live risk choice")

        owner_promotions = [
            item
            for item in self._journal_records(
                backing.runtime_promotions,
                label="runtime_promotion",
            )
            if _text(item.recorded_by) == owner
            and (
                (promotion.subject_ref and item.subject_ref == promotion.subject_ref)
                or (not promotion.subject_ref and item.request_ref == promotion.request_ref)
            )
        ]
        self._latest(owner_promotions, promotion, label="runtime_promotion")
        current_sets = (
            (self._journal_records(backing.materializations, label="order_materialization"), materialization, "order_materialization"),
            (self._journal_records(backing.connectivity_checks, label="venue_connectivity_check"), connectivity, "venue_connectivity_check"),
            (self._journal_records(backing.safety_attestations, label="venue_safety_attestation"), safety, "venue_safety_attestation"),
            (self._journal_records(backing.capabilities, label="venue_capability"), capability, "venue_capability"),
            (self._journal_records(backing.submit_requests, label="submit_request"), submit_request, "submit_request"),
            (self._journal_records(backing.submissions, label="submission"), submission, "submission"),
        )
        for records, selected, label in current_sets:
            linked = [
                item
                for item in records
                if item.order_intent_ref == intent.order_intent_ref
                and item.runtime_promotion_ref == promotion.runtime_promotion_ref
            ]
            if any(_text(item.recorded_by) != owner for item in linked):
                raise ExecutionClosureError(f"{label} has a cross-owner child record")
            matching = [item for item in linked if _text(item.recorded_by) == owner]
            self._latest(matching, selected, label=label)
        linked_reconciliations = [
            item
            for item in self._journal_records(
                backing.reconciliations,
                label="reconciliation",
            )
            if item.submission_ref == submission.submission_ref
        ]
        if any(_text(item.recorded_by) != owner for item in linked_reconciliations):
            raise ExecutionClosureError("reconciliation has a cross-owner child record")
        reconciliations = [
            item for item in linked_reconciliations if _text(item.recorded_by) == owner
        ]
        self._latest(reconciliations, reconciliation, label="reconciliation")

        flow_ref = "execution_order_flow:" + content_hash(
            {
                "owner_user_id": owner,
                "order_intent_ref": intent.order_intent_ref,
                "runtime_promotion_ref": promotion.runtime_promotion_ref,
            }
        )
        states = tuple(
            ExecutionClosureComponentState(
                component_kind=label,
                component_ref=_record_ref(record),
                created_at_utc=_text(record.created_at_utc),
                state_hash=_state_hash(record),
            )
            for label, record in components
        )
        evaluated_at = snapshot_evaluated_at_utc or as_of.isoformat()
        _aware_time(evaluated_at, field="snapshot.evaluated_at_utc")
        return ExecutionClosureSnapshot(
            owner_user_id=owner,
            order_flow_ref=flow_ref,
            freshness_policy_ref=self._freshness_policy_ref,
            evidence_ttl_seconds=self._evidence_ttl_seconds,
            evaluated_at_utc=evaluated_at,
            runtime=runtime,
            asset_class=intent.asset_class,
            instrument_ref=intent.instrument_ref,
            venue_ref=_text(intent.venue_ref),
            submission_status=submission.submission_status,
            reconciliation_status=reconciliation.status,
            components=states,
        )

    def record_current(
        self,
        *,
        owner_user_id: str,
        order_intent_ref: str,
        runtime_promotion_ref: str,
        order_materialization_ref: str,
        venue_connectivity_check_ref: str,
        venue_safety_attestation_ref: str,
        venue_capability_ref: str,
        submit_request_ref: str,
        submission_ref: str,
        venue_event_refs: tuple[str, ...],
        reconciliation_ref: str,
        reconciliation_action_refs: tuple[str, ...] = (),
        user_risk_choice_ref: str | None = None,
    ) -> ExecutionClosureReceipt:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            if self._poisoned:
                raise ExecutionClosureError("execution closure ledger is corrupt and quarantined")
            append_original: tuple[bool, bytes] | None = None
            try:
                with self._locked_backing() as backing:
                    snapshot = self._resolve_snapshot(
                        backing=backing,
                        owner=owner,
                        order_intent_ref=order_intent_ref,
                        runtime_promotion_ref=runtime_promotion_ref,
                        order_materialization_ref=order_materialization_ref,
                        venue_connectivity_check_ref=venue_connectivity_check_ref,
                        venue_safety_attestation_ref=venue_safety_attestation_ref,
                        venue_capability_ref=venue_capability_ref,
                        submit_request_ref=submit_request_ref,
                        submission_ref=submission_ref,
                        venue_event_refs=venue_event_refs,
                        reconciliation_ref=reconciliation_ref,
                        reconciliation_action_refs=reconciliation_action_refs,
                        user_risk_choice_ref=user_risk_choice_ref,
                        as_of=datetime.now(UTC),
                    )
                    blank = ExecutionClosureReceipt(
                        receipt_ref="",
                        owner_user_id=owner,
                        order_intent_ref=order_intent_ref,
                        runtime_promotion_ref=runtime_promotion_ref,
                        order_materialization_ref=order_materialization_ref,
                        venue_connectivity_check_ref=venue_connectivity_check_ref,
                        venue_safety_attestation_ref=venue_safety_attestation_ref,
                        venue_capability_ref=venue_capability_ref,
                        submit_request_ref=submit_request_ref,
                        submission_ref=submission_ref,
                        venue_event_refs=venue_event_refs,
                        reconciliation_ref=reconciliation_ref,
                        reconciliation_action_refs=reconciliation_action_refs,
                        user_risk_choice_ref=user_risk_choice_ref,
                        snapshot=snapshot,
                    )
                    receipt = ExecutionClosureReceipt(
                        **{
                            **asdict(blank),
                            "receipt_ref": blank.canonical_receipt_ref,
                            "snapshot": blank.snapshot,
                        }
                    )
                    decision = validate_execution_closure_receipt_shape(receipt)
                    if not decision.accepted:
                        raise ExecutionClosureError(
                            ",".join(item.code for item in decision.violations)
                        )
                    existing = self._receipts.get((owner, receipt.receipt_ref))
                    if existing is not None:
                        if existing != receipt:
                            raise ExecutionClosureError(
                                "execution closure receipt identity collision"
                            )
                        return existing
                    append_original = self._atomic_append(receipt)
                    self._load_existing_unlocked()
                    if (
                        self._poisoned
                        or self._receipts.get((owner, receipt.receipt_ref)) != receipt
                    ):
                        raise ExecutionClosureCommitUncertain(
                            "execution closure append could not be verified from durable ledger"
                        )
            except Exception:
                if append_original is None:
                    raise
                original_exists, original = append_original
                try:
                    self._restore_original(
                        original_exists=original_exists,
                        original=original,
                    )
                    self._load_existing_unlocked()
                except Exception as recovery_exc:
                    raise ExecutionClosureCommitUncertain(
                        "execution closure failed after append and durable rollback is uncertain"
                    ) from recovery_exc
                raise
            return receipt

    def receipt(self, receipt_ref: str, *, owner_user_id: str) -> ExecutionClosureReceipt:
        owner = _owner(owner_user_id)
        ref = _real_ref(receipt_ref, field="receipt_ref")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            if self._poisoned:
                raise ExecutionClosureError("execution closure ledger is corrupt and quarantined")
            try:
                return self._receipts[(owner, ref)]
            except KeyError as exc:
                raise KeyError("execution closure receipt is not recorded for owner") from exc

    def receipts(self, *, owner_user_id: str) -> tuple[ExecutionClosureReceipt, ...]:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            if self._poisoned:
                return ()
            return tuple(
                receipt
                for (record_owner, _), receipt in self._receipts.items()
                if record_owner == owner
            )

    def validate_current(
        self, receipt_ref: str, *, owner_user_id: str
    ) -> ExecutionClosureDecision:
        try:
            owner = _owner(owner_user_id)
            with self._thread_lock, self._exclusive_lock():
                self._load_existing_unlocked()
                if self._poisoned:
                    raise ExecutionClosureError("execution closure ledger is corrupt and quarantined")
                receipt = self._receipts[(owner, _real_ref(receipt_ref, field="receipt_ref"))]
                if self._heads.get((owner, receipt.order_intent_ref)) != receipt:
                    raise ExecutionClosureError("execution closure receipt is superseded for this intent")
                with self._locked_backing() as backing:
                    current = self._resolve_snapshot(
                        backing=backing,
                        owner=owner,
                        order_intent_ref=receipt.order_intent_ref,
                        runtime_promotion_ref=receipt.runtime_promotion_ref,
                        order_materialization_ref=receipt.order_materialization_ref,
                        venue_connectivity_check_ref=receipt.venue_connectivity_check_ref,
                        venue_safety_attestation_ref=receipt.venue_safety_attestation_ref,
                        venue_capability_ref=receipt.venue_capability_ref,
                        submit_request_ref=receipt.submit_request_ref,
                        submission_ref=receipt.submission_ref,
                        venue_event_refs=receipt.venue_event_refs,
                        reconciliation_ref=receipt.reconciliation_ref,
                        reconciliation_action_refs=receipt.reconciliation_action_refs,
                        user_risk_choice_ref=receipt.user_risk_choice_ref,
                        as_of=datetime.now(UTC),
                        snapshot_evaluated_at_utc=receipt.snapshot.evaluated_at_utc,
                    )
        except (KeyError, PermissionError, ExecutionClosureError, OSError, ValueError) as exc:
            return ExecutionClosureDecision(
                False,
                (
                    ExecutionClosureViolation(
                        "execution_closure_current_resolution_failed",
                        f"current execution closure cannot be resolved: {type(exc).__name__}",
                        field="receipt_ref",
                        ref=_text(receipt_ref),
                    ),
                ),
            )
        violations = list(validate_execution_closure_receipt_shape(receipt).violations)
        if current != receipt.snapshot:
            violations.append(
                ExecutionClosureViolation(
                    "execution_closure_current_state_drifted",
                    "execution promotion, safety, venue, submission, event, or reconciliation state changed",
                    field="snapshot",
                    ref=receipt.receipt_ref,
                )
            )
        return ExecutionClosureDecision(not violations, tuple(violations))


def execution_closure_semantic_material(
    receipt: ExecutionClosureReceipt,
    *,
    entrypoint_ref: str = EXECUTION_CLOSURE_ENTRYPOINT_REF,
) -> ExecutionClosureSemanticMaterial:
    if entrypoint_ref != EXECUTION_CLOSURE_ENTRYPOINT_REF:
        raise ValueError("section 12 semantic material requires the canonical execution closure API")
    producers = tuple(
        sorted(
            f"execution_boundary_producer:{item.component_kind}:{item.component_ref}:{item.state_hash}"
            for item in receipt.snapshot.components
        )
    )
    stores = tuple(
        sorted(
            {
                receipt.receipt_ref,
                *(
                    f"execution_boundary_state:{item.component_kind}:{item.component_ref}:{item.state_hash}"
                    for item in receipt.snapshot.components
                ),
            }
        )
    )
    consumers = (
        f"execution_submission_outcome:{receipt.submission_ref}:{receipt.snapshot.submission_status}",
        f"execution_reconciliation_terminal:{receipt.reconciliation_ref}:{receipt.snapshot.reconciliation_status}",
    )
    gates = (
        receipt.receipt_ref,
        receipt.runtime_promotion_ref,
        receipt.venue_safety_attestation_ref,
        receipt.venue_capability_ref,
        receipt.reconciliation_ref,
    )
    tests = tuple(
        sorted(
            "execution_closure_current_check:"
            f"{receipt.receipt_ref}:{item.component_kind}:{item.component_ref}:{item.state_hash}"
            for item in receipt.snapshot.components
        )
    )
    return ExecutionClosureSemanticMaterial(
        subject_ref=(
            f"goal_section:§12:execution_closure:{receipt.snapshot.runtime}:{receipt.receipt_ref}"
        ),
        producer_refs=producers,
        store_refs=stores,
        consumer_refs=consumers,
        gate_verdict_refs=gates,
        test_refs=tests,
    )


def execution_section_semantic_material(
    execution_receipt: ExecutionClosureReceipt,
    *,
    execution_coverage_refs: tuple[str, ...],
    execution_validation_refs: tuple[str, ...],
    execution_producer_refs: tuple[str, ...],
    execution_store_refs: tuple[str, ...],
    execution_consumer_refs: tuple[str, ...],
) -> ExecutionClosureSemanticMaterial:
    """Compose one flow receipt with its canonical source API lineages.

    Section 12 is an independent producer for the later M9 platform row.  It
    must therefore never consume §14 or a PlatformClosure receipt.  The source
    coverages are the already-recorded execution-boundary API writes that
    produced each component in the receipt; the audit-only closure endpoint is
    not allowed to create a second self-certifying QRO/Compiler chain.
    """

    base = execution_closure_semantic_material(execution_receipt)
    coverages = _exact_unique(
        execution_coverage_refs,
        field="execution_coverage_refs",
    )
    validations = _exact_unique(
        execution_validation_refs,
        field="execution_validation_refs",
    )
    source_producers = _exact_unique(
        execution_producer_refs,
        field="execution_producer_refs",
    )
    source_stores = _exact_unique(
        execution_store_refs,
        field="execution_store_refs",
    )
    source_consumers = _exact_unique(
        execution_consumer_refs,
        field="execution_consumer_refs",
    )
    aggregate_ref = content_hash(
        {
            "execution_receipt_ref": execution_receipt.receipt_ref,
            "execution_coverage_refs": coverages,
            "execution_validation_refs": validations,
            "execution_producer_refs": source_producers,
            "execution_store_refs": source_stores,
            "execution_consumer_refs": source_consumers,
        }
    )
    producers = tuple(sorted({*base.producer_refs, *source_producers}))
    stores = tuple(sorted({*base.store_refs, *coverages, *source_stores}))
    consumers = tuple(
        sorted(
            {
                *base.consumer_refs,
                EXECUTION_CLOSURE_ENTRYPOINT_REF,
                *coverages,
                *source_consumers,
            }
        )
    )
    gates = base.gate_verdict_refs
    tests = tuple(sorted({*base.test_refs, *validations}))
    return ExecutionClosureSemanticMaterial(
        subject_ref=f"goal_section:§12:execution_aggregate:{aggregate_ref}",
        producer_refs=producers,
        store_refs=stores,
        consumer_refs=consumers,
        gate_verdict_refs=gates,
        test_refs=tests,
    )


class ExecutionClosureSectionAdapter:
    """Prove section 12 from one receipt and its source API lineages."""

    def __init__(
        self,
        entrypoint_registry: Any,
        closure_registry: PersistentExecutionClosureRegistry,
    ) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._closure_registry = closure_registry

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, message: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_execution_closure_invalid",
                    message,
                    field=field,
                    ref=ref,
                )
            )

        owner = _text(owner)
        if record.section != "§12":
            reject("section", record.section, "execution closure adapter only supports section 12")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject("recorded_by", record.recorded_by, "section 12 semantic proof owner mismatch")
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "section 12 completion requires a complete claim with no residuals",
            )
        if (
            not record.entrypoint_coverage_refs
            or len(record.entrypoint_coverage_refs)
            != len(set(record.entrypoint_coverage_refs))
        ):
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "section 12 requires unique source execution API lineages",
            )
            return GoalSemanticDecision(False, tuple(violations))

        receipt_refs = tuple(
            ref
            for ref in record.gate_verdict_refs
            if ref.startswith("execution_closure_receipt:")
        )
        if len(receipt_refs) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(receipt_refs),
                "section 12 requires exactly one durable current execution receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._closure_registry.receipt(
                receipt_ref,
                owner_user_id=owner,
            )
        except (KeyError, ExecutionClosureError):
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "execution closure receipt is absent for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        current = self._closure_registry.validate_current(
            receipt_ref,
            owner_user_id=owner,
        )
        if not current.accepted:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "execution closure receipt is no longer current: "
                + ",".join(item.code for item in current.violations),
            )

        entrypoint_by_kind = {
            "order_intent": "api:research_os.execution.order_intents",
            "runtime_promotion": "api:research_os.execution.runtime_promotions",
            "order_materialization": "api:research_os.execution.order_materializations",
            "venue_connectivity_check": "api:research_os.execution.venue_connectivity_checks",
            "venue_safety_attestation": "api:research_os.execution.venue_safety_attestations",
            "venue_capability": "api:research_os.execution.venue_capabilities",
            "submit_request": "api:research_os.execution.submit_requests",
            "submission": "api:research_os.execution.order_submissions",
            "venue_event": "api:research_os.execution.venue_events",
            "reconciliation": "api:research_os.execution.reconciliations",
            "reconciliation_action": "api:research_os.execution.reconciliation_actions",
            "user_risk_choice": "api:copy_trade.risk_consents.confirm",
        }
        components = {
            item.component_ref: item for item in receipt.snapshot.components
        }
        if len(components) != len(receipt.snapshot.components):
            reject(
                "store_refs",
                receipt_ref,
                "execution closure component refs must be unique",
            )
            return GoalSemanticDecision(False, tuple(violations))

        covered: dict[str, str] = {}
        validation_refs: list[str] = []
        producer_refs: list[str] = []
        store_refs: list[str] = []
        consumer_refs: list[str] = []
        coverage_for_ref = strict_current_entrypoint_lookup(
            self._entrypoint_registry,
            owner=owner,
        )
        for coverage_ref in record.entrypoint_coverage_refs:
            try:
                coverage = coverage_for_ref(coverage_ref)
                backing = self._entrypoint_registry.validate_real_backing(coverage)
            except Exception as exc:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"source execution API lineage could not be resolved: {type(exc).__name__}",
                )
                continue
            if not bool(getattr(backing, "accepted", False)):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "source execution API lineage is not current",
                )
            if _text(getattr(coverage, "recorded_by", "")) != owner:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "source execution API lineage owner mismatch",
                )
            source = _text(
                getattr(
                    getattr(coverage, "entry_source", ""),
                    "value",
                    getattr(coverage, "entry_source", ""),
                )
            )
            entrypoint = _text(getattr(coverage, "entrypoint_ref", ""))
            sections = tuple(
                _text(getattr(section, "value", section))
                for section in (getattr(coverage, "goal_sections", ()) or ())
            )
            if source != "api" or sections != ("§12",):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "execution source coverage must be an API lineage owned exactly by section 12",
                )
                continue
            if bool(getattr(coverage, "silent_mock_fallback_used", False)) or bool(
                getattr(coverage, "raw_payload_persisted", False)
            ):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "execution source coverage cannot use mock fallback or persist raw payloads",
                )
            canonical_refs = tuple(
                _text(ref)
                for ref in getattr(coverage, "canonical_command_refs", ()) or ()
            )
            matched_refs = tuple(ref for ref in canonical_refs if ref in components)
            if len(matched_refs) != 1:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "each source coverage must bind exactly one receipt component",
                )
                continue
            component_ref = matched_refs[0]
            component = components[component_ref]
            expected_entrypoint = entrypoint_by_kind.get(component.component_kind)
            if expected_entrypoint is None or entrypoint != expected_entrypoint:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "source coverage entrypoint does not match its execution component kind",
                )
                continue
            if component_ref in covered:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "one execution component cannot be proved by two source coverages",
                )
                continue
            evidence_refs = tuple(
                _text(ref) for ref in getattr(coverage, "evidence_refs", ()) or ()
            )
            if component_ref not in evidence_refs:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "source coverage evidence does not bind the receipt component",
                )
            current_validations = tuple(
                _text(ref)
                for ref in getattr(coverage, "validation_refs", ()) or ()
            )
            if (
                not current_validations
                or len(current_validations) != len(set(current_validations))
                or not any(
                    ref.startswith("goal_validation_receipt:")
                    for ref in current_validations
                )
            ):
                reject(
                    "test_refs",
                    coverage_ref,
                    "each source execution lineage requires unique durable validation evidence",
                )
            covered[component_ref] = coverage_ref
            validation_refs.extend(current_validations)
            producer_refs.extend(
                _text(ref) for ref in getattr(coverage, "qro_refs", ()) or ()
            )
            producer_refs.extend(
                _text(ref)
                for ref in getattr(coverage, "research_graph_command_refs", ()) or ()
            )
            store_refs.extend(
                _text(ref) for ref in getattr(coverage, "compiler_ir_refs", ()) or ()
            )
            store_refs.extend(
                _text(ref) for ref in getattr(coverage, "compiler_pass_refs", ()) or ()
            )
            consumer_refs.append(entrypoint)

        if set(covered) != set(components):
            reject(
                "entrypoint_coverage_refs",
                ",".join(sorted(set(components) - set(covered))),
                "source execution API lineages must cover every receipt component exactly once",
            )
        try:
            expected = execution_section_semantic_material(
                receipt,
                execution_coverage_refs=tuple(record.entrypoint_coverage_refs),
                execution_validation_refs=tuple(sorted(set(validation_refs))),
                execution_producer_refs=tuple(sorted(set(producer_refs))),
                execution_store_refs=tuple(sorted(set(store_refs))),
                execution_consumer_refs=tuple(sorted(set(consumer_refs))),
            )
        except ValueError as exc:
            reject("store_refs", receipt_ref, str(exc))
            return GoalSemanticDecision(False, tuple(violations))
        if record.subject_ref != expected.subject_ref:
            reject(
                "subject_ref",
                record.subject_ref,
                "section 12 subject must bind the current receipt and source API lineages",
            )
        for field in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            actual = tuple(getattr(record, field))
            wanted = tuple(getattr(expected, field))
            if actual != wanted:
                reject(
                    field,
                    ",".join(actual),
                    f"{field} must exactly match the current section 12 aggregate",
                )
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "EXECUTION_CLOSURE_ENTRYPOINT_REF",
    "EXECUTION_CLOSURE_RECEIPT_VERSION",
    "EXECUTION_CLOSURE_SCHEMA_VERSION",
    "ExecutionClosureCommitUncertain",
    "ExecutionClosureComponentState",
    "ExecutionClosureDecision",
    "ExecutionClosureError",
    "ExecutionClosureReceipt",
    "ExecutionClosureSectionAdapter",
    "ExecutionClosureSemanticMaterial",
    "ExecutionClosureSnapshot",
    "ExecutionClosureViolation",
    "PersistentExecutionClosureRegistry",
    "execution_closure_receipt_from_dict",
    "execution_closure_receipt_identity",
    "execution_closure_semantic_material",
    "execution_closure_snapshot_from_dict",
    "execution_section_semantic_material",
    "validate_execution_closure_receipt_shape",
]
