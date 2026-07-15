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


# ── 研究面资产:探针 #6(adj_factor look-ahead) / #7(停牌伪 bar) ────────────────

def _research_frames():
    import polars as pl
    from datetime import datetime, UTC

    def _ts(day):
        return datetime(2024, 1, day, tzinfo=UTC)

    days = [2, 3, 4, 5, 8]  # 交易日(周一~周五,1/6-7 是周末)
    symbols = ["000001.SZ", "000002.SZ", "999999.SZ"]  # 999999 = 已调出成员
    rows = {"symbol": [], "ts": [], "open": [], "high": [], "low": [],
            "close": [], "volume": []}
    frows = {"symbol": [], "ts": [], "adj_factor": []}
    for s in symbols:
        skip = {4} if s == "999999.SZ" else set()  # 999999 在 1/4 有记录停牌无 bar
        for d in days:
            scale = 0.5 if d >= 5 else 1.0  # 1/5 除权:价格减半补偿 factor 翻倍(诚实基底)
            if d not in skip:
                rows["symbol"].append(s); rows["ts"].append(_ts(d))
                rows["open"].append(10.0 * scale); rows["high"].append(11.0 * scale)
                rows["low"].append(9.5 * scale); rows["close"].append(10.5 * scale)
                rows["volume"].append(1000.0)
            frows["symbol"].append(s); frows["ts"].append(_ts(d))
            frows["adj_factor"].append(2.0 if d >= 5 else 1.0)  # 1/5 除权跳变
    bars = pl.DataFrame(rows)
    factors = pl.DataFrame(frows)
    suspensions = pl.DataFrame(
        {"symbol": ["999999.SZ"], "ts": [_ts(4)],
         "suspend_timing": pl.Series("suspend_timing", [None], dtype=pl.Utf8),
         "suspend_type": ["S"]}
    )
    return bars, factors, suspensions


def test_research_quality_green_on_honest_tables():
    from app.data_onboarding import research_quality_report

    bars, factors, suspensions = _research_frames()
    report = research_quality_report(
        bars, factors, suspensions, current_members={"000001.SZ", "000002.SZ"}
    )
    assert report["ok"], report["checks"]
    assert report["checks"]["survivorship_free_union"]["ok"]
    assert report["checks"]["factors_all_finite"]["ok"]  # 绿基线:factor 全有限


def test_factors_all_finite_caught():
    # 种坏:adj_factor 置 NaN / +inf——polars 里既非 null 又非 `<=0`（NaN<=0 / +inf<=0 均 False），
    # factor_bar_day_completeness 与 factor_positive 两门都漏 → factors_all_finite 门必炸
    # （否则非有限 factor 算出 NaN/inf hfq 却当合格数据落盘）。把该门去掉 → 本测试红。
    import polars as pl

    from app.data_onboarding import research_quality_report

    bars, factors, suspensions = _research_frames()
    nan_f = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == factors["ts"][2]))
        .then(pl.lit(float("nan")))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    rep_nan = research_quality_report(bars, nan_f, suspensions)
    assert not rep_nan["ok"]
    assert not rep_nan["checks"]["factors_all_finite"]["ok"]

    inf_f = factors.with_columns(
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") == factors["ts"][2]))
        .then(pl.lit(float("inf")))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    rep_inf = research_quality_report(bars, inf_f, suspensions)
    assert not rep_inf["checks"]["factors_all_finite"]["ok"]


def test_probe6_factor_lookahead_shift_is_caught():
    # 种坏(#6):复权因子整体前移一天(look-ahead 错位)→ 同日覆盖门必炸。
    import polars as pl
    from datetime import timedelta

    from app.data_onboarding import research_quality_report

    bars, factors, suspensions = _research_frames()
    shifted = factors.with_columns((pl.col("ts") + pl.duration(days=1)).alias("ts"))
    report = research_quality_report(bars, shifted, suspensions)
    assert not report["ok"]
    assert not report["checks"]["factor_bar_day_completeness"]["ok"]


def test_probe6b_gross_factor_corruption_caught_real_events_tolerated():
    # 种坏(#6b):某日 factor ×6 → 对称比率门(4.5)必炸;合法缩股不误杀。
    import polars as pl

    from app.data_onboarding import research_quality_report

    bars, factors, suspensions = _research_frames()
    corrupted = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == factors["ts"][2]))
        .then(pl.col("adj_factor") * 6.0)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    report_bad = research_quality_report(bars, corrupted, suspensions)
    assert not report_bad["checks"]["hfq_continuity_symmetric_ratio"]["ok"]
    # 合法缩股(factor 永久 ÷2,伴随 raw 价 ×2 → hfq 连续):不误杀
    legit = factors.with_columns(
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") >= factors["ts"][2]))
        .then(pl.col("adj_factor") * 0.5)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    legit_bars = bars.with_columns(
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") >= factors["ts"][2]))
        .then(pl.col("close") * 2.0)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") >= factors["ts"][2]))
        .then(pl.col("high") * 2.0)
        .otherwise(pl.col("high"))
        .alias("high"),
    )
    report_ok = research_quality_report(legit_bars, legit, suspensions)
    assert report_ok["checks"]["hfq_continuity_symmetric_ratio"]["ok"]


def test_probe7_fake_bar_on_recorded_suspension_caught():
    # 种坏(#7):在有记录的全天停牌日(999999.SZ @ 1/4)伪造一根 bar → 冲突门必炸。
    import polars as pl
    from datetime import datetime, UTC

    from app.data_onboarding import research_quality_report

    bars, factors, suspensions = _research_frames()
    fake = pl.DataFrame(
        {"symbol": ["999999.SZ"], "ts": [datetime(2024, 1, 4, tzinfo=UTC)],
         "open": [10.0], "high": [11.0], "low": [9.5], "close": [10.5],
         "volume": [500.0]}
    )
    with_fake = pl.concat([bars, fake]).sort(["symbol", "ts"])
    report = research_quality_report(with_fake, factors, suspensions)
    assert not report["ok"]
    assert not report["checks"]["no_bars_on_recorded_suspension_days"]["ok"]


def test_probe7_half_day_suspension_does_not_conflict():
    # 边界:真日内窗(start<end,如 "09:31-10:00")当天有 bar 属正常,不误杀。
    # (无 "-" 或退化窗的 timing 保守当全天=fail-closed,见 degenerate 反例测试。)
    import polars as pl
    from datetime import datetime, UTC

    from app.data_onboarding import research_quality_report

    bars, factors, suspensions = _research_frames()
    half_day = pl.DataFrame(
        {"symbol": ["000001.SZ"], "ts": [datetime(2024, 1, 3, tzinfo=UTC)],
         "suspend_timing": ["09:31-10:00"], "suspend_type": ["S"]}
    )
    merged = pl.concat([suspensions, half_day])
    report = research_quality_report(bars, factors, merged)
    assert report["checks"]["no_bars_on_recorded_suspension_days"]["ok"]


# ── codex 增量审 REJECT 反例逐一钉死(修复回归) ───────────────────────────────

def _rq(bars, factors, suspensions, **kw):
    from app.data_onboarding import research_quality_report

    return research_quality_report(bars, factors, suspensions, **kw)


def test_codex_counterexample_downward_collapse_caught():
    # 反例1:factor 永久 ÷10(单边门抓不到 r=-0.9)→ 对称比率门 1/q=10>4.5 必炸。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    collapsed = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= factors["ts"][2]))
        .then(pl.col("adj_factor") * 0.1)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    report = _rq(bars, collapsed, suspensions)
    assert not report["checks"]["hfq_continuity_symmetric_ratio"]["ok"]


def test_codex_counterexample_single_day_x4_pair_revert_caught():
    # 反例2:平坦区单日 factor ×4(+3.0/-0.75 双尖峰,单腿均过 4.5 对称门)
    # → 成对回转检测必炸。注:若腐蚀日紧邻真实除权日,乘积≠1 会逃逸——
    # 属已声明检测下限(与真实事件混叠不可分),测试点取平坦区 ts[1]。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    spiked = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == factors["ts"][1]))
        .then(pl.col("adj_factor") * 4.0)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    report = _rq(bars, spiked, suspensions)
    assert not report["checks"]["hfq_no_uncompensated_factor_spikes"]["ok"]


def test_detection_floor_flat_region_in_band_fabrication_documented_miss():
    # 检测下限成文(非缺陷否认,经三轮对抗收窄):平坦区无中生有的带内小幅假因子
    # (如 3% 假分红,fq 与 r 双双 <0.30)——本层设计上不可检(与真实小分红不可分),
    # 真解药=factor vintage(known_at)落盘做真 PIT 门(后续卡)。
    # 注:靠近真实除权日的互换/错置会解耦补偿而被不变量抓住(见上方回归测试),
    # 下限比最初声明的更窄。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    ts1 = factors["ts"][1]  # 平坦区(远离 1/5 除权日)
    fabricated = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= ts1)
                & (pl.col("ts") < factors["ts"][3]))
        .then(pl.col("adj_factor") * 1.03)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    report = _rq(bars, fabricated, suspensions)
    # 带内伪造如实滑过——若未来该断言翻转,说明有了更强的门,更新本档案。
    assert report["checks"]["hfq_continuity_symmetric_ratio"]["ok"]
    assert report["checks"]["hfq_no_uncompensated_factor_spikes"]["ok"]


def test_codex_counterexample_degenerate_timing_full_day_caught():
    # 反例3:供应商用 "09:30-09:30" 退化窗编码全天停牌——伪 bar 必炸(不再当半日放行)。
    import polars as pl
    from datetime import datetime, UTC

    bars, factors, suspensions = _research_frames()
    degenerate = pl.DataFrame(
        {"symbol": ["000001.SZ"], "ts": [datetime(2024, 1, 3, tzinfo=UTC)],
         "suspend_timing": ["09:30-09:30"], "suspend_type": ["S"]}
    )
    merged = pl.concat([suspensions, degenerate])
    report = _rq(bars, factors, merged)  # 000001.SZ 在 1/3 有 bar → 冲突
    assert not report["checks"]["no_bars_on_recorded_suspension_days"]["ok"]


def test_codex_counterexample_null_close_caught():
    # 反例4:中段 close=None 此前 fail-open(比较式 null 被 sum 吞)→ 新增七列 null 门必炸。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    holed = bars.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == bars["ts"][2]))
        .then(None)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    report = _rq(holed, factors, suspensions)
    assert not report["checks"]["bars_no_nulls"]["ok"]


# ── codex 轮5 REJECT 三反例钉死 ────────────────────────────────────────────────

def test_codex_r5_price_drift_cannot_launder_pair_revert():
    # 反例5-1:factor [1,4,1] + 两日原始价累涨 6%——旧判据 q·q'(=价格收益)被
    # 6% 顶出容差而放行;新判据 fq·fq'=4×0.25=1 与价格无关,必炸。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    spiked = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == factors["ts"][1]))
        .then(pl.col("adj_factor") * 4.0)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    drifted = bars.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= bars["ts"][2]))
        .then(pl.col("close") * 1.06)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= bars["ts"][2]))
        .then(pl.col("high") * 1.06)
        .otherwise(pl.col("high"))
        .alias("high"),
    )
    report = _rq(drifted, spiked, suspensions)
    assert not report["checks"]["hfq_no_uncompensated_factor_spikes"]["ok"]


def test_codex_r5_boundary_censoring_caught():
    # 反例5-2:仅首日或末日 factor ×4——单腿删失,成对判据够不着 → 边界规则必炸。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    for target_ts in (factors["ts"][0], factors["ts"][4]):
        mutated = factors.with_columns(
            pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == target_ts))
            .then(pl.col("adj_factor") * 4.0)
            .otherwise(pl.col("adj_factor"))
            .alias("adj_factor")
        )
        report = _rq(bars, mutated, suspensions)
        assert not report["checks"]["hfq_no_uncompensated_factor_spikes"]["ok"], target_ts


def test_codex_r5_spaced_degenerate_window_caught():
    # 反例5-3:'09:30 - 09:30'(带空格退化窗)——去空格后判全天,伪 bar 必炸。
    import polars as pl
    from datetime import datetime, UTC

    bars, factors, suspensions = _research_frames()
    spaced = pl.DataFrame(
        {"symbol": ["000001.SZ"], "ts": [datetime(2024, 1, 3, tzinfo=UTC)],
         "suspend_timing": ["09:30 - 09:30"], "suspend_type": ["S"]}
    )
    merged = pl.concat([suspensions, spaced])
    report = _rq(bars, factors, merged)
    assert not report["checks"]["no_bars_on_recorded_suspension_days"]["ok"]


def test_codex_r6_float_endpoint_and_gapped_spikes_caught():
    # 轮6两反例:①端点 1.05 浮点溢出旧容差;②[4,3.9,1] 隔腿双尖峰逃逸旧紧邻判据
    # ——单一不变量规则下两者的尖峰腿各自命中,必炸。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    for factor_seq in ([1.0, 4.0, 1.05, 1.05, 1.05], [1.0, 4.0, 3.9, 1.0, 1.0]):
        mutated = factors.with_columns(
            pl.when(pl.col("symbol") == "000001.SZ")
            .then(
                pl.col("ts").replace_strict(
                    dict(zip(factors.filter(pl.col("symbol") == "000001.SZ")["ts"],
                             factor_seq)),
                    default=None, return_dtype=pl.Float64,
                )
            )
            .otherwise(pl.col("adj_factor"))
            .alias("adj_factor")
        )
        report = _rq(bars, mutated, suspensions)
        check = report["checks"]["hfq_no_uncompensated_factor_spikes"]
        assert not check["ok"], factor_seq
        assert "=2" in check["detail"], check["detail"]  # 两腿各自命中,计数钉死


def test_legitimate_large_split_with_price_compensation_not_flagged():
    # 反向不误杀:10送10(fq=0.5 方向按 hfq 定义取 2.0)且 raw 价格反向补偿
    # → r 落常带 → 不变量规则不命中。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    ts_event = factors["ts"][2]
    big_split = factors.with_columns(
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") >= ts_event))
        .then(pl.col("adj_factor") * 2.0)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    compensated = bars.with_columns(
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") >= ts_event))
        .then(pl.col("close") * 0.5)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("ts") >= ts_event))
        .then(pl.col("low") * 0.5)
        .otherwise(pl.col("low"))
        .alias("low"),
    )
    report = _rq(compensated, big_split, suspensions)
    assert report["checks"]["hfq_no_uncompensated_factor_spikes"]["ok"]


def test_codex_r7_nan_volume_caught():
    # 轮7真 fail-open:NaN 注入(非 null)此前只有 preflight 有 finite 门,
    # 研究门缺失——补 bars_all_finite 后必炸。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    poisoned = bars.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") == bars["ts"][1]))
        .then(float("nan"))
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    report = _rq(poisoned, factors, suspensions)
    assert not report["checks"]["bars_all_finite"]["ok"]


def test_threat_model_floor_price_coupled_suffix_forgery_documented_miss():
    # 威胁模型 floor 成文(codex 轮7 canonical 构造,非缺陷否认):
    # 真实暴跌日(fq=1 纯价格事件)上反向伪造后缀 factor 使 q≈1——单源自洽、
    # 与价格精确耦合,质量门层数学上不可分辨(它与真实公司行动的唯一区别在
    # 源头事实,不在数据形状)。对抗性完整性归签名链/重拉比对/跨源/vintage。
    import polars as pl

    bars, factors, suspensions = _research_frames()
    ts_crash = bars["ts"][2]
    crashed = bars.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= ts_crash))
        .then(pl.col("close") * 0.21)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= ts_crash))
        .then(pl.col("low") * 0.19)
        .otherwise(pl.col("low"))
        .alias("low"),
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= ts_crash))
        .then(pl.col("open") * 0.22)
        .otherwise(pl.col("open"))
        .alias("open"),
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= ts_crash))
        .then(pl.col("high") * 0.23)
        .otherwise(pl.col("high"))
        .alias("high"),
    )
    forged = factors.with_columns(
        pl.when((pl.col("symbol") == "000001.SZ") & (pl.col("ts") >= ts_crash))
        .then(pl.col("adj_factor") / 0.21)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    report = _rq(crashed, forged, suspensions)
    # 如实滑过(floor)——若未来翻转,说明接入了跨源/vintage 门,更新本档案。
    assert report["checks"]["hfq_no_uncompensated_factor_spikes"]["ok"]
