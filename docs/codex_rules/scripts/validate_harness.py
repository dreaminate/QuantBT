from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

TASK_ID_RE = re.compile(r"^TASK-\d{4}$")
VERSION_RE = re.compile(r"^v\d+$")
DEP_RE = re.compile(r"^TASK-\d{4}@v\d+$")
RULE_CHG_RE = re.compile(r"^RULE-CHG-\d{4}\.md$")

ALLOWED_TASK_STATUS = {"draft", "confirmed", "in_progress", "done"}
ALLOWED_REVIEW_STATUS = {"0", "1"}
STAGES = {"rules", "alignment", "implementation", "ci"}
PLACEHOLDER_TOKENS = ["待填写", "待填充", "TODO", "TBD"]

REQUIRED_CODEX_KNOW = [
    "project_alignment.md",
    "glossary.md",
    "domain_model.md",
    "workflow.md",
    "task_contract.md",
    "acceptance_rules.md",
    "architecture_decisions.md",
    "open_questions.md",
]

REQUIRED_TEMPLATES = [
    "TASK.md",
    "CHANGE.md",
    "RULE_CHANGE.md",
    "OPEN_QUESTION.md",
    "EXPERIMENT.md",
]

REQUIRED_TASK_FIELDS = [
    "id",
    "version",
    "status",
    "review_status",
    "depends_on",
    "layer",
    "confirmed_by",
    "confirmed_at",
]

REQUIRED_TASK_SECTIONS = [
    "## Scope",
    "## Inputs",
    "## Outputs",
    "## Interfaces",
    "## State Changes",
    "## Acceptance Matrix",
    "## Allowed Files",
    "## Open Questions",
]

ACCEPTANCE_ITEMS = [
    "文档一致性",
    "数据契约",
    "研究接口",
    "风控约束",
    "回测现实性",
    "Artifact 导出",
    "API/UI",
    "回归测试",
]

ALLOWED_LAYERS = {
    "data",
    "feature",
    "model",
    "signal",
    "optimizer",
    "risk",
    "backtest",
    "artifact",
    "api",
    "ui",
    "docs",
    "harness",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def add(errors: list[str], path: Path, message: str) -> None:
    try:
        label = path.relative_to(ROOT)
    except ValueError:
        label = path
    errors.append(f"{label}: {message}")


def parse_kv(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fffA-Za-z_]+)\s*[:：]\s*(.*)$", line)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def is_emptyish(value: str) -> bool:
    return value.strip() in {"", "无", "none", "None", "N/A"}


def valid_dep_list(value: str) -> bool:
    if is_emptyish(value):
        return True
    return all(DEP_RE.match(part.strip()) for part in value.split(","))


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def markdown_table_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            current.append(stripped)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_markdown_table(text: str, required_headers: list[str]) -> list[dict[str, str]]:
    for lines in markdown_table_blocks(text):
        if len(lines) < 2:
            continue
        headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
        if headers != required_headers or not is_table_separator(lines[1]):
            continue
        rows: list[dict[str, str]] = []
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != len(headers):
                break
            rows.append(dict(zip(headers, cells)))
        return rows
    return []


def has_markdown_table(text: str, required_headers: list[str]) -> bool:
    return bool(parse_markdown_table(text, required_headers)) or any(
        [cell.strip() for cell in lines[0].strip("|").split("|")] == required_headers and is_table_separator(lines[1])
        for lines in markdown_table_blocks(text)
        if len(lines) >= 2
    )


def contains_placeholder(text: str) -> str | None:
    for token in PLACEHOLDER_TOKENS:
        if token in text:
            return token
    return None


def has_substantive_content(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or is_table_separator(stripped):
            continue
        if re.match(r"^([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fffA-Za-z_]+)\s*[:：]\s*(.*)$", stripped):
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if any(cell and cell not in {"N/A", "无", "none", "None"} for cell in cells):
                return True
            continue
        return True
    return False


def validate_review_status_file(path: Path, errors: list[str]) -> None:
    if not path.exists():
        add(errors, path, "missing file")
        return
    fields = parse_kv(read_text(path))
    review = fields.get("review_status", "")
    status = fields.get("status") or fields.get("状态") or ""
    if not review:
        add(errors, path, "missing review_status")
        return
    if review not in ALLOWED_REVIEW_STATUS:
        add(errors, path, "review_status must be 0 or 1")
    if status == "pending_review" and review == "1":
        add(errors, path, "pending_review file must use review_status 0")
    if review == "1":
        if is_emptyish(fields.get("confirmed_by", "")):
            add(errors, path, "review_status 1 requires confirmed_by")
        if is_emptyish(fields.get("confirmed_at", "")):
            add(errors, path, "review_status 1 requires confirmed_at")


def require_reviewed(path: Path, errors: list[str]) -> None:
    validate_review_status_file(path, errors)
    if path.exists() and parse_kv(read_text(path)).get("review_status") != "1":
        add(errors, path, "must have review_status 1 for this stage")


def validate_rules(errors: list[str]) -> None:
    readme = ROOT / "docs" / "codex_rules" / "README.md"
    changes = ROOT / "docs" / "codex_rules" / "changes"
    validate_review_status_file(readme, errors)
    if not changes.exists():
        add(errors, changes, "missing rule changes directory")
        return
    for path in changes.glob("*.md"):
        if not RULE_CHG_RE.match(path.name):
            add(errors, path, "rule change file name must be RULE-CHG-0000.md")
        validate_review_status_file(path, errors)


def require_rules_reviewed(errors: list[str]) -> None:
    require_reviewed(ROOT / "docs" / "codex_rules" / "README.md", errors)
    changes = ROOT / "docs" / "codex_rules" / "changes"
    for path in changes.glob("*.md"):
        require_reviewed(path, errors)


def validate_templates(errors: list[str]) -> None:
    templates = ROOT / "docs" / "templates"
    if not templates.exists():
        add(errors, templates, "missing templates directory")
        return
    for name in REQUIRED_TEMPLATES:
        path = templates / name
        validate_review_status_file(path, errors)


def validate_codex_know(errors: list[str], *, strict: bool, task: str | None = None) -> None:
    know_dir = ROOT / "docs" / "codex_know"
    if not know_dir.exists():
        add(errors, know_dir, "missing codex_know directory")
        return
    for name in REQUIRED_CODEX_KNOW:
        path = know_dir / name
        if strict:
            require_reviewed(path, errors)
        else:
            validate_review_status_file(path, errors)
        if path.exists() and strict:
            text = read_text(path)
            placeholder = contains_placeholder(text)
            if placeholder:
                add(errors, path, f"strict stage forbids placeholder text: {placeholder}")
            if name != "open_questions.md" and not has_substantive_content(text):
                add(errors, path, "strict stage requires substantive aligned content")
    open_questions = know_dir / "open_questions.md"
    if open_questions.exists():
        headers = ["问题ID", "scope", "blocking_task", "status", "decision", "confirmed_by", "confirmed_at"]
        rows = parse_markdown_table(read_text(open_questions), headers)
        if not has_markdown_table(read_text(open_questions), headers):
            add(errors, open_questions, "missing open questions table")
        if strict:
            for row in rows:
                status = row["status"].strip().lower()
                blocker = row["blocking_task"].strip()
                if status in {"open", "pending", "blocked"} and blocker in {"ALL", "all", "global", "全局", task or ""}:
                    add(errors, open_questions, f"blocking open question for {blocker}: {row['问题ID']}")


def validate_task_index(errors: list[str], *, allow_empty: bool, require_reviewed_index: bool) -> list[dict[str, str]]:
    path = ROOT / "docs" / "tasks" / "index.md"
    if require_reviewed_index:
        require_reviewed(path, errors)
    else:
        validate_review_status_file(path, errors)
    if not path.exists():
        return []
    headers = ["任务ID", "当前版本", "状态", "review_status", "依赖版本", "stale_by", "重验状态", "入口"]
    rows = parse_markdown_table(read_text(path), headers)
    if not has_markdown_table(read_text(path), headers):
        add(errors, path, "missing required task index table")
        return []
    if not rows and not allow_empty:
        add(errors, path, "task index must not be empty for this stage")
    for row in rows:
        task_id = row["任务ID"]
        version = row["当前版本"]
        status = row["状态"]
        review = row["review_status"]
        deps = row["依赖版本"]
        stale_by = row["stale_by"]
        entry = row["入口"]
        if not TASK_ID_RE.match(task_id):
            add(errors, path, f"invalid task id in index: {task_id}")
        if not VERSION_RE.match(version):
            add(errors, path, f"invalid version for {task_id}: {version}")
        if status not in ALLOWED_TASK_STATUS:
            add(errors, path, f"invalid status for {task_id}: {status}")
        if review not in ALLOWED_REVIEW_STATUS:
            add(errors, path, f"invalid review_status for {task_id}: {review}")
        if not valid_dep_list(deps):
            add(errors, path, f"dependencies must use TASK-0000@v1 for {task_id}")
        if not is_emptyish(stale_by) and not valid_dep_list(stale_by):
            add(errors, path, f"stale_by must use TASK-0000@v1 for {task_id}")
        if is_emptyish(entry):
            add(errors, path, f"missing entry for {task_id}")
    return rows


def validate_acceptance_matrix(path: Path, text: str, errors: list[str], *, strict: bool) -> None:
    for item in ACCEPTANCE_ITEMS:
        if item not in text:
            add(errors, path, f"acceptance matrix missing item: {item}")
    rows = parse_markdown_table(text, ["项", "状态", "命令", "通过标准"])
    if strict and not rows:
        add(errors, path, "missing acceptance matrix table")
        return
    if strict:
        for row in rows:
            item = row["项"]
            if item not in ACCEPTANCE_ITEMS:
                continue
            status = row["状态"]
            command = row["命令"]
            standard = row["通过标准"]
            if status == "required":
                if is_emptyish(command):
                    add(errors, path, f"required acceptance item missing command: {item}")
                if is_emptyish(standard):
                    add(errors, path, f"required acceptance item missing pass standard: {item}")
            elif not status.startswith("N/A + "):
                add(errors, path, f"acceptance item must be required or N/A + reason: {item}")


def validate_task_dir(task_dir: Path, index_row: dict[str, str] | None, errors: list[str], *, strict: bool) -> None:
    task_md = task_dir / "TASK.md"
    if not task_md.exists():
        add(errors, task_dir, "missing TASK.md")
        return
    if index_row is None:
        add(errors, task_dir, "task directory is not registered in docs/tasks/index.md")
    text = read_text(task_md)
    fields = parse_kv(text)
    for field in REQUIRED_TASK_FIELDS:
        if field not in fields:
            add(errors, task_md, f"missing field: {field}")
    for section in REQUIRED_TASK_SECTIONS:
        if section not in text:
            add(errors, task_md, f"missing section: {section}")
    task_id = fields.get("id", "")
    version = fields.get("version", "")
    review = fields.get("review_status", "")
    deps = fields.get("depends_on", "")
    layer = fields.get("layer", "")
    if not TASK_ID_RE.match(task_id):
        add(errors, task_md, f"invalid id: {task_id}")
    if task_dir.name != task_id:
        add(errors, task_md, f"directory name {task_dir.name} does not match id {task_id}")
    if not VERSION_RE.match(version):
        add(errors, task_md, f"invalid version: {version}")
    if review not in ALLOWED_REVIEW_STATUS:
        add(errors, task_md, "review_status must be 0 or 1")
    if not valid_dep_list(deps):
        add(errors, task_md, "depends_on must use TASK-0000@v1")
    if layer and any(part.strip() not in ALLOWED_LAYERS for part in layer.split(",")):
        add(errors, task_md, f"unknown layer: {layer}")
    if strict:
        require_reviewed(task_md, errors)
        placeholder = contains_placeholder(text)
        if placeholder:
            add(errors, task_md, f"strict stage forbids placeholder text: {placeholder}")
    if index_row:
        if index_row["当前版本"] != version:
            add(errors, task_md, "version does not match docs/tasks/index.md")
        if index_row["review_status"] != review:
            add(errors, task_md, "review_status does not match docs/tasks/index.md")
    version_file = task_dir / "versions" / f"{version}.md"
    if not version_file.exists():
        add(errors, task_md, f"missing immutable version file versions/{version}.md")
    elif strict:
        require_reviewed(version_file, errors)
    validate_acceptance_matrix(task_md, text, errors, strict=strict)


def validate_tasks(errors: list[str], *, allow_empty_index: bool, require_reviewed_index: bool, strict: bool, only_task: str | None) -> None:
    rows = validate_task_index(errors, allow_empty=allow_empty_index, require_reviewed_index=require_reviewed_index)
    rows_by_id = {row["任务ID"]: row for row in rows}
    tasks_dir = ROOT / "docs" / "tasks"
    if not tasks_dir.exists():
        add(errors, tasks_dir, "missing tasks directory")
        return
    for task_dir in tasks_dir.iterdir():
        if not task_dir.is_dir() or not TASK_ID_RE.match(task_dir.name):
            continue
        if only_task and task_dir.name != only_task:
            continue
        validate_task_dir(task_dir, rows_by_id.get(task_dir.name), errors, strict=strict)
    if only_task and only_task not in rows_by_id:
        add(errors, tasks_dir, f"requested task is not registered in docs/tasks/index.md: {only_task}")
    for task_id, row in rows_by_id.items():
        if only_task and task_id != only_task:
            continue
        if strict and row["review_status"] != "1":
            add(errors, tasks_dir, f"{task_id} requires review_status 1 for this stage")
        if strict and not is_emptyish(row["stale_by"]):
            add(errors, tasks_dir, f"{task_id} is stale: {row['stale_by']}")
        entry = row["入口"]
        if not is_emptyish(entry) and not (ROOT / entry).exists():
            add(errors, tasks_dir, f"index entry path does not exist for {task_id}: {entry}")


def validate_git(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        add(errors, ROOT, "implementation stage requires a Git repository")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate quant research harness documents.")
    parser.add_argument("--stage", choices=sorted(STAGES), default="rules")
    parser.add_argument("--task", help="Task id for implementation checks, e.g. TASK-0001")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    validate_rules(errors)
    if args.stage in {"alignment", "implementation", "ci"}:
        require_rules_reviewed(errors)
    validate_templates(errors)
    if args.stage in {"alignment", "implementation", "ci"}:
        validate_codex_know(errors, strict=True, task=args.task)
    else:
        validate_codex_know(errors, strict=False, task=args.task)
    validate_tasks(
        errors,
        allow_empty_index=args.stage in {"rules", "alignment"},
        require_reviewed_index=args.stage in {"implementation", "ci"},
        strict=args.stage in {"implementation", "ci"},
        only_task=args.task,
    )
    if args.stage in {"implementation", "ci"}:
        validate_git(errors)
        if not args.task:
            add(errors, ROOT / "docs" / "tasks" / "index.md", "implementation and ci stages require --task")
    if errors:
        print(f"Harness validation failed for stage {args.stage}:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Harness validation passed for stage {args.stage}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
