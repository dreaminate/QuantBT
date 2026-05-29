"""数据平台 v2 · 字段映射存储。

记录 (source, data_kind) 级别的"原始列 → canonical id（或 freeform id）"显式覆盖。
默认空表 → catalog 回退到 canonical 词典解析；P2 给内置源 seed 映射、P4 由 Agent
``data.infer_mapping`` / ``data.apply_mapping`` 写入用户源的映射。

落 sqlite（生产接 data/community.db；测试用 ":memory:"）。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from .canonical import CANONICAL

_STRUCTURAL = {"ts", "symbol", "market", "interval"}


@dataclass
class FieldMapping:
    source: str
    data_kind: str
    raw_column: str
    field_id: str
    is_freeform: bool = False


def validate_field_id(field_id: str, is_freeform: bool) -> None:
    """写入前校验目标 field_id —— 防止脏 id 进入字段宇宙、把 load_panel 打成 DuplicateError 或产死字段。

    - 必须是合法 Python 标识符（因子表达式引擎用 ast.Name 引用，点号/中文/非法字符引用不到）；
    - 不能是 join/元数据结构键 ts/symbol/market/interval（会与 panel 键重名抛 DuplicateError）；
    - 非 freeform 时必须落在 canonical 受控词典内。
    """
    fid = str(field_id or "")
    if not fid.isidentifier():
        raise ValueError(f"field_id 必须是合法标识符（不能含点号/空格/中文等）: {field_id!r}")
    if fid in _STRUCTURAL:
        raise ValueError(f"field_id 不能是结构键 {sorted(_STRUCTURAL)}: {fid}")
    if not is_freeform and fid not in set(CANONICAL.ids()):
        raise ValueError(f"非 freeform 的 field_id 必须在 canonical 词典内: {fid}")


class FieldMappingStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS field_mappings (
                    source       TEXT NOT NULL,
                    data_kind    TEXT NOT NULL,
                    raw_column   TEXT NOT NULL,
                    field_id     TEXT NOT NULL,
                    is_freeform  INTEGER NOT NULL DEFAULT 0,
                    updated_at   TEXT,
                    PRIMARY KEY (source, data_kind, raw_column)
                )
                """
            )
            self._conn.commit()

    def set(self, mapping: FieldMapping) -> None:
        validate_field_id(mapping.field_id, mapping.is_freeform)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO field_mappings"
                " (source, data_kind, raw_column, field_id, is_freeform, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mapping.source,
                    mapping.data_kind,
                    mapping.raw_column,
                    mapping.field_id,
                    1 if mapping.is_freeform else 0,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.commit()

    def set_many(self, mappings: list[FieldMapping]) -> None:
        for m in mappings:
            self.set(m)

    def get(self, source: str, data_kind: str) -> dict[str, tuple[str, bool]]:
        """返回 {raw_column: (field_id, is_freeform)}。"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT raw_column, field_id, is_freeform FROM field_mappings"
                " WHERE source = ? AND data_kind = ?",
                (source, data_kind),
            )
            return {row[0]: (row[1], bool(row[2])) for row in cur.fetchall()}

    def all(self) -> list[FieldMapping]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT source, data_kind, raw_column, field_id, is_freeform FROM field_mappings"
            )
            return [
                FieldMapping(source=r[0], data_kind=r[1], raw_column=r[2], field_id=r[3], is_freeform=bool(r[4]))
                for r in cur.fetchall()
            ]


__all__ = ["FieldMapping", "FieldMappingStore"]
