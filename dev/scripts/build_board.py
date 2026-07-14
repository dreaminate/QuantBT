#!/usr/bin/env python3
"""本机工作板生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

从 tasks/{本机 .identity}/ 的 active 卡现生成 board/{developer_id}/board.md（只含本人卡）。
board 是**生成视图、不手维护**；改了卡跑一次即同步。**只定位；实时依据看卡原文 + 代码。**
`render(dev, me)` 返回 {路径:内容} 供 validate_dev 重算比对新鲜度;main 才写盘。
跑：  python dev/scripts/build_board.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oslib import oq_tag_counts  # noqa: E402


def fm(txt: str) -> dict:
    if not txt.lstrip().startswith("---"):
        return {}
    L = txt.splitlines()
    s = next((i for i, l in enumerate(L) if l.strip() == "---"), None)
    if s is None:
        return {}
    e = next((i for i in range(s + 1, len(L)) if L[i].strip() == "---"), None)
    if e is None:
        return {}
    d: dict = {}
    k = None
    for ln in L[s + 1:e]:
        if re.match(r"^\s*-\s+", ln) and k == "depends_on":
            d.setdefault("depends_on", []).append(re.sub(r"\s{2,}#.*$", "", ln.split("-", 1)[1]).strip().strip("'\""))
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", ln)
        if not m:
            continue
        k = m.group(1)
        v = re.sub(r"\s{2,}#.*$", "", m.group(2)).strip()
        if k == "depends_on":
            if v.startswith("["):
                inner = v.strip("[]").strip()
                d["depends_on"] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            else:
                d.setdefault("depends_on", [])
        else:
            d[k] = v
    return d


def render(dev: Path, me: str) -> dict:
    """返回 {board/{me}/board.md 绝对路径(str): 内容}。不写盘。"""
    base = dev / "tasks" / me
    rows = []
    if base.is_dir():
        for d in sorted(base.glob("*")):
            if d.name == "done" or not d.is_dir() or not (d / "TASK.md").is_file():
                continue
            txt = (d / "TASK.md").read_text(encoding="utf-8")
            f = fm(txt)
            pend, dec, _bad = oq_tag_counts(txt)
            oq = f"已决 {dec}/{dec + pend}" if (pend or dec) else "-"
            rows.append((d.name, f.get("title", "?"), f.get("status", "?"), f.get("area", "-"),
                         f.get("priority", "-"), oq, " ".join(x[:8] for x in (f.get("depends_on") or []))))
    lines = [
        f"# BOARD · {me} 的工作板（生成 · 勿手改/勿入库 · os.py refresh 重建）",
        "",
        f"> 只含 **{me}** 名下 active 卡（从 tasks/{me}/ 现生成）。**导航 only，实时依据看卡原文 + 对应代码。**",
        "> 「已决 D/总」从 OQ 标签现算、不落盘——待拍>0 的卡别进实现(RULES §7)。",
        "",
        "| uuid8 | 标题 | status | area | 优先级 | 已决 D/总 | 依赖(uuid8) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(c or "-" for c in r) + " |")
    if not rows:
        lines.append("| _（名下无 active 卡）_ | | | | | | |")
    return {str(dev / "board" / me / "board.md"): "\n".join(lines) + "\n"}


if __name__ == "__main__":
    DEV = Path(__file__).resolve().parents[1]
    idp = DEV / ".identity"
    me = idp.read_text(encoding="utf-8").strip().splitlines()[0].strip() if idp.is_file() and idp.read_text(encoding="utf-8").strip() else None
    if not me:
        print("无 dev/.identity（本机开发者身份），无法生成 board")
        sys.exit(1)
    for p, c in render(DEV, me).items():
        path = Path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(c, encoding="utf-8")
    print(f"已写 board/{me}/board.md")
    sys.exit(0)
