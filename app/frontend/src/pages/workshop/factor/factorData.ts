/**
 * 因子台 F1 mock 数据层（规格：dev/research/findings/desk-handoff/factorDeck.md
 * + docs/design/handoff/project/因子台.dc.html）。
 *
 * 诚实不变量：
 * - 本文件全是 mock（除因子库列表可由 FactorDeskPage 接 GET /api/factors 覆盖）；
 *   凡渲染 mock 区块的 view 必挂 <MockBadge/>。
 * - 零硬编码色值：状态/族色一律映射 --desk-* token；alpha 填充用 color-mix(token)。
 * - 阈值判定（五态机 / IC / audit）严格按 R25：弱点不染绿、不假绿灯。
 */

export type LifecycleState =
  | "NEW"
  | "QUALIFIED"
  | "PROBATION"
  | "OBSERVATION"
  | "WARNING"
  | "RETIRED";

export type FactorFamily = "动量" | "反转" | "波动" | "量价" | "形态";

export type Market = "equity_cn" | "crypto";

/** 单个 horizon 的衰减点。 */
export interface DecayPoint {
  h: number;
  ic: number;
}

/** mock 因子完整记录（合成 IC 序列 / 衰减 / 分层）。 */
export interface MockFactor {
  id: string;
  formula: string;
  desc: string;
  fam: FactorFamily;
  state: LifecycleState;
  why: string;
  icMean: number;
  icIr: number;
  rankIc: number;
  sampleT: number;
  /** 60 日 daily IC 序列。 */
  series: number[];
  decay: DecayPoint[];
  /** 5 分位累计净值，每组 40 期。 */
  layers: number[][];
}

/** 后端 GET /api/factors 真实字段子集（用于覆盖列表展示）。 */
export interface ApiFactorItem {
  factor_id: string;
  version: number;
  formula: string;
  lifecycle_state: string;
  description?: string;
  ic_summary?: { ic_mean?: number; rank_ic_mean?: number } | null;
}

export const LIFECYCLE_PATH: LifecycleState[] = [
  "NEW",
  "QUALIFIED",
  "PROBATION",
  "OBSERVATION",
  "WARNING",
  "RETIRED",
];

/** 状态色：映射到 --desk-* token（零裸 hex）。 */
export function stateColorVar(s: LifecycleState): string {
  switch (s) {
    case "NEW":
      return "var(--desk-text-muted)";
    case "QUALIFIED":
      return "var(--desk-info)";
    case "PROBATION":
      return "var(--desk-warning)";
    case "OBSERVATION":
      return "var(--desk-success)";
    case "WARNING":
      return "var(--desk-warning)";
    case "RETIRED":
      return "var(--desk-danger)";
  }
}

/** 状态淡底（alpha 14%），用 token 做 color-mix，避免裸 rgba/hex。 */
export function stateBgVar(s: LifecycleState): string {
  return `color-mix(in srgb, ${stateColorVar(s)} 14%, transparent)`;
}

/** 因子族色：映射到 --desk-* token。 */
export function famColorVar(f: FactorFamily): string {
  switch (f) {
    case "动量":
      return "var(--desk-accent)";
    case "反转":
      return "var(--desk-info)";
    case "波动":
      return "var(--desk-warning)";
    case "量价":
      return "var(--desk-success)";
    case "形态":
      return "var(--desk-ghost)";
  }
}

export function famBgVar(f: FactorFamily): string {
  return `color-mix(in srgb, ${famColorVar(f)} 14%, transparent)`;
}

/**
 * IC 阈值色（R25：弱点不染绿）：>=0.02 绿、<=0 红、之间中性（非绿）。
 */
export function icThresholdColor(v: number): string {
  if (v >= 0.02) return "var(--desk-success)";
  if (v <= 0) return "var(--desk-danger)";
  return "var(--desk-text-soft)";
}

/** IC-IR 阈值色：>=0.5 绿、<=0 红、之间黄（边际，非绿）。 */
export function irThresholdColor(v: number): string {
  if (v >= 0.5) return "var(--desk-success)";
  if (v <= 0) return "var(--desk-danger)";
  return "var(--desk-warning)";
}

/** sample-t 阈值色：|t|>=3 绿、否则黄（证据不足，非绿）。 */
export function tThresholdColor(v: number): string {
  return Math.abs(v) >= 3 ? "var(--desk-success)" : "var(--desk-warning)";
}

/** 确定性伪随机（与 DC `_nz` 同式，保证 SSR/测试稳定）。 */
export function nz(i: number): number {
  const x = Math.sin(i * 12.9898 + 7.13) * 43758.5453;
  return x - Math.floor(x);
}

/** 柱状路径（日度 IC）：每根柱从中线 mid 画到值高度。 */
export function svgBars(series: number[], w: number, h: number, mid: number): string {
  const n = series.length;
  const max = Math.max(0.08, ...series.map((v) => Math.abs(v)));
  let d = "";
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * w;
    const y = mid - (series[i] / max) * (h * 0.42);
    d += `M${x.toFixed(1)} ${mid} L${x.toFixed(1)} ${y.toFixed(1)} `;
  }
  return d.trim();
}

/** 折线路径（分层 / 累计 IC）。 */
export function svgLine(
  arr: number[],
  w: number,
  h: number,
  lo: number,
  hi: number,
  pad = 0,
): string {
  const n = arr.length;
  const span = hi - lo || 1;
  return arr
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${((i / (n - 1)) * w).toFixed(1)} ${(
          h -
          pad -
          ((v - lo) / span) * (h - 2 * pad)
        ).toFixed(1)}`,
    )
    .join(" ");
}

/** mock 种子表：[id, formula, desc, fam, state, quality, why]。 */
const SEED: [string, string, string, FactorFamily, LifecycleState, number, string][] = [
  ["alpha_vol_adj_mom_20d", "ts_pct_change(close,20) / ts_std(ts_pct_change(close,1),20)", "波动调整 1 月动量（夏普风格）", "动量", "OBSERVATION", 0.93, "纯动量在高波动股上失真。除以已实现波动 → 单位风险的动量，等价于截面 Sharpe 排序。机构里这是最稳的一档趋势因子。"],
  ["alpha_mom_xs_20d", "rank(ts_pct_change(close,20))", "1 月动量截面排名", "动量", "OBSERVATION", 0.8, "把 20 日收益做截面 rank，去掉绝对幅度只留相对强弱。A 股周频里中期动量比短期更干净。"],
  ["alpha_xs_winsor_mom20", "cs_winsorize(ts_pct_change(close,20))", "1 月动量截面截尾", "动量", "PROBATION", 0.64, "动量尾部常被妖股污染。截尾后 IC 更稳，IR 提升明显——牺牲一点峰值换稳定。"],
  ["alpha_reversal_5d", "neg(ts_pct_change(close,5))", "1 周反转", "反转", "PROBATION", 0.66, "短周期 A 股散户主导，超跌反弹强。取 5 日收益的负向作短反转。"],
  ["alpha_price_volume_corr_20d", "ts_corr(close,volume,20)", "20 日价量相关性（Alpha#6 近亲）", "量价", "PROBATION", 0.6, "价涨量增=健康趋势，价涨量缩=背离。20 日滚动相关刻画这种价量配合。"],
  ["alpha_xs_demean_log_volume", "cs_demean(log(volume + 1))", "成交量对数截面去均值（Alpha#2 近亲）", "量价", "QUALIFIED", 0.55, "对数压缩量纲，截面去均值得到相对活跃度。流动性溢价的代理。"],
  ["alpha_reversal_residual_20d", "neg(ts_zscore(close,20))", "20 日 z-score 反转（高于均值看空）", "反转", "QUALIFIED", 0.52, "价格偏离 20 日均值越多越可能回归。z-score 标准化后取负。"],
  ["alpha_ema_cross", "ts_ema(close,5) - ts_ema(close,20)", "EMA 5-20 金叉", "动量", "QUALIFIED", 0.5, "经典双均线，EMA 比 SMA 更跟手。差值正=短期强于长期。"],
  ["alpha_vol_ratio", "ts_std(ts_pct_change(close,1),5) / ts_std(ts_pct_change(close,1),60)", "短/长期波动率比", "波动", "QUALIFIED", 0.48, "短波/长波 > 1 表示波动放大，常先于趋势转折。低波异象的时序版。"],
  ["alpha_sma_dev_20d", "(close - ts_mean(close,20)) / ts_mean(close,20)", "20 日均线偏离", "反转", "NEW", 0.4, "价格相对均线的百分比偏离，均值回归的朴素代理。刚入库待观察。"],
  ["alpha_skew_returns_60d", "ts_skew(ts_pct_change(close,1),60)", "60 日收益偏度", "波动", "NEW", 0.35, "右偏（彩票偏好）股票长期跑输。偏度因子捕捉这种行为定价。"],
  ["alpha_close_in_range_5d", "(close - ts_min(low,5)) / (ts_max(high,5) - ts_min(low,5))", "Stochastic K 形式", "形态", "NEW", 0.3, "收盘在 5 日高低区间的相对位置，超买超卖形态。"],
  ["alpha_vol_to_avg_20d", "volume / ts_mean(volume,20)", "量比", "量价", "WARNING", 0.27, "曾经有效的量比因子，近 30 日 IC 衰减过半——拥挤后失效，进 WARNING。"],
  ["alpha_mom_1d", "ts_pct_change(close,1)", "1 日动量", "动量", "WARNING", 0.22, "日频动量噪声大、换手高，扣费后所剩无几。仅作组合微调，不单用。"],
  ["alpha_drawdown_60d", "ts_min(close,60) / ts_max(close,60)", "60 日最大回撤近似", "波动", "RETIRED", 0.12, "回撤代理与已有低波因子高度共线，且 IR 长期为负。已退役。"],
  ["alpha_volume_growth_5d", "ts_pct_change(volume,5)", "成交量 5 日变化", "量价", "RETIRED", 0.1, "量变化方向不稳定，多空两侧都无显著超额。退役保留作对照。"],
];

const HORIZONS = [1, 3, 5, 10, 20];

/** 合成 mock 因子全集（确定性，无副作用）。 */
export function buildMockFactors(): MockFactor[] {
  return SEED.map(([id, formula, desc, fam, state, q, why], i) => {
    const base = q * 0.075 - 0.012;
    const decaying = state === "WARNING";
    const dead = state === "RETIRED";
    const icMean = dead ? (nz(i) - 0.55) * 0.02 : base;
    const icIr = dead ? -0.1 - nz(i + 3) * 0.2 : q * 1.7;
    const rankIc = icMean * 1.06;
    const sampleT = icIr * 3.1;

    const series: number[] = [];
    for (let k = 0; k < 60; k++) {
      let mu = icMean;
      if (decaying) mu = icMean * (1 - 0.7 * (k / 59));
      series.push(mu + (nz(i * 31 + k) - 0.5) * 0.05);
    }

    const peak = dead ? 1 : i % 2 === 0 ? 5 : 3;
    const decay: DecayPoint[] = HORIZONS.map((h) => {
      const dist = Math.abs(h - peak);
      let v = icMean * Math.exp(-dist / (decaying ? 5 : 9)) * (h <= peak ? 0.6 + (0.4 * h) / peak : 1);
      if (dead) v = (nz(i + h) - 0.55) * 0.018;
      return { h, ic: v };
    });

    const layers: number[][] = [];
    for (let b = 0; b < 5; b++) {
      const arr: number[] = [];
      let cum = 1;
      const tilt = dead ? (nz(i + b) - 0.5) * 0.0008 : (b - 2) * (icMean * 0.06);
      for (let t = 0; t < 40; t++) {
        cum *= 1 + tilt + (nz(i * 17 + b * 7 + t) - 0.5) * 0.012;
        arr.push(cum);
      }
      layers.push(arr);
    }

    return {
      id,
      formula,
      desc,
      fam,
      state,
      why,
      icMean,
      icIr,
      rankIc,
      sampleT,
      series,
      decay,
      layers,
    };
  });
}

export interface LifecycleEventRow {
  from: string;
  to: LifecycleState;
  reason: string;
  when: string;
  color: string;
  line: boolean;
}

const EVENT_REASONS: Record<string, string> = {
  QUALIFIED: "|IC|>0.03 且 IR>0.5 且 t>3 — 自动入选",
  PROBATION: "连续 3 月 IC 不为负 — 进试用",
  OBSERVATION: "模拟实盘 1 月年化 > 基准 — 进观察",
  WARNING: "30 日 IC 衰减 >50% — 触发预警",
  RETIRED: "连续 2 周 WARNING 未修复 — 退役",
};

const EVENT_DAYS = [
  "2026-05-27",
  "2026-05-29",
  "2026-06-05",
  "2026-06-12",
  "2026-06-18",
  "2026-06-20",
];

/** 该因子从 NEW 到当前态的迁移事件链（最新在上）。 */
export function eventsFor(f: MockFactor): LifecycleEventRow[] {
  const idx = LIFECYCLE_PATH.indexOf(f.state);
  const out: LifecycleEventRow[] = [];
  for (let k = idx; k >= 1; k--) {
    const to = LIFECYCLE_PATH[k];
    out.push({
      from: LIFECYCLE_PATH[k - 1],
      to,
      reason: EVENT_REASONS[to] ?? "",
      when: `${EVENT_DAYS[k]} · 自动迁移`,
      color: stateColorVar(to),
      line: k > 1,
    });
  }
  if (idx === 0) {
    out.push({
      from: "—",
      to: "NEW",
      reason: "表达式注册入库 · 初始态",
      when: `${EVENT_DAYS[0]} · 自动迁移`,
      color: stateColorVar("NEW"),
      line: false,
    });
  }
  return out;
}

/** 五态机节点 glyph。 */
export const STATE_GLYPH: Record<LifecycleState, string> = {
  NEW: "○",
  QUALIFIED: "✓",
  PROBATION: "◐",
  OBSERVATION: "◉",
  WARNING: "!",
  RETIRED: "×",
};

/** 五态机节点副标。 */
export const STATE_SUB: Record<LifecycleState, string> = {
  NEW: "刚注册",
  QUALIFIED: "IC达标",
  PROBATION: "试用中",
  OBSERVATION: "模拟观察",
  WARNING: "IC衰减",
  RETIRED: "已退役",
};

/** 五态机节点间阈值标注（5 段连线）。 */
export const STATE_THRESH = [
  "IC>.03·IR>.5",
  "3月IC≥0",
  "实盘>基准",
  "衰减>50%",
  "2周未修复",
];

export const MARKET_POOL: Record<Market, string> = {
  equity_cn: "中证全 A · 4870 标的 · 周频",
  crypto: "USDT 永续 · 312 标的 · 日频",
};
