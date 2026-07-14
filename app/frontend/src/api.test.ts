import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getRun, getRunSeries } from "./api";


afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});


function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}


describe("shared API authentication", () => {
  it("routes RunDetail and series reads through the stored Bearer token", async () => {
    localStorage.setItem("qb-auth-token", "test-access-token");
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ run_id: "demo" }))
      .mockResolvedValueOnce(jsonResponse({ available: true, points: [] }));
    vi.stubGlobal("fetch", fetchSpy);

    await getRun("demo");
    await getRunSeries("demo", "equity", "overall");

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls.map(([path]) => path)).toEqual([
      "/api/runs/demo",
      "/api/runs/demo/series?series=equity&segment=overall",
    ]);
    for (const [, init] of fetchSpy.mock.calls as [RequestInfo, RequestInit][]) {
      expect(new Headers(init.headers).get("authorization")).toBe("Bearer test-access-token");
    }
  });

  it("does not add Authorization to an external URL even when its path starts with /api", async () => {
    localStorage.setItem("qb-auth-token", "must-not-leak");
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchSpy);

    await apiFetch("https://external.invalid/api/runs/demo");

    const [, init] = fetchSpy.mock.calls[0] as [RequestInfo, RequestInit];
    expect(new Headers(init.headers).has("authorization")).toBe(false);
  });

  it("preserves anonymous same-origin API reads when no session exists", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchSpy);

    await apiFetch("/api/public/status");

    const [, init] = fetchSpy.mock.calls[0] as [RequestInfo, RequestInit];
    expect(new Headers(init.headers).has("authorization")).toBe(false);
  });

  it("surfaces a 401 detail without retrying, clearing the token, or logging it", async () => {
    localStorage.setItem("qb-auth-token", "retained-test-token");
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({ detail: "Not authenticated" }, 401));
    vi.stubGlobal("fetch", fetchSpy);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(getRun("demo")).rejects.toThrow("Not authenticated");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("qb-auth-token")).toBe("retained-test-token");
    expect(logSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
