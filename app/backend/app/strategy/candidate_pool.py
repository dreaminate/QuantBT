"""A4 · 策略台 → 模拟台 候选池（handoff 终点，止于模拟盘，绝不导向实盘）。

策略台 agent 跑到回测拍板即终点。`submit_candidate` 把候选策略写进候选池——
**destination 钉死 paper_desk（模拟盘）**，绝不导向直接实盘：

  · 治理红线（D-PERM / R8 不跳级）：候选池只接受 destination="paper_desk"；任何
    "live"/"mainnet"/"realmoney" 目的地一律拒绝（直推实盘=跳级=致命，§5）。
  · 进场与否、监控、动钱永远是模拟台/实盘安全阶梯的事，候选池只登记意图，不下单、不动钱。
  · 复用 experiments/store._JsonlStore（append-only + 崩溃容错 + 线程锁），不另造存储引擎。
  · candidate_id 内容寻址自单一身份源 lineage.ids.content_hash（不另造哈希族）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..experiments.store import _JsonlStore
from ..lineage.ids import content_hash

# 候选池唯一合法目的地——止于模拟盘。任何其它值（live/mainnet/realmoney）即跳级，硬拒。
_ALLOWED_DESTINATION = "paper_desk"
_FORBIDDEN_DESTINATIONS = {"live", "mainnet", "realmoney", "real", "production_trade"}


class HandoffRejected(Exception):
    """候选交接被拒（直推实盘/缺 run_id 等跳级/缺要件）——返回可读原因，不静默放行。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CandidatePoolStore:
    """模拟台候选池：策略台终点写入，模拟台读取。绝不下单/动钱/导向实盘。"""

    def __init__(self, root: Path | str) -> None:
        self._store = _JsonlStore(Path(root) / "strategy_candidates.jsonl")

    def submit(
        self,
        *,
        run_id: str,
        name: str,
        created_by: str,
        destination: str = _ALLOWED_DESTINATION,
        factor_set: str | None = None,
        model_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """登记一个候选策略到模拟台候选池（止于模拟盘）。

        治理硬门：
          · run_id 必填（不对幽灵 run 开候选）。
          · destination 必须是 paper_desk——任何实盘/动钱目的地（live/mainnet/realmoney/…）即跳级，硬拒。
        """

        if not run_id:
            raise HandoffRejected("候选交接必须绑 run_id（不对幽灵 run 开候选）")
        dest = (destination or "").strip().casefold()
        if dest in _FORBIDDEN_DESTINATIONS or dest != _ALLOWED_DESTINATION:
            raise HandoffRejected(
                f"候选交接只止于模拟盘（destination=paper_desk）；拒绝目的地 {destination!r}"
                "——策略台绝不导向直接实盘（D-PERM 不跳级，进场/动钱由模拟台与实盘安全阶梯决定）"
            )
        candidate_id = "cand_" + content_hash([run_id, name, created_by])[:10]
        record = {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "name": name,
            "created_by": created_by,
            "destination": _ALLOWED_DESTINATION,  # 钉死，不取调用方传值
            "factor_set": factor_set,
            "model_id": model_id,
            "note": note,
            "status": "candidate",               # 候选——非已进场、非动钱
            "stops_at": "paper_desk",
            "submitted_at_utc": _now(),
        }
        self._store.append(record)
        return record

    def list_candidates(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._store.read_all():
            latest[row["candidate_id"]] = row
        return list(latest.values())


__all__ = ["CandidatePoolStore", "HandoffRejected"]
