"""HypothesisCardStore（T-017 / spine 04 §3.1, §4.7）。

复用 `experiments/store.py:_JsonlStore`（append-only + 崩溃容错 + 线程锁）。冻结时：
强制三必填非空 + 过可证伪性启发式 + 读 honest-N 快照（**实读 T-013 一本账、不接受调用方传 N**）+
写一条 `kind="card_freeze"` 账本条目（让「卡的数量本身计入 N」）+ 发 PROV 事件。
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..experiments.store import _JsonlStore
from ..strategy_goal import FalsifiableTriplet
from .card import CardFrozenError, CardTamperError, HypothesisCard, compute_content_hash
from .falsifiability import assess_falsifiability
from .lineage_hook import LineageHook

# 默认显著性档（R3/P1：记录快照，可切换、不锁死）。
_DEFAULT_FLOOR = {"tier": "标准", "value": 3.0, "adjustable": True}


class FreezeRejected(Exception):
    """冻结被拒（三必填缺/不可证伪/验证官 blocked）——返回可读原因，非静默冻结。"""


class PromoteRejected(Exception):
    """探索→确认晋级被拒（OOS 探索污染）。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id() -> str:
    return f"card-{uuid.uuid4().hex[:12]}"


class HypothesisCardStore:
    def __init__(self, root: Path | str, *, lineage_hook: LineageHook | None = None) -> None:
        self._store = _JsonlStore(Path(root) / "hypothesis_cards.jsonl")
        self._lineage = lineage_hook or LineageHook()
        self._freeze_lock = threading.Lock()   # freeze 读-改-写原子性（T10b 并发双写）

    # ── 读 ──
    def get(self, card_id: str) -> HypothesisCard:
        latest: dict[str, Any] | None = None
        for row in self._store.read_all():       # latest-wins
            if row.get("card_id") == card_id:
                latest = row
        if latest is None:
            raise KeyError(f"假设卡不存在: {card_id}")
        card = HypothesisCard.from_dict(latest)
        # 复核 #7：冻结过的卡读路径上重算 content_hash 对账——被篡改(改了受哈希字段)即抓，不返脏数据。
        # content_hash 排除了 status/frozen_at/deviations/review，故 deviated/retired 卡仍能正确对账。
        if card.content_hash and card.status in ("frozen", "deviated", "retired"):
            if compute_content_hash(card) != card.content_hash:
                raise CardTamperError(
                    f"卡 {card_id} 落盘内容被篡改：重算 content_hash 与存量不符（防自欺，非访问控制）"
                )
        return card

    def list_cards(self, strategy_goal_ref: str | None = None) -> list[HypothesisCard]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._store.read_all():
            latest[row["card_id"]] = row
        cards = [HypothesisCard.from_dict(v) for v in latest.values()]
        if strategy_goal_ref is not None:
            cards = [c for c in cards if c.strategy_goal_ref == strategy_goal_ref]
        return cards

    # ── 写 ──
    def create(self, *, strategy_goal_ref: str, layer: str,
               falsifiable: dict[str, Any] | None = None,
               touched_versions: list[str] | None = None,
               parent_card_id: str | None = None) -> HypothesisCard:
        """建 draft 卡。P2：探索卡 falsifiable 可空，create 永不校验可证伪性。"""

        card = HypothesisCard(
            card_id=_gen_id(), strategy_goal_ref=strategy_goal_ref, layer=layer,  # type: ignore[arg-type]
            status="draft", falsifiable=falsifiable,
            touched_versions=list(touched_versions or []), parent_card_id=parent_card_id,
        )
        self._store.append(card.to_dict())
        return card

    def freeze(self, card_id: str, *, frozen_oos: dict[str, Any] | None = None,
               ledger=None, review: dict[str, Any] | None = None,
               human_reviewed: bool = False) -> HypothesisCard:
        """冻结 confirmatory 卡。强制门：三必填非空 + 可证伪性 + 验证官 + honest-N 实读。幂等。"""

        with self._freeze_lock:
            card = self.get(card_id)
            if card.status == "frozen":           # 幂等（T10）：返存量、不重跑、不重复计 N
                return card
            # 复核 #10：只有 confirmatory 可冻结（secondary/exploratory 都不可，否则 secondary 能过闸摸 OOS）。
            if card.layer != "confirmatory":
                raise FreezeRejected(f"只有 confirmatory 卡可冻结，本卡 layer={card.layer}；先 promote（P2）")
            # 复核 #15：confirmatory 冻结必须接真账本——否则 honest-N 静默为 0 却号称「实读自一本账」。
            if ledger is None:
                raise FreezeRejected("confirmatory 冻结必须接 T-013 一本账（honest-N 实读，不可缺）")
            # 复核 #11：必须绑非空 frozen_oos（含 dataset_version），否则 consumed BLOCK 形同虚设。
            if not (frozen_oos or {}).get("dataset_version"):
                raise FreezeRejected("confirmatory 冻结必须绑定 frozen_oos.dataset_version（一次性消费需有切片可盖戳）")
            # 复核 #9：冻结绑的 OOS 切片不得是源卡探索期碰过的（防 promote 后 freeze 重绑污染数据）。
            polluted = self._ancestor_touched_versions(card)
            if (frozen_oos or {}).get("dataset_version") in polluted:
                raise FreezeRejected(
                    f"探索污染：frozen_oos 切片 {frozen_oos['dataset_version']} 已被源卡链触碰过，不得作确认 OOS"
                )
            if not card.falsifiable:
                raise FreezeRejected("三必填缺失（economic_mechanism/falsification_condition/stop_rule）")
            # 校验三必填非空 + 过短（min_length）——空白串/全空格在此被 pydantic 拒。
            try:
                triplet = FalsifiableTriplet(**card.falsifiable)
            except Exception as exc:  # noqa: BLE001
                raise FreezeRejected(f"三必填非法/过短（装样子不算填）：{exc}") from exc
            # 可证伪性启发式（真检测非字数门）。
            fv = assess_falsifiability(triplet)
            if fv.confidence == "low" and not human_reviewed:
                raise FreezeRejected(
                    f"可证伪性证据不足(confidence=low)：{[c for c, _ in fv.flags]}；不静默冻结，需人工复核 + 验证官二次挑战"
                )
            # 复核 #1：裁决须是针对【本卡】产的（verdict.target_ref==card_id），不得拿无关裁决冒名顶替。
            # 向后兼容：不带 target_ref 的手工 review 不受影响；真验证官 to_review() 总带 target_ref。
            if review and review.get("target_ref") and review.get("target_ref") != card.card_id:
                raise FreezeRejected(
                    f"验证官裁决张冠李戴：review.target_ref={review.get('target_ref')} ≠ 本卡 {card.card_id}"
                )
            if review and review.get("verdict") == "blocked":
                raise FreezeRejected(f"异模型一致性检查 blocked：{review.get('notes', '')}")

            # honest-N 实读（T5 命门）：从 T-013 一本账读，**绝不接受调用方传入的 N**。
            honest_n = 0
            ledger_ref = None
            config_cluster = ""
            if ledger is not None:
                from ..lineage.ledger import LedgerEntry
                entry = LedgerEntry.create(
                    factor=card.card_id, params={}, universe="card",
                    dataset_version=(frozen_oos or {}).get("dataset_version", "unknown"),
                    freq="card_freeze", label="card",
                    strategy_goal_ref=card.strategy_goal_ref, kind="card_freeze", stage="confirmatory",
                )
                rec, _ = ledger.record_or_hit(entry)
                ledger_ref = rec.entry_id
                config_cluster = rec.config_hash
                honest_n = ledger.honest_n(card.strategy_goal_ref)   # 含本卡，实读

            # 复核 #5：low（即便人工放行）也保留 needs_human_review，不静音可证伪性不足的告警。
            needs_review = (fv.confidence in {"low", "medium"}) or bool(review and review.get("verdict") == "concern")

            # 先设非状态字段（status 仍 draft，只读门未生效），content_hash 最后算，status 最后翻。
            card.frozen_oos = frozen_oos
            card.review = review
            card.needs_human_review = needs_review
            card.multiplicity = {
                "honest_n_at_freeze": honest_n,
                "config_hash_cluster": config_cluster,
                "ledger_ref": ledger_ref,
                "significance_floor": dict(_DEFAULT_FLOOR),
                "n_cluster_note": "honest_n 实读自 T-013 一本账（card_freeze 条目计入）；真值下界，不可改小",
                "falsifiability": fv.to_dict(),
            }
            card.frozen_at_utc = _now()
            card.content_hash = compute_content_hash(card)
            card.status = "frozen"               # 翻状态最后做 → 之后核心字段只读
            self._store.append(card.to_dict())
            self._lineage.emit(card, "freeze")
            return card

    def _ancestor_touched_versions(self, card: HypothesisCard) -> set[str]:
        """沿 parent_card_id 链收集所有探索期碰过的 dataset_version（复核 #9：freeze 防重绑污染）。"""

        seen: set[str] = set(card.touched_versions or [])
        cur = card.parent_card_id
        guard = 0
        while cur and guard < 64:
            guard += 1
            try:
                p = self.get(cur)
            except KeyError:
                break
            seen.update(p.touched_versions or [])
            cur = p.parent_card_id
        return seen

    def retire(self, card_id: str, reason: str = "") -> HypothesisCard:
        """退役卡（stop_rule 触发 / 用户归档）。append + 发 PROV 事件（复核 low-note：原本未实现）。"""

        card = self.get(card_id)
        card.status = "retired"
        if reason:
            card.deviations = [*card.deviations, {"retire_reason": reason, "when": _now()}]
        self._store.append(card.to_dict())
        self._lineage.emit(card, "retire")
        return card

    def fork_card(self, card_id: str) -> HypothesisCard:
        """开新 draft 卡（parent_card_id 指回）——改已冻结卡的唯一合法途径。"""

        src = self.get(card_id)
        fork = HypothesisCard(
            card_id=_gen_id(), strategy_goal_ref=src.strategy_goal_ref, layer=src.layer,
            status="draft", falsifiable=src.falsifiable, parent_card_id=src.card_id,
            touched_versions=list(src.touched_versions),
        )
        self._store.append(fork.to_dict())
        return fork

    def promote_to_confirmatory(self, source_card_id: str, fresh_dataset_version: str) -> HypothesisCard:
        """探索→确认晋级：校验新 OOS 切片【未被源卡触碰过】（T3 防探索污染）。"""

        src = self.get(source_card_id)
        if fresh_dataset_version in (src.touched_versions or []):
            raise PromoteRejected(
                f"探索污染：新 OOS 切片 {fresh_dataset_version} 已被源卡 {source_card_id} 触碰过，不得作为确认 OOS"
            )
        card = HypothesisCard(
            card_id=_gen_id(), strategy_goal_ref=src.strategy_goal_ref, layer="confirmatory",
            status="draft", falsifiable=src.falsifiable, parent_card_id=src.card_id,
        )
        self._store.append(card.to_dict())
        self._lineage.emit(card, "promote")
        return card

    def deviation(self, card_id: str, deviation: dict[str, Any]) -> HypothesisCard:
        """提交偏离：append + 自动降级标记 + 发 PROV 事件（deviations 非只读字段）。"""

        card = self.get(card_id)
        card.deviations = [*card.deviations, {**deviation, "when": _now()}]
        card.status = "deviated"
        self._store.append(card.to_dict())
        self._lineage.emit(card, "deviate")
        return card


__all__ = ["FreezeRejected", "HypothesisCardStore", "PromoteRejected"]
