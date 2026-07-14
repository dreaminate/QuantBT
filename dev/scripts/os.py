#!/usr/bin/env python3
"""dev OS 卡生命周期 CLI（【开发os级别】勿改 · clone 自 Multi-Dev-Os）。

把「多步手工 + 手抄 32 位 uuid + 忘跑 build_*」收成原子命令(经验库「validate 四连坑」的解药):
  mint     造卡进 pool:自动 uuid、从模板建卡、--depends-on 接受 uuid8 前缀自动解析成全 32 位
  assign   分配(仅 leader/admin):移目录 + 改 owner/assigned_by 两处同改 + 刷视图
  done     落档:status=done + 盖 done_at + 移 done/ + 刷视图
  archive  done 卡按季归档到 done/archive/YYYY-QN/ + 记 index.md(活跃面瘦身)
  refresh  重建全部派生视图(DEVMAP/_NAV/board/TRACE.coverage —— 派生视图不入库,现用现生成)
  log      按契约格式落一条日志(自动把上月条目滚动到 log/{id}/archive/YYYY-MM.md)
  validate 跑 validate_dev.py

跑:  python dev/scripts/os.py <命令> -h 看各命令参数。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import subprocess
import sys
import uuid as _uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oslib import gather_cards, parse_frontmatter, read_areas, read_identity, read_team  # noqa: E402

DEV = Path(__file__).resolve().parents[1]
ROOT = DEV.parent


def _die(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(1)


def _today() -> str:
    return _dt.date.today().isoformat()


def _now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d-%H%M")


def _me_role() -> tuple[str | None, str | None]:
    team = read_team(DEV)
    me = read_identity(DEV)
    return me, team.get(me) if me else None


def _set_fm(txt: str, key: str, value: str) -> str:
    """改 frontmatter 一个字段(保留行尾注释;字段不存在则插在 frontmatter 末尾)。"""
    lines = txt.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "---"), None)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"), None) if start is not None else None
    if start is None or end is None:
        _die(f"frontmatter 缺失,没法改 {key}")
    pat = re.compile(rf"^({key}:)(\s*)([^#\n]*?)(\s*)(#.*)?$")
    for i in range(start + 1, end):
        m = pat.match(lines[i])
        if m:
            comment = f"  {m.group(5)}" if m.group(5) else ""
            lines[i] = f"{key}: {value}{comment}"
            return "\n".join(lines) + ("\n" if txt.endswith("\n") else "")
    lines.insert(end, f"{key}: {value}")
    return "\n".join(lines) + ("\n" if txt.endswith("\n") else "")


def _move(src: Path, dst: Path) -> None:
    """git mv(卡是 tracked 内容,保 rename 历史);不在 git 环境则退回 shutil.move。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "mv", str(src), str(dst)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        shutil.move(str(src), str(dst))


def _find_card(uuid8: str) -> tuple[Path, dict]:
    team = read_team(DEV)
    cards = gather_cards(DEV, list(team.keys()))
    hits = [c for c in cards if c["name"] == uuid8 or (c["key"] and c["key"].startswith(uuid8))]
    if not hits:
        _die(f"找不到卡 {uuid8}(pool/各 dev active/done 都翻过了)")
    if len(hits) > 1:
        _die(f"前缀 {uuid8} 多义:{[c['name'] for c in hits]},给全一点")
    return hits[0]["dir"], hits[0]


def _resolve_deps(prefixes: list[str]) -> list[str]:
    """uuid8 前缀 → 全 32 位(唯一匹配才放行,fail-closed:多义/无匹配即报错,不悬空)。"""
    team = read_team(DEV)
    keys = [c["key"] for c in gather_cards(DEV, list(team.keys())) if c["key"] and not c["legacy"]]
    out: list[str] = []
    for p in prefixes:
        p = p.strip()
        if not p:
            continue
        hits = sorted({k for k in keys if k.startswith(p)})
        if not hits:
            _die(f"依赖 {p} 无匹配卡(依赖必须先存在,否则 DAG 悬空)")
        if len(hits) > 1:
            _die(f"依赖前缀 {p} 多义:{[h[:12] for h in hits]}")
        out.append(hits[0])
    return out


# ── 命令 ─────────────────────────────────────────────────────────


def cmd_mint(a) -> None:
    tpl = DEV / "tasks/_templates/TASK.md"
    if not tpl.is_file():
        _die("缺 tasks/_templates/TASK.md 模板")
    if a.area:
        registered = read_areas(DEV)
        if registered and a.area not in registered:
            print(f"⚠️  area「{a.area}」未在 tasks/_areas.md 注册(validate 会 WARN;先登记再用更稳)")
    deps = _resolve_deps(a.depends_on.split(",")) if a.depends_on else []
    uid = _uuid.uuid4().hex
    d = DEV / "tasks/pool" / uid[:8]
    if d.exists():
        _die(f"目录已存在:{d}")
    txt = tpl.read_text(encoding="utf-8")
    txt = re.sub(r"<!--.*?-->\n?", "", txt, count=1, flags=re.S)  # 剥模板说明注释
    for k, v in [("uuid", uid), ("title", a.title), ("status", "todo"), ("owner", "wait"),
                 ("priority", a.priority), ("area", a.area or ""), ("source", a.source or ""),
                 ("source_ref", a.source_ref or ""), ("goal_section", a.goal_section or "")]:
        txt = _set_fm(txt, k, v)
    if deps:
        txt = _set_fm(txt, "depends_on", "[" + ", ".join(deps) + "]")
    txt = txt.replace("# <title>", f"# {a.title}", 1)
    d.mkdir(parents=True)
    (d / "TASK.md").write_text(txt, encoding="utf-8")
    print(f"✅ mint tasks/pool/{uid[:8]}/  uuid={uid}")
    print("   下一步:填 [必填] 节(Scope/接线点/对抗测试/验收),再由 leader/admin `os.py assign` 分配")


def cmd_assign(a) -> None:
    me, role = _me_role()
    if role not in ("leader", "admin"):
        _die(f"分配仅 leader/admin(RULES §8);本机身份 {me or '缺失'} role={role or '-'}")
    team = read_team(DEV)
    if a.dev not in team:
        _die(f"{a.dev} 不在 TEAM.md 花名册")
    src, card = _find_card(a.uuid8)
    if card["loc"] != "pool" and not a.force:
        _die(f"卡在 {card['loc']}(owner={card['folder']}),改派加 --force")
    dst = DEV / "tasks" / a.dev / src.name
    _move(src, dst)
    tm = dst / "TASK.md"
    txt = tm.read_text(encoding="utf-8")
    txt = _set_fm(txt, "owner", a.dev)
    txt = _set_fm(txt, "assigned_by", me)
    tm.write_text(txt, encoding="utf-8")
    print(f"✅ assign {src.name} → tasks/{a.dev}/(owner/assigned_by 已同改;待 {a.dev} self-review 置 review_status: 1)")
    cmd_refresh(a)


def cmd_done(a) -> None:
    me, role = _me_role()
    src, card = _find_card(a.uuid8)
    if card["loc"] != "active":
        _die(f"卡 {a.uuid8} 不在 active(现 {card['loc']}),没法落档")
    owner = card["folder"]
    if me != owner and role not in ("leader", "admin"):
        _die(f"只有 owner({owner})或 leader/admin 能落档;本机身份 {me or '缺失'}")
    tm = src / "TASK.md"
    txt = tm.read_text(encoding="utf-8")
    txt = _set_fm(txt, "status", "done")
    txt = _set_fm(txt, "done_at", _today())
    tm.write_text(txt, encoding="utf-8")
    dst = DEV / "tasks" / owner / "done" / src.name
    _move(src, dst)
    print(f"✅ done {src.name} → tasks/{owner}/done/(status=done · done_at={_today()})")
    print(f"   收尾别忘:刷 state/{owner}/state.md + `os.py log \"...\"` + `os.py validate`")
    cmd_refresh(a)


def _quarter(date_str: str) -> str:
    y, m = int(date_str[:4]), int(date_str[5:7])
    return f"{y}-Q{(m - 1) // 3 + 1}"


def cmd_archive(a) -> None:
    now_q = _quarter(_today())
    moved = 0
    for dev_id in read_team(DEV):
        donebase = DEV / "tasks" / dev_id / "done"
        if not donebase.is_dir():
            continue
        for d in sorted(donebase.glob("*")):
            if not d.is_dir() or d.name in ("archive",) or d.name.startswith("."):
                continue
            tm = d / "TASK.md"
            fmd = parse_frontmatter(tm.read_text(encoding="utf-8")) if tm.is_file() else {}
            stamp = fmd.get("done_at") or _dt.date.fromtimestamp(d.stat().st_mtime).isoformat()
            q = _quarter(stamp)
            if q >= now_q and not a.all:  # 当季留在活跃面;--all 连当季一起收
                continue
            dst = donebase / "archive" / q / d.name
            _move(d, dst)
            idx = donebase / "archive" / q / "index.md"
            title = fmd.get("title", d.name)
            area = fmd.get("area", "-")
            if not idx.is_file():
                idx.write_text(f"# done 归档 · {q}（index 由 os.py archive 追加;卡原文就在本目录）\n\n"
                               f"| uuid8 | area | 标题 | done_at |\n|---|---|---|---|\n", encoding="utf-8")
            with idx.open("a", encoding="utf-8") as f:
                f.write(f"| {d.name} | {area} | {title} | {stamp} |\n")
            moved += 1
    print(f"✅ archive:归档 {moved} 张 done 卡(依赖解析不受影响,validate/ledger 照常看得见归档卡)" if moved
          else "archive:没有可归档的 done 卡(当季的留在活跃面;--all 连当季一起收)")
    if moved:
        cmd_refresh(a)


def cmd_refresh(_a=None) -> None:
    import importlib
    n = 0
    for mod, args in [("build_dev_map", ()), ("build_trace", ())]:
        try:
            m = importlib.import_module(mod)
            for p, c in m.render(DEV, *args).items():
                Path(p).parent.mkdir(parents=True, exist_ok=True)
                Path(p).write_text(c, encoding="utf-8")
                n += 1
        except ModuleNotFoundError:
            pass
    me = read_identity(DEV)
    if me:
        m = importlib.import_module("build_board")
        for p, c in m.render(DEV, me).items():
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text(c, encoding="utf-8")
            n += 1
    print(f"✅ refresh:重建 {n} 个派生视图(不入库,dev/.gitignore 已挡)")


_ENTRY = re.compile(r"^## (\d{4}-\d{2})-\d{2}")


def cmd_log(a) -> None:
    me = read_identity(DEV)
    if not me:
        _die("缺 dev/.identity,不知道记到谁名下")
    logdir = DEV / "log" / me
    logdir.mkdir(parents=True, exist_ok=True)
    lp = logdir / "log.md"
    if not lp.is_file():
        tpl = DEV / "log/_TEMPLATE.md"
        head = re.sub(r"<!--.*?-->\n?", "", tpl.read_text(encoding="utf-8"), count=1, flags=re.S) if tpl.is_file() else "# LOG\n"
        head = head.replace("<developer_id>", me)
        lp.write_text(head.split("## YYYY-MM-DD")[0].rstrip() + "\n", encoding="utf-8")
    lines = lp.read_text(encoding="utf-8").splitlines()
    # 滚动:上月及更早的条目切到 archive/YYYY-MM.md(条目=## 日期标题起到下个 ## 前)
    this_month = _today()[:7]
    head_end = next((i for i, ln in enumerate(lines) if _ENTRY.match(ln)), len(lines))
    entries: list[tuple[str, list[str]]] = []
    i = head_end
    while i < len(lines):
        m = _ENTRY.match(lines[i])
        j = next((k for k in range(i + 1, len(lines)) if _ENTRY.match(lines[k])), len(lines))
        entries.append((m.group(1) if m else this_month, lines[i:j]))
        i = j
    keep = [e for e in entries if e[0] >= this_month]
    roll = [e for e in entries if e[0] < this_month]
    for month, chunk in roll:
        ap = logdir / "archive" / f"{month}.md"
        ap.parent.mkdir(parents=True, exist_ok=True)
        if not ap.is_file():
            ap.write_text(f"# LOG 归档 · {me} · {month}(os.py log 自动滚动)\n", encoding="utf-8")
        with ap.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(chunk).rstrip() + "\n")
    entry = [f"## {_now_stamp()} {a.message}"] + [f"- {d}" for d in (a.detail or [])]
    out = lines[:head_end] + entry + [""] + [ln for _, chunk in keep for ln in chunk]
    lp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    rolled = f";滚动 {len(roll)} 条到 archive/" if roll else ""
    print(f"✅ log/{me}/log.md 落一条{rolled}")


def cmd_validate(_a) -> None:
    r = subprocess.run([sys.executable, str(DEV / "scripts/validate_dev.py")])
    sys.exit(r.returncode)


def main() -> None:
    ap = argparse.ArgumentParser(prog="os.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mint", help="造卡进 pool(自动 uuid/模板/依赖解析)")
    p.add_argument("title")
    p.add_argument("--area", default="", help="功能域 slug(须已在 tasks/_areas.md 注册)")
    p.add_argument("--source", default="", choices=["", "research", "goal", "interaction"])
    p.add_argument("--source-ref", default="")
    p.add_argument("--goal-section", default="", help="服务 GOAL 哪节,如 §3")
    p.add_argument("--priority", default="P1", choices=["P0", "P1", "P2", "P3"])
    p.add_argument("--depends-on", default="", help="上游卡 uuid8 前缀,逗号分隔(自动解析全 32 位)")
    p.set_defaults(fn=cmd_mint)

    p = sub.add_parser("assign", help="分配 pool 卡给 developer(仅 leader/admin)")
    p.add_argument("uuid8")
    p.add_argument("dev")
    p.add_argument("--force", action="store_true", help="非 pool 卡改派")
    p.set_defaults(fn=cmd_assign)

    p = sub.add_parser("done", help="落档(status/done_at/移 done/ 原子完成)")
    p.add_argument("uuid8")
    p.set_defaults(fn=cmd_done)

    p = sub.add_parser("archive", help="done 卡按季归档(默认留当季;--all 全收)")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_archive)

    p = sub.add_parser("refresh", help="重建全部派生视图(DEVMAP/_NAV/board/TRACE.coverage)")
    p.set_defaults(fn=cmd_refresh)

    p = sub.add_parser("log", help="按契约格式落一条日志(自动按月滚动)")
    p.add_argument("message")
    p.add_argument("--detail", action="append", help="要点行,可重复")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("validate", help="跑 validate_dev.py")
    p.set_defaults(fn=cmd_validate)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
