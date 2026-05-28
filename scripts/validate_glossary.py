#!/usr/bin/env python3
"""v0.8.4 · Glossary 词条校验脚本（CI 用）。

用法：
    python scripts/validate_glossary.py docs/glossary
    python scripts/validate_glossary.py docs/glossary --min-count 30
    python scripts/validate_glossary.py docs/glossary --require-index-match

退出码：
    0 = PASS  ·  1 = FAIL（schema/frontmatter/related 闭环/count 不足）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从仓库根直接跑：将 app/backend 加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.glossary import validate_glossary_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantBT glossary validator")
    parser.add_argument("directory", help="glossary 目录路径（如 docs/glossary）")
    parser.add_argument("--min-count", type=int, default=0, help="最低词条数；少于此数报 FAIL")
    parser.add_argument(
        "--require-index-match",
        action="store_true",
        help="校验 _index.yaml 中每个 slug 都有对应 .md 文件",
    )
    parser.add_argument(
        "--strict-related",
        action="store_true",
        help="related 引用必须都已存在；默认 warning 不影响 ok (用于 baseline 30 条到位前)",
    )
    args = parser.parse_args()

    result = validate_glossary_dir(
        Path(args.directory),
        min_count=args.min_count,
        require_index_match=args.require_index_match,
        strict_related=args.strict_related,
    )

    ok = result["ok"]
    count = result["count"]
    invalid = result["invalid"]

    if result["errors"]:
        print("ERRORS:", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e}", file=sys.stderr)
    if result["related_violations"]:
        print("RELATED CLOSURE VIOLATIONS:", file=sys.stderr)
        for v in result["related_violations"]:
            print(f"  - {v}", file=sys.stderr)

    status = "PASS" if ok else "FAIL"
    print(f"{status} count={count} invalid={invalid}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
