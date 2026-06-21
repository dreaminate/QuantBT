import {
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
  type WheelEvent,
  useRef,
} from "react";
import { NodeCard } from "./NodeCard";
import { EdgeLayer } from "./EdgeLayer";
import {
  type NodeView,
  type EdgeView,
  type PortRef,
  type MarqueeRect,
} from "./types";
import {
  type Viewport,
  type Point,
  clampZoom,
  gridSize,
  zoomAt,
  WHEEL_ZOOM_FACTOR,
} from "./geometry";

/** 选中态（节点 + 边 id 集合）。 */
export interface Selection {
  nodeIds: string[];
  edgeIds: string[];
}

export interface GraphCanvasProps {
  nodes: NodeView[];
  edges: EdgeView[];
  pan: { x: number; y: number };
  zoom: number;
  selection: Selection;
  /** Ghost 提议边（虚线预览）。 */
  ghostEdges?: EdgeView[];
  /** 正在拉的连线（起点 → 当前指针，世界坐标）。 */
  link?: { from: Point; to: Point } | null;
  /** 进行中的框选矩形（屏幕坐标）。 */
  marquee?: MarqueeRect | null;
  /** 顶部浮层（diff/血缘 banner、MiniMap、图例由消费方塞 children）。 */
  children?: ReactNode;

  onPan: (pan: { x: number; y: number }) => void;
  onZoom: (vp: Viewport) => void;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  /** 节点拖拽（head pointerdown 起，消费方在 locked 时自行忽略）。 */
  onNodeMove: (id: string, e: PointerEvent<HTMLDivElement>) => void;
  /** 端口起/落连线。 */
  onConnect: (ref: PortRef, side: "in" | "out", e: PointerEvent<HTMLDivElement>) => void;
  /** Shift+空白拖拽 → 框选（屏幕坐标矩形）。 */
  onMarquee: (rect: MarqueeRect) => void;
}

/**
 * 共享画布引擎（DC §1/§4，受控）。
 * #sb-pan transform translate(panX,panY) scale(zoom) origin 0 0；点阵网格随 pan/zoom 联动；
 * pointerdown 空白→平移、Shift→框选 marquee；wheel 以光标为锚 ×1.12 缩放。
 * locked 规则与节点删除由消费方处理——引擎只渲染 + 上抛事件，不内置业务。
 */
export function GraphCanvas({
  nodes,
  edges,
  pan,
  zoom,
  selection,
  ghostEdges = [],
  link = null,
  marquee = null,
  children,
  onPan,
  onZoom,
  onSelectNode,
  onSelectEdge,
  onNodeMove,
  onConnect,
  onMarquee,
}: GraphCanvasProps) {
  const surfRef = useRef<HTMLDivElement | null>(null);
  // 平移/框选的活动手势（指针锚 + 起始 pan）。
  const drag = useRef<
    | { mode: "pan"; startX: number; startY: number; panX: number; panY: number }
    | { mode: "marquee"; startX: number; startY: number }
    | null
  >(null);

  const vp: Viewport = { panX: pan.x, panY: pan.y, zoom };

  /** 取相对画布面左上角的屏幕坐标。 */
  function localPoint(e: { clientX: number; clientY: number }): Point {
    const r = surfRef.current?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  }

  function onSurfacePointerDown(e: PointerEvent<HTMLDivElement>): void {
    // 仅响应画布面自身（非冒泡自节点/端口）。
    if (e.target !== e.currentTarget) return;
    const p = localPoint(e);
    surfRef.current?.setPointerCapture?.(e.pointerId);
    if (e.shiftKey) {
      drag.current = { mode: "marquee", startX: p.x, startY: p.y };
    } else {
      drag.current = { mode: "pan", startX: p.x, startY: p.y, panX: pan.x, panY: pan.y };
    }
  }

  function onSurfacePointerMove(e: PointerEvent<HTMLDivElement>): void {
    const d = drag.current;
    if (!d) return;
    const p = localPoint(e);
    if (d.mode === "pan") {
      onPan({ x: d.panX + (p.x - d.startX), y: d.panY + (p.y - d.startY) });
    } else {
      const x = Math.min(d.startX, p.x);
      const y = Math.min(d.startY, p.y);
      onMarquee({ x, y, w: Math.abs(p.x - d.startX), h: Math.abs(p.y - d.startY) });
    }
  }

  function onSurfacePointerUp(e: PointerEvent<HTMLDivElement>): void {
    drag.current = null;
    surfRef.current?.releasePointerCapture?.(e.pointerId);
  }

  function onWheel(e: WheelEvent<HTMLDivElement>): void {
    const anchor = localPoint(e);
    const factor = e.deltaY < 0 ? WHEEL_ZOOM_FACTOR : 1 / WHEEL_ZOOM_FACTOR;
    onZoom(zoomAt(vp, anchor, factor));
  }

  const gs = gridSize(clampZoom(zoom));
  const surfStyle: CSSProperties = {
    position: "relative",
    flex: 1,
    minHeight: 0,
    overflow: "hidden",
    background: "var(--desk-canvas)",
    cursor: "grab",
    // 点阵网格：radial-gradient，size = 22*zoom，随 pan/zoom 联动。
    backgroundImage: "radial-gradient(var(--desk-grid-dot) 1px, transparent 1px)",
    backgroundSize: `${gs}px ${gs}px`,
    backgroundPosition: `${pan.x}px ${pan.y}px`,
  };

  const panStyle: CSSProperties = {
    position: "absolute",
    inset: 0,
    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
    transformOrigin: "0 0",
  };

  const selNodeSet = new Set(selection.nodeIds);

  return (
    <div
      ref={surfRef}
      data-graph-surface
      style={surfStyle}
      onPointerDown={onSurfacePointerDown}
      onPointerMove={onSurfacePointerMove}
      onPointerUp={onSurfacePointerUp}
      onWheel={onWheel}
    >
      {/* 浮层（banner / MiniMap / 图例）：屏幕坐标，不随 pan 变换 */}
      {children}

      {/* 框选矩形（屏幕坐标） */}
      {marquee && (
        <div
          data-marquee
          style={{
            position: "absolute",
            left: marquee.x,
            top: marquee.y,
            width: marquee.w,
            height: marquee.h,
            border: "1px dashed var(--desk-info)",
            background: "var(--desk-minimap-view)",
            pointerEvents: "none",
          }}
        />
      )}

      {/* #sb-pan：世界坐标层 */}
      <div id="sb-pan" data-pan-layer style={panStyle}>
        <EdgeLayer
          nodes={nodes}
          edges={edges}
          selectedEdgeIds={selection.edgeIds}
          ghostEdges={ghostEdges}
          link={link}
          onSelectEdge={onSelectEdge}
        />
        {nodes.map((n) => (
          <NodeCard
            key={n.id}
            node={n}
            selected={selNodeSet.has(n.id)}
            onSelect={onSelectNode}
            onHeadPointerDown={onNodeMove}
            onPortPointerDown={onConnect}
          />
        ))}
      </div>
    </div>
  );
}

/** marquee 屏幕矩形是否覆盖某节点（消费方做框选命中可复用）。 */
export function nodeInMarquee(node: NodeView, rect: MarqueeRect, vp: Viewport): boolean {
  // 节点世界包围盒投到屏幕，与 marquee 求相交。
  const a = { x: node.x * vp.zoom + vp.panX, y: node.y * vp.zoom + vp.panY };
  const b = {
    x: (node.x + node.w) * vp.zoom + vp.panX,
    y: (node.y + 80) * vp.zoom + vp.panY,
  };
  return a.x < rect.x + rect.w && b.x > rect.x && a.y < rect.y + rect.h && b.y > rect.y;
}
