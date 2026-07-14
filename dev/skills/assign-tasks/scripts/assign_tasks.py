#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Iterable


UUID32_RE = re.compile(r"^[0-9a-f]{32}$")
ROLE_SET = {"leader", "admin", "developer"}


@dataclasses.dataclass(frozen=True)
class Card:
    uuid: str
    uuid8: str
    title: str
    status: str
    owner: str
    deps: tuple[str, ...]
    loc: str
    path: Path


@dataclasses.dataclass(frozen=True)
class Package:
    package_id: str
    task_ids: tuple[str, ...]
    entry: str
    exit: str
    kind: str
    ready: bool
    blocker_refs: tuple[str, ...]
    blocker_tasks: tuple[str, ...]
    suggested_owner: str | None
    assignment_reason: str | None


@dataclasses.dataclass(frozen=True)
class Analysis:
    team: dict[str, str]
    cards: dict[str, Card]
    pending: dict[str, Card]
    pending_edges: list[tuple[str, str]]
    packages: dict[str, Package]
    package_order: tuple[str, ...]
    package_edges: tuple[tuple[str, str], ...]


def strip_comment(value: str) -> str:
    return re.sub(r"\s{2,}#.*$", "", value).strip()


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_inline_list(value: str) -> list[str]:
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    return [strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]


def parse_frontmatter(text: str) -> dict[str, object]:
    if not text.lstrip().startswith("---"):
        return {}
    lines = text.splitlines()
    start = next((idx for idx, line in enumerate(lines) if line.strip() == "---"), None)
    if start is None:
        return {}
    end = next((idx for idx in range(start + 1, len(lines)) if lines[idx].strip() == "---"), None)
    if end is None:
        return {}
    data: dict[str, object] = {}
    current_key: str | None = None
    for raw in lines[start + 1:end]:
        if re.match(r"^\s*-\s+", raw) and current_key == "depends_on":
            item = strip_quotes(strip_comment(raw.split("-", 1)[1]))
            data.setdefault("depends_on", [])
            cast = data["depends_on"]
            if isinstance(cast, list) and item:
                cast.append(item)
            continue
        match = re.match(r"^([A-Za-z_]+):\s*(.*)$", raw)
        if not match:
            continue
        key, raw_value = match.group(1), strip_comment(match.group(2))
        current_key = key
        if key == "depends_on":
            if raw_value.startswith("[") and raw_value.endswith("]"):
                data[key] = parse_inline_list(raw_value)
            elif raw_value:
                data[key] = [strip_quotes(raw_value)]
            else:
                data[key] = []
        else:
            data[key] = strip_quotes(raw_value)
    return data


def normalize_deps(raw: object, label: str, errors: list[str]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        items: Iterable[object] = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        errors.append(f"{label}: depends_on 必须是 uuid 列表")
        return ()
    deps: list[str] = []
    for item in items:
        dep = str(item or "").strip().lower()
        if not dep:
            continue
        if not UUID32_RE.match(dep):
            errors.append(f"{label}: depends_on 项「{dep}」不是 32 位 uuid")
            continue
        deps.append(dep)
    return tuple(deps)


def read_team(dev: Path) -> dict[str, str]:
    team_path = dev / "TEAM.md"
    team: dict[str, str] = {}
    if not team_path.is_file():
        return team
    for line in team_path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[1] in ROLE_SET:
            team[cells[0]] = cells[1]
    return team


def iter_task_dirs(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return [path for path in sorted(base.iterdir()) if path.is_dir() and not path.name.startswith(".")]


def load_card(task_dir: Path, owner_folder: str, loc: str, errors: list[str]) -> Card | None:
    task_path = task_dir / "TASK.md"
    label = f"{loc}/{owner_folder}/{task_dir.name}" if owner_folder != "wait" else f"{loc}/{task_dir.name}"
    if not task_path.is_file():
        errors.append(f"{label}: 缺 TASK.md")
        return None
    fm = parse_frontmatter(task_path.read_text(encoding="utf-8"))
    uuid = str(fm.get("uuid") or "").strip().lower()
    if not UUID32_RE.match(uuid):
        errors.append(f"{label}: uuid「{uuid}」非法或缺失")
        return None
    deps = normalize_deps(fm.get("depends_on"), label, errors)
    owner = str(fm.get("owner") or owner_folder).strip()
    title = str(fm.get("title") or task_dir.name).strip()
    status = str(fm.get("status") or "").strip()
    return Card(
        uuid=uuid,
        uuid8=uuid[:8],
        title=title or task_dir.name,
        status=status,
        owner=owner,
        deps=deps,
        loc=loc,
        path=task_path,
    )


def gather_cards(dev: Path, team: dict[str, str]) -> tuple[dict[str, Card], list[str]]:
    errors: list[str] = []
    cards: dict[str, Card] = {}

    for task_dir in iter_task_dirs(dev / "tasks" / "pool"):
        card = load_card(task_dir, "wait", "pool", errors)
        if not card:
            continue
        if card.uuid in cards:
            errors.append(f"重复 uuid: {card.uuid}")
            continue
        cards[card.uuid] = card

    tasks_root = dev / "tasks"
    if tasks_root.is_dir():
        known_meta = {"pool", "_templates"}
        for entry in sorted(tasks_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in known_meta:
                continue
            if entry.name not in team:
                errors.append(f"tasks/ 下未知归属文件夹 {entry.name}")
                continue
            for task_dir in iter_task_dirs(entry):
                if task_dir.name == "done":
                    continue
                card = load_card(task_dir, entry.name, "active", errors)
                if not card:
                    continue
                if card.uuid in cards:
                    errors.append(f"重复 uuid: {card.uuid}")
                    continue
                cards[card.uuid] = card
            for task_dir in iter_task_dirs(entry / "done"):
                card = load_card(task_dir, entry.name, "done", errors)
                if not card:
                    continue
                if card.uuid in cards:
                    errors.append(f"重复 uuid: {card.uuid}")
                    continue
                cards[card.uuid] = card
    return cards, errors


def validate_graph(cards: dict[str, Card]) -> list[str]:
    errors: list[str] = []
    graph: dict[str, list[str]] = {uuid: [] for uuid in cards}
    for card in cards.values():
        for dep in card.deps:
            if dep not in cards:
                errors.append(f"{card.uuid8}: 依赖 {dep[:8]} 不存在")
                continue
            graph[dep].append(card.uuid)
    if errors:
        return errors

    color: dict[str, int] = {uuid: 0 for uuid in cards}
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        color[node] = 1
        stack.append(node)
        for nxt in graph[node]:
            if color[nxt] == 1:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == 0:
                cycle = dfs(nxt)
                if cycle:
                    return cycle
        stack.pop()
        color[node] = 2
        return None

    for node in sorted(graph):
        if color[node] == 0:
            cycle = dfs(node)
            if cycle:
                errors.append("任务 DAG 成环：" + " -> ".join(cards[uuid].uuid8 for uuid in cycle))
                break
    return errors


def pending_cards(cards: dict[str, Card]) -> dict[str, Card]:
    return {
        uuid: card
        for uuid, card in cards.items()
        if card.loc == "pool" and card.owner == "wait" and card.status != "done"
    }


def build_pending_edges(pending: dict[str, Card]) -> list[tuple[str, str]]:
    pending_ids = set(pending)
    edges: list[tuple[str, str]] = []
    for uuid, card in pending.items():
        for dep in card.deps:
            if dep in pending_ids:
                edges.append((dep, uuid))
    return sorted(edges)


def split_packages(pending: dict[str, Card], edges: list[tuple[str, str]]) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    preds: dict[str, set[str]] = {uuid: set() for uuid in pending}
    succs: dict[str, set[str]] = {uuid: set() for uuid in pending}
    for src, dst in edges:
        succs[src].add(dst)
        preds[dst].add(src)

    cut_edges = {
        (src, dst)
        for src, dst in edges
        if len(succs[src]) > 1 or len(preds[dst]) > 1
    }

    adjacency: dict[str, set[str]] = {uuid: set() for uuid in pending}
    for src, dst in edges:
        if (src, dst) in cut_edges:
            continue
        adjacency[src].add(dst)
        adjacency[dst].add(src)

    package_tasks: dict[str, tuple[str, ...]] = {}
    package_of: dict[str, str] = {}
    seen: set[str] = set()

    for start in sorted(pending, key=lambda uuid: pending[uuid].uuid8):
        if start in seen:
            continue
        queue: deque[str] = deque([start])
        component: set[str] = set()
        seen.add(start)
        while queue:
            cur = queue.popleft()
            component.add(cur)
            for nxt in sorted(adjacency[cur], key=lambda uuid: pending[uuid].uuid8):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

        entries = sorted(
            (uuid for uuid in component if not (preds[uuid] & component)),
            key=lambda uuid: pending[uuid].uuid8,
        )
        exits = sorted(
            (uuid for uuid in component if not (succs[uuid] & component)),
            key=lambda uuid: pending[uuid].uuid8,
        )
        if len(entries) != 1 or len(exits) != 1:
            raise ValueError(
                "package segmentation failed: component is not a linear chain "
                f"({[pending[uuid].uuid8 for uuid in sorted(component, key=lambda item: pending[item].uuid8)]})"
            )

        ordered: list[str] = []
        cur = entries[0]
        while True:
            ordered.append(cur)
            next_nodes = sorted(succs[cur] & component, key=lambda uuid: pending[uuid].uuid8)
            if not next_nodes:
                break
            cur = next_nodes[0]
        if set(ordered) != component:
            raise ValueError(
                "package segmentation failed: component traversal lost nodes "
                f"({[pending[uuid].uuid8 for uuid in sorted(component, key=lambda item: pending[item].uuid8)]})"
            )

        package_id = f"pkg-{pending[entries[0]].uuid8}"
        package_tasks[package_id] = tuple(ordered)
        for uuid in ordered:
            package_of[uuid] = package_id
    return package_tasks, package_of


def active_counts(cards: dict[str, Card], team: dict[str, str]) -> dict[str, int]:
    counts = {member: 0 for member in team}
    for card in cards.values():
        if card.loc == "active" and card.owner in counts:
            counts[card.owner] += 1
    return counts


def is_satisfied(card: Card) -> bool:
    return card.loc == "done"


def choose_owner(
    task_ids: tuple[str, ...],
    cards: dict[str, Card],
    team: dict[str, str],
    active_load: dict[str, int],
    assigned_tasks: dict[str, int],
) -> tuple[str | None, str | None]:
    if not team:
        return None, None
    preference: Counter[str] = Counter()
    task_set = set(task_ids)
    for uuid in task_ids:
        for dep in cards[uuid].deps:
            if dep in task_set or dep not in cards:
                continue
            dep_card = cards[dep]
            if dep_card.loc == "done" and dep_card.owner in team:
                preference[dep_card.owner] += 1

    members = sorted(team)

    def score(member: str) -> tuple[int, int, int, str]:
        projected = active_load.get(member, 0) + assigned_tasks.get(member, 0)
        return (-preference[member], projected, assigned_tasks.get(member, 0), member)

    owner = min(members, key=score)
    if preference[owner] > 0:
        reason = "upstream-continuity"
    else:
        reason = "active-load"
    assigned_tasks[owner] = assigned_tasks.get(owner, 0) + len(task_ids)
    return owner, reason


def topo_package_order(package_tasks: dict[str, tuple[str, ...]], package_edges: set[tuple[str, str]]) -> tuple[str, ...]:
    indegree = {package_id: 0 for package_id in package_tasks}
    outgoing: dict[str, set[str]] = {package_id: set() for package_id in package_tasks}
    for src, dst in package_edges:
        if dst not in outgoing[src]:
            outgoing[src].add(dst)
            indegree[dst] += 1
    queue = deque(sorted((pkg for pkg, degree in indegree.items() if degree == 0), key=str))
    ordered: list[str] = []
    while queue:
        pkg = queue.popleft()
        ordered.append(pkg)
        for nxt in sorted(outgoing[pkg]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(ordered) != len(package_tasks):
        raise ValueError("package DAG contains a cycle")
    return tuple(ordered)


def analyze(dev: Path) -> Analysis:
    team = read_team(dev)
    cards, errors = gather_cards(dev, team)
    errors.extend(validate_graph(cards))
    if errors:
        raise ValueError("\n".join(errors))

    pending = pending_cards(cards)
    pending_edges = build_pending_edges(pending)
    package_tasks, package_of = split_packages(pending, pending_edges)

    package_edges: set[tuple[str, str]] = set()
    package_preds: dict[str, set[str]] = {package_id: set() for package_id in package_tasks}
    package_succs: dict[str, set[str]] = {package_id: set() for package_id in package_tasks}
    for src, dst in pending_edges:
        src_pkg = package_of[src]
        dst_pkg = package_of[dst]
        if src_pkg == dst_pkg:
            continue
        package_edges.add((src_pkg, dst_pkg))
        package_preds[dst_pkg].add(src_pkg)
        package_succs[src_pkg].add(dst_pkg)

    active_load = active_counts(cards, team)
    assigned_tasks = {member: 0 for member in team}
    ready_sort = sorted(
        package_tasks,
        key=lambda pkg: (len(package_preds[pkg]) != 0, pending[package_tasks[pkg][0]].uuid8),
    )

    packages: dict[str, Package] = {}
    for package_id in ready_sort:
        task_ids = package_tasks[package_id]
        task_set = set(task_ids)
        entry = task_ids[0]
        exit_task = task_ids[-1]

        blocker_refs: set[str] = set()
        blocker_tasks: set[str] = set()

        for uuid in task_ids:
            for dep in cards[uuid].deps:
                if dep in task_set:
                    continue
                dep_card = cards[dep]
                if is_satisfied(dep_card):
                    continue
                if dep in pending:
                    blocker_refs.add(package_of[dep])
                elif dep_card.loc == "active":
                    blocker_refs.add(f"active:{dep_card.uuid8}")
                else:
                    blocker_refs.add(f"unsatisfied:{dep_card.uuid8}")
                blocker_tasks.add(dep)

        ready = not blocker_refs
        entry_external = [dep for dep in cards[entry].deps if dep not in task_set]
        unsatisfied_entry = [dep for dep in entry_external if not is_satisfied(cards[dep])]
        if ready:
            kind = "foundation" if len(package_succs[package_id]) > 1 else "independent"
            suggested_owner, suggested_reason = choose_owner(
                task_ids, cards, team, active_load, assigned_tasks
            )
        else:
            kind = "join" if len(entry_external) > 1 and unsatisfied_entry else "future"
            suggested_owner, suggested_reason = None, None

        packages[package_id] = Package(
            package_id=package_id,
            task_ids=task_ids,
            entry=entry,
            exit=exit_task,
            kind=kind,
            ready=ready,
            blocker_refs=tuple(sorted(blocker_refs)),
            blocker_tasks=tuple(sorted(blocker_tasks, key=lambda dep: cards[dep].uuid8)),
            suggested_owner=suggested_owner,
            assignment_reason=suggested_reason,
        )

    order = topo_package_order(package_tasks, package_edges)
    return Analysis(
        team=team,
        cards=cards,
        pending=pending,
        pending_edges=pending_edges,
        packages=packages,
        package_order=order,
        package_edges=tuple(sorted(package_edges)),
    )


def task_link(card: Card) -> str:
    if card.loc == "pool":
        target = f"pool/{card.uuid8}/TASK.md"
    elif card.loc == "done":
        target = f"{card.owner}/done/{card.uuid8}/TASK.md"
    else:
        target = f"{card.owner}/{card.uuid8}/TASK.md"
    return f"[{card.uuid8}]({target})"


def blocker_task_label(cards: dict[str, Card], uuid: str) -> str:
    card = cards[uuid]
    return f"{task_link(card)}:{card.loc}"


def mermaid_graph(analysis: Analysis) -> str:
    lines = ["flowchart TD"]
    if not analysis.pending:
        lines.append('  empty["no pending tasks"]')
        return "\n".join(lines)
    for package_id in analysis.package_order:
        package = analysis.packages[package_id]
        for uuid in package.task_ids:
            card = analysis.pending[uuid]
            state = "ready" if package.ready else f"blocked:{package.kind}"
            label = f"{card.uuid8} {card.title} [{package.package_id} {package.kind} {state}]".replace('"', "'")
            lines.append(f'  n{card.uuid8}["{label}"]')
    for src, dst in analysis.pending_edges:
        lines.append(f"  n{analysis.pending[src].uuid8} --> n{analysis.pending[dst].uuid8}")
    return "\n".join(lines)


def render_board(analysis: Analysis) -> str:
    ready_packages = [pkg for pkg in analysis.package_order if analysis.packages[pkg].ready]
    blocked_packages = [pkg for pkg in analysis.package_order if not analysis.packages[pkg].ready]
    blocked_active = sum(
        1 for pkg in blocked_packages if any(ref.startswith("active:") for ref in analysis.packages[pkg].blocker_refs)
    )
    blocked_pending = sum(
        1 for pkg in blocked_packages if any(ref.startswith("pkg-") for ref in analysis.packages[pkg].blocker_refs)
    )
    join_count = sum(1 for pkg in blocked_packages if analysis.packages[pkg].kind == "join")

    lines = [
        "# ASSIGNMENT BOARD · package-level DAG allocation recommendation",
        "",
        "> Generated from the full task DAG. Ready means every external predecessor is already in `done/`.",
        "> This is still a recommendation: leader/admin reviews the package split, then confirms the final flat task assignments below.",
        "",
        "## Dependency Graph",
        "",
        "```mermaid",
        mermaid_graph(analysis),
        "```",
        "",
        "## Summary",
        "",
        f"- Team members: {len(analysis.team)}",
        f"- Pending tasks: {len(analysis.pending)}",
        f"- Packages: {len(analysis.packages)}",
        f"- Ready packages: {len(ready_packages)}",
        f"- Blocked by active: {blocked_active}",
        f"- Blocked by pending: {blocked_pending}",
        f"- Join packages: {join_count}",
        "",
        "## Package Summary",
        "",
        "| package_id | type | entry_task | exit_task | task_count | blocker_packages | suggested_owner |",
        "|---|---|---|---|---:|---|---|",
    ]
    if analysis.package_order:
        for package_id in analysis.package_order:
            package = analysis.packages[package_id]
            entry = task_link(analysis.pending[package.entry])
            exit_task = task_link(analysis.pending[package.exit])
            blockers = ", ".join(package.blocker_refs) if package.blocker_refs else "-"
            owner = package.suggested_owner or "-"
            lines.append(
                f"| {package.package_id} | {package.kind} | {entry} | {exit_task} | "
                f"{len(package.task_ids)} | {blockers} | {owner} |"
            )
    else:
        lines.append("| _none_ | | | | | | |")

    lines += [
        "",
        "## Ready Packages",
        "",
        "| package_id | type | entry_task | exit_task | task_count | suggested_owner | reason |",
        "|---|---|---|---|---:|---|---|",
    ]
    if ready_packages:
        for package_id in ready_packages:
            package = analysis.packages[package_id]
            lines.append(
                f"| {package.package_id} | {package.kind} | {task_link(analysis.pending[package.entry])} | "
                f"{task_link(analysis.pending[package.exit])} | {len(package.task_ids)} | "
                f"{package.suggested_owner or '-'} | {package.assignment_reason or '-'} |"
            )
    else:
        lines.append("| _none_ | | | | | | |")

    lines += [
        "",
        "## Blocked Packages",
        "",
        "| package_id | type | entry_task | task_count | blocker_packages | blocking_tasks |",
        "|---|---|---|---:|---|---|",
    ]
    if blocked_packages:
        for package_id in blocked_packages:
            package = analysis.packages[package_id]
            blockers = ", ".join(package.blocker_refs) if package.blocker_refs else "-"
            tasks = ", ".join(blocker_task_label(analysis.cards, uuid) for uuid in package.blocker_tasks) or "-"
            lines.append(
                f"| {package.package_id} | {package.kind} | {task_link(analysis.pending[package.entry])} | "
                f"{len(package.task_ids)} | {blockers} | {tasks} |"
            )
    else:
        lines.append("| _none_ | | | | | |")

    lines += [
        "",
        "## Package Details",
        "",
    ]
    if analysis.package_order:
        for package_id in analysis.package_order:
            package = analysis.packages[package_id]
            lines += [
                f"### {package.package_id} · {package.kind}",
                "",
                f"- entry: {task_link(analysis.pending[package.entry])}",
                f"- exit: {task_link(analysis.pending[package.exit])}",
                f"- ready: {'yes' if package.ready else 'no'}",
                f"- suggested_owner: {package.suggested_owner or '-'}",
                "",
                "| task | title | depends_on |",
                "|---|---|---|",
            ]
            for uuid in package.task_ids:
                card = analysis.pending[uuid]
                deps = ", ".join(dep[:8] for dep in card.deps) or "-"
                lines.append(f"| {task_link(card)} | {card.title} | {deps} |")
            lines.append("")
    else:
        lines += ["_no pending packages_", ""]

    lines += [
        "## Final Assignments",
        "",
        "> Review this flat table before running the apply script. Only ready packages are included here.",
        "",
        "| task | title | final_owner | package | reason |",
        "|---|---|---|---|---|",
    ]
    final_rows = 0
    for package_id in ready_packages:
        package = analysis.packages[package_id]
        if not package.suggested_owner:
            continue
        for uuid in package.task_ids:
            card = analysis.pending[uuid]
            lines.append(
                f"| {task_link(card)} | {card.title} | {package.suggested_owner} | "
                f"{package.package_id} | {package.assignment_reason or '-'} |"
            )
            final_rows += 1
    if final_rows == 0:
        lines.append("| _none_ | | | | |")
    return "\n".join(lines) + "\n"


def write_board(dev: Path, analysis: Analysis) -> Path:
    path = dev / "tasks" / "ASSIGNMENT_BOARD.md"
    path.write_text(render_board(analysis), encoding="utf-8")
    return path


def default_dev_path() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build package-level task DAG and assignment board.")
    parser.add_argument("--dev", type=Path, default=default_dev_path(), help="Path to dev directory.")
    parser.add_argument("--write", action="store_true", help="Write dev/tasks/ASSIGNMENT_BOARD.md.")
    args = parser.parse_args(argv)
    try:
        analysis = analyze(args.dev)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    board = render_board(analysis)
    if args.write:
        path = write_board(args.dev, analysis)
        print(f"wrote {path}")
    else:
        print(board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
