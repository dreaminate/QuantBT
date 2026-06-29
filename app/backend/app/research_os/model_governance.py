"""GOAL §15 model governance promotion contract.

This module does not replace the existing training code or model registry. It
adds a strict promotion gate for the model-governance fields named in GOAL §15:
ValidationDossier, artifact loading safety, challenger evidence for high-risk
models, and recertification after material changes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from ..lineage.ids import content_hash as qbt_content_hash
from .spine import RuntimeStatus


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
        fmt = _value(self.artifact_format) or _format_from_uri(self.uri)
        if fmt == ModelArtifactFormat.OTHER.value:
            fmt = _format_from_uri(self.uri)
        object.__setattr__(self, "artifact_format", fmt)
        object.__setattr__(self, "source", _value(self.source) or ModelArtifactSource.UNKNOWN.value)
        if not self.artifact_id:
            object.__setattr__(
                self,
                "artifact_id",
                "model_artifact_"
                + qbt_content_hash(
                    {
                        "artifact_ref": self.artifact_ref,
                        "uri": self.uri,
                        "artifact_format": fmt,
                        "source": self.source,
                        "content_hash": self.content_hash,
                    }
                ),
            )

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

    def __post_init__(self) -> None:
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
        if not self.passport_id:
            object.__setattr__(
                self,
                "passport_id",
                "model_passport_"
                + qbt_content_hash(
                    {
                        "model_version_ref": self.model_version_ref,
                        "training_run_ref": self.training_run_ref,
                        "model_risk_tier": _value(self.model_risk_tier),
                        "artifact_manifest": _stable(self.artifact_manifest),
                    }
                ),
            )


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

    def __post_init__(self) -> None:
        for name in (
            "metric_refs",
            "drift_signal_refs",
            "performance_threshold_refs",
            "recertification_trigger_refs",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        if not self.monitoring_profile_id:
            object.__setattr__(
                self,
                "monitoring_profile_id",
                "model_monitoring_profile_"
                + qbt_content_hash(
                    {
                        "model_version_ref": self.model_version_ref,
                        "model_passport_ref": self.model_passport_ref,
                        "metric_refs": self.metric_refs,
                        "schedule_ref": self.schedule_ref,
                        "alert_policy_ref": self.alert_policy_ref,
                    }
                ),
            )


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        if not self.recertification_record_id:
            object.__setattr__(
                self,
                "recertification_record_id",
                "model_recertification_"
                + qbt_content_hash(
                    {
                        "model_version_ref": self.model_version_ref,
                        "model_passport_ref": self.model_passport_ref,
                        "trigger": _value(self.trigger),
                        "change_event_ref": self.change_event_ref,
                        "evidence_refs": self.evidence_refs,
                        "decision": self.decision,
                    }
                ),
            )


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

    def __post_init__(self) -> None:
        for name in ("checks", "limitations"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        if not self.artifact_inspection_record_id:
            object.__setattr__(
                self,
                "artifact_inspection_record_id",
                "model_artifact_inspection_"
                + qbt_content_hash(
                    {
                        "model_version_ref": self.model_version_ref,
                        "model_passport_ref": self.model_passport_ref,
                        "artifact_ref": self.artifact_ref,
                        "inspection_ref": self.inspection_ref,
                        "artifact_hash": self.artifact_hash,
                        "inspection_status": self.inspection_status,
                        "inspection_mode": self.inspection_mode,
                    }
                ),
            )


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_refs", _tuple(self.feature_refs))
        if not self.serving_invocation_id:
            object.__setattr__(
                self,
                "serving_invocation_id",
                "model_serving_invocation_"
                + qbt_content_hash(
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
                ),
            )


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
    """Append-only registry for ModelGovernancePassport records.

    The registry records governance metadata only. It does not load model files,
    register training artifacts in the legacy ModelRegistry, or promote a model
    into a runtime stage.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._passports: dict[str, ModelGovernancePassport] = {}
        self._change_events: dict[str, tuple[str, ...]] = {}
        self._monitoring_profiles: dict[str, ModelMonitoringProfile] = {}
        self._recertification_records: dict[str, ModelRecertificationRecord] = {}
        self._artifact_inspections: dict[str, ModelArtifactInspectionRecord] = {}
        self._serving_invocations: dict[str, ModelServingInvocationRecord] = {}
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
                except Exception as exc:  # noqa: BLE001 - bad model governance history must block startup.
                    raise ValueError(f"invalid persisted model governance row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported model governance schema_version")
        event_type = row.get("event_type")
        if event_type == "model_passport_recorded":
            raw = row.get("passport")
            if not isinstance(raw, dict):
                raise ValueError("model governance event missing passport")
            passport = model_passport_from_dict(raw)
            self._record_passport(passport, change_events=_trigger_tuple(row.get("change_events")), persist=persist)
            return
        if event_type == "model_monitoring_profile_recorded":
            raw = row.get("monitoring_profile")
            if not isinstance(raw, dict):
                raise ValueError("model governance event missing monitoring_profile")
            self._record_monitoring_profile(monitoring_profile_from_dict(raw), persist=persist)
            return
        if event_type == "model_recertification_recorded":
            raw = row.get("recertification_record")
            if not isinstance(raw, dict):
                raise ValueError("model governance event missing recertification_record")
            self._record_recertification_record(recertification_record_from_dict(raw), persist=persist)
            return
        if event_type == "model_artifact_inspection_recorded":
            raw = row.get("artifact_inspection")
            if not isinstance(raw, dict):
                raise ValueError("model governance event missing artifact_inspection")
            self._record_artifact_inspection(artifact_inspection_record_from_dict(raw), persist=persist)
            return
        if event_type == "model_serving_invocation_recorded":
            raw = row.get("serving_invocation")
            if not isinstance(raw, dict):
                raise ValueError("model governance event missing serving_invocation")
            self._record_serving_invocation(serving_invocation_record_from_dict(raw), persist=persist)
            return
        raise ValueError(f"unknown model governance event_type={event_type!r}")

    def record_passport(
        self,
        passport: ModelGovernancePassport,
        *,
        change_events: tuple[RecertificationTrigger | str, ...] = (),
    ) -> ModelGovernancePassport:
        return self._record_passport(passport, change_events=change_events, persist=True)

    def _record_passport(
        self,
        passport: ModelGovernancePassport,
        *,
        change_events: tuple[RecertificationTrigger | str, ...],
        persist: bool,
    ) -> ModelGovernancePassport:
        normalized_change_events = _trigger_tuple(change_events)
        decision = validate_model_promotion(passport, change_events=normalized_change_events)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._passports[passport.passport_id] = passport
        self._change_events[passport.passport_id] = normalized_change_events
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "model_passport_recorded",
                    "passport": _stable(passport),
                    "change_events": list(normalized_change_events),
                }
            )
        return passport

    def _matching_passport(self, model_passport_ref: str, model_version_ref: str) -> ModelGovernancePassport:
        if not model_passport_ref:
            raise ValueError("model_passport_ref is required")
        try:
            passport = self._passports[model_passport_ref]
        except KeyError as exc:
            raise ValueError(f"model_passport_ref not recorded: {model_passport_ref}") from exc
        if passport.model_version_ref != model_version_ref:
            raise ValueError(
                "model_passport_ref does not match model_version_ref: "
                f"{passport.model_version_ref!r} != {model_version_ref!r}"
            )
        return passport

    def record_monitoring_profile(self, profile: ModelMonitoringProfile) -> ModelMonitoringProfile:
        return self._record_monitoring_profile(profile, persist=True)

    def _record_monitoring_profile(
        self,
        profile: ModelMonitoringProfile,
        *,
        persist: bool,
    ) -> ModelMonitoringProfile:
        passport = self._matching_passport(profile.model_passport_ref, profile.model_version_ref)
        if not profile.metric_refs:
            raise ValueError("monitoring profile requires metric_refs")
        if not str(profile.schedule_ref or "").strip():
            raise ValueError("monitoring profile requires schedule_ref")
        if not str(profile.alert_policy_ref or "").strip():
            raise ValueError("monitoring profile requires alert_policy_ref")
        declared = {_value(trigger) for trigger in passport.recertification_triggers}
        for trigger in profile.recertification_trigger_refs:
            if _value(trigger) not in declared:
                raise ValueError(f"monitoring profile trigger not declared on passport: {_value(trigger)}")
        self._monitoring_profiles[profile.monitoring_profile_id] = profile
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "model_monitoring_profile_recorded",
                    "monitoring_profile": _stable(profile),
                }
            )
        return profile

    def record_recertification_record(self, record: ModelRecertificationRecord) -> ModelRecertificationRecord:
        return self._record_recertification_record(record, persist=True)

    def _record_recertification_record(
        self,
        record: ModelRecertificationRecord,
        *,
        persist: bool,
    ) -> ModelRecertificationRecord:
        passport = self._matching_passport(record.model_passport_ref, record.model_version_ref)
        trigger = _value(record.trigger)
        if trigger not in {_value(value) for value in passport.recertification_triggers}:
            raise ValueError(f"recertification trigger not declared on passport: {trigger}")
        if not str(record.change_event_ref or "").strip():
            raise ValueError("recertification record requires change_event_ref")
        if not record.evidence_refs:
            raise ValueError("recertification record requires evidence_refs")
        if record.decision not in {"accepted", "rejected", "waived"}:
            raise ValueError("recertification decision must be accepted, rejected, or waived")
        if not str(record.recorded_by or "").strip():
            raise ValueError("recertification record requires recorded_by")
        self._recertification_records[record.recertification_record_id] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "model_recertification_recorded",
                    "recertification_record": _stable(record),
                }
            )
        return record

    def record_artifact_inspection(self, record: ModelArtifactInspectionRecord) -> ModelArtifactInspectionRecord:
        return self._record_artifact_inspection(record, persist=True)

    def _record_artifact_inspection(
        self,
        record: ModelArtifactInspectionRecord,
        *,
        persist: bool,
    ) -> ModelArtifactInspectionRecord:
        passport = self._matching_passport(record.model_passport_ref, record.model_version_ref)
        artifact = next(
            (candidate for candidate in passport.artifact_manifest if candidate.artifact_ref == record.artifact_ref),
            None,
        )
        if artifact is None:
            raise ValueError(f"artifact_ref not recorded on passport: {record.artifact_ref}")
        if not str(record.inspection_ref or "").strip():
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
        if not str(record.inspection_mode or "").strip():
            raise ValueError("artifact inspection requires inspection_mode")
        if not str(record.inspector_ref or "").strip():
            raise ValueError("artifact inspection requires inspector_ref")
        if not record.checks:
            raise ValueError("artifact inspection requires checks")
        if artifact.is_external and artifact.is_unsafe_serialized and record.inspection_status == "accepted":
            raise ValueError("external pickle/joblib artifact inspection cannot be accepted")
        if artifact.is_unsafe_serialized and record.inspection_mode != "metadata_only_no_deserialize":
            raise ValueError("pickle/joblib artifact inspection must use metadata_only_no_deserialize mode")
        self._artifact_inspections[record.artifact_inspection_record_id] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "model_artifact_inspection_recorded",
                    "artifact_inspection": _stable(record),
                }
            )
        return record

    def record_serving_invocation(self, record: ModelServingInvocationRecord) -> ModelServingInvocationRecord:
        return self._record_serving_invocation(record, persist=True)

    def _record_serving_invocation(
        self,
        record: ModelServingInvocationRecord,
        *,
        persist: bool,
    ) -> ModelServingInvocationRecord:
        self._matching_passport(record.model_passport_ref, record.model_version_ref)
        if _value(record.runtime) not in {RuntimeStatus.LIVE.value, "staging", "production"}:
            raise ValueError("model serving invocation runtime must be staging or production/live")
        if not record.feature_refs:
            raise ValueError("model serving invocation requires feature_refs")
        if record.row_count <= 0:
            raise ValueError("model serving invocation requires row_count > 0")
        if not str(record.request_hash or "").strip():
            raise ValueError("model serving invocation requires request_hash")
        if not str(record.prediction_hash or "").strip():
            raise ValueError("model serving invocation requires prediction_hash")
        inspection = next(
            (
                item
                for item in self._artifact_inspections.values()
                if item.inspection_ref == record.artifact_inspection_ref
                and item.model_passport_ref == record.model_passport_ref
                and item.inspection_status == "accepted"
            ),
            None,
        )
        if inspection is None:
            raise ValueError("model serving invocation requires accepted artifact_inspection_ref")
        profile = self._monitoring_profiles.get(record.monitoring_profile_ref)
        if profile is None or profile.model_passport_ref != record.model_passport_ref:
            raise ValueError("model serving invocation requires matching monitoring_profile_ref")
        if not str(record.recorded_by or "").strip():
            raise ValueError("model serving invocation requires recorded_by")
        self._serving_invocations[record.serving_invocation_id] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "model_serving_invocation_recorded",
                    "serving_invocation": _stable(record),
                }
            )
        return record

    def passport(self, passport_id: str) -> ModelGovernancePassport:
        return self._passports[passport_id]

    def passports(self) -> list[ModelGovernancePassport]:
        return list(self._passports.values())

    def change_events(self, passport_id: str) -> tuple[str, ...]:
        return self._change_events[passport_id]

    def monitoring_profile(self, profile_id: str) -> ModelMonitoringProfile:
        return self._monitoring_profiles[profile_id]

    def monitoring_profiles(self) -> list[ModelMonitoringProfile]:
        return list(self._monitoring_profiles.values())

    def recertification_record(self, record_id: str) -> ModelRecertificationRecord:
        return self._recertification_records[record_id]

    def recertification_records(self) -> list[ModelRecertificationRecord]:
        return list(self._recertification_records.values())

    def artifact_inspection(self, record_id: str) -> ModelArtifactInspectionRecord:
        return self._artifact_inspections[record_id]

    def artifact_inspections(self) -> list[ModelArtifactInspectionRecord]:
        return list(self._artifact_inspections.values())

    def serving_invocation(self, record_id: str) -> ModelServingInvocationRecord:
        return self._serving_invocations[record_id]

    def serving_invocations(self) -> list[ModelServingInvocationRecord]:
        return list(self._serving_invocations.values())


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
