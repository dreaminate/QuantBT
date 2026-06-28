"""SA-3 · promote 门链 seam（§9/§10/§13/§16/§17 六门共享收口·codemap construction-map §4.D）。

**为什么存在**：六道节门——§9 因子/策略边界、§10 成本/TCA、§10 控制面、§13 信任发版、§16 工程标准、
§17 RDP——都要穿过同一个 chokepoint `ide/promote.py`。没有共享 seam，这就退化成对 promote.py 的
**六次串行改**（六张卡抢同一热文件）。本模块提供注册式门链：每道节门把自己的 check **注册**成一个具名
check，promote.py 只需调用 `chain.evaluate(manifest)` **一次**，拿回全部门的裁定。

**职责分离（gaming-proof 的关键）**：
  - 一道 check **只懂「这个 run 过没过」**（返回 `GateCheckResult(ok, reason, missing)`）——它不决定
    自己是 advisory 还是 enforce。
  - **advisory/enforce 由门链经 SA-2 策略（`governance.enforcement_policy`）统一盖章**，绝非 check
    自报。于是**没有任何 check 能自封 enforce 绕过 producer-绿灯门**——策略是唯一的翻转 chokepoint。
  - 「过没过」与「该不该 enforce」正交合成 `GateVerdict`：**只有 enforce 且未过才阻断 promote**；
    advisory 一律只记录、永不阻断（守 LOCKED 决策「转绿前只 advisory + 记录·绝不误拒诚实 run」）。

**fail-closed / 反作弊（codex 对抗复审后加固）**：
  - `GateCheckResult.ok` **必须是布尔**——拒 `ok="false"` 这类 truthy 字符串冒充过门（否则
    `bool("false")==True` 会静默吞掉一次 enforce 拒绝）；门链消费侧再 `ok is True` 二次兜底。
  - 每道 check 收到的是 manifest 的**独立深拷贝**——一道 check 改不动另一道 check 看到的字段，也污染
    不了原 manifest（防「前一道门伪造字段、后一道 enforce 门据此放行」的串改攻击）。
  - enforce 门的 check **抛异常** → 视为未过（`ok=False, errored=True`）→ 阻断（坏掉的 enforce 门
    绝不静默放行）；advisory 门抛异常 → 记录不阻断。
  - producer 未绿的 enforce_intent 门 → SA-2 策略降级 advisory（拒翻），即便 check 判 ok=False 也
    **不阻断**（绝不在未接线门上误拒诚实 run）。
  - `GateVerdict.advisory_or_enforce` 只认 `advisory`/`enforce` 字面（`"enforce "` 这类错拼 → 构造即抛），
    杜绝「错拼 mode 让 enforcing 误判 False、阻断被悄悄丢」。

**复用不重造（RULES §1 单一源）**：已建 §16 release gate（`promote_assembler.evaluate_run_releasable`
→ `ReleaseValidation`）作为门链的**一道 check** 插入即可——`GateCheckResult.from_release_validation`
duck-type 适配，绝不重写任何门判定。

**冷导入安全**：`app.governance` 包 __init__ 经 spine_invariants 触达 orchestrator，存在**既有**冷导入
循环（非本卡引入）。本模块刻意**不在顶层 import governance**——MODE 字面量本地声明（值与
`enforcement_policy.MODE_*` 同·由 test_promote_gate_chain 守不漂），policy 符号在 `register`/`evaluate`
**惰性载入**。于是 `import app.release_gate.promote_gate_chain` 自身冷导入安全·不强加导入顺序。

**领地**：本文件是新建孤立模块。**不**在此串进 `ide/promote.py`（中心后续一次性串入·两步法）。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:  # 仅类型检查期·运行期不触发 governance 包冷导入循环
    from ..governance.enforcement_policy import EnforcementDecl, EnforcementResolution

# wire 词汇：值与 `governance.enforcement_policy.MODE_ADVISORY/MODE_ENFORCE` 同（语义单一源在那）。
# 本地声明 = 冷导入安全（不在顶层 import governance）；漂移由 test_chain_mode_constants_match_policy 守。
MODE_ADVISORY = "advisory"
MODE_ENFORCE = "enforce"

RunManifest = Mapping[str, Any]


def _clean(s: object) -> str:
    return s.strip() if isinstance(s, str) and s.strip() else ""


@dataclass(frozen=True)
class GateCheckResult:
    """一道门 check 对某 run 的**过/不过发现**（门只懂过没过·不碰 advisory/enforce）。

    `ok` **必须是布尔**（构造即校验）——这是反作弊硬契约：拒 `ok="false"` / `ok=1` 这类 truthy 非布尔
    冒充过门（`bool("false")` 会是 True·会静默吞 enforce 拒绝）。
    """

    ok: bool
    reason: str = ""
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError(
                f"GateCheckResult.ok 必须是 bool，得到 {type(self.ok).__name__}="
                f"{self.ok!r}（fail-closed·拒 truthy 非布尔冒充过门）"
            )

    @classmethod
    def from_release_validation(cls, validation: Any) -> "GateCheckResult":
        """复用已建 §16 release gate（`ReleaseValidation`）—— duck-typed·不硬 import·不重造判定。

        取 `.ok`（硬门聚合裁定·严格 `is True`）+ `.reason_text`（人读拒因）+ `.missing`（缺了哪些）。
        任一缺字段诚实降级（`ok` 非 True → False·fail-closed）。
        """

        ok = getattr(validation, "ok", False) is True
        try:
            reason = _clean(getattr(validation, "reason_text", "") or "")
        except Exception:  # noqa: BLE001 — 取 reason 失败不影响 ok 裁定
            reason = ""
        try:
            missing = tuple(getattr(validation, "missing", ()) or ())
        except Exception:  # noqa: BLE001
            missing = ()
        return cls(ok=ok, reason=reason, missing=missing)


# 一道注册的 check：吃 run manifest，吐 GateCheckResult。
GateCheck = Callable[[RunManifest], GateCheckResult]


@dataclass(frozen=True)
class GateVerdict:
    """门链对一道门的**收口裁定**（chain 输出单元）。

    四必填字段（中心串 promote.py 时读这四个）：`gate_name` / `ok` / `advisory_or_enforce` / `reason`。
    其余为诚实审计字段（producer 绿否 / 拒翻 / check 是否炸·全落 run.json 可追溯）。
    """

    gate_name: str
    ok: bool
    advisory_or_enforce: str  # 由 SA-2 策略盖章·绝非 check 自报·只认 advisory/enforce 字面
    reason: str = ""
    missing: tuple[str, ...] = ()
    producer_key: str = ""
    producer_green: bool = False
    flip_refused: bool = False
    errored: bool = False

    def __post_init__(self) -> None:
        if self.advisory_or_enforce not in (MODE_ADVISORY, MODE_ENFORCE):
            raise ValueError(
                f"[{self.gate_name}] 未知 advisory_or_enforce={self.advisory_or_enforce!r}"
                f"（只认 {MODE_ADVISORY!r}/{MODE_ENFORCE!r}·杜绝错拼让阻断被悄悄丢）"
            )

    @property
    def enforcing(self) -> bool:
        return self.advisory_or_enforce == MODE_ENFORCE

    @property
    def blocks(self) -> bool:
        """是否阻断 promote。**单一阻断规则**：仅当 enforce 且未过才阻断；advisory 永不阻断。"""

        return self.enforcing and not self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "ok": self.ok,
            "advisory_or_enforce": self.advisory_or_enforce,
            "reason": self.reason,
            "missing": list(self.missing),
            "producer_key": self.producer_key,
            "producer_green": self.producer_green,
            "flip_refused": self.flip_refused,
            "errored": self.errored,
            "blocks": self.blocks,
        }


@dataclass(frozen=True)
class ChainResult:
    """门链一次评估的聚合结果（不抛·结构化面·供 promote 落 run.json + 决定是否阻断）。"""

    verdicts: tuple[GateVerdict, ...] = ()

    @property
    def rejections(self) -> tuple[GateVerdict, ...]:
        """阻断 promote 的裁定（仅 enforce 且未过）。"""

        return tuple(v for v in self.verdicts if v.blocks)

    @property
    def rejected(self) -> bool:
        """整链是否拒绝晋级（任一 enforce 门未过）。advisory 门未过**不**拒。"""

        return bool(self.rejections)

    @property
    def advisories(self) -> tuple[GateVerdict, ...]:
        """advisory 门裁定（只记录·永不阻断·含未过的）。"""

        return tuple(v for v in self.verdicts if not v.enforcing)

    @property
    def reason_text(self) -> str:
        if not self.rejections:
            return "门链全部 enforce 门通过（advisory 门只记录不阻断）"
        return "；".join(f"[{v.gate_name}] {v.reason}" for v in self.rejections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rejected": self.rejected,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "rejections": [v.to_dict() for v in self.rejections],
            "advisories": [v.to_dict() for v in self.advisories],
            "reason_text": self.reason_text,
        }


@dataclass(frozen=True)
class _Registration:
    decl: "EnforcementDecl"
    check: GateCheck


class PromoteGateChain:
    """注册式 promote 门链（实例级注册表·无隐藏全局态·可独立测）。

    用法（中心串 promote.py 时）：
        chain = default_chain()                 # 或注入一个独立实例
        chain.register(gate_name="s17_rdp", check=rdp_check,
                       required_producer="rdp_runjson_producers", enforce_intent=True)
        result = chain.evaluate(manifest, producer_status=ledger)
        manifest["promote_gate_chain"] = result.to_dict()
        if result.rejected:
            raise PromoteError(result.reason_text)   # 仅 enforce 门未过才到这
    """

    def __init__(self) -> None:
        self._regs: dict[str, _Registration] = {}

    def register(
        self,
        *,
        gate_name: str,
        check: GateCheck,
        required_producer: str = "",
        enforce_intent: bool = False,
    ) -> None:
        """注册一道节门的具名 check + 其 enforce 意图声明。

        - `gate_name` 唯一（重复注册 → 抛·防一道门被悄悄覆盖）。
        - `enforce_intent=True` 的门仅当 `required_producer` 转绿才真 enforce（SA-2 策略管翻转）。
        """

        from ..governance.enforcement_policy import EnforcementDecl  # 惰性·冷导入安全

        name = _clean(gate_name)
        if not name:
            raise ValueError("gate_name 不能为空")
        if name in self._regs:
            raise ValueError(f"门 {name!r} 已注册（防重复/防静默覆盖）")
        if not callable(check):
            raise TypeError(f"门 {name!r} 的 check 必须可调用，得到 {type(check).__name__}")
        decl = EnforcementDecl(
            gate_name=name,
            required_producer=_clean(required_producer),
            enforce_intent=bool(enforce_intent),
        )
        self._regs[name] = _Registration(decl=decl, check=check)

    @property
    def gate_names(self) -> tuple[str, ...]:
        return tuple(self._regs.keys())

    def evaluate(
        self, manifest: RunManifest, *, producer_status: "Any | None" = None
    ) -> ChainResult:
        """跑**全部**注册 check 一遍，收齐裁定（绝不短路·enforce 拒后仍收 advisory 记录）。

        每道 check 收到 manifest 的**独立深拷贝**——防一道 check 串改另一道 check 看到的字段 / 污染原
        manifest（反作弊）。
        """

        from ..governance.enforcement_policy import resolve_enforcement  # 惰性·冷导入安全

        verdicts: list[GateVerdict] = []
        for reg in self._regs.values():
            # 策略先解析（独立于 check 行为·避免 check 影响 advisory/enforce 判定）。
            resolution = resolve_enforcement(reg.decl, producer_status)
            verdicts.append(self._run_one(self._isolate(manifest), reg, resolution))
        return ChainResult(verdicts=tuple(verdicts))

    @staticmethod
    def _isolate(manifest: RunManifest) -> Any:
        """给一道 check 一份隔离的 manifest（深拷贝·防跨 check 串改/污染原 manifest）。

        深拷贝失败（罕见·manifest 携不可拷对象）→ 退浅拷贝（至少隔离顶层 rebinding）→ 再不行原样传。
        """

        try:
            return copy.deepcopy(dict(manifest))
        except Exception:  # noqa: BLE001
            try:
                return dict(manifest)
            except Exception:  # noqa: BLE001
                return manifest

    @staticmethod
    def _run_one(
        manifest: RunManifest, reg: _Registration, resolution: "EnforcementResolution"
    ) -> GateVerdict:
        try:
            cr = reg.check(manifest)
            if not isinstance(cr, GateCheckResult):
                raise TypeError(
                    f"check 须返回 GateCheckResult，得到 {type(cr).__name__}"
                )
            return GateVerdict(
                gate_name=resolution.gate_name,
                ok=cr.ok is True,  # 严格·二次兜底（GateCheckResult 已保证 bool）
                advisory_or_enforce=resolution.mode,
                reason=_clean(cr.reason) or resolution.reason,
                missing=tuple(cr.missing or ()),
                producer_key=resolution.producer_key,
                producer_green=resolution.producer_green,
                flip_refused=resolution.flip_refused,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed：check 炸了不静默放行
            # enforce 门：errored→ok=False→阻断（坏门绝不放行）。advisory 门：记录不阻断。
            return GateVerdict(
                gate_name=resolution.gate_name,
                ok=False,
                advisory_or_enforce=resolution.mode,
                reason=f"check 执行异常（fail-closed·视为未过）: {type(exc).__name__}: {exc}",
                producer_key=resolution.producer_key,
                producer_green=resolution.producer_green,
                flip_refused=resolution.flip_refused,
                errored=True,
            )


# ════════════════════════════════════════════════════════════════════════════
# 进程级默认门链（给中心一个串 promote.py 的共享落点·测试用独立实例不碰它）
# ════════════════════════════════════════════════════════════════════════════
_DEFAULT_CHAIN: PromoteGateChain | None = None


def default_chain() -> PromoteGateChain:
    """进程级共享门链（六道节门注册进这里·promote.py 评估这里）。"""

    global _DEFAULT_CHAIN
    if _DEFAULT_CHAIN is None:
        _DEFAULT_CHAIN = PromoteGateChain()
    return _DEFAULT_CHAIN


def reset_default_chain() -> None:
    """清空默认门链（测试隔离用·绝不在生产路径调）。"""

    global _DEFAULT_CHAIN
    _DEFAULT_CHAIN = None


__all__ = [
    "MODE_ADVISORY",
    "MODE_ENFORCE",
    "RunManifest",
    "GateCheck",
    "GateCheckResult",
    "GateVerdict",
    "ChainResult",
    "PromoteGateChain",
    "default_chain",
    "reset_default_chain",
]
