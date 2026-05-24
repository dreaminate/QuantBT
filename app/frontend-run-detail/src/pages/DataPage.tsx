import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { cancelJob, getDataPreview, listDataFiles, listDataOverview, listJobs, retryJob } from "../api";
import { DataPullPanel } from "../components/DataPullPanel";
import { StatusPill } from "../components/StatusPill";
import type { JobResponse } from "../types";


type DomainTab = "cn_stock" | "hk_stock" | "us_stock" | "crypto" | "browser" | "jobs";
type DataBrowserBucketId = "cn" | "hk" | "us" | "crypto";

type DomainConfig = {
  key: Exclude<DomainTab, "browser" | "jobs">;
  label: string;
  pullMarkets: string[];
};


const DOMAIN_CONFIGS: DomainConfig[] = [
  { key: "cn_stock", label: "A股/指数/基金/债券", pullMarkets: ["stocks_cn", "indices_cn", "funds_cn", "bonds_cn"] },
  { key: "hk_stock", label: "港股", pullMarkets: ["stocks_hk"] },
  { key: "us_stock", label: "美股", pullMarkets: ["stocks_us"] },
  { key: "crypto", label: "加密", pullMarkets: ["binanceusdm"] },
];

const DOMAIN_TAB_ORDER: DomainTab[] = ["cn_stock", "hk_stock", "us_stock", "crypto", "browser", "jobs"];
const DOMAIN_LABELS: Record<DomainTab, string> = {
  cn_stock: "A股",
  hk_stock: "港股",
  us_stock: "美股",
  crypto: "加密",
  browser: "数据浏览",
  jobs: "任务中心",
};

const DATA_BROWSER_BUCKETS: {
  id: DataBrowserBucketId;
  label: string;
  markets: string[];
}[] = [
  { id: "cn", label: "A股域", markets: ["stocks_cn", "indices_cn", "funds_cn", "bonds_cn"] },
  { id: "hk", label: "港股", markets: ["stocks_hk"] },
  { id: "us", label: "美股", markets: ["stocks_us"] },
  { id: "crypto", label: "加密", markets: ["binanceusdm"] },
];

function preferredBrowserBucketFromMarket(market: string): DataBrowserBucketId {
  if (["stocks_cn", "indices_cn", "funds_cn", "bonds_cn"].includes(market)) return "cn";
  if (market === "stocks_hk") return "hk";
  if (market === "stocks_us") return "us";
  return "crypto";
}


function formatJobType(jobType: string) {
  const mapping: Record<string, string> = {
    data_sync_pull: "数据拉取",
    binance_full_pull: "加密一键全量",
  };
  return mapping[jobType] ?? jobType;
}


function formatJobSummary(job: JobResponse) {
  const summary = job.payload_summary;
  if (!summary || typeof summary !== "object") return "";
  const rec = summary as Record<string, unknown>;
  if (rec.kind === "binance_full_pull") {
    const bits: string[] = [];
    if (rec.market) bits.push(String(rec.market));
    if (rec.default_interval != null && rec.default_interval !== "") bits.push(`周期 ${String(rec.default_interval)}`);
    const vs = rec.vision_start;
    const ve = rec.vision_end;
    if (vs != null || ve != null) bits.push(`Vision ${vs ?? "—"} ~ ${ve ?? "今天"}`);
    return bits.join(" · ");
  }
  const bits: string[] = [];
  if (rec.market) bits.push(String(rec.market));
  if (rec.data_kind) bits.push(String(rec.data_kind));
  if (rec.interval) bits.push(String(rec.interval));
  if (rec.full_history) bits.push("全历史");
  else if (rec.start || rec.end) bits.push(`${rec.start ?? "—"} ~ ${rec.end ?? "—"}`);
  if (typeof rec.symbol_count === "number" && rec.symbol_count > 0) {
    bits.push(`symbols ${rec.symbol_count}`);
  }
  return bits.join(" · ");
}


function overviewKey(market: string, interval: string | null | undefined, dataKind: string) {
  return `${market}::${interval ?? ""}::${dataKind}`;
}


export function DataPage() {
  const [activeTab, setActiveTab] = useState<DomainTab>("cn_stock");
  const [browserBucketId, setBrowserBucketId] = useState<DataBrowserBucketId>("cn");

  return (
    <div className="data-center-layout">
      <aside className="data-center-sidebar">
        <div className="data-center-sidebar-header">
          <p className="eyebrow">Data center</p>
          <h2>数据中心</h2>
        </div>
        <nav className="data-center-nav" aria-label="Data center sections">
          {DOMAIN_TAB_ORDER.map((key) => (
            <button key={key} type="button" className={`data-center-nav-item ${activeTab === key ? "active" : ""}`} onClick={() => setActiveTab(key)}>
              {DOMAIN_LABELS[key]}
            </button>
          ))}
        </nav>
      </aside>
      <div className="data-center-main">
        {DOMAIN_CONFIGS.some((config) => config.key === activeTab) ? (
          <DomainPullView
            domain={DOMAIN_CONFIGS.find((config) => config.key === activeTab)!}
            onGoToBrowser={(market) => {
              setBrowserBucketId(preferredBrowserBucketFromMarket(market));
              setActiveTab("browser");
            }}
            onGoToTaskCenter={() => setActiveTab("jobs")}
          />
        ) : null}
        {activeTab === "browser" ? <DataBrowserView bucketId={browserBucketId} onBucketChange={setBrowserBucketId} /> : null}
        {activeTab === "jobs" ? <JobsCenterView /> : null}
      </div>
    </div>
  );
}


function DomainPullView({
  domain,
  onGoToTaskCenter,
  onGoToBrowser,
}: {
  domain: DomainConfig;
  onGoToTaskCenter: () => void;
  onGoToBrowser: (market: string) => void;
}) {
  return <DataPullPanel domain={domain} onGoToTaskCenter={onGoToTaskCenter} onGoToBrowser={onGoToBrowser} />;
}


function DataBrowserView({
  bucketId,
  onBucketChange,
}: {
  bucketId: DataBrowserBucketId;
  onBucketChange: (bucketId: DataBrowserBucketId) => void;
}) {
  const overviewQuery = useQuery({ queryKey: ["data-overview"], queryFn: () => listDataOverview() });

  const filteredOverview = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => DATA_BROWSER_BUCKETS.find((bucket) => bucket.id === bucketId)?.markets.includes(item.market)),
    [bucketId, overviewQuery.data],
  );

  const [selectedOverviewKey, setSelectedOverviewKey] = useState("");
  useEffect(() => {
    if (filteredOverview.length === 0) {
      setSelectedOverviewKey("");
      return;
    }
    if (!filteredOverview.some((item) => overviewKey(item.market, item.interval, item.data_kind) === selectedOverviewKey)) {
      const first = filteredOverview[0];
      setSelectedOverviewKey(overviewKey(first.market, first.interval, first.data_kind));
    }
  }, [filteredOverview, selectedOverviewKey]);

  const selectedOverview = useMemo(
    () => filteredOverview.find((item) => overviewKey(item.market, item.interval, item.data_kind) === selectedOverviewKey) ?? null,
    [filteredOverview, selectedOverviewKey],
  );

  const filesQuery = useQuery({
    queryKey: ["data-files", selectedOverview?.market, selectedOverview?.interval, selectedOverview?.data_kind],
    queryFn: () =>
      listDataFiles({
        market: selectedOverview?.market,
        interval: selectedOverview?.interval ?? undefined,
        data_kind: selectedOverview?.data_kind,
      }),
    enabled: Boolean(selectedOverview),
  });

  const [selectedFileId, setSelectedFileId] = useState("");
  useEffect(() => {
    const files = filesQuery.data ?? [];
    if (files.length === 0) {
      setSelectedFileId("");
      return;
    }
    if (!files.some((item) => item.file_id === selectedFileId)) {
      setSelectedFileId(files[0].file_id);
    }
  }, [filesQuery.data, selectedFileId]);

  const selectedFile = useMemo(
    () => (filesQuery.data ?? []).find((item) => item.file_id === selectedFileId) ?? null,
    [filesQuery.data, selectedFileId],
  );

  const previewQuery = useQuery({
    queryKey: ["data-preview", selectedFile?.file_id, selectedFile?.preferred_format],
    queryFn: () => getDataPreview({ file_id: selectedFile?.file_id, format: selectedFile?.preferred_format, limit: 20 }),
    enabled: Boolean(selectedFile?.file_id),
  });

  return (
    <section className="panel data-browser-root">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Browser</p>
          <h3>数据浏览</h3>
        </div>
      </div>
      <div className="data-browser-buckets">
        {DATA_BROWSER_BUCKETS.map((bucket) => (
          <button key={bucket.id} type="button" className={`data-browser-bucket ${bucket.id === bucketId ? "active" : ""}`} onClick={() => onBucketChange(bucket.id)}>
            {bucket.label}
          </button>
        ))}
      </div>

      <div className="data-browser-columns">
        <div className="data-browser-list">
          <h4>数据集</h4>
          <div className="list-stack">
            {filteredOverview.map((item) => {
              const key = overviewKey(item.market, item.interval, item.data_kind);
              return (
                <button key={key} type="button" className={`data-browser-overview-row ${key === selectedOverviewKey ? "active" : ""}`} onClick={() => setSelectedOverviewKey(key)}>
                  <strong>
                    {item.market} / {item.data_kind}
                    {item.interval ? ` / ${item.interval}` : ""}
                  </strong>
                  <span className="muted">
                    文件 {item.file_count} · symbols {item.symbol_count} · rows {item.row_count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="data-browser-list">
          <h4>文件列表</h4>
          <div className="list-stack">
            {(filesQuery.data ?? []).map((item) => (
              <button key={item.file_id} type="button" className={`data-browser-file-row ${item.file_id === selectedFileId ? "active" : ""}`} onClick={() => setSelectedFileId(item.file_id)}>
                <strong>{item.symbol_key ?? item.partition}</strong>
                <span className="muted">{item.file_path}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="data-browser-preview">
          <h4>预览</h4>
          {previewQuery.data ? (
            <>
              <p className="inline-note muted">
                {previewQuery.data.file_path} · {previewQuery.data.row_count ?? 0} rows
              </p>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {previewQuery.data.columns.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewQuery.data.rows.map((row, index) => (
                      <tr key={index}>
                        {previewQuery.data!.columns.map((column) => (
                          <td key={column}>{String(row[column] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">选择文件后可预览前 20 行。</p>
          )}
        </div>
      </div>
    </section>
  );
}


function JobsCenterView() {
  const jobsQuery = useQuery({
    queryKey: ["jobs", "center"],
    queryFn: () => listJobs({ limit: 100 }),
    refetchInterval: (query) => {
      const jobs = query.state.data;
      if (!jobs?.length) return false;
      return jobs.some((j) => j.status === "queued" || j.status === "running") ? 2500 : false;
    },
  });
  const retryMutation = useMutation({
    mutationFn: (jobId: string) => retryJob(jobId),
    onSuccess: () => void jobsQuery.refetch(),
  });
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => void jobsQuery.refetch(),
  });

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Jobs</p>
          <h3>任务中心</h3>
        </div>
      </div>
      <div className="list-stack">
        {jobsQuery.isLoading ? <p className="muted">加载任务列表…</p> : null}
        {!jobsQuery.isLoading && (jobsQuery.data ?? []).length === 0 ? <p className="muted">暂无任务（含「数据拉取」与「加密一键全量」）。</p> : null}
        {(jobsQuery.data ?? []).map((job) => (
          <div key={job.job_id} className="job-list-item">
            <div className="job-list-item-row">
              <div>
                <strong>{formatJobType(job.job_type)}</strong>
                <div className="muted">{formatJobSummary(job)}</div>
              </div>
              <StatusPill status={job.status} />
            </div>
            <div className="muted">
              {job.submitted_at}
              {job.duration_seconds != null ? ` · ${job.duration_seconds.toFixed(2)}s` : ""}
            </div>
            {job.error ? <div className="error-text">{job.error}</div> : null}
            <div className="button-row">
              <button type="button" className="ghost-button" onClick={() => retryMutation.mutate(job.job_id)}>
                重试
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => cancelMutation.mutate(job.job_id)}
                disabled={!["queued", "running"].includes(job.status)}
              >
                取消
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
