// 数据平台 v2 · 数据源开关 + 字段目录 + 字段映射向导 的类型与 API client。

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try {
      const d: unknown = await res.json();
      if (d && typeof d === "object" && "detail" in d) {
        msg = String((d as Record<string, unknown>).detail);
      }
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type FieldEntry = {
  field_id: string;
  source: string;
  dataset_id: string;
  raw_column: string;
};

export type FieldUniverse = {
  canonical: FieldEntry[];
  freeform: FieldEntry[];
};

export type InferSuggestion = {
  raw_column: string;
  suggested_field_id: string | null;
  is_freeform: boolean;
  confidence: number;
  reason: string;
};

export type InferReport = {
  suggestions: InferSuggestion[];
  canonical_options: string[];
};

export function listFields(market: string, interval?: string, enabledOnly = true): Promise<FieldUniverse> {
  const q = new URLSearchParams({ market, enabled_only: String(enabledOnly) });
  if (interval) q.set("interval", interval);
  return fetchJson<FieldUniverse>(`/api/fields?${q.toString()}`);
}

export function inferFieldMapping(columns: string[], market?: string, dataKind = "ohlcv"): Promise<InferReport> {
  return fetchJson<InferReport>("/api/fields/infer-mapping", {
    method: "POST",
    body: JSON.stringify({ columns, market: market ?? null, data_kind: dataKind }),
  });
}

export type MappingItem = { raw_column: string; field_id: string; is_freeform?: boolean };

export function applyFieldMapping(source: string, dataKind: string, mappings: MappingItem[]): Promise<{ applied: number }> {
  return fetchJson<{ applied: number }>("/api/fields/mapping", {
    method: "POST",
    body: JSON.stringify({ source, data_kind: dataKind, mappings }),
  });
}
