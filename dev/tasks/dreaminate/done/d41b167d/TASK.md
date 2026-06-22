---
uuid: d41b167d61bc474fa6dffebebd20e879
title: Agent 窗口 D-PERM 反例 UI + self-approve 二次确认
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [82120b9c60814566beea2d6b210ef31e]
---

# Agent 窗口 D-PERM 反例 UI + self-approve 二次确认

## Scope [必填]
补设计稿两处治理盲点：① bypass 模式下 `realmoney`/`external` 工具**仍弹 gate 确认**的反例变体（让"权限轴⟂治理轴"在 UI 可见，给陌生用户看见"bypass 也拦真钱"）；② self-approve（gate「别再问→升 auto」）加**二次确认**（修设计稿无二次确认盲点，T-030）。gate 的 `side_effect` 必从后端 `tool_status` 真值取、不前端伪造。**不做**对话流/工具可视化/权限三态主体（T-040 82120b9c）、不做血统/red/可证伪弹窗（T-041 3d95e0f6）、不改后端 `permission_gate` 逻辑。

## 上下文 / 动机 [按需]
设计稿（`/tmp/qbt-handoff/quantbt-claude/project/QuantBT Agent.dc.html`）全程只演示 `backtest.run`（`side_effect: none`），none 类 bypass 自跑天经地义——**从未演示 external/realmoney 工具在 bypass 下被拦的画面**，治理轴在 UI 上"隐形"。后端 `permission_gate`（agent_runtime.py L44-48）已正确实现 realmoney 任何模式恒 confirm、external 仅 bypass 自动；本卡补的是让该后端真值在 UI **可视**的反例 gate。设计稿 `_resolveGate("always")` 直接 `permMode→auto`，无二次确认（T-030 盲点）。关联 T-041（3d95e0f6，其 Scope 列了 T-030 但未细化，本卡承接细节）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/pages/workshop/（T-040 新建的 agent 窗口组件 / gate 渲染器） | gate block 渲染 | 扩展 gate：当 `side_effect ∈ {realmoney, external}` 时即便 `permMode==="bypass"/"auto"` 仍渲染确认变体（红边/治理徽标"治理门·bypass 不跳"），不静默执行 |
| app/frontend/（gate side_effect 取值处） | gate.se 赋值 | 从 `/api/agent/tools` 的 `tool_status[].side_effect` 真值取，禁前端硬编码/默认 none；缺值按最严（confirm）兜底 |
| app/backend/app/main.py | L1505-1517 `/api/agent/tools` | 复用（不改）：`tool_status[].side_effect` 来自 `rt._side_effects`，是前端 gate 唯一真值源 |
| app/backend/app/agent/agent_runtime.py | L37-48 `permission_gate` | 复用（不改）：UI gate 变体行为须与该函数判定一致（realmoney→confirm 恒真、external→bypass 才 execute） |
| app/frontend/（self-approve handler，对应设计稿 `_resolveGate("always")`） | approveAlways 路径 | 升 auto 前插二次确认步（"确认放宽权限到 auto？"），用户再确认才 `permMode→auto`；取消则只批本次 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「bypass 下 `realmoney` 工具不弹确认、直接执行」→ 门必抓：assert bypass 模式 realmoney gate 仍渲染确认变体且未发执行请求（D-PERM 核心反例 / R 权限轴⟂治理轴）。变异要杀：把 gate 条件从 `side_effect==='realmoney'` 篡成 `permMode!=='bypass'` 必被测试红。
2. 种「self-approve 升 auto 无二次确认（一键直升）」→ 门必抓：assert approveAlways 不经二次确认步不会改 `permMode`（T-030 / INV-5 晋级需额外背书的 UI 同构）。变异要杀：删掉二次确认直接 set permMode=auto 必红。
3. 种「前端伪造 `side_effect='none'` 绕 gate」→ 门必抓：gate 的 se 必等于 `/api/agent/tools` 后端真值，注入 none 覆盖真值 realmoney 时门仍 confirm（real钱不可被前端降级）。变异要杀：让 gate 读本地常量而非后端 tool_status 必红。
4. 种「external 在 ask/auto 下不弹确认」→ 门必抓：external 仅 bypass execute，ask/auto 须 confirm，与 permission_gate L46-47 同构。

## 复用 [按需]
- 后端 `permission_gate`（agent_runtime.py L37-48）、`/api/agent/tools` tool_status（main.py L1505-1517）已就绪，本卡只读真值、不重造判定。
- gate block 渲染框架由 T-040 提供，本卡扩展其变体分支，不另起组件。

## 红线 [按需]
- 权限轴⟂治理轴：bypass 绝不跳 OrderGuard/审批门；realmoney UI gate 恒 confirm（与后端 L44-45 一致）。
- 默认止于模拟盘：反例 gate 文案不导向直接实盘；A股 live 下单永远拒、下单唯一入口经 OrderGuard。
- 裁决/确认措辞禁「可信/安全/排除过拟合/保证」（R7）；文案走后端 `_verdict_note` / tool_status 真值，不前端编。
- side_effect 缺值按最严（confirm）兜底，绝不默认 none。

## 非目标 [按需]
- 不实装对话流/工具可视化/权限三态主体（T-040）。
- 不实装血统警告/red 裁决/可证伪 409 引导弹窗（T-041）——本卡只补 self-approve 二次确认与 D-PERM 反例 gate；与 T-041 Scope 的 T-030 边界：T-041 列名、本卡落细节，避免双源。
- 不改后端 `permission_gate` / `/api/agent/tools` 逻辑（扩展不替换）。
- `/stream` 端点未接 `permission_mode`（main.py L3127-3128 仅 q+current）属 T-040/后端缺口，非本卡。

## Open Questions（已决 D/总）[按需]
- [已决] realmoney 任何模式（含 bypass）恒 confirm —— 后端 `permission_gate` L44-45 已定，UI 同构（D-PERM）。
- [已决] gate side_effect 取后端 `tool_status` 真值、禁前端伪造 —— D-PERM 纵深防御。
- [已决] self-approve 二次确认本卡承接落细节，T-041(3d95e0f6) 只列名不实装、避免双源。— leader 2026-06-21
- D/总：2/3（占位，主控 build_card_counters 重算）。

## 验收一句话 [必填]
种「bypass 下 realmoney 直接跑 / self-approve 一键升 auto / 前端伪造 side_effect=none 绕 gate」三坏，门必抓（realmoney 恒 confirm、升 auto 须二次确认、se 取后端真值），且不破现有测试基线。
