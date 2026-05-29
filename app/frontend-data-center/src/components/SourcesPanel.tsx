// 数据平台 v2 · 数据源开关树（市场级 + 源级两层）。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listSources,
  setMarketSourcesEnabled,
  setSourceEnabled,
  type MarketSourcesNode,
  type SourceNode,
} from "../dataPlatform";

export function SourcesPanel() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["data-sources"], queryFn: listSources });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["data-sources"] });
  const toggleSource = useMutation({
    mutationFn: (v: { name: string; market: string; enabled: boolean }) => setSourceEnabled(v.name, v.market, v.enabled),
    onSuccess: invalidate,
  });
  const toggleMarket = useMutation({
    mutationFn: (v: { market: string; enabled: boolean; kind?: string }) => setMarketSourcesEnabled(v.market, v.enabled, v.kind),
    onSuccess: invalidate,
  });

  if (isLoading) return <p style={{ padding: 16 }}>加载中…</p>;
  if (error) return <p style={{ padding: 16, color: "crimson" }}>加载失败：{(error as Error).message}</p>;

  const tree: MarketSourcesNode[] = data ?? [];

  return (
    <section style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 4px" }}>数据源开关</h3>
      <p style={{ color: "#666", fontSize: 13, margin: "0 0 16px" }}>
        关掉某市场的官方源 → 量化流程的可用字段宇宙就不再包含它；用户自带源不受影响。这就是"DIY 是否使用官方数据"。
      </p>
      {tree.length === 0 ? (
        <p style={{ color: "#888" }}>暂无已登记数据源——先在「数据拉取」拉一些数据，或接入用户源后刷新本页。</p>
      ) : null}
      {tree.map((node) => (
        <div key={node.market} style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>{node.market || "（未分类）"}</strong>
            <span style={{ display: "flex", gap: 8 }}>
              <button type="button" disabled={!node.market} onClick={() => toggleMarket.mutate({ market: node.market, enabled: true, kind: "official" })}>
                启用全部官方
              </button>
              <button type="button" disabled={!node.market} onClick={() => toggleMarket.mutate({ market: node.market, enabled: false, kind: "official" })}>
                屏蔽全部官方
              </button>
            </span>
          </div>
          <table style={{ width: "100%", marginTop: 8, fontSize: 13, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "#888", textAlign: "left" }}>
                <th>源</th>
                <th>类型</th>
                <th>状态</th>
                <th style={{ textAlign: "right" }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {node.sources.map((s: SourceNode) => (
                <tr key={`${s.name}@${s.market}`} style={{ borderTop: "1px solid #f2f2f2" }}>
                  <td>{s.label || s.name}</td>
                  <td>{s.kind === "user" ? "用户自带" : "官方"}</td>
                  <td>{s.enabled ? "✅ 启用" : "🚫 屏蔽"}</td>
                  <td style={{ textAlign: "right" }}>
                    <button type="button" onClick={() => toggleSource.mutate({ name: s.name, market: s.market, enabled: !s.enabled })}>
                      {s.enabled ? "屏蔽" : "启用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}
