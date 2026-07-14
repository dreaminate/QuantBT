from __future__ import annotations

import json
import multiprocessing as mp
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
    MarketDataUseValidationRecord,
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentMarketDataRegistry,
    PersistentResearchGraphStore,
    QROType,
    ValidationUseContext,
    dataset_semantics_record_from_dict,
    validate_dataset_semantics,
    validate_market_data_use,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver


_OWNER = "market_user"


def _patch_goal_proof_stores(tmp_path, monkeypatch, *, graph):  # noqa: ANN001
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
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)


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


def _use_validation(*, owner: str = _OWNER, **overrides) -> MarketDataUseValidationRecord:
    data = {
        "validation_ref": "market_data_use:btc_daily:paper",
        "request_ref": "strategy:crypto_paper",
        "use_context": ValidationUseContext.PAPER.value,
        "dataset_refs": ("dataset:btc_daily:v1",),
        "instrument_refs": ("instrument:BTCUSDT",),
        "capability_matrix_ref": "capability:crypto_spot",
        "capital_record_ref": "capital:usdt_book",
        "transformation_refs": ("transform:daily_close",),
        "accepted": True,
        "violation_codes": (),
        "evidence_refs": ("evidence:btc_daily:paper",),
        "recorded_by": owner,
        "created_at_utc": "2026-07-12T00:00:00+00:00",
    }
    data.update(overrides)
    return MarketDataUseValidationRecord(**data)


def _record_market_bundle(registry: PersistentMarketDataRegistry, *, owner: str = _OWNER) -> None:
    registry.record_dataset(
        _dataset(),
        owner_user_id=owner,
        use_context=ValidationUseContext.CONFIRMATORY_VALIDATION,
    )
    registry.record_instrument(_instrument(), owner_user_id=owner)
    registry.record_capability_matrix(
        _matrix(),
        owner_user_id=owner,
        use_context=ValidationUseContext.PAPER,
    )


def _race_record_instrument(path: str, currency: str, start, results) -> None:
    registry = PersistentMarketDataRegistry(path)
    start.wait(timeout=10)
    try:
        registry.record_instrument(
            _instrument(currency=currency),
            owner_user_id="race-owner",
        )
    except Exception as exc:  # noqa: BLE001 - child reports the exact collision outcome.
        results.put((type(exc).__name__, str(exc)))
    else:
        results.put(("ok", ""))


@pytest.fixture()
def market_data_client(tmp_path, monkeypatch):
    registry = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", registry)
    _patch_goal_proof_stores(tmp_path, monkeypatch, graph=graph)
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
    _record_market_bundle(registry)
    registry.record_use_validation(_use_validation(), owner_user_id=_OWNER)

    replayed = PersistentMarketDataRegistry(path)

    assert replayed.dataset("dataset:btc_daily:v1", owner_user_id=_OWNER).source_ref == "source:binance_vision"
    assert replayed.instrument("instrument:BTCUSDT", owner_user_id=_OWNER).exchange_calendar_ref == "calendar:crypto_24_7"
    assert replayed.capability_matrix("capability:crypto_spot", owner_user_id=_OWNER).paper is True
    assert replayed.use_validation(
        "market_data_use:btc_daily:paper",
        owner_user_id=_OWNER,
    ).recorded_by == _OWNER
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert {row["schema_version"] for row in rows} == {2}
    assert {row["owner_user_id"] for row in rows} == {_OWNER}


def test_market_data_registry_quarantines_ownerless_v1_without_inference(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "instrument_spec_recorded",
                "instrument": _instrument().to_dict(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry = PersistentMarketDataRegistry(path)

    assert registry.legacy_quarantined_count == 1
    assert registry.instruments(owner_user_id=_OWNER) == []
    with pytest.raises(KeyError, match="unknown instrument spec"):
        registry.instrument("instrument:BTCUSDT", owner_user_id=_OWNER)


def test_market_data_registry_allows_same_ref_for_distinct_owners(tmp_path):
    registry = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    registry.record_instrument(_instrument(currency="USDT"), owner_user_id="owner-a")
    registry.record_instrument(_instrument(currency="USD"), owner_user_id="owner-b")

    assert registry.instrument("instrument:BTCUSDT", owner_user_id="owner-a").currency == "USDT"
    assert registry.instrument("instrument:BTCUSDT", owner_user_id="owner-b").currency == "USD"
    assert len(registry.instruments(owner_user_id="owner-a")) == 1
    assert len(registry.instruments(owner_user_id="owner-b")) == 1
    with pytest.raises(KeyError, match="unknown instrument spec"):
        registry.instrument("instrument:BTCUSDT", owner_user_id="owner-c")


def test_market_data_use_validation_rejects_foreign_dependencies_without_write(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    registry = PersistentMarketDataRegistry(path)
    _record_market_bundle(registry, owner="owner-a")
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="same-owner dataset"):
        registry.record_use_validation(
            _use_validation(owner="owner-b"),
            owner_user_id="owner-b",
        )

    assert path.read_text(encoding="utf-8") == before
    assert registry.use_validations(owner_user_id="owner-b") == []


def test_market_data_use_validation_rejects_recorded_by_owner_mismatch(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    registry = PersistentMarketDataRegistry(path)
    _record_market_bundle(registry, owner="owner-a")
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="recorded_by must match owner_user_id"):
        registry.record_use_validation(
            _use_validation(owner="owner-b"),
            owner_user_id="owner-a",
        )

    assert path.read_text(encoding="utf-8") == before


def test_market_data_registry_exact_retry_is_idempotent_and_collision_rejects(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    first = PersistentMarketDataRegistry(path)
    second = PersistentMarketDataRegistry(path)
    record = _instrument(currency="USDT")

    first.record_instrument(record, owner_user_id="owner-a")
    second.record_instrument(record, owner_user_id="owner-a")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    with pytest.raises(ValueError, match="record collision"):
        second.record_instrument(
            _instrument(currency="USD"),
            owner_user_id="owner-a",
        )
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert PersistentMarketDataRegistry(path).instrument(
        "instrument:BTCUSDT",
        owner_user_id="owner-a",
    ).currency == "USDT"


def test_market_data_registry_peer_append_is_visible_to_existing_reader(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    reader = PersistentMarketDataRegistry(path)
    writer = PersistentMarketDataRegistry(path)

    writer.record_instrument(_instrument(), owner_user_id="owner-a")

    assert reader.instrument(
        "instrument:BTCUSDT",
        owner_user_id="owner-a",
    ).currency == "USDT"


def test_market_data_registry_read_after_external_corruption_fails_closed(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    reader = PersistentMarketDataRegistry(path)
    writer = PersistentMarketDataRegistry(path)
    writer.record_instrument(_instrument(), owner_user_id="owner-a")
    assert reader.instruments(owner_user_id="owner-a")

    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            '{"schema_version":2,"owner_user_id":"owner-a","event_type":"broken"}\n'
        )

    with pytest.raises(ValueError, match="invalid persisted market data row"):
        reader.instruments(owner_user_id="owner-a")


def test_market_data_registry_two_process_collision_is_atomic(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    results = ctx.Queue()
    processes = [
        ctx.Process(target=_race_record_instrument, args=(str(path), currency, start, results))
        for currency in ("USDT", "USD")
    ]
    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    assert sorted(kind for kind, _ in outcomes) == ["ValueError", "ok"]
    assert any("record collision" in message for kind, message in outcomes if kind == "ValueError")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    persisted = PersistentMarketDataRegistry(path).instrument(
        "instrument:BTCUSDT",
        owner_user_id="race-owner",
    )
    assert persisted.currency in {"USDT", "USD"}


def test_market_data_registry_malformed_history_fails_closed(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    path.write_text(
        '{"schema_version":2,"owner_user_id":"owner-a","event_type":"dataset_semantics_recorded","dataset":{"dataset_ref":"dataset:bad"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted market data row"):
        PersistentMarketDataRegistry(path)


def test_market_data_registry_external_corruption_clears_live_replay_state(tmp_path):
    path = tmp_path / "market_data_assets.jsonl"
    registry = PersistentMarketDataRegistry(path)
    registry.record_instrument(_instrument(), owner_user_id=_OWNER)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"schema_version":2,"owner_user_id":"market_user","event_type":"broken"}\n')

    with pytest.raises(ValueError, match="invalid persisted market data row"):
        registry.record_instrument(
            _instrument(instrument_ref="instrument:ETHUSDT"),
            owner_user_id=_OWNER,
        )

    with pytest.raises(ValueError, match="invalid persisted market data row"):
        registry.instruments(owner_user_id=_OWNER)
    assert registry._instruments == {}


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
    assert registry.dataset("dataset:btc_daily:v1", owner_user_id=_OWNER).version == "v1"
    assert registry.instrument("instrument:BTCUSDT", owner_user_id=_OWNER).asset_class == "crypto_spot"
    assert registry.capability_matrix("capability:crypto_spot", owner_user_id=_OWNER).testnet is True
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


def test_market_data_api_isolates_same_refs_by_authenticated_user(market_data_client):
    client, registry, _graph = market_data_client
    _post_market_data_assets(client)

    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="second_user",
        user_id="second_user",
    )

    summary = client.get("/api/research-os/market_data/summary")
    assert summary.status_code == 200
    assert summary.json()["dataset_total"] == 0
    assert summary.json()["instrument_total"] == 0

    foreign_use = client.post(
        "/api/research-os/market_data/use_requests",
        json={
            "market_data_use": {
                "request_ref": "strategy:foreign_refs",
                "use_context": "paper",
                "dataset_refs": ["dataset:btc_daily:v1"],
                "instrument_refs": ["instrument:BTCUSDT"],
                "capability_matrix_ref": "capability:crypto_spot",
            }
        },
    )
    assert foreign_use.status_code == 422
    assert "unknown dataset semantics record" in foreign_use.text

    second_instrument = client.post(
        "/api/research-os/market_data/instruments",
        json={"instrument": _instrument(currency="USD").to_dict()},
    )
    assert second_instrument.status_code == 200, second_instrument.text
    assert registry.instrument(
        "instrument:BTCUSDT",
        owner_user_id="market_user",
    ).currency == "USDT"
    assert registry.instrument(
        "instrument:BTCUSDT",
        owner_user_id="second_user",
    ).currency == "USD"


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
    assert registry.datasets(owner_user_id=_OWNER) == []
    assert registry.instruments(owner_user_id=_OWNER) == []
    assert registry.capability_matrices(owner_user_id=_OWNER) == []
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
    assert registry.datasets(owner_user_id=_OWNER) == []
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
    recorded = registry.use_validation(body["validation_ref"], owner_user_id=_OWNER)
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
    assert registry.use_validations(owner_user_id=_OWNER) == []
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
    assert registry.use_validations(owner_user_id=_OWNER) == []
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
    assert registry.use_validations(owner_user_id=_OWNER) == []
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
    assert registry.use_validations(owner_user_id=_OWNER) == []
    assert len(graph.commands()) == before_commands
