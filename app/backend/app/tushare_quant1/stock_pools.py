"""对齐 quant1 的 resolve_stock_pool 签名，底层使用 qb 的 symbol_pools JSON。"""

from __future__ import annotations

from typing import Any

from .project_paths import ProjectPaths


def resolve_stock_pool(
    paths: ProjectPaths,
    *,
    pool_id: str | None = None,
    preset_name: str | None = None,
    market: str | None = None,
) -> dict[str, Any] | None:
    del paths
    from ..symbol_pools import list_symbol_pools, load_symbol_pool_symbols

    m = market or "stocks_cn"
    if pool_id:
        try:
            syms = load_symbol_pool_symbols(pool_id, m)
            return {"pool_id": pool_id, "market": m, "symbols": syms, "editable": True}
        except RuntimeError:
            pass
    key = (preset_name or "").strip().lower()
    if key:
        for row in list_symbol_pools(m):
            pid = str(row.get("pool_id") or "").strip().lower()
            name = str(row.get("name") or "").strip().lower()
            if key == pid or key == name:
                try:
                    syms = load_symbol_pool_symbols(str(row["pool_id"]), m)
                    return {"pool_id": row["pool_id"], "market": m, "symbols": syms, "editable": True}
                except RuntimeError:
                    return None
    return None
