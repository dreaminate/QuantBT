# CLAUDE.md

<!-- 【开发os级别】clone 自 dev-os · 慢变路由,勿塞当前进度(进度在 STATE/BOARD)。 -->

⛔ 别直接改代码 —— 先读 dev/。本仓库由 **dev/ 开发 OS** 驱动,不是普通仓库。

## 动手前按顺序读四台
dev/GOAL.md(终态) → dev/STATE.md(现状 gap) → dev/tasks/BOARD.md(下一步)
→ dev/exec/HANDOFF.md(入口) → dev/RULES.md(OS 铁律) + dev/RULES.project.md(本项目红线) + dev/DECISIONS.md(已决,不重议)
重资料 dev/research/archive/ read-on-demand,别默认全加载

## 怎么干活(Goal Loop)
取 BOARD todo → dev/tasks/active/<id>/ 写实现 + 对抗测试(「种已知 bug 门必抓」)
→ 测试跑绿(不破坏现有基线)→ 落档 done/ + 刷 STATE + python dev/scripts/validate_dev.py 自检
诚实:🟡 未验证 ≠ ✅ 已验证,不假绿灯

## 开发 agent 的规矩(全文 dev/RULES.md)
- 不破坏现有测试基线;改现有文件「扩展不替换」
- 不擅自 commit/push —— 用户明说才提交
- 改代码不得削弱产品安全不变量;项目特定红线见 dev/RULES.project.md
- 审计/复核先立框架再挑刺(大→小→细),框架是假设、可被细节推翻 —— 见 dev/RULES.md §6

## 仓库分工
dev/ = 怎么建(开发 OS,可复用) · 其余 = 项目本身 · 改产品行为同步文档

> 本文件只放慢变路由 + 通用开发规矩。项目红线在 RULES.project.md,当前任务/进度在 STATE/BOARD —— 绝不写进这里(防漂)。
