I now have a complete picture. Here is the structured analysis.

---

# 模拟台 / PaperBoard 设计稿全解剖

> 范围：`模拟台.dc.html`(44KB · 全功能页面) + `PaperBoard.dc.html`(6.5KB · 嵌入式卡片)。对照 GOAL §5 live ladder + 现有 `BinanceTradingPage.tsx` + 后端 `app/paper/` / `app/execution/paper_venue.py`。

## 0. 两文件关系（先定性）

| 维度 | `模拟台.dc.html` | `PaperBoard.dc.html` |
|---|---|---|
| 角色 | **独立全屏页面**(`height:100vh`，自带 title bar + 台 switcher + 5 子 tab) | **嵌入式卡片组件**(单个 `border-radius:11px` 圆角卡，无 title bar，无导航) |
| preview 尺寸 | `1280×880`(桌面全页) | `430×520`(竖卡，移动/侧栏比例) |
| 数据源 | `state` 内置 mock(`_runs` 三条) | `this.props.board`(外部注入 `board.hist/paper/positions/risk`) |
| 内容覆盖 | 运行盘+持仓成交+风险门+复盘归因+晋升通道(5 视图全集) | 单 run 速览：metrics + 净值缩略图 + top持仓 + 风险门 4 格 |
| 强调色 | 净值实盘段用 **绿 `#9bbd5a`** | 净值实盘段用 **橙 `#d97757`**(品牌色) |

**结论**：`模拟台` = **主页面**(对应一条 sidebar 路由 `/paper` 或 `/simulator`)；`PaperBoard` = **可复用卡片**，是 `模拟台` 运行盘视图的浓缩版，定位为「嵌进别处的模拟盘 widget」(如策略台某策略详情、首页 dashboard、跟单页)。两者是「全页 vs 卡片」而非「页 vs 子组件」——`PaperBoard` 并非 `模拟台` 内部实际使用的子组件(模拟台运行盘是自绘的，二者代码独立)，但视觉/数据语义同源，落地时应抽成共享组件复用。

---

## ① 整体布局骨架（区域树 + 尺寸）

### 模拟台.dc.html
```
<body #1c1b19, JetBrains Mono, color #e6e1d6, font 13.5px/1.5>
└ flex column, height 100vh
  ├─ TITLE BAR  (flex:none, h=42px, pad 0 14px, bg #201f1c, border-bottom 1px #302d29)
  │   ├ 3× 假红绿灯圆点 (11px, #3a3733)
  │   ├ ✳(#d97757) + "QuantBT"(600)
  │   ├ 台 SWITCHER (pill 组: bg #1a1916, border #302d29, radius 8px, pad 3px)
  │   │    因子台 / Model台 / 策略台 / [模拟台=active: bg #9bbd5a, color #16200f, 700]
  │   ├ spacer flex:1
  │   ├ MARKET SWITCH (pill: A股 / 加密, active bg #9bbd5a)
  │   └ clockLabel (11px #5f5b53, "下一收盘 MTM · 16:00 CST · T−2h14m")
  ├─ SUB-TAB BAR (flex:none, pad 8px 16px, bg #1a1916, border-bottom #302d29)
  │   ├ ▦运行盘 ⊞持仓与成交 ⛨风险门 ↺复盘归因 ⤴晋升通道  (tab btns)
  │   ├ spacer
  │   ├ subHint (11px #6f6a61)
  │   └ "MOCK 数据" badge (9.5px #9bbd5a, border #3c5230, radius 20px)
  └─ BODY (flex:1, min-height:0, display flex)
     ├ RUN LIST 侧栏 (collapsible)
     │   ├ 折叠态: w=34px, vertical-rl "模拟盘 ›"
     │   └ 展开态: w=288px, border-right #302d29
     │       ├ header (pad 9 13, "模拟盘" + runCountLabel + ‹折叠)
     │       ├ scroll list (pad 8): run 卡片 ×N
     │       │     卡片: pad 9 11, radius 9, active border #3c5230 / bg #1c2018
     │       │       row1: status dot + name(600,12px) + stat(9px)
     │       │       row2: market + "第 N 周" + total%(600)
     │       └ footer (10px #6f6a61: "A股止于 paper · 唯一硬墙在交易所侧远程信任域")
     └ MAIN (flex:1, overflow-y auto, bg #191815)
         └ 5 个 sc-if 互斥视图，每个 pad 18px 22px, max-width 840–900px
             RUN / BOOK / RISK / REVIEW / PROMO
```

### PaperBoard.dc.html
```
<x-dc>
└ CARD (bg #1d1c19, border 1px #34302a, radius 11px, overflow hidden)
  ├ HEADER (pad 11 15, bg #221f1c, border-bottom #302d29)
  │   pulse dot(#7fa650) + "模拟盘 · {strategy}" + "运行中 · 第 N 周" chip(右, #9bbd5a)
  ├ LIVE METRICS (flex, pad 13 15 9): 今日盈亏 / 累计收益 / 超额(vs 500)  各 20px/700
  ├ NAV CHART (pad 2 15 10): svg h=88px, hist灰 #5f5b53 + paper橙 #d97757 + split 虚线
  ├ POSITIONS (pad 2 15 10): "当前持仓 · top N" + 行 ×4 (name/sym/w/pnl)
  └ RISK GATE (pad 11 15, bg #1a1916, border-top #302d29)
       ⛨ "风险门·会话外不可改" + gateStatus + 4 格 flex-wrap (各 flex 1 1 44%)
       脚注: "A股止于 paper — 唯一硬墙在交易所侧远程信任域;本地门仅为防篡改证据,非防篡改。"
```

---

## ② 每个面板/区块职责 + 关键视觉值

### 模拟台 — RUN VIEW（运行盘，默认视图）
- **header**: pulse 状态点(9px, ring 3px `r_statRing`, `animation:ppulse 2s`) + name(17px/700) + origin(11px #6f6a61, 例 "策略台 · strat_wk_cn_01") + 右侧 status chip(radius 20px)。
- **live metrics**(grid 4列, gap 11): 卡 bg `#1d1c19`, border `#302d29`, radius 10, pad 11 14；label 10.5px #7d7668 / value **21px/700**(涨绿 `#9bbd5a` 跌红 `#d97066` 平 `#cfc8ba`) / note 9.5px #6f6a61。4 指标=今日盈亏 / 累计收益 / 超额 vs bench / 年化·夏普。
- **equity chart**: 卡同上 radius 10；标题"净值曲线 · equity log" + "mark_to_market 每收盘写一笔" + 右 "vs {bench}"(#9bbd5a)。SVG viewBox `0 0 720 200`, h=180px：split 竖虚线(`#4a433a` dash 3 3) + bench 虚线(`#5f5b53`) + 回测段实线(`#6f6a61` 1.6) + **实盘段绿线(`#9bbd5a` 2.2)** + 绿色面积(`rgba(155,189,90,0.10)`)。轴注：← 回测段 / ▏模拟盘上线 / 实盘段 →。
- **scheduler + positions**(flex 横排, gap 14)：
  - 左 flex 1.1 — **调度器 · PaperScheduler**：标题带绿 ⟳ + 右 `r_schedState` 活跃/暂停(带 `pblink` 呼吸点)。KV 列表(每行 border-bottom #221f1c)直接映射后端 `PaperSchedulerState`：running / bar_interval / bars_fed / mtm_count / last_bar_at / last_mtm_at / last_error。
  - 右 flex 1 — **持仓速览**(top N)：name(flex1.6 省略号) / w(flex0.8) / pnl(flex0.9, 涨绿跌红 600)。

### 模拟台 — BOOK VIEW（持仓与成交）
- **balance strip**(grid 4): 总权益 / 可用现金 / 持仓市值 / 冻结挂单(value 17px/700, A股 ¥ vs 加密 $)。
- **positions table**: 卡 overflow hidden；表头行 bg `#211f1c`；列 标的(1.8)/权重(1)/数量(1)/成本(1.1)/现价(1.1)/浮盈(1)；标的双行(name #cfc8ba + sym 9.5px #6f6a61)；浮盈 600 涨绿跌红。注："等权多头 · 已 MTM"。
- **fills**(成交回报): 同卡式；列 时间(1.3)/标的(1.6)/方向(0.7,买绿卖红)/数量(1)/成交价(1)/费用(1)。注："feed_bar 撮合 · 含滑点+手续费"——直连后端 `paper_venue.feed_bar()`。

### 模拟台 — RISK VIEW（风险门 · 治理核心）
- 标题 ⛨(#9bbd5a 15px) + **"风险门 · 会话外不可改"**(16px/700) + 右 status chip(全绿·1预警)。
- 说明(11px #8f897c): 门限发布时冻结，**Agent 在会话中永不可改**(`永不可改`=#d99a8e)；"本地门仅为防篡改证据(非防篡改)——A股唯一硬墙在交易所侧远程信任域"。
- **gate grid**(2列): 每格 border 动态(超限红 `#5a3a36` 否则 #302d29)；含 k / lock(🔒冻结=#d9b25f) / cur(18px/700)·限 limit / 进度条(h5px, fill=门色)。6 门：单笔名义上限/杠杆/周换手/回撤熔断/单行业暴露/单票上限。
- **violation log**: ≣ "违规日志 · 防篡改证据链" + "append-only · 哈希链"；时间线(圆点+连线)，每条 title/detail/when·hash(0x7af3…21bc)。

### 模拟台 — REVIEW VIEW（复盘归因）
- **回测预期 → 模拟实盘**表：指标 / 回测段 / 模拟段 / **实盘衰减**(decay 色：劣化 #d9b25f / 好于预期 #9bbd5a / 换手升 #d97066)。底注 bullet box(border-left 3px #d9b25f)。
- **超额因子归因**: 居中 0 轴的横向双向条(`left/width` 计算, 正绿负红)，左右轴注 −贡献/0/+贡献。
- **cost drag**(grid 3): 滑点拖累 / 手续费 / 未成交损失(value 17px/700, 红/黄)。

### 模拟台 — PROMOTION VIEW（晋升通道 · live ladder UI 核心）
- 说明：与因子台五态机联动 `PROBATION → 模拟实盘 1月年化>基准 → OBSERVATION`；**Agent 永不自动晋级，须人工审批 + 验证背书(INV-5)**。
- **pipeline**: 4 阶段节点(圆 34px；current=实心绿+ring，reached=描边绿，未达=#211f1c 灰描边) + 箭头连线(达成绿/未达 #34302a)。阶段=QUALIFIED→PROBATION→模拟实盘→OBSERVATION。
- **gate check 卡**(border `pm_gateBorder`): header "晋级判定 · {name}" + 右 elig chip。4 检查项(图标✓/○/✕ + 文 + 值)：运行≥28天 / 模拟段年化>基准 / 风险门0违规 / 实盘衰减<30%。**审批按钮**`pm_approve`(三态：可点绿实心 / 已晋级描边只读 / 不可点灰 not-allowed) + hint。
- **factor lifecycle linkage**: 本策略因子表(state 色：OBSERVATION/PROBATION=#d9b25f, QUALIFIED=#6f9bd1) + "去因子台 ↗"(链 `因子台.dc.html`, #a98fd4)。

---

## ③ 状态模型（`{{}}` 变量清单 + TS interface 草拟）

### 模拟台 React state（真实可变状态，仅 5 个）
```ts
interface PaperDeskState {
  view: "run" | "book" | "risk" | "review" | "promo";   // 子 tab
  market: "equity_cn" | "crypto";                        // 市场切换
  selRun: string;                                        // 当前选中 run id
  listOpen: boolean;                                     // 侧栏折叠
  promoted: boolean;                                     // 晋升 demo 标志(本地)
}
```

### `{{}}` 绑定全清单（renderVals 派生）
顶栏/导航：`mktBtns[] clockLabel`，子tab：`goRun/goBook/goRisk/goReview/goPromo tabRun/tabBook/... viewRun/viewBook/... subHint`，侧栏：`listOpen listCollapsed listToggle runCountLabel runList[]`。
RUN：`r_name r_origin r_bench r_statDot r_statRing r_statColor r_statBg r_statText r_metrics[] r_histPath r_paperPath r_paperArea r_benchPath r_splitX r_sched[] r_schedState r_posPreview[] r_posCount`。
BOOK：`bk_balance[] bk_positions[] bk_posCount bk_fills[]`。
RISK：`rk_gates[] rk_status rk_statColor rk_statBg rk_statBorder rk_log[]`。
REVIEW：`rv_rows[] rv_note rv_attr[] rv_excess rv_cost[]`。
PROMO：`pm_stages[] pm_gateBorder pm_elig pm_eligColor pm_eligBorder pm_checks[] pm_approve pm_approveStyle pm_approveLabel pm_approveHint pm_factors[]`。

### 建议的领域 TS 接口（落地用，含与后端字段对齐标注）
```ts
// —— 直接映射 PaperSchedulerState (scheduler.py:46) ——
interface PaperRunStatus {
  strategy_id: string;
  running: boolean;
  started_at_utc: string | null;
  last_bar_at_utc: string | null;
  last_mtm_at_utc: string | null;
  bars_fed: number;
  mtm_count: number;
  last_error: string | null;
}
// —— scheduler.snapshot() 顶层 ——
interface PaperSnapshot extends PaperRunStatus {
  balance: Record<string, { asset: string; free: number; locked: number }>;
  positions: Record<string, { quantity: number; entry_price: number; mark_price: number }>;
  config: { strategy_id: string; symbols: string[]; interval_seconds: number; market: "equity_cn" | "crypto" };
}
interface PaperRun {                          // 侧栏 + 头部
  id: string; name: string; origin: string;   // origin = "策略台 · strat_xxx"
  market: "equity_cn" | "crypto";
  status: "running" | "paused" | "stopped";
  days: number; bench: string;
  total: number; today: number; excess: number;
}
interface PaperMetric { label: string; value: string; color: string; note: string }
interface PaperPosition {                      // BOOK; 来自 paper_venue Position + MTM
  name: string; sym: string; w: string; qty: string;
  entry: string; mark: string; pnl: string;
}
interface PaperFill {                          // 来自 feed_bar() 回报 / ExecutionAuditLog "paper_fill"
  time: string; sym: string; side: "买" | "卖";
  qty: string; price: string; fee: string;
}
interface RiskGate {                           // 治理冻结门
  k: string; cur: string; limit: string; pct: string;
  color: string; lock: "🔒 冻结" | "";
}
interface RiskViolation { title: string; detail: string; when: string; hash: string; color: string }
interface ReviewRow { k: string; bt: string; paper: string; decay: string; decayColor: string }
interface AttrBar { name: string; val: string; color: string; left: string; width: string }
interface PromoStage { label: string; sub: string; glyph: string; reached: boolean; current: boolean }
interface PromoCheck { t: string; v: string; icon: string; color: string }
interface PromoFactor { id: string; state: "QUALIFIED"|"PROBATION"|"OBSERVATION"; w: string; contrib: string }
```

### PaperBoard props
```ts
interface PaperBoardProps {
  board?: {
    strategy?: string; days?: number;
    pnlToday?: number; totalReturn?: number; excess?: number;
    hist?: number[]; paper?: number[];                    // 净值序列
    positions?: { name: string; sym: string; w: string; pnl: number }[];
    risk?: { maxNotional?: string; leverage?: number; turnover?: string; ddHalt?: string };
  };
}
```

---

## ④ 交互清单（所有 handler 行为）

| handler | 触发 | 行为 | 真实/演示 |
|---|---|---|---|
| `mktBtns[].on` | 点 A股/加密 | `setState({market})` 切市场，全数据(余额/持仓/clock)随之换 ¥↔$、收盘时钟 | 演示(本地 mock) |
| `goRun/goBook/goRisk/goReview/goPromo` | 点子 tab | `setState({view})` 切互斥视图 | 本地 |
| `listToggle` | 点侧栏 ‹ / 折叠条 | `setState({listOpen: !listOpen})` | 本地 |
| `runList[].select` | 点 run 卡片 | `setState({selRun: r.id})` 切当前 run | 本地(需接 `/api/paper/runs`) |
| `pm_approve` | 点"⤴ 人工审批晋级" | 仅当 `canPromote`(eligible && !promoted) 时 `setState({promoted:true})`；按钮三态切换文案+样式，并把首个因子 state PROBATION→OBSERVATION | **演示——真实需 POST 审批端点(缺)** |

> 关键缺口：模拟台**没有 start/stop/重启调度器、kill switch、暂停 run 的 handler**——这些是 GOAL §5 要求的运行控制(kill switch 分级)。设计稿是只读 dashboard + 一个 demo 审批。`PaperBoard` 完全无 handler(纯展示卡)。

---

## ⑤ 治理 / 业务元素专章（这是本页的灵魂，对齐 GOAL §5/INV-5/R13/R24-R25）

1. **风险门「会话外不可改」**(RISK view + PaperBoard 底部)：门限策略发布时冻结写哈希，**Agent 会话内永不可改**，改动请求被拒并入哈希链日志。直接呼应 GOAL §2「安全 deny-by-default + 交易所侧硬墙」+ INV「不削弱安全不变量」。视觉用 🔒冻结 标记杠杆/回撤熔断两条硬门。
2. **「A股止于 paper · 唯一硬墙在交易所侧远程信任域」**(侧栏 footer + RISK 说明 + PaperBoard 脚注，出现 3 次)：精确对齐 GOAL §5 验收「**A股 live 下单永远拒**」+ R13(A股纯多头弱腿) + RULES「致命错误：A股 live 下单」。诚实声明本地门=防篡改证据**非防篡改**(不假绿灯，对齐 §3 硬不变量)。
3. **晋升通道 = live ladder 的 paper→OBSERVATION 段**(PROMO view)：`QUALIFIED→PROBATION→模拟实盘 1月>基准→OBSERVATION`，**Agent 永不自动晋级须人工 + 验证背书(INV-5)**，4 道判定门(28天/超额/0违规/衰减<30%)。对齐 §5 live ladder「不可跳级」+ §2「HITL 双通道审批」+ §6「恰当依赖非信任最大化」。但注意：设计稿晋升终点是 OBSERVATION(因子生命周期态)，**不是** GOAL §5 ladder 的 `testnet→小额live→加码`——这一段(真钱阶梯)在模拟台未画，属上游 BinanceTradingPage 域。
4. **实盘衰减归因**(REVIEW)：回测↔paper 对账，"样本外打 7-8 折健康区间"，衰减主因=真实滑点>回测假设 + 涨跌停无法成交。对齐 §5 验收「回测↔paper 对账对不上=指向 bug」+ §4 成本/TCA。
5. **防篡改证据链**(违规日志 append-only 哈希链)：对齐 §9 性能架构「append-only JSONL 防篡改审计」+ 后端 `ExecutionAuditLog`。
6. **MOCK 数据 badge**：诚实标注当前是 mock，不假装真实——对齐反谄媚/不假绿灯文化。

---

## ⑥ Design tokens 差异（与策略台 #1c1b19 / #d97757 / JetBrains Mono 对比）

**已确认策略台 token**：bg `#1c1b19`、title bar `#201f1c`、border `#302d29`、品牌 ✳ `#d97757`、字体 JetBrains Mono、文本 `#e6e1d6`。模拟台**完全继承同一套基础 token**(逐字一致)：

| token | 策略台 | 模拟台 | 一致? |
|---|---|---|---|
| page bg | #1c1b19 | #1c1b19 | ✅ |
| title bar bg | #201f1c | #201f1c | ✅ |
| border | #302d29 | #302d29 | ✅ |
| 字体 | JetBrains Mono | JetBrains Mono | ✅ |
| text 主 | #e6e1d6 | #e6e1d6 | ✅ |
| 卡片 bg | #1d1c19 | #1d1c19 | ✅ |
| 品牌 ✳ | **#d97757(橙)** | **#d97757(橙)** | ✅(仅 title bar logo) |
| **active/主强调色** | **#d97757 橙**(策略台 tab active = 橙底) | **#9bbd5a 绿**(模拟台 tab/晋升/净值全绿) | ⚠️ **差异** |
| 涨/正 | #9bbd5a | #9bbd5a | ✅ |
| 跌/负 | #d97066 | #d97066 | ✅ |
| 警告/黄 | #d9b25f | #d9b25f | ✅ |
| 字号基准 | 13px | 13.5px | △ 微差 |
| title bar 高 | 44px | 42px | △ 微差 |

**核心 token 差异 = 主强调色**：策略台用**品牌橙 `#d97757`** 作 active/CTA；模拟台改用**绿 `#9bbd5a`** 贯穿(台 switcher active、净值实盘段、晋升节点、风险全绿、审批 CTA)。语义化合理——绿=「运行中/已上线/安全放行」，契合模拟盘"live & green-light"主题。**内部矛盾点**：`模拟台`净值实盘段用绿 `#9bbd5a`，而 `PaperBoard` 同一段用品牌橙 `#d97757`(且 pulse dot 用 `#7fa650`/动画名 `ccpulse` 而非模拟台的 `ppulse`)——两文件实盘色不统一，落地时需二选一(建议统一为绿，与"模拟盘运行中"语义一致)。补充独有 token：紫 `#a98fd4`(跨台链接)、蓝 `#6f9bd1`(因子 QUALIFIED 态)、绿 active 文字 `#16200f`。

---

## ⑦ 对应现有前端 + 落点建议 + 后端缺口

### 现有前端映射（graphify 确认）
- **没有对应页面**。`app/frontend/src/pages/` 26 个页面中**无 paper/simulator/模拟台**。最接近的是 `workshop/BinanceTradingPage.tsx`(路由 `/trading`)，但它是**完全不同的关注点**：它管 keystore 写入 / testnet↔mainnet 二次确认 / risk monitor + kill switch ——即 live ladder 的**真钱阶梯段(testnet→mainnet)**，而设计稿模拟台管的是 **paper 段(运行/持仓/风险门/复盘/晋升)**。二者是 ladder 上**相邻但不重叠**的两段。
- App.tsx 路由表无 `/paper`；台 switcher 链向 `因子台/Model台/策略台/模拟台`，但前端实际页面是 `factors/models/workshop/...`——设计稿的"四台"导航尚未在 React 路由实装。

### 落点建议
1. **新建** `app/frontend/src/pages/workshop/PaperDeskPage.tsx`(或 `simulator/`)，路由 `/paper` 或 `/simulator`，对应模拟台全页。**不要塞进 BinanceTradingPage**——职责不同(paper 监控 vs 真钱密钥/网络切换)，且 BinanceTradingPage 用的是 `cc-*` 类名体系(亮色 token `--cc-*`)，与设计稿暗色 token 体系不同。
2. **抽共享卡片** `components/PaperBoardCard.tsx`(对应 PaperBoard.dc.html)，供策略台/首页/跟单页复用；模拟台 RUN view 的运行盘也复用它。
3. **复用** BinanceTradingPage 已有的 kill switch (`POST /api/risk/kill_switch`) 与 risk alerts (`/api/risk/alerts`)——模拟台 RISK view 的"违规日志/熔断"应接 `RISK_MONITOR`，避免重复实现。
4. **真钱阶梯衔接**：模拟台 PROMO 的 OBSERVATION 之后，应跳转/链向 BinanceTradingPage(testnet→mainnet)，把 ladder 两段串起来——设计稿目前止于 OBSERVATION，未画此衔接。

### 后端端点缺口（落地必补）
| 设计稿需要 | 后端现状 | 缺口 |
|---|---|---|
| `GET /api/paper/status`(调度器状态) | scheduler.py docstring 写了要 expose 给此端点，但 **main.py 中无任何 `/api/paper/*` 路由** | **缺：整组 paper API 未挂载**。`PaperScheduler.snapshot()` / `PaperSchedulerState` 数据结构已就绪，只差 FastAPI 路由 + 进程常驻 wiring |
| `POST /api/paper/start` `/stop` `/runs`(列表+选择) | 无 | **缺**。scheduler 有 `start()/stop()/tick_once()/mtm_once()` 但无 HTTP 暴露；且当前无"多 run 管理"(scheduler 是单策略实例) |
| BOOK: 持仓/成交/余额 | `paper_venue` 有 `get_balance()/get_position()/feed_bar()` + `ExecutionAuditLog`(paper_place/paper_fill 事件) | **缺**：成交回报 list 端点(从 audit log 派生 fills)、持仓表端点 |
| RISK: 冻结门 + 违规哈希链 | `/api/risk/alerts` + `RISK_MONITOR` + `RiskLimits` 存在；kill switch 存在 | **部分**：缺"门限发布冻结哈希"持久化 + append-only 违规链端点 |
| REVIEW: 回测↔paper 衰减对账 | 无专门端点(回测侧 PBO/DSR 在 §4 已建) | **缺**：paper vs backtest decay 对账端点 |
| PROMO: 人工审批晋级 | 有 `factor_factory/lifecycle.py`(`LifecycleManager.evaluate()` / `evaluate_transition()` PROBATION→OBSERVATION 状态机) + `/api/factors` | **缺**：晋级判定聚合端点(28天/超额/0违规/衰减 4 门) + **人工审批 POST 端点**(须 approver≠creator + 验证背书, INV-5)；lifecycle 引擎在但未接 HTTP 审批门 |
| 净值曲线(equity log) | `paper_venue.mark_to_market()` 写 JSONL `equity_log_path` | **缺**：读 equity log 的端点(供净值图) |

**一句话**：后端核心引擎(`PaperVenue` 撮合/MTM/audit + `PaperScheduler` 状态机 + `LifecycleManager` 五态机 + risk/killswitch)**已具备**，但**整层 `/api/paper/*` HTTP 路由与"多 run 管理 / 晋级审批门"未实装**——这是模拟台落地的最大后端工作量。

---

## 相关文件路径（绝对）
- 设计稿：`/tmp/qbt-handoff/quantbt-claude/project/模拟台.dc.html`、`/tmp/qbt-handoff/quantbt-claude/project/PaperBoard.dc.html`、参照 `/tmp/qbt-handoff/quantbt-claude/project/策略台.dc.html`
- 后端引擎(已建)：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/paper/scheduler.py`、`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/execution/paper_venue.py`、`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/factor_factory/lifecycle.py`、`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/risk/checks.py`
- 后端路由(缺 paper)：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/main.py`(risk/security 端点在 L925–1146、L1454–1498；无 `/api/paper`)
- 现有前端：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/pages/workshop/BinanceTradingPage.tsx`(路由 `/trading`)、`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/App.tsx`(路由表，无 `/paper`)
- 落点(建议新建)：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/pages/workshop/PaperDeskPage.tsx` + `components/PaperBoardCard.tsx`
- 治理依据：`/Users/wzy/Work/01_Projects/QuantBT/dev/GOAL.md` §5(L45–49)