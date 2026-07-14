#!/usr/bin/env python3
"""LOG 索引生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

团队并发：LOG 已 folder 化 = `log/{developer_id}/log.md`（+ 可选 `log.archive.md`）。
按需**打印**所有 developer 的统一时间线索引，每条 = 日期 · 标题 · `developer/文件:行`，按日期倒序。

用途：支撑"**强制查 LOG**"——某历史在哪个人的 log,先看本索引定位、再读原文（索引仅定位、必读原文）。
索引**从正文重生**（每次跑都重算）、**不落盘第二份、绝不手维护** —— 枚举类防漂。
跑：  python dev/scripts/build_log_index.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
LOGBASE = DEV / "log"


def _entries(p: Path) -> list[tuple[str, int]]:
    if not p.is_file():
        return []
    out: list[tuple[str, int]] = []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if ln.startswith("## ") and not ln[3:].lstrip().startswith("<"):
            out.append((ln[3:].strip(), i))
    return out


def _datekey(title: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", title)
    return m.group(1) if m else "0000-00-00"


rows: list[tuple[str, str, int]] = []   # (title, "dev/file", line)
if LOGBASE.is_dir():
    for devdir in sorted(LOGBASE.glob("*")):
        if not devdir.is_dir():
            continue
        targets = [devdir / "log.md", devdir / "log.archive.md"]
        if (devdir / "archive").is_dir():  # os.py log 按月滚动的归档(archive/YYYY-MM.md)
            targets += sorted((devdir / "archive").glob("*.md"))
        for lf in targets:
            for title, line in _entries(lf):
                rows.append((title, f"{devdir.name}/{lf.relative_to(devdir)}", line))

rows.sort(key=lambda r: _datekey(r[0]), reverse=True)

print(f"LOG 索引（团队）—— {len(rows)} 条，来自 {len([d for d in LOGBASE.glob('*') if d.is_dir()]) if LOGBASE.is_dir() else 0} 个 developer\n")
for title, where, line in rows:
    print(f"  log/{where}:{line}  {title}")
if not rows:
    print("  （LOG 为空）")
print("\n（索引仅定位 —— 据 文件:行 跳到 LOG 原文条款再行事，别只凭这行标题。）")
sys.exit(0)
