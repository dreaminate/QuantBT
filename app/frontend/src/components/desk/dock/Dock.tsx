import { type ReactNode } from "react";

/**
 * 底部工作台 dock 容器（parseConsole.md §P6，h228）。
 * 受控：tabs 槽 + 折叠回调 + 内容槽由消费台注入；组件不持 tab 态。
 */

export interface DockProps {
  /** tab 段控槽（DockTabs 实例）。 */
  tabs?: ReactNode;
  /** 右侧附加槽（MOCK pill 等）。 */
  right?: ReactNode;
  /** 折叠回调（折叠后由上层渲染折叠条）。 */
  onCollapse?: () => void;
  /** 当前 tab 内容。 */
  children?: ReactNode;
}

export function Dock({ tabs, right, onCollapse, children }: DockProps) {
  return (
    <div
      data-dock
      style={{
        flex: "none",
        height: 228,
        display: "flex",
        flexDirection: "column",
        background: "var(--desk-soft-btn)",
        borderTop: "1px solid var(--desk-border)",
      }}
    >
      <div
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
          borderBottom: "1px solid var(--desk-border)",
          background: "var(--desk-card)",
        }}
      >
        {tabs}
        <div style={{ flex: 1 }} />
        {right}
        {onCollapse && (
          <button
            onClick={onCollapse}
            aria-label="收起工作台"
            style={{
              fontFamily: "inherit",
              fontSize: 12,
              padding: "2px 8px",
              borderRadius: "var(--desk-radius-sm)",
              border: "none",
              background: "transparent",
              color: "var(--desk-text-dim)",
              cursor: "pointer",
            }}
          >
            ▾
          </button>
        )}
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "auto",
          padding: "11px 14px",
        }}
      >
        {children}
      </div>
    </div>
  );
}
