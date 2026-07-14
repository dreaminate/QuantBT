"""模型中心 · 训练台 REST 端点测试（TestClient）。"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.auth import require_user_dependency
from app.experiments import ExperimentStore, ModelRegistry, RunStore
from app.main import app
from app.research_os import (
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentModelGovernanceRegistry,
    ResearchGraphStore,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver
from app.training import TrainingService

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authenticated_training_user():
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="pytest",
        username="pytest",
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_training_models_endpoint() -> None:
    r = client.get("/api/training/models")
    assert r.status_code == 200
    cards = r.json()
    keys = {c["key"] for c in cards}
    assert {"lgbm", "xgboost", "tft", "lstm"} <= keys
    xgb = next(c for c in cards if c["key"] == "xgboost")
    assert xgb["family"] == "ml"
    assert "param_schema" in xgb and "available" in xgb


def test_training_datasets_endpoint() -> None:
    r = client.get("/api/training/datasets")
    assert r.status_code == 200
    ds = r.json()
    assert any(d["dataset_id"] == "demo_ashare_xsec" for d in ds)
    assert all("feature_cols" in d for d in ds)


def test_training_codegen_preview() -> None:
    r = client.post(
        "/api/training/codegen",
        json={"model": "xgboost", "task": "regression", "feature_cols": ["f_mom5"], "label_col": "label"},
    )
    assert r.status_code == 200
    code = r.json()["code"]
    assert "train_model" in code and "emit" in code


def test_training_codegen_tft_now_runnable() -> None:
    # TFT 纯 torch 模板已落地 → codegen 生成 train_dl 代码
    r = client.post(
        "/api/training/codegen",
        json={"model": "tft", "task": "regression", "feature_cols": ["f_mom5"]},
    )
    assert r.status_code == 200
    assert "arch='tft'" in r.json()["code"]


def test_training_submit_and_poll_succeeds(training_market_data_use_validation_ref) -> None:
    r = client.post(
        "/api/training/jobs",
        json={
            "name": "api-xgb",
            "model": "xgboost",
            "task": "regression",
            "dataset_id": "demo_ashare_xsec",
            "market_data_use_validation_refs": [training_market_data_use_validation_ref],
            "feature_cols": ["f_mom5", "f_mom20", "f_vol20", "f_value"],
            "label_col": "label",
            "hyperparams": {"n_estimators": 40, "max_depth": 3},
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    final = None
    for _ in range(60):
        jr = client.get(f"/api/training/jobs/{job_id}")
        assert jr.status_code == 200
        final = jr.json()
        if final["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert final and final["status"] == "succeeded", final
    assert "r2" in final["metrics"]
    assert final["model_version"] is not None
    assert final["model_passport_ref"]
    assert final["validation_dossier_ref"]
    assert final["request"]["market_data_use_validation_refs"] == [training_market_data_use_validation_ref]
    assert job_id in {j["job_id"] for j in client.get("/api/training/jobs").json()}


def test_training_submit_requires_market_data_use_validation_refs() -> None:
    response = client.post(
        "/api/training/jobs",
        json={
            "name": "api-xgb-no-market-data-proof",
            "model": "xgboost",
            "task": "regression",
            "dataset_id": "demo_ashare_xsec",
            "feature_cols": ["f_mom5", "f_mom20"],
            "label_col": "label",
        },
    )

    assert response.status_code == 422
    assert "market_data_use_validation_refs is required" in response.text


@pytest.mark.parametrize("as_of_known", [None, "", "not-an-iso-time"])
def test_confirmatory_training_rejects_invalid_pit_cutoff_before_queue(
    as_of_known,
) -> None:
    before = {job.job_id for job in app_main.TRAINING_SERVICE.list_jobs()}
    payload = {
        "name": "confirmatory-without-valid-pit-cutoff",
        "model": "xgboost",
        "task": "regression",
        "dataset_id": "demo_ashare_xsec",
        "feature_cols": ["f_mom5", "f_mom20"],
        "label_col": "label",
        "use_context": "confirmatory_validation",
    }
    if as_of_known is not None:
        payload["as_of_known"] = as_of_known

    response = client.post("/api/training/jobs", json=payload)

    assert response.status_code == 422
    assert "as_of_known" in response.text
    assert {job.job_id for job in app_main.TRAINING_SERVICE.list_jobs()} == before


def test_training_success_records_model_qro_without_metrics_or_artifact_payload(
    tmp_path,
    monkeypatch,
    training_market_data_use_validation_ref,
) -> None:
    graph = ResearchGraphStore()
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
    experiments_root = tmp_path / "experiments"
    governance = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    service = TrainingService(
        tmp_path / "training_runs",
        experiment_store=ExperimentStore(experiments_root),
        run_store=RunStore(experiments_root),
        model_registry=ModelRegistry(experiments_root, model_governance_registry=governance),
        model_governance_registry=governance,
        result_recorder=app_main._record_training_job_qro,
        timeout=1800,
    )
    monkeypatch.setattr(app_main, "TRAINING_SERVICE", service)
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(app_main, "COMPILER_IR_STORE", compiler_store)
    monkeypatch.setattr(app_main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validation_store)
    monkeypatch.setattr(app_main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence_store)
    monkeypatch.setattr(app_main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    isolated = TestClient(app_main.app)

    response = isolated.post(
        "/api/training/jobs",
        json={
            "name": "graph-qro-xgb",
            "model": "xgboost",
            "task": "regression",
            "dataset_id": "demo_ashare_xsec",
            "market_data_use_validation_refs": [training_market_data_use_validation_ref],
            "feature_cols": ["f_mom5", "f_mom20", "f_vol20", "f_value"],
            "label_col": "label",
            "hyperparams": {"n_estimators": 20, "max_depth": 2},
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    final = None
    for _ in range(60):
        polled = isolated.get(f"/api/training/jobs/{job_id}")
        assert polled.status_code == 200, polled.text
        final = polled.json()
        if final["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)

    assert final and final["status"] == "succeeded", final
    assert final["qro_id"]
    assert final["research_graph_command_id"]
    assert final["compiler_ir_ref"]
    assert final["compiler_pass_ref"]
    assert final["entrypoint_coverage_ref"]
    qro = graph.qro(final["qro_id"])
    assert qro.qro_type == "Model" or getattr(qro.qro_type, "value", None) == "Model"
    assert qro.input_contract["entry_source"] == "api"
    assert qro.input_contract["job_id"] == job_id
    assert qro.input_contract["market_data_use_validation_refs"] == [training_market_data_use_validation_ref]
    assert qro.output_contract["model_version_ref"].startswith("model_version:xgboost:v")
    assert qro.output_contract["model_passport_ref"] == final["model_passport_ref"]
    assert qro.output_contract["validation_dossier_ref"] == final["validation_dossier_ref"]
    assert qro.output_contract["market_data_use_validation_refs"] == [training_market_data_use_validation_ref]
    qro_contract_text = str(qro.input_contract) + str(qro.output_contract)
    assert "artifact_dir" not in qro_contract_text
    assert "artifact_path" not in qro_contract_text
    assert "r2" not in qro_contract_text
    ir = compiler_store.ir(final["compiler_ir_ref"])
    compiler_pass = compiler_store.compiler_pass(final["compiler_pass_ref"])
    coverage = coverage_store.coverage(final["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (final["qro_id"],)
    assert ir.graph_command_refs == (final["research_graph_command_id"],)
    assert ir.permission_ref == "training.job:service"
    assert len(ir.validation_refs) == 1
    [validation_ref] = ir.validation_refs
    assert validation_ref.startswith("goal_validation_receipt:")
    receipt = validation_store.receipt(validation_ref, owner_user_id="pytest")
    assert receipt.subject_qro_refs == (final["qro_id"],)
    assert receipt.graph_command_refs == (final["research_graph_command_id"],)
    assert receipt.outcome == "passed"
    assert final["validation_dossier_ref"] in receipt.evidence_refs
    assert final["model_passport_ref"] in receipt.evidence_refs
    assert training_market_data_use_validation_ref in receipt.evidence_refs
    assert compiler_pass.entry_source == "api"
    assert compiler_pass.actor_source == "agent"
    assert compiler_pass.permission_ref == "training.job:service"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == "api:training.jobs"
    assert coverage.qro_refs == (final["qro_id"],)
    assert coverage.research_graph_command_refs == (final["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (final["compiler_ir_ref"],)
    compiled_text = str(ir.__dict__) + str(compiler_pass.__dict__) + str(coverage.__dict__)
    assert "artifact_dir" not in compiled_text
    assert "artifact_path" not in compiled_text
    assert "r2" not in compiled_text

    audit = isolated.get("/api/research-os/graph/commands", params={"limit": 5})
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    matching = [
        command["payload"]["qro"]
        for command in audit_body["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == final["qro_id"]
    ]
    assert matching
    assert matching[0]["output_contract"]["metrics_hash"]
    assert "artifact_path" not in str(matching[0])
    assert "r2" not in str(matching[0])


def test_training_model_detail_has_body() -> None:
    r = client.get("/api/training/models/lstm")
    assert r.status_code == 200
    assert "## L1" in r.json()["body"]
    assert client.get("/api/training/models/nope").status_code == 404


def test_training_agent_context_endpoint() -> None:
    r = client.get("/api/training/agent_context")
    assert r.status_code == 200
    assert "只能" in r.json()["system_prompt"]


def test_training_add_model_roundtrip() -> None:
    from app.models.card_loader import DEFAULT_CARDS_DIR
    from app.models.catalog import reload_catalog

    key = "api_test_tabnet"
    path = DEFAULT_CARDS_DIR / f"{key}.md"
    if path.exists():  # 防御：上次被 kill 的 run 可能留下残卡 → 先清，保证幂等
        path.unlink()
        reload_catalog()
    try:
        r = client.post(
            "/api/training/models",
            json={"key": key, "family": "dl", "display_name": "TabNet(测试)", "tasks": ["regression"], "description": "agent 搜来的新模型"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["runnable"] is False
        assert key in {c["key"] for c in client.get("/api/training/models").json()}
    finally:
        if path.exists():
            path.unlink()
        reload_catalog()


def test_training_submit_bad_dataset() -> None:
    r = client.post(
        "/api/training/jobs",
        json={"model": "xgboost", "task": "regression", "dataset_id": "nope", "feature_cols": ["f_mom5"]},
    )
    assert r.status_code == 400
