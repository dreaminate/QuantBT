---
name: assign-tasks
description: Build package-level DAG assignment recommendations for Multi-Dev-Os task cards. Use when Codex needs to read dev/tasks TASK.md front matter, split the full pending DAG into assignable sub-DAG packages, and write a package-first assignment board.
---

# Assign Tasks

Use `scripts/assign_tasks.py` for deterministic package generation and assignment planning.

## Workflow

1. Run the script from the repository root:

   ```bash
   python dev/skills/assign-tasks/scripts/assign_tasks.py --dev dev --write
   ```

2. Review `dev/tasks/ASSIGNMENT_BOARD.md`.

3. Use the board as an assignment recommendation only. Actual assignment still follows the project rule: leader/admin moves cards from `dev/tasks/pool/{uuid8}/` to `dev/tasks/{developer_id}/{uuid8}/`.

## Behavior

- Read every `TASK.md` under `dev/tasks/pool/`, active member folders, and member `done/` folders.
- Build the full task DAG from all valid task cards; fail closed on malformed cards, dangling dependencies, duplicate ids, or cycles.
- Treat `done/` tasks as satisfied predecessors; `active/` and `pool/` tasks remain unsatisfied blockers.
- Split the pending DAG into package-level sub-DAGs by cutting after split points and before join points.
- Mark a ready shared trunk package as `foundation`.
- Mark merge-point packages as later `join` work until their upstream packages finish.
- Recommend owners only for ready `foundation` and `independent` packages.

## Output

The generated board contains:

- Mermaid DAG for all pending tasks.
- Package summary and blockers.
- Ready package recommendations.
- Blocked package inventory.
- Package details with concrete task membership.
- Final flat task assignments for leader confirmation and downstream apply.
