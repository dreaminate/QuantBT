/**
 * G2 画布引擎共享类型 + 类别/兼容性 → token 映射（DC parseConsole §3.3/§7.1）。
 * 引擎只渲染 + 上抛事件，**不持业务状态**；这里只放渲染所需的视图模型类型。
 */

/** 节点类别（DC NodeCat）。 */
export type NodeCat =
  | "research"
  | "scope"
  | "data"
  | "factor"
  | "model"
  | "signal"
  | "position"
  | "risk"
  | "exec"
  | "eval";

/** 节点运行态（DC NodeState）。 */
export type NodeState =
  | "idle"
  | "dirty"
  | "validating"
  | "valid"
  | "queued"
  | "running"
  | "succeeded"
  | "warning"
  | "invalid"
  | "failed"
  | "stale";

/** 连线兼容性 5 态（DC Compat）。 */
export type Compat = "ok" | "adapt" | "warn" | "bad" | "?";

/** 端口视图模型（引擎只需 id + 名称用于渲染/锚点）。 */
export interface PortView {
  id: string;
  name: string;
}

/** 节点视图模型（受控：坐标/选中由消费方持有并下传）。 */
export interface NodeView {
  id: string;
  cat: NodeCat;
  title: string;
  /** 世界坐标左上角 x。 */
  x: number;
  /** 世界坐标左上角 y。 */
  y: number;
  /** 节点宽度（168~184）。 */
  w: number;
  state: NodeState;
  /** 卡片正文行。 */
  lines: string[];
  ins: PortView[];
  outs: PortView[];
  /** 可选 badge 文案（如「← 因子台」）。 */
  badge?: string;
  /** Final Risk Gate 等不可删节点。 */
  locked?: boolean;
}

/** 端口引用（节点 id + 端口 id）。 */
export interface PortRef {
  node: string;
  port: string;
}

/** 连线视图模型。 */
export interface EdgeView {
  id: string;
  from: PortRef;
  to: PortRef;
  compat: Compat;
}

/** 框选矩形（屏幕坐标）。 */
export interface MarqueeRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 类别色（DC CAT，§7.1 1041 行）→ --desk-* token。 */
const CAT_VAR: Record<NodeCat, string> = {
  research: "var(--desk-info)",
  scope: "var(--desk-info)",
  eval: "var(--desk-info)",
  data: "var(--desk-cat-data)",
  factor: "var(--desk-success)",
  model: "var(--desk-ghost)",
  signal: "var(--desk-warning)",
  position: "var(--desk-cat-position)",
  risk: "var(--desk-danger)",
  exec: "var(--desk-accent)",
};

/** 取节点类别色（token 字符串）。 */
export function catColor(cat: NodeCat): string {
  return CAT_VAR[cat];
}

/** state 色（DC STATE，§7.1 1001 行）→ --desk-* token。 */
const STATE_VAR: Record<NodeState, string> = {
  idle: "var(--desk-text-faint)",
  dirty: "var(--desk-warning)",
  warning: "var(--desk-warning)",
  validating: "var(--desk-info)",
  queued: "var(--desk-info)",
  valid: "var(--desk-success)",
  succeeded: "var(--desk-success)",
  running: "var(--desk-accent)",
  invalid: "var(--desk-danger)",
  failed: "var(--desk-danger)",
  stale: "var(--desk-text-muted)",
};

/** 取节点 state 色（token 字符串）。 */
export function stateColor(state: NodeState): string {
  return STATE_VAR[state];
}

/** running 态走 StatusDot 呼吸动画。 */
export function isPulsing(state: NodeState): boolean {
  return state === "running";
}

/** 兼容性色（DC _compatColor）→ --desk-* token。端口 hover 着色用。 */
const COMPAT_VAR: Record<Compat, string> = {
  ok: "var(--desk-success)",
  adapt: "var(--desk-info)",
  warn: "var(--desk-warning)",
  bad: "var(--desk-danger)",
  "?": "var(--desk-text-muted)",
};

/** 取兼容性色（token 字符串）。 */
export function compatColor(compat: Compat): string {
  return COMPAT_VAR[compat];
}

/** 连线 stroke 色（DC _edgeStroke）→ --desk-* token。选中优先于 compat。 */
const EDGE_STROKE_VAR: Record<Compat, string> = {
  ok: "var(--desk-edge-ok)",
  adapt: "var(--desk-edge-adapt)",
  warn: "var(--desk-edge-warn)",
  bad: "var(--desk-edge-bad)",
  "?": "var(--desk-edge-idle)",
};

/** 取连线 stroke 色；selected 时返回 accent。 */
export function edgeStroke(compat: Compat, selected: boolean): string {
  return selected ? "var(--desk-accent)" : EDGE_STROKE_VAR[compat];
}
