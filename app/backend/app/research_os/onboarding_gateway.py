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
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from app.cross_process_lock import acquire_exclusive_fd


SECRET_PATTERN = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]\s*['\"]?[^,\s'\"]{6,}|"
    r"password\s*[:=]\s*['\"]?[^,\s'\"]{6,}|oauth[_-]?token\s*[:=]\s*['\"]?[^,\s'\"]{6,})"
)
SECRET_IDENTIFIER_PATTERN = re.compile(r"(?i)(api[_-]?key|api[_-]?secret|secret|password|oauth|credential|private[_-]?key)")
CANONICAL_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")

_NO_SECRET_SOURCE_CONNECTOR_TYPES: dict[str, frozenset[str]] = {
    "local_file": frozenset({"local_file_no_auth"}),
    "public_api": frozenset({"public_api_no_auth"}),
    "public_csv": frozenset({"public_csv_no_auth"}),
    "public_dataset": frozenset({"public_dataset_no_auth"}),
}


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


class NoSecretDataSourcePolicyStatus(str, Enum):
    ACTIVE = "active"
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
class NoSecretDataSourcePolicyRecord:
    policy_ref: str
    source_ref: str
    source_type: str
    connector_type: str
    external_credential_required: bool
    permission_scope: str
    status: NoSecretDataSourcePolicyStatus | str
    actor_ref: str
    approved_at: str
    approval_ref: str
    evidence_refs: tuple[str, ...]
    reason: str
    revoked_at: str | None = None
    revocation_reason: str | None = None
    revocation_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(
            self,
            "revocation_evidence_refs",
            _tuple(self.revocation_evidence_refs),
        )


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
    plaintext_credential: str | None = field(default=None, repr=False)  # 防明文：LLM provider 凭据，repr/str 永不渲染（model_dump 仍暴露·功能边界）

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
    plaintext_credential: str | None = field(default=None, repr=False)  # 防明文：LLM 凭据，repr/str 永不渲染
    payload_preview: dict[str, Any] | None = field(default=None, repr=False)  # 防明文：预览可能内嵌 prompt/secret，repr/str 永不渲染


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


def validate_no_secret_data_source_policy(
    record: NoSecretDataSourcePolicyRecord,
    *,
    source: DataSourceAssetRecord,
    ingestion_skills: tuple[IngestionSkillRecord, ...] = (),
) -> OnboardingDecision:
    """Validate a narrowly-scoped public/local source no-credential approval."""

    violations: list[OnboardingViolation] = []
    for field_name in (
        "policy_ref",
        "source_ref",
        "source_type",
        "connector_type",
        "permission_scope",
        "actor_ref",
        "approved_at",
        "approval_ref",
        "reason",
    ):
        _require_text(
            violations,
            field_name=field_name,
            value=getattr(record, field_name),
            ref=record.policy_ref,
        )

    if not str(record.policy_ref or "").startswith("no_secret_policy:"):
        violations.append(
            OnboardingViolation(
                "no_secret_policy_ref_invalid",
                "NoSecretDataSourcePolicy policy_ref must use the no_secret_policy namespace",
                field="policy_ref",
                ref=record.policy_ref,
            )
        )
    if record.source_ref != source.source_ref:
        violations.append(
            OnboardingViolation(
                "no_secret_policy_source_mismatch",
                "NoSecretDataSourcePolicy source_ref must exactly match the recorded DataSourceAsset",
                field="source_ref",
                ref=record.policy_ref,
            )
        )
    allowed_connector_types = _NO_SECRET_SOURCE_CONNECTOR_TYPES.get(record.source_type)
    if allowed_connector_types is None:
        violations.append(
            OnboardingViolation(
                "no_secret_policy_source_type_not_eligible",
                "NoSecretDataSourcePolicy source_type must be explicitly public or local",
                field="source_type",
                ref=record.source_type,
            )
        )
    elif record.connector_type not in allowed_connector_types:
        violations.append(
            OnboardingViolation(
                "no_secret_policy_connector_type_not_eligible",
                "NoSecretDataSourcePolicy connector_type must be an eligible no-auth connector for source_type",
                field="connector_type",
                ref=record.connector_type,
            )
        )
    if record.external_credential_required is not False:
        violations.append(
            OnboardingViolation(
                "no_secret_policy_external_credential_required",
                "NoSecretDataSourcePolicy requires external_credential_required=False",
                field="external_credential_required",
                ref=record.policy_ref,
            )
        )
    normalized_permission_scope = str(record.permission_scope or "").strip().lower()
    if normalized_permission_scope != "read" and not normalized_permission_scope.endswith(":read"):
        violations.append(
            OnboardingViolation(
                "no_secret_policy_permission_scope_not_read_only",
                "NoSecretDataSourcePolicy permission_scope must be read-only",
                field="permission_scope",
                ref=record.permission_scope,
            )
        )
    if not record.evidence_refs or any(not _present(ref) for ref in record.evidence_refs):
        violations.append(
            OnboardingViolation(
                "no_secret_policy_missing_evidence_refs",
                "NoSecretDataSourcePolicy requires non-empty evidence_refs",
                field="evidence_refs",
                ref=record.policy_ref,
            )
        )
    if contains_plaintext_secret(_json_value(record)):
        violations.append(
            OnboardingViolation(
                "plaintext_secret_in_no_secret_policy",
                "NoSecretDataSourcePolicy metadata cannot contain credential material",
                field="no_secret_policy",
                ref=record.policy_ref,
            )
        )

    status = _ref_value(record.status)
    if status not in {
        NoSecretDataSourcePolicyStatus.ACTIVE.value,
        NoSecretDataSourcePolicyStatus.REVOKED.value,
    }:
        violations.append(
            OnboardingViolation(
                "no_secret_policy_status_invalid",
                "NoSecretDataSourcePolicy status must be active or revoked",
                field="status",
                ref=record.policy_ref,
            )
        )
    elif status == NoSecretDataSourcePolicyStatus.ACTIVE.value:
        if _present(record.revoked_at) or _present(record.revocation_reason) or record.revocation_evidence_refs:
            violations.append(
                OnboardingViolation(
                    "active_no_secret_policy_has_revocation_metadata",
                    "active NoSecretDataSourcePolicy cannot contain revocation metadata",
                    field="revoked_at",
                    ref=record.policy_ref,
                )
            )
    else:
        for field_name, value in (
            ("revoked_at", record.revoked_at),
            ("revocation_reason", record.revocation_reason),
        ):
            if not _present(value):
                violations.append(
                    OnboardingViolation(
                        f"revoked_no_secret_policy_missing_{field_name}",
                        f"revoked NoSecretDataSourcePolicy requires {field_name}",
                        field=field_name,
                        ref=record.policy_ref,
                    )
                )
        if not record.revocation_evidence_refs or any(
            not _present(ref) for ref in record.revocation_evidence_refs
        ):
            violations.append(
                OnboardingViolation(
                    "revoked_no_secret_policy_missing_evidence_refs",
                    "revoked NoSecretDataSourcePolicy requires revocation_evidence_refs",
                    field="revocation_evidence_refs",
                    ref=record.policy_ref,
                )
            )

    for skill in ingestion_skills:
        if skill.source_ref != record.source_ref:
            continue
        if skill.source_type != record.source_type:
            violations.append(
                OnboardingViolation(
                    "no_secret_policy_skill_source_type_mismatch",
                    "NoSecretDataSourcePolicy source_type must match every skill for the source",
                    field="source_type",
                    ref=skill.skill_id,
                )
            )
        if skill.permission_scope != record.permission_scope:
            violations.append(
                OnboardingViolation(
                    "no_secret_policy_skill_permission_scope_mismatch",
                    "NoSecretDataSourcePolicy permission_scope must exactly match the skill",
                    field="permission_scope",
                    ref=skill.skill_id,
                )
            )
        if skill.secret_refs or not ingestion_skill_allows_no_secret_connector(skill):
            violations.append(
                OnboardingViolation(
                    "no_secret_policy_conflicts_with_skill_secret_path",
                    "active NoSecretDataSourcePolicy cannot coexist with a credential-bearing skill path",
                    field="secret_refs",
                    ref=skill.skill_id,
                )
            )

    return OnboardingDecision(accepted=not violations, violations=tuple(violations))


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


_ONBOARDING_SCHEMA_VERSION = 2
_RECORDED_BY_TYPES = (
    DataConnectorConnectionCheckRecord,
    DataConnectorSchemaProbeRecord,
    DataConnectorFieldMappingRecord,
    DataConnectorPITBitemporalRuleRecord,
    LLMProviderHealthSnapshotRecord,
)


_EVENT_RECORD_TYPES: dict[str, tuple[type[Any], str, str]] = {
    "secret_ref_recorded": (SecretRefRecord, "secret_ref", "_secret_refs"),
    "data_source_asset_recorded": (DataSourceAssetRecord, "source_ref", "_data_sources"),
    "no_secret_data_source_policy_recorded": (
        NoSecretDataSourcePolicyRecord,
        "policy_ref",
        "_no_secret_data_source_policies",
    ),
    "ingestion_skill_recorded": (IngestionSkillRecord, "skill_id", "_ingestion_skills"),
    "data_connector_check_recorded": (
        DataConnectorConnectionCheckRecord,
        "check_ref",
        "_data_connector_checks",
    ),
    "data_connector_schema_probe_recorded": (
        DataConnectorSchemaProbeRecord,
        "probe_ref",
        "_data_connector_schema_probes",
    ),
    "data_connector_field_mapping_recorded": (
        DataConnectorFieldMappingRecord,
        "mapping_ref",
        "_data_connector_field_mappings",
    ),
    "data_connector_pit_bitemporal_rule_recorded": (
        DataConnectorPITBitemporalRuleRecord,
        "rule_ref",
        "_data_connector_pit_bitemporal_rules",
    ),
    "llm_provider_recorded": (LLMProviderRecord, "provider_id", "_llm_providers"),
    "llm_provider_health_snapshot_recorded": (
        LLMProviderHealthSnapshotRecord,
        "snapshot_ref",
        "_llm_provider_health_snapshots",
    ),
    "llm_credential_pool_recorded": (
        LLMCredentialPoolRecord,
        "pool_id",
        "_credential_pools",
    ),
    "model_routing_policy_recorded": (
        ModelRoutingPolicyRecord,
        "routing_policy_id",
        "_routing_policies",
    ),
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
        self._lock_path = self._path.with_name(f"{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._reset_state()
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return self._legacy_quarantined_count

    def _reset_state(self) -> None:
        self._secret_refs: dict[tuple[str, str], SecretRefRecord] = {}
        self._data_sources: dict[tuple[str, str], DataSourceAssetRecord] = {}
        self._no_secret_data_source_policies: dict[
            tuple[str, str], NoSecretDataSourcePolicyRecord
        ] = {}
        self._ingestion_skills: dict[tuple[str, str], IngestionSkillRecord] = {}
        self._data_connector_checks: dict[tuple[str, str], DataConnectorConnectionCheckRecord] = {}
        self._data_connector_schema_probes: dict[tuple[str, str], DataConnectorSchemaProbeRecord] = {}
        self._data_connector_field_mappings: dict[tuple[str, str], DataConnectorFieldMappingRecord] = {}
        self._data_connector_pit_bitemporal_rules: dict[
            tuple[str, str], DataConnectorPITBitemporalRuleRecord
        ] = {}
        self._llm_providers: dict[tuple[str, str], LLMProviderRecord] = {}
        self._llm_provider_health_snapshots: dict[
            tuple[str, str], LLMProviderHealthSnapshotRecord
        ] = {}
        self._credential_pools: dict[tuple[str, str], LLMCredentialPoolRecord] = {}
        self._routing_policies: dict[tuple[str, str], ModelRoutingPolicyRecord] = {}
        self._record_metadata: dict[tuple[str, str, str], tuple[int, str, dict[str, Any]]] = {}
        self._legacy_quarantined_count = 0

    @staticmethod
    def _require_owner_user_id(owner_user_id: str) -> str:
        if (
            type(owner_user_id) is not str
            or not owner_user_id
            or owner_user_id != owner_user_id.strip()
            or any(ord(char) < 32 for char in owner_user_id)
        ):
            raise ValueError("owner_user_id must be a stable non-empty exact string")
        return owner_user_id

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._reset_state()
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("onboarding settings row must be an object")
                    if row.get("schema_version") == 1:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_v2_row(row)
                except Exception as exc:  # noqa: BLE001 - bad settings history must block startup.
                    raise ValueError(
                        f"invalid persisted onboarding settings row at {self._path}:{line_no}"
                    ) from exc

    @staticmethod
    def _record_hash(row_without_hash: dict[str, Any]) -> str:
        return "sha256:" + _content_hash(row_without_hash)

    def _apply_v2_row(self, row: dict[str, Any]) -> None:
        expected_fields = {
            "schema_version",
            "owner_user_id",
            "event_type",
            "record_revision",
            "previous_record_hash",
            "record_hash",
            "payload",
        }
        if set(row) != expected_fields or row.get("schema_version") != _ONBOARDING_SCHEMA_VERSION:
            raise ValueError("unsupported or malformed onboarding settings schema_version")
        owner_user_id = self._require_owner_user_id(row.get("owner_user_id"))
        event_type = row.get("event_type")
        spec = _EVENT_RECORD_TYPES.get(event_type)
        if spec is None:
            raise ValueError(f"unknown onboarding settings event_type={event_type!r}")
        record_type, ref_field, _storage_name = spec
        payload = row.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("onboarding settings event payload must be an object")
        revision = row.get("record_revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("record_revision must be a positive exact integer")
        previous_hash = row.get("previous_record_hash")
        if previous_hash is not None and type(previous_hash) is not str:
            raise ValueError("previous_record_hash must be null or a string")
        record_hash = row.get("record_hash")
        if type(record_hash) is not str:
            raise ValueError("record_hash must be a string")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        if record_hash != self._record_hash(body):
            raise ValueError("onboarding settings record_hash mismatch")
        record = record_type(**payload)
        record_ref = _ref_value(getattr(record, ref_field))
        if not record_ref:
            raise ValueError(f"onboarding settings record missing {ref_field}")
        metadata_key = (owner_user_id, event_type, record_ref)
        previous = self._record_metadata.get(metadata_key)
        if previous is None:
            if revision != 1 or previous_hash is not None:
                raise ValueError("first onboarding record revision must be 1 with no previous hash")
        elif revision != previous[0] + 1 or previous_hash != previous[1]:
            raise ValueError("onboarding settings revision/hash chain mismatch")
        self._validate_record(owner_user_id, record)
        self._store_record(owner_user_id, event_type, record_ref, record)
        self._record_metadata[metadata_key] = (revision, record_hash, payload)

    def _append_event(self, row: dict[str, Any]) -> None:
        encoded = (
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        existed = self._path.exists()
        fd = os.open(self._path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        start_size = os.fstat(fd).st_size
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("onboarding settings append made no progress")
                view = view[written:]
            os.fsync(fd)
        except Exception:
            try:
                os.ftruncate(fd, start_size)
                os.fsync(fd)
            except OSError:
                pass
            raise
        finally:
            os.close(fd)
        if not existed:
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def _validate_record(self, owner_user_id: str, record: Any) -> None:
        if isinstance(record, _RECORDED_BY_TYPES) and record.recorded_by != owner_user_id:
            raise ValueError("recorded_by must exactly match owner_user_id")
        owner_key = lambda ref: (owner_user_id, ref)
        if isinstance(record, SecretRefRecord):
            decision = validate_secret_ref(record)
        elif isinstance(record, DataSourceAssetRecord):
            current = self._data_sources.get(owner_key(record.source_ref))
            if current is not None and current != record:
                active_policies = tuple(
                    policy
                    for (owner, _policy_ref), policy in self._no_secret_data_source_policies.items()
                    if owner == owner_user_id
                    and policy.source_ref == record.source_ref
                    and _ref_value(policy.status) == NoSecretDataSourcePolicyStatus.ACTIVE.value
                )
                if active_policies:
                    raise ValueError(
                        "DataSourceAsset with an active NoSecretDataSourcePolicy is immutable; "
                        "revoke the policy before changing the source"
                    )
            decision = validate_data_source_asset(record)
        elif isinstance(record, NoSecretDataSourcePolicyRecord):
            source = self._data_sources.get(owner_key(record.source_ref))
            if source is None:
                raise ValueError(
                    f"NoSecretDataSourcePolicy source_ref {record.source_ref!r} is not recorded for owner"
                )
            current = self._no_secret_data_source_policies.get(owner_key(record.policy_ref))
            if current is None:
                if _ref_value(record.status) != NoSecretDataSourcePolicyStatus.ACTIVE.value:
                    raise ValueError("first NoSecretDataSourcePolicy revision must be active")
                active_for_source = tuple(
                    policy
                    for (owner, policy_ref), policy in self._no_secret_data_source_policies.items()
                    if owner == owner_user_id
                    and policy_ref != record.policy_ref
                    and policy.source_ref == record.source_ref
                    and _ref_value(policy.status) == NoSecretDataSourcePolicyStatus.ACTIVE.value
                )
                if active_for_source:
                    raise ValueError(
                        "source_ref already has an active NoSecretDataSourcePolicy for owner"
                    )
            else:
                immutable_fields = (
                    "policy_ref",
                    "source_ref",
                    "source_type",
                    "connector_type",
                    "external_credential_required",
                    "permission_scope",
                    "actor_ref",
                    "approved_at",
                    "approval_ref",
                    "evidence_refs",
                    "reason",
                )
                if any(getattr(current, field) != getattr(record, field) for field in immutable_fields):
                    raise ValueError(
                        "NoSecretDataSourcePolicy approval identity is immutable; create a new policy"
                    )
                current_status = _ref_value(current.status)
                next_status = _ref_value(record.status)
                if current_status == NoSecretDataSourcePolicyStatus.REVOKED.value:
                    raise ValueError("revoked NoSecretDataSourcePolicy is terminal")
                if next_status != NoSecretDataSourcePolicyStatus.REVOKED.value:
                    raise ValueError(
                        "active NoSecretDataSourcePolicy is immutable; only revocation is allowed"
                    )
            skills = tuple(
                skill
                for (owner, _skill_id), skill in self._ingestion_skills.items()
                if owner == owner_user_id and skill.source_ref == record.source_ref
            )
            decision = validate_no_secret_data_source_policy(
                record,
                source=source,
                ingestion_skills=skills,
            )
        elif isinstance(record, IngestionSkillRecord):
            if owner_key(record.source_ref) not in self._data_sources:
                raise ValueError(f"IngestionSkill source_ref {record.source_ref!r} is not recorded for owner")
            secrets = {
                ref: value
                for (owner, ref), value in self._secret_refs.items()
                if owner == owner_user_id
            }
            decision = validate_ingestion_skill_run(record, secrets=secrets)
            active_policies = tuple(
                policy
                for (owner, _policy_ref), policy in self._no_secret_data_source_policies.items()
                if owner == owner_user_id
                and policy.source_ref == record.source_ref
                and _ref_value(policy.status) == NoSecretDataSourcePolicyStatus.ACTIVE.value
            )
            for policy in active_policies:
                policy_decision = validate_no_secret_data_source_policy(
                    policy,
                    source=self._data_sources[owner_key(record.source_ref)],
                    ingestion_skills=(record,),
                )
                if not policy_decision.accepted:
                    raise ValueError(_decision_message(policy_decision))
        elif isinstance(record, DataConnectorConnectionCheckRecord):
            try:
                skill = self._ingestion_skills[owner_key(record.skill_id)]
                source = self._data_sources[owner_key(record.source_ref)]
            except KeyError as exc:
                raise ValueError("connector check dependencies are not recorded for owner") from exc
            secrets = {
                ref: value
                for (owner, ref), value in self._secret_refs.items()
                if owner == owner_user_id
            }
            decision = validate_data_connector_connection_check(
                record, skill=skill, source=source, secrets=secrets
            )
        elif isinstance(record, DataConnectorSchemaProbeRecord):
            try:
                skill = self._ingestion_skills[owner_key(record.skill_id)]
                source = self._data_sources[owner_key(record.source_ref)]
                connector_check = self._data_connector_checks[owner_key(record.connector_check_ref)]
            except KeyError as exc:
                raise ValueError("schema probe dependencies are not recorded for owner") from exc
            decision = validate_data_connector_schema_probe(
                record, skill=skill, source=source, connector_check=connector_check
            )
        elif isinstance(record, DataConnectorFieldMappingRecord):
            try:
                skill = self._ingestion_skills[owner_key(record.skill_id)]
                source = self._data_sources[owner_key(record.source_ref)]
                schema_probe = self._data_connector_schema_probes[owner_key(record.schema_probe_ref)]
            except KeyError as exc:
                raise ValueError("field mapping dependencies are not recorded for owner") from exc
            decision = validate_data_connector_field_mapping(
                record, skill=skill, source=source, schema_probe=schema_probe
            )
        elif isinstance(record, DataConnectorPITBitemporalRuleRecord):
            try:
                skill = self._ingestion_skills[owner_key(record.skill_id)]
                source = self._data_sources[owner_key(record.source_ref)]
                field_mapping = self._data_connector_field_mappings[owner_key(record.field_mapping_ref)]
                schema_probe = self._data_connector_schema_probes[owner_key(record.schema_probe_ref)]
            except KeyError as exc:
                raise ValueError("PIT/bitemporal rule dependencies are not recorded for owner") from exc
            decision = validate_data_connector_pit_bitemporal_rule(
                record,
                skill=skill,
                source=source,
                field_mapping=field_mapping,
                schema_probe=schema_probe,
            )
        elif isinstance(record, LLMProviderRecord):
            decision = validate_llm_provider(record)
            for ref in record.auth_refs:
                if owner_key(ref) not in self._secret_refs:
                    raise ValueError(f"LLM provider auth_ref {ref!r} is not recorded for owner")
        elif isinstance(record, LLMProviderHealthSnapshotRecord):
            decision = validate_llm_provider_health_snapshot(record)
            provider = self._llm_providers.get(owner_key(record.provider_id))
            if provider is None:
                raise ValueError(
                    f"LLMProviderHealthSnapshot provider_id {record.provider_id!r} is not recorded for owner"
                )
            if record.auth_ref not in provider.auth_refs:
                raise ValueError(
                    f"LLMProviderHealthSnapshot auth_ref {record.auth_ref!r} is not recorded for provider"
                )
            secret_ref = self._secret_refs.get(owner_key(record.auth_ref))
            if secret_ref is None:
                raise ValueError(
                    f"LLMProviderHealthSnapshot auth_ref {record.auth_ref!r} is not recorded for owner"
                )
            if secret_ref.status == SecretRefStatus.REVOKED or str(secret_ref.status) == SecretRefStatus.REVOKED.value:
                raise ValueError(f"LLMProviderHealthSnapshot auth_ref {record.auth_ref!r} is revoked")
        elif isinstance(record, LLMCredentialPoolRecord):
            decision = validate_credential_pool(record)
            if owner_key(record.provider_id) not in self._llm_providers:
                raise ValueError(
                    f"LLM credential pool provider_id {record.provider_id!r} is not recorded for owner"
                )
            for ref in record.auth_refs:
                if owner_key(ref) not in self._secret_refs:
                    raise ValueError(
                        f"LLM credential pool auth_ref {ref!r} is not recorded for owner"
                    )
        elif isinstance(record, ModelRoutingPolicyRecord):
            decision = validate_model_routing_policy(record)
            for provider_id in record.allowed_providers:
                if owner_key(provider_id) not in self._llm_providers:
                    raise ValueError(
                        f"ModelRoutingPolicy provider {provider_id!r} is not recorded for owner"
                    )
            if owner_key(record.credential_pool_ref) not in self._credential_pools:
                raise ValueError(
                    f"ModelRoutingPolicy credential_pool_ref {record.credential_pool_ref!r} is not recorded for owner"
                )
        else:
            raise ValueError(f"unsupported onboarding settings record type {type(record).__name__}")
        if not decision.accepted:
            raise ValueError(_decision_message(decision))

    def _store_record(self, owner_user_id: str, event_type: str, record_ref: str, record: Any) -> None:
        storage_name = _EVENT_RECORD_TYPES[event_type][2]
        getattr(self, storage_name)[(owner_user_id, record_ref)] = record

    def _record(
        self,
        event_type: str,
        record: Any,
        *,
        owner_user_id: str,
        expected_previous_revision: int | None,
        expected_previous_hash: str | None,
    ) -> Any:
        owner_user_id = self._require_owner_user_id(owner_user_id)
        record_type, ref_field, _storage_name = _EVENT_RECORD_TYPES[event_type]
        if not isinstance(record, record_type):
            raise TypeError(f"{event_type} requires {record_type.__name__}")
        record_ref = _ref_value(getattr(record, ref_field))
        payload = _json_value(record)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            metadata_key = (owner_user_id, event_type, record_ref)
            previous = self._record_metadata.get(metadata_key)
            if previous is not None and payload == previous[2]:
                return record
            if previous is None:
                if expected_previous_revision is not None or expected_previous_hash is not None:
                    raise ValueError("new onboarding record must not declare previous revision/hash")
                revision = 1
                previous_hash = None
            else:
                if (
                    type(expected_previous_revision) is not int
                    or expected_previous_revision != previous[0]
                    or type(expected_previous_hash) is not str
                    or expected_previous_hash != previous[1]
                ):
                    raise ValueError("changed onboarding record requires matching previous revision and hash")
                revision = previous[0] + 1
                previous_hash = previous[1]
            self._validate_record(owner_user_id, record)
            body = {
                "schema_version": _ONBOARDING_SCHEMA_VERSION,
                "owner_user_id": owner_user_id,
                "event_type": event_type,
                "record_revision": revision,
                "previous_record_hash": previous_hash,
                "payload": payload,
            }
            row = {**body, "record_hash": self._record_hash(body)}
            self._append_event(row)
            self._store_record(owner_user_id, event_type, record_ref, record)
            self._record_metadata[metadata_key] = (revision, row["record_hash"], payload)
            return record

    def _record_public(
        self,
        event_type: str,
        record: Any,
        *,
        owner_user_id: str,
        expected_previous_revision: int | None = None,
        expected_previous_hash: str | None = None,
    ) -> Any:
        return self._record(
            event_type,
            record,
            owner_user_id=owner_user_id,
            expected_previous_revision=expected_previous_revision,
            expected_previous_hash=expected_previous_hash,
        )

    def record_secret_ref(self, record: SecretRefRecord, *, owner_user_id: str, **cas: Any) -> SecretRefRecord:
        return self._record_public("secret_ref_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_data_source_asset(
        self, record: DataSourceAssetRecord, *, owner_user_id: str, **cas: Any
    ) -> DataSourceAssetRecord:
        return self._record_public("data_source_asset_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_no_secret_data_source_policy(
        self,
        record: NoSecretDataSourcePolicyRecord,
        *,
        owner_user_id: str,
        **cas: Any,
    ) -> NoSecretDataSourcePolicyRecord:
        return self._record_public(
            "no_secret_data_source_policy_recorded",
            record,
            owner_user_id=owner_user_id,
            **cas,
        )

    def record_ingestion_skill(
        self, record: IngestionSkillRecord, *, owner_user_id: str, **cas: Any
    ) -> IngestionSkillRecord:
        return self._record_public("ingestion_skill_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_data_connector_check(
        self,
        record: DataConnectorConnectionCheckRecord,
        *,
        owner_user_id: str,
        **cas: Any,
    ) -> DataConnectorConnectionCheckRecord:
        return self._record_public("data_connector_check_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_data_connector_schema_probe(
        self,
        record: DataConnectorSchemaProbeRecord,
        *,
        owner_user_id: str,
        **cas: Any,
    ) -> DataConnectorSchemaProbeRecord:
        return self._record_public(
            "data_connector_schema_probe_recorded", record, owner_user_id=owner_user_id, **cas
        )

    def record_data_connector_field_mapping(
        self,
        record: DataConnectorFieldMappingRecord,
        *,
        owner_user_id: str,
        **cas: Any,
    ) -> DataConnectorFieldMappingRecord:
        return self._record_public(
            "data_connector_field_mapping_recorded", record, owner_user_id=owner_user_id, **cas
        )

    def record_data_connector_pit_bitemporal_rule(
        self,
        record: DataConnectorPITBitemporalRuleRecord,
        *,
        owner_user_id: str,
        **cas: Any,
    ) -> DataConnectorPITBitemporalRuleRecord:
        return self._record_public(
            "data_connector_pit_bitemporal_rule_recorded",
            record,
            owner_user_id=owner_user_id,
            **cas,
        )

    def record_llm_provider(
        self, record: LLMProviderRecord, *, owner_user_id: str, **cas: Any
    ) -> LLMProviderRecord:
        return self._record_public("llm_provider_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_llm_provider_health_snapshot(
        self,
        record: LLMProviderHealthSnapshotRecord,
        *,
        owner_user_id: str,
        **cas: Any,
    ) -> LLMProviderHealthSnapshotRecord:
        return self._record_public(
            "llm_provider_health_snapshot_recorded", record, owner_user_id=owner_user_id, **cas
        )

    def record_credential_pool(
        self, record: LLMCredentialPoolRecord, *, owner_user_id: str, **cas: Any
    ) -> LLMCredentialPoolRecord:
        return self._record_public("llm_credential_pool_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_routing_policy(
        self, record: ModelRoutingPolicyRecord, *, owner_user_id: str, **cas: Any
    ) -> ModelRoutingPolicyRecord:
        return self._record_public("model_routing_policy_recorded", record, owner_user_id=owner_user_id, **cas)

    def record_state(self, event_type: str, record_ref: str, *, owner_user_id: str) -> tuple[int, str]:
        owner_user_id = self._require_owner_user_id(owner_user_id)
        if event_type not in _EVENT_RECORD_TYPES:
            raise ValueError(f"unknown onboarding settings event_type={event_type!r}")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            revision, record_hash, _payload = self._record_metadata[
                (owner_user_id, event_type, record_ref)
            ]
            return revision, record_hash

    def _get(self, storage_name: str, record_ref: str, owner_user_id: str) -> Any:
        owner_user_id = self._require_owner_user_id(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return getattr(self, storage_name)[(owner_user_id, record_ref)]

    def _list(self, storage_name: str, owner_user_id: str) -> list[Any]:
        owner_user_id = self._require_owner_user_id(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return [
                record
                for (owner, _ref), record in getattr(self, storage_name).items()
                if owner == owner_user_id
            ]

    def secret_ref(self, ref: str, *, owner_user_id: str) -> SecretRefRecord:
        return self._get("_secret_refs", ref, owner_user_id)

    def data_source(self, source_ref: str, *, owner_user_id: str) -> DataSourceAssetRecord:
        return self._get("_data_sources", source_ref, owner_user_id)

    def no_secret_data_source_policy(
        self, policy_ref: str, *, owner_user_id: str
    ) -> NoSecretDataSourcePolicyRecord:
        return self._get("_no_secret_data_source_policies", policy_ref, owner_user_id)

    def ingestion_skill(self, skill_id: str, *, owner_user_id: str) -> IngestionSkillRecord:
        return self._get("_ingestion_skills", skill_id, owner_user_id)

    def data_connector_check(
        self, check_ref: str, *, owner_user_id: str
    ) -> DataConnectorConnectionCheckRecord:
        return self._get("_data_connector_checks", check_ref, owner_user_id)

    def data_connector_schema_probe(
        self, probe_ref: str, *, owner_user_id: str
    ) -> DataConnectorSchemaProbeRecord:
        return self._get("_data_connector_schema_probes", probe_ref, owner_user_id)

    def data_connector_field_mapping(
        self, mapping_ref: str, *, owner_user_id: str
    ) -> DataConnectorFieldMappingRecord:
        return self._get("_data_connector_field_mappings", mapping_ref, owner_user_id)

    def data_connector_pit_bitemporal_rule(
        self, rule_ref: str, *, owner_user_id: str
    ) -> DataConnectorPITBitemporalRuleRecord:
        return self._get("_data_connector_pit_bitemporal_rules", rule_ref, owner_user_id)

    def llm_provider(self, provider_id: str, *, owner_user_id: str) -> LLMProviderRecord:
        return self._get("_llm_providers", provider_id, owner_user_id)

    def llm_provider_health_snapshot(
        self, snapshot_ref: str, *, owner_user_id: str
    ) -> LLMProviderHealthSnapshotRecord:
        return self._get("_llm_provider_health_snapshots", snapshot_ref, owner_user_id)

    def credential_pool(self, pool_id: str, *, owner_user_id: str) -> LLMCredentialPoolRecord:
        return self._get("_credential_pools", pool_id, owner_user_id)

    def routing_policy(
        self, routing_policy_id: str, *, owner_user_id: str
    ) -> ModelRoutingPolicyRecord:
        return self._get("_routing_policies", routing_policy_id, owner_user_id)

    def secret_refs(self, *, owner_user_id: str) -> list[SecretRefRecord]:
        return self._list("_secret_refs", owner_user_id)

    def data_sources(self, *, owner_user_id: str) -> list[DataSourceAssetRecord]:
        return self._list("_data_sources", owner_user_id)

    def no_secret_data_source_policies(
        self,
        *,
        owner_user_id: str,
        source_ref: str | None = None,
        status: NoSecretDataSourcePolicyStatus | str | None = None,
    ) -> list[NoSecretDataSourcePolicyRecord]:
        policies = self._list("_no_secret_data_source_policies", owner_user_id)
        if source_ref is not None:
            policies = [policy for policy in policies if policy.source_ref == source_ref]
        if status is not None:
            policies = [policy for policy in policies if _ref_value(policy.status) == _ref_value(status)]
        return policies

    def ingestion_skills(self, *, owner_user_id: str) -> list[IngestionSkillRecord]:
        return self._list("_ingestion_skills", owner_user_id)

    def data_connector_checks(self, *, owner_user_id: str) -> list[DataConnectorConnectionCheckRecord]:
        return self._list("_data_connector_checks", owner_user_id)

    def data_connector_schema_probes(self, *, owner_user_id: str) -> list[DataConnectorSchemaProbeRecord]:
        return self._list("_data_connector_schema_probes", owner_user_id)

    def data_connector_field_mappings(self, *, owner_user_id: str) -> list[DataConnectorFieldMappingRecord]:
        return self._list("_data_connector_field_mappings", owner_user_id)

    def data_connector_pit_bitemporal_rules(
        self, *, owner_user_id: str
    ) -> list[DataConnectorPITBitemporalRuleRecord]:
        return self._list("_data_connector_pit_bitemporal_rules", owner_user_id)

    def llm_providers(self, *, owner_user_id: str) -> list[LLMProviderRecord]:
        return self._list("_llm_providers", owner_user_id)

    def llm_provider_health_snapshots(
        self, provider_id: str | None = None, *, owner_user_id: str
    ) -> list[LLMProviderHealthSnapshotRecord]:
        snapshots = self._list("_llm_provider_health_snapshots", owner_user_id)
        if provider_id is not None:
            return [record for record in snapshots if record.provider_id == provider_id]
        return snapshots

    def credential_pools(self, *, owner_user_id: str) -> list[LLMCredentialPoolRecord]:
        return self._list("_credential_pools", owner_user_id)

    def routing_policies(self, *, owner_user_id: str) -> list[ModelRoutingPolicyRecord]:
        return self._list("_routing_policies", owner_user_id)


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
    "NoSecretDataSourcePolicyRecord",
    "NoSecretDataSourcePolicyStatus",
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
    "validate_no_secret_data_source_policy",
    "validate_secret_ref",
]
