"""Content-bound formal execution coordinator for live copy-trade.

No live venue call belongs here.  The coordinator resolves canonical parents,
durably prepares the formal pre-submit chain, and records sanitized outcomes.
The relayer remains the only component that invokes the guarded venue.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Callable

from ..execution.base import ExecutionReport, Order, OrderAck, OrderExecutionObservation
from ..execution.emergency import AccountExecutionObservation
from ..lineage.ids import content_hash
from ..risk import RiskLimits
from ..security.gate.ingest import Attestation
from ..security.gate.policy import gate_hash
from ..research_os import (
    ExecutionOrderIntentRecord,
    ExecutionOrderMaterializationRecord,
    ExecutionOrderSubmissionRecord,
    ExecutionReconciliationRecord,
    ExecutionSubmitRequestRecord,
    ExecutionVenueCapabilityRecord,
    ExecutionVenueConnectivityCheckRecord,
    ExecutionVenueEventRecord,
    ExecutionVenueSafetyAttestationRecord,
    QROType,
    RuntimePromotionRecord,
    RuntimeStatus,
    UserRiskChoiceRecord,
    execution_client_order_ref_hash,
    execution_reconciliation_from_dict,
    execution_venue_event_from_dict,
    reconcile_execution_venue_events,
    validate_user_risk_choice,
)
from .gate_binding import follower_gate, relay_nonce
from .risk_state import CopyTradeRiskError, PersistentFollowerRiskStateStore, PreTradeReservation
from .service import copy_trade_signal_id


class CopyTradeFormalError(PermissionError):
    pass


@dataclass(frozen=True)
class CopyTradeRuntimeRequirements:
    subject_ref: str
    request_ref: str
    permission_gate_ref: str
    order_guard_ref: str
    idempotency_key: str
    audit_record_ref: str
    kill_switch_ref: str
    secret_ref: str
    responsibility_boundary_ref: str

    def to_dict(self) -> dict[str, str]:
        return {
            "subject_ref": self.subject_ref,
            "request_ref": self.request_ref,
            "permission_gate_ref": self.permission_gate_ref,
            "order_guard_ref": self.order_guard_ref,
            "idempotency_key": self.idempotency_key,
            "audit_record_ref": self.audit_record_ref,
            "kill_switch_ref": self.kill_switch_ref,
            "secret_ref": self.secret_ref,
            "responsibility_boundary_ref": self.responsibility_boundary_ref,
        }


_RISK_DISCLOSURE_TEXT = {
    "cost": "Fees, bid-ask spread, slippage, funding, and conversion costs can materially reduce or reverse returns.",
    "leverage": "Leverage magnifies both gains and losses and can exhaust the selected risk budget quickly.",
    "margin": "Margin requirements and available collateral can change; rejected or reduced orders remain possible.",
    "borrow": "Borrow availability and borrowing costs may change or become unavailable where the venue or product uses borrowing.",
    "funding": "Perpetual funding is variable, can be charged repeatedly, and is not guaranteed to favor the position.",
    "slippage": "Execution price can differ from the observed quote, especially during volatility or poor liquidity.",
    "impact": "The order itself can move the market; quoted depth does not guarantee executable depth.",
    "liquidation": "Rapid moves, margin changes, or venue rules can liquidate positions before software controls react.",
    "regulation": "Availability, tax, reporting, and regulatory treatment depend on jurisdiction and can change.",
}
_RISK_DISCLOSURE_REFS = {
    name: f"copy_trade_{name}_disclosure_v1_" + content_hash({"name": name, "text": text})
    for name, text in _RISK_DISCLOSURE_TEXT.items()
}
_RISK_FAILURE_MODE_TEXT = {
    "venue_unavailable": "The venue or network can become unavailable while orders or positions remain open.",
    "stale_or_missing_market_data": "Market data can be delayed, stale, incomplete, or unavailable, so a guard may reject an order or react late.",
    "partial_fill_or_outcome_unknown": "An order can partially fill or have an unknown outcome after a timeout; retrying can duplicate exposure until reconciliation finishes.",
    "gap_move_and_liquidation": "Prices can gap through intended exits and trigger liquidation before a stop or emergency close is accepted.",
    "credential_or_permission_revocation": "Credentials, account permissions, or venue trading eligibility can be revoked without warning.",
    "reconciliation_or_halt_delay": "Cancellation, reconciliation, and emergency HALT actions can be delayed and cannot guarantee an immediate flat account.",
}
_RISK_FAILURE_MODE_REFS = {
    name: "copy_trade_failure_mode_v1_" + content_hash({"name": name, "text": text})
    for name, text in _RISK_FAILURE_MODE_TEXT.items()
}
_RISK_RECOMMENDATION_TEXT = (
    "Remain on testnet unless you deliberately accept a small-live capped loss budget that you can afford to lose in full."
)
_RISK_RECOMMENDATION_REF = "copy_trade_recommendation_v1_" + content_hash(
    {"recommendation": _RISK_RECOMMENDATION_TEXT}
)
_RISK_RESPONSIBILITY_TEXT = {
    "user": "You choose the capped small-live risk budget, maintain venue eligibility and credentials, monitor the account, and can request HALT or unsubscribe.",
    "platform": "QuantBT enforces the declared software guards and records evidence, but cannot guarantee fills, uptime, price, liquidation avoidance, or profit.",
    "venue": "The venue controls matching, margin, liquidation, permissions, outages, and final account state.",
}
_RISK_RESPONSIBILITY_REF = "copy_trade_responsibility_boundary_v1_" + content_hash(
    _RISK_RESPONSIBILITY_TEXT
)
_RISK_DISCLOSURE_PROFILE_CONTENT = {
    "asset_class": "crypto_perp",
    "selected_risk_path": "small_live",
    "disclosures": {
        name: {"ref": _RISK_DISCLOSURE_REFS[name], "text": text}
        for name, text in _RISK_DISCLOSURE_TEXT.items()
    },
    "failure_modes": {
        name: {"ref": _RISK_FAILURE_MODE_REFS[name], "text": text}
        for name, text in _RISK_FAILURE_MODE_TEXT.items()
    },
    "recommendation": {
        "ref": _RISK_RECOMMENDATION_REF,
        "text": _RISK_RECOMMENDATION_TEXT,
    },
    "responsibility_boundary": {
        "ref": _RISK_RESPONSIBILITY_REF,
        "parties": _RISK_RESPONSIBILITY_TEXT,
    },
    "waiver_effect": "none",
}
_RISK_DISCLOSURE_PROFILE_CONTENT_HASH = content_hash(_RISK_DISCLOSURE_PROFILE_CONTENT)
_RISK_DISCLOSURE_PROFILE_REF = (
    "copy_trade_risk_profile_v2_" + _RISK_DISCLOSURE_PROFILE_CONTENT_HASH
)
_RISK_ACKNOWLEDGEMENT_REFS = (
    *tuple(_RISK_DISCLOSURE_REFS.values()),
    *tuple(_RISK_FAILURE_MODE_REFS.values()),
    _RISK_RECOMMENDATION_REF,
    _RISK_RESPONSIBILITY_REF,
)


def copy_trade_risk_disclosure_profile() -> dict[str, Any]:
    return {
        "profile_ref": _RISK_DISCLOSURE_PROFILE_REF,
        "profile_content_hash": _RISK_DISCLOSURE_PROFILE_CONTENT_HASH,
        **_RISK_DISCLOSURE_PROFILE_CONTENT,
        "required_acknowledgement_refs": list(_RISK_ACKNOWLEDGEMENT_REFS),
    }


@dataclass(frozen=True)
class PreparedCopyTradeExecution:
    promotion: RuntimePromotionRecord
    intent: ExecutionOrderIntentRecord
    materialization: ExecutionOrderMaterializationRecord
    connectivity: ExecutionVenueConnectivityCheckRecord
    safety: ExecutionVenueSafetyAttestationRecord
    capability: ExecutionVenueCapabilityRecord
    submit_request: ExecutionSubmitRequestRecord
    reservation: PreTradeReservation
    observation: AccountExecutionObservation
    attestation: Attestation


def _runtime_identity_for_follower(follower: Any) -> tuple[dict[str, Any], str, str]:
    stable = {
        "follower_id": str(getattr(follower, "follower_id", "") or ""),
        "user_id": str(getattr(follower, "user_id", "") or ""),
        "master_id": str(getattr(follower, "master_id", "") or ""),
        "account_binding_ref": str(getattr(follower, "account_binding_ref", "") or ""),
        "network": str(getattr(follower, "binance_network", "") or ""),
        "invest_amount": float(getattr(follower, "invest_amount", 0) or 0),
        "per_order_max_usdt": float(getattr(follower, "per_order_max_usdt", 0) or 0),
        "daily_loss_limit_pct": float(getattr(follower, "daily_loss_limit_pct", 0) or 0),
        "max_positions": int(getattr(follower, "max_positions", 0) or 0),
        "max_leverage": float(getattr(follower, "max_leverage", 0) or 0),
    }
    if not all(str(stable[key]).strip() for key in ("follower_id", "user_id", "master_id", "account_binding_ref")):
        raise CopyTradeFormalError("copy-trade runtime requirements need a bound follower/account identity")
    subject_ref = "copy_trade_subject_" + content_hash(
        {key: stable[key] for key in ("follower_id", "user_id", "master_id", "account_binding_ref")}
    )
    policy_hash = content_hash(stable)
    return stable, subject_ref, "copy_trade_runtime_request_" + policy_hash


def build_user_risk_choice(
    follower: Any,
    *,
    owner_user_id: str,
    selected_risk_path: str,
    risk_disclosure_profile_ref: str,
) -> UserRiskChoiceRecord:
    stable, subject_ref, request_ref = _runtime_identity_for_follower(follower)
    owner = str(owner_user_id or "").strip()
    if owner != stable["user_id"]:
        raise CopyTradeFormalError("risk choice authenticated owner does not match follower")
    if selected_risk_path != "small_live":
        raise CopyTradeFormalError("only the explicit small_live risk path is supported")
    if risk_disclosure_profile_ref != _RISK_DISCLOSURE_PROFILE_REF:
        raise CopyTradeFormalError("risk disclosure profile is unknown or stale")
    record = UserRiskChoiceRecord(
        choice_ref="",
        selected_risk_path=selected_risk_path,
        cost_disclosure_ref=_RISK_DISCLOSURE_REFS["cost"],
        leverage_disclosure_ref=_RISK_DISCLOSURE_REFS["leverage"],
        margin_disclosure_ref=_RISK_DISCLOSURE_REFS["margin"],
        borrow_disclosure_ref=_RISK_DISCLOSURE_REFS["borrow"],
        funding_disclosure_ref=_RISK_DISCLOSURE_REFS["funding"],
        slippage_disclosure_ref=_RISK_DISCLOSURE_REFS["slippage"],
        impact_disclosure_ref=_RISK_DISCLOSURE_REFS["impact"],
        liquidation_disclosure_ref=_RISK_DISCLOSURE_REFS["liquidation"],
        regulation_disclosure_ref=_RISK_DISCLOSURE_REFS["regulation"],
        failure_mode_refs=tuple(_RISK_FAILURE_MODE_REFS.values()),
        recommendation_ref=_RISK_RECOMMENDATION_REF,
        responsibility_boundary_ref=_RISK_RESPONSIBILITY_REF,
        owner_user_id=owner,
        master_id=stable["master_id"],
        follower_id=stable["follower_id"],
        account_binding_ref=stable["account_binding_ref"],
        subject_ref=subject_ref,
        runtime_request_ref=request_ref,
        asset_class="crypto_perp",
        risk_disclosure_profile_ref=_RISK_DISCLOSURE_PROFILE_REF,
        actor_source="user_manual",
    )
    decision = validate_user_risk_choice(record)
    if not decision.accepted:
        raise CopyTradeFormalError(
            ";".join(violation.code for violation in decision.violations)
        )
    return record


def validate_user_risk_choice_for_follower(
    choice: UserRiskChoiceRecord,
    follower: Any,
) -> None:
    stable, subject_ref, request_ref = _runtime_identity_for_follower(follower)
    violations = [
        violation.code
        for violation in validate_user_risk_choice(choice).violations
    ]
    expected_pairs = {
        "owner_user_id": stable["user_id"],
        "master_id": stable["master_id"],
        "follower_id": stable["follower_id"],
        "account_binding_ref": stable["account_binding_ref"],
        "subject_ref": subject_ref,
        "runtime_request_ref": request_ref,
        "asset_class": "crypto_perp",
        "selected_risk_path": "small_live",
        "risk_disclosure_profile_ref": _RISK_DISCLOSURE_PROFILE_REF,
        "responsibility_boundary_ref": _RISK_RESPONSIBILITY_REF,
    }
    for field_name, expected in expected_pairs.items():
        if getattr(choice, field_name) != expected:
            violations.append(f"risk_choice_{field_name}_mismatch")
    for name, expected in _RISK_DISCLOSURE_REFS.items():
        field_name = f"{name}_disclosure_ref"
        if getattr(choice, field_name) != expected:
            violations.append(f"risk_choice_{field_name}_mismatch")
    if choice.failure_mode_refs != tuple(_RISK_FAILURE_MODE_REFS.values()):
        violations.append("risk_choice_failure_modes_mismatch")
    if choice.recommendation_ref != _RISK_RECOMMENDATION_REF:
        violations.append("risk_choice_recommendation_mismatch")
    if violations:
        raise CopyTradeFormalError(";".join(dict.fromkeys(violations)))


def runtime_requirements_for_follower(
    follower: Any,
    *,
    risk_choice: UserRiskChoiceRecord | None = None,
) -> CopyTradeRuntimeRequirements:
    stable, subject_ref, request_ref = _runtime_identity_for_follower(follower)
    if risk_choice is not None:
        validate_user_risk_choice_for_follower(risk_choice, follower)
    policy_hash = request_ref.removeprefix("copy_trade_runtime_request_")
    return CopyTradeRuntimeRequirements(
        subject_ref=subject_ref,
        request_ref=request_ref,
        permission_gate_ref="copy_trade_permission_" + policy_hash,
        order_guard_ref="copy_trade_order_guard_" + policy_hash,
        idempotency_key="copy_trade_runtime_idempotency_" + content_hash(subject_ref),
        audit_record_ref="copy_trade_runtime_audit_" + content_hash(stable),
        kill_switch_ref="copy_trade_kill_switch_" + content_hash(stable["account_binding_ref"]),
        secret_ref="copy_trade_secret_ref_" + content_hash(stable["account_binding_ref"]),
        responsibility_boundary_ref=(
            str(risk_choice.responsibility_boundary_ref or "")
            if risk_choice is not None
            else ""
        ),
    )


def runtime_approval_binding_for_follower(
    follower: Any,
    *,
    risk_choice: UserRiskChoiceRecord,
) -> dict[str, str]:
    requirements = runtime_requirements_for_follower(follower, risk_choice=risk_choice)
    consent_event_ref = str(
        getattr(follower, "user_risk_consent_event_ref", "") or ""
    ).strip()
    if not consent_event_ref:
        raise CopyTradeFormalError(
            "copy-trade runtime approval requires a persistent user risk consent event"
        )
    payload = {
        "subject_ref": requirements.subject_ref,
        "runtime_request_ref": requirements.request_ref,
        "user_risk_choice_ref": risk_choice.choice_ref,
        "user_risk_consent_event_ref": consent_event_ref,
        "account_binding_ref": str(risk_choice.account_binding_ref),
        "risk_disclosure_profile_ref": str(risk_choice.risk_disclosure_profile_ref),
        "responsibility_boundary_ref": requirements.responsibility_boundary_ref,
    }
    return {
        "approval_target_ref": "copy_trade_runtime_approval_v1_" + content_hash(payload),
        **payload,
    }


def validate_live_runtime_promotion(
    promotion: RuntimePromotionRecord,
    follower: Any,
    *,
    risk_choice: UserRiskChoiceRecord,
    approval_store: Any,
    require_active_account: Callable[[str], bool] | None = None,
) -> CopyTradeRuntimeRequirements:
    requirements = runtime_requirements_for_follower(follower, risk_choice=risk_choice)
    approval_binding = runtime_approval_binding_for_follower(
        follower,
        risk_choice=risk_choice,
    )
    violations: list[str] = []
    expected_ref = replace(promotion, runtime_promotion_ref="").runtime_promotion_ref
    if promotion.runtime_promotion_ref != expected_ref:
        violations.append("runtime_promotion_content_identity_mismatch")
    if str(promotion.target_runtime) != RuntimeStatus.LIVE.value:
        violations.append("runtime_promotion_target_not_live")
    if str(promotion.source_runtime) != RuntimeStatus.TESTNET.value or not str(promotion.testnet_run_ref or "").strip():
        violations.append("runtime_promotion_missing_testnet_ladder")
    if str(promotion.asset_class) != "crypto_perp":
        violations.append("runtime_promotion_asset_not_crypto_perp")
    for field_name, expected in requirements.to_dict().items():
        if getattr(promotion, field_name, None) != expected:
            violations.append(f"runtime_promotion_{field_name}_mismatch")
    if str(promotion.mock_profile or "none").lower() not in {"", "none", "real", "live"}:
        violations.append("runtime_promotion_mock_profile")
    if not promotion.evidence_refs:
        violations.append("runtime_promotion_missing_evidence")
    if risk_choice.choice_ref not in set(promotion.evidence_refs):
        violations.append("runtime_promotion_missing_user_risk_choice")
    consent_event_ref = str(
        getattr(follower, "user_risk_consent_event_ref", "") or ""
    ).strip()
    if not consent_event_ref or consent_event_ref not in set(promotion.evidence_refs):
        violations.append("runtime_promotion_missing_user_risk_consent_event")
    try:
        approval = approval_store.get(str(promotion.approval_ref or ""))
    except Exception:  # noqa: BLE001
        approval = None
        violations.append("runtime_promotion_approval_unresolved")
    if approval is not None:
        if getattr(approval, "decision", None) != "approved":
            violations.append("runtime_promotion_approval_not_approved")
        if getattr(approval, "action_kind", None) != "live_order":
            violations.append("runtime_promotion_approval_wrong_action")
        if getattr(approval, "model_id", None) != approval_binding["approval_target_ref"]:
            violations.append("runtime_promotion_approval_request_mismatch")
        approval_evidence = getattr(approval, "evidence", None)
        if (
            not isinstance(approval_evidence, dict)
            or approval_evidence.get("copy_trade_runtime_approval") != approval_binding
        ):
            violations.append("runtime_promotion_approval_evidence_mismatch")
        if not getattr(approval, "approver", None) or getattr(approval, "approver", None) == getattr(approval, "created_by", None):
            violations.append("runtime_promotion_approval_not_independent")
    account_ref = str(getattr(follower, "account_binding_ref", "") or "")
    if require_active_account is not None and not require_active_account(account_ref):
        violations.append("runtime_promotion_kill_switch_account_inactive")
    if violations:
        raise CopyTradeFormalError(";".join(violations))
    return requirements


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _full_ref(record: Any, field_name: str, prefix: str) -> Any:
    payload = record.to_dict()
    payload.pop(field_name, None)
    payload.pop("created_at_utc", None)
    return replace(record, **{field_name: prefix + content_hash(payload)})


def _same_semantics(left: Any, right: Any) -> bool:
    a = left.to_dict()
    b = right.to_dict()
    a.pop("created_at_utc", None)
    b.pop("created_at_utc", None)
    return a == b


def _ensure(store: Any, getter: str, recorder: str, ref: str, record: Any, **kwargs: Any) -> Any:
    try:
        existing = getattr(store, getter)(ref)
    except KeyError:
        return getattr(store, recorder)(record, **kwargs)
    if not _same_semantics(existing, record):
        raise CopyTradeFormalError(f"formal execution content collision at {ref}")
    return existing


class CopyTradeFormalExecutionCoordinator:
    def __init__(
        self,
        *,
        runtime_promotions: Any,
        user_risk_choices: Any,
        order_intents: Any,
        materializations: Any,
        connectivity_checks: Any,
        safety_attestations: Any,
        capabilities: Any,
        submit_requests: Any,
        submissions: Any,
        venue_events: Any,
        reconciliations: Any,
        signal_validations: Any,
        market_data_registry: Any,
        research_graph: Any,
        approval_store: Any,
        risk_store: PersistentFollowerRiskStateStore,
        observation_provider: Callable[[Any, str], AccountExecutionObservation],
        active_account_provider: Callable[[], tuple[str, ...]],
        consent_authority_provider: Callable[[Any, UserRiskChoiceRecord], bool],
        master_provider: Callable[[str], Any],
        testnet_evidence_provider: Callable[[str, Any], bool],
    ) -> None:
        self._runtime_promotions = runtime_promotions
        self._user_risk_choices = user_risk_choices
        self._intents = order_intents
        self._materializations = materializations
        self._connectivity = connectivity_checks
        self._safety = safety_attestations
        self._capabilities = capabilities
        self._submit_requests = submit_requests
        self._submissions = submissions
        self._events = venue_events
        self._reconciliations = reconciliations
        self._signal_validations = signal_validations
        self._market_data = market_data_registry
        self._graph = research_graph
        self._approval_store = approval_store
        self._risk_store = risk_store
        self._risk_store.bind_formal_proof_stores(
            reconciliation_store=reconciliations,
            venue_event_store=venue_events,
            submission_store=submissions,
        )
        self._observe = observation_provider
        self._active_accounts = active_account_provider
        self._consent_authority = consent_authority_provider
        self._master = master_provider
        self._testnet_evidence = testnet_evidence_provider

    def _refresh_projection_stores(self) -> None:
        """Refresh durable registries before deriving a cross-process event set."""

        for store in (
            self._runtime_promotions,
            self._user_risk_choices,
            self._intents,
            self._materializations,
            self._connectivity,
            self._safety,
            self._capabilities,
            self._submit_requests,
            self._submissions,
            self._events,
            self._reconciliations,
            self._signal_validations,
        ):
            refresh = getattr(store, "refresh", None)
            if callable(refresh):
                refresh()

    def abort_pre_submit(self, *, follower: Any, signal: Any, reason_ref: str) -> bool:
        return self._risk_store.abort_pre_submit(
            follower_id=str(getattr(follower, "follower_id", "") or ""),
            account_binding_ref=str(getattr(follower, "account_binding_ref", "") or ""),
            signal_id=str(getattr(signal, "signal_id", "") or ""),
            reason_ref=reason_ref,
        )

    def mark_order_request_started(self, prepared: PreparedCopyTradeExecution) -> None:
        """Persist the exact order-request boundary in the HMAC risk ledger."""

        self._risk_store.mark_order_request_started(
            prepared.reservation,
            runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
            order_intent_ref=prepared.intent.order_intent_ref,
            order_materialization_ref=prepared.materialization.materialization_ref,
            venue_capability_ref=prepared.capability.venue_capability_ref,
            submit_request_ref=prepared.submit_request.submit_request_ref,
        )

    def durable_outcome_after_projection_failure(
        self,
        prepared: PreparedCopyTradeExecution,
    ) -> dict[str, str]:
        """Read the sealed risk outcome when a downstream projection failed."""

        attempts = [
            attempt
            for attempt in self._risk_store.formal_projection_attempts(
                follower_id=prepared.reservation.follower_id,
                account_binding_ref=prepared.reservation.account_binding_ref,
            )
            if attempt["reservation"].reservation_ref
            == prepared.reservation.reservation_ref
            and attempt.get("state") in {
                "order_request_started",
                "submission_accepted",
                "submission_unknown",
                "venue_reject",
                "definitive_reject",
            }
        ]
        if len(attempts) != 1:
            return {"formal_status": "outcome_unknown"}
        attempt = attempts[0]
        state = str(attempt.get("state") or "")
        payload = attempt.get("payload") if isinstance(attempt.get("payload"), dict) else {}
        if state in {"venue_reject", "definitive_reject"}:
            status = "rejected"
        elif state == "submission_accepted":
            ack_status = str(payload.get("ack_status") or "new")
            status = "needs_reconcile" if ack_status in {"partially_filled", "filled"} else "placed"
        else:
            status = "outcome_unknown"
        return {
            "formal_status": status,
            "submission_ref": str(payload.get("submission_ref") or ""),
            "venue_order_ref": str(payload.get("venue_order_ref") or ""),
            "audit_projection_status": "pending",
        }

    def _prepared_submission_context(
        self,
        reservation: PreTradeReservation,
        context: dict[str, str],
    ) -> Any:
        required = {
            "runtime_promotion_ref",
            "order_intent_ref",
            "order_materialization_ref",
            "venue_capability_ref",
            "submit_request_ref",
            "client_order_id",
        }
        if not required <= set(context) or not all(str(context[key] or "").strip() for key in required):
            raise CopyTradeFormalError("started execution attempt lacks formal recovery refs")
        if context["client_order_id"] != reservation.client_order_id:
            raise CopyTradeFormalError("started execution attempt client identity mismatch")
        promotion = self._runtime_promotions.promotion(context["runtime_promotion_ref"])
        intent = self._intents.intent(context["order_intent_ref"])
        materialization = self._materializations.materialization(
            context["order_materialization_ref"]
        )
        capability = self._capabilities.capability(context["venue_capability_ref"])
        submit_request = self._submit_requests.request(context["submit_request_ref"])
        if submit_request.client_order_ref_hash != execution_client_order_ref_hash(
            reservation.client_order_id
        ):
            raise CopyTradeFormalError("started execution attempt submit-request identity mismatch")
        return SimpleNamespace(
            promotion=promotion,
            intent=intent,
            materialization=materialization,
            capability=capability,
            submit_request=submit_request,
            reservation=reservation,
        )

    def ensure_started_attempt_projection(
        self,
        reservation: PreTradeReservation,
        binding: dict[str, str],
    ) -> dict[str, str]:
        """Compatibility wrapper around the complete sealed projection outbox."""

        matches = [
            attempt
            for attempt in self._risk_store.formal_projection_attempts(
                follower_id=reservation.follower_id,
                account_binding_ref=reservation.account_binding_ref,
            )
            if attempt["reservation"].reservation_ref == reservation.reservation_ref
            and attempt.get("state") in {
                "order_request_started",
                "submission_accepted",
                "submission_unknown",
                "venue_reject",
                "definitive_reject",
            }
        ]
        if len(matches) != 1:
            raise CopyTradeFormalError("risk reservation has no unique projection outbox item")
        if binding.get("state") and binding["state"] != matches[0]["state"]:
            raise CopyTradeFormalError("projection binding state changed during recovery")
        return self.ensure_formal_projection(matches[0])

    def ensure_formal_projection(self, attempt: dict[str, Any]) -> dict[str, str]:
        """Idempotently project one sealed risk-outbox item into all formal JSONLs."""

        reservation = attempt.get("reservation")
        if not isinstance(reservation, PreTradeReservation):
            raise CopyTradeFormalError("formal projection attempt lacks a typed reservation")
        self._refresh_projection_stores()
        context = self._risk_store.order_request_context(reservation.reservation_ref)
        if context is None:
            raise CopyTradeFormalError("risk reservation has no durable order-request context")
        prepared = self._prepared_submission_context(reservation, context)
        state = str(attempt.get("state") or "")
        payload = attempt.get("payload")
        if not isinstance(payload, dict):
            raise CopyTradeFormalError("formal projection outbox payload is malformed")
        actor = str(payload.get("actor") or "copy_trade_signal_relayer")
        if state == "formal_lifecycle_claim":
            binding_event_id = str(attempt.get("binding_event_id") or "")
            if not binding_event_id:
                raise CopyTradeFormalError("lifecycle claim lacks its sealed risk identity")
            sealed = self._risk_store.lifecycle_projection_claim(binding_event_id)
            if sealed["reservation_ref"] != reservation.reservation_ref:
                raise CopyTradeFormalError("lifecycle claim reservation identity mismatch")
            if sealed["payload"] != payload:
                raise CopyTradeFormalError("lifecycle claim payload differs from the sealed risk ledger")

            reservation_attempts = [
                candidate
                for candidate in self._risk_store.formal_projection_attempts(
                    follower_id=reservation.follower_id,
                    account_binding_ref=reservation.account_binding_ref,
                )
                if candidate["reservation"].reservation_ref == reservation.reservation_ref
            ]
            outcome_attempts = [
                candidate
                for candidate in reservation_attempts
                if candidate.get("state") in {
                    "submission_accepted",
                    "submission_unknown",
                    "venue_reject",
                    "definitive_reject",
                }
            ]
            if len(outcome_attempts) != 1:
                raise CopyTradeFormalError("lifecycle claim lacks one sealed submission outcome")
            self.ensure_formal_projection(outcome_attempts[0])

            if not any(
                candidate.get("binding_event_id") == binding_event_id
                for candidate in reservation_attempts
            ):
                raise CopyTradeFormalError("lifecycle claim is absent from the sealed projection order")

            expected_event = payload.get("venue_event")
            expected_reconciliation = payload.get("reconciliation")
            if not isinstance(expected_event, dict) or not isinstance(expected_reconciliation, dict):
                raise CopyTradeFormalError("lifecycle claim lacks exact formal identities")
            event = execution_venue_event_from_dict(expected_event)
            reconciliation = execution_reconciliation_from_dict(expected_reconciliation)
            if event.to_dict() != expected_event or reconciliation.to_dict() != expected_reconciliation:
                raise CopyTradeFormalError("lifecycle claim formal payload cannot be losslessly decoded")
            if event.venue_event_ref not in set(reconciliation.event_refs):
                raise CopyTradeFormalError("lifecycle reconciliation omits its sealed venue event")

            with self._risk_store.formal_projection_guard(reservation.reservation_ref):
                self._refresh_projection_stores()
                try:
                    submission = self._submissions.submission(str(event.submission_ref or ""))
                except KeyError as exc:
                    raise CopyTradeFormalError(
                        "lifecycle claim lacks its persisted submission parent"
                    ) from exc
                event = _ensure(
                    self._events,
                    "event",
                    "record_event",
                    event.venue_event_ref,
                    event,
                    known_order_intent_refs={prepared.intent.order_intent_ref},
                    known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
                    known_submission_refs={submission.submission_ref},
                    submission=submission,
                )
                try:
                    reconciliation_events = tuple(
                        self._events.event(ref) for ref in reconciliation.event_refs
                    )
                except KeyError as exc:
                    raise CopyTradeFormalError(
                        "lifecycle reconciliation has an unrepaired prior venue event"
                    ) from exc
                reconciliation = _ensure(
                    self._reconciliations,
                    "reconciliation",
                    "record_reconciliation",
                    reconciliation.reconciliation_ref,
                    reconciliation,
                    known_order_intent_refs={prepared.intent.order_intent_ref},
                    known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
                    known_venue_event_refs=set(reconciliation.event_refs),
                    known_submission_refs={submission.submission_ref},
                    submission=submission,
                    venue_events=reconciliation_events,
                )
                self._risk_store.finalize_lifecycle_projection_claim(
                    reservation,
                    claim_event_id=binding_event_id,
                )

            projection_kind = str(payload.get("projection_kind") or "")
            if projection_kind == "fill":
                report_payload = payload.get("report")
                if not isinstance(report_payload, dict):
                    raise CopyTradeFormalError("fill lifecycle claim lacks execution report")
                formal_status = (
                    "filled"
                    if str(report_payload.get("status") or "") == "filled"
                    else "needs_reconcile"
                )
            elif projection_kind == "terminal":
                formal_status = str(payload.get("expected_status") or "")
                if formal_status not in {"closed_no_fill", "closed_partial_fill"}:
                    raise CopyTradeFormalError("terminal lifecycle claim has invalid expected status")
            else:
                raise CopyTradeFormalError("lifecycle claim has unsupported projection kind")
            return {
                "submission_ref": submission.submission_ref,
                "venue_event_ref": event.venue_event_ref,
                "reconciliation_ref": reconciliation.reconciliation_ref,
                "formal_status": formal_status,
            }
        if state == "order_request_started":
            repaired = self.record_failure(
                prepared,
                reason_ref="submission_unknown_process_recovery_" + content_hash(
                    reservation.reservation_ref
                ),
                definitive_reject=False,
                actor=actor,
            )
            return {**repaired, "formal_status": "outcome_unknown"}
        if state not in {
            "submission_accepted",
            "submission_unknown",
            "venue_reject",
            "definitive_reject",
        }:
            raise CopyTradeFormalError("risk reservation has unsupported projection state")

        formal_status = str(payload.get("formal_submission_status") or "")
        if formal_status not in {"accepted", "outcome_unknown", "rejected"}:
            raise CopyTradeFormalError("formal projection outbox has invalid submission status")
        submission = self._record_submission(
            prepared,
            status=formal_status,
            ack_ref=str(payload.get("ack_ref") or "") or None,
            venue_order_ref=str(payload.get("venue_order_ref") or "") or None,
            actor=actor,
        )
        expected_submission_ref = str(payload.get("submission_ref") or "")
        if not expected_submission_ref or submission.submission_ref != expected_submission_ref:
            raise CopyTradeFormalError("recovered formal submission identity mismatch")

        event: ExecutionVenueEventRecord | None = None
        if state in {"submission_accepted", "venue_reject", "definitive_reject"}:
            rejected = state in {"venue_reject", "definitive_reject"}
            ack_ref = str(payload.get("ack_ref") or payload.get("reason_ref") or "")
            if not ack_ref:
                raise CopyTradeFormalError("formal ack projection lacks ack evidence")
            ack_status = str(payload.get("ack_status") or ("rejected" if rejected else "new"))
            raw_event_hash = (
                "sha256:" + content_hash(str(payload.get("reason_ref") or ack_ref))
                if state == "definitive_reject"
                else "sha256:"
                + content_hash(
                    {
                        "ack_ref": ack_ref,
                        "status": ack_status,
                        "venue_order_ref": submission.venue_order_ref,
                    }
                )
            )
            event = ExecutionVenueEventRecord(
                order_intent_ref=prepared.intent.order_intent_ref,
                runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                venue_ref=submission.venue_ref,
                event_kind="rejected" if rejected else "accepted",
                status="rejected" if rejected else "accepted",
                audit_record_ref="copy_event_audit_" + content_hash(submission.submission_ref),
                order_guard_ref=submission.order_guard_ref,
                idempotency_key=submission.idempotency_key,
                venue_order_ref=submission.venue_order_ref,
                client_order_ref=reservation.client_order_id,
                ack_ref=ack_ref,
                raw_event_hash=raw_event_hash,
                evidence_refs=(ack_ref,),
                recorded_by=actor,
                created_at_utc=str(payload.get("ack_accepted_at_utc") or datetime.now(UTC).isoformat()),
            )
            event = _ensure(
                self._events,
                "event",
                "record_event",
                event.venue_event_ref,
                event,
                known_order_intent_refs={prepared.intent.order_intent_ref},
                known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
                known_submission_refs={submission.submission_ref},
                submission=submission,
            )
        events = (event,) if event is not None else ()
        evidence_refs = (
            (event.venue_event_ref,)
            if event is not None
            else (str(payload.get("reason_ref") or "projection_outcome_unknown"),)
        )
        reconciliation = reconcile_execution_venue_events(
            order_intent_ref=prepared.intent.order_intent_ref,
            runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_order_ref=submission.venue_order_ref,
            audit_record_ref="copy_reconcile_audit_" + content_hash(submission.submission_ref),
            events=events,
            evidence_refs=evidence_refs,
            recorded_by=actor,
        )
        reconciliation = _ensure(
            self._reconciliations,
            "reconciliation",
            "record_reconciliation",
            reconciliation.reconciliation_ref,
            reconciliation,
            known_order_intent_refs={prepared.intent.order_intent_ref},
            known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
            known_venue_event_refs={item.venue_event_ref for item in events},
            known_submission_refs={submission.submission_ref},
            submission=submission,
            venue_events=events,
        )
        binding_event_id = str(attempt.get("binding_event_id") or "")
        self._risk_store.mark_formal_projection_completed(
            reservation,
            binding_event_id=binding_event_id,
            submission_ref=submission.submission_ref,
            venue_event_ref=event.venue_event_ref if event is not None else None,
            reconciliation_ref=reconciliation.reconciliation_ref,
        )
        result = {
            "submission_ref": submission.submission_ref,
            "reconciliation_ref": reconciliation.reconciliation_ref,
            "formal_status": formal_status,
        }
        if event is not None:
            result["venue_event_ref"] = event.venue_event_ref
        return result

    def prepare(self, *, follower: Any, signal: Any, order: Order, actor: str) -> PreparedCopyTradeExecution:
        if str(getattr(follower, "binance_network", "")) != "mainnet":
            raise CopyTradeFormalError("formal live coordinator only accepts mainnet followers")
        refresh_choices = getattr(self._user_risk_choices, "refresh", None)
        if callable(refresh_choices):
            refresh_choices()
        refresh_promotions = getattr(self._runtime_promotions, "refresh", None)
        if callable(refresh_promotions):
            refresh_promotions()
        try:
            risk_choice = self._user_risk_choices.choice_for_owner(
                str(getattr(follower, "user_risk_choice_ref", "") or ""),
                str(getattr(follower, "user_id", "") or ""),
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise CopyTradeFormalError("formal live execution cannot resolve the follower user risk choice") from exc
        validate_user_risk_choice_for_follower(risk_choice, follower)
        if not self._consent_authority(follower, risk_choice):
            raise CopyTradeFormalError(
                "formal live execution cannot resolve an exact audited user consent activation"
            )
        try:
            promotion = self._runtime_promotions.promotion(
                str(getattr(follower, "runtime_promotion_ref", "") or "")
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise CopyTradeFormalError(
                "formal live execution cannot resolve the follower runtime promotion"
            ) from exc
        validate_live_runtime_promotion(
            promotion,
            follower,
            risk_choice=risk_choice,
            approval_store=self._approval_store,
            require_active_account=lambda ref: ref in set(self._active_accounts()),
        )
        testnet_run_ref = str(promotion.testnet_run_ref or "")
        if testnet_run_ref not in set(promotion.evidence_refs) or not self._testnet_evidence(
            testnet_run_ref,
            follower,
        ):
            raise CopyTradeFormalError("runtime promotion lacks resolved formal testnet evidence")

        if str(getattr(signal, "signal_id", "")) != copy_trade_signal_id(signal):
            raise CopyTradeFormalError("copy-trade signal content identity mismatch")
        if str(getattr(signal, "status", "")) != "live":
            raise CopyTradeFormalError("copy-trade signal is not live")
        try:
            published_at = datetime.fromisoformat(str(getattr(signal, "published_at_utc", "")))
            if published_at.tzinfo is None:
                raise ValueError("naive timestamp")
            age_s = (datetime.now(UTC) - published_at.astimezone(UTC)).total_seconds()
        except (TypeError, ValueError) as exc:
            raise CopyTradeFormalError("copy-trade signal timestamp is malformed") from exc
        if age_s < -5 or age_s > 60:
            raise CopyTradeFormalError("copy-trade signal is future-dated or expired")
        if str(getattr(signal, "master_id", "")) != str(getattr(follower, "master_id", "")):
            raise CopyTradeFormalError("copy-trade signal master does not match follower subscription")
        master = self._master(str(getattr(follower, "master_id", "")))
        if master is None:
            raise CopyTradeFormalError("copy-trade master cannot be resolved")
        master_owner_user_id = str(getattr(master, "user_id", "") or "").strip()
        if not master_owner_user_id:
            raise CopyTradeFormalError("copy-trade master lacks a stable owner user id")

        qro_id = str(getattr(signal, "strategy_book_qro_id", "") or "")
        qro = self._graph.qro(qro_id)
        if _value(qro.qro_type) != QROType.STRATEGY_BOOK.value:
            raise CopyTradeFormalError("copy-trade signal source is not a StrategyBook QRO")
        if _value(qro.allowed_environment) != RuntimeStatus.LIVE.value:
            raise CopyTradeFormalError("StrategyBook QRO is not approved for live environment")
        if _value(qro.evidence_status) != "sufficient" or _value(qro.governance_status) != "approved":
            raise CopyTradeFormalError("StrategyBook QRO lacks sufficient approved evidence")
        if str(getattr(qro, "owner", "") or "") != master_owner_user_id:
            raise CopyTradeFormalError("StrategyBook QRO owner does not match copy-trade master")
        if _value(getattr(qro, "runtime_status", "")) != RuntimeStatus.LIVE.value:
            raise CopyTradeFormalError("StrategyBook QRO runtime is not live")
        if str(getattr(qro, "mock_profile", "none") or "none").lower() not in {"", "none", "real", "live"}:
            raise CopyTradeFormalError("StrategyBook QRO is mock-backed")

        signal_validation_ref = str(getattr(signal, "signal_validation_ref", "") or "")
        refresh_signal_validations = getattr(self._signal_validations, "refresh", None)
        if callable(refresh_signal_validations):
            refresh_signal_validations()
        try:
            signal_validation = self._signal_validations.validation(
                signal_validation_ref,
                owner_user_id=master_owner_user_id,
            )
        except (KeyError, LookupError, PermissionError, TypeError, ValueError) as exc:
            raise CopyTradeFormalError(
                "copy-trade signal validation cannot be resolved for the master owner"
            ) from exc
        if _value(signal_validation.verdict) != "accepted":
            raise CopyTradeFormalError("copy-trade signal validation is not accepted")
        qro_signal_refs = set(getattr(qro, "evidence_refs", ()) or ())
        qro_signal_refs.update(
            (getattr(qro, "output_contract", {}) or {}).get("signal_refs", ())
            if isinstance(getattr(qro, "output_contract", {}), dict)
            else ()
        )
        if str(signal_validation.signal_ref) not in qro_signal_refs:
            raise CopyTradeFormalError("accepted signal validation is not bound to the StrategyBook QRO")
        market_validation_ref = str(getattr(signal, "market_data_use_validation_ref", "") or "")
        try:
            market_validation = self._market_data.use_validation(
                market_validation_ref,
                owner_user_id=master_owner_user_id,
            )
        except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError) as exc:
            raise CopyTradeFormalError(
                "copy-trade market data validation cannot be resolved for the master owner"
            ) from exc
        if str(getattr(market_validation, "recorded_by", "") or "").strip() != master_owner_user_id:
            raise CopyTradeFormalError("copy-trade market data validation owner does not match master")
        if not market_validation.accepted or str(market_validation.use_context) != RuntimeStatus.LIVE.value:
            raise CopyTradeFormalError("copy-trade market data validation is not accepted for live")
        instrument_ref = str(getattr(signal, "instrument_ref", "") or "")
        if instrument_ref not in set(market_validation.instrument_refs):
            raise CopyTradeFormalError("copy-trade instrument is not bound to market data validation")
        try:
            instrument = self._market_data.instrument(
                instrument_ref,
                owner_user_id=master_owner_user_id,
            )
        except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError) as exc:
            raise CopyTradeFormalError(
                "copy-trade instrument cannot be resolved for the master owner"
            ) from exc
        if str(instrument.asset_class) not in {"crypto_perp", "perpetual"}:
            raise CopyTradeFormalError("copy-trade instrument is not crypto_perp")
        venue_symbol = str(getattr(instrument, "venue_symbol", "") or "").upper()
        if not venue_symbol or venue_symbol != str(order.symbol or "").upper():
            raise CopyTradeFormalError("copy-trade instrument venue symbol does not match the order")

        observation = self._observe(follower, str(order.symbol))
        limits = RiskLimits(
            per_order_max_usdt=float(getattr(follower, "per_order_max_usdt", 0) or 0),
            daily_loss_limit_pct=float(getattr(follower, "daily_loss_limit_pct", 0) or 0),
        )
        try:
            reservation = self._risk_store.reserve(
                follower=follower,
                signal_id=str(signal.signal_id),
                order=order,
                observation=observation,
                limits=limits,
            )
        except CopyTradeRiskError as exc:
            raise CopyTradeFormalError(str(exc)) from exc
        expected_venue_ref = f"leased_binance:{follower.account_binding_ref}:mainnet:usdm_futures"
        if str(order.venue) != expected_venue_ref:
            self._risk_store.mark_definitive_reject(
                reservation,
                reason_ref="risk_reject_" + content_hash("venue_identity_mismatch"),
            )
            raise CopyTradeFormalError("copy-trade order venue is not account-scoped")

        idempotency_key = relay_nonce(str(signal.signal_id), str(follower.follower_id))
        audit_seed = {"reservation_ref": reservation.reservation_ref, "actor": actor}
        common = {
            "permission_gate_ref": promotion.permission_gate_ref,
            "order_guard_ref": promotion.order_guard_ref,
            "idempotency_key": idempotency_key,
            "kill_switch_ref": promotion.kill_switch_ref,
            "secret_ref": promotion.secret_ref,
            "responsibility_boundary_ref": promotion.responsibility_boundary_ref,
        }
        intent = ExecutionOrderIntentRecord(
            source_portfolio_ref=None,
            strategy_book_ref="qro:" + qro.qro_id,
            execution_policy_ref=str(promotion.permission_gate_ref),
            risk_policy_ref=reservation.risk_check_ref,
            runtime=RuntimeStatus.LIVE,
            asset_class="crypto_perp",
            instrument_ref=instrument_ref,
            side=str(order.side),
            order_type=str(order.order_type),
            venue_ref=expected_venue_ref,
            signal_ref=str(signal_validation.signal_ref),
            signal_validation_ref=signal_validation_ref,
            market_data_use_validation_ref=market_validation_ref,
            quantity_ref="quantity_" + content_hash({"reservation_ref": reservation.reservation_ref, "quantity": order.quantity}),
            price_ref=observation.source_ref,
            time_in_force_ref="time_in_force_" + content_hash(str(order.time_in_force)),
            audit_record_ref="copy_intent_audit_" + content_hash(audit_seed),
            failure_mode_refs=("venue_timeout", "submission_outcome_unknown", "reconciliation_required"),
            recorded_by=actor,
            **common,
        )
        intent = _full_ref(intent, "order_intent_ref", "order_intent_")
        intent = _ensure(
            self._intents,
            "intent",
            "record_intent",
            intent.order_intent_ref,
            intent,
            known_signal_validation_refs={signal_validation_ref},
            known_market_data_use_validation_refs={market_validation_ref},
        )

        payload_hash = "sha256:" + content_hash(order.to_dict())
        materialization = ExecutionOrderMaterializationRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            materializer_ref="copy_trade_formal_materializer:v1",
            materialization_mode="live",
            materialization_status="materialized",
            audit_record_ref="copy_materialization_audit_" + content_hash(audit_seed),
            order_schema_ref="schema:execution_order:v1",
            order_payload_hash=payload_hash,
            quantity_resolution_ref=intent.quantity_ref,
            price_resolution_ref=observation.source_ref,
            time_in_force_resolution_ref=intent.time_in_force_ref,
            market_snapshot_ref=observation.source_ref,
            risk_check_ref=reservation.risk_check_ref,
            materialize_enabled=True,
            evidence_refs=(reservation.risk_check_ref, observation.source_ref),
            recorded_by=actor,
            **common,
        )
        materialization = _full_ref(materialization, "materialization_ref", "order_materialization_")
        materialization = _ensure(
            self._materializations,
            "materialization",
            "record_materialization",
            materialization.materialization_ref,
            materialization,
            known_order_intent_refs={intent.order_intent_ref},
            known_runtime_promotion_refs={promotion.runtime_promotion_ref},
            order_intent=intent,
            runtime_promotion=promotion,
        )

        safety_refs = {
            "credential_check_ref": observation.credential_check_ref,
            "ip_allowlist_ref": observation.ip_allowlist_ref,
            "withdrawal_disabled_ref": observation.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": observation.hmac_replay_protection_ref,
            "health_check_ref": observation.health_check_ref,
            "rate_limit_ref": observation.rate_limit_ref,
        }
        connectivity = ExecutionVenueConnectivityCheckRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            venue_ref=expected_venue_ref,
            guarded_venue_ref="guarded:" + expected_venue_ref,
            runtime="live",
            asset_class="crypto_perp",
            connectivity_status="accepted",
            checker_ref="copy_trade_account_observer:v1",
            audit_record_ref="copy_connectivity_audit_" + content_hash(audit_seed),
            instrument_ref=instrument_ref,
            connectivity_check_hash=observation.source_ref,
            evidence_refs=(observation.source_ref,),
            recorded_by=actor,
            **common,
            **safety_refs,
        )
        connectivity = _full_ref(connectivity, "venue_connectivity_check_ref", "venue_connectivity_check_")
        connectivity = _ensure(
            self._connectivity,
            "check",
            "record_check",
            connectivity.venue_connectivity_check_ref,
            connectivity,
            known_order_intent_refs={intent.order_intent_ref},
            known_runtime_promotion_refs={promotion.runtime_promotion_ref},
            order_intent=intent,
            runtime_promotion=promotion,
        )

        safety = ExecutionVenueSafetyAttestationRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            venue_ref=expected_venue_ref,
            guarded_venue_ref="guarded:" + expected_venue_ref,
            runtime="live",
            asset_class="crypto_perp",
            attestation_status="accepted",
            audit_record_ref="copy_safety_audit_" + content_hash(audit_seed),
            venue_connectivity_check_ref=connectivity.venue_connectivity_check_ref,
            instrument_ref=instrument_ref,
            evidence_refs=(observation.source_ref, connectivity.venue_connectivity_check_ref),
            recorded_by=actor,
            **common,
            **safety_refs,
        )
        safety = _full_ref(safety, "venue_safety_attestation_ref", "venue_safety_attestation_")
        safety = _ensure(
            self._safety,
            "attestation",
            "record_attestation",
            safety.venue_safety_attestation_ref,
            safety,
            known_order_intent_refs={intent.order_intent_ref},
            known_runtime_promotion_refs={promotion.runtime_promotion_ref},
            known_venue_connectivity_check_refs={connectivity.venue_connectivity_check_ref},
            order_intent=intent,
            runtime_promotion=promotion,
            venue_connectivity_check=connectivity,
        )

        capability = ExecutionVenueCapabilityRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            venue_ref=expected_venue_ref,
            guarded_venue_ref="guarded:" + expected_venue_ref,
            submitter_ref="copy_trade_signal_relayer:v1",
            runtime="live",
            asset_class="crypto_perp",
            capability_status="ready",
            audit_record_ref="copy_capability_audit_" + content_hash(audit_seed),
            venue_safety_attestation_ref=safety.venue_safety_attestation_ref,
            instrument_ref=instrument_ref,
            can_submit_orders=True,
            evidence_refs=(safety.venue_safety_attestation_ref,),
            recorded_by=actor,
            **common,
            **safety_refs,
        )
        capability = _full_ref(capability, "venue_capability_ref", "venue_capability_")
        capability = _ensure(
            self._capabilities,
            "capability",
            "record_capability",
            capability.venue_capability_ref,
            capability,
            known_order_intent_refs={intent.order_intent_ref},
            known_runtime_promotion_refs={promotion.runtime_promotion_ref},
            known_venue_safety_attestation_refs={safety.venue_safety_attestation_ref},
            order_intent=intent,
            runtime_promotion=promotion,
            venue_safety_attestation=safety,
        )

        submit_request = ExecutionSubmitRequestRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submitter_ref=capability.submitter_ref,
            guarded_venue_ref=capability.guarded_venue_ref,
            venue_ref=capability.venue_ref,
            submit_request_mode="live",
            submit_request_status="ready",
            audit_record_ref="copy_submit_request_audit_" + content_hash(audit_seed),
            order_schema_ref=materialization.order_schema_ref,
            order_payload_hash=materialization.order_payload_hash,
            submit_request_schema_ref="schema:copy_trade_submit_request:v1",
            submit_request_hash="sha256:" + content_hash(
                {"materialization_ref": materialization.materialization_ref, "capability_ref": capability.venue_capability_ref}
            ),
            client_order_ref_hash=execution_client_order_ref_hash(str(order.client_order_id or "")),
            evidence_refs=(materialization.materialization_ref, capability.venue_capability_ref),
            recorded_by=actor,
            **common,
        )
        submit_request = _full_ref(submit_request, "submit_request_ref", "submit_request_")
        submit_request = _ensure(
            self._submit_requests,
            "request",
            "record_request",
            submit_request.submit_request_ref,
            submit_request,
            known_order_intent_refs={intent.order_intent_ref},
            known_runtime_promotion_refs={promotion.runtime_promotion_ref},
            known_order_materialization_refs={materialization.materialization_ref},
            known_venue_capability_refs={capability.venue_capability_ref},
            order_intent=intent,
            runtime_promotion=promotion,
            order_materialization=materialization,
            venue_capability=capability,
        )
        return PreparedCopyTradeExecution(
            promotion=promotion,
            intent=intent,
            materialization=materialization,
            connectivity=connectivity,
            safety=safety,
            capability=capability,
            submit_request=submit_request,
            reservation=reservation,
            observation=observation,
            attestation=Attestation(
                passed=True,
                verdict_id=safety.venue_safety_attestation_ref,
                checker_model="copy_trade_account_observer:v1",
                note="account-bound live safety attestation",
            ),
        )

    def _record_submission(
        self,
        prepared: PreparedCopyTradeExecution,
        *,
        status: str,
        ack_ref: str | None,
        venue_order_ref: str | None,
        actor: str,
        before_persist: Callable[[ExecutionOrderSubmissionRecord], None] | None = None,
    ) -> ExecutionOrderSubmissionRecord:
        common = {
            "permission_gate_ref": prepared.promotion.permission_gate_ref,
            "order_guard_ref": prepared.promotion.order_guard_ref,
            "idempotency_key": prepared.intent.idempotency_key,
            "kill_switch_ref": prepared.promotion.kill_switch_ref,
            "secret_ref": prepared.promotion.secret_ref,
            "responsibility_boundary_ref": prepared.promotion.responsibility_boundary_ref,
        }
        record = ExecutionOrderSubmissionRecord(
            order_intent_ref=prepared.intent.order_intent_ref,
            runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
            submitter_ref=prepared.capability.submitter_ref,
            guarded_venue_ref=prepared.capability.guarded_venue_ref,
            venue_ref=prepared.capability.venue_ref,
            submission_mode="live",
            audit_record_ref="copy_submission_audit_" + content_hash(prepared.reservation.reservation_ref),
            submit_enabled=True,
            order_materialization_ref=prepared.materialization.materialization_ref,
            venue_capability_ref=prepared.capability.venue_capability_ref,
            submit_request_ref=prepared.submit_request.submit_request_ref,
            submission_status=status,
            venue_order_ref=venue_order_ref,
            ack_ref=ack_ref,
            client_order_ref_hash=prepared.submit_request.client_order_ref_hash,
            evidence_refs=tuple(ref for ref in (prepared.submit_request.submit_request_ref, ack_ref) if ref),
            recorded_by=actor,
            **common,
        )
        if before_persist is not None:
            before_persist(record)
        return _ensure(
            self._submissions,
            "submission",
            "record_submission",
            record.submission_ref,
            record,
            known_order_intent_refs={prepared.intent.order_intent_ref},
            known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
            known_order_materialization_refs={prepared.materialization.materialization_ref},
            known_venue_capability_refs={prepared.capability.venue_capability_ref},
            known_submit_request_refs={prepared.submit_request.submit_request_ref},
            order_intent=prepared.intent,
            runtime_promotion=prepared.promotion,
            order_materialization=prepared.materialization,
            venue_capability=prepared.capability,
            submit_request=prepared.submit_request,
        )

    def record_success(
        self,
        prepared: PreparedCopyTradeExecution,
        *,
        ack: OrderAck,
        actor: str,
    ) -> dict[str, str]:
        ack_ref = "copy_trade_ack_" + content_hash(
            {
                "order_id": str(ack.order_id),
                "client_order_id": str(ack.client_order_id or ""),
                "accepted_at_utc": str(ack.accepted_at_utc),
                "status": str(ack.status),
            }
        )
        ack_status = str(ack.status or "").lower()
        rejected = ack_status == "rejected"
        invalid_ack: list[str] = []
        if ack_status not in {"new", "partially_filled", "filled", "canceled", "rejected", "expired"}:
            invalid_ack.append("status")
        if not rejected and not str(ack.order_id or "").strip():
            invalid_ack.append("venue_order_ref")
        if str(ack.client_order_id or "") != prepared.reservation.client_order_id:
            invalid_ack.append("client_order_id")
        try:
            accepted_at = datetime.fromisoformat(str(ack.accepted_at_utc))
            if accepted_at.tzinfo is None:
                raise ValueError("naive timestamp")
            prepared_at = datetime.fromisoformat(prepared.reservation.created_at_utc)
            age_s = (datetime.now(UTC) - accepted_at.astimezone(UTC)).total_seconds()
            if age_s < -5 or accepted_at.astimezone(UTC) < prepared_at.astimezone(UTC):
                invalid_ack.append("accepted_at_utc")
        except (TypeError, ValueError):
            invalid_ack.append("accepted_at_utc")
        if invalid_ack:
            reason_ref = "untrusted_ack_" + content_hash(
                {"ack_ref": ack_ref, "invalid_fields": sorted(set(invalid_ack))}
            )
            return {
                **self.record_failure(
                    prepared,
                    reason_ref=reason_ref,
                    definitive_reject=False,
                    actor=actor,
                ),
                "formal_status": "outcome_unknown",
                "formal_reason": reason_ref,
            }

        if ack_status in {"canceled", "expired"}:
            reason_ref = "terminal_ack_requires_reconciliation_" + content_hash(
                {"ack_ref": ack_ref, "status": ack_status}
            )

            def bind_unknown(submission_record: ExecutionOrderSubmissionRecord) -> None:
                self._risk_store.mark_submission_unknown(
                    prepared.reservation,
                    reason_ref=reason_ref,
                    submission_ref=submission_record.submission_ref,
                    venue_order_ref=submission_record.venue_order_ref,
                    ack_ref=submission_record.ack_ref,
                    actor=actor,
                )

            submission = self._record_submission(
                prepared,
                status="outcome_unknown",
                ack_ref=ack_ref,
                venue_order_ref=str(ack.order_id or "") or None,
                actor=actor,
                before_persist=bind_unknown,
            )
            reconciliation = reconcile_execution_venue_events(
                order_intent_ref=prepared.intent.order_intent_ref,
                runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                venue_order_ref=submission.venue_order_ref,
                audit_record_ref="copy_reconcile_audit_" + content_hash(submission.submission_ref),
                events=(),
                evidence_refs=(reason_ref,),
                recorded_by=actor,
            )
            reconciliation = _ensure(
                self._reconciliations,
                "reconciliation",
                "record_reconciliation",
                reconciliation.reconciliation_ref,
                reconciliation,
                known_order_intent_refs={prepared.intent.order_intent_ref},
                known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
                known_venue_event_refs=set(),
                known_submission_refs={submission.submission_ref},
                submission=submission,
                venue_events=(),
            )
            binding = self._risk_store.submission_binding_for_reservation(
                prepared.reservation.reservation_ref
            )
            if binding is None or not binding.get("binding_event_id"):
                raise CopyTradeFormalError("terminal ack lacks a durable projection binding")
            self._risk_store.mark_formal_projection_completed(
                prepared.reservation,
                binding_event_id=binding["binding_event_id"],
                submission_ref=submission.submission_ref,
                venue_event_ref=None,
                reconciliation_ref=reconciliation.reconciliation_ref,
            )
            return {
                "submission_ref": submission.submission_ref,
                "reconciliation_ref": reconciliation.reconciliation_ref,
                "formal_status": "outcome_unknown",
                "formal_reason": reason_ref,
            }

        def bind_risk(submission_record: ExecutionOrderSubmissionRecord) -> None:
            if rejected:
                self._risk_store.mark_venue_reject(
                    prepared.reservation,
                    reason_ref=ack_ref,
                    submission_ref=submission_record.submission_ref,
                    venue_order_ref=submission_record.venue_order_ref,
                    ack_ref=ack_ref,
                    ack_accepted_at_utc=str(ack.accepted_at_utc),
                    actor=actor,
                )
            else:
                self._risk_store.mark_submitted(
                    prepared.reservation,
                    submission_ref=submission_record.submission_ref,
                    venue_order_ref=str(ack.order_id),
                    ack_ref=ack_ref,
                    ack_accepted_at_utc=str(ack.accepted_at_utc),
                    ack_status=ack_status,
                    actor=actor,
                )

        submission = self._record_submission(
            prepared,
            status="rejected" if rejected else "accepted",
            ack_ref=ack_ref,
            venue_order_ref=str(ack.order_id or "") or None,
            actor=actor,
            before_persist=bind_risk,
        )
        event = ExecutionVenueEventRecord(
            order_intent_ref=prepared.intent.order_intent_ref,
            runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=submission.venue_ref,
            event_kind="rejected" if rejected else "accepted",
            status="rejected" if rejected else "accepted",
            audit_record_ref="copy_event_audit_" + content_hash(submission.submission_ref),
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            venue_order_ref=submission.venue_order_ref,
            client_order_ref=str(ack.client_order_id or "") or None,
            ack_ref=ack_ref,
            raw_event_hash="sha256:" + content_hash(
                {"ack_ref": ack_ref, "status": str(ack.status), "venue_order_ref": submission.venue_order_ref}
            ),
            evidence_refs=(ack_ref,),
            recorded_by=actor,
            created_at_utc=str(ack.accepted_at_utc),
        )
        event = _ensure(
            self._events,
            "event",
            "record_event",
            event.venue_event_ref,
            event,
            known_order_intent_refs={prepared.intent.order_intent_ref},
            known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
            known_submission_refs={submission.submission_ref},
            submission=submission,
        )
        reconciliation = reconcile_execution_venue_events(
            order_intent_ref=prepared.intent.order_intent_ref,
            runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_order_ref=submission.venue_order_ref,
            audit_record_ref="copy_reconcile_audit_" + content_hash(submission.submission_ref),
            events=(event,),
            evidence_refs=(event.venue_event_ref,),
            recorded_by=actor,
        )
        reconciliation = _ensure(
            self._reconciliations,
            "reconciliation",
            "record_reconciliation",
            reconciliation.reconciliation_ref,
            reconciliation,
            known_order_intent_refs={prepared.intent.order_intent_ref},
            known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
            known_venue_event_refs={event.venue_event_ref},
            known_submission_refs={submission.submission_ref},
            submission=submission,
            venue_events=(event,),
        )
        binding = self._risk_store.submission_binding_for_reservation(
            prepared.reservation.reservation_ref
        )
        if binding is None or not binding.get("binding_event_id"):
            raise CopyTradeFormalError("ack outcome lacks a durable projection binding")
        self._risk_store.mark_formal_projection_completed(
            prepared.reservation,
            binding_event_id=binding["binding_event_id"],
            submission_ref=submission.submission_ref,
            venue_event_ref=event.venue_event_ref,
            reconciliation_ref=reconciliation.reconciliation_ref,
        )
        return {
            "submission_ref": submission.submission_ref,
            "venue_event_ref": event.venue_event_ref,
            "reconciliation_ref": reconciliation.reconciliation_ref,
            "formal_status": (
                "rejected"
                if rejected
                else "needs_reconcile"
                if ack_status in {"partially_filled", "filled"}
                else "placed"
            ),
        }

    def _risk_bound_submission_for_observation(
        self,
        *,
        client_order_id: str,
        venue_order_ref: str,
        expected_submission_ref: str | None,
    ) -> ExecutionOrderSubmissionRecord:
        client_id = str(client_order_id or "").strip()
        order_ref = str(venue_order_ref or "").strip()
        expected_ref = str(expected_submission_ref or "").strip()
        if not client_id or not order_ref:
            raise CopyTradeFormalError(
                "formal observation lacks exact client and venue order identities"
            )
        try:
            bindings = self._risk_store.verified_formal_submission_bindings()
        except CopyTradeRiskError as exc:
            raise CopyTradeFormalError(
                "formal observation risk authority is unavailable"
            ) from exc
        matches = [
            binding
            for binding in bindings
            if binding.outcome_state in {"submission_accepted", "submission_unknown"}
            and binding.client_order_id == client_id
            and (not binding.venue_order_ref or binding.venue_order_ref == order_ref)
            and (not expected_ref or binding.submission_ref == expected_ref)
        ]
        if len(matches) != 1:
            raise CopyTradeFormalError(
                "formal observation does not resolve to exactly one risk-bound submission"
            )
        binding = matches[0]
        try:
            submission = self._submissions.submission(binding.submission_ref)
        except KeyError as exc:
            raise CopyTradeFormalError(
                "risk-bound formal submission is missing"
            ) from exc
        allowed_statuses = (
            {"accepted", "outcome_unknown"}
            if binding.outcome_state == "submission_accepted"
            else {"outcome_unknown"}
        )
        if (
            submission.submission_status not in allowed_statuses
            or submission.client_order_ref_hash
            != execution_client_order_ref_hash(client_id)
            or (
                submission.venue_order_ref
                and submission.venue_order_ref != order_ref
            )
            or (
                binding.venue_order_ref
                and submission.venue_order_ref
                and binding.venue_order_ref != submission.venue_order_ref
            )
        ):
            raise CopyTradeFormalError(
                "risk-bound formal submission differs from the observation identity"
            )
        return submission

    def record_execution_report(
        self,
        report: ExecutionReport,
        *,
        actor: str,
        expected_submission_ref: str | None = None,
        normalized_cost_usdt: float | None = None,
        cost_conversion_ref: str | None = None,
    ) -> dict[str, str]:
        """Project one source-identified fill into the formal and risk ledgers."""

        self._refresh_projection_stores()
        if report.status not in {"partially_filled", "filled"}:
            raise CopyTradeFormalError("execution report is not a fill lifecycle event")
        if not str(report.client_order_id or "").strip():
            raise CopyTradeFormalError("execution report lacks client-order identity")
        if not str(report.source_event_ref or "").strip() or not str(report.raw_event_hash or "").startswith(
            "sha256:"
        ):
            raise CopyTradeFormalError("execution report lacks source event evidence")
        submission = self._risk_bound_submission_for_observation(
            client_order_id=str(report.client_order_id),
            venue_order_ref=str(report.order_id),
            expected_submission_ref=expected_submission_ref,
        )
        intent = self._intents.intent(submission.order_intent_ref)
        promotion = self._runtime_promotions.promotion(submission.runtime_promotion_ref)
        reservation = self._risk_store.reservation_for_submission(submission.submission_ref)
        event_kind = str(report.status)
        fill_ref = str(report.source_event_ref)
        fee_ref = "execution_fee_" + content_hash(
            {
                "fill_ref": fill_ref,
                "commission": report.commission,
                "commission_asset": report.commission_asset,
                "normalized_cost_usdt": normalized_cost_usdt,
                "cost_conversion_ref": cost_conversion_ref,
            }
        )
        event = ExecutionVenueEventRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=submission.venue_ref,
            event_kind=event_kind,
            status=event_kind,
            audit_record_ref="copy_fill_audit_" + content_hash(fill_ref),
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            venue_order_ref=str(report.order_id),
            client_order_ref=str(report.client_order_id),
            fill_ref=fill_ref,
            quantity_ref="fill_quantity_" + content_hash(
                {
                    "filled_qty": report.filled_qty,
                    "cumulative_filled_qty": report.cumulative_filled_qty,
                }
            ),
            price_ref="fill_price_" + content_hash({"fill_price": report.fill_price}),
            fee_ref=fee_ref,
            raw_event_hash=report.raw_event_hash,
            evidence_refs=tuple(
                ref
                for ref in (fill_ref, report.raw_event_hash, cost_conversion_ref)
                if str(ref or "").strip()
            ),
            recorded_by=actor,
            created_at_utc=report.timestamp_utc,
        )
        return self._commit_execution_report_projection(
            report=report,
            actor=actor,
            normalized_cost_usdt=normalized_cost_usdt,
            cost_conversion_ref=cost_conversion_ref,
            submission=submission,
            intent=intent,
            promotion=promotion,
            reservation=reservation,
            event=event,
        )

    def _commit_execution_report_projection(
        self,
        *,
        report: ExecutionReport,
        actor: str,
        normalized_cost_usdt: float | None,
        cost_conversion_ref: str | None,
        submission: Any,
        intent: Any,
        promotion: Any,
        reservation: PreTradeReservation,
        event: ExecutionVenueEventRecord,
    ) -> dict[str, str]:
        """Serialize validation, formal appends, and the matching risk transition."""

        with self._risk_store.formal_projection_guard(reservation.reservation_ref):
            self._refresh_projection_stores()
            existing_events = [
                item
                for item in self._events.events()
                if item.submission_ref == submission.submission_ref
                and item.venue_event_ref != event.venue_event_ref
            ]
            events = tuple(
                sorted(
                    (*existing_events, event),
                    key=lambda item: (item.created_at_utc, item.venue_event_ref),
                )
            )
            reconciliation = reconcile_execution_venue_events(
                order_intent_ref=intent.order_intent_ref,
                runtime_promotion_ref=promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                venue_order_ref=str(report.order_id),
                audit_record_ref="copy_fill_reconcile_audit_" + content_hash(
                    {
                        "submission_ref": submission.submission_ref,
                        "event_refs": [item.venue_event_ref for item in events],
                    }
                ),
                events=events,
                evidence_refs=tuple(item.venue_event_ref for item in events),
                recorded_by=actor,
            )
            claim_event_id = self._risk_store.claim_fill_projection(
                reservation,
                report=report,
                submission_ref=submission.submission_ref,
                venue_event=event,
                reconciliation=reconciliation,
                normalized_cost_usdt=normalized_cost_usdt,
                cost_conversion_ref=cost_conversion_ref,
                realized_pnl_delta=report.realized_pnl_delta,
                realized_pnl_complete=report.realized_pnl_complete,
                actor=actor,
            )
            event = _ensure(
                self._events,
                "event",
                "record_event",
                event.venue_event_ref,
                event,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_submission_refs={submission.submission_ref},
                submission=submission,
            )
            reconciliation = _ensure(
                self._reconciliations,
                "reconciliation",
                "record_reconciliation",
                reconciliation.reconciliation_ref,
                reconciliation,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_venue_event_refs={item.venue_event_ref for item in events},
                known_submission_refs={submission.submission_ref},
                submission=submission,
                venue_events=events,
            )
            self._risk_store.finalize_lifecycle_projection_claim(
                reservation,
                claim_event_id=claim_event_id,
            )
            return {
                "submission_ref": submission.submission_ref,
                "venue_event_ref": event.venue_event_ref,
                "reconciliation_ref": reconciliation.reconciliation_ref,
                "formal_status": "filled" if report.status == "filled" else "needs_reconcile",
            }

    def record_order_observation(
        self,
        observation: OrderExecutionObservation,
        *,
        actor: str,
        expected_submission_ref: str | None = None,
    ) -> dict[str, str]:
        """Project an authoritative canceled/expired/rejected order terminal.

        Fill rows must be projected first.  This method closes only the
        remaining reservation after the formal terminal reconciliation exists.
        """

        self._refresh_projection_stores()
        if observation.status not in {"canceled", "expired", "rejected"}:
            raise CopyTradeFormalError("order observation is not a supported terminal lifecycle event")
        if not str(observation.client_order_id or "").strip() or not str(observation.order_id or "").strip():
            raise CopyTradeFormalError("terminal order observation lacks exact order identities")
        if not str(observation.source_event_ref or "").strip() or not str(
            observation.raw_event_hash or ""
        ).startswith("sha256:"):
            raise CopyTradeFormalError("terminal order observation lacks source evidence")
        submission = self._risk_bound_submission_for_observation(
            client_order_id=observation.client_order_id,
            venue_order_ref=observation.order_id,
            expected_submission_ref=expected_submission_ref,
        )
        reservation = self._risk_store.reservation_for_submission(submission.submission_ref)
        tolerance = max(reservation.order_quantity, 1.0) * 1e-9
        if observation.symbol.upper() != reservation.symbol or observation.side != reservation.side:
            raise CopyTradeFormalError("terminal order observation instrument or side mismatch")
        if abs(observation.requested_qty - reservation.order_quantity) > tolerance:
            raise CopyTradeFormalError("terminal order observation quantity mismatch")
        if (
            observation.cumulative_filled_qty < -tolerance
            or observation.cumulative_filled_qty > observation.requested_qty + tolerance
        ):
            raise CopyTradeFormalError("terminal order observation has invalid cumulative quantity")
        intent = self._intents.intent(submission.order_intent_ref)
        promotion = self._runtime_promotions.promotion(submission.runtime_promotion_ref)
        event = ExecutionVenueEventRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=submission.venue_ref,
            event_kind=observation.status,
            status=observation.status,
            audit_record_ref="copy_terminal_audit_" + content_hash(observation.source_event_ref),
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            venue_order_ref=observation.order_id,
            client_order_ref=observation.client_order_id,
            ack_ref=(observation.source_event_ref if observation.status == "rejected" else None),
            quantity_ref="terminal_quantity_" + content_hash(
                {
                    "requested_qty": observation.requested_qty,
                    "cumulative_filled_qty": observation.cumulative_filled_qty,
                }
            ),
            raw_event_hash=observation.raw_event_hash,
            evidence_refs=(observation.source_event_ref, observation.raw_event_hash),
            recorded_by=actor,
            created_at_utc=observation.observed_at_utc,
        )
        return self._commit_terminal_observation_projection(
            observation=observation,
            actor=actor,
            submission=submission,
            intent=intent,
            promotion=promotion,
            reservation=reservation,
            event=event,
        )

    def _commit_terminal_observation_projection(
        self,
        *,
        observation: OrderExecutionObservation,
        actor: str,
        submission: Any,
        intent: Any,
        promotion: Any,
        reservation: PreTradeReservation,
        event: ExecutionVenueEventRecord,
    ) -> dict[str, str]:
        with self._risk_store.formal_projection_guard(reservation.reservation_ref):
            self._refresh_projection_stores()
            existing_events = [
                item
                for item in self._events.events()
                if item.submission_ref == submission.submission_ref
                and item.venue_event_ref != event.venue_event_ref
            ]
            events = tuple(
                sorted(
                    (*existing_events, event),
                    key=lambda item: (item.created_at_utc, item.venue_event_ref),
                )
            )
            reconciliation = reconcile_execution_venue_events(
                order_intent_ref=intent.order_intent_ref,
                runtime_promotion_ref=promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                venue_order_ref=observation.order_id,
                audit_record_ref="copy_terminal_reconcile_audit_" + content_hash(
                    {
                        "submission_ref": submission.submission_ref,
                        "event_refs": [item.venue_event_ref for item in events],
                    }
                ),
                events=events,
                evidence_refs=tuple(item.venue_event_ref for item in events),
                recorded_by=actor,
            )
            tolerance = max(reservation.order_quantity, 1.0) * 1e-9
            expected_status = (
                "closed_no_fill"
                if observation.cumulative_filled_qty <= tolerance
                else "closed_partial_fill"
            )
            if reconciliation.status != expected_status or reconciliation.action_required:
                raise CopyTradeFormalError(
                    f"terminal order reconciliation did not close safely: {reconciliation.status}"
                )
            claim_event_id = self._risk_store.claim_terminal_projection(
                reservation,
                observation=observation,
                submission_ref=submission.submission_ref,
                venue_event=event,
                reconciliation=reconciliation,
                actor=actor,
            )
            event = _ensure(
                self._events,
                "event",
                "record_event",
                event.venue_event_ref,
                event,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_submission_refs={submission.submission_ref},
                submission=submission,
            )
            reconciliation = _ensure(
                self._reconciliations,
                "reconciliation",
                "record_reconciliation",
                reconciliation.reconciliation_ref,
                reconciliation,
                known_order_intent_refs={intent.order_intent_ref},
                known_runtime_promotion_refs={promotion.runtime_promotion_ref},
                known_venue_event_refs={item.venue_event_ref for item in events},
                known_submission_refs={submission.submission_ref},
                submission=submission,
                venue_events=events,
            )
            self._risk_store.finalize_lifecycle_projection_claim(
                reservation,
                claim_event_id=claim_event_id,
            )
            return {
                "submission_ref": submission.submission_ref,
                "venue_event_ref": event.venue_event_ref,
                "reconciliation_ref": reconciliation.reconciliation_ref,
                "formal_status": expected_status,
            }

    def record_failure(
        self,
        prepared: PreparedCopyTradeExecution,
        *,
        reason_ref: str,
        definitive_reject: bool,
        actor: str,
    ) -> dict[str, str]:
        ack_ref = reason_ref if definitive_reject else None
        def bind_risk(submission_record: ExecutionOrderSubmissionRecord) -> None:
            if definitive_reject:
                self._risk_store.mark_definitive_reject(
                    prepared.reservation,
                    reason_ref=reason_ref,
                    submission_ref=submission_record.submission_ref,
                    ack_ref=reason_ref,
                    actor=actor,
                )
            else:
                self._risk_store.mark_submission_unknown(
                    prepared.reservation,
                    reason_ref=reason_ref,
                    submission_ref=submission_record.submission_ref,
                    venue_order_ref=submission_record.venue_order_ref,
                    ack_ref=submission_record.ack_ref,
                    actor=actor,
                )

        submission = self._record_submission(
            prepared,
            status="rejected" if definitive_reject else "outcome_unknown",
            ack_ref=ack_ref,
            venue_order_ref=None,
            actor=actor,
            before_persist=bind_risk,
        )
        event: ExecutionVenueEventRecord | None = None
        if definitive_reject:
            event = ExecutionVenueEventRecord(
                order_intent_ref=prepared.intent.order_intent_ref,
                runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                venue_ref=submission.venue_ref,
                event_kind="rejected",
                status="rejected",
                audit_record_ref="copy_event_audit_" + content_hash(submission.submission_ref),
                order_guard_ref=submission.order_guard_ref,
                idempotency_key=submission.idempotency_key,
                client_order_ref=prepared.reservation.client_order_id,
                ack_ref=reason_ref,
                raw_event_hash="sha256:" + content_hash(reason_ref),
                evidence_refs=(reason_ref,),
                recorded_by=actor,
            )
            event = _ensure(
                self._events,
                "event",
                "record_event",
                event.venue_event_ref,
                event,
                known_order_intent_refs={prepared.intent.order_intent_ref},
                known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
                known_submission_refs={submission.submission_ref},
                submission=submission,
            )
            reconciliation = reconcile_execution_venue_events(
                order_intent_ref=prepared.intent.order_intent_ref,
                runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                audit_record_ref="copy_reconcile_audit_" + content_hash(submission.submission_ref),
                events=(event,),
                evidence_refs=(event.venue_event_ref,),
                recorded_by=actor,
            )
        else:
            reconciliation = reconcile_execution_venue_events(
                order_intent_ref=prepared.intent.order_intent_ref,
                runtime_promotion_ref=prepared.promotion.runtime_promotion_ref,
                submission_ref=submission.submission_ref,
                audit_record_ref="copy_reconcile_audit_" + content_hash(submission.submission_ref),
                events=(),
                evidence_refs=(reason_ref,),
                recorded_by=actor,
            )
        reconciliation = _ensure(
            self._reconciliations,
            "reconciliation",
            "record_reconciliation",
            reconciliation.reconciliation_ref,
            reconciliation,
            known_order_intent_refs={prepared.intent.order_intent_ref},
            known_runtime_promotion_refs={prepared.promotion.runtime_promotion_ref},
            known_venue_event_refs={event.venue_event_ref} if event is not None else set(),
            known_submission_refs={submission.submission_ref},
            submission=submission,
            venue_events=(event,) if event is not None else (),
        )
        binding = self._risk_store.submission_binding_for_reservation(
            prepared.reservation.reservation_ref
        )
        if binding is None or not binding.get("binding_event_id"):
            raise CopyTradeFormalError("failure outcome lacks a durable projection binding")
        self._risk_store.mark_formal_projection_completed(
            prepared.reservation,
            binding_event_id=binding["binding_event_id"],
            submission_ref=submission.submission_ref,
            venue_event_ref=event.venue_event_ref if event is not None else None,
            reconciliation_ref=reconciliation.reconciliation_ref,
        )
        result = {
            "submission_ref": submission.submission_ref,
            "reconciliation_ref": reconciliation.reconciliation_ref,
        }
        if event is not None:
            result["venue_event_ref"] = event.venue_event_ref
        return result


__all__ = [
    "CopyTradeFormalError",
    "CopyTradeFormalExecutionCoordinator",
    "CopyTradeRuntimeRequirements",
    "PreparedCopyTradeExecution",
    "runtime_requirements_for_follower",
    "validate_live_runtime_promotion",
]
