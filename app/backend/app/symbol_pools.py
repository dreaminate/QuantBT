from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import SYMBOL_POOLS_DIR


def _normalize_symbol_list(raw: list[Any]) -> list[str]:
    symbols: list[str] = []
    for item in raw:
        for chunk in str(item).replace("，", ",").split(","):
            value = chunk.strip().upper()
            if value:
                symbols.append(value)
    return list(dict.fromkeys(symbols))


def _read_pool(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_symbol_pools(market: str | None = None) -> list[dict[str, Any]]:
    SYMBOL_POOLS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for path in sorted(SYMBOL_POOLS_DIR.glob("*.json")):
        try:
            data = _read_pool(path)
        except (OSError, json.JSONDecodeError):
            continue
        m = data.get("market")
        if market and m != market:
            continue
        pool_id = str(data.get("pool_id") or path.stem)
        symbols = data.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [symbols]
        rows.append(
            {
                "pool_id": pool_id,
                "name": str(data.get("name") or pool_id),
                "market": m,
                "symbol_count": len(symbols) if isinstance(symbols, list) else 0,
            }
        )
    return rows


def load_symbol_pool_symbols(pool_id: str, expected_market: str) -> list[str]:
    path = SYMBOL_POOLS_DIR / f"{pool_id}.json"
    if not path.exists():
        raise RuntimeError(f"Pool not found: {pool_id}")
    data = _read_pool(path)
    if data.get("market") and data.get("market") != expected_market:
        raise RuntimeError("Pool does not belong to the selected market.")
    raw = data.get("symbols") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise RuntimeError("Invalid pool format: symbols must be a list.")
    return _normalize_symbol_list([str(x) for x in raw])
