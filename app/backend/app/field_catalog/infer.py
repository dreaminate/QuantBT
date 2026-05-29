"""数据平台 v2 · 字段映射启发式推断（供 Agent ``data.infer_mapping`` 工具）。

给用户源的陌生列，基于列名与 canonical 词典(id + 别名)做精确/近似匹配，产出**建议**
（不自动落地）。LLM 拿这些种子 + canonical_options 再做最终决策，人工确认后才写映射。
"""

from __future__ import annotations

import difflib
from typing import Any

from .canonical import CANONICAL

_STRUCTURAL = {"ts", "symbol", "market", "interval"}


def _alias_pool() -> dict[str, str]:
    pool: dict[str, str] = {}
    for f in CANONICAL.all():
        pool[f.id.lower()] = f.id
        for a in f.aliases:
            pool[a.lower()] = f.id
    return pool


def infer_mapping(columns: list[str], *, market: str | None = None, sample: dict | None = None) -> list[dict[str, Any]]:
    pool = _alias_pool()
    keys = list(pool.keys())
    out: list[dict[str, Any]] = []
    for col in columns:
        c = str(col)
        if c in _STRUCTURAL:
            out.append({"raw_column": c, "suggested_field_id": c, "is_freeform": False, "confidence": 1.0, "reason": "结构键"})
            continue
        exact = CANONICAL.resolve(c, market)
        if exact:
            out.append({"raw_column": c, "suggested_field_id": exact, "is_freeform": False, "confidence": 1.0, "reason": "命中 canonical id/别名"})
            continue
        m = difflib.get_close_matches(c.lower(), keys, n=1, cutoff=0.84)
        if m:
            fid = pool[m[0]]
            cf = CANONICAL.get(fid)
            # 与 exact 分支一致地做市场过滤：不给某市场推荐它不适用的 canonical 字段
            if cf is not None and cf.applies_to(market):
                out.append({"raw_column": c, "suggested_field_id": fid, "is_freeform": False, "confidence": 0.7, "reason": f"近似匹配 {m[0]} → {fid}（请确认）"})
                continue
        out.append({"raw_column": c, "suggested_field_id": None, "is_freeform": True, "confidence": 0.0, "reason": "词典无对应；建议作 freeform 或登记新 canonical"})
    return out


def infer_mapping_report(
    columns: list[str], *, market: str | None = None, data_kind: str = "ohlcv", sample: dict | None = None
) -> dict[str, Any]:
    return {
        "suggestions": infer_mapping(columns, market=market, sample=sample),
        "canonical_options": CANONICAL.ids(),
        "data_kind": data_kind,  # 回显，供 apply 时透传到正确的 (source, data_kind) 桶（M3）
    }


__all__ = ["infer_mapping", "infer_mapping_report"]
