/**
 * 策略台 mock 图数据（parseConsole.md §3.2「_build()」逐字提取）。
 * P0：mock 驱动、刷新即重置、无后端——凡 mock 区块 UI 必挂 <MockBadge/>（B9 诚实）。
 *
 * 16 节点 / 19 连线 DAG + Ask 提议（Ghost ops）+ mock 成交/运行历史/版本/贡献。
 * 全部数值/字面量来自 DC 原型 `策略台.dc.html` _build()，非推断。
 */

import {
  type NodeCat,
  type NodeState,
  type Compat,
  type NodeView,
  type EdgeView,
} from "../../components/desk/canvas";

/** 阶段键（DC StageKey s1..s8）。 */
export type StageKey = "s1" | "s2" | "s3" | "s4" | "s5" | "s6" | "s7" | "s8";

/** 端口领域模型（含 dt/freq/req/role/schema，校验/兼容性依赖）。 */
export interface DomainPort {
  id: string;
  name: string;
  /** dataType。 */
  dt: string;
  /** 频率 'D' 日 / 'W' 周 / '—' / ''。 */
  freq: string;
  scope: string;
  req: boolean;
  /** 'exec' 角色触发 Final Gate 连线门。 */
  role: string;
  schema: string;
}

/** 节点领域模型（mock 全集；NodeView 是其渲染子集投影）。 */
export interface DomainNode {
  id: string;
  cat: NodeCat;
  stage: StageKey;
  title: string;
  x: number;
  y: number;
  w: number;
  state: NodeState;
  desc: string;
  params: Record<string, string>;
  ins: DomainPort[];
  outs: DomainPort[];
  lines: string[];
  lineage: string;
  badge?: string;
  mock?: boolean;
  /** Final Risk Gate 等不可删节点（B6）。 */
  locked?: boolean;
  /** 仅 backtest 节点：卡上出「↗打开回测详情」。 */
  openRun?: boolean;
}

export interface DomainEdge {
  id: string;
  from: { node: string; port: string };
  to: { node: string; port: string };
  compat: Compat;
}

/** GhostOp 3 种（主原型实装子集：addNode / addEdge / setParam）。 */
export type GhostOp =
  | { op: "addNode"; node: DomainNode }
  | { op: "addEdge"; edge: DomainEdge }
  | { op: "setParam"; node: string; k: string; v: string };

export interface AgentProposal {
  patchId: string;
  title: string;
  /** diff 行 [sign, text]（色由 ChatBubble DiffSign 决定，不传 hex）。 */
  diff: { sign: "+" | "~" | "-"; text: string }[];
  ops: GhostOp[];
}

export interface MockTrade {
  id: string;
  symbol: string;
  side: "买入" | "卖出";
  qty: string;
  px: string;
  when: string;
  weight: string;
  pnl: string;
  ret: string;
  /** 血缘链路节点 id 序列。 */
  path: string[];
}

export interface MockRun {
  id: string;
  when: string;
  excess: string;
  dd: string;
  sharpe: string;
  status: "succeeded" | "warning";
  cur?: boolean;
}

export interface MockVersion {
  vid: string;
  label: string;
  lifecycle: string;
  cur?: boolean;
}

/** 端口工厂（对齐 DC P(id,name,dt,opts)）。 */
function P(
  id: string,
  name: string,
  dt: string,
  opts: Partial<Omit<DomainPort, "id" | "name" | "dt">> = {},
): DomainPort {
  return {
    id,
    name,
    dt,
    freq: opts.freq ?? "",
    scope: opts.scope ?? "",
    req: opts.req !== false,
    role: opts.role ?? "",
    schema: opts.schema ?? "",
  };
}

/** 16 节点初始定义（DC defs[]）。 */
export const MOCK_NODES: DomainNode[] = [
  {
    id: "thesis",
    cat: "research",
    stage: "s1",
    title: "立题 Thesis",
    x: 40,
    y: 250,
    w: 176,
    state: "valid",
    desc: "可证伪命题：SUE+中期动量+估值，A股周频年化超额≥15%、回撤≤20%。可证伪条件：样本外 DSR≤0 或 PBO≥0.5。",
    params: {
      objective: "超额≥15% / 回撤≤20%",
      horizon: "weekly",
      benchmark: "000905.SH",
      stage: "exploratory",
    },
    ins: [],
    outs: [P("thesis", "thesis", "thesis", { freq: "—" })],
    lines: ["超额≥15% · 回撤≤20%", "benchmark 中证500", "周频 · exploratory"],
    lineage: "hyp_wk_cn_01",
  },
  {
    id: "market",
    cat: "research",
    stage: "s2",
    title: "市场组合 Market",
    x: 300,
    y: 120,
    w: 178,
    state: "valid",
    desc: "市场层约束：资产类别 equity_cn、交易日历、可交易时段、币种。与投资标的池相互独立（B1）。",
    params: { asset_class: "equity_cn", calendar: "SSE/SZSE", currency: "CNY" },
    ins: [P("in", "thesis", "thesis", { req: false })],
    outs: [P("constraints", "marketConstraints", "marketConstraints", { freq: "D" })],
    lines: ["equity_cn · A股", "日历 SSE/SZSE · CNY"],
    lineage: "mkt_cn",
  },
  {
    id: "universe",
    cat: "research",
    stage: "s2",
    title: "投资标的池 Universe",
    x: 300,
    y: 392,
    w: 178,
    state: "valid",
    desc: "只定义允许交易哪些标的，不含权重（B2）。剔除 ST/上市<1y/流动性不足。",
    params: { rule: "剔除ST · 上市>1y · ADV>2000万", count: "≈5412" },
    ins: [P("in", "thesis", "thesis", { req: false })],
    outs: [P("set", "instrumentSet", "instrumentSet", { freq: "D" })],
    lines: ["剔除ST · 上市>1y", "ADV>¥2000万 · ≈5412只", "⚠ 不含权重"],
    lineage: "univ_cn_liquid",
  },
  {
    id: "domain",
    cat: "scope",
    stage: "s2",
    title: "Tradable Domain ∩",
    x: 540,
    y: 256,
    w: 168,
    state: "valid",
    desc: "TradableDomain = InvestmentUniverse ∩ MarketConstraints。可交易标的域，下游因子/信号在此域内计算。",
    params: { op: "intersection" },
    ins: [
      P("mc", "marketConstraints", "marketConstraints"),
      P("iu", "instrumentSet", "instrumentSet"),
    ],
    outs: [P("td", "tradableDomain", "tradableDomain", { freq: "D" })],
    lines: ["∩ 求交", "可交易域"],
    lineage: "domain_cn",
  },
  {
    id: "data",
    cat: "data",
    stage: "s3",
    title: "数据源 DataSource",
    x: 768,
    y: 120,
    w: 180,
    state: "valid",
    desc: "Point-in-Time 日频量价+基本面+一致预期+北向。引用列全部命中字段宇宙（41 列）。",
    params: { sources: "official_cn_eod · consensus · north", fields: "41", pit: "true" },
    ins: [P("scope", "tradableDomain", "tradableDomain", { req: false })],
    outs: [
      P("panel", "panel", "panel", {
        freq: "D",
        schema: "[date,symbol,ohlcv,fundamental,sue,north]",
      }),
    ],
    lines: ["日频量价+基本面", "SUE · 北向 · PIT", "字段宇宙 41 列"],
    lineage: "ds_cn_eod",
    mock: true,
  },
  {
    id: "neutral",
    cat: "data",
    stage: "s3",
    title: "中性化 Neutralize",
    x: 768,
    y: 392,
    w: 180,
    state: "valid",
    desc: "因子预处理：缺失值→去极值(Winsor 1%)→标准化→行业/市值中性化。",
    params: { winsor: "1%", standardize: "zscore", neutralize: "industry+size" },
    ins: [P("in", "panel", "panel", { freq: "D" })],
    outs: [P("out", "panel", "panel", { freq: "D" })],
    lines: ["Winsor 1% · zscore", "行业+市值 中性化"],
    lineage: "tx_neutral",
  },
  {
    id: "factors",
    cat: "factor",
    stage: "s3",
    title: "因子集 fs_core3",
    x: 1004,
    y: 256,
    w: 180,
    state: "valid",
    desc: "从因子台选用 QUALIFIED+ 因子组（不在策略台造因子，B4）：surprise_sue / mom_20_120 / ep_ttm，两两|ρ|<0.35。",
    params: { factors: "surprise_sue, mom_20_120, ep_ttm", min_state: "QUALIFIED" },
    ins: [
      P("scope", "tradableDomain", "tradableDomain"),
      P("feat", "panel", "panel", { freq: "D" }),
    ],
    outs: [
      P("fp", "factorPanel", "factorPanel", { freq: "W", schema: "[date,symbol,sue,mom,ep]" }),
    ],
    lines: ["surprise_sue IC .067", "mom_20_120 · ep_ttm", "← 因子台 QUALIFIED+"],
    lineage: "fs_core3",
    badge: "← 因子台",
    mock: true,
  },
  {
    id: "model",
    cat: "model",
    stage: "s4",
    title: "Model · lgbm_rank_6f",
    x: 1240,
    y: 256,
    w: 184,
    state: "valid",
    desc: "仅从 Model Registry 引用 model_id@version（B3，不训练）。LambdaRank，输入6特征 Schema，输出截面打分。Artifact：pinned@v2。",
    params: {
      model_id: "lgbm_rank_6f",
      version: "v2 (staging)",
      task: "lambdarank",
      artifact: "pinned",
    },
    ins: [P("feat", "factorPanel", "factorPanel", { freq: "W", schema: "6 features" })],
    outs: [
      P("score", "modelScore", "modelScore", { freq: "W", schema: "[date,symbol,score]" }),
    ],
    lines: ["lgbm_rank_6f @ v2", "LambdaRank · WF 8/8正", "Artifact: pinned"],
    lineage: "mdl_lgbm_v2",
    badge: "← Model台",
    mock: true,
  },
  {
    id: "signal",
    cat: "signal",
    stage: "s5",
    title: "信号 Signal",
    x: 1480,
    y: 256,
    w: 178,
    state: "valid",
    desc: "把模型打分转为可交易信号：每周五收盘按 score 截面排序，取前 10% 为多头候选。输出标准 SignalIntent。",
    params: { rule: "rank(score) top decile", rebalance: "weekly_fri", direction: "long" },
    ins: [P("score", "modelScore", "modelScore", { freq: "W" })],
    outs: [P("intent", "signalIntent", "signalIntent", { freq: "W", schema: "SignalIntent[]" })],
    lines: ["截面排序 top 10%", "周五调仓 · 纯多头", "→ SignalIntent"],
    lineage: "sig_topdecile",
  },
  {
    id: "entry",
    cat: "position",
    stage: "s6",
    title: "入场 Entry",
    x: 1716,
    y: 116,
    w: 172,
    state: "valid",
    desc: "信号选入前10%且未停牌/未涨停；分批建仓平滑冲击成本。",
    params: { cond: "rank<=10% & !halt & !limitUp", fill: "分批 TWAP" },
    ins: [P("sig", "signalIntent", "signalIntent", { freq: "W" })],
    outs: [P("e", "entrySignal", "entrySignal", { freq: "W" })],
    lines: ["前10% & 未停牌", "分批建仓"],
    lineage: "entry_01",
  },
  {
    id: "exit",
    cat: "position",
    stage: "s6",
    title: "退出 Exit",
    x: 1716,
    y: 332,
    w: 172,
    state: "valid",
    desc: "信号跌出前30%分位 / 个股止损 -12% / 周五再平衡时换出。",
    params: { exit: "rank>30% | stop -12% | rebalance", trailing: "off" },
    ins: [P("sig", "signalIntent", "signalIntent", { freq: "W" })],
    outs: [P("x", "exitSignal", "exitSignal", { freq: "W" })],
    lines: ["跌出前30% / 止损-12%", "周五再平衡换出"],
    lineage: "exit_01",
  },
  {
    id: "optim",
    cat: "position",
    stage: "s6",
    title: "仓位优化 Optimizer",
    x: 1944,
    y: 224,
    w: 182,
    state: "valid",
    desc: "组合优化求目标权重：等风险加权，单票≤3%，行业偏离≤5%，换手≤60%/周。输出 Target Portfolio。",
    params: { sizing: "equal_risk", max_pos: "3%", sector_dev: "5%", turnover: "60%/w" },
    ins: [
      P("e", "entrySignal", "entrySignal"),
      P("x", "exitSignal", "exitSignal"),
    ],
    outs: [
      P("tp", "targetPortfolio", "targetPortfolio", {
        freq: "W",
        schema: "TargetPortfolioItem[]",
      }),
    ],
    lines: ["等风险 · 单票≤3%", "行业偏离≤5%", "→ TargetPortfolio"],
    lineage: "optim_eqrisk",
  },
  {
    id: "prisk",
    cat: "risk",
    stage: "s7",
    title: "组合风险 PortfolioRisk",
    x: 2178,
    y: 224,
    w: 180,
    state: "valid",
    desc: "敞口/集中度/VaR 校验：暴露限额、流动性下限 ¥2000万/日、VaR(95) 监控。",
    params: { exposure: "net 100% / gross 100%", liquidity: "¥2000万/日", var95: "monitor" },
    ins: [P("tp", "targetPortfolio", "targetPortfolio")],
    outs: [P("rp", "riskedPortfolio", "riskedPortfolio", { freq: "W" })],
    lines: ["暴露/集中度/VaR", "流动性下限校验"],
    lineage: "prisk_01",
  },
  {
    id: "gate",
    cat: "risk",
    stage: "s7",
    title: "Final Risk Gate",
    x: 2406,
    y: 224,
    w: 176,
    state: "valid",
    locked: true,
    desc: "最终风险闸门（B6 不可删除/绕过）：组合回撤熔断 20%、单日跌停不接、全局风控开关。任何到执行的路径必须穿过它。",
    params: { dd_halt: "20%", reject: "跌停/停牌", kill_switch: "armed" },
    ins: [P("rp", "riskedPortfolio", "riskedPortfolio")],
    outs: [P("ap", "approvedPortfolio", "approvedPortfolio", { freq: "W" })],
    lines: ["回撤熔断 20%", "🔒 不可绕过", "Kill Switch armed"],
    lineage: "final_gate",
  },
  {
    id: "exec",
    cat: "exec",
    stage: "s7",
    title: "执行 Execution",
    x: 2630,
    y: 224,
    w: 176,
    state: "valid",
    desc: "执行算法：分批/VWAP 下单，生成 Order Intent。Backtest 撮合 / Paper / Live 三态共用此配置。",
    params: { algo: "VWAP 分批", slice: "5", venue: "sim" },
    ins: [P("ap", "approvedPortfolio", "approvedPortfolio", { role: "exec" })],
    outs: [P("oi", "orderIntent", "orderIntent", { freq: "W" })],
    lines: ["VWAP 分批下单", "→ OrderIntent"],
    lineage: "exec_vwap",
  },
  {
    id: "bench",
    cat: "eval",
    stage: "s8",
    title: "基准 Benchmark",
    x: 2854,
    y: 96,
    w: 168,
    state: "valid",
    desc: "回测基准：中证500 全收益。",
    params: { benchmark: "000905.SH", type: "total_return" },
    ins: [],
    outs: [P("b", "benchmark", "benchmark", { freq: "D" })],
    lines: ["中证500", "000905.SH"],
    lineage: "bench_500",
  },
  {
    id: "backtest",
    cat: "eval",
    stage: "s8",
    title: "回测与评价 Backtest",
    x: 2854,
    y: 296,
    w: 184,
    state: "succeeded",
    desc: "组装回测：2019–2024 · neutral 成本。结果 超额17.3% / 回撤15.8% / PBO0.18 / DSR1.34。点开回测详情查看完整 Trace 与血缘。",
    params: { window: "2019-01..2024-12", cost: "neutral" },
    ins: [
      P("oi", "orderIntent", "orderIntent"),
      P("b", "benchmark", "benchmark", { req: false }),
    ],
    outs: [],
    lines: ["超额 17.3% · 回撤 15.8%", "PBO 0.18 · DSR 1.34"],
    lineage: "run_wk_cn_8f2a",
    mock: true,
    openRun: true,
  },
];

/** 19 连线（DC edges[]）。 */
export const MOCK_EDGES: DomainEdge[] = [
  { id: "e1", from: { node: "thesis", port: "thesis" }, to: { node: "market", port: "in" }, compat: "ok" },
  { id: "e2", from: { node: "thesis", port: "thesis" }, to: { node: "universe", port: "in" }, compat: "ok" },
  { id: "e3", from: { node: "market", port: "constraints" }, to: { node: "domain", port: "mc" }, compat: "ok" },
  { id: "e4", from: { node: "universe", port: "set" }, to: { node: "domain", port: "iu" }, compat: "ok" },
  { id: "e5", from: { node: "domain", port: "td" }, to: { node: "data", port: "scope" }, compat: "ok" },
  { id: "e6", from: { node: "domain", port: "td" }, to: { node: "factors", port: "scope" }, compat: "ok" },
  { id: "e7", from: { node: "data", port: "panel" }, to: { node: "neutral", port: "in" }, compat: "ok" },
  { id: "e8", from: { node: "neutral", port: "out" }, to: { node: "factors", port: "feat" }, compat: "ok" },
  { id: "e9", from: { node: "factors", port: "fp" }, to: { node: "model", port: "feat" }, compat: "ok" },
  { id: "e10", from: { node: "model", port: "score" }, to: { node: "signal", port: "score" }, compat: "ok" },
  { id: "e11", from: { node: "signal", port: "intent" }, to: { node: "entry", port: "sig" }, compat: "ok" },
  { id: "e12", from: { node: "signal", port: "intent" }, to: { node: "exit", port: "sig" }, compat: "ok" },
  { id: "e13", from: { node: "entry", port: "e" }, to: { node: "optim", port: "e" }, compat: "ok" },
  { id: "e14", from: { node: "exit", port: "x" }, to: { node: "optim", port: "x" }, compat: "ok" },
  { id: "e15", from: { node: "optim", port: "tp" }, to: { node: "prisk", port: "tp" }, compat: "ok" },
  { id: "e16", from: { node: "prisk", port: "rp" }, to: { node: "gate", port: "rp" }, compat: "ok" },
  { id: "e17", from: { node: "gate", port: "ap" }, to: { node: "exec", port: "ap" }, compat: "ok" },
  { id: "e18", from: { node: "exec", port: "oi" }, to: { node: "backtest", port: "oi" }, compat: "ok" },
  { id: "e19", from: { node: "bench", port: "b" }, to: { node: "backtest", port: "b" }, compat: "adapt" },
];

/** Ask 默认提议（pt_4f1a：加 VaR/CVaR + 降换手）。 */
export const MOCK_PROPOSAL: AgentProposal = {
  patchId: "pt_4f1a",
  title: "加 VaR/CVaR 风险预算 + 降换手",
  diff: [
    { sign: "+", text: "新增 VaR/CVaR 节点（接 仓位优化 输出）" },
    { sign: "+", text: "连线 仓位优化 → VaR/CVaR" },
    { sign: "~", text: "仓位优化 turnover 60%/w → 45%/w" },
  ],
  ops: [
    {
      op: "addNode",
      node: {
        id: "varcvar",
        cat: "risk",
        stage: "s7",
        title: "VaR/CVaR 预算",
        x: 1944,
        y: 392,
        w: 178,
        state: "idle",
        desc: "风险预算：限制组合 VaR(95)/CVaR(97.5) 上限，超限回缩高风险仓位。",
        params: { var95: "≤2.5%/日", cvar975: "≤3.5%/日" },
        ins: [P("tp", "targetPortfolio", "targetPortfolio")],
        outs: [P("rb", "riskBudget", "riskBudget", { freq: "W" })],
        lines: ["VaR(95)≤2.5%/日", "CVaR(97.5)≤3.5%/日"],
        lineage: "risk_varcvar",
      },
    },
    {
      op: "addEdge",
      edge: {
        id: "e_var",
        from: { node: "optim", port: "tp" },
        to: { node: "varcvar", port: "tp" },
        compat: "ok",
      },
    },
    { op: "setParam", node: "optim", k: "turnover", v: "45%/w" },
  ],
};

/** Auto/Bypass 自动增节点（DrawdownGuard，事务化 + 可整轮撤销）。 */
export const MOCK_AUTO_NODE: DomainNode = {
  id: "ddguard",
  cat: "risk",
  stage: "s7",
  title: "回撤护栏 DrawdownGuard",
  x: 2178,
  y: 396,
  w: 182,
  state: "idle",
  desc: "Auto/Bypass 自动增节点：滚动回撤超阈值时降杠杆。",
  params: { trigger: "rolling DD>12%", action: "降杠杆 50%" },
  ins: [P("rp", "riskedPortfolio", "riskedPortfolio", { freq: "W" })],
  outs: [P("g", "guardedPortfolio", "riskedPortfolio", { freq: "W" })],
  lines: ["滚动回撤>12% → 降杠杆", "Auto 生成"],
  lineage: "auto_ddguard",
};

/** mock 成交（DC _trades，含血缘 path）。 */
export const MOCK_TRADES: MockTrade[] = [
  {
    id: "tx_001",
    symbol: "300750 宁德时代",
    side: "买入",
    qty: "12,000 股",
    px: "¥182.40",
    when: "2024-11-15",
    weight: "2.8%",
    pnl: "+¥84,200",
    ret: "+19.2%",
    path: ["model", "signal", "entry", "optim", "prisk", "gate", "exec", "backtest"],
  },
  {
    id: "tx_002",
    symbol: "600519 贵州茅台",
    side: "买入",
    qty: "1,800 股",
    px: "¥1,512.0",
    when: "2024-11-15",
    weight: "2.5%",
    pnl: "+¥51,600",
    ret: "+11.4%",
    path: ["model", "signal", "entry", "optim", "prisk", "gate", "exec", "backtest"],
  },
  {
    id: "tx_003",
    symbol: "002594 比亚迪",
    side: "卖出",
    qty: "9,500 股",
    px: "¥246.10",
    when: "2024-12-06",
    weight: "—",
    pnl: "-¥18,300",
    ret: "-7.3%",
    path: ["model", "signal", "exit", "optim", "prisk", "gate", "exec", "backtest"],
  },
];

/** mock 运行历史（DC _runs）。 */
export const MOCK_RUNS: MockRun[] = [
  { id: "run_wk_cn_8f2a", when: "12-28 09:14", excess: "+17.3%", dd: "15.8%", sharpe: "1.82", status: "succeeded", cur: true },
  { id: "run_wk_cn_7d10", when: "12-21 18:02", excess: "+15.1%", dd: "17.2%", sharpe: "1.61", status: "succeeded" },
  { id: "run_wk_cn_6a02", when: "12-14 11:40", excess: "+9.8%", dd: "22.4%", sharpe: "1.12", status: "warning" },
];

/** mock 版本（DC _versions）。 */
export const MOCK_VERSIONS: MockVersion[] = [
  { vid: "v3", label: "v3 草稿", lifecycle: "Backtested · 当前", cur: true },
  { vid: "v2", label: "v2", lifecycle: "Reviewed" },
  { vid: "v1", label: "v1", lifecycle: "Draft" },
];

/** diff 基线（DC _diff）。 */
export const MOCK_DIFF = {
  base: "v2",
  added: ["signal"] as string[],
  changed: ["model", "optim"] as string[],
};

/** 节点回测贡献（DC _contribution，色用语义 tone 不传 hex）。 */
export type ContribTone = "success" | "danger" | "warning" | "neutral";
export const MOCK_CONTRIBUTION: Record<string, { k: string; v: string; tone: ContribTone }[]> = {
  signal: [
    { k: "收益贡献", v: "+6.2%", tone: "success" },
    { k: "信号数", v: "1,284", tone: "neutral" },
    { k: "命中率", v: "57%", tone: "neutral" },
  ],
  model: [
    { k: "收益贡献", v: "+8.1%", tone: "success" },
    { k: "特征重要度", v: "sue.40 mom.37 ep.23", tone: "neutral" },
  ],
  optim: [
    { k: "换手成本", v: "-1.8%", tone: "danger" },
    { k: "平均持仓", v: "48 只", tone: "neutral" },
  ],
  exec: [
    { k: "冲击成本", v: "-0.9%", tone: "danger" },
    { k: "成交笔数", v: "3,210", tone: "neutral" },
  ],
  backtest: [
    { k: "年化超额", v: "+17.3%", tone: "success" },
    { k: "最大回撤", v: "15.8%", tone: "warning" },
    { k: "Sharpe", v: "1.82", tone: "success" },
  ],
};

/** 阶段元信息（DC STGORDER + 标题）。 */
export const STAGES: { key: StageKey; idx: string; title: string }[] = [
  { key: "s1", idx: "01", title: "研究 Research" },
  { key: "s2", idx: "02", title: "域 Scope" },
  { key: "s3", idx: "03", title: "数据/因子 Data" },
  { key: "s4", idx: "04", title: "模型 Model" },
  { key: "s5", idx: "05", title: "信号 Signal" },
  { key: "s6", idx: "06", title: "仓位 Position" },
  { key: "s7", idx: "07", title: "风险/执行 Risk" },
  { key: "s8", idx: "08", title: "评价 Eval" },
];

/** DomainNode → NodeView（渲染子集投影）。 */
export function toNodeView(n: DomainNode): NodeView {
  return {
    id: n.id,
    cat: n.cat,
    title: n.title,
    x: n.x,
    y: n.y,
    w: n.w,
    state: n.state,
    lines: n.lines,
    ins: n.ins.map((p) => ({ id: p.id, name: p.name })),
    outs: n.outs.map((p) => ({ id: p.id, name: p.name })),
    badge: n.badge,
    locked: n.locked,
  };
}

/** DomainEdge → EdgeView。 */
export function toEdgeView(e: DomainEdge): EdgeView {
  return { id: e.id, from: e.from, to: e.to, compat: e.compat };
}
