---
uuid: a75c4beb6bf64f70b21e55c85a012363
title: Agent 窗口产物工作区 — 8 产物卡 + Strategy.yaml + Report.md
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871, d5ea778c285a46e0872dba3a87ab1182, 82120b9c60814566beea2d6b210ef31e]
---

# Agent 窗口产物工作区 — 8 产物卡 + Strategy.yaml + Report.md

## Scope [必填]
做 QuantBT Agent 窗口右栏「产物工作区」：8 张产物卡（假设/市场/因子集/模型/信号/风控执行/RunVerdictCard）+ COWORK/CODE(strategy.yaml)/REPORT(markdown) 三 tab + 跨台血统蓝胶囊（←因子台/←Model台）常驻展开；**不做** 左栏对话流/工具可视化/权限三态（T-040 82120b9c 已领）、不做里程碑进度线/台 switcher（另卡）、不做后端 8 工具 schema+handler 与裁决数据计算（属 T-043，本卡只消费已就绪的产物 JSON）。

## 上下文 / 动机 [按需]
设计稿右栏是策略台脊柱可视化：产物卡逐里程碑累积（假设→市场→因子集→模型→信号→风控→回测裁决）。G3（d5ea778c）已明示「不内置产物工作区 8 卡（属 A1）」，本卡即 A1。血统蓝胶囊与底注（「只选用 QUALIFIED+，不在此造因子」「只引用 model_id，不训练」）是血统门的 UI 投影 —— 设计稿把它做成**常驻展开**而非可折叠，本卡必须照此实装。RunVerdictCard 在现有前端尚不存在，本卡新建，数据契约对齐后端裁决产物（sharpe/excess/maxDD/PBO/DSR/equity/3 成本预设/_verdict_note）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/components/desk/cowork/ | 新建目录 | 新建 Cowork 容器 + 8 张产物卡组件（HypothesisCard/MarketCard/FactorSetCard/ModelCard/SignalCard/RiskExecCard/RunVerdictCard）+ CodeView(yaml 高亮)/ReportView(md)，受控 props 传入产物对象 |
| app/frontend/src/components/desk/cowork/RunVerdictCard.tsx | 新建 | 渲染 runObj（sharpe/annExcess/maxDD/PBO/DSR/equity vs bench/3 成本预设），弱点字段默认展开不染绿，裁决措辞只读后端 _verdict_note |
| app/frontend/src/components/desk/cowork/LineageBadge.tsx | 新建 | ←因子台/←Model台 蓝胶囊(#6f9bd1)，常驻展开、`collapsible=false` 内置约束；含「只引用不造」底注 |
| app/frontend/src/components/desk/agent/ChatBubble (G3 d5ea778c L26) | 复用 tool block 的 ↗cowork 链接 | tool block ↗ 聚焦本工作区对应产物卡（接口对齐，本卡不改 ChatBubble 内部） |
| app/frontend/src/components/MetricCard.tsx / StatusPill.tsx / charts/ | 复用 | RunVerdictCard 指标与 equity 曲线复用现有 MetricCard/charts，胶囊复用 G1 Pill/StatusPill |
| app/frontend/src/pages/workshop/Mode2ChatPage.tsx (Mode2ChatPage L47) | T-040 挂载点 | 本卡只导出 Cowork 组件供 T-040 右栏挂载；不在此卡改 Mode2 布局 |
| 后端 /api/agent/tools tool_status[].side_effect (main.py L1505) | 数据真值源 | 产物卡/血统标记的治理属性从后端真值取，前端不伪造 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「血统蓝胶囊或弱点字段（PBO/DSR/maxDD/可证伪失败阈值）默认 `collapsed`/可折叠藏起」→ 门必抓：LineageBadge 与 RunVerdictCard 弱点字段渲染后默认可见、`collapsible=false`（R25 弱点一等呈现）。变异要杀：把 `defaultExpanded=true` 改成 `false`、把 `collapsible` 暴露成 prop 默认 true —— 测试须红。
2. 种「因子集卡接收 `<QUALIFIED 因子` 或模型卡接收 `<staging 模型` 仍正常渲染为已选用」→ 门必抓：产物卡对低于门槛血统的入参拒绝渲染为「选用」、显式标注违规（血统门「只引用不造」不可被绕过）。变异要杀：去掉血统等级校验分支 —— 测试须红。
3. 种「RunVerdictCard 把 PBO/DSR/red 裁决染成绿色或自造『可信/排除过拟合』文案」→ 门必抓：弱点不染绿、裁决文本只透传后端 `_verdict_note`、无前端硬编码裁决词（R7/R25）。变异要杀：把 verdict 文案改成前端字符串常量 —— 测试须红。
4. 种「MOCK/占位产物对象渲染时不带诚实角标」→ 门必抓：mock 数据卡显式 MOCK 角标（诚实角标红线）。

## 复用 [按需]
G1（d11d1426）design tokens / Pill / SegmentedControl / per-desk accent；G3（d5ea778c）`desk/agent/` ChatBubble 的 tool↗cowork 接口约定；现有 `MetricCard.tsx` / `StatusPill.tsx` / `charts/`（RunVerdictCard 指标与 equity 曲线）；落地用 `cc-*` CSS 变量映射设计稿色值（灰/绿/黄/红/蓝阶），勿内联硬编码。

## 红线 [按需]
弱点一等呈现：red/PBO/DSR/血统默认展开、不染绿、不折叠（R25）；裁决措辞禁「可信/安全/排除过拟合/保证」，文案走后端 `_verdict_note`（R7）；血统门「只引用不造」—— 产物卡只接 QUALIFIED+ 因子 / staging+ 模型，不在前端造/训；治理属性（side_effect/血统等级）从后端真值取、前端不伪造（D-PERM）；MOCK 数据诚实角标。

## 非目标 [按需]
不做左栏对话流/工具可视化/权限三态（T-040 82120b9c）；不做里程碑进度线 + 4 台 switcher（另卡）；不做后端 8 工具 schema/handler 与裁决数据计算（T-043）；不做候选策略提交模拟台端点（另卡）；不做 Tauri 桌面挂载（T-042）。

## Open Questions（已决 1/1）[按需]
- [已决] 产物卡受控化：8 卡 + RunVerdictCard 全 props 传入产物对象，血统蓝胶囊与弱点字段「常驻展开、不可折叠」为组件内置约束（沿用 G3 d5ea778c「治理 block 默认展开为组件内置约束」决策）。

## 验收一句话 [必填]
种「血统/弱点默认折叠藏起」「产物卡接 <QUALIFIED 因子或 <staging 模型仍渲染为选用」「裁决染绿/自造裁决词」「MOCK 无角标」四类坏门必抓，8 卡 + yaml/md tab 像素对齐设计稿，且不破现有前端测试基线。
