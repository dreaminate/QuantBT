"""v0.8.4 · Glossary 词条 loader + Pydantic schema + 校验。

提供：
- GlossaryTerm dataclass (frontmatter + 四段 L1-L4)
- GlossaryRegistry: in-memory + 文件加载 + alias 索引 + related 闭环检查
- validate_glossary_dir(): CI 用，命令行版在 scripts/validate_glossary.py

设计：
- 文件名 = slug（snake_case 英文）
- 正文必须有 ## L1 / ## L2 / ## L3 / ## L4 四段
- frontmatter 必填 term/display/aliases/level/category/sources/related
"""

from __future__ import annotations

from .loader import (
    GlossaryError,
    GlossaryFrontmatter,
    GlossaryRegistry,
    GlossaryTerm,
    load_glossary_dir,
    parse_glossary_md,
    validate_glossary_dir,
)

__all__ = [
    "GlossaryError",
    "GlossaryFrontmatter",
    "GlossaryRegistry",
    "GlossaryTerm",
    "load_glossary_dir",
    "parse_glossary_md",
    "validate_glossary_dir",
]
