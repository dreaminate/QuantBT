import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
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
  RunAttributionResponse,
  RunDetail,
  RunSeriesPoint,
  SeriesName,
} from "../types";
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
  /** 策略每日收益率（小数），用于第二层每日盈亏柱 */
  dailyStrategyReturn?: number;
  dailyBuy?: number;
  dailySell?: number;
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
  return formatNumber(number);
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
    let dailyStrategyReturn: number | undefined;
    if (strategyNav !== undefined) {
      dailyStrategyReturn =
        previousStrategyNav && previousStrategyNav !== 0 ? strategyNav / previousStrategyNav - 1 : 0;
    }
    rows.push({
      date,
      strategyReturn,
      benchmarkReturn,
      dailyStrategyReturn,
      dailyBuy: buyMap.get(date),
      dailySell: sellMap.get(date),
    });
    if (strategyNav !== undefined) previousStrategyNav = strategyNav;
  }
  return rows;
}


function filterOverviewRows(rows: OverviewRow[], startDate: string, endDate: string) {
  return rows.filter((row) => {
    if (startDate && row.date < startDate) return false;
    if (endDate && row.date > endDate) return false;
    return true;
  });
}


/** JoinQuant 回测概览图配色 */
const JQ_GRID = "#EAEAEA";
const JQ_STRATEGY_LINE = "#4C78A8";
const JQ_BENCHMARK_LINE = "#E45756";
const JQ_STRATEGY_AREA = "rgba(76, 120, 168, 0.15)";
const JQ_DAILY_POS = "#54A24B";
const JQ_DAILY_NEG = "#B279A2";
const JQ_BUY_BAR = "#4C78A8";
const JQ_SELL_BAR = "#F58518";

function formatOverviewXAxisDateLabel(dateStr: string) {
  return dateStr.length >= 10 ? dateStr.slice(2) : dateStr;
}

function formatOverviewAmountAxis(value: number) {
  const a = Math.abs(value);
  if (a >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (a >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return formatNumber(value, 0);
}

function buildOverviewOption(rows: OverviewRow[], benchmarkLabel: string): EChartsOption {
  const categories = rows.map((row) => row.date);
  const splitLineStyle = { lineStyle: { color: JQ_GRID, width: 1 } };
  const axisLabelStyle = { color: "#6b7280", fontSize: 11 };

  return {
    animation: false,
    legend: {
      top: 8,
      left: 12,
      itemWidth: 12,
      itemHeight: 8,
      selectedMode: true,
      textStyle: { color: "#4a5560", fontSize: 12 },
      data: ["策略收益", benchmarkLabel, "每日盈亏", "买入", "卖出"],
    },
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
        const first = params[0] as { dataIndex?: number };
        const index = first.dataIndex;
        if (index === undefined || index < 0) return "";
        const row = rows[index];
        if (!row) return "";
        const bench = benchmarkLabel;
        return [
          `<div style="font-weight:600;margin-bottom:4px">${formatOverviewXAxisDateLabel(row.date)}</div>`,
          `策略收益：${row.strategyReturn != null ? formatPct(row.strategyReturn) : "—"}`,
          `${bench}：${row.benchmarkReturn != null ? formatPct(row.benchmarkReturn) : "—"}`,
          `每日盈亏：${row.dailyStrategyReturn != null ? formatPct(row.dailyStrategyReturn) : "—"}`,
          `买入：${row.dailyBuy != null ? formatNumber(row.dailyBuy) : "—"}`,
          `卖出：${row.dailySell != null ? formatNumber(row.dailySell) : "—"}`,
        ].join("<br/>");
      },
    },
    grid: [
      { top: 34, left: 48, right: 54, height: 230 },
      { top: 264, left: 48, right: 54, height: 115 },
      { top: 379, left: 48, right: 54, height: 115 },
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
        type: "value",
        gridIndex: 0,
        position: "right",
        splitLine: splitLineStyle,
        axisLine: { show: false },
        axisLabel: { ...axisLabelStyle, formatter: (value: number) => formatPct(value) },
      },
      {
        type: "value",
        gridIndex: 1,
        position: "right",
        splitLine: splitLineStyle,
        axisLine: { show: false },
        axisLabel: { ...axisLabelStyle, formatter: (value: number) => formatPct(value) },
      },
      {
        type: "value",
        gridIndex: 2,
        position: "right",
        splitLine: splitLineStyle,
        axisLine: { show: false },
        axisLabel: { ...axisLabelStyle, formatter: (value: number) => formatOverviewAmountAxis(value) },
      },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1, 2], filterMode: "filter" },
      {
        type: "slider",
        xAxisIndex: [0, 1, 2],
        bottom: 12,
        height: 20,
        borderColor: "#d5dbe3",
        backgroundColor: "#f5f5f5",
        fillerColor: "rgba(76, 120, 168, 0.22)",
        handleStyle: { color: "#fff", borderColor: "#9aa5b1" },
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
        lineStyle: { color: JQ_STRATEGY_LINE, width: 2 },
        areaStyle: { color: JQ_STRATEGY_AREA },
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: "#000000", width: 1.5, type: "solid" },
          data: [{ yAxis: 0 }],
        },
        data: rows.map((row) => row.strategyReturn ?? null),
      },
      {
        name: benchmarkLabel,
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        smooth: false,
        lineStyle: { color: JQ_BENCHMARK_LINE, width: 2 },
        data: rows.map((row) => row.benchmarkReturn ?? null),
      },
      {
        name: "每日盈亏",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        barWidth: "60%",
        barCategoryGap: "40%",
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
        barWidth: "30%",
        barGap: "10%",
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
        barWidth: "30%",
        barGap: "10%",
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


export function RunDetailPage() {
  const { runId: routeRunId = "" } = useParams();
  const runId = routeRunId;
  const [detailContentTab, setDetailContentTab] = useState<DetailContentTab>("overview");
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");

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
  const metricItems = useMemo(
    () => [
      { key: "total_return", label: "总收益", value: run?.returns ?? run?.metrics?.total_return, format: "pct" as MetricFormat },
      { key: "annualized_return", label: "年化收益", value: run?.annualized_return, format: "pct" as MetricFormat },
      { key: "max_drawdown", label: "最大回撤", value: run?.drawdown ?? run?.metrics?.max_drawdown, format: "pct" as MetricFormat },
      { key: "sharpe", label: "夏普比率", value: run?.sharpe, format: "num" as MetricFormat },
      { key: "sortino", label: "索提诺比率", value: run?.sortino, format: "num" as MetricFormat },
      { key: "alpha", label: "Alpha", value: run?.alpha, format: "pct" as MetricFormat },
      { key: "beta", label: "Beta", value: run?.beta, format: "num" as MetricFormat },
      { key: "trade_count", label: "交易次数", value: run?.trade_count, format: "num" as MetricFormat },
    ],
    [run],
  );

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

  const filteredRows = useMemo(() => filterOverviewRows(overviewRows, rangeStart, rangeEnd), [overviewRows, rangeEnd, rangeStart]);
  const benchmarkLabel = run?.benchmark || "基准收益";
  const overviewOption = useMemo(() => buildOverviewOption(filteredRows, benchmarkLabel), [benchmarkLabel, filteredRows]);
  const metricOption = useMemo(
    () => (metricConfig ? buildMetricOption(metricSeriesQuery.data?.points ?? [], metricConfig.title, metricConfig.color, metricConfig.format) : null),
    [metricConfig, metricSeriesQuery.data?.points],
  );

  if (!runId) {
    return <section className="panel panel-full">缺少 runId</section>;
  }
  if (runQuery.isLoading) {
    return <section className="panel panel-full">加载中...</section>;
  }
  if (runQuery.isError || !run) {
    return <section className="panel panel-full">读取回测详情失败。</section>;
  }

  return (
    <div className="jq-run-layout">
      <aside className="jq-run-sidebar">
        <div className="jq-run-sidebar-header">
          <p className="eyebrow">Run detail</p>
          <h2>{run.strategy_name}</h2>
          <p className="muted">
            {run.record_name || run.run_id} · {formatDateTime(run.started_at)}
          </p>
        </div>
        {SIDEBAR_GROUPS.map((group) => (
          <section key={group.title} className="jq-run-sidebar-group">
            <h3>{group.title}</h3>
            <div className="jq-run-sidebar-links">
              {group.items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`jq-run-sidebar-link ${detailContentTab === item.key ? "active" : ""}`}
                  onClick={() => setDetailContentTab(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </section>
        ))}
      </aside>

      <div className="jq-run-main">
        <section className="panel jq-run-summary-card">
          <div className="jq-run-summary-head">
            <div>
              <p className="eyebrow">Summary</p>
              <h3>{run.strategy_name}</h3>
            </div>
            <div className="actions">
              <a className="ghost-button" href={buildRunExportUrl(runId, "nav")}>
                导出净值
              </a>
              <a className="ghost-button" href={buildRunExportUrl(runId, "trades")}>
                导出交易
              </a>
              <a className="ghost-button" href={buildArtifactDownloadUrl(runId, "report")}>
                下载报告
              </a>
            </div>
          </div>
          <dl className="meta-grid compact">
            <div>
              <dt>Run ID</dt>
              <dd>{run.run_id}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{run.status}</dd>
            </div>
            <div>
              <dt>市场</dt>
              <dd>{run.market || "—"}</dd>
            </div>
            <div>
              <dt>周期</dt>
              <dd>{run.frequency || "—"}</dd>
            </div>
            <div>
              <dt>基准</dt>
              <dd>{run.benchmark || "—"}</dd>
            </div>
            <div>
              <dt>开始时间</dt>
              <dd>{formatDateTime(run.started_at)}</dd>
            </div>
          </dl>
        </section>

        {detailContentTab === "overview" ? (
          <>
            <section className="jq-metric-grid">
              {metricItems.map((item) => (
                <div key={item.key} className="metric-card">
                  <span>{item.label}</span>
                  <strong className={metricClass(item.value)}>{formatMetricValue(item.value, item.format)}</strong>
                </div>
              ))}
            </section>

            <section className="panel jq-run-overview-panel">
              <div className="panel-header split">
                <div>
                  <p className="eyebrow">Overview chart</p>
                  <h3>收益概述</h3>
                </div>
                <div className="button-row">
                  <label>
                    <span>开始</span>
                    <input type="date" value={rangeStart} onChange={(event) => setRangeStart(event.target.value)} />
                  </label>
                  <label>
                    <span>结束</span>
                    <input type="date" value={rangeEnd} onChange={(event) => setRangeEnd(event.target.value)} />
                  </label>
                </div>
              </div>
              <ReactECharts option={overviewOption} style={{ height: 560 }} notMerge lazyUpdate />
            </section>
          </>
        ) : null}

        {detailContentTab === "trade_detail" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Trades</p>
                <h3>交易详情</h3>
              </div>
            </div>
            <JqTradesPanel runId={runId} available={Boolean(run.series_available.trades ?? run.artifact_stats.trades?.available)} />
          </section>
        ) : null}

        {detailContentTab === "daily_position" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Positions</p>
                <h3>每日持仓&收益</h3>
              </div>
            </div>
            <JqDailyHoldingsPanel runId={runId} available={Boolean(run.series_available.positions ?? run.artifact_stats.positions?.available)} />
          </section>
        ) : null}

        {detailContentTab === "log_output" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Logs</p>
                <h3>日志输出</h3>
              </div>
            </div>
            <div className="code-block compact-code">
              {(logsQuery.data?.entries ?? []).map((entry, index) => (
                <div key={index}>
                  {entry.timestamp} - {entry.level} - {entry.message}
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {detailContentTab === "strategy_code" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Source</p>
                <h3>策略代码</h3>
              </div>
            </div>
            <pre className="code-block compact-code">{sourceQuery.data?.content ?? "# 未提供 strategy.py"}</pre>
          </section>
        ) : null}

        {detailContentTab === "report" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Report</p>
                <h3>Markdown 报告</h3>
              </div>
            </div>
            <pre className="code-block compact-code">{run.report_markdown || "未提供 report.md"}</pre>
          </section>
        ) : null}

        {detailContentTab === "attribution" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Attribution</p>
                <h3>归因</h3>
              </div>
            </div>
            {attributionQuery.data?.available ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {Object.keys((attributionRowsPayload(attributionQuery.data)[0] ?? {}) as Record<string, unknown>).map((key) => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {attributionRowsPayload(attributionQuery.data).map((row, index) => (
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
              <p className="muted">{(attributionQuery.data as RunAttributionResponse | undefined)?.message ?? "未提供 attribution.csv"}</p>
            )}
          </section>
        ) : null}

        {detailContentTab === "performance" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Artifacts</p>
                <h3>性能分析</h3>
              </div>
            </div>
            <div className="grid-3">
              {Object.entries(run.artifact_stats).map(([key, item]) => (
                <div key={key} className="metric-card">
                  <span>{key}</span>
                  <strong>{item.available ? "已提供" : "缺失"}</strong>
                  <small className="muted">{item.file_size_bytes ? formatFileSize(item.file_size_bytes) : "—"}</small>
                  <small className="muted">{item.row_count != null ? `${item.row_count} rows` : "—"}</small>
                </div>
              ))}
            </div>
            {run.produced_outputs.length ? (
              <div className="table-wrap" style={{ marginTop: 16 }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>output_name</th>
                      <th>dataset_name</th>
                      <th>version_id</th>
                      <th>row_count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.produced_outputs.map((item) => (
                      <tr key={`${item.output_name}-${item.version_id ?? ""}`}>
                        <td>{item.output_name}</td>
                        <td>{item.dataset_name ?? "—"}</td>
                        <td>{item.version_id ?? "—"}</td>
                        <td>{item.row_count ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        ) : null}

        {metricConfig && metricOption ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Metric series</p>
                <h3>{metricConfig.title}</h3>
              </div>
            </div>
            <ReactECharts option={metricOption} style={{ height: 420 }} notMerge lazyUpdate />
          </section>
        ) : null}
      </div>
    </div>
  );
}
