#!/usr/bin/env python3
"""项目专属检查（**QuantBT 填**）。`validate_dev.py` 会自动连带跑本文件的 `project_checks`。

适配本项目就改这里：
- `PROJECT_ANCHORS`：项目关键文件（存在性检查，相对仓库根）。
- `STALE_PREFIXES`：活跃文档不应再出现的"迁移前旧路径"（防悬空引用）。
- 还可在 `project_checks` 里加任意本项目自定义检查。
"""
from __future__ import annotations

from pathlib import Path

# ── 项目配置（填这里）─────────────────────────────────────────────
PROJECT_ANCHORS: list[str] = [
    "app/backend/app/lineage/ids.py",
    "app/backend/tests/test_lineage_node_id.py",
]
STALE_PREFIXES: list[str] = [
    "docs/institutional-agent-os",
    "docs/codex_know", "docs/codex_rules",
    "docs/strategy/_", "docs/templates/", "docs/tasks/",
    "docs/roadmap/", "docs/references/",
]
# 活跃文档（被 STALE_PREFIXES 扫描；append-only 的 DECISIONS 不在内）
LIVE_DOCS: list[str] = [
    "GOAL.md", "STATE.md", "RULES.md", "RULES.project.md", "README.md", "ISSUES.md",
    "tasks/BOARD.md", "research/INDEX.md", "exec/HANDOFF.md", "exec/LOG.md",
]
# ────────────────────────────────────────────────────────────────────


def project_checks(DEV: Path, ROOT: Path) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []

    # 项目锚点存在性（脊柱地基）
    for rel in PROJECT_ANCHORS:
        (oks if (ROOT / rel).is_file() else fails).append(f"项目锚点 {rel}")
    if not PROJECT_ANCHORS:
        oks.append("（未配置项目锚点，跳过）")

    # 活跃文档无迁移前旧路径
    stale_hits = 0
    for rel in LIVE_DOCS:
        p = DEV / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        for pre in STALE_PREFIXES:
            if pre in text:
                fails.append(f"活跃文档 {rel} 含迁移前旧路径 `{pre}`（悬空引用）")
                stale_hits += 1
    if not STALE_PREFIXES or stale_hits == 0:
        oks.append("活跃文档无迁移前旧路径悬空引用")

    return oks, fails
