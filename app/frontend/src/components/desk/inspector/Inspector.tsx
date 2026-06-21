import { type ReactNode } from "react";

/**
 * Inspector 容器（parseConsole.md §P5，w340）。
 * 受控：open / onToggle 由消费台持有；选中体头、tabs、tab 内容均作为槽。
 * 组件本身不持选中态——全部 props 传入。
 */

export interface InspectorProps {
  /** 标题（如选中节点名或「Inspector」）。 */
  title: ReactNode;
  /** 折叠回调（折叠条由上层 CollapsiblePanel 渲染；此处只出折叠按钮）。 */
  onCollapse?: () => void;
  /** 选中体头槽（类别色块 + 标题 + category/state/MOCK pills + desc）。 */
  selectionHead?: ReactNode;
  /** tab 段控槽（InspectorTabs 实例）。 */
  tabs?: ReactNode;
  /** 当前 tab 内容（参数行 / 端口卡 / 校验 / 版本）。 */
  children?: ReactNode;
}

export function Inspector({
  title,
  onCollapse,
  selectionHead,
  tabs,
  children,
}: InspectorProps) {
  return (
    <div
      data-inspector
      style={{
        width: 340,
        flex: "none",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: "var(--desk-panel)",
        borderLeft: "1px solid var(--desk-border)",
      }}
    >
      <div
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "9px 13px",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <span aria-hidden style={{ color: "var(--desk-info)" }}>
          ◰
        </span>
        <span style={{ color: "var(--desk-text)", fontSize: 14, fontWeight: 600 }}>
          {title}
        </span>
        <div style={{ flex: 1 }} />
        {onCollapse && (
          <button
            onClick={onCollapse}
            aria-label="折叠 Inspector"
            style={{
              fontFamily: "inherit",
              fontSize: 13,
              padding: "2px 6px",
              borderRadius: "var(--desk-radius-sm)",
              border: "none",
              background: "transparent",
              color: "var(--desk-text-dim)",
              cursor: "pointer",
            }}
          >
            ›
          </button>
        )}
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "12px 14px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {selectionHead}
        {tabs}
        <div>{children}</div>
      </div>
    </div>
  );
}
