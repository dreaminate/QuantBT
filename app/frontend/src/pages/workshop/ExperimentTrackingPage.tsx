import { useEffect, useState } from "react";

interface ExperimentItem {
  experiment_id: string;
  name: string;
  asset_class: string;
  created_at_utc: string;
}

interface RunItem {
  run_id: string;
  experiment_id: string;
  status: string;
  started_at_utc: string;
  finished_at_utc?: string | null;
  metrics?: Record<string, number>;
}

export function ExperimentTrackingPage() {
  const [experiments, setExperiments] = useState<ExperimentItem[]>([]);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [selectedExp, setSelectedExp] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/experiments")
      .then((r) => r.json())
      .then(setExperiments)
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedExp) {
      setRuns([]);
      return;
    }
    fetch(`/api/experiments/${selectedExp}/runs`)
      .then((r) => r.json())
      .then(setRuns)
      .catch((e) => setErr(String(e)));
  }, [selectedExp]);

  return (
    <div style={{ padding: 16, display: "grid", gridTemplateColumns: "1fr 2fr", gap: 16 }}>
      <section>
        <h3>实验 ({experiments.length})</h3>
        {err && <pre style={{ color: "crimson" }}>{err}</pre>}
        {experiments.length === 0 ? (
          <p style={{ color: "#666" }}>暂无实验。Agent 跑回测会自动建实验。</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0 }}>
            {experiments.map((e) => (
              <li
                key={e.experiment_id}
                style={{
                  padding: 8,
                  borderBottom: "1px solid #eee",
                  cursor: "pointer",
                  background: selectedExp === e.experiment_id ? "#eef" : "transparent",
                }}
                onClick={() => setSelectedExp(e.experiment_id)}
              >
                <div><strong>{e.name}</strong></div>
                <div style={{ fontSize: 12, color: "#666" }}>
                  {e.asset_class} · {e.created_at_utc.slice(0, 19)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3>{selectedExp ? `Runs of ${selectedExp}` : "选一个实验"}</h3>
        {runs.length === 0 ? (
          <p style={{ color: "#666" }}>无 run</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #ddd" }}>
                <th align="left">run_id</th>
                <th align="left">status</th>
                <th align="right">sharpe</th>
                <th align="right">pbo</th>
                <th align="right">dsr</th>
                <th align="left">started</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{r.run_id}</td>
                  <td>{r.status}</td>
                  <td align="right">{r.metrics?.sharpe?.toFixed(3) ?? "—"}</td>
                  <td align="right">{r.metrics?.pbo?.toFixed(3) ?? "—"}</td>
                  <td align="right">{r.metrics?.deflated_sharpe?.toFixed(3) ?? "—"}</td>
                  <td style={{ fontSize: 12, color: "#666" }}>{r.started_at_utc.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default ExperimentTrackingPage;
