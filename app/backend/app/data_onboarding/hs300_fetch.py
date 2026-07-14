"""HS300 十年日频 raw staging 拉取（Tushare 2000 积分档;research-only）。

链条第一步的可复现实现:staging 缓存 = hs300_pipeline.assemble_panel 的唯一输入。
布局(与 pipeline 消费端契约一致):

    <staging>/trade_cal_sse.parquet
    <staging>/stock_basic_{L,D}.parquet
    <staging>/index_weight/YYYYMM.parquet      # 逐月 000300.SH 成分快照
    <staging>/daily/<code>__<code>.parquet     # 2 码/文件并联
    <staging>/adj_factor/<code>__<code>.parquet
    <staging>/index_daily_000300SH.parquet

设计依据(tushare.pro 文档,2026-07 实测):回填 ts_code 轴(单码十年≈2446 行<6000 行上限,
2 码并联);限速保守 180 次/分(权限表 2000 档=200 次/分,daily 接口页自称 500——取小值留余量);
错误退避按官方 msg 子串:「每分钟最多访问」睡满窗口重试、「每天最多访问」抛 DailyLimitError、
「没有…权限」抛 PermissionDeniedError 不重试。幂等:已存在的 parquet 单元跳过,重跑续拉。

Token 红线:只经 SecureKeystore(keyring name="tushare")解析,绝不打印/落盘/入异常文本。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

RATE_LIMIT_PER_MIN = 180
_RETRY_BASE_SECONDS = 2.0
_RETRY_MAX_SECONDS = 60.0
_MAX_ATTEMPTS = 8


class DailyLimitError(RuntimeError):
    """Tushare 当日调用上限已耗尽——停到次日,不重试。"""


class PermissionDeniedError(RuntimeError):
    """接口权限不足——配置错误,不重试。"""


class RateLimiter:
    """滑动窗口限速:每 60s 至多 ``per_minute`` 次调用(monotonic 时钟,免时钟回拨)。"""

    def __init__(self, per_minute: int = RATE_LIMIT_PER_MIN, clock=time.monotonic,
                 sleeper=time.sleep) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute 必须为正")
        self.per_minute = per_minute
        self._clock = clock
        self._sleep = sleeper
        self._calls: list[float] = []

    def acquire(self) -> None:
        while True:  # sleep 后重查窗口,时钟未前进也不会放行超额调用
            now = self._clock()
            self._calls = [t for t in self._calls if now - t < 60.0]
            if len(self._calls) < self.per_minute:
                self._calls.append(now)
                return
            wait = 60.0 - (now - self._calls[0]) + 0.5
            self._sleep(max(wait, 0.1))


def classify_tushare_error(message: str) -> str:
    """官方无数字错误码,只有 msg 文本——按子串分类退避策略。"""
    if "每分钟最多访问" in message:
        return "rate_limit"
    if "每天最多访问" in message:
        return "daily_limit"
    if "没有" in message and "权限" in message:
        return "permission"
    return "transient"


def call_with_backoff(fn: Callable[..., Any], *, limiter: RateLimiter,
                      sleeper=time.sleep, **kwargs: Any) -> Any:
    delay = _RETRY_BASE_SECONDS
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        limiter.acquire()
        try:
            return fn(**kwargs)
        except Exception as exc:  # tushare SDK 只抛携 msg 的裸 Exception,无类型分层
            kind = classify_tushare_error(str(exc))
            if kind == "daily_limit":
                raise DailyLimitError("Tushare 当日接口上限耗尽,次日再续(幂等续拉)") from None
            if kind == "permission":
                raise PermissionDeniedError(
                    "Tushare 接口权限不足(检查积分档)"
                ) from None
            last_exc = exc
            if attempt == _MAX_ATTEMPTS - 1:
                break  # 最后一跳不再睡
            sleeper(61.0 if kind == "rate_limit" else delay)
            if kind != "rate_limit":
                delay = min(delay * 2.0, _RETRY_MAX_SECONDS)
    raise RuntimeError(
        f"Tushare 调用重试耗尽(最后错误 {type(last_exc).__name__})"
    ) from last_exc


def _save_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # .partial 后缀不以 .parquet 结尾:中断残留绝不会被消费端 *.parquet glob 读入
    tmp = path.with_name(path.name + ".partial")
    frame.to_parquet(tmp, index=False)
    tmp.rename(path)


def fetch_raw_hs300(
    staging_dir: str | Path,
    *,
    pro: Any,
    start_compact: str = "20160601",
    end_compact: str = "20260630",
    calendar_start: str = "20150101",
    calendar_end: str = "20261231",
    per_minute: int = RATE_LIMIT_PER_MIN,
    progress: Callable[[str], None] | None = None,
    limiter: RateLimiter | None = None,
    sleeper=time.sleep,
) -> dict[str, Any]:
    """全量回填 staging(幂等:已有单元跳过)。``pro`` = tushare pro_api 实例。

    调用量级(2026-07 实测):日历 1 + 股票表 2 + 月度快照 ~121 + 并集 622 只
    ×2 接口 ÷2 码/次 ≈ 700 次,180 次/分下约 4-6 分钟。

    注意:staging 目录与拉取窗口一一绑定——单元文件名不含窗口参数,换 start/end
    必须换新 staging 目录,否则旧窗口缓存会被幂等跳过(下游 preflight 会拦但费解)。
    """
    root = Path(staging_dir)
    root.mkdir(parents=True, exist_ok=True)
    limiter = limiter or RateLimiter(per_minute, sleeper=sleeper)
    note = progress or (lambda _s: None)

    def have(rel: str) -> bool:
        return (root / rel).exists()

    if not have("trade_cal_sse.parquet"):
        frame = call_with_backoff(
            pro.trade_cal, limiter=limiter, sleeper=sleeper,
            exchange="SSE", start_date=calendar_start, end_date=calendar_end,
        )
        _save_atomic(frame, root / "trade_cal_sse.parquet")
        note("trade_cal saved")
    for status in ("L", "D"):
        rel = f"stock_basic_{status}.parquet"
        if not have(rel):
            frame = call_with_backoff(
                pro.stock_basic, limiter=limiter, sleeper=sleeper,
                list_status=status,
                fields="ts_code,symbol,name,area,industry,market,exchange,"
                       "list_status,list_date,delist_date",
            )
            _save_atomic(frame, root / rel)
            note(f"stock_basic {status} saved")

    months = pd.period_range(
        f"{start_compact[:4]}-{start_compact[4:6]}",
        f"{end_compact[:4]}-{end_compact[4:6]}",
        freq="M",
    )
    for month in months:
        rel = f"index_weight/{month.strftime('%Y%m')}.parquet"
        if have(rel):
            continue
        frame = call_with_backoff(
            pro.index_weight, limiter=limiter, sleeper=sleeper,
            index_code="000300.SH",
            start_date=month.start_time.strftime("%Y%m%d"),
            end_date=month.end_time.strftime("%Y%m%d"),
        )
        if frame is None or frame.empty:
            frame = pd.DataFrame(
                columns=["index_code", "con_code", "trade_date", "weight"]
            )
            note(f"index_weight {month} EMPTY")
        _save_atomic(frame, root / rel)
    note(f"index_weight monthly done ({len(months)} months)")

    union: set[str] = set()
    for month in months:
        part = pd.read_parquet(root / f"index_weight/{month.strftime('%Y%m')}.parquet")
        union.update(part["con_code"].dropna().tolist())
    members = sorted(union)
    _save_atomic(pd.DataFrame({"ts_code": members}), root / "member_union.parquet")
    note(f"member union: {len(members)}")

    pairs = [members[i : i + 2] for i in range(0, len(members), 2)]
    for kind, fn in (("daily", pro.daily), ("adj_factor", pro.adj_factor)):
        done = 0
        for pair in pairs:
            key = "__".join(code.replace(".", "_") for code in pair)
            rel = f"{kind}/{key}.parquet"
            if not have(rel):
                frame = call_with_backoff(
                    fn, limiter=limiter, sleeper=sleeper,
                    ts_code=",".join(pair),
                    start_date=start_compact, end_date=end_compact,
                )
                _save_atomic(
                    frame if frame is not None else pd.DataFrame(), root / rel
                )
            done += 1
            if done % 50 == 0:
                note(f"{kind}: {done}/{len(pairs)}")
        note(f"{kind} done: {done}/{len(pairs)}")

    if not have("index_daily_000300SH.parquet"):
        frame = call_with_backoff(
            pro.index_daily, limiter=limiter, sleeper=sleeper,
            ts_code="000300.SH", start_date=start_compact, end_date=end_compact,
        )
        _save_atomic(frame, root / "index_daily_000300SH.parquet")
        note("index_daily saved")
    note("ALL RAW FETCH COMPLETE")
    return {"members": len(members), "months": len(months), "staging": str(root)}


__all__ = [
    "DailyLimitError",
    "PermissionDeniedError",
    "RateLimiter",
    "call_with_backoff",
    "classify_tushare_error",
    "fetch_raw_hs300",
]
