from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.lineage.ids import content_hash
from app.research_os.agent_workflow_closure import AGENT_WORKFLOW_ENTRYPOINT_REF
from app.research_os.backtest_evidence import (
    BacktestArtifactState,
    BacktestAttributionRecord,
    BacktestMonitorRecord,
    PersistentBacktestEvidenceRegistry,
)
from app.research_os.platform_coverage import (
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.goal_coverage import goal_entrypoint_coverage_identity
from app.research_os.platform_source_adapters_m9_m15 import (
    PlatformSourceAdaptersM9M15Context,
    ResolvedDAGCapabilitySource,
    build_platform_source_adapters_m9_m15,
    unavailable_platform_source_rows_m9_m15,
)


OWNER = "owner-platform-m9-m15"
OTHER_OWNER = "owner-platform-m9-m15-other"
WORKFLOW = "agentwf_" + "a" * 64
WORKFLOW_GOAL_SECTIONS = ("§0", "§1", "§5", "§7", "§8")
SERVICE_OWNER = "service:llm-gateway"
M15_MATH_REF = "math:M15"
BINDING_ENTRYPOINTS = {
    "M9": "api:research_os.platform.spine_bindings.m9",
    "M10": "api:research_os.platform.spine_bindings.m10",
    "M11": "api:research_os.platform.spine_bindings.m11",
    "M12": "api:research_os.platform.spine_bindings.m12",
    "M13": "api:research_os.platform.spine_bindings.m13_m14",
    "M14": "api:research_os.platform.spine_bindings.m13_m14",
}
BUSINESS_ENTRYPOINTS = {
    "M9": ("api", "api:research_os.execution.order_intents"),
    "M10": ("ide", "ide:strategy.run"),
    "M11": ("api", "api:goal.lifecycle.closure"),
    "M12": ("api", "api:models.gates.approve"),
    "M13": ("agent_shell", AGENT_WORKFLOW_ENTRYPOINT_REF),
    "M14": ("agent_shell", AGENT_WORKFLOW_ENTRYPOINT_REF),
}


def _decision(accepted: bool = True):
    return SimpleNamespace(accepted=accepted, violations=())


def _state_hash(value) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _record(
    row: str,
    specific: dict[str, str],
    *,
    qro_ref: str | None = None,
    graph_ref: str | None = None,
    lifecycle_ref: str | None = None,
) -> PlatformCapabilityRecord:
    return PlatformCapabilityRecord(
        m_row=row,
        qro_ref=qro_ref or f"qro:{row}",
        research_graph_ref=graph_ref or f"rgcmd:{row}",
        lifecycle_ref=lifecycle_ref or f"lifecycle:{row}",
        governance_ref=f"goal_validation_receipt:{row}",
        rag_ref=f"rag:{row}",
        math_spine_ref=f"math:{row}",
        evidence_refs=(f"evidence:{row}",),
        specific_refs=tuple(
            PlatformSpecificRef(key=key, ref=ref) for key, ref in specific.items()
        ),
    )


def _attach_binding_lineage(
    context: PlatformSourceAdaptersM9M15Context,
    record: PlatformCapabilityRecord,
    qro: SimpleNamespace,
    row: str,
) -> PlatformSourceAdaptersM9M15Context:
    qro.mathematical_refs = (record.math_spine_ref,)
    historical_values = dict(vars(qro))
    for field in ("input_contract", "output_contract"):
        value = historical_values.get(field)
        if isinstance(value, dict):
            historical_values[field] = dict(value)
    historical_values["mathematical_refs"] = ()
    business_qro = SimpleNamespace(**historical_values)
    business_source, business_entrypoint = BUSINESS_ENTRYPOINTS[row]
    business_actor = OWNER
    if row == "M12":
        business_actor = qro.input_contract["delegated_actor"]

    current_command = SimpleNamespace(
        command_id=record.research_graph_ref,
        command_type="upsert_qro",
        actor=OWNER,
        source="api",
        actor_source="user_manual",
        payload={"qro": qro},
        evidence_refs=(record.math_spine_ref, f"rgcmd:{row}:business"),
        tool_record_refs=(BINDING_ENTRYPOINTS[row],),
    )
    business_command = SimpleNamespace(
        command_id=f"rgcmd:{row}:business",
        command_type="upsert_qro",
        actor=business_actor,
        source=business_source,
        actor_source="agent" if row in {"M13", "M14"} else "user_manual",
        payload={"qro": business_qro},
        evidence_refs=(),
        tool_record_refs=(),
    )
    projection = SimpleNamespace(
        projection_ref=f"rgproj:{row}:binding",
        qro_id=qro.qro_id,
        command_id=current_command.command_id,
        owner=OWNER,
        actor=OWNER,
        source="api",
        actor_source="user_manual",
        mathematical_refs=(record.math_spine_ref,),
    )

    def compiler_pair(
        kind: str,
        command: SimpleNamespace,
        qro_value: SimpleNamespace,
        source: str,
        entrypoint: str,
    ):
        ir = SimpleNamespace(
            ir_ref=f"compiler_ir:{row}:{kind}",
            owner=OWNER,
            source_qro_refs=(qro_value.qro_id,),
            graph_command_refs=(command.command_id,),
            mathematical_spine_chain_refs=tuple(qro_value.mathematical_refs),
            canonical_command_refs=(f"entrypoint:{entrypoint}",),
        )
        compiler_pass = SimpleNamespace(
            pass_ref=f"compiler_pass:{row}:{kind}",
            actor=OWNER,
            output_ir_ref=ir.ir_ref,
            input_qro_refs=(qro_value.qro_id,),
            graph_command_refs=(command.command_id,),
            status="compiled",
            entry_source=source,
            canonical_command_refs=ir.canonical_command_refs,
        )
        return ir, compiler_pass

    current_ir, current_pass = compiler_pair(
        "binding",
        current_command,
        qro,
        "api",
        BINDING_ENTRYPOINTS[row],
    )
    business_ir, business_pass = compiler_pair(
        "business",
        business_command,
        business_qro,
        business_source,
        business_entrypoint,
    )

    class Graph:
        def __init__(self):
            self.current_qro = qro
            self.business_qro = business_qro
            self.current_command = current_command
            self.business_command = business_command
            self.projection = projection
            self.command_rows = [business_command, current_command]
            self.projection_rows = [projection]

        def qro(self, ref):
            if ref != self.current_qro.qro_id:
                raise KeyError(ref)
            return self.current_qro

        def commands(self):
            return list(self.command_rows)

        def projection_index(self, *, owner):
            return [item for item in self.projection_rows if item.owner == owner]

    class Compiler:
        def __init__(self):
            self.ir_rows = [business_ir, current_ir]
            self.pass_rows = [business_pass, current_pass]

        def irs(self, *, owner):
            return [item for item in self.ir_rows if item.owner == owner]

        def passes(self, *, owner):
            return [item for item in self.pass_rows if item.actor == owner]

        def ir(self, ref, *, owner):
            return next(item for item in self.irs(owner=owner) if item.ir_ref == ref)

        def compiler_pass(self, ref, *, owner):
            return next(
                item for item in self.passes(owner=owner) if item.pass_ref == ref
            )

    metadata = {
        "row": row,
        "graph_command_ref": current_command.command_id,
        "compiler_ir_ref": current_ir.ir_ref,
        "compiler_pass_ref": current_pass.pass_ref,
        "binding_projection_ref": projection.projection_ref,
        "business_graph_command_ref": business_command.command_id,
        "business_compiler_ir_ref": business_ir.ir_ref,
        "business_compiler_pass_ref": business_pass.pass_ref,
        "business_entry_source": business_source,
        "business_entrypoint_ref": business_entrypoint,
    }

    prior_rag = context.rag_index

    class RAG:
        def __init__(self):
            prior_document = getattr(prior_rag, "row_document", None)
            prior_metadata = getattr(prior_document, "metadata", None)
            self.document = SimpleNamespace(
                document_id=record.rag_ref,
                metadata={
                    **(
                        dict(prior_metadata)
                        if isinstance(prior_metadata, dict)
                        else {}
                    ),
                    "row_policy": metadata,
                },
            )

        def __getattr__(self, name):
            if prior_rag is None:
                raise AttributeError(name)
            return getattr(prior_rag, name)

        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if (
                ref != self.document.document_id
                or owner_user_id != OWNER
                or require_current is not True
            ):
                raise KeyError(ref)
            return self.document

    return replace(
        context,
        research_graph_store=Graph(),
        compiler_store=Compiler(),
        rag_index=RAG(),
    )


def _attach_workflow_binding_lineage(
    context: PlatformSourceAdaptersM9M15Context,
    record: PlatformCapabilityRecord,
    qro: SimpleNamespace,
    snapshot: SimpleNamespace,
    row: str,
) -> PlatformSourceAdaptersM9M15Context:
    context = _attach_binding_lineage(context, record, qro, row)
    graph = context.research_graph_store
    compiler = context.compiler_store
    business_command = graph.business_command
    business_qro = graph.business_qro
    business_ir = next(
        item
        for item in compiler.ir_rows
        if item.graph_command_refs == (business_command.command_id,)
    )
    business_pass = next(
        item
        for item in compiler.pass_rows
        if item.graph_command_refs == (business_command.command_id,)
    )

    def component(ref: str, value, status: str = "current"):
        return SimpleNamespace(
            component_ref=ref,
            principal_id=OWNER,
            revision="1",
            state_hash=_state_hash(value),
            status=status,
            link_map={},
        )

    snapshot.qro = component(business_qro.qro_id, business_qro)
    snapshot.graph_command = component(
        business_command.command_id,
        business_command,
    )
    snapshot.compiler_ir = component(business_ir.ir_ref, business_ir)
    snapshot.compiler_pass = component(
        business_pass.pass_ref,
        business_pass,
        "passed",
    )
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source="agent_shell",
        entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
        goal_sections=WORKFLOW_GOAL_SECTIONS,
        qro_refs=(business_qro.qro_id,),
        research_graph_command_refs=(business_command.command_id,),
        compiler_ir_refs=(business_ir.ir_ref,),
        compiler_pass_refs=(business_pass.pass_ref,),
    )
    coverage_links = {
        "entry_source": "agent_shell",
        "entrypoint_ref": AGENT_WORKFLOW_ENTRYPOINT_REF,
        "workflow_id": WORKFLOW,
        "rag_usage_ref": snapshot.rag_usage.component_ref,
        "qro_ref": business_qro.qro_id,
        "graph_command_ref": business_command.command_id,
        "compiler_ir_ref": business_ir.ir_ref,
        "compiler_pass_ref": business_pass.pass_ref,
    }
    snapshot.entrypoint_coverage = SimpleNamespace(
        component_ref=coverage_ref,
        principal_id=OWNER,
        revision="1",
        state_hash=_state_hash({"coverage_ref": coverage_ref}),
        status="current",
        link_map=coverage_links,
    )
    return context


def _row_adapters(adapters, row: str):
    return {
        key: adapter
        for raw_key, adapter in adapters.items()
        if isinstance(raw_key, tuple) and raw_key[0] == row
        for key in (raw_key[1],)
    }


def _specific_ref(record: PlatformCapabilityRecord, key: str) -> str:
    return next(item.ref for item in record.specific_refs if item.key == key)


def _load_values(adapters, row: str, record: PlatformCapabilityRecord, owner: str = OWNER):
    refs = {item.key: item.ref for item in record.specific_refs}
    selected = _row_adapters(adapters, row)
    values = {
        key: adapter.load(refs[key], owner, record)
        for key, adapter in selected.items()
    }
    for key, adapter in selected.items():
        assert adapter.validate_linkage(values[key], owner, record) == ()
    return values


def test_default_builder_keeps_incomplete_rows_fail_closed_with_exact_blockers() -> None:
    context = PlatformSourceAdaptersM9M15Context()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    unavailable = unavailable_platform_source_rows_m9_m15(context)

    assert adapters == {}
    assert validators == {}
    assert set(unavailable) == {"M9", "M10", "M11", "M12", "M13", "M14", "M15"}
    assert "missing dependency:execution_closure_registry" in unavailable["M9"]
    assert "missing dependency:compiler_store" in unavailable["M9"]
    assert "missing dependency:rag_index" in unavailable["M9"]
    assert "missing dependency:backtest_evidence_registry" in unavailable["M10"]
    assert "missing dependency:model_governance_registry" in unavailable["M12"]
    assert "missing dependency:agent_capability_ledger" in unavailable["M13"]
    assert "missing dependency:llm_service_owner_user_id" in unavailable["M14"]


def _lifecycle_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            vars(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _m11_fixture():
    before = SimpleNamespace(
        asset_ref="governed_asset:strategy:v1",
        asset_type="StrategyBook",
        category="production_asset",
        lifecycle_state="validated",
        evidence_refs=("evidence:before",),
    )
    after = SimpleNamespace(
        asset_ref="governed_asset:strategy:v2",
        asset_type="StrategyBook",
        category="production_asset",
        lifecycle_state="approved_runtime",
        evidence_refs=("evidence:after",),
    )
    transition_ref = "lifecycle_transition:strategy:v2"
    transition = SimpleNamespace(
        transition_ref=transition_ref,
        canonical_ref=transition_ref,
        owner_user_id=OWNER,
        logical_asset_ref="strategy:logical",
        before_asset_ref=before.asset_ref,
        after_asset_ref=after.asset_ref,
        from_state=before.lifecycle_state,
        to_state=after.lifecycle_state,
        before_asset_sha256=_lifecycle_hash(before),
        after_asset_sha256=_lifecycle_hash(after),
    )
    receipt = SimpleNamespace(
        receipt_ref="lifecycle_closure_receipt:m11",
        owner_user_id=OWNER,
        transition_refs=(transition_ref,),
        current_asset_refs=(after.asset_ref,),
        current_asset_sha256s=(_lifecycle_hash(after),),
        asset_types=("StrategyBook",),
    )
    qro = SimpleNamespace(
        qro_id="qro:M11",
        qro_type="ValidationDossier",
        owner=OWNER,
        input_contract={
            "entry_source": "api",
            "lifecycle_transition_refs": [transition_ref],
        },
        output_contract={
            "lifecycle_closure_receipt_ref": receipt.receipt_ref,
            "asset_count": 1,
            "asset_types": ["StrategyBook"],
            "status": "lifecycle_closure_current",
        },
        lineage=(receipt.receipt_ref, transition_ref),
        implementation_hash="lifecycle_closure:" + content_hash(vars(receipt)),
    )

    class Assets:
        records = {before.asset_ref: before, after.asset_ref: after}

        def governed_asset(self, ref, *, owner_user_id):
            if owner_user_id != OWNER:
                raise KeyError(ref)
            return self.records[ref]

    class Transitions:
        current = True

        def transition(self, ref, *, owner_user_id):
            if owner_user_id != OWNER or ref != transition_ref:
                raise KeyError(ref)
            return transition

        def receipt(self, ref, *, owner_user_id):
            if owner_user_id != OWNER or ref != receipt.receipt_ref:
                raise KeyError(ref)
            return receipt

        def validate_current(self, ref, *, owner_user_id):
            if owner_user_id != OWNER or ref != receipt.receipt_ref:
                return _decision(False)
            return _decision(self.current)

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    transitions_store = Transitions()
    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        asset_lifecycle_registry=Assets(),
        lifecycle_transition_registry=transitions_store,
    )
    record = _record(
        "M11",
        {
            "governed_asset_ref": after.asset_ref,
            "lifecycle_transition_ref": transition_ref,
        },
        qro_ref=qro.qro_id,
        lifecycle_ref=receipt.receipt_ref,
    )
    context = _attach_binding_lineage(context, record, qro, "M11")
    return context, record, transition, transitions_store


def test_m11_binds_exact_current_transition_asset_receipt_and_qro() -> None:
    context, record, _transition, _store = _m11_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M11", record)

    assert set(_row_adapters(adapters, "M11")) == {
        "governed_asset_ref",
        "lifecycle_transition_ref",
    }
    assert set(validators) == {"M11"}
    assert validators["M11"](record, OWNER, values) == ()


def test_m11_rejects_cross_owner_stale_and_same_owner_asset_recombination() -> None:
    context, record, transition, store = _m11_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M11", record)

    with pytest.raises(KeyError):
        _row_adapters(adapters, "M11")["governed_asset_ref"].load(
            "governed_asset:strategy:v2", OTHER_OWNER, record
        )

    store.current = False
    assert "not current" in " ".join(validators["M11"](record, OWNER, values))
    store.current = True
    transition.after_asset_ref = "governed_asset:strategy:other"
    assert "after asset mismatch" in " ".join(
        validators["M11"](record, OWNER, values)
    )


def _dag_record(kind: str, source_ref: str, mode: str, *, workflow: str = WORKFLOW):
    details = {}
    if kind == "dag_fork":
        details = {"from_task_id": "task-a", "overrides_ref": "overrides:1"}
    elif kind == "dag_rollback":
        details = {"to_task_id": "task-a"}
    payload = {
        "mode": mode,
        "succeeded": True,
        "details": details,
        "nodes": [
            {"task_id": "task-a", "checkpoint_ref": "checkpoint:kernel-node-a"}
        ],
        "node_id_by_task": [
            {"task_id": "task-a", "checkpoint_ref": "checkpoint:kernel-node-a"}
        ],
    }
    return SimpleNamespace(
        record_ref=f"agent_capability:{kind}:{workflow[-6:]}",
        owner_user_id=OWNER,
        workflow_id=workflow,
        capability_kind=kind,
        source_ref=source_ref,
        payload=payload,
    )


def _component(ref: str, kind: str, **extra):
    return SimpleNamespace(
        component_ref=ref,
        link_map={"capability_kind": kind, **extra},
    )


def _m13_fixture():
    run = _dag_record("dag_checkpoint", "dag_run:sha256:" + "1" * 64, "run")
    replay = _dag_record("dag_replay", "replay:sha256:" + "2" * 64, "replay")
    fork = _dag_record("dag_fork", "fork:sha256:" + "3" * 64, "fork")
    rollback = _dag_record("dag_rollback", "rollback:sha256:" + "4" * 64, "rollback")
    heads = {
        value.capability_kind: value for value in (run, replay, fork, rollback)
    }

    class Ledger:
        def __init__(self):
            self.heads = heads
            self.current = True

        def current_head(self, *, owner_user_id, workflow_id, capability_kind):
            if owner_user_id != OWNER or workflow_id != WORKFLOW:
                raise KeyError(capability_kind)
            return self.heads[capability_kind]

        def record(self, ref, *, owner_user_id):
            if owner_user_id != OWNER:
                raise KeyError(ref)
            return next(value for value in self.heads.values() if value.record_ref == ref)

        def validate_current(self, ref, *, owner_user_id):
            return _decision(
                self.current
                and owner_user_id == OWNER
                and any(value.record_ref == ref for value in self.heads.values())
            )

    qro = SimpleNamespace(
        qro_id="qro:M13",
        owner=OWNER,
        mathematical_refs=(),
    )
    snapshot = SimpleNamespace(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        rag_usage=SimpleNamespace(component_ref="rag-usage:m13"),
        qro=SimpleNamespace(component_ref=qro.qro_id),
        graph_command=SimpleNamespace(component_ref="rgcmd:M13"),
        capability_heads=(
            *(
                _component(value.record_ref, value.capability_kind)
                for value in (run, replay, fork, rollback)
            ),
            _component("agent_capability:react", "react", dag_record_ref=run.record_ref),
            _component(
                "agent_capability:replay",
                "replay",
                dag_record_ref=replay.record_ref,
            ),
        ),
    )
    receipt = SimpleNamespace(
        receipt_ref="agent_workflow_closure_receipt:m13",
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        snapshot=snapshot,
    )

    class Closures:
        def __init__(self):
            self.current = True
            self.head = receipt

        def receipt(self, ref, *, owner_user_id):
            if ref != receipt.receipt_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return receipt

        def current_receipt(self, *, owner_user_id, workflow_id):
            if owner_user_id != OWNER or workflow_id != WORKFLOW:
                raise KeyError(workflow_id)
            return self.head

        def validate_current(self, ref, *, owner_user_id):
            return _decision(
                self.current and ref == receipt.receipt_ref and owner_user_id == OWNER
            )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class RAG:
        def __init__(self):
            self.current = True
            self.upstream_document_ref = "rag:business:m13"
            self.usage = SimpleNamespace(
                usage_id="rag-usage:m13",
                owner_user_id=OWNER,
                workflow_ref=WORKFLOW,
                actor="agent",
                returned_documents=(
                    SimpleNamespace(document_id=self.upstream_document_ref),
                ),
            )
            self.row_document = SimpleNamespace(
                document_id="rag:M13",
                metadata={
                    "upstream_business_rag": {
                        "usage_ref": self.usage.usage_id,
                        "document_refs": [self.upstream_document_ref],
                        "role": "upstream_business_context",
                    }
                },
            )

        def strict_usage_for_owner(self, ref, *, owner_user_id):
            if ref != self.usage.usage_id or owner_user_id != OWNER:
                raise KeyError(ref)
            return self.usage

        def validate_current_usage(self, ref, *, owner_user_id):
            return _decision(
                self.current and ref == self.usage.usage_id and owner_user_id == OWNER
            )

        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if (
                ref != self.row_document.document_id
                or owner_user_id != OWNER
                or require_current is not True
            ):
                raise KeyError(ref)
            return self.row_document

    ledger = Ledger()
    closures = Closures()
    rag = RAG()
    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        agent_capability_ledger=ledger,
        agent_workflow_closure_registry=closures,
        rag_index=rag,
    )
    record = _record(
        "M13",
        {
            "dag_run_ref": run.source_ref,
            "checkpoint_ref": "checkpoint:kernel-node-a",
            "replay_ref": replay.source_ref,
            "fork_ref": fork.source_ref,
            "rollback_ref": rollback.source_ref,
        },
        qro_ref=qro.qro_id,
        lifecycle_ref=receipt.receipt_ref,
    )
    context = _attach_workflow_binding_lineage(
        context,
        record,
        qro,
        snapshot,
        "M13",
    )
    return context, record, ledger, closures


def test_m13_uses_current_canonical_dag_heads_and_checkpoint_payload_join() -> None:
    context, record, _ledger, _closures = _m13_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M13", record)

    assert set(_row_adapters(adapters, "M13")) == {
        "dag_run_ref",
        "checkpoint_ref",
        "replay_ref",
        "fork_ref",
        "rollback_ref",
    }
    assert set(validators) == {"M13"}
    assert validators["M13"](record, OWNER, values) == ()


def test_m13_rejects_cross_owner_stale_head_and_same_owner_workflow_recombination() -> None:
    context, record, ledger, closures = _m13_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M13", record)

    with pytest.raises(KeyError):
        _row_adapters(adapters, "M13")["dag_run_ref"].load(
            dict((item.key, item.ref) for item in record.specific_refs)["dag_run_ref"],
            OTHER_OWNER,
            record,
        )

    old_run = values["dag_run_ref"].record
    ledger.heads["dag_checkpoint"] = _dag_record(
        "dag_checkpoint",
        "dag_run:sha256:" + "9" * 64,
        "run",
    )
    assert "not the current head" in " ".join(
        validators["M13"](record, OWNER, values)
    )
    ledger.heads["dag_checkpoint"] = old_run
    values["fork_ref"] = replace(values["fork_ref"], workflow_id="agentwf_" + "b" * 64)
    assert "different owner workflow" in " ".join(
        validators["M13"](record, OWNER, values)
    )
    values["fork_ref"] = replace(values["fork_ref"], workflow_id=WORKFLOW)
    context.rag_index.usage.returned_documents = (
        SimpleNamespace(document_id="rag:same-owner-unrelated"),
    )
    assert "usage/document binding mismatch" in " ".join(
        validators["M13"](record, OWNER, values)
    )
    context.rag_index.usage.returned_documents = (
        SimpleNamespace(document_id=context.rag_index.upstream_document_ref),
    )
    closures.current = False
    assert _row_adapters(adapters, "M13")["replay_ref"].load(
        dict((item.key, item.ref) for item in record.specific_refs)["replay_ref"],
        OWNER,
        record,
    ) == values["replay_ref"]
    closures.head = SimpleNamespace(
        **{
            **vars(closures.head),
            "receipt_ref": "agent_workflow_closure_receipt:m13:other-head",
        }
    )
    with pytest.raises(LookupError, match="not the current"):
        _row_adapters(adapters, "M13")["replay_ref"].load(
            dict((item.key, item.ref) for item in record.specific_refs)["replay_ref"],
            OWNER,
            record,
        )


def _m14_fixture():
    gateway_ref = "llm_gateway:call-m14"
    routing_ref = "model_routing_policy:agent"
    pool_ref = "credential_pool:openai"
    tib_ref = "tib_m14"
    terminal = SimpleNamespace(
        call_id="call-m14",
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        invocation_id="invocation-m14",
        record_kind="terminal",
        status="ok",
        provider="openai",
        model="gpt-5",
        auth_ref="secretref:openai:primary",
        role="researcher",
    )
    use_binding = SimpleNamespace(
        binding_ref="llm_gateway_use_binding:m14",
        owner_user_id=OWNER,
        service_principal_ref=SERVICE_OWNER,
        provider_ref="openai",
        auth_ref=terminal.auth_ref,
        credential_pool_ref=pool_ref,
        routing_policy_ref=routing_ref,
        terminal_call_id=terminal.call_id,
        invocation_id=terminal.invocation_id,
        workflow_id=WORKFLOW,
        terminal_status="ok",
    )
    routing = SimpleNamespace(
        routing_policy_id=routing_ref,
        role_agent="researcher",
        allowed_providers=("openai",),
        allowed_models=("gpt-5",),
        credential_pool_ref=pool_ref,
    )
    pool = SimpleNamespace(
        pool_id=pool_ref,
        provider_id="openai",
        auth_refs=(terminal.auth_ref,),
        revoked_refs=(),
        owner=SERVICE_OWNER,
    )
    tib = SimpleNamespace(
        binding_id=tib_ref,
        consistency_verdict="server_property_check",
        verifier_ref="verifier:canonical_spine_property_v1",
    )
    checks = (
        {
            "binding_id": tib_ref,
            "result": "pass",
            "input_refs": ("code:test",),
            "verifier_ref": "verifier:canonical_spine_property_v1",
        },
    )
    qro = SimpleNamespace(
        qro_id="qro:M14",
        owner=OWNER,
        mathematical_refs=(),
        theory_implementation_binding=tib_ref,
    )
    snapshot = SimpleNamespace(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        rag_usage=SimpleNamespace(component_ref="rag-usage:m14"),
        qro=SimpleNamespace(component_ref=qro.qro_id),
        graph_command=SimpleNamespace(component_ref="rgcmd:M14"),
        terminal_calls=(SimpleNamespace(component_ref=terminal.call_id),),
        llm_use_bindings=(SimpleNamespace(component_ref=use_binding.binding_ref),),
    )
    receipt = SimpleNamespace(
        receipt_ref="agent_workflow_closure_receipt:m14",
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        snapshot=snapshot,
    )

    class Calls:
        def resolve_terminal_record(self, call_id, owner_user_id):
            if call_id != terminal.call_id or owner_user_id != OWNER:
                raise KeyError(call_id)
            return terminal

    class Bindings:
        def __init__(self):
            self.current = True

        def binding_for_terminal(self, call_id, *, owner_user_id):
            if call_id != terminal.call_id or owner_user_id != OWNER:
                raise KeyError(call_id)
            return use_binding

        def validate_current(self, ref, *, owner_user_id):
            return _decision(
                self.current and ref == use_binding.binding_ref and owner_user_id == OWNER
            )

    class Onboarding:
        def routing_policy(self, ref, *, owner_user_id):
            if ref != routing_ref or owner_user_id != SERVICE_OWNER:
                raise KeyError(ref)
            return routing

        def credential_pool(self, ref, *, owner_user_id):
            if ref != pool_ref or owner_user_id != SERVICE_OWNER:
                raise KeyError(ref)
            return pool

    class Spine:
        def binding(self, ref, *, owner):
            if ref != tib_ref or owner != OWNER:
                raise KeyError(ref)
            return tib

        def checks_for(self, ref, *, owner):
            if ref != tib_ref or owner != OWNER:
                raise KeyError(ref)
            return list(checks)

    class SpineChains:
        def __init__(self):
            self.chain = SimpleNamespace(theory_binding_refs=(tib_ref,))

        def verified_chain(self, ref, *, owner):
            if ref != "math:M14" or owner != OWNER:
                raise KeyError(ref)
            return self.chain

    class RAG:
        def __init__(self):
            self.current = True
            self.upstream_document_ref = "rag:business:m14"
            self.usage = SimpleNamespace(
                usage_id="rag-usage:m14",
                owner_user_id=OWNER,
                workflow_ref=WORKFLOW,
                actor="agent",
                returned_documents=(
                    SimpleNamespace(document_id=self.upstream_document_ref),
                ),
            )
            self.row_document = SimpleNamespace(
                document_id="rag:M14",
                metadata={
                    "upstream_business_rag": {
                        "usage_ref": self.usage.usage_id,
                        "document_refs": [self.upstream_document_ref],
                        "role": "upstream_business_context",
                    }
                },
            )

        def strict_usage_for_owner(self, ref, *, owner_user_id):
            if ref != self.usage.usage_id or owner_user_id != OWNER:
                raise KeyError(ref)
            return self.usage

        def validate_current_usage(self, ref, *, owner_user_id):
            return _decision(
                self.current and ref == self.usage.usage_id and owner_user_id == OWNER
            )

        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if (
                ref != self.row_document.document_id
                or owner_user_id != OWNER
                or require_current is not True
            ):
                raise KeyError(ref)
            return self.row_document

    class Closures:
        def __init__(self):
            self.current = True
            self.head = receipt

        def current_receipt(self, *, owner_user_id, workflow_id):
            if owner_user_id != OWNER or workflow_id != WORKFLOW:
                raise KeyError(workflow_id)
            return self.head

        def validate_current(self, ref, *, owner_user_id):
            return _decision(
                self.current and ref == receipt.receipt_ref and owner_user_id == OWNER
            )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    binding_store = Bindings()
    closures = Closures()
    spine_chains = SpineChains()
    rag = RAG()
    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        llm_call_record_store=Calls(),
        llm_use_binding_store=binding_store,
        onboarding_registry=Onboarding(),
        canonical_spine_ledger=Spine(),
        spine_chain_registry=spine_chains,
        agent_workflow_closure_registry=closures,
        rag_index=rag,
        llm_service_owner_user_id=SERVICE_OWNER,
    )
    record = _record(
        "M14",
        {
            "llm_gateway_ref": gateway_ref,
            "model_routing_policy_ref": routing_ref,
            "credential_pool_ref": pool_ref,
            "theory_implementation_binding_ref": tib_ref,
        },
        qro_ref=qro.qro_id,
        lifecycle_ref=receipt.receipt_ref,
    )
    context = _attach_workflow_binding_lineage(
        context,
        record,
        qro,
        snapshot,
        "M14",
    )
    return context, record, use_binding, binding_store, closures


def test_m14_binds_terminal_use_binding_service_routing_pool_and_canonical_tib() -> None:
    context, record, _binding, _store, _closures = _m14_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M14", record)

    assert set(_row_adapters(adapters, "M14")) == {
        "llm_gateway_ref",
        "model_routing_policy_ref",
        "credential_pool_ref",
        "theory_implementation_binding_ref",
    }
    assert set(validators) == {"M14"}
    assert validators["M14"](record, OWNER, values) == ()


def test_m14_rejects_cross_owner_stale_and_same_owner_routing_recombination() -> None:
    context, record, use_binding, binding_store, closures = _m14_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M14", record)

    with pytest.raises(KeyError):
        _row_adapters(adapters, "M14")["llm_gateway_ref"].load(
            "llm_gateway:call-m14", OTHER_OWNER, record
        )
    use_binding.routing_policy_ref = "model_routing_policy:other"
    assert "routing policy mismatch" in " ".join(
        validators["M14"](record, OWNER, values)
    )
    use_binding.routing_policy_ref = "model_routing_policy:agent"
    context.spine_chain_registry.chain.theory_binding_refs = ("tib_same_owner_other",)
    assert "omits the selected" in " ".join(
        validators["M14"](record, OWNER, values)
    )
    context.spine_chain_registry.chain.theory_binding_refs = ("tib_m14",)
    context.rag_index.usage.returned_documents = (
        SimpleNamespace(document_id="rag:same-owner-unrelated"),
    )
    assert "usage/document binding mismatch" in " ".join(
        validators["M14"](record, OWNER, values)
    )
    context.rag_index.usage.returned_documents = (
        SimpleNamespace(document_id=context.rag_index.upstream_document_ref),
    )
    binding_store.current = False
    with pytest.raises(LookupError, match="current identity"):
        _row_adapters(adapters, "M14")["llm_gateway_ref"].load(
            "llm_gateway:call-m14", OWNER, record
        )
    binding_store.current = True
    closures.current = False
    assert validators["M14"](record, OWNER, values) == ()
    closures.head = SimpleNamespace(
        **{
            **vars(closures.head),
            "receipt_ref": "agent_workflow_closure_receipt:m14:other-head",
        }
    )
    assert "common lifecycle ref" in " ".join(
        validators["M14"](record, OWNER, values)
    )


def _m15_fixture():
    receipt = SimpleNamespace(
        receipt_ref="desk_topology_receipt:m15",
        owner_user_id=OWNER,
        topology_ref="desk_topology:m15",
        handoff_refs=("desk_handoff:one", "desk_handoff:two"),
    )
    desks = tuple(
        SimpleNamespace(
            desk=f"desk-{index}",
            typed_canvas_ref=f"typed_canvas:desk-{index}",
            source_of_truth_refs=("research_graph",),
        )
        for index in range(9)
    )
    topology = SimpleNamespace(
        topology_ref=receipt.topology_ref,
        owner_user_id=OWNER,
        revision=1,
        projections=desks,
    )
    qro = SimpleNamespace(
        qro_id="qro:M15",
        qro_type="ValidationDossier",
        owner=OWNER,
        version=1,
        input_contract={
            "entry_source": "api",
            "topology_ref": receipt.topology_ref,
            "handoff_refs": list(receipt.handoff_refs),
        },
        output_contract={
            "desk_topology_receipt_ref": receipt.receipt_ref,
            "status": "desk_topology_current",
            "desk_count": 9,
        },
        lineage=(receipt.receipt_ref, receipt.topology_ref, *receipt.handoff_refs),
        mathematical_refs=(M15_MATH_REF,),
        implementation_hash="desk_topology_closure:" + content_hash(vars(receipt)),
    )
    command = SimpleNamespace(
        command_id="rgcmd:M15",
        actor=OWNER,
        timestamp="2026-07-12T00:00:00Z",
        payload={"qro": qro},
    )
    projection_ref = "rgproj_" + content_hash(
        {
            "qro_id": qro.qro_id,
            "qro_version": qro.version,
            "command_id": command.command_id,
            "command_timestamp": command.timestamp,
        }
    )
    projection = SimpleNamespace(
        projection_ref=projection_ref,
        qro_id=qro.qro_id,
        qro_type=qro.qro_type,
        command_id=command.command_id,
        owner=OWNER,
        actor=OWNER,
        input_contract_keys=tuple(sorted(qro.input_contract)),
        output_contract_keys=tuple(sorted(qro.output_contract)),
        input_contract_hash=content_hash(qro.input_contract),
        output_contract_hash=content_hash(qro.output_contract),
        qro_version=qro.version,
        command_timestamp=command.timestamp,
        lineage=qro.lineage,
        mathematical_refs=qro.mathematical_refs,
    )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

        def commands(self):
            return [command]

        def projection_index(self, *, owner):
            return [projection] if owner == OWNER else []

    class Topologies:
        def __init__(self):
            self.current = topology
            self.accepted = True

        def topology(self, ref, *, owner_user_id):
            if ref != topology.topology_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return topology

        def current_topology(self, *, owner_user_id):
            if owner_user_id != OWNER:
                raise KeyError(owner_user_id)
            return self.current

        def receipt(self, ref, *, owner_user_id):
            if ref != receipt.receipt_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return receipt

        def validate_topology_current(self, value, *, owner_user_id):
            return _decision(self.accepted and value == self.current and owner_user_id == OWNER)

        def validate_current_receipt(self, value, *, owner_user_id):
            return _decision(self.accepted and value == receipt and owner_user_id == OWNER)

    topology_store = Topologies()
    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        desk_topology_registry=topology_store,
    )
    record = _record(
        "M15",
        {"typed_canvas_projection_ref": projection_ref},
        qro_ref=qro.qro_id,
        graph_ref=command.command_id,
        lifecycle_ref=receipt.receipt_ref,
    )
    return context, record, projection, topology_store


def test_m15_binds_current_graph_projection_to_current_nine_desk_topology() -> None:
    context, record, _projection, _topology_store = _m15_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M15", record)

    assert set(_row_adapters(adapters, "M15")) == {"typed_canvas_projection_ref"}
    assert set(validators) == {"M15"}
    assert validators["M15"](record, OWNER, values) == ()


def test_m15_rejects_cross_owner_projection_drift_and_stale_topology() -> None:
    context, record, projection, topology_store = _m15_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M15", record)

    with pytest.raises(LookupError, match="missing or ambiguous"):
        _row_adapters(adapters, "M15")["typed_canvas_projection_ref"].load(
            projection.projection_ref, OTHER_OWNER, record
        )
    projection.output_contract_hash = "drifted"
    assert "output hash mismatch" in " ".join(
        validators["M15"](record, OWNER, values)
    )
    projection.output_contract_hash = content_hash(
        context.research_graph_store.qro("qro:M15").output_contract
    )
    topology_store.current = SimpleNamespace(topology_ref="desk_topology:new")
    assert "not current" in " ".join(validators["M15"](record, OWNER, values))


def test_m15_rejects_same_owner_mathematical_spine_recombination() -> None:
    context, record, projection, _topology_store = _m15_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M15", record)

    context.research_graph_store.qro(record.qro_ref).mathematical_refs = (
        "math:M15:unrelated",
    )
    projection.mathematical_refs = ("math:M15:unrelated",)

    assert "not exactly bound" in " ".join(
        validators["M15"](record, OWNER, values)
    )


def _m9_fixture():
    intent = SimpleNamespace(
        order_intent_ref="order_intent_m9",
        recorded_by=OWNER,
        market_data_use_validation_ref="market_data_use:m9",
        execution_policy_ref="execution_policy:m9",
        risk_policy_ref="risk_policy:m9",
        runtime="testnet",
        asset_class="crypto_perp",
        instrument_ref="instrument:BTCUSDT_PERP",
        side="buy",
        order_type="limit",
        venue_ref="venue:binance_sandbox",
        permission_gate_ref="permission:testnet:m9",
        order_guard_ref="order_guard:m9",
        kill_switch_ref="kill_switch:m9",
        responsibility_boundary_ref="responsibility:m9",
    )
    use_validation = SimpleNamespace(
        validation_ref=intent.market_data_use_validation_ref,
        recorded_by=OWNER,
        use_context="testnet",
        capability_matrix_ref="capability:crypto_perp:testnet",
        instrument_refs=(intent.instrument_ref,),
        accepted=True,
        violation_codes=(),
    )
    matrix = SimpleNamespace(
        matrix_ref=use_validation.capability_matrix_ref,
        asset_class=intent.asset_class,
        testnet=True,
        paper=True,
        live=False,
    )
    receipt_ref = "execution_closure_receipt:" + "9" * 64
    receipt = SimpleNamespace(
        receipt_ref=receipt_ref,
        canonical_receipt_ref=receipt_ref,
        owner_user_id=OWNER,
        order_intent_ref=intent.order_intent_ref,
        snapshot=SimpleNamespace(
            owner_user_id=OWNER,
            runtime=intent.runtime,
            asset_class=intent.asset_class,
            instrument_ref=intent.instrument_ref,
            venue_ref=intent.venue_ref,
            submission_status="accepted",
            reconciliation_status="reconciled",
        ),
    )
    qro = SimpleNamespace(
        qro_id="qro_m9_execution_boundary",
        qro_type="ExecutionPolicy",
        owner=OWNER,
        input_contract={
            "order_intent_ref": intent.order_intent_ref,
            "market_data_use_validation_ref": intent.market_data_use_validation_ref,
            "runtime": intent.runtime,
            "asset_class": intent.asset_class,
            "instrument_ref": intent.instrument_ref,
            "side": intent.side,
            "order_type": intent.order_type,
        },
        output_contract={
            "status": "order_intent_recorded",
            "execution_policy_ref": intent.execution_policy_ref,
            "risk_policy_ref": intent.risk_policy_ref,
            "market_data_use_validation_ref": intent.market_data_use_validation_ref,
            "permission_gate_ref": intent.permission_gate_ref,
            "order_guard_ref": intent.order_guard_ref,
            "kill_switch_ref": intent.kill_switch_ref,
            "responsibility_boundary_ref": intent.responsibility_boundary_ref,
            "place_order_called": False,
        },
    )

    class Closures:
        accepted = True

        def receipt(self, ref, *, owner_user_id):
            if ref != receipt_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return receipt

        def validate_current(self, ref, *, owner_user_id):
            return _decision(
                self.accepted and ref == receipt_ref and owner_user_id == OWNER
            )

    class Intents:
        def intent(self, ref):
            if ref != intent.order_intent_ref:
                raise KeyError(ref)
            return intent

    class MarketData:
        def capability_matrix(self, ref, *, owner_user_id):
            if ref != matrix.matrix_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return matrix

        def use_validation(self, ref, *, owner_user_id):
            if ref != use_validation.validation_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return use_validation

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    closure_store = Closures()
    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        execution_closure_registry=closure_store,
        execution_order_intent_registry=Intents(),
        market_data_registry=MarketData(),
    )
    record = _record(
        "M9",
        {
            "execution_boundary_ref": receipt_ref,
            "market_capability_matrix_ref": matrix.matrix_ref,
        },
        qro_ref=qro.qro_id,
        lifecycle_ref=receipt_ref,
    )
    context = _attach_binding_lineage(context, record, qro, "M9")
    return context, record, intent, use_validation, qro, closure_store


def test_m9_binds_current_execution_closure_market_matrix_and_qro() -> None:
    context, record, _intent, _use, _qro, _closures = _m9_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M9", record)

    assert set(_row_adapters(adapters, "M9")) == {
        "execution_boundary_ref",
        "market_capability_matrix_ref",
    }
    assert set(validators) == {"M9"}
    assert validators["M9"](record, OWNER, values) == ()


def test_m9_rejects_cross_owner_stale_closure_and_matrix_recombination() -> None:
    context, record, _intent, use_validation, qro, closures = _m9_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M9", record)

    with pytest.raises(KeyError):
        _row_adapters(adapters, "M9")["execution_boundary_ref"].load(
            _specific_ref(record, "execution_boundary_ref"),
            OTHER_OWNER,
            record,
        )
    closures.accepted = False
    assert "not current" in " ".join(validators["M9"](record, OWNER, values))
    closures.accepted = True
    use_validation.capability_matrix_ref = "capability:other"
    assert "Matrix/use-validation mismatch" in " ".join(
        validators["M9"](record, OWNER, values)
    )
    use_validation.capability_matrix_ref = "capability:crypto_perp:testnet"
    qro.input_contract["instrument_ref"] = "instrument:ETHUSDT_PERP"
    assert "instrument_ref mismatch" in " ".join(
        validators["M9"](record, OWNER, values)
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("capability_graph", "capability Graph ref"),
        ("projection_command", "projection linkage mismatch"),
        ("current_ir_math", "current binding compiler lineage mismatch"),
        ("current_entrypoint", "current binding compiler lineage mismatch"),
        ("business_entrypoint_metadata", "business command metadata mismatch"),
        ("business_ir_recombined", "binding and historical business refs"),
        ("business_owner", "historical business QRO is stale or recombined"),
        ("business_contract", "historical business QRO is stale or recombined"),
        ("business_command_ambiguous", "business Graph head is missing or ambiguous"),
        ("current_compiler_ambiguous", "compiler lineage is missing or ambiguous"),
    ),
)
def test_m9_rejects_recombined_current_binding_and_historical_business_metadata(
    mutation: str,
    expected: str,
) -> None:
    context, record, _intent, _use, _qro, _closures = _m9_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M9", record)
    graph = context.research_graph_store
    compiler = context.compiler_store
    metadata = context.rag_index.document.metadata["row_policy"]
    current_ir = next(
        item for item in compiler.ir_rows if item.ir_ref == metadata["compiler_ir_ref"]
    )
    current_pass = next(
        item
        for item in compiler.pass_rows
        if item.pass_ref == metadata["compiler_pass_ref"]
    )

    if mutation == "capability_graph":
        record = replace(
            record,
            research_graph_ref=graph.business_command.command_id,
        )
    elif mutation == "projection_command":
        graph.projection.command_id = graph.business_command.command_id
    elif mutation == "current_ir_math":
        current_ir.mathematical_spine_chain_refs = ("math:M9:unrelated",)
    elif mutation == "current_entrypoint":
        refs = ("entrypoint:api:research_os.platform.spine_bindings.wrong",)
        current_ir.canonical_command_refs = refs
        current_pass.canonical_command_refs = refs
    elif mutation == "business_entrypoint_metadata":
        metadata["business_entrypoint_ref"] = "api:same-owner-unrelated"
    elif mutation == "business_ir_recombined":
        metadata["business_compiler_ir_ref"] = metadata["compiler_ir_ref"]
    elif mutation == "business_owner":
        graph.business_qro.owner = OTHER_OWNER
    elif mutation == "business_contract":
        graph.business_qro.output_contract["status"] = "same-owner-unrelated"
    elif mutation == "business_command_ambiguous":
        duplicate = SimpleNamespace(**vars(graph.business_command))
        duplicate.command_id = f"{graph.business_command.command_id}:ambiguous"
        graph.command_rows.append(duplicate)
    else:
        duplicate = SimpleNamespace(**vars(current_pass))
        duplicate.pass_ref = f"{current_pass.pass_ref}:ambiguous"
        compiler.pass_rows.append(duplicate)

    assert expected in " ".join(validators["M9"](record, OWNER, values))


def test_m9_binding_adapter_validation_does_not_write_lineage_stores() -> None:
    context, record, _intent, _use, _qro, _closures = _m9_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M9", record)

    def snapshot() -> tuple[str, str, str]:
        return (
            repr(
                (
                    context.research_graph_store.command_rows,
                    context.research_graph_store.projection_rows,
                    context.research_graph_store.current_qro,
                    context.research_graph_store.business_qro,
                )
            ),
            repr(
                (
                    context.compiler_store.ir_rows,
                    context.compiler_store.pass_rows,
                )
            ),
            repr(context.rag_index.document),
        )

    before = snapshot()
    assert validators["M9"](record, OWNER, values) == ()
    assert snapshot() == before


def _m10_fixture(tmp_path):
    source_run_ref = "ide_run:m10-run"
    qro = SimpleNamespace(
        qro_id="qro_backtest_m10",
        qro_type="BacktestRun",
        owner=OWNER,
        output_contract={"run_id": "m10-run", "status": "succeeded"},
    )
    methodology = SimpleNamespace(
        validation_ref="validation_methodology:m10",
        cost_model_refs=("cost_model:fees",),
    )
    depth = SimpleNamespace(
        depth_ref="validation_depth:m10",
        cost_model_refs=("cost_model:slippage",),
    )
    methodology_binding = SimpleNamespace(
        owner_user_id=OWNER,
        recorded_by="researcher",
        source_run_ref=source_run_ref,
        backtest_run_ref=qro.qro_id,
    )
    depth_binding = SimpleNamespace(
        owner_user_id=OWNER,
        recorded_by="researcher",
        source_run_ref=source_run_ref,
        backtest_run_ref=qro.qro_id,
    )
    artifact_holder = {
        "state": BacktestArtifactState(
            artifact_sha256="sha256:" + "a" * 64,
            row_count=4,
            component_refs=("component:brinson", "component:cost"),
        )
    }

    def resolve_artifact(owner, backtest, source, path):
        if (
            owner != OWNER
            or backtest != qro.qro_id
            or source != source_run_ref
            or path != "attribution.csv"
        ):
            raise KeyError((owner, backtest, source, path))
        return artifact_holder["state"]

    evidence = PersistentBacktestEvidenceRegistry(
        tmp_path / "m10_backtest_evidence.jsonl",
        artifact_resolver=resolve_artifact,
    )
    state = artifact_holder["state"]
    attribution = evidence.record_attribution(
        BacktestAttributionRecord(
            owner_user_id=OWNER,
            recorded_by=OWNER,
            backtest_run_ref=qro.qro_id,
            source_run_ref=source_run_ref,
            validation_methodology_ref=methodology.validation_ref,
            validation_depth_ref=depth.depth_ref,
            artifact_path="attribution.csv",
            artifact_sha256=state.artifact_sha256,
            row_count=state.row_count,
            component_refs=state.component_refs,
            cost_model_refs=("cost_model:fees", "cost_model:slippage"),
        )
    )
    triggers = ("consistency_check:drawdown", "math_trigger:cost_drift")
    monitor = evidence.record_monitor(
        BacktestMonitorRecord(
            owner_user_id=OWNER,
            recorded_by=OWNER,
            backtest_run_ref=qro.qro_id,
            attribution_ref=attribution.attribution_ref,
            monitoring_profile_ref="monitoring_profile:m10",
            performance_primary_alert_ref="performance_alert:drawdown",
            cost_drift_ref="cost_drift:shortfall",
            drift_root_cause_ref="drift_root_cause:fees",
            mathematical_trigger_refs=triggers,
            evidence_refs=(
                attribution.attribution_ref,
                "monitoring_profile:m10",
                "performance_alert:drawdown",
                "cost_drift:shortfall",
                "drift_root_cause:fees",
                *triggers,
            ),
        )
    )
    chain = SimpleNamespace(
        chain_ref="math:M10",
        recorded_by=OWNER,
        backtest_run_ref=qro.qro_id,
        attribution_ref=attribution.attribution_ref,
        monitor_ref=monitor.monitor_ref,
        theory_binding_refs=("theory_binding:m10",),
        consistency_check_refs=triggers,
        evidence_refs=(attribution.attribution_ref, monitor.monitor_ref),
        validation_refs=(methodology.validation_ref, depth.depth_ref),
    )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class Methodologies:
        def methodology(self, ref, *, owner_user_id):
            if ref != methodology.validation_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return methodology

        def methodology_binding(self, ref, *, owner_user_id):
            if ref != methodology.validation_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return methodology_binding

    class Depths:
        def depth(self, ref, *, owner_user_id):
            if ref != depth.depth_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return depth

        def depth_binding(self, ref, *, owner_user_id):
            if ref != depth.depth_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return depth_binding

    class Chains:
        def verified_chain(self, ref, *, owner):
            if ref != chain.chain_ref or owner != OWNER:
                raise KeyError(ref)
            return chain

    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        validation_methodology_registry=Methodologies(),
        validation_depth_registry=Depths(),
        backtest_evidence_registry=evidence,
        spine_chain_registry=Chains(),
    )
    record = _record(
        "M10",
        {
            "backtest_run_ref": qro.qro_id,
            "validation_methodology_ref": methodology.validation_ref,
            "validation_depth_ref": depth.depth_ref,
            "attribution_ref": attribution.attribution_ref,
            "monitor_ref": monitor.monitor_ref,
        },
        qro_ref=qro.qro_id,
        lifecycle_ref=monitor.monitor_ref,
    )
    context = _attach_binding_lineage(context, record, qro, "M10")
    return context, record, artifact_holder, methodology_binding, chain


def test_m10_binds_backtest_methodology_depth_attribution_monitor_and_spine(
    tmp_path,
) -> None:
    context, record, _artifact, _binding, _chain = _m10_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M10", record)

    assert set(_row_adapters(adapters, "M10")) == {
        "backtest_run_ref",
        "validation_methodology_ref",
        "validation_depth_ref",
        "attribution_ref",
        "monitor_ref",
    }
    assert set(validators) == {"M10"}
    assert validators["M10"](record, OWNER, values) == ()
    qro = context.research_graph_store.qro(record.qro_ref)
    qro.output_contract = {
        "source_run_id": "m10-run",
        "promoted_run_id": "formal-run-m10",
        "status": "completed",
    }
    context.research_graph_store.business_qro.output_contract = dict(
        qro.output_contract
    )
    assert validators["M10"](record, OWNER, values) == ()


def test_m10_rejects_cross_owner_artifact_drift_and_lineage_recombination(
    tmp_path,
) -> None:
    context, record, artifact_holder, methodology_binding, chain = _m10_fixture(
        tmp_path
    )
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M10", record)

    with pytest.raises(LookupError):
        _row_adapters(adapters, "M10")["attribution_ref"].load(
            _specific_ref(record, "attribution_ref"),
            OTHER_OWNER,
            record,
        )
    artifact_holder["state"] = BacktestArtifactState(
        artifact_sha256="sha256:" + "b" * 64,
        row_count=5,
        component_refs=("component:brinson", "component:cost"),
    )
    stale = " ".join(validators["M10"](record, OWNER, values))
    assert "Attribution is not current" in stale
    assert "Monitor is not current" in stale
    artifact_holder["state"] = BacktestArtifactState(
        artifact_sha256="sha256:" + "a" * 64,
        row_count=4,
        component_refs=("component:brinson", "component:cost"),
    )
    methodology_binding.backtest_run_ref = "qro_backtest_other"
    assert "ValidationMethodology/BacktestRun mismatch" in " ".join(
        validators["M10"](record, OWNER, values)
    )
    methodology_binding.backtest_run_ref = "qro_backtest_m10"
    chain.consistency_check_refs = ()
    assert "mathematical triggers are not spine-bound" in " ".join(
        validators["M10"](record, OWNER, values)
    )


def test_m10_rejects_same_owner_unrelated_lifecycle_monitor(tmp_path) -> None:
    context, record, _artifact, _binding, _chain = _m10_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M10", record)

    recombined = replace(record, lifecycle_ref="monitor:same-owner-unrelated")

    assert "common lifecycle ref is not the current Monitor" in " ".join(
        validators["M10"](recombined, OWNER, values)
    )


def _m12_fixture():
    passport_ref = "model_passport_" + "1" * 64
    recert_ref = "model_recertification_" + "2" * 64
    model_version_ref = "model_version:ridge:v2"
    head_hash = "model_governance_head_" + "3" * 64
    reviewer_grant_ref = "reviewer_grant:m12"
    reviewer_grant_hash = "sha256:" + "4" * 64
    passport = SimpleNamespace(
        passport_id=passport_ref,
        owner_user_id=OWNER,
        recorded_by="training-service",
        model_version_ref=model_version_ref,
        recertification_records=(recert_ref,),
    )
    recertification = SimpleNamespace(
        recertification_record_id=recert_ref,
        owner_user_id=OWNER,
        recorded_by="independent-reviewer",
        model_passport_ref=passport_ref,
        model_version_ref=model_version_ref,
        decision="accepted",
    )
    gate = SimpleNamespace(
        gate_id="gate-m12-model-promotion",
        model_id="model_asset:owner-platform-m9-m15:ridge",
        version=2,
        from_stage="dev",
        to_stage="staging",
        action_kind="promote_staging",
        created_by="model-owner",
        approver="independent-reviewer",
        decision="approved",
        side_effect_executed=True,
        side_effect_ref=f"stage:{OWNER}:ridge:v2:staging",
        evidence={
            "owner_user_id": OWNER,
            "logical_model_id": "ridge",
            "model_passport_ref": passport_ref,
            "model_recertification_record_refs": [recert_ref],
            "model_recertification_record_head_hashes": {recert_ref: head_hash},
            "reviewer_user_id": "independent-reviewer",
            "reviewer_grant_id": reviewer_grant_ref,
            "reviewer_grant_record_hash": reviewer_grant_hash,
        },
    )
    qro = SimpleNamespace(
        qro_id="qro_model_promotion_m12",
        qro_type="Model",
        owner=OWNER,
        approval=gate.gate_id,
        input_contract={
            "gate_id": gate.gate_id,
            "model": "ridge",
            "model_version": 2,
            "model_version_ref": model_version_ref,
            "delegated_actor": "independent-reviewer",
            "delegated_actor_authority_ref": reviewer_grant_ref,
            "delegated_actor_authority_hash": reviewer_grant_hash,
        },
        output_contract={
            "status": "promotion_gate_approved",
            "gate_id": gate.gate_id,
            "decision": "approved",
            "model_passport_ref": passport_ref,
            "side_effect_ref": gate.side_effect_ref,
            "approved_by": "independent-reviewer",
        },
    )
    chain = SimpleNamespace(
        chain_ref="math:M12",
        recorded_by=OWNER,
        model_ref=model_version_ref,
        evidence_refs=(passport_ref, recert_ref, gate.gate_id),
        validation_refs=("validation_dossier:m12",),
        theory_binding_refs=("theory_binding:model:m12",),
    )

    class Governance:
        head = head_hash

        def passport(self, ref, *, owner_user_id):
            if ref != passport_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return passport

        def recertification_record(self, ref, *, owner_user_id):
            if ref != recert_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return recertification

        def current_head_hash(self, ref, *, owner_user_id, event_type=None):
            if (
                ref != recert_ref
                or owner_user_id != OWNER
                or event_type != "model_recertification_recorded"
            ):
                raise KeyError(ref)
            return self.head

    class Models:
        def promotion_gate(self, ref, *, owner_user_id):
            if ref != gate.gate_id or owner_user_id != OWNER:
                raise KeyError(ref)
            return gate

        def promotion_reviewer_authority_evidence(
            self,
            ref,
            *,
            model_id,
            reviewer_user_id,
            grant_id,
            grant_record_hash,
            permission,
        ):
            if (
                ref != gate.gate_id
                or model_id != "ridge"
                or reviewer_user_id != "independent-reviewer"
                or grant_id != reviewer_grant_ref
                or grant_record_hash != reviewer_grant_hash
                or permission != "approve"
            ):
                raise KeyError(ref)
            return SimpleNamespace(
                grant_id=reviewer_grant_ref,
                gate_id=gate.gate_id,
                owner_user_id=OWNER,
                model_id="ridge",
                model_asset_ref=gate.model_id,
                model_version=gate.version,
                reviewer_user_id="independent-reviewer",
                permissions=("approve",),
            )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class Chains:
        def verified_chain(self, ref, *, owner):
            if ref != chain.chain_ref or owner != OWNER:
                raise KeyError(ref)
            return chain

    governance = Governance()
    context = PlatformSourceAdaptersM9M15Context(
        research_graph_store=Graph(),
        model_governance_registry=governance,
        model_registry=Models(),
        spine_chain_registry=Chains(),
    )
    record = _record(
        "M12",
        {
            "model_passport_ref": passport_ref,
            "model_promotion_ref": gate.gate_id,
            "approval_ref": gate.gate_id,
            "recertification_ref": recert_ref,
        },
        qro_ref=qro.qro_id,
        lifecycle_ref=gate.side_effect_ref,
    )
    context = _attach_binding_lineage(context, record, qro, "M12")
    return context, record, passport, recertification, gate, qro, governance


def test_m12_binds_passport_approved_promotion_recertification_and_spine() -> None:
    context, record, _passport, _recert, _gate, _qro, _governance = _m12_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M12", record)

    assert set(_row_adapters(adapters, "M12")) == {
        "model_passport_ref",
        "model_promotion_ref",
        "approval_ref",
        "recertification_ref",
    }
    assert set(validators) == {"M12"}
    assert validators["M12"](record, OWNER, values) == ()


@pytest.mark.parametrize("row", ("M9", "M10", "M11", "M12", "M13", "M14"))
@pytest.mark.parametrize("mutation", ("actor_source", "evidence_refs", "tool_record_refs"))
def test_binding_adapters_reject_inexact_server_binder_provenance(
    row: str,
    mutation: str,
    tmp_path,
) -> None:
    if row == "M9":
        context, record, *_ = _m9_fixture()
    elif row == "M10":
        context, record, *_ = _m10_fixture(tmp_path / f"m10-{mutation}")
    elif row == "M11":
        context, record, *_ = _m11_fixture()
    elif row == "M12":
        context, record, *_ = _m12_fixture()
    elif row == "M13":
        context, record, *_ = _m13_fixture()
    else:
        context, record, *_ = _m14_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, row, record)
    command = context.research_graph_store.current_command
    if mutation == "actor_source":
        command.actor_source = "agent"
    elif mutation == "evidence_refs":
        command.evidence_refs = tuple(reversed(command.evidence_refs))
    else:
        command.tool_record_refs = ("api:research_os.platform.spine_bindings.other",)

    assert "current binding command provenance mismatch" in " ".join(
        validators[row](record, OWNER, values)
    )


@pytest.mark.parametrize("row", ("M13", "M14"))
def test_workflow_binding_adapters_are_order_independent_and_reject_ambiguity(
    row: str,
) -> None:
    if row == "M13":
        context, record, *_ = _m13_fixture()
    else:
        context, record, *_ = _m14_fixture()
    graph = context.research_graph_store
    compiler = context.compiler_store
    graph.command_rows.reverse()
    compiler.ir_rows.reverse()
    compiler.pass_rows.reverse()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, row, record)

    assert validators[row](record, OWNER, values) == ()
    duplicate = SimpleNamespace(
        **{
            **vars(graph.business_command),
            "command_id": graph.business_command.command_id + ":ambiguous",
        }
    )
    graph.command_rows.append(duplicate)
    assert "missing or ambiguous" in " ".join(
        validators[row](record, OWNER, values)
    )


def test_m12_rejects_cross_owner_self_approval_stale_head_and_gate_recombination() -> None:
    context, record, _passport, _recert, gate, _qro, governance = _m12_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M12", record)

    with pytest.raises(KeyError):
        _row_adapters(adapters, "M12")["model_passport_ref"].load(
            _specific_ref(record, "model_passport_ref"),
            OTHER_OWNER,
            record,
        )
    gate.approver = gate.created_by
    assert "creator/approver independence" in " ".join(
        validators["M12"](record, OWNER, values)
    )
    gate.approver = "independent-reviewer"
    governance.head = "model_governance_head_" + "4" * 64
    assert "head is stale" in " ".join(validators["M12"](record, OWNER, values))
    governance.head = "model_governance_head_" + "3" * 64
    other_gate = SimpleNamespace(**{**vars(gate), "gate_id": "gate-other"})
    recombined = {
        **values,
        "approval_ref": replace(values["approval_ref"], gate=other_gate),
    }
    assert "not the same durable gate" in " ".join(
        validators["M12"](record, OWNER, recombined)
    )


def test_m12_rejects_recombined_delegated_reviewer_authority() -> None:
    context, record, _passport, _recert, _gate, qro, _governance = _m12_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M12", record)
    qro.input_contract["delegated_actor_authority_hash"] = "sha256:" + "9" * 64

    assert "delegated reviewer authority" in " ".join(
        validators["M12"](record, OWNER, values)
    )


def test_m12_keeps_historical_reviewer_command_separate_from_owner_binding() -> None:
    context, record, _passport, _recert, gate, _qro, _governance = _m12_fixture()
    adapters, validators = build_platform_source_adapters_m9_m15(context)
    values = _load_values(adapters, "M12", record)
    graph = context.research_graph_store

    assert graph.current_command.actor == OWNER
    assert graph.business_command.actor == gate.approver
    assert validators["M12"](record, OWNER, values) == ()

    graph.business_command.actor = OWNER
    assert "historical business command metadata mismatch" in " ".join(
        validators["M12"](record, OWNER, values)
    )
    graph.business_command.actor = gate.approver
    graph.current_command.actor = gate.approver
    assert "current binding QRO/Graph/math linkage mismatch" in " ".join(
        validators["M12"](record, OWNER, values)
    )
