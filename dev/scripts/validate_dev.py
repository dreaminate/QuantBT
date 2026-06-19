#!/usr/bin/env python3
"""dev/ 开发 OS 结构校验器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

团队并发版：身份 + folder 化布局 + 任务卡 frontmatter + 依赖 DAG（无环/无悬空）。
只管 **OS 结构**；项目专属检查在 `validate_project.py`（【项目级别】填），本脚本自动连带跑。

跑：  python dev/scripts/validate_dev.py
退出码 0 = 全过；1 = 有 FAIL。CI / pre-commit 可挂这个。
适配新项目：**别动本文件**，只改 `validate_project.py`。

布局（团队并发）：
  全局单文件：GOAL / CODEMAP / RULES / RULES.project / README / TEAM.md
  本机身份：  dev/.identity（gitignore，值=本机 developer_id，须 ∈ TEAM.md）
  per-dev folder（committed）：state|board|log|experience|decisions|issues / {developer_id}/...
  任务卡：    tasks/pool/{uuid8}/（owner:wait） · tasks/{developer_id}/{uuid8}/ · tasks/{developer_id}/done/{uuid8}/
  卡 id：     文件夹名=uuid 前8位 hex；frontmatter.uuid=全32位；依赖锚全32位 uuid。冻结历史卡保 legacy T-xxx（兼容,不重 mint）。
  研究台：    research/{ideas,active,findings}/{developer_id}/...（INDEX/TRACE=全局聚合视图）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]          # dev/
ROOT = DEV.parent                                  # 仓库根

# ---------- 解析工具 ----------

def parse_frontmatter(txt: str) -> dict:
    """解析任务卡顶部 YAML frontmatter（极简：key: value + depends_on 列表）。无则返回 {}。"""
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


_LEGACY_ID = re.compile(r"^T-\d{3,4}$")
_UUID8 = re.compile(r"^[0-9a-f]{8}$")
_UUID32 = re.compile(r"^[0-9a-f]{32}$")


def load_card(d: Path, owner_folder: str, loc: str) -> dict:
    """读一张卡 → 统一结构。新卡读 frontmatter；冻结历史卡（无 frontmatter）走 legacy。"""
    txt = (d / "TASK.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(txt)
    if fm.get("uuid"):
        return {"legacy": False, "key": fm.get("uuid", ""), "name": d.name, "owner": fm.get("owner", ""),
                "status": fm.get("status", ""), "deps": fm.get("depends_on", []) or [],
                "review": fm.get("review_status", ""), "folder": owner_folder, "loc": loc, "txt": txt, "dir": d}
    # legacy 冻结卡：从 body 抽 状态/review
    ms = re.search(r"\*\*状态\*\*[：:]\s*(todo|in_progress|done)", txt)
    mr = re.search(r"review_status[^\d]{0,4}(\d)", txt)
    return {"legacy": True, "key": d.name, "name": d.name, "owner": owner_folder,
            "status": ms.group(1) if ms else "", "deps": [], "review": mr.group(1) if mr else "",
            "folder": owner_folder, "loc": loc, "txt": txt, "dir": d}


def gather_cards(dev: Path, devs: list[str]) -> list[dict]:
    cards: list[dict] = []
    pool = dev / "tasks/pool"
    if pool.is_dir():
        for d in sorted(pool.glob("*")):
            if d.is_dir() and (d / "TASK.md").is_file():
                cards.append(load_card(d, "wait", "pool"))
    for dev_id in devs:
        base = dev / "tasks" / dev_id
        if not base.is_dir():
            continue
        for d in sorted(base.glob("*")):
            if d.name == "done" or not d.is_dir() or not (d / "TASK.md").is_file():
                continue
            cards.append(load_card(d, dev_id, "active"))
        donebase = base / "done"
        if donebase.is_dir():
            for d in sorted(donebase.glob("*")):
                if d.is_dir() and (d / "TASK.md").is_file():
                    cards.append(load_card(d, dev_id, "done"))
    return cards


# ---------- 检查 ----------

def run_os_checks(dev: Path) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []

    # 1. 全局单文件（团队并发：DECISIONS/ISSUES/STATE/LOG/experience/BOARD 已 folder 化,不在此）
    for rel in ["GOAL.md", "CODEMAP.md", "RULES.md", "RULES.project.md", "README.md", "TEAM.md"]:
        (oks if (dev / rel).is_file() else fails).append(f"全局文件 {rel}")

    # 2. folder 化目录 + 骨架目录（固定名）
    for rel in ["state", "board", "log", "experience", "decisions", "issues",
                "tasks/pool", "tasks/_templates",
                "research/ideas", "research/active", "research/findings", "research/archive",
                "exec", "scripts"]:
        (oks if (dev / rel).is_dir() else fails).append(f"目录 {rel}/")

    # 2b. OS 结构文件（固定名）
    os_files = [
        "research/INDEX.md", "research/TRACE.md", "research/WORKFLOW.md",
        "exec/HANDOFF.md",
        "scripts/validate_project.py", "scripts/build_ledger.py", "scripts/build_log_index.py",
        "scripts/build_card_counters.py", "scripts/build_board.py", "scripts/build_dev_map.py", "scripts/README.md",
        "tasks/_templates/TASK.md",
        "research/ideas/_TEMPLATE.md", "research/active/_TEMPLATE.md", "research/findings/_TEMPLATE.md",
    ]
    for rel in os_files:
        (oks if (dev / rel).is_file() else fails).append(f"OS 结构文件 {rel}")
    (oks if (dev.parent / "CLAUDE.md").is_file() else fails).append("OS 结构文件 CLAUDE.md(根)")
    return oks, fails


def check_identity_team(dev: Path, team: dict) -> tuple[list[str], list[str], str | None]:
    """.identity 存在 + ∈ TEAM；TEAM 恰好 1 个 leader。返回 (oks, fails, my_id)。"""
    oks: list[str] = []
    fails: list[str] = []
    my_id = None
    idp = dev / ".identity"
    if not idp.is_file():
        fails.append(".identity 缺失（本机开发者身份；gitignore、各人本地建,值须 ∈ TEAM.md）")
    else:
        my_id = idp.read_text(encoding="utf-8").strip().splitlines()[0].strip() if idp.read_text(encoding="utf-8").strip() else ""
        if not my_id:
            fails.append(".identity 为空")
        elif my_id not in team:
            fails.append(f".identity「{my_id}」不在 TEAM.md 花名册（须先在 TEAM.md 登记）")
        else:
            oks.append(f"本机身份 {my_id}（role={team[my_id]}）")
    if team:
        leaders = [d for d, r in team.items() if r == "leader"]
        if len(leaders) == 1:
            oks.append(f"TEAM.md leader 唯一（{leaders[0]}）")
        elif len(leaders) == 0:
            fails.append("TEAM.md 无 leader（须恰好 1 个）")
        else:
            fails.append(f"TEAM.md leader 不唯一：{leaders}（须恰好 1 个）")
    return oks, fails, my_id


def check_my_status(dev: Path, my_id: str | None) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    if not my_id:
        return oks, fails
    sp = dev / "state" / my_id / "state.md"
    (oks if sp.is_file() else fails).append(f"本机 state（state/{my_id}/state.md）")
    return oks, fails


def check_cards(dev: Path, cards: list[dict]) -> tuple[list[str], list[str]]:
    """卡：owner==folder · 新卡文件名==uuid8 · status 合法 · 依赖无悬空 · DAG 无环。"""
    oks: list[str] = []
    fails: list[str] = []
    keys = {c["key"] for c in cards if c["key"]}
    for c in cards:
        tag = c["name"]
        # owner == 所在 folder
        if not c["legacy"] and c["owner"] != c["folder"]:
            fails.append(f"卡 {tag}：frontmatter owner「{c['owner']}」≠ 所在文件夹「{c['folder']}」")
        # 新卡：文件夹名 == uuid 前 8 位
        if not c["legacy"]:
            if not _UUID32.match(c["key"]):
                fails.append(f"卡 {tag}：uuid「{c['key']}」非 32 位 hex")
            elif c["name"] != c["key"][:8]:
                fails.append(f"卡 {tag}：文件夹名应 = uuid 前 8 位「{c['key'][:8]}」")
        # status 合法
        if c["status"] and c["status"] not in ("todo", "in_progress", "done"):
            fails.append(f"卡 {tag}：status「{c['status']}」非法（todo|in_progress|done）")
        # done 卡须在 done/ 且 status=done
        if c["loc"] == "done" and c["status"] and c["status"] != "done":
            fails.append(f"卡 {tag}：在 done/ 但 status≠done")
        # 依赖无悬空（uuid 或 legacy id 都接受）
        for dep in c["deps"]:
            if dep and dep not in keys:
                fails.append(f"卡 {tag}：依赖「{dep[:12]}」无对应卡（悬空依赖）")
    # DAG 无环（只对有 deps 的卡建图）
    graph = {c["key"]: [d for d in c["deps"] if d in keys] for c in cards if c["key"]}
    cycle = _find_cycle(graph)
    if cycle:
        fails.append(f"任务 DAG 成环：{' → '.join(x[:8] for x in cycle)}（依赖必须无环）")
    elif graph:
        oks.append(f"任务 DAG 无环 + 依赖无悬空（{len(cards)} 卡）")
    return oks, fails


def _find_cycle(graph: dict) -> list | None:
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


def _lint_state_evidence(dev: Path) -> tuple[list[str], list[str]]:
    """所有 state/*/state.md 的「确定 ✅」行须挂可指认证据（防假绿灯）。"""
    oks: list[str] = []
    fails: list[str] = []
    base = dev / "state"
    if not base.is_dir():
        return oks, fails
    n = 0
    for p in sorted(base.glob("*/state.md")):
        status_i = ev_i = None
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "|" not in ln:
                status_i = ev_i = None
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if "状态" in cells and "证据" in cells:
                status_i, ev_i = cells.index("状态"), cells.index("证据")
                continue
            if status_i is None or set(ln.strip()) <= set("|-: "):
                continue
            if len(cells) <= max(status_i, ev_i):
                continue
            status, ev = cells[status_i], cells[ev_i]
            if "✅" in status and "⬜" not in status and "🟡" not in status and "<" not in status:
                n += 1
                if not re.search(r"\.\w{1,5}\b|passed|passing|绿|通过|\d", ev):
                    fails.append(f"{p.parent.name}/state ✅ 行证据空泛(疑假绿灯):「{status[:18]}」/「{ev[:28]}」")
    if n and not fails:
        oks.append(f"state ✅ 行均挂可指认证据({n} 行)")
    return oks, fails


RULES_CANARY = ["对抗测试", "扩展不替换", "不自作主张改", "致命错误", "🟡", "框架"]


def _canary_rules(dev: Path) -> list[str]:
    p = dev / "RULES.md"
    if not p.is_file():
        return []
    txt = p.read_text(encoding="utf-8")
    missing = [s for s in RULES_CANARY if s not in txt]
    if missing:
        return [f"RULES.md 缺核心不变量 {missing} —— 疑被精简;非授权 OS 级改动请复原,授权了同步回 Multi-Dev-Os"]
    return []


_TASK_REQUIRED = ["Scope", "接线点", "对抗测试", "验收"]


def _lint_task_cards(cards: list[dict]) -> tuple[list[str], list[str]]:
    """OQ 标签/计数器 + todo 完善度 + review_status。"""
    fails: list[str] = []
    warns: list[str] = []

    def _headers(txt):
        return [ln[3:].strip() for ln in txt.splitlines() if ln.startswith("## ")]

    def _pending(txt):
        return txt.count("[需拍板")

    def _oq_issues(txt):
        header, body, grab = None, [], False
        for ln in txt.splitlines():
            if ln.startswith("## ") and "Open Questions" in ln:
                header, grab = ln, True
                continue
            if grab and ln.startswith("## "):
                break
            if grab:
                body.append(ln)
        if not header:
            return []
        issues = []
        bad = [m.group(1) for ln in body if (m := re.match(r"-\s*\*{0,2}\[([^\]\s·]+)", ln)) and m.group(1) not in ("需拍板", "已决")]
        if bad:
            issues.append(f"非规范决策标签 {bad} —— 只认 [需拍板]/[已决](标签漂→计数连锁错,RULES §7)")
        m = re.search(r"已决[^\d\n]{0,4}(\d+)\s*/\s*(\d+)", header)
        if m:
            b = "\n".join(body)
            ap, ad = b.count("[需拍板"), b.count("[已决")
            if (int(m.group(1)), int(m.group(2))) != (ad, ap + ad):
                issues.append(f"计数器 已决 {m.group(1)}/{m.group(2)} 与标签不符(实 [已决]×{ad}/[需拍板]×{ap} → 应 {ad}/{ap + ad};跑 build_card_counters.py)")
        return issues

    pending_review = []
    for c in cards:
        txt, tag = c["txt"], c["name"]
        for iss in _oq_issues(txt):
            warns.append(f"{tag} Open Questions {iss}")
        if c["loc"] == "done" and _pending(txt):
            fails.append(f"{tag}(done)Open Questions 待拍={_pending(txt)}>0 —— done 不可有未拍板项")
        if c["loc"] == "active" and c["status"] == "todo":
            if _pending(txt):
                warns.append(f"{tag} 状态=todo 但 待拍={_pending(txt)}>0 —— todo 应拍板完(RULES §7)")
            if not c["legacy"]:
                missing = [k for k in _TASK_REQUIRED if not any(k in h for h in _headers(txt))]
                if missing:
                    warns.append(f"{tag} 状态=todo 但缺 [必填] 节 {missing}")
        if c["loc"] == "active" and str(c["review"]) == "0":
            pending_review.append(tag)
    if pending_review:
        warns.append(f"卡未经确认(review_status:0):{', '.join(pending_review)} —— 取卡实现/落档前需被分配者过目(RULES §7)")
    return fails, warns


# ---------- 主流程 ----------

team = read_team(DEV)
devs = list(team.keys())
cards = gather_cards(DEV, devs)

oks, fails = run_os_checks(DEV)
i_oks, i_fails, my_id = check_identity_team(DEV, team)
oks += i_oks; fails += i_fails
m_oks, m_fails = check_my_status(DEV, my_id)
oks += m_oks; fails += m_fails
c_oks, c_fails = check_cards(DEV, cards)
oks += c_oks; fails += c_fails
s_oks, s_fails = _lint_state_evidence(DEV)
oks += s_oks; fails += s_fails
t_fails, t_warns = _lint_task_cards(cards)
fails += t_fails
warns = _canary_rules(DEV) + t_warns

try:
    sys.path.insert(0, str(DEV / "scripts"))
    from validate_project import project_checks  # type: ignore

    p_oks, p_fails = project_checks(DEV, ROOT)
    oks += p_oks; fails += p_fails
except ModuleNotFoundError:
    oks.append("（无 validate_project.py，跳过项目检查）")

print(f"dev/ 完整性校验（团队并发）—— {len(oks)} ✅  /  {len(fails)} ❌  /  {len(warns)} ⚠️\n")
for m in oks:
    print(f"  ✅ {m}")
if warns:
    print()
    for m in warns:
        print(f"  ⚠️  {m}")
if fails:
    print()
    for m in fails:
        print(f"  ❌ {m}")
    print(f"\nFAIL（{len(fails)} 项）")
    sys.exit(1)
print("\nPASS —— harness 自检通过")
sys.exit(0)
