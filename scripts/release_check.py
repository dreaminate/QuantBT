#!/usr/bin/env python3
"""v0.9.0 · Release 收口自动化校验脚本。

跑全部 pre-release 命令并汇总。任何一条失败 → exit 1。

用法:
    python scripts/release_check.py --tag v0.9.0
    python scripts/release_check.py --tag v0.9.0 --skip-build  # 跳过 vite build
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], *, cwd: Path | None = None, allow_fail: bool = False) -> tuple[bool, str]:
    """运行命令，返回 (ok, stdout_tail)。"""
    try:
        result = subprocess.run(
            cmd, cwd=cwd or ROOT,
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    ok = result.returncode == 0
    tail = (result.stdout or "")[-300:] + "\n" + (result.stderr or "")[-200:]
    return ok or allow_fail, tail.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="待发布的 git tag，如 v0.9.0")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    print(f"=== Release Check · tag={args.tag} ===\n")

    checks: list[tuple[str, bool, str]] = []

    # 1. pytest
    print("[1] 后端全量 pytest...")
    ok, tail = run(["python", "-m", "pytest", "app/backend/tests", "-q", "--tb=no"])
    checks.append(("pytest", ok, tail.split("\n")[-1] if tail else ""))

    # 2. Glossary 校验
    print("[2] Glossary 校验...")
    ok, tail = run(["python", "scripts/validate_glossary.py", "docs/glossary", "--min-count", "3"])
    checks.append(("glossary", ok, tail.split("\n")[-1] if tail else ""))

    # 3. TSC
    print("[3] TypeScript typecheck...")
    ok, tail = run(["npx", "tsc", "--noEmit"], cwd=ROOT / "app" / "frontend")
    checks.append(("tsc", ok, "0 errors" if ok else tail))

    # 4. Vite build
    if not args.skip_build:
        print("[4] Vite production build...")
        ok, tail = run(["npx", "vite", "build"], cwd=ROOT / "app" / "frontend")
        checks.append(("vite build", ok, "✓ built" if ok else tail))

    # 5. release notes 存在
    print("[5] Release notes 存在...")
    notes_path = ROOT / "docs" / "releases" / f"{args.tag}.md"
    notes_exist = notes_path.exists()
    checks.append(("release notes", notes_exist, str(notes_path)))

    # 6. CHANGELOG 同步 (软检查)
    print("[6] GOAL doc 提到该 tag (soft)...")
    goal_path = ROOT / "QuantBT-GOAL.md"
    mentioned = args.tag in goal_path.read_text(encoding="utf-8") if goal_path.exists() else False
    checks.append(("GOAL mentions tag", mentioned, ""))

    # 7. git working tree clean
    print("[7] Git working tree...")
    ok, tail = run(["git", "status", "--porcelain"])
    clean = ok and not tail
    checks.append(("git clean", clean, "clean" if clean else "uncommitted changes"))

    # 输出汇总
    print("\n=== Results ===")
    all_pass = True
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"  [{mark}] {name:24s} · {detail}")
        if not ok:
            all_pass = False

    if all_pass:
        print(f"\n=== {args.tag} READY TO RELEASE ===")
        return 0
    print(f"\n=== {args.tag} NOT READY · fix failures above ===")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
