#!/usr/bin/env python3
"""v0.8.4 Day 5 · 首次跑回测耗时分布 SQL smoke。

按 GPT Pro patch1 §H.c 的 SQL 跑：注册 → 首次成功 run_completed 间隔，bucket 直方图。

v0.8.4 baseline 阶段 events 表里只有 run_detail_viewed / risk_metric_expanded /
glossary_term_viewed / risk_summary_shown 四个事件；user_registered 和 run_completed
要等 v0.8.6 接入。本脚本现在跑会返空表（无错），但 schema 已就位，v0.8.6 接入后直
接出图。

用法:
    python scripts/query_first_run_time.py
    python scripts/query_first_run_time.py --db data/community.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


SQL_BUCKET = """
WITH registered AS (
  SELECT user_id, MIN(datetime(occurred_at)) AS registered_at
  FROM events WHERE event_name='user_registered' AND user_id IS NOT NULL GROUP BY user_id
),
first_success_run AS (
  SELECT user_id, MIN(datetime(occurred_at)) AS first_run_at
  FROM events
  WHERE event_name='run_completed'
    AND json_extract(properties,'$.status')='success'
    AND user_id IS NOT NULL
  GROUP BY user_id
),
delta AS (
  SELECT r.user_id,
         CAST((julianday(f.first_run_at)-julianday(r.registered_at))*24*60 AS INTEGER) AS minutes
  FROM registered r JOIN first_success_run f ON r.user_id=f.user_id
  WHERE f.first_run_at >= r.registered_at
),
bucketed AS (
  SELECT CASE
           WHEN minutes < 5 THEN '00_<5min'
           WHEN minutes < 15 THEN '01_5-15min'
           WHEN minutes < 30 THEN '02_15-30min'
           WHEN minutes < 60 THEN '03_30-60min'
           WHEN minutes < 180 THEN '04_1-3h'
           WHEN minutes < 1440 THEN '05_3-24h'
           ELSE '06_>24h'
         END AS bucket,
         COUNT(*) AS users
  FROM delta
  GROUP BY 1
)
SELECT bucket, users, ROUND(users*100.0/SUM(users) OVER (), 2) AS pct
FROM bucketed ORDER BY bucket;
"""

SQL_PERCENTILES = """
WITH registered AS (
  SELECT user_id, MIN(datetime(occurred_at)) AS registered_at
  FROM events WHERE event_name='user_registered' GROUP BY user_id
),
first_success_run AS (
  SELECT user_id, MIN(datetime(occurred_at)) AS first_run_at
  FROM events WHERE event_name='run_completed' AND json_extract(properties,'$.status')='success'
  GROUP BY user_id
),
delta AS (
  SELECT r.user_id,
         CAST((julianday(f.first_run_at)-julianday(r.registered_at))*24*60 AS INTEGER) AS minutes
  FROM registered r JOIN first_success_run f ON r.user_id=f.user_id
),
ranked AS (
  SELECT minutes, ROW_NUMBER() OVER (ORDER BY minutes) AS rn, COUNT(*) OVER () AS n FROM delta
)
SELECT
  MIN(CASE WHEN rn >= CAST(n*0.50 AS INTEGER) THEN minutes END) AS p50_min,
  MIN(CASE WHEN rn >= CAST(n*0.90 AS INTEGER) THEN minutes END) AS p90_min,
  MAX(n) AS total_users
FROM ranked;
"""

SQL_BASELINE_COUNTS = """
SELECT event_name, COUNT(*) AS cnt
FROM events
GROUP BY event_name
ORDER BY cnt DESC;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="首次跑回测耗时 funnel")
    parser.add_argument("--db", default="data/community.db")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"DB 不存在: {db}", file=sys.stderr)
        return 1

    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row

        # 先看表是否有
        try:
            counts = c.execute(SQL_BASELINE_COUNTS).fetchall()
        except sqlite3.OperationalError as exc:
            print(f"events 表未初始化: {exc}", file=sys.stderr)
            print("  → 启动主后端会自动建表 (EventService 在 main.py 加载)")
            return 1

        print("--- 事件总览 ---")
        if not counts:
            print("  (无事件)")
        for row in counts:
            print(f"  {row['event_name']:32s} {row['cnt']}")

        print()
        print("--- 首次跑回测耗时 bucket 分布 ---")
        rows = c.execute(SQL_BUCKET).fetchall()
        if not rows:
            print("  (无数据 — v0.8.4 baseline 还没有 user_registered / run_completed 埋点)")
        else:
            print(f"  {'bucket':14s} {'users':>6s} {'pct':>7s}")
            for r in rows:
                print(f"  {r['bucket']:14s} {r['users']:>6d} {r['pct']:>6.2f}%")

        print()
        print("--- 百分位 (p50 / p90 / total) ---")
        prow = c.execute(SQL_PERCENTILES).fetchone()
        if prow and prow["total_users"]:
            print(f"  p50_min={prow['p50_min']}, p90_min={prow['p90_min']}, total_users={prow['total_users']}")
            print(f"  目标: p50 < 15 分钟（v0.8.4 后期目标）")
        else:
            print("  (无 funnel 数据)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
