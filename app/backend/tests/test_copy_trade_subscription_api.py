from __future__ import annotations

from dataclasses import dataclass, replace
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.auth import require_user_dependency
from app.copy_trade import (
    CopyTradeError,
    CopyTradeService,
    Execution,
    FollowerFillEconomics,
    Follower,
    build_user_risk_choice,
    copy_trade_risk_disclosure_profile,
    runtime_approval_binding_for_follower,
    runtime_requirements_for_follower,
)
from app.execution.emergency import ActiveEmergencyVenueRegistry
from app.research_os import RuntimePromotionRecord
from app.research_os.execution_boundary import (
    PersistentConsentBackedUserRiskChoiceRegistry,
)
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    RiskConsentEntrypointCoverageRegistry,
)
from app.security.gate.account_halt import PersistentAccountHaltBarrier
from app.security.mainnet_guards import MainnetGuardsService


class _Broker:
    def __init__(self) -> None:
        self.has_key_calls = 0
        self.account_binding_calls = 0

    def has_key(self, _name: str, **_kwargs) -> bool:
        self.has_key_calls += 1
        return True

    def credential_binding_ref(self, _name: str, **_kwargs) -> str:
        self.account_binding_calls += 1
        return "exchange_credential_test"


class _Guards:
    def __init__(self, audit_service: MainnetGuardsService) -> None:
        self.audit_service = audit_service
        self.ip_allowed = True
        self.within_limit = True
        self.fail_log = False
        self.on_log = None
        self.logs: list[dict] = []

    def check_ip(self, _user_id: str, _source_ip: str) -> bool:
        return self.ip_allowed

    def get_config(self, _user_id: str):
        return SimpleNamespace(require_password_per_order=False)

    def check_within_daily_limit(self, _user_id: str, _notional: float) -> tuple[bool, str]:
        return self.within_limit, "daily limit rejected"

    def log_operation(self, _user_id: str, _operation: str, **kwargs) -> str:
        self.logs.append(kwargs)
        if self.on_log is not None:
            self.on_log()
        if self.fail_log:
            raise RuntimeError("audit unavailable")
        return self.audit_service.log_operation(_user_id, _operation, **kwargs)


class _PromotionStore:
    def __init__(self, promotion: RuntimePromotionRecord) -> None:
        self.value = promotion
        self.calls = 0

    def promotion(self, ref: str) -> RuntimePromotionRecord:
        self.calls += 1
        if ref != self.value.runtime_promotion_ref:
            raise KeyError(ref)
        return self.value

    def refresh(self) -> None:
        return None


class _ApprovalStore:
    def __init__(self, approval) -> None:
        self.approval = approval

    def get(self, ref: str):
        if ref != "approval-1":
            raise KeyError(ref)
        return self.approval


@dataclass
class _Handle:
    account_ref: str
    owner_user_id: str = "follower-user"
    keystore_name: str = "mainnet-key"
    credential_binding_ref: str = "exchange_credential_test"

    @property
    def name(self) -> str:
        return f"handle:{self.account_ref}"

    def list_open_positions(self):
        return []

    def list_open_order_refs(self):
        return ()

    def emergency_cancel_all(self):
        return {"ok": True, "verified_noop": True, "actions": []}

    def reconcile_emergency_actions_for_halt(self, _context):
        return ()

    def close_open_position(self, _position):
        raise AssertionError("zero-position test handle must not submit a close")

    def close_open_position_for_halt(self, _position, _context):
        raise AssertionError("zero-position test handle must not submit a contextual close")

    def verify_emergency_flat(self, *, close_positions=True):
        return {
            "ok": True,
            "normal_open_order_refs": [],
            "algo_open_order_refs": [],
            "open_positions": [],
        }


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/subscribe",
            "raw_path": b"/subscribe",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 9000),
            "server": ("test", 80),
        }
    )


def _payload(
    promotion_ref: str,
    choice_ref: str = "",
    consent_event_ref: str = "",
) -> dict:
    profile = copy_trade_risk_disclosure_profile()
    return {
        "binance_network": "mainnet",
        "binance_keystore_name": "mainnet-key",
        "runtime_promotion_ref": promotion_ref,
        "user_risk_choice_ref": choice_ref,
        "user_risk_consent_event_ref": consent_event_ref,
        "selected_risk_path": "small_live",
        "risk_disclosure_profile_ref": profile["profile_ref"],
        "risk_disclosures_acknowledged": True,
        "invest_amount": 1_000.0,
        "per_order_max_usdt": 100.0,
        "daily_loss_limit_pct": 0.05,
        "max_positions": 3,
        "max_leverage": 2.0,
        "password": "server-verified-by-test-double",
    }


def _install_harness(monkeypatch, tmp_path, *, asset_class: str = "crypto_perp"):
    service = CopyTradeService(tmp_path / "copy-trade.sqlite3")
    master = service.register_master(
        "master-user",
        "Master",
        asset_class=asset_class,
    )
    provisional = Follower(
        follower_id=f"follower-user::{master.master_id}",
        user_id="follower-user",
        master_id=master.master_id,
        invest_amount=1_000.0,
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref="exchange_credential_test",
    )
    profile = copy_trade_risk_disclosure_profile()
    choice = build_user_risk_choice(
        provisional,
        owner_user_id="follower-user",
        selected_risk_path="small_live",
        risk_disclosure_profile_ref=profile["profile_ref"],
    )
    preliminary_requirements = runtime_requirements_for_follower(
        provisional,
        risk_choice=choice,
    )
    challenge = service.risk_consents.issue_challenge(
        owner_user_id="follower-user",
        follower_id=provisional.follower_id,
        master_id=master.master_id,
        account_binding_ref=provisional.account_binding_ref,
        credential_binding_ref=provisional.credential_binding_ref,
        subject_ref=preliminary_requirements.subject_ref,
        runtime_request_ref=preliminary_requirements.request_ref,
        risk_profile_ref=profile["profile_ref"],
        source_ip_hash=service.risk_consents.source_ip_hash("127.0.0.1"),
        payload={
            "schema_version": 1,
            "risk_profile": profile,
            "required_acknowledgement_refs": profile["required_acknowledgement_refs"],
            "normalized_risk_limits": {
                "invest_amount": 1_000.0,
                "per_order_max_usdt": 100.0,
                "daily_loss_limit_pct": 0.05,
                "max_positions": 3,
                "max_leverage": 2.0,
            },
            "binance_keystore_name": "mainnet-key",
            "proposed_user_risk_choice": choice.to_dict(),
        },
    )
    event = service.risk_consents.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="follower-user",
        user_risk_choice_ref=choice.choice_ref,
        user_risk_choice=choice.to_dict(),
        acknowledged_item_refs=profile["required_acknowledgement_refs"],
        source_ip_hash=service.risk_consents.source_ip_hash("127.0.0.1"),
        password_verified=True,
        totp_verified=False,
    )
    choices = PersistentConsentBackedUserRiskChoiceRegistry(
        service.risk_consents,
        legacy_path=tmp_path / "user-risk-choices.jsonl",
    )
    coverage_registry = RiskConsentEntrypointCoverageRegistry(
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal-coverage.jsonl"),
        service.risk_consents,
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
    )
    provisional = replace(
        provisional,
        user_risk_choice_ref=choice.choice_ref,
        user_risk_consent_event_ref=event.consent_event_ref,
    )
    requirements = runtime_requirements_for_follower(provisional, risk_choice=choice)
    approval_binding = runtime_approval_binding_for_follower(
        provisional,
        risk_choice=choice,
    )
    promotion = RuntimePromotionRecord(
        **requirements.to_dict(),
        asset_class="crypto_perp",
        source_runtime="testnet",
        target_runtime="live",
        testnet_run_ref="execution_reconcile_v2_testnet",
        approval_ref="approval-1",
        evidence_refs=(
            "execution_reconcile_v2_testnet",
            choice.choice_ref,
            event.consent_event_ref,
        ),
        mock_profile="none",
    )
    approval = SimpleNamespace(
        decision="approved",
        action_kind="live_order",
        model_id=approval_binding["approval_target_ref"],
        evidence={"copy_trade_runtime_approval": approval_binding},
        approver="risk-officer",
        created_by="requester",
    )
    broker = _Broker()
    guards = _Guards(MainnetGuardsService(tmp_path / "copy-trade.sqlite3"))
    promotions = _PromotionStore(promotion)
    active = ActiveEmergencyVenueRegistry()
    halt_barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")

    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", service)
    monkeypatch.setattr(main, "COPY_TRADE_RISK_CONSENT_STORE", service.risk_consents)
    monkeypatch.setattr(main, "ORDER_BROKER", broker)
    monkeypatch.setattr(main, "MAINNET_GUARDS", guards)
    monkeypatch.setattr(main, "RUNTIME_PROMOTIONS", promotions)
    monkeypatch.setattr(main, "USER_RISK_CHOICES", choices)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_registry)
    monkeypatch.setattr(main, "APPROVAL_GATE_STORE", _ApprovalStore(approval))
    monkeypatch.setattr(main, "ACTIVE_EMERGENCY_VENUES", active)
    monkeypatch.setattr(main, "ACCOUNT_HALT_BARRIER", halt_barrier)
    monkeypatch.setattr(main, "_user_keystore_ref", lambda _user_id, alias: str(alias))
    monkeypatch.setattr(main, "_verify_second_factor_result", lambda *_args: (True, False))
    monkeypatch.setattr(main, "_copy_trade_formal_testnet_subject", lambda _ref: requirements.subject_ref)
    monkeypatch.setattr(main, "_copy_trade_formal_testnet_evidence", lambda _ref, _follower: True)
    monkeypatch.setattr(
        main,
        "_emergency_handle_for_follower",
        lambda follower, **_kwargs: _Handle(follower.account_binding_ref),
    )
    monkeypatch.setattr(
        main,
        "_copy_trade_subscription_safety_observation",
        lambda follower, _handle: SimpleNamespace(
            account_ref="exchange_account_uid_test",
            permission_warnings=(),
        ),
    )
    return SimpleNamespace(
        service=service,
        master=master,
        promotion=promotion,
        choice=choice,
        challenge=challenge,
        event=event,
        choices=choices,
        coverage_registry=coverage_registry,
        profile=profile,
        requirements=requirements,
        broker=broker,
        guards=guards,
        promotions=promotions,
        active=active,
        halt_barrier=halt_barrier,
    )


def _subscribe(harness):
    return main.ct_subscribe(
        harness.master.master_id,
        _request(),
        _payload(
            harness.promotion.runtime_promotion_ref,
            harness.choice.choice_ref,
            harness.event.consent_event_ref,
        ),
        SimpleNamespace(user_id="follower-user"),
    )


def test_mainnet_spot_rejects_before_sensitive_surfaces(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path, asset_class="crypto_spot")

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 400
    assert harness.broker.has_key_calls == 0
    assert harness.broker.account_binding_calls == 0
    assert harness.promotions.calls == 0
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None
    assert harness.active.account_refs() == ()


def test_missing_ip_or_second_factor_calls_no_broker_or_mutating_surface(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    harness.guards.ip_allowed = False

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 400
    assert harness.broker.has_key_calls == 0
    assert harness.broker.account_binding_calls == 0
    assert harness.promotions.calls == 0
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None
    assert harness.active.account_refs() == ()


def test_unknown_promotion_does_not_fetch_credentials(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    payload = _payload(
        "runtime_promotion_v2_unknown",
        harness.choice.choice_ref,
        harness.event.consent_event_ref,
    )

    with pytest.raises(HTTPException) as caught:
        main.ct_subscribe(
            harness.master.master_id,
            _request(),
            payload,
            SimpleNamespace(user_id="follower-user"),
        )

    assert caught.value.status_code == 400
    assert harness.broker.has_key_calls == 0
    assert harness.broker.account_binding_calls == 0
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None


def test_missing_or_cross_owner_risk_choice_rejects_before_broker_access(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)

    for choice_ref in ("", "user_risk_choice_v2_unknown"):
        with pytest.raises(HTTPException) as caught:
            main.ct_subscribe(
                harness.master.master_id,
                _request(),
                _payload(
                    harness.promotion.runtime_promotion_ref,
                    choice_ref,
                    harness.event.consent_event_ref,
                ),
                SimpleNamespace(user_id="follower-user"),
            )
        assert caught.value.status_code == 403

    bob_follower = replace(
        Follower(
            follower_id=f"bob::{harness.master.master_id}",
            user_id="bob",
            master_id=harness.master.master_id,
            invest_amount=1_000.0,
            per_order_max_usdt=100.0,
            daily_loss_limit_pct=0.05,
            max_positions=3,
            max_leverage=2.0,
            binance_keystore_name="bob-key",
            binance_network="mainnet",
            account_binding_ref="exchange_account_uid_bob",
        )
    )
    bob_choice = build_user_risk_choice(
        bob_follower,
        owner_user_id="bob",
        selected_risk_path="small_live",
        risk_disclosure_profile_ref=harness.profile["profile_ref"],
    )
    bob_requirements = runtime_requirements_for_follower(
        bob_follower,
        risk_choice=bob_choice,
    )
    bob_challenge = harness.service.risk_consents.issue_challenge(
        owner_user_id="bob",
        follower_id=bob_follower.follower_id,
        master_id=bob_follower.master_id,
        account_binding_ref=bob_follower.account_binding_ref,
        credential_binding_ref="exchange_credential_bob",
        subject_ref=bob_requirements.subject_ref,
        runtime_request_ref=bob_requirements.request_ref,
        risk_profile_ref=harness.profile["profile_ref"],
        source_ip_hash=harness.service.risk_consents.source_ip_hash("127.0.0.1"),
        payload={
            "risk_profile": harness.profile,
            "required_acknowledgement_refs": harness.profile[
                "required_acknowledgement_refs"
            ],
            "proposed_user_risk_choice": bob_choice.to_dict(),
        },
    )
    harness.service.risk_consents.consume_challenge(
        challenge_ref=bob_challenge.challenge_ref,
        owner_user_id="bob",
        user_risk_choice_ref=bob_choice.choice_ref,
        user_risk_choice=bob_choice.to_dict(),
        acknowledged_item_refs=harness.profile["required_acknowledgement_refs"],
        source_ip_hash=harness.service.risk_consents.source_ip_hash("127.0.0.1"),
        password_verified=True,
        totp_verified=False,
    )
    harness.choices.refresh()
    with pytest.raises(HTTPException) as caught:
        main.ct_subscribe(
            harness.master.master_id,
            _request(),
            _payload(
                harness.promotion.runtime_promotion_ref,
                bob_choice.choice_ref,
                harness.event.consent_event_ref,
            ),
            SimpleNamespace(user_id="follower-user"),
        )
    assert caught.value.status_code == 403
    assert harness.broker.has_key_calls == 0
    assert harness.broker.account_binding_calls == 0


def test_risk_choice_limits_and_promotion_evidence_are_exact_before_broker_access(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    changed_limits = _payload(
        harness.promotion.runtime_promotion_ref,
        harness.choice.choice_ref,
        harness.event.consent_event_ref,
    )
    changed_limits["invest_amount"] = 1_001.0
    with pytest.raises(HTTPException) as caught:
        main.ct_subscribe(
            harness.master.master_id,
            _request(),
            changed_limits,
            SimpleNamespace(user_id="follower-user"),
        )
    assert caught.value.status_code == 403
    assert harness.broker.has_key_calls == 0

    harness.promotions.value = replace(
        harness.promotion,
        evidence_refs=("execution_reconcile_v2_testnet",),
    )
    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)
    assert caught.value.status_code == 403
    assert harness.broker.has_key_calls == 0


def test_observed_venue_uid_mismatch_compensates_without_follower_or_handle(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main,
        "_copy_trade_subscription_safety_observation",
        lambda _follower, _handle: SimpleNamespace(
            account_ref="exchange_account_uid_different",
            permission_warnings=(),
        ),
    )

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 403
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None
    assert harness.active.account_refs() == ()


def test_unbound_testnet_subject_rejects_before_credentials(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "_copy_trade_formal_testnet_subject", lambda _ref: "different-subject")

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 403
    assert harness.broker.has_key_calls == 0
    assert harness.broker.account_binding_calls == 0
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None


def test_exchange_safety_failure_leaves_no_follower_or_handle(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)

    def fail_safety(_follower, _handle):
        raise PermissionError("exchange IP restriction unavailable")

    monkeypatch.setattr(main, "_copy_trade_subscription_safety_observation", fail_safety)

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 403
    assert harness.broker.account_binding_calls == 1
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None
    assert harness.active.account_refs() == ()
    assert harness.guards.logs == []


def test_audit_failure_restores_exact_prior_state_and_registry(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    harness.guards.fail_log = True

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 503
    assert harness.service.get_follower(f"follower-user::{harness.master.master_id}") is None
    assert harness.active.account_refs() == ()
    assert [item["result"] for item in harness.guards.logs] == ["prepared", "failed"]


def test_audit_failure_restores_existing_stopped_row_exactly(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    harness.service.subscribe(
        "follower-user",
        harness.master.master_id,
        invest_amount=250.0,
        binance_keystore_name="old-key",
        binance_network="mainnet",
        per_order_max_usdt=25.0,
        daily_loss_limit_pct=0.02,
        max_positions=1,
        max_leverage=1.0,
        account_binding_ref="exchange_account_uid_test",
        runtime_promotion_ref="old-promotion",
        user_risk_choice_ref="old-choice",
    )
    assert harness.service.unsubscribe("follower-user", harness.master.master_id)
    before = harness.service.get_follower(f"follower-user::{harness.master.master_id}")
    assert before is not None
    harness.guards.fail_log = True

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 503
    after = harness.service.get_follower(f"follower-user::{harness.master.master_id}")
    assert after is not None
    assert after.to_dict() == before.to_dict()
    assert harness.active.account_refs() == ()


def test_automated_activation_compensation_cannot_downgrade_user_close_intent(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)

    def fail_after_user_close_latches() -> None:
        if harness.guards.logs[-1].get("result") != "ok":
            return
        harness.halt_barrier.begin_halt_many(
            "follower-user",
            ["exchange_account_uid_test"],
            halt_ref="user-emergency-close",
            action_name="emergency_close_all",
            close_positions=True,
        )
        raise RuntimeError("terminal activation audit unavailable")

    harness.guards.on_log = fail_after_user_close_latches

    with pytest.raises(HTTPException) as caught:
        _subscribe(harness)

    assert caught.value.status_code == 503
    operation = harness.halt_barrier.owner_halt_operation("follower-user")
    assert operation.halt_ref == "user-emergency-close"
    assert operation.action_name == "emergency_close_all"
    assert operation.close_positions is True
    follower = harness.service.get_follower(f"follower-user::{harness.master.master_id}")
    assert follower is not None and follower.status == "draining"
    assert harness.active.account_refs() == ("exchange_account_uid_test",)


def test_fully_mocked_mainnet_happy_path_commits_once_with_truthful_audit(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)

    response = _subscribe(harness)

    persisted = harness.service.get_follower(response["follower_id"])
    assert persisted is not None
    assert persisted.to_dict() == response
    assert response["status"] == "active"
    assert response["account_binding_ref"] == "exchange_account_uid_test"
    assert "secret" not in repr(response).lower()
    assert harness.active.account_refs() == ("exchange_account_uid_test",)
    assert [item["result"] for item in harness.guards.logs] == ["prepared", "ok"]
    assert harness.guards.logs[-1]["password_verified"] is True
    assert harness.guards.logs[-1]["totp_verified"] is False
    assert harness.broker.account_binding_calls == 1


def test_subscription_is_not_relay_visible_until_audit_completes(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    audit_entered = threading.Event()
    allow_audit = threading.Event()
    results: list[dict] = []
    errors: list[BaseException] = []

    def block_audit() -> None:
        audit_entered.set()
        if not allow_audit.wait(timeout=5):
            raise RuntimeError("test audit barrier timed out")

    harness.guards.on_log = block_audit

    def run_subscription() -> None:
        try:
            results.append(_subscribe(harness))
        except BaseException as exc:  # noqa: BLE001 - thread assertion handoff
            errors.append(exc)

    worker = threading.Thread(target=run_subscription)
    worker.start()
    assert audit_entered.wait(timeout=5)
    staged = harness.service.get_follower(f"follower-user::{harness.master.master_id}")
    assert staged is not None and staged.status == "activating"
    assert harness.service.list_followers(harness.master.master_id, active_only=True) == []

    allow_audit.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []
    assert results and results[0]["status"] == "active"


def test_cross_process_activating_unsubscribe_fence_survives_activation_compensation(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    audit_entered = threading.Event()
    allow_audit = threading.Event()
    errors: list[BaseException] = []

    def block_prepared_audit() -> None:
        audit_entered.set()
        if not allow_audit.wait(timeout=5):
            raise RuntimeError("test audit barrier timed out")

    harness.guards.on_log = block_prepared_audit

    def run_activation() -> None:
        try:
            _subscribe(harness)
        except BaseException as exc:  # noqa: BLE001 - thread assertion handoff.
            errors.append(exc)

    worker = threading.Thread(target=run_activation)
    worker.start()
    assert audit_entered.wait(timeout=5)
    follower_id = f"follower-user::{harness.master.master_id}"
    staged = harness.service.get_follower(follower_id)
    assert staged is not None and staged.status == "activating"

    # These two durable operations model another backend process.  They do not
    # share this process's subscription RLock.
    assert harness.service.begin_draining("follower-user", harness.master.master_id)
    halted = harness.halt_barrier.begin_account_halt(
        staged.account_binding_ref,
        staged.user_id,
        halt_ref="concurrent-activating-unsubscribe",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
        allow_missing=True,
    )
    assert halted.state == "halting"

    allow_audit.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], HTTPException)
    assert errors[0].status_code == 503
    retained = harness.service.get_follower(follower_id)
    assert retained is not None and retained.status == "draining"
    assert harness.active.account_refs() == ("exchange_account_uid_test",)
    assert harness.halt_barrier.snapshot(staged.account_binding_ref).state == "halting"


def test_restore_follower_state_cas_never_deletes_a_concurrent_draining_row(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    staged = harness.service.subscribe(
        user_id="follower-user",
        master_id=harness.master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref=harness.event.credential_binding_ref,
        runtime_promotion_ref=harness.promotion.runtime_promotion_ref,
        user_risk_choice_ref=harness.choice.choice_ref,
        user_risk_consent_event_ref=harness.event.consent_event_ref,
        initial_status="activating",
    )
    assert harness.service.begin_draining("follower-user", harness.master.master_id)

    restored = harness.service.restore_follower_state(
        "follower-user",
        harness.master.master_id,
        None,
        expected_account_binding_ref=staged.account_binding_ref,
        expected_binance_keystore_name=staged.binance_keystore_name,
        expected_credential_binding_ref=staged.credential_binding_ref,
        expected_runtime_promotion_ref=staged.runtime_promotion_ref,
        expected_user_risk_choice_ref=staged.user_risk_choice_ref,
        expected_user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
    )

    assert restored is False
    current = harness.service.get_follower(staged.follower_id)
    assert current is not None and current.status == "draining"


def test_activating_unsubscribe_stages_missing_halt_row_and_proves_flat_before_stop(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    staged = harness.service.subscribe(
        user_id="follower-user",
        master_id=harness.master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref=harness.event.credential_binding_ref,
        runtime_promotion_ref=harness.promotion.runtime_promotion_ref,
        user_risk_choice_ref=harness.choice.choice_ref,
        user_risk_consent_event_ref=harness.event.consent_event_ref,
        initial_status="activating",
    )
    monkeypatch.setattr(
        main,
        "FOLLOWER_RISK_STATE",
        SimpleNamespace(has_open_reservations=lambda *_args: False),
    )

    outcome = main.ct_unsubscribe(
        harness.master.master_id,
        SimpleNamespace(user_id="follower-user"),
    )

    assert outcome == {"unsubscribed": True, "draining": False}
    current = harness.service.get_follower(staged.follower_id)
    assert current is not None and current.status == "stopped"
    halted = harness.halt_barrier.snapshot(staged.account_binding_ref)
    assert halted is not None and halted.state == "halted"
    assert halted.flat_proof_ref
    assert harness.halt_barrier.flat_proof(halted.flat_proof_ref)["account_epochs"] == {
        staged.account_binding_ref: halted.epoch
    }


def test_startup_quarantines_committed_but_unaudited_activation_before_relay(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    staged = harness.service.subscribe(
        user_id="follower-user",
        master_id=harness.master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref=harness.event.credential_binding_ref,
        runtime_promotion_ref=harness.promotion.runtime_promotion_ref,
        user_risk_choice_ref=harness.choice.choice_ref,
        user_risk_consent_event_ref=harness.event.consent_event_ref,
        initial_status="activating",
    )
    activation_ref = "copy_trade_activation_crash_probe"
    harness.service.prepare_mainnet_activation(
        activation_ref=activation_ref,
        user_id=staged.user_id,
        master_id=staged.master_id,
        account_binding_ref=staged.account_binding_ref,
        credential_binding_ref=staged.credential_binding_ref,
        runtime_promotion_ref=staged.runtime_promotion_ref,
        user_risk_choice_ref=staged.user_risk_choice_ref,
        user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
        runtime_request_ref=harness.requirements.request_ref,
        risk_profile_ref=harness.profile["profile_ref"],
    )
    harness.halt_barrier.activate(staged.account_binding_ref, staged.user_id)
    harness.service.activate_subscription(
        staged.user_id,
        staged.master_id,
        activation_ref=activation_ref,
        account_binding_ref=staged.account_binding_ref,
        binance_keystore_name=staged.binance_keystore_name,
        credential_binding_ref=staged.credential_binding_ref,
        runtime_promotion_ref=staged.runtime_promotion_ref,
        user_risk_choice_ref=staged.user_risk_choice_ref,
        user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
        runtime_request_ref=harness.requirements.request_ref,
        risk_profile_ref=harness.profile["profile_ref"],
    )
    assert harness.service.unfinished_mainnet_activations()[0].status == "committed"
    monkeypatch.setattr(main, "KEYSTORE", SimpleNamespace(is_durable=True))
    monkeypatch.setattr(
        main,
        "TRADING_CREDENTIALS",
        SimpleNamespace(
            credential=lambda _ref: SimpleNamespace(
                status="active",
                owner_user_id="follower-user",
                credential_binding_ref="exchange_credential_test",
            )
        ),
    )

    main._bootstrap_active_emergency_venues()

    current = harness.service.get_follower(staged.follower_id)
    assert current is not None and current.status == "draining"
    halt = harness.halt_barrier.snapshot(staged.account_binding_ref)
    assert halt is not None and halt.state == "halting"
    assert halt.halt_action_name == "copy_trade_startup_quarantine"
    assert halt.halt_close_positions is False
    assert harness.service.unfinished_mainnet_activations() == ()
    assert harness.active.account_refs() == (staged.account_binding_ref,)
    assert any(
        issue["follower_id"] == staged.follower_id
        and "unaudited" in issue["reason"]
        for issue in main._COPY_TRADE_BOOTSTRAP_ISSUES
    ), main._COPY_TRADE_BOOTSTRAP_ISSUES


def test_live_capability_requires_the_followers_exact_audited_activation(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    staged = harness.service.subscribe(
        user_id="follower-user",
        master_id=harness.master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref=harness.event.credential_binding_ref,
        runtime_promotion_ref=harness.promotion.runtime_promotion_ref,
        user_risk_choice_ref=harness.choice.choice_ref,
        user_risk_consent_event_ref=harness.event.consent_event_ref,
        initial_status="activating",
    )
    activation_ref = "copy_trade_activation_exact_capability_probe"
    harness.service.prepare_mainnet_activation(
        activation_ref=activation_ref,
        user_id=staged.user_id,
        master_id=staged.master_id,
        account_binding_ref=staged.account_binding_ref,
        credential_binding_ref=staged.credential_binding_ref,
        runtime_promotion_ref=staged.runtime_promotion_ref,
        user_risk_choice_ref=staged.user_risk_choice_ref,
        user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
        runtime_request_ref=harness.requirements.request_ref,
        risk_profile_ref=harness.profile["profile_ref"],
    )
    committed = harness.service.activate_subscription(
        staged.user_id,
        staged.master_id,
        activation_ref=activation_ref,
        account_binding_ref=staged.account_binding_ref,
        binance_keystore_name=staged.binance_keystore_name,
        credential_binding_ref=staged.credential_binding_ref,
        runtime_promotion_ref=staged.runtime_promotion_ref,
        user_risk_choice_ref=staged.user_risk_choice_ref,
        user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
        runtime_request_ref=harness.requirements.request_ref,
        risk_profile_ref=harness.profile["profile_ref"],
    )
    assert committed.activation_ref == activation_ref
    reopened = CopyTradeService(tmp_path / "copy-trade.sqlite3")
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", reopened)
    live_capability = SimpleNamespace(
        owner_user_id=staged.user_id,
        account_identity_ref=staged.account_binding_ref,
        keystore_name=staged.binance_keystore_name,
        credential_binding_ref=staged.credential_binding_ref,
        action="request_live_order",
    )
    emergency_capability = SimpleNamespace(
        **{
            **vars(live_capability),
            "action": "emergency_reduce_risk",
        }
    )

    assert main._mainnet_capability_account_status(live_capability) is None
    assert main._mainnet_capability_account_status(emergency_capability) == "active"

    wrong_audit_ref = harness.guards.log_operation(
        staged.user_id,
        "copy_trade_subscription",
        operation_ref="different-activation",
        result="ok",
    )
    with pytest.raises(CopyTradeError, match="does not authorize"):
        reopened.mark_mainnet_activation_audited(
            activation_ref,
            activation_audit_ref=wrong_audit_ref,
        )
    activation_audit_ref = harness.guards.log_operation(
        staged.user_id,
        "copy_trade_subscription",
        operation_ref=activation_ref,
        result="ok",
    )
    reopened.mark_mainnet_activation_audited(
        activation_ref,
        activation_audit_ref=activation_audit_ref,
    )
    assert main._mainnet_capability_account_status(live_capability) == "active"
    conn = sqlite3.connect(tmp_path / "copy-trade.sqlite3")
    try:
        conn.execute(
            "UPDATE mainnet_audit_log SET integrity_seal='tampered' WHERE audit_ref=?",
            (activation_audit_ref,),
        )
        conn.commit()
    finally:
        conn.close()
    assert main._mainnet_capability_account_status(live_capability) is None


def test_consent_event_is_permanently_claimed_even_after_failed_activation(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    staged = harness.service.subscribe(
        user_id="follower-user",
        master_id=harness.master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref=harness.event.credential_binding_ref,
        runtime_promotion_ref=harness.promotion.runtime_promotion_ref,
        user_risk_choice_ref=harness.choice.choice_ref,
        user_risk_consent_event_ref=harness.event.consent_event_ref,
        initial_status="activating",
    )
    common = {
        "user_id": staged.user_id,
        "master_id": staged.master_id,
        "account_binding_ref": staged.account_binding_ref,
        "credential_binding_ref": staged.credential_binding_ref,
        "runtime_promotion_ref": staged.runtime_promotion_ref,
        "user_risk_choice_ref": staged.user_risk_choice_ref,
        "user_risk_consent_event_ref": staged.user_risk_consent_event_ref,
        "runtime_request_ref": harness.requirements.request_ref,
        "risk_profile_ref": harness.profile["profile_ref"],
    }
    harness.service.prepare_mainnet_activation(
        activation_ref="activation-first-claim",
        **common,
    )
    harness.service.mark_mainnet_activation_failed("activation-first-claim")

    with pytest.raises(CopyTradeError, match="permanently claimed"):
        harness.service.prepare_mainnet_activation(
            activation_ref="activation-replay-claim",
            **common,
        )


def test_activation_transaction_rolls_back_follower_ref_when_journal_commit_fails(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    staged = harness.service.subscribe(
        user_id="follower-user",
        master_id=harness.master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="mainnet-key",
        binance_network="mainnet",
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
        account_binding_ref="exchange_account_uid_test",
        credential_binding_ref=harness.event.credential_binding_ref,
        runtime_promotion_ref=harness.promotion.runtime_promotion_ref,
        user_risk_choice_ref=harness.choice.choice_ref,
        user_risk_consent_event_ref=harness.event.consent_event_ref,
        initial_status="activating",
    )
    activation_ref = "activation-rollback-probe"
    harness.service.prepare_mainnet_activation(
        activation_ref=activation_ref,
        user_id=staged.user_id,
        master_id=staged.master_id,
        account_binding_ref=staged.account_binding_ref,
        credential_binding_ref=staged.credential_binding_ref,
        runtime_promotion_ref=staged.runtime_promotion_ref,
        user_risk_choice_ref=staged.user_risk_choice_ref,
        user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
        runtime_request_ref=harness.requirements.request_ref,
        risk_profile_ref=harness.profile["profile_ref"],
    )
    conn = sqlite3.connect(tmp_path / "copy-trade.sqlite3")
    try:
        conn.execute(
            """
            CREATE TRIGGER fail_activation_commit
            BEFORE UPDATE OF status ON ct_mainnet_activation_operations
            WHEN NEW.status='committed'
            BEGIN
                SELECT RAISE(ABORT, 'injected journal commit failure');
            END
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="injected journal commit failure"):
        harness.service.activate_subscription(
            staged.user_id,
            staged.master_id,
            activation_ref=activation_ref,
            account_binding_ref=staged.account_binding_ref,
            binance_keystore_name=staged.binance_keystore_name,
            credential_binding_ref=staged.credential_binding_ref,
            runtime_promotion_ref=staged.runtime_promotion_ref,
            user_risk_choice_ref=staged.user_risk_choice_ref,
            user_risk_consent_event_ref=staged.user_risk_consent_event_ref,
            runtime_request_ref=harness.requirements.request_ref,
            risk_profile_ref=harness.profile["profile_ref"],
        )
    current = harness.service.get_follower(staged.follower_id)
    assert current is not None and current.status == "activating"
    assert current.activation_ref == ""
    assert harness.service.unfinished_mainnet_activations()[0].status == "prepared"


def test_legacy_runtime_requirements_no_longer_creates_live_authority(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as caught:
        main.ct_runtime_requirements(
            harness.master.master_id,
            _request(),
            {},
            SimpleNamespace(user_id="follower-user"),
        )

    assert caught.value.status_code == 410


def test_consent_challenge_uses_venue_uid_and_returns_complete_readable_profile(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    challenge_response = main.ct_issue_risk_consent_challenge(
        harness.master.master_id,
        _request(),
        _payload(""),
        SimpleNamespace(user_id="follower-user"),
    )
    profile = challenge_response["risk_profile"]
    assert challenge_response["account_binding_ref"] == "exchange_account_uid_test"
    assert profile["failure_modes"]
    assert profile["recommendation"]["text"]
    assert profile["responsibility_boundary"]["parties"]

    consent_response = main.ct_record_risk_consent(
        harness.master.master_id,
        _request(),
        {
            "challenge_ref": challenge_response["challenge_ref"],
            "acknowledged_item_refs": profile["required_acknowledgement_refs"],
            "password": "server-verified-by-test-double",
        },
        SimpleNamespace(user_id="follower-user"),
    )

    assert consent_response["account_binding_ref"] == "exchange_account_uid_test"
    assert consent_response["runtime_promotion"]["approval_binding"][
        "user_risk_consent_event_ref"
    ] == consent_response["consent_event_ref"]
    assert consent_response["runtime_promotion"]["approval_binding"][
        "runtime_request_ref"
    ] == challenge_response["runtime_request_ref"]
    assert "exchange_credential_test" not in repr(consent_response)
    assert harness.broker.account_binding_calls >= 2

    projection = main.ct_get_risk_consent(
        consent_response["consent_event_ref"],
        SimpleNamespace(user_id="follower-user"),
    )
    assert projection["risk_profile"] == profile


def test_unsubscribe_with_unresolved_risk_enters_draining_and_keeps_emergency_handle(
    monkeypatch,
    tmp_path,
) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    response = _subscribe(harness)
    monkeypatch.setattr(
        main,
        "FOLLOWER_RISK_STATE",
        SimpleNamespace(has_open_reservations=lambda *_args: True),
    )

    outcome = main.ct_unsubscribe(
        harness.master.master_id,
        SimpleNamespace(user_id="follower-user"),
    )

    assert outcome == {"unsubscribed": False, "draining": True}
    follower = harness.service.get_follower(response["follower_id"])
    assert follower is not None and follower.status == "draining"
    assert harness.active.account_refs() == ("exchange_account_uid_test",)
    assert harness.halt_barrier.snapshot("exchange_account_uid_test").state == "halting"


def test_unsubscribe_finalizes_only_after_zero_risk_positions_and_orders(monkeypatch, tmp_path) -> None:
    harness = _install_harness(monkeypatch, tmp_path)
    response = _subscribe(harness)
    monkeypatch.setattr(
        main,
        "FOLLOWER_RISK_STATE",
        SimpleNamespace(has_open_reservations=lambda *_args: False),
    )

    outcome = main.ct_unsubscribe(
        harness.master.master_id,
        SimpleNamespace(user_id="follower-user"),
    )

    assert outcome == {"unsubscribed": True, "draining": False}
    follower = harness.service.get_follower(response["follower_id"])
    assert follower is not None and follower.status == "stopped"
    assert harness.active.account_refs() == ()
    assert harness.halt_barrier.snapshot("exchange_account_uid_test").state == "halted"


def test_execution_api_requires_auth_bounds_limit_and_returns_incomplete_projection(monkeypatch) -> None:
    calls: list[tuple[str, str | None, str | None, int]] = []
    execution = Execution(
        exec_id="exec-owned",
        signal_id="signal-owned",
        follower_id="alice::master-owned",
        status="failed",
        venue_order_id="secret-venue-order",
        filled_qty=12.0,
        fill_price=99.0,
        commission=3.0,
        error="raw private exchange error",
        created_at_utc="2026-01-01T00:00:00+00:00",
    )

    def list_for_user(user_id, *, signal_id=None, follower_id=None, limit=200):
        calls.append((user_id, signal_id, follower_id, limit))
        return [execution]

    monkeypatch.setattr(
        main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(list_executions_for_user=list_for_user),
    )
    main.app.dependency_overrides.pop(require_user_dependency, None)
    client = TestClient(main.app)
    assert client.get("/api/copy_trade/executions").status_code in {401, 403}
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="alice")
    try:
        assert client.get("/api/copy_trade/executions?limit=-1").status_code == 422
        assert client.get("/api/copy_trade/executions?limit=201").status_code == 422
        response = client.get(
            "/api/copy_trade/executions?signal_id=signal-owned&follower_id=alice%3A%3Amaster-owned&limit=10"
        )
        assert response.status_code == 200
        assert calls == [("alice", "signal-owned", "alice::master-owned", 10)]
        body = response.json()
        assert body == [
            {
                "execution_ref": "exec-owned",
                "signal_ref": "signal-owned",
                "follower_ref": "alice::master-owned",
                "dispatch_status": "failed",
                "state_source": "legacy_dispatch_journal",
                "economics_complete": False,
                "created_at_utc": "2026-01-01T00:00:00+00:00",
                "finished_at_utc": None,
            }
        ]
        assert "secret-venue-order" not in response.text
        assert "raw private exchange error" not in response.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_fill_economics_api_uses_owned_followers_and_exposes_no_raw_payload(monkeypatch) -> None:
    calls: list[tuple[tuple[str, ...], str | None, str | None, int]] = []
    follower = SimpleNamespace(follower_id="alice::master-owned", master_id="master-owned")
    record = FollowerFillEconomics(
        event_ref="fill-event-1",
        reservation_ref="reservation-1",
        submission_ref="submission-1",
        venue_event_ref="venue-event-1",
        reconciliation_ref="reconciliation-1",
        source_event_ref="source-trade-1",
        raw_event_hash="sha256:" + "a" * 64,
        signal_ref="signal-owned",
        follower_ref=follower.follower_id,
        account_binding_ref="exchange-account-owned",
        symbol="BTCUSDT",
        side="buy",
        venue_order_ref="venue-order-1",
        client_order_ref="client-order-1",
        fill_status="filled",
        filled_qty=0.01,
        cumulative_filled_qty=0.01,
        fill_price=10_000.0,
        fill_price_source="venue_fill",
        filled_notional_usdt=100.0,
        commission=0.04,
        commission_asset="USDT",
        normalized_cost_usdt=0.04,
        cost_conversion_ref="cost-usdt",
        cost_complete=True,
        realized_pnl_delta=-1.25,
        realized_pnl_complete=True,
        fill_economics_complete=True,
        occurred_at_utc="2026-07-12T00:00:00+00:00",
    )

    class RiskStore:
        def fill_economics_for_followers(
            self, follower_ids, *, signal_id=None, follower_id=None, limit=200
        ):
            calls.append((tuple(follower_ids), signal_id, follower_id, limit))
            return (record,)

    service = SimpleNamespace(
        list_subscriptions=lambda user_id: [follower] if user_id == "alice" else [],
        get_master=lambda master_id: SimpleNamespace(asset_class="crypto_perp")
        if master_id == "master-owned"
        else None,
    )
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", service)
    monkeypatch.setattr(main, "FOLLOWER_RISK_STATE", RiskStore())
    main.app.dependency_overrides.pop(require_user_dependency, None)
    client = TestClient(main.app)
    assert client.get("/api/copy_trade/fills").status_code in {401, 403}
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="alice")
    try:
        response = client.get(
            "/api/copy_trade/fills?signal_id=signal-owned&follower_id=alice%3A%3Amaster-owned&limit=1"
        )
        assert response.status_code == 200
        assert calls == [
            (("alice::master-owned",), "signal-owned", "alice::master-owned", 1)
        ]
        body = response.json()
        assert body[0]["fill_price"] == 10_000.0
        assert body[0]["realized_pnl_delta"] == -1.25
        assert body[0]["fill_economics_complete"] is True
        assert body[0]["holding_cost_complete"] is False
        assert body[0]["total_economics_complete"] is False
        assert body[0]["state_source"] == "hmac_copy_trade_risk_ledger"
        assert "raw" not in body[0]
        assert "raw_payload" not in body[0]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
