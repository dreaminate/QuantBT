import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";

import { renderWithDesk } from "../../test/harness";
import ModelSwitcher from "./ModelSwitcher";

/**
 * 跨厂商切模型 S7 · 每对话模型切换器测试。
 * 守：列 Auto 顶项 + 已 auth 厂商可选模型(分组,未 auth/非聊天不显示)、初始回显 GET selection、
 * 选中即 PATCH 正确 body(pinned / auto)。凭据从不经前端(只传 provider/model 名)。
 */

function login() {
  localStorage.setItem("qb-auth-token", "tok");
  localStorage.setItem("qb-auth-user", JSON.stringify({ user_id: "u1", username: "t" }));
}

const MODELS = {
  providers: [
    {
      provider: "openai",
      auth_kind: "api_key",
      authed: true,
      selectable: true,
      models: [
        { model: "gpt-4o", tier: "strong", selectable: true },
        { model: "text-embedding-3", selectable: false },
      ],
    },
    {
      provider: "anthropic",
      auth_kind: "api_key",
      authed: true,
      selectable: true,
      models: [{ model: "claude-opus-4-8", tier: "strong", selectable: true }],
    },
    { provider: "qwen", auth_kind: "none", authed: false, selectable: false, models: [] },
    // 订阅厂商:目录里 authed+selectable,但 gateway 未接订阅、PATCH 会 409 → 切换器必须**不显示**它。
    {
      provider: "anthropic-sub-fixture",
      auth_kind: "subscription_cli",
      authed: true,
      selectable: true,
      models: [{ model: "claude-sub-only", selectable: true, supports_tools: false }],
    },
  ],
};

function stubFetch(selection: Record<string, unknown> = { mode: "auto" }, patchCapture?: Record<string, unknown>[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/api/llm/models")) {
        return Promise.resolve(new Response(JSON.stringify(MODELS), { status: 200 }));
      }
      if (u.includes("/llm-selection")) {
        if (init?.method === "PATCH") {
          const body = JSON.parse(String(init.body));
          patchCapture?.push(body);
          const saved = body.mode === "auto" ? { mode: "auto" } : body;
          return Promise.resolve(new Response(JSON.stringify({ thread_id: "t1", llm_selection: saved }), { status: 200 }));
        }
        return Promise.resolve(new Response(JSON.stringify({ thread_id: "t1", llm_selection: selection }), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }),
  );
}

beforeEach(login);
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function sel(container: HTMLElement): HTMLSelectElement {
  return container.querySelector("[data-model-select]") as HTMLSelectElement;
}

describe("ModelSwitcher · 每对话切模型", () => {
  it("列 Auto 顶项 + 已 auth 厂商可选模型(分组);未 auth/非聊天模型不显示", async () => {
    stubFetch();
    const { container } = renderWithDesk(<ModelSwitcher threadId="t1" />);
    await waitFor(() => expect(sel(container).querySelectorAll("optgroup").length).toBe(2));
    const opts = Array.from(sel(container).querySelectorAll("option")).map((o) => o.value);
    expect(opts).toContain("__auto__"); // Auto 顶项
    expect(opts).toContain("openai::gpt-4o");
    expect(opts).toContain("anthropic::claude-opus-4-8");
    expect(opts).not.toContain("openai::text-embedding-3"); // 非聊天模型不可选
    expect(sel(container).querySelector('optgroup[label="qwen"]')).toBeNull(); // 未 auth 厂商不显示
    // 订阅厂商(auth_kind=subscription_cli)不显示——gateway 未接订阅,选了会 409(避免误导 UX)
    expect(sel(container).querySelector('optgroup[label="anthropic-sub-fixture"]')).toBeNull();
    expect(opts).not.toContain("anthropic-sub-fixture::claude-sub-only");
  });

  it("初始回显 GET 的 pinned selection", async () => {
    stubFetch({ mode: "pinned", provider: "openai", model: "gpt-4o" });
    const { container } = renderWithDesk(<ModelSwitcher threadId="t1" />);
    await waitFor(() => expect(sel(container).value).toBe("openai::gpt-4o"));
  });

  it("选某模型 → PATCH {mode:pinned,provider,model}", async () => {
    const patches: Record<string, unknown>[] = [];
    stubFetch({ mode: "auto" }, patches);
    const { container } = renderWithDesk(<ModelSwitcher threadId="t1" />);
    await waitFor(() => expect(sel(container).querySelectorAll("option").length).toBeGreaterThan(1));
    fireEvent.change(sel(container), { target: { value: "anthropic::claude-opus-4-8" } });
    await waitFor(() =>
      expect(patches).toContainEqual({ mode: "pinned", provider: "anthropic", model: "claude-opus-4-8" }),
    );
  });

  it("选 Auto → PATCH {mode:auto}", async () => {
    const patches: Record<string, unknown>[] = [];
    stubFetch({ mode: "pinned", provider: "openai", model: "gpt-4o" }, patches);
    const { container } = renderWithDesk(<ModelSwitcher threadId="t1" />);
    await waitFor(() => expect(sel(container).value).toBe("openai::gpt-4o"));
    fireEvent.change(sel(container), { target: { value: "__auto__" } });
    await waitFor(() => expect(patches).toContainEqual({ mode: "auto" }));
  });

  it("stale pin(不在目录)仍显示当前项,不空白", async () => {
    stubFetch({ mode: "pinned", provider: "openai", model: "gpt-legacy-removed" });
    const { container } = renderWithDesk(<ModelSwitcher threadId="t1" />);
    await waitFor(() => expect(sel(container).value).toBe("openai::gpt-legacy-removed"));
  });
});
