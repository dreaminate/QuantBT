from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import require_user_dependency


class _Guards:
    def __init__(self) -> None:
        self.audit_calls: list[dict] = []
        self.allow_ip = True
        self.corrupt_audit = False

    def check_ip(self, user_id: str, source_ip: str) -> bool:
        return self.allow_ip and user_id == "owner" and source_ip == "testclient"

    def verify_totp(self, user_id: str, code: str) -> bool:
        return False

    def log_operation(self, user_id: str, operation: str, **values) -> str:  # noqa: ANN003
        audit_ref = f"mainnet_audit_v1_{len(self.audit_calls) + 1}"
        self.audit_calls.append(
            {"audit_ref": audit_ref, "user_id": user_id, "operation": operation, **values}
        )
        return audit_ref

    def audit_record(self, audit_ref: str):  # noqa: ANN201
        authorized = next(
            call for call in self.audit_calls if call["audit_ref"] == audit_ref
        )
        return SimpleNamespace(
            audit_ref=audit_ref,
            user_id=authorized["user_id"],
            operation=authorized["operation"],
            operation_ref=(
                "corrupt-operation-ref"
                if self.corrupt_audit
                else authorized["operation_ref"]
            ),
            source_ip=authorized["source_ip"],
            result=authorized["result"],
            password_verified=authorized["password_verified"],
            totp_verified=authorized["totp_verified"],
        )


class _Auth:
    def __init__(self, accepted_password: str = "secret") -> None:
        self.accepted_password = accepted_password

    def verify_password(self, user_id: str, password: str) -> bool:
        return user_id == "owner" and password == self.accepted_password


class _Journal:
    def __init__(self) -> None:
        self.owner_user_id = "owner"

    def action(self, action_ref: str):  # noqa: ANN201
        if action_ref != "action-1":
            raise LookupError(action_ref)
        return SimpleNamespace(
            action_ref="action-1",
            owner_user_id=self.owner_user_id,
            account_ref="account-1",
            account_epoch=7,
            last_event_ref="event-head",
            symbol="BTCUSDT",
            side="sell",
        )


class _Barrier:
    def __init__(self) -> None:
        self.state = "halting"
        self.epoch = 7
        self.halt_ref = "halt-current"

    def validate_account(self, account_ref: str, owner_user_id: str):  # noqa: ANN201
        assert (account_ref, owner_user_id) == ("account-1", "owner")
        return SimpleNamespace(
            state=self.state,
            epoch=self.epoch,
            halt_ref=self.halt_ref,
        )

    def owner_epoch(self, owner_user_id: str) -> int:
        assert owner_user_id == "owner"
        return 11


class _Handle:
    name = "leased_binance:account-1:mainnet:usdm_futures"

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.persisted_resolution: dict | None = None

    def resolve_unknown_submission_for_halt(
        self,
        action_ref,
        context,
        *,
        operator_auth_audit_ref,
    ):  # noqa: ANN001, ANN201
        self.calls.append((action_ref, context, operator_auth_audit_ref))
        if self.persisted_resolution is None:
            self.persisted_resolution = {
                "historical_submission_outcome": "unknown",
                "historical_fill_state": "unknown",
                "automatic_retry_permitted": False,
                "operator_auth_audit_ref": operator_auth_audit_ref,
            }
        return {
            "action": {"action_ref": action_ref, "status": "manual_unknown_flat"},
            "resolution": dict(self.persisted_resolution),
            "resolved_via": (
                "manual_unknown_flat"
                if len(self.calls) == 1
                else "persisted_manual_unknown_flat"
            ),
        }


class _Registry:
    def __init__(self, handle: _Handle) -> None:
        self.handle = handle

    def venue_for_user(self, owner_user_id: str, account_ref: str) -> _Handle:
        assert (owner_user_id, account_ref) == ("owner", "account-1")
        return self.handle


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    guards = _Guards()
    handle = _Handle()
    journal = _Journal()
    barrier = _Barrier()
    monkeypatch.setattr(main, "MAINNET_GUARDS", guards)
    monkeypatch.setattr(main, "AUTH_SERVICE", _Auth())
    monkeypatch.setattr(main, "EMERGENCY_ACTION_JOURNAL", journal)
    monkeypatch.setattr(main, "ACCOUNT_HALT_BARRIER", barrier)
    monkeypatch.setattr(main, "ACTIVE_EMERGENCY_VENUES", _Registry(handle))
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="owner",
        username="owner",
    )
    try:
        yield TestClient(main.app), guards, handle, journal, barrier
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_resolution_endpoint_persists_and_rechecks_operator_authorization(api) -> None:
    client, guards, handle, _journal, _barrier = api

    response = client.post(
        "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission",
        json={"password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["automatic_retry_permitted"] is False
    assert response.json()["action"]["status"] == "manual_unknown_flat"
    assert handle.calls[0][0] == "action-1"
    assert handle.calls[0][1].owner_epoch == 11
    assert handle.calls[0][1].account_epoch == 7
    assert handle.calls[0][2] == "mainnet_audit_v1_1"
    assert [call["result"] for call in guards.audit_calls] == ["authorized", "ok"]


def test_resolution_endpoint_rejects_unverified_second_factor_without_venue_call(
    api,
) -> None:
    client, _guards, handle, _journal, _barrier = api

    response = client.post(
        "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission",
        json={"password": "wrong"},
    )

    assert response.status_code == 403
    assert handle.calls == []


def test_resolution_endpoint_rejects_untrusted_ip_before_audit_or_venue(api) -> None:
    client, guards, handle, _journal, _barrier = api
    guards.allow_ip = False

    response = client.post(
        "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission",
        json={"password": "secret"},
    )

    assert response.status_code == 403
    assert guards.audit_calls == []
    assert handle.calls == []


def test_resolution_endpoint_hides_foreign_action_before_audit_or_venue(api) -> None:
    client, guards, handle, journal, _barrier = api
    journal.owner_user_id = "different-owner"

    response = client.post(
        "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission",
        json={"password": "secret"},
    )

    assert response.status_code == 404
    assert guards.audit_calls == []
    assert handle.calls == []


def test_resolution_endpoint_rejects_stale_halt_scope_before_audit_or_venue(api) -> None:
    client, guards, handle, _journal, barrier = api
    barrier.epoch = 8

    response = client.post(
        "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission",
        json={"password": "secret"},
    )

    assert response.status_code == 409
    assert guards.audit_calls == []
    assert handle.calls == []


def test_resolution_endpoint_rejects_corrupt_authorization_audit_before_venue(api) -> None:
    client, guards, handle, _journal, _barrier = api
    guards.corrupt_audit = True

    response = client.post(
        "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission",
        json={"password": "secret"},
    )

    assert response.status_code == 409
    assert [call["result"] for call in guards.audit_calls] == ["authorized"]
    assert handle.calls == []


def test_resolution_endpoint_repeat_preserves_original_resolution_evidence(api) -> None:
    client, guards, handle, _journal, _barrier = api
    url = "/api/security/mainnet/emergency-actions/action-1/resolve-unknown-submission"

    first = client.post(url, json={"password": "secret"})
    second = client.post(url, json={"password": "secret"})

    assert first.status_code == second.status_code == 200
    assert first.json()["resolution"] == second.json()["resolution"]
    assert second.json()["resolved_via"] == "persisted_manual_unknown_flat"
    assert first.json()["resolution"]["operator_auth_audit_ref"] == "mainnet_audit_v1_1"
    assert second.json()["operator_auth_audit_ref"] == "mainnet_audit_v1_3"
    assert [call["result"] for call in guards.audit_calls] == [
        "authorized",
        "ok",
        "authorized",
        "ok",
    ]
    assert len(handle.calls) == 2
