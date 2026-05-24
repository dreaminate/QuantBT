import type {
  DataFileItem,
  DataKindOption,
  DataMarket,
  DataOverviewItem,
  DataPreviewResponse,
  BinanceFullPullRequest,
  DataPullRequest,
  SymbolPoolItem,
  JobResponse,
  RunAttributionResponse,
  RunCompareResponse,
  RunCompareSeriesResponse,
  RunDetail,
  RunLogResponse,
  RunQueryRequest,
  RunQueryResponse,
  RunSeriesResponse,
  RunSummary,
  RunTableResponse,
  SeriesName,
  SeriesSegment,
  StrategySourceResponse,
  TableName,
  TableOrder,
} from "./types";


async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const detail = contentType.includes("application/json") ? await response.json() : await response.text();
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null && "detail" in detail
          ? String((detail as { detail: unknown }).detail)
          : `Request failed with status ${response.status}`;
    throw new Error(message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}


export function listMarkets() {
  return apiFetch<DataMarket[]>("/api/data/markets");
}


export function listDataOverview() {
  return apiFetch<DataOverviewItem[]>("/api/data/overview");
}


export function listDataFiles(params: {
  market?: string;
  interval?: string;
  data_kind?: string;
} = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<DataFileItem[]>(`/api/data/files${suffix}`);
}


export function listDataKinds(params: { market?: string } = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<DataKindOption[]>(`/api/data/kinds${suffix}`);
}


export function listSymbolPools(params: { market?: string } = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<SymbolPoolItem[]>(`/api/data/pools${suffix}`);
}


export function getDataPreview(params: {
  file_id?: string;
  market?: string;
  interval?: string;
  symbol?: string;
  data_kind?: string;
  format?: string;
  limit?: number;
}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  return apiFetch<DataPreviewResponse>(`/api/data/preview?${search.toString()}`);
}


export function createDataPullJob(payload: DataPullRequest) {
  return apiFetch<JobResponse>("/api/jobs/data/pull", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createBinanceFullPullJob(payload: BinanceFullPullRequest = {}) {
  return apiFetch<JobResponse>("/api/jobs/data/pull-binance-full", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listJobs(params: { limit?: number; status?: string; job_type?: string } = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<JobResponse[]>(`/api/jobs${suffix}`);
}


export function getJob(jobId: string) {
  return apiFetch<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}`);
}


export function retryJob(jobId: string) {
  return apiFetch<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
}


export function cancelJob(jobId: string) {
  return apiFetch<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}


export function listRuns() {
  return apiFetch<RunSummary[]>("/api/runs");
}


export function queryRuns(payload: RunQueryRequest) {
  return apiFetch<RunQueryResponse>("/api/runs/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}


export type DeleteRunResponse = { deleted: string };

export function deleteRun(runId: string) {
  return apiFetch<DeleteRunResponse>(`/api/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}


export type RealtimeWsEvent = { type: string; payload?: Record<string, unknown> };

/** quant1 同款签名；qb 单机后端未实现 WS 时返回占位，避免控制台连接错误。 */
export function connectRunsSocket(): WebSocket {
  const stub: { close: () => void; onmessage: ((this: WebSocket, ev: MessageEvent) => void) | null } = {
    close: () => {},
    onmessage: null,
  };
  return stub as unknown as WebSocket;
}

export function decodeRealtimeEvent(event: MessageEvent<string>): RealtimeWsEvent | null {
  try {
    return JSON.parse(event.data) as RealtimeWsEvent;
  } catch {
    return null;
  }
}


export function compareRuns(runIds: string[]) {
  const search = new URLSearchParams();
  for (const runId of runIds) {
    search.append("run_ids", runId);
  }
  return apiFetch<RunCompareResponse>(`/api/runs/compare?${search.toString()}`);
}


export function getRun(runId: string) {
  return apiFetch<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`);
}


export function getRunSeries(runId: string, series: SeriesName, segment: SeriesSegment) {
  const search = new URLSearchParams({ series, segment });
  return apiFetch<RunSeriesResponse>(`/api/runs/${encodeURIComponent(runId)}/series?${search.toString()}`);
}


export function getCompareSeries(runIds: string[], series: SeriesName, segment: SeriesSegment) {
  const search = new URLSearchParams({ series, segment });
  for (const runId of runIds) {
    search.append("run_ids", runId);
  }
  return apiFetch<RunCompareSeriesResponse>(`/api/runs/compare/series?${search.toString()}`);
}


export function getRunLogs(runId: string, params: { limit?: number; offset?: number } = {}) {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<RunLogResponse>(`/api/runs/${encodeURIComponent(runId)}/logs${suffix}`);
}


export function getRunAttribution(runId: string) {
  return apiFetch<RunAttributionResponse>(`/api/runs/${encodeURIComponent(runId)}/attribution`);
}


export function getRunSource(runId: string) {
  return apiFetch<StrategySourceResponse>(`/api/runs/${encodeURIComponent(runId)}/source`);
}


type RunTableOptions = {
  limit?: number;
  offset?: number;
  sort?: string;
  order?: TableOrder;
  start_ts?: string;
  end_ts?: string;
  symbol?: string;
  side?: string;
};


export function getRunTable(runId: string, tableName: TableName, options: RunTableOptions = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<RunTableResponse>(`/api/runs/${encodeURIComponent(runId)}/tables/${tableName}${suffix}`);
}


export function buildArtifactDownloadUrl(runId: string, artifactName: string) {
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactName)}/download`;
}


export function buildRunExportUrl(runId: string, exportType: "nav" | "positions" | "trades" | "metrics") {
  return `/api/runs/${encodeURIComponent(runId)}/export/${exportType}`;
}
