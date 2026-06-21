import { type CSSProperties, type ReactNode } from "react";

/** banner 语气：diff（琥珀）/ lineage 血缘（琥珀）/ info（蓝）。 */
export type BannerTone = "diff" | "lineage" | "info";

const TONE: Record<BannerTone, { border: string; color: string }> = {
  diff: { border: "var(--desk-warning)", color: "var(--desk-warning)" },
  lineage: { border: "var(--desk-warning)", color: "var(--desk-warning)" },
  info: { border: "var(--desk-info)", color: "var(--desk-info)" },
};

/**
 * 画布顶部居中浮层胶囊（DC §4 diff banner / 血缘 banner）。
 * 受控：内容 + 可选「退出/清除」动作上抛回调。
 */
export function CanvasBanner({
  tone = "info",
  children,
  actionLabel,
  onAction,
}: {
  tone?: BannerTone;
  children: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
}) {
  const t = TONE[tone];
  const wrapStyle: CSSProperties = {
    position: "absolute",
    top: 12,
    left: "50%",
    transform: "translateX(-50%)",
    display: "inline-flex",
    alignItems: "center",
    gap: 10,
    padding: "6px 14px",
    background: "var(--desk-card)",
    border: `1px solid ${t.border}`,
    borderRadius: "var(--desk-radius-pill)",
    color: t.color,
    fontSize: 11,
    whiteSpace: "nowrap",
    zIndex: 5,
  };
  return (
    <div data-canvas-banner style={wrapStyle}>
      <span>{children}</span>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          style={{
            fontFamily: "inherit",
            fontSize: 10.5,
            padding: "2px 8px",
            background: "transparent",
            border: `1px solid ${t.border}`,
            borderRadius: "var(--desk-radius-sm)",
            color: t.color,
            cursor: "pointer",
          }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
