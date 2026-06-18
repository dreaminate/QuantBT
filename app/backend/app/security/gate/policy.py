"""确定性策略门 deny-by-default + 分级威胁模型（T-018 / spine 06，INV-2/INV-5）。

会话外、**agent 不可写**的规则引擎：限额/白名单/杠杆上限/最大回撤/提币默认禁。空白名单 = deny-all。
裁决措辞铁律（T17）：只说「证据充分/不足 + 适用域 + 未验证项」，绝不说「安全/可信/保证」；
并明示 TCB 天花板——单机本地门对属主仅为【防篡改证据】，非防篡改；唯一真硬墙在交易所侧。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...lineage.ids import content_hash as _content_hash

# 单机 TCB 诚实声明（T17：必须出现在裁决里，不撒「安全」谎）。
TCB_DISCLOSURE = (
    "单机本地门对属主仅为防篡改证据、非防篡改；唯一真硬墙在交易所侧远程信任域。"
    "通过本门 ≠ 防住自适应攻击——这本身是「高危只信交易所硬墙」的更强理由。"
)
_BANNED_WORDS = ("安全", "可信", "保证", "trustworthy", "guaranteed", "proven")


class TrustTier(str, Enum):
    PAPER = "paper"             # A股/加密 paper：无资金外流 → 门"防自欺"档
    CRYPTO_TESTNET = "testnet"  # 假钱 → 中档
    CRYPTO_LIVE = "crypto_live" # 真钱不可逆 → 最严档


def classify(asset_class: str, is_live: bool, reversibility: str = "irreversible") -> TrustTier:
    """R9：威胁等级 = f(asset_class, is_live, reversibility)。A股永不 live（永远 paper）。"""

    ac = (asset_class or "").lower()
    if "equity" in ac or "cn" in ac or "a_share" in ac or "ashare" in ac:
        return TrustTier.PAPER          # A股最多到 paper（MEMORY 项目范围硬约束）
    if not is_live:
        return TrustTier.PAPER if reversibility == "reversible" else TrustTier.CRYPTO_TESTNET
    return TrustTier.CRYPTO_LIVE


_TIER_RANK = {TrustTier.PAPER: 0, TrustTier.CRYPTO_TESTNET: 1, TrustTier.CRYPTO_LIVE: 2}


class PolicyGate(BaseModel):
    """会话外、不可变（frozen）的策略门。改门必须换实例 + 落审计。"""

    tier: TrustTier
    symbol_whitelist: frozenset[str] = frozenset()       # 空集 = deny-all（deny-by-default）
    max_notional_per_order_usdt: float = Field(0.0, ge=0)
    max_leverage: float = Field(1.0, ge=0)
    daily_turnover_cap: float = Field(0.0, ge=0)
    max_drawdown_halt: float = Field(0.30, ge=0)
    withdraw: Literal["deny"] = "deny"                    # 类型上不可设 allow（T3）
    require_dual_control_above_usdt: float | None = None
    require_validation_attestation: bool = False          # go_live 前置（INV-5，消费 R 账本）

    model_config = ConfigDict(frozen=True)


def gate_hash(gate: "PolicyGate") -> str:
    """冻结门的内容指纹（复核 #3）：capability.gate_ref 绑定它，防用旧/松门的 capability 取 key。"""

    payload = {
        "tier": gate.tier.value, "whitelist": sorted(gate.symbol_whitelist),
        "max_notional": gate.max_notional_per_order_usdt, "max_leverage": gate.max_leverage,
        "daily_turnover_cap": gate.daily_turnover_cap, "max_drawdown_halt": gate.max_drawdown_halt,
        "withdraw": gate.withdraw, "dual_above": gate.require_dual_control_above_usdt,
        "require_attestation": gate.require_validation_attestation,
    }
    return _content_hash(payload)


class PolicyDecision(BaseModel):
    allow: bool
    tier: TrustTier
    matched_rules: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    escalate_to_human: bool = False
    verdict_text: str = ""

    model_config = ConfigDict(frozen=True)


class OrderGated(Exception):
    """订单被策略门拦截——附 PolicyDecision，调用方不得继续取 key/下单。"""

    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__("; ".join(decision.violations) or "gated")
        self.decision = decision


# 资金外流动作（提币/划转）——allow-list 之外一律拒（复核 #10）。
_FUND_EGRESS = ("withdraw", "transfer", "提币", "划转", "transferout")
_ALLOWED_ACTIONS = ("request_live_order",)


def _order_notional(order: Any, tier: TrustTier, *, ref_price: float | None = None) -> float:
    """名义额（USDT）。**非 PAPER 只信 order.price 或【可信调用方显式入参 ref_price】，
    绝不信 order.extra（复核 #5/#7：extra 是 agent/信号侧不可信输入）**。

    `ref_price` 由可信边界（如 relay 从 venue 取的 mark）显式传入，用于 market 单（order.price=None）
    的名义额核验——市价单不改 order.price（venue 会把 price 发给交易所，市价单会被污染），故走独立通道。
    两者皆无 → 返 -1（不可核），实盘 deny-by-default 不放无法证伪名义额的单。
    """

    qty = abs(float(getattr(order, "quantity", 0) or 0))
    px = getattr(order, "price", None)
    extra = getattr(order, "extra", None) or {}
    if tier == TrustTier.PAPER:
        if isinstance(extra, dict) and extra.get("notional_usdt"):
            try:
                return abs(float(extra["notional_usdt"]))
            except (TypeError, ValueError):
                pass
        if px is None and isinstance(extra, dict):
            px = extra.get("ref_price") or extra.get("mark_price")
        if px is None:
            px = ref_price
        try:
            return abs(qty * float(px)) if px else 0.0
        except (TypeError, ValueError):
            return 0.0
    # 非 PAPER：认 order.price（撮合价）或可信 ref_price；都无 → 不可核（-1），实盘不放无法证伪的单。
    if px is None:
        px = ref_price
    try:
        return abs(qty * float(px)) if px is not None else -1.0
    except (TypeError, ValueError):
        return -1.0


def _verdict_text(allow: bool, tier: TrustTier, violations: list[str], escalate: bool) -> str:
    head = "证据充分：本单在该门各项约束内" if allow and not escalate else "证据不足：未满足放行约束"
    domain = f"适用域=该门档位({tier.value})/本单参数快照/本地策略门"
    unverified = "未验证=交易所侧实际撮合/对手方/自适应攻击/属主恶意（TCB 之外）"
    detail = ("命中拦截：" + "、".join(violations)) if violations else "无拦截项"
    esc = "；需人在环 + 验证官 attestation" if escalate else ""
    text = f"{head}（{detail}{esc}）。{domain}；{unverified}。{TCB_DISCLOSURE}"
    # 复核 low-note：运行时也守措辞（不只靠测试），未来改文案漂出黑名单即当场炸。
    assert not any(w in text for w in _BANNED_WORDS), f"verdict_text 含绝对化措辞: {text}"
    return text


def evaluate(
    gate: PolicyGate,
    order: Any,
    *,
    action: str = "request_live_order",
    attestation_ok: bool = False,
    daily_turnover_so_far: float = 0.0,
    drawdown_now: float = 0.0,
    ref_price: float | None = None,
) -> PolicyDecision:
    """deny-by-default 评估。任一违规 → allow=False。CRYPTO_LIVE 大额 → escalate。"""

    matched: list[str] = []
    violations: list[str] = []
    escalate = False
    is_live = gate.tier != TrustTier.PAPER

    # 资金外流 allow-list（复核 #10）：提币/划转 + action 不在白名单 → 一等 DENY（不只精确 'withdraw'）。
    norm_action = (action or "").strip().lower()
    ot = (getattr(order, "order_type", None) or "")
    if any(k in norm_action for k in _FUND_EGRESS) or any(k in str(ot).lower() for k in _FUND_EGRESS):
        violations.append("fund_egress_denied_by_default")
        return PolicyDecision(allow=False, tier=gate.tier, matched_rules=["withdraw=deny"],
                              violations=violations, escalate_to_human=False,
                              verdict_text=_verdict_text(False, gate.tier, violations, False))
    if norm_action not in _ALLOWED_ACTIONS:
        violations.append(f"action_not_allowed:{norm_action or 'empty'}")
        return PolicyDecision(allow=False, tier=gate.tier, matched_rules=[],
                              violations=violations, escalate_to_human=False,
                              verdict_text=_verdict_text(False, gate.tier, violations, False))

    symbol = getattr(order, "symbol", "")
    # 白名单 deny-by-default：空集 = 全拒。
    if symbol not in gate.symbol_whitelist:
        violations.append(f"symbol_not_whitelisted:{symbol}")
    else:
        matched.append("symbol_whitelist")

    # 杠杆上限（复核 #8）：非 PAPER 未声明 leverage → 违规（venue 会用账户默认杠杆，最高可达 125x）。
    lev = getattr(order, "leverage", None)
    if is_live and lev is None:
        violations.append("leverage_unspecified")
    elif lev is not None and float(lev) > gate.max_leverage:
        violations.append(f"max_leverage_exceeded:{lev}>{gate.max_leverage}")
    else:
        matched.append("max_leverage")

    # 单笔名义额上限（复核 #6/#17：非 PAPER 必须设正上限，0/未设 = 配置错 = deny，非「无限制」）。
    notional = _order_notional(order, gate.tier, ref_price=ref_price)
    if is_live and gate.max_notional_per_order_usdt <= 0:
        violations.append("notional_cap_unset")          # 实盘门没设名义上限 = deny-by-default
    elif notional < 0:
        violations.append("notional_unverifiable")        # 实盘无撮合价不可核 → 不放
    elif gate.max_notional_per_order_usdt > 0 and notional > gate.max_notional_per_order_usdt:
        violations.append(f"max_notional_exceeded:{notional:.0f}>{gate.max_notional_per_order_usdt:.0f}")
    else:
        matched.append("max_notional")

    # 日内换手上限（复核 #9：CRYPTO_LIVE 必须设正上限）。
    if gate.tier == TrustTier.CRYPTO_LIVE and gate.daily_turnover_cap <= 0:
        violations.append("turnover_cap_unset")
    elif gate.daily_turnover_cap > 0 and (daily_turnover_so_far + max(notional, 0)) > gate.daily_turnover_cap:
        violations.append("daily_turnover_cap_exceeded")

    # 最大回撤熔断。
    if abs(drawdown_now) > gate.max_drawdown_halt:
        violations.append(f"max_drawdown_halt:{abs(drawdown_now):.2f}>{gate.max_drawdown_halt:.2f}")

    # 升级到人在环：CRYPTO_LIVE 且超双控阈值，或门要求 attestation。
    needs_attestation = gate.require_validation_attestation or (
        gate.tier == TrustTier.CRYPTO_LIVE
        and gate.require_dual_control_above_usdt is not None
        and notional > gate.require_dual_control_above_usdt
    )
    if needs_attestation:
        escalate = True
        if not attestation_ok:
            violations.append("missing_attestation")

    allow = not violations
    return PolicyDecision(
        allow=allow, tier=gate.tier, matched_rules=matched, violations=violations,
        escalate_to_human=escalate, verdict_text=_verdict_text(allow, gate.tier, violations, escalate),
    )


__all__ = ["OrderGated", "PolicyDecision", "PolicyGate", "TCB_DISCLOSURE", "TrustTier",
           "classify", "evaluate", "gate_hash", "_BANNED_WORDS", "_TIER_RANK"]
