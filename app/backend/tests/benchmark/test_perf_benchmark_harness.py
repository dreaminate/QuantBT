"""Adversarial tests for the GOAL §16 performance-baseline benchmark harness.

Covers, per RULES §2 (种已知坏门必抓) and §3 (诚实纪律):
- the three baselines that are measured for real report GREEN with evidence;
- the two baselines that genuinely cannot be measured here are honest
  KNOWN_RUN_GAP -- never a fake pass;
- HS300 can become measured only with a signed DatasetVersion/manifest/source
  contract; unsigned metadata, membership, coverage, and file mutations stay GAP;
- regressing a baseline past threshold reports RED (the falsifiability proof);
- an injected delay that pushes a measured callable over threshold reports RED;
- the mutation-killable gate: an over-threshold measurement cannot pass, and a
  gap cannot be laundered into green.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture(scope="module")
def hs300_proof_fixture(tmp_path_factory):
    """Build a test-only contract; it is never real market-data evidence."""
    import numpy as np
    import pandas as pd
    import polars as pl

    from app.connectors.base import make_wide_fetch_result
    from app.data_quality import DatasetRegistry, GERule

    root = tmp_path_factory.mktemp("hs300-proof-contract")
    data_path = root / "hs300_panel.parquet"
    registry_path = root / "registry.jsonl"
    receipt_path = root / "provenance.json"
    universe_path = root / "universe.json"
    symbols = [f"{index:06d}.SZ" for index in range(1, 301)]
    all_weekdays = pd.bdate_range("2014-01-02", "2024-01-03")
    selected = np.linspace(
        0,
        len(all_weekdays) - 1,
        num=ph._HS300_MIN_TRADING_DAYS,
        dtype=int,
    )
    dates = all_weekdays[selected].to_numpy(dtype="datetime64[us]")
    n_rows = len(symbols) * len(dates)
    row_index = np.arange(n_rows)
    base = 10.0 + (row_index % 200) * 0.01
    frame = pl.DataFrame(
        {
            "ts": np.tile(dates, len(symbols)),
            "symbol": np.repeat(np.asarray(symbols, dtype=object), len(dates)),
            "open": base,
            "high": base + 1.0,
            "low": base - 0.5,
            "close": base + 0.25,
            "volume": 100_000 + (row_index % 10_000),
        }
    ).with_columns(pl.col("ts").dt.replace_time_zone("UTC"))
    frame.write_parquet(data_path)

    fetch_result = replace(
        make_wide_fetch_result(frame, source_name="tushare"),
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@test-contract-1",
        secret_ref="keyring://tushare/perf-test",
        known_at_utc=datetime.now(UTC).isoformat(),
        effective_at_utc=frame.get_column("ts").max().isoformat(),
    )
    registry = DatasetRegistry(registry_path)
    version = registry.register(
        "hs300_daily_10y_test_contract",
        fetch_result,
        file_paths=[str(data_path)],
        rules=[
            GERule(column=column, rule_type="not_null")
            for column in ("open", "high", "low", "close", "volume")
        ],
        metadata={
            "market": "stocks_cn",
            "interval": "1d",
            "data_kind": "ohlcv",
        },
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@test-contract-1",
        secret_ref="keyring://tushare/perf-test",
        known_at_utc=fetch_result.known_at_utc,
        effective_at_utc=fetch_result.effective_at_utc,
        require_provenance=True,
    )
    manifest_path = Path(version.manifest_path)
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    key = "test-only-hs300-provenance-key-32-bytes-minimum"
    authority_root = ph.HS300AuthorityRoot(
        root_id="test-only-out-of-band-root-v1",
        key_id="test-authority-v1",
        verification_key_sha256=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        authority_level="operator_attested",
        source_name="tushare",
        source_refs=("tushare://daily",),
        universe_refs=(ph._HS300_UNIVERSE_REF,),
    )
    universe_payload = {
        "schema_version": ph._HS300_UNIVERSE_SCHEMA,
        "authority_root_id": authority_root.root_id,
        "key_id": authority_root.key_id,
        "universe_ref": ph._HS300_UNIVERSE_REF,
        "as_of_date": "2024-01-03",
        "constituent_symbols": symbols,
    }
    _write_signed_receipt(universe_path, universe_payload, key)
    universe_snapshot_sha256 = hashlib.sha256(universe_path.read_bytes()).hexdigest()
    payload = {
        "schema_version": ph._HS300_RECEIPT_SCHEMA,
        "authority_root_id": authority_root.root_id,
        "key_id": authority_root.key_id,
        "dataset_id": version.dataset_id,
        "dataset_version": version.version_id,
        "dataset_record_sha256": hashlib.sha256(
            json.dumps(
                version.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "dataset_frame_sha256": version.sha256,
        "manifest_sha256": manifest_sha256,
        "source_name": version.source_name,
        "source_ref": version.source_ref,
        "ingestion_skill_version": version.ingestion_skill_version,
        "market": version.metadata["market"],
        "interval": version.metadata["interval"],
        "data_kind": version.metadata["data_kind"],
        "universe_ref": ph._HS300_UNIVERSE_REF,
        "universe_snapshot_sha256": universe_snapshot_sha256,
        "loaded_panel_sha256": ph._hs300_loaded_panel_sha256(frame),
        "row_count": version.row_count,
        "coverage_start_utc": version.coverage_start_utc,
        "coverage_end_utc": version.coverage_end_utc,
        "attested_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_signed_receipt(receipt_path, payload, key)
    return {
        "root": root,
        "data_path": data_path,
        "registry_path": registry_path,
        "receipt_path": receipt_path,
        "universe_path": universe_path,
        "key": key,
        "authority_root": authority_root,
        "version": version,
        "payload": payload,
        "universe_payload": universe_payload,
        "symbols": symbols,
    }


def _measure_hs300_fixture(fixture, **overrides):
    values = {
        "dataset_path": fixture["data_path"],
        "registry_path": fixture["registry_path"],
        "dataset_version_ref": fixture["version"].version_id,
        "provenance_receipt_path": fixture["receipt_path"],
        "universe_snapshot_path": fixture["universe_path"],
        "provenance_key": fixture["key"],
    }
    values.update(overrides)
    return ph.measure_hs300_10y_daily_read(**values)


def _pin_hs300_root(monkeypatch, fixture) -> None:
    """Simulate prior out-of-band review; never part of production evidence."""
    monkeypatch.setattr(
        ph,
        "_HS300_PINNED_AUTHORITY_ROOTS",
        (fixture["authority_root"],),
    )


def _write_signed_receipt(path: Path, payload: dict, key: str) -> None:
    signature = hmac.new(
        key.encode("utf-8"),
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    path.write_text(
        json.dumps(
            {**payload, "signature_hmac_sha256": signature},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _build_multifile_hs300_fixture(base_fixture, tmp_path: Path):
    """Create a real two-parquet DatasetVersion using the test-only authority."""
    import polars as pl

    from app.connectors.base import make_wide_fetch_result
    from app.data_quality import DatasetRegistry, GERule

    root = tmp_path / "multifile-hs300"
    root.mkdir()
    data_paths = (root / "part-a.parquet", root / "part-b.parquet")
    registry_path = root / "registry.jsonl"
    receipt_path = root / "provenance.json"
    frame = pl.read_parquet(base_fixture["data_path"])
    first_half = set(base_fixture["symbols"][:150])
    frame.filter(pl.col("symbol").is_in(first_half)).write_parquet(data_paths[0])
    frame.filter(~pl.col("symbol").is_in(first_half)).write_parquet(data_paths[1])

    fetch_result = replace(
        make_wide_fetch_result(frame, source_name="tushare"),
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@test-contract-1",
        secret_ref="keyring://tushare/perf-test",
        known_at_utc=datetime.now(UTC).isoformat(),
        effective_at_utc=frame.get_column("ts").max().isoformat(),
    )
    version = DatasetRegistry(registry_path).register(
        "hs300_daily_10y_multifile_test_contract",
        fetch_result,
        file_paths=[str(path) for path in data_paths],
        rules=[
            GERule(column=column, rule_type="not_null")
            for column in ("open", "high", "low", "close", "volume")
        ],
        metadata={
            "market": "stocks_cn",
            "interval": "1d",
            "data_kind": "ohlcv",
        },
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@test-contract-1",
        secret_ref="keyring://tushare/perf-test",
        known_at_utc=fetch_result.known_at_utc,
        effective_at_utc=fetch_result.effective_at_utc,
        require_provenance=True,
    )
    manifest_sha256 = hashlib.sha256(
        Path(version.manifest_path).read_bytes()
    ).hexdigest()
    payload = {
        **base_fixture["payload"],
        "dataset_id": version.dataset_id,
        "dataset_version": version.version_id,
        "dataset_record_sha256": hashlib.sha256(
            json.dumps(
                version.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "dataset_frame_sha256": version.sha256,
        "manifest_sha256": manifest_sha256,
        "loaded_panel_sha256": ph._hs300_loaded_panel_sha256(frame),
        "row_count": version.row_count,
        "coverage_start_utc": version.coverage_start_utc,
        "coverage_end_utc": version.coverage_end_utc,
        "attested_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_signed_receipt(receipt_path, payload, base_fixture["key"])
    return {
        "data_path": root,
        "registry_path": registry_path,
        "receipt_path": receipt_path,
        "universe_path": base_fixture["universe_path"],
        "key": base_fixture["key"],
        "authority_root": base_fixture["authority_root"],
        "version": version,
        "data_files": data_paths,
    }


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


def test_arbitrary_caller_key_and_self_signed_synthetic_hs300_stays_gap(
    hs300_proof_fixture,
):
    assert ph._HS300_PINNED_AUTHORITY_ROOTS == ()
    measurement = _measure_hs300_fixture(hs300_proof_fixture)
    assert measurement.measured is False
    assert "out-of-band production authority root" in measurement.unavailable_reason
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP


def test_simulated_out_of_band_root_exercises_verified_reader_contract(
    hs300_proof_fixture,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    measurement = _measure_hs300_fixture(hs300_proof_fixture)
    assert measurement.measured is True
    assert measurement.observed_seconds is not None
    assert measurement.observed_seconds < measurement.threshold_seconds
    assert "authority_bound_provenance=True" in measurement.evidence_ref
    assert "authority_level=operator_attested" in measurement.evidence_ref
    assert "authority_level=vendor_verified" not in measurement.evidence_ref
    assert "symbols=300" in measurement.evidence_ref
    assert f"trading_days={ph._HS300_MIN_TRADING_DAYS}" in measurement.evidence_ref
    for field_name in (
        "authority_root_sha256",
        "verification_key_sha256",
        "registry_sha256",
        "receipt_sha256",
        "universe_snapshot_sha256",
        "loaded_panel_sha256",
        "dataset_record_sha256",
        "frame_sha256",
        "manifest_sha256",
    ):
        assert re.search(rf":{field_name}=[0-9a-f]{{64}}(?=:)", measurement.evidence_ref)
    assert hs300_proof_fixture["key"] not in measurement.evidence_ref
    assert hs300_proof_fixture["key"] not in measurement.detail
    assert classify_performance_baseline(measurement).status == PERF_PASS


def test_vendor_verified_authority_label_is_rejected_fail_closed(
    hs300_proof_fixture,
    monkeypatch,
):
    vendor_claim = replace(
        hs300_proof_fixture["authority_root"],
        authority_level="vendor_verified",
    )
    monkeypatch.setattr(ph, "_HS300_PINNED_AUTHORITY_ROOTS", (vendor_claim,))

    measurement = _measure_hs300_fixture(hs300_proof_fixture)

    assert measurement.measured is False
    assert measurement.observed_seconds is None
    assert "not production-qualified" in measurement.unavailable_reason
    assert hs300_proof_fixture["key"] not in measurement.unavailable_reason
    assert hs300_proof_fixture["key"] not in measurement.evidence_ref
    assert hs300_proof_fixture["key"] not in measurement.detail
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP


def test_hs300_caller_scale_arguments_cannot_weaken_production_proof(
    hs300_proof_fixture,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    measurement = _measure_hs300_fixture(
        hs300_proof_fixture,
        n_symbols=1,
        n_days=1,
    )
    assert measurement.measured is True
    assert "symbols=300" in measurement.evidence_ref
    assert f"trading_days={ph._HS300_MIN_TRADING_DAYS}" in measurement.evidence_ref


def test_verified_hs300_over_threshold_is_measured_red_not_gap(
    hs300_proof_fixture,
    monkeypatch,
):
    def slow_timing(fn, *, repeat=5, warmup=1):  # noqa: ARG001
        assert warmup == 0
        fn()
        return ph.TimingSample(
            median_seconds=0.1,
            best_seconds=0.1,
            worst_seconds=3.5,
            repeat=1,
            first_seconds=3.5,
        )

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    monkeypatch.setattr(ph, "_time_call", slow_timing)
    measurement = _measure_hs300_fixture(hs300_proof_fixture)
    assert measurement.measured is True
    assert measurement.observed_seconds == 3.5
    assert classify_performance_baseline(measurement).status == PERF_FAIL


def test_hs300_timed_sample_orders_snapshot_then_reader_then_replay(
    hs300_proof_fixture,
    monkeypatch,
):
    from app.data_hash import dataset_hash
    from app.field_catalog import catalog

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)

    def forbidden_proxy(**_kwargs):
        raise AssertionError("configured production proof must run before any proxy")

    monkeypatch.setattr(ph, "_hs300_synthetic_proxy", forbidden_proxy)
    events = []
    real_verify_manifest = dataset_hash.verify_manifest
    real_materialize = ph._materialize_hs300_manifest_snapshot
    real_reader = catalog._read_dataset

    def tracked_materialize(*args, **kwargs):
        events.append("snapshot-read-hash-write")
        return real_materialize(*args, **kwargs)

    def tracked_reader(*args, **kwargs):
        events.append("field-catalog-reader")
        return real_reader(*args, **kwargs)

    def tracked_verify_manifest(*args, **kwargs):
        events.append("full-file-manifest-hash")
        return real_verify_manifest(*args, **kwargs)

    def tracked_timing(fn, *, repeat=5, warmup=1):  # noqa: ARG001
        assert warmup == 0
        events.append("timer-entry")
        fn()
        return ph.TimingSample(
            median_seconds=0.1,
            best_seconds=0.1,
            worst_seconds=0.1,
            repeat=1,
            first_seconds=0.1,
        )

    monkeypatch.setattr(dataset_hash, "verify_manifest", tracked_verify_manifest)
    monkeypatch.setattr(ph, "_materialize_hs300_manifest_snapshot", tracked_materialize)
    monkeypatch.setattr(catalog, "_read_dataset", tracked_reader)
    monkeypatch.setattr(ph, "_time_call", tracked_timing)
    measurement = _measure_hs300_fixture(hs300_proof_fixture)
    assert measurement.measured is True
    assert events == [
        "timer-entry",
        "snapshot-read-hash-write",
        "field-catalog-reader",
        "full-file-manifest-hash",
        "full-file-manifest-hash",
    ]


def test_run_all_benchmarks_routes_hs300_contract_to_real_consumer(
    hs300_proof_fixture,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    report = ph.run_all_benchmarks(
        hs300_dataset_path=hs300_proof_fixture["data_path"],
        hs300_registry_path=hs300_proof_fixture["registry_path"],
        hs300_dataset_version_ref=hs300_proof_fixture["version"].version_id,
        hs300_provenance_receipt_path=hs300_proof_fixture["receipt_path"],
        hs300_universe_snapshot_path=hs300_proof_fixture["universe_path"],
        hs300_provenance_key=hs300_proof_fixture["key"],
    )
    verdict = next(
        item
        for item in report.verdicts
        if item.measurement.baseline_ref == ph.BASELINE_HS300_READ
    )
    assert verdict.status == PERF_PASS
    assert {item.measurement.baseline_ref for item in report.gaps} == {
        ph.BASELINE_RUN_FIRST_SCREEN
    }


def test_unsigned_self_authored_hs300_metadata_stays_gap(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    registry_before = hs300_proof_fixture["registry_path"].read_bytes()
    manifest_path = Path(hs300_proof_fixture["version"].manifest_path)
    manifest_before = manifest_path.read_bytes()
    data_before = hashlib.sha256(
        hs300_proof_fixture["data_path"].read_bytes()
    ).hexdigest()
    receipt_path = tmp_path / "unsigned.json"
    receipt_path.write_text(
        json.dumps(
            {
                **hs300_proof_fixture["payload"],
                "signature_hmac_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    measurement = _measure_hs300_fixture(
        hs300_proof_fixture,
        provenance_receipt_path=receipt_path,
    )
    assert measurement.measured is False
    assert "signature mismatch" in measurement.unavailable_reason
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP
    assert hs300_proof_fixture["key"] not in measurement.detail
    assert hs300_proof_fixture["registry_path"].read_bytes() == registry_before
    assert manifest_path.read_bytes() == manifest_before
    assert (
        hashlib.sha256(hs300_proof_fixture["data_path"].read_bytes()).hexdigest()
        == data_before
    )


def test_signed_wrong_hs300_membership_is_rejected(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    receipt_path = tmp_path / "wrong-membership.json"
    universe_path = tmp_path / "wrong-universe.json"
    wrong_symbols = [*hs300_proof_fixture["symbols"][:-1], "000301.SZ"]
    universe_payload = {
        **hs300_proof_fixture["universe_payload"],
        "constituent_symbols": wrong_symbols,
    }
    _write_signed_receipt(universe_path, universe_payload, hs300_proof_fixture["key"])
    payload = {
        **hs300_proof_fixture["payload"],
        "universe_snapshot_sha256": hashlib.sha256(
            universe_path.read_bytes()
        ).hexdigest(),
    }
    _write_signed_receipt(receipt_path, payload, hs300_proof_fixture["key"])
    measurement = _measure_hs300_fixture(
        hs300_proof_fixture,
        provenance_receipt_path=receipt_path,
        universe_snapshot_path=universe_path,
    )
    assert measurement.measured is False
    assert "membership snapshot" in measurement.unavailable_reason
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP


def test_pinned_authority_rejects_an_attacker_key_even_with_matching_receipts(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    attacker_key = "attacker-controlled-hs300-key-material-at-least-32-bytes"
    universe_path = tmp_path / "attacker-universe.json"
    receipt_path = tmp_path / "attacker-receipt.json"
    _write_signed_receipt(
        universe_path,
        hs300_proof_fixture["universe_payload"],
        attacker_key,
    )
    payload = {
        **hs300_proof_fixture["payload"],
        "universe_snapshot_sha256": hashlib.sha256(
            universe_path.read_bytes()
        ).hexdigest(),
    }
    _write_signed_receipt(receipt_path, payload, attacker_key)
    measurement = _measure_hs300_fixture(
        hs300_proof_fixture,
        provenance_receipt_path=receipt_path,
        universe_snapshot_path=universe_path,
        provenance_key=attacker_key,
    )
    assert measurement.measured is False
    assert "pinned authority fingerprint" in measurement.unavailable_reason
    assert attacker_key not in measurement.detail


@pytest.mark.parametrize("surface", ["receipt", "registry", "universe", "data"])
def test_hs300_post_read_replay_rejects_mutation_without_partial_green(
    hs300_proof_fixture,
    monkeypatch,
    surface,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    monkeypatch.setattr(
        ph,
        "_hs300_synthetic_proxy",
        lambda **_kwargs: ("test-only synthetic proxy bypass", 0.0),
    )
    path = {
        "receipt": hs300_proof_fixture["receipt_path"],
        "registry": hs300_proof_fixture["registry_path"],
        "universe": hs300_proof_fixture["universe_path"],
        "data": hs300_proof_fixture["data_path"],
    }[surface]
    original = path.read_bytes()

    def mutate_after_reader(fn, *, repeat=5, warmup=1):  # noqa: ARG001
        assert warmup == 0
        fn()
        path.write_bytes(original + (b"\n" if surface != "data" else b"tampered"))
        return ph.TimingSample(
            median_seconds=0.1,
            best_seconds=0.1,
            worst_seconds=0.1,
            repeat=1,
            first_seconds=0.1,
        )

    monkeypatch.setattr(ph, "_time_call", mutate_after_reader)
    try:
        measurement = _measure_hs300_fixture(hs300_proof_fixture)
    finally:
        path.write_bytes(original)
    assert measurement.measured is False
    assert measurement.observed_seconds is None
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP
    assert any(
        marker in measurement.unavailable_reason
        for marker in ("changed during", "manifest verification failed")
    )


def test_hs300_transient_same_rows_different_parquet_bytes_cannot_flatter_timing(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    import polars as pl

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    monkeypatch.setattr(
        ph,
        "_hs300_synthetic_proxy",
        lambda **_kwargs: ("test-only synthetic proxy bypass", 0.0),
    )
    data_path = hs300_proof_fixture["data_path"]
    original = data_path.read_bytes()
    alternate_path = tmp_path / "alternate-encoding.parquet"
    original_frame = pl.read_parquet(data_path)
    original_frame.write_parquet(alternate_path, compression="uncompressed")
    alternate = alternate_path.read_bytes()
    assert alternate != original
    assert ph._hs300_loaded_panel_sha256(pl.read_parquet(alternate_path)) == (
        hs300_proof_fixture["payload"]["loaded_panel_sha256"]
    )

    def transient_swap(fn, *, repeat=5, warmup=1):  # noqa: ARG001
        assert warmup == 0
        data_path.write_bytes(alternate)
        try:
            fn()
        finally:
            data_path.write_bytes(original)
        raise AssertionError("manifest-byte mismatch should abort the timed sample")

    monkeypatch.setattr(ph, "_time_call", transient_swap)
    try:
        measurement = _measure_hs300_fixture(hs300_proof_fixture)
    finally:
        data_path.write_bytes(original)
    assert measurement.measured is False
    assert "manifest" in measurement.unavailable_reason.lower()


def test_hs300_reader_consumes_private_manifest_bytes_during_original_path_swap(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    import polars as pl

    from app.field_catalog import catalog

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    data_path = hs300_proof_fixture["data_path"]
    original = data_path.read_bytes()
    alternate_path = tmp_path / "inner-swap-uncompressed.parquet"
    pl.read_parquet(data_path).write_parquet(
        alternate_path,
        compression="uncompressed",
    )
    alternate = alternate_path.read_bytes()
    assert alternate != original
    manifest = json.loads(
        Path(hs300_proof_fixture["version"].manifest_path).read_text(
            encoding="utf-8"
        )
    )
    expected_file_sha256 = manifest["files"][0]["sha256"]
    real_reader = catalog._read_dataset
    observed_snapshot_paths = []

    def swap_original_inside_reader(dataset, *args, **kwargs):
        snapshot_path = Path(dataset.files[0].path)
        observed_snapshot_paths.append(snapshot_path)
        assert snapshot_path != data_path
        assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == (
            expected_file_sha256
        )
        data_path.write_bytes(alternate)
        try:
            return real_reader(dataset, *args, **kwargs)
        finally:
            data_path.write_bytes(original)

    monkeypatch.setattr(catalog, "_read_dataset", swap_original_inside_reader)
    try:
        measurement = _measure_hs300_fixture(hs300_proof_fixture)
    finally:
        data_path.write_bytes(original)
    assert measurement.measured is True
    assert len(observed_snapshot_paths) == 3
    assert "manifest_byte_snapshot=True" in measurement.evidence_ref


def test_manifest_detects_renamed_or_mutated_hs300_file(
    hs300_proof_fixture,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    data_path = hs300_proof_fixture["data_path"]
    original = data_path.read_bytes()
    try:
        data_path.write_bytes(original + b"tampered")
        measurement = _measure_hs300_fixture(hs300_proof_fixture)
    finally:
        data_path.write_bytes(original)
    assert measurement.measured is False
    assert "manifest" in measurement.unavailable_reason.lower()
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP


def test_signed_receipt_detects_persisted_dataset_record_mutation(
    hs300_proof_fixture,
    monkeypatch,
):
    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    registry_path = hs300_proof_fixture["registry_path"]
    original = registry_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in original.splitlines() if line.strip()]
    assert len(rows) == 1
    rows[0]["schema_drift_status"] = "forged-after-attestation"
    try:
        registry_path.write_text(
            json.dumps(rows[0], ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        measurement = _measure_hs300_fixture(hs300_proof_fixture)
    finally:
        registry_path.write_text(original, encoding="utf-8")
    assert measurement.measured is False
    assert "dataset_record_sha256" in measurement.unavailable_reason
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP


def test_hs300_rejects_five_duplicated_recorded_data_tests(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    from app.data_quality import DatasetVersion

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    registry_path = hs300_proof_fixture["registry_path"]
    original = registry_path.read_text(encoding="utf-8")
    row = json.loads(original.strip())
    row["ge_results"] = [row["ge_results"][0]] * 5
    mutated_version = DatasetVersion.from_dict(row)
    payload = {
        **hs300_proof_fixture["payload"],
        "dataset_record_sha256": hashlib.sha256(
            json.dumps(
                mutated_version.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    receipt_path = tmp_path / "duplicate-ge-receipt.json"
    _write_signed_receipt(receipt_path, payload, hs300_proof_fixture["key"])
    try:
        registry_path.write_text(
            json.dumps(row, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        measurement = _measure_hs300_fixture(
            hs300_proof_fixture,
            provenance_receipt_path=receipt_path,
        )
    finally:
        registry_path.write_text(original, encoding="utf-8")
    assert measurement.measured is False
    assert "five distinct recorded passing data tests" in measurement.unavailable_reason


def test_hs300_short_coverage_is_rejected_even_with_matching_receipt(
    hs300_proof_fixture,
):
    import polars as pl

    frame = pl.read_parquet(hs300_proof_fixture["data_path"])
    dates = frame.get_column("ts").unique().sort().head(20)
    short = frame.filter(pl.col("ts").is_in(dates.implode()))
    start = short.get_column("ts").min().isoformat()
    end = short.get_column("ts").max().isoformat()
    version = SimpleNamespace(
        row_count=short.height,
        coverage_start_utc=start,
        coverage_end_utc=end,
    )
    manifest = SimpleNamespace(total_row_count=short.height)
    receipt = {
        "loaded_panel_sha256": "0" * 64,
    }
    universe = {
        "constituent_symbols": hs300_proof_fixture["symbols"],
    }
    with pytest.raises(ph.HS300DatasetUnavailable, match="only 20 distinct"):
        ph._validate_hs300_panel(
            frame=short,
            version=version,
            manifest=manifest,
            receipt=receipt,
            universe=universe,
        )


def test_hs300_daily_contract_rejects_intraday_timestamp_inflation(
    hs300_proof_fixture,
):
    import polars as pl

    first = pl.read_parquet(hs300_proof_fixture["data_path"]).head(1)
    intraday = pl.concat(
        [
            first,
            first.with_columns((pl.col("ts") + pl.duration(hours=1)).alias("ts")),
        ]
    )
    version = SimpleNamespace(
        row_count=intraday.height,
        coverage_start_utc=intraday.get_column("ts").min().isoformat(),
        coverage_end_utc=intraday.get_column("ts").max().isoformat(),
    )
    manifest = SimpleNamespace(total_row_count=intraday.height)
    with pytest.raises(ph.HS300DatasetUnavailable, match="trading_date, symbol"):
        ph._validate_hs300_panel(
            frame=intraday,
            version=version,
            manifest=manifest,
            receipt={"loaded_panel_sha256": "0" * 64},
            universe={"constituent_symbols": [first.item(0, "symbol")]},
        )


def test_unexpected_hs300_implementation_error_is_not_laundered_into_gap(
    hs300_proof_fixture,
    monkeypatch,
):
    def broken(_config):
        raise RuntimeError("programming regression")

    monkeypatch.setattr(ph, "_measure_verified_hs300_read", broken)
    with pytest.raises(RuntimeError, match="programming regression"):
        _measure_hs300_fixture(hs300_proof_fixture)


def test_actual_field_catalog_reader_swallowed_exception_is_a_hard_failure(
    hs300_proof_fixture,
    monkeypatch,
):
    import polars as pl

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)

    def broken_parquet_reader(*_args, **_kwargs):
        raise RuntimeError("reader implementation regression")

    monkeypatch.setattr(pl, "read_parquet", broken_parquet_reader)
    with pytest.raises(ph.HS300BenchmarkFailure, match="swallowed"):
        _measure_hs300_fixture(hs300_proof_fixture)


def test_nonempty_partial_field_catalog_result_is_a_hard_failure(
    hs300_proof_fixture,
    monkeypatch,
):
    from app.field_catalog import catalog

    _pin_hs300_root(monkeypatch, hs300_proof_fixture)
    real_reader = catalog._read_dataset

    def partial_reader(*args, **kwargs):
        loaded = real_reader(*args, **kwargs)
        assert loaded is not None and loaded.height > 1
        return loaded.head(loaded.height - 1)

    monkeypatch.setattr(catalog, "_read_dataset", partial_reader)
    with pytest.raises(ph.HS300BenchmarkFailure, match="partial"):
        _measure_hs300_fixture(hs300_proof_fixture)


def test_multifile_field_catalog_one_read_failure_is_a_hard_failure(
    hs300_proof_fixture,
    tmp_path,
    monkeypatch,
):
    import polars as pl

    multifile = _build_multifile_hs300_fixture(hs300_proof_fixture, tmp_path)
    _pin_hs300_root(monkeypatch, multifile)
    real_read_parquet = pl.read_parquet
    read_events: list[tuple[str, str]] = []

    def fail_second_snapshot(source, *args, **kwargs):
        path = Path(source)
        if path.name.startswith("0001-"):
            read_events.append(("failed", path.name))
            raise RuntimeError("test-only second parquet read failure")
        read_events.append(("passed", path.name))
        return real_read_parquet(source, *args, **kwargs)

    monkeypatch.setattr(pl, "read_parquet", fail_second_snapshot)
    with pytest.raises(ph.HS300BenchmarkFailure, match="partial"):
        _measure_hs300_fixture(multifile)

    assert read_events == [
        ("passed", "0000-part-a.parquet"),
        ("failed", "0001-part-b.parquet"),
    ]


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


def _valid_run_observation(**overrides):
    responses = [
        ph.RunApiObservation(
            key="core",
            status=200,
            has_bearer=True,
            payload={"run_id": "demo", "record_name": "Real demo run"},
        ),
        *(
            ph.RunApiObservation(
                key=f"series:{series}",
                status=200,
                has_bearer=True,
                payload={
                    "run_id": "demo",
                    "series": series,
                    "segment": "overall",
                    "available": series in {"equity", "benchmark_return"},
                    "points": (
                        [{"timestamp": "2026-01-01", "value": 1.0}]
                        if series in {"equity", "benchmark_return"}
                        else []
                    ),
                },
            )
            for series in ph._RUN_REQUIRED_SERIES
        ),
        ph.RunApiObservation(
            key="coach",
            status=200,
            has_bearer=True,
            payload={"suggestion": None, "risk_summary": {}},
        ),
    ]
    values = {
        "run_id": "demo",
        "navigation_status": 200,
        "dom_state": "ready",
        "api_responses": tuple(responses),
    }
    values.update(overrides)
    return ph.RunFirstScreenObservation(**values)


def test_authenticated_browser_probe_measures_real_run_first_screen_green(monkeypatch):
    seen = []

    def probe(config):
        seen.append(config)
        return ph.RunFirstScreenProbeResult(
            observed_seconds=0.42,
            observation=_valid_run_observation(),
        )

    monkeypatch.setattr(ph, "_playwright_run_first_screen_probe", probe)
    measurement = ph.measure_run_first_screen(
        run_url="http://127.0.0.1:5176/runs/demo",
        username="local-user",
        password="local-secret",
    )
    assert len(seen) == 1
    assert seen[0].run_url == "http://127.0.0.1:5176/runs/demo"
    assert "local-secret" not in repr(seen[0])
    assert measurement.measured is True
    assert measurement.observed_seconds == pytest.approx(0.42)
    assert "authenticated=True" in measurement.evidence_ref
    assert "local-user" not in measurement.evidence_ref
    assert "local-secret" not in measurement.evidence_ref
    assert classify_performance_baseline(measurement).status == PERF_PASS


@pytest.mark.parametrize("dom_state", ["loading", "error", "missing"])
def test_run_probe_rejects_loading_error_and_missing_shells(dom_state):
    with pytest.raises(ph.RunFirstScreenUnavailable, match="DOM state"):
        ph._validate_run_first_screen_observation(
            _valid_run_observation(dom_state=dom_state)
        )


@pytest.mark.parametrize(
    ("target_key", "mutation", "message"),
    [
        ("core", {"status": 401}, "non-2xx"),
        ("series:equity", {"status": 500}, "non-2xx"),
        ("coach", {"status": 403}, "non-2xx"),
        ("series:benchmark_return", {"has_bearer": False}, "Bearer"),
    ],
)
def test_run_probe_rejects_non_2xx_and_unauthenticated_api_mutations(
    target_key, mutation, message
):
    observation = _valid_run_observation()
    mutated = tuple(
        replace(response, **mutation) if response.key == target_key else response
        for response in observation.api_responses
    )
    with pytest.raises(ph.RunFirstScreenUnavailable, match=message):
        ph._validate_run_first_screen_observation(
            replace(observation, api_responses=mutated)
        )


def test_run_probe_rejects_missing_required_api_and_empty_chart_series():
    observation = _valid_run_observation()
    without_coach = tuple(
        response for response in observation.api_responses if response.key != "coach"
    )
    with pytest.raises(ph.RunFirstScreenUnavailable, match="response missing: coach"):
        ph._validate_run_first_screen_observation(
            replace(observation, api_responses=without_coach)
        )

    no_chart_points = tuple(
        replace(response, payload={**response.payload, "points": []})
        if response.key in {"series:equity", "series:benchmark_return"}
        else response
        for response in observation.api_responses
    )
    with pytest.raises(ph.RunFirstScreenUnavailable, match="no chart points"):
        ph._validate_run_first_screen_observation(
            replace(observation, api_responses=no_chart_points)
        )


def test_run_probe_rejects_series_bound_to_a_different_run():
    observation = _valid_run_observation()
    wrong_run = tuple(
        replace(response, payload={**response.payload, "run_id": "other"})
        if response.key.startswith("series:")
        else response
        for response in observation.api_responses
    )
    with pytest.raises(ph.RunFirstScreenUnavailable, match="requested run_id"):
        ph._validate_run_first_screen_observation(
            replace(observation, api_responses=wrong_run)
        )


def test_run_url_rejects_remote_http_and_requires_exact_remote_https_allowlist():
    with pytest.raises(ValueError, match="remote Run URL"):
        ph._parse_run_url("http://collector.invalid/runs/demo")
    with pytest.raises(ValueError, match="remote Run URL"):
        ph._parse_run_url("https://example.invalid/runs/demo")
    assert ph._parse_run_url(
        "https://example.invalid/runs/demo",
        allowed_origins=("https://example.invalid",),
    ) == ("https://example.invalid", "demo")
    with pytest.raises(ValueError, match="query parameters"):
        ph._parse_run_url("http://127.0.0.1:5176/runs/demo?token=secret")
    with pytest.raises(ValueError, match="control characters"):
        ph._parse_run_url("http://127.0.0.1:5176/runs/demo\n")


def test_request_auth_must_equal_the_fresh_login_token():
    assert ph._request_uses_login_token("Bearer fresh-token", "fresh-token") is True
    assert ph._request_uses_login_token("Bearer other-valid-token", "fresh-token") is False
    assert ph._request_uses_login_token("Basic fresh-token", "fresh-token") is False


def test_unavailable_playwright_probe_stays_known_gap_and_redacts_credentials(monkeypatch):
    def unavailable(config):
        raise ph.RunFirstScreenUnavailable(
            f"browser unavailable for {config.username} / {config.password}"
        )

    monkeypatch.setattr(ph, "_playwright_run_first_screen_probe", unavailable)
    measurement = ph.measure_run_first_screen(
        run_url="http://127.0.0.1:5176/runs/demo",
        username="local-user",
        password="local-secret",
    )
    assert measurement.measured is False
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP
    assert "local-secret" not in measurement.evidence_ref
    # A deliberately raised domain error is expected to be safe, but the public
    # measurement still must never copy configured credentials to its evidence.
    assert "local-secret" not in measurement.detail


def test_safe_probe_error_redacts_url_query_and_bearer_material():
    config = ph.RunFirstScreenProbeConfig(
        run_url="https://allowed.example/runs/demo?api_key=query-secret",
        username="local-user",
        password="local-secret",
    )
    message = ph._safe_probe_error(
        RuntimeError(
            "failed https://allowed.example/runs/demo?api_key=query-secret "
            "Authorization: Bearer token-secret"
        ),
        config,
    )
    assert "query-secret" not in message
    assert "token-secret" not in message
    assert "local-secret" not in message


def test_browser_probe_over_threshold_is_measured_red_not_gap(monkeypatch):
    def slow_probe(_config):
        return ph.RunFirstScreenProbeResult(
            observed_seconds=2.5,
            observation=_valid_run_observation(),
        )

    monkeypatch.setattr(ph, "_playwright_run_first_screen_probe", slow_probe)
    measurement = ph.measure_run_first_screen(
        run_url="http://127.0.0.1:5176/runs/demo",
        username="local-user",
        password="local-secret",
    )
    assert measurement.measured is True
    assert classify_performance_baseline(measurement).status == PERF_FAIL


def test_browser_probe_result_must_bind_configured_run_id(monkeypatch):
    def mismatched(_config):
        return ph.RunFirstScreenProbeResult(
            observed_seconds=0.01,
            observation=_valid_run_observation(run_id="different-run"),
        )

    monkeypatch.setattr(ph, "_playwright_run_first_screen_probe", mismatched)
    measurement = ph.measure_run_first_screen(
        run_url="http://127.0.0.1:5176/runs/demo",
        username="local-user",
        password="local-secret",
    )
    assert measurement.measured is False
    assert classify_performance_baseline(measurement).status == PERF_KNOWN_RUN_GAP
    assert "configured run_id" in measurement.unavailable_reason


def test_cli_reads_password_from_named_env_only(monkeypatch):
    monkeypatch.setenv(ph.RUN_PROBE_URL_ENV, "http://127.0.0.1:5176/runs/demo")
    monkeypatch.setenv(ph.RUN_PROBE_USERNAME_ENV, "local-user")
    monkeypatch.setenv("TEST_RUN_PASSWORD", "local-secret")
    args = ph._parse_cli(["--run-password-env", "TEST_RUN_PASSWORD"])
    assert args.run_url == "http://127.0.0.1:5176/runs/demo"
    assert args.run_username == "local-user"
    assert not hasattr(args, "run_password")
    assert "local-secret" not in repr(args)


def test_cli_plumbs_hs300_paths_but_never_accepts_key_value(monkeypatch):
    monkeypatch.setenv(ph.HS300_DATASET_PATH_ENV, "/data/hs300.parquet")
    monkeypatch.setenv(ph.HS300_REGISTRY_PATH_ENV, "/data/registry.jsonl")
    monkeypatch.setenv(
        ph.HS300_DATASET_VERSION_REF_ENV,
        "dataset_version:hs300:v1",
    )
    monkeypatch.setenv(ph.HS300_PROVENANCE_RECEIPT_ENV, "/data/receipt.json")
    monkeypatch.setenv(ph.HS300_UNIVERSE_SNAPSHOT_ENV, "/data/universe.json")
    monkeypatch.setenv("TEST_HS300_KEY", "never-render-this-key-material")
    args = ph._parse_cli(
        ["--hs300-provenance-key-env", "TEST_HS300_KEY"]
    )
    assert args.hs300_dataset_path == "/data/hs300.parquet"
    assert args.hs300_registry_path == "/data/registry.jsonl"
    assert args.hs300_dataset_version_ref == "dataset_version:hs300:v1"
    assert args.hs300_provenance_receipt == "/data/receipt.json"
    assert args.hs300_universe_snapshot == "/data/universe.json"
    assert args.hs300_provenance_key_env == "TEST_HS300_KEY"
    assert not hasattr(args, "hs300_provenance_key")
    assert not hasattr(args, "hs300_authority_root")
    assert "never-render-this-key-material" not in repr(args)


def test_main_plumbs_universe_and_env_key_without_rendering_secret(
    monkeypatch,
    capsys,
):
    key = "main-plumbing-hs300-key-material-at-least-32-bytes"
    monkeypatch.setenv("TEST_MAIN_HS300_KEY", key)
    captured = {}

    class FakeReport:
        exit_code = 2

        @staticmethod
        def render():
            return "honest test report"

    def fake_run_all_benchmarks(**kwargs):
        captured.update(kwargs)
        return FakeReport()

    monkeypatch.setattr(ph, "run_all_benchmarks", fake_run_all_benchmarks)
    exit_code = ph._main(
        [
            "--hs300-dataset-path",
            "/data/hs300.parquet",
            "--hs300-registry-path",
            "/data/registry.jsonl",
            "--hs300-dataset-version-ref",
            "dataset_version:hs300:v1",
            "--hs300-provenance-receipt",
            "/data/receipt.json",
            "--hs300-universe-snapshot",
            "/data/universe.json",
            "--hs300-provenance-key-env",
            "TEST_MAIN_HS300_KEY",
        ]
    )
    assert exit_code == 2
    assert captured["hs300_universe_snapshot_path"] == "/data/universe.json"
    assert captured["hs300_provenance_key"] == key
    assert key not in capsys.readouterr().out


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
