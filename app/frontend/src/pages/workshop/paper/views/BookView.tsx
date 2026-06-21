import { color } from "../colors";
import { balance, bookPositions, fills, posCount } from "../mock";
import {
  type PaperMarket,
  type BalanceCell,
  type BookPosition,
  type Fill,
} from "../types";

/**
 * 持仓与成交：余额条 + 持仓表 + 成交回报表。
 * 接真：传 live* 即用后端 /api/paper/* 派生数据；未传则回退 mock（调用方挂 MockBadge）。
 */
export function BookView({
  market,
  liveBalance,
  livePositions,
  liveFills,
}: {
  market: PaperMarket;
  liveBalance?: BalanceCell[] | null;
  livePositions?: BookPosition[] | null;
  liveFills?: Fill[] | null;
}) {
  const bal = liveBalance ?? balance(market);
  const positions = livePositions ?? bookPositions(market);
  const rows = liveFills ?? fills(market);
  const posLabel = livePositions ? `${positions.length} 票 · 已 MTM` : `${posCount(market)} 票 · 等权多头 · 已 MTM`;

  return (
    <div style={{ padding: "18px 22px", maxWidth: 900 }}>
      {/* balance strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4,1fr)",
          gap: 11,
          marginBottom: 16,
        }}
      >
        {bal.map((b) => (
          <div
            key={b.label}
            style={{
              background: "var(--desk-card)",
              border: "1px solid var(--desk-border)",
              borderRadius: "var(--desk-radius-lg)",
              padding: "11px 14px",
            }}
          >
            <div style={{ fontSize: 10.5, color: "var(--desk-text-muted)" }}>{b.label}</div>
            <div
              style={{ fontSize: 17, fontWeight: 700, color: "var(--desk-text-soft)", marginTop: 3 }}
            >
              {b.value}
            </div>
          </div>
        ))}
      </div>

      {/* positions table */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          overflow: "hidden",
          marginBottom: 16,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "11px 15px",
            background: "var(--desk-node-head)",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600 }}>
            当前持仓
          </span>
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-text-faint)" }}>
            {posLabel}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            padding: "8px 15px",
            fontSize: 10,
            color: "var(--desk-text-faint)",
            borderBottom: "1px solid var(--desk-border-soft)",
          }}
        >
          <span style={{ flex: 1.8 }}>标的</span>
          <span style={{ flex: 1, textAlign: "right" }}>权重</span>
          <span style={{ flex: 1, textAlign: "right" }}>数量</span>
          <span style={{ flex: 1.1, textAlign: "right" }}>成本</span>
          <span style={{ flex: 1.1, textAlign: "right" }}>现价</span>
          <span style={{ flex: 1, textAlign: "right" }}>浮盈</span>
        </div>
        {positions.map((p) => (
          <div
            key={p.sym}
            style={{
              display: "flex",
              alignItems: "center",
              padding: "8px 15px",
              borderBottom: "1px solid var(--desk-border-soft)",
              fontSize: 11.5,
            }}
          >
            <div style={{ flex: 1.8, display: "flex", flexDirection: "column" }}>
              <span style={{ color: "var(--desk-text-soft)" }}>{p.name}</span>
              <span style={{ color: "var(--desk-text-faint)", fontSize: 9.5 }}>{p.sym}</span>
            </div>
            <span style={{ flex: 1, textAlign: "right", color: "var(--desk-node-line)" }}>
              {p.w}
            </span>
            <span style={{ flex: 1, textAlign: "right", color: "var(--desk-node-line)" }}>
              {p.qty}
            </span>
            <span style={{ flex: 1.1, textAlign: "right", color: "var(--desk-text-muted)" }}>
              {p.entry}
            </span>
            <span style={{ flex: 1.1, textAlign: "right", color: "var(--desk-text-soft)" }}>
              {p.mark}
            </span>
            <span
              style={{ flex: 1, textAlign: "right", color: color(p.pnlColor), fontWeight: 600 }}
            >
              {p.pnl}
            </span>
          </div>
        ))}
      </div>

      {/* fills */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "11px 15px",
            background: "var(--desk-node-head)",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600 }}>
            成交回报 · fills
          </span>
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-text-faint)" }}>
            feed_bar 撮合 · 含滑点+手续费
          </span>
        </div>
        <div
          style={{
            display: "flex",
            padding: "8px 15px",
            fontSize: 10,
            color: "var(--desk-text-faint)",
            borderBottom: "1px solid var(--desk-border-soft)",
          }}
        >
          <span style={{ flex: 1.3 }}>时间</span>
          <span style={{ flex: 1.6 }}>标的</span>
          <span style={{ flex: 0.7 }}>方向</span>
          <span style={{ flex: 1, textAlign: "right" }}>数量</span>
          <span style={{ flex: 1, textAlign: "right" }}>成交价</span>
          <span style={{ flex: 1, textAlign: "right" }}>费用</span>
        </div>
        {rows.map((f, i) => (
          <div
            key={`${f.time}-${i}`}
            style={{
              display: "flex",
              alignItems: "center",
              padding: "7px 15px",
              borderBottom: "1px solid var(--desk-border-soft)",
              fontSize: 11,
            }}
          >
            <span style={{ flex: 1.3, color: "var(--desk-text-muted)" }}>{f.time}</span>
            <span style={{ flex: 1.6, color: "var(--desk-text-soft)" }}>{f.sym}</span>
            <span style={{ flex: 0.7, color: color(f.sideColor), fontWeight: 600 }}>{f.side}</span>
            <span style={{ flex: 1, textAlign: "right", color: "var(--desk-node-line)" }}>
              {f.qty}
            </span>
            <span style={{ flex: 1, textAlign: "right", color: "var(--desk-node-line)" }}>
              {f.price}
            </span>
            <span style={{ flex: 1, textAlign: "right", color: "var(--desk-text-muted)" }}>
              {f.fee}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
