import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";
import { AgentWorkbenchPage } from "./AgentWorkbenchPage";
import { streamAgentWorkbench } from "./agentLive";

/**
 * A4 真实流测试：研究执行台 LIVE 模式（真 /api/agent/workbench/stream）+ handoff
 * 真调 /api/strategy/submit_candidate（止于模拟盘）。
 *
 * 治理红线（与后端对抗测试对齐）：
 *  · gate 的 side_effect 是后端真值，agentLive 原样透传（不前端伪造）。
 *  · handoff destination 钉死 paper_desk——前端绝不传 live/mainnet（直推实盘=跳级）。
 */

// 用 ReadableStream 造一个 SSE 响应体（供 fetch mock 返回）。
function sseResponse(frames: string[]): Response {
  const body = frames.map((f) => f + "\n\n").join("");
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

describe("agentLive · SSE 事件投影（纯逻辑，无真网络）", () => {
  it("把后端结构化事件投影成 blocks + 里程碑 + done", async () => {
    const blocks: { type: string; tool?: string; sideEffect?: string }[] = [];
    const milestones: string[] = [];
    let done = false;
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        'event: user\ndata: {"text":"组装策略"}',
        'event: thinking\ndata: {"text":"先立题"}',
        'event: tool_start\ndata: {"tool":"hypothesis.create","side_effect":"none"}',
        'event: tool_end\ndata: {"result":{"card_id":"card_x"}}',
        'event: milestone\ndata: {"key":"立题","tool":"hypothesis.create"}',
        'event: done\ndata: {"final_message":"ok","succeeded":true}',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      streamAgentWorkbench("组装策略", "ask", {
        onBlock: (b) => blocks.push({ type: b.type, tool: b.toolName, sideEffect: b.sideEffect }),
        onToolEnd: () => {},
        onMilestone: (k) => milestones.push(k),
        onDone: () => {
          done = true;
          resolve();
        },
        onError: () => resolve(),
      });
    });

    expect(blocks.some((b) => b.type === "user")).toBe(true);
    expect(blocks.some((b) => b.type === "tool" && b.tool === "hypothesis.create")).toBe(true);
    expect(milestones).toContain("立题");
    expect(done).toBe(true);
  });

  it("gate 事件透传后端真 side_effect（realmoney 不被前端改写）", async () => {
    const gates: { tool?: string; sideEffect?: string; weakness?: boolean }[] = [];
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        'event: gate\ndata: {"tool":"order.submit","side_effect":"realmoney","governance_weakness":true}',
        'event: done\ndata: {"final_message":"","succeeded":false}',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      streamAgentWorkbench("x", "bypass", {
        onBlock: (b) => {
          if (b.type === "gate")
            gates.push({ tool: b.gateTool, sideEffect: b.sideEffect, weakness: b.governanceWeakness });
        },
        onToolEnd: () => {},
        onMilestone: () => {},
        onDone: () => resolve(),
        onError: () => resolve(),
      });
    });

    expect(gates.length).toBe(1);
    expect(gates[0].sideEffect).toBe("realmoney");
    expect(gates[0].weakness).toBe(true);
  });

  it("流非 200 → onError（诚实呈现，不假绿灯）", async () => {
    let err = "";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 500 })));
    await new Promise<void>((resolve) => {
      streamAgentWorkbench("x", "ask", {
        onBlock: () => {},
        onToolEnd: () => {},
        onMilestone: () => {},
        onDone: () => resolve(),
        onError: (m) => {
          err = m;
          resolve();
        },
      });
    });
    expect(err).toContain("500");
  });
});

describe("AgentWorkbenchPage · 真实流开关 + handoff 真端点", () => {
  beforeEach(() => {
    // 给个安全的 fetch 兜底（默认真实流挂载即起真流；mock 它避免真网络）。
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse(['event: done\ndata: {"final_message":"","succeeded":true}']),
      ),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("DS-2 默认真实流：LIVE badge 在、顶栏 MockBadge（「MOCK 数据」）不在 + 挂载即调真 stream", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(['event: done\ndata: {"final_message":"","succeeded":true}']),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    expect(container.querySelector("[data-live-badge]")).not.toBeNull();
    expect(screen.queryByText("MOCK 数据")).toBeNull();
    // 默认真实流 → 挂载即调真 workbench stream 端点（不放 mock 假绿灯）。
    await waitFor(() => {
      const called = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(called.some((u) => u.includes("/api/agent/workbench/stream"))).toBe(true);
    });
  });

  it("点「看演示」→ 切 demo（MockBadge 出现、LIVE badge 消失，mock 剧本回放）", async () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    fireEvent.click(container.querySelector("[data-demo-toggle]") as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
    });
    expect(container.querySelector("[data-live-badge]")).toBeNull();
    // 演示态铺了 mock 剧本（首条 prompt 在）。
    expect(screen.getByText(/组装一个 A股周频多因子策略/)).toBeInTheDocument();
  });

  it("handoff 提交真调 /api/strategy/submit_candidate（destination=paper_desk，不直推实盘）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ candidate_id: "cand_x", destination: "paper_desk" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    // handoff 是「看演示」剧本终点（mock 回放跑到回测拍板才解锁）→ 先进演示。
    fireEvent.click(container.querySelector("[data-demo-toggle]") as HTMLElement);
    // 跑到回测拍板（解锁 handoff）。
    fireEvent.click(screen.getByText("1. 批准本次"));
    const submit = await screen.findByText(/提交进模拟台候选/);
    fireEvent.click(submit);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/strategy/submit_candidate"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.destination).toBe("paper_desk");
      // 前端绝不传实盘目的地（直推实盘=跳级，D-PERM）。
      expect(["live", "mainnet", "realmoney"]).not.toContain(body.destination);
    });
  });

  // DS-2 blocker #1 回归门：默认真实流态下发消息绝不落 mock 块（不假绿灯）。
  it("对抗：真实流态发真消息 → 驱动真流（调 stream 端点），绝不注入 mock 「看演示」ack 块", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(['event: done\ndata: {"final_message":"","succeeded":true}']),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithDesk(<AgentWorkbenchPage />); // 默认 liveMode=true
    const box = screen.getByPlaceholderText("回复，或 / 命令…");
    fireEvent.change(box, { target: { value: "把回撤收紧到 15%" } });
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => {
      const called = fetchMock.mock.calls.map((c) => String(c[0]));
      // 用户消息进了真 stream 端点（q=...）。
      expect(
        called.some(
          (u) =>
            u.includes("/api/agent/workbench/stream") &&
            u.includes(encodeURIComponent("把回撤收紧到 15%")),
        ),
      ).toBe(true);
    });
    // 绝不出现 mock「看演示」假绿灯 ack 文案。
    expect(screen.queryByText(/看演示 mock：策略台脚本已跑到回测拍板/)).toBeNull();
  });

  it("对抗：真实流态 /clear → 重起真流（不铺 mock 剧本，不出现首条 mock prompt）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(['event: done\ndata: {"final_message":"","succeeded":true}']),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    const box = screen.getByPlaceholderText("回复，或 / 命令…");
    fireEvent.change(box, { target: { value: "/clear" } });
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => {
      const called = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(called.some((u) => u.includes("/api/agent/workbench/stream"))).toBe(true);
    });
    // LIVE 态 /clear 绝不铺 mock 剧本 + 仍是 LIVE 标。
    expect(screen.queryByText(/组装一个 A股周频多因子策略/)).toBeNull();
    expect(container.querySelector("[data-live-badge]")).not.toBeNull();
  });
});
