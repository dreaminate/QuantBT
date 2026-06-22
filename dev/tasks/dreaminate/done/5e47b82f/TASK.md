---
uuid: 5e47b82f3ba847938f4000fadf9c2fb7
title: 因子台前端 P0 — 5 视图像素还原 + mock(库/相关/评测/构建DSL/研究)
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871, d5ea778c285a46e0872dba3a87ab1182]
---

# 因子台前端 P0 — 5 视图像素还原 + mock(库/相关/评测/构建DSL/研究)

## Scope [必填]
增强 `app/frontend/src/pages/workshop/FactorMarketPage.tsx` → 因子台容器（FactorDeskPage），把 DC 原型「因子台.dc.html」的 5 个互斥子 tab 视图（因子库 / 相关性 / 评测台 / 构建台 / 研究台）像素还原成 React + `cc-*` className（紫 accent `#a98fd4`、状态机/因子族色板）；**因子库列表**复用现有真实 `GET /api/factors`，**其余 4 视图全 mock + 常驻「MOCK 数据」诚实角标**。**不做**：不新建任何后端端点（IC日序/衰减/分层回测/相关矩阵/校验/注册/audit/agent chat 全归 F2）、不改后端、不补设计稿缺漏的 §3 两骨干（本卡只列入 Open Question）。

## 上下文 / 动机 [按需]
DC handoff bundle 的「因子台.dc.html」(852 行) 是 inline-style 体系，本仓库前端是 `cc-*` className + CSS 变量体系（`app/frontend/src/theme-cc.css`），token 值已与设计稿零漂移（页面 bg `#1c1b19`、accent 紫 `#a98fd4`、橙 `#d97757`、JetBrains Mono），映射成本低。现有 `FactorMarketPage.tsx` 只覆盖设计稿「因子库列表」约 20%（无详情/相关/评测/构建/研究），且其 `fetch("/api/factors")` 是全台少数已对齐真实后端的接线，必须**增强不重写**以保住该接线。本卡是 epic cfb0fea9（整套台前端实装）的因子台 P0，依赖 G1 d11d1426 / G3 d5ea778c。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/frontend/src/pages/workshop/FactorMarketPage.tsx` | L14 `FactorMarketPage()` 整体 | 升级为容器 FactorDeskPage：保留 L20-25 `fetch("/api/factors")` 真实接线供因子库视图复用；外包 market 切换 + 5 sub-tab bar（▤因子库/⊞相关性/⚖评测台/⌨构建台/⚗研究台 互斥 view state） |
| `app/frontend/src/pages/workshop/FactorMarketPage.tsx` | L3-10 `interface FactorItem` | 扩展不替换：保留已对齐后端 `to_dict` 的字段子集；mock 视图新增的 `factor_family`/decay/layers/corr/audit 等独立 type 与真实 type 物理隔离，标 `// MOCK only` |
| `app/frontend/src/pages/workshop/FactorMarketPage.tsx` | L49 subtitle「44 个白箱算子」 | 校准：后端实测 `list_operators()` 注册 43 个算子（数字漂移），改为真实计数或 `{operators.length}` 动态拉取，禁硬编漂移数 |
| 新增 `app/frontend/src/pages/workshop/factor/FactorLibraryView.tsx` 等 5 个 view 文件 | 新建（容器拆分） | 库视图吃真实 `/api/factors`；相关/评测/构建/研究 4 视图吃本地 mock 常量，每个 mock 数据块挂 MOCK 角标组件 |
| `app/frontend/src/App.tsx` | L65 `<Route path="/factors" element={<FactorMarketPage />} />` | 路由 element 指向增强后的容器（仍导出 `FactorMarketPage` 名或同步改 import L8），不改 RunDetail 冻结分支 L41-50 |
| `app/frontend/src/theme-cc.css` | `cc-*` token 变量区 | 扩展不替换：补因子台特有语义色（状态机 6 色 / 因子族 5 色 / 代码块蓝 `#1b2330` / `ffpulse` 呼吸动画），命名前缀沿用 cc-，禁改既有 token |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「五态机阈值/前视检查渲染成假绿」——把一个 lifecycle_state=WARNING 或 IC≤0/前视检查未过的因子，UI 渲成 QUALIFIED 绿态或「前视检查 ✓无穿越」绿勾 → 门必抓：未验证态绝不显示为已通过，状态色与 `lifecycle_state` 真值一一对应，前视/校验标记仅在真为 pass 时为绿（违硬不变量「未验证≠已验证 R3」）。变异要杀点：状态→颜色映射函数若被改成恒返回绿/恒 pass，渲染快照断言必失败。
2. 种「IC/audit 弱点折叠或染绿」——把 red/低 IC/PBO/DSR/血统 等弱点指标默认折叠隐藏、或把不及格（IC≤0、|t|<3、ρ>0.7 冗余、verdict=未通过/存疑）染成绿色 → 门必抓：弱点一等呈现默认展开不折叠不染绿（R25），不及格走红 `#d97066`、边际走黄 `#d9b25f`，audit verdict「未通过/存疑」绝不绿。变异要杀点：阈值色函数若把红/黄分支短路成绿，或弱点区默认 `collapsed`，断言必失败。
3. 种「MOCK 视图无诚实角标」——相关/评测/构建/研究 4 视图渲染 mock 数据但缺「MOCK 数据」角标，伪装成真数据 → 门必抓：4 mock 视图必常驻 MOCK 角标（`#a98fd4` border `#4a4060`），因子库视图（真实 `/api/factors`）不误标。
4. 种「裁决/审查文案出现禁词」——研究台/详情区文案出现「可信/安全/排除过拟合/保证」 → 门必抓：禁词扫描断言为 0，裁决措辞走占位/后端 `_verdict_note`（R7）。

## 复用 [按需]
- 现有 `fetch("/api/factors")`（L20-25）+ `FactorItem`（L3-10）+ `FactorCard`（L139）+ `ORDER`（L12）+ `cc-lifecycle--{state}` className → 因子库视图直接复用，零重写真实接线。
- `theme-cc.css` 既有 `cc-*` token（bg/border/radius/scrollbar/selection 已与设计稿一致）→ 仅按因子业务扩状态机/族色板。
- 兄弟 workshop 页（StrategyWorkshopPage / AgentChatPage 的 chat 双栏布局）作为构建台/研究台「左聊天右工作区」布局范式参考。

## 红线 [按需]
- 默认止于模拟盘：因子台任何「注册/晋级/上线」按钮（含构建台 gate modal `bdGateYes`）本期为 mock，绝不导向直接实盘下单；不触 OrderGuard。
- 权限轴 ⟂ 治理轴：mock 的注册/晋级流不得在 UI 暗示可 bypass 过拟合门/血统门/审批门。
- RunDetailPage 冻结：本卡不碰 `App.tsx` L41-50 冻结分支与 RunDetail 交互逻辑。
- 弱点一等：red/PBO/DSR/血统/低 IC 默认展开、不染绿、不折叠藏起（R25）。

## 非目标 [按需]
- 不新建后端端点（IC 日序 / ic_decay / layered_backtest / correlation / validate / POST factors / audit / agent chat 全归 F2）。
- 不补设计稿缺漏的 §3 两骨干（三纯库结构 / 暴力遍历挖掘 view）——本期仅作 Open Question，待拍板后另立卡。
- 不实现真实因子 Agent / 学术审查 LLM 对话（R20 LLM 引导生成暂缓，chat 为 mock 拼接）。
- 不为后端补 `factor_family` / `market` 字段（前端 mock 自造，标 MOCK）。

## Open Questions（已决 D/总）[按需]
1. [已决] F1=B 用户 2026-06-21 拍板走 (b)：本期补两骨干（三纯库 + 暴力遍历挖掘），handoff 无稿由 leader 按 GOAL §3 + factor_factory 直接设计实装，**新立卡 F3 `a11e2aa5`（前端设计+实装）+ F4 `51271d38`（后端信号契约/挖掘守门引擎）承接**；本 F1 卡只还原 handoff 现有 5 视图，两骨干不在本卡。（D-DESK-F1B / GOAL §3 R17 三纯库 / R16 暴力遍历=诚实-N）

D/总：0/1（主控 build_card_counters 重算）

## 验收一句话 [必填]
种「五态机/前视渲假绿 + IC/audit 弱点折叠或染绿（含 MOCK 视图缺角标、裁决文案禁词）」→ 门必抓（状态色一一对应真值、弱点默认展开不绿、4 mock 视图常驻角标、禁词扫描为 0），且不破现有 `/api/factors` 接线与前端测试基线、不动 RunDetail 冻结。
