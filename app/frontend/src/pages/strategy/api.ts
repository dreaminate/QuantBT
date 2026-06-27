/**
 * 策略台真实后端封装（S2）。authFetch 自动带 Bearer。
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
import { type EdgeView, type NodeView } from "../../components/desk/canvas";
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

export interface ResearchGraphCanvasProjection {
  total: number;
  limit: number;
  filters: Record<string, string>;
  read_only: boolean;
  source_projection_refs: string[];
  nodes: NodeView[];
  edges: EdgeView[];
}

export interface ResearchGraphCanvasProjectionParams {
  limit?: number;
  qro_type?: string;
  owner?: string;
  market?: string;
  universe?: string;
  definition_status?: string;
  evidence_status?: string;
  runtime_status?: string;
  lineage_token?: string;
}

export interface CanvasAssetMutationRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  target_asset_type: string;
  target_ref: string;
  field_path: string;
  operation: "set_ref" | "set_hash" | "append_ref";
  canonical_command_ref: string;
  audit_ref: string;
  value_ref?: string;
  value_hash?: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface CanvasAssetMutationResponse {
  accepted: boolean;
  command_type: string;
  mutation_command_id: string;
  qro_command_id: string;
  qro_id: string;
  qro_version: number;
  projection_ref: string;
  updated_field_path: string;
  recorded_by: string;
}

export interface CanvasLayoutRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  target_asset_type: string;
  target_ref: string;
  node_id: string;
  x: number;
  y: number;
  w: number;
  canonical_command_ref: string;
  audit_ref: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface CanvasLayoutResponse {
  accepted: boolean;
  command_type: "record_canvas_layout";
  layout_command_id: string;
  layout_ref: string;
  layout_hash: string;
  mutation_command_id: string;
  qro_command_id: string;
  qro_id: string;
  qro_version: number;
  projection_ref: string;
  updated_field_path: string;
  recorded_by: string;
}

export interface GraphEdgeRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  from_qro_id: string;
  to_qro_id: string;
  relation_type: string;
  canonical_command_ref: string;
  audit_ref: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface GraphEdgeResponse {
  accepted: boolean;
  command_type: "record_graph_edge";
  graph_edge_command_id: string;
  edge_ref: string;
  from_qro_id: string;
  to_qro_id: string;
  relation_type: string;
  projection_edge_id: string;
  recorded_by: string;
}

export interface GraphEdgeDeletionRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  edge_ref: string;
  canonical_command_ref: string;
  audit_ref: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface GraphEdgeDeletionResponse {
  accepted: boolean;
  command_type: "delete_graph_edge";
  graph_edge_deletion_command_id: string;
  edge_ref: string;
  deletion_ref: string;
  projection_edge_id: string;
  recorded_by: string;
}

export interface QROTombstoneRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  qro_id: string;
  canonical_command_ref: string;
  audit_ref: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface QROTombstoneResponse {
  accepted: boolean;
  command_type: "tombstone_qro";
  qro_tombstone_command_id: string;
  qro_id: string;
  tombstone_ref: string;
  projection_node_id: string;
  recorded_by: string;
}

export interface GraphPatchApplicationRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  target_qro_id: string;
  patch_kind: "ghost" | "auto";
  patch_ref: string;
  patch_hash: string;
  canonical_command_ref: string;
  audit_ref: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface GraphPatchApplicationResponse {
  accepted: boolean;
  command_type: "apply_graph_patch";
  patch_application_command_id: string;
  patch_qro_command_id: string;
  graph_edge_command_id: string;
  application_ref: string;
  patch_qro_id: string;
  target_qro_id: string;
  patch_kind: "ghost" | "auto";
  projection_node_id: string;
  projection_edge_id: string;
  recorded_by: string;
}

export interface CanvasParameterValueRequest {
  command_ref: string;
  source_desk: string;
  actor_source: "user_manual" | "agent" | "user_confirmed_agent" | "scheduled_agent";
  target_qro_id: string;
  target_asset_type: string;
  param_key: string;
  param_value: string;
  canonical_command_ref: string;
  audit_ref: string;
  evidence_refs?: string[];
  tool_record_refs?: string[];
}

export interface CanvasParameterValueResponse {
  accepted: boolean;
  command_type: "set_canvas_parameter";
  parameter_command_id: string;
  qro_command_id: string;
  qro_id: string;
  qro_version: number;
  projection_ref: string;
  param_key: string;
  parameter_ref: string;
  value_hash: string;
  updated_field_path: string;
  recorded_by: string;
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

export async function fetchResearchGraphCanvasProjection(
  params: ResearchGraphCanvasProjectionParams = {},
): Promise<ResearchGraphCanvasProjection> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const suffix = query.toString();
  const res = await authFetch(`/api/research-os/graph/canvas_projection${suffix ? `?${suffix}` : ""}`);
  return unwrap<ResearchGraphCanvasProjection>(res);
}

export async function executeResearchGraphCanvasAssetMutation(
  payload: CanvasAssetMutationRequest,
): Promise<CanvasAssetMutationResponse> {
  const res = await authFetch("/api/research-os/graph/canvas_asset_mutations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<CanvasAssetMutationResponse>(res);
}

export async function recordResearchGraphCanvasLayout(
  payload: CanvasLayoutRequest,
): Promise<CanvasLayoutResponse> {
  const res = await authFetch("/api/research-os/graph/canvas_layouts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<CanvasLayoutResponse>(res);
}

export async function recordResearchGraphEdge(
  payload: GraphEdgeRequest,
): Promise<GraphEdgeResponse> {
  const res = await authFetch("/api/research-os/graph/edges", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<GraphEdgeResponse>(res);
}

export async function deleteResearchGraphEdge(
  payload: GraphEdgeDeletionRequest,
): Promise<GraphEdgeDeletionResponse> {
  const res = await authFetch("/api/research-os/graph/edge_deletions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<GraphEdgeDeletionResponse>(res);
}

export async function tombstoneResearchGraphQro(
  payload: QROTombstoneRequest,
): Promise<QROTombstoneResponse> {
  const res = await authFetch("/api/research-os/graph/qro_tombstones", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<QROTombstoneResponse>(res);
}

export async function applyResearchGraphPatch(
  payload: GraphPatchApplicationRequest,
): Promise<GraphPatchApplicationResponse> {
  const res = await authFetch("/api/research-os/graph/patch_applications", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<GraphPatchApplicationResponse>(res);
}

export async function saveResearchGraphCanvasParameterValue(
  payload: CanvasParameterValueRequest,
): Promise<CanvasParameterValueResponse> {
  const res = await authFetch("/api/research-os/graph/canvas_parameter_values", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return unwrap<CanvasParameterValueResponse>(res);
}
