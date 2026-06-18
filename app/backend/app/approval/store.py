"""ApprovalGateStore · append-only 审批门事件落盘（T-019 / spine 07 §4-A）。

复用 `experiments/store.py:_JsonlStore`（append-only + 崩溃容错）。latest-wins 读当前态——
门状态跃迁每次 append 新行，恢复（R11）读最近完整行，绝不重跑前面的副作用。
"""

from __future__ import annotations

from pathlib import Path

from ..experiments.store import _JsonlStore
from .schema import ApprovalGate


class ApprovalGateStore:
    def __init__(self, root: Path | str) -> None:
        self._store = _JsonlStore(Path(root) / "approval_gates.jsonl")

    def append(self, gate: ApprovalGate) -> ApprovalGate:
        self._store.append(gate.to_dict())
        return gate

    def get(self, gate_id: str) -> ApprovalGate:
        latest = None
        for row in self._store.read_all():       # latest-wins
            if row.get("gate_id") == gate_id:
                latest = row
        if latest is None:
            raise KeyError(f"审批门不存在: {gate_id}")
        return ApprovalGate.from_dict(latest)

    def list_pending(self) -> list[ApprovalGate]:
        latest: dict[str, dict] = {}
        for row in self._store.read_all():
            latest[row["gate_id"]] = row
        return [ApprovalGate.from_dict(v) for v in latest.values() if v.get("decision") == "pending"]

    def list_executed_keys(self) -> set[str]:
        """所有已执行门后副作用的 idempotency_key（跨 gate 去重用，复核 #9）。"""

        latest: dict[str, dict] = {}
        for row in self._store.read_all():
            latest[row["gate_id"]] = row
        return {v.get("idempotency_key", "") for v in latest.values()
                if v.get("side_effect_executed") and v.get("idempotency_key")}


__all__ = ["ApprovalGateStore"]
