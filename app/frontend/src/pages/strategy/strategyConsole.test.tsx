import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { type ReactNode } from "react";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import { Routes, Route, MemoryRouter, useLocation } from "react-router-dom";
import { assertNoFrozenPageImport } from "../../test/harness";
import { StrategyConsolePage } from "../StrategyConsolePage";
import {
  MOCK_NODES,
  MOCK_EDGES,
  MOCK_PROPOSAL,
  toNodeView,
  type DomainPort,
} from "./mockGraph";
import { validateGraph, canDelete, compat } from "./graphLogic";

const here = dirname(fileURLToPath(import.meta.url));
const pageSrcDir = dirname(here); // src/pages

function toDict() {
  const d: Record<string, (typeof MOCK_NODES)[number]> = {};
  for (const n of MOCK_NODES) d[n.id] = n;
  return d;
}

function LocationProbe({ onChange }: { onChange?: (p: string) => void }) {
  const loc = useLocation();
  if (onChange) onChange(loc.pathname);
  return <div data-testid="run-detail-probe">{loc.pathname}</div>;
}
function RouterHarness({ children, routeSpy }: { children: ReactNode; routeSpy?: (p: string) => void }) {
  return (
    <MemoryRouter initialEntries={["/strategy"]}>
      <Routes>
        <Route path="/strategy" element={children} />
        <Route path="/runs/:runId" element={<LocationProbe onChange={routeSpy} />} />
      </Routes>
    </MemoryRouter>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 渲染策略台并挂一个 /runs/:runId 探针路由，捕获单段跳转。 */
function renderPage(routeSpy?: (path: string) => void) {
  return render(
    <RouterHarness routeSpy={routeSpy}>
      <StrategyConsolePage />
    </RouterHarness>,
  );
}

function researchGraphProjectionBody(
  options: {
    qroX?: number;
    qroY?: number;
    qroW?: number;
    withSecondQro?: boolean;
    includeGraphEdge?: boolean;
    omitPrimaryQro?: boolean;
    includePatchApplication?: "ghost" | "auto";
  } = {},
) {
  const primaryNodes = options.omitPrimaryQro
    ? []
    : [
        {
          id: "canvas_node:command:cmd_1",
          cat: "research",
          title: "Graph command",
          x: 40,
          y: 40,
          w: 184,
          state: "valid",
          lines: ["type upsert_qro", "actor agent_runtime", "cmd cmd_1"],
          ins: [],
          outs: [{ id: "out:cmd_1", name: "upsert_qro" }],
          badge: "Research Graph",
          locked: true,
        },
        {
          id: "canvas_node:qro:qro_policy_1",
          cat: "position",
          title: "PortfolioPolicy",
          x: options.qroX ?? 304,
          y: options.qroY ?? 40,
          w: options.qroW ?? 184,
          state: "running",
          lines: ["qro qro_policy_1", "CN / CSI500", "evidence sufficient", "keys objective"],
          ins: [{ id: "in:qro_policy_1", name: "graph" }],
          outs: [{ id: "out:qro_policy_1", name: "qro" }],
          badge: "strategy_goal_store",
          locked: true,
        },
      ];
  const primaryEdges = options.omitPrimaryQro
    ? []
    : [
        {
          id: "canvas_edge:cmd_1:qro_policy_1",
          from: { node: "canvas_node:command:cmd_1", port: "out:cmd_1" },
          to: { node: "canvas_node:qro:qro_policy_1", port: "in:qro_policy_1" },
          compat: "ok",
        },
      ];
  const secondNodes = options.withSecondQro
    ? [
        {
          id: "canvas_node:command:cmd_2",
          cat: "research",
          title: "Graph command",
          x: 40,
          y: 186,
          w: 184,
          state: "valid",
          lines: ["type upsert_qro", "actor agent_runtime", "cmd cmd_2"],
          ins: [],
          outs: [{ id: "out:cmd_2", name: "upsert_qro" }],
          badge: "Research Graph",
          locked: true,
        },
        {
          id: "canvas_node:qro:qro_signal_1",
          cat: "signal",
          title: "Signal",
          x: 560,
          y: 186,
          w: 184,
          state: "validating",
          lines: ["qro qro_signal_1", "CN / CSI500", "evidence exploratory", "keys factor"],
          ins: [{ id: "in:qro_signal_1", name: "graph" }],
          outs: [{ id: "out:qro_signal_1", name: "qro" }],
          badge: "strategy_goal_store",
          locked: true,
        },
      ]
    : [];
  const secondEdges = options.withSecondQro
    ? [
        {
          id: "canvas_edge:cmd_2:qro_signal_1",
          from: { node: "canvas_node:command:cmd_2", port: "out:cmd_2" },
          to: { node: "canvas_node:qro:qro_signal_1", port: "in:qro_signal_1" },
          compat: "ok",
        },
      ]
    : [];
  const graphEdges = options.includeGraphEdge
    ? [
        {
          id: "canvas_edge:graph:rgedge_policy_signal",
          from: { node: "canvas_node:qro:qro_policy_1", port: "out:qro_policy_1" },
          to: { node: "canvas_node:qro:qro_signal_1", port: "in:qro_signal_1" },
          compat: "ok",
        },
      ]
    : [];
  const patchNodes = options.includePatchApplication
    ? [
        {
          id: `canvas_node:command:cmd_patch_${options.includePatchApplication}`,
          cat: "research",
          title: "Graph command",
          x: 40,
          y: 332,
          w: 184,
          state: "valid",
          lines: ["type canvas", "actor user_manual", "cmd cmd_patch"],
          ins: [],
          outs: [{ id: `out:cmd_patch_${options.includePatchApplication}`, name: "upsert_qro" }],
          badge: "Research Graph",
          locked: true,
        },
        {
          id: `canvas_node:qro:qro_patch_${options.includePatchApplication}`,
          cat: "research",
          title: "GraphPatchApplication",
          x: 560,
          y: 332,
          w: 184,
          state: "valid",
          lines: [`qro qro_patch_${options.includePatchApplication}`, "CN / CSI500", "evidence exploratory", "keys patch_ref"],
          ins: [{ id: `in:qro_patch_${options.includePatchApplication}`, name: "graph" }],
          outs: [{ id: `out:qro_patch_${options.includePatchApplication}`, name: "qro" }],
          badge: "strategy_goal_store",
          locked: true,
        },
      ]
    : [];
  const patchEdges = options.includePatchApplication
    ? [
        {
          id: `canvas_edge:cmd_patch_${options.includePatchApplication}:qro_patch_${options.includePatchApplication}`,
          from: {
            node: `canvas_node:command:cmd_patch_${options.includePatchApplication}`,
            port: `out:cmd_patch_${options.includePatchApplication}`,
          },
          to: {
            node: `canvas_node:qro:qro_patch_${options.includePatchApplication}`,
            port: `in:qro_patch_${options.includePatchApplication}`,
          },
          compat: "ok",
        },
        {
          id: `canvas_edge:graph:rgedge_patch_${options.includePatchApplication}`,
          from: { node: "canvas_node:qro:qro_policy_1", port: "out:qro_policy_1" },
          to: {
            node: `canvas_node:qro:qro_patch_${options.includePatchApplication}`,
            port: `in:qro_patch_${options.includePatchApplication}`,
          },
          compat: "ok",
        },
      ]
    : [];
  return {
    total: (options.omitPrimaryQro ? 0 : 1) + (options.withSecondQro ? 1 : 0) + (options.includePatchApplication ? 1 : 0),
    limit: 24,
    filters: {},
    read_only: true,
    source_projection_refs: [
      ...(options.omitPrimaryQro ? [] : ["projection:qro_policy_1"]),
      ...(options.withSecondQro ? ["projection:qro_signal_1"] : []),
      ...(options.includePatchApplication ? [`projection:qro_patch_${options.includePatchApplication}`] : []),
    ],
    raw_prompt: "secret_prompt_should_not_render",
    nodes: [
      ...primaryNodes,
      ...secondNodes,
      ...patchNodes,
    ],
    edges: [
      ...primaryEdges,
      ...secondEdges,
      ...graphEdges,
      ...patchEdges,
    ],
  };
}

describe("S1 策略台 · 渲染骨架", () => {
  it("DeskShell data-desk='strategy'（橙 accent）+ 顶栏 DeskSwitcher current=strategy + 策略名/版本/runtime 段控", () => {
    const { container } = renderPage();
    const root = container.querySelector(".desk-root") as HTMLElement;
    expect(root.dataset.desk).toBe("strategy");
    // 台切换器当前态 = 策略台（仍可点击，aria-current 标记 active）
    expect(screen.getByText("策略台").closest("a")).toHaveAttribute("href", "/strategy");
    expect(screen.getByText("策略台").closest("a")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("strat_wk_cn_01")).toBeInTheDocument();
    expect(screen.getByText(/v3 草稿/)).toBeInTheDocument();
    // runtime 三态段控
    expect(screen.getByRole("tab", { name: "Backtest" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Paper" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Live" })).toBeInTheDocument();
    // 顶栏动作
    expect(screen.getByText(/运行回测/)).toBeInTheDocument();
    expect(screen.getByText(/编译源码/)).toBeInTheDocument();
    expect(screen.getByText("发布 ▸")).toBeInTheDocument();
  });

  it("中区渲染 17 节点 + 19 连线（mock DAG · DC defs[] 真值，narration「16」off-by-one）", () => {
    const { container } = renderPage();
    // 先拒绝 Ask 提议，去掉 ghost 预览节点，得到纯初始图。
    fireEvent.click(screen.getByText("拒绝"));
    const nodeEls = container.querySelectorAll("[data-node-id]");
    expect(nodeEls.length).toBe(17);
    const edgeEls = container.querySelectorAll("[data-edge-id]");
    expect(edgeEls.length).toBe(19);
  });

  it("左实现面板 / 可拖分隔线 / 右 Inspector / 底 Dock 默认折叠", () => {
    const { container } = renderPage();
    expect(screen.getByText("实现面板")).toBeInTheDocument();
    expect(container.querySelector('[data-pane-splitter="left"]')).not.toBeNull();
    expect(container.querySelector('[data-pane-splitter="right"]')).not.toBeNull();
    const insp = container.querySelector("[data-inspector]") as HTMLElement;
    expect(insp.style.width).toBe("var(--desk-right-pane-width, 340px)");
    // dock 默认折叠：出折叠条、无展开 dock
    expect(container.querySelector("[data-dock-collapsed]")).not.toBeNull();
    expect(container.querySelector("[data-dock]")).toBeNull();
  });
});

describe("S1 对抗①：节点「↗打开回测」用 navigate('/runs/:runId') 单段", () => {
  it("点开回测 → 路径命中 /^\\/runs\\/[^/]+$/（单段，不嵌 RunDetailPage）", () => {
    const seen: string[] = [];
    const { container } = renderPage((p) => seen.push(p));
    fireEvent.click(container.querySelector("[data-open-run]")!);
    const last = seen[seen.length - 1];
    expect(last).toMatch(/^\/runs\/[^/]+$/);
    expect(last).toBe("/runs/run_wk_cn_8f2a");
  });

  it("源码不 import 冻结 RunDetailPage（旁挂跳转，非嵌入）", () => {
    const src = readFileSync(join(pageSrcDir, "StrategyConsolePage.tsx"), "utf8");
    assertNoFrozenPageImport(src);
    expect(src).not.toMatch(/import[^;]*RunDetailPage/);
  });
});

describe("S1 对抗②：Final Risk Gate 节点 locked，不可删", () => {
  it("逻辑层 canDelete：gate=false（locked），普通节点=true", () => {
    const dict = toDict();
    expect(canDelete(dict.gate)).toBe(false);
    expect(canDelete(dict.signal)).toBe(true);
  });

  it("UI：选中 gate 按 Delete 后节点仍在（删除门跳过 locked）", () => {
    const { container } = renderPage();
    // 选中 Final Risk Gate（点节点卡 head，避开 desc 文本里的同名串）
    const gateCard = container.querySelector("[data-node-id='gate']") as HTMLElement;
    fireEvent.click(gateCard);
    fireEvent.keyDown(window, { key: "Delete" });
    expect(container.querySelector("[data-node-id='gate']")).not.toBeNull();
  });

  it("对照：选中普通节点（信号 Signal）按 Delete 可删", () => {
    const { container } = renderPage();
    const sigCard = container.querySelector("[data-node-id='signal']") as HTMLElement;
    fireEvent.click(sigCard);
    fireEvent.keyDown(window, { key: "Delete" });
    expect(container.querySelector("[data-node-id='signal']")).toBeNull();
  });
});

describe("S1 对抗③：runtime==='live' 时画布只读 + 参数 disabled + 🔒Live只读", () => {
  it("切 Live → 出现 🔒 Live 只读 + 画布只读 banner + Fork/Kill", () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    expect(screen.getByText("🔒 Live 只读")).toBeInTheDocument();
    expect(screen.getByText(/Live 只读 · 画布与参数已锁定/)).toBeInTheDocument();
    expect(screen.getByText("⑂ Fork 草稿")).toBeInTheDocument();
    expect(screen.getByLabelText("Kill Switch")).toBeInTheDocument();
  });

  it("Live 下选中节点 → Inspector 参数 input 全 disabled", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    fireEvent.click(screen.getByText("信号 Signal"));
    const inputs = container.querySelectorAll("[data-param-row] input");
    expect(inputs.length).toBeGreaterThan(0);
    inputs.forEach((i) => expect((i as HTMLInputElement).disabled).toBe(true));
  });

  it("Live 下节点不可拖（拖拽不改坐标）", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    const gateHead = container.querySelector("[data-node-head='signal']") as HTMLElement;
    const card = container.querySelector("[data-node-id='signal']") as HTMLElement;
    const x0 = card.style.left;
    fireEvent.pointerDown(gateHead, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 300, clientY: 300 });
    fireEvent.pointerUp(window);
    expect(card.style.left).toBe(x0);
  });
});

describe("S1 对抗④：agentMode='bypass' 时 UI 仍显治理门拦（权限轴 ⟂ 治理轴）", () => {
  it("Bypass 模式 + Live → 🔒Live只读治理门仍在（权限态不跳治理门）", () => {
    renderPage();
    // 切 bypass 权限
    fireEvent.click(screen.getByRole("tab", { name: "Bypass" }));
    // 状态行展示 bypass（受控展示，不可编辑）
    const status = document.querySelector("[data-status-row]") as HTMLElement;
    expect(within(status).getByText(/bypass/)).toBeInTheDocument();
    // 切 Live：治理门（Live 只读）仍出现，bypass 不绕过
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    expect(screen.getByText("🔒 Live 只读")).toBeInTheDocument();
    expect(screen.getByText(/Live 只读 · 画布与参数已锁定/)).toBeInTheDocument();
  });

  it("Bypass 下 Final Risk Gate 仍 locked 不可删（治理轴独立于权限轴）", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Bypass" }));
    fireEvent.click(screen.getByText("Final Risk Gate"));
    const before = container.querySelectorAll("[data-node-id]").length;
    fireEvent.keyDown(window, { key: "Delete" });
    expect(container.querySelectorAll("[data-node-id]").length).toBe(before);
  });
});

describe("S1 对抗⑤：mock 区块带 MockBadge（B9 诚实，不假绿灯）", () => {
  it("画布工具条 + dock 历史 + Inspector 贡献卡均挂 MOCK 角标", () => {
    const { container } = renderPage();
    // 工具条 MOCK 数据角标
    expect(screen.getAllByText(/MOCK/).length).toBeGreaterThan(0);
    // 选中有贡献的节点 → 切版本/血缘 tab → 贡献卡带 MockBadge
    fireEvent.click(screen.getByText("信号 Signal"));
    fireEvent.click(screen.getByRole("tab", { name: "版本/血缘" }));
    const contrib = container.querySelector("[data-contribution]") as HTMLElement;
    expect(within(contrib).getByText(/MOCK/)).toBeInTheDocument();
  });
});

describe("S2 Research Graph → GraphCanvas 只读投影", () => {
  it("mount 后拉 /api/research-os/graph/canvas_projection；成功则渲染真实只读节点，不显示 raw payload", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse(researchGraphProjectionBody())),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(/Research Graph · 1 QRO/)).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/research-os/graph/canvas_projection?limit=24");
    expect(document.querySelector("[data-canvas-source]")).toHaveAttribute("data-canvas-source", "research_graph");
    expect(document.querySelector("[data-graph-projection-banner]")).toHaveTextContent("无 raw payload");
    expect(container.querySelectorAll("[data-node-id]").length).toBe(2);
    expect(container.querySelector("[data-node-id='canvas_node:qro:qro_policy_1']")).not.toBeNull();
    expect(container.querySelectorAll("[data-edge-id]").length).toBe(1);
    expect(document.body).not.toHaveTextContent("secret_prompt_should_not_render");
  });

  it("真实投影 QRO 节点拖拽写 canonical exact layout 并重放服务端坐标", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/canvas_layouts") {
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "record_canvas_layout",
            layout_command_id: "rgcmd_layout_record",
            layout_ref: "canvas_layout:qro_policy_1:hash_canvas_layout_server",
            layout_hash: "hash_canvas_layout_server",
            mutation_command_id: "rgcmd_layout_mut",
            qro_command_id: "rgcmd_layout_qro",
            qro_id: "qro_policy_1",
            qro_version: 2,
            projection_ref: "rgproj_layout",
            updated_field_path: "output_contract.canvas_layout_ref",
            recorded_by: "tester",
          }),
        );
      }
      if (url.startsWith("/api/research-os/graph/canvas_projection") && fetchMock.mock.calls.length > 1) {
        return Promise.resolve(jsonResponse(researchGraphProjectionBody({ qroX: 520, qroY: 160, qroW: 184 })));
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody()));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();
    const nodeSelector = "[data-node-id='canvas_node:qro:qro_policy_1']";
    await waitFor(() => expect(container.querySelector(nodeSelector)).not.toBeNull());

    const card = container.querySelector(nodeSelector) as HTMLElement;
    const head = container.querySelector("[data-node-head='canvas_node:qro:qro_policy_1']") as HTMLElement;
    fireEvent.click(card);
    fireEvent.pointerDown(head, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 260, clientY: 260 });
    fireEvent.pointerUp(window);
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]) === "/api/research-os/graph/canvas_layouts")).toBe(true);
    });
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/canvas_layouts");
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"node_id":"canvas_node:qro:qro_policy_1"');
    expect(body).toContain('"x":');
    expect(body).toContain('"y":');
    expect(body).toContain('"w":184');
    expect(body).not.toContain("raw_value");
    expect(body).not.toContain("output_contract.canvas_layout_hash");
    await waitFor(() => expect((container.querySelector(nodeSelector) as HTMLElement).style.left).toBe("520px"));
    expect((container.querySelector(nodeSelector) as HTMLElement).style.top).toBe("160px");
  });

  it("投影失败时保留 mock 画布并标明 mock fallback", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ detail: "offline" }, 503))));
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(/MOCK fallback · offline/)).toBeInTheDocument());
    expect(document.querySelector("[data-canvas-source]")).toHaveAttribute("data-canvas-source", "mock_fallback");
    expect(container.querySelector("[data-node-id='thesis']")).not.toBeNull();
  });

  it("选中真实 QRO 节点后可触发 canonical asset mutation，并重拉 projection", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/canvas_asset_mutations") {
        return Promise.resolve(
          jsonResponse({
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
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody()));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const nodeSelector = "[data-node-id='canvas_node:qro:qro_policy_1']";
    await waitFor(() => expect(container.querySelector(nodeSelector)).not.toBeNull());
    fireEvent.click(container.querySelector(nodeSelector) as HTMLElement);
    fireEvent.click(screen.getByLabelText("记录 Graph 编辑"));

    await waitFor(() => expect(screen.getByText(/已写入 QRO v2/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/canvas_asset_mutations");
    expect(postCall).toBeTruthy();
    expect((postCall![1] as RequestInit).method).toBe("POST");
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain("output_contract.canvas_edit_ref");
    expect(body).toContain("canvas_edit:strategy_console:qro_policy_1");
    expect(body).not.toContain("raw_value");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });

  it("选中真实 QRO 节点后可保存参数值，且不提交 raw node wrapper", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/canvas_parameter_values") {
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "set_canvas_parameter",
            parameter_command_id: "rgcmd_param_value",
            qro_command_id: "rgcmd_param_qro",
            qro_id: "qro_policy_1",
            qro_version: 4,
            projection_ref: "rgproj_param",
            param_key: "turnover",
            parameter_ref: "rgparam_turnover",
            value_hash: "hash_param_turnover",
            updated_field_path: "output_contract.canvas_param_value_ref",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody()));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const nodeSelector = "[data-node-id='canvas_node:qro:qro_policy_1']";
    await waitFor(() => expect(container.querySelector(nodeSelector)).not.toBeNull());
    fireEvent.click(container.querySelector(nodeSelector) as HTMLElement);
    fireEvent.change(screen.getByLabelText("Graph 参数名"), { target: { value: "turnover" } });
    fireEvent.change(screen.getByLabelText("Graph 参数值"), { target: { value: "45%/w" } });
    fireEvent.click(screen.getByLabelText("记录 Graph 参数"));

    await waitFor(() => expect(screen.getByText(/已保存参数 turnover/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/canvas_parameter_values");
    expect(postCall).toBeTruthy();
    expect((postCall![1] as RequestInit).method).toBe("POST");
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"target_qro_id":"qro_policy_1"');
    expect(body).toContain('"param_key":"turnover"');
    expect(body).toContain('"param_value":"45%/w"');
    expect(body).toContain("canonical:strategy_console_param_value:qro_policy_1:turnover");
    expect(body).not.toContain("raw_value");
    expect(body).not.toContain('"params"');
    expect(body).not.toContain("context_payload");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });

  it("真实 QRO 节点按 Delete 时写入 QRO tombstone，且不提交 raw node object", async () => {
    let tombstoned = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/qro_tombstones") {
        tombstoned = true;
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "tombstone_qro",
            qro_tombstone_command_id: "rgcmd_qro_tombstone",
            qro_id: "qro_policy_1",
            tombstone_ref: "rgqrodel_policy_1",
            projection_node_id: "canvas_node:qro:qro_policy_1",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody({
        withSecondQro: tombstoned,
        omitPrimaryQro: tombstoned,
      })));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const nodeSelector = "[data-node-id='canvas_node:qro:qro_policy_1']";
    await waitFor(() => expect(container.querySelector(nodeSelector)).not.toBeNull());
    fireEvent.click(container.querySelector(nodeSelector) as HTMLElement);
    fireEvent.keyDown(window, { key: "Delete" });

    await waitFor(() => expect(screen.getByText(/已删除 QRO node/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/qro_tombstones");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"qro_id":"qro_policy_1"');
    expect(body).toContain("canonical:strategy_console_tombstone_qro:qro_policy_1");
    expect(body).not.toContain("canvas_node:");
    expect(body).not.toContain("raw_value");
    expect(body).not.toContain('"params"');
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
    await waitFor(() => expect(container.querySelector(nodeSelector)).toBeNull());
  });

  it("真实投影端口两步连接可创建 QRO-to-QRO graph edge，且不提交 raw endpoint object", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/edges") {
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "record_graph_edge",
            graph_edge_command_id: "rgcmd_graph_edge",
            edge_ref: "rgedge_policy_signal",
            from_qro_id: "qro_policy_1",
            to_qro_id: "qro_signal_1",
            relation_type: "canvas_connect",
            projection_edge_id: "canvas_edge:graph:rgedge_policy_signal",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody({ withSecondQro: true, includeGraphEdge: url.includes("canvas_projection?") })));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const fromQroNode = "[data-node-id='canvas_node:qro:qro_policy_1']";
    const toQroNode = "[data-node-id='canvas_node:qro:qro_signal_1']";
    await waitFor(() => expect(container.querySelector(fromQroNode)).not.toBeNull());
    await waitFor(() => expect(container.querySelector(toQroNode)).not.toBeNull());
    const outPort = within(container.querySelector(fromQroNode) as HTMLElement).getByLabelText("出端口 qro");
    const inPort = within(container.querySelector(toQroNode) as HTMLElement).getByLabelText("入端口 graph");
    fireEvent.pointerDown(outPort);
    fireEvent.pointerDown(inPort);

    await waitFor(() => expect(screen.getByText(/已创建 Graph edge/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/edges");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"from_qro_id":"qro_policy_1"');
    expect(body).toContain('"to_qro_id":"qro_signal_1"');
    expect(body).toContain('"relation_type":"canvas_connect"');
    expect(body).toContain("canonical:strategy_console_graph_edge:qro_policy_1:qro_signal_1");
    expect(body).not.toContain("canvas_node:");
    expect(body).not.toContain('"port"');
    expect(body).not.toContain("raw_value");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });

  it("选中真实 QRO-to-QRO graph edge 后可 tombstone，且不提交 raw endpoint object", async () => {
    let deleted = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/edge_deletions") {
        deleted = true;
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "delete_graph_edge",
            graph_edge_deletion_command_id: "rgcmd_graph_edge_delete",
            edge_ref: "rgedge_policy_signal",
            deletion_ref: "rgedgedel_policy_signal",
            projection_edge_id: "canvas_edge:graph:rgedge_policy_signal",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody({ withSecondQro: true, includeGraphEdge: !deleted })));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const edgeSelector = "[data-edge-id='canvas_edge:graph:rgedge_policy_signal']";
    await waitFor(() => expect(container.querySelector(edgeSelector)).not.toBeNull());
    fireEvent.click(container.querySelector(edgeSelector) as SVGPathElement);
    fireEvent.click(screen.getByLabelText("记录 Graph 删除"));

    await waitFor(() => expect(screen.getByText(/已删除 Graph edge/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/edge_deletions");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"edge_ref":"rgedge_policy_signal"');
    expect(body).toContain("canonical:strategy_console_delete_graph_edge:rgedge_policy_signal");
    expect(body).not.toContain("canvas_node:");
    expect(body).not.toContain('"port"');
    expect(body).not.toContain('"from"');
    expect(body).not.toContain('"to"');
    expect(body).not.toContain("raw_value");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
    await waitFor(() => expect(container.querySelector(edgeSelector)).toBeNull());
  });

  it("真实投影下接受 Ghost proposal 会应用 Graph patch，且不提交 raw ops", async () => {
    let applied = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/patch_applications") {
        applied = true;
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "apply_graph_patch",
            patch_application_command_id: "rgcmd_apply_ghost",
            patch_qro_command_id: "rgcmd_patch_qro",
            graph_edge_command_id: "rgcmd_patch_edge",
            application_ref: "rgpatch_ghost",
            patch_qro_id: "qro_patch_ghost",
            target_qro_id: "qro_policy_1",
            patch_kind: "ghost",
            projection_node_id: "canvas_node:qro:qro_patch_ghost",
            projection_edge_id: "canvas_edge:graph:rgedge_patch_ghost",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody({
        includePatchApplication: applied ? "ghost" : undefined,
      })));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    await waitFor(() => expect(container.querySelector("[data-node-id='canvas_node:qro:qro_policy_1']")).not.toBeNull());
    fireEvent.change(screen.getByPlaceholderText("> 输入研究任务…"), { target: { value: "draft proposal" } });
    fireEvent.click(screen.getByText("↵ 发送"));
    await waitFor(() => expect(container.querySelector("[data-proposal]")).not.toBeNull());
    fireEvent.click(screen.getByText(/接受 Patch/));

    await waitFor(() => expect(screen.getByText(/Ghost patch 已应用到 Research Graph/)).toBeInTheDocument());
    expect(container.querySelector("[data-node-id='varcvar']")).toBeNull();
    await waitFor(() => expect(container.querySelector("[data-node-id='canvas_node:qro:qro_patch_ghost']")).not.toBeNull());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/patch_applications");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"target_qro_id":"qro_policy_1"');
    expect(body).toContain('"patch_kind":"ghost"');
    expect(body).toContain("canvas_patch:ghost:strategy_console:qro_policy_1:pt_4f1a");
    expect(body).toContain("hash_strategy_console_ghost_");
    expect(body).not.toContain("raw_value");
    expect(body).not.toContain("ops");
    expect(body).not.toContain("varcvar");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });

  it("真实投影下 Auto 会应用 Graph patch，且不提交 raw generated patch", async () => {
    let applied = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/patch_applications") {
        applied = true;
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "apply_graph_patch",
            patch_application_command_id: "rgcmd_apply_auto",
            patch_qro_command_id: "rgcmd_patch_auto_qro",
            graph_edge_command_id: "rgcmd_patch_auto_edge",
            application_ref: "rgpatch_auto",
            patch_qro_id: "qro_patch_auto",
            target_qro_id: "qro_policy_1",
            patch_kind: "auto",
            projection_node_id: "canvas_node:qro:qro_patch_auto",
            projection_edge_id: "canvas_edge:graph:rgedge_patch_auto",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody({
        includePatchApplication: applied ? "auto" : undefined,
      })));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    await waitFor(() => expect(container.querySelector("[data-node-id='canvas_node:qro:qro_policy_1']")).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: "Auto" }));
    fireEvent.change(screen.getByPlaceholderText("> 输入研究任务…"), { target: { value: "add guard" } });
    fireEvent.click(screen.getByText("↵ 发送"));

    await waitFor(() => expect(screen.getByText(/Auto patch 已应用到 Research Graph/)).toBeInTheDocument());
    expect(container.querySelector("[data-node-id='ddguard']")).toBeNull();
    await waitFor(() => expect(container.querySelector("[data-node-id='canvas_node:qro:qro_patch_auto']")).not.toBeNull());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/patch_applications");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain('"target_qro_id":"qro_policy_1"');
    expect(body).toContain('"patch_kind":"auto"');
    expect(body).toContain("canvas_patch:auto:strategy_console:qro_policy_1:pt_auto");
    expect(body).toContain("hash_strategy_console_auto_");
    expect(body).not.toContain("raw_value");
    expect(body).not.toContain("DrawdownGuard");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });

  it("选中真实投影连线后可记录 canonical edge relation，且不提交 raw edge payload", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/canvas_asset_mutations") {
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "execute_canvas_asset_mutation",
            mutation_command_id: "rgcmd_edge_mut",
            qro_command_id: "rgcmd_edge_qro",
            qro_id: "qro_policy_1",
            qro_version: 3,
            projection_ref: "rgproj_edge",
            updated_field_path: "output_contract.canvas_edge_ref",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody()));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const edgeSelector = "[data-edge-id='canvas_edge:cmd_1:qro_policy_1']";
    await waitFor(() => expect(container.querySelector(edgeSelector)).not.toBeNull());
    fireEvent.click(container.querySelector(edgeSelector) as SVGPathElement);
    fireEvent.click(screen.getByLabelText("记录 Graph 连线"));

    await waitFor(() => expect(screen.getByText(/已写入 QRO v3/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/canvas_asset_mutations");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain("output_contract.canvas_edge_ref");
    expect(body).toContain("canvas_edge:strategy_console:qro_policy_1:canvas_edge:cmd_1:qro_policy_1");
    expect(body).toContain("hash_strategy_console_edge_");
    expect(body).not.toContain('"from"');
    expect(body).not.toContain('"to"');
    expect(body).not.toContain("raw_value");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });

  it("选中真实投影连线后可记录删除 ref/hash，且不提交 raw edge payload", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/research-os/graph/canvas_asset_mutations") {
        return Promise.resolve(
          jsonResponse({
            accepted: true,
            command_type: "execute_canvas_asset_mutation",
            mutation_command_id: "rgcmd_edge_delete_mut",
            qro_command_id: "rgcmd_edge_delete_qro",
            qro_id: "qro_policy_1",
            qro_version: 6,
            projection_ref: "rgproj_edge_delete",
            updated_field_path: "output_contract.canvas_delete_ref",
            recorded_by: "tester",
          }),
        );
      }
      return Promise.resolve(jsonResponse(researchGraphProjectionBody()));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPage();

    const edgeSelector = "[data-edge-id='canvas_edge:cmd_1:qro_policy_1']";
    await waitFor(() => expect(container.querySelector(edgeSelector)).not.toBeNull());
    fireEvent.click(container.querySelector(edgeSelector) as SVGPathElement);
    fireEvent.click(screen.getByLabelText("记录 Graph 删除"));

    await waitFor(() => expect(screen.getByText(/已写入 QRO v6/)).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find((call) => String(call[0]) === "/api/research-os/graph/canvas_asset_mutations");
    expect(postCall).toBeTruthy();
    const body = String((postCall![1] as RequestInit).body);
    expect(body).toContain("output_contract.canvas_delete_ref");
    expect(body).toContain("canvas_delete:strategy_console:qro_policy_1:edge:canvas_edge:cmd_1:qro_policy_1");
    expect(body).toContain("hash_strategy_console_delete_");
    expect(body).not.toContain('"from"');
    expect(body).not.toContain('"to"');
    expect(body).not.toContain("raw_value");
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).startsWith("/api/research-os/graph/canvas_projection")).length).toBe(2);
  });
});

describe("S1 治理逻辑 · 连线门/校验门（B6 三层强制）", () => {
  it("连线门 compat：role='exec' 来源非 approvedPortfolio → bad（不可绕 Final Gate）", () => {
    // exec 入口 dt=approvedPortfolio（与 Final Gate 输出一致，DC exec.ins）。
    const execIn: DomainPort = { id: "ap", name: "approvedPortfolio", dt: "approvedPortfolio", freq: "W", scope: "", req: true, role: "exec", schema: "" };
    const fromGate: DomainPort = { id: "ap", name: "approvedPortfolio", dt: "approvedPortfolio", freq: "W", scope: "", req: true, role: "", schema: "" };
    const fromOther: DomainPort = { id: "rp", name: "riskedPortfolio", dt: "riskedPortfolio", freq: "W", scope: "", req: true, role: "", schema: "" };
    expect(compat(fromGate, execIn).s).toBe("ok");
    expect(compat(fromOther, execIn).s).toBe("bad");
    expect(compat(fromOther, execIn).reason).toMatch(/Final Risk Gate/);
  });

  it("校验门 validateGraph：完整初始图 ok（exec 经 gate，无 bad）", () => {
    const v = validateGraph(toDict(), MOCK_EDGES);
    expect(v.ok).toBe(true);
    expect(v.errorCount).toBe(0);
  });

  it("校验门：把 exec 入边改接 prisk（绕过 gate）→ error 违反 B6", () => {
    const broken = MOCK_EDGES.map((e) =>
      e.id === "e17" ? { ...e, from: { node: "prisk", port: "rp" } } : e,
    );
    const v = validateGraph(toDict(), broken);
    expect(v.ok).toBe(false);
    expect(v.issues.some((i) => /B6/.test(i.text))).toBe(true);
  });

  it("adapt 频率门：bench(D) → backtest(b) 日频→周频或类型适配（非 bad）", () => {
    const v = validateGraph(toDict(), MOCK_EDGES);
    // e19 是 adapt，不应产生 bad error
    expect(v.issues.some((i) => /不兼容/.test(i.text))).toBe(false);
  });
});

describe("S1 Agent 权限三态 · 提议/事务化", () => {
  it("Ask：默认挂 Ghost 提议卡 + 画布出 ghost 虚线边；接受后 patch 块入对话", () => {
    const { container } = renderPage();
    expect(container.querySelector("[data-proposal]")).not.toBeNull();
    // ghost 边渲染
    expect(container.querySelector("[data-ghost-edge-id='e_var']")).not.toBeNull();
    fireEvent.click(screen.getByText(/接受 Patch/));
    // 提议消失 + 新增 varcvar 节点
    expect(container.querySelector("[data-proposal]")).toBeNull();
    expect(container.querySelector("[data-node-id='varcvar']")).not.toBeNull();
    expect(screen.getByText(MOCK_PROPOSAL.patchId)).toBeInTheDocument();
  });

  it("拒绝提议 → 提议卡消失、不加节点", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByText("拒绝"));
    expect(container.querySelector("[data-proposal]")).toBeNull();
    expect(container.querySelector("[data-node-id='varcvar']")).toBeNull();
  });
});

describe("S1 视口 · 缩放/适应", () => {
  it("放大按钮 → zoom 上升（zoomPct 变化）", () => {
    const { container } = renderPage();
    const pct = () => (container.querySelector("[data-zoom-pct]") as HTMLElement).textContent;
    const before = pct();
    fireEvent.click(screen.getByLabelText("放大"));
    expect(pct()).not.toBe(before);
  });
});

describe("S1 对抗：mockGraph/页面源码禁裸 hex（须走 --desk-* token）", () => {
  it("strategy/ + StrategyConsolePage 不含 #hex 字面色", () => {
    const files: string[] = [];
    for (const f of readdirSync(here)) {
      if (/\.tsx?$/.test(f) && !f.includes(".test.")) files.push(join(here, f));
    }
    files.push(join(pageSrcDir, "StrategyConsolePage.tsx"));
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(f, "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });
});

describe("S1 mock 数据完整性（DC _build 对齐）", () => {
  it("17 节点含 gate(locked) / backtest(openRun) / 因子台·Model台 badge（DC defs[] 真值）", () => {
    expect(MOCK_NODES.length).toBe(17);
    expect(MOCK_NODES.find((n) => n.id === "gate")?.locked).toBe(true);
    expect(MOCK_NODES.find((n) => n.id === "backtest")?.openRun).toBe(true);
    expect(MOCK_NODES.find((n) => n.id === "factors")?.badge).toBe("← 因子台");
    expect(MOCK_NODES.find((n) => n.id === "model")?.badge).toBe("← Model台");
  });

  it("toNodeView 投影出渲染子集（含 locked/badge）", () => {
    const v = toNodeView(MOCK_NODES.find((n) => n.id === "gate")!);
    expect(v.locked).toBe(true);
    expect(v.title).toBe("Final Risk Gate");
    expect(v.ins.length).toBe(1);
  });

  it("19 连线 + 唯一 id", () => {
    expect(MOCK_EDGES.length).toBe(19);
    expect(new Set(MOCK_EDGES.map((e) => e.id)).size).toBe(19);
  });
});
