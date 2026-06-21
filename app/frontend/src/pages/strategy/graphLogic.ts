/**
 * 策略台图逻辑（parseConsole.md §5 治理专章 + DC _validateGraph/_compat）。
 *
 * 三层硬强制（B6 不靠文案）：
 *  ① 删除门：locked 节点不可删（canDelete）。
 *  ② 校验门：到 exec 的路径必须经 Final Risk Gate（validateGraph error）。
 *  ③ 连线门：role==='exec' 入口来源非 approvedPortfolio → compat=bad（拒绝建边）。
 *
 * 全纯函数、无副作用、可单测。校验是渲染期 derived（非缓存 Toast）。
 */

import { type Compat } from "../../components/desk/canvas";
import { type DomainNode, type DomainEdge, type DomainPort } from "./mockGraph";

/** 校验问题级别。 */
export type IssueLevel = "error" | "warn";

export interface ValidationIssue {
  level: IssueLevel;
  /** 关联节点 id（点击定位）。 */
  nodeId?: string;
  text: string;
}

export interface GraphValidation {
  issues: ValidationIssue[];
  errorCount: number;
  warnCount: number;
  /** error 数为 0 即整图 ok。 */
  ok: boolean;
}

/** 端口兼容性结果（DC _compat 返回 { s, reason }）。 */
export interface CompatResult {
  s: Compat;
  reason: string;
}

const ADAPT: Record<string, string[]> = {
  modelScore: ["signalIntent"],
  factorPanel: ["modelScore"],
  panel: ["factorPanel"],
};
const WARN: Record<string, string[]> = {
  signalIntent: ["targetPortfolio"],
  targetPortfolio: ["signalIntent"],
};

/**
 * 连线门（B6 第三层）：判断 out 端口能否接到 in 端口。
 * role==='exec' 且来源 dt 非 approvedPortfolio → bad（执行入口必须经 Final Risk Gate）。
 */
export function compat(out: DomainPort | null, inp: DomainPort | null): CompatResult {
  if (!out || !inp) return { s: "?", reason: "未知" };
  // 连线门：执行入口必须经 Final Risk Gate（B6），不可绕过。
  if (inp.role === "exec" && out.dt !== "approvedPortfolio") {
    return { s: "bad", reason: "执行入口必须经 Final Risk Gate（B6），不可绕过" };
  }
  if (out.dt === inp.dt) {
    if (
      out.freq &&
      inp.freq &&
      out.freq !== inp.freq &&
      out.freq !== "—" &&
      inp.freq !== "—"
    ) {
      return out.freq === "D" && inp.freq === "W"
        ? { s: "adapt", reason: "日频→周频，需 Resample 聚合" }
        : { s: "warn", reason: "频率不一致：" + out.freq + "→" + inp.freq };
    }
    return { s: "ok", reason: "类型与频率一致" };
  }
  if ((ADAPT[out.dt] ?? []).includes(inp.dt)) {
    return { s: "adapt", reason: "可经适配节点转换 " + out.dt + "→" + inp.dt };
  }
  if ((WARN[out.dt] ?? []).includes(inp.dt)) {
    return { s: "warn", reason: "语义相近但不应直接相连" };
  }
  return { s: "bad", reason: "类型不兼容：" + out.dt + " → " + inp.dt };
}

/** 删除门（B6 第一层）：locked 节点不可删。 */
export function canDelete(node: DomainNode | undefined): boolean {
  return !!node && !node.locked;
}

function portOf(node: DomainNode | undefined, portId: string, dir: "in" | "out"): DomainPort | null {
  if (!node) return null;
  const arr = dir === "out" ? node.outs : node.ins;
  return arr.find((p) => p.id === portId) ?? null;
}

/**
 * 图校验（B6 第二层 + 必填端口 + 连线兼容性）。渲染期 derived。
 * 规则：
 *  ① 必填 in 端口未连 → warn。
 *  ② exec 有入边但无一来自 gate（approvedPortfolio 来源）→ error（违反 B6）。
 *  ③ 连线 compat=bad → error。
 */
export function validateGraph(
  nodes: Record<string, DomainNode>,
  edges: DomainEdge[],
): GraphValidation {
  const issues: ValidationIssue[] = [];

  // 入边索引：to.node → 已连的 in 端口集合。
  const connectedIn = new Map<string, Set<string>>();
  for (const e of edges) {
    if (!connectedIn.has(e.to.node)) connectedIn.set(e.to.node, new Set());
    connectedIn.get(e.to.node)!.add(e.to.port);
  }

  // ① 必填端口未连。
  for (const n of Object.values(nodes)) {
    const conn = connectedIn.get(n.id) ?? new Set<string>();
    for (const p of n.ins) {
      if (p.req && !conn.has(p.id)) {
        issues.push({ level: "warn", nodeId: n.id, text: `${n.title}：必填端口「${p.name}」未连接` });
      }
    }
  }

  // ② exec 入口必须经 Final Risk Gate（B6）。
  for (const e of edges) {
    const toNode = nodes[e.to.node];
    const toPort = portOf(toNode, e.to.port, "in");
    if (toPort?.role === "exec") {
      const fromPort = portOf(nodes[e.from.node], e.from.port, "out");
      if (fromPort?.dt !== "approvedPortfolio") {
        issues.push({
          level: "error",
          nodeId: e.to.node,
          text: "违反 B6：执行入口未经 Final Risk Gate（必须穿过最终风险闸门）",
        });
      }
    }
  }

  // ③ compat=bad 的连线。
  for (const e of edges) {
    const out = portOf(nodes[e.from.node], e.from.port, "out");
    const inp = portOf(nodes[e.to.node], e.to.port, "in");
    const c = compat(out, inp);
    if (c.s === "bad") {
      issues.push({ level: "error", nodeId: e.to.node, text: `连线不兼容：${c.reason}` });
    }
  }

  const errorCount = issues.filter((i) => i.level === "error").length;
  const warnCount = issues.filter((i) => i.level === "warn").length;
  return { issues, errorCount, warnCount, ok: errorCount === 0 };
}

/** 节点级校验（Inspector 校验 tab）：聚合该节点相关 issue。 */
export function nodeIssues(
  nodeId: string,
  validation: GraphValidation,
): ValidationIssue[] {
  return validation.issues.filter((i) => i.nodeId === nodeId);
}
