import { color } from "../colors";
import { reviewRows, REVIEW_NOTE, attrBars, costCells } from "../mock";
import { type PaperRun } from "../types";

/**
 * 复盘归因：回测预期 → 模拟实盘衰减表 + 超额因子归因 + 成本拖累。
 * R25：实盘衰减/弱点不折叠不染绿——劣化项保留黄/红 decayColor，诚实暴露。
 */
export function ReviewView({ run }: { run: PaperRun }) {
  const rows = reviewRows();
  const attr = attrBars();
  const cost = costCells();
  const excess = (run.excess >= 0 ? "+" : "") + (run.excess * 100).toFixed(1) + "%";

  return (
    <div style={{ padding: "18px 22px", maxWidth: 900 }}>
      <div style={{ fontSize: 12, color: "var(--desk-text-muted)", marginBottom: 14 }}>
        复盘归因 · 回测预期 vs 模拟实盘 · 实盘衰减与超额拆解
      </div>

      {/* expected vs realized */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "13px 16px",
          marginBottom: 14,
        }}
      >
        <div style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600, marginBottom: 11 }}>
          回测预期 → 模拟实盘
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              padding: "7px 0",
              fontSize: 10,
              color: "var(--desk-text-faint)",
              borderBottom: "1px solid var(--desk-grid-dot)",
            }}
          >
            <span style={{ flex: 1.4 }}>指标</span>
            <span style={{ flex: 1, textAlign: "right" }}>回测段</span>
            <span style={{ flex: 1, textAlign: "right" }}>模拟段</span>
            <span style={{ flex: 1, textAlign: "right" }}>实盘衰减</span>
          </div>
          {rows.map((r) => (
            <div
              key={r.k}
              style={{
                display: "flex",
                padding: "9px 0",
                borderBottom: "1px solid var(--desk-border-soft)",
                fontSize: 12,
              }}
            >
              <span style={{ flex: 1.4, color: "var(--desk-text-dim)" }}>{r.k}</span>
              <span style={{ flex: 1, textAlign: "right", color: "var(--desk-text-muted)" }}>
                {r.bt}
              </span>
              <span
                style={{ flex: 1, textAlign: "right", color: "var(--desk-text-soft)", fontWeight: 600 }}
              >
                {r.paper}
              </span>
              <span style={{ flex: 1, textAlign: "right", color: color(r.decayColor) }}>
                {r.decay}
              </span>
            </div>
          ))}
        </div>
        <div
          style={{
            marginTop: 11,
            fontSize: 10.5,
            color: "var(--desk-text-muted)",
            lineHeight: 1.6,
            background: "var(--desk-node-head)",
            borderLeft: "3px solid var(--desk-warning)",
            borderRadius: "var(--desk-radius-sm)",
            padding: "8px 11px",
          }}
        >
          {REVIEW_NOTE}
        </div>
      </div>

      {/* factor attribution */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "13px 16px",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12,
            color: "var(--desk-text-soft)",
            fontWeight: 600,
            marginBottom: 12,
          }}
        >
          超额因子归因
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-text-faint)" }}>
            vs {run.bench} · 累计 {excess}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {attr.map((a) => (
            <div key={a.name} style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <span style={{ width: 120, flex: "none", fontSize: 11, color: "var(--desk-text-dim)" }}>
                {a.name}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 18,
                  background: "var(--desk-node-head)",
                  borderRadius: 4,
                  position: "relative",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    left: a.left,
                    width: a.width,
                    top: 0,
                    bottom: 0,
                    background: color(a.color),
                    borderRadius: 3,
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: 0,
                    bottom: 0,
                    width: 1,
                    background: "var(--desk-border-hover)",
                  }}
                />
              </div>
              <span
                style={{
                  width: 54,
                  flex: "none",
                  textAlign: "right",
                  fontSize: 11,
                  color: color(a.color),
                  fontWeight: 600,
                }}
              >
                {a.val}
              </span>
            </div>
          ))}
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 9,
            color: "var(--desk-text-faint)",
            marginTop: 9,
            paddingLeft: 131,
          }}
        >
          <span>−贡献</span>
          <span>0</span>
          <span>+贡献</span>
        </div>
      </div>

      {/* cost drag */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 11 }}>
        {cost.map((c) => (
          <div
            key={c.label}
            style={{
              background: "var(--desk-card)",
              border: "1px solid var(--desk-border)",
              borderRadius: "var(--desk-radius-lg)",
              padding: "11px 14px",
            }}
          >
            <div style={{ fontSize: 10.5, color: "var(--desk-text-muted)" }}>{c.label}</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: color(c.color), marginTop: 3 }}>
              {c.value}
            </div>
            <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", marginTop: 2 }}>
              {c.note}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
