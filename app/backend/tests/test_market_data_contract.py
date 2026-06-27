from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    CrossCurrencyCapitalRecord,
    DataTransformationClaim,
    DatasetSemanticsRecord,
    InstrumentSpec,
    MarketCapabilityMatrixRecord,
    MarketDataUseRequest,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentMarketDataRegistry,
    PersistentResearchGraphStore,
    QROType,
    ValidationUseContext,
    dataset_semantics_record_from_dict,
    validate_dataset_semantics,
    validate_market_data_use,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _dataset(**overrides) -> DatasetSemanticsRecord:
    data = {
        "dataset_ref": "dataset:btc_daily:v1",
        "source_ref": "source:binance_vision",
        "version": "v1",
        "known_at_ref": "known_at:ingest_time",
        "effective_at_ref": "effective_at:bar_close",
        "pit_bitemporal_rules_ref": "pit:bars:v1",
        "quality_status": "passed",
        "lineage_refs": ("lineage:btc_daily:v1",),
        "freshness_status": "fresh",
        "checksum": "sha256:abc",
    }
    data.update(overrides)
    return DatasetSemanticsRecord(**data)


def _instrument(**overrides) -> InstrumentSpec:
    data = {
        "instrument_ref": "instrument:BTCUSDT",
        "asset_class": "crypto_spot",
        "instrument_type": "spot",
        "currency": "USDT",
        "exchange_calendar_ref": "calendar:crypto_24_7",
        "symbol_mapping_ref": "symbol:btc_usdt",
    }
    data.update(overrides)
    return InstrumentSpec(**data)


def _matrix(**overrides) -> MarketCapabilityMatrixRecord:
    data = {
        "matrix_ref": "capability:crypto_spot",
        "asset_class": "crypto_spot",
        "instrument_type": "spot",
        "research": True,
        "backtest": True,
        "paper": True,
        "testnet": True,
        "live": False,
        "long": True,
        "short": False,
        "leverage": False,
        "options": False,
        "margin": False,
        "borrow": False,
        "data_availability": "available",
        "cost_model_availability": "maker_taker",
        "execution_availability": "paper/testnet",
        "permission_requirement": "paper_permission",
    }
    data.update(overrides)
    return MarketCapabilityMatrixRecord(**data)


def _transform(**overrides) -> dict:
    data = {
        "transform_ref": "transform:daily_close",
        "claims_theory_correct": True,
        "formula_ref": "formula:daily_bar_close",
        "unit_binding_ref": "unit:quote_currency",
        "timing_binding_ref": "timing:next_bar_execution",
    }
    data.update(overrides)
    return data


@pytest.fixture()
def market_data_client(tmp_path, monkeypatch):
    registry = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", registry)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="market_user",
        user_id="market_user",
    )
    try:
        yield TestClient(main.app), registry, graph
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def _post_market_data_assets(
    client: TestClient, *, matrix: MarketCapabilityMatrixRecord | None = None
) -> tuple[dict, dict, dict]:
    dataset = client.post(
        "/api/research-os/market_data/datasets",
        json={"use_context": "confirmatory_validation", "dataset": _dataset().to_dict()},
    )
    instrument = client.post(
        "/api/research-os/market_data/instruments",
        json={"instrument": _instrument().to_dict()},
    )
    capability = client.post(
        "/api/research-os/market_data/capability_matrices",
        json={"use_context": "paper", "capability_matrix": (matrix or _matrix()).to_dict()},
    )
    assert dataset.status_code == 200, dataset.text
    assert instrument.status_code == 200, instrument.text
    assert capability.status_code == 200, capability.text
    return dataset.json(), instrument.json(), capability.json()


def _assert_compiler_coverage(body: dict, *, entrypoint_ref: str) -> None:
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == entrypoint_ref
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.research_graph_command_refs == (body["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert compiler_pass.direct_graph_mutation is False
    assert compiler_pass.bypassed_permission is False
    assert compiler_pass.raw_llm_output_embedded_as_ir is False
    assert coverage.silent_mock_fallback_used is False
    assert coverage.raw_payload_persisted is False
    compiled_text = f"{ir.__dict__} {compiler_pass.__dict__} {coverage.__dict__}"
    assert "raw_rows" not in compiled_text
    assert "sk-" not in compiled_text


def test_confirmatory_validation_rejects_dataset_without_pit_semantics():
    decision = validate_dataset_semantics(
        _dataset(known_at_ref=None, effective_at_ref=None, pit_bitemporal_rules_ref=None),
        use_context=ValidationUseContext.CONFIRMATORY_VALIDATION,
    )
    assert not decision.accepted
    assert "dataset_missing_pit_semantics" in _codes(decision)


def test_cross_currency_strategy_requires_base_currency_and_fx_conversion():
    request = MarketDataUseRequest(
        request_ref="strategy:cross_currency",
        use_context=ValidationUseContext.BACKTEST,
        datasets=(_dataset(),),
        instruments=(
            _instrument(instrument_ref="instrument:BTCUSDT", currency="USDT"),
            _instrument(instrument_ref="instrument:SPY", asset_class="equity_us", currency="USD"),
        ),
        capability_matrix=_matrix(),
        capital_record=CrossCurrencyCapitalRecord(base_currency=None, fx_conversion_ref=None),
    )
    decision = validate_market_data_use(request)
    assert not decision.accepted
    assert "cross_currency_capital_missing" in _codes(decision)


def test_option_strategy_requires_expiry_strike_multiplier_and_settlement():
    option = _instrument(
        instrument_ref="instrument:SPY:call",
        asset_class="equity_us_option",
        instrument_type="option",
        currency="USD",
        expiry_ref=None,
        strike_ref=None,
        contract_multiplier_ref=None,
        settlement_ref=None,
    )
    decision = validate_market_data_use(
        MarketDataUseRequest(
            request_ref="strategy:option_missing_terms",
            use_context=ValidationUseContext.BACKTEST,
            datasets=(_dataset(),),
            instruments=(option,),
            capability_matrix=_matrix(asset_class="equity_us_option", instrument_type="option", options=True),
        )
    )
    assert not decision.accepted
    assert "option_semantics_incomplete" in _codes(decision)


def test_live_request_requires_market_capability_permission_and_blocks_a_share_live():
    decision = validate_market_data_use(
        MarketDataUseRequest(
            request_ref="strategy:cn_live",
            use_context=ValidationUseContext.LIVE,
            datasets=(_dataset(),),
            instruments=(
                _instrument(
                    instrument_ref="instrument:600519",
                    asset_class="equity_cn",
                    instrument_type="stock",
                    currency="CNY",
                    exchange_calendar_ref="calendar:sse",
                ),
            ),
            capability_matrix=_matrix(
                matrix_ref="capability:equity_cn",
                asset_class="equity_cn",
                instrument_type="stock",
                live=False,
                permission_requirement=None,
            ),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {"a_share_live_forbidden", "live_capability_missing"}


def test_theory_correct_data_transform_requires_formula_unit_and_timing_binding():
    decision = validate_market_data_use(
        MarketDataUseRequest(
            request_ref="transform:adjusted_close",
            use_context=ValidationUseContext.BACKTEST,
            datasets=(_dataset(),),
            instruments=(_instrument(),),
            capability_matrix=_matrix(),
            transformation_claims=(
                DataTransformationClaim(
                    transform_ref="adjustment:split_dividend",
                    claims_theory_correct=True,
                    formula_ref=None,
                    unit_binding_ref=None,
                    timing_binding_ref=None,
                ),
            ),
        )
    )
    assert not decision.accepted
    assert "transformation_theory_binding_missing" in _codes(decision)


def test_complete_market_data_use_contract_accepts_crypto_paper():
    decision = validate_market_data_use(
        MarketDataUseRequest(
            request_ref="strategy:crypto_paper",
            use_context=ValidationUseContext.PAPER,
            datasets=(_dataset(),),
            instruments=(_instrument(),),
            capability_matrix=_matrix(),
            capital_record=CrossCurrencyCapitalRecord(
                base_currency="USDT",
                fx_conversion_ref="fx:identity_usdt",
            ),
            transformation_claims=(
                DataTransformationClaim(
                    transform_ref="sampling:daily_close",
                    claims_theory_correct=True,
                    formula_ref="formula:daily_bar_close",
                    unit_binding_ref="unit:quote_currency",
                    timing_binding_ref="timing:next_bar_execution",
                ),
            ),
        )
    )
    assert decision.accepted
    assert decision.violations == ()


def test_market_data_registry_replays_append_only_records(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    registry = PersistentMarketDataRegistry(path)
    registry.record_dataset(_dataset(), use_context=ValidationUseContext.CONFIRMATORY_VALIDATION)
    registry.record_instrument(_instrument())
    registry.record_capability_matrix(_matrix(), use_context=ValidationUseContext.PAPER)

    replayed = PersistentMarketDataRegistry(path)

    assert replayed.dataset("dataset:btc_daily:v1").source_ref == "source:binance_vision"
    assert replayed.instrument("instrument:BTCUSDT").exchange_calendar_ref == "calendar:crypto_24_7"
    assert replayed.capability_matrix("capability:crypto_spot").paper is True


def test_market_data_registry_malformed_history_fails_closed(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    path.write_text(
        '{"schema_version":1,"event_type":"dataset_semantics_recorded","dataset":{"dataset_ref":"dataset:bad"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted market data row"):
        PersistentMarketDataRegistry(path)


def test_market_data_api_records_assets_and_qros(market_data_client):
    client, registry, graph = market_data_client

    dataset = client.post(
        "/api/research-os/market_data/datasets",
        json={
            "use_context": "confirmatory_validation",
            "dataset": _dataset().to_dict(),
        },
    )
    instrument = client.post(
        "/api/research-os/market_data/instruments",
        json={"instrument": _instrument().to_dict()},
    )
    capability = client.post(
        "/api/research-os/market_data/capability_matrices",
        json={"use_context": "paper", "capability_matrix": _matrix().to_dict()},
    )

    assert dataset.status_code == 200, dataset.text
    assert instrument.status_code == 200, instrument.text
    assert capability.status_code == 200, capability.text
    assert dataset.json()["raw_data_stored"] is False
    assert instrument.json()["connector_called"] is False
    assert capability.json()["venue_called"] is False
    assert registry.dataset("dataset:btc_daily:v1").version == "v1"
    assert registry.instrument("instrument:BTCUSDT").asset_class == "crypto_spot"
    assert registry.capability_matrix("capability:crypto_spot").testnet is True
    qro_types = {
        str(command.payload["qro"].qro_type.value if hasattr(command.payload["qro"].qro_type, "value") else command.payload["qro"].qro_type)
        for command in graph.commands()
    }
    assert qro_types == {
        QROType.DATASET.value,
        QROType.DATA_SOURCE_ASSET.value,
        QROType.MARKET_CAPABILITY_MATRIX.value,
    }

    summary = client.get("/api/research-os/market_data/summary")
    assert summary.status_code == 200
    assert summary.json()["dataset_total"] == 1
    assert summary.json()["instrument_total"] == 1
    assert summary.json()["capability_matrix_total"] == 1
    assert summary.json()["use_validation_total"] == 0


def test_market_data_api_rejects_invalid_records_without_partial_write(market_data_client):
    client, registry, graph = market_data_client

    bad_dataset = client.post(
        "/api/research-os/market_data/datasets",
        json={
            "use_context": "confirmatory_validation",
            "dataset": _dataset(known_at_ref=None, effective_at_ref=None, pit_bitemporal_rules_ref=None).to_dict(),
        },
    )
    bad_option = client.post(
        "/api/research-os/market_data/instruments",
        json={
            "instrument": _instrument(
                instrument_ref="instrument:SPY:call",
                asset_class="equity_us_option",
                instrument_type="option",
                currency="USD",
                expiry_ref=None,
                strike_ref=None,
                contract_multiplier_ref=None,
                settlement_ref=None,
            ).to_dict()
        },
    )
    bad_live_matrix = client.post(
        "/api/research-os/market_data/capability_matrices",
        json={
            "use_context": "live",
            "capability_matrix": _matrix(live=False, permission_requirement=None).to_dict(),
        },
    )

    assert bad_dataset.status_code == 422
    assert "dataset_missing_pit_semantics" in bad_dataset.text
    assert bad_option.status_code == 422
    assert "option_semantics_incomplete" in bad_option.text
    assert bad_live_matrix.status_code == 422
    assert "live_capability_missing" in bad_live_matrix.text
    assert registry.datasets() == []
    assert registry.instruments() == []
    assert registry.capability_matrices() == []
    assert graph.commands() == []


def test_market_data_api_rejects_raw_payload_and_plaintext_secret_without_write(market_data_client):
    client, registry, graph = market_data_client
    payload = _dataset().to_dict()
    payload["rows"] = [{"close": 100.0}]

    raw_payload = client.post("/api/research-os/market_data/datasets", json={"dataset": payload})
    secret_payload = client.post(
        "/api/research-os/market_data/datasets",
        json={"dataset": {**_dataset().to_dict(), "source_ref": "sk-live-secret-value"}},
    )

    assert raw_payload.status_code == 422
    assert "raw market-data" in raw_payload.text
    assert secret_payload.status_code == 422
    assert "plaintext secret" in secret_payload.text
    assert registry.datasets() == []
    assert graph.commands() == []


def test_market_data_parser_keeps_tuple_refs():
    parsed = dataset_semantics_record_from_dict(_dataset(lineage_refs=["lineage:a", "lineage:b"]).to_dict())
    assert parsed.lineage_refs == ("lineage:a", "lineage:b")


def test_market_data_use_gate_records_accepted_refs_and_qro(market_data_client):
    client, registry, graph = market_data_client
    dataset_body, instrument_body, capability_body = _post_market_data_assets(client)
    _assert_compiler_coverage(dataset_body, entrypoint_ref="api:research_os.market_data.datasets")
    _assert_compiler_coverage(instrument_body, entrypoint_ref="api:research_os.market_data.instruments")
    _assert_compiler_coverage(
        capability_body,
        entrypoint_ref="api:research_os.market_data.capability_matrices",
    )

    response = client.post(
        "/api/research-os/market_data/use_requests",
        json={
            "market_data_use": {
                "request_ref": "strategy:crypto_paper",
                "use_context": "paper",
                "dataset_refs": ["dataset:btc_daily:v1"],
                "instrument_refs": ["instrument:BTCUSDT"],
                "capability_matrix_ref": "capability:crypto_spot",
                "capital_record_ref": "capital:usdt_book",
                "capital_record": {
                    "base_currency": "USDT",
                    "fx_conversion_ref": "fx:identity_usdt",
                },
                "transformation_claims": [_transform()],
            }
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] is True
    assert body["raw_data_stored"] is False
    assert body["strategy_builder_called"] is False
    recorded = registry.use_validation(body["validation_ref"])
    assert recorded.dataset_refs == ("dataset:btc_daily:v1",)
    assert recorded.capability_matrix_ref == "capability:crypto_spot"
    assert len(graph.commands()) == 4
    last_qro = graph.commands()[-1].payload["qro"]
    assert last_qro.output_contract["status"] == "market_data_use_validated"
    assert last_qro.output_contract["connector_called"] is False

    summary = client.get("/api/research-os/market_data/summary")
    assert summary.status_code == 200
    assert summary.json()["use_validation_total"] == 1


def test_market_data_use_gate_rejects_unrecorded_refs_without_write(market_data_client):
    client, registry, graph = market_data_client

    response = client.post(
        "/api/research-os/market_data/use_requests",
        json={
            "market_data_use": {
                "request_ref": "strategy:unknown_data",
                "use_context": "paper",
                "dataset_refs": ["dataset:missing"],
                "instrument_refs": ["instrument:BTCUSDT"],
                "capability_matrix_ref": "capability:crypto_spot",
            }
        },
    )

    assert response.status_code == 422
    assert "unknown dataset semantics record" in response.text
    assert registry.use_validations() == []
    assert graph.commands() == []


def test_market_data_use_gate_rejects_cross_currency_without_capital_no_partial(market_data_client):
    client, registry, graph = market_data_client
    _post_market_data_assets(client)
    spy = client.post(
        "/api/research-os/market_data/instruments",
        json={
            "instrument": _instrument(
                instrument_ref="instrument:SPY",
                asset_class="equity_us",
                instrument_type="stock",
                currency="USD",
                exchange_calendar_ref="calendar:nyse",
            ).to_dict()
        },
    )
    assert spy.status_code == 200, spy.text
    before_commands = len(graph.commands())

    response = client.post(
        "/api/research-os/market_data/use_requests",
        json={
            "market_data_use": {
                "request_ref": "strategy:cross_currency",
                "use_context": "backtest",
                "dataset_refs": ["dataset:btc_daily:v1"],
                "instrument_refs": ["instrument:BTCUSDT", "instrument:SPY"],
                "capability_matrix_ref": "capability:crypto_spot",
            }
        },
    )

    assert response.status_code == 422
    assert "cross_currency_capital_missing" in response.text
    assert registry.use_validations() == []
    assert len(graph.commands()) == before_commands


def test_market_data_use_gate_rejects_live_unavailable_matrix_no_partial(market_data_client):
    client, registry, graph = market_data_client
    _post_market_data_assets(client, matrix=_matrix(live=False, permission_requirement=None))
    before_commands = len(graph.commands())

    response = client.post(
        "/api/research-os/market_data/use_requests",
        json={
            "market_data_use": {
                "request_ref": "strategy:live_without_permission",
                "use_context": "live",
                "dataset_refs": ["dataset:btc_daily:v1"],
                "instrument_refs": ["instrument:BTCUSDT"],
                "capability_matrix_ref": "capability:crypto_spot",
            }
        },
    )

    assert response.status_code == 422
    assert "live_capability_missing" in response.text
    assert registry.use_validations() == []
    assert len(graph.commands()) == before_commands


def test_market_data_use_gate_rejects_raw_rows_without_write(market_data_client):
    client, registry, graph = market_data_client
    _post_market_data_assets(client)
    before_commands = len(graph.commands())

    response = client.post(
        "/api/research-os/market_data/use_requests",
        json={
            "market_data_use": {
                "request_ref": "strategy:raw_rows",
                "use_context": "paper",
                "dataset_refs": ["dataset:btc_daily:v1"],
                "instrument_refs": ["instrument:BTCUSDT"],
                "capability_matrix_ref": "capability:crypto_spot",
                "rows": [{"close": 100.0}],
            }
        },
    )

    assert response.status_code == 422
    assert "raw market-data" in response.text
    assert registry.use_validations() == []
    assert len(graph.commands()) == before_commands
