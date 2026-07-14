import { useEffect, useState } from "react";
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
import { type ApproveState, type PaperRun, type PromoCheck } from "../types";

/**
 * 晋升通道 · live ladder 的 paper→OBSERVATION 段。
 * INV-5：系统不会自动晋级，须人工审批 + 验证背书。审批按钮三态：
 *   ready=可点（人工触发）/ promoted=已晋级只读 / blocked=不可点（禁用），不一键自动晋级。
 * 真实后端：liveChecks 来自后端 4 门聚合（/api/paper/promotion）；onApprove 由页面接 POST 审批端点。
 *
 * §3 不假绿灯：审批须填验证背书(endorsement_ref) + 理由(reason)——后端 INV-5 必拒空，
 * 前端同样硬拦（空背书/空理由不发请求），失败显式报错、绝不乐观伪「已晋级」绿态。
 */
export function PromoView({
  run,
  promoted,
  onApprove,
  liveMode = false,
  liveRunName,
  liveEligible,
  liveChecks,
  approving,
  approveError,
}: {
  run: PaperRun;
  promoted: boolean;
  /** 提交真审批：携验证背书 + 理由（INV-5）。失败由页面经 approveError 显式回传。 */
  onApprove: (form: { endorsementRef: string; reason: string }) => void;
  /** true 时整页只显示 promotion API 返回的状态；未返回的生命周期数据显式标不可用。 */
  liveMode?: boolean;
  liveRunName?: string;
  liveEligible?: boolean;
  liveChecks?: PromoCheck[] | null;
  /** 审批请求在途（禁用按钮，防重复提交）。 */
  approving?: boolean;
  /** 审批失败的诚实错误文案（缺背书/未审批/网络失败）；非空即显红，不伪成功。 */
  approveError?: string | null;
}) {
  const stages = liveMode ? [] : promoStages(promoted);
  const elig = liveMode
    ? {
        eligible: liveEligible === true,
        label: promoted
          ? "后端状态：已晋级"
          : liveEligible
            ? "后端判定：满足晋级条件"
            : "后端判定：不满足晋级条件",
        color: promoted || liveEligible ? ("up" as const) : ("warn" as const),
      }
    : promoEligibility(run, promoted);
  const checks = liveMode ? (liveChecks ?? []) : promoChecks(run);
  const aState: ApproveState = liveMode
    ? promoted
      ? "promoted"
      : liveEligible
        ? "ready"
        : "blocked"
    : approveState(run, promoted);
  const factors = liveMode ? [] : promoFactors(promoted);
  const displayName = liveMode ? (liveRunName ?? "后端未返回 run 名称") : run.name;
  const approvalLabel = liveMode
    ? aState === "promoted"
      ? "✓ 已晋级 · 后端已记录"
      : "⤴ 人工审批晋级"
    : approveLabel(aState);
  const approvalHint = liveMode
    ? aState === "promoted"
      ? "晋级状态来自后端 promotion 记录"
      : "Agent 永不自动 · 须人工 + 验证背书（INV-5）"
    : approveHint(aState);

  // 审批表单：验证背书 + 理由（INV-5 必填，前端硬拦空值）。
  const [endorsementRef, setEndorsementRef] = useState("");
  const [reason, setReason] = useState("");
  const formIncomplete = !endorsementRef.trim() || !reason.trim();

  // 晋级成功后清空表单（避免残留旧背书/理由被下次误提交）。
  useEffect(() => {
    if (promoted) {
      setEndorsementRef("");
      setReason("");
    }
  }, [promoted]);

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
        {liveMode
          ? "晋升通道 · 后端 promotion gate"
          : "晋升通道 · 模拟实盘是因子/策略上真钱前的最后一道闸"}
      </div>
      <div style={{ fontSize: 11, color: "var(--desk-text-faint)", marginBottom: 16 }}>
        {liveMode ? (
          "合格、晋级和门检查均来自 /api/paper/*；接口未返回的生命周期与因子引用不会用 mock 补齐。"
        ) : (
          <>
            与因子台五态机联动：<span style={{ color: "var(--desk-warning)" }}>PROBATION</span> → 模拟实盘 1
            月年化 &gt; 基准 → <span style={{ color: "var(--desk-success)" }}>OBSERVATION</span>。Agent
            永不自动晋级，须人工审批 + 验证背书（INV-5）。
          </>
        )}
      </div>

      {/* pipeline */}
      <div
        data-testid={liveMode ? "live-promo-lifecycle-unavailable" : undefined}
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          padding: 16,
          marginBottom: 14,
        }}
      >
        {liveMode ? (
          <div style={{ color: "var(--desk-text-muted)", fontSize: 11.5, lineHeight: 1.6 }}>
            promotion API 未返回生命周期阶段引用；此处不显示 mock 阶段。
          </div>
        ) : (
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
                      color:
                        s.reached || s.current
                          ? "var(--desk-success)"
                          : "var(--desk-text-faint)",
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
        )}
      </div>

      {/* gate check */}
      <div
        style={{
          background: "var(--desk-card)",
          border: `1px solid ${color(elig.color)}`,
          borderRadius: "var(--desk-radius-lg)",
          overflow: "hidden",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            padding: "12px 15px",
            background: "var(--desk-node-head)",
            borderBottom: `1px solid ${color(elig.color)}`,
            display: "flex",
            alignItems: "center",
            gap: 9,
          }}
        >
          <span style={{ color: color(elig.color) }}>⤴</span>
          <span style={{ fontWeight: 700 }}>晋级判定 · {displayName}</span>
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
            {checks.length ? (
              checks.map((c) => (
                <div
                  key={c.t}
                  style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12 }}
                >
                  <span style={{ color: color(c.color), fontSize: 13 }}>{c.icon}</span>
                  <span style={{ color: "var(--desk-text-dim)", flex: 1 }}>{c.t}</span>
                  <span style={{ color: color(c.color), fontSize: 11 }}>{c.v}</span>
                </div>
              ))
            ) : (
              <span style={{ color: "var(--desk-text-muted)", fontSize: 11.5 }}>
                后端未返回晋级检查；未显示 mock 检查
              </span>
            )}
          </div>
          {/* 审批表单（INV-5）：验证背书 + 理由必填，仅 ready 态显示（已晋级/blocked 不可填）。 */}
          {aState === "ready" && (
            <div
              data-promote-form
              style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 11 }}
            >
              <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <span style={{ fontSize: 10.5, color: "var(--desk-text-faint)" }}>
                  验证背书（endorsement_ref · verdict_id / 验证记录引用，必填）
                </span>
                <input
                  data-testid="promote-endorsement"
                  value={endorsementRef}
                  onChange={(e) => setEndorsementRef(e.target.value)}
                  placeholder="如 verdict_8f2a / 独立验证官记录引用"
                  style={inputStyle}
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <span style={{ fontSize: 10.5, color: "var(--desk-text-faint)" }}>
                  审批理由（reason，必填）
                </span>
                <input
                  data-testid="promote-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="为何放行晋级（留痕进审计）"
                  style={inputStyle}
                />
              </label>
            </div>
          )}
          <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
            <button
              type="button"
              onClick={() =>
                onApprove({ endorsementRef: endorsementRef.trim(), reason: reason.trim() })
              }
              disabled={aState !== "ready" || formIncomplete || !!approving}
              aria-disabled={aState !== "ready" || formIncomplete || !!approving}
              style={{
                fontFamily: "inherit",
                fontSize: 12,
                padding: "9px 16px",
                borderRadius: "var(--desk-radius)",
                ...(aState === "ready" && (formIncomplete || approving)
                  ? {
                      background: "var(--desk-hover)",
                      border: "1px solid var(--desk-border-strong)",
                      color: "var(--desk-text-faint)",
                      cursor: "not-allowed",
                    }
                  : approveStyle),
              }}
            >
              {approving ? "审批提交中…" : approvalLabel}
            </button>
            <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>
              {aState === "ready" && formIncomplete
                ? "须填验证背书 + 理由（INV-5：裸翻必拒）"
                : approvalHint}
            </span>
          </div>
          {/* §3 失败诚实呈现：缺背书/未审批/网络失败 → 显红，绝不伪「已晋级」绿。
              已晋级（promoted）后绝不并显红错（防绿/红矛盾态）。 */}
          {approveError && !promoted && (
            <div
              data-testid="promote-error"
              role="alert"
              style={{
                marginTop: 10,
                padding: "8px 11px",
                fontSize: 11.5,
                color: "var(--desk-danger)",
                border: "1px solid var(--desk-danger)",
                borderRadius: "var(--desk-radius-sm)",
                background: "color-mix(in srgb, var(--desk-danger) 8%, transparent)",
              }}
            >
              晋级失败（诚实呈现，未晋级）：{approveError}
            </div>
          )}
        </div>
      </div>

      {/* factor lifecycle linkage */}
      <div
        data-testid={liveMode ? "live-promo-factors-unavailable" : undefined}
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
          {liveMode ? "因子生命周期引用" : "本策略因子 · 生命周期联动"}
          {!liveMode && (
            <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-ghost)" }}>
              去因子台 ↗
            </span>
          )}
        </div>
        {liveMode ? (
          <div style={{ color: "var(--desk-text-muted)", fontSize: 11.5, lineHeight: 1.6 }}>
            promotion API 未返回因子 ID、权重、贡献或生命周期引用；此处不显示 mock 因子。
          </div>
        ) : (
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
                <span style={{ flex: 1, fontSize: 10, color: color(f.stateColor) }}>
                  {f.state}
                </span>
                <span
                  style={{
                    flex: 1,
                    textAlign: "right",
                    fontSize: 10.5,
                    color: "var(--desk-text-muted)",
                  }}
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
        )}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 11.5,
  padding: "6px 9px",
  borderRadius: "var(--desk-radius-sm)",
  border: "1px solid var(--desk-border-strong)",
  background: "var(--desk-card)",
  color: "var(--desk-text)",
};
