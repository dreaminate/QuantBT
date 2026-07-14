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
in this environment (no real HS300 10y dataset, or no configured live
frontend/authenticated browser), the baseline is recorded as ``measured=False``
-> KNOWN_RUN_GAP, never a fake pass.  The Run first-screen baseline can be closed
only by this harness driving a real Playwright login + page navigation and
observing both real-content DOM markers and the required authenticated API
responses.  A caller-provided timing number is never accepted as proof.
The HS300 gap closes only for a production DatasetVersion whose manifest,
recorded data tests, fixed 10-year/300-member content checks, and out-of-band
pinned operator provenance/universe receipts all verify around the timed reader;
a file name, caller-created key, or unsigned sidecar can never close it. No
Tushare-issued digital signature is claimed by this harness today.

Runnable:  python app/backend/tests/benchmark/perf_harness.py
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

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

RUN_PROBE_URL_ENV = "QUANTBT_PERF_RUN_URL"
RUN_PROBE_USERNAME_ENV = "QUANTBT_PERF_USERNAME"
RUN_PROBE_PASSWORD_ENV = "QUANTBT_PERF_PASSWORD"
RUN_PROBE_ALLOWED_ORIGINS_ENV = "QUANTBT_PERF_ALLOWED_RUN_ORIGINS"
HS300_DATASET_PATH_ENV = "QUANTBT_PERF_HS300_DATASET_PATH"
HS300_REGISTRY_PATH_ENV = "QUANTBT_PERF_HS300_REGISTRY_PATH"
HS300_DATASET_VERSION_REF_ENV = "QUANTBT_PERF_HS300_DATASET_VERSION_REF"
HS300_PROVENANCE_RECEIPT_ENV = "QUANTBT_PERF_HS300_PROVENANCE_RECEIPT"
HS300_UNIVERSE_SNAPSHOT_ENV = "QUANTBT_PERF_HS300_UNIVERSE_SNAPSHOT"
HS300_PROVENANCE_KEY_ENV = "QUANTBT_PERF_HS300_PROVENANCE_KEY"
_RUN_REQUIRED_SERIES = ("equity", "benchmark_return", "daily_buy", "daily_sell")

_HS300_RECEIPT_SCHEMA = "quantbt.hs300_perf_provenance.v2"
_HS300_UNIVERSE_SCHEMA = "quantbt.hs300_perf_universe.v1"
_HS300_REQUIRED_SYMBOL_COUNT = 300
_HS300_MIN_TRADING_DAYS = 2400
_HS300_MIN_CALENDAR_SPAN_DAYS = 3650
_HS300_MIN_SYMBOL_COVERAGE_RATIO = 0.80
_HS300_SOURCE_REFS = frozenset(
    {
        "tushare://daily",
        "tushare://pro/daily",
        "tushare://hs300/daily",
    }
)
_HS300_UNIVERSE_REF = "tushare://index_weight/000300.SH"
_HS300_SYMBOL_RE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_HS300_RECEIPT_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "authority_root_id",
        "key_id",
        "dataset_id",
        "dataset_version",
        "dataset_record_sha256",
        "dataset_frame_sha256",
        "manifest_sha256",
        "source_name",
        "source_ref",
        "ingestion_skill_version",
        "market",
        "interval",
        "data_kind",
        "universe_ref",
        "universe_snapshot_sha256",
        "loaded_panel_sha256",
        "row_count",
        "coverage_start_utc",
        "coverage_end_utc",
        "attested_at_utc",
    }
)
_HS300_UNIVERSE_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "authority_root_id",
        "key_id",
        "universe_ref",
        "as_of_date",
        "constituent_symbols",
    }
)
_HS300_PRODUCTION_AUTHORITY_LEVELS = frozenset({"operator_attested"})


@dataclass(frozen=True)
class TimingSample:
    median_seconds: float
    best_seconds: float
    worst_seconds: float
    repeat: int
    first_seconds: float | None = None


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
        first_seconds=samples[0],
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


# ──────────────── baseline 1: HS300 x 10y daily read (< 3s) ────────────────
@dataclass(frozen=True)
class HS300AuthorityRoot:
    """Out-of-band signer identity pinned in reviewed harness code.

    The raw verification secret is never stored here. A runtime key is usable
    only when its SHA-256 fingerprint matches a root that was independently
    reviewed and added to ``_HS300_PINNED_AUTHORITY_ROOTS``. This prevents a
    dataset caller from minting both a receipt and its own trust anchor.

    ``operator_attested`` means the named independent operator attests the
    source/universe contract. It is deliberately not ``vendor_verified``;
    this harness has no Tushare-issued signature and accepts no vendor level.
    """

    root_id: str
    key_id: str
    verification_key_sha256: str
    authority_level: str
    source_name: str
    source_refs: tuple[str, ...]
    universe_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "key_id": self.key_id,
            "verification_key_sha256": self.verification_key_sha256,
            "authority_level": self.authority_level,
            "source_name": self.source_name,
            "source_refs": list(self.source_refs),
            "universe_refs": list(self.universe_refs),
        }


# Production is intentionally GAP until a separately reviewed authority root is
# pinned here. CLI arguments, environment variables, receipts, registries and
# dataset files cannot add to this tuple.
_HS300_PINNED_AUTHORITY_ROOTS: tuple[HS300AuthorityRoot, ...] = ()


@dataclass(frozen=True)
class HS300DatasetProbeConfig:
    """Inputs for an authority-bound local HS300 dataset measurement.

    ``provenance_key`` verifies a detached receipt and is excluded from repr.
    Paths and registry labels alone are insufficient because generated data
    could otherwise be renamed and self-declared as Tushare data.
    """

    dataset_path: Path
    registry_path: Path
    dataset_version_ref: str
    provenance_receipt_path: Path
    universe_snapshot_path: Path
    provenance_key: str = field(repr=False)


@dataclass(frozen=True)
class HS300DatasetReadProof:
    timing: TimingSample
    acceptance_seconds: float
    dataset_id: str
    dataset_version: str
    authority_root_id: str
    authority_level: str
    authority_root_sha256: str
    verification_key_sha256: str
    key_id: str
    registry_sha256: str
    receipt_sha256: str
    universe_snapshot_sha256: str
    universe_as_of_date: str
    loaded_panel_sha256: str
    dataset_record_sha256: str
    dataset_frame_sha256: str
    manifest_sha256: str
    row_count: int
    symbol_count: int
    trading_day_count: int
    coverage_start: str
    coverage_end: str


class HS300DatasetUnavailable(RuntimeError):
    """The configured dataset cannot support an honest production measurement."""


class HS300BenchmarkFailure(RuntimeError):
    """A configured, authority-bound production reader failed unexpectedly."""


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_utc(value: object, *, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise HS300DatasetUnavailable(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HS300DatasetUnavailable(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise HS300DatasetUnavailable(f"{field_name} must carry a timezone")
    return parsed.astimezone(UTC)


def _read_hs300_json_object(
    path: Path, *, label: str
) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise HS300DatasetUnavailable(f"{label} is missing")
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise HS300DatasetUnavailable(f"{label} is unreadable") from exc
    if not raw_bytes or len(raw_bytes) > 1_000_000:
        raise HS300DatasetUnavailable(f"{label} has an invalid size")
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HS300DatasetUnavailable(f"{label} is unreadable") from exc
    if not isinstance(raw, dict):
        raise HS300DatasetUnavailable(f"{label} must be a JSON object")
    return raw, hashlib.sha256(raw_bytes).hexdigest()


def _verify_hs300_hmac(
    *,
    payload: dict[str, Any],
    signature: object,
    key_bytes: bytes,
    label: str,
) -> None:
    if (
        not isinstance(signature, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", signature)
    ):
        raise HS300DatasetUnavailable(f"{label} has no valid detached HMAC signature")
    expected_signature = hmac.new(
        key_bytes,
        _canonical_json_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected_signature):
        raise HS300DatasetUnavailable(f"{label} signature mismatch")


def _resolve_hs300_authority_root(
    *,
    authority_root_id: object,
    key_id: object,
    provenance_key: str,
) -> tuple[HS300AuthorityRoot, str, str]:
    if not isinstance(authority_root_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,128}", authority_root_id
    ):
        raise HS300DatasetUnavailable("HS300 authority_root_id is invalid")
    if not isinstance(key_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,128}", key_id
    ):
        raise HS300DatasetUnavailable("HS300 provenance key_id is invalid")
    key_bytes = provenance_key.encode("utf-8")
    if len(key_bytes) < 32:
        raise HS300DatasetUnavailable(
            "HS300 provenance verification key must contain at least 32 bytes"
        )
    candidates = tuple(
        root
        for root in _HS300_PINNED_AUTHORITY_ROOTS
        if root.root_id == authority_root_id
    )
    if len(candidates) != 1:
        raise HS300DatasetUnavailable(
            "HS300 signer is not pinned by an out-of-band production authority root"
        )
    root = candidates[0]
    root_payload = root.to_payload()
    if (
        root.key_id != key_id
        or root.authority_level not in _HS300_PRODUCTION_AUTHORITY_LEVELS
        or root.source_name != "tushare"
        or not root.source_refs
        or not set(root.source_refs) <= _HS300_SOURCE_REFS
        or _HS300_UNIVERSE_REF not in root.universe_refs
        or not re.fullmatch(r"[0-9a-f]{64}", root.verification_key_sha256)
    ):
        raise HS300DatasetUnavailable(
            "pinned HS300 authority root is malformed or not production-qualified"
        )
    verification_key_sha256 = hashlib.sha256(key_bytes).hexdigest()
    if not hmac.compare_digest(
        verification_key_sha256, root.verification_key_sha256
    ):
        raise HS300DatasetUnavailable(
            "HS300 provenance key does not match the pinned authority fingerprint"
        )
    authority_root_sha256 = hashlib.sha256(
        _canonical_json_bytes(root_payload)
    ).hexdigest()
    return root, authority_root_sha256, verification_key_sha256


def _load_hs300_receipt(
    config: HS300DatasetProbeConfig,
) -> tuple[dict[str, Any], HS300AuthorityRoot, str, str, str]:
    raw, receipt_sha256 = _read_hs300_json_object(
        config.provenance_receipt_path,
        label="signed HS300 provenance receipt",
    )
    expected_fields = _HS300_RECEIPT_PAYLOAD_FIELDS | {"signature_hmac_sha256"}
    if set(raw) != expected_fields:
        raise HS300DatasetUnavailable(
            "HS300 provenance receipt has missing or unknown fields"
        )
    payload = {
        field_name: raw[field_name]
        for field_name in _HS300_RECEIPT_PAYLOAD_FIELDS
    }
    root, authority_root_sha256, verification_key_sha256 = (
        _resolve_hs300_authority_root(
            authority_root_id=payload["authority_root_id"],
            key_id=payload["key_id"],
            provenance_key=config.provenance_key,
        )
    )
    _verify_hs300_hmac(
        payload=payload,
        signature=raw.get("signature_hmac_sha256"),
        key_bytes=config.provenance_key.encode("utf-8"),
        label="HS300 provenance receipt",
    )

    if payload["schema_version"] != _HS300_RECEIPT_SCHEMA:
        raise HS300DatasetUnavailable("unsupported HS300 provenance receipt schema")
    text_fields = (
        "authority_root_id",
        "key_id",
        "dataset_id",
        "dataset_version",
        "dataset_record_sha256",
        "dataset_frame_sha256",
        "manifest_sha256",
        "source_name",
        "source_ref",
        "ingestion_skill_version",
        "market",
        "interval",
        "data_kind",
        "universe_ref",
        "universe_snapshot_sha256",
        "loaded_panel_sha256",
        "coverage_start_utc",
        "coverage_end_utc",
        "attested_at_utc",
    )
    if any(
        not isinstance(payload[field_name], str)
        or not payload[field_name].strip()
        for field_name in text_fields
    ):
        raise HS300DatasetUnavailable(
            "HS300 provenance receipt contains an invalid text field"
        )
    if type(payload["row_count"]) is not int or payload["row_count"] <= 0:
        raise HS300DatasetUnavailable(
            "HS300 provenance receipt row_count must be a positive integer"
        )
    for checksum_field in (
        "dataset_record_sha256",
        "dataset_frame_sha256",
        "manifest_sha256",
        "universe_snapshot_sha256",
        "loaded_panel_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", payload[checksum_field]):
            raise HS300DatasetUnavailable(
                f"HS300 provenance receipt {checksum_field} is invalid"
            )
    attested_at = _parse_utc(
        payload["attested_at_utc"], field_name="attested_at_utc"
    )
    coverage_start = _parse_utc(
        payload["coverage_start_utc"], field_name="coverage_start_utc"
    )
    coverage_end = _parse_utc(
        payload["coverage_end_utc"], field_name="coverage_end_utc"
    )
    if coverage_end <= coverage_start:
        raise HS300DatasetUnavailable(
            "HS300 provenance receipt coverage interval is invalid"
        )
    if attested_at > datetime.now(UTC) + timedelta(minutes=5):
        raise HS300DatasetUnavailable("HS300 provenance receipt is future-dated")
    return (
        payload,
        root,
        authority_root_sha256,
        verification_key_sha256,
        receipt_sha256,
    )


def _load_hs300_universe_snapshot(
    *,
    config: HS300DatasetProbeConfig,
    root: HS300AuthorityRoot,
) -> tuple[dict[str, Any], str]:
    raw, universe_snapshot_sha256 = _read_hs300_json_object(
        config.universe_snapshot_path,
        label="signed HS300 universe snapshot",
    )
    expected_fields = _HS300_UNIVERSE_PAYLOAD_FIELDS | {"signature_hmac_sha256"}
    if set(raw) != expected_fields:
        raise HS300DatasetUnavailable(
            "HS300 universe snapshot has missing or unknown fields"
        )
    payload = {
        field_name: raw[field_name]
        for field_name in _HS300_UNIVERSE_PAYLOAD_FIELDS
    }
    if (
        payload["schema_version"] != _HS300_UNIVERSE_SCHEMA
        or payload["authority_root_id"] != root.root_id
        or payload["key_id"] != root.key_id
        or payload["universe_ref"] not in root.universe_refs
    ):
        raise HS300DatasetUnavailable(
            "HS300 universe snapshot is not bound to the pinned authority root"
        )
    _verify_hs300_hmac(
        payload=payload,
        signature=raw.get("signature_hmac_sha256"),
        key_bytes=config.provenance_key.encode("utf-8"),
        label="HS300 universe snapshot",
    )
    as_of_date = payload.get("as_of_date")
    if not isinstance(as_of_date, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of_date
    ):
        raise HS300DatasetUnavailable("HS300 universe as_of_date is invalid")
    try:
        parsed_as_of = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HS300DatasetUnavailable("HS300 universe as_of_date is invalid") from exc
    if parsed_as_of > datetime.now(UTC).date():
        raise HS300DatasetUnavailable("HS300 universe snapshot is future-dated")
    symbols = payload.get("constituent_symbols")
    if not isinstance(symbols, list) or len(symbols) != _HS300_REQUIRED_SYMBOL_COUNT:
        raise HS300DatasetUnavailable(
            "authority-bound HS300 universe must contain exactly 300 constituents"
        )
    if (
        any(not isinstance(symbol, str) for symbol in symbols)
        or symbols != sorted(symbols)
        or len(set(symbols)) != _HS300_REQUIRED_SYMBOL_COUNT
        or any(not _HS300_SYMBOL_RE.fullmatch(symbol) for symbol in symbols)
    ):
        raise HS300DatasetUnavailable(
            "authority-bound HS300 constituents must be unique sorted SH/SZ symbols"
        )
    return payload, universe_snapshot_sha256


def _validate_hs300_registry_contract(
    *,
    version: Any,
    receipt: dict[str, Any],
    manifest_sha256: str,
    root: HS300AuthorityRoot,
    universe: dict[str, Any],
    universe_snapshot_sha256: str,
) -> None:
    from app.connectors.base import is_secret_reference
    from app.data_quality import make_version_id
    from app.field_catalog.sources import is_official_source

    if (
        not isinstance(version.dataset_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", version.dataset_id)
    ):
        raise HS300DatasetUnavailable("DatasetVersion dataset_id is invalid")
    if version.source_name != "tushare" or not is_official_source(version.source_name):
        raise HS300DatasetUnavailable(
            "DatasetVersion must be recorded by the official Tushare source"
        )
    if version.source_ref not in _HS300_SOURCE_REFS:
        raise HS300DatasetUnavailable(
            "DatasetVersion source_ref is not an approved Tushare daily endpoint"
        )
    if (
        version.source_name != root.source_name
        or version.source_ref not in root.source_refs
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion source is outside the pinned authority scope"
        )
    if (
        not isinstance(version.ingestion_skill_version, str)
        or not re.fullmatch(
            r"tushare@[A-Za-z0-9._+-]{1,80}", version.ingestion_skill_version
        )
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion lacks a versioned Tushare ingestion skill"
        )
    if not is_secret_reference(version.secret_ref):
        raise HS300DatasetUnavailable(
            "DatasetVersion lacks a non-plaintext SecretRef for source authority"
        )
    if not isinstance(version.lineage_id, str) or not version.lineage_id.strip():
        raise HS300DatasetUnavailable("DatasetVersion lineage is missing")
    if version.quality_verdict != "pass":
        raise HS300DatasetUnavailable("DatasetVersion quality_verdict must be pass")
    ge_results = version.ge_results
    if (
        not isinstance(ge_results, list)
        or len(ge_results) < 5
        or any(
            not isinstance(result, dict)
            or result.get("passed") is not True
            or type(result.get("failed_count")) is not int
            or result.get("failed_count") != 0
            or not isinstance(result.get("column"), str)
            or not result.get("column")
            or not isinstance(result.get("rule_type"), str)
            or not result.get("rule_type")
            for result in ge_results
        )
        or len(
            {
                (result["column"], result["rule_type"])
                for result in ge_results
            }
        )
        < 5
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion needs at least five distinct recorded passing data tests"
        )
    metadata = version.metadata
    if not isinstance(metadata, dict):
        raise HS300DatasetUnavailable("DatasetVersion metadata is malformed")
    if metadata.get("market") != "stocks_cn":
        raise HS300DatasetUnavailable("DatasetVersion market must be stocks_cn")
    if metadata.get("interval") != "1d":
        raise HS300DatasetUnavailable("DatasetVersion interval must be 1d")
    if metadata.get("data_kind") not in {"ohlcv", "daily"}:
        raise HS300DatasetUnavailable(
            "DatasetVersion data_kind must be ohlcv or daily"
        )
    raw_columns = metadata.get("columns")
    if (
        not isinstance(raw_columns, list)
        or any(not isinstance(column, str) for column in raw_columns)
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion metadata columns must be a string list"
        )
    columns = set(raw_columns)
    required_columns = {"open", "high", "low", "close"}
    if (
        not required_columns <= columns
        or not columns.intersection({"ts", "timestamp", "trade_date"})
        or not columns.intersection({"symbol", "ts_code"})
        or not columns.intersection({"volume", "vol"})
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion metadata does not declare the canonical OHLCV keys"
        )
    if (
        not isinstance(version.sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", version.sha256.lower())
    ):
        raise HS300DatasetUnavailable("DatasetVersion frame checksum is invalid")
    if version.version_id != make_version_id(
        version.fetched_at_utc,
        version.sha256,
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion version_id does not match its canonical identity"
        )
    if type(version.row_count) is not int or version.row_count <= 0:
        raise HS300DatasetUnavailable(
            "DatasetVersion row_count must be a positive integer"
        )

    expected = {
        "dataset_id": version.dataset_id,
        "dataset_version": version.version_id,
        "dataset_record_sha256": hashlib.sha256(
            _canonical_json_bytes(version.to_dict())
        ).hexdigest(),
        "dataset_frame_sha256": version.sha256,
        "manifest_sha256": manifest_sha256,
        "source_name": version.source_name,
        "source_ref": version.source_ref,
        "ingestion_skill_version": version.ingestion_skill_version,
        "market": metadata.get("market"),
        "interval": metadata.get("interval"),
        "data_kind": metadata.get("data_kind"),
        "row_count": version.row_count,
        "coverage_start_utc": version.coverage_start_utc,
        "coverage_end_utc": version.coverage_end_utc,
    }
    mismatches = [
        name for name, value in expected.items() if receipt.get(name) != value
    ]
    if mismatches:
        raise HS300DatasetUnavailable(
            "signed provenance does not exactly bind DatasetVersion fields: "
            + ", ".join(sorted(mismatches))
        )
    if receipt.get("universe_ref") != _HS300_UNIVERSE_REF:
        raise HS300DatasetUnavailable(
            "signed provenance does not bind the Tushare HS300 index-weight universe"
        )
    if receipt.get("authority_root_id") != root.root_id:
        raise HS300DatasetUnavailable(
            "signed provenance does not bind the pinned authority root"
        )
    if receipt.get("universe_snapshot_sha256") != universe_snapshot_sha256:
        raise HS300DatasetUnavailable(
            "signed provenance does not bind the exact HS300 universe snapshot"
        )
    coverage_end = _parse_utc(
        version.coverage_end_utc,
        field_name="coverage_end_utc",
    )
    if universe.get("as_of_date") != coverage_end.date().isoformat():
        raise HS300DatasetUnavailable(
            "HS300 universe as_of_date must equal the dataset coverage end date"
        )
    fetched_at = _parse_utc(version.fetched_at_utc, field_name="fetched_at_utc")
    attested_at = _parse_utc(
        receipt["attested_at_utc"], field_name="attested_at_utc"
    )
    if attested_at < fetched_at:
        raise HS300DatasetUnavailable(
            "HS300 provenance receipt predates the recorded dataset fetch"
        )


def _load_hs300_manifest_and_paths(
    *,
    config: HS300DatasetProbeConfig,
    version: Any,
    verify_files: bool = True,
) -> tuple[Any, str, tuple[Path, ...]]:
    from app.data_hash.dataset_hash import DatasetManifest, verify_manifest

    if not version.manifest_path:
        raise HS300DatasetUnavailable("DatasetVersion has no immutable file manifest")
    manifest_path = Path(version.manifest_path).expanduser()
    if not manifest_path.is_file():
        raise HS300DatasetUnavailable("DatasetVersion file manifest is missing")
    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HS300DatasetUnavailable("DatasetVersion file manifest is unreadable") from exc
    manifest_fields = {
        "dataset_id",
        "version",
        "files",
        "created_at_utc",
        "total_size_bytes",
        "total_row_count",
    }
    if not isinstance(manifest_raw, dict) or set(manifest_raw) != manifest_fields:
        raise HS300DatasetUnavailable("DatasetVersion file manifest is malformed")
    raw_files = manifest_raw.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise HS300DatasetUnavailable("DatasetVersion file manifest contains no files")
    file_fields = {"relative_path", "sha256", "size_bytes", "row_count"}
    if any(
        not isinstance(item, dict) or set(item) != file_fields
        for item in raw_files
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion manifest file entries are malformed"
        )
    try:
        manifest = DatasetManifest.from_dict(manifest_raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise HS300DatasetUnavailable("DatasetVersion file manifest is malformed") from exc
    if manifest.dataset_id != version.dataset_id or manifest.version != version.version_id:
        raise HS300DatasetUnavailable(
            "DatasetVersion file manifest identity does not match the registry"
        )

    relative_paths: list[str] = []
    for entry in manifest.files:
        relative = PurePosixPath(entry.relative_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise HS300DatasetUnavailable(
                "DatasetVersion manifest contains an unsafe path"
            )
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(entry.sha256).lower())
            or type(entry.size_bytes) is not int
            or entry.size_bytes <= 0
            or type(entry.row_count) is not int
            or entry.row_count <= 0
            or relative.suffix.lower() != ".parquet"
        ):
            raise HS300DatasetUnavailable(
                "DatasetVersion manifest requires hashed non-empty parquet entries"
            )
        relative_paths.append(relative.as_posix())
    if len(relative_paths) != len(set(relative_paths)):
        raise HS300DatasetUnavailable(
            "DatasetVersion manifest contains duplicate paths"
        )
    if sum(entry.size_bytes for entry in manifest.files) != manifest.total_size_bytes:
        raise HS300DatasetUnavailable(
            "DatasetVersion manifest entry sizes do not match total_size_bytes"
        )
    if (
        sum(entry.row_count for entry in manifest.files)
        != manifest.total_row_count
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion manifest entry rows do not match total_row_count"
        )

    file_paths = tuple(
        Path(value).expanduser() for value in (version.file_paths or ())
    )
    if not file_paths or any(not path.is_file() for path in file_paths):
        raise HS300DatasetUnavailable(
            "DatasetVersion physical parquet files are missing"
        )
    if len(file_paths) == 1:
        root = file_paths[0].parent
    else:
        root = Path(os.path.commonpath([str(path) for path in file_paths]))
        if not root.is_dir():
            root = root.parent
    try:
        recorded_relatives = [
            path.relative_to(root).as_posix() for path in file_paths
        ]
    except ValueError as exc:
        raise HS300DatasetUnavailable(
            "DatasetVersion files do not share the recorded manifest root"
        ) from exc
    if sorted(recorded_relatives) != sorted(relative_paths):
        raise HS300DatasetUnavailable(
            "DatasetVersion file_paths do not exactly match the immutable manifest"
        )

    configured_path = config.dataset_path.expanduser()
    if configured_path.is_file():
        if (
            len(file_paths) != 1
            or configured_path.resolve() != file_paths[0].resolve()
        ):
            raise HS300DatasetUnavailable(
                "configured HS300 dataset file does not match DatasetVersion"
            )
    elif configured_path.is_dir():
        configured_root = configured_path.resolve()
        if any(
            not path.resolve().is_relative_to(configured_root)
            for path in file_paths
        ):
            raise HS300DatasetUnavailable(
                "configured HS300 dataset directory does not contain all versioned files"
            )
    else:
        raise HS300DatasetUnavailable("configured HS300 dataset path is missing")

    if verify_files:
        ok, mismatches = verify_manifest(manifest_path, root)
        if not ok:
            raise HS300DatasetUnavailable(
                "DatasetVersion manifest verification failed: " + "; ".join(mismatches)
            )
    actual_total_size = sum(path.stat().st_size for path in file_paths)
    if manifest.total_size_bytes != actual_total_size:
        raise HS300DatasetUnavailable(
            "DatasetVersion manifest total_size_bytes mismatch"
        )
    if manifest.total_row_count != version.row_count:
        raise HS300DatasetUnavailable(
            "DatasetVersion row_count does not match its file manifest"
        )
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return manifest, manifest_sha256, file_paths


def _hs300_loaded_panel_sha256(frame: Any) -> str:
    """Hash the exact canonical reader output independently of file encoding."""
    import polars as pl

    from app.connectors.base import _sha256_of_frame

    canonical_columns = [
        "ts",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    canonical = (
        frame.select(canonical_columns)
        .with_columns(
            [
                pl.col(column).cast(pl.Float64, strict=False).alias(column)
                for column in ("open", "high", "low", "close", "volume")
            ]
        )
        .sort(["symbol", "ts"])
        .rechunk()
    )
    return _sha256_of_frame(canonical)


def _materialize_hs300_manifest_snapshot(
    *,
    manifest: Any,
    file_paths: tuple[Path, ...],
    snapshot_dir: Path,
) -> tuple[Path, ...]:
    """Create private byte-exact inputs for one timed reader sample.

    Reading, hashing and writing the private snapshots all happen inside the
    timed sample. The FieldCatalog helper then consumes only these snapshots,
    so an original pathname cannot be swapped to a different parquet encoding
    during the read and restored before post-validation.
    """
    if len(file_paths) == 1:
        root = file_paths[0].parent
    else:
        root = Path(os.path.commonpath([str(path) for path in file_paths]))
        if not root.is_dir():
            root = root.parent
    entries = {
        PurePosixPath(entry.relative_path).as_posix(): entry
        for entry in manifest.files
    }
    snapshots: list[Path] = []
    for index, path in enumerate(file_paths):
        try:
            relative = path.relative_to(root).as_posix()
            entry = entries[relative]
            raw = path.read_bytes()
        except (KeyError, OSError, ValueError) as exc:
            raise HS300DatasetUnavailable(
                "manifest-bound HS300 file could not be snapshotted"
            ) from exc
        if (
            len(raw) != entry.size_bytes
            or hashlib.sha256(raw).hexdigest() != entry.sha256
        ):
            raise HS300DatasetUnavailable(
                "timed HS300 input bytes do not match the immutable manifest"
            )
        snapshot = snapshot_dir / f"{index:04d}-{path.name}"
        try:
            written = snapshot.write_bytes(raw)
            os.chmod(snapshot, 0o400)
        except OSError as exc:
            raise HS300DatasetUnavailable(
                "private manifest-bound HS300 snapshot could not be written"
            ) from exc
        if written != len(raw):
            raise HS300DatasetUnavailable(
                "private manifest-bound HS300 snapshot was only partially written"
            )
        snapshots.append(snapshot)
    return tuple(snapshots)


def _validate_hs300_panel(
    *,
    frame: Any,
    version: Any,
    manifest: Any,
    receipt: dict[str, Any],
    universe: dict[str, Any],
) -> tuple[Any, int, int, str, str, str]:
    import polars as pl

    if frame is None or not isinstance(frame, pl.DataFrame) or frame.is_empty():
        raise HS300DatasetUnavailable(
            "production FieldCatalog loader returned no rows"
        )
    if "volume" not in frame.columns and "vol" in frame.columns:
        frame = frame.rename({"vol": "volume"})
    elif "volume" in frame.columns and "vol" in frame.columns:
        frame = frame.with_columns(
            pl.coalesce([pl.col("volume"), pl.col("vol")]).alias("volume")
        ).drop("vol")
    required = {"ts", "symbol", "open", "high", "low", "close", "volume"}
    if not required <= set(frame.columns):
        raise HS300DatasetUnavailable(
            "loaded HS300 panel lacks canonical OHLCV columns"
        )
    frame = frame.select(sorted(required)).with_columns(
        [
            pl.col(column).cast(pl.Float64, strict=False).alias(column)
            for column in ("open", "high", "low", "close", "volume")
        ]
    )
    if frame.height != version.row_count or frame.height != manifest.total_row_count:
        raise HS300DatasetUnavailable(
            "production loader row count does not match DatasetVersion and manifest"
        )
    if frame.select(pl.struct(["ts", "symbol"]).n_unique()).item() != frame.height:
        raise HS300DatasetUnavailable(
            "HS300 panel contains duplicate (ts, symbol) rows"
        )
    frame = frame.with_columns(
        pl.col("ts").dt.date().alias("__hs300_trading_date")
    )
    if (
        frame.select(
            pl.struct(["__hs300_trading_date", "symbol"]).n_unique()
        ).item()
        != frame.height
    ):
        raise HS300DatasetUnavailable(
            "daily HS300 panel contains multiple rows for one (trading_date, symbol)"
        )
    if any(frame.get_column(column).null_count() for column in required):
        raise HS300DatasetUnavailable(
            "HS300 panel contains null canonical OHLCV values"
        )
    for column in ("open", "high", "low", "close", "volume"):
        if frame.select((~pl.col(column).is_finite()).any()).item():
            raise HS300DatasetUnavailable(
                f"HS300 panel contains non-finite {column} values"
            )
    if frame.select(
        (
            (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
            | (pl.col("volume") < 0)
            | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
        ).any()
    ).item():
        raise HS300DatasetUnavailable(
            "HS300 panel violates OHLCV price/volume invariants"
        )

    symbols = sorted(frame.get_column("symbol").unique().to_list())
    if symbols != universe["constituent_symbols"]:
        raise HS300DatasetUnavailable(
            "loaded symbols do not exactly match the authority-bound HS300 membership snapshot"
        )
    symbol_count = len(symbols)
    trading_day_count = frame.get_column("__hs300_trading_date").n_unique()
    if trading_day_count < _HS300_MIN_TRADING_DAYS:
        raise HS300DatasetUnavailable(
            f"HS300 panel has only {trading_day_count} distinct trading days"
        )
    if frame.select((pl.col("__hs300_trading_date").dt.weekday() > 5).any()).item():
        raise HS300DatasetUnavailable("HS300 panel contains weekend dates")
    coverage_start_value = frame.get_column("ts").min()
    coverage_end_value = frame.get_column("ts").max()
    span_days = (
        coverage_end_value - coverage_start_value
    ).total_seconds() / 86400.0
    if span_days < _HS300_MIN_CALENDAR_SPAN_DAYS:
        raise HS300DatasetUnavailable(
            f"HS300 panel spans only {span_days:.0f} calendar days"
        )
    min_symbol_days = (
        frame.group_by("symbol")
        .agg(pl.col("__hs300_trading_date").n_unique().alias("trading_days"))
        .get_column("trading_days")
        .min()
    )
    if min_symbol_days < math.ceil(
        trading_day_count * _HS300_MIN_SYMBOL_COVERAGE_RATIO
    ):
        raise HS300DatasetUnavailable(
            "one or more signed HS300 constituents lack 80% daily coverage"
        )

    recorded_start = _parse_utc(
        version.coverage_start_utc, field_name="coverage_start_utc"
    )
    recorded_end = _parse_utc(
        version.coverage_end_utc, field_name="coverage_end_utc"
    )
    actual_start = coverage_start_value.astimezone(UTC)
    actual_end = coverage_end_value.astimezone(UTC)
    if recorded_start != actual_start or recorded_end != actual_end:
        raise HS300DatasetUnavailable(
            "DatasetVersion coverage bounds do not match the loaded panel"
        )
    loaded_panel_sha256 = _hs300_loaded_panel_sha256(
        frame.drop("__hs300_trading_date")
    )
    if receipt.get("loaded_panel_sha256") != loaded_panel_sha256:
        raise HS300DatasetUnavailable(
            "production reader output does not match the authority-bound panel hash "
            f"(expected={receipt.get('loaded_panel_sha256')}, actual={loaded_panel_sha256})"
        )
    return (
        frame.drop("__hs300_trading_date"),
        symbol_count,
        trading_day_count,
        actual_start.isoformat(),
        actual_end.isoformat(),
        loaded_panel_sha256,
    )


def _measure_verified_hs300_read(
    config: HS300DatasetProbeConfig,
) -> HS300DatasetReadProof:
    from app.data_quality import DatasetRegistry
    from app.field_catalog.catalog import _read_dataset
    from app.field_catalog.contract import DatasetInfo, FileRef

    if not config.registry_path.is_file():
        raise HS300DatasetUnavailable("production DatasetRegistry is missing")
    try:
        registry_sha256 = hashlib.sha256(
            config.registry_path.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise HS300DatasetUnavailable("production DatasetRegistry is unreadable") from exc
    registry = DatasetRegistry(config.registry_path)
    try:
        version = registry.resolve_version_ref(config.dataset_version_ref)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HS300DatasetUnavailable(
            "configured dataset_version_ref is absent or ambiguous"
        ) from exc
    if hashlib.sha256(config.registry_path.read_bytes()).hexdigest() != registry_sha256:
        raise HS300DatasetUnavailable(
            "DatasetRegistry changed while resolving the selected version"
        )

    (
        receipt,
        root,
        authority_root_sha256,
        verification_key_sha256,
        receipt_sha256,
    ) = _load_hs300_receipt(config)
    universe, universe_snapshot_sha256 = _load_hs300_universe_snapshot(
        config=config,
        root=root,
    )
    if (
        receipt.get("universe_snapshot_sha256") != universe_snapshot_sha256
        or receipt.get("universe_ref") != universe.get("universe_ref")
    ):
        raise HS300DatasetUnavailable(
            "provenance receipt does not bind the exact authority-signed universe"
        )
    manifest, manifest_sha256, file_paths = _load_hs300_manifest_and_paths(
        config=config,
        version=version,
        verify_files=False,
    )
    _validate_hs300_registry_contract(
        version=version,
        receipt=receipt,
        manifest_sha256=manifest_sha256,
        root=root,
        universe=universe,
        universe_snapshot_sha256=universe_snapshot_sha256,
    )

    metadata = version.metadata
    file_refs = []
    for path in file_paths:
        stem = path.name.removesuffix(".parquet")
        file_symbol = stem if _HS300_SYMBOL_RE.fullmatch(stem) else None
        file_refs.append(FileRef(str(path), file_symbol))
    dataset = DatasetInfo(
        dataset_id=version.dataset_id,
        source_name=version.source_name,
        market=metadata["market"],
        interval=metadata["interval"],
        data_kind=metadata["data_kind"],
        columns=list(metadata.get("columns") or ()),
        files=file_refs,
    )
    captured_frames: list[Any] = []

    def _run() -> None:
        with tempfile.TemporaryDirectory(prefix="quantbt-hs300-snapshot-") as tmp:
            snapshot_paths = _materialize_hs300_manifest_snapshot(
                manifest=manifest,
                file_paths=file_paths,
                snapshot_dir=Path(tmp),
            )
            snapshot_dataset = DatasetInfo(
                dataset_id=dataset.dataset_id,
                source_name=dataset.source_name,
                market=dataset.market,
                interval=dataset.interval,
                data_kind=dataset.data_kind,
                columns=list(dataset.columns),
                files=[
                    FileRef(str(snapshot), original_ref.symbol)
                    for snapshot, original_ref in zip(
                        snapshot_paths,
                        dataset.files,
                        strict=True,
                    )
                ],
            )
            loaded = _read_dataset(
                snapshot_dataset,
                {"open", "high", "low", "close", "volume", "vol"},
                None,
            )
            if loaded is None or loaded.is_empty():
                raise HS300BenchmarkFailure(
                    "configured production FieldCatalog reader returned no HS300 rows; "
                    "the reader may have swallowed an internal file-read exception"
                )
            if (
                loaded.height != version.row_count
                or loaded.height != manifest.total_row_count
            ):
                raise HS300BenchmarkFailure(
                    "configured production FieldCatalog reader returned a partial "
                    "authority-bound dataset; one or more file-read errors may have "
                    "been swallowed"
                )
        iteration_manifest, iteration_manifest_sha256, iteration_paths = (
            _load_hs300_manifest_and_paths(
                config=config,
                version=version,
                verify_files=True,
            )
        )
        if (
            iteration_manifest != manifest
            or iteration_manifest_sha256 != manifest_sha256
            or tuple(path.resolve() for path in iteration_paths)
            != tuple(path.resolve() for path in file_paths)
        ):
            raise HS300DatasetUnavailable(
                "timed reader did not consume the manifest-bound file set"
            )
        captured_frames.append(loaded)

    # No proxy or untimed reader call precedes this configured path. Each sample
    # includes the reader plus immediate manifest-byte verification, so a faster
    # alternate parquet encoding cannot be timed and swapped back before replay.
    timing = _time_call(_run, repeat=3, warmup=0)
    if len(captured_frames) != timing.repeat:
        raise HS300DatasetUnavailable(
            "timed reader sample count does not match the reported timing sample"
        )
    validated_reads = tuple(
        _validate_hs300_panel(
            frame=frame,
            version=version,
            manifest=manifest,
            receipt=receipt,
            universe=universe,
        )
        for frame in captured_frames
    )
    if not validated_reads:
        raise HS300DatasetUnavailable("timed reader produced no validated samples")
    read_bindings = tuple(result[1:] for result in validated_reads)
    if any(binding != read_bindings[0] for binding in read_bindings[1:]):
        raise HS300DatasetUnavailable(
            "timed reader samples do not share one authority-bound identity"
        )
    (
        symbol_count,
        trading_day_count,
        coverage_start,
        coverage_end,
        loaded_panel_sha256,
    ) = read_bindings[0]
    first_sample_seconds = (
        timing.first_seconds
        if timing.first_seconds is not None
        else timing.median_seconds
    )
    acceptance_seconds = max(first_sample_seconds, timing.median_seconds)

    # Re-open every mutable proof surface after timing. A persistent mutation of
    # receipt, registry, universe, manifest or data files must prevent emission
    # of a measured result; manifest verification rehashes every parquet file.
    try:
        replayed_registry_sha256 = hashlib.sha256(
            config.registry_path.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise HS300DatasetUnavailable(
            "DatasetRegistry could not be reread after the timed read"
        ) from exc
    if replayed_registry_sha256 != registry_sha256:
        raise HS300DatasetUnavailable(
            "DatasetRegistry bytes changed during the timed read"
        )
    try:
        replayed_version = DatasetRegistry(config.registry_path).resolve_version_ref(
            config.dataset_version_ref
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HS300DatasetUnavailable(
            "DatasetVersion could not be replayed after the timed read"
        ) from exc
    if replayed_version != version:
        raise HS300DatasetUnavailable(
            "DatasetVersion changed during the timed read"
        )
    (
        replayed_receipt,
        replayed_root,
        replayed_authority_root_sha256,
        replayed_verification_key_sha256,
        replayed_receipt_sha256,
    ) = _load_hs300_receipt(config)
    replayed_universe, replayed_universe_snapshot_sha256 = (
        _load_hs300_universe_snapshot(
            config=config,
            root=replayed_root,
        )
    )
    if (
        replayed_receipt != receipt
        or replayed_root != root
        or replayed_authority_root_sha256 != authority_root_sha256
        or replayed_verification_key_sha256 != verification_key_sha256
        or replayed_receipt_sha256 != receipt_sha256
        or replayed_universe != universe
        or replayed_universe_snapshot_sha256 != universe_snapshot_sha256
    ):
        raise HS300DatasetUnavailable(
            "HS300 authority, receipt or universe changed during the timed read"
        )
    replayed_manifest, replayed_manifest_sha256, replayed_paths = (
        _load_hs300_manifest_and_paths(
            config=config,
            version=replayed_version,
        )
    )
    if (
        replayed_manifest != manifest
        or replayed_manifest_sha256 != manifest_sha256
        or tuple(path.resolve() for path in replayed_paths)
        != tuple(path.resolve() for path in file_paths)
    ):
        raise HS300DatasetUnavailable(
            "DatasetVersion manifest changed during the timed read"
        )
    _validate_hs300_registry_contract(
        version=replayed_version,
        receipt=replayed_receipt,
        manifest_sha256=replayed_manifest_sha256,
        root=replayed_root,
        universe=replayed_universe,
        universe_snapshot_sha256=replayed_universe_snapshot_sha256,
    )
    return HS300DatasetReadProof(
        timing=timing,
        acceptance_seconds=acceptance_seconds,
        dataset_id=version.dataset_id,
        dataset_version=version.version_id,
        authority_root_id=root.root_id,
        authority_level=root.authority_level,
        authority_root_sha256=authority_root_sha256,
        verification_key_sha256=verification_key_sha256,
        key_id=root.key_id,
        registry_sha256=registry_sha256,
        receipt_sha256=receipt_sha256,
        universe_snapshot_sha256=universe_snapshot_sha256,
        universe_as_of_date=universe["as_of_date"],
        loaded_panel_sha256=loaded_panel_sha256,
        dataset_record_sha256=receipt["dataset_record_sha256"],
        dataset_frame_sha256=version.sha256,
        manifest_sha256=manifest_sha256,
        row_count=version.row_count,
        symbol_count=symbol_count,
        trading_day_count=trading_day_count,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )


def _hs300_synthetic_proxy(
    *, n_symbols: int, n_days: int, seed: int
) -> tuple[str, float | None]:
    """Keep the historical full-scale proxy visible without treating it as proof."""
    synthetic_read_seconds: float | None = None
    try:
        import numpy as np
        import polars as pl

        rng = np.random.default_rng(seed)
        n_rows = n_symbols * n_days
        symbols = np.repeat(
            np.asarray(
                [f"{i:06d}.SZ" for i in range(n_symbols)],
                dtype=object,
            ),
            n_days,
        )
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
    except Exception as exc:  # noqa: BLE001 - proxy failure must never mask the gap
        proxy_note = f"synthetic read proxy unavailable: {type(exc).__name__}"
    else:
        proxy_note = (
            f"synthetic full-scale read proxy: polars read_parquet over "
            f"{n_symbols} x {n_days} = {n_symbols * n_days} OHLCV rows "
            f"= {synthetic_read_seconds:.4f}s (NOT production HS300 data)"
        )

    return proxy_note, synthetic_read_seconds


def _safe_hs300_error(
    exc: BaseException, config: HS300DatasetProbeConfig
) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if config.provenance_key:
        message = message.replace(config.provenance_key, "<redacted>")
    return message


def measure_hs300_10y_daily_read(
    *,
    dataset_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    dataset_version_ref: str | None = None,
    provenance_receipt_path: str | Path | None = None,
    universe_snapshot_path: str | Path | None = None,
    provenance_key: str | None = None,
    n_symbols: int = 300,
    n_days: int = 2430,
    seed: int = 3,
) -> PerformanceBaselineMeasurement:
    """Measure a provenance-bound production HS300 read, or return an honest GAP.

    A valid measurement requires an exact production ``DatasetVersion``, its
    immutable per-file manifest, at least five recorded passing data tests, and
    a detached HMAC receipt whose key fingerprint is pinned in reviewed code by
    an out-of-band authority root. The receipt binds the Tushare source contract
    and a separately signed exact ``000300.SH`` index-weight membership snapshot
    to the version, manifest and reader-output hashes. The timed operation is the
    manifest-byte snapshot materialization plus the repository's real
    ``FieldCatalog`` disk-reader path, including its first reader call.

    ``operator_attested`` is an operator trust boundary, not a claim that Tushare
    itself digitally signed the files. This schema cannot emit vendor verification.
    Without the out-of-band root and authority-bound universe the result remains
    ``KNOWN_RUN_GAP``. ``n_symbols``/``n_days`` affect only the labelled synthetic
    diagnostic; production acceptance thresholds are fixed constants.
    """
    inputs = {
        "dataset path": dataset_path,
        "DatasetRegistry path": registry_path,
        "dataset_version_ref": dataset_version_ref,
        "signed provenance receipt": provenance_receipt_path,
        "signed universe snapshot": universe_snapshot_path,
        "provenance verification key": provenance_key,
    }
    provided = {name: value is not None for name, value in inputs.items()}
    proxy_note = "synthetic diagnostic not run before configured production reader"
    synthetic_read_seconds: float | None = None
    if not all(provided.values()):
        proxy_note, synthetic_read_seconds = _hs300_synthetic_proxy(
            n_symbols=n_symbols,
            n_days=n_days,
            seed=seed,
        )
    if not any(provided.values()):
        reason = (
            "production HS300 10y dataset proof not configured; require a real "
            "DatasetVersion + immutable manifest + out-of-band pinned authority "
            "+ signed provenance/universe receipts"
        )
    elif not all(provided.values()):
        missing = sorted(
            name for name, present in provided.items() if not present
        )
        reason = (
            "HS300 production probe configuration incomplete; missing "
            + ", ".join(missing)
        )
    else:
        config = HS300DatasetProbeConfig(
            dataset_path=Path(dataset_path or ""),
            registry_path=Path(registry_path or ""),
            dataset_version_ref=str(dataset_version_ref or ""),
            provenance_receipt_path=Path(provenance_receipt_path or ""),
            universe_snapshot_path=Path(universe_snapshot_path or ""),
            provenance_key=str(provenance_key or ""),
        )
        try:
            proof = _measure_verified_hs300_read(config)
        except HS300DatasetUnavailable as exc:
            reason = _safe_hs300_error(exc, config)
            proxy_note, synthetic_read_seconds = _hs300_synthetic_proxy(
                n_symbols=n_symbols,
                n_days=n_days,
                seed=seed,
            )
        else:
            timing = proof.timing
            evidence = (
                "benchmark:hs300_10y_read"
                f":dataset_id={proof.dataset_id}"
                f":dataset_version={proof.dataset_version}"
                f":authority_root_id={proof.authority_root_id}"
                f":authority_level={proof.authority_level}"
                f":authority_root_sha256={proof.authority_root_sha256}"
                f":verification_key_sha256={proof.verification_key_sha256}"
                f":key_id={proof.key_id}"
                f":registry_sha256={proof.registry_sha256}"
                f":receipt_sha256={proof.receipt_sha256}"
                f":universe_snapshot_sha256={proof.universe_snapshot_sha256}"
                f":universe_as_of_date={proof.universe_as_of_date}"
                f":loaded_panel_sha256={proof.loaded_panel_sha256}"
                f":dataset_record_sha256={proof.dataset_record_sha256}"
                f":frame_sha256={proof.dataset_frame_sha256}"
                f":manifest_sha256={proof.manifest_sha256}"
                ":authority_bound_provenance=True"
                ":manifest_byte_snapshot=True"
                f":symbols={proof.symbol_count}"
                f":trading_days={proof.trading_day_count}"
                f":rows={proof.row_count}"
                f":first_sample_s={(timing.first_seconds if timing.first_seconds is not None else timing.median_seconds):.4f}"
                f":median_s={timing.median_seconds:.4f}"
                f":acceptance_s={proof.acceptance_seconds:.4f}"
            )
            detail = (
                "byte-exact private manifest snapshot materialization plus the "
                "production FieldCatalog disk-reader over a manifest-verified, "
                f"{proof.authority_level} Tushare/000300.SH contract; "
                f"{proof.symbol_count} authority-bound constituents from the fixed "
                f"as-of {proof.universe_as_of_date} snapshot x "
                f"{proof.trading_day_count} trading days, {proof.row_count} rows, "
                f"coverage={proof.coverage_start}..{proof.coverage_end}; "
                f"first_sample={(timing.first_seconds if timing.first_seconds is not None else timing.median_seconds):.4f}s "
                f"median={timing.median_seconds:.4f}s "
                f"best={timing.best_seconds:.4f}s "
                f"worst={timing.worst_seconds:.4f}s over {timing.repeat} runs. "
                f"Acceptance uses max(first-sample, median)={proof.acceptance_seconds:.4f}s; "
                "No proxy or untimed loader/hash warmup precedes the configured sample. "
                "Each timed sample begins by reading and hashing the original manifest bytes into "
                "private read-only parquet snapshots, makes FieldCatalog consume only "
                "those snapshots, then rehashes every original versioned file before "
                "returning. Post-timing verification repeats that check; receipt, "
                "registry, universe and authority bindings are replayed "
                "before this result is emitted. This records the first reader call, "
                "not a guaranteed operating-system cold-cache state. "
                "Authority level is reported literally; operator_attested is not a "
                "Tushare-issued digital signature. The cohort is one signed as-of "
                "snapshot, not proof of a historical point-in-time membership timeline."
            )
            return PerformanceBaselineMeasurement(
                baseline_ref=BASELINE_HS300_READ,
                metric_name="沪深300×10年日频读取 (HS300 10y daily read)",
                threshold_seconds=3.0,
                measured=True,
                observed_seconds=proof.acceptance_seconds,
                evidence_ref=evidence,
                detail=detail,
            )

    evidence = (
        "benchmark:hs300_10y_read:KNOWN_RUN_GAP"
        f":production_probe_configured={all(provided.values())}"
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
        detail=f"{proxy_note}; production probe: {reason}",
    )


# ───────────────────── baseline 3: Run first-screen (< 2s) ────────────────────
@dataclass(frozen=True)
class RunFirstScreenProbeConfig:
    """Inputs needed for an executable authenticated browser measurement.

    ``password`` is excluded from repr so a failed probe/report cannot disclose
    it accidentally.  The command-line interface accepts the password only via
    a named environment variable, keeping it out of the process argument list.
    """

    run_url: str
    username: str
    password: str = field(repr=False)
    timeout_seconds: float = 15.0
    allowed_origins: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunApiObservation:
    """One browser-observed Run API response, reduced to validation evidence."""

    key: str
    status: int
    has_bearer: bool
    payload: Any


@dataclass(frozen=True)
class RunFirstScreenObservation:
    """Pure-data boundary between Playwright collection and strict validation."""

    run_id: str
    navigation_status: int
    dom_state: str
    api_responses: tuple[RunApiObservation, ...]


@dataclass(frozen=True)
class RunFirstScreenProbeResult:
    observed_seconds: float
    observation: RunFirstScreenObservation


class RunFirstScreenUnavailable(RuntimeError):
    """The real browser proof could not be collected; callers must report GAP."""


def _request_uses_login_token(authorization: str, token: str) -> bool:
    """Bind request evidence to the fresh login token without retaining it."""
    if not authorization or not token:
        return False
    return hmac.compare_digest(authorization, f"Bearer {token}")


def _safe_probe_error(exc: BaseException, config: RunFirstScreenProbeConfig) -> str:
    """Return an exception description with configured credentials redacted."""
    message = f"{type(exc).__name__}: {exc}"
    for secret in (config.password, config.username):
        if secret:
            message = message.replace(secret, "<redacted>")
    try:
        parts = urlsplit(config.run_url)
        if parts.query:
            safe_url = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, "<redacted>", "")
            )
            message = message.replace(config.run_url, safe_url)
    except Exception:
        pass
    message = re.sub(
        r"([?&][^=\s?#&]+)=([^&#\s]+)",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer <redacted>", message)
    return message


def _normalized_allowed_origins(values: tuple[str, ...]) -> frozenset[str]:
    origins: set[str] = set()
    for raw in values:
        parts = urlsplit(str(raw or "").strip())
        if (
            parts.scheme != "https"
            or not parts.netloc
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "allowed remote Run origins must be exact credential-free HTTPS origins"
            )
        origins.add(urlunsplit((parts.scheme, parts.netloc, "", "", "")))
    return frozenset(origins)


def _is_loopback_host(hostname: str | None) -> bool:
    host = str(hostname or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_run_url(
    run_url: str,
    *,
    allowed_origins: tuple[str, ...] = (),
) -> tuple[str, str]:
    if not run_url or any(ord(char) < 32 or ord(char) == 127 for char in run_url):
        raise ValueError("Run URL must be a stable non-empty string without control characters")
    parts = urlsplit(run_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Run URL must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Run URL must not contain user-info credentials")
    if parts.fragment:
        raise ValueError("Run URL must not contain a fragment")
    if parts.query:
        raise ValueError("Run URL must not contain query parameters")
    prefix = "/runs/"
    if not parts.path.startswith(prefix):
        raise ValueError("Run URL path must be /runs/<run_id>")
    encoded_run_id = parts.path[len(prefix):]
    run_id = unquote(encoded_run_id)
    if not run_id or "/" in encoded_run_id or "/" in run_id:
        raise ValueError("Run URL must identify exactly one non-empty run_id segment")
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    if not _is_loopback_host(parts.hostname):
        allowed = _normalized_allowed_origins(tuple(allowed_origins))
        if parts.scheme != "https" or origin not in allowed:
            raise ValueError(
                "remote Run URL requires HTTPS and an exact explicit allowed origin"
            )
    return origin, run_id


def _run_api_key(url: str, *, origin: str, run_id: str) -> str | None:
    """Classify only same-origin API responses used by the Run first screen."""
    parts = urlsplit(url)
    response_origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    if response_origin != origin:
        return None
    path = unquote(parts.path)
    base = f"/api/runs/{run_id}"
    if path == base:
        return "core"
    if path == f"{base}/coach_suggestion":
        return "coach"
    if path != f"{base}/series":
        return None
    query = parse_qs(parts.query, keep_blank_values=True)
    series = query.get("series", [])
    segment = query.get("segment", [])
    if len(series) != 1 or series[0] not in _RUN_REQUIRED_SERIES:
        return None
    if segment != ["overall"]:
        return None
    return f"series:{series[0]}"


def _validate_run_first_screen_observation(observation: RunFirstScreenObservation) -> str:
    """Reject shell-only, unauthenticated, missing, or malformed browser evidence."""
    if not 200 <= observation.navigation_status < 300:
        raise RunFirstScreenUnavailable(
            f"Run navigation returned HTTP {observation.navigation_status}"
        )
    if observation.dom_state != "ready":
        raise RunFirstScreenUnavailable(
            f"Run real-content marker unavailable; DOM state={observation.dom_state!r}"
        )

    required_keys = (
        "core",
        *(f"series:{name}" for name in _RUN_REQUIRED_SERIES),
        "coach",
    )
    grouped: dict[str, list[RunApiObservation]] = {key: [] for key in required_keys}
    for response in observation.api_responses:
        if response.key in grouped:
            grouped[response.key].append(response)

    for key in required_keys:
        responses = grouped[key]
        if not responses:
            raise RunFirstScreenUnavailable(f"required Run API response missing: {key}")
        bad_statuses = [response.status for response in responses if not 200 <= response.status < 300]
        if bad_statuses:
            raise RunFirstScreenUnavailable(
                f"required Run API response {key} returned non-2xx status(es): {bad_statuses}"
            )
        if any(not response.has_bearer for response in responses):
            raise RunFirstScreenUnavailable(
                f"required Run API request lacked Bearer authentication: {key}"
            )

    latest = {key: grouped[key][-1].payload for key in required_keys}
    core = latest["core"]
    if not isinstance(core, dict) or core.get("run_id") != observation.run_id:
        raise RunFirstScreenUnavailable("Run core API payload does not bind the requested run_id")
    if not any(
        isinstance(core.get(name), str) and core[name].strip()
        for name in ("record_name", "strategy_name", "strategy_id")
    ):
        raise RunFirstScreenUnavailable("Run core API payload has no real run-name field")

    useful_chart_points = 0
    for series_name in _RUN_REQUIRED_SERIES:
        payload = latest[f"series:{series_name}"]
        if not isinstance(payload, dict):
            raise RunFirstScreenUnavailable(f"Run series payload is not an object: {series_name}")
        if payload.get("series") != series_name or payload.get("segment") != "overall":
            raise RunFirstScreenUnavailable(
                f"Run series payload identity mismatch: {series_name}"
            )
        if payload.get("run_id") != observation.run_id:
            raise RunFirstScreenUnavailable(
                f"Run series payload does not bind the requested run_id: {series_name}"
            )
        points = payload.get("points")
        if not isinstance(points, list):
            raise RunFirstScreenUnavailable(f"Run series points are malformed: {series_name}")
        if series_name in {"equity", "benchmark_return"}:
            useful_chart_points += len(points)
    if useful_chart_points <= 0:
        raise RunFirstScreenUnavailable(
            "Run equity/benchmark series contain no chart points; real first-screen chart not proven"
        )

    coach = latest["coach"]
    if (
        not isinstance(coach, dict)
        or "suggestion" not in coach
        or not isinstance(coach.get("risk_summary"), dict)
    ):
        raise RunFirstScreenUnavailable("Run coach API payload is malformed")

    return ",".join(
        f"{key}={','.join(str(response.status) for response in grouped[key])}"
        for key in required_keys
    )


def _playwright_run_first_screen_probe(
    config: RunFirstScreenProbeConfig,
) -> RunFirstScreenProbeResult:
    """Perform login and cold Run navigation in a real headless Chromium page."""
    try:
        origin, run_id = _parse_run_url(
            config.run_url,
            allowed_origins=config.allowed_origins,
        )
        if not config.username or not config.password:
            raise ValueError("Run probe username and password must both be non-empty")
        if not math.isfinite(config.timeout_seconds) or config.timeout_seconds <= 0:
            raise ValueError("Run probe timeout must be a positive finite number")
    except ValueError as exc:
        raise RunFirstScreenUnavailable(str(exc)) from exc

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001 - optional runtime dependency
        raise RunFirstScreenUnavailable(
            f"Playwright Python package unavailable: {_safe_probe_error(exc, config)}"
        ) from exc

    timeout_ms = int(config.timeout_seconds * 1000)
    try:
        with sync_playwright() as playwright:
            auth_client = playwright.request.new_context(base_url=origin)
            try:
                login_response = auth_client.post(
                    "/api/auth/login",
                    data={"username": config.username, "password": config.password},
                    timeout=timeout_ms,
                )
                if not 200 <= login_response.status < 300:
                    raise RunFirstScreenUnavailable(
                        f"Run probe authentication returned HTTP {login_response.status}"
                    )
                login_payload = login_response.json()
            finally:
                auth_client.dispose()

            if (
                not isinstance(login_payload, dict)
                or not isinstance(login_payload.get("token"), str)
                or not login_payload["token"]
                or not isinstance(login_payload.get("user"), dict)
            ):
                raise RunFirstScreenUnavailable("Run probe authentication payload is malformed")
            login_token = login_payload["token"]

            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    storage_state={
                        "cookies": [],
                        "origins": [
                            {
                                "origin": origin,
                                "localStorage": [
                                    {"name": "qb-auth-token", "value": login_payload["token"]},
                                    {
                                        "name": "qb-auth-user",
                                        "value": json.dumps(login_payload["user"], separators=(",", ":")),
                                    },
                                ],
                            }
                        ],
                    },
                )
                try:
                    page = context.new_page()
                    captured: list[tuple[str, int, bool, Any]] = []
                    pending: dict[str, int] = {}

                    def _request_started(request: Any) -> None:
                        key = _run_api_key(request.url, origin=origin, run_id=run_id)
                        if key is None:
                            return
                        pending[key] = pending.get(key, 0) + 1

                    def _finish_pending(key: str) -> None:
                        remaining = pending.get(key, 0) - 1
                        if remaining > 0:
                            pending[key] = remaining
                        else:
                            pending.pop(key, None)

                    def _request_finished(request: Any) -> None:
                        key = _run_api_key(request.url, origin=origin, run_id=run_id)
                        if key is None:
                            return
                        _finish_pending(key)
                        authorization = request.header_value("authorization") or ""
                        response = request.response()
                        captured.append(
                            (
                                key,
                                int(response.status) if response is not None else 0,
                                _request_uses_login_token(authorization, login_token),
                                response,
                            )
                        )

                    def _request_failed(request: Any) -> None:
                        key = _run_api_key(request.url, origin=origin, run_id=run_id)
                        if key is None:
                            return
                        _finish_pending(key)
                        authorization = request.header_value("authorization") or ""
                        captured.append(
                            (key, 0, _request_uses_login_token(authorization, login_token), None)
                        )

                    page.on("request", _request_started)
                    page.on("requestfinished", _request_finished)
                    page.on("requestfailed", _request_failed)
                    started = time.perf_counter()
                    navigation = page.goto(
                        config.run_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    navigation_status = int(navigation.status) if navigation is not None else 0
                    deadline = started + config.timeout_seconds
                    dom_state = "missing"
                    required = {
                        "core",
                        "coach",
                        *(f"series:{name}" for name in _RUN_REQUIRED_SERIES),
                    }
                    dom_state_script = """(expectedRunId) => {
                      const bodyText = document.body?.innerText || "";
                      if (bodyText.includes("回测详情加载失败。")) return "error";
                      if (bodyText.includes("缺少 runId")) return "error";
                      const title = document.querySelector(".jq-run-overview-page-title");
                      const runName = document.querySelector(".jq-run-detail-status-left strong");
                      const metrics = document.querySelector(".jq-run-overview-metrics-board");
                      const chart = document.querySelector(".jq-run-overview-chart-panel--jq canvas");
                      const ready = document.querySelector(
                        '[data-run-first-screen-ready="true"]'
                      );
                      const coachReady = document.querySelector(
                        '[data-run-coach-ready="true"]'
                      );
                      const titleReady = title?.textContent?.includes("收益概述") === true;
                      const runReady = (runName?.textContent?.trim()?.length || 0) > 0;
                      const metricsReady = (metrics?.textContent?.trim()?.length || 0) > 0;
                      const chartBox = chart?.getBoundingClientRect();
                      const chartReady = Boolean(
                        chartBox &&
                        chartBox.width > 0 &&
                        chartBox.height > 0 &&
                        ready?.getAttribute("data-run-id") === expectedRunId &&
                        coachReady?.getAttribute("data-run-id") === expectedRunId
                      );
                      if (titleReady && runReady && metricsReady && chartReady) return "ready";
                      if (bodyText.includes("加载回测详情中…")) return "loading";
                      return "missing";
                    }"""
                    while time.perf_counter() < deadline:
                        dom_state = str(page.evaluate(dom_state_script, run_id))
                        seen = {item[0] for item in captured}
                        if dom_state == "error" or (
                            dom_state == "ready" and required <= seen and not pending
                        ):
                            break
                        page.wait_for_timeout(20)

                    page.wait_for_timeout(0)
                    dom_state = str(page.evaluate(dom_state_script, run_id))
                    observed_seconds = time.perf_counter() - started
                    observations: list[RunApiObservation] = []
                    for key, status, has_bearer, response in captured:
                        try:
                            payload = response.json() if response is not None else None
                        except Exception:
                            payload = None
                        observations.append(
                            RunApiObservation(
                                key=key,
                                status=status,
                                has_bearer=has_bearer,
                                payload=payload,
                            )
                        )
                    observation = RunFirstScreenObservation(
                        run_id=run_id,
                        navigation_status=navigation_status,
                        dom_state=dom_state,
                        api_responses=tuple(observations),
                    )
                    _validate_run_first_screen_observation(observation)
                    return RunFirstScreenProbeResult(
                        observed_seconds=observed_seconds,
                        observation=observation,
                    )
                finally:
                    context.close()
            finally:
                browser.close()
    except RunFirstScreenUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - all collection failures are honest GAPs
        raise RunFirstScreenUnavailable(
            f"authenticated Playwright Run probe unavailable: {_safe_probe_error(exc, config)}"
        ) from exc


def _run_first_screen_backend_proxy(*, n_days: int, seed: int) -> tuple[str, float | None]:
    """Measure only the backend contribution, for transparent GAP diagnostics."""
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

    return proxy_note, backend_assembly_seconds


def measure_run_first_screen(
    *,
    run_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout_seconds: float = 15.0,
    allowed_origins: tuple[str, ...] = (),
    n_days: int = 1000,
    seed: int = 9,
) -> PerformanceBaselineMeasurement:
    """Measure a real authenticated Run first-screen, or return an honest GAP.

    With no browser inputs this remains network-free and records the historical
    backend proxy as a gap diagnostic.  With all three inputs, the harness logs
    in through the real auth endpoint, opens a fresh Chromium context, starts the
    timer immediately before navigation, and stops only after real-content DOM
    markers plus core/four-series/coach responses are observed.  The strict
    validator rejects loading/error shells, missing Bearer headers, non-2xx
    responses, malformed payloads, and empty first-screen chart series.
    """
    proxy_note, backend_assembly_seconds = _run_first_screen_backend_proxy(
        n_days=n_days, seed=seed
    )
    provided = (run_url is not None, username is not None, password is not None)
    if not any(provided):
        reason = (
            "authenticated browser probe not configured; provide Run URL, username, "
            "and password so the harness can perform real login + navigation"
        )
    elif not all(provided):
        missing = [
            name
            for name, value in (
                ("Run URL", run_url),
                ("username", username),
                ("password", password),
            )
            if value is None
        ]
        reason = f"authenticated browser probe configuration incomplete; missing {', '.join(missing)}"
    else:
        config = RunFirstScreenProbeConfig(
            run_url=run_url or "",
            username=username or "",
            password=password or "",
            timeout_seconds=timeout_seconds,
            allowed_origins=tuple(allowed_origins),
        )
        try:
            _origin, expected_run_id = _parse_run_url(
                config.run_url,
                allowed_origins=config.allowed_origins,
            )
            result = _playwright_run_first_screen_probe(config)
            if not math.isfinite(result.observed_seconds) or result.observed_seconds < 0:
                raise RunFirstScreenUnavailable("browser probe returned an invalid duration")
            if not isinstance(result.observation, RunFirstScreenObservation):
                raise RunFirstScreenUnavailable("browser probe returned no raw observation")
            if result.observation.run_id != expected_run_id:
                raise RunFirstScreenUnavailable(
                    "browser probe observation does not bind the configured run_id"
                )
            api_status_summary = _validate_run_first_screen_observation(
                result.observation
            )
        except RunFirstScreenUnavailable as exc:
            reason = _safe_probe_error(exc, config)
        except Exception as exc:  # noqa: BLE001 - injected/browser seams also fail closed
            reason = f"browser probe failed closed: {_safe_probe_error(exc, config)}"
        else:
            evidence = (
                f"benchmark:run_first_screen:run_id={expected_run_id}"
                f":authenticated=True:observed_s={result.observed_seconds:.4f}"
                f":api={api_status_summary}"
            )
            detail = (
                f"Playwright Chromium authenticated cold-page navigation to /runs/{expected_run_id}; "
                "real marker=run-name + 收益概述 + metrics + painted-chart-canvas; "
                f"required API responses={api_status_summary}; "
                f"ready={result.observed_seconds:.4f}s. {proxy_note}"
            )
            return PerformanceBaselineMeasurement(
                baseline_ref=BASELINE_RUN_FIRST_SCREEN,
                metric_name="Run 首屏 (Run first-screen)",
                threshold_seconds=2.0,
                measured=True,
                observed_seconds=result.observed_seconds,
                evidence_ref=evidence,
                detail=detail,
            )

    evidence = (
        f"benchmark:run_first_screen:KNOWN_RUN_GAP"
        f":browser_probe_configured={all(provided)}"
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
        detail=f"{proxy_note}; browser probe: {reason}",
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


def all_measurements(
    *,
    hs300_dataset_path: str | Path | None = None,
    hs300_registry_path: str | Path | None = None,
    hs300_dataset_version_ref: str | None = None,
    hs300_provenance_receipt_path: str | Path | None = None,
    hs300_universe_snapshot_path: str | Path | None = None,
    hs300_provenance_key: str | None = None,
    run_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    run_timeout_seconds: float = 15.0,
    run_allowed_origins: tuple[str, ...] = (),
) -> tuple[PerformanceBaselineMeasurement, ...]:
    """Run every baseline measurement and return raw observations (no verdicts)."""
    return (
        measure_standard_backtest(),
        measure_rag_first_results(),
        measure_asset_library_retrieval(),
        measure_hs300_10y_daily_read(
            dataset_path=hs300_dataset_path,
            registry_path=hs300_registry_path,
            dataset_version_ref=hs300_dataset_version_ref,
            provenance_receipt_path=hs300_provenance_receipt_path,
            universe_snapshot_path=hs300_universe_snapshot_path,
            provenance_key=hs300_provenance_key,
        ),
        measure_run_first_screen(
            run_url=run_url,
            username=username,
            password=password,
            timeout_seconds=run_timeout_seconds,
            allowed_origins=run_allowed_origins,
        ),
    )


def run_all_benchmarks(
    *,
    hs300_dataset_path: str | Path | None = None,
    hs300_registry_path: str | Path | None = None,
    hs300_dataset_version_ref: str | None = None,
    hs300_provenance_receipt_path: str | Path | None = None,
    hs300_universe_snapshot_path: str | Path | None = None,
    hs300_provenance_key: str | None = None,
    run_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    run_timeout_seconds: float = 15.0,
    run_allowed_origins: tuple[str, ...] = (),
) -> BenchmarkReport:
    """Measure all five baselines and classify each via the shared §16 gate."""
    return BenchmarkReport(
        tuple(
            classify_performance_baseline(m)
            for m in all_measurements(
                hs300_dataset_path=hs300_dataset_path,
                hs300_registry_path=hs300_registry_path,
                hs300_dataset_version_ref=hs300_dataset_version_ref,
                hs300_provenance_receipt_path=hs300_provenance_receipt_path,
                hs300_universe_snapshot_path=hs300_universe_snapshot_path,
                hs300_provenance_key=hs300_provenance_key,
                run_url=run_url,
                username=username,
                password=password,
                run_timeout_seconds=run_timeout_seconds,
                run_allowed_origins=run_allowed_origins,
            )
        )
    )


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure all GOAL §16 baselines; optionally verify a provenance-bound "
            "HS300 dataset and drive an authenticated Run page."
        )
    )
    parser.add_argument(
        "--hs300-dataset-path",
        default=os.environ.get(HS300_DATASET_PATH_ENV),
        help=(
            "exact versioned parquet file or directory containing the versioned files "
            f"(default: ${HS300_DATASET_PATH_ENV})"
        ),
    )
    parser.add_argument(
        "--hs300-registry-path",
        default=os.environ.get(HS300_REGISTRY_PATH_ENV),
        help=f"production DatasetRegistry JSONL path (default: ${HS300_REGISTRY_PATH_ENV})",
    )
    parser.add_argument(
        "--hs300-dataset-version-ref",
        default=os.environ.get(HS300_DATASET_VERSION_REF_ENV),
        help=(
            "exact DatasetVersion reference recorded in the registry "
            f"(default: ${HS300_DATASET_VERSION_REF_ENV})"
        ),
    )
    parser.add_argument(
        "--hs300-provenance-receipt",
        default=os.environ.get(HS300_PROVENANCE_RECEIPT_ENV),
        help=(
            "detached signed provenance receipt JSON path "
            f"(default: ${HS300_PROVENANCE_RECEIPT_ENV})"
        ),
    )
    parser.add_argument(
        "--hs300-universe-snapshot",
        default=os.environ.get(HS300_UNIVERSE_SNAPSHOT_ENV),
        help=(
            "authority-signed exact HS300 membership snapshot JSON path "
            f"(default: ${HS300_UNIVERSE_SNAPSHOT_ENV})"
        ),
    )
    parser.add_argument(
        "--hs300-provenance-key-env",
        default=HS300_PROVENANCE_KEY_ENV,
        help=(
            "name of the environment variable holding the receipt HMAC key "
            f"(default: {HS300_PROVENANCE_KEY_ENV}); key values are not accepted as CLI args"
        ),
    )
    parser.add_argument(
        "--run-url",
        default=os.environ.get(RUN_PROBE_URL_ENV),
        help=f"absolute /runs/<run_id> URL (default: ${RUN_PROBE_URL_ENV})",
    )
    parser.add_argument(
        "--run-username",
        default=os.environ.get(RUN_PROBE_USERNAME_ENV),
        help=f"local login username (default: ${RUN_PROBE_USERNAME_ENV})",
    )
    parser.add_argument(
        "--run-password-env",
        default=RUN_PROBE_PASSWORD_ENV,
        help=(
            "name of the environment variable holding the local login password "
            f"(default: {RUN_PROBE_PASSWORD_ENV}); password values are not accepted as CLI args"
        ),
    )
    parser.add_argument(
        "--run-timeout-seconds",
        type=float,
        default=os.environ.get("QUANTBT_PERF_RUN_TIMEOUT_SECONDS", "15"),
        help="authenticated Run probe timeout (default: 15 seconds)",
    )
    parser.add_argument(
        "--run-allowed-origin",
        action="append",
        default=None,
        help=(
            "exact HTTPS origin permitted to receive Run credentials; repeatable. "
            f"Defaults to comma-separated ${RUN_PROBE_ALLOWED_ORIGINS_ENV}. "
            "Loopback origins need no allowlist entry."
        ),
    )
    return parser.parse_args(argv)


def _main(argv: list[str] | None = None) -> int:
    args = _parse_cli(argv)
    password = os.environ.get(args.run_password_env) if args.run_password_env else None
    hs300_provenance_key = (
        os.environ.get(args.hs300_provenance_key_env)
        if args.hs300_provenance_key_env
        else None
    )
    allowed_origins = tuple(args.run_allowed_origin or ())
    if args.run_allowed_origin is None:
        allowed_origins = tuple(
            item.strip()
            for item in os.environ.get(RUN_PROBE_ALLOWED_ORIGINS_ENV, "").split(",")
            if item.strip()
        )
    report = run_all_benchmarks(
        hs300_dataset_path=args.hs300_dataset_path,
        hs300_registry_path=args.hs300_registry_path,
        hs300_dataset_version_ref=args.hs300_dataset_version_ref,
        hs300_provenance_receipt_path=args.hs300_provenance_receipt,
        hs300_universe_snapshot_path=args.hs300_universe_snapshot,
        hs300_provenance_key=hs300_provenance_key,
        run_url=args.run_url,
        username=args.run_username,
        password=password,
        run_timeout_seconds=args.run_timeout_seconds,
        run_allowed_origins=allowed_origins,
    )
    print(report.render())
    # exit 1 = regression, 0 = fully closed, 2 = no regression but gaps remain.
    # exit 0 is reserved for full closure so a gappy run can never read as "green".
    return report.exit_code


if __name__ == "__main__":
    sys.exit(_main())
