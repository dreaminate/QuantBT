"""Current typed-store adapters for GOAL section 14 rows M9-M15.

Rows are registered only when every required domain object has an exact getter
and the row can be joined to one current owner-scoped lineage.  Reference
shapes, RAG metadata, QRO strings, and generic goal-closure receipts are never
substituted for missing domain objects.  M9 resolves the typed execution-domain
closure receipt itself because that receipt revalidates the complete live
execution boundary against its backing stores.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable

from ..lineage.ids import content_hash
from .agent_workflow_closure import AGENT_WORKFLOW_ENTRYPOINT_REF
from .goal_coverage import goal_entrypoint_coverage_identity
from .platform_coverage import PlatformCapabilityRecord
from .qro_spine_binding import (
    QROSpineBindingError,
    platform_spine_binding_historical_command_ref,
)
from .platform_typed_sources import (
    PlatformRowLinkValidator,
    PlatformTypedSourceAdapter,
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)


M9 = "M9"
M10 = "M10"
M11 = "M11"
M12 = "M12"
M13 = "M13"
M14 = "M14"
M15 = "M15"

_SPINE_BINDING_ENTRYPOINT_BY_ROW = {
    M9: "api:research_os.platform.spine_bindings.m9",
    M10: "api:research_os.platform.spine_bindings.m10",
    M11: "api:research_os.platform.spine_bindings.m11",
    M12: "api:research_os.platform.spine_bindings.m12",
    M13: "api:research_os.platform.spine_bindings.m13_m14",
    M14: "api:research_os.platform.spine_bindings.m13_m14",
}
_BUSINESS_ENTRYPOINT_BY_ROW = {
    M9: ("api", "api:research_os.execution.order_intents"),
    M10: ("ide", "ide:strategy.run"),
    M11: ("api", "api:goal.lifecycle.closure"),
    M12: ("api", "api:models.gates.approve"),
    M13: ("agent_shell", AGENT_WORKFLOW_ENTRYPOINT_REF),
    M14: ("agent_shell", AGENT_WORKFLOW_ENTRYPOINT_REF),
}
_AGENT_WORKFLOW_GOAL_SECTIONS = ("§0", "§1", "§5", "§7", "§8")


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _row(record: PlatformCapabilityRecord) -> str:
    return _text(record.m_row)


def _specific(record: PlatformCapabilityRecord) -> dict[str, str]:
    return {_text(item.key): _text(item.ref) for item in record.specific_refs}


def _owner_of(value: Any) -> str:
    return _text(getattr(value, "owner_user_id", getattr(value, "owner", "")))


def _qro_type(value: Any) -> str:
    return _text(getattr(value, "qro_type", ""))


def _has_methods(value: Any, methods: tuple[str, ...]) -> bool:
    return value is not None and all(callable(getattr(value, method, None)) for method in methods)


def _accepted(value: Any) -> bool:
    return bool(getattr(value, "accepted", False))


def _call(label: str, fn: Callable[[], Any]) -> tuple[Any | None, list[str]]:
    try:
        return fn(), []
    except Exception as exc:  # noqa: BLE001 - every backing-store failure closes the row.
        return None, [f"{label} lookup failed:{type(exc).__name__}"]


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return vars(value)
    return value


def _state_hash(value: Any) -> str:
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


def _lifecycle_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _plain(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _component_by_link(
    components: tuple[Any, ...],
    link_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for component in components:
        links = getattr(component, "link_map", None)
        if not isinstance(links, dict):
            links = dict(getattr(component, "links", ()) or ())
        identity = _text(links.get(link_name))
        if not identity or identity in result:
            raise LookupError(f"workflow closure has ambiguous {link_name}")
        result[identity] = component
    return result


def _workflow_rag_violations(
    rag_index: Any,
    *,
    label: str,
    snapshot: Any,
    record: PlatformCapabilityRecord,
    owner: str,
    workflow_id: str,
) -> tuple[str, ...]:
    violations: list[str] = []
    usage_ref = _text(
        getattr(getattr(snapshot, "rag_usage", None), "component_ref", "")
    )
    usage, errors = _call(
        f"{label} strict RAG usage",
        lambda: rag_index.strict_usage_for_owner(
            usage_ref,
            owner_user_id=owner,
        ),
    )
    violations.extend(errors)
    if usage is None:
        return tuple(violations)
    decision, errors = _call(
        f"{label} strict RAG current check",
        lambda: rag_index.validate_current_usage(
            usage_ref,
            owner_user_id=owner,
        ),
    )
    violations.extend(errors)
    if decision is None or not _accepted(decision):
        violations.append(f"{label} strict RAG usage is not current")
    if (
        _owner_of(usage) != owner
        or _text(getattr(usage, "workflow_ref", "")) != workflow_id
        or _text(getattr(usage, "actor", "")) != "agent"
    ):
        violations.append(f"{label} strict RAG owner/workflow/actor mismatch")
    returned_document_ids = tuple(
        _text(getattr(item, "document_id", ""))
        for item in tuple(getattr(usage, "returned_documents", ()) or ())
    )
    row_document, errors = _call(
        f"{label} platform lineage RAG",
        lambda: rag_index.document_for_owner(
            _text(record.rag_ref),
            owner_user_id=owner,
            require_current=True,
        ),
    )
    violations.extend(errors)
    if row_document is None:
        return tuple(violations)
    metadata = getattr(row_document, "metadata", None)
    upstream = (
        metadata.get("upstream_business_rag")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(upstream, dict) or set(upstream) != {
        "usage_ref",
        "document_refs",
        "role",
    }:
        violations.append(
            f"{label} platform lineage RAG lacks exact upstream business RAG metadata"
        )
        return tuple(violations)
    bound_documents = upstream.get("document_refs")
    if not isinstance(bound_documents, list) or not bound_documents:
        violations.append(
            f"{label} upstream business RAG document binding is unavailable"
        )
        return tuple(violations)
    if (
        _text(upstream.get("usage_ref")) != usage_ref
        or _text(upstream.get("role")) != "upstream_business_context"
        or tuple(_text(item) for item in bound_documents) != returned_document_ids
    ):
        violations.append(
            f"{label} upstream business RAG usage/document binding mismatch"
        )
    if _text(record.rag_ref) in returned_document_ids:
        violations.append(
            f"{label} reserved platform lineage RAG cannot be its own upstream input"
        )
    return tuple(violations)


def _workflow_snapshot_binding_violations(
    context: "PlatformSourceAdaptersM9M15Context",
    *,
    label: str,
    snapshot: Any,
    record: PlatformCapabilityRecord,
    owner: str,
    workflow_id: str,
) -> tuple[str, ...]:
    """Join the immutable Agent Shell snapshot to the current binder metadata."""

    violations: list[str] = []
    document, errors = _call(
        f"{label} platform lineage RAG",
        lambda: context.rag_index.document_for_owner(
            _text(record.rag_ref),
            owner_user_id=owner,
            require_current=True,
        ),
    )
    violations.extend(errors)
    if document is None:
        return tuple(violations)
    raw_metadata = getattr(document, "metadata", None)
    metadata = (
        raw_metadata.get("row_policy") if isinstance(raw_metadata, dict) else None
    )
    required = {
        "business_graph_command_ref",
        "business_compiler_ir_ref",
        "business_compiler_pass_ref",
        "business_entry_source",
        "business_entrypoint_ref",
    }
    if not isinstance(metadata, dict) or not required.issubset(metadata):
        return (*violations, f"{label} row policy lacks historical workflow metadata")

    qro_component = getattr(snapshot, "qro", None)
    graph_component = getattr(snapshot, "graph_command", None)
    ir_component = getattr(snapshot, "compiler_ir", None)
    pass_component = getattr(snapshot, "compiler_pass", None)
    coverage_component = getattr(snapshot, "entrypoint_coverage", None)
    qro_ref = _text(getattr(qro_component, "component_ref", ""))
    graph_ref = _text(getattr(graph_component, "component_ref", ""))
    ir_ref = _text(getattr(ir_component, "component_ref", ""))
    pass_ref = _text(getattr(pass_component, "component_ref", ""))
    usage_ref = _text(
        getattr(getattr(snapshot, "rag_usage", None), "component_ref", "")
    )
    if (
        qro_ref != _text(record.qro_ref)
        or graph_ref != _text(metadata["business_graph_command_ref"])
        or ir_ref != _text(metadata["business_compiler_ir_ref"])
        or pass_ref != _text(metadata["business_compiler_pass_ref"])
        or _text(metadata["business_entry_source"]) != "agent_shell"
        or _text(metadata["business_entrypoint_ref"])
        != AGENT_WORKFLOW_ENTRYPOINT_REF
    ):
        violations.append(
            f"{label} workflow snapshot does not name the exact historical Agent Shell lineage"
        )
        return tuple(violations)

    commands = tuple(
        item
        for item in tuple(context.research_graph_store.commands() or ())
        if _text(getattr(item, "command_id", "")) == graph_ref
    )
    if len(commands) != 1:
        return (*violations, f"{label} historical Graph command is missing or ambiguous")
    command = commands[0]
    payload = getattr(command, "payload", None)
    historical_qro = payload.get("qro") if isinstance(payload, dict) else None
    compiler_snapshot, errors = _call(
        f"{label} canonical compiler snapshot",
        lambda: platform_compiler_snapshot(
            context.compiler_store,
            owner=owner,
        ),
    )
    violations.extend(errors)
    if compiler_snapshot is None:
        return tuple(violations)
    compiler_ir, errors = _call(
        f"{label} historical compiler IR",
        lambda: compiler_snapshot.ir(ir_ref),
    )
    violations.extend(errors)
    compiler_pass, errors = _call(
        f"{label} historical compiler pass",
        lambda: compiler_snapshot.compiler_pass(pass_ref),
    )
    violations.extend(errors)
    if compiler_ir is None or compiler_pass is None:
        return tuple(violations)
    component_values = (
        (qro_component, historical_qro, "current"),
        (graph_component, command, "current"),
        (ir_component, compiler_ir, "current"),
        (pass_component, compiler_pass, "passed"),
    )
    if any(
        _text(getattr(component, "principal_id", "")) != owner
        or _text(getattr(component, "status", "")) != status
        or _text(getattr(component, "state_hash", "")) != _state_hash(value)
        for component, value, status in component_values
    ):
        violations.append(
            f"{label} workflow snapshot historical component hash mismatch"
        )
    if (
        _owner_of(historical_qro) != owner
        or tuple(getattr(historical_qro, "mathematical_refs", ()) or ())
        or _text(getattr(command, "source", "")) != "agent_shell"
        or _text(getattr(command, "actor_source", "")) != "agent"
        or _text(getattr(command, "actor", "")) != owner
        or tuple(getattr(compiler_ir, "source_qro_refs", ()) or ()) != (qro_ref,)
        or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ())
        != (graph_ref,)
        or tuple(getattr(compiler_ir, "mathematical_spine_chain_refs", ()) or ())
        or _text(getattr(compiler_pass, "output_ir_ref", "")) != ir_ref
        or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ()) != (qro_ref,)
        or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
        != (graph_ref,)
        or _text(getattr(compiler_pass, "entry_source", "")) != "agent_shell"
        or _canonical_entrypoint(compiler_ir, compiler_pass)
        != AGENT_WORKFLOW_ENTRYPOINT_REF
    ):
        violations.append(f"{label} historical workflow compiler lineage mismatch")

    coverage_ref = _text(getattr(coverage_component, "component_ref", ""))
    expected_coverage_ref = goal_entrypoint_coverage_identity(
        entry_source="agent_shell",
        entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
        goal_sections=_AGENT_WORKFLOW_GOAL_SECTIONS,
        qro_refs=(qro_ref,),
        research_graph_command_refs=(graph_ref,),
        compiler_ir_refs=(ir_ref,),
        compiler_pass_refs=(pass_ref,),
    )
    links = getattr(coverage_component, "link_map", None)
    if not isinstance(links, dict):
        links = dict(getattr(coverage_component, "links", ()) or ())
    expected_links = {
        "entry_source": "agent_shell",
        "entrypoint_ref": AGENT_WORKFLOW_ENTRYPOINT_REF,
        "workflow_id": workflow_id,
        "rag_usage_ref": usage_ref,
        "qro_ref": qro_ref,
        "graph_command_ref": graph_ref,
        "compiler_ir_ref": ir_ref,
        "compiler_pass_ref": pass_ref,
    }
    if (
        coverage_ref != expected_coverage_ref
        or links != expected_links
        or _text(getattr(coverage_component, "principal_id", "")) != owner
        or _text(getattr(coverage_component, "status", "")) != "current"
        or not _valid_sha256(getattr(coverage_component, "state_hash", ""))
    ):
        violations.append(
            f"{label} historical workflow coverage is not structurally content-bound"
        )
    return tuple(violations)


@dataclass(frozen=True)
class PlatformSourceAdaptersM9M15Context:
    research_graph_store: Any = None
    compiler_store: Any = None
    execution_closure_registry: Any = None
    execution_order_intent_registry: Any = None
    market_data_registry: Any = None
    validation_methodology_registry: Any = None
    validation_depth_registry: Any = None
    backtest_evidence_registry: Any = None
    model_governance_registry: Any = None
    model_registry: Any = None
    asset_lifecycle_registry: Any = None
    lifecycle_transition_registry: Any = None
    agent_capability_ledger: Any = None
    agent_workflow_closure_registry: Any = None
    llm_call_record_store: Any = None
    llm_use_binding_store: Any = None
    onboarding_registry: Any = None
    canonical_spine_ledger: Any = None
    spine_chain_registry: Any = None
    rag_index: Any = None
    desk_topology_registry: Any = None
    llm_service_owner_user_id: str = ""


@dataclass(frozen=True)
class ResolvedExecutionBoundarySource:
    receipt: Any
    order_intent: Any
    market_data_use_validation: Any


@dataclass(frozen=True)
class ResolvedBacktestRunSource:
    qro: Any


@dataclass(frozen=True)
class ResolvedValidationMethodologySource:
    record: Any
    binding: Any


@dataclass(frozen=True)
class ResolvedValidationDepthSource:
    record: Any
    binding: Any


@dataclass(frozen=True)
class ResolvedModelGateSource:
    gate: Any


@dataclass(frozen=True)
class ResolvedGovernedAssetSource:
    asset_ref: str
    owner_user_id: str
    record: Any


@dataclass(frozen=True)
class ResolvedDAGCapabilitySource:
    source_ref: str
    owner_user_id: str
    workflow_id: str
    capability_kind: str
    record: Any


@dataclass(frozen=True)
class ResolvedDAGCheckpointSource:
    checkpoint_ref: str
    owner_user_id: str
    workflow_id: str
    dag_run: Any


@dataclass(frozen=True)
class ResolvedM14LLMGatewaySource:
    gateway_ref: str
    owner_user_id: str
    terminal_record: Any
    use_binding: Any


@dataclass(frozen=True)
class ResolvedServiceRoutingPolicySource:
    routing_policy_ref: str
    service_principal_ref: str
    record: Any


@dataclass(frozen=True)
class ResolvedServiceCredentialPoolSource:
    credential_pool_ref: str
    service_principal_ref: str
    record: Any


@dataclass(frozen=True)
class ResolvedTheoryImplementationBindingSource:
    binding_ref: str
    owner_user_id: str
    record: Any
    consistency_checks: tuple[Any, ...]


def _qro_identity_without_math(value: Any) -> dict[str, Any] | None:
    payload = _plain(value)
    if not isinstance(payload, dict) or "mathematical_refs" not in payload:
        return None
    return {
        str(key): child
        for key, child in payload.items()
        if str(key) != "mathematical_refs"
    }


def _canonical_entrypoint(compiler_ir: Any, compiler_pass: Any) -> str:
    refs = {
        _text(ref).removeprefix("entrypoint:")
        for group in (
            getattr(compiler_ir, "canonical_command_refs", ()),
            getattr(compiler_pass, "canonical_command_refs", ()),
        )
        for ref in tuple(group or ())
        if _text(ref).startswith("entrypoint:")
    }
    return next(iter(refs)) if len(refs) == 1 else ""


def _binding_lineage_violations(
    context: PlatformSourceAdaptersM9M15Context,
    *,
    record: PlatformCapabilityRecord,
    owner: str,
) -> tuple[str, ...]:
    """Validate current binder lineage and its immutable historical business head."""

    row = _row(record)
    if row not in _SPINE_BINDING_ENTRYPOINT_BY_ROW:
        return ()
    graph = context.research_graph_store
    compiler = context.compiler_store
    rag = context.rag_index
    violations: list[str] = []

    document, errors = _call(
        f"{row} platform lineage RAG",
        lambda: rag.document_for_owner(
            _text(record.rag_ref),
            owner_user_id=owner,
            require_current=True,
        ),
    )
    violations.extend(errors)
    if document is None:
        return tuple(violations)
    document_metadata = getattr(document, "metadata", None)
    metadata = (
        document_metadata.get("row_policy")
        if isinstance(document_metadata, dict)
        else None
    )
    required_metadata = (
        "row",
        "graph_command_ref",
        "compiler_ir_ref",
        "compiler_pass_ref",
        "binding_projection_ref",
        "business_graph_command_ref",
        "business_compiler_ir_ref",
        "business_compiler_pass_ref",
        "business_entry_source",
        "business_entrypoint_ref",
    )
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(key), str)
        or metadata[key] != metadata[key].strip()
        or not metadata[key]
        for key in required_metadata
    ):
        return (
            *violations,
            f"{row} platform lineage RAG lacks exact binding/business metadata",
        )
    if metadata["row"] != row:
        violations.append(f"{row} platform lineage RAG row metadata mismatch")
    if metadata["graph_command_ref"] != _text(record.research_graph_ref):
        violations.append(f"{row} capability Graph ref is not the current binding head")
    current_refs = (
        metadata["graph_command_ref"],
        metadata["compiler_ir_ref"],
        metadata["compiler_pass_ref"],
    )
    business_refs = (
        metadata["business_graph_command_ref"],
        metadata["business_compiler_ir_ref"],
        metadata["business_compiler_pass_ref"],
    )
    if any(current == business for current, business in zip(current_refs, business_refs)):
        violations.append(f"{row} binding and historical business refs are not independent")

    compiler_snapshot, errors = _call(
        f"{row} canonical compiler snapshot",
        lambda: platform_compiler_snapshot(compiler, owner=owner),
    )
    violations.extend(errors)
    if compiler_snapshot is None:
        return tuple(violations)

    qro, errors = _call(
        f"{row} current binding QRO",
        lambda: graph.qro(_text(record.qro_ref)),
    )
    violations.extend(errors)

    def exact_command(ref: str, label: str) -> Any:
        matches = tuple(
            item
            for item in tuple(graph.commands() or ())
            if _text(getattr(item, "command_id", "")) == ref
        )
        if len(matches) != 1:
            raise LookupError(f"{label} is missing or ambiguous")
        return matches[0]

    current_command, errors = _call(
        f"{row} current binding Graph command",
        lambda: exact_command(metadata["graph_command_ref"], "binding command"),
    )
    violations.extend(errors)
    business_command, errors = _call(
        f"{row} historical business Graph command",
        lambda: exact_command(
            metadata["business_graph_command_ref"],
            "historical business command",
        ),
    )
    violations.extend(errors)

    projections, errors = _call(
        f"{row} current binding projection",
        lambda: tuple(
            item
            for item in tuple(graph.projection_index(owner=owner) or ())
            if _text(getattr(item, "qro_id", "")) == _text(record.qro_ref)
        ),
    )
    violations.extend(errors)
    projection = None
    if projections is not None:
        if len(projections) != 1:
            violations.append(f"{row} current owner binding projection is missing or ambiguous")
        else:
            projection = projections[0]

    def exact_ir(ref: str) -> Any:
        return compiler_snapshot.ir(ref)

    def exact_pass(ref: str) -> Any:
        return compiler_snapshot.compiler_pass(ref)

    current_ir, errors = _call(
        f"{row} current binding compiler IR",
        lambda: exact_ir(metadata["compiler_ir_ref"]),
    )
    violations.extend(errors)
    current_pass, errors = _call(
        f"{row} current binding compiler pass",
        lambda: exact_pass(metadata["compiler_pass_ref"]),
    )
    violations.extend(errors)
    business_ir, errors = _call(
        f"{row} historical business compiler IR",
        lambda: exact_ir(metadata["business_compiler_ir_ref"]),
    )
    violations.extend(errors)
    business_pass, errors = _call(
        f"{row} historical business compiler pass",
        lambda: exact_pass(metadata["business_compiler_pass_ref"]),
    )
    violations.extend(errors)

    if qro is None or current_command is None or business_command is None:
        return tuple(violations)
    try:
        linked_business_ref = platform_spine_binding_historical_command_ref(
            current_command,
            owner_user_id=owner,
            qro_ref=_text(record.qro_ref),
            chain_ref=_text(record.math_spine_ref),
            entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[row],
        )
    except QROSpineBindingError as exc:
        violations.append(f"{row} current binding command provenance mismatch:{exc}")
    else:
        if linked_business_ref != metadata["business_graph_command_ref"]:
            violations.append(
                f"{row} binding command does not name the selected historical business command"
            )
    current_payload = getattr(current_command, "payload", None)
    current_command_qro = (
        current_payload.get("qro") if isinstance(current_payload, dict) else None
    )
    business_payload = getattr(business_command, "payload", None)
    business_qro = (
        business_payload.get("qro") if isinstance(business_payload, dict) else None
    )
    current_math = tuple(
        _text(item) for item in tuple(getattr(qro, "mathematical_refs", ()) or ())
    )
    business_math = tuple(
        _text(item)
        for item in tuple(getattr(business_qro, "mathematical_refs", ()) or ())
    )
    if (
        _owner_of(qro) != owner
        or _text(getattr(qro, "qro_id", "")) != _text(record.qro_ref)
        or current_command_qro != qro
        or _text(getattr(current_command, "actor", "")) != owner
        or _text(getattr(current_command, "source", "")) != "api"
        or current_math != (_text(record.math_spine_ref),)
    ):
        violations.append(f"{row} current binding QRO/Graph/math linkage mismatch")
    current_identity = _qro_identity_without_math(qro)
    business_identity = _qro_identity_without_math(business_qro)
    if (
        business_qro is None
        or _owner_of(business_qro) != owner
        or _text(getattr(business_qro, "qro_id", "")) != _text(record.qro_ref)
        or current_identity is None
        or business_identity != current_identity
        or business_math
    ):
        violations.append(f"{row} historical business QRO is stale or recombined")
    historical_business_commands = tuple(
        item
        for item in tuple(graph.commands() or ())
        for payload in (getattr(item, "payload", None),)
        for candidate in (
            payload.get("qro") if isinstance(payload, dict) else None,
        )
        if _text(getattr(candidate, "qro_id", "")) == _text(record.qro_ref)
        and not tuple(getattr(candidate, "mathematical_refs", ()) or ())
        and _qro_identity_without_math(candidate) == current_identity
    )
    if (
        len(historical_business_commands) != 1
        or historical_business_commands[0] != business_command
    ):
        violations.append(f"{row} historical business Graph head is missing or ambiguous")

    business_source, business_entrypoint = _BUSINESS_ENTRYPOINT_BY_ROW[row]
    expected_business_actor = owner
    if row == M12 and business_qro is not None:
        inputs = getattr(business_qro, "input_contract", None)
        expected_business_actor = (
            _text(inputs.get("delegated_actor")) if isinstance(inputs, dict) else ""
        )
        if not expected_business_actor or expected_business_actor == owner:
            violations.append(f"{row} historical reviewer is not independent")
    if (
        _text(getattr(business_command, "actor", "")) != expected_business_actor
        or _text(getattr(business_command, "source", "")) != business_source
        or (
            row in {M13, M14}
            and _text(getattr(business_command, "actor_source", "")) != "agent"
        )
        or metadata["business_entry_source"] != business_source
        or metadata["business_entrypoint_ref"] != business_entrypoint
    ):
        violations.append(f"{row} historical business command metadata mismatch")

    if projection is not None and (
        _text(getattr(projection, "projection_ref", ""))
        != metadata["binding_projection_ref"]
        or _owner_of(projection) != owner
        or _text(getattr(projection, "command_id", ""))
        != metadata["graph_command_ref"]
        or _text(getattr(projection, "actor", "")) != owner
        or _text(getattr(projection, "source", "")) != "api"
        or _text(getattr(projection, "actor_source", "")) != "user_manual"
        or tuple(
            _text(item)
            for item in tuple(getattr(projection, "mathematical_refs", ()) or ())
        )
        != (_text(record.math_spine_ref),)
    ):
        violations.append(f"{row} current binding projection linkage mismatch")

    def validate_compiler_pair(
        *,
        label: str,
        qro_value: Any,
        command: Any,
        compiler_ir: Any,
        compiler_pass: Any,
        expected_math_refs: tuple[str, ...],
        entry_source: str,
        entrypoint_ref: str,
    ) -> None:
        if compiler_ir is None or compiler_pass is None:
            return
        qro_ref = _text(getattr(qro_value, "qro_id", ""))
        command_ref = _text(getattr(command, "command_id", ""))
        try:
            lineage_pairs = tuple(
                (candidate_ir, candidate_pass)
                for candidate_ir in compiler_snapshot.irs
                if tuple(getattr(candidate_ir, "source_qro_refs", ()) or ())
                == (qro_ref,)
                and tuple(getattr(candidate_ir, "graph_command_refs", ()) or ())
                == (command_ref,)
                for candidate_pass in compiler_snapshot.passes
                if _text(getattr(candidate_pass, "output_ir_ref", ""))
                == _text(getattr(candidate_ir, "ir_ref", ""))
                and tuple(getattr(candidate_pass, "input_qro_refs", ()) or ())
                == (qro_ref,)
                and tuple(getattr(candidate_pass, "graph_command_refs", ()) or ())
                == (command_ref,)
                and _text(getattr(candidate_pass, "actor", "")) == owner
                and _text(getattr(candidate_pass, "status", "")).lower()
                == "compiled"
            )
        except Exception as exc:  # noqa: BLE001 - compiler history fails closed.
            violations.append(
                f"{row} {label} compiler history lookup failed:{type(exc).__name__}"
            )
            return
        if len(lineage_pairs) != 1 or lineage_pairs[0] != (
            compiler_ir,
            compiler_pass,
        ):
            violations.append(f"{row} {label} compiler lineage is missing or ambiguous")
        if (
            _owner_of(compiler_ir) != owner
            or _text(getattr(compiler_pass, "actor", "")) != owner
            or tuple(getattr(compiler_ir, "source_qro_refs", ()) or ())
            != (qro_ref,)
            or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ())
            != (command_ref,)
            or tuple(
                _text(item)
                for item in tuple(
                    getattr(compiler_ir, "mathematical_spine_chain_refs", ()) or ()
                )
            )
            != expected_math_refs
            or _text(getattr(compiler_pass, "output_ir_ref", ""))
            != _text(getattr(compiler_ir, "ir_ref", ""))
            or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
            != (qro_ref,)
            or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
            != (command_ref,)
            or _text(getattr(compiler_pass, "status", "")).lower() != "compiled"
            or _text(getattr(compiler_pass, "entry_source", "")) != entry_source
            or _canonical_entrypoint(compiler_ir, compiler_pass) != entrypoint_ref
        ):
            violations.append(f"{row} {label} compiler lineage mismatch")

    validate_compiler_pair(
        label="current binding",
        qro_value=qro,
        command=current_command,
        compiler_ir=current_ir,
        compiler_pass=current_pass,
        expected_math_refs=(_text(record.math_spine_ref),),
        entry_source="api",
        entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[row],
    )
    validate_compiler_pair(
        label="historical business",
        qro_value=business_qro,
        command=business_command,
        compiler_ir=business_ir,
        compiler_pass=business_pass,
        expected_math_refs=(),
        entry_source=business_source,
        entrypoint_ref=business_entrypoint,
    )
    return tuple(violations)


_STATIC_UNAVAILABLE: dict[str, tuple[str, ...]] = {}


def unavailable_platform_source_rows_m9_m15(
    context: PlatformSourceAdaptersM9M15Context,
) -> dict[str, tuple[str, ...]]:
    """Report exact blockers; unavailable rows are never partially registered."""

    unavailable = dict(_STATIC_UNAVAILABLE)
    requirements: dict[str, tuple[tuple[str, Any, tuple[str, ...]], ...]] = {
        M9: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "compiler_store",
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
            ),
            ("rag_index", context.rag_index, ("document_for_owner",)),
            (
                "execution_closure_registry",
                context.execution_closure_registry,
                ("receipt", "validate_current"),
            ),
            (
                "execution_order_intent_registry",
                context.execution_order_intent_registry,
                ("intent",),
            ),
            (
                "market_data_registry",
                context.market_data_registry,
                ("capability_matrix", "use_validation"),
            ),
        ),
        M10: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "compiler_store",
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
            ),
            ("rag_index", context.rag_index, ("document_for_owner",)),
            (
                "validation_methodology_registry",
                context.validation_methodology_registry,
                ("methodology", "methodology_binding"),
            ),
            (
                "validation_depth_registry",
                context.validation_depth_registry,
                ("depth", "depth_binding"),
            ),
            (
                "backtest_evidence_registry",
                context.backtest_evidence_registry,
                (
                    "attribution",
                    "monitor",
                    "validate_current_attribution",
                    "validate_current_monitor",
                ),
            ),
            (
                "spine_chain_registry",
                context.spine_chain_registry,
                ("verified_chain",),
            ),
        ),
        M11: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "compiler_store",
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
            ),
            ("rag_index", context.rag_index, ("document_for_owner",)),
            (
                "asset_lifecycle_registry",
                context.asset_lifecycle_registry,
                ("governed_asset",),
            ),
            (
                "lifecycle_transition_registry",
                context.lifecycle_transition_registry,
                ("transition", "receipt", "validate_current"),
            ),
        ),
        M12: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "compiler_store",
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
            ),
            ("rag_index", context.rag_index, ("document_for_owner",)),
            (
                "model_governance_registry",
                context.model_governance_registry,
                ("passport", "recertification_record", "current_head_hash"),
            ),
            (
                "model_registry",
                context.model_registry,
                ("promotion_gate", "promotion_reviewer_authority_evidence"),
            ),
            (
                "spine_chain_registry",
                context.spine_chain_registry,
                ("verified_chain",),
            ),
        ),
        M13: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "compiler_store",
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
            ),
            (
                "rag_index",
                context.rag_index,
                (
                    "strict_usage_for_owner",
                    "validate_current_usage",
                    "document_for_owner",
                ),
            ),
            (
                "agent_capability_ledger",
                context.agent_capability_ledger,
                ("record", "current_head", "validate_current"),
            ),
            (
                "agent_workflow_closure_registry",
                context.agent_workflow_closure_registry,
                ("receipt", "current_receipt"),
            ),
        ),
        M14: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "compiler_store",
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
            ),
            (
                "llm_call_record_store",
                context.llm_call_record_store,
                ("resolve_terminal_record",),
            ),
            (
                "llm_use_binding_store",
                context.llm_use_binding_store,
                ("binding_for_terminal", "validate_current"),
            ),
            (
                "onboarding_registry",
                context.onboarding_registry,
                ("routing_policy", "credential_pool"),
            ),
            (
                "canonical_spine_ledger",
                context.canonical_spine_ledger,
                ("binding", "checks_for"),
            ),
            (
                "spine_chain_registry",
                context.spine_chain_registry,
                ("verified_chain",),
            ),
            (
                "rag_index",
                context.rag_index,
                (
                    "strict_usage_for_owner",
                    "validate_current_usage",
                    "document_for_owner",
                ),
            ),
            (
                "agent_workflow_closure_registry",
                context.agent_workflow_closure_registry,
                ("current_receipt",),
            ),
        ),
        M15: (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "desk_topology_registry",
                context.desk_topology_registry,
                (
                    "topology",
                    "current_topology",
                    "receipt",
                    "validate_topology_current",
                    "validate_current_receipt",
                ),
            ),
        ),
    }
    for row, dependencies in requirements.items():
        missing = tuple(
            name for name, value, methods in dependencies if not _has_methods(value, methods)
        )
        if row == M14 and not _text(context.llm_service_owner_user_id):
            missing = (*missing, "llm_service_owner_user_id")
        if missing:
            unavailable[row] = tuple(f"missing dependency:{name}" for name in missing)
    return unavailable


def _m9(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    closures = context.execution_closure_registry
    intents = context.execution_order_intent_registry
    market_data = context.market_data_registry

    def load_boundary(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M9 or not ref.startswith("execution_closure_receipt:"):
            raise LookupError("M9 ExecutionBoundary must be a real execution closure receipt")
        receipt = closures.receipt(ref, owner_user_id=owner)
        if (
            _text(getattr(receipt, "receipt_ref", "")) != ref
            or _text(getattr(receipt, "canonical_receipt_ref", "")) != ref
            or _owner_of(receipt) != owner
        ):
            raise LookupError("M9 execution closure identity/owner mismatch")
        current = closures.validate_current(ref, owner_user_id=owner)
        if not _accepted(current):
            raise LookupError("M9 execution closure receipt is not current")
        intent = intents.intent(_text(getattr(receipt, "order_intent_ref", "")))
        if (
            _text(getattr(intent, "order_intent_ref", ""))
            != _text(getattr(receipt, "order_intent_ref", ""))
            or _text(getattr(intent, "recorded_by", "")) != owner
        ):
            raise LookupError("M9 execution order intent owner/identity mismatch")
        use_ref = _text(getattr(intent, "market_data_use_validation_ref", ""))
        use_validation = market_data.use_validation(use_ref, owner_user_id=owner)
        if (
            _text(getattr(use_validation, "validation_ref", "")) != use_ref
            or _text(getattr(use_validation, "recorded_by", "")) != owner
        ):
            raise LookupError("M9 market-data validation owner/identity mismatch")
        return ResolvedExecutionBoundarySource(receipt, intent, use_validation)

    def validate_boundary(
        value: ResolvedExecutionBoundarySource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        receipt = value.receipt
        intent = value.order_intent
        use_validation = value.market_data_use_validation
        expected = _specific(record).get("execution_boundary_ref")
        if _owner_of(receipt) != owner:
            violations.append("M9 execution closure owner mismatch")
        if _text(getattr(receipt, "receipt_ref", "")) != expected:
            violations.append("M9 execution closure identity mismatch")
        if _text(getattr(intent, "recorded_by", "")) != owner:
            violations.append("M9 execution order intent owner mismatch")
        if _text(getattr(receipt, "order_intent_ref", "")) != _text(
            getattr(intent, "order_intent_ref", "")
        ):
            violations.append("M9 execution closure/order-intent mismatch")
        if _text(getattr(use_validation, "recorded_by", "")) != owner:
            violations.append("M9 market-data validation owner mismatch")
        if _text(getattr(intent, "market_data_use_validation_ref", "")) != _text(
            getattr(use_validation, "validation_ref", "")
        ):
            violations.append("M9 order-intent/market-data validation mismatch")
        current, errors = _call(
            "M9 current execution closure",
            lambda: closures.validate_current(expected or "", owner_user_id=owner),
        )
        violations.extend(errors)
        if current is None or not _accepted(current):
            violations.append("M9 execution closure is not current")
        return tuple(violations)

    def load_matrix(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M9:
            raise LookupError("MarketCapabilityMatrix is not an M9 source")
        matrix = market_data.capability_matrix(ref, owner_user_id=owner)
        if _text(getattr(matrix, "matrix_ref", "")) != ref:
            raise LookupError("M9 MarketCapabilityMatrix identity mismatch")
        return matrix

    def validate_matrix(
        value: Any,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        if _text(getattr(value, "matrix_ref", "")) != _specific(record).get(
            "market_capability_matrix_ref"
        ):
            return ("M9 MarketCapabilityMatrix identity mismatch",)
        return ()

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        boundary = values.get("execution_boundary_ref")
        matrix = values.get("market_capability_matrix_ref")
        if not isinstance(boundary, ResolvedExecutionBoundarySource) or matrix is None:
            return ("M9 requires current execution closure and MarketCapabilityMatrix",)
        violations = list(
            _binding_lineage_violations(context, record=record, owner=owner)
        )
        receipt = boundary.receipt
        intent = boundary.order_intent
        use_validation = boundary.market_data_use_validation
        current, errors = _call(
            "M9 current execution closure",
            lambda: closures.validate_current(
                _text(getattr(receipt, "receipt_ref", "")),
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        if current is None or not _accepted(current):
            violations.append("M9 execution closure is not current")
        qro, errors = _call("M9 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is None:
            return tuple(violations)
        if _owner_of(qro) != owner or _qro_type(qro) != "ExecutionPolicy":
            violations.append("M9 QRO owner/type mismatch")
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        if not isinstance(input_contract, dict) or not isinstance(output_contract, dict):
            violations.append("M9 QRO input/output contracts are unavailable")
            return tuple(violations)
        input_pairs = (
            ("order_intent_ref", getattr(intent, "order_intent_ref", "")),
            (
                "market_data_use_validation_ref",
                getattr(intent, "market_data_use_validation_ref", ""),
            ),
            ("runtime", getattr(intent, "runtime", "")),
            ("asset_class", getattr(intent, "asset_class", "")),
            ("instrument_ref", getattr(intent, "instrument_ref", "")),
            ("side", getattr(intent, "side", "")),
            ("order_type", getattr(intent, "order_type", "")),
        )
        for key, expected in input_pairs:
            if _text(input_contract.get(key)) != _text(expected):
                violations.append(f"M9 QRO {key} mismatch")
        output_pairs = (
            ("execution_policy_ref", getattr(intent, "execution_policy_ref", "")),
            ("risk_policy_ref", getattr(intent, "risk_policy_ref", "")),
            (
                "market_data_use_validation_ref",
                getattr(intent, "market_data_use_validation_ref", ""),
            ),
            ("permission_gate_ref", getattr(intent, "permission_gate_ref", "")),
            ("order_guard_ref", getattr(intent, "order_guard_ref", "")),
            ("kill_switch_ref", getattr(intent, "kill_switch_ref", "")),
            (
                "responsibility_boundary_ref",
                getattr(intent, "responsibility_boundary_ref", ""),
            ),
        )
        for key, expected in output_pairs:
            if _text(output_contract.get(key)) != _text(expected):
                violations.append(f"M9 QRO {key} mismatch")
        if _text(output_contract.get("status")) != "order_intent_recorded":
            violations.append("M9 QRO order-intent status mismatch")
        if output_contract.get("place_order_called") is not False:
            violations.append("M9 order-intent QRO must not claim an order side effect")
        snapshot = getattr(receipt, "snapshot", None)
        snapshot_pairs = (
            ("owner_user_id", owner),
            ("runtime", getattr(intent, "runtime", "")),
            ("asset_class", getattr(intent, "asset_class", "")),
            ("instrument_ref", getattr(intent, "instrument_ref", "")),
            ("venue_ref", getattr(intent, "venue_ref", "")),
        )
        for key, expected in snapshot_pairs:
            if _text(getattr(snapshot, key, "")) != _text(expected):
                violations.append(f"M9 execution closure snapshot {key} mismatch")
        if _text(record.lifecycle_ref) != _text(getattr(receipt, "receipt_ref", "")):
            violations.append("M9 common lifecycle ref is not the current execution closure")
        if not bool(getattr(use_validation, "accepted", False)) or tuple(
            getattr(use_validation, "violation_codes", ()) or ()
        ):
            violations.append("M9 market-data use validation is not accepted")
        if _text(getattr(use_validation, "capability_matrix_ref", "")) != _text(
            getattr(matrix, "matrix_ref", "")
        ):
            violations.append("M9 MarketCapabilityMatrix/use-validation mismatch")
        if _text(getattr(use_validation, "use_context", "")) != _text(
            getattr(intent, "runtime", "")
        ):
            violations.append("M9 market-data validation/runtime mismatch")
        if _text(getattr(matrix, "asset_class", "")) != _text(
            getattr(intent, "asset_class", "")
        ):
            violations.append("M9 MarketCapabilityMatrix asset-class mismatch")
        if _text(getattr(intent, "instrument_ref", "")) not in tuple(
            _text(item) for item in tuple(getattr(use_validation, "instrument_refs", ()) or ())
        ):
            violations.append("M9 execution instrument is absent from market-data validation")
        runtime = _text(getattr(intent, "runtime", ""))
        capability_flag = {
            "paper": "paper",
            "testnet": "testnet",
            "live": "live",
        }.get(runtime)
        if capability_flag is None or getattr(matrix, capability_flag, None) is not True:
            violations.append("M9 MarketCapabilityMatrix does not allow execution runtime")
        return tuple(violations)

    return (
        {
            (M9, "execution_boundary_ref"): PlatformTypedSourceAdapter(
                source_kind="current_execution_closure_boundary",
                load=load_boundary,
                validate_linkage=validate_boundary,
            ),
            (M9, "market_capability_matrix_ref"): PlatformTypedSourceAdapter(
                source_kind="owner_market_capability_matrix",
                load=load_matrix,
                validate_linkage=validate_matrix,
            ),
        },
        validate_row,
    )


def _m10(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    methodologies = context.validation_methodology_registry
    depths = context.validation_depth_registry
    evidence = context.backtest_evidence_registry
    chains = context.spine_chain_registry

    def load_backtest(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M10 or ref != _text(record.qro_ref):
            raise LookupError("M10 BacktestRun must be the exact persisted row QRO")
        qro = graph.qro(ref)
        if _text(getattr(qro, "qro_id", "")) != ref:
            raise LookupError("M10 BacktestRun QRO identity mismatch")
        if _owner_of(qro) != owner or _qro_type(qro) != "BacktestRun":
            raise LookupError("M10 BacktestRun QRO owner/type mismatch")
        return ResolvedBacktestRunSource(qro)

    def validate_backtest(
        value: ResolvedBacktestRunSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        qro = value.qro
        expected = _specific(record).get("backtest_run_ref")
        if _text(getattr(qro, "qro_id", "")) != expected or expected != _text(
            record.qro_ref
        ):
            violations.append("M10 BacktestRun/QRO identity mismatch")
        if _owner_of(qro) != owner or _qro_type(qro) != "BacktestRun":
            violations.append("M10 BacktestRun QRO owner/type mismatch")
        return tuple(violations)

    def load_methodology(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M10:
            raise LookupError("ValidationMethodology is not an M10 source")
        value = methodologies.methodology(ref, owner_user_id=owner)
        binding = methodologies.methodology_binding(ref, owner_user_id=owner)
        if _text(getattr(value, "validation_ref", "")) != ref:
            raise LookupError("M10 ValidationMethodology identity mismatch")
        return ResolvedValidationMethodologySource(value, binding)

    def validate_methodology(
        value: ResolvedValidationMethodologySource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _text(getattr(value.record, "validation_ref", "")) != _specific(
            record
        ).get("validation_methodology_ref"):
            violations.append("M10 ValidationMethodology identity mismatch")
        if _owner_of(value.binding) != owner:
            violations.append("M10 ValidationMethodology owner binding mismatch")
        if not _text(getattr(value.binding, "recorded_by", "")):
            violations.append("M10 ValidationMethodology lacks a recorded actor")
        return tuple(violations)

    def load_depth(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M10:
            raise LookupError("ValidationDepth is not an M10 source")
        value = depths.depth(ref, owner_user_id=owner)
        binding = depths.depth_binding(ref, owner_user_id=owner)
        if _text(getattr(value, "depth_ref", "")) != ref:
            raise LookupError("M10 ValidationDepth identity mismatch")
        return ResolvedValidationDepthSource(value, binding)

    def validate_depth(
        value: ResolvedValidationDepthSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _text(getattr(value.record, "depth_ref", "")) != _specific(record).get(
            "validation_depth_ref"
        ):
            violations.append("M10 ValidationDepth identity mismatch")
        if _owner_of(value.binding) != owner:
            violations.append("M10 ValidationDepth owner binding mismatch")
        if not _text(getattr(value.binding, "recorded_by", "")):
            violations.append("M10 ValidationDepth lacks a recorded actor")
        return tuple(violations)

    def load_attribution(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M10 or not ref.startswith("attribution:"):
            raise LookupError("M10 Attribution ref is not canonical")
        value = evidence.attribution(ref, owner_user_id=owner)
        decision = evidence.validate_current_attribution(ref, owner_user_id=owner)
        if (
            _text(getattr(value, "attribution_ref", "")) != ref
            or _owner_of(value) != owner
            or not _accepted(decision)
        ):
            raise LookupError("M10 Attribution is not the current owner record")
        return value

    def validate_attribution(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        expected = _specific(record).get("attribution_ref")
        if _owner_of(value) != owner:
            violations.append("M10 Attribution owner mismatch")
        if _text(getattr(value, "attribution_ref", "")) != expected:
            violations.append("M10 Attribution identity mismatch")
        decision, errors = _call(
            "M10 current Attribution",
            lambda: evidence.validate_current_attribution(
                expected or "",
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        if decision is None or not _accepted(decision):
            violations.append("M10 Attribution is not current")
        return tuple(violations)

    def load_monitor(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M10 or not ref.startswith("monitor:"):
            raise LookupError("M10 Monitor ref is not canonical")
        value = evidence.monitor(ref, owner_user_id=owner)
        decision = evidence.validate_current_monitor(ref, owner_user_id=owner)
        if (
            _text(getattr(value, "monitor_ref", "")) != ref
            or _owner_of(value) != owner
            or not _accepted(decision)
        ):
            raise LookupError("M10 Monitor is not the current owner record")
        return value

    def validate_monitor(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        expected = _specific(record).get("monitor_ref")
        if _owner_of(value) != owner:
            violations.append("M10 Monitor owner mismatch")
        if _text(getattr(value, "monitor_ref", "")) != expected:
            violations.append("M10 Monitor identity mismatch")
        decision, errors = _call(
            "M10 current Monitor",
            lambda: evidence.validate_current_monitor(
                expected or "",
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        if decision is None or not _accepted(decision):
            violations.append("M10 Monitor is not current")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        run = values.get("backtest_run_ref")
        methodology = values.get("validation_methodology_ref")
        depth = values.get("validation_depth_ref")
        attribution = values.get("attribution_ref")
        monitor = values.get("monitor_ref")
        if (
            not isinstance(run, ResolvedBacktestRunSource)
            or not isinstance(methodology, ResolvedValidationMethodologySource)
            or not isinstance(depth, ResolvedValidationDepthSource)
            or attribution is None
            or monitor is None
        ):
            return ("M10 requires BacktestRun, methodology, depth, Attribution, and Monitor",)
        violations = list(
            _binding_lineage_violations(context, record=record, owner=owner)
        )
        qro = run.qro
        methodology_record = methodology.record
        methodology_binding = methodology.binding
        depth_record = depth.record
        depth_binding = depth.binding
        backtest_ref = _specific(record).get("backtest_run_ref", "")
        source_run_ref = _text(getattr(methodology_binding, "source_run_ref", ""))
        if not source_run_ref.startswith("ide_run:"):
            violations.append("M10 methodology source is not a persisted IDE run")
        output_contract = getattr(qro, "output_contract", None)
        qro_source_run_id = ""
        if isinstance(output_contract, dict):
            qro_source_run_id = _text(
                output_contract.get("source_run_id") or output_contract.get("run_id")
            )
        if qro_source_run_id != source_run_ref.removeprefix("ide_run:"):
            violations.append("M10 BacktestRun QRO/source IDE run mismatch")
        for label, binding in (
            ("ValidationMethodology", methodology_binding),
            ("ValidationDepth", depth_binding),
        ):
            if _owner_of(binding) != owner:
                violations.append(f"M10 {label} owner binding mismatch")
            if _text(getattr(binding, "backtest_run_ref", "")) != backtest_ref:
                violations.append(f"M10 {label}/BacktestRun mismatch")
            if _text(getattr(binding, "source_run_ref", "")) != source_run_ref:
                violations.append(f"M10 {label}/source-run mismatch")
        attribution_pairs = (
            ("owner_user_id", owner),
            ("backtest_run_ref", backtest_ref),
            ("source_run_ref", source_run_ref),
            (
                "validation_methodology_ref",
                getattr(methodology_record, "validation_ref", ""),
            ),
            ("validation_depth_ref", getattr(depth_record, "depth_ref", "")),
        )
        for field, expected in attribution_pairs:
            if _text(getattr(attribution, field, "")) != _text(expected):
                violations.append(f"M10 Attribution {field} mismatch")
        if not _text(getattr(attribution, "recorded_by", "")):
            violations.append("M10 Attribution lacks a recorded actor")
        expected_cost_refs = {
            _text(item)
            for item in (
                *tuple(getattr(methodology_record, "cost_model_refs", ()) or ()),
                *tuple(getattr(depth_record, "cost_model_refs", ()) or ()),
            )
            if _text(item)
        }
        if set(tuple(getattr(attribution, "cost_model_refs", ()) or ())) != expected_cost_refs:
            violations.append("M10 Attribution cost-model binding mismatch")
        if (
            _owner_of(monitor) != owner
            or _text(getattr(monitor, "backtest_run_ref", "")) != backtest_ref
            or _text(getattr(monitor, "attribution_ref", ""))
            != _text(getattr(attribution, "attribution_ref", ""))
        ):
            violations.append("M10 Monitor owner/BacktestRun/Attribution mismatch")
        if _text(record.lifecycle_ref) != _text(getattr(monitor, "monitor_ref", "")):
            violations.append("M10 common lifecycle ref is not the current Monitor")
        if not _text(getattr(monitor, "recorded_by", "")):
            violations.append("M10 Monitor lacks a recorded actor")
        if bool(getattr(monitor, "used_dsr_as_primary_live_alert", False)):
            violations.append("M10 Monitor uses DSR as the primary live alert")
        attribution_current, errors = _call(
            "M10 current Attribution",
            lambda: evidence.validate_current_attribution(
                _text(getattr(attribution, "attribution_ref", "")),
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        if attribution_current is None or not _accepted(attribution_current):
            violations.append("M10 Attribution is not current")
        monitor_current, errors = _call(
            "M10 current Monitor",
            lambda: evidence.validate_current_monitor(
                _text(getattr(monitor, "monitor_ref", "")),
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        if monitor_current is None or not _accepted(monitor_current):
            violations.append("M10 Monitor is not current")
        chain, errors = _call(
            "M10 Mathematical Spine chain",
            lambda: chains.verified_chain(_text(record.math_spine_ref), owner=owner),
        )
        violations.extend(errors)
        if chain is None:
            return tuple(violations)
        chain_pairs = (
            ("backtest_run_ref", backtest_ref),
            ("attribution_ref", getattr(attribution, "attribution_ref", "")),
            ("monitor_ref", getattr(monitor, "monitor_ref", "")),
        )
        for field, expected in chain_pairs:
            if _text(getattr(chain, field, "")) != _text(expected):
                violations.append(f"M10 Mathematical Spine {field} mismatch")
        validation_refs = {
            _text(item) for item in tuple(getattr(chain, "validation_refs", ()) or ())
        }
        required_validation_refs = {
            _text(getattr(methodology_record, "validation_ref", "")),
            _text(getattr(depth_record, "depth_ref", "")),
        }
        if not required_validation_refs.issubset(validation_refs):
            violations.append("M10 Mathematical Spine lacks methodology/depth refs")
        chain_math_refs = {
            _text(item)
            for item in (
                *tuple(getattr(chain, "theory_binding_refs", ()) or ()),
                *tuple(getattr(chain, "consistency_check_refs", ()) or ()),
                *tuple(getattr(chain, "evidence_refs", ()) or ()),
                *tuple(getattr(chain, "validation_refs", ()) or ()),
            )
        }
        if not set(tuple(getattr(monitor, "mathematical_trigger_refs", ()) or ())).issubset(
            chain_math_refs
        ):
            violations.append("M10 Monitor mathematical triggers are not spine-bound")
        return tuple(violations)

    return (
        {
            (M10, "backtest_run_ref"): PlatformTypedSourceAdapter(
                source_kind="owner_backtest_run_qro",
                load=load_backtest,
                validate_linkage=validate_backtest,
            ),
            (M10, "validation_methodology_ref"): PlatformTypedSourceAdapter(
                source_kind="owner_validation_methodology",
                load=load_methodology,
                validate_linkage=validate_methodology,
            ),
            (M10, "validation_depth_ref"): PlatformTypedSourceAdapter(
                source_kind="owner_validation_depth",
                load=load_depth,
                validate_linkage=validate_depth,
            ),
            (M10, "attribution_ref"): PlatformTypedSourceAdapter(
                source_kind="current_backtest_attribution",
                load=load_attribution,
                validate_linkage=validate_attribution,
            ),
            (M10, "monitor_ref"): PlatformTypedSourceAdapter(
                source_kind="current_backtest_monitor",
                load=load_monitor,
                validate_linkage=validate_monitor,
            ),
        },
        validate_row,
    )


def _m11(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    assets = context.asset_lifecycle_registry
    transitions = context.lifecycle_transition_registry

    def load_asset(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M11 or not ref.startswith("governed_asset:"):
            raise LookupError("GovernedAsset ref is not canonical for M11")
        value = assets.governed_asset(ref, owner_user_id=owner)
        if _text(getattr(value, "asset_ref", "")) != ref:
            raise LookupError("GovernedAsset identity mismatch")
        return ResolvedGovernedAssetSource(ref, owner, value)

    def validate_asset(
        value: ResolvedGovernedAssetSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner:
            violations.append("M11 GovernedAsset owner mismatch")
        if value.asset_ref != _specific(record).get("governed_asset_ref"):
            violations.append("M11 GovernedAsset identity mismatch")
        if _text(getattr(value.record, "asset_ref", "")) != value.asset_ref:
            violations.append("M11 GovernedAsset stored identity mismatch")
        return tuple(violations)

    def load_transition(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M11 or not ref.startswith("lifecycle_transition:"):
            raise LookupError("LifecycleTransition ref is not canonical for M11")
        value = transitions.transition(ref, owner_user_id=owner)
        if (
            _text(getattr(value, "transition_ref", "")) != ref
            or _owner_of(value) != owner
            or _text(getattr(value, "canonical_ref", "")) != ref
        ):
            raise LookupError("LifecycleTransition identity/owner mismatch")
        return value

    def validate_transition(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("M11 LifecycleTransition owner mismatch")
        if _text(getattr(value, "transition_ref", "")) != _specific(record).get(
            "lifecycle_transition_ref"
        ):
            violations.append("M11 LifecycleTransition identity mismatch")
        if _text(getattr(value, "canonical_ref", "")) != _text(
            getattr(value, "transition_ref", "")
        ):
            violations.append("M11 LifecycleTransition content identity mismatch")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        asset_source = values.get("governed_asset_ref")
        transition = values.get("lifecycle_transition_ref")
        if not isinstance(asset_source, ResolvedGovernedAssetSource) or transition is None:
            return ("M11 requires exact GovernedAsset and LifecycleTransition objects",)
        asset = asset_source.record
        violations = list(
            _binding_lineage_violations(context, record=record, owner=owner)
        )
        qro, errors = _call("M11 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is None:
            return tuple(violations)
        if _owner_of(qro) != owner or _qro_type(qro) != "ValidationDossier":
            violations.append("M11 QRO must be an owner-scoped ValidationDossier")
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        if not isinstance(input_contract, dict) or set(input_contract) != {
            "entry_source",
            "lifecycle_transition_refs",
        }:
            violations.append("M11 lifecycle QRO input contract is inexact")
            return tuple(violations)
        if not isinstance(output_contract, dict) or set(output_contract) != {
            "lifecycle_closure_receipt_ref",
            "asset_count",
            "asset_types",
            "status",
        }:
            violations.append("M11 lifecycle QRO output contract is inexact")
            return tuple(violations)
        receipt_ref = _text(output_contract.get("lifecycle_closure_receipt_ref"))
        receipt, errors = _call(
            "M11 lifecycle receipt",
            lambda: transitions.receipt(receipt_ref, owner_user_id=owner),
        )
        violations.extend(errors)
        if receipt is None:
            return tuple(violations)
        decision, errors = _call(
            "M11 lifecycle current check",
            lambda: transitions.validate_current(receipt_ref, owner_user_id=owner),
        )
        violations.extend(errors)
        if decision is None or not _accepted(decision):
            violations.append("M11 lifecycle closure receipt is not current")
        transition_refs = tuple(getattr(receipt, "transition_refs", ()) or ())
        asset_refs = tuple(getattr(receipt, "current_asset_refs", ()) or ())
        asset_hashes = tuple(getattr(receipt, "current_asset_sha256s", ()) or ())
        if not (len(transition_refs) == len(asset_refs) == len(asset_hashes)):
            violations.append("M11 lifecycle receipt arrays are misaligned")
        try:
            index = transition_refs.index(_text(getattr(transition, "transition_ref", "")))
        except ValueError:
            index = -1
            violations.append("M11 transition is not a current lifecycle head")
        if index >= 0:
            if asset_refs[index] != _text(getattr(asset, "asset_ref", "")):
                violations.append("M11 transition/receipt recombine a different current asset")
            if asset_hashes[index] != _lifecycle_sha256(asset):
                violations.append("M11 current governed asset hash drifted")
        before, errors = _call(
            "M11 before asset",
            lambda: assets.governed_asset(
                _text(getattr(transition, "before_asset_ref", "")),
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        exact_pairs = (
            (record.lifecycle_ref, receipt_ref, "common lifecycle receipt"),
            (getattr(transition, "after_asset_ref", ""), getattr(asset, "asset_ref", ""), "after asset"),
            (getattr(transition, "to_state", ""), getattr(asset, "lifecycle_state", ""), "to state"),
            (getattr(transition, "after_asset_sha256", ""), _lifecycle_sha256(asset), "after hash"),
        )
        for actual, expected, label in exact_pairs:
            if _text(actual) != _text(expected):
                violations.append(f"M11 {label} mismatch")
        if before is not None:
            if _text(getattr(transition, "from_state", "")) != _text(
                getattr(before, "lifecycle_state", "")
            ):
                violations.append("M11 from state mismatch")
            if _text(getattr(transition, "before_asset_sha256", "")) != _lifecycle_sha256(
                before
            ):
                violations.append("M11 before governed asset hash drifted")
        if tuple(input_contract.get("lifecycle_transition_refs") or ()) != transition_refs:
            violations.append("M11 QRO transition heads do not match the current receipt")
        if _text(input_contract.get("entry_source")) != "api":
            violations.append("M11 QRO entry source mismatch")
        if output_contract.get("asset_count") != len(asset_refs):
            violations.append("M11 QRO asset count mismatch")
        if tuple(output_contract.get("asset_types") or ()) != tuple(
            getattr(receipt, "asset_types", ()) or ()
        ):
            violations.append("M11 QRO asset types mismatch")
        if _text(output_contract.get("status")) != "lifecycle_closure_current":
            violations.append("M11 QRO lifecycle status mismatch")
        expected_lineage = (receipt_ref, *transition_refs)
        if tuple(getattr(qro, "lineage", ()) or ()) != expected_lineage:
            violations.append("M11 QRO lifecycle lineage mismatch")
        if _text(getattr(qro, "implementation_hash", "")) != (
            "lifecycle_closure:" + content_hash(_plain(receipt))
        ):
            violations.append("M11 QRO lifecycle receipt hash mismatch")
        return tuple(violations)

    return (
        {
            (M11, "governed_asset_ref"): PlatformTypedSourceAdapter(
                source_kind="asset_lifecycle_governed_asset",
                load=load_asset,
                validate_linkage=validate_asset,
            ),
            (M11, "lifecycle_transition_ref"): PlatformTypedSourceAdapter(
                source_kind="asset_lifecycle_transition",
                load=load_transition,
                validate_linkage=validate_transition,
            ),
        },
        validate_row,
    )


_DAG_KIND_BY_FIELD = {
    "dag_run_ref": "dag_checkpoint",
    "replay_ref": "dag_replay",
    "fork_ref": "dag_fork",
    "rollback_ref": "dag_rollback",
}
_DAG_PREFIX_BY_KIND = {
    "dag_checkpoint": "dag_run:",
    "dag_replay": "replay:",
    "dag_fork": "fork:",
    "dag_rollback": "rollback:",
}
_DAG_MODE_BY_KIND = {
    "dag_checkpoint": "run",
    "dag_replay": "replay",
    "dag_fork": "fork",
    "dag_rollback": "rollback",
}


def _checkpoint_maps(record: Any) -> tuple[dict[str, str], dict[str, str]]:
    payload = getattr(record, "payload", None)
    if not isinstance(payload, dict):
        raise LookupError("DAG capability payload is malformed")

    def mapping(rows: Any) -> dict[str, str]:
        if not isinstance(rows, list) or not rows:
            raise LookupError("DAG checkpoint rows are unavailable")
        result: dict[str, str] = {}
        for item in rows:
            if not isinstance(item, dict):
                raise LookupError("DAG checkpoint row is malformed")
            task = _text(item.get("task_id"))
            checkpoint = _text(item.get("checkpoint_ref"))
            if not task or not checkpoint.startswith("checkpoint:") or task in result:
                raise LookupError("DAG checkpoint identity is malformed or ambiguous")
            result[task] = checkpoint
        if len(set(result.values())) != len(result):
            raise LookupError("DAG checkpoint ref maps to multiple tasks")
        return result

    return mapping(payload.get("nodes")), mapping(payload.get("node_id_by_task"))


def _current_dag_source(
    ledger: Any,
    *,
    owner: str,
    workflow_id: str,
    capability_kind: str,
    source_ref: str,
) -> ResolvedDAGCapabilitySource:
    prefix = _DAG_PREFIX_BY_KIND[capability_kind]
    if not source_ref.startswith(prefix):
        raise LookupError("DAG source ref has the wrong canonical namespace")
    value = ledger.current_head(
        owner_user_id=owner,
        workflow_id=workflow_id,
        capability_kind=capability_kind,
    )
    if _text(getattr(value, "source_ref", "")) != source_ref:
        raise LookupError("DAG source does not match the current owner/workflow head")
    decision = ledger.validate_current(
        _text(getattr(value, "record_ref", "")), owner_user_id=owner
    )
    if not _accepted(decision):
        raise LookupError("DAG source is not a current owner/workflow head")
    stored = ledger.record(_text(getattr(value, "record_ref", "")), owner_user_id=owner)
    payload = getattr(stored, "payload", None)
    if (
        stored != value
        or _owner_of(stored) != owner
        or _text(getattr(stored, "capability_kind", "")) != capability_kind
        or not isinstance(payload, dict)
        or payload.get("succeeded") is not True
        or _text(payload.get("mode")) != _DAG_MODE_BY_KIND[capability_kind]
    ):
        raise LookupError("DAG current head payload/identity mismatch")
    if capability_kind in {"dag_checkpoint", "dag_replay"}:
        if payload.get("details") != {}:
            raise LookupError("DAG run/replay details must be empty")
    elif capability_kind == "dag_fork":
        if set(payload.get("details") or {}) != {"from_task_id", "overrides_ref"}:
            raise LookupError("DAG fork details are inexact")
    elif set(payload.get("details") or {}) != {"to_task_id"}:
        raise LookupError("DAG rollback details are inexact")
    return ResolvedDAGCapabilitySource(
        source_ref=source_ref,
        owner_user_id=owner,
        workflow_id=workflow_id,
        capability_kind=capability_kind,
        record=stored,
    )


def _m12(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    governance = context.model_governance_registry
    models = context.model_registry
    chains = context.spine_chain_registry

    def load_passport(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M12 or not ref.startswith("model_passport_"):
            raise LookupError("M12 ModelPassport ref is not canonical")
        passport = governance.passport(ref, owner_user_id=owner)
        if (
            _text(getattr(passport, "passport_id", "")) != ref
            or _owner_of(passport) != owner
        ):
            raise LookupError("M12 ModelPassport identity/owner mismatch")
        return passport

    def validate_passport(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("M12 ModelPassport owner mismatch")
        if _text(getattr(value, "passport_id", "")) != _specific(record).get(
            "model_passport_ref"
        ):
            violations.append("M12 ModelPassport identity mismatch")
        if not _text(getattr(value, "recorded_by", "")):
            violations.append("M12 ModelPassport lacks a recorded actor")
        return tuple(violations)

    def load_gate(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M12:
            raise LookupError("model promotion gate is not an M12 source")
        gate = models.promotion_gate(ref, owner_user_id=owner)
        if _text(getattr(gate, "gate_id", "")) != ref:
            raise LookupError("M12 promotion gate identity mismatch")
        return ResolvedModelGateSource(gate)

    def _validate_gate_key(
        key: str,
        value: ResolvedModelGateSource,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        if _text(getattr(value.gate, "gate_id", "")) != _specific(record).get(key):
            return (f"M12 {key} does not resolve to the durable promotion gate",)
        return ()

    def validate_promotion(
        value: ResolvedModelGateSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        return _validate_gate_key("model_promotion_ref", value, owner, record)

    def validate_approval(
        value: ResolvedModelGateSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        return _validate_gate_key("approval_ref", value, owner, record)

    def load_recertification(
        ref: str,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> Any:
        if _row(record) != M12 or not ref.startswith("model_recertification_"):
            raise LookupError("M12 RecertificationRecord ref is not canonical")
        value = governance.recertification_record(ref, owner_user_id=owner)
        if (
            _text(getattr(value, "recertification_record_id", "")) != ref
            or _owner_of(value) != owner
        ):
            raise LookupError("M12 RecertificationRecord identity/owner mismatch")
        governance.current_head_hash(
            ref,
            owner_user_id=owner,
            event_type="model_recertification_recorded",
        )
        return value

    def validate_recertification(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        expected = _specific(record).get("recertification_ref")
        if _owner_of(value) != owner:
            violations.append("M12 RecertificationRecord owner mismatch")
        if _text(getattr(value, "recertification_record_id", "")) != expected:
            violations.append("M12 RecertificationRecord identity mismatch")
        _head, errors = _call(
            "M12 current RecertificationRecord head",
            lambda: governance.current_head_hash(
                expected or "",
                owner_user_id=owner,
                event_type="model_recertification_recorded",
            ),
        )
        violations.extend(errors)
        if _head is None:
            violations.append("M12 RecertificationRecord current head is unavailable")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        passport = values.get("model_passport_ref")
        promotion = values.get("model_promotion_ref")
        approval = values.get("approval_ref")
        recertification = values.get("recertification_ref")
        if (
            passport is None
            or not isinstance(promotion, ResolvedModelGateSource)
            or not isinstance(approval, ResolvedModelGateSource)
            or recertification is None
        ):
            return ("M12 requires ModelPassport, promotion, approval, and recertification",)
        violations = list(
            _binding_lineage_violations(context, record=record, owner=owner)
        )
        promotion_gate = promotion.gate
        approval_gate = approval.gate
        gate_id = _text(getattr(promotion_gate, "gate_id", ""))
        if gate_id != _text(getattr(approval_gate, "gate_id", "")):
            violations.append("M12 promotion and approval are not the same durable gate")
        if promotion_gate != approval_gate:
            violations.append("M12 promotion/approval gate state recombination detected")
        gate, errors = _call(
            "M12 current promotion gate",
            lambda: models.promotion_gate(gate_id, owner_user_id=owner),
        )
        violations.extend(errors)
        if gate is None:
            return tuple(violations)
        if gate != promotion_gate:
            violations.append("M12 promotion gate is no longer current")
        if _text(getattr(gate, "decision", "")) != "approved":
            violations.append("M12 promotion gate is not approved")
        if not bool(getattr(gate, "side_effect_executed", False)) or not _text(
            getattr(gate, "side_effect_ref", "")
        ):
            violations.append("M12 approved promotion did not execute its stage side effect")
        creator = _text(getattr(gate, "created_by", ""))
        approver = _text(getattr(gate, "approver", ""))
        if not creator or not approver or creator == approver:
            violations.append("M12 promotion lacks creator/approver independence")
        if _text(getattr(gate, "action_kind", "")) not in {
            "promote_staging",
            "promote_production",
        }:
            violations.append("M12 gate action is not a model promotion")
        gate_evidence = getattr(gate, "evidence", None)
        if not isinstance(gate_evidence, dict):
            violations.append("M12 promotion gate evidence is unavailable")
            return tuple(violations)
        passport_ref = _text(getattr(passport, "passport_id", ""))
        model_version_ref = _text(getattr(passport, "model_version_ref", ""))
        logical_model_id = _text(gate_evidence.get("logical_model_id"))
        version = getattr(gate, "version", None)
        expected_model_version_refs = {
            f"{logical_model_id}:v{version}",
            f"{logical_model_id}:{version}",
            f"model_version:{logical_model_id}:v{version}",
            f"model_version:{logical_model_id}:{version}",
        }
        if (
            gate_evidence.get("owner_user_id") != owner
            or _text(gate_evidence.get("model_passport_ref")) != passport_ref
            or model_version_ref not in expected_model_version_refs
        ):
            violations.append("M12 promotion gate owner/passport/model-version mismatch")
        recert_ref = _text(getattr(recertification, "recertification_record_id", ""))
        if (
            _owner_of(recertification) != owner
            or _text(getattr(recertification, "model_passport_ref", "")) != passport_ref
            or _text(getattr(recertification, "model_version_ref", ""))
            != model_version_ref
            or _text(getattr(recertification, "decision", ""))
            not in {"accepted", "waived"}
        ):
            violations.append("M12 RecertificationRecord owner/model/passport/decision mismatch")
        if recert_ref not in tuple(getattr(passport, "recertification_records", ()) or ()):
            violations.append("M12 ModelPassport does not include the RecertificationRecord")
        gate_recert_refs = tuple(
            _text(item)
            for item in tuple(gate_evidence.get("model_recertification_record_refs") or ())
        )
        if recert_ref not in gate_recert_refs:
            violations.append("M12 promotion gate does not include the RecertificationRecord")
        current_head, errors = _call(
            "M12 RecertificationRecord head",
            lambda: governance.current_head_hash(
                recert_ref,
                owner_user_id=owner,
                event_type="model_recertification_recorded",
            ),
        )
        violations.extend(errors)
        head_map = gate_evidence.get("model_recertification_record_head_hashes")
        if (
            current_head is None
            or not isinstance(head_map, dict)
            or _text(head_map.get(recert_ref)) != _text(current_head)
        ):
            violations.append("M12 promotion gate RecertificationRecord head is stale")
        qro, errors = _call("M12 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is None:
            return tuple(violations)
        if _owner_of(qro) != owner or _qro_type(qro) != "Model":
            violations.append("M12 promotion approval QRO owner/type mismatch")
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        if not isinstance(input_contract, dict) or not isinstance(output_contract, dict):
            violations.append("M12 promotion approval QRO contracts are unavailable")
            return tuple(violations)
        if (
            _text(input_contract.get("gate_id")) != gate_id
            or _text(input_contract.get("model_version_ref")) != model_version_ref
            or _text(input_contract.get("model")) != logical_model_id
            or input_contract.get("model_version") != version
        ):
            violations.append("M12 promotion approval QRO input/gate mismatch")
        if (
            _text(output_contract.get("status")) != "promotion_gate_approved"
            or _text(output_contract.get("gate_id")) != gate_id
            or _text(output_contract.get("decision")) != "approved"
            or _text(output_contract.get("model_passport_ref")) != passport_ref
            or _text(output_contract.get("side_effect_ref"))
            != _text(getattr(gate, "side_effect_ref", ""))
        ):
            violations.append("M12 promotion approval QRO output/gate mismatch")
        if _text(getattr(qro, "approval", "")) != gate_id:
            violations.append("M12 promotion approval QRO approval ref mismatch")
        delegated_actor = _text(input_contract.get("delegated_actor"))
        delegated_authority_ref = _text(
            input_contract.get("delegated_actor_authority_ref")
        )
        delegated_authority_hash = _text(
            input_contract.get("delegated_actor_authority_hash")
        )
        if (
            not delegated_actor
            or _text(output_contract.get("approved_by")) != delegated_actor
            or _text(getattr(gate, "approver", "")) != delegated_actor
            or not delegated_authority_ref
            or not delegated_authority_hash
            or _text(gate_evidence.get("reviewer_user_id")) != delegated_actor
            or _text(gate_evidence.get("reviewer_grant_id"))
            != delegated_authority_ref
            or _text(gate_evidence.get("reviewer_grant_record_hash"))
            != delegated_authority_hash
        ):
            violations.append("M12 delegated reviewer authority linkage mismatch")
        else:
            grant, errors = _call(
                "M12 delegated reviewer authority",
                lambda: models.promotion_reviewer_authority_evidence(
                    gate_id,
                    model_id=logical_model_id,
                    reviewer_user_id=delegated_actor,
                    grant_id=delegated_authority_ref,
                    grant_record_hash=delegated_authority_hash,
                    permission="approve",
                ),
            )
            violations.extend(errors)
            if grant is not None and (
                _text(getattr(grant, "grant_id", ""))
                != delegated_authority_ref
                or _text(getattr(grant, "gate_id", "")) != gate_id
                or _text(getattr(grant, "owner_user_id", "")) != owner
                or _text(getattr(grant, "model_id", "")) != logical_model_id
                or _text(getattr(grant, "model_asset_ref", ""))
                != _text(getattr(gate, "model_id", ""))
                or getattr(grant, "model_version", None) != version
                or _text(getattr(grant, "reviewer_user_id", ""))
                != delegated_actor
                or "approve"
                not in {
                    _text(item)
                    for item in tuple(getattr(grant, "permissions", ()) or ())
                }
            ):
                violations.append("M12 delegated reviewer authority is stale or recombined")
        if _text(record.lifecycle_ref) != _text(getattr(gate, "side_effect_ref", "")):
            violations.append("M12 common lifecycle ref is not the promotion stage side effect")
        chain, errors = _call(
            "M12 Mathematical Spine chain",
            lambda: chains.verified_chain(_text(record.math_spine_ref), owner=owner),
        )
        violations.extend(errors)
        if chain is None:
            return tuple(violations)
        if _text(getattr(chain, "model_ref", "")) not in {
            model_version_ref,
            passport_ref,
        }:
            violations.append("M12 Mathematical Spine model ref mismatch")
        chain_refs = {
            _text(item)
            for item in (
                *tuple(getattr(chain, "evidence_refs", ()) or ()),
                *tuple(getattr(chain, "validation_refs", ()) or ()),
                *tuple(getattr(chain, "theory_binding_refs", ()) or ()),
            )
        }
        if passport_ref not in chain_refs and _text(getattr(chain, "model_ref", "")) != passport_ref:
            violations.append("M12 Mathematical Spine does not bind ModelPassport")
        return tuple(violations)

    return (
        {
            (M12, "model_passport_ref"): PlatformTypedSourceAdapter(
                source_kind="current_owner_model_passport",
                load=load_passport,
                validate_linkage=validate_passport,
            ),
            (M12, "model_promotion_ref"): PlatformTypedSourceAdapter(
                source_kind="current_model_promotion_gate",
                load=load_gate,
                validate_linkage=validate_promotion,
            ),
            (M12, "approval_ref"): PlatformTypedSourceAdapter(
                source_kind="approved_model_promotion_gate",
                load=load_gate,
                validate_linkage=validate_approval,
            ),
            (M12, "recertification_ref"): PlatformTypedSourceAdapter(
                source_kind="current_model_recertification_record",
                load=load_recertification,
                validate_linkage=validate_recertification,
            ),
        },
        validate_row,
    )


def _m13(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    ledger = context.agent_capability_ledger
    closures = context.agent_workflow_closure_registry
    rag = context.rag_index

    def current_workflow_receipt(
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> Any:
        receipt_ref = _text(record.lifecycle_ref)
        receipt = closures.receipt(receipt_ref, owner_user_id=owner)
        workflow = _text(getattr(receipt, "workflow_id", ""))
        if not workflow:
            raise LookupError("M13 lifecycle receipt lacks a workflow identity")
        current = closures.current_receipt(
            owner_user_id=owner,
            workflow_id=workflow,
        )
        if (
            current != receipt
            or _owner_of(receipt) != owner
            or _text(getattr(receipt, "receipt_ref", "")) != receipt_ref
        ):
            raise LookupError("M13 lifecycle receipt is not the current owner/workflow head")
        return receipt

    def capability_adapter(field: str) -> PlatformTypedSourceAdapter:
        capability_kind = _DAG_KIND_BY_FIELD[field]

        def load(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
            if _row(record) != M13:
                raise LookupError("DAG capability adapter only supports M13")
            receipt = current_workflow_receipt(owner, record)
            return _current_dag_source(
                ledger,
                owner=owner,
                workflow_id=_text(getattr(receipt, "workflow_id", "")),
                capability_kind=capability_kind,
                source_ref=ref,
            )

        def validate(
            value: ResolvedDAGCapabilitySource,
            owner: str,
            record: PlatformCapabilityRecord,
        ) -> tuple[str, ...]:
            violations: list[str] = []
            if value.owner_user_id != owner:
                violations.append(f"M13 {field} owner mismatch")
            if value.capability_kind != capability_kind:
                violations.append(f"M13 {field} capability kind mismatch")
            if value.source_ref != _specific(record).get(field):
                violations.append(f"M13 {field} identity mismatch")
            return tuple(violations)

        return PlatformTypedSourceAdapter(
            source_kind=f"agent_capability_{capability_kind}",
            load=load,
            validate_linkage=validate,
        )

    def load_checkpoint(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M13 or not ref.startswith("checkpoint:"):
            raise LookupError("DAG checkpoint ref is not canonical for M13")
        receipt = current_workflow_receipt(owner, record)
        workflow = _text(getattr(receipt, "workflow_id", ""))
        value = ledger.current_head(
            owner_user_id=owner,
            workflow_id=workflow,
            capability_kind="dag_checkpoint",
        )
        decision = ledger.validate_current(
            _text(getattr(value, "record_ref", "")), owner_user_id=owner
        )
        nodes, index = _checkpoint_maps(value)
        if not _accepted(decision) or nodes != index or ref not in nodes.values():
            raise LookupError("checkpoint is not bound by the current owner/workflow DAG run")
        return ResolvedDAGCheckpointSource(
            checkpoint_ref=ref,
            owner_user_id=owner,
            workflow_id=workflow,
            dag_run=value,
        )

    def validate_checkpoint(
        value: ResolvedDAGCheckpointSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner:
            violations.append("M13 checkpoint owner mismatch")
        if value.checkpoint_ref != _specific(record).get("checkpoint_ref"):
            violations.append("M13 checkpoint identity mismatch")
        try:
            nodes, index = _checkpoint_maps(value.dag_run)
        except LookupError:
            violations.append("M13 checkpoint maps are malformed")
        else:
            if nodes != index or value.checkpoint_ref not in nodes.values():
                violations.append("M13 checkpoint is not content-bound by the DAG run")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        run = values.get("dag_run_ref")
        checkpoint = values.get("checkpoint_ref")
        replay = values.get("replay_ref")
        fork = values.get("fork_ref")
        rollback = values.get("rollback_ref")
        if not all(
            (
                isinstance(run, ResolvedDAGCapabilitySource),
                isinstance(checkpoint, ResolvedDAGCheckpointSource),
                isinstance(replay, ResolvedDAGCapabilitySource),
                isinstance(fork, ResolvedDAGCapabilitySource),
                isinstance(rollback, ResolvedDAGCapabilitySource),
            )
        ):
            return ("M13 requires exact current run/checkpoint/replay/fork/rollback objects",)
        sources = (run, replay, fork, rollback)
        workflows = {item.workflow_id for item in sources} | {checkpoint.workflow_id}
        violations: list[str] = list(
            _binding_lineage_violations(context, record=record, owner=owner)
        )
        if len(workflows) != 1 or "" in workflows:
            return ("M13 DAG sources recombine different owner workflow heads",)
        workflow = next(iter(workflows))
        if checkpoint.dag_run != run.record:
            violations.append("M13 checkpoint belongs to a different DAG run")
        for source in sources:
            current, errors = _call(
                f"M13 current {source.capability_kind}",
                lambda source=source: ledger.current_head(
                    owner_user_id=owner,
                    workflow_id=workflow,
                    capability_kind=source.capability_kind,
                ),
            )
            violations.extend(errors)
            if current is not None and (
                current != source.record
                or _text(getattr(current, "record_ref", ""))
                != _text(getattr(source.record, "record_ref", ""))
            ):
                violations.append(f"M13 {source.capability_kind} is not the current head")
        qro, errors = _call("M13 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is not None and _owner_of(qro) != owner:
            violations.append("M13 QRO owner mismatch")
        receipt, errors = _call(
            "M13 workflow closure",
            lambda: current_workflow_receipt(owner, record),
        )
        violations.extend(errors)
        if receipt is None:
            return tuple(violations)
        snapshot = getattr(receipt, "snapshot", None)
        if (
            _owner_of(snapshot) != owner
            or _text(getattr(snapshot, "workflow_id", "")) != workflow
        ):
            violations.append("M13 Agent workflow closure owner/workflow mismatch")
            return tuple(violations)
        if _text(getattr(getattr(snapshot, "qro", None), "component_ref", "")) != _text(
            record.qro_ref
        ):
            violations.append("M13 workflow closure QRO mismatch")
        violations.extend(
            _workflow_snapshot_binding_violations(
                context,
                label="M13",
                snapshot=snapshot,
                record=record,
                owner=owner,
                workflow_id=workflow,
            )
        )
        if _text(record.lifecycle_ref) != _text(getattr(receipt, "receipt_ref", "")):
            violations.append("M13 common lifecycle ref is not the current workflow receipt")
        violations.extend(
            _workflow_rag_violations(
                rag,
                label="M13",
                snapshot=snapshot,
                record=record,
                owner=owner,
                workflow_id=workflow,
            )
        )
        try:
            capability_components = _component_by_link(
                tuple(getattr(snapshot, "capability_heads", ()) or ()),
                "capability_kind",
            )
        except LookupError as exc:
            return (*violations, f"M13 {exc}")
        for source in sources:
            component = capability_components.get(source.capability_kind)
            if component is None or _text(getattr(component, "component_ref", "")) != _text(
                getattr(source.record, "record_ref", "")
            ):
                violations.append(
                    f"M13 workflow closure {source.capability_kind} head mismatch"
                )
        react = capability_components.get("react")
        workflow_replay = capability_components.get("replay")
        if react is None:
            violations.append("M13 current workflow closure lacks React capability")
        else:
            links = getattr(react, "link_map", dict(getattr(react, "links", ()) or ()))
            if links.get("dag_record_ref") != _text(getattr(run.record, "record_ref", "")):
                violations.append("M13 React capability does not bind the DAG run")
        if workflow_replay is None:
            violations.append("M13 current workflow closure lacks Replay capability")
        else:
            links = getattr(
                workflow_replay,
                "link_map",
                dict(getattr(workflow_replay, "links", ()) or ()),
            )
            if links.get("dag_record_ref") != _text(
                getattr(replay.record, "record_ref", "")
            ):
                violations.append("M13 Replay capability does not bind the DAG replay")
        return tuple(violations)

    adapters = {
        (M13, field): capability_adapter(field) for field in _DAG_KIND_BY_FIELD
    }
    adapters[(M13, "checkpoint_ref")] = PlatformTypedSourceAdapter(
        source_kind="agent_capability_dag_checkpoint_node",
        load=load_checkpoint,
        validate_linkage=validate_checkpoint,
    )
    return adapters, validate_row


def _m14(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    calls = context.llm_call_record_store
    bindings = context.llm_use_binding_store
    onboarding = context.onboarding_registry
    spine = context.canonical_spine_ledger
    spine_chains = context.spine_chain_registry
    closures = context.agent_workflow_closure_registry
    rag = context.rag_index
    service_owner = _text(context.llm_service_owner_user_id)

    def load_gateway(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M14 or not ref.startswith("llm_gateway:"):
            raise LookupError("LLM gateway ref is not canonical for M14")
        call_id = ref.removeprefix("llm_gateway:")
        if not call_id:
            raise LookupError("LLM gateway terminal call id is required")
        terminal = calls.resolve_terminal_record(call_id, owner)
        binding = bindings.binding_for_terminal(call_id, owner_user_id=owner)
        decision = bindings.validate_current(
            _text(getattr(binding, "binding_ref", "")), owner_user_id=owner
        )
        if (
            not _accepted(decision)
            or _text(getattr(terminal, "call_id", "")) != call_id
            or _owner_of(terminal) != owner
            or _text(getattr(terminal, "record_kind", "")) != "terminal"
            or _text(getattr(terminal, "status", "")) != "ok"
            or _owner_of(binding) != owner
            or _text(getattr(binding, "terminal_call_id", "")) != call_id
            or _text(getattr(binding, "terminal_status", "")) != "ok"
        ):
            raise LookupError("LLM terminal/use-binding current identity mismatch")
        return ResolvedM14LLMGatewaySource(ref, owner, terminal, binding)

    def validate_gateway(
        value: ResolvedM14LLMGatewaySource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner:
            violations.append("M14 LLM gateway owner mismatch")
        if value.gateway_ref != _specific(record).get("llm_gateway_ref"):
            violations.append("M14 LLM gateway identity mismatch")
        if _text(getattr(value.terminal_record, "status", "")) != "ok":
            violations.append("M14 LLM gateway terminal is not successful")
        return tuple(violations)

    def load_routing(ref: str, _owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M14 or not ref.startswith(("model_routing_policy:", "routing:")):
            raise LookupError("ModelRoutingPolicy ref is not canonical for M14")
        value = onboarding.routing_policy(ref, owner_user_id=service_owner)
        if _text(getattr(value, "routing_policy_id", "")) != ref:
            raise LookupError("ModelRoutingPolicy identity mismatch")
        return ResolvedServiceRoutingPolicySource(ref, service_owner, value)

    def validate_routing(
        value: ResolvedServiceRoutingPolicySource,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        if (
            value.service_principal_ref != service_owner
            or value.routing_policy_ref != _specific(record).get("model_routing_policy_ref")
        ):
            return ("M14 ModelRoutingPolicy identity/service-principal mismatch",)
        return ()

    def load_pool(ref: str, _owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M14 or not ref.startswith(("credential_pool:", "pool:")):
            raise LookupError("CredentialPool ref is not canonical for M14")
        value = onboarding.credential_pool(ref, owner_user_id=service_owner)
        if (
            _text(getattr(value, "pool_id", "")) != ref
            or _text(getattr(value, "owner", "")) != service_owner
        ):
            raise LookupError("CredentialPool identity/service-principal mismatch")
        return ResolvedServiceCredentialPoolSource(ref, service_owner, value)

    def validate_pool(
        value: ResolvedServiceCredentialPoolSource,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        if (
            value.service_principal_ref != service_owner
            or value.credential_pool_ref != _specific(record).get("credential_pool_ref")
        ):
            return ("M14 CredentialPool identity/service-principal mismatch",)
        return ()

    def load_tib(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M14 or not ref.startswith("tib_"):
            raise LookupError("canonical TheoryImplementationBinding ref is not canonical for M14")
        value = spine.binding(ref, owner=owner)
        checks = tuple(spine.checks_for(ref, owner=owner) or ())
        if _text(getattr(value, "binding_id", "")) != ref:
            raise LookupError("canonical TheoryImplementationBinding identity mismatch")
        return ResolvedTheoryImplementationBindingSource(ref, owner, value, checks)

    def validate_tib(
        value: ResolvedTheoryImplementationBindingSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner:
            violations.append("M14 TheoryImplementationBinding owner mismatch")
        if value.binding_ref != _specific(record).get(
            "theory_implementation_binding_ref"
        ):
            violations.append("M14 TheoryImplementationBinding identity mismatch")
        binding = value.record
        if _text(getattr(binding, "consistency_verdict", "")) != "server_property_check":
            violations.append("M14 TheoryImplementationBinding is not server-verified")
        if not _text(getattr(binding, "verifier_ref", "")):
            violations.append("M14 TheoryImplementationBinding verifier is missing")
        if not value.consistency_checks:
            violations.append("M14 TheoryImplementationBinding has no persisted ConsistencyCheck")
        for check in value.consistency_checks:
            get = check.get if isinstance(check, dict) else lambda key, default=None: getattr(
                check, key, default
            )
            if _text(get("binding_id")) != value.binding_ref or _text(get("result")) != "pass":
                violations.append("M14 TheoryImplementationBinding check is not passing/bound")
            if not tuple(get("input_refs", ()) or ()) or not _text(get("verifier_ref")):
                violations.append("M14 TheoryImplementationBinding check evidence is incomplete")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        gateway = values.get("llm_gateway_ref")
        routing_source = values.get("model_routing_policy_ref")
        pool_source = values.get("credential_pool_ref")
        tib_source = values.get("theory_implementation_binding_ref")
        if not (
            isinstance(gateway, ResolvedM14LLMGatewaySource)
            and isinstance(routing_source, ResolvedServiceRoutingPolicySource)
            and isinstance(pool_source, ResolvedServiceCredentialPoolSource)
            and isinstance(tib_source, ResolvedTheoryImplementationBindingSource)
        ):
            return ("M14 requires exact terminal, routing, pool, and canonical TIB objects",)
        terminal = gateway.terminal_record
        use_binding = gateway.use_binding
        routing = routing_source.record
        pool = pool_source.record
        tib = tib_source.record
        violations: list[str] = list(
            _binding_lineage_violations(context, record=record, owner=owner)
        )
        exact_pairs = (
            (getattr(use_binding, "service_principal_ref", ""), service_owner, "service principal"),
            (getattr(use_binding, "routing_policy_ref", ""), routing_source.routing_policy_ref, "routing policy"),
            (getattr(use_binding, "credential_pool_ref", ""), pool_source.credential_pool_ref, "credential pool"),
            (getattr(use_binding, "provider_ref", ""), getattr(terminal, "provider", ""), "terminal provider"),
            (getattr(use_binding, "auth_ref", ""), getattr(terminal, "auth_ref", ""), "terminal auth"),
            (getattr(use_binding, "workflow_id", ""), getattr(terminal, "workflow_id", ""), "workflow"),
            (getattr(use_binding, "invocation_id", ""), getattr(terminal, "invocation_id", ""), "invocation"),
            (getattr(routing, "credential_pool_ref", ""), getattr(pool, "pool_id", ""), "routing/pool"),
            (getattr(pool, "provider_id", ""), getattr(terminal, "provider", ""), "pool provider"),
        )
        for actual, expected, label in exact_pairs:
            if _text(actual) != _text(expected):
                violations.append(f"M14 {label} mismatch")
        auth_ref = _text(getattr(terminal, "auth_ref", ""))
        if auth_ref not in tuple(getattr(pool, "auth_refs", ()) or ()):
            violations.append("M14 terminal auth is absent from the selected credential pool")
        if auth_ref in tuple(getattr(pool, "revoked_refs", ()) or ()):
            violations.append("M14 terminal auth is revoked in the selected credential pool")
        if _text(getattr(terminal, "provider", "")) not in tuple(
            getattr(routing, "allowed_providers", ()) or ()
        ):
            violations.append("M14 terminal provider is outside the selected routing policy")
        if _text(getattr(terminal, "model", "")) not in tuple(
            getattr(routing, "allowed_models", ()) or ()
        ):
            violations.append("M14 terminal model is outside the selected routing policy")
        if _text(getattr(routing, "role_agent", "")) != _text(
            getattr(terminal, "role", "")
        ):
            violations.append("M14 terminal role does not match the selected routing policy")
        qro, errors = _call("M14 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is None:
            return tuple(violations)
        if _owner_of(qro) != owner:
            violations.append("M14 QRO owner mismatch")
        if _text(getattr(qro, "theory_implementation_binding", "")) != _text(
            getattr(tib, "binding_id", "")
        ):
            violations.append("M14 QRO does not bind the selected canonical TIB")
        chain, errors = _call(
            "M14 verified Mathematical Spine",
            lambda: spine_chains.verified_chain(_text(record.math_spine_ref), owner=owner),
        )
        violations.extend(errors)
        if chain is not None and tib_source.binding_ref not in tuple(
            getattr(chain, "theory_binding_refs", ()) or ()
        ):
            violations.append("M14 Mathematical Spine chain omits the selected canonical TIB")
        workflow = _text(getattr(use_binding, "workflow_id", ""))
        receipt, errors = _call(
            "M14 workflow closure",
            lambda: closures.current_receipt(
                owner_user_id=owner,
                workflow_id=workflow,
            ),
        )
        violations.extend(errors)
        if receipt is None:
            return tuple(violations)
        snapshot = getattr(receipt, "snapshot", None)
        if (
            _owner_of(snapshot) != owner
            or _text(getattr(snapshot, "workflow_id", "")) != workflow
        ):
            violations.append("M14 Agent workflow closure owner/workflow mismatch")
        if _text(record.lifecycle_ref) != _text(getattr(receipt, "receipt_ref", "")):
            violations.append("M14 common lifecycle ref is not the current workflow receipt")
        if _text(getattr(getattr(snapshot, "qro", None), "component_ref", "")) != _text(
            record.qro_ref
        ):
            violations.append("M14 workflow closure QRO mismatch")
        violations.extend(
            _workflow_snapshot_binding_violations(
                context,
                label="M14",
                snapshot=snapshot,
                record=record,
                owner=owner,
                workflow_id=workflow,
            )
        )
        violations.extend(
            _workflow_rag_violations(
                rag,
                label="M14",
                snapshot=snapshot,
                record=record,
                owner=owner,
                workflow_id=workflow,
            )
        )
        terminal_components = {
            _text(getattr(item, "component_ref", "")): item
            for item in tuple(getattr(snapshot, "terminal_calls", ()) or ())
        }
        binding_components = {
            _text(getattr(item, "component_ref", "")): item
            for item in tuple(getattr(snapshot, "llm_use_bindings", ()) or ())
        }
        if len(terminal_components) != len(
            tuple(getattr(snapshot, "terminal_calls", ()) or ())
        ):
            violations.append("M14 workflow closure has duplicate terminal call identities")
        if len(binding_components) != len(
            tuple(getattr(snapshot, "llm_use_bindings", ()) or ())
        ):
            violations.append("M14 workflow closure has duplicate use-binding identities")
        if _text(getattr(terminal, "call_id", "")) not in terminal_components:
            violations.append("M14 terminal call is absent from the current workflow closure")
        if _text(getattr(use_binding, "binding_ref", "")) not in binding_components:
            violations.append("M14 use binding is absent from the current workflow closure")
        return tuple(violations)

    return (
        {
            (M14, "llm_gateway_ref"): PlatformTypedSourceAdapter(
                source_kind="llm_gateway_terminal_and_use_binding",
                load=load_gateway,
                validate_linkage=validate_gateway,
            ),
            (M14, "model_routing_policy_ref"): PlatformTypedSourceAdapter(
                source_kind="onboarding_model_routing_policy",
                load=load_routing,
                validate_linkage=validate_routing,
            ),
            (M14, "credential_pool_ref"): PlatformTypedSourceAdapter(
                source_kind="onboarding_llm_credential_pool",
                load=load_pool,
                validate_linkage=validate_pool,
            ),
            (M14, "theory_implementation_binding_ref"): PlatformTypedSourceAdapter(
                source_kind="canonical_mathematical_spine_tib",
                load=load_tib,
                validate_linkage=validate_tib,
            ),
        },
        validate_row,
    )


def _m15(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[dict[tuple[str, str], PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    topologies = context.desk_topology_registry

    def load_projection(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M15 or not ref.startswith("rgproj_"):
            raise LookupError("Research Graph projection ref is not canonical for M15")
        matches = [
            item
            for item in graph.projection_index(owner=owner)
            if _text(getattr(item, "projection_ref", "")) == ref
        ]
        if len(matches) != 1:
            raise LookupError("Research Graph projection is missing or ambiguous")
        projection = matches[0]
        if (
            _owner_of(projection) != owner
            or _text(getattr(projection, "qro_id", "")) != _text(record.qro_ref)
            or _text(getattr(projection, "command_id", "")) != _text(
                record.research_graph_ref
            )
        ):
            raise LookupError("Research Graph projection/QRO/command linkage mismatch")
        return projection

    def validate_projection(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("M15 Research Graph projection owner mismatch")
        if _text(getattr(value, "projection_ref", "")) != _specific(record).get(
            "typed_canvas_projection_ref"
        ):
            violations.append("M15 Research Graph projection identity mismatch")
        if _text(getattr(value, "qro_id", "")) != _text(record.qro_ref):
            violations.append("M15 Research Graph projection QRO mismatch")
        if _text(getattr(value, "command_id", "")) != _text(record.research_graph_ref):
            violations.append("M15 Research Graph projection command mismatch")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        projection = values.get("typed_canvas_projection_ref")
        if projection is None:
            return ("M15 requires the exact current Research Graph projection",)
        violations: list[str] = []
        qro, errors = _call("M15 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        command, errors = _call(
            "M15 Research Graph command",
            lambda: next(
                item
                for item in graph.commands()
                if _text(getattr(item, "command_id", ""))
                == _text(record.research_graph_ref)
            ),
        )
        violations.extend(errors)
        if qro is None or command is None:
            return tuple(violations)
        if _owner_of(qro) != owner or _text(getattr(command, "actor", "")) != owner:
            violations.append("M15 QRO/command owner mismatch")
        payload = getattr(command, "payload", None)
        if not isinstance(payload, dict) or payload.get("qro") != qro:
            violations.append("M15 command does not carry the exact current QRO")
        projection_pairs = (
            (
                getattr(projection, "projection_ref", ""),
                "rgproj_"
                + content_hash(
                    {
                        "qro_id": getattr(qro, "qro_id", ""),
                        "qro_version": getattr(qro, "version", None),
                        "command_id": getattr(command, "command_id", ""),
                        "command_timestamp": getattr(command, "timestamp", ""),
                    }
                ),
                "identity",
            ),
            (getattr(projection, "qro_id", ""), getattr(qro, "qro_id", ""), "QRO id"),
            (getattr(projection, "command_id", ""), getattr(command, "command_id", ""), "command id"),
            (getattr(projection, "qro_type", ""), _qro_type(qro), "QRO type"),
            (getattr(projection, "owner", ""), owner, "owner"),
            (getattr(projection, "actor", ""), getattr(command, "actor", ""), "actor"),
            (getattr(projection, "market", ""), getattr(qro, "market", ""), "market"),
            (getattr(projection, "universe", ""), getattr(qro, "universe", ""), "universe"),
            (getattr(projection, "horizon", ""), getattr(qro, "horizon", ""), "horizon"),
            (getattr(projection, "frequency", ""), getattr(qro, "frequency", ""), "frequency"),
            (getattr(projection, "status_axes", {}), getattr(qro, "status_axes", lambda: {})(), "status axes"),
            (tuple(getattr(projection, "evidence_refs", ()) or ()), tuple(getattr(qro, "evidence_refs", ()) or ()), "evidence refs"),
            (tuple(getattr(projection, "mathematical_refs", ()) or ()), tuple(getattr(qro, "mathematical_refs", ()) or ()), "mathematical refs"),
            (getattr(projection, "permission", ""), getattr(qro, "permission", ""), "permission"),
            (getattr(projection, "input_contract_hash", ""), content_hash(getattr(qro, "input_contract", {})), "input hash"),
            (getattr(projection, "output_contract_hash", ""), content_hash(getattr(qro, "output_contract", {})), "output hash"),
            (getattr(projection, "qro_version", None), getattr(qro, "version", None), "QRO version"),
            (getattr(projection, "command_timestamp", ""), getattr(command, "timestamp", ""), "command timestamp"),
        )
        for actual, expected, label in projection_pairs:
            if actual != expected:
                violations.append(f"M15 projection {label} mismatch")
        if tuple(getattr(projection, "input_contract_keys", ()) or ()) != tuple(
            sorted(str(key) for key in getattr(qro, "input_contract", {}))
        ):
            violations.append("M15 projection input keys mismatch")
        if tuple(getattr(projection, "output_contract_keys", ()) or ()) != tuple(
            sorted(str(key) for key in getattr(qro, "output_contract", {}))
        ):
            violations.append("M15 projection output keys mismatch")
        if tuple(getattr(projection, "lineage", ()) or ()) != tuple(
            getattr(qro, "lineage", ()) or ()
        ):
            violations.append("M15 projection lineage mismatch")
        qro_math_refs = tuple(
            _text(ref) for ref in tuple(getattr(qro, "mathematical_refs", ()) or ())
        )
        if qro_math_refs != (_text(record.math_spine_ref),):
            violations.append(
                "M15 Mathematical Spine is not exactly bound by the topology QRO"
            )
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        if _qro_type(qro) != "ValidationDossier":
            violations.append("M15 QRO must be a ValidationDossier")
        if not isinstance(input_contract, dict) or set(input_contract) != {
            "entry_source",
            "topology_ref",
            "handoff_refs",
        }:
            violations.append("M15 desk-topology QRO input contract is inexact")
            return tuple(violations)
        if not isinstance(output_contract, dict) or set(output_contract) != {
            "desk_topology_receipt_ref",
            "status",
            "desk_count",
        }:
            violations.append("M15 desk-topology QRO output contract is inexact")
            return tuple(violations)
        receipt_ref = _text(output_contract.get("desk_topology_receipt_ref"))
        receipt, errors = _call(
            "M15 desk topology receipt",
            lambda: topologies.receipt(receipt_ref, owner_user_id=owner),
        )
        violations.extend(errors)
        if receipt is None:
            return tuple(violations)
        if _owner_of(receipt) != owner or _text(getattr(receipt, "receipt_ref", "")) != receipt_ref:
            violations.append("M15 desk topology receipt owner/identity mismatch")
        receipt_decision, errors = _call(
            "M15 current desk topology receipt",
            lambda: topologies.validate_current_receipt(receipt, owner_user_id=owner),
        )
        violations.extend(errors)
        if receipt_decision is None or not _accepted(receipt_decision):
            violations.append("M15 desk topology receipt is not current")
        topology_ref = _text(getattr(receipt, "topology_ref", ""))
        topology, errors = _call(
            "M15 desk topology",
            lambda: topologies.topology(topology_ref, owner_user_id=owner),
        )
        violations.extend(errors)
        current, errors = _call(
            "M15 current desk topology",
            lambda: topologies.current_topology(owner_user_id=owner),
        )
        violations.extend(errors)
        if topology is None or current is None:
            return tuple(violations)
        topology_decision, errors = _call(
            "M15 desk topology current check",
            lambda: topologies.validate_topology_current(topology, owner_user_id=owner),
        )
        violations.extend(errors)
        if topology_decision is None or not _accepted(topology_decision):
            violations.append("M15 nine-desk topology is not current")
        if current != topology:
            violations.append("M15 desk topology is not the current revision")
        desk_projections = tuple(getattr(topology, "projections", ()) or ())
        desks = tuple(_text(getattr(item, "desk", "")) for item in desk_projections)
        if len(desk_projections) != 9 or len(set(desks)) != 9 or "" in desks:
            violations.append("M15 topology does not contain exactly nine distinct desks")
        for desk_projection in desk_projections:
            if not _text(getattr(desk_projection, "typed_canvas_ref", "")):
                violations.append("M15 desk projection lacks Typed Canvas")
            if tuple(getattr(desk_projection, "source_of_truth_refs", ()) or ()) != (
                "research_graph",
            ):
                violations.append("M15 desk projection does not use Research Graph as source of truth")
        if _text(record.lifecycle_ref) != receipt_ref:
            violations.append("M15 common lifecycle ref is not the current topology receipt")
        if _text(input_contract.get("topology_ref")) != topology_ref:
            violations.append("M15 QRO topology ref mismatch")
        if _text(input_contract.get("entry_source")) != "api":
            violations.append("M15 QRO entry source mismatch")
        if tuple(input_contract.get("handoff_refs") or ()) != tuple(
            getattr(receipt, "handoff_refs", ()) or ()
        ):
            violations.append("M15 QRO handoff refs mismatch")
        if _text(output_contract.get("status")) != "desk_topology_current":
            violations.append("M15 QRO topology status mismatch")
        if output_contract.get("desk_count") != 9:
            violations.append("M15 QRO desk count mismatch")
        expected_lineage = (
            receipt_ref,
            topology_ref,
            *tuple(getattr(receipt, "handoff_refs", ()) or ()),
        )
        if tuple(getattr(qro, "lineage", ()) or ()) != expected_lineage:
            violations.append("M15 QRO desk topology lineage mismatch")
        if _text(getattr(qro, "implementation_hash", "")) != (
            "desk_topology_closure:" + content_hash(_plain(receipt))
        ):
            violations.append("M15 QRO desk topology receipt hash mismatch")
        return tuple(violations)

    return (
        {
            (M15, "typed_canvas_projection_ref"): PlatformTypedSourceAdapter(
                source_kind="research_graph_current_projection",
                load=load_projection,
                validate_linkage=validate_projection,
            )
        },
        validate_row,
    )


def build_platform_source_adapters_m9_m15(
    context: PlatformSourceAdaptersM9M15Context,
) -> tuple[
    dict[str | tuple[str, str], PlatformTypedSourceAdapter],
    dict[str, PlatformRowLinkValidator],
]:
    """Build only complete M9-M15 adapter families."""

    unavailable = unavailable_platform_source_rows_m9_m15(context)
    adapters: dict[str | tuple[str, str], PlatformTypedSourceAdapter] = {}
    validators: dict[str, PlatformRowLinkValidator] = {}
    for row, builder in (
        (M9, _m9),
        (M10, _m10),
        (M11, _m11),
        (M12, _m12),
        (M13, _m13),
        (M14, _m14),
        (M15, _m15),
    ):
        if row in unavailable:
            continue
        row_adapters, validator = builder(context)
        overlap = set(adapters).intersection(row_adapters)
        if overlap:
            raise ValueError(f"duplicate M9-M15 platform adapters: {sorted(overlap)}")
        adapters.update(row_adapters)
        validators[row] = validator
    return adapters, validators


__all__ = [
    "PlatformSourceAdaptersM9M15Context",
    "ResolvedBacktestRunSource",
    "ResolvedDAGCapabilitySource",
    "ResolvedDAGCheckpointSource",
    "ResolvedExecutionBoundarySource",
    "ResolvedGovernedAssetSource",
    "ResolvedM14LLMGatewaySource",
    "ResolvedModelGateSource",
    "ResolvedServiceCredentialPoolSource",
    "ResolvedServiceRoutingPolicySource",
    "ResolvedTheoryImplementationBindingSource",
    "ResolvedValidationDepthSource",
    "ResolvedValidationMethodologySource",
    "build_platform_source_adapters_m9_m15",
    "unavailable_platform_source_rows_m9_m15",
]
