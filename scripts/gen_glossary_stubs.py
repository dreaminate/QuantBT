#!/usr/bin/env python3
"""v0.9.11 · 从 _index.yaml 生成 27 个 stub 词条 markdown。

每个 stub 含最小 frontmatter (term/display/aliases/level/category/sources/related)
+ L1/L2/L3/L4 占位段落。让 strict_related 校验通过。

GPT Pro 出真内容后只需 replace 文件，不动 _index.yaml 和 importer。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_DIR = ROOT / "docs" / "glossary"

CATEGORY_LEVEL_DEFAULT = {
    # 按 _index.yaml 已分类的 batch + level 经验值
    "metric": "beginner",
    "risk": "intermediate",
    "factor": "intermediate",
    "model": "advanced",
    "portfolio": "intermediate",
    "data": "beginner",
    "execution": "intermediate",
}


def stub_markdown(slug: str, display: str, category: str, related_slugs: list[str]) -> str:
    level = CATEGORY_LEVEL_DEFAULT.get(category, "beginner")
    related_block = "related: []" if not related_slugs else "related:\n" + "\n".join(f"  - {r}" for r in related_slugs)
    return f"""---
term: {slug}
display: "{display}"
aliases:
  - {slug}
level: {level}
category: {category}
sources:
  - "占位: 待 GPT Pro 出完整词条 (按 docs/glossary/_PROMPT_FOR_GPT_PRO.md 6 批次)"
{related_block}
---

## L1 一句话

待 GPT Pro 补全 (placeholder, 不阻断 strict_related 校验)。

## L2 公式与例子

待 GPT Pro 补全公式 + 算例。

## L3 业界阈值与误区

待 GPT Pro 补全:
- 阈值参考表格
- 至少 3 条带文献出处的常见误区

## L4 延伸阅读

待 GPT Pro 补全相关词条链接与文献。
"""


def main() -> int:
    index_path = GLOSSARY_DIR / "_index.yaml"
    if not index_path.exists():
        print(f"[FAIL] _index.yaml 不存在: {index_path}", file=sys.stderr)
        return 1

    data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    terms = data.get("terms") or []
    if not terms:
        print("[FAIL] _index.yaml 无 terms", file=sys.stderr)
        return 1

    # 构造 slug → category map (for related)
    all_slugs = {t["slug"] for t in terms}

    created = 0
    skipped = 0
    for entry in terms:
        slug = entry["slug"]
        display = entry.get("display", slug)
        category = entry.get("category", "metric")
        md_path = GLOSSARY_DIR / f"{slug}.md"
        if md_path.exists():
            skipped += 1
            continue
        # 简单 related: 同 category 的其它词条选 2-3 个
        same_cat = [t["slug"] for t in terms if t.get("category") == category and t["slug"] != slug]
        related = same_cat[:3]
        md_path.write_text(
            stub_markdown(slug, display, category, related),
            encoding="utf-8",
        )
        created += 1
        print(f"  [STUB] {slug} (category={category}, related={related})")

    print(f"\n  created={created} / skipped={skipped} / total={len(terms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
