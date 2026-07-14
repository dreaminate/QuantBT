import { StatusDot, MockBadge } from "./desk";
import { buildEquityPaths } from "../pages/workshop/paper/equity";
import { signColor, pnlColor, color, pct } from "../pages/workshop/paper/colors";
import { defaultBoardData } from "../pages/workshop/paper/mock";
import { type PaperBoardData } from "../pages/workshop/paper/types";

/**
 * 模拟盘速览卡（PaperBoard.dc.html）——可嵌进策略台/首页/跟单页的复用 widget。
 * metrics + 净值缩略 + 持仓 top N + 风险门 4 格。mock/backend 来源由 props 判别，禁止 backend 缺值时静默补 mock。
 * 风险门「会话外不可改」：纯展示、无任何编辑控件（只读硬墙的证据）。
 */
type PaperBoardCardProps =
  | { source?: "mock"; board?: Partial<PaperBoardData> }
  | { source: "backend"; board: PaperBoardData };

export function PaperBoardCard(props: PaperBoardCardProps) {
  const isMock = props.source !== "backend";
  if (props.source === "backend" && !props.board) {
    return (
      <div data-testid="paper-board-unavailable" style={{ color: "var(--desk-warning)" }}>
        后端 board 数据不可用；未回落 MOCK。
      </div>
    );
  }
  if (
    props.source === "backend"
    && (!props.board.runtimeEvidence || !props.board.riskEvidence)
  ) {
    return (
      <div
        data-testid="paper-board-unavailable"
        style={{ color: "var(--desk-warning)" }}
      >
        后端 board 缺运行或风险证据；未渲染收益、净值与全绿状态，也未回落 MOCK。
      </div>
    );
  }
  const data: PaperBoardData = props.source === "backend"
    ? props.board
    : { ...defaultBoardData(), ...props.board };
  const runtimeEvidence = data.runtimeEvidence;
  const runtimeRunning = runtimeEvidence?.status === "running";
  const runtimeTone = runtimeRunning ? "var(--desk-success)" : "var(--desk-warning)";
  const runtimeLabel = runtimeEvidence?.label?.trim()
    || (isMock ? "运行中" : "运行状态证据不可用");
  const riskEvidence = data.riskEvidence;
  const riskGreen = riskEvidence?.chainIntact === true && riskEvidence.violationCount === 0;
  const riskTone = riskGreen ? "var(--desk-success)" : "var(--desk-warning)";
  const riskLabel = riskEvidence === undefined
    ? (isMock ? "全绿 · 0 违规" : "风险证据不可用")
    : riskEvidence.chainIntact !== true
      ? "风险链未验证"
      : riskEvidence.violationCount === null
        ? "违规数不可用"
        : `${riskEvidence.violationCount} 违规`;
  const W = 600;
  const H = 110;
  const PAD = 6;
  const paths = buildEquityPaths(
    data.hist,
    data.paper,
    [],
    W,
    H,
    PAD,
    data.hist.length,
    data.hist.length + data.paper.length - 1,
  );

  const risks: { k: string; v: string; color: ReturnType<typeof color>; locked: boolean }[] = [
    { k: "单笔名义上限", v: data.risk.maxNotional, color: color("flat"), locked: false },
    { k: "杠杆", v: `${data.risk.leverage.toFixed(1)}×`, color: color("warn"), locked: true },
    { k: "换手上限", v: data.risk.turnover, color: color("flat"), locked: false },
    { k: "回撤熔断", v: data.risk.ddHalt, color: color("flat"), locked: true },
  ];

  return (
    <div
      data-testid="paper-board-card"
      style={{
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border-strong)",
        borderRadius: "var(--desk-radius-lg)",
        overflow: "hidden",
        fontFamily: "var(--desk-mono)",
        color: "var(--desk-text)",
      }}
    >
      {/* header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 9,
          padding: "11px 15px",
          background: "var(--desk-node-head)",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <StatusDot color={runtimeTone} pulse={runtimeRunning} size={8} />
        <span style={{ fontWeight: 600 }}>模拟盘 · {data.strategy}</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: runtimeTone,
            border: `1px solid ${runtimeTone}`,
            padding: "3px 10px",
            borderRadius: "var(--desk-radius-pill)",
          }}
        >
          {runtimeLabel} · 第 {data.days} 周
        </span>
        {isMock && <MockBadge />}
      </div>

      {/* live metrics */}
      <div style={{ display: "flex", padding: "13px 15px 9px" }}>
        <Metric label="今日盈亏" value={pct(data.pnlToday, 2)} tone={pnlColor(data.pnlToday)} />
        <Metric label="累计收益" value={pct(data.totalReturn)} tone="flat" />
        <Metric label="超额(vs 500)" value={pct(data.excess)} tone="up" />
      </div>

      {/* nav chart */}
      <div style={{ padding: "2px 15px 10px" }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: 88, display: "block" }}
          aria-label="净值缩略图"
        >
          <line
            x1={paths.splitX}
            y1={6}
            x2={paths.splitX}
            y2={H - PAD}
            stroke="var(--desk-border-hover)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
          <path d={paths.histPath} fill="none" stroke="var(--desk-text-faint)" strokeWidth={1.5} />
          <path d={paths.paperPath} fill="none" stroke="var(--desk-success)" strokeWidth={2} />
        </svg>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            color: "var(--desk-text-faint)",
            fontSize: 10,
            marginTop: 2,
          }}
        >
          <span>← 回测段</span>
          <span style={{ color: "var(--desk-success)" }}>模拟盘上线 →</span>
        </div>
      </div>

      {/* positions */}
      <div style={{ padding: "2px 15px 10px" }}>
        <div style={{ color: "var(--desk-text-muted)", fontSize: 11, marginBottom: 6 }}>
          当前持仓 · top {data.positions.length}
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {data.positions.map((p) => (
            <div
              key={p.sym}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "5px 0",
                borderBottom: "1px solid var(--desk-grid-dot)",
              }}
            >
              <span style={{ flex: 1.4, color: "var(--desk-text-soft)" }}>{p.name}</span>
              <span style={{ flex: 1, color: "var(--desk-text-muted)", fontSize: 12 }}>{p.sym}</span>
              <span
                style={{ flex: 0.8, textAlign: "right", color: "var(--desk-node-line)" }}
              >
                {p.w}
              </span>
              <span
                style={{ flex: 0.9, textAlign: "right", color: color(signColor(p.pnl)) }}
              >
                {pct(p.pnl / 100)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* risk gate — 会话外不可改：纯展示、无编辑控件 */}
      <div
        style={{
          padding: "11px 15px",
          background: "var(--desk-soft-btn)",
          borderTop: "1px solid var(--desk-border)",
        }}
      >
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}
        >
          <span style={{ color: "var(--desk-success)" }}>⛨</span>
          <span style={{ color: "var(--desk-text-soft)", fontWeight: 600, fontSize: 12.5 }}>
            风险门 · 会话外不可改
          </span>
          <span
            data-testid="paper-board-risk-evidence"
            style={{ marginLeft: "auto", fontSize: 11, color: riskTone }}
          >
            {riskLabel}
          </span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
          {risks.map((r) => (
            <div
              key={r.k}
              style={{
                flex: "1 1 44%",
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                background: "var(--desk-node-head)",
                border: "1px solid var(--desk-border)",
                borderRadius: "var(--desk-radius-sm)",
                padding: "6px 10px",
              }}
            >
              <span style={{ color: "var(--desk-text-muted)", fontSize: 11.5 }}>{r.k}</span>
              <span style={{ color: r.color, fontSize: 11.5, fontWeight: 600 }}>
                {r.v} {r.locked ? "🔒" : ""}
              </span>
            </div>
          ))}
        </div>
        <div
          style={{
            marginTop: 9,
            fontSize: 11,
            color: "var(--desk-text-faint)",
            lineHeight: 1.55,
          }}
        >
          A股止于 paper — 唯一硬墙在交易所侧远程信任域;本地门仅为防篡改证据,非防篡改。
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: Parameters<typeof color>[0];
}) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>{label}</div>
      <div style={{ color: color(tone), fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
