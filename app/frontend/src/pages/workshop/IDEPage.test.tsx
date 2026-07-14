import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as auth from "../../lib/auth";
import { IDEPage } from "./IDEPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function ideRun(runId: string, second: number, validationRefs: string[] = []) {
  return {
    run_id: runId,
    strategy_id: "strategy-1",
    owner_username: "owner",
    status: "ok",
    started_at_utc: `2026-07-14T00:00:${String(second).padStart(2, "0")}Z`,
    market_data_use_validation_refs: validationRefs,
    finished_at_utc: `2026-07-14T00:00:${String(second + 1).padStart(2, "0")}Z`,
    exit_code: 0,
    error: null,
    stdout_excerpt: "done",
    stderr_excerpt: "",
    duration_s: 1.25,
    result_keys: ["equity_curve", "metrics"],
  };
}

function validRdpManifestDraft(overrides: Record<string, unknown> = {}) {
  return {
    research_question: "Can this IDE strategy reproduce under governed evidence?",
    graph_refs: ["research_graph:ide-run"],
    data_refs: ["dataset:BTCUSDT_1d"],
    dataset_version_refs: ["dataset_version:BTCUSDT_1d:v1"],
    market_data_use_validation_refs: ["market_data_use:BTCUSDT_1d:backtest"],
    ingestion_skill_refs: ["ingestion_skill:binance:v1"],
    mathematical_refs: ["mathematical:momentum:v1"],
    theory_binding_refs: ["theory_binding:momentum:v1"],
    consistency_check_refs: ["consistency_check:momentum:v1"],
    code_refs: ["code:ide-strategy:v1"],
    environment_lock_ref: "environment_lock:ide:v1",
    test_refs: ["test:ide-strategy:v1"],
    honest_n_refs: ["honest_n:ide-strategy:v1"],
    cost_and_execution_assumptions: ["fees=10bps"],
    known_limits: ["offline sandbox only"],
    unverified_residuals: ["live slippage not observed"],
    verifier_verdict_ref: "verifier_verdict:ide-strategy:v1",
    compiler_artifact_refs: ["compiler_artifact:ide-strategy:v1"],
    mathematical_spine_chain_refs: ["math_spine_chain:ide-strategy:v1"],
    goal_entrypoint_coverage_refs: ["goal_entrypoint_coverage:ide-strategy:v1"],
    target_runtime: "offline",
    ...overrides,
  };
}

const owner = { user_id: "user-1", username: "owner", display_name: "Owner" };

function renderIDE() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<IDEPage />} />
        <Route path="/agent-workbench" element={<div>RDP workbench destination</div>} />
        <Route path="/runs/:runId" element={<div>promoted run destination</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function installBaseMocks(
  runs: ReturnType<typeof ideRun>[],
  manifestResponder: () => Promise<Response>,
) {
  vi.spyOn(auth, "getStoredUser").mockReturnValue(owner);
  const authFetch = vi.spyOn(auth, "authFetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url === "/api/ide/strategies") return Promise.resolve(jsonResponse([]));
    if (url === "/api/ide/runs?limit=20") return Promise.resolve(jsonResponse(runs));
    if (url === "/api/ide/ai_context") return Promise.resolve(jsonResponse(null));
    if (url === "/api/research-os/rdp/manifests") return manifestResponder();
    if (url.startsWith("/api/ide/runs/") && url.endsWith("/promote")) {
      return Promise.resolve(jsonResponse({ run_id: "formal-1", run_url: "/runs/formal-1" }));
    }
    throw new Error(`unexpected authFetch: ${url} ${String(init?.method ?? "GET")}`);
  });
  return authFetch;
}

describe("IDEPage formal promotion prerequisites", () => {
  beforeEach(() => {
    vi.stubGlobal("alert", vi.fn());
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ risk_summary: null })));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("loads owner-scoped summaries, keeps only exact dual bindings, and submits the selected package and label", async () => {
    const run = ideRun("ide-1", 1, ["market_data_use:BTCUSDT_1d:backtest"]);
    let resolveManifests!: (response: Response) => void;
    const manifestResponse = new Promise<Response>((resolve) => {
      resolveManifests = resolve;
    });
    const authFetch = installBaseMocks([run], () => manifestResponse);

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-1"));

    expect(await screen.findByTestId("ide-rdp-loading")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /提交正式 Run 提升申请/ })).toBeDisabled();

    resolveManifests(jsonResponse({
      manifests: [
        {
          package_id: "rdp-extra-asset-ref",
          research_question: "must be excluded",
          asset_refs: ["ide_run:ide-1", "asset:extra"],
          run_refs: ["ide_run:ide-1"],
        },
        {
          package_id: "rdp-wrong-run-ref",
          research_question: "must also be excluded",
          asset_refs: ["ide_run:ide-1"],
          run_refs: ["ide_run:other"],
        },
        {
          package_id: "rdp-exact",
          research_question: "exactly bound package",
          asset_refs: ["ide_run:ide-1"],
          run_refs: ["ide_run:ide-1"],
        },
      ],
    }));

    const packageSelect = await screen.findByLabelText("RDP package（必选）");
    expect(within(packageSelect).getAllByRole("option")).toHaveLength(2);
    expect(within(packageSelect).queryByText(/rdp-extra-asset-ref/)).toBeNull();
    expect(within(packageSelect).queryByText(/rdp-wrong-run-ref/)).toBeNull();
    expect(packageSelect).toHaveValue("");
    expect(screen.getByLabelText("promotion label（必选）")).toHaveValue("");
    expect(screen.getByText(/不表示已通过校验/)).toBeInTheDocument();
    expect(screen.getByText(/后端会重新执行当前重现回执与证据校验/)).toBeInTheDocument();

    fireEvent.change(packageSelect, { target: { value: "rdp-exact" } });
    fireEvent.change(screen.getByLabelText("promotion label（必选）"), {
      target: { value: "exploratory" },
    });
    const promoteButton = screen.getByRole("button", { name: /提交正式 Run 提升申请/ });
    expect(promoteButton).toBeEnabled();
    fireEvent.click(promoteButton);

    await waitFor(() => {
      expect(authFetch.mock.calls.some(([input]) => String(input) === "/api/ide/runs/ide-1/promote")).toBe(true);
    });
    const promoteCall = authFetch.mock.calls.find(
      ([input]) => String(input) === "/api/ide/runs/ide-1/promote",
    );
    expect(promoteCall).toBeDefined();
    expect(JSON.parse(String(promoteCall?.[1]?.body))).toEqual({
      market_data_use_validation_refs: ["market_data_use:BTCUSDT_1d:backtest"],
      rdp_package_id: "rdp-exact",
      requested_label: "exploratory",
    });
  });

  it("fails closed with honest error and no-candidate states and links to the RDP workbench", async () => {
    const run = ideRun("ide-empty", 2);
    const authFetch = installBaseMocks([run], async () => jsonResponse({
      manifests: [{
        package_id: "rdp-not-exact",
        asset_refs: ["ide_run:ide-empty"],
        run_refs: ["ide_run:other"],
      }],
    }));

    const view = renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-empty"));
    expect(await screen.findByTestId("ide-rdp-empty")).toHaveTextContent("精确绑定当前 IDE run");
    const promoteButton = screen.getByRole("button", { name: /提交正式 Run 提升申请/ });
    expect(promoteButton).toBeDisabled();
    fireEvent.click(promoteButton);
    expect(authFetch.mock.calls.some(([input]) => String(input).endsWith("/promote"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /打开研究执行台/ }));
    expect(await screen.findByText("RDP workbench destination")).toBeInTheDocument();

    view.unmount();
    authFetch.mockRestore();
    vi.spyOn(auth, "getStoredUser").mockReturnValue(owner);
    const errorFetch = vi.spyOn(auth, "authFetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/ide/strategies") return Promise.resolve(jsonResponse([]));
      if (url === "/api/ide/runs?limit=20") return Promise.resolve(jsonResponse([run]));
      if (url === "/api/ide/ai_context") return Promise.resolve(jsonResponse(null));
      if (url === "/api/research-os/rdp/manifests") {
        return Promise.resolve(jsonResponse({ detail: "owner RDP store unavailable" }, 503));
      }
      throw new Error(`unexpected authFetch: ${url}`);
    });

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-empty"));
    expect(await screen.findByTestId("ide-rdp-error")).toHaveTextContent("owner RDP store unavailable");
    expect(screen.queryByLabelText("RDP package（必选）")).toBeNull();
    expect(screen.getByRole("button", { name: /提交正式 Run 提升申请/ })).toBeDisabled();
    expect(errorFetch.mock.calls.some(([input]) => String(input).endsWith("/promote"))).toBe(false);
  });

  it("resets stale package and label selections whenever the active IDE run changes", async () => {
    const firstRun = ideRun("ide-first", 3);
    const secondRun = ideRun("ide-second", 4);
    let manifestCall = 0;
    let resolveSecond!: (response: Response) => void;
    const secondResponse = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    installBaseMocks([firstRun, secondRun], () => {
      manifestCall += 1;
      if (manifestCall === 1) {
        return Promise.resolve(jsonResponse({ manifests: [{
          package_id: "rdp-first",
          asset_refs: ["ide_run:ide-first"],
          run_refs: ["ide_run:ide-first"],
        }] }));
      }
      return secondResponse;
    });

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-first"));
    fireEvent.change(await screen.findByLabelText("RDP package（必选）"), {
      target: { value: "rdp-first" },
    });
    fireEvent.change(screen.getByLabelText("promotion label（必选）"), {
      target: { value: "proof_backed" },
    });
    expect(screen.getByRole("button", { name: /提交正式 Run 提升申请/ })).toBeEnabled();

    fireEvent.click(screen.getByTestId("ide-recent-run-ide-second"));
    expect(await screen.findByTestId("ide-rdp-loading")).toBeInTheDocument();
    expect(screen.queryByLabelText("RDP package（必选）")).toBeNull();
    expect(screen.getByRole("button", { name: /提交正式 Run 提升申请/ })).toBeDisabled();

    resolveSecond(jsonResponse({ manifests: [{
      package_id: "rdp-second",
      asset_refs: ["ide_run:ide-second"],
      run_refs: ["ide_run:ide-second"],
    }] }));

    const secondPackageSelect = await screen.findByLabelText("RDP package（必选）");
    expect(secondPackageSelect).toHaveValue("");
    expect(within(secondPackageSelect).queryByText(/rdp-first/)).toBeNull();
    expect(within(secondPackageSelect).getByText(/rdp-second/)).toBeInTheDocument();
    expect(screen.getByLabelText("promotion label（必选）")).toHaveValue("");
    expect(screen.getByRole("button", { name: /提交正式 Run 提升申请/ })).toBeDisabled();
  });

  it("creates an RDP from an empty registry, strips server-owned fields, refetches, and preselects only the exact package", async () => {
    const run = ideRun("ide-create", 5, ["market_data_use:BTCUSDT_1d:backtest"]);
    const calls: { url: string; init?: RequestInit }[] = [];
    let manifestGetCalls = 0;
    vi.spyOn(auth, "getStoredUser").mockReturnValue(owner);
    vi.spyOn(auth, "authFetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url === "/api/ide/strategies") return Promise.resolve(jsonResponse([]));
      if (url === "/api/ide/runs?limit=20") return Promise.resolve(jsonResponse([run]));
      if (url === "/api/ide/ai_context") return Promise.resolve(jsonResponse(null));
      if (url === "/api/research-os/rdp/manifests" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          package_id: "rdp-created-exact",
          manifest_version: "rdp.v3",
          recorded_by: "owner",
        }));
      }
      if (url === "/api/research-os/rdp/manifests") {
        manifestGetCalls += 1;
        if (manifestGetCalls === 1) return Promise.resolve(jsonResponse({ manifests: [] }));
        return Promise.resolve(jsonResponse({
          manifests: [
            {
              package_id: "rdp-created-exact",
              research_question: "current run package",
              asset_refs: ["ide_run:ide-create"],
              run_refs: ["ide_run:ide-create"],
            },
            {
              package_id: "rdp-created-wrong-run",
              asset_refs: ["ide_run:other"],
              run_refs: ["ide_run:other"],
            },
          ],
        }));
      }
      throw new Error(`unexpected authFetch: ${url} ${String(init?.method ?? "GET")}`);
    });

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-create"));
    expect(await screen.findByTestId("ide-rdp-empty")).toBeInTheDocument();
    expect(screen.getByTestId("ide-rdp-create-guidance")).toHaveTextContent("不会自动生成证据");

    const draft = validRdpManifestDraft({
      ide_run_id: "ide-spoofed",
      asset_refs: ["ide_run:spoofed"],
      run_refs: ["ide_run:spoofed"],
      source_file_refs: ["source_file:spoofed.py"],
      artifact_hash: "sha256:spoofed",
      reproducibility_command: "python spoof.py",
      package_id: "rdp-spoofed",
      rdp_id: "rdp-spoofed",
    });
    fireEvent.change(screen.getByLabelText("RDP manifest JSON draft"), {
      target: { value: JSON.stringify(draft, null, 2) },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建并绑定当前 run 的 RDP" }));

    expect(await screen.findByTestId("ide-rdp-create-success")).toHaveTextContent("rdp-created-exact");
    const packageSelect = screen.getByLabelText("RDP package（必选）");
    expect(packageSelect).toHaveValue("rdp-created-exact");
    expect(within(packageSelect).queryByText(/rdp-created-wrong-run/)).toBeNull();
    expect(screen.getByTestId("ide-rdp-stripped-fields")).toHaveTextContent("artifact_hash");
    expect(manifestGetCalls).toBe(2);

    const createCall = calls.find(
      (call) => call.url === "/api/research-os/rdp/manifests" && call.init?.method === "POST",
    );
    expect(createCall).toBeDefined();
    const submitted = JSON.parse(String(createCall?.init?.body));
    expect(submitted.ide_run_id).toBe("ide-create");
    expect(submitted.manifest.research_question).toBe(draft.research_question);
    for (const serverField of [
      "ide_run_id",
      "asset_refs",
      "run_refs",
      "source_file_refs",
      "artifact_hash",
      "reproducibility_command",
      "package_id",
      "rdp_id",
    ]) {
      expect(submitted.manifest).not.toHaveProperty(serverField);
    }
  });

  it("rejects invalid and non-object manifest JSON locally without POSTing", async () => {
    const run = ideRun("ide-invalid-json", 6);
    const authFetch = installBaseMocks([run], async () => jsonResponse({ manifests: [] }));

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-invalid-json"));
    await screen.findByTestId("ide-rdp-empty");

    fireEvent.change(screen.getByLabelText("RDP manifest JSON draft"), { target: { value: "{" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并绑定当前 run 的 RDP" }));
    expect(await screen.findByTestId("ide-rdp-create-error")).toHaveTextContent("JSON 无效");

    fireEvent.change(screen.getByLabelText("RDP manifest JSON draft"), { target: { value: "[]" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并绑定当前 run 的 RDP" }));
    expect(await screen.findByTestId("ide-rdp-create-error")).toHaveTextContent("顶层必须是 object");
    expect(authFetch.mock.calls.some(
      ([input, init]) => String(input) === "/api/research-os/rdp/manifests" && init?.method === "POST",
    )).toBe(false);
  });

  it("surfaces backend RDP validation detail without changing the promotion state", async () => {
    const run = ideRun("ide-backend-reject", 7);
    let manifestGetCalls = 0;
    vi.spyOn(auth, "getStoredUser").mockReturnValue(owner);
    const authFetch = vi.spyOn(auth, "authFetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/ide/strategies") return Promise.resolve(jsonResponse([]));
      if (url === "/api/ide/runs?limit=20") return Promise.resolve(jsonResponse([run]));
      if (url === "/api/ide/ai_context") return Promise.resolve(jsonResponse(null));
      if (url === "/api/research-os/rdp/manifests" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ detail: "missing_compiler_artifact_refs" }, 422));
      }
      if (url === "/api/research-os/rdp/manifests") {
        manifestGetCalls += 1;
        return Promise.resolve(jsonResponse({ manifests: [] }));
      }
      throw new Error(`unexpected authFetch: ${url} ${String(init?.method ?? "GET")}`);
    });

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-backend-reject"));
    await screen.findByTestId("ide-rdp-empty");
    fireEvent.change(screen.getByLabelText("RDP manifest JSON draft"), {
      target: { value: JSON.stringify(validRdpManifestDraft()) },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建并绑定当前 run 的 RDP" }));

    expect(await screen.findByTestId("ide-rdp-create-error")).toHaveTextContent("missing_compiler_artifact_refs");
    expect(screen.queryByLabelText("RDP package（必选）")).toBeNull();
    expect(screen.getByRole("button", { name: /提交正式 Run 提升申请/ })).toBeDisabled();
    expect(manifestGetCalls).toBe(1);
    expect(authFetch.mock.calls.filter(
      ([input, init]) => String(input) === "/api/research-os/rdp/manifests" && init?.method === "POST",
    )).toHaveLength(1);
  });

  it("ignores a stale create refresh when the active IDE run changes", async () => {
    const firstRun = ideRun("ide-create-first", 8);
    const secondRun = ideRun("ide-create-second", 9);
    let manifestGetCalls = 0;
    let resolveFirstRefresh!: (response: Response) => void;
    const firstRefresh = new Promise<Response>((resolve) => {
      resolveFirstRefresh = resolve;
    });
    vi.spyOn(auth, "getStoredUser").mockReturnValue(owner);
    vi.spyOn(auth, "authFetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/ide/strategies") return Promise.resolve(jsonResponse([]));
      if (url === "/api/ide/runs?limit=20") return Promise.resolve(jsonResponse([firstRun, secondRun]));
      if (url === "/api/ide/ai_context") return Promise.resolve(jsonResponse(null));
      if (url === "/api/research-os/rdp/manifests" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ package_id: "rdp-first-created" }));
      }
      if (url === "/api/research-os/rdp/manifests") {
        manifestGetCalls += 1;
        if (manifestGetCalls === 1) return Promise.resolve(jsonResponse({ manifests: [] }));
        if (manifestGetCalls === 2) return firstRefresh;
        return Promise.resolve(jsonResponse({
          manifests: [{
            package_id: "rdp-second",
            asset_refs: ["ide_run:ide-create-second"],
            run_refs: ["ide_run:ide-create-second"],
          }],
        }));
      }
      throw new Error(`unexpected authFetch: ${url} ${String(init?.method ?? "GET")}`);
    });

    renderIDE();
    fireEvent.click(await screen.findByTestId("ide-recent-run-ide-create-first"));
    await screen.findByTestId("ide-rdp-empty");
    fireEvent.change(screen.getByLabelText("RDP manifest JSON draft"), {
      target: { value: JSON.stringify(validRdpManifestDraft()) },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建并绑定当前 run 的 RDP" }));
    await waitFor(() => expect(manifestGetCalls).toBe(2));

    fireEvent.click(screen.getByTestId("ide-recent-run-ide-create-second"));
    const secondPackageSelect = await screen.findByLabelText("RDP package（必选）");
    expect(within(secondPackageSelect).getByText(/rdp-second/)).toBeInTheDocument();
    expect(secondPackageSelect).toHaveValue("");
    expect(screen.getByLabelText("RDP manifest JSON draft")).toHaveValue("{}");

    resolveFirstRefresh(jsonResponse({
      manifests: [{
        package_id: "rdp-first-created",
        asset_refs: ["ide_run:ide-create-first"],
        run_refs: ["ide_run:ide-create-first"],
      }],
    }));
    await waitFor(() => {
      expect(within(screen.getByLabelText("RDP package（必选）")).queryByText(/rdp-first-created/)).toBeNull();
      expect(screen.queryByTestId("ide-rdp-create-success")).toBeNull();
      expect(screen.queryByTestId("ide-rdp-create-error")).toBeNull();
    });
    expect(manifestGetCalls).toBe(3);
  });
});
