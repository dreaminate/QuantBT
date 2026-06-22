I now have a complete picture. I've read the full 570-line design spec, all four task cards, both existing frontend pages, the backend register_tool block, the agent runtime permission gate, the tool schema names, and the D-PERM decision. Here is my structured report.

---

# QuantBT Agent 窗口设计稿解析 + 四卡吻合度审计

## 0. 审计框架（大→小→细，先立后挑）

设计稿 `QuantBT Agent.dc.html`（570 行）是「**策略台**」的 agent 客户端窗口，仿 Claude Code：左对话流 + 右产物工作区 + 顶栏权限/治理。它不是通用 agent 窗口，而是**策略台专属**（组装+回测，止于交接模拟台）。审计四卡是否覆盖、是否守住 D-PERM，结论先行：**四卡 scope 整体方向吻合，但设计稿信息量远超四卡描述，存在约 8 个 T-040 未列明的结构性新元素需补卡或显式扩 scope**（详见 §5 / §7）。

---

## ① 整体布局骨架（区域树 + 尺寸）

```
x-dc (height:100vh, bg #1c1b19, color #e6e1d6, font 13.5px/1.5, JetBrains Mono)
└─ flex column
   ├─ ① TITLE BAR + 台 SWITCHER          flex:none h=42px  bg #201f1c  border-bottom #302d29
   │    · 三个 macOS 红绿灯圆点(11px, #3a3733 灰——非功能装饰)
   │    · ✳ logo(#d97757) + "QuantBT"(600)
   │    · 台 switcher pill 组(因子台敬请/Model台链接/策略台 active/模拟台敬请)
   │    · spacer → ~/strategies/weekly-cn 路径(#5f5b53 11px) + ↻重放按钮
   ├─ ② MILESTONE LADDER (进度线)         flex:none  bg #1a1916  padding 8/18/9
   │    · 顶行: "策略台 · 组装 + 回测" ↔ "终点：候选策略 → 交接模拟台" (9.5px #5f5b53)
   │    · 7 节点横线: 立题→市场→因子集→模型→信号→风控→回测
   │      (dot: active 11px #d97757+ccring脉冲 / reached 9px #7fa650 / 未达 9px 空心边框)
   │      (连接线: 已过 #5d7a3a / 未过 #302d29)
   └─ ③ BODY                              flex:1 min-h:0  flex row
       ├─ LEFT · CHAT  (可折叠)
       │    展开: width = chatW(默认440, 拖拽 280~760); wsClose 时 flex:1
       │    折叠: width 32px 竖条 "对话 ›"
       │    ├─ #cc-scroll  flex:1 overflow-y:auto  padding 8/18
       │    │    └─ blocks[] 渲染(7 种 block 类型, 见 ③状态模型)
       │    │    └─ busy 行(✻ + busyWord + secs/tokens/esc)
       │    └─ INPUT + STATUS  flex:none  border-top #302d29  bg #1c1b19
       │         · slash 命令面板(/ 触发, 6 条)
       │         · 输入框(> prompt + textarea + 发送按钮 #d97757)
       │         · 状态行: ⏺model │ permGlyph permMode │ ctx 进度条 │ ⎇branch
       ├─ SPLITTER  width 5px  cursor col-resize  hover→#d97757  (仅 chat+ws 同开时)
       └─ RIGHT · WORKSPACE (产物工作区, 可折叠)
            展开: flex:1 min-w:0  bg #191815
            折叠: width 34px 竖条 "‹ 产物工作区"
            ├─ tab 栏  flex:none  padding 7/14  bg #1d1c19
            │    [◳产物] [⌨ Strategy.yaml] [▤ Report.md(reportReady 才出)] + hint + ›收起
            └─ 内容区  flex:1 overflow-y:auto  padding 18/20
                 · COWORK (max-w 620 居中): 8 张产物卡 + RunVerdictCard(dc-import)
                 · CODE (max-w 640): strategy yaml 行号高亮
                 · REPORT (max-w 620): markdown 渲染
```

预览尺寸 `$preview: 1280×880`。两栏均可独立折叠；splitter 仅双开时出现。

---

## ② 每个面板/区块职责 + 关键视觉

### A. Title bar（L29-45）
- **台 switcher**（核心治理元素）：4 个台分三态——`active`(策略台, bg #d97757/字#1c1b19/700)、`link`(Model台, 可跳转)、`plain+soon`(因子台/模拟台, #6f6a61 + "敬请"灰胶囊)。pill 组容器 bg #1a1916 / border #302d29 / radius 8 / padding 3。字号 11.5px / radius 6 / padding 4-11。
- **↻ 重放**：透明底 + border #302d29，hover border #4a463f。

### B. Milestone ladder（L48-66）— **这是设计稿独有的强结构，四卡未提**
- 7 节点：立题/市场/因子集/模型/信号/风控/回测。每节点 `flex:1`，上方连接线 + dot + label + sub。
- dot 三态见骨架。label 色：active #d97757 / reached #cfc8ba / 未达 #5f5b53。
- sub 动态：因子集→`fs_core3`、模型→`v2·staging`、回测→`拍板✓`。
- 点击节点 = `_gotoMs` 跳回该里程碑的 cowork 产物 + 滚动定位对话锚点。

### C. Chat blocks（7 种, L80-158）
| block | 视觉 |
|---|---|
| **user** (L83) | `>`(#d97757 700) + 文本 #cfc8ba, margin 16/0/4 |
| **thinking** (L87) | ✻(#9b8d72) + 斜体 thinkLabel + meta；展开后左边框 #34302a, 文本 #7d7568 斜体 12.5px, streaming 光标 ccblink |
| **say** (L94) | ●(#d97757) + 文本 #e6e1d6, streaming 橙光标 |
| **todos** (L98) | ● + "Update Todos" + 左边框列表(☑#7fa650 done / ◐#d9b25f doing / ☐#5f5b53 todo, done 划线) |
| **tool** (L109) | dot(done ●#7fa650 / running ◐#d9b25f) + `name(args)` + statusLabel；done 后 ⎿ + summary(#9bbd5a 12.5px) + ↗cowork 链接(#6f9bd1) |
| **gate** (L124) | **权限弹窗**, 见 §5 |
| **handoff** (L146) | **终点交接卡**, 见 §5 |

### D. Input + status（L166-184）
- 输入框：border 动态(`inputBorder` draft 时 #4a463f / 空 #302d29)，bg #211f1c，radius 11，padding 10/13。`>` 提示符 + textarea(max-h 120, 自动行高) + 发送按钮(#d97757, hover #e08862, label `▶ 开始`/`↵`)。
- **状态行**（治理可见性关键）：`⏺` + model(`sonnet-4.5`) │ **permGlyph permMode**(auto ◐#d9b25f / 非auto ⏸#7fa650) │ `ctx` 进度条(42×5px, >75% 转 #d9b25f) │ `⎇ branch`。

### E. Workspace 产物卡（COWORK, L214-323）— 8 张卡
统一卡壳：border #34302a / bg #1d1c19 / radius 11；卡头 bg #221f1c / border-bottom #302d29 / 橙图标 + 标题 600。
1. **假设卡**(L220)：命题/可证伪条件(#d99a8e 红=失败阈值)/benchmark/goal_ref；右上 `exploratory` 黄胶囊。
2. **市场卡**(L232)：3 数据源 + 字段宇宙 41 列分组 + 覆盖说明。
3. **因子集卡**(L250)：3 因子(左边框 #9bbd5a 绿) + IC + QUALIFIED 绿胶囊；右上 `← 因子台·选用`(#6f9bd1 蓝胶囊 = **跨台血统标记**)；底注"只选用 QUALIFIED+，不在此造因子"。
4. **模型卡**(L265)：task/CV NDCG/walk-forward 8/8(可展开 8 窗口表，最差 W4 +0.9% #d9b25f 黄)；右上 `← Model台·staging` 蓝胶囊；底注"只引用 model_id，不训练"。
5. **信号卡**(L287)：信号规则/调仓/方向/候选数。
6. **风控+执行卡**(L299)：风控限额(绿=约束/红 #d99a8e=熔断) + 执行机制(进入/退出)。
7. **RunVerdictCard**(L322)：`dc-import` 外部组件(100%×420px)，渲染 `runObj`(sharpe/excess/maxDD/PBO/DSR/equity曲线/3 成本预设)。
- **CODE tab**(L327)：yaml 随里程碑累积，6 色高亮(key/val/str/cmt/plain/ref)，`←因子台`/`←Model台`注释用 ref 蓝。
- **REPORT tab**(L337)：markdown(h/h2#d97757/li#bcd98a绿/p)。

---

## ③ 状态模型（{{}} 变量清单 + TS interface 草拟）

state 字段（L352-358）：
`permMode, blocks[], cursor, busy, busyWord, busySecs, busyTokens, thinkOpen{}, draft, slashOpen, started, gateWaiting, ctxUsed, reachedMs[], activeMs, coworkOverride, wsTab("cowork"|"code"|"report"), factorsSelected, modelSelected, signalSelected, portfolioSelected, runReady, reportReady, wfOpen, wsOpen, chatOpen, chatW`

实例字段：`_events[]`(脚本驱动剧本), `_milestoneDefs[]`, `_runObj`, `_factorSet`, `_fieldGroups`, `_msAnchor{}`。

```ts
type PermMode = "ask" | "auto" | "bypass";
type SideEffect = "none" | "external" | "realmoney";
type BlockType = "user"|"thinking"|"say"|"todos"|"tool"|"gate"|"handoff";
type CoworkKind = "hypothesis"|"market"|"factorSet"|"model"|"signal"|"portfolio"|"run";

interface ToolBlock {            // isTool
  id: string; type: "tool";
  name: string;                  // backtest.run / hypothesis.create ...
  args: Record<string, unknown>;
  ms?: string;                   // 关联里程碑 key
  cowork?: CoworkKind;           // 关联产物卡
  _status: "running" | "done";
  summary: string;
  side_effect?: SideEffect;      // [缺] 设计稿 tool block 未显式带, 应补
}
interface GateBlock {            // isGate — 权限弹窗
  id: string; type: "gate";
  tool: string;                  // "backtest.run"
  se: string;                    // "side_effect: none"  ← 必须真实
  blurb: string; args: Record<string, unknown>;
  _pending: boolean; _resolved?: "once" | "always" | "no";
}
interface HandoffBlock { id: string; type: "handoff"; _pending: boolean; _resolved?: boolean; }
interface Milestone { key: string; label: string; cowork: CoworkKind; }
interface RunObj {
  run_id: string; sharpe: number; annExcess: number; maxDD: number;
  turnover: number; winWeeks: number; ir: number;
  equity: number[]; bench: number[];
  cost: { preset: string; sharpe: number; excess: number }[];
  pbo: number; dsr: number;
}
interface AgentWindowState {
  permMode: PermMode; blocks: Block[]; cursor: number;
  busy: boolean; busyWord: string; busySecs: number; busyTokens: number;
  draft: string; slashOpen: boolean; gateWaiting: boolean; ctxUsed: number;
  reachedMs: string[]; activeMs: string | null;
  coworkOverride: CoworkKind | null; wsTab: "cowork"|"code"|"report";
  factorsSelected/modelSelected/signalSelected/portfolioSelected/runReady/reportReady: boolean;
  wfOpen/wsOpen/chatOpen: boolean; chatW: number;
}
```
⚠️ 设计稿是**纯前端脚本剧本回放**（`_events[]` 硬编码、`_typewrite` 模拟流式、`permission_gate` 仅前端 `_gate()`）。真实接线需把 events 换成 SSE 流 + 真后端 gate（见 §7）。

---

## ④ 交互清单（所有 handler）

| handler | 行为 |
|---|---|
| `restart`/`_restart` | 清 timers，重置 state，重放剧本 |
| `_start`/`_next` | 剧本推进引擎：按 cursor 取 event，分发到 user/thinking/say/todos/tool/gate/handoff |
| `_typewrite` | 逐字符流式打字(随机步进+延迟) |
| `chatToggle`/`wsToggle` | 折叠/展开左右栏 |
| `splitDown` + pointermove/up | 拖拽 splitter 调 chatW(clamp 280-760) |
| `m.go`/`_gotoMs(key)` | 仅 reached 可点；切 coworkOverride 到该里程碑 cowork + 滚动定位锚点 |
| `b.focus`/`_focusCowork` | tool block 的 ↗ 链接 → 聚焦对应产物卡 |
| `b.toggle` | thinking 块展开/收起 |
| `wfToggle` | 模型卡 walk-forward 8 窗口表展开 |
| `tabCowork/Code/Report Click` | 切 wsTab |
| `onDraft` | 输入；`/` 开头→开 slash 面板 |
| `onKey` | Enter 发送(Shift+Enter 换行) |
| `send`/`_send` | `/clear`·`/restart`→重放；否则推 user + demo 回执 |
| `s.pick`(slash) | 选命令填入 draft |
| **`b.approveOnce`/`_resolveGate("once")`** | 批准本次：patch resolved=once → 继续 |
| **`b.approveAlways`/`_resolveGate("always")`** | 批准且 `permMode→auto`(升级权限!) |
| **`b.reject`/`_resolveGate("no")`** | 拒绝：resolved=no + 追问"怎么改" |
| **`b.submit`/`_submitHandoff`** | 提交候选策略进模拟台候选池(终点) |

---

## ⑤ 治理 / 业务元素专章（D-PERM 守门审计）

### 权限三态 UI（设计稿 vs 后端实现）
- 状态行 `permMode` 实时显示（auto ◐黄 / 非auto ⏸绿），slash `/permissions` 可切 ask/auto/bypass，`$props.permissionStart` 可初始化三态。
- **gate 弹窗只在 `permMode==="ask"` 出现**（`_gate()` L455 = `mode==="ask"`）。这与后端 `permission_gate(mode, side_effect)`（agent_runtime.py L37-48）**逻辑一致**：`none` 类工具 ask→confirm、auto/bypass→execute。
- gate 弹窗三选项：`1.Yes` / `2.Yes 别再问(→auto)` / `3.No 告诉怎么改(esc)`，仿 Claude Code 数字键风格。绿底批准、红底拒绝。

### D-PERM「权限轴 ⟂ 治理轴：bypass 绝不跳治理门」是否守住？
**结论：设计稿守住了，但靠的是「回避」而非「正面演示」——存在一处需补强的盲点。**

✅ **守住**：
1. 设计稿全程**只演示 `backtest.run`，明示 `se: "side_effect: none"`**。none 类工具 bypass 自跑天经地义，不违反 D-PERM。
2. 顶栏明示终点是「交接模拟台」，handoff 卡文案"进场与否、监控由模拟台决定"——**默认止于模拟盘**(D-PERM L176 / R8 不跳级)，设计稿守住了"agent 绝不把直接实盘作默认导向"。
3. 后端 `permission_gate`：`realmoney` 任何模式(含 bypass)恒 `confirm`(L44-45)；`external`(testnet) 仅 bypass 自动、ask/auto 需确认(L46-47)。register 块(main.py L296-305) **只注册 side_effect=none 工具**，动钱/晋级永不注册——纵深防御与设计稿叙事一致。

⚠️ **盲点（需补卡/补文案）**：
1. **设计稿从未演示 external / realmoney 工具在 bypass 下被拦的画面**。D-PERM 的核心反例（"bypass 也拦真钱"）在 UI 上**没有可视证据**。T-040 对抗测试 #3「默认导向实盘必抓」需要这块 UI，但设计稿没给——**应补一张"bypass 模式下 realmoney 仍弹确认"的 gate 变体**，否则陌生用户看不到治理轴的存在。
2. `_resolveGate("always")` 直接把 `permMode→auto`，**没有 self-approve 二次确认**（T-030 在 T-041 scope 内）——设计稿此处与 T-041「self-approve 二次确认」**冲突/缺失**。
3. gate 弹窗 `se` 是 demo 硬编码字符串。真实接线必须从后端 `tool_status[].side_effect` 取真值（否则可伪造 none 绕过，正是 T-040 对抗 #1）。

### 业务元素（策略台脊柱）
- **跨台血统标记**：因子集/模型卡的 `←因子台`/`←Model台` 蓝胶囊 = 血统门可视化（QUALIFIED+ 因子、staging+ 模型、"不在此造/不在此训"底注）。这呼应 T-040 对抗 #2「血统弱点默认展开」，但设计稿把它做成**常驻展开**(✅ 正确)。
- **可证伪门**：假设卡"可证伪条件"用红色 #d99a8e 渲染失败阈值 → 对应 T-041 的可证伪 409 引导句，但设计稿是产物卡展示、非 409 弹窗（T-041 还需补弹窗形态）。
- **过拟合三角门**：RunVerdictCard 含 PBO 0.18 / DSR 1.34 → 对应 T-043 对抗 #3。

---

## ⑥ Design tokens 差异（与策略台/Model台那套对比）

设计稿 token 与全局基准**完全一致**（同一设计语言）：
| token | 设计稿值 | 基准(CLAUDE/Model台) | 一致? |
|---|---|---|---|
| 主背景 | `#1c1b19` | #1c1b19 | ✅ |
| 强调橙 | `#d97757` | #d97757 | ✅ |
| 字体 | JetBrains Mono | JetBrains Mono | ✅ |
| 正文色 | #e6e1d6 / 次 #cfc8ba / 弱 #8f897c / 更弱 #5f5b53 | — | (新增完整灰阶) |
| 成功绿 | #7fa650 / #9bbd5a / #bcd98a | — | (绿阶) |
| 警告黄 | #d9b25f | — | (黄阶) |
| 危险红 | #d99a8e | — | (红阶) |
| 蓝(血统/链接) | #6f9bd1 | — | (蓝阶) |
| 面板分层 | bg #1a1916/#1d1c19/#191815/#211f1c, border #302d29/#34302a/#2a2723 | — | (深色分层) |
| radius | 6/7/8/10/11px | — | |
| 动画 | ccblink(光标) / ccring(里程碑脉冲) | — | |

⚠️ **落地差异**：现有前端用 CSS 变量类(`cc-card`/`cc-btn--accent`/`var(--cc-border)` 等, 见 Mode2ChatPage)，**不是内联十六进制**。设计稿全内联色值，落地时须**映射到现有 `cc-*` token 系统**（新增缺失的灰/绿/黄/红/蓝阶 CSS 变量），不要内联硬编码——否则与全站主题漂移。

---

## ⑦ 对应现有前端页面 + 落点建议 + 后端缺口

### graphify 定位的现有页面
- `app/frontend/src/pages/workshop/Mode2ChatPage.tsx`（`Mode2ChatPage()` L47）：thread 列表 + SSE 流式 + MessageBubble + market_mode 下拉 + RAG hits。**有真 SSE、有 market_mode、无工具可视化/无权限三态/无产物工作区/无里程碑**。
- `app/frontend/src/pages/workshop/AgentChatPage.tsx`（`AgentChatPage()` L23）：`/api/agent/chat` 非流式 + LLM provider 状态条 + ChatMsg(tool_calls 仅显示 `⇒ name` 胶囊)。**有最朴素的 tool_call 可视化、无权限、无产物区**。

### 落点建议（新建 vs 增强）

| 设计稿区块 | 落点 | 新建/增强 |
|---|---|---|
| 整窗骨架(双栏+折叠+splitter+里程碑) | **新建** `AgentWorkbenchPage.tsx`(或 workshop/agent-window/) | T-040 接线点写"扩展 Mode2ChatPage"，但设计稿是**全新两栏布局**，Mode2 单栏 thread 模型无法直接扩展。**建议新建组件、复用 Mode2 的 SSE/authFetch 逻辑**，而非原地改 Mode2（避免破坏现有 /chat 基线）。← 需向 leader 澄清 T-040「扩展不替换」的字面与设计稿现实的张力。 |
| 7 种 chat block | 新建 block 渲染器(替代 MessageBubble/ChatMsg) | 新建 |
| 工具可视化(折叠摘要+下钻) | 增强 ChatMsg 思路 | 新建 |
| 权限三态状态行 + slash /permissions | **新建**，对接后端 permission_mode | 新建 |
| gate 弹窗 | T-041 scope | 新建 |
| 8 张产物卡 + RunVerdictCard | **新建**产物工作区 | 新建 |
| 里程碑进度线 | **设计稿独有、四卡未列** | 新建(需补卡, 见下) |
| 台 switcher(因子台/Model台/策略台/模拟台) | **设计稿独有、四卡未列** | 新建(需补卡) |
| Tauri 桌面挂载 | T-042 | 复用 |

### 四卡覆盖度逐条映射（核心交付）
| 设计稿元素 | 覆盖卡 | 状态 |
|---|---|---|
| 对话流 + 7 种 block | T-040 | ✅ 覆盖(scope 含"对话流+工具可视化") |
| 工具可视化(折叠/下钻) | T-040 | ✅ 覆盖 |
| 权限三态状态行+切换 | T-040 | ✅ 覆盖 |
| gate 审批弹窗 + 三选项 | T-041 | ✅ 覆盖(审批弹窗) |
| 血统警告/red 裁决/可证伪引导 | T-041 | ✅ 覆盖 |
| self-approve 二次确认 | T-041 | ⚠️ 设计稿 `→auto` **没做二次确认**，与 T-041 冲突——落地须加 |
| 产物工作区(8 卡+code+report) | **无卡** | ❌ **未覆盖**——四卡均无"右侧产物工作区/cowork"scope。**需补卡** |
| 里程碑进度线(7 节点+跳转) | **无卡** | ❌ **未覆盖**——需补卡 |
| 台 switcher(4 台导航) | **无卡** | ❌ **未覆盖**——跨台导航，需补卡 |
| 双栏折叠 + splitter 拖拽 | T-040(隐含) | ⚠️ 未显式，建议并入 T-040 |
| backtest.run 接真引擎 | T-043 | ✅ 覆盖 |
| eval.pbo / report.generate 真 handler | T-043 | ✅ 覆盖 |
| RunVerdictCard 数据(sharpe/PBO/DSR/equity) | T-043 后端 + 前端无卡 | ⚠️ 后端有、前端产物卡无卡 |
| Tauri 挂载 | T-042 | ✅ 覆盖 |

**需补 3 张卡**（设计稿超出现有四卡 scope）：
1. **T-044 产物工作区**：右栏 8 张产物卡 + Strategy.yaml + Report.md tab（cowork 可视化）。这是设计稿一半的体量，四卡完全没提。
2. **T-045 里程碑进度线 + 跨台台 switcher**：7 节点进度 + 4 台导航。
3. **T-046（或并入 T-041）**：D-PERM 反例 UI——bypass 模式下 realmoney/external 仍弹确认的 gate 变体 + self-approve 二次确认（补 T-040 对抗 #3 的 UI 证据）。

### 后端端点缺口
| 需求 | 现状 | 缺口 |
|---|---|---|
| `/api/agent/chat/{tid}/stream` SSE | ✅ 有(main.py L3127) | 仅发 `chunk`/`rag`/`done` 事件；**缺 tool_call 开始/结束、gate 挂起、todos、thinking、里程碑事件**——设计稿 7 种 block 需后端发结构化 SSE event 类型 |
| `permission_mode` 入参 | ✅ 有(`/message` L3105 取 payload) | **`/stream` 端点未接 permission_mode**(stream 用 current_user，未见取 permission_mode)——需补 |
| `/api/agent/tools` tool_status + side_effect | ✅ 有(L1505) | 可用；前端 gate 须从此取真 `side_effect`(防伪造) |
| `backtest.run` / `eval.pbo` / `report.generate` 注册 | ❌ **未注册**(register 块 L296-305 只有 strategy_goal/factor.run_ic/code.replicate/field tools) | **T-043 核心缺口**：这三个 + hypothesis.create/factor_set.compose/model_registry.select/signal.define/portfolio.construct **均未注册**(schema 有 backtest.run/eval.pbo/report.generate 但 handler 未接；hypothesis/factor_set/model_registry/signal/portfolio **schema 都没有**)。设计稿用了 7 个工具名，后端 schema 只覆盖 backtest.run/eval.pbo/report.generate，**其余 4 个工具名后端不存在**——需建 schema + handler |
| 候选策略提交模拟台(handoff) | ❌ 无端点 | 需新建 `/api/strategy/submit_candidate`(治理门：止于模拟盘) |
| 跨台导航(因子台/Model台/模拟台数据) | 部分(Model台存在) | 因子台/模拟台"敬请"——未建 |

---

## 关键结论（给 leader 拍板）

1. **四卡 scope 覆盖约 60%**：对话流/工具可视化/权限三态/弹窗/Tauri/backtest 接引擎都在；**产物工作区(8 卡)、里程碑进度线、台 switcher 三大结构性区块完全没卡**——这是设计稿近一半的视觉体量，必须补卡，否则四卡做完仍交付不出设计稿。
2. **D-PERM 守住但缺正面 UI 证据**：设计稿只演 none 类 bypass 自跑，没演 realmoney/external 在 bypass 下被拦——治理轴在 UI 上"隐形"。建议补一张反例 gate，让陌生用户看得见"bypass 也拦真钱"。
3. **self-approve(→auto) 二次确认缺失**：设计稿 `2.Yes 别再问` 直接升 auto，与 T-041(T-030)冲突，落地须加二次确认。
4. **后端工具缺口大**：设计稿 7 个业务工具名中 **4 个(hypothesis.create/factor_set.compose/model_registry.select/signal.define/portfolio.construct)后端 schema 都不存在**，3 个(backtest.run/eval.pbo/report.generate)有 schema 无 handler。T-043 scope 需扩到补这些 schema+handler，否则 agent 跑不出设计稿剧本。
5. **落点张力**：T-040 写"扩展 Mode2ChatPage 不替换"，但设计稿是全新双栏布局，Mode2 单栏 thread 模型扩不动——建议**新建组件复用 Mode2 的 SSE/auth 逻辑**，需向 leader 澄清字面冲突。
6. **token 一致**(#1c1b19/#d97757/JetBrains Mono 全对齐)，但落地须映射到现有 `cc-*` CSS 变量、勿内联硬编码。

相关文件（绝对路径）：
- 设计稿：`/tmp/qbt-handoff/quantbt-claude/project/QuantBT Agent.dc.html`
- 现有前端：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/pages/workshop/Mode2ChatPage.tsx`、`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/pages/workshop/AgentChatPage.tsx`
- 后端权限/工具：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/agent/agent_runtime.py`(L37 permission_gate)、`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/main.py`(L286 _agent_runtime / L296-305 register / L1505 tools / L3127 stream)、`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/agent/tool_schema.py`
- 决策：`/Users/wzy/Work/01_Projects/QuantBT/dev/decisions/dreaminate/DECISIONS.md`(§D-PERM L169-177)
- 四卡：`/Users/wzy/Work/01_Projects/QuantBT/dev/tasks/dreaminate/{82120b9c,3d95e0f6,bc21c7c1,3bb62d7d}/TASK.md`