from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.connectors.base import make_fetch_result
from app.data_quality import (
    DatasetRegistry,
    GERule,
    compute_freshness,
    expected_end_utc,
    make_version_id,
    run_ge_checks,
)


def _sample_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)],
            "symbol": ["BTC", "BTC"],
            "market": ["binanceusdm", "binanceusdm"],
            "interval": ["1d", "1d"],
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.0],
            "close": [1.5, 2.5],
            "volume": [100.0, 200.0],
            "amount": [150.0, 250.0],
        }
    )


def test_ge_rules_pass_on_clean_data() -> None:
    df = _sample_frame()
    rules = [
        GERule(column="close", rule_type="not_null"),
        GERule(column="ts", rule_type="unique"),
        GERule(column="ts", rule_type="monotonic", params={"order": "asc"}),
        GERule(column="close", rule_type="value_range", params={"min": 0, "max": 10}),
    ]
    results = run_ge_checks(df, rules)
    assert all(r.passed for r in results), [r.message for r in results if not r.passed]


def test_ge_rules_catch_dirty_data() -> None:
    df = pl.DataFrame({"x": [1, None, 3, 3], "y": [3, 2, 1, 0]})
    rules = [
        GERule(column="x", rule_type="not_null"),
        GERule(column="x", rule_type="unique"),
        GERule(column="y", rule_type="monotonic", params={"order": "asc"}),
        GERule(column="x", rule_type="value_range", params={"min": 0, "max": 2}),
    ]
    results = run_ge_checks(df, rules)
    assert not results[0].passed
    assert not results[1].passed
    assert not results[2].passed
    assert not results[3].passed


def test_ge_rule_missing_column() -> None:
    df = pl.DataFrame({"a": [1]})
    results = run_ge_checks(df, [GERule(column="b", rule_type="not_null")])
    assert results[0].passed is False
    assert "不存在" in results[0].message


def test_dataset_registry_appends_and_is_immutable(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    fr = make_fetch_result(_sample_frame(), source_name="test")
    v1 = reg.register("btc_daily", fr, file_paths=["a.parquet"])
    fr2 = make_fetch_result(_sample_frame().with_columns(pl.col("close") + 0.01), source_name="test")
    v2 = reg.register("btc_daily", fr2, file_paths=["b.parquet"])
    versions = reg.list_versions("btc_daily")
    assert {v.version_id for v in versions} == {v1.version_id, v2.version_id}
    assert reg.latest("btc_daily").version_id in {v1.version_id, v2.version_id}
    assert reg.list_dataset_ids() == ["btc_daily"]


def test_dataset_registry_ge_rules_persist(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    fr = make_fetch_result(_sample_frame(), source_name="test")
    rules = [GERule(column="close", rule_type="not_null"), GERule(column="ts", rule_type="unique")]
    version = reg.register("btc_daily", fr, rules=rules)
    assert len(version.ge_results) == 2
    assert all(r["passed"] for r in version.ge_results)


def test_version_id_format() -> None:
    vid = make_version_id("2024-05-01T10:00:00+00:00", "abcdef1234567890" * 4)
    assert vid.endswith("__abcdef12")


def test_freshness_red_when_stale(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    old_frame = _sample_frame().with_columns(
        pl.col("ts").map_elements(lambda _: datetime(2020, 1, 1, tzinfo=UTC), return_dtype=pl.Datetime("us", "UTC"))
    )
    fr = make_fetch_result(old_frame, source_name="test")
    reg.register("btc_daily", fr)
    report = compute_freshness("btc_daily", "binanceusdm", reg)
    assert report.status == "red"
    assert report.staleness_seconds and report.staleness_seconds > 7 * 24 * 3600


def test_freshness_green_when_fresh(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    fresh_ts = datetime.now(UTC) - timedelta(minutes=1)
    fresh_frame = _sample_frame().with_columns(
        pl.col("ts").map_elements(lambda _: fresh_ts, return_dtype=pl.Datetime("us", "UTC"))
    )
    fr = make_fetch_result(fresh_frame, source_name="test")
    reg.register("btc_daily", fr)
    report = compute_freshness("btc_daily", "binanceusdm", reg)
    assert report.status == "green"


def test_freshness_unknown_when_no_version(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    report = compute_freshness("nope", "binanceusdm", reg)
    assert report.status == "unknown"


def test_expected_end_a_share_skips_weekend() -> None:
    sunday = datetime(2024, 5, 5, 10, 0, tzinfo=UTC)  # Sun
    expected = expected_end_utc("stocks_cn", now=sunday)
    assert expected.weekday() < 5
