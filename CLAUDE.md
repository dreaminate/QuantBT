# CLAUDE.md

<!-- 【开发os级别】clone 自 Multi-Dev-Os · 慢变路由,勿塞当前进度(进度在各人 state/board)。 -->

⛔ 别直接改代码 —— 先读 dev/。本仓库由 **dev/ 团队并发开发 OS** 驱动(范式源 = Multi-Dev-Os),不是普通仓库。

## 团队并发（先认这个）
- **你是谁**:`dev/.identity`(本机·不入库)= 你的 `developer_id`;`dev/TEAM.md` = 全员 + role(leader×1 / admin×N / developer)。
- **folder 化**:state/board/log/experience/decisions/issues/研究台 全 `{type}/{developer_id}/` per-dev → **读任何一类要遍历 `{type}/*/` 聚合**;导航 map(`dev/DEVMAP.md` / 各 `_NAV.md`)快定位,**只定位、实时依据永远是原文 + 对应代码**。
- **权限**:分配(pool→某人)与 land(合并 main)**仅 leader/admin**;developer 只写自己 `tasks/{自己}/` 名下卡 + self-review。
- **新鲜度**:开工前 `git pull` main;新提交触及你卡依赖代码 → 先看 diff + DEVMAP 再动手(不另设 commit-hash)。

## 动手前按顺序读
`.identity` + `TEAM.md`(你是谁) → `dev/GOAL.md`(终态) → 你的 `dev/state/{你}/state.md`(现状 gap) + `dev/board/{你}/board.md`(你的卡 = **下一步**;全局下一步看 `DEVMAP`)
→ `dev/exec/HANDOFF.md`(入口) → `dev/RULES.md`(OS 铁律) + `dev/RULES.project.md`(本项目红线) + 决策(**已决·不重议**;遍历 `dev/decisions/*/`,先看 `DEVMAP`/`_NAV` 定位)
重资料 `dev/research/archive/` read-on-demand,别默认全加载

## 怎么干活(并发 Goal Loop)
取卡(developer:自己 `tasks/{你}/` 名下 todo,**进实现须 review_status=1 且 待拍=0 两闸皆过**;leader/admin:可从 `tasks/pool/` 分配)
→ `dev/tasks/{你}/{uuid8}/` 写实现 + 对抗测试(「种已知 bug 门必抓」)→ 测试跑绿(不破基线)→ 落档 `tasks/{你}/done/` + 刷你的 state + 跑 `build_board`/`build_dev_map`/`validate_dev`
→ **land(合并进 main)仅 leader/admin**
诚实:🟡 未验证 ≠ ✅ 已验证,不假绿灯
遇前置闸门(需用户过目/点头)→ 先停下请拍板,但讲清点头后走完整套 Loop,别在闸门处截断

## 开发 agent 的规矩(全文 dev/RULES.md)
- 不破坏现有测试基线;改现有文件「扩展不替换」
- 不擅自 commit/push —— 用户明说才提交
- 改代码不得削弱产品安全不变量;项目特定红线见 dev/RULES.project.md
- 【开发os级别】文件(RULES/validate_dev/模板)**不自作主张改**;用户明确要改才改(= OS 级改动,会和 Multi-Dev-Os 分叉)
- 审计/复核先立框架再挑刺(大→小→细),框架是假设、可被细节推翻 —— dev/RULES.md §6
- 规划阶段:待拍板项(含**工程取舍**四面:优缺点/效果是否一样/前后是否冲突/架构是否和谐)**逐一详解后停下等拍板**,循环到清零再实现 —— §7
- 索引/导航 map/§标题**只为定位,不替代原文**:据它跳到位后**必读原文 + 对应代码**
- 每 session 末:`dev/log/{你}/log.md` 落一行(干了啥 + 交接)——durable 进度进仓库,别只活在会被压缩的对话里
- **强制查 LOG**:查历史先跑 `python dev/scripts/build_log_index.py`(遍历全员 log 统一索引)定位 → 读 `log/{dev}/log.md` 原文,别因自己 log 没有就当没发生(别人可能记了)

## 仓库分工
dev/ = 怎么建(团队并发开发 OS,范式回流 Multi-Dev-Os) · 其余 = 项目本身 · 改产品行为同步文档

## memory 协同(项目级 · `~/.claude/projects/<本项目>`,私有不进仓库)
每个项目就两个自动加载的上下文源:**项目 memory** 和 **dev/**,分工别串(零重叠;memory 按 cwd 隔离、**无全局层**、同机各项目各自独立不互通):
- **dev/ = 项目状态**(目标/进度/决策/任务/红线),在仓库、自检、人人 clone 可见 —— 项目的事一律以它为准。
- **项目 memory = dev/ 装不下的那层**,只装三类:① 操作者是谁 + 怎么和 agent 协作 ② 工作偏好(commit 习惯 / 协作节奏 / 复核口味等) ③ 外部参考 / 凭据(token/key 的存在与额度——**不是密钥本身**、外部方法论 URL)。私有、自动加载。
- **判定式**(每条都先问):**「dev/ 装得下吗?」**——装得下(项目状态/决策/进度/红线)→只进 dev/、memory 一字不记;装不下(仅操作者身份/偏好/外部凭据存在性)→进 memory 对应槽。进 dev/ 再分:**进行中状态**→state(**易变数值**如测试数/覆盖率/行号**不写死、以实跑为准**)、**已拍板取舍**→decisions、**红线**→RULES.project。
- **防飘**:绝不把 dev/ 项目状态复制进 memory(双源必漂),引用 dev/ 按**章节名**钉;memory 里某条成熟成**项目规则** → 升级进 dev/(RULES.project / decisions),不留第二份。

> 本文件只放慢变路由 + 通用开发规矩。项目红线在 RULES.project.md,当前任务/进度在各人 state/board —— 绝不写进这里(防漂)。
