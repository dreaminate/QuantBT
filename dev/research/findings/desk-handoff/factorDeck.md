I now have a complete picture: design file fully read, existing frontend page read, backend factor module and routes mapped, GOAL §3 confirmed. The backend has only 3 factor routes (`/api/factors/operators`, `/api/factors`, `/api/factors/{id}`); no routes exist for IC decay, correlation, layered backtest, lifecycle event-log, expression validation, registration, or alpha audit — though the underlying compute functions (`compute_ic_decay`, `compile_expression`, `evaluate_on_panel`, `LifecycleManager.events`) exist in the module and are not HTTP-exposed.

Here is the structured analysis.

---

# 因子台 (FactorDesk) 设计稿逐行分析

源文件: `/tmp/qbt-handoff/quantbt-claude/project/因子台.dc.html` (852 行)
对照前端: `/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/pages/workshop/FactorMarketPage.tsx` (167 行)
对照后端: `/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/factor_factory/` + `app/backend/app/main.py`

---

## ① 整体布局骨架 (区域树 + 尺寸)

```
x-dc 根 (display:flex column; height:100vh; bg #1c1b19; color #e6e1d6; 13.5px; line-height 1.5)
│
├─ TITLE BAR (flex:none; h 42px; pad 0 14px; bg #201f1c; border-bottom 1px #302d29)
│   ├─ 3× 红绿灯圆点 (11×11; radius 50%; #3a3733)
│   ├─ ✳ logo (#d97757) + "QuantBT" (600)
│   ├─ 台 SWITCHER (bg #1a1916; border #302d29; radius 8px; pad 3px)
│   │    因子台[active] / Model台 / 策略台 / 模拟台 — pill 11.5px; active bg #a98fd4 文字 #1c1726
│   ├─ flex:1 spacer
│   ├─ 市场切换 mktBtns (A股 / 加密) — pill 10.5px; active bg #a98fd4
│   └─ poolLabel (11px #5f5b53) — "中证全 A · 4870 标的 · 周频"
│
├─ SUB-TAB BAR (flex:none; pad 8px 16px; bg #1a1916; border-bottom 1px #302d29)
│   ├─ 5 tabs: ▤因子库 / ⊞相关性 / ⚖评测台 / ⌨构建台 / ⚗研究台
│   ├─ flex:1 spacer
│   ├─ subHint (11px #6f6a61) — 随 view 变
│   └─ "MOCK 数据" badge (9.5px #a98fd4; border #4a4060; radius 20px)
│
└─ BODY (flex:1; min-height:0; display:flex) — 5 个互斥 sc-if view
    ├─ LIBRARY  : [因子列表 312px (可折叠→34px)] + [因子详情 flex:1; bg #191815; pad 18px 22px; max-width 820px]
    ├─ CORR     : 单列 (flex:1; bg #191815; pad 20px 24px; max-width 1000px) → [矩阵 flex:none] + [去冗余侧栏 flex:1 min 260px]
    ├─ EVAL     : 单列 (flex:1; pad 18px 22px; max-width 920px)
    ├─ BUILD    : [agent chat 330px; bg #1a1916] + [DSL 编辑器 flex:1; bg #191815] + gate modal (absolute inset:0)
    └─ RESEARCH : [审查 chat 336px; bg #1a1916] + [审查报告 flex:1; pad 18px 24px; max-width 780px]
```

布局范式与策略台一致: 顶部 42px title bar + 台 switcher、二级 tab bar、左栏固定宽 + 右栏 flex:1 滚动、聊天区固定 ~330px。两个 view (构建台/研究台) 是 Claude-Code 风格的左聊天右工作区双栏。

---

## ② 每个面板/区块职责 + 关键视觉

### A. 因子库 view (viewLib) — 主入口

**左: 因子列表 (width 312px; border-right 1px #302d29)**
- 折叠态: width 34px; 竖排文字 `因子库 ›` (writing-mode vertical-rl; 11px #8f897c; letter-spacing 1px); 点击展开
- 头部 (pad 9px 13px): "因子库" + factorCountLabel ("16 因子") + ‹ 折叠键
- 生命周期 filter 行 (flex-wrap; gap 4px; pad 8px 11px): 7 个 pill `全部/NEW/QUALIFIED/PROBATION/OBSERVATION/WARNING/RETIRED` + 计数; 9.5px; radius 11px; active border+文字用状态色
- 因子卡列表 (overflow-y auto; pad 8px): 每卡 pad 9px 11px; radius 9px; 选中 border #5a4a6a / bg #211c26, 否则 border #262320 / bg #1d1c19
  - 行1: 状态色圆点 (7px; OBSERVATION 态有 `ffpulse` 呼吸动画) + factor_id (600; 12px; ellipsis) + 状态徽标 (9px; radius 9px; 用 stateColor/stateBg)
  - 行2: formula (10px #8a8174; ellipsis)
  - 行3: fam (#6f6a61) + IC (icColor 阈值色) + IR (#7d7668)

**右: 因子详情 (flex:1; bg #191815; pad 18px 22px; max-width 820px)**
1. **Header**: factor_id (17px 700) + v{version} + 因子族徽标 (famColor/famBg; radius 12px) | 右上: 状态 (11px 700 stateColor) + 入库日期
2. **formula box**: 12px #9bb3c9; bg #1b2330; border #2c4452; radius 7px (蓝色"代码"质感, 全台统一)
3. **因子五态机生命周期** (bg #1d1c19; border #302d29; radius 10px; pad 14px 16px): 标题 "◷ 因子五态机 · M11 生命周期" + 副标 "阈值参数化 · 每次评估写 event_log"; 6 个节点横向等分:
   - 节点圆 30×30: active=填充状态色+`box-shadow 0 0 0 4px {c}33`; passed=透明描边; future=#211f1c 灰
   - glyph: NEW`○` QUALIFIED`✓` PROBATION`◐` OBSERVATION`◉` WARNING`!` RETIRED`×`
   - 节点间连线 + 阈值标注 (8px): `IC>.03·IR>.5` / `3月IC≥0` / `实盘>基准` / `衰减>50%` / `2周未修复`
4. **硬指标 4 卡** (grid 4×1; gap 10px): IC均值 / Rank-IC / IC-IR / sample t; 数值 19px 700; 阈值色 (绿 ≥0.02/≥0.5/≥3, 红 ≤0, 黄边际)
5. **IC 时序 (flex 1.4) + IC 衰减 (flex 1)** SVG:
   - 日度IC: viewBox 0 0 320 110; 柱 = `d_icBars` (stroke 2.4); 白线 = 20日均线 (`d_icMa`); μ 标注
   - 衰减曲线: viewBox 0 0 220 110; 紫线 `d_decayPath` (#a98fd4) + 面积 `d_decayArea` (rgba .12) + 5 dots; x 标签 1/3/5/10/20d
6. **因子动机 (flex 1.2) + event log (flex 1)**:
   - 动机: "✎ 因子动机 · 想抓什么 alpha"; 引述块 (bg #211c26; border-left 3px #a98fd4); 4 元数据格 (算子链/截面时序/换手代理/前视检查✓无穿越)
   - event log: "≣ lifecycle_event_log"; 竖时间线 (9px 圆点 + 连线), 每条 `{from} → {to}` + reason + when

### B. 相关性 view (viewCorr) — 拥挤度 / 去冗余

- 说明: "因子相关矩阵 · 拥挤度与去冗余 · Spearman rank-corr, {window}"
- **矩阵** (9×9; cell 38×30px): 对角线 `·` (#3a3733); 正相关红系 `rgba(217,112,102,α)`, 负相关蓝系 `rgba(111,155,209,α)`, α=0.12+|ρ|·0.7; |ρ|>0.7 红框 #6a3a36; 点击开配对详情
- 图例: 渐变条 `−1 [蓝→灰→红] +1` + "■ |ρ|>0.7 冗余"
- **右侧栏** (flex:1; gap 12px):
  - 配对详情 (pairOpen 时; border #4a4060): pairA vs pairB + ρ (24px 700; pairColor) + verdict (>0.7 红"高度冗余", >0.4 黄"中度", 否则绿"低相关")
  - 冗余簇 (clusters): 每簇 |ρ|≈x + "留 N" 绿徽标 + 成员 (★保留/→淘汰; IR)
  - 组合拥挤度 (crowdRows): 平均|ρ| / 有效独立维度 / 最大簇占比 — 进度条

### C. 评测台 view (viewEval) — IC / 分层回测 / 硬指标

- Header: factor_id + formula + horizon 切换 (1/3/5/10/20d; active bg #a98fd4)
- **硬指标 5 卡** (grid 5×1): IC@{h}d / Rank-IC / IC-IR / 胜率 / 样本期; 17px 700
- **分层回测** (bg #1d1c19; radius 10px): "分层回测 · 五分位累计净值"; SVG viewBox 0 0 460 200; 5 条线 (Q1 蓝 #6f9bd1 → Q5 绿 #9bbd5a; Q1/Q5 粗 2.2 中间 1.4); 右侧图例 + 各组收益 + 多空 Q5−Q1 spread; 单调性判定 (>3%绿"单调性好"/>0黄"弱单调"/≤0红"无单调性")
- **IC序列累计 (flex 1.3) + IC衰减表 (flex 1)**: 累计IC紫线; 衰减表 (horizon/IC/Rank-IC/IR 四列, 选中行 #a98fd4)

### D. 构建台 view (viewBuild) — DSL + Claude Code

- **左 agent chat (330px; bg #1a1916)**: 头 "✳ 因子 Agent · Claude Code · DSL 即代码"; 消息 4 型: user(`>` #a98fd4) / think(`✻` 斜体 #8a7e6a) / say(`●`) / patch(代码卡 bg #211c26 border #4a4060); 底部 chips (加一层截面rank/降换手/IC衰减检查) + textarea (placeholder "描述想抓的 alpha…") + ↵ 按钮
- **中 DSL 编辑器 (flex:1; bg #191815)**: 头 "⌨ 表达式编辑器 · factor_factory.expression · polars 编译" + 校验状态 (bdValid)
  - formula box (蓝 #1b2330; 16px #cfe2f0)
  - **算子库 palette** (bdOpGroups): 4 组 (时序ts_* / 截面cs_* / 逐元素 / 字段); 点击插入 token; 蓝色 chip
  - **AST 解析树** (bdAst): 缩进树, 字段绿 / 数字黄 / 算子蓝
  - **即时IC预览 (flex 1) + lint 侧栏 (230px)**: IC预览SVG (60日样本内) + bdLints (前视✓/量纲✓/换手△) + "⊕ 注册到因子库" 按钮
- **gate modal** (absolute inset:0; bg rgba(10,9,8,.6)): "⊕ 注册因子 · 进入五态机"; 初始 NEW; 3 检查 (编译通过/前视/无重名) + ✓注册/取消

### E. 研究台 view (viewResearch) — alpha 真伪审查

- **左 chat (336px)**: "⚗ 学术审查 · academic audit"; user/say 两型; placeholder "质询这个因子是否真 alpha…"
- **右 审查报告 (max-width 780px)**: factor_id + verdict 徽标 (真alpha绿/存疑黄/未通过红) + summary
  - **审查 checks 5 条**: 多重检验校正(Bonferroni/BHY) / 数据窥探p-hacking / IC显著性t检验(Newey-West) / IC衰减半衰期 / 经济学先验; 每条 icon+title+stat+detail
  - **相关文献 3 篇**: De Bondt&Thaler 1985 / Jegadeesh&Titman 1993 / Harvey-Liu-Zhu 2016; title+venue+ref+gist+借鉴

---

## ③ 状态模型 (state 变量 + TS interface 草拟)

**DC state (line 443-460):**
```
view: "library"|"corr"|"eval"|"build"|"research"   // 主 view
market: "equity_cn"|"crypto"
selFactor: string                                   // 选中 factor_id
listOpen: boolean; lifeFilter: "ALL"|<6态>
corrPair: [idA, idB, rho] | null
evalHorizon: 1|3|5|10|20
bdExpr, bdFactorId, bdDraft: string; bdGateOpen: boolean
bdChat: {role:"user"|"think"|"say"|"patch", text, code?}[]
rsDraft: string; rsChat: {role:"user"|"say", text}[]
```

**TS interface 草拟 (对齐后端 to_dict 真实字段):**
```ts
type LifecycleState = "NEW"|"QUALIFIED"|"PROBATION"|"OBSERVATION"|"WARNING"|"RETIRED";
type FactorFamily = "动量"|"反转"|"波动"|"量价"|"形态";  // 设计稿自造, 后端无此字段 ⚠
type Market = "equity_cn"|"crypto";

// 后端 Factor.to_dict() 真实字段 (registry.py L27-39):
interface FactorItem {
  factor_id: string; version: number; formula: string;
  author: string; created_at_utc: string; description: string;
  lifecycle_state: LifecycleState;
  params: Record<string, unknown>;
  ic_summary: ICSummary | null;          // 当前前端只用 ic_mean/rank_ic_mean
}
// 后端 ICReport.to_dict() (ic.py L19-37):
interface ICReport {
  horizon: number; ic_mean: number; rank_ic_mean: number;
  ic_ir: number; rank_ic_ir: number; sample_count: number;
  by_period: { ts:string; ic:number; rank_ic?:number }[];   // ← 设计稿日度IC柱来源
}
// 后端 LifecycleEvent.to_dict() (lifecycle.py L57-67):
interface LifecycleEvent {
  factor_id:string; version:number;
  from_state:LifecycleState; to_state:LifecycleState;
  happened_at_utc:string; reason:string;        // ← 设计稿 event log 来源 (但无 HTTP 端点)
}
// 后端 list_operators() (operators.py L249): {name, arity} — 设计稿 sig/group 是前端补的
interface OperatorMeta { name:string; arity:number; }

// 设计稿独有、后端无对应数据源 (纯 mock):
interface DecayPoint { h:number; ic:number; rank_ic:number; ir:number; }   // compute_ic_decay 有但未暴露
interface LayeredBacktest { quantiles: number[][]; spread:number; monotonic:boolean; }  // 后端完全无
interface CorrCell { a:string; b:string; rho:number; }                      // 后端完全无
interface RedundancyCluster { rho:number; keep:string; members:{id,ir,role}[]; }  // 后端完全无
interface AlphaAudit { verdict:"真alpha"|"存疑"|"未通过"; checks:AuditCheck[]; papers:Paper[]; }  // 后端完全无
```

关键漂移: 设计稿用 `factor_family`(动量/反转/...) 和 `ic_summary.ic_mean` 的丰富衍生 (IC-IR / sample_t / decay / layers) — 后端 `Factor` 无 family 字段, `ic_summary` 只是一个 dict (内容由 `set_ic_summary` 写入, schema 未约束)。

---

## ④ 交互清单 (所有 handler)

**Shell:**
- `mktBtns[].on` → setState market (A股/加密), 切换 poolLabel + corrWindow
- `goLib/goCorr/goEval/goBuild/goResearch` → setState view (5 tab)

**因子库:**
- `listToggle` → 折叠/展开左列表
- `lifeFilters[].on` → setState lifeFilter (按生命周期态过滤列表)
- `factorList[].select` → setState selFactor (切换详情)

**相关性:**
- `corrRows[].cells[].on` → setState corrPair=[a,b,v] (开配对详情)
- `pairClose` → corrPair=null

**评测台:**
- `horizonBtns[].on` → setState evalHorizon (1/3/5/10/20d, 切换硬指标/衰减表选中行)

**构建台:**
- `bdOpGroups[].ops[].on` → `insert(token)` 把算子/字段追加进 bdExpr (智能加空格)
- `bdOnDraft/bdOnKey/bdSend` → `_bdAsk(text)` 追加 user+say 消息 (mock 回复)
- `bdChips[].on` → `_bdAsk(预设 query)`
- `bdGate` → bdGateOpen=true; `bdGateNo` → false; `bdGateYes` → `_bdRegister()` (追加 "✓已注册...NEW" 消息)
- 隐含校验: `bdValid` 实时检测括号配平 (split("(")==split(")"))

**研究台:**
- `rsOnDraft/rsOnKey/rsSend/rsChips` → `_rsAsk(text)` (mock 学术审查回复)

全部 handler 当前都是纯前端 mock (setState 拼接消息 / 切换状态), 无任何真实 fetch。

---

## ⑤ 治理 / 业务元素专章 (与 GOAL §3 / §4 对照)

设计稿在治理面做得相当扎实, 这是它最有价值的部分:

| 治理元素 | 设计稿落点 | GOAL 对照 | 后端现状 |
|---|---|---|---|
| **五态机生命周期** | 因子库详情顶部全宽组件, 阈值标注 (IC>.03·IR>.5 / 3月IC≥0 / 实盘>基准 / 衰减>50% / 2周未修复) | §3 机构级因子生命周期 (衰减/拥挤/容量/退役); M11 | ✅ `LifecycleThresholds`(L27-35) 阈值完全吻合; `evaluate_transition` 已实现 |
| **lifecycle_event_log** | "每次评估写 event_log" + 详情页时间线; from→to+reason+when | §3 跨策略复用独立资产; 审计 | ✅ `LifecycleEvent` + `LifecycleManager.events()` 存在 ⚠ 无 HTTP 端点 |
| **前视检查 (no look-ahead)** | 动机区 "前视检查 ✓无穿越"; 构建台 lint "无前视: 仅用 ts_* 历史窗口"; gate "前视检查通过·无标签穿越" | §3/§4 防泄露 (purge/embargo) | ⚠ 编译期 `compile_expression` 在, 但显式前视审计未见 |
| **诚实-N 守门人 / 多重检验** | 研究台 "多重检验校正 Bonferroni/BHY", "在 N 个候选中检验, 校正后 p<0.05"; deflated Sharpe | §3 诚实-N (N_eff 必抓); §4 DSR-FST/PBO-CSCV; honest-N (t>3 不硬编) | ❌ 后端完全无 (无审计端点/无 DSR/无 PBO) |
| **IC 显著性 t 检验** | sample t 硬指标 + 研究台 "Newey-West 调整自相关, |t|>3" | §4 t>3 不硬编、三档预注册 | ⚠ `sample_t` 在 `FactorObservation`, 但 Newey-West 调整未见 |
| **拥挤度 / 去冗余** | 相关性 view 全套 (矩阵 + 冗余簇 + 有效独立维度 + 最大簇占比) | §3 拥挤/容量/因子族 | ❌ 后端完全无 corr/拥挤 计算 |
| **因子族 (family)** | 全台用动量/反转/波动/量价/形态 5 族着色 | §3 因子族 | ❌ 后端 `Factor` 无 family 字段 |
| **三纯库 (算术/ML/DL)** | ⚠ **设计稿未体现**: 构建台只做算术表达式 DSL, 无 ML/DL 库入口, 无"信号契约"分层 | §3 核心: 三库纯净 + DL/ML 输出登记为"信号"进因子库 | 后端有 `factor_factory`(算术) ✅, 但 ML/DL→信号契约 未建 |
| **暴力遍历挖掘 + 生成/守门解耦** | ⚠ **设计稿未体现**: 无"因子挖掘"批量遍历 UI (任务描述提到, 设计稿缺) | §3 暴力遍历=诚实-N; 生成器/守门器严格解耦, 守门指标绝不进 fitness | ❌ 后端无挖掘/遍历 |
| **MOCK 数据 诚实标注** | sub-tab bar 右侧常驻 "MOCK 数据" badge | 硬不变量: 未验证≠已验证, 不假绿灯 | ✅ 设计姿态正确 |

诚实评估: 设计稿覆盖了 §3 的"生命周期 + 拥挤度 + 多重检验门槛"三块, 但**漏了 §3 的两个骨干**——(1) 三纯库结构 (算术/ML/DL 分库 + 信号契约), 设计只有算术 DSL; (2) 暴力遍历挖掘界面 (生成器/守门器解耦), 任务标题提到"三纯库: 算术暴力遍历/ML/DL"但稿子里没有对应 view。这是设计稿与 GOAL §3 的最大缺口。

---

## ⑥ Design tokens 差异 (与策略台对照)

完全一致, 同一套设计系统:

| token | 因子台 | 策略台基线 | 一致 |
|---|---|---|---|
| 页面背景 | `#1c1b19` | `#1c1b19` | ✅ |
| 强调色 (Anthropic 橙) | `#d97757` (logo/动量族) | `#d97757` | ✅ |
| 主操作紫 | `#a98fd4` (active/agent/按钮) | `#a98fd4` | ✅ |
| 字体 | JetBrains Mono 400-700 | JetBrains Mono | ✅ |
| 正文色 / 字号 | `#e6e1d6` / 13.5px / lh 1.5 | 同 | ✅ |
| 面板 bg / border / radius | `#1d1c19` / `#302d29` / 10px | 同 | ✅ |
| 工作区 bg | `#191815` | 同 | ✅ |
| 侧栏/chat bg | `#1a1916` | 同 | ✅ |
| 滚动条 | 9px; thumb #3a3733 | 同 | ✅ |
| selection | `rgba(169,143,212,0.30)` | 同 | ✅ |

**因子台特有语义色 (新增, 与策略台不冲突):**
- 状态色: NEW `#8f897c` / QUALIFIED `#6f9bd1` / PROBATION `#d9b25f` / OBSERVATION `#9bbd5a` / WARNING `#e0a050` / RETIRED `#d97066`
- 因子族色: 动量 `#d97757` / 反转 `#6f9bd1` / 波动 `#d9b25f` / 量价 `#9bbd5a` / 形态 `#b89cd8`
- 代码/公式蓝: bg `#1b2330` / border `#2c4452` / 文字 `#9bb3c9`~`#cfe2f0` (全台统一的"表达式即代码"质感)
- 阈值绿/红/黄: 达标 `#9bbd5a` / 不及格 `#d97066` / 边际 `#d9b25f`
- 新动画: `ffpulse` (OBSERVATION 圆点呼吸) / `ffring` (定义了但未使用)

结论: 因子台与策略台/Model台/模拟台是同一设计语言, tokens 零漂移; 仅按因子业务扩展了状态机色板与代码块色, 命名一致。

---

## ⑦ 对应现有前端页面 + 落点建议 + 后端端点缺口

### 现有前端 (graphify 定位)
- `app/frontend/src/pages/workshop/FactorMarketPage.tsx` (community 255; L14 `FactorMarketPage()`, L139 `FactorCard()`, L12 `ORDER`, L3 `FactorItem`)
- 现状: 极简。只有一个 `fetch("/api/factors")` → 按 lifecycle_state 分组的卡片/表格双视图 + 搜索框。无详情、无相关性、无评测、无构建台、无研究台。用 `cc-*` className 体系 (与 dc 稿的 inline style 不同体系)。
- `FactorItem` interface (L3-10) 已对齐后端真实字段子集 (factor_id/version/formula/lifecycle_state/description/ic_summary{ic_mean,rank_ic_mean})。

### 落点建议: **大幅增强 (非新建)**
保留路由 `pages/workshop/FactorMarketPage.tsx` 作为"因子台"容器, 但需要从单页扩成 **5-tab 工作台**。建议结构:
```
pages/workshop/factor/
├─ FactorDeskPage.tsx        // 容器: market 切换 + 5 sub-tab (替换/包裹现 FactorMarketPage)
├─ FactorLibraryView.tsx     // 增强现有: 左列表(可折叠+lifecycle filter) + 右详情(五态机/硬指标/IC图/event log)
├─ FactorCorrView.tsx        // 新: 相关矩阵 + 去冗余 (需新后端)
├─ FactorEvalView.tsx        // 新: 分层回测 + IC衰减表 (部分新后端)
├─ FactorBuildView.tsx       // 新: DSL 编辑器 + 算子 palette + AST + agent chat
└─ FactorResearchView.tsx    // 新: alpha 审查 + chat (需新后端)
```
理由: 现页只覆盖设计稿的"因子库列表"约 20%, 且现页是真实 fetch (非 mock); 删掉重写会丢失已对齐的 `/api/factors` 接线。增强路径可复用现有 `FactorItem`/`FactorCard`/`ORDER` 与 cc-* 样式体系。注意: dc 稿是 inline-style 体系, 落地需转成项目的 cc-* className + CSS 变量 (token 值已一致, 映射成本低)。

### 后端端点缺口 (按设计稿数据需求 vs `main.py` 现状)

**已有 (3 个, 足够支撑因子库列表 + 详情骨架):**
- `GET /api/factors/operators` (L422) → `list_operators()` → `{name, arity}[]` (43 个算子; 注意现前端 subtitle 写"44 个", 实测注册 43 — 数字漂移, 需校准)
- `GET /api/factors` (L428) → 全部因子 to_dict
- `GET /api/factors/{factor_id}?version=` (L434) → 单因子

**缺口 (设计稿需要、后端无 HTTP 端点; 部分计算函数已存在于 module 但未暴露):**

| 设计需求 | 建议端点 | 后端现状 |
|---|---|---|
| 因子详情 IC 日度序列 (`d_icBars`) | `GET /api/factors/{id}/ic?horizon=` | `compute_ic_report().by_period` 已实现, **未暴露** (需 panel 数据源) |
| IC 衰减曲线/表 (`d_decay*`, `ev_decayTable`) | `GET /api/factors/{id}/ic_decay` | `compute_ic_decay()` (ic.py L112) 已实现, **未暴露** |
| 分层回测五分位 (`ev_layers`) | `GET /api/factors/{id}/layered_backtest?horizon=` | ❌ **后端完全无** (需新建 quantile 回测) |
| lifecycle event log (`d_events`) | `GET /api/factors/{id}/lifecycle/events` | `LifecycleManager.events()`/`history()` (lifecycle.py L139-147) 已实现, **未暴露** |
| 相关矩阵 + 去冗余 (`corrRows`/`clusters`/`crowdRows`) | `GET /api/factors/correlation?market=` | ❌ **后端完全无** |
| 表达式实时校验 + 即时IC (`bdValid`/`bdPreview`) | `POST /api/factors/validate` (compile+前视+IC) | `compile_expression`/`parse_expression`/`evaluate_on_panel` (expression.py) 已实现, **未暴露** |
| 注册新因子 (gate `bdGateYes`) | `POST /api/factors` | `FactorRegistry.register()` (registry.py L58) 已实现, **无 POST 路由** |
| alpha 真伪审查 (`rsChecks`: 多重检验/DSR/Newey-West) | `POST /api/factors/{id}/audit` | ❌ **后端完全无** (§4 DSR/PBO 未建) |
| 因子 Agent / 学术审查 chat | `POST /api/factors/agent` (Claude Code) | ❌ 无 (R20 LLM 引导生成暂缓) |
| factor_family 字段 | (扩 `Factor` model) | ❌ `Factor` 无 family 字段, 设计稿全台用它着色 — 需后端补字段或前端从 formula 推断 |
| market 维度 (equity_cn/crypto) | 现 `/api/factors` 无 market 参数 | ❌ registry 无 market 分区 |

**缺口优先级 (从"接近可上线"角度):**
1. 低成本/高价值 (计算已存在, 只缺路由): `ic`、`ic_decay`、`lifecycle/events`、`validate`、`POST /api/factors` — 这 5 个能把"因子库详情 + 构建台"做成真数据。
2. 中成本 (需新建计算): `layered_backtest`、`correlation`/去冗余 — 评测台与相关性 view 的真数据。
3. 高成本/对齐 GOAL §3-§4 (机构级核心, 慎重): `audit` (诚实-N/DSR/PBO/Newey-West) — 这是 GOAL 的硬骨头, 设计稿做了 UI 但后端零实现; 落地前需先在 dev/ 立卡 + 拍板方法学 (R2 多证据三角、honest-N 三档预注册)。
4. 设计补漏 (设计稿本身缺): **三纯库 (算术/ML/DL 分库 + 信号契约)** 与 **暴力遍历挖掘 view** — 这是 §3 骨干, 设计稿未覆盖, 需补设计再谈端点。

**注意事项 (落地前提):** 多数 IC/回测端点都依赖一个"panel 数据源" (polars DataFrame: symbol/ts/close/volume...), 现 `factor_factory` 的计算函数都吃 panel 入参; main.py 暂无"按因子+市场取 panel 跑 IC"的接线层。这是把所有评测类端点做实的共同前置, 应优先确认数据面 (datasets/universe/symbol_pools 模块已存在, 需打通)。