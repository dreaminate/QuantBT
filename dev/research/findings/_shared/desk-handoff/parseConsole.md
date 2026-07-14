I have now read both files completely, including the full `<script>` data block. Here is the structured report.

---

# 策略台 (StrategyBoard) — DC 原型完整还原报告

> 依据：`策略台.dc.html` (1250 行，主目标 · P0 画布原型) + `策略台蓝本.dc.html` (341 行，配套架构规格文档)。所有数值/色值/handler 均从源码逐行提取，非推断处已标注「推断」。

---

## 0. 文件性质与全局基底

| 项 | 值 |
|---|---|
| DC 根 | `<x-dc>`，内含 `<helmet>` (字体+全局样式) + 单一 `<div>` 全屏布局 + 尾部 `<script type="text/x-dc">` (一个 `class Component extends DCLogic`) |
| 字体 | `"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace`，从 Google Fonts 拉 weights 400/500/600/700 |
| 画布尺寸提示 | `$preview: { width:1440, height:920 }` (主文件) / `1280×900` (蓝本) |
| 全局背景 | `#1c1b19`；正文字色 `#e6e1d6`；`font-size:13px; line-height:1.5; user-select:none` |
| 滚动条 | 宽 9px，thumb `#3a3733` 圆角 6px，track 透明 |
| selection 高亮 | `rgba(217,119,87,0.28)` (即主橙 `#d97757` 的 28% alpha) |
| 渲染范式 | React-like：`state` + `setState` + `renderVals()` 把状态展平成视图模型，模板 `{{ }}` 全部取自 `renderVals()` 的 return 对象。`componentDidMount` 挂全局 pointer/key/wheel 监听，卸载时解绑。**无后端，刷新即重置，所有"运行/回测"是 setTimeout 流式 mock。** |

---

## 1. 整体布局骨架 (区域树)

根容器 `display:flex; flex-direction:column; height:100vh; position:relative`，三段纵向：TOPBAR (固定 44px) → BODY (flex:1) → 浮层 (popover/drawer 绝对定位)。

```
ROOT  flex column · 100vh · bg #1c1b19 · position:relative
│
├─ TOPBAR                         flex:none · h44 · flex row · align-center · gap10 · pad 0 14 · bg #201f1c · border-bottom #302d29 · z60
│   ├─ ✳ logo (#d97757) + "QuantBT" (600)
│   ├─ 台切换器 segmented        bg #1a1916 · border #302d29 · radius8 · pad3 · gap2
│   │     [因子台 link][Model台 link][策略台 ●active 橙底][模拟台 link]
│   ├─ 竖分隔 1×18 #302d29
│   ├─ 策略名 "strat_wk_cn_01" (600)
│   ├─ 版本按钮 {{versionLabel}} ▾  → verToggle (打开 version popover)
│   ├─ runtime 段控 segmented     [Backtest][Paper][Live]  (sc-for runtimeBtns)
│   ├─ ⟨sc-if liveGov⟩  🔒Live只读 pill + ⑂Fork草稿 btn + Kill Switch btn   ← 仅 runtime=live 出现
│   ├─ <spacer flex:1>
│   ├─ ↺ undo · ↻ redo  (禁用态变灰 #4a463f)
│   ├─ 竖分隔
│   ├─ ✓校验 btn   (errLabel/errColor/errBorder 动态)
│   ├─ ▷运行回测 btn (绿系 #1e261a/#3c5230/#bcd98a)
│   ├─ ⟨/⟩编译源码 btn (蓝系 #161f2a/#2c4452/#9bc4ea)
│   ├─ 发布▸ btn (透明边框)
│   └─ 蓝本↗ link (→ 策略台蓝本.dc.html)
│
├─ version popover  ⟨sc-if verMenuOpen⟩   absolute top48 left196 · w282 · bg #211f1c · border #3a352e · radius11 · shadow 0 16 40 rgba(0,0,0,.5) · z80
│     标题"版本历史·GraphVersion" + sc-for versionRows[{dot,label,lifecycle,对比btn,回滚btn}] + 底部[⎘Clone][⎇Branch][✕]
│
└─ BODY  flex:1 · min-h0 · flex column
    ├─ MAIN ROW  flex:1 · min-h0 · flex row
    │   │
    │   ├─ LEFT · AGENT
    │   │    ⟨sc-if leftCollapsed⟩ 折叠条 w32 · 竖排"Agent ›" · bg #1d1c19 · 点击展开
    │   │    ⟨sc-if leftOpen⟩ 面板 flex:none · w316 · flex column · border-right #302d29 · bg #1b1a17
    │   │        ├─ header  pad 9/13 · ✳Agent + mode段控[Ask|Auto|Bypass] + ‹折叠
    │   │        ├─ modeHint 行  pad6/13 · font9.5 · #7d7668
    │   │        ├─ scroll区 #sb-agentscroll  flex:1 · overflow-y · pad10/13
    │   │        │     "上下文 · {{ctxLabel}}" + sc-for agentBlocks(user/think/say/patch) + ⟨sc-if hasProposal⟩ Ghost提议卡
    │   │        └─ composer  flex:none · border-top · textarea + ↵send + 状态行(⏺sonnet-4.5 │ mode │ ⎇branch)
    │   │
    │   ├─ CENTER · CANVAS   flex:1 · min-w0 · flex column · bg #191815
    │   │    ├─ 工具条  flex:none · pad7/12 · border-bottom · bg #1d1c19
    │   │    │     [−][{{zoomPct}}][＋][适应][⧉自动布局] │ canvasHint … <spacer> [MOCK数据 pill][selCountLabel]
    │   │    └─ 画布面 #sb-graph  flex:1 · position:relative · overflow:hidden · cursor动态 · 点阵网格背景
    │   │          ├─ ⟨sc-if diffOn⟩ diff banner (顶部居中)
    │   │          ├─ ⟨sc-if traceOn⟩ 血缘 banner (顶部居中)
    │   │          ├─ ⟨sc-if marqueeOn⟩ 框选矩形 (虚线蓝)
    │   │          ├─ #sb-pan  absolute inset0 · transform translate(panX,panY) scale(zoom) · origin 0 0
    │   │          │     ├─ sc-for stages[]   语义阶段框 (虚线圆角框 + 顶部 -26px 标题"NN · 名 · N节点·完成")
    │   │          │     ├─ <svg> 连线层  defs#sbarrow + sc-for edges[] + sc-for ghostEdges[] + ⟨sc-if linkOn⟩拉线预览
    │   │          │     ├─ sc-for ghostNodes[]  虚线紫卡 (Agent 提议预览)
    │   │          │     └─ sc-for nodes[]  in端口·out端口·节点卡(head色块+标题+badge+lock+state点 / body行+badge+↗打开回测)
    │   │          ├─ MiniMap  absolute right12 bottom12 · 158×104 · sc-for miniNodes + 视口框
    │   │          └─ 兼容性图例  absolute left12 bottom12 · 4 个 pill (兼容/可适配/需转换/不兼容)
    │   │
    │   └─ RIGHT · INSPECTOR
    │        ⟨sc-if rightCollapsed⟩ 折叠条 w32 · 竖排"‹ Inspector" · ◰图标(#6f9bd1)
    │        ⟨sc-if rightOpen⟩ 面板 flex:none · w340 · flex column · border-left · bg #1b1a17
    │            ├─ header  ◰ + {{inspTitle}} + ›折叠
    │            ├─ ⟨sc-if hasSel⟩ 选中节点视图：标题卡 + tab段控[参数|端口|校验|版本/血缘] + 各 tab 内容
    │            └─ ⟨sc-if noSel⟩ 无选中视图：图校验概览 (GraphValidationResult) + issue 列表 + 操作提示
    │
    └─ BOTTOM · WORKBENCH (dock)
         ⟨sc-if dockCollapsed⟩ 折叠条 h30 · "▤ 工作台 · 输出/日志/运行历史/血缘溯源" · ▴
         ⟨sc-if dockOpen⟩ 面板 flex:none · h228 · flex column · border-top · bg #1a1916
             ├─ tab条  sc-for dockTabs[输出预览|Schema|统计|日志|运行历史|血缘溯源] + MOCK pill + ▾收起
             └─ 内容区  flex:1 · overflow:auto · pad11/14 · 7 种互斥 sc-if (见 §4)

浮层 (BODY 之外，根 div 内，全部 absolute)：
 ├─ ⟨sc-if publishOpen⟩  发布抽屉  右侧 w392 · 遮罩 z90 · 抽屉 z91
 └─ ⟨sc-if codeOpen⟩     代码抽屉  右侧 w608/max90vw · 遮罩 z90 · 抽屉 z91
```

**三栏宽度速查：** 左 Agent `316px` / 右 Inspector `340px` / 底 dock `228px` / 折叠条统一 `32px`(侧) `30px`(底)。TOPBAR `44px`。

---

## 2. 每个面板/区块逐项规格

### P1 · TOPBAR (顶栏)
- 容器：`h44 · pad 0 14 · bg #201f1c · border-bottom 1px #302d29 · gap10 · z60`
- **台切换器**：容器 `bg #1a1916 · border #302d29 · radius8 · pad3 · gap2`；每项 `font11 · pad 3/9 · radius6`；非激活 `#a39a8a` hover→`bg #2a2723 / #e6e1d6`；激活(策略台) `bg #d97757 · color #1c1b19 · 700`。
- **版本按钮**：`bg #1a1916 · border #302d29 · #a39a8a · font11 · pad 4/9 · radius7`，hover border→`#4a463f`。
- **runtime 段控**：同台切换器外壳；按钮由 `runtimeBtns` 动态生成，激活态：live→`bg #d97066`，其余→`bg #6f9bd1`，激活文字 `#16202c · 700`，非激活 `#a39a8a · 400`，`font11 · pad 4/11 · radius6`。
- **校验按钮**：`bg #1a1916`，边框/文字色随 `errBorder/errColor` (见 §状态)；`font11.5 · pad 5/11 · radius7`。
- **运行按钮**：绿系 `bg #1e261a · border #3c5230 · #bcd98a`，hover→`#243420`。
- **编译源码按钮**：蓝系 `bg #161f2a · border #2c4452 · #9bc4ea`，hover→`#1b2735`。
- **发布按钮**：`transparent · border #302d29 · #a39a8a`，hover border→`#4a463f`。

### P2 · LEFT AGENT 面板 (w316)
- header `pad 9/13 · border-bottom #302d29`；mode 段控外壳 `bg #161512 · border #302d29 · radius7 · pad2`，按钮激活 `bg #d97757 · #1c1b19 · 700`，非激活 `#8f897c · 400`，`font10 · pad 3/8 · radius5`。
- modeHint：`pad 6/13 · border-bottom #262320 · font9.5 · #7d7668 · line1.6`。
- **对话块 4 类**(`agentBlocks`)：
  - `user`：`> ` (#d97757 700) + 文本 (#cfc8ba)，`margin 13/0/5`。
  - `think`：`✻`(#9b8d72) + 斜体文本 (#8a7e6a · font12)，`margin 9`。
  - `say`：`●`(#d97757) + 文本 (#e6e1d6)，`margin 8`。
  - `patch`：卡片 `border {{patchBorder}} · bg #201f1c · radius9 · pad 9/12`；头 `⟳ + 标题 + patchId pill`；"受影响 · …"；已撤销→`✓整轮已撤销`(#9bbd5a)，未撤销→`↺整轮撤销Patch`按钮(`bg #2a1d1b · border #523630 · #d99a8e`)。
- **Ghost 提议卡**(`hasProposal`)：`border 1px dashed #5a4a6a · bg #211c26 · radius9 · pad 10/12`；头`◇(#b89cd8) + 标题(#d8c9ec) + "Ghost · patchId" pill`；diff 行(`+`绿/`~`琥珀/`-`)；说明"↑画布上虚线即此提议的 Ghost 预览(影响 N 处)"；按钮`✓接受Patch`(紫系 `bg #2a2438 · border #6a5a8a · #d8c9ec`) + `拒绝`(透明)。
- **composer**：输入框 `border {{inputBorder}}(有内容#4a463f/空#302d29) · bg #211f1c · radius10 · pad 8/11`；`> ` 前缀 + textarea(`font12.5 · max-h90`) + ↵send(`bg #d97757 · #1c1b19 · 700`)；状态行`⏺sonnet-4.5 │ {{modeGlyph}}{{agentMode}} │ ⎇ strat/weekly-cn`。

### P3 · CENTER 工具条
- 缩放按钮 `ctrlBtn`：`bg #1a1916 · border #302d29 · #cfc8ba · 26×26 · radius6`；带文字按钮 `ctrlBtnW`：`#a39a8a · h26 · pad 0 9 · font10.5`。
- `MOCK 数据` pill：`#6f9bd1 · border #2c4452 · bg rgba(111,155,209,.1) · pad 2/8 · radius20`。

### P4 · CANVAS 画布面 (#sb-graph)
- **网格背景**：`radial-gradient(#2a2723 1px, transparent 1px)`，`size = 22*zoom px`，`position = panX,panY` (随平移/缩放联动)。
- **阶段框**(`stages`)：虚线 `1px dashed`，正常 `#34302a`，有缺口 `#5a4a2a`；`radius14 · bg rgba(255,255,255,0.012) · z0`；位置由该阶段成员节点包围盒 ±20px pad 算出；标题在框上方 `-26px`，"NN · 名"(有缺口→`#d9b25f`否则`#8f897c`) + "N节点·完成/有缺口" + 可选"N项待修复" pill。
- **节点卡**(`nodes`)：宽 `n.w` (168~184)，高由 `_nodeH` 动态算 (端口数与行数取大者)；`border 1.5px`(选中`#d97757`/血缘链路`#7a6a3a`/默认`#34302a`) · `bg #1d1c19 · radius9`；head `pad 5/9 · bg`(选中`#2a2723`/默认`#221f1c`)；head 内：7×7 圆角2 类别色点 + 标题(#e6e1d6 600 省略号) + 可选 diff badge + 可选 🔒(locked) + 6×6 state 圆点(running 加 `sbpulse` 动画)；body `pad 6/9 · gap2`：行(`font10 · #9a9488` 省略号) + 可选 badge(蓝 pill) + 可选`↗打开回测详情`(#6f9bd1)。
  - **ring/shadow**：选中 `0 0 0 3px rgba(217,119,87,0.2),0 8px22 rgba(0,0,0,.42)`；血缘链路上 `0 0 0 2.5px rgba(217,178,95,0.55)`；diff added `rgba(127,166,80,0.5)`；diff changed `rgba(217,178,95,0.5)`；默认 `0 4px14 rgba(0,0,0,.32)`。
  - **opacity 降焦**：trace 模式非链路节点 `0.3`；diff 模式非 diff 节点 `0.42`。
- **端口**：14×14 圆 · `border 1.5px` · 类别色；in 在 `left:-7px`，out 在 `right:-7px`，`top = 38 + i*20 px`；hover 时入口背景/边框变兼容性色。
- **连线**(svg path)：贝塞尔(两端水平切入)；stroke 由 `_edgeStroke(compat,sel)` → ok`#5d6f4c`/adapt`#3f6178`/warn`#8a6a2a`/bad`#8a3a30`/sel`#d97757`/血缘`#d9b25f`；width 1.8(普通)/2.6(选中)/3(血缘)；adapt 用 `dash 6 4`；末端 `marker #sbarrow`(▷ #6a6258)。
- **MiniMap**：`158×104 · bg rgba(22,21,18,0.82) · border #302d29 · radius8`；节点缩略块用类别色 opacity0.7；视口框 `border #d97757 · bg rgba(217,119,87,0.08)`。
- **兼容性图例 4 pill**：兼容`● #9bbd5a`/可适配`◐ #6f9bd1`/需转换`⚠ #d9b25f`/不兼容`✕ #d97066`，各自 `bg rgba(色,.12) · border 对应深色 · font9.5 · pad2/8 · radius20`。

### P5 · RIGHT INSPECTOR (w340)
- **选中态**：标题卡(类别色块 9×9 + 标题 font14 + category/state/MOCK pills + desc font11.5)；tab 段控(参数/端口/校验/版本血缘，激活 `bg #2a2723 · #e6e1d6`，非激活 `#7d7668`)。
  - **参数 tab**：每行 label(min-w108 · `#7d8aa0` · 带 `?` tip 圆点 `bg #6f9bd1`) + input(`bg #161512 · border #302d29 · #cfc8ba · radius6`，readonly/locked → disabled)。
  - **端口 tab**：输入端口卡(`bg #161512 · border #2a2723 · border-left 2px {required色#5a4a2a/optional#4a4a42} · radius7`：名 + 连接态(已连接#9bbd5a/可选#6f6a61/未连接#d9b25f) + meta) + 输出端口卡(border-left `#4a4a42`)。
  - **校验 tab**：无问题→`✓该节点校验通过`(#9bbd5a)；有→issue 卡(icon 色 + 文本)。
  - **版本/血缘 tab**：节点 ID + 血缘(#6f9bd1)；有贡献→回测贡献卡(`run_wk_cn_8f2a MOCK` + k/v 行) + `↗在回测详情中定位该节点`按钮。
- **无选中态**：`图校验·GraphValidationResult` 标题 + 大字 glyph(✕/⚠/✓) + headline/sub + issue 列表(可点定位) + 底部操作提示(连线/框选/Del/⌘Z)。

### P6 · BOTTOM WORKBENCH dock (h228)
- tab 条：`pad 6/12 · border-bottom · bg #1d1c19`；6 tab(`dockTabs`)激活 `bg #2a2723`，血缘溯源 tab 带长 tooltip；右侧 MOCK pill + ▾。
- 内容区 7 种互斥视图，详见 §4。

### P7 · 发布抽屉 (publishOpen, w392)
- 遮罩 `rgba(0,0,0,0.5) z90`；抽屉 `right0 · bg #1b1a17 · border-left #3a352e · shadow -16 0 40 · z91`。
- header `⇲ 发布·生命周期 + ✕`；body：`StrategyLifecycle` 9 步竖列(每步 14×14 圆点 dot/ring 色随进度 + label + 当前 pill) + `发布检查清单`(4 项卡) + `推进到 X →` 主按钮(`bg #d97757`)。

### P8 · 代码抽屉 (codeOpen, w608/max90vw)
- 遮罩 z90；抽屉 `bg #161512 · border-left #2c4452 · z91`。
- header `⟨/⟩编译·Graph→Source + "前端 codegen·不执行" pill + ✕`；pipeline 行(图→校验→序列化→Codegen→回测引擎)；可选错误横幅；tab(strategy.py / strategy.yaml)；代码区(行号 #3f3b35 + 语法高亮 segs)；底部说明。

---

## 3. 状态模型

### 3.1 `state` 字段 (源码 488-502 行，权威)

```ts
interface StrategyBoardState {
  // ── 图数据 ──
  nodes: Record<NodeId, NodeInstance>;   // 节点字典 (初始 16 个)
  edges: Edge[];                          // 连线数组 (初始 19 条)
  sel: { nodeIds: NodeId[]; edgeIds: EdgeId[] };  // 选中态

  // ── 视口 (不进 Undo) ──
  panX: number;   // 初始 44
  panY: number;   // 初始 70
  zoom: number;   // 初始 0.72，范围 [0.22, 2.2]

  // ── 临时手势态 ──
  marquee: { x; y; w; h } | null;        // 框选矩形 (屏幕坐标)
  linking: { node; port; ax; ay } | null;// 正在拉的连线 (起点世界坐标)
  linkPx: number; linkPy: number;        // 拉线终点 (世界坐标)
  hoverPort: { node; port; s; reason } | null;  // 悬停入口 + 兼容性

  // ── Undo/Redo ──
  undoStack: Snapshot[];  // 最多 60 步，每步 {nodes,edges} 深拷贝
  redoStack: Snapshot[];

  // ── 模式/运行态 ──
  agentMode: 'ask' | 'auto' | 'bypass';  // 初始 'ask'
  runtime: 'backtest' | 'paper' | 'live';// 初始 'backtest'；live→只读

  // ── 面板开合 ──
  leftOpen: boolean;   // true  (Agent)
  rightOpen: boolean;  // true  (Inspector)
  dockOpen: boolean;   // false (工作台)
  inspTab: 'params'|'ports'|'validate'|'version';  // 初始 'params'
  dockTab: 'preview'|'schema'|'stats'|'logs'|'history'|'lineage'; // 初始 'preview'

  // ── Agent ──
  draft: string;                 // 输入框
  agentBlocks: AgentBlock[];     // 对话流 (user/think/say/patch)
  proposal: AgentProposal | null;// 待接受的 Ask 提议

  // ── 运行/回测 (mock) ──
  running: boolean;
  runLog: { t; c; m }[];         // 日志行 (时间/色/消息)

  // ── 治理/版本 ──
  trace: Trade | null;           // 当前高亮血缘的成交
  verMenuOpen: boolean;
  diffBase: VersionId | null;    // diff 基线 (null=未对比)
  publishOpen: boolean;
  killArmed: boolean;            // 初始 true (Kill Switch)
  codeOpen: boolean;
  codeTab: 'py' | 'yaml';        // 初始 'py'
  lifecycle: StrategyLifecycle;  // 初始 'Backtested'
  ver: string;                   // 初始 'v3 草稿'
}
```

### 3.2 实例字段 (非 state，挂在 `this._*`，`_build()` 构造一次)

```ts
this._trades: Trade[]          // 3 笔 mock 成交 (tx_001..003)，每笔含 path:NodeId[]
this._runs: Run[]              // 3 条 mock 运行历史 (run_wk_cn_8f2a/7d10/6a02)
this._versions: Version[]      // 3 个版本 (v3当前/v2/v1)
this._diff: { base:'v2', added:['signal'], changed:['model','optim'] }
this._contribution: Record<NodeId, [k,v,color][]>  // 5 节点的回测贡献
this._varProposal: AgentProposal  // Ask 默认提议 (pt_4f1a: 加 VaR/CVaR + 降换手)
```

### 3.3 推断的领域类型 (来自 `_build` 节点字面量 + 蓝本 §10)

```ts
type NodeId = string; type EdgeId = string;
type NodeCat = 'research'|'scope'|'data'|'factor'|'model'|'signal'|'position'|'risk'|'exec'|'eval';
type StageKey = 's1'|'s2'|'s3'|'s4'|'s5'|'s6'|'s7'|'s8';
type NodeState = 'idle'|'dirty'|'validating'|'valid'|'queued'|'running'|'succeeded'|'warning'|'invalid'|'failed'|'stale';
type Compat = 'ok'|'adapt'|'warn'|'bad'|'?';   // 连线 5 态 (蓝本里 5 态含 '?待后端校验')

interface Port {        // _build 里的 P() 工厂产物
  id: string; name: string; dt: string /*dataType*/;
  freq: string;  /* 'D'日 | 'W'周 | '—' | '' */
  scope: string; req: boolean; role: string; /* 'exec' 触发 Final Gate 规则 */
  schema: string;
}
interface NodeInstance {
  id: NodeId; cat: NodeCat; stage: StageKey; title: string;
  x: number; y: number; w: number;
  state: NodeState; desc: string;
  params: Record<string, string>;     // 注意：原型里值全是 string
  ins: Port[]; outs: Port[];
  lines: string[];                    // 卡片正文行
  lineage: string;                    // 血缘 id
  badge?: string;                     // '← 因子台' / '← Model台'
  mock?: boolean; locked?: boolean;   // locked 仅 gate=true
  openRun?: boolean;                  // 仅 backtest=true
}
interface Edge { id; from:{node;port}; to:{node;port}; compat:Compat }
interface Trade { id; symbol; side:'买入'|'卖出'; qty; px; when; weight; pnl; ret; path:NodeId[] }
interface Run { id; when; excess; dd; sharpe; status:'succeeded'|'warning'; cur?:boolean }
interface AgentBlock { type:'user'|'think'|'say'|'patch'; text?; patchId?; affected?; reverted? }
interface AgentProposal { patchId; title; diff:[sign,text,color][]; ops:GhostOp[] }
type GhostOp = {op:'addNode';node} | {op:'addEdge';edge} | {op:'setParam';node;k;v};
```

### 3.4 完整 `{{ }}` 绑定清单 (按区域，全部来自 `renderVals()` return)

**TOPBAR/版本**：`versionLabel · verToggle · verMenuOpen · versionRows[{dot,label,lifecycle,diff,rollback}] · cloneVer · branchVer · runtimeBtns[{label,on,style}] · undo/redo · undoStyle/redoStyle · validate · errLabel/errColor/errBorder · runLabel/runClick · openCode/closeCode · openPublish`

**治理 (live)**：`liveGov(=readonly) · fork · kill · killArmed · killLabel · killStyle`

**LEFT Agent**：`leftOpen/leftCollapsed/leftToggle · ctxLabel · agentBlocks[{isUser,isThink,isSay,isPatch,text,patchId,affected,reverted,notReverted,patchBorder,patchIcon2,undo}] · modeHint · modeBtns[] · agentMode · modeColor/modeGlyph · hasProposal · proposal{title,patchId,affectedCount,diff[{sign,t,c}]} · acceptProposal/rejectProposal · composerPh · draft/onDraft/onKey/send · inputBorder`

**CANVAS**：`zoomPct · zoomIn/zoomOut/fit/autoLayout · ctrlBtn/ctrlBtnW · canvasHint · surfCursor · gridStyle · bgDown · panX/panY/zoom · marqueeOn/marquee · diffOn/diffLabel/diffAdded/diffChanged/exitDiff · traceOn/traceLabel/traceCount/clearTrace · stages[{idx,title,titleColor,compLabel,hasMissing,missingText,frameStyle}] · nodes[{id,w,locked,title,dotColor,headBg,border,stateColor,stateLabel,statePulse,lines,badge,diffBadge,diffColor,openRun,openRunClick,inPorts[],outPorts[],wrapStyle,cardStyle,badgeStyle,headDown,select}] · edges[{path,stroke,width,dash,opacity,click}] · ghostNodes[{wrapStyle,title,lines}] · ghostEdges[{path}] · linkOn/linkPath/linkColor · miniNodes[{style}]/miniViewStyle · selCountLabel`

**RIGHT Inspector**：`rightOpen/rightCollapsed/rightToggle · inspTitle · hasSel/noSel · insp{id,title,category,catColor,stateColor,stateLabel,mock,desc,lineage,noParams,params[{label,tip,hasTip,v,disabled,onInput}],ins[{name,conn,connColor,req,meta}],outs[{name,meta}],noIssues,issues[{icon,c,t}],hasContribution,contribution[{k,v,color}],openRun} · inspTabs[] · inspParamsTab/inspPortsTab/inspValidTab/inspVerTab · gv{color,glyph,headline,sub,issues[{icon,c,t,loc,go}]}`

**DOCK**：`dockOpen/dockCollapsed/dockToggle · dockTabs[{label,tip,on,style}] · dockEmpty/dockEmptyText · dockPreview/dockSchema/dockStats/dockLogs/dockHistory/dockLineage · dockNodeTitle · dockCols/dockCells[{t,style}] · dockSchemaText · dockStatRows[{k,v,color}] · logLines[{t,c,m}]/logsEmpty · runCells[{t,style}] · tradesShown/tradeRows[{...,go,rowBg,rowBorder}]/tradeCount · trace{label,meta,runHref,chain[{title,color,arrow,go}]} · runDetail{runId,excess,dd,sharpe,pbodsr,freq,window,trades,href}`

**发布/代码**：`publishOpen/closePublish · lifecycleSteps[{label,current,dot,ring,color,weight}] · checklist[{icon,color,t}] · advance/advanceLabel · codeOpen/codeTab/codeTabs[] · codeLines[{n,segs[{c,t}]}] · codeFile · pipeline[{label,color,arrow}] · codeErr/codeErrCount`

---

## 4. 交互清单 (所有 onClick/handler → 行为推断)

| Handler | 触发位置 | 行为 |
|---|---|---|
| `verToggle` | 版本▾ / popover✕ | 切换 `verMenuOpen` |
| `runtimeBtns[].on` | Backtest/Paper/Live 段控 | 设 `runtime`，清选中。live→全局只读+顶栏出现 Fork/Kill |
| `validate` | ✓校验 | 清选中 + 开右栏 (展示图校验概览，**不重新计算**——校验是渲染时实时跑的) |
| `runClick`→`_runGraph` | ▷运行回测 | 若未在跑：17 节点全置 queued→流式 setTimeout 逐节点 running→succeeded，日志流式，开 dock 切 logs；末尾落"✓完成·超额17.3%…"。全 mock |
| `openCode`/`closeCode` | ⟨/⟩编译源码 | 开/关代码抽屉。打开时 `_genPyLines`/`_genYamlLines` 实时从当前图重新生成源码 |
| `openPublish`/`closePublish` | 发布▸ | 开/关发布抽屉 |
| `undo`/`redo` (⌘Z/⌘⇧Z) | 顶栏 + 键盘 | 从 undo/redo 栈恢复 {nodes,edges} 快照，清选中 |
| `verToggle`→`versionRows[].diff`→`_enterDiff` | popover「对比」 | 设 `diffBase=v2`，画布进入 diff overlay (added 绿/changed 琥珀，余降焦) |
| `versionRows[].rollback`→`_rollback` | popover「回滚」 | 改 `ver` 标签 + Agent 流追加 mock 说明 |
| `cloneVer`/`branchVer` | popover 底部 | 调 `_rollback` mock (改 ver 为 "v3 clone/branch") |
| `exitDiff` | diff banner「退出对比」 | `diffBase=null` |
| `leftToggle`/`rightToggle`/`dockToggle` | 折叠条/箭头 | 切对应面板开合 |
| `modeBtns[].on` | Ask/Auto/Bypass | 设 `agentMode` |
| `send`/`onKey(Enter)`→`_sendAgent` | composer | 追加 user 块；ask→重新挂 proposal+say；auto/bypass→`_applyAuto` 直接加节点 |
| `acceptProposal`→`_acceptProposal` | Ghost 卡「接受」 | 入 undo 栈→应用 ops(addNode/addEdge/setParam)→清 proposal→追加 patch 块 |
| `rejectProposal`→`_rejectProposal` | Ghost 卡「拒绝」 | 清 proposal + 追加 say |
| `agentBlocks[].undo`→`_revertPatch` | patch 卡「整轮撤销」 | `_undo()` + 把该 patch 块标 reverted |
| `zoomIn/zoomOut`→`_zoomBy` | ＋/− | 以画布中心为锚 ×1.15 / ÷1.15，clamp [0.22,2.2] |
| `fit`→`_fit` | 适应 | 计算所有节点包围盒，缩放平移使其居中 (max zoom 1.4) |
| `autoLayout`→`_autoLayout` | ⧉自动布局 | 入 undo 栈，按 stage 分 8 列(bandW236)重排，30ms 后 fit |
| `bgDown`→`_bgDown` | 画布空白 pointerdown | Shift→框选 marquee；否则→平移 pan，清选中+关版本菜单 |
| `nodes[].headDown`→`_nodeDown` | 节点头 pointerdown | 选中(支持多选保持)；live 下 return 不可拖；否则进 node 拖拽，存快照 |
| `nodes[].select` | 节点 click | 单选该节点 + 开右栏 |
| `nodes[].openRunClick`/`insp.openRun`→`_openRunDetail` | ↗打开回测详情 | `location.href = 回测详情.dc.html?from=node:backtest` |
| `outPorts[].down`→`_portDown` | 出口 pointerdown | live 下 return；否则进 link 拖拽，记起点世界坐标 |
| `inPorts[].enter/leave`→`_portEnter/_portLeave` | 入口 hover | link 中实时算 `_compat` 设 hoverPort 兼容性着色 |
| (全局 pointerup)`_onUp` | 松手 | node→若移动则入栈；link→若 hoverPort 非 bad 且目标口未占用则建边；marquee→选中框内节点 |
| (全局 wheel)`_onWheel` | 滚轮 | 以光标为锚缩放 ×1.12 / ÷1.12 |
| (全局 keydown)`_onKeyDown` | Del/Backspace | `_delSel` 删选中节点/边 (locked 节点跳过) |
| `edges[].click`→`_selectEdge` | 连线 click | 选中该边 |
| `inspTabs[].on` | 参数/端口/校验/版本 | 设 `inspTab` |
| `params[].onInput`→`_setParam` | 参数 input | 入栈 + 改 param + 非 succeeded 节点置 dirty |
| `gv.issues[].go`/`trace.chain[].go`/`insp...`→`_select` | issue/链路节点 click | 选中并定位该节点 |
| `dockTabs[].on` | dock 6 tab | 设 `dockTab` |
| `tradeRows[].go`→`_setTrace` | 成交行 click | 选中该笔→开 dock 切 lineage→画布高亮其 path 链路 |
| `clearTrace`/`exitDiff` | 清除高亮 | `trace=null` |
| `fork`→`_fork` | ⑂Fork草稿 | runtime→backtest，ver→"v4 草稿(fork)"，追加 say (B7 Fork) |
| `kill`→`_toggleKill` | Kill Switch | 切 `killArmed` |
| `advance`→`_advance` | 发布抽屉「推进」 | lifecycle 沿 9 步序列 +1 |
| `codeTabs[].on` | py/yaml | 设 `codeTab`，重新生成对应源码 |

**dock 内容区 7 互斥视图**：`preview`(节点输出 mock fixture 表格，PREVIEW 只有 factors/model/signal/backtest 有) · `schema`(节点端口 schema 文本) · `stats`(节点 mock 统计 或 图整体节点/连线/错误/警告数) · `logs`(运行日志流) · `history`(3 条 run 表格) · `lineage`(回测概览 6 卡 + 成交明细表 + 选中时血缘链路条) · 空态引导。

---

## 5. 治理元素专章

| 治理 UI | 触发条件 | 状态机 / 行为 | 关键不变量 |
|---|---|---|---|
| **Live 只读锁** | `runtime === 'live'` → `readonly=true` | 顶栏出现 `🔒 Live 只读` pill；`_nodeDown`/`_portDown` 直接 return (不可拖节点/拉线)；Inspector 参数 input 全 `disabled`；节点卡 cursor→default | B7：已发布 Live 只读 |
| **Fork 草稿** | 仅 live 下顶栏 `⑂ Fork 草稿` | `_fork`：runtime→backtest，ver→"v4 草稿(fork)"，Agent 流追加说明 | B7：编辑触发 Fork 新草稿 |
| **Kill Switch** | 仅 live 下顶栏 | `_toggleKill` 切 `killArmed`；label `● ARMED`(armed: bg#2a1d1b/border#8a4d3a/#e6a08e) ↔ `○ OFF`(bg#1a1916/灰)。初始 armed=true。Final Gate 节点参数也显示 `kill_switch: armed` | 紧急停机开关 |
| **Final Risk Gate** | `gate` 节点 `locked:true` | 头部 🔒；`_delSel` 跳过 locked 节点 (不可删)；`_validateGraph`：若 exec 有入边但无一来自 gate → `error: 违反 B6`；`_compat`：入口 `role==='exec'` 且来源非 `approvedPortfolio` → `bad: 执行入口必须经 Final Risk Gate` (连线被拒) | **B6：不可删除/不可绕过**，三层强制(删除门/校验门/连线门) |
| **Validate / 图校验** | 渲染时实时跑 `_validateGraph` | 规则：①必填 in 端口未连→warn ②exec 未经 gate→error ③compat=bad→error。`ok = error数===0`。结果驱动顶栏 errLabel、Inspector 校验 tab、无选中图校验概览、阶段框缺口标记、dock stats | 校验常驻 (非 Toast)，可点定位 |
| **版本切换** | 顶栏版本▾ → popover | `_pickVersion`(改 ver)；3 版本 v3当前(橙点)/v2/v1；每版可「对比」(`_enterDiff`)「回滚」(`_rollback`)；底部 Clone/Branch | GraphVersion |
| **Diff 对比** | popover「对比」→`diffBase=v2` | 画布顶 diff banner(+1新增/~2改动)；added(signal)绿环、changed(model,optim)琥珀环、余 opacity0.5；`exitDiff` 退出 | 只读双图 overlay (蓝本路由 /diff/:baseVid) |
| **Runtime 切换** | 顶栏段控 [Backtest|Paper|Live] | `runtimeBtns[].on` 设 runtime + 清选中。live→readonly+治理 UI 出现。backtest/paper 蓝激活，live 红激活 | 同一张图表达三态 (B7) |
| **血缘/谱系 (Lineage)** | 成交行 click `_setTrace` 或 deep-link `?trace=` | 画布顶血缘 banner + path 链路节点琥珀高亮(非链路 opacity0.3)、链路边琥珀加粗；dock lineage tab 显示链路条(交易←信号←节点逐级) + `↗回测详情定位`；每节点有 `lineage` id 作跨主题锚点 | 回测对象始终是整条图(run_id 级)，选成交只高亮不改回测对象 |
| **发布生命周期** | 发布▸ 抽屉 `_advance` | 9 步序列 `Draft→Validated→Backtested→Reviewed→Approved→Paper→Live→Paused→Retired`；当前 `Backtested`(state.lifecycle)；推进到 Live 后按钮变"已上线(Live 只读)"；checklist 部分项随 curI≥3/≥4 点亮 | B8：发布审批；Bypass 不绕过 |
| **Agent 权限三态** | Ask/Auto/Bypass 段控 | **Ask**：先出 proposal(Ghost 虚线预览)，用户 accept/reject/refine；**Auto**：`_applyAuto` 直接改草稿(事务化，加 DrawdownGuard 节点)，对话里可整轮撤销；**Bypass**：同 Auto，可跨节点批量 | B8：Auto/Bypass 必须事务化+整轮 Undo+Patch ID+快照；不绕过 Final Gate/发布审批 |

**deep-link 支持** (`componentDidMount`)：`?trace=tx_001` → 250ms 后 `_setTrace`；`?node=exec` → `_select`。对接回测详情页双向跳转。

---

## 6. 策略台 vs 策略台蓝本 — 差异

**两者不是繁简/模板关系，而是「实现 vs 规格」两类不同文档：**

| 维度 | 策略台.dc.html (主) | 策略台蓝本.dc.html |
|---|---|---|
| 性质 | **可交互的 P0 画布原型** (功能实现) | **静态架构规格文档** (滚动文章 + TOC) |
| 体量 | 1250 行 / 133KB | 341 行 / 44KB |
| 布局 | 四区工作台 (顶/左/中/右/底) | 左 TOC(232px) + 右文档正文(max-w920) |
| 交互 | 全功能：拖拽/连线/缩放/Undo/Agent/回测/血缘/发布 | 仅锚点跳转 + hover 高亮，无业务逻辑 |
| `<script>` | 完整 `Component` 类 (state+geometry+compat+codegen+renderVals) | 仅 `$preview` props，无逻辑 |
| 节点数 | **16 节点 + 19 连线** 实装 | 文字描述 8 大类 Registry |
| 内容 | 把规格变成可点的东西 | 13 章：现状审查/约束 B1-B9/路由/IA四区/组件树/Node Registry/状态机/画布状态模型/Agent Patch 状态机/TS Contract/状态矩阵/后端接口/P0-P2 落地 |
| 角色 | 给设计还原/实装直接抄的视觉与交互真值 | 给工程落地 React 的契约真值 (类型/Repository/路由/边界) |
| 互链 | 顶栏 `蓝本↗` → 蓝本 | 顶栏 `→ 打开 P0 画布原型` → 主原型 |

**蓝本独有、主原型未实装但需落地的内容**(实装方案应补)：8 大类完整 Node Registry (主原型只用了其中 16 个) · 端口 9 维类型系统 · 完整节点状态机(含 stale 斜纹/cancelled) · 画布状态分桶(勿合并单一 store) · GhostOp 7 种(主原型只实现 addNode/addEdge/setParam) · 完整 Screen Map 路由 · Repository/Adapter 接口清单 + REST 端点 · 页面状态矩阵(Empty/Loading/Error/Readonly 四态 × 4 区) · `contractVersion: strategy-graph@0.1.0`。

**B1-B9 约束**(蓝本 §02，实装须编码为校验规则而非文案)：B1 市场组合∩标的池 · B2 标的池不含权重 · B3 Model 只引用不训练 · B4 因子可直接产信号 · B5 Model 输出强制过 PositionValidation→PortfolioRisk→FinalRiskGate→Execution · **B6 Final Risk Gate 不可删/绕** · B7 Live 只读+Fork · B8 Ask 先 Ghost / Auto·Bypass 事务化 · B9 Mock 必须标 MOCK 角标。

---

## 7. Design Tokens 汇总 (pixel-perfect 依据)

### 7.1 色板 (hex → 语义)

**底色/中性 (warm charcoal)**
| hex | 语义 |
|---|---|
| `#1c1b19` | app 根背景 / 选中按钮文字 |
| `#191815` | 画布面背景 |
| `#1a1916` | dock 背景 / 按钮底 / 代码抽屉底 |
| `#1b1a17` | 左右面板底 / 抽屉底 |
| `#1d1c19` | 节点卡底 / 工具条底 / 折叠条底 / 卡片底 |
| `#1d1c19`→head `#221f1c` | 节点 head 默认底 |
| `#201f1c` / `#211f1c` | 顶栏底 / composer 底 / patch 卡底 / 版本 popover 底 |
| `#161512` | input 底 / 端口底 / 代码抽屉底 / pre 代码块底 |
| `#2a2723` | hover 底 / 选中 head 底 / 激活 tab 底 |
| `#262320` | 分隔/hover |
| `#302d29` | 主边框线 |
| `#34302a` | 节点默认边 / 阶段框正常边 |
| `#3a3733` | 次边框 / 滚动条 thumb / 禁用 |
| `#4a463f` | hover 边 / 有内容 input 边 |
| `#3f3b35` | 代码行号 / pipeline 箭头 |

**文字色**
| hex | 语义 |
|---|---|
| `#e6e1d6` | 主文字 |
| `#cfc8ba` | 次强文字 / 值 |
| `#a39a8a` | 三级文字 / 段落 |
| `#9a9488` | 节点行文字 |
| `#8f897c` | 弱文字 / 标签 |
| `#7d7668` / `#7d8aa0` | 更弱 / 表头蓝灰 |
| `#6f6a61` | 占位 / 提示 |
| `#5f5b53` / `#5f6a52` | 最弱 / 代码注释绿灰 |

**品牌/语义强调**
| hex | 语义 |
|---|---|
| `#d97757` | **主橙 (品牌)** — logo/激活/Run箭头/选中边/主按钮 |
| `#9bbd5a` | 绿 — valid/succeeded/兼容/正收益/通过 |
| `#6f9bd1` | 蓝 — research/scope/eval/可适配/MOCK/info |
| `#d9b25f` | 琥珀 — dirty/warning/需转换/血缘高亮/Live只读 |
| `#d97066` | 红 — risk类/invalid/failed/不兼容/Live按钮 |
| `#b89cd8` | 紫 — model类/Ghost 提议 |
| `#c89b6f` / `#c98a6f` | 棕 — data类 / Python 关键字高亮 |
| `#6fb0a0` | 青 — position类 |
| `#9bc4ea` | 亮蓝 — 编译源码按钮 / codegen |
| `#d99a8e` / `#d9c4a0` / `#e6a08e` | 暖红/暖黄/橙红 — 负收益/警告文/Kill armed |
| `#bcd98a` | 浅绿 — Run 按钮文字 |
| `#cbb89a` | 代码正文 |

**节点类别色 CAT** (1041 行)：research/scope/eval→`#6f9bd1` · data→`#c89b6f` · factor→`#9bbd5a` · model→`#b89cd8` · signal→`#d9b25f` · position→`#6fb0a0` · risk→`#d97066` · exec→`#d97757`

**兼容性色** (`_compatColor`)：ok`#9bbd5a` · adapt`#6f9bd1` · warn`#d9b25f` · bad`#d97066` · ?`#8f897c`
**连线 stroke** (`_edgeStroke`)：ok`#5d6f4c` · adapt`#3f6178` · warn`#8a6a2a` · bad`#8a3a30` · ?`#4a463f` · sel`#d97757` · 血缘`#d9b25f`
**state 色 STATE** (1001 行)：idle`#6f6a61` · dirty/warning`#d9b25f` · validating/queued`#6f9bd1` · valid/succeeded`#9bbd5a` · running`#d97757` · invalid/failed`#d97066` · stale`#8f897c`

**按钮配色族** (背景/边框/文字三元组)：
- 绿系(运行/Fork)：`#1e261a / #3c5230 / #bcd98a`，hover bg `#243420`
- 蓝系(编译)：`#161f2a / #2c4452 / #9bc4ea`，hover bg `#1b2735`
- 紫系(接受 Patch)：`#2a2438 / #6a5a8a / #d8c9ec`，hover bg `#332a45`
- 红系(撤销/Kill armed)：`#2a1d1b / #523630 / #d99a8e`
- 中性默认：`#1a1916 / #302d29 / #a39a8a`

**带 alpha 的语义底色** (pill/环)：兼容性 pill `rgba(色,.12)`；MOCK `rgba(111,155,209,.1)`；选中环 `rgba(217,119,87,0.2)`；血缘环 `rgba(217,178,95,0.55)`；diff added 环 `rgba(127,166,80,0.5)`；selection `rgba(217,119,87,0.28)`；阶段框 `rgba(255,255,255,0.012)`；MiniMap 底 `rgba(22,21,18,0.82)`；遮罩 `rgba(0,0,0,0.5)`。

### 7.2 字体
- family：`"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace` (全局唯一等宽字体)，weights 400/500/600/700。
- `font-variant-numeric: tabular-nums` 用于所有数值列 (成交价/盈亏/指标)。

### 7.3 字号阶 (px)
`8.5`(Ghost pill) · `9`(diff badge / 极小标签) · `9.5`(meta/图例/血缘说明) · `10`(节点行/上下文标签) · `10.5`(日志/表格/代码) · `11`(段落/端口/pill/issue) · `11.5`(按钮/desc/正文) · `12`(对话/think) · `12.5`(textarea/面板标题) · `13`(根基准) · `13`(缩放±/undo redo 图标) · `14`(Inspector 标题/dock 统计大数) · `15`(血缘概览数值) · `17`(蓝本 h2) · `22`(图校验大 glyph) · `24`(蓝本主标题)

### 7.4 间距阶
- gap：`2`(段控内) · `6 · 7 · 8 · 9 · 10 · 11`(主)
- padding：`pad 0 14`(顶栏) · `3/9`(台切换项) · `4/9~4/11`(段控按钮) · `5/9`(节点 head) · `5/11`(tab) · `6/9`(节点 body) · `6/13`(modeHint) · `7/9`(端口卡) · `8/11`(成交行/卡片) · `8/12`(校验卡) · `9/12~9/13`(约束卡) · `10/12~10/13`(Ghost卡) · `12/14`(Inspector 标题卡) · `13/16`(抽屉 header) · `14`(抽屉 body) · `16/14`(蓝本 TOC) · `28/40`(蓝本正文)
- 端口锚点步长：`20px` (port top = 38 + i*20)
- 自动布局：bandW `236` · baseX `40` · 行距 `150`

### 7.5 圆角阶 (px)
`1`(MiniMap 节点) · `2`(类别色点) · `5`(mode 按钮) · `6`(滚动条/小按钮/缩放) · `7`(段控按钮/主按钮/端口卡/issue卡) · `8`(台切换器外壳/卡片/dock按钮/抽屉主按钮) · `9`(节点卡/patch卡/Ghost卡/banner/代码块) · `10`(composer) · `11`(版本 popover) · `14`(阶段框) · `20`(pill 胶囊)

### 7.6 阴影
- 节点默认：`0 4px 14px rgba(0,0,0,0.32)`
- 节点选中：`0 0 0 3px rgba(217,119,87,0.2), 0 8px 22px rgba(0,0,0,0.42)`
- 血缘高亮节点：`0 0 0 2.5px rgba(217,178,95,0.55), 0 6px 18px rgba(0,0,0,0.4)`
- diff added/changed 环：`0 0 0 2.5px rgba(127,166,80,0.5)` / `rgba(217,178,95,0.5)`
- Ghost 节点：`0 0 0 3px rgba(184,156,216,0.12)`
- 版本 popover：`0 16px 40px rgba(0,0,0,0.5)`
- 抽屉(左展开)：`-16px 0 40px rgba(0,0,0,0.4~0.45)`

### 7.7 动画 keyframes (helmet 定义)
- `sbpulse`：`0%,100%{opacity:1} 50%{opacity:0.35}` — 用于 running 状态点 (`animation:sbpulse 1s ease-in-out infinite`)
- `sbring`：`0%{box-shadow:0 0 0 0 rgba(217,119,87,0.45)} 100%{box-shadow:0 0 0 7px rgba(217,119,87,0)}` — 定义但**未在模板中引用** (预留脉冲环)
- `sbdash`：`to{stroke-dashoffset:-16}` — 定义但**未在模板中引用** (预留流动虚线)
- 缩放因子：滚轮 `1.12`，按钮 `1.15`，zoom clamp `[0.22, 2.2]`

### 7.8 SVG 标记
- `#sbarrow`：`markerWidth/Height 9 · refX7 refY3 · path M0,0 L7,3 L0,6 Z · fill #6a6258`
- 连线路径 `_path(a,b)`：`dx = max(40, |bx-ax|*0.42)`，`M ax,ay C ax+dx,ay bx-dx,by bx,by` (两端水平切入贝塞尔)
- Ghost 连线：`stroke #b89cd8 · width2 · dash "6 5" · opacity0.8`

---

## 实装关键提醒 (给主控 agent)

1. **校验是渲染期实时计算** (`_validateGraph` 在 `renderVals` 内每次跑)，非缓存——React 实装应转为 derived/memoized selector。
2. **治理三态门是硬编码强制** (删除门/校验门/连线门各一处)，B6 不能只靠文案。
3. **codegen 双向** (`_genYaml/_genPy` 从当前图实时反编译)——"改图即改码"，py 还带正则语法高亮 `_tokPy/_tokYaml`。
4. **坐标系**：节点存世界坐标，`#sb-pan` 用 `translate(panX,panY) scale(zoom)`；屏幕↔世界换算 `_s2w`；端口锚点 `_anchorIn/Out`，连线/框选/MiniMap 全依赖此几何。
5. **3 个 keyframes 中 2 个 (sbring/sbdash) 已定义未用**——还原时可补上脉冲环/流动虚线提升质感，或保持现状。
6. 主原型只实装 16 节点子集 + 3 GhostOp；完整 Registry/状态机/GhostOp/路由/Repository 在蓝本，落地需按蓝本 §05-§13 补齐。

文件路径：`/tmp/qbt-handoff/quantbt-claude/project/策略台.dc.html`、`/tmp/qbt-handoff/quantbt-claude/project/策略台蓝本.dc.html`。