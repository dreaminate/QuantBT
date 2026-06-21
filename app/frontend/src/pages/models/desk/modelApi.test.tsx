/**
 * M2 Model台「切真」对抗测试：作业队列 / walk-forward / 图 codegen / 晋级门走 authFetch 真端点。
 *
 * mock lib/auth.authFetch，断言：
 *  - codegenGraph 命中 POST /api/training/codegen，body 含 graph（图→代码字符串预览）。
 *  - serializeGraph 把画布原子映射成后端 codegen 原子名（Linear→linear，端口仅送 node）。
 *  - fetchJobs/fetchWalkForward 命中各自 GET 端点；walk-forward ran=false 不假绿。
 *  - mapBackendJob 把后端 detail 富文档映射成 JobDetail（缺字段=空，绝不编造）。
 *  - promote 门 approve 走 POST .../gates/{gate}/approve，body 带 approver/reason/risk_restated。
 *  - 后端报错不假绿：unwrap 抛错由调用方回退 mock（这里断它确实 throw）。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import * as auth from "../../../lib/auth";
import {
  serializeGraph,
  codegenGraph,
  fetchJobs,
  fetchWalkForward,
  approvePromotionGate,
  type BackendJob,
} from "./modelApi";
import { mapBackendJob } from "./JobsDeck";
import { BUILD_NODES, BUILD_EDGES } from "./modelMock";

function jsonRes(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

let authFetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  authFetchSpy = vi.spyOn(auth, "authFetch");
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("M2 modelApi · 图 codegen 序列化与端点", () => {
  it("serializeGraph：画布原子 → 后端原子名（Linear→linear），端口只送 node", () => {
    const ser = serializeGraph(BUILD_NODES, BUILD_EDGES);
    const nodes = ser.nodes as { id: string; type: string; features?: number; params: Record<string, number> }[];
    const input = nodes.find((n) => n.id === "n1");
    expect(input?.type).toBe("input");
    expect(input?.features).toBe(28); // 从 "features: 28" 抽出
    const lin = nodes.find((n) => n.id === "n2");
    expect(lin?.type).toBe("linear");
    expect(lin?.params.out).toBe(256); // 从 "out: 256" 抽出
    const head = nodes.find((n) => n.id === "n5");
    expect(head?.type).toBe("head");
    // 边只送 from/to.node（后端按线性链拓扑判定）
    const e = (ser.edges as { from: { node: string }; to: { node: string } }[])[0];
    expect(e.from.node).toBe("n1");
    expect(e.to.node).toBe("n2");
  });

  it("codegenGraph → POST /api/training/codegen，body 带 graph", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes({ code: "class GraphModel(nn.Module):...", mode: "graph", compiled: false }),
    );
    const r = await codegenGraph(BUILD_NODES, BUILD_EDGES);
    expect(r.mode).toBe("graph");
    expect(r.compiled).toBe(false); // 主进程只产字符串、未编译（M6）
    const [url, init] = authFetchSpy.mock.calls[0];
    expect(url).toBe("/api/training/codegen");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toContain("graph");
  });

  it("codegen 后端 400（非法图）→ throw（调用方据此回退 mock，不假绿）", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ detail: "线性链起点必须是 input 节点" }, false, 400));
    await expect(codegenGraph(BUILD_NODES, BUILD_EDGES)).rejects.toThrow(/input/);
  });
});

describe("M2 modelApi · 作业队列与 walk-forward 端点", () => {
  it("fetchJobs → GET /api/training/jobs", async () => {
    authFetchSpy.mockResolvedValue(jsonRes([]));
    await fetchJobs();
    expect(authFetchSpy.mock.calls[0][0]).toBe("/api/training/jobs");
  });

  it("fetchWalkForward → GET .../walkforward；ran=false 不假绿", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes({ status: "succeeded", ran: false, n_windows: 0, windows: [] }),
    );
    const wf = await fetchWalkForward("trn-x");
    expect(authFetchSpy.mock.calls[0][0]).toBe("/api/training/jobs/trn-x/walkforward");
    expect(wf.ran).toBe(false);
    expect(wf.windows).toEqual([]);
  });
});

describe("M2 modelApi · 晋级审批门（治理三态强制）", () => {
  it("approvePromotionGate → POST .../gates/{gate}/approve，body 带三态字段", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ decision: "approved" }));
    await approvePromotionGate("m1", "gate-1", {
      approver: "bob",
      reason: "独立复核证据三角同向",
      risk_restated: true,
    });
    const [url, init] = authFetchSpy.mock.calls[0];
    expect(url).toBe("/api/models/m1/gates/gate-1/approve");
    const body = (init as RequestInit).body as string;
    expect(body).toContain("approver");
    expect(body).toContain("reason");
    expect(body).toContain("risk_restated");
  });

  it("approve 后端 422（approver==creator）→ throw（前端不当成功，不假绿）", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ detail: "approver 不得等于 creator" }, false, 422));
    await expect(
      approvePromotionGate("m1", "gate-1", { approver: "alice", reason: "自批", risk_restated: true }),
    ).rejects.toThrow(/creator/);
  });
});

describe("M2 JobsDeck · mapBackendJob（后端 detail → JobDetail）", () => {
  function backendJob(over: Partial<BackendJob> = {}): BackendJob {
    return {
      job_id: "trn-real-1", name: "lgbm_real", model: "lgbm", family: "ml", task: "lambdarank",
      status: "succeeded", metrics: { ndcg: 0.231 }, elapsed_seconds: 8.2,
      tensorboard: false, error: null,
      detail: {
        why: "排序基线", data: "equity_cn", window: "2019~2023", label: "fwd_ret_5",
        design: "GBDT", arch: "LightGBM 800 trees", hparams: "lr 0.03",
        sections: [["正则化", "dropout"]],
      },
      ...over,
    };
  }

  it("富文档与指标完整映射（why/arch/sections + ndcg 格式化）", () => {
    const tj = mapBackendJob(backendJob());
    expect(tj.id).toBe("trn-real-1");
    expect(tj.family).toBe("ml");
    expect(tj.arch).toBe("LightGBM 800 trees"); // detail.arch 优先于 model
    expect(tj.ndcg).toBe("0.231");
    expect(tj.detail.why).toBe("排序基线");
    expect(tj.detail.sections).toEqual([["正则化", "dropout"]]);
    expect(tj.elapsed).toBe("8.2s");
  });

  it("缺 detail → 空 JobDetail（绝不编造富文档，不假绿）", () => {
    const tj = mapBackendJob(backendJob({ detail: {}, metrics: {} }));
    expect(tj.detail.why).toBe("");
    expect(tj.detail.sections).toEqual([]);
    expect(tj.ndcg).toBeUndefined(); // 无 ndcg 指标 → 不编造
    expect(tj.arch).toBe("lgbm"); // detail.arch 空 → 回退 model 名
  });

  it("未知 family → code（不硬塞 ml/dl）", () => {
    const tj = mapBackendJob(backendJob({ family: "mixed" }));
    expect(tj.family).toBe("code");
  });
});
