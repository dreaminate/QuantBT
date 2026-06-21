/**
 * 模拟台领域类型（对齐 paperDeck.md ③ + 后端 PaperSchedulerState / paper_venue）。
 * 落地时这些字段映射真实 /api/paper/* 响应；当前由 mock.ts 填充（挂 MockBadge 诚实标注）。
 */

export type PaperView = "run" | "book" | "risk" | "review" | "promo" | "live_access";
export type PaperMarket = "equity_cn" | "crypto";
export type PaperRunStatus = "running" | "paused" | "stopped";

/** 语义色 token key（统一映射 --desk-*，禁裸 hex）。 */
export type DeskColor =
  | "up" // 涨/正 → success
  | "down" // 跌/负 → danger
  | "warn" // 警告/黄 → warning
  | "info" // 蓝（因子 QUALIFIED）
  | "flat" // 平 → text-soft
  | "dim" // text-dim
  | "muted"; // text-muted

export interface PaperRun {
  id: string;
  name: string;
  origin: string;
  market: PaperMarket;
  status: PaperRunStatus;
  days: number;
  bench: string;
  total: number;
  today: number;
  excess: number;
  q: number;
}

export interface RunListItem {
  id: string;
  name: string;
  marketLabel: string;
  days: number;
  statText: string;
  statColor: DeskColor;
  total: string;
  pnlColor: DeskColor;
  pulse: boolean;
  active: boolean;
}

export interface PaperMetric {
  label: string;
  value: string;
  color: DeskColor;
  note: string;
}

export interface SchedRow {
  k: string;
  v: string;
  color: DeskColor;
}

export interface PosPreview {
  name: string;
  w: string;
  pnl: string;
  pnlColor: DeskColor;
}

export interface BalanceCell {
  label: string;
  value: string;
}

export interface BookPosition {
  name: string;
  sym: string;
  w: string;
  qty: string;
  entry: string;
  mark: string;
  pnl: string;
  pnlColor: DeskColor;
}

export interface Fill {
  time: string;
  sym: string;
  side: "买" | "卖";
  sideColor: DeskColor;
  qty: string;
  price: string;
  fee: string;
}

export interface RiskGate {
  k: string;
  cur: string;
  limit: string;
  pct: string;
  color: DeskColor;
  /** 冻结门：会话外不可改的硬门（杠杆 / 回撤熔断）。 */
  locked: boolean;
  /** 超限格：边框染危险色。 */
  breach: boolean;
}

export interface ViolationEntry {
  title: string;
  titleColor: DeskColor;
  detail: string;
  when: string;
  hash: string;
  color: DeskColor;
  line: boolean;
}

export interface ReviewRow {
  k: string;
  bt: string;
  paper: string;
  decay: string;
  decayColor: DeskColor;
}

export interface AttrBar {
  name: string;
  val: string;
  color: DeskColor;
  left: string;
  width: string;
}

export interface CostCell {
  label: string;
  value: string;
  color: DeskColor;
  note: string;
}

export interface PromoStage {
  label: string;
  sub: string;
  glyph: string;
  reached: boolean;
  current: boolean;
  hasArrow: boolean;
  arrowReached: boolean;
}

export interface PromoCheck {
  t: string;
  v: string;
  icon: string;
  color: DeskColor;
}

export type ApproveState = "ready" | "promoted" | "blocked";

export interface PromoFactor {
  id: string;
  state: "QUALIFIED" | "PROBATION" | "OBSERVATION";
  stateColor: DeskColor;
  w: string;
  contrib: string;
  contribColor: DeskColor;
}

/** PaperBoardCard 外部注入数据（PaperBoard.dc.html props.board）。 */
export interface PaperBoardData {
  strategy: string;
  days: number;
  pnlToday: number;
  totalReturn: number;
  excess: number;
  hist: number[];
  paper: number[];
  positions: { name: string; sym: string; w: string; pnl: number }[];
  risk: {
    maxNotional: string;
    leverage: number;
    turnover: string;
    ddHalt: string;
  };
}
