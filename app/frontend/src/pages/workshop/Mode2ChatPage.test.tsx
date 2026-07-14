import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import { renderWithDesk } from "../../test/harness";
import { Mode2ChatPage } from "./Mode2ChatPage";


function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}


function sseResponse(frame: string): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(frame + "\n\n"));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}


describe("Mode2ChatPage authenticated SSE", () => {
  beforeEach(() => {
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    localStorage.setItem("qb-auth-token", "session-token");
    localStorage.setItem(
      "qb-auth-user",
      JSON.stringify({ user_id: "u1", username: "u1", display_name: "User One" }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("uses the auth module token for the protected chat stream", async () => {
    const thread = {
      thread_id: "thr_owner",
      user_id: "u1",
      market_mode: "ashare_research",
      active_run_id: null,
      active_strategy_id: null,
      title: "",
      state: "ENTER_THREAD",
      created_at_utc: "2026-07-12T00:00:00Z",
      updated_at_utc: "2026-07-12T00:00:00Z",
    };
    const fetchMock = vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/agent/chat/threads") return jsonResponse([]);
      if (url === "/api/agent/chat/start") return jsonResponse(thread);
      if (url === "/api/agent/chat/thr_owner") {
        return jsonResponse({ thread, messages: [] });
      }
      if (url.startsWith("/api/agent/chat/thr_owner/stream?")) {
        const headers = new Headers(init?.headers);
        expect(headers.get("authorization")).toBe("Bearer session-token");
        return sseResponse('event: done\ndata: {"message_id":"msg_1"}');
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithDesk(<Mode2ChatPage />);
    fireEvent.click(await screen.findByRole("button", { name: "+ 新对话" }));
    const input = await screen.findByPlaceholderText("问任意量化问题（Enter 发送，Shift+Enter 换行）");
    fireEvent.change(input, { target: { value: "PBO 是什么" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("/stream?q=")),
      ).toBe(true);
    });
  });
});
