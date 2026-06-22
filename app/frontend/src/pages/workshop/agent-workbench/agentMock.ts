import {
  type AgentBlock,
  type SideEffect,
  type TodoItem,
} from "../../../components/desk";
import { type RunVerdictData } from "../../../components/RunVerdictCard";

/**
 * Agent 工作台 mock 数据 + 类型（agentDeck.md / QuantBT Agent.dc.html →React）。
 *
 * P0：纯 mock 剧本，未接真后端 SSE/agent_runtime——故页面常驻 <MockBadge/>，不假绿灯。
 *
 * 治理真值原则（D-PERM / R25）：
 *  · tool/gate 的 side_effect 是**受控真值**（来自后端 tool_status），mock 这里只占位、
 *    页面渲染时原样透传给 ChatBubble，绝不前端伪造或当可编辑字段。
 *  · 设计稿剧本只演 side_effect:none 的 backtest.run；为让 D-PERM 反例
 *    「bypass 也拦真钱」可见，本 mock 额外提供 realmoney/external 的 gate 反例事件。
 */

/** 七里程碑节点（立题→市场→因子集→模型→信号→风控→回测）。 */
export type MilestoneKey =
  | "立题"
  | "市场"
  | "因子集"
  | "模型"
  | "信号"
  | "仓位风控"
  | "回测";

/** 产物卡种类（与里程碑一一对应 + market）。 */
export type CoworkKind =
  | "hypothesis"
  | "market"
  | "factorSet"
  | "model"
  | "signal"
  | "portfolio"
  | "run";

export interface MilestoneDef {
  key: MilestoneKey;
  label: string;
  cowork: CoworkKind;
}

/** 进度线 7 节点定义（cowork 锚点 + 短 label）。 */
export const MILESTONE_DEFS: MilestoneDef[] = [
  { key: "立题", label: "立题", cowork: "hypothesis" },
  { key: "市场", label: "市场", cowork: "market" },
  { key: "因子集", label: "因子集", cowork: "factorSet" },
  { key: "模型", label: "模型", cowork: "model" },
  { key: "信号", label: "信号", cowork: "signal" },
  { key: "仓位风控", label: "风控", cowork: "portfolio" },
  { key: "回测", label: "回测", cowork: "run" },
];

/** 工作区 tab。 */
export type WorkspaceTab = "cowork" | "code" | "report";

/** 剧本事件——驱动「重放」推进对话流 + 解锁产物卡/里程碑。 */
export interface ScriptEvent {
  id: string;
  /** 关联里程碑（到达即点亮进度线节点）。 */
  ms?: MilestoneKey;
  /** 关联产物卡（tool ↗ 下钻 / 里程碑跳转目标）。 */
  cowork?: CoworkKind;
  /** ChatBubble 渲染所需的全部 props（type + 内容）。 */
  block: Omit<AgentBlock, "id">;
  /** 推进副作用：解锁哪张产物卡。 */
  unlock?: CoworkKind;
}

const HYP_TODOS: TodoItem[] = [
  { text: "立题：假设卡", state: "doing" },
  { text: "市场：确认数据/字段宇宙", state: "todo" },
  { text: "选用因子集（因子台）", state: "todo" },
  { text: "选用模型（Model台）", state: "todo" },
  { text: "信号 → 风控", state: "todo" },
  { text: "组装 + 回测", state: "todo" },
];

function todoStep(done: number): TodoItem[] {
  const labels = [
    "立题：假设卡",
    "市场：确认数据/字段宇宙",
    "选用因子集（因子台）",
    "选用模型（Model台）",
    "信号 → 风控",
    "组装 + 回测",
  ];
  return labels.map((text, i) => ({
    text,
    state: i < done ? "done" : i === done ? "doing" : "todo",
  }));
}

const FIRST_PROMPT =
  "组装一个 A股周频多因子策略：超额 15% / 回撤 ≤ 20%。从因子台和 Model台已发布的资产里选用因子集和模型，跑回测。";

export const AGENT_FIRST_PROMPT = FIRST_PROMPT;

/**
 * 策略台剧本（agentDeck.md §③ _events[]）。
 * gate 事件 backtest.run 带 side_effect:none（受控真值）——none 类 bypass 自跑不违 D-PERM。
 */
export const AGENT_SCRIPT: ScriptEvent[] = [
  { id: "u1", block: { type: "user", text: FIRST_PROMPT } },
  {
    id: "th1",
    block: {
      type: "think",
      text: "策略台只做组装+回测：先立假设卡，确认字段，然后从因子台拉 QUALIFIED+ 因子组、从 Model台拉 staging+ 模型（不在这训），组装跑 backtest.run。到回测拍板为止——进场是模拟台的事。",
    },
  },
  {
    id: "sH",
    block: {
      type: "say",
      text: "先把这句话立成可证伪的假设卡（exploratory）：",
    },
  },
  {
    id: "tH",
    ms: "立题",
    cowork: "hypothesis",
    unlock: "hypothesis",
    block: {
      type: "tool",
      toolName: "hypothesis.create",
      toolArgs: "goal_ref: sg_wk_cn_01, stage: exploratory",
      toolStatus: "done",
      toolSummary: "假设卡 hyp_wk_cn_01 已建",
    },
  },
  { id: "td1", block: { type: "todos", todos: HYP_TODOS } },
  {
    id: "s1",
    block: {
      type: "say",
      text: "市场层：确认这套策略用了哪些数据、因子要引用的列都在字段宇宙里：",
    },
  },
  {
    id: "t2",
    ms: "市场",
    cowork: "market",
    unlock: "market",
    block: {
      type: "tool",
      toolName: "data.describe_fields",
      toolArgs: "market: equity_cn",
      toolStatus: "done",
      toolSummary: "市场 equity_cn · 3 源 5412 标的 · 字段宇宙 41 列 · 引用列全命中",
    },
  },
  {
    id: "s3",
    block: {
      type: "say",
      text: "从因子台选 QUALIFIED+ 的因子组成 factor_set（不在策略台造因子）：",
    },
  },
  {
    id: "t4",
    ms: "因子集",
    cowork: "factorSet",
    unlock: "factorSet",
    block: {
      type: "tool",
      toolName: "factor_set.compose",
      toolArgs: "from: 因子台, filter: state>=QUALIFIED",
      toolStatus: "done",
      toolSummary: "fs_core3 · 3 因子选用（surprise_sue · mom_20_120 · ep_ttm）",
    },
  },
  {
    id: "s5",
    block: {
      type: "say",
      text: "从 Model台选已发布的 staging 模型（重训去 Model台）：",
    },
  },
  {
    id: "t5",
    ms: "模型",
    cowork: "model",
    unlock: "model",
    block: {
      type: "tool",
      toolName: "model_registry.select",
      toolArgs: "model: lgbm_rank_6f@v2, stage: staging",
      toolStatus: "done",
      toolSummary: "lgbm_rank_6f@v2（staging）选用 · walk-forward 8/8 正",
    },
  },
  { id: "td2", block: { type: "todos", todos: todoStep(4) } },
  {
    id: "sSig",
    block: {
      type: "say",
      text: "模型出的是打分，要先转成可交易信号：定义打分→排序→选股的信号规则。",
    },
  },
  {
    id: "tSig",
    ms: "信号",
    cowork: "signal",
    unlock: "signal",
    block: {
      type: "tool",
      toolName: "signal.define",
      toolArgs: "rule: rank(score) top decile, rebalance: weekly_fri",
      toolStatus: "done",
      toolSummary: "信号已定义 · 周五按模型分排序、取前 10% 为多头候选",
    },
  },
  {
    id: "sPos",
    block: {
      type: "say",
      text: "信号是候选名单，还要定风控（仓位在内）与执行机制（由信号触发）才能落地交易：",
    },
  },
  {
    id: "tPos",
    ms: "仓位风控",
    cowork: "portfolio",
    unlock: "portfolio",
    block: {
      type: "tool",
      toolName: "portfolio.construct",
      toolArgs: "sizing: equal_risk, max_pos: 0.03, dd_halt: 0.20",
      toolStatus: "done",
      toolSummary: "风控+执行机制已定义 · 等权风险 · 单票≤3% · 回撤熔断20%",
    },
  },
  { id: "td3b", block: { type: "todos", todos: todoStep(5) } },
  {
    id: "s6",
    block: {
      type: "say",
      text: "组装成 strat_wk_cn_01（因子集+模型+信号+风控），跑回测。backtest.run 写 runs/：",
    },
  },
  {
    id: "g1",
    block: {
      type: "gate",
      gateTool: "backtest.run",
      sideEffect: "none",
      gateBlurb:
        "组装 fs_core3 + lgbm_rank_6f@v2 + 信号/风控规则，neutral 成本跑周频回测，写 runs/run_wk_cn_8f2a/。",
    },
  },
  {
    id: "t8",
    ms: "回测",
    cowork: "run",
    unlock: "run",
    block: {
      type: "tool",
      toolName: "backtest.run",
      toolArgs: "factor_set: fs_core3, model_id: lgbm_rank_6f@v2",
      toolStatus: "done",
      toolSummary:
        "回测+体检完成 · 超额17.3% · 回撤15.8% · PBO0.18 · DSR1.34",
    },
  },
  { id: "td3", block: { type: "todos", todos: todoStep(6) } },
  {
    id: "f1",
    block: {
      type: "say",
      text: "回测拍板：双目标在容差内、PBO/DSR 未触发过拟合熔断。这是策略台的终点。",
    },
  },
];

/** slash 命令面板（agentDeck.md _slashCmds）。 */
export interface SlashCmd {
  cmd: string;
  desc: string;
}

export const SLASH_CMDS: SlashCmd[] = [
  { cmd: "/clear", desc: "清空并重放策略台流程" },
  { cmd: "/factor-set", desc: "从因子台选用因子组 factor_set" },
  { cmd: "/model", desc: "从 Model台选用已发布模型" },
  { cmd: "/backtest", desc: "backtest.run — 组装回测" },
  { cmd: "/handoff", desc: "提交候选策略进模拟台" },
  { cmd: "/permissions", desc: "切权限 ask / auto / bypass" },
];

/** 假设卡 mock 内容。 */
export const MOCK_HYPOTHESIS = {
  id: "hyp_wk_cn_01",
  proposition: "SUE + 中期动量 + 估值，在 A股周频可获年化超额 ≥ 15%",
  falsify: "样本外 DSR ≤ 0 或 PBO ≥ 0.5 即推翻",
  benchmark: "中证500 · 000905.SH",
  goalRef: "sg_wk_cn_01",
};

/** 市场卡：3 数据源 + 字段分组。 */
export const MOCK_DATA_SOURCES: { id: string; note: string }[] = [
  { id: "official_cn_eod", note: "日频量价 ohlcv·adj·fundamental" },
  { id: "official_consensus", note: "一致预期 analyst_est·sue" },
  { id: "user_altdata_v3", note: "北向 north_flow·turnover_ext" },
];

export const MOCK_FIELD_GROUPS: { k: string; v: string }[] = [
  { k: "canonical 量价", v: "open high low close vwap volume amount" },
  { k: "canonical 财务", v: "pe_ttm pb roe_ttm netprofit_yoy" },
  { k: "official_ 前缀", v: "official_sue official_north_net" },
  { k: "freeform(用户)", v: "turnover_ext north_flow_z" },
];

/** 因子集卡：3 因子（QUALIFIED）。 */
export const MOCK_FACTOR_SET: {
  id: string;
  state: string;
  ic: string;
  note: string;
}[] = [
  { id: "surprise_sue", state: "QUALIFIED", ic: "0.067", note: "盈余惊喜 · 最强、衰减慢" },
  { id: "mom_20_120", state: "QUALIFIED", ic: "0.058", note: "中期动量 · 稳健正贡献" },
  { id: "ep_ttm", state: "QUALIFIED", ic: "0.044", note: "估值 · 与动量低相关、分散" },
];

/** 模型卡 walk-forward 8 窗口表。 */
export const MOCK_WF_WINDOWS: {
  w: string;
  span: string;
  oos: string;
  ndcg: string;
  worst?: boolean;
}[] = [
  { w: "W1", span: "2019–20 → 21H1", oos: "+4.2%", ndcg: "0.241" },
  { w: "W2", span: "2019–21H1 → 21H2", oos: "+3.1%", ndcg: "0.228" },
  { w: "W3", span: "2019–21 → 22H1", oos: "+1.8%", ndcg: "0.207" },
  { w: "W4", span: "2019–22H1 → 22H2", oos: "+0.9%", ndcg: "0.196", worst: true },
  { w: "W5", span: "2019–22 → 23H1", oos: "+3.6%", ndcg: "0.233" },
  { w: "W6", span: "2019–23H1 → 23H2", oos: "+2.4%", ndcg: "0.219" },
  { w: "W7", span: "2019–23 → 24H1", oos: "+4.0%", ndcg: "0.238" },
  { w: "W8", span: "2019–24H1 → 24H2", oos: "+2.7%", ndcg: "0.224" },
];

/** 信号卡内容。 */
export const MOCK_SIGNAL = {
  rule: "每周五收盘按模型分排序，取截面前 10% 为多头候选",
  rebalance: "周频 · 周五收盘",
  direction: "纯多头（对冲基准）",
  candidates: "~50 只（前 10%）",
};

/** 风控限额（红=熔断/约束分两类）。 */
export const MOCK_RISK_SIZING: string[] = [
  "等风险加权",
  "单票 ≤ 3%",
  "行业偏离 ≤ 5%",
  "换手 ≤ 60%/周",
];
export const MOCK_RISK_LIMITS: string[] = [
  "组合回撤熔断 20%",
  "单日跌停不接",
  "流动性下限 ¥2000万/日",
];
export const MOCK_EXEC = {
  enter:
    "信号选入前 10% 且未触及停牌/涨停板；分批建仓平滑冲击成本。",
  exit: "信号跌出前 30% 分位 / 个股止损 -12% / 周五再平衡时换出。",
};

/**
 * RunVerdictCard mock（沿用 DC runObj 数值，构造合规 verdictNote）。
 * P0 占位——落地由后端 verifier._verdict_note 供，禁绝对化措辞（R7）。
 */
export const MOCK_AGENT_RUN: RunVerdictData = {
  runId: "run_wk_cn_8f2a",
  verdict: "consistent",
  kpi: {
    annExcess: 0.173,
    maxDD: 0.158,
    sharpe: 1.82,
    ir: 1.41,
    winWeeks: 0.61,
    turnover: 0.42,
  },
  equity: buildSeries(0.6, -2.4, 0.5),
  bench: buildSeries(0.18, 0, 0.12),
  cost: [
    { preset: "optimistic", sharpe: 2.05, excess: 0.196 },
    { preset: "neutral", sharpe: 1.82, excess: 0.173 },
    { preset: "pessimistic", sharpe: 1.49, excess: 0.138 },
  ],
  pbo: 0.18,
  dsr: 1.34,
  bootstrapCI: [0.21, 1.97],
  verdictNote:
    "双目标在容差内、PBO 0.18 / DSR 1.34 未触发熔断。适用域：中证500 成分、周频、2019–2024；未验证项：制度变更稳健性、实盘冲击成本。建议 pessimistic 成本下纸面跟踪 4 周再决定动钱。",
  promoteState: "candidate",
};

/** 净值/基准序列（确定性造数，对齐 DC seed 走势）。 */
function buildSeries(scale: number, dipEvery7: number, drift: number): number[] {
  const seed = [
    3, -1, 4, 2, -2, 5, 1, 3, -1, 4, 6, -3, 2, 5, 1, 4, -2, 3, 6, 2, -1, 5, 3,
    1, 4, -2, 6, 3, 2, 5, -1, 4, 1, 3, 6, -2, 5, 2, 4, -1, 3, 6, 1, 5, -2, 4, 3,
    2, 6, 1, -1, 5, 3, 4, 2, 6, -2, 5,
  ];
  const out: number[] = [];
  let v = 1.0;
  for (let i = 0; i < 58; i++) {
    v *= 1 + (seed[i] * scale + (i % 7 === 0 ? dipEvery7 : drift)) / 100;
    out.push(Number(v.toFixed(4)));
  }
  return out;
}

/** strategy.yaml 行（随到达里程碑累积；color 用 desk token 名，不裸 hex）。 */
export type CodeColor =
  | "key"
  | "val"
  | "str"
  | "cmt"
  | "plain"
  | "ref";

export interface CodeLine {
  n: number;
  t: string;
  color: CodeColor;
}

/** 按已到达里程碑构造 strategy.yaml 行（agentDeck.md _codeLines）。 */
export function buildCodeLines(reached: MilestoneKey[]): CodeLine[] {
  const raw: { t: string; color: CodeColor }[] = [];
  const push = (t: string, color: CodeColor) => raw.push({ t, color });
  push("name: weekly_cn_multifactor", "plain");
  if (reached.includes("立题")) {
    push("hypothesis: hyp_wk_cn_01            # exploratory", "cmt");
    push("goal:", "key");
    push("  asset_class: equity_cn", "val");
    push("  objective: 年化超额≥15% · 回撤≤20%", "val");
    push("  horizon: weekly", "val");
    push('  benchmark: "000905.SH"', "str");
  }
  if (reached.includes("因子集")) {
    push("", "plain");
    push("factor_set: fs_core3                  # ← 因子台", "ref");
    push("  - surprise_sue          # IC 0.067 · QUALIFIED", "cmt");
    push("  - mom_20_120            # IC 0.058 · QUALIFIED", "cmt");
    push("  - ep_ttm                # IC 0.044 · QUALIFIED", "cmt");
  }
  if (reached.includes("模型")) {
    push("", "plain");
    push("model: lgbm_rank_6f@v2                # ← Model台 · staging", "ref");
    push("  task: lambdarank", "val");
    push("  cv_ndcg: 0.231", "val");
    push("  walk_forward: 8/8 windows +", "val");
  }
  if (reached.includes("回测")) {
    push("", "plain");
    push("backtest:", "key");
    push("  cost_preset: neutral", "val");
    push("  window: 2019-01..2024-12", "val");
    push(
      "  result: { excess: 0.173, mdd: 0.158, pbo: 0.18, dsr: 1.34 }",
      "val",
    );
  }
  return raw.map((x, i) => ({ n: i + 1, t: x.t, color: x.color }));
}

/** report.md 行（h/h2/li/p 四型）。 */
export type ReportKind = "h" | "h2" | "li" | "p";
export interface ReportLine {
  kind: ReportKind;
  t: string;
}

export const MOCK_REPORT_MD: ReportLine[] = [
  { kind: "h", t: "strat_wk_cn_01 · 回测报告" },
  { kind: "p", t: "fs_core3 + lgbm_rank_6f@v2 · 2019–2024 · 中证500 · neutral" },
  { kind: "h2", t: "结论" },
  { kind: "li", t: "年化超额 17.3% — 达标 (≥15%)" },
  { kind: "li", t: "最大回撤 15.8% — 达标 (≤20%)" },
  { kind: "li", t: "PBO 0.18 / DSR 1.34 — 非过拟合幸存者" },
  { kind: "h2", t: "交接" },
  {
    kind: "p",
    t: "策略台终点。候选策略可提交模拟台，进场与监控由模拟台决定。",
  },
];

/**
 * D-PERM 反例 gate 模板（让「权限轴 ⟂ 治理轴：bypass 也拦真钱」可见）。
 * side_effect 是受控真值——即便 permMode=bypass/auto，realmoney/external 仍须确认。
 * 设计稿剧本未演这一格；这里显式造数补 UI 证据（T-040 对抗 #3 / D-PERM）。
 */
export interface PermDemoGate {
  gateTool: string;
  sideEffect: SideEffect;
  gateBlurb: string;
  /** 治理弱点（真钱/血统/red）→ 常驻展开不可折叠（R25）。 */
  governanceWeakness?: boolean;
}

export const PERM_DEMO_GATES: Record<
  "realmoney" | "external",
  PermDemoGate
> = {
  realmoney: {
    gateTool: "order.submit",
    sideEffect: "realmoney",
    gateBlurb:
      "提交真钱订单（动钱·不可逆）。策略台不做实盘——此门是 D-PERM 反例演示：side_effect=realmoney 即便 bypass/auto 仍弹确认。",
    governanceWeakness: true,
  },
  external: {
    gateTool: "broker.testnet_order",
    sideEffect: "external",
    gateBlurb:
      "向外部测试网下单（external 副作用）。external 在 ask/auto 下仍须确认——治理门不随权限放宽而跳过。",
    governanceWeakness: true,
  },
};

/**
 * T-041 教学文案弹窗 mock 演示数据（硬透明 + 软决定，绝不死挡）。
 *
 * 三型受控真值占位——落地由后端供给：
 *  · 可证伪 confidence/flags ← assess_falsifiability（D-T024-FALS）。
 *  · 血统未过因子 ← 后端血统校验（D-PROVENANCE）。
 *  · red 裁决 note/弱点 ← verifier._verdict_note（R7 禁绝对化词，前端不杜撰）。
 */
export const MOCK_FALSIFIABILITY_GUIDE = {
  tool: "backtest.run（confirmatory）",
  confidence: "low" as const,
  cardMissing: false,
  flags: [
    "缺可观测前置条件 X（「若X则效应消失」的X缺失）",
    "缺可观测阈值或方向（消失/反号/超过阈值/数值）",
  ],
};

export const MOCK_PROVENANCE_ACK = {
  destination: "paper_desk",
  unverified: [
    { id: "mom_resid_20d", stage: "未独立验证" },
    { id: "liq_amihud_z", stage: "假设卡未冻结" },
  ],
};

export const MOCK_RED_VERDICT = {
  subject: "run_wk_cn_8f2a",
  // 走后端 _verdict_note 口径：证据[一致/存疑/不一致] + 适用域 + 未验证项 N；禁 R7 词。
  verdictNote:
    "证据不一致：样本外窗口与样本内方向背离，适用域仅限训练区间，未验证项 3。",
  weaknesses: [
    "walk-forward 末两窗超额转负，方向与样本内背离",
    "成本敏感性：pessimistic 预设下超额收窄至接近 0",
    "因子集与基准相关性偏高，独立增益待复核",
  ],
};
