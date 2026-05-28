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
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">
            <span className="cc-prompt">$</span>experiments ({experiments.length})
          </h1>
          <p className="cc-page-subtitle">
            嵌入式 lineage · Model stage 提升 (dev → staging → production → archived)
          </p>
        </div>
      </div>

      {err && <div className="cc-chip cc-chip--danger">{err}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16 }}>
        <aside className="cc-card" style={{ padding: 12, minHeight: 400 }}>
          <div className="cc-section-title" style={{ marginBottom: 8 }}>
            experiments
          </div>
          {experiments.length === 0 ? (
            <div className="cc-dim" style={{ fontSize: 12 }}>
              暂无实验。Agent 跑回测会自动建。
            </div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {experiments.map((e) => (
                <li key={e.experiment_id} style={{ marginBottom: 4 }}>
                  <button
                    type="button"
                    onClick={() => setSelectedExp(e.experiment_id)}
                    className={`cc-btn cc-btn--ghost cc-btn--sm`}
                    style={{
                      width: "100%",
                      justifyContent: "flex-start",
                      background:
                        selectedExp === e.experiment_id ? "var(--cc-accent-soft)" : "transparent",
                      color: selectedExp === e.experiment_id ? "var(--cc-accent)" : undefined,
                    }}
                  >
                    <span style={{ flex: 1, textAlign: "left" }}>{e.name}</span>
                    <span className="cc-dim" style={{ fontSize: 10 }}>
                      {e.asset_class}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section>
          <div className="cc-section-title" style={{ marginBottom: 12 }}>
            {selectedExp ? `runs of ${selectedExp}` : "← 选一个 experiment"}
          </div>
          {selectedExp && (
            <table className="cc-table">
              <thead>
                <tr>
                  <th>run_id</th>
                  <th>status</th>
                  <th style={{ textAlign: "right" }}>sharpe</th>
                  <th style={{ textAlign: "right" }}>pbo</th>
                  <th style={{ textAlign: "right" }}>dsr</th>
                  <th>started</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="cc-dim">
                      no runs
                    </td>
                  </tr>
                ) : (
                  runs.map((r) => (
                    <tr key={r.run_id}>
                      <td className="cc-mono" style={{ fontSize: 11 }}>
                        {r.run_id}
                      </td>
                      <td>
                        <span
                          className={`cc-chip ${
                            r.status === "succeeded"
                              ? "cc-chip--success"
                              : r.status === "failed"
                                ? "cc-chip--danger"
                                : ""
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {r.metrics?.sharpe?.toFixed(3) ?? "—"}
                      </td>
                      <td style={{ textAlign: "right" }}>{r.metrics?.pbo?.toFixed(3) ?? "—"}</td>
                      <td style={{ textAlign: "right" }}>
                        {r.metrics?.deflated_sharpe?.toFixed(3) ?? "—"}
                      </td>
                      <td className="cc-dim" style={{ fontSize: 11 }}>
                        {r.started_at_utc.slice(0, 19)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  );
}

export default ExperimentTrackingPage;
