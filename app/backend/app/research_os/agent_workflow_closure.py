"""Durable, current-backed completion receipts for one GOAL section 7 workflow.

The receipt is deliberately narrower than a generic "the agent ran" marker.  A
green workflow must be one authenticated Agent Shell turn whose durable event
stream, Gateway calls, user-to-service bindings, strict RAG use, QRO/Graph
write, governed compiler lineage, and Agent Shell coverage all resolve to the
same owner and workflow.  The injected resolver owns the store-specific reads;
this module owns the exact cross-store shape and refuses caller-supplied
recombination.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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
from .ref_resolution import is_placeholder_ref


AGENT_WORKFLOW_CLOSURE_SCHEMA_VERSION = 4
AGENT_WORKFLOW_CLOSURE_RECEIPT_VERSION = "agent_workflow_closure_receipt.v3"
AGENT_WORKFLOW_ENTRYPOINT_REF = "agent_shell:agent.workbench.stream"
AGENT_WORKFLOW_REQUIRED_CAPABILITY_KINDS = (
    "plan",
    "review",
    "react",
    "replay",
    "repair",
    "agent_code_change",
    "dag_checkpoint",
    "dag_replay",
    "dag_fork",
    "dag_rollback",
)

_WORKFLOW_ID_RE = re.compile(r"agentwf_[0-9a-f]{64}")
_REQUIRED_EVENT_KINDS = frozenset(
    {
        "AgentPlanCreated",
        "TodoUpdated",
        "RoleAgentDispatched",
        "LLMRouteSelected",
        "CredentialPoolSelected",
        "LLMCallStarted",
        "LLMCallFinished",
        "ToolCallStarted",
        "ToolCallFinished",
        "RagHitUsed",
        "ArtifactProduced",
        "RunVerdictProduced",
    }
)
_EVENT_BASE_LINKS = frozenset({"workflow_id", "sequence", "kind"})
_EVENT_EXTRA_LINKS = {
    "LLMRouteSelected": frozenset({"invocation_id", "attempt_no"}),
    "CredentialPoolSelected": frozenset({"invocation_id", "attempt_no"}),
    "LLMCallStarted": frozenset({"invocation_id", "attempt_no"}),
    "LLMCallFinished": frozenset(
        {"invocation_id", "attempt_no", "call_ref"}
    ),
    "ProviderFallbackUsed": frozenset(
        {"invocation_id", "from_attempt_no", "to_attempt_no"}
    ),
    "ToolCallStarted": frozenset({"tool_name", "node_id", "tool_call_ref"}),
    "ToolCallFinished": frozenset(
        {"tool_name", "node_id", "tool_call_ref", "ok"}
    ),
    "RagHitUsed": frozenset({"usage_ref"}),
    "RunVerdictProduced": frozenset({"succeeded"}),
    "FailureDetected": frozenset({"failure_ref"}),
    "RepairAttempted": frozenset({"failure_ref"}),
}

_CAPABILITY_BASE_LINKS = frozenset(
    {"workflow_id", "capability_kind", "previous_record_ref", "source_ref"}
)
_CAPABILITY_EXTRA_LINKS = {
    "plan": frozenset(),
    "review": frozenset(
        {"source_event_ref", "builder_call_ref", "verifier_call_ref"}
    ),
    "react": frozenset({"source_event_ref", "dag_record_ref"}),
    "replay": frozenset({"source_event_ref", "dag_record_ref"}),
    "repair": frozenset(
        {
            "failure_ref",
            "failure_event_ref",
            "repair_event_ref",
            "code_change_ref",
            "permission_ref",
        }
    ),
    "agent_code_change": frozenset(
        {"source_event_ref", "code_change_ref", "permission_ref"}
    ),
    "dag_checkpoint": frozenset(),
    "dag_replay": frozenset(),
    "dag_fork": frozenset({"from_task_id", "overrides_ref"}),
    "dag_rollback": frozenset({"to_task_id"}),
}
_CAPABILITY_STATUS = {
    "plan": "ready",
    "review": "passed",
    "react": "succeeded",
    "replay": "succeeded",
    "repair": "recorded",
    "agent_code_change": "recorded",
    "dag_checkpoint": "succeeded",
    "dag_replay": "succeeded",
    "dag_fork": "succeeded",
    "dag_rollback": "succeeded",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _refs(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, (tuple, list)) else (() if value is None else (value,))
    return tuple(_text(item) for item in values if _text(item))


def _links(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    items = value.items() if isinstance(value, Mapping) else value
    return tuple(sorted((_text(key), _text(child)) for key, child in items))


def _valid_hash(value: str) -> bool:
    token = _text(value).lower()
    if token.startswith("sha256:"):
        token = token[7:]
    return len(token) == 64 and all(char in "0123456789abcdef" for char in token)


@dataclass(frozen=True)
class AgentWorkflowClosureViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class AgentWorkflowClosureDecision:
    accepted: bool
    violations: tuple[AgentWorkflowClosureViolation, ...]


class AgentWorkflowClosureError(ValueError):
    """A workflow cannot be proven current and complete."""


class AgentWorkflowClosureCommitUncertain(AgentWorkflowClosureError):
    """The journal write failed and durable rollback could not be proven."""


@dataclass(frozen=True)
class AgentWorkflowComponentState:
    component_ref: str
    principal_id: str
    revision: str
    state_hash: str
    status: str
    links: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("component_ref", "principal_id", "revision", "state_hash", "status"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        object.__setattr__(self, "status", self.status.lower())
        object.__setattr__(self, "links", _links(self.links))

    @property
    def link_map(self) -> dict[str, str]:
        return dict(self.links)


@dataclass(frozen=True)
class AgentWorkflowClosureSnapshot:
    owner_user_id: str
    workflow_id: str
    events: tuple[AgentWorkflowComponentState, ...]
    terminal_calls: tuple[AgentWorkflowComponentState, ...]
    llm_attempts: tuple[AgentWorkflowComponentState, ...]
    llm_use_bindings: tuple[AgentWorkflowComponentState, ...]
    capability_heads: tuple[AgentWorkflowComponentState, ...]
    rag_usage: AgentWorkflowComponentState
    qro: AgentWorkflowComponentState
    graph_command: AgentWorkflowComponentState
    compiler_ir: AgentWorkflowComponentState
    compiler_pass: AgentWorkflowComponentState
    entrypoint_coverage: AgentWorkflowComponentState
    residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", _text(self.owner_user_id))
        object.__setattr__(self, "workflow_id", _text(self.workflow_id))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "terminal_calls", tuple(self.terminal_calls))
        object.__setattr__(self, "llm_attempts", tuple(self.llm_attempts))
        object.__setattr__(self, "llm_use_bindings", tuple(self.llm_use_bindings))
        object.__setattr__(self, "capability_heads", tuple(self.capability_heads))
        object.__setattr__(self, "residuals", _refs(self.residuals))


@dataclass(frozen=True)
class AgentWorkflowClosureReceipt:
    receipt_ref: str
    owner_user_id: str
    workflow_id: str
    record_revision: int
    previous_receipt_ref: str
    snapshot: AgentWorkflowClosureSnapshot
    receipt_version: str = AGENT_WORKFLOW_CLOSURE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_ref",
            "owner_user_id",
            "workflow_id",
            "previous_receipt_ref",
            "receipt_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))

    @property
    def canonical_receipt_ref(self) -> str:
        return agent_workflow_closure_receipt_identity(
            owner_user_id=self.owner_user_id,
            workflow_id=self.workflow_id,
            record_revision=self.record_revision,
            previous_receipt_ref=self.previous_receipt_ref,
            snapshot=self.snapshot,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class AgentWorkflowClosureSemanticMaterial:
    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]


WorkflowClosureResolver = Callable[[str, str], AgentWorkflowClosureSnapshot]


def _component_from_dict(value: Any) -> AgentWorkflowComponentState:
    if not isinstance(value, dict) or set(value) != {
        "component_ref",
        "principal_id",
        "revision",
        "state_hash",
        "status",
        "links",
    }:
        raise ValueError("agent workflow component has an inexact field set")
    return AgentWorkflowComponentState(**value)


def agent_workflow_closure_snapshot_from_dict(value: Any) -> AgentWorkflowClosureSnapshot:
    if not isinstance(value, dict) or set(value) != {
        "owner_user_id",
        "workflow_id",
        "events",
        "terminal_calls",
        "llm_attempts",
        "llm_use_bindings",
        "capability_heads",
        "rag_usage",
        "qro",
        "graph_command",
        "compiler_ir",
        "compiler_pass",
        "entrypoint_coverage",
        "residuals",
    }:
        raise ValueError("agent workflow closure snapshot has an inexact field set")
    return AgentWorkflowClosureSnapshot(
        owner_user_id=value["owner_user_id"],
        workflow_id=value["workflow_id"],
        events=tuple(_component_from_dict(item) for item in value["events"]),
        terminal_calls=tuple(_component_from_dict(item) for item in value["terminal_calls"]),
        llm_attempts=tuple(_component_from_dict(item) for item in value["llm_attempts"]),
        llm_use_bindings=tuple(
            _component_from_dict(item) for item in value["llm_use_bindings"]
        ),
        capability_heads=tuple(
            _component_from_dict(item) for item in value["capability_heads"]
        ),
        rag_usage=_component_from_dict(value["rag_usage"]),
        qro=_component_from_dict(value["qro"]),
        graph_command=_component_from_dict(value["graph_command"]),
        compiler_ir=_component_from_dict(value["compiler_ir"]),
        compiler_pass=_component_from_dict(value["compiler_pass"]),
        entrypoint_coverage=_component_from_dict(value["entrypoint_coverage"]),
        residuals=tuple(value["residuals"]),
    )


def agent_workflow_closure_receipt_from_dict(value: Any) -> AgentWorkflowClosureReceipt:
    if not isinstance(value, dict) or set(value) != {
        "receipt_ref",
        "owner_user_id",
        "workflow_id",
        "record_revision",
        "previous_receipt_ref",
        "snapshot",
        "receipt_version",
    }:
        raise ValueError("agent workflow closure receipt has an inexact field set")
    return AgentWorkflowClosureReceipt(
        receipt_ref=value["receipt_ref"],
        owner_user_id=value["owner_user_id"],
        workflow_id=value["workflow_id"],
        record_revision=value["record_revision"],
        previous_receipt_ref=value["previous_receipt_ref"],
        snapshot=agent_workflow_closure_snapshot_from_dict(value["snapshot"]),
        receipt_version=value["receipt_version"],
    )


def agent_workflow_closure_receipt_identity(
    *,
    owner_user_id: str,
    workflow_id: str,
    record_revision: int,
    previous_receipt_ref: str,
    snapshot: AgentWorkflowClosureSnapshot,
    receipt_version: str = AGENT_WORKFLOW_CLOSURE_RECEIPT_VERSION,
) -> str:
    return "agent_workflow_closure_receipt:" + _sha256(
        {
            "owner_user_id": _text(owner_user_id),
            "workflow_id": _text(workflow_id),
            "record_revision": record_revision,
            "previous_receipt_ref": _text(previous_receipt_ref),
            "snapshot": asdict(snapshot),
            "receipt_version": _text(receipt_version),
        }
    )


def _reject(
    violations: list[AgentWorkflowClosureViolation],
    code: str,
    message: str,
    *,
    field: str = "",
    ref: str = "",
) -> None:
    violations.append(AgentWorkflowClosureViolation(code, message, field=field, ref=ref))


def _component_groups(
    snapshot: AgentWorkflowClosureSnapshot,
) -> dict[str, tuple[AgentWorkflowComponentState, ...]]:
    return {
        "events": snapshot.events,
        "terminal_calls": snapshot.terminal_calls,
        "llm_attempts": snapshot.llm_attempts,
        "llm_use_bindings": snapshot.llm_use_bindings,
        "capability_heads": snapshot.capability_heads,
        "rag_usage": (snapshot.rag_usage,),
        "qro": (snapshot.qro,),
        "graph_command": (snapshot.graph_command,),
        "compiler_ir": (snapshot.compiler_ir,),
        "compiler_pass": (snapshot.compiler_pass,),
        "entrypoint_coverage": (snapshot.entrypoint_coverage,),
    }


def validate_agent_workflow_closure_snapshot(
    snapshot: AgentWorkflowClosureSnapshot,
    *,
    owner_user_id: str,
    workflow_id: str,
) -> AgentWorkflowClosureDecision:
    """Validate a single non-recombinable Agent Shell workflow chain."""

    violations: list[AgentWorkflowClosureViolation] = []
    owner = _text(owner_user_id)
    workflow = _text(workflow_id)
    if not owner or snapshot.owner_user_id != owner:
        _reject(
            violations,
            "agent_workflow_owner_mismatch",
            "workflow closure owner must exactly match the requested owner",
            field="owner_user_id",
            ref=snapshot.owner_user_id,
        )
    if not _WORKFLOW_ID_RE.fullmatch(workflow) or snapshot.workflow_id != workflow:
        _reject(
            violations,
            "agent_workflow_identity_invalid",
            "workflow closure requires the exact production Agent workflow identity",
            field="workflow_id",
            ref=snapshot.workflow_id,
        )
    if snapshot.residuals:
        _reject(
            violations,
            "agent_workflow_residuals_present",
            "workflow closure cannot pass with unresolved residuals",
            field="residuals",
            ref=",".join(snapshot.residuals),
        )

    groups = _component_groups(snapshot)
    all_components = tuple(component for values in groups.values() for component in values)
    refs = [component.component_ref for component in all_components]
    if len(refs) != len(set(refs)):
        _reject(
            violations,
            "agent_workflow_component_ref_reused",
            "one evidence identity cannot stand in for two workflow components",
        )
    for group_name, components in groups.items():
        if not components:
            _reject(
                violations,
                "agent_workflow_component_group_empty",
                "every workflow evidence group must be non-empty",
                field=group_name,
            )
        for component in components:
            if not all(
                (
                    component.component_ref,
                    component.principal_id,
                    component.revision,
                    component.state_hash,
                    component.status,
                )
            ):
                _reject(
                    violations,
                    "agent_workflow_component_incomplete",
                    "every workflow component requires ref, principal, revision, hash, and status",
                    field=group_name,
                    ref=component.component_ref,
                )
            if component.principal_id != owner:
                _reject(
                    violations,
                    "agent_workflow_component_owner_mismatch",
                    "every workflow component must belong to the same owner",
                    field=group_name,
                    ref=component.component_ref,
                )
            if not _valid_hash(component.state_hash):
                _reject(
                    violations,
                    "agent_workflow_component_hash_invalid",
                    "component state_hash must be a full sha256 digest",
                    field=group_name,
                    ref=component.component_ref,
                )
            if is_placeholder_ref(component.component_ref):
                _reject(
                    violations,
                    "agent_workflow_component_placeholder",
                    "workflow closure cannot use placeholder or fixture evidence",
                    field=group_name,
                    ref=component.component_ref,
                )

    if not snapshot.events:
        return AgentWorkflowClosureDecision(False, tuple(violations))
    sequences: list[int] = []
    kinds: list[str] = []
    for event in snapshot.events:
        links = event.link_map
        kind = links.get("kind", "")
        expected_keys = _EVENT_BASE_LINKS | _EVENT_EXTRA_LINKS.get(kind, frozenset())
        if frozenset(links) != expected_keys:
            _reject(
                violations,
                "agent_workflow_event_links_inexact",
                "workflow event links must exactly expose its sequence and controlled join fields",
                field="events",
                ref=event.component_ref,
            )
        if links.get("workflow_id") != workflow:
            _reject(
                violations,
                "agent_workflow_event_scope_mismatch",
                "every event must belong to the receipt workflow",
                field="events",
                ref=event.component_ref,
            )
        try:
            sequence = int(links.get("sequence", ""))
        except ValueError:
            sequence = 0
        sequences.append(sequence)
        kinds.append(kind)
    if sequences != list(range(1, len(snapshot.events) + 1)):
        _reject(
            violations,
            "agent_workflow_event_sequence_invalid",
            "workflow events must be one complete contiguous durable sequence",
            field="events",
            ref=workflow,
        )
    missing_kinds = sorted(_REQUIRED_EVENT_KINDS.difference(kinds))
    if missing_kinds:
        _reject(
            violations,
            "agent_workflow_required_events_missing",
            "a complete workflow requires plan, dispatch, Gateway, tool, artifact, "
            "and verdict events",
            field="events",
            ref=",".join(missing_kinds),
        )
    event_refs = {event.component_ref for event in snapshot.events}
    events_by_ref = {event.component_ref: event for event in snapshot.events}
    failures_by_ref: dict[str, list[tuple[int, AgentWorkflowComponentState]]] = {}
    repairs_by_ref: dict[str, list[tuple[int, AgentWorkflowComponentState]]] = {}
    for index, event in enumerate(snapshot.events):
        kind = event.link_map.get("kind", "")
        if kind not in {"FailureDetected", "RepairAttempted"}:
            continue
        failure_ref = event.link_map.get("failure_ref", "")
        if not failure_ref:
            _reject(
                violations,
                "agent_workflow_failure_pair_invalid",
                "failure and repair events require one opaque failure identity",
                field="events",
                ref=event.component_ref,
            )
            continue
        target = failures_by_ref if kind == "FailureDetected" else repairs_by_ref
        target.setdefault(failure_ref, []).append((index, event))
    for failure_ref in sorted(set(failures_by_ref) | set(repairs_by_ref)):
        failures = failures_by_ref.get(failure_ref, ())
        repairs = repairs_by_ref.get(failure_ref, ())
        if (
            len(failures) != 1
            or len(repairs) != 1
            or failures[0][0] >= repairs[0][0]
        ):
            _reject(
                violations,
                "agent_workflow_failure_pair_invalid",
                "each failure must have exactly one later durable repair attempt",
                field="events",
                ref=failure_ref,
            )
    final_event = snapshot.events[-1]
    if (
        final_event.link_map.get("kind") != "RunVerdictProduced"
        or final_event.link_map.get("succeeded") != "true"
        or final_event.status != "succeeded"
    ):
        _reject(
            violations,
            "agent_workflow_final_verdict_invalid",
            "the final durable event must be a successful RunVerdictProduced",
            field="events",
            ref=final_event.component_ref,
        )

    capabilities_by_kind: dict[str, AgentWorkflowComponentState] = {}
    required_capabilities = set(AGENT_WORKFLOW_REQUIRED_CAPABILITY_KINDS)
    for capability in snapshot.capability_heads:
        links = capability.link_map
        kind = links.get("capability_kind", "")
        expected_keys = _CAPABILITY_BASE_LINKS | _CAPABILITY_EXTRA_LINKS.get(
            kind, frozenset()
        )
        if kind not in required_capabilities or frozenset(links) != expected_keys:
            _reject(
                violations,
                "agent_workflow_capability_links_inexact",
                "capability heads must expose only their controlled workflow joins",
                field="capability_heads",
                ref=capability.component_ref,
            )
            continue
        if kind in capabilities_by_kind:
            _reject(
                violations,
                "agent_workflow_capability_ambiguous",
                "each required Agent capability must have exactly one current head",
                field="capability_heads",
                ref=kind,
            )
        capabilities_by_kind[kind] = capability
        try:
            revision = int(capability.revision)
        except ValueError:
            revision = 0
        previous_ref = links.get("previous_record_ref", "")
        if (
            links.get("workflow_id") != workflow
            or links.get("source_ref") == ""
            or capability.status != _CAPABILITY_STATUS[kind]
            or revision <= 0
            or ((revision == 1) != (not previous_ref))
            or (revision > 1 and not previous_ref.startswith("agent_capability:"))
        ):
            _reject(
                violations,
                "agent_workflow_capability_not_current_ready",
                "capability head must preserve its exact revision chain and successful state",
                field="capability_heads",
                ref=capability.component_ref,
            )
    missing_capabilities = sorted(required_capabilities - set(capabilities_by_kind))
    extra_capabilities = sorted(set(capabilities_by_kind) - required_capabilities)
    if missing_capabilities or extra_capabilities or len(snapshot.capability_heads) != len(
        AGENT_WORKFLOW_REQUIRED_CAPABILITY_KINDS
    ):
        _reject(
            violations,
            "agent_workflow_required_capabilities_missing",
            "section 7 closure requires one current head for every governed Agent capability",
            field="capability_heads",
            ref=",".join((*missing_capabilities, *extra_capabilities)),
        )

    if required_capabilities.issubset(capabilities_by_kind):
        plan = capabilities_by_kind["plan"]
        review = capabilities_by_kind["review"]
        react = capabilities_by_kind["react"]
        replay = capabilities_by_kind["replay"]
        repair = capabilities_by_kind["repair"]
        code_change = capabilities_by_kind["agent_code_change"]
        dag_checkpoint = capabilities_by_kind["dag_checkpoint"]
        dag_replay = capabilities_by_kind["dag_replay"]
        terminal_refs_for_review = {
            review.link_map.get("builder_call_ref", ""),
            review.link_map.get("verifier_call_ref", ""),
        }
        source_links = {
            "plan": plan.link_map.get("source_ref", ""),
            "review": review.link_map.get("source_event_ref", ""),
            "react": react.link_map.get("source_event_ref", ""),
            "replay": replay.link_map.get("source_event_ref", ""),
            "agent_code_change": code_change.link_map.get("source_event_ref", ""),
            "repair_failure": repair.link_map.get("failure_event_ref", ""),
            "repair_attempt": repair.link_map.get("repair_event_ref", ""),
        }
        source_kinds = {
            "plan": "AgentPlanCreated",
            "review": "VerifierChallengeRaised",
            "react": "RunVerdictProduced",
            "replay": "RunVerdictProduced",
            "agent_code_change": "RepairAttempted",
            "repair_failure": "FailureDetected",
            "repair_attempt": "RepairAttempted",
        }
        invalid_sources = [
            name
            for name, event_ref in source_links.items()
            if event_ref not in event_refs
            or events_by_ref[event_ref].link_map.get("kind") != source_kinds[name]
        ]
        failure_ref = repair.link_map.get("failure_ref", "")
        repair_failure_event = events_by_ref.get(
            repair.link_map.get("failure_event_ref", "")
        )
        repair_attempt_event = events_by_ref.get(
            repair.link_map.get("repair_event_ref", "")
        )
        relationship_invalid = (
            react.link_map.get("dag_record_ref") != dag_checkpoint.component_ref
            or replay.link_map.get("dag_record_ref") != dag_replay.component_ref
            or repair.link_map.get("code_change_ref")
            != code_change.link_map.get("code_change_ref")
            or repair.link_map.get("permission_ref")
            != code_change.link_map.get("permission_ref")
            or code_change.link_map.get("source_ref")
            != code_change.link_map.get("code_change_ref")
            or not terminal_refs_for_review.issubset(
                {terminal.component_ref for terminal in snapshot.terminal_calls}
            )
            or any(not ref for ref in terminal_refs_for_review)
            or invalid_sources
            or repair_failure_event is None
            or repair_attempt_event is None
            or repair_failure_event.link_map.get("failure_ref") != failure_ref
            or repair_attempt_event.link_map.get("failure_ref") != failure_ref
        )
        if relationship_invalid:
            _reject(
                violations,
                "agent_workflow_capability_relationship_invalid",
                "Agent capabilities must bind exact events, LLM calls, DAG heads, and repair evidence",
                field="capability_heads",
                ref=workflow,
            )

    starts: dict[str, tuple[int, str, str]] = {}
    consumed_tool_calls: set[str] = set()
    successful_finishes = 0
    for index, event in enumerate(snapshot.events):
        links = event.link_map
        call_ref = links.get("tool_call_ref", "")
        if links.get("kind") == "ToolCallStarted":
            if (
                not call_ref
                or call_ref in starts
                or not links.get("tool_name")
                or not links.get("node_id")
            ):
                _reject(
                    violations,
                    "agent_workflow_tool_pair_invalid",
                    "each tool start requires one unique call identity, tool, and node",
                    field="events",
                    ref=event.component_ref,
                )
            else:
                starts[call_ref] = (
                    index,
                    links.get("tool_name", ""),
                    links.get("node_id", ""),
                )
        elif links.get("kind") == "ToolCallFinished":
            start = starts.get(call_ref)
            valid_pair = (
                start is not None
                and call_ref not in consumed_tool_calls
                and start[0] < index
                and start[1] == links.get("tool_name", "")
                and start[2] == links.get("node_id", "")
            )
            if not valid_pair:
                _reject(
                    violations,
                    "agent_workflow_tool_pair_invalid",
                    "every tool finish must consume exactly one prior same-call same-node start",
                    field="events",
                    ref=event.component_ref,
                )
            else:
                consumed_tool_calls.add(call_ref)
            if (
                valid_pair
                and links.get("ok") == "true"
                and event.status == "succeeded"
            ):
                successful_finishes += 1
    unmatched_tool_calls = sorted(set(starts) - consumed_tool_calls)
    if unmatched_tool_calls:
        _reject(
            violations,
            "agent_workflow_tool_pair_invalid",
            "every governed tool start requires exactly one terminal finish",
            field="events",
            ref=",".join(unmatched_tool_calls),
        )
    if successful_finishes < 1:
        _reject(
            violations,
            "agent_workflow_successful_tool_missing",
            "section 7 closure requires at least one successful governed tool call",
            field="events",
            ref=workflow,
        )

    invocation_states: dict[str, dict[str, Any]] = {}
    finished_by_call: dict[str, tuple[str, int]] = {}

    def positive_int(value: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    for event in snapshot.events:
        links = event.link_map
        kind = links.get("kind", "")
        if kind not in {
            "LLMRouteSelected",
            "CredentialPoolSelected",
            "LLMCallStarted",
            "ProviderFallbackUsed",
            "LLMCallFinished",
        }:
            continue
        invocation_id = links.get("invocation_id", "")
        if not invocation_id:
            _reject(
                violations,
                "agent_workflow_llm_state_invalid",
                "every Gateway event requires one invocation identity",
                field="events",
                ref=event.component_ref,
            )
            continue
        state = invocation_states.get(invocation_id)
        if kind == "LLMRouteSelected":
            attempt = positive_int(links.get("attempt_no", ""))
            if state is not None or attempt != 1:
                _reject(
                    violations,
                    "agent_workflow_llm_state_invalid",
                    "each invocation must begin once at route attempt one",
                    field="events",
                    ref=event.component_ref,
                )
                continue
            invocation_states[invocation_id] = {
                "attempt": attempt,
                "stage": "routed",
                "fallbacks": [],
            }
            continue
        if state is None:
            _reject(
                violations,
                "agent_workflow_llm_state_invalid",
                "Gateway credential, start, fallback, and finish require a prior route",
                field="events",
                ref=event.component_ref,
            )
            continue
        if kind == "ProviderFallbackUsed":
            from_attempt = positive_int(links.get("from_attempt_no", ""))
            to_attempt = positive_int(links.get("to_attempt_no", ""))
            if (
                state["stage"] not in {"routed", "credentialed", "started"}
                or from_attempt != state["attempt"]
                or to_attempt != from_attempt + 1
            ):
                _reject(
                    violations,
                    "agent_workflow_llm_state_invalid",
                    "fallback must advance exactly one unfinished Gateway attempt",
                    field="events",
                    ref=event.component_ref,
                )
                continue
            state["fallbacks"].append((from_attempt, to_attempt))
            state["attempt"] = to_attempt
            state["stage"] = "routed"
            continue
        attempt = positive_int(links.get("attempt_no", ""))
        if attempt != state["attempt"]:
            _reject(
                violations,
                "agent_workflow_llm_state_invalid",
                "Gateway event attempt does not match the current invocation attempt",
                field="events",
                ref=event.component_ref,
            )
            continue
        if kind == "CredentialPoolSelected":
            if state["stage"] != "routed":
                _reject(
                    violations,
                    "agent_workflow_llm_state_invalid",
                    "credential selection must follow the current routed attempt once",
                    field="events",
                    ref=event.component_ref,
                )
            else:
                state["stage"] = "credentialed"
        elif kind == "LLMCallStarted":
            if state["stage"] != "credentialed":
                _reject(
                    violations,
                    "agent_workflow_llm_state_invalid",
                    "LLM call start must follow one current credential selection",
                    field="events",
                    ref=event.component_ref,
                )
            else:
                state["stage"] = "started"
        elif kind == "LLMCallFinished":
            call_ref = links.get("call_ref", "")
            if (
                state["stage"] != "started"
                or not call_ref
                or call_ref in finished_by_call
            ):
                _reject(
                    violations,
                    "agent_workflow_llm_state_invalid",
                    "LLM finish must terminate one started attempt with a unique call ref",
                    field="events",
                    ref=event.component_ref,
                )
            else:
                state["stage"] = "finished"
                state["call_ref"] = call_ref
                finished_by_call[call_ref] = (invocation_id, attempt)

    unfinished_invocations = sorted(
        invocation_id
        for invocation_id, state in invocation_states.items()
        if state.get("stage") != "finished"
    )
    if unfinished_invocations:
        _reject(
            violations,
            "agent_workflow_llm_state_invalid",
            "every routed Gateway invocation must reach exactly one successful finish",
            field="events",
            ref=",".join(unfinished_invocations),
        )

    terminal_ref_list = [
        component.component_ref for component in snapshot.terminal_calls
    ]
    terminal_refs = set(terminal_ref_list)
    if (
        not terminal_refs
        or len(terminal_refs) != len(terminal_ref_list)
        or terminal_refs != set(finished_by_call)
    ):
        _reject(
            violations,
            "agent_workflow_terminal_event_mismatch",
            "LLM finishes must be a bijection with successful terminal call records",
            field="terminal_calls",
            ref=workflow,
        )
    bindings_by_terminal: dict[str, AgentWorkflowComponentState] = {}
    for binding in snapshot.llm_use_bindings:
        links = binding.link_map
        if frozenset(links) != frozenset({"workflow_id", "invocation_id", "terminal_call_ref"}):
            _reject(
                violations,
                "agent_workflow_binding_links_inexact",
                "Gateway use binding links are inexact",
                field="llm_use_bindings",
                ref=binding.component_ref,
            )
        if binding.status != "active" or links.get("workflow_id") != workflow:
            _reject(
                violations,
                "agent_workflow_binding_not_current",
                "Gateway use bindings must be current and workflow-scoped",
                field="llm_use_bindings",
                ref=binding.component_ref,
            )
        terminal_ref = links.get("terminal_call_ref", "")
        if terminal_ref in bindings_by_terminal:
            _reject(
                violations,
                "agent_workflow_binding_ambiguous",
                "each terminal call must have exactly one Gateway use binding",
                field="llm_use_bindings",
                ref=terminal_ref,
            )
        bindings_by_terminal[terminal_ref] = binding
    if set(bindings_by_terminal) != terminal_refs:
        _reject(
            violations,
            "agent_workflow_terminal_binding_mismatch",
            "terminal calls and Gateway use bindings must be a bijection",
            field="llm_use_bindings",
            ref=workflow,
        )
    terminals_by_invocation: dict[str, AgentWorkflowComponentState] = {}
    for terminal in snapshot.terminal_calls:
        links = terminal.link_map
        if frozenset(links) != frozenset({"workflow_id", "invocation_id", "binding_ref"}):
            _reject(
                violations,
                "agent_workflow_terminal_links_inexact",
                "terminal call links are inexact",
                field="terminal_calls",
                ref=terminal.component_ref,
            )
            continue
        binding = bindings_by_terminal.get(terminal.component_ref)
        finished_identity = finished_by_call.get(terminal.component_ref)
        terminal_invocation = links.get("invocation_id", "")
        if terminal_invocation in terminals_by_invocation:
            _reject(
                violations,
                "agent_workflow_terminal_chain_mismatch",
                "each Gateway invocation must resolve exactly one terminal call",
                field="terminal_calls",
                ref=terminal_invocation,
            )
        elif terminal_invocation:
            terminals_by_invocation[terminal_invocation] = terminal
        if (
            terminal.status != "ok"
            or links.get("workflow_id") != workflow
            or binding is None
            or finished_identity is None
            or links.get("invocation_id") != finished_identity[0]
            or positive_int(terminal.revision) != finished_identity[1]
            or links.get("binding_ref") != binding.component_ref
            or links.get("invocation_id") != binding.link_map.get("invocation_id")
        ):
            _reject(
                violations,
                "agent_workflow_terminal_chain_mismatch",
                "terminal call and Gateway binding must share workflow and invocation identities",
                field="terminal_calls",
                ref=terminal.component_ref,
            )

    attempts_by_invocation: dict[str, list[AgentWorkflowComponentState]] = {}
    for attempt in snapshot.llm_attempts:
        links = attempt.link_map
        if frozenset(links) != frozenset(
            {
                "workflow_id",
                "invocation_id",
                "attempt_no",
                "record_kind",
                "terminal_call_ref",
                "failure_stage",
            }
        ):
            _reject(
                violations,
                "agent_workflow_llm_attempt_links_inexact",
                "LLM attempt links must expose the exact audited invocation chain",
                field="llm_attempts",
                ref=attempt.component_ref,
            )
            continue
        invocation_id = links.get("invocation_id", "")
        attempt_no = positive_int(links.get("attempt_no", ""))
        terminal = terminals_by_invocation.get(invocation_id)
        status_valid = attempt.status in {"ok", "error"}
        failure_stage_valid = (
            attempt.status == "ok" and not links.get("failure_stage")
        ) or (
            attempt.status == "error" and bool(links.get("failure_stage"))
        )
        if (
            links.get("workflow_id") != workflow
            or links.get("record_kind") != "attempt"
            or attempt_no <= 0
            or positive_int(attempt.revision) != attempt_no
            or terminal is None
            or links.get("terminal_call_ref") != terminal.component_ref
            or not status_valid
            or not failure_stage_valid
        ):
            _reject(
                violations,
                "agent_workflow_llm_attempt_invalid",
                "each LLM attempt must be a status-faithful member of one terminal invocation",
                field="llm_attempts",
                ref=attempt.component_ref,
            )
        attempts_by_invocation.setdefault(invocation_id, []).append(attempt)

    expected_invocations = set(invocation_states)
    if set(attempts_by_invocation) != expected_invocations:
        _reject(
            violations,
            "agent_workflow_llm_attempt_chain_mismatch",
            "every routed invocation must expose its complete persisted attempt ledger",
            field="llm_attempts",
            ref=workflow,
        )
    for invocation_id, state in invocation_states.items():
        terminal = terminals_by_invocation.get(invocation_id)
        attempts = sorted(
            attempts_by_invocation.get(invocation_id, ()),
            key=lambda component: positive_int(component.link_map.get("attempt_no", "")),
        )
        terminal_attempt = (
            positive_int(terminal.revision) if terminal is not None else 0
        )
        attempt_numbers = [
            positive_int(component.link_map.get("attempt_no", ""))
            for component in attempts
        ]
        expected_numbers = list(range(1, terminal_attempt + 1))
        expected_fallbacks = [
            (attempt_no, attempt_no + 1)
            for attempt_no in range(1, terminal_attempt)
        ]
        statuses = [component.status for component in attempts]
        if (
            terminal is None
            or attempt_numbers != expected_numbers
            or state.get("fallbacks") != expected_fallbacks
            or not statuses
            or statuses[-1] != "ok"
            or any(status != "error" for status in statuses[:-1])
        ):
            _reject(
                violations,
                "agent_workflow_llm_attempt_chain_mismatch",
                "attempt records, fallback events, and the successful terminal attempt must form one contiguous chain",
                field="llm_attempts",
                ref=invocation_id,
            )

    rag_ref = snapshot.rag_usage.component_ref
    visible_rag_refs = tuple(
        event.link_map.get("usage_ref", "")
        for event in snapshot.events
        if event.link_map.get("kind") == "RagHitUsed"
    )
    if visible_rag_refs != (rag_ref,):
        _reject(
            violations,
            "agent_workflow_visible_rag_mismatch",
            "the current strict RAG usage must have exactly one visible RagHitUsed event",
            field="events",
            ref=",".join(visible_rag_refs),
        )
    qro_ref = snapshot.qro.component_ref
    graph_ref = snapshot.graph_command.component_ref
    ir_ref = snapshot.compiler_ir.component_ref
    pass_ref = snapshot.compiler_pass.component_ref
    coverage_ref = snapshot.entrypoint_coverage.component_ref
    exact_links = {
        "rag_usage": (
            snapshot.rag_usage,
            {"workflow_id": workflow, "qro_ref": qro_ref},
            "accepted",
        ),
        "qro": (
            snapshot.qro,
            {
                "workflow_id": workflow,
                "rag_usage_ref": rag_ref,
                "graph_command_ref": graph_ref,
                "coverage_ref": coverage_ref,
            },
            "current",
        ),
        "graph_command": (
            snapshot.graph_command,
            {"qro_ref": qro_ref, "coverage_ref": coverage_ref},
            "current",
        ),
        "compiler_ir": (
            snapshot.compiler_ir,
            {
                "qro_ref": qro_ref,
                "graph_command_ref": graph_ref,
                "compiler_pass_ref": pass_ref,
                "coverage_ref": coverage_ref,
            },
            "current",
        ),
        "compiler_pass": (
            snapshot.compiler_pass,
            {"compiler_ir_ref": ir_ref, "coverage_ref": coverage_ref},
            "passed",
        ),
        "entrypoint_coverage": (
            snapshot.entrypoint_coverage,
            {
                "entry_source": "agent_shell",
                "entrypoint_ref": AGENT_WORKFLOW_ENTRYPOINT_REF,
                "workflow_id": workflow,
                "rag_usage_ref": rag_ref,
                "qro_ref": qro_ref,
                "graph_command_ref": graph_ref,
                "compiler_ir_ref": ir_ref,
                "compiler_pass_ref": pass_ref,
            },
            "current",
        ),
    }
    for field_name, (component, expected, status) in exact_links.items():
        if component.link_map != expected or component.status != status:
            _reject(
                violations,
                "agent_workflow_lineage_mismatch",
                "RAG, QRO, Graph, compiler, and coverage must form one exact current workflow",
                field=field_name,
                ref=component.component_ref,
            )

    return AgentWorkflowClosureDecision(not violations, tuple(violations))


def validate_agent_workflow_closure_receipt_shape(
    receipt: AgentWorkflowClosureReceipt,
) -> AgentWorkflowClosureDecision:
    violations: list[AgentWorkflowClosureViolation] = []
    if receipt.receipt_version != AGENT_WORKFLOW_CLOSURE_RECEIPT_VERSION:
        _reject(
            violations,
            "agent_workflow_receipt_version_unsupported",
            "agent workflow closure receipt version is unsupported",
            field="receipt_version",
            ref=receipt.receipt_ref,
        )
    if type(receipt.record_revision) is not int or receipt.record_revision <= 0:
        _reject(
            violations,
            "agent_workflow_receipt_revision_invalid",
            "receipt record_revision must be a positive integer",
            field="record_revision",
            ref=receipt.receipt_ref,
        )
    if (receipt.record_revision == 1) != (not receipt.previous_receipt_ref):
        _reject(
            violations,
            "agent_workflow_receipt_previous_invalid",
            "only revision one may omit previous_receipt_ref",
            field="previous_receipt_ref",
            ref=receipt.receipt_ref,
        )
    if receipt.record_revision > 1 and not receipt.previous_receipt_ref.startswith(
        "agent_workflow_closure_receipt:"
    ):
        _reject(
            violations,
            "agent_workflow_receipt_previous_invalid",
            "later revisions must bind the prior workflow receipt",
            field="previous_receipt_ref",
            ref=receipt.previous_receipt_ref,
        )
    snapshot_decision = validate_agent_workflow_closure_snapshot(
        receipt.snapshot,
        owner_user_id=receipt.owner_user_id,
        workflow_id=receipt.workflow_id,
    )
    violations.extend(snapshot_decision.violations)
    if receipt.receipt_ref != receipt.canonical_receipt_ref:
        _reject(
            violations,
            "agent_workflow_receipt_identity_mismatch",
            "receipt_ref must content-bind the complete current workflow snapshot",
            field="receipt_ref",
            ref=receipt.receipt_ref,
        )
    return AgentWorkflowClosureDecision(not violations, tuple(violations))


class PersistentAgentWorkflowClosureRegistry:
    """Schema-v2 owner ledger with per-workflow revision and hash chains."""

    def __init__(self, path: str | Path, *, resolve_snapshot: WorkflowClosureResolver) -> None:
        if not callable(resolve_snapshot):
            raise TypeError("resolve_snapshot must be callable")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._resolve_snapshot = resolve_snapshot
        self._thread_lock = threading.RLock()
        self._records: dict[tuple[str, str], AgentWorkflowClosureReceipt] = {}
        self._heads: dict[tuple[str, str], AgentWorkflowClosureReceipt] = {}
        self._head_hashes: dict[tuple[str, str], str] = {}
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

    @staticmethod
    def _workflow(value: Any) -> str:
        workflow = _text(value)
        if workflow != value or not _WORKFLOW_ID_RE.fullmatch(workflow):
            raise ValueError("workflow_id must be an exact production Agent workflow identity")
        return workflow

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _reset(self) -> None:
        self._records = {}
        self._heads = {}
        self._head_hashes = {}
        self._legacy_quarantined_count = 0

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        for line_no, line in enumerate(
            self._path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self._legacy_quarantined_count += 1
                continue
            if (
                not isinstance(row, dict)
                or row.get("schema_version")
                != AGENT_WORKFLOW_CLOSURE_SCHEMA_VERSION
            ):
                self._legacy_quarantined_count += 1
                continue
            try:
                self._apply_row(row)
            except Exception as exc:  # schema-v2 corruption must fail startup closed.
                raise ValueError(
                    f"invalid persisted agent workflow closure row at {self._path}:{line_no}"
                ) from exc

    def _apply_row(self, row: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "event_type",
            "owner_user_id",
            "workflow_id",
            "record_revision",
            "previous_record_hash",
            "receipt",
            "record_hash",
        }
        if set(row) != expected or row.get("event_type") != "agent_workflow_closure_recorded":
            raise ValueError("agent workflow closure row has an inexact schema-v2 envelope")
        owner = self._owner(row["owner_user_id"])
        workflow = self._workflow(row["workflow_id"])
        scope = (owner, workflow)
        previous = self._heads.get(scope)
        expected_revision = 1 if previous is None else previous.record_revision + 1
        expected_previous_hash = "" if previous is None else self._head_hashes[scope]
        if row["record_revision"] != expected_revision:
            raise ValueError("agent workflow closure record revision chain mismatch")
        if row["previous_record_hash"] != expected_previous_hash:
            raise ValueError("agent workflow closure previous_record_hash mismatch")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        expected_hash = "sha256:" + _sha256(body)
        if row["record_hash"] != expected_hash:
            raise ValueError("agent workflow closure record_hash mismatch")
        receipt = agent_workflow_closure_receipt_from_dict(row["receipt"])
        if (
            receipt.owner_user_id != owner
            or receipt.workflow_id != workflow
            or receipt.record_revision != expected_revision
            or receipt.previous_receipt_ref != ("" if previous is None else previous.receipt_ref)
        ):
            raise ValueError("agent workflow closure receipt chain does not match its envelope")
        decision = validate_agent_workflow_closure_receipt_shape(receipt)
        if not decision.accepted:
            raise ValueError("invalid agent workflow closure receipt shape")
        key = (owner, receipt.receipt_ref)
        existing = self._records.get(key)
        if existing is not None and existing != receipt:
            raise ValueError("agent workflow closure receipt identity collision")
        self._records[key] = receipt
        self._heads[scope] = receipt
        self._head_hashes[scope] = expected_hash

    def _resolve(self, owner: str, workflow: str) -> AgentWorkflowClosureSnapshot:
        snapshot = self._resolve_snapshot(owner, workflow)
        if not isinstance(snapshot, AgentWorkflowClosureSnapshot):
            raise TypeError("workflow closure resolver must return AgentWorkflowClosureSnapshot")
        return snapshot

    @staticmethod
    def _decision_error(decision: AgentWorkflowClosureDecision) -> AgentWorkflowClosureError:
        codes = ", ".join(item.code for item in decision.violations)
        return AgentWorkflowClosureError(f"agent workflow closure rejected: {codes}")

    def record_current(
        self,
        owner_user_id: str,
        workflow_id: str,
    ) -> AgentWorkflowClosureReceipt:
        """Resolve twice under the closure lock and append only a stable snapshot."""

        owner = self._owner(owner_user_id)
        workflow = self._workflow(workflow_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            first = self._resolve(owner, workflow)
            first_decision = validate_agent_workflow_closure_snapshot(
                first, owner_user_id=owner, workflow_id=workflow
            )
            if not first_decision.accepted:
                raise self._decision_error(first_decision)
            second = self._resolve(owner, workflow)
            second_decision = validate_agent_workflow_closure_snapshot(
                second, owner_user_id=owner, workflow_id=workflow
            )
            if not second_decision.accepted:
                raise self._decision_error(second_decision)
            if first != second:
                raise AgentWorkflowClosureError(
                    "agent workflow backing changed during closure resolution"
                )
            scope = (owner, workflow)
            previous = self._heads.get(scope)
            if previous is not None and previous.snapshot == second:
                return previous
            revision = 1 if previous is None else previous.record_revision + 1
            previous_ref = "" if previous is None else previous.receipt_ref
            blank = AgentWorkflowClosureReceipt(
                receipt_ref="",
                owner_user_id=owner,
                workflow_id=workflow,
                record_revision=revision,
                previous_receipt_ref=previous_ref,
                snapshot=second,
            )
            receipt = AgentWorkflowClosureReceipt(
                **{**asdict(blank), "receipt_ref": blank.canonical_receipt_ref, "snapshot": second}
            )
            decision = validate_agent_workflow_closure_receipt_shape(receipt)
            if not decision.accepted:
                raise self._decision_error(decision)
            previous_hash = "" if previous is None else self._head_hashes[scope]
            body = {
                "schema_version": AGENT_WORKFLOW_CLOSURE_SCHEMA_VERSION,
                "event_type": "agent_workflow_closure_recorded",
                "owner_user_id": owner,
                "workflow_id": workflow,
                "record_revision": revision,
                "previous_record_hash": previous_hash,
                "receipt": asdict(receipt),
            }
            row = {**body, "record_hash": "sha256:" + _sha256(body)}
            original_exists = self._path.exists()
            original = self._path.read_bytes() if original_exists else b""
            self._atomic_append(row)
            try:
                committed = self._resolve(owner, workflow)
                committed_decision = validate_agent_workflow_closure_snapshot(
                    committed,
                    owner_user_id=owner,
                    workflow_id=workflow,
                )
                if not committed_decision.accepted or committed != second:
                    raise AgentWorkflowClosureError(
                        "agent workflow backing changed while closure was being committed"
                    )
            except Exception:
                try:
                    self._restore_original(
                        original_exists=original_exists,
                        original=original,
                    )
                except Exception as recovery_exc:
                    raise AgentWorkflowClosureCommitUncertain(
                        "agent workflow closure became stale during commit and rollback is uncertain"
                    ) from recovery_exc
                raise
            self._records[(owner, receipt.receipt_ref)] = receipt
            self._heads[scope] = receipt
            self._head_hashes[scope] = row["record_hash"]
            return receipt

    def _restore_original(self, *, original_exists: bool, original: bytes) -> None:
        if original_exists:
            fd, raw_restore = tempfile.mkstemp(
                prefix=f".{self._path.name}.restore.",
                dir=self._path.parent,
            )
            restore = Path(raw_restore)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb", closefd=True) as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                fd = -1
                os.replace(restore, self._path)
            finally:
                if fd >= 0:
                    os.close(fd)
                restore.unlink(missing_ok=True)
        else:
            self._path.unlink(missing_ok=True)
        parent_fd = os.open(
            self._path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def _atomic_append(self, row: dict[str, Any]) -> None:
        original_exists = self._path.exists()
        original = self._path.read_bytes() if original_exists else b""
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        payload = original + separator + (_canonical_json(row) + "\n").encode("utf-8")
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        tmp = Path(raw_tmp)
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            fd = -1
            os.replace(tmp, self._path)
            replaced = True
            parent_fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except Exception as exc:
            if replaced:
                try:
                    if original_exists:
                        restore_fd, raw_restore = tempfile.mkstemp(
                            prefix=f".{self._path.name}.restore.", dir=self._path.parent
                        )
                        restore = Path(raw_restore)
                        try:
                            os.fchmod(restore_fd, 0o600)
                            with os.fdopen(restore_fd, "wb", closefd=True) as handle:
                                handle.write(original)
                                handle.flush()
                                os.fsync(handle.fileno())
                            restore_fd = -1
                            os.replace(restore, self._path)
                        finally:
                            if restore_fd >= 0:
                                os.close(restore_fd)
                            restore.unlink(missing_ok=True)
                    else:
                        self._path.unlink(missing_ok=True)
                    parent_fd = os.open(
                        self._path.parent,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                    )
                    try:
                        os.fsync(parent_fd)
                    finally:
                        os.close(parent_fd)
                except Exception as recovery_exc:  # noqa: BLE001 - commit state is unknown.
                    raise AgentWorkflowClosureCommitUncertain(
                        "agent workflow closure append failed and durable rollback is uncertain"
                    ) from recovery_exc
            raise exc
        finally:
            if fd >= 0:
                os.close(fd)
            tmp.unlink(missing_ok=True)

    def receipt(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> AgentWorkflowClosureReceipt:
        owner = self._owner(owner_user_id)
        ref = _text(receipt_ref)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._records[(owner, ref)]
            except KeyError:
                raise KeyError("agent workflow closure receipt is not recorded for owner") from None

    def current_receipt(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
    ) -> AgentWorkflowClosureReceipt:
        owner = self._owner(owner_user_id)
        workflow = self._workflow(workflow_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._heads[(owner, workflow)]
            except KeyError:
                raise KeyError("agent workflow closure has no current receipt for owner") from None

    def validate_current(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> AgentWorkflowClosureDecision:
        try:
            receipt = self.receipt(receipt_ref, owner_user_id=owner_user_id)
            current = self.current_receipt(
                owner_user_id=owner_user_id,
                workflow_id=receipt.workflow_id,
            )
            resolved = self._resolve(receipt.owner_user_id, receipt.workflow_id)
        except Exception as exc:  # noqa: BLE001 - current backing resolution fails closed.
            return AgentWorkflowClosureDecision(
                False,
                (
                    AgentWorkflowClosureViolation(
                        "agent_workflow_current_resolution_failed",
                        f"current workflow evidence could not be resolved: {type(exc).__name__}",
                        ref=_text(receipt_ref),
                    ),
                ),
            )
        violations: list[AgentWorkflowClosureViolation] = []
        if current.receipt_ref != receipt.receipt_ref:
            _reject(
                violations,
                "agent_workflow_receipt_not_head",
                "workflow receipt is no longer the current revision",
                field="receipt_ref",
                ref=receipt.receipt_ref,
            )
        resolved_decision = validate_agent_workflow_closure_snapshot(
            resolved,
            owner_user_id=receipt.owner_user_id,
            workflow_id=receipt.workflow_id,
        )
        violations.extend(resolved_decision.violations)
        if resolved != receipt.snapshot:
            _reject(
                violations,
                "agent_workflow_backing_changed",
                "one or more workflow evidence components are no longer current",
                field="snapshot",
                ref=receipt.receipt_ref,
            )
        return AgentWorkflowClosureDecision(not violations, tuple(violations))


def agent_workflow_closure_semantic_material(
    receipt: AgentWorkflowClosureReceipt,
    *,
    validation_refs: tuple[str, ...],
) -> AgentWorkflowClosureSemanticMaterial:
    snapshot = receipt.snapshot
    return AgentWorkflowClosureSemanticMaterial(
        subject_ref=f"agent_workflow:{receipt.workflow_id}:{receipt.receipt_ref}",
        producer_refs=tuple(
            dict.fromkeys(
                (
                    *(event.component_ref for event in snapshot.events),
                    *(call.component_ref for call in snapshot.terminal_calls),
                    *(attempt.component_ref for attempt in snapshot.llm_attempts),
                    snapshot.graph_command.component_ref,
                )
            )
        ),
        store_refs=tuple(
            dict.fromkeys(
                (
                    receipt.receipt_ref,
                    *(binding.component_ref for binding in snapshot.llm_use_bindings),
                    *(capability.component_ref for capability in snapshot.capability_heads),
                    snapshot.rag_usage.component_ref,
                    snapshot.qro.component_ref,
                    snapshot.compiler_ir.component_ref,
                    snapshot.compiler_pass.component_ref,
                    snapshot.entrypoint_coverage.component_ref,
                )
            )
        ),
        consumer_refs=(
            AGENT_WORKFLOW_ENTRYPOINT_REF,
            f"agent_workflow:{receipt.workflow_id}",
        ),
        gate_verdict_refs=(receipt.receipt_ref, snapshot.events[-1].component_ref),
        test_refs=tuple(dict.fromkeys(_refs(validation_refs))),
    )


class AgentWorkflowClosureSectionAdapter:
    """Read-only GOAL section 7 adapter over one current receipt and coverage."""

    def __init__(
        self,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        closure_registry: PersistentAgentWorkflowClosureRegistry,
    ) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._closure_registry = closure_registry

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
                    "goal_semantic_agent_workflow_closure_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        owner = _text(owner)
        if record.section != "§7":
            reject("section", record.section, "agent workflow closure adapter only supports §7")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject("recorded_by", record.recorded_by, "§7 semantic proof owner mismatch")
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "§7 completion requires an explicit complete claim with no residuals",
            )
        if len(record.entrypoint_coverage_refs) != 1:
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "§7 requires exactly one Agent Shell entrypoint coverage",
            )
            return GoalSemanticDecision(False, tuple(violations))
        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
            coverage_decision = self._entrypoint_registry.validate_real_backing(coverage)
        except Exception:  # noqa: BLE001 - coverage resolution fails closed.
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "Agent Shell entrypoint coverage could not be resolved for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not bool(getattr(coverage_decision, "accepted", False)):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "Agent Shell entrypoint coverage failed strict current backing",
            )
        if (
            self._entry_source(coverage) != "agent_shell"
            or _text(getattr(coverage, "entrypoint_ref", "")) != AGENT_WORKFLOW_ENTRYPOINT_REF
            or "§7" not in set(getattr(coverage, "goal_sections", ()) or ())
        ):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§7 requires the canonical Agent workbench Agent Shell lineage",
            )
        if bool(getattr(coverage, "silent_mock_fallback_used", False)) or bool(
            getattr(coverage, "raw_payload_persisted", False)
        ):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "Agent Shell coverage cannot use a silent mock or persist raw payloads",
            )

        receipt_refs = tuple(
            ref
            for ref in record.gate_verdict_refs
            if ref.startswith("agent_workflow_closure_receipt:")
        )
        if len(receipt_refs) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(record.gate_verdict_refs),
                "§7 requires exactly one durable workflow closure receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._closure_registry.receipt(receipt_ref, owner_user_id=owner)
            current = self._closure_registry.validate_current(
                receipt_ref, owner_user_id=owner
            )
        except Exception:  # noqa: BLE001 - receipt resolution fails closed.
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§7 workflow closure receipt could not be resolved for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not current.accepted:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§7 workflow closure receipt is no longer current",
            )
        snapshot = receipt.snapshot
        if snapshot.entrypoint_coverage.component_ref != coverage_ref:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "workflow receipt and semantic proof recombine different entrypoint lineages",
            )
        expected_coverage_refs = {
            "qro_refs": (snapshot.qro.component_ref,),
            "research_graph_command_refs": (snapshot.graph_command.component_ref,),
            "compiler_ir_refs": (snapshot.compiler_ir.component_ref,),
            "compiler_pass_refs": (snapshot.compiler_pass.component_ref,),
        }
        for field_name, expected in expected_coverage_refs.items():
            if tuple(getattr(coverage, field_name, ()) or ()) != expected:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"coverage {field_name} does not equal the workflow receipt lineage",
                )
        validation_refs = tuple(getattr(coverage, "validation_refs", ()) or ())
        if not validation_refs:
            reject(
                "test_refs",
                coverage_ref,
                "Agent Shell coverage must retain real validation refs",
            )
        material = agent_workflow_closure_semantic_material(
            receipt,
            validation_refs=validation_refs,
        )
        for field_name in (
            "subject_ref",
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            if tuple(_refs(getattr(record, field_name))) != tuple(
                _refs(getattr(material, field_name))
            ):
                reject(
                    field_name,
                    ",".join(_refs(getattr(record, field_name))),
                    f"§7 {field_name} must equal the current workflow closure material",
                )
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "AGENT_WORKFLOW_CLOSURE_RECEIPT_VERSION",
    "AGENT_WORKFLOW_CLOSURE_SCHEMA_VERSION",
    "AGENT_WORKFLOW_ENTRYPOINT_REF",
    "AGENT_WORKFLOW_REQUIRED_CAPABILITY_KINDS",
    "AgentWorkflowClosureCommitUncertain",
    "AgentWorkflowClosureDecision",
    "AgentWorkflowClosureError",
    "AgentWorkflowClosureReceipt",
    "AgentWorkflowClosureSectionAdapter",
    "AgentWorkflowClosureSemanticMaterial",
    "AgentWorkflowClosureSnapshot",
    "AgentWorkflowClosureViolation",
    "AgentWorkflowComponentState",
    "PersistentAgentWorkflowClosureRegistry",
    "agent_workflow_closure_receipt_from_dict",
    "agent_workflow_closure_receipt_identity",
    "agent_workflow_closure_semantic_material",
    "agent_workflow_closure_snapshot_from_dict",
    "validate_agent_workflow_closure_receipt_shape",
    "validate_agent_workflow_closure_snapshot",
]
