import { useEffect, useState } from "react";

interface FactorItem {
  factor_id: string;
  version: number;
  formula: string;
  lifecycle_state: string;
  description?: string;
  ic_summary?: { ic_mean?: number; rank_ic_mean?: number } | null;
}

export function FactorMarketPage() {
  const [items, setItems] = useState<FactorItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/factors")
      .then((r) => r.json())
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);
  const grouped = items.reduce<Record<string, FactorItem[]>>((acc, f) => {
    (acc[f.lifecycle_state] ||= []).push(f);
    return acc;
  }, {});
  const order = ["QUALIFIED", "PROBATION", "OBSERVATION", "WARNING", "NEW", "RETIRED"];
  return (
    <div style={{ padding: 16 }}>
      <h2>因子市场 ({items.length})</h2>
      {err && <pre style={{ color: "crimson" }}>{err}</pre>}
      {order
        .filter((k) => grouped[k]?.length)
        .map((state) => (
          <section key={state} style={{ marginBottom: 24 }}>
            <h3>
              {state} <span style={{ color: "#888", fontSize: 12 }}>({grouped[state].length})</span>
            </h3>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #ddd" }}>
                  <th align="left">factor_id</th>
                  <th align="left">v</th>
                  <th align="left">公式</th>
                  <th align="right">IC</th>
                  <th align="right">RankIC</th>
                  <th align="left">描述</th>
                </tr>
              </thead>
              <tbody>
                {grouped[state].map((f) => (
                  <tr key={`${f.factor_id}-${f.version}`} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ fontFamily: "monospace" }}>{f.factor_id}</td>
                    <td>v{f.version}</td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{f.formula}</td>
                    <td align="right">{f.ic_summary?.ic_mean?.toFixed(4) ?? "—"}</td>
                    <td align="right">{f.ic_summary?.rank_ic_mean?.toFixed(4) ?? "—"}</td>
                    <td style={{ color: "#666" }}>{f.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
    </div>
  );
}

export default FactorMarketPage;
