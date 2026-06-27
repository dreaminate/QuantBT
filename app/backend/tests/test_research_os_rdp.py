from __future__ import annotations

from app.research_os import (
    ActorSource,
    ConsistencyStatus,
    QRORecord,
    QROType,
    RuntimeStatus,
    manifest_from_qro,
    validate_rdp_manifest,
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
        "mathematical_refs": ("math_momentum",),
        "theory_implementation_binding": "tbind_momentum",
        "methodology_choice_ref": "mchoice_standard",
        "consistency_status": ConsistencyStatus.ACCEPTED,
        "allowed_environment": RuntimeStatus.PAPER,
    }
    data.update(overrides)
    return QRORecord(**data)


def _manifest(**overrides):
    qro = overrides.pop("qro", _qro())
    data = {
        "qro": qro,
        "research_question": "Can daily BTC momentum survive costs?",
        "graph_refs": ("rg:qro_graph",),
        "data_refs": ("dataset:BTCUSDT_1d",),
        "dataset_version_refs": ("dsver:btc-2023",),
        "market_data_use_validation_refs": ("market_data_use:BTCUSDT_1d:backtest",),
        "ingestion_skill_refs": ("skill:binance-vision-daily",),
        "consistency_check_refs": ("ccheck_momentum",),
        "code_refs": ("app/strategy/momentum.py",),
        "environment_lock_ref": "env:poetry-lock",
        "reproducibility_command": "python -m quantbt.run --run r1",
        "artifact_hash": "sha256:abc",
        "test_refs": ("tests/test_momentum.py",),
        "run_refs": ("run:bt1",),
        "honest_n_refs": ("ledger:goal1",),
        "cost_and_execution_assumptions": ("fee=10bps",),
        "attribution_refs": ("attrib:bt1",),
        "unverified_residuals": ("live slippage not observed",),
        "verifier_verdict_ref": "verdict:bt1",
        "compiler_artifact_refs": ("compiler_artifact:strategy:001",),
        "mathematical_spine_chain_refs": ("math_spine_chain:btc_momentum:v1",),
        "goal_entrypoint_coverage_refs": ("goal_entrypoint_coverage:strategy:001",),
        "responsibility_refs": ("resp:standard",),
        "approval_ref": "approval:paper",
        "source_file_refs": ("source:unit",),
    }
    data.update(overrides)
    return manifest_from_qro(**data)


def test_rdp_manifest_accepts_complete_paper_package():
    manifest = _manifest()
    assert manifest.package_id.startswith("rdp_")
    assert validate_rdp_manifest(manifest, has_user_waiver=False) == ()
    rendered = manifest.to_open_json()
    assert "reproducibility_command" in rendered
    assert "unverified_residuals" in rendered


def test_rdp_manifest_rejects_missing_dataset_version_and_repro_command():
    manifest = _manifest(dataset_version_refs=(), reproducibility_command="")
    violations = validate_rdp_manifest(manifest)
    codes = {v.code for v in violations}
    assert "missing_dataset_version_refs" in codes
    assert "missing_reproducibility_command" in codes


def test_rdp_manifest_requires_market_data_use_validation_refs():
    manifest = _manifest(market_data_use_validation_refs=())
    violations = validate_rdp_manifest(manifest)
    assert {v.code for v in violations} == {"missing_market_data_use_validation_refs"}


def test_rdp_manifest_rejects_missing_unverified_residuals():
    manifest = _manifest(unverified_residuals=())
    violations = validate_rdp_manifest(manifest)
    assert {v.code for v in violations} == {"missing_unverified_residuals"}


def test_rdp_manifest_requires_compiler_spine_and_entrypoint_coverage_refs():
    manifest = _manifest(
        compiler_artifact_refs=(),
        mathematical_spine_chain_refs=(),
        goal_entrypoint_coverage_refs=(),
    )
    codes = {v.code for v in validate_rdp_manifest(manifest)}
    assert codes >= {
        "missing_compiler_artifact_refs",
        "missing_mathematical_spine_chain_refs",
        "missing_goal_entrypoint_coverage_refs",
    }


def test_rdp_manifest_requires_methodology_and_responsibility_for_user_waiver():
    qro = _qro(methodology_choice_ref=None)
    manifest = _manifest(qro=qro, responsibility_refs=())
    codes = {v.code for v in validate_rdp_manifest(manifest, has_user_waiver=True)}
    assert "missing_methodology_choice_refs" in codes
    assert "missing_responsibility_refs" in codes


def test_live_rdp_requires_deployment_monitor_rollback_and_retire_refs():
    qro = _qro(allowed_environment=RuntimeStatus.LIVE)
    manifest = _manifest(qro=qro, deployment_refs=(), monitor_refs=(), rollback_plan_ref=None, retire_plan_ref=None)
    codes = {v.code for v in validate_rdp_manifest(manifest)}
    assert codes >= {
        "missing_deployment_refs",
        "missing_monitor_refs",
        "missing_rollback_plan_ref",
        "missing_retire_plan_ref",
    }
