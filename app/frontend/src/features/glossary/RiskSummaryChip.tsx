/**
 * v0.8.4 Day 4 · RunDetail 顶部证据状态 chip + popover。
 *
 * 4 档：ok / caution / high_risk / insufficient_data
 * 只读展示；不写策略买卖建议；缺字段显示"信息不足"而非报错。
 *
 * 严格隔离: ig-* 不依赖 jq-* / cc-* 样式，inline style 兜底，
 * 加在 RunOverviewTab header 旁边不破坏冻结布局。
 */

import { useEffect, useRef, useState } from "react";
import { trackEvent } from "./trackEvent";
import type { RiskSummary } from "../../types";

interface Props {
  riskSummary?: RiskSummary | null;
  /** v0.8.7.1: 显示"审计覆盖"小绿勾 */
  auditedMetrics?: boolean;
}

const TRUST_PRESET = {
  ok: { label: "证据一致", color: "#1f9a52", bg: "rgba(31, 154, 82, 0.12)" },
  caution: { label: "存疑", color: "#c98a14", bg: "rgba(201, 138, 20, 0.12)" },
  high_risk: { label: "高风险", color: "#cc3344", bg: "rgba(204, 51, 68, 0.12)" },
  insufficient_data: { label: "信息不足", color: "#888888", bg: "rgba(136, 136, 136, 0.12)" },
} as const;

export function RiskSummaryChip({ riskSummary, auditedMetrics = true }: Props) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // mount 时触发一次"看见证据状态卡片"
  useEffect(() => {
    if (riskSummary) {
      trackEvent("risk_summary_shown", {
        trust_level: riskSummary.trust_level,
        flag_count: riskSummary.flags.length,
      });
    }
  }, [riskSummary?.trust_level, riskSummary?.flags.length]);

  if (!riskSummary) return null;

  const preset = TRUST_PRESET[riskSummary.trust_level];
  return (
    <span ref={boxRef} style={{ position: "relative", display: "inline-block", marginLeft: 12, verticalAlign: "middle" }}>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        title={riskSummary.summary}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          background: preset.bg,
          color: preset.color,
          border: `1px solid ${preset.color}`,
          borderRadius: 12,
          fontSize: 11,
          lineHeight: 1.3,
          fontFamily: "inherit",
          cursor: "pointer",
          fontWeight: 600,
        }}
        aria-label={`证据状态: ${preset.label}`}
      >
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: preset.color }} />
        {preset.label}
        {riskSummary.flags.length > 0 && (
          <span style={{ opacity: 0.85, fontWeight: 400 }}>· {riskSummary.flags.length}</span>
        )}
      </button>
      {auditedMetrics && (
        <span
          title="PBO / DSR / Purged k-fold 经 v0.8.7.1 学术 audit 单测覆盖"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 2,
            marginLeft: 4,
            padding: "1px 6px",
            background: "rgba(31, 154, 82, 0.12)",
            color: "#1f9a52",
            border: "1px solid #1f9a52",
            borderRadius: 10,
            fontSize: 10,
            fontWeight: 500,
            verticalAlign: "middle",
          }}
        >
          ✓ audited
        </span>
      )}
      {open && (
        <div
          role="dialog"
          onClick={(e) => e.stopPropagation()}
          style={{
            position: "absolute",
            zIndex: 999,
            top: "calc(100% + 6px)",
            left: 0,
            minWidth: 320,
            maxWidth: 480,
            background: "var(--cc-bg-elev, #1a1f2a)",
            color: "var(--cc-text, #e6edf3)",
            border: "1px solid var(--cc-border, rgba(255,255,255,0.12))",
            borderRadius: 6,
            padding: 12,
            boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
            fontSize: 12,
            lineHeight: 1.5,
            textAlign: "left",
            fontWeight: "normal",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            <span style={{ color: preset.color }}>● {preset.label}</span>
            <span style={{ marginLeft: 8, color: "var(--cc-dim, #888)", fontWeight: 400 }}>{riskSummary.summary}</span>
          </div>
          {riskSummary.flags.length > 0 && (
            <ul style={{ paddingLeft: 18, margin: "4px 0 6px 0" }}>
              {riskSummary.flags.map((f) => (
                <li key={f.name} style={{ marginBottom: 4 }}>
                  <span
                    style={{
                      fontSize: 10,
                      padding: "1px 5px",
                      marginRight: 6,
                      borderRadius: 3,
                      background: f.severity === "high" ? "rgba(204,51,68,0.2)" : "rgba(201,138,20,0.2)",
                      color: f.severity === "high" ? "#ff7a87" : "#e2b358",
                    }}
                  >
                    {f.severity.toUpperCase()}
                  </span>
                  {f.message}
                </li>
              ))}
            </ul>
          )}
          {riskSummary.checked_metrics.length > 0 && (
            <div style={{ fontSize: 10, color: "var(--cc-dim, #888)", marginTop: 6, borderTop: "1px solid var(--cc-border, rgba(255,255,255,0.08))", paddingTop: 6 }}>
              已检 {riskSummary.checked_metrics.length} 个指标: {riskSummary.checked_metrics.join(" · ")}
            </div>
          )}
          <div style={{ fontSize: 10, color: "var(--cc-dim, #666)", marginTop: 6, fontStyle: "italic" }}>
            本卡片仅展示当前证据状态，**不构成投资建议**
          </div>
        </div>
      )}
    </span>
  );
}
