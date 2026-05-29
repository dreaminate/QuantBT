"""数据平台 v2 · 字段目录包。

- ``contract``：量化流程数据访问契约（WidePanel / FieldRequirement / PanelResult）。
- ``canonical``：canonical 受控字段词典。
- ``mapping``：(source, data_kind) 级原始列→字段 id 映射存储。
- ``catalog``：FieldCatalog —— 以 DatasetRegistry 为真相源的字段目录 + load_panel。

详见 docs/plans/v2-data-platform.md（§2.5 扩展性契约 / §3 P1）。
"""

from __future__ import annotations

from .canonical import CANONICAL, CanonicalField, CanonicalRegistry
from .catalog import FieldCatalog, FieldEntry, FieldUniverse, SourceFilter
from .contract import DatasetInfo, FieldRequirement, FileRef, PanelResult, WidePanel
from .intake import register_official_dataset
from .mapping import FieldMapping, FieldMappingStore
from .sources import DatasetSource, InventoryDatasetSource, RegistryDatasetSource

__all__ = [
    "CANONICAL",
    "CanonicalField",
    "CanonicalRegistry",
    "DatasetInfo",
    "DatasetSource",
    "FieldCatalog",
    "FieldEntry",
    "FieldMapping",
    "FieldMappingStore",
    "FieldRequirement",
    "FieldUniverse",
    "FileRef",
    "InventoryDatasetSource",
    "PanelResult",
    "RegistryDatasetSource",
    "SourceFilter",
    "WidePanel",
    "register_official_dataset",
]
