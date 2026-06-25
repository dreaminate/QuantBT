import { StatusDot } from "../../../../components/desk";
import { color } from "../colors";
import {
  runHeader,
  runMetrics,
  runEquity,
  schedRows,
  posPreview,
  posCount,
} from "../mock";
import { type PaperRun, type PaperMarket, type SchedRow } from "../types";

/**
 * 运行盘：头部状态 + 4 指标 + 净值曲线 + 调度器 KV + 持仓速览。
 * 真实后端：传 liveSched（来自 /api/paper/status）即用后端 PaperSchedulerState；未传回退 mock。
 */
export function RunView({
  run,
  market,
  liveSched,
  liveRunning,
}: {
  run: PaperRun;
  market: PaperMarket;
  liveSched?: SchedRow[] | null;
  liveRunning?: boolean | null;
}) {
  const head = runHeader(run);
  const metrics = runMetrics(run);
  const eq = runEquity(run);
  const sched = liveSched ?? schedRows(run, market);
  const positions = posPreview(market);
  const running = liveRunning ?? run.status === "running";

  return (
    <div style={{ padding: "18px 22px", maxWidth: 880 }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 14 }}>
        <StatusDot color={color(head.statColor)} pulse size={9} />
        <span style={{ fontSize: 17, fontWeight: 700 }}>{head.name}</span>
        <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>{head.origin}</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: color(head.statColor),
            border: `1px solid ${color(head.statColor)}`,
            padding: "3px 11px",
            borderRadius: "var(--desk-radius-pill)",
          }}
        >
          {head.statText}
        </span>
      </div>

      {/* live metrics */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4,1fr)",
          gap: 11,
          marginBottom: 14,
        }}
      >
        {metrics.map((m) => (
          <div
            key={m.label}
            style={{
              background: "var(--desk-card)",
              border: "1px solid var(--desk-border)",
              borderRadius: "var(--desk-radius-lg)",
              padding: "11px 14px",
            }}
          >
            <div style={{ fontSize: 10.5, color: "var(--desk-text-muted)" }}>{m.label}</div>
            <div
              style={{ fontSize: 21, fontWeight: 700, color: color(m.color), marginTop: 3 }}
            >
              {m.value}
            </div>
            <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", marginTop: 2 }}>
              {m.note}
            </div>
          </div>
        ))}
      </div>

      {/* equity chart */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "13px 16px",
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 9 }}>
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600 }}>
            净值曲线 · equity log
          </span>
          <span style={{ fontSize: 10, color: "var(--desk-text-muted)" }}>
            mark_to_market 每收盘写一笔
          </span>
          <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--desk-success)" }}>
            vs {run.bench}
          </span>
        </div>
        <svg
          viewBox="0 0 720 200"
          preserveAspectRatio="none"
          style={{ width: "100%", height: 180, display: "block" }}
          aria-label="净值曲线"
        >
          <line
            x1={eq.splitX}
            y1={8}
            x2={eq.splitX}
            y2={192}
            stroke="var(--desk-border-hover)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
          <path
            d={eq.benchPath}
            fill="none"
            stroke="var(--desk-text-faint)"
            strokeWidth={1.2}
            strokeDasharray="3 3"
          />
          <path d={eq.histPath} fill="none" stroke="var(--desk-text-faint)" strokeWidth={1.6} />
          <path d={eq.paperArea} fill="var(--desk-minimap-view)" />
          <path d={eq.paperPath} fill="none" stroke="var(--desk-success)" strokeWidth={2.2} />
        </svg>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 9.5,
            color: "var(--desk-text-faint)",
            marginTop: 3,
          }}
        >
          <span>← 回测段（样本外延伸）</span>
          <span style={{ color: "var(--desk-border-hover)" }}>▏ 模拟盘上线</span>
          <span style={{ color: "var(--desk-success)" }}>实盘段 →</span>
        </div>
      </div>

      {/* scheduler + positions */}
      <div style={{ display: "flex", gap: 14 }}>
        <div
          style={{
            flex: 1.1,
            background: "var(--desk-card)",
            border: "1px solid var(--desk-border)",
            borderRadius: "var(--desk-radius-lg)",
            padding: "13px 15px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 11.5,
              color: "var(--desk-text-soft)",
              fontWeight: 600,
              marginBottom: 11,
            }}
          >
            <span style={{ color: "var(--desk-success)" }}>⟳</span>调度器 · PaperScheduler
            <span
              style={{
                marginLeft: "auto",
                fontSize: 9.5,
                color: "var(--desk-success)",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <StatusDot color="var(--desk-success)" pulse size={6} />
              {running ? "活跃" : "暂停"}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {sched.map((s) => (
              <div
                key={s.k}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "6px 0",
                  borderBottom: "1px solid var(--desk-border-soft)",
                  fontSize: 11,
                }}
              >
                <span style={{ color: "var(--desk-text-muted)" }}>{s.k}</span>
                <span style={{ color: color(s.color) }}>{s.v}</span>
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            flex: 1,
            background: "var(--desk-card)",
            border: "1px solid var(--desk-border)",
            borderRadius: "var(--desk-radius-lg)",
            padding: "13px 15px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 11.5,
              color: "var(--desk-text-soft)",
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            持仓速览
            <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-text-faint)" }}>
              top {posCount(market)}
            </span>
          </div>
          {positions.map((p) => (
            <div
              key={p.name}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "5px 0",
                borderBottom: "1px solid var(--desk-border-soft)",
              }}
            >
              <span
                style={{
                  flex: 1.6,
                  color: "var(--desk-text-soft)",
                  fontSize: 11.5,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {p.name}
              </span>
              <span
                style={{ flex: 0.8, textAlign: "right", color: "var(--desk-text-muted)", fontSize: 11 }}
              >
                {p.w}
              </span>
              <span
                style={{
                  flex: 0.9,
                  textAlign: "right",
                  color: color(p.pnlColor),
                  fontSize: 11,
                  fontWeight: 600,
                }}
              >
                {p.pnl}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
