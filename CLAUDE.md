# CLAUDE.md

<!-- 【开发os级别】clone 自 dev-os · 慢变路由,勿塞当前进度(进度在 STATE/BOARD)。 -->

⛔ 别直接改代码 —— 先读 dev/。本仓库由 **dev/ 开发 OS** 驱动,不是普通仓库。

## 动手前按顺序读四台
dev/GOAL.md(终态) → dev/STATE.md(现状 gap) → dev/tasks/BOARD.md(下一步)
→ dev/exec/HANDOFF.md(入口) → dev/RULES.md(OS 铁律) + dev/RULES.project.md(本项目红线) + dev/DECISIONS.md(已决,不重议)
重资料 dev/research/archive/ read-on-demand,别默认全加载

## 怎么干活(Goal Loop)
取 BOARD todo → dev/tasks/active/<id>/ 写实现 + 对抗测试(「种已知 bug 门必抓」)
→ 测试跑绿(不破坏现有基线)→ 落档 done/ + 刷 STATE + python dev/scripts/validate_dev.py 自检(OS 结构 + 连带跑 validate_project 项目检查)
诚实:🟡 未验证 ≠ ✅ 已验证,不假绿灯

## 开发 agent 的规矩(全文 dev/RULES.md)
- 不破坏现有测试基线;改现有文件「扩展不替换」
- 不擅自 commit/push —— 用户明说才提交
- 改代码不得削弱产品安全不变量;项目特定红线见 dev/RULES.project.md
- 【开发os级别】文件(RULES.md/validate_dev/模板)**不自作主张改**;用户明确要改才改(= OS 级改动,会和 dev-os 分叉)
- 审计/复核先立框架再挑刺(大→小→细),框架是假设、可被细节推翻 —— 见 dev/RULES.md §6

## 仓库分工
dev/ = 怎么建(开发 OS,可复用) · 其余 = 项目本身 · 改产品行为同步文档

## memory 协同(跨 session · 在 ~/.claude,不在本仓库)
agent 的 memory 与 dev/ 是两个**自动加载**的上下文源,分工别串:
- **dev/ = 项目状态唯一源**(目标/进度/决策/任务/红线),在仓库、可自检、不漂 —— 项目的事一律以它为准。
- **memory 只装 dev/ 装不下的**:①操作者画像(谁在操作/怎么协作,≠产品目标用户) ②跨 session 工作偏好(dev/RULES 没收录的) ③外部参考/凭据位置。
- **绝不**把 dev/ 内容(进度/决策/里程碑/子系统状态)复制进 memory —— 双源必漂(实战删过一批漂掉的)。
- 引用 dev/ 按**章节名**钉,别只钉号(号会随蒸馏漂)。MEMORY.md 顶部应有这条铁律自述。

> 本文件只放慢变路由 + 通用开发规矩。项目红线在 RULES.project.md,当前任务/进度在 STATE/BOARD —— 绝不写进这里(防漂)。
