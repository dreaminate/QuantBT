/**
 * Model台后端封装（M2 接真）。authFetch 自动带 Bearer。
 *
 * 对接 main.py 已有/本卡新增端点：
 *  - GET  /api/training/jobs                     训练队列（含 detail 富文档透传）
 *  - GET  /api/training/jobs/{id}                单 job 快照（status/metrics/detail）
 *  - GET  /api/training/jobs/{id}/walkforward    walk-forward 逐窗（本卡新增，诚实合约）
 *  - POST /api/training/codegen                  图→代码字符串预览（graph 路径，D-DESK-F1B(a)）
 *  - GET  /api/training/models/{key}             模型卡详情（含 io_spec）
 *  - POST /api/models/{id}/promote               晋级（dev/archived 直翻 / staging/production 开门）
 *  - POST /api/models/{id}/gates/{gate}/approve  审批门（approver≠creator / reason / risk_restated 强制）
 *
 * 诚实原则：未接 / fetch 失败 → 调用方回退 mock 并保留 MockBadge，绝不假绿。
 */

import { authFetch } from "../../../lib/auth";
import type { NodeView, EdgeView } from "../../../components/desk";

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const j = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(j.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// 训练作业（jobs）
// ---------------------------------------------------------------------------

/** 后端 TrainingJob.to_dict（与 store.TrainingJob 对齐；detail 为富文档透传）。 */
export interface BackendJob {
  job_id: string;
  name: string;
  model: string;
  family: string;
  task: string;
  status: "queued" | "running" | "succeeded" | "failed";
  metrics: Record<string, number>;
  elapsed_seconds: number | null;
  tensorboard: boolean;
  error: string | null;
  detail: Record<string, unknown>;
}

export async function fetchJobs(): Promise<BackendJob[]> {
  return unwrap<BackendJob[]>(await authFetch("/api/training/jobs"));
}

export async function fetchJob(jobId: string): Promise<BackendJob> {
  return unwrap<BackendJob>(await authFetch(`/api/training/jobs/${encodeURIComponent(jobId)}`));
}

// ---------------------------------------------------------------------------
// walk-forward 逐窗（DRILL-IN）
// ---------------------------------------------------------------------------

/** 后端 walk_forward_windows 单窗（model_eval.walk_forward_windows）。 */
export interface BackendWfWindow {
  w: string;
  fold_index: number;
  n_train: number;
  n_test: number;
  metric_key: string | null;
  /** OOS 主指标，可正可负；null=该窗无数值（前端据正负诚实上色、不洗成绿）。 */
  metric: number | null;
}

/** walk-forward 端点返回（ran=false 时前端显示「待跑」，绝不假绿）。 */
export interface BackendWalkForward {
  status: string;
  ran: boolean;
  cv_scheme?: string;
  metric_key?: string | null;
  n_windows: number;
  n_positive?: number;
  n_scored?: number;
  windows: BackendWfWindow[];
}

export async function fetchWalkForward(jobId: string): Promise<BackendWalkForward> {
  return unwrap<BackendWalkForward>(
    await authFetch(`/api/training/jobs/${encodeURIComponent(jobId)}/walkforward`),
  );
}

// ---------------------------------------------------------------------------
// 构建台图 → 代码字符串预览（graph codegen · 主进程不碰 torch）
// ---------------------------------------------------------------------------

/** 构建台原子类型 → 后端 codegen 原子名（与 codegen._GRAPH_ATOMS 对齐）。 */
const ATOM_ALIAS: Record<string, string> = {
  Input: "input",
  Linear: "linear",
  Conv1d: "conv1d",
  GELU: "gelu",
  ReLU: "relu",
  Tanh: "tanh",
  Dropout: "dropout",
  LSTM: "lstm",
  GRU: "gru",
  Head: "head",
  Output: "output",
};

/** 从节点 lines 抽一个 `key: number`（如 "features: 28" / "out: 256"）。 */
function _numFrom(lines: string[] | undefined, key: string): number | undefined {
  if (!lines) return undefined;
  for (const ln of lines) {
    const m = ln.match(new RegExp(`${key}\\s*[:：]\\s*(\\d+)`));
    if (m) return Number(m[1]);
  }
  return undefined;
}

/** 画布 NodeView/EdgeView → 后端 codegen 图 schema（线性链子集）。 */
export function serializeGraph(nodes: NodeView[], edges: EdgeView[]): {
  nodes: unknown[];
  edges: unknown[];
} {
  return {
    nodes: nodes.map((n) => {
      const atom = ATOM_ALIAS[n.title] ?? n.title.toLowerCase();
      const params: Record<string, number> = {};
      const features = _numFrom(n.lines, "features");
      const out = _numFrom(n.lines, "out");
      if (out !== undefined) params.out = out;
      return {
        id: n.id,
        type: atom,
        ...(features !== undefined ? { features } : {}),
        params,
      };
    }),
    edges: edges.map((e) => ({
      from: { node: e.from.node },
      to: { node: e.to.node },
    })),
  };
}

export interface CodegenResult {
  code: string;
  mode: "graph" | "spec";
  /** 主进程只产代码字符串、未编译（M6 子进程隔离）。 */
  compiled?: boolean;
}

export async function codegenGraph(nodes: NodeView[], edges: EdgeView[]): Promise<CodegenResult> {
  const graph = serializeGraph(nodes, edges);
  return unwrap<CodegenResult>(
    await authFetch("/api/training/codegen", {
      method: "POST",
      body: JSON.stringify({ graph }),
    }),
  );
}

// ---------------------------------------------------------------------------
// 晋级 / 审批门（promote / approve · 治理三态强制，对齐后端 422）
// ---------------------------------------------------------------------------

export interface PromoteResult {
  gate_id?: string;
  decision?: string;
  [k: string]: unknown;
}

export async function promoteModel(
  modelId: string,
  body: { version: number; stage: string; created_by?: string; verification_record_id?: string },
): Promise<PromoteResult> {
  return unwrap<PromoteResult>(
    await authFetch(`/api/models/${encodeURIComponent(modelId)}/promote`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
}

export async function approvePromotionGate(
  modelId: string,
  gateId: string,
  body: { approver: string; reason: string; risk_restated?: boolean },
): Promise<PromoteResult> {
  return unwrap<PromoteResult>(
    await authFetch(
      `/api/models/${encodeURIComponent(modelId)}/gates/${encodeURIComponent(gateId)}/approve`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  );
}
