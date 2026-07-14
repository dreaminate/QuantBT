#!/usr/bin/env python3
"""dev/scripts 共用库（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

单一源(RULES §1):frontmatter 解析 / TEAM 读取 / 卡遍历 / OQ 标签统计 只在这里实现一份,
validate_dev / os.py / build_trace 均 import 本库(存量 build_* 逐步迁移)。
"""
from __future__ import annotations

import re
from pathlib import Path

_LEGACY_ID = re.compile(r"^T-\d{3,4}$")
_UUID8 = re.compile(r"^[0-9a-f]{8}$")
_UUID32 = re.compile(r"^[0-9a-f]{32}$")
AREA_SLUG = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_-]+)?$")

# 派生视图(不入库;dev/.gitignore 同口径,相对 dev/)
DERIVED_REL = [
    "DEVMAP.md",
    "tasks/LEDGER.md",
    "tasks/ASSIGNMENT_BOARD.md",
    "research/TRACE.coverage.md",
]


def parse_frontmatter(txt: str) -> dict:
    """解析 YAML frontmatter(极简:key: value + depends_on 列表)。无则 {}。"""
    if not txt.lstrip().startswith("---"):
        return {}
    lines = txt.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "---"), None)
    if start is None:
        return {}
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    fm: dict = {}
    key = None
    for ln in lines[start + 1:end]:
        if re.match(r"^\s*-\s+", ln) and key == "depends_on":
            fm.setdefault("depends_on", []).append(re.sub(r"\s{2,}#.*$", "", ln.split("-", 1)[1]).strip().strip("'\""))
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", ln)
        if not m:
            continue
        k, v = m.group(1), re.sub(r"\s{2,}#.*$", "", m.group(2)).strip()
        key = k
        if k == "depends_on":
            if v.startswith("["):
                inner = v.strip("[]").strip()
                fm["depends_on"] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            else:
                fm.setdefault("depends_on", [])
        else:
            fm[k] = v
    return fm


def read_team(dev: Path) -> dict:
    """TEAM.md → {developer_id: role}。"""
    p = dev / "TEAM.md"
    team: dict = {}
    if not p.is_file():
        return team
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        did, role = cells[0], cells[1]
        if role in ("leader", "admin", "developer"):
            team[did] = role
    return team


def read_identity(dev: Path) -> str | None:
    idp = dev / ".identity"
    if not idp.is_file():
        return None
    txt = idp.read_text(encoding="utf-8").strip()
    return txt.splitlines()[0].strip() if txt else None


def load_card(d: Path, owner_folder: str, loc: str) -> dict:
    """读一张卡 → 统一结构。新卡读 frontmatter;冻结历史卡(T-xxx 命名)走 legacy;
    缺 TASK.md / 无 uuid 又非 legacy 命名 → 标坏卡(check_cards 会 FAIL,不放行)。"""
    tm = d / "TASK.md"
    if not tm.is_file():
        return {"legacy": False, "key": "", "name": d.name, "owner": owner_folder, "status": "",
                "deps": [], "review": "", "folder": owner_folder, "loc": loc, "txt": "", "dir": d, "no_task_md": True}
    txt = tm.read_text(encoding="utf-8")
    fm = parse_frontmatter(txt)
    if fm.get("uuid"):
        return {"legacy": False, "key": fm.get("uuid", ""), "name": d.name, "owner": fm.get("owner", ""),
                "status": fm.get("status", ""), "deps": fm.get("depends_on", []) or [],
                "review": fm.get("review_status", ""), "area": fm.get("area", ""),
                "goal_section": fm.get("goal_section", ""), "done_at": fm.get("done_at", ""),
                "folder": owner_folder, "loc": loc, "txt": txt, "dir": d}
    if _LEGACY_ID.match(d.name):  # 冻结历史卡:T-xxx 命名 + body 抽 状态/review
        ms = re.search(r"\*\*状态\*\*[：:]\s*(todo|in_progress|done)", txt)
        mr = re.search(r"review_status[^\d]{0,4}(\d)", txt)
        return {"legacy": True, "key": d.name, "name": d.name, "owner": owner_folder,
                "status": ms.group(1) if ms else "", "deps": [], "review": mr.group(1) if mr else "",
                "area": "", "goal_section": "", "done_at": "",
                "folder": owner_folder, "loc": loc, "txt": txt, "dir": d}
    # 无 uuid 又非 legacy 命名 → 坏的新卡(frontmatter 缺 uuid);key="" 会被 check_cards 的 uuid 检查抓
    return {"legacy": False, "key": "", "name": d.name, "owner": fm.get("owner", ""),
            "status": fm.get("status", ""), "deps": fm.get("depends_on", []) or [],
            "review": fm.get("review_status", ""), "area": fm.get("area", ""),
            "goal_section": fm.get("goal_section", ""), "done_at": fm.get("done_at", ""),
            "folder": owner_folder, "loc": loc, "txt": txt, "dir": d}


def _done_dirs(donebase: Path):
    """done/ 直下的卡目录 + done/archive/<期>/ 下的卡目录(归档卡仍是 done,依赖解析不断链)。"""
    if not donebase.is_dir():
        return
    for d in sorted(donebase.glob("*")):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name == "archive":
            for period in sorted(d.glob("*")):
                if not period.is_dir():
                    continue
                for card in sorted(period.glob("*")):
                    if card.is_dir() and not card.name.startswith("."):
                        yield card, "done(archive)"
            continue
        yield d, "done"


def gather_cards(dev: Path, devs: list[str]) -> list[dict]:
    cards: list[dict] = []
    pool = dev / "tasks/pool"
    if pool.is_dir():
        for d in sorted(pool.glob("*")):
            if d.is_dir() and not d.name.startswith("."):  # 缺 TASK.md 的也收(load_card 标坏卡、不静默忽略)
                cards.append(load_card(d, "wait", "pool"))
    for dev_id in devs:
        base = dev / "tasks" / dev_id
        if not base.is_dir():
            continue
        for d in sorted(base.glob("*")):
            if d.name == "done" or not d.is_dir() or d.name.startswith("."):
                continue
            cards.append(load_card(d, dev_id, "active"))
        for d, loc in _done_dirs(base / "done"):
            cards.append(load_card(d, dev_id, loc))
    return cards


def oq_section_lines(txt: str) -> list[str]:
    """卡的 ## Open Questions 节正文行(不含标题;无该节 → [])。
    聚合**全部**同名节——若卡里出现重复 OQ 节,第二个节里的标签也不许漏(只读第一节 = 标签可被藏)。"""
    out: list[str] = []
    grab = False
    for ln in txt.splitlines():
        if ln.startswith("## "):
            grab = "Open Questions" in ln
            continue
        if grab:
            out.append(ln)
    return out


_TAG_LINE = re.compile(r"^\s*-\s*\*{0,2}\[([^\]\s·]+)")


def oq_tag_counts(txt: str) -> tuple[int, int, list[str]]:
    """OQ 节按**行首列表项**统计标签(散文里的字面量不算) → (待拍数, 已决数, 非规范标签列表)。"""
    pending = decided = 0
    bad: list[str] = []
    for ln in oq_section_lines(txt):
        m = _TAG_LINE.match(ln)
        if not m:
            continue
        tag = m.group(1)
        if tag == "需拍板":
            pending += 1
        elif tag == "已决":
            decided += 1
        else:
            bad.append(tag)
    return pending, decided, bad


def read_areas(dev: Path) -> list[str]:
    """tasks/_areas.md 已注册 slug(表格第一列;占位 <…> 跳过)。文件缺失 → []。"""
    p = dev / "tasks/_areas.md"
    if not p.is_file():
        return []
    out: list[str] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cells or not cells[0] or cells[0] in ("slug", ":---", "---") or set(cells[0]) <= set(":- "):
            continue
        if "<" in cells[0]:
            continue
        out.append(cells[0])
    return out


def find_cycle(graph: dict) -> list | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list = []

    def dfs(n):
        color[n] = GRAY
        stack.append(n)
        for m in graph.get(n, []):
            if color.get(m, BLACK) == GRAY:
                return stack[stack.index(m):] + [m]
            if color.get(m, BLACK) == WHITE:
                r = dfs(m)
                if r:
                    return r
        color[n] = BLACK
        stack.pop()
        return None

    for n in graph:
        if color[n] == WHITE:
            r = dfs(n)
            if r:
                return r
    return None
