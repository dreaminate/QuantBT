I now have a complete picture. The backend has all the data behind the verdict card (PBO `eval/pbo.py`, DSR `eval/dsr.py`, overfit gate `eval/overfit_gate.py` with `GateVerdict` + wording tests, verdict `verification/`, promote `ide/promote.py`) but none of it is wired to a per-run endpoint that either frontend consumes. Compiling the structured report.

---

# 设计稿解析 + 冻结红线比对报告：回测详情 / RunVerdictCard

> 范围：`/tmp/qbt-handoff/quantbt-claude/project/回测详情.dc.html`（64KB）+ `RunVerdictCard.dc.html`（21KB），逐项对照冻结页 `app/frontend-run-detail/src/pages/RunDetailPage.tsx`（1533 行）。
> 关键事实先行：**`回测详情.dc.html` 是冻结页本身的设计稿（深色主题重绘 + 三处新区块）；`RunVerdictCard.dc.html` 是全新独立组件**（紧凑裁决卡 + 内嵌全详情 modal）。两者用同一套 token，与策略台 `#1c1b19/#d97757/JetBrains Mono` 一致。

---

## ① 整体布局骨架（区域树 + 尺寸）

### A. `回测详情.dc.html`（= 冻结页的深色重绘，浅色→深色）
```
#jq-rd  [100vh, flex-col, bg #f0f2f5(浅) / 设计稿仍是浅色!, font 14px, color #333]
├─ .jq-topbar            [h46, bg #1a2b4a 深蓝, padding 0 18px, gap24]   ← 设计稿新增完整顶栏
│   ├─ .jq-logo          ["QB" icon 26×26 bg#4a7cf7 r6 + "QuantBT" 17px/700]
│   ├─ .jq-nav           [数据|因子|模型|策略|回测(active)|研究, 13.5px, active下边框2px白]
│   └─ a 血缘定位         [margin-left:auto, "← 策略台 · 血缘定位", border 1px rgba白.25, r7]  ← 新增治理入口
└─ .jq-rd-body           [flex1, padding 10/14]
    └─ .jq-run-detail-shell [flex-col flex1]
        ├─ .jq-run-detail-statusbar  [minH30, bg#eef1f4, border#d7dbe2, 11.5px, space-between]
        │   ├─ left: {{recordName}}/{{status}}/基准/频率/区间/开始
        │   └─ right: 净值|交易|指标|报告 (a, #2f6fdd)
        └─ .jq-run-detail-main       [flex-row, margin-top8, flex1]
            ├─ aside .jq-run-detail-sidebar  [flex 0 0 158px, bg#eef1f4, border 右0]
            │   └─ navGroups → 功能视图(8项) + 指标页(10项)  [navitem active: 白底+#2f6fdd+inset左条]
            └─ main .jq-run-detail-content   [flex1, bg#fff, border, overflow hidden]
                └─ <sc-if> × 9 视图  (overview / trades / positions / log / perf / code / report / attribution / metric)
                    overview 内：page-head(收益概述) → summary-board(11列×2行 metrics grid)
                                 → chart-toolbar(缩放预设 + 三图例 + 线/对数轴 radio + 双 date input)
                                 → chart-panel(#ovc echarts, minH 560, 三联网格: 净值300/每日盈亏120/买卖120)
```

### B. `RunVerdictCard.dc.html`（全新独立卡片，深色）
```
card  [bg#1d1c19, border 1px#34302a, r11, overflow hidden, JetBrains Mono, color#e6e1d6]
├─ header        [flex, gap10, padding 11/15, bg#221f1c, border-bottom#302d29]
│   ├─ ◳ #d97757 + "回测详情 · {{runId}}" 600
│   ├─ <sc-if drawing> "⟳ 生成中 {{drawPct}}" 10px #d9b25f
│   └─ verdict chip [ml-auto, 11px/600, color/bg 动态, padding 3/11, r20]  ← 裁决 pill
├─ KPI 行         [flex wrap, padding 13/15/9]  4 格(min 88px): 年化超额/最大回撤/Sharpe/周胜率
│                  [label 11px#7d7668 · value 21px/700 · sub 10.5px#5f5b53(目标/约束/IR/换手)]
├─ 净值缩略图     [padding 4/15/10]
│   ├─ 图例行 [策略净值(#d97757 2px) · 中证500(#5f5b53 2px) · "完整回测详情页↗"(#6f9bd1) · "卡内预览"(#8f897c)]
│   ├─ svg [viewBox动态, h118, area渐变 rvgrad + benchPath虚线 + eqPath]
│   └─ 轴标 [2019-01 ── 2024-12·312周]
├─ 成本敏感性     [padding 4/15/12]  "成本敏感性 · Sharpe/年化超额"
│   └─ 3 cost cells [flex, bg#221f1c, border动态, r8] preset/sharpe16px/超额
├─ footer 裁决区  [padding 11/15, bg#1a1916, border-top#302d29]
│   ├─ PBO/DSR 行 [PBO {{pbo}} "<0.5健康" · DSR {{dsr}} ">0显著"]
│   └─ verdictNote(flex1) + promote 按钮 [bg/border/color 动态, 12px/700, r8]
└─ <sc-if detailOpen> FULL DETAIL MODAL  [fixed inset0, bg rgba(8,8,7,.74), z200]
    └─ dialog [w880, maxH92vh, bg#1a1916, border#3a352e, r14, shadow]
        ├─ sticky header [runId + 区间副标 + verdict chip + "↗打开完整页面"(#d97757) + ✕关闭]
        └─ body [padding16/18, flex-col gap16]
            ├─ metrics grid 4列(12项)  ├─ 净值+回撤 svg(h190, 含 dd 红带)
            ├─ 月度超额热力图(6年×12月, seed 生成)
            ├─ 交易统计 | 过拟合体检 (并排 flex)
            ├─ 成本设置(可编辑 input number ×4, 单边合计 bp)
            └─ 期末持仓 top8 表
```

---

## ② 每个面板/区块职责 + 关键视觉值

| 区块 | 职责 | 关键视觉（设计稿原值） |
|---|---|---|
| **topbar（详情稿）** | 全局产品导航 + 血缘回跳 | bg `#1a2b4a`，h46，logo icon bg `#4a7cf7`，nav active 下边框 2px 白；血缘按钮 border `rgba(255,255,255,.25)` r7 |
| **statusbar** | run 元信息条 | minH30，bg `#eef1f4`，border `#d7dbe2`，11.5px；strong `#233b73`，completed `#2f6fdd`，failed `#d34f4f` |
| **sidebar** | 9+10 视图切换 | flex 158px，bg `#eef1f4`；navitem 12px `#5c6675`，hover `#2f6fdd`，active 白底+`#2f6fdd`+`inset 2px 0 0` 左条 |
| **metrics grid** | 21 项绩效指标 | `grid-template-columns: repeat(11, 1fr)`，gap 4/2；label 11px`#888`，value 14px/600`#222`；**A股色：正=红`#d34f4f`、负=绿`#2e8b57`**（`.positive/.negative` 反向！）；最大回撤区间跨 2 列 |
| **chart-toolbar** | 缩放/图例/轴/日期 | 图例 swatch 策略`#4C78A8`/超额`#F28E2B`/基准`#E45756`；link `#1a5fb4` |
| **echarts 三联图** | 净值+每日盈亏+买卖 | 主图 300 / 每日 120 / 买卖 120，gap8；grid `#EAEAEA`；策略 area `rgba(76,120,168,.15)` |
| **RunVerdictCard header** | 标题 + 裁决 pill | bg `#221f1c`，verdict chip r20，色/底动态（晋级候选=`#9bbd5a`/`rgba(127,166,80,.15)`） |
| **KPI 4 格** | 双目标 + 风险速读 | value 21px/700；达标绿 `#9bbd5a`，中性 `#e6e1d6`；sub `#5f5b53` 10.5px 带「目标≥15% / 约束≤20%」 |
| **成本敏感性** | 3 预设 Sharpe/超额 | cell bg `#221f1c`，neutral border `#4a433a`，pessimistic label `#d9b25f`、optimistic `#9bbd5a` |
| **footer 裁决** | PBO/DSR + note + promote | bg `#1a1916`；PBO<0.5 绿否则 `#d97066`；promote 默认 bg `#d97757` color `#1c1b19`，已登记后转 `rgba(127,166,80,.14)`+绿字 |
| **detail modal** | 完整详情复刻 | dialog bg `#1a1916` r14；卡片 bg `#1d1c19` border `#302d29` r9~10；热力正 `rgba(127,166,80,a)` 负 `rgba(217,112,102,a)` |

---

## ③ 状态模型（{{}} 变量清单 + TS interface 草拟）

### 详情稿 `state`（与冻结页 1:1）
`tab` · `logTab(logs|errors)` · `yMode(linear|log)` · `showStrategy/showExcess/showBenchmark` · `rangeStart/rangeEnd` · `tradeGroup/tradeOrder`。
绑定变量：`recordName/status/benchmark/frequency/analysisRange/startedAt`、`navGroups[]`、9 个 `isXxx` 布尔、`metricsRow1[11]/metricsRow2[10]`、图例 cls `legS/legE/legB`、`tradeDays[]/positionDays[]/logLines[]`、`artifactRows/outputRows/attrSummary/attrRows`、`metricTitle/metricColor/metricLatest/metricSubtitle/metricTableRows`。

### RunVerdictCard `state`
`promoted(bool)` · `detailOpen(bool)` · `drawP(0→1 动画)` · `cost:{commission,slippage,stamp,impact}`。

```ts
// 裁决卡数据契约（后端需新增端点供给）
interface RunVerdictCard {
  runId: string;
  verdict: "consistent" | "concern" | "blocked";   // ⚠ 后端 schema 三态——不可用 "晋级候选/可信" 当裁决枚举
  verdictLabel: string;        // 展示文案（"晋级候选" 来自 overfit_gate.GateVerdict，≠ 验证官 verdict）
  verdictColor: string; verdictBg: string;
  kpi: { annExcess: number; maxDD: number; sharpe: number; ir: number; winWeeks: number; turnover: number };
  equity: number[]; bench: number[];
  cost: Array<{ preset: "optimistic"|"neutral"|"pessimistic"; sharpe: number; excess: number }>;
  pbo: number; dsr: number;          // eval/pbo.py, eval/dsr.py
  verdictNote: string;               // 必须用 verifier._verdict_note 措辞：一致/存疑/不一致，禁可信/安全
  promoteState: "candidate" | "registered";
}
// 完整 modal 额外：metrics[12], heat[6×12], tradeStats[6], overfit[4], holdings[8], costRows(可编辑)
```

---

## ④ 交互清单（所有 handler 行为）

**详情稿（= 冻结页已有，零新增交互）**：`setState({tab})` 切视图 · `toggleStrategy/Excess/Benchmark` 图例显隐 · `setLinear/setLog` 轴模式 · `preset1m/3m/1y/All` + `onStartDate/onEndDate` + `_onZoom` 缩放（dataZoom↔日期单一数据源）· `toggleTradeOrder` 交易排序 · `setLogTabLogs/Err` 日志过滤。

**RunVerdictCard（全新）**：
- `openDetail/closeDetail` → 打开/关闭全屏 modal；`stop(e)` 阻止冒泡。
- `onPromote` → `promoted=true`，按钮文案/配色切换为「✓已登记对比分析」。**这是写动作**，需对接 `ide/promote.py`。
- `c.onInput` → `_setCost(key,v)` 实时改成本，驱动 `costTotal` 重算（modal 内）。
- `componentDidMount` 净值绘制动画 `drawP 0→1`（纯展示）。
- 两个外链：`href="回测详情.dc.html"` + `openDetail`（卡内预览）——落地时前者应路由到冻结页 `/runs/:id`。

---

## ⑤ 治理/业务元素专章（GOAL §6 信任层映射）

**RunVerdictCard 是设计稿全新独立组件**（不在冻结页内），它正是 GOAL §6「L1–L4 渐进披露 + 弱点一等呈现(R25)」的承载：
- **L1（一眼裁决）**：header verdict pill + 4 KPI（双目标达标即绿）。
- **L2（弱点/风险一等）**：footer 的 PBO/DSR 与 verdictNote 同级于结论——「弱点一等呈现」。设计稿 note 文案`"双目标达标，PBO 0.18/DSR 1.34 排除过拟合。建议 pessimistic 成本下纸面跟踪 4 周再决定动钱"`——把保守动作写进结论。
- **L3（敏感性）**：成本敏感性 3 预设，pessimistic 高亮——抗「乐观参数选择」。
- **L4（完整证据）**：modal 的 metrics/热力/交易/过拟合体检/可编辑成本/持仓。

**裁决措辞红线（强约束，落地必须遵守）**：后端 `verification/schema.py` 把 verdict 锁死为 `consistent/concern/blocked`，`DISCLOSURE` 明文**禁用**「可信/安全/保证/可复现/组织独立」；`verifier._verdict_note` 只输出「一致/存疑/不一致 + 适用域 + 未验证项」。
⚠️ **设计稿的 "晋级候选" 来自另一条管线**——`eval/overfit_gate.py::GateVerdict`（PBO/DSR 过拟合门），**不是验证官 verdict**。落地时必须分清两个枚举：UI 不能把 GateVerdict 的「晋级候选」与 verifier 的三态混为一谈，且 `verdictNote` 文案必须由后端 `_verdict_note` 供给、不可前端杜撰「排除过拟合」这类绝对化措辞（设计稿原文已越界，落地需改写为「容差内/未触发熔断」式表述）。

---

## ⑥ Design tokens 差异（vs 策略台 `#1c1b19/#d97757/JetBrains Mono`）

| Token | RunVerdictCard（深色卡） | 详情稿主体（浅色） | 与策略台一致? |
|---|---|---|---|
| 字体 | **JetBrains Mono, ui-monospace** | Microsoft YaHei / PingFang（**浅色 sans**） | 卡片 ✅一致 / 详情主体 ❌（沿用 JoinQuant 浅色风） |
| 主背景 | `#1d1c19` / `#1a1916` / `#221f1c` | `#f0f2f5` / `#fff` | 卡片 ✅（策略台同族 `#1c1b19`）/ 详情 ❌ |
| 强调色 | **`#d97757`**（净值线/promote/链接） | `#2f6fdd` 蓝 / `#4C78A8` 图例 | 卡片 ✅ / 详情 ❌ |
| 成功/警示 | 绿 `#9bbd5a` / 黄 `#d9b25f` / 红 `#d97066` | A股反向：正红`#d34f4f`/负绿`#2e8b57` | 不同语义系统 |
| 边框/圆角 | `#302d29~#3a352e`，r8~14 | `#d7dbe2`，r2 | 卡片 ✅深色族 |

**结论**：RunVerdictCard 与策略台/裁决卡设计语言完全统一（深色 + 暖橙 + Mono），可直接落入策略台体系。**详情稿主体保留 JoinQuant 浅色风（这正是冻结页现状）**——即设计稿没有要求把冻结页改成深色，只在其上加 topbar/血缘入口。两套主题是**有意并存**：冻结回测页=浅色专业风，治理/裁决层=深色暖橙信任风。

---

## ⑦ 对应现有前端 + 落点建议 + 后端缺口

### 对应关系（graphify 确认）
- **冻结页** = `app/frontend-run-detail/src/pages/RunDetailPage.tsx`（社区 29，RULES.project §10 钉死「收益概述页冻结」）。topbar 在同工程 `App.tsx`（现 logo=`Q1/1Backtest`，**非**设计稿的 `QB/QuantBT`，且无导航 tabs、无血缘按钮）。
- `app/frontend/src/pages/RunDetailPage.tsx`（社区 46）是另一套主应用页，**不是**红线冻结对象。
- 两个前端**均无任何裁决卡 UI**（grep verdict/PBO/DSR/晋级 在 run-detail 零命中）。

### 落点建议
- **RunVerdictCard → 新建独立组件**（`app/frontend/.../RunVerdictCard.tsx` 或挂入策略台/runs 列表），**绝不**嵌进冻结页。它是 §6 信任层新页面（M15「治理新页面待加」），不受冻结约束。
- **详情稿的 topbar/血缘入口 → 改 `App.tsx`（非冻结文件）**，安全。

### ⚖️ 冻结红线分类表（设计稿 vs 冻结 RunDetailPage）

| 设计稿改动 | 性质 | 判定 | 依据 |
|---|---|---|---|
| topbar logo/导航 tabs/血缘回跳按钮 | 在 `App.tsx`（非冻结文件） | ✅ **允许** | 红线只钉 `RunDetailPage.tsx` 收益概述页 |
| statusbar 加「区间 {{analysisRange}}」字段 | 加显示字段 | ✅ **允许** | 「加字段」明文允许 |
| metrics grid 排版/列宽/A股正负配色 tone | 排版/显示逻辑 | ✅ **允许** | 「排版/显示逻辑」允许 |
| 9 视图 sc-if、sidebar 分组、图表三联结构 | 与冻结页一致（无改） | ✅ **无需动** | 设计稿=现状重绘 |
| RunVerdictCard 整体（卡 + modal + promote + 可编辑成本） | 全新独立组件 | ✅ **允许（新建）** | 不进冻结页即可 |
| **若把裁决卡/KPI 条嵌入冻结页 overview 顶部** | 新增交互区块到冻结页 | 🔴 **违红线** | 改冻结页交互结构 |
| **把详情主体浅色改深色主题** | 重构冻结页视觉体系 | 🔴 **违红线**（超「排版」范畴，需停下问用户） | 主题切换=重构显示体系，设计稿也未要求 |
| **modal 内「成本可编辑→重算回测」** | 新增交互+逻辑 | 🔴 **违红线 if 放冻结页**；放裁决卡则允许 | 冻结页禁新交互/逻辑 |
| **detailContentTab/dataZoom/图例 toggle 行为改写** | 重构现有交互 | 🔴 **违红线** | 「绝不重构交互/逻辑」 |

### Pixel-perfect 可达程度
- **可 100% 落地、不碰红线**：RunVerdictCard 全卡 + modal（新组件）；`App.tsx` 顶栏 + 血缘入口；冻结页内纯排版/配色/加字段微调。
- **必须停下问用户（要动冻结页）**：① 把裁决 KPI/卡片**嵌入** overview 页顶；② 冻结页**整体深色化**；③ 任何 dataZoom/tab/图例**交互改写**；④ 在冻结页内放可编辑成本输入并触发重算。

### 后端端点缺口（数据已具备、端点未通）
后端逻辑齐全但**无一个 run 级裁决端点**，现有 `api.ts` 仅 `/api/runs/{id}` `/series` `/logs` `/attribution` `/source` `/tables` `/export` `/artifacts`——**无 verdict/overfit/cost-sensitivity/promote**。需新增：
1. `GET /api/runs/{id}/verdict` → 投影 `verification/store.py::VerdictStore` + `VerdictRecord.to_review()`（三态 + disclosure + note）。
2. `GET /api/runs/{id}/overfit` → `eval/overfit_gate.py::run_overfit_gate`（PBO `eval/pbo.py::cscv_pbo`、DSR `eval/dsr.py::deflated_sharpe_ratio`、honest-N、GateVerdict）。
3. `GET /api/runs/{id}/cost-sensitivity?preset=` → 3 预设 Sharpe/超额（后端现无，需新增成本扫描）。
4. `POST /api/runs/{id}/promote` → `ide/promote.py`（promote 写动作，注意 RULES：land/分配权限语义，promote 是否需审批待确认）。
5. modal 的月度热力/交易统计/持仓 top8——前两类可复用 `/series`/`/tables`，**月度超额热力图后端无聚合端点**（设计稿现用前端 seed 造数）。

**关键风险提示（需用户拍板）**：设计稿 verdictNote 写「排除过拟合」「可信」式绝对措辞，与后端 `DISCLOSURE`/`_verdict_note` 的「禁可信/安全/保证」铁律冲突——落地文案必须以后端供给为准、改写设计稿原文。这属 GOAL §6 + R7 红线，不可照搬 pixel-perfect 文案。

**相关文件（绝对路径）**：
- 冻结页：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend-run-detail/src/pages/RunDetailPage.tsx`
- 顶栏（非冻结）：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend-run-detail/src/App.tsx`
- API 层：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend-run-detail/src/api.ts`
- 裁决后端：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/verification/{schema,verifier,store}.py`
- 过拟合/PBO/DSR：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/eval/{overfit_gate,pbo,dsr,gate_runner}.py`
- promote：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/ide/promote.py`
- 红线源：`/Users/wzy/Work/01_Projects/QuantBT/dev/RULES.project.md` §10、`dev/GOAL.md` §0/§6