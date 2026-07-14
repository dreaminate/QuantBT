from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.factor_factory import FactorRegistry, LifecycleManager, SignalContractRegistry
from app.hypothesis.store import HypothesisCardStore
from app.research_os import (
    PersistentAssetLifecycleRegistry,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentResearchAssetRAGIndex,
    PersistentResearchGraphStore,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.research_design_assets import (
    PersistentResearchDesignAssetRegistry,
)
from app.strategy_goal import PRESETS
from app.strategy_goal_store import StrategyGoalStore


OWNER = "research-design-api-owner"


def _install_research_design_api_stores(tmp_path, monkeypatch):
    design = PersistentResearchDesignAssetRegistry(
        tmp_path / "research_design.jsonl"
    )
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    lifecycle = PersistentAssetLifecycleRegistry(tmp_path / "lifecycle.jsonl")
    rag = PersistentResearchAssetRAGIndex(tmp_path / "rag.jsonl")
    factors = FactorRegistry(tmp_path / "factors.json")
    goals = StrategyGoalStore(tmp_path / "strategy_goals")
    hypotheses = HypothesisCardStore(tmp_path / "hypotheses")
    signals = SignalContractRegistry(tmp_path / "signals.jsonl")
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=lifecycle,
            governance_registry=None,
            rag_index=rag,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_DESIGN_ASSET_REGISTRY", design)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", rag)
    monkeypatch.setattr(main, "FACTOR_REGISTRY", factors)
    monkeypatch.setattr(main, "FACTOR_LIFECYCLE", LifecycleManager(factors))
    monkeypatch.setattr(main, "STRATEGY_GOAL_STORE", goals)
    monkeypatch.setattr(main, "HYPOTHESIS_STORE", hypotheses)
    monkeypatch.setattr(main, "SIGNAL_CONTRACTS", signals)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    return design, graph, lifecycle, rag, goals


def test_normal_apis_record_owner_typed_m1_m4_and_signal_assets(
    tmp_path,
    monkeypatch,
):
    design, graph, lifecycle, rag, goals = _install_research_design_api_stores(
        tmp_path, monkeypatch
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=OWNER,
        username="researcher",
    )
    try:
        client = TestClient(main.app)
        universe_response = client.post(
            "/api/research_os/universe_definitions",
            json={
                "id": "api-crypto-pairs",
                "name": "API crypto pairs",
                "market": "binanceusdm",
                "rules": {
                    "market": "binanceusdm",
                    "static_symbols": ["BTCUSDT", "ETHUSDT"],
                },
            },
        )
        assert universe_response.status_code == 200, universe_response.text
        universe_body = universe_response.json()
        universe_ref = universe_body["universe_definition_ref"]
        assert design.universe_definition(
            universe_ref, owner_user_id=OWNER
        ).definition["id"] == "api-crypto-pairs"

        regime_response = client.post(
            "/api/research_os/regime_scenarios",
            json={
                "universe_definition_ref": universe_ref,
                "scenario": {
                    "name": "API high volatility",
                    "detector": "wilder_adx_vol_z",
                    "config": {"vol_window": 20, "crisis_z": 1.5},
                },
            },
        )
        assert regime_response.status_code == 200, regime_response.text
        regime_ref = regime_response.json()["regime_scenario_ref"]
        assert design.regime_scenario(
            regime_ref, owner_user_id=OWNER
        ).universe_definition_ref == universe_ref

        label_response = client.post(
            "/api/research_os/label_definitions",
            json={
                "label_kind": "time_series",
                "output_column": "forward_return_5d",
                "horizon": 5,
                "parameters": {"price_column": "close"},
                "known_at_rule": "known after the five-day horizon closes",
                "effective_at_rule": "effective at the forecast origin",
                "market": "binanceusdm",
                "universe_ref": universe_ref,
                "frequency": "1d",
            },
        )
        assert label_response.status_code == 200, label_response.text
        label_ref = label_response.json()["label_ref"]
        assert design.label_definition(
            label_ref, owner_user_id=OWNER
        ).output_column == "forward_return_5d"

        goal_id = goals.create(PRESETS["crypto_perp_trend_daily"])
        hypothesis_response = client.post(
            "/api/hypothesis_cards",
            json={
                "strategy_goal_ref": f"strategy_goal:{goal_id}",
                "layer": "exploratory",
                "universe_definition_ref": universe_ref,
                "regime_scenario_ref": regime_ref,
            },
        )
        assert hypothesis_response.status_code == 200, hypothesis_response.text
        hypothesis_body = hypothesis_response.json()
        hypothesis = design.hypothesis_envelope(
            hypothesis_body["hypothesis_card_ref"],
            owner_user_id=OWNER,
        )
        assert hypothesis.universe_definition_ref == universe_ref
        assert hypothesis.regime_scenario_ref == regime_ref

        factor_response = client.post(
            "/api/factors",
            json={
                "factor_id": "api_momentum",
                "formula": "ts_mean(close, 5)",
                "label_ref": label_ref,
            },
        )
        assert factor_response.status_code == 200, factor_response.text
        factor_body = factor_response.json()
        factor_envelope = design.factor_envelope(
            factor_body["factor_ref"], owner_user_id=OWNER
        )
        assert factor_envelope.label_ref == label_ref

        signal_response = client.post(
            "/api/factors/signal_contracts",
            json={
                "name": "API signal",
                "source_lib": "ml",
                "model_ref": "registry://models/api_signal.pkl",
                "output_kind": "xs_score",
                "horizon": 5,
                "leakage": {"oof": True, "purge": True, "embargo": True},
            },
        )
        assert signal_response.status_code == 200, signal_response.text
        signal_body = signal_response.json()
        signal_envelope = design.signal_contract_envelope(
            signal_body["signal_contract_ref"], owner_user_id=OWNER
        )
        assert signal_envelope.source_content_hash == signal_body["source_content_hash"]

        for body, asset_type in (
            (universe_body, "UniverseDefinition"),
            (regime_response.json(), "RegimeScenario"),
            (label_response.json(), "LabelDefinition"),
            (hypothesis_body, "HypothesisCard"),
        ):
            assert graph.qro(body["qro_id"]).owner == OWNER
            assert lifecycle.governed_asset(
                body["lifecycle_ref"], owner_user_id=OWNER
            ).asset_type == asset_type
            assert rag.document_for_owner(
                body["rag_ref"],
                owner_user_id=OWNER,
                require_current=True,
            ).permission.allowed_users == (OWNER,)

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            user_id="other-owner",
            username="other",
        )
        hidden = client.get(f"/api/research_os/universe_definitions/{universe_ref}")
        assert hidden.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
