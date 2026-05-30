/**
 * 训练评价图（零依赖内联 SVG，复用回测详情页的深色风格）。
 * 后端 /api/training/jobs/{id}/eval 返回 charts[]，本组件按 kind 渲染。
 * 单图为主：bar(特征重要度/分fold) / line(学习曲线/ROC) / scatter(预测-实际/残差)。
 */

const PALETTE = ["#2f6fdd", "#d34f4f", "#7e5ab6", "#2e8b57", "#d68910", "#21618c"];
const GRID = "var(--cc-border, #333)";
const AXIS = "var(--cc-text-dim, #707070)";
const TEXT = "var(--cc-text-soft, #a0a0a0)";

export interface ChartData {
  id: string;
  title: string;
  kind: "bar" | "line" | "scatter";
  labels?: string[];
  values?: number[];
  x?: number[] | null;
  series?: { name: string; values: number[] }[];
  points?: number[][];
  ref_line?: boolean;
  x_label?: string;
  y_label?: string;
}

const W = 360;
const H = 200;
const PAD = { t: 12, r: 14, b: 28, l: 44 };

function scale(v: number, lo: number, hi: number, a: number, b: number): number {
  if (hi === lo) return (a + b) / 2;
  return a + ((v - lo) / (hi - lo)) * (b - a);
}

function BarChart({ c }: { c: ChartData }) {
  const labels = c.labels ?? [];
  const values = c.values ?? [];
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const bw = innerW / Math.max(values.length, 1);
  const zeroY = scale(0, min, max, PAD.t + innerH, PAD.t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      <line x1={PAD.l} y1={zeroY} x2={W - PAD.r} y2={zeroY} stroke={GRID} />
      {values.map((v, i) => {
        const x = PAD.l + i * bw + bw * 0.15;
        const y = scale(v, min, max, PAD.t + innerH, PAD.t);
        const h = Math.abs(y - zeroY);
        return (
          <g key={i}>
            <rect x={x} y={Math.min(y, zeroY)} width={bw * 0.7} height={Math.max(h, 0.5)} fill={PALETTE[0]} opacity={0.85} />
            {labels.length <= 12 && (
              <text x={x + bw * 0.35} y={H - PAD.b + 12} fill={AXIS} fontSize={8} textAnchor="middle">
                {labels[i]?.length > 8 ? labels[i].slice(0, 7) + "…" : labels[i]}
              </text>
            )}
          </g>
        );
      })}
      <text x={PAD.l} y={PAD.t - 2} fill={TEXT} fontSize={9}>{max.toFixed(3)}</text>
    </svg>
  );
}

function LineChart({ c }: { c: ChartData }) {
  const series = c.series ?? [];
  const allVals = series.flatMap((s) => s.values);
  if (allVals.length === 0) return null;
  const max = Math.max(...allVals);
  const min = Math.min(...allVals);
  const innerH = H - PAD.t - PAD.b;
  const n = Math.max(...series.map((s) => s.values.length), 1);
  const xv = c.x && c.x.length === n ? c.x : null;
  const xmin = xv ? Math.min(...xv) : 0;
  const xmax = xv ? Math.max(...xv) : n - 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {[0, 0.5, 1].map((f) => {
        const y = PAD.t + f * innerH;
        return <line key={f} x1={PAD.l} y1={y} x2={W - PAD.r} y2={y} stroke={GRID} opacity={0.5} />;
      })}
      {series.map((s, si) => {
        const pts = s.values.map((v, i) => {
          const xx = xv ? scale(xv[i], xmin, xmax, PAD.l, W - PAD.r) : scale(i, 0, n - 1, PAD.l, W - PAD.r);
          const yy = scale(v, min, max, PAD.t + innerH, PAD.t);
          return `${xx},${yy}`;
        });
        return <polyline key={si} points={pts.join(" ")} fill="none" stroke={PALETTE[si % PALETTE.length]} strokeWidth={1.5} />;
      })}
      <text x={PAD.l} y={PAD.t - 2} fill={TEXT} fontSize={9}>{max.toFixed(3)}</text>
      <text x={PAD.l} y={H - PAD.b + 10} fill={TEXT} fontSize={9}>{min.toFixed(3)}</text>
      {series.length > 1 && (
        <g>
          {series.map((s, si) => (
            <g key={si} transform={`translate(${W - PAD.r - 80}, ${PAD.t + 4 + si * 12})`}>
              <rect width={8} height={8} fill={PALETTE[si % PALETTE.length]} />
              <text x={11} y={8} fill={TEXT} fontSize={9}>{s.name}</text>
            </g>
          ))}
        </g>
      )}
    </svg>
  );
}

function ScatterChart({ c }: { c: ChartData }) {
  const pts = c.points ?? [];
  if (pts.length === 0) return null;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const innerH = H - PAD.t - PAD.b;
  const sx = (v: number) => scale(v, xmin, xmax, PAD.l, W - PAD.r);
  const sy = (v: number) => scale(v, ymin, ymax, PAD.t + innerH, PAD.t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {[0, 0.5, 1].map((f) => {
        const y = PAD.t + f * innerH;
        return <line key={f} x1={PAD.l} y1={y} x2={W - PAD.r} y2={y} stroke={GRID} opacity={0.4} />;
      })}
      {c.ref_line && (
        <line x1={sx(Math.max(xmin, ymin))} y1={sy(Math.max(xmin, ymin))} x2={sx(Math.min(xmax, ymax))} y2={sy(Math.min(xmax, ymax))} stroke={PALETTE[1]} strokeDasharray="3 3" opacity={0.7} />
      )}
      {pts.map((p, i) => (
        <circle key={i} cx={sx(p[0])} cy={sy(p[1])} r={1.6} fill={PALETTE[0]} opacity={0.55} />
      ))}
      {c.x_label && <text x={(PAD.l + W - PAD.r) / 2} y={H - 4} fill={AXIS} fontSize={9} textAnchor="middle">{c.x_label}</text>}
      {c.y_label && <text x={10} y={PAD.t + 4} fill={AXIS} fontSize={9}>{c.y_label}</text>}
    </svg>
  );
}

export function EvalChart({ c }: { c: ChartData }) {
  return (
    <div className="cc-card" style={{ padding: 10, minWidth: 0 }}>
      <div className="cc-soft" style={{ fontSize: 12, marginBottom: 4 }}>{c.title}</div>
      {c.kind === "bar" && <BarChart c={c} />}
      {c.kind === "line" && <LineChart c={c} />}
      {c.kind === "scatter" && <ScatterChart c={c} />}
    </div>
  );
}

export function EvalCharts({ charts }: { charts: ChartData[] }) {
  if (!charts || charts.length === 0) {
    return <div className="cc-dim" style={{ fontSize: 12 }}>暂无评价图（训练完成后自动生成）</div>;
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 10 }}>
      {charts.map((c) => <EvalChart key={c.id} c={c} />)}
    </div>
  );
}

export default EvalCharts;
