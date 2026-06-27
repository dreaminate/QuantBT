"""GOAL §12 execution boundary contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..lineage.ids import content_hash as qbt_content_hash
from .spine import RuntimeStatus


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _tuple(value))


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


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


IMMUTABLE_EXECUTION_INVARIANTS = {
    "permission",
    "secret_isolation",
    "secret_ref",
    "orderguard",
    "order_guard",
    "idempotency",
    "kill_switch",
    "audit",
    "no_silent_mock",
    "a_share_live",
}


@dataclass(frozen=True)
class ExecutionBoundaryViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class ExecutionBoundaryDecision:
    accepted: bool
    violations: tuple[ExecutionBoundaryViolation, ...]


@dataclass(frozen=True)
class RuntimePromotionRequest:
    request_ref: str
    asset_class: str
    source_runtime: RuntimeStatus | str
    target_runtime: RuntimeStatus | str
    paper_run_ref: str | None = None
    testnet_run_ref: str | None = None
    approval_ref: str | None = None
    permission_gate_ref: str | None = None
    order_guard_ref: str | None = None
    idempotency_key: str | None = None
    audit_record_ref: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    waiver_requests: tuple[str, ...] = ()
    mock_profile: str = "none"

    def __post_init__(self) -> None:
        object.__setattr__(self, "waiver_requests", _tuple(self.waiver_requests))


@dataclass(frozen=True)
class RuntimePromotionRecord:
    request_ref: str
    asset_class: str
    source_runtime: RuntimeStatus | str
    target_runtime: RuntimeStatus | str
    paper_run_ref: str | None = None
    testnet_run_ref: str | None = None
    approval_ref: str | None = None
    permission_gate_ref: str | None = None
    order_guard_ref: str | None = None
    idempotency_key: str | None = None
    audit_record_ref: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    waiver_requests: tuple[str, ...] = ()
    mock_profile: str = "none"
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    runtime_promotion_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_runtime", _value(self.source_runtime) or RuntimeStatus.OFFLINE.value)
        object.__setattr__(self, "target_runtime", _value(self.target_runtime) or RuntimeStatus.OFFLINE.value)
        object.__setattr__(self, "waiver_requests", _str_tuple(self.waiver_requests))
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        if not self.runtime_promotion_ref:
            object.__setattr__(
                self,
                "runtime_promotion_ref",
                "runtime_promotion_"
                + qbt_content_hash(
                    {
                        "request_ref": self.request_ref,
                        "asset_class": self.asset_class,
                        "source_runtime": _value(self.source_runtime),
                        "target_runtime": _value(self.target_runtime),
                        "paper_run_ref": self.paper_run_ref,
                        "testnet_run_ref": self.testnet_run_ref,
                        "approval_ref": self.approval_ref,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "audit_record_ref": self.audit_record_ref,
                        "kill_switch_ref": self.kill_switch_ref,
                        "secret_ref": self.secret_ref,
                        "responsibility_boundary_ref": self.responsibility_boundary_ref,
                        "mock_profile": self.mock_profile,
                    }
                ),
            )

    def to_request(self) -> RuntimePromotionRequest:
        return RuntimePromotionRequest(
            request_ref=self.request_ref,
            asset_class=self.asset_class,
            source_runtime=self.source_runtime,
            target_runtime=self.target_runtime,
            paper_run_ref=self.paper_run_ref,
            testnet_run_ref=self.testnet_run_ref,
            approval_ref=self.approval_ref,
            permission_gate_ref=self.permission_gate_ref,
            order_guard_ref=self.order_guard_ref,
            idempotency_key=self.idempotency_key,
            audit_record_ref=self.audit_record_ref,
            kill_switch_ref=self.kill_switch_ref,
            secret_ref=self.secret_ref,
            responsibility_boundary_ref=self.responsibility_boundary_ref,
            waiver_requests=self.waiver_requests,
            mock_profile=self.mock_profile,
        )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class DriftTriggeredAction:
    action_ref: str
    action_kind: str
    feature_drift_ref: str | None
    performance_evidence_ref: str | None
    risk_evidence_ref: str | None


@dataclass(frozen=True)
class HaltRecoveryPlan:
    plan_ref: str
    halt_event_ref: str
    reconcile_ref: str | None
    auto_resend_order: bool


@dataclass(frozen=True)
class ExecutionMathClaim:
    claim_ref: str
    claim_kind: str
    claims_math_basis: bool
    consistency_check_ref: str | None


@dataclass(frozen=True)
class ExecutionOrderIntentRecord:
    source_portfolio_ref: str | None
    strategy_book_ref: str | None
    execution_policy_ref: str
    risk_policy_ref: str
    runtime: RuntimeStatus | str
    asset_class: str
    instrument_ref: str
    side: str
    order_type: str
    venue_ref: str | None = None
    signal_ref: str | None = None
    signal_validation_ref: str | None = None
    market_data_use_validation_ref: str | None = None
    quantity_ref: str | None = None
    notional_ref: str | None = None
    price_ref: str | None = None
    time_in_force_ref: str | None = None
    permission_gate_ref: str | None = None
    order_guard_ref: str | None = None
    idempotency_key: str | None = None
    audit_record_ref: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    failure_mode_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    order_intent_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime", _value(self.runtime) or RuntimeStatus.OFFLINE.value)
        object.__setattr__(self, "failure_mode_refs", _str_tuple(self.failure_mode_refs))
        if not self.order_intent_ref:
            object.__setattr__(
                self,
                "order_intent_ref",
                "order_intent_"
                + qbt_content_hash(
                    {
                        "source_portfolio_ref": self.source_portfolio_ref,
                        "strategy_book_ref": self.strategy_book_ref,
                        "execution_policy_ref": self.execution_policy_ref,
                        "risk_policy_ref": self.risk_policy_ref,
                        "runtime": _value(self.runtime),
                        "asset_class": self.asset_class,
                        "instrument_ref": self.instrument_ref,
                        "side": self.side,
                        "order_type": self.order_type,
                        "venue_ref": self.venue_ref,
                        "signal_ref": self.signal_ref,
                        "signal_validation_ref": self.signal_validation_ref,
                        "market_data_use_validation_ref": self.market_data_use_validation_ref,
                        "quantity_ref": self.quantity_ref,
                        "notional_ref": self.notional_ref,
                        "price_ref": self.price_ref,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionOrderMaterializationRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    materializer_ref: str
    materialization_mode: str
    materialization_status: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    order_schema_ref: str | None = None
    order_payload_hash: str | None = None
    quantity_resolution_ref: str | None = None
    notional_resolution_ref: str | None = None
    price_resolution_ref: str | None = None
    time_in_force_resolution_ref: str | None = None
    market_snapshot_ref: str | None = None
    risk_check_ref: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    materialize_enabled: bool = False
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    materialization_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        object.__setattr__(self, "materialize_enabled", bool(self.materialize_enabled))
        if not self.materialization_ref:
            object.__setattr__(
                self,
                "materialization_ref",
                "order_materialization_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "materializer_ref": self.materializer_ref,
                        "materialization_mode": self.materialization_mode,
                        "materialization_status": self.materialization_status,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "idempotency_key": self.idempotency_key,
                        "order_schema_ref": self.order_schema_ref,
                        "order_payload_hash": self.order_payload_hash,
                        "quantity_resolution_ref": self.quantity_resolution_ref,
                        "notional_resolution_ref": self.notional_resolution_ref,
                        "price_resolution_ref": self.price_resolution_ref,
                        "time_in_force_resolution_ref": self.time_in_force_resolution_ref,
                        "risk_check_ref": self.risk_check_ref,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionVenueConnectivityCheckRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    venue_ref: str
    guarded_venue_ref: str
    runtime: str
    asset_class: str
    connectivity_status: str
    checker_ref: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    credential_check_ref: str
    ip_allowlist_ref: str
    withdrawal_disabled_ref: str
    hmac_replay_protection_ref: str
    health_check_ref: str
    rate_limit_ref: str
    instrument_ref: str | None = None
    sandbox_proof_ref: str | None = None
    connectivity_check_hash: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    venue_connectivity_check_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        object.__setattr__(self, "runtime", _value(self.runtime))
        if not self.venue_connectivity_check_ref:
            object.__setattr__(
                self,
                "venue_connectivity_check_ref",
                "venue_connectivity_check_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "venue_ref": self.venue_ref,
                        "guarded_venue_ref": self.guarded_venue_ref,
                        "runtime": self.runtime,
                        "asset_class": self.asset_class,
                        "connectivity_status": self.connectivity_status,
                        "checker_ref": self.checker_ref,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "idempotency_key": self.idempotency_key,
                        "credential_check_ref": self.credential_check_ref,
                        "ip_allowlist_ref": self.ip_allowlist_ref,
                        "withdrawal_disabled_ref": self.withdrawal_disabled_ref,
                        "hmac_replay_protection_ref": self.hmac_replay_protection_ref,
                        "health_check_ref": self.health_check_ref,
                        "rate_limit_ref": self.rate_limit_ref,
                        "sandbox_proof_ref": self.sandbox_proof_ref,
                        "connectivity_check_hash": self.connectivity_check_hash,
                        "kill_switch_ref": self.kill_switch_ref,
                        "secret_ref": self.secret_ref,
                        "responsibility_boundary_ref": self.responsibility_boundary_ref,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionVenueSafetyAttestationRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    venue_ref: str
    guarded_venue_ref: str
    runtime: str
    asset_class: str
    attestation_status: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    credential_check_ref: str
    ip_allowlist_ref: str
    withdrawal_disabled_ref: str
    hmac_replay_protection_ref: str
    health_check_ref: str
    rate_limit_ref: str
    venue_connectivity_check_ref: str | None = None
    instrument_ref: str | None = None
    sandbox_proof_ref: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    venue_safety_attestation_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        object.__setattr__(self, "runtime", _value(self.runtime))
        if not self.venue_safety_attestation_ref:
            object.__setattr__(
                self,
                "venue_safety_attestation_ref",
                "venue_safety_attestation_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "venue_ref": self.venue_ref,
                        "guarded_venue_ref": self.guarded_venue_ref,
                        "runtime": self.runtime,
                        "asset_class": self.asset_class,
                        "attestation_status": self.attestation_status,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "idempotency_key": self.idempotency_key,
                        "credential_check_ref": self.credential_check_ref,
                        "ip_allowlist_ref": self.ip_allowlist_ref,
                        "withdrawal_disabled_ref": self.withdrawal_disabled_ref,
                        "hmac_replay_protection_ref": self.hmac_replay_protection_ref,
                        "health_check_ref": self.health_check_ref,
                        "rate_limit_ref": self.rate_limit_ref,
                        "venue_connectivity_check_ref": self.venue_connectivity_check_ref,
                        "sandbox_proof_ref": self.sandbox_proof_ref,
                        "kill_switch_ref": self.kill_switch_ref,
                        "secret_ref": self.secret_ref,
                        "responsibility_boundary_ref": self.responsibility_boundary_ref,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionVenueCapabilityRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    venue_ref: str
    guarded_venue_ref: str
    submitter_ref: str
    runtime: str
    asset_class: str
    capability_status: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    venue_safety_attestation_ref: str | None = None
    instrument_ref: str | None = None
    credential_check_ref: str | None = None
    ip_allowlist_ref: str | None = None
    withdrawal_disabled_ref: str | None = None
    hmac_replay_protection_ref: str | None = None
    health_check_ref: str | None = None
    rate_limit_ref: str | None = None
    sandbox_proof_ref: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    can_submit_orders: bool = False
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    venue_capability_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        object.__setattr__(self, "can_submit_orders", bool(self.can_submit_orders))
        object.__setattr__(self, "runtime", _value(self.runtime))
        if not self.venue_capability_ref:
            object.__setattr__(
                self,
                "venue_capability_ref",
                "venue_capability_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "venue_ref": self.venue_ref,
                        "guarded_venue_ref": self.guarded_venue_ref,
                        "submitter_ref": self.submitter_ref,
                        "runtime": self.runtime,
                        "asset_class": self.asset_class,
                        "capability_status": self.capability_status,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "idempotency_key": self.idempotency_key,
                        "venue_safety_attestation_ref": self.venue_safety_attestation_ref,
                        "credential_check_ref": self.credential_check_ref,
                        "ip_allowlist_ref": self.ip_allowlist_ref,
                        "withdrawal_disabled_ref": self.withdrawal_disabled_ref,
                        "hmac_replay_protection_ref": self.hmac_replay_protection_ref,
                        "health_check_ref": self.health_check_ref,
                        "rate_limit_ref": self.rate_limit_ref,
                        "kill_switch_ref": self.kill_switch_ref,
                        "secret_ref": self.secret_ref,
                        "responsibility_boundary_ref": self.responsibility_boundary_ref,
                        "can_submit_orders": self.can_submit_orders,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionSubmitRequestRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    order_materialization_ref: str
    venue_capability_ref: str
    submitter_ref: str
    guarded_venue_ref: str
    venue_ref: str
    submit_request_mode: str
    submit_request_status: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    order_schema_ref: str | None = None
    order_payload_hash: str | None = None
    submit_request_schema_ref: str | None = None
    submit_request_hash: str | None = None
    client_order_ref_hash: str | None = None
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    submit_request_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        if not self.submit_request_ref:
            object.__setattr__(
                self,
                "submit_request_ref",
                "submit_request_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "order_materialization_ref": self.order_materialization_ref,
                        "venue_capability_ref": self.venue_capability_ref,
                        "submitter_ref": self.submitter_ref,
                        "guarded_venue_ref": self.guarded_venue_ref,
                        "venue_ref": self.venue_ref,
                        "submit_request_mode": self.submit_request_mode,
                        "submit_request_status": self.submit_request_status,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "idempotency_key": self.idempotency_key,
                        "order_schema_ref": self.order_schema_ref,
                        "order_payload_hash": self.order_payload_hash,
                        "submit_request_schema_ref": self.submit_request_schema_ref,
                        "submit_request_hash": self.submit_request_hash,
                        "client_order_ref_hash": self.client_order_ref_hash,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionOrderSubmissionRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    submitter_ref: str
    guarded_venue_ref: str
    venue_ref: str
    submission_mode: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    kill_switch_ref: str | None = None
    secret_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    submit_enabled: bool = False
    order_materialization_ref: str | None = None
    venue_capability_ref: str | None = None
    submit_request_ref: str | None = None
    submission_status: str = "recorded"
    venue_order_ref: str | None = None
    ack_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    submission_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        object.__setattr__(self, "submit_enabled", bool(self.submit_enabled))
        if not self.submission_ref:
            object.__setattr__(
                self,
                "submission_ref",
                "order_submission_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "submitter_ref": self.submitter_ref,
                        "guarded_venue_ref": self.guarded_venue_ref,
                        "venue_ref": self.venue_ref,
                        "submission_mode": self.submission_mode,
                        "permission_gate_ref": self.permission_gate_ref,
                        "order_guard_ref": self.order_guard_ref,
                        "idempotency_key": self.idempotency_key,
                        "order_materialization_ref": self.order_materialization_ref,
                        "venue_capability_ref": self.venue_capability_ref,
                        "submit_request_ref": self.submit_request_ref,
                        "submission_status": self.submission_status,
                        "venue_order_ref": self.venue_order_ref,
                        "ack_ref": self.ack_ref,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionVenueEventRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    venue_ref: str
    event_kind: str
    status: str
    audit_record_ref: str
    order_guard_ref: str
    idempotency_key: str
    venue_order_ref: str | None = None
    client_order_ref: str | None = None
    ack_ref: str | None = None
    fill_ref: str | None = None
    reconcile_ref: str | None = None
    quantity_ref: str | None = None
    price_ref: str | None = None
    fee_ref: str | None = None
    raw_event_hash: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    venue_event_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        if not self.venue_event_ref:
            object.__setattr__(
                self,
                "venue_event_ref",
                "venue_event_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "venue_ref": self.venue_ref,
                        "event_kind": self.event_kind,
                        "status": self.status,
                        "venue_order_ref": self.venue_order_ref,
                        "client_order_ref": self.client_order_ref,
                        "ack_ref": self.ack_ref,
                        "fill_ref": self.fill_ref,
                        "reconcile_ref": self.reconcile_ref,
                        "raw_event_hash": self.raw_event_hash,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionReconciliationRecord:
    order_intent_ref: str
    runtime_promotion_ref: str
    audit_record_ref: str
    venue_order_ref: str | None = None
    event_refs: tuple[str, ...] = ()
    status: str = "missing_events"
    discrepancy_refs: tuple[str, ...] = ()
    action_required: bool = True
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    reconciliation_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_refs", _str_tuple(self.event_refs))
        object.__setattr__(self, "discrepancy_refs", _str_tuple(self.discrepancy_refs))
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        if not self.reconciliation_ref:
            object.__setattr__(
                self,
                "reconciliation_ref",
                "execution_reconcile_"
                + qbt_content_hash(
                    {
                        "order_intent_ref": self.order_intent_ref,
                        "runtime_promotion_ref": self.runtime_promotion_ref,
                        "venue_order_ref": self.venue_order_ref,
                        "event_refs": self.event_refs,
                        "status": self.status,
                        "discrepancy_refs": self.discrepancy_refs,
                        "action_required": self.action_required,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class ExecutionReconciliationActionRecord:
    reconciliation_ref: str
    action_kind: str
    audit_record_ref: str
    action_status: str = "open"
    action_owner_ref: str | None = None
    remediation_ref: str | None = None
    halt_plan_ref: str | None = None
    waiver_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    action_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _str_tuple(self.evidence_refs))
        if not self.action_ref:
            object.__setattr__(
                self,
                "action_ref",
                "execution_reconcile_action_"
                + qbt_content_hash(
                    {
                        "reconciliation_ref": self.reconciliation_ref,
                        "action_kind": self.action_kind,
                        "action_status": self.action_status,
                        "action_owner_ref": self.action_owner_ref,
                        "remediation_ref": self.remediation_ref,
                        "halt_plan_ref": self.halt_plan_ref,
                        "waiver_ref": self.waiver_ref,
                        "evidence_refs": self.evidence_refs,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class UserRiskChoiceRecord:
    choice_ref: str
    selected_risk_path: str
    cost_disclosure_ref: str | None
    leverage_disclosure_ref: str | None
    margin_disclosure_ref: str | None
    borrow_disclosure_ref: str | None
    funding_disclosure_ref: str | None
    slippage_disclosure_ref: str | None
    liquidation_disclosure_ref: str | None
    regulation_disclosure_ref: str | None
    failure_mode_refs: tuple[str, ...]
    recommendation_ref: str | None
    responsibility_boundary_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_mode_refs", _tuple(self.failure_mode_refs))


def validate_runtime_promotion(request: RuntimePromotionRequest) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    target = _value(request.target_runtime)
    source = _value(request.source_runtime)
    asset_class = str(request.asset_class or "").lower()

    if target == RuntimeStatus.LIVE.value:
        if asset_class in {"a_share", "equity_cn", "stocks_cn", "cn_equity"}:
            violations.append(
                ExecutionBoundaryViolation(
                    "a_share_live_forbidden",
                    "A-share live requires a future explicit governance decision and is currently unreachable",
                    field="asset_class",
                    ref=request.request_ref,
                )
            )
        if source not in {RuntimeStatus.PAPER.value, RuntimeStatus.TESTNET.value, "small_live"} or (
            not _present(request.paper_run_ref) and not _present(request.testnet_run_ref)
        ):
            violations.append(
                ExecutionBoundaryViolation(
                    "live_ladder_jump",
                    "live promotion must pass through paper or testnet evidence first",
                    field="source_runtime",
                    ref=request.request_ref,
                )
            )
        required_refs = (
            "approval_ref",
            "permission_gate_ref",
            "order_guard_ref",
            "idempotency_key",
            "audit_record_ref",
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        )
        for field_name in required_refs:
            if not _present(getattr(request, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "missing_live_execution_invariant",
                        f"live execution requires {field_name}",
                        field=field_name,
                        ref=request.request_ref,
                    )
                )

    if str(request.mock_profile or "none").lower() not in {"", "none", "real", "live"} and target == RuntimeStatus.LIVE.value:
        violations.append(
            ExecutionBoundaryViolation(
                "live_mock_profile",
                "live runtime cannot use silent mock or simulation profile",
                field="mock_profile",
                ref=request.request_ref,
            )
        )

    for waiver in request.waiver_requests:
        if str(waiver).strip().lower() in IMMUTABLE_EXECUTION_INVARIANTS:
            violations.append(
                ExecutionBoundaryViolation(
                    "waiver_attempted_execution_invariant",
                    "user waiver cannot bypass execution invariants",
                    field="waiver_requests",
                    ref=request.request_ref,
                )
            )

    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def runtime_promotion_record_from_dict(data: dict[str, Any]) -> RuntimePromotionRecord:
    return RuntimePromotionRecord(
        request_ref=str(data.get("request_ref") or ""),
        asset_class=str(data.get("asset_class") or ""),
        source_runtime=str(data.get("source_runtime") or RuntimeStatus.OFFLINE.value),
        target_runtime=str(data.get("target_runtime") or RuntimeStatus.OFFLINE.value),
        paper_run_ref=data.get("paper_run_ref"),
        testnet_run_ref=data.get("testnet_run_ref"),
        approval_ref=data.get("approval_ref"),
        permission_gate_ref=data.get("permission_gate_ref"),
        order_guard_ref=data.get("order_guard_ref"),
        idempotency_key=data.get("idempotency_key"),
        audit_record_ref=data.get("audit_record_ref"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        waiver_requests=_str_tuple(data.get("waiver_requests")),
        mock_profile=str(data.get("mock_profile") or "none"),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
    )


def validate_runtime_promotion_record(record: RuntimePromotionRecord) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in ("request_ref", "asset_class", "source_runtime", "target_runtime"):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "runtime_promotion_missing_required_ref",
                    f"runtime promotion requires {field_name}",
                    field=field_name,
                    ref=record.runtime_promotion_ref,
                )
            )
    violations.extend(validate_runtime_promotion(record.to_request()).violations)
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_drift_triggered_action(action: DriftTriggeredAction) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    if _present(action.feature_drift_ref) and not (
        _present(action.performance_evidence_ref) or _present(action.risk_evidence_ref)
    ):
        if str(action.action_kind).lower() in {"trade", "order", "scale_up", "scale_down", "kill", "demote"}:
            violations.append(
                ExecutionBoundaryViolation(
                    "feature_drift_alone_triggered_trade_action",
                    "feature drift alone cannot trigger trading/capital actions without performance or risk evidence",
                    field="feature_drift_ref",
                    ref=action.action_ref,
                )
            )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_halt_recovery(plan: HaltRecoveryPlan) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    if plan.auto_resend_order:
        violations.append(
            ExecutionBoundaryViolation(
                "halt_auto_resend_order",
                "HALT recovery cannot auto-resend orders; it must reconcile first",
                field="auto_resend_order",
                ref=plan.plan_ref,
            )
        )
    if not _present(plan.reconcile_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "halt_missing_reconcile",
                "HALT recovery requires a reconcile record",
                field="reconcile_ref",
                ref=plan.plan_ref,
            )
        )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_execution_math_claim(claim: ExecutionMathClaim) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    if claim.claims_math_basis and not _present(claim.consistency_check_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "execution_math_missing_consistency_check",
                "execution cost, margin, or kill-trigger math claims require ConsistencyCheck",
                field="consistency_check_ref",
                ref=claim.claim_ref,
            )
        )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_order_intent_from_dict(data: dict[str, Any]) -> ExecutionOrderIntentRecord:
    return ExecutionOrderIntentRecord(
        source_portfolio_ref=data.get("source_portfolio_ref"),
        strategy_book_ref=data.get("strategy_book_ref"),
        execution_policy_ref=str(data.get("execution_policy_ref") or ""),
        risk_policy_ref=str(data.get("risk_policy_ref") or ""),
        runtime=str(data.get("runtime") or RuntimeStatus.OFFLINE.value),
        asset_class=str(data.get("asset_class") or ""),
        instrument_ref=str(data.get("instrument_ref") or ""),
        side=str(data.get("side") or ""),
        order_type=str(data.get("order_type") or ""),
        venue_ref=data.get("venue_ref"),
        signal_ref=data.get("signal_ref"),
        signal_validation_ref=data.get("signal_validation_ref"),
        market_data_use_validation_ref=data.get("market_data_use_validation_ref"),
        quantity_ref=data.get("quantity_ref"),
        notional_ref=data.get("notional_ref"),
        price_ref=data.get("price_ref"),
        time_in_force_ref=data.get("time_in_force_ref"),
        permission_gate_ref=data.get("permission_gate_ref"),
        order_guard_ref=data.get("order_guard_ref"),
        idempotency_key=data.get("idempotency_key"),
        audit_record_ref=data.get("audit_record_ref"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        failure_mode_refs=_str_tuple(data.get("failure_mode_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        order_intent_ref=str(data.get("order_intent_ref") or ""),
    )


def validate_execution_order_intent(
    record: ExecutionOrderIntentRecord,
    *,
    known_signal_validation_refs: set[str] | None = None,
    known_market_data_use_validation_refs: set[str] | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    runtime = _value(record.runtime)
    asset_class = str(record.asset_class or "").lower()

    if not (_present(record.source_portfolio_ref) or _present(record.strategy_book_ref)):
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_missing_source_asset",
                "order intent requires a portfolio or StrategyBook source ref",
                field="source_portfolio_ref",
                ref=record.order_intent_ref,
            )
        )
    for field_name in ("execution_policy_ref", "risk_policy_ref", "instrument_ref"):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_intent_missing_required_ref",
                    f"order intent requires {field_name}",
                    field=field_name,
                    ref=record.order_intent_ref,
                )
            )
    if str(record.side).lower() not in {"buy", "sell"}:
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_bad_side",
                "order intent side must be buy or sell",
                field="side",
                ref=record.order_intent_ref,
            )
        )
    if str(record.order_type).lower() not in {
        "market",
        "limit",
        "stop_market",
        "stop_loss",
        "take_profit",
        "take_profit_market",
        "limit_maker",
        "trailing_stop_market",
    }:
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_bad_order_type",
                "order intent order_type is not in the allowed execution contract set",
                field="order_type",
                ref=record.order_intent_ref,
            )
        )
    if not (_present(record.quantity_ref) or _present(record.notional_ref)):
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_missing_sizing_ref",
                "order intent requires quantity_ref or notional_ref; raw quantity/notional belongs outside this audit record",
                field="quantity_ref",
                ref=record.order_intent_ref,
            )
        )
    if _present(record.signal_ref) and not _present(record.signal_validation_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_missing_signal_validation_ref",
                "signal-driven order intent requires accepted SignalPerformanceValidation ref",
                field="signal_validation_ref",
                ref=record.order_intent_ref,
            )
        )
    if _present(record.signal_validation_ref) and not _present(record.signal_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_signal_validation_without_signal",
                "signal_validation_ref cannot appear without signal_ref",
                field="signal_ref",
                ref=record.order_intent_ref,
            )
        )
    if (
        known_signal_validation_refs is not None
        and _present(record.signal_validation_ref)
        and str(record.signal_validation_ref) not in known_signal_validation_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "order_intent_unknown_signal_validation_ref",
                "order intent signal_validation_ref must resolve to an accepted signal validation record",
                field="signal_validation_ref",
                ref=record.order_intent_ref,
            )
        )

    if runtime in {RuntimeStatus.PAPER.value, RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        if not _present(record.market_data_use_validation_ref):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_intent_missing_market_data_use_validation_ref",
                    "paper/testnet/live order intents require accepted MarketDataUse validation ref",
                    field="market_data_use_validation_ref",
                    ref=record.order_intent_ref,
                )
            )
        elif (
            known_market_data_use_validation_refs is not None
            and str(record.market_data_use_validation_ref) not in known_market_data_use_validation_refs
        ):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_intent_unknown_market_data_use_validation_ref",
                    "order intent market_data_use_validation_ref must resolve to an accepted MarketDataUse validation",
                    field="market_data_use_validation_ref",
                    ref=record.order_intent_ref,
                )
            )

    if runtime == RuntimeStatus.LIVE.value and asset_class in {"a_share", "equity_cn", "stocks_cn", "cn_equity"}:
        violations.append(
            ExecutionBoundaryViolation(
                "a_share_live_order_intent_forbidden",
                "A-share live order intent is unreachable in current governance boundary",
                field="asset_class",
                ref=record.order_intent_ref,
            )
        )
    if runtime in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "venue_ref",
            "permission_gate_ref",
            "order_guard_ref",
            "idempotency_key",
            "audit_record_ref",
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_intent_missing_execution_invariant",
                        f"{runtime} order intent requires {field_name}",
                        field=field_name,
                        ref=record.order_intent_ref,
                    )
                )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_order_materialization_from_dict(data: dict[str, Any]) -> ExecutionOrderMaterializationRecord:
    return ExecutionOrderMaterializationRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        materializer_ref=str(data.get("materializer_ref") or ""),
        materialization_mode=str(data.get("materialization_mode") or "record_only"),
        materialization_status=str(data.get("materialization_status") or "recorded"),
        permission_gate_ref=str(data.get("permission_gate_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        order_schema_ref=data.get("order_schema_ref"),
        order_payload_hash=data.get("order_payload_hash"),
        quantity_resolution_ref=data.get("quantity_resolution_ref"),
        notional_resolution_ref=data.get("notional_resolution_ref"),
        price_resolution_ref=data.get("price_resolution_ref"),
        time_in_force_resolution_ref=data.get("time_in_force_resolution_ref"),
        market_snapshot_ref=data.get("market_snapshot_ref"),
        risk_check_ref=data.get("risk_check_ref"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        materialize_enabled=bool(data.get("materialize_enabled", False)),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        materialization_ref=str(data.get("materialization_ref") or ""),
    )


def validate_execution_order_materialization(
    record: ExecutionOrderMaterializationRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    order_intent: ExecutionOrderIntentRecord | None = None,
    runtime_promotion: RuntimePromotionRecord | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "materializer_ref",
        "materialization_mode",
        "materialization_status",
        "permission_gate_ref",
        "order_guard_ref",
        "idempotency_key",
        "audit_record_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_missing_required_ref",
                    f"execution order materialization requires {field_name}",
                    field=field_name,
                    ref=record.materialization_ref,
                )
            )

    mode = str(record.materialization_mode or "").lower()
    status = str(record.materialization_status or "").lower()
    if mode not in {"record_only", "paper", "testnet", "live"}:
        violations.append(
            ExecutionBoundaryViolation(
                "order_materialization_bad_mode",
                "execution order materialization_mode is outside the supported set",
                field="materialization_mode",
                ref=record.materialization_ref,
            )
        )
    if status not in {"recorded", "materialized", "failed"}:
        violations.append(
            ExecutionBoundaryViolation(
                "order_materialization_bad_status",
                "execution order materialization_status is outside the supported set",
                field="materialization_status",
                ref=record.materialization_ref,
            )
        )
    if record.materialize_enabled and mode == "record_only":
        violations.append(
            ExecutionBoundaryViolation(
                "order_materialization_enabled_record_only",
                "materialize_enabled order materializations must use paper, testnet, or live mode",
                field="materialization_mode",
                ref=record.materialization_ref,
            )
        )
    if not record.materialize_enabled and status == "materialized":
        violations.append(
            ExecutionBoundaryViolation(
                "order_materialization_status_without_materializer",
                "materialized status requires materialize_enabled",
                field="materialization_status",
                ref=record.materialization_ref,
            )
        )
    if status == "materialized":
        for field_name in (
            "order_schema_ref",
            "order_payload_hash",
            "risk_check_ref",
            "market_snapshot_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_materialization_missing_materialized_ref",
                        f"materialized order requires {field_name}",
                        field=field_name,
                        ref=record.materialization_ref,
                    )
                )
        if not (_present(record.quantity_resolution_ref) or _present(record.notional_resolution_ref)):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_missing_sizing_resolution",
                    "materialized order requires quantity_resolution_ref or notional_resolution_ref",
                    field="quantity_resolution_ref",
                    ref=record.materialization_ref,
                )
            )
    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "order_materialization_unknown_order_intent_ref",
                "execution order materialization must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.materialization_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "order_materialization_unknown_runtime_promotion_ref",
                "execution order materialization must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.materialization_ref,
            )
        )

    if order_intent is not None:
        expected_pairs = (
            ("permission_gate_ref", order_intent.permission_gate_ref),
            ("order_guard_ref", order_intent.order_guard_ref),
            ("idempotency_key", order_intent.idempotency_key),
            ("kill_switch_ref", order_intent.kill_switch_ref),
            ("secret_ref", order_intent.secret_ref),
            ("responsibility_boundary_ref", order_intent.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_materialization_intent_ref_mismatch",
                        f"execution order materialization {field_name} must match its order intent",
                        field=field_name,
                        ref=record.materialization_ref,
                    )
                )
        intent_runtime = _value(order_intent.runtime)
        if record.materialize_enabled and mode != intent_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_runtime_mismatch",
                    "materialize_enabled order materialization mode must match the order intent runtime",
                    field="materialization_mode",
                    ref=record.materialization_ref,
                )
            )
        if _present(order_intent.quantity_ref) and status == "materialized" and not _present(record.quantity_resolution_ref):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_missing_quantity_resolution",
                    "order intent quantity_ref requires quantity_resolution_ref before submission",
                    field="quantity_resolution_ref",
                    ref=record.materialization_ref,
                )
            )
        if _present(order_intent.notional_ref) and status == "materialized" and not _present(record.notional_resolution_ref):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_missing_notional_resolution",
                    "order intent notional_ref requires notional_resolution_ref before submission",
                    field="notional_resolution_ref",
                    ref=record.materialization_ref,
                )
            )
        if _present(order_intent.price_ref) and status == "materialized" and not _present(record.price_resolution_ref):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_missing_price_resolution",
                    "priced order intent requires price_resolution_ref before submission",
                    field="price_resolution_ref",
                    ref=record.materialization_ref,
                )
            )
        asset_class = str(order_intent.asset_class or "").lower()
        if mode == RuntimeStatus.LIVE.value and asset_class in {"a_share", "equity_cn", "stocks_cn", "cn_equity"}:
            violations.append(
                ExecutionBoundaryViolation(
                    "a_share_live_order_materialization_forbidden",
                    "A-share live order materialization is unreachable in current governance boundary",
                    field="asset_class",
                    ref=record.materialization_ref,
                )
            )

    if runtime_promotion is not None:
        target_runtime = _value(runtime_promotion.target_runtime)
        if record.materialize_enabled and mode != target_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_materialization_runtime_promotion_mismatch",
                    "materialize_enabled order materialization mode must match runtime promotion target_runtime",
                    field="runtime_promotion_ref",
                    ref=record.materialization_ref,
                )
            )
        expected_pairs = (
            ("permission_gate_ref", runtime_promotion.permission_gate_ref),
            ("order_guard_ref", runtime_promotion.order_guard_ref),
            ("kill_switch_ref", runtime_promotion.kill_switch_ref),
            ("secret_ref", runtime_promotion.secret_ref),
            ("responsibility_boundary_ref", runtime_promotion.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_materialization_promotion_ref_mismatch",
                        f"execution order materialization {field_name} must match runtime promotion",
                        field=field_name,
                        ref=record.materialization_ref,
                    )
                )

    if mode in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_materialization_missing_execution_invariant",
                        f"{mode} order materialization requires {field_name}",
                        field=field_name,
                        ref=record.materialization_ref,
                    )
                )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_venue_connectivity_check_from_dict(data: dict[str, Any]) -> ExecutionVenueConnectivityCheckRecord:
    return ExecutionVenueConnectivityCheckRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        guarded_venue_ref=str(data.get("guarded_venue_ref") or ""),
        runtime=str(data.get("runtime") or ""),
        asset_class=str(data.get("asset_class") or ""),
        connectivity_status=str(data.get("connectivity_status") or "recorded"),
        checker_ref=str(data.get("checker_ref") or ""),
        permission_gate_ref=str(data.get("permission_gate_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        credential_check_ref=str(data.get("credential_check_ref") or ""),
        ip_allowlist_ref=str(data.get("ip_allowlist_ref") or ""),
        withdrawal_disabled_ref=str(data.get("withdrawal_disabled_ref") or ""),
        hmac_replay_protection_ref=str(data.get("hmac_replay_protection_ref") or ""),
        health_check_ref=str(data.get("health_check_ref") or ""),
        rate_limit_ref=str(data.get("rate_limit_ref") or ""),
        instrument_ref=data.get("instrument_ref"),
        sandbox_proof_ref=data.get("sandbox_proof_ref"),
        connectivity_check_hash=data.get("connectivity_check_hash"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        venue_connectivity_check_ref=str(data.get("venue_connectivity_check_ref") or ""),
    )


def validate_execution_venue_connectivity_check(
    record: ExecutionVenueConnectivityCheckRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    order_intent: ExecutionOrderIntentRecord | None = None,
    runtime_promotion: RuntimePromotionRecord | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "venue_ref",
        "guarded_venue_ref",
        "runtime",
        "asset_class",
        "connectivity_status",
        "checker_ref",
        "permission_gate_ref",
        "order_guard_ref",
        "idempotency_key",
        "audit_record_ref",
        "credential_check_ref",
        "ip_allowlist_ref",
        "withdrawal_disabled_ref",
        "hmac_replay_protection_ref",
        "health_check_ref",
        "rate_limit_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_connectivity_check_missing_required_ref",
                    f"execution venue connectivity check requires {field_name}",
                    field=field_name,
                    ref=record.venue_connectivity_check_ref,
                )
            )

    runtime = str(record.runtime or "").lower()
    status = str(record.connectivity_status or "").lower()
    if runtime not in {"paper", "testnet", "live"}:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_connectivity_check_bad_runtime",
                "execution venue connectivity check runtime is outside the supported set",
                field="runtime",
                ref=record.venue_connectivity_check_ref,
            )
        )
    if status not in {"recorded", "accepted", "failed", "revoked"}:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_connectivity_check_bad_status",
                "execution venue connectivity check status is outside the supported set",
                field="connectivity_status",
                ref=record.venue_connectivity_check_ref,
            )
        )
    if status == "accepted" and not _present(record.connectivity_check_hash):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_connectivity_check_missing_hash",
                "accepted venue connectivity check requires connectivity_check_hash",
                field="connectivity_check_hash",
                ref=record.venue_connectivity_check_ref,
            )
        )
    if runtime in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_connectivity_check_missing_execution_invariant",
                        f"{runtime} venue connectivity check requires {field_name}",
                        field=field_name,
                        ref=record.venue_connectivity_check_ref,
                    )
                )
    if runtime == RuntimeStatus.LIVE.value and str(record.asset_class or "").lower() in {
        "a_share",
        "equity_cn",
        "stocks_cn",
        "cn_equity",
    }:
        violations.append(
            ExecutionBoundaryViolation(
                "a_share_live_venue_connectivity_check_forbidden",
                "A-share live venue connectivity check is unreachable in current governance boundary",
                field="asset_class",
                ref=record.venue_connectivity_check_ref,
            )
        )

    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_connectivity_check_unknown_order_intent_ref",
                "execution venue connectivity check must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.venue_connectivity_check_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_connectivity_check_unknown_runtime_promotion_ref",
                "execution venue connectivity check must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.venue_connectivity_check_ref,
            )
        )

    if order_intent is not None:
        expected_pairs = (
            ("venue_ref", order_intent.venue_ref),
            ("permission_gate_ref", order_intent.permission_gate_ref),
            ("order_guard_ref", order_intent.order_guard_ref),
            ("idempotency_key", order_intent.idempotency_key),
            ("kill_switch_ref", order_intent.kill_switch_ref),
            ("secret_ref", order_intent.secret_ref),
            ("responsibility_boundary_ref", order_intent.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_connectivity_check_intent_ref_mismatch",
                        f"execution venue connectivity check {field_name} must match its order intent",
                        field=field_name,
                        ref=record.venue_connectivity_check_ref,
                    )
                )
        if runtime != _value(order_intent.runtime):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_connectivity_check_runtime_mismatch",
                    "execution venue connectivity check runtime must match the order intent runtime",
                    field="runtime",
                    ref=record.venue_connectivity_check_ref,
                )
            )
        if str(record.asset_class or "") != str(order_intent.asset_class or ""):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_connectivity_check_asset_class_mismatch",
                    "execution venue connectivity check asset_class must match the order intent",
                    field="asset_class",
                    ref=record.venue_connectivity_check_ref,
                )
            )

    if runtime_promotion is not None:
        if runtime != _value(runtime_promotion.target_runtime):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_connectivity_check_runtime_promotion_mismatch",
                    "execution venue connectivity check runtime must match runtime promotion target_runtime",
                    field="runtime_promotion_ref",
                    ref=record.venue_connectivity_check_ref,
                )
            )
        if str(record.asset_class or "") != str(runtime_promotion.asset_class or ""):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_connectivity_check_promotion_asset_class_mismatch",
                    "execution venue connectivity check asset_class must match runtime promotion",
                    field="asset_class",
                    ref=record.venue_connectivity_check_ref,
                )
            )
        expected_pairs = (
            ("permission_gate_ref", runtime_promotion.permission_gate_ref),
            ("order_guard_ref", runtime_promotion.order_guard_ref),
            ("kill_switch_ref", runtime_promotion.kill_switch_ref),
            ("secret_ref", runtime_promotion.secret_ref),
            ("responsibility_boundary_ref", runtime_promotion.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_connectivity_check_promotion_ref_mismatch",
                        f"execution venue connectivity check {field_name} must match runtime promotion",
                        field=field_name,
                        ref=record.venue_connectivity_check_ref,
                    )
                )

    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_venue_safety_attestation_from_dict(data: dict[str, Any]) -> ExecutionVenueSafetyAttestationRecord:
    return ExecutionVenueSafetyAttestationRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        guarded_venue_ref=str(data.get("guarded_venue_ref") or ""),
        runtime=str(data.get("runtime") or ""),
        asset_class=str(data.get("asset_class") or ""),
        attestation_status=str(data.get("attestation_status") or "recorded"),
        permission_gate_ref=str(data.get("permission_gate_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        credential_check_ref=str(data.get("credential_check_ref") or ""),
        ip_allowlist_ref=str(data.get("ip_allowlist_ref") or ""),
        withdrawal_disabled_ref=str(data.get("withdrawal_disabled_ref") or ""),
        hmac_replay_protection_ref=str(data.get("hmac_replay_protection_ref") or ""),
        health_check_ref=str(data.get("health_check_ref") or ""),
        rate_limit_ref=str(data.get("rate_limit_ref") or ""),
        venue_connectivity_check_ref=data.get("venue_connectivity_check_ref"),
        instrument_ref=data.get("instrument_ref"),
        sandbox_proof_ref=data.get("sandbox_proof_ref"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        venue_safety_attestation_ref=str(data.get("venue_safety_attestation_ref") or ""),
    )


def validate_execution_venue_safety_attestation(
    record: ExecutionVenueSafetyAttestationRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    known_venue_connectivity_check_refs: set[str] | None = None,
    order_intent: ExecutionOrderIntentRecord | None = None,
    runtime_promotion: RuntimePromotionRecord | None = None,
    venue_connectivity_check: ExecutionVenueConnectivityCheckRecord | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "venue_ref",
        "guarded_venue_ref",
        "runtime",
        "asset_class",
        "attestation_status",
        "permission_gate_ref",
        "order_guard_ref",
        "idempotency_key",
        "audit_record_ref",
        "credential_check_ref",
        "ip_allowlist_ref",
        "withdrawal_disabled_ref",
        "hmac_replay_protection_ref",
        "health_check_ref",
        "rate_limit_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_missing_required_ref",
                    f"execution venue safety attestation requires {field_name}",
                    field=field_name,
                    ref=record.venue_safety_attestation_ref,
                )
            )

    runtime = str(record.runtime or "").lower()
    status = str(record.attestation_status or "").lower()
    if runtime not in {"paper", "testnet", "live"}:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_safety_attestation_bad_runtime",
                "execution venue safety attestation runtime is outside the supported set",
                field="runtime",
                ref=record.venue_safety_attestation_ref,
            )
        )
    if status not in {"recorded", "accepted", "failed", "revoked"}:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_safety_attestation_bad_status",
                "execution venue safety attestation_status is outside the supported set",
                field="attestation_status",
                ref=record.venue_safety_attestation_ref,
            )
        )
    if status == "accepted" and not _present(record.venue_connectivity_check_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_safety_attestation_missing_connectivity_check_ref",
                "accepted venue safety attestation requires venue_connectivity_check_ref",
                field="venue_connectivity_check_ref",
                ref=record.venue_safety_attestation_ref,
            )
        )
    if runtime in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_safety_attestation_missing_execution_invariant",
                        f"{runtime} venue safety attestation requires {field_name}",
                        field=field_name,
                        ref=record.venue_safety_attestation_ref,
                    )
                )
    if runtime == RuntimeStatus.LIVE.value and str(record.asset_class or "").lower() in {
        "a_share",
        "equity_cn",
        "stocks_cn",
        "cn_equity",
    }:
        violations.append(
            ExecutionBoundaryViolation(
                "a_share_live_venue_safety_attestation_forbidden",
                "A-share live venue safety attestation is unreachable in current governance boundary",
                field="asset_class",
                ref=record.venue_safety_attestation_ref,
            )
        )

    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_safety_attestation_unknown_order_intent_ref",
                "execution venue safety attestation must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.venue_safety_attestation_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_safety_attestation_unknown_runtime_promotion_ref",
                "execution venue safety attestation must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.venue_safety_attestation_ref,
            )
        )
    if (
        known_venue_connectivity_check_refs is not None
        and _present(record.venue_connectivity_check_ref)
        and str(record.venue_connectivity_check_ref) not in known_venue_connectivity_check_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_safety_attestation_unknown_connectivity_check_ref",
                "execution venue safety attestation venue_connectivity_check_ref must resolve to a recorded connectivity check",
                field="venue_connectivity_check_ref",
                ref=record.venue_safety_attestation_ref,
            )
        )

    if order_intent is not None:
        expected_pairs = (
            ("venue_ref", order_intent.venue_ref),
            ("permission_gate_ref", order_intent.permission_gate_ref),
            ("order_guard_ref", order_intent.order_guard_ref),
            ("idempotency_key", order_intent.idempotency_key),
            ("kill_switch_ref", order_intent.kill_switch_ref),
            ("secret_ref", order_intent.secret_ref),
            ("responsibility_boundary_ref", order_intent.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_safety_attestation_intent_ref_mismatch",
                        f"execution venue safety attestation {field_name} must match its order intent",
                        field=field_name,
                        ref=record.venue_safety_attestation_ref,
                    )
                )
        if runtime != _value(order_intent.runtime):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_runtime_mismatch",
                    "execution venue safety attestation runtime must match the order intent runtime",
                    field="runtime",
                    ref=record.venue_safety_attestation_ref,
                )
            )
        if str(record.asset_class or "") != str(order_intent.asset_class or ""):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_asset_class_mismatch",
                    "execution venue safety attestation asset_class must match the order intent",
                    field="asset_class",
                    ref=record.venue_safety_attestation_ref,
                )
            )
        if _present(order_intent.instrument_ref) and _present(record.instrument_ref) and record.instrument_ref != order_intent.instrument_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_instrument_ref_mismatch",
                    "execution venue safety attestation instrument_ref must match the order intent",
                    field="instrument_ref",
                    ref=record.venue_safety_attestation_ref,
                )
            )

    if runtime_promotion is not None:
        if runtime != _value(runtime_promotion.target_runtime):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_runtime_promotion_mismatch",
                    "execution venue safety attestation runtime must match runtime promotion target_runtime",
                    field="runtime_promotion_ref",
                    ref=record.venue_safety_attestation_ref,
                )
            )
        if str(record.asset_class or "") != str(runtime_promotion.asset_class or ""):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_promotion_asset_class_mismatch",
                    "execution venue safety attestation asset_class must match runtime promotion",
                    field="asset_class",
                    ref=record.venue_safety_attestation_ref,
                )
            )
        expected_pairs = (
            ("permission_gate_ref", runtime_promotion.permission_gate_ref),
            ("order_guard_ref", runtime_promotion.order_guard_ref),
            ("kill_switch_ref", runtime_promotion.kill_switch_ref),
            ("secret_ref", runtime_promotion.secret_ref),
            ("responsibility_boundary_ref", runtime_promotion.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_safety_attestation_promotion_ref_mismatch",
                        f"execution venue safety attestation {field_name} must match runtime promotion",
                        field=field_name,
                        ref=record.venue_safety_attestation_ref,
                    )
                )

    if venue_connectivity_check is not None:
        expected_pairs = (
            ("order_intent_ref", venue_connectivity_check.order_intent_ref),
            ("runtime_promotion_ref", venue_connectivity_check.runtime_promotion_ref),
            ("venue_ref", venue_connectivity_check.venue_ref),
            ("guarded_venue_ref", venue_connectivity_check.guarded_venue_ref),
            ("runtime", venue_connectivity_check.runtime),
            ("asset_class", venue_connectivity_check.asset_class),
            ("permission_gate_ref", venue_connectivity_check.permission_gate_ref),
            ("order_guard_ref", venue_connectivity_check.order_guard_ref),
            ("idempotency_key", venue_connectivity_check.idempotency_key),
            ("credential_check_ref", venue_connectivity_check.credential_check_ref),
            ("ip_allowlist_ref", venue_connectivity_check.ip_allowlist_ref),
            ("withdrawal_disabled_ref", venue_connectivity_check.withdrawal_disabled_ref),
            ("hmac_replay_protection_ref", venue_connectivity_check.hmac_replay_protection_ref),
            ("health_check_ref", venue_connectivity_check.health_check_ref),
            ("rate_limit_ref", venue_connectivity_check.rate_limit_ref),
            ("sandbox_proof_ref", venue_connectivity_check.sandbox_proof_ref),
            ("kill_switch_ref", venue_connectivity_check.kill_switch_ref),
            ("secret_ref", venue_connectivity_check.secret_ref),
            ("responsibility_boundary_ref", venue_connectivity_check.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_safety_attestation_connectivity_check_ref_mismatch",
                        f"execution venue safety attestation {field_name} must match connectivity check",
                        field=field_name,
                        ref=record.venue_safety_attestation_ref,
                    )
                )
        if record.venue_connectivity_check_ref != venue_connectivity_check.venue_connectivity_check_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_connectivity_check_ref_mismatch",
                    "execution venue safety attestation must reference the supplied venue_connectivity_check_ref",
                    field="venue_connectivity_check_ref",
                    ref=record.venue_safety_attestation_ref,
                )
            )
        if status == "accepted" and venue_connectivity_check.connectivity_status != "accepted":
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_safety_attestation_connectivity_check_not_accepted",
                    "accepted venue safety attestation requires accepted connectivity check",
                    field="venue_connectivity_check_ref",
                    ref=record.venue_safety_attestation_ref,
                )
            )

    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_venue_capability_from_dict(data: dict[str, Any]) -> ExecutionVenueCapabilityRecord:
    return ExecutionVenueCapabilityRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        guarded_venue_ref=str(data.get("guarded_venue_ref") or ""),
        submitter_ref=str(data.get("submitter_ref") or ""),
        runtime=str(data.get("runtime") or ""),
        asset_class=str(data.get("asset_class") or ""),
        capability_status=str(data.get("capability_status") or "recorded"),
        permission_gate_ref=str(data.get("permission_gate_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        venue_safety_attestation_ref=data.get("venue_safety_attestation_ref"),
        instrument_ref=data.get("instrument_ref"),
        credential_check_ref=data.get("credential_check_ref"),
        ip_allowlist_ref=data.get("ip_allowlist_ref"),
        withdrawal_disabled_ref=data.get("withdrawal_disabled_ref"),
        hmac_replay_protection_ref=data.get("hmac_replay_protection_ref"),
        health_check_ref=data.get("health_check_ref"),
        rate_limit_ref=data.get("rate_limit_ref"),
        sandbox_proof_ref=data.get("sandbox_proof_ref"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        can_submit_orders=bool(data.get("can_submit_orders", False)),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        venue_capability_ref=str(data.get("venue_capability_ref") or ""),
    )


def validate_execution_venue_capability(
    record: ExecutionVenueCapabilityRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    known_venue_safety_attestation_refs: set[str] | None = None,
    order_intent: ExecutionOrderIntentRecord | None = None,
    runtime_promotion: RuntimePromotionRecord | None = None,
    venue_safety_attestation: ExecutionVenueSafetyAttestationRecord | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "venue_ref",
        "guarded_venue_ref",
        "submitter_ref",
        "runtime",
        "asset_class",
        "capability_status",
        "permission_gate_ref",
        "order_guard_ref",
        "idempotency_key",
        "audit_record_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_missing_required_ref",
                    f"execution venue capability requires {field_name}",
                    field=field_name,
                    ref=record.venue_capability_ref,
                )
            )

    runtime = str(record.runtime or "").lower()
    status = str(record.capability_status or "").lower()
    if runtime not in {"paper", "testnet", "live"}:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_bad_runtime",
                "execution venue capability runtime is outside the supported set",
                field="runtime",
                ref=record.venue_capability_ref,
            )
        )
    if status not in {"recorded", "ready", "failed", "revoked"}:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_bad_status",
                "execution venue capability_status is outside the supported set",
                field="capability_status",
                ref=record.venue_capability_ref,
            )
        )
    if record.can_submit_orders and status != "ready":
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_submit_without_ready",
                "can_submit_orders requires ready capability_status",
                field="can_submit_orders",
                ref=record.venue_capability_ref,
            )
        )
    if status == "ready" and not record.can_submit_orders:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_ready_without_submit_flag",
                "ready venue capability must set can_submit_orders",
                field="can_submit_orders",
                ref=record.venue_capability_ref,
            )
        )
    if status == "ready" and not _present(record.venue_safety_attestation_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_missing_safety_attestation_ref",
                "ready venue capability requires venue_safety_attestation_ref",
                field="venue_safety_attestation_ref",
                ref=record.venue_capability_ref,
            )
        )
    if status == "ready":
        for field_name in (
            "credential_check_ref",
            "ip_allowlist_ref",
            "withdrawal_disabled_ref",
            "hmac_replay_protection_ref",
            "health_check_ref",
            "rate_limit_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_capability_missing_ready_ref",
                        f"ready venue capability requires {field_name}",
                        field=field_name,
                        ref=record.venue_capability_ref,
                    )
                )
    if runtime in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_capability_missing_execution_invariant",
                        f"{runtime} venue capability requires {field_name}",
                        field=field_name,
                        ref=record.venue_capability_ref,
                    )
                )
    if runtime == RuntimeStatus.LIVE.value and str(record.asset_class or "").lower() in {
        "a_share",
        "equity_cn",
        "stocks_cn",
        "cn_equity",
    }:
        violations.append(
            ExecutionBoundaryViolation(
                "a_share_live_venue_capability_forbidden",
                "A-share live venue capability is unreachable in current governance boundary",
                field="asset_class",
                ref=record.venue_capability_ref,
            )
        )

    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_unknown_order_intent_ref",
                "execution venue capability must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.venue_capability_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_unknown_runtime_promotion_ref",
                "execution venue capability must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.venue_capability_ref,
            )
        )
    if (
        known_venue_safety_attestation_refs is not None
        and _present(record.venue_safety_attestation_ref)
        and str(record.venue_safety_attestation_ref) not in known_venue_safety_attestation_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_capability_unknown_safety_attestation_ref",
                "execution venue capability venue_safety_attestation_ref must resolve to a recorded safety attestation",
                field="venue_safety_attestation_ref",
                ref=record.venue_capability_ref,
            )
        )

    if order_intent is not None:
        expected_pairs = (
            ("venue_ref", order_intent.venue_ref),
            ("permission_gate_ref", order_intent.permission_gate_ref),
            ("order_guard_ref", order_intent.order_guard_ref),
            ("idempotency_key", order_intent.idempotency_key),
            ("kill_switch_ref", order_intent.kill_switch_ref),
            ("secret_ref", order_intent.secret_ref),
            ("responsibility_boundary_ref", order_intent.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_capability_intent_ref_mismatch",
                        f"execution venue capability {field_name} must match its order intent",
                        field=field_name,
                        ref=record.venue_capability_ref,
                    )
                )
        intent_runtime = _value(order_intent.runtime)
        if runtime != intent_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_runtime_mismatch",
                    "execution venue capability runtime must match the order intent runtime",
                    field="runtime",
                    ref=record.venue_capability_ref,
                )
            )
        if str(record.asset_class or "") != str(order_intent.asset_class or ""):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_asset_class_mismatch",
                    "execution venue capability asset_class must match the order intent",
                    field="asset_class",
                    ref=record.venue_capability_ref,
                )
            )
        if _present(order_intent.instrument_ref) and _present(record.instrument_ref) and record.instrument_ref != order_intent.instrument_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_instrument_ref_mismatch",
                    "execution venue capability instrument_ref must match the order intent",
                    field="instrument_ref",
                    ref=record.venue_capability_ref,
                )
                )

    if venue_safety_attestation is not None:
        expected_pairs = (
            ("order_intent_ref", venue_safety_attestation.order_intent_ref),
            ("runtime_promotion_ref", venue_safety_attestation.runtime_promotion_ref),
            ("venue_ref", venue_safety_attestation.venue_ref),
            ("guarded_venue_ref", venue_safety_attestation.guarded_venue_ref),
            ("runtime", venue_safety_attestation.runtime),
            ("asset_class", venue_safety_attestation.asset_class),
            ("permission_gate_ref", venue_safety_attestation.permission_gate_ref),
            ("order_guard_ref", venue_safety_attestation.order_guard_ref),
            ("idempotency_key", venue_safety_attestation.idempotency_key),
            ("credential_check_ref", venue_safety_attestation.credential_check_ref),
            ("ip_allowlist_ref", venue_safety_attestation.ip_allowlist_ref),
            ("withdrawal_disabled_ref", venue_safety_attestation.withdrawal_disabled_ref),
            ("hmac_replay_protection_ref", venue_safety_attestation.hmac_replay_protection_ref),
            ("health_check_ref", venue_safety_attestation.health_check_ref),
            ("rate_limit_ref", venue_safety_attestation.rate_limit_ref),
            ("sandbox_proof_ref", venue_safety_attestation.sandbox_proof_ref),
            ("kill_switch_ref", venue_safety_attestation.kill_switch_ref),
            ("secret_ref", venue_safety_attestation.secret_ref),
            ("responsibility_boundary_ref", venue_safety_attestation.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_capability_safety_attestation_ref_mismatch",
                        f"execution venue capability {field_name} must match safety attestation",
                        field=field_name,
                        ref=record.venue_capability_ref,
                    )
                )
        if record.venue_safety_attestation_ref != venue_safety_attestation.venue_safety_attestation_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_safety_attestation_ref_mismatch",
                    "execution venue capability must reference the supplied venue_safety_attestation_ref",
                    field="venue_safety_attestation_ref",
                    ref=record.venue_capability_ref,
                )
            )
        if status == "ready" and venue_safety_attestation.attestation_status != "accepted":
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_safety_attestation_not_accepted",
                    "ready venue capability requires accepted safety attestation",
                    field="venue_safety_attestation_ref",
                    ref=record.venue_capability_ref,
                )
            )

    if runtime_promotion is not None:
        target_runtime = _value(runtime_promotion.target_runtime)
        if runtime != target_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_runtime_promotion_mismatch",
                    "execution venue capability runtime must match runtime promotion target_runtime",
                    field="runtime_promotion_ref",
                    ref=record.venue_capability_ref,
                )
            )
        if str(record.asset_class or "") != str(runtime_promotion.asset_class or ""):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_capability_promotion_asset_class_mismatch",
                    "execution venue capability asset_class must match runtime promotion",
                    field="asset_class",
                    ref=record.venue_capability_ref,
                )
            )
        expected_pairs = (
            ("permission_gate_ref", runtime_promotion.permission_gate_ref),
            ("order_guard_ref", runtime_promotion.order_guard_ref),
            ("kill_switch_ref", runtime_promotion.kill_switch_ref),
            ("secret_ref", runtime_promotion.secret_ref),
            ("responsibility_boundary_ref", runtime_promotion.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_capability_promotion_ref_mismatch",
                        f"execution venue capability {field_name} must match runtime promotion",
                        field=field_name,
                        ref=record.venue_capability_ref,
                    )
                )

    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_submit_request_from_dict(data: dict[str, Any]) -> ExecutionSubmitRequestRecord:
    return ExecutionSubmitRequestRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        order_materialization_ref=str(data.get("order_materialization_ref") or ""),
        venue_capability_ref=str(data.get("venue_capability_ref") or ""),
        submitter_ref=str(data.get("submitter_ref") or ""),
        guarded_venue_ref=str(data.get("guarded_venue_ref") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        submit_request_mode=str(data.get("submit_request_mode") or "record_only"),
        submit_request_status=str(data.get("submit_request_status") or "recorded"),
        permission_gate_ref=str(data.get("permission_gate_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        order_schema_ref=data.get("order_schema_ref"),
        order_payload_hash=data.get("order_payload_hash"),
        submit_request_schema_ref=data.get("submit_request_schema_ref"),
        submit_request_hash=data.get("submit_request_hash"),
        client_order_ref_hash=data.get("client_order_ref_hash"),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        submit_request_ref=str(data.get("submit_request_ref") or ""),
    )


def validate_execution_submit_request(
    record: ExecutionSubmitRequestRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    known_order_materialization_refs: set[str] | None = None,
    known_venue_capability_refs: set[str] | None = None,
    order_intent: ExecutionOrderIntentRecord | None = None,
    runtime_promotion: RuntimePromotionRecord | None = None,
    order_materialization: ExecutionOrderMaterializationRecord | None = None,
    venue_capability: ExecutionVenueCapabilityRecord | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "order_materialization_ref",
        "venue_capability_ref",
        "submitter_ref",
        "guarded_venue_ref",
        "venue_ref",
        "submit_request_mode",
        "submit_request_status",
        "permission_gate_ref",
        "order_guard_ref",
        "idempotency_key",
        "audit_record_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_missing_required_ref",
                    f"execution submit request requires {field_name}",
                    field=field_name,
                    ref=record.submit_request_ref,
                )
            )

    mode = str(record.submit_request_mode or "").lower()
    status = str(record.submit_request_status or "").lower()
    if mode not in {"record_only", "paper", "testnet", "live"}:
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_bad_mode",
                "execution submit request mode is outside the supported set",
                field="submit_request_mode",
                ref=record.submit_request_ref,
            )
        )
    if status not in {"recorded", "ready", "failed", "revoked"}:
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_bad_status",
                "execution submit request status is outside the supported set",
                field="submit_request_status",
                ref=record.submit_request_ref,
            )
        )
    if status == "ready" and mode == "record_only":
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_ready_record_only",
                "ready submit requests must use paper, testnet, or live mode",
                field="submit_request_mode",
                ref=record.submit_request_ref,
            )
        )
    if status == "ready":
        for field_name in (
            "order_schema_ref",
            "order_payload_hash",
            "submit_request_schema_ref",
            "submit_request_hash",
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "submit_request_missing_ready_ref",
                        f"ready submit request requires {field_name}",
                        field=field_name,
                        ref=record.submit_request_ref,
                    )
                )
    if mode in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "submit_request_missing_execution_invariant",
                        f"{mode} submit request requires {field_name}",
                        field=field_name,
                        ref=record.submit_request_ref,
                    )
                )

    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_unknown_order_intent_ref",
                "execution submit request must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.submit_request_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_unknown_runtime_promotion_ref",
                "execution submit request must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.submit_request_ref,
            )
        )
    if (
        known_order_materialization_refs is not None
        and record.order_materialization_ref not in known_order_materialization_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_unknown_materialization_ref",
                "execution submit request must resolve to a recorded materialization",
                field="order_materialization_ref",
                ref=record.submit_request_ref,
            )
        )
    if known_venue_capability_refs is not None and record.venue_capability_ref not in known_venue_capability_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "submit_request_unknown_venue_capability_ref",
                "execution submit request must resolve to a recorded venue capability",
                field="venue_capability_ref",
                ref=record.submit_request_ref,
            )
        )

    if order_intent is not None:
        expected_pairs = (
            ("venue_ref", order_intent.venue_ref),
            ("permission_gate_ref", order_intent.permission_gate_ref),
            ("order_guard_ref", order_intent.order_guard_ref),
            ("idempotency_key", order_intent.idempotency_key),
            ("kill_switch_ref", order_intent.kill_switch_ref),
            ("secret_ref", order_intent.secret_ref),
            ("responsibility_boundary_ref", order_intent.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "submit_request_intent_ref_mismatch",
                        f"execution submit request {field_name} must match its order intent",
                        field=field_name,
                        ref=record.submit_request_ref,
                    )
                )
        intent_runtime = _value(order_intent.runtime)
        if status == "ready" and mode != intent_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_runtime_mismatch",
                    "ready submit request mode must match the order intent runtime",
                    field="submit_request_mode",
                    ref=record.submit_request_ref,
                )
            )
        asset_class = str(order_intent.asset_class or "").lower()
        if mode == RuntimeStatus.LIVE.value and asset_class in {"a_share", "equity_cn", "stocks_cn", "cn_equity"}:
            violations.append(
                ExecutionBoundaryViolation(
                    "a_share_live_submit_request_forbidden",
                    "A-share live submit request is unreachable in current governance boundary",
                    field="asset_class",
                    ref=record.submit_request_ref,
                )
            )

    if runtime_promotion is not None:
        target_runtime = _value(runtime_promotion.target_runtime)
        if status == "ready" and mode != target_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_runtime_promotion_mismatch",
                    "ready submit request mode must match runtime promotion target_runtime",
                    field="runtime_promotion_ref",
                    ref=record.submit_request_ref,
                )
            )
        expected_pairs = (
            ("permission_gate_ref", runtime_promotion.permission_gate_ref),
            ("order_guard_ref", runtime_promotion.order_guard_ref),
            ("kill_switch_ref", runtime_promotion.kill_switch_ref),
            ("secret_ref", runtime_promotion.secret_ref),
            ("responsibility_boundary_ref", runtime_promotion.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "submit_request_promotion_ref_mismatch",
                        f"execution submit request {field_name} must match runtime promotion",
                        field=field_name,
                        ref=record.submit_request_ref,
                    )
                )

    if order_materialization is not None:
        expected_pairs = (
            ("order_intent_ref", order_materialization.order_intent_ref),
            ("runtime_promotion_ref", order_materialization.runtime_promotion_ref),
            ("permission_gate_ref", order_materialization.permission_gate_ref),
            ("order_guard_ref", order_materialization.order_guard_ref),
            ("idempotency_key", order_materialization.idempotency_key),
            ("kill_switch_ref", order_materialization.kill_switch_ref),
            ("secret_ref", order_materialization.secret_ref),
            ("responsibility_boundary_ref", order_materialization.responsibility_boundary_ref),
            ("order_schema_ref", order_materialization.order_schema_ref),
            ("order_payload_hash", order_materialization.order_payload_hash),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "submit_request_materialization_ref_mismatch",
                        f"execution submit request {field_name} must match materialization",
                        field=field_name,
                        ref=record.submit_request_ref,
                    )
                )
        if record.order_materialization_ref != order_materialization.materialization_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_materialization_ref_mismatch",
                    "execution submit request must reference the supplied materialization_ref",
                    field="order_materialization_ref",
                    ref=record.submit_request_ref,
                )
            )
        if status == "ready" and order_materialization.materialization_status != "materialized":
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_materialization_not_ready",
                    "ready submit request requires materialized order payload hash refs",
                    field="order_materialization_ref",
                    ref=record.submit_request_ref,
                )
            )

    if venue_capability is not None:
        expected_pairs = (
            ("order_intent_ref", venue_capability.order_intent_ref),
            ("runtime_promotion_ref", venue_capability.runtime_promotion_ref),
            ("submitter_ref", venue_capability.submitter_ref),
            ("guarded_venue_ref", venue_capability.guarded_venue_ref),
            ("venue_ref", venue_capability.venue_ref),
            ("permission_gate_ref", venue_capability.permission_gate_ref),
            ("order_guard_ref", venue_capability.order_guard_ref),
            ("idempotency_key", venue_capability.idempotency_key),
            ("kill_switch_ref", venue_capability.kill_switch_ref),
            ("secret_ref", venue_capability.secret_ref),
            ("responsibility_boundary_ref", venue_capability.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "submit_request_venue_capability_ref_mismatch",
                        f"execution submit request {field_name} must match venue capability",
                        field=field_name,
                        ref=record.submit_request_ref,
                    )
                )
        if record.venue_capability_ref != venue_capability.venue_capability_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_venue_capability_ref_mismatch",
                    "execution submit request must reference the supplied venue_capability_ref",
                    field="venue_capability_ref",
                    ref=record.submit_request_ref,
                )
            )
        if status == "ready" and (venue_capability.capability_status != "ready" or not venue_capability.can_submit_orders):
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_venue_capability_not_ready",
                    "ready submit request requires ready venue capability",
                    field="venue_capability_ref",
                    ref=record.submit_request_ref,
                )
            )
        if status == "ready" and mode != str(venue_capability.runtime or "").lower():
            violations.append(
                ExecutionBoundaryViolation(
                    "submit_request_venue_capability_runtime_mismatch",
                    "ready submit request mode must match venue capability runtime",
                    field="submit_request_mode",
                    ref=record.submit_request_ref,
                )
            )

    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_order_submission_from_dict(data: dict[str, Any]) -> ExecutionOrderSubmissionRecord:
    return ExecutionOrderSubmissionRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        submitter_ref=str(data.get("submitter_ref") or ""),
        guarded_venue_ref=str(data.get("guarded_venue_ref") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        submission_mode=str(data.get("submission_mode") or "record_only"),
        permission_gate_ref=str(data.get("permission_gate_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        kill_switch_ref=data.get("kill_switch_ref"),
        secret_ref=data.get("secret_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        submit_enabled=bool(data.get("submit_enabled", False)),
        order_materialization_ref=data.get("order_materialization_ref"),
        venue_capability_ref=data.get("venue_capability_ref"),
        submit_request_ref=data.get("submit_request_ref"),
        submission_status=str(data.get("submission_status") or "recorded"),
        venue_order_ref=data.get("venue_order_ref"),
        ack_ref=data.get("ack_ref"),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        submission_ref=str(data.get("submission_ref") or ""),
    )


def validate_execution_order_submission(
    record: ExecutionOrderSubmissionRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    known_order_materialization_refs: set[str] | None = None,
    known_venue_capability_refs: set[str] | None = None,
    known_submit_request_refs: set[str] | None = None,
    order_intent: ExecutionOrderIntentRecord | None = None,
    runtime_promotion: RuntimePromotionRecord | None = None,
    order_materialization: ExecutionOrderMaterializationRecord | None = None,
    venue_capability: ExecutionVenueCapabilityRecord | None = None,
    submit_request: ExecutionSubmitRequestRecord | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "submitter_ref",
        "guarded_venue_ref",
        "venue_ref",
        "submission_mode",
        "permission_gate_ref",
        "order_guard_ref",
        "idempotency_key",
        "audit_record_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_missing_required_ref",
                    f"execution order submission requires {field_name}",
                    field=field_name,
                    ref=record.submission_ref,
                )
            )

    mode = str(record.submission_mode or "").lower()
    status = str(record.submission_status or "").lower()
    if mode not in {"record_only", "paper", "testnet", "live"}:
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_bad_mode",
                "execution order submission_mode is outside the supported set",
                field="submission_mode",
                ref=record.submission_ref,
            )
        )
    if status not in {"recorded", "skipped", "submitted", "accepted", "rejected", "failed"}:
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_bad_status",
                "execution order submission_status is outside the supported set",
                field="submission_status",
                ref=record.submission_ref,
            )
        )
    if record.submit_enabled and mode == "record_only":
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_submit_enabled_record_only",
                "submit_enabled order submissions must use paper, testnet, or live mode",
                field="submission_mode",
                ref=record.submission_ref,
            )
        )
    if record.submit_enabled and not _present(record.order_materialization_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_missing_materialization_ref",
                "submit_enabled order submission requires order_materialization_ref",
                field="order_materialization_ref",
                ref=record.submission_ref,
            )
        )
    if record.submit_enabled and not _present(record.venue_capability_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_missing_venue_capability_ref",
                "submit_enabled order submission requires venue_capability_ref",
                field="venue_capability_ref",
                ref=record.submission_ref,
            )
        )
    if record.submit_enabled and not _present(record.submit_request_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_missing_submit_request_ref",
                "submit_enabled order submission requires recorded submit_request_ref",
                field="submit_request_ref",
                ref=record.submission_ref,
            )
        )
    if not record.submit_enabled and status in {"submitted", "accepted"}:
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_status_without_submit",
                "submitted/accepted status requires submit_enabled",
                field="submission_status",
                ref=record.submission_ref,
            )
        )
    if status in {"submitted", "accepted", "rejected"} and not _present(record.ack_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_missing_ack_ref",
                "submitted/accepted/rejected submissions require ack_ref evidence",
                field="ack_ref",
                ref=record.submission_ref,
            )
        )
    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_unknown_order_intent_ref",
                "execution order submission must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.submission_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_unknown_runtime_promotion_ref",
                "execution order submission must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.submission_ref,
            )
        )
    if (
        known_order_materialization_refs is not None
        and _present(record.order_materialization_ref)
        and str(record.order_materialization_ref) not in known_order_materialization_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_unknown_materialization_ref",
                "execution order submission order_materialization_ref must resolve to a recorded materialization",
                field="order_materialization_ref",
                ref=record.submission_ref,
            )
        )
    if (
        known_venue_capability_refs is not None
        and _present(record.venue_capability_ref)
        and str(record.venue_capability_ref) not in known_venue_capability_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_unknown_venue_capability_ref",
                "execution order submission venue_capability_ref must resolve to a recorded venue capability",
                field="venue_capability_ref",
                ref=record.submission_ref,
            )
        )
    if (
        known_submit_request_refs is not None
        and _present(record.submit_request_ref)
        and str(record.submit_request_ref) not in known_submit_request_refs
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "order_submission_unknown_submit_request_ref",
                "execution order submission submit_request_ref must resolve to a recorded submit request",
                field="submit_request_ref",
                ref=record.submission_ref,
            )
        )

    if order_intent is not None:
        expected_pairs = (
            ("venue_ref", order_intent.venue_ref),
            ("permission_gate_ref", order_intent.permission_gate_ref),
            ("order_guard_ref", order_intent.order_guard_ref),
            ("idempotency_key", order_intent.idempotency_key),
            ("kill_switch_ref", order_intent.kill_switch_ref),
            ("secret_ref", order_intent.secret_ref),
            ("responsibility_boundary_ref", order_intent.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_submission_intent_ref_mismatch",
                        f"execution order submission {field_name} must match its order intent",
                        field=field_name,
                        ref=record.submission_ref,
                    )
                )
        intent_runtime = _value(order_intent.runtime)
        if record.submit_enabled and mode != intent_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_runtime_mismatch",
                    "submit_enabled order submission mode must match the order intent runtime",
                    field="submission_mode",
                    ref=record.submission_ref,
                )
            )
        asset_class = str(order_intent.asset_class or "").lower()
        if mode == RuntimeStatus.LIVE.value and asset_class in {"a_share", "equity_cn", "stocks_cn", "cn_equity"}:
            violations.append(
                ExecutionBoundaryViolation(
                    "a_share_live_order_submission_forbidden",
                    "A-share live order submission is unreachable in current governance boundary",
                    field="asset_class",
                    ref=record.submission_ref,
                )
            )

    if runtime_promotion is not None:
        target_runtime = _value(runtime_promotion.target_runtime)
        if record.submit_enabled and mode != target_runtime:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_runtime_promotion_mismatch",
                    "submit_enabled order submission mode must match runtime promotion target_runtime",
                    field="runtime_promotion_ref",
                    ref=record.submission_ref,
                )
            )
        expected_pairs = (
            ("permission_gate_ref", runtime_promotion.permission_gate_ref),
            ("order_guard_ref", runtime_promotion.order_guard_ref),
            ("kill_switch_ref", runtime_promotion.kill_switch_ref),
            ("secret_ref", runtime_promotion.secret_ref),
            ("responsibility_boundary_ref", runtime_promotion.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_submission_promotion_ref_mismatch",
                        f"execution order submission {field_name} must match runtime promotion",
                        field=field_name,
                        ref=record.submission_ref,
                    )
                )

    if order_materialization is not None:
        expected_pairs = (
            ("order_intent_ref", order_materialization.order_intent_ref),
            ("runtime_promotion_ref", order_materialization.runtime_promotion_ref),
            ("permission_gate_ref", order_materialization.permission_gate_ref),
            ("order_guard_ref", order_materialization.order_guard_ref),
            ("idempotency_key", order_materialization.idempotency_key),
            ("kill_switch_ref", order_materialization.kill_switch_ref),
            ("secret_ref", order_materialization.secret_ref),
            ("responsibility_boundary_ref", order_materialization.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_submission_materialization_ref_mismatch",
                        f"execution order submission {field_name} must match materialization",
                        field=field_name,
                        ref=record.submission_ref,
                    )
                )
        if record.order_materialization_ref != order_materialization.materialization_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_materialization_ref_mismatch",
                    "execution order submission must reference the supplied materialization_ref",
                    field="order_materialization_ref",
                    ref=record.submission_ref,
                )
            )
        if record.submit_enabled and order_materialization.materialization_status != "materialized":
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_materialization_not_ready",
                    "submit_enabled order submission requires materialized order payload hash refs",
                    field="order_materialization_ref",
                    ref=record.submission_ref,
                )
            )

    if venue_capability is not None:
        expected_pairs = (
            ("order_intent_ref", venue_capability.order_intent_ref),
            ("runtime_promotion_ref", venue_capability.runtime_promotion_ref),
            ("submitter_ref", venue_capability.submitter_ref),
            ("guarded_venue_ref", venue_capability.guarded_venue_ref),
            ("venue_ref", venue_capability.venue_ref),
            ("permission_gate_ref", venue_capability.permission_gate_ref),
            ("order_guard_ref", venue_capability.order_guard_ref),
            ("idempotency_key", venue_capability.idempotency_key),
            ("kill_switch_ref", venue_capability.kill_switch_ref),
            ("secret_ref", venue_capability.secret_ref),
            ("responsibility_boundary_ref", venue_capability.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_submission_venue_capability_ref_mismatch",
                        f"execution order submission {field_name} must match venue capability",
                        field=field_name,
                        ref=record.submission_ref,
                    )
                )
        if record.venue_capability_ref != venue_capability.venue_capability_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_venue_capability_ref_mismatch",
                    "execution order submission must reference the supplied venue_capability_ref",
                    field="venue_capability_ref",
                    ref=record.submission_ref,
                )
            )
        if record.submit_enabled and (
            venue_capability.capability_status != "ready" or not venue_capability.can_submit_orders
        ):
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_venue_capability_not_ready",
                    "submit_enabled order submission requires ready venue capability",
                    field="venue_capability_ref",
                    ref=record.submission_ref,
                )
            )
        if record.submit_enabled and mode != str(venue_capability.runtime or "").lower():
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_venue_capability_runtime_mismatch",
                    "submit_enabled order submission mode must match venue capability runtime",
                    field="submission_mode",
                    ref=record.submission_ref,
                )
            )

    if submit_request is not None:
        expected_pairs = (
            ("order_intent_ref", submit_request.order_intent_ref),
            ("runtime_promotion_ref", submit_request.runtime_promotion_ref),
            ("order_materialization_ref", submit_request.order_materialization_ref),
            ("venue_capability_ref", submit_request.venue_capability_ref),
            ("submitter_ref", submit_request.submitter_ref),
            ("guarded_venue_ref", submit_request.guarded_venue_ref),
            ("venue_ref", submit_request.venue_ref),
            ("permission_gate_ref", submit_request.permission_gate_ref),
            ("order_guard_ref", submit_request.order_guard_ref),
            ("idempotency_key", submit_request.idempotency_key),
            ("kill_switch_ref", submit_request.kill_switch_ref),
            ("secret_ref", submit_request.secret_ref),
            ("responsibility_boundary_ref", submit_request.responsibility_boundary_ref),
        )
        for field_name, expected in expected_pairs:
            actual = getattr(record, field_name)
            if _present(expected) and actual != expected:
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_submission_submit_request_ref_mismatch",
                        f"execution order submission {field_name} must match submit request",
                        field=field_name,
                        ref=record.submission_ref,
                    )
                )
        if record.submit_request_ref != submit_request.submit_request_ref:
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_submit_request_ref_mismatch",
                    "execution order submission must reference the supplied submit_request_ref",
                    field="submit_request_ref",
                    ref=record.submission_ref,
                )
            )
        if record.submit_enabled and submit_request.submit_request_status != "ready":
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_submit_request_not_ready",
                    "submit_enabled order submission requires ready submit request envelope",
                    field="submit_request_ref",
                    ref=record.submission_ref,
                )
            )
        if record.submit_enabled and mode != str(submit_request.submit_request_mode or "").lower():
            violations.append(
                ExecutionBoundaryViolation(
                    "order_submission_submit_request_runtime_mismatch",
                    "submit_enabled order submission mode must match submit request mode",
                    field="submission_mode",
                    ref=record.submission_ref,
                )
            )

    if mode in {RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        for field_name in (
            "kill_switch_ref",
            "secret_ref",
            "responsibility_boundary_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "order_submission_missing_execution_invariant",
                        f"{mode} order submission requires {field_name}",
                        field=field_name,
                        ref=record.submission_ref,
                    )
                )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_venue_event_from_dict(data: dict[str, Any]) -> ExecutionVenueEventRecord:
    return ExecutionVenueEventRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        event_kind=str(data.get("event_kind") or ""),
        status=str(data.get("status") or ""),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        order_guard_ref=str(data.get("order_guard_ref") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        venue_order_ref=data.get("venue_order_ref"),
        client_order_ref=data.get("client_order_ref"),
        ack_ref=data.get("ack_ref"),
        fill_ref=data.get("fill_ref"),
        reconcile_ref=data.get("reconcile_ref"),
        quantity_ref=data.get("quantity_ref"),
        price_ref=data.get("price_ref"),
        fee_ref=data.get("fee_ref"),
        raw_event_hash=data.get("raw_event_hash"),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        venue_event_ref=str(data.get("venue_event_ref") or ""),
    )


def validate_execution_venue_event(
    record: ExecutionVenueEventRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in (
        "order_intent_ref",
        "runtime_promotion_ref",
        "venue_ref",
        "event_kind",
        "status",
        "audit_record_ref",
        "order_guard_ref",
        "idempotency_key",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "venue_event_missing_required_ref",
                    f"execution venue event requires {field_name}",
                    field=field_name,
                    ref=record.venue_event_ref,
                )
            )
    event_kind = str(record.event_kind or "").lower()
    if event_kind not in {
        "submitted",
        "accepted",
        "rejected",
        "partially_filled",
        "filled",
        "canceled",
        "expired",
        "reconciled",
    }:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_event_bad_kind",
                "execution venue event_kind is outside the supported audit event set",
                field="event_kind",
                ref=record.venue_event_ref,
            )
        )
    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_event_unknown_order_intent_ref",
                "execution venue event must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.venue_event_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "venue_event_unknown_runtime_promotion_ref",
                "execution venue event must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.venue_event_ref,
            )
        )
    if event_kind in {"accepted", "partially_filled", "filled", "canceled", "expired", "reconciled"} and not _present(
        record.venue_order_ref
    ):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_event_missing_venue_order_ref",
                "venue ack/fill/cancel/reconcile events require venue_order_ref",
                field="venue_order_ref",
                ref=record.venue_event_ref,
            )
        )
    if event_kind in {"accepted", "rejected"} and not _present(record.ack_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_event_missing_ack_ref",
                "venue accepted/rejected events require ack_ref",
                field="ack_ref",
                ref=record.venue_event_ref,
            )
        )
    if event_kind in {"partially_filled", "filled"}:
        for field_name in ("fill_ref", "quantity_ref", "price_ref"):
            if not _present(getattr(record, field_name)):
                violations.append(
                    ExecutionBoundaryViolation(
                        "venue_event_missing_fill_ref",
                        f"venue fill events require {field_name}",
                        field=field_name,
                        ref=record.venue_event_ref,
                    )
                )
    if event_kind == "reconciled" and not _present(record.reconcile_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "venue_event_missing_reconcile_ref",
                "venue reconciled event requires reconcile_ref",
                field="reconcile_ref",
                ref=record.venue_event_ref,
            )
        )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def execution_reconciliation_from_dict(data: dict[str, Any]) -> ExecutionReconciliationRecord:
    return ExecutionReconciliationRecord(
        order_intent_ref=str(data.get("order_intent_ref") or ""),
        runtime_promotion_ref=str(data.get("runtime_promotion_ref") or ""),
        venue_order_ref=data.get("venue_order_ref"),
        event_refs=_str_tuple(data.get("event_refs")),
        status=str(data.get("status") or "missing_events"),
        discrepancy_refs=_str_tuple(data.get("discrepancy_refs")),
        action_required=bool(data.get("action_required", True)),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        reconciliation_ref=str(data.get("reconciliation_ref") or ""),
    )


def execution_reconciliation_action_from_dict(data: dict[str, Any]) -> ExecutionReconciliationActionRecord:
    return ExecutionReconciliationActionRecord(
        reconciliation_ref=str(data.get("reconciliation_ref") or ""),
        action_kind=str(data.get("action_kind") or ""),
        action_status=str(data.get("action_status") or "open"),
        action_owner_ref=data.get("action_owner_ref"),
        remediation_ref=data.get("remediation_ref"),
        halt_plan_ref=data.get("halt_plan_ref"),
        waiver_ref=data.get("waiver_ref"),
        audit_record_ref=str(data.get("audit_record_ref") or ""),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        action_ref=str(data.get("action_ref") or ""),
    )


def reconcile_execution_venue_events(
    *,
    order_intent_ref: str,
    runtime_promotion_ref: str,
    audit_record_ref: str,
    events: tuple[ExecutionVenueEventRecord, ...],
    venue_order_ref: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    recorded_by: str = "system",
) -> ExecutionReconciliationRecord:
    matching = tuple(
        event
        for event in events
        if event.order_intent_ref == order_intent_ref
        and event.runtime_promotion_ref == runtime_promotion_ref
        and (not _present(venue_order_ref) or event.venue_order_ref == venue_order_ref)
    )
    event_refs = tuple(event.venue_event_ref for event in matching)
    event_kinds = {str(event.event_kind or "").lower() for event in matching}
    statuses = {str(event.status or "").lower() for event in matching}
    venue_order_refs = {str(event.venue_order_ref) for event in matching if _present(event.venue_order_ref)}
    discrepancy_refs: list[str] = []

    if not matching:
        status = "missing_events"
        discrepancy_refs.append("missing_venue_events")
    elif len(venue_order_refs) > 1:
        status = "venue_order_mismatch"
        discrepancy_refs.append("multiple_venue_order_refs")
    elif {"filled", "canceled"} <= event_kinds or {"filled", "rejected"} <= event_kinds:
        status = "terminal_conflict"
        discrepancy_refs.append("conflicting_terminal_events")
    elif "reconciled" in event_kinds:
        status = "reconciled"
    elif event_kinds & {"filled", "partially_filled"} or statuses & {"filled", "partially_filled"}:
        status = "needs_reconcile"
        discrepancy_refs.append("missing_reconcile_event")
    elif event_kinds & {"canceled", "expired", "rejected"} or statuses & {"canceled", "expired", "rejected"}:
        status = "closed_no_fill"
    else:
        status = "open"
        discrepancy_refs.append("no_terminal_event")

    action_required = status not in {"reconciled", "closed_no_fill"}
    if _present(venue_order_ref) and venue_order_refs and venue_order_ref not in venue_order_refs:
        status = "venue_order_mismatch"
        discrepancy_refs.append("requested_venue_order_ref_not_observed")
        action_required = True
    observed_venue_order_ref = venue_order_ref or (sorted(venue_order_refs)[0] if len(venue_order_refs) == 1 else None)
    return ExecutionReconciliationRecord(
        order_intent_ref=order_intent_ref,
        runtime_promotion_ref=runtime_promotion_ref,
        venue_order_ref=observed_venue_order_ref,
        event_refs=event_refs,
        status=status,
        discrepancy_refs=tuple(dict.fromkeys(discrepancy_refs)),
        action_required=action_required,
        audit_record_ref=audit_record_ref,
        evidence_refs=evidence_refs,
        recorded_by=recorded_by,
    )


def validate_execution_reconciliation(
    record: ExecutionReconciliationRecord,
    *,
    known_order_intent_refs: set[str] | None = None,
    known_runtime_promotion_refs: set[str] | None = None,
    known_venue_event_refs: set[str] | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in ("order_intent_ref", "runtime_promotion_ref", "audit_record_ref", "status"):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "execution_reconcile_missing_required_ref",
                    f"execution reconciliation requires {field_name}",
                    field=field_name,
                    ref=record.reconciliation_ref,
                )
            )
    if record.status not in {
        "missing_events",
        "open",
        "needs_reconcile",
        "reconciled",
        "closed_no_fill",
        "terminal_conflict",
        "venue_order_mismatch",
    }:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_bad_status",
                "execution reconciliation status is outside the supported set",
                field="status",
                ref=record.reconciliation_ref,
            )
        )
    if record.status in {"reconciled", "closed_no_fill"} and record.action_required:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_terminal_action_required",
                "terminal reconciled/closed_no_fill states cannot require action",
                field="action_required",
                ref=record.reconciliation_ref,
            )
        )
    if record.status in {"missing_events", "open", "needs_reconcile", "terminal_conflict", "venue_order_mismatch"}:
        if not record.action_required:
            violations.append(
                ExecutionBoundaryViolation(
                    "execution_reconcile_open_without_action",
                    "non-terminal reconciliation states must require follow-up action",
                    field="action_required",
                    ref=record.reconciliation_ref,
                )
            )
        if not record.discrepancy_refs:
            violations.append(
                ExecutionBoundaryViolation(
                    "execution_reconcile_missing_discrepancy_ref",
                    "non-terminal reconciliation states require discrepancy_refs",
                    field="discrepancy_refs",
                    ref=record.reconciliation_ref,
                )
            )
    if known_order_intent_refs is not None and record.order_intent_ref not in known_order_intent_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_unknown_order_intent_ref",
                "execution reconciliation must resolve to a recorded order intent",
                field="order_intent_ref",
                ref=record.reconciliation_ref,
            )
        )
    if known_runtime_promotion_refs is not None and record.runtime_promotion_ref not in known_runtime_promotion_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_unknown_runtime_promotion_ref",
                "execution reconciliation must resolve to a recorded runtime promotion",
                field="runtime_promotion_ref",
                ref=record.reconciliation_ref,
            )
        )
    if known_venue_event_refs is not None:
        missing = [event_ref for event_ref in record.event_refs if event_ref not in known_venue_event_refs]
        if missing:
            violations.append(
                ExecutionBoundaryViolation(
                    "execution_reconcile_unknown_venue_event_ref",
                    "execution reconciliation event_refs must resolve to recorded venue events",
                    field="event_refs",
                    ref=record.reconciliation_ref,
                )
            )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_execution_reconciliation_action(
    record: ExecutionReconciliationActionRecord,
    *,
    known_reconciliation_refs: set[str] | None = None,
    action_required_by_ref: dict[str, bool] | None = None,
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    for field_name in ("reconciliation_ref", "action_kind", "action_status", "audit_record_ref"):
        if not _present(getattr(record, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "execution_reconcile_action_missing_required_ref",
                    f"execution reconciliation action requires {field_name}",
                    field=field_name,
                    ref=record.action_ref,
                )
            )
    allowed_kinds = {
        "investigate",
        "halt_runtime",
        "request_missing_reconcile",
        "escalate_manual_review",
        "waive_with_evidence",
    }
    if record.action_kind not in allowed_kinds:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_bad_kind",
                "execution reconciliation action_kind is outside the supported set",
                field="action_kind",
                ref=record.action_ref,
            )
        )
    if record.action_status not in {"open", "acknowledged", "completed", "waived"}:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_bad_status",
                "execution reconciliation action_status is outside the supported set",
                field="action_status",
                ref=record.action_ref,
            )
        )
    if known_reconciliation_refs is not None and record.reconciliation_ref not in known_reconciliation_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_unknown_reconciliation_ref",
                "execution reconciliation action must resolve to a recorded reconciliation",
                field="reconciliation_ref",
                ref=record.action_ref,
            )
        )
    if action_required_by_ref is not None and action_required_by_ref.get(record.reconciliation_ref) is False:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_not_required",
                "execution reconciliation action can only be recorded for action_required reconciliations",
                field="reconciliation_ref",
                ref=record.action_ref,
            )
        )
    if not record.evidence_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_missing_evidence",
                "execution reconciliation actions require evidence_refs",
                field="evidence_refs",
                ref=record.action_ref,
            )
        )
    if record.action_kind == "halt_runtime" and not _present(record.halt_plan_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_missing_halt_plan",
                "halt_runtime actions require halt_plan_ref",
                field="halt_plan_ref",
                ref=record.action_ref,
            )
        )
    if record.action_kind == "waive_with_evidence" and not _present(record.waiver_ref):
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_missing_waiver",
                "waive_with_evidence actions require waiver_ref",
                field="waiver_ref",
                ref=record.action_ref,
            )
        )
    if record.action_status in {"completed", "waived"} and not (_present(record.remediation_ref) or _present(record.waiver_ref)):
        violations.append(
            ExecutionBoundaryViolation(
                "execution_reconcile_action_closed_without_resolution_ref",
                "closed reconciliation actions require remediation_ref or waiver_ref",
                field="remediation_ref",
                ref=record.action_ref,
            )
        )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


class PersistentExecutionOrderIntentRegistry:
    """Append-only order-intent registry.

    Records order intent refs and policy refs only. It does not place orders and
    does not store raw quantities, prices, API keys, or venue payloads.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionOrderIntentRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution order intent schema_version")
                if row.get("event_type") != "execution_order_intent_recorded":
                    raise ValueError("unsupported execution order intent event_type")
                payload = row.get("order_intent")
                if not isinstance(payload, dict):
                    raise ValueError("missing order_intent")
                record = execution_order_intent_from_dict(payload)
                decision = validate_execution_order_intent(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution order intent record: {codes}")
                self._records[record.order_intent_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution order intent row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionOrderIntentRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_order_intent_recorded",
            "order_intent": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_intent(
        self,
        record: ExecutionOrderIntentRecord,
        *,
        known_signal_validation_refs: set[str] | None = None,
        known_market_data_use_validation_refs: set[str] | None = None,
    ) -> ExecutionOrderIntentRecord:
        decision = validate_execution_order_intent(
            record,
            known_signal_validation_refs=known_signal_validation_refs,
            known_market_data_use_validation_refs=known_market_data_use_validation_refs,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.order_intent_ref] = record
        self._append(record)
        return record

    def intent(self, order_intent_ref: str) -> ExecutionOrderIntentRecord:
        if order_intent_ref not in self._records:
            raise KeyError(f"unknown execution order intent: {order_intent_ref}")
        return self._records[order_intent_ref]

    def intents(self) -> list[ExecutionOrderIntentRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.order_intent_ref))


class PersistentExecutionOrderMaterializationRegistry:
    """Append-only order materialization registry.

    Records refs and hashes needed for guarded submission. It never persists raw
    order payloads, quantities, prices, API keys, or venue-native requests.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionOrderMaterializationRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution order materialization schema_version")
                if row.get("event_type") != "execution_order_materialization_recorded":
                    raise ValueError("unsupported execution order materialization event_type")
                payload = row.get("order_materialization")
                if not isinstance(payload, dict):
                    raise ValueError("missing order_materialization")
                record = execution_order_materialization_from_dict(payload)
                decision = validate_execution_order_materialization(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution order materialization record: {codes}")
                self._records[record.materialization_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution order materialization row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionOrderMaterializationRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_order_materialization_recorded",
            "order_materialization": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_materialization(
        self,
        record: ExecutionOrderMaterializationRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        order_intent: ExecutionOrderIntentRecord | None = None,
        runtime_promotion: RuntimePromotionRecord | None = None,
    ) -> ExecutionOrderMaterializationRecord:
        decision = validate_execution_order_materialization(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.materialization_ref] = record
        self._append(record)
        return record

    def materialization(self, materialization_ref: str) -> ExecutionOrderMaterializationRecord:
        if materialization_ref not in self._records:
            raise KeyError(f"unknown execution order materialization: {materialization_ref}")
        return self._records[materialization_ref]

    def materializations(self) -> list[ExecutionOrderMaterializationRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.materialization_ref))


class PersistentExecutionVenueConnectivityCheckRegistry:
    """Append-only guarded venue connectivity check registry.

    Records refs and hashes from a venue connectivity checker. It never stores
    API keys, raw orders, raw venue payloads, quantities, or prices.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionVenueConnectivityCheckRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution venue connectivity check schema_version")
                if row.get("event_type") != "execution_venue_connectivity_check_recorded":
                    raise ValueError("unsupported execution venue connectivity check event_type")
                payload = row.get("venue_connectivity_check")
                if not isinstance(payload, dict):
                    raise ValueError("missing venue_connectivity_check")
                record = execution_venue_connectivity_check_from_dict(payload)
                decision = validate_execution_venue_connectivity_check(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution venue connectivity check record: {codes}")
                self._records[record.venue_connectivity_check_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(
                    f"invalid persisted execution venue connectivity check row at {self._path}:{line_no}"
                ) from exc

    def _append(self, record: ExecutionVenueConnectivityCheckRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_venue_connectivity_check_recorded",
            "venue_connectivity_check": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_check(
        self,
        record: ExecutionVenueConnectivityCheckRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        order_intent: ExecutionOrderIntentRecord | None = None,
        runtime_promotion: RuntimePromotionRecord | None = None,
    ) -> ExecutionVenueConnectivityCheckRecord:
        decision = validate_execution_venue_connectivity_check(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.venue_connectivity_check_ref] = record
        self._append(record)
        return record

    def check(self, venue_connectivity_check_ref: str) -> ExecutionVenueConnectivityCheckRecord:
        if venue_connectivity_check_ref not in self._records:
            raise KeyError(f"unknown execution venue connectivity check: {venue_connectivity_check_ref}")
        return self._records[venue_connectivity_check_ref]

    def checks(self) -> list[ExecutionVenueConnectivityCheckRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.venue_connectivity_check_ref))


class PersistentExecutionVenueSafetyAttestationRegistry:
    """Append-only guarded venue safety attestation registry.

    Records evidence refs backing venue capability readiness. It never stores
    API keys, raw orders, raw venue payloads, quantities, or prices.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionVenueSafetyAttestationRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution venue safety attestation schema_version")
                if row.get("event_type") != "execution_venue_safety_attestation_recorded":
                    raise ValueError("unsupported execution venue safety attestation event_type")
                payload = row.get("venue_safety_attestation")
                if not isinstance(payload, dict):
                    raise ValueError("missing venue_safety_attestation")
                record = execution_venue_safety_attestation_from_dict(payload)
                decision = validate_execution_venue_safety_attestation(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution venue safety attestation record: {codes}")
                self._records[record.venue_safety_attestation_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution venue safety attestation row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionVenueSafetyAttestationRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_venue_safety_attestation_recorded",
            "venue_safety_attestation": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_attestation(
        self,
        record: ExecutionVenueSafetyAttestationRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        known_venue_connectivity_check_refs: set[str] | None = None,
        order_intent: ExecutionOrderIntentRecord | None = None,
        runtime_promotion: RuntimePromotionRecord | None = None,
        venue_connectivity_check: ExecutionVenueConnectivityCheckRecord | None = None,
    ) -> ExecutionVenueSafetyAttestationRecord:
        decision = validate_execution_venue_safety_attestation(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            known_venue_connectivity_check_refs=known_venue_connectivity_check_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            venue_connectivity_check=venue_connectivity_check,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.venue_safety_attestation_ref] = record
        self._append(record)
        return record

    def attestation(self, venue_safety_attestation_ref: str) -> ExecutionVenueSafetyAttestationRecord:
        if venue_safety_attestation_ref not in self._records:
            raise KeyError(f"unknown execution venue safety attestation: {venue_safety_attestation_ref}")
        return self._records[venue_safety_attestation_ref]

    def attestations(self) -> list[ExecutionVenueSafetyAttestationRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.venue_safety_attestation_ref))


class PersistentExecutionVenueCapabilityRegistry:
    """Append-only guarded venue capability registry.

    Records readiness refs for a guarded submitter and venue. It never stores
    API keys, raw orders, raw venue payloads, quantities, or prices.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionVenueCapabilityRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution venue capability schema_version")
                if row.get("event_type") != "execution_venue_capability_recorded":
                    raise ValueError("unsupported execution venue capability event_type")
                payload = row.get("venue_capability")
                if not isinstance(payload, dict):
                    raise ValueError("missing venue_capability")
                record = execution_venue_capability_from_dict(payload)
                decision = validate_execution_venue_capability(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution venue capability record: {codes}")
                self._records[record.venue_capability_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution venue capability row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionVenueCapabilityRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_venue_capability_recorded",
            "venue_capability": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_capability(
        self,
        record: ExecutionVenueCapabilityRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        known_venue_safety_attestation_refs: set[str] | None = None,
        order_intent: ExecutionOrderIntentRecord | None = None,
        runtime_promotion: RuntimePromotionRecord | None = None,
        venue_safety_attestation: ExecutionVenueSafetyAttestationRecord | None = None,
    ) -> ExecutionVenueCapabilityRecord:
        decision = validate_execution_venue_capability(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            known_venue_safety_attestation_refs=known_venue_safety_attestation_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            venue_safety_attestation=venue_safety_attestation,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.venue_capability_ref] = record
        self._append(record)
        return record

    def capability(self, venue_capability_ref: str) -> ExecutionVenueCapabilityRecord:
        if venue_capability_ref not in self._records:
            raise KeyError(f"unknown execution venue capability: {venue_capability_ref}")
        return self._records[venue_capability_ref]

    def capabilities(self) -> list[ExecutionVenueCapabilityRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.venue_capability_ref))


class PersistentExecutionSubmitRequestRegistry:
    """Append-only submit request envelope registry.

    The registry records refs and hashes that authorize a guarded submission.
    It never stores raw orders, raw venue payloads, API keys, quantities, or prices.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionSubmitRequestRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution submit request schema_version")
                if row.get("event_type") != "execution_submit_request_recorded":
                    raise ValueError("unsupported execution submit request event_type")
                payload = row.get("submit_request")
                if not isinstance(payload, dict):
                    raise ValueError("missing submit_request")
                record = execution_submit_request_from_dict(payload)
                decision = validate_execution_submit_request(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution submit request record: {codes}")
                self._records[record.submit_request_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution submit request row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionSubmitRequestRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_submit_request_recorded",
            "submit_request": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_request(
        self,
        record: ExecutionSubmitRequestRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        known_order_materialization_refs: set[str] | None = None,
        known_venue_capability_refs: set[str] | None = None,
        order_intent: ExecutionOrderIntentRecord | None = None,
        runtime_promotion: RuntimePromotionRecord | None = None,
        order_materialization: ExecutionOrderMaterializationRecord | None = None,
        venue_capability: ExecutionVenueCapabilityRecord | None = None,
    ) -> ExecutionSubmitRequestRecord:
        decision = validate_execution_submit_request(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.submit_request_ref] = record
        self._append(record)
        return record

    def request(self, submit_request_ref: str) -> ExecutionSubmitRequestRecord:
        if submit_request_ref not in self._records:
            raise KeyError(f"unknown execution submit request: {submit_request_ref}")
        return self._records[submit_request_ref]

    def requests(self) -> list[ExecutionSubmitRequestRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.submit_request_ref))


class PersistentExecutionOrderSubmissionRegistry:
    """Append-only guarded submission registry.

    The registry records refs around a guarded submitter call. It never stores
    raw orders, raw venue payloads, API keys, quantities, or prices.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionOrderSubmissionRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution order submission schema_version")
                if row.get("event_type") != "execution_order_submission_recorded":
                    raise ValueError("unsupported execution order submission event_type")
                payload = row.get("order_submission")
                if not isinstance(payload, dict):
                    raise ValueError("missing order_submission")
                record = execution_order_submission_from_dict(payload)
                decision = validate_execution_order_submission(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution order submission record: {codes}")
                self._records[record.submission_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution order submission row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionOrderSubmissionRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_order_submission_recorded",
            "order_submission": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_submission(
        self,
        record: ExecutionOrderSubmissionRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        known_order_materialization_refs: set[str] | None = None,
        known_venue_capability_refs: set[str] | None = None,
        known_submit_request_refs: set[str] | None = None,
        order_intent: ExecutionOrderIntentRecord | None = None,
        runtime_promotion: RuntimePromotionRecord | None = None,
        order_materialization: ExecutionOrderMaterializationRecord | None = None,
        venue_capability: ExecutionVenueCapabilityRecord | None = None,
        submit_request: ExecutionSubmitRequestRecord | None = None,
    ) -> ExecutionOrderSubmissionRecord:
        decision = validate_execution_order_submission(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.submission_ref] = record
        self._append(record)
        return record

    def submission(self, submission_ref: str) -> ExecutionOrderSubmissionRecord:
        if submission_ref not in self._records:
            raise KeyError(f"unknown execution order submission: {submission_ref}")
        return self._records[submission_ref]

    def submissions(self) -> list[ExecutionOrderSubmissionRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.submission_ref))


class PersistentRuntimePromotionRegistry:
    """Append-only runtime promotion registry.

    The registry records environment transition decisions and their required
    guard refs. It does not place orders, call venues, or mutate account state.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, RuntimePromotionRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported runtime promotion schema_version")
                if row.get("event_type") != "runtime_promotion_recorded":
                    raise ValueError("unsupported runtime promotion event_type")
                payload = row.get("runtime_promotion")
                if not isinstance(payload, dict):
                    raise ValueError("missing runtime_promotion")
                record = runtime_promotion_record_from_dict(payload)
                decision = validate_runtime_promotion_record(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid runtime promotion record: {codes}")
                self._records[record.runtime_promotion_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted runtime promotion row at {self._path}:{line_no}") from exc

    def _append(self, record: RuntimePromotionRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "runtime_promotion_recorded",
            "runtime_promotion": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_promotion(self, record: RuntimePromotionRecord) -> RuntimePromotionRecord:
        decision = validate_runtime_promotion_record(record)
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.runtime_promotion_ref] = record
        self._append(record)
        return record

    def promotion(self, runtime_promotion_ref: str) -> RuntimePromotionRecord:
        if runtime_promotion_ref not in self._records:
            raise KeyError(f"unknown runtime promotion: {runtime_promotion_ref}")
        return self._records[runtime_promotion_ref]

    def promotions(self) -> list[RuntimePromotionRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.runtime_promotion_ref))


class PersistentExecutionVenueEventRegistry:
    """Append-only venue event registry.

    This records venue ack/fill/reconcile evidence refs. It never calls a venue
    and never stores raw venue payloads or order material.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionVenueEventRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution venue event schema_version")
                if row.get("event_type") != "execution_venue_event_recorded":
                    raise ValueError("unsupported execution venue event event_type")
                payload = row.get("venue_event")
                if not isinstance(payload, dict):
                    raise ValueError("missing venue_event")
                record = execution_venue_event_from_dict(payload)
                decision = validate_execution_venue_event(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution venue event record: {codes}")
                self._records[record.venue_event_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt execution history must be visible.
                raise ValueError(f"invalid persisted execution venue event row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionVenueEventRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_venue_event_recorded",
            "venue_event": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_event(
        self,
        record: ExecutionVenueEventRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
    ) -> ExecutionVenueEventRecord:
        decision = validate_execution_venue_event(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.venue_event_ref] = record
        self._append(record)
        return record

    def event(self, venue_event_ref: str) -> ExecutionVenueEventRecord:
        if venue_event_ref not in self._records:
            raise KeyError(f"unknown execution venue event: {venue_event_ref}")
        return self._records[venue_event_ref]

    def events(self) -> list[ExecutionVenueEventRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.venue_event_ref))


class PersistentExecutionReconciliationRegistry:
    """Append-only execution reconciliation registry."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionReconciliationRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution reconciliation schema_version")
                if row.get("event_type") != "execution_reconciliation_recorded":
                    raise ValueError("unsupported execution reconciliation event_type")
                payload = row.get("reconciliation")
                if not isinstance(payload, dict):
                    raise ValueError("missing reconciliation")
                record = execution_reconciliation_from_dict(payload)
                decision = validate_execution_reconciliation(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution reconciliation record: {codes}")
                self._records[record.reconciliation_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt reconciliation history must be visible.
                raise ValueError(f"invalid persisted execution reconciliation row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionReconciliationRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_reconciliation_recorded",
            "reconciliation": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_reconciliation(
        self,
        record: ExecutionReconciliationRecord,
        *,
        known_order_intent_refs: set[str] | None = None,
        known_runtime_promotion_refs: set[str] | None = None,
        known_venue_event_refs: set[str] | None = None,
    ) -> ExecutionReconciliationRecord:
        decision = validate_execution_reconciliation(
            record,
            known_order_intent_refs=known_order_intent_refs,
            known_runtime_promotion_refs=known_runtime_promotion_refs,
            known_venue_event_refs=known_venue_event_refs,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.reconciliation_ref] = record
        self._append(record)
        return record

    def reconciliation(self, reconciliation_ref: str) -> ExecutionReconciliationRecord:
        if reconciliation_ref not in self._records:
            raise KeyError(f"unknown execution reconciliation: {reconciliation_ref}")
        return self._records[reconciliation_ref]

    def reconciliations(self) -> list[ExecutionReconciliationRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.reconciliation_ref))


class PersistentExecutionReconciliationActionRegistry:
    """Append-only reconciliation action registry."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: dict[str, ExecutionReconciliationActionRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported execution reconciliation action schema_version")
                if row.get("event_type") != "execution_reconciliation_action_recorded":
                    raise ValueError("unsupported execution reconciliation action event_type")
                payload = row.get("action")
                if not isinstance(payload, dict):
                    raise ValueError("missing reconciliation action")
                record = execution_reconciliation_action_from_dict(payload)
                decision = validate_execution_reconciliation_action(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid execution reconciliation action record: {codes}")
                self._records[record.action_ref] = record
            except Exception as exc:  # noqa: BLE001 - corrupt action history must be visible.
                raise ValueError(f"invalid persisted execution reconciliation action row at {self._path}:{line_no}") from exc

    def _append(self, record: ExecutionReconciliationActionRecord) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "execution_reconciliation_action_recorded",
            "action": record.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def record_action(
        self,
        record: ExecutionReconciliationActionRecord,
        *,
        known_reconciliation_refs: set[str] | None = None,
        action_required_by_ref: dict[str, bool] | None = None,
    ) -> ExecutionReconciliationActionRecord:
        decision = validate_execution_reconciliation_action(
            record,
            known_reconciliation_refs=known_reconciliation_refs,
            action_required_by_ref=action_required_by_ref,
        )
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        self._records[record.action_ref] = record
        self._append(record)
        return record

    def action(self, action_ref: str) -> ExecutionReconciliationActionRecord:
        if action_ref not in self._records:
            raise KeyError(f"unknown execution reconciliation action: {action_ref}")
        return self._records[action_ref]

    def actions(self) -> list[ExecutionReconciliationActionRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at_utc, item.action_ref))


def validate_user_risk_choice(choice: UserRiskChoiceRecord) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    required = (
        "cost_disclosure_ref",
        "leverage_disclosure_ref",
        "margin_disclosure_ref",
        "slippage_disclosure_ref",
        "liquidation_disclosure_ref",
        "regulation_disclosure_ref",
        "recommendation_ref",
        "responsibility_boundary_ref",
    )
    for field_name in required:
        if not _present(getattr(choice, field_name)):
            violations.append(
                ExecutionBoundaryViolation(
                    "risk_choice_missing_responsibility_boundary",
                    "user risk choices require disclosures, recommendation, and responsibility boundary",
                    field=field_name,
                    ref=choice.choice_ref,
                )
            )
    if not choice.failure_mode_refs:
        violations.append(
            ExecutionBoundaryViolation(
                "risk_choice_missing_failure_modes",
                "user risk choices require failure-mode disclosure",
                field="failure_mode_refs",
                ref=choice.choice_ref,
            )
        )
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_execution_boundary(
    promotion: RuntimePromotionRequest,
    *,
    drift_actions: tuple[DriftTriggeredAction, ...] = (),
    halt_recovery_plans: tuple[HaltRecoveryPlan, ...] = (),
    math_claims: tuple[ExecutionMathClaim, ...] = (),
    user_risk_choices: tuple[UserRiskChoiceRecord, ...] = (),
) -> ExecutionBoundaryDecision:
    violations: list[ExecutionBoundaryViolation] = []
    violations.extend(validate_runtime_promotion(promotion).violations)
    for action in drift_actions:
        violations.extend(validate_drift_triggered_action(action).violations)
    for plan in halt_recovery_plans:
        violations.extend(validate_halt_recovery(plan).violations)
    for claim in math_claims:
        violations.extend(validate_execution_math_claim(claim).violations)
    for choice in user_risk_choices:
        violations.extend(validate_user_risk_choice(choice).violations)
    return ExecutionBoundaryDecision(accepted=not violations, violations=tuple(violations))


__all__ = [
    "DriftTriggeredAction",
    "ExecutionBoundaryDecision",
    "ExecutionBoundaryViolation",
    "ExecutionMathClaim",
    "ExecutionOrderIntentRecord",
    "ExecutionOrderMaterializationRecord",
    "ExecutionOrderSubmissionRecord",
    "ExecutionSubmitRequestRecord",
    "ExecutionVenueConnectivityCheckRecord",
    "ExecutionReconciliationActionRecord",
    "ExecutionReconciliationRecord",
    "ExecutionVenueCapabilityRecord",
    "ExecutionVenueEventRecord",
    "ExecutionVenueSafetyAttestationRecord",
    "HaltRecoveryPlan",
    "PersistentExecutionOrderMaterializationRegistry",
    "PersistentExecutionOrderSubmissionRegistry",
    "PersistentExecutionSubmitRequestRegistry",
    "PersistentExecutionVenueConnectivityCheckRegistry",
    "PersistentExecutionReconciliationActionRegistry",
    "PersistentExecutionReconciliationRegistry",
    "PersistentExecutionVenueCapabilityRegistry",
    "PersistentExecutionVenueEventRegistry",
    "PersistentExecutionVenueSafetyAttestationRegistry",
    "PersistentExecutionOrderIntentRegistry",
    "PersistentRuntimePromotionRegistry",
    "RuntimePromotionRecord",
    "RuntimePromotionRequest",
    "UserRiskChoiceRecord",
    "execution_order_intent_from_dict",
    "execution_order_materialization_from_dict",
    "execution_order_submission_from_dict",
    "execution_submit_request_from_dict",
    "execution_venue_connectivity_check_from_dict",
    "execution_reconciliation_action_from_dict",
    "execution_reconciliation_from_dict",
    "execution_venue_capability_from_dict",
    "execution_venue_event_from_dict",
    "execution_venue_safety_attestation_from_dict",
    "reconcile_execution_venue_events",
    "runtime_promotion_record_from_dict",
    "validate_drift_triggered_action",
    "validate_execution_boundary",
    "validate_execution_math_claim",
    "validate_execution_order_intent",
    "validate_execution_order_materialization",
    "validate_execution_order_submission",
    "validate_execution_submit_request",
    "validate_execution_venue_connectivity_check",
    "validate_execution_reconciliation_action",
    "validate_execution_reconciliation",
    "validate_execution_venue_capability",
    "validate_execution_venue_event",
    "validate_execution_venue_safety_attestation",
    "validate_halt_recovery",
    "validate_runtime_promotion",
    "validate_runtime_promotion_record",
    "validate_user_risk_choice",
]
