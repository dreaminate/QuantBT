"""HS300 证据链生产者对抗测试（种已知坏，门必抓；RULES §2）。

镜像等价性钉死：app 侧 data_onboarding 对 harness 契约是「语义复刻·非导入」，
两侧漂移由本文件直接对拍 harness 符号抓死（字段集/schema 串/签名/panel 哈希）。
全部用小合成 staging（300 只 × 30 日），不碰真实 staging、不写共享 data/audit。
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

import perf_harness as ph  # noqa: E402

from app.connectors.base import is_secret_reference  # noqa: E402
from app.data_onboarding import (  # noqa: E402
    RECEIPT_PAYLOAD_FIELDS,
    RECEIPT_SCHEMA,
    UNIVERSE_PAYLOAD_FIELDS,
    UNIVERSE_REF,
    UNIVERSE_SCHEMA,
    assemble_panel,
    build_chain,
    canonical_payload_bytes,
    load_list_dates,
    load_members,
    loaded_panel_sha256,
    preflight_report,
    sign_payload,
)

SYMBOLS = [f"{index:06d}.SZ" for index in range(1, 301)]
KEY = "test-only-producer-key-32-bytes-minimum-x"


def _business_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    return days


DAYS = _business_days(date(2024, 1, 2), 30)


def _staging(tmp_path: Path, *, late_symbol: str | None = None,
             late_from_index: int = 0, drop_days: set[str] | None = None,
             mutate_daily=None) -> Path:
    staging = tmp_path / "staging"
    (staging / "index_weight").mkdir(parents=True)
    (staging / "daily").mkdir()
    pl.DataFrame(
        {
            "index_code": ["000300.SH"] * len(SYMBOLS),
            "con_code": SYMBOLS,
            "trade_date": [DAYS[-1]] * len(SYMBOLS),
            "weight": [100.0 / len(SYMBOLS)] * len(SYMBOLS),
        }
    ).write_parquet(staging / "index_weight" / "202401.parquet")
    list_dates = {
        symbol: ("20100104" if symbol != late_symbol else DAYS[late_from_index])
        for symbol in SYMBOLS
    }
    pl.DataFrame(
        {"ts_code": SYMBOLS, "list_date": [list_dates[s] for s in SYMBOLS]}
    ).write_parquet(staging / "stock_basic_L.parquet")
    rows = {"ts_code": [], "trade_date": [], "open": [], "high": [], "low": [],
            "close": [], "vol": []}
    for symbol in SYMBOLS:
        start_index = late_from_index if symbol == late_symbol else 0
        for day in DAYS[start_index:]:
            if drop_days and symbol == late_symbol and day in drop_days:
                continue
            base = 10.0 + (hash((symbol, day)) % 100) * 0.01
            rows["ts_code"].append(symbol)
            rows["trade_date"].append(day)
            rows["open"].append(base)
            rows["high"].append(base + 1.0)
            rows["low"].append(base - 0.5)
            rows["close"].append(base + 0.25)
            rows["vol"].append(1000.0)
    daily = pl.DataFrame(rows)
    if mutate_daily is not None:
        daily = mutate_daily(daily)
    daily.write_parquet(staging / "daily" / "all.parquet")
    return staging


_PREFLIGHT_SMALL = {
    "min_trading_days": 20,
    "min_span_days": 25,
}


def test_contract_mirrors_match_harness():
    assert RECEIPT_PAYLOAD_FIELDS == ph._HS300_RECEIPT_PAYLOAD_FIELDS
    assert UNIVERSE_PAYLOAD_FIELDS == ph._HS300_UNIVERSE_PAYLOAD_FIELDS
    assert RECEIPT_SCHEMA == ph._HS300_RECEIPT_SCHEMA
    assert UNIVERSE_SCHEMA == ph._HS300_UNIVERSE_SCHEMA
    assert UNIVERSE_REF == ph._HS300_UNIVERSE_REF


def test_sign_payload_verifiable_by_harness_hmac():
    payload = {"a": 1, "b": "中文", "c": [1, 2]}
    signed = sign_payload(payload, KEY)
    ph._verify_hs300_hmac(
        payload=payload,
        signature=signed["signature_hmac_sha256"],
        key_bytes=KEY.encode("utf-8"),
        label="producer parity",
    )


def test_loaded_panel_sha256_matches_harness(tmp_path):
    staging = _staging(tmp_path)
    frame = assemble_panel(
        staging, members=SYMBOLS, start_date="2024-01-01", end_date="2024-02-29"
    )
    assert loaded_panel_sha256(frame) == ph._hs300_loaded_panel_sha256(frame)


def test_assemble_panel_is_deterministic(tmp_path):
    staging = _staging(tmp_path)
    first = assemble_panel(
        staging, members=SYMBOLS, start_date="2024-01-01", end_date="2024-02-29"
    )
    second = assemble_panel(
        staging, members=SYMBOLS, start_date="2024-01-01", end_date="2024-02-29"
    )
    assert loaded_panel_sha256(first) == loaded_panel_sha256(second)
    assert first.equals(second)


def test_assemble_panel_rejects_duplicate_rows(tmp_path):
    def _dup(daily: pl.DataFrame) -> pl.DataFrame:
        return pl.concat([daily, daily.head(1)])

    staging = _staging(tmp_path, mutate_daily=_dup)
    with pytest.raises(ValueError, match="重复"):
        assemble_panel(
            staging, members=SYMBOLS, start_date="2024-01-01", end_date="2024-02-29"
        )


def _report(staging, **kwargs):
    frame = assemble_panel(
        staging, members=SYMBOLS, start_date="2024-01-01", end_date="2024-02-29"
    )
    list_dates = load_list_dates(staging, load_members(staging, "202401"))
    return preflight_report(frame, list_dates, **{**_PREFLIGHT_SMALL, **kwargs})


def test_preflight_green_on_honest_staging(tmp_path):
    report = _report(_staging(tmp_path))
    assert report["ok"], report["checks"]


def test_preflight_catches_bars_before_listing(tmp_path):
    # 种坏:上市日签在第 5 日,但 bar 从第 1 日就有。
    staging = _staging(tmp_path)
    frame = assemble_panel(
        staging, members=SYMBOLS, start_date="2024-01-01", end_date="2024-02-29"
    )
    list_dates = load_list_dates(staging, SYMBOLS)
    list_dates[SYMBOLS[0]] = (
        f"{DAYS[5][0:4]}-{DAYS[5][4:6]}-{DAYS[5][6:8]}"
    )
    report = preflight_report(frame, list_dates, **_PREFLIGHT_SMALL)
    assert not report["ok"]
    assert not report["checks"]["no_bars_before_listing"]["ok"]


def test_preflight_catches_first_bar_lag(tmp_path):
    # 种坏:晚上市成员首 bar 比上市日晚 5 个交易日,lag 容差 2。
    staging = _staging(tmp_path, late_symbol=SYMBOLS[0], late_from_index=10,
                       drop_days=set(DAYS[10:15]))
    report = _report(staging, first_bar_lag_days=2)
    assert not report["ok"]
    assert not report["checks"]["first_bar_lag"]["ok"]


def test_preflight_catches_coverage_hole(tmp_path):
    # 种坏:晚上市成员自上市 20 日中挖掉 8 日(60% < 80%),首 bar 保持对齐。
    staging = _staging(tmp_path, late_symbol=SYMBOLS[0], late_from_index=10,
                       drop_days=set(DAYS[12:20]))
    report = _report(staging)
    assert not report["ok"]
    assert not report["checks"]["since_listing_coverage"]["ok"]


def test_preflight_catches_negative_volume(tmp_path):
    def _neg(daily: pl.DataFrame) -> pl.DataFrame:
        return daily.with_columns(
            pl.when(pl.arange(0, daily.height) == 0)
            .then(-1.0)
            .otherwise(pl.col("vol"))
            .alias("vol")
        )

    report = _report(_staging(tmp_path, mutate_daily=_neg))
    assert not report["ok"]
    assert not report["checks"]["ohlcv_invariants"]["ok"]


def test_preflight_catches_weekend_bar(tmp_path):
    def _weekend(daily: pl.DataFrame) -> pl.DataFrame:
        return daily.with_columns(
            pl.when(pl.arange(0, daily.height) == 0)
            .then(pl.lit("20240106"))  # Saturday
            .otherwise(pl.col("trade_date"))
            .alias("trade_date")
        )

    report = _report(_staging(tmp_path, mutate_daily=_weekend))
    assert not report["ok"]
    assert not report["checks"]["no_weekend_bars"]["ok"]


def _built_chain(tmp_path):
    staging = _staging(tmp_path)
    data_root = tmp_path / "data-root"
    return build_chain(
        staging,
        registry_path=data_root / "registry.jsonl",
        panel_path=data_root / "lake" / "panel.parquet",
        out_dir=data_root / "provenance",
        key=KEY,
        root_id="test-producer-root-v1",
        key_id="test-producer-key-v1",
        snapshot_yyyymm="202401",
        start_date="2024-01-01",
        end_date="2024-02-29",
        as_of_date="2024-02-12",
        preflight_kwargs=_PREFLIGHT_SMALL,
    )


def test_build_chain_secret_hygiene(tmp_path):
    result = _built_chain(tmp_path)
    for path_key in ("receipt_path", "universe_path"):
        text = Path(result[path_key]).read_text(encoding="utf-8")
        assert KEY not in text
    assert KEY not in repr(result)
    registry_text = Path(result["registry_path"]).read_text(encoding="utf-8")
    assert KEY not in registry_text
    assert "keyring://" in registry_text
    assert is_secret_reference("keyring://quantbt/tushare")


def test_build_chain_refuses_failing_preflight(tmp_path):
    staging = _staging(tmp_path, late_symbol=SYMBOLS[0], late_from_index=10,
                       drop_days=set(DAYS[12:20]))
    data_root = tmp_path / "data-root"
    with pytest.raises(ValueError, match="preflight"):
        build_chain(
            staging,
            registry_path=data_root / "registry.jsonl",
            panel_path=data_root / "lake" / "panel.parquet",
            out_dir=data_root / "provenance",
            key=KEY,
            root_id="r",
            key_id="k",
            snapshot_yyyymm="202401",
            start_date="2024-01-01",
            end_date="2024-02-29",
            as_of_date="2024-02-12",
            preflight_kwargs=_PREFLIGHT_SMALL,
        )


def test_build_chain_feeds_harness_until_scale_gate(tmp_path, monkeypatch):
    # 负向规模证明:小合成链的 root/签名/registry/manifest/成员/universe 全部
    # 被 harness 接受,唯一拦下它的是不可注入的 2400 交易日规模门——
    # 证明生产者产物格式与 harness 契约逐字节兼容。
    result = _built_chain(tmp_path)
    root = ph.HS300AuthorityRoot(
        root_id="test-producer-root-v1",
        key_id="test-producer-key-v1",
        verification_key_sha256=hashlib.sha256(KEY.encode("utf-8")).hexdigest(),
        authority_level="operator_attested",
        source_name="tushare",
        source_refs=("tushare://daily",),
        universe_refs=(ph._HS300_UNIVERSE_REF,),
    )
    monkeypatch.setattr(ph, "_HS300_PINNED_AUTHORITY_ROOTS", (root,))
    measurement = ph.measure_hs300_10y_daily_read(
        dataset_path=result["panel_path"],
        registry_path=result["registry_path"],
        dataset_version_ref=result["dataset_version_ref"],
        provenance_receipt_path=result["receipt_path"],
        universe_snapshot_path=result["universe_path"],
        provenance_key=KEY,
    )
    assert measurement.measured is False
    assert "distinct trading days" in measurement.unavailable_reason
    assert KEY not in (measurement.unavailable_reason or "")
    assert KEY not in (measurement.detail or "")
