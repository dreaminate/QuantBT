# CLAUDE.md

<!-- 【开发os级别】clone 自 Multi-Dev-Os · 慢变路由,勿塞当前进度(进度在各人 state/board)。 -->

⛔ 别直接改代码 —— 先读 dev/。本仓库由 **dev/ 团队并发开发 OS** 驱动(范式源 = Multi-Dev-Os),不是普通仓库。

## 硬不变量（违一条即出事 · 全文 `dev/RULES.md`，据 § 跳读原文）
- 🟡 未验证 ≠ ✅ 已验证 —— 状态绝不假绿灯（§3）
- 不擅自 commit/push（用户明说才提交）；**分配 / land（合并 main）仅 leader/admin**（§4/§8）
- 不削弱安全不变量；致命错误（动钱 / 不可逆 / 数据泄露）即停工报告（§5）
- 对抗测试「种已知坏门必抓」、不破现有基线；改现有文件**扩展不替换**（§2/§4）
- **【开发os级别】文件**（`RULES` / `validate_dev` / 模板）不自作主张改，用户明说才动（§4）
- 待拍板项（含**工程取舍**四面：优缺点 / 效果是否一样 / 前后冲突 / 架构是否和谐）**逐一详解后停下等拍板**、循环到清零（§7）
- 审计先立框架（大→小→细）再挑刺，框架是假设、可被细节推翻（§6）

## 你是谁 + folder 化
- **身份**：`dev/.identity`（本机·不入库）= 你的 `developer_id`；`dev/TEAM.md` = 全员 + role（leader×1 / admin×N / developer）。
- **folder 化**：state/board/log/experience/decisions/issues/研究台 全 `{type}/{developer_id}/` per-dev → **读任一类要遍历 `{type}/*/` 聚合**；导航 map（`dev/DEVMAP.md` / 各 `_NAV.md`）**只定位，实时依据永远是原文 + 对应代码**。

## 动手前按顺序读
`.identity` + `TEAM.md`（你是谁）→ `dev/GOAL.md`（终态）→ 你的 `state/{你}/state.md`（现状）+ `board/{你}/board.md`（你的卡 = **下一步**；全局看 `DEVMAP`）→ `dev/exec/HANDOFF.md`（**入口脚本 = 怎么干活 / 收尾 / land 的唯一源**）→ `dev/RULES.md`（OS 铁律全文）+ `dev/RULES.project.md`（本项目红线）+ 决策（**已决·不重议**；遍历 `dev/decisions/*/`，先看 `DEVMAP`/`_NAV` 定位）。重资料 `research/archive/` read-on-demand，别默认全加载。

## 仓库分工
dev/ = 团队并发开发 OS（范式回流 Multi-Dev-Os）· 其余 = 项目本身 · 改产品行为同步文档。

## memory 协同(项目级 · `~/.claude/projects/<本项目>`,私有不进仓库)
每个项目就两个自动加载的上下文源:**项目 memory** 和 **dev/**,分工别串(零重叠;memory 按 cwd 隔离、**无全局层**、同机各项目各自独立不互通):
- **dev/ = 项目状态**(目标/进度/决策/任务/红线),在仓库、自检、人人 clone 可见 —— 项目的事一律以它为准。
- **项目 memory = dev/ 装不下的那层**,只装三类:① 操作者是谁 + 怎么和 agent 协作 ② 工作偏好(commit 习惯 / 协作节奏 / 复核口味等) ③ 外部参考 / 凭据(token/key 的存在与额度——**不是密钥本身**、外部方法论 URL)。私有、自动加载。
- **判定式**(每条都先问):**「dev/ 装得下吗?」**——装得下(项目状态/决策/进度/红线)→只进 dev/、memory 一字不记;装不下(仅操作者身份/偏好/外部凭据存在性)→进 memory 对应槽。进 dev/ 再分:**进行中状态**→state(**易变数值**如测试数/覆盖率/行号**不写死、以实跑为准**)、**已拍板取舍**→decisions、**红线**→RULES.project。
- **防飘**:绝不把 dev/ 项目状态复制进 memory(双源必漂),引用 dev/ 按**章节名**钉;memory 里某条成熟成**项目规则** → 升级进 dev/(RULES.project / decisions),不留第二份。

> 本文件只放慢变路由 + 硬不变量摘要。规矩全文在 `RULES.md`、怎么干活在 `HANDOFF.md`、当前进度在各人 state/board —— 绝不写进这里(防漂)。
