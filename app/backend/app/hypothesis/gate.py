"""can_touch_final_oos 软闸门（T-017 / spine 04 §3.6）。

三个【结构性 BLOCK】（硬，诚信底线/防灾难，非研究旋钮）：探索层 / 未冻结 / OOS 已消费。
其余一律【软护栏】：产风险提示 + needs_human_review，**永不**自动 pass/fail。
裁决措辞只说「证据充分/不足 + 适用域 + 未验证项」，绝不说「可信/安全/保证」（R5/R7）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .card import HypothesisCard

_DISCLAIMER = (
    "本闸门为启发式、非统计确定性；honest-N 不可观测（只是下界），DSR 是标度修正非真理（R5）。"
    "本裁决只陈述证据充分/不足 + 适用域 + 未验证项，不对结论下定性判断。"
)


@dataclass
class GateDecision:
    allow: bool
    block_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    needs_human_review: bool = True
    disclaimer: str = _DISCLAIMER

    def to_dict(self) -> dict:
        return asdict(self)


def _block(reason: str) -> GateDecision:
    return GateDecision(allow=False, block_reason=reason, needs_human_review=True)


def can_touch_final_oos(card: HypothesisCard, honest_n_now: int | None = None) -> GateDecision:
    # —— 三结构性 BLOCK（硬）——
    if card.layer == "exploratory":
        return _block("探索层不得直接触碰最终 OOS；先晋级 confirmatory 重开冻结卡（P2 硬边界）")
    if card.status != "frozen":
        return _block("假设卡未冻结（缺只读+时间戳+content_hash），不得触碰最终 OOS")
    if card.frozen_oos and card.frozen_oos.get("consumed"):
        return _block("该 OOS 切片已被消费一次（R12 一次性消费，触碰留痕）")

    # —— 软护栏：产提示 + 要人工裁决，不自动 pass/fail ——
    warnings: list[str] = []
    mult = card.multiplicity or {}
    n_at_freeze = mult.get("honest_n_at_freeze")
    if honest_n_now is not None and n_at_freeze is not None and honest_n_now > n_at_freeze:
        warnings.append(
            f"冻结后 honest-N 又涨了（{n_at_freeze}→{honest_n_now}），卡层面 garden-of-forking-paths 风险，"
            "门槛应人工抬高"
        )
    fals = card.falsifiable or {}
    mech = fals.get("economic_mechanism") or {}
    if not mech.get("confounder_concerns"):
        warnings.append("未声明混杂担忧，因果信心降级")
    rev = card.review or {}
    if rev.get("verdict") == "concern":
        warnings.append("异模型一致性检查报 concern（非组织独立验证，仅一致性检查）")
    if card.needs_human_review:
        warnings.append("可证伪性启发式信心不足，已标人工复核")
    if card.frozen_oos and card.frozen_oos.get("regime_warning"):
        warnings.append(f"frozen_oos {card.frozen_oos['regime_warning']}（制度突变，代表性存疑）")

    return GateDecision(allow=True, warnings=warnings, needs_human_review=True)


__all__ = ["GateDecision", "can_touch_final_oos"]
