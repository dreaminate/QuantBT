/**
 * G2 共享画布引擎 · 纯几何（DC parseConsole §4「坐标系」+ §7.8「SVG 路径/锚点」）。
 *
 * 坐标系：节点存**世界坐标**；`#sb-pan` 用 `translate(panX,panY) scale(zoom)` origin 0 0。
 * 屏幕↔世界换算、端口锚点、贝塞尔连线、缩放 clamp、网格步长——全部纯函数，无副作用、可单测。
 */

/** 视口（pan + zoom），不进 Undo 栈。 */
export interface Viewport {
  panX: number;
  panY: number;
  zoom: number;
}

/** 平面坐标点（屏幕或世界，按上下文）。 */
export interface Point {
  x: number;
  y: number;
}

/** zoom 合法区间 [0.22, 2.2]（DC state.zoom 范围）。 */
export const ZOOM_MIN = 0.22;
export const ZOOM_MAX = 2.2;

/** 滚轮缩放因子（以光标为锚 ×1.12）。 */
export const WHEEL_ZOOM_FACTOR = 1.12;

/** 按钮缩放因子（以画布中心为锚 ×1.15）。 */
export const BUTTON_ZOOM_FACTOR = 1.15;

/** 端口锚点：第 0 口 top=38，逐口 +20（DC `top = 38 + i*20`）。 */
export const PORT_TOP_BASE = 38;
export const PORT_TOP_STEP = 20;

/** in 端口横偏 left:-7、out 端口横偏 right:-7（端口 14×14，圆心外探 7px）。 */
export const PORT_INSET = 7;

/** 网格基础步长（屏幕步长 = 22*zoom）。 */
export const GRID_BASE = 22;

/** 贝塞尔最小水平切入量。 */
export const EDGE_MIN_DX = 40;

/** 贝塞尔水平切入量系数（|bx-ax| 占比）。 */
export const EDGE_DX_RATIO = 0.42;

/** 把 zoom 夹到合法区间 [0.22, 2.2]。 */
export function clampZoom(zoom: number): number {
  if (zoom < ZOOM_MIN) return ZOOM_MIN;
  if (zoom > ZOOM_MAX) return ZOOM_MAX;
  return zoom;
}

/**
 * 屏幕坐标 → 世界坐标。
 * 屏幕点先减去平移、再除以缩放（`#sb-pan` 是先 translate 后 scale，逆变换反序）。
 */
export function screenToWorld(screen: Point, vp: Viewport): Point {
  return {
    x: (screen.x - vp.panX) / vp.zoom,
    y: (screen.y - vp.panY) / vp.zoom,
  };
}

/**
 * 世界坐标 → 屏幕坐标。
 * 世界点先乘缩放、再加平移（正变换：scale 后 translate）。
 */
export function worldToScreen(world: Point, vp: Viewport): Point {
  return {
    x: world.x * vp.zoom + vp.panX,
    y: world.y * vp.zoom + vp.panY,
  };
}

/**
 * 入端口锚点（世界坐标）。
 * 端口圆心在节点左边外探 PORT_INSET、纵向 `38 + i*20`。
 * @param nodeX 节点左上角世界 x
 * @param nodeY 节点左上角世界 y
 * @param index 第几个入端口（0 起）
 */
export function anchorIn(nodeX: number, nodeY: number, index: number): Point {
  return {
    x: nodeX - PORT_INSET,
    y: nodeY + PORT_TOP_BASE + index * PORT_TOP_STEP,
  };
}

/**
 * 出端口锚点（世界坐标）。
 * 端口圆心在节点右边外探 PORT_INSET、纵向 `38 + i*20`。
 * @param nodeX 节点左上角世界 x
 * @param nodeY 节点左上角世界 y
 * @param nodeW 节点宽度
 * @param index 第几个出端口（0 起）
 */
export function anchorOut(
  nodeX: number,
  nodeY: number,
  nodeW: number,
  index: number,
): Point {
  return {
    x: nodeX + nodeW + PORT_INSET,
    y: nodeY + PORT_TOP_BASE + index * PORT_TOP_STEP,
  };
}

/**
 * 两端水平切入的三次贝塞尔路径（DC `_path`）。
 * `dx = max(40, |bx-ax|*0.42)`，返回 `M ax,ay C ax+dx,ay bx-dx,by bx,by`。
 */
export function edgePath(a: Point, b: Point): string {
  const dx = Math.max(EDGE_MIN_DX, Math.abs(b.x - a.x) * EDGE_DX_RATIO);
  return `M ${a.x},${a.y} C ${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
}

/** 网格屏幕步长 = 22*zoom（随缩放联动）。 */
export function gridSize(zoom: number): number {
  return GRID_BASE * zoom;
}

/**
 * 以某屏幕锚点缩放：保持锚点下的世界坐标不动，求新的 pan。
 * 用于滚轮（锚=光标）与按钮（锚=画布中心）缩放。
 */
export function zoomAt(vp: Viewport, anchor: Point, factor: number): Viewport {
  const nextZoom = clampZoom(vp.zoom * factor);
  // 锚点世界坐标在缩放前后不变 → world = (anchor - pan)/zoom 求新 pan。
  const world = screenToWorld(anchor, vp);
  return {
    zoom: nextZoom,
    panX: anchor.x - world.x * nextZoom,
    panY: anchor.y - world.y * nextZoom,
  };
}
