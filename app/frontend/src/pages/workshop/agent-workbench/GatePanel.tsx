import { useState } from "react";
import {
  ChatBubble,
  type SideEffect,
  type PermissionMode,
} from "../../../components/desk";
import { gateNeedsConfirm, isGovernanceWeakness } from "./permGate";

/**
 * 权限门面板（agentDeck.md gate block + 治理红线 §①②④⑤）。
 *
 * 复用 G3 ChatBubble 的 gate 变体渲染；本层负责**治理决策逻辑**：
 *  · gateNeedsConfirm：side_effect∈{realmoney,external} 时即便 bypass/auto 仍渲染确认变体
 *    （D-PERM 反例 / T-040 对抗 #1 #3）。
 *  · self-approve（批准且不再问 → auto）插入**二次确认步**（T-030 / T-041）。
 *  · side_effect 是受控真值（props，来自后端 tool_status），绝不前端伪造。
 *  · 治理弱点（真钱/血统/red）block 由 ChatBubble 强制常驻展开、不可折叠（R25）。
 */

export interface GatePanelProps {
  gateTool: string;
  /** 受控真值——来自后端 tool_status，不前端伪造。 */
  sideEffect: SideEffect;
  gateBlurb: string;
  /** 当前权限模式（决定 none 类是否需确认；不放宽治理轴）。 */
  permMode: PermissionMode;
  /** 显式治理弱点（血统/red 裁决）——与 realmoney/external 一样强制常驻展开。 */
  governanceWeakness?: boolean;
  /** 批准本次。 */
  onApproveOnce: () => void;
  /** 批准且升 auto（经二次确认后才真正升级）。 */
  onApproveAlways: () => void;
  /** 拒绝。 */
  onReject: () => void;
}

export function GatePanel(props: GatePanelProps) {
  const {
    gateTool,
    sideEffect,
    gateBlurb,
    permMode,
    governanceWeakness,
    onApproveOnce,
    onApproveAlways,
    onReject,
  } = props;

  // self-approve 二次确认步（T-030）：先 confirming，再真正 →auto。
  const [confirmingSelfApprove, setConfirmingSelfApprove] = useState(false);

  const needsConfirm = gateNeedsConfirm(permMode, sideEffect);
  const weakness = isGovernanceWeakness(sideEffect, governanceWeakness);

  // 不需确认（none + auto/bypass）：门自动放行，渲染只读「已自动放行」提示而非确认按钮。
  if (!needsConfirm) {
    return (
      <div
        data-gate-auto-pass="true"
        data-gate-side-effect={sideEffect}
        style={{ margin: "10px 0 10px 18px" }}
      >
        <div
          style={{
            fontSize: 11.5,
            color: "var(--desk-text-dim)",
            border: "1px solid var(--desk-border)",
            borderRadius: "var(--desk-radius)",
            padding: "8px 11px",
            background: "var(--desk-card)",
          }}
        >
          <span style={{ color: "var(--desk-success)" }}>● </span>
          {gateTool} · side_effect: none · {permMode} 模式自动放行（none 类工具不需逐次确认）。
        </div>
      </div>
    );
  }

  return (
    <div
      data-gate-panel
      data-gate-side-effect={sideEffect}
      data-gate-needs-confirm="true"
      style={{ marginLeft: 18 }}
    >
      <ChatBubble
        type="gate"
        gateTool={gateTool}
        sideEffect={sideEffect}
        gateBlurb={gateBlurb}
        governanceWeakness={weakness}
        onApproveOnce={onApproveOnce}
        onApproveAlways={() => setConfirmingSelfApprove(true)}
        onReject={onReject}
      />
      {confirmingSelfApprove && (
        <div
          data-self-approve-confirm
          style={{
            margin: "0 0 12px",
            border: "1px solid var(--desk-warning)",
            background:
              "color-mix(in srgb, var(--desk-warning) 10%, transparent)",
            borderRadius: "var(--desk-radius-lg)",
            padding: "10px 12px",
          }}
        >
          <div
            style={{
              fontSize: 11.5,
              color: "var(--desk-text-soft)",
              lineHeight: 1.55,
              marginBottom: 8,
            }}
          >
            二次确认：批准后 {gateTool} 将不再逐次询问，权限模式升为 <b>auto</b>。
            自我批准升级须你再点一次确认（不可一键自批）。
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              data-self-approve-yes
              onClick={() => {
                setConfirmingSelfApprove(false);
                onApproveAlways();
              }}
              style={{
                fontFamily: "inherit",
                fontSize: 11.5,
                padding: "5px 11px",
                borderRadius: "var(--desk-radius-sm)",
                border: "1px solid var(--desk-warning)",
                background: "transparent",
                color: "var(--desk-warning)",
                cursor: "pointer",
              }}
            >
              确认升级为 auto
            </button>
            <button
              data-self-approve-cancel
              onClick={() => setConfirmingSelfApprove(false)}
              style={{
                fontFamily: "inherit",
                fontSize: 11.5,
                padding: "5px 11px",
                borderRadius: "var(--desk-radius-sm)",
                border: "1px solid var(--desk-border)",
                background: "transparent",
                color: "var(--desk-text-dim)",
                cursor: "pointer",
              }}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
