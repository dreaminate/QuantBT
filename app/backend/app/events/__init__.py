"""v0.8.4 Day 5 · 简易事件埋点 (sqlite events 表)。

按 GPT Pro patch1 §H 设计：events 表 + json properties + 三个常用索引。
v0.8.4 阶段只支持 4 个核心事件：
  - run_detail_viewed
  - risk_metric_expanded
  - glossary_term_viewed
  - risk_summary_shown

v0.8.6 起会扩展到 10 个事件 + funnel SQL + 可选 PostHog。
"""

from __future__ import annotations

from .service import EventService, EventTrackError

__all__ = ["EventService", "EventTrackError"]
