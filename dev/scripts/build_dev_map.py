#!/usr/bin/env python3
"""全局导航 map 生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

遍历所有 developer folder → 生成导航 map（**只定位;实时依据永远是原文 + 对应代码**）：
  dev/DEVMAP.md   **活跃面**:developer(+role) → active 卡 + pool 待分配 + 按 area 索引。
                  done 只给计数(活死分离,导航不被落档卡淹没)——全量历史看 build_ledger.py。
  {decisions,issues,state,log,experience,research/ideas,research/active,research/findings}/_NAV.md
                  developer → 文件 + 一行梗概
派生视图**不入库**(dev/.gitignore 已挡),现用现生成:os.py refresh 一键重建。
跑：  python dev/scripts/build_dev_map.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oslib import gather_cards, oq_tag_counts, read_team  # noqa: E402

_NAV_FOLDERS = ["decisions", "issues", "state", "log", "experience",
                "research/ideas", "research/active", "research/findings"]


def first_title(p: Path) -> str:
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            return ln.lstrip("# ").strip()[:60]
        if ln.strip() and not ln.startswith("---"):
            return ln.strip()[:60]
    return ""


def _row(c: dict) -> str:
    fm_title = ""
    for ln in c["txt"].splitlines():
        if ln.startswith("title:"):
            fm_title = ln.split(":", 1)[1].split("#")[0].strip()
            break
    pend, _dec, _bad = oq_tag_counts(c["txt"])
    pend_s = str(pend) if pend else "-"
    return f"| {c['name']} | {fm_title or c['name']} | {c['status'] or '?'} | {c.get('area') or '-'} | {pend_s} |"


def render(dev: Path) -> dict:
    """返回 {绝对路径(str): 内容} for DEVMAP.md + 各存在 folder 的 _NAV.md。不写盘。"""
    out: dict = {}
    team = read_team(dev)
    cards = gather_cards(dev, list(team.keys()))
    lines = [
        "# DEVMAP · 全局任务导航 · 活跃面（生成 · 勿手改/勿入库 · os.py refresh 重建）",
        "",
        "> 谁手上有什么活 + pool 里等分配的。**只定位;实时依据永远是卡原文 + 对应代码。**",
        "> 活死分离:done 只计数,全量历史 `python dev/scripts/build_ledger.py`。",
        "",
    ]
    active_rows: list = []
    for dev_id, role in team.items():
        mine = [c for c in cards if c["folder"] == dev_id]
        act = [c for c in mine if c["loc"] == "active"]
        n_done = sum(1 for c in mine if c["loc"].startswith("done"))
        n_arch = sum(1 for c in mine if c["loc"] == "done(archive)")
        lines += [f"## {dev_id} · {role}", "", "| uuid8 | 标题 | status | area | 待拍 |", "|---|---|---|---|---|"]
        for c in act:
            lines.append(_row(c))
            active_rows.append((dev_id, c))
        if not act:
            lines.append("| _（名下无 active 卡）_ | | | | |")
        lines += ["", f"done 落档 {n_done} 张(含归档 {n_arch})——看 `tasks/{dev_id}/done/` 或 ledger。", ""]
    pool = [c for c in cards if c["loc"] == "pool"]
    lines += ["## pool · 待分配", "", "| uuid8 | 标题 | status | area | 待拍 |", "|---|---|---|---|---|"]
    for c in pool:
        lines.append(_row(c))
        active_rows.append(("wait", c))
    if not pool:
        lines.append("| _（池空）_ | | | | |")
    lines.append("")
    areas: dict = {}
    for who, c in active_rows:
        areas.setdefault(c.get("area") or "-", []).append((who, c))
    lines += ["## 按 area 功能索引（活跃卡）", "", "| area | 卡(uuid8 · status) | developer |", "|---|---|---|"]
    for a in sorted(areas):
        for who, c in areas[a]:
            lines.append(f"| {a} | {c['name']} · {c['status'] or '?'} | {who} |")
    out[str(dev / "DEVMAP.md")] = "\n".join(lines) + "\n"

    for rel in _NAV_FOLDERS:
        base = dev / rel
        if not base.is_dir():
            continue
        nl = [f"# _NAV · {rel}/（生成 · 勿手改/勿入库 · os.py refresh 重建）", "",
              "> developer → 文件 + 梗概。**只定位;实时看原文。**", ""]
        for devdir in sorted(base.glob("*")):
            if not devdir.is_dir() or devdir.name == "__pycache__":
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
    print(f"已写 DEVMAP.md(活跃面) + {n_nav} 个 folder _NAV.md(派生视图,不入库)")
