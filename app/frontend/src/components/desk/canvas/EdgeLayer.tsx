import { type CSSProperties } from "react";
import {
  type NodeView,
  type EdgeView,
  type PortRef,
  edgeStroke,
} from "./types";
import { anchorIn, anchorOut, edgePath, type Point } from "./geometry";

/** 连线层渲染参数（世界坐标，置于 #sb-pan 内）。 */
export interface EdgeLayerProps {
  nodes: NodeView[];
  edges: EdgeView[];
  /** 选中的边 id 集合。 */
  selectedEdgeIds?: string[];
  /** Ghost 提议边（虚线预览）。 */
  ghostEdges?: EdgeView[];
  /** 正在拉的连线（起点 → 当前指针，世界坐标）。 */
  link?: { from: Point; to: Point } | null;
  onSelectEdge?: (id: string) => void;
}

/** out 端口锚点（世界坐标），找不到节点/端口返回 null。 */
function outAnchor(nodes: Map<string, NodeView>, ref: PortRef): Point | null {
  const n = nodes.get(ref.node);
  if (!n) return null;
  const i = n.outs.findIndex((p) => p.id === ref.port);
  if (i === -1) return null;
  return anchorOut(n.x, n.y, n.w, i);
}

/** in 端口锚点（世界坐标），找不到节点/端口返回 null。 */
function inAnchor(nodes: Map<string, NodeView>, ref: PortRef): Point | null {
  const n = nodes.get(ref.node);
  if (!n) return null;
  const i = n.ins.findIndex((p) => p.id === ref.port);
  if (i === -1) return null;
  return anchorIn(n.x, n.y, i);
}

/**
 * 连线 SVG 层（DC §4「连线」+ §7.8）。
 * edges 经 geometry.edgePath 成贝塞尔 path；ghost 边 dash；末端箭头 marker。
 * 受控：选中态由 props 传，点击上抛 onSelectEdge。
 */
export function EdgeLayer({
  nodes,
  edges,
  selectedEdgeIds = [],
  ghostEdges = [],
  link = null,
  onSelectEdge,
}: EdgeLayerProps) {
  const map = new Map(nodes.map((n) => [n.id, n]));
  const selSet = new Set(selectedEdgeIds);

  const svgStyle: CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    overflow: "visible",
    pointerEvents: "none",
  };

  return (
    <svg style={svgStyle} aria-hidden>
      <defs>
        <marker
          id="desk-edge-arrow"
          markerWidth={9}
          markerHeight={9}
          refX={7}
          refY={3}
          orient="auto"
          markerUnits="userSpaceOnUse"
        >
          <path d="M0,0 L7,3 L0,6 Z" fill="var(--desk-edge-arrow)" />
        </marker>
      </defs>

      {edges.map((e) => {
        const a = outAnchor(map, e.from);
        const b = inAnchor(map, e.to);
        if (!a || !b) return null;
        const sel = selSet.has(e.id);
        const adapt = e.compat === "adapt";
        return (
          <path
            key={e.id}
            d={edgePath(a, b)}
            fill="none"
            stroke={edgeStroke(e.compat, sel)}
            strokeWidth={sel ? 2.6 : 1.8}
            strokeDasharray={adapt ? "6 4" : undefined}
            markerEnd="url(#desk-edge-arrow)"
            style={{ pointerEvents: "stroke", cursor: "pointer" }}
            data-edge-id={e.id}
            onClick={() => onSelectEdge?.(e.id)}
          />
        );
      })}

      {ghostEdges.map((e) => {
        const a = outAnchor(map, e.from);
        const b = inAnchor(map, e.to);
        if (!a || !b) return null;
        return (
          <path
            key={`ghost-${e.id}`}
            d={edgePath(a, b)}
            fill="none"
            stroke="var(--desk-ghost)"
            strokeWidth={2}
            strokeDasharray="6 5"
            opacity={0.8}
            data-ghost-edge-id={e.id}
          />
        );
      })}

      {link && (
        <path
          d={edgePath(link.from, link.to)}
          fill="none"
          stroke="var(--desk-accent)"
          strokeWidth={2}
          strokeDasharray="4 4"
          data-link-preview
        />
      )}
    </svg>
  );
}
