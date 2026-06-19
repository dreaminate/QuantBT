#!/usr/bin/env python3
"""tasks 全含量账本生成器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

团队并发：扫 pool + 每个 developer 的 active/done → 全含量任务表（含 owner 列）。
**从目录现生成,不落第二份手维护账本 → 永不跑偏。** board/{dev}/board.md 是各人活跃版。
`render(dev)` 返回 {LEDGER.md 路径:内容} 供 validate_dev 重算比对新鲜度;LEDGER.md 是
**opt-in committed**(`--write` 才落盘),一旦落盘即被新鲜度门守(改卡没刷→过期 FAIL)。
跑:  python dev/scripts/build_ledger.py          # 打印
     python dev/scripts/build_ledger.py --write  # 另写 dev/tasks/LEDGER.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


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


def card_info(d: Path, owner: str, loc: str) -> dict:
    txt = (d / "TASK.md").read_text(encoding="utf-8") if (d / "TASK.md").is_file() else ""
    f = fm(txt)
    if f.get("uuid"):
        return {"id": d.name, "title": f.get("title", "?"), "状态": f.get("status", "?"),
                "review": f.get("review_status", "?"), "owner": f.get("owner", owner), "位置": loc}
    title = ""
    for line in txt.splitlines():
        m = re.match(r"#\s*\S+\s*·\s*(.+)", line)
        if m:
            title = m.group(1).strip()
            break
    st = re.search(r"\*\*状态\*\*[：:]\s*([^\n·|]+)", txt)
    rv = re.search(r"\*\*review_status\*\*[：:]\s*([0-9])", txt)
    return {"id": d.name, "title": title or "?", "状态": (st.group(1).strip() if st else "?"),
            "review": (rv.group(1) if rv else "?"), "owner": owner, "位置": loc}


def render(dev: Path) -> dict:
    """返回 {tasks/LEDGER.md 绝对路径(str): 内容}。不写盘。"""
    tasks = dev / "tasks"
    team = read_team(dev)
    rows: list[dict] = []
    pool = tasks / "pool"
    if pool.is_dir():
        for d in sorted(pool.glob("*")):
            if d.is_dir() and not d.name.startswith("."):
                rows.append(card_info(d, "wait", "pool"))
    for dev_id in team:
        base = tasks / dev_id
        if not base.is_dir():
            continue
        for d in sorted(base.glob("*")):
            if d.name == "done" or not d.is_dir() or d.name.startswith("."):
                continue
            rows.append(card_info(d, dev_id, "active"))
        if (base / "done").is_dir():
            for d in sorted((base / "done").glob("*")):
                if d.is_dir() and not d.name.startswith("."):
                    rows.append(card_info(d, dev_id, "done"))
    lines = [
        "# LEDGER · 全含量任务账本（自动生成 · 勿手改 · 跑 build_ledger.py 刷新）",
        "",
        "| id | 标题 | 状态 | review | owner | 位置 |",
        "|----|------|------|--------|-------|------|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['title']} | {r['状态']} | {r['review']} | {r['owner']} | {r['位置']} |")
    n_active = sum(1 for r in rows if r["位置"] == "active")
    n_pool = sum(1 for r in rows if r["位置"] == "pool")
    lines += ["", f"共 {len(rows)} 任务（pool {n_pool} / active {n_active} / done {len(rows) - n_active - n_pool}）"]
    return {str(tasks / "LEDGER.md"): "\n".join(lines) + "\n"}


if __name__ == "__main__":
    DEV = Path(__file__).resolve().parents[1]
    out = next(iter(render(DEV).values()))
    if "--write" in sys.argv:
        path = DEV / "tasks" / "LEDGER.md"
        path.write_text(out, encoding="utf-8")
        print(f"已写 {path}")
    else:
        print(out)
