# HANDOFF · 新 session 入口提示词

把下面整段复制给新 session 即可接上：

---
继续在 QuantBT 用 dev/ 开发 OS 干活。先读 `dev/` 四台、再按 BOARD 接着干（当前阶段/进度以 `STATE.md` + `BOARD.md` 实时为准，本文件不写死）。

1. 读 `dev/GOAL.md`(终态) + `dev/STATE.md`(现状 gap) + `dev/tasks/BOARD.md`(下一步) + `dev/RULES.md`(OS 铁律) + `dev/RULES.project.md`(本项目红线) + `dev/DECISIONS.md`(R1–R29/S1–S4)。重资料在 `dev/research/archive/`，read-on-demand。
2. 按 BOARD 取**最高优先 `todo`**（以 BOARD 实时为准——**别认这里写死的 task id**，防漂）。读 `dev/research/findings/` 里对应设计的接线 + 对抗测试要点。
3. 复用现有模块（`experiments/store.py`、`data_packages.py`、`lineage/ids.py` 等），写实现 + 对抗测试（「种已知 bug 门必抓」），`cd app/backend && python -m pytest <新测试> -v` 跑绿。
4. 完成：`tasks/active/<id>/` 落档到 `tasks/done/<id>/`、更新 `BOARD.md`、刷新 `STATE.md`（诚实标 ✅/🟡/⬜）、跑 `python dev/scripts/validate_dev.py`。
5. 红线见 `RULES.md`（OS 通用：诚实/对抗测试/扩展不替换/不擅自 commit/审计纪律）+ `RULES.project.md`（本项目：RunDetailPage 冻结/A股不实盘/key·杠杆/单一源）。不破坏现有测试基线（**数目以实跑 pytest 为准，别认 STATE/卡里写死的数**）。遇 `DECISIONS.md` 没覆盖的新岔路、**或 BOARD/卡标注的前置闸门（如收口簇A 须先过目+岔路点头才动代码）**，停下问用户。

先用三五句复述你的理解 + 当前任务的设计要点，再动手。
---
