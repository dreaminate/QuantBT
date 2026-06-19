#!/usr/bin/env python3
"""全局导航 map 生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

遍历所有 developer folder → 生成导航 map（**只定位；实时依据永远是原文 + 对应代码**）：
  dev/DEVMAP.md   developer(+role) → 拿了哪些卡 [uuid8·标题·status·area]；+ 按 area 索引；+ pool 待分配
  {decisions,issues,state,log,experience,research/ideas,research/active,research/findings}/_NAV.md
                  developer → 文件 + 一行梗概
`render(dev)` 返回 {路径:内容} 供 validate_dev 重算比对新鲜度;main 才写盘。
跑：  python dev/scripts/build_dev_map.py
"""
from __future__ import annotations

import re
from pathlib import Path

_NAV_FOLDERS = ["decisions", "issues", "state", "log", "experience",
                "research/ideas", "research/active", "research/findings"]


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
    for ln in L[s + 1:e]:
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", ln)
        if m and m.group(1) != "depends_on":
            d[m.group(1)] = re.sub(r"\s{2,}#.*$", "", m.group(2)).strip()
    return d


def read_team(dev: Path) -> dict:
    p = dev / "TEAM.md"
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


def card_rows(base: Path, loc: str) -> list[tuple]:
    rows = []
    if not base.is_dir():
        return rows
    for d in sorted(base.glob("*")):
        if not d.is_dir() or not (d / "TASK.md").is_file():
            continue
        f = fm((d / "TASK.md").read_text(encoding="utf-8"))
        rows.append((d.name, f.get("title", d.name), f.get("status", "?"), f.get("area", "-"), loc))
    return rows


def first_title(p: Path) -> str:
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            return ln.lstrip("# ").strip()[:60]
        if ln.strip() and not ln.startswith("---"):
            return ln.strip()[:60]
    return ""


def render(dev: Path) -> dict:
    """返回 {绝对路径(str): 内容} for DEVMAP.md + 各存在 folder 的 _NAV.md。不写盘。"""
    out: dict = {}
    team = read_team(dev)
    lines = [
        "# DEVMAP · 全局任务导航（生成 · 勿手改 · 跑 build_dev_map.py 刷新）",
        "",
        "> 谁拿了哪些卡 + 在哪步 + 什么功能。**只定位；实时依据永远是卡原文 + 对应代码。**",
        "",
    ]
    all_rows: list[tuple] = []
    for dev_id, role in team.items():
        rows = card_rows(dev / "tasks" / dev_id, "active") + card_rows(dev / "tasks" / dev_id / "done", "done")
        lines += [f"## {dev_id} · {role}", "", "| uuid8 | 标题 | status | area | 位置 |", "|---|---|---|---|---|"]
        for r in rows:
            lines.append("| " + " | ".join(str(c or "-") for c in r) + " |")
            all_rows.append((dev_id,) + r)
        if not rows:
            lines.append("| _（名下无卡）_ | | | | |")
        lines.append("")
    pool = card_rows(dev / "tasks/pool", "pool")
    lines += ["## pool · 待分配", "", "| uuid8 | 标题 | status | area |", "|---|---|---|---|"]
    for r in pool:
        lines.append("| " + " | ".join(str(c or "-") for c in r[:4]) + " |")
    if not pool:
        lines.append("| _（池空）_ | | | |")
    lines.append("")
    areas: dict = {}
    for r in all_rows:
        areas.setdefault(r[4] or "-", []).append(r)
    lines += ["## 按 area 功能索引", "", "| area | 卡(uuid8 · status) | developer |", "|---|---|---|"]
    for a in sorted(areas):
        for r in areas[a]:
            lines.append(f"| {a} | {r[1]} · {r[3]} | {r[0]} |")
    out[str(dev / "DEVMAP.md")] = "\n".join(lines) + "\n"

    for rel in _NAV_FOLDERS:
        base = dev / rel
        if not base.is_dir():
            continue
        nl = [f"# _NAV · {rel}/（生成 · 勿手改 · 跑 build_dev_map.py）", "",
              "> developer → 文件 + 梗概。**只定位；实时看原文。**", ""]
        for devdir in sorted(base.glob("*")):
            if not devdir.is_dir():
                continue
            nl.append(f"## {devdir.name}")
            files = [p for p in sorted(devdir.rglob("*.md"))]
            for p in files:
                nl.append(f"- `{p.relative_to(base)}` — {first_title(p)}")
            if not files:
                nl.append("- _（空）_")
            nl.append("")
        out[str(base / "_NAV.md")] = "\n".join(nl) + "\n"
    return out


if __name__ == "__main__":
    DEV = Path(__file__).resolve().parents[1]
    written = render(DEV)
    for p, c in written.items():
        Path(p).write_text(c, encoding="utf-8")
    n_nav = sum(1 for p in written if p.endswith("_NAV.md"))
    print(f"已写 DEVMAP.md + {n_nav} 个 folder _NAV.md")
