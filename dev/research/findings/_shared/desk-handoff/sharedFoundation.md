I now have a complete, verified picture across all desks plus the existing React baseline. Here is the analysis.

---

# 跨台共享地基分析 — DC→React 还原依据

## 0. 大框架先立（假设，可被细节推翻）

6 个 DC 台分**两套设计系统**：
- **暗色 IDE 套（5 台）**：策略台 / 因子台 / Model台 / 模拟台 / QuantBT Agent —— 共享 `#1c1b19` 底 + JetBrains Mono + `#201f1c` 顶栏 + `#302d29` 边框 + 橙 `#d97757` 品牌。**这是地基本体**。
- **遗留浅色套（1 台）**：`回测详情.dc.html` —— 完全独立的 `jq-*` 前缀系统（`#f0f2f5` 底、`#1a2b4a` 蓝顶栏、微软雅黑、ECharts CDN）。这是 JoinQuant 风的旧详情页，**与暗色套零共享**。它已对应现有 React `app/frontend-run-detail/`（独立 package，graphify community=127/265），还原时**不并入地基**，单独走。

下面 1-4 全部针对**暗色 IDE 套**。

---

## 1. 跨台共享 UI 清单（标注出现台）

| 组件 | 出现台 | DC 实现要点 |
|---|---|---|
| **顶栏壳 TopBar** | 全 5 台 | `height 42–44px · bg #201f1c · border-bottom #302d29`。策略台 44px（无红绿灯点），其余 4 台 42px + macOS 三红绿灯点 `11px #3a3733` |
| **台切换器 DeskSwitcher** | 全 5 台（Agent 除外＊） | pill 组：`bg #1a1916 border #302d29 radius 8px pad 3px`，当前台 = 实心品牌色块，其余 = `<a>` 链接 hover `#2a2723`。**每台用自己的品牌色高亮**（见 §2 accent 表） |
| **品牌字标** | 全 5 台 | `✳ #d97757` + `QuantBT 600` |
| **段控/SegmentedGroup** | 全 5 台（策略×2 因子×3 Model 模拟×2 Agent×2）| `bg #1a1916 border #302d29 radius 7–8px pad 2–3px` 内含 `<sc-for>` 按钮组；驱动 runtime/mode/market/inspector-tab 切换 |
| **Sub-Tab 二级标签条** | 因子台(库/相关/评测/构建)、Model台、模拟台 | `padding 8px16 bg #1a1916 border-bottom` + 按钮，active 态走 `{{ tab* }}` 计算样式 |
| **左侧可折叠面板（折叠成 32–34px 竖条 + 竖排文字）** | 全 5 台 | `writing-mode:vertical-rl` 竖条 + `‹ / ›` toggle。策略/Agent=Agent对话，Model=训练队列，模拟=模拟盘列表，因子=因子详情 |
| **Agent 对话栏** | 策略台、QuantBT Agent（专属台）；Model台=「构建助手」变体 | 角色气泡：user `> #d97757`、think `✻ 斜体 #8a7e6a`、say `● #e6e1d6`、patch `⟳`、proposal/Ghost `◇ #b89cd8`。底部输入 `> ` prompt + 模型/mode/branch 状态行 |
| **画布引擎 Canvas（pan/zoom/拖拽/连线/marquee/MiniMap）** | 策略台（满配）；因子台「相关性」视图（轻量）| `#sb-pan transform:translate(panX,panY) scale(zoom)` + `<svg>` 边 + 节点端口 `onPointerDown/Up` 连线 + marquee 框选 + 网格底 `gridStyle` |
| **节点卡 NodeCard** | 策略台（满）、因子台 | header(色点+标题+diff badge+🔒lock+状态脉冲点) + body(行+badge) + 进/出端口圆点 14px `cursor:crosshair` + Ghost 虚线变体 |
| **MiniMap 缩略图** | 策略台 | 右下 `158×104 rgba(22,21,18,.82)` + miniNodes + 视口框 |
| **画布控制条 CanvasControls** | 策略台 | zoom −/%/＋ · 适应 · ⧉自动布局 · hint · MOCK 徽章 · 选中计数 |
| **画布浮层横幅（diff/血缘 trace）** | 策略台 | `position:absolute top:10 left:50%` 居中胶囊，蓝=diff、黄=血缘 |
| **Inspector 检查器 340px** | 策略台（满）；因子台/Model台/模拟台 = 右侧详情面板同构 | header(◰+标题+`›`折叠) + 选中体头(色点+标题+category/state pill) + inspTabs 段控 + 参数表(label+tip`?`+input) |
| **底部 Dock 228px** | 策略台 | dockTabs 段控(预览/Schema/统计/日志/历史) + 内容区 + MOCK + `▾`折叠 |
| **Pill / Badge** | 全 5 台（策略 18 处最密）| `radius 20px border 1px` 单色态：MOCK蓝 `#6f9bd1`、兼容绿、Live锁黄 `#d9b25f`、lifecycle、family 等 |
| **版本 Popover** | 策略台 | `versionLabel ▾` → 浮层版本历史 + Clone/Branch/对比/回滚 |
| **Live 治理条 + Fork/Kill** | 策略台、模拟台 | `🔒 Live 只读` 黄徽 + Fork草稿绿钮 + Kill 钮 |
| **状态脉冲点 StatusDot** | 全 5 台 | `border-radius:50% + animation:*pulse/ring/blink`（每台自带 keyframes：sb*/ff*/cc*/p*）|
| **MOCK 数据徽章** | 全 5 台 | 蓝胶囊，提示非真后端 |

＊QuantBT Agent 台无台切换 pill（它是 Agent 主页/全屏对话），但顶栏壳/红绿灯/段控/pill 全共享。

---

## 2. 共享 design system（唯一全局 token 集）

**结论：暗色 5 台 token 高度一致，但有一处关键差异——每台一个「主题 accent」**。除 accent 外，灰阶/边框/字体/圆角/动画完全统一。

### 唯一全局 token 集（暗色套，从 DC 反推）
```
/* 底层 */                          /* 文字 */
bg            #1c1b19              text          #e6e1d6
bg-topbar     #201f1c              text-soft     #cfc8ba / #a39a8a
bg-panel      #1b1a17              text-dim      #8f897c
bg-canvas     #191815 / #161512   text-muted    #6f6a61 / #5f5b53
bg-input      #161512
bg-soft-btn   #1a1916            /* 边框 */
bg-hover      #2a2723 / #211f1c    border        #302d29
                                   border-soft   #2a2723 / #262320
/* 圆角阶 */                        border-strong #3a3733 / #4a463f
radius-sm 6px · radius 7–8px · radius-lg 11px · pill 20px

/* 字体 */  JetBrains Mono / ui-monospace / SF Mono / Menlo （全台等宽，无 sans 正文）
/* 字号阶 */ 9–10px 徽标 · 11–11.5px 正文/钮 · 12.5px 面板标题 · 14px 选中标题 · 17px 大标题
/* 动画 */  pulse(opacity)·ring(box-shadow 扩散)·blink·dash(stroke-dashoffset 流动连线)
```

### 每台主题 accent（**唯一不一致项**）
| 台 | accent | selection / ring rgba | 当前台 pill 配色 |
|---|---|---|---|
| 策略台 | 橙 `#d97757` | `217,119,87,.28` | `#d97757`/字`#1c1b19` |
| QuantBT Agent | 橙 `#d97757` | 同上 | — |
| Model台 | 橙品牌＋蓝 `#6f9bd1` 台色 | `217,119,87` | `#6f9bd1`/字`#16202c` |
| 因子台 | 紫 `#a98fd4`/`#b89cd8` | `169,143,212,.30` | `#a98fd4`/字`#1c1726` |
| 模拟台 | 绿 `#9bbd5a` | `155,189,90,.28` | `#9bbd5a`/字`#16200f` |

辅助语义色（全台共用）：success 绿 `#9bbd5a/#bcd98a`、info/MOCK 蓝 `#6f9bd1`、warning/Live 黄 `#d9b25f`、danger 红 `#d97066/#c95757`、ghost 紫 `#b89cd8`。

> 与现有 `theme-cc.css` 的关系：theme-cc 用 `#1a1a1a/#232323/#333/#d97757`，DC 用 `#1c1b19/#201f1c/#302d29/#d97757`——**色相同方向、具体值略有偏移**。还原时建议把 DC 这套精确值落成 `--desk-*` token 子集（见 §4），accent 做成 per-desk CSS 变量 `--desk-accent`。

---

## 3. 建议抽出的共享组件清单（目录草案）

```
app/frontend/src/components/desk/            ← 新建：暗色 IDE 台地基
├── DeskShell.tsx          壳容器（顶栏+左折叠面板+中区+右Inspector+底Dock 槽位）
├── DeskTopBar.tsx         顶栏（红绿灯点 + 字标 + children 插槽）
├── DeskSwitcher.tsx       台切换 pill 组（current + links，accent 由 prop）
├── SegmentedControl.tsx   段控（全台最高频，sc-for 钮组 → React map）★最该先抽
├── SubTabBar.tsx          二级标签条（因子/Model/模拟）
├── CollapsiblePanel.tsx   左侧可折叠面板（含 vertical-rl 折叠竖条 + toggle）
├── Pill.tsx               pill/badge（variant: mock/success/warning/danger/info/ghost/lifecycle）★高频
├── StatusDot.tsx          脉冲状态点（variant + animation: pulse/ring/blink）
├── MockBadge.tsx          MOCK 徽章（薄封装 Pill）
├── inspector/
│   ├── Inspector.tsx      340 容器（header+折叠+选中体头+tabs 槽）
│   ├── InspectorTabs.tsx  段控复用
│   └── ParamRow.tsx       参数行（label+tip?+input）
├── dock/
│   ├── Dock.tsx           228 容器（tabs+折叠+内容槽）
│   └── DockTabs.tsx       段控复用
├── canvas/                ← 仅策略台（+因子相关性）需要，重点工程
│   ├── GraphCanvas.tsx    pan/zoom/marquee/grid 引擎（transform translate+scale）
│   ├── NodeCard.tsx       节点卡（header/body/ports/ghost/lock/diff badge）
│   ├── NodePort.tsx       连线端口（pointer 事件 + crosshair）
│   ├── EdgeLayer.tsx      SVG 边 + ghost 边 + 流动 dash 动画
│   ├── MiniMap.tsx        右下缩略图 + 视口框
│   ├── CanvasControls.tsx zoom/适应/自动布局/hint
│   └── CanvasBanner.tsx   diff/血缘 居中浮层横幅
└── agent/
    ├── AgentChat.tsx      对话容器（策略台栏 + Agent 主台 + Model「构建助手」共用）
    ├── ChatBubble.tsx     user/think/say/patch/proposal(Ghost) 角色气泡
    └── ChatComposer.tsx   底部 > 输入 + 模型/mode/branch 状态行
```

**单台专属（不进 desk/，留 pages/ 下）：**
- 版本 Popover、Live 治理条/Fork/Kill、MiniMap（仅策略台用，可放 canvas/ 但只 1 处消费）→ 策略台专属
- 训练队列卡 + TensorBoard 嵌入 → Model台专属
- 模拟盘列表 + 净值曲线 + PaperScheduler → 模拟台专属
- 因子库/相关性矩阵/评测台/构建台 → 因子台专属
- `回测详情` 整套 `jq-*` → 不进 desk/，沿用现有 `app/frontend-run-detail/`

---

## 4. 对照现有 `components/` + theme-cc.css：复用 vs 新建

graphify 确认现有 `components/` 只有 8 个文件 + `shell/Shell.tsx` + `charts/EvalCharts.tsx`，**全部是路由式后台风，不是 IDE 台风**。

**可复用（直接接）：**
- `theme-cc.css` —— token 体系骨架（`--cc-*` 命名约定、light/dark、mono 字体栈、pill/chip/btn/table/tabs/lifecycle/scrollbar/响应式）。**地基应扩展它而非另起**：新增 `--desk-bg:#1c1b19 / --desk-topbar:#201f1c / --desk-border:#302d29 / --desk-accent`（per-desk override）一组子 token，复用其 lifecycle pill、`.cc-mono`、响应式断点。
- `charts/EvalCharts.tsx`（自绘 SVG line/bar/scatter，PALETTE/scale/PAD）—— Inspector/Dock 里的迷你图、模拟台净值曲线可复用。
- `StatusPill.tsx`（status→中文 label）—— `Pill.tsx` 的 status 变体可并入/复用其 label map。
- `MetricCard.tsx`、`charts/` PALETTE —— Dock 统计区、Inspector 指标。

**必须新建（现有库完全没有）：**
- 全部 `desk/` 下组件 —— 现有 `Shell.tsx` 是 topbar+sidebar+statusbar 的**路由壳**，与 DeskShell（左折叠/中画布/右Inspector/底Dock 的**IDE 四栏**）是两种壳，**不可改造复用，平行新建**。
- 画布引擎全套（GraphCanvas/NodeCard/Port/EdgeLayer/MiniMap）—— 仓库零基础，是地基最重工程。
- AgentChat 全套 —— 现有无对话组件。
- SegmentedControl / CollapsiblePanel / Inspector / Dock —— 全新。

**冲突/取舍提示（留给拍板）：**
1. **token 双源风险**：theme-cc 的 `#1a1a1a` vs DC 的 `#1c1b19` 不一致。建议**统一到 DC 精确值**并让 theme-cc 引用，避免两套深色漂移。
2. **per-desk accent**：是做成 4 个静态主题 class（`.desk--strat/.desk--factor/...`）还是单 CSS 变量 `--desk-accent` 由路由注入——影响 DeskSwitcher/StatusDot/Pill 全链。
3. **Shell vs DeskShell 并存**：现有路由（/runs /workshop 等）走旧 Shell，新台走 DeskShell，需定路由边界（哪些 path 进 IDE 壳）。

---

## 关键文件路径（绝对）
- 地基源（暗色 5 台）：`/tmp/qbt-handoff/quantbt-claude/project/{策略台,因子台,Model台,模拟台}.dc.html` + `/tmp/qbt-handoff/quantbt-claude/project/QuantBT Agent.dc.html`
- 遗留浅色独立套：`/tmp/qbt-handoff/quantbt-claude/project/回测详情.dc.html`（对应 `/Users/wzy/Work/01_Projects/QuantBT/app/frontend-run-detail/`）
- DC runtime：`/tmp/qbt-handoff/quantbt-claude/project/support.js`（`<x-dc>`/`{{}}`/`<sc-for>`/`<sc-if>`/`style-hover` 编译为 React）
- 现有可复用 token：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/theme-cc.css`
- 现有路由壳（平行参考、不复用）：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/components/shell/Shell.tsx`
- 现有可复用图表：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/components/charts/EvalCharts.tsx`
- 现有小组件：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/components/{StatusPill,MetricCard}.tsx`
- 建议新建地基目录：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/components/desk/`