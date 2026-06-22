import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../test/harness";
import { LLMSettingsPage } from "./LLMSettingsPage";

/**
 * DS-2 · LLM 配置页测试：复用已有 POST /api/llm/configure + GET /api/llm/status，
 * 含 Hermes 预设（custom + http://localhost:<port>/v1）。
 *
 * 守的红线：
 *  · 提交真打 /api/llm/configure（单一源端点，不另造）。
 *  · custom 缺 base_url/model 前端先拦（与后端 400 口径一致）。
 *  · Hermes 预设把 provider 切 custom + 预填本地代理 base_url（引导用订阅额度，不自实现 OAuth）。
 *  · 诚实状态：只声明「配置已写入」，不伪装成「已连通真模型」（§3 不假绿灯）。
 */

function login() {
  localStorage.setItem("qb-auth-token", "tok");
  localStorage.setItem(
    "qb-auth-user",
    JSON.stringify({ user_id: "u1", username: "tester", display_name: "T" }),
  );
}

beforeEach(() => {
  login();
  // 默认 fetch 兜底：status 空、configure 成功。
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ providers: [] }), { status: 200 }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ configured: "anthropic" }), { status: 200 }),
      );
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("LLMSettingsPage · 配置流程", () => {
  it("anthropic 填 api_key → 保存真打 POST /api/llm/configure（含 provider+api_key）", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ configured: "anthropic", model: "claude-sonnet-4.5" }), {
          status: 200,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    fireEvent.change(container.querySelector("[data-api-key]") as HTMLElement, {
      target: { value: "sk-ant-xyz" },
    });
    fireEvent.click(container.querySelector("[data-configure-submit]") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/llm/configure"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.provider).toBe("anthropic");
      expect(body.api_key).toBe("sk-ant-xyz");
    });
  });

  it("Hermes 预设：切 custom + 预填 http://localhost:<port>/v1，保存后 base_url 进 configure body", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ configured: "custom", model: "claude-sonnet-4.5" }), {
          status: 200,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    fireEvent.click(container.querySelector("[data-hermes-apply]") as HTMLElement);

    // 预设切 custom 并预填本地代理地址 + 模型占位。
    const baseUrl = container.querySelector("[data-base-url]") as HTMLInputElement;
    const model = container.querySelector("[data-model]") as HTMLInputElement;
    expect(baseUrl).not.toBeNull();
    expect(baseUrl.value).toMatch(/^http:\/\/localhost:\d+\/v1$/);
    expect(model.value.length).toBeGreaterThan(0);

    fireEvent.click(container.querySelector("[data-configure-submit]") as HTMLElement);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/llm/configure"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.provider).toBe("custom");
      expect(body.base_url).toMatch(/^http:\/\/localhost:\d+\/v1$/);
      expect(body.model.length).toBeGreaterThan(0);
    });
  });

  it("对抗：custom 缺 base_url/model 不得打 configure（前端先拦，与后端 400 口径一致）", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    // 切到 custom 但不填 base_url/model。
    fireEvent.change(container.querySelector("[data-provider-select]") as HTMLElement, {
      target: { value: "custom" },
    });
    const submit = container.querySelector("[data-configure-submit]") as HTMLButtonElement;
    // 提交按钮禁用（custom 不全）。
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    // 即便强点也绝不打 configure（disabled + 前端守卫双保险）。
    const configureCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/api/llm/configure"),
    );
    expect(configureCalls.length).toBe(0);
  });

  it("诚实状态（§3 不假绿灯）：configure 成功只声明『已写入配置』，不声称『已连通真模型』", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ configured: "anthropic", model: "claude" }), { status: 200 }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    fireEvent.change(container.querySelector("[data-api-key]") as HTMLElement, {
      target: { value: "sk-ant-xyz" },
    });
    fireEvent.click(container.querySelector("[data-configure-submit]") as HTMLElement);

    await waitFor(() => {
      const r = container.querySelector("[data-configure-result]");
      expect(r).not.toBeNull();
      const text = (r as HTMLElement).textContent ?? "";
      expect(text).toMatch(/已写入配置/);
      // 不得把「写入 keystore」伪装成「已连通真模型」。
      expect(text).not.toMatch(/已连通真模型|连接成功|模型可用/);
    });
  });

  it("configure 失败 → 诚实显示错误（不假绿灯）", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ detail: "anthropic 必须填 api_key" }), { status: 400 }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    // anthropic 不填 key 直接提交 → 前端先拦显示错误（不打端点）。
    fireEvent.click(container.querySelector("[data-configure-submit]") as HTMLElement);
    await waitFor(() => {
      const r = container.querySelector("[data-configure-result]");
      expect(r).not.toBeNull();
      expect((r as HTMLElement).textContent).toMatch(/必须填 api_key/);
    });
  });
});
