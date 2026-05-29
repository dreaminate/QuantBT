"""M2 · 动态资产池包。"""

from __future__ import annotations

from .definition import UniverseDefinition, UniverseRules, universe_presets
from .resolver import UniverseResult, resolve_universe, resolve_universe_series

__all__ = [
    "UniverseDefinition",
    "UniverseRules",
    "universe_presets",
    "UniverseResult",
    "resolve_universe",
    "resolve_universe_series",
]
