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
遇 BOARD/卡标注的**前置闸门**(需用户过目/点头)→ 先停下请拍板,但仍要讲清点头后将走完的整套 Loop(对抗测试→不破基线→落档+刷 STATE+validate),别在闸门处截断收尾

## 开发 agent 的规矩(全文 dev/RULES.md)
- 不破坏现有测试基线;改现有文件「扩展不替换」
- 不擅自 commit/push —— 用户明说才提交
- 改代码不得削弱产品安全不变量;项目特定红线见 dev/RULES.project.md
- 【开发os级别】文件(RULES.md/validate_dev/模板)**不自作主张改**;用户明确要改才改(= OS 级改动,会和 dev-os 分叉)
- 审计/复核先立框架再挑刺(大→小→细),框架是假设、可被细节推翻 —— 见 dev/RULES.md §6

## 仓库分工
dev/ = 怎么建(开发 OS,可复用) · 其余 = 项目本身 · 改产品行为同步文档

## memory 协同(项目级 · `~/.claude/projects/<本项目>`,私有不进仓库)
每个项目就两个自动加载的上下文源:**项目 memory** 和 **dev/**,分工别串(零重叠;memory 按 cwd 隔离、**无全局层**、同机各项目各自独立不互通):
- **dev/ = 项目状态**(目标/进度/决策/任务/红线),在仓库、自检、人人 clone 可见 —— 项目的事一律以它为准。
- **项目 memory = dev/ 装不下的那层**,只装三类:① 操作者是谁 + 怎么和 agent 协作 ② 工作偏好(commit 习惯 / 协作节奏 / 复核口味等) ③ 外部参考 / 凭据(token/key 的存在与额度——**不是密钥本身**、外部方法论 URL)。私有、自动加载。
- **判定式**(每条都先问):**「dev/ 装得下吗?」**——装得下(项目状态/决策/进度/红线)→只进 dev/、memory 一字不记;装不下(仅操作者身份/偏好/外部凭据存在性)→进 memory 对应槽。
- **防飘**:绝不把 dev/ 项目状态复制进 memory(双源必漂),引用 dev/ 按**章节名**钉;memory 里某条成熟成**项目规则** → 升级进 dev/(RULES.project / DECISIONS),不留第二份。

> 本文件只放慢变路由 + 通用开发规矩。项目红线在 RULES.project.md,当前任务/进度在 STATE/BOARD —— 绝不写进这里(防漂)。
