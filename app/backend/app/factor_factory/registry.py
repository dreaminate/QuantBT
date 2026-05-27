"""M4 · 因子注册表 (内存级 + JSON 落盘)。

因子模型：
- factor_id: 用户/Agent 提供的唯一 id（snake_case）
- version: 自增整数
- formula: 表达式字符串
- author / created_at_utc / description
- lifecycle_state: 与 M11 状态机对接
- params: 表达式自由参数（保留位）
- ic_summary: 最近一次跑出的 IC 简报（可选）
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


LifecycleState = Literal["NEW", "QUALIFIED", "PROBATION", "OBSERVATION", "WARNING", "RETIRED"]


@dataclass
class Factor:
    factor_id: str
    formula: str
    version: int = 1
    author: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    description: str = ""
    lifecycle_state: LifecycleState = "NEW"
    params: dict[str, Any] = field(default_factory=dict)
    ic_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Factor":
        return cls(**data)


class FactorRegistry:
    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = Path(store_path) if store_path else None
        self._items: dict[tuple[str, int], Factor] = {}
        self._lock = threading.Lock()
        if self._store_path and self._store_path.exists():
            self._load()

    @property
    def store_path(self) -> Path | None:
        return self._store_path

    def register(
        self,
        factor_id: str,
        formula: str,
        *,
        author: str = "system",
        description: str = "",
        params: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> Factor:
        with self._lock:
            existing_versions = sorted(v for (fid, v) in self._items if fid == factor_id)
            next_version = (existing_versions[-1] + 1) if existing_versions and not overwrite else (
                existing_versions[-1] if existing_versions and overwrite else 1
            )
            factor = Factor(
                factor_id=factor_id,
                formula=formula,
                version=next_version,
                author=author,
                description=description,
                params=params or {},
            )
            self._items[(factor_id, factor.version)] = factor
            if overwrite and (factor_id, next_version) in self._items and existing_versions:
                # 覆盖时清掉旧条目
                pass
        self._persist()
        return factor

    def get(self, factor_id: str, version: int | None = None) -> Factor:
        keys = [k for k in self._items if k[0] == factor_id]
        if not keys:
            raise KeyError(f"未注册的因子: {factor_id}")
        if version is None:
            version = max(k[1] for k in keys)
        if (factor_id, version) not in self._items:
            raise KeyError(f"factor_id={factor_id} version={version} 未注册")
        return self._items[(factor_id, version)]

    def list(self) -> list[Factor]:
        return sorted(self._items.values(), key=lambda f: (f.factor_id, f.version))

    def update_state(self, factor_id: str, version: int, state: LifecycleState) -> Factor:
        factor = self.get(factor_id, version)
        factor.lifecycle_state = state
        self._persist()
        return factor

    def set_ic_summary(self, factor_id: str, version: int, summary: dict[str, Any]) -> Factor:
        factor = self.get(factor_id, version)
        factor.ic_summary = summary
        self._persist()
        return factor

    def _persist(self) -> None:
        if not self._store_path:
            return
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [f.to_dict() for f in self.list()]
        self._store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        assert self._store_path is not None
        items = json.loads(self._store_path.read_text(encoding="utf-8"))
        for data in items:
            factor = Factor.from_dict(data)
            self._items[(factor.factor_id, factor.version)] = factor


__all__ = ["Factor", "FactorRegistry", "LifecycleState"]
