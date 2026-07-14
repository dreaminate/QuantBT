from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency

from app.research_os import (
    CrossCurrencyCapitalRecord,
    DataTransformationClaim,
    DatasetSemanticsRecord,
    GoalSectionSemanticProofRecord,
    InstrumentSpec,
    MarketCapabilityMatrixRecord,
    MarketDataUseValidationRecord,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentMarketDataRegistry,
    PersistentResearchGraphStore,
    build_real_platform_coverage_resolver,
    goal_section_semantic_proof_identity,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.market_coverage import (
    MARKET_COVERAGE_ENTRYPOINT_REF,
    MARKET_FAMILY_REQUIRED_FIELDS,
    REQUIRED_MARKET_FAMILIES,
    MarketCapitalStateRecord,
    MarketCoverageCommitUncertain,
    MarketCoverageError,
    MarketCoverageSectionAdapter,
    MarketInstrumentSemanticsRecord,
    MarketTransformationStateRecord,
    PersistentMarketCoverageRegistry,
    market_coverage_semantic_material,
)


OWNER = "market-owner"
CAPITAL_REF = "capital:global_book"
TRANSFORM_REF = "transform:daily_adjusted_close"


def _dataset() -> DatasetSemanticsRecord:
    return DatasetSemanticsRecord(
        dataset_ref="dataset:global:daily:v1",
        source_ref="source:licensed_global_feed",
        version="v1",
        known_at_ref="known_at:vendor_publish_time",
        effective_at_ref="effective_at:exchange_event_time",
        pit_bitemporal_rules_ref="pit:global_daily:v1",
        quality_status="passed",
        lineage_refs=("lineage:licensed_global_feed:v1",),
        freshness_status="current",
        checksum="sha256:" + "a" * 64,
        sampling_rule_ref="sampling:daily_close:v1",
        adjustment_formula_ref="formula:corporate_action_adjustment:v1",
        asof_join_rule_ref="asof:known_before_decision:v1",
        missingness_model_ref="missingness:explicit_gap:v1",
        survivorship_rule_ref="survivorship:point_in_time_universe:v1",
    )


def _instrument(family: str) -> InstrumentSpec:
    common = {
        "instrument_ref": f"instrument:{family}:canonical",
        "asset_class": family,
        "instrument_type": family,
        "currency": "USD",
        "exchange_calendar_ref": f"calendar:{family}:primary",
        "contract_spec_ref": f"contract:{family}:v1",
        "symbol_mapping_ref": f"symbol:{family}:canonical",
    }
    if family == "option":
        common.update(
            asset_class="options",
            option_chain_ref="option_chain:listed:v1",
            expiry_ref="expiry:listed:v1",
            strike_ref="strike:listed:v1",
            contract_multiplier_ref="multiplier:listed:v1",
            settlement_ref="settlement:cash:v1",
            exercise_style_ref="exercise:european:v1",
            margin_ref="margin:option:v1",
        )
    elif family == "future":
        common.update(
            asset_class="futures",
            instrument_type="future",
            futures_roll_rule_ref="roll:volume_open_interest:v1",
            continuous_contract_rule_ref="continuous:ratio_adjusted:v1",
            contract_multiplier_ref="multiplier:future:v1",
            settlement_ref="settlement:physical:v1",
            margin_ref="margin:future:v1",
        )
    elif family == "bond":
        common.update(asset_class="bond", instrument_type="bond")
    elif family == "fx":
        common.update(asset_class="fx", instrument_type="fx", currency="EUR")
    elif family == "commodity":
        common.update(
            asset_class="commodity",
            instrument_type="future",
            futures_roll_rule_ref="roll:commodity:v1",
            continuous_contract_rule_ref="continuous:commodity:v1",
            contract_multiplier_ref="multiplier:commodity:v1",
            settlement_ref="settlement:physical:v1",
            margin_ref="margin:commodity:v1",
        )
    return InstrumentSpec(**common)


def _matrix(family: str, *, context: str) -> MarketCapabilityMatrixRecord:
    instrument = _instrument(family)
    return MarketCapabilityMatrixRecord(
        matrix_ref=f"capability:{family}:v1",
        asset_class=instrument.asset_class,
        instrument_type=instrument.instrument_type,
        research=True,
        backtest=True,
        paper=True,
        testnet=True,
        live=False,
        long=True,
        short=True,
        leverage=family in {"option", "future", "fx", "commodity"},
        options=family == "option",
        margin=family in {"option", "future", "fx", "commodity"},
        borrow=family in {"bond", "fx"},
        data_availability="licensed_current",
        cost_model_availability="family_specific_current",
        execution_availability="paper_testnet_only",
        permission_requirement=f"market:{family}:{context}",
    )


def _capital(*, revision: str = "v1", financing_ref: str = "financing:global:v1") -> MarketCapitalStateRecord:
    return MarketCapitalStateRecord(
        capital_ref=CAPITAL_REF,
        revision=revision,
        known_at=f"known_at:capital:{revision}",
        effective_at=f"effective_at:capital:{revision}",
        freshness_status="current",
        capital=CrossCurrencyCapitalRecord(
            base_currency="USD",
            fx_conversion_ref="fx_conversion:global:v1",
            collateral_ref="collateral:global:v1",
            margin_ref="margin:global:v1",
            leverage_ref="leverage:global:v1",
            net_exposure_ref="exposure:net:v1",
            gross_exposure_ref="exposure:gross:v1",
            capital_allocation_ref="allocation:global:v1",
            financing_cost_ref=financing_ref,
        ),
    )


def _transformation(*, revision: str = "v1", formula_ref: str = "formula:daily_adjusted_close:v1") -> MarketTransformationStateRecord:
    return MarketTransformationStateRecord(
        transform_ref=TRANSFORM_REF,
        revision=revision,
        known_at=f"known_at:transform:{revision}",
        effective_at=f"effective_at:transform:{revision}",
        freshness_status="current",
        claim=DataTransformationClaim(
            transform_ref=TRANSFORM_REF,
            claims_theory_correct=True,
            formula_ref=formula_ref,
            unit_binding_ref="unit:price_quote_currency:v1",
            timing_binding_ref="timing:next_bar_execution:v1",
        ),
    )


def _race_record_transformation(ledger_path: str, market_path: str, index: int, start, results) -> None:
    transform_ref = f"transform:race:{index}"
    registry = PersistentMarketCoverageRegistry(
        ledger_path,
        PersistentMarketDataRegistry(market_path),
    )
    record = MarketTransformationStateRecord(
        transform_ref=transform_ref,
        revision="v1",
        known_at=f"known_at:race:{index}",
        effective_at=f"effective_at:race:{index}",
        freshness_status="current",
        claim=DataTransformationClaim(
            transform_ref=transform_ref,
            claims_theory_correct=True,
            formula_ref=f"formula:race:{index}",
            unit_binding_ref=f"unit:race:{index}",
            timing_binding_ref=f"timing:race:{index}",
        ),
    )
    start.wait(timeout=10)
    try:
        registry.record_transformation(record, owner_user_id=OWNER)
    except Exception as exc:  # noqa: BLE001 - child reports the exact failure.
        results.put((type(exc).__name__, str(exc)))
    else:
        results.put(("ok", transform_ref))


def _semantics(
    family: str,
    *,
    revision: str = "v1",
    instrument_family: str | None = None,
) -> MarketInstrumentSemanticsRecord:
    target_family = instrument_family or family
    semantics_ref = f"instrument_semantics:{family}:canonical"
    if target_family != family:
        semantics_ref = f"instrument_semantics:{target_family}:{family}:canonical"
    return MarketInstrumentSemanticsRecord(
        semantics_ref=semantics_ref,
        revision=revision,
        known_at=f"known_at:semantics:{family}:{revision}",
        effective_at=f"effective_at:semantics:{family}:{revision}",
        freshness_status="current",
        instrument_ref=_instrument(target_family).instrument_ref,
        market_family=family,
        semantic_fields=tuple(
            (field_name, f"{field_name.removesuffix('_ref')}:{family}:{revision}")
            for field_name in sorted(MARKET_FAMILY_REQUIRED_FIELDS[family])
        ),
    )


def _semantic_records() -> tuple[MarketInstrumentSemanticsRecord, ...]:
    return (
        *(_semantics(family) for family in sorted(REQUIRED_MARKET_FAMILIES)),
        _semantics("future", instrument_family="commodity"),
    )


def _record_market_data(
    registry: PersistentMarketDataRegistry,
    *,
    dataset: DatasetSemanticsRecord | None = None,
    contexts: tuple[str, ...] = (
        "research",
        "backtest",
        "confirmatory_validation",
        "paper",
        "testnet",
    ),
) -> tuple[str, ...]:
    dataset = dataset or _dataset()
    registry.record_dataset(
        dataset,
        owner_user_id=OWNER,
        use_context="confirmatory_validation",
    )
    validation_refs: list[str] = []
    for family in sorted(REQUIRED_MARKET_FAMILIES):
        instrument = _instrument(family)
        matrix = _matrix(family, context="research")
        registry.record_instrument(instrument, owner_user_id=OWNER)
        registry.record_capability_matrix(
            matrix,
            owner_user_id=OWNER,
            use_context="research",
        )
        for context in contexts:
            validation_ref = f"market_data_use:{family}:{context}:v1"
            registry.record_use_validation(
                MarketDataUseValidationRecord(
                    validation_ref=validation_ref,
                    request_ref=f"strategy:{family}:{context}:coverage",
                    use_context=context,
                    dataset_refs=(dataset.dataset_ref,),
                    instrument_refs=(instrument.instrument_ref,),
                    capability_matrix_ref=matrix.matrix_ref,
                    capital_record_ref=CAPITAL_REF,
                    transformation_refs=(TRANSFORM_REF,),
                    accepted=True,
                    violation_codes=(),
                    evidence_refs=(f"evidence:market_coverage:{family}:{context}:v1",),
                    recorded_by=OWNER,
                    created_at_utc="2026-07-12T20:00:00+00:00",
                ),
                owner_user_id=OWNER,
            )
            validation_refs.append(validation_ref)
    return tuple(validation_refs)


def _build_current(tmp_path):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    use_refs = _record_market_data(market_registry)
    coverage_registry = PersistentMarketCoverageRegistry(
        tmp_path / "market_coverage.jsonl",
        market_registry,
    )
    coverage_registry.record_capital(_capital(), owner_user_id=OWNER)
    coverage_registry.record_transformation(_transformation(), owner_user_id=OWNER)
    semantic_records = _semantic_records()
    for record in semantic_records:
        coverage_registry.record_instrument_semantics(record, owner_user_id=OWNER)
    receipt = coverage_registry.record_current(
        owner_user_id=OWNER,
        use_validation_refs=use_refs,
        capital_record_ref=CAPITAL_REF,
        transformation_refs=(TRANSFORM_REF,),
        instrument_semantics_refs=tuple(record.semantics_ref for record in semantic_records),
    )
    return market_registry, coverage_registry, receipt


def test_market_coverage_receipt_replays_hash_chain_and_remains_current(tmp_path):
    market_registry, registry, receipt = _build_current(tmp_path)

    assert receipt.receipt_ref == receipt.canonical_receipt_ref
    assert registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted
    assert set(receipt.snapshot.market_families) == set(REQUIRED_MARKET_FAMILIES)
    assert set(receipt.snapshot.use_contexts) == {
        "research",
        "backtest",
        "confirmatory_validation",
        "paper",
        "testnet",
    }

    rows = [json.loads(line) for line in registry.path.read_text(encoding="utf-8").splitlines()]
    previous = None
    for row in rows:
        assert row["schema_version"] == 2
        assert row["owner_user_id"] == OWNER
        assert row["previous_record_hash"] == previous
        body = {key: value for key, value in row.items() if key != "record_hash"}
        import hashlib

        expected = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert row["record_hash"] == f"sha256:{expected}"
        previous = row["record_hash"]
    assert os.stat(registry.path).st_mode & 0o777 == 0o600

    replayed = PersistentMarketCoverageRegistry(registry.path, market_registry)
    assert replayed.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    assert replayed.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted


def test_market_coverage_api_records_state_and_current_section11_lineage(
    tmp_path,
    monkeypatch,
):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    use_refs = _record_market_data(market_registry)
    coverage_registry = PersistentMarketCoverageRegistry(
        tmp_path / "market_coverage.jsonl",
        market_registry,
    )
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
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
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        resolver=build_real_platform_coverage_resolver(
            research_graph_store=graph,
            lifecycle_registry=main.ASSET_LIFECYCLE_REGISTRY,
            governance_registry=main.MODEL_GOVERNANCE_REGISTRY,
            rag_index=main.RESEARCH_ASSET_RAG_INDEX,
            spine_chain_registry=main.MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            compiler_store=compiler,
            document_store=main.DOCUMENT_INTELLIGENCE_STORE,
            goal_validation_receipt_registry=validations,
        ),
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_registry)
    monkeypatch.setattr(main, "MARKET_COVERAGE_REGISTRY", coverage_registry)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", entrypoints)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username=OWNER,
        user_id=OWNER,
    )
    client = TestClient(main.app)
    try:
        capital = client.post(
            "/api/research-os/market_coverage/capital_states",
            json={"market_capital_state": asdict(_capital())},
        )
        assert capital.status_code == 200, capital.text
        assert capital.json()["recorded_by"] == OWNER

        transformation = client.post(
            "/api/research-os/market_coverage/transformation_states",
            json={"market_transformation_state": asdict(_transformation())},
        )
        assert transformation.status_code == 200, transformation.text
        semantics = _semantic_records()
        for record in semantics:
            response = client.post(
                "/api/research-os/market_coverage/instrument_semantics",
                json={"market_instrument_semantics": asdict(record)},
            )
            assert response.status_code == 200, response.text

        current = client.post(
            "/api/research-os/goal/market_coverage/current",
            json={
                "use_validation_refs": list(use_refs),
                "capital_record_ref": CAPITAL_REF,
                "transformation_refs": [TRANSFORM_REF],
                "instrument_semantics_refs": [
                    record.semantics_ref for record in semantics
                ],
            },
        )
        assert current.status_code == 200, current.text
        body = current.json()
        assert set(body["market_families"]) == set(REQUIRED_MARKET_FAMILIES)
        assert body["entrypoint_coverage_ref"].startswith(
            "goal_entrypoint_coverage:"
        )
        receipt = coverage_registry.receipt(
            body["receipt_ref"], owner_user_id=OWNER
        )
        assert coverage_registry.validate_current(
            receipt.receipt_ref, owner_user_id=OWNER
        ).accepted
        coverage = entrypoints.canonical_coverage(
            body["entrypoint_coverage_ref"],
            owner=OWNER,
        )
        assert coverage.entrypoint_ref == MARKET_COVERAGE_ENTRYPOINT_REF
        assert coverage.goal_sections == ("§11",)
        assert len(coverage.validation_refs) == 1
        compiler_validation = validations.receipt(
            coverage.validation_refs[0],
            owner_user_id=OWNER,
        )
        assert receipt.receipt_ref in compiler_validation.evidence_refs

        summary = client.get("/api/research-os/goal/market_coverage")
        assert summary.status_code == 200
        assert summary.json()["receipt_total"] == 1
        assert summary.json()["receipts"][0]["current"] is True

        extra = client.post(
            "/api/research-os/goal/market_coverage/current",
            json={
                "use_validation_refs": list(use_refs),
                "capital_record_ref": CAPITAL_REF,
                "transformation_refs": [TRANSFORM_REF],
                "instrument_semantics_refs": [
                    record.semantics_ref for record in semantics
                ],
                "caller_claim": "must-not-be-accepted",
            },
        )
        assert extra.status_code == 422
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_market_coverage_does_not_auto_seed_missing_refs_or_write_partial_receipt(tmp_path):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    use_refs = _record_market_data(market_registry)
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)
    registry.record_capital(_capital(), owner_user_id=OWNER)
    before = registry.path.read_bytes()

    with pytest.raises(MarketCoverageError, match="transformation_ref"):
        registry.record_current(
            owner_user_id=OWNER,
            use_validation_refs=use_refs,
            capital_record_ref=CAPITAL_REF,
            transformation_refs=(TRANSFORM_REF,),
            instrument_semantics_refs=tuple(
                f"instrument_semantics:{family}:canonical"
                for family in sorted(REQUIRED_MARKET_FAMILIES)
            ),
        )

    assert registry.path.read_bytes() == before
    assert registry.receipts(owner_user_id=OWNER) == ()


def test_market_coverage_rejects_incomplete_use_contexts_before_append(tmp_path):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    use_refs = _record_market_data(
        market_registry,
        contexts=("research", "backtest", "confirmatory_validation", "paper"),
    )
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)
    registry.record_capital(_capital(), owner_user_id=OWNER)
    registry.record_transformation(_transformation(), owner_user_id=OWNER)
    semantic_records = _semantic_records()
    for record in semantic_records:
        registry.record_instrument_semantics(record, owner_user_id=OWNER)
    before = registry.path.read_bytes()

    with pytest.raises(MarketCoverageError, match="every required environment"):
        registry.record_current(
            owner_user_id=OWNER,
            use_validation_refs=use_refs,
            capital_record_ref=CAPITAL_REF,
            transformation_refs=(TRANSFORM_REF,),
            instrument_semantics_refs=tuple(record.semantics_ref for record in semantic_records),
        )

    assert registry.path.read_bytes() == before
    assert registry.receipts(owner_user_id=OWNER) == ()


def test_market_coverage_rejects_cross_owner_refs_without_receipt_write(tmp_path):
    market_registry, registry, _receipt = _build_current(tmp_path)
    before = registry.path.read_bytes()
    use_refs = tuple(
        record.validation_ref for record in market_registry.use_validations(owner_user_id=OWNER)
    )

    with pytest.raises(MarketCoverageError, match="owner"):
        registry.record_current(
            owner_user_id="other-owner",
            use_validation_refs=use_refs,
            capital_record_ref=CAPITAL_REF,
            transformation_refs=(TRANSFORM_REF,),
            instrument_semantics_refs=tuple(
                f"instrument_semantics:{family}:canonical"
                for family in sorted(REQUIRED_MARKET_FAMILIES)
            ),
        )

    assert registry.path.read_bytes() == before
    assert registry.receipts(owner_user_id="other-owner") == ()


def test_market_coverage_receipt_fails_when_capital_or_registry_record_drifts(tmp_path):
    market_registry, registry, receipt = _build_current(tmp_path)
    registry.record_capital(
        _capital(revision="v2", financing_ref="financing:global:v2"),
        owner_user_id=OWNER,
    )
    decision = registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER)
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {"market_coverage_current_state_drifted"}

    # Rebuild a current receipt, then mutate one canonical market-data row.  The
    # existing market registry has no row hash, so the coverage receipt must be
    # the layer that detects this ref-state drift.
    current = registry.record_current(
        owner_user_id=OWNER,
        use_validation_refs=receipt.use_validation_refs,
        capital_record_ref=CAPITAL_REF,
        transformation_refs=receipt.transformation_refs,
        instrument_semantics_refs=receipt.instrument_semantics_refs,
    )
    path = market_registry.path
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row.get("event_type") == "market_data_use_validation_recorded":
            row["use_validation"]["evidence_refs"] = ["evidence:market_coverage:drifted"]
            break
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    drifted = registry.validate_current(current.receipt_ref, owner_user_id=OWNER)
    assert not drifted.accepted
    assert {item.code for item in drifted.violations} == {"market_coverage_current_state_drifted"}


def test_market_coverage_rejects_incomplete_capital_transform_and_family_fields(tmp_path):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)

    with pytest.raises(MarketCoverageError, match="market_capital_semantics_incomplete"):
        registry.record_capital(
            replace(_capital(), capital=replace(_capital().capital, margin_ref=None)),
            owner_user_id=OWNER,
        )
    with pytest.raises(MarketCoverageError, match="market_transformation_binding"):
        registry.record_transformation(
            _transformation(formula_ref=""),
            owner_user_id=OWNER,
        )
    option = _semantics("option")
    with pytest.raises(MarketCoverageError, match="market_instrument_semantics_inexact"):
        registry.record_instrument_semantics(
            replace(option, semantic_fields=option.semantic_fields[:-1]),
            owner_user_id=OWNER,
        )
    assert not registry.path.exists()


def test_market_coverage_rejects_placeholder_pit_refs_without_receipt_write(tmp_path):
    dataset = replace(
        _dataset(),
        known_at_ref="fixture:known_at",
        effective_at_ref="placeholder:effective_at",
        pit_bitemporal_rules_ref="goal_closure:pit_rules",
    )
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    use_refs = _record_market_data(market_registry, dataset=dataset)
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)
    registry.record_capital(_capital(), owner_user_id=OWNER)
    registry.record_transformation(_transformation(), owner_user_id=OWNER)
    semantic_records = _semantic_records()
    for record in semantic_records:
        registry.record_instrument_semantics(record, owner_user_id=OWNER)
    before = registry.path.read_bytes()

    with pytest.raises(ValueError, match="cannot be synthetic"):
        registry.record_current(
            owner_user_id=OWNER,
            use_validation_refs=use_refs,
            capital_record_ref=CAPITAL_REF,
            transformation_refs=(TRANSFORM_REF,),
            instrument_semantics_refs=tuple(record.semantics_ref for record in semantic_records),
        )

    assert registry.path.read_bytes() == before
    assert registry.receipts(owner_user_id=OWNER) == ()


def test_market_coverage_quarantines_legacy_and_poisoned_hash_chain(tmp_path):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    path = tmp_path / "market_coverage.jsonl"
    path.write_text(json.dumps({"schema_version": 1, "owner": "legacy"}) + "\n", encoding="utf-8")
    registry = PersistentMarketCoverageRegistry(path, market_registry)
    assert registry.legacy_quarantined_count == 1
    assert registry.corrupt_quarantined_count == 0
    registry.record_capital(_capital(), owner_user_id=OWNER)

    rows = path.read_text(encoding="utf-8").splitlines()
    current = json.loads(rows[-1])
    current["payload"]["capital"]["margin_ref"] = "margin:tampered"
    rows[-1] = json.dumps(current)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    poisoned = PersistentMarketCoverageRegistry(path, market_registry)
    assert poisoned.legacy_quarantined_count == 1
    assert poisoned.corrupt_quarantined_count == 1
    assert poisoned.poisoned is True
    with pytest.raises(MarketCoverageError, match="corrupt"):
        poisoned.record_transformation(_transformation(), owner_user_id=OWNER)


def test_market_coverage_atomic_replace_failure_leaves_journal_unchanged(tmp_path, monkeypatch):
    from app.research_os import market_coverage as module

    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)
    registry.record_capital(_capital(), owner_user_id=OWNER)
    before = registry.path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        registry.record_transformation(_transformation(), owner_user_id=OWNER)

    assert registry.path.read_bytes() == before


def test_market_coverage_directory_fsync_failure_reports_visible_uncertain_commit(
    tmp_path, monkeypatch
):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)
    registry.record_capital(_capital(), owner_user_id=OWNER)
    original_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync failed")
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    with pytest.raises(MarketCoverageCommitUncertain, match="commit is visible"):
        registry.record_transformation(_transformation(), owner_user_id=OWNER)

    monkeypatch.setattr(os, "fsync", original_fsync)
    replayed = PersistentMarketCoverageRegistry(registry.path, market_registry)
    assert not replayed.poisoned
    assert replayed.record_transformation(_transformation(), owner_user_id=OWNER) == _transformation()


def test_market_coverage_receipt_append_holds_market_registry_writer_lock(tmp_path, monkeypatch):
    market_registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    use_refs = _record_market_data(market_registry)
    registry = PersistentMarketCoverageRegistry(tmp_path / "market_coverage.jsonl", market_registry)
    registry.record_capital(_capital(), owner_user_id=OWNER)
    registry.record_transformation(_transformation(), owner_user_id=OWNER)
    semantic_records = _semantic_records()
    for record in semantic_records:
        registry.record_instrument_semantics(record, owner_user_id=OWNER)

    writer_started = threading.Event()
    writer_done = threading.Event()
    writer_errors: list[Exception] = []

    def write_new_dataset() -> None:
        writer_started.set()
        try:
            market_registry.record_dataset(
                replace(_dataset(), dataset_ref="dataset:late_writer:v1"),
                owner_user_id=OWNER,
                use_context="confirmatory_validation",
            )
        except Exception as exc:  # noqa: BLE001 - captured for the parent assertion.
            writer_errors.append(exc)
        finally:
            writer_done.set()

    original_record_unlocked = registry._record_unlocked
    writer: threading.Thread | None = None

    def record_while_writer_waits(*, owner, event_type, record):
        nonlocal writer
        if event_type == "market_coverage_receipt_recorded":
            writer = threading.Thread(target=write_new_dataset)
            writer.start()
            assert writer_started.wait(timeout=2)
            assert not writer_done.wait(timeout=0.1)
        return original_record_unlocked(owner=owner, event_type=event_type, record=record)

    monkeypatch.setattr(registry, "_record_unlocked", record_while_writer_waits)
    receipt = registry.record_current(
        owner_user_id=OWNER,
        use_validation_refs=use_refs,
        capital_record_ref=CAPITAL_REF,
        transformation_refs=(TRANSFORM_REF,),
        instrument_semantics_refs=tuple(record.semantics_ref for record in semantic_records),
    )
    assert writer is not None
    writer.join(timeout=2)
    assert writer_done.is_set()
    assert writer_errors == []
    assert registry.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    assert not registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted


def test_market_coverage_cross_process_writers_preserve_hash_chain(tmp_path):
    ledger_path = tmp_path / "market_coverage.jsonl"
    market_path = tmp_path / "market_data.jsonl"
    PersistentMarketDataRegistry(market_path)
    context = mp.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_race_record_transformation,
            args=(str(ledger_path), str(market_path), index, start, results),
        )
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0
    outcomes = [results.get(timeout=2) for _worker in workers]
    assert {outcome for outcome, _detail in outcomes} == {"ok"}

    replayed = PersistentMarketCoverageRegistry(
        ledger_path,
        PersistentMarketDataRegistry(market_path),
    )
    assert replayed.poisoned is False
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    previous = None
    for row in rows:
        assert row["previous_record_hash"] == previous
        previous = row["record_hash"]


class _EntrypointRegistry:
    def __init__(self, coverage):
        self._coverage = coverage

    def coverage(self, coverage_ref, *, owner):
        if coverage_ref != self._coverage.coverage_ref or owner != OWNER:
            raise KeyError(coverage_ref)
        return self._coverage

    @staticmethod
    def validate_real_backing(_coverage):
        return SimpleNamespace(accepted=True, violations=())


def _proof(receipt, coverage_ref: str) -> GoalSectionSemanticProofRecord:
    material = market_coverage_semantic_material(receipt)
    values = {
        "section": "§11",
        "subject_ref": material.subject_ref,
        "producer_refs": material.producer_refs,
        "store_refs": material.store_refs,
        "consumer_refs": material.consumer_refs,
        "gate_verdict_refs": material.gate_verdict_refs,
        "test_refs": material.test_refs,
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    return GoalSectionSemanticProofRecord(
        proof_ref=goal_section_semantic_proof_identity(**values),
        **values,
    )


def test_market_coverage_semantic_adapter_requires_exact_current_api_material(tmp_path):
    _market_registry, registry, receipt = _build_current(tmp_path)
    coverage = SimpleNamespace(
        coverage_ref="goal_entrypoint_coverage:market_coverage:current",
        entry_source="api",
        entrypoint_ref=MARKET_COVERAGE_ENTRYPOINT_REF,
        goal_sections=("§11",),
        validation_refs=(receipt.receipt_ref, "runtime_validator:market_coverage_current_v1"),
        recorded_by=OWNER,
    )
    adapter = MarketCoverageSectionAdapter(_EntrypointRegistry(coverage), registry)
    proof = _proof(receipt, coverage.coverage_ref)

    assert adapter.validate(proof, owner=OWNER).accepted

    registry.record_transformation(
        _transformation(revision="v2", formula_ref="formula:daily_adjusted_close:v2"),
        owner_user_id=OWNER,
    )
    stale = adapter.validate(proof, owner=OWNER)
    assert not stale.accepted
    assert {item.code for item in stale.violations} == {
        "goal_semantic_market_coverage_invalid"
    }
