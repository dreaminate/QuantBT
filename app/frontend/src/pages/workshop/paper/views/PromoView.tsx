import { color } from "../colors";
import {
  promoStages,
  promoEligibility,
  promoChecks,
  approveState,
  approveLabel,
  approveHint,
  promoFactors,
} from "../mock";
import { type PaperRun, type PromoCheck } from "../types";

/**
 * 晋升通道 · live ladder 的 paper→OBSERVATION 段。
 * INV-5：Agent 永不自动晋级，须人工审批 + 验证背书。审批按钮三态：
 *   ready=可点（人工触发）/ promoted=已晋级只读 / blocked=不可点（禁用），不一键自动晋级。
 * 接真：liveChecks 来自后端 4 门聚合（/api/paper/promotion）；onApprove 由页面接 POST 审批端点。
 */
export function PromoView({
  run,
  promoted,
  onApprove,
  liveChecks,
}: {
  run: PaperRun;
  promoted: boolean;
  onApprove: () => void;
  liveChecks?: PromoCheck[] | null;
}) {
  const stages = promoStages(promoted);
  const elig = promoEligibility(run, promoted);
  const checks = liveChecks ?? promoChecks(run);
  const aState = approveState(run, promoted);
  const factors = promoFactors(promoted);

  const approveStyle: React.CSSProperties =
    aState === "promoted"
      ? {
          background: "transparent",
          border: "1px solid var(--desk-success)",
          color: "var(--desk-success)",
          cursor: "default",
        }
      : aState === "ready"
        ? {
            background: "var(--desk-success)",
            border: "none",
            color: "var(--desk-accent-ink)",
            fontWeight: 700,
            cursor: "pointer",
          }
        : {
            background: "var(--desk-hover)",
            border: "1px solid var(--desk-border-strong)",
            color: "var(--desk-text-faint)",
            cursor: "not-allowed",
          };

  return (
    <div style={{ padding: "18px 22px", maxWidth: 860 }}>
      <div style={{ fontSize: 12, color: "var(--desk-text-muted)", marginBottom: 4 }}>
        晋升通道 · 模拟实盘是因子/策略上真钱前的最后一道闸
      </div>
      <div style={{ fontSize: 11, color: "var(--desk-text-faint)", marginBottom: 16 }}>
        与因子台五态机联动：<span style={{ color: "var(--desk-warning)" }}>PROBATION</span> → 模拟实盘 1
        月年化 &gt; 基准 → <span style={{ color: "var(--desk-success)" }}>OBSERVATION</span>。Agent
        永不自动晋级，须人工审批 + 验证背书（INV-5）。
      </div>

      {/* pipeline */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          padding: 16,
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "stretch" }}>
          {stages.map((s) => {
            const nodeStyle: React.CSSProperties = s.current
              ? {
                  background: "var(--desk-success)",
                  color: "var(--desk-accent-ink)",
                  boxShadow: "0 0 0 4px var(--desk-minimap-view)",
                }
              : s.reached
                ? {
                    background: "transparent",
                    color: "var(--desk-success)",
                    border: "2px solid var(--desk-success)",
                  }
                : {
                    background: "var(--desk-node-head)",
                    color: "var(--desk-text-faint)",
                    border: "2px solid var(--desk-border-strong)",
                  };
            return (
              <div
                key={s.label}
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 14,
                    fontWeight: 700,
                    ...nodeStyle,
                  }}
                >
                  {s.glyph}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: s.reached || s.current ? "var(--desk-success)" : "var(--desk-text-faint)",
                    fontWeight: s.current ? 700 : 500,
                    marginTop: 8,
                  }}
                >
                  {s.label}
                </div>
                <div
                  style={{
                    fontSize: 9,
                    color: "var(--desk-text-faint)",
                    marginTop: 3,
                    textAlign: "center",
                    lineHeight: 1.4,
                    minHeight: 26,
                  }}
                >
                  {s.sub}
                </div>
                {s.hasArrow && (
                  <div
                    style={{
                      position: "absolute",
                      top: 16,
                      right: -1,
                      width: "calc(100% - 8px)",
                      height: 1,
                      transform: "translateX(50%)",
                      background: s.arrowReached
                        ? "var(--desk-success)"
                        : "var(--desk-border-strong)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* gate check */}
      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-success)",
          borderRadius: "var(--desk-radius-lg)",
          overflow: "hidden",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            padding: "12px 15px",
            background: "var(--desk-node-head)",
            borderBottom: "1px solid var(--desk-success)",
            display: "flex",
            alignItems: "center",
            gap: 9,
          }}
        >
          <span style={{ color: "var(--desk-success)" }}>⤴</span>
          <span style={{ fontWeight: 700 }}>晋级判定 · {run.name}</span>
          <span
            style={{
              marginLeft: "auto",
              fontSize: 10,
              color: color(elig.color),
              border: `1px solid ${color(elig.color)}`,
              padding: "2px 10px",
              borderRadius: "var(--desk-radius-pill)",
            }}
          >
            {elig.label}
          </span>
        </div>
        <div style={{ padding: "13px 15px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 13 }}>
            {checks.map((c) => (
              <div
                key={c.t}
                style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12 }}
              >
                <span style={{ color: color(c.color), fontSize: 13 }}>{c.icon}</span>
                <span style={{ color: "var(--desk-text-dim)", flex: 1 }}>{c.t}</span>
                <span style={{ color: color(c.color), fontSize: 11 }}>{c.v}</span>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
            <button
              type="button"
              onClick={onApprove}
              disabled={aState !== "ready"}
              aria-disabled={aState !== "ready"}
              style={{
                fontFamily: "inherit",
                fontSize: 12,
                padding: "9px 16px",
                borderRadius: "var(--desk-radius)",
                ...approveStyle,
              }}
            >
              {approveLabel(aState)}
            </button>
            <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>
              {approveHint(aState)}
            </span>
          </div>
        </div>
      </div>

      {/* factor lifecycle linkage */}
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
          本策略因子 · 生命周期联动
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-ghost)" }}>
            去因子台 ↗
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {factors.map((f) => (
            <div
              key={f.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 0",
                borderBottom: "1px solid var(--desk-border-soft)",
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  flex: "none",
                  background: color(f.stateColor),
                }}
              />
              <span style={{ flex: 1.6, color: "var(--desk-text-soft)", fontSize: 11.5 }}>
                {f.id}
              </span>
              <span style={{ flex: 1, fontSize: 10, color: color(f.stateColor) }}>{f.state}</span>
              <span
                style={{ flex: 1, textAlign: "right", fontSize: 10.5, color: "var(--desk-text-muted)" }}
              >
                权重 {f.w}
              </span>
              <span
                style={{
                  flex: 0.9,
                  textAlign: "right",
                  fontSize: 10.5,
                  color: color(f.contribColor),
                }}
              >
                {f.contrib}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
