"""Adversarial tests for the GOAL §16 performance-baseline benchmark harness.

Covers, per RULES §2 (种已知坏门必抓) and §3 (诚实纪律):
- the three baselines that are measured for real report GREEN with evidence;
- the two baselines that genuinely cannot be measured here are honest
  KNOWN_RUN_GAP -- never a fake pass;
- regressing a baseline past threshold reports RED (the falsifiability proof);
- an injected delay that pushes a measured callable over threshold reports RED;
- the mutation-killable gate: an over-threshold measurement cannot pass, and a
  gap cannot be laundered into green.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

# tests/benchmark is not a package; make the sibling harness importable robustly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import perf_harness as ph  # noqa: E402
from app.research_os.engineering_standards import (  # noqa: E402
    PERF_FAIL,
    PERF_KNOWN_RUN_GAP,
    PERF_PASS,
    PerformanceBaselineMeasurement,
    classify_performance_baseline,
)


def _codes(verdict) -> set[str]:
    assert verdict.decision is not None
    return {v.code for v in verdict.decision.violations}


# ───────────────────────────── measured = GREEN ───────────────────────────────
def test_standard_backtest_measures_green():
    measurement = ph.measure_standard_backtest()
    assert measurement.measured is True
    assert measurement.threshold_seconds == 60.0
    assert measurement.observed_seconds is not None
    assert measurement.observed_seconds < measurement.threshold_seconds
    assert measurement.evidence_ref
    verdict = classify_performance_baseline(measurement)
    assert verdict.status == PERF_PASS
    assert verdict.is_pass


def test_rag_first_results_carry_source_version_and_pass():
    measurement = ph.measure_rag_first_results()
    assert measurement.measured is True
    assert measurement.threshold_seconds == 3.0
    assert measurement.observed_seconds is not None
    assert measurement.observed_seconds < measurement.threshold_seconds
    # GOAL §16: the first batch must carry source + version.
    assert "source_version=True" in measurement.evidence_ref
    assert "source_version=False" not in measurement.evidence_ref
    assert classify_performance_baseline(measurement).status == PERF_PASS


def test_rag_hits_structurally_carry_source_and_version():
    # Direct structural check of the §16 "带 source/version" requirement.
    from app.research_os.asset_rag import (
        AssetRAGDocument,
        RAGPermission,
        RAGProjection,
        RAGQueryContext,
        ResearchAssetRAGIndex,
    )

    index = ResearchAssetRAGIndex()
    index.add(
        AssetRAGDocument(
            source_id="src:momentum",
            version="v3",
            title="momentum factor note",
            body="momentum volatility factor a-share daily",
            projection=RAGProjection.FACTOR,
            asset_ref="asset:factor:momentum",
            permission=RAGPermission(),
            applicability="a_share daily",
            source_kind="research_note",
        )
    )
    ctx = RAGQueryContext(
        user_id="u", desk="d", visible_asset_refs=("asset:factor:momentum",)
    )
    hits = index.retrieve("momentum factor", context=ctx, top_k=5)
    assert hits
    for hit in hits:
        assert hit.source_id and hit.version


def test_asset_library_retrieval_measures_green():
    measurement = ph.measure_asset_library_retrieval()
    assert measurement.measured is True
    assert measurement.threshold_seconds == 1.0
    assert measurement.observed_seconds is not None
    assert measurement.observed_seconds < measurement.threshold_seconds
    assert measurement.evidence_ref
    assert classify_performance_baseline(measurement).status == PERF_PASS


def test_asset_library_retrieval_restores_pool_dir():
    from app import symbol_pools

    before = symbol_pools.SYMBOL_POOLS_DIR
    ph.measure_asset_library_retrieval()
    assert symbol_pools.SYMBOL_POOLS_DIR == before


# ───────────────────────── unmeasurable = honest GAP ──────────────────────────
def test_hs300_read_is_known_run_gap_not_fake_pass():
    measurement = ph.measure_hs300_10y_daily_read()
    assert measurement.measured is False
    assert measurement.observed_seconds is None
    assert measurement.unavailable_reason
    verdict = classify_performance_baseline(measurement)
    assert verdict.status == PERF_KNOWN_RUN_GAP
    assert not verdict.is_pass
    assert verdict.decision is None
    # the transparency proxy ran, but it is NOT claimed as a production pass
    assert "synthetic" in measurement.detail.lower()


def test_run_first_screen_is_known_run_gap_not_fake_pass():
    measurement = ph.measure_run_first_screen()
    assert measurement.measured is False
    assert measurement.observed_seconds is None
    assert measurement.unavailable_reason
    verdict = classify_performance_baseline(measurement)
    assert verdict.status == PERF_KNOWN_RUN_GAP
    assert not verdict.is_pass
    assert "browser" in measurement.unavailable_reason.lower()


# ───────────────── adversarial: regress a baseline => RED ──────────────────────
def test_regressed_backtest_reports_red():
    """Inject a perf regression: a backtest measured over 60s must report RED."""
    good = ph.measure_standard_backtest()
    assert classify_performance_baseline(good).status == PERF_PASS

    regressed = replace(good, observed_seconds=good.threshold_seconds + 5.0)
    verdict = classify_performance_baseline(regressed)
    assert verdict.status == PERF_FAIL
    assert not verdict.is_pass
    assert "performance_baseline_exceeded" in _codes(verdict)


def test_injected_delay_pushes_measured_baseline_red():
    """A real injected delay measured by the harness timer, over threshold => RED.

    Exercises the end-to-end path (real timing -> classify) without a 60s sleep:
    a 50ms delay against a 10ms threshold is a deterministic regression.
    """

    def _slow() -> None:
        time.sleep(0.05)

    timing = ph._time_call(_slow, repeat=2, warmup=0)
    assert timing.median_seconds >= 0.05

    measurement = PerformanceBaselineMeasurement(
        baseline_ref="perf:test_injected_delay",
        metric_name="injected delay probe",
        threshold_seconds=0.01,
        measured=True,
        observed_seconds=timing.median_seconds,
        evidence_ref="benchmark:injected_delay",
    )
    assert classify_performance_baseline(measurement).status == PERF_FAIL


# ─────────── mutation-killable gate (target-RED test for the 3-state) ──────────
def test_over_threshold_measurement_cannot_pass():
    """The single gate that the mutation 3-state targets.

    Weakening ``classify_performance_baseline`` so an over-threshold measurement
    passes makes THIS test go red. Deterministic (120s vs 60s, no timing).
    """
    measurement = PerformanceBaselineMeasurement(
        baseline_ref="perf:guard",
        metric_name="over-threshold guard",
        threshold_seconds=60.0,
        measured=True,
        observed_seconds=120.0,
        evidence_ref="benchmark:guard",
    )
    verdict = classify_performance_baseline(measurement)
    assert verdict.status == PERF_FAIL
    assert not verdict.is_pass
    assert "performance_baseline_exceeded" in _codes(verdict)


def test_known_run_gap_cannot_be_laundered_into_green():
    gap = PerformanceBaselineMeasurement(
        baseline_ref="perf:gap",
        metric_name="gap",
        threshold_seconds=3.0,
        measured=False,
        observed_seconds=None,
        evidence_ref="benchmark:gap",
        unavailable_reason="no production data here",
    )
    assert classify_performance_baseline(gap).status == PERF_KNOWN_RUN_GAP
    # sneaking an observed time + evidence onto a measured=False record must not pass
    sneaky = replace(gap, observed_seconds=0.001)
    assert classify_performance_baseline(sneaky).status == PERF_KNOWN_RUN_GAP
    assert not classify_performance_baseline(sneaky).is_pass


def test_measured_without_evidence_fails():
    measurement = PerformanceBaselineMeasurement(
        baseline_ref="perf:noevidence",
        metric_name="missing evidence",
        threshold_seconds=3.0,
        measured=True,
        observed_seconds=0.1,
        evidence_ref=None,
    )
    verdict = classify_performance_baseline(measurement)
    assert verdict.status == PERF_FAIL
    assert "performance_baseline_missing_evidence" in _codes(verdict)


def test_measured_without_observed_seconds_raises():
    measurement = PerformanceBaselineMeasurement(
        baseline_ref="perf:bad",
        metric_name="measured but no time",
        threshold_seconds=3.0,
        measured=True,
        observed_seconds=None,
        evidence_ref="benchmark:bad",
    )
    with pytest.raises(ValueError):
        classify_performance_baseline(measurement)


# ──────────────────────────── full-report smoke ───────────────────────────────
def test_run_all_benchmarks_honest_report():
    report = ph.run_all_benchmarks()
    assert len(report.verdicts) == 5
    assert report.no_regression is True
    assert len(report.failed) == 0
    assert len(report.passed) == 3
    assert len(report.gaps) == 2
    # honest: KNOWN_RUN_GAPs keep full closure False; they are not counted as pass
    assert report.fully_closed is False

    passed_refs = {v.measurement.baseline_ref for v in report.passed}
    assert passed_refs == {
        ph.BASELINE_STANDARD_BACKTEST,
        ph.BASELINE_RAG_FIRST_RESULTS,
        ph.BASELINE_ASSET_LIBRARY_RETRIEVAL,
    }
    gap_refs = {v.measurement.baseline_ref for v in report.gaps}
    assert gap_refs == {ph.BASELINE_HS300_READ, ph.BASELINE_RUN_FIRST_SCREEN}

    # render must not crash and must surface the honest tallies
    rendered = report.render()
    assert "KNOWN_RUN_GAP" in rendered
    assert "fully_closed=False" in rendered

    # honest exit code: gaps present + nothing failed => 2 (NOT a green 0)
    assert report.exit_code == 2


def _verdict(observed, threshold, *, measured=True, evidence="benchmark:x", reason=None):
    return classify_performance_baseline(
        PerformanceBaselineMeasurement(
            baseline_ref="perf:x",
            metric_name="x",
            threshold_seconds=threshold,
            measured=measured,
            observed_seconds=observed,
            evidence_ref=evidence,
            unavailable_reason=reason,
        )
    )


def test_exit_code_distinguishes_closure_regression_and_gap():
    all_pass = ph.BenchmarkReport((_verdict(0.1, 1.0), _verdict(0.2, 1.0)))
    assert all_pass.fully_closed is True
    assert all_pass.exit_code == 0

    with_regression = ph.BenchmarkReport((_verdict(0.1, 1.0), _verdict(5.0, 1.0)))
    assert with_regression.exit_code == 1

    with_gap = ph.BenchmarkReport(
        (_verdict(0.1, 1.0), _verdict(None, 1.0, measured=False, reason="no data"))
    )
    assert with_gap.failed == ()
    assert with_gap.fully_closed is False
    assert with_gap.exit_code == 2
