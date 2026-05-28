"""GOAL §M9.3 G + §13.3 末项：实盘 vs 回测每周成本偏差报告。

实盘成本来源：ExecutionAuditLog 中 `fill` / `binance_*_place` 记录的 commission；
回测预期：strategy 关联的 cost_model（BacktestCostModel / CryptoPerpCostModel）
按对应名义重新计算。

输出：
- `data/reports/cost_drift_{YYYYWW}.md`
- 同时返回 `CostDriftReport` 对象给 API / DAG
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


@dataclass
class CostDriftReport:
    week_iso: str            # "2024-W18"
    asset_class: str
    n_fills: int = 0
    total_notional: float = 0.0
    actual_total_cost: float = 0.0
    expected_total_cost: float = 0.0
    drift_abs: float = 0.0
    drift_pct: float | None = None
    by_symbol: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# 成本偏差报告 · {self.week_iso} · {self.asset_class}",
            "",
            f"- 成交笔数: {self.n_fills}",
            f"- 总名义: {self.total_notional:.2f}",
            f"- **实盘成本**: {self.actual_total_cost:.4f}",
            f"- **回测预期**: {self.expected_total_cost:.4f}",
            f"- **绝对偏差**: {self.drift_abs:.4f}"
            + (f" ({self.drift_pct*100:.2f}%)" if self.drift_pct is not None else ""),
            "",
            "## 按 symbol 拆分",
            "",
            "| symbol | n_fills | notional | actual | expected | drift |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for sym, info in sorted(self.by_symbol.items()):
            lines.append(
                f"| {sym} | {info['n_fills']:.0f} | {info['notional']:.2f} | "
                f"{info['actual']:.4f} | {info['expected']:.4f} | {info['drift']:.4f} |"
            )
        if self.notes:
            lines += ["", "## Notes"]
            for n in self.notes:
                lines.append(f"- {n}")
        return "\n".join(lines)


def _week_iso(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def compute_weekly_cost_drift(
    audit_records: Iterable[dict[str, Any]],
    *,
    week: date | None = None,
    asset_class: str = "crypto_perp",
    expected_commission_bps: float = 4.0,
    expected_slippage_bps: float = 2.0,
    expected_funding_apply: bool = True,
    expected_funding_bps_per_day: float = 3.0,
) -> CostDriftReport:
    """对 audit log（kind='fill' / 'binance_*_place'）算本周成本偏差。"""

    week = week or datetime.now(UTC).date()
    week_iso = _week_iso(week)
    week_monday = week - timedelta(days=week.weekday())
    week_friday = week_monday + timedelta(days=6)

    report = CostDriftReport(week_iso=week_iso, asset_class=asset_class)
    bps = (expected_commission_bps + expected_slippage_bps) * 1e-4

    for record in audit_records:
        kind = record.get("kind", "")
        # 只统计真实成交事件；place ack 不算
        if kind not in {"fill", "paper_fill"}:
            continue
        payload = record.get("payload", {}) or {}
        # 时间筛选
        ts = payload.get("ts") or payload.get("timestamp") or record.get("logged_at_utc")
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(UTC).date()
        except Exception:  # noqa: BLE001
            continue
        if not (week_monday <= dt <= week_friday + timedelta(days=2)):  # 含周末
            continue
        # 名义 + 实际成本
        qty = float(payload.get("filled_qty") or payload.get("quantity") or 0)
        price = float(payload.get("fill_price") or payload.get("price") or 0)
        notional = abs(qty * price)
        actual_cost = float(payload.get("commission") or payload.get("estimated_fee") or 0)
        expected_cost = notional * bps
        if asset_class == "crypto_perp" and expected_funding_apply:
            # 简化：funding 按日 bps * 1（假设一天 1 笔 funding；真实 8h 三次需 caller 在 audit 中给）
            expected_cost += notional * expected_funding_bps_per_day * 1e-4
        sym = str(payload.get("symbol") or "")
        per = report.by_symbol.setdefault(sym, {"n_fills": 0, "notional": 0, "actual": 0, "expected": 0, "drift": 0})
        per["n_fills"] += 1
        per["notional"] += notional
        per["actual"] += actual_cost
        per["expected"] += expected_cost
        per["drift"] += actual_cost - expected_cost
        report.n_fills += 1
        report.total_notional += notional
        report.actual_total_cost += actual_cost
        report.expected_total_cost += expected_cost

    report.drift_abs = report.actual_total_cost - report.expected_total_cost
    if report.expected_total_cost > 0:
        report.drift_pct = report.drift_abs / report.expected_total_cost
    if abs(report.drift_pct or 0) > 0.30:
        report.notes.append("⚠️ 实盘成本偏离回测预期超过 30%，请检查 cost_model 是否需重标定")
    return report


def write_weekly_report(
    report: CostDriftReport,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"cost_drift_{report.week_iso}.md"
    target.write_text(report.to_markdown(), encoding="utf-8")
    return target


__all__ = ["CostDriftReport", "compute_weekly_cost_drift", "write_weekly_report"]
