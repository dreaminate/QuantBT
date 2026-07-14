"""Durable automatic producers for GOAL section 15 recertification events.

The public producer accepts an owner, a current passport, and the persistent
training-job store.  It never accepts a trigger name.  Supported triggers
are derived from exact, canonical before/after state:

* material model change: training-code, model-interface, or artifact bytes;
* new asset class: the typed request bound to each persisted training job;
* new execution environment: the passport ``target_runtime``;
* dependency update: the passport vendor/foundation dependency refs.

Feature-distribution drift and performance degradation are emitted only from a
durable owner/model/passport observation whose immutable rule is breached.  A
monitoring profile alone is configuration and can never manufacture an event.

Detected events are immutable obligations.  This module has no decision, waive,
or resolve API.  A separate recertification record may clear an exact event at a
promotion gate, but detecting an event can never clear itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..cross_process_lock import acquire_exclusive_fd
from .model_governance import (
    ModelGovernancePassport,
    ModelRecertificationRecord,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
)
from .model_recertification_evidence import (
    DependencyKind,
    ModelEvidenceError,
    MonitoringSignalKind,
    PersistentModelRecertificationEvidenceRegistry,
)
from .spine import RuntimeStatus

if TYPE_CHECKING:
    from ..training.store import TrainingJobStore


_SCHEMA_VERSION = 1
_EVENT_TYPE = "model_recertification_change_detected"
_PRODUCER_REF = "model_recertification_evidence_detector:v2"
_LEGACY_PRODUCER_REF = "model_passport_transition_detector:v1"
_OBLIGATION = "requires_recertification"
_SUPPORTED_TRIGGERS = frozenset(
    {
        RecertificationTrigger.MATERIAL_MODEL_CHANGE,
        RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
        RecertificationTrigger.PERFORMANCE_DEGRADATION,
        RecertificationTrigger.NEW_ASSET_CLASS,
        RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,
        RecertificationTrigger.DEPENDENCY_UPDATE,
    }
)


class ModelRecertificationEventError(ValueError):
    """A request or persisted event ledger is invalid."""


class ModelRecertificationEvidenceError(ModelRecertificationEventError):
    """The current typed before/after evidence cannot be resolved exactly."""


class ModelRecertificationCommitUncertain(RuntimeError):
    """An event append failed and its rollback could not be verified."""


def _required(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ModelRecertificationEventError(
            f"model recertification event {field_name} is required"
        )
    return normalized


def _enum_value(value: Any) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value or "")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ModelRecertificationEvidenceError(
            "model recertification state must be finite canonical JSON"
        ) from exc


def _sha256(prefix: str, value: Any) -> str:
    return prefix + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_refs(values: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ModelRecertificationEvidenceError(f"{field_name} must be a tuple or list")
    normalized = tuple(_required(value, field_name) for value in values)
    if not normalized:
        raise ModelRecertificationEvidenceError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise ModelRecertificationEvidenceError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def _ordered_refs(values: Any, field_name: str) -> tuple[str, ...]:
    """Validate refs without sorting when their order changes model behavior."""

    if not isinstance(values, (list, tuple)):
        raise ModelRecertificationEvidenceError(f"{field_name} must be a tuple or list")
    normalized = tuple(_required(value, field_name) for value in values)
    if not normalized:
        raise ModelRecertificationEvidenceError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise ModelRecertificationEvidenceError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class ModelChangeState:
    """Canonical semantic state plus the exact persisted refs that supplied it."""

    canonical_state_json: str
    evidence_refs: tuple[str, ...]
    state_hash: str = ""

    def __post_init__(self) -> None:
        raw = _required(self.canonical_state_json, "canonical_state_json")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelRecertificationEventError(
                "model recertification canonical_state_json is invalid"
            ) from exc
        if not isinstance(parsed, dict) or not parsed:
            raise ModelRecertificationEventError(
                "model recertification canonical state must be a non-empty object"
            )
        canonical = _canonical_json(parsed)
        if raw != canonical:
            raise ModelRecertificationEventError(
                "model recertification state JSON must already be canonical"
            )
        refs = tuple(_required(ref, "evidence_ref") for ref in self.evidence_refs)
        if not refs or len(refs) != len(set(refs)):
            raise ModelRecertificationEventError(
                "model recertification state requires unique evidence refs"
            )
        expected = _sha256("model_recertification_state_", parsed)
        supplied = str(self.state_hash or "").strip()
        if supplied and supplied != expected:
            raise ModelRecertificationEventError(
                "model recertification state hash does not match canonical state"
            )
        object.__setattr__(self, "canonical_state_json", canonical)
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "state_hash", expected)

    @classmethod
    def build(cls, state: dict[str, Any], evidence_refs: tuple[str, ...]) -> ModelChangeState:
        return cls(_canonical_json(state), evidence_refs)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True)
class ModelRecertificationChangeEvent:
    """One immutable, owner-scoped recertification obligation."""

    owner_user_id: str
    model_type_card_ref: str
    trigger: RecertificationTrigger
    before_passport_ref: str
    after_passport_ref: str
    before_model_version_ref: str
    after_model_version_ref: str
    before_state: ModelChangeState
    after_state: ModelChangeState
    producer_ref: str = _PRODUCER_REF
    obligation: str = _OBLIGATION
    event_ref: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "owner_user_id",
            "model_type_card_ref",
            "before_passport_ref",
            "after_passport_ref",
            "before_model_version_ref",
            "after_model_version_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name),
            )
        try:
            trigger = (
                self.trigger
                if isinstance(self.trigger, RecertificationTrigger)
                else RecertificationTrigger(str(self.trigger))
            )
        except ValueError as exc:
            raise ModelRecertificationEventError(
                "model recertification event trigger is unsupported"
            ) from exc
        if trigger not in _SUPPORTED_TRIGGERS:
            raise ModelRecertificationEventError(
                "model recertification event trigger has no automatic producer"
            )
        object.__setattr__(self, "trigger", trigger)
        if (
            trigger
            in {
                RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
                RecertificationTrigger.PERFORMANCE_DEGRADATION,
            }
            and (
                self.before_passport_ref != self.after_passport_ref
                or self.before_model_version_ref != self.after_model_version_ref
            )
        ):
            raise ModelRecertificationEventError(
                "model monitoring passport transition has no automatic producer"
            )
        if self.producer_ref not in {_PRODUCER_REF, _LEGACY_PRODUCER_REF}:
            raise ModelRecertificationEventError(
                "model recertification event producer_ref is not canonical"
            )
        if self.obligation != _OBLIGATION:
            raise ModelRecertificationEventError(
                "model recertification event may only create a recertification obligation"
            )
        if (
            self.before_passport_ref == self.after_passport_ref
            and trigger
            not in {
                RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
                RecertificationTrigger.PERFORMANCE_DEGRADATION,
                RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,
            }
        ):
            raise ModelRecertificationEventError(
                "passport-transition event requires distinct passport refs"
            )
        if self.before_state.state_hash == self.after_state.state_hash:
            raise ModelRecertificationEventError(
                "model recertification event requires changed semantic state"
            )
        material = self.identity_material()
        expected = _sha256("model_recertification_event_", material)
        supplied = str(self.event_ref or "").strip()
        if supplied and supplied != expected:
            raise ModelRecertificationEventError(
                "model recertification event ref does not match exact transition"
            )
        object.__setattr__(self, "event_ref", expected)

    def identity_material(self) -> dict[str, Any]:
        return {
            "owner_user_id": self.owner_user_id,
            "model_type_card_ref": self.model_type_card_ref,
            "trigger": _enum_value(self.trigger),
            "before_passport_ref": self.before_passport_ref,
            "after_passport_ref": self.after_passport_ref,
            "before_model_version_ref": self.before_model_version_ref,
            "after_model_version_ref": self.after_model_version_ref,
            "before_state": self.before_state.to_dict(),
            "after_state": self.after_state.to_dict(),
            "producer_ref": self.producer_ref,
            "obligation": self.obligation,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_material()
        payload["event_ref"] = self.event_ref
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModelRecertificationChangeEvent:
        if not isinstance(raw, dict):
            raise ModelRecertificationEventError(
                "model recertification event payload must be an object"
            )
        expected_keys = {
            "owner_user_id",
            "model_type_card_ref",
            "trigger",
            "before_passport_ref",
            "after_passport_ref",
            "before_model_version_ref",
            "after_model_version_ref",
            "before_state",
            "after_state",
            "producer_ref",
            "obligation",
            "event_ref",
        }
        if set(raw) != expected_keys:
            raise ModelRecertificationEventError(
                "model recertification event payload fields are inexact"
            )
        before = raw.get("before_state")
        after = raw.get("after_state")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ModelRecertificationEventError(
                "model recertification event requires before and after state"
            )
        state_keys = {"canonical_state_json", "evidence_refs", "state_hash"}
        if set(before) != state_keys or set(after) != state_keys:
            raise ModelRecertificationEventError(
                "model recertification state payload fields are inexact"
            )
        return cls(
            owner_user_id=str(raw.get("owner_user_id") or ""),
            model_type_card_ref=str(raw.get("model_type_card_ref") or ""),
            trigger=RecertificationTrigger(str(raw.get("trigger") or "")),
            before_passport_ref=str(raw.get("before_passport_ref") or ""),
            after_passport_ref=str(raw.get("after_passport_ref") or ""),
            before_model_version_ref=str(raw.get("before_model_version_ref") or ""),
            after_model_version_ref=str(raw.get("after_model_version_ref") or ""),
            before_state=ModelChangeState(
                canonical_state_json=str(before.get("canonical_state_json") or ""),
                evidence_refs=tuple(before.get("evidence_refs") or ()),
                state_hash=str(before.get("state_hash") or ""),
            ),
            after_state=ModelChangeState(
                canonical_state_json=str(after.get("canonical_state_json") or ""),
                evidence_refs=tuple(after.get("evidence_refs") or ()),
                state_hash=str(after.get("state_hash") or ""),
            ),
            producer_ref=str(raw.get("producer_ref") or ""),
            obligation=str(raw.get("obligation") or ""),
            event_ref=str(raw.get("event_ref") or ""),
        )


@dataclass(frozen=True)
class ModelRecertificationProducerStatus:
    trigger: RecertificationTrigger
    available: bool
    evidence_kind: str
    blocker: str = ""
    limitation: str = ""


@dataclass(frozen=True)
class ModelRecertificationRequirement:
    """One exact transition that must have a current clearing review record."""

    trigger: RecertificationTrigger
    change_event_ref: str
    before_passport_ref: str
    after_passport_ref: str
    event_record_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, RecertificationTrigger):
            raise ModelRecertificationEventError(
                "model recertification requirement trigger must be typed"
            )
        for field_name in (
            "change_event_ref",
            "before_passport_ref",
            "after_passport_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "event_record_hash", str(self.event_record_hash or "").strip())


@dataclass(frozen=True)
class ModelRecertificationResolution:
    """Exact obligations and the latest owner-scoped reviews that clear them."""

    passport_ref: str
    requirements: tuple[ModelRecertificationRequirement, ...]
    automatic_events: tuple[ModelRecertificationChangeEvent, ...]
    recertification_records: tuple[ModelRecertificationRecord, ...]
    producer_statuses: tuple[ModelRecertificationProducerStatus, ...]

    @property
    def required_triggers(self) -> tuple[RecertificationTrigger, ...]:
        return tuple(requirement.trigger for requirement in self.requirements)

    def gate_metadata(
        self,
        governance: PersistentModelGovernanceRegistry,
        *,
        owner_user_id: str,
    ) -> dict[str, Any]:
        record_heads = {
            record.recertification_record_id: governance.current_head_hash(
                record.recertification_record_id,
                owner_user_id=owner_user_id,
                event_type="model_recertification_recorded",
            )
            for record in self.recertification_records
        }
        return {
            "model_recertification_required_triggers": [
                requirement.trigger.value for requirement in self.requirements
            ],
            "model_recertification_event_refs": [
                requirement.change_event_ref for requirement in self.requirements
            ],
            "model_recertification_event_record_hashes": {
                requirement.change_event_ref: requirement.event_record_hash
                for requirement in self.requirements
                if requirement.event_record_hash
            },
            "model_recertification_record_refs": [
                record.recertification_record_id for record in self.recertification_records
            ],
            "model_recertification_record_head_hashes": record_heads,
            "model_recertification_producer_statuses": [
                {
                    "trigger": status.trigger.value,
                    "available": status.available,
                    "evidence_kind": status.evidence_kind,
                    "blocker": status.blocker,
                    "limitation": status.limitation,
                }
                for status in self.producer_statuses
            ],
        }


_BASE_PRODUCER_STATUSES = (
    ModelRecertificationProducerStatus(
        RecertificationTrigger.MATERIAL_MODEL_CHANGE,
        True,
        "owner-scoped consecutive model governance passports",
    ),
    ModelRecertificationProducerStatus(
        RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
        False,
        "owner/model-scoped feature distribution observations",
        "no durable owner/model-scoped feature-distribution observation store exists; "
        "monitoring profile drift_signal_refs are configuration, not observations",
    ),
    ModelRecertificationProducerStatus(
        RecertificationTrigger.PERFORMANCE_DEGRADATION,
        False,
        "owner/model-scoped production performance observations and threshold verdicts",
        "no durable owner/model-scoped production-performance observation store is bound "
        "to ModelMonitoringProfile thresholds; factor monitoring is not model evidence",
    ),
    ModelRecertificationProducerStatus(
        RecertificationTrigger.NEW_ASSET_CLASS,
        True,
        "typed TrainingRequest bound to each persisted TrainingJob/passport",
    ),
    ModelRecertificationProducerStatus(
        RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,
        True,
        "owner-scoped consecutive passport target_runtime",
        limitation="a ModelRegistry stage change without a new passport is not a passport transition",
    ),
    ModelRecertificationProducerStatus(
        RecertificationTrigger.DEPENDENCY_UPDATE,
        False,
        "owner-scoped content-bound dependency fingerprint ledger",
        "no durable dependency evidence registry is bound",
    ),
)


def producer_statuses(
    *,
    evidence_registry_available: bool = False,
    model_registry_available: bool = False,
) -> tuple[ModelRecertificationProducerStatus, ...]:
    """Return producer capabilities for the stores actually bound to detection."""

    statuses: list[ModelRecertificationProducerStatus] = []
    for status in _BASE_PRODUCER_STATUSES:
        if status.trigger in {
            RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
            RecertificationTrigger.PERFORMANCE_DEGRADATION,
        } and evidence_registry_available:
            statuses.append(
                ModelRecertificationProducerStatus(
                    status.trigger,
                    True,
                    "hash-chained owner/model/passport monitoring rule and observation ledger",
                )
            )
        elif status.trigger == RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT:
            if model_registry_available:
                statuses.append(
                    ModelRecertificationProducerStatus(
                        status.trigger,
                        True,
                        "passport target_runtime plus durable ModelRegistry governed-stage history",
                    )
                )
            else:
                statuses.append(status)
        elif status.trigger == RecertificationTrigger.DEPENDENCY_UPDATE:
            if evidence_registry_available:
                statuses.append(
                    ModelRecertificationProducerStatus(
                        status.trigger,
                        True,
                        "owner-scoped content-bound dependency fingerprint ledger",
                    )
                )
            else:
                statuses.append(status)
        else:
            statuses.append(status)
    return tuple(statuses)


def _passport_artifact_state(passport: ModelGovernancePassport) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for artifact in passport.artifact_manifest:
        artifacts.append(
            {
                "artifact_format": _required(artifact.artifact_format, "artifact_format"),
                "source": _required(artifact.source, "artifact_source"),
                "content_hash": _required(artifact.content_hash, "artifact_content_hash"),
            }
        )
    if not artifacts:
        raise ModelRecertificationEvidenceError(
            "material model state requires an artifact manifest"
        )
    artifacts.sort(key=_canonical_json)
    return artifacts


def _material_state(passport: ModelGovernancePassport) -> ModelChangeState:
    # Input order is behavioral for many estimators; do not sort it away.  A
    # feature reorder with the same set must still create a material-change event.
    feature_refs = _ordered_refs(passport.feature_refs, "feature_refs")
    label_refs = _ordered_refs(passport.label_refs, "label_refs")
    artifacts = _passport_artifact_state(passport)
    return ModelChangeState.build(
        {
            "training_code_hash": _required(
                passport.training_code_hash, "training_code_hash"
            ),
            "feature_refs": list(feature_refs),
            "label_refs": list(label_refs),
            "artifacts": artifacts,
        },
        (
            passport.passport_id,
            _required(passport.training_run_ref, "training_run_ref"),
            *(artifact.artifact_ref for artifact in passport.artifact_manifest),
        ),
    )


def _runtime_state(passport: ModelGovernancePassport) -> ModelChangeState:
    raw_runtime = _required(_enum_value(passport.target_runtime), "target_runtime")
    try:
        runtime = RuntimeStatus(raw_runtime).value
    except ValueError as exc:
        raise ModelRecertificationEvidenceError(
            "new-execution-environment producer requires a typed RuntimeStatus"
        ) from exc
    return ModelChangeState.build(
        {"target_runtime": runtime},
        (passport.passport_id,),
    )


def _dependency_state(
    passport: ModelGovernancePassport,
    *,
    owner_user_id: str,
    evidence_registry: PersistentModelRecertificationEvidenceRegistry | None,
) -> ModelChangeState:
    if evidence_registry is None:
        vendor_refs = _normalized_refs(
            passport.vendor_dependency_refs,
            "vendor_dependency_refs",
        )
        foundation_refs = _normalized_refs(
            passport.foundation_model_dependency_refs,
            "foundation_model_dependency_refs",
        )
        if vendor_refs != ("none",) or foundation_refs != ("none",):
            raise ModelRecertificationEvidenceError(
                "dependency producer requires a durable content-fingerprint registry"
            )
        return ModelChangeState.build(
            {
                "vendor_dependencies": [],
                "foundation_model_dependencies": [],
                "resolution": "no_external_dependencies",
            },
            (passport.passport_id,),
        )
    try:
        vendor = evidence_registry.resolve_dependencies(
            passport.vendor_dependency_refs,
            owner_user_id=owner_user_id,
            dependency_kind=DependencyKind.VENDOR,
        )
        foundation = evidence_registry.resolve_dependencies(
            passport.foundation_model_dependency_refs,
            owner_user_id=owner_user_id,
            dependency_kind=DependencyKind.FOUNDATION_MODEL,
        )
    except (KeyError, ModelEvidenceError) as exc:
        raise ModelRecertificationEvidenceError(
            "dependency producer cannot resolve every declared content fingerprint"
        ) from exc
    records = (*vendor, *foundation)
    return ModelChangeState.build(
        {
            "vendor_dependencies": [
                {
                    "dependency_ref": item.dependency_ref,
                    "content_fingerprint": item.content_fingerprint,
                    "resolver_ref": item.resolver_ref,
                }
                for item in vendor
            ],
            "foundation_model_dependencies": [
                {
                    "dependency_ref": item.dependency_ref,
                    "content_fingerprint": item.content_fingerprint,
                    "resolver_ref": item.resolver_ref,
                }
                for item in foundation
            ],
        },
        (
            passport.passport_id,
            *(item.fingerprint_ref for item in records),
            *(evidence_registry.current_record_hash(item.fingerprint_ref, owner_user_id=owner_user_id) for item in records),
        ),
    )


def _asset_class_state(
    passport: ModelGovernancePassport,
    *,
    owner_user_id: str,
    training_jobs: TrainingJobStore,
) -> ModelChangeState:
    prefix = "training_plan:"
    if not passport.training_plan_ref.startswith(prefix):
        raise ModelRecertificationEvidenceError(
            "new-asset-class producer requires a training-service training_plan_ref"
        )
    job_id = passport.training_plan_ref[len(prefix) :]
    if not job_id:
        raise ModelRecertificationEvidenceError(
            "new-asset-class producer requires a concrete training job id"
        )
    try:
        job = training_jobs.get(job_id)
    except Exception as exc:  # noqa: BLE001 - exact backing is fail closed.
        raise ModelRecertificationEvidenceError(
            f"new-asset-class producer cannot resolve training job {job_id}"
        ) from exc
    if _required(getattr(job, "owner_user_id", ""), "training_job.owner_user_id") != owner_user_id:
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job owner does not match event owner"
        )
    if getattr(job, "status", None) != "succeeded":
        raise ModelRecertificationEvidenceError(
            "new-asset-class producer requires a succeeded training job"
        )
    model = _required(getattr(job, "model", ""), "training_job.model")
    if f"model_type_card:{model}" != passport.model_type_card_ref:
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job does not match model type card"
        )
    run_id = _required(getattr(job, "run_id", ""), "training_job.run_id")
    if passport.training_run_ref != f"training_run:{run_id}":
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job does not match passport training run"
        )
    if getattr(job, "model_passport_ref", None) != passport.passport_id:
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job does not bind the passport"
        )
    version = getattr(job, "model_version", None)
    if type(version) is not int or version <= 0:
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job requires a positive model version"
        )
    if passport.model_version_ref != f"model_version:{model}:v{version}":
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job version does not match passport"
        )
    request = getattr(job, "request", None)
    if not isinstance(request, dict):
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job request must be an object"
        )
    try:
        # Lazy import avoids a module cycle if TrainingService later wires this
        # producer after persisting a completed job.
        from ..training.service import TrainingRequest

        typed_request = TrainingRequest(**request)
    except Exception as exc:  # noqa: BLE001 - malformed persisted request is evidence failure.
        raise ModelRecertificationEvidenceError(
            "new-asset-class training job request is not a typed TrainingRequest"
        ) from exc
    if (
        typed_request.name != getattr(job, "name", None)
        or typed_request.model != model
        or typed_request.task != getattr(job, "task", None)
        or tuple(typed_request.feature_cols) != tuple(passport.feature_refs)
        or (typed_request.label_col,) != tuple(passport.label_refs)
    ):
        raise ModelRecertificationEvidenceError(
            "new-asset-class typed request does not match training job/passport"
        )
    if not isinstance(typed_request.asset_class, str):
        raise ModelRecertificationEvidenceError(
            "TrainingRequest.asset_class must be a typed string"
        )
    asset_class = _required(typed_request.asset_class, "TrainingRequest.asset_class")
    job_state_ref = _sha256("training_job_state_", job.to_dict())
    return ModelChangeState.build(
        {"asset_class": asset_class},
        (passport.passport_id, passport.training_plan_ref, job_state_ref),
    )


def _event(
    *,
    owner_user_id: str,
    trigger: RecertificationTrigger,
    before: ModelGovernancePassport,
    after: ModelGovernancePassport,
    before_state: ModelChangeState,
    after_state: ModelChangeState,
) -> ModelRecertificationChangeEvent:
    return ModelRecertificationChangeEvent(
        owner_user_id=owner_user_id,
        model_type_card_ref=after.model_type_card_ref,
        trigger=trigger,
        before_passport_ref=before.passport_id,
        after_passport_ref=after.passport_id,
        before_model_version_ref=before.model_version_ref,
        after_model_version_ref=after.model_version_ref,
        before_state=before_state,
        after_state=after_state,
    )


def _monitoring_events(
    *,
    governance: PersistentModelGovernanceRegistry,
    evidence_registry: PersistentModelRecertificationEvidenceRegistry | None,
    owner_user_id: str,
    passport: ModelGovernancePassport,
) -> tuple[ModelRecertificationChangeEvent, ...]:
    if evidence_registry is None:
        return ()
    try:
        breaches = evidence_registry.breached_observations(
            owner_user_id=owner_user_id,
            model_type_card_ref=passport.model_type_card_ref,
            model_passport_ref=passport.passport_id,
        )
    except ModelEvidenceError as exc:
        raise ModelRecertificationEvidenceError(
            "monitoring producer evidence cannot be resolved"
        ) from exc
    trigger_by_kind = {
        MonitoringSignalKind.FEATURE_DISTRIBUTION: RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
        MonitoringSignalKind.PERFORMANCE: RecertificationTrigger.PERFORMANCE_DEGRADATION,
    }
    events: list[ModelRecertificationChangeEvent] = []
    for rule, observation in breaches:
        if (
            rule.owner_user_id != owner_user_id
            or rule.model_type_card_ref != passport.model_type_card_ref
            or rule.model_version_ref != passport.model_version_ref
            or rule.model_passport_ref != passport.passport_id
        ):
            raise ModelRecertificationEvidenceError(
                "monitoring breach does not bind the current owner/model/passport"
            )
        try:
            profile = governance.monitoring_profile(
                rule.monitoring_profile_ref,
                owner_user_id=owner_user_id,
            )
        except KeyError as exc:
            raise ModelRecertificationEvidenceError(
                "monitoring breach rule profile is not recorded for owner"
            ) from exc
        expected_refs = (
            profile.drift_signal_refs
            if rule.signal_kind == MonitoringSignalKind.FEATURE_DISTRIBUTION
            else profile.performance_threshold_refs
        )
        if (
            profile.model_passport_ref != passport.passport_id
            or profile.model_version_ref != passport.model_version_ref
            or rule.signal_ref not in expected_refs
        ):
            raise ModelRecertificationEvidenceError(
                "monitoring breach rule is not authorized by the bound profile"
            )
        before_state = ModelChangeState.build(
            {
                "rule_ref": rule.rule_ref,
                "signal_kind": rule.signal_kind.value,
                "signal_ref": rule.signal_ref,
                "baseline_value": rule.baseline_value,
                "threshold_value": rule.threshold_value,
                "comparison": rule.comparison.value,
                "breached": False,
            },
            (
                passport.passport_id,
                profile.monitoring_profile_id,
                rule.rule_ref,
                evidence_registry.current_record_hash(rule.rule_ref, owner_user_id=owner_user_id),
            ),
        )
        after_state = ModelChangeState.build(
            {
                "rule_ref": rule.rule_ref,
                "observation_record_ref": observation.record_ref,
                "observation_ref": observation.observation_ref,
                "observed_value": observation.observed_value,
                "breached": True,
            },
            (
                passport.passport_id,
                rule.rule_ref,
                observation.record_ref,
                evidence_registry.current_record_hash(observation.record_ref, owner_user_id=owner_user_id),
            ),
        )
        events.append(
            _event(
                owner_user_id=owner_user_id,
                trigger=trigger_by_kind[rule.signal_kind],
                before=passport,
                after=passport,
                before_state=before_state,
                after_state=after_state,
            )
        )
    return tuple(events)


def _stage_environment_event(
    *,
    model_registry: Any | None,
    owner_user_id: str,
    passport: ModelGovernancePassport,
    proposed_execution_stage: str | None = None,
) -> tuple[ModelRecertificationChangeEvent, ...]:
    """Emit a stage-only environment event before and after a governed change.

    The first staging/production row establishes the environment baseline.  A
    later transition between governed stages (for example staging→production)
    is a new execution environment even when no new passport was issued.  The
    optional stage is a typed ModelRegistry target, not a caller-supplied trigger;
    it lets the event be reviewed and bound into the promotion gate *before* the
    stage side effect executes.  After execution, the same semantic transition
    is reconstructed from durable history and therefore has the same event ref.
    """

    if model_registry is None:
        return ()
    stage_history = getattr(model_registry, "stage_history", None)
    if not callable(stage_history):
        raise ModelRecertificationEvidenceError(
            "stage environment producer requires a typed ModelRegistry history getter"
        )
    allowed_stages = {"dev", "staging", "production", "archived"}
    proposed = str(proposed_execution_stage or "").strip()
    if proposed and proposed not in allowed_stages:
        raise ModelRecertificationEvidenceError(
            "stage environment producer target stage is unsupported"
        )
    version_prefix = "model_version:"
    if not passport.model_type_card_ref or not passport.model_version_ref.startswith(version_prefix):
        raise ModelRecertificationEvidenceError("stage environment producer model refs are invalid")
    version_material = passport.model_version_ref[len(version_prefix):]
    try:
        model_id, raw_version = version_material.rsplit(":", 1)
        version = int(raw_version[1:] if raw_version.startswith("v") else raw_version)
        if not model_id or version <= 0:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ModelRecertificationEvidenceError("stage environment producer version is invalid") from exc
    try:
        raw_history = tuple(
            stage_history(
                model_id,
                version,
                owner_user_id=owner_user_id,
            )
        )
    except KeyError:
        # A passport may be recorded before its ModelRegistry version row.  In
        # that state there is no stage transition to derive; the passport-level
        # runtime producer remains active and later promotion re-evaluates after
        # the model version exists.
        return ()
    except (TypeError, ValueError) as exc:
        raise ModelRecertificationEvidenceError(
            "stage environment producer cannot resolve durable ModelRegistry history"
        ) from exc
    if not raw_history:
        raise ModelRecertificationEvidenceError(
            "stage environment producer resolved an empty model history"
        )
    current = raw_history[-1]
    if (
        getattr(current, "owner_user_id", None) != owner_user_id
        or getattr(current, "model_id", None) != model_id
        or getattr(current, "version", None) != version
        or getattr(current, "model_passport_ref", None)
        not in {None, "", passport.passport_id}
        or getattr(current, "validation_dossier_ref", None)
        not in {None, "", passport.validation_dossier_ref}
    ):
        raise ModelRecertificationEvidenceError(
            "stage environment model version does not bind the current passport"
        )
    governed: list[str] = []
    for item in raw_history:
        item_stage = str(getattr(item, "stage", "") or "")
        if item_stage in {"staging", "production"} and (
            not governed or governed[-1] != item_stage
        ):
            governed.append(item_stage)

    transition: tuple[str, str] | None = None
    current_stage = str(getattr(current, "stage", "") or "")
    if proposed and proposed != current_stage:
        # A first governed stage is the baseline; only a later governed-to-
        # governed change creates the stage-only obligation.
        if current_stage in {"staging", "production"} and proposed in {
            "staging",
            "production",
        }:
            transition = (current_stage, proposed)
    elif current_stage in {"staging", "production"} and len(governed) >= 2:
        transition = (governed[-2], governed[-1])
    if transition is None or transition[0] == transition[1]:
        return ()

    common_state = {
        "owner_user_id": owner_user_id,
        "model_id": model_id,
        "version": version,
        "model_passport_ref": passport.passport_id,
    }
    evidence_refs = (passport.passport_id, passport.model_version_ref)
    before_state = ModelChangeState.build(
        {**common_state, "governed_stage": transition[0]},
        evidence_refs,
    )
    after_state = ModelChangeState.build(
        {**common_state, "governed_stage": transition[1]},
        evidence_refs,
    )
    return (
        _event(
            owner_user_id=owner_user_id,
            trigger=RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,
            before=passport,
            after=passport,
            before_state=before_state,
            after_state=after_state,
        ),
    )


def _detect_transition(
    *,
    governance: PersistentModelGovernanceRegistry,
    owner_user_id: str,
    current_passport_ref: str,
    training_jobs: TrainingJobStore,
    evidence_registry: PersistentModelRecertificationEvidenceRegistry | None = None,
    model_registry: Any | None = None,
    proposed_execution_stage: str | None = None,
) -> tuple[ModelRecertificationChangeEvent, ...]:
    # Importing ``training.store`` at module load time enters ``training.__init__``
    # and cycles through TrainingService -> model_governance_closure -> this module.
    # Detection runs only after service construction, so the exact runtime type
    # check belongs here.
    from ..training.store import TrainingJobStore

    if not isinstance(governance, PersistentModelGovernanceRegistry):
        raise ModelRecertificationEvidenceError(
            "model recertification detection requires a persistent governance registry"
        )
    if not isinstance(training_jobs, TrainingJobStore):
        raise ModelRecertificationEvidenceError(
            "model recertification detection requires a persistent TrainingJobStore"
        )
    owner = _required(owner_user_id, "owner_user_id")
    passport_ref = _required(current_passport_ref, "current_passport_ref")
    try:
        current = governance.passport(passport_ref, owner_user_id=owner)
    except KeyError as exc:
        raise ModelRecertificationEvidenceError(
            "current passport is not recorded for owner"
        ) from exc
    passports = governance.passports(owner_user_id=owner)
    indexes = [
        index
        for index, candidate in enumerate(passports)
        if candidate.passport_id == current.passport_id
    ]
    if len(indexes) != 1:
        raise ModelRecertificationEvidenceError(
            "current passport must occur exactly once in owner history"
        )
    prior = next(
        (
            candidate
            for candidate in reversed(passports[: indexes[0]])
            if candidate.model_type_card_ref == current.model_type_card_ref
        ),
        None,
    )
    non_transition_events = (
        *_monitoring_events(
            governance=governance,
            evidence_registry=evidence_registry,
            owner_user_id=owner,
            passport=current,
        ),
        *_stage_environment_event(
            model_registry=model_registry,
            owner_user_id=owner,
            passport=current,
            proposed_execution_stage=proposed_execution_stage,
        ),
    )
    if prior is None:
        return tuple(non_transition_events)
    if prior.owner_user_id != owner or current.owner_user_id != owner:
        raise ModelRecertificationEvidenceError(
            "passport owner does not match transition owner"
        )
    if prior.model_type_card_ref != current.model_type_card_ref:
        raise ModelRecertificationEvidenceError(
            "passport transition crosses model type cards"
        )

    state_pairs = (
        (
            RecertificationTrigger.MATERIAL_MODEL_CHANGE,
            _material_state(prior),
            _material_state(current),
        ),
        (
            RecertificationTrigger.NEW_ASSET_CLASS,
            _asset_class_state(
                prior,
                owner_user_id=owner,
                training_jobs=training_jobs,
            ),
            _asset_class_state(
                current,
                owner_user_id=owner,
                training_jobs=training_jobs,
            ),
        ),
        (
            RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,
            _runtime_state(prior),
            _runtime_state(current),
        ),
        (
            RecertificationTrigger.DEPENDENCY_UPDATE,
            _dependency_state(
                prior,
                owner_user_id=owner,
                evidence_registry=evidence_registry,
            ),
            _dependency_state(
                current,
                owner_user_id=owner,
                evidence_registry=evidence_registry,
            ),
        ),
    )
    events = [
        _event(
            owner_user_id=owner,
            trigger=trigger,
            before=prior,
            after=current,
            before_state=before_state,
            after_state=after_state,
        )
        for trigger, before_state, after_state in state_pairs
        if before_state.state_hash != after_state.state_hash
    ]
    identities = {(event.trigger.value, event.event_ref) for event in events}
    for event in non_transition_events:
        identity = (event.trigger.value, event.event_ref)
        if identity not in identities:
            events.append(event)
            identities.add(identity)
    return tuple(events)


class PersistentModelRecertificationEventRegistry:
    """Strict append-only ledger for automatically detected change events."""

    def __init__(
        self,
        path: str | Path,
        *,
        evidence_registry: PersistentModelRecertificationEvidenceRegistry | None = None,
        model_registry: Any | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._evidence_registry = evidence_registry
        self._model_registry = model_registry
        self._events: dict[tuple[str, str], ModelRecertificationChangeEvent] = {}
        self._record_hashes: dict[tuple[str, str], str] = {}
        self._ordered: list[ModelRecertificationChangeEvent] = []
        self._last_record_hash = ""
        self._refresh()

    @property
    def evidence_registry(self) -> PersistentModelRecertificationEvidenceRegistry | None:
        return self._evidence_registry

    def bind_sources(
        self,
        *,
        evidence_registry: PersistentModelRecertificationEvidenceRegistry,
        model_registry: Any,
    ) -> None:
        """Bind exact canonical sibling stores once; later identity drift is rejected."""

        if not isinstance(evidence_registry, PersistentModelRecertificationEvidenceRegistry):
            raise ModelRecertificationEventError("invalid recertification evidence registry")
        if self._evidence_registry is not None and self._evidence_registry is not evidence_registry:
            if Path(self._evidence_registry.path) != Path(evidence_registry.path):
                raise ModelRecertificationEventError("recertification evidence registry path mismatch")
        if self._model_registry is not None and self._model_registry is not model_registry:
            raise ModelRecertificationEventError("model registry identity mismatch")
        self._evidence_registry = evidence_registry
        self._model_registry = model_registry

    def producer_statuses(self) -> tuple[ModelRecertificationProducerStatus, ...]:
        return producer_statuses(
            evidence_registry_available=self._evidence_registry is not None,
            model_registry_available=self._model_registry is not None,
        )

    @property
    def path(self) -> Path:
        return self._path

    def _acquire_file_lock(self) -> tuple[int, Any]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
        except Exception:
            os.close(fd)
            raise
        return fd, held

    @staticmethod
    def _record_hash(row: dict[str, Any]) -> str:
        material = dict(row)
        material.pop("record_hash", None)
        return _sha256("model_recertification_record_", material)

    def _reset(self) -> None:
        self._events = {}
        self._record_hashes = {}
        self._ordered = []
        self._last_record_hash = ""

    def _apply_row(self, row: dict[str, Any]) -> None:
        expected_keys = {
            "schema_version",
            "event_type",
            "sequence",
            "owner_user_id",
            "previous_record_hash",
            "event",
            "record_hash",
        }
        if set(row) != expected_keys:
            raise ModelRecertificationEventError(
                "model recertification persisted row fields are inexact"
            )
        if row.get("schema_version") != _SCHEMA_VERSION:
            raise ModelRecertificationEventError(
                "model recertification event schema_version=1 is required"
            )
        if row.get("event_type") != _EVENT_TYPE:
            raise ModelRecertificationEventError(
                "model recertification persisted event_type is unsupported"
            )
        sequence = row.get("sequence")
        if type(sequence) is not int or sequence != len(self._ordered) + 1:
            raise ModelRecertificationEventError(
                "model recertification event sequence is missing or forked"
            )
        previous = str(row.get("previous_record_hash") or "").strip()
        if previous != self._last_record_hash:
            raise ModelRecertificationEventError(
                "model recertification event hash chain is missing or forked"
            )
        record_hash = _required(row.get("record_hash"), "record_hash")
        if record_hash != self._record_hash(row):
            raise ModelRecertificationEventError(
                "model recertification persisted record hash does not match content"
            )
        raw_event = row.get("event")
        if not isinstance(raw_event, dict):
            raise ModelRecertificationEventError(
                "model recertification persisted row requires an event object"
            )
        event = ModelRecertificationChangeEvent.from_dict(raw_event)
        owner = _required(row.get("owner_user_id"), "owner_user_id")
        if owner != event.owner_user_id:
            raise ModelRecertificationEventError(
                "model recertification row owner does not match event owner"
            )
        key = (owner, event.event_ref)
        if key in self._events:
            raise ModelRecertificationEventError(
                "model recertification persisted event ref is duplicated"
            )
        self._events[key] = event
        self._record_hashes[key] = record_hash
        self._ordered.append(event)
        self._last_record_hash = record_hash

    def _load_locked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ModelRecertificationEventError(
                            "model recertification persisted row must be an object"
                        )
                    self._apply_row(row)
                except Exception as exc:  # noqa: BLE001 - corruption must fail closed.
                    raise ModelRecertificationEventError(
                        f"invalid model recertification event row at {self._path}:{line_no}"
                    ) from exc

    def _refresh(self) -> None:
        with self._thread_lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_locked()
            finally:
                held.release()
                os.close(fd)

    def _rows_for(self, events: tuple[ModelRecertificationChangeEvent, ...]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        previous = self._last_record_hash
        sequence = len(self._ordered)
        for event in events:
            sequence += 1
            row = {
                "schema_version": _SCHEMA_VERSION,
                "event_type": _EVENT_TYPE,
                "sequence": sequence,
                "owner_user_id": event.owner_user_id,
                "previous_record_hash": previous,
                "event": event.to_dict(),
            }
            row["record_hash"] = self._record_hash(row)
            previous = row["record_hash"]
            rows.append(row)
        return rows

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _restore_original(self, *, existed: bool, payload: bytes) -> None:
        if existed:
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(fd, payload[offset:])
                    if written <= 0:
                        raise OSError("model recertification rollback write made no progress")
                    offset += written
                os.fsync(fd)
            finally:
                os.close(fd)
            return
        if self._path.exists():
            self._path.unlink()
            self._fsync_parent(self._path)

    def _append_locked(self, events: tuple[ModelRecertificationChangeEvent, ...]) -> None:
        if not events:
            return
        rows = self._rows_for(events)
        payload = "".join(
            _canonical_json(row) + "\n"
            for row in rows
        ).encode("utf-8")
        created = not self._path.exists()
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("model recertification append made no progress")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            self._fsync_parent(self._path)

    def detect_and_record_current(
        self,
        *,
        governance: PersistentModelGovernanceRegistry,
        owner_user_id: str,
        current_passport_ref: str,
        training_jobs: TrainingJobStore,
        proposed_execution_stage: str | None = None,
    ) -> tuple[ModelRecertificationChangeEvent, ...]:
        """Detect all supportable triggers and atomically persist new obligations.

        The transition is resolved twice before the append and once after it.  If
        the backing governance/training state changes, the append is rolled back.
        Exact replay returns the existing events without appending another row.
        """

        first = _detect_transition(
            governance=governance,
            owner_user_id=owner_user_id,
            current_passport_ref=current_passport_ref,
            training_jobs=training_jobs,
            evidence_registry=self._evidence_registry,
            model_registry=self._model_registry,
            proposed_execution_stage=proposed_execution_stage,
        )
        second = _detect_transition(
            governance=governance,
            owner_user_id=owner_user_id,
            current_passport_ref=current_passport_ref,
            training_jobs=training_jobs,
            evidence_registry=self._evidence_registry,
            model_registry=self._model_registry,
            proposed_execution_stage=proposed_execution_stage,
        )
        if first != second:
            raise ModelRecertificationEvidenceError(
                "model recertification evidence changed while detection was evaluated"
            )
        with self._thread_lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_locked()
                locked = _detect_transition(
                    governance=governance,
                    owner_user_id=owner_user_id,
                    current_passport_ref=current_passport_ref,
                    training_jobs=training_jobs,
                    evidence_registry=self._evidence_registry,
                    model_registry=self._model_registry,
                    proposed_execution_stage=proposed_execution_stage,
                )
                if locked != second:
                    raise ModelRecertificationEvidenceError(
                        "model recertification evidence changed before event append"
                    )
                new_events: list[ModelRecertificationChangeEvent] = []
                for event in locked:
                    existing = self._events.get((event.owner_user_id, event.event_ref))
                    if existing is None:
                        new_events.append(event)
                    elif existing != event:
                        raise ModelRecertificationEventError(
                            "model recertification event identity collision"
                        )
                if not new_events:
                    return tuple(
                        self._events[(event.owner_user_id, event.event_ref)]
                        for event in locked
                    )

                original_exists = self._path.exists()
                original = self._path.read_bytes() if original_exists else b""
                try:
                    self._append_locked(tuple(new_events))
                    after = _detect_transition(
                        governance=governance,
                        owner_user_id=owner_user_id,
                        current_passport_ref=current_passport_ref,
                        training_jobs=training_jobs,
                        evidence_registry=self._evidence_registry,
                        model_registry=self._model_registry,
                        proposed_execution_stage=proposed_execution_stage,
                    )
                    if after != locked:
                        raise ModelRecertificationEvidenceError(
                            "model recertification evidence changed while events were committed"
                        )
                    self._load_locked()
                    for event in locked:
                        if self._events.get((event.owner_user_id, event.event_ref)) != event:
                            raise ModelRecertificationEventError(
                                "model recertification event append could not be verified"
                            )
                except Exception:
                    try:
                        self._restore_original(existed=original_exists, payload=original)
                        self._load_locked()
                    except Exception as rollback_exc:  # noqa: BLE001
                        raise ModelRecertificationCommitUncertain(
                            "model recertification event rollback could not be verified"
                        ) from rollback_exc
                    raise
                return tuple(
                    self._events[(event.owner_user_id, event.event_ref)]
                    for event in locked
                )
            finally:
                held.release()
                os.close(fd)

    def event(
        self,
        event_ref: str,
        *,
        owner_user_id: str,
    ) -> ModelRecertificationChangeEvent:
        owner = _required(owner_user_id, "owner_user_id")
        ref = _required(event_ref, "event_ref")
        self._refresh()
        try:
            return self._events[(owner, ref)]
        except KeyError as exc:
            raise KeyError(
                "model recertification event is not recorded for owner"
            ) from exc

    def events_for_passport(
        self,
        passport_ref: str,
        *,
        owner_user_id: str,
    ) -> tuple[ModelRecertificationChangeEvent, ...]:
        owner = _required(owner_user_id, "owner_user_id")
        ref = _required(passport_ref, "passport_ref")
        self._refresh()
        return tuple(
            event
            for event in self._ordered
            if event.owner_user_id == owner and event.after_passport_ref == ref
        )

    def current_record_hash(
        self,
        event_ref: str,
        *,
        owner_user_id: str,
    ) -> str:
        """Return the exact durable row hash for closure snapshot binding."""

        owner = _required(owner_user_id, "owner_user_id")
        ref = _required(event_ref, "event_ref")
        self._refresh()
        try:
            return self._record_hashes[(owner, ref)]
        except KeyError as exc:
            raise KeyError(
                "model recertification event is not recorded for owner"
            ) from exc

    def events_for_model(
        self,
        model_type_card_ref: str,
        *,
        owner_user_id: str,
    ) -> tuple[ModelRecertificationChangeEvent, ...]:
        owner = _required(owner_user_id, "owner_user_id")
        model_ref = _required(model_type_card_ref, "model_type_card_ref")
        self._refresh()
        return tuple(
            event
            for event in self._ordered
            if event.owner_user_id == owner and event.model_type_card_ref == model_ref
        )


def resolve_current_recertification_requirements(
    *,
    governance: PersistentModelGovernanceRegistry,
    event_registry: PersistentModelRecertificationEventRegistry,
    training_jobs: TrainingJobStore,
    owner_user_id: str,
    current_passport_ref: str,
    proposed_execution_stage: str | None = None,
) -> ModelRecertificationResolution:
    """Resolve exact current obligations without trusting passport event fields.

    Automatic passport-transition events come from the durable event registry.
    DATA_SCHEMA_CHANGE remains sourced from the training service's independently
    reproducible schema fingerprints.  The latest owner-scoped review for every
    exact event must be accepted or explicitly waived; a later rejection reopens
    the obligation.  A caller-supplied ``change_events`` argument and
    ``passport.recertification_records`` are intentionally not decision inputs.
    """

    owner = _required(owner_user_id, "owner_user_id")
    passport_ref = _required(current_passport_ref, "current_passport_ref")
    detected_events = event_registry.detect_and_record_current(
        governance=governance,
        owner_user_id=owner,
        current_passport_ref=passport_ref,
        training_jobs=training_jobs,
        proposed_execution_stage=proposed_execution_stage,
    )
    try:
        passport = governance.passport(passport_ref, owner_user_id=owner)
    except KeyError as exc:
        raise ModelRecertificationEvidenceError(
            "current passport is not recorded for owner"
        ) from exc
    owner_passports = governance.passports(owner_user_id=owner)
    indexes = [
        index
        for index, candidate in enumerate(owner_passports)
        if candidate.passport_id == passport.passport_id
    ]
    if len(indexes) != 1:
        raise ModelRecertificationEvidenceError(
            "current passport must occur exactly once in owner history"
        )
    passport_index = indexes[0]

    automatic_events = detected_events
    requirements: list[ModelRecertificationRequirement] = []
    for event in automatic_events:
        if (
            event.owner_user_id != owner
            or event.model_type_card_ref != passport.model_type_card_ref
            or event.after_passport_ref != passport.passport_id
            or event.after_model_version_ref != passport.model_version_ref
        ):
            raise ModelRecertificationEvidenceError(
                "automatic recertification event does not bind the current passport"
            )
        requirements.append(
            ModelRecertificationRequirement(
                trigger=event.trigger,
                change_event_ref=event.event_ref,
                before_passport_ref=event.before_passport_ref,
                after_passport_ref=event.after_passport_ref,
                event_record_hash=event_registry.current_record_hash(
                    event.event_ref,
                    owner_user_id=owner,
                ),
            )
        )

    prior_schema_passport = next(
        (
            candidate
            for candidate in reversed(owner_passports[:passport_index])
            if candidate.model_type_card_ref == passport.model_type_card_ref
            and str(candidate.dataset_schema_fingerprint or "").strip()
        ),
        None,
    )
    current_schema = str(passport.dataset_schema_fingerprint or "").strip()
    if prior_schema_passport is not None and not current_schema:
        raise ModelRecertificationEvidenceError(
            "current passport removed the durable dataset schema fingerprint"
        )
    if (
        prior_schema_passport is not None
        and current_schema
        and prior_schema_passport.dataset_schema_fingerprint != current_schema
    ):
        from ..training.schema_drift import schema_change_event_ref

        requirements.append(
            ModelRecertificationRequirement(
                trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
                change_event_ref=schema_change_event_ref(
                    passport.model_type_card_ref,
                    prior_schema_passport.dataset_schema_fingerprint,
                    current_schema,
                ),
                before_passport_ref=prior_schema_passport.passport_id,
                after_passport_ref=passport.passport_id,
            )
        )

    identities = [
        (requirement.trigger.value, requirement.change_event_ref)
        for requirement in requirements
    ]
    if len(identities) != len(set(identities)):
        raise ModelRecertificationEvidenceError(
            "current recertification requirements contain a duplicate exact event"
        )

    owner_records = governance.recertification_records(owner_user_id=owner)
    resolved: list[ModelRecertificationRecord] = []
    for requirement in requirements:
        exact_history = [
            record
            for record in owner_records
            if _enum_value(record.trigger) == requirement.trigger.value
            and record.change_event_ref == requirement.change_event_ref
        ]
        if not exact_history:
            raise ModelRecertificationEvidenceError(
                "recertification required for "
                f"{requirement.trigger.value} event {requirement.change_event_ref}"
            )
        current = exact_history[-1]
        expected_passport_ref = (
            requirement.before_passport_ref
            if requirement.trigger == RecertificationTrigger.DATA_SCHEMA_CHANGE
            else requirement.after_passport_ref
        )
        try:
            bound_passport = governance.passport(
                current.model_passport_ref,
                owner_user_id=owner,
            )
        except KeyError as exc:
            raise ModelRecertificationEvidenceError(
                "exact recertification review passport binding is missing"
            ) from exc
        if (
            current.model_passport_ref != expected_passport_ref
            or bound_passport.model_type_card_ref != passport.model_type_card_ref
            or current.model_version_ref != bound_passport.model_version_ref
        ):
            raise ModelRecertificationEvidenceError(
                "latest exact recertification review binds the wrong model transition"
            )
        if current.decision not in {"accepted", "waived"}:
            raise ModelRecertificationEvidenceError(
                "latest exact recertification review does not clear "
                f"{requirement.trigger.value} event {requirement.change_event_ref}"
            )
        if not current.evidence_refs:
            raise ModelRecertificationEvidenceError(
                "latest exact recertification review has no evidence refs"
            )
        resolved.append(current)

    return ModelRecertificationResolution(
        passport_ref=passport.passport_id,
        requirements=tuple(requirements),
        automatic_events=automatic_events,
        recertification_records=tuple(resolved),
        producer_statuses=event_registry.producer_statuses(),
    )


__all__ = [
    "ModelChangeState",
    "ModelRecertificationChangeEvent",
    "ModelRecertificationCommitUncertain",
    "ModelRecertificationEventError",
    "ModelRecertificationEvidenceError",
    "ModelRecertificationProducerStatus",
    "ModelRecertificationRequirement",
    "ModelRecertificationResolution",
    "PersistentModelRecertificationEventRegistry",
    "producer_statuses",
    "resolve_current_recertification_requirements",
]
