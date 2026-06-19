#!/usr/bin/env python3
"""LOG 索引生成器（【开发os级别】勿改 · clone 自 dev-os）。

按需**打印**执行台 LOG 的统一时间线索引：`exec/LOG.md`（活跃）+ `exec/LOG.archive.md`
（归档，若有），每条 = 日期 · 标题 · `文件:行`，按日期倒序。

用途：支撑"**强制查 LOG**"逻辑——活跃 `LOG.md` 没查到的历史，**必须**来这看归档索引、
定位到 `LOG.archive.md` 原文（索引仅定位，必读原文）。

索引是**从正文重生的**（每次跑都重算），**不落盘第二份、绝不手维护** —— 枚举类防漂。
跑：  python dev/scripts/build_log_index.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]   # dev/
EXEC = DEV / "exec"


def _entries(p: Path) -> list[tuple[str, str, int]]:
    """提取 markdown `## ` 标题作为 LOG 条目：(标题, 文件名, 行号)。"""
    if not p.is_file():
        return []
    out: list[tuple[str, str, int]] = []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if ln.startswith("## "):
            out.append((ln[3:].strip(), p.name, i))
    return out


def _datekey(title: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", title)
    return m.group(1) if m else "0000-00-00"


rows = _entries(EXEC / "LOG.md") + _entries(EXEC / "LOG.archive.md")
rows.sort(key=lambda r: _datekey(r[0]), reverse=True)

active = sum(1 for _, f, _ in rows if f == "LOG.md")
archived = len(rows) - active
print(f"LOG 索引 —— {len(rows)} 条（活跃 {active} · 归档 {archived}）"
      f"{'  ⚠️ 无 LOG.archive.md（尚未归档）' if not (EXEC / 'LOG.archive.md').is_file() else ''}\n")
for title, fname, line in rows:
    print(f"  {fname}:{line}  {title}")
if not rows:
    print("  （LOG 为空）")
print("\n（索引仅定位 —— 据 文件:行 跳到 LOG 原文条款再行事，别只凭这行标题。）")
sys.exit(0)
