#!/usr/bin/env python3
"""任务卡 Open Questions 计数器生成器（【开发os级别】勿改 · clone 自 dev-os）。

从每张 active 卡 `## Open Questions` 区的**实际决策标签**重算计数,写回标题
`（已决 D/T）`:**D = `[已决]` 数,T = `[已决]`+`[需拍板]` 数**(D=T 即全决、可进实现)。
**计数派生自标签、人别手敲**——改完 Open Questions 标签后跑一次本脚本即同步。

⚠️ 整个机制依赖**标签名一致**:只认规范名 `[需拍板]` / `[已决]`(见 RULES §7)。
标签一漂(写成 `[已拍]`/`[待拍]` 等),计数就连锁错——`validate_dev.py` 另设标签规范检查兜底。

跑：python dev/scripts/build_card_counters.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
ACTIVE = DEV / "tasks/active"

changed: list[tuple[str, str, str]] = []
for p in sorted(ACTIVE.glob("T-*/TASK.md")):
    lines = p.read_text(encoding="utf-8").splitlines()
    hi = next((i for i, ln in enumerate(lines)
               if ln.startswith("## ") and "Open Questions" in ln), None)
    if hi is None:
        continue
    bj = next((j for j in range(hi + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    body = "\n".join(lines[hi + 1:bj])
    decided = body.count("[已决")      # 已决数（前缀计数:标签是 [已决 · 注]）
    total = decided + body.count("[需拍板")   # 总决策数（已决 + 待拍）
    new = re.sub(r"(?:已决|待拍板)\s*\d+\s*/\s*\d+", f"已决 {decided}/{total}", lines[hi])
    if new != lines[hi]:               # 只动有计数器格式且数字变了的标题
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
