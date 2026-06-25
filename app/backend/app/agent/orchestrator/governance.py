"""Agent Orchestrator · DAG 治理 + 工具派发唯一闸（GOAL §7「所有 role agent 受 deterministic DAG 管理」）。

GOAL §7 硬契约：role agent 只通过**工具权限 + canonical command + governed compiler** 写 Research
Graph；LLM 永在节点内、绝不当控制器；多 Agent **绝不**绕过 DAG 自由派发工具。本模块把这条兑现成
一道可证伪的结构闸：

- 工具**只能**经 `GovernedToolDispatcher.dispatch(...)` 派发，且必须携带一枚 `NodeExecutionContext`
  ——它**只**由 orchestrator 在进入某个**冻结 DAG 节点**时铸出（`enter_node`），带 HMAC 令牌。
- 没有节点上下文（`node_ctx=None`）= LLM 当控制器自由派发 → `DAGBypassError`（绕过 DAG → 拒）。
- 令牌对不上（伪造上下文骗闸）→ `DAGBypassError`。
- 工具不在该节点冻结的 `permitted_tools` 里（越权 / 越 DAG 计划）→ `ToolPermissionError`。

「冻结」语义照 dag/kernel 的内核纪律：图结构运行前冻结，节点产出绝不改图结构。节点内 LLM 想调
计划外工具 = 想动态改图 → 本闸拒。令牌 = 治理 provenance（同 gateway 封印范式）：证明这次派发确实
发生在 orchestrator 亲手进入的节点内，**不是**密码学意义对同进程恶意构造者的防御，但兑现了 GOAL
真正要的「绕过 DAG 的工具使用不被接受、且留账」。

诚实边界：AgentRuntime（被 wrap·不改）把工具 handler 异常吞成 error payload。故越权派发除了在 handler
即时拒，还把违规记进 dispatcher 的 violations——节点 op 跑完 `drain_violations()` 非空即 **raise**，
让内核把该节点判 failed（FailureDetected）。两层都在咬，单测各自种坏门必抓。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any, Callable

ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


class GovernanceError(RuntimeError):
    pass


class DAGBypassError(GovernanceError):
    """工具派发绕过 DAG 节点治理（无节点上下文 / 伪造令牌）→ 拒（GOAL §7）。"""


class ToolPermissionError(GovernanceError):
    """工具不在该节点冻结的 permitted_tools 里（越权 / 越 DAG 计划）→ 拒（GOAL §7 工具权限按台过滤）。"""


@dataclass(frozen=True)
class NodeExecutionContext:
    """进入一个冻结 DAG 节点时铸出的执行上下文——工具派发的准入凭证（GOAL §7）。

    `token` 由 dispatcher 用其私有 nonce 对 (node_id, task_id, role, sorted(permitted_tools)) 做 HMAC。
    没有 nonce 就造不出能过闸的 ctx——这正是「绕过 DAG 自由派发」无法伪造一个有效节点上下文的落点。
    """

    node_id: str
    task_id: str
    role: str
    permitted_tools: frozenset[str]
    token: str


def _canon(permitted: frozenset[str]) -> str:
    return json.dumps(sorted(permitted), ensure_ascii=False)


@dataclass
class ToolCallRecord:
    """一次受治理工具派发的账（GOAL §7：每次工具调用落账·可 replay）。"""

    tool: str
    node_id: str
    task_id: str
    role: str
    ok: bool
    error_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "node_id": self.node_id,
            "task_id": self.task_id,
            "role": self.role,
            "ok": self.ok,
            "error_kind": self.error_kind,
        }


@dataclass
class ToolViolation:
    """一次被闸拦下的越界派发（绕 DAG / 越权）——节点 op 据此 raise→failed。"""

    tool: str
    node_id: str
    task_id: str
    role: str
    kind: str       # "dag_bypass" | "tool_permission"
    reason: str


class GovernedToolDispatcher:
    """工具派发的**唯一闸**（GOAL §7）。

    工具注册 + 节点上下文铸造/核验 + 权限核验 + 落账 + 违规簿记，全在此。orchestrator 把每个 role
    的工具经 `register(...)` 注册（注册名必须 ∈ role 白名单·越界登记期即拒），运行期所有派发经
    `dispatch(...)`，无有效节点上下文一律拒。
    """

    def __init__(self, *, on_event: Callable[[str, dict[str, Any], NodeExecutionContext], None] | None = None) -> None:
        self._tools: dict[str, ToolHandler] = {}
        self._nonce = secrets.token_bytes(32)          # dispatcher 私有，铸/验令牌唯一钥
        self._records: list[ToolCallRecord] = []
        self._violations: list[ToolViolation] = []
        self._active: set[str] = set()                 # 当前在册的有效节点令牌（进/出节点维护）
        self._on_event = on_event                      # 投影 ToolCallStarted/Finished（可选）

    # —— 工具注册 ——
    def register(self, tool: str, handler: ToolHandler) -> None:
        self._tools[tool] = handler

    def registered_tools(self) -> frozenset[str]:
        return frozenset(self._tools)

    # —— 节点边界：令牌铸造 / 核验 ——
    def _mint_token(self, node_id: str, task_id: str, role: str, permitted: frozenset[str]) -> str:
        msg = f"{node_id}\x00{task_id}\x00{role}\x00{_canon(permitted)}".encode("utf-8")
        return hmac.new(self._nonce, msg, hashlib.sha256).hexdigest()[:32]

    def enter_node(
        self, *, node_id: str, task_id: str, role: str, permitted_tools: frozenset[str]
    ) -> NodeExecutionContext:
        """进入冻结 DAG 节点：铸出携带有效令牌的执行上下文，登记为 active。"""

        token = self._mint_token(node_id, task_id, role, permitted_tools)
        ctx = NodeExecutionContext(
            node_id=node_id, task_id=task_id, role=role,
            permitted_tools=frozenset(permitted_tools), token=token,
        )
        self._active.add(token)
        return ctx

    def exit_node(self, ctx: NodeExecutionContext) -> None:
        self._active.discard(ctx.token)

    def _verify_ctx(self, ctx: NodeExecutionContext | None) -> None:
        # 闸 1：无节点上下文 = LLM 当控制器自由派发 → 拒（绕过 DAG）。
        if ctx is None:
            raise DAGBypassError(
                "工具派发缺节点执行上下文——LLM/agent 在冻结 DAG 之外自由派发工具，"
                "绕过 deterministic DAG 治理（GOAL §7：多 Agent 绕过 DAG 自由派发工具 → 拒）"
            )
        # 闸 2：令牌须由本 dispatcher nonce 对 ctx 字段铸出，且仍 active（伪造上下文骗闸 → 拒）。
        expected = self._mint_token(ctx.node_id, ctx.task_id, ctx.role, ctx.permitted_tools)
        if not hmac.compare_digest(expected, ctx.token) or ctx.token not in self._active:
            raise DAGBypassError(
                "节点执行上下文令牌无效/未激活——伪造的节点上下文不能骗过 DAG 治理闸（GOAL §7）"
            )

    # —— 唯一派发口 ——
    def dispatch(self, tool: str, args: dict[str, Any], *, node_ctx: NodeExecutionContext | None) -> dict[str, Any]:
        """受治理工具派发——所有工具调用唯一入口（GOAL §7）。

        无有效节点上下文 → DAGBypassError；工具越白名单 → ToolPermissionError；都过 → 执行 + 落账。
        被拦的越界派发同时记 violation（供节点 op `drain_violations` 判 failed）。
        """

        try:
            self._verify_ctx(node_ctx)
        except DAGBypassError as exc:
            self._violations.append(ToolViolation(
                tool=tool, node_id=getattr(node_ctx, "node_id", ""), task_id=getattr(node_ctx, "task_id", ""),
                role=getattr(node_ctx, "role", ""), kind="dag_bypass", reason=str(exc),
            ))
            raise
        assert node_ctx is not None  # _verify_ctx 已保证
        # 闸 3：工具必须在该节点冻结的 permitted_tools（越权 / 越 DAG 计划 → 拒）。
        if tool not in node_ctx.permitted_tools:
            v = ToolViolation(
                tool=tool, node_id=node_ctx.node_id, task_id=node_ctx.task_id, role=node_ctx.role,
                kind="tool_permission",
                reason=(
                    f"工具 {tool!r} 不在节点冻结权限集 {sorted(node_ctx.permitted_tools)}——"
                    "越权 / 越 DAG 计划派发（GOAL §7 工具权限按台过滤）"
                ),
            )
            self._violations.append(v)
            raise ToolPermissionError(v.reason)
        handler = self._tools.get(tool)
        if handler is None:
            raise ToolPermissionError(f"工具 {tool!r} 未注册到受治理派发器（不可裸调）")

        if self._on_event is not None:
            self._on_event("started", {"tool": tool, "args_keys": sorted(args)}, node_ctx)
        try:
            payload = handler(tool, args)
        except Exception as exc:  # noqa: BLE001  —— handler 内部错如实落账，不静默
            self._records.append(ToolCallRecord(
                tool=tool, node_id=node_ctx.node_id, task_id=node_ctx.task_id, role=node_ctx.role,
                ok=False, error_kind=type(exc).__name__,
            ))
            if self._on_event is not None:
                self._on_event("finished", {"tool": tool, "ok": False, "error_kind": type(exc).__name__}, node_ctx)
            raise
        self._records.append(ToolCallRecord(
            tool=tool, node_id=node_ctx.node_id, task_id=node_ctx.task_id, role=node_ctx.role, ok=True,
        ))
        if self._on_event is not None:
            self._on_event("finished", {"tool": tool, "ok": True}, node_ctx)
        return payload

    # —— 账 / 违规读取 ——
    def records(self) -> tuple[ToolCallRecord, ...]:
        return tuple(self._records)

    def records_for(self, node_id: str) -> list[ToolCallRecord]:
        return [r for r in self._records if r.node_id == node_id]

    def violations(self) -> tuple[ToolViolation, ...]:
        return tuple(self._violations)

    def drain_violations(self, node_id: str | None = None) -> list[ToolViolation]:
        """取出（并从待查清单移除）违规：node_id 给定则只取该节点的。"""

        if node_id is None:
            out = list(self._violations)
            self._violations.clear()
            return out
        out = [v for v in self._violations if v.node_id == node_id]
        self._violations = [v for v in self._violations if v.node_id != node_id]
        return out

    def bind_node_tool(
        self, ctx: NodeExecutionContext, tool: str
    ) -> ToolHandler:
        """生成绑定到某节点上下文的 handler，注册进被 wrap 的 AgentRuntime（扩展不替换）。

        AgentRuntime 调 `handler(name, args)` 时，本闭包补上 node_ctx 转交 `dispatch`——于是
        runtime 里发出的每个工具调用都经治理闸；计划外工具在闸上即拒并记 violation。
        """

        def _bound(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return self.dispatch(name, args, node_ctx=ctx)

        return _bound


__all__ = [
    "GovernanceError",
    "DAGBypassError",
    "ToolPermissionError",
    "NodeExecutionContext",
    "ToolCallRecord",
    "ToolViolation",
    "GovernedToolDispatcher",
    "ToolHandler",
]
