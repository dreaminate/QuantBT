"""卡状态跃迁 → 谱系总线 PROV 事件（T-017 / spine 04 §3.4，00 §1.2-D）。

每次 draft→frozen→deviated→retired 必须发一条 PROV 事件，否则审计轨迹缺一段。
部件03 完整 PROV DAG 总线未就绪（T-013 只建了 ledger 部分）→ 走 on_event 回调 + 本地
`pending_lineage` 留痕，**绝不静默吞掉**（部件03 总线上线后一次性回填 + 覆盖盲区告警，§7-7）。
"""

from __future__ import annotations

from typing import Any, Callable

EventSink = Callable[[str, dict[str, Any]], None]


class LineageHook:
    def __init__(self, on_event: EventSink | None = None) -> None:
        self._on_event = on_event
        self.pending: list[dict[str, Any]] = []   # 总线未就绪时的待回填留痕（不静默吞）

    def emit(self, card, transition: str) -> None:
        payload = {
            "transition": transition,            # freeze | deviate | retire | promote
            "card_id": card.card_id,
            "content_hash": card.content_hash,
            "layer": card.layer,
            "strategy_goal_ref": card.strategy_goal_ref,
        }
        if self._on_event is not None:
            try:
                self._on_event(f"card.{transition}", payload)
            except Exception:  # noqa: BLE001  复核 #8：sink 失败不得静默丢事件 → 落 pending 留痕
                self.pending.append({**payload, "delivery_failed": True})
        else:
            self.pending.append(payload)          # 总线未就绪：留痕，等部件03回填


__all__ = ["LineageHook"]
