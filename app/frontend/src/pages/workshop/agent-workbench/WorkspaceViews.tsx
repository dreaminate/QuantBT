import {
  buildCodeLines,
  MOCK_REPORT_MD,
  type CodeColor,
  type MilestoneKey,
  type ReportKind,
} from "./agentMock";

/**
 * 工作区非产物视图：Strategy.yaml（CODE）+ Report.md（REPORT）。
 * 全受控展示，色值经 token 映射（零裸 hex）。
 */

/** yaml 语义色 → desk token（ref 蓝标跨台来源）。 */
const CODE_COLOR_VAR: Record<CodeColor, string> = {
  key: "var(--desk-info)",
  val: "var(--desk-text-soft)",
  str: "var(--desk-success)",
  cmt: "var(--desk-text-faint)",
  plain: "var(--desk-text-dim)",
  ref: "var(--desk-info)",
};

export function CodeView({ reached }: { reached: MilestoneKey[] }) {
  const lines = buildCodeLines(reached);
  return (
    <div
      data-ws-view="code"
      style={{
        maxWidth: 640,
        margin: "0 auto",
        background: "var(--desk-input)",
        border: "1px solid var(--desk-border-soft)",
        borderRadius: "var(--desk-radius-lg)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "7px 14px",
          background: "var(--desk-card)",
          borderBottom: "1px solid var(--desk-border-soft)",
          color: "var(--desk-text-dim)",
          fontSize: 11,
        }}
      >
        strategy/weekly_cn_multifactor.yaml
      </div>
      <div style={{ padding: "12px 0" }}>
        {lines.map((ln) => (
          <div key={ln.n} style={{ display: "flex", padding: "0 14px" }}>
            <span
              style={{
                color: "var(--desk-border-strong)",
                minWidth: 28,
                textAlign: "right",
                paddingRight: 14,
                userSelect: "none",
                fontSize: 12,
              }}
            >
              {ln.n}
            </span>
            <span
              style={{
                color: CODE_COLOR_VAR[ln.color],
                whiteSpace: "pre",
                fontSize: 12.5,
              }}
            >
              {ln.t}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const REPORT_STYLE: Record<ReportKind, React.CSSProperties> = {
  h: {
    color: "var(--desk-text)",
    fontWeight: 700,
    fontSize: 16,
    marginBottom: 8,
  },
  h2: {
    color: "var(--desk-accent)",
    fontWeight: 600,
    margin: "13px 0 5px",
  },
  li: { color: "var(--desk-success)", margin: "3px 0 3px 4px" },
  p: {
    color: "var(--desk-text-muted)",
    marginBottom: 6,
    lineHeight: 1.6,
  },
};

export function ReportView() {
  return (
    <div
      data-ws-view="report"
      style={{
        maxWidth: 620,
        margin: "0 auto",
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border-strong)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "18px 22px",
      }}
    >
      {MOCK_REPORT_MD.map((m, i) => (
        <div key={i} style={REPORT_STYLE[m.kind]}>
          {m.kind === "li" ? `· ${m.t}` : m.t}
        </div>
      ))}
    </div>
  );
}
