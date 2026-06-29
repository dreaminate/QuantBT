"""SA-3 · promote 门链**单一注册收口**（construction-map §4.D · 中心串行第三波）。

**为什么存在**：SA-3 的承诺是「`ide/promote.py` 只改一次」。各节门（§9 边界 / §10 成本 / §10 控制面
/ 未来 §13/§16/§17）已各自落地成 PARALLEL-SAFE 的 `register_*` 函数。若让 promote.py 逐一 import 并
register 每道门，则**每加一道门就要再改一次 promote.py**——SA-3 想消灭的正是这种「六次串行改热文件」。
本模块把所有 `register_*` 收进**一处**：promote.py 只认 `ensure_default_chain()` 一个入口；**加新门 =
本文件 `_GATE_REGISTRARS` 加一行·绝不再碰 promote.py**。

**advisory-first（守 LOCKED 决策 1）**：本模块只**注册** check（每道门 `enforce_intent=True` = 有资格
enforce），**不**碰 producer 绿灯账。门是 advisory 还是 enforce 由 SA-2 策略在 `chain.evaluate(...,
producer_status=...)` 时按 producer 绿否盖章——producer 未绿（出厂默认全红）→ 全 advisory → 只记录不
阻断。本模块**绝不** mark 任何 producer 绿（那是各门独立 producer 卡的事·假绿灯违 RULES.project）。

**冷导入安全（SA-3 cold-cycle note）**：顶层只 import 同包子模块（`promote_gate_chain` /
`section9_boundary_gate` / `section10_methodology_gate`·三者均经实证冷导入安全·顶层不触 governance
冷循环）。**刻意不** import `release_gate/__init__`（既有冷导入环）——消费方/本模块都从子模块直接 import。
模块**无 import 期副作用**（不 auto-register·register 内的 governance 惰性载入只在 `ensure_default_chain`/
`register_all_gates` 被**调用**时才触发）；于是 `import app.release_gate.gate_registry` 自身冷导入安全。

**领地**：本文件是新建孤立收口件。promote.py 调 `ensure_default_chain().evaluate(...)` 一次（中心串行）。
"""

from __future__ import annotations

from typing import Callable

from .promote_gate_chain import PromoteGateChain, default_chain
from .section9_boundary_gate import register_section9_boundary_gate
from .section10_methodology_gate import (
    register_section10_controlplane_gate,
    register_section10_cost_gate,
)
from .section13_trust_gate import register_section13_trust_gate
from .section17_rdp_gate import register_section17_rdp_gate

# 一道节门的注册器：吃一个门链·把自己的具名 check + enforce 意图注册进去（不返回值）。
GateRegistrar = Callable[[PromoteGateChain], None]

# ════════════════════════════════════════════════════════════════════════════
# 单一注册清单（**加新门 = 这里加一行**·绝不改 promote.py·这就是 SA-3 的承诺）
# 已落地：§9 边界 · §10 成本 · §10 控制面 · §13 信任 · §17 RDP。未来 §16 工程标准 落 register_* 后
# 在本元组追加一行即可——promote.py 一字不动。
# ════════════════════════════════════════════════════════════════════════════
_GATE_REGISTRARS: tuple[GateRegistrar, ...] = (
    register_section9_boundary_gate,
    register_section10_cost_gate,
    register_section10_controlplane_gate,
    register_section13_trust_gate,
    register_section17_rdp_gate,
)


def register_all_gates(chain: PromoteGateChain) -> PromoteGateChain:
    """把全部已落地节门注册进给定门链（纯函数·可作用于任何独立 PromoteGateChain 实例）。

    顺序按 `_GATE_REGISTRARS`。重复注册同名门 → 底层 `chain.register` 抛（防静默覆盖）——故本函数
    只应作用于**空链**（或经 `ensure_default_chain` 的幂等守卫）。返回该链便于链式调用。
    """

    for registrar in _GATE_REGISTRARS:
        registrar(chain)
    return chain


def ensure_default_chain() -> PromoteGateChain:
    """返回进程级共享门链 `default_chain()`，并**幂等**确保全部节门已注册其上。

    promote.py 的唯一入口：`ensure_default_chain().evaluate(manifest, producer_status=...)`。

    幂等 + reset 安全：仅当链为空才注册（`not chain.gate_names`）——首次填满后再调直接返回（不重复
    注册·不撞 `register` 的防重抛）；测试 `reset_default_chain()` 清空后，下次调用又会重新填满。
    本函数**不**注册任何 producer 绿灯（advisory-first·门绿否全交 evaluate 期的 producer_status）。
    """

    chain = default_chain()
    if not chain.gate_names:
        register_all_gates(chain)
    return chain


__all__ = [
    "GateRegistrar",
    "register_all_gates",
    "ensure_default_chain",
]
