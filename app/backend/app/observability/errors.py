"""错误上报：Sentry 接入位 + 默认本地日志。

设计：
- `SENTRY_DSN` 环境变量存在 → 自动 init sentry-sdk + FastAPI integration
- 任何情况都把错误落 `data/audit/errors.jsonl`（append-only）
- 提供 `report_exception(exc, context)` 单一入口；调用方不关心 Sentry 在不在
"""

from __future__ import annotations

import json
import logging
import os
import threading
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class LocalErrorLog:
    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]


@dataclass
class ErrorReporter:
    local_log: LocalErrorLog
    sentry_enabled: bool = False
    sentry_dsn_set: bool = False

    def report(self, exc: BaseException, context: dict[str, Any] | None = None) -> None:
        ctx = dict(context or {})
        payload = {
            "ts_utc": datetime.now(UTC).isoformat(),
            "exc_type": type(exc).__name__,
            "exc_msg": str(exc)[:1000],
            "traceback": "".join(traceback.format_exception(exc))[-4000:],
            "context": ctx,
            "sentry": self.sentry_enabled,
        }
        try:
            self.local_log.append(payload)
        except Exception as log_exc:  # noqa: BLE001
            logger.warning("写本地 error log 失败：%s", log_exc)
        if self.sentry_enabled:
            try:
                import sentry_sdk  # type: ignore[import-not-found]

                with sentry_sdk.new_scope() as scope:
                    for k, v in ctx.items():
                        scope.set_tag(k, str(v)[:100])
                    sentry_sdk.capture_exception(exc)
            except Exception as sentry_exc:  # noqa: BLE001
                logger.warning("sentry 上报失败：%s", sentry_exc)

    def info_snapshot(self) -> dict[str, Any]:
        return {
            "sentry_enabled": self.sentry_enabled,
            "sentry_dsn_set": self.sentry_dsn_set,
            "local_log_path": str(self.local_log.path),
            "recent": self.local_log.tail(10),
        }


_REPORTER: ErrorReporter | None = None


def init_error_reporting(log_path: Path | None = None) -> ErrorReporter:
    """启动时调一次；DSN 设了就 init sentry-sdk。"""

    global _REPORTER
    log_path = Path(log_path or Path("data") / "audit" / "errors.jsonl")
    reporter = ErrorReporter(local_log=LocalErrorLog(path=log_path))
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if dsn:
        reporter.sentry_dsn_set = True
        try:
            import sentry_sdk  # type: ignore[import-not-found]

            sentry_sdk.init(
                dsn=dsn,
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
                send_default_pii=False,
                environment=os.environ.get("QUANTBT_ENV", "dev"),
            )
            reporter.sentry_enabled = True
            logger.info("Sentry 已启用（dsn 前缀 %s...）", dsn[:18])
        except ImportError:
            logger.warning("SENTRY_DSN 已设但 sentry-sdk 未安装；仅本地落日志")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sentry 初始化失败：%s；仅本地落日志", exc)
    _REPORTER = reporter
    return reporter


def get_reporter() -> ErrorReporter:
    if _REPORTER is None:
        return init_error_reporting()
    return _REPORTER


__all__ = ["ErrorReporter", "LocalErrorLog", "get_reporter", "init_error_reporting"]
