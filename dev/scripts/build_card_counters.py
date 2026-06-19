#!/usr/bin/env python3
"""任务卡 Open Questions 计数器生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

从每张未落档卡 `## Open Questions` 区的**实际决策标签**重算计数,写回标题
`（已决 D/T）`:**D = `[已决]` 数,T = `[已决]`+`[需拍板]` 数**(D=T 即全决、可进实现)。
团队并发：扫 tasks/pool + tasks/{developer_id}/（不含 done）。
**计数派生自标签、人别手敲**——改完标签后跑一次即同步。

⚠️ 机制依赖**标签名一致**:只认规范名 `[需拍板]` / `[已决]`(见 RULES §7)；validate_dev 兜底。
跑：python dev/scripts/build_card_counters.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
TASKS = DEV / "tasks"


def read_team() -> dict:
    p = DEV / "TEAM.md"
    t: dict = {}
    if not p.is_file():
        return t
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip().startswith("|"):
            continue
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(c) >= 2 and c[1] in ("leader", "admin", "developer"):
            t[c[0]] = c[1]
    return t


targets: list[Path] = []
pool = TASKS / "pool"
if pool.is_dir():
    targets += [d / "TASK.md" for d in sorted(pool.glob("*")) if d.is_dir() and (d / "TASK.md").is_file()]
for dev_id in read_team():
    base = TASKS / dev_id
    if base.is_dir():
        targets += [d / "TASK.md" for d in sorted(base.glob("*"))
                    if d.name != "done" and d.is_dir() and (d / "TASK.md").is_file()]

changed: list[tuple[str, str, str]] = []
for p in targets:
    lines = p.read_text(encoding="utf-8").splitlines()
    hi = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and "Open Questions" in ln), None)
    if hi is None:
        continue
    bj = next((j for j in range(hi + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    body = "\n".join(lines[hi + 1:bj])
    decided = body.count("[已决")
    total = decided + body.count("[需拍板")
    new = re.sub(r"(?:已决|待拍板)\s*\d+\s*/\s*\d+", f"已决 {decided}/{total}", lines[hi])
    if new != lines[hi]:
        old = lines[hi].strip()
        lines[hi] = new
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        changed.append((p.parent.name, old, new.strip()))

if changed:
    for tid, old, new in changed:
        print(f"  {tid}: {old}  →  {new}")
    print(f"\n{len(changed)} 张卡计数器已从标签重算写回。")
else:
    print("所有卡计数器已与标签一致,无需改。")
sys.exit(0)
