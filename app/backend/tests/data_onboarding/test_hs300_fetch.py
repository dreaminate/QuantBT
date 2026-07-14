"""hs300_fetch 对抗测试（无网络:假 pro API + 假时钟）。"""

from __future__ import annotations

import pandas as pd
import pytest

from app.data_onboarding.hs300_fetch import (
    DailyLimitError,
    PermissionDeniedError,
    RateLimiter,
    call_with_backoff,
    classify_tushare_error,
    fetch_raw_hs300,
)


def test_classify_tushare_error_official_substrings():
    assert classify_tushare_error("抱歉，您每分钟最多访问该接口500次") == "rate_limit"
    assert classify_tushare_error("抱歉，您每天最多访问该接口100000次") == "daily_limit"
    assert classify_tushare_error("抱歉，您没有访问该接口的权限") == "permission"
    assert classify_tushare_error("connection reset") == "transient"


def test_rate_limiter_sleeps_when_window_full():
    clock = {"now": 0.0}
    sleeps: list[float] = []

    def _clock():
        return clock["now"]

    def _sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    limiter = RateLimiter(per_minute=3, clock=_clock, sleeper=_sleep)
    for _ in range(3):
        limiter.acquire()
    assert not sleeps
    limiter.acquire()  # 第 4 次必须等窗口
    assert sleeps and sleeps[0] > 0


def test_call_with_backoff_rate_limit_retries_then_succeeds():
    sleeps: list[float] = []
    attempts = {"n": 0}

    def _fn(**_kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise Exception("抱歉，您每分钟最多访问该接口200次")
        return "ok"

    limiter = RateLimiter(per_minute=1000, sleeper=lambda s: sleeps.append(s))
    result = call_with_backoff(_fn, limiter=limiter, sleeper=lambda s: sleeps.append(s))
    assert result == "ok"
    assert 61.0 in sleeps


def test_call_with_backoff_daily_limit_raises_no_retry():
    calls = {"n": 0}

    def _fn(**_kw):
        calls["n"] += 1
        raise Exception("抱歉，您每天最多访问该接口100000次")

    limiter = RateLimiter(per_minute=1000, sleeper=lambda _s: None)
    with pytest.raises(DailyLimitError):
        call_with_backoff(_fn, limiter=limiter, sleeper=lambda _s: None)
    assert calls["n"] == 1


def test_call_with_backoff_permission_raises_no_retry():
    def _fn(**_kw):
        raise Exception("抱歉，您没有访问该接口的权限,权限的具体详情访问…")

    limiter = RateLimiter(per_minute=1000, sleeper=lambda _s: None)
    with pytest.raises(PermissionDeniedError):
        call_with_backoff(_fn, limiter=limiter, sleeper=lambda _s: None)


class _FakePro:
    """两个月×4 只股的最小假 Tushare pro API,记录调用数。"""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def _count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def trade_cal(self, **_kw):
        self._count("trade_cal")
        return pd.DataFrame(
            {"exchange": ["SSE"] * 2, "cal_date": ["20240102", "20240103"],
             "is_open": [1, 1], "pretrade_date": ["20231229", "20240102"]}
        )

    def stock_basic(self, list_status="L", **_kw):
        self._count("stock_basic")
        if list_status == "D":
            return pd.DataFrame(columns=["ts_code", "list_date", "delist_date"])
        return pd.DataFrame(
            {"ts_code": [f"00000{i}.SZ" for i in range(1, 5)],
             "list_date": ["20100104"] * 4}
        )

    def index_weight(self, **kw):
        self._count("index_weight")
        return pd.DataFrame(
            {"index_code": ["000300.SH"] * 4,
             "con_code": [f"00000{i}.SZ" for i in range(1, 5)],
             "trade_date": [kw["end_date"]] * 4, "weight": [25.0] * 4}
        )

    def daily(self, ts_code="", **_kw):
        self._count("daily")
        codes = ts_code.split(",")
        return pd.DataFrame(
            {"ts_code": codes, "trade_date": ["20240102"] * len(codes),
             "open": [10.0] * len(codes), "high": [11.0] * len(codes),
             "low": [9.5] * len(codes), "close": [10.5] * len(codes),
             "vol": [1000.0] * len(codes), "amount": [1000.0] * len(codes)}
        )

    def adj_factor(self, ts_code="", **_kw):
        self._count("adj_factor")
        codes = ts_code.split(",")
        return pd.DataFrame(
            {"ts_code": codes, "trade_date": ["20240102"] * len(codes),
             "adj_factor": [1.0] * len(codes)}
        )

    def index_daily(self, **_kw):
        self._count("index_daily")
        return pd.DataFrame(
            {"ts_code": ["000300.SH"], "trade_date": ["20240102"],
             "open": [3500.0], "high": [3550.0], "low": [3480.0],
             "close": [3520.0], "vol": [1.0], "amount": [1.0]}
        )


def test_fetch_raw_hs300_idempotent_skips_existing(tmp_path):
    pro = _FakePro()
    limiter = RateLimiter(per_minute=100000, sleeper=lambda _s: None)
    kwargs = dict(
        pro=pro, start_compact="20240101", end_compact="20240229",
        calendar_start="20240101", calendar_end="20240301",
        limiter=limiter, sleeper=lambda _s: None,
    )
    first = fetch_raw_hs300(tmp_path / "staging", **kwargs)
    assert first["members"] == 4
    calls_after_first = dict(pro.calls)
    second = fetch_raw_hs300(tmp_path / "staging", **kwargs)
    assert second["members"] == 4
    # 幂等:第二轮所有已缓存单元跳过,零新 API 调用
    assert pro.calls == calls_after_first


def test_fetch_layout_matches_pipeline_contract(tmp_path):
    pro = _FakePro()
    limiter = RateLimiter(per_minute=100000, sleeper=lambda _s: None)
    fetch_raw_hs300(
        tmp_path / "staging", pro=pro,
        start_compact="20240101", end_compact="20240229",
        calendar_start="20240101", calendar_end="20240301",
        limiter=limiter, sleeper=lambda _s: None,
    )
    staging = tmp_path / "staging"
    assert (staging / "trade_cal_sse.parquet").exists()
    assert (staging / "stock_basic_L.parquet").exists()
    assert (staging / "stock_basic_D.parquet").exists()
    assert sorted(p.name for p in (staging / "index_weight").glob("*.parquet")) == [
        "202401.parquet", "202402.parquet",
    ]
    assert len(list((staging / "daily").glob("*.parquet"))) == 2  # 4 只 ÷ 2 码/文件
    assert len(list((staging / "adj_factor").glob("*.parquet"))) == 2
    assert (staging / "index_daily_000300SH.parquet").exists()
