#!/usr/bin/env python3
"""SA-4 数据卫生：清运行时 JSONL 账本里的 goal_closure 占位种子行。

已移除的 "goal closure" 闭合 materializer 曾往两本 append-only 运行时账本播种自证闭合的占位
记录，使纯解析检查可被骗过：
  - <data-root>/audit/mathematical_spine_chains.jsonl
  - <data-root>/audit/research_graph_commands.jsonl
研究代码侧已加 write门（research_os/spine.py + graph/research_graph.py）fail-closed 掉**新**种子；
本脚本清**既存残留**行。两本账本 gitignored（运行时数据，不入库）。

设计：
  - 默认 **dry-run**（只报告不改），要真删须显式 `--apply`（动审计账本=可逆性谨慎）。
  - `--apply` 先写带时间戳的 .bak 备份，再原子重写（temp + os.replace）。
  - 只删「整行小写后含 goal_closure / goal-closure / goalclosure 任一」的行，其余逐字节保留。
  - 幂等：重跑删 0 行。

⚠️ 隔离边界：这脚本所在的开发 worktree **不应**假设能改到 main checkout 的运行时数据目录。
   真正的 purge 由**中心在 main 数据目录**上跑（main 的 data/audit/*.jsonl 才是带种子的那份）。

用法：
  python scripts/purge_goal_closure_seeds.py                 # dry-run，自动定位 <repo>/data
  python scripts/purge_goal_closure_seeds.py --apply         # 真删（带备份）
  python scripts/purge_goal_closure_seeds.py --data-root /path/to/data --apply
  BACKTEST_DATA_ROOT=/path/to/data python scripts/purge_goal_closure_seeds.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 与 research_os/spine.py / graph/research_graph.py 的 _GOAL_CLOSURE_SEED_TOKENS 对齐（故意只 goal_closure
# 族·不含 synthetic/fixture 等更宽 token，避免误删合法 synthetic 行）。大小写不敏感子串匹配。
GOAL_CLOSURE_SEED_TOKENS: tuple[str, ...] = ("goal_closure", "goal-closure", "goalclosure")

LEDGER_NAMES: tuple[str, ...] = (
    "mathematical_spine_chains.jsonl",
    "research_graph_commands.jsonl",
)


def _carries_goal_closure_seed(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in GOAL_CLOSURE_SEED_TOKENS)


def _default_data_root() -> Path:
    env = os.getenv("BACKTEST_DATA_ROOT")
    if env:
        return Path(env).resolve()
    # 本文件位于 <repo>/scripts/purge_goal_closure_seeds.py → <repo>/data
    return (Path(__file__).resolve().parents[1] / "data").resolve()


def purge_ledger(path: Path, *, apply: bool) -> dict[str, int]:
    """返回 {total, removed, kept}。dry-run（apply=False）不改文件。"""

    if not path.exists():
        return {"total": 0, "removed": 0, "kept": 0, "missing": 1}

    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()

    kept: list[str] = []
    removed = 0
    for line in lines:
        if line.strip() and _carries_goal_closure_seed(line):
            removed += 1
            continue
        kept.append(line)

    stats = {"total": len(lines), "removed": removed, "kept": len(kept), "missing": 0}
    if not apply or removed == 0:
        return stats

    # 备份后原子重写。
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    backup.write_text("".join(lines), encoding="utf-8")
    tmp = path.with_suffix(path.suffix + f".tmp.{stamp}")
    tmp.write_text("".join(kept), encoding="utf-8")
    os.replace(tmp, path)  # 原子替换
    stats["backup"] = str(backup)  # type: ignore[assignment]
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清运行时 JSONL 账本里的 goal_closure 占位种子行（SA-4）。")
    parser.add_argument("--data-root", type=Path, default=None, help="数据根目录（默认 BACKTEST_DATA_ROOT 或 <repo>/data）。")
    parser.add_argument("--apply", action="store_true", help="真删（默认 dry-run 只报告）。")
    args = parser.parse_args(argv)

    data_root = (args.data_root.resolve() if args.data_root else _default_data_root())
    audit_dir = data_root / "audit"
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[SA-4 purge · {mode}] data-root = {data_root}")
    print(f"[SA-4 purge · {mode}] audit-dir = {audit_dir}")

    total_removed = 0
    any_ledger = False
    for name in LEDGER_NAMES:
        path = audit_dir / name
        stats = purge_ledger(path, apply=args.apply)
        if stats.get("missing"):
            print(f"  - {name}: (不存在·跳过)")
            continue
        any_ledger = True
        total_removed += stats["removed"]
        backup = stats.get("backup")
        suffix = f" · backup={backup}" if backup else ""
        verb = "removed" if args.apply else "would-remove"
        print(f"  - {name}: total={stats['total']} {verb}={stats['removed']} kept={stats['kept']}{suffix}")

    if not any_ledger:
        print("[SA-4 purge] 未发现目标账本（audit 目录无种子文件）。")
    elif not args.apply and total_removed > 0:
        print(f"[SA-4 purge] DRY-RUN：共 {total_removed} 行含 goal_closure 种子。加 --apply 真删（会先备份）。")
    elif args.apply:
        print(f"[SA-4 purge] APPLY 完成：共删 {total_removed} 行。")
    else:
        print("[SA-4 purge] 干净：无 goal_closure 种子行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
