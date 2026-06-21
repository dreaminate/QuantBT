/**
 * 策略台后端封装（S2 接真）。authFetch 自动带 Bearer。
 *
 * 对接 main.py 的 4 个端点：
 *  - POST /api/ide/strategies/{name}/validate     图校验（B6 三层，后端权威）
 *  - GET  /api/ide/strategies/{name}/versions     版本史（lineage append-only）
 *  - POST /api/ide/strategies/{name}/fork         策略级 Fork（血缘锚 lineage/ids.py）
 *  - GET  /api/ide/strategies/{name}/live_snapshot Live 只读聚合（A股 live 永拒，无下单面）
 *
 * 复用已有 编辑/run/promote/kill/publish 端点，不重造。
 */

import { authFetch } from "../../lib/auth";
import { type DomainNode, type DomainEdge } from "./mockGraph";

/** 后端 validate 返回（与 strategy_graph.validate_graph 一致）。 */
export interface BackendValidation {
  ok: boolean;
  errors: { nodeId?: string; text: string }[];
  warnings: { nodeId?: string; text: string }[];
}

/** 版本史条目（与 service.StrategyVersion 一致）。 */
export interface BackendVersion {
  version_id: string;
  strategy_id: string;
  owner_username: string;
  content_hash: string;
  parent_content_hash: string | null;
  parent_strategy_id: string | null;
  label: string;
  origin: "save" | "fork";
  created_at_utc: string;
}

/** Fork 结果（= StrategyFile）。 */
export interface BackendStrategy {
  strategy_id: string;
  owner_username: string;
  name: string;
  code: string;
  asset_class: string;
  description: string;
  updated_at_utc: string;
}

/** Live 只读快照（与 main.ide_strategy_live_snapshot 一致；无下单参数）。 */
export interface BackendLiveSnapshot {
  strategy_id: string;
  name: string;
  asset_class: string;
  live_allowed: boolean;
  reason?: string;
  runtime: string;
  readonly: boolean;
  positions: unknown[];
  recent_runs: {
    run_id: string;
    status: string;
    started_at_utc: string;
    finished_at_utc: string | null;
    duration_s: number;
    result_keys: string[];
  }[];
  run_count?: number;
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error((j as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** 序列化图为后端 validate 入参（只送校验需要的端口字段，避免冗余）。 */
export function serializeGraph(
  nodes: Record<string, DomainNode>,
  edges: DomainEdge[],
): { nodes: unknown[]; edges: unknown[] } {
  const ser = (p: DomainNode["ins"][number]) => ({
    id: p.id,
    name: p.name,
    dt: p.dt,
    freq: p.freq,
    req: p.req,
    role: p.role,
  });
  return {
    nodes: Object.values(nodes).map((n) => ({
      id: n.id,
      title: n.title,
      locked: n.locked,
      ins: n.ins.map(ser),
      outs: n.outs.map(ser),
    })),
    edges: edges.map((e) => ({ id: e.id, from: e.from, to: e.to })),
  };
}

export async function validateStrategyGraph(
  name: string,
  nodes: Record<string, DomainNode>,
  edges: DomainEdge[],
): Promise<BackendValidation> {
  const res = await authFetch(`/api/ide/strategies/${encodeURIComponent(name)}/validate`, {
    method: "POST",
    body: JSON.stringify(serializeGraph(nodes, edges)),
  });
  return unwrap<BackendValidation>(res);
}

export async function fetchStrategyVersions(name: string): Promise<BackendVersion[]> {
  const res = await authFetch(`/api/ide/strategies/${encodeURIComponent(name)}/versions`);
  return unwrap<BackendVersion[]>(res);
}

export async function forkStrategy(name: string, forkName?: string): Promise<BackendStrategy> {
  const res = await authFetch(`/api/ide/strategies/${encodeURIComponent(name)}/fork`, {
    method: "POST",
    body: JSON.stringify(forkName ? { fork_name: forkName } : {}),
  });
  return unwrap<BackendStrategy>(res);
}

export async function fetchLiveSnapshot(name: string): Promise<BackendLiveSnapshot> {
  const res = await authFetch(`/api/ide/strategies/${encodeURIComponent(name)}/live_snapshot`);
  return unwrap<BackendLiveSnapshot>(res);
}
