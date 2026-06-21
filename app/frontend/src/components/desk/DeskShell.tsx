import { type ReactNode } from "react";
import { type DeskKey } from "./DeskTopBar";

/**
 * 暗色台四栏壳（G1 d11d1426）：顶栏 + 主行(左/中/右) + 底 dock。
 * per-desk accent 由 data-desk 注入；折叠由各 slot（CollapsiblePanel）自理。
 */
export function DeskShell({
  desk,
  topbar,
  left,
  center,
  right,
  dock,
}: {
  desk: DeskKey;
  topbar: ReactNode;
  left?: ReactNode;
  center: ReactNode;
  right?: ReactNode;
  dock?: ReactNode;
}) {
  return (
    <div
      className="desk-root"
      data-desk={desk}
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "var(--desk-bg)",
        color: "var(--desk-text)",
        fontFamily: "var(--desk-mono)",
        fontSize: 13,
        lineHeight: 1.5,
        userSelect: "none",
      }}
    >
      {topbar}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
          {left}
          <main
            style={{
              flex: 1,
              minWidth: 0,
              display: "flex",
              flexDirection: "column",
              background: "var(--desk-canvas)",
            }}
          >
            {center}
          </main>
          {right}
        </div>
        {dock}
      </div>
    </div>
  );
}
