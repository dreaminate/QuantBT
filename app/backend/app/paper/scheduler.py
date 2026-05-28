"""Paper trading 进程常驻调度器。

设计：
- 每 N 秒拉一次最新 bar（按 connector 拉，或 caller 注入 bar provider）
- 喂给 PaperVenue.feed_bar()
- 每个交易日（A股 16:00 CST；加密 24:00 UTC）调 mark_to_market() 写 equity log
- 状态 expose 给 /api/paper/status
- 用 `python -m app.paper.scheduler --strategy <id>` 启动；后台线程化封装方便测试

线程模型：一个调度循环 + 一个 MTM 时钟，互不阻塞。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from ..execution.paper_venue import PaperEquitySnapshot, PaperVenue


logger = logging.getLogger(__name__)


BarProvider = Callable[[str], dict[str, Any] | None]   # symbol → bar dict
MarkProvider = Callable[[list[str]], dict[str, float]]  # symbols → marks
MarketKind = Literal["equity_cn", "crypto"]


@dataclass
class PaperSchedulerConfig:
    strategy_id: str
    symbols: list[str]
    bar_interval_seconds: float = 60.0
    market: MarketKind = "equity_cn"
    equity_log_path: Path | None = None
    auto_start_threads: bool = False


@dataclass
class PaperSchedulerState:
    strategy_id: str
    running: bool = False
    started_at_utc: str | None = None
    last_bar_at_utc: str | None = None
    last_mtm_at_utc: str | None = None
    bars_fed: int = 0
    mtm_count: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _next_close_utc(market: MarketKind, now: datetime | None = None) -> datetime:
    """下一个收盘 UTC 时间。A股 16:00 CST = 08:00 UTC（结算窗口 +30min）；加密 24:00 UTC。"""

    now = (now or datetime.now(UTC)).astimezone(UTC)
    if market == "equity_cn":
        target = now.replace(hour=8, minute=30, second=0, microsecond=0)
        while target <= now or target.weekday() >= 5:
            target = target + timedelta(days=1)
        return target
    # crypto: next day 00:00 UTC
    target = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return target


class PaperScheduler:
    def __init__(
        self,
        venue: PaperVenue,
        config: PaperSchedulerConfig,
        *,
        bar_provider: BarProvider | None = None,
        mark_provider: MarkProvider | None = None,
    ) -> None:
        self._venue = venue
        self._cfg = config
        self._bar_provider = bar_provider
        self._mark_provider = mark_provider
        self._state = PaperSchedulerState(strategy_id=config.strategy_id)
        self._stop_event = threading.Event()
        self._bar_thread: threading.Thread | None = None
        self._mtm_thread: threading.Thread | None = None
        if config.auto_start_threads:
            self.start()

    @property
    def state(self) -> PaperSchedulerState:
        return self._state

    def start(self) -> None:
        if self._state.running:
            return
        self._stop_event.clear()
        self._state.running = True
        self._state.started_at_utc = datetime.now(UTC).isoformat()
        self._bar_thread = threading.Thread(target=self._bar_loop, name="paper-bar", daemon=True)
        self._mtm_thread = threading.Thread(target=self._mtm_loop, name="paper-mtm", daemon=True)
        self._bar_thread.start()
        self._mtm_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        for t in (self._bar_thread, self._mtm_thread):
            if t and t.is_alive():
                t.join(timeout=2)
        self._state.running = False

    # ----- 让测试方便驱动的同步接口 -----

    def tick_once(self) -> int:
        """手动喂一轮 bar；返回成交数。测试 / Notebook 用。"""

        if not self._bar_provider:
            return 0
        fills = 0
        for sym in self._cfg.symbols:
            bar = self._bar_provider(sym)
            if bar is None:
                continue
            try:
                executed = self._venue.feed_bar(bar)
                fills += len(executed)
            except Exception as exc:  # noqa: BLE001
                self._state.last_error = f"feed_bar({sym}): {exc}"
                continue
        self._state.bars_fed += 1
        self._state.last_bar_at_utc = datetime.now(UTC).isoformat()
        return fills

    def mtm_once(self) -> PaperEquitySnapshot:
        marks: dict[str, float] = {}
        if self._mark_provider:
            marks = self._mark_provider(self._cfg.symbols)
        snap = self._venue.mark_to_market(marks)
        self._state.mtm_count += 1
        self._state.last_mtm_at_utc = snap.taken_at_utc
        return snap

    # ----- 后台线程 -----

    def _bar_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick_once()
            except Exception as exc:  # noqa: BLE001
                self._state.last_error = f"bar_loop: {exc}"
            if self._stop_event.wait(self._cfg.bar_interval_seconds):
                break

    def _mtm_loop(self) -> None:
        while not self._stop_event.is_set():
            target = _next_close_utc(self._cfg.market)
            wait_s = max((target - datetime.now(UTC)).total_seconds(), 1.0)
            # 把长 wait 切成短 sleep 便于响应 stop
            slept = 0.0
            while slept < wait_s and not self._stop_event.is_set():
                step = min(60.0, wait_s - slept)
                if self._stop_event.wait(step):
                    return
                slept += step
            if self._stop_event.is_set():
                return
            try:
                self.mtm_once()
            except Exception as exc:  # noqa: BLE001
                self._state.last_error = f"mtm_loop: {exc}"

    def snapshot(self) -> dict[str, Any]:
        snap = self._state.to_dict()
        # 顺带把 venue 余额暴露
        bal = self._venue.get_balance()
        snap["balance"] = {k: {"asset": v.asset, "free": v.free, "locked": v.locked} for k, v in bal.items()}
        snap["positions"] = {
            sym: {"quantity": pos.quantity, "entry_price": pos.entry_price, "mark_price": pos.mark_price}
            for sym, pos in self._venue._positions.items()  # noqa: SLF001
        }
        snap["config"] = {
            "strategy_id": self._cfg.strategy_id,
            "symbols": list(self._cfg.symbols),
            "interval_seconds": self._cfg.bar_interval_seconds,
            "market": self._cfg.market,
        }
        return snap


def _cli() -> None:
    """python -m app.paper.scheduler --strategy <id> --symbols BTCUSDT,ETHUSDT。

    生产实际接 connector 拉实时 bar；这里给一个 stub 实现，方便用户验证 wiring。
    """

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbols", required=True, help="comma-separated")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--market", choices=("equity_cn", "crypto"), default="crypto")
    args = parser.parse_args()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    venue = PaperVenue()
    cfg = PaperSchedulerConfig(
        strategy_id=args.strategy,
        symbols=syms,
        bar_interval_seconds=args.interval,
        market=args.market,
    )

    def _stub_bar(sym: str) -> dict[str, Any] | None:
        return None  # 占位；生产请注入 connector-driven provider

    sched = PaperScheduler(venue, cfg, bar_provider=_stub_bar)
    sched.start()
    print(json.dumps(sched.snapshot(), ensure_ascii=False))
    try:
        while True:
            time.sleep(30)
            print(json.dumps(sched.snapshot(), ensure_ascii=False))
    except KeyboardInterrupt:
        sched.stop()


if __name__ == "__main__":  # pragma: no cover
    _cli()


__all__ = ["PaperScheduler", "PaperSchedulerConfig", "PaperSchedulerState"]
