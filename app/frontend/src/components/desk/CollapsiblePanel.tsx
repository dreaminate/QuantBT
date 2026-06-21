import { type ReactNode } from "react";

/** 左/右可折叠面板：展开显 children，折叠成 32px 竖排标签条。 */
export function CollapsiblePanel({
  open,
  onToggle,
  side,
  width = 316,
  label,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  side: "left" | "right";
  width?: number;
  label: string;
  children: ReactNode;
}) {
  const edge =
    side === "left"
      ? { borderRight: "1px solid var(--desk-border)" }
      : { borderLeft: "1px solid var(--desk-border)" };
  if (!open) {
    return (
      <button
        onClick={onToggle}
        title={`展开${label}`}
        style={{
          flex: "none",
          width: 32,
          background: "var(--desk-card)",
          border: "none",
          ...edge,
          color: "var(--desk-text-muted)",
          cursor: "pointer",
          writingMode: "vertical-rl",
          letterSpacing: 1,
          fontSize: 11,
          fontFamily: "inherit",
        }}
      >
        {side === "left" ? `${label} ›` : `‹ ${label}`}
      </button>
    );
  }
  return (
    <aside
      style={{
        flex: "none",
        width,
        display: "flex",
        flexDirection: "column",
        background: "var(--desk-panel)",
        ...edge,
        minHeight: 0,
      }}
    >
      {children}
    </aside>
  );
}
