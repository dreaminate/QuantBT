import type { DataKindOption, DataPullRequest } from "../types";

export const MARKET_LABELS: Record<string, string> = {
  stocks_cn: "A-share (stocks_cn)",
  stocks_hk: "HK stocks (stocks_hk)",
  stocks_us: "US stocks (stocks_us)",
  binanceusdm: "Crypto (binanceusdm)",
  indices_cn: "CN indices (indices_cn)",
  funds_cn: "CN funds (funds_cn)",
  bonds_cn: "CN bonds (bonds_cn)",
};

export function formatMarketLabel(code: string): string {
  return MARKET_LABELS[code] ?? code;
}

export function formatDataKindLabel(kind: DataKindOption): string {
  const n = kind.stats_count ?? 0;
  return `${kind.data_kind} (${n})`;
}

export const SYMBOL_SOURCE_OPTIONS = [
  { value: "pool" as const, label: "Use symbol pool" },
  { value: "manual" as const, label: "Manual input" },
  { value: "all" as const, label: "All symbols" },
];

export const REFRESH_MODE_OPTIONS = [
  { value: "incremental" as const, label: "Incremental" },
  { value: "full" as const, label: "Full Refresh" },
];

/** Comma / newline / space separated; trim, dedupe, uppercase (aligned with backend). */
export function parseSymbolsInput(text: string): string[] {
  const parts = text
    .split(/[\s,，\n\r]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => s.toUpperCase());
  return [...new Set(parts)];
}

export type SymbolSource = "pool" | "manual" | "all";

export function buildDataPullPayload(options: {
  market: string;
  dataKind: string;
  symbolSource: SymbolSource;
  poolId: string;
  symbolsInput: string;
  fullHistory: boolean;
  start: string;
  end: string;
  refreshMode: "incremental" | "full";
  binanceInterval: string;
  selectedKind: DataKindOption | null;
}): DataPullRequest {
  const {
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
  } = options;

  const base: DataPullRequest = {
    market,
    data_kind: dataKind,
    symbol_source: symbolSource,
    symbols: [],
    full_history: fullHistory,
    refresh_mode: refreshMode,
    progress_mode: "detailed",
  };

  if (!fullHistory) {
    base.start = start || undefined;
    base.end = end || undefined;
  }

  if (symbolSource === "pool") {
    base.pool_id = poolId;
    base.symbols = [];
  } else if (symbolSource === "manual") {
    base.symbols = selectedKind?.supports_symbols ? parseSymbolsInput(symbolsInput) : [];
  } else {
    base.symbols = [];
  }

  if (
    market === "binanceusdm" &&
    [
      "klines",
      "vision_klines",
      "vision_mark_price_klines",
      "vision_index_price_klines",
      "vision_premium_index_klines",
      "open_interest_hist",
      "taker_buy_sell_volume",
    ].includes(dataKind)
  ) {
    base.interval = binanceInterval;
  }

  return base;
}

export function validateClientPullForm(options: {
  symbolSource: SymbolSource;
  poolId: string;
  poolsLength: number;
  symbolsParsed: string[];
  supportsSymbols: boolean;
  fullHistory: boolean;
  supportsDateRange: boolean;
  start: string;
  end: string;
}): string | null {
  const { symbolSource, poolId, poolsLength, symbolsParsed, supportsSymbols, fullHistory, supportsDateRange, start, end } = options;
  if (symbolSource === "pool") {
    if (poolsLength === 0) return "No symbol pool available for this market. Create one under Pools in the sidebar first.";
    if (!poolId.trim()) return "Please choose a pool.";
  }
  if (symbolSource === "manual" && supportsSymbols && symbolsParsed.length === 0) {
    return "Enter at least one symbol.";
  }
  if (!fullHistory && supportsDateRange) {
    if (!start || !end) return "Start and End are required.";
    if (start > end) return "Start must be on or before End.";
  }
  return null;
}
