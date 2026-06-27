import { afterEach, describe, expect, it, vi } from "vitest";
import { authFetch } from "./auth";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("authFetch", () => {
  it("does not force JSON content-type for FormData uploads", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchSpy);
    const body = new FormData();
    body.set("file", new Blob(["uploaded note"], { type: "text/markdown" }), "upload.md");

    await authFetch("/api/research-os/documents/parse_upload", { method: "POST", body });

    const [, init] = fetchSpy.mock.calls[0] as [RequestInfo, RequestInit];
    expect(new Headers(init.headers).has("content-type")).toBe(false);
  });
});
