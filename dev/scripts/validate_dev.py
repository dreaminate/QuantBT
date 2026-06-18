#!/usr/bin/env python3
"""dev/ 开发 OS 结构校验器（【开发os级别】勿改 · clone 自 dev-os）。

只管 **OS 结构**：四台文件齐全 / 目录齐全 / BOARD↔done 一致 / 活跃任务孤儿。
**项目专属检查在同目录 `validate_project.py`（【项目级别】填）**——本脚本会自动连带跑它。

跑：  python dev/scripts/validate_dev.py
退出码 0 = 全过；1 = 有 FAIL。CI / pre-commit 可挂这个。
适配新项目：**别动本文件**，只改 `validate_project.py`。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]          # dev/
ROOT = DEV.parent                                  # 仓库根


def run_os_checks(dev: Path) -> tuple[list[str], list[str]]:
    """纯 OS 结构检查（项目无关）。"""
    oks: list[str] = []
    fails: list[str] = []

    # 1. 四台必需文件
    required = [
        "GOAL.md", "STATE.md", "RULES.md", "RULES.project.md", "DECISIONS.md",
        "ISSUES.md", "README.md",
        "tasks/BOARD.md", "research/INDEX.md", "exec/HANDOFF.md", "exec/LOG.md",
    ]
    for rel in required:
        (oks if (dev / rel).is_file() else fails).append(f"四台文件 {rel}")

    # 2. 目录骨架（文件夹结构,固定·不可改名）
    for rel in ["tasks/active", "tasks/done", "tasks/_templates",
                "research/ideas", "research/active", "research/findings", "research/archive",
                "exec", "scripts"]:
        (oks if (dev / rel).is_dir() else fails).append(f"目录 {rel}/")

    # 2b. OS 结构文件（固定名,改名/删 → FAIL；变动的任务卡/研究文件名不在内）
    os_files = [
        "research/TRACE.md", "research/DISTILL.md", "research/WORKFLOW.md",
        "scripts/validate_project.py", "scripts/build_ledger.py", "scripts/README.md",
        "tasks/_templates/TASK.md",
        "research/ideas/README.md", "research/ideas/_TEMPLATE.md",
        "research/active/README.md", "research/active/_TEMPLATE.md",
        "research/findings/_TEMPLATE.md",
    ]
    for rel in os_files:
        (oks if (dev / rel).is_file() else fails).append(f"OS 结构文件 {rel}")
    (oks if (dev.parent / "CLAUDE.md").is_file() else fails).append("OS 结构文件 CLAUDE.md(根)")

    # 3. BOARD ✅done ↔ done/<id>/
    board = (dev / "tasks/BOARD.md").read_text(encoding="utf-8") if (dev / "tasks/BOARD.md").is_file() else ""
    done_in_board = set()
    for line in board.splitlines():
        if "✅" in line and "done" in line:
            m = re.search(r"\bT-\d{3,4}\b", line)
            if m:
                done_in_board.add(m.group(0))
    for tid in sorted(done_in_board):
        if (dev / "tasks/done" / tid / "TASK.md").is_file():
            oks.append(f"落档一致 {tid}（BOARD done ↔ done/{tid}/TASK.md）")
        else:
            fails.append(f"{tid} 在 BOARD 标 ✅done 但缺 done/{tid}/TASK.md")
    for tid in sorted({p.name for p in (dev / "tasks/done").glob("T-*") if p.is_dir()}):
        if not (dev / "tasks/done" / tid / "TASK.md").is_file():
            fails.append(f"done/{tid}/ 缺 TASK.md")

    # 4. active/<id>/ 应在 BOARD(活跃版)有行 —— 孤儿任务检查
    board_ids = set(re.findall(r"\bT-\d{3,4}\b", board))
    for tid in sorted({p.name for p in (dev / "tasks/active").glob("T-*") if p.is_dir()}):
        if tid in board_ids:
            oks.append(f"BOARD 含活跃任务 {tid}")
        else:
            fails.append(f"active/{tid}/ 不在 BOARD 活跃版（孤儿任务,主力板漏了）")

    return oks, fails


oks, fails = run_os_checks(DEV)

# 连带跑项目检查（validate_project.py，【项目级别】填；缺了不算错）
try:
    sys.path.insert(0, str(DEV / "scripts"))
    from validate_project import project_checks  # type: ignore

    p_oks, p_fails = project_checks(DEV, ROOT)
    oks += p_oks
    fails += p_fails
except ModuleNotFoundError:
    oks.append("（无 validate_project.py，跳过项目检查）")

# 报告
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
