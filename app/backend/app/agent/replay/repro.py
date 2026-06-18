"""三级可复现分级 + pass^k 严口径度量（T-016 / spine 02 §3.2、§5.2）。

托管 API bitwise 不可达（dossier §8.3）：默认走 DECISION 级（k 次全同到「足以支撑同一下游决策」）。
pass^k 是【严口径】= k 次输出在该级投影下【全同】才算 1.0（非 pass@k 的「至少一次对」）。
诚实边界：pass^k 高 ≠ 正确率高——它只量确定性、不量质量（面板须明示，dossier §6.6/§8.5）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ...lineage.ids import canonical_json

PASS_CARET_K_CAVEAT = (
    "pass^k 是 k 次输出在该级投影下【全同】的严口径确定性度量；"
    "高确定性 ≠ 高正确性（不是质量分）。托管 API 的 bitwise 级不可达，故默认只到 decision 级。"
)


class ReproLevel(str, Enum):
    BITWISE = "bitwise"      # 整段响应逐字节同（仅自托管批不变内核可达，本项目默认不用）
    DECISION = "decision"    # 中低频默认：tool_calls 的 name+arguments 结构全同（足以支撑同一决策）
    SEMANTIC = "semantic"    # 仅 tool 名集合同（措辞/参数可变）


def _project(response: dict[str, Any], level: ReproLevel) -> str:
    """把一条响应投影到某复现级的可比串（同级同投影 = 该级等价）。"""

    tool_calls = response.get("tool_calls") or []
    if level is ReproLevel.BITWISE:
        return canonical_json(response)
    if level is ReproLevel.DECISION:
        # 决策级：tool 调用的 name + 规范化 arguments（措辞 content 不计）
        norm = []
        for c in tool_calls:
            name = c.get("name") or c.get("function", {}).get("name", "")
            args = c.get("arguments") or c.get("function", {}).get("arguments") or "{}"
            norm.append({"name": name, "arguments": _canon_args(args)})
        return canonical_json(norm)
    # SEMANTIC：仅 tool 名集合（排序去重）
    names = sorted({(c.get("name") or c.get("function", {}).get("name", "")) for c in tool_calls})
    return canonical_json(names)


def _canon_args(args: Any) -> Any:
    if isinstance(args, str):
        try:
            import json
            return json.loads(args)
        except Exception:  # noqa: BLE001
            return args
    return args


def pass_caret_k(responses: list[dict[str, Any]], level: ReproLevel) -> float:
    """pass^k 严口径：返回与【最常见投影】一致的比例。k 次全同 → 1.0；分歧 → < 1.0。

    `responses` = 同一节点 k 次采样的 response dict 列表。
    """

    if not responses:
        return 0.0
    projections = [_project(r, level) for r in responses]
    counts: dict[str, int] = {}
    for p in projections:
        counts[p] = counts.get(p, 0) + 1
    return max(counts.values()) / len(projections)


__all__ = ["PASS_CARET_K_CAVEAT", "ReproLevel", "pass_caret_k"]
