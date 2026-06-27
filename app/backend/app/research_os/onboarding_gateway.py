"""GOAL §4 Data Onboarding, Settings/Secrets, and LLM Gateway contracts.

This module is a governance contract for data/LLM onboarding records. It does
not replace current connectors or LLM provider adapters. It gives Settings,
SecretRef, IngestionSkill, DataSourceAsset, LLMProvider, CredentialPool, and
ModelRoutingPolicy a strict validator so agent-facing code cannot treat
plaintext credentials or revoked refs as normal runtime state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


SECRET_PATTERN = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]\s*['\"]?[^,\s'\"]{6,}|"
    r"password\s*[:=]\s*['\"]?[^,\s'\"]{6,}|oauth[_-]?token\s*[:=]\s*['\"]?[^,\s'\"]{6,})"
)
SECRET_IDENTIFIER_PATTERN = re.compile(r"(?i)(api[_-]?key|api[_-]?secret|secret|password|oauth|credential|private[_-]?key)")
CANONICAL_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")


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


def _ref_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _content_hash(value: Any) -> str:
    body = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _is_secret_or_token_ref(ref: str) -> bool:
    r = str(ref or "").strip().lower()
    return r.startswith(("secretref:", "secret_ref:", "secref:", "tokenref:", "token_ref:"))


def contains_plaintext_secret(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key).lower()
            if key_str in {"api_key", "api_secret", "secret", "password", "oauth_token", "token"}:
                return True
            if contains_plaintext_secret(child):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(contains_plaintext_secret(child) for child in value)
    return bool(SECRET_PATTERN.search(str(value)))


def ingestion_skill_allows_no_secret_connector(skill: "IngestionSkillRecord") -> bool:
    auth_mode = str(
        skill.connector_config.get("auth_mode")
        or skill.connector_config.get("auth")
        or skill.connector_config.get("credential_mode")
        or ""
    ).strip().lower().replace("-", "_")
    auth_ref = str(
        skill.connector_config.get("auth_ref")
        or skill.connector_config.get("secret_ref")
        or skill.connector_config.get("token_ref")
        or ""
    ).strip()
    return auth_mode in {"none", "no_auth", "public"} and not auth_ref and not skill.secret_refs


def _field_mapping_plaintext_payload(record: "DataConnectorFieldMappingRecord") -> dict[str, Any]:
    payload = _json_value(record)
    payload["source_to_canonical"] = [
        {"source_column": source_column, "canonical_field": canonical_field}
        for source_column, canonical_field in record.source_to_canonical.items()
    ]
    return payload


class SecretRefStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    STALE = "stale"
    ROTATING = "rotating"


class IngestionLifecycleState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DEGRADED = "degraded"
    NEEDS_REPAIR = "needs_repair"
    REVOKED = "revoked"


@dataclass(frozen=True)
class OnboardingViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class OnboardingWarning:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class OnboardingDecision:
    accepted: bool
    violations: tuple[OnboardingViolation, ...]
    warnings: tuple[OnboardingWarning, ...] = ()
    export_allowed: bool = True
    share_allowed: bool = True


@dataclass(frozen=True)
class SecretRefRecord:
    secret_ref: str
    scope: str
    status: SecretRefStatus | str
    created_at: str
    last_test: str | None = None
    last_used: str | None = None
    rotation_record: str | None = None
    access_audit: tuple[str, ...] = ()
    stale_warning: str | None = None
    connector_scope_review: str | None = None
    revoked_at: str | None = None
    affected_skills: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "access_audit", _tuple(self.access_audit))
        object.__setattr__(self, "affected_skills", _tuple(self.affected_skills))


@dataclass(frozen=True)
class IngestionSkillRecord:
    skill_id: str
    source_type: str
    source_ref: str
    connector_config: dict[str, Any]
    schema_mapping_ref: str
    secret_refs: tuple[str, ...]
    refresh_mode: str
    data_quality_tests: tuple[str, ...]
    pit_bitemporal_rules_ref: str
    output_dataset_id: str
    owner: str
    version: str
    lifecycle_state: IngestionLifecycleState | str
    freshness_status: str
    permission_scope: str
    dependency_lock_ref: str
    schedule_owner: str
    rollback_plan_ref: str
    last_run: str | None = None
    last_success: str | None = None
    drift_alerts: tuple[str, ...] = ()
    failure_reason: str | None = None
    schema_drift_status: str = "none"
    schema_drift_event_refs: tuple[str, ...] = ()
    downstream_impact_refs: tuple[str, ...] = ()
    dry_run_diff_ref: str | None = None
    quarantine_ref: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "secret_refs",
            "data_quality_tests",
            "drift_alerts",
            "schema_drift_event_refs",
            "downstream_impact_refs",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


@dataclass(frozen=True)
class DataSourceAssetRecord:
    source_ref: str
    license: str | None
    redistribution_rights: str | None
    rate_limit: str | None
    tos_constraints: str | None
    commercial_use_status: str | None
    retention_policy: str | None
    source_owner: str | None
    source_url_or_path: str | None


@dataclass(frozen=True)
class DataConnectorConnectionCheckRecord:
    check_ref: str
    skill_id: str
    source_ref: str
    secret_refs: tuple[str, ...]
    checked_at: str
    checker_ref: str
    status: str
    health_status: str
    quota_status: str
    permission_scope: str | None = None
    capability_refs: tuple[str, ...] = ()
    schema_probe_ref: str | None = None
    response_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    recorded_by: str | None = None

    def __post_init__(self) -> None:
        for name in ("secret_refs", "capability_refs"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


@dataclass(frozen=True)
class DataConnectorSchemaProbeRecord:
    probe_ref: str
    skill_id: str
    source_ref: str
    connector_check_ref: str
    probed_at: str
    schema_signature_hash: str
    columns: tuple[str, ...]
    dtypes: dict[str, str]
    row_count: int
    dataset_version_ref: str | None = None
    drift_status: str = "none"
    previous_probe_ref: str | None = None
    schema_drift_event_ref: str | None = None
    downstream_impact_refs: tuple[str, ...] = ()
    recorded_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", _tuple(self.columns))
        object.__setattr__(self, "dtypes", {str(k): str(v) for k, v in dict(self.dtypes or {}).items()})
        object.__setattr__(self, "downstream_impact_refs", _tuple(self.downstream_impact_refs))


@dataclass(frozen=True)
class DataConnectorFieldMappingRecord:
    mapping_ref: str
    skill_id: str
    source_ref: str
    schema_probe_ref: str
    mapped_at: str
    schema_signature_hash: str
    source_to_canonical: dict[str, str]
    event_time_column: str
    known_at_column: str | None = None
    effective_at_column: str | None = None
    symbol_column: str | None = None
    unmapped_columns: tuple[str, ...] = ()
    mapping_hash: str | None = None
    mapping_method: str = "manual"
    pit_bitemporal_candidate_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_to_canonical",
            {str(k): str(v) for k, v in dict(self.source_to_canonical or {}).items()},
        )
        object.__setattr__(self, "unmapped_columns", _tuple(self.unmapped_columns))
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))


@dataclass(frozen=True)
class DataConnectorPITBitemporalRuleRecord:
    rule_ref: str
    skill_id: str
    source_ref: str
    field_mapping_ref: str
    schema_probe_ref: str
    generated_at: str
    event_time_column: str
    known_at_policy: str
    effective_at_policy: str
    asof_join_policy: str
    timezone: str
    lookahead_guard_ref: str
    restatement_policy: str
    known_at_column: str | None = None
    effective_at_column: str | None = None
    calendar_ref: str | None = None
    monotonicity_check_ref: str | None = None
    rule_hash: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))


@dataclass(frozen=True)
class LLMProviderRecord:
    provider_id: str
    provider_type: str
    auth_methods: tuple[str, ...]
    base_url: str
    model_profiles: tuple[str, ...]
    capability_tags: tuple[str, ...]
    context_window: int
    tool_calling_support: bool
    structured_output_support: bool
    cost_model_ref: str
    rate_limits: str
    data_retention_policy: str
    region_residency: str
    allowed_roles: tuple[str, ...]
    allowed_desks: tuple[str, ...]
    health_status: str
    quota_status: str
    auth_refs: tuple[str, ...]
    plaintext_credential: str | None = None

    def __post_init__(self) -> None:
        for name in ("auth_methods", "model_profiles", "capability_tags", "allowed_roles", "allowed_desks", "auth_refs"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


@dataclass(frozen=True)
class LLMProviderHealthSnapshotRecord:
    snapshot_ref: str
    provider_id: str
    auth_ref: str
    checked_at: str
    checker_ref: str
    health_status: str
    quota_status: str
    latency_ms: int
    response_hash: str
    capability_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None
    recorded_by: str | None = None
    snapshot_hash: str | None = None

    def __post_init__(self) -> None:
        for name in ("capability_refs", "evidence_refs"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        payload = {
            "snapshot_ref": self.snapshot_ref,
            "provider_id": self.provider_id,
            "auth_ref": self.auth_ref,
            "checked_at": self.checked_at,
            "checker_ref": self.checker_ref,
            "health_status": self.health_status,
            "quota_status": self.quota_status,
            "latency_ms": self.latency_ms,
            "response_hash": self.response_hash,
            "capability_refs": self.capability_refs,
            "evidence_refs": self.evidence_refs,
            "error_code": self.error_code,
            "recorded_by": self.recorded_by,
        }
        expected = "sha16:" + _content_hash(payload)[:16]
        if self.snapshot_hash and self.snapshot_hash != expected:
            raise ValueError("LLMProviderHealthSnapshot hash mismatch")
        object.__setattr__(self, "snapshot_hash", expected)


@dataclass(frozen=True)
class LLMCredentialPoolRecord:
    pool_id: str
    provider_id: str
    auth_refs: tuple[str, ...]
    priority: tuple[str, ...]
    rotation_policy: str
    fallback_policy: str
    rate_limit_policy: str
    quota_policy: str
    owner: str
    last_test: str | None = None
    last_used: str | None = None
    revoked_refs: tuple[str, ...] = ()
    affected_role_agents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("auth_refs", "priority", "revoked_refs", "affected_role_agents"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


@dataclass(frozen=True)
class ModelRoutingPolicyRecord:
    routing_policy_id: str
    role_agent: str
    desk: str
    task_type: str
    required_capabilities: tuple[str, ...]
    allowed_providers: tuple[str, ...]
    allowed_models: tuple[str, ...]
    credential_pool_ref: str | None
    fallback_order: tuple[str, ...]
    cost_limit: str | None
    latency_limit: str | None
    data_retention_requirement: str | None
    independence_requirement: str | None
    replay_requirement: str | None

    def __post_init__(self) -> None:
        for name in ("required_capabilities", "allowed_providers", "allowed_models", "fallback_order"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


@dataclass(frozen=True)
class LLMGatewayCallRequest:
    role_agent: str
    desk: str
    task_type: str
    provider_id: str
    model_id: str
    routing_policy_ref: str
    credential_pool_ref: str
    auth_ref: str
    via_gateway: bool
    replay_record_ref: str | None = None
    plaintext_credential: str | None = None
    payload_preview: dict[str, Any] | None = None


def _require_text(
    violations: list[OnboardingViolation],
    *,
    field_name: str,
    value: str | None,
    ref: str,
) -> None:
    if not _present(value):
        violations.append(
            OnboardingViolation(
                "settings_required_field_missing",
                f"{field_name} is required",
                field=field_name,
                ref=ref,
            )
        )


def validate_secret_ref(record: SecretRefRecord) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    _require_text(violations, field_name="secret_ref", value=record.secret_ref, ref=record.secret_ref)
    _require_text(violations, field_name="scope", value=record.scope, ref=record.secret_ref)
    _require_text(violations, field_name="created_at", value=record.created_at, ref=record.secret_ref)
    if not _is_secret_or_token_ref(record.secret_ref):
        violations.append(
            OnboardingViolation(
                "secret_ref_not_settings_managed",
                "SecretRef metadata must use a SecretRef or TokenRef identifier",
                field="secret_ref",
                ref=record.secret_ref,
            )
        )
    if contains_plaintext_secret(_json_value(record)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_secret_ref_metadata",
                "SecretRef metadata cannot contain plaintext credential material",
                field="secret_ref",
                ref=record.secret_ref,
            )
        )
    if _ref_value(record.status) == SecretRefStatus.REVOKED.value and not _present(record.revoked_at):
        violations.append(
            OnboardingViolation(
                "revoked_secret_missing_revoked_at",
                "revoked SecretRef metadata must include revoked_at",
                field="revoked_at",
                ref=record.secret_ref,
            )
        )
    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_data_source_asset(asset: DataSourceAssetRecord) -> OnboardingDecision:
    warnings: list[OnboardingWarning] = []
    violations: list[OnboardingViolation] = []
    _require_text(violations, field_name="source_ref", value=asset.source_ref, ref=asset.source_ref)
    if contains_plaintext_secret(_json_value(asset)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_data_source_asset",
                "DataSourceAsset metadata cannot contain plaintext credential material",
                field="source_url_or_path",
                ref=asset.source_ref,
            )
        )
    for field_name in ("license", "rate_limit", "retention_policy"):
        if not _present(getattr(asset, field_name)):
            warnings.append(
                OnboardingWarning(
                    f"missing_{field_name}",
                    f"DataSourceAsset missing {field_name}; export/share must be restricted",
                    field=field_name,
                    ref=asset.source_ref,
                )
            )
    restricted = bool(warnings)
    return OnboardingDecision(
        accepted=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
        export_allowed=not restricted,
        share_allowed=not restricted,
    )


def validate_ingestion_skill_run(
    skill: IngestionSkillRecord,
    *,
    secrets: dict[str, SecretRefRecord],
) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []

    if contains_plaintext_secret(skill.connector_config):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_connector_config",
                "connector_config must contain SecretRef/TokenRef only, not plaintext credentials",
                field="connector_config",
                ref=skill.skill_id,
            )
        )

    for ref in skill.secret_refs:
        record = secrets.get(ref)
        if record is None:
            violations.append(
                OnboardingViolation(
                    "missing_secret_ref_record",
                    "IngestionSkill secret_ref must resolve to Settings/Secrets metadata",
                    field="secret_refs",
                    ref=ref,
                )
            )
            continue
        if _ref_value(record.status) == SecretRefStatus.REVOKED.value:
            allowed_states = {
                IngestionLifecycleState.PAUSED.value,
                IngestionLifecycleState.DEGRADED.value,
                IngestionLifecycleState.NEEDS_REPAIR.value,
                IngestionLifecycleState.REVOKED.value,
            }
            if _ref_value(skill.lifecycle_state) not in allowed_states:
                violations.append(
                    OnboardingViolation(
                        "revoked_secret_skill_running",
                        "SecretRef revoke must pause, degrade, revoke, or mark the skill needs_repair",
                        field="lifecycle_state",
                        ref=skill.skill_id,
                    )
                )

    if str(skill.schema_drift_status).lower() not in {"", "none", "ok", "unchanged"}:
        if not skill.schema_drift_event_refs or not skill.downstream_impact_refs:
            violations.append(
                OnboardingViolation(
                    "schema_drift_missing_event_or_impact",
                    "schema drift requires an event record and downstream impact preview",
                    field="schema_drift_status",
                    ref=skill.skill_id,
                )
            )

    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_data_connector_connection_check(
    record: DataConnectorConnectionCheckRecord,
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    secrets: dict[str, SecretRefRecord],
) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    warnings: list[OnboardingWarning] = []

    for field_name in ("check_ref", "skill_id", "source_ref", "checked_at", "checker_ref", "status"):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.check_ref)

    if contains_plaintext_secret(_json_value(record)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_connector_check",
                "connector check metadata cannot contain plaintext credential material",
                field="data_connector_check",
                ref=record.check_ref,
            )
        )

    if record.skill_id != skill.skill_id:
        violations.append(
            OnboardingViolation(
                "connector_check_skill_mismatch",
                "connector check skill_id must match the recorded IngestionSkill",
                field="skill_id",
                ref=record.check_ref,
            )
        )
    if record.source_ref != skill.source_ref or record.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "connector_check_source_mismatch",
                "connector check source_ref must match the IngestionSkill and DataSourceAsset",
                field="source_ref",
                ref=record.check_ref,
            )
        )

    skill_decision = validate_ingestion_skill_run(skill, secrets=secrets)
    violations.extend(skill_decision.violations)
    source_decision = validate_data_source_asset(source)
    violations.extend(source_decision.violations)
    warnings.extend(source_decision.warnings)

    if not record.secret_refs and not ingestion_skill_allows_no_secret_connector(skill):
        violations.append(
            OnboardingViolation(
                "connector_check_missing_secret_refs",
                "connector check requires Settings-managed SecretRef/TokenRef references unless the IngestionSkill explicitly declares auth_mode=none",
                field="secret_refs",
                ref=record.check_ref,
            )
        )
    skill_refs = set(skill.secret_refs)
    for ref in record.secret_refs:
        if ref not in skill_refs:
            violations.append(
                OnboardingViolation(
                    "connector_check_secret_ref_not_in_skill",
                    "connector check secret_refs must be declared by the IngestionSkill",
                    field="secret_refs",
                    ref=ref,
                )
            )
        secret = secrets.get(ref)
        if secret is None:
            violations.append(
                OnboardingViolation(
                    "connector_check_missing_secret_ref_record",
                    "connector check secret_ref must resolve to Settings/Secrets metadata",
                    field="secret_refs",
                    ref=ref,
                )
            )
            continue
        if _ref_value(secret.status) == SecretRefStatus.REVOKED.value:
            violations.append(
                OnboardingViolation(
                    "connector_check_uses_revoked_secret_ref",
                    "connector check cannot use a revoked SecretRef",
                    field="secret_refs",
                    ref=ref,
                )
            )

    status = str(record.status or "").lower()
    if status not in {"ok", "failed", "disabled", "degraded"}:
        violations.append(
            OnboardingViolation(
                "connector_check_invalid_status",
                "connector check status must be ok, failed, disabled, or degraded",
                field="status",
                ref=record.check_ref,
            )
        )
    if status == "ok":
        if str(record.health_status or "").lower() not in {"ok", "healthy"}:
            violations.append(
                OnboardingViolation(
                    "connector_check_ok_without_healthy_status",
                    "ok connector check requires healthy health_status",
                    field="health_status",
                    ref=record.check_ref,
                )
            )
        if not _present(record.response_hash):
            violations.append(
                OnboardingViolation(
                    "connector_check_ok_missing_response_hash",
                    "ok connector check requires a sanitized response_hash",
                    field="response_hash",
                    ref=record.check_ref,
                )
            )
    if status in {"failed", "disabled"} and not _present(record.error_code):
        violations.append(
            OnboardingViolation(
                "connector_check_failure_missing_error_code",
                "failed or disabled connector check requires an error_code",
                field="error_code",
                ref=record.check_ref,
            )
        )

    return OnboardingDecision(
        accepted=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
        export_allowed=source_decision.export_allowed,
        share_allowed=source_decision.share_allowed,
    )


def validate_data_connector_schema_probe(
    record: DataConnectorSchemaProbeRecord,
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    connector_check: DataConnectorConnectionCheckRecord,
) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []

    for field_name in ("probe_ref", "skill_id", "source_ref", "connector_check_ref", "probed_at", "schema_signature_hash"):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.probe_ref)

    if contains_plaintext_secret(_json_value(record)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_schema_probe",
                "schema probe metadata cannot contain plaintext credential material",
                field="schema_probe",
                ref=record.probe_ref,
            )
        )
    if record.skill_id != skill.skill_id:
        violations.append(
            OnboardingViolation(
                "schema_probe_skill_mismatch",
                "schema probe skill_id must match the recorded IngestionSkill",
                field="skill_id",
                ref=record.probe_ref,
            )
        )
    if record.source_ref != skill.source_ref or record.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "schema_probe_source_mismatch",
                "schema probe source_ref must match the IngestionSkill and DataSourceAsset",
                field="source_ref",
                ref=record.probe_ref,
            )
        )
    if record.connector_check_ref != connector_check.check_ref:
        violations.append(
            OnboardingViolation(
                "schema_probe_connector_check_mismatch",
                "schema probe must bind the ok connector check used for ingestion",
                field="connector_check_ref",
                ref=record.probe_ref,
            )
        )
    if str(connector_check.status or "").lower() != "ok":
        violations.append(
            OnboardingViolation(
                "schema_probe_requires_ok_connector_check",
                "schema probe requires an ok DataConnectorConnectionCheck",
                field="connector_check_ref",
                ref=record.probe_ref,
            )
        )
    if not record.columns or not record.dtypes:
        violations.append(
            OnboardingViolation(
                "schema_probe_missing_columns_or_dtypes",
                "schema probe requires observed columns and dtypes",
                field="columns",
                ref=record.probe_ref,
            )
        )
    missing_dtype = [name for name in record.columns if name not in record.dtypes]
    if missing_dtype:
        violations.append(
            OnboardingViolation(
                "schema_probe_dtype_missing_for_column",
                "schema probe dtypes must cover every observed column",
                field="dtypes",
                ref=",".join(missing_dtype),
            )
        )
    drift_status = str(record.drift_status or "").lower()
    if drift_status not in {"none", "unchanged", "changed", "drifted"}:
        violations.append(
            OnboardingViolation(
                "schema_probe_invalid_drift_status",
                "schema probe drift_status must be none, unchanged, changed, or drifted",
                field="drift_status",
                ref=record.probe_ref,
            )
        )
    if drift_status in {"changed", "drifted"}:
        if not _present(record.previous_probe_ref):
            violations.append(
                OnboardingViolation(
                    "schema_drift_missing_previous_probe",
                    "schema drift requires the previous schema probe ref",
                    field="previous_probe_ref",
                    ref=record.probe_ref,
                )
            )
        if not _present(record.schema_drift_event_ref) or not record.downstream_impact_refs:
            violations.append(
                OnboardingViolation(
                    "schema_drift_missing_event_or_impact",
                    "schema drift requires an event record and downstream impact preview",
                    field="schema_drift_event_ref",
                    ref=record.probe_ref,
                )
            )

    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def data_connector_field_mapping_hash(record: DataConnectorFieldMappingRecord) -> str:
    return "field_mapping:" + _content_hash(
        {
            "mapping_ref": record.mapping_ref,
            "skill_id": record.skill_id,
            "source_ref": record.source_ref,
            "schema_probe_ref": record.schema_probe_ref,
            "schema_signature_hash": record.schema_signature_hash,
            "source_to_canonical": record.source_to_canonical,
            "event_time_column": record.event_time_column,
            "known_at_column": record.known_at_column,
            "effective_at_column": record.effective_at_column,
            "symbol_column": record.symbol_column,
            "unmapped_columns": record.unmapped_columns,
            "mapping_method": record.mapping_method,
            "pit_bitemporal_candidate_ref": record.pit_bitemporal_candidate_ref,
            "evidence_refs": record.evidence_refs,
        }
    )


def validate_data_connector_field_mapping(
    record: DataConnectorFieldMappingRecord,
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    schema_probe: DataConnectorSchemaProbeRecord,
) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []

    for field_name in (
        "mapping_ref",
        "skill_id",
        "source_ref",
        "schema_probe_ref",
        "mapped_at",
        "schema_signature_hash",
        "event_time_column",
    ):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.mapping_ref)

    if contains_plaintext_secret(_field_mapping_plaintext_payload(record)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_field_mapping",
                "field mapping metadata cannot contain plaintext credential material",
                field="field_mapping",
                ref=record.mapping_ref,
            )
        )
    if record.skill_id != skill.skill_id:
        violations.append(
            OnboardingViolation(
                "field_mapping_skill_mismatch",
                "field mapping skill_id must match the recorded IngestionSkill",
                field="skill_id",
                ref=record.mapping_ref,
            )
        )
    if record.source_ref != skill.source_ref or record.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "field_mapping_source_mismatch",
                "field mapping source_ref must match the IngestionSkill and DataSourceAsset",
                field="source_ref",
                ref=record.mapping_ref,
            )
        )
    if record.schema_probe_ref != schema_probe.probe_ref:
        violations.append(
            OnboardingViolation(
                "field_mapping_schema_probe_mismatch",
                "field mapping must bind the recorded schema probe",
                field="schema_probe_ref",
                ref=record.mapping_ref,
            )
        )
    if schema_probe.skill_id != skill.skill_id or schema_probe.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "field_mapping_schema_probe_wrong_scope",
                "field mapping schema probe must belong to the same IngestionSkill and DataSourceAsset",
                field="schema_probe_ref",
                ref=record.schema_probe_ref,
            )
        )
    if record.schema_signature_hash != schema_probe.schema_signature_hash:
        violations.append(
            OnboardingViolation(
                "field_mapping_schema_signature_mismatch",
                "field mapping schema_signature_hash must match the schema probe",
                field="schema_signature_hash",
                ref=record.mapping_ref,
            )
        )
    if skill.schema_mapping_ref and record.mapping_ref != skill.schema_mapping_ref:
        violations.append(
            OnboardingViolation(
                "field_mapping_ref_mismatch",
                "field mapping_ref must resolve the IngestionSkill schema_mapping_ref",
                field="mapping_ref",
                ref=record.mapping_ref,
            )
        )

    schema_columns = {str(column) for column in schema_probe.columns}
    mapped_columns = {str(column) for column in record.source_to_canonical}
    unmapped_columns = {str(column) for column in record.unmapped_columns}
    if not record.source_to_canonical:
        violations.append(
            OnboardingViolation(
                "field_mapping_missing_source_to_canonical",
                "field mapping requires source_to_canonical entries",
                field="source_to_canonical",
                ref=record.mapping_ref,
            )
        )
    unknown_columns = sorted((mapped_columns | unmapped_columns) - schema_columns)
    if unknown_columns:
        violations.append(
            OnboardingViolation(
                "field_mapping_unknown_source_column",
                "field mapping can only reference columns observed by the schema probe",
                field="source_to_canonical",
                ref=",".join(unknown_columns),
            )
        )
    overlap = sorted(mapped_columns & unmapped_columns)
    if overlap:
        violations.append(
            OnboardingViolation(
                "field_mapping_column_both_mapped_and_unmapped",
                "field mapping cannot mark a source column as both mapped and unmapped",
                field="unmapped_columns",
                ref=",".join(overlap),
            )
        )
    missing_columns = sorted(schema_columns - mapped_columns - unmapped_columns)
    if missing_columns:
        violations.append(
            OnboardingViolation(
                "field_mapping_missing_column_coverage",
                "field mapping must map or explicitly mark every observed column as unmapped",
                field="source_to_canonical",
                ref=",".join(missing_columns),
            )
        )

    canonical_targets: list[str] = []
    for source_column in record.unmapped_columns:
        if SECRET_IDENTIFIER_PATTERN.search(str(source_column)):
            violations.append(
                OnboardingViolation(
                    "field_mapping_secret_like_column_or_field",
                    "field mapping cannot normalize secret-like columns or field identifiers",
                    field="unmapped_columns",
                    ref=str(source_column),
                )
            )
    for source_column, canonical_field in record.source_to_canonical.items():
        if SECRET_IDENTIFIER_PATTERN.search(str(source_column)) or SECRET_IDENTIFIER_PATTERN.search(str(canonical_field)):
            violations.append(
                OnboardingViolation(
                    "field_mapping_secret_like_column_or_field",
                    "field mapping cannot normalize secret-like columns or field identifiers",
                    field="source_to_canonical",
                    ref=str(source_column),
                )
            )
        if not _present(canonical_field):
            violations.append(
                OnboardingViolation(
                    "field_mapping_empty_canonical_field",
                    "field mapping canonical field cannot be empty",
                    field="source_to_canonical",
                    ref=str(source_column),
                )
            )
        elif not CANONICAL_FIELD_PATTERN.match(str(canonical_field)):
            violations.append(
                OnboardingViolation(
                    "field_mapping_invalid_canonical_field",
                    "field mapping canonical field must be a stable identifier",
                    field="source_to_canonical",
                    ref=str(canonical_field),
                )
            )
        canonical_targets.append(str(canonical_field))

    duplicate_targets = sorted({target for target in canonical_targets if canonical_targets.count(target) > 1})
    if duplicate_targets:
        violations.append(
            OnboardingViolation(
                "field_mapping_duplicate_canonical_field",
                "field mapping cannot map multiple source columns to the same canonical field",
                field="source_to_canonical",
                ref=",".join(duplicate_targets),
            )
        )

    event_time_column = str(record.event_time_column or "").strip()
    if event_time_column:
        if event_time_column not in schema_columns:
            violations.append(
                OnboardingViolation(
                    "field_mapping_event_time_unknown",
                    "field mapping event_time_column must be observed by the schema probe",
                    field="event_time_column",
                    ref=event_time_column,
                )
            )
        if event_time_column not in mapped_columns:
            violations.append(
                OnboardingViolation(
                    "field_mapping_event_time_unmapped",
                    "field mapping event_time_column must have a canonical mapping",
                    field="event_time_column",
                    ref=event_time_column,
                )
            )
    for optional_field in ("known_at_column", "effective_at_column", "symbol_column"):
        value = str(getattr(record, optional_field) or "").strip()
        if value and value not in schema_columns:
            violations.append(
                OnboardingViolation(
                    f"field_mapping_{optional_field}_unknown",
                    f"field mapping {optional_field} must be observed by the schema probe",
                    field=optional_field,
                    ref=value,
                )
            )

    if not _present(record.mapping_hash):
        violations.append(
            OnboardingViolation(
                "field_mapping_missing_hash",
                "field mapping requires a deterministic mapping_hash",
                field="mapping_hash",
                ref=record.mapping_ref,
            )
        )
    elif record.mapping_hash != data_connector_field_mapping_hash(record):
        violations.append(
            OnboardingViolation(
                "field_mapping_hash_mismatch",
                "field mapping_hash must match mapping content",
                field="mapping_hash",
                ref=record.mapping_ref,
            )
        )

    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def data_connector_pit_bitemporal_rule_hash(record: DataConnectorPITBitemporalRuleRecord) -> str:
    return "pit_bitemporal_rule:" + _content_hash(
        {
            "rule_ref": record.rule_ref,
            "skill_id": record.skill_id,
            "source_ref": record.source_ref,
            "field_mapping_ref": record.field_mapping_ref,
            "schema_probe_ref": record.schema_probe_ref,
            "event_time_column": record.event_time_column,
            "known_at_column": record.known_at_column,
            "effective_at_column": record.effective_at_column,
            "known_at_policy": record.known_at_policy,
            "effective_at_policy": record.effective_at_policy,
            "asof_join_policy": record.asof_join_policy,
            "timezone": record.timezone,
            "calendar_ref": record.calendar_ref,
            "lookahead_guard_ref": record.lookahead_guard_ref,
            "monotonicity_check_ref": record.monotonicity_check_ref,
            "restatement_policy": record.restatement_policy,
            "evidence_refs": record.evidence_refs,
        }
    )


def validate_data_connector_pit_bitemporal_rule(
    record: DataConnectorPITBitemporalRuleRecord,
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    field_mapping: DataConnectorFieldMappingRecord,
    schema_probe: DataConnectorSchemaProbeRecord,
) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []

    for field_name in (
        "rule_ref",
        "skill_id",
        "source_ref",
        "field_mapping_ref",
        "schema_probe_ref",
        "generated_at",
        "event_time_column",
        "known_at_policy",
        "effective_at_policy",
        "asof_join_policy",
        "timezone",
        "lookahead_guard_ref",
        "restatement_policy",
    ):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.rule_ref)

    if contains_plaintext_secret(_json_value(record)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_pit_bitemporal_rule",
                "PIT/bitemporal rule metadata cannot contain plaintext credential material",
                field="pit_bitemporal_rule",
                ref=record.rule_ref,
            )
        )
    if record.skill_id != skill.skill_id:
        violations.append(
            OnboardingViolation(
                "pit_rule_skill_mismatch",
                "PIT/bitemporal rule skill_id must match the recorded IngestionSkill",
                field="skill_id",
                ref=record.rule_ref,
            )
        )
    if record.source_ref != skill.source_ref or record.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "pit_rule_source_mismatch",
                "PIT/bitemporal rule source_ref must match the IngestionSkill and DataSourceAsset",
                field="source_ref",
                ref=record.rule_ref,
            )
        )
    if record.rule_ref != skill.pit_bitemporal_rules_ref:
        violations.append(
            OnboardingViolation(
                "pit_rule_ref_mismatch",
                "PIT/bitemporal rule_ref must resolve the IngestionSkill pit_bitemporal_rules_ref",
                field="rule_ref",
                ref=record.rule_ref,
            )
        )
    if record.field_mapping_ref != field_mapping.mapping_ref:
        violations.append(
            OnboardingViolation(
                "pit_rule_field_mapping_mismatch",
                "PIT/bitemporal rule must bind the recorded field mapping",
                field="field_mapping_ref",
                ref=record.rule_ref,
            )
        )
    if record.schema_probe_ref != schema_probe.probe_ref or record.schema_probe_ref != field_mapping.schema_probe_ref:
        violations.append(
            OnboardingViolation(
                "pit_rule_schema_probe_mismatch",
                "PIT/bitemporal rule must bind the schema probe used by the field mapping",
                field="schema_probe_ref",
                ref=record.rule_ref,
            )
        )
    if field_mapping.skill_id != skill.skill_id or field_mapping.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "pit_rule_field_mapping_wrong_scope",
                "PIT/bitemporal rule field mapping must belong to the same IngestionSkill and DataSourceAsset",
                field="field_mapping_ref",
                ref=record.field_mapping_ref,
            )
        )

    schema_columns = {str(column) for column in schema_probe.columns}
    mapped_columns = {str(column) for column in field_mapping.source_to_canonical}
    event_time_column = str(record.event_time_column or "").strip()
    if event_time_column:
        if event_time_column not in schema_columns:
            violations.append(
                OnboardingViolation(
                    "pit_rule_event_time_unknown",
                    "PIT/bitemporal event_time_column must be observed by the schema probe",
                    field="event_time_column",
                    ref=event_time_column,
                )
            )
        if event_time_column != field_mapping.event_time_column or event_time_column not in mapped_columns:
            violations.append(
                OnboardingViolation(
                    "pit_rule_event_time_not_field_mapping_axis",
                    "PIT/bitemporal event_time_column must match the field mapping event time axis",
                    field="event_time_column",
                    ref=event_time_column,
                )
            )

    for optional_field in ("known_at_column", "effective_at_column"):
        value = str(getattr(record, optional_field) or "").strip()
        if value and value not in schema_columns:
            violations.append(
                OnboardingViolation(
                    f"pit_rule_{optional_field}_unknown",
                    f"PIT/bitemporal {optional_field} must be observed by the schema probe",
                    field=optional_field,
                    ref=value,
                )
            )
    if record.known_at_column and field_mapping.known_at_column and record.known_at_column != field_mapping.known_at_column:
        violations.append(
            OnboardingViolation(
                "pit_rule_known_at_mismatch",
                "PIT/bitemporal known_at_column must match the field mapping known_at candidate when one is recorded",
                field="known_at_column",
                ref=str(record.known_at_column),
            )
        )
    if record.effective_at_column and field_mapping.effective_at_column and record.effective_at_column != field_mapping.effective_at_column:
        violations.append(
            OnboardingViolation(
                "pit_rule_effective_at_mismatch",
                "PIT/bitemporal effective_at_column must match the field mapping effective_at candidate when one is recorded",
                field="effective_at_column",
                ref=str(record.effective_at_column),
            )
        )

    known_policy = str(record.known_at_policy or "").lower()
    effective_policy = str(record.effective_at_policy or "").lower()
    asof_policy = str(record.asof_join_policy or "").lower()
    if not record.known_at_column and known_policy not in {"connector_fetched_at", "ingestion_time", "source_publish_time"}:
        violations.append(
            OnboardingViolation(
                "pit_rule_known_at_policy_missing_source",
                "PIT/bitemporal rule without known_at_column must use an explicit connector/source publish time policy",
                field="known_at_policy",
                ref=record.rule_ref,
            )
        )
    if not record.effective_at_column and effective_policy not in {"event_time", "bar_close", "coverage_window"}:
        violations.append(
            OnboardingViolation(
                "pit_rule_effective_at_policy_missing_source",
                "PIT/bitemporal rule without effective_at_column must state how effective_at is derived",
                field="effective_at_policy",
                ref=record.rule_ref,
            )
        )
    if asof_policy in {"", "none", "latest", "current_snapshot", "full_history"} or "known_at" not in asof_policy:
        violations.append(
            OnboardingViolation(
                "pit_rule_asof_policy_not_pit_safe",
                "PIT/bitemporal asof_join_policy must constrain known_at before decision time",
                field="asof_join_policy",
                ref=record.rule_ref,
            )
        )
    if not _present(record.rule_hash):
        violations.append(
            OnboardingViolation(
                "pit_rule_missing_hash",
                "PIT/bitemporal rule requires a deterministic rule_hash",
                field="rule_hash",
                ref=record.rule_ref,
            )
        )
    elif record.rule_hash != data_connector_pit_bitemporal_rule_hash(record):
        violations.append(
            OnboardingViolation(
                "pit_rule_hash_mismatch",
                "PIT/bitemporal rule_hash must match rule content",
                field="rule_hash",
                ref=record.rule_ref,
            )
        )
    required_evidence = {record.field_mapping_ref, record.schema_probe_ref}
    if not required_evidence.issubset({str(ref) for ref in record.evidence_refs}):
        violations.append(
            OnboardingViolation(
                "pit_rule_missing_evidence_refs",
                "PIT/bitemporal rule evidence_refs must include field_mapping_ref and schema_probe_ref",
                field="evidence_refs",
                ref=record.rule_ref,
            )
        )

    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_llm_provider(provider: LLMProviderRecord) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    if provider.plaintext_credential or contains_plaintext_secret(provider.plaintext_credential):
        violations.append(
            OnboardingViolation(
                "plaintext_llm_provider_credential",
                "LLM provider credential must be stored through Settings/Secrets",
                field="plaintext_credential",
                ref=provider.provider_id,
            )
        )
    for ref in provider.auth_refs:
        if not _is_secret_or_token_ref(str(ref)):
            violations.append(
                OnboardingViolation(
                    "llm_auth_ref_not_settings_managed",
                    "LLM provider auth_refs must be SecretRef or TokenRef",
                    field="auth_refs",
                    ref=provider.provider_id,
                )
            )
    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_llm_provider_health_snapshot(snapshot: LLMProviderHealthSnapshotRecord) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    required_fields = {
        "snapshot_ref": snapshot.snapshot_ref,
        "provider_id": snapshot.provider_id,
        "auth_ref": snapshot.auth_ref,
        "checked_at": snapshot.checked_at,
        "checker_ref": snapshot.checker_ref,
        "response_hash": snapshot.response_hash,
    }
    for field, value in required_fields.items():
        if not _present(value):
            violations.append(
                OnboardingViolation(
                    f"missing_{field}",
                    f"LLMProviderHealthSnapshot requires {field}",
                    field=field,
                    ref=snapshot.snapshot_ref,
                )
            )
    if not _is_secret_or_token_ref(snapshot.auth_ref):
        violations.append(
            OnboardingViolation(
                "llm_provider_health_auth_ref_not_settings_managed",
                "LLMProviderHealthSnapshot auth_ref must be a Settings-managed SecretRef or TokenRef",
                field="auth_ref",
                ref=snapshot.snapshot_ref,
            )
        )
    if str(snapshot.health_status or "").strip().lower() not in {"ok", "degraded", "down", "unknown"}:
        violations.append(
            OnboardingViolation(
                "invalid_llm_provider_health_status",
                "LLMProviderHealthSnapshot health_status must be ok/degraded/down/unknown",
                field="health_status",
                ref=snapshot.snapshot_ref,
            )
        )
    if str(snapshot.quota_status or "").strip().lower() not in {"ok", "limited", "exhausted", "unknown"}:
        violations.append(
            OnboardingViolation(
                "invalid_llm_provider_quota_status",
                "LLMProviderHealthSnapshot quota_status must be ok/limited/exhausted/unknown",
                field="quota_status",
                ref=snapshot.snapshot_ref,
            )
        )
    if int(snapshot.latency_ms) < 0:
        violations.append(
            OnboardingViolation(
                "invalid_llm_provider_latency",
                "LLMProviderHealthSnapshot latency_ms cannot be negative",
                field="latency_ms",
                ref=snapshot.snapshot_ref,
            )
        )
    if contains_plaintext_secret(_json_value(snapshot)):
        violations.append(
            OnboardingViolation(
                "plaintext_llm_provider_health_payload",
                "LLMProviderHealthSnapshot cannot contain plaintext credentials",
                field="payload",
                ref=snapshot.snapshot_ref,
            )
        )
    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_credential_pool(pool: LLMCredentialPoolRecord) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    if not pool.auth_refs:
        violations.append(
            OnboardingViolation(
                "missing_pool_auth_refs",
                "LLMCredentialPool requires Settings-managed auth_refs",
                field="auth_refs",
                ref=pool.pool_id,
            )
        )
    for ref in pool.auth_refs:
        if not _is_secret_or_token_ref(str(ref)):
            violations.append(
                OnboardingViolation(
                    "pool_auth_ref_not_settings_managed",
                    "LLMCredentialPool auth_refs must be SecretRef or TokenRef",
                    field="auth_refs",
                    ref=pool.pool_id,
                )
            )
    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_model_routing_policy(policy: ModelRoutingPolicyRecord) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    if not policy.allowed_models:
        violations.append(
            OnboardingViolation(
                "missing_allowed_models",
                "ModelRoutingPolicy requires allowed_models",
                field="allowed_models",
                ref=policy.routing_policy_id,
            )
        )
    if not _present(policy.credential_pool_ref):
        violations.append(
            OnboardingViolation(
                "missing_credential_pool_ref",
                "ModelRoutingPolicy requires credential_pool_ref",
                field="credential_pool_ref",
                ref=policy.routing_policy_id,
            )
        )
    if not _present(policy.replay_requirement):
        violations.append(
            OnboardingViolation(
                "missing_replay_requirement",
                "ModelRoutingPolicy requires replay_requirement",
                field="replay_requirement",
                ref=policy.routing_policy_id,
            )
        )
    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def validate_llm_gateway_call(
    request: LLMGatewayCallRequest,
    *,
    policy: ModelRoutingPolicyRecord,
    credential_pool: LLMCredentialPoolRecord,
    secrets: dict[str, SecretRefRecord] | None = None,
) -> OnboardingDecision:
    violations: list[OnboardingViolation] = []
    violations.extend(validate_model_routing_policy(policy).violations)
    violations.extend(validate_credential_pool(credential_pool).violations)

    if not request.via_gateway:
        violations.append(
            OnboardingViolation(
                "role_agent_bypassed_llm_gateway",
                "role agent LLM calls must go through LLM Gateway",
                field="via_gateway",
                ref=request.role_agent,
            )
        )
    if request.plaintext_credential or contains_plaintext_secret(request.plaintext_credential):
        violations.append(
            OnboardingViolation(
                "plaintext_llm_call_credential",
                "LLM call request must use auth_ref, not plaintext credential",
                field="plaintext_credential",
                ref=request.role_agent,
            )
        )
    if contains_plaintext_secret(request.payload_preview):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_llm_payload",
                "LLM payload preview appears to contain plaintext secret material",
                field="payload_preview",
                ref=request.role_agent,
            )
        )
    if not _is_secret_or_token_ref(request.auth_ref):
        violations.append(
            OnboardingViolation(
                "llm_call_auth_ref_not_settings_managed",
                "LLM call auth_ref must be SecretRef or TokenRef",
                field="auth_ref",
                ref=request.role_agent,
            )
        )
    if request.auth_ref in credential_pool.revoked_refs:
        violations.append(
            OnboardingViolation(
                "llm_call_uses_revoked_auth_ref",
                "LLM call cannot use a revoked auth_ref",
                field="auth_ref",
                ref=request.auth_ref,
            )
        )
    if secrets is not None:
        secret_record = secrets.get(request.auth_ref)
        if secret_record is None:
            violations.append(
                OnboardingViolation(
                    "llm_call_missing_secret_ref_record",
                    "LLM call auth_ref must resolve to Settings/Secrets metadata",
                    field="auth_ref",
                    ref=request.auth_ref,
                )
            )
        elif _ref_value(secret_record.status) == SecretRefStatus.REVOKED.value:
            violations.append(
                OnboardingViolation(
                    "llm_call_uses_revoked_secret_ref",
                    "LLM call cannot use a revoked SecretRef",
                    field="auth_ref",
                    ref=request.auth_ref,
                )
            )
    if request.provider_id not in policy.allowed_providers:
        violations.append(
            OnboardingViolation(
                "provider_not_allowed_by_policy",
                "LLM call provider is not allowed by routing policy",
                field="provider_id",
                ref=request.provider_id,
            )
        )
    if request.model_id not in policy.allowed_models:
        violations.append(
            OnboardingViolation(
                "model_not_allowed_by_policy",
                "LLM call model is not allowed by routing policy",
                field="model_id",
                ref=request.model_id,
            )
        )
    if request.credential_pool_ref != policy.credential_pool_ref or request.credential_pool_ref != credential_pool.pool_id:
        violations.append(
            OnboardingViolation(
                "credential_pool_mismatch",
                "LLM call credential pool must match the routing policy and pool record",
                field="credential_pool_ref",
                ref=request.credential_pool_ref,
            )
        )
    if request.auth_ref not in credential_pool.auth_refs:
        violations.append(
            OnboardingViolation(
                "auth_ref_not_in_pool",
                "LLM call auth_ref must belong to the selected credential pool",
                field="auth_ref",
                ref=request.auth_ref,
            )
        )
    if str(policy.replay_requirement or "").lower() in {"required", "record", "record_replay"} and not _present(
        request.replay_record_ref
    ):
        violations.append(
            OnboardingViolation(
                "missing_llm_replay_record",
                "routing policy requires an LLM replay/record reference",
                field="replay_record_ref",
                ref=request.role_agent,
            )
        )

    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: OnboardingDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "settings record rejected"


def _event_row(event_type: str, field_name: str, record: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_type": event_type,
        field_name: _json_value(record),
    }


_EVENT_RECORD_TYPES: dict[str, tuple[str, type[Any]]] = {
    "secret_ref_recorded": ("secret_ref", SecretRefRecord),
    "data_source_asset_recorded": ("data_source_asset", DataSourceAssetRecord),
    "ingestion_skill_recorded": ("ingestion_skill", IngestionSkillRecord),
    "data_connector_check_recorded": ("data_connector_check", DataConnectorConnectionCheckRecord),
    "data_connector_schema_probe_recorded": ("data_connector_schema_probe", DataConnectorSchemaProbeRecord),
    "data_connector_field_mapping_recorded": ("data_connector_field_mapping", DataConnectorFieldMappingRecord),
    "data_connector_pit_bitemporal_rule_recorded": (
        "data_connector_pit_bitemporal_rule",
        DataConnectorPITBitemporalRuleRecord,
    ),
    "llm_provider_recorded": ("llm_provider", LLMProviderRecord),
    "llm_provider_health_snapshot_recorded": ("llm_provider_health_snapshot", LLMProviderHealthSnapshotRecord),
    "llm_credential_pool_recorded": ("credential_pool", LLMCredentialPoolRecord),
    "model_routing_policy_recorded": ("routing_policy", ModelRoutingPolicyRecord),
}


class PersistentOnboardingRegistry:
    """Append-only metadata registry for Settings/Secrets and LLM routing records.

    This store never contains plaintext credentials. It records only SecretRef /
    TokenRef metadata and references that role-agent code can validate before it
    calls the LLM Gateway.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_refs: dict[str, SecretRefRecord] = {}
        self._data_sources: dict[str, DataSourceAssetRecord] = {}
        self._ingestion_skills: dict[str, IngestionSkillRecord] = {}
        self._data_connector_checks: dict[str, DataConnectorConnectionCheckRecord] = {}
        self._data_connector_schema_probes: dict[str, DataConnectorSchemaProbeRecord] = {}
        self._data_connector_field_mappings: dict[str, DataConnectorFieldMappingRecord] = {}
        self._data_connector_pit_bitemporal_rules: dict[str, DataConnectorPITBitemporalRuleRecord] = {}
        self._llm_providers: dict[str, LLMProviderRecord] = {}
        self._llm_provider_health_snapshots: dict[str, LLMProviderHealthSnapshotRecord] = {}
        self._credential_pools: dict[str, LLMCredentialPoolRecord] = {}
        self._routing_policies: dict[str, ModelRoutingPolicyRecord] = {}
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
                except Exception as exc:  # noqa: BLE001 - bad settings history must block startup.
                    raise ValueError(f"invalid persisted onboarding settings row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported onboarding settings schema_version")
        event_type = str(row.get("event_type") or "")
        spec = _EVENT_RECORD_TYPES.get(event_type)
        if spec is None:
            raise ValueError(f"unknown onboarding settings event_type={event_type!r}")
        field_name, record_type = spec
        raw = row.get(field_name)
        if not isinstance(raw, dict):
            raise ValueError(f"onboarding settings event missing {field_name}")
        record = record_type(**raw)
        if isinstance(record, SecretRefRecord):
            self._record_secret_ref(record, persist=persist)
        elif isinstance(record, DataSourceAssetRecord):
            self._record_data_source_asset(record, persist=persist)
        elif isinstance(record, IngestionSkillRecord):
            self._record_ingestion_skill(record, persist=persist)
        elif isinstance(record, DataConnectorConnectionCheckRecord):
            self._record_data_connector_check(record, persist=persist)
        elif isinstance(record, DataConnectorSchemaProbeRecord):
            self._record_data_connector_schema_probe(record, persist=persist)
        elif isinstance(record, DataConnectorFieldMappingRecord):
            self._record_data_connector_field_mapping(record, persist=persist)
        elif isinstance(record, DataConnectorPITBitemporalRuleRecord):
            self._record_data_connector_pit_bitemporal_rule(record, persist=persist)
        elif isinstance(record, LLMProviderRecord):
            self._record_llm_provider(record, persist=persist)
        elif isinstance(record, LLMProviderHealthSnapshotRecord):
            self._record_llm_provider_health_snapshot(record, persist=persist)
        elif isinstance(record, LLMCredentialPoolRecord):
            self._record_credential_pool(record, persist=persist)
        elif isinstance(record, ModelRoutingPolicyRecord):
            self._record_routing_policy(record, persist=persist)
        else:
            raise ValueError(f"unsupported onboarding settings record type {type(record).__name__}")

    def record_secret_ref(self, record: SecretRefRecord) -> SecretRefRecord:
        return self._record_secret_ref(record, persist=True)

    def _record_secret_ref(self, record: SecretRefRecord, *, persist: bool) -> SecretRefRecord:
        decision = validate_secret_ref(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._secret_refs[record.secret_ref] = record
        if persist:
            self._append_event(_event_row("secret_ref_recorded", "secret_ref", record))
        return record

    def record_data_source_asset(self, record: DataSourceAssetRecord) -> DataSourceAssetRecord:
        return self._record_data_source_asset(record, persist=True)

    def _record_data_source_asset(self, record: DataSourceAssetRecord, *, persist: bool) -> DataSourceAssetRecord:
        decision = validate_data_source_asset(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._data_sources[record.source_ref] = record
        if persist:
            self._append_event(_event_row("data_source_asset_recorded", "data_source_asset", record))
        return record

    def record_ingestion_skill(self, record: IngestionSkillRecord) -> IngestionSkillRecord:
        return self._record_ingestion_skill(record, persist=True)

    def _record_ingestion_skill(self, record: IngestionSkillRecord, *, persist: bool) -> IngestionSkillRecord:
        if record.source_ref not in self._data_sources:
            raise ValueError(f"IngestionSkill source_ref {record.source_ref!r} is not recorded")
        decision = validate_ingestion_skill_run(record, secrets=self._secret_refs)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._ingestion_skills[record.skill_id] = record
        if persist:
            self._append_event(_event_row("ingestion_skill_recorded", "ingestion_skill", record))
        return record

    def record_data_connector_check(
        self,
        record: DataConnectorConnectionCheckRecord,
    ) -> DataConnectorConnectionCheckRecord:
        return self._record_data_connector_check(record, persist=True)

    def _record_data_connector_check(
        self,
        record: DataConnectorConnectionCheckRecord,
        *,
        persist: bool,
    ) -> DataConnectorConnectionCheckRecord:
        try:
            skill = self._ingestion_skills[record.skill_id]
        except KeyError as exc:
            raise ValueError(f"connector check skill_id {record.skill_id!r} is not recorded") from exc
        try:
            source = self._data_sources[record.source_ref]
        except KeyError as exc:
            raise ValueError(f"connector check source_ref {record.source_ref!r} is not recorded") from exc
        decision = validate_data_connector_connection_check(
            record,
            skill=skill,
            source=source,
            secrets=self._secret_refs,
        )
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._data_connector_checks[record.check_ref] = record
        if persist:
            self._append_event(_event_row("data_connector_check_recorded", "data_connector_check", record))
        return record

    def record_data_connector_schema_probe(
        self,
        record: DataConnectorSchemaProbeRecord,
    ) -> DataConnectorSchemaProbeRecord:
        return self._record_data_connector_schema_probe(record, persist=True)

    def _record_data_connector_schema_probe(
        self,
        record: DataConnectorSchemaProbeRecord,
        *,
        persist: bool,
    ) -> DataConnectorSchemaProbeRecord:
        try:
            skill = self._ingestion_skills[record.skill_id]
        except KeyError as exc:
            raise ValueError(f"schema probe skill_id {record.skill_id!r} is not recorded") from exc
        try:
            source = self._data_sources[record.source_ref]
        except KeyError as exc:
            raise ValueError(f"schema probe source_ref {record.source_ref!r} is not recorded") from exc
        try:
            connector_check = self._data_connector_checks[record.connector_check_ref]
        except KeyError as exc:
            raise ValueError(f"schema probe connector_check_ref {record.connector_check_ref!r} is not recorded") from exc
        decision = validate_data_connector_schema_probe(
            record,
            skill=skill,
            source=source,
            connector_check=connector_check,
        )
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._data_connector_schema_probes[record.probe_ref] = record
        if persist:
            self._append_event(_event_row("data_connector_schema_probe_recorded", "data_connector_schema_probe", record))
        return record

    def record_data_connector_field_mapping(
        self,
        record: DataConnectorFieldMappingRecord,
    ) -> DataConnectorFieldMappingRecord:
        return self._record_data_connector_field_mapping(record, persist=True)

    def _record_data_connector_field_mapping(
        self,
        record: DataConnectorFieldMappingRecord,
        *,
        persist: bool,
    ) -> DataConnectorFieldMappingRecord:
        try:
            skill = self._ingestion_skills[record.skill_id]
        except KeyError as exc:
            raise ValueError(f"field mapping skill_id {record.skill_id!r} is not recorded") from exc
        try:
            source = self._data_sources[record.source_ref]
        except KeyError as exc:
            raise ValueError(f"field mapping source_ref {record.source_ref!r} is not recorded") from exc
        try:
            schema_probe = self._data_connector_schema_probes[record.schema_probe_ref]
        except KeyError as exc:
            raise ValueError(f"field mapping schema_probe_ref {record.schema_probe_ref!r} is not recorded") from exc
        decision = validate_data_connector_field_mapping(
            record,
            skill=skill,
            source=source,
            schema_probe=schema_probe,
        )
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._data_connector_field_mappings[record.mapping_ref] = record
        if persist:
            self._append_event(
                _event_row("data_connector_field_mapping_recorded", "data_connector_field_mapping", record)
            )
        return record

    def record_data_connector_pit_bitemporal_rule(
        self,
        record: DataConnectorPITBitemporalRuleRecord,
    ) -> DataConnectorPITBitemporalRuleRecord:
        return self._record_data_connector_pit_bitemporal_rule(record, persist=True)

    def _record_data_connector_pit_bitemporal_rule(
        self,
        record: DataConnectorPITBitemporalRuleRecord,
        *,
        persist: bool,
    ) -> DataConnectorPITBitemporalRuleRecord:
        try:
            skill = self._ingestion_skills[record.skill_id]
        except KeyError as exc:
            raise ValueError(f"PIT/bitemporal rule skill_id {record.skill_id!r} is not recorded") from exc
        try:
            source = self._data_sources[record.source_ref]
        except KeyError as exc:
            raise ValueError(f"PIT/bitemporal rule source_ref {record.source_ref!r} is not recorded") from exc
        try:
            field_mapping = self._data_connector_field_mappings[record.field_mapping_ref]
        except KeyError as exc:
            raise ValueError(f"PIT/bitemporal rule field_mapping_ref {record.field_mapping_ref!r} is not recorded") from exc
        try:
            schema_probe = self._data_connector_schema_probes[record.schema_probe_ref]
        except KeyError as exc:
            raise ValueError(f"PIT/bitemporal rule schema_probe_ref {record.schema_probe_ref!r} is not recorded") from exc
        decision = validate_data_connector_pit_bitemporal_rule(
            record,
            skill=skill,
            source=source,
            field_mapping=field_mapping,
            schema_probe=schema_probe,
        )
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._data_connector_pit_bitemporal_rules[record.rule_ref] = record
        if persist:
            self._append_event(
                _event_row(
                    "data_connector_pit_bitemporal_rule_recorded",
                    "data_connector_pit_bitemporal_rule",
                    record,
                )
            )
        return record

    def record_llm_provider(self, record: LLMProviderRecord) -> LLMProviderRecord:
        return self._record_llm_provider(record, persist=True)

    def _record_llm_provider(self, record: LLMProviderRecord, *, persist: bool) -> LLMProviderRecord:
        decision = validate_llm_provider(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        for ref in record.auth_refs:
            if ref not in self._secret_refs:
                raise ValueError(f"LLM provider auth_ref {ref!r} is not recorded")
        self._llm_providers[record.provider_id] = record
        if persist:
            self._append_event(_event_row("llm_provider_recorded", "llm_provider", record))
        return record

    def record_llm_provider_health_snapshot(
        self,
        record: LLMProviderHealthSnapshotRecord,
    ) -> LLMProviderHealthSnapshotRecord:
        return self._record_llm_provider_health_snapshot(record, persist=True)

    def _record_llm_provider_health_snapshot(
        self,
        record: LLMProviderHealthSnapshotRecord,
        *,
        persist: bool,
    ) -> LLMProviderHealthSnapshotRecord:
        decision = validate_llm_provider_health_snapshot(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        provider = self._llm_providers.get(record.provider_id)
        if provider is None:
            raise ValueError(f"LLMProviderHealthSnapshot provider_id {record.provider_id!r} is not recorded")
        if record.auth_ref not in provider.auth_refs:
            raise ValueError(f"LLMProviderHealthSnapshot auth_ref {record.auth_ref!r} is not recorded for provider")
        secret_ref = self._secret_refs.get(record.auth_ref)
        if secret_ref is None:
            raise ValueError(f"LLMProviderHealthSnapshot auth_ref {record.auth_ref!r} is not recorded")
        if secret_ref.status == SecretRefStatus.REVOKED or str(secret_ref.status) == SecretRefStatus.REVOKED.value:
            raise ValueError(f"LLMProviderHealthSnapshot auth_ref {record.auth_ref!r} is revoked")
        self._llm_provider_health_snapshots[record.snapshot_ref] = record
        if persist:
            self._append_event(
                _event_row(
                    "llm_provider_health_snapshot_recorded",
                    "llm_provider_health_snapshot",
                    record,
                )
            )
        return record

    def record_credential_pool(self, record: LLMCredentialPoolRecord) -> LLMCredentialPoolRecord:
        return self._record_credential_pool(record, persist=True)

    def _record_credential_pool(self, record: LLMCredentialPoolRecord, *, persist: bool) -> LLMCredentialPoolRecord:
        decision = validate_credential_pool(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        if record.provider_id not in self._llm_providers:
            raise ValueError(f"LLM credential pool provider_id {record.provider_id!r} is not recorded")
        for ref in record.auth_refs:
            if ref not in self._secret_refs:
                raise ValueError(f"LLM credential pool auth_ref {ref!r} is not recorded")
        self._credential_pools[record.pool_id] = record
        if persist:
            self._append_event(_event_row("llm_credential_pool_recorded", "credential_pool", record))
        return record

    def record_routing_policy(self, record: ModelRoutingPolicyRecord) -> ModelRoutingPolicyRecord:
        return self._record_routing_policy(record, persist=True)

    def _record_routing_policy(self, record: ModelRoutingPolicyRecord, *, persist: bool) -> ModelRoutingPolicyRecord:
        decision = validate_model_routing_policy(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        for provider_id in record.allowed_providers:
            if provider_id not in self._llm_providers:
                raise ValueError(f"ModelRoutingPolicy provider {provider_id!r} is not recorded")
        if record.credential_pool_ref not in self._credential_pools:
            raise ValueError(f"ModelRoutingPolicy credential_pool_ref {record.credential_pool_ref!r} is not recorded")
        self._routing_policies[record.routing_policy_id] = record
        if persist:
            self._append_event(_event_row("model_routing_policy_recorded", "routing_policy", record))
        return record

    def secret_ref(self, ref: str) -> SecretRefRecord:
        return self._secret_refs[ref]

    def data_source(self, source_ref: str) -> DataSourceAssetRecord:
        return self._data_sources[source_ref]

    def ingestion_skill(self, skill_id: str) -> IngestionSkillRecord:
        return self._ingestion_skills[skill_id]

    def data_connector_check(self, check_ref: str) -> DataConnectorConnectionCheckRecord:
        return self._data_connector_checks[check_ref]

    def data_connector_schema_probe(self, probe_ref: str) -> DataConnectorSchemaProbeRecord:
        return self._data_connector_schema_probes[probe_ref]

    def data_connector_field_mapping(self, mapping_ref: str) -> DataConnectorFieldMappingRecord:
        return self._data_connector_field_mappings[mapping_ref]

    def data_connector_pit_bitemporal_rule(self, rule_ref: str) -> DataConnectorPITBitemporalRuleRecord:
        return self._data_connector_pit_bitemporal_rules[rule_ref]

    def llm_provider(self, provider_id: str) -> LLMProviderRecord:
        return self._llm_providers[provider_id]

    def llm_provider_health_snapshot(self, snapshot_ref: str) -> LLMProviderHealthSnapshotRecord:
        return self._llm_provider_health_snapshots[snapshot_ref]

    def credential_pool(self, pool_id: str) -> LLMCredentialPoolRecord:
        return self._credential_pools[pool_id]

    def routing_policy(self, routing_policy_id: str) -> ModelRoutingPolicyRecord:
        return self._routing_policies[routing_policy_id]

    def secret_refs(self) -> list[SecretRefRecord]:
        return list(self._secret_refs.values())

    def data_sources(self) -> list[DataSourceAssetRecord]:
        return list(self._data_sources.values())

    def ingestion_skills(self) -> list[IngestionSkillRecord]:
        return list(self._ingestion_skills.values())

    def data_connector_checks(self) -> list[DataConnectorConnectionCheckRecord]:
        return list(self._data_connector_checks.values())

    def data_connector_schema_probes(self) -> list[DataConnectorSchemaProbeRecord]:
        return list(self._data_connector_schema_probes.values())

    def data_connector_field_mappings(self) -> list[DataConnectorFieldMappingRecord]:
        return list(self._data_connector_field_mappings.values())

    def data_connector_pit_bitemporal_rules(self) -> list[DataConnectorPITBitemporalRuleRecord]:
        return list(self._data_connector_pit_bitemporal_rules.values())

    def llm_providers(self) -> list[LLMProviderRecord]:
        return list(self._llm_providers.values())

    def llm_provider_health_snapshots(self, provider_id: str | None = None) -> list[LLMProviderHealthSnapshotRecord]:
        snapshots = list(self._llm_provider_health_snapshots.values())
        if provider_id is not None:
            return [record for record in snapshots if record.provider_id == provider_id]
        return snapshots

    def credential_pools(self) -> list[LLMCredentialPoolRecord]:
        return list(self._credential_pools.values())

    def routing_policies(self) -> list[ModelRoutingPolicyRecord]:
        return list(self._routing_policies.values())


__all__ = [
    "DataConnectorConnectionCheckRecord",
    "DataConnectorFieldMappingRecord",
    "DataConnectorPITBitemporalRuleRecord",
    "DataConnectorSchemaProbeRecord",
    "DataSourceAssetRecord",
    "IngestionLifecycleState",
    "IngestionSkillRecord",
    "LLMCredentialPoolRecord",
    "LLMProviderHealthSnapshotRecord",
    "LLMGatewayCallRequest",
    "LLMProviderRecord",
    "ModelRoutingPolicyRecord",
    "OnboardingDecision",
    "OnboardingViolation",
    "OnboardingWarning",
    "PersistentOnboardingRegistry",
    "SecretRefRecord",
    "SecretRefStatus",
    "contains_plaintext_secret",
    "data_connector_field_mapping_hash",
    "data_connector_pit_bitemporal_rule_hash",
    "ingestion_skill_allows_no_secret_connector",
    "validate_credential_pool",
    "validate_data_connector_connection_check",
    "validate_data_connector_field_mapping",
    "validate_data_connector_pit_bitemporal_rule",
    "validate_data_connector_schema_probe",
    "validate_data_source_asset",
    "validate_ingestion_skill_run",
    "validate_llm_gateway_call",
    "validate_llm_provider",
    "validate_llm_provider_health_snapshot",
    "validate_model_routing_policy",
    "validate_secret_ref",
]
