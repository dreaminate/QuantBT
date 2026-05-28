"""v0.8.4 · Glossary loader 单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.glossary import (
    GlossaryError,
    GlossaryFrontmatter,
    GlossaryRegistry,
    GlossaryTerm,
    load_glossary_dir,
    validate_glossary_dir,
)
from app.glossary.loader import parse_glossary_md


REPO_ROOT = Path(__file__).resolve().parents[3]
GLOSSARY_DIR = REPO_ROOT / "docs" / "glossary"


# ============================================================
# frontmatter Pydantic schema
# ============================================================


def test_frontmatter_minimum_valid():
    fm = GlossaryFrontmatter(
        term="sharpe_ratio",
        display="Sharpe Ratio",
        aliases=["sharpe"],
        level="beginner",
        category="metric",
        sources=["Sharpe 1966"],
    )
    assert fm.term == "sharpe_ratio"
    assert fm.related == []


def test_frontmatter_rejects_bad_level():
    with pytest.raises(Exception):
        GlossaryFrontmatter(
            term="x", display="X", aliases=[], level="advanced_pro",
            category="metric", sources=["s"],
        )


def test_frontmatter_rejects_bad_category():
    with pytest.raises(Exception):
        GlossaryFrontmatter(
            term="x", display="X", aliases=[], level="beginner",
            category="trading", sources=["s"],
        )


def test_frontmatter_rejects_kebab_case_slug():
    with pytest.raises(Exception):
        GlossaryFrontmatter(
            term="sharpe-ratio", display="X", aliases=[], level="beginner",
            category="metric", sources=["s"],
        )


def test_frontmatter_rejects_empty_sources():
    with pytest.raises(Exception):
        GlossaryFrontmatter(
            term="x", display="X", aliases=[], level="beginner",
            category="metric", sources=[],
        )


def test_frontmatter_rejects_inverted_range():
    with pytest.raises(Exception):
        GlossaryFrontmatter(
            term="x", display="X", aliases=[], level="beginner",
            category="metric", sources=["s"], typical_range=[3, 1],
        )


def test_frontmatter_extra_field_rejected():
    with pytest.raises(Exception):
        GlossaryFrontmatter(
            term="x", display="X", aliases=[], level="beginner",
            category="metric", sources=["s"], bogus_field="oops",
        )


# ============================================================
# parse_glossary_md
# ============================================================


def _make_md(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


def _minimal_md(slug: str = "test_term", related: list[str] | None = None) -> str:
    rel = related or []
    related_block = "related: []" if not rel else "related:\n" + "\n".join(f"  - {r}" for r in rel)
    return f"""---
term: {slug}
display: "Test"
aliases:
  - t
level: beginner
category: metric
sources:
  - "Test source"
{related_block}
---

## L1 一句话
short.

## L2 公式与例子
formula.

## L3 业界阈值与误区
- pitfall 1
- pitfall 2

## L4 延伸阅读
related stuff.
"""


def test_parse_minimal_valid(tmp_path: Path):
    p = _make_md(tmp_path, "test_term", _minimal_md())
    t = parse_glossary_md(p)
    assert t.slug == "test_term"
    assert t.l1 == "short."
    assert "formula" in t.l2
    assert "pitfall 1" in t.l3
    assert "related stuff" in t.l4


def test_parse_rejects_missing_frontmatter(tmp_path: Path):
    p = _make_md(tmp_path, "bad", "## L1\nhi\n## L2\n## L3\n## L4\n")
    with pytest.raises(GlossaryError, match="frontmatter"):
        parse_glossary_md(p)


def test_parse_rejects_missing_section(tmp_path: Path):
    body = _minimal_md().replace("## L3 业界阈值与误区\n- pitfall 1\n- pitfall 2\n\n", "")
    p = _make_md(tmp_path, "bad", body)
    with pytest.raises(GlossaryError, match="L3"):
        parse_glossary_md(p)


def test_parse_rejects_out_of_order_sections(tmp_path: Path):
    body = """---
term: x
display: X
aliases: []
level: beginner
category: metric
sources: ["s"]
related: []
---

## L2
two.

## L1
one.

## L3
three.

## L4
four.
"""
    p = _make_md(tmp_path, "x", body)
    with pytest.raises(GlossaryError, match="顺序"):
        parse_glossary_md(p)


def test_parse_rejects_filename_slug_mismatch(tmp_path: Path):
    p = _make_md(tmp_path, "wrong_name", _minimal_md("test_term"))
    with pytest.raises(GlossaryError, match="文件名"):
        parse_glossary_md(p)


# ============================================================
# Registry
# ============================================================


def test_registry_add_and_get(tmp_path: Path):
    p = _make_md(tmp_path, "test_term", _minimal_md())
    reg = GlossaryRegistry()
    reg.add(parse_glossary_md(p))
    assert reg.get("test_term") is not None
    assert len(reg) == 1


def test_registry_rejects_duplicate(tmp_path: Path):
    p = _make_md(tmp_path, "test_term", _minimal_md())
    reg = GlossaryRegistry()
    reg.add(parse_glossary_md(p))
    with pytest.raises(GlossaryError, match="重复"):
        reg.add(parse_glossary_md(p))


def test_registry_alias_lookup(tmp_path: Path):
    p = _make_md(tmp_path, "test_term", _minimal_md())
    reg = GlossaryRegistry()
    reg.add(parse_glossary_md(p))
    assert reg.lookup("t") is not None         # alias
    assert reg.lookup("T") is not None         # case-insensitive
    assert reg.lookup("test_term") is not None # slug
    assert reg.lookup("nope") is None


def test_registry_related_closure_detects_dangling(tmp_path: Path):
    p = _make_md(tmp_path, "a", _minimal_md("a", related=["b"]))
    reg = GlossaryRegistry()
    reg.add(parse_glossary_md(p))
    violations = reg.validate_related_closure()
    assert len(violations) == 1
    assert "b" in violations[0]


def test_registry_related_closure_passes_when_complete(tmp_path: Path):
    pa = _make_md(tmp_path, "a", _minimal_md("a", related=["b"]))
    pb = _make_md(tmp_path, "b", _minimal_md("b", related=["a"]))
    reg = GlossaryRegistry()
    reg.add(parse_glossary_md(pa))
    reg.add(parse_glossary_md(pb))
    assert reg.validate_related_closure() == []


def test_term_to_dict_progressive_disclosure(tmp_path: Path):
    p = _make_md(tmp_path, "test_term", _minimal_md())
    t = parse_glossary_md(p)
    full = t.to_dict()
    assert "l1" in full and "l2" in full and "l3" in full and "l4" in full
    only_l2 = t.to_dict(level="l2")
    assert "l1" in only_l2 and "l2" in only_l2
    assert "l3" not in only_l2 and "l4" not in only_l2


def test_term_levels_available(tmp_path: Path):
    p = _make_md(tmp_path, "test_term", _minimal_md())
    t = parse_glossary_md(p)
    assert t.levels_available == ["l1", "l2", "l3", "l4"]


# ============================================================
# load_glossary_dir / validate_glossary_dir
# ============================================================


def test_load_dir_skips_underscore_files(tmp_path: Path):
    _make_md(tmp_path, "_SCHEMA", _minimal_md("_schema"))  # 应被跳过
    _make_md(tmp_path, "real", _minimal_md("real"))
    reg = load_glossary_dir(tmp_path)
    assert len(reg) == 1
    assert reg.get("real") is not None
    assert reg.get("_schema") is None


def test_load_dir_missing_raises(tmp_path: Path):
    with pytest.raises(GlossaryError):
        load_glossary_dir(tmp_path / "nope")


def test_list_summary_shape(tmp_path: Path):
    _make_md(tmp_path, "alpha", _minimal_md("alpha"))
    _make_md(tmp_path, "beta", _minimal_md("beta"))
    reg = load_glossary_dir(tmp_path)
    summary = reg.list_summary()
    assert len(summary) == 2
    assert {s["slug"] for s in summary} == {"alpha", "beta"}
    assert all("levels_available" in s for s in summary)


def test_validate_with_min_count_below_threshold(tmp_path: Path):
    _make_md(tmp_path, "only_one", _minimal_md("only_one"))
    result = validate_glossary_dir(tmp_path, min_count=10)
    assert result["ok"] is False
    assert result["count"] == 1


def test_validate_returns_ok_when_valid(tmp_path: Path):
    _make_md(tmp_path, "a", _minimal_md("a"))
    result = validate_glossary_dir(tmp_path, min_count=1)
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["invalid"] == 0


def test_validate_collects_schema_errors(tmp_path: Path):
    _make_md(tmp_path, "bad", "no frontmatter at all\n\n## L1\nx")
    result = validate_glossary_dir(tmp_path)
    assert result["ok"] is False
    assert result["invalid"] >= 1


# ============================================================
# 真实 docs/glossary 加载校验（3 条样例 + index）
# ============================================================


def test_real_glossary_dir_loads_three_samples():
    """v0.8.4 Day 1 验收：sharpe_ratio / pbo / deflated_sharpe 三条样例必须能加载。"""
    if not GLOSSARY_DIR.exists():
        pytest.skip("docs/glossary 不存在")
    reg = load_glossary_dir(GLOSSARY_DIR)
    assert len(reg) >= 3
    for slug in ("sharpe_ratio", "pbo", "deflated_sharpe"):
        t = reg.get(slug)
        assert t is not None, f"{slug} 必须存在"
        assert t.l1 and t.l2 and t.l3 and t.l4, f"{slug} 四段必须非空"
        # L1 是 hover tooltip，必须短
        assert len(t.l1) <= 60, f"{slug}.l1 不能超过 60 字（hover tooltip 容量）"


def test_real_glossary_aliases_searchable():
    if not GLOSSARY_DIR.exists():
        pytest.skip("docs/glossary 不存在")
    reg = load_glossary_dir(GLOSSARY_DIR)
    # sharpe / 夏普 / pbo / dsr 应该都能命中
    for q in ("sharpe", "夏普", "pbo", "dsr"):
        assert reg.lookup(q) is not None, f"alias {q!r} 应命中"
