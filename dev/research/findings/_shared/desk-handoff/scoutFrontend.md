I have all the data needed. Producing the structured report.

---

# QuantBT 前端架构侦察 · 策略台落点报告

调查目标 = `app/frontend/`(主前端,Vite+React Router+TS)。注意:仓库另有 `app/frontend-run-detail/`(冻结页独立子工程)和 `app/desktop/`(Tauri)。本报告全部针对 `app/frontend/`。

## 1. 路由结构(`app/frontend/src/App.tsx`)

App 是 `<Routes>` 单层路由,**唯一例外**是冻结的 RunDetail 走独立 `jq-app` 布局、绕过整个 Shell:

```
isFrozenRunDetail = /^\/runs\/[^/]+$/  →  <RunDetailPage/> 裸渲染(无 Shell)
```

其余全部包在 `<Shell>` 里。完整路由表(路径 → 组件 → 文件):

| 路径 | 组件 | 文件 | Shell area |
|---|---|---|---|
| `/` | HomePage | pages/HomePage.tsx | home |
| `/runs` | RunsPage | pages/RunsPage.tsx | research |
| `/runs/:runId` | **RunDetailPage(冻结)** | pages/RunDetailPage.tsx | (绕过 Shell) |
| `/compare` | ComparePage | pages/ComparePage.tsx | research |
| `/data` | DataPage | pages/DataPage.tsx | research |
| `/strategies` | StrategyIndexPage | pages/StrategyIndexPage.tsx | research |
| `/workshop` | StrategyWorkshopPage | pages/workshop/StrategyWorkshopPage.tsx | workshop |
| `/agent` | AgentChatPage | pages/workshop/AgentChatPage.tsx | workshop |
| `/factors` | FactorMarketPage | pages/workshop/FactorMarketPage.tsx | workshop |
| `/trading` | BinanceTradingPage | pages/workshop/BinanceTradingPage.tsx | workshop |
| `/experiments` | ExperimentTrackingPage | pages/workshop/ExperimentTrackingPage.tsx | workshop |
| `/ide` | IDEPage | pages/workshop/IDEPage.tsx | workshop |
| `/chat` | Mode2ChatPage | pages/workshop/Mode2ChatPage.tsx | workshop |
| `/training` | TrainingBenchPage | pages/models/TrainingBenchPage.tsx | models |
| `/models` | ModelLibraryPage | pages/models/ModelLibraryPage.tsx | models |
| `/login` `/register` | LoginPage | pages/community/LoginPage.tsx | community |
| `/community` | CommunityFeedPage | pages/community/CommunityFeedPage.tsx | community |
| `/square` | SharedStrategiesPage | pages/community/SharedStrategiesPage.tsx | community |
| `/copy-trade` | CopyTradePage | pages/community/CopyTradePage.tsx | community |
| `/glossary` `/glossary/:slug` | GlossaryIndex/Detail | pages/community/ | community |
| `/metrics/funnel` | FunnelDashboardPage | pages/FunnelDashboardPage.tsx | — |
| `/pricing` | PricingPage | pages/PricingPage.tsx | — |
| `/templates` | StrategyTemplatesPage | pages/StrategyTemplatesPage.tsx | workshop |
| `/settings/security` | SettingsSecurityPage | pages/SettingsSecurityPage.tsx | — |
| `/u/:username` | UserProfilePage | pages/community/UserProfilePage.tsx | community |

Shell 的左侧栏由 `areaOf(pathname)` 决定(`Shell.tsx:381`),sidebar 分组在 `SIDEBAR_BY_AREA`(`Shell.tsx:18`),顶栏五大区:Home / Research / Workshop / Models / Community(`TopNav` `Shell.tsx:136`)。**没有任何 `*Console*` 页面存在**,`StrategyConsole`/`策略台` 在 src 内零命中。

## 2. 现有策略相关页面职责 + 与设计稿重叠判断

| 页面 | 路由 | 职责(实读) | 与"策略台编辑器"重叠度 |
|---|---|---|---|
| **StrategyWorkshopPage** | `/workshop` | 极薄(143 行)。一个 textarea → POST `/api/agent/slot_fill` → 右侧渲染 StrategyGoal JSON。纯"自然语言→意图 schema",**无编辑器/无版本/无 run**。 | 低。是策略台的"目标录入"前置环节 |
| **StrategyIndexPage** | `/strategies` | quantpedia 风**只读索引**。`GET /api/runs` 按 asset_class 分组卡片,每卡显 Sharpe/PBO/DSR/MaxDD,点击 → `/runs/:runId`。是"策略发现/浏览"。 | 低。是入口列表,不是工作台 |
| **StrategyTemplatesPage** | `/templates` | 模板广场。`GET /api/strategies/templates` 列 3 模板,一键 `POST .../fork_to_ide` → `navigate(ide_url)`。 | 中(**fork** 语义已实现,但目标是 IDE) |
| **IDEPage** ⭐ | `/ide` | **最重(700+ 行,与设计稿重叠最大)**。聚宽风三栏:左策略文件列表、中 textarea 代码编辑器+行号+toolbar(运行/保存/AI)、右 tab(运行输出/AI 助手)。已实现 save/run/delete/promote/AI 补全/risk_preview。 | **高**。它已是"编辑+跑+提升"的策略工作台 |

**重叠结论**:设计稿(顶栏 tab 导航 / 版本 / Live 只读 / Fork / kill / validate / 编译源码 / 发布)= **一个治理增强版的 IDEPage**。当前 IDEPage 已覆盖 编辑 / save / run / fork(经 templates) / promote(≈发布到正式 run);**缺口** = 顶栏 tab 多视图、版本历史、Live 只读态、kill(后端有 `/api/risk/kill_switch`)、validate(后端无独立端点)、"编译源码"独立视图、正式 publish(后端有 `/api/sharing/publish`)。

**判断:新建 `StrategyConsolePage`,不要在 IDEPage 上原地膨胀。** 理由(工程取舍四面):
- **优点**:IDEPage 定位是"聚宽风轻量代码沙箱实验",已 700+ 行;治理态(版本/Live/kill/发布)是不同心智模型,塞进去会两套状态机纠缠。新页可走顶栏 tab 把"编辑/版本/Live/源码/发布"做成清晰分区。
- **效果是否一样**:不一样。增强 IDEPage 会让"快速试代码"和"治理一条上线策略"挤在同一栏,UX 退化。
- **前后冲突**:IDEPage 仍被 `/templates` fork 流、Mode2 教练引用,改其布局有回归面;新页零回归。
- **架构和谐**:Console 可复用 IDEPage 的 `CodeEditor`/`RunOutput`/`AIPanel` 子组件(需先抽出),符合"扩展不替换"(RULES §2/§4)。建议 Console 落 workshop area(与 IDE/templates 同栏),或新建独立 area。

## 3. 主题系统(`theme-cc.css` / `styles.css`)

`theme-cc.css` **已经是 Claude Code 暗色主题**,`cc-*` 前缀,与 RunDetail 的 `jq-*` 完全隔离。CSS 变量(`:root[data-theme="dark"]`):

| 设计稿要求 | 现有变量 | 一致? |
|---|---|---|
| 背景 `#1c1b19` | `--cc-bg: #1a1a1a` | **接近但不等**(差 2 个色阶) |
| 橙 `#d97757` | `--cc-accent: #d97757` | ✅ **完全一致** |
| JetBrains Mono | `--cc-mono: "SF Mono","JetBrains Mono",…` | ✅ 已在字栈 |

配套已有:`--cc-bg-elevated #232323` / `--cc-border #333` / 语义色 success/warning/danger/info、light mode 全套、`--cc-radius`、tab 类(`.cc-tabs`/`.cc-tab`/`.cc-tab.active` 在 `theme-cc.css:696`)。**结论:可直接复用,无需引入新主题。** 唯一微差是背景 `#1a1a1a` vs 稿 `#1c1b19` —— 若要像素级对齐,改 `--cc-bg` 一处即可(全局生效,需评估对现有页影响,属"动主题"小心)。橙色与字体已 100% 命中。

## 4. 可复用组件(`app/frontend/src/components/`)

- `shell/Shell.tsx` — Shell/TopNav/Sidebar/StatusBar/MobileDrawer + `SIDEBAR_BY_AREA`/`areaOf`。**策略台必经此挂载**;加路由要同步改 `SIDEBAR_BY_AREA` + `areaOf`。
- `charts/EvalCharts.tsx` — 回测评估图表,Console 的指标预览可复用。
- `MetricCard.tsx` / `StatusPill.tsx` — 指标卡 / 状态胶囊,直接可用。
- `JobPanel.tsx` / `JobProgressBanner.tsx` — 异步 job 进度(run 跑批可复用)。
- `FieldsPanel.tsx` / `DataPullPanel.tsx` / `Jq*Panel.tsx` — 数据/持仓/成交面板(策略台"持仓/成交"tab 可借)。
- **IDEPage 内部子组件**(同文件内,未抽出):`CodeEditor()`(L439)、`RunOutput()`(L506)、`AIPanel()`(L605)。Console 要复用编辑器/输出栏,**建议先把这三个抽成 `components/` 下共享组件**,再两页共用。
- `lib/auth.ts` — `getStoredUser()` / `authFetch()`(带 token),所有写操作走它。

## 5. API 层(`api.ts` + `app/backend/app/main.py`)

`api.ts` 封装的主要是 **run/data/job** 系列(`listRuns`/`queryRuns`/`getRun`/`getRunSeries`/`compareRuns`/`getRunSource`/`getRunTable`/data files/jobs CRUD)。**注意:策略/IDE 端点没进 `api.ts`**,各页面直接 `fetch`/`authFetch` 裸调。后端是单文件 `main.py`(3284 行,FastAPI `@app.*`,无 APIRouter)。

策略台需要的操作 vs 后端现状:

| Console 操作 | 后端端点 | 状态 |
|---|---|---|
| 列策略/读/存/删 | `GET/POST/DELETE /api/ide/strategies[/{name}]` (main.py:2308-2336) | ✅ 已有 |
| **run** | `POST /api/ide/strategies/{name}/run` (2345) + `GET /api/ide/runs[/{id}]` (2354) | ✅ 已有(沙箱) |
| 运行产物/风险预览 | `GET /api/ide/runs/{id}/{kind}` (2370) + `/risk_preview` (2451) | ✅ 已有 |
| **promote(→正式 run)** | `POST /api/ide/runs/{id}/promote` (2520) → 返回 `run_url` | ✅ 已有 |
| **fork** | `POST /api/strategies/templates/{id}/fork_to_ide` (2774);通用分享 fork `POST /api/sharing/{share_id}/fork` (1776) | ⚠️ 仅"模板/分享 fork",**无"任意策略版本 fork"** |
| **publish(发布)** | `POST /api/sharing/publish` (1716) | ✅ 有(走分享体系,非"上线") |
| **kill** | `POST /api/risk/kill_switch` (1482,需 IP 白名单+密码) | ✅ 有(交易级硬墙) |
| **validate** | — | ❌ **无独立 validate 端点**(目前 run 即隐含校验) |
| **编译源码 / 源码视图** | `GET /api/runs/{id}/source` (2265) + `/api/ide/ai_context`(含 code_skeleton) | ⚠️ 部分(正式 run 有 source;IDE 策略源即 code 字段) |
| **版本历史** | — | ❌ **无版本端点**(IDE strategy 只存最新 code,save 覆盖) |
| **Live 只读态** | `/api/trading/*`(BinanceTrading)、`/api/paper`(paper 模块存在) | ⚠️ 有交易台但无"策略 Live 只读快照"端点 |
| 目标录入 | `POST /api/agent/slot_fill` (1534) | ✅ 已有 |

**缺口小结**:validate、版本历史、"策略级 fork"、"Live 只读快照" 这四项后端尚无对应端点 —— 策略台落地前需与后端对齐(或先做前端壳 + 标 🟡 未接真)。其余(编辑/run/promote/kill/publish/源码)端点齐备。

## 6. 冻结约束(GOAL §M15)

- `RunDetailPage`(`pages/RunDetailPage.tsx`,55KB)是 **GOAL 唯一原硬约束冻结页**:只允许排版/显示逻辑/加字段,不可重构。
- App.tsx 用 `/^\/runs\/[^/]+$/` 把它**单独拎出 Shell**,走 `jq-app`/`jq-main--wide` 裸布局,用 `jq-*` 老 CSS。
- **策略台会触碰它的两个点**:(a) IDEPage `promote` 后 `navigate(run_url)` → 跳 `/runs/:id`;StrategyIndexPage/StrategyCard 也 `<Link to="/runs/:id">`。Console 同理会跳回测详情。
- **落地注意**:
  1. Console **只能"跳转到" `/runs/:runId`,绝不嵌入/iframe/复用 RunDetailPage 组件** —— 嵌入会被迫触碰冻结页布局。
  2. 跳转 URL 必须严格匹配 `/runs/{单段}`,否则会落进 Shell 分支(冻结意图失效)。带 query/子路径(如 `/runs/:id/console`)会**不被识别为冻结**,需避开。
  3. Console 自身全程用 `cc-*` 主题,**不要引入 `jq-*` 类**(隔离纪律)。

## 7. 落点建议

**一句话结论**:新建 `StrategyConsolePage`(路由 `/console` 或 `/strategy/:name`,挂 workshop area),把 IDEPage 的 `CodeEditor`/`RunOutput`/`AIPanel` 抽成共享组件后复用;顶栏 tab 做"编辑/版本/Live/源码/发布"分区;主题直接吃现有 `cc-*` 暗色(橙+JetBrains 已命中,背景 `#1a1a1a` 视需微调为 `#1c1b19`)。**不增强 IDEPage、不嵌入冻结的 RunDetailPage(只跳转)。** validate/版本/策略级 fork/Live 只读 四个后端端点缺失,需先对齐或前端壳标 🟡。

**新增文件清单(草案)**
- `app/frontend/src/pages/workshop/StrategyConsolePage.tsx` — 策略台主页(顶栏 tab shell)
- `app/frontend/src/components/editor/CodeEditor.tsx` — 从 IDEPage L439 抽出共享
- `app/frontend/src/components/editor/RunOutput.tsx` — 从 IDEPage L506 抽出
- `app/frontend/src/components/editor/AIPanel.tsx` — 从 IDEPage L605 抽出(可选)
- `app/frontend/src/api.ts` 内**新增** strategy/ide 端点封装(目前裸 fetch,建议收口进 api.ts)

**需改动的现有文件**
- `app/frontend/src/App.tsx` — 加 `<Route path="/console" element={<StrategyConsolePage/>} />`(确保**不**形如 `/runs/...`,避开冻结正则)
- `app/frontend/src/components/shell/Shell.tsx` — `SIDEBAR_BY_AREA.workshop` 加一项「策略台」;`areaOf()` 把 `/console` 归入 workshop(若另立 area 则两处都改 + 加 `AREA_LABEL` + TopNav 加项)
- `app/frontend/src/pages/workshop/IDEPage.tsx` — 改为 import 抽出的共享编辑器组件(扩展不替换,保持 `/ide` 行为不变,需回归 templates fork 流)
- `app/frontend/src/theme-cc.css` —(可选)`--cc-bg: #1a1a1a → #1c1b19` 像素对齐,属"动主题"需评估全局影响
- 后端 `app/backend/app/main.py` — 若要 validate/版本/策略级 fork/Live 只读,新增对应 `@app.*` 端点(扩展不替换)

**关键路径锚点**:App.tsx 冻结正则 `App.tsx:39`;Shell 导航源 `Shell.tsx:18`(SIDEBAR)/`:381`(areaOf)/`:136`(TopNav);主题变量 `theme-cc.css:17-83`;IDE 后端端点群 `main.py:2308-2520`;kill/publish/fork `main.py:1482/1716/1776/2774`。