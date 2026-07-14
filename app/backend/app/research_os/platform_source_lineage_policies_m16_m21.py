"""Server-owned source-lineage policies for GOAL section 14 rows M16-M21.

The public finalizer accepts one owner-scoped business anchor.  This module
derives every other ref from current typed stores and from one strictly backed
non-section-14 entrypoint coverage.  It deliberately does not search arbitrary
serialized objects for ref-shaped strings.

Canonical anchors:

* M16: current ``shared_asset_ref``
* M17: current guarded copy-trade ``submission_ref``
* M18: current canonical ``ConsistencyCheck`` ref
* M19: current ``tutorial_asset_ref``
* M20: pre-existing terminal account ``HALT`` ref
* M21: current IDE strategy ref for new writes; governed asset ref for legacy

M20 is read-only here.  The resolver consumes durable HALT evidence and never
starts, drains, finalizes, resumes, or otherwise mutates an emergency action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import Enum
from typing import Any, Callable, Iterable

from ..ide.service import StrategyFile
from ..lineage.ids import content_hash
from .goal_coverage import (
    goal_entrypoint_coverage_identity,
    validate_goal_entrypoint_coverage,
)
from .platform_coverage import PlatformCapabilityRecord, PlatformSpecificRef
from .platform_business_history_m16_m21 import (
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
)
from .platform_source_lineage_core import PlatformSourceLineagePolicyResolution
from .platform_typed_sources import (
    PlatformCompilerSnapshot,
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)
from .ref_resolution import is_placeholder_ref


M16 = "M16"
M17 = "M17"
M18 = "M18"
M19 = "M19"
M20 = "M20"
M21 = "M21"

SUPPORTED_ROWS = (M16, M17, M18, M19, M20, M21)

_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    M16: ("api:research_os.platform.business_attestations.m16",),
    M17: ("api:research_os.platform.business_attestations.m17",),
    M18: ("api:research_os.platform.business_attestations.m18",),
    M19: ("api:research_os.platform.business_attestations.m19",),
    M20: ("api:research_os.platform.business_attestations.m20",),
    M21: ("api:research_os.platform.business_attestations.m21",),
}

_HISTORICAL_BUSINESS_ENTRYPOINTS: dict[str, tuple[str, str]] = {
    M16: ("api", "api:sharing.publish"),
    M19: ("api", "api:research_os.teaching.assets"),
    M21: ("api", "api:strategies.templates.fork_to_ide"),
}

_POST_BUSINESS_ATTESTATION_ROWS = frozenset(_HISTORICAL_BUSINESS_ENTRYPOINTS)

_POST_BUSINESS_BINDING_GOAL_SECTIONS: dict[str, tuple[str, ...]] = {
    M16: ("§0", "§1", "§6", "§8", "§16"),
    M19: ("§0", "§1", "§6", "§8", "§17"),
    M21: ("§0", "§1", "§6", "§8"),
}

_ENTRY_SOURCES = {
    M16: "api",
    M17: "api",
    M18: "api",
    M19: "api",
    M20: "api",
    M21: "api",
}

_DIRECT_BUSINESS_ATTESTATION_ROWS = frozenset((M17, M18, M20))

_DIRECT_GOAL_SECTIONS: dict[str, tuple[str, ...]] = {
    M17: ("§0", "§1", "§6", "§8", "§16"),
    M18: ("§0", "§1", "§6", "§7", "§8", "§17"),
    M20: ("§0", "§1", "§8", "§16"),
}

_DIRECT_OUTPUT_CONTRACTS: dict[str, dict[str, str]] = {
    M17: {"status": "guarded_submission_recorded"},
    M18: {"status": "current_code_package_attested"},
    M20: {"status": "halted_security_controls_verified"},
}

_DIRECT_CONTRACT_KEYS: dict[str, tuple[str, ...]] = {
    M17: (
        "submission_ref",
        "copy_trade_subscription_ref",
        "runtime_promotion_ref",
        "risk_gate_ref",
        "execution_audit_ref",
    ),
    M18: (
        "canonical_code_command_ref",
        "consistency_check_ref",
        "rdp_package_ref",
    ),
    M20: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
}


class PlatformSourceLineagePolicyM16M21Error(ValueError):
    """One anchor does not resolve to a unique current M16-M21 lineage."""


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _enum_text(value: Any) -> str:
    return _text(getattr(value, "value", value))


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
        raise PlatformSourceLineagePolicyM16M21Error(
            f"{field} is not an exact stable ref"
        )
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    if prefixes and not token.startswith(prefixes):
        raise PlatformSourceLineagePolicyM16M21Error(
            f"{field} does not use its canonical prefix"
        )
    return token


def _owner(value: Any) -> str:
    return _text(
        getattr(
            value,
            "owner_user_id",
            getattr(value, "owner", getattr(value, "user_id", "")),
        )
    )


def _one(values: Iterable[Any], *, label: str) -> Any:
    matches = tuple(values)
    if len(matches) != 1:
        raise PlatformSourceLineagePolicyM16M21Error(
            f"{label} must resolve to exactly one current record"
        )
    return matches[0]


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlatformSourceLineagePolicyM16M21Error(f"{field} is malformed")
    return value


def _tuple_refs(value: Any, *, field: str, required: bool = True) -> tuple[str, ...]:
    raw = tuple(value or ())
    refs = tuple(_exact(item, field=field) for item in raw)
    if required and not refs:
        raise PlatformSourceLineagePolicyM16M21Error(f"{field} is required")
    if len(refs) != len(set(refs)):
        raise PlatformSourceLineagePolicyM16M21Error(
            f"{field} contains duplicate refs"
        )
    return refs


def _specific_map(record: PlatformCapabilityRecord) -> dict[str, str]:
    return {_text(item.key): _text(item.ref) for item in record.specific_refs}


def _contract_ref(
    qro: Any,
    key: str,
    *,
    prefix: str | tuple[str, ...] = (),
) -> str:
    values: list[str] = []
    for name in ("input_contract", "output_contract"):
        contract = _mapping(getattr(qro, name, None), field=f"QRO {name}")
        if key in contract:
            values.append(
                _exact(contract[key], field=f"QRO {name}.{key}", prefix=prefix)
            )
    if not values or len(set(values)) != 1:
        raise PlatformSourceLineagePolicyM16M21Error(
            f"QRO contracts must bind one exact {key}"
        )
    return values[0]


def _require_contract_refs(qro: Any, expected: dict[str, str]) -> None:
    for key, ref in expected.items():
        if _contract_ref(qro, key) != ref:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"QRO contract {key} mismatch"
            )


def _specific_refs(
    keys: tuple[str, ...],
    values: tuple[str, ...],
) -> tuple[PlatformSpecificRef, ...]:
    return tuple(
        PlatformSpecificRef(key, value)
        for key, value in zip(keys, values, strict=True)
    )


def _refresh_if_available(value: Any) -> None:
    refresh = getattr(value, "refresh", None)
    if callable(refresh):
        refresh()


def _unique_refs(*groups: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for group in groups:
        if group is None:
            continue
        values = (
            group
            if isinstance(group, (tuple, list, set, frozenset))
            else (group,)
        )
        for value in values:
            ref = _exact(value, field="derived reference")
            if ref not in refs:
                refs.append(ref)
    return tuple(refs)


@dataclass(frozen=True)
class _BusinessLineage:
    coverage: Any
    qro: Any
    command: Any
    compiler_ir: Any
    compiler_pass: Any
    chain: Any


@dataclass(frozen=True)
class _HistoricalBusinessLineage:
    qro: Any
    command: Any
    compiler_ir: Any
    compiler_pass: Any
    entry_source: str
    entrypoint_ref: str
    coverage: Any = None


@dataclass(frozen=True)
class _PostBusinessAttestationLineage:
    current: _BusinessLineage
    projection: Any
    historical: _HistoricalBusinessLineage


EntrypointViewFactory = Callable[[], Any]
QROPredicate = Callable[[Any, Any], bool]


@dataclass(frozen=True)
class PlatformSourceLineagePoliciesM16M21Context:
    """Typed stores needed to resolve the six current business rows."""

    research_graph_store: Any
    compiler_store: Any
    entrypoint_registry: Any
    spine_chain_registry: Any
    asset_lifecycle_registry: Any
    sharing_service: Any
    copy_trade_service: Any
    runtime_promotion_registry: Any
    follower_risk_state_store: Any
    execution_order_submission_registry: Any
    execution_order_intent_registry: Any
    canonical_spine_ledger: Any
    rdp_store: Any
    teaching_asset_registry: Any
    onboarding_registry: Any
    llm_call_record_store: Any
    account_halt_barrier: Any
    llm_service_owner_user_id: str = ""
    research_graph_view_factory: EntrypointViewFactory | None = None
    entrypoint_view_factory: EntrypointViewFactory | None = None
    compiler_view_factory: EntrypointViewFactory | None = None
    ide_strategy_loader: Callable[[str, str], Any] | None = None


class PlatformSourceLineagePolicyResolverM16M21:
    """Resolve M16-M21 from one real anchor and exact typed relationships."""

    registered_rows = SUPPORTED_ROWS

    def __init__(self, context: PlatformSourceLineagePoliciesM16M21Context) -> None:
        self._context = context
        requirements = (
            (
                context.research_graph_store,
                ("qro", "commands"),
                "research_graph_store",
            ),
            (
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
                "compiler_store",
            ),
            (
                context.entrypoint_registry,
                ("records", "validate_real_backing"),
                "entrypoint_registry",
            ),
            (
                context.spine_chain_registry,
                ("verified_chain",),
                "spine_chain_registry",
            ),
            (
                context.asset_lifecycle_registry,
                (
                    "governed_asset",
                    "governed_asset_by_mock_label_ref",
                    "governed_asset_by_category_ref",
                ),
                "asset_lifecycle_registry",
            ),
            (
                context.sharing_service,
                ("shared_asset", "permission", "source", "status"),
                "sharing_service",
            ),
            (
                context.copy_trade_service,
                ("get_follower", "subscription"),
                "copy_trade_service",
            ),
            (
                context.runtime_promotion_registry,
                ("promotion",),
                "runtime_promotion_registry",
            ),
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
            (
                context.execution_order_intent_registry,
                ("intent",),
                "execution_order_intent_registry",
            ),
            (
                context.canonical_spine_ledger,
                ("check", "binding"),
                "canonical_spine_ledger",
            ),
            (context.rdp_store, ("manifests",), "rdp_store"),
            (
                context.teaching_asset_registry,
                ("tutorial_asset", "bundles"),
                "teaching_asset_registry",
            ),
            (
                context.onboarding_registry,
                ("secret_ref",),
                "onboarding_registry",
            ),
            (
                context.llm_call_record_store,
                ("read_all",),
                "llm_call_record_store",
            ),
            (
                context.account_halt_barrier,
                ("halt_evidence",),
                "account_halt_barrier",
            ),
        )
        for value, methods, label in requirements:
            missing = [name for name in methods if not callable(getattr(value, name, None))]
            if missing:
                raise TypeError(f"{label} is missing required methods: {missing}")
        if context.entrypoint_view_factory is not None and not callable(
            context.entrypoint_view_factory
        ):
            raise TypeError("entrypoint_view_factory must be callable")
        if context.research_graph_view_factory is not None and not callable(
            context.research_graph_view_factory
        ):
            raise TypeError("research_graph_view_factory must be callable")
        if context.compiler_view_factory is not None and not callable(
            context.compiler_view_factory
        ):
            raise TypeError("compiler_view_factory must be callable")
        if context.ide_strategy_loader is not None and not callable(
            context.ide_strategy_loader
        ):
            raise TypeError("ide_strategy_loader must be callable")

    def _entrypoints(self) -> Any:
        if self._context.entrypoint_view_factory is None:
            return self._context.entrypoint_registry
        view = self._context.entrypoint_view_factory()
        if not callable(getattr(view, "records", None)) or not callable(
            getattr(view, "validate_real_backing", None)
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "fresh entrypoint view lacks required methods"
            )
        return view

    def _compiler(self) -> Any:
        if self._context.compiler_view_factory is None:
            return self._context.compiler_store
        view = self._context.compiler_view_factory()
        required = platform_compiler_snapshot_required_methods(view)
        missing = tuple(
            name for name in required if not callable(getattr(view, name, None))
        )
        if missing:
            raise PlatformSourceLineagePolicyM16M21Error(
                "fresh compiler view lacks required methods: "
                + ", ".join(missing)
            )
        return view

    def _validate_direct_business_attestation(
        self,
        *,
        owner: str,
        row: str,
        anchor: str,
        coverage: Any,
        qro: Any,
        command: Any,
        compiler_ir: Any,
        compiler_pass: Any,
        chain: Any,
        compiler_snapshot: PlatformCompilerSnapshot,
    ) -> None:
        """Require the exact persisted shape emitted by the row attestor."""

        entrypoint = _ENTRYPOINTS[row][0]
        qro_ref = _exact(getattr(qro, "qro_id", ""), field=f"{row} QRO ref")
        command_ref = _exact(
            getattr(command, "command_id", ""),
            field=f"{row} Graph command ref",
        )
        chain_ref = _exact(
            getattr(chain, "chain_ref", ""),
            field=f"{row} Mathematical Spine ref",
        )
        anchor = _exact(anchor, field=f"{row} attestation anchor")
        input_contract = _mapping(
            getattr(qro, "input_contract", None),
            field=f"{row} QRO input_contract",
        )
        output_contract = _mapping(
            getattr(qro, "output_contract", None),
            field=f"{row} QRO output_contract",
        )
        qro_evidence = _tuple_refs(
            getattr(qro, "evidence_refs", ()),
            field=f"{row} QRO evidence_refs",
        )
        qro_lineage = _tuple_refs(
            getattr(qro, "lineage", ()),
            field=f"{row} QRO lineage",
        )
        contract_keys = _DIRECT_CONTRACT_KEYS[row]
        if set(input_contract) != set(contract_keys):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} QRO input_contract keys are stale or recombined"
            )
        expected_lineage = _unique_refs(
            tuple(input_contract[key] for key in contract_keys),
            chain_ref,
        )
        expected_implementation_hash = "platform_business_attestation_" + content_hash(
            {
                "schema_version": 1,
                "row": row,
                "owner_user_id": owner,
                "input_contract": input_contract,
                "output_contract": _DIRECT_OUTPUT_CONTRACTS[row],
                "mathematical_spine_chain_ref": chain_ref,
            }
        )
        expected_command_ref = "rgcmd_" + content_hash(
            {
                "schema_version": 1,
                "record_type": "platform_business_attestation",
                "row": row,
                "owner_user_id": owner,
                "anchor_ref": anchor,
                "entrypoint_ref": entrypoint,
                "qro_ref": qro_ref,
                "mathematical_spine_chain_ref": chain_ref,
            }
        )
        expected_permission = (
            f"platform.business_attestation:{row.lower()}:user_manual"
        )
        expected_coverage_ref = goal_entrypoint_coverage_identity(
            entry_source="api",
            entrypoint_ref=entrypoint,
            goal_sections=_DIRECT_GOAL_SECTIONS[row],
            qro_refs=(qro_ref,),
            research_graph_command_refs=(command_ref,),
            compiler_ir_refs=(
                _text(getattr(compiler_ir, "ir_ref", "")),
            ),
            compiler_pass_refs=(
                _text(getattr(compiler_pass, "pass_ref", "")),
            ),
        )

        commands = tuple(self._context.research_graph_store.commands() or ())
        entrypoint_commands = tuple(
            item
            for item in commands
            if _text(getattr(item, "actor", "")) == owner
            and entrypoint
            in tuple(getattr(item, "tool_record_refs", ()) or ())
        )
        projection_index = getattr(
            self._context.research_graph_store,
            "projection_index",
            None,
        )
        if not callable(projection_index):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} Research Graph cannot prove its current projection"
            )
        projections = tuple(
            item
            for item in tuple(projection_index(owner=owner) or ())
            if _text(getattr(item, "qro_id", "")) == qro_ref
        )
        projection = _one(
            projections,
            label=f"{row} exact current Research Graph projection",
        )

        relevant_irs = tuple(
            item
            for item in compiler_snapshot.irs
            if qro_ref in tuple(getattr(item, "source_qro_refs", ()) or ())
            or command_ref in tuple(getattr(item, "graph_command_refs", ()) or ())
        )
        relevant_passes = tuple(
            item
            for item in compiler_snapshot.passes
            if qro_ref in tuple(getattr(item, "input_qro_refs", ()) or ())
            or command_ref in tuple(getattr(item, "graph_command_refs", ()) or ())
        )

        ir_ref = _exact(
            getattr(compiler_ir, "ir_ref", ""),
            field=f"{row} compiler IR ref",
        )
        pass_ref = _exact(
            getattr(compiler_pass, "pass_ref", ""),
            field=f"{row} compiler pass ref",
        )
        canonical_refs = _tuple_refs(
            getattr(compiler_ir, "canonical_command_refs", ()),
            field=f"{row} compiler canonical_command_refs",
        )
        required_canonical_refs = {
            f"research_graph_command:{command_ref}",
            f"entrypoint:{entrypoint}",
            anchor,
            chain_ref,
        }
        if row == M18:
            required_canonical_refs.add(
                _contract_ref(qro, "canonical_code_command_ref")
            )
        validation_refs = _tuple_refs(
            getattr(compiler_ir, "validation_refs", ()),
            field=f"{row} compiler validation_refs",
        )
        compiler_evidence_refs = _tuple_refs(
            getattr(compiler_ir, "evidence_refs", ()),
            field=f"{row} compiler evidence_refs",
        )
        receipt_refs = tuple(
            ref
            for ref in validation_refs
            if ref.startswith("goal_validation_receipt:")
        )

        if (
            _enum_text(getattr(qro, "actor", "")) != "user_manual"
            or output_contract != _DIRECT_OUTPUT_CONTRACTS[row]
            or qro_lineage != expected_lineage
            or _text(getattr(qro, "implementation_hash", ""))
            != expected_implementation_hash
            or _text(getattr(qro, "permission", ""))
            != f"platform.business_attestation:{row.lower()}:owner"
            or command_ref != expected_command_ref
            or entrypoint_commands != (command,)
            or _enum_text(getattr(command, "actor_source", ""))
            != "user_manual"
            or tuple(getattr(command, "evidence_refs", ()) or ())
            != qro_evidence
            or tuple(getattr(command, "tool_record_refs", ()) or ())
            != (entrypoint,)
            or _owner(projection) != owner
            or _text(getattr(projection, "command_id", "")) != command_ref
            or _text(getattr(projection, "actor", "")) != owner
            or _enum_text(getattr(projection, "source", "")) != "api"
            or _enum_text(getattr(projection, "actor_source", ""))
            != "user_manual"
            or _enum_text(getattr(projection, "qro_type", ""))
            != _enum_text(getattr(qro, "qro_type", ""))
            or tuple(getattr(projection, "evidence_refs", ()) or ())
            != qro_evidence
            or tuple(getattr(projection, "mathematical_refs", ()) or ())
            != (chain_ref,)
            or _text(getattr(projection, "input_contract_hash", ""))
            != content_hash(input_contract)
            or _text(getattr(projection, "output_contract_hash", ""))
            != content_hash(output_contract)
            or int(getattr(projection, "qro_version", 0) or 0)
            != int(getattr(qro, "version", 1) or 1)
            or relevant_irs != (compiler_ir,)
            or relevant_passes != (compiler_pass,)
            or _owner(compiler_ir) != owner
            or tuple(getattr(compiler_ir, "source_qro_refs", ()) or ())
            != (qro_ref,)
            or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ())
            != (command_ref,)
            or tuple(
                getattr(compiler_ir, "mathematical_spine_chain_refs", ()) or ()
            )
            != (chain_ref,)
            or len(compiler_evidence_refs) != 1
            or not compiler_evidence_refs[0].startswith(
                "entrypoint_evidence:"
            )
            or len(receipt_refs) != 1
            or _text(getattr(compiler_ir, "permission_ref", ""))
            != expected_permission
            or _text(getattr(compiler_pass, "output_ir_ref", "")) != ir_ref
            or tuple(getattr(compiler_pass, "input_ir_refs", ()) or ())
            != ()
            or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
            != (qro_ref,)
            or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
            != (command_ref,)
            or _text(getattr(compiler_pass, "actor", "")) != owner
            or _enum_text(getattr(compiler_pass, "actor_source", ""))
            != "user_manual"
            or _enum_text(getattr(compiler_pass, "entry_source", "")) != "api"
            or _text(getattr(compiler_pass, "status", "")) != "compiled"
            or _text(getattr(compiler_pass, "permission_ref", ""))
            != expected_permission
            or tuple(getattr(compiler_pass, "tool_record_refs", ()) or ())
            != (entrypoint, anchor, chain_ref, "api:compile_qro")
            or tuple(getattr(compiler_pass, "evidence_refs", ()) or ())
            != compiler_evidence_refs
            or tuple(getattr(compiler_pass, "validation_refs", ()) or ())
            != validation_refs
            or tuple(getattr(compiler_pass, "canonical_command_refs", ()) or ())
            != canonical_refs
            or not required_canonical_refs.issubset(canonical_refs)
            or _text(getattr(coverage, "coverage_ref", ""))
            != expected_coverage_ref
            or tuple(getattr(coverage, "evidence_refs", ()) or ())
            != compiler_evidence_refs
            or tuple(getattr(coverage, "validation_refs", ()) or ())
            != validation_refs
            or tuple(getattr(coverage, "permission_refs", ()) or ())
            != (expected_permission,)
            or tuple(getattr(coverage, "canonical_command_refs", ()) or ())
            != canonical_refs
            or bool(getattr(coverage, "silent_mock_fallback_used", False))
            or bool(getattr(coverage, "raw_payload_persisted", False))
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} direct business attestation lineage is stale or recombined"
            )

    @staticmethod
    def _direct_compiler_proof_refs(
        lineage: _BusinessLineage,
        *,
        row: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Partition a strictly backed direct-attestation compiler bundle.

        Prefixes establish the persisted record shape only.  The caller has
        already required ``validate_real_backing`` for this exact coverage, so
        these refs are trusted through the registry rather than by spelling.
        """

        ir_evidence = _tuple_refs(
            getattr(lineage.compiler_ir, "evidence_refs", ()),
            field=f"{row} compiler IR evidence_refs",
        )
        pass_evidence = _tuple_refs(
            getattr(lineage.compiler_pass, "evidence_refs", ()),
            field=f"{row} compiler pass evidence_refs",
        )
        coverage_evidence = _tuple_refs(
            getattr(lineage.coverage, "evidence_refs", ()),
            field=f"{row} coverage evidence_refs",
        )
        if (
            ir_evidence != pass_evidence
            or ir_evidence != coverage_evidence
            or len(ir_evidence) != 1
            or not ir_evidence[0].startswith("entrypoint_evidence:")
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} compiler proof must bind one strictly backed entrypoint evidence ref"
            )

        ir_validations = _tuple_refs(
            getattr(lineage.compiler_ir, "validation_refs", ()),
            field=f"{row} compiler IR validation_refs",
        )
        pass_validations = _tuple_refs(
            getattr(lineage.compiler_pass, "validation_refs", ()),
            field=f"{row} compiler pass validation_refs",
        )
        coverage_validations = _tuple_refs(
            getattr(lineage.coverage, "validation_refs", ()),
            field=f"{row} coverage validation_refs",
        )
        if (
            ir_validations != pass_validations
            or ir_validations != coverage_validations
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} compiler validation proof is divergent"
            )
        receipt_refs = tuple(
            ref
            for ref in ir_validations
            if ref.startswith("goal_validation_receipt:")
        )
        domain_validation_refs = tuple(
            ref
            for ref in ir_validations
            if not ref.startswith("goal_validation_receipt:")
        )
        if len(receipt_refs) != 1:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} compiler proof must bind exactly one durable GOAL validation receipt"
            )
        return ir_evidence, domain_validation_refs, receipt_refs

    @staticmethod
    def _require_direct_attestation_refs(
        lineage: _BusinessLineage,
        *,
        row: str,
        evidence_refs: tuple[str, ...],
        validation_refs: tuple[str, ...],
    ) -> None:
        if (
            tuple(getattr(lineage.qro, "evidence_refs", ()) or ())
            != evidence_refs
            or tuple(getattr(lineage.command, "evidence_refs", ()) or ())
            != evidence_refs
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} semantic attestation evidence is stale or recombined"
            )
        _compiler_evidence, domain_validations, _receipts = (
            PlatformSourceLineagePolicyResolverM16M21._direct_compiler_proof_refs(
                lineage,
                row=row,
            )
        )
        if domain_validations != validation_refs:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} semantic validation evidence is stale or recombined"
            )

    def _business_lineage(
        self,
        *,
        owner: str,
        row: str,
        anchor: str = "",
        predicate: QROPredicate,
    ) -> _BusinessLineage:
        view = self._entrypoints()
        compiler_store = self._compiler()
        try:
            records = tuple(view.records(owner=owner))
            compiler_snapshot = platform_compiler_snapshot(
                compiler_store,
                owner=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} business coverage listing failed:{type(exc).__name__}"
            ) from exc
        if row in _DIRECT_BUSINESS_ATTESTATION_ROWS:
            row_records = tuple(
                coverage
                for coverage in records
                if _text(getattr(coverage, "recorded_by", "")) == owner
                and _text(getattr(coverage, "entrypoint_ref", ""))
                == _ENTRYPOINTS[row][0]
                and "§14"
                not in tuple(
                    _enum_text(section)
                    for section in tuple(
                        getattr(coverage, "goal_sections", ()) or ()
                    )
                )
            )
            if len(row_records) != 1:
                raise PlatformSourceLineagePolicyM16M21Error(
                    f"{row} strict business QRO/Graph/compiler lineage must have exactly one owner row-attestation coverage"
                )
        candidates: list[_BusinessLineage] = []
        for coverage in records:
            sections = tuple(_enum_text(item) for item in tuple(getattr(coverage, "goal_sections", ()) or ()))
            if (
                _text(getattr(coverage, "recorded_by", "")) != owner
                or not sections
                or "§14" in sections
                or (
                    row in _DIRECT_BUSINESS_ATTESTATION_ROWS
                    and sections != _DIRECT_GOAL_SECTIONS[row]
                )
                or (
                    row in _POST_BUSINESS_ATTESTATION_ROWS
                    and sections != _POST_BUSINESS_BINDING_GOAL_SECTIONS[row]
                )
                or _enum_text(getattr(coverage, "entry_source", ""))
                != _ENTRY_SOURCES[row]
                or _text(getattr(coverage, "entrypoint_ref", ""))
                not in _ENTRYPOINTS[row]
            ):
                continue
            qro_refs = tuple(getattr(coverage, "qro_refs", ()) or ())
            graph_refs = tuple(
                getattr(coverage, "research_graph_command_refs", ()) or ()
            )
            ir_refs = tuple(getattr(coverage, "compiler_ir_refs", ()) or ())
            pass_refs = tuple(getattr(coverage, "compiler_pass_refs", ()) or ())
            if not all(
                len(refs) == 1
                for refs in (qro_refs, graph_refs, ir_refs, pass_refs)
            ):
                continue
            try:
                decision = view.validate_real_backing(coverage)
                if not bool(getattr(decision, "accepted", False)):
                    continue
                qro = self._context.research_graph_store.qro(qro_refs[0])
                command = _one(
                    (
                        item
                        for item in self._context.research_graph_store.commands()
                        if _text(getattr(item, "command_id", "")) == graph_refs[0]
                    ),
                    label=f"{row} Research Graph command",
                )
                payload = getattr(command, "payload", None)
                embedded = payload.get("qro") if isinstance(payload, dict) else None
                if (
                    embedded != qro
                    or _owner(qro) != owner
                    or _text(getattr(command, "actor", "")) != owner
                    or _enum_text(getattr(command, "source", ""))
                    != _ENTRY_SOURCES[row]
                    or _text(getattr(command, "command_type", ""))
                    != "upsert_qro"
                    or not predicate(qro, command)
                ):
                    continue
                mathematical_refs = _tuple_refs(
                    getattr(qro, "mathematical_refs", ()),
                    field=f"{row} QRO mathematical_refs",
                )
                if len(mathematical_refs) != 1:
                    continue
                chain = self._context.spine_chain_registry.verified_chain(
                    mathematical_refs[0],
                    owner=owner,
                )
                if _text(getattr(chain, "chain_ref", "")) != mathematical_refs[0]:
                    continue
                compiler_ir = compiler_snapshot.ir(ir_refs[0])
                compiler_pass = compiler_snapshot.compiler_pass(pass_refs[0])
                canonical_entrypoint = self._canonical_entrypoint(
                    row=row,
                    command_ref=graph_refs[0],
                    compiler_ir=compiler_ir,
                    compiler_pass=compiler_pass,
                )
                if (
                    tuple(getattr(compiler_ir, "source_qro_refs", ()) or ())
                    != (qro_refs[0],)
                    or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ())
                    != (graph_refs[0],)
                    or tuple(
                        getattr(compiler_ir, "mathematical_spine_chain_refs", ())
                        or ()
                    )
                    != mathematical_refs
                    or _text(getattr(compiler_ir, "owner", "")) != owner
                    or _text(getattr(compiler_pass, "output_ir_ref", ""))
                    != ir_refs[0]
                    or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
                    != (qro_refs[0],)
                    or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
                    != (graph_refs[0],)
                    or _text(getattr(compiler_pass, "actor", "")) != owner
                    or _enum_text(getattr(compiler_pass, "entry_source", ""))
                    != _ENTRY_SOURCES[row]
                    or tuple(getattr(coverage, "canonical_command_refs", ()) or ())
                    != tuple(getattr(compiler_ir, "canonical_command_refs", ()) or ())
                    or tuple(getattr(compiler_pass, "canonical_command_refs", ()) or ())
                    != tuple(getattr(compiler_ir, "canonical_command_refs", ()) or ())
                    or canonical_entrypoint
                    != _text(getattr(coverage, "entrypoint_ref", ""))
                ):
                    continue
                if row in _DIRECT_BUSINESS_ATTESTATION_ROWS:
                    self._validate_direct_business_attestation(
                        owner=owner,
                        row=row,
                        anchor=anchor,
                        coverage=coverage,
                        qro=qro,
                        command=command,
                        compiler_ir=compiler_ir,
                        compiler_pass=compiler_pass,
                        chain=chain,
                        compiler_snapshot=compiler_snapshot,
                    )
            except Exception:
                continue
            candidates.append(
                _BusinessLineage(
                    coverage=coverage,
                    qro=qro,
                    command=command,
                    compiler_ir=compiler_ir,
                    compiler_pass=compiler_pass,
                    chain=chain,
                )
            )
        return _one(candidates, label=f"{row} strict business QRO/Graph/compiler lineage")

    @staticmethod
    def _qro_identity_without_math(qro: Any, *, row: str) -> dict[str, Any]:
        payload = _plain(qro)
        if not isinstance(payload, dict) or "mathematical_refs" not in payload:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} QRO identity is unavailable"
            )
        payload.pop("mathematical_refs")
        return payload

    @staticmethod
    def _canonical_entrypoint(
        *,
        row: str,
        command_ref: str,
        compiler_ir: Any,
        compiler_pass: Any,
    ) -> str:
        ir_refs = tuple(getattr(compiler_ir, "canonical_command_refs", ()) or ())
        pass_refs = tuple(
            getattr(compiler_pass, "canonical_command_refs", ()) or ()
        )
        expected_command_ref = f"research_graph_command:{command_ref}"
        entrypoints = {
            _text(ref).removeprefix("entrypoint:")
            for ref in ir_refs
            if _text(ref).startswith("entrypoint:")
        }
        if (
            ir_refs != pass_refs
            or expected_command_ref not in ir_refs
            or len(entrypoints) != 1
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} compiler lineage lacks one canonical Graph command/entrypoint"
            )
        return next(iter(entrypoints))

    def _historical_compiler_lineage(
        self,
        *,
        owner: str,
        row: str,
        qro: Any,
        command: Any,
    ) -> _HistoricalBusinessLineage:
        compiler_store = self._compiler()
        compiler_snapshot = platform_compiler_snapshot(
            compiler_store,
            owner=owner,
        )
        qro_ref = _exact(getattr(qro, "qro_id", ""), field=f"{row} QRO ref")
        command_ref = _exact(
            getattr(command, "command_id", ""),
            field=f"{row} Graph command ref",
        )
        matching_irs = tuple(
            item
            for item in compiler_snapshot.irs
            if tuple(getattr(item, "source_qro_refs", ()) or ()) == (qro_ref,)
            and tuple(getattr(item, "graph_command_refs", ()) or ())
            == (command_ref,)
            and _owner(item) == owner
        )
        pairs: list[tuple[Any, Any]] = []
        for compiler_ir in matching_irs:
            for compiler_pass in compiler_snapshot.passes:
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
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} QRO/Graph history must select exactly one compiler IR/pass pair"
            )
        compiler_ir, compiler_pass = pairs[0]
        qro_math = tuple(
            _exact(ref, field=f"{row} historical QRO mathematical_refs")
            for ref in tuple(getattr(qro, "mathematical_refs", ()) or ())
        )
        if (
            len(qro_math) != len(set(qro_math))
            or tuple(
                getattr(compiler_ir, "mathematical_spine_chain_refs", ()) or ()
            )
            != qro_math
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} historical compiler Mathematical Spine mismatch"
            )
        entrypoint_ref = self._canonical_entrypoint(
            row=row,
            command_ref=command_ref,
            compiler_ir=compiler_ir,
            compiler_pass=compiler_pass,
        )
        return _HistoricalBusinessLineage(
            qro=qro,
            command=command,
            compiler_ir=compiler_ir,
            compiler_pass=compiler_pass,
            entry_source=_enum_text(getattr(compiler_pass, "entry_source", "")),
            entrypoint_ref=entrypoint_ref,
        )

    def _historical_business_coverage(
        self,
        *,
        owner: str,
        row: str,
        lineage: _HistoricalBusinessLineage,
    ) -> Any:
        view = self._entrypoints()
        try:
            records = tuple(view.records(owner=owner))
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} historical business coverage listing failed:{type(exc).__name__}"
            ) from exc
        qro_ref = _text(getattr(lineage.qro, "qro_id", ""))
        command_ref = _text(getattr(lineage.command, "command_id", ""))
        ir_ref = _text(getattr(lineage.compiler_ir, "ir_ref", ""))
        pass_ref = _text(getattr(lineage.compiler_pass, "pass_ref", ""))
        canonical_refs = tuple(
            getattr(lineage.compiler_ir, "canonical_command_refs", ()) or ()
        )
        candidates: list[Any] = []
        for coverage in records:
            sections = tuple(
                _enum_text(item)
                for item in tuple(getattr(coverage, "goal_sections", ()) or ())
            )
            if (
                _text(getattr(coverage, "recorded_by", "")) != owner
                or not sections
                or "§14" in sections
                or _enum_text(getattr(coverage, "entry_source", ""))
                != lineage.entry_source
                or _text(getattr(coverage, "entrypoint_ref", ""))
                != lineage.entrypoint_ref
                or tuple(getattr(coverage, "qro_refs", ()) or ()) != (qro_ref,)
                or tuple(
                    getattr(coverage, "research_graph_command_refs", ()) or ()
                )
                != (command_ref,)
                or tuple(getattr(coverage, "compiler_ir_refs", ()) or ())
                != (ir_ref,)
                or tuple(getattr(coverage, "compiler_pass_refs", ()) or ())
                != (pass_ref,)
                or tuple(getattr(coverage, "canonical_command_refs", ()) or ())
                != canonical_refs
            ):
                continue
            decision = validate_goal_entrypoint_coverage(coverage)
            expected_identity = goal_entrypoint_coverage_identity(
                entry_source=getattr(coverage, "entry_source", ""),
                entrypoint_ref=getattr(coverage, "entrypoint_ref", ""),
                goal_sections=tuple(getattr(coverage, "goal_sections", ()) or ()),
                qro_refs=tuple(getattr(coverage, "qro_refs", ()) or ()),
                research_graph_command_refs=tuple(
                    getattr(coverage, "research_graph_command_refs", ()) or ()
                ),
                compiler_ir_refs=tuple(
                    getattr(coverage, "compiler_ir_refs", ()) or ()
                ),
                compiler_pass_refs=tuple(
                    getattr(coverage, "compiler_pass_refs", ()) or ()
                ),
            )
            for field_name in (
                "evidence_refs",
                "validation_refs",
                "permission_refs",
                "replay_refs",
                "canonical_command_refs",
            ):
                _tuple_refs(
                    getattr(coverage, field_name, ()),
                    field=f"{row} historical coverage {field_name}",
                )
            if (
                bool(getattr(decision, "accepted", False))
                and _text(getattr(coverage, "coverage_ref", ""))
                == expected_identity
            ):
                candidates.append(coverage)
        return _one(
            candidates,
            label=f"{row} strict historical business entrypoint coverage",
        )

    def _validate_post_business_binding(
        self,
        *,
        owner: str,
        row: str,
        anchor: str,
        current: _BusinessLineage,
        projection: Any,
        historical: _HistoricalBusinessLineage,
    ) -> None:
        """Validate the exact server-owned historical-to-binding overlay."""

        entrypoint = _ENTRYPOINTS[row][0]
        qro_ref = _exact(
            getattr(current.qro, "qro_id", ""),
            field=f"{row} binding QRO ref",
        )
        command_ref = _exact(
            getattr(current.command, "command_id", ""),
            field=f"{row} binding Graph command ref",
        )
        historical_ref = _exact(
            getattr(historical.command, "command_id", ""),
            field=f"{row} historical business Graph command ref",
        )
        chain_ref = _exact(
            getattr(current.chain, "chain_ref", ""),
            field=f"{row} binding Mathematical Spine ref",
        )
        anchor = _exact(anchor, field=f"{row} binding anchor")
        ir_ref = _exact(
            getattr(current.compiler_ir, "ir_ref", ""),
            field=f"{row} binding compiler IR ref",
        )
        pass_ref = _exact(
            getattr(current.compiler_pass, "pass_ref", ""),
            field=f"{row} binding compiler pass ref",
        )
        goal_sections = _POST_BUSINESS_BINDING_GOAL_SECTIONS[row]
        expected_coverage_ref = goal_entrypoint_coverage_identity(
            entry_source="api",
            entrypoint_ref=entrypoint,
            goal_sections=goal_sections,
            qro_refs=(qro_ref,),
            research_graph_command_refs=(command_ref,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        permission_ref = f"platform.spine_binding:{row.lower()}:user_manual"
        canonical_refs = _tuple_refs(
            getattr(current.compiler_ir, "canonical_command_refs", ()),
            field=f"{row} binding canonical_command_refs",
        )
        required_canonical_refs = {
            f"research_graph_command:{command_ref}",
            f"entrypoint:{entrypoint}",
            anchor,
            chain_ref,
        }
        entrypoint_commands = tuple(
            item
            for item in tuple(self._context.research_graph_store.commands() or ())
            if _text(getattr(item, "actor", "")) == owner
            and entrypoint
            in tuple(getattr(item, "tool_record_refs", ()) or ())
            and _text(
                getattr(
                    (
                        getattr(item, "payload", {}).get("qro")
                        if isinstance(getattr(item, "payload", None), dict)
                        else None
                    ),
                    "qro_id",
                    "",
                )
            )
            == qro_ref
        )
        if (
            entrypoint_commands != (current.command,)
            or _enum_text(getattr(current.command, "source", "")) != "api"
            or _enum_text(getattr(current.command, "actor_source", ""))
            != "user_manual"
            or _text(getattr(current.command, "actor", "")) != owner
            or tuple(getattr(current.command, "tool_record_refs", ()) or ())
            != (entrypoint,)
            or tuple(getattr(current.command, "evidence_refs", ()) or ())
            != (chain_ref, historical_ref)
            or _enum_text(getattr(projection, "actor_source", ""))
            != "user_manual"
            or tuple(getattr(current.coverage, "goal_sections", ()) or ())
            != goal_sections
            or _text(getattr(current.coverage, "coverage_ref", ""))
            != expected_coverage_ref
            or _text(getattr(current.compiler_pass, "output_ir_ref", ""))
            != ir_ref
            or tuple(getattr(current.compiler_pass, "input_ir_refs", ()) or ())
            != ()
            or _enum_text(getattr(current.compiler_pass, "actor_source", ""))
            != "user_manual"
            or _enum_text(getattr(current.compiler_pass, "entry_source", ""))
            != "api"
            or _text(getattr(current.compiler_pass, "status", ""))
            != "compiled"
            or tuple(getattr(current.compiler_pass, "tool_record_refs", ()) or ())
            != (entrypoint, anchor, chain_ref, "api:compile_qro")
            or _text(getattr(current.compiler_ir, "permission_ref", ""))
            != permission_ref
            or _text(getattr(current.compiler_pass, "permission_ref", ""))
            != permission_ref
            or tuple(getattr(current.coverage, "permission_refs", ()) or ())
            != (permission_ref,)
            or tuple(
                getattr(current.compiler_pass, "canonical_command_refs", ()) or ()
            )
            != canonical_refs
            or tuple(getattr(current.coverage, "canonical_command_refs", ()) or ())
            != canonical_refs
            or not required_canonical_refs.issubset(canonical_refs)
            or bool(getattr(current.coverage, "silent_mock_fallback_used", False))
            or bool(getattr(current.coverage, "raw_payload_persisted", False))
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} current post-business binding is stale or recombined"
            )

    def _post_business_attestation_lineage(
        self,
        *,
        owner: str,
        row: str,
        anchor: str,
        predicate: QROPredicate,
    ) -> _PostBusinessAttestationLineage:
        if row not in _POST_BUSINESS_ATTESTATION_ROWS:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} is not a post-business attestation row"
            )
        current = self._business_lineage(
            owner=owner,
            row=row,
            predicate=predicate,
        )
        qro_ref = _exact(
            getattr(current.qro, "qro_id", ""),
            field=f"{row} current attestation QRO ref",
        )
        command_ref = _exact(
            getattr(current.command, "command_id", ""),
            field=f"{row} current attestation Graph command ref",
        )
        declared = _tuple_refs(
            getattr(current.qro, "mathematical_refs", ()),
            field=f"{row} current attestation QRO mathematical_refs",
        )
        if len(declared) != 1:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} current attestation must bind exactly one Mathematical Spine"
            )

        projection_index = getattr(
            self._context.research_graph_store,
            "projection_index",
            None,
        )
        if not callable(projection_index):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} Research Graph cannot prove the current projection"
            )
        projections = tuple(
            item
            for item in tuple(projection_index(owner=owner) or ())
            if _text(getattr(item, "qro_id", "")) == qro_ref
        )
        projection = _one(projections, label=f"{row} current owner QRO projection")
        if (
            _owner(projection) != owner
            or _text(getattr(projection, "command_id", "")) != command_ref
            or _text(getattr(projection, "actor", "")) != owner
            or _enum_text(getattr(projection, "source", "")) != "api"
            or tuple(getattr(projection, "mathematical_refs", ()) or ())
            != declared
            or _text(getattr(current.command, "actor", "")) != owner
            or _enum_text(getattr(current.command, "source", "")) != "api"
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} current projection is not the owner/API attestation head"
            )

        bound_identity = self._qro_identity_without_math(current.qro, row=row)
        expected_business_source, expected_business_entrypoint = (
            _HISTORICAL_BUSINESS_ENTRYPOINTS[row]
        )
        expected_attestation_entrypoint = _ENTRYPOINTS[row][0]
        historical_matches: list[_HistoricalBusinessLineage] = []
        for command in tuple(self._context.research_graph_store.commands() or ()):
            payload = getattr(command, "payload", None)
            embedded = payload.get("qro") if isinstance(payload, dict) else None
            if _text(getattr(embedded, "qro_id", "")) != qro_ref:
                continue
            if self._qro_identity_without_math(embedded, row=row) != bound_identity:
                raise PlatformSourceLineagePolicyM16M21Error(
                    f"{row} QRO history changes fields other than mathematical_refs"
                )
            historical_math = tuple(
                _exact(
                    ref,
                    field=f"{row} historical QRO mathematical_refs",
                )
                for ref in tuple(getattr(embedded, "mathematical_refs", ()) or ())
            )
            if len(historical_math) != len(set(historical_math)):
                raise PlatformSourceLineagePolicyM16M21Error(
                    f"{row} QRO history contains duplicate Mathematical Spine refs"
                )
            lineage = self._historical_compiler_lineage(
                owner=owner,
                row=row,
                qro=embedded,
                command=command,
            )
            if not historical_math:
                if (
                    _text(getattr(command, "actor", "")) != owner
                    or _enum_text(getattr(command, "source", ""))
                    != expected_business_source
                    or lineage.entry_source != expected_business_source
                    or lineage.entrypoint_ref != expected_business_entrypoint
                ):
                    raise PlatformSourceLineagePolicyM16M21Error(
                        f"{row} historical business Graph/compiler lineage mismatch"
                    )
                historical_matches.append(lineage)
                continue
            if (
                historical_math != declared
                or embedded != current.qro
                or _text(getattr(command, "actor", "")) != owner
                or _enum_text(getattr(command, "source", "")) != "api"
                or lineage.entry_source != "api"
                or lineage.entrypoint_ref != expected_attestation_entrypoint
            ):
                raise PlatformSourceLineagePolicyM16M21Error(
                    f"{row} unrecognized or recombined attestation history"
                )
        historical = _one(
            historical_matches,
            label=f"{row} immutable historical business Graph/compiler lineage",
        )
        historical = replace(
            historical,
            coverage=self._historical_business_coverage(
                owner=owner,
                row=row,
                lineage=historical,
            ),
        )
        self._validate_post_business_binding(
            owner=owner,
            row=row,
            anchor=anchor,
            current=current,
            projection=projection,
            historical=historical,
        )
        return _PostBusinessAttestationLineage(
            current=current,
            projection=projection,
            historical=historical,
        )

    @staticmethod
    def _post_business_attestation_metadata(
        attestation: _PostBusinessAttestationLineage,
        *,
        row: str,
    ) -> tuple[tuple[str, Any], ...]:
        historical = attestation.historical
        return (
            (
                "binding_projection_ref",
                _exact(
                    getattr(attestation.projection, "projection_ref", ""),
                    field=f"{row} binding projection ref",
                ),
            ),
            (
                "business_graph_command_ref",
                _exact(
                    getattr(historical.command, "command_id", ""),
                    field=f"{row} historical business Graph command ref",
                ),
            ),
            (
                "historical_business_coverage_ref",
                _exact(
                    getattr(historical.coverage, "coverage_ref", ""),
                    field=f"{row} historical business coverage ref",
                ),
            ),
            (
                "business_compiler_ir_ref",
                _exact(
                    getattr(historical.compiler_ir, "ir_ref", ""),
                    field=f"{row} historical business compiler IR ref",
                ),
            ),
            (
                "business_compiler_pass_ref",
                _exact(
                    getattr(historical.compiler_pass, "pass_ref", ""),
                    field=f"{row} historical business compiler pass ref",
                ),
            ),
            ("historical_business_entry_source", historical.entry_source),
            ("historical_business_entrypoint_ref", historical.entrypoint_ref),
        )

    @staticmethod
    def _resolution(
        *,
        row: str,
        anchor: str,
        lineage: _BusinessLineage,
        lifecycle_ref: str,
        math_spine_ref: str,
        specific_refs: tuple[PlatformSpecificRef, ...],
        primary_rag_asset_ref: str,
        metadata: tuple[tuple[str, Any], ...],
    ) -> PlatformSourceLineagePolicyResolution:
        lineage_metadata = (
            (
                "business_coverage_ref",
                _exact(
                    getattr(lineage.coverage, "coverage_ref", ""),
                    field=f"{row} business coverage_ref",
                ),
            ),
            (
                "graph_command_ref",
                _exact(
                    getattr(lineage.command, "command_id", ""),
                    field=f"{row} graph command_ref",
                ),
            ),
            (
                "compiler_ir_ref",
                _exact(
                    getattr(lineage.compiler_ir, "ir_ref", ""),
                    field=f"{row} compiler IR ref",
                ),
            ),
            (
                "compiler_pass_ref",
                _exact(
                    getattr(lineage.compiler_pass, "pass_ref", ""),
                    field=f"{row} compiler pass ref",
                ),
            ),
        )
        metadata_keys = tuple(key for key, _value in (*lineage_metadata, *metadata))
        if len(metadata_keys) != len(set(metadata_keys)):
            raise PlatformSourceLineagePolicyM16M21Error(
                f"{row} row policy metadata contains duplicate keys"
            )
        return PlatformSourceLineagePolicyResolution(
            m_row=row,
            anchor_ref=anchor,
            qro_ref=_text(lineage.qro.qro_id),
            business_entry_source=_enum_text(lineage.coverage.entry_source),
            business_entrypoint_ref=_text(lineage.coverage.entrypoint_ref),
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=math_spine_ref,
            specific_refs=specific_refs,
            primary_rag_asset_ref=primary_rag_asset_ref,
            row_policy_metadata=(*lineage_metadata, *metadata),
        )

    def _m16(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M16 anchor_ref", prefix="shared_asset:")
        try:
            strategy = self._context.sharing_service.shared_asset(
                anchor, owner_user_id=owner
            )
            from ..sharing.service import (
                shared_strategy_asset_ref,
                shared_strategy_permission,
                shared_strategy_source,
                shared_strategy_status,
            )

            permission = shared_strategy_permission(strategy)
            source = shared_strategy_source(strategy)
            status = shared_strategy_status(strategy)
            stored_permission = self._context.sharing_service.permission(
                permission.permission_ref,
                owner_user_id=owner,
            )
            stored_source = self._context.sharing_service.source(
                source.source_ref,
                owner_user_id=owner,
            )
            stored_status = self._context.sharing_service.status(
                status.status_ref,
                owner_user_id=owner,
            )
            lifecycle = self._context.asset_lifecycle_registry.governed_asset(
                anchor,
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M16 typed sharing lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            _text(getattr(strategy, "author_id", "")) != owner
            or shared_strategy_asset_ref(strategy) != anchor
            or stored_permission != permission
            or stored_source != source
            or stored_status != status
            or _text(getattr(lifecycle, "asset_ref", "")) != anchor
            or _text(getattr(lifecycle, "asset_type", "")) != "SharedStrategy"
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M16 shared strategy/lifecycle bundle is stale or recombined"
            )
        evidence = set(_tuple_refs(getattr(lifecycle, "evidence_refs", ()), field="M16 lifecycle evidence_refs"))
        expected_refs = {
            "shared_asset_ref": anchor,
            "permission_ref": _exact(permission.permission_ref, field="M16 permission_ref", prefix="permission:"),
            "source_ref": _exact(source.source_ref, field="M16 source_ref", prefix="source:"),
            "status_ref": _exact(status.status_ref, field="M16 status_ref", prefix="status:"),
        }
        if not set(expected_refs.values()).difference({anchor}).issubset(evidence):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M16 governed SharedStrategy omits sharing governance evidence"
            )
        attestation = self._post_business_attestation_lineage(
            owner=owner,
            row=M16,
            anchor=anchor,
            predicate=lambda qro, _command: (
                _enum_text(getattr(qro, "qro_type", "")) == "StrategyBook"
                and not _require_contract_refs(qro, expected_refs)
            ),
        )
        lineage = attestation.current
        return self._resolution(
            row=M16,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=anchor,
            math_spine_ref=_text(lineage.chain.chain_ref),
            specific_refs=_specific_refs(tuple(expected_refs), tuple(expected_refs.values())),
            primary_rag_asset_ref=anchor,
            metadata=(
                *self._post_business_attestation_metadata(
                    attestation,
                    row=M16,
                ),
                ("share_id", _text(strategy.share_id)),
                ("run_id", _text(strategy.run_id)),
            ),
        )

    def _m17(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(
            anchor,
            field="M17 anchor_ref",
            prefix="order_submission_",
        )
        try:
            _refresh_if_available(self._context.execution_order_submission_registry)
            _refresh_if_available(self._context.execution_order_intent_registry)
            _refresh_if_available(self._context.runtime_promotion_registry)
            submission = self._context.execution_order_submission_registry.submission(anchor)
            audit_ref = _exact(
                getattr(submission, "audit_record_ref", ""),
                field="M17 execution_audit_ref",
                prefix="copy_submission_audit_",
            )
            audit_submission = self._context.execution_order_submission_registry.submission_by_audit_record_ref(
                audit_ref
            )
            reservation = self._context.follower_risk_state_store.reservation_for_submission(
                anchor
            )
            reservation_ref = _exact(
                getattr(reservation, "reservation_ref", ""),
                field="M17 reservation_ref",
                prefix="copy_reservation_",
            )
            risk_by_ref = self._context.follower_risk_state_store.reservation_by_risk_check_ref(
                _text(reservation.risk_check_ref)
            )
            follower = self._context.copy_trade_service.get_follower(
                _text(reservation.follower_id)
            )
            if follower is None:
                raise KeyError("current follower is missing")
            from ..copy_trade.service import copy_trade_subscription_ref

            subscription_ref = copy_trade_subscription_ref(follower)
            current_follower = self._context.copy_trade_service.subscription(
                subscription_ref,
                owner_user_id=owner,
            )
            promotion = self._context.runtime_promotion_registry.promotion(
                _text(submission.runtime_promotion_ref)
            )
            intent_ref = _exact(
                getattr(submission, "order_intent_ref", ""),
                field="M17 order_intent_ref",
                prefix="order_intent_",
            )
            intent = self._context.execution_order_intent_registry.intent(
                intent_ref
            )
            from ..lineage.ids import content_hash

            expected_subject_ref = "copy_trade_subject_" + content_hash(
                {
                    "follower_id": _exact(
                        getattr(follower, "follower_id", ""),
                        field="M17 follower_id",
                    ),
                    "user_id": _exact(
                        getattr(follower, "user_id", ""),
                        field="M17 follower user_id",
                    ),
                    "master_id": _exact(
                        getattr(follower, "master_id", ""),
                        field="M17 follower master_id",
                    ),
                    "account_binding_ref": _exact(
                        getattr(follower, "account_binding_ref", ""),
                        field="M17 follower account_binding_ref",
                    ),
                }
            )
            expected_audit_ref = "copy_submission_audit_" + content_hash(
                reservation_ref
            )
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
                field="M17 account_binding_ref",
            )
            execution_policy_ref = _exact(
                getattr(intent, "execution_policy_ref", ""),
                field="M17 intent execution_policy_ref",
            )
            intent_risk_ref = _exact(
                getattr(intent, "risk_policy_ref", ""),
                field="M17 intent risk_policy_ref",
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M17 guarded submission lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            risk_by_ref != reservation
            or audit_submission != submission
            or current_follower != follower
            or _text(getattr(follower, "user_id", "")) != owner
            or _text(getattr(follower, "status", "")) == "stopped"
            or _text(getattr(follower, "account_binding_ref", ""))
            != account_ref
            or _text(getattr(follower, "runtime_promotion_ref", ""))
            != _text(getattr(submission, "runtime_promotion_ref", ""))
            or _text(getattr(submission, "submission_ref", "")) != anchor
            or audit_ref != expected_audit_ref
            or _text(getattr(submission, "recorded_by", ""))
            != "copy_trade_signal_relayer"
            or _text(getattr(submission, "submitter_ref", ""))
            != "copy_trade_signal_relayer:v1"
            or bool(getattr(submission, "submit_enabled", False)) is not True
            or _text(getattr(submission, "submission_mode", "")) != "live"
            or _text(getattr(promotion, "target_runtime", "")) != "live"
            or _text(getattr(promotion, "subject_ref", ""))
            != expected_subject_ref
            or _text(getattr(submission, "permission_gate_ref", ""))
            != permission_ref
            or _text(getattr(submission, "order_guard_ref", ""))
            != order_guard_ref
            or _text(getattr(intent, "order_intent_ref", "")) != intent_ref
            or _text(getattr(intent, "recorded_by", "")) != owner
            or _enum_text(getattr(intent, "runtime", "")) != "live"
            or intent_risk_ref != _text(getattr(reservation, "risk_check_ref", ""))
            or execution_policy_ref != permission_ref
            or _text(getattr(intent, "permission_gate_ref", ""))
            != permission_ref
            or _text(getattr(intent, "order_guard_ref", ""))
            != order_guard_ref
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M17 subscription/promotion/risk/intent/submission lineage is stale or recombined"
            )
        expected_refs = {
            "copy_trade_subscription_ref": _exact(
                subscription_ref,
                field="M17 copy_trade_subscription_ref",
                prefix="copy_trade_subscription_",
            ),
            "runtime_promotion_ref": _exact(
                submission.runtime_promotion_ref,
                field="M17 runtime_promotion_ref",
                prefix=("runtime_promotion_", "runtime_promotion:"),
            ),
            "risk_gate_ref": _exact(
                reservation.risk_check_ref,
                field="M17 risk_gate_ref",
                prefix="copy_risk_check_",
            ),
            "execution_audit_ref": audit_ref,
        }
        attestation_refs = {"submission_ref": anchor, **expected_refs}
        lineage = self._business_lineage(
            owner=owner,
            row=M17,
            anchor=anchor,
            predicate=lambda qro, _command: (
                _enum_text(getattr(qro, "qro_type", "")) == "ExecutionPolicy"
                and not _require_contract_refs(qro, attestation_refs)
            ),
        )
        if (
            _text(getattr(lineage.chain, "risk_policy_ref", ""))
            != expected_refs["risk_gate_ref"]
            or _text(getattr(lineage.chain, "execution_policy_ref", ""))
            != execution_policy_ref
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M17 intent policies are recombined outside the verified Mathematical Spine chain"
            )
        self._require_direct_attestation_refs(
            lineage,
            row=M17,
            evidence_refs=_unique_refs(
                tuple(attestation_refs.values()),
                reservation_ref,
                intent_ref,
                account_ref,
                order_guard_ref,
                _text(lineage.chain.chain_ref),
            ),
            validation_refs=_unique_refs(
                expected_refs["risk_gate_ref"],
                expected_refs["execution_audit_ref"],
                _text(lineage.chain.chain_ref),
            ),
        )
        return self._resolution(
            row=M17,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=expected_refs["runtime_promotion_ref"],
            math_spine_ref=_text(lineage.chain.chain_ref),
            specific_refs=_specific_refs(tuple(expected_refs), tuple(expected_refs.values())),
            primary_rag_asset_ref=expected_refs["copy_trade_subscription_ref"],
            metadata=(
                ("submission_ref", anchor),
                ("reservation_ref", reservation_ref),
                ("order_intent_ref", intent_ref),
            ),
        )

    def _m18(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M18 anchor_ref", prefix="cc_")
        try:
            check = self._context.canonical_spine_ledger.check(anchor, owner=owner)
            binding = self._context.canonical_spine_ledger.binding(
                _text(check.binding_id),
                owner=owner,
            )
            manifests = tuple(
                manifest
                for manifest in self._context.rdp_store.manifests(
                    owner_user_id=owner
                )
                if anchor
                in tuple(getattr(manifest, "consistency_check_refs", ()) or ())
            )
            manifest = _one(manifests, label="M18 owner RDP for ConsistencyCheck")
        except PlatformSourceLineagePolicyM16M21Error:
            raise
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M18 check/binding/RDP lookup failed:{type(exc).__name__}"
            ) from exc
        result = _enum_text(getattr(check, "result", ""))
        if (
            _text(getattr(check, "check_id", "")) != anchor
            or _text(getattr(binding, "binding_id", ""))
            != _text(getattr(check, "binding_id", ""))
            or result != "pass"
            or not tuple(getattr(manifest, "test_refs", ()) or ())
            or tuple(getattr(manifest, "unverified_residuals", ()) or ())
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M18 check/binding/RDP is not a current verified code package"
            )
        graph_refs = _tuple_refs(
            getattr(manifest, "graph_refs", ()),
            field="M18 RDP graph_refs",
        )
        code_refs = _tuple_refs(
            getattr(manifest, "code_refs", ()),
            field="M18 RDP code_refs",
        )
        test_refs = _tuple_refs(
            getattr(manifest, "test_refs", ()),
            field="M18 RDP test_refs",
        )
        used_by = set(
            _tuple_refs(getattr(binding, "used_by", ()), field="M18 binding used_by")
        )
        canonical_command_ref = _one(
            sorted(set(graph_refs).intersection(used_by)),
            label="M18 canonical IDE code command",
        )
        try:
            canonical_command = _one(
                (
                    item
                    for item in self._context.research_graph_store.commands()
                    if _text(getattr(item, "command_id", ""))
                    == canonical_command_ref
                ),
                label="M18 canonical IDE code command record",
            )
            command_payload = _mapping(
                getattr(canonical_command, "payload", None),
                field="M18 canonical IDE command payload",
            )
            source_qro = command_payload.get("qro")
            source_qro_ref = _exact(
                getattr(source_qro, "qro_id", ""),
                field="M18 canonical IDE source QRO ref",
            )
            stored_source_qro = self._context.research_graph_store.qro(
                source_qro_ref
            )
            source_input = _mapping(
                getattr(source_qro, "input_contract", None),
                field="M18 canonical IDE source QRO input_contract",
            )
            code_ref = _exact(
                source_input.get("code_hash"),
                field="M18 canonical IDE code_ref",
            )
        except PlatformSourceLineagePolicyM16M21Error:
            raise
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M18 canonical IDE command/QRO lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            stored_source_qro != source_qro
            or _owner(source_qro) != owner
            or _text(getattr(canonical_command, "actor", "")) != owner
            or _enum_text(getattr(canonical_command, "source", "")) != "ide"
            or _text(getattr(canonical_command, "command_type", ""))
            != "upsert_qro"
            or _enum_text(getattr(source_qro, "qro_type", ""))
            not in {"StrategyBook", "BacktestRun"}
            or _text(source_input.get("entry_source")) != "ide"
            or code_ref not in code_refs
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M18 canonical IDE command/QRO/code is stale or recombined"
            )

        package_ref = _exact(
            getattr(manifest, "package_id", ""),
            field="M18 RDP package_id",
        )
        attestation_refs = {
            "canonical_code_command_ref": _exact(
                canonical_command_ref,
                field="M18 canonical_code_command_ref",
                prefix="rgcmd_",
            ),
            "consistency_check_ref": anchor,
            "rdp_package_ref": package_ref,
        }

        def predicate(qro: Any, command: Any) -> bool:
            if _enum_text(getattr(qro, "qro_type", "")) != "ValidationDossier":
                return False
            if _text(getattr(command, "command_id", "")) in graph_refs:
                return False
            _require_contract_refs(qro, attestation_refs)
            return True

        lineage = self._business_lineage(
            owner=owner,
            row=M18,
            anchor=anchor,
            predicate=predicate,
        )
        binding_id = _exact(
            getattr(binding, "binding_id", ""),
            field="M18 binding_id",
        )
        chain_consistency_check_refs = _tuple_refs(
            getattr(lineage.chain, "consistency_check_refs", ()),
            field="M18 Mathematical Spine consistency_check_refs",
        )
        chain_theory_binding_refs = _tuple_refs(
            getattr(lineage.chain, "theory_binding_refs", ()),
            field="M18 Mathematical Spine theory_binding_refs",
        )
        if (
            anchor not in chain_consistency_check_refs
            or binding_id not in chain_theory_binding_refs
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M18 check/binding is recombined outside the verified Mathematical Spine chain"
            )
        chain_ref = _text(lineage.chain.chain_ref)
        manifest_chain_refs = _tuple_refs(
            getattr(manifest, "mathematical_spine_chain_refs", ()),
            field="M18 RDP mathematical_spine_chain_refs",
        )
        if manifest_chain_refs != (chain_ref,):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M18 RDP must bind the exact verified Mathematical Spine chain"
            )
        self._require_direct_attestation_refs(
            lineage,
            row=M18,
            evidence_refs=_unique_refs(
                tuple(attestation_refs.values()),
                binding_id,
                source_qro_ref,
                code_ref,
                chain_ref,
                test_refs,
            ),
            validation_refs=(),
        )
        expected_refs = {
            "canonical_code_command_ref": attestation_refs[
                "canonical_code_command_ref"
            ],
            "consistency_check_ref": anchor,
        }
        return self._resolution(
            row=M18,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=package_ref,
            math_spine_ref=chain_ref,
            specific_refs=_specific_refs(tuple(expected_refs), tuple(expected_refs.values())),
            primary_rag_asset_ref=package_ref,
            metadata=(
                ("binding_id", binding_id),
                ("rdp_package_ref", package_ref),
                ("canonical_code_qro_ref", source_qro_ref),
                ("canonical_code_ref", code_ref),
            ),
        )

    def _m19(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M19 anchor_ref", prefix="tutorial_asset:")
        try:
            tutorial = self._context.teaching_asset_registry.tutorial_asset(
                anchor,
                owner_user_id=owner,
            )
            bundle = _one(
                (
                    item
                    for item in self._context.teaching_asset_registry.bundles(
                        owner_user_id=owner
                    )
                    if _text(item.tutorial.tutorial_asset_ref) == anchor
                ),
                label="M19 teaching bundle",
            )
            lifecycle = self._context.asset_lifecycle_registry.governed_asset(
                _text(tutorial.governed_asset_ref),
                owner_user_id=owner,
            )
        except PlatformSourceLineagePolicyM16M21Error:
            raise
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M19 teaching bundle lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            bundle.tutorial != tutorial
            or _owner(tutorial) != owner
            or _owner(bundle.weakness) != owner
            or _owner(bundle.evidence) != owner
            or _text(bundle.weakness.tutorial_asset_ref) != anchor
            or _text(bundle.evidence.tutorial_asset_ref) != anchor
            or _text(bundle.evidence.weakness_disclosure_ref)
            != _text(bundle.weakness.weakness_disclosure_ref)
            or bool(getattr(bundle.weakness, "visible_by_default", False)) is not True
            or not tuple(getattr(bundle.weakness, "weakness_refs", ()) or ())
            or not tuple(getattr(bundle.evidence, "evidence_refs", ()) or ())
            or _text(getattr(lifecycle, "asset_ref", ""))
            != _text(tutorial.governed_asset_ref)
            or _enum_text(getattr(lifecycle, "category", ""))
            != _text(tutorial.category)
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M19 tutorial/weakness/evidence/lifecycle bundle is stale or recombined"
            )
        expected_refs = {
            "tutorial_asset_ref": anchor,
            "weakness_disclosure_ref": _exact(
                bundle.weakness.weakness_disclosure_ref,
                field="M19 weakness_disclosure_ref",
                prefix="weakness_disclosure:",
            ),
            "teaching_evidence_ref": _exact(
                bundle.evidence.teaching_evidence_ref,
                field="M19 teaching_evidence_ref",
                prefix="teaching_evidence:",
            ),
        }
        attestation = self._post_business_attestation_lineage(
            owner=owner,
            row=M19,
            anchor=anchor,
            predicate=lambda qro, _command: (
                _enum_text(getattr(qro, "qro_type", ""))
                in {"DocumentArtifact", "StrategyBook"}
                and not _require_contract_refs(qro, expected_refs)
                and _contract_ref(qro, "governed_asset_ref")
                == _text(tutorial.governed_asset_ref)
            ),
        )
        lineage = attestation.current
        return self._resolution(
            row=M19,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=_text(tutorial.governed_asset_ref),
            math_spine_ref=_text(lineage.chain.chain_ref),
            specific_refs=_specific_refs(tuple(expected_refs), tuple(expected_refs.values())),
            primary_rag_asset_ref=_text(tutorial.governed_asset_ref),
            metadata=(
                *self._post_business_attestation_metadata(
                    attestation,
                    row=M19,
                ),
                ("teaching_category", _text(tutorial.category)),
                ("weakness_count", len(tuple(bundle.weakness.weakness_refs))),
            ),
        )

    def _m20(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(
            anchor,
            field="M20 anchor_ref",
            prefix=("kill_switch:", "account_halt_"),
        )
        try:
            halt = self._context.account_halt_barrier.halt_evidence(
                anchor,
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M20 durable HALT lookup failed:{type(exc).__name__}"
            ) from exc
        accounts = _tuple_refs(
            getattr(halt, "account_binding_refs", ()),
            field="M20 HALT account_binding_refs",
        )
        flat_proofs = _tuple_refs(
            getattr(halt, "flat_proof_refs", ()),
            field="M20 HALT flat_proof_refs",
        )
        if (
            _owner(halt) != owner
            or _text(getattr(halt, "halt_ref", "")) != anchor
            or _text(getattr(halt, "owner_state", "")) != "halted"
            or len(accounts) != len(flat_proofs)
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M20 HALT is not terminal or lacks one flat proof per account"
            )

        try:
            terminal_records = tuple(
                self._context.llm_call_record_store.read_all(owner_user_id=owner)
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M20 terminal LLM record listing failed:{type(exc).__name__}"
            ) from exc
        service_owner = _text(self._context.llm_service_owner_user_id)
        candidates: list[tuple[_BusinessLineage, str, str, str]] = []
        for terminal in terminal_records:
            try:
                if (
                    _owner(terminal) != owner
                    or _text(getattr(terminal, "record_kind", "")) != "terminal"
                    or _text(getattr(terminal, "status", "")) != "ok"
                ):
                    continue
                call_id = _exact(
                    getattr(terminal, "call_id", ""),
                    field="M20 terminal call_id",
                )
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
                secret_matches: list[tuple[str, Any]] = []
                for stored_owner in dict.fromkeys((owner, service_owner)):
                    if not stored_owner:
                        continue
                    try:
                        record = self._context.onboarding_registry.secret_ref(
                            secret_ref,
                            owner_user_id=stored_owner,
                        )
                    except (KeyError, LookupError, PermissionError, TypeError, ValueError):
                        continue
                    if _text(getattr(record, "secret_ref", "")) == secret_ref:
                        secret_matches.append((stored_owner, record))
                stored_owner, secret = _one(
                    secret_matches,
                    label="M20 owner/service SecretRef",
                )
                if (
                    stored_owner not in {owner, service_owner}
                    or _text(getattr(secret, "status", "")) != "active"
                ):
                    continue
                expected_refs = {
                    "secret_ref": secret_ref,
                    "llm_gateway_ref": gateway_ref,
                    "kill_switch_ref": anchor,
                }

                def predicate(qro: Any, _command: Any) -> bool:
                    return (
                        _enum_text(getattr(qro, "qro_type", "")) == "RiskPolicy"
                        and not _require_contract_refs(qro, expected_refs)
                    )

                lineage = self._business_lineage(
                    owner=owner,
                    row=M20,
                    anchor=anchor,
                    predicate=predicate,
                )
                chain_ref = _text(lineage.chain.chain_ref)
                self._require_direct_attestation_refs(
                    lineage,
                    row=M20,
                    evidence_refs=_unique_refs(
                        tuple(expected_refs.values()),
                        call_id,
                        accounts,
                        flat_proofs,
                        chain_ref,
                    ),
                    validation_refs=_unique_refs(
                        anchor,
                        flat_proofs,
                        chain_ref,
                    ),
                )
                chain_evidence = set(
                    _tuple_refs(
                        getattr(lineage.chain, "evidence_refs", ()),
                        field="M20 Mathematical Spine evidence_refs",
                    )
                )
                chain_validation = set(
                    _tuple_refs(
                        getattr(lineage.chain, "validation_refs", ()),
                        field="M20 Mathematical Spine validation_refs",
                    )
                )
                if (
                    not {secret_ref, gateway_ref, *flat_proofs}.issubset(
                        chain_evidence
                    )
                    or not {anchor, *flat_proofs}.issubset(chain_validation)
                ):
                    raise PlatformSourceLineagePolicyM16M21Error(
                        "M20 HALT/LLM evidence is outside the declared verified Mathematical Spine chain"
                    )
            except (KeyError, LookupError, PermissionError, TypeError, ValueError):
                continue
            candidates.append((lineage, secret_ref, call_id, gateway_ref))
        lineage, secret_ref, call_id, gateway_ref = _one(
            candidates,
            label="M20 current terminal LLM/SecretRef/API attestation lineage",
        )
        expected_refs = {
            "secret_ref": secret_ref,
            "llm_gateway_ref": gateway_ref,
            "kill_switch_ref": anchor,
        }
        return self._resolution(
            row=M20,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=anchor,
            math_spine_ref=_text(lineage.chain.chain_ref),
            specific_refs=_specific_refs(tuple(expected_refs), tuple(expected_refs.values())),
            primary_rag_asset_ref=anchor,
            metadata=(
                ("llm_call_id", call_id),
                ("halt_owner_epoch", int(getattr(halt, "owner_epoch", 0) or 0)),
            ),
        )

    def _m21(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M21 anchor_ref")
        new_identity = anchor.startswith("ide_strategy:")

        def predicate(qro: Any, _command: Any) -> bool:
            if _enum_text(getattr(qro, "qro_type", "")) != "StrategyBook":
                return False
            input_contract = _mapping(
                getattr(qro, "input_contract", None),
                field="M21 QRO input_contract",
            )
            output_contract = _mapping(
                getattr(qro, "output_contract", None),
                field="M21 QRO output_contract",
            )
            if new_identity:
                if (
                    set(input_contract) != {"entry_source", "governed_asset_ref"}
                    or set(output_contract)
                    != {
                        "ide_strategy_ref",
                        "ide_strategy_snapshot_hash",
                        "governed_template_snapshot_hash",
                        "mock_label_ref",
                        "asset_category_ref",
                        "status",
                    }
                    or _text(input_contract.get("entry_source")) != "api"
                    or _text(output_contract.get("status"))
                    != "template_fork_recorded"
                ):
                    return False
                _exact(
                    input_contract.get("governed_asset_ref"),
                    field="M21 governed_asset_ref",
                )
                return (
                    _contract_ref(
                        qro,
                        "ide_strategy_ref",
                        prefix="ide_strategy:",
                    )
                    == anchor
                )
            if (
                set(input_contract) != {"entry_source", "asset_ref"}
                or set(output_contract)
                != {
                    "ide_strategy_ref",
                    "mock_label_ref",
                    "asset_category_ref",
                    "status",
                }
                or _text(input_contract.get("entry_source")) != "api"
                or _text(output_contract.get("status"))
                != "template_fork_recorded"
            ):
                return False
            _contract_ref(qro, "ide_strategy_ref", prefix="ide_strategy:")
            return _contract_ref(qro, "asset_ref") == anchor

        attestation = self._post_business_attestation_lineage(
            owner=owner,
            row=M21,
            anchor=anchor,
            predicate=predicate,
        )
        lineage = attestation.current
        governed_asset_ref = (
            _contract_ref(lineage.qro, "governed_asset_ref")
            if new_identity
            else anchor
        )
        output_contract = _mapping(
            getattr(lineage.qro, "output_contract", None),
            field="M21 QRO output_contract",
        )
        ide_strategy_ref = _contract_ref(
            lineage.qro,
            "ide_strategy_ref",
            prefix="ide_strategy:",
        )
        if self._context.ide_strategy_loader is None:
            raise PlatformSourceLineagePolicyM16M21Error(
                "M21 current IDE strategy loader is unavailable"
            )
        try:
            ide_strategy = self._context.ide_strategy_loader(
                ide_strategy_ref,
                owner,
            )
            asset = self._context.asset_lifecycle_registry.governed_asset(
                governed_asset_ref,
                owner_user_id=owner,
            )
            mock_asset = self._context.asset_lifecycle_registry.governed_asset_by_mock_label_ref(
                _text(asset.mock_label_ref),
                owner_user_id=owner,
            )
            category_asset = self._context.asset_lifecycle_registry.governed_asset_by_category_ref(
                _text(asset.asset_category_ref),
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"M21 IDE strategy/governed asset lookup failed:{type(exc).__name__}"
            ) from exc
        category = _enum_text(getattr(asset, "category", ""))
        if (
            not isinstance(ide_strategy, StrategyFile)
            or f"ide_strategy:{ide_strategy.strategy_id}" != ide_strategy_ref
            or not _text(ide_strategy.owner_username)
            or mock_asset != asset
            or category_asset != asset
            or _text(getattr(asset, "asset_ref", "")) != governed_asset_ref
            or (
                new_identity
                and _text(getattr(asset, "asset_type", "")) != "StrategyTemplate"
            )
            or category not in {"demo", "template", "example", "tutorial"}
            or not _text(getattr(asset, "display_label", ""))
        ):
            raise PlatformSourceLineagePolicyM16M21Error(
                "M21 IDE strategy/governed example is stale, hidden, or recombined"
            )
        expected_refs = {
            "mock_label_ref": _exact(
                asset.mock_label_ref,
                field="M21 mock_label_ref",
                prefix="mock_label:",
            ),
            "asset_category_ref": _exact(
                asset.asset_category_ref,
                field="M21 asset_category_ref",
                prefix="asset_category:",
            ),
        }
        _require_contract_refs(lineage.qro, expected_refs)
        if new_identity:
            if (
                _contract_ref(lineage.qro, "ide_strategy_ref") != anchor
                or _contract_ref(lineage.qro, "governed_asset_ref")
                != governed_asset_ref
                or _exact(
                    output_contract.get("ide_strategy_snapshot_hash"),
                    field="M21 ide_strategy_snapshot_hash",
                )
                != m21_ide_strategy_snapshot_hash(ide_strategy)
                or _exact(
                    output_contract.get("governed_template_snapshot_hash"),
                    field="M21 governed_template_snapshot_hash",
                )
                != m21_governed_template_snapshot_hash(asset)
                or not _text(asset.asset_category_ref).startswith(
                    f"asset_category:{_text(ide_strategy.asset_class)}:"
                )
            ):
                raise PlatformSourceLineagePolicyM16M21Error(
                    "M21 IDE strategy/governed template snapshot is stale or recombined"
                )
        elif _contract_ref(lineage.qro, "asset_ref") != anchor:
            raise PlatformSourceLineagePolicyM16M21Error(
                "M21 legacy governed asset contract is recombined"
            )
        return self._resolution(
            row=M21,
            anchor=anchor,
            lineage=lineage,
            lifecycle_ref=governed_asset_ref,
            math_spine_ref=_text(lineage.chain.chain_ref),
            specific_refs=_specific_refs(tuple(expected_refs), tuple(expected_refs.values())),
            primary_rag_asset_ref=governed_asset_ref,
            metadata=(
                *self._post_business_attestation_metadata(
                    attestation,
                    row=M21,
                ),
                ("asset_category", category),
                ("display_label", _text(asset.display_label)),
            ),
        )

    def resolve(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        if self._context.research_graph_view_factory is not None:
            graph = self._context.research_graph_view_factory()
            required = ("qro", "commands", "projection_index")
            missing = tuple(
                name
                for name in required
                if not callable(getattr(graph, name, None))
            )
            if missing:
                raise PlatformSourceLineagePolicyM16M21Error(
                    "fresh Research Graph view lacks required methods: "
                    + ", ".join(missing)
                )
            return type(self)(
                replace(
                    self._context,
                    research_graph_store=graph,
                    research_graph_view_factory=None,
                )
            ).resolve(
                owner_user_id=owner_user_id,
                m_row=m_row,
                anchor_ref=anchor_ref,
            )
        owner = _exact(owner_user_id, field="owner_user_id")
        row = str(getattr(m_row, "value", m_row) or "")
        if row not in SUPPORTED_ROWS:
            raise PlatformSourceLineagePolicyM16M21Error(
                f"unsupported M16-M21 policy row: {row!r}"
            )
        resolver = {
            M16: self._m16,
            M17: self._m17,
            M18: self._m18,
            M19: self._m19,
            M20: self._m20,
            M21: self._m21,
        }[row]
        return resolver(owner=owner, anchor=anchor_ref)

    def semantic_violations(
        self,
        resolution: PlatformSourceLineagePolicyResolution,
        *,
        owner_user_id: str,
        business_coverage: Any,
        capability_record: PlatformCapabilityRecord,
        rag_document: Any,
    ) -> tuple[str, ...]:
        """Re-resolve every typed relation and compare the derived snapshot."""

        violations: list[str] = []
        try:
            expected = self.resolve(
                owner_user_id=owner_user_id,
                m_row=resolution.m_row,
                anchor_ref=resolution.anchor_ref,
            )
        except Exception as exc:
            return (f"policy anchor is no longer current:{type(exc).__name__}",)
        if expected != resolution:
            violations.append("policy resolution differs from current typed stores")
        if _text(getattr(business_coverage, "recorded_by", "")) != owner_user_id:
            violations.append("business coverage owner mismatch")
        if _enum_text(getattr(business_coverage, "entry_source", "")) != expected.business_entry_source:
            violations.append("business coverage entry source mismatch")
        if _text(getattr(business_coverage, "entrypoint_ref", "")) != expected.business_entrypoint_ref:
            violations.append("business coverage entrypoint mismatch")
        if tuple(getattr(business_coverage, "qro_refs", ()) or ()) != (expected.qro_ref,):
            violations.append("business coverage QRO mismatch")
        if _text(getattr(capability_record, "m_row", "")) != expected.m_row:
            violations.append("capability row mismatch")
        if _text(capability_record.qro_ref) != expected.qro_ref:
            violations.append("capability QRO mismatch")
        if _text(capability_record.lifecycle_ref) != expected.lifecycle_ref:
            violations.append("capability lifecycle mismatch")
        if _text(capability_record.math_spine_ref) != expected.math_spine_ref:
            violations.append("capability Mathematical Spine mismatch")
        if _specific_map(capability_record) != {
            item.key: item.ref for item in expected.specific_refs
        }:
            violations.append("capability specific refs mismatch")
        if _text(getattr(rag_document, "asset_ref", "")) != expected.primary_rag_asset_ref:
            violations.append("reserved RAG asset mismatch")
        permission = getattr(rag_document, "permission", None)
        if owner_user_id not in tuple(getattr(permission, "allowed_users", ()) or ()):
            violations.append("reserved RAG owner permission mismatch")
        if expected.primary_rag_asset_ref not in tuple(
            getattr(permission, "allowed_assets", ()) or ()
        ):
            violations.append("reserved RAG asset permission mismatch")
        return tuple(violations)


def build_platform_source_lineage_policy_resolver_m16_m21(
    context: PlatformSourceLineagePoliciesM16M21Context,
) -> PlatformSourceLineagePolicyResolverM16M21:
    """Build the complete server-owned policy group for M16-M21."""

    return PlatformSourceLineagePolicyResolverM16M21(context)


__all__ = [
    "PlatformSourceLineagePoliciesM16M21Context",
    "PlatformSourceLineagePolicyM16M21Error",
    "PlatformSourceLineagePolicyResolverM16M21",
    "SUPPORTED_ROWS",
    "build_platform_source_lineage_policy_resolver_m16_m21",
]
