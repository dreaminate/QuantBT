/**
 * 模拟台 MOCK 数据派生（对齐 模拟台.dc.html renderVals）。
 * 纯函数：state → 各视图 typed 数据。所有色值走 DeskColor token（禁裸 hex）。
 * 落地时整层替换为 /api/paper/* 响应解析；此处是诚实 MOCK（页面挂 MockBadge）。
 */
import { buildEquityPaths, nz, type EquityPaths } from "./equity";
import { pnlColor, signColor, pct } from "./colors";
import type {
  PaperRun,
  PaperMarket,
  PaperView,
  RunListItem,
  PaperMetric,
  SchedRow,
  PosPreview,
  BalanceCell,
  BookPosition,
  Fill,
  RiskGate,
  ViolationEntry,
  ReviewRow,
  AttrBar,
  CostCell,
  PromoStage,
  PromoCheck,
  PromoFactor,
  ApproveState,
  DeskColor,
} from "./types";

export const RUNS: PaperRun[] = [
  {
    id: "weekly_cn_multifactor",
    name: "weekly_cn_multifactor",
    origin: "策略台 · strat_wk_cn_01",
    market: "equity_cn",
    status: "running",
    days: 4,
    bench: "中证500",
    total: 0.041,
    today: 0.006,
    excess: 0.018,
    q: 0.8,
  },
  {
    id: "crypto_perp_mom",
    name: "crypto_perp_mom",
    origin: "策略台 · strat_crypto_02",
    market: "crypto",
    status: "running",
    days: 6,
    bench: "BTC",
    total: 0.083,
    today: -0.012,
    excess: 0.031,
    q: 0.7,
  },
  {
    id: "dividend_lowvol_cn",
    name: "dividend_lowvol_cn",
    origin: "策略台 · strat_div_03",
    market: "equity_cn",
    status: "paused",
    days: 2,
    bench: "中证红利",
    total: 0.012,
    today: 0.0,
    excess: -0.004,
    q: 0.45,
  },
];

function statText(s: PaperRun["status"]): string {
  return s === "running" ? "运行中" : s === "paused" ? "已暂停" : "停止";
}
function statColor(s: PaperRun["status"]): DeskColor {
  return s === "running" ? "up" : s === "paused" ? "warn" : "muted";
}

export function findRun(id: string): PaperRun {
  return RUNS.find((r) => r.id === id) ?? RUNS[0];
}

export function runCountLabel(): string {
  const running = RUNS.filter((r) => r.status === "running").length;
  return `${RUNS.length} 个 · ${running} 跑`;
}

export function buildRunList(selRun: string): RunListItem[] {
  return RUNS.map((r) => ({
    id: r.id,
    name: r.name,
    marketLabel: r.market === "equity_cn" ? "A股" : "加密",
    days: r.days,
    statText: statText(r.status),
    statColor: statColor(r.status),
    total: pct(r.total),
    pnlColor: signColor(r.total),
    pulse: r.status === "running",
    active: r.id === selRun,
  }));
}

export function clockLabel(market: PaperMarket): string {
  return market === "equity_cn"
    ? "下一收盘 MTM · 16:00 CST · T−2h14m"
    : "下一收盘 MTM · 24:00 UTC · T−5h41m";
}

export function subHint(view: PaperView): string {
  switch (view) {
    case "run":
      return "实时净值 · 调度器状态";
    case "book":
      return "持仓 / 成交 / 余额";
    case "risk":
      return "会话外不可改的硬墙";
    case "review":
      return "实盘衰减 · 超额拆解";
    case "promo":
      return "PROBATION → 模拟1月 → OBSERVATION";
    case "live_access":
      return "Binance 实盘接入 · keystore / 风控 / 急停";
  }
}

// ===== RUN =====
export function runHeader(run: PaperRun): {
  name: string;
  origin: string;
  statText: string;
  statColor: DeskColor;
} {
  return {
    name: run.name,
    origin: run.origin,
    statText: statText(run.status),
    statColor: statColor(run.status),
  };
}

export function runMetrics(run: PaperRun): PaperMetric[] {
  const annual = ((run.total / run.days) * 52 * 100).toFixed(0);
  const sharpe = (1.1 + run.q).toFixed(2);
  return [
    {
      label: "今日盈亏",
      value: pct(run.today, 2),
      color: pnlColor(run.today),
      note: "MTM 截至上一收盘",
    },
    {
      label: "累计收益",
      value: pct(run.total),
      color: signColor(run.total),
      note: "模拟上线以来",
    },
    {
      label: "超额 vs " + run.bench,
      value: pct(run.excess),
      color: signColor(run.excess),
      note: "alpha 部分",
    },
    {
      label: "年化 / 夏普",
      value: `${annual}% · ${sharpe}`,
      color: "flat",
      note: "模拟段估计",
    },
  ];
}

export function runEquity(run: PaperRun): EquityPaths {
  const W = 720;
  const H = 200;
  const PAD = 8;
  const hist: number[] = [];
  let hv = 1;
  for (let i = 0; i < 30; i++) {
    hv *= 1 + 0.004 + (nz(i + run.days) - 0.5) * 0.014;
    hist.push(hv);
  }
  const paper: number[] = [hist[hist.length - 1]];
  let pv = paper[0];
  const ppd = run.days * 5;
  for (let i = 0; i < ppd; i++) {
    pv *= 1 + run.total / ppd + (nz(i * 3 + 9) - 0.5) * 0.011;
    paper.push(pv);
  }
  const allN = 30 + ppd;
  const bench: number[] = [];
  let bv = 1;
  for (let i = 0; i < allN; i++) {
    bv *= 1 + 0.0025 + (nz(i + 50) - 0.5) * 0.012;
    bench.push(bv);
  }
  return buildEquityPaths(hist, paper, bench, W, H, PAD, 30, allN);
}

export function schedRows(run: PaperRun, market: PaperMarket): SchedRow[] {
  const lastBar = market === "equity_cn" ? "15:00:02 CST" : "13:24:08 UTC";
  return [
    {
      k: "running",
      v: run.status === "running" ? "True" : "False",
      color: run.status === "running" ? "up" : "warn",
    },
    { k: "bar_interval", v: "60.0s", color: "flat" },
    { k: "bars_fed", v: String(run.days * 5 * 240 + 117), color: "flat" },
    { k: "mtm_count", v: String(run.days * 5), color: "flat" },
    { k: "last_bar_at", v: lastBar, color: "dim" },
    {
      k: "last_mtm_at",
      v: market === "equity_cn" ? "08:30 UTC" : "00:00 UTC",
      color: "dim",
    },
    { k: "last_error", v: "None", color: "up" },
  ];
}

const POS_CN: [string, string, number][] = [
  ["贵州茅台", "600519", 0.018],
  ["宁德时代", "300750", -0.009],
  ["招商银行", "600036", 0.024],
  ["比亚迪", "002594", 0.031],
  ["隆基绿能", "601012", -0.014],
  ["美的集团", "000333", 0.012],
];
const POS_CRYPTO: [string, string, number][] = [
  ["BTCUSDT", "perp", 0.022],
  ["ETHUSDT", "perp", -0.018],
  ["SOLUSDT", "perp", 0.045],
  ["BNBUSDT", "perp", 0.008],
  ["AVAXUSDT", "perp", -0.011],
  ["LINKUSDT", "perp", 0.027],
];
function posBase(market: PaperMarket): [string, string, number][] {
  return market === "crypto" ? POS_CRYPTO : POS_CN;
}

export function posPreview(market: PaperMarket): PosPreview[] {
  return posBase(market)
    .slice(0, 5)
    .map((p, i) => ({
      name: p[0],
      w: (10 + i * 1.5).toFixed(0) + "%",
      pnl: pct(p[2]),
      pnlColor: signColor(p[2]),
    }));
}

export function posCount(market: PaperMarket): number {
  return posBase(market).length;
}

// ===== BOOK =====
export function balance(market: PaperMarket): BalanceCell[] {
  const crypto = market === "crypto";
  return [
    { label: "总权益", value: crypto ? "$108,300" : "¥1,041,200" },
    { label: "可用现金", value: crypto ? "$12,840" : "¥98,600" },
    { label: "持仓市值", value: crypto ? "$95,460" : "¥942,600" },
    { label: "冻结(挂单)", value: crypto ? "$0" : "¥0" },
  ];
}

export function bookPositions(market: PaperMarket): BookPosition[] {
  const crypto = market === "crypto";
  return posBase(market).map((p, i) => {
    const entryNum = crypto ? 100 + i * 37 : 20 + i * 31;
    const entry = entryNum.toFixed(crypto ? 1 : 2);
    const mark = (entryNum * (1 + p[2])).toFixed(crypto ? 1 : 2);
    const qty = crypto
      ? (nz(i) * 3 + 0.4).toFixed(2)
      : String(Math.trunc(nz(i) * 800 + 200));
    return {
      name: p[0],
      sym: p[1],
      w: (10 + i * 1.5).toFixed(1) + "%",
      qty,
      entry,
      mark,
      pnl: pct(p[2]),
      pnlColor: signColor(p[2]),
    };
  });
}

export function fills(market: PaperMarket): Fill[] {
  const crypto = market === "crypto";
  const base = posBase(market);
  const out: Fill[] = [];
  for (let i = 0; i < 7; i++) {
    const p = base[i % base.length];
    const side: "买" | "卖" = nz(i * 5) > 0.45 ? "买" : "卖";
    out.push({
      time: `周一 14:5${i % 9}:0${i % 6}`,
      sym: `${p[0]} · ${p[1]}`,
      side,
      sideColor: side === "买" ? "up" : "down",
      qty: crypto
        ? (nz(i + 2) * 2 + 0.2).toFixed(2)
        : String(Math.trunc(nz(i) * 400 + 100)),
      price: crypto ? (100 + i * 23).toFixed(1) : (20 + i * 17).toFixed(2),
      fee: crypto
        ? "$" + (nz(i) * 3 + 0.4).toFixed(2)
        : "¥" + (nz(i) * 8 + 1.2).toFixed(1),
    });
  }
  return out;
}

// ===== RISK ===== （门限发布时冻结，会话外不可改——locked 标记硬门）
export function riskGates(): RiskGate[] {
  return [
    {
      k: "单笔名义上限",
      cur: "8.4%",
      limit: "10%",
      pct: "84%",
      color: "warn",
      locked: false,
      breach: false,
    },
    {
      k: "杠杆",
      cur: "1.0×",
      limit: "1.0×",
      pct: "100%",
      color: "up",
      locked: true,
      breach: false,
    },
    {
      k: "周换手",
      cur: "42%",
      limit: "60%",
      pct: "70%",
      color: "up",
      locked: false,
      breach: false,
    },
    {
      k: "回撤熔断",
      cur: "−6.1%",
      limit: "−20%",
      pct: "31%",
      color: "up",
      locked: true,
      breach: false,
    },
    {
      k: "单行业暴露",
      cur: "23%",
      limit: "30%",
      pct: "77%",
      color: "up",
      locked: false,
      breach: false,
    },
    {
      k: "单票上限",
      cur: "9.6%",
      limit: "10%",
      pct: "96%",
      color: "down",
      locked: false,
      breach: true,
    },
  ];
}

export function violations(): ViolationEntry[] {
  return [
    {
      title: "单票上限触线预警",
      titleColor: "warn",
      detail: "比亚迪权重升至 9.6%，逼近 10% 硬限。下一调仓自动降配至 8.5%。",
      when: "周二 09:31",
      hash: "0x7af3…21bc",
      color: "warn",
      line: true,
    },
    {
      title: "回撤熔断 · 未触发",
      titleColor: "up",
      detail: "盘中最大回撤 −6.1%，距 −20% 熔断线安全。",
      when: "周一 14:55",
      hash: "0x3c1d…88a0",
      color: "up",
      line: true,
    },
    {
      title: "门限冻结快照",
      titleColor: "muted",
      detail: "策略发布时写入门限哈希，会话内任何改动请求被拒绝并记录。",
      when: "上线 · D0",
      hash: "0x0091…ff42",
      color: "muted",
      line: false,
    },
  ];
}

// ===== REVIEW ===== （实盘衰减不折叠不染绿：劣化项保留黄/红，R25）
export function reviewRows(): ReviewRow[] {
  return [
    { k: "年化收益", bt: "+22.4%", paper: "+18.9%", decay: "−16%", decayColor: "warn" },
    { k: "夏普", bt: "1.84", paper: "1.52", decay: "−17%", decayColor: "warn" },
    {
      k: "最大回撤",
      bt: "−11.2%",
      paper: "−6.1%",
      decay: "好于预期",
      decayColor: "up",
    },
    { k: "IC 命中率", bt: "57%", paper: "54%", decay: "−3pt", decayColor: "warn" },
    { k: "周换手", bt: "38%", paper: "42%", decay: "+4pt", decayColor: "down" },
  ];
}

export const REVIEW_NOTE =
  "实盘衰减 ~16%，落在「样本外打 7-8 折」的健康区间。衰减主因：真实滑点高于回测假设 + 涨跌停无法成交。换手略升需关注，是触发器在波动期更频繁调仓所致。";

export function attrBars(): AttrBar[] {
  const seed: [string, number][] = [
    ["动量 · vol_adj_mom", 0.62],
    ["反转 · reversal_5d", 0.28],
    ["量价 · pv_corr", 0.15],
    ["波动 · vol_ratio", -0.12],
    ["成本拖累", -0.31],
  ];
  const amax = Math.max(...seed.map((a) => Math.abs(a[1])));
  return seed.map((a) => {
    const frac = (a[1] / amax) * 0.5;
    const pos = a[1] >= 0;
    return {
      name: a[0],
      val: pct(a[1]),
      color: pos ? "up" : "down",
      left: pos ? "50%" : 50 + frac * 100 + "%",
      width: Math.abs(frac) * 100 + "%",
    };
  });
}

export function costCells(): CostCell[] {
  return [
    { label: "滑点拖累", value: "−0.21%", color: "down", note: "vs 回测假设 −0.10%" },
    { label: "手续费", value: "−0.08%", color: "down", note: "双边 万2.5" },
    { label: "未成交损失", value: "−0.05%", color: "warn", note: "涨跌停 / 流动性" },
  ];
}

// ===== PROMOTION ===== （Agent 永不自动晋级，须人工 + 验证背书 INV-5）
export function promoStages(promoted: boolean): PromoStage[] {
  const defs = [
    { label: "QUALIFIED", sub: "因子达标", glyph: "✓", reached: true, current: false },
    { label: "PROBATION", sub: "试用入池", glyph: "◐", reached: true, current: false },
    {
      label: "模拟实盘",
      sub: "1月 > 基准",
      glyph: "▦",
      reached: true,
      current: !promoted,
    },
    {
      label: "OBSERVATION",
      sub: "进观察期",
      glyph: "◉",
      reached: promoted,
      current: promoted,
    },
  ];
  return defs.map((s, i) => {
    const next = defs[i + 1];
    return {
      ...s,
      hasArrow: i < 3,
      arrowReached: s.reached && !!next && (next.reached || next.current),
    };
  });
}

export function promoEligibility(
  run: PaperRun,
  promoted: boolean,
): { daysIn: number; eligible: boolean; label: string; color: DeskColor } {
  const daysIn = run.days * 7;
  const eligible = daysIn >= 28 && run.excess > 0;
  const label = promoted
    ? "已晋级 OBSERVATION"
    : eligible
      ? "满足晋级条件"
      : `观察中 · ${daysIn}/28 天`;
  const color: DeskColor = promoted || eligible ? "up" : "warn";
  return { daysIn, eligible, label, color };
}

export function promoChecks(run: PaperRun): PromoCheck[] {
  const daysIn = run.days * 7;
  return [
    {
      t: "模拟运行满 1 个月（≥28 天）",
      v: `${daysIn} / 28 天`,
      icon: daysIn >= 28 ? "✓" : "○",
      color: daysIn >= 28 ? "up" : "warn",
    },
    {
      t: "模拟段年化 > 基准",
      v: (run.excess > 0 ? "超额 " : "") + pct(run.excess),
      icon: run.excess > 0 ? "✓" : "✕",
      color: run.excess > 0 ? "up" : "down",
    },
    { t: "风险门 0 违规", v: "全绿", icon: "✓", color: "up" },
    { t: "实盘衰减 < 30%", v: "−16%", icon: "✓", color: "up" },
  ];
}

/** 审批三态：可点（人工绿）/ 已晋级（只读描边）/ 不可点（灰禁用）。 */
export function approveState(run: PaperRun, promoted: boolean): ApproveState {
  if (promoted) return "promoted";
  const { eligible } = promoEligibility(run, promoted);
  return eligible ? "ready" : "blocked";
}

export function approveLabel(state: ApproveState): string {
  return state === "promoted" ? "✓ 已晋级 · 同步因子台" : "⤴ 人工审批晋级";
}

export function approveHint(state: ApproveState): string {
  return state === "promoted"
    ? "因子台对应因子已迁入 OBSERVATION"
    : "Agent 永不自动 · 须人工 + 验证背书（INV-5）";
}

export function promoFactors(promoted: boolean): PromoFactor[] {
  return [
    {
      id: "alpha_vol_adj_mom_20d",
      state: promoted ? "OBSERVATION" : "PROBATION",
      stateColor: promoted ? "up" : "warn",
      w: "32%",
      contrib: "+0.62%",
      contribColor: "up",
    },
    {
      id: "alpha_reversal_5d",
      state: "PROBATION",
      stateColor: "warn",
      w: "24%",
      contrib: "+0.28%",
      contribColor: "up",
    },
    {
      id: "alpha_xs_demean_log_volume",
      state: "QUALIFIED",
      stateColor: "info",
      w: "21%",
      contrib: "+0.15%",
      contribColor: "up",
    },
    {
      id: "alpha_vol_ratio",
      state: "QUALIFIED",
      stateColor: "info",
      w: "23%",
      contrib: "−0.12%",
      contribColor: "down",
    },
  ];
}

// ===== PaperBoardCard 默认 mock（PaperBoard.dc.html renderVals 默认值） =====
export function defaultBoardData(): import("./types").PaperBoardData {
  return {
    strategy: "weekly_cn_multifactor",
    days: 1,
    pnlToday: 0.006,
    totalReturn: 0.041,
    excess: 0.018,
    hist: [1, 1.2, 1.45, 1.62],
    paper: [1.62, 1.64, 1.63, 1.66, 1.69],
    positions: [
      { name: "贵州茅台", sym: "600519", w: "12%", pnl: 1.8 },
      { name: "招商银行", sym: "600036", w: "11%", pnl: 2.4 },
      { name: "比亚迪", sym: "002594", w: "10%", pnl: 3.1 },
      { name: "宁德时代", sym: "300750", w: "10%", pnl: -0.9 },
    ],
    risk: {
      maxNotional: "10%",
      leverage: 1,
      turnover: "60%/周",
      ddHalt: "20%",
    },
  };
}
