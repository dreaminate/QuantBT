# HANDOFF · 新 session 入口提示词（团队并发）

> **慢变 · 怎么更新**：只在**入口/路由本身**变时改;进度在各人 `state/board`（实时源）、不写这里。

把下面整段复制给新 session 即可接上：

---
继续在 QuantBT 用 dev/ **团队并发**开发 OS 干活（范式源 = Multi-Dev-Os）。**folder 全 per-dev 化,读任何一类要遍历 `{type}/*/` 聚合;导航 map(`DEVMAP.md`/各 `_NAV.md`)只定位、实时看原文 + 代码。**

1. **认身份**：读 `dev/.identity`（你是谁 = developer_id）+ `dev/TEAM.md`（全员 + 你的 role:leader/admin/developer）。
2. **读地基**：`dev/GOAL.md`（终态）+ 你的 `dev/state/{你}/state.md`（现状）+ `dev/board/{你}/board.md`（你的活跃卡）+ `dev/RULES.md` + `dev/RULES.project.md` + 决策（遍历 `dev/decisions/*/`，先看 `dev/DEVMAP.md`/各 `_NAV.md` 定位再读原文）。重资料 `research/archive/` read-on-demand。
3. **同步代码**：`git pull` main;若有新提交（尤其触及你卡依赖的代码路径）→ 先看 diff + `DEVMAP` 刷新理解再动手（无 commit-hash,git pull/diff 即新鲜度信号）。
4. **取卡**：developer → 取自己 `tasks/{你}/` 名下 todo（进实现须 review_status=1 且 待拍=0）;leader/admin → 可从 `tasks/pool/` 分配（改归属文件夹,告知可选 developer）。读对应 `research/findings/` 接线 + 对抗测试要点。
5. **干活**：复用现有模块（`lineage/ids.py` 等），写实现 + 对抗测试（「种已知 bug 门必抓」），`cd app/backend && python -m pytest <新测试> -v` 跑绿、不破基线。
6. **收尾**：落档 `tasks/{你}/done/<uuid8>/`、刷你的 `state/{你}/state.md`、`log/{你}/log.md` 落一行、跑 `build_board.py` + `build_dev_map.py` + `python dev/scripts/validate_dev.py`。**land（合并进 main）仅 leader/admin。**
7. 红线见 `RULES.md`（诚实/对抗测试/扩展不替换/不擅自 commit/§8 团队并发）+ `RULES.project.md`（RunDetailPage 冻结/A股不实盘/key·杠杆/单一源）。遇 `decisions/` 没覆盖的新岔路、**或卡标注的前置闸门**，停下问用户。

先用三五句复述你的理解（你是谁/role + 当前任务设计要点），再动手。
---
