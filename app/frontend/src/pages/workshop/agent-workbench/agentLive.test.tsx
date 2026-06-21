import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";
import { AgentWorkbenchPage } from "./AgentWorkbenchPage";
import { streamAgentWorkbench } from "./agentLive";

/**
 * A4 接真测试：agent 工作台 LIVE 模式（真 /api/agent/workbench/stream）+ handoff
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

describe("AgentWorkbenchPage · 接真开关 + handoff 真端点", () => {
  beforeEach(() => {
    // 默认 mock 模式不发请求；给个安全的 fetch 兜底。
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 200 })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("默认 mock 模式：MockBadge 在、LIVE badge 不在", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    expect(screen.getAllByText(/MOCK/).length).toBeGreaterThan(0);
    expect(container.querySelector("[data-live-badge]")).toBeNull();
  });

  it("点接真开关 → 切 LIVE 模式（LIVE badge 出现）+ 调真 stream 端点", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(['event: done\ndata: {"final_message":"","succeeded":true}']),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    fireEvent.click(container.querySelector("[data-live-toggle]") as HTMLElement);
    await waitFor(() => {
      expect(container.querySelector("[data-live-badge]")).not.toBeNull();
    });
    // 调了真 workbench stream 端点。
    const called = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(called.some((u) => u.includes("/api/agent/workbench/stream"))).toBe(true);
  });

  it("handoff 提交真调 /api/strategy/submit_candidate（destination=paper_desk，不直推实盘）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ candidate_id: "cand_x", destination: "paper_desk" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithDesk(<AgentWorkbenchPage />);
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
});
