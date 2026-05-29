"""数据平台 v2 · 量化流程数据访问契约（见 docs/plans/v2-data-platform.md §2.5）。

量化流程所有模块（特征/标签/模型/信号/组合/执行/评估，以及未来新增模块）都通过
这层契约拿数据：声明 ``FieldRequirement`` → ``FieldCatalog.load_panel`` 解析 →
得到 ``WidePanel`` + ``manifest``（每个字段来自哪个源）+ ``missing``（缺哪些）。

模块**永不 import connector、永不硬编码列名**——这是"扩展性脊梁"，一经定稿只扩不破。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

# 量化流程的通用数据货币：ts × symbol 宽表，列 = 任意 canonical + freeform 字段。
WidePanel = pl.DataFrame


@dataclass
class FieldRequirement:
    """一个量化模块声明它需要的字段。"""

    canonical_ids: list[str]                  # 必需字段（canonical 或 freeform id）
    market: str
    interval: str
    optional_ids: list[str] = field(default_factory=list)  # 可选字段，缺失不报错
    derive: bool = True                       # 允许派生（如 amount 缺 → close*volume）
    symbols: list[str] | None = None          # None=全部 symbol

    def all_ids(self) -> list[str]:
        out: list[str] = []
        for fid in [*self.canonical_ids, *self.optional_ids]:
            if fid not in out:
                out.append(fid)
        return out


@dataclass
class PanelResult:
    """``load_panel`` 的返回。"""

    panel: WidePanel
    manifest: dict[str, str]                   # field_id -> source_name
    missing: list[str]                         # 必需字段里没解析到的（列缺失 / 全 null / 空 panel）
    optional_missing: list[str] = field(default_factory=list)
    row_count: int = 0                         # panel 行数；ok 不仅看列在、也隐含 row_count>0

    @property
    def ok(self) -> bool:
        return not self.missing


@dataclass
class FileRef:
    """数据集里的一个物理文件。``symbol`` 用于"单 symbol 文件、symbol 在文件名/分区而非列"的情况。"""

    path: str
    symbol: str | None = None


@dataclass
class DatasetInfo:
    """一个逻辑数据集（一个 (source, market, data_kind, interval)）及其物理文件。"""

    dataset_id: str
    source_name: str
    market: str | None = None
    interval: str | None = None
    data_kind: str | None = None
    columns: list[str] = field(default_factory=list)
    files: list[FileRef] = field(default_factory=list)

    @property
    def file_paths(self) -> list[str]:
        return [f.path for f in self.files]


__all__ = ["WidePanel", "FieldRequirement", "PanelResult", "FileRef", "DatasetInfo"]
