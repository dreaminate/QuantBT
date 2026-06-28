"""SA-2 · enforce 切换策略件（横切·LOCKED 决策 1·codemap construction-map §4.1）。

LOCKED 决策（中心转达·已 bake）：**每个门的「证据 producer 接线测试」转绿那刻，自动从
advisory 翻 enforce；转绿前只 advisory + 记录；绝不误拒诚实 run。** 本模块把这条决策编码成
一个**不可绕**的策略件——任何门要 enforce（在真路径上「拒」坏 run），必须先证明它的证据
producer 已绿（producer-wiring 测试通过、被标 green）。

fail-closed 不变量（本模块的灵魂·守 RULES §3 诚实 + RULES.project「未验证≠已验证」）：
  **mode==ENFORCE ⟹ producer_green==True。** 这条不变量在 `EnforcementResolution.__post_init__`
  硬核——任何试图构造「无绿 producer 却 enforce」的解析对象 → 立即抛 `EnforcementPolicyError`。
  于是「在未接线门上误拒诚实 run」这个不安全态**在类型层不可表示**，无法被任何调用方（含未来
  的 gaming 尝试）静默绕过。

两条公开 API，职责分离：
  - `resolve_enforcement(decl, producer_status)`：**安全运行期解析**。enforce_intent 且 producer
    已绿 → ENFORCE；否则降级 ADVISORY 并把「拒翻」记进 `flip_refused`。**绝不抛、绝不静默 enforce**
    （守 LOCKED 决策「转绿前只 advisory + 记录」、守「绝不误拒诚实 run」）。promote 主流程用这条。
  - `EnforcementResolution(...)` 直接构造：受 `__post_init__` 的结构不变量保护——enforce-on-red
    不可表示。这是「拒翻」的**结构性**保证（gaming-proof），与 resolve 的运行期降级互补。

诚实边界：本模块**只**决定「该不该 enforce」，不决定「门过没过」（那是各门 check 自己的事），
也不持有「producer 到底绿没绿」的真相——真相由 producer-wiring 测试 + 调用方传入的
`producer_status` 提供。本件只保证：没有绿证据，就绝不 enforce。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Union

# —— 生效模式（单一命名源·下游 release_gate.promote_gate_chain 复用，不另造字面量）——
MODE_ADVISORY = "advisory"
MODE_ENFORCE = "enforce"
ENFORCEMENT_MODES = (MODE_ADVISORY, MODE_ENFORCE)

# producer 绿灯状态源：一张 {producer_key: green_bool} 映射，或一个 key→bool 的可调用。
# 缺 key / 异常 / None 一律视为「未绿」（fail-closed 默认·见 `_is_green`）。
ProducerStatus = Union[Mapping[str, bool], Callable[[str], bool]]


class EnforcementPolicyError(ValueError):
    """fail-closed 违反：试图在无绿 producer 时让门 enforce（不可表示的不安全态）。"""


def _clean(s: object) -> str:
    return s.strip() if isinstance(s, str) and s.strip() else ""


def _is_green(status: ProducerStatus | None, key: str) -> bool:
    """producer 是否已绿。**严格 + fail-closed**：唯有状态源对该 key 给出**布尔 `True`** 才算绿。

    刻意用 `is True` 而非 `bool(...)`——否则 `"red"` / `"false"` / `1` 这类 truthy 非布尔值会被当成绿
    （假绿灯·违 RULES.project「未验证≠已验证」）。空 key / 缺 key / None / 状态源异常 → 一律未绿
    （fail-closed：「不注册 producer」「状态源炸了」都只会停在 advisory·绝不意外 enforce）。
    """

    if not key or status is None:
        return False
    if callable(status):
        try:
            return status(key) is True
        except Exception:  # noqa: BLE001 — 状态源异常视为未绿（fail-closed·绝不因此 enforce）
            return False
    try:
        return status.get(key, False) is True  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return False


@dataclass(frozen=True)
class EnforcementDecl:
    """一个门对 enforce 的**意图声明**（注册期不可变·喂给策略解析）。

    - `enforce_intent=False` → 纯 advisory 门（GOAL 无「拒」语义 / 只记录）：永远不 enforce。
    - `enforce_intent=True`  → 该门有 GOAL「拒」语义、**有资格** enforce，但仅当 `required_producer`
      转绿才真翻 enforce；未绿则被策略降级 advisory + 记录（绝不误拒诚实 run）。
    - `required_producer` 空 → 该门没有可证明的证据 producer，enforce_intent 即便为真也永远停 advisory
      （fail-closed：无 producer ⇒ 永不绿 ⇒ 永不 enforce）。
    """

    gate_name: str
    required_producer: str = ""
    enforce_intent: bool = False

    def __post_init__(self) -> None:
        if not _clean(self.gate_name):
            raise EnforcementPolicyError("EnforcementDecl.gate_name 不能为空")


@dataclass(frozen=True)
class EnforcementResolution:
    """策略对一个门解析出的**生效模式**（含完整审计痕迹·可投影进 run.json）。

    结构不变量（fail-closed 核心）：
      ① `mode` 必须 ∈ {advisory, enforce}；
      ② **`mode==enforce` ⟹ `producer_green==True`**——enforce-on-red 不可表示，构造即抛；
      ③ enforce 解析不得同时 `flip_refused`（语义自洽）。
    """

    gate_name: str
    mode: str
    producer_key: str
    producer_green: bool
    enforce_intent: bool
    flip_refused: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if self.mode not in ENFORCEMENT_MODES:
            raise EnforcementPolicyError(
                f"[{self.gate_name}] 未知 enforcement mode: {self.mode!r}"
            )
        # —— fail-closed 灵魂：没有绿 producer，就不可能 enforce ——
        if self.mode == MODE_ENFORCE and not self.producer_green:
            raise EnforcementPolicyError(
                f"[{self.gate_name}] fail-closed：producer {self.producer_key!r} 未绿，"
                f"拒绝 enforce 翻转（不可表示「无证据却 enforce」的不安全态）"
            )
        if self.mode == MODE_ENFORCE and self.flip_refused:
            raise EnforcementPolicyError(
                f"[{self.gate_name}] enforce 解析不得同时标 flip_refused（语义不自洽）"
            )

    @property
    def enforcing(self) -> bool:
        return self.mode == MODE_ENFORCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "mode": self.mode,
            "producer_key": self.producer_key,
            "producer_green": self.producer_green,
            "enforce_intent": self.enforce_intent,
            "flip_refused": self.flip_refused,
            "reason": self.reason,
        }


def resolve_enforcement(
    decl: EnforcementDecl, producer_status: ProducerStatus | None = None
) -> EnforcementResolution:
    """安全运行期解析（promote 主流程用·绝不抛、绝不静默 enforce）。

    判定（守 LOCKED 决策）：
      - `enforce_intent=False` → ADVISORY（纯记录门）。
      - `enforce_intent=True` 且 `required_producer` 已绿 → **ENFORCE**（producer 转绿即自动翻）。
      - `enforce_intent=True` 但 producer 未绿/缺 → **ADVISORY + flip_refused=True**：拒绝 enforce
        翻转、降级记录（绝不误拒诚实 run·守「转绿前只 advisory + 记录」）。
    """

    green = _is_green(producer_status, decl.required_producer)

    if not decl.enforce_intent:
        return EnforcementResolution(
            gate_name=decl.gate_name,
            mode=MODE_ADVISORY,
            producer_key=decl.required_producer,
            producer_green=green,
            enforce_intent=False,
            flip_refused=False,
            reason="advisory 门（无 enforce 意图·只记录不阻断）",
        )

    if green:
        return EnforcementResolution(
            gate_name=decl.gate_name,
            mode=MODE_ENFORCE,
            producer_key=decl.required_producer,
            producer_green=True,
            enforce_intent=True,
            flip_refused=False,
            reason=f"producer {decl.required_producer!r} 已绿 → 自动 enforce（LOCKED 决策 1）",
        )

    why = (
        "未声明 required_producer"
        if not _clean(decl.required_producer)
        else f"producer {decl.required_producer!r} 未绿/缺"
    )
    return EnforcementResolution(
        gate_name=decl.gate_name,
        mode=MODE_ADVISORY,
        producer_key=decl.required_producer,
        producer_green=False,
        enforce_intent=True,
        flip_refused=True,
        reason=f"{why}：拒绝 enforce 翻转（fail-closed·降级 advisory + 记录·绝不误拒诚实 run）",
    )


class ProducerStatusLedger:
    """producer 绿灯账（薄字典包·给中心/测试一个显式 `mark_green` API）。

    **honest 默认**：所有 producer 初始为 **red**（未绿）——seam 出厂即 advisory-first，门只在
    其 producer-wiring 测试转绿、被显式 `mark_green` 后才有资格 enforce。绝不预置任何 producer 为绿
    （那就是假绿灯·违 RULES.project「未验证≠已验证」）。
    """

    def __init__(self, green: Mapping[str, bool] | None = None) -> None:
        self._green: dict[str, bool] = {}
        if green:
            # 严格：只有布尔 True 入账为绿（"red"/"false"/1 等 truthy 非布尔 → red·防假绿灯）。
            for k, v in green.items():
                self._green[k] = v is True

    def mark_green(self, producer_key: str) -> None:
        if not _clean(producer_key):
            raise EnforcementPolicyError("producer_key 不能为空")
        self._green[producer_key] = True

    def mark_red(self, producer_key: str) -> None:
        self._green[producer_key] = False

    def is_green(self, producer_key: str) -> bool:
        return self._green.get(producer_key, False) is True

    def __call__(self, producer_key: str) -> bool:
        return self.is_green(producer_key)

    def as_mapping(self) -> dict[str, bool]:
        return dict(self._green)


__all__ = [
    "MODE_ADVISORY",
    "MODE_ENFORCE",
    "ENFORCEMENT_MODES",
    "ProducerStatus",
    "EnforcementPolicyError",
    "EnforcementDecl",
    "EnforcementResolution",
    "ProducerStatusLedger",
    "resolve_enforcement",
]
