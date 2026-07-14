"""GOAL §15 model governance promotion contract.

This module does not replace the existing training code or model registry. It
adds a strict promotion gate for the model-governance fields named in GOAL §15:
ValidationDossier, artifact loading safety, challenger evidence for high-risk
models, and recertification after material changes.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash as qbt_content_hash
from .spine import RuntimeStatus


_MODEL_GOVERNANCE_SCHEMA_VERSION = 2
_LEGACY_COMPAT_OWNER = "model_governance"


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _trigger_tuple(value: Any) -> tuple[str, ...]:
    return tuple(_value(v) for v in _tuple(value))


def _stable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _stable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _stable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


class ModelRiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ModelArtifactSource(str, Enum):
    PROJECT_PRODUCED = "project_produced"
    INTERNAL_REGISTRY = "internal_registry"
    VENDOR = "vendor"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class ModelArtifactFormat(str, Enum):
    SAFE_TENSORS = "safe_tensors"
    PICKLE = "pickle"
    JOBLIB = "joblib"
    TORCH = "torch"
    ONNX = "onnx"
    JSON = "json"
    OTHER = "other"


class RecertificationTrigger(str, Enum):
    DATA_SCHEMA_CHANGE = "data_schema_change"
    FEATURE_DISTRIBUTION_DRIFT = "feature_distribution_drift"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    MATERIAL_MODEL_CHANGE = "material_model_change"
    NEW_ASSET_CLASS = "new_asset_class"
    NEW_EXECUTION_ENVIRONMENT = "new_execution_environment"
    DEPENDENCY_UPDATE = "dependency_update"


UNSAFE_SERIALIZED_FORMATS = {
    ModelArtifactFormat.PICKLE.value,
    ModelArtifactFormat.JOBLIB.value,
}


@dataclass(frozen=True)
class ModelGovernanceViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class ModelPromotionDecision:
    accepted: bool
    violations: tuple[ModelGovernanceViolation, ...]


@dataclass(frozen=True)
class SafeLoadingPolicy:
    sandboxed_load_inspect: bool
    prefer_safe_tensors: bool = True
    torch_weights_only: bool | None = None
    direct_load_allowed: bool = False
    policy_ref: str = ""


@dataclass(frozen=True)
class ModelArtifactManifestEntry:
    artifact_ref: str
    uri: str
    artifact_format: ModelArtifactFormat | str = ModelArtifactFormat.OTHER
    source: ModelArtifactSource | str = ModelArtifactSource.PROJECT_PRODUCED
    content_hash: str = ""
    producer_run_ref: str | None = None
    hash_algorithm: str = "sha256"
    direct_load: bool = False
    sandbox_inspection_ref: str | None = None
    artifact_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_ref", _normalized_text(self.artifact_ref))
        object.__setattr__(self, "uri", _normalized_text(self.uri))
        object.__setattr__(self, "content_hash", _normalized_text(self.content_hash))
        object.__setattr__(
            self,
            "producer_run_ref",
            _normalized_text(self.producer_run_ref) or None,
        )
        fmt = _value(self.artifact_format) or _format_from_uri(self.uri)
        if fmt == ModelArtifactFormat.OTHER.value:
            fmt = _format_from_uri(self.uri)
        object.__setattr__(self, "artifact_format", fmt)
        object.__setattr__(self, "source", _value(self.source) or ModelArtifactSource.UNKNOWN.value)
        canonical_id = "model_artifact_" + qbt_content_hash(
            {
                "artifact_ref": self.artifact_ref,
                "uri": self.uri,
                "artifact_format": fmt,
                "source": self.source,
                "content_hash": self.content_hash,
            }
        )
        supplied_id = _normalized_text(self.artifact_id)
        if supplied_id and supplied_id != canonical_id:
            raise ValueError("model artifact identity does not match durable content")
        object.__setattr__(self, "artifact_id", canonical_id)

    @property
    def is_external(self) -> bool:
        return _value(self.source) in {ModelArtifactSource.EXTERNAL.value, ModelArtifactSource.UNKNOWN.value}

    @property
    def is_unsafe_serialized(self) -> bool:
        return _value(self.artifact_format) in UNSAFE_SERIALIZED_FORMATS

    @property
    def is_torch(self) -> bool:
        return _value(self.artifact_format) == ModelArtifactFormat.TORCH.value


@dataclass(frozen=True)
class ModelGovernancePassport:
    model_version_ref: str
    model_type_card_ref: str
    training_plan_ref: str
    training_run_ref: str
    model_risk_tier: ModelRiskTier | str
    materiality: str
    intended_use: tuple[str, ...]
    prohibited_use: tuple[str, ...]
    dataset_refs: tuple[str, ...]
    feature_refs: tuple[str, ...]
    label_refs: tuple[str, ...]
    training_code_hash: str
    artifact_manifest: tuple[ModelArtifactManifestEntry, ...]
    safe_loading_policy: SafeLoadingPolicy
    vendor_dependency_refs: tuple[str, ...]
    foundation_model_dependency_refs: tuple[str, ...]
    monitoring_requirements: tuple[str, ...]
    recertification_triggers: tuple[RecertificationTrigger | str, ...]
    validation_dossier_ref: str | None = None
    challenger_result: str | None = None
    recertification_records: tuple[str, ...] = ()
    # GOAL §15 DATA_SCHEMA_CHANGE producer (C-S15): fingerprint of the training
    # dataset schema (model-consumed feature/label columns + dtypes) this passport
    # was produced from. Additive/optional — does not enter ``passport_id`` (id
    # stays stable) and defaults empty for passports recorded before this field
    # existed. The training service stores it and compares the next run's
    # fingerprint against it to detect a data schema change requiring recert.
    dataset_schema_fingerprint: str = ""
    target_runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE
    passport_id: str = ""
    owner_user_id: str = ""
    recorded_by: str = ""

    def __post_init__(self) -> None:
        for name in (
            "model_version_ref",
            "model_type_card_ref",
            "training_plan_ref",
            "training_run_ref",
            "materiality",
            "training_code_hash",
            "validation_dossier_ref",
            "challenger_result",
            "dataset_schema_fingerprint",
            "owner_user_id",
            "recorded_by",
        ):
            value = _normalized_text(getattr(self, name))
            if name in {"validation_dossier_ref", "challenger_result"}:
                object.__setattr__(self, name, value or None)
            else:
                object.__setattr__(self, name, value)
        for name in (
            "intended_use",
            "prohibited_use",
            "dataset_refs",
            "feature_refs",
            "label_refs",
            "artifact_manifest",
            "vendor_dependency_refs",
            "foundation_model_dependency_refs",
            "monitoring_requirements",
            "recertification_triggers",
            "recertification_records",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        canonical_id = "model_passport_" + qbt_content_hash(
            {
                "model_version_ref": self.model_version_ref,
                "training_run_ref": self.training_run_ref,
                "model_risk_tier": _value(self.model_risk_tier),
                "artifact_manifest": _stable(self.artifact_manifest),
            }
        )
        supplied_id = _normalized_text(self.passport_id)
        if supplied_id and supplied_id != canonical_id:
            raise ValueError("model passport identity does not match durable content")
        object.__setattr__(self, "passport_id", canonical_id)


@dataclass(frozen=True)
class ModelMonitoringProfile:
    model_version_ref: str
    model_passport_ref: str
    metric_refs: tuple[str, ...]
    schedule_ref: str
    alert_policy_ref: str
    drift_signal_refs: tuple[str, ...] = ()
    performance_threshold_refs: tuple[str, ...] = ()
    recertification_trigger_refs: tuple[RecertificationTrigger | str, ...] = ()
    runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE
    owner: str = "model_governance"
    monitoring_profile_id: str = ""
    owner_user_id: str = ""
    recorded_by: str = ""

    def __post_init__(self) -> None:
        for name in (
            "model_version_ref",
            "model_passport_ref",
            "schedule_ref",
            "alert_policy_ref",
            "owner",
            "owner_user_id",
            "recorded_by",
        ):
            object.__setattr__(self, name, _normalized_text(getattr(self, name)))
        for name in (
            "metric_refs",
            "drift_signal_refs",
            "performance_threshold_refs",
            "recertification_trigger_refs",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        canonical_id = "model_monitoring_profile_" + qbt_content_hash(
            {
                "model_version_ref": self.model_version_ref,
                "model_passport_ref": self.model_passport_ref,
                "metric_refs": self.metric_refs,
                "schedule_ref": self.schedule_ref,
                "alert_policy_ref": self.alert_policy_ref,
            }
        )
        supplied_id = _normalized_text(self.monitoring_profile_id)
        if supplied_id and supplied_id != canonical_id:
            raise ValueError("model monitoring profile identity does not match durable content")
        object.__setattr__(self, "monitoring_profile_id", canonical_id)


@dataclass(frozen=True)
class ModelRecertificationRecord:
    model_version_ref: str
    model_passport_ref: str
    trigger: RecertificationTrigger | str
    change_event_ref: str
    evidence_refs: tuple[str, ...]
    decision: str
    recorded_by: str
    recertification_record_id: str = ""
    owner_user_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "model_version_ref",
            "model_passport_ref",
            "change_event_ref",
            "decision",
            "recorded_by",
            "owner_user_id",
        ):
            object.__setattr__(self, name, _normalized_text(getattr(self, name)))
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        canonical_id = "model_recertification_" + qbt_content_hash(
            {
                "model_version_ref": self.model_version_ref,
                "model_passport_ref": self.model_passport_ref,
                "trigger": _value(self.trigger),
                "change_event_ref": self.change_event_ref,
                "evidence_refs": self.evidence_refs,
                "decision": self.decision,
            }
        )
        supplied_id = _normalized_text(self.recertification_record_id)
        if supplied_id and supplied_id != canonical_id:
            raise ValueError("model recertification identity does not match durable content")
        object.__setattr__(self, "recertification_record_id", canonical_id)


@dataclass(frozen=True)
class ModelArtifactInspectionRecord:
    model_version_ref: str
    model_passport_ref: str
    artifact_ref: str
    inspection_ref: str
    artifact_hash: str
    inspection_status: str
    inspection_mode: str
    inspector_ref: str
    checks: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    recorded_by: str = "model_governance"
    artifact_inspection_record_id: str = ""
    owner_user_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "model_version_ref",
            "model_passport_ref",
            "artifact_ref",
            "inspection_ref",
            "artifact_hash",
            "inspection_status",
            "inspection_mode",
            "inspector_ref",
            "recorded_by",
            "owner_user_id",
        ):
            object.__setattr__(self, name, _normalized_text(getattr(self, name)))
        for name in ("checks", "limitations"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        canonical_id = "model_artifact_inspection_" + qbt_content_hash(
            {
                "model_version_ref": self.model_version_ref,
                "model_passport_ref": self.model_passport_ref,
                "artifact_ref": self.artifact_ref,
                "inspection_ref": self.inspection_ref,
                "artifact_hash": self.artifact_hash,
                "inspection_status": self.inspection_status,
                "inspection_mode": self.inspection_mode,
            }
        )
        supplied_id = _normalized_text(self.artifact_inspection_record_id)
        if supplied_id and supplied_id != canonical_id:
            raise ValueError("model artifact inspection identity does not match durable content")
        object.__setattr__(self, "artifact_inspection_record_id", canonical_id)


@dataclass(frozen=True)
class ModelServingInvocationRecord:
    model_version_ref: str
    model_passport_ref: str
    artifact_inspection_ref: str
    monitoring_profile_ref: str
    feature_refs: tuple[str, ...]
    row_count: int
    request_hash: str
    prediction_hash: str
    runtime: RuntimeStatus | str
    recorded_by: str
    serving_invocation_id: str = ""
    owner_user_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "model_version_ref",
            "model_passport_ref",
            "artifact_inspection_ref",
            "monitoring_profile_ref",
            "request_hash",
            "prediction_hash",
            "recorded_by",
            "owner_user_id",
        ):
            object.__setattr__(self, name, _normalized_text(getattr(self, name)))
        object.__setattr__(self, "feature_refs", _tuple(self.feature_refs))
        canonical_id = "model_serving_invocation_" + qbt_content_hash(
            {
                "model_version_ref": self.model_version_ref,
                "model_passport_ref": self.model_passport_ref,
                "artifact_inspection_ref": self.artifact_inspection_ref,
                "monitoring_profile_ref": self.monitoring_profile_ref,
                "row_count": self.row_count,
                "request_hash": self.request_hash,
                "prediction_hash": self.prediction_hash,
                "runtime": _value(self.runtime),
            }
        )
        supplied_id = _normalized_text(self.serving_invocation_id)
        if supplied_id and supplied_id != canonical_id:
            raise ValueError("model serving invocation identity does not match durable content")
        object.__setattr__(self, "serving_invocation_id", canonical_id)


def model_passport_from_dict(raw: dict[str, Any]) -> ModelGovernancePassport:
    artifacts = tuple(
        entry
        if isinstance(entry, ModelArtifactManifestEntry)
        else ModelArtifactManifestEntry(**entry)
        for entry in _tuple(raw.get("artifact_manifest"))
    )
    safe_loading_raw = raw.get("safe_loading_policy")
    if isinstance(safe_loading_raw, SafeLoadingPolicy):
        safe_loading_policy = safe_loading_raw
    elif isinstance(safe_loading_raw, dict):
        safe_loading_policy = SafeLoadingPolicy(**safe_loading_raw)
    else:
        safe_loading_policy = SafeLoadingPolicy(sandboxed_load_inspect=False)
    return ModelGovernancePassport(
        model_version_ref=str(raw.get("model_version_ref") or ""),
        model_type_card_ref=str(raw.get("model_type_card_ref") or ""),
        training_plan_ref=str(raw.get("training_plan_ref") or ""),
        training_run_ref=str(raw.get("training_run_ref") or ""),
        model_risk_tier=raw.get("model_risk_tier") or ModelRiskTier.LOW.value,
        materiality=str(raw.get("materiality") or ""),
        intended_use=_tuple(raw.get("intended_use")),
        prohibited_use=_tuple(raw.get("prohibited_use")),
        dataset_refs=_tuple(raw.get("dataset_refs")),
        feature_refs=_tuple(raw.get("feature_refs")),
        label_refs=_tuple(raw.get("label_refs")),
        training_code_hash=str(raw.get("training_code_hash") or ""),
        artifact_manifest=artifacts,
        safe_loading_policy=safe_loading_policy,
        vendor_dependency_refs=_tuple(raw.get("vendor_dependency_refs")),
        foundation_model_dependency_refs=_tuple(raw.get("foundation_model_dependency_refs")),
        monitoring_requirements=_tuple(raw.get("monitoring_requirements")),
        recertification_triggers=_tuple(raw.get("recertification_triggers")),
        validation_dossier_ref=raw.get("validation_dossier_ref"),
        challenger_result=raw.get("challenger_result"),
        recertification_records=_tuple(raw.get("recertification_records")),
        dataset_schema_fingerprint=str(raw.get("dataset_schema_fingerprint") or ""),
        target_runtime=raw.get("target_runtime") or RuntimeStatus.OFFLINE.value,
        passport_id=str(raw.get("passport_id") or ""),
        owner_user_id=str(raw.get("owner_user_id") or ""),
        recorded_by=str(raw.get("recorded_by") or ""),
    )


def monitoring_profile_from_dict(raw: dict[str, Any]) -> ModelMonitoringProfile:
    return ModelMonitoringProfile(
        model_version_ref=str(raw.get("model_version_ref") or ""),
        model_passport_ref=str(raw.get("model_passport_ref") or ""),
        metric_refs=_tuple(raw.get("metric_refs")),
        schedule_ref=str(raw.get("schedule_ref") or ""),
        alert_policy_ref=str(raw.get("alert_policy_ref") or ""),
        drift_signal_refs=_tuple(raw.get("drift_signal_refs")),
        performance_threshold_refs=_tuple(raw.get("performance_threshold_refs")),
        recertification_trigger_refs=_tuple(raw.get("recertification_trigger_refs")),
        runtime=raw.get("runtime") or RuntimeStatus.OFFLINE.value,
        owner=str(raw.get("owner") or "model_governance"),
        monitoring_profile_id=str(raw.get("monitoring_profile_id") or ""),
        owner_user_id=str(raw.get("owner_user_id") or ""),
        recorded_by=str(raw.get("recorded_by") or ""),
    )


def recertification_record_from_dict(raw: dict[str, Any]) -> ModelRecertificationRecord:
    return ModelRecertificationRecord(
        model_version_ref=str(raw.get("model_version_ref") or ""),
        model_passport_ref=str(raw.get("model_passport_ref") or ""),
        trigger=raw.get("trigger") or "",
        change_event_ref=str(raw.get("change_event_ref") or ""),
        evidence_refs=_tuple(raw.get("evidence_refs")),
        decision=str(raw.get("decision") or ""),
        recorded_by=str(raw.get("recorded_by") or ""),
        recertification_record_id=str(raw.get("recertification_record_id") or ""),
        owner_user_id=str(raw.get("owner_user_id") or ""),
    )


def artifact_inspection_record_from_dict(raw: dict[str, Any]) -> ModelArtifactInspectionRecord:
    return ModelArtifactInspectionRecord(
        model_version_ref=str(raw.get("model_version_ref") or ""),
        model_passport_ref=str(raw.get("model_passport_ref") or ""),
        artifact_ref=str(raw.get("artifact_ref") or ""),
        inspection_ref=str(raw.get("inspection_ref") or ""),
        artifact_hash=str(raw.get("artifact_hash") or ""),
        inspection_status=str(raw.get("inspection_status") or ""),
        inspection_mode=str(raw.get("inspection_mode") or ""),
        inspector_ref=str(raw.get("inspector_ref") or ""),
        checks=_tuple(raw.get("checks")),
        limitations=_tuple(raw.get("limitations")),
        recorded_by=str(raw.get("recorded_by") or "model_governance"),
        artifact_inspection_record_id=str(raw.get("artifact_inspection_record_id") or ""),
        owner_user_id=str(raw.get("owner_user_id") or ""),
    )


def serving_invocation_record_from_dict(raw: dict[str, Any]) -> ModelServingInvocationRecord:
    return ModelServingInvocationRecord(
        model_version_ref=str(raw.get("model_version_ref") or ""),
        model_passport_ref=str(raw.get("model_passport_ref") or ""),
        artifact_inspection_ref=str(raw.get("artifact_inspection_ref") or ""),
        monitoring_profile_ref=str(raw.get("monitoring_profile_ref") or ""),
        feature_refs=_tuple(raw.get("feature_refs")),
        row_count=int(raw.get("row_count") or 0),
        request_hash=str(raw.get("request_hash") or ""),
        prediction_hash=str(raw.get("prediction_hash") or ""),
        runtime=raw.get("runtime") or RuntimeStatus.OFFLINE.value,
        recorded_by=str(raw.get("recorded_by") or ""),
        serving_invocation_id=str(raw.get("serving_invocation_id") or ""),
        owner_user_id=str(raw.get("owner_user_id") or ""),
    )


def _format_from_uri(uri: str) -> str:
    suffix = PurePosixPath(str(uri or "")).suffix.lower()
    if suffix in {".safetensors"}:
        return ModelArtifactFormat.SAFE_TENSORS.value
    if suffix in {".pkl", ".pickle"}:
        return ModelArtifactFormat.PICKLE.value
    if suffix in {".joblib"}:
        return ModelArtifactFormat.JOBLIB.value
    if suffix in {".pt", ".pth"}:
        return ModelArtifactFormat.TORCH.value
    if suffix in {".onnx"}:
        return ModelArtifactFormat.ONNX.value
    if suffix in {".json"}:
        return ModelArtifactFormat.JSON.value
    return ModelArtifactFormat.OTHER.value


def validate_model_promotion(
    passport: ModelGovernancePassport,
    *,
    change_events: tuple[RecertificationTrigger | str, ...] = (),
) -> ModelPromotionDecision:
    violations: list[ModelGovernanceViolation] = []

    def missing_text(field_name: str, value: str | None) -> None:
        if not str(value or "").strip():
            violations.append(
                ModelGovernanceViolation(
                    f"missing_{field_name}",
                    f"{field_name} is required for model promotion",
                    field=field_name,
                    ref=passport.model_version_ref,
                )
            )

    def missing_list(field_name: str, value: tuple[Any, ...]) -> None:
        if not value:
            violations.append(
                ModelGovernanceViolation(
                    f"missing_{field_name}",
                    f"{field_name} is required for model promotion",
                    field=field_name,
                    ref=passport.model_version_ref,
                )
            )

    missing_text("model_version_ref", passport.model_version_ref)
    missing_text("model_type_card_ref", passport.model_type_card_ref)
    missing_text("training_plan_ref", passport.training_plan_ref)
    missing_text("training_run_ref", passport.training_run_ref)
    missing_text("materiality", passport.materiality)
    missing_text("training_code_hash", passport.training_code_hash)
    missing_text("validation_dossier_ref", passport.validation_dossier_ref)
    missing_list("intended_use", passport.intended_use)
    missing_list("prohibited_use", passport.prohibited_use)
    missing_list("dataset_refs", passport.dataset_refs)
    missing_list("feature_refs", passport.feature_refs)
    missing_list("label_refs", passport.label_refs)
    missing_list("artifact_manifest", passport.artifact_manifest)
    missing_list("vendor_dependency_refs", passport.vendor_dependency_refs)
    missing_list("foundation_model_dependency_refs", passport.foundation_model_dependency_refs)
    missing_list("monitoring_requirements", passport.monitoring_requirements)
    missing_list("recertification_triggers", passport.recertification_triggers)

    if not passport.safe_loading_policy.sandboxed_load_inspect:
        violations.append(
            ModelGovernanceViolation(
                "missing_sandboxed_load_inspect",
                "model artifact loading must use sandboxed load or inspection",
                field="safe_loading_policy",
                ref=passport.model_version_ref,
            )
        )

    if _value(passport.model_risk_tier) in {ModelRiskTier.HIGH.value, ModelRiskTier.CRITICAL.value}:
        missing_text("challenger_result", passport.challenger_result)

    for artifact in passport.artifact_manifest:
        _validate_artifact(passport, artifact, violations)

    _validate_recertification(passport, _tuple(change_events), violations)

    return ModelPromotionDecision(accepted=not violations, violations=tuple(violations))


def _validate_artifact(
    passport: ModelGovernancePassport,
    artifact: ModelArtifactManifestEntry,
    violations: list[ModelGovernanceViolation],
) -> None:
    if not str(artifact.content_hash or "").strip():
        violations.append(
            ModelGovernanceViolation(
                "missing_artifact_hash",
                "model artifact must bind a content hash",
                field="artifact_manifest.content_hash",
                ref=artifact.artifact_ref,
            )
        )
    if not str(artifact.producer_run_ref or "").strip():
        violations.append(
            ModelGovernanceViolation(
                "missing_producer_run_ref",
                "model artifact must bind the producer training run",
                field="artifact_manifest.producer_run_ref",
                ref=artifact.artifact_ref,
            )
        )
    if passport.safe_loading_policy.sandboxed_load_inspect and not str(
        artifact.sandbox_inspection_ref or ""
    ).strip():
        violations.append(
            ModelGovernanceViolation(
                "missing_sandbox_inspection_ref",
                "model artifact must bind a sandbox inspection ref",
                field="artifact_manifest.sandbox_inspection_ref",
                ref=artifact.artifact_ref,
            )
        )

    if artifact.is_external and artifact.is_unsafe_serialized:
        violations.append(
            ModelGovernanceViolation(
                "external_serialized_artifact_blocked",
                "external pickle/joblib artifacts are blocked for promotion",
                field="artifact_manifest",
                ref=artifact.artifact_ref,
            )
        )
        if artifact.direct_load:
            violations.append(
                ModelGovernanceViolation(
                    "external_pickle_direct_load",
                    "external pickle/joblib artifacts cannot be directly loaded",
                    field="artifact_manifest.direct_load",
                    ref=artifact.artifact_ref,
                )
            )

    if artifact.is_unsafe_serialized and (artifact.direct_load or passport.safe_loading_policy.direct_load_allowed):
        violations.append(
            ModelGovernanceViolation(
                "unsafe_serialized_direct_load",
                "pickle/joblib artifacts require governed inspection, not direct load",
                field="safe_loading_policy.direct_load_allowed",
                ref=artifact.artifact_ref,
            )
        )

    if artifact.is_torch and passport.safe_loading_policy.torch_weights_only is not True:
        violations.append(
            ModelGovernanceViolation(
                "torch_weights_only_required",
                "torch artifacts require weights_only=True policy",
                field="safe_loading_policy.torch_weights_only",
                ref=artifact.artifact_ref,
            )
        )


def _validate_recertification(
    passport: ModelGovernancePassport,
    change_events: tuple[Any, ...],
    violations: list[ModelGovernanceViolation],
) -> None:
    if not change_events:
        return

    declared = {_value(trigger) for trigger in passport.recertification_triggers}
    records = passport.recertification_records
    for event in {_value(trigger) for trigger in change_events}:
        if event not in declared:
            violations.append(
                ModelGovernanceViolation(
                    "recertification_trigger_not_declared",
                    f"{event} must be declared as a recertification trigger",
                    field="recertification_triggers",
                    ref=passport.model_version_ref,
                )
            )
        if not records:
            code = (
                "material_model_change_without_recertification"
                if event == RecertificationTrigger.MATERIAL_MODEL_CHANGE.value
                else "missing_recertification_record"
            )
            violations.append(
                ModelGovernanceViolation(
                    code,
                    f"{event} requires a recertification record before promotion",
                    field="recertification_records",
                    ref=passport.model_version_ref,
                )
            )


def _decision_message(decision: ModelPromotionDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "model governance record rejected"


class PersistentModelGovernanceRegistry:
    """Append-only, owner-scoped governance event ledger.

    Schema-v1 history had no trustworthy owner envelope, so it is counted as
    quarantined and never participates in schema-v2 lookups. Every mutable
    logical ref advances an immutable hash-linked head. A differing replacement
    must present the exact current head hash; exact replay remains idempotent.
    """

    _EVENT_SPECS = {
        "model_passport_recorded": ("passport", model_passport_from_dict, "passport_id"),
        "model_monitoring_profile_recorded": (
            "monitoring_profile",
            monitoring_profile_from_dict,
            "monitoring_profile_id",
        ),
        "model_recertification_recorded": (
            "recertification_record",
            recertification_record_from_dict,
            "recertification_record_id",
        ),
        "model_artifact_inspection_recorded": (
            "artifact_inspection",
            artifact_inspection_record_from_dict,
            "artifact_inspection_record_id",
        ),
        "model_serving_invocation_recorded": (
            "serving_invocation",
            serving_invocation_record_from_dict,
            "serving_invocation_id",
        ),
    }

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._reset_state()
        self._refresh()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @staticmethod
    def _required(value: Any, field_name: str) -> str:
        normalized = _normalized_text(value)
        if not normalized:
            raise ValueError(f"model governance {field_name} is required")
        return normalized

    def _reset_state(self) -> None:
        self._passports: dict[tuple[str, str], ModelGovernancePassport] = {}
        self._change_events: dict[tuple[str, str], tuple[str, ...]] = {}
        self._monitoring_profiles: dict[tuple[str, str], ModelMonitoringProfile] = {}
        self._recertification_records: dict[tuple[str, str], ModelRecertificationRecord] = {}
        self._artifact_inspections: dict[tuple[str, str], ModelArtifactInspectionRecord] = {}
        self._serving_invocations: dict[tuple[str, str], ModelServingInvocationRecord] = {}
        self._heads: dict[tuple[str, str, str], tuple[int, str]] = {}
        self._current_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._row_order: dict[tuple[str, str, str], int] = {}
        self._event_sequence = 0
        self._legacy_quarantined_count = 0

    def _acquire_file_lock(self) -> tuple[int, Any]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
        except Exception:
            os.close(fd)
            raise
        return fd, held

    def _refresh(self) -> None:
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_existing()
            finally:
                held.release()
                os.close(fd)

    def _load_existing(self) -> None:
        self._reset_state()
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    schema_version = row.get("schema_version")
                    if schema_version == 1:
                        self._legacy_quarantined_count += 1
                        continue
                    if schema_version != _MODEL_GOVERNANCE_SCHEMA_VERSION:
                        raise ValueError(
                            f"unsupported model governance schema_version={schema_version!r}"
                        )
                    self._apply_row(row)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"invalid persisted model governance row at {self._path}:{line_no}"
                    ) from exc

    @staticmethod
    def _head_hash(row: dict[str, Any]) -> str:
        material = dict(row)
        material.pop("head_hash", None)
        return "model_governance_head_" + qbt_content_hash(material)

    @staticmethod
    def _material(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in row.items()
            if key not in {"revision", "previous_head_hash", "head_hash"}
        }

    def _normalize_record_actors(
        self,
        record: Any,
        *,
        owner_user_id: str | None,
        recorded_by: str | None,
    ) -> tuple[Any, str, str]:
        embedded_owner = _normalized_text(getattr(record, "owner_user_id", ""))
        explicit_owner = _normalized_text(owner_user_id)
        if explicit_owner and embedded_owner and explicit_owner != embedded_owner:
            raise ValueError("model governance caller owner_user_id does not match record owner_user_id")
        owner = explicit_owner or embedded_owner or _LEGACY_COMPAT_OWNER

        embedded_actor = _normalized_text(getattr(record, "recorded_by", ""))
        explicit_actor = _normalized_text(recorded_by)
        if explicit_actor and embedded_actor and explicit_actor != embedded_actor:
            raise ValueError("model governance caller recorded_by does not match record recorded_by")
        actor = explicit_actor or embedded_actor or owner
        return replace(record, owner_user_id=owner, recorded_by=actor), owner, actor

    def _parse_row_record(self, row: dict[str, Any]) -> tuple[str, str, str, Any, str]:
        event_type = _normalized_text(row.get("event_type"))
        try:
            payload_key, parser, ref_field = self._EVENT_SPECS[event_type]
        except KeyError as exc:
            raise ValueError(f"unknown model governance event_type={event_type!r}") from exc
        owner = self._required(row.get("owner_user_id"), "owner_user_id")
        actor = self._required(row.get("recorded_by"), "recorded_by")
        raw = row.get(payload_key)
        if not isinstance(raw, dict):
            raise ValueError(f"model governance event missing {payload_key}")
        record = parser(raw)
        record, _, _ = self._normalize_record_actors(
            record,
            owner_user_id=owner,
            recorded_by=actor,
        )
        record_ref = self._required(getattr(record, ref_field, ""), ref_field)
        return event_type, owner, actor, record, record_ref

    def _apply_row(self, row: dict[str, Any]) -> Any:
        if row.get("schema_version") != _MODEL_GOVERNANCE_SCHEMA_VERSION:
            raise ValueError("model governance owner envelope schema_version=2 is required")
        event_type, owner, _actor, record, record_ref = self._parse_row_record(row)
        revision = row.get("revision")
        if type(revision) is not int or revision <= 0:
            raise ValueError("model governance revision must be a positive integer")
        previous_head_hash = _normalized_text(row.get("previous_head_hash"))
        head_hash = self._required(row.get("head_hash"), "head_hash")
        if head_hash != self._head_hash(row):
            raise ValueError("model governance head hash does not match event content")

        head_key = (owner, event_type, record_ref)
        current = self._heads.get(head_key)
        if current is not None and revision == current[0] and head_hash == current[1]:
            if self._current_rows[head_key] != row:
                raise ValueError("model governance duplicate head collision")
            return self._record_for_event(event_type, owner, record_ref)
        expected_revision = 1 if current is None else current[0] + 1
        expected_previous = "" if current is None else current[1]
        if revision != expected_revision or previous_head_hash != expected_previous:
            raise ValueError("model governance revision chain is stale or forked")

        extras = {"change_events": _trigger_tuple(row.get("change_events"))}
        self._validate_record(event_type, owner, record, extras=extras)
        key = (owner, record_ref)
        if event_type == "model_passport_recorded":
            self._passports[key] = record
            self._change_events[key] = extras["change_events"]
        elif event_type == "model_monitoring_profile_recorded":
            self._monitoring_profiles[key] = record
        elif event_type == "model_recertification_recorded":
            self._recertification_records[key] = record
        elif event_type == "model_artifact_inspection_recorded":
            self._artifact_inspections[key] = record
        elif event_type == "model_serving_invocation_recorded":
            self._serving_invocations[key] = record
        self._heads[head_key] = (revision, head_hash)
        self._current_rows[head_key] = row
        self._event_sequence += 1
        self._row_order[head_key] = self._event_sequence
        return record

    def _record_for_event(self, event_type: str, owner: str, record_ref: str) -> Any:
        stores = {
            "model_passport_recorded": self._passports,
            "model_monitoring_profile_recorded": self._monitoring_profiles,
            "model_recertification_recorded": self._recertification_records,
            "model_artifact_inspection_recorded": self._artifact_inspections,
            "model_serving_invocation_recorded": self._serving_invocations,
        }
        return stores[event_type][(owner, record_ref)]

    def _matching_passport(
        self,
        model_passport_ref: str,
        model_version_ref: str,
        *,
        owner_user_id: str,
    ) -> ModelGovernancePassport:
        passport_ref = self._required(model_passport_ref, "model_passport_ref")
        try:
            passport = self._passports[(owner_user_id, passport_ref)]
        except KeyError as exc:
            raise ValueError(f"model_passport_ref not recorded for owner: {passport_ref}") from exc
        if passport.model_version_ref != model_version_ref:
            raise ValueError(
                "model_passport_ref does not match model_version_ref: "
                f"{passport.model_version_ref!r} != {model_version_ref!r}"
            )
        return passport

    def _validate_record(
        self,
        event_type: str,
        owner: str,
        record: Any,
        *,
        extras: dict[str, Any],
    ) -> None:
        if record.owner_user_id != owner:
            raise ValueError("model governance record owner does not match event owner")
        if not _normalized_text(record.recorded_by):
            raise ValueError("model governance record requires recorded_by")
        if event_type == "model_passport_recorded":
            decision = validate_model_promotion(
                record,
                change_events=_trigger_tuple(extras.get("change_events")),
            )
            if not decision.accepted:
                raise ValueError(_decision_message(decision))
            return

        passport = self._matching_passport(
            record.model_passport_ref,
            record.model_version_ref,
            owner_user_id=owner,
        )
        if event_type == "model_monitoring_profile_recorded":
            if not record.metric_refs:
                raise ValueError("monitoring profile requires metric_refs")
            if not record.schedule_ref:
                raise ValueError("monitoring profile requires schedule_ref")
            if not record.alert_policy_ref:
                raise ValueError("monitoring profile requires alert_policy_ref")
            declared = {_value(trigger) for trigger in passport.recertification_triggers}
            for trigger in record.recertification_trigger_refs:
                if _value(trigger) not in declared:
                    raise ValueError(
                        f"monitoring profile trigger not declared on passport: {_value(trigger)}"
                    )
            return
        if event_type == "model_recertification_recorded":
            trigger = _value(record.trigger)
            if trigger not in {_value(value) for value in passport.recertification_triggers}:
                raise ValueError(f"recertification trigger not declared on passport: {trigger}")
            if not record.change_event_ref:
                raise ValueError("recertification record requires change_event_ref")
            if not record.evidence_refs:
                raise ValueError("recertification record requires evidence_refs")
            if record.decision not in {"accepted", "rejected", "waived"}:
                raise ValueError("recertification decision must be accepted, rejected, or waived")
            return
        if event_type == "model_artifact_inspection_recorded":
            artifact = next(
                (
                    candidate
                    for candidate in passport.artifact_manifest
                    if candidate.artifact_ref == record.artifact_ref
                ),
                None,
            )
            if artifact is None:
                raise ValueError(f"artifact_ref not recorded on passport: {record.artifact_ref}")
            if not record.inspection_ref:
                raise ValueError("artifact inspection requires inspection_ref")
            if artifact.sandbox_inspection_ref and artifact.sandbox_inspection_ref != record.inspection_ref:
                raise ValueError(
                    "artifact inspection_ref does not match passport sandbox_inspection_ref: "
                    f"{artifact.sandbox_inspection_ref!r} != {record.inspection_ref!r}"
                )
            if artifact.content_hash != record.artifact_hash:
                raise ValueError(
                    "artifact inspection hash does not match passport artifact hash: "
                    f"{artifact.content_hash!r} != {record.artifact_hash!r}"
                )
            if record.inspection_status not in {"accepted", "rejected"}:
                raise ValueError("artifact inspection status must be accepted or rejected")
            if not record.inspection_mode:
                raise ValueError("artifact inspection requires inspection_mode")
            if not record.inspector_ref:
                raise ValueError("artifact inspection requires inspector_ref")
            if not record.checks:
                raise ValueError("artifact inspection requires checks")
            if artifact.is_external and artifact.is_unsafe_serialized and record.inspection_status == "accepted":
                raise ValueError("external pickle/joblib artifact inspection cannot be accepted")
            if artifact.is_unsafe_serialized and record.inspection_mode != "metadata_only_no_deserialize":
                raise ValueError(
                    "pickle/joblib artifact inspection must use metadata_only_no_deserialize mode"
                )
            return
        if event_type == "model_serving_invocation_recorded":
            if _value(record.runtime) not in {RuntimeStatus.LIVE.value, "staging", "production"}:
                raise ValueError("model serving invocation runtime must be staging or production/live")
            if not record.feature_refs:
                raise ValueError("model serving invocation requires feature_refs")
            if record.row_count <= 0:
                raise ValueError("model serving invocation requires row_count > 0")
            if not record.request_hash:
                raise ValueError("model serving invocation requires request_hash")
            if not record.prediction_hash:
                raise ValueError("model serving invocation requires prediction_hash")
            inspection = self._latest_artifact_inspection(
                owner,
                passport_ref=record.model_passport_ref,
                inspection_ref=record.artifact_inspection_ref,
            )
            if inspection is None or inspection.inspection_status != "accepted":
                raise ValueError("model serving invocation requires current accepted artifact_inspection_ref")
            profile = self._monitoring_profiles.get((owner, record.monitoring_profile_ref))
            if profile is None or profile.model_passport_ref != record.model_passport_ref:
                raise ValueError("model serving invocation requires matching monitoring_profile_ref")

    def _write_record(
        self,
        event_type: str,
        record: Any,
        *,
        owner_user_id: str | None,
        recorded_by: str | None,
        expected_head_hash: str | None,
        extras: dict[str, Any] | None = None,
    ) -> Any:
        normalized, owner, actor = self._normalize_record_actors(
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
        )
        payload_key, _parser, ref_field = self._EVENT_SPECS[event_type]
        record_ref = self._required(getattr(normalized, ref_field, ""), ref_field)
        extras = dict(extras or {})
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_existing()
                self._validate_record(event_type, owner, normalized, extras=extras)
                material = {
                    "schema_version": _MODEL_GOVERNANCE_SCHEMA_VERSION,
                    "event_type": event_type,
                    "owner_user_id": owner,
                    "recorded_by": actor,
                    payload_key: _stable(normalized),
                    **extras,
                }
                head_key = (owner, event_type, record_ref)
                current_row = self._current_rows.get(head_key)
                expected = _normalized_text(expected_head_hash)
                if current_row is not None:
                    current_hash = current_row["head_hash"]
                    if expected and expected != current_hash:
                        raise ValueError("model governance expected_head_hash is stale")
                    if self._material(current_row) == material:
                        return self._record_for_event(event_type, owner, record_ref)
                    if not expected:
                        raise ValueError(
                            "model governance differing replacement requires expected_head_hash"
                        )
                    revision = int(current_row["revision"]) + 1
                    previous_head_hash = current_hash
                else:
                    if expected:
                        raise ValueError("model governance expected_head_hash is stale")
                    revision = 1
                    previous_head_hash = ""
                row = {
                    **material,
                    "revision": revision,
                    "previous_head_hash": previous_head_hash,
                }
                row["head_hash"] = self._head_hash(row)
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
                return self._apply_row(row)
            finally:
                held.release()
                os.close(fd)

    def record_passport(
        self,
        passport: ModelGovernancePassport,
        *,
        change_events: tuple[RecertificationTrigger | str, ...] = (),
        owner_user_id: str | None = None,
        recorded_by: str | None = None,
        expected_head_hash: str | None = None,
    ) -> ModelGovernancePassport:
        return self._write_record(
            "model_passport_recorded",
            passport,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            expected_head_hash=expected_head_hash,
            extras={"change_events": list(_trigger_tuple(change_events))},
        )

    def record_monitoring_profile(
        self,
        profile: ModelMonitoringProfile,
        *,
        owner_user_id: str | None = None,
        recorded_by: str | None = None,
        expected_head_hash: str | None = None,
    ) -> ModelMonitoringProfile:
        return self._write_record(
            "model_monitoring_profile_recorded",
            profile,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            expected_head_hash=expected_head_hash,
        )

    def record_recertification_record(
        self,
        record: ModelRecertificationRecord,
        *,
        owner_user_id: str | None = None,
        recorded_by: str | None = None,
        expected_head_hash: str | None = None,
    ) -> ModelRecertificationRecord:
        return self._write_record(
            "model_recertification_recorded",
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            expected_head_hash=expected_head_hash,
        )

    def record_artifact_inspection(
        self,
        record: ModelArtifactInspectionRecord,
        *,
        owner_user_id: str | None = None,
        recorded_by: str | None = None,
        expected_head_hash: str | None = None,
    ) -> ModelArtifactInspectionRecord:
        return self._write_record(
            "model_artifact_inspection_recorded",
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            expected_head_hash=expected_head_hash,
        )

    def record_serving_invocation(
        self,
        record: ModelServingInvocationRecord,
        *,
        owner_user_id: str | None = None,
        recorded_by: str | None = None,
        expected_head_hash: str | None = None,
    ) -> ModelServingInvocationRecord:
        return self._write_record(
            "model_serving_invocation_recorded",
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            expected_head_hash=expected_head_hash,
        )

    def _owner_for_mapping(
        self,
        mapping: dict[tuple[str, str], Any],
        owner_user_id: str | None,
    ) -> str | None:
        explicit = _normalized_text(owner_user_id)
        if explicit:
            return explicit
        owners = {owner for owner, _ref in self._passports}
        owners.update(owner for owner, _ref in mapping)
        if len(owners) > 1:
            raise ValueError("model governance owner_user_id is required for an ambiguous lookup")
        return next(iter(owners), None)

    def _get(
        self,
        mapping: dict[tuple[str, str], Any],
        record_ref: str,
        *,
        owner_user_id: str | None,
    ) -> Any:
        self._refresh()
        owner = self._owner_for_mapping(mapping, owner_user_id)
        if owner is None:
            raise KeyError(record_ref)
        return mapping[(owner, str(record_ref))]

    def _all(
        self,
        mapping: dict[tuple[str, str], Any],
        *,
        owner_user_id: str | None,
    ) -> list[Any]:
        self._refresh()
        owner = self._owner_for_mapping(mapping, owner_user_id)
        if owner is None:
            return []
        return [record for (record_owner, _ref), record in mapping.items() if record_owner == owner]

    def passport(
        self,
        passport_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> ModelGovernancePassport:
        return self._get(self._passports, passport_id, owner_user_id=owner_user_id)

    def passports(self, *, owner_user_id: str | None = None) -> list[ModelGovernancePassport]:
        return self._all(self._passports, owner_user_id=owner_user_id)

    def change_events(
        self,
        passport_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> tuple[str, ...]:
        return self._get(self._change_events, passport_id, owner_user_id=owner_user_id)

    def monitoring_profile(
        self,
        profile_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> ModelMonitoringProfile:
        return self._get(self._monitoring_profiles, profile_id, owner_user_id=owner_user_id)

    def monitoring_profiles(
        self,
        *,
        owner_user_id: str | None = None,
    ) -> list[ModelMonitoringProfile]:
        return self._all(self._monitoring_profiles, owner_user_id=owner_user_id)

    def recertification_record(
        self,
        record_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> ModelRecertificationRecord:
        return self._get(self._recertification_records, record_id, owner_user_id=owner_user_id)

    def recertification_records(
        self,
        *,
        owner_user_id: str | None = None,
    ) -> list[ModelRecertificationRecord]:
        return self._all(self._recertification_records, owner_user_id=owner_user_id)

    def artifact_inspection(
        self,
        record_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> ModelArtifactInspectionRecord:
        return self._get(self._artifact_inspections, record_id, owner_user_id=owner_user_id)

    def artifact_inspections(
        self,
        *,
        owner_user_id: str | None = None,
    ) -> list[ModelArtifactInspectionRecord]:
        return self._all(self._artifact_inspections, owner_user_id=owner_user_id)

    def serving_invocation(
        self,
        record_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> ModelServingInvocationRecord:
        return self._get(self._serving_invocations, record_id, owner_user_id=owner_user_id)

    def serving_invocations(
        self,
        *,
        owner_user_id: str | None = None,
    ) -> list[ModelServingInvocationRecord]:
        return self._all(self._serving_invocations, owner_user_id=owner_user_id)

    def current_head_hash(
        self,
        record_ref: str,
        *,
        owner_user_id: str | None = None,
        event_type: str | None = None,
    ) -> str:
        self._refresh()
        explicit_owner = _normalized_text(owner_user_id)
        matches = [
            (key, head)
            for key, head in self._heads.items()
            if key[2] == str(record_ref)
            and (not explicit_owner or key[0] == explicit_owner)
            and (not event_type or key[1] == event_type)
        ]
        if not matches:
            raise KeyError(record_ref)
        if len(matches) != 1:
            raise ValueError("model governance owner_user_id and event_type are required for an ambiguous head")
        return matches[0][1][1]

    def is_current_head(
        self,
        record_ref: str,
        head_hash: str,
        *,
        owner_user_id: str,
        event_type: str | None = None,
    ) -> bool:
        try:
            return self.current_head_hash(
                record_ref,
                owner_user_id=owner_user_id,
                event_type=event_type,
            ) == _normalized_text(head_hash)
        except (KeyError, ValueError):
            return False

    def _latest_artifact_inspection(
        self,
        owner: str,
        *,
        passport_ref: str,
        inspection_ref: str,
        artifact_ref: str | None = None,
    ) -> ModelArtifactInspectionRecord | None:
        matches = [
            (self._row_order[(owner, "model_artifact_inspection_recorded", record_ref)], record)
            for (record_owner, record_ref), record in self._artifact_inspections.items()
            if record_owner == owner
            and record.model_passport_ref == passport_ref
            and record.inspection_ref == inspection_ref
            and (artifact_ref is None or record.artifact_ref == artifact_ref)
        ]
        return max(matches, default=(0, None), key=lambda item: item[0])[1]

    def model_closure_violations(
        self,
        owner_user_id: str,
        passport_ref: str,
    ) -> tuple[ModelGovernanceViolation, ...]:
        """Recompute §15 closure from current owner-scoped durable heads.

        This ledger cannot prove external plan/run/version/dossier, promotion, or
        approval stores. Those obligations remain explicit violations instead of
        being inferred from string refs on the passport.
        """

        self._refresh()
        owner = self._required(owner_user_id, "owner_user_id")
        ref = self._required(passport_ref, "passport_ref")
        passport = self._passports.get((owner, ref))
        if passport is None:
            return (
                ModelGovernanceViolation(
                    "model_passport_not_recorded",
                    "model passport is not recorded for this owner",
                    field="passport_ref",
                    ref=ref,
                ),
            )

        violations: list[ModelGovernanceViolation] = []
        for code, field_name, value in (
            ("training_plan_not_durably_resolved", "training_plan_ref", passport.training_plan_ref),
            ("training_run_not_durably_resolved", "training_run_ref", passport.training_run_ref),
            ("model_version_not_durably_resolved", "model_version_ref", passport.model_version_ref),
            (
                "validation_dossier_not_durably_resolved",
                "validation_dossier_ref",
                passport.validation_dossier_ref,
            ),
            ("promotion_not_durably_resolved", "promotion_ref", passport.passport_id),
            ("approval_not_durably_resolved", "approval_ref", passport.passport_id),
        ):
            violations.append(
                ModelGovernanceViolation(
                    code,
                    "external governance producer is not connected to this owner-scoped registry",
                    field=field_name,
                    ref=_normalized_text(value),
                )
            )

        if _value(passport.model_risk_tier) in {ModelRiskTier.HIGH.value, ModelRiskTier.CRITICAL.value}:
            violations.append(
                ModelGovernanceViolation(
                    "challenger_evidence_not_durably_resolved",
                    "high-risk challenger evidence requires an exact durable external producer",
                    field="challenger_result",
                    ref=_normalized_text(passport.challenger_result),
                )
            )

        profiles = [
            (self._row_order[(owner, "model_monitoring_profile_recorded", record_ref)], profile)
            for (record_owner, record_ref), profile in self._monitoring_profiles.items()
            if record_owner == owner and profile.model_passport_ref == ref
        ]
        if not profiles:
            violations.append(
                ModelGovernanceViolation(
                    "current_monitoring_profile_missing",
                    "model closure requires a current owner-scoped monitoring profile",
                    field="monitoring_profile_ref",
                    ref=ref,
                )
            )

        for artifact in passport.artifact_manifest:
            violations.append(
                ModelGovernanceViolation(
                    "artifact_content_not_durably_resolved",
                    "artifact bytes require an exact durable external content resolver",
                    field="artifact_manifest.content_hash",
                    ref=artifact.artifact_ref,
                )
            )
            if artifact.producer_run_ref != passport.training_run_ref:
                violations.append(
                    ModelGovernanceViolation(
                        "artifact_lineage_mismatch",
                        "artifact producer run does not match the passport training run",
                        field="artifact_manifest.producer_run_ref",
                        ref=artifact.artifact_ref,
                    )
                )
            inspection = self._latest_artifact_inspection(
                owner,
                passport_ref=ref,
                inspection_ref=_normalized_text(artifact.sandbox_inspection_ref),
                artifact_ref=artifact.artifact_ref,
            )
            if (
                inspection is None
                or inspection.inspection_status != "accepted"
                or inspection.artifact_hash != artifact.content_hash
            ):
                violations.append(
                    ModelGovernanceViolation(
                        "current_artifact_inspection_missing",
                        "model closure requires a current accepted inspection with the exact artifact hash",
                        field="artifact_manifest",
                        ref=artifact.artifact_ref,
                    )
                )

        change_events = self._change_events.get((owner, ref), ())
        for trigger in change_events:
            candidates = [
                (
                    self._row_order[(owner, "model_recertification_recorded", record_ref)],
                    record,
                )
                for (record_owner, record_ref), record in self._recertification_records.items()
                if record_owner == owner
                and record.model_passport_ref == ref
                and _value(record.trigger) == trigger
            ]
            current = max(candidates, default=(0, None), key=lambda item: item[0])[1]
            if (
                current is None
                or current.decision not in {"accepted", "waived"}
                or current.recertification_record_id not in passport.recertification_records
            ):
                violations.append(
                    ModelGovernanceViolation(
                        "current_recertification_missing",
                        "change event is not cleared by the current exact recertification record",
                        field="recertification_records",
                        ref=trigger,
                    )
                )
        return tuple(violations)


__all__ = [
    "ModelArtifactFormat",
    "ModelArtifactInspectionRecord",
    "ModelArtifactManifestEntry",
    "ModelArtifactSource",
    "ModelGovernancePassport",
    "ModelGovernanceViolation",
    "ModelMonitoringProfile",
    "ModelPromotionDecision",
    "ModelRecertificationRecord",
    "ModelRiskTier",
    "ModelServingInvocationRecord",
    "PersistentModelGovernanceRegistry",
    "RecertificationTrigger",
    "SafeLoadingPolicy",
    "artifact_inspection_record_from_dict",
    "monitoring_profile_from_dict",
    "model_passport_from_dict",
    "recertification_record_from_dict",
    "serving_invocation_record_from_dict",
    "validate_model_promotion",
]
