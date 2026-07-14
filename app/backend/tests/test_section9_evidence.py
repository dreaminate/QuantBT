from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    PersistentAssetLifecycleRegistry,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentResearchAssetRAGIndex,
    PersistentResearchGraphStore,
    PersistentSignalValidationRegistry,
    QROType,
)
from app.research_os.research_design_assets import (
    PersistentResearchDesignAssetRegistry,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver

from app.research_os.factor_strategy_boundary import (
    FactorAssetKind,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    SignalPerformanceValidationRecord,
    SignalProtocolRecord,
    SignalValidationVerdict,
    StrategyBookContract,
    StrategyLegContract,
)
from app.research_os.section9_evidence import (
    FactorGenerationRecord,
    PersistentSection9EvidenceRegistry,
    Section9EvidenceSnapshot,
    section9_evidence_snapshot_to_dict,
    validate_section9_evidence_snapshot,
)


def _snapshot() -> Section9EvidenceSnapshot:
    validation = SignalPerformanceValidationRecord(
        signal_ref="sig::alpha",
        validation_dataset_ref="dataset_version:btc:v1",
        evaluation_window_ref="window:oos",
        methodology_ref="methodology:strict",
        metric_refs=("metric:dsr",),
        performance_summary_ref="summary:alpha",
        leakage_check_ref="leakage:alpha",
        evidence_refs=("evidence:alpha",),
        verdict=SignalValidationVerdict.ACCEPTED,
        recorded_by="alice-id",
    )
    return Section9EvidenceSnapshot(
        source_strategy_ref="stg_alpha",
        factor_library_entries=(
            FactorLibraryEntry(
                factor_ref="factor:alpha",
                kind=FactorAssetKind.EXPRESSION,
                ref="expression:close/open-1",
                mathematical_refs=("math:alpha",),
                theory_binding_ref="binding:alpha",
                run_config_binding_ref="run_config:alpha",
            ),
        ),
        factor_generations=(
            FactorGenerationRecord(
                generation_ref="generation:alpha",
                produced_factor_ref="factor:alpha",
                generator=FactorGeneratorSpec(
                    generator_ref="generator:enumerative",
                    structure_inputs=("operator:add", "field:close", "field:open"),
                    fitness_inputs=("complexity",),
                    gatekeeper_ref="gatekeeper:factor-validation",
                ),
            ),
        ),
        signal_protocols=(
            SignalProtocolRecord(
                signal_ref="sig::alpha",
                source_model_ref="model:alpha.onnx",
                oof=True,
                purge=True,
                embargo=True,
                train_test_lock_ref="lock:alpha",
                honest_n_ref="honest_n:alpha",
                forecast_time_ref="forecast_time:close",
                prediction_horizon_ref="horizon:1d",
                unit_ref="unit:return",
                direction_semantics_ref="direction:signed",
                confidence_ref="confidence:probability",
                expires_at_ref="expiry:next_close",
            ),
        ),
        signal_validations=(validation,),
        strategy_book=StrategyBookContract(
            strategy_book_ref="strategy_book:alpha",
            factor_refs=("factor:alpha",),
            signal_refs=("sig::alpha",),
            legs=(
                StrategyLegContract(
                    intent_ref="intent:alpha:long",
                    side="long",
                    instrument_ref="instrument:BTCUSDT",
                ),
            ),
            mathematical_refs=("math:strategy-alpha",),
            theory_binding_refs=("binding:strategy-alpha",),
            run_config_binding_refs=("run_config:strategy-alpha",),
            signal_validation_refs=(validation.validation_id,),
        ),
    )


def _codes(snapshot: Section9EvidenceSnapshot) -> set[str]:
    return {
        violation.code
        for violation in validate_section9_evidence_snapshot(snapshot).violations
    }


def test_section9_snapshot_is_content_bound_and_complete():
    snapshot = _snapshot()
    assert snapshot.snapshot_ref.startswith("s9snap_")
    assert validate_section9_evidence_snapshot(snapshot).accepted

    incomplete = replace(snapshot, factor_generations=(), snapshot_ref="")
    assert "section9_snapshot_family_missing" in _codes(incomplete)


def test_section9_snapshot_rejects_generator_signal_and_strategy_drift():
    snapshot = _snapshot()
    bad_generation = replace(
        snapshot,
        factor_generations=(
            replace(snapshot.factor_generations[0], produced_factor_ref="factor:other"),
        ),
        snapshot_ref="",
    )
    assert "section9_generation_factor_closure_mismatch" in _codes(bad_generation)

    bad_signal = replace(
        snapshot,
        strategy_book=replace(
            snapshot.strategy_book,
            signal_refs=("sig::other",),
        ),
        snapshot_ref="",
    )
    assert "section9_strategy_signal_closure_mismatch" in _codes(bad_signal)

    rejected_validation = replace(
        snapshot,
        signal_validations=(
            replace(
                snapshot.signal_validations[0],
                verdict=SignalValidationVerdict.REJECTED.value,
                validation_id="",
            ),
        ),
        snapshot_ref="",
    )
    assert "signal_validation_not_accepted" in _codes(rejected_validation)


def test_section9_registry_is_owner_scoped_replay_safe_and_quarantines_legacy(tmp_path):
    path = tmp_path / "section9.jsonl"
    path.write_text(json.dumps({"schema_version": 1, "snapshot": {}}) + "\n")
    registry = PersistentSection9EvidenceRegistry(path)
    assert registry.legacy_quarantined_count == 1
    snapshot = registry.record_snapshot(
        _snapshot(),
        owner_user_id="alice-id",
        recorded_by="alice",
    )
    before = path.read_bytes()

    assert registry.snapshot(
        snapshot.snapshot_ref,
        owner_user_id="alice-id",
    ) == snapshot
    with pytest.raises(KeyError):
        registry.snapshot(snapshot.snapshot_ref, owner_user_id="bob-id")
    assert registry.record_snapshot(
        snapshot,
        owner_user_id="alice-id",
        recorded_by="alice",
    ) == snapshot
    assert path.read_bytes() == before

    reloaded = PersistentSection9EvidenceRegistry(path)
    assert reloaded.snapshot(
        snapshot.snapshot_ref,
        owner_user_id="alice-id",
    ) == snapshot


def test_section9_registry_rejects_invalid_snapshot_without_partial_write(tmp_path):
    registry = PersistentSection9EvidenceRegistry(tmp_path / "section9.jsonl")
    invalid = replace(_snapshot(), signal_protocols=(), snapshot_ref="")
    with pytest.raises(ValueError, match="section9_snapshot_family_missing"):
        registry.record_snapshot(
            invalid,
            owner_user_id="alice-id",
            recorded_by="alice",
        )
    assert not registry.path.exists()


def test_section9_api_persists_real_owner_strategy_book_qro_lifecycle_and_rag(
    tmp_path,
    monkeypatch,
):
    snapshot = _snapshot()
    validations = PersistentSignalValidationRegistry(
        tmp_path / "signal_validations.jsonl"
    )
    validations.record_validation(
        snapshot.signal_validations[0],
        owner_user_id="alice-id",
        known_signal_refs={snapshot.signal_validations[0].signal_ref},
    )
    design = PersistentResearchDesignAssetRegistry(
        tmp_path / "research_design.jsonl"
    )
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    lifecycle = PersistentAssetLifecycleRegistry(tmp_path / "lifecycle.jsonl")
    rag = PersistentResearchAssetRAGIndex(tmp_path / "rag.jsonl")
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    goal_validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=goal_validations,
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
            goal_validation_receipt_registry=goal_validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(
        main,
        "SECTION9_EVIDENCE_REGISTRY",
        PersistentSection9EvidenceRegistry(tmp_path / "section9.jsonl"),
    )
    monkeypatch.setattr(main, "SIGNAL_VALIDATIONS", validations)
    monkeypatch.setattr(main, "RESEARCH_DESIGN_ASSET_REGISTRY", design)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", rag)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", goal_validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    monkeypatch.setattr(
        main,
        "IDE_SERVICE",
        SimpleNamespace(
            list_strategies=lambda username: (
                SimpleNamespace(strategy_id="stg_alpha", owner=username),
            )
        ),
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="alice-id",
        username="alice",
    )
    try:
        client = TestClient(main.app)
        response = client.post(
            "/api/research-os/section9/evidence_snapshots",
            json=section9_evidence_snapshot_to_dict(snapshot),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        evidence = body["strategy_book"]
        assert evidence["strategy_book_ref"] == snapshot.strategy_book.strategy_book_ref
        record = design.strategy_book(
            snapshot.strategy_book.strategy_book_ref,
            owner_user_id="alice-id",
        )
        assert record.strategy_book["legs"][0]["intent_ref"] == "intent:alpha:long"
        assert graph.qro(evidence["qro_id"]).qro_type == QROType.STRATEGY_BOOK
        assert lifecycle.governed_asset(
            evidence["lifecycle_ref"], owner_user_id="alice-id"
        ).asset_type == "StrategyBook"
        assert rag.document_for_owner(
            evidence["rag_ref"],
            owner_user_id="alice-id",
            require_current=True,
        ).asset_ref == snapshot.strategy_book.strategy_book_ref

        journal_before_retry = design.path.read_bytes()
        retry = client.post(
            "/api/research-os/section9/evidence_snapshots",
            json=section9_evidence_snapshot_to_dict(snapshot),
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["strategy_book"]["qro_id"] == evidence["qro_id"]
        assert design.path.read_bytes() == journal_before_retry
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
