import { type CSSProperties } from "react";
import { type NodeView, catColor } from "./types";
import { type Viewport } from "./geometry";

/** MiniMap 尺寸（DC §4「MiniMap」158×104）。 */
export const MINIMAP_W = 158;
export const MINIMAP_H = 104;
const PAD = 8;

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** 所有节点的世界包围盒（无节点时退化为单位框）。 */
function nodeBounds(nodes: NodeView[]): Bounds {
  if (nodes.length === 0) return { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.x);
    minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + n.w);
    maxY = Math.max(maxY, n.y + 80);
  }
  return { minX, minY, maxX, maxY };
}

/**
 * 缩略图（DC §4「MiniMap」，受控）。
 * 节点缩略块用类别色；视口框依据当前 viewport + 画布可视尺寸推算。
 */
export function MiniMap({
  nodes,
  viewport,
  /** 画布可视区屏幕尺寸，用于换算视口框。 */
  viewSize,
}: {
  nodes: NodeView[];
  viewport: Viewport;
  viewSize: { w: number; h: number };
}) {
  const b = nodeBounds(nodes);
  const worldW = Math.max(1, b.maxX - b.minX);
  const worldH = Math.max(1, b.maxY - b.minY);
  // 等比缩放到 minimap 内容区（留 PAD 边距）。
  const scale = Math.min((MINIMAP_W - PAD * 2) / worldW, (MINIMAP_H - PAD * 2) / worldH);

  const toMini = (wx: number, wy: number): { x: number; y: number } => ({
    x: PAD + (wx - b.minX) * scale,
    y: PAD + (wy - b.minY) * scale,
  });

  // 视口框：屏幕 (0,0)~(viewSize) 反投影到世界，再投到 minimap。
  const vw0 = (0 - viewport.panX) / viewport.zoom;
  const vh0 = (0 - viewport.panY) / viewport.zoom;
  const vw1 = (viewSize.w - viewport.panX) / viewport.zoom;
  const vh1 = (viewSize.h - viewport.panY) / viewport.zoom;
  const tl = toMini(vw0, vh0);
  const br = toMini(vw1, vh1);

  const wrapStyle: CSSProperties = {
    position: "absolute",
    right: 12,
    bottom: 12,
    width: MINIMAP_W,
    height: MINIMAP_H,
    background: "var(--desk-minimap-bg)",
    border: "1px solid var(--desk-border)",
    borderRadius: "var(--desk-radius)",
    overflow: "hidden",
  };

  return (
    <div data-minimap style={wrapStyle} aria-label="缩略图">
      <svg width={MINIMAP_W} height={MINIMAP_H}>
        {nodes.map((n) => {
          const p = toMini(n.x, n.y);
          return (
            <rect
              key={n.id}
              x={p.x}
              y={p.y}
              width={Math.max(2, n.w * scale)}
              height={Math.max(2, 22 * scale)}
              rx={1}
              fill={catColor(n.cat)}
              opacity={0.7}
            />
          );
        })}
        <rect
          data-minimap-view
          x={tl.x}
          y={tl.y}
          width={Math.max(0, br.x - tl.x)}
          height={Math.max(0, br.y - tl.y)}
          fill="var(--desk-minimap-view)"
          stroke="var(--desk-accent)"
          strokeWidth={1}
        />
      </svg>
    </div>
  );
}
