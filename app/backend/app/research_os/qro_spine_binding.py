"""Prepare a current QRO for a server-owned Mathematical Spine binding head.

Business QROs are often written before a complete canonical Mathematical Spine
can exist: the chain itself must resolve the persisted business asset.  A later
authenticated binding operation may therefore append a new Research Graph head
for the same QRO identity, provided it changes only the QRO's explicit
Mathematical Spine declaration.  This module performs the read-only preflight;
the caller owns persistence and compiler/coverage writes.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from ..cross_process_lock import acquire_exclusive_fd
from .ref_resolution import is_placeholder_ref
from .spine import (
    ActorSource,
    EntrySource,
    ResearchGraphCommand,
    ResearchGraphDurabilityError,
)


_PROCESS_BINDING_LOCK = threading.RLock()


@contextmanager
def _binding_transaction(research_graph_store: Any):
    """Serialize prepare/write/compile across threads and persistent workers."""

    with _PROCESS_BINDING_LOCK:
        raw_path = getattr(research_graph_store, "path", None)
        if raw_path is None:
            yield
            return
        lock_path = Path(str(raw_path) + ".platform-qro-lineage.lock")
        fd = None
        held = None
        try:
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                os.chmod(lock_path, 0o600)
                try:
                    held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                    refresh = getattr(research_graph_store, "refresh", None)
                    if not callable(refresh):
                        raise TypeError(
                            "persistent Research Graph store lacks refresh()"
                        )
                    refresh()
                except Exception as exc:  # noqa: BLE001 - no write has started.
                    raise QROSpineBindingCommitError(
                        f"platform Spine binding lock/refresh failed:"
                        f"{type(exc).__name__}:{exc}",
                        phase="binding_lock",
                        graph_binding_current=None,
                    ) from exc
            except QROSpineBindingCommitError:
                raise
            except Exception as exc:  # noqa: BLE001 - lock setup failed before observation.
                raise QROSpineBindingCommitError(
                    f"platform Spine binding lock setup failed:"
                    f"{type(exc).__name__}:{exc}",
                    phase="binding_lock",
                    graph_binding_current=None,
                ) from exc
            yield
        finally:
            if held is not None:
                held.release()
            if fd is not None:
                os.close(fd)


class QROSpineBindingError(ValueError):
    """The QRO, projection, command, or chain cannot be safely bound."""


class QROSpineBindingCommitError(RuntimeError):
    """A binding cycle stopped after its current Graph state was observed.

    ``graph_binding_current`` reports only what the supplied Graph store exposed
    after the failure.  ``None`` means lock/setup failure prevented observation.
    It does not claim that compiler or coverage writes were rolled back, because
    those stores are append-only and independently durable.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        graph_binding_current: bool | None,
        graph_command_ref: str = "",
        graph_command_created: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.graph_binding_current = (
            None
            if graph_binding_current is None
            else bool(graph_binding_current)
        )
        self.graph_command_ref = str(graph_command_ref or "")
        self.graph_command_created = (
            None
            if graph_command_created is None
            else bool(graph_command_created)
        )


class QROSpineBindingCompensationBlocked(RuntimeError):
    """A higher-level append-only proof prefix was preserved before failure."""


def _exact(value: Any, *, field: str) -> str:
    raw = str(getattr(value, "value", value) or "")
    token = raw.strip()
    if (
        not token
        or token != raw
        or any(ord(char) < 32 for char in token)
        or is_placeholder_ref(token)
    ):
        raise QROSpineBindingError(f"{field} is not an exact stable ref")
    return token


def _owner(value: Any) -> str:
    return str(
        getattr(
            value,
            "owner_user_id",
            getattr(value, "owner", getattr(value, "recorded_by", "")),
        )
        or ""
    ).strip()


@dataclass(frozen=True)
class CurrentQROSpineBindingPlan:
    owner_user_id: str
    qro_ref: str
    chain_ref: str
    current_qro: Any
    bound_qro: Any
    prior_projection: Any
    prior_command: Any
    already_bound: bool


@dataclass(frozen=True)
class CurrentQROSpineBindingResult:
    owner_user_id: str
    qro_ref: str
    chain_ref: str
    graph_command_ref: str
    graph_command_created: bool
    compiler_ir_ref: str
    compiler_pass_ref: str
    entrypoint_coverage_ref: str


def prepare_current_qro_spine_binding(
    *,
    research_graph_store: Any,
    qro_ref: str,
    owner_user_id: str,
    verified_chain: Any,
) -> CurrentQROSpineBindingPlan:
    """Validate one current QRO head and prepare its exact chain declaration.

    Existing QROs may be mathless or already bound to the same single chain.
    Rebinding a QRO from one non-empty chain to another is rejected: that is a
    new research object/version decision, not a provenance repair.

    The prior command actor is intentionally not required to equal the owner.
    Delegated-reviewer business commands are valid when a row-specific policy
    validates their durable authority.  The new binding command must be written
    by the authenticated owner at the persistence layer.
    """

    owner = _exact(owner_user_id, field="owner_user_id")
    requested_qro_ref = _exact(qro_ref, field="qro_ref")
    chain_ref = _exact(
        getattr(verified_chain, "chain_ref", ""),
        field="verified_chain.chain_ref",
    )
    if _owner(verified_chain) != owner:
        raise QROSpineBindingError("verified Mathematical Spine owner mismatch")

    try:
        qro = research_graph_store.qro(requested_qro_ref)
    except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
        raise QROSpineBindingError(
            f"current QRO is unavailable:{type(exc).__name__}"
        ) from exc
    if _exact(getattr(qro, "qro_id", ""), field="qro.qro_id") != requested_qro_ref:
        raise QROSpineBindingError("current QRO identity mismatch")
    if _owner(qro) != owner:
        raise QROSpineBindingError("current QRO owner mismatch")

    try:
        projections = tuple(
            item
            for item in tuple(
                research_graph_store.projection_index(owner=owner) or ()
            )
            if str(getattr(item, "qro_id", "") or "") == requested_qro_ref
        )
    except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
        raise QROSpineBindingError(
            f"current QRO projection is unavailable:{type(exc).__name__}"
        ) from exc
    if len(projections) != 1:
        raise QROSpineBindingError(
            "QRO must have exactly one owner-scoped current projection"
        )
    projection = projections[0]
    if _owner(projection) != owner:
        raise QROSpineBindingError("current QRO projection owner mismatch")
    command_ref = _exact(
        getattr(projection, "command_id", ""),
        field="projection.command_id",
    )
    try:
        commands = tuple(
            item
            for item in tuple(research_graph_store.commands() or ())
            if str(getattr(item, "command_id", "") or "") == command_ref
        )
    except (OSError, TypeError, ValueError) as exc:
        raise QROSpineBindingError(
            f"current Graph command is unavailable:{type(exc).__name__}"
        ) from exc
    if len(commands) != 1:
        raise QROSpineBindingError(
            "current projection must name exactly one Research Graph command"
        )
    command = commands[0]
    payload = getattr(command, "payload", None)
    embedded = payload.get("qro") if isinstance(payload, dict) else None
    if embedded != qro:
        raise QROSpineBindingError(
            "current projection command carries a stale or recombined QRO"
        )

    declared = tuple(
        _exact(item, field="qro.mathematical_refs")
        for item in tuple(getattr(qro, "mathematical_refs", ()) or ())
    )
    if len(declared) != len(set(declared)):
        raise QROSpineBindingError("QRO mathematical_refs contains duplicates")
    if declared not in ((), (chain_ref,)):
        raise QROSpineBindingError(
            "current QRO is already bound to a different Mathematical Spine chain"
        )

    bound_qro = qro if declared == (chain_ref,) else replace(
        qro,
        mathematical_refs=(chain_ref,),
    )
    if (
        _exact(getattr(bound_qro, "qro_id", ""), field="bound_qro.qro_id")
        != requested_qro_ref
        or getattr(bound_qro, "input_contract", None)
        != getattr(qro, "input_contract", None)
        or getattr(bound_qro, "output_contract", None)
        != getattr(qro, "output_contract", None)
        or str(getattr(bound_qro, "implementation_hash", "") or "")
        != str(getattr(qro, "implementation_hash", "") or "")
    ):
        raise QROSpineBindingError(
            "Mathematical Spine binding changed the QRO business identity"
        )

    return CurrentQROSpineBindingPlan(
        owner_user_id=owner,
        qro_ref=requested_qro_ref,
        chain_ref=chain_ref,
        current_qro=qro,
        bound_qro=bound_qro,
        prior_projection=projection,
        prior_command=command,
        already_bound=declared == (chain_ref,),
    )


def _enum_text(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value or "").strip()


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _plain(child) for key, child in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    return value


def _identity_without_math(qro: Any) -> dict[str, Any]:
    payload = _plain(qro)
    if not isinstance(payload, dict) or "mathematical_refs" not in payload:
        raise QROSpineBindingError("QRO identity is unavailable")
    payload.pop("mathematical_refs")
    return payload


def _command_qro(command: Any) -> Any:
    payload = getattr(command, "payload", None)
    return payload.get("qro") if isinstance(payload, dict) else None


def platform_spine_binding_historical_command_ref(
    command: Any,
    *,
    owner_user_id: str,
    qro_ref: str,
    chain_ref: str,
    entrypoint_ref: str,
) -> str:
    """Validate the exact server-owned binder command and return its history ref."""

    owner = _exact(owner_user_id, field="owner_user_id")
    expected_qro_ref = _exact(qro_ref, field="qro_ref")
    expected_chain_ref = _exact(chain_ref, field="chain_ref")
    expected_entrypoint = _exact(entrypoint_ref, field="entrypoint_ref")
    command_ref = _exact(
        getattr(command, "command_id", ""),
        field="binding_command.command_id",
    )
    qro = _command_qro(command)
    if (
        str(getattr(command, "command_type", "") or "") != "upsert_qro"
        or _enum_text(getattr(command, "source", "")) != EntrySource.API.value
        or _enum_text(getattr(command, "actor_source", ""))
        != ActorSource.USER_MANUAL.value
        or str(getattr(command, "actor", "") or "") != owner
        or _exact(getattr(qro, "qro_id", ""), field="binding_qro.qro_id")
        != expected_qro_ref
        or tuple(getattr(qro, "mathematical_refs", ()) or ())
        != (expected_chain_ref,)
        or tuple(getattr(command, "tool_record_refs", ()) or ())
        != (expected_entrypoint,)
    ):
        raise QROSpineBindingError(
            "binding command is not the exact owner/API/user-manual platform head"
        )
    evidence_refs = tuple(getattr(command, "evidence_refs", ()) or ())
    if (
        len(evidence_refs) != 2
        or evidence_refs[0] != expected_chain_ref
        or evidence_refs[1] == command_ref
    ):
        raise QROSpineBindingError(
            "binding command evidence must name the exact chain and historical command"
        )
    return _exact(
        evidence_refs[1],
        field="binding_command.historical_command_ref",
    )


def _binding_command_is_current(
    *,
    research_graph_store: Any,
    command: Any,
    owner_user_id: str,
    qro_ref: str,
    chain_ref: str,
    entrypoint_ref: str,
) -> bool:
    """Check the exact owner/API binding-head contract without ordering."""

    try:
        historical_ref = platform_spine_binding_historical_command_ref(
            command,
            owner_user_id=owner_user_id,
            qro_ref=qro_ref,
            chain_ref=chain_ref,
            entrypoint_ref=entrypoint_ref,
        )
        current = research_graph_store.qro(qro_ref)
        projections = tuple(
            item
            for item in tuple(
                research_graph_store.projection_index(owner=owner_user_id) or ()
            )
            if str(getattr(item, "qro_id", "") or "") == qro_ref
        )
        if len(projections) != 1:
            return False
        projection = projections[0]
        command_ref = _exact(
            getattr(command, "command_id", ""),
            field="binding_command.command_id",
        )
        if (
            _exact(getattr(projection, "command_id", ""), field="projection.command_id")
            != command_ref
            or _owner(projection) != owner_user_id
            or _command_qro(command) != current
            or _owner(current) != owner_user_id
            or tuple(getattr(current, "mathematical_refs", ()) or ())
            != (chain_ref,)
        ):
            return False
        historical = tuple(
            item
            for item in tuple(research_graph_store.commands() or ())
            if str(getattr(item, "command_id", "") or "") == historical_ref
        )
        if len(historical) != 1:
            return False
        historical_qro = _command_qro(historical[0])
        return (
            str(getattr(historical_qro, "qro_id", "") or "") == qro_ref
            and not tuple(getattr(historical_qro, "mathematical_refs", ()) or ())
            and _identity_without_math(historical_qro)
            == _identity_without_math(current)
        )
    except (KeyError, LookupError, OSError, TypeError, ValueError):
        return False


def current_qro_spine_binding_is_observed(
    *,
    research_graph_store: Any,
    owner_user_id: str,
    qro_ref: str,
    chain_ref: str,
    entrypoint_ref: str,
    graph_command_ref: str,
) -> bool:
    """Observe whether one command ref is still the exact current binder head."""

    try:
        command_ref = _exact(graph_command_ref, field="graph_command_ref")
        matches = tuple(
            item
            for item in tuple(research_graph_store.commands() or ())
            if str(getattr(item, "command_id", "") or "") == command_ref
        )
        if len(matches) != 1:
            return False
        return _binding_command_is_current(
            research_graph_store=research_graph_store,
            command=matches[0],
            owner_user_id=owner_user_id,
            qro_ref=qro_ref,
            chain_ref=chain_ref,
            entrypoint_ref=entrypoint_ref,
        )
    except (KeyError, LookupError, OSError, TypeError, ValueError):
        return False


def _binding_command_is_observed(
    *,
    research_graph_store: Any,
    command: Any,
) -> bool:
    """Return whether the exact command is observable in the Graph history."""

    try:
        command_ref = _exact(
            getattr(command, "command_id", ""),
            field="binding_command.command_id",
        )
        matches = tuple(
            item
            for item in tuple(research_graph_store.commands() or ())
            if str(getattr(item, "command_id", "") or "") == command_ref
        )
        return len(matches) == 1 and matches[0] == command
    except (KeyError, LookupError, OSError, TypeError, ValueError):
        return False


def _record_current_qro_spine_binding_locked(
    *,
    research_graph_store: Any,
    qro_ref: str,
    owner_user_id: str,
    verified_chain: Any,
    entrypoint_ref: str,
    validate_plan: Callable[[CurrentQROSpineBindingPlan], None] | None,
    compile_binding: Callable[[Any, Any], Mapping[str, Any]],
) -> CurrentQROSpineBindingResult:
    """Append or reuse one current owner/API binding head, then compile it.

    The compiler callback receives the exact bound QRO and current binding
    command.  It must return the three persisted refs used by the platform
    lineage policy.  A retry after a compiler failure reuses the current exact
    binding head; it never appends another Graph command merely because a later
    store failed.
    """

    entrypoint = _exact(entrypoint_ref, field="entrypoint_ref")
    if not callable(compile_binding):
        raise QROSpineBindingError("compile_binding must be callable")
    plan = prepare_current_qro_spine_binding(
        research_graph_store=research_graph_store,
        qro_ref=qro_ref,
        owner_user_id=owner_user_id,
        verified_chain=verified_chain,
    )
    if validate_plan is not None:
        if not callable(validate_plan):
            raise QROSpineBindingError("validate_plan must be callable")
        validate_plan(plan)

    command = plan.prior_command
    created = False
    if plan.already_bound:
        if not _binding_command_is_current(
            research_graph_store=research_graph_store,
            command=command,
            owner_user_id=plan.owner_user_id,
            qro_ref=plan.qro_ref,
            chain_ref=plan.chain_ref,
            entrypoint_ref=entrypoint,
        ):
            raise QROSpineBindingError(
                "already-bound QRO is not the exact current platform binding head"
            )
    else:
        historical_ref = _exact(
            getattr(plan.prior_command, "command_id", ""),
            field="historical_command.command_id",
        )
        command = ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=plan.owner_user_id,
            payload={"qro": plan.bound_qro},
            evidence_refs=(plan.chain_ref, historical_ref),
            tool_record_refs=(entrypoint,),
        )
        try:
            apply_if_current = getattr(
                research_graph_store,
                "apply_if_current",
                None,
            )
            if not callable(apply_if_current):
                raise TypeError(
                    "Research Graph store lacks atomic apply_if_current()"
                )
            returned_ref = apply_if_current(historical_ref, command)
        except Exception as exc:  # noqa: BLE001 - report the observed partial boundary.
            durability_unknown = isinstance(exc, ResearchGraphDurabilityError)
            graph_binding_current = (
                None
                if durability_unknown
                else _binding_command_is_current(
                    research_graph_store=research_graph_store,
                    command=command,
                    owner_user_id=plan.owner_user_id,
                    qro_ref=plan.qro_ref,
                    chain_ref=plan.chain_ref,
                    entrypoint_ref=entrypoint,
                )
            )
            graph_command_observed = (
                None
                if durability_unknown
                else _binding_command_is_observed(
                    research_graph_store=research_graph_store,
                    command=command,
                )
            )
            raise QROSpineBindingCommitError(
                f"Research Graph binding write failed:{type(exc).__name__}:{exc}",
                phase="research_graph",
                graph_binding_current=graph_binding_current,
                graph_command_ref=str(getattr(command, "command_id", "") or ""),
                graph_command_created=graph_command_observed,
            ) from exc
        if str(returned_ref or "") != str(command.command_id or ""):
            graph_binding_current = _binding_command_is_current(
                research_graph_store=research_graph_store,
                command=command,
                owner_user_id=plan.owner_user_id,
                qro_ref=plan.qro_ref,
                chain_ref=plan.chain_ref,
                entrypoint_ref=entrypoint,
            )
            raise QROSpineBindingCommitError(
                "Research Graph binding write returned a different command ref",
                phase="research_graph_ack",
                graph_binding_current=graph_binding_current,
                graph_command_ref=str(command.command_id or ""),
                graph_command_created=_binding_command_is_observed(
                    research_graph_store=research_graph_store,
                    command=command,
                ),
            )
        created = True
        if not _binding_command_is_current(
            research_graph_store=research_graph_store,
            command=command,
            owner_user_id=plan.owner_user_id,
            qro_ref=plan.qro_ref,
            chain_ref=plan.chain_ref,
            entrypoint_ref=entrypoint,
        ):
            raise QROSpineBindingCommitError(
                "Research Graph binding write is not the current exact head",
                phase="research_graph_verify",
                graph_binding_current=False,
                graph_command_ref=str(command.command_id or ""),
                graph_command_created=True,
            )

    try:
        compiled = compile_binding(plan.bound_qro, command)
        if not isinstance(compiled, Mapping):
            raise TypeError("compile_binding result must be a mapping")
        compiler_ir_ref = _exact(
            compiled.get("compiler_ir_ref"),
            field="compiler_ir_ref",
        )
        compiler_pass_ref = _exact(
            compiled.get("compiler_pass_ref"),
            field="compiler_pass_ref",
        )
        coverage_ref = _exact(
            compiled.get("entrypoint_coverage_ref"),
            field="entrypoint_coverage_ref",
        )
    except Exception as exc:  # noqa: BLE001 - Graph state must be reported, never hidden.
        raise QROSpineBindingCommitError(
            f"compiler/coverage binding write failed:{type(exc).__name__}:{exc}",
            phase="compiler_coverage",
            graph_binding_current=_binding_command_is_current(
                research_graph_store=research_graph_store,
                command=command,
                owner_user_id=plan.owner_user_id,
                qro_ref=plan.qro_ref,
                chain_ref=plan.chain_ref,
                entrypoint_ref=entrypoint,
            ),
            graph_command_ref=str(getattr(command, "command_id", "") or ""),
            graph_command_created=_binding_command_is_observed(
                research_graph_store=research_graph_store,
                command=command,
            ),
        ) from exc

    return CurrentQROSpineBindingResult(
        owner_user_id=plan.owner_user_id,
        qro_ref=plan.qro_ref,
        chain_ref=plan.chain_ref,
        graph_command_ref=_exact(
            getattr(command, "command_id", ""),
            field="binding_command.command_id",
        ),
        graph_command_created=created,
        compiler_ir_ref=compiler_ir_ref,
        compiler_pass_ref=compiler_pass_ref,
        entrypoint_coverage_ref=coverage_ref,
    )


def record_current_qro_spine_binding(
    *,
    research_graph_store: Any,
    qro_ref: str,
    owner_user_id: str,
    verified_chain: Any,
    entrypoint_ref: str,
    validate_plan: Callable[[CurrentQROSpineBindingPlan], None] | None = None,
    compile_binding: Callable[[Any, Any], Mapping[str, Any]],
) -> CurrentQROSpineBindingResult:
    """Serialize and record one current QRO Mathematical Spine binding."""

    with _binding_transaction(research_graph_store):
        return _record_current_qro_spine_binding_locked(
            research_graph_store=research_graph_store,
            qro_ref=qro_ref,
            owner_user_id=owner_user_id,
            verified_chain=verified_chain,
            entrypoint_ref=entrypoint_ref,
            validate_plan=validate_plan,
            compile_binding=compile_binding,
        )


__all__ = [
    "CurrentQROSpineBindingPlan",
    "CurrentQROSpineBindingResult",
    "QROSpineBindingCompensationBlocked",
    "QROSpineBindingCommitError",
    "QROSpineBindingError",
    "prepare_current_qro_spine_binding",
    "current_qro_spine_binding_is_observed",
    "platform_spine_binding_historical_command_ref",
    "record_current_qro_spine_binding",
]
