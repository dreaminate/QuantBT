"""v0.8.4 · Glossary 词条 markdown 加载 + Pydantic schema + 校验。

文件布局：
  docs/glossary/<slug>.md       — 词条文件
  docs/glossary/_index.yaml     — slug 清单（30 条 baseline）
  docs/glossary/_SCHEMA.md      — 给作者看的规范

约束：
- 文件名 = slug (snake_case 英文)
- YAML frontmatter 必填: term/display/aliases/level/category/sources/related
- 正文必须按顺序含 ## L1 ## L2 ## L3 ## L4 四段
- related 必须指向存在的 slug（闭环校验）

使用：
  from app.glossary import load_glossary_dir, validate_glossary_dir
  reg = load_glossary_dir(Path("docs/glossary"))
  term = reg.get("sharpe_ratio")    # → GlossaryTerm
  term = reg.lookup("夏普")          # alias 命中
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class GlossaryError(Exception):
    """词条结构 / frontmatter / related 闭环错误。"""


VALID_LEVELS = {"beginner", "intermediate", "advanced"}
VALID_CATEGORIES = {"metric", "factor", "model", "risk", "execution", "data", "portfolio"}

# 正文必须按顺序匹配的四段标题
_SECTION_HEADERS = ("## L1", "## L2", "## L3", "## L4")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class GlossaryFrontmatter(BaseModel):
    """词条 frontmatter Pydantic schema。"""

    model_config = ConfigDict(extra="forbid")

    term: str
    display: str
    aliases: list[str] = Field(default_factory=list)
    level: str
    category: str
    formula_latex: str | None = None
    unit: str | None = None
    typical_range: list[float | int] | None = None
    sources: list[str] = Field(min_length=1)
    related: list[str] = Field(default_factory=list)

    @field_validator("term")
    @classmethod
    def _term_slug(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c == "_" for c in v):
            raise ValueError("term 必须是 snake_case 英文")
        return v

    @field_validator("level")
    @classmethod
    def _level_in_set(cls, v: str) -> str:
        if v not in VALID_LEVELS:
            raise ValueError(f"level 必须 ∈ {sorted(VALID_LEVELS)}")
        return v

    @field_validator("category")
    @classmethod
    def _category_in_set(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category 必须 ∈ {sorted(VALID_CATEGORIES)}")
        return v

    @field_validator("typical_range")
    @classmethod
    def _range_two_elements(cls, v: list[float | int] | None) -> list[float | int] | None:
        if v is None:
            return v
        if len(v) != 2 or v[0] >= v[1]:
            raise ValueError("typical_range 必须为 [lo, hi] 且 lo < hi")
        return v


@dataclass
class GlossaryTerm:
    """已加载且通过 schema 校验的词条。"""

    slug: str
    frontmatter: GlossaryFrontmatter
    l1: str
    l2: str
    l3: str
    l4: str
    source_path: str = ""

    @property
    def display(self) -> str:
        return self.frontmatter.display

    @property
    def aliases(self) -> list[str]:
        return list(self.frontmatter.aliases)

    @property
    def related(self) -> list[str]:
        return list(self.frontmatter.related)

    @property
    def levels_available(self) -> list[str]:
        out: list[str] = []
        if self.l1.strip(): out.append("l1")
        if self.l2.strip(): out.append("l2")
        if self.l3.strip(): out.append("l3")
        if self.l4.strip(): out.append("l4")
        return out

    def to_dict(self, *, level: str | None = None) -> dict[str, Any]:
        """level=None 返回全部四段；level='l2' 返回 l1+l2；以此渐进披露。"""
        fm = self.frontmatter.model_dump(exclude_none=True)
        out: dict[str, Any] = {
            "slug": self.slug,
            "frontmatter": fm,
            "levels_available": self.levels_available,
        }
        depth_order = ["l1", "l2", "l3", "l4"]
        limit = depth_order.index(level) + 1 if level in depth_order else 4
        for i, key in enumerate(depth_order):
            if i < limit:
                out[key] = getattr(self, key)
        return out


@dataclass
class GlossaryRegistry:
    """in-memory 词条仓库 + alias 索引 + related 闭环检查。"""

    terms: dict[str, GlossaryTerm] = field(default_factory=dict)
    _alias_index: dict[str, str] = field(default_factory=dict)  # lowercased alias → slug

    def add(self, term: GlossaryTerm) -> None:
        if term.slug in self.terms:
            raise GlossaryError(f"重复 slug: {term.slug}")
        self.terms[term.slug] = term
        # 索引 slug + display + aliases
        keys = [term.slug, term.frontmatter.display] + term.aliases
        for key in keys:
            k = (key or "").strip().lower()
            if k and k not in self._alias_index:
                self._alias_index[k] = term.slug

    def __len__(self) -> int:
        return len(self.terms)

    def __iter__(self) -> Iterable[GlossaryTerm]:
        return iter(self.terms.values())

    def get(self, slug: str) -> GlossaryTerm | None:
        return self.terms.get(slug)

    def lookup(self, query: str) -> GlossaryTerm | None:
        """slug / display / alias 不区分大小写命中。"""
        if not query:
            return None
        slug = self._alias_index.get(query.strip().lower())
        if slug is None:
            return None
        return self.terms.get(slug)

    def list_summary(self) -> list[dict[str, Any]]:
        """`/api/glossary` 用：返回 slug + display + level + category + aliases。"""
        return [
            {
                "slug": t.slug,
                "display": t.display,
                "level": t.frontmatter.level,
                "category": t.frontmatter.category,
                "aliases": t.aliases,
                "levels_available": t.levels_available,
            }
            for t in self.terms.values()
        ]

    def validate_related_closure(self) -> list[str]:
        """检查 related 引用是否都指向已存在的 slug。返回违规列表。"""
        violations: list[str] = []
        for t in self.terms.values():
            for ref in t.related:
                if ref not in self.terms:
                    violations.append(f"{t.slug}.related → {ref} (不存在)")
        return violations


# ============================================================
# parser
# ============================================================


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise GlossaryError("缺少 YAML frontmatter (--- ... ---)")
    fm_raw, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as exc:
        raise GlossaryError(f"frontmatter YAML 解析失败: {exc}") from exc
    if not isinstance(fm, dict):
        raise GlossaryError("frontmatter 必须是 dict")
    return fm, body


def _extract_section(body: str, header: str, next_headers: list[str]) -> str:
    """按 `## L1` 提取段落，到下一个 ## L* 或文件结束为止。"""
    pattern = rf"(?ms)^{re.escape(header)}\b.*?\n(.*?)(?=^{'|'.join('## ' + h.split()[1] for h in [hh + ' ' for hh in next_headers])}|\Z)"
    # 上面的多 alt 比较脆弱；改用简单"找下一个 ## L 标题"的方式
    start_re = re.compile(rf"(?m)^{re.escape(header)}\b[^\n]*\n")
    m = start_re.search(body)
    if not m:
        return ""
    rest = body[m.end():]
    # 找下一个 ## L<digit> 或 EOF
    next_re = re.compile(r"(?m)^## L\d\b")
    nm = next_re.search(rest)
    return (rest[: nm.start()] if nm else rest).strip()


def parse_glossary_md(path: Path) -> GlossaryTerm:
    """读 markdown 文件 → GlossaryTerm。raise GlossaryError 当违反 schema。"""

    text = path.read_text(encoding="utf-8")
    fm_dict, body = _split_frontmatter(text)
    try:
        fm = GlossaryFrontmatter(**fm_dict)
    except Exception as exc:  # noqa: BLE001
        raise GlossaryError(f"{path.name} frontmatter 校验失败: {exc}") from exc

    # 校验四段标题按顺序出现
    last_pos = -1
    for header in _SECTION_HEADERS:
        idx = body.find(header)
        if idx < 0:
            raise GlossaryError(f"{path.name} 缺少段落 {header}")
        if idx < last_pos:
            raise GlossaryError(f"{path.name} 段落 {header} 必须按 L1→L4 顺序出现")
        last_pos = idx

    l1 = _extract_section(body, "## L1", [])
    l2 = _extract_section(body, "## L2", [])
    l3 = _extract_section(body, "## L3", [])
    l4 = _extract_section(body, "## L4", [])

    # 文件名 = slug = frontmatter.term
    expected_slug = path.stem
    if fm.term != expected_slug:
        raise GlossaryError(f"{path.name}: frontmatter.term={fm.term!r} ≠ 文件名 stem={expected_slug!r}")

    return GlossaryTerm(
        slug=expected_slug,
        frontmatter=fm,
        l1=l1,
        l2=l2,
        l3=l3,
        l4=l4,
        source_path=str(path),
    )


def load_glossary_dir(directory: Path) -> GlossaryRegistry:
    """从目录加载所有非下划线开头的 .md 文件。

    跳过：以 _ 开头的（_SCHEMA.md / _PROMPT_FOR_GPT_PRO.md / _index.yaml 等元文件）。
    """

    if not directory.exists():
        raise GlossaryError(f"目录不存在: {directory}")
    reg = GlossaryRegistry()
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        term = parse_glossary_md(path)
        reg.add(term)
    # 闭环检查（不抛，由调用方决定）
    return reg


def validate_glossary_dir(
    directory: Path,
    *,
    min_count: int = 0,
    require_index_match: bool = False,
    strict_related: bool = False,
) -> dict[str, Any]:
    """CLI 校验入口；返回 {ok, count, invalid, errors[], related_violations[]}。

    :param min_count: 至少需要这么多条词条；不足返 ok=False
    :param require_index_match: True 时校验 _index.yaml 中每个 slug 都有 .md
    :param strict_related: True 时 related 闭环违规算 error 影响 ok；
                           False（默认）算 warning 只记录不影响 ok
    """

    errors: list[str] = []
    reg = GlossaryRegistry()

    if not directory.exists():
        return {"ok": False, "count": 0, "invalid": 1, "errors": [f"directory not found: {directory}"], "related_violations": []}

    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            term = parse_glossary_md(path)
            reg.add(term)
        except GlossaryError as exc:
            errors.append(str(exc))

    related_violations = reg.validate_related_closure()

    if require_index_match:
        idx_path = directory / "_index.yaml"
        if not idx_path.exists():
            errors.append("_index.yaml 不存在但 require_index_match=True")
        else:
            try:
                idx_data = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
                idx_slugs = [t.get("slug") for t in (idx_data.get("terms") or [])]
                for s in idx_slugs:
                    if s not in reg.terms:
                        errors.append(f"_index.yaml 含 slug={s} 但 {s}.md 不存在")
            except yaml.YAMLError as exc:
                errors.append(f"_index.yaml 解析失败: {exc}")

    ok = not errors and len(reg) >= min_count
    if strict_related and related_violations:
        ok = False
    return {
        "ok": ok,
        "count": len(reg),
        "invalid": len(errors),
        "errors": errors,
        "related_violations": related_violations,
    }


__all__ = [
    "GlossaryError",
    "GlossaryFrontmatter",
    "GlossaryRegistry",
    "GlossaryTerm",
    "load_glossary_dir",
    "parse_glossary_md",
    "validate_glossary_dir",
]
