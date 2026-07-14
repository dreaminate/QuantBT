from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.research_os.backtest_evidence import (
    BacktestArtifactState,
    BacktestAttributionRecord,
    BacktestEvidenceError,
    BacktestMonitorRecord,
    PersistentBacktestEvidenceRegistry,
)


OWNER = "owner-backtest-evidence"
OTHER_OWNER = "owner-backtest-evidence-other"
BACKTEST = "qro_backtest_owner_run"
SOURCE_RUN = "ide_run:run-42"


class MutableArtifactResolver:
    def __init__(self, state: BacktestArtifactState) -> None:
        self.state = state
        self.second_state: BacktestArtifactState | None = None
        self.calls = 0

    def __call__(
        self,
        owner_user_id: str,
        backtest_run_ref: str,
        source_run_ref: str,
        artifact_path: str,
    ) -> BacktestArtifactState:
        assert owner_user_id == OWNER
        assert backtest_run_ref == BACKTEST
        assert source_run_ref == SOURCE_RUN
        assert artifact_path == "attribution.csv"
        self.calls += 1
        if self.second_state is not None and self.calls % 2 == 0:
            return self.second_state
        return self.state


def _state(token: str, *, rows: int = 3) -> BacktestArtifactState:
    return BacktestArtifactState(
        artifact_sha256="sha256:" + token * 64,
        row_count=rows,
        component_refs=("component:brinson", "component:cost"),
    )


def _attribution(state: BacktestArtifactState) -> BacktestAttributionRecord:
    return BacktestAttributionRecord(
        owner_user_id=OWNER,
        recorded_by=OWNER,
        backtest_run_ref=BACKTEST,
        source_run_ref=SOURCE_RUN,
        validation_methodology_ref="validation_methodology:run-42",
        validation_depth_ref="validation_depth:run-42",
        artifact_path="attribution.csv",
        artifact_sha256=state.artifact_sha256,
        row_count=state.row_count,
        component_refs=state.component_refs,
        cost_model_refs=("cost_model:fees", "cost_model:slippage"),
    )


def _monitor(
    attribution: BacktestAttributionRecord,
    *,
    backtest_run_ref: str = BACKTEST,
    used_dsr_as_primary_live_alert: bool = False,
) -> BacktestMonitorRecord:
    trigger_refs = ("consistency_check:drawdown", "math_trigger:cost_drift")
    profile_ref = "monitoring_profile:run-42"
    performance_ref = "performance_alert:drawdown"
    cost_drift_ref = "cost_drift:implementation_shortfall"
    root_cause_ref = "drift_root_cause:cost_model"
    return BacktestMonitorRecord(
        owner_user_id=OWNER,
        recorded_by=OWNER,
        backtest_run_ref=backtest_run_ref,
        attribution_ref=attribution.attribution_ref,
        monitoring_profile_ref=profile_ref,
        performance_primary_alert_ref=performance_ref,
        cost_drift_ref=cost_drift_ref,
        drift_root_cause_ref=root_cause_ref,
        mathematical_trigger_refs=trigger_refs,
        evidence_refs=(
            attribution.attribution_ref,
            profile_ref,
            performance_ref,
            cost_drift_ref,
            root_cause_ref,
            *trigger_refs,
        ),
        used_dsr_as_primary_live_alert=used_dsr_as_primary_live_alert,
    )


def test_backtest_evidence_round_trips_current_owner_records(tmp_path) -> None:
    state = _state("a")
    resolver = MutableArtifactResolver(state)
    path = tmp_path / "backtest_evidence.jsonl"
    registry = PersistentBacktestEvidenceRegistry(path, artifact_resolver=resolver)

    attribution = registry.record_attribution(_attribution(state))
    monitor = registry.record_monitor(_monitor(attribution))

    restarted = PersistentBacktestEvidenceRegistry(path, artifact_resolver=resolver)
    assert restarted.attribution(
        attribution.attribution_ref,
        owner_user_id=OWNER,
    ) == attribution
    assert restarted.monitor(monitor.monitor_ref, owner_user_id=OWNER) == monitor
    assert restarted.current_attribution(
        owner_user_id=OWNER,
        backtest_run_ref=BACKTEST,
    ) == attribution
    assert restarted.current_monitor(
        owner_user_id=OWNER,
        backtest_run_ref=BACKTEST,
    ) == monitor
    assert restarted.validate_current_attribution(
        attribution.attribution_ref,
        owner_user_id=OWNER,
    ).accepted
    assert restarted.validate_current_monitor(
        monitor.monitor_ref,
        owner_user_id=OWNER,
    ).accepted
    with pytest.raises(KeyError):
        restarted.attribution(attribution.attribution_ref, owner_user_id=OTHER_OWNER)


def test_artifact_drift_supersedes_attribution_and_monitor(tmp_path) -> None:
    first_state = _state("b")
    resolver = MutableArtifactResolver(first_state)
    registry = PersistentBacktestEvidenceRegistry(
        tmp_path / "backtest_evidence.jsonl",
        artifact_resolver=resolver,
    )
    first_attribution = registry.record_attribution(_attribution(first_state))
    first_monitor = registry.record_monitor(_monitor(first_attribution))

    second_state = _state("c", rows=5)
    resolver.state = second_state
    second_attribution = registry.record_attribution(_attribution(second_state))
    second_monitor = registry.record_monitor(_monitor(second_attribution))

    assert second_attribution.attribution_ref != first_attribution.attribution_ref
    assert second_monitor.monitor_ref != first_monitor.monitor_ref
    assert not registry.validate_current_attribution(
        first_attribution.attribution_ref,
        owner_user_id=OWNER,
    ).accepted
    assert not registry.validate_current_monitor(
        first_monitor.monitor_ref,
        owner_user_id=OWNER,
    ).accepted
    assert registry.validate_current_monitor(
        second_monitor.monitor_ref,
        owner_user_id=OWNER,
    ).accepted


def test_resolution_race_and_invalid_monitor_leave_no_partial_record(tmp_path) -> None:
    first_state = _state("d")
    resolver = MutableArtifactResolver(first_state)
    path = tmp_path / "backtest_evidence.jsonl"
    registry = PersistentBacktestEvidenceRegistry(path, artifact_resolver=resolver)
    resolver.second_state = _state("e")

    with pytest.raises(BacktestEvidenceError, match="changed during resolution"):
        registry.record_attribution(_attribution(first_state))
    assert not path.exists()

    resolver.second_state = None
    resolver.calls = 0
    attribution = registry.record_attribution(_attribution(first_state))
    before = path.read_bytes()
    with pytest.raises(BacktestEvidenceError, match="dsr_primary"):
        registry.record_monitor(
            _monitor(attribution, used_dsr_as_primary_live_alert=True)
        )
    assert path.read_bytes() == before
    with pytest.raises(BacktestEvidenceError, match="current exact attribution"):
        registry.record_monitor(
            _monitor(attribution, backtest_run_ref="qro_backtest_other_run")
        )
    assert path.read_bytes() == before


def test_monitor_requires_complete_evidence_and_exact_content_identity(tmp_path) -> None:
    state = _state("f")
    resolver = MutableArtifactResolver(state)
    registry = PersistentBacktestEvidenceRegistry(
        tmp_path / "backtest_evidence.jsonl",
        artifact_resolver=resolver,
    )
    attribution = registry.record_attribution(_attribution(state))
    monitor = _monitor(attribution)

    incomplete = replace(
        monitor,
        evidence_refs=(attribution.attribution_ref,),
        monitor_ref="",
    )
    with pytest.raises(BacktestEvidenceError, match="evidence_incomplete"):
        registry.record_monitor(incomplete)
    with pytest.raises(ValueError, match="identity"):
        replace(monitor, monitor_ref="monitor:not-the-content-hash")


def test_hash_chain_tampering_fails_closed_on_restart(tmp_path) -> None:
    state = _state("1")
    resolver = MutableArtifactResolver(state)
    path = tmp_path / "backtest_evidence.jsonl"
    registry = PersistentBacktestEvidenceRegistry(path, artifact_resolver=resolver)
    attribution = registry.record_attribution(_attribution(state))
    registry.record_monitor(_monitor(attribution))

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["row_count"] = 999
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(BacktestEvidenceError, match="invalid persisted"):
        PersistentBacktestEvidenceRegistry(path, artifact_resolver=resolver)
