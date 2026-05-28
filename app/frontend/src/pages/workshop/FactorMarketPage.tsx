import { useEffect, useState } from "react";

interface FactorItem {
  factor_id: string;
  version: number;
  formula: string;
  lifecycle_state: string;
  description?: string;
  ic_summary?: { ic_mean?: number; rank_ic_mean?: number } | null;
}

const ORDER = ["QUALIFIED", "PROBATION", "OBSERVATION", "WARNING", "NEW", "RETIRED"];

export function FactorMarketPage() {
  const [items, setItems] = useState<FactorItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "table">("grid");

  useEffect(() => {
    fetch("/api/factors")
      .then((r) => r.json())
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  const filtered = q.trim()
    ? items.filter(
        (f) =>
          f.factor_id.toLowerCase().includes(q.toLowerCase()) ||
          f.formula.toLowerCase().includes(q.toLowerCase()) ||
          (f.description || "").toLowerCase().includes(q.toLowerCase()),
      )
    : items;

  const grouped: Record<string, FactorItem[]> = {};
  filtered.forEach((f) => {
    (grouped[f.lifecycle_state] ||= []).push(f);
  });

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">
            <span className="cc-prompt">$</span>factors ({items.length})
          </h1>
          <p className="cc-page-subtitle">
            44 个白箱算子 · AST 表达式引擎 · IC/Rank-IC/IC-IR/IC 衰减 · 五态机自动迁移。
          </p>
        </div>
        <div className="cc-row">
          <input
            className="cc-input"
            placeholder="搜 factor_id / formula / desc"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 280 }}
          />
          <div className="cc-tabs" style={{ borderBottom: 0, margin: 0 }}>
            <button
              type="button"
              className={`cc-tab${viewMode === "grid" ? " active" : ""}`}
              onClick={() => setViewMode("grid")}
            >
              卡片
            </button>
            <button
              type="button"
              className={`cc-tab${viewMode === "table" ? " active" : ""}`}
              onClick={() => setViewMode("table")}
            >
              表格
            </button>
          </div>
        </div>
      </div>

      {err && <div className="cc-chip cc-chip--danger">{err}</div>}

      {viewMode === "grid"
        ? ORDER.filter((s) => grouped[s]?.length).map((state) => (
            <section key={state} className="cc-section">
              <div className="cc-section-header">
                <h2 className="cc-section-title">
                  <span className={`cc-lifecycle cc-lifecycle--${state}`}>{state}</span>
                  <span className="cc-soft" style={{ marginLeft: 8 }}>
                    {grouped[state].length}
                  </span>
                </h2>
              </div>
              <div className="cc-grid">
                {grouped[state].map((f) => (
                  <FactorCard key={`${f.factor_id}-${f.version}`} f={f} />
                ))}
              </div>
            </section>
          ))
        : (
          <table className="cc-table">
            <thead>
              <tr>
                <th>factor_id</th>
                <th>v</th>
                <th>formula</th>
                <th style={{ textAlign: "right" }}>IC</th>
                <th style={{ textAlign: "right" }}>RankIC</th>
                <th>lifecycle</th>
                <th>描述</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((f) => (
                <tr key={`${f.factor_id}-${f.version}`}>
                  <td className="cc-mono">{f.factor_id}</td>
                  <td className="cc-dim">v{f.version}</td>
                  <td className="cc-mono cc-soft" style={{ fontSize: 11 }}>
                    {f.formula}
                  </td>
                  <td style={{ textAlign: "right" }}>{f.ic_summary?.ic_mean?.toFixed(4) ?? "—"}</td>
                  <td style={{ textAlign: "right" }}>
                    {f.ic_summary?.rank_ic_mean?.toFixed(4) ?? "—"}
                  </td>
                  <td>
                    <span className={`cc-lifecycle cc-lifecycle--${f.lifecycle_state}`}>
                      {f.lifecycle_state}
                    </span>
                  </td>
                  <td className="cc-dim">{f.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </>
  );
}

function FactorCard({ f }: { f: FactorItem }) {
  return (
    <div className="cc-card">
      <div className="cc-row" style={{ justifyContent: "space-between" }}>
        <div className="cc-card-title">{f.factor_id}</div>
        <span className={`cc-lifecycle cc-lifecycle--${f.lifecycle_state}`}>
          {f.lifecycle_state}
        </span>
      </div>
      <div className="cc-dim" style={{ fontSize: 11, marginBottom: 8 }}>
        v{f.version} · {f.description || "—"}
      </div>
      <pre className="cc-code" style={{ fontSize: 11, marginBottom: 8 }}>
        {f.formula}
      </pre>
      <div className="cc-row" style={{ gap: 6 }}>
        {f.ic_summary?.ic_mean != null && (
          <span className="cc-chip">IC {f.ic_summary.ic_mean.toFixed(3)}</span>
        )}
        {f.ic_summary?.rank_ic_mean != null && (
          <span className="cc-chip">RankIC {f.ic_summary.rank_ic_mean.toFixed(3)}</span>
        )}
      </div>
    </div>
  );
}

export default FactorMarketPage;
