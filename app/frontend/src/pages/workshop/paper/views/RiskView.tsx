import { color } from "../colors";
import { riskGates, violations } from "../mock";

/**
 * 风险门 · 会话外不可改（治理核心）。
 * 关键不变量：门限发布时冻结、Agent 会话内永不可改 —— 本视图为纯只读 dashboard，
 * 不渲染任何 input/select/可编辑控件（只读硬墙的证据）。违规日志为 append-only 哈希链。
 */
export function RiskView() {
  const gates = riskGates();
  const log = violations();

  return (
    <div style={{ padding: "18px 22px", maxWidth: 840 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ color: "var(--desk-success)", fontSize: 15 }}>⛨</span>
        <span style={{ fontSize: 16, fontWeight: 700 }}>风险门 · 会话外不可改</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: "var(--desk-success)",
            background: "transparent",
            border: "1px solid var(--desk-success)",
            padding: "4px 12px",
            borderRadius: "var(--desk-radius-pill)",
          }}
        >
          全绿 · 1 预警
        </span>
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--desk-text-muted)",
          marginBottom: 16,
          lineHeight: 1.6,
        }}
      >
        门限在策略发布时冻结，Agent 在会话中
        <span style={{ color: "var(--desk-danger)" }}>永不可改</span>
        。本地门仅为防篡改证据（非防篡改）——A股的唯一硬墙在交易所侧远程信任域。
      </div>

      {/* gate grid — 只读：每格无编辑控件，仅展示 cur/limit/进度 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2,1fr)",
          gap: 11,
          marginBottom: 16,
        }}
      >
        {gates.map((g) => (
          <div
            key={g.k}
            data-testid="risk-gate"
            data-locked={g.locked ? "true" : "false"}
            style={{
              background: "var(--desk-card)",
              border: `1px solid ${g.breach ? "var(--desk-danger)" : "var(--desk-border)"}`,
              borderRadius: "var(--desk-radius-lg)",
              padding: "12px 14px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 11, color: "var(--desk-text-soft)", fontWeight: 600 }}>
                {g.k}
              </span>
              {g.locked && (
                <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-warning)" }}>
                  🔒 冻结
                </span>
              )}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontSize: 18, fontWeight: 700, color: color(g.color) }}>{g.cur}</span>
              <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>/ 限 {g.limit}</span>
            </div>
            <div
              style={{
                height: 5,
                background: "var(--desk-grid-dot)",
                borderRadius: 3,
                overflow: "hidden",
                marginTop: 8,
              }}
            >
              <div style={{ height: "100%", width: g.pct, background: color(g.color) }} />
            </div>
          </div>
        ))}
      </div>

      {/* violation log — append-only 哈希链 */}
      <div
        style={{
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
          <span style={{ color: "var(--desk-success)" }}>≣</span>违规日志 · 防篡改证据链
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-text-faint)" }}>
            append-only · 哈希链
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {log.map((l) => (
            <div key={l.hash} style={{ display: "flex", gap: 11, paddingBottom: 11 }}>
              <div
                style={{
                  flex: "none",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    width: 9,
                    height: 9,
                    borderRadius: "50%",
                    background: color(l.color),
                  }}
                />
                {l.line && (
                  <span
                    style={{
                      width: 1,
                      flex: 1,
                      background: "var(--desk-border-strong)",
                      marginTop: 3,
                    }}
                  />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0, paddingBottom: 2 }}>
                <div style={{ fontSize: 11.5, color: color(l.titleColor) }}>{l.title}</div>
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--desk-text-muted)",
                    marginTop: 2,
                    lineHeight: 1.5,
                  }}
                >
                  {l.detail}
                </div>
                <div style={{ fontSize: 9, color: "var(--desk-text-faint)", marginTop: 2 }}>
                  {l.when} · {l.hash}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
