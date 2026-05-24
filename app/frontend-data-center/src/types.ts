export type DataMarket = {
  market: string;
  label: string;
};

export type DataOverviewItem = {
  market: string;
  interval?: string | null;
  data_kind: string;
  file_count: number;
  symbol_count: number;
  row_count: number;
  start?: string | null;
  end?: string | null;
  updated_at?: string | null;
  formats: string[];
};

export type DataFileItem = {
  file_id: string;
  market: string;
  interval?: string | null;
  data_kind: string;
  symbol_key?: string | null;
  partition: string;
  formats: string[];
  preferred_format: string;
  file_path: string;
  row_count?: number | null;
  start?: string | null;
  end?: string | null;
  updated_at?: string | null;
};

export type DataPreviewResponse = {
  file_id: string;
  market: string;
  interval?: string | null;
  data_kind: string;
  symbol_key?: string | null;
  partition: string;
  format: string;
  file_path: string;
  row_count?: number | null;
  start?: string | null;
  end?: string | null;
  available_formats: string[];
  columns: string[];
  rows: Array<Record<string, string | number | boolean | null>>;
};

export type DataKindOption = {
  market: string;
  data_kind: string;
  api_name: string;
  label: string;
  required_points: number;
  effective_points_ceiling?: number | null;
  supports_symbols: boolean;
  supports_date_range: boolean;
  independent_permission: boolean;
  stats_count?: number;
  needs_binance_interval?: boolean;
};

export type SymbolPoolItem = {
  pool_id: string;
  name: string;
  market: string | null;
  symbol_count: number;
};

/** POST /api/jobs/data/pull-binance-full — 可选，未传字段用后端默认 */
export type BinanceFullPullRequest = {
  vision_start?: string;
  vision_end?: string | null;
  default_interval?: string;
};

export type DataPullRequest = {
  market: string;
  data_kind: string;
  symbol_mode?: "manual" | "all" | "stock_pool" | "preset";
  symbol_source?: "pool" | "manual" | "all";
  symbols: string[];
  stock_pool_id?: string;
  pool_id?: string;
  preset_name?: string;
  start?: string;
  end?: string;
  full_history?: boolean;
  refresh_mode?: "incremental" | "full";
  interval?: string;
  progress_mode?: "basic" | "detailed";
};

export type JobProgressDetailItem = {
  label: string;
  status: "pending" | "active" | "completed" | "failed";
  message?: string | null;
};

export type JobProgress = {
  percent: number;
  stage: string;
  stage_label: string;
  message?: string | null;
  mode: "basic" | "detailed";
  stats: Record<string, unknown>;
  detail_items: JobProgressDetailItem[];
};

export type JobPayloadSummary = {
  kind?: string;
  market?: string;
  data_kind?: string;
  symbol_mode?: string;
  symbol_count?: number;
  start?: string | null;
  end?: string | null;
  full_history?: boolean;
  interval?: string | null;
};

export type JobResponse = {
  job_id: string;
  job_type: string;
  status: string;
  payload: Record<string, unknown>;
  submitted_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  progress?: JobProgress | null;
  error?: string | null;
  result?: Record<string, unknown> | null;
  run_id?: string | null;
  duration_seconds?: number | null;
  payload_summary?: JobPayloadSummary | null;
};

export type ArtifactStat = {
  artifact_name: string;
  available: boolean;
  file_path?: string | null;
  file_size_bytes?: number | null;
  row_count?: number | null;
};

export type RunDataDependency = {
  source_type: string;
  label?: string | null;
  dataset_name?: string | null;
  version?: string | null;
  market?: string | null;
  data_kind?: string | null;
  interval?: string | null;
  symbol?: string | null;
  output_name?: string | null;
  producer_id?: string | null;
  file_path?: string | null;
  file_format?: string | null;
  row_count?: number | null;
  start?: string | null;
  end?: string | null;
  details: Record<string, unknown>;
};

export type RunNamedOutput = {
  producer_scope?: string;
  producer_id?: string;
  producer_name?: string | null;
  component_run_id?: string | null;
  output_name: string;
  output_type?: string;
  dataset_name?: string | null;
  version_id?: string | null;
  artifact_path?: string;
  file_path?: string | null;
  row_count?: number | null;
  start?: string | null;
  end?: string | null;
  consumed_by?: string[];
  summary?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type RunDetail = {
  run_id: string;
  strategy_name: string;
  strategy_id: string;
  started_at: string;
  status: string;
  record_name?: string | null;
  strategy_mode?: string | null;
  strategy_ref?: string | null;
  strategy_script_path?: string | null;
  strategy_script_name?: string | null;
  artifact_dir: string;
  metrics: Record<string, any>;
  report_markdown: string;
  config_snapshot?: Record<string, any> | null;
  artifacts: Record<string, string>;
  artifact_stats: Record<string, ArtifactStat>;
  data_dependencies: RunDataDependency[];
  produced_outputs: RunNamedOutput[];
  component_runs: Array<Record<string, any>>;
  series_available: Record<string, boolean>;
  oos_periods: number;
  market?: string | null;
  frequency?: string | null;
  benchmark?: string | null;
  model_used: boolean;
  tearsheet_available: boolean;
  data_coverage_summary: Record<string, unknown>;
  returns?: number | null;
  turnover?: number | null;
  margin?: number | null;
  pnl?: number | null;
  drawdown?: number | null;
  fitness?: number | null;
  sharpe?: number | null;
  book_size?: number | null;
  long_count?: number | null;
  short_count?: number | null;
  annualized_return?: number | null;
  alpha?: number | null;
  beta?: number | null;
  win_rate?: number | null;
  sortino?: number | null;
  information_ratio?: number | null;
  volatility?: number | null;
  benchmark_volatility?: number | null;
  profit_loss_ratio?: number | null;
  avg_daily_return?: number | null;
  daily_win_rate?: number | null;
  trade_count?: number | null;
  analysis_start?: string | null;
  analysis_end?: string | null;
  duration_seconds?: number | null;
};

export type RunAttributionResponse = {
  run_id: string;
  available: boolean;
  method: string;
  benchmark?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  summary: Record<string, unknown>;
  rows: Array<Record<string, unknown>>;
  message?: string | null;
};

export type RunSummary = {
  run_id: string;
  strategy_name: string;
  status: string;
  started_at: string;
  record_name?: string | null;
};

export type SeriesName =
  | "equity"
  | "drawdown"
  | "turnover"
  | "net_return"
  | "gross_return"
  | "funding_return"
  | "fee_cost"
  | "strategy_return"
  | "benchmark_return"
  | "alpha"
  | "beta"
  | "sharpe"
  | "sortino"
  | "information_ratio"
  | "volatility"
  | "benchmark_volatility"
  | "max_drawdown"
  | "daily_buy"
  | "daily_sell";

export type SeriesSegment = "overall";

export type RunSeriesPoint = {
  timestamp?: string | null;
  value?: number | null;
};

export type RunSeriesResponse = {
  run_id: string;
  series: SeriesName | string;
  segment: SeriesSegment | string;
  available: boolean;
  points: RunSeriesPoint[];
};

export type RunLogEntry = {
  timestamp: string;
  level: string;
  message: string;
};

export type RunLogResponse = {
  entries: RunLogEntry[];
  total: number;
};

export type TableName = "portfolio" | "trades" | "positions";
export type TableOrder = "asc" | "desc";

export type RunTableColumn = {
  key: string;
  label: string;
  dtype: "datetime" | "number" | "string";
};

export type RunTableResponse = {
  table_name: string;
  available: boolean;
  columns: RunTableColumn[];
  rows: Array<Record<string, any>>;
  total_rows: number;
};

export type StrategySourceResponse = {
  file_name: string;
  content: string;
};
