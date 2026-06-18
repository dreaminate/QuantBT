"""受控翻译层 · LLM 输出不直接当决策（T-016 / spine 02 §3.3，dossier §8.4「确定地错」）。

LLM 只产受 schema 约束的结构化对象、**不持决策权**。翻译层在 tool_calls 派发前夹一道：
schema 校验 + 语义不变量（如 leverage 不超注入上限）。schema 合规但语义越界 → `human_confirm_required`
（**不派发**，挂起等审批门），而非让「确定地错」被确定性放大成真副作用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

TranslationStatus = Literal["ok", "schema_invalid", "human_confirm_required"]

def _is_leverage_key(key: str) -> bool:
    """归一后匹配杠杆字段名（含 camelCase / 加词变体；不误伤 relevance 等）。"""

    norm = re.sub(r"[^a-z0-9]", "", str(key).lower())   # 去下划线/驼峰大小写
    return "leverage" in norm or norm in {"lev", "levmax", "maxlev"}


def _as_number(v: Any) -> float | None:
    """把数值/数值字符串转 float（排除 bool，避免 True→1.0 类型混淆）；失败返 None。"""

    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


@dataclass
class TranslationResult:
    status: TranslationStatus
    tool_calls: list[dict[str, Any]]
    reason: str = ""


def _parse_args(call: dict[str, Any]) -> dict[str, Any] | None:
    raw = call.get("arguments") or call.get("function", {}).get("arguments") or "{}"
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {"_value": v}
        except json.JSONDecodeError:
            return None
    return None


def _max_leverage_in(args: dict[str, Any]) -> float | None:
    """递归找 args 里最大的杠杆值。鲁棒于：字符串数值("30")、列表([10,30])、camelCase/加词变体。

    复核 #8/#9/#10：旧实现只认 dict-key 处的 int/float 标量 → 字符串/列表/变体名全绕过。
    """

    found: list[float] = []

    def harvest(value: Any) -> None:
        """从一个【杠杆字段的值】里收所有数值（标量/字符串/列表元素）。"""
        if isinstance(value, (list, tuple)):
            for x in value:
                n = _as_number(x)
                if n is not None:
                    found.append(n)
        else:
            n = _as_number(value)
            if n is not None:
                found.append(n)

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if _is_leverage_key(k):
                    harvest(v)        # 杠杆键的值无论标量/字符串/列表都收
                walk(v)               # 仍继续下钻（嵌套 constraints + 多层）
        elif isinstance(o, (list, tuple)):
            for x in o:
                walk(x)

    walk(args)
    return max(found) if found else None


class ControlledTranslator:
    def __init__(self, *, leverage_cap: float | None = None, known_tools: set[str] | None = None) -> None:
        self._leverage_cap = leverage_cap
        self._known_tools = known_tools

    def translate(self, tool_calls: list[dict[str, Any]] | None) -> TranslationResult:
        calls = tool_calls or []
        for call in calls:
            name = call.get("name") or call.get("function", {}).get("name", "")
            args = _parse_args(call)
            if args is None:
                return TranslationResult("schema_invalid", calls, f"tool_call {name!r} 参数非合法 JSON")
            if self._known_tools is not None and name and name not in self._known_tools:
                return TranslationResult("schema_invalid", calls, f"未知 tool {name!r}（不在 schema 白名单）")
            if self._leverage_cap is not None:
                lev = _max_leverage_in(args)
                if lev is not None and lev > self._leverage_cap:
                    return TranslationResult(
                        "human_confirm_required", calls,
                        f"tool {name!r} 请求杠杆 {lev} 超注入上限 {self._leverage_cap}：schema 合规但语义越界，"
                        f"挂起等人工确认（绝不直接派发，防确定地错被放大）",
                    )
        return TranslationResult("ok", calls)


__all__ = ["ControlledTranslator", "TranslationResult", "TranslationStatus"]
