from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.research_os.agent_workflow_closure import AGENT_WORKFLOW_ENTRYPOINT_REF
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    goal_entrypoint_coverage_identity,
)
from app.research_os.platform_coverage import PlatformCapabilityRecord
from app.research_os.ref_resolution import RealRefResolver
from app.research_os.platform_source_lineage_policies_m9_m15 import (
    M9,
    M10,
    M10_SPINE_BINDING_ENTRYPOINT_REF,
    M11,
    M11_SPINE_BINDING_ENTRYPOINT_REF,
    M12,
    M12_SPINE_BINDING_ENTRYPOINT_REF,
    M13,
    M13_M14_SPINE_BINDING_ENTRYPOINT_REF,
    M14,
    M15,
    M9_SPINE_BINDING_ENTRYPOINT_REF,
    POLICY_VERSION,
    PlatformSourceLineagePoliciesM9M15Context,
    PlatformSourceLineagePoliciesM9M15Error,
    build_platform_source_lineage_policies_m9_m15,
    unavailable_platform_source_lineage_policies_m9_m15,
)


OWNER = "owner:platform-policy:m9-m15"
OTHER_OWNER = "owner:platform-policy:m9-m15:other"
SERVICE_OWNER = "service:llm-gateway"
REVIEWER = "reviewer:platform-policy:m12"
MODEL_ID = "logical-model:m12"
MODEL_ASSET_REF = "model-asset:m12"
REVIEWER_GRANT_REF = "model_reviewer_grant:m12"
REVIEWER_GRANT_HASH = "sha256:m12-reviewer-grant"
WORKFLOW = "agentwf_" + "a" * 64
WORKFLOW_GOAL_SECTIONS = ("§0", "§1", "§5", "§7", "§8")
BINDING_ENTRYPOINTS = {
    M9: M9_SPINE_BINDING_ENTRYPOINT_REF,
    M10: M10_SPINE_BINDING_ENTRYPOINT_REF,
    M11: M11_SPINE_BINDING_ENTRYPOINT_REF,
    M12: M12_SPINE_BINDING_ENTRYPOINT_REF,
    M13: M13_M14_SPINE_BINDING_ENTRYPOINT_REF,
    M14: M13_M14_SPINE_BINDING_ENTRYPOINT_REF,
}
BUSINESS_ENTRYPOINTS = {
    M9: "api:research_os.execution.order_intents",
    M10: "ide:strategy.run",
    M11: "api:goal.lifecycle.closure",
    M12: "api:models.gates.approve",
    M13: AGENT_WORKFLOW_ENTRYPOINT_REF,
    M14: AGENT_WORKFLOW_ENTRYPOINT_REF,
}
BUSINESS_SOURCES = {
    M9: "api",
    M10: "ide",
    M11: "api",
    M12: "api",
    M13: "agent_shell",
    M14: "agent_shell",
}


def _decision(accepted: bool = True):
    return SimpleNamespace(accepted=accepted, violations=())


class _Unavailable:
    def __getattr__(self, name: str):
        def missing(*_args, **_kwargs):
            raise KeyError(name)

        return missing


class _Graph:
    def __init__(self):
        self.qros: dict[str, SimpleNamespace] = {}
        self.command_rows: list[SimpleNamespace] = []
        self.projections: list[SimpleNamespace] = []

    def add(
        self,
        qro,
        command_ref: str,
        *,
        actor: str | None = None,
        source: str = "api",
        actor_source: str = "user_manual",
        evidence_refs: tuple[str, ...] = (),
        tool_record_refs: tuple[str, ...] = (),
    ):
        self.qros[qro.qro_id] = qro
        command = SimpleNamespace(
            command_id=command_ref,
            command_type="upsert_qro",
            actor=actor or qro.owner,
            source=source,
            actor_source=actor_source,
            payload={"qro": qro},
            evidence_refs=evidence_refs,
            tool_record_refs=tool_record_refs,
        )
        self.command_rows.append(command)
        return command

    def qro(self, ref):
        return self.qros[ref]

    def commands(self):
        return list(self.command_rows)

    def projection_index(self, *, owner):
        return [item for item in self.projections if item.owner == owner]


class _Compiler:
    def __init__(self):
        self.ir_rows: list[SimpleNamespace] = []
        self.pass_rows: list[SimpleNamespace] = []

    def add(
        self,
        qro,
        command,
        source: str,
        entrypoint: str,
        *,
        ref_suffix: str = "",
    ):
        suffix = f":{ref_suffix}" if ref_suffix else ""
        ir = SimpleNamespace(
            ir_ref=f"compiler_ir:{qro.qro_id}{suffix}",
            source_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=(
                f"research_graph_command:{command.command_id}",
                f"entrypoint:{entrypoint}",
            ),
            mathematical_spine_chain_refs=tuple(qro.mathematical_refs),
            owner=OWNER,
        )
        compiler_pass = SimpleNamespace(
            pass_ref=f"compiler_pass:{qro.qro_id}{suffix}",
            output_ir_ref=ir.ir_ref,
            input_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=ir.canonical_command_refs,
            actor=OWNER,
            status="compiled",
            entry_source=source,
        )
        self.ir_rows.append(ir)
        self.pass_rows.append(compiler_pass)
        return ir, compiler_pass

    def irs(self, *, owner):
        return [item for item in self.ir_rows if item.owner == owner]

    def passes(self, *, owner):
        return [item for item in self.pass_rows if item.actor == owner]

    def ir(self, ref, *, owner):
        return next(item for item in self.irs(owner=owner) if item.ir_ref == ref)

    def compiler_pass(self, ref, *, owner):
        return next(item for item in self.passes(owner=owner) if item.pass_ref == ref)

    def canonical_ir(self, ref, *, owner):
        return self.ir(ref, owner=owner)

    def canonical_compiler_pass(self, ref, *, owner):
        return self.compiler_pass(ref, owner=owner)


class _Spines:
    def __init__(self):
        self.rows: dict[str, SimpleNamespace] = {}

    def add(self, row: str, *refs: str):
        chain = SimpleNamespace(
            chain_ref=f"math:{row}",
            recorded_by=OWNER,
            evidence_refs=tuple(refs),
        )
        self.rows[chain.chain_ref] = chain
        return chain

    def chains(self, *, owner):
        return [item for item in self.rows.values() if item.recorded_by == owner]

    def verified_chain(self, ref, *, owner):
        value = self.rows[ref]
        if value.recorded_by != owner:
            raise KeyError(ref)
        return value


class _ExecutionClosures:
    def __init__(self, receipt):
        self.value = receipt
        self.current = True

    def receipt(self, ref, *, owner_user_id):
        if ref != self.value.receipt_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.value

    def validate_current(self, ref, *, owner_user_id):
        return _decision(
            self.current and ref == self.value.receipt_ref and owner_user_id == OWNER
        )


class _Intents:
    def __init__(self, intent):
        self.value = intent

    def intent(self, ref):
        if ref != self.value.order_intent_ref:
            raise KeyError(ref)
        return self.value


class _Market:
    def __init__(self, use, matrix):
        self.use = use
        self.matrix = matrix

    def use_validation(self, ref, *, owner_user_id):
        if ref != self.use.validation_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.use

    def capability_matrix(self, ref, *, owner_user_id):
        if ref != self.matrix.matrix_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.matrix


class _BacktestEvidence:
    def __init__(self, attribution, monitor):
        self.attribution_row = attribution
        self.monitor_row = monitor
        self.attribution_current = True
        self.monitor_current = True

    def attribution(self, ref, *, owner_user_id):
        if ref != self.attribution_row.attribution_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.attribution_row

    def monitor(self, ref, *, owner_user_id):
        if ref != self.monitor_row.monitor_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.monitor_row

    def validate_current_attribution(self, ref, *, owner_user_id):
        return _decision(
            self.attribution_current
            and ref == self.attribution_row.attribution_ref
            and owner_user_id == OWNER
        )

    def validate_current_monitor(self, ref, *, owner_user_id):
        return _decision(
            self.monitor_current
            and ref == self.monitor_row.monitor_ref
            and owner_user_id == OWNER
        )


class _Methodologies:
    def __init__(self, record, binding):
        self.record = record
        self.binding = binding

    def methodology(self, ref, *, owner_user_id):
        if ref != self.record.validation_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.record

    def methodology_binding(self, ref, *, owner_user_id):
        if ref != self.record.validation_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.binding


class _Depths:
    def __init__(self, record, binding):
        self.record = record
        self.binding = binding

    def depth(self, ref, *, owner_user_id):
        if ref != self.record.depth_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.record

    def depth_binding(self, ref, *, owner_user_id):
        if ref != self.record.depth_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.binding


class _Assets:
    def __init__(self, asset):
        self.value = asset

    def governed_asset(self, ref, *, owner_user_id):
        if ref != self.value.asset_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.value


class _Transitions:
    def __init__(self, transition, receipt):
        self.transition_row = transition
        self.receipt_rows = [receipt]
        self.current = True

    def transition(self, ref, *, owner_user_id):
        if ref != self.transition_row.transition_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.transition_row

    def receipts(self, *, owner_user_id):
        return list(self.receipt_rows) if owner_user_id == OWNER else []

    def validate_current(self, ref, *, owner_user_id):
        return _decision(
            self.current
            and owner_user_id == OWNER
            and any(item.receipt_ref == ref for item in self.receipt_rows)
        )


class _Governance:
    def __init__(self, passport, recert, head):
        self.passport_row = passport
        self.recert_row = recert
        self.head = head

    def passport(self, ref, *, owner_user_id):
        if ref != self.passport_row.passport_id or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.passport_row

    def recertification_record(self, ref, *, owner_user_id):
        if ref != self.recert_row.recertification_record_id or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.recert_row

    def current_head_hash(self, ref, *, owner_user_id, event_type=None):
        if (
            ref != self.recert_row.recertification_record_id
            or owner_user_id != OWNER
            or event_type != "model_recertification_recorded"
        ):
            raise KeyError(ref)
        return self.head


class _Models:
    def __init__(self, gate):
        self.gate = gate
        self.authority_current = True
        self.authority_calls: list[dict[str, object]] = []
        self.grant = SimpleNamespace(
            grant_id=REVIEWER_GRANT_REF,
            gate_id=gate.gate_id,
            owner_user_id=OWNER,
            model_id=MODEL_ID,
            model_asset_ref=gate.model_id,
            model_version=gate.version,
            reviewer_user_id=REVIEWER,
            permissions=("approve",),
            record_hash=REVIEWER_GRANT_HASH,
        )

    def promotion_gate(self, ref, *, owner_user_id):
        if ref != self.gate.gate_id or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.gate

    def promotion_reviewer_authority_evidence(
        self,
        gate_id,
        *,
        model_id,
        reviewer_user_id,
        grant_id,
        grant_record_hash,
        permission,
    ):
        call = {
            "gate_id": gate_id,
            "model_id": model_id,
            "reviewer_user_id": reviewer_user_id,
            "grant_id": grant_id,
            "grant_record_hash": grant_record_hash,
            "permission": permission,
        }
        self.authority_calls.append(call)
        if not self.authority_current or call != {
            "gate_id": self.gate.gate_id,
            "model_id": MODEL_ID,
            "reviewer_user_id": REVIEWER,
            "grant_id": REVIEWER_GRANT_REF,
            "grant_record_hash": REVIEWER_GRANT_HASH,
            "permission": "approve",
        }:
            raise ValueError("promotion gate reviewer authority evidence is invalid")
        return self.grant


class _AgentLedger:
    def __init__(self, heads):
        self.heads = heads
        self.current = True

    def current_head(self, *, owner_user_id, workflow_id, capability_kind):
        if owner_user_id != OWNER or workflow_id != WORKFLOW:
            raise KeyError(capability_kind)
        return self.heads[capability_kind]

    def record(self, ref, *, owner_user_id):
        if owner_user_id != OWNER:
            raise KeyError(ref)
        return next(item for item in self.heads.values() if item.record_ref == ref)

    def validate_current(self, ref, *, owner_user_id):
        return _decision(
            self.current
            and owner_user_id == OWNER
            and any(item.record_ref == ref for item in self.heads.values())
        )


class _WorkflowClosures:
    def __init__(self, receipt):
        self.value = receipt
        self.current = True

    def receipt(self, ref, *, owner_user_id):
        if ref != self.value.receipt_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.value

    def current_receipt(self, *, owner_user_id, workflow_id):
        if owner_user_id != OWNER or workflow_id != WORKFLOW:
            raise KeyError(workflow_id)
        return self.value

    def validate_current(self, ref, *, owner_user_id):
        return _decision(
            self.current and ref == self.value.receipt_ref and owner_user_id == OWNER
        )


class _RAG:
    def __init__(self, usage):
        self.usage = usage
        self.current = True

    def strict_usage_for_owner(self, ref, *, owner_user_id):
        if ref != self.usage.usage_id or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.usage

    def validate_current_usage(self, ref, *, owner_user_id):
        return _decision(
            self.current and ref == self.usage.usage_id and owner_user_id == OWNER
        )


class _Calls:
    def __init__(self, terminal):
        self.terminal = terminal

    def resolve_terminal_record(self, call_id, owner_user_id):
        if call_id != self.terminal.call_id or owner_user_id != OWNER:
            raise KeyError(call_id)
        return self.terminal


class _Bindings:
    def __init__(self, binding):
        self.binding = binding
        self.current = True

    def binding_for_terminal(self, call_id, *, owner_user_id):
        if call_id != self.binding.terminal_call_id or owner_user_id != OWNER:
            raise KeyError(call_id)
        return self.binding

    def validate_current(self, ref, *, owner_user_id):
        return _decision(
            self.current and ref == self.binding.binding_ref and owner_user_id == OWNER
        )


class _Onboarding:
    def __init__(self, routing, pool):
        self.routing = routing
        self.pool = pool

    def routing_policy(self, ref, *, owner_user_id):
        if ref != self.routing.routing_policy_id or owner_user_id != SERVICE_OWNER:
            raise KeyError(ref)
        return self.routing

    def credential_pool(self, ref, *, owner_user_id):
        if ref != self.pool.pool_id or owner_user_id != SERVICE_OWNER:
            raise KeyError(ref)
        return self.pool


class _CanonicalSpine:
    def __init__(self, tib, checks):
        self.tib = tib
        self.checks = checks

    def binding(self, ref, *, owner):
        if ref != self.tib.binding_id or owner != OWNER:
            raise KeyError(ref)
        return self.tib

    def checks_for(self, ref, *, owner):
        if ref != self.tib.binding_id or owner != OWNER:
            raise KeyError(ref)
        return list(self.checks)


class _Topologies:
    def __init__(self, receipt, topology):
        self.receipt_row = receipt
        self.topology_row = topology
        self.current = topology
        self.accepted = True

    def receipt(self, ref, *, owner_user_id):
        if ref != self.receipt_row.receipt_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.receipt_row

    def topology(self, ref, *, owner_user_id):
        if ref != self.topology_row.topology_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.topology_row

    def current_topology(self, *, owner_user_id):
        if owner_user_id != OWNER:
            raise KeyError(owner_user_id)
        return self.current

    def validate_current_receipt(self, value, *, owner_user_id):
        return _decision(
            self.accepted and value == self.receipt_row and owner_user_id == OWNER
        )

    def validate_topology_current(self, value, *, owner_user_id):
        return _decision(
            self.accepted and value == self.current and owner_user_id == OWNER
        )


def _qro(
    ref: str,
    kind: str,
    inputs: dict,
    outputs: dict,
    math_ref: str | None,
):
    return SimpleNamespace(
        qro_id=ref,
        qro_type=kind,
        owner=OWNER,
        input_contract=dict(inputs),
        output_contract=dict(outputs),
        implementation_hash=f"implementation:{ref}",
        mathematical_refs=(math_ref,) if math_ref else (),
        theory_implementation_binding="",
    )


def _bind_qro_math(qro: SimpleNamespace, math_ref: str) -> SimpleNamespace:
    values = dict(vars(qro))
    values["input_contract"] = dict(qro.input_contract)
    values["output_contract"] = dict(qro.output_contract)
    values["mathematical_refs"] = (math_ref,)
    return SimpleNamespace(**values)


def _projection(
    qro: SimpleNamespace,
    command: SimpleNamespace,
    projection_ref: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        projection_ref=projection_ref,
        qro_id=qro.qro_id,
        command_id=command.command_id,
        owner=qro.owner,
        actor=command.actor,
        source=command.source,
        actor_source=command.actor_source,
        mathematical_refs=tuple(qro.mathematical_refs),
    )


def _dag_head(kind: str, source_ref: str):
    return SimpleNamespace(
        record_ref=f"agent_capability:{kind}",
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=kind,
        source_ref=source_ref,
        payload={
            "mode": {
                "dag_checkpoint": "run",
                "dag_replay": "replay",
                "dag_fork": "fork",
                "dag_rollback": "rollback",
            }[kind],
            "succeeded": True,
            "nodes": [{"task_id": "task-a", "checkpoint_ref": "checkpoint:m13"}],
            "node_id_by_task": [
                {"task_id": "task-a", "checkpoint_ref": "checkpoint:m13"}
            ],
        },
    )


def _state_hash(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _component(
    ref: str,
    *,
    status: str = "current",
    links: dict | None = None,
    value=None,
    principal_id: str = OWNER,
):
    return SimpleNamespace(
        component_ref=ref,
        principal_id=principal_id,
        revision="1",
        state_hash=_state_hash(value if value is not None else {"ref": ref}),
        status=status,
        link_map=dict(links or {}),
    )


def _build_system():
    graph = _Graph()
    compiler = _Compiler()
    spines = _Spines()

    # M9: execution closure -> order intent -> market use/matrix -> QRO/compiler/math.
    intent = SimpleNamespace(
        order_intent_ref="order_intent:m9",
        recorded_by=OWNER,
        market_data_use_validation_ref="market_data_use:m9",
        execution_policy_ref="execution_policy:m9",
        risk_policy_ref="risk_policy:m9",
    )
    use = SimpleNamespace(
        validation_ref=intent.market_data_use_validation_ref,
        recorded_by=OWNER,
        capability_matrix_ref="capability:m9",
        accepted=True,
        violation_codes=(),
    )
    matrix = SimpleNamespace(matrix_ref=use.capability_matrix_ref)
    m9_receipt = SimpleNamespace(
        receipt_ref="execution_closure_receipt:m9",
        owner_user_id=OWNER,
        order_intent_ref=intent.order_intent_ref,
    )
    m9_chain = spines.add(
        M9,
        m9_receipt.receipt_ref,
        intent.order_intent_ref,
        use.validation_ref,
        matrix.matrix_ref,
        intent.execution_policy_ref,
        intent.risk_policy_ref,
    )
    m9_business_qro = _qro(
        "qro:m9",
        "ExecutionPolicy",
        {
            "order_intent_ref": intent.order_intent_ref,
            "market_data_use_validation_ref": use.validation_ref,
        },
        {
            "execution_policy_ref": intent.execution_policy_ref,
            "risk_policy_ref": intent.risk_policy_ref,
        },
        None,
    )
    m9_business_command = graph.add(m9_business_qro, "rgcmd:m9:business")
    compiler.add(
        m9_business_qro,
        m9_business_command,
        "api",
        "api:research_os.execution.order_intents",
        ref_suffix="business",
    )
    m9_qro = _bind_qro_math(m9_business_qro, m9_chain.chain_ref)
    m9_command = graph.add(
        m9_qro,
        "rgcmd:m9:spine-binding",
        evidence_refs=(m9_chain.chain_ref, m9_business_command.command_id),
        tool_record_refs=(M9_SPINE_BINDING_ENTRYPOINT_REF,),
    )
    compiler.add(
        m9_qro,
        m9_command,
        "api",
        M9_SPINE_BINDING_ENTRYPOINT_REF,
        ref_suffix="spine-binding",
    )
    graph.projections.append(_projection(m9_qro, m9_command, "rgproj:m9:spine-binding"))

    # M10: current monitor -> attribution -> methodology/depth -> BacktestRun.
    methodology = SimpleNamespace(validation_ref="validation_methodology:m10")
    depth = SimpleNamespace(depth_ref="validation_depth:m10")
    method_binding = SimpleNamespace(
        owner_user_id=OWNER,
        backtest_run_ref="qro:m10",
        source_run_ref="ide_run:m10",
    )
    depth_binding = SimpleNamespace(**vars(method_binding))
    attribution = SimpleNamespace(
        attribution_ref="attribution:m10",
        owner_user_id=OWNER,
        backtest_run_ref="qro:m10",
        validation_methodology_ref=methodology.validation_ref,
        validation_depth_ref=depth.depth_ref,
    )
    monitor = SimpleNamespace(
        monitor_ref="monitor:m10",
        owner_user_id=OWNER,
        backtest_run_ref="qro:m10",
        attribution_ref=attribution.attribution_ref,
    )
    m10_chain = spines.add(
        M10,
        "qro:m10",
        methodology.validation_ref,
        depth.depth_ref,
        attribution.attribution_ref,
        monitor.monitor_ref,
    )
    m10_business_qro = _qro(
        "qro:m10",
        "BacktestRun",
        {"source_run_ref": method_binding.source_run_ref},
        {"status": "succeeded"},
        None,
    )
    m10_business_command = graph.add(
        m10_business_qro,
        "rgcmd:m10:business",
        source="ide",
    )
    compiler.add(
        m10_business_qro,
        m10_business_command,
        "ide",
        "ide:strategy.run",
        ref_suffix="business",
    )
    m10_qro = _bind_qro_math(m10_business_qro, m10_chain.chain_ref)
    m10_command = graph.add(
        m10_qro,
        "rgcmd:m10:spine-binding",
        evidence_refs=(m10_chain.chain_ref, m10_business_command.command_id),
        tool_record_refs=(M10_SPINE_BINDING_ENTRYPOINT_REF,),
    )
    compiler.add(
        m10_qro,
        m10_command,
        "api",
        M10_SPINE_BINDING_ENTRYPOINT_REF,
        ref_suffix="spine-binding",
    )
    graph.projections.append(
        _projection(m10_qro, m10_command, "rgproj:m10:spine-binding")
    )

    # M11: transition -> exactly one current lifecycle receipt/current asset.
    asset = SimpleNamespace(asset_ref="governed_asset:m11", owner_user_id=OWNER)
    transition = SimpleNamespace(
        transition_ref="lifecycle_transition:m11",
        canonical_ref="lifecycle_transition:m11",
        owner_user_id=OWNER,
        after_asset_ref=asset.asset_ref,
    )
    lifecycle_receipt = SimpleNamespace(
        receipt_ref="lifecycle_closure_receipt:m11",
        owner_user_id=OWNER,
        transition_refs=(transition.transition_ref,),
        current_asset_refs=(asset.asset_ref,),
    )
    m11_chain = spines.add(
        M11,
        lifecycle_receipt.receipt_ref,
        transition.transition_ref,
        asset.asset_ref,
    )
    m11_business_qro = _qro(
        "qro:m11",
        "ValidationDossier",
        {"lifecycle_transition_refs": list(lifecycle_receipt.transition_refs)},
        {"lifecycle_closure_receipt_ref": lifecycle_receipt.receipt_ref},
        None,
    )
    m11_business_command = graph.add(m11_business_qro, "rgcmd:m11:business")
    compiler.add(
        m11_business_qro,
        m11_business_command,
        "api",
        "api:goal.lifecycle.closure",
        ref_suffix="business",
    )
    m11_qro = _bind_qro_math(m11_business_qro, m11_chain.chain_ref)
    m11_command = graph.add(
        m11_qro,
        "rgcmd:m11:spine-binding",
        evidence_refs=(m11_chain.chain_ref, m11_business_command.command_id),
        tool_record_refs=(M11_SPINE_BINDING_ENTRYPOINT_REF,),
    )
    compiler.add(
        m11_qro,
        m11_command,
        "api",
        M11_SPINE_BINDING_ENTRYPOINT_REF,
        ref_suffix="spine-binding",
    )
    graph.projections.append(
        _projection(m11_qro, m11_command, "rgproj:m11:spine-binding")
    )

    # M12: approved promotion gate -> passport/current recertification -> QRO.
    passport = SimpleNamespace(
        passport_id="model_passport_m12",
        owner_user_id=OWNER,
        model_version_ref="model_version:m12",
    )
    recert = SimpleNamespace(
        recertification_record_id="model_recertification_m12",
        owner_user_id=OWNER,
        model_passport_ref=passport.passport_id,
        model_version_ref=passport.model_version_ref,
    )
    recert_head = "model_head:m12"
    gate = SimpleNamespace(
        gate_id="gate-m12",
        model_id=MODEL_ASSET_REF,
        version=7,
        approver=REVIEWER,
        decision="approved",
        side_effect_executed=True,
        side_effect_ref="stage:m12:staging",
        evidence={
            "owner_user_id": OWNER,
            "logical_model_id": MODEL_ID,
            "model_passport_ref": passport.passport_id,
            "model_recertification_record_refs": [recert.recertification_record_id],
            "model_recertification_record_head_hashes": {
                recert.recertification_record_id: recert_head
            },
            "reviewer_user_id": REVIEWER,
            "reviewer_grant_id": REVIEWER_GRANT_REF,
            "reviewer_grant_record_hash": REVIEWER_GRANT_HASH,
        },
    )
    m12_chain = spines.add(
        M12,
        gate.gate_id,
        passport.passport_id,
        recert.recertification_record_id,
        passport.model_version_ref,
    )
    m12_business_qro = _qro(
        "qro:m12",
        "Model",
        {
            "gate_id": gate.gate_id,
            "model": MODEL_ID,
            "model_version_ref": passport.model_version_ref,
            "delegated_actor": REVIEWER,
            "delegated_actor_authority_ref": REVIEWER_GRANT_REF,
            "delegated_actor_authority_hash": REVIEWER_GRANT_HASH,
        },
        {
            "gate_id": gate.gate_id,
            "model": MODEL_ID,
            "model_passport_ref": passport.passport_id,
            "decision": "approved",
            "side_effect_ref": gate.side_effect_ref,
            "approved_by": REVIEWER,
            "status": "promotion_gate_approved",
        },
        None,
    )
    m12_business_command = graph.add(
        m12_business_qro,
        "rgcmd:m12:business",
        actor=REVIEWER,
    )
    compiler.add(
        m12_business_qro,
        m12_business_command,
        "api",
        "api:models.gates.approve",
        ref_suffix="business",
    )
    m12_qro = _bind_qro_math(m12_business_qro, m12_chain.chain_ref)
    m12_command = graph.add(
        m12_qro,
        "rgcmd:m12:spine-binding",
        evidence_refs=(m12_chain.chain_ref, m12_business_command.command_id),
        tool_record_refs=(M12_SPINE_BINDING_ENTRYPOINT_REF,),
    )
    compiler.add(
        m12_qro,
        m12_command,
        "api",
        M12_SPINE_BINDING_ENTRYPOINT_REF,
        ref_suffix="spine-binding",
    )
    graph.projections.append(
        _projection(m12_qro, m12_command, "rgproj:m12:spine-binding")
    )

    # M13/M14 share one immutable Agent Shell workflow snapshot and one later
    # owner/API binder projection for the same QRO id.
    heads = {
        "dag_checkpoint": _dag_head("dag_checkpoint", "dag_run:m13"),
        "dag_replay": _dag_head("dag_replay", "replay:m13"),
        "dag_fork": _dag_head("dag_fork", "fork:m13"),
        "dag_rollback": _dag_head("dag_rollback", "rollback:m13"),
    }
    terminal = SimpleNamespace(
        call_id="call-m14",
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        record_kind="terminal",
        status="ok",
        provider="openai",
        auth_ref="secretref:openai:m14",
    )
    binding = SimpleNamespace(
        binding_ref="llm_use_binding:m14",
        owner_user_id=OWNER,
        terminal_call_id=terminal.call_id,
        terminal_status="ok",
        workflow_id=WORKFLOW,
        routing_policy_ref="model_routing_policy:m14",
        credential_pool_ref="credential_pool:m14",
        service_principal_ref=SERVICE_OWNER,
    )
    tib = SimpleNamespace(
        binding_id="tib_m14",
        consistency_verdict="server_property_check",
    )
    workflow_receipt_ref = "agent_workflow_closure_receipt:m13-m14"
    workflow_chain = spines.add(
        "M13-M14",
        workflow_receipt_ref,
        *(item.source_ref for item in heads.values()),
        "checkpoint:m13",
        tib.binding_id,
        f"llm_gateway:{terminal.call_id}",
        binding.binding_ref,
        binding.routing_policy_ref,
        binding.credential_pool_ref,
    )
    workflow_business_qro = _qro(
        "qro:workflow",
        "AgentWorkflow",
        {"workflow_id": WORKFLOW},
        {"status": "succeeded"},
        None,
    )
    workflow_business_qro.theory_implementation_binding = tib.binding_id
    workflow_business_command = graph.add(
        workflow_business_qro,
        "rgcmd:workflow:business",
        source="agent_shell",
        actor_source="agent",
    )
    workflow_business_ir, workflow_business_pass = compiler.add(
        workflow_business_qro,
        workflow_business_command,
        "agent_shell",
        AGENT_WORKFLOW_ENTRYPOINT_REF,
        ref_suffix="business",
    )
    workflow_qro = _bind_qro_math(
        workflow_business_qro,
        workflow_chain.chain_ref,
    )
    workflow_command = graph.add(
        workflow_qro,
        "rgcmd:workflow:spine-binding",
        evidence_refs=(
            workflow_chain.chain_ref,
            workflow_business_command.command_id,
        ),
        tool_record_refs=(M13_M14_SPINE_BINDING_ENTRYPOINT_REF,),
    )
    workflow_ir, workflow_pass = compiler.add(
        workflow_qro,
        workflow_command,
        "api",
        M13_M14_SPINE_BINDING_ENTRYPOINT_REF,
        ref_suffix="spine-binding",
    )
    graph.projections.append(
        _projection(
            workflow_qro,
            workflow_command,
            "rgproj:workflow:spine-binding",
        )
    )
    usage = SimpleNamespace(
        usage_id="rag_usage:workflow",
        owner_user_id=OWNER,
        workflow_ref=WORKFLOW,
        actor="agent",
        returned_documents=(
            SimpleNamespace(document_id="rag_document:upstream:m13-m14"),
        ),
    )
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source="agent_shell",
        entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
        goal_sections=WORKFLOW_GOAL_SECTIONS,
        qro_refs=(workflow_business_qro.qro_id,),
        research_graph_command_refs=(workflow_business_command.command_id,),
        compiler_ir_refs=(workflow_business_ir.ir_ref,),
        compiler_pass_refs=(workflow_business_pass.pass_ref,),
    )
    workflow_coverage = GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source="agent_shell",
        entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
        goal_sections=WORKFLOW_GOAL_SECTIONS,
        qro_refs=(workflow_business_qro.qro_id,),
        research_graph_command_refs=(workflow_business_command.command_id,),
        compiler_ir_refs=(workflow_business_ir.ir_ref,),
        compiler_pass_refs=(workflow_business_pass.pass_ref,),
        evidence_refs=(usage.usage_id,),
        validation_refs=("validation:workflow",),
        permission_refs=("permission:workflow",),
        replay_refs=("replay:workflow",),
        recorded_by=OWNER,
    )
    coverage_links = {
        "entry_source": "agent_shell",
        "entrypoint_ref": AGENT_WORKFLOW_ENTRYPOINT_REF,
        "workflow_id": WORKFLOW,
        "rag_usage_ref": usage.usage_id,
        "qro_ref": workflow_business_qro.qro_id,
        "graph_command_ref": workflow_business_command.command_id,
        "compiler_ir_ref": workflow_business_ir.ir_ref,
        "compiler_pass_ref": workflow_business_pass.pass_ref,
    }
    snapshot = SimpleNamespace(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        qro=_component(
            workflow_business_qro.qro_id,
            value=workflow_business_qro,
        ),
        graph_command=_component(
            workflow_business_command.command_id,
            value=workflow_business_command,
        ),
        compiler_ir=_component(
            workflow_business_ir.ir_ref,
            value=workflow_business_ir,
        ),
        compiler_pass=_component(
            workflow_business_pass.pass_ref,
            status="passed",
            value=workflow_business_pass,
        ),
        entrypoint_coverage=_component(
            coverage_ref,
            status="current",
            links=coverage_links,
            value=workflow_coverage,
        ),
        rag_usage=_component(usage.usage_id, status="accepted"),
        terminal_calls=(_component(terminal.call_id),),
        llm_use_bindings=(_component(binding.binding_ref),),
    )
    workflow_receipt = SimpleNamespace(
        receipt_ref=workflow_receipt_ref,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        snapshot=snapshot,
    )
    routing = SimpleNamespace(
        routing_policy_id=binding.routing_policy_ref,
        credential_pool_ref=binding.credential_pool_ref,
    )
    pool = SimpleNamespace(
        pool_id=binding.credential_pool_ref,
        owner=SERVICE_OWNER,
        provider_id=terminal.provider,
        auth_refs=(terminal.auth_ref,),
        revoked_refs=(),
    )
    checks = ({"binding_id": tib.binding_id, "result": "pass"},)

    # M15: current topology receipt -> QRO/Graph/projection + exact QRO math.
    topology = SimpleNamespace(topology_ref="desk_topology:m15", owner_user_id=OWNER)
    topology_receipt = SimpleNamespace(
        receipt_ref="desk_topology_receipt:m15",
        owner_user_id=OWNER,
        topology_ref=topology.topology_ref,
    )
    m15_chain = spines.add(M15, topology.topology_ref)
    m15_qro = _qro(
        "qro:m15",
        "ValidationDossier",
        {"topology_ref": topology.topology_ref},
        {
            "desk_topology_receipt_ref": topology_receipt.receipt_ref,
            "status": "desk_topology_current",
        },
        m15_chain.chain_ref,
    )
    m15_command = graph.add(m15_qro, "rgcmd:m15")
    compiler.add(m15_qro, m15_command, "api", "api:goal.desk_topology.current")
    projection = SimpleNamespace(
        projection_ref="rgproj_m15",
        qro_id=m15_qro.qro_id,
        command_id=m15_command.command_id,
        owner=OWNER,
    )
    graph.projections.append(projection)

    stores = SimpleNamespace(
        execution_closures=_ExecutionClosures(m9_receipt),
        intents=_Intents(intent),
        market=_Market(use, matrix),
        backtest=_BacktestEvidence(attribution, monitor),
        methodologies=_Methodologies(methodology, method_binding),
        depths=_Depths(depth, depth_binding),
        assets=_Assets(asset),
        transitions=_Transitions(transition, lifecycle_receipt),
        governance=_Governance(passport, recert, recert_head),
        models=_Models(gate),
        agent_ledger=_AgentLedger(heads),
        workflow_closures=_WorkflowClosures(workflow_receipt),
        rag=_RAG(usage),
        calls=_Calls(terminal),
        bindings=_Bindings(binding),
        onboarding=_Onboarding(routing, pool),
        canonical_spine=_CanonicalSpine(tib, checks),
        topologies=_Topologies(topology_receipt, topology),
    )
    context = PlatformSourceLineagePoliciesM9M15Context(
        research_graph_store=graph,
        compiler_store=compiler,
        spine_chain_registry=spines,
        execution_closure_registry=stores.execution_closures,
        execution_order_intent_registry=stores.intents,
        market_data_registry=stores.market,
        validation_methodology_registry=stores.methodologies,
        validation_depth_registry=stores.depths,
        backtest_evidence_registry=stores.backtest,
        asset_lifecycle_registry=stores.assets,
        lifecycle_transition_registry=stores.transitions,
        model_governance_registry=stores.governance,
        model_registry=stores.models,
        agent_capability_ledger=stores.agent_ledger,
        agent_workflow_closure_registry=stores.workflow_closures,
        rag_index=stores.rag,
        llm_call_record_store=stores.calls,
        llm_use_binding_store=stores.bindings,
        onboarding_registry=stores.onboarding,
        canonical_spine_ledger=stores.canonical_spine,
        desk_topology_registry=stores.topologies,
        llm_service_owner_user_id=SERVICE_OWNER,
    )
    anchors = {
        M9: m9_receipt.receipt_ref,
        M10: monitor.monitor_ref,
        M11: transition.transition_ref,
        M12: gate.gate_id,
        M13: workflow_receipt.receipt_ref,
        M14: f"llm_gateway:{terminal.call_id}",
        M15: topology_receipt.receipt_ref,
    }
    expected_specifics = {
        M9: (m9_receipt.receipt_ref, matrix.matrix_ref),
        M10: (
            m10_qro.qro_id,
            methodology.validation_ref,
            depth.depth_ref,
            attribution.attribution_ref,
            monitor.monitor_ref,
        ),
        M11: (asset.asset_ref, transition.transition_ref),
        M12: (
            passport.passport_id,
            gate.gate_id,
            gate.gate_id,
            recert.recertification_record_id,
        ),
        M13: (
            heads["dag_checkpoint"].source_ref,
            "checkpoint:m13",
            heads["dag_replay"].source_ref,
            heads["dag_fork"].source_ref,
            heads["dag_rollback"].source_ref,
        ),
        M14: (
            f"llm_gateway:{terminal.call_id}",
            routing.routing_policy_id,
            pool.pool_id,
            tib.binding_id,
        ),
        M15: (projection.projection_ref,),
    }
    return SimpleNamespace(
        context=context,
        graph=graph,
        compiler=compiler,
        spines=spines,
        stores=stores,
        anchors=anchors,
        expected_specifics=expected_specifics,
        coverage_ref=coverage_ref,
        business_qros={
            M9: m9_business_qro,
            M10: m10_business_qro,
            M11: m11_business_qro,
            M12: m12_business_qro,
            M13: workflow_business_qro,
            M14: workflow_business_qro,
        },
        business_commands={
            M9: m9_business_command,
            M10: m10_business_command,
            M11: m11_business_command,
            M12: m12_business_command,
            M13: workflow_business_command,
            M14: workflow_business_command,
        },
        binding_commands={
            M9: m9_command,
            M10: m10_command,
            M11: m11_command,
            M12: m12_command,
            M13: workflow_command,
            M14: workflow_command,
        },
        workflow_coverage=workflow_coverage,
    )


def test_builder_reports_exact_missing_dependencies_and_exposes_group_api() -> None:
    empty = PlatformSourceLineagePoliciesM9M15Context()
    unavailable = unavailable_platform_source_lineage_policies_m9_m15(empty)
    resolver = build_platform_source_lineage_policies_m9_m15(empty)

    assert set(unavailable) == {M9, M10, M11, M12, M13, M14, M15}
    assert "missing dependency:compiler_store" in unavailable[M9]
    assert "missing dependency:agent_capability_ledger" in unavailable[M13]
    assert "missing dependency:llm_service_owner_user_id" in unavailable[M14]
    assert resolver.registered_rows == ()
    assert resolver.unavailable_rows == unavailable
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="unavailable"):
        resolver.resolve(owner_user_id=OWNER, m_row=M9, anchor_ref="anchor:m9")


def test_binding_rows_report_missing_current_projection_api_at_build_time() -> None:
    system = _build_system()
    graph_without_projection = SimpleNamespace(
        qro=system.graph.qro,
        commands=system.graph.commands,
    )
    context = replace(
        system.context,
        research_graph_store=graph_without_projection,
    )

    unavailable = unavailable_platform_source_lineage_policies_m9_m15(context)
    resolver = build_platform_source_lineage_policies_m9_m15(context)

    for row in (M9, M10, M11, M12, M13, M14, M15):
        assert unavailable[row] == ("missing dependency:research_graph_store",)
    assert resolver.registered_rows == ()


@pytest.mark.parametrize("row", (M9, M10, M11, M12, M13, M14, M15))
def test_each_row_derives_exact_current_refs_from_only_one_anchor(row: str) -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=system.anchors[row],
    )

    assert resolver.registered_rows == (M9, M10, M11, M12, M13, M14, M15)
    assert resolution.m_row == row
    assert resolution.anchor_ref == system.anchors[row]
    assert tuple(item.ref for item in resolution.specific_refs) == system.expected_specifics[row]
    assert dict(resolution.row_policy_metadata)["policy_version"] == POLICY_VERSION
    assert dict(resolution.row_policy_metadata)["graph_command_ref"].startswith("rgcmd:")
    assert resolution.math_spine_ref.startswith("math:")
    assert (resolution.upstream_business_rag is not None) is (row in {M13, M14})
    if row in BINDING_ENTRYPOINTS:
        metadata = dict(resolution.row_policy_metadata)
        assert resolution.business_entry_source == "api"
        assert resolution.business_entrypoint_ref == BINDING_ENTRYPOINTS[row]
        assert metadata["binding_projection_ref"].startswith("rgproj:")
        assert metadata["business_graph_command_ref"] == (
            system.business_commands[row].command_id
        )
    if row in {M13, M14}:
        metadata = dict(resolution.row_policy_metadata)
        assert resolution.business_entry_source == "api"
        assert (
            resolution.business_entrypoint_ref
            == M13_M14_SPINE_BINDING_ENTRYPOINT_REF
        )
        assert metadata["business_entry_source"] == "agent_shell"
        assert metadata["business_entrypoint_ref"] == AGENT_WORKFLOW_ENTRYPOINT_REF
        assert resolution.upstream_business_rag.document_refs == (
            "rag_document:upstream:m13-m14",
        )


@pytest.mark.parametrize("row", (M9, M10, M11, M12, M13, M14, M15))
def test_semantic_check_binds_coverage_compiler_capability_and_final_rag(row: str) -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=system.anchors[row],
    )
    metadata = dict(resolution.row_policy_metadata)
    coverage = SimpleNamespace(
        recorded_by=OWNER,
        entry_source=resolution.business_entry_source,
        entrypoint_ref=resolution.business_entrypoint_ref,
        qro_refs=(resolution.qro_ref,),
        research_graph_command_refs=(metadata["graph_command_ref"],),
        compiler_ir_refs=(metadata["compiler_ir_ref"],),
        compiler_pass_refs=(metadata["compiler_pass_ref"],),
    )
    if row in {M13, M14}:
        sections = ("§0", "§1", "§6", "§8")
        coverage = GoalEntrypointCoverageRecord(
            coverage_ref=goal_entrypoint_coverage_identity(
                entry_source=resolution.business_entry_source,
                entrypoint_ref=resolution.business_entrypoint_ref,
                goal_sections=sections,
                qro_refs=(resolution.qro_ref,),
                research_graph_command_refs=(metadata["graph_command_ref"],),
                compiler_ir_refs=(metadata["compiler_ir_ref"],),
                compiler_pass_refs=(metadata["compiler_pass_ref"],),
            ),
            entry_source=resolution.business_entry_source,
            entrypoint_ref=resolution.business_entrypoint_ref,
            goal_sections=sections,
            qro_refs=(resolution.qro_ref,),
            research_graph_command_refs=(metadata["graph_command_ref"],),
            compiler_ir_refs=(metadata["compiler_ir_ref"],),
            compiler_pass_refs=(metadata["compiler_pass_ref"],),
            evidence_refs=("evidence:current-binder",),
            validation_refs=("validation:current-binder",),
            permission_refs=("permission:current-binder",),
            replay_refs=("replay:current-binder",),
            recorded_by=OWNER,
        )
    capability = PlatformCapabilityRecord(
        m_row=row,
        qro_ref=resolution.qro_ref,
        research_graph_ref=metadata["graph_command_ref"],
        lifecycle_ref=resolution.lifecycle_ref,
        governance_ref=f"goal_validation_receipt:{row}",
        rag_ref=f"rag:{row}",
        math_spine_ref=resolution.math_spine_ref,
        evidence_refs=(f"evidence:{row}",),
        specific_refs=resolution.specific_refs,
    )
    rag_metadata = {"row_policy": metadata}
    if resolution.upstream_business_rag is not None:
        rag_metadata["upstream_business_rag"] = {
            "usage_ref": resolution.upstream_business_rag.usage_ref,
            "document_refs": list(resolution.upstream_business_rag.document_refs),
            "role": "upstream_business_context",
        }
    rag = SimpleNamespace(
        document_id=capability.rag_ref,
        asset_ref=resolution.primary_rag_asset_ref,
        metadata=rag_metadata,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(resolution.primary_rag_asset_ref,),
        ),
    )

    assert resolver.semantic_violations(
        resolution,
        owner_user_id=OWNER,
        business_coverage=coverage,
        capability_record=capability,
        rag_document=rag,
    ) == ()
    if row in {M13, M14}:
        bad_sections = (*coverage.goal_sections, "§14")
        self_certifying = replace(
            coverage,
            goal_sections=bad_sections,
            coverage_ref=goal_entrypoint_coverage_identity(
                entry_source=coverage.entry_source,
                entrypoint_ref=coverage.entrypoint_ref,
                goal_sections=bad_sections,
                qro_refs=coverage.qro_refs,
                research_graph_command_refs=coverage.research_graph_command_refs,
                compiler_ir_refs=coverage.compiler_ir_refs,
                compiler_pass_refs=coverage.compiler_pass_refs,
            ),
        )
        assert "strict non-§14" in " ".join(
            resolver.semantic_violations(
                resolution,
                owner_user_id=OWNER,
                business_coverage=self_certifying,
                capability_record=capability,
                rag_document=rag,
            )
        )

    recombined = replace(
        capability,
        lifecycle_ref="lifecycle:same-owner-unrelated",
    )
    assert "capability refs" in " ".join(
        resolver.semantic_violations(
            resolution,
            owner_user_id=OWNER,
            business_coverage=coverage,
            capability_record=recombined,
            rag_document=rag,
        )
    )
    if row in BINDING_ENTRYPOINTS:
        wrong_coverage = SimpleNamespace(**vars(coverage))
        wrong_coverage.entrypoint_ref = (
            "api:research_os.platform.spine_bindings.same-owner-unrelated"
        )
        assert f"{row} business coverage owner/entrypoint mismatch" in (
            resolver.semantic_violations(
                resolution,
                owner_user_id=OWNER,
                business_coverage=wrong_coverage,
                capability_record=capability,
                rag_document=rag,
            )
        )


@pytest.mark.parametrize("row", (M9, M10, M11, M12, M13, M14, M15))
def test_cross_owner_and_unknown_anchor_cannot_supply_proof_refs(row: str) -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises((KeyError, PlatformSourceLineagePoliciesM9M15Error)):
        resolver.resolve(
            owner_user_id=OTHER_OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )
    with pytest.raises((KeyError, StopIteration, PlatformSourceLineagePoliciesM9M15Error)):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=f"{system.anchors[row]}:caller-forged",
        )


@pytest.mark.parametrize("row", (M9, M10, M11, M12, M13, M14))
def test_binding_replay_uses_only_current_projection_and_keeps_one_business_head(
    row: str,
) -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    original = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=system.anchors[row],
    )
    original_metadata = dict(original.row_policy_metadata)
    qro = system.graph.qros[original.qro_ref]
    replay = system.graph.add(
        qro,
        f"rgcmd:{row.lower()}:spine-binding:replay",
        evidence_refs=(
            qro.mathematical_refs[0],
            system.business_commands[row].command_id,
        ),
        tool_record_refs=(BINDING_ENTRYPOINTS[row],),
    )
    system.compiler.add(
        qro,
        replay,
        "api",
        BINDING_ENTRYPOINTS[row],
        ref_suffix=f"{row.lower()}-spine-binding-replay",
    )
    replay_projection = _projection(
        qro,
        replay,
        f"rgproj:{row.lower()}:spine-binding:replay",
    )
    system.graph.projections[:] = [
        item for item in system.graph.projections if item.qro_id != qro.qro_id
    ] + [replay_projection]

    current = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=system.anchors[row],
    )
    metadata = dict(current.row_policy_metadata)

    assert current.qro_ref == original.qro_ref
    assert metadata["graph_command_ref"] == replay.command_id
    assert metadata["graph_command_ref"] != original_metadata["graph_command_ref"]
    assert metadata["binding_projection_ref"] == replay_projection.projection_ref
    assert metadata["business_graph_command_ref"] == (
        system.business_commands[row].command_id
    )
    assert metadata["business_graph_command_ref"] == original_metadata[
        "business_graph_command_ref"
    ]


@pytest.mark.parametrize("row", (M13, M14))
def test_workflow_binding_policy_is_order_independent_and_uses_historical_snapshot(
    row: str,
) -> None:
    system = _build_system()
    system.graph.command_rows.reverse()
    system.compiler.ir_rows.reverse()
    system.compiler.pass_rows.reverse()
    # The closure's strict-current resolver would now reject the historical
    # Agent Shell coverage after the same-id binder became current.  The row
    # policy must use the immutable head snapshot instead of re-certifying it.
    system.stores.workflow_closures.current = False
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=system.anchors[row],
    )
    metadata = dict(resolution.row_policy_metadata)

    assert metadata["graph_command_ref"] == system.binding_commands[row].command_id
    assert (
        metadata["business_graph_command_ref"]
        == system.business_commands[row].command_id
    )
    assert metadata["workflow_coverage_ref"] == system.coverage_ref


@pytest.mark.parametrize("row", (M13, M14))
def test_real_resolver_marks_historical_workflow_coverage_stale_but_policy_preserves_it(
    row: str,
) -> None:
    system = _build_system()
    real_resolver = RealRefResolver(
        research_graph_store=system.graph,
        lifecycle_registry=_Unavailable(),
        governance_registry=_Unavailable(),
        rag_index=_Unavailable(),
        spine_chain_registry=system.spines,
        compiler_store=system.compiler,
        owner=OWNER,
    )

    real_violations = real_resolver.entrypoint_linkage_violations(
        system.workflow_coverage
    )
    assert any(
        reason
        == "graph command QRO payload is stale or differs from current store state"
        for _field, _ref, reason in real_violations
    )

    # The historical coverage is not sent back through a current-state gate.
    # Its immutable workflow receipt links it to the exact old Graph/compiler
    # objects, while the platform row follows the current binder projection.
    result = build_platform_source_lineage_policies_m9_m15(
        system.context
    ).resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=system.anchors[row],
    )
    metadata = dict(result.row_policy_metadata)
    assert metadata["business_graph_command_ref"] == (
        system.business_commands[row].command_id
    )
    assert metadata["graph_command_ref"] == system.binding_commands[row].command_id


@pytest.mark.parametrize("row", (M13, M14))
@pytest.mark.parametrize(
    "mutation",
    (
        "actor_source",
        "evidence_refs",
        "tool_record_refs",
        "projection_actor_source",
        "historical_actor_source",
    ),
)
def test_workflow_binding_policy_rejects_inexact_binder_and_snapshot_provenance(
    row: str,
    mutation: str,
) -> None:
    system = _build_system()
    command = system.binding_commands[row]
    projection = next(
        item
        for item in system.graph.projections
        if item.qro_id == system.business_qros[row].qro_id
    )
    if mutation == "actor_source":
        command.actor_source = "agent"
    elif mutation == "evidence_refs":
        command.evidence_refs = tuple(reversed(command.evidence_refs))
    elif mutation == "tool_record_refs":
        command.tool_record_refs = ("api:research_os.platform.spine_bindings.other",)
    elif mutation == "projection_actor_source":
        projection.actor_source = "agent"
    else:
        system.business_commands[row].actor_source = "user_manual"
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )


@pytest.mark.parametrize("row", (M13, M14))
def test_workflow_binding_policy_rejects_recombined_historical_coverage(row: str) -> None:
    system = _build_system()
    snapshot = system.stores.workflow_closures.value.snapshot
    snapshot.entrypoint_coverage.state_hash = "sha256:" + "0" * 64
    snapshot.entrypoint_coverage.component_ref = (
        "goal_entrypoint_coverage:" + "f" * 64
    )
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(
        PlatformSourceLineagePoliciesM9M15Error,
        match="structurally content-bound",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )


@pytest.mark.parametrize("row", (M9, M10, M11, M12, M13, M14))
@pytest.mark.parametrize("history", ("missing", "ambiguous"))
def test_binding_rows_require_exactly_one_historical_business_command(
    row: str,
    history: str,
) -> None:
    system = _build_system()
    business = system.business_commands[row]
    if history == "missing":
        system.graph.command_rows[:] = [
            item for item in system.graph.command_rows if item is not business
        ]
        system.compiler.ir_rows[:] = [
            item
            for item in system.compiler.ir_rows
            if item.graph_command_refs != (business.command_id,)
        ]
        system.compiler.pass_rows[:] = [
            item
            for item in system.compiler.pass_rows
            if item.graph_command_refs != (business.command_id,)
        ]
    else:
        duplicate = SimpleNamespace(
            command_id=f"{business.command_id}:ambiguous",
            command_type="upsert_qro",
            actor=business.actor,
            source=business.source,
            actor_source=business.actor_source,
            payload={"qro": system.business_qros[row]},
            evidence_refs=(),
            tool_record_refs=(),
        )
        system.graph.command_rows.append(duplicate)
        system.compiler.add(
            system.business_qros[row],
            duplicate,
            BUSINESS_SOURCES[row],
            BUSINESS_ENTRYPOINTS[row],
            ref_suffix=f"{row.lower()}-business-ambiguous",
        )
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    expected = (
        "missing or ambiguous"
        if history == "missing" or row not in {M13, M14}
        else "recombines another historical command"
    )
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match=expected):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )


@pytest.mark.parametrize("row", (M9, M10, M11, M12))
def test_binding_rows_reject_wrong_binding_entrypoint(row: str) -> None:
    system = _build_system()
    command_ref = system.binding_commands[row].command_id
    compiler_ir = next(
        item
        for item in system.compiler.ir_rows
        if item.graph_command_refs == (command_ref,)
    )
    compiler_pass = next(
        item
        for item in system.compiler.pass_rows
        if item.graph_command_refs == (command_ref,)
    )
    wrong_refs = tuple(
        "entrypoint:api:research_os.platform.spine_bindings.wrong"
        if str(item).startswith("entrypoint:")
        else item
        for item in compiler_ir.canonical_command_refs
    )
    compiler_ir.canonical_command_refs = wrong_refs
    compiler_pass.canonical_command_refs = wrong_refs
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(
        PlatformSourceLineagePoliciesM9M15Error,
        match="binding compiler entrypoint mismatch",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("projection_math", "projection"),
        ("foreign_binding_actor", "current projection"),
        ("recombined_implementation", "fields other than"),
        ("ambiguous_projection", "ambiguous current projections"),
    ),
)
def test_binding_rows_reject_current_projection_drift_and_recombination(
    mutation: str,
    message: str,
) -> None:
    system = _build_system()
    row = M9
    qro = system.graph.qros["qro:m9"]
    projection = next(
        item for item in system.graph.projections if item.qro_id == qro.qro_id
    )
    if mutation == "projection_math":
        projection.mathematical_refs = ("math:same-owner-unrelated",)
    elif mutation == "foreign_binding_actor":
        system.binding_commands[row].actor = OTHER_OWNER
    elif mutation == "recombined_implementation":
        qro.implementation_hash = "implementation:same-owner-unrelated"
    else:
        duplicate = SimpleNamespace(**vars(projection))
        duplicate.projection_ref = f"{projection.projection_ref}:ambiguous"
        system.graph.projections.append(duplicate)
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match=message):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )


def test_binding_policy_resolution_is_read_only_for_graph_compiler_and_spine() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    def snapshot() -> tuple[tuple[str, ...], ...]:
        return (
            tuple(item.command_id for item in system.graph.command_rows),
            tuple(item.projection_ref for item in system.graph.projections),
            tuple(sorted(system.graph.qros)),
            tuple(item.ir_ref for item in system.compiler.ir_rows),
            tuple(item.pass_ref for item in system.compiler.pass_rows),
            tuple(sorted(system.spines.rows)),
        )

    before = snapshot()
    for row in (M9, M10, M11, M12):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=system.anchors[row],
        )

    assert snapshot() == before


def test_m9_and_m11_reject_missing_or_recombined_qro_ir_math_binding() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    system.graph.qros["qro:m9"].mathematical_refs = ()
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="exact unique"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M9,
            anchor_ref=system.anchors[M9],
        )

    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    ir = next(
        item
        for item in system.compiler.ir_rows
        if item.graph_command_refs
        == (system.binding_commands[M11].command_id,)
    )
    ir.mathematical_spine_chain_refs = ("math:same-owner-unrelated",)
    system.spines.add("same-owner-unrelated", "metadata:unrelated")
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="binding mismatch"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M11,
            anchor_ref=system.anchors[M11],
        )


def test_unrelated_chain_metadata_cannot_rescue_missing_exact_qro_math_ref() -> None:
    system = _build_system()
    system.spines.add(
        "unrelated-broad-metadata",
        system.anchors[M9],
        "order_intent:m9",
        "capability:m9",
    )
    system.graph.qros["qro:m9"].mathematical_refs = ()
    ir = next(
        item
        for item in system.compiler.ir_rows
        if item.graph_command_refs == (system.binding_commands[M9].command_id,)
    )
    ir.mathematical_spine_chain_refs = ()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="exact unique"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M9,
            anchor_ref=system.anchors[M9],
        )


def test_m10_and_m12_reject_stale_current_evidence() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    system.stores.backtest.monitor_current = False
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="Monitor is not current"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M10,
            anchor_ref=system.anchors[M10],
        )

    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    system.stores.governance.head = "model_head:same-owner-stale"
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="stale"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M12,
            anchor_ref=system.anchors[M12],
        )


def test_m12_accepts_only_exact_delegated_reviewer_authority() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row=M12,
        anchor_ref=system.anchors[M12],
    )

    command = system.business_commands[M12]
    binding_command = system.binding_commands[M12]
    compiler_pass = next(
        item
        for item in system.compiler.pass_rows
        if item.graph_command_refs == (command.command_id,)
    )
    assert command.actor == REVIEWER
    assert binding_command.actor == OWNER
    assert compiler_pass.actor == OWNER
    assert resolution.qro_ref == "qro:m12"
    assert resolution.business_entrypoint_ref == M12_SPINE_BINDING_ENTRYPOINT_REF
    assert dict(resolution.row_policy_metadata)["business_graph_command_ref"] == (
        command.command_id
    )
    assert system.stores.models.authority_calls == [
        {
            "gate_id": system.anchors[M12],
            "model_id": MODEL_ID,
            "reviewer_user_id": REVIEWER,
            "grant_id": REVIEWER_GRANT_REF,
            "grant_record_hash": REVIEWER_GRANT_HASH,
            "permission": "approve",
        }
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("command_actor", "actor mismatch"),
        ("grant_hash", "gate evidence mismatch"),
        ("stale_authority", "authority is invalid"),
        ("wrong_grant_owner", "grant does not match"),
        ("ambiguous_command", "ambiguous"),
    ),
)
def test_m12_rejects_recombined_or_stale_delegated_authority(
    mutation: str,
    message: str,
) -> None:
    system = _build_system()
    qro = system.business_qros[M12]
    command = system.business_commands[M12]
    if mutation == "command_actor":
        command.actor = "reviewer:same-owner-unrelated"
    elif mutation == "grant_hash":
        qro.input_contract["delegated_actor_authority_hash"] = (
            "sha256:same-owner-unrelated"
        )
        system.graph.qros["qro:m12"].input_contract[
            "delegated_actor_authority_hash"
        ] = "sha256:same-owner-unrelated"
    elif mutation == "stale_authority":
        system.stores.models.authority_current = False
    elif mutation == "wrong_grant_owner":
        system.stores.models.grant.owner_user_id = OTHER_OWNER
    else:
        duplicate = system.graph.add(
            qro,
            "rgcmd:m12:business:ambiguous",
            actor=REVIEWER,
        )
        system.compiler.add(
            qro,
            duplicate,
            "api",
            "api:models.gates.approve",
            ref_suffix="business-ambiguous",
        )
        system.graph.qros[qro.qro_id] = _bind_qro_math(qro, "math:M12")
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match=message):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M12,
            anchor_ref=system.anchors[M12],
        )


def test_m11_rejects_ambiguous_current_receipt_for_same_transition() -> None:
    system = _build_system()
    original = system.stores.transitions.receipt_rows[0]
    system.stores.transitions.receipt_rows.append(
        SimpleNamespace(
            receipt_ref="lifecycle_closure_receipt:m11:ambiguous",
            owner_user_id=OWNER,
            transition_refs=original.transition_refs,
            current_asset_refs=original.current_asset_refs,
        )
    )
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="exactly one"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M11,
            anchor_ref=system.anchors[M11],
        )


def test_m13_m14_require_exact_workflow_entrypoint_and_upstream_rag() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    snapshot = system.stores.workflow_closures.value.snapshot
    snapshot.entrypoint_coverage.link_map["entrypoint_ref"] = "agent_shell:same-owner-unrelated"
    with pytest.raises(
        PlatformSourceLineagePoliciesM9M15Error,
        match="structurally content-bound",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M13,
            anchor_ref=system.anchors[M13],
        )

    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    system.stores.rag.usage.returned_documents = ()
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="exact unique"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M14,
            anchor_ref=system.anchors[M14],
        )


def test_m13_rejects_stale_dag_head_and_m14_rejects_routing_recombination() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    system.stores.agent_ledger.current = False
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="not current"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M13,
            anchor_ref=system.anchors[M13],
        )

    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    system.stores.bindings.binding.routing_policy_ref = "model_routing_policy:same-owner-other"
    with pytest.raises((KeyError, PlatformSourceLineagePoliciesM9M15Error)):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M14,
            anchor_ref=system.anchors[M14],
        )


def test_m15_rejects_ambiguous_projection_and_stale_topology() -> None:
    system = _build_system()
    system.graph.projections.append(
        SimpleNamespace(
            projection_ref="rgproj_m15_ambiguous",
            qro_id="qro:m15",
            command_id="rgcmd:m15",
            owner=OWNER,
        )
    )
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    with pytest.raises(
        PlatformSourceLineagePoliciesM9M15Error,
        match="ambiguous current projections",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M15,
            anchor_ref=system.anchors[M15],
        )

    system = _build_system()
    system.stores.topologies.current = SimpleNamespace(
        topology_ref="desk_topology:same-owner-stale",
        owner_user_id=OWNER,
    )
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="not current"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M15,
            anchor_ref=system.anchors[M15],
        )


def test_m15_replay_selects_current_projection_command_and_rejects_stale_coverage() -> None:
    system = _build_system()
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)
    stale_resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row=M15,
        anchor_ref=system.anchors[M15],
    )
    stale_metadata = dict(stale_resolution.row_policy_metadata)
    qro = system.graph.qros["qro:m15"]

    replay_command = system.graph.add(
        qro,
        "rgcmd:m15:replay",
    )
    system.compiler.add(
        qro,
        replay_command,
        "api",
        "api:goal.desk_topology.current",
    )
    replay_projection = SimpleNamespace(
        projection_ref="rgproj_m15_replay",
        qro_id=qro.qro_id,
        command_id=replay_command.command_id,
        owner=OWNER,
    )
    system.graph.projections[:] = [replay_projection]

    current = resolver.resolve(
        owner_user_id=OWNER,
        m_row=M15,
        anchor_ref=system.anchors[M15],
    )
    metadata = dict(current.row_policy_metadata)
    assert current.qro_ref == stale_resolution.qro_ref
    assert metadata["graph_command_ref"] == replay_command.command_id
    assert metadata["graph_command_ref"] != stale_metadata["graph_command_ref"]
    assert tuple(item.ref for item in current.specific_refs) == (
        replay_projection.projection_ref,
    )

    stale_coverage = SimpleNamespace(
        recorded_by=OWNER,
        entry_source=current.business_entry_source,
        entrypoint_ref=current.business_entrypoint_ref,
        qro_refs=(current.qro_ref,),
        research_graph_command_refs=(stale_metadata["graph_command_ref"],),
        compiler_ir_refs=(stale_metadata["compiler_ir_ref"],),
        compiler_pass_refs=(stale_metadata["compiler_pass_ref"],),
    )
    capability = PlatformCapabilityRecord(
        m_row=M15,
        qro_ref=current.qro_ref,
        research_graph_ref=metadata["graph_command_ref"],
        lifecycle_ref=current.lifecycle_ref,
        governance_ref="goal_validation_receipt:M15:replay",
        rag_ref="rag:M15:replay",
        math_spine_ref=current.math_spine_ref,
        evidence_refs=("evidence:M15:replay",),
        specific_refs=current.specific_refs,
    )
    rag = SimpleNamespace(
        asset_ref=current.primary_rag_asset_ref,
        metadata={"row_policy": metadata},
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(current.primary_rag_asset_ref,),
        ),
    )
    violations = resolver.semantic_violations(
        current,
        owner_user_id=OWNER,
        business_coverage=stale_coverage,
        capability_record=capability,
        rag_document=rag,
    )
    assert "M15 business coverage research_graph_command_refs mismatch" in violations


def test_duplicate_compiler_pair_is_rejected_as_ambiguous() -> None:
    system = _build_system()
    duplicate = SimpleNamespace(**vars(system.compiler.pass_rows[0]))
    duplicate.pass_ref = "compiler_pass:qro:m9:ambiguous"
    system.compiler.pass_rows.append(duplicate)
    resolver = build_platform_source_lineage_policies_m9_m15(system.context)

    with pytest.raises(PlatformSourceLineagePoliciesM9M15Error, match="exactly one"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=M9,
            anchor_ref=system.anchors[M9],
        )
