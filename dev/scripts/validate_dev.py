#!/usr/bin/env python3
"""dev/ 开发 OS 完整性校验器 —— 让 harness 能自检，不靠手工纪律。

跑：  python dev/scripts/validate_dev.py      （仓库根或任意目录均可）
退出码 0 = 全过；1 = 有 FAIL。CI/pre-commit 可挂这个。

校验项（全部 exact，无误报）：
  1. 四台必需文件齐全
  2. tasks/{active,done,_templates} 目录存在
  3. BOARD 标 ✅done 的任务 ↔ done/<id>/TASK.md 一一对应（抓「标 done 却没落档」）
  4. 每个 done/<id>/ 有 TASK.md
  5. 活跃文档无「迁移前旧路径」悬空引用（DECISIONS append-only + research/archive 豁免）
  6. 脊柱地基 lineage/ids.py + 其对抗测试存在
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]          # dev/
ROOT = DEV.parent                                  # 仓库根

fails: list[str] = []
oks: list[str] = []


def ok(msg: str) -> None:
    oks.append(msg)


def fail(msg: str) -> None:
    fails.append(msg)


# --- 1. 四台必需文件 -------------------------------------------------------
REQUIRED = [
    "GOAL.md", "STATE.md", "RULES.md", "DECISIONS.md", "README.md",
    "tasks/BOARD.md", "research/INDEX.md", "exec/HANDOFF.md", "exec/LOG.md",
]
for rel in REQUIRED:
    (ok if (DEV / rel).is_file() else fail)(f"四台文件 {rel}")

# --- 2. 任务台目录 ---------------------------------------------------------
for rel in ["tasks/active", "tasks/done", "tasks/_templates"]:
    (ok if (DEV / rel).is_dir() else fail)(f"目录 {rel}/")

# --- 3 + 4. BOARD ✅done ↔ done/<id>/ -------------------------------------
board = (DEV / "tasks/BOARD.md").read_text(encoding="utf-8") if (DEV / "tasks/BOARD.md").is_file() else ""
# 表格行：| T-012 | ... | ✅ done | ...
done_in_board = set()
for line in board.splitlines():
    if "✅" in line and "done" in line:
        m = re.search(r"\bT-\d{3,4}\b", line)
        if m:
            done_in_board.add(m.group(0))

done_dirs = {p.name for p in (DEV / "tasks/done").glob("T-*") if p.is_dir()}

for tid in sorted(done_in_board):
    rec = DEV / "tasks/done" / tid / "TASK.md"
    if rec.is_file():
        ok(f"落档一致 {tid}（BOARD done ↔ done/{tid}/TASK.md）")
    else:
        fail(f"{tid} 在 BOARD 标 ✅done 但缺 done/{tid}/TASK.md（落档纪律漏了）")

for tid in sorted(done_dirs):
    if not (DEV / "tasks/done" / tid / "TASK.md").is_file():
        fail(f"done/{tid}/ 缺 TASK.md")

# --- 5. 活跃文档无迁移前旧路径悬空引用 ------------------------------------
# 这些前缀的内容已迁走/归位；活跃文档若还引用 = 悬空。
STALE_PREFIXES = [
    "docs/institutional-agent-os",
    "docs/codex_know", "docs/codex_rules",
    "docs/strategy/_",          # 旧 GPT-Pro 握手提示已进 exec/archive/handoffs
    "docs/templates/",          # 已进 tasks/_templates
    "docs/tasks/",              # 已进 dev/tasks
    "docs/roadmap/", "docs/references/",
]
# 活跃文档（不含 append-only 的 DECISIONS、不含 research/archive 历史档）
LIVE_DOCS = [
    "GOAL.md", "STATE.md", "RULES.md", "README.md",
    "tasks/BOARD.md", "research/INDEX.md", "exec/HANDOFF.md", "exec/LOG.md",
]
stale_hits = 0
for rel in LIVE_DOCS:
    p = DEV / rel
    if not p.is_file():
        continue
    text = p.read_text(encoding="utf-8")
    for pre in STALE_PREFIXES:
        if pre in text:
            fail(f"活跃文档 {rel} 含迁移前旧路径 `{pre}`（悬空引用）")
            stale_hits += 1
if stale_hits == 0:
    ok("活跃文档无迁移前旧路径悬空引用")

# --- 6. 脊柱地基 -----------------------------------------------------------
for rel in ["app/backend/app/lineage/ids.py", "app/backend/tests/test_lineage_node_id.py"]:
    (ok if (ROOT / rel).is_file() else fail)(f"脊柱地基 {rel}")

# --- 报告 ------------------------------------------------------------------
print(f"dev/ 完整性校验 —— {len(oks)} ✅  /  {len(fails)} ❌\n")
for m in oks:
    print(f"  ✅ {m}")
if fails:
    print()
    for m in fails:
        print(f"  ❌ {m}")
    print(f"\nFAIL（{len(fails)} 项）")
    sys.exit(1)
print("\nPASS —— harness 自检通过")
sys.exit(0)
