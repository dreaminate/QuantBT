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

    def suspend_d(self, ts_code="", **_kw):
        self._count("suspend_d")
        codes = ts_code.split(",")
        return pd.DataFrame(
            {"ts_code": [codes[0]], "trade_date": ["20240103"],
             "suspend_timing": [None], "suspend_type": ["S"]}
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
    assert len(list((staging / "suspend_d").glob("*.parquet"))) == 2
    assert (staging / "index_daily_000300SH.parquet").exists()


def test_fetch_resumes_after_mid_pipeline_daily_limit(tmp_path):
    # 种坏:第二次 index_weight 调用抛当日上限 → 重跑后已完成单元零重复调用。
    class _LimitOnceThenOk(_FakePro):
        def __init__(self):
            super().__init__()
            self.iw_calls = 0

        def index_weight(self, **kw):
            self.iw_calls += 1
            if self.iw_calls == 2:
                raise Exception("抱歉，您每天最多访问该接口100000次")
            return super().index_weight(**kw)

    pro = _LimitOnceThenOk()
    limiter = RateLimiter(per_minute=100000, sleeper=lambda _s: None)
    kwargs = dict(
        pro=pro, start_compact="20240101", end_compact="20240229",
        calendar_start="20240101", calendar_end="20240301",
        limiter=limiter, sleeper=lambda _s: None,
    )
    with pytest.raises(DailyLimitError):
        fetch_raw_hs300(tmp_path / "staging", **kwargs)
    trade_cal_calls = pro.calls["trade_cal"]
    result = fetch_raw_hs300(tmp_path / "staging", **kwargs)  # 续拉
    assert result["members"] == 4
    # 已完成单元(trade_cal/stock_basic/第一个月快照)不重复调用
    assert pro.calls["trade_cal"] == trade_cal_calls


def test_assemble_panel_rejects_corrupt_parquet(tmp_path):
    # 种坏:daily 目录混入半写损坏文件 → 组面板必须炸出来,不许静默跳过。
    from app.data_onboarding import assemble_panel as _assemble

    pro = _FakePro()
    limiter = RateLimiter(per_minute=100000, sleeper=lambda _s: None)
    fetch_raw_hs300(
        tmp_path / "staging", pro=pro,
        start_compact="20240101", end_compact="20240229",
        calendar_start="20240101", calendar_end="20240301",
        limiter=limiter, sleeper=lambda _s: None,
    )
    corrupt = tmp_path / "staging" / "daily" / "zz_corrupt.parquet"
    corrupt.write_bytes(b"PAR1" + b"\x00" * 64)
    with pytest.raises(Exception):
        _assemble(
            tmp_path / "staging",
            members=[f"00000{i}.SZ" for i in range(1, 5)],
            start_date="2024-01-01", end_date="2024-02-29",
        )


def test_cli_missing_token_hint_never_suggests_keygen(tmp_path, monkeypatch):
    # 种坏回归:缺外部 token 时的报错绝不能指向 keygen(会生成随机串顶替真 token)。
    import importlib.util
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location(
        "hs300_onboard", _P(__file__).resolve().parents[3].parent / "scripts" / "hs300_onboard.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _EmptyKS:
        def fetch(self, _name):
            return None

    monkeypatch.setattr(mod, "_keystore", lambda: _EmptyKS())
    with pytest.raises(SystemExit) as exc_info:
        mod._fetch_key("tushare")
    message = str(exc_info.value)
    assert "store-token" in message
    assert "keygen --key-name tushare" not in message
    with pytest.raises(SystemExit) as exc_info2:
        mod._fetch_key("hs300_provenance")
    assert "keygen" in str(exc_info2.value)
