/**
 * S2 策略台「切真」对抗测试：校验/版本/Fork/Live 走 authFetch 新端点（非 mock）。
 *
 * mock lib/auth.authFetch，断言：
 *  - validate 命中 POST /api/ide/strategies/{name}/validate，body 含 nodes/edges。
 *  - 序列化只送校验所需端口字段（dt/req/role），不漏 role（B6 连线门依赖它）。
 *  - versions 命中 GET .../versions；fork 命中 POST .../fork。
 *  - live 切换命中 GET .../live_snapshot；A股 live 永拒 → 出 ⛔ 禁止 banner。
 *  - 后端报错不假绿灯：validate 失败保留本地校验、如实标错。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import * as auth from "../../lib/auth";
import {
  serializeGraph,
  validateStrategyGraph,
  fetchStrategyVersions,
  forkStrategy,
  fetchLiveSnapshot,
  fetchResearchGraphCanvasProjection,
  executeResearchGraphCanvasAssetMutation,
  recordResearchGraphCanvasLayout,
} from "./api";
import { MOCK_NODES, MOCK_EDGES, type DomainNode } from "./mockGraph";
import { StrategyConsolePage } from "../StrategyConsolePage";

function toDict(): Record<string, DomainNode> {
  const d: Record<string, DomainNode> = {};
  for (const n of MOCK_NODES) d[n.id] = n;
  return d;
}

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

/** authFetch 是否被以某 URL 后缀调用过（避开 mock.calls 元素的 any 推断）。 */
function calledWithSuffix(suffix: string): boolean {
  const calls = authFetchSpy.mock.calls as unknown[][];
  return calls.some((c) => String(c[0]).endsWith(suffix));
}

describe("S2 api.ts · 序列化与端点", () => {
  it("serializeGraph 送 nodes/edges 且端口含 role（B6 连线门依赖）", () => {
    const ser = serializeGraph(toDict(), MOCK_EDGES);
    expect(Array.isArray(ser.nodes)).toBe(true);
    expect(Array.isArray(ser.edges)).toBe(true);
    const execNode = (ser.nodes as { id: string; ins: { role?: string }[] }[]).find((n) => n.id === "exec");
    expect(execNode).toBeTruthy();
    // exec 入口 role='exec' 必须随序列化送出（否则后端 B6 校验失效）。
    expect(execNode!.ins.some((p) => p.role === "exec")).toBe(true);
    // edge 保留 from/to（后端按端口连通判定）。
    const e = (ser.edges as { from: unknown; to: unknown }[])[0];
    expect(e.from).toBeTruthy();
    expect(e.to).toBeTruthy();
  });

  it("validateStrategyGraph → POST .../validate 带 body", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ ok: true, errors: [], warnings: [] }));
    const r = await validateStrategyGraph("s1", toDict(), MOCK_EDGES);
    expect(r.ok).toBe(true);
    const [url, init] = authFetchSpy.mock.calls[0];
    expect(url).toBe("/api/ide/strategies/s1/validate");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toContain("nodes");
  });

  it("fetchStrategyVersions → GET .../versions", async () => {
    authFetchSpy.mockResolvedValue(jsonRes([]));
    await fetchStrategyVersions("s1");
    expect(authFetchSpy.mock.calls[0][0]).toBe("/api/ide/strategies/s1/versions");
  });

  it("forkStrategy → POST .../fork", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ name: "s1_fork" }));
    const f = await forkStrategy("s1");
    expect(f.name).toBe("s1_fork");
    expect(authFetchSpy.mock.calls[0][0]).toBe("/api/ide/strategies/s1/fork");
    expect((authFetchSpy.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("fetchLiveSnapshot → GET .../live_snapshot", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ live_allowed: true, readonly: true }));
    await fetchLiveSnapshot("s1");
    expect(authFetchSpy.mock.calls[0][0]).toBe("/api/ide/strategies/s1/live_snapshot");
  });

  it("fetchResearchGraphCanvasProjection → GET Research Graph 只读投影", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes({ total: 0, limit: 24, filters: {}, read_only: true, source_projection_refs: [], nodes: [], edges: [] }),
    );
    const r = await fetchResearchGraphCanvasProjection({ limit: 24, qro_type: "PortfolioPolicy" });
    expect(r.read_only).toBe(true);
    expect(authFetchSpy.mock.calls[0][0]).toBe(
      "/api/research-os/graph/canvas_projection?limit=24&qro_type=PortfolioPolicy",
    );
  });

  it("executeResearchGraphCanvasAssetMutation → POST canonical asset mutation", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes({
        accepted: true,
        command_type: "execute_canvas_asset_mutation",
        mutation_command_id: "rgcmd_mut",
        qro_command_id: "rgcmd_qro",
        qro_id: "qro_policy_1",
        qro_version: 2,
        projection_ref: "rgproj_2",
        updated_field_path: "output_contract.canvas_edit_ref",
        recorded_by: "tester",
      }),
    );
    const r = await executeResearchGraphCanvasAssetMutation({
      command_ref: "canvas_command:strategy_console:qro_policy_1:1",
      source_desk: "strategy",
      actor_source: "user_manual",
      target_asset_type: "PortfolioPolicy",
      target_ref: "qro_policy_1",
      field_path: "output_contract.canvas_edit_ref",
      operation: "set_ref",
      canonical_command_ref: "canonical:strategy_console:qro_policy_1:1",
      audit_ref: "audit:strategy_console:qro_policy_1:1",
      value_ref: "canvas_edit:strategy_console:qro_policy_1:1",
      value_hash: "hash_strategy_console_1",
      evidence_refs: ["frontend:StrategyConsolePage:canvas_asset_mutation"],
    });
    expect(r.qro_version).toBe(2);
    const [url, init] = authFetchSpy.mock.calls[0];
    expect(url).toBe("/api/research-os/graph/canvas_asset_mutations");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toContain("output_contract.canvas_edit_ref");
    expect((init as RequestInit).body).not.toContain("raw_value");
  });

  it("recordResearchGraphCanvasLayout → POST exact layout record", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes({
        accepted: true,
        command_type: "record_canvas_layout",
        layout_command_id: "rgcmd_layout",
        layout_ref: "canvas_layout:qro_policy_1:hash_canvas_layout_1",
        layout_hash: "hash_canvas_layout_1",
        mutation_command_id: "rgcmd_layout_mut",
        qro_command_id: "rgcmd_layout_qro",
        qro_id: "qro_policy_1",
        qro_version: 2,
        projection_ref: "rgproj_layout",
        updated_field_path: "output_contract.canvas_layout_ref",
        recorded_by: "tester",
      }),
    );
    const r = await recordResearchGraphCanvasLayout({
      command_ref: "canvas_command:strategy_console_layout:qro_policy_1:1",
      source_desk: "strategy",
      actor_source: "user_manual",
      target_asset_type: "PortfolioPolicy",
      target_ref: "qro_policy_1",
      node_id: "canvas_node:qro:qro_policy_1",
      x: 520,
      y: 160,
      w: 184,
      canonical_command_ref: "canonical:strategy_console_layout:qro_policy_1:1",
      audit_ref: "audit:strategy_console_layout:qro_policy_1:1",
      evidence_refs: ["frontend:StrategyConsolePage:qro_node_layout_drag"],
    });
    expect(r.layout_ref).toBe("canvas_layout:qro_policy_1:hash_canvas_layout_1");
    const [url, init] = authFetchSpy.mock.calls[0];
    expect(url).toBe("/api/research-os/graph/canvas_layouts");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toContain('"node_id":"canvas_node:qro:qro_policy_1"');
    expect((init as RequestInit).body).toContain('"x":520');
    expect((init as RequestInit).body).not.toContain("raw_value");
  });

  it("非 2xx → 抛 detail（不静默吞错）", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ detail: "boom" }, false, 400));
    await expect(validateStrategyGraph("s1", toDict(), MOCK_EDGES)).rejects.toThrow("boom");
  });
});

function Harness({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter initialEntries={["/strategy"]}>
      <Routes>
        <Route path="/strategy" element={children} />
        <Route path="/runs/:runId" element={<div />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("S2 页面切真 · 校验/版本/Fork/Live 走真端点", () => {
  it("点「校验」→ 调后端 validate 端点", async () => {
    authFetchSpy.mockResolvedValue(jsonRes({ ok: true, errors: [], warnings: [] }));
    const { container } = render(<Harness><StrategyConsolePage /></Harness>);
    fireEvent.click(screen.getByText("拒绝")); // 清 ghost 提议
    fireEvent.click(container.querySelector("[data-validate]") as HTMLElement);
    await waitFor(() =>
      expect(calledWithSuffix("/validate")).toBe(true),
    );
  });

  it("开版本菜单 → 调 versions 端点并渲染真实条目", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes([
        {
          version_id: "sv_1", strategy_id: "stg_x", owner_username: "tester",
          content_hash: "abcdef0123456789", parent_content_hash: null,
          parent_strategy_id: null, label: "save now", origin: "save",
          created_at_utc: "2026-01-01T00:00:00Z",
        },
      ]),
    );
    const { container } = render(<Harness><StrategyConsolePage /></Harness>);
    fireEvent.click(screen.getByText("拒绝"));
    fireEvent.click(container.querySelector("[data-version-toggle]") as HTMLElement);
    await waitFor(() =>
      expect(calledWithSuffix("/versions")).toBe(true),
    );
    await waitFor(() => expect(document.querySelector("[data-version-row]")).not.toBeNull());
  });

  it("切 Live → 调 live_snapshot；A股 live 永拒渲染 ⛔ 禁止 banner", async () => {
    authFetchSpy.mockResolvedValue(
      jsonRes({
        strategy_id: "stg_x", name: "strat_wk_cn_01", asset_class: "equity_cn",
        live_allowed: false, reason: "A股（equity_cn）实盘交易永久禁止（合规红线，不可绕过）",
        runtime: "live", readonly: true, positions: [], recent_runs: [],
      }),
    );
    render(<Harness><StrategyConsolePage /></Harness>);
    fireEvent.click(screen.getByText("拒绝"));
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    await waitFor(() =>
      expect(calledWithSuffix("/live_snapshot")).toBe(true),
    );
    await waitFor(() => expect(document.querySelector("[data-live-forbidden]")).not.toBeNull());
    expect(screen.getByText(/永久禁止/)).toBeInTheDocument();
  });

  it("Fork（Live 下）→ 调 fork 端点", async () => {
    authFetchSpy.mockImplementation((url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith("/live_snapshot")) {
        return Promise.resolve(jsonRes({ live_allowed: true, readonly: true, runtime: "live", positions: [], recent_runs: [], run_count: 0, name: "strat_wk_cn_01", strategy_id: "x", asset_class: "crypto_perp" }));
      }
      if (u.endsWith("/fork")) {
        return Promise.resolve(jsonRes({ name: "strat_wk_cn_01_fork", strategy_id: "y", owner_username: "tester", code: "", asset_class: "crypto_perp", description: "", updated_at_utc: "" }));
      }
      return Promise.resolve(jsonRes({}));
    });
    render(<Harness><StrategyConsolePage /></Harness>);
    fireEvent.click(screen.getByText("拒绝"));
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    fireEvent.click(await screen.findByText("⑂ Fork 草稿"));
    await waitFor(() =>
      expect(calledWithSuffix("/fork")).toBe(true),
    );
  });
});
