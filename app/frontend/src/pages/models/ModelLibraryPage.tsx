import { useEffect, useState } from "react";

/**
 * 模型中心 · 模型库
 * 已训练模型(本体)一览：复用 M12 ModelRegistry(/api/models)。
 * 每个模型可展开看版本/stage/指标/来源 run（血缘）。本体可被训练台 predict_with 复用为输入。
 */

interface ModelVersion {
  model_id: string;
  version: number;
  stage: string;
  created_at_utc: string;
  metrics: Record<string, number>;
  artifact_path?: string | null;
  source_run_id?: string | null;
  note?: string;
}

const STAGE_COLOR: Record<string, string> = {
  dev: "var(--cc-text-dim)",
  staging: "var(--cc-warning)",
  production: "var(--cc-success)",
  archived: "var(--cc-text-muted)",
};

export function ModelLibraryPage() {
  const [models, setModels] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, ModelVersion[]>>({});

  useEffect(() => {
    fetch("/api/models").then((r) => r.json()).then(setModels).catch(() => {});
  }, []);

  const toggle = (id: string) => {
    if (open === id) {
      setOpen(null);
      return;
    }
    setOpen(id);
    if (!versions[id]) {
      fetch(`/api/models/${encodeURIComponent(id)}/versions`)
        .then((r) => r.json())
        .then((v) => setVersions((cur) => ({ ...cur, [id]: v })))
        .catch(() => {});
    }
  };

  return (
    <div>
      <div className="cc-page-header">
        <div>
          <p className="eyebrow">模型中心</p>
          <h1 className="cc-page-title">{"// 模型库"}</h1>
          <div className="cc-soft">训练好的模型本体（artifact + 版本 + stage + 血缘）。可在训练台被复用为新训练的输入特征。</div>
        </div>
      </div>

      {models.length === 0 ? (
        <div className="cc-card cc-dim" style={{ padding: 24 }}>还没有训练好的模型，去训练台跑一个。</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {models.map((id) => (
            <div key={id} className="cc-card" style={{ padding: 0, overflow: "hidden" }}>
              <button
                type="button"
                onClick={() => toggle(id)}
                className="cc-row"
                style={{ width: "100%", justifyContent: "space-between", padding: "12px 14px", background: "transparent", border: "none", cursor: "pointer", color: "inherit" }}
              >
                <span className="cc-mono" style={{ fontWeight: 600 }}>{id}</span>
                <span className="cc-soft" style={{ fontSize: 12 }}>{open === id ? "▾" : "▸"} 版本</span>
              </button>
              {open === id && (
                <table className="cc-table" style={{ width: "100%", fontSize: 12, borderTop: "1px solid var(--cc-border-soft)" }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "var(--cc-text-dim)" }}>
                      <th style={{ padding: "4px 14px" }}>v</th>
                      <th style={{ padding: "4px 8px" }}>stage</th>
                      <th style={{ padding: "4px 8px" }}>指标</th>
                      <th style={{ padding: "4px 8px" }}>来源 run</th>
                      <th style={{ padding: "4px 8px" }}>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(versions[id] ?? []).map((v) => (
                      <tr key={v.version} style={{ borderTop: "1px solid var(--cc-border-soft)" }}>
                        <td style={{ padding: "5px 14px" }} className="cc-mono">{v.version}</td>
                        <td style={{ padding: "5px 8px", color: STAGE_COLOR[v.stage] }}>{v.stage}</td>
                        <td style={{ padding: "5px 8px" }} className="cc-mono">
                          {Object.entries(v.metrics ?? {}).slice(0, 3).map(([k, x]) => `${k}=${Number(x).toFixed(3)}`).join("  ") || "—"}
                        </td>
                        <td style={{ padding: "5px 8px" }} className="cc-mono cc-soft">{v.source_run_id ?? "—"}</td>
                        <td style={{ padding: "5px 8px" }} className="cc-soft">{(v.created_at_utc ?? "").slice(0, 16).replace("T", " ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ModelLibraryPage;
