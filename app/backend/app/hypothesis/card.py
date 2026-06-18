"""可证伪假设卡 schema + content_hash + 冻结只读状态机（T-017 / spine 04 §3.3-3.5）。

content_hash 复用 `lineage.ids.content_hash`（canonical_json + NFC 归一 + sha256[:16]）——
键序/Unicode 不变量（00 §2.2 / T6b）天然由单一身份源保证，不另造哈希。
冻结后核心字段只读：改字段抛 CardFrozenError，必须 fork 开新卡（parent_card_id 指回）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from ..lineage.ids import content_hash as _content_hash

Layer = Literal["exploratory", "secondary", "confirmatory"]
Status = Literal["draft", "frozen", "deviated", "retired"]

# 冻结后只读的核心字段（改它们必须 fork）。deviations/review/status/frozen_at 是冻结后仍可演进的。
_FROZEN_READONLY = frozenset({
    "card_id", "strategy_goal_ref", "layer", "created_at_utc", "parent_card_id",
    "falsifiable", "frozen_oos", "multiplicity", "content_hash", "touched_versions",
})
# content_hash 排除字段（这些不进内容指纹：状态/时间戳/事后演进字段）。
_HASH_EXCLUDE = frozenset({"content_hash", "frozen_at_utc", "status", "deviations", "review", "needs_human_review"})


class CardFrozenError(Exception):
    """对已冻结卡的核心字段赋值——只读，必须 fork_card 开新卡。"""


class CardTamperError(Exception):
    """已冻结卡落盘内容被篡改：重算 content_hash 与存量不符（防自欺，非访问控制）。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class HypothesisCard:
    card_id: str
    strategy_goal_ref: str
    layer: Layer
    status: Status = "draft"
    created_at_utc: str = field(default_factory=_now)
    frozen_at_utc: str | None = None
    content_hash: str | None = None
    parent_card_id: str | None = None
    touched_versions: list[str] = field(default_factory=list)
    falsifiable: dict[str, Any] | None = None      # strategy_goal.FalsifiableTriplet.model_dump()
    frozen_oos: dict[str, Any] | None = None
    multiplicity: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    deviations: list[dict[str, Any]] = field(default_factory=list)
    needs_human_review: bool = False

    def __post_init__(self) -> None:
        # _frozen_core 一旦置真就【粘住】（复核 #6）：冻结后即便 status 转 deviated/retired，核心字段仍只读
        # ——deviation() 不能借「翻状态」重开 hashed 字段。重建时凡冻结过(status∈frozen/deviated/retired
        # 或已有 content_hash)即锁。
        sticky = self.status in ("frozen", "deviated", "retired") or self.content_hash is not None
        object.__setattr__(self, "_frozen_core", sticky)
        object.__setattr__(self, "_init_done", True)

    def __setattr__(self, name: str, value: Any) -> None:
        # 冻结只读门（T7/#6）：构造完成后、已冻结过(_frozen_core)时改核心字段 → CardFrozenError（改须 fork）。
        if getattr(self, "_init_done", False) and getattr(self, "_frozen_core", False) and name in _FROZEN_READONLY:
            raise CardFrozenError(f"卡已冻结，字段 {name!r} 只读；要改请 fork_card() 开新卡")
        super().__setattr__(name, value)
        if name == "status" and value == "frozen":
            object.__setattr__(self, "_frozen_core", True)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HypothesisCard":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def compute_content_hash(card: HypothesisCard) -> str:
    """冻结内容指纹（sha256[:16]，含 NFC 归一，复用 ids）。排除状态/时间戳/事后演进字段。"""

    payload = {k: v for k, v in card.to_dict().items() if k not in _HASH_EXCLUDE}
    return _content_hash(payload)


__all__ = ["CardFrozenError", "HypothesisCard", "Layer", "Status", "compute_content_hash"]
