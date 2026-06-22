---
uuid: be3dc5985ab04acdac8aeb44fb4d8d7f
title: 策略台前端 P0 — DAG 编排工作台像素还原 + mock 交互
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871, b9af7c82ef4c4ea6bfd1e3b6fc4d9219, d5ea778c285a46e0872dba3a87ab1182]
---

# 策略台前端 P0 — DAG 编排工作台像素还原 + mock 交互

## Scope [必填]
新建 `app/frontend/src/pages/StrategyConsolePage.tsx`，把策略台 DC 原型四区（顶栏 44 / 左 Agent 316 / 中 DAG 画布 / 右 Inspector 340 / 底 dock 228）pixel-perfect 还原成 React，复用地基 G1（壳/token/cssToObj）+ G2（画布引擎）+ G3（Agent 对话/Inspector/Dock），用 mock 数据驱动、可拖拽连线缩放 Undo、MOCK 角标诚实标注；**不做**：不接真后端（归 S2 `9fd4f1a6`）、不嵌冻结 RunDetailPage（节点「↗打开回测」只 `navigate('/runs/:runId')` 单段跳转）、不实装画布引擎本体（用 G2 受控组件）。

## 上下文 / 动机 [按需]
策略台是 DC handoff 的主目标 P0 原型（`策略台.dc.html` 1250 行，初始 16 节点 / 19 连线 DAG）。DC 运行时是建在 React 18 上的微型模板引擎：单一真相源 = `class Component extends DCLogic` 的 `this.state`（~30 键），模板 `{{}}` 字段全过 `renderVals()`（L996–1245）投影成扁平视图模型；`setState → renderVals 重算 → 重渲染` 与原生 React 一致。转 React 几乎 1:1：`{{x}}`→`{vm.x}`、`sc-for`→`.map(key=$index)`、`sc-if`→`&&`（保留 JS 真值语义）、`style="{{s}}"`→`style={cssToObj(vm.s)}`、`onInput`→`onChange`、字符串 `disabled`→布尔、`style-hover`→CSS `:hover`。本卡只搬本台的节点定义 / mock fixtures（`_trades`/`_runs`/`_versions`/`_diff`/`_contribution`）+ 视图模型 + 受控接线，交互引擎与对话/Inspector/Dock 壳件由 G2/G3 提供。原型唯一真实导航 `window.location.href = "回测详情.dc.html?..."` → React Router 单段跳转，落进 App.tsx L39 冻结分支保住 RunDetailPage 冻结意图。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/pages/StrategyConsolePage.tsx | 新建 | 策略台四区组装：DeskShell(G1) 内放 AgentChat(G3·左316) + GraphCanvas(G2·中) + Inspector(G3·右340) + Dock(G3·底228)；本台 mock fixtures + renderVals 视图模型 + 节点 Registry / 兼容性着色 / locked 规则传入 G2 |
| app/frontend/src/App.tsx | 路由表 + 冻结正则 L39 | 加 `<Route path="/strategy" element={<StrategyConsolePage />} />`（DeskShell 分支，**严格在 L39 `/^\/runs\/[^/]+$/` 冻结正则之后/之外**，不动冻结分支） |
| app/frontend/src/components/shell/Shell.tsx | SIDEBAR_BY_AREA L18 / AREA_LABEL L47 / areaOf L381 | 策略台导航入口接入（与 G1 DeskShell 路由边界一致，扩展不替换现有 4 区 map） |
| app/frontend/src/components/desk/canvas/ | G2 b9af7c82 产物 | 消费 GraphCanvas/NodeCard/NodePort/EdgeLayer/MiniMap/CanvasControls/CanvasBanner（受控 props，本卡不改引擎） |
| app/frontend/src/components/desk/agent/ + inspector/ + dock/ | G3 d5ea778c 产物 | 消费 AgentChat/ChatBubble/ChatComposer + Inspector/InspectorTabs/ParamRow + Dock/DockTabs（受控传入本台 blocks/params/tabs） |
| app/frontend/src/lib/cssToObj.ts | G1 d11d1426 产物 | 动态 CSS 字符串（cardStyle/frameStyle/gridStyle/killStyle…）→ React style 对象 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「节点『↗打开回测』跳 `/runs/{runId}?tab=x` 多段或非 `/^\/runs\/[^/]+$/` 形状」→ 门必抓：跳转目标落进 App.tsx 非冻结 Shell 分支、冻结意图失效（须严格单段 `/runs/:runId`，变异要杀：在 runId 后追加 `/` 子段或 query 使正则不命中）。
2. 种「Final Risk Gate 等 locked 节点被 Del/框选删除生效」→ 门必抓：locked 节点删除被拒（治理强制节点不可删，变异要杀：删除路径漏判 `n.locked` 直接 splice）。
3. 种「`runtime==='live'` 只读态下节点仍可拖拽 / 参数 input 可改 / 连线可建」→ 门必抓：live 下画布与参数全只读、出现 🔒Live只读 pill + Fork草稿入口（变异要杀：拖拽/onChange/连线 handler 未读 live 守卫）。
4. 种「Agent mode=bypass 时 UI 直调真钱下单 / 晋级 / 跳 OrderGuard·审批·过拟合·血统门」→ 门必抓：权限轴⟂治理轴，bypass 仅省 Agent 自身确认、绝不跳任何治理门（沿用 T-029 入口×门矩阵，变异要杀：bypass 分支短路掉门校验）。
5. 种「MOCK fixtures 渲染但无 MOCK 角标 / 角标被折叠隐藏」→ 门必抓：画布/Dock/Inspector 的 mock 数据带诚实 MOCK 角标（变异要杀：删 MockBadge 仍过测）。

## 复用 [按需]
G1（DeskShell/DeskTopBar/DeskSwitcher/SegmentedControl/SubTabBar/CollapsiblePanel/Pill/StatusDot/MockBadge + theme-cc `--desk-*` token + per-desk accent 策略橙 + cssToObj）；G2（画布引擎全套受控组件 + geometry 世界↔屏幕换算/端口锚点/贝塞尔）；G3（AgentChat 7 型气泡 / Inspector 段控+ParamRow / Dock）；现有 `lib/auth.ts`（authFetch 占位，S2 接线用）。

## 红线 [按需]
RunDetailPage 冻结：节点只跳转单段 `/runs/:runId`、不嵌入不深色化重构（GOAL §0 / RULES.project §10）；权限轴⟂治理轴：bypass 绝不跳 OrderGuard/审批/过拟合/血统门（D-PERM）；默认止于模拟盘（runtime 初始 backtest，不自动导向直接实盘）；弱点一等呈现：Inspector/Dock 校验里 red/PBO/DSR/血统默认展开不染绿不折叠（R25）；裁决/校验措辞禁「可信/安全/排除过拟合/保证」、文案走后端 `_verdict_note`（R7，P0 mock 阶段用占位但不得出现违禁绝对措辞）；A股 live 下单永远拒；下单唯一入口经 OrderGuard、实盘 key 不进 LLM；扩展不替换（App.tsx/Shell.tsx 只加路由与导航项）。

## 非目标 [按需]
不接真后端 / 不实装 SSE 工具流（→ S2 `9fd4f1a6`）；不改 G2 画布引擎本体或 G3 受控组件内部（只消费）；不实装代码抽屉真 codegen（前端拼字符串 mock 预览，真序列化归 S2）；不碰因子台/Model台/模拟台/Agent 主台（各自台卡）；不动冻结 RunDetailPage 任何交互逻辑。

## Open Questions（已决 3/3）[按需]
- [已决] 节点「↗打开回测」用 React Router `navigate('/runs/:runId')` 单段跳转，复用 App.tsx L39 冻结分支（不在策略台内嵌 RunDetailPage）。
- [已决] 策略台业务态（nodes/edges/sel/pan/zoom/runtime/agentMode/undo 栈等 ~30 键）由本台 page 持有，G2/G3 全受控（props 下传 + 回调上抛），引擎/对话壳不持本台业务状态。
- [已决] P0 用 DC 原型硬编码 mock fixtures 驱动跑通 UI，全部 mock 数据带 MOCK 角标；接后端归 S2，本卡不留半接线状态。

## 验收一句话 [必填]
策略台四区像素对齐 DC token、mock 可拖拽连线缩放 Undo、locked 不可删、live 只读、bypass 不跳治理门、节点跳转严格落单段 `/runs/:runId` 冻结分支、mock 带诚实角标；种上述 5 类坏门必抓且不破现有 Shell/RunDetailPage 测试基线。
