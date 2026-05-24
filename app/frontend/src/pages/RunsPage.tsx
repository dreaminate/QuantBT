import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { connectRunsSocket, decodeRealtimeEvent, deleteRun, queryRuns } from "../api";
import { StatusPill } from "../components/StatusPill";
import type { RunNumericFilter, RunQueryRequest, RunSummary } from "../types";
import { formatNumber, formatPct, summarizeDatasetVersions } from "../utils";

const T = {
  runsPage: {
    deleteRuns: "删除回测",
    compareAction: "对比实验",
    search: "搜索",
    favoriteOnly: "仅收藏",
    strategyMode: "策略模式",
    datasetVersion: "数据集版本",
    universeSnapshot: "Universe 快照",
    status: "状态",
    modelUsed: "使用模型",
    sharpeMin: "夏普 >=",
    drawdownMax: "回撤 <=",
    turnoverMax: "换手 <=",
    fitnessMin: "适应度 >=",
    longCountMin: "多头数 >=",
    shortCountMin: "空头数 >=",
    record: "记录",
    strategy: "策略",
    script: "脚本",
    totalReturn: "总收益",
    sharpe: "夏普",
    maxDrawdown: "最大回撤",
    dataset: "数据集",
    universe: "Universe",
    select: "选择",
  },
  common: { all: "全部", missing: "缺失" },
  simulatePage: { benchmark: "基准" },
  comparePage: { winRate: "胜率" },
};

const STRATEGY_KINDS: Record<string, string> = {
  rule: "规则",
  model: "模型",
  combo: "组合",
  unknown: "未知",
};

function formatStrategyKind(kind: string) {
  return STRATEGY_KINDS[kind] ?? kind;
}

type RunFilters = {
  search: string;
  favoriteOnly: boolean;
  strategyMode: string;
  market: string;
  frequency: string;
  benchmark: string;
  datasetVersion: string;
  universeSnapshot: string;
  status: string;
  modelUsed: "all" | "true" | "false";
};

type NumericInputs = {
  sharpe: { operator: RunNumericFilter["operator"]; value: string; valueTo: string };
  drawdown: { operator: RunNumericFilter["operator"]; value: string; valueTo: string };
  turnover: { operator: RunNumericFilter["operator"]; value: string; valueTo: string };
  fitness: { operator: RunNumericFilter["operator"]; value: string; valueTo: string };
  long_count: { operator: RunNumericFilter["operator"]; value: string; valueTo: string };
  short_count: { operator: RunNumericFilter["operator"]; value: string; valueTo: string };
};

function runDisplayName(recordName: string | null | undefined, runId: string) {
  return recordName?.trim() ? recordName : runId;
}

function parseNumber(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildNumericFilters(values: NumericInputs): RunNumericFilter[] {
  const filters: RunNumericFilter[] = [];
  for (const field of ["sharpe", "drawdown", "turnover", "fitness", "long_count", "short_count"] as const) {
    const item = values[field];
    const value = parseNumber(item.value);
    const valueTo = parseNumber(item.valueTo);
    if (value === null) {
      continue;
    }
    if (item.operator === "between") {
      if (valueTo === null) {
        continue;
      }
      filters.push({ field, operator: "between", value, value_to: valueTo });
      continue;
    }
    filters.push({ field, operator: item.operator, value });
  }
  return filters;
}

export function RunsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const initialSearch = searchParams.get("strategy_id") ?? "";
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [filters, setFilters] = useState<RunFilters>({
    search: initialSearch,
    favoriteOnly: false,
    strategyMode: "all",
    market: "all",
    frequency: "all",
    benchmark: "all",
    datasetVersion: "all",
    universeSnapshot: "all",
    status: "all",
    modelUsed: "all",
  });
  const [numericInputs, setNumericInputs] = useState<NumericInputs>({
    sharpe: { operator: ">=", value: "", valueTo: "" },
    drawdown: { operator: "<=", value: "", valueTo: "" },
    turnover: { operator: "<=", value: "", valueTo: "" },
    fitness: { operator: ">=", value: "", valueTo: "" },
    long_count: { operator: ">=", value: "", valueTo: "" },
    short_count: { operator: ">=", value: "", valueTo: "" },
  });
  const [realtimeStatuses, setRealtimeStatuses] = useState<Record<string, string>>({});

  const numericFilters = useMemo(() => buildNumericFilters(numericInputs), [numericInputs]);
  const request = useMemo<RunQueryRequest>(
    () => ({
      search: filters.search,
      favorite_only: filters.favoriteOnly,
      strategy_mode: filters.strategyMode === "all" ? null : filters.strategyMode,
      market: filters.market === "all" ? null : filters.market,
      frequency: filters.frequency === "all" ? null : filters.frequency,
      benchmark: filters.benchmark === "all" ? null : filters.benchmark,
      dataset_version: filters.datasetVersion === "all" ? null : filters.datasetVersion,
      universe_snapshot_id: filters.universeSnapshot === "all" ? null : filters.universeSnapshot,
      status: filters.status === "all" ? null : filters.status,
      model_used: filters.modelUsed === "all" ? null : filters.modelUsed === "true",
      sort_by: "started_at",
      sort_order: "desc",
      limit: 200,
      offset: 0,
      numeric_filters: numericFilters,
    }),
    [filters, numericFilters],
  );

  const runsQuery = useQuery({
    queryKey: ["runs-query", request],
    queryFn: () => queryRuns(request),
    refetchInterval: (query) => {
      const data = query.state.data as { rows?: RunSummary[] } | undefined;
      const hasRunning = (data?.rows ?? []).some((item) => ["queued", "running"].includes(item.status));
      return hasRunning ? 2500 : false;
    },
  });

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      return;
    }
    const socket = connectRunsSocket();
    socket.onmessage = (messageEvent) => {
      const event = decodeRealtimeEvent(messageEvent);
      if (!event || event.type !== "status") {
        return;
      }
      const payload = (event.payload ?? {}) as Record<string, unknown>;
      if (typeof payload.run_id !== "string" || typeof payload.status !== "string") {
        return;
      }
      setRealtimeStatuses((current) => ({ ...current, [payload.run_id as string]: payload.status as string }));
    };
    return () => socket.close();
  }, []);

  const deleteRunsMutation = useMutation({
    mutationFn: async (runIds: string[]) => {
      for (const runId of runIds) {
        await deleteRun(runId);
      }
    },
    onSuccess: async (_, runIds) => {
      setSelectedIds((current) => current.filter((item) => !runIds.includes(item)));
      await queryClient.invalidateQueries({ queryKey: ["runs-query"] });
    },
  });

  const sortedSelectedIds = useMemo(() => [...selectedIds].sort(), [selectedIds]);
  const runs = runsQuery.data?.rows ?? [];
  const availableFilters = runsQuery.data?.available_filters ?? {};
  const activeNumericFilterChips = useMemo(
    () =>
      numericFilters.map((item) =>
        item.operator === "between"
          ? `${item.field} between ${item.value} and ${item.value_to}`
          : `${item.field} ${item.operator} ${item.value}`,
      ),
    [numericFilters],
  );

  const toggleRun = (runId: string) => {
    setSelectedIds((current) => (current.includes(runId) ? current.filter((item) => item !== runId) : [...current, runId]));
  };

  const updateNumericField = (field: keyof NumericInputs, key: "operator" | "value" | "valueTo", value: string) => {
    setNumericInputs((current) => ({
      ...current,
      [field]: {
        ...current[field],
        [key]: value,
      },
    }));
  };

  const [filtersOpen, setFiltersOpen] = useState(true);

  return (
    <section className="panel panel-full">
      <div className="panel-header split">
        <div>
          <h2>回测列表</h2>
          <span className="row-subtitle">共 {runsQuery.data?.total_rows ?? 0} 条记录</span>
        </div>
        <div className="button-row">
          <button
            type="button"
            className="ghost-button"
            disabled={sortedSelectedIds.length === 0 || deleteRunsMutation.isPending}
            onClick={() => {
              if (window.confirm(`确定删除已选中的 ${sortedSelectedIds.length} 条回测？`)) {
                deleteRunsMutation.mutate(sortedSelectedIds);
              }
            }}
          >
            {T.runsPage.deleteRuns} {sortedSelectedIds.length || ""}
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={sortedSelectedIds.length === 0}
            onClick={() =>
              navigate(`/compare?${sortedSelectedIds.map((runId) => `run_ids=${encodeURIComponent(runId)}`).join("&")}`)
            }
          >
            {T.runsPage.compareAction} {sortedSelectedIds.length || ""}
          </button>
        </div>
      </div>

      <div style={{ padding: "0 20px 8px" }}>
        <button type="button" className="ghost-button" style={{ fontSize: 12 }} onClick={() => setFiltersOpen((c) => !c)}>
          {filtersOpen ? "收起筛选 ▲" : "展开筛选 ▼"}
        </button>
      </div>
      <div className="toolbar-grid" style={{ display: filtersOpen ? undefined : "none" }}>
        <label>
          <span>{T.runsPage.search}</span>
          <input
            aria-label="run-search"
            value={filters.search}
            onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
          />
        </label>
        <label className="checkbox-row">
          <span>{T.runsPage.favoriteOnly}</span>
          <input
            type="checkbox"
            checked={filters.favoriteOnly}
            onChange={(event) => setFilters((current) => ({ ...current, favoriteOnly: event.target.checked }))}
          />
        </label>
        <label>
          <span>{T.runsPage.strategyMode}</span>
          <select
            aria-label="strategy-mode-filter"
            value={filters.strategyMode}
            onChange={(event) => setFilters((current) => ({ ...current, strategyMode: event.target.value }))}
          >
            <option value="all">{T.common.all}</option>
            {(availableFilters.strategy_mode ?? []).map((option) => (
              <option key={option} value={option}>
                {formatStrategyKind(option)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{T.runsPage.datasetVersion}</span>
          <select
            aria-label="dataset-filter"
            value={filters.datasetVersion}
            onChange={(event) => setFilters((current) => ({ ...current, datasetVersion: event.target.value }))}
          >
            <option value="all">{T.common.all}</option>
            {(availableFilters.dataset_version ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>市场</span>
          <select aria-label="market-filter" value={filters.market} onChange={(event) => setFilters((current) => ({ ...current, market: event.target.value }))}>
            <option value="all">{T.common.all}</option>
            {(availableFilters.market ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>周期</span>
          <select
            aria-label="frequency-filter"
            value={filters.frequency}
            onChange={(event) => setFilters((current) => ({ ...current, frequency: event.target.value }))}
          >
            <option value="all">{T.common.all}</option>
            {(availableFilters.frequency ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{T.simulatePage.benchmark}</span>
          <select
            aria-label="benchmark-filter"
            value={filters.benchmark}
            onChange={(event) => setFilters((current) => ({ ...current, benchmark: event.target.value }))}
          >
            <option value="all">{T.common.all}</option>
            {(availableFilters.benchmark ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{T.runsPage.universeSnapshot}</span>
          <select
            aria-label="universe-filter"
            value={filters.universeSnapshot}
            onChange={(event) => setFilters((current) => ({ ...current, universeSnapshot: event.target.value }))}
          >
            <option value="all">{T.common.all}</option>
            {(availableFilters.universe_snapshot_id ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{T.runsPage.status}</span>
          <select aria-label="status-filter" value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}>
            <option value="all">{T.common.all}</option>
            {(availableFilters.status ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{T.runsPage.modelUsed}</span>
          <select
            aria-label="model-used-filter"
            value={filters.modelUsed}
            onChange={(event) =>
              setFilters((current) => ({ ...current, modelUsed: event.target.value as RunFilters["modelUsed"] }))
            }
          >
            <option value="all">{T.common.all}</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </label>
        {(
          [
            ["sharpe", T.runsPage.sharpeMin, "sharpe-min-filter"],
            ["drawdown", T.runsPage.drawdownMax, "drawdown-max-filter"],
            ["turnover", T.runsPage.turnoverMax, "turnover-max-filter"],
            ["fitness", T.runsPage.fitnessMin, "fitness-min-filter"],
            ["long_count", T.runsPage.longCountMin, "long-count-min-filter"],
            ["short_count", T.runsPage.shortCountMin, "short-count-min-filter"],
          ] as const
        ).map(([field, label, ariaLabel]) => (
          <label key={field}>
            <span>{label}</span>
            <div className="button-row">
              <select value={numericInputs[field].operator} onChange={(event) => updateNumericField(field, "operator", event.target.value)}>
                <option value=">=">&gt;=</option>
                <option value="<=">&lt;=</option>
                <option value=">">&gt;</option>
                <option value="<">&lt;</option>
                <option value="=">=</option>
                <option value="between">between</option>
              </select>
              <input aria-label={ariaLabel} value={numericInputs[field].value} onChange={(event) => updateNumericField(field, "value", event.target.value)} />
              {numericInputs[field].operator === "between" ? (
                <input
                  aria-label={`${ariaLabel}-secondary`}
                  value={numericInputs[field].valueTo}
                  onChange={(event) => updateNumericField(field, "valueTo", event.target.value)}
                />
              ) : null}
            </div>
          </label>
        ))}
      </div>

      {activeNumericFilterChips.length > 0 ? (
        <div className="button-row">
          {activeNumericFilterChips.map((chip) => (
            <span key={chip} className="hint-card">
              {chip}
            </span>
          ))}
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th />
              <th>{T.runsPage.record}</th>
              <th>{T.runsPage.strategy}</th>
              <th>{T.runsPage.script}</th>
              <th>{T.runsPage.totalReturn}</th>
              <th>年化收益</th>
              <th>{T.runsPage.sharpe}</th>
              <th>{T.runsPage.maxDrawdown}</th>
              <th>{T.comparePage.winRate}</th>
              <th>{T.runsPage.dataset}</th>
              <th>{T.runsPage.universe}</th>
              <th>市场</th>
              <th>{T.simulatePage.benchmark}</th>
              <th>{T.runsPage.modelUsed}</th>
              <th>{T.runsPage.status}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`${T.runsPage.select} ${run.run_id}`}
                    checked={selectedIds.includes(run.run_id)}
                    onChange={() => toggleRun(run.run_id)}
                  />
                </td>
                <td>
                  <Link to={`/runs/${run.run_id}`}>{runDisplayName(run.record_name, run.run_id)}</Link>
                  <span className="row-subtitle">{run.run_id}</span>
                  <span className="row-subtitle">{run.started_at}</span>
                </td>
                <td>
                  <strong>{run.strategy_name}</strong>
                  <span className="row-subtitle">{formatStrategyKind(run.strategy_mode ?? "unknown")}</span>
                </td>
                <td>{run.strategy_script_name ?? T.common.missing}</td>
                <td
                  style={{
                    color: Number(run.returns ?? run.overall.total_return ?? 0) >= 0 ? "var(--danger)" : "var(--success)",
                    fontWeight: 600,
                  }}
                >
                  {formatPct(run.returns ?? run.overall.total_return)}
                </td>
                <td
                  style={{
                    color: Number(run.annualized_return ?? run.overall.annualized_return ?? 0) >= 0 ? "var(--danger)" : "var(--success)",
                    fontWeight: 600,
                  }}
                >
                  {formatPct(run.annualized_return ?? run.overall.annualized_return)}
                </td>
                <td style={{ fontWeight: 600 }}>{formatNumber(run.sharpe ?? run.overall.sharpe)}</td>
                <td style={{ color: "var(--success)", fontWeight: 600 }}>{formatPct(run.drawdown ?? run.overall.max_drawdown)}</td>
                <td style={{ fontWeight: 600 }}>{formatPct(run.win_rate ?? run.overall.win_rate)}</td>
                <td>{summarizeDatasetVersions(run.dataset_versions ?? {})}</td>
                <td>{run.universe_snapshot_id ?? "最新"}</td>
                <td>{run.market ?? T.common.missing}</td>
                <td>{run.benchmark ?? T.common.missing}</td>
                <td>{run.model_used ? "true" : "false"}</td>
                <td>
                  <StatusPill status={realtimeStatuses[run.run_id] ?? run.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
