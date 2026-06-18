"""可证伪性启发式检测器（T-017 / spine 04 §3.7）—— 真语义检测，**非字数门**。

00 §2.1 点名：若启发式只查 min_length≥12，套套逻辑会漏过、退化成字数门。故四规则做真检测：
套套逻辑(判据=策略自身盈亏) / 无前置 X(缺"若X则") / 无可观测阈值(缺方向/数值) / 噪声(不连贯垃圾文本)。

诚实边界（R5）：本检测是启发式、非统计确定性；low/high 只反映「证据充分/不足」，绝不宣称
「可信/有效」。confidence=low → 不静默冻结（放行须人工复核 + 验证官二次挑战）。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# 策略【自身输出】当证伪判据 = 循环论证。复核 #1/#2/#14：不只是 P&L 动词，还含「净值/累计收益/
# 夏普/回撤/超额收益/因子失效」等自指标，以及英文表述（检测器不能是中文-only 字词门）。
_SELF_RESULT = (
    # 裸盈亏
    "不赚钱", "赚钱", "亏损", "不盈利", "不能盈利", "没有盈利", "收益为负", "跑不赢", "策略亏",
    "策略失败", "策略不成立", "没有收益", "表现不佳", "无法盈利", "不挣钱",
    # 策略自身权益/绩效指标（用它当判据 = 循环）
    "净值", "累计收益", "年化收益", "样本外收益", "策略收益", "回测收益", "收益曲线", "资金曲线",
    "夏普", "胜率", "回撤", "超额收益", "阿尔法", "因子失效", "信号失效", "策略夏普",
    # 英文（复核 #2：英文循环判据此前完全绕过）
    "makes money", "loses money", "is profitable", "not profitable", "unprofitable",
    "net asset value", "cumulative return", "equity curve", "sharpe", "drawdown",
    "the thesis is wrong", "thesis is wrong", "hypothesis is falsified", "validate the thesis",
    "validates the thesis", "returns will", "underperform", "excess return", "pnl",
)
# 可观测前置条件连接词（"若 X 则 …"）。
_ANTECEDENT = ("若", "如果", "当", "倘若", "一旦", "假如", " if ", "if ", " when ", "when ")
# 可观测方向/阈值（效应消失/反号/越过阈值）。CN + EN（复核 #3：英文阈值此前绕过）。
_THRESHOLD = ("消失", "反号", "转负", "转正", "下降", "上升", "低于", "高于", "超过", "小于",
              "大于", "不再", "失效", "收敛", "扩大", "缩小", "翻转", "归零",
              "disappear", "vanish", "exceed", "above", "below", "rise", "fall", "drop",
              "reverse", "flip", "converge", "widen", "narrow", "cease", "no longer", "goes to zero",
              "turns negative")
# 领域【独立】可观测变量小词典（驱动机制的外生量，非策略自身输出）。
_DOMAIN = ("利率", "资金费率", "成交量", "利差", "溢价", "流动性", "波动", "估值", "基差",
           "融券", "因子", "信号", "价差", "换手", "持仓", "情绪", "事件", "基本面", "宏观",
           "利好", "利空", "动量", "反转", "价值", "规模", "质量", "拥挤", "容量", "spread",
           "funding", "volume", "rate", "premium", "liquidity", "volatility", "valuation", "basis")


@dataclass
class FalsifiabilityVerdict:
    flags: list[tuple[str, str]]    # [(code, human_reason)]
    confidence: str                 # high | medium | low

    def to_dict(self) -> dict:
        return {"flags": [{"code": c, "reason": r} for c, r in self.flags], "confidence": self.confidence}


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(n.strip().lower() in t for n in needles)


def _has_threshold(fc: str) -> bool:
    return _has_any(fc, _THRESHOLD) or bool(re.search(r"\d", fc or "")) or "%" in (fc or "")


def _looks_gibberish(text: str) -> bool:
    """随机/乱码文本：含一长串无元音的拉丁辅音串（asdfghjkl 类键盘乱敲占位垃圾）。

    复核 low-note：把 'y' 当元音 + 阈值提到 7，避免误杀 rhythm 等真实无 aeiou 词。
    """

    for run in re.findall(r"[a-z]{7,}", (text or "").lower()):
        if not re.search(r"[aeiouy]", run):
            return True
    return False


def assess_falsifiability(triplet) -> FalsifiabilityVerdict:
    """triplet: strategy_goal.FalsifiableTriplet（或同形 dict）。"""

    fc = _get(triplet, "falsification_condition", "")

    flags: list[tuple[str, str]] = []

    # 规则1 套套逻辑（复核 #1/#2/#14）：判据用【策略自身输出】（盈亏/净值/夏普/回撤/超额收益/因子失效…）
    # 当证伪条件 = 循环论证。检测「自指」而非仅 P&L 动词，CN+EN 双语。
    if _has_any(fc, _SELF_RESULT):
        flags.append(("tautology", "证伪判据指向策略自身输出（净值/收益/夏普/回撤/因子失效…），循环论证、非独立可观测量"))

    # 规则2 无前置 X：缺「若 X 则…」的可观测前置条件。
    if not _has_any(fc, _ANTECEDENT):
        flags.append(("no_antecedent", "缺可观测前置条件 X（'若X则效应消失'的X缺失）"))

    # 规则3 无可观测阈值：缺方向/数值判据。
    if not _has_threshold(fc):
        flags.append(("no_threshold", "缺可观测阈值或方向（消失/反号/超过阈值/数值）"))

    # 规则4 噪声/不连贯（复核 #4）：乱码，或【falsification_condition 自身】未触及任何具体可观测量
    # （独立 domain 量 或 自指标）——不让机制的领域词「洗白」一个内容空洞的判据。
    fc_has_observable = _has_any(fc, _DOMAIN) or _has_any(fc, _SELF_RESULT)
    if _looks_gibberish(fc) or not fc_has_observable:
        flags.append(("noise", "证伪条件自身未触及任何具体可观测量或疑似随机文本，语义空洞/不连贯"))

    confidence = "high" if not flags else ("low" if len(flags) >= 2 else "medium")
    return FalsifiabilityVerdict(flags=flags, confidence=confidence)


def _get(obj, attr, default):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


__all__ = ["FalsifiabilityVerdict", "assess_falsifiability"]
