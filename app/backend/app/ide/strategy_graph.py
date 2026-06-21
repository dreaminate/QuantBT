"""S2 策略台后端逻辑：图校验 (B6 三层) + 策略级 fork/版本身份锚定。

为什么是独立模块（CLAUDE「新逻辑优先新模块文件，main.py 只加端点」）：
- main.py 是单文件 @app.* 巨壳，扩展不替换——这里放纯函数 + 服务方法，main.py 只调。

身份单一源（三联硬约束「身份经 lineage/ids.py 单一身份源」）：
- 策略版本/Fork 的内容指纹一律走 `lineage.content_hash`（16 位、canonical_json），
  **绝不**自造第二套 hashlib —— 否则同一策略两个 id，版本史/血缘当场裂。
- Fork 的父锚 (`parent_strategy_id` / `parent_content_hash`) 是版本史的血缘边，
  与模板 fork / 社区分享 fork 是不同语义：这里锚的是「同一作者草稿谱系」。

图校验镜像前端 graphLogic.ts（同一套 B6 规则，前后端一致，防「前端拦后端漏」）：
  ① 必填 in 端口未连 → warn
  ② exec 入口未经 Final Risk Gate（来源 dt≠approvedPortfolio）→ error（违反 B6）
  ③ 连线 compat=bad → error
校验是【无副作用】纯函数，不下单、不动钱、不碰 OrderGuard —— 它只读图、出诊断。
"""

from __future__ import annotations

from typing import Any

from ..lineage import content_hash

# B6：执行入口必须消费 Final Risk Gate 的产物。Gate 输出的数据类型 == approvedPortfolio。
# 与前端 graphLogic.ts compat()/validateGraph() 同一常量口径（单一真值，禁分叉）。
EXEC_ROLE = "exec"
APPROVED_PORTFOLIO_DT = "approvedPortfolio"

# compat() 的语义映射（与 graphLogic.ts ADAPT / WARN 逐字对齐）。
_ADAPT: dict[str, list[str]] = {
    "modelScore": ["signalIntent"],
    "factorPanel": ["modelScore"],
    "panel": ["factorPanel"],
}
_WARN: dict[str, list[str]] = {
    "signalIntent": ["targetPortfolio"],
    "targetPortfolio": ["signalIntent"],
}


def _port_of(node: dict[str, Any] | None, port_id: str, direction: str) -> dict[str, Any] | None:
    if not node:
        return None
    arr = node.get("outs" if direction == "out" else "ins") or []
    for p in arr:
        if isinstance(p, dict) and p.get("id") == port_id:
            return p
    return None


def compat(out_port: dict[str, Any] | None, in_port: dict[str, Any] | None) -> dict[str, str]:
    """端口兼容性（连线门 · B6 第三层）。返回 {s, reason}，与前端 compat() 一致。

    role==='exec' 且来源 dt≠approvedPortfolio → bad（执行入口必须经 Final Risk Gate）。
    """

    if not out_port or not in_port:
        return {"s": "?", "reason": "未知"}
    if in_port.get("role") == EXEC_ROLE and out_port.get("dt") != APPROVED_PORTFOLIO_DT:
        return {"s": "bad", "reason": "执行入口必须经 Final Risk Gate（B6），不可绕过"}

    out_dt = out_port.get("dt")
    in_dt = in_port.get("dt")
    out_freq = out_port.get("freq") or ""
    in_freq = in_port.get("freq") or ""
    if out_dt == in_dt:
        if out_freq and in_freq and out_freq != in_freq and out_freq != "—" and in_freq != "—":
            if out_freq == "D" and in_freq == "W":
                return {"s": "adapt", "reason": "日频→周频，需 Resample 聚合"}
            return {"s": "warn", "reason": f"频率不一致：{out_freq}→{in_freq}"}
        return {"s": "ok", "reason": "类型与频率一致"}
    if in_dt in _ADAPT.get(out_dt, []):
        return {"s": "adapt", "reason": f"可经适配节点转换 {out_dt}→{in_dt}"}
    if in_dt in _WARN.get(out_dt, []):
        return {"s": "warn", "reason": "语义相近但不应直接相连"}
    return {"s": "bad", "reason": f"类型不兼容：{out_dt} → {in_dt}"}


def validate_graph(nodes: list[dict[str, Any]] | dict[str, Any], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """图校验（B6 第二层 + 必填端口 + 连线兼容性）。无副作用纯函数。

    入参 nodes 可为 list[node] 或 {id: node}；edges 为 list[edge]。
    返回 {ok, errors:[...], warnings:[...]}（每条 {nodeId?, text}）。ok = len(errors)==0。
    """

    node_map: dict[str, dict[str, Any]] = {}
    if isinstance(nodes, dict):
        node_map = {str(k): v for k, v in nodes.items() if isinstance(v, dict)}
    else:
        for n in nodes or []:
            if isinstance(n, dict) and n.get("id") is not None:
                node_map[str(n["id"])] = n

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    edges = [e for e in (edges or []) if isinstance(e, dict)]

    # 入边索引：to.node → 已连 in 端口集合。
    connected_in: dict[str, set[str]] = {}
    for e in edges:
        to = e.get("to") or {}
        tnode, tport = to.get("node"), to.get("port")
        if tnode is None or tport is None:
            continue
        connected_in.setdefault(str(tnode), set()).add(str(tport))

    # ① 必填端口未连 → warn。
    for nid, n in node_map.items():
        conn = connected_in.get(nid, set())
        for p in n.get("ins") or []:
            if not isinstance(p, dict):
                continue
            if p.get("req") and str(p.get("id")) not in conn:
                warnings.append({"nodeId": nid, "text": f"{n.get('title', nid)}：必填端口「{p.get('name')}」未连接"})

    # ② exec 入口必须经 Final Risk Gate（B6）。
    for e in edges:
        to = e.get("to") or {}
        frm = e.get("from") or {}
        to_node = node_map.get(str(to.get("node")))
        to_port = _port_of(to_node, str(to.get("port")), "in")
        if to_port and to_port.get("role") == EXEC_ROLE:
            from_port = _port_of(node_map.get(str(frm.get("node"))), str(frm.get("port")), "out")
            if not from_port or from_port.get("dt") != APPROVED_PORTFOLIO_DT:
                errors.append({
                    "nodeId": str(to.get("node")),
                    "text": "违反 B6：执行入口未经 Final Risk Gate（必须穿过最终风险闸门）",
                })

    # ③ compat=bad 的连线 → error。
    for e in edges:
        frm = e.get("from") or {}
        to = e.get("to") or {}
        out_port = _port_of(node_map.get(str(frm.get("node"))), str(frm.get("port")), "out")
        in_port = _port_of(node_map.get(str(to.get("node"))), str(to.get("port")), "in")
        c = compat(out_port, in_port)
        if c["s"] == "bad":
            errors.append({"nodeId": str(to.get("node")), "text": f"连线不兼容：{c['reason']}"})

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def strategy_content_hash(*, name: str, code: str, asset_class: str) -> str:
    """策略草稿的内容指纹（版本/Fork 身份）——单一身份源经 lineage.content_hash。

    name 进哈希（与 config_hash 不同：策略版本史里改名=新草稿身份，刻意区分），
    code/asset_class 是行为决定项。16 位、canonical_json、NFC 归一，全库同族。
    """

    return content_hash({"name": name, "code": code, "asset_class": asset_class})


__all__ = [
    "APPROVED_PORTFOLIO_DT",
    "EXEC_ROLE",
    "compat",
    "strategy_content_hash",
    "validate_graph",
]
