---
name: apply-task-assignments
description: Apply leader-approved Multi-Dev-Os task assignments from dev/tasks/ASSIGNMENT_BOARD.md. Use when Codex needs to move pending task cards from dev/tasks/pool to member task folders, update TASK.md front matter ownership fields, and verify assignment moves from a board table.
---

# Apply Task Assignments

Use `scripts/apply_assignments.py` to preview, then apply the leader's final task assignment board.

## Workflow

1. Confirm the board has one assignment table:
   - Preferred section names: `Leader Final Assignments` or `Final Assignments`.
   - Fallback section: `Suggested Assignments`.
   - Required columns: `task` and one owner column: `final_owner`, `owner`, `assignee`, `member`, or `suggested_owner`.

2. Preview the recognized assignment result from the repository root:

   ```bash
   python dev/skills/apply-task-assignments/scripts/apply_assignments.py --dev dev
   ```

3. Wait for the leader to confirm that the printed assignment result is final.

4. Apply the moves only after confirmation:

   ```bash
   python dev/skills/apply-task-assignments/scripts/apply_assignments.py --dev dev --write --confirm
   ```

## Behavior

- Parse Markdown table rows from the leader-approved board.
- Resolve task links like `[00000010](pool/00000010/TASK.md)`.
- Move each source directory from `dev/tasks/pool/{uuid8}` to `dev/tasks/{member}/{uuid8}`.
- Update `TASK.md` front matter: `owner: {member}`, `assigned_by: {leader}`, `review_status: 0`.
- Refuse unknown members, missing source cards, destination collisions, non-pool links, malformed rows, and duplicate task rows.
- Default mode only prints the recognized assignment result.
- `--write` without `--confirm` is refused.
