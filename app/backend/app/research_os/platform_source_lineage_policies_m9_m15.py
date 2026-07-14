"""Server-derived source-lineage policies for GOAL section 14 rows M9-M15.

The public finalizer accepts only ``owner_user_id``, ``m_row``, and one
business anchor.  This module resolves every proof ref from current typed
stores.  It never accepts QRO, compiler, Mathematical Spine, lifecycle, RAG,
or row-specific refs from a caller.

M13 and M14 deliberately bind the strict RAG usage that predates the reserved
platform-row RAG document.  The finalizer records that usage as
``upstream_business_rag``; the reserved document is not allowed to certify
itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable

from .agent_workflow_closure import AGENT_WORKFLOW_ENTRYPOINT_REF
from .goal_coverage import (
    goal_entrypoint_coverage_identity,
    validate_goal_entrypoint_coverage,
)
from .platform_coverage import PlatformCapabilityRecord, PlatformSpecificRef
from .platform_source_lineage_core import (
    PlatformSourceLineagePolicyResolution,
    UpstreamBusinessRAGBinding,
)
from .platform_typed_sources import (
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)
from .qro_spine_binding import (
    QROSpineBindingError,
    platform_spine_binding_historical_command_ref,
)
from .spine import EntrySource


M9 = "M9"
M10 = "M10"
M11 = "M11"
M12 = "M12"
M13 = "M13"
M14 = "M14"
M15 = "M15"
SUPPORTED_ROWS = (M9, M10, M11, M12, M13, M14, M15)
POLICY_VERSION = "platform_source_lineage_policies_m9_m15.v1"

M9_SPINE_BINDING_ENTRYPOINT_REF = "api:research_os.platform.spine_bindings.m9"
M10_SPINE_BINDING_ENTRYPOINT_REF = "api:research_os.platform.spine_bindings.m10"
M11_SPINE_BINDING_ENTRYPOINT_REF = "api:research_os.platform.spine_bindings.m11"
M12_SPINE_BINDING_ENTRYPOINT_REF = "api:research_os.platform.spine_bindings.m12"
M13_M14_SPINE_BINDING_ENTRYPOINT_REF = (
    "api:research_os.platform.spine_bindings.m13_m14"
)

_SPINE_BINDING_ENTRYPOINT_BY_ROW = {
    M9: M9_SPINE_BINDING_ENTRYPOINT_REF,
    M10: M10_SPINE_BINDING_ENTRYPOINT_REF,
    M11: M11_SPINE_BINDING_ENTRYPOINT_REF,
    M12: M12_SPINE_BINDING_ENTRYPOINT_REF,
    M13: M13_M14_SPINE_BINDING_ENTRYPOINT_REF,
    M14: M13_M14_SPINE_BINDING_ENTRYPOINT_REF,
}

_BUSINESS_ENTRYPOINT_BY_ROW = {
    M9: (EntrySource.API.value, "api:research_os.execution.order_intents"),
    M10: (EntrySource.IDE.value, "ide:strategy.run"),
    M11: (EntrySource.API.value, "api:goal.lifecycle.closure"),
    M12: (EntrySource.API.value, "api:models.gates.approve"),
    M13: (EntrySource.AGENT_SHELL.value, AGENT_WORKFLOW_ENTRYPOINT_REF),
    M14: (EntrySource.AGENT_SHELL.value, AGENT_WORKFLOW_ENTRYPOINT_REF),
}

_AGENT_WORKFLOW_GOAL_SECTIONS = ("§0", "§1", "§5", "§7", "§8")

_DAG_KINDS = (
    ("dag_run_ref", "dag_checkpoint"),
    ("replay_ref", "dag_replay"),
    ("fork_ref", "dag_fork"),
    ("rollback_ref", "dag_rollback"),
)


class PlatformSourceLineagePoliciesM9M15Error(ValueError):
    """One anchor does not resolve to one current owner-scoped lineage."""


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _owner_of(value: Any) -> str:
    return _text(getattr(value, "owner_user_id", getattr(value, "owner", "")))


def _accepted(value: Any) -> bool:
    return bool(getattr(value, "accepted", False))


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _plain(child) for key, child in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(child) for child in value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    return value


def _state_hash(value: Any) -> str:
    """Match the immutable component digest used by Agent workflow receipts."""

    payload = asdict(value) if is_dataclass(value) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: Any) -> bool:
    token = _text(value).lower()
    if token.startswith("sha256:"):
        token = token[7:]
    return len(token) == 64 and all(char in "0123456789abcdef" for char in token)


def _exact_ref(value: Any, *, field: str) -> str:
    raw = str(getattr(value, "value", value) or "")
    ref = raw.strip()
    if not ref or raw != ref or any(ord(char) < 32 for char in ref):
        raise PlatformSourceLineagePoliciesM9M15Error(
            f"{field} must be an exact non-empty ref"
        )
    return ref


def _unique_refs(value: Any, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    refs = tuple(_exact_ref(item, field=field) for item in tuple(value or ()))
    if (not allow_empty and not refs) or len(refs) != len(set(refs)):
        raise PlatformSourceLineagePoliciesM9M15Error(
            f"{field} must be an exact unique ref list"
        )
    return refs


def _require_owner(value: Any, owner: str, *, label: str) -> None:
    if _owner_of(value) != owner:
        raise PlatformSourceLineagePoliciesM9M15Error(f"{label} owner mismatch")


def _require_current(decision: Any, *, label: str) -> None:
    if not _accepted(decision):
        raise PlatformSourceLineagePoliciesM9M15Error(f"{label} is not current")


def _has_methods(value: Any, methods: tuple[str, ...]) -> bool:
    return value is not None and all(callable(getattr(value, name, None)) for name in methods)


@dataclass(frozen=True)
class PlatformSourceLineagePoliciesM9M15Context:
    research_graph_store: Any = None
    compiler_store: Any = None
    spine_chain_registry: Any = None
    execution_closure_registry: Any = None
    execution_order_intent_registry: Any = None
    market_data_registry: Any = None
    validation_methodology_registry: Any = None
    validation_depth_registry: Any = None
    backtest_evidence_registry: Any = None
    asset_lifecycle_registry: Any = None
    lifecycle_transition_registry: Any = None
    model_governance_registry: Any = None
    model_registry: Any = None
    agent_capability_ledger: Any = None
    agent_workflow_closure_registry: Any = None
    rag_index: Any = None
    llm_call_record_store: Any = None
    llm_use_binding_store: Any = None
    onboarding_registry: Any = None
    canonical_spine_ledger: Any = None
    desk_topology_registry: Any = None
    llm_service_owner_user_id: str = ""


@dataclass(frozen=True)
class _CompilerLineage:
    qro: Any
    command: Any
    compiler_ir: Any
    compiler_pass: Any
    entry_source: str
    entrypoint_ref: str

    @property
    def qro_ref(self) -> str:
        return _text(getattr(self.qro, "qro_id", ""))

    @property
    def command_ref(self) -> str:
        return _text(getattr(self.command, "command_id", ""))

    @property
    def ir_ref(self) -> str:
        return _text(getattr(self.compiler_ir, "ir_ref", ""))

    @property
    def pass_ref(self) -> str:
        return _text(getattr(self.compiler_pass, "pass_ref", ""))


def unavailable_platform_source_lineage_policies_m9_m15(
    context: PlatformSourceLineagePoliciesM9M15Context,
) -> dict[str, tuple[str, ...]]:
    """Return exact missing dependency blockers for each row policy."""

    common = (
        ("research_graph_store", context.research_graph_store, ("qro", "commands")),
        (
            "compiler_store",
            context.compiler_store,
            platform_compiler_snapshot_required_methods(context.compiler_store),
        ),
        ("spine_chain_registry", context.spine_chain_registry, ("verified_chain",)),
    )
    row_requirements: dict[str, tuple[tuple[str, Any, tuple[str, ...]], ...]] = {
        M9: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("execution_closure_registry", context.execution_closure_registry, ("receipt", "validate_current")),
            ("execution_order_intent_registry", context.execution_order_intent_registry, ("intent",)),
            ("market_data_registry", context.market_data_registry, ("use_validation", "capability_matrix")),
        ),
        M10: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("validation_methodology_registry", context.validation_methodology_registry, ("methodology", "methodology_binding")),
            ("validation_depth_registry", context.validation_depth_registry, ("depth", "depth_binding")),
            ("backtest_evidence_registry", context.backtest_evidence_registry, ("monitor", "attribution", "validate_current_monitor", "validate_current_attribution")),
        ),
        M11: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("asset_lifecycle_registry", context.asset_lifecycle_registry, ("governed_asset",)),
            ("lifecycle_transition_registry", context.lifecycle_transition_registry, ("transition", "receipts", "validate_current")),
        ),
        M12: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("model_governance_registry", context.model_governance_registry, ("passport", "recertification_record", "current_head_hash")),
            (
                "model_registry",
                context.model_registry,
                ("promotion_gate", "promotion_reviewer_authority_evidence"),
            ),
        ),
        M13: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("agent_capability_ledger", context.agent_capability_ledger, ("record", "current_head", "validate_current")),
            ("agent_workflow_closure_registry", context.agent_workflow_closure_registry, ("receipt", "current_receipt")),
            ("rag_index", context.rag_index, ("strict_usage_for_owner", "validate_current_usage")),
        ),
        M14: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("agent_workflow_closure_registry", context.agent_workflow_closure_registry, ("current_receipt",)),
            ("rag_index", context.rag_index, ("strict_usage_for_owner", "validate_current_usage")),
            ("llm_call_record_store", context.llm_call_record_store, ("resolve_terminal_record",)),
            ("llm_use_binding_store", context.llm_use_binding_store, ("binding_for_terminal", "validate_current")),
            ("onboarding_registry", context.onboarding_registry, ("routing_policy", "credential_pool")),
            ("canonical_spine_ledger", context.canonical_spine_ledger, ("binding", "checks_for")),
        ),
        M15: (
            ("research_graph_store", context.research_graph_store, ("qro", "commands", "projection_index")),
            ("desk_topology_registry", context.desk_topology_registry, ("receipt", "topology", "current_topology", "validate_current_receipt", "validate_topology_current")),
        ),
    }
    unavailable: dict[str, tuple[str, ...]] = {}
    for row in SUPPORTED_ROWS:
        missing = list(
            dict.fromkeys(
                name
                for name, value, methods in (*common, *row_requirements[row])
                if not _has_methods(value, methods)
            )
        )
        if row == M14 and not _text(context.llm_service_owner_user_id):
            missing.append("llm_service_owner_user_id")
        if missing:
            unavailable[row] = tuple(f"missing dependency:{name}" for name in missing)
    return unavailable


class PlatformSourceLineagePoliciesM9M15:
    """Composite resolver implementing all available M9-M15 row policies."""

    def __init__(self, context: PlatformSourceLineagePoliciesM9M15Context) -> None:
        if not isinstance(context, PlatformSourceLineagePoliciesM9M15Context):
            raise TypeError("context must be PlatformSourceLineagePoliciesM9M15Context")
        self._context = context
        self._unavailable = unavailable_platform_source_lineage_policies_m9_m15(context)

    @property
    def registered_rows(self) -> tuple[str, ...]:
        return tuple(row for row in SUPPORTED_ROWS if row not in self._unavailable)

    @property
    def unavailable_rows(self) -> dict[str, tuple[str, ...]]:
        return dict(self._unavailable)

    def _available(self, row: str) -> None:
        if row not in SUPPORTED_ROWS:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"unsupported M9-M15 platform row:{row}"
            )
        blockers = self._unavailable.get(row)
        if blockers:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"platform source-lineage policy {row} is unavailable:" + ",".join(blockers)
            )

    def _qro(self, ref: str, owner: str) -> Any:
        qro = self._context.research_graph_store.qro(ref)
        if _text(getattr(qro, "qro_id", "")) != ref:
            raise PlatformSourceLineagePoliciesM9M15Error("QRO identity mismatch")
        _require_owner(qro, owner, label="QRO")
        return qro

    def _command_for_qro(self, qro: Any, owner: str) -> Any:
        qro_ref = _text(getattr(qro, "qro_id", ""))
        matches = []
        for command in tuple(self._context.research_graph_store.commands() or ()):
            payload = getattr(command, "payload", None)
            command_qro = payload.get("qro") if isinstance(payload, dict) else None
            if (
                _text(getattr(command_qro, "qro_id", "")) == qro_ref
                and command_qro == qro
                and _text(getattr(command, "actor", "")) == owner
            ):
                matches.append(command)
        if len(matches) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "QRO must have exactly one exact owner Research Graph command"
            )
        return matches[0]

    def _select_qro(
        self,
        owner: str,
        predicate: Callable[[Any], bool],
        *,
        label: str,
        command_validator: Callable[[Any, Any], None] | None = None,
    ) -> tuple[Any, Any]:
        matches: dict[str, tuple[Any, Any]] = {}
        for command in tuple(self._context.research_graph_store.commands() or ()):
            payload = getattr(command, "payload", None)
            qro = payload.get("qro") if isinstance(payload, dict) else None
            qro_ref = _text(getattr(qro, "qro_id", ""))
            if (
                not qro_ref
                or _owner_of(qro) != owner
                or not predicate(qro)
            ):
                continue
            if command_validator is None:
                if _text(getattr(command, "actor", "")) != owner:
                    continue
            else:
                command_validator(qro, command)
            current = self._qro(qro_ref, owner)
            if current != qro:
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{label} Research Graph command carries a stale QRO"
                )
            existing = matches.get(qro_ref)
            if existing is not None and existing[1] != command:
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{label} QRO has ambiguous Research Graph commands"
                )
            matches[qro_ref] = (qro, command)
        if len(matches) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} anchor must select exactly one current QRO"
            )
        return next(iter(matches.values()))

    def _validate_m12_delegated_command(
        self,
        qro: Any,
        command: Any,
        *,
        owner: str,
        gate: Any,
        logical_model: str,
    ) -> None:
        inputs = getattr(qro, "input_contract", None)
        outputs = getattr(qro, "output_contract", None)
        if not isinstance(inputs, dict) or not isinstance(outputs, dict):
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M12 delegated reviewer QRO contracts are unavailable"
            )
        reviewer = _exact_ref(
            inputs.get("delegated_actor"), field="M12.delegated_actor"
        )
        grant_ref = _exact_ref(
            inputs.get("delegated_actor_authority_ref"),
            field="M12.delegated_actor_authority_ref",
        )
        grant_hash = _exact_ref(
            inputs.get("delegated_actor_authority_hash"),
            field="M12.delegated_actor_authority_hash",
        )
        gate_evidence = getattr(gate, "evidence", None)
        if (
            _text(getattr(command, "actor", "")) != reviewer
            or _text(getattr(gate, "approver", "")) != reviewer
            or _text(outputs.get("approved_by")) != reviewer
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M12 delegated reviewer actor mismatch"
            )
        if (
            not isinstance(gate_evidence, dict)
            or _text(gate_evidence.get("reviewer_user_id")) != reviewer
            or _text(gate_evidence.get("reviewer_grant_id")) != grant_ref
            or _text(gate_evidence.get("reviewer_grant_record_hash")) != grant_hash
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M12 delegated reviewer gate evidence mismatch"
            )
        try:
            grant = self._context.model_registry.promotion_reviewer_authority_evidence(
                _text(getattr(gate, "gate_id", "")),
                model_id=logical_model,
                reviewer_user_id=reviewer,
                grant_id=grant_ref,
                grant_record_hash=grant_hash,
                permission="approve",
            )
        except Exception as exc:  # noqa: BLE001 - delegated authority validation fails closed.
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M12 delegated reviewer authority is invalid"
            ) from exc
        if (
            _text(getattr(grant, "grant_id", "")) != grant_ref
            or _text(getattr(grant, "gate_id", ""))
            != _text(getattr(gate, "gate_id", ""))
            or _text(getattr(grant, "owner_user_id", "")) != owner
            or _text(getattr(grant, "model_id", "")) != logical_model
            or _text(getattr(grant, "model_asset_ref", ""))
            != _text(getattr(gate, "model_id", ""))
            or getattr(grant, "model_version", None)
            != getattr(gate, "version", None)
            or _text(getattr(grant, "reviewer_user_id", "")) != reviewer
            or "approve"
            not in {_text(item) for item in tuple(getattr(grant, "permissions", ()) or ())}
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M12 delegated reviewer grant does not match the promotion gate"
            )

    def _select_current_projected_qro(
        self,
        owner: str,
        predicate: Callable[[Any], bool],
        *,
        label: str,
    ) -> tuple[Any, Any, Any]:
        """Select the command currently projected for one owner QRO.

        Research Graph commands are append-only, while ``projection_index`` is
        the current per-QRO head.  A deterministic replay can therefore leave
        several valid historical commands for one unchanged QRO; only the
        command named by the current projection may drive compiler/coverage
        lineage.
        """

        matches: dict[str, tuple[Any, Any, Any]] = {}
        for projection in tuple(
            self._context.research_graph_store.projection_index(owner=owner) or ()
        ):
            if _owner_of(projection) != owner:
                continue
            qro_ref = _exact_ref(
                getattr(projection, "qro_id", ""),
                field=f"{label}.projection.qro_id",
            )
            qro = self._qro(qro_ref, owner)
            if not predicate(qro):
                continue
            command_ref = _exact_ref(
                getattr(projection, "command_id", ""),
                field=f"{label}.projection.command_id",
            )
            commands = tuple(
                command
                for command in tuple(
                    self._context.research_graph_store.commands() or ()
                )
                if _text(getattr(command, "command_id", "")) == command_ref
            )
            if len(commands) != 1:
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{label} current projection must bind exactly one Graph command"
                )
            command = commands[0]
            payload = getattr(command, "payload", None)
            command_qro = payload.get("qro") if isinstance(payload, dict) else None
            if (
                _text(getattr(command, "actor", "")) != owner
                or command_qro != qro
            ):
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{label} current projection carries stale QRO/Graph lineage"
                )
            if qro_ref in matches:
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{label} QRO has ambiguous current projections"
                )
            matches[qro_ref] = (qro, command, projection)
        if len(matches) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} anchor must select exactly one current projected QRO"
            )
        return next(iter(matches.values()))

    @staticmethod
    def _qro_identity_without_math(qro: Any, *, label: str) -> dict[str, Any]:
        """Return the complete QRO identity except the post-business math binding."""

        payload = _plain(qro)
        if not isinstance(payload, dict) or "mathematical_refs" not in payload:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} QRO identity is unavailable"
            )
        payload.pop("mathematical_refs")
        return payload

    def _spine_binding_lineage(
        self,
        *,
        owner: str,
        row: str,
        predicate: Callable[[Any], bool],
        business_command_validator: Callable[[Any, Any], None] | None = None,
    ) -> tuple[_CompilerLineage, Any, _CompilerLineage]:
        """Resolve one current owner binding head and one historical business head.

        M9-M14 business QROs are written before their complete Mathematical
        Spine is available.  The server later appends an owner-authenticated
        API command for the same QRO id whose only QRO change is the singleton
        ``mathematical_refs`` binding.  Research Graph history remains
        append-only, so the historical business command is validated
        independently while compiler/coverage lineage follows only the
        current projection-selected binding command.
        """

        binding_entrypoint = _SPINE_BINDING_ENTRYPOINT_BY_ROW[row]
        business_source, business_entrypoint = _BUSINESS_ENTRYPOINT_BY_ROW[row]
        qro, binding_command, projection = self._select_current_projected_qro(
            owner,
            predicate,
            label=row,
        )
        declared = _unique_refs(
            getattr(qro, "mathematical_refs", ()),
            field=f"{row}.binding_qro.mathematical_refs",
        )
        if len(declared) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} current binding QRO must declare exactly one Mathematical Spine chain"
            )
        projection_refs = _unique_refs(
            getattr(projection, "mathematical_refs", ()),
            field=f"{row}.binding_projection.mathematical_refs",
        )
        if (
            projection_refs != declared
            or _text(getattr(projection, "actor", "")) != owner
            or _text(getattr(projection, "source", "")) != EntrySource.API.value
            or _text(getattr(binding_command, "source", ""))
            != EntrySource.API.value
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} current owner projection is not the authenticated API binding head"
            )
        try:
            linked_business_command_ref = (
                platform_spine_binding_historical_command_ref(
                    binding_command,
                    owner_user_id=owner,
                    qro_ref=_text(getattr(qro, "qro_id", "")),
                    chain_ref=declared[0],
                    entrypoint_ref=binding_entrypoint,
                )
            )
        except QROSpineBindingError as exc:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} current binding command provenance mismatch:{exc}"
            ) from exc
        binding_lineage = self._compiler_lineage(
            owner=owner,
            qro=qro,
            command=binding_command,
        )
        if (
            binding_lineage.entry_source != EntrySource.API.value
            or binding_lineage.entrypoint_ref != binding_entrypoint
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} current binding compiler entrypoint mismatch"
            )

        bound_identity = self._qro_identity_without_math(qro, label=row)
        business_lineages: list[_CompilerLineage] = []
        for command in tuple(self._context.research_graph_store.commands() or ()):
            payload = getattr(command, "payload", None)
            historical_qro = payload.get("qro") if isinstance(payload, dict) else None
            if _text(getattr(historical_qro, "qro_id", "")) != binding_lineage.qro_ref:
                continue
            if self._qro_identity_without_math(historical_qro, label=row) != bound_identity:
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{row} QRO history changes fields other than mathematical_refs"
                )
            historical_refs = _unique_refs(
                getattr(historical_qro, "mathematical_refs", ()),
                field=f"{row}.historical_qro.mathematical_refs",
                allow_empty=True,
            )
            if (
                _text(getattr(command, "command_id", ""))
                == binding_lineage.command_ref
            ):
                if historical_qro != qro or historical_refs != declared:
                    raise PlatformSourceLineagePoliciesM9M15Error(
                        f"{row} current binding command carries recombined QRO state"
                    )
                continue
            historical_lineage = self._compiler_lineage(
                owner=owner,
                qro=historical_qro,
                command=command,
            )
            if not historical_refs:
                if (
                    historical_lineage.entry_source != business_source
                    or historical_lineage.entrypoint_ref != business_entrypoint
                    or _text(getattr(command, "source", "")) != business_source
                    or tuple(
                        getattr(
                            historical_lineage.compiler_ir,
                            "mathematical_spine_chain_refs",
                            (),
                        )
                        or ()
                    )
                ):
                    raise PlatformSourceLineagePoliciesM9M15Error(
                        f"{row} historical business compiler lineage mismatch"
                    )
                if business_command_validator is None:
                    if _text(getattr(command, "actor", "")) != owner:
                        raise PlatformSourceLineagePoliciesM9M15Error(
                            f"{row} historical business command owner mismatch"
                        )
                else:
                    business_command_validator(historical_qro, command)
                business_lineages.append(historical_lineage)
                continue
            if (
                historical_qro != qro
                or historical_refs != declared
                or _text(getattr(command, "actor", "")) != owner
                or _text(getattr(command, "source", "")) != EntrySource.API.value
                or historical_lineage.entry_source != EntrySource.API.value
                or historical_lineage.entrypoint_ref != binding_entrypoint
                or tuple(
                    getattr(
                        historical_lineage.compiler_ir,
                        "mathematical_spine_chain_refs",
                        (),
                    )
                    or ()
                )
                != declared
            ):
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{row} unrecognized or recombined binding history"
                )
        if len(business_lineages) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} historical business command is missing or ambiguous; expected exactly one"
            )
        if business_lineages[0].command_ref != linked_business_command_ref:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} binding command does not name the selected historical business command"
            )
        business_lineage = business_lineages[0]
        if row in {M13, M14} and (
            _text(getattr(projection, "actor_source", "")) != "user_manual"
            or _text(getattr(business_lineage.command, "source", ""))
            != EntrySource.AGENT_SHELL.value
            or _text(getattr(business_lineage.command, "actor_source", ""))
            != "agent"
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{row} current projection or historical Agent Shell provenance is inexact"
            )
        return binding_lineage, projection, business_lineage

    @staticmethod
    def _spine_binding_metadata(
        *,
        projection: Any,
        business_lineage: _CompilerLineage,
    ) -> tuple[tuple[str, Any], ...]:
        return (
            (
                "binding_projection_ref",
                _exact_ref(
                    getattr(projection, "projection_ref", ""),
                    field="binding_projection_ref",
                ),
            ),
            ("business_graph_command_ref", business_lineage.command_ref),
            ("business_compiler_ir_ref", business_lineage.ir_ref),
            ("business_compiler_pass_ref", business_lineage.pass_ref),
            ("business_entry_source", business_lineage.entry_source),
            ("business_entrypoint_ref", business_lineage.entrypoint_ref),
        )

    @staticmethod
    def _entrypoint_from_refs(*groups: Any) -> str:
        refs = {
            ref.removeprefix("entrypoint:")
            for group in groups
            for ref in tuple(group or ())
            if _text(ref).startswith("entrypoint:")
        }
        if len(refs) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "compiler lineage must bind exactly one canonical entrypoint"
            )
        return next(iter(refs))

    def _compiler_lineage(
        self,
        *,
        owner: str,
        qro: Any,
        command: Any,
    ) -> _CompilerLineage:
        qro_ref = _text(getattr(qro, "qro_id", ""))
        command_ref = _text(getattr(command, "command_id", ""))
        compiler = platform_compiler_snapshot(
            self._context.compiler_store,
            owner=owner,
        )
        irs = tuple(
            item
            for item in compiler.irs
            if tuple(getattr(item, "source_qro_refs", ()) or ()) == (qro_ref,)
            and tuple(getattr(item, "graph_command_refs", ()) or ()) == (command_ref,)
            and _text(getattr(item, "owner", "")) == owner
        )
        pairs: list[tuple[Any, Any]] = []
        for compiler_ir in irs:
            for compiler_pass in compiler.passes:
                if (
                    _text(getattr(compiler_pass, "output_ir_ref", ""))
                    == _text(getattr(compiler_ir, "ir_ref", ""))
                    and tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
                    == (qro_ref,)
                    and tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
                    == (command_ref,)
                    and _text(getattr(compiler_pass, "actor", "")) == owner
                    and _text(getattr(compiler_pass, "status", "compiled")).lower()
                    == "compiled"
                ):
                    pairs.append((compiler_ir, compiler_pass))
        if len(pairs) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "QRO/Graph must select exactly one current compiler IR/pass pair"
            )
        compiler_ir, compiler_pass = pairs[0]
        entrypoint = self._entrypoint_from_refs(
            getattr(compiler_ir, "canonical_command_refs", ()),
            getattr(compiler_pass, "canonical_command_refs", ()),
        )
        source = _text(getattr(compiler_pass, "entry_source", ""))
        if source not in {item.value for item in EntrySource}:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "compiler pass has an unknown entry source"
            )
        return _CompilerLineage(
            qro=qro,
            command=command,
            compiler_ir=compiler_ir,
            compiler_pass=compiler_pass,
            entry_source=source,
            entrypoint_ref=entrypoint,
        )

    def _compiler_lineage_by_refs(
        self,
        *,
        owner: str,
        qro_ref: str,
        command_ref: str,
        ir_ref: str,
        pass_ref: str,
        entry_source: str,
        entrypoint_ref: str,
    ) -> _CompilerLineage:
        commands = tuple(
            item
            for item in tuple(self._context.research_graph_store.commands() or ())
            if _text(getattr(item, "command_id", "")) == command_ref
        )
        if len(commands) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "workflow closure historical Graph command is missing or ambiguous"
            )
        command = commands[0]
        payload = getattr(command, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        if (
            _text(getattr(qro, "qro_id", "")) != qro_ref
            or _owner_of(qro) != owner
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                "workflow closure historical QRO/Graph identity mismatch"
            )
        lineage = self._compiler_lineage(owner=owner, qro=qro, command=command)
        compiler_ir = lineage.compiler_ir
        compiler_pass = lineage.compiler_pass
        if (
            lineage.ir_ref != ir_ref
            or lineage.pass_ref != pass_ref
            or tuple(getattr(compiler_ir, "source_qro_refs", ()) or ()) != (qro_ref,)
            or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ()) != (command_ref,)
            or _text(getattr(compiler_pass, "output_ir_ref", "")) != ir_ref
            or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ()) != (qro_ref,)
            or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ()) != (command_ref,)
            or _text(getattr(compiler_ir, "owner", "")) != owner
            or _text(getattr(compiler_pass, "actor", "")) != owner
            or lineage.entry_source != entry_source
            or lineage.entrypoint_ref != entrypoint_ref
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                "workflow closure compiler lineage mismatch"
            )
        return _CompilerLineage(
            qro=qro,
            command=command,
            compiler_ir=compiler_ir,
            compiler_pass=compiler_pass,
            entry_source=entry_source,
            entrypoint_ref=entrypoint_ref,
        )

    def _math_chain(
        self,
        *,
        owner: str,
        lineage: _CompilerLineage,
        label: str,
    ) -> Any:
        declared = _unique_refs(
            getattr(lineage.qro, "mathematical_refs", ()),
            field=f"{label}.qro.mathematical_refs",
        )
        if len(declared) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} QRO must bind exactly one Mathematical Spine chain"
            )
        compiler_refs = _unique_refs(
            getattr(lineage.compiler_ir, "mathematical_spine_chain_refs", ()),
            field=f"{label}.compiler_ir.mathematical_spine_chain_refs",
        )
        if compiler_refs != declared:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} QRO/compiler IR Mathematical Spine binding mismatch"
            )
        chain = self._context.spine_chain_registry.verified_chain(
            declared[0], owner=owner
        )
        if (
            _text(getattr(chain, "chain_ref", "")) != declared[0]
            or _text(getattr(chain, "recorded_by", "")) != owner
            or _text(getattr(lineage.compiler_pass, "output_ir_ref", ""))
            != lineage.ir_ref
            or tuple(getattr(lineage.compiler_pass, "input_qro_refs", ()) or ())
            != (lineage.qro_ref,)
            or tuple(getattr(lineage.compiler_pass, "graph_command_refs", ()) or ())
            != (lineage.command_ref,)
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} QRO/IR/pass/Mathematical Spine lineage mismatch"
            )
        return chain

    @staticmethod
    def _metadata(
        *,
        row: str,
        lineage: _CompilerLineage,
        extra: tuple[tuple[str, Any], ...] = (),
    ) -> tuple[tuple[str, Any], ...]:
        return (
            ("policy_version", POLICY_VERSION),
            ("row", row),
            ("graph_command_ref", lineage.command_ref),
            ("compiler_ir_ref", lineage.ir_ref),
            ("compiler_pass_ref", lineage.pass_ref),
            *extra,
        )

    @staticmethod
    def _resolution(
        *,
        row: str,
        anchor: str,
        lineage: _CompilerLineage,
        lifecycle_ref: str,
        math_chain: Any,
        specific_refs: tuple[tuple[str, str], ...],
        primary_rag_asset_ref: str,
        metadata: tuple[tuple[str, Any], ...],
        upstream: UpstreamBusinessRAGBinding | None = None,
    ) -> PlatformSourceLineagePolicyResolution:
        return PlatformSourceLineagePolicyResolution(
            m_row=row,
            anchor_ref=anchor,
            qro_ref=lineage.qro_ref,
            business_entry_source=lineage.entry_source,
            business_entrypoint_ref=lineage.entrypoint_ref,
            lifecycle_ref=_exact_ref(lifecycle_ref, field=f"{row}.lifecycle_ref"),
            math_spine_ref=_exact_ref(
                getattr(math_chain, "chain_ref", ""), field=f"{row}.math_spine_ref"
            ),
            specific_refs=tuple(
                PlatformSpecificRef(key, _exact_ref(ref, field=f"{row}.{key}"))
                for key, ref in specific_refs
            ),
            primary_rag_asset_ref=_exact_ref(
                primary_rag_asset_ref, field=f"{row}.primary_rag_asset_ref"
            ),
            row_policy_metadata=metadata,
            upstream_business_rag=upstream,
        )

    def _resolve_m9(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        closures = self._context.execution_closure_registry
        intents = self._context.execution_order_intent_registry
        market = self._context.market_data_registry
        receipt = closures.receipt(anchor, owner_user_id=owner)
        _require_owner(receipt, owner, label="M9 execution closure")
        if _text(getattr(receipt, "receipt_ref", "")) != anchor:
            raise PlatformSourceLineagePoliciesM9M15Error("M9 execution closure identity mismatch")
        _require_current(
            closures.validate_current(anchor, owner_user_id=owner),
            label="M9 execution closure",
        )
        intent_ref = _exact_ref(getattr(receipt, "order_intent_ref", ""), field="M9.order_intent_ref")
        intent = intents.intent(intent_ref)
        if (
            _text(getattr(intent, "order_intent_ref", "")) != intent_ref
            or _text(getattr(intent, "recorded_by", "")) != owner
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M9 order intent identity/owner mismatch")
        use_ref = _exact_ref(
            getattr(intent, "market_data_use_validation_ref", ""),
            field="M9.market_data_use_validation_ref",
        )
        use = market.use_validation(use_ref, owner_user_id=owner)
        if (
            _text(getattr(use, "validation_ref", "")) != use_ref
            or _text(getattr(use, "recorded_by", "")) != owner
            or not bool(getattr(use, "accepted", False))
            or tuple(getattr(use, "violation_codes", ()) or ())
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M9 market-data use validation is not accepted/current")
        matrix_ref = _exact_ref(
            getattr(use, "capability_matrix_ref", ""), field="M9.market_capability_matrix_ref"
        )
        matrix = market.capability_matrix(matrix_ref, owner_user_id=owner)
        if _text(getattr(matrix, "matrix_ref", "")) != matrix_ref:
            raise PlatformSourceLineagePoliciesM9M15Error("M9 MarketCapabilityMatrix identity mismatch")

        def predicate(qro: Any) -> bool:
            inputs = getattr(qro, "input_contract", None)
            outputs = getattr(qro, "output_contract", None)
            return (
                _text(getattr(qro, "qro_type", "")) == "ExecutionPolicy"
                and isinstance(inputs, dict)
                and isinstance(outputs, dict)
                and _text(inputs.get("order_intent_ref")) == intent_ref
                and _text(inputs.get("market_data_use_validation_ref")) == use_ref
                and _text(outputs.get("execution_policy_ref"))
                == _text(getattr(intent, "execution_policy_ref", ""))
                and _text(outputs.get("risk_policy_ref"))
                == _text(getattr(intent, "risk_policy_ref", ""))
            )

        lineage, projection, business_lineage = self._spine_binding_lineage(
            owner=owner,
            row=M9,
            predicate=predicate,
        )
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M9",
        )
        return self._resolution(
            row=M9,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=anchor,
            math_chain=math,
            specific_refs=(("execution_boundary_ref", anchor), ("market_capability_matrix_ref", matrix_ref)),
            primary_rag_asset_ref=anchor,
            metadata=self._metadata(
                row=M9,
                lineage=lineage,
                extra=(
                    *self._spine_binding_metadata(
                        projection=projection,
                        business_lineage=business_lineage,
                    ),
                    ("order_intent_ref", intent_ref),
                    ("market_data_use_validation_ref", use_ref),
                ),
            ),
        )

    def _resolve_m10(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        evidence = self._context.backtest_evidence_registry
        monitor = evidence.monitor(anchor, owner_user_id=owner)
        _require_owner(monitor, owner, label="M10 Monitor")
        if _text(getattr(monitor, "monitor_ref", "")) != anchor:
            raise PlatformSourceLineagePoliciesM9M15Error("M10 Monitor identity mismatch")
        _require_current(
            evidence.validate_current_monitor(anchor, owner_user_id=owner),
            label="M10 Monitor",
        )
        attribution_ref = _exact_ref(getattr(monitor, "attribution_ref", ""), field="M10.attribution_ref")
        attribution = evidence.attribution(attribution_ref, owner_user_id=owner)
        _require_owner(attribution, owner, label="M10 Attribution")
        _require_current(
            evidence.validate_current_attribution(attribution_ref, owner_user_id=owner),
            label="M10 Attribution",
        )
        qro_ref = _exact_ref(getattr(monitor, "backtest_run_ref", ""), field="M10.backtest_run_ref")
        if _text(getattr(attribution, "backtest_run_ref", "")) != qro_ref:
            raise PlatformSourceLineagePoliciesM9M15Error("M10 Monitor/Attribution backtest mismatch")
        methodology_ref = _exact_ref(
            getattr(attribution, "validation_methodology_ref", ""), field="M10.validation_methodology_ref"
        )
        depth_ref = _exact_ref(
            getattr(attribution, "validation_depth_ref", ""), field="M10.validation_depth_ref"
        )
        methodology = self._context.validation_methodology_registry.methodology(
            methodology_ref, owner_user_id=owner
        )
        methodology_binding = self._context.validation_methodology_registry.methodology_binding(
            methodology_ref, owner_user_id=owner
        )
        depth = self._context.validation_depth_registry.depth(depth_ref, owner_user_id=owner)
        depth_binding = self._context.validation_depth_registry.depth_binding(
            depth_ref, owner_user_id=owner
        )
        if (
            _text(getattr(methodology, "validation_ref", "")) != methodology_ref
            or _text(getattr(depth, "depth_ref", "")) != depth_ref
            or _owner_of(methodology_binding) != owner
            or _owner_of(depth_binding) != owner
            or _text(getattr(methodology_binding, "backtest_run_ref", "")) != qro_ref
            or _text(getattr(depth_binding, "backtest_run_ref", "")) != qro_ref
            or _text(getattr(methodology_binding, "source_run_ref", ""))
            != _text(getattr(depth_binding, "source_run_ref", ""))
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M10 methodology/depth lineage mismatch")
        def predicate(qro: Any) -> bool:
            return (
                _text(getattr(qro, "qro_id", "")) == qro_ref
                and _text(getattr(qro, "qro_type", "")) == "BacktestRun"
            )

        lineage, projection, business_lineage = self._spine_binding_lineage(
            owner=owner,
            row=M10,
            predicate=predicate,
        )
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M10",
        )
        return self._resolution(
            row=M10,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=anchor,
            math_chain=math,
            specific_refs=(
                ("backtest_run_ref", qro_ref),
                ("validation_methodology_ref", methodology_ref),
                ("validation_depth_ref", depth_ref),
                ("attribution_ref", attribution_ref),
                ("monitor_ref", anchor),
            ),
            primary_rag_asset_ref=anchor,
            metadata=self._metadata(
                row=M10,
                lineage=lineage,
                extra=(
                    *self._spine_binding_metadata(
                        projection=projection,
                        business_lineage=business_lineage,
                    ),
                    (
                        "source_run_ref",
                        _text(getattr(methodology_binding, "source_run_ref", "")),
                    ),
                ),
            ),
        )

    def _resolve_m11(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        transitions = self._context.lifecycle_transition_registry
        assets = self._context.asset_lifecycle_registry
        transition = transitions.transition(anchor, owner_user_id=owner)
        _require_owner(transition, owner, label="M11 LifecycleTransition")
        if (
            _text(getattr(transition, "transition_ref", "")) != anchor
            or _text(getattr(transition, "canonical_ref", "")) != anchor
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M11 LifecycleTransition identity mismatch")
        receipts = []
        for receipt in tuple(transitions.receipts(owner_user_id=owner) or ()):
            if anchor not in tuple(getattr(receipt, "transition_refs", ()) or ()):
                continue
            decision = transitions.validate_current(
                _text(getattr(receipt, "receipt_ref", "")), owner_user_id=owner
            )
            if _accepted(decision):
                receipts.append(receipt)
        if len(receipts) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M11 transition must select exactly one current lifecycle receipt"
            )
        receipt = receipts[0]
        transition_refs = tuple(getattr(receipt, "transition_refs", ()) or ())
        asset_refs = tuple(getattr(receipt, "current_asset_refs", ()) or ())
        if len(transition_refs) != len(asset_refs):
            raise PlatformSourceLineagePoliciesM9M15Error("M11 lifecycle receipt arrays are misaligned")
        index = transition_refs.index(anchor)
        asset_ref = _exact_ref(asset_refs[index], field="M11.governed_asset_ref")
        asset = assets.governed_asset(asset_ref, owner_user_id=owner)
        if (
            _text(getattr(asset, "asset_ref", "")) != asset_ref
            or _text(getattr(transition, "after_asset_ref", "")) != asset_ref
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M11 transition/current asset mismatch")
        receipt_ref = _exact_ref(getattr(receipt, "receipt_ref", ""), field="M11.lifecycle_receipt_ref")

        def predicate(qro: Any) -> bool:
            inputs = getattr(qro, "input_contract", None)
            outputs = getattr(qro, "output_contract", None)
            return (
                _text(getattr(qro, "qro_type", "")) == "ValidationDossier"
                and isinstance(inputs, dict)
                and isinstance(outputs, dict)
                and tuple(inputs.get("lifecycle_transition_refs") or ()) == transition_refs
                and _text(outputs.get("lifecycle_closure_receipt_ref")) == receipt_ref
            )

        lineage, projection, business_lineage = self._spine_binding_lineage(
            owner=owner,
            row=M11,
            predicate=predicate,
        )
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M11",
        )
        return self._resolution(
            row=M11,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=receipt_ref,
            math_chain=math,
            specific_refs=(("governed_asset_ref", asset_ref), ("lifecycle_transition_ref", anchor)),
            primary_rag_asset_ref=asset_ref,
            metadata=self._metadata(
                row=M11,
                lineage=lineage,
                extra=(
                    *self._spine_binding_metadata(
                        projection=projection,
                        business_lineage=business_lineage,
                    ),
                    ("lifecycle_receipt_ref", receipt_ref),
                ),
            ),
        )

    def _resolve_m12(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        models = self._context.model_registry
        governance = self._context.model_governance_registry
        gate = models.promotion_gate(anchor, owner_user_id=owner)
        if (
            _text(getattr(gate, "gate_id", "")) != anchor
            or _text(getattr(gate, "decision", "")) != "approved"
            or not bool(getattr(gate, "side_effect_executed", False))
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M12 promotion gate is not approved/current")
        evidence = getattr(gate, "evidence", None)
        if not isinstance(evidence, dict) or _text(evidence.get("owner_user_id")) != owner:
            raise PlatformSourceLineagePoliciesM9M15Error("M12 promotion gate owner evidence mismatch")
        logical_model = _exact_ref(
            evidence.get("logical_model_id"), field="M12.logical_model_id"
        )
        passport_ref = _exact_ref(evidence.get("model_passport_ref"), field="M12.model_passport_ref")
        passport = governance.passport(passport_ref, owner_user_id=owner)
        _require_owner(passport, owner, label="M12 ModelPassport")
        if _text(getattr(passport, "passport_id", "")) != passport_ref:
            raise PlatformSourceLineagePoliciesM9M15Error("M12 ModelPassport identity mismatch")
        recert_refs = _unique_refs(
            evidence.get("model_recertification_record_refs"), field="M12.recertification_refs"
        )
        if len(recert_refs) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M12 gate must bind exactly one current RecertificationRecord"
            )
        recert_ref = recert_refs[0]
        recert = governance.recertification_record(recert_ref, owner_user_id=owner)
        _require_owner(recert, owner, label="M12 RecertificationRecord")
        current_head = governance.current_head_hash(
            recert_ref,
            owner_user_id=owner,
            event_type="model_recertification_recorded",
        )
        head_map = evidence.get("model_recertification_record_head_hashes")
        model_version_ref = _exact_ref(
            getattr(passport, "model_version_ref", ""), field="M12.model_version_ref"
        )
        if (
            _text(getattr(recert, "recertification_record_id", "")) != recert_ref
            or _text(getattr(recert, "model_passport_ref", "")) != passport_ref
            or _text(getattr(recert, "model_version_ref", "")) != model_version_ref
            or not isinstance(head_map, dict)
            or _text(head_map.get(recert_ref)) != _text(current_head)
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M12 recertification lineage is stale/mismatched")

        def predicate(qro: Any) -> bool:
            inputs = getattr(qro, "input_contract", None)
            outputs = getattr(qro, "output_contract", None)
            return (
                _text(getattr(qro, "qro_type", "")) == "Model"
                and isinstance(inputs, dict)
                and isinstance(outputs, dict)
                and _text(inputs.get("gate_id")) == anchor
                and _text(inputs.get("model")) == logical_model
                and _text(inputs.get("model_version_ref")) == model_version_ref
                and _text(outputs.get("gate_id")) == anchor
                and _text(outputs.get("model")) == logical_model
                and _text(outputs.get("model_passport_ref")) == passport_ref
                and _text(outputs.get("decision")) == "approved"
                and _text(outputs.get("side_effect_ref"))
                == _text(getattr(gate, "side_effect_ref", ""))
                and _text(outputs.get("status")) == "promotion_gate_approved"
            )

        lineage, projection, business_lineage = self._spine_binding_lineage(
            owner=owner,
            row=M12,
            predicate=predicate,
            business_command_validator=lambda candidate, graph_command: (
                self._validate_m12_delegated_command(
                    candidate,
                    graph_command,
                    owner=owner,
                    gate=gate,
                    logical_model=logical_model,
                )
            ),
        )
        lifecycle_ref = _exact_ref(getattr(gate, "side_effect_ref", ""), field="M12.lifecycle_ref")
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M12",
        )
        return self._resolution(
            row=M12,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=lifecycle_ref,
            math_chain=math,
            specific_refs=(
                ("model_passport_ref", passport_ref),
                ("model_promotion_ref", anchor),
                ("approval_ref", anchor),
                ("recertification_ref", recert_ref),
            ),
            primary_rag_asset_ref=passport_ref,
            metadata=self._metadata(
                row=M12,
                lineage=lineage,
                extra=(
                    *self._spine_binding_metadata(
                        projection=projection,
                        business_lineage=business_lineage,
                    ),
                    ("model_version_ref", model_version_ref),
                    ("recertification_head_hash", _text(current_head)),
                ),
            ),
        )

    def _workflow_receipt(self, owner: str, receipt: Any, *, label: str) -> Any:
        _require_owner(receipt, owner, label=f"{label} workflow closure")
        receipt_ref = _exact_ref(getattr(receipt, "receipt_ref", ""), field=f"{label}.workflow_receipt_ref")
        workflow = _exact_ref(getattr(receipt, "workflow_id", ""), field=f"{label}.workflow_id")
        current = self._context.agent_workflow_closure_registry.current_receipt(
            owner_user_id=owner, workflow_id=workflow
        )
        if current != receipt:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} workflow closure is not the current owner/workflow head"
            )
        snapshot = getattr(receipt, "snapshot", None)
        if _owner_of(snapshot) != owner or _text(getattr(snapshot, "workflow_id", "")) != workflow:
            raise PlatformSourceLineagePoliciesM9M15Error(f"{label} workflow snapshot owner/id mismatch")
        return snapshot

    def _workflow_lineage(
        self,
        *,
        owner: str,
        snapshot: Any,
        label: str,
    ) -> tuple[
        _CompilerLineage,
        Any,
        _CompilerLineage,
        UpstreamBusinessRAGBinding,
    ]:
        qro_ref = _exact_ref(getattr(getattr(snapshot, "qro", None), "component_ref", ""), field=f"{label}.qro_ref")
        graph_ref = _exact_ref(getattr(getattr(snapshot, "graph_command", None), "component_ref", ""), field=f"{label}.graph_ref")
        ir_ref = _exact_ref(getattr(getattr(snapshot, "compiler_ir", None), "component_ref", ""), field=f"{label}.compiler_ir_ref")
        pass_ref = _exact_ref(getattr(getattr(snapshot, "compiler_pass", None), "component_ref", ""), field=f"{label}.compiler_pass_ref")
        coverage = getattr(snapshot, "entrypoint_coverage", None)
        links = getattr(coverage, "link_map", None)
        if not isinstance(links, dict):
            links = dict(getattr(coverage, "links", ()) or ())
        workflow = _text(getattr(snapshot, "workflow_id", ""))
        expected_links = {
            "entry_source": EntrySource.AGENT_SHELL.value,
            "entrypoint_ref": AGENT_WORKFLOW_ENTRYPOINT_REF,
            "workflow_id": workflow,
            "rag_usage_ref": _text(getattr(getattr(snapshot, "rag_usage", None), "component_ref", "")),
            "qro_ref": qro_ref,
            "graph_command_ref": graph_ref,
            "compiler_ir_ref": ir_ref,
            "compiler_pass_ref": pass_ref,
        }
        coverage_ref = _exact_ref(
            getattr(coverage, "component_ref", ""),
            field=f"{label}.workflow_coverage_ref",
        )
        expected_coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=EntrySource.AGENT_SHELL.value,
            entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
            goal_sections=_AGENT_WORKFLOW_GOAL_SECTIONS,
            qro_refs=(qro_ref,),
            research_graph_command_refs=(graph_ref,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        if (
            links != expected_links
            or coverage_ref != expected_coverage_ref
            or _text(getattr(coverage, "principal_id", "")) != owner
            or _text(getattr(coverage, "status", "")) != "current"
            or not _text(getattr(coverage, "revision", ""))
            or not _valid_sha256(getattr(coverage, "state_hash", ""))
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} historical workflow coverage is not structurally content-bound"
            )
        historical_lineage = self._compiler_lineage_by_refs(
            owner=owner,
            qro_ref=qro_ref,
            command_ref=graph_ref,
            ir_ref=ir_ref,
            pass_ref=pass_ref,
            entry_source=EntrySource.AGENT_SHELL.value,
            entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
        )
        historical_components = (
            (getattr(snapshot, "qro", None), historical_lineage.qro, "current"),
            (
                getattr(snapshot, "graph_command", None),
                historical_lineage.command,
                "current",
            ),
            (
                getattr(snapshot, "compiler_ir", None),
                historical_lineage.compiler_ir,
                "current",
            ),
            (
                getattr(snapshot, "compiler_pass", None),
                historical_lineage.compiler_pass,
                "passed",
            ),
        )
        if any(
            _text(getattr(component, "principal_id", "")) != owner
            or _text(getattr(component, "status", "")) != status
            or _text(getattr(component, "state_hash", "")) != _state_hash(value)
            for component, value, status in historical_components
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} workflow snapshot does not content-bind its historical lineage"
            )
        if (
            tuple(getattr(historical_lineage.qro, "mathematical_refs", ()) or ())
            or _text(getattr(historical_lineage.command, "command_type", ""))
            != "upsert_qro"
            or _text(getattr(historical_lineage.command, "source", ""))
            != EntrySource.AGENT_SHELL.value
            or _text(getattr(historical_lineage.command, "actor_source", ""))
            != "agent"
            or _text(getattr(historical_lineage.command, "actor", "")) != owner
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} historical Agent Shell QRO/Graph provenance is inexact"
            )

        def validate_historical_snapshot(qro: Any, command: Any) -> None:
            if qro != historical_lineage.qro or command != historical_lineage.command:
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"{label} workflow snapshot recombines another historical command"
                )

        binding_lineage, projection, selected_historical = self._spine_binding_lineage(
            owner=owner,
            row=label,
            predicate=lambda qro: _text(getattr(qro, "qro_id", "")) == qro_ref,
            business_command_validator=validate_historical_snapshot,
        )
        if selected_historical != historical_lineage:
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} binder does not link the immutable workflow snapshot"
            )
        usage_ref = _exact_ref(expected_links["rag_usage_ref"], field=f"{label}.rag_usage_ref")
        usage = self._context.rag_index.strict_usage_for_owner(
            usage_ref, owner_user_id=owner
        )
        _require_current(
            self._context.rag_index.validate_current_usage(
                usage_ref, owner_user_id=owner
            ),
            label=f"{label} upstream strict RAG usage",
        )
        if (
            _owner_of(usage) != owner
            or _text(getattr(usage, "workflow_ref", "")) != workflow
            or _text(getattr(usage, "actor", "")) != "agent"
        ):
            raise PlatformSourceLineagePoliciesM9M15Error(
                f"{label} upstream strict RAG owner/workflow/actor mismatch"
            )
        document_refs = _unique_refs(
            tuple(
                _text(getattr(item, "document_id", ""))
                for item in tuple(getattr(usage, "returned_documents", ()) or ())
            ),
            field=f"{label}.upstream_rag.document_refs",
        )
        return (
            binding_lineage,
            projection,
            historical_lineage,
            UpstreamBusinessRAGBinding(
                usage_ref=usage_ref,
                document_refs=document_refs,
            ),
        )

    @staticmethod
    def _checkpoint_refs(dag_record: Any) -> tuple[str, ...]:
        payload = getattr(dag_record, "payload", None)
        if not isinstance(payload, dict):
            raise PlatformSourceLineagePoliciesM9M15Error("M13 DAG checkpoint payload is unavailable")
        nodes = payload.get("nodes")
        indexed = payload.get("node_id_by_task")

        def mapping(rows: Any) -> dict[str, str]:
            if not isinstance(rows, list) or not rows:
                raise PlatformSourceLineagePoliciesM9M15Error("M13 DAG checkpoint rows are unavailable")
            result: dict[str, str] = {}
            for item in rows:
                if not isinstance(item, dict):
                    raise PlatformSourceLineagePoliciesM9M15Error("M13 DAG checkpoint row is malformed")
                task = _exact_ref(item.get("task_id"), field="M13.checkpoint.task_id")
                checkpoint = _exact_ref(item.get("checkpoint_ref"), field="M13.checkpoint_ref")
                if task in result or checkpoint in result.values():
                    raise PlatformSourceLineagePoliciesM9M15Error("M13 DAG checkpoint mapping is ambiguous")
                result[task] = checkpoint
            return result

        node_map = mapping(nodes)
        index_map = mapping(indexed)
        if node_map != index_map:
            raise PlatformSourceLineagePoliciesM9M15Error("M13 DAG checkpoint maps disagree")
        return tuple(node_map.values())

    def _resolve_m13(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        closures = self._context.agent_workflow_closure_registry
        receipt = closures.receipt(anchor, owner_user_id=owner)
        snapshot = self._workflow_receipt(owner, receipt, label="M13")
        lineage, projection, historical_lineage, upstream = self._workflow_lineage(
            owner=owner,
            snapshot=snapshot,
            label="M13",
        )
        workflow = _text(getattr(snapshot, "workflow_id", ""))
        ledger = self._context.agent_capability_ledger
        heads: dict[str, Any] = {}
        for _field, kind in _DAG_KINDS:
            head = ledger.current_head(
                owner_user_id=owner,
                workflow_id=workflow,
                capability_kind=kind,
            )
            _require_current(
                ledger.validate_current(
                    _text(getattr(head, "record_ref", "")), owner_user_id=owner
                ),
                label=f"M13 {kind}",
            )
            stored = ledger.record(
                _text(getattr(head, "record_ref", "")), owner_user_id=owner
            )
            if (
                stored != head
                or _owner_of(head) != owner
                or _text(getattr(head, "workflow_id", "")) != workflow
                or _text(getattr(head, "capability_kind", "")) != kind
            ):
                raise PlatformSourceLineagePoliciesM9M15Error(
                    f"M13 {kind} current head identity mismatch"
                )
            heads[kind] = head
        checkpoints = self._checkpoint_refs(heads["dag_checkpoint"])
        if len(checkpoints) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M13 current DAG run must select exactly one checkpoint anchor"
            )
        source_refs = {
            kind: _exact_ref(getattr(head, "source_ref", ""), field=f"M13.{kind}.source_ref")
            for kind, head in heads.items()
        }
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M13",
        )
        return self._resolution(
            row=M13,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=anchor,
            math_chain=math,
            specific_refs=(
                ("dag_run_ref", source_refs["dag_checkpoint"]),
                ("checkpoint_ref", checkpoints[0]),
                ("replay_ref", source_refs["dag_replay"]),
                ("fork_ref", source_refs["dag_fork"]),
                ("rollback_ref", source_refs["dag_rollback"]),
            ),
            primary_rag_asset_ref=anchor,
            metadata=self._metadata(
                row=M13,
                lineage=lineage,
                extra=(
                    *self._spine_binding_metadata(
                        projection=projection,
                        business_lineage=historical_lineage,
                    ),
                    ("workflow_id", workflow),
                    ("workflow_coverage_ref", _text(getattr(getattr(snapshot, "entrypoint_coverage", None), "component_ref", ""))),
                ),
            ),
            upstream=upstream,
        )

    def _resolve_m14(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        if not anchor.startswith("llm_gateway:"):
            raise PlatformSourceLineagePoliciesM9M15Error("M14 anchor must be a canonical LLM gateway ref")
        call_id = _exact_ref(anchor.removeprefix("llm_gateway:"), field="M14.terminal_call_id")
        terminal = self._context.llm_call_record_store.resolve_terminal_record(call_id, owner)
        binding = self._context.llm_use_binding_store.binding_for_terminal(
            call_id, owner_user_id=owner
        )
        _require_current(
            self._context.llm_use_binding_store.validate_current(
                _text(getattr(binding, "binding_ref", "")), owner_user_id=owner
            ),
            label="M14 LLM use binding",
        )
        if (
            _owner_of(terminal) != owner
            or _owner_of(binding) != owner
            or _text(getattr(terminal, "call_id", "")) != call_id
            or _text(getattr(terminal, "record_kind", "")) != "terminal"
            or _text(getattr(terminal, "status", "")) != "ok"
            or _text(getattr(binding, "terminal_call_id", "")) != call_id
            or _text(getattr(binding, "terminal_status", "")) != "ok"
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M14 terminal/use-binding identity mismatch")
        workflow = _exact_ref(getattr(binding, "workflow_id", ""), field="M14.workflow_id")
        receipt = self._context.agent_workflow_closure_registry.current_receipt(
            owner_user_id=owner, workflow_id=workflow
        )
        snapshot = self._workflow_receipt(owner, receipt, label="M14")
        terminal_refs = tuple(
            _text(getattr(item, "component_ref", ""))
            for item in tuple(getattr(snapshot, "terminal_calls", ()) or ())
        )
        binding_refs = tuple(
            _text(getattr(item, "component_ref", ""))
            for item in tuple(getattr(snapshot, "llm_use_bindings", ()) or ())
        )
        if terminal_refs.count(call_id) != 1 or binding_refs.count(
            _text(getattr(binding, "binding_ref", ""))
        ) != 1:
            raise PlatformSourceLineagePoliciesM9M15Error(
                "M14 terminal/use binding is absent or ambiguous in workflow closure"
            )
        lineage, projection, historical_lineage, upstream = self._workflow_lineage(
            owner=owner,
            snapshot=snapshot,
            label="M14",
        )
        service_owner = _exact_ref(
            self._context.llm_service_owner_user_id, field="M14.llm_service_owner_user_id"
        )
        routing_ref = _exact_ref(getattr(binding, "routing_policy_ref", ""), field="M14.routing_policy_ref")
        pool_ref = _exact_ref(getattr(binding, "credential_pool_ref", ""), field="M14.credential_pool_ref")
        routing = self._context.onboarding_registry.routing_policy(
            routing_ref, owner_user_id=service_owner
        )
        pool = self._context.onboarding_registry.credential_pool(
            pool_ref, owner_user_id=service_owner
        )
        if (
            _text(getattr(binding, "service_principal_ref", "")) != service_owner
            or _text(getattr(routing, "routing_policy_id", "")) != routing_ref
            or _text(getattr(routing, "credential_pool_ref", "")) != pool_ref
            or _text(getattr(pool, "pool_id", "")) != pool_ref
            or _text(getattr(pool, "owner", "")) != service_owner
            or _text(getattr(pool, "provider_id", "")) != _text(getattr(terminal, "provider", ""))
            or _text(getattr(terminal, "auth_ref", "")) not in tuple(getattr(pool, "auth_refs", ()) or ())
            or _text(getattr(terminal, "auth_ref", "")) in tuple(getattr(pool, "revoked_refs", ()) or ())
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M14 gateway/routing/pool lineage mismatch")
        tib_ref = _exact_ref(
            getattr(lineage.qro, "theory_implementation_binding", ""),
            field="M14.theory_implementation_binding_ref",
        )
        tib = self._context.canonical_spine_ledger.binding(tib_ref, owner=owner)
        checks = tuple(self._context.canonical_spine_ledger.checks_for(tib_ref, owner=owner) or ())
        if (
            _text(getattr(tib, "binding_id", "")) != tib_ref
            or _text(getattr(tib, "consistency_verdict", "")) != "server_property_check"
            or not checks
            or any(
                _text(item.get("binding_id") if isinstance(item, dict) else getattr(item, "binding_id", "")) != tib_ref
                or _text(item.get("result") if isinstance(item, dict) else getattr(item, "result", "")) != "pass"
                for item in checks
            )
        ):
            raise PlatformSourceLineagePoliciesM9M15Error("M14 canonical TIB/check lineage mismatch")
        binding_ref = _exact_ref(getattr(binding, "binding_ref", ""), field="M14.llm_use_binding_ref")
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M14",
        )
        receipt_ref = _exact_ref(getattr(receipt, "receipt_ref", ""), field="M14.lifecycle_ref")
        return self._resolution(
            row=M14,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=receipt_ref,
            math_chain=math,
            specific_refs=(
                ("llm_gateway_ref", anchor),
                ("model_routing_policy_ref", routing_ref),
                ("credential_pool_ref", pool_ref),
                ("theory_implementation_binding_ref", tib_ref),
            ),
            primary_rag_asset_ref=anchor,
            metadata=self._metadata(
                row=M14,
                lineage=lineage,
                extra=(
                    *self._spine_binding_metadata(
                        projection=projection,
                        business_lineage=historical_lineage,
                    ),
                    ("workflow_id", workflow),
                    ("workflow_coverage_ref", _text(getattr(getattr(snapshot, "entrypoint_coverage", None), "component_ref", ""))),
                    ("llm_use_binding_ref", binding_ref),
                ),
            ),
            upstream=upstream,
        )

    def _resolve_m15(self, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        topologies = self._context.desk_topology_registry
        receipt = topologies.receipt(anchor, owner_user_id=owner)
        _require_owner(receipt, owner, label="M15 topology receipt")
        if _text(getattr(receipt, "receipt_ref", "")) != anchor:
            raise PlatformSourceLineagePoliciesM9M15Error("M15 topology receipt identity mismatch")
        _require_current(
            topologies.validate_current_receipt(receipt, owner_user_id=owner),
            label="M15 topology receipt",
        )
        topology_ref = _exact_ref(getattr(receipt, "topology_ref", ""), field="M15.topology_ref")
        topology = topologies.topology(topology_ref, owner_user_id=owner)
        current = topologies.current_topology(owner_user_id=owner)
        _require_current(
            topologies.validate_topology_current(topology, owner_user_id=owner),
            label="M15 topology",
        )
        if topology != current or _text(getattr(topology, "topology_ref", "")) != topology_ref:
            raise PlatformSourceLineagePoliciesM9M15Error("M15 topology is not the current owner revision")

        def predicate(qro: Any) -> bool:
            inputs = getattr(qro, "input_contract", None)
            outputs = getattr(qro, "output_contract", None)
            return (
                _text(getattr(qro, "qro_type", "")) == "ValidationDossier"
                and isinstance(inputs, dict)
                and isinstance(outputs, dict)
                and _text(inputs.get("topology_ref")) == topology_ref
                and _text(outputs.get("desk_topology_receipt_ref")) == anchor
                and _text(outputs.get("status")) == "desk_topology_current"
            )

        qro, command, projection = self._select_current_projected_qro(
            owner,
            predicate,
            label="M15",
        )
        lineage = self._compiler_lineage(owner=owner, qro=qro, command=command)
        projection_ref = _exact_ref(
            getattr(projection, "projection_ref", ""),
            field="M15.typed_canvas_projection_ref",
        )
        math = self._math_chain(
            owner=owner,
            lineage=lineage,
            label="M15",
        )
        return self._resolution(
            row=M15,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=anchor,
            math_chain=math,
            specific_refs=(("typed_canvas_projection_ref", projection_ref),),
            primary_rag_asset_ref=topology_ref,
            metadata=self._metadata(row=M15, lineage=lineage, extra=(("topology_ref", topology_ref),)),
        )

    def resolve(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        owner = _exact_ref(owner_user_id, field="owner_user_id")
        row = _text(m_row)
        anchor = _exact_ref(anchor_ref, field="anchor_ref")
        self._available(row)
        resolver = {
            M9: self._resolve_m9,
            M10: self._resolve_m10,
            M11: self._resolve_m11,
            M12: self._resolve_m12,
            M13: self._resolve_m13,
            M14: self._resolve_m14,
            M15: self._resolve_m15,
        }[row]
        return resolver(owner, anchor)

    def semantic_violations(
        self,
        resolution: PlatformSourceLineagePolicyResolution,
        *,
        owner_user_id: str,
        business_coverage: Any,
        capability_record: PlatformCapabilityRecord,
        rag_document: Any,
    ) -> tuple[str, ...]:
        """Re-resolve current state and bind exact coverage/compiler/RAG metadata."""

        row = _text(getattr(resolution, "m_row", ""))
        try:
            current = self.resolve(
                owner_user_id=owner_user_id,
                m_row=row,
                anchor_ref=_text(getattr(resolution, "anchor_ref", "")),
            )
        except Exception as exc:  # noqa: BLE001 - semantic checks fail closed.
            return (f"{row} current policy re-resolution failed:{type(exc).__name__}",)
        violations: list[str] = []
        if current != resolution:
            violations.append(f"{row} policy resolution is stale or recombined")
        metadata = dict(resolution.row_policy_metadata)
        expected_coverage = {
            "qro_refs": (resolution.qro_ref,),
            "research_graph_command_refs": (metadata.get("graph_command_ref"),),
            "compiler_ir_refs": (metadata.get("compiler_ir_ref"),),
            "compiler_pass_refs": (metadata.get("compiler_pass_ref"),),
        }
        for field, expected in expected_coverage.items():
            if tuple(getattr(business_coverage, field, ()) or ()) != expected:
                violations.append(f"{row} business coverage {field} mismatch")
        if (
            _text(getattr(business_coverage, "recorded_by", "")) != owner_user_id
            or _text(getattr(business_coverage, "entry_source", ""))
            != resolution.business_entry_source
            or _text(getattr(business_coverage, "entrypoint_ref", ""))
            != resolution.business_entrypoint_ref
        ):
            violations.append(f"{row} business coverage owner/entrypoint mismatch")
        if row in {M13, M14}:
            try:
                coverage_decision = validate_goal_entrypoint_coverage(
                    business_coverage
                )
                sections = tuple(
                    _text(section)
                    for section in tuple(
                        getattr(business_coverage, "goal_sections", ()) or ()
                    )
                )
                expected_identity = goal_entrypoint_coverage_identity(
                    entry_source=resolution.business_entry_source,
                    entrypoint_ref=resolution.business_entrypoint_ref,
                    goal_sections=sections,
                    qro_refs=(resolution.qro_ref,),
                    research_graph_command_refs=(metadata.get("graph_command_ref"),),
                    compiler_ir_refs=(metadata.get("compiler_ir_ref"),),
                    compiler_pass_refs=(metadata.get("compiler_pass_ref"),),
                )
                if (
                    not coverage_decision.accepted
                    or not sections
                    or len(sections) != len(set(sections))
                    or "§14" in sections
                    or _text(getattr(business_coverage, "coverage_ref", ""))
                    != expected_identity
                ):
                    violations.append(
                        f"{row} current binder coverage is not strict non-§14 content-bound evidence"
                    )
            except (AttributeError, TypeError, ValueError):
                violations.append(
                    f"{row} current binder coverage is not strict non-§14 content-bound evidence"
                )
        actual_specifics = tuple(
            (_text(item.key), _text(item.ref)) for item in capability_record.specific_refs
        )
        expected_specifics = tuple(
            (_text(item.key), _text(item.ref)) for item in resolution.specific_refs
        )
        if (
            _text(capability_record.qro_ref) != resolution.qro_ref
            or _text(capability_record.lifecycle_ref) != resolution.lifecycle_ref
            or _text(capability_record.math_spine_ref) != resolution.math_spine_ref
            or actual_specifics != expected_specifics
        ):
            violations.append(f"{row} capability refs do not equal the server policy")
        rag_metadata = getattr(rag_document, "metadata", None)
        row_policy = rag_metadata.get("row_policy") if isinstance(rag_metadata, dict) else None
        if row_policy != _plain(metadata):
            violations.append(f"{row} final RAG row-policy metadata mismatch")
        if (
            _text(getattr(rag_document, "asset_ref", ""))
            != resolution.primary_rag_asset_ref
            or owner_user_id
            not in tuple(
                getattr(getattr(rag_document, "permission", None), "allowed_users", ()) or ()
            )
            or resolution.primary_rag_asset_ref
            not in tuple(
                getattr(getattr(rag_document, "permission", None), "allowed_assets", ()) or ()
            )
        ):
            violations.append(f"{row} final RAG asset/permission mismatch")
        binding = resolution.upstream_business_rag
        if binding is not None:
            upstream = rag_metadata.get("upstream_business_rag") if isinstance(rag_metadata, dict) else None
            if upstream != {
                "usage_ref": binding.usage_ref,
                "document_refs": list(binding.document_refs),
                "role": "upstream_business_context",
            }:
                violations.append(f"{row} upstream RAG metadata mismatch")
        return tuple(violations)


def build_platform_source_lineage_policies_m9_m15(
    context: PlatformSourceLineagePoliciesM9M15Context,
) -> PlatformSourceLineagePoliciesM9M15:
    """Build the composite M9-M15 policy resolver without writing any store."""

    return PlatformSourceLineagePoliciesM9M15(context)


__all__ = [
    "M9",
    "M9_SPINE_BINDING_ENTRYPOINT_REF",
    "M10",
    "M10_SPINE_BINDING_ENTRYPOINT_REF",
    "M11",
    "M11_SPINE_BINDING_ENTRYPOINT_REF",
    "M12",
    "M12_SPINE_BINDING_ENTRYPOINT_REF",
    "M13",
    "M14",
    "M13_M14_SPINE_BINDING_ENTRYPOINT_REF",
    "M15",
    "POLICY_VERSION",
    "PlatformSourceLineagePoliciesM9M15",
    "PlatformSourceLineagePoliciesM9M15Context",
    "PlatformSourceLineagePoliciesM9M15Error",
    "build_platform_source_lineage_policies_m9_m15",
    "unavailable_platform_source_lineage_policies_m9_m15",
]
