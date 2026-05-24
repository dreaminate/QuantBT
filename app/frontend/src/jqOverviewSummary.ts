/**
 * JoinQuant「收益概述」指标：固定顺序与标签，仅消费后端 `jq_overview_metrics`。
 */

import type { JqOverviewMetrics } from "./types";
import { formatNumber, formatPct } from "./utils";

export type MetricFormat = "pct" | "num" | "text";

export type SummaryMetricDef = {
  key: keyof JqOverviewMetrics;
  label: string;
  format: MetricFormat;
  row: 1 | 2;
  order: number;
};

/** 与 JoinQuant 一致的两行、顺序固定（勿改 order） */
export const JQ_OVERVIEW_SUMMARY_DEFS: readonly SummaryMetricDef[] = [
  { key: "strategy_return", label: "策略收益", format: "pct", row: 1, order: 1 },
  { key: "strategy_annual_return", label: "策略年化收益", format: "pct", row: 1, order: 2 },
  { key: "excess_return", label: "超额收益", format: "pct", row: 1, order: 3 },
  { key: "benchmark_return", label: "基准收益", format: "pct", row: 1, order: 4 },
  { key: "alpha", label: "阿尔法", format: "pct", row: 1, order: 5 },
  { key: "beta", label: "贝塔", format: "num", row: 1, order: 6 },
  { key: "sharpe_ratio", label: "夏普比率", format: "num", row: 1, order: 7 },
  { key: "win_rate", label: "胜率", format: "pct", row: 1, order: 8 },
  { key: "profit_loss_ratio", label: "盈亏比", format: "num", row: 1, order: 9 },
  { key: "max_drawdown", label: "最大回撤", format: "pct", row: 1, order: 10 },
  { key: "sortino_ratio", label: "索提诺比率", format: "num", row: 1, order: 11 },
  { key: "avg_daily_excess_return", label: "日均超额收益", format: "pct", row: 2, order: 1 },
  { key: "excess_max_drawdown", label: "超额收益最大回撤", format: "pct", row: 2, order: 2 },
  { key: "excess_sharpe_ratio", label: "超额收益夏普比率", format: "num", row: 2, order: 3 },
  { key: "daily_win_rate", label: "日胜率", format: "pct", row: 2, order: 4 },
  { key: "profit_count", label: "盈利次数", format: "num", row: 2, order: 5 },
  { key: "loss_count", label: "亏损次数", format: "num", row: 2, order: 6 },
  { key: "information_ratio", label: "信息比率", format: "num", row: 2, order: 7 },
  { key: "strategy_volatility", label: "策略波动率", format: "pct", row: 2, order: 8 },
  { key: "benchmark_volatility", label: "基准波动率", format: "pct", row: 2, order: 9 },
  { key: "max_drawdown_period", label: "最大回撤区间", format: "text", row: 2, order: 10 },
] as const;

export type SummaryMetricValue = {
  key: string;
  label: string;
  format: MetricFormat;
  row: 1 | 2;
  order: number;
  raw: unknown;
  display: string;
  tone: "positive" | "negative" | "normal";
};

function safeNum(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function toneForMetric(def: SummaryMetricDef, raw: unknown): "positive" | "negative" | "normal" {
  if (def.format === "text") return "normal";
  const n = safeNum(raw);
  if (n === null) return "normal";
  /* 聚宽：贝塔、盈亏比多为黑字；回撤类负值为绿 */
  if (def.key === "beta" || def.key === "profit_loss_ratio") return "normal";
  if (def.key === "max_drawdown" || def.key === "excess_max_drawdown") {
    return n < 0 ? "negative" : "normal";
  }
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "normal";
}

function formatMaxDrawdownPeriod(raw: unknown): string {
  if (!raw) return "—";
  if (Array.isArray(raw) && raw.length === 2) {
    const a = String(raw[0]).slice(0, 10);
    const b = String(raw[1]).slice(0, 10);
    if (a && b) return `${a} ~ ${b}`;
  }
  return "—";
}

export function formatJqMetricCell(def: SummaryMetricDef, raw: unknown): string {
  if (def.key === "max_drawdown_period") {
    return formatMaxDrawdownPeriod(raw);
  }
  if (def.format === "text") {
    const t = String(raw ?? "").trim();
    return t || "—";
  }
  const n = safeNum(raw);
  if (n === null) return "—";
  if (def.format === "pct") return formatPct(n);
  if (def.format === "num") {
    if (def.key === "profit_count" || def.key === "loss_count") return formatNumber(n, 0);
    return formatNumber(n);
  }
  return "—";
}

export function buildJqSummaryRows(metrics: JqOverviewMetrics | undefined | null): { row1: SummaryMetricValue[]; row2: SummaryMetricValue[] } {
  const m = metrics ?? ({} as JqOverviewMetrics);
  const row1: SummaryMetricValue[] = [];
  const row2: SummaryMetricValue[] = [];
  for (const def of JQ_OVERVIEW_SUMMARY_DEFS) {
    const raw = m[def.key];
    const display = formatJqMetricCell(def, raw);
    const item: SummaryMetricValue = {
      key: def.key,
      label: def.label,
      format: def.format,
      row: def.row,
      order: def.order,
      raw,
      display,
      tone: toneForMetric(def, raw),
    };
    if (def.row === 1) row1.push(item);
    else row2.push(item);
  }
  row1.sort((a, b) => a.order - b.order);
  row2.sort((a, b) => a.order - b.order);
  return { row1, row2 };
}
