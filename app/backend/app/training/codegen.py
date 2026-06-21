"""结构化 spec → 训练脚本代码。

"训练台本质是跑代码"：结构化的一键训练，其实也是先把 spec 渲染成脚本再跑——
和 agent 直接生成代码同一条执行路径（runner 全功率进程）。这样 ML/DL 不再硬分，
都是"生成代码 → 跑"。

`spec_to_code(spec)` 接收 request.to_dict()，避免与 service 循环 import。
脚本从 `QUANTBT_PANEL_PATH`(parquet) 读数据、`QUANTBT_JOB_DIR` 落产物，
最后 `emit(...)` 回吐与 TrainResult.to_dict 同形的结果。
"""

from __future__ import annotations

from typing import Any

from ..models.catalog import get_model_card

_HEADER = '''import os
from pathlib import Path

import pandas as pd

from app.training.lib import emit, predict_with  # noqa: F401

panel = pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])
job_dir = Path(os.environ["QUANTBT_JOB_DIR"])
'''

# 已实现 torch 训练模板的 DL 架构（与 app.models.dl.architectures 对齐）；
# 卡片可收录更多 DL（tft/nbeats…），但未在此集合内 → codegen 明确提示模板排队。
_RUNNABLE_DL = {"lstm", "gru", "alstm", "mlp", "tcn", "transformer", "tft", "nbeats", "nhits", "deepar"}


def spec_to_code(spec: dict[str, Any]) -> str:
    card = get_model_card(spec["model"])
    if card.family == "dl":
        return _dl_code(spec)
    return _ml_code(spec)


def _ml_code(spec: dict[str, Any]) -> str:
    body = f'''
from app.models.training import ModelSpec, train_model

model_spec = ModelSpec(
    task={spec["task"]!r},
    model={spec["model"]!r},
    feature_cols={list(spec["feature_cols"])!r},
    label_col={spec.get("label_col", "label")!r},
    cv_scheme={spec.get("cv_scheme", "purged_kfold")!r},
    n_splits={int(spec.get("n_splits", 5))},
    embargo_pct={float(spec.get("embargo_pct", 0.01))},
    walk_forward_train={int(spec.get("walk_forward_train", 252))},
    walk_forward_test={int(spec.get("walk_forward_test", 63))},
    walk_forward_embargo={int(spec.get("walk_forward_embargo", 5))},
    hyperparams={dict(spec.get("hyperparams") or {})!r},
    group_col={spec.get("group_col")!r},
)
res = train_model(model_spec, panel, artifact_dir=job_dir)
emit(res.to_dict())
'''
    return _HEADER + body


def _dl_code(spec: dict[str, Any]) -> str:
    model = spec["model"]
    if model not in _RUNNABLE_DL:
        raise NotImplementedError(
            f"DL 模型 {model} 的训练模板排队中（已实现: {sorted(_RUNNABLE_DL)}）；卡片已收录，"
            f"实现该架构只需在 app/models/dl/architectures.py 加一个 nn.Module。"
        )
    hp = dict(spec.get("hyperparams") or {})
    body = f'''
from app.models.dl import train_dl

res = train_dl(
    panel,
    arch={model!r},
    feature_cols={list(spec["feature_cols"])!r},
    label_col={spec.get("label_col", "label")!r},
    job_dir=job_dir,
    task={spec["task"]!r},
    symbol_col={spec.get("symbol_col", "symbol")!r},
    hyperparams={hp!r},
)
emit(res)
'''
    return _HEADER + body


# ============================================================
# 构建台图 → nn.Module 代码（D-DESK-F1B 子集 (a)：线性链）
# ============================================================
#
# 【M6 硬约束】主进程**绝不** import torch / 实例化 nn.Module 跑形状校验。
# 这里只做**纯字符串/AST 拼装**：拓扑排序 → 形状推断（纯整数算术）→ 拼 `nn.Module` 源文本。
# 编译/实例化/训练必须经 `runner.run_code` 子进程（与 _dl_code 同一执行路径）。
# 本卡只产「图→代码字符串」预览；子进程真编译训练入作业台属后续里程碑。
#
# 子集 (a)：input → {linear|conv1d|lstm|gru|dropout|relu|gelu|tanh} ... → head → output，
#   无分支、无嵌套（恰好 ≤1 入 ≤1 出）。覆盖 90% 树/序列模型、形状推断闭合、风险最低。
#   (b) 分支、(c) 机制嵌套留后续。

# 拼装期支持的原子（纯 string emit；不 import torch）。
_GRAPH_ATOMS = {"input", "linear", "conv1d", "lstm", "gru", "dropout", "relu", "gelu", "tanh", "head", "output"}
# 激活/正则等无参形状透传层（不改最后一维）。
_PASSTHROUGH = {"dropout", "relu", "gelu", "tanh"}


class GraphCodegenError(ValueError):
    """图结构非法（非线性链 / 缺 input/output / 形状不自洽 / 含未支持原子）。"""


def _topo_linear_chain(nodes: dict[str, dict[str, Any]], edges: list[Any]) -> list[str]:
    """校验是单条线性链并返回拓扑顺序的 node id 列表。

    线性链定义：每节点入度 ≤1、出度 ≤1；恰好一个入度 0（input）、一个出度 0（output）；
    无环、无分叉、所有节点连通成一条。任何分支/多入多出 → GraphCodegenError（子集 (a) 不接）。
    """
    indeg: dict[str, int] = {nid: 0 for nid in nodes}
    outdeg: dict[str, int] = {nid: 0 for nid in nodes}
    nxt: dict[str, str] = {}
    for e in edges:
        src, dst = _edge_ends(e)
        if src not in nodes or dst not in nodes:
            raise GraphCodegenError(f"边引用了不存在的节点: {src}→{dst}")
        outdeg[src] += 1
        indeg[dst] += 1
        nxt[src] = dst
    for nid in nodes:
        if indeg[nid] > 1 or outdeg[nid] > 1:
            raise GraphCodegenError(
                f"节点 {nid} 入度{indeg[nid]}/出度{outdeg[nid]} —— 构建台 codegen 当前仅支持线性链（无分支/无多入多出）"
            )
    heads = [nid for nid in nodes if indeg[nid] == 0]
    tails = [nid for nid in nodes if outdeg[nid] == 0]
    if len(heads) != 1 or len(tails) != 1:
        raise GraphCodegenError(
            f"线性链须恰好一个起点/一个终点（现起点 {len(heads)} 终点 {len(tails)}）"
        )
    order: list[str] = []
    cur: str | None = heads[0]
    seen: set[str] = set()
    while cur is not None:
        if cur in seen:
            raise GraphCodegenError("图含环，无法拓扑排序")
        seen.add(cur)
        order.append(cur)
        cur = nxt.get(cur)
    if len(order) != len(nodes):
        raise GraphCodegenError("图不连通：存在未接入主链的孤立节点")
    return order


def _edge_ends(e: Any) -> tuple[str, str]:
    """边支持两种形态：[src, dst] 或 {from:{node}, to:{node}}（前端 EdgeView）。"""
    if isinstance(e, (list, tuple)) and len(e) >= 2:
        return str(e[0]), str(e[1])
    if isinstance(e, dict):
        frm = e.get("from")
        to = e.get("to")
        src = frm.get("node") if isinstance(frm, dict) else frm
        dst = to.get("node") if isinstance(to, dict) else to
        if src is not None and dst is not None:
            return str(src), str(dst)
    raise GraphCodegenError(f"无法解析边: {e!r}")


def _node_type(n: dict[str, Any]) -> str:
    """节点类型（兼容前端 cat/title/type 多写法 → 规整成原子名）。"""
    t = (n.get("type") or n.get("atom") or n.get("title") or n.get("cat") or "").strip().lower()
    aliases = {"in": "input", "out": "output", "fc": "linear", "dense": "linear"}
    return aliases.get(t, t)


def graph_to_code(graph: dict[str, Any]) -> str:
    """图(bdNodes/bdEdges) → nn.Module 源文本（线性链子集 · 纯字符串拼装、主进程不碰 torch）。

    形状推断为**纯整数算术**（无 torch）：从 input 的 features 维起，逐层按 params 推下一维。
    返回的脚本与 _dl_code 同执行路径——真编译/训练仍唯经 runner.run_code 子进程。
    """
    raw_nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    nodes: dict[str, dict[str, Any]] = {}
    for n in raw_nodes:
        nid = str(n.get("id") or "")
        if not nid:
            raise GraphCodegenError("节点缺 id")
        nodes[nid] = n
    if not nodes:
        raise GraphCodegenError("空图：至少需要 input→…→output")

    order = _topo_linear_chain(nodes, edges)
    if _node_type(nodes[order[0]]) != "input":
        raise GraphCodegenError("线性链起点必须是 input 节点")
    if _node_type(nodes[order[-1]]) != "output":
        raise GraphCodegenError("线性链终点必须是 output 节点")

    # 形状推断：从 input.features 起逐层算（纯整数）。
    in_node = nodes[order[0]]
    dim = int(in_node.get("features") or (in_node.get("params") or {}).get("features") or 0)
    if dim <= 0:
        raise GraphCodegenError("input 节点须声明 features(>0)")

    init_lines: list[str] = []
    fwd_lines: list[str] = []
    shape_trace: list[str] = [f"# input: [N, {dim}]"]
    li = 0
    for nid in order[1:-1]:  # 跳过 input/output 端
        n = nodes[nid]
        nt = _node_type(n)
        p = n.get("params") or {}
        if nt not in _GRAPH_ATOMS:
            raise GraphCodegenError(f"节点 {nid} 类型 {nt!r} 不在支持集合 {sorted(_GRAPH_ATOMS)}（子集 (a)）")
        if nt in ("linear", "head"):
            out = int(p.get("out") or p.get("out_features") or (1 if nt == "head" else 0))
            if out <= 0:
                raise GraphCodegenError(f"{nt} 节点 {nid} 须声明 out(>0)")
            li += 1
            init_lines.append(f"        self.l{li} = nn.Linear({dim}, {out})")
            fwd_lines.append(f"        x = self.l{li}(x)  # [N, {out}]")
            dim = out
            shape_trace.append(f"# {nt}: [N, {dim}]")
        elif nt == "conv1d":
            out = int(p.get("out_channels") or p.get("out") or 0)
            k = int(p.get("kernel_size") or p.get("kernel") or 3)
            if out <= 0:
                raise GraphCodegenError(f"conv1d 节点 {nid} 须声明 out_channels(>0)")
            li += 1
            init_lines.append(
                f"        self.l{li} = nn.Conv1d({dim}, {out}, kernel_size={k}, padding={k // 2})"
            )
            fwd_lines.append(f"        x = self.l{li}(x)  # [N, {out}, T]")
            dim = out
            shape_trace.append(f"# conv1d: [N, {dim}, T]")
        elif nt in ("lstm", "gru"):
            hidden = int(p.get("hidden") or p.get("hidden_size") or 0)
            if hidden <= 0:
                raise GraphCodegenError(f"{nt} 节点 {nid} 须声明 hidden(>0)")
            li += 1
            cls = "LSTM" if nt == "lstm" else "GRU"
            init_lines.append(
                f"        self.l{li} = nn.{cls}({dim}, {hidden}, batch_first=True)"
            )
            fwd_lines.append(f"        x, _ = self.l{li}(x)  # [N, T, {hidden}]")
            fwd_lines.append(f"        x = x[:, -1, :]  # 取末步 → [N, {hidden}]")
            dim = hidden
            shape_trace.append(f"# {nt}: [N, {dim}]")
        else:  # passthrough（dropout/relu/gelu/tanh）：形状不变
            li += 1
            mod = {"dropout": f"nn.Dropout({float(p.get('p', 0.1))})",
                   "relu": "nn.ReLU()", "gelu": "nn.GELU()", "tanh": "nn.Tanh()"}[nt]
            init_lines.append(f"        self.l{li} = {mod}")
            fwd_lines.append(f"        x = self.l{li}(x)  # [N, {dim}] (passthrough)")
            shape_trace.append(f"# {nt}: [N, {dim}]")

    init_block = "\n".join(init_lines) or "        pass"
    fwd_block = "\n".join(fwd_lines) or "        pass"
    trace_block = "\n".join(shape_trace)
    return (
        "# 构建台图 → nn.Module（线性链子集 · 纯字符串拼装）\n"
        "# 【M6】DL 编译/实例化/训练走全功率子进程跑 torch；主进程绝不 import torch。\n"
        f"{trace_block}\n"
        "import torch.nn as nn\n\n"
        "class GraphModel(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        f"{init_block}\n\n"
        "    def forward(self, x):\n"
        f"{fwd_block}\n"
        "        return x\n"
    )


__all__ = ["GraphCodegenError", "graph_to_code", "spec_to_code"]
