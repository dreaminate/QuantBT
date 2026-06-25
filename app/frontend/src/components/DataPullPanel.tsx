import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createBinanceFullPullJob, createDataPullJob, getJob, listDataKinds, listSymbolPools } from "../api";
import { JobPanel } from "./JobPanel";
import { JobProgressBanner } from "./JobProgressBanner";
import {
  buildDataPullPayload,
  formatDataKindLabel,
  formatMarketLabel,
  parseSymbolsInput,
  REFRESH_MODE_OPTIONS,
  SYMBOL_SOURCE_OPTIONS,
  type SymbolSource,
  validateClientPullForm,
} from "../lib/dataPullForm";
import type { DataPullRequest, JobResponse } from "../types";

const BINANCE_KLINE_INTERVALS = [
  "1m",
  "3m",
  "5m",
  "15m",
  "30m",
  "1h",
  "2h",
  "4h",
  "6h",
  "8h",
  "12h",
  "1d",
  "3d",
  "1w",
  "1M",
] as const;

/** Binance /futures/data openInterestHist & takerBuySellVol `period` (subset of kline intervals). */
const BINANCE_FUTURES_DATA_PERIODS = ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"] as const;

/** Vision USDM daily zip kline-compatible intervals (aligns with backend VISION_DAILY_KLINE_INTERVALS). */
const VISION_DAILY_KLINE_INTERVALS = [
  "1s",
  "1m",
  "3m",
  "5m",
  "15m",
  "30m",
  "1h",
  "2h",
  "4h",
  "6h",
  "8h",
  "12h",
  "1d",
] as const;

/** 与后端 VISION_DAILY_KLINE_INTERVAL_KINDS 对齐的日 K Vision 种类 */
const VISION_DAILY_KLINE_DATA_KINDS: readonly string[] = [
  "vision_klines",
  "vision_cm_klines",
  "vision_spot_klines",
  "vision_mark_price_klines",
  "vision_index_price_klines",
  "vision_premium_index_klines",
  "vision_cm_mark_price_klines",
  "vision_cm_index_price_klines",
  "vision_cm_premium_index_klines",
];

type DomainConfig = {
  key: string;
  label: string;
  pullMarkets: string[];
};

type DataPullPanelProps = {
  domain: DomainConfig;
  onGoToBrowser: (market: string) => void;
  onGoToTaskCenter: () => void;
};

export function DataPullPanel({ domain, onGoToBrowser, onGoToTaskCenter }: DataPullPanelProps) {
  const queryClient = useQueryClient();

  const [market, setMarket] = useState(domain.pullMarkets[0]);
  const [dataKind, setDataKind] = useState("");
  const [symbolSource, setSymbolSource] = useState<SymbolSource>("manual");
  const [poolId, setPoolId] = useState("");
  const [symbolsInput, setSymbolsInput] = useState("");
  const [fullHistory, setFullHistory] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [refreshMode, setRefreshMode] = useState<"incremental" | "full">("incremental");
  const [binanceInterval, setBinanceInterval] = useState("1h");
  /** 批量全量拉取传给后端的 default_interval（K 线柱宽，非历史长度） */
  const [fullPullDefaultInterval, setFullPullDefaultInterval] = useState("1h");
  const [jobId, setJobId] = useState<string | null>(null);
  const [lastRefreshedJobId, setLastRefreshedJobId] = useState<string | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);

  useEffect(() => {
    setMarket(domain.pullMarkets[0]);
    setDataKind("");
    setBinanceInterval("1h");
    setFullPullDefaultInterval("1h");
    setSymbolsInput("");
    setPoolId("");
    setSymbolSource("manual");
    setJobId(null);
    setClientError(null);
  }, [domain.key, domain.pullMarkets]);

  const kindsQuery = useQuery({
    queryKey: ["data-kinds", market],
    queryFn: () => listDataKinds({ market }),
  });

  const poolsQuery = useQuery({
    queryKey: ["data-pools", market],
    queryFn: () => listSymbolPools({ market }),
  });

  useEffect(() => {
    const kinds = kindsQuery.data ?? [];
    if (kinds.length === 0) {
      setDataKind("");
      return;
    }
    if (!kinds.some((item) => item.data_kind === dataKind)) {
      setDataKind(kinds[0].data_kind);
    }
  }, [kindsQuery.data, dataKind]);

  useEffect(() => {
    if (symbolSource !== "pool") return;
    const pools = poolsQuery.data ?? [];
    if (pools.length === 0) {
      setPoolId("");
    } else if (!pools.some((p) => p.pool_id === poolId)) {
      setPoolId(pools[0].pool_id);
    }
  }, [poolsQuery.data, symbolSource, poolId]);

  useEffect(() => {
    setPoolId("");
    setSymbolSource("manual");
    setClientError(null);
  }, [market]);

  useEffect(() => {
    setSymbolsInput("");
    setClientError(null);
  }, [dataKind]);

  useEffect(() => {
    if (market !== "binanceusdm") return;
    if (dataKind !== "open_interest_hist" && dataKind !== "taker_buy_sell_volume") return;
    if (!BINANCE_FUTURES_DATA_PERIODS.includes(binanceInterval as (typeof BINANCE_FUTURES_DATA_PERIODS)[number])) {
      setBinanceInterval("1h");
    }
  }, [market, dataKind, binanceInterval]);

  useEffect(() => {
    if (market !== "binanceusdm") return;
    if (!VISION_DAILY_KLINE_DATA_KINDS.includes(dataKind)) {
      return;
    }
    if (!VISION_DAILY_KLINE_INTERVALS.includes(binanceInterval as (typeof VISION_DAILY_KLINE_INTERVALS)[number])) {
      setBinanceInterval("1h");
    }
  }, [market, dataKind, binanceInterval]);

  const selectedKind = useMemo(
    () => (kindsQuery.data ?? []).find((item) => item.data_kind === dataKind) ?? null,
    [kindsQuery.data, dataKind],
  );

  const symbolsParsed = useMemo(() => parseSymbolsInput(symbolsInput), [symbolsInput]);

  const fullPullMutation = useMutation({
    mutationFn: () =>
      createBinanceFullPullJob({
        default_interval: fullPullDefaultInterval,
      }),
    onSuccess: (job) => {
      setJobId(job.job_id);
      setLastRefreshedJobId(null);
      setClientError(null);
    },
    onError: (error: Error) => {
      setClientError(error.message);
    },
  });

  const pullMutation = useMutation({
    mutationFn: (payload: DataPullRequest) => createDataPullJob(payload),
    onSuccess: (job) => {
      setJobId(job.job_id);
      setLastRefreshedJobId(null);
      setClientError(null);
    },
    onError: (error: Error) => {
      setClientError(error.message);
    },
  });

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && ["queued", "running"].includes(data.status) ? 1000 : false;
    },
  });

  useEffect(() => {
    if (!jobId || !jobQuery.data || jobQuery.data.status !== "succeeded" || lastRefreshedJobId === jobId) return;
    setLastRefreshedJobId(jobId);
    void queryClient.invalidateQueries({ queryKey: ["data-overview"] });
    void queryClient.invalidateQueries({ queryKey: ["data-files"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["data-kinds", market] });
    void queryClient.invalidateQueries({ queryKey: ["data-pools", market] });
  }, [jobId, jobQuery.data, lastRefreshedJobId, queryClient, market]);

  const submitPull = () => {
    if (!selectedKind) return;
    const err = validateClientPullForm({
      symbolSource,
      poolId,
      poolsLength: (poolsQuery.data ?? []).length,
      symbolsParsed,
      supportsSymbols: selectedKind.supports_symbols,
      fullHistory,
      supportsDateRange: selectedKind.supports_date_range,
      start,
      end,
    });
    if (err) {
      setClientError(err);
      return;
    }
    const payload = buildDataPullPayload({
      market,
      dataKind,
      symbolSource,
      poolId,
      symbolsInput,
      fullHistory,
      start,
      end,
      refreshMode,
      binanceInterval,
      selectedKind,
    });
    setClientError(null);
    pullMutation.mutate(payload);
  };

  const pullDisabled =
    !dataKind ||
    pullMutation.isPending ||
    fullPullMutation.isPending ||
    kindsQuery.isLoading ||
    (symbolSource === "pool" && poolsQuery.isLoading);

  const showPoolHint =
    symbolSource === "pool" &&
    !poolsQuery.isLoading &&
    (poolsQuery.data ?? []).length === 0;

  return (
    <>
      <JobProgressBanner job={jobQuery.data} onViewTasks={onGoToTaskCenter} />

      <section className="data-pull-toolbar panel panel-soft">
        <p className="data-pull-toolbar-text">
          Use Data Browser to inspect A-share files after pulling or refreshing data.
        </p>
        <button type="button" className="ghost-button data-pull-toolbar-btn" onClick={() => onGoToBrowser(market)}>
          Open Data Browser
        </button>
      </section>

      <section className="panel data-pull-card">
        <div className="data-pull-header">
          <p className="eyebrow data-pull-eyebrow">DATA PULL</p>
          <h3 className="data-pull-title">Pull market data</h3>
        </div>

        {market === "binanceusdm" ? (
          <div className="data-pull-full-banner panel-soft" style={{ marginBottom: "1rem", padding: "0.75rem 1rem", borderRadius: "8px" }}>
            <p style={{ margin: "0 0 0.5rem", fontSize: "0.9rem", lineHeight: 1.5 }}>
              按顺序批量拉取<strong>全部加密 data_kind</strong>：Vision 覆盖{" "}
              <a href="https://data.binance.vision/?prefix=data/" target="_blank" rel="noreferrer">
                data.binance.vision
              </a>{" "}
              下 USDM/CM 日频、现货日频、期权 BVOL/EOH；REST 为 USDT 永续。
              <strong>「周期」</strong>指 K 线柱宽（如 <code>1m</code>、<code>1h</code>），
              <em>不是</em>
              只拉「一小时历史」——历史跨度由起止日期决定（批量任务里 Vision 默认从 <code>2019-09-01</code> 到<strong>今天</strong>）。
              下方可选批量任务使用的周期（与 UM REST klines / 需周期的 Vision 共用）；<code>1m</code> 等比 <code>1h</code> 量大得多。任务可能极长，请勿关闭标签。
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", marginBottom: "0.5rem" }}>
              <label className="data-pull-field" style={{ margin: 0, minWidth: "min(100%, 16rem)" }}>
                <span className="data-pull-label">批量全量 · K 线/周期</span>
                <select
                  value={fullPullDefaultInterval}
                  onChange={(e) => setFullPullDefaultInterval(e.target.value)}
                  className="data-pull-control"
                  disabled={fullPullMutation.isPending}
                >
                  {BINANCE_KLINE_INTERVALS.map((iv) => (
                    <option key={iv} value={iv}>
                      {iv}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="primary-button data-pull-primary"
                disabled={pullMutation.isPending || fullPullMutation.isPending || kindsQuery.isLoading}
                onClick={() => {
                  if (
                    !window.confirm(
                      `确定开始批量全量拉取？周期=${fullPullDefaultInterval}，将依次执行所有加密 data_kind（全市场），耗时极长，并可能触发 API 限频。`
                    )
                  ) {
                    return;
                  }
                  setClientError(null);
                  fullPullMutation.mutate();
                }}
              >
                {fullPullMutation.isPending ? "批量全量进行中…" : "批量全量拉取加密"}
              </button>
            </div>
          </div>
        ) : null}

        <div className="data-pull-fields">
          {kindsQuery.isSuccess && (kindsQuery.data?.length ?? 0) === 0 && market !== "binanceusdm" ? (
            <p className="inline-note muted" style={{ gridColumn: "1 / -1", marginBottom: "0.25rem" }}>
              当前市场下<strong>没有可用的 Data Kind</strong>：常见原因是 Tushare token 未配置、调用 <code>user()</code> 失败（含官方限频）、或积分低于 2000，接口列表会被全部过滤掉。请检查环境变量{" "}
              <code>TUSHARE_TOKEN</code> / <code>QUANT1_TUSHARE_TOKENS</code> 或 <code>config/secrets/tushare_tokens.json</code>，并查看后端日志；限频时可稍后再试或依赖本地缓存的 token 校验文件。
            </p>
          ) : null}
          {market !== "binanceusdm" && (kindsQuery.data?.length ?? 0) > 0 ? (
            <p className="inline-note muted" style={{ gridColumn: "1 / -1", marginBottom: "0.25rem" }}>
              A 股等 Tushare 拉取往往要拆成大量请求，受每分钟频次限制，进度可能在 35%～80% 停留很久，属正常现象；全历史 + 全市场会特别久。
            </p>
          ) : null}
          <label className="data-pull-field">
            <span className="data-pull-label">Market</span>
            <select value={market} onChange={(event) => setMarket(event.target.value)} className="data-pull-control">
              {domain.pullMarkets.map((m) => (
                <option key={m} value={m}>
                  {formatMarketLabel(m)}
                </option>
              ))}
            </select>
          </label>

          <label className="data-pull-field">
            <span className="data-pull-label">Data Kind</span>
            <select value={dataKind} onChange={(event) => setDataKind(event.target.value)} className="data-pull-control">
              {(kindsQuery.data ?? []).map((item) => (
                <option key={item.data_kind} value={item.data_kind}>
                  {formatDataKindLabel(item)}
                </option>
              ))}
            </select>
          </label>

          {market === "binanceusdm" &&
          (selectedKind?.needs_binance_interval ||
            [
              "klines",
              ...VISION_DAILY_KLINE_DATA_KINDS,
              "open_interest_hist",
              "taker_buy_sell_volume",
            ].includes(dataKind)) ? (
            <label className="data-pull-field">
              <span className="data-pull-label">
                {dataKind === "open_interest_hist" || dataKind === "taker_buy_sell_volume" ? "Period" : "K-line interval"}
              </span>
              <select value={binanceInterval} onChange={(event) => setBinanceInterval(event.target.value)} className="data-pull-control">
                {(dataKind === "open_interest_hist" || dataKind === "taker_buy_sell_volume"
                  ? BINANCE_FUTURES_DATA_PERIODS
                  : VISION_DAILY_KLINE_DATA_KINDS.includes(dataKind)
                    ? VISION_DAILY_KLINE_INTERVALS
                    : BINANCE_KLINE_INTERVALS
                ).map((interval) => (
                  <option key={interval} value={interval}>
                    {interval}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label className="data-pull-field">
            <span className="data-pull-label">Symbol source</span>
            <select
              value={symbolSource}
              onChange={(event) => setSymbolSource(event.target.value as SymbolSource)}
              className="data-pull-control"
            >
              {SYMBOL_SOURCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          {symbolSource === "pool" ? (
            <label className="data-pull-field">
              <span className="data-pull-label">Choose pool</span>
              <select value={poolId} onChange={(event) => setPoolId(event.target.value)} className="data-pull-control" disabled={!poolsQuery.data?.length}>
                {(poolsQuery.data ?? []).length === 0 ? (
                  <option value="">—</option>
                ) : (
                  (poolsQuery.data ?? []).map((p) => (
                    <option key={p.pool_id} value={p.pool_id}>
                      {p.name} ({p.symbol_count})
                    </option>
                  ))
                )}
              </select>
            </label>
          ) : null}

          {showPoolHint ? (
            <p className="data-pull-pool-hint">
              No pools for this market yet. Create one under Pools in the sidebar (pick A-share / HK / US / Crypto first).
            </p>
          ) : null}

          {symbolSource === "manual" ? (
            <label className="data-pull-field">
              <span className="data-pull-label">Symbols</span>
              <textarea
                value={symbolsInput}
                onChange={(event) => setSymbolsInput(event.target.value)}
                rows={4}
                className="data-pull-control data-pull-textarea"
                disabled={!selectedKind?.supports_symbols}
                placeholder={selectedKind?.supports_symbols ? "BTCUSDT, ETHUSDT or 000001.SZ" : "Not required for this data kind"}
              />
            </label>
          ) : null}

          <div className="data-pull-checkbox-row">
            <span className="data-pull-label">Pull full available history</span>
            <input
              type="checkbox"
              checked={fullHistory}
              onChange={(event) => {
                setFullHistory(event.target.checked);
                if (event.target.checked) setClientError(null);
              }}
            />
          </div>

          <label className="data-pull-field">
            <span className="data-pull-label">Start</span>
            <input
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              disabled={fullHistory || !selectedKind?.supports_date_range}
              className="data-pull-control"
              placeholder="年 / 月 / 日"
            />
          </label>

          <label className="data-pull-field">
            <span className="data-pull-label">End</span>
            <input
              type="date"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              disabled={fullHistory || !selectedKind?.supports_date_range}
              className="data-pull-control"
              placeholder="年 / 月 / 日"
            />
          </label>

          <label className="data-pull-field">
            <span className="data-pull-label">Refresh Mode</span>
            <select
              value={refreshMode}
              onChange={(event) => setRefreshMode(event.target.value as "incremental" | "full")}
              className="data-pull-control"
            >
              {REFRESH_MODE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          {clientError ? <p className="data-pull-error">{clientError}</p> : null}

          <div className="data-pull-actions">
            <button type="button" className="primary-button data-pull-primary" onClick={submitPull} disabled={pullDisabled}>
              Pull Data
            </button>
          </div>
        </div>
      </section>

      <section className="panel data-pull-job-status">
        <h4 className="data-pull-job-status-title">Job Status</h4>
        <JobStatusLine job={jobQuery.data} jobId={jobId} />
      </section>

      <JobPanel job={jobQuery.data} />
    </>
  );
}

function JobStatusLine({ job, jobId }: { job: JobResponse | undefined; jobId: string | null }) {
  if (!jobId) {
    return <p className="muted data-pull-job-muted">No active job yet.</p>;
  }
  if (!job) {
    return <p className="muted data-pull-job-muted">Loading job…</p>;
  }
  return (
    <p className="data-pull-job-line">
      <strong>{job.status}</strong>
      {job.progress?.message ? ` — ${job.progress.message}` : ""}
    </p>
  );
}
