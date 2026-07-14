"""Persist server-derived M17, M18, and M20 business attestations.

The public operation accepts only an authenticated owner, a supported platform
row, and that row's canonical business anchor.  Every other reference is read
from an injected, owner-scoped store before the first append-only write.

This module deliberately does not submit orders, reserve risk, relay signals,
write RDP manifests, or start/finalize a HALT operation.  Its only mutations are
one owner/API Research Graph QRO head and the compiler/coverage callback supplied
by the application composition root.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .goal_coverage import goal_entrypoint_coverage_identity
from .ref_resolution import is_placeholder_ref
from .spine import (
    ActorSource,
    ConsistencyStatus,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    GovernanceStatus,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    RuntimeStatus,
)
from .spine_chain_selection import resolve_unique_verified_spine_chain
from .platform_typed_sources import (
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)


M17 = "M17"
M18 = "M18"
M20 = "M20"
SUPPORTED_ROWS = (M17, M18, M20)

ENTRYPOINT_REFS = {
    M17: "api:research_os.platform.business_attestations.m17",
    M18: "api:research_os.platform.business_attestations.m18",
    M20: "api:research_os.platform.business_attestations.m20",
}

_QRO_TYPES = {
    M17: QROType.EXECUTION_POLICY,
    M18: QROType.VALIDATION_DOSSIER,
    M20: QROType.RISK_POLICY,
}

_OUTPUT_CONTRACTS = {
    M17: {"status": "guarded_submission_recorded"},
    M18: {"status": "current_code_package_attested"},
    M20: {"status": "halted_security_controls_verified"},
}

_GOAL_SECTIONS = {
    M17: ("§0", "§1", "§6", "§8", "§16"),
    M18: ("§0", "§1", "§6", "§7", "§8", "§17"),
    M20: ("§0", "§1", "§8", "§16"),
}

_PROCESS_ATTESTATION_LOCK = threading.RLock()


class PlatformBusinessAttestationError(ValueError):
    """Current server-owned state cannot form one truthful attestation."""


class PlatformBusinessAttestationCommitError(RuntimeError):
    """An append-only attestation cycle stopped after a mutation boundary.

    The error reports observed Graph state only.  ``None`` means the durable
    state could not be observed.  On this error type, ``graph_command_created``
    means the exact command is observed in history; it does not guess whether
    this particular retry performed the first append.  Compiler and coverage
    stores are independent append-only ledgers, so this exception never claims
    that a partial IR/pass/coverage write was rolled back.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        graph_attestation_current: bool | None,
        graph_command_ref: str = "",
        graph_command_created: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = str(phase)
        self.graph_attestation_current = (
            None
            if graph_attestation_current is None
            else bool(graph_attestation_current)
        )
        self.graph_command_ref = str(graph_command_ref or "")
        self.graph_command_created = (
            None
            if graph_command_created is None
            else bool(graph_command_created)
        )


@contextmanager
def _attestation_transaction(context: Any):
    """Serialize preflight, Graph, compiler, and coverage observation.

    A process lock covers in-memory stores and multiple service instances.  A
    path-scoped file lock additionally serializes callers that share a durable
    Research Graph.  The durable Graph is refreshed only after the lock is
    held, so a second caller cannot make a decision from its startup snapshot.
    """

    graph = context.research_graph_store
    with _PROCESS_ATTESTATION_LOCK:
        raw_path = getattr(graph, "path", None)
        if raw_path is None:
            yield
            return
        lock_path = Path(str(raw_path) + ".platform-business-attestation.lock")
        fd = None
        held = None
        try:
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                os.chmod(lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                refresh = getattr(graph, "refresh", None)
                if not callable(refresh):
                    raise TypeError("persistent Research Graph store lacks refresh()")
                refresh()
            except Exception as exc:  # noqa: BLE001 - no mutation has started.
                raise PlatformBusinessAttestationCommitError(
                    "platform business attestation lock/refresh failed:"
                    f"{type(exc).__name__}:{exc}",
                    phase="attestation_lock",
                    graph_attestation_current=None,
                    graph_command_created=None,
                ) from exc
            yield
        finally:
            if held is not None:
                held.release()
            if fd is not None:
                os.close(fd)


@dataclass(frozen=True)
class PlatformBusinessAttestationCompilePlan:
    """Server-derived inputs for the application's governed compiler callback."""

    row: str
    owner_user_id: str
    anchor_ref: str
    entrypoint_ref: str
    pass_name: str
    validation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    environment_lock_ref: str
    permission_ref: str
    deterministic_run_plan_ref: str
    rollback_ref: str
    tool_record_refs: tuple[str, ...]
    node_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...]
    lifecycle_refs: tuple[str, ...]
    rdp_refs: tuple[str, ...]
    theory_binding_refs: tuple[str, ...]
    consistency_check_refs: tuple[str, ...]
    mathematical_spine_chain_refs: tuple[str, ...]
    goal_sections: tuple[str, ...]


@dataclass(frozen=True)
class PlatformBusinessAttestationContext:
    """Application-owned stores used by the read-only preflight and commit."""

    research_graph_store: Any
    compiler_store: Any
    entrypoint_registry: Any
    spine_chain_registry: Any
    compile_attestation: Callable[[QRORecord, ResearchGraphCommand, PlatformBusinessAttestationCompilePlan], Mapping[str, Any]]
    validate_current_attestation: Callable[[PlatformBusinessAttestationResult], Any]
    entrypoint_view_factory: Callable[[], Any] | None = None
    compiler_view_factory: Callable[[], Any] | None = None
    validation_receipt_registry: Any = None
    copy_trade_service: Any = None
    runtime_promotion_registry: Any = None
    follower_risk_state_store: Any = None
    execution_order_submission_registry: Any = None
    execution_order_intent_registry: Any = None
    canonical_spine_ledger: Any = None
    rdp_store: Any = None
    onboarding_registry: Any = None
    llm_call_record_store: Any = None
    account_halt_barrier: Any = None
    llm_service_owner_user_id: str = ""


@dataclass(frozen=True)
class PlatformBusinessAttestationResult:
    owner_user_id: str
    row: str
    anchor_ref: str
    entrypoint_ref: str
    qro_ref: str
    graph_command_ref: str
    graph_command_created: bool
    mathematical_spine_chain_ref: str
    compiler_ir_ref: str
    compiler_pass_ref: str
    entrypoint_coverage_ref: str


@dataclass(frozen=True)
class _PreparedAttestation:
    owner_user_id: str
    row: str
    anchor_ref: str
    entrypoint_ref: str
    qro: QRORecord
    chain: Any
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    lifecycle_refs: tuple[str, ...]
    rdp_refs: tuple[str, ...]
    theory_binding_refs: tuple[str, ...]
    consistency_check_refs: tuple[str, ...]
    canonical_business_command_refs: tuple[str, ...]


def _enum_text(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value or "").strip()


def _owner(value: Any) -> str:
    return str(
        getattr(
            value,
            "owner_user_id",
            getattr(
                value,
                "owner",
                getattr(
                    value,
                    "recorded_by",
                    getattr(value, "user_id", getattr(value, "actor", "")),
                ),
            ),
        )
        or ""
    ).strip()


def _exact(
    value: Any,
    *,
    field: str,
    prefix: str | tuple[str, ...] = (),
) -> str:
    raw = str(getattr(value, "value", value) or "")
    token = raw.strip()
    if (
        not token
        or token != raw
        or any(ord(char) < 32 for char in token)
        or is_placeholder_ref(token)
    ):
        raise PlatformBusinessAttestationError(f"{field} is not an exact stable ref")
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    if prefixes and not token.startswith(prefixes):
        raise PlatformBusinessAttestationError(
            f"{field} does not use its canonical prefix"
        )
    return token


def _tuple_refs(
    values: Any,
    *,
    field: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    refs = tuple(_exact(value, field=field) for value in tuple(values or ()))
    if not refs and not allow_empty:
        raise PlatformBusinessAttestationError(f"{field} must contain at least one ref")
    if len(refs) != len(set(refs)):
        raise PlatformBusinessAttestationError(f"{field} contains duplicate refs")
    return refs


def _unique_refs(*groups: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for group in groups:
        if group is None:
            continue
        values = group if isinstance(group, (tuple, list, set, frozenset)) else (group,)
        for value in values:
            ref = _exact(value, field="derived reference")
            if ref not in refs:
                refs.append(ref)
    return tuple(refs)


def _one(values: Iterable[Any], *, label: str) -> Any:
    matches = tuple(values)
    if len(matches) != 1:
        raise PlatformBusinessAttestationError(
            f"{label} must resolve to exactly one current record; found {len(matches)}"
        )
    return matches[0]


def _refresh_if_available(store: Any) -> None:
    refresh = getattr(store, "refresh", None)
    if callable(refresh):
        refresh()


def _require_methods(value: Any, methods: tuple[str, ...], *, label: str) -> None:
    missing = tuple(name for name in methods if not callable(getattr(value, name, None)))
    if missing:
        raise PlatformBusinessAttestationError(
            f"{label} is missing required methods: {', '.join(missing)}"
        )


def _entrypoint_read_methods(view: Any) -> tuple[str, ...]:
    """Select canonical proof heads when the store advertises them.

    In-memory doubles and legacy replay fixtures remain an explicit
    compatibility surface, matching :func:`platform_compiler_snapshot`.
    """

    if (
        getattr(view, "canonical_projection_available", None) is not False
        and callable(getattr(view, "canonical_records", None))
        and callable(getattr(view, "canonical_coverage", None))
    ):
        return ("canonical_records", "canonical_coverage", "validate_real_backing")
    return ("records", "coverage", "validate_real_backing")


def _entrypoint_records(view: Any, *, owner: str) -> tuple[Any, ...]:
    methods = _entrypoint_read_methods(view)
    return tuple(getattr(view, methods[0])(owner=owner) or ())


def _entrypoint_coverage(view: Any, ref: str, *, owner: str) -> Any:
    methods = _entrypoint_read_methods(view)
    return getattr(view, methods[1])(ref, owner=owner)


def _chain_ref(chain: Any, *, owner: str) -> str:
    ref = _exact(getattr(chain, "chain_ref", ""), field="Mathematical Spine chain_ref")
    if _owner(chain) != owner:
        raise PlatformBusinessAttestationError("Mathematical Spine owner mismatch")
    return ref


def _qro(
    *,
    owner: str,
    row: str,
    contracts: Mapping[str, str],
    chain: Any,
    market: str,
    universe: str,
    horizon: str,
    frequency: str,
    evidence_refs: tuple[str, ...],
    theory_binding_ref: str | None = None,
) -> QRORecord:
    chain_ref = _chain_ref(chain, owner=owner)
    input_contract = {str(key): _exact(value, field=f"{row} input_contract.{key}") for key, value in contracts.items()}
    implementation_hash = "platform_business_attestation_" + content_hash(
        {
            "schema_version": 1,
            "row": row,
            "owner_user_id": owner,
            "input_contract": input_contract,
            "output_contract": _OUTPUT_CONTRACTS[row],
            "mathematical_spine_chain_ref": chain_ref,
        }
    )
    common = dict(
        qro_type=_QRO_TYPES[row],
        owner=owner,
        actor=ActorSource.USER_MANUAL,
        input_contract=input_contract,
        output_contract=dict(_OUTPUT_CONTRACTS[row]),
        market=str(market or "unspecified").strip() or "unspecified",
        universe=str(universe or "unspecified").strip() or "unspecified",
        horizon=str(horizon or "event").strip() or "event",
        frequency=str(frequency or "event").strip() or "event",
        lineage=_unique_refs(tuple(input_contract.values()), chain_ref),
        implementation_hash=implementation_hash,
        assumptions=(
            "All attested references were derived from current owner-scoped stores during one read-only preflight.",
        ),
        known_limits=(
            "This record attests persisted state only; it does not claim CI, production health, execution success, or user acceptance.",
        ),
        failure_modes=(
            "A later source mutation, duplicate source, or recombined lineage invalidates reuse and requires explicit review.",
        ),
        validation_plan=(
            "Replay the row-specific source-lineage policy against the persisted QRO, Graph, compiler, coverage, and Mathematical Spine stores.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.SUFFICIENT,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        evidence_refs=evidence_refs,
        mathematical_refs=(chain_ref,),
        permission=f"platform.business_attestation:{row.lower()}:owner",
        responsibility_boundary=(
            "Read-only business-state attestation; no order, reservation, relay, RDP, secret, or HALT mutation."
        ),
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    if row == M18:
        common.update(
            theory_implementation_binding=theory_binding_ref,
            consistency_status=ConsistencyStatus.ACCEPTED,
            consistency_verdict=ConsistencyStatus.ACCEPTED,
        )
    return QRORecord(**common)


class PlatformBusinessAttestationService:
    """Derive, persist, verify, and idempotently reuse one row attestation.

    Every successful append is forward-only.  A later callback, verification,
    or acknowledgement failure reports observed durable state; it never
    deletes Graph, compiler, coverage, evidence, or validation history.
    """

    def __init__(self, context: PlatformBusinessAttestationContext) -> None:
        self._context = context
        _require_methods(
            context.research_graph_store,
            ("qro", "commands", "projection_index", "apply"),
            label="research_graph_store",
        )
        _require_methods(
            context.compiler_store,
            platform_compiler_snapshot_required_methods(context.compiler_store),
            label="compiler_store",
        )
        _require_methods(
            context.entrypoint_registry,
            _entrypoint_read_methods(context.entrypoint_registry),
            label="entrypoint_registry",
        )
        _require_methods(
            context.spine_chain_registry,
            ("chains", "verified_chain"),
            label="spine_chain_registry",
        )
        if not callable(context.compile_attestation):
            raise PlatformBusinessAttestationError("compile_attestation must be callable")
        if not callable(context.validate_current_attestation):
            raise PlatformBusinessAttestationError(
                "validate_current_attestation must be callable"
            )
        if context.entrypoint_view_factory is not None and not callable(
            context.entrypoint_view_factory
        ):
            raise PlatformBusinessAttestationError(
                "entrypoint_view_factory must be callable"
            )
        if context.compiler_view_factory is not None and not callable(
            context.compiler_view_factory
        ):
            raise PlatformBusinessAttestationError(
                "compiler_view_factory must be callable"
            )

    def _entrypoint_view(self) -> Any:
        view = (
            self._context.entrypoint_view_factory()
            if self._context.entrypoint_view_factory is not None
            else self._context.entrypoint_registry
        )
        _require_methods(
            view,
            _entrypoint_read_methods(view),
            label="entrypoint view",
        )
        return view

    def _compiler_view(self) -> Any:
        view = (
            self._context.compiler_view_factory()
            if self._context.compiler_view_factory is not None
            else self._context.compiler_store
        )
        _require_methods(
            view,
            platform_compiler_snapshot_required_methods(view),
            label="compiler view",
        )
        return view

    def _validate_current_policy(
        self,
        *,
        result: PlatformBusinessAttestationResult,
        prepared: _PreparedAttestation,
        command: ResearchGraphCommand,
    ) -> None:
        """Replay the row policy before making staged ledgers visible as success."""

        try:
            resolution = self._context.validate_current_attestation(result)
            if (
                _enum_text(getattr(resolution, "m_row", "")) != result.row
                or _exact(
                    getattr(resolution, "anchor_ref", ""),
                    field="policy resolution anchor_ref",
                )
                != result.anchor_ref
                or _exact(
                    getattr(resolution, "qro_ref", ""),
                    field="policy resolution qro_ref",
                )
                != result.qro_ref
                or _enum_text(
                    getattr(resolution, "business_entry_source", "")
                )
                != EntrySource.API.value
                or _exact(
                    getattr(resolution, "business_entrypoint_ref", ""),
                    field="policy resolution business_entrypoint_ref",
                )
                != result.entrypoint_ref
                or _exact(
                    getattr(resolution, "math_spine_ref", ""),
                    field="policy resolution math_spine_ref",
                )
                != result.mathematical_spine_chain_ref
            ):
                raise PlatformBusinessAttestationError(
                    "current row policy returned different or recombined attestation lineage"
                )
        except Exception as exc:
            graph_current, graph_observed = self._observe_graph_state(
                prepared=prepared,
                command=command,
            )
            raise PlatformBusinessAttestationCommitError(
                f"current row-policy replay failed:{type(exc).__name__}:{exc}",
                phase="policy_replay",
                graph_attestation_current=graph_current,
                graph_command_ref=command.command_id,
                graph_command_created=graph_observed,
            ) from exc

    def _prepare_m17(self, *, owner: str, anchor: str) -> _PreparedAttestation:
        context = self._context
        for value, methods, label in (
            (context.copy_trade_service, ("get_follower", "subscription"), "copy_trade_service"),
            (context.runtime_promotion_registry, ("promotion",), "runtime_promotion_registry"),
            (
                context.follower_risk_state_store,
                ("reservation_for_submission", "reservation_by_risk_check_ref"),
                "follower_risk_state_store",
            ),
            (
                context.execution_order_submission_registry,
                ("submission", "submission_by_audit_record_ref"),
                "execution_order_submission_registry",
            ),
            (context.execution_order_intent_registry, ("intent",), "execution_order_intent_registry"),
        ):
            _require_methods(value, methods, label=label)
        anchor = _exact(anchor, field="M17 anchor_ref", prefix="order_submission_")
        try:
            _refresh_if_available(context.execution_order_submission_registry)
            _refresh_if_available(context.execution_order_intent_registry)
            _refresh_if_available(context.runtime_promotion_registry)
            submission = context.execution_order_submission_registry.submission(anchor)
            audit_ref = _exact(
                getattr(submission, "audit_record_ref", ""),
                field="M17 execution_audit_ref",
                prefix="copy_submission_audit_",
            )
            audit_submission = context.execution_order_submission_registry.submission_by_audit_record_ref(audit_ref)
            reservation = context.follower_risk_state_store.reservation_for_submission(anchor)
            reservation_ref = _exact(
                getattr(reservation, "reservation_ref", ""),
                field="M17 reservation_ref",
                prefix="copy_reservation_",
            )
            risk_ref = _exact(
                getattr(reservation, "risk_check_ref", ""),
                field="M17 risk_gate_ref",
                prefix="copy_risk_check_",
            )
            risk_reservation = context.follower_risk_state_store.reservation_by_risk_check_ref(risk_ref)
            follower_id = _exact(getattr(reservation, "follower_id", ""), field="M17 follower_id")
            follower = context.copy_trade_service.get_follower(follower_id)
            if follower is None:
                raise KeyError("current follower is missing")
            from ..copy_trade.service import copy_trade_subscription_ref

            subscription_ref = _exact(
                copy_trade_subscription_ref(follower),
                field="M17 copy_trade_subscription_ref",
                prefix="copy_trade_subscription_",
            )
            current_follower = context.copy_trade_service.subscription(
                subscription_ref,
                owner_user_id=owner,
            )
            promotion_ref = _exact(
                getattr(submission, "runtime_promotion_ref", ""),
                field="M17 runtime_promotion_ref",
                prefix=("runtime_promotion_", "runtime_promotion:"),
            )
            promotion = context.runtime_promotion_registry.promotion(promotion_ref)
            intent_ref = _exact(
                getattr(submission, "order_intent_ref", ""),
                field="M17 order_intent_ref",
                prefix="order_intent_",
            )
            intent = context.execution_order_intent_registry.intent(intent_ref)
        except PlatformBusinessAttestationError:
            raise
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"M17 guarded submission preflight failed:{type(exc).__name__}:{exc}"
            ) from exc

        expected_subject_ref = "copy_trade_subject_" + content_hash(
            {
                "follower_id": _exact(getattr(follower, "follower_id", ""), field="M17 follower_id"),
                "user_id": _exact(getattr(follower, "user_id", ""), field="M17 follower user_id"),
                "master_id": _exact(getattr(follower, "master_id", ""), field="M17 follower master_id"),
                "account_binding_ref": _exact(
                    getattr(follower, "account_binding_ref", ""),
                    field="M17 follower account_binding_ref",
                ),
            }
        )
        expected_audit_ref = "copy_submission_audit_" + content_hash(reservation_ref)
        permission_ref = _exact(
            getattr(promotion, "permission_gate_ref", ""),
            field="M17 permission_gate_ref",
        )
        order_guard_ref = _exact(
            getattr(promotion, "order_guard_ref", ""),
            field="M17 order_guard_ref",
        )
        account_ref = _exact(
            getattr(reservation, "account_binding_ref", ""),
            field="M17 reservation account_binding_ref",
        )
        execution_policy_ref = _exact(
            getattr(intent, "execution_policy_ref", ""),
            field="M17 execution_policy_ref",
        )
        intent_risk_ref = _exact(
            getattr(intent, "risk_policy_ref", ""),
            field="M17 intent risk_policy_ref",
        )
        if (
            audit_submission != submission
            or risk_reservation != reservation
            or current_follower != follower
            or _owner(follower) != owner
            or _enum_text(getattr(follower, "status", "")) == "stopped"
            or _exact(getattr(follower, "account_binding_ref", ""), field="M17 follower account_binding_ref") != account_ref
            or _exact(getattr(follower, "runtime_promotion_ref", ""), field="M17 follower promotion_ref") != promotion_ref
            or _exact(getattr(submission, "submission_ref", ""), field="M17 submission_ref") != anchor
            or audit_ref != expected_audit_ref
            or _enum_text(getattr(submission, "recorded_by", "")) != "copy_trade_signal_relayer"
            or _enum_text(getattr(submission, "submitter_ref", "")) != "copy_trade_signal_relayer:v1"
            or getattr(submission, "submit_enabled", False) is not True
            or _enum_text(getattr(submission, "submission_mode", "")) != "live"
            or _enum_text(getattr(promotion, "target_runtime", "")) != "live"
            or _exact(
                getattr(promotion, "runtime_promotion_ref", ""),
                field="M17 promotion ref",
            )
            != promotion_ref
            or _exact(getattr(promotion, "subject_ref", ""), field="M17 promotion subject_ref") != expected_subject_ref
            or _exact(getattr(submission, "permission_gate_ref", ""), field="M17 submission permission_gate_ref") != permission_ref
            or _exact(getattr(submission, "order_guard_ref", ""), field="M17 submission order_guard_ref") != order_guard_ref
            or _exact(getattr(intent, "order_intent_ref", ""), field="M17 intent ref") != intent_ref
            or _owner(intent) != owner
            or _enum_text(getattr(intent, "runtime", "")) != "live"
            or intent_risk_ref != risk_ref
            or execution_policy_ref != permission_ref
            or _exact(getattr(intent, "permission_gate_ref", ""), field="M17 intent permission_gate_ref") != permission_ref
            or _exact(getattr(intent, "order_guard_ref", ""), field="M17 intent order_guard_ref") != order_guard_ref
        ):
            raise PlatformBusinessAttestationError(
                "M17 subscription/promotion/risk/intent/submission state is stale or recombined"
            )
        chain = resolve_unique_verified_spine_chain(
            context.spine_chain_registry,
            owner_user_id=owner,
            scalar_refs={
                "risk_policy_ref": risk_ref,
                "execution_policy_ref": execution_policy_ref,
            },
        )
        chain_ref = _chain_ref(chain, owner=owner)
        contracts = {
            "submission_ref": anchor,
            "copy_trade_subscription_ref": subscription_ref,
            "runtime_promotion_ref": promotion_ref,
            "risk_gate_ref": risk_ref,
            "execution_audit_ref": audit_ref,
        }
        evidence_refs = _unique_refs(
            tuple(contracts.values()),
            reservation_ref,
            intent_ref,
            account_ref,
            order_guard_ref,
            chain_ref,
        )
        qro = _qro(
            owner=owner,
            row=M17,
            contracts=contracts,
            chain=chain,
            market=_enum_text(getattr(intent, "asset_class", "")),
            universe=_enum_text(getattr(intent, "instrument_ref", "")),
            horizon="guarded_live_submission",
            frequency="event",
            evidence_refs=evidence_refs,
        )
        return _PreparedAttestation(
            owner_user_id=owner,
            row=M17,
            anchor_ref=anchor,
            entrypoint_ref=ENTRYPOINT_REFS[M17],
            qro=qro,
            chain=chain,
            evidence_refs=evidence_refs,
            validation_refs=_unique_refs(risk_ref, audit_ref, chain_ref),
            lifecycle_refs=(promotion_ref,),
            rdp_refs=(),
            theory_binding_refs=_tuple_refs(
                getattr(chain, "theory_binding_refs", ()),
                field="M17 chain theory_binding_refs",
                allow_empty=True,
            ),
            consistency_check_refs=_tuple_refs(
                getattr(chain, "consistency_check_refs", ()),
                field="M17 chain consistency_check_refs",
                allow_empty=True,
            ),
            canonical_business_command_refs=(),
        )

    def _prepare_m18(self, *, owner: str, anchor: str) -> _PreparedAttestation:
        context = self._context
        _require_methods(context.canonical_spine_ledger, ("check", "binding"), label="canonical_spine_ledger")
        _require_methods(context.rdp_store, ("manifests",), label="rdp_store")
        anchor = _exact(anchor, field="M18 anchor_ref", prefix="cc_")
        try:
            _refresh_if_available(context.rdp_store)
            check = context.canonical_spine_ledger.check(anchor, owner=owner)
            binding_id = _exact(getattr(check, "binding_id", ""), field="M18 binding_id")
            binding = context.canonical_spine_ledger.binding(binding_id, owner=owner)
            manifests = tuple(
                manifest
                for manifest in context.rdp_store.manifests(owner_user_id=owner)
                if anchor in tuple(getattr(manifest, "consistency_check_refs", ()) or ())
            )
            manifest = _one(manifests, label="M18 owner RDP for ConsistencyCheck")
        except PlatformBusinessAttestationError:
            raise
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"M18 check/binding/RDP preflight failed:{type(exc).__name__}:{exc}"
            ) from exc
        if (
            _exact(getattr(check, "check_id", ""), field="M18 check_id") != anchor
            or _exact(getattr(binding, "binding_id", ""), field="M18 binding_id") != binding_id
            or _enum_text(getattr(check, "result", "")) != "pass"
            or not tuple(getattr(manifest, "test_refs", ()) or ())
            or tuple(getattr(manifest, "unverified_residuals", ()) or ())
        ):
            raise PlatformBusinessAttestationError(
                "M18 check/binding/RDP is not a current verified code package"
            )
        graph_refs = _tuple_refs(getattr(manifest, "graph_refs", ()), field="M18 RDP graph_refs")
        code_refs = _tuple_refs(getattr(manifest, "code_refs", ()), field="M18 RDP code_refs")
        used_by = _tuple_refs(getattr(binding, "used_by", ()), field="M18 binding used_by")
        canonical_command_ref = _one(
            sorted(set(graph_refs).intersection(used_by)),
            label="M18 canonical IDE code command",
        )
        canonical_command_ref = _exact(
            canonical_command_ref,
            field="M18 canonical_code_command_ref",
            prefix="rgcmd_",
        )
        try:
            canonical_command = _one(
                (
                    command
                    for command in context.research_graph_store.commands()
                    if _enum_text(getattr(command, "command_id", "")) == canonical_command_ref
                ),
                label="M18 canonical IDE command record",
            )
            payload = getattr(canonical_command, "payload", None)
            source_qro = payload.get("qro") if isinstance(payload, dict) else None
            source_qro_ref = _exact(getattr(source_qro, "qro_id", ""), field="M18 source QRO ref")
            stored_source_qro = context.research_graph_store.qro(source_qro_ref)
            source_input = getattr(source_qro, "input_contract", None)
            if not isinstance(source_input, dict):
                raise PlatformBusinessAttestationError("M18 source QRO input_contract is malformed")
            code_ref = _exact(source_input.get("code_hash"), field="M18 source code_ref")
        except PlatformBusinessAttestationError:
            raise
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"M18 canonical IDE command/QRO preflight failed:{type(exc).__name__}:{exc}"
            ) from exc
        if (
            stored_source_qro != source_qro
            or _owner(source_qro) != owner
            or _owner(canonical_command) != owner
            or _enum_text(getattr(canonical_command, "source", "")) != EntrySource.IDE.value
            or _enum_text(getattr(canonical_command, "command_type", "")) != "upsert_qro"
            or _enum_text(getattr(source_qro, "qro_type", "")) not in {QROType.STRATEGY_BOOK.value, QROType.BACKTEST_RUN.value}
            or _enum_text(source_input.get("entry_source")) != EntrySource.IDE.value
            or code_ref not in code_refs
        ):
            raise PlatformBusinessAttestationError(
                "M18 canonical IDE command/QRO/code is stale or recombined"
            )
        package_ref = _exact(getattr(manifest, "package_id", ""), field="M18 RDP package_id")
        chain = resolve_unique_verified_spine_chain(
            context.spine_chain_registry,
            owner_user_id=owner,
            contains_refs={
                "consistency_check_refs": (anchor,),
                "theory_binding_refs": (binding_id,),
            },
        )
        chain_ref = _chain_ref(chain, owner=owner)
        manifest_chain_refs = _tuple_refs(
            getattr(manifest, "mathematical_spine_chain_refs", ()),
            field="M18 RDP mathematical_spine_chain_refs",
        )
        if manifest_chain_refs != (chain_ref,):
            raise PlatformBusinessAttestationError(
                "M18 RDP must bind the exact verified Mathematical Spine chain"
            )
        contracts = {
            "canonical_code_command_ref": canonical_command_ref,
            "consistency_check_ref": anchor,
            "rdp_package_ref": package_ref,
        }
        evidence_refs = _unique_refs(
            tuple(contracts.values()),
            binding_id,
            source_qro_ref,
            code_ref,
            chain_ref,
            tuple(getattr(manifest, "test_refs", ()) or ()),
        )
        qro = _qro(
            owner=owner,
            row=M18,
            contracts=contracts,
            chain=chain,
            market=_enum_text(getattr(source_qro, "market", "")),
            universe=_enum_text(getattr(source_qro, "universe", "")),
            horizon=_enum_text(getattr(source_qro, "horizon", "")),
            frequency=_enum_text(getattr(source_qro, "frequency", "")),
            evidence_refs=evidence_refs,
            theory_binding_ref=binding_id,
        )
        prepared = _PreparedAttestation(
            owner_user_id=owner,
            row=M18,
            anchor_ref=anchor,
            entrypoint_ref=ENTRYPOINT_REFS[M18],
            qro=qro,
            chain=chain,
            evidence_refs=evidence_refs,
            validation_refs=_unique_refs(anchor, tuple(getattr(manifest, "test_refs", ()) or ()), chain_ref),
            lifecycle_refs=(package_ref,),
            rdp_refs=(package_ref,),
            theory_binding_refs=(binding_id,),
            consistency_check_refs=(anchor,),
            canonical_business_command_refs=(canonical_command_ref,),
        )
        if self._command(prepared).command_id in graph_refs:
            raise PlatformBusinessAttestationError(
                "M18 attestation Graph command must remain separate from the historical RDP"
            )
        return prepared

    def _prepare_m20(self, *, owner: str, anchor: str) -> _PreparedAttestation:
        context = self._context
        _require_methods(context.account_halt_barrier, ("halt_evidence",), label="account_halt_barrier")
        _require_methods(context.llm_call_record_store, ("read_all",), label="llm_call_record_store")
        _require_methods(context.onboarding_registry, ("secret_ref",), label="onboarding_registry")
        anchor = _exact(
            anchor,
            field="M20 anchor_ref",
            prefix=("kill_switch:", "account_halt_"),
        )
        try:
            halt = context.account_halt_barrier.halt_evidence(anchor, owner_user_id=owner)
            terminal_records = tuple(context.llm_call_record_store.read_all(owner_user_id=owner))
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"M20 HALT/LLM preflight failed:{type(exc).__name__}:{exc}"
            ) from exc
        accounts = _tuple_refs(getattr(halt, "account_binding_refs", ()), field="M20 HALT account_binding_refs")
        flat_proofs = _tuple_refs(getattr(halt, "flat_proof_refs", ()), field="M20 HALT flat_proof_refs")
        if (
            _owner(halt) != owner
            or _exact(getattr(halt, "halt_ref", ""), field="M20 HALT ref") != anchor
            or _enum_text(getattr(halt, "owner_state", "")) != "halted"
            or len(accounts) != len(flat_proofs)
        ):
            raise PlatformBusinessAttestationError(
                "M20 HALT is not terminal or lacks one flat proof per account"
            )
        service_owner = str(context.llm_service_owner_user_id or "").strip()
        candidates: list[tuple[Any, str, str, Any, str]] = []
        for terminal in terminal_records:
            if (
                _owner(terminal) != owner
                or _enum_text(getattr(terminal, "record_kind", "")) != "terminal"
                or _enum_text(getattr(terminal, "status", "")) != "ok"
            ):
                continue
            try:
                call_id = _exact(getattr(terminal, "call_id", ""), field="M20 terminal call_id")
                gateway_ref = _exact(
                    f"llm_gateway:{call_id}",
                    field="M20 llm_gateway_ref",
                    prefix="llm_gateway:",
                )
                secret_ref = _exact(
                    getattr(terminal, "auth_ref", ""),
                    field="M20 terminal auth_ref",
                    prefix=("secret:", "secretref:", "tokenref:"),
                )
                matches: list[tuple[str, Any]] = []
                for stored_owner in dict.fromkeys((owner, service_owner)):
                    if not stored_owner:
                        continue
                    try:
                        secret = context.onboarding_registry.secret_ref(
                            secret_ref,
                            owner_user_id=stored_owner,
                        )
                    except (KeyError, LookupError, PermissionError, TypeError, ValueError):
                        continue
                    if _exact(getattr(secret, "secret_ref", ""), field="M20 SecretRef") == secret_ref:
                        matches.append((stored_owner, secret))
                stored_owner, secret = _one(matches, label="M20 owner/service SecretRef")
                if stored_owner not in {owner, service_owner} or _enum_text(getattr(secret, "status", "")) != "active":
                    continue
            except PlatformBusinessAttestationError:
                continue
            candidates.append((terminal, secret_ref, gateway_ref, secret, stored_owner))
        terminal, secret_ref, gateway_ref, _secret, _stored_owner = _one(
            candidates,
            label="M20 terminal owner LLM call with one active owner/service SecretRef",
        )
        call_id = _exact(getattr(terminal, "call_id", ""), field="M20 terminal call_id")
        chain = resolve_unique_verified_spine_chain(
            context.spine_chain_registry,
            owner_user_id=owner,
            contains_refs={
                "evidence_refs": _unique_refs(
                    secret_ref,
                    gateway_ref,
                    flat_proofs,
                ),
                "validation_refs": _unique_refs(anchor, flat_proofs),
            },
        )
        chain_ref = _chain_ref(chain, owner=owner)
        contracts = {
            "secret_ref": secret_ref,
            "llm_gateway_ref": gateway_ref,
            "kill_switch_ref": anchor,
        }
        evidence_refs = _unique_refs(
            tuple(contracts.values()),
            call_id,
            accounts,
            flat_proofs,
            chain_ref,
        )
        qro = _qro(
            owner=owner,
            row=M20,
            contracts=contracts,
            chain=chain,
            market="cross_market",
            universe="owner_account_security_boundary",
            horizon="terminal_halt",
            frequency="event",
            evidence_refs=evidence_refs,
        )
        return _PreparedAttestation(
            owner_user_id=owner,
            row=M20,
            anchor_ref=anchor,
            entrypoint_ref=ENTRYPOINT_REFS[M20],
            qro=qro,
            chain=chain,
            evidence_refs=evidence_refs,
            validation_refs=_unique_refs(anchor, flat_proofs, chain_ref),
            lifecycle_refs=(anchor,),
            rdp_refs=(),
            theory_binding_refs=_tuple_refs(
                getattr(chain, "theory_binding_refs", ()),
                field="M20 chain theory_binding_refs",
                allow_empty=True,
            ),
            consistency_check_refs=_tuple_refs(
                getattr(chain, "consistency_check_refs", ()),
                field="M20 chain consistency_check_refs",
                allow_empty=True,
            ),
            canonical_business_command_refs=(),
        )

    def prepare(self, *, owner_user_id: str, row: str, anchor_ref: str) -> _PreparedAttestation:
        """Run the complete business-source preflight without mutating a store."""

        owner = _exact(owner_user_id, field="owner_user_id")
        normalized_row = str(row or "").strip().upper()
        if normalized_row not in SUPPORTED_ROWS:
            raise PlatformBusinessAttestationError(
                f"unsupported business attestation row: {normalized_row or row!r}"
            )
        preparers = {
            M17: self._prepare_m17,
            M18: self._prepare_m18,
            M20: self._prepare_m20,
        }
        return preparers[normalized_row](owner=owner, anchor=anchor_ref)

    @staticmethod
    def _command(prepared: _PreparedAttestation) -> ResearchGraphCommand:
        chain_ref = _chain_ref(prepared.chain, owner=prepared.owner_user_id)
        command_id = "rgcmd_" + content_hash(
            {
                "schema_version": 1,
                "record_type": "platform_business_attestation",
                "row": prepared.row,
                "owner_user_id": prepared.owner_user_id,
                "anchor_ref": prepared.anchor_ref,
                "entrypoint_ref": prepared.entrypoint_ref,
                "qro_ref": prepared.qro.qro_id,
                "mathematical_spine_chain_ref": chain_ref,
            }
        )
        return ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=prepared.owner_user_id,
            payload={"qro": prepared.qro},
            evidence_refs=prepared.evidence_refs,
            tool_record_refs=(prepared.entrypoint_ref,),
            command_id=command_id,
        )

    def _graph_command_is_exact(
        self,
        *,
        prepared: _PreparedAttestation,
        command: Any,
    ) -> bool:
        payload = getattr(command, "payload", None)
        embedded = payload.get("qro") if isinstance(payload, dict) else None
        expected = self._command(prepared)
        return (
            _enum_text(getattr(command, "command_id", "")) == expected.command_id
            and embedded == prepared.qro
            and _owner(command) == prepared.owner_user_id
            and _enum_text(getattr(command, "source", "")) == EntrySource.API.value
            and _enum_text(getattr(command, "actor_source", "")) == ActorSource.USER_MANUAL.value
            and _enum_text(getattr(command, "command_type", "")) == "upsert_qro"
            and tuple(getattr(command, "evidence_refs", ()) or ()) == prepared.evidence_refs
            and tuple(getattr(command, "tool_record_refs", ()) or ()) == (prepared.entrypoint_ref,)
        )

    def _existing_graph_command(
        self,
        prepared: _PreparedAttestation,
    ) -> ResearchGraphCommand | None:
        graph = self._context.research_graph_store
        candidate = self._command(prepared)
        commands = tuple(graph.commands() or ())
        entrypoint_commands = tuple(
            command
            for command in commands
            if prepared.entrypoint_ref in tuple(getattr(command, "tool_record_refs", ()) or ())
            and _owner(command) == prepared.owner_user_id
        )
        try:
            stored_qro = graph.qro(prepared.qro.qro_id)
        except (KeyError, LookupError):
            stored_qro = None
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"current business attestation QRO lookup failed:{type(exc).__name__}:{exc}"
            ) from exc
        projections = tuple(
            projection
            for projection in tuple(graph.projection_index(owner=prepared.owner_user_id) or ())
            if _enum_text(getattr(projection, "qro_id", "")) == prepared.qro.qro_id
        )
        if stored_qro is None:
            if projections:
                raise PlatformBusinessAttestationError(
                    "business attestation projection exists without its QRO"
                )
            if entrypoint_commands:
                raise PlatformBusinessAttestationError(
                    "different or stale business attestation Graph command already exists"
                )
            return None
        if stored_qro != prepared.qro:
            raise PlatformBusinessAttestationError(
                "business attestation QRO identity contains different or recombined state"
            )
        if len(projections) != 1 or _owner(projections[0]) != prepared.owner_user_id:
            raise PlatformBusinessAttestationError(
                "business attestation QRO must have exactly one owner current projection"
            )
        matches = tuple(
            command
            for command in commands
            if _enum_text(getattr(command, "command_id", "")) == candidate.command_id
        )
        if len(matches) != 1 or len(entrypoint_commands) != 1:
            raise PlatformBusinessAttestationError(
                "business attestation Graph command must be unique for the owner/entrypoint"
            )
        command = matches[0]
        if (
            not self._graph_command_is_exact(prepared=prepared, command=command)
            or _enum_text(getattr(projections[0], "command_id", "")) != candidate.command_id
        ):
            raise PlatformBusinessAttestationError(
                "business attestation Graph head is stale or recombined"
            )
        return command

    def _observe_graph_state(
        self,
        *,
        prepared: _PreparedAttestation,
        command: ResearchGraphCommand,
    ) -> tuple[bool | None, bool | None]:
        """Observe exact history and exact current head without overclaiming.

        The first value reports whether ``command`` is the exact current QRO
        head.  The second reports whether that exact command is present once in
        history.  ``None`` means the corresponding store reads failed, rather
        than silently converting an unobservable durability boundary to false.
        """

        graph = self._context.research_graph_store
        try:
            commands = tuple(graph.commands() or ())
        except Exception:  # noqa: BLE001 - caller needs an explicit unknown state.
            return None, None
        matches = tuple(
            item
            for item in commands
            if _enum_text(getattr(item, "command_id", "")) == command.command_id
        )
        observed = (
            len(matches) == 1
            and matches[0] == command
            and self._graph_command_is_exact(prepared=prepared, command=matches[0])
        )
        try:
            stored_qro = graph.qro(prepared.qro.qro_id)
        except (KeyError, LookupError):
            return False, observed
        except Exception:  # noqa: BLE001 - current projection is unobservable.
            return None, observed
        try:
            projections = tuple(
                projection
                for projection in tuple(
                    graph.projection_index(owner=prepared.owner_user_id) or ()
                )
                if _enum_text(getattr(projection, "qro_id", ""))
                == prepared.qro.qro_id
            )
        except Exception:  # noqa: BLE001 - current projection is unobservable.
            return None, observed
        current = (
            observed
            and stored_qro == prepared.qro
            and len(projections) == 1
            and _owner(projections[0]) == prepared.owner_user_id
            and _enum_text(getattr(projections[0], "command_id", ""))
            == command.command_id
        )
        return bool(current), observed

    def _compile_plan(
        self,
        *,
        prepared: _PreparedAttestation,
        command: ResearchGraphCommand,
    ) -> PlatformBusinessAttestationCompilePlan:
        chain_ref = _chain_ref(prepared.chain, owner=prepared.owner_user_id)
        row_token = prepared.row.lower()
        canonical_refs = _unique_refs(
            f"research_graph_command:{command.command_id}",
            prepared.anchor_ref,
            chain_ref,
            prepared.canonical_business_command_refs,
        )
        return PlatformBusinessAttestationCompilePlan(
            row=prepared.row,
            owner_user_id=prepared.owner_user_id,
            anchor_ref=prepared.anchor_ref,
            entrypoint_ref=prepared.entrypoint_ref,
            pass_name=f"api_platform_business_attestation_{row_token}_qro_to_ir",
            validation_refs=prepared.validation_refs,
            evidence_refs=prepared.evidence_refs,
            environment_lock_ref=f"env:platform_business_attestation:{row_token}:v1",
            permission_ref=f"platform.business_attestation:{row_token}:user_manual",
            deterministic_run_plan_ref=(
                f"runplan:platform_business_attestation:{row_token}:"
                + content_hash(
                    {
                        "qro_ref": prepared.qro.qro_id,
                        "graph_command_ref": command.command_id,
                        "anchor_ref": prepared.anchor_ref,
                        "chain_ref": chain_ref,
                    }
                )
            ),
            rollback_ref=(
                f"rollback:platform_business_attestation:{row_token}:append_only_repair_required"
            ),
            tool_record_refs=(prepared.entrypoint_ref, prepared.anchor_ref, chain_ref),
            node_refs=(
                f"qro:{prepared.qro.qro_id}",
                f"qro_type:{_enum_text(prepared.qro.qro_type)}",
                prepared.anchor_ref,
                chain_ref,
            ),
            canonical_command_refs=canonical_refs,
            lifecycle_refs=prepared.lifecycle_refs,
            rdp_refs=prepared.rdp_refs,
            theory_binding_refs=_tuple_refs(
                getattr(prepared.chain, "theory_binding_refs", ()),
                field=f"{prepared.row} Mathematical Spine theory_binding_refs",
            ),
            consistency_check_refs=_tuple_refs(
                getattr(prepared.chain, "consistency_check_refs", ()),
                field=f"{prepared.row} Mathematical Spine consistency_check_refs",
            ),
            mathematical_spine_chain_refs=(chain_ref,),
            goal_sections=_GOAL_SECTIONS[prepared.row],
        )

    def _preflight_partial_compiler_state(
        self,
        *,
        prepared: _PreparedAttestation,
        command: ResearchGraphCommand,
        graph_exists: bool,
    ) -> None:
        owner = prepared.owner_user_id
        qro_ref = prepared.qro.qro_id
        graph_ref = command.command_id
        chain_ref = _chain_ref(prepared.chain, owner=owner)
        compiler = platform_compiler_snapshot(
            self._compiler_view(),
            owner=owner,
        )
        relevant_irs = tuple(
            ir
            for ir in compiler.irs
            if qro_ref in tuple(getattr(ir, "source_qro_refs", ()) or ())
            or graph_ref in tuple(getattr(ir, "graph_command_refs", ()) or ())
        )
        if len(relevant_irs) > 1:
            raise PlatformBusinessAttestationError(
                "multiple compiler IR records target the business attestation Graph head"
            )
        if relevant_irs:
            ir = relevant_irs[0]
            if (
                _owner(ir) != owner
                or tuple(getattr(ir, "source_qro_refs", ()) or ()) != (qro_ref,)
                or tuple(getattr(ir, "graph_command_refs", ()) or ()) != (graph_ref,)
                or tuple(getattr(ir, "mathematical_spine_chain_refs", ()) or ()) != (chain_ref,)
            ):
                raise PlatformBusinessAttestationError(
                    "partial compiler IR is different or recombined"
                )
        relevant_passes = tuple(
            compiler_pass
            for compiler_pass in compiler.passes
            if qro_ref in tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
            or graph_ref in tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
        )
        if not graph_exists and (relevant_irs or relevant_passes):
            raise PlatformBusinessAttestationError(
                "compiler state exists before its business attestation Graph head"
            )
        if len(relevant_passes) > 1:
            raise PlatformBusinessAttestationError(
                "multiple compiler passes target the business attestation Graph head"
            )
        if relevant_passes:
            compiler_pass = relevant_passes[0]
            if not relevant_irs or (
                _owner(compiler_pass) != owner
                or _enum_text(getattr(compiler_pass, "entry_source", "")) != EntrySource.API.value
                or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ()) != (qro_ref,)
                or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ()) != (graph_ref,)
                or _enum_text(getattr(compiler_pass, "output_ir_ref", ""))
                != _enum_text(getattr(relevant_irs[0], "ir_ref", ""))
            ):
                raise PlatformBusinessAttestationError(
                    "partial compiler pass is different or recombined"
                )

    def _coverage_candidates(self, *, prepared: _PreparedAttestation) -> tuple[Any, ...]:
        view = self._entrypoint_view()
        try:
            records = _entrypoint_records(view, owner=prepared.owner_user_id)
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"business attestation coverage listing failed:{type(exc).__name__}:{exc}"
            ) from exc
        return tuple(
            record
            for record in records
            if _enum_text(getattr(record, "entrypoint_ref", "")) == prepared.entrypoint_ref
        )

    def _validate_persisted_lineage(
        self,
        *,
        prepared: _PreparedAttestation,
        command: ResearchGraphCommand,
        coverage_ref: str,
    ) -> tuple[str, str, str]:
        owner = prepared.owner_user_id
        chain_ref = _chain_ref(prepared.chain, owner=owner)
        plan = self._compile_plan(prepared=prepared, command=command)
        view = self._entrypoint_view()
        compiler = platform_compiler_snapshot(
            self._compiler_view(),
            owner=owner,
        )
        candidates = self._coverage_candidates(prepared=prepared)
        if (
            len(candidates) != 1
            or _enum_text(getattr(candidates[0], "coverage_ref", ""))
            != coverage_ref
        ):
            raise PlatformBusinessAttestationError(
                "business attestation coverage must be the unique owner/entrypoint record"
            )
        try:
            coverage = _entrypoint_coverage(view, coverage_ref, owner=owner)
            decision = view.validate_real_backing(coverage)
            if not bool(getattr(decision, "accepted", False)):
                raise PlatformBusinessAttestationError(
                    "business attestation coverage lacks strict real backing"
                )
            ir_ref = _one(tuple(getattr(coverage, "compiler_ir_refs", ()) or ()), label="business attestation compiler IR ref")
            pass_ref = _one(tuple(getattr(coverage, "compiler_pass_refs", ()) or ()), label="business attestation compiler pass ref")
            compiler_ir = compiler.ir(ir_ref)
            compiler_pass = compiler.compiler_pass(pass_ref)
            stored_chain = self._context.spine_chain_registry.verified_chain(chain_ref, owner=owner)
            stored_qro = self._context.research_graph_store.qro(prepared.qro.qro_id)
        except PlatformBusinessAttestationError:
            raise
        except Exception as exc:
            raise PlatformBusinessAttestationError(
                f"persisted business attestation lineage lookup failed:{type(exc).__name__}:{exc}"
            ) from exc
        expected_coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=EntrySource.API,
            entrypoint_ref=prepared.entrypoint_ref,
            goal_sections=plan.goal_sections,
            qro_refs=(prepared.qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        canonical_refs = tuple(getattr(compiler_ir, "canonical_command_refs", ()) or ())
        sections = tuple(_enum_text(section) for section in tuple(getattr(coverage, "goal_sections", ()) or ()))
        relevant_irs = tuple(
            item
            for item in compiler.irs
            if prepared.qro.qro_id
            in tuple(getattr(item, "source_qro_refs", ()) or ())
            or command.command_id
            in tuple(getattr(item, "graph_command_refs", ()) or ())
        )
        relevant_passes = tuple(
            item
            for item in compiler.passes
            if prepared.qro.qro_id
            in tuple(getattr(item, "input_qro_refs", ()) or ())
            or command.command_id
            in tuple(getattr(item, "graph_command_refs", ()) or ())
        )
        semantic_evidence_refs = tuple(plan.evidence_refs)
        ir_evidence_refs = tuple(
            getattr(compiler_ir, "evidence_refs", ()) or ()
        )
        pass_evidence_refs = tuple(
            getattr(compiler_pass, "evidence_refs", ()) or ()
        )
        coverage_evidence_refs = tuple(
            getattr(coverage, "evidence_refs", ()) or ()
        )
        ir_validation_refs = tuple(
            getattr(compiler_ir, "validation_refs", ()) or ()
        )
        pass_validation_refs = tuple(
            getattr(compiler_pass, "validation_refs", ()) or ()
        )
        coverage_validation_refs = tuple(
            getattr(coverage, "validation_refs", ()) or ()
        )
        receipt_refs = tuple(
            ref
            for ref in ir_validation_refs
            if str(ref).startswith("goal_validation_receipt:")
        )
        # Prefixes classify the persisted proof shape only.  Trust comes from
        # validate_real_backing above, whose production resolver validates the
        # independent evidence record and receipt against this owner/QRO/Graph.
        if (
            _enum_text(getattr(coverage, "coverage_ref", "")) != coverage_ref
            or coverage_ref != expected_coverage_ref
            or _owner(coverage) != owner
            or _enum_text(getattr(coverage, "entry_source", "")) != EntrySource.API.value
            or _enum_text(getattr(coverage, "entrypoint_ref", "")) != prepared.entrypoint_ref
            or sections != plan.goal_sections
            or "§14" in sections
            or tuple(getattr(coverage, "qro_refs", ()) or ()) != (prepared.qro.qro_id,)
            or tuple(getattr(coverage, "research_graph_command_refs", ()) or ()) != (command.command_id,)
            or stored_qro != prepared.qro
            or stored_chain != prepared.chain
            or tuple(getattr(prepared.qro, "mathematical_refs", ()) or ()) != (chain_ref,)
            or tuple(getattr(compiler_ir, "source_qro_refs", ()) or ()) != (prepared.qro.qro_id,)
            or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ()) != (command.command_id,)
            or tuple(getattr(compiler_ir, "mathematical_spine_chain_refs", ()) or ()) != (chain_ref,)
            or _owner(compiler_ir) != owner
            or _enum_text(getattr(compiler_pass, "output_ir_ref", "")) != ir_ref
            or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ()) != (prepared.qro.qro_id,)
            or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ()) != (command.command_id,)
            or _owner(compiler_pass) != owner
            or _enum_text(getattr(compiler_pass, "actor_source", "")) != ActorSource.USER_MANUAL.value
            or _enum_text(getattr(compiler_pass, "entry_source", "")) != EntrySource.API.value
            or tuple(getattr(compiler_pass, "canonical_command_refs", ()) or ()) != canonical_refs
            or tuple(getattr(coverage, "canonical_command_refs", ()) or ()) != canonical_refs
            or bool(getattr(coverage, "silent_mock_fallback_used", False))
            or bool(getattr(coverage, "raw_payload_persisted", False))
            or relevant_irs != (compiler_ir,)
            or relevant_passes != (compiler_pass,)
            or not set(plan.canonical_command_refs).issubset(canonical_refs)
            or tuple(getattr(stored_qro, "evidence_refs", ()) or ())
            != semantic_evidence_refs
            or tuple(getattr(command, "evidence_refs", ()) or ())
            != semantic_evidence_refs
            or ir_evidence_refs != pass_evidence_refs
            or ir_evidence_refs != coverage_evidence_refs
            or len(ir_evidence_refs) != 1
            or not str(ir_evidence_refs[0]).startswith(
                "entrypoint_evidence:"
            )
            or ir_validation_refs != pass_validation_refs
            or ir_validation_refs != coverage_validation_refs
            or len(ir_validation_refs) != len(set(ir_validation_refs))
            or len(receipt_refs) != 1
            or (
                prepared.row == M18
                and ir_validation_refs != (receipt_refs[0],)
            )
            or (
                prepared.row != M18
                and ir_validation_refs
                != (*tuple(plan.validation_refs), receipt_refs[0])
            )
            or not set(plan.lifecycle_refs).issubset(tuple(getattr(coverage, "lifecycle_refs", ()) or ()))
            or not set(plan.rdp_refs).issubset(tuple(getattr(coverage, "rdp_refs", ()) or ()))
            or not set(plan.theory_binding_refs).issubset(tuple(getattr(compiler_ir, "theory_binding_refs", ()) or ()))
            or not set(plan.consistency_check_refs).issubset(tuple(getattr(compiler_ir, "consistency_check_refs", ()) or ()))
        ):
            raise PlatformBusinessAttestationError(
                "persisted business attestation lineage is stale, different, or recombined"
            )
        if not self._graph_command_is_exact(prepared=prepared, command=command):
            raise PlatformBusinessAttestationError(
                "persisted business attestation Graph command is not exact"
            )
        current, observed = self._observe_graph_state(
            prepared=prepared,
            command=command,
        )
        if current is not True or observed is not True:
            raise PlatformBusinessAttestationError(
                "persisted business attestation Graph command is not the exact current head"
            )
        return _exact(ir_ref, field="compiler_ir_ref"), _exact(pass_ref, field="compiler_pass_ref"), coverage_ref

    def record(
        self,
        *,
        owner_user_id: str,
        row: str,
        anchor_ref: str,
    ) -> PlatformBusinessAttestationResult:
        """Serialize and persist or reuse one exact owner/API attestation."""

        with _attestation_transaction(self._context):
            return self._record_locked(
                owner_user_id=owner_user_id,
                row=row,
                anchor_ref=anchor_ref,
            )

    def _record_locked(
        self,
        *,
        owner_user_id: str,
        row: str,
        anchor_ref: str,
    ) -> PlatformBusinessAttestationResult:
        """Persist or reuse one exact current owner/API attestation.

        Business/source, chain, Graph, existing coverage, and partial compiler
        checks all complete before a new Graph command is applied.
        """

        prepared = self.prepare(
            owner_user_id=owner_user_id,
            row=row,
            anchor_ref=anchor_ref,
        )
        command = self._existing_graph_command(prepared) or self._command(prepared)
        coverage_candidates = self._coverage_candidates(prepared=prepared)
        if len(coverage_candidates) > 1:
            raise PlatformBusinessAttestationError(
                "multiple owner business attestations exist for the row entrypoint"
            )
        if coverage_candidates:
            existing = self._existing_graph_command(prepared)
            if existing is None:
                raise PlatformBusinessAttestationError(
                    "coverage exists without the exact current business attestation Graph head"
                )
            coverage_ref = _exact(
                getattr(coverage_candidates[0], "coverage_ref", ""),
                field="entrypoint_coverage_ref",
            )
            ir_ref, pass_ref, coverage_ref = self._validate_persisted_lineage(
                prepared=prepared,
                command=existing,
                coverage_ref=coverage_ref,
            )
            result = self._result(
                prepared=prepared,
                command=existing,
                created=False,
                ir_ref=ir_ref,
                pass_ref=pass_ref,
                coverage_ref=coverage_ref,
            )
            self._validate_current_policy(
                result=result,
                prepared=prepared,
                command=existing,
            )
            return result

        existing_command = self._existing_graph_command(prepared)
        if existing_command is not None:
            command = existing_command
            self._preflight_partial_compiler_state(
                prepared=prepared,
                command=command,
                graph_exists=True,
            )
        else:
            # No Graph/IR/pass/coverage state exists at this entrypoint.  This is
            # the final read-only check before the first append-only mutation.
            self._preflight_partial_compiler_state(
                prepared=prepared,
                command=command,
                graph_exists=False,
            )

        created = False
        if existing_command is None:
            try:
                returned_ref = self._context.research_graph_store.apply(command)
            except Exception as exc:
                graph_current, graph_observed = self._observe_graph_state(
                    prepared=prepared,
                    command=command,
                )
                raise PlatformBusinessAttestationCommitError(
                    f"Research Graph attestation write failed:{type(exc).__name__}:{exc}",
                    phase="research_graph",
                    graph_attestation_current=graph_current,
                    graph_command_ref=command.command_id,
                    graph_command_created=graph_observed,
                ) from exc
            created = True
            if _enum_text(returned_ref) != command.command_id:
                graph_current, graph_observed = self._observe_graph_state(
                    prepared=prepared,
                    command=command,
                )
                raise PlatformBusinessAttestationCommitError(
                    "Research Graph attestation write returned a different command ref",
                    phase="research_graph_ack",
                    graph_attestation_current=graph_current,
                    graph_command_ref=command.command_id,
                    graph_command_created=graph_observed,
                )
            graph_current, graph_observed = self._observe_graph_state(
                prepared=prepared,
                command=command,
            )
            if graph_current is not True or graph_observed is not True:
                raise PlatformBusinessAttestationCommitError(
                    "Research Graph attestation write is not the exact current head",
                    phase="research_graph_verify",
                    graph_attestation_current=graph_current,
                    graph_command_ref=command.command_id,
                    graph_command_created=graph_observed,
                )

        plan = self._compile_plan(prepared=prepared, command=command)
        try:
            compiled = self._context.compile_attestation(prepared.qro, command, plan)
            if not isinstance(compiled, Mapping):
                raise TypeError("compile_attestation result must be a mapping")
            if set(compiled) != {
                "compiler_ir_ref",
                "compiler_pass_ref",
                "entrypoint_coverage_ref",
            }:
                raise ValueError("compile_attestation result must contain exactly the three persisted refs")
            ir_ref = _exact(compiled.get("compiler_ir_ref"), field="compiler_ir_ref")
            pass_ref = _exact(compiled.get("compiler_pass_ref"), field="compiler_pass_ref")
            coverage_ref = _exact(compiled.get("entrypoint_coverage_ref"), field="entrypoint_coverage_ref")
            verified_ir_ref, verified_pass_ref, verified_coverage_ref = self._validate_persisted_lineage(
                prepared=prepared,
                command=command,
                coverage_ref=coverage_ref,
            )
            if (ir_ref, pass_ref, coverage_ref) != (
                verified_ir_ref,
                verified_pass_ref,
                verified_coverage_ref,
            ):
                raise PlatformBusinessAttestationError(
                    "compiler callback refs differ from the persisted attestation lineage"
                )
        except Exception as exc:
            graph_current, graph_observed = self._observe_graph_state(
                prepared=prepared,
                command=command,
            )
            raise PlatformBusinessAttestationCommitError(
                f"compiler/coverage attestation write failed:{type(exc).__name__}:{exc}",
                phase="compiler_coverage",
                graph_attestation_current=graph_current,
                graph_command_ref=command.command_id,
                graph_command_created=graph_observed,
            ) from exc
        result = self._result(
            prepared=prepared,
            command=command,
            created=created,
            ir_ref=ir_ref,
            pass_ref=pass_ref,
            coverage_ref=coverage_ref,
        )
        self._validate_current_policy(
            result=result,
            prepared=prepared,
            command=command,
        )
        return result

    @staticmethod
    def _result(
        *,
        prepared: _PreparedAttestation,
        command: ResearchGraphCommand,
        created: bool,
        ir_ref: str,
        pass_ref: str,
        coverage_ref: str,
    ) -> PlatformBusinessAttestationResult:
        return PlatformBusinessAttestationResult(
            owner_user_id=prepared.owner_user_id,
            row=prepared.row,
            anchor_ref=prepared.anchor_ref,
            entrypoint_ref=prepared.entrypoint_ref,
            qro_ref=prepared.qro.qro_id,
            graph_command_ref=command.command_id,
            graph_command_created=created,
            mathematical_spine_chain_ref=_chain_ref(
                prepared.chain,
                owner=prepared.owner_user_id,
            ),
            compiler_ir_ref=ir_ref,
            compiler_pass_ref=pass_ref,
            entrypoint_coverage_ref=coverage_ref,
        )


def record_platform_business_attestation(
    *,
    context: PlatformBusinessAttestationContext,
    owner_user_id: str,
    row: str,
    anchor_ref: str,
) -> PlatformBusinessAttestationResult:
    """Functional entrypoint with the same owner/row/anchor-only contract."""

    return PlatformBusinessAttestationService(context).record(
        owner_user_id=owner_user_id,
        row=row,
        anchor_ref=anchor_ref,
    )


__all__ = [
    "ENTRYPOINT_REFS",
    "M17",
    "M18",
    "M20",
    "SUPPORTED_ROWS",
    "PlatformBusinessAttestationCommitError",
    "PlatformBusinessAttestationCompilePlan",
    "PlatformBusinessAttestationContext",
    "PlatformBusinessAttestationError",
    "PlatformBusinessAttestationResult",
    "PlatformBusinessAttestationService",
    "record_platform_business_attestation",
]
