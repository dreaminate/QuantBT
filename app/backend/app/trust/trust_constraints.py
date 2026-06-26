"""§13 信任层硬约束门 —— 诚实硬约束 + waiver-safety 边界(命门) + 反谄媚 + 弱点一等呈现（greenfield）。

QuantBT §13 的目标是【恰当依赖】(R24)，不是信任最大化。本门把 GOAL §13 的诚实契约落成可核查的硬门，
并【收编只读·不重造】已建件：方法学控制面（`methodology.constrain_promotion`）、一致性门
（`spine_gate.evaluate_promotion`）、发版 mock 诚实（`release_gate.mock_honesty`）。本卡的【增量】是四块：

  ① 诚实硬约束门（check_honesty_constraints）
     不得伪造 proof_backed / evidence_sufficient / production_ready（声明须有【已建证据门】裁定背书·
     本层不另写一致性判定）；不得让理论↔实现不一致冒充一致；单人模式不得声明组织独立。
  ② waiver-safety 边界门 = 命门（evaluate_waiver_safety / assert_safety_invariants_intact）
     **不得让 secret / OrderGuard / kill switch / no-silent-mock 被 waiver 绕过**。user 可为研究松紧
     自负其责（研究自由），但安全不变量不在可弃权域——任何弃权目标触及它们 → 拒（fail-closed·撞即停）。
  ③ 反谄媚门（check_anti_sycophancy）
     Agent 遇稳赢 / 越级实盘 / 忽略成本 / 忽略 N / 忽略泄露 → 不顺从 user wishful thinking 输出强结论，
     而是给【缺口 + 证据要求 + 下一步验证动作】，把结论诚实降级（R26 专业知识优先·非安全可 override）。
  ④ 弱点一等呈现门（check_weakness_disclosure）
     风险 / 缺口 / 弱点默认可见、绝不淡化隐藏（R25）；user waiver 不得被隐藏。

诚实纪律（RULES §3 · 北极星 correctness）：
- 强标签真假【委派】已建证据门裁定（reuse 不 recreate）：本层只核「声明 ↔ 门裁定是否一致」。
- 安全不变量【真拒】(raise SafetyWaiverError)，绝不静默降级成 soft ok=False（命门不可商量）。
- 反谄媚是「裁定非拦截存在」：它把越权强结论降级到诚实强度 + 出缺口，**不**硬拦用户在可证伪经济
  事项上自负其责推进（D-T024「硬透明 + 软决定」/ R26 可 override）；安全侧才硬拦。
- 裁决口径自检（假绿灯反噬自身）：本门 verdict_text 绝不出现越权正向断言（见 `_BANNED_POSITIVE_TERMS`）。

诚实限界（不号称做到的）：本门核查【声明的治理工件 + 声明姿态】是否自洽，**不**自行证明数学命题、
**不**识破谎报姿态的执行块（如把真 mock 谎报成 live —— 那是 mock_honesty 模块的同款诚实限界）、
**不**接 main.py 编排（greenfield 后端门·接线是中心/下游另卡·诚实残余）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..lineage.spine import STRONG_LABELS, MethodologyChoiceRecord
from ..lineage.spine_gate import SpineDecision
from ..methodology.control_plane import MethodologyDecision
from .responsibility import ResponsibilityDisclosureRecord

__all__ = [
    # 安全不变量 / 命门
    "INV_SECRET",
    "INV_ORDER_GUARD",
    "INV_KILL_SWITCH",
    "INV_NO_SILENT_MOCK",
    "SAFETY_INVARIANTS",
    "map_target_to_safety_invariant",
    "WaiverRequest",
    "WaiverSafetyDecision",
    "SafetyWaiverError",
    "collect_waived_targets",
    "evaluate_waiver_safety",
    "assert_safety_invariants_intact",
    # 反谄媚
    "STRENGTH_STRONG",
    "STRENGTH_TENTATIVE",
    "STRENGTH_EXPLORATORY",
    "CONCLUSION_STRENGTHS",
    "AgentConclusion",
    "AntiSycophancyDecision",
    "check_anti_sycophancy",
    # 弱点披露
    "DisclosureManifest",
    # 诚实硬约束
    "TrustClaim",
    # 通用裁定结构
    "TrustViolation",
    "TrustDecision",
    "TrustValidation",
    "TrustRejected",
    # 违规码
    "FAKE_STRONG_LABEL",
    "FAKE_CONSISTENCY",
    "FAKE_ORG_INDEPENDENCE",
    "WEAKNESS_HIDDEN",
    "WAIVER_HIDDEN",
    "AGENT_DECIDED_FOR_USER",
    "MISSING_RESPONSIBILITY",
    "INCOMPLETE_RESPONSIBILITY",
    "SAFETY_WAIVER_BYPASS",
    "SYCOPHANTIC_STRONG_CONCLUSION",
    # 子门
    "check_honesty_constraints",
    "check_weakness_disclosure",
    "check_user_autonomy",
    "check_responsibility",
    "gate_waiver_safety",
    "gate_anti_sycophancy",
    # 聚合
    "TrustContext",
    "evaluate_trust",
    "require_trustworthy",
]


# ════════════════════════════════════════════════════════════════════════════
# 裁决口径自检（假绿灯反噬自身 · 同 spine_gate.BANNED_POSITIVE_TERMS / policy._BANNED_WORDS 范式）
# ════════════════════════════════════════════════════════════════════════════
# 越权正向断言：本门拒/放裁决里都绝不能出现（label token / 安全不变量名允许被【命名】，
# 但「已证明 / 证据充分 / 保证 / 可信 / proven ...」这类正向断言禁止——那是我们自己打假绿灯）。
_BANNED_POSITIVE_TERMS = (
    "已证明",
    "证据充分",
    "evidence 充分",
    "保证",
    "可信",
    "trustworthy",
    "guaranteed",
    "proven",
    "production-ready 达成",
)


def _assert_no_banned_positive(text: str) -> None:
    for term in _BANNED_POSITIVE_TERMS:
        if term in text:
            raise AssertionError(
                f"trust 门自检失败：裁决口径出现越权正向断言 {term!r}（= 我们自己打了假绿灯）"
            )


# ════════════════════════════════════════════════════════════════════════════
# 通用裁定结构（镜像 release_gate.ReleaseGateOutcome / ReleaseValidation · 账面一致）
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TrustViolation:
    """信任层一条违规（违规码 + 诚实说明）。测试据 `code` 精确断言抓到哪条门·非泛绿。"""

    code: str
    reason: str


@dataclass(frozen=True)
class TrustDecision:
    """一条信任层子门的裁定（`passed=False` + `violations` 列违规 + `notes` 软披露 + 诚实 verdict）。"""

    gate_id: str
    passed: bool
    violations: tuple[TrustViolation, ...] = ()
    notes: tuple[str, ...] = ()
    verdict_text: str = ""

    @property
    def violation_codes(self) -> tuple[str, ...]:
        return tuple(v.code for v in self.violations)

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "violations": [{"code": v.code, "reason": v.reason} for v in self.violations],
            "notes": list(self.notes),
            "verdict_text": self.verdict_text,
        }


# 违规码（投影/测试据此精确断言）。
FAKE_STRONG_LABEL = "fake_strong_label"
FAKE_CONSISTENCY = "fake_theory_impl_consistency"
FAKE_ORG_INDEPENDENCE = "fake_org_independence"
WEAKNESS_HIDDEN = "weakness_hidden"
WAIVER_HIDDEN = "user_waiver_hidden"
AGENT_DECIDED_FOR_USER = "agent_decided_for_user"
MISSING_RESPONSIBILITY = "missing_responsibility_disclosure"
INCOMPLETE_RESPONSIBILITY = "incomplete_responsibility_disclosure"
SAFETY_WAIVER_BYPASS = "safety_invariant_waiver_bypass"
SYCOPHANTIC_STRONG_CONCLUSION = "sycophantic_strong_conclusion"


# ════════════════════════════════════════════════════════════════════════════
# ② waiver-safety 边界门 = 命门：安全不变量不在可弃权域
# ════════════════════════════════════════════════════════════════════════════
# 四个不可弃权的安全不变量（§13「不得让 secret / OrderGuard / kill switch / no-silent-mock 被 waiver 绕过」）。
INV_SECRET = "secret"               # 实盘 key/secret 不进 LLM·不明文落库/日志（security.keystore / LLM Gateway 门2）
INV_ORDER_GUARD = "order_guard"     # 所有执行路径必经 OrderGuard·下单唯一入口·提币 deny-by-default（security.gate）
INV_KILL_SWITCH = "kill_switch"     # 紧急平仓/回撤熔断/急停（trading.safety / policy max_drawdown_halt）
INV_NO_SILENT_MOCK = "no_silent_mock"  # 生产结果不走 silent mock fallback·template 不冒充生产成功（release_gate.mock_honesty）

SAFETY_INVARIANTS: frozenset[str] = frozenset(
    {INV_SECRET, INV_ORDER_GUARD, INV_KILL_SWITCH, INV_NO_SILENT_MOCK}
)

# 自由文本弃权目标 → 安全不变量 的别名表（substring·小写·中英）。
# fail-closed 取向：宁可把模糊目标判成「触及安全不变量 → 拒」，也绝不放过真绕过。刻意【不】收录
# 裸 "key"（太宽·会误伤 "key metrics"），只收明确指向 secret/凭据的串。
_SAFETY_ALIASES: tuple[tuple[str, str], ...] = (
    # secret / 凭据：实盘 key 不进 LLM·不明文落库
    ("secret", INV_SECRET),
    ("api key", INV_SECRET),
    ("api_key", INV_SECRET),
    ("apikey", INV_SECRET),
    ("密钥", INV_SECRET),
    ("私钥", INV_SECRET),
    ("key 进 llm", INV_SECRET),
    ("key进llm", INV_SECRET),
    ("keystore", INV_SECRET),
    ("凭据", INV_SECRET),
    ("credential", INV_SECRET),
    # OrderGuard / 下单唯一入口 / 资金外流 deny-by-default
    ("orderguard", INV_ORDER_GUARD),
    ("order_guard", INV_ORDER_GUARD),
    ("order guard", INV_ORDER_GUARD),
    ("下单门", INV_ORDER_GUARD),
    ("下单唯一入口", INV_ORDER_GUARD),
    ("place_order", INV_ORDER_GUARD),
    ("place order", INV_ORDER_GUARD),
    ("策略门", INV_ORDER_GUARD),
    ("policy gate", INV_ORDER_GUARD),
    ("杠杆护栏", INV_ORDER_GUARD),
    ("防重放", INV_ORDER_GUARD),
    ("hmac", INV_ORDER_GUARD),
    ("nonce", INV_ORDER_GUARD),
    ("提币", INV_ORDER_GUARD),
    ("划转", INV_ORDER_GUARD),
    ("withdraw", INV_ORDER_GUARD),
    ("transfer", INV_ORDER_GUARD),
    # kill switch / 熔断 / 紧急平仓 / 急停
    ("kill switch", INV_KILL_SWITCH),
    ("kill_switch", INV_KILL_SWITCH),
    ("killswitch", INV_KILL_SWITCH),
    ("熔断", INV_KILL_SWITCH),
    ("急停", INV_KILL_SWITCH),
    ("紧急平仓", INV_KILL_SWITCH),
    ("回撤熔断", INV_KILL_SWITCH),
    ("max_drawdown_halt", INV_KILL_SWITCH),
    ("emergency", INV_KILL_SWITCH),
    ("halt", INV_KILL_SWITCH),
    # no-silent-mock / 生产结果不走 mock fallback / template 不冒充生产成功
    ("no-silent-mock", INV_NO_SILENT_MOCK),
    ("no_silent_mock", INV_NO_SILENT_MOCK),
    ("silent mock", INV_NO_SILENT_MOCK),
    ("silent_mock", INV_NO_SILENT_MOCK),
    ("mock fallback", INV_NO_SILENT_MOCK),
    ("mock_fallback", INV_NO_SILENT_MOCK),
    ("silent fallback", INV_NO_SILENT_MOCK),
    ("假成功", INV_NO_SILENT_MOCK),
    ("冒充生产", INV_NO_SILENT_MOCK),
    ("template false success", INV_NO_SILENT_MOCK),
    ("mock 诚实", INV_NO_SILENT_MOCK),
)

WAIVER_SAFETY_DISCLOSURE = (
    "waiver-safety 边界门把弃权目标映射到安全不变量(secret/OrderGuard/kill switch/no-silent-mock)；"
    "命中即拒（命门·fail-closed）。它**只**裁『弃权能不能绕安全不变量』，不替各安全门做运行时强制——"
    "真硬墙在各自模块（security.gate / keystore / trading.safety / release_gate.mock_honesty）。"
)


def map_target_to_safety_invariant(target: str) -> str | None:
    """把一个自由文本弃权目标映射到安全不变量名（命中返不变量名·否则 None）。

    匹配：先看是否就是不变量名，再 substring 扫别名表（小写）。fail-closed：模糊命中也算触及。
    """

    if not isinstance(target, str):
        return None
    t = target.strip().lower()
    if not t:
        return None
    if t in SAFETY_INVARIANTS:
        return t
    for kw, inv in _SAFETY_ALIASES:
        if kw in t:
            return inv
    return None


@dataclass(frozen=True)
class WaiverRequest:
    """一条 user/agent 发起的弃权/放宽请求：声明要跳过/放宽哪些目标（步骤名 / 标的 / 口径）。

    `waived_targets` 是自由文本目标集（如「部分稳健性门放宽」/「关掉 kill switch」/「secret 注入 LLM 调试」）。
    安全门把每个目标映射到安全不变量；命中任一 → 该目标【拒】（命门·不可弃权）；其余非安全目标可放宽
    （研究自由）。`actor` 须 user（弃权【决定】不能由 agent 替拍）；`asset_ref`/`rationale` 留痕。
    """

    waived_targets: tuple[str, ...] = ()
    actor: str = "user"
    rationale: str = ""
    asset_ref: str = ""


@dataclass(frozen=True)
class WaiverSafetyDecision:
    """waiver-safety 边界门裁定。`bypass_attempted=True` 即有目标触及安全不变量（命门触发）。"""

    bypass_attempted: bool
    refused_safety_targets: tuple[tuple[str, str], ...]  # (原始 target, 命中的安全不变量)
    permitted_targets: tuple[str, ...]                   # 非安全目标（合法放宽·研究自由）
    verdict_text: str
    disclosure: str = WAIVER_SAFETY_DISCLOSURE

    @property
    def ok(self) -> bool:
        return not self.bypass_attempted


class SafetyWaiverError(Exception):
    """弃权请求试图绕过安全不变量（§13 命门·撞即停工报告）——携带结构化 `decision`。"""

    def __init__(self, decision: WaiverSafetyDecision) -> None:
        self.decision = decision
        super().__init__(decision.verdict_text)


def collect_waived_targets(
    *,
    waiver: WaiverRequest | None = None,
    methodology_choice: MethodologyChoiceRecord | None = None,
    extra_targets: Sequence[str] = (),
) -> tuple[str, ...]:
    """聚合一次操作【所有】弃权目标：WaiverRequest + MethodologyChoiceRecord.skipped_steps + 额外目标。

    刻意把方法学放权的 `skipped_steps` 也纳入扫描 —— 防「借方法学放宽之名、把安全不变量塞进 skipped_steps
    偷渡」。复用既建的 MethodologyChoiceRecord（不另造），只在其上叠加安全边界检查。
    """

    targets: list[str] = []
    if waiver is not None:
        targets.extend(waiver.waived_targets)
    if methodology_choice is not None:
        targets.extend(methodology_choice.skipped_steps)
    targets.extend(extra_targets)
    return tuple(targets)


def evaluate_waiver_safety(targets: Sequence[str]) -> WaiverSafetyDecision:
    """裁定一组弃权目标是否触及安全不变量（结构化·不抛）。供披露「哪些拒/哪些可放宽」。"""

    refused: list[tuple[str, str]] = []
    permitted: list[str] = []
    for t in targets:
        inv = map_target_to_safety_invariant(t)
        if inv is not None:
            refused.append((t, inv))
        else:
            permitted.append(t)

    if refused:
        names = "；".join(f"『{t}』→{inv}" for t, inv in refused)
        verdict = (
            f"waiver-safety 边界门拒绝：弃权请求触及安全不变量（{names}）。"
            "安全不变量(secret/OrderGuard/kill switch/no-silent-mock)不在可弃权域（§13 命门）——"
            "user 可为研究松紧自负其责，但绝不能凭 waiver 绕过安全不变量。"
            f"其余 {len(permitted)} 项非安全目标可放宽（属研究松紧域）。"
        )
    else:
        verdict = (
            f"waiver-safety 边界门放行：{len(permitted)} 项弃权目标均未触及安全不变量"
            "（属研究松紧 / 方法学放宽域·研究自由）。安全不变量保持强制。"
        )
    _assert_no_banned_positive(verdict)
    return WaiverSafetyDecision(
        bypass_attempted=bool(refused),
        refused_safety_targets=tuple(refused),
        permitted_targets=tuple(permitted),
        verdict_text=verdict,
    )


def assert_safety_invariants_intact(targets: Sequence[str]) -> None:
    """命门硬路径（fail-closed·撞即停工报告）：任一弃权目标触及安全不变量 → raise SafetyWaiverError。

    这是「安全不变量绝不可被 waiver 绕过」的不可商量入口：调用方在接受任何 waiver/放权前调它一脚。
    """

    decision = evaluate_waiver_safety(targets)
    if decision.bypass_attempted:
        raise SafetyWaiverError(decision)


def gate_waiver_safety(targets: Sequence[str]) -> TrustDecision:
    """把 waiver-safety 裁定包成统一 TrustDecision（供聚合·与其它子门同账面）。"""

    decision = evaluate_waiver_safety(targets)
    violations = tuple(
        TrustViolation(
            SAFETY_WAIVER_BYPASS,
            f"弃权目标『{t}』触及安全不变量 {inv} → 拒（§13 命门·安全不变量不可 waiver）",
        )
        for t, inv in decision.refused_safety_targets
    )
    return TrustDecision(
        gate_id="waiver_safety",
        passed=decision.ok,
        violations=violations,
        verdict_text=decision.verdict_text,
    )


# ════════════════════════════════════════════════════════════════════════════
# ③ 反谄媚门：不顺从 user wishful thinking 输出强结论
# ════════════════════════════════════════════════════════════════════════════
STRENGTH_STRONG = "strong"
STRENGTH_TENTATIVE = "tentative"
STRENGTH_EXPLORATORY = "exploratory"
CONCLUSION_STRENGTHS = frozenset({STRENGTH_STRONG, STRENGTH_TENTATIVE, STRENGTH_EXPLORATORY})

ANTI_SYC_DISCLOSURE = (
    "反谄媚门是『裁定非拦截』：它把越权强结论降级到诚实强度 + 给缺口/证据要求/下一步，"
    "**不**硬拦 user 在可证伪经济事项上自负其责推进（R26 专业知识优先·可 override）；"
    "安全侧（越级实盘触执行红线）才硬拦。它不替 user 拍方法学/风险选择。"
)


@dataclass(frozen=True)
class AgentConclusion:
    """Agent 拟输出的一条结论 + 它真实的证据姿态（反谄媚门据此判越权强结论）。

    `strength`：agent 想给的强度（strong 须无谄媚缺口）。诚实姿态布尔：`cost_modeled`(计成本/TCA)、
    `leakage_checked`(查 look-ahead 泄露)、`multiple_testing_controlled`(控多重检验)。
    `sample_n`：支撑样本（None=未追踪；≤1=冷启动 N=1）。`claims_sure_win`(声称稳赢/包赚)、
    `proposes_live_escalation`(提议越级实盘) + `staged_validation_done`(实盘前阶梯验证是否做完)。
    `user_pressure`：user wishful-thinking 施压文本（留痕·门对它【对称】不松口）。
    """

    text: str = ""
    strength: str = STRENGTH_STRONG
    claims_sure_win: bool = False
    proposes_live_escalation: bool = False
    staged_validation_done: bool = False
    sample_n: int | None = None
    cost_modeled: bool = False
    leakage_checked: bool = False
    multiple_testing_controlled: bool = False
    user_pressure: str = ""

    def __post_init__(self) -> None:
        if self.strength not in CONCLUSION_STRENGTHS:
            raise ValueError(
                f"strength 非法：{self.strength!r} ∉ {sorted(CONCLUSION_STRENGTHS)}"
            )

    @property
    def is_strong(self) -> bool:
        return self.strength == STRENGTH_STRONG


@dataclass(frozen=True)
class AntiSycophancyDecision:
    """反谄媚裁定：把越权强结论降到 `permitted_strength` + 出缺口/证据要求/下一步。

    `refused_strong_conclusion`：是否拦下了「带谄媚缺口的强结论」。`sure_win_refused`：是否剥掉了
    稳赢/包赚断言。`refused_live_escalation`：是否拦下了「缺阶梯验证的越级实盘」（执行侧红线·硬拦）。
    `ok=False` 即「有谄媚越权被拦」（= §13『顺从 wishful thinking 输出强结论/越级实盘 → 拒』兑现）。
    """

    permitted_strength: str
    permit_sure_win: bool
    refused_strong_conclusion: bool
    sure_win_refused: bool
    refused_live_escalation: bool
    gaps: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    next_steps: tuple[str, ...]
    verdict_text: str
    disclosure: str = ANTI_SYC_DISCLOSURE

    @property
    def ok(self) -> bool:
        return not (
            self.refused_strong_conclusion
            or self.sure_win_refused
            or self.refused_live_escalation
        )


def check_anti_sycophancy(c: AgentConclusion) -> AntiSycophancyDecision:
    """反谄媚核查：稳赢 / 越级实盘 / 忽略成本 / 忽略 N / 忽略泄露 → 不输出强结论，给缺口+证据+下一步。

    设计要点：
    - 稳赢/包赚断言任何强度都剥掉（市场收益不确定·可证伪经济错觉·R26 不背书）。
    - 强结论(strong)若带任一缺口（无成本/无泄露查/N 未知/N≤1 冷启动/未控多重检验）→ 降级到 tentative。
    - 越级实盘缺阶梯验证 → 出缺口（且触执行侧·须安全门放行；A股永不实盘）。
    - 门对 `user_pressure` 对称：user 越想要强结论，缺口在场就越要降级——不顺从。
    - 不替 user 拍：只降级 agent 的【输出强度】，非安全事项 user 仍可自负其责推进（R26 可 override）。
    """

    gaps: list[str] = []
    evidence: list[str] = []
    next_steps: list[str] = []

    if c.claims_sure_win:
        gaps.append("声称稳赢/包赚——市场收益不确定，『稳赢』是可证伪的经济错觉")
        evidence.append("把主张改述成可证伪假设：样本外 + 成本/TCA 后净收益分布 + 最大回撤/破产风险")
        next_steps.append("撤下『稳赢』表述，按可证伪假设跑样本外 + 成本后验证再谈强度")

    refused_live = c.proposes_live_escalation and not c.staged_validation_done
    if refused_live:
        gaps.append("提议越级实盘——未完成 paper→testnet→小额 live 阶梯验证")
        evidence.append("分阶段验证账齐 + 执行侧安全门(OrderGuard/policy gate)放行")
        next_steps.append("回到当前阶梯跑满、安全门核过再谈实盘；A股永不实盘")

    if c.is_strong and not c.cost_modeled:
        gaps.append("强结论但未计成本/TCA——成本可吃掉表面 alpha")
        evidence.append("成本/TCA/容量扣减后的净收益")
        next_steps.append("加成本模型重估，确认成本扣减后仍成立再谈强度")

    if c.is_strong and not c.leakage_checked:
        gaps.append("强结论但未查 look-ahead/泄露——泄露会虚高样本内表现")
        evidence.append("PIT / purge / embargo 泄露检查通过")
        next_steps.append("过泄露检查再谈强度")

    if c.is_strong:
        if c.sample_n is None:
            gaps.append("强结论但样本 N 未追踪——N 未知不能出强结论")
            evidence.append("登记 honest-N + 多重检验账")
            next_steps.append("先追踪 N 与多重检验，再谈强度")
        elif c.sample_n <= 1:
            gaps.append(
                f"强结论但 N={c.sample_n}（冷启动）——N=1 是先验断言/未验证结果，不得包装成统计证据"
            )
            evidence.append("按 R27 标『先验断言未经数据检验』；要统计证据须积累样本(PSR/MinTRL)")
            next_steps.append("标先验断言、不冒充统计证据；积累样本后再谈强度")
        elif not c.multiple_testing_controlled:
            gaps.append("强结论但未控多重检验——挑出来的『最佳』可能是多重检验假阳")
            evidence.append("多重检验账(PBO/DSR 等)扣减后仍显著")
            next_steps.append("过多重检验账再谈强度")

    refused_strong = c.is_strong and bool(gaps)
    sure_win_refused = c.claims_sure_win
    permitted_strength = STRENGTH_TENTATIVE if refused_strong else c.strength

    if refused_strong or sure_win_refused or refused_live:
        verdict = (
            f"反谄媚门拒绝越权结论：检出 {len(gaps)} 处缺口"
            f"（{'；'.join(gaps)}）。不顺从 user wishful thinking——"
            f"降级到诚实强度『{permitted_strength}』、剥离稳赢断言/越级实盘，并给出证据要求与下一步验证动作。"
        )
    else:
        verdict = (
            f"反谄媚门放行：结论强度『{c.strength}』与其证据姿态相称，未检出谄媚缺口。"
        )
    _assert_no_banned_positive(verdict)

    return AntiSycophancyDecision(
        permitted_strength=permitted_strength,
        permit_sure_win=False,  # 稳赢断言从不被背书
        refused_strong_conclusion=refused_strong,
        sure_win_refused=sure_win_refused,
        refused_live_escalation=refused_live,
        gaps=tuple(gaps),
        evidence_requirements=tuple(evidence),
        next_steps=tuple(next_steps),
        verdict_text=verdict,
    )


def gate_anti_sycophancy(c: AgentConclusion) -> TrustDecision:
    """把反谄媚裁定包成统一 TrustDecision（供聚合）。`passed=False` 即拦下了谄媚强结论。"""

    d = check_anti_sycophancy(c)
    violations: list[TrustViolation] = []
    if not d.ok:
        violations.append(
            TrustViolation(
                SYCOPHANTIC_STRONG_CONCLUSION,
                "顺从 user wishful thinking 输出越权强结论/稳赢断言/越级实盘 → 拒（§13 反谄媚）："
                + "；".join(d.gaps),
            )
        )
    notes = tuple(f"证据要求：{e}" for e in d.evidence_requirements) + tuple(
        f"下一步：{s}" for s in d.next_steps
    )
    return TrustDecision(
        gate_id="anti_sycophancy",
        passed=d.ok,
        violations=tuple(violations),
        notes=notes,
        verdict_text=d.verdict_text,
    )


# ════════════════════════════════════════════════════════════════════════════
# ④ 弱点一等呈现门：风险/缺口/弱点默认可见·绝不淡化隐藏（R25）+ 不隐藏 user waiver
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class DisclosureManifest:
    """要展示给 user 的披露清单（弱点一等呈现门据此判隐藏）。

    `known_weaknesses`：系统已知的弱点/风险/缺口全集。`shown`：实际展示给 user 的项。
    `hidden`：被显式标记隐藏的项（默认应空·R25 弱点一律一等呈现绝不淡化）。
    `waivers`：在场的 user waiver 全集（choice_id / 描述）。`shown_waivers`：实际展示的 waiver。
    """

    known_weaknesses: tuple[str, ...] = ()
    shown: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    waivers: tuple[str, ...] = ()
    shown_waivers: tuple[str, ...] = ()


def check_weakness_disclosure(m: DisclosureManifest) -> TrustDecision:
    """弱点/风险/缺口默认隐藏 → 拒；user waiver 被隐藏 → 拒。绝不「证据强时做轻」（R25 撤回）。"""

    violations: list[TrustViolation] = []
    shown_set = set(m.shown)
    for w in m.known_weaknesses:
        if w not in shown_set:
            violations.append(
                TrustViolation(
                    WEAKNESS_HIDDEN,
                    f"已知弱点/风险『{w}』未展示（不在 shown）→ 拒（§13/R25 弱点一等呈现·绝不淡化隐藏）",
                )
            )
    for h in m.hidden:
        violations.append(
            TrustViolation(
                WEAKNESS_HIDDEN,
                f"项『{h}』被标记隐藏 → 拒（§13 风险/缺口/弱点须保持可见）",
            )
        )
    shown_waiver_set = set(m.shown_waivers)
    for w in m.waivers:
        if w not in shown_waiver_set:
            violations.append(
                TrustViolation(
                    WAIVER_HIDDEN,
                    f"user waiver『{w}』未展示 → 拒（§13 不得隐藏 user waiver；user-waived 弱点不得默认隐藏）",
                )
            )

    passed = not violations
    if passed:
        verdict = (
            f"弱点一等呈现门放行：{len(m.known_weaknesses)} 项弱点/风险全部展示、无标隐藏项、"
            f"{len(m.waivers)} 条 user waiver 全部展示。"
        )
    else:
        verdict = "弱点一等呈现门拒绝：" + "；".join(v.reason for v in violations)
    _assert_no_banned_positive(verdict)
    return TrustDecision(
        gate_id="weakness_disclosure",
        passed=passed,
        violations=tuple(violations),
        verdict_text=verdict,
    )


# ════════════════════════════════════════════════════════════════════════════
# ① 诚实硬约束门：不伪造强标签 / 不冒充一致 / 单人模式不声明组织独立
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TrustClaim:
    """一条对外/晋级的信任声明：声称达到什么强度 + 它真实背书的【已建证据门】裁定（复用·不重判）。

    `claimed_label`：声称的标签（可能是强标签）。`spine_decision` / `methodology_decision`：来自
    `spine_gate.evaluate_promotion` / `methodology.constrain_promotion` 的裁定 —— 本层只核「声明 ↔ 门裁定
    是否一致」，绝不另写一致性判定（单一源·reuse 不 recreate）。
    `claims_organizational_independence` + `single_person_mode` + `has_real_org_process`：§13 组织独立性
    只在真实组织流程存在时声明（单人模式只展示 functional independence）。
    `claims_theory_impl_consistent` + `consistency_failed`：理论↔实现不一致不得冒充一致。
    """

    asset_ref: str = ""
    claimed_label: str = ""
    spine_decision: SpineDecision | None = None
    methodology_decision: MethodologyDecision | None = None
    claims_organizational_independence: bool = False
    single_person_mode: bool = False
    has_real_org_process: bool = False
    claims_theory_impl_consistent: bool = False
    consistency_failed: bool = False


def check_honesty_constraints(claim: TrustClaim) -> TrustDecision:
    """诚实硬约束核查：声称强标签必须有【已建证据门】放行该标签背书，否则 = 伪造 → 拒。"""

    violations: list[TrustViolation] = []
    notes: list[str] = []
    label = (claim.claimed_label or "").strip()
    strong = label in STRONG_LABELS

    if strong:
        sd = claim.spine_decision
        md = claim.methodology_decision
        # spine 一致性门必须放行该【确切】标签（reuse·本层不另判一致性）。
        spine_ok = sd is not None and sd.promotable and sd.granted_label == label
        # methodology 控制面若在场不得 cap 掉它（放宽档会把强标签降级）。
        meth_ok = md is None or (md.permitted and md.granted_label == label and not md.capped)
        if not (spine_ok and meth_ok):
            why: list[str] = []
            if sd is None:
                why.append("无 spine 一致性门裁定背书")
            elif not sd.promotable:
                why.append(f"spine 一致性门未放行（只授 {sd.granted_label}）")
            elif sd.granted_label != label:
                why.append(f"spine 一致性门只授『{sd.granted_label}』≠声称『{label}』")
            if md is not None and not (md.permitted and md.granted_label == label and not md.capped):
                why.append(
                    f"methodology 控制面把它降级到『{md.granted_label}』(capped={md.capped})"
                )
            violations.append(
                TrustViolation(
                    FAKE_STRONG_LABEL,
                    f"声称强标签『{label}』但{'；'.join(why)} → 拒"
                    "（§13 不得伪造 proof_backed / evidence_sufficient / production_ready）",
                )
            )
        else:
            notes.append(f"强标签『{label}』经已建证据门放行（spine + methodology 双背书）")

    if claim.claims_theory_impl_consistent and claim.consistency_failed:
        violations.append(
            TrustViolation(
                FAKE_CONSISTENCY,
                "声称理论↔实现一致但一致性检查 fail → 拒"
                "（§13 不得让理论与实现不一致的产物冒充一致）",
            )
        )

    if claim.claims_organizational_independence and (
        claim.single_person_mode or not claim.has_real_org_process
    ):
        violations.append(
            TrustViolation(
                FAKE_ORG_INDEPENDENCE,
                "单人模式/无真实组织流程却声明组织独立 → 拒"
                "（§13 组织独立性只在真实组织流程存在时声明；单人模式只展示 functional independence："
                "隔离验证路径 / 不可变证据 / 二次确认 / 异模型验证）",
            )
        )

    passed = not violations
    if passed:
        verdict = "诚实硬约束门放行：声称标签与已建证据门裁定一致，未检出伪造强标签/冒充一致/越权组织独立。"
    else:
        verdict = "诚实硬约束门拒绝：" + "；".join(v.reason for v in violations)
    _assert_no_banned_positive(verdict)
    return TrustDecision(
        gate_id="honesty_constraints",
        passed=passed,
        violations=tuple(violations),
        notes=tuple(notes),
        verdict_text=verdict,
    )


# ════════════════════════════════════════════════════════════════════════════
# 用户自主门：不替 user 拍板方法学/风险选择（§13「Agent 给推荐，不替 user 决定」）
# ════════════════════════════════════════════════════════════════════════════
_USER_ACTORS = frozenset({"user", "human", "operator", "owner", "属主", "用户"})


def _is_user_actor(actor: str) -> bool:
    return (actor or "").strip().lower() in _USER_ACTORS


def check_user_autonomy(
    *,
    methodology_choice: MethodologyChoiceRecord | None = None,
    responsibility: ResponsibilityDisclosureRecord | None = None,
) -> TrustDecision:
    """§13「不替 user 决定」：方法学放权 / 风险承担的【决定】须由 user 发起，agent 替拍 → 拒。

    系统可【推荐】(recommendation)，但放权/承担风险的拍板不能 actor=agent/system。
    - 方法学放权（MCR.is_waiver）actor 是明确的非 user → 拒。
    - 风险承担（responsibility.user_accepted_risk）actor 非 user（含空，因风险归属须明确署名）→ 拒。
    """

    violations: list[TrustViolation] = []

    if methodology_choice is not None and methodology_choice.is_waiver:
        actor = (methodology_choice.actor or "").strip()
        if actor and not _is_user_actor(actor):
            violations.append(
                TrustViolation(
                    AGENT_DECIDED_FOR_USER,
                    f"方法学放权由 actor={actor!r}（非 user）拍板 → 拒"
                    "（§13 Agent 替 user 拍板方法学选择）",
                )
            )

    if responsibility is not None and responsibility.user_accepted_risk:
        if not _is_user_actor(responsibility.actor):
            violations.append(
                TrustViolation(
                    AGENT_DECIDED_FOR_USER,
                    f"风险承担由 actor={responsibility.actor!r}（非 user）拍板 → 拒"
                    "（§13 Agent 替 user 拍板风险选择；风险归属须 user 明确署名）",
                )
            )

    passed = not violations
    if passed:
        verdict = "用户自主门放行：方法学/风险选择均由 user 拍板，系统只给推荐未替 user 决定。"
    else:
        verdict = "用户自主门拒绝：" + "；".join(v.reason for v in violations)
    _assert_no_banned_positive(verdict)
    return TrustDecision(
        gate_id="user_autonomy",
        passed=passed,
        violations=tuple(violations),
        verdict_text=verdict,
    )


# ════════════════════════════════════════════════════════════════════════════
# 责任披露门：user 承担风险 → 须完整 ResponsibilityDisclosureRecord（但不过度拦非红线）
# ════════════════════════════════════════════════════════════════════════════
def check_responsibility(
    *,
    risk_assumed: bool,
    responsibility: ResponsibilityDisclosureRecord | None = None,
) -> TrustDecision:
    """§13：user 承担风险 → 必须有【完整】ResponsibilityDisclosureRecord；缺/不完整 → 拒。

    诚实对称（§13「user 选择自负其责后系统仍阻断非红线交付 → 拒」）：本门**只**要求把责任留痕，
    留痕齐了就放行 —— 不在此再加任何非红线阻断（安全红线另由 waiver-safety 命门硬守，与本门正交）。
    """

    violations: list[TrustViolation] = []
    notes: list[str] = []

    if risk_assumed:
        if responsibility is None:
            violations.append(
                TrustViolation(
                    MISSING_RESPONSIBILITY,
                    "user 承担风险但缺 ResponsibilityDisclosureRecord → 拒"
                    "（§13 须把选择写入责任披露记录）",
                )
            )
        elif not responsibility.is_complete:
            miss = responsibility.missing_fields()
            violations.append(
                TrustViolation(
                    INCOMPLETE_RESPONSIBILITY,
                    f"ResponsibilityDisclosureRecord 不完整（缺 {','.join(miss)}）→ 拒"
                    "（§13 责任边界 / 风险归属 / 具体承担项须齐，空壳记录不算数）",
                )
            )
        else:
            notes.append(
                f"user 已经完整 ResponsibilityDisclosureRecord 承担风险"
                f"（disclosure_id={responsibility.disclosure_id}）→ 非红线交付不再加阻断"
            )

    passed = not violations
    if passed:
        verdict = (
            "责任披露门放行：未承担风险或已附完整责任披露记录——非红线交付按 user 选择继续。"
        )
    else:
        verdict = "责任披露门拒绝：" + "；".join(v.reason for v in violations)
    _assert_no_banned_positive(verdict)
    return TrustDecision(
        gate_id="responsibility_disclosure",
        passed=passed,
        violations=tuple(violations),
        notes=tuple(notes),
        verdict_text=verdict,
    )


# ════════════════════════════════════════════════════════════════════════════
# 聚合入口：跑全部信任层硬约束门（命门走硬 raise·其余结构化）
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TrustContext:
    """一次信任层核查的输入束（全字段默认空 → 部分上下文也能核·相关门才触发）。"""

    asset_ref: str = ""
    # ② waiver-safety（命门）
    waiver: WaiverRequest | None = None
    methodology_choice: MethodologyChoiceRecord | None = None
    extra_waived_targets: tuple[str, ...] = ()
    # ① 诚实硬约束
    claim: TrustClaim | None = None
    # ③ 反谄媚
    conclusion: AgentConclusion | None = None
    # ④ 弱点一等呈现
    disclosure: DisclosureManifest | None = None
    # 责任披露 + 用户自主
    risk_assumed: bool = False
    responsibility: ResponsibilityDisclosureRecord | None = None


@dataclass(frozen=True)
class TrustValidation:
    """一次信任层核查的聚合结果（不抛门拒·结构化）。`ok` = 全部子门 passed。

    命门（安全不变量被 waiver 绕过）**不**走这里的 soft ok=False —— 它在 `evaluate_trust` 里直接
    raise SafetyWaiverError（撞即停）。本结构里的 `waiver_safety` 仅当无绕过时记录「放行 + 哪些可放宽」。
    """

    ok: bool
    decisions: tuple[TrustDecision, ...]
    waiver_safety: WaiverSafetyDecision
    anti_sycophancy: AntiSycophancyDecision | None = None

    @property
    def rejections(self) -> tuple[TrustDecision, ...]:
        return tuple(d for d in self.decisions if not d.passed)

    @property
    def violation_codes(self) -> tuple[str, ...]:
        out: list[str] = []
        for d in self.rejections:
            out.extend(d.violation_codes)
        return tuple(out)

    @property
    def reason_text(self) -> str:
        if self.ok:
            return "过信任层全部已运行硬约束门（§13）"
        return "；".join(f"[{d.gate_id}] {d.verdict_text}" for d in self.rejections)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "decisions": [d.to_dict() for d in self.decisions],
            "rejections": [d.to_dict() for d in self.rejections],
            "waiver_safety": {
                "bypass_attempted": self.waiver_safety.bypass_attempted,
                "refused_safety_targets": [
                    {"target": t, "invariant": inv}
                    for t, inv in self.waiver_safety.refused_safety_targets
                ],
                "permitted_targets": list(self.waiver_safety.permitted_targets),
            },
            "reason_text": self.reason_text,
        }


class TrustRejected(Exception):
    """信任层硬约束未过（非命门软违规）：携带结构化 `validation` 供调用方读缺口。"""

    def __init__(self, validation: TrustValidation) -> None:
        self.validation = validation
        super().__init__(validation.reason_text)


def evaluate_trust(ctx: TrustContext) -> TrustValidation:
    """对一次上下文跑信任层全部硬约束门，返结构化结果。

    命门先行（fail-closed·撞即停）：任一弃权目标触及安全不变量 → 直接 raise SafetyWaiverError，
    绝不降级成 soft ok=False（安全不变量不可 waiver·不可商量）。其余诚实/反谄媚/弱点/责任/自主
    门走结构化裁定，`ok = 全部子门 passed`。
    """

    targets = collect_waived_targets(
        waiver=ctx.waiver,
        methodology_choice=ctx.methodology_choice,
        extra_targets=ctx.extra_waived_targets,
    )
    assert_safety_invariants_intact(targets)  # 命门：撞即 raise

    decisions: list[TrustDecision] = []
    anti_syc: AntiSycophancyDecision | None = None

    if ctx.claim is not None:
        decisions.append(check_honesty_constraints(ctx.claim))
    if ctx.conclusion is not None:
        anti_syc = check_anti_sycophancy(ctx.conclusion)
        decisions.append(gate_anti_sycophancy(ctx.conclusion))
    if ctx.disclosure is not None:
        decisions.append(check_weakness_disclosure(ctx.disclosure))
    decisions.append(
        check_user_autonomy(
            methodology_choice=ctx.methodology_choice, responsibility=ctx.responsibility
        )
    )
    decisions.append(
        check_responsibility(risk_assumed=ctx.risk_assumed, responsibility=ctx.responsibility)
    )

    ok = all(d.passed for d in decisions)
    return TrustValidation(
        ok=ok,
        decisions=tuple(decisions),
        waiver_safety=evaluate_waiver_safety(targets),
        anti_sycophancy=anti_syc,
    )


def require_trustworthy(ctx: TrustContext) -> TrustContext:
    """核查并在未过信任层硬约束门时 raise（命门走 SafetyWaiverError·其余 TrustRejected）。过 → 原样返回。"""

    v = evaluate_trust(ctx)  # 命门在内部 raise SafetyWaiverError
    if not v.ok:
        raise TrustRejected(v)
    return ctx
