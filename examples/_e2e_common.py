"""端到端 demo 共用工具：合成 panel + 写标准 run 目录。

两个 demo（A股 / 加密永续）共享：
- `synthetic_panel(...)` 产生 deterministic 多 symbol panel + sector
- `write_run_artifacts(...)` 把 portfolio / trades / metrics / report.md 落到
  `data/artifacts/experiments/{run_id}/`（兼容现有 RunDetailPage 期望格式）
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

# 让 demo 脚本直接跑时也能 import app.*
BACKEND_DIR = Path(__file__).resolve().parents[1] / "app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def project_run_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "artifacts" / "experiments"


# ----- 合成 panel -----

def synthetic_panel(
    *,
    symbols: list[str],
    sectors: dict[str, str] | None = None,
    days: int = 240,
    start: datetime | None = None,
    base_price: float = 10.0,
    seed: int = 7,
    drift_per_symbol: dict[str, float] | None = None,
    volatility: float = 0.02,
) -> pl.DataFrame:
    """生成 (ts, symbol, market, interval, open, high, low, close, volume, amount, sector)
    panel；deterministic（同 seed 同输出）。
    """

    rng = np.random.default_rng(seed)
    start_dt = start or datetime(2023, 1, 1, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for sid, symbol in enumerate(symbols):
        sector = (sectors or {}).get(symbol, "tech")
        drift = (drift_per_symbol or {}).get(symbol, 0.0003 * (sid % 5 - 2))
        prev = base_price * (1 + sid * 0.1)
        for i in range(days):
            ts = start_dt + timedelta(days=i)
            shock = rng.normal(loc=drift, scale=volatility)
            close = prev * (1 + shock)
            high = max(prev, close) * (1 + abs(rng.normal(scale=0.005)))
            low = min(prev, close) * (1 - abs(rng.normal(scale=0.005)))
            volume = float(rng.integers(800_000, 1_500_000))
            rows.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "market": "stocks_cn",
                    "interval": "1d",
                    "open": prev,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": volume * close,
                    "sector": sector,
                }
            )
            prev = close
    return pl.DataFrame(rows).sort(["symbol", "ts"])


# ----- 标准 run 目录写盘 -----

def _to_iso(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.astimezone(UTC).isoformat()
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.isoformat()
    return str(ts)


def write_run_artifacts(
    *,
    run_id: str,
    run_meta: dict[str, Any],
    portfolio: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: dict[str, Any],
    report_markdown: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """落到 data/artifacts/experiments/{run_id}/，按现有 RunDetailPage 期望的列名。"""

    root = project_run_root() / run_id
    root.mkdir(parents=True, exist_ok=True)

    portfolio = portfolio.copy()
    if "timestamp" in portfolio.columns:
        portfolio["timestamp"] = portfolio["timestamp"].map(_to_iso)
    portfolio.to_csv(root / "portfolio.csv", index=False)

    trades = trades.copy()
    if "execution_timestamp" in trades.columns:
        trades["execution_timestamp"] = trades["execution_timestamp"].map(_to_iso)
    trades.to_csv(root / "trades.csv", index=False)

    run_json = {
        "run_id": run_id,
        "started_at": run_meta.get("started_at_utc") or datetime.now(UTC).isoformat(),
        "status": "completed",
        **run_meta,
        "metrics": metrics,
    }
    (root / "run.json").write_text(json.dumps(run_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "report.md").write_text(report_markdown, encoding="utf-8")

    for name, content in (extra_files or {}).items():
        (root / name).write_text(content, encoding="utf-8")
    return root


__all__ = [
    "BACKEND_DIR",
    "project_run_root",
    "synthetic_panel",
    "write_run_artifacts",
]
