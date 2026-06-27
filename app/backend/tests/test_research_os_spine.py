from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    ActorSource,
    ConsistencyCheck,
    ConsistencyStatus,
    EntrySource,
    MathematicalSpineChainRecord,
    MethodologyChoiceRecord,
    MethodologyPath,
    PersistentMathematicalSpineChainRegistry,
    PromotionGuard,
    PromotionLabel,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphError,
    ResearchGraphStore,
    RuntimeStatus,
    TheoryImplementationBinding,
    TheoryStatus,
    validate_mathematical_spine_chain,
)


def _qro(**overrides) -> QRORecord:
    data = {
        "qro_type": QROType.STRATEGY_BOOK,
        "owner": "dreaminate",
        "actor": ActorSource.USER_MANUAL,
        "input_contract": {"intent": "long BTC momentum"},
        "output_contract": {"strategy_book": "v1"},
        "market": "crypto",
        "universe": "BTCUSDT",
        "horizon": "30d",
        "frequency": "1d",
        "lineage": ("source:unit-test",),
        "implementation_hash": "impl_abc",
        "assumptions": ("daily close is tradable at next bar",),
        "known_limits": ("sample fixture only",),
        "failure_modes": ("look-ahead in signal timestamp",),
        "validation_plan": ("run backtest",),
    }
    data.update(overrides)
    return QRORecord(**data)


def _binding() -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref="math_momentum_payoff",
        implementation_ref="app/strategy/momentum.py",
        implementation_spec="signal is close/ma - 1",
        code_ref="app/strategy/momentum.py:1",
        config_ref="cfg_v1_demo",
        data_contract_ref="dataset:BTCUSDT_1d",
        test_refs=("tests/test_momentum.py::test_signal_formula",),
        simulation_refs=("sim:momentum-fixture",),
        numerical_check_refs=("check:numerical-close-ma",),
        symbol_mapping={"P_t": "close"},
        unit_mapping={"return": "ratio"},
        dimension_check="dimensionless ratio",
        tolerance="1e-9",
        known_differences=(),
        consistency_verdict=ConsistencyStatus.ACCEPTED,
        verifier_ref="verifier:unit",
    )


def _chain(**overrides) -> MathematicalSpineChainRecord:
    data = {
        "chain_ref": "math_spine_chain:btc_momentum:v1",
        "data_semantics_ref": "dataset_semantics:btc_1d",
        "factor_ref": "factor:momentum_20d",
        "model_ref": "model:momentum_classifier:v1",
        "forecast_ref": "forecast:btc_momentum:v1",
        "signal_contract_ref": "signal_contract:btc_momentum:v1",
        "strategy_book_ref": "strategy_book:btc_momentum:v1",
        "portfolio_policy_ref": "portfolio_policy:btc_momentum:v1",
        "risk_policy_ref": "risk_policy:btc_momentum:v1",
        "execution_policy_ref": "execution_policy:paper_btc:v1",
        "backtest_run_ref": "backtest_run:bt1",
        "attribution_ref": "attribution:bt1",
        "monitor_ref": "monitor:weekly_btc_momentum",
        "theory_binding_refs": ("tbind:momentum", "tbind:portfolio-risk"),
        "consistency_check_refs": ("ccheck:momentum", "ccheck:risk"),
        "methodology_choice_ref": "mchoice:standard",
        "responsibility_boundary_ref": "resp:standard",
        "evidence_refs": ("evidence:bt1", "evidence:monitor"),
        "validation_refs": ("pytest:test_research_os_spine",),
        "consistency_verdict": ConsistencyStatus.ACCEPTED,
        "target_runtime": RuntimeStatus.PAPER,
        "recorded_by": "u1",
    }
    data.update(overrides)
    return MathematicalSpineChainRecord(**data)


def _payload(record) -> dict:
    return record.__dict__.copy()


def _client_with_chain_store(tmp_path, monkeypatch):
    store = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")
    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store


def test_research_graph_writes_require_canonical_command():
    store = ResearchGraphStore()
    qro = _qro()
    cmd = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"qro": qro},
        evidence_refs=("unit:evidence",),
    )
    command_id = store.apply(cmd)
    assert command_id.startswith("rgcmd_")
    assert store.qro(qro.qro_id).qro_id == qro.qro_id
    assert store.commands()[0].source == EntrySource.CANVAS


def test_research_graph_rejects_canvas_mutation_without_qro_payload():
    store = ResearchGraphStore()
    bad = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"not_qro": {}},
    )
    with pytest.raises(ResearchGraphError):
        store.apply(bad)


def test_status_axes_stay_separate_not_single_green_light():
    qro = _qro(
        evidence_status="sufficient",
        governance_status="unreviewed",
        runtime_status="offline",
    )
    assert qro.status_axes() == {
        "definition": "draft",
        "theory": "not_required",
        "consistency": "not_applicable",
        "evidence": "sufficient",
        "governance": "unreviewed",
        "runtime": "offline",
    }


def test_user_waived_methodology_requires_responsibility_boundary_and_skipped_steps():
    with pytest.raises(ValueError):
        MethodologyChoiceRecord(
            asset_ref="qro_1",
            run_ref=None,
            chosen_path=MethodologyPath.USER_WAIVED_THEORY,
            available_options=("strict", "user_waived_theory"),
            recommendation="strict",
            tradeoffs_shown=("faster but weaker claim",),
            risks_shown=("formula may not match implementation",),
            responsibility_boundary="user accepts exploratory-only status",
            actor=ActorSource.USER_MANUAL,
            allowed_environment=RuntimeStatus.PAPER,
            skipped_steps=(),
        )


def test_promotion_rejects_user_waiver_as_strong_evidence():
    choice = MethodologyChoiceRecord(
        asset_ref="qro_1",
        run_ref=None,
        chosen_path=MethodologyPath.USER_WAIVED_THEORY,
        available_options=("strict", "user_waived_theory"),
        recommendation="strict",
        tradeoffs_shown=("faster but weaker claim",),
        risks_shown=("theory gap remains",),
        responsibility_boundary="user accepts exploratory-only status",
        actor=ActorSource.USER_MANUAL,
        allowed_environment=RuntimeStatus.PAPER,
        skipped_steps=("TheorySpec derivation",),
    )
    qro = _qro(
        evidence_refs=("run:bt1",),
        methodology_choice_ref=choice.choice_id,
        theory_status=TheoryStatus.USER_WAIVED,
    )
    decision = PromotionGuard.evaluate(
        qro,
        target_labels={PromotionLabel.EVIDENCE_SUFFICIENT},
        methodology_choices={choice.choice_id: choice},
    )
    assert not decision.accepted
    assert {v.code for v in decision.violations} >= {"user_waiver_overclaim", "theory_waived_overclaim"}


def test_promotion_rejects_theory_claim_without_binding():
    qro = _qro(
        evidence_refs=("run:bt1",),
        mathematical_refs=("math_momentum_payoff",),
        theory_status=TheoryStatus.ACCEPTED,
        consistency_status=ConsistencyStatus.UNBOUND,
    )
    decision = PromotionGuard.evaluate(qro, target_labels={PromotionLabel.PROOF_BACKED})
    assert not decision.accepted
    assert {v.code for v in decision.violations} >= {"missing_theory_binding", "consistency_not_accepted"}


def test_promotion_accepts_bound_theory_with_consistency_check():
    binding = _binding()
    check = ConsistencyCheck(
        binding_id=binding.binding_id,
        check_type="numerical",
        input_refs=("fixture:btc",),
        expected_property="signal equals close/ma - 1",
        observed_property="max_abs_error=0",
        result=ConsistencyStatus.ACCEPTED,
        affected_assets=("qro:strategy",),
        verifier_ref="verifier:unit",
    )
    qro = _qro(
        evidence_refs=("run:bt1",),
        mathematical_refs=(binding.theory_ref,),
        theory_status=TheoryStatus.ACCEPTED,
        consistency_status=ConsistencyStatus.ACCEPTED,
        theory_implementation_binding=binding.binding_id,
        mock_profile="none",
    )
    decision = PromotionGuard.evaluate(
        qro,
        target_labels={PromotionLabel.PROOF_BACKED, PromotionLabel.EVIDENCE_SUFFICIENT},
        bindings={binding.binding_id: binding},
        consistency_checks={binding.binding_id: [check]},
    )
    assert decision.accepted
    assert decision.violations == ()


def test_production_ready_rejects_explicit_mock_profile():
    qro = _qro(evidence_refs=("run:bt1",), mock_profile="deterministic_sim_walk")
    decision = PromotionGuard.evaluate(qro, target_labels={PromotionLabel.PRODUCTION_READY})
    assert not decision.accepted
    assert {v.code for v in decision.violations} == {"production_mock_fallback"}


def test_mathematical_spine_chain_requires_full_data_to_monitor_refs():
    decision = validate_mathematical_spine_chain(
        _chain(
            model_ref="",
            forecast_ref="",
            execution_policy_ref="",
            monitor_ref="",
            theory_binding_refs=(),
            consistency_check_refs=(),
            consistency_verdict=ConsistencyStatus.UNBOUND,
        )
    )
    assert not decision.accepted
    assert {violation.code for violation in decision.violations} >= {
        "mathematical_spine_chain_required_ref_missing",
        "mathematical_spine_chain_consistency_not_accepted",
    }
    assert {violation.field for violation in decision.violations} >= {
        "model_ref",
        "forecast_ref",
        "execution_policy_ref",
        "monitor_ref",
        "theory_binding_refs",
        "consistency_check_refs",
    }


def test_mathematical_spine_chain_rejects_silent_mock_fallback():
    decision = validate_mathematical_spine_chain(_chain(silent_mock_fallback_used=True))
    assert not decision.accepted
    assert {violation.code for violation in decision.violations} == {
        "mathematical_spine_chain_silent_mock_fallback"
    }


def test_persistent_mathematical_spine_chain_registry_replays_record(tmp_path):
    path = tmp_path / "mathematical_spine_chains.jsonl"
    store = PersistentMathematicalSpineChainRegistry(path)
    store.record_chain(_chain())

    reloaded = PersistentMathematicalSpineChainRegistry(path)
    assert reloaded.chain("math_spine_chain:btc_momentum:v1").monitor_ref == "monitor:weekly_btc_momentum"
    assert reloaded.chains()[0].signal_contract_ref == "signal_contract:btc_momentum:v1"


def test_persistent_mathematical_spine_chain_registry_rejects_invalid_without_writing(tmp_path):
    store = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")

    with pytest.raises(ValueError, match="mathematical_spine_chain_required_ref_missing"):
        store.record_chain(_chain(evidence_refs=(), validation_refs=()))

    assert not store.path.exists()


def test_mathematical_spine_chain_api_records_summary(tmp_path, monkeypatch):
    client, _store = _client_with_chain_store(tmp_path, monkeypatch)
    try:
        response = client.post("/api/research-os/spine/mathematical_chains", json=_payload(_chain(recorded_by="spoof")))
        assert response.status_code == 200, response.text
        assert response.json() == {
            "chain_ref": "math_spine_chain:btc_momentum:v1",
            "target_runtime": "paper",
            "recorded_by": "u1",
        }

        summary = client.get("/api/research-os/spine/mathematical_chains/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["user"] == "u1"
        assert body["mathematical_chain_total"] == 1
        assert body["mathematical_chains"][0]["recorded_by"] == "u1"
        assert body["mathematical_chains"][0]["execution_policy_ref"] == "execution_policy:paper_btc:v1"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
