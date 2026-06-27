import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as auth from "../../../lib/auth";
import { MethodologyValidationPanel } from "./MethodologyValidationPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

interface CPCVRecord {
  cpcv_ref: string;
  claim_ref: string;
  fold_count: number;
  embargo_observations: number;
  sample_count: number;
  mean_metric: number;
  min_metric: number;
  max_metric: number;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

interface ConformalRecord {
  conformal_ref: string;
  claim_ref: string;
  alpha: number;
  calibration_count: number;
  nonconformity_threshold: number;
  coverage_estimate: number;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
  abstain_policy_ref?: string | null;
}

interface TCARecord {
  tca_ref: string;
  claim_ref: string;
  sample_count: number;
  gross_mean_bps: number;
  total_cost_bps: number;
  net_mean_bps: number;
  cost_component_refs: string[];
  cost_model_refs: string[];
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

interface DepthRecord {
  depth_ref: string;
  claim_ref: string;
  claim_label: string;
  target_environment: string;
  cpcv_ref?: string | null;
  walk_forward_ref?: string | null;
  conformal_ref?: string | null;
  abstain_policy_ref?: string | null;
  tca_ref?: string | null;
  cost_model_refs: string[];
  feature_leakage_probe_refs: string[];
  feature_leakage_verdict: string;
  fault_injection_refs: string[];
  fault_injection_verdict: string;
  recovery_drill_refs: string[];
  recovery_drill_verdict: string;
  evidence_refs: string[];
  validation_result_refs: string[];
  methodology_choice_ref?: string | null;
  responsibility_boundary_ref?: string | null;
  user_waived_path: boolean;
  silent_mock_fallback_used: boolean;
}

interface RuntimeDrillRecord {
  runtime_drill_ref: string;
  claim_ref: string;
  target_environment: string;
  drill_mode: string;
  venue_ref: string;
  fault_scenario: string;
  expected_guard_ref: string;
  observed_guard_ref: string;
  recovery_action_ref: string;
  fault_injection_ref: string;
  recovery_drill_ref: string;
  fault_injection_verdict: string;
  recovery_drill_verdict: string;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

function mean(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function installMethodologyMock(options: {
  cpcv?: CPCVRecord[];
  conformal?: ConformalRecord[];
  tca?: TCARecord[];
  depths?: DepthRecord[];
  runtimeDrills?: RuntimeDrillRecord[];
} = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const state = {
    cpcv: [...(options.cpcv ?? [])],
    conformal: [...(options.conformal ?? [])],
    tca: [...(options.tca ?? [])],
    depths: [...(options.depths ?? [])],
    runtimeDrills: [...(options.runtimeDrills ?? [])],
  };
  const summary = () => ({
    user: "u1",
    validation_depth_total: state.depths.length,
    validation_depths: state.depths,
    runtime_drill_total: state.runtimeDrills.length,
    runtime_drills: state.runtimeDrills,
    calculator_totals: {
      cpcv: state.cpcv.length,
      conformal: state.conformal.length,
      tca: state.tca.length,
    },
    cpcv_calculations: state.cpcv,
    conformal_calculations: state.conformal,
    tca_calculations: state.tca,
  });

  vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === "/api/research-os/methodology/summary") {
      return Promise.resolve(jsonResponse(summary()));
    }
    if (url === "/api/research-os/methodology/cpcv") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        cpcv_ref?: string;
        claim_ref: string;
        fold_metric_values: number[];
        embargo_observations?: number;
        evidence_refs: string[];
        validation_result_refs: string[];
      };
      const values = body.fold_metric_values;
      const record: CPCVRecord = {
        cpcv_ref: body.cpcv_ref ?? "cpcv:generated",
        claim_ref: body.claim_ref,
        fold_count: values.length,
        embargo_observations: body.embargo_observations ?? 0,
        sample_count: values.length,
        mean_metric: mean(values),
        min_metric: Math.min(...values),
        max_metric: Math.max(...values),
        source_hash: "sha256:cpcv",
        evidence_refs: body.evidence_refs,
        validation_result_refs: body.validation_result_refs,
      };
      state.cpcv.push(record);
      return Promise.resolve(jsonResponse({ ...record, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/methodology/validation_depth_records") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { validation_depth: DepthRecord };
      state.depths.push(body.validation_depth);
      return Promise.resolve(
        jsonResponse({
          depth_ref: body.validation_depth.depth_ref,
          claim_ref: body.validation_depth.claim_ref,
          target_environment: body.validation_depth.target_environment,
          recorded_by: "u1",
        }),
      );
    }
    if (url === "/api/research-os/methodology/runtime_drills") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        runtime_drill_ref?: string;
        claim_ref: string;
        target_environment: string;
        drill_mode: string;
        venue_ref: string;
        fault_scenario: string;
        expected_guard_ref: string;
        observed_guard_ref: string;
        recovery_action_ref: string;
        evidence_refs: string[];
        validation_result_refs: string[];
        fault_injection_ref?: string;
        recovery_drill_ref?: string;
      };
      const record: RuntimeDrillRecord = {
        runtime_drill_ref: body.runtime_drill_ref ?? "runtime_drill:generated",
        claim_ref: body.claim_ref,
        target_environment: body.target_environment,
        drill_mode: body.drill_mode,
        venue_ref: body.venue_ref,
        fault_scenario: body.fault_scenario,
        expected_guard_ref: body.expected_guard_ref,
        observed_guard_ref: body.observed_guard_ref,
        recovery_action_ref: body.recovery_action_ref,
        fault_injection_ref: body.fault_injection_ref ?? "fault_injection:generated",
        recovery_drill_ref: body.recovery_drill_ref ?? "recovery_drill:generated",
        fault_injection_verdict: "passed",
        recovery_drill_verdict: "passed",
        source_hash: "sha256:runtime-drill",
        evidence_refs: body.evidence_refs,
        validation_result_refs: body.validation_result_refs,
      };
      state.runtimeDrills.push(record);
      return Promise.resolve(jsonResponse({ ...record, recorded_by: "u1" }));
    }
    return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
  });

  return { calls, state };
}

function change(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MethodologyValidationPanel", () => {
  it("loads methodology summary without raw calculator series", async () => {
    installMethodologyMock({
      cpcv: [
        {
          cpcv_ref: "cpcv:v1",
          claim_ref: "claim:alpha",
          fold_count: 3,
          embargo_observations: 2,
          sample_count: 3,
          mean_metric: 0.11,
          min_metric: 0.07,
          max_metric: 0.15,
          source_hash: "sha256:cpcv",
          evidence_refs: ["evidence:cpcv"],
          validation_result_refs: ["pytest:cpcv"],
        },
      ],
      depths: [
        {
          depth_ref: "validation_depth:v1",
          claim_ref: "claim:alpha",
          claim_label: "evidence_sufficient",
          target_environment: "paper",
          cpcv_ref: "cpcv:v1",
          walk_forward_ref: "walk_forward:v1",
          conformal_ref: "conformal:v1",
          abstain_policy_ref: "abstain:v1",
          tca_ref: "tca:v1",
          cost_model_refs: ["cost:v1"],
          feature_leakage_probe_refs: ["leak:v1"],
          feature_leakage_verdict: "accepted",
          fault_injection_refs: ["fault:v1"],
          fault_injection_verdict: "accepted",
          recovery_drill_refs: ["recovery:v1"],
          recovery_drill_verdict: "accepted",
          evidence_refs: ["evidence:v1"],
          validation_result_refs: ["validation:v1"],
          user_waived_path: false,
          silent_mock_fallback_used: false,
        },
      ],
    });

    render(<MethodologyValidationPanel />);

    expect(await screen.findByText("depth 1")).toBeInTheDocument();
    expect(await screen.findByText("cpcv 1")).toBeInTheDocument();
    expect((await screen.findAllByText("cpcv:v1")).length).toBeGreaterThan(0);
    expect(await screen.findByText("mean 0.11 · folds 3")).toBeInTheDocument();
    expect((await screen.findAllByText("validation_depth:v1")).length).toBeGreaterThan(0);
    expect(await screen.findByText("evidence_sufficient · paper")).toBeInTheDocument();
    expect(screen.queryByText("0.07")).toBeNull();
    expect(screen.queryByText("0.15")).toBeNull();
  });

  it("records CPCV with parsed numeric folds and required refs", async () => {
    const { calls } = installMethodologyMock();

    render(<MethodologyValidationPanel />);

    expect(await screen.findByText("depth 0")).toBeInTheDocument();
    change("methodology-cpcv-claim-ref", "claim:alpha");
    change("methodology-cpcv-values", "0.10, 0.12, 0.11");
    change("methodology-cpcv-embargo", "2");
    change("methodology-cpcv-evidence-refs", "evidence:cpcv");
    change("methodology-cpcv-validation-refs", "pytest:cpcv");
    change("methodology-cpcv-ref", "cpcv:manual");
    fireEvent.click(screen.getByTestId("methodology-cpcv-submit"));

    await waitFor(() => expect(calls.some((call) => call.url === "/api/research-os/methodology/cpcv")).toBe(true));
    const cpcvCall = calls.find((call) => call.url === "/api/research-os/methodology/cpcv");
    expect(JSON.parse(String(cpcvCall?.init?.body))).toEqual({
      claim_ref: "claim:alpha",
      fold_metric_values: [0.1, 0.12, 0.11],
      embargo_observations: 2,
      evidence_refs: ["evidence:cpcv"],
      validation_result_refs: ["pytest:cpcv"],
      cpcv_ref: "cpcv:manual",
    });
    expect((await screen.findAllByText("cpcv:manual")).length).toBeGreaterThan(0);
    expect(await screen.findByText("mean 0.11 · folds 3")).toBeInTheDocument();
  });

  it("blocks missing CPCV folds before calling backend", async () => {
    const { calls } = installMethodologyMock();

    render(<MethodologyValidationPanel />);

    expect(await screen.findByText("depth 0")).toBeInTheDocument();
    change("methodology-cpcv-claim-ref", "claim:alpha");
    fireEvent.click(screen.getByTestId("methodology-cpcv-submit"));

    expect(await screen.findByTestId("methodology-error")).toHaveTextContent("fold_metric_values required");
    expect(calls.some((call) => call.url === "/api/research-os/methodology/cpcv")).toBe(false);
  });

  it("records runtime drill and fills validation-depth fault and recovery refs", async () => {
    const { calls } = installMethodologyMock();

    render(<MethodologyValidationPanel />);

    expect(await screen.findByText("runtime drills 0")).toBeInTheDocument();
    change("methodology-drill-claim-ref", "claim:alpha");
    change("methodology-drill-target-env", "paper");
    change("methodology-drill-mode", "simulation");
    change("methodology-drill-venue-ref", "venue:paper:local");
    change("methodology-drill-fault-scenario", "venue_timeout");
    change("methodology-drill-expected-guard-ref", "order_guard:timeout");
    change("methodology-drill-observed-guard-ref", "order_guard:timeout");
    change("methodology-drill-recovery-action-ref", "recovery:reconcile_before_resend");
    change("methodology-drill-evidence-refs", "evidence:drill");
    change("methodology-drill-validation-refs", "pytest:drill");
    change("methodology-drill-runtime-ref", "runtime_drill:v1");
    change("methodology-drill-fault-ref", "fault_injection:v1");
    change("methodology-drill-recovery-ref", "recovery_drill:v1");
    fireEvent.click(screen.getByTestId("methodology-record-runtime-drill"));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/research-os/methodology/runtime_drills")).toBe(true),
    );
    const drillCall = calls.find((call) => call.url === "/api/research-os/methodology/runtime_drills");
    expect(JSON.parse(String(drillCall?.init?.body))).toEqual({
      claim_ref: "claim:alpha",
      target_environment: "paper",
      drill_mode: "simulation",
      venue_ref: "venue:paper:local",
      fault_scenario: "venue_timeout",
      expected_guard_ref: "order_guard:timeout",
      observed_guard_ref: "order_guard:timeout",
      recovery_action_ref: "recovery:reconcile_before_resend",
      evidence_refs: ["evidence:drill"],
      validation_result_refs: ["pytest:drill"],
      runtime_drill_ref: "runtime_drill:v1",
      fault_injection_ref: "fault_injection:v1",
      recovery_drill_ref: "recovery_drill:v1",
    });
    expect((await screen.findAllByText("runtime_drill:v1")).length).toBeGreaterThan(0);
    expect((screen.getByTestId("methodology-depth-fault-refs") as HTMLInputElement).value).toBe(
      "fault_injection:v1",
    );
    expect((screen.getByTestId("methodology-depth-recovery-refs") as HTMLInputElement).value).toBe(
      "recovery_drill:v1",
    );
  });

  it("records validation depth with evidence refs, runtime drill refs, and no silent mock fallback", async () => {
    const { calls } = installMethodologyMock();

    render(<MethodologyValidationPanel />);

    expect(await screen.findByText("depth 0")).toBeInTheDocument();
    change("methodology-depth-ref", "validation_depth:v1");
    change("methodology-depth-claim-ref", "claim:alpha");
    change("methodology-depth-claim-label", "evidence_sufficient");
    change("methodology-depth-target-env", "paper");
    change("methodology-depth-cpcv-ref", "cpcv:v1");
    change("methodology-depth-walk-forward-ref", "walk_forward:v1");
    change("methodology-depth-conformal-ref", "conformal:v1");
    change("methodology-depth-abstain-ref", "abstain:v1");
    change("methodology-depth-tca-ref", "tca:v1");
    change("methodology-depth-cost-model-refs", "cost:v1");
    change("methodology-depth-leakage-refs", "leak:v1");
    change("methodology-depth-leakage-verdict", "accepted");
    change("methodology-depth-fault-refs", "fault:v1");
    change("methodology-depth-fault-verdict", "accepted");
    change("methodology-depth-recovery-refs", "recovery:v1");
    change("methodology-depth-recovery-verdict", "accepted");
    change("methodology-depth-evidence-refs", "evidence:v1");
    change("methodology-depth-validation-refs", "validation:v1");
    change("methodology-depth-choice-ref", "methodology_choice:v1");
    change("methodology-depth-responsibility-ref", "responsibility:v1");
    fireEvent.click(screen.getByTestId("methodology-record-depth"));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/research-os/methodology/validation_depth_records")).toBe(true),
    );
    const depthCall = calls.find((call) => call.url === "/api/research-os/methodology/validation_depth_records");
    expect(JSON.parse(String(depthCall?.init?.body))).toEqual({
      validation_depth: {
        depth_ref: "validation_depth:v1",
        claim_ref: "claim:alpha",
        claim_label: "evidence_sufficient",
        target_environment: "paper",
        cpcv_ref: "cpcv:v1",
        walk_forward_ref: "walk_forward:v1",
        conformal_ref: "conformal:v1",
        abstain_policy_ref: "abstain:v1",
        tca_ref: "tca:v1",
        cost_model_refs: ["cost:v1"],
        feature_leakage_probe_refs: ["leak:v1"],
        feature_leakage_verdict: "accepted",
        fault_injection_refs: ["fault:v1"],
        fault_injection_verdict: "accepted",
        recovery_drill_refs: ["recovery:v1"],
        recovery_drill_verdict: "accepted",
        evidence_refs: ["evidence:v1"],
        validation_result_refs: ["validation:v1"],
        methodology_choice_ref: "methodology_choice:v1",
        responsibility_boundary_ref: "responsibility:v1",
        user_waived_path: false,
        silent_mock_fallback_used: false,
      },
    });
    expect((await screen.findAllByText("validation_depth:v1")).length).toBeGreaterThan(0);
    expect(await screen.findByText("evidence_sufficient · paper")).toBeInTheDocument();
  });
});
