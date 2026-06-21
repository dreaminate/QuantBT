import { type CSSProperties, type ReactNode } from "react";

const ctrlBtn: CSSProperties = {
  width: 26,
  height: 26,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: "inherit",
  fontSize: 13,
  background: "var(--desk-soft-btn)",
  border: "1px solid var(--desk-border)",
  borderRadius: "var(--desk-radius-sm)",
  color: "var(--desk-text-soft)",
  cursor: "pointer",
};

const ctrlBtnW: CSSProperties = {
  height: 26,
  padding: "0 9px",
  display: "inline-flex",
  alignItems: "center",
  fontFamily: "inherit",
  fontSize: 10.5,
  background: "var(--desk-soft-btn)",
  border: "1px solid var(--desk-border)",
  borderRadius: "var(--desk-radius-sm)",
  color: "var(--desk-text-dim)",
  cursor: "pointer",
};

function CtrlBtn({
  onClick,
  title,
  wide = false,
  children,
}: {
  onClick: () => void;
  title: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <button type="button" title={title} aria-label={title} style={wide ? ctrlBtnW : ctrlBtn} onClick={onClick}>
      {children}
    </button>
  );
}

/**
 * 画布控件条（DC §1 工具条左段，受控）。
 * zoom −/%/＋ · 适应 · 自动布局；全部上抛回调，不内置缩放逻辑。
 */
export function CanvasControls({
  zoom,
  onZoomOut,
  onZoomIn,
  onFit,
  onAutoLayout,
}: {
  zoom: number;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onFit: () => void;
  onAutoLayout: () => void;
}) {
  const pct = `${Math.round(zoom * 100)}%`;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <CtrlBtn title="缩小" onClick={onZoomOut}>
        −
      </CtrlBtn>
      <span
        data-zoom-pct
        style={{
          minWidth: 40,
          textAlign: "center",
          fontSize: 10.5,
          color: "var(--desk-text-dim)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {pct}
      </span>
      <CtrlBtn title="放大" onClick={onZoomIn}>
        ＋
      </CtrlBtn>
      <CtrlBtn title="适应" wide onClick={onFit}>
        适应
      </CtrlBtn>
      <CtrlBtn title="自动布局" wide onClick={onAutoLayout}>
        ⧉ 自动布局
      </CtrlBtn>
    </div>
  );
}
