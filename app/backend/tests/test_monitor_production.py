from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.dag.engine import run_dag
from app.execution import ExecutionAuditLog
from app.factor_factory.lifecycle import LifecycleManager, LifecycleThresholds
from app.factor_factory.registry import FactorRegistry
from app.monitor.production import (
    build_weekly_monitor_dag,
    build_weekly_monitor_scheduler,
    configure_monitor_runtime,
)
from app.research_os import (
    PersistentCompilerIRStore,
    PersistentExecutionReconciliationActionRegistry,
    PersistentExecutionReconciliationRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    ResearchGraphStore,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver


def _install_goal_proof_stores(tmp_path, monkeypatch, graph):  # noqa: ANN001
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler_store = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validation_store = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence_store = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler_store,
        validation_receipt_registry=validation_store,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler_store,
            goal_validation_receipt_registry=validation_store,
            platform_source_evidence_registry=evidence_store,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler_store)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validation_store)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence_store)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    return compiler_store, coverage_store


@pytest.fixture
def monitor_env(tmp_path, monkeypatch):
    registry = FactorRegistry(tmp_path / "factors.json")
    manager = LifecycleManager(registry, thresholds=LifecycleThresholds(warning_persist_weeks=2))
    audit_log = ExecutionAuditLog()
    graph = ResearchGraphStore()
    compiler_store, coverage_store = _install_goal_proof_stores(
        tmp_path, monkeypatch, graph
    )
    reconciliations = PersistentExecutionReconciliationRegistry(tmp_path / "execution_reconciliations.jsonl")
    reconciliation_actions = PersistentExecutionReconciliationActionRegistry(tmp_path / "execution_reconciliation_actions.jsonl")
    monkeypatch.setattr(main, "FACTOR_REGISTRY", registry)
    monkeypatch.setattr(main, "FACTOR_LIFECYCLE", manager)
    monkeypatch.setattr(main, "EXECUTION_AUDIT_LOG", audit_log)
    monkeypatch.setattr(main, "EXECUTION_RECONCILIATIONS", reconciliations)
    monkeypatch.setattr(main, "EXECUTION_RECONCILIATION_ACTIONS", reconciliation_actions)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester", username="tester"
    )
    try:
        yield TestClient(main.app), registry, manager, audit_log
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def _high_cost_fill(audit_log: ExecutionAuditLog, *, timestamp: str | None = None) -> None:
    audit_log.log(
        "fill",
        {
            "symbol": "BTCUSDT",
            "filled_qty": 1,
            "fill_price": 30000,
            "commission": 1000,
            "timestamp": timestamp or datetime(2024, 5, 1, tzinfo=UTC).isoformat(),
        },
    )


def test_weekly_monitor_endpoint_retires_warning_factor_from_cost_drift(monitor_env) -> None:
    client, registry, manager, audit_log = monitor_env
    factor = registry.register("cost_sensitive_alpha", "close")
    registry.update_state(factor.factor_id, factor.version, "WARNING")
    _high_cost_fill(audit_log)

    first = client.post("/api/monitor/weekly_tick", json={"week": "2024-05-01"})
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["n_fills"] == 1
    assert first_body["actions"][0]["drift_breach"] is True
    assert first_body["lifecycle_events"] == []
    assert registry.get(factor.factor_id).lifecycle_state == "WARNING"

    second = client.post("/api/monitor/weekly_tick", json={"week": "2024-05-01"})
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["lifecycle_events"][0]["to_state"] == "RETIRED"
    assert registry.get(factor.factor_id).lifecycle_state == "RETIRED"
    assert len(manager.events(factor.factor_id)) == 1


def test_weekly_monitor_endpoint_records_factor_observation(monitor_env) -> None:
    client, registry, manager, _audit_log = monitor_env
    factor = registry.register("ic_alpha", "close")
    registry.update_state(factor.factor_id, factor.version, "QUALIFIED")

    response = client.post(
        "/api/monitor/weekly_tick",
        json={
            "week": "2024-05-01",
            "factor_observations": [
                {
                    "factor_id": factor.factor_id,
                    "version": factor.version,
                    "horizon": 5,
                    "ic_mean": 0.04,
                    "ic_ir": 0.7,
                    "rank_ic_mean": 0.035,
                    "sample_t": 3.5,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["factors_checked"] == 1
    assert body["actions"][0]["drift_breach"] is False
    history = manager.history(factor.factor_id, factor.version)
    assert len(history) == 1
    assert history[0].ic_mean == pytest.approx(0.04)


def test_weekly_monitor_endpoint_records_scheduler_qro_without_payload_leakage(monitor_env) -> None:
    client, registry, _manager, audit_log = monitor_env
    factor = registry.register("monitor_secret_alpha", "close")
    registry.update_state(factor.factor_id, factor.version, "WARNING")
    _high_cost_fill(audit_log)
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    response = client.post("/api/monitor/weekly_tick", json={"week": "2024-05-01"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["qro_id"]
    assert body["research_graph_command_id"]
    assert body["compiler_ir_ref"]
    assert body["compiler_pass_ref"]
    assert body["entrypoint_coverage_ref"]
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before + 1
    qro = main.RESEARCH_GRAPH_STORE.qro(body["qro_id"])
    assert qro.qro_type == "Observable" or getattr(qro.qro_type, "value", None) == "Observable"
    assert qro.input_contract["entry_source"] == "scheduler"
    assert qro.input_contract["trigger"] == "manual_api"
    assert qro.output_contract["result_hash"] == body["research_graph_result_hash"]
    assert qro.output_contract["n_fills"] == 1
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert ir.permission_ref == "monitor.weekly_tick:user_manual"
    assert len(ir.validation_refs) == 1
    [validation_ref] = ir.validation_refs
    assert validation_ref.startswith("goal_validation_receipt:")
    receipt = main.GOAL_VALIDATION_RECEIPT_REGISTRY.receipt(
        validation_ref,
        owner_user_id="tester",
    )
    assert receipt.subject_qro_refs == (body["qro_id"],)
    assert receipt.graph_command_refs == (body["research_graph_command_id"],)
    assert receipt.outcome == "passed"
    assert compiler_pass.entry_source == "scheduler"
    assert compiler_pass.actor_source == "user_manual"
    assert compiler_pass.permission_ref == "monitor.weekly_tick:user_manual"
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert coverage.entry_source == "scheduler"
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.research_graph_command_refs == (body["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    qro_contract_text = str(qro.input_contract) + str(qro.output_contract)
    assert "monitor_secret_alpha" not in qro_contract_text
    assert "cost_drift_report" not in qro_contract_text
    assert "actions" not in qro_contract_text
    compiled_text = str(ir.__dict__) + str(compiler_pass.__dict__) + str(coverage.__dict__)
    assert "monitor_secret_alpha" not in compiled_text
    assert "cost_drift_report" not in compiled_text
    assert "actions" not in compiled_text

    audit = client.get("/api/research-os/graph/commands", params={"limit": 5})
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    matching = [
        command["payload"]["qro"]
        for command in audit_body["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == body["qro_id"]
    ]
    assert matching
    assert matching[0]["input_contract"]["scheduler_op"] == "monitor.weekly_tick"
    assert "monitor_secret_alpha" not in str(matching[0])


def test_weekly_monitor_endpoint_disables_ownerless_reconciliation_action_producer(
    monitor_env,
) -> None:
    client, _registry, _manager, _audit_log = monitor_env

    first = client.post("/api/monitor/weekly_tick", json={"week": "2024-05-01"})

    assert first.status_code == 200, first.text
    producer = first.json()["execution_reconciliation_action_producer"]
    assert producer == {
        "status": "disabled_requires_explicit_owner",
        "created_count": 0,
        "record_only": True,
    }
    assert main.EXECUTION_RECONCILIATION_ACTIONS.actions() == []

    second = client.post("/api/monitor/weekly_tick", json={"week": "2024-05-01"})
    assert second.status_code == 200, second.text
    assert second.json()["execution_reconciliation_action_producer"] == producer


def test_weekly_monitor_rejects_gate_verdict_as_observation(monitor_env) -> None:
    client, registry, manager, _audit_log = monitor_env
    factor = registry.register("no_gate_alpha", "close")
    registry.update_state(factor.factor_id, factor.version, "QUALIFIED")
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    before_ir = len(main.COMPILER_IR_STORE.irs())
    before_coverage = len(main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records())

    response = client.post(
        "/api/monitor/weekly_tick",
        json={
            "week": "2024-05-01",
            "factor_observations": [
                {
                    "factor_id": factor.factor_id,
                    "version": factor.version,
                    "ic_mean": 0.04,
                    "ic_ir": 0.7,
                    "rank_ic_mean": 0.035,
                    "sample_t": 3.5,
                    "dsr": 0.9,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert "gate/overfit" in response.text
    assert manager.history(factor.factor_id, factor.version) == []
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert len(main.COMPILER_IR_STORE.irs()) == before_ir
    assert len(main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()) == before_coverage


def test_weekly_monitor_dag_op_uses_configured_runtime(tmp_path, monkeypatch) -> None:
    registry = FactorRegistry(tmp_path / "factors.json")
    manager = LifecycleManager(registry, thresholds=LifecycleThresholds(warning_persist_weeks=2))
    audit_log = ExecutionAuditLog()
    graph = ResearchGraphStore()
    compiler_store, coverage_store = _install_goal_proof_stores(
        tmp_path, monkeypatch, graph
    )
    monkeypatch.setattr(
        main,
        "EXECUTION_RECONCILIATIONS",
        PersistentExecutionReconciliationRegistry(tmp_path / "dag_execution_reconciliations.jsonl"),
    )
    monkeypatch.setattr(
        main,
        "EXECUTION_RECONCILIATION_ACTIONS",
        PersistentExecutionReconciliationActionRegistry(tmp_path / "dag_execution_reconciliation_actions.jsonl"),
    )
    factor = registry.register("dag_alpha", "close")
    registry.update_state(factor.factor_id, factor.version, "WARNING")
    _high_cost_fill(audit_log, timestamp=datetime.now(UTC).isoformat())
    configure_monitor_runtime(
        lifecycle_manager=manager,
        factor_registry=registry,
        execution_audit_log=audit_log,
        result_recorder=main._record_weekly_monitor_qro_from_scheduler,
    )
    dag = build_weekly_monitor_dag(schedule="* * * * *")

    first = run_dag(dag)
    second = run_dag(dag)

    assert first.succeeded is True
    assert second.succeeded is True
    assert registry.get(factor.factor_id).lifecycle_state == "RETIRED"
    assert second.tasks[0].result["lifecycle_events"][0]["to_state"] == "RETIRED"
    assert first.tasks[0].result["qro_id"]
    assert second.tasks[0].result["research_graph_command_id"]
    assert first.tasks[0].result["entrypoint_coverage_ref"]
    assert second.tasks[0].result["compiler_pass_ref"]
    assert len(graph.commands()) == 2
    assert len(compiler_store.irs()) == 2
    assert len(compiler_store.passes()) == 2
    assert len(coverage_store.records()) == 2
    second_qro = graph.qro(second.tasks[0].result["qro_id"])
    assert second_qro.input_contract["entry_source"] == "scheduler"
    assert second_qro.input_contract["trigger"] == "dag"
    assert second_qro.output_contract["lifecycle_event_count"] == 1
    second_pass = compiler_store.compiler_pass(second.tasks[0].result["compiler_pass_ref"])
    assert second_pass.entry_source == "scheduler"
    assert second_pass.actor_source == "scheduled_agent"


def test_weekly_monitor_scheduler_builds_with_strict_croniter() -> None:
    scheduler = build_weekly_monitor_scheduler(strict=True, schedule="* * * * *")
    assert scheduler is not None
