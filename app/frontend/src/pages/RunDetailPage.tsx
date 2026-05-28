import type { ChangeEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import type { ECharts } from "echarts";
import type { EChartsOption } from "echarts";
import { useParams } from "react-router-dom";

import {
  buildArtifactDownloadUrl,
  buildRunExportUrl,
  getRun,
  getRunAttribution,
  getRunLogs,
  getRunSeries,
  getRunSource,
} from "../api";
import { JqDailyHoldingsPanel } from "../components/JqDailyHoldingsPanel";
import { JqTradesPanel } from "../components/JqTradesPanel";
import type {
  JqOverviewMetrics,
  RunAttributionResponse,
  RunDetail,
  RunSeriesPoint,
  SeriesName,
} from "../types";
import { buildJqSummaryRows } from "../jqOverviewSummary";
import { getGlossarySlugForMetric } from "../features/glossary/metricGlossaryMap";
import { GlossaryInfoButton } from "../features/glossary/GlossaryInfoButton";
import { formatFileSize, formatNumber, formatPct } from "../utils";

type DetailContentTab =
  | "overview"
  | "trade_detail"
  | "daily_position"
  | "log_output"
  | "performance"
  | "strategy_code"
  | "report"
  | "attribution"
  | "metric_strategy_return"
  | "metric_benchmark_return"
  | "metric_alpha"
  | "metric_beta"
  | "metric_sharpe"
  | "metric_sortino"
  | "metric_ir"
  | "metric_volatility"
  | "metric_bm_volatility"
  | "metric_max_drawdown";

type MetricFormat = "pct" | "num" | "text";

type OverviewRow = {
  date: string;
  strategyReturn?: number;
  benchmarkReturn?: number;
  /** 累计超额 (1+Rs)/(1+Rb)-1，与 jq_overview_metrics.excess_return 同源语义（序列上为逐点） */
  excessReturn?: number;
  /** 策略每日收益率（小数），用于第二层每日盈亏柱 */
  dailyStrategyReturn?: number;
  dailyBuy?: number;
  dailySell?: number;
};

/** 主图折线：策略 / 超额 / 基准 显隐与 Y 轴线性或对数（ wealth = 1+r ） */
type OverviewMainChartView = {
  yMode: "linear" | "log";
  showStrategy: boolean;
  showExcess: boolean;
  showBenchmark: boolean;
};

/** 图表可视时间窗口（与顶部日期、dataZoom 单一数据源） */
type VisibleRange = {
  start: string;
  end: string;
};

const SIDEBAR_GROUPS: Array<{ title: string; items: Array<{ key: DetailContentTab; label: string }> }> = [
  {
    title: "功能视图",
    items: [
      { key: "overview", label: "收益概述" },
      { key: "trade_detail", label: "交易详情" },
      { key: "daily_position", label: "每日持仓&收益" },
      { key: "log_output", label: "日志输出" },
      { key: "performance", label: "性能分析" },
      { key: "strategy_code", label: "策略代码" },
      { key: "report", label: "Markdown 报告" },
      { key: "attribution", label: "归因" },
    ],
  },
  {
    title: "指标页",
    items: [
      { key: "metric_strategy_return", label: "策略收益" },
      { key: "metric_benchmark_return", label: "基准收益" },
      { key: "metric_alpha", label: "阿尔法" },
      { key: "metric_beta", label: "贝塔" },
      { key: "metric_sharpe", label: "夏普比率" },
      { key: "metric_sortino", label: "索提诺比率" },
      { key: "metric_ir", label: "信息比率" },
      { key: "metric_volatility", label: "波动率" },
      { key: "metric_bm_volatility", label: "基准波动率" },
      { key: "metric_max_drawdown", label: "最大回撤" },
    ],
  },
];

const METRIC_PAGE_CONFIG: Record<
  Exclude<
    DetailContentTab,
    "overview" | "trade_detail" | "daily_position" | "log_output" | "performance" | "strategy_code" | "report" | "attribution"
  >,
  { series: SeriesName; title: string; color: string; format: MetricFormat }
> = {
  metric_strategy_return: { series: "strategy_return", title: "策略收益", color: "#2f6fdd", format: "pct" },
  metric_benchmark_return: { series: "benchmark_return", title: "基准收益", color: "#d34f4f", format: "pct" },
  metric_alpha: { series: "alpha", title: "阿尔法", color: "#7e5ab6", format: "pct" },
  metric_beta: { series: "beta", title: "贝塔", color: "#2e8b57", format: "num" },
  metric_sharpe: { series: "sharpe", title: "夏普比率", color: "#21618c", format: "num" },
  metric_sortino: { series: "sortino", title: "索提诺比率", color: "#d68910", format: "num" },
  metric_ir: { series: "information_ratio", title: "信息比率", color: "#5b6c7d", format: "num" },
  metric_volatility: { series: "volatility", title: "波动率", color: "#6c3483", format: "pct" },
  metric_bm_volatility: { series: "benchmark_volatility", title: "基准波动率", color: "#7b7d7d", format: "pct" },
  metric_max_drawdown: { series: "max_drawdown", title: "最大回撤", color: "#b42318", format: "pct" },
};

function useRunSeriesQuery(runId: string, series: SeriesName, enabled = true) {
  return useQuery({
    queryKey: ["jq-run-series", runId, series],
    queryFn: () => getRunSeries(runId, series, "overall"),
    enabled: enabled && Boolean(runId),
    staleTime: 10_000,
  });
}

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}

function toDateLabel(value?: string | null) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function safeNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatMetricValue(value: unknown, format: MetricFormat) {
  const number = safeNumber(value);
  if (format === "text") {
    const text = String(value ?? "").trim();
    return text || "—";
  }
  if (number === null) {
    return "—";
  }
  if (format === "pct") {
    return formatPct(number);
  }
  return format === "num" && Number.isInteger(number) ? formatNumber(number, 0) : formatNumber(number);
}

function metricClass(value: unknown) {
  const number = safeNumber(value);
  if (number === null) return "";
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "";
}

function normalizeEquityPoints(points: RunSeriesPoint[]) {
  const first = safeNumber(points[0]?.value);
  if (!first || first === 0) {
    return new Map<string, number>();
  }
  return new Map(points.filter((point) => point.timestamp).map((point) => [toDateLabel(point.timestamp), Number(point.value) / first]));
}

function normalizeBenchmarkPoints(points: RunSeriesPoint[]) {
  return new Map(points.filter((point) => point.timestamp).map((point) => [toDateLabel(point.timestamp), Number(point.value) + 1]));
}

function buildDateAxis(...seriesGroups: Array<RunSeriesPoint[]>) {
  return Array.from(
    new Set(
      seriesGroups.flatMap((points) => points.map((point) => toDateLabel(point.timestamp)).filter((value) => value.length > 0)),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

function buildOverviewRows(
  equityPoints: RunSeriesPoint[],
  benchmarkPoints: RunSeriesPoint[],
  dailyBuyPoints: RunSeriesPoint[],
  dailySellPoints: RunSeriesPoint[],
) {
  const dates = buildDateAxis(equityPoints, benchmarkPoints, dailyBuyPoints, dailySellPoints);
  const equityMap = normalizeEquityPoints(equityPoints);
  const benchmarkMap = normalizeBenchmarkPoints(benchmarkPoints);
  const buyMap = new Map(dailyBuyPoints.map((point) => [toDateLabel(point.timestamp), Number(point.value)]));
  const sellMap = new Map(dailySellPoints.map((point) => [toDateLabel(point.timestamp), Number(point.value)]));

  let previousStrategyNav: number | null = null;
  const rows: OverviewRow[] = [];
  for (const date of dates) {
    const strategyNav = equityMap.get(date);
    const benchmarkNav = benchmarkMap.get(date);
    const strategyReturn = strategyNav !== undefined ? strategyNav - 1 : undefined;
    const benchmarkReturn = benchmarkNav !== undefined ? benchmarkNav - 1 : undefined;
    let excessReturn: number | undefined;
    if (strategyReturn !== undefined && benchmarkReturn !== undefined) {
      excessReturn = (1 + strategyReturn) / (1 + benchmarkReturn) - 1;
    }
    let dailyStrategyReturn: number | undefined;
    if (strategyNav !== undefined) {
      dailyStrategyReturn =
        previousStrategyNav && previousStrategyNav !== 0 ? strategyNav / previousStrategyNav - 1 : 0;
    }
    rows.push({
      date,
      strategyReturn,
      benchmarkReturn,
      excessReturn,
      dailyStrategyReturn,
      dailyBuy: buyMap.get(date),
      dailySell: sellMap.get(date),
    });
    if (strategyNav !== undefined) previousStrategyNav = strategyNav;
  }
  return rows;
}

function clampVisibleRange(start: string, end: string, dates: string[]): { start: string; end: string } {
  if (!dates.length) return { start: "", end: "" };
  const lo = dates[0];
  const hi = dates[dates.length - 1];
  let s = start || lo;
  let e = end || hi;
  if (s < lo) s = lo;
  if (e > hi) e = hi;
  if (s > e) [s, e] = [e, s];
  return ensureMinCategoryDateSpan(s, e, dates);
}

/**
 * slider 用百分比映射到 category 下标时，Math.round 常把两端收成同一下标 → 可视区间只剩 1 天，图画成一条竖线。
 * 用 floor/ceil 拉开两端，并保证至少跨 1 个下标（两天）除非全序列只有一天。
 */
function percentWindowToCategoryDates(startPct: number, endPct: number, categories: string[]): { start: string; end: string } {
  const len = categories.length;
  if (len === 0) return { start: "", end: "" };
  if (len === 1) return { start: categories[0], end: categories[0] };
  const maxIdx = len - 1;
  const r0 = (startPct / 100) * maxIdx;
  const r1 = (endPct / 100) * maxIdx;
  let lo = Math.floor(Math.min(r0, r1));
  let hi = Math.ceil(Math.max(r0, r1));
  if (hi <= lo) hi = Math.min(maxIdx, lo + 1);
  return { start: categories[lo], end: categories[hi] };
}

function ensureMinCategoryDateSpan(start: string, end: string, categories: string[]): { start: string; end: string } {
  if (categories.length <= 1) return { start, end };
  const i0 = categories.indexOf(start.slice(0, 10));
  const i1 = categories.indexOf(end.slice(0, 10));
  if (i0 < 0 || i1 < 0) return { start, end };
  let lo = Math.min(i0, i1);
  let hi = Math.max(i0, i1);
  if (hi > lo) return { start: categories[lo], end: categories[hi] };
  if (hi < categories.length - 1) return { start: categories[lo], end: categories[hi + 1] };
  if (lo > 0) return { start: categories[lo - 1], end: categories[hi] };
  return { start: categories[0], end: categories[Math.min(1, categories.length - 1)] };
}

/** 全区间用 0–100% 表示，避免 startValue/endValue 贴边时第三层柱在 filter 模式下异常 */
function isFullVisibleRange(range: VisibleRange | null, categories: string[]): boolean {
  if (!range?.start || !range?.end || !categories.length) return false;
  return range.start === categories[0] && range.end === categories[categories.length - 1];
}

/** 与 buildOverviewOption / dispatchDataZoom 共用：全区间走百分比，局部走 category */
function visibleRangeToDataZoomProps(
  range: VisibleRange | null,
  categories: string[],
): Record<string, string | number> {
  if (!range?.start || !range?.end || !categories.length) return {};
  if (isFullVisibleRange(range, categories)) {
    return { start: 0, end: 100 };
  }
  const c = clampVisibleRange(range.start, range.end, categories);
  return { startValue: c.start, endValue: c.end };
}

/**
 * 从图表实例读取当前 dataZoom 窗口（优先 getOption，兼容全区间百分比与局部 category）
 * 优先读 slider：与 inside 同步时偶尔顺序不一致，避免读到窄窗口下的「单点」状态。
 */
function readVisibleRangeFromChartInstance(chart: ECharts, categories: string[]): VisibleRange | null {
  if (!categories.length) return null;
  const first = categories[0];
  const last = categories[categories.length - 1];
  const opt = chart.getOption() as {
    dataZoom?: Array<{
      type?: string;
      startValue?: string | number;
      endValue?: string | number;
      start?: number;
      end?: number;
    }>;
  };
  const list = opt.dataZoom ?? [];
  const ordered = [...list].sort((a, b) => {
    if (a.type === "slider" && b.type !== "slider") return -1;
    if (b.type === "slider" && a.type !== "slider") return 1;
    return 0;
  });
  for (const dz of ordered) {
    if (dz.startValue != null && dz.endValue != null) {
      const sv = dz.startValue;
      const ev = dz.endValue;
      if (typeof sv === "number" && typeof ev === "number") {
        const i0 = Math.min(sv, ev);
        const i1 = Math.max(sv, ev);
        let lo = Math.floor(i0);
        let hi = Math.ceil(i1);
        if (categories.length > 1 && hi <= lo) hi = Math.min(categories.length - 1, lo + 1);
        const s = categories[lo];
        const e = categories[hi];
        if (s && e) return ensureMinCategoryDateSpan(s, e, categories);
      } else {
        return ensureMinCategoryDateSpan(String(sv).slice(0, 10), String(ev).slice(0, 10), categories);
      }
    }
    if (typeof dz.start === "number" && typeof dz.end === "number") {
      return percentWindowToCategoryDates(dz.start, dz.end, categories);
    }
  }
  return { start: first, end: last };
}

/** 事件 params 兜底解析（与 readVisibleRangeFromChartInstance 二选一补充） */
function extractDataZoomRange(params: unknown, categories: string[]): { start: string; end: string } | null {
  if (!categories.length) return null;
  const first = categories[0];
  const last = categories[categories.length - 1];

  const raw = params as {
    batch?: Array<{
      startValue?: string | number;
      endValue?: string | number;
      start?: number;
      end?: number;
    }>;
    startValue?: string | number;
    endValue?: string | number;
    start?: number;
    end?: number;
  };

  const batch = raw.batch?.[0] ?? raw;
  let startV = batch.startValue;
  let endV = batch.endValue;

  if (typeof startV === "number" && typeof endV === "number") {
    const i0 = Math.min(startV, endV);
    const i1 = Math.max(startV, endV);
    let lo = Math.floor(i0);
    let hi = Math.ceil(i1);
    if (categories.length > 1 && hi <= lo) hi = Math.min(categories.length - 1, lo + 1);
    const s = categories[lo];
    const e = categories[hi];
    if (s && e) return ensureMinCategoryDateSpan(s, e, categories);
  }

  if (startV !== undefined && endV !== undefined && typeof startV !== "number") {
    return ensureMinCategoryDateSpan(String(startV).slice(0, 10), String(endV).slice(0, 10), categories);
  }

  if (typeof batch.start === "number" && typeof batch.end === "number") {
    return percentWindowToCategoryDates(batch.start, batch.end, categories);
  }

  return null;
}

/** JoinQuant 回测概览图配色 */
const JQ_GRID = "#EAEAEA";
const JQ_STRATEGY_LINE = "#4C78A8";
const JQ_BENCHMARK_LINE = "#E45756";
/** 聚宽图例：超额收益多为橙色线 */
const JQ_EXCESS_LINE = "#F28E2B";
const JQ_STRATEGY_AREA = "rgba(76, 120, 168, 0.15)";
const JQ_DAILY_POS = "#54A24B";
const JQ_DAILY_NEG = "#B279A2";
const JQ_BUY_BAR = "#4C78A8";
const JQ_SELL_BAR = "#F58518";

/**
 * 收益概述 · 三联图布局（ECharts grid 像素）。
 * —— 调图高度：只改下面「固定高度」一组数字；totalChartPx 会随公式自动变。
 * —— 调买卖图纵轴：搜 computeBuySellAxisBounds（98 分位、pad）。
 * —— 调时间缩放：搜 buildOverviewOption 里 dataZoom（inside：zoomOnMouseWheel / moveOnMouseMove；slider：height/bottom）。
 *    当前 ECharts 类型未导出 inside 的 zoomRate；若你用的 echarts 运行时支持，可在该 inside 对象里自行加 zoomRate 并配合 // @ts-expect-error。
 */
export type OverviewChartLayout = {
  legendTop: number;
  legendBlock: number;
  mainH: number;
  dailyH: number;
  tradeH: number;
  gridGap: number;
  gridTop0: number;
  gridTop1: number;
  gridTop2: number;
  totalChartPx: number;
  sliderHeight: number;
  sliderBottom: number;
};

/** 图上方留白（给 grid 顶距用，一般 2～8） */
const OVERVIEW_LEGEND_TOP = 6;
/** 与 legendTop 一起参与 gridTop0，一般很小即可 */
const OVERVIEW_LEGEND_BLOCK = 4;
/** 三个子图之间的竖向间距（px） */
const OVERVIEW_GRID_GAP = 18;
/** 底部时间轴 slider 高度（px） */
const OVERVIEW_SLIDER_H = 18;
/** slider 距容器底边（px） */
const OVERVIEW_SLIDER_BOTTOM = 18;

/** —— 自行改这三项即可调三图相对高度（像素）—— */
const MAIN_CHART_HEIGHT_PX = 360;
const DAILY_CHART_HEIGHT_PX = 160;
const TRADE_CHART_HEIGHT_PX = 160;

function getFixedOverviewChartLayout(): OverviewChartLayout {
  const mainH = MAIN_CHART_HEIGHT_PX;
  const dailyH = DAILY_CHART_HEIGHT_PX;
  const tradeH = TRADE_CHART_HEIGHT_PX;
  const gridTop0 = OVERVIEW_LEGEND_TOP + OVERVIEW_LEGEND_BLOCK;
  const gridTop1 = gridTop0 + mainH + OVERVIEW_GRID_GAP;
  const gridTop2 = gridTop1 + dailyH + OVERVIEW_GRID_GAP;
  const totalChartPx =
    OVERVIEW_LEGEND_TOP +
    OVERVIEW_LEGEND_BLOCK +
    mainH +
    OVERVIEW_GRID_GAP +
    dailyH +
    OVERVIEW_GRID_GAP +
    tradeH +
    OVERVIEW_SLIDER_BOTTOM +
    OVERVIEW_SLIDER_H;

  return {
    legendTop: OVERVIEW_LEGEND_TOP,
    legendBlock: OVERVIEW_LEGEND_BLOCK,
    mainH,
    dailyH,
    tradeH,
    gridGap: OVERVIEW_GRID_GAP,
    gridTop0,
    gridTop1,
    gridTop2,
    totalChartPx,
    sliderHeight: OVERVIEW_SLIDER_H,
    sliderBottom: OVERVIEW_SLIDER_BOTTOM,
  };
}

function formatOverviewXAxisDateLabel(dateStr: string) {
  return dateStr.length >= 10 ? dateStr.slice(2) : dateStr;
}

function formatOverviewAmountAxis(value: number) {
  const a = Math.abs(value);
  if (a >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (a >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return formatNumber(value, 0);
}

/** 第三层买卖柱：围绕 0 对称，用 |买|/|卖| 的 98 分位作尺度，避免极值压扁 */
function computeBuySellAxisBounds(rows: OverviewRow[]): { min: number; max: number } {
  const absVals: number[] = [];
  for (const row of rows) {
    if (row.dailyBuy != null && row.dailyBuy !== 0) absVals.push(Math.abs(row.dailyBuy));
    if (row.dailySell != null && row.dailySell !== 0) absVals.push(Math.abs(row.dailySell));
  }
  if (absVals.length === 0) return { min: -1, max: 1 };
  absVals.sort((a, b) => a - b);
  const ix = Math.min(Math.max(0, Math.floor((absVals.length - 1) * 0.98)), absVals.length - 1);
  const p98 = absVals[ix] ?? absVals[absVals.length - 1];
  const maxAbs = Math.max(p98, 1e-12);
  const pad = 1.125;
  const bound = maxAbs * pad;
  return { min: -bound, max: bound };
}

function mainChartYValue(row: OverviewRow, kind: "strategy" | "excess" | "benchmark", yMode: "linear" | "log"): number | null {
  const r = kind === "strategy" ? row.strategyReturn : kind === "excess" ? row.excessReturn : row.benchmarkReturn;
  if (r == null || Number.isNaN(r)) return null;
  if (yMode === "log") {
    const w = 1 + r;
    return w > 0 ? w : null;
  }
  return r;
}

function buildOverviewOption(
  rows: OverviewRow[],
  benchmarkLabel: string,
  visibleRange: VisibleRange | null,
  layout: OverviewChartLayout,
  mainView: OverviewMainChartView,
): EChartsOption {
  const categories = rows.map((row) => row.date);
  const splitLineStyle = { lineStyle: { color: JQ_GRID, width: 1 } };
  const axisLabelStyle = { color: "#6b7280", fontSize: 11 };
  const dzProps =
    visibleRange?.start && visibleRange?.end && categories.length > 0
      ? visibleRangeToDataZoomProps(visibleRange, categories)
      : {};

  const tradeYBounds = computeBuySellAxisBounds(rows);

  const { mainH, dailyH, tradeH, gridTop0, gridTop1, gridTop2, sliderHeight, sliderBottom } = layout;

  const yMainType = mainView.yMode === "log" ? "log" : "value";
  const yMainAxisLabel =
    mainView.yMode === "log"
      ? { ...axisLabelStyle, formatter: (value: number) => formatPct(value - 1) }
      : { ...axisLabelStyle, formatter: (value: number) => formatPct(value) };

  return {
    animation: false,
    legend: { show: false },
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "cross",
        link: [{ xAxisIndex: [0, 1, 2] }],
        crossStyle: { color: "#999", width: 1, type: "dashed" },
      },
      backgroundColor: "#fff",
      borderColor: "#d0d0d0",
      borderWidth: 1,
      textStyle: { color: "#333", fontSize: 12 },
      formatter: (params: unknown) => {
        if (!Array.isArray(params) || params.length === 0) return "";
        const first = params[0] as { dataIndex?: number; axisValue?: string };
        const dateKey =
          typeof first.axisValue === "string" && first.axisValue.length >= 8
            ? first.axisValue.slice(0, 10)
            : undefined;
        const row =
          (dateKey ? rows.find((r) => r.date === dateKey) : undefined) ??
          rows[first.dataIndex ?? -1];
        if (!row) return "";
        const bench = benchmarkLabel;
        const ex = row.excessReturn != null ? formatPct(row.excessReturn) : "—";
        return [
          `<div style="font-weight:600;margin-bottom:4px">${formatOverviewXAxisDateLabel(row.date)}</div>`,
          `策略收益：${row.strategyReturn != null ? formatPct(row.strategyReturn) : "—"}`,
          `超额收益：${ex}`,
          `${bench}：${row.benchmarkReturn != null ? formatPct(row.benchmarkReturn) : "—"}`,
          `每日盈亏：${row.dailyStrategyReturn != null ? formatPct(row.dailyStrategyReturn) : "—"}`,
          `买入：${row.dailyBuy != null ? formatNumber(row.dailyBuy) : "—"}`,
          `卖出：${row.dailySell != null ? formatNumber(row.dailySell) : "—"}`,
        ].join("<br/>");
      },
    },
    grid: [
      { top: gridTop0, left: 48, right: 52, height: mainH, borderColor: "#ddd", containLabel: false },
      { top: gridTop1, left: 48, right: 52, height: dailyH, borderColor: "#ddd", containLabel: false },
      { top: gridTop2, left: 48, right: 52, height: tradeH, borderColor: "#ddd", containLabel: false },
    ],
    xAxis: [
      {
        type: "category",
        gridIndex: 0,
        data: categories,
        boundaryGap: false,
        axisLine: { lineStyle: { color: JQ_GRID } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
      {
        type: "category",
        gridIndex: 1,
        data: categories,
        boundaryGap: true,
        axisLine: { lineStyle: { color: JQ_GRID } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
      {
        type: "category",
        gridIndex: 2,
        data: categories,
        boundaryGap: true,
        axisLine: { lineStyle: { color: JQ_GRID } },
        axisTick: { show: false },
        axisLabel: {
          ...axisLabelStyle,
          formatter: (value: string) => formatOverviewXAxisDateLabel(value),
        },
      },
    ],
    yAxis: [
      {
        type: yMainType,
        gridIndex: 0,
        position: "right",
        scale: mainView.yMode === "linear",
        splitLine: splitLineStyle,
        axisLine: { show: false },
        axisLabel: yMainAxisLabel,
      },
      {
        type: "value",
        gridIndex: 1,
        position: "right",
        scale: true,
        splitLine: splitLineStyle,
        axisLine: { show: false },
        axisLabel: { ...axisLabelStyle, formatter: (value: number) => formatPct(value) },
        min: (v: { min: number; max: number }) => Math.min(v.min, 0),
        max: (v: { min: number; max: number }) => Math.max(v.max, 0),
      },
      {
        type: "value",
        gridIndex: 2,
        position: "right",
        scale: false,
        splitLine: splitLineStyle,
        axisLine: { show: false },
        axisLabel: { ...axisLabelStyle, formatter: (value: number) => formatOverviewAmountAxis(value) },
        min: tradeYBounds.min,
        max: tradeYBounds.max,
      },
    ],
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: [0, 1, 2],
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseWheel: false,
        moveOnMouseMove: true,
        // 最小可视窗口：避免滚轮一缩压成 1 个 category → 三联图全变一根竖线
        // minValueSpan = 5 个 category（约 5 个交易日）；minSpan = 2% 兜底
        minValueSpan: Math.min(5, Math.max(1, categories.length - 1)),
        minSpan: 2,
        ...dzProps,
      },
      {
        type: "slider",
        xAxisIndex: [0, 1, 2],
        filterMode: "none",
        bottom: sliderBottom,
        height: sliderHeight,
        borderColor: "#d5dbe3",
        backgroundColor: "#f5f5f5",
        fillerColor: "rgba(76, 120, 168, 0.22)",
        handleStyle: { color: "#fff", borderColor: "#9aa5b1" },
        // slider 两个 handle 拖到一起也会触发同一 bug；同样的最小窗口
        minValueSpan: Math.min(5, Math.max(1, categories.length - 1)),
        minSpan: 2,
        ...dzProps,
      },
    ],
    series: [
      {
        name: "策略收益",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        smooth: false,
        lineStyle: {
          color: JQ_STRATEGY_LINE,
          width: mainView.showStrategy ? 2 : 0,
          opacity: mainView.showStrategy ? 1 : 0,
        },
        areaStyle: mainView.showStrategy ? { color: JQ_STRATEGY_AREA } : { opacity: 0 },
        markLine: mainView.showStrategy
          ? {
              silent: true,
              symbol: "none",
              label: { show: false },
              lineStyle: { color: "#000000", width: 1.5, type: "solid" },
              data: [{ yAxis: mainView.yMode === "log" ? 1 : 0 }],
            }
          : undefined,
        data: rows.map((row) => mainChartYValue(row, "strategy", mainView.yMode)),
      },
      {
        name: "超额收益",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        smooth: false,
        lineStyle: {
          color: JQ_EXCESS_LINE,
          width: mainView.showExcess ? 2 : 0,
          opacity: mainView.showExcess ? 1 : 0,
        },
        data: rows.map((row) => mainChartYValue(row, "excess", mainView.yMode)),
      },
      {
        name: benchmarkLabel,
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        smooth: false,
        lineStyle: {
          color: JQ_BENCHMARK_LINE,
          width: mainView.showBenchmark ? 2 : 0,
          opacity: mainView.showBenchmark ? 1 : 0,
        },
        data: rows.map((row) => mainChartYValue(row, "benchmark", mainView.yMode)),
      },
      {
        name: "每日盈亏",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        large: false,
        clip: false,
        barMinWidth: 2,
        barMaxWidth: 14,
        barWidth: "55%",
        barCategoryGap: "35%",
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: "#333333", width: 1, type: "solid" },
          data: [{ yAxis: 0 }],
        },
        data: rows.map((row) => {
          const v = row.dailyStrategyReturn;
          if (v === undefined || v === null) return null;
          return {
            value: v,
            itemStyle: { color: v >= 0 ? JQ_DAILY_POS : JQ_DAILY_NEG },
          };
        }),
      },
      {
        name: "买入",
        type: "bar",
        xAxisIndex: 2,
        yAxisIndex: 2,
        large: false,
        clip: false,
        z: 2,
        barMinWidth: 2,
        barMaxWidth: 10,
        barWidth: "38%",
        barGap: "12%",
        barCategoryGap: "28%",
        data: rows.map((row) => ({
          value: row.dailyBuy ?? null,
          itemStyle: { color: JQ_BUY_BAR },
        })),
      },
      {
        name: "卖出",
        type: "bar",
        xAxisIndex: 2,
        yAxisIndex: 2,
        large: false,
        clip: false,
        z: 2,
        barMinWidth: 2,
        barMaxWidth: 10,
        barWidth: "38%",
        barGap: "12%",
        barCategoryGap: "28%",
        data: rows.map((row) => ({
          value: row.dailySell != null && row.dailySell !== 0 ? -Math.abs(row.dailySell) : row.dailySell ?? null,
          itemStyle: { color: JQ_SELL_BAR },
        })),
      },
    ],
  };
}

function buildMetricOption(points: RunSeriesPoint[], title: string, color: string, format: MetricFormat): EChartsOption {
  return {
    animation: false,
    title: { text: title, left: 12, top: 10 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => {
        if (typeof value !== "number") return String(value ?? "");
        return format === "pct" ? formatPct(value) : formatNumber(value);
      },
    },
    xAxis: {
      type: "category",
      data: points.map((point) => toDateLabel(point.timestamp)),
      boundaryGap: false,
    },
    yAxis: {
      type: "value",
      axisLabel: {
        formatter: (value: number) => (format === "pct" ? formatPct(value) : formatNumber(value)),
      },
    },
    series: [
      {
        type: "line",
        smooth: true,
        data: points.map((point) => point.value ?? null),
        lineStyle: { color },
        itemStyle: { color },
        areaStyle: { opacity: 0.08, color },
      },
    ],
  };
}

function attributionRowsPayload(response: RunAttributionResponse | undefined) {
  if (!response || !response.available) return [];
  return response.rows;
}

function metricRaw(run: RunDetail, key: string): unknown {
  return (run.metrics ?? {})[key];
}

function OverviewMetricsJq({ metrics }: { metrics?: JqOverviewMetrics | null }) {
  const { row1, row2 } = buildJqSummaryRows(metrics);
  return (
    <div className="jq-run-overview-metrics-jq">
      <div className="jq-run-overview-metrics-row">
        {row1.map((item) => (
          <div key={item.key} className="jq-run-overview-metric-block">
            <span>
              {item.label}
              <GlossaryInfoButton slug={getGlossarySlugForMetric(item.key)} ariaLabel={`查看 ${item.label} 术语解释`} />
            </span>
            <strong className={item.tone !== "normal" ? item.tone : ""}>{item.display}</strong>
          </div>
        ))}
      </div>
      <div className="jq-run-overview-metrics-row jq-run-overview-metrics-row--r2">
        {row2.map((item) => (
          <div
            key={item.key}
            className={
              item.key === "max_drawdown_period"
                ? "jq-run-overview-metric-block jq-run-overview-metric-block--col2"
                : "jq-run-overview-metric-block"
            }
          >
            <span>
              {item.label}
              <GlossaryInfoButton slug={getGlossarySlugForMetric(item.key)} ariaLabel={`查看 ${item.label} 术语解释`} />
            </span>
            <strong className={item.tone !== "normal" ? item.tone : ""}>{item.display}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function presetRange(
  kind: "1m" | "1y" | "all",
  dates: string[],
  currentEnd: string,
): { start: string; end: string } {
  if (!dates.length) return { start: "", end: "" };
  const first = dates[0];
  const last = dates[dates.length - 1];
  const end = (currentEnd && dates.includes(currentEnd) ? currentEnd : last) || last;
  if (kind === "all") return { start: first, end: last };
  const endD = new Date(`${end}T12:00:00`);
  if (kind === "1m") {
    endD.setMonth(endD.getMonth() - 1);
  } else {
    endD.setFullYear(endD.getFullYear() - 1);
  }
  let start = endD.toISOString().slice(0, 10);
  if (start < first) start = first;
  if (start > end) start = first;
  return clampVisibleRange(start, end, dates);
}

function RunOverviewTab({
  run,
  overviewRows,
  benchmarkLabel,
}: {
  run: RunDetail;
  overviewRows: OverviewRow[];
  benchmarkLabel: string;
}) {
  const dateList = useMemo(() => overviewRows.map((r) => r.date), [overviewRows]);
  const dateListRef = useRef(dateList);
  dateListRef.current = dateList;
  const [visibleRange, setVisibleRange] = useState<VisibleRange>({ start: "", end: "" });
  const [mainView, setMainView] = useState<OverviewMainChartView>({
    yMode: "linear",
    showStrategy: true,
    showExcess: true,
    showBenchmark: true,
  });
  const chartRef = useRef<InstanceType<typeof ReactECharts> | null>(null);
  const chartWrapRef = useRef<HTMLDivElement | null>(null);
  const syncingFromDispatch = useRef(false);

  useEffect(() => {
    const onResize = () => {
      requestAnimationFrame(() => chartRef.current?.getEchartsInstance()?.resize());
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const chartLayout = useMemo(() => getFixedOverviewChartLayout(), []);

  useEffect(() => {
    if (!dateList.length) {
      setVisibleRange({ start: "", end: "" });
      return;
    }
    setVisibleRange((prev) => {
      if (!prev.start || !prev.end) {
        return { start: dateList[0], end: dateList[dateList.length - 1] };
      }
      return clampVisibleRange(prev.start, prev.end, dateList);
    });
  }, [dateList]);

  const option = useMemo(
    () =>
      buildOverviewOption(
        overviewRows,
        benchmarkLabel,
        visibleRange.start ? visibleRange : null,
        chartLayout,
        mainView,
      ),
    [benchmarkLabel, chartLayout, mainView, overviewRows, visibleRange],
  );

  const chartHeightPx = chartLayout.totalChartPx;

  /** 容器尺寸变化时 ECharts resize（图总高由 getFixedOverviewChartLayout 固定常量决定） */
  useEffect(() => {
    const wrap = chartWrapRef.current;
    if (!wrap || !overviewRows.length) return;
    const resize = () => {
      chartRef.current?.getEchartsInstance()?.resize();
    };
    const ro = new ResizeObserver(() => {
      requestAnimationFrame(resize);
    });
    ro.observe(wrap);
    requestAnimationFrame(resize);
    return () => {
      ro.disconnect();
    };
  }, [overviewRows.length, chartHeightPx, option, chartLayout.totalChartPx]);

  const flushRangeFromChart = useCallback(() => {
    if (syncingFromDispatch.current) return;
    requestAnimationFrame(() => {
      if (syncingFromDispatch.current) return;
      const chart = chartRef.current?.getEchartsInstance() as ECharts | undefined;
      const cats = dateListRef.current;
      if (!chart || !cats.length) return;
      let next = readVisibleRangeFromChartInstance(chart, cats);
      if (!next) return;
      next = clampVisibleRange(next.start, next.end, cats);
      setVisibleRange((prev) => {
        if (next.start === prev.start && next.end === prev.end) return prev;
        return next;
      });
    });
  }, []);

  const dispatchDataZoom = useCallback((start: string, end: string) => {
    const inst = chartRef.current?.getEchartsInstance() as ECharts | undefined;
    const cats = dateListRef.current;
    if (!inst || !start || !end || !cats.length) return;
    syncingFromDispatch.current = true;
    const props = visibleRangeToDataZoomProps({ start, end }, cats);
    inst.dispatchAction({
      type: "dataZoom",
      xAxisIndex: [0, 1, 2],
      ...props,
    });
    window.setTimeout(() => {
      syncingFromDispatch.current = false;
      flushRangeFromChart();
    }, 80);
  }, [flushRangeFromChart]);

  const onDataZoomEvent = useCallback(
    (_params: unknown) => {
      if (syncingFromDispatch.current) return;
      const chart = chartRef.current?.getEchartsInstance() as ECharts | undefined;
      const cats = dateListRef.current;
      if (!chart || !cats.length) return;
      const fromChart = readVisibleRangeFromChartInstance(chart, cats);
      const fromParams = extractDataZoomRange(_params, cats);
      const next = fromChart ?? fromParams;
      if (!next) return;
      const clamped = clampVisibleRange(next.start, next.end, cats);
      setVisibleRange((prev) => {
        if (clamped.start === prev.start && clamped.end === prev.end) return prev;
        return clamped;
      });
    },
    [],
  );

  const applyRange = useCallback(
    (start: string, end: string) => {
      if (!dateList.length) return;
      const next = clampVisibleRange(start, end, dateList);
      setVisibleRange(next);
      dispatchDataZoom(next.start, next.end);
    },
    [dateList, dispatchDataZoom],
  );

  const onStartDateChange = (e: ChangeEvent<HTMLInputElement>) => {
    applyRange(e.target.value, visibleRange.end);
  };

  const onEndDateChange = (e: ChangeEvent<HTMLInputElement>) => {
    applyRange(visibleRange.start, e.target.value);
  };

  return (
    <section className="jq-run-panel-section jq-run-overview-module jq-run-overview-jq-page">
      <header className="jq-run-overview-page-head" aria-label="收益概述">
        <h2 className="jq-run-overview-page-title">收益概述</h2>
      </header>

      <div className="jq-run-overview-summary-board jq-run-overview-summary-board--metrics-only">
        <div className="jq-run-overview-metrics-board">
          <OverviewMetricsJq metrics={run.jq_overview_metrics} />
        </div>
      </div>

      <div className="jq-run-overview-chart-toolbar jq-run-overview-chart-toolbar--jq">
        <div className="jq-run-overview-presets jq-run-overview-presets--jq" role="group" aria-label="缩放">
          <span className="jq-run-zoom-prefix">缩放：</span>
          {[
            { key: "1m" as const, label: "1个月" },
            { key: "1y" as const, label: "1年" },
            { key: "all" as const, label: "全部" },
          ].map((p) => (
            <button
              key={p.key}
              type="button"
              className="jq-run-tb-link"
              disabled={!dateList.length}
              onClick={() => {
                const r = presetRange(p.key, dateList, visibleRange.end);
                applyRange(r.start, r.end);
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="jq-run-overview-toolbar-center jq-run-overview-toolbar-center--jq" aria-label="图例与坐标轴">
          <button type="button" className="jq-run-tb-legend" onClick={() => setMainView((m) => ({ ...m, showStrategy: !m.showStrategy }))}>
            <i className="jq-run-tb-swatch" style={{ background: JQ_STRATEGY_LINE }} />
            策略收益
          </button>
          <button type="button" className="jq-run-tb-legend" onClick={() => setMainView((m) => ({ ...m, showExcess: !m.showExcess }))}>
            <i className="jq-run-tb-swatch" style={{ background: JQ_EXCESS_LINE }} />
            超额收益
          </button>
          <button type="button" className="jq-run-tb-legend" onClick={() => setMainView((m) => ({ ...m, showBenchmark: !m.showBenchmark }))}>
            <i className="jq-run-tb-swatch" style={{ background: JQ_BENCHMARK_LINE }} />
            {benchmarkLabel}
          </button>
          <label className="jq-run-tb-radio">
            <input
              type="radio"
              name={`jq-yaxis-${run.run_id}`}
              checked={mainView.yMode === "linear"}
              onChange={() => setMainView((m) => ({ ...m, yMode: "linear" }))}
            />
            普通轴
          </label>
          <label className="jq-run-tb-radio">
            <input
              type="radio"
              name={`jq-yaxis-${run.run_id}`}
              checked={mainView.yMode === "log"}
              onChange={() => setMainView((m) => ({ ...m, yMode: "log" }))}
            />
            对数轴
          </label>
          <label className="jq-run-tb-check">
            <input
              type="checkbox"
              checked={mainView.showExcess}
              onChange={(e) => setMainView((m) => ({ ...m, showExcess: e.target.checked }))}
            />
            超额收益
          </label>
        </div>
        <div className="jq-run-overview-date-toolbar jq-run-overview-date-toolbar--jq" aria-label="图表可视时间区间">
          <span className="jq-run-overview-time-label">时间：</span>
          <input
            type="date"
            className="jq-run-overview-date-input"
            value={visibleRange.start}
            min={dateList[0] ?? undefined}
            max={dateList[dateList.length - 1] ?? undefined}
            onChange={onStartDateChange}
          />
          <span className="jq-run-overview-date-sep" aria-hidden>
            -
          </span>
          <input
            type="date"
            className="jq-run-overview-date-input"
            value={visibleRange.end}
            min={dateList[0] ?? undefined}
            max={dateList[dateList.length - 1] ?? undefined}
            onChange={onEndDateChange}
          />
        </div>
      </div>

      <div className="jq-run-overview-chart-panel jq-run-overview-chart-panel--jq">
        {overviewRows.length ? (
          <div
            ref={chartWrapRef}
            className="jq-run-overview-chart-resize-wrap"
            style={{ width: "100%", minHeight: chartHeightPx }}
          >
            <ReactECharts
              ref={chartRef}
              option={option}
              style={{ width: "100%", height: chartHeightPx }}
              notMerge
              lazyUpdate
              onEvents={{
                dataZoom: onDataZoomEvent,
                datazoom: onDataZoomEvent,
              }}
            />
          </div>
        ) : (
          <div className="jq-run-fallback-chart" style={{ minHeight: 200 }}>
            暂无序列数据，无法绘制概览图
          </div>
        )}
      </div>
    </section>
  );
}

function MetricPage({ title, color, format, points }: { title: string; color: string; format: MetricFormat; points: RunSeriesPoint[] }) {
  return (
    <section className="jq-run-panel-section">
      <div className="jq-run-section-head">
        <strong>{title}</strong>
      </div>
      <div className="jq-run-metric-chart">
        <ReactECharts option={buildMetricOption(points, title, color, format)} style={{ height: 308 }} notMerge lazyUpdate />
      </div>
      <div className="jq-table-shell">
        <table className="jq-legacy-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>{title}</th>
            </tr>
          </thead>
          <tbody>
            {points.length ? (
              points.map((point, index) => (
                <tr key={`${point.timestamp ?? "row"}-${index}`}>
                  <td>{toDateLabel(point.timestamp)}</td>
                  <td className={metricClass(point.value)}>{formatMetricValue(point.value, format)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={2}>暂无数据</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PerformancePanel({ run }: { run: RunDetail }) {
  const artifactRows = Object.values(run.artifact_stats ?? {});
  return (
    <section className="jq-run-panel-section">
      <div className="jq-run-section-head">
        <strong>性能分析</strong>
      </div>
      <div className="jq-run-performance-grid">
        <div className="jq-run-performance-card">
          <h4>产物概况</h4>
          <table className="jq-legacy-table">
            <thead>
              <tr>
                <th>artifact</th>
                <th>状态</th>
                <th>大小</th>
                <th>行数</th>
              </tr>
            </thead>
            <tbody>
              {artifactRows.length ? (
                artifactRows.map((item) => (
                  <tr key={item.artifact_name}>
                    <td>{item.artifact_name}</td>
                    <td>{item.available ? "已提供" : "缺失"}</td>
                    <td>{item.file_size_bytes ? formatFileSize(item.file_size_bytes) : "—"}</td>
                    <td>{item.row_count != null ? formatNumber(item.row_count, 0) : "—"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4}>暂无 artifact</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="jq-run-performance-card">
          <h4>命名输出</h4>
          <table className="jq-legacy-table">
            <thead>
              <tr>
                <th>output_name</th>
                <th>dataset_name</th>
                <th>version_id</th>
                <th>row_count</th>
              </tr>
            </thead>
            <tbody>
              {run.produced_outputs.length ? (
                run.produced_outputs.map((item) => (
                  <tr key={`${item.output_name}-${item.version_id ?? ""}`}>
                    <td>{item.output_name}</td>
                    <td>{item.dataset_name ?? "—"}</td>
                    <td>{item.version_id ?? "—"}</td>
                    <td>{item.row_count ?? "—"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4}>暂无命名输出</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

export function RunDetailPage() {
  const { runId: routeRunId = "" } = useParams();
  const runId = routeRunId;
  const [detailContentTab, setDetailContentTab] = useState<DetailContentTab>("overview");
  const [logTab, setLogTab] = useState<"logs" | "errors">("logs");

  const runQuery = useQuery({
    queryKey: ["run-detail", runId],
    queryFn: () => getRun(runId),
    enabled: Boolean(runId),
  });

  const strategySeriesQuery = useRunSeriesQuery(runId, "equity");
  const benchmarkSeriesQuery = useRunSeriesQuery(runId, "benchmark_return");
  const dailyBuySeriesQuery = useRunSeriesQuery(runId, "daily_buy");
  const dailySellSeriesQuery = useRunSeriesQuery(runId, "daily_sell");

  const isMetricTab = detailContentTab.startsWith("metric_");
  const metricConfig = isMetricTab ? METRIC_PAGE_CONFIG[detailContentTab as keyof typeof METRIC_PAGE_CONFIG] : null;
  const metricSeriesQuery = useRunSeriesQuery(runId, metricConfig?.series ?? "strategy_return", Boolean(metricConfig));

  const logsQuery = useQuery({
    queryKey: ["run-logs", runId],
    queryFn: () => getRunLogs(runId, { limit: 800, offset: 0 }),
    enabled: Boolean(runId) && detailContentTab === "log_output",
  });

  const sourceQuery = useQuery({
    queryKey: ["run-source", runId],
    queryFn: () => getRunSource(runId),
    enabled: Boolean(runId) && detailContentTab === "strategy_code",
  });

  const attributionQuery = useQuery({
    queryKey: ["run-attribution", runId],
    queryFn: () => getRunAttribution(runId),
    enabled: Boolean(runId) && detailContentTab === "attribution",
  });

  const run = runQuery.data;
  const overviewRows = useMemo(
    () =>
      buildOverviewRows(
        strategySeriesQuery.data?.points ?? [],
        benchmarkSeriesQuery.data?.points ?? [],
        dailyBuySeriesQuery.data?.points ?? [],
        dailySellSeriesQuery.data?.points ?? [],
      ),
    [
      benchmarkSeriesQuery.data?.points,
      dailyBuySeriesQuery.data?.points,
      dailySellSeriesQuery.data?.points,
      strategySeriesQuery.data?.points,
    ],
  );
  const benchmarkLabel = run?.benchmark?.trim() || "基准收益";
  const filteredLogs = (logsQuery.data?.entries ?? []).filter((entry) =>
    logTab === "errors" ? /error|failed|traceback/i.test(`${entry.level} ${entry.message}`) : true,
  );

  if (!runId) {
    return <section className="jq-run-detail-shell">缺少 runId</section>;
  }
  if (runQuery.isLoading) {
    return <section className="jq-run-detail-shell">加载回测详情中…</section>;
  }
  if (runQuery.isError || !run) {
    return <section className="jq-run-detail-shell">回测详情加载失败。</section>;
  }

  const renderMainContent = () => {
    if (detailContentTab === "overview") {
      return <RunOverviewTab run={run} overviewRows={overviewRows} benchmarkLabel={benchmarkLabel} />;
    }

    if (detailContentTab === "trade_detail") {
      return (
        <section className="jq-run-panel-section">
          <div className="jq-run-section-head">
            <strong>交易详情</strong>
          </div>
          <JqTradesPanel runId={runId} available={Boolean(run.series_available.trades ?? run.artifact_stats.trades?.available)} />
        </section>
      );
    }

    if (detailContentTab === "daily_position") {
      return (
        <section className="jq-run-panel-section">
          <div className="jq-run-section-head">
            <strong>每日持仓&收益</strong>
          </div>
          <JqDailyHoldingsPanel runId={runId} available={Boolean(run.series_available.positions ?? run.artifact_stats.positions?.available)} />
        </section>
      );
    }

    if (detailContentTab === "log_output") {
      return (
        <section className="jq-run-panel-section">
          <div className="jq-run-section-head">
            <strong>日志输出</strong>
          </div>
          <div className="jq-run-log-tabs">
            {[
              { key: "logs" as const, label: "日志" },
              { key: "errors" as const, label: "错误" },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                className={logTab === item.key ? "jq-run-log-tab active" : "jq-run-log-tab"}
                onClick={() => setLogTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="jq-run-log-console">
            {filteredLogs.length ? (
              filteredLogs.map((entry, index) => (
                <div key={`${entry.timestamp}-${index}`} className="jq-run-log-line">
                  <span>{entry.timestamp || "--"}</span>
                  <span>{entry.level || "--"}</span>
                  <span>{entry.message}</span>
                </div>
              ))
            ) : (
              <div className="jq-run-log-line">暂无日志输出</div>
            )}
          </div>
        </section>
      );
    }

    if (detailContentTab === "performance") {
      return <PerformancePanel run={run} />;
    }

    if (detailContentTab === "strategy_code") {
      return (
        <section className="jq-run-panel-section">
          <div className="jq-run-section-head">
            <strong>策略代码</strong>
          </div>
          <div className="jq-run-code-head">
            <span>{sourceQuery.data?.file_name ?? `${run.strategy_id}.py`}</span>
          </div>
          <pre className="jq-run-code-block">{sourceQuery.data?.content ?? "# 未提供 strategy.py"}</pre>
        </section>
      );
    }

    if (detailContentTab === "report") {
      return (
        <section className="jq-run-panel-section">
          <div className="jq-run-section-head">
            <strong>Markdown 报告</strong>
          </div>
          <div className="jq-run-code-head">
            <span>report.md</span>
          </div>
          <pre className="jq-run-code-block">{run.report_markdown || "未提供 report.md"}</pre>
        </section>
      );
    }

    if (detailContentTab === "attribution") {
      const rows = attributionRowsPayload(attributionQuery.data);
      const summaryEntries = Object.entries(attributionQuery.data?.summary ?? {}).slice(0, 5);
      return (
        <section className="jq-run-panel-section">
          <div className="jq-run-section-head">
            <strong>归因</strong>
          </div>
          <div className="jq-run-attribution-panel">
            {summaryEntries.length ? (
              <div className="jq-run-attribution-summary">
                {summaryEntries.map(([key, value]) => (
                  <div key={key} className="jq-run-attribution-summary-item">
                    <span>{key}</span>
                    <strong>{String(value ?? "—")}</strong>
                  </div>
                ))}
              </div>
            ) : null}
            {rows.length ? (
              <div className="jq-table-shell">
                <table className="jq-legacy-table">
                  <thead>
                    <tr>
                      {Object.keys((rows[0] ?? {}) as Record<string, unknown>).map((key) => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={index}>
                        {Object.keys(row).map((key) => (
                          <td key={key}>{String((row as Record<string, unknown>)[key] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="jq-run-attribution-empty">{attributionQuery.data?.message ?? "未提供 attribution.csv"}</div>
            )}
          </div>
        </section>
      );
    }

    if (metricConfig) {
      return <MetricPage title={metricConfig.title} color={metricConfig.color} format={metricConfig.format} points={metricSeriesQuery.data?.points ?? []} />;
    }

    return null;
  };

  return (
    <div className="jq-run-detail-shell">
      <div className="jq-run-detail-statusbar">
        <div className="jq-run-detail-status-left">
          <strong>{run.record_name?.trim() || run.strategy_name}</strong>
          <span className={`jq-status-text ${run.status}`}>{run.status}</span>
          <span>基准: {benchmarkLabel}</span>
          <span>频率: {run.frequency || "—"}</span>
          <span>开始: {formatDateTime(run.started_at)}</span>
        </div>
        <div className="jq-run-detail-status-right">
          <a href={buildRunExportUrl(run.run_id, "nav")}>净值</a>
          <a href={buildRunExportUrl(run.run_id, "trades")}>交易</a>
          <a href={buildRunExportUrl(run.run_id, "metrics")}>指标</a>
          <a href={buildArtifactDownloadUrl(run.run_id, "report")}>报告</a>
        </div>
      </div>
      <div className="jq-run-detail-main">
        <aside className="jq-run-detail-sidebar">
          <div role="tablist" aria-label="Run detail navigation">
            {SIDEBAR_GROUPS.map((group) => (
              <div key={group.title} className="jq-run-detail-navgroup">
                <div className="jq-run-detail-navtitle">{group.title}</div>
                {group.items.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    role="tab"
                    aria-selected={detailContentTab === item.key}
                    className={detailContentTab === item.key ? "jq-run-detail-navitem active" : "jq-run-detail-navitem"}
                    onClick={() => setDetailContentTab(item.key)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </aside>
        <main className="jq-run-detail-content">{renderMainContent()}</main>
      </div>
    </div>
  );
}
