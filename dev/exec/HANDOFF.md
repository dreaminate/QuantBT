# HANDOFF · 新 session 入口提示词

把下面整段复制给新 session 即可接上：

---
继续建造 QuantBT 机构级 Agent OS 脊柱（实现阶段）。先读 `dev/` 四台、再按 BOARD 接着建。

1. 读 `dev/GOAL.md`(终态) + `dev/STATE.md`(现状 gap) + `dev/tasks/BOARD.md`(下一步) + `dev/RULES.md`(铁律) + `dev/DECISIONS.md`(R1–R29/S1–S4)。重资料在 `dev/research/archive/`，read-on-demand。
2. 按 BOARD 取下一个 `todo` 任务（当前优先：**T-001 蒸馏 GOAL**，然后 **T-013 一本账**）。读 `dev/research/findings/spine-designs/` 里对应设计的 §4 接线 + §5 对抗测试。
3. 复用现有模块（`experiments/store.py`、`data_packages.py:70`、`lineage/ids.py`），写实现 + 对抗测试（「种已知 bug 门必抓」），`cd app/backend && python -m pytest <新测试> -v` 跑绿。
4. 完成：`tasks/active/<id>/` 落档到 `tasks/done/<id>/`、更新 `BOARD.md`、刷新 `STATE.md`（诚实标 ✅/🟡/⬜）。
5. 红线见 `RULES.md`（OS 通用：诚实/对抗测试/扩展不替换/不擅自 commit/审计纪律）+ `RULES.project.md`（本项目：RunDetailPage 冻结/A股不实盘/key·杠杆/单一源）。不破坏现有测试基线（数目以 `STATE.md` 为准）。只有遇到 `DECISIONS.md` 没覆盖的新岔路才停下来问用户。

先用三五句复述你的理解 + 当前任务的设计要点，再动手。
---
