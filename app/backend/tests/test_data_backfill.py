"""数据补充管线测试（无网络：注入 fetch/call）。"""

from __future__ import annotations

import calendar
import csv
import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from app.data_backfill import binance, tushare


def _ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def _kline_zip(open_times: list[int]) -> bytes:
    rows = [[str(ot), "1", "2", "0.5", "1.5", "100", str(ot + 1), "150", "10", "50", "75", "0"] for ot in open_times]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        s = io.StringIO()
        csv.writer(s).writerows(rows)
        zf.writestr("data.csv", s.getvalue())
    return buf.getvalue()


def _mock_fetch(url: str) -> bytes | None:
    """monthly url → 该月所有天；daily url → 当天一行。1d 连续。"""
    base = url.rsplit("/", 1)[-1].replace(".zip", "")  # SYM-1d-2023-01 或 SYM-1d-2023-01-15
    parts = base.split("-")
    if len(parts) == 4:  # 月
        y, m = int(parts[2]), int(parts[3])
        days = calendar.monthrange(y, m)[1]
        return _kline_zip([_ms(y, m, d) for d in range(1, days + 1)])
    if len(parts) == 5:  # 日
        y, m, d = int(parts[2]), int(parts[3]), int(parts[4])
        return _kline_zip([_ms(y, m, d)])
    return None


# ───────────── Binance 拼接 ─────────────


def test_stitch_klines_continuous(tmp_path: Path) -> None:
    res = binance.stitch_klines(
        "BTCUSDT", "1d", market="um", start=date(2023, 1, 1), end=date(2023, 2, 15),
        data_root=tmp_path, fetch=_mock_fetch,
    )
    assert res.months_pulled == 1  # Jan 月 zip
    assert res.days_pulled == 15  # Feb 1-15 日 zip
    assert res.rows == 31 + 15  # 连续
    assert res.gaps == 0  # 1d 无缺口
    df = binance.read_klines("BTCUSDT", "1d", market="um", data_root=tmp_path)
    assert len(df) == 46
    assert list(df["open_time"]) == sorted(df["open_time"])  # 有序
    assert df["open_time"].is_unique  # 去重


def test_stitch_gap_detection(tmp_path: Path) -> None:
    # 只给两个相隔很远的日 → 缺口
    def sparse(url: str) -> bytes | None:
        if url.endswith("2023-03-01.zip"):
            return _kline_zip([_ms(2023, 3, 1)])
        if url.endswith("2023-03-10.zip"):
            return _kline_zip([_ms(2023, 3, 10)])
        return None

    res = binance.stitch_klines(
        "ETHUSDT", "1d", start=date(2023, 3, 1), end=date(2023, 3, 10),
        data_root=tmp_path, fetch=sparse,
    )
    assert res.rows == 2
    assert res.gaps == 1  # 3-01 → 3-10 一个缺口


def test_backfill_all_binance_skip_existing(tmp_path: Path) -> None:
    plan = binance.BinanceBackfillPlan(market="um", intervals=("1d",), symbols=("BTCUSDT",), start=date(2023, 1, 1))
    r1 = binance.backfill_all_binance(plan, data_root=tmp_path, fetch=_mock_fetch, skip_existing=True)
    assert len(r1) == 1 and r1[0].rows > 0
    # 第二次：已存在 → 跳过
    r2 = binance.backfill_all_binance(plan, data_root=tmp_path, fetch=_mock_fetch, skip_existing=True)
    assert r2 == []


def test_list_symbols_injected() -> None:
    syms = binance.list_symbols("um", fetch_json=lambda u: {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING"}, {"symbol": "ETHUSDT", "status": "TRADING"}]})
    assert syms == ["BTCUSDT", "ETHUSDT"]


# ───────────── Tushare 编排 ─────────────


def _mock_call(api_name: str, **params):
    if api_name == "stock_basic":
        return pd.DataFrame({"ts_code": ["000001.SZ", "600000.SH"]})
    # 标的级：返回 2 行假数据
    code = params.get("ts_code", "X")
    return pd.DataFrame({"ts_code": [code, code], "trade_date": ["20230103", "20230104"], "close": [10.0, 11.0]})


def test_list_a_share_symbols() -> None:
    syms = tushare.list_a_share_symbols(_mock_call)
    assert "000001.SZ" in syms and "600000.SH" in syms


def test_backfill_per_symbol_and_resume(tmp_path: Path) -> None:
    iface = tushare.TushareInterface("daily", "daily", "per_symbol")
    s1 = tushare.backfill_interface(iface, _mock_call, data_root=tmp_path, symbols=["000001.SZ", "600000.SH"])
    assert s1.units_done == 2 and s1.rows == 4
    # 落地可像 API 一样读
    df = tushare.read_tushare("daily", data_root=tmp_path, ts_code="000001.SZ")
    assert len(df) == 2 and "close" in df
    # 断点续传：再跑全跳过
    s2 = tushare.backfill_interface(iface, _mock_call, data_root=tmp_path, symbols=["000001.SZ", "600000.SH"])
    assert s2.units_done == 0 and s2.units_skipped == 2


def test_backfill_market_scope(tmp_path: Path) -> None:
    iface = tushare.TushareInterface("stock_basic", "stock_basic", "market", {"list_status": "L"})
    s = tushare.backfill_interface(iface, _mock_call, data_root=tmp_path)
    assert s.units_done == 1
    assert len(tushare.read_tushare("stock_basic", data_root=tmp_path)) == 2


def test_backfill_all_a_share_subset(tmp_path: Path) -> None:
    ifaces = (
        tushare.TushareInterface("stock_basic", "stock_basic", "market", {"list_status": "L"}),
        tushare.TushareInterface("daily", "daily", "per_symbol"),
    )
    out = tushare.backfill_all_a_share(_mock_call, data_root=tmp_path, interfaces=ifaces, symbols=["000001.SZ"])
    assert {s.interface for s in out} == {"stock_basic", "daily"}
    assert sum(s.rows for s in out) > 0


# ───────── code-review 回归：数据回填 3 bug ─────────

def test_binance_daily_does_not_predate_start(tmp_path: Path) -> None:
    """回归 #7：start 在月中时，日 zip 不应拉早于 start 的天。"""
    fetched: list[str] = []

    def spy(url: str) -> bytes | None:
        fetched.append(url)
        return _mock_fetch(url)

    res = binance.stitch_klines(
        "BTCUSDT", "1d", market="um", start=date(2023, 2, 5), end=date(2023, 2, 15),
        data_root=tmp_path, fetch=spy,
    )
    # 不应请求 Feb1..Feb4
    for d in range(1, 5):
        assert not any(url.endswith(f"2023-02-0{d}.zip") for url in fetched), f"误拉 Feb-0{d}"
    # 应请求 Feb5..Feb15
    assert any(url.endswith("2023-02-05.zip") for url in fetched)
    assert res.days_pulled == 11  # 5..15


def test_binance_gap_unknown_interval_not_silent_zero(tmp_path: Path) -> None:
    """回归 #8：未知 interval 的缺口检测不静默返回 0，而是 -1（不可判定）。"""
    def fetch(url: str) -> bytes | None:
        # 任意 interval 的日 zip 给一行
        if url.endswith(".zip") and "daily" in url:
            return _kline_zip([_ms(2023, 5, 1)])
        return None

    res = binance.stitch_klines(
        "BTCUSDT", "1M", market="um", start=date(2023, 5, 1), end=date(2023, 5, 1),
        data_root=tmp_path, fetch=fetch,
    )
    assert res.gaps == -1  # 未知间隔 → 不可判定，而非误报 0
    # 已映射的 interval 仍正常算
    assert binance._count_gaps([0, 60000, 120000], 60000) == 0
    assert binance._count_gaps([0, 180000], 60000) == 1
    assert binance._count_gaps([0, 1], 0) == -1  # step 未知


def test_tushare_empty_frame_not_persisted_resumes(tmp_path: Path) -> None:
    """回归 #9：空结果不落盘 → resume 会重试，不被永久跳过。"""
    calls = {"n": 0}

    def flaky_call(api_name: str, **params):
        # 第一次返回空（模拟瞬时失败），第二次返回数据
        calls["n"] += 1
        if calls["n"] == 1:
            return pd.DataFrame()  # 空
        return pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20230103"], "close": [10.0]})

    iface = tushare.TushareInterface("daily", "daily", "per_symbol")
    s1 = tushare.backfill_interface(iface, flaky_call, data_root=tmp_path, symbols=["000001.SZ"])
    assert s1.units_done == 0 and s1.empty == 1  # 空，未落盘
    assert not (tmp_path / "tushare" / "daily" / "000001.SZ.parquet").exists()
    # resume：这次拿到数据
    s2 = tushare.backfill_interface(iface, flaky_call, data_root=tmp_path, symbols=["000001.SZ"])
    assert s2.units_done == 1 and s2.units_skipped == 0  # 重试成功，未被跳过
    assert len(tushare.read_tushare("daily", data_root=tmp_path, ts_code="000001.SZ")) == 1
