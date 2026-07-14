#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import re
import shutil
import sys
from pathlib import Path


ASSIGNMENT_SECTIONS = ("Leader Final Assignments", "Final Assignments", "Suggested Assignments")
OWNER_COLUMNS = ("final_owner", "owner", "assignee", "member", "suggested_owner")
TASK_LINK_RE = re.compile(r"\[([0-9a-f]{8})\]\(([^)]+)\)")
ROLE_SET = {"leader", "admin", "developer"}


@dataclasses.dataclass(frozen=True)
class Decision:
    uuid8: str
    owner: str
    source_link: str


@dataclasses.dataclass(frozen=True)
class MovePlan:
    decision: Decision
    src_dir: Path
    dst_dir: Path
    task_file: Path


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


def default_assigned_by(team: dict[str, str]) -> str:
    leaders = sorted(member for member, role in team.items() if role == "leader")
    return leaders[0] if leaders else ""


def section_lines(text: str, section_name: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"## {section_name}":
            start = idx + 1
            break
    if start is None:
        return []
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return lines[start:end]


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def parse_decisions(board_path: Path) -> tuple[str, list[Decision]]:
    if not board_path.is_file():
        raise FileNotFoundError(f"missing assignment board: {board_path}")
    text = board_path.read_text(encoding="utf-8")
    for section in ASSIGNMENT_SECTIONS:
        lines = [line for line in section_lines(text, section) if line.strip().startswith("|")]
        if not lines:
            continue
        header = split_row(lines[0])
        header_map = {name: idx for idx, name in enumerate(header)}
        if "task" not in header_map:
            continue
        owner_col = next((column for column in OWNER_COLUMNS if column in header_map), None)
        if owner_col is None:
            continue
        decisions: list[Decision] = []
        seen: set[str] = set()
        for line in lines[1:]:
            cells = split_row(line)
            if is_separator(cells) or len(cells) < len(header):
                continue
            task_cell = clean_cell(cells[header_map["task"]])
            owner = clean_cell(cells[header_map[owner_col]])
            if not owner or owner == "_none_":
                continue
            match = TASK_LINK_RE.search(task_cell)
            if not match:
                raise ValueError(f"malformed task link in {section}: {task_cell}")
            uuid8, source_link = match.group(1), match.group(2)
            if uuid8 in seen:
                raise ValueError(f"duplicate task decision: {uuid8}")
            seen.add(uuid8)
            decisions.append(Decision(uuid8=uuid8, owner=owner, source_link=source_link))
        return section, decisions
    return "", []


def build_move_plans(dev: Path, decisions: list[Decision], team: dict[str, str]) -> list[MovePlan]:
    plans: list[MovePlan] = []
    for decision in decisions:
        if decision.owner not in team:
            raise ValueError(f"unknown assignee {decision.owner} for task {decision.uuid8}")
        normalized = decision.source_link.strip()
        if not normalized.startswith(f"pool/{decision.uuid8}/"):
            raise ValueError(
                f"task {decision.uuid8} must point to pool/{decision.uuid8}/TASK.md, got {normalized}"
            )
        src_dir = dev / "tasks" / "pool" / decision.uuid8
        task_file = src_dir / "TASK.md"
        dst_dir = dev / "tasks" / decision.owner / decision.uuid8
        if not src_dir.is_dir():
            raise FileNotFoundError(f"missing source task directory: {src_dir}")
        if not task_file.is_file():
            raise FileNotFoundError(f"missing source TASK.md: {task_file}")
        if dst_dir.exists():
            raise FileExistsError(f"destination already exists: {dst_dir}")
        plans.append(MovePlan(decision=decision, src_dir=src_dir, dst_dir=dst_dir, task_file=task_file))
    return plans


def update_frontmatter(text: str, owner: str, assigned_by: str) -> str:
    lines = text.splitlines()
    start = next((idx for idx, line in enumerate(lines) if line.strip() == "---"), None)
    if start is None:
        raise ValueError("TASK.md missing front matter start")
    end = next((idx for idx in range(start + 1, len(lines)) if lines[idx].strip() == "---"), None)
    if end is None:
        raise ValueError("TASK.md missing front matter end")
    replacements = {"owner": owner, "assigned_by": assigned_by, "review_status": "0"}
    found: set[str] = set()
    updated = list(lines)
    for idx in range(start + 1, end):
        match = re.match(r"^([A-Za-z_]+):(\s*)(.*)$", updated[idx])
        if not match:
            continue
        key = match.group(1)
        if key in replacements:
            updated[idx] = f"{key}: {replacements[key]}"
            found.add(key)
    insert_at = end
    for key in ("owner", "assigned_by", "review_status"):
        if key not in found:
            updated.insert(insert_at, f"{key}: {replacements[key]}")
            insert_at += 1
    return "\n".join(updated) + ("\n" if text.endswith("\n") else "")


def apply_plans(plans: list[MovePlan], assigned_by: str, write: bool) -> list[str]:
    messages: list[str] = []
    for plan in plans:
        messages.append(f"{plan.decision.uuid8}: pool -> {plan.decision.owner}")
        if not write:
            continue
        text = plan.task_file.read_text(encoding="utf-8")
        updated = update_frontmatter(text, plan.decision.owner, assigned_by)
        plan.task_file.write_text(updated, encoding="utf-8")
        plan.dst_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(plan.src_dir), str(plan.dst_dir))
    return messages


def render_preview(section: str, plans: list[MovePlan], assigned_by: str) -> str:
    lines = [
        f"recognized {len(plans)} assignment decisions from [{section}]",
        f"assigned_by: {assigned_by}",
        "",
        "| task | from | to |",
        "|---|---|---|",
    ]
    for plan in plans:
        lines.append(f"| {plan.decision.uuid8} | pool/{plan.decision.uuid8} | {plan.decision.owner}/{plan.decision.uuid8} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply task assignment moves from ASSIGNMENT_BOARD.md.")
    parser.add_argument("--dev", type=Path, default=Path("dev"), help="Path to dev directory.")
    parser.add_argument("--board", type=Path, default=None, help="Assignment board path.")
    parser.add_argument("--assigned-by", default=None, help="Leader/admin id to write into assigned_by.")
    parser.add_argument("--write", action="store_true", help="Move tasks and update TASK.md front matter.")
    parser.add_argument("--confirm", action="store_true", help="Confirm that the leader approved the printed plan.")
    args = parser.parse_args(argv)

    dev = args.dev
    board_path = args.board or (dev / "tasks" / "ASSIGNMENT_BOARD.md")
    team = read_team(dev)
    assigned_by = args.assigned_by or default_assigned_by(team)
    if not assigned_by:
        print("no leader found; pass --assigned-by", file=sys.stderr)
        return 1
    if assigned_by not in team:
        print(f"assigned_by is not in TEAM.md: {assigned_by}", file=sys.stderr)
        return 1

    try:
        section, decisions = parse_decisions(board_path)
        if not decisions:
            print(f"no assignment decisions found in {board_path}")
            return 0
        plans = build_move_plans(dev, decisions, team)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(render_preview(section, plans, assigned_by))
    if args.write and not args.confirm:
        print("")
        print("refused: --write requires --confirm after leader approval")
        return 2
    if not args.write:
        print("")
        print("preview only: no files moved; rerun with --write --confirm after leader approval")
        return 0
    print("")
    print(f"WRITE: applying {len(plans)} confirmed decisions")
    for message in apply_plans(plans, assigned_by, args.write):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
