#!/usr/bin/env python3
"""tasks 全含量账本生成器 —— 扫 active/ + done/ 出完整任务表。

BOARD.md 是「活跃版」(只 todo/in_progress,完成即删行,永不臃肿);
本脚本出「全含量版」(含 done)供需要时查询。**从目录现生成,不落第二份手维护账本 → 永不跑偏。**

跑:  python dev/scripts/build_ledger.py            # 打印到 stdout
     python dev/scripts/build_ledger.py --write    # 另写 dev/tasks/LEDGER.md(标自动生成)

【开发os级别】勿改 · clone 自 dev-os。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
TASKS = DEV / "tasks"


def card_info(task_md: Path, loc: str) -> dict:
    tid = task_md.parent.name
    text = task_md.read_text(encoding="utf-8") if task_md.is_file() else ""
    title = ""
    for line in text.splitlines():
        m = re.match(r"#\s*T-\S+\s*·\s*(.+)", line)
        if m:
            title = m.group(1).strip()
            break
    st = re.search(r"\*\*状态\*\*[：:]\s*([^\n·|]+)", text)
    rv = re.search(r"\*\*review_status\*\*[：:]\s*([0-9])", text)
    return {
        "id": tid,
        "title": title or "?",
        "状态": (st.group(1).strip() if st else "?"),
        "review": (rv.group(1) if rv else "?"),
        "位置": loc,
    }


rows: list[dict] = []
for loc in ("active", "done"):
    for d in sorted((TASKS / loc).glob("T-*")):
        if d.is_dir():
            rows.append(card_info(d / "TASK.md", loc))

lines = [
    "# LEDGER · 全含量任务账本（自动生成 · 勿手改 · 跑 build_ledger.py 刷新）",
    "",
    "| id | 标题 | 状态 | review | 位置 |",
    "|----|------|------|--------|------|",
]
for r in rows:
    lines.append(f"| {r['id']} | {r['title']} | {r['状态']} | {r['review']} | {r['位置']} |")
n_active = sum(1 for r in rows if r["位置"] == "active")
lines.append("")
lines.append(f"共 {len(rows)} 个任务（active {n_active} / done {len(rows) - n_active}）")
out = "\n".join(lines) + "\n"

if "--write" in sys.argv:
    (TASKS / "LEDGER.md").write_text(out, encoding="utf-8")
    print(f"已写 {TASKS / 'LEDGER.md'}（{len(rows)} 任务）")
else:
    print(out)
