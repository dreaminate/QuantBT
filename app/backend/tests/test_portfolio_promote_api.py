from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.factor_factory import SignalContractRegistry
from app.lineage.ledger import Ledger
from app.portfolio.gate import portfolio_strategy_goal_ref
from app.research_os import (
    MarketDataUseValidationRecord,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentResearchGraphStore,
    PersistentSignalValidationRegistry,
    QROType,
    SignalPerformanceValidationRecord,
    SignalValidationVerdict,
)


class _MemReturnsStore:
    def __init__(self) -> None:
        self._data: dict[str, list[float]] = {}

    def put(self, key: str, value: list[float]) -> None:
        self._data.setdefault(key, list(value))

    def get(self, key: str) -> list[float]:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]


class _MarketDataUseRegistry:
    def __init__(self, records: list[MarketDataUseValidationRecord] | None = None) -> None:
        self._records = {record.validation_ref: record for record in records or []}

    def use_validation(self, validation_ref: str) -> MarketDataUseValidationRecord:
        if validation_ref not in self._records:
            raise KeyError(validation_ref)
        return self._records[validation_ref]


def _market_data_use_validation(**overrides) -> MarketDataUseValidationRecord:
    data = {
        "validation_ref": "market_data_use:portfolio:accepted",
        "request_ref": "market_data_request:portfolio",
        "use_context": "production",
        "dataset_refs": ("dataset:portfolio_panel:v2",),
        "instrument_refs": ("instrument:BTCUSDT", "instrument:ETHUSDT"),
        "capability_matrix_ref": "capability:crypto_portfolio:production",
        "capital_record_ref": None,
        "transformation_refs": ("transform:returns:v1",),
        "accepted": True,
        "violation_codes": (),
        "evidence_refs": ("evidence:market_data_use_gate",),
        "recorded_by": "tester",
        "created_at_utc": "2026-06-27T00:00:00+00:00",
    }
    data.update(overrides)
    return MarketDataUseValidationRecord(**data)


@pytest.fixture
def portfolio_promote_env(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path / "lineage")
    returns_store = _MemReturnsStore()
    monkeypatch.setattr(main, "LEDGER", ledger)
    monkeypatch.setattr(main, "RETURNS_STORE", returns_store)
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([_market_data_use_validation()]))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", PersistentResearchGraphStore(tmp_path / "research_graph.jsonl"))
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester", username="tester"
    )
    try:
        yield TestClient(main.app), ledger, returns_store
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def _payload(*, weights: dict[str, float] | None = None) -> dict:
    n = 320
    weights = weights or {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    return {
        "weights": weights,
        "asset_returns": {
            "BTCUSDT": [0.0012 + (0.0002 if idx % 5 == 0 else 0.0) for idx in range(n)],
            "ETHUSDT": [0.0008 + (0.0001 if idx % 7 == 0 else 0.0) for idx in range(n)],
        },
        "markets": {"BTCUSDT": "crypto_perp", "ETHUSDT": "crypto_spot"},
        "dataset_version": "panel:prod:test",
        "market_data_use_validation_refs": ["market_data_use:portfolio:accepted"],
        "freq": "1d",
    }


def _assert_portfolio_compiler_coverage(body: dict) -> None:
    assert body["qro_id"].startswith("qro_")
    assert body["research_graph_command_id"].startswith("rgcmd_")
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    qro = main.RESEARCH_GRAPH_STORE.qro(body["qro_id"])
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert qro.qro_type == QROType.PORTFOLIO_POLICY
    assert qro.output_contract["promote_state"] == "gate_recorded"
    assert qro.output_contract["config_hash"] == body["config_hash"]
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == "api:portfolios.promote"
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.research_graph_command_refs == (body["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert compiler_pass.direct_graph_mutation is False
    assert compiler_pass.bypassed_permission is False
    assert compiler_pass.raw_llm_output_embedded_as_ir is False
    assert coverage.silent_mock_fallback_used is False
    assert coverage.raw_payload_persisted is False
    compiled_text = f"{qro.__dict__} {ir.__dict__} {compiler_pass.__dict__} {coverage.__dict__}"
    assert "asset_returns" not in compiled_text
    assert "0.0012" not in compiled_text
    assert "0.0008" not in compiled_text
    assert "sk-" not in compiled_text


def _signal_contract_and_validation(tmp_path, monkeypatch, *, verdict=SignalValidationVerdict.ACCEPTED):
    contracts = SignalContractRegistry(tmp_path / "signal_contracts.jsonl")
    contract = contracts.register(
        name="Portfolio signal",
        source_lib="ml",
        model_ref="registry://models/portfolio_signal.pkl",
        output_kind="xs_score",
        horizon=5,
        leakage={"oof": True, "purge": True, "embargo": True},
        author="tester",
    )
    validations = PersistentSignalValidationRegistry(tmp_path / "signal_validations.jsonl")
    validation = validations.record_validation(
        SignalPerformanceValidationRecord(
            signal_ref=contract.signal_ref,
            validation_dataset_ref="dataset_version:portfolio:oos",
            evaluation_window_ref="window:2025q4",
            methodology_ref="methodology:cpcv_walkforward",
            metric_refs=("metric:rank_ic", "metric:dsr"),
            performance_summary_ref="signal_perf:portfolio_signal:oos",
            leakage_check_ref="leakage:oof_purge_embargo",
            evidence_refs=("evidence:signal_validation_report",),
            verdict=verdict,
            recorded_by="tester",
        ),
        known_signal_refs={contract.signal_ref},
    )
    monkeypatch.setattr(main, "SIGNAL_CONTRACTS", contracts)
    monkeypatch.setattr(main, "SIGNAL_VALIDATIONS", validations)
    return contract, validation


def test_portfolio_promote_records_honest_n_and_gate(portfolio_promote_env) -> None:
    client, ledger, _store = portfolio_promote_env
    ref = portfolio_strategy_goal_ref("p_prod")
    assert ledger.honest_n(ref) == 0

    response = client.post("/api/portfolios/p_prod/promote", json=_payload())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["record"] is True
    assert body["promote_state"] == "gate_recorded"
    assert body["strategy_goal_ref"] == ref
    assert body["honest_n_before"] == 0
    assert body["honest_n_after"] == 1
    assert body["honest_n_delta"] == 1
    assert body["gate_verdict"]["honest_n"] == 1
    assert body["config_hash"].startswith("cfg_v1_")
    _assert_portfolio_compiler_coverage(body)
    assert ledger.honest_n(ref) == 1
    assert "no order" in body["boundary"]


def test_portfolio_promote_accepts_signal_with_accepted_validation(portfolio_promote_env, tmp_path, monkeypatch) -> None:
    client, ledger, _store = portfolio_promote_env
    contract, validation = _signal_contract_and_validation(tmp_path, monkeypatch)
    payload = _payload()
    payload["signal_refs"] = [contract.signal_ref]
    payload["signal_validation_refs"] = [validation.validation_id]

    response = client.post("/api/portfolios/p_signal/promote", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["signal_refs"] == [contract.signal_ref]
    assert body["signal_validation_refs"] == [validation.validation_id]
    assert body["market_data_use_validation_refs"] == ["market_data_use:portfolio:accepted"]
    _assert_portfolio_compiler_coverage(body)
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_signal")) == 1


def test_portfolio_promote_rejects_missing_market_data_use_validation_without_recording(
    portfolio_promote_env,
) -> None:
    client, ledger, _store = portfolio_promote_env
    payload = _payload()
    payload.pop("market_data_use_validation_refs")

    response = client.post("/api/portfolios/p_missing_market_data_use/promote", json=payload)

    assert response.status_code == 422
    assert "market_data_use_validation_refs" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_missing_market_data_use")) == 0


def test_portfolio_promote_rejects_unknown_market_data_use_validation_without_recording(
    portfolio_promote_env,
) -> None:
    client, ledger, _store = portfolio_promote_env
    payload = _payload()
    payload["market_data_use_validation_refs"] = ["market_data_use:missing"]

    response = client.post("/api/portfolios/p_unknown_market_data_use/promote", json=payload)

    assert response.status_code == 422
    assert "unknown market data use validation" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_unknown_market_data_use")) == 0


def test_portfolio_promote_rejects_unaccepted_market_data_use_validation_without_recording(
    portfolio_promote_env,
    monkeypatch,
) -> None:
    client, ledger, _store = portfolio_promote_env
    rejected = _market_data_use_validation(
        validation_ref="market_data_use:portfolio:rejected",
        accepted=False,
        violation_codes=("market_data_use_live_matrix_unavailable",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([rejected]))
    payload = _payload()
    payload["market_data_use_validation_refs"] = [rejected.validation_ref]

    response = client.post("/api/portfolios/p_rejected_market_data_use/promote", json=payload)

    assert response.status_code == 422
    assert "not accepted" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_rejected_market_data_use")) == 0


def test_portfolio_promote_rejects_market_data_use_symbol_mismatch_without_recording(
    portfolio_promote_env,
    monkeypatch,
) -> None:
    client, ledger, _store = portfolio_promote_env
    mismatch = _market_data_use_validation(
        validation_ref="market_data_use:portfolio:eth_only",
        instrument_refs=("instrument:ETHUSDT",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([mismatch]))
    payload = _payload()
    payload["market_data_use_validation_refs"] = [mismatch.validation_ref]

    response = client.post("/api/portfolios/p_market_data_symbol_mismatch/promote", json=payload)

    assert response.status_code == 422
    assert "do not cover portfolio symbols" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_market_data_symbol_mismatch")) == 0


def test_portfolio_promote_rejects_signal_without_accepted_validation(
    portfolio_promote_env,
    tmp_path,
    monkeypatch,
) -> None:
    client, ledger, _store = portfolio_promote_env
    contract, _validation = _signal_contract_and_validation(tmp_path, monkeypatch)
    payload = _payload()
    payload["signal_refs"] = [contract.signal_ref]

    response = client.post("/api/portfolios/p_missing_signal_validation/promote", json=payload)

    assert response.status_code == 422
    assert "signal_validation_refs" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_missing_signal_validation")) == 0


def test_portfolio_promote_rejects_rejected_signal_validation_without_recording(
    portfolio_promote_env,
    tmp_path,
    monkeypatch,
) -> None:
    client, ledger, _store = portfolio_promote_env
    contract, validation = _signal_contract_and_validation(
        tmp_path,
        monkeypatch,
        verdict=SignalValidationVerdict.REJECTED,
    )
    payload = _payload()
    payload["signal_refs"] = [contract.signal_ref]
    payload["signal_validation_refs"] = [validation.validation_id]

    response = client.post("/api/portfolios/p_rejected_signal_validation/promote", json=payload)

    assert response.status_code == 422
    assert "not accepted" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_rejected_signal_validation")) == 0


def test_portfolio_promote_reordered_composition_does_not_double_spend(portfolio_promote_env) -> None:
    client, ledger, _store = portfolio_promote_env
    ref = portfolio_strategy_goal_ref("p_same")
    first = client.post("/api/portfolios/p_same/promote", json=_payload())
    assert first.status_code == 200, first.text

    reordered = _payload(weights={"ETHUSDT": 0.4, "BTCUSDT": 0.6})
    reordered["asset_returns"] = {
        "ETHUSDT": reordered["asset_returns"]["ETHUSDT"],
        "BTCUSDT": reordered["asset_returns"]["BTCUSDT"],
    }
    reordered["markets"] = {"ETHUSDT": "crypto_spot", "BTCUSDT": "crypto_perp"}
    second = client.post("/api/portfolios/p_same/promote", json=reordered)

    assert second.status_code == 200, second.text
    assert second.json()["config_hash"] == first.json()["config_hash"]
    assert second.json()["honest_n_before"] == 1
    assert second.json()["honest_n_after"] == 1
    assert second.json()["honest_n_delta"] == 0
    assert ledger.honest_n(ref) == 1


def test_portfolio_promote_overfit_records_without_false_green(portfolio_promote_env, monkeypatch) -> None:
    client, ledger, _store = portfolio_promote_env
    validation = _market_data_use_validation(
        validation_ref="market_data_use:bad_symbol:accepted",
        instrument_refs=("instrument:BAD",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([validation]))
    n = 320
    payload = {
        "weights": {"BAD": 1.0},
        "asset_returns": {"BAD": [(-0.002 if idx % 2 == 0 else -0.0005) for idx in range(n)]},
        "markets": {"BAD": "crypto_perp"},
        "dataset_version": "panel:negative:test",
        "market_data_use_validation_refs": [validation.validation_ref],
        "freq": "1d",
    }

    response = client.post("/api/portfolios/p_bad/promote", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gate_verdict"]["color"] != "green"
    assert body["honest_n_after"] == 1
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_bad")) == 1


def test_portfolio_promote_bad_input_does_not_record(portfolio_promote_env) -> None:
    client, ledger, _store = portfolio_promote_env
    payload = _payload()
    payload["asset_returns"]["ETHUSDT"] = [0.01]

    response = client.post("/api/portfolios/p_invalid/promote", json=payload)

    assert response.status_code == 422
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_invalid")) == 0


def test_portfolio_promote_preview_flag_rejected(portfolio_promote_env) -> None:
    client, ledger, _store = portfolio_promote_env
    payload = _payload()
    payload["record"] = False

    response = client.post("/api/portfolios/p_preview/promote", json=payload)

    assert response.status_code == 422
    assert "record=True" in response.text
    assert ledger.honest_n(portfolio_strategy_goal_ref("p_preview")) == 0
