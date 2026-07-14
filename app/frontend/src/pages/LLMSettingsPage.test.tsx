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
  it("状态卡显示 Settings Gateway refs，但不显示 API key", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              providers: [
                {
                  provider: "anthropic",
                  configured: true,
                  model: "claude-sonnet-4.5",
                  settings_managed: true,
                  secret_ref: "secret:llm:anthropic",
                  credential_pool_ref: "llm_pool:anthropic",
                  routing_policy_ref: "llm_route:anthropic",
                  auth_status: "active",
                },
              ],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);

    await waitFor(() => {
      expect(container.textContent).toContain("Gateway 管理");
      expect(container.textContent).toContain("NoLLMConfigured");
      expect(container.textContent).not.toContain("后端回退到开发期本地模型");
      expect(container.textContent).toContain("secret:llm:anthropic");
      expect(container.textContent).toContain("llm_pool:anthropic");
      expect(container.textContent).toContain("llm_route:anthropic");
      expect(container.textContent).not.toContain("sk-ant");
    });
  });

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

  it("配置成功回执只显示 Settings refs，不声称已连通", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            configured: "anthropic",
            model: "claude-sonnet-4.5",
            settings_refs: {
              secret_ref: "secret:llm:anthropic",
              credential_pool_ref: "llm_pool:anthropic",
              routing_policy_ref: "llm_route:anthropic",
            },
          }),
          { status: 200 },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    fireEvent.change(container.querySelector("[data-api-key]") as HTMLElement, {
      target: { value: "sk-ant-xyz" },
    });
    fireEvent.click(container.querySelector("[data-configure-submit]") as HTMLElement);

    await waitFor(() => {
      const text = (container.querySelector("[data-configure-result]") as HTMLElement).textContent ?? "";
      expect(text).toContain("SecretRef=secret:llm:anthropic");
      expect(text).toContain("Settings metadata");
      expect(text).not.toMatch(/已连通真模型|连接成功|模型可用/);
      expect(text).not.toContain("sk-ant-xyz");
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

  it("测试连接真打 /api/llm/test，并显示 provider 回复预览", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              providers: [
                {
                  provider: "anthropic",
                  configured: true,
                  settings_managed: true,
                  secret_ref: "secret:llm:anthropic",
                  credential_pool_ref: "llm_pool:anthropic",
                  routing_policy_ref: "llm_route:anthropic",
                  auth_status: "active",
                },
              ],
            }),
            { status: 200 },
          ),
        );
      }
      if (String(url).includes("/api/llm/test")) {
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true, provider: "anthropic", reply_preview: "ok" }), {
            status: 200,
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    await waitFor(() => {
      expect(container.querySelector("[data-test-provider='anthropic']")).not.toBeNull();
    });
    fireEvent.click(container.querySelector("[data-test-provider='anthropic']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/api/llm/test"));
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.provider).toBe("anthropic");
      expect((container.querySelector("[data-connection-test-result]") as HTMLElement).textContent).toContain("✓ anthropic: ok");
    });
  });

  it("测试连接失败时显示 Gateway 错误，不报成功", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              providers: [
                {
                  provider: "anthropic",
                  configured: true,
                  settings_managed: true,
                  secret_ref: "secret:llm:anthropic",
                  credential_pool_ref: "llm_pool:anthropic",
                  routing_policy_ref: "llm_route:anthropic",
                  auth_status: "revoked",
                },
              ],
            }),
            { status: 200 },
          ),
        );
      }
      if (String(url).includes("/api/llm/test")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ok: false,
              provider: "anthropic",
              error: "NoLLMConfigured: LLM Gateway route rejected for anthropic",
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    await waitFor(() => {
      expect(container.querySelector("[data-test-provider='anthropic']")).not.toBeNull();
    });
    fireEvent.click(container.querySelector("[data-test-provider='anthropic']") as HTMLElement);

    await waitFor(() => {
      const text = (container.querySelector("[data-connection-test-result]") as HTMLElement).textContent ?? "";
      expect(text).toContain("✗ anthropic");
      expect(text).toContain("LLM Gateway route rejected");
      expect(text).not.toContain("✓");
    });
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

  it("health snapshot：基于 Settings provider/auth_ref 只提交 refs/hash-only payload", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (String(url).includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              llm_providers: [
                {
                  provider_id: "openai",
                  auth_refs: ["secretref:openai:project"],
                  health_status: "unknown",
                  quota_status: "unknown",
                },
              ],
              llm_provider_health_snapshots: [],
            }),
            { status: 200 },
          ),
        );
      }
      if (String(url).includes("/api/research-os/settings/llm_provider_health_snapshots")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              snapshot_ref: "llm_health:openai:001",
              snapshot_hash: "sha16:healthsnapshot",
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    await waitFor(() => {
      expect((container.querySelector("[data-health-provider-select]") as HTMLSelectElement).value).toBe("openai");
      expect((container.querySelector("[data-health-auth-ref]") as HTMLSelectElement).value).toBe(
        "secretref:openai:project",
      );
    });

    fireEvent.change(container.querySelector("[data-health-status]") as HTMLElement, {
      target: { value: "degraded" },
    });
    fireEvent.change(container.querySelector("[data-quota-status]") as HTMLElement, {
      target: { value: "limited" },
    });
    fireEvent.change(container.querySelector("[data-health-latency]") as HTMLElement, {
      target: { value: "123" },
    });
    fireEvent.change(container.querySelector("[data-health-response-hash]") as HTMLElement, {
      target: { value: "sha16:providerping" },
    });
    fireEvent.change(container.querySelector("[data-health-capability-refs]") as HTMLElement, {
      target: { value: "capability:tool_calling, capability:structured_output" },
    });
    fireEvent.change(container.querySelector("[data-health-evidence-refs]") as HTMLElement, {
      target: { value: "evidence:llm-health-check" },
    });
    fireEvent.click(container.querySelector("[data-health-snapshot-submit]") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/llm_provider_health_snapshots"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.provider_id).toBe("openai");
      expect(body.auth_ref).toBe("secretref:openai:project");
      expect(body.health_status).toBe("degraded");
      expect(body.quota_status).toBe("limited");
      expect(body.latency_ms).toBe(123);
      expect(body.response_hash).toBe("sha16:providerping");
      expect(body.capability_refs).toEqual(["capability:tool_calling", "capability:structured_output"]);
      expect(body.evidence_refs).toEqual(["evidence:llm-health-check"]);
      expect(Object.keys(body).join(" ")).not.toMatch(/api_key|token|secret|raw_response|raw_payload/);
    });

    await waitFor(() => {
      expect((container.querySelector("[data-health-snapshot-result]") as HTMLElement).textContent).toContain(
        "snapshot 已记录",
      );
    });
  });

  it("health snapshot：缺 auth_ref 时前端阻断，不打 snapshot API", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (String(url).includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              llm_providers: [{ provider_id: "openai", auth_refs: [] }],
              llm_provider_health_snapshots: [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    await waitFor(() => {
      expect((container.querySelector("[data-health-provider-select]") as HTMLSelectElement).value).toBe("openai");
    });
    fireEvent.change(container.querySelector("[data-health-response-hash]") as HTMLElement, {
      target: { value: "sha16:providerping" },
    });

    const submit = container.querySelector("[data-health-snapshot-submit]") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    expect(
      fetchMock.mock.calls.filter((c) =>
        String(c[0]).includes("/api/research-os/settings/llm_provider_health_snapshots"),
      ),
    ).toHaveLength(0);
  });

  it("health snapshot：后端拒绝时显示失败，不假装记录成功", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (String(url).includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              llm_providers: [{ provider_id: "openai", auth_refs: ["secretref:openai:project"] }],
              llm_provider_health_snapshots: [],
            }),
            { status: 200 },
          ),
        );
      }
      if (String(url).includes("/api/research-os/settings/llm_provider_health_snapshots")) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "invalid_llm_provider_quota_status" }), {
            status: 422,
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<LLMSettingsPage />);
    await waitFor(() => {
      expect((container.querySelector("[data-health-auth-ref]") as HTMLSelectElement).value).toBe(
        "secretref:openai:project",
      );
    });
    fireEvent.change(container.querySelector("[data-health-response-hash]") as HTMLElement, {
      target: { value: "sha16:providerping" },
    });
    fireEvent.click(container.querySelector("[data-health-snapshot-submit]") as HTMLElement);

    await waitFor(() => {
      const text = (container.querySelector("[data-health-snapshot-result]") as HTMLElement).textContent ?? "";
      expect(text).toContain("记录失败 (422)");
      expect(text).toContain("invalid_llm_provider_quota_status");
      expect(text).not.toContain("✓");
    });
  });
});
