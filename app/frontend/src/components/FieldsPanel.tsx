// 数据平台 v2 · 字段查看器 + 字段映射向导。
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  applyFieldMapping,
  inferFieldMapping,
  listFields,
  type FieldEntry,
  type MappingItem,
} from "../dataPlatform";

const MARKETS = [
  { value: "stocks_cn", label: "A股" },
  { value: "binanceusdm", label: "加密 · USDM 永续" },
  { value: "binance_spot", label: "加密 · 现货" },
];

const slug = (s: string) => s.replace(/[^0-9A-Za-z_]+/g, "_").replace(/^_+|_+$/g, "") || "x";
const parseColumns = (text: string) => [...new Set(text.split(/[\s,]+/).map((c) => c.trim()).filter(Boolean))];

function FieldTable({ title, rows }: { title: string; rows: FieldEntry[] }) {
  return (
    <div style={{ flex: 1, minWidth: 280 }}>
      <h4 style={{ margin: "0 0 6px" }}>
        {title} <span style={{ color: "#999", fontWeight: 400 }}>({rows.length})</span>
      </h4>
      <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ color: "#888", textAlign: "left" }}>
            <th>字段</th>
            <th>来源</th>
            <th>原始列</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.field_id} style={{ borderTop: "1px solid #f2f2f2" }}>
              <td><code>{f.field_id}</code></td>
              <td>{f.source}</td>
              <td>{f.raw_column}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FieldsPanel() {
  const [market, setMarket] = useState("stocks_cn");
  const { data, isLoading, error } = useQuery({ queryKey: ["fields", market], queryFn: () => listFields(market) });

  // 字段映射向导
  const [source, setSource] = useState("user_myapi");
  const [dataKind, setDataKind] = useState("ohlcv");
  const [colsText, setColsText] = useState("");
  const [rows, setRows] = useState<MappingItem[]>([]);
  const [applied, setApplied] = useState<number | null>(null);

  const infer = useMutation({
    mutationFn: () => inferFieldMapping(parseColumns(colsText), market, dataKind),
    onSuccess: (r) => {
      setApplied(null);
      setRows(
        r.suggestions.map((s) => ({
          raw_column: s.raw_column,
          // freeform 默认 id 用合法标识符 {source}__{col}（后端要求标识符，点号会被 422 拒）
          field_id: s.suggested_field_id ?? `${slug(source)}__${slug(s.raw_column)}`,
          is_freeform: s.is_freeform,
        })),
      );
    },
  });
  const apply = useMutation({
    mutationFn: () => applyFieldMapping(source, dataKind, rows.filter((r) => r.raw_column && r.field_id)),
    onSuccess: (r) => setApplied(r.applied),
  });

  return (
    <section style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>可用字段宇宙</h3>
        <select value={market} onChange={(e) => setMarket(e.target.value)}>
          {MARKETS.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
        <span style={{ color: "#666", fontSize: 13 }}>随启用的数据源动态变化（canonical 可跨源移植，freeform 带源命名空间）。</span>
      </div>

      {isLoading ? <p>加载中…</p> : null}
      {error ? <p style={{ color: "crimson" }}>加载失败：{(error as Error).message}</p> : null}
      {data ? (
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          <FieldTable title="规范字段 canonical" rows={data.canonical} />
          <FieldTable title="自由字段 freeform" rows={data.freeform} />
        </div>
      ) : null}

      <hr style={{ margin: "20px 0", border: "none", borderTop: "1px solid #eee" }} />

      <h3 style={{ margin: "0 0 4px" }}>字段映射向导</h3>
      <p style={{ color: "#666", fontSize: 13, margin: "0 0 12px" }}>
        把用户源的原始列名对齐到 canonical（系统给出候选映射，人工确认后写入）。粘贴列名，点「推断」，调整后「应用」。
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <label>源名 <input value={source} onChange={(e) => setSource(e.target.value)} style={{ width: 160 }} /></label>
        <label>数据类型 <input value={dataKind} onChange={(e) => setDataKind(e.target.value)} style={{ width: 120 }} /></label>
        <button type="button" disabled={infer.isPending || !colsText.trim()} onClick={() => infer.mutate()}>
          {infer.isPending ? "推断中…" : "推断映射"}
        </button>
      </div>
      <textarea
        value={colsText}
        onChange={(e) => setColsText(e.target.value)}
        placeholder="原始列名，逗号或空格分隔，如：t, px, qty, oi"
        rows={2}
        style={{ width: "100%", marginBottom: 8 }}
      />
      {infer.error ? <p style={{ color: "crimson" }}>{(infer.error as Error).message}</p> : null}
      {rows.length > 0 ? (
        <>
          <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse", marginBottom: 8 }}>
            <thead>
              <tr style={{ color: "#888", textAlign: "left" }}>
                <th>原始列</th>
                <th>→ 对齐到字段</th>
                <th>freeform?</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.raw_column}#${i}`} style={{ borderTop: "1px solid #f2f2f2" }}>
                  <td>{r.raw_column}</td>
                  <td>
                    <input
                      value={r.field_id}
                      onChange={(e) => {
                        const next = [...rows];
                        next[i] = { ...next[i], field_id: e.target.value };
                        setRows(next);
                      }}
                      style={{ width: "90%" }}
                    />
                  </td>
                  <td>{r.is_freeform ? "是" : "否"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" disabled={apply.isPending} onClick={() => apply.mutate()}>
            {apply.isPending ? "应用中…" : "应用映射"}
          </button>
          {applied !== null ? <span style={{ color: "green", marginLeft: 8 }}>已写入 {applied} 条映射 ✅</span> : null}
        </>
      ) : null}
    </section>
  );
}
