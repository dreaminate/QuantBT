"""CLI：跑本周（或指定周）的实盘 vs 回测成本偏差报告。

用法：
    python scripts/weekly_cost_drift.py --audit-log data/audit/audit.jsonl --asset crypto_perp
    python scripts/weekly_cost_drift.py --week 2024-W18 ...

可挂到 M13 DAG，每周一早上跑上周的报告。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.monitor import compute_weekly_cost_drift
from app.monitor.cost_drift import write_weekly_report


def _parse_week(s: str | None) -> date | None:
    if not s:
        return None
    if s.lower() == "now":
        return datetime.now().date()
    y, w = s.split("-W")
    return datetime.fromisocalendar(int(y), int(w), 4).date()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-log", default="data/audit/audit.jsonl")
    parser.add_argument("--asset", default="crypto_perp")
    parser.add_argument("--week", default="now", help="ISO 周如 2024-W18 或 'now'")
    parser.add_argument("--out-dir", default="data/reports")
    args = parser.parse_args()
    log = Path(args.audit_log)
    if not log.exists():
        print(f"audit log 不存在: {log}", file=sys.stderr)
        return 1
    records = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    report = compute_weekly_cost_drift(records, week=_parse_week(args.week), asset_class=args.asset)
    target = write_weekly_report(report, Path(args.out_dir))
    print(f"✅ 已写 {target}")
    print(report.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
