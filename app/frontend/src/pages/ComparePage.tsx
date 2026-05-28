import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link, useSearchParams } from "react-router-dom";

import { compareRuns, getCompareSeries, getRunSource } from "../api";
import { MetricCard } from "../components/MetricCard";
import type { RunCompareSeriesResponse, SeriesSegment } from "../types";
import { formatNumber, formatPct, summarizeDatasetVersions } from "../utils";

const text = {
  comparePage: {
    eyebrow: "对比实验",
    emptyTitle: "请先在实验中心选择实验",
    emptyNote: "先在实验中心勾选一个或多个实验，再打开对比页。",
    selectedRunsSuffix: "个已选实验",
    selectedRuns: "已选实验",
    curveAlignment: "曲线对齐",
    rebased: "重设基准",
    segment: "区段",
    metricsEyebrow: "指标矩阵",
    metricsTitle: "按实验查看研究诊断",
    run: "实验",
    strategy: "策略",
    totalReturn: "总收益",
    sharpe: "夏普",
    maxDrawdown: "最大回撤",
    winRate: "胜率",
    avgTurnover: "平均换手",
    feeCost: "手续费成本",
    fundingReturn: "资金费收益",
    curveEyebrow: "曲线对比",
    curveTitle: "重设基准资金曲线与回撤",
    rebasedEquity: "重设基准资金曲线",
    drawdown: "回撤",
    noSeriesData: "当前没有可用的时序数据。",
  },
  app: { secondaryNav: { runs: "回测列表" } },
  common: { latestValue: "最新" },
};

function formatSegment(segment: SeriesSegment): string {
  return segment === "overall" ? "全样本" : "样本外";
}

function SegmentToggle({
  value,
  onChange,
}: {
  value: SeriesSegment;
  onChange: (value: SeriesSegment) => void;
}) {
  return (
    <div className="segment-toggle" role="tablist" aria-label="Compare segment">
      {(["overall", "oos"] as const).map((segment) => (
        <button
          key={segment}
          type="button"
          className={segment === value ? "toggle-button active" : "toggle-button"}
          onClick={() => onChange(segment)}
        >
          {formatSegment(segment)}
        </button>
      ))}
    </div>
  );
}

function buildCompareChartData(series: RunCompareSeriesResponse) {
  const rows = new Map<string, Record<string, string | number>>();
  for (const run of series.runs) {
    for (const point of run.points) {
      const rowKey = point.timestamp ?? `step-${point.step_index ?? 0}`;
      const current = rows.get(rowKey) ?? { row_key: rowKey, step_index: point.step_index ?? 0, timestamp: point.timestamp ?? "" };
      if (point.value !== undefined && point.value !== null) {
        current[run.run_id] = point.value;
      }
      rows.set(rowKey, current);
    }
  }
  return Array.from(rows.values()).sort((left, right) => {
    const leftTs = Date.parse(String(left.timestamp ?? ""));
    const rightTs = Date.parse(String(right.timestamp ?? ""));
    if (Number.isFinite(leftTs) && Number.isFinite(rightTs)) {
      return leftTs - rightTs;
    }
    return Number(left.step_index) - Number(right.step_index);
  });
}

function CompareChart({
  title,
  data,
  runIds,
  formatter,
  xKey,
}: {
  title: string;
  data: Array<Record<string, string | number>>;
  runIds: string[];
  formatter: (value?: number | null) => string;
  xKey: "step_index" | "timestamp";
}) {
  const palette = ["#76e3d1", "#f2a65a", "#8de1a2", "#ff8a8a", "#9bb0cb"];
  return (
    <div className="chart-card">
      <div className="panel-header compact">
        <h3>{title}</h3>
      </div>
      {data.length > 0 ? (
        <div className="chart-shell">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={data}>
              <CartesianGrid stroke="rgba(125, 182, 255, 0.12)" vertical={false} />
              <XAxis dataKey={xKey} stroke="#9bb0cb" minTickGap={32} />
              <YAxis stroke="#9bb0cb" tickFormatter={(value) => formatter(Number(value))} width={80} />
              <Tooltip
                formatter={(value: number) => formatter(Number(value))}
                contentStyle={{
                  background: "rgba(8, 17, 31, 0.96)",
                  border: "1px solid rgba(125, 182, 255, 0.18)",
                  borderRadius: "16px",
                }}
              />
              {runIds.map((runId, index) => (
                <Line
                  key={runId}
                  type="monotone"
                  dataKey={runId}
                  stroke={palette[index % palette.length]}
                  dot={false}
                  strokeWidth={2.2}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="muted panel-body">{text.comparePage.noSeriesData}</p>
      )}
    </div>
  );
}

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const [segment, setSegment] = useState<SeriesSegment>("overall");
  const mode = searchParams.get("mode") === "code" ? "code" : "overview";
  const runIds = useMemo(() => searchParams.getAll("run_ids"), [searchParams]);

  const compareQuery = useQuery({
    queryKey: ["compare", runIds],
    queryFn: () => compareRuns(runIds),
    enabled: runIds.length > 0,
    refetchInterval: (query) => {
      const data = query.state.data as { runs?: Array<{ status?: string }> } | undefined;
      const hasRunning = (data?.runs ?? []).some((item) => ["queued", "running"].includes(item.status ?? ""));
      return hasRunning ? 2500 : false;
    },
  });
  const equityQuery = useQuery({
    queryKey: ["compare-series", runIds, "equity", segment],
    queryFn: () => getCompareSeries(runIds, "equity", segment),
    enabled: mode === "overview" && runIds.length > 0,
  });
  const drawdownQuery = useQuery({
    queryKey: ["compare-series", runIds, "drawdown", segment],
    queryFn: () => getCompareSeries(runIds, "drawdown", segment),
    enabled: mode === "overview" && runIds.length > 0,
  });
  const codeQuery = useQuery({
    queryKey: ["compare-code", runIds],
    queryFn: async () =>
      Promise.all(
        runIds.map(async (runId) => ({
          runId,
          source: await getRunSource(runId),
        })),
      ),
    enabled: mode === "code" && runIds.length > 0,
  });

  if (runIds.length === 0) {
    return (
      <section className="panel panel-full">
        <div className="panel-header">
          <p className="eyebrow">{text.comparePage.eyebrow}</p>
          <h2>{text.comparePage.emptyTitle}</h2>
        </div>
        <p className="inline-note muted">{text.comparePage.emptyNote}</p>
      </section>
    );
  }

  const equityData = buildCompareChartData(equityQuery.data ?? { series: "equity", segment, runs: [] });
  const drawdownData = buildCompareChartData(drawdownQuery.data ?? { series: "drawdown", segment, runs: [] });
  const xKey: "step_index" | "timestamp" = equityData.some((item) => String(item.timestamp ?? "").length > 0) ? "timestamp" : "step_index";
  const codeItems = codeQuery.data ?? [];
  const codeContents = codeItems.map((item) => item.source.content);
  const codeIdentical = codeContents.length > 1 && codeContents.every((item) => item === codeContents[0]);

  return (
    <div className="detail-stack">
      <section className="panel panel-soft">
        <div className="panel-header split">
          <div>
            <p className="eyebrow">{text.comparePage.eyebrow}</p>
            <h2>
              {runIds.length} {text.comparePage.selectedRunsSuffix}
            </h2>
          </div>
          <div className="button-row">
            <Link className="ghost-button" to="/runs">
              {text.app.secondaryNav.runs}
            </Link>
            {mode === "overview" ? <SegmentToggle value={segment} onChange={setSegment} /> : null}
          </div>
        </div>
        <div className="metric-grid">
          <MetricCard label={text.comparePage.selectedRuns} value={String(runIds.length)} />
          <MetricCard label={text.comparePage.curveAlignment} value={mode === "code" ? "Code Snapshot" : text.comparePage.rebased} />
          <MetricCard label={text.comparePage.segment} value={mode === "code" ? "Code" : formatSegment(segment)} />
        </div>
      </section>

      {mode === "code" ? (
        <section className="panel panel-soft">
          <div className="panel-header">
            <p className="eyebrow">{text.comparePage.metricsEyebrow}</p>
            <h3>代码对比</h3>
          </div>
          <p className="inline-note muted">
            {codeIdentical ? "当前选中回测的策略快照内容一致。" : "当前选中回测的策略快照内容存在差异。"}
          </p>
          <div className="jq-run-chart-grid">
            {codeItems.map((item) => {
              const run = compareQuery.data?.runs.find((entry) => entry.run_id === item.runId);
              return (
                <div key={item.runId} className="jq-run-chart-card">
                  <div className="jq-run-chart-head">
                    <strong>{run?.strategy_name ?? item.runId}</strong>
                    <span>{item.source.file_name}</span>
                  </div>
                  <div className="jq-run-chart-body">
                    <pre className="jq-run-code-block">{item.source.content}</pre>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {mode === "overview" ? (
        <>
          <section className="panel panel-soft">
            <div className="panel-header">
              <p className="eyebrow">{text.comparePage.metricsEyebrow}</p>
              <h3>{text.comparePage.metricsTitle}</h3>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{text.comparePage.run}</th>
                    <th>{text.comparePage.strategy}</th>
                    <th>可信度</th>
                    <th>{text.comparePage.totalReturn}</th>
                    <th>{text.comparePage.sharpe}</th>
                    <th>{text.comparePage.maxDrawdown}</th>
                    <th>{text.comparePage.winRate}</th>
                    <th>{text.comparePage.avgTurnover}</th>
                    <th>{text.comparePage.feeCost}</th>
                    <th>{text.comparePage.fundingReturn}</th>
                  </tr>
                </thead>
                <tbody>
                  {compareQuery.data?.runs.map((run) => {
                    const metrics = segment === "overall" ? run.overall : run.out_of_sample;
                    const fee = run.cost_breakdown?.fee_cost;
                    const funding = run.cost_breakdown?.funding_return;
                    const avgTurn =
                      (metrics as Record<string, number | null | undefined>).avg_turnover ?? (metrics as Record<string, number | null | undefined>).turnover;
                    return (
                      <tr key={run.run_id}>
                        <td>
                          <Link to={`/runs/${run.run_id}`}>{run.run_id}</Link>
                          {["queued", "running"].includes(run.status) ? <span className="row-subtitle">实时中</span> : null}
                          <span className="row-subtitle">{run.universe_snapshot_id ?? text.common.latestValue}</span>
                        </td>
                        <td>
                          <strong>{run.strategy_name}</strong>
                          <span className="row-subtitle">{summarizeDatasetVersions(run.dataset_versions ?? {})}</span>
                        </td>
                        <td>
                          {(() => {
                            const rs = (run as any).risk_summary as { trust_level?: string; flags?: any[] } | undefined;
                            if (!rs) return <span style={{ color: "#888" }}>—</span>;
                            const colorMap: Record<string, string> = {
                              ok: "#1f9a52", caution: "#c98a14", high_risk: "#cc3344", insufficient_data: "#888",
                            };
                            const labelMap: Record<string, string> = {
                              ok: "可信", caution: "存疑", high_risk: "高风险", insufficient_data: "信息不足",
                            };
                            const color = colorMap[rs.trust_level || "insufficient_data"];
                            const label = labelMap[rs.trust_level || "insufficient_data"];
                            return (
                              <span title={(rs.flags || []).map((f: any) => f.message).join(" · ")}
                                    style={{ color, fontWeight: 600, fontSize: 12 }}>
                                ● {label}
                                {rs.flags && rs.flags.length > 0 && (
                                  <span style={{ marginLeft: 4, fontWeight: 400, fontSize: 10 }}>({rs.flags.length})</span>
                                )}
                              </span>
                            );
                          })()}
                        </td>
                        <td>{formatPct(metrics.total_return)}</td>
                        <td>{formatNumber(metrics.sharpe)}</td>
                        <td>{formatPct(metrics.max_drawdown)}</td>
                        <td>{formatPct(metrics.win_rate)}</td>
                        <td>{formatNumber(avgTurn)}</td>
                        <td>{formatPct(typeof fee === "number" ? fee : null)}</td>
                        <td>{formatPct(typeof funding === "number" ? funding : null)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel panel-soft">
            <div className="panel-header">
              <p className="eyebrow">{text.comparePage.curveEyebrow}</p>
              <h3>{text.comparePage.curveTitle}</h3>
            </div>
            <div className="chart-grid compare-grid">
              <CompareChart
                title={text.comparePage.rebasedEquity}
                data={equityData}
                runIds={runIds}
                formatter={(value) => formatNumber(value, 3)}
                xKey={xKey}
              />
              <CompareChart
                title={text.comparePage.drawdown}
                data={drawdownData}
                runIds={runIds}
                formatter={formatPct}
                xKey={drawdownData.some((item) => String(item.timestamp ?? "").length > 0) ? "timestamp" : "step_index"}
              />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
