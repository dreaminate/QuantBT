"""GOAL §16 performance-baseline benchmark harness.

GOAL §16 lists five performance baselines:

    1. 沪深300 × 10年日频基础数据读取 < 3s   (HS300 x 10y daily read)
    2. 标准回测 < 60s                          (standard backtest)
    3. Run 首屏 < 2s                            (Run first-screen)
    4. 常用资产库检索 < 1s                       (common asset-library retrieval)
    5. RAG 返回带 source/version 的首批结果 < 3s (RAG first results w/ source+version)

A ``validate_performance_baseline`` lib already exists in
``app.research_os.engineering_standards`` but nothing actually *measures* the
baselines. This module is the missing harness: it runs real code paths, times
them with ``time.perf_counter``, and routes every observation through
``classify_performance_baseline`` (which reuses ``validate_performance_baseline``
-- the threshold/evidence logic is NOT reimplemented here).

Honesty (GOAL §3 / RULES §3): where the *production* baseline cannot be measured
in this environment (no real HS300 10y dataset, no live frontend/browser), the
baseline is recorded as ``measured=False`` -> KNOWN_RUN_GAP, never a fake pass.
For those gaps we still run a real, clearly-labelled *proxy* timing (synthetic
full-scale read; backend overview-series assembly) and attach the number in
``detail`` for transparency -- but the headline status stays an honest gap.

Runnable:  python app/backend/tests/benchmark/perf_harness.py
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Make ``app.*`` importable when this file is run as a standalone script
# (under pytest the conftest already puts app/backend on sys.path).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.research_os.engineering_standards import (  # noqa: E402
    PERF_FAIL,
    PERF_KNOWN_RUN_GAP,
    PERF_PASS,
    PerformanceBaselineMeasurement,
    PerformanceBaselineVerdict,
    classify_performance_baseline,
)

# Baseline references (stable ids used in evidence + reports).
BASELINE_HS300_READ = "perf:hs300_10y_daily_read"
BASELINE_STANDARD_BACKTEST = "perf:standard_backtest"
BASELINE_RUN_FIRST_SCREEN = "perf:run_first_screen"
BASELINE_ASSET_LIBRARY_RETRIEVAL = "perf:asset_library_retrieval"
BASELINE_RAG_FIRST_RESULTS = "perf:rag_first_results"


@dataclass(frozen=True)
class TimingSample:
    median_seconds: float
    best_seconds: float
    worst_seconds: float
    repeat: int


def _time_call(fn: Callable[[], object], *, repeat: int = 5, warmup: int = 1) -> TimingSample:
    """Time ``fn`` ``repeat`` times after ``warmup`` untimed runs; report the median.

    Median (not best) is reported as the observed latency so a single fast run
    cannot flatter the baseline. Best/worst are kept for the evidence detail.
    """
    for _ in range(max(warmup, 0)):
        fn()
    samples: list[float] = []
    for _ in range(max(repeat, 1)):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return TimingSample(
        median_seconds=statistics.median(samples),
        best_seconds=min(samples),
        worst_seconds=max(samples),
        repeat=len(samples),
    )


# ───────────────────────── baseline 2: standard backtest (< 60s) ──────────────
def measure_standard_backtest(
    *, n_symbols: int = 300, n_days: int = 756, n_features: int = 4, top_n: int = 30, seed: int = 7
) -> PerformanceBaselineMeasurement:
    """Measure the real standard-backtest chain on a synthetic HS300-scale panel.

    Exercises ``app.training.backtest_bridge.backtest_trained_model`` end to end:
    a real fitted sklearn model -> per-day cross-sectional scores -> top-N weights
    -> shift(1) (look-ahead guard) -> portfolio returns -> metrics + equity curve.
    Synthetic prices/features do not change the vectorised work the backtest does,
    so this is a real measurement of the product backtest at representative scale.
    """
    import pickle

    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LinearRegression

    from app.training.backtest_bridge import backtest_trained_model

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2016-01-04", periods=n_days)
    symbols = [f"{i:06d}.SZ" for i in range(n_symbols)]
    n_rows = n_days * n_symbols
    ts = np.repeat(dates.values, n_symbols)
    sym = np.tile(np.asarray(symbols, dtype=object), n_days)
    close = 10.0 + np.abs(rng.standard_normal(n_rows)) * 5.0 + 1.0
    feature_cols = [f"f{j}" for j in range(n_features)]
    feature_data = {name: rng.standard_normal(n_rows) for name in feature_cols}
    panel = pd.DataFrame({"ts": ts, "symbol": sym, "close": close, **feature_data})

    model = LinearRegression().fit(panel[feature_cols], panel["close"].to_numpy())

    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "model.pkl"
        with artifact.open("wb") as fh:
            pickle.dump(model, fh)

        def _run() -> None:
            backtest_trained_model(artifact, panel, feature_cols=feature_cols, top_n=top_n)

        timing = _time_call(_run, repeat=3, warmup=1)

    evidence = (
        f"benchmark:standard_backtest:n_symbols={n_symbols}:n_days={n_days}"
        f":rows={n_rows}:median_s={timing.median_seconds:.4f}"
    )
    detail = (
        f"backtest_trained_model on synthetic HS300-scale panel "
        f"({n_symbols} symbols x {n_days} days = {n_rows} rows, {n_features} features); "
        f"median={timing.median_seconds:.4f}s best={timing.best_seconds:.4f}s "
        f"worst={timing.worst_seconds:.4f}s over {timing.repeat} runs"
    )
    return PerformanceBaselineMeasurement(
        baseline_ref=BASELINE_STANDARD_BACKTEST,
        metric_name="标准回测 (standard backtest)",
        threshold_seconds=60.0,
        measured=True,
        observed_seconds=timing.median_seconds,
        evidence_ref=evidence,
        detail=detail,
    )


# ───────────────────── baseline 5: RAG first results w/ source/version (< 3s) ──
def measure_rag_first_results(
    *, n_docs: int = 500, top_k: int = 5, seed: int = 11
) -> PerformanceBaselineMeasurement:
    """Measure the real Research Asset RAG retrieval path on a seeded corpus.

    Exercises ``ResearchAssetRAGIndex.retrieve``. §16 requires the first batch to
    carry source + version; every ``AssetRAGHit`` structurally carries source_id
    and version, and we record in the evidence that the returned batch does.
    """
    import random

    from app.research_os.asset_rag import (
        AssetRAGDocument,
        RAGPermission,
        RAGProjection,
        RAGQueryContext,
        ResearchAssetRAGIndex,
    )

    rng = random.Random(seed)
    vocab = [
        "momentum",
        "reversal",
        "volatility",
        "liquidity",
        "value",
        "quality",
        "carry",
        "size",
        "beta",
        "drawdown",
        "sharpe",
        "factor",
    ]
    index = ResearchAssetRAGIndex()
    visible_assets: list[str] = []
    for i in range(n_docs):
        asset_ref = f"asset:factor:{i}"
        visible_assets.append(asset_ref)
        body = " ".join(rng.choice(vocab) for _ in range(24))
        index.add(
            AssetRAGDocument(
                source_id=f"src:factor:{i}",
                version=f"v{(i % 5) + 1}",
                title=f"factor research note {i} {rng.choice(vocab)}",
                body=f"{body} a-share daily research note {i}",
                projection=RAGProjection.FACTOR,
                asset_ref=asset_ref,
                permission=RAGPermission(),
                applicability="a_share daily cross-section",
                source_kind="research_note",
            )
        )

    context = RAGQueryContext(
        user_id="user:bench",
        desk="desk:bench",
        visible_asset_refs=tuple(visible_assets),
    )
    captured: dict[str, list] = {}

    def _run() -> None:
        captured["hits"] = index.retrieve(
            "momentum volatility factor", context=context, top_k=top_k
        )

    timing = _time_call(_run, repeat=5, warmup=1)
    hits = captured.get("hits", [])
    have_source_version = bool(hits) and all(h.source_id and h.version for h in hits)

    evidence = (
        f"benchmark:rag_first_results:n_docs={n_docs}:hits={len(hits)}"
        f":source_version={have_source_version}:median_s={timing.median_seconds:.4f}"
    )
    detail = (
        f"ResearchAssetRAGIndex.retrieve over seeded corpus of {n_docs} docs; "
        f"returned {len(hits)} hits, all carry source+version={have_source_version}; "
        f"median={timing.median_seconds:.4f}s best={timing.best_seconds:.4f}s "
        f"worst={timing.worst_seconds:.4f}s over {timing.repeat} runs"
    )
    return PerformanceBaselineMeasurement(
        baseline_ref=BASELINE_RAG_FIRST_RESULTS,
        metric_name="RAG 首批结果带 source/version (RAG first results)",
        threshold_seconds=3.0,
        measured=True,
        observed_seconds=timing.median_seconds,
        evidence_ref=evidence,
        detail=detail,
    )


# ──────────────────── baseline 4: common asset-library retrieval (< 1s) ────────
def measure_asset_library_retrieval(
    *, n_pools: int = 40, symbols_per_pool: int = 300, seed: int = 5
) -> PerformanceBaselineMeasurement:
    """Measure the real symbol/asset-pool library retrieval over local JSON.

    Exercises ``app.symbol_pools.list_symbol_pools`` + ``load_symbol_pool_symbols``
    against a seeded on-disk pool library at representative scale (real I/O, real
    repo code path). The module-global pool dir is restored afterwards.
    """
    from app import symbol_pools

    with tempfile.TemporaryDirectory() as tmp:
        pool_dir = Path(tmp)
        for p in range(n_pools):
            symbols = [f"{(p * 1000 + i):06d}.SZ" for i in range(symbols_per_pool)]
            (pool_dir / f"pool_{p}.json").write_text(
                json.dumps(
                    {
                        "pool_id": f"pool_{p}",
                        "name": f"Bench pool {p}",
                        "market": "stocks_cn",
                        "symbols": symbols,
                    }
                ),
                encoding="utf-8",
            )

        original_dir = symbol_pools.SYMBOL_POOLS_DIR
        symbol_pools.SYMBOL_POOLS_DIR = pool_dir
        try:

            def _run() -> None:
                rows = symbol_pools.list_symbol_pools(market="stocks_cn")
                symbol_pools.load_symbol_pool_symbols(rows[0]["pool_id"], "stocks_cn")

            timing = _time_call(_run, repeat=5, warmup=1)
        finally:
            symbol_pools.SYMBOL_POOLS_DIR = original_dir

    evidence = (
        f"benchmark:asset_library_retrieval:n_pools={n_pools}"
        f":symbols_per_pool={symbols_per_pool}:median_s={timing.median_seconds:.4f}"
    )
    detail = (
        f"list_symbol_pools + load_symbol_pool_symbols over {n_pools} pools "
        f"x {symbols_per_pool} symbols; median={timing.median_seconds:.4f}s "
        f"best={timing.best_seconds:.4f}s worst={timing.worst_seconds:.4f}s "
        f"over {timing.repeat} runs"
    )
    return PerformanceBaselineMeasurement(
        baseline_ref=BASELINE_ASSET_LIBRARY_RETRIEVAL,
        metric_name="常用资产库检索 (asset-library retrieval)",
        threshold_seconds=1.0,
        measured=True,
        observed_seconds=timing.median_seconds,
        evidence_ref=evidence,
        detail=detail,
    )


# ──────────────── baseline 1: HS300 x 10y daily read (< 3s) — KNOWN_RUN_GAP ─────
def measure_hs300_10y_daily_read(
    *, n_symbols: int = 300, n_days: int = 2430, seed: int = 3
) -> PerformanceBaselineMeasurement:
    """KNOWN_RUN_GAP: no production HS300 10y store in this environment.

    The production baseline reads the *real* HS300 10y daily dataset through the
    ingestion/adjust pipeline; that dataset is not present here (no Tushare-backed
    store), so this is an honest gap -- NOT a pass. For transparency we still run a
    real full-scale columnar read (polars read_parquet over a synthetic
    300 x 2430-row OHLCV frame) and record that number in ``detail``. Synthetic
    uniform data is not the production dataset, so the headline status stays GAP.
    """
    synthetic_read_seconds: float | None = None
    try:
        import numpy as np
        import polars as pl

        rng = np.random.default_rng(seed)
        n_rows = n_symbols * n_days
        symbols = np.repeat(np.asarray([f"{i:06d}.SZ" for i in range(n_symbols)], dtype=object), n_days)
        day_index = np.tile(np.arange(n_days), n_symbols)
        frame = pl.DataFrame(
            {
                "symbol": symbols,
                "day": day_index,
                "open": rng.random(n_rows),
                "high": rng.random(n_rows),
                "low": rng.random(n_rows),
                "close": rng.random(n_rows),
                "volume": rng.integers(0, 10_000_000, n_rows),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hs300_10y_synth.parquet"
            frame.write_parquet(path)

            def _run() -> None:
                pl.read_parquet(path)

            timing = _time_call(_run, repeat=3, warmup=1)
            synthetic_read_seconds = timing.median_seconds
    except Exception as exc:  # noqa: BLE001 - transparency proxy must never mask the gap
        synthetic_read_seconds = None
        proxy_note = f"synthetic read proxy unavailable: {exc!r}"
    else:
        proxy_note = (
            f"synthetic full-scale read proxy: polars read_parquet over "
            f"{n_symbols} x {n_days} = {n_symbols * n_days} OHLCV rows "
            f"= {synthetic_read_seconds:.4f}s (NOT production HS300 data)"
        )

    reason = (
        "production HS300 10y daily store absent in this environment "
        "(no real Tushare-backed dataset); synthetic uniform data is not the "
        "production dataset, so no production pass is claimed"
    )
    evidence = (
        f"benchmark:hs300_10y_read:KNOWN_RUN_GAP"
        f":synthetic_read_seconds={synthetic_read_seconds}"
    )
    return PerformanceBaselineMeasurement(
        baseline_ref=BASELINE_HS300_READ,
        metric_name="沪深300×10年日频读取 (HS300 10y daily read)",
        threshold_seconds=3.0,
        measured=False,
        observed_seconds=None,
        evidence_ref=evidence,
        unavailable_reason=reason,
        detail=proxy_note,
    )


# ─────────────────── baseline 3: Run first-screen (< 2s) — KNOWN_RUN_GAP ───────
def measure_run_first_screen(*, n_days: int = 1000, seed: int = 9) -> PerformanceBaselineMeasurement:
    """KNOWN_RUN_GAP: end-to-end first-screen needs a frontend + browser paint.

    "Run 首屏 < 2s" is a frontend paint SLO (network + React render); it cannot be
    measured in a Python-only harness, so this is an honest gap -- NOT a pass. For
    transparency we measure the real *backend* overview-series assembly
    (``run_detail_core._compute_drawdown_series`` + ``_compute_max_drawdown_series``
    over a synthetic equity frame) and record it in ``detail`` as the backend's
    contribution to the first screen.
    """
    backend_assembly_seconds: float | None = None
    try:
        import numpy as np
        import polars as pl

        from app import run_detail_core

        rng = np.random.default_rng(seed)
        equity = (1.0 + rng.standard_normal(n_days) * 0.01).cumprod()
        frame = pl.DataFrame(
            {"timestamp": [f"2020-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}" for i in range(n_days)],
             "equity": equity}
        )

        def _run() -> None:
            with_dd = run_detail_core._compute_drawdown_series(frame)
            run_detail_core._compute_max_drawdown_series(with_dd)

        timing = _time_call(_run, repeat=5, warmup=1)
        backend_assembly_seconds = timing.median_seconds
    except Exception as exc:  # noqa: BLE001 - transparency proxy must never mask the gap
        backend_assembly_seconds = None
        proxy_note = f"backend overview-assembly proxy unavailable: {exc!r}"
    else:
        proxy_note = (
            f"backend overview-series assembly proxy: drawdown + max-drawdown over "
            f"{n_days}-row equity = {backend_assembly_seconds:.4f}s "
            f"(backend contribution only; excludes browser paint + network)"
        )

    reason = (
        "end-to-end Run first-screen requires a running frontend + browser paint "
        "timing (network + React render); not measurable in a Python-only harness"
    )
    evidence = (
        f"benchmark:run_first_screen:KNOWN_RUN_GAP"
        f":backend_assembly_seconds={backend_assembly_seconds}"
    )
    return PerformanceBaselineMeasurement(
        baseline_ref=BASELINE_RUN_FIRST_SCREEN,
        metric_name="Run 首屏 (Run first-screen)",
        threshold_seconds=2.0,
        measured=False,
        observed_seconds=None,
        evidence_ref=evidence,
        unavailable_reason=reason,
        detail=proxy_note,
    )


# ───────────────────────────────── report ─────────────────────────────────────
@dataclass(frozen=True)
class BenchmarkReport:
    verdicts: tuple[PerformanceBaselineVerdict, ...]

    @property
    def passed(self) -> tuple[PerformanceBaselineVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status == PERF_PASS)

    @property
    def failed(self) -> tuple[PerformanceBaselineVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status == PERF_FAIL)

    @property
    def gaps(self) -> tuple[PerformanceBaselineVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status == PERF_KNOWN_RUN_GAP)

    @property
    def no_regression(self) -> bool:
        """True iff no *measured* baseline is over threshold (gaps are not regressions)."""
        return not self.failed

    @property
    def fully_closed(self) -> bool:
        """True iff every baseline is a real measured PASS (no FAIL, no GAP)."""
        return bool(self.verdicts) and all(v.status == PERF_PASS for v in self.verdicts)

    @property
    def exit_code(self) -> int:
        """Process exit code; exit 0 NEVER means "green" when gaps remain.

        - 1 = regression: at least one measured baseline is over threshold.
        - 0 = fully closed: every baseline is a measured PASS (no FAIL, no gap).
        - 2 = no regression but incomplete: KNOWN_RUN_GAP present, nothing failed.

        A consumer that only cares about regressions treats {0, 2} as acceptable;
        a consumer that requires full closure accepts only 0. Either way, gaps can
        never be laundered into a "green" exit 0.
        """
        if self.failed:
            return 1
        return 0 if self.fully_closed else 2

    def render(self) -> str:
        lines = ["GOAL §16 performance-baseline benchmark report", "=" * 60]
        for verdict in self.verdicts:
            m = verdict.measurement
            if verdict.status == PERF_PASS:
                badge = "GREEN/PASS"
                num = f"{m.observed_seconds:.4f}s <= {m.threshold_seconds:.1f}s"
            elif verdict.status == PERF_FAIL:
                badge = "RED/FAIL"
                num = f"{m.observed_seconds:.4f}s > {m.threshold_seconds:.1f}s"
            else:
                badge = "KNOWN_RUN_GAP"
                num = f"unavailable (threshold {m.threshold_seconds:.1f}s)"
            lines.append(f"[{badge}] {m.metric_name}")
            lines.append(f"    {num}")
            lines.append(f"    evidence: {m.evidence_ref}")
            if m.detail:
                lines.append(f"    detail:   {m.detail}")
            if m.unavailable_reason:
                lines.append(f"    gap-why:  {m.unavailable_reason}")
        lines.append("=" * 60)
        lines.append(
            f"passed={len(self.passed)} failed={len(self.failed)} "
            f"known_run_gaps={len(self.gaps)} "
            f"no_regression={self.no_regression} fully_closed={self.fully_closed}"
        )
        return "\n".join(lines)


def all_measurements() -> tuple[PerformanceBaselineMeasurement, ...]:
    """Run every baseline measurement and return raw observations (no verdicts)."""
    return (
        measure_standard_backtest(),
        measure_rag_first_results(),
        measure_asset_library_retrieval(),
        measure_hs300_10y_daily_read(),
        measure_run_first_screen(),
    )


def run_all_benchmarks() -> BenchmarkReport:
    """Measure all five baselines and classify each via the shared §16 gate."""
    return BenchmarkReport(
        tuple(classify_performance_baseline(m) for m in all_measurements())
    )


if __name__ == "__main__":
    report = run_all_benchmarks()
    print(report.render())
    # exit 1 = regression, 0 = fully closed, 2 = no regression but gaps remain.
    # exit 0 is reserved for full closure so a gappy run can never read as "green".
    sys.exit(report.exit_code)
