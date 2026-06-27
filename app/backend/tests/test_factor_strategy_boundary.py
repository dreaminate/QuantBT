from __future__ import annotations

from app.research_os import (
    FactorAssetKind,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    MarketDataUseValidationRecord,
    PersistentSignalValidationRegistry,
    SignalPerformanceValidationRecord,
    SignalProtocolRecord,
    SignalValidationVerdict,
    StrategyBookContract,
    StrategyLegContract,
    StrategySide,
    validate_factor_generator,
    validate_factor_library_entry,
    validate_signal_performance_validation,
    validate_strategy_book,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _factor(**overrides) -> FactorLibraryEntry:
    data = {
        "factor_ref": "factor:momentum:v1",
        "kind": FactorAssetKind.EXPRESSION,
        "ref": "rank(close/ts_mean(close,20))",
        "lifecycle_state": "QUALIFIED",
    }
    data.update(overrides)
    return FactorLibraryEntry(**data)


def _signal(**overrides) -> SignalProtocolRecord:
    data = {
        "signal_ref": "sig::gbdt_momentum",
        "source_model_ref": "registry://models/gbdt_momentum.pkl",
        "oof": True,
        "purge": True,
        "embargo": True,
        "train_test_lock_ref": "split_lock:001",
        "honest_n_ref": "honest_n:001",
        "forecast_time_ref": "time:prediction_asof",
        "prediction_horizon_ref": "horizon:5d",
        "unit_ref": "unit:expected_return",
        "direction_semantics_ref": "direction:signed_score",
        "confidence_ref": "confidence:model_score_quantile",
        "expires_at_ref": "expiry:next_rebalance",
    }
    data.update(overrides)
    return SignalProtocolRecord(**data)


def _book(**overrides) -> StrategyBookContract:
    data = {
        "strategy_book_ref": "strategy_book:momentum_pair",
        "factor_refs": ("factor:momentum:v1",),
        "signal_refs": ("sig::gbdt_momentum",),
        "legs": (
            StrategyLegContract(
                intent_ref="leg:long_btc",
                side=StrategySide.LONG,
                instrument_ref="instrument:BTCUSDT",
                venue_ref="venue:binance_paper",
                permission_check_ref="permission:paper",
            ),
        ),
        "mathematical_refs": ("math:payoff",),
        "theory_binding_refs": ("binding:strategy_payoff",),
        "run_config_binding_refs": ("run_config:strategy_payoff",),
    }
    data.update(overrides)
    return StrategyBookContract(**data)


def _signal_validation(**overrides) -> SignalPerformanceValidationRecord:
    data = {
        "signal_ref": "sig::gbdt_momentum",
        "validation_dataset_ref": "dataset_version:btc_daily:v2",
        "evaluation_window_ref": "window:oos_2025q4",
        "methodology_ref": "methodology:cpcv_walkforward",
        "metric_refs": ("metric:rank_ic", "metric:dsr", "metric:pbo"),
        "performance_summary_ref": "signal_perf:gbdt_momentum:oos_2025q4",
        "leakage_check_ref": "leakage_check:oof_purge_embargo:001",
        "evidence_refs": ("evidence:signal_perf_report",),
        "verdict": SignalValidationVerdict.ACCEPTED,
        "regime_check_ref": "regime:crypto_trend",
        "capacity_check_ref": "capacity:paper_only",
        "known_limits_refs": ("limit:not_alpha_proof",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return SignalPerformanceValidationRecord(**data)


def _market_data_use_validation(**overrides) -> MarketDataUseValidationRecord:
    data = {
        "validation_ref": "market_data_use:btc_paper_accepted",
        "request_ref": "market_data_request:btc_paper",
        "use_context": "paper",
        "dataset_refs": ("dataset:btc_daily:v2",),
        "instrument_refs": ("instrument:BTCUSDT",),
        "capability_matrix_ref": "capability:crypto_spot:paper",
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


def test_factor_generator_rejects_gate_metric_in_fitness():
    spec = FactorGeneratorSpec(
        generator_ref="generator:formula_search",
        structure_inputs=("complexity", "novelty"),
        fitness_inputs=("novelty", "ic", "sharpe"),
        gatekeeper_ref="gatekeeper:factor_audit",
    )
    decision = validate_factor_generator(spec)
    assert not decision.accepted
    assert "gate_metric_in_generator_fitness" in _codes(decision)


def test_model_body_cannot_be_registered_as_factor_library_entry():
    decision = validate_factor_library_entry(
        _factor(kind=FactorAssetKind.MODEL_BODY, ref="registry://models/tcn_alpha.pt")
    )
    assert not decision.accepted
    assert _codes(decision) >= {"model_body_in_factor_library", "model_body_ref_in_factor_library"}


def test_strategy_book_short_intent_requires_execution_checks():
    short_leg = StrategyLegContract(
        intent_ref="leg:short_equity",
        side=StrategySide.SHORT,
        instrument_ref="instrument:AAPL",
        expected_pnl_ref="pnl:short_thesis",
        venue_ref=None,
        borrow_check_ref=None,
        margin_check_ref=None,
    )
    decision = validate_strategy_book(
        _book(legs=(short_leg,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
    )
    assert not decision.accepted
    assert "short_intent_missing_execution_checks" in _codes(decision)


def test_retired_factor_cannot_be_default_adopted_by_new_strategy():
    retired = _factor(lifecycle_state="RETIRED", adopted_by_default=True)
    decision = validate_strategy_book(
        _book(default_factor_refs=("factor:momentum:v1",)),
        factor_library={"factor:momentum:v1": retired},
        signal_protocols={"sig::gbdt_momentum": _signal()},
    )
    assert not decision.accepted
    assert "retired_factor_default_adoption" in _codes(decision)


def test_strategy_math_refs_require_run_config_binding():
    decision = validate_strategy_book(
        _book(theory_binding_refs=(), run_config_binding_refs=()),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
    )
    assert not decision.accepted
    assert "strategy_math_without_run_config_binding" in _codes(decision)


def test_ml_signal_usage_requires_oof_purge_embargo_lock_and_honest_n():
    incomplete = _signal(oof=True, purge=False, embargo=True, train_test_lock_ref=None, honest_n_ref=None)
    decision = validate_strategy_book(
        _book(),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": incomplete},
    )
    assert not decision.accepted
    assert "signal_protocol_incomplete" in _codes(decision)


def test_ml_signal_usage_requires_expiry_and_direction_semantics():
    incomplete = _signal(expires_at_ref=None, direction_semantics_ref=None)
    decision = validate_strategy_book(
        _book(),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": incomplete},
    )
    assert not decision.accepted
    assert "signal_protocol_incomplete" in _codes(decision)


def test_signal_validation_requires_refs_metrics_and_evidence():
    incomplete = _signal_validation(
        validation_dataset_ref="",
        metric_refs=(),
        evidence_refs=(),
        leakage_check_ref="",
    )
    decision = validate_signal_performance_validation(incomplete, known_signal_refs={"sig::gbdt_momentum"})
    assert not decision.accepted
    assert _codes(decision) >= {
        "signal_validation_missing_required_ref",
        "signal_validation_missing_metric_refs",
        "signal_validation_missing_evidence_refs",
    }


def test_signal_validation_registry_persists_and_replays(tmp_path):
    path = tmp_path / "signal_validations.jsonl"
    registry = PersistentSignalValidationRegistry(path)
    record = registry.record_validation(_signal_validation(), known_signal_refs={"sig::gbdt_momentum"})

    reloaded = PersistentSignalValidationRegistry(path)

    assert reloaded.validation(record.validation_id).signal_ref == "sig::gbdt_momentum"
    assert reloaded.accepted_for_signal("sig::gbdt_momentum")[0].validation_id == record.validation_id


def test_strategy_book_requires_accepted_signal_validation_when_enabled():
    accepted = _signal_validation()
    decision = validate_strategy_book(
        _book(signal_validation_refs=(accepted.validation_id,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        signal_validations={accepted.validation_id: accepted},
        require_signal_validation=True,
    )
    assert decision.accepted


def test_strategy_book_rejects_missing_or_rejected_signal_validation_when_required():
    missing = validate_strategy_book(
        _book(signal_validation_refs=()),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        signal_validations={},
        require_signal_validation=True,
    )
    assert not missing.accepted
    assert "missing_signal_performance_validation" in _codes(missing)

    rejected = _signal_validation(verdict=SignalValidationVerdict.REJECTED)
    bad = validate_strategy_book(
        _book(signal_validation_refs=(rejected.validation_id,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        signal_validations={rejected.validation_id: rejected},
        require_signal_validation=True,
    )
    assert not bad.accepted
    assert _codes(bad) >= {"signal_validation_not_accepted", "missing_signal_performance_validation"}


def test_strategy_book_requires_accepted_market_data_use_validation_when_enabled():
    accepted = _market_data_use_validation()
    decision = validate_strategy_book(
        _book(market_data_use_validation_refs=(accepted.validation_ref,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        market_data_use_validations={accepted.validation_ref: accepted},
        require_market_data_use_validation=True,
    )
    assert decision.accepted


def test_strategy_book_rejects_missing_or_unknown_market_data_use_validation_when_required():
    missing = validate_strategy_book(
        _book(market_data_use_validation_refs=()),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        market_data_use_validations={},
        require_market_data_use_validation=True,
    )
    assert not missing.accepted
    assert "missing_market_data_use_validation" in _codes(missing)

    unknown = validate_strategy_book(
        _book(market_data_use_validation_refs=("market_data_use:missing",)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        market_data_use_validations={},
        require_market_data_use_validation=True,
    )
    assert not unknown.accepted
    assert _codes(unknown) >= {
        "missing_market_data_use_validation_record",
        "missing_market_data_use_validation",
    }


def test_strategy_book_rejects_market_data_use_validation_that_does_not_cover_leg_instrument():
    accepted = _market_data_use_validation(
        validation_ref="market_data_use:eth_paper_accepted",
        instrument_refs=("instrument:ETHUSDT",),
    )
    decision = validate_strategy_book(
        _book(market_data_use_validation_refs=(accepted.validation_ref,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        market_data_use_validations={accepted.validation_ref: accepted},
        require_market_data_use_validation=True,
    )
    assert not decision.accepted
    assert "missing_market_data_use_validation" in _codes(decision)


def test_strategy_book_rejects_unaccepted_market_data_use_validation_when_required():
    rejected = _market_data_use_validation(
        validation_ref="market_data_use:btc_rejected",
        accepted=False,
        violation_codes=("market_data_use_live_matrix_unavailable",),
    )
    decision = validate_strategy_book(
        _book(market_data_use_validation_refs=(rejected.validation_ref,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
        market_data_use_validations={rejected.validation_ref: rejected},
        require_market_data_use_validation=True,
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "market_data_use_not_accepted",
        "market_data_use_has_violations",
        "missing_market_data_use_validation",
    }


def test_strategy_book_accepts_complete_factor_signal_short_and_math_contracts():
    short_leg = StrategyLegContract(
        intent_ref="leg:short_perp",
        side=StrategySide.SHORT,
        instrument_ref="instrument:BTCUSDT_PERP",
        expected_pnl_ref="pnl:funding_short",
        venue_ref="venue:binance_testnet",
        borrow_check_ref="borrow:perp_available",
        margin_check_ref="margin:isolated_cap",
        regulation_check_ref="regulation:crypto_derivatives_allowed",
        permission_check_ref="permission:testnet_confirmed",
    )
    decision = validate_strategy_book(
        _book(legs=(short_leg,)),
        factor_library={"factor:momentum:v1": _factor()},
        signal_protocols={"sig::gbdt_momentum": _signal()},
    )
    assert decision.accepted
    assert decision.violations == ()
