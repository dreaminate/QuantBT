#!/usr/bin/env python3
"""dev/ 开发 OS 结构校验器（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

团队并发版：身份 + folder 化布局 + 任务卡 frontmatter + 依赖 DAG（无环/无悬空）。
只管 **OS 结构**；项目专属检查在 `validate_project.py`（【项目级别】填），本脚本自动连带跑。

跑：  python dev/scripts/validate_dev.py    (或 os.py validate)
退出码 0 = 全过；1 = 有 FAIL。CI / pre-commit 可挂这个。
适配新项目：**别动本文件**，只改 `validate_project.py`。

布局（团队并发）：
  全局单文件：GOAL / CODEMAP / RULES / RULES.project / README / TEAM.md
  本机身份：  dev/.identity（dev/.gitignore 已挡，值=本机 developer_id，须 ∈ TEAM.md）
  per-dev folder（committed）：state|board|log|experience|decisions|issues / {developer_id}/...
    state/{id}/state.md    重生型 gap 表(续接快照禁入,归 frontier.md;本闸抓堆叠/超限)
    state/{id}/frontier.md 重生型前沿快照(允许长,每 loop 整篇覆写)
    log/{id}/log.md        追加型当月 + archive/YYYY-MM.md 按月滚动(os.py log 自动)
  任务卡：    tasks/pool/{uuid8}/（owner:wait） · tasks/{developer_id}/{uuid8}/ ·
              tasks/{developer_id}/done/{uuid8}/ · done/archive/YYYY-QN/{uuid8}/(季度归档,仍算 done)
  卡 id：     文件夹名=uuid 前8位 hex；frontmatter.uuid=全32位；依赖锚全32位 uuid。冻结历史卡保 legacy T-xxx。
  area：      须 ∈ tasks/_areas.md 词表(slug 语法强制,防导航轴碎片化)
  派生视图：  DEVMAP/_NAV/board/LEDGER/TRACE.coverage **不入库**(dev/.gitignore),现用现生成(os.py refresh)
  研究台：    research/{ideas,active,findings}/{developer_id}/...(+ findings/_shared/ 共享槽)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oslib import (  # noqa: E402
    AREA_SLUG, _UUID32, find_cycle, gather_cards, oq_tag_counts, read_areas, read_team,
)

DEV = Path(__file__).resolve().parents[1]          # dev/
ROOT = DEV.parent                                  # 仓库根


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
                "research/findings/_shared",
                "exec", "scripts"]:
        (oks if (dev / rel).is_dir() else fails).append(f"目录 {rel}/")

    # 2b. OS 结构文件（固定名）
    os_files = [
        ".gitignore",
        "research/INDEX.md", "research/TRACE.md", "research/WORKFLOW.md",
        "exec/HANDOFF.md",
        "scripts/validate_project.py", "scripts/_oslib.py", "scripts/os.py",
        "scripts/build_ledger.py", "scripts/build_log_index.py", "scripts/build_trace.py",
        "scripts/build_board.py", "scripts/build_dev_map.py", "scripts/README.md",
        "tasks/_templates/TASK.md", "tasks/_areas.md",
        "research/ideas/README.md", "research/ideas/_TEMPLATE.md",
        "research/active/README.md", "research/active/_TEMPLATE.md",
        "research/findings/_TEMPLATE.md",
        "state/_TEMPLATE.md", "state/_TEMPLATE.frontier.md",
        "log/_TEMPLATE.md", "decisions/_TEMPLATE.md",
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
        fails.append(".identity 缺失（本机开发者身份；dev/.gitignore 已挡、各人本地建,值须 ∈ TEAM.md）")
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
    """本机 log（session 落档,本地产物）。state 落地见 check_member_states（全员）。"""
    oks: list[str] = []
    fails: list[str] = []
    if not my_id:
        return oks, fails
    lp = dev / "log" / my_id / "log.md"
    (oks if lp.is_file() else fails).append(f"本机 log（log/{my_id}/log.md）—— 每 session 末落一条（RULES §8;os.py log）")
    return oks, fails


def check_member_states(dev: Path, team: dict, cards: list[dict]) -> tuple[list[str], list[str]]:
    """手上有 active 卡的**真实**(非 <占位>)成员须有 state/{id}/state.md —— 在干活就得记对照 GOAL 的现状,
    不只本机一人(防别人 gap 长期空着 / CI 无 .identity 时整段跳过）。
    占位成员(<leader_id> 等)、没领 active 卡的成员跳过,不误伤范式仓与挂名新人。"""
    oks: list[str] = []
    fails: list[str] = []
    active_owners = {c["folder"] for c in cards if c["loc"] == "active"}
    real = [d for d in team if "<" not in d and ">" not in d and d in active_owners]
    if not real:
        oks.append("（无真实成员持 active 卡，跳过持卡成员 state 检查）")
        return oks, fails
    missing = [d for d in real if not (dev / "state" / d / "state.md").is_file()]
    for d in missing:
        fails.append(f"成员 {d} 持 active 卡但缺 state/{d}/state.md —— 在干活须维护对照 GOAL 的现状（RULES §8；用 state/_TEMPLATE.md）")
    if not missing:
        oks.append(f"持卡成员 state 落地（{len(real)} 人 state.md 齐）")
    return oks, fails


def check_task_folders(dev: Path, devs: list[str]) -> tuple[list[str], list[str]]:
    """tasks/ 下每个文件夹须是 pool / _* 元目录 / TEAM 里的 developer_id —— 防孤儿卡 / owner 不在 TEAM。"""
    oks: list[str] = []
    fails: list[str] = []
    base = dev / "tasks"
    if not base.is_dir():
        return oks, fails
    unknown = [d.name for d in sorted(base.glob("*"))
               if d.is_dir() and d.name != "pool" and not d.name.startswith("_") and d.name not in devs]
    if unknown:
        fails.append(f"tasks/ 下未知归属文件夹 {unknown} —— 须是 pool / TEAM 里的 developer_id（孤儿卡 / owner 不在 TEAM）")
    else:
        oks.append("tasks/ 文件夹归属合法（pool + TEAM developer_id）")
    return oks, fails


def check_research_folders(dev: Path, devs: list[str]) -> tuple[list[str], list[str]]:
    """research/{ideas,active,findings}/ 一级目录须 ∈ TEAM ∪ {_shared} —— folder 化归属在研究台同样有牙
    （镜像 check_task_folders;共享型研究产物有名分:findings/_shared/<topic>/,别挤 per-dev 区或死在 /tmp）。"""
    oks: list[str] = []
    fails: list[str] = []
    bad: list[str] = []
    for rel in ["research/ideas", "research/active", "research/findings"]:
        base = dev / rel
        if not base.is_dir():
            continue
        for d in sorted(base.glob("*")):
            if not d.is_dir() or d.name == "__pycache__":
                continue
            if d.name not in devs and d.name != "_shared":
                bad.append(f"{rel}/{d.name}/")
    if bad:
        fails.append(f"研究台未知归属目录 {bad} —— 须是 TEAM developer_id 或 _shared/（共享产物槽）")
    else:
        oks.append("研究台目录归属合法（TEAM developer_id + _shared）")
    return oks, fails


def check_cards(dev: Path, cards: list[dict]) -> tuple[list[str], list[str]]:
    """卡：owner==folder · 新卡文件名==uuid8 · status 合法 · 依赖无悬空 · DAG 无环。"""
    oks: list[str] = []
    fails: list[str] = []
    keys = {c["key"] for c in cards if c["key"] and not c.get("no_task_md")}
    seen: dict = {}
    for c in cards:
        if c["key"] and not c.get("no_task_md"):
            seen.setdefault(c["key"], []).append(c["name"])
    for k, names in seen.items():
        if len(names) > 1:
            fails.append(f"uuid/id 重复：{k[:12]} 被 {names} 多卡共用（身份须唯一）")
    dangling = False
    for c in cards:
        tag = c["name"]
        if c.get("no_task_md"):
            fails.append(f"卡目录 {c['folder']}/{tag}/ 缺 TASK.md（空壳/坏卡）")
            continue
        if not c["legacy"] and c["owner"] != c["folder"]:
            fails.append(f"卡 {tag}：frontmatter owner「{c['owner']}」≠ 所在文件夹「{c['folder']}」")
        if not c["legacy"]:
            if not _UUID32.match(c["key"]):
                fails.append(f"卡 {tag}：uuid「{c['key']}」非 32 位 hex（新卡 frontmatter.uuid 必填且合法）")
            elif c["name"] != c["key"][:8]:
                fails.append(f"卡 {tag}：文件夹名应 = uuid 前 8 位「{c['key'][:8]}」")
        if c["status"] and c["status"] not in ("todo", "in_progress", "done"):
            fails.append(f"卡 {tag}：status「{c['status']}」非法（todo|in_progress|done）")
        # done/（含季度归档）里的新卡必须 status=done(缺 status 也不行;legacy 冻结卡格式各异、宽容)
        if c["loc"].startswith("done") and not c["legacy"] and c["status"] != "done":
            fails.append(f"卡 {tag}：在 {c['loc']} 但 status≠done（实「{c['status'] or '空'}」）")
        for dep in c["deps"]:
            if dep and dep not in keys:
                fails.append(f"卡 {tag}：依赖「{dep[:12]}」无对应卡（悬空依赖;归档卡也在解析范围,不是归档背锅）")
                dangling = True
    graph = {c["key"]: [d for d in c["deps"] if d in keys] for c in cards if c["key"] and not c.get("no_task_md")}
    cycle = find_cycle(graph)
    if cycle:
        fails.append(f"任务 DAG 成环：{' → '.join(x[:8] for x in cycle)}（依赖必须无环）")
    elif graph and not dangling:
        oks.append(f"任务 DAG 无环 + 依赖无悬空（{len(cards)} 卡,含归档）")
    return oks, fails


def _lint_card_areas(dev: Path, cards: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """area 是 DEVMAP 分组轴:活跃卡(pool/active)非法 slug → FAIL;未注册 → WARN(先登记 tasks/_areas.md)。
    done 卡不追溯(历史包袱不阻断)。"""
    oks: list[str] = []
    fails: list[str] = []
    warns: list[str] = []
    registered = read_areas(dev)
    bad_syntax: list[str] = []
    unregistered: list[str] = []
    for c in cards:
        if c["legacy"] or c.get("no_task_md") or c["loc"] not in ("pool", "active"):
            continue
        area = (c.get("area") or "").strip()
        if not area:
            continue
        if not AREA_SLUG.match(area):
            bad_syntax.append(f"{c['name']}(area={area!r})")
        elif registered and area not in registered:
            unregistered.append(f"{c['name']}({area})")
    if bad_syntax:
        fails.append(f"area slug 非法 {bad_syntax} —— 语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$（自由文本会把 DEVMAP 分组轴打碎）")
    if unregistered:
        warns.append(f"area 未在 tasks/_areas.md 注册:{', '.join(unregistered)} —— 先登记再用(宁可粗,别细)")
    if not bad_syntax:
        oks.append("活跃卡 area slug 合法")
    return oks, fails, warns


_STATE_HEAD_FORBIDDEN = re.compile(r"^#{1,3}\s.*(上次刷新|本会话续接|前沿快照|frontier)", re.I)
_STATE_MARK_FORBIDDEN = re.compile(r"^>?\s*\**\s*(上次刷新|本会话续接|前沿快照)\s*[：:]")
_STATE_DATED_HEAD = re.compile(r"^#{1,3}\s.*\d{4}-\d{2}-\d{2}")


def _lint_state_shape(dev: Path) -> tuple[list[str], list[str], list[str]]:
    """state.md 是重生型 gap 表:① 续接/刷新块 → FAIL(那是 frontier.md 的职责;堆叠正是 339KB 事故根因)。
    抓两种实测形态:专设标题(## 上次刷新…,一个就 FAIL) + blockquote/裸标记行(> 上次刷新：…,
    ≥2 行=堆叠 FAIL,1 行但 >300 字符=整块现场塞进时间戳行 FAIL;1 行短戳=合法元信息放行)。
    ② 体积 >32KB / 单行 >2000 字符 → WARN(重生型长不到这个量,超限=在堆历史)。frontier.md 不设限。"""
    oks: list[str] = []
    fails: list[str] = []
    warns: list[str] = []
    base = dev / "state"
    if not base.is_dir():
        return oks, fails, warns
    n = 0
    for p in sorted(base.glob("*/state.md")):
        n += 1
        txt = p.read_text(encoding="utf-8")
        heads = [ln.strip()[:40] for ln in txt.splitlines() if _STATE_HEAD_FORBIDDEN.match(ln)]
        marks = [ln for ln in txt.splitlines() if _STATE_MARK_FORBIDDEN.match(ln)]
        stuffed = len(marks) >= 2 or (len(marks) == 1 and len(marks[0]) > 300)
        if heads or stuffed:
            shown = heads + [ln.strip()[:40] for ln in marks[:3]]
            detail = f"(标记行 ×{len(marks)})" if marks else ""
            fails.append(f"{p.parent.name}/state.md 含续接快照块 {shown}{detail} —— 归 state/{p.parent.name}/frontier.md"
                         f"(重生型,整篇覆写;模板 state/_TEMPLATE.frontier.md),state.md 只装 gap 表")
        # 第三种实测形态:日期化小节标题堆叠 = 把 state 当会话日记写(叙事该归 log/frontier)
        dated = [ln.strip()[:40] for ln in txt.splitlines() if _STATE_DATED_HEAD.match(ln)]
        if len(dated) >= 3:
            fails.append(f"{p.parent.name}/state.md 含 {len(dated)} 个日期化小节标题(会话日记形态,如 {dated[:2]}) —— "
                         f"叙事归 log、续接现场归 frontier.md,state 只装对照 GOAL 的 gap 表(日期属于 log,不属于 gap)")
        size = p.stat().st_size
        if size > 32 * 1024:
            warns.append(f"{p.parent.name}/state.md {size // 1024}KB > 32KB —— 重生型该整篇重写,别堆历史(叙事归 log,现场归 frontier)")
        maxline = max((len(ln) for ln in txt.splitlines()), default=0)
        if maxline > 2000:
            warns.append(f"{p.parent.name}/state.md 最长行 {maxline} 字符 > 2000 —— 单行巨块不可读不可 diff,拆行")
    if n and not fails:
        oks.append(f"state 形态合规（{n} 份,无续接块堆叠）")
    return oks, fails, warns


def _lint_state_evidence(dev: Path) -> tuple[list[str], list[str]]:
    """所有 state/*/state.md 的「确定 ✅」行须挂可指认证据（防假绿灯）。
    ① 证据须可指认:file(.ext)/file:line/带口径数字(% 或 a/b)/测试通过词 —— 裸数字(年份/节号)不算证据。
    ② ✅ 须落在规范的「状态|证据」表内:文件含 ✅ 却无该表头 → 诚实门看不见,报 FAIL(防靠不写表头绕过)。"""
    oks: list[str] = []
    fails: list[str] = []
    base = dev / "state"
    if not base.is_dir():
        return oks, fails
    n = 0
    for p in sorted(base.glob("*/state.md")):
        status_i = ev_i = None
        saw_header = False
        txt = p.read_text(encoding="utf-8")
        for ln in txt.splitlines():
            if "|" not in ln:
                status_i = ev_i = None
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if "状态" in cells and "证据" in cells:
                status_i, ev_i = cells.index("状态"), cells.index("证据")
                saw_header = True
                continue
            if status_i is None or set(ln.strip()) <= set("|-: "):
                continue
            if len(cells) <= max(status_i, ev_i):
                continue
            status, ev = cells[status_i], cells[ev_i]
            if "✅" in status and "⬜" not in status and "🟡" not in status and "<" not in status:
                n += 1
                if not re.search(r"\.\w{1,5}\b|:\d|\d+\s*%|\d+\s*/\s*\d+|passed|passing|绿|通过", ev):
                    fails.append(f"{p.parent.name}/state ✅ 行证据空泛(疑假绿灯):「{status[:18]}」/「{ev[:28]}」")
        if "✅" in txt and not saw_header:
            fails.append(f"{p.parent.name}/state 有 ✅ 却无「状态|证据」表头 —— 诚实门看不见(请用 state/_TEMPLATE.md 的表)")
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
    """OQ 标签规范(行首列表项才算,散文字面量不误报) + todo 完善度 + review_status 执行闸。
    计数器已退役:「已决 D/总」不落盘,board/DEVMAP 展示时现算(单一源=标签本身)。"""
    fails: list[str] = []
    warns: list[str] = []

    def _headers(txt):
        return [ln[3:].strip() for ln in txt.splitlines() if ln.startswith("## ")]

    pending_review = []
    for c in cards:
        txt, tag = c["txt"], c["name"]
        pend, _dec, bad = oq_tag_counts(txt)
        if bad:
            warns.append(f"{tag} Open Questions 非规范决策标签 {bad} —— 只认 [需拍板]/[已决](RULES §7)")
        if c["loc"].startswith("done") and pend:
            fails.append(f"{tag}(done)Open Questions 待拍={pend}>0 —— done 不可有未拍板项")
        if c["loc"] == "active" and c["status"] == "todo":
            if pend:
                warns.append(f"{tag} 状态=todo 但 待拍={pend}>0 —— 取卡(→in_progress)前须拍板完(执行闸会硬拦,RULES §7)")
            if not c["legacy"]:
                missing = [k for k in _TASK_REQUIRED if not any(k in h for h in _headers(txt))]
                if missing:
                    warns.append(f"{tag} 状态=todo 但缺 [必填] 节 {missing}")
        # 执行闸（= 取卡闸 review_status=1 且 待拍=0）：in_progress 是正在执行,拍板/确认必须已清,否则硬拦
        if c["loc"] == "active" and c["status"] == "in_progress" and not c["legacy"]:
            if pend:
                fails.append(f"{tag} 状态=in_progress 但 待拍={pend}>0 —— 执行前须拍板完(取卡闸 待拍=0,RULES §7)")
            if str(c["review"]) == "0":
                fails.append(f"{tag} 状态=in_progress 但 review_status=0 —— 执行前须被分配者过目(取卡闸 review=1,RULES §7)")
        if c["loc"] == "active" and c["status"] != "in_progress" and str(c["review"]) == "0":
            pending_review.append(tag)
    if pending_review:
        warns.append(f"卡未经确认(review_status:0):{', '.join(pending_review)} —— 取卡实现/落档前需被分配者过目(RULES §7)")
    return fails, warns


_DERIVED_EXACT = ["DEVMAP.md", "tasks/LEDGER.md", "tasks/ASSIGNMENT_BOARD.md", "research/TRACE.coverage.md"]
_DERIVED_PAT = re.compile(r"(^|/)_NAV\.md$|^board/[^/]+/board\.md$")


def check_derived_not_tracked(dev: Path) -> tuple[list[str], list[str]]:
    """派生视图不入库(取代旧「新鲜度重算比对」门:不入库 = 没有新鲜度要守、多分支零冲突、无需手跑 build_*)。
    dev/.gitignore 挡新增;本检查抓**已被 track** 的存量(升级期迁移:git rm --cached 后即绿)。非 git 环境跳过。"""
    oks: list[str] = []
    fails: list[str] = []
    r = subprocess.run(["git", "ls-files", "--", str(dev)], cwd=dev.parent, capture_output=True, text=True)
    if r.returncode != 0:
        oks.append("（非 git 环境，跳过派生视图入库检查）")
        return oks, fails
    tracked_bad: list[str] = []
    prefix = dev.name + "/"
    for ln in r.stdout.splitlines():
        rel = ln[len(prefix):] if ln.startswith(prefix) else ln
        if rel in _DERIVED_EXACT or _DERIVED_PAT.search(rel):
            tracked_bad.append(rel)
    if tracked_bad:
        fails.append(f"派生视图被 git track:{tracked_bad} —— 派生数据不入库(现用现生成,os.py refresh);"
                     f"迁移:git rm --cached 这些文件(dev/.gitignore 已挡后续)")
    else:
        oks.append("派生视图不入库（DEVMAP/_NAV/board/LEDGER/TRACE.coverage 均未被 track）")
    return oks, fails


# ---------- 主流程 ----------

team = read_team(DEV)
devs = list(team.keys())
cards = gather_cards(DEV, devs)

oks, fails = run_os_checks(DEV)
i_oks, i_fails, my_id = check_identity_team(DEV, team)
oks += i_oks; fails += i_fails
m_oks, m_fails = check_my_status(DEV, my_id)
oks += m_oks; fails += m_fails
ms_oks, ms_fails = check_member_states(DEV, team, cards)
oks += ms_oks; fails += ms_fails
c_oks, c_fails = check_cards(DEV, cards)
oks += c_oks; fails += c_fails
tf_oks, tf_fails = check_task_folders(DEV, devs)
oks += tf_oks; fails += tf_fails
rf_oks, rf_fails = check_research_folders(DEV, devs)
oks += rf_oks; fails += rf_fails
d_oks, d_fails = check_derived_not_tracked(DEV)
oks += d_oks; fails += d_fails
s_oks, s_fails = _lint_state_evidence(DEV)
oks += s_oks; fails += s_fails
sh_oks, sh_fails, sh_warns = _lint_state_shape(DEV)
oks += sh_oks; fails += sh_fails
a_oks, a_fails, a_warns = _lint_card_areas(DEV, cards)
oks += a_oks; fails += a_fails
t_fails, t_warns = _lint_task_cards(cards)
fails += t_fails
warns = _canary_rules(DEV) + sh_warns + a_warns + t_warns

try:
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
