#!/usr/bin/env python3
"""TRACE 覆盖派生视图生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

TRACE.md 手填层只装真慢变(GOAL 节 ↔ 文献/finding ↔ 决策锚);「哪些卡在实现哪节、覆盖到哪」
是纯派生量——本脚本从卡 frontmatter.goal_section 聚合,现生成 research/TRACE.coverage.md
(**不入库**,dev/.gitignore 已挡)。铁律二:枚举类绝不手维护。
跑:  python dev/scripts/build_trace.py    (os.py refresh 也会带跑)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oslib import gather_cards, read_team  # noqa: E402


def _goal_sections(dev: Path) -> dict:
    """GOAL.md 的「## N. 标题」节(占位 <…> 跳过) → {N: 标题}。"""
    p = dev / "GOAL.md"
    secs: dict = {}
    if not p.is_file():
        return secs
    for ln in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(\d+)\.\s+(.+?)\s*$", ln)
        if m and "<" not in m.group(2):
            secs[m.group(1)] = m.group(2)
    return secs


def _norm(gs: str) -> str:
    """goal_section 归一:'§3' / '3' / '3.' → '3'。"""
    return re.sub(r"[§\s.]", "", gs or "")


def render(dev: Path) -> dict:
    secs = _goal_sections(dev)
    cards = [c for c in gather_cards(dev, list(read_team(dev).keys())) if not c.get("no_task_md")]
    by_sec: dict = {}
    orphans: list = []
    for c in cards:
        gs = _norm(c.get("goal_section", ""))
        if not gs:
            continue
        (by_sec.setdefault(gs, []) if gs in secs else orphans).append(c)
    lines = [
        "# TRACE.coverage · GOAL 节 × 任务卡 覆盖派生视图（生成 · 勿手改 · 不入库）",
        "",
        "> 从卡 frontmatter.goal_section 聚合;手填溯源(文献/finding/决策)看 TRACE.md。",
        "> 图例:✅ done · 🔵 active · ⚪ pool。**只定位;实时依据看卡原文。**",
        "",
        "| GOAL 节 | 覆盖 | 卡(uuid8 · status) |",
        "|---|---|---|",
    ]
    for n in sorted(secs, key=int):
        cs = by_sec.get(n, [])
        done = sum(1 for c in cs if c["status"] == "done")
        act = sum(1 for c in cs if c["loc"] == "active")
        pool = sum(1 for c in cs if c["loc"] == "pool")
        mark = "⬜ 无卡" if not cs else f"✅{done} 🔵{act} ⚪{pool}"
        cell = " · ".join(f"{c['name']}({c['status']})" for c in cs) or "-"
        lines.append(f"| §{n} {secs[n]} | {mark} | {cell} |")
    if orphans:
        lines += ["", "## ⚠️ goal_section 对不上 GOAL 节(检查节号或 GOAL 是否改版)", ""]
        for c in orphans:
            lines.append(f"- {c['name']}(goal_section={c.get('goal_section')})")
    uncov = [n for n in secs if n not in by_sec]
    lines += ["", f"覆盖体检:{len(secs) - len(uncov)}/{len(secs)} 节有卡" + (f";无卡节:{'、'.join('§' + n for n in sorted(uncov, key=int))}" if uncov else "")]
    return {str(dev / "research/TRACE.coverage.md"): "\n".join(lines) + "\n"}


if __name__ == "__main__":
    DEV = Path(__file__).resolve().parents[1]
    for p, c in render(DEV).items():
        Path(p).write_text(c, encoding="utf-8")
        print(f"已写 {Path(p).relative_to(DEV)}(派生视图,不入库)")
