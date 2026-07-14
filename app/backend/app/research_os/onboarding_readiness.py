"""Durable, re-resolvable GOAL section 4 onboarding readiness receipts.

The registry accepts only the four identities that select a readiness chain.
All evidence is read through an injected resolver and is checked again whenever
the receipt is used.  A persisted receipt is therefore a snapshot, not a
permanent assertion: secret rotation, revocation, health, mapping, routing, or
terminal-call drift makes the old receipt red.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.cross_process_lock import acquire_exclusive_fd

from .goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    strict_current_entrypoint_coverage,
)
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)


READINESS_SCHEMA_VERSION = 2
READINESS_RECEIPT_VERSION = "onboarding_readiness_receipt.v1"
ONBOARDING_READINESS_ENTRYPOINT_REF = "api:goal.onboarding.readiness"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _links(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    items = value.items() if isinstance(value, Mapping) else value
    return tuple(sorted((_text(key), _text(child)) for key, child in items))


@dataclass(frozen=True)
class OnboardingReadinessViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class OnboardingReadinessDecision:
    accepted: bool
    violations: tuple[OnboardingReadinessViolation, ...]


class OnboardingReadinessError(ValueError):
    """The resolved chain cannot produce a green readiness receipt."""


@dataclass(frozen=True)
class ReadinessComponentState:
    """Identity and exact current-state fingerprint for one resolved record."""

    component_ref: str
    principal_id: str
    revision: str
    state_hash: str
    status: str
    links: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in ("component_ref", "principal_id", "revision", "state_hash", "status"):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "status", self.status.lower())
        object.__setattr__(self, "links", _links(self.links))

    @property
    def link_map(self) -> dict[str, str]:
        return dict(self.links)


@dataclass(frozen=True)
class OnboardingReadinessSnapshot:
    """Fully resolved data-onboarding and terminal LLM-consumption chain."""

    owner_user_id: str
    credential_mode: str
    data_source: ReadinessComponentState
    secret_or_no_secret_policy: ReadinessComponentState
    connection_check: ReadinessComponentState
    schema_probe: ReadinessComponentState
    field_mapping: ReadinessComponentState
    pit_rule: ReadinessComponentState
    ingestion_skill: ReadinessComponentState
    ingestion_update: ReadinessComponentState
    dataset_version: ReadinessComponentState
    dataset_semantics: ReadinessComponentState
    dataset_use_validation: ReadinessComponentState
    llm_provider: ReadinessComponentState
    service_principal_auth: ReadinessComponentState
    provider_health: ReadinessComponentState
    credential_pool: ReadinessComponentState
    routing_policy: ReadinessComponentState
    user_service_binding: ReadinessComponentState
    terminal_llm_call: ReadinessComponentState
    residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", _text(self.owner_user_id))
        object.__setattr__(self, "credential_mode", _text(self.credential_mode).lower())
        object.__setattr__(
            self,
            "residuals",
            tuple(_text(item) for item in self.residuals if _text(item)),
        )


@dataclass(frozen=True)
class OnboardingReadinessReceipt:
    receipt_ref: str
    owner_user_id: str
    data_source_ref: str
    llm_routing_policy_ref: str
    terminal_llm_call_ref: str
    snapshot: OnboardingReadinessSnapshot
    receipt_version: str = READINESS_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for name in (
            "receipt_ref",
            "owner_user_id",
            "data_source_ref",
            "llm_routing_policy_ref",
            "terminal_llm_call_ref",
            "receipt_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))

    @property
    def canonical_receipt_ref(self) -> str:
        return onboarding_readiness_receipt_identity(
            owner_user_id=self.owner_user_id,
            data_source_ref=self.data_source_ref,
            llm_routing_policy_ref=self.llm_routing_policy_ref,
            terminal_llm_call_ref=self.terminal_llm_call_ref,
            snapshot=self.snapshot,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class OnboardingReadinessSemanticMaterial:
    """Canonical §4 proof material derived only from a persisted receipt."""

    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]


ReadinessResolver = Callable[
    [str, str, str, str],
    OnboardingReadinessSnapshot,
]


def _component_from_dict(value: Any) -> ReadinessComponentState:
    if not isinstance(value, dict):
        raise ValueError("onboarding readiness component must be an object")
    if set(value) != {
        "component_ref",
        "principal_id",
        "revision",
        "state_hash",
        "status",
        "links",
    }:
        raise ValueError("onboarding readiness component has an inexact field set")
    return ReadinessComponentState(
        component_ref=value["component_ref"],
        principal_id=value["principal_id"],
        revision=value["revision"],
        state_hash=value["state_hash"],
        status=value["status"],
        links=value["links"],
    )


_SNAPSHOT_COMPONENT_FIELDS = (
    "data_source",
    "secret_or_no_secret_policy",
    "connection_check",
    "schema_probe",
    "field_mapping",
    "pit_rule",
    "ingestion_skill",
    "ingestion_update",
    "dataset_version",
    "dataset_semantics",
    "dataset_use_validation",
    "llm_provider",
    "service_principal_auth",
    "provider_health",
    "credential_pool",
    "routing_policy",
    "user_service_binding",
    "terminal_llm_call",
)
READINESS_COMPONENT_FIELDS = _SNAPSHOT_COMPONENT_FIELDS


def onboarding_readiness_snapshot_from_dict(value: Any) -> OnboardingReadinessSnapshot:
    if not isinstance(value, dict):
        raise ValueError("onboarding readiness snapshot must be an object")
    expected = {"owner_user_id", "credential_mode", "residuals", *_SNAPSHOT_COMPONENT_FIELDS}
    if set(value) != expected:
        raise ValueError("onboarding readiness snapshot has an inexact field set")
    return OnboardingReadinessSnapshot(
        owner_user_id=value["owner_user_id"],
        credential_mode=value["credential_mode"],
        residuals=tuple(value["residuals"]),
        **{name: _component_from_dict(value[name]) for name in _SNAPSHOT_COMPONENT_FIELDS},
    )


def onboarding_readiness_receipt_from_dict(value: Any) -> OnboardingReadinessReceipt:
    if not isinstance(value, dict):
        raise ValueError("onboarding readiness receipt must be an object")
    expected = {
        "receipt_ref",
        "owner_user_id",
        "data_source_ref",
        "llm_routing_policy_ref",
        "terminal_llm_call_ref",
        "snapshot",
        "receipt_version",
    }
    if set(value) != expected:
        raise ValueError("onboarding readiness receipt has an inexact field set")
    return OnboardingReadinessReceipt(
        receipt_ref=value["receipt_ref"],
        owner_user_id=value["owner_user_id"],
        data_source_ref=value["data_source_ref"],
        llm_routing_policy_ref=value["llm_routing_policy_ref"],
        terminal_llm_call_ref=value["terminal_llm_call_ref"],
        snapshot=onboarding_readiness_snapshot_from_dict(value["snapshot"]),
        receipt_version=value["receipt_version"],
    )


def onboarding_readiness_receipt_identity(
    *,
    owner_user_id: str,
    data_source_ref: str,
    llm_routing_policy_ref: str,
    terminal_llm_call_ref: str,
    snapshot: OnboardingReadinessSnapshot,
    receipt_version: str = READINESS_RECEIPT_VERSION,
) -> str:
    return "onboarding_readiness_receipt:" + _sha256(
        {
            "owner_user_id": _text(owner_user_id),
            "data_source_ref": _text(data_source_ref),
            "llm_routing_policy_ref": _text(llm_routing_policy_ref),
            "terminal_llm_call_ref": _text(terminal_llm_call_ref),
            "snapshot": asdict(snapshot),
            "receipt_version": _text(receipt_version),
        }
    )


_REQUIRED_LINK_KEYS: dict[str, frozenset[str]] = {
    "data_source": frozenset(),
    "secret_or_no_secret_policy": frozenset({"source_ref"}),
    "connection_check": frozenset({"source_ref", "auth_policy_ref", "ingestion_skill_ref"}),
    "schema_probe": frozenset({"source_ref", "connection_check_ref", "ingestion_skill_ref"}),
    "field_mapping": frozenset({"source_ref", "schema_probe_ref", "ingestion_skill_ref"}),
    "pit_rule": frozenset(
        {"source_ref", "schema_probe_ref", "field_mapping_ref", "ingestion_skill_ref"}
    ),
    "ingestion_skill": frozenset(
        {"source_ref", "auth_policy_ref", "field_mapping_ref", "pit_rule_ref", "output_dataset_id"}
    ),
    "ingestion_update": frozenset({"source_ref", "ingestion_skill_ref", "dataset_version_ref"}),
    "dataset_version": frozenset({"dataset_id", "source_ref", "ingestion_skill_ref"}),
    "dataset_semantics": frozenset(
        {"source_ref", "ingestion_skill_ref", "ingestion_update_ref", "dataset_version_ref"}
    ),
    "dataset_use_validation": frozenset(
        {"source_ref", "dataset_semantics_ref", "dataset_version_ref"}
    ),
    "llm_provider": frozenset({"service_principal_ref"}),
    "service_principal_auth": frozenset({"provider_ref", "service_principal_ref"}),
    "provider_health": frozenset(
        {"provider_ref", "auth_ref", "service_principal_ref", "freshness_status"}
    ),
    "credential_pool": frozenset({"provider_ref", "auth_ref", "service_principal_ref"}),
    "routing_policy": frozenset(
        {"provider_ref", "auth_ref", "credential_pool_ref", "service_principal_ref"}
    ),
    "user_service_binding": frozenset(
        {
            "owner_user_id",
            "provider_ref",
            "auth_ref",
            "credential_pool_ref",
            "routing_policy_ref",
            "service_principal_ref",
        }
    ),
    "terminal_llm_call": frozenset(
        {
            "owner_user_id",
            "provider_ref",
            "auth_ref",
            "credential_pool_ref",
            "routing_policy_ref",
            "service_principal_ref",
            "user_service_binding_ref",
            "record_kind",
        }
    ),
}


_ACCEPTED_STATUSES: dict[str, frozenset[str]] = {
    "data_source": frozenset({"active"}),
    "secret_or_no_secret_policy": frozenset({"active", "approved"}),
    "connection_check": frozenset({"ok"}),
    "schema_probe": frozenset({"ok", "unchanged"}),
    "field_mapping": frozenset({"validated"}),
    "pit_rule": frozenset({"validated"}),
    "ingestion_skill": frozenset({"active"}),
    "ingestion_update": frozenset({"succeeded"}),
    "dataset_version": frozenset({"registered"}),
    "dataset_semantics": frozenset({"validated"}),
    "dataset_use_validation": frozenset({"passed"}),
    "llm_provider": frozenset({"active"}),
    "service_principal_auth": frozenset({"active"}),
    "provider_health": frozenset({"healthy"}),
    "credential_pool": frozenset({"active"}),
    "routing_policy": frozenset({"active"}),
    "user_service_binding": frozenset({"active"}),
    "terminal_llm_call": frozenset({"ok"}),
}


_DATA_COMPONENT_FIELDS = _SNAPSHOT_COMPONENT_FIELDS[:11]


def _valid_state_hash(value: str) -> bool:
    token = _text(value).lower()
    if token.startswith("sha256:"):
        token = token[7:]
    return len(token) == 64 and all(char in "0123456789abcdef" for char in token)


def _violation(
    violations: list[OnboardingReadinessViolation],
    code: str,
    message: str,
    *,
    field: str = "",
    ref: str = "",
) -> None:
    violations.append(OnboardingReadinessViolation(code, message, field=field, ref=ref))


def validate_onboarding_readiness_snapshot(
    snapshot: OnboardingReadinessSnapshot,
    *,
    owner_user_id: str,
    data_source_ref: str,
    llm_routing_policy_ref: str,
    terminal_llm_call_ref: str,
) -> OnboardingReadinessDecision:
    """Validate exact identity, ownership, linkage, health, and zero residuals."""

    violations: list[OnboardingReadinessViolation] = []
    owner = _text(owner_user_id)
    expected_refs = {
        "data_source": _text(data_source_ref),
        "routing_policy": _text(llm_routing_policy_ref),
        "terminal_llm_call": _text(terminal_llm_call_ref),
    }
    if not all((owner, *expected_refs.values())):
        _violation(
            violations,
            "onboarding_readiness_identity_missing",
            "owner, data source, routing policy, and terminal call identities are required",
        )
    if snapshot.owner_user_id != owner:
        _violation(
            violations,
            "onboarding_readiness_owner_mismatch",
            "resolved snapshot owner must exactly match the requested owner",
            field="owner_user_id",
            ref=snapshot.owner_user_id,
        )
    if snapshot.residuals:
        _violation(
            violations,
            "onboarding_readiness_residuals_present",
            "readiness cannot pass with unresolved residuals",
            field="residuals",
            ref=",".join(snapshot.residuals),
        )

    components = {name: getattr(snapshot, name) for name in _SNAPSHOT_COMPONENT_FIELDS}
    for name, component in components.items():
        if not all(
            (
                component.component_ref,
                component.principal_id,
                component.revision,
                component.state_hash,
                component.status,
            )
        ):
            _violation(
                violations,
                "onboarding_readiness_component_incomplete",
                "every readiness component requires identity, principal, revision, hash, and status",
                field=name,
                ref=component.component_ref,
            )
        if not _valid_state_hash(component.state_hash):
            _violation(
                violations,
                "onboarding_readiness_state_hash_invalid",
                "component state_hash must be a full sha256 digest",
                field=name,
                ref=component.component_ref,
            )
        link_keys = [key for key, _value in component.links]
        if len(link_keys) != len(set(link_keys)) or frozenset(link_keys) != _REQUIRED_LINK_KEYS[name]:
            _violation(
                violations,
                "onboarding_readiness_link_fields_inexact",
                "component linkage fields must exactly match the readiness contract",
                field=name,
                ref=component.component_ref,
            )
        if component.status not in _ACCEPTED_STATUSES[name]:
            _violation(
                violations,
                "onboarding_readiness_status_not_accepted",
                "component is not in a readiness-accepted current state",
                field=name,
                ref=component.component_ref,
            )
    for name, expected in expected_refs.items():
        if components[name].component_ref != expected:
            _violation(
                violations,
                "onboarding_readiness_requested_ref_mismatch",
                "resolver output must exactly match each requested identity",
                field=name,
                ref=components[name].component_ref,
            )

    for name in _DATA_COMPONENT_FIELDS:
        component = components[name]
        if component.principal_id != owner:
            _violation(
                violations,
                "onboarding_readiness_data_owner_mismatch",
                "every data onboarding record must belong to the requesting owner",
                field=name,
                ref=component.component_ref,
            )

    source_ref = components["data_source"].component_ref
    auth_policy_ref = components["secret_or_no_secret_policy"].component_ref
    connection_ref = components["connection_check"].component_ref
    schema_ref = components["schema_probe"].component_ref
    mapping_ref = components["field_mapping"].component_ref
    pit_ref = components["pit_rule"].component_ref
    skill_ref = components["ingestion_skill"].component_ref
    update_ref = components["ingestion_update"].component_ref
    version_ref = components["dataset_version"].component_ref
    semantics_ref = components["dataset_semantics"].component_ref

    expected_data_links: dict[str, dict[str, str]] = {
        "secret_or_no_secret_policy": {"source_ref": source_ref},
        "connection_check": {
            "source_ref": source_ref,
            "auth_policy_ref": auth_policy_ref,
            "ingestion_skill_ref": skill_ref,
        },
        "schema_probe": {
            "source_ref": source_ref,
            "connection_check_ref": connection_ref,
            "ingestion_skill_ref": skill_ref,
        },
        "field_mapping": {
            "source_ref": source_ref,
            "schema_probe_ref": schema_ref,
            "ingestion_skill_ref": skill_ref,
        },
        "pit_rule": {
            "source_ref": source_ref,
            "schema_probe_ref": schema_ref,
            "field_mapping_ref": mapping_ref,
            "ingestion_skill_ref": skill_ref,
        },
        "ingestion_skill": {
            "source_ref": source_ref,
            "auth_policy_ref": auth_policy_ref,
            "field_mapping_ref": mapping_ref,
            "pit_rule_ref": pit_ref,
            "output_dataset_id": components["dataset_version"].link_map.get("dataset_id", ""),
        },
        "ingestion_update": {
            "source_ref": source_ref,
            "ingestion_skill_ref": skill_ref,
            "dataset_version_ref": version_ref,
        },
        "dataset_version": {
            "dataset_id": components["ingestion_skill"].link_map.get("output_dataset_id", ""),
            "source_ref": source_ref,
            "ingestion_skill_ref": skill_ref,
        },
        "dataset_semantics": {
            "source_ref": source_ref,
            "ingestion_skill_ref": skill_ref,
            "ingestion_update_ref": update_ref,
            "dataset_version_ref": version_ref,
        },
        "dataset_use_validation": {
            "source_ref": source_ref,
            "dataset_semantics_ref": semantics_ref,
            "dataset_version_ref": version_ref,
        },
    }
    for name, expected in expected_data_links.items():
        if components[name].link_map != expected:
            _violation(
                violations,
                "onboarding_readiness_data_chain_mismatch",
                "data onboarding records must form one exact owner-scoped chain",
                field=name,
                ref=components[name].component_ref,
            )

    if snapshot.credential_mode not in {"secret_ref", "no_secret_policy"}:
        _violation(
            violations,
            "onboarding_readiness_credential_mode_invalid",
            "credential_mode must be secret_ref or no_secret_policy",
            field="credential_mode",
            ref=snapshot.credential_mode,
        )
    elif snapshot.credential_mode == "secret_ref":
        if not auth_policy_ref.lower().startswith(("secretref:", "secret_ref:")):
            _violation(
                violations,
                "onboarding_readiness_secret_ref_invalid",
                "secret-backed onboarding requires an explicit SecretRef identity",
                field="secret_or_no_secret_policy",
                ref=auth_policy_ref,
            )
        if components["secret_or_no_secret_policy"].status != "active":
            _violation(
                violations,
                "onboarding_readiness_secret_not_active",
                "secret-backed onboarding requires a currently active SecretRef",
                field="secret_or_no_secret_policy",
                ref=auth_policy_ref,
            )
    elif not auth_policy_ref.startswith("no_secret_policy:"):
        _violation(
            violations,
            "onboarding_readiness_no_secret_policy_invalid",
            "public connectors require an explicit no-secret policy identity",
            field="secret_or_no_secret_policy",
            ref=auth_policy_ref,
        )

    provider = components["llm_provider"]
    auth = components["service_principal_auth"]
    pool = components["credential_pool"]
    policy = components["routing_policy"]
    binding = components["user_service_binding"]
    service_principal_ref = provider.link_map.get("service_principal_ref", "")
    for name in (
        "llm_provider",
        "service_principal_auth",
        "provider_health",
        "credential_pool",
        "routing_policy",
    ):
        if components[name].principal_id != service_principal_ref:
            _violation(
                violations,
                "onboarding_readiness_service_principal_mismatch",
                "provider, auth, health, pool, and routing policy must resolve to one service principal",
                field=name,
                ref=components[name].component_ref,
            )
    for name in ("user_service_binding", "terminal_llm_call"):
        if components[name].principal_id != owner:
            _violation(
                violations,
                "onboarding_readiness_llm_user_owner_mismatch",
                "use binding and terminal call must belong to the requesting user",
                field=name,
                ref=components[name].component_ref,
            )

    common_llm = {
        "provider_ref": provider.component_ref,
        "auth_ref": auth.component_ref,
        "credential_pool_ref": pool.component_ref,
        "service_principal_ref": service_principal_ref,
    }
    expected_llm_links = {
        "llm_provider": {"service_principal_ref": service_principal_ref},
        "service_principal_auth": {
            "provider_ref": provider.component_ref,
            "service_principal_ref": service_principal_ref,
        },
        "provider_health": {
            "provider_ref": provider.component_ref,
            "auth_ref": auth.component_ref,
            "service_principal_ref": service_principal_ref,
            "freshness_status": "current",
        },
        "credential_pool": {
            "provider_ref": provider.component_ref,
            "auth_ref": auth.component_ref,
            "service_principal_ref": service_principal_ref,
        },
        "routing_policy": {
            **common_llm,
        },
        "user_service_binding": {
            **common_llm,
            "owner_user_id": owner,
            "routing_policy_ref": policy.component_ref,
        },
        "terminal_llm_call": {
            **common_llm,
            "owner_user_id": owner,
            "routing_policy_ref": policy.component_ref,
            "user_service_binding_ref": binding.component_ref,
            "record_kind": "terminal",
        },
    }
    for name, expected in expected_llm_links.items():
        if components[name].link_map != expected:
            _violation(
                violations,
                "onboarding_readiness_llm_chain_mismatch",
                "terminal LLM consumption must exactly bind user, service principal, auth, pool, and policy",
                field=name,
                ref=components[name].component_ref,
            )

    return OnboardingReadinessDecision(not violations, tuple(violations))


def validate_onboarding_readiness_receipt_shape(
    receipt: OnboardingReadinessReceipt,
) -> OnboardingReadinessDecision:
    violations: list[OnboardingReadinessViolation] = []
    if receipt.receipt_version != READINESS_RECEIPT_VERSION:
        _violation(
            violations,
            "onboarding_readiness_receipt_version_unsupported",
            "readiness receipt version is unsupported",
            field="receipt_version",
            ref=receipt.receipt_ref,
        )
    decision = validate_onboarding_readiness_snapshot(
        receipt.snapshot,
        owner_user_id=receipt.owner_user_id,
        data_source_ref=receipt.data_source_ref,
        llm_routing_policy_ref=receipt.llm_routing_policy_ref,
        terminal_llm_call_ref=receipt.terminal_llm_call_ref,
    )
    violations.extend(decision.violations)
    if receipt.receipt_ref != receipt.canonical_receipt_ref:
        _violation(
            violations,
            "onboarding_readiness_receipt_identity_mismatch",
            "receipt_ref must content-bind all component identities and current state hashes",
            field="receipt_ref",
            ref=receipt.receipt_ref,
        )
    return OnboardingReadinessDecision(not violations, tuple(violations))


class PersistentOnboardingReadinessRegistry:
    """Schema-v2 owner ledger whose receipts remain green only while current."""

    def __init__(self, path: str | Path, *, resolve_snapshot: ReadinessResolver) -> None:
        if not callable(resolve_snapshot):
            raise TypeError("resolve_snapshot must be callable")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._resolve_snapshot = resolve_snapshot
        self._records: dict[tuple[str, str], OnboardingReadinessReceipt] = {}
        self._heads: dict[tuple[str, str, str, str], OnboardingReadinessReceipt] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return self._legacy_quarantined_count

    @staticmethod
    def _owner(value: Any) -> str:
        owner = _text(value)
        if not owner or owner != value or any(ord(char) < 32 for char in owner):
            raise ValueError("owner_user_id must be a stable non-empty exact string")
        return owner

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

    def _reset(self) -> None:
        self._records = {}
        self._heads = {}
        self._legacy_quarantined_count = 0

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self._legacy_quarantined_count += 1
                continue
            if not isinstance(row, dict) or row.get("schema_version") != READINESS_SCHEMA_VERSION:
                self._legacy_quarantined_count += 1
                continue
            try:
                self._apply_row(row)
            except Exception as exc:  # schema-v2 corruption must fail startup closed.
                raise ValueError(
                    f"invalid persisted onboarding readiness row at {self._path}:{line_no}"
                ) from exc

    def _apply_row(self, row: dict[str, Any]) -> None:
        expected = {"schema_version", "event_type", "owner_user_id", "receipt", "record_hash"}
        if set(row) != expected or row.get("event_type") != "onboarding_readiness_recorded":
            raise ValueError("onboarding readiness row has an inexact schema-v2 envelope")
        owner = self._owner(row["owner_user_id"])
        body = {key: value for key, value in row.items() if key != "record_hash"}
        if row["record_hash"] != "sha256:" + _sha256(body):
            raise ValueError("onboarding readiness record_hash mismatch")
        receipt = onboarding_readiness_receipt_from_dict(row["receipt"])
        if receipt.owner_user_id != owner:
            raise ValueError("onboarding readiness row owner mismatch")
        decision = validate_onboarding_readiness_receipt_shape(receipt)
        if not decision.accepted:
            raise ValueError("invalid onboarding readiness receipt shape")
        key = (owner, receipt.receipt_ref)
        existing = self._records.get(key)
        if existing is not None and existing != receipt:
            raise ValueError("onboarding readiness receipt identity collision")
        self._records[key] = receipt
        self._heads[self._scope(receipt)] = receipt

    @staticmethod
    def _scope(receipt: OnboardingReadinessReceipt) -> tuple[str, str, str, str]:
        return (
            receipt.owner_user_id,
            receipt.data_source_ref,
            receipt.llm_routing_policy_ref,
            receipt.terminal_llm_call_ref,
        )

    def _resolve(self, owner: str, source: str, policy: str, call: str) -> OnboardingReadinessSnapshot:
        snapshot = self._resolve_snapshot(owner, source, policy, call)
        if not isinstance(snapshot, OnboardingReadinessSnapshot):
            raise TypeError("readiness resolver must return OnboardingReadinessSnapshot")
        return snapshot

    @staticmethod
    def _decision_error(decision: OnboardingReadinessDecision) -> OnboardingReadinessError:
        codes = ", ".join(item.code for item in decision.violations)
        return OnboardingReadinessError(f"onboarding readiness rejected: {codes}")

    def record_current(
        self,
        owner_user_id: str,
        data_source_ref: str,
        llm_routing_policy_ref: str,
        terminal_llm_call_ref: str,
    ) -> OnboardingReadinessReceipt:
        """Resolve and persist current evidence from identities only."""

        owner = self._owner(owner_user_id)
        source = _text(data_source_ref)
        policy = _text(llm_routing_policy_ref)
        call = _text(terminal_llm_call_ref)
        snapshot = self._resolve(owner, source, policy, call)
        decision = validate_onboarding_readiness_snapshot(
            snapshot,
            owner_user_id=owner,
            data_source_ref=source,
            llm_routing_policy_ref=policy,
            terminal_llm_call_ref=call,
        )
        if not decision.accepted:
            raise self._decision_error(decision)
        blank = OnboardingReadinessReceipt(
            receipt_ref="",
            owner_user_id=owner,
            data_source_ref=source,
            llm_routing_policy_ref=policy,
            terminal_llm_call_ref=call,
            snapshot=snapshot,
        )
        receipt = OnboardingReadinessReceipt(
            receipt_ref=blank.canonical_receipt_ref,
            owner_user_id=blank.owner_user_id,
            data_source_ref=blank.data_source_ref,
            llm_routing_policy_ref=blank.llm_routing_policy_ref,
            terminal_llm_call_ref=blank.terminal_llm_call_ref,
            snapshot=blank.snapshot,
            receipt_version=blank.receipt_version,
        )
        shape = validate_onboarding_readiness_receipt_shape(receipt)
        if not shape.accepted:
            raise self._decision_error(shape)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            key = (owner, receipt.receipt_ref)
            existing = self._records.get(key)
            if existing is not None:
                if existing == receipt:
                    return existing
                raise OnboardingReadinessError("onboarding readiness receipt identity collision")
            body = {
                "schema_version": READINESS_SCHEMA_VERSION,
                "event_type": "onboarding_readiness_recorded",
                "owner_user_id": owner,
                "receipt": asdict(receipt),
            }
            row = {**body, "record_hash": "sha256:" + _sha256(body)}
            self._atomic_append(row)
            self._records[key] = receipt
            self._heads[self._scope(receipt)] = receipt
        return receipt

    def _atomic_append(self, row: dict[str, Any]) -> None:
        existing = self._path.read_bytes() if self._path.exists() else b""
        encoded = (_canonical_json(row) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(existing)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def receipt(self, receipt_ref: str, *, owner_user_id: str) -> OnboardingReadinessReceipt:
        owner = self._owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._records[(owner, _text(receipt_ref))]
            except KeyError as exc:
                raise KeyError("onboarding readiness receipt is not recorded for owner") from exc

    def receipts(self, *, owner_user_id: str) -> tuple[OnboardingReadinessReceipt, ...]:
        owner = self._owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return tuple(record for (record_owner, _ref), record in self._records.items() if record_owner == owner)

    def current_receipt(
        self,
        owner_user_id: str,
        data_source_ref: str,
        llm_routing_policy_ref: str,
        terminal_llm_call_ref: str,
    ) -> OnboardingReadinessReceipt:
        owner = self._owner(owner_user_id)
        scope = (
            owner,
            _text(data_source_ref),
            _text(llm_routing_policy_ref),
            _text(terminal_llm_call_ref),
        )
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._heads[scope]
            except KeyError as exc:
                raise KeyError("onboarding readiness scope has no recorded receipt") from exc

    def validate_current(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> OnboardingReadinessDecision:
        """Re-resolve every dependency and reject any current-state drift."""

        receipt = self.receipt(receipt_ref, owner_user_id=owner_user_id)
        try:
            current = self._resolve(
                receipt.owner_user_id,
                receipt.data_source_ref,
                receipt.llm_routing_policy_ref,
                receipt.terminal_llm_call_ref,
            )
        except Exception as exc:  # missing/revoked dependencies are a red decision, not green history.
            return OnboardingReadinessDecision(
                False,
                (
                    OnboardingReadinessViolation(
                        "onboarding_readiness_resolution_failed",
                        f"current readiness chain could not be resolved: {type(exc).__name__}",
                        ref=receipt.receipt_ref,
                    ),
                ),
            )
        decision = validate_onboarding_readiness_snapshot(
            current,
            owner_user_id=receipt.owner_user_id,
            data_source_ref=receipt.data_source_ref,
            llm_routing_policy_ref=receipt.llm_routing_policy_ref,
            terminal_llm_call_ref=receipt.terminal_llm_call_ref,
        )
        violations = list(decision.violations)
        if current != receipt.snapshot:
            _violation(
                violations,
                "onboarding_readiness_current_state_drifted",
                "current component identity, revision, state, status, or linkage differs from the receipt",
                ref=receipt.receipt_ref,
            )
        return OnboardingReadinessDecision(not violations, tuple(violations))


def onboarding_readiness_semantic_material(
    receipt: OnboardingReadinessReceipt,
    *,
    entrypoint_ref: str = ONBOARDING_READINESS_ENTRYPOINT_REF,
) -> OnboardingReadinessSemanticMaterial:
    """Derive the only accepted §4 proof surface from one readiness receipt."""

    if entrypoint_ref != ONBOARDING_READINESS_ENTRYPOINT_REF:
        raise ValueError("§4 semantic material requires the canonical readiness API")
    components = tuple(
        (name, getattr(receipt.snapshot, name)) for name in READINESS_COMPONENT_FIELDS
    )
    state_refs = tuple(
        "onboarding_readiness_component_state:"
        f"{receipt.receipt_ref}:{name}:{component.component_ref}:"
        f"{component.revision}:{component.state_hash}"
        for name, component in components
    )
    current_check_refs = tuple(
        "onboarding_readiness_current_check:"
        f"{receipt.receipt_ref}:{name}:{component.component_ref}:"
        f"{component.revision}:{component.state_hash}"
        for name, component in components
    )
    return OnboardingReadinessSemanticMaterial(
        subject_ref=(
            "goal_section:§4:onboarding_readiness_receipt:"
            f"{receipt.receipt_ref}"
        ),
        producer_refs=tuple(component.component_ref for _name, component in components),
        store_refs=(receipt.receipt_ref, *state_refs),
        consumer_refs=(
            entrypoint_ref,
            receipt.snapshot.user_service_binding.component_ref,
            receipt.snapshot.terminal_llm_call.component_ref,
        ),
        gate_verdict_refs=(receipt.receipt_ref,),
        test_refs=current_check_refs,
    )


class OnboardingReadinessSectionAdapter:
    """Prove GOAL §4 from one current receipt and one canonical API lineage."""

    def __init__(
        self,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        readiness_registry: PersistentOnboardingReadinessRegistry,
    ) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._readiness_registry = readiness_registry

    @staticmethod
    def _entry_source(coverage: Any) -> str:
        value = getattr(coverage, "entry_source", "")
        return _text(getattr(value, "value", value)).lower()

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, reason: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_onboarding_readiness_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        owner = _text(owner)
        if record.section != "§4":
            reject("section", record.section, "onboarding readiness adapter only supports §4")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject(
                "recorded_by",
                record.recorded_by,
                "§4 semantic proof owner must match the requested owner",
            )
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "§4 completion requires an explicit complete claim with no residuals",
            )
        if len(record.entrypoint_coverage_refs) != 1:
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "§4 requires exactly one canonical readiness API lineage",
            )
            return GoalSemanticDecision(False, tuple(violations))

        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
        except (KeyError, LookupError, TypeError, ValueError):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§4 readiness API lineage is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if _text(getattr(coverage, "recorded_by", "")) != owner:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§4 readiness API lineage owner does not match",
            )
        try:
            coverage_decision = self._entrypoint_registry.validate_real_backing(coverage)
        except Exception:  # noqa: BLE001 - current entrypoint validation fails closed.
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§4 readiness API current-backing validation raised",
            )
        else:
            if not bool(getattr(coverage_decision, "accepted", False)):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "§4 readiness API lineage failed strict current backing",
                )
        if (
            self._entry_source(coverage) != "api"
            or _text(getattr(coverage, "entrypoint_ref", ""))
            != ONBOARDING_READINESS_ENTRYPOINT_REF
        ):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§4 requires the canonical onboarding-readiness API entrypoint",
            )
        if "§4" not in set(getattr(coverage, "goal_sections", ()) or ()):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "readiness API lineage does not cite §4",
            )

        receipt_refs = tuple(
            _text(ref)
            for ref in tuple(getattr(coverage, "validation_refs", ()) or ())
            if _text(ref).startswith("onboarding_readiness_receipt:")
        )
        if len(receipt_refs) != 1 or len(set(receipt_refs)) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(receipt_refs),
                "§4 readiness API lineage must bind exactly one readiness receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._readiness_registry.receipt(
                receipt_ref,
                owner_user_id=owner,
            )
        except (KeyError, LookupError, TypeError, ValueError):
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§4 readiness receipt is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        try:
            current = self._readiness_registry.validate_current(
                receipt_ref,
                owner_user_id=owner,
            )
        except Exception:  # noqa: BLE001 - live readiness validation fails closed.
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§4 readiness receipt current validation raised",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not current.accepted:
            codes = ",".join(sorted({item.code for item in current.violations}))
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§4 readiness receipt is no longer current"
                + (f": {codes}" if codes else ""),
            )

        components = tuple(
            (name, getattr(receipt.snapshot, name))
            for name in READINESS_COMPONENT_FIELDS
        )
        component_refs = tuple(component.component_ref for _name, component in components)
        if len(components) != 18 or len(component_refs) != len(set(component_refs)):
            reject(
                "producer_refs",
                ",".join(component_refs),
                "§4 requires exactly 18 distinct readiness component identities",
            )

        service_principal_ref = receipt.snapshot.llm_provider.link_map.get(
            "service_principal_ref", ""
        )
        service_components = (
            receipt.snapshot.llm_provider,
            receipt.snapshot.service_principal_auth,
            receipt.snapshot.provider_health,
            receipt.snapshot.credential_pool,
            receipt.snapshot.routing_policy,
        )
        user_components = (
            receipt.snapshot.user_service_binding,
            receipt.snapshot.terminal_llm_call,
        )
        call_links = receipt.snapshot.terminal_llm_call.link_map
        if (
            not service_principal_ref
            or any(item.principal_id != service_principal_ref for item in service_components)
            or any(item.principal_id != owner for item in user_components)
            or call_links.get("user_service_binding_ref")
            != receipt.snapshot.user_service_binding.component_ref
            or call_links.get("routing_policy_ref") != receipt.llm_routing_policy_ref
            or call_links.get("record_kind") != "terminal"
        ):
            reject(
                "consumer_refs",
                receipt.snapshot.terminal_llm_call.component_ref,
                "§4 terminal call must consume the exact owner-to-service-principal binding and policy",
            )

        expected = onboarding_readiness_semantic_material(receipt)
        if record.subject_ref != expected.subject_ref:
            reject(
                "subject_ref",
                record.subject_ref,
                "§4 subject must content-bind the current readiness receipt",
            )
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            expected_values = tuple(getattr(expected, field_name))
            actual_values = tuple(getattr(record, field_name))
            if (
                len(actual_values) != len(set(actual_values))
                or set(actual_values) != set(expected_values)
            ):
                reject(
                    field_name,
                    ",".join(sorted(actual_values)),
                    f"{field_name} must exactly match all current §4 receipt material",
                )

        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "ONBOARDING_READINESS_ENTRYPOINT_REF",
    "OnboardingReadinessDecision",
    "OnboardingReadinessError",
    "OnboardingReadinessReceipt",
    "OnboardingReadinessSectionAdapter",
    "OnboardingReadinessSemanticMaterial",
    "OnboardingReadinessSnapshot",
    "OnboardingReadinessViolation",
    "PersistentOnboardingReadinessRegistry",
    "READINESS_COMPONENT_FIELDS",
    "READINESS_RECEIPT_VERSION",
    "READINESS_SCHEMA_VERSION",
    "ReadinessComponentState",
    "ReadinessResolver",
    "onboarding_readiness_receipt_from_dict",
    "onboarding_readiness_receipt_identity",
    "onboarding_readiness_semantic_material",
    "onboarding_readiness_snapshot_from_dict",
    "validate_onboarding_readiness_receipt_shape",
    "validate_onboarding_readiness_snapshot",
]
