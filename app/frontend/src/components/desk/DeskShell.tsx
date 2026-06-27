import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
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
  const [leftWidth, setLeftWidth] = usePaneWidth(desk, "left", 316);
  const [rightWidth, setRightWidth] = usePaneWidth(desk, "right", 340);
  const drag = useRef<DragState | null>(null);

  const setPaneWidth = (side: PaneSide, width: number) => {
    if (side === "left") setLeftWidth(width);
    else setRightWidth(width);
  };

  function beginResize(side: PaneSide, event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    drag.current = {
      side,
      startX: event.clientX,
      startWidth: side === "left" ? leftWidth : rightWidth,
    };
  }

  useEffect(() => {
    function onMove(event: PointerEvent) {
      const active = drag.current;
      if (!active) return;
      const delta = active.side === "left"
        ? event.clientX - active.startX
        : active.startX - event.clientX;
      setPaneWidth(active.side, clampPaneWidth(active.startWidth + delta));
    }
    function onUp() {
      drag.current = null;
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  });

  const rootStyle: CSSProperties & Record<string, string | number> = {
    "--desk-left-pane-width": `${leftWidth}px`,
    "--desk-right-pane-width": `${rightWidth}px`,
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    background: "var(--desk-bg)",
    color: "var(--desk-text)",
    fontFamily: "var(--desk-mono)",
    fontSize: 13,
    lineHeight: 1.5,
    userSelect: "none",
  };

  return (
    <div
      className="desk-root"
      data-desk={desk}
      style={rootStyle}
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
          {left && (
            <PaneSplitter
              side="left"
              width={leftWidth}
              onPointerDown={beginResize}
              onStep={(delta) => setLeftWidth(clampPaneWidth(leftWidth + delta))}
            />
          )}
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
          {right && (
            <PaneSplitter
              side="right"
              width={rightWidth}
              onPointerDown={beginResize}
              onStep={(delta) => setRightWidth(clampPaneWidth(rightWidth + delta))}
            />
          )}
          {right}
        </div>
        {dock}
      </div>
    </div>
  );
}

type PaneSide = "left" | "right";

type DragState = {
  side: PaneSide;
  startX: number;
  startWidth: number;
};

const PANE_MIN = 220;
const PANE_MAX = 560;

function paneStorageKey(desk: DeskKey, side: PaneSide): string {
  return `qb-desk-pane-width:${desk}:${side}`;
}

function clampPaneWidth(width: number): number {
  return Math.max(PANE_MIN, Math.min(PANE_MAX, Math.round(width)));
}

function readStoredPaneWidth(desk: DeskKey, side: PaneSide, fallback: number): number {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(paneStorageKey(desk, side));
  const parsed = raw === null ? NaN : Number(raw);
  return Number.isFinite(parsed) ? clampPaneWidth(parsed) : fallback;
}

function usePaneWidth(
  desk: DeskKey,
  side: PaneSide,
  fallback: number,
): [number, (next: number) => void] {
  const [width, setWidth] = useState(() => readStoredPaneWidth(desk, side, fallback));

  useEffect(() => {
    setWidth(readStoredPaneWidth(desk, side, fallback));
  }, [desk, fallback, side]);

  function update(next: number) {
    const clamped = clampPaneWidth(next);
    setWidth(clamped);
    try {
      window.localStorage.setItem(paneStorageKey(desk, side), String(clamped));
    } catch {
      /* noop */
    }
  }

  return [width, update];
}

function PaneSplitter({
  side,
  width,
  onPointerDown,
  onStep,
}: {
  side: PaneSide;
  width: number;
  onPointerDown: (side: PaneSide, event: ReactPointerEvent<HTMLDivElement>) => void;
  onStep: (delta: number) => void;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={side === "left" ? "调整左侧面板宽度" : "调整右侧面板宽度"}
      aria-valuemin={PANE_MIN}
      aria-valuemax={PANE_MAX}
      aria-valuenow={width}
      tabIndex={0}
      data-pane-splitter={side}
      onPointerDown={(event) => onPointerDown(side, event)}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          onStep(side === "left" ? -16 : 16);
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          onStep(side === "left" ? 16 : -16);
        }
      }}
      style={{
        flex: "none",
        width: 7,
        marginLeft: side === "left" ? -4 : 0,
        marginRight: side === "right" ? -4 : 0,
        cursor: "col-resize",
        touchAction: "none",
        zIndex: 10,
        background: "transparent",
        borderLeft: "1px solid transparent",
        borderRight: "1px solid transparent",
      }}
      title="拖动调整面板宽度"
    />
  );
}
