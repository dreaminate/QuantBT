---
uuid: d93dc5a0804b4b5e8776c943487d888e
title: 裁决卡 RunVerdictCard + 回测详情顶栏/血缘入口（非冻结）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871]
---

# 裁决卡 RunVerdictCard + 回测详情顶栏/血缘入口（非冻结）

## Scope [必填]
新建独立 RunVerdictCard 组件（紧凑卡 + 全屏 detail modal + promote 按钮 + modal 内可编辑成本），挂入策略台/runs 列表，并改非冻结的 `frontend-run-detail/src/App.tsx` 加 QB/QuantBT logo+导航 tabs+血缘回跳；冻结 RunDetailPage 仅做「加字段/排版/A股正负配色 tone」微调——**绝不**把裁决卡/KPI 嵌入冻结页、**绝不**深色化或改写冻结页交互逻辑。

## 上下文 / 动机 [按需]
事实依据 `/tmp/qbt-runDetailDeck.md`：handoff 含两份稿——`回测详情.dc.html`（= 冻结页现状的重绘，浅色 JoinQuant 风 + 新 topbar/血缘入口）与 `RunVerdictCard.dc.html`（全新深色暖橙 Mono 卡，与策略台 `#1c1b19/#d97757` 同族）。两套主题**有意并存**：冻结回测页=浅色专业风，治理/裁决层=深色信任风。RunVerdictCard 是 GOAL §6 信任层 L1–L4 渐进披露的承载（M15 治理新页面），不受冻结约束。后端裁决/过拟合/promote 逻辑齐全（`verification/`、`eval/`、`ide/promote.py`）但**无 run 级 verdict/overfit/cost/promote 端点**——本卡前端先落组件 + api.ts 桩，端点供给依赖 G1。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/frontend/src/components/RunVerdictCard.tsx` | 新建 | 全新组件：紧凑卡(header verdict pill + 4 KPI + 净值缩略 svg + 成本敏感性 3 cell + footer PBO/DSR+note+promote) + 全屏 detail modal(metrics12/热力6×12/交易/过拟合体检/可编辑成本 input×4/持仓 top8)。深色 token 复用策略台体系 |
| `app/frontend/src/pages/RunDetailPage.tsx` (社区46, 非冻结主应用页) 或 runs 列表页 | 挂载点 | 旁挂 `<RunVerdictCard/>`；不进 frontend-run-detail 冻结页 |
| `app/frontend-run-detail/src/App.tsx` | L7-L19 `.jq-topbar` + L9-L12 `.jq-logo`(现 `Q1`/`1Backtest`) + L13-L17 `.jq-nav`(现仅 1 项) | 改 logo→`QB`/`QuantBT`(bg `#4a7cf7`)、nav 扩为「数据\|因子\|模型\|策略\|回测(active)\|研究」、`margin-left:auto` 加「← 策略台 · 血缘定位」按钮(border `rgba(255,255,255,.25)` r7)。**非冻结文件，安全** |
| `app/frontend-run-detail/src/pages/RunDetailPage.tsx` | L1492 `.jq-run-detail-statusbar` 块(L1491-1505) | 仅「加字段」：statusbar 加「区间 {{analysisRange}}」。**不动结构/交互** |
| `app/frontend-run-detail/src/pages/RunDetailPage.tsx` | L167-171 `metricClass()` + L832 `OverviewMetricsJq` | 仅排版/A股正负配色 tone(正=红`#d34f4f`/负=绿`#2e8b57`)。**不动 sc-if/dataZoom/图例 toggle** |
| `app/frontend-run-detail/src/api.ts` | L162-232 末尾(`buildRunExportUrl` 后) | 扩展 4 个 fetch 桩：`getRunVerdict`/`getRunOverfit`/`getRunCostSensitivity`/`promoteRun`(POST)，对接 G1 端点；现有函数不替换 |
| 后端投影(只读对照, 实装在 G1) | `verification/schema.py::to_review()` L92 / `verifier._verdict_note()` L204 / `eval/overfit_gate.py::run_overfit_gate` L130 + `GateVerdict` L51 / `ide/promote.py::promote_ide_run` L53 | verdict 三态来自 `to_review()['verdict']`(schema.py L20)；note 来自 `_verdict_note`；「晋级候选」来自 `GateVerdict.verdict_phrasing`(L63)≠验证官 verdict |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「把 RunVerdictCard / KPI 条 / promote 按钮 import 或挂进 `frontend-run-detail/src/pages/RunDetailPage.tsx`(冻结 overview)」→ 门必抓：冻结页文件出现 `RunVerdictCard`/`verdict`/`promote`/裁决 KPI 区块即 fail（RULES.project §10 收益概述页冻结，变异要杀「悄悄在 overview 顶插一行 KPI」）。
2. 种「冻结 RunDetailPage overview 主体被深色化(bg 改 `#1d1c19`/`#1a1916` 类深色、font 改 JetBrains Mono、字色改 `#e6e1d6`)」→ 门必抓：冻结页 overview 样式 diff 触深色 token 即 fail（超「排版」范畴=重构显示体系，必须停下问用户；变异要杀「整页 className 换主题」）。
3. 种「冻结页 dataZoom / DetailContentTab / 图例 toggle / setLinear-setLog handler 行为被改写」→ 门必抓：`buildOverviewOption`/`visibleRangeToDataZoomProps`/`toggleStrategy` 等交互逻辑 diff 即 fail（dataZoom↔日期单一数据源不可破，变异要杀「顺手改缩放联动」）。
4. 种「UI 出现绝对措辞『可信/安全/排除过拟合/保证/可复现』或前端杜撰 verdictNote」→ 门必抓：组件/快照含禁词即 fail，verdictNote 必须来自后端 `_verdict_note`/`to_review()['notes']`（R7 + schema.py L5/L22 禁词表，变异要杀「照搬设计稿『PBO 0.18 排除过拟合』原文」）。
5. 种「verdict 枚举混用：把 `GateVerdict` 的『晋级候选』当验证官 verdict 三态，或 verdict 取了 `consistent/concern/blocked` 之外的值」→ 门必抓：verdict 字段非三态、或把 overfit 晋级态渲染进 verdict pill 即 fail（schema.py L20 三态锁，变异要杀「verdict='晋级候选'」）。
6. 种「promote 按钮跳过审批/血统/过拟合门直接写盘，或 approver=creator」→ 门必抓：`promoteRun` 不经后端门、或前端伪造 promoteState 即 fail（权限轴⟂治理轴，INV-5 approver≠creator + 验证背书）。

## 复用 [按需]
- 净值/回撤 svg 与 metrics 数据复用 `/api/runs/{id}/series` `/tables`（api.ts L172/L213）；月度超额热力图后端无聚合端点（设计稿现 seed 造数）→ 用 MOCK 诚实角标，端点缺口记 G1。
- verdict 三态/note/disclosure 复用后端 `VerdictRecord.to_review()`（schema.py L92）形状；过拟合 PBO/DSR/honest-N/GateVerdict 复用 `run_overfit_gate`（overfit_gate.py L130）。

## 红线 [按需]
- 三处必须**停下问用户**(不得自行实施)：① 把裁决卡/KPI 嵌入冻结页 overview；② 冻结页整体深色化；③ 冻结页 dataZoom/tab/图例交互改写。
- verdict 三态锁 `consistent/concern/blocked`，**禁**与 `overfit_gate.GateVerdict` 的「晋级候选」混用（两条独立管线）。
- 措辞禁「可信/安全/排除过拟合/保证/可复现/组织独立」，verdictNote 一律走后端 `_verdict_note`（R7）。
- promote 是写动作，经后端门(审批/血统/过拟合)，bypass 绝不跳门；approver≠creator + 验证背书(INV-5)；默认止于模拟盘，不导向直接实盘。
- 弱点一等呈现(R25)：PBO/DSR/note 与裁决同级、默认展开、不染绿、不折叠；MOCK 数据(热力图等)挂诚实角标。

## 非目标 [按需]
- 不实装后端 4 端点（`/verdict` `/overfit` `/cost-sensitivity` `/promote`）+ 月度热力聚合——属 G1 `d11d1426`，本卡只落前端组件 + api.ts 桩 + MOCK 兜底。
- 不改 `app/frontend/src/pages/RunDetailPage.tsx`(社区46) 的交互逻辑，仅作 RunVerdictCard 挂载宿主。
- 不碰 OrderGuard/下单链路；不触 torch（主进程 M6）。

## Open Questions（已决 D/总）[按需]
- [已决] RunVerdictCard 落深色暖橙 Mono(策略台同族)，冻结页主体保留浅色 JoinQuant 风——两套主题有意并存（依据 `/tmp/qbt-runDetailDeck.md` ⑥/⑦）。
- [已决] 裁决卡绝不嵌冻结页，挂策略台/runs 列表（RULES.project §10 + 红线总表）。
- [已决] verdict 三态与 GateVerdict「晋级候选」分属两枚举，UI 不混用（schema.py L20 / overfit_gate.py L51）。
- [已决] promote 复用现有晋级审批门(ide/promote + 审批门，approver≠creator + 验证背书 INV-5)，不另起独立审批步、避免双审批源；端点语义在 R2/G1 实装时对齐。— leader 2026-06-21

## 验收一句话 [必填]
种「裁决卡嵌入冻结页 / 冻结页深色化或交互改写 / UI 绝对措辞 / verdict 枚举混用 / promote 跳门」五类坏 → 对抗门全抓，且 RunVerdictCard 新组件 + App.tsx 顶栏/血缘入口落地后不破冻结 RunDetailPage 现有交互与渲染基线。

## 残余（收尾补，非阻塞）
- frontend-run-detail/src/App.tsx 顶栏（logo→QB/QuantBT · nav tabs · 血缘回跳入口）属另一前端工程的**非冻结** App.tsx，cosmetic；本卡主体 RunVerdictCard 已完成验证（16 passed，红线全守），顶栏留 land 前补。

## 残余已清（2026-06-22）
- frontend-run-detail/src/App.tsx 顶栏(logo→QB/QuantBT、nav 6 tab、血缘回跳按钮)+styles.css .jq-lineage-btn 完成；冻结 RunDetailPage.tsx 零改动(git diff 确认)；tsc+build 绿。
