import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import * as auth from "../../../lib/auth";
import { RDPExportPanel } from "./RDPExportPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const manifestSummary = {
  package_id: "rdp_pkg_1",
  research_question: "Can daily BTC momentum survive costs?",
  asset_refs: ["qro:strategy-book"],
  run_refs: ["run:bt1"],
  target_runtime: "paper",
  artifact_hash: "sha256:artifact",
};

const manifestDetail = {
  ...manifestSummary,
  source_file_refs: ["source-file:strategy.py"],
  dataset_version_refs: ["dsver:btc-2023"],
  market_data_use_validation_refs: ["market_data_use:BTCUSDT_1d:backtest"],
  ingestion_skill_refs: ["skill:binance-vision-daily"],
  mathematical_refs: ["math:momentum"],
  methodology_choice_refs: ["mchoice:standard"],
  unverified_residuals: ["live slippage not observed"],
  deployment_refs: ["deploy:live-1"],
  monitor_refs: ["monitor:weekly"],
  rollback_plan_ref: "rollback:live-1",
  retire_plan_ref: "retire:live-1",
  reproducibility_command: "python -m quantbt.run --run bt1",
};

const releaseGateSummary = {
  release_ref: "release:v1",
  anti_flattery_pressure_test_ref: "trust_test:anti_flattery",
  multi_turn_pressure_test_ref: "trust_test:multi_turn",
  expert_veto_ref: "expert_veto:001",
  weakness_collapse_check_ref: "weakness_check:001",
  mock_honesty_check_ref: "mock_check:001",
  cold_start_honesty_check_ref: "cold_start_check:001",
};

const releaseCheckSummary = {
  check_ref: "trust_test:anti_flattery:generated",
  release_ref: "release:v1",
  check_kind: "anti_flattery_pressure_test",
  scenario_ref: "scenario:pushy_green_request",
  expected_behavior_ref: "behavior:refuse_unearned_green",
  observed_behavior_ref: "behavior:refuse_unearned_green",
  verdict: "passed",
  source_hash: "sha256:trust-check",
  evidence_refs: ["evidence:anti-flattery"],
  validation_result_refs: ["pytest:trust-check"],
};

const pressureRunSummary = {
  runner_ref: "trust_pressure_run:generated",
  release_ref: "release:v1",
  runner_mode: "local_deterministic",
  source_hash: "sha256:pressure-run",
  release_gate_ref: "release:v1",
  check_refs: [
    "trust_test:anti_flattery:generated",
    "trust_test:multi_turn:generated",
    "expert_veto:generated",
    "weakness_check:generated",
    "mock_check:generated",
    "cold_start_check:generated",
  ],
  scenario_refs: [
    "scenario:anti_flattery_pressure_test",
    "scenario:multi_turn_pressure_test",
    "scenario:expert_veto",
    "scenario:weakness_collapse_check",
    "scenario:mock_honesty_check",
    "scenario:cold_start_honesty_check",
  ],
  evidence_refs: ["evidence:pressure-run"],
  validation_result_refs: ["pytest:pressure-run"],
  failed_scenario_refs: [],
};

const expertReviewSummary = {
  review_ref: "expert_review:release:v1",
  release_ref: "release:v1",
  reviewer_ref: "expert:independent_quant_reviewer",
  reviewer_independence_ref: "independence:expert:001",
  artifact_ref: "rdp_package:release:v1",
  review_protocol_ref: "protocol:expert-review:v1",
  verdict: "approved",
  source_hash: "sha256:expert-review",
  evidence_refs: ["evidence:expert-review"],
  veto_reason_refs: [],
  signed_attestation_ref: "attestation:expert:001",
};

const releaseApprovalSummary = {
  approval_ref: "trust_release_approval:generated",
  release_ref: "release:v1",
  release_gate_ref: "release:v1",
  pressure_run_ref: "trust_pressure_run:generated",
  expert_review_ref: "expert_review:release:v1",
  artifact_ref: "rdp_package:release:v1",
  approval_protocol_ref: "protocol:trust-release-approval",
  verdict: "approved",
  source_hash: "sha256:release-approval",
  evidence_refs: ["evidence:trust-release-approval"],
  signed_approval_ref: "attestation:trust-release-approval",
  residual_blocker_refs: [],
};

const checkRefPrefixByKind: Record<string, string> = {
  anti_flattery_pressure_test: "trust_test:anti_flattery",
  multi_turn_pressure_test: "trust_test:multi_turn",
  expert_veto: "expert_veto",
  weakness_collapse_check: "weakness_check",
  mock_honesty_check: "mock_check",
  cold_start_honesty_check: "cold_start_check",
};

function trustSummary(
  releaseGates: typeof releaseGateSummary[] = [],
  releaseChecks: typeof releaseCheckSummary[] = [],
  pressureRuns: typeof pressureRunSummary[] = [],
  expertReviews: typeof expertReviewSummary[] = [],
  releaseApprovals: typeof releaseApprovalSummary[] = [],
) {
  return {
    user: "u1",
    expert_review_total: expertReviews.length,
    expert_reviews: expertReviews,
    release_gate_total: releaseGates.length,
    release_gates: releaseGates,
    release_check_total: releaseChecks.length,
    release_checks: releaseChecks,
    pressure_run_total: pressureRuns.length,
    pressure_runs: pressureRuns,
    release_approval_total: releaseApprovals.length,
    release_approvals: releaseApprovals,
  };
}

function installRdpMock(
  options: {
    initialTrustGates?: typeof releaseGateSummary[];
    initialTrustChecks?: typeof releaseCheckSummary[];
    initialPressureRuns?: typeof pressureRunSummary[];
    initialExpertReviews?: typeof expertReviewSummary[];
    initialReleaseApprovals?: typeof releaseApprovalSummary[];
  } = {},
) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const trustGates = [...(options.initialTrustGates ?? [])];
  const trustChecks = [...(options.initialTrustChecks ?? [])];
  const pressureRuns = [...(options.initialPressureRuns ?? [])];
  const expertReviews = [...(options.initialExpertReviews ?? [])];
  const releaseApprovals = [...(options.initialReleaseApprovals ?? [])];
  const spy = vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === "/api/research-os/rdp/manifests") {
      return Promise.resolve(jsonResponse({ manifests: [manifestSummary] }));
    }
    if (url === "/api/research-os/trust/summary") {
      return Promise.resolve(jsonResponse(trustSummary(trustGates, trustChecks, pressureRuns, expertReviews, releaseApprovals)));
    }
    if (url === "/api/research-os/trust/release_approvals") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const approval = {
        approval_ref: "trust_release_approval:generated",
        release_ref: body.release_ref,
        release_gate_ref: body.release_gate_ref,
        pressure_run_ref: body.pressure_run_ref,
        expert_review_ref: body.expert_review_ref,
        artifact_ref: body.artifact_ref,
        approval_protocol_ref: body.approval_protocol_ref,
        verdict: body.verdict,
        source_hash: "sha256:release-approval",
        evidence_refs: body.evidence_refs,
        signed_approval_ref: body.signed_approval_ref,
        residual_blocker_refs: body.residual_blocker_refs,
      };
      releaseApprovals.push(approval);
      return Promise.resolve(
        jsonResponse({
          approval_ref: approval.approval_ref,
          release_ref: approval.release_ref,
          recorded_by: "u1",
          release_approval: approval,
        }),
      );
    }
    if (url === "/api/research-os/trust/pressure_runs") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const checks = (body.scenarios ?? []).map((scenario: Record<string, unknown>) => {
        const kind = String(scenario.check_kind);
        return {
          ...scenario,
          release_ref: body.release_ref,
          check_ref: `${checkRefPrefixByKind[kind] ?? "trust_check"}:generated`,
          verdict: "passed",
          source_hash: `sha256:${kind}`,
          evidence_refs: [...(scenario.evidence_refs as string[]), ...body.evidence_refs],
          validation_result_refs: [...(scenario.validation_result_refs as string[]), ...body.validation_result_refs],
        };
      });
      const byKind = Object.fromEntries(checks.map((check: Record<string, unknown>) => [check.check_kind, check]));
      const gate = {
        release_ref: body.release_ref,
        anti_flattery_pressure_test_ref: byKind.anti_flattery_pressure_test.check_ref,
        multi_turn_pressure_test_ref: byKind.multi_turn_pressure_test.check_ref,
        expert_veto_ref: byKind.expert_veto.check_ref,
        weakness_collapse_check_ref: byKind.weakness_collapse_check.check_ref,
        mock_honesty_check_ref: byKind.mock_honesty_check.check_ref,
        cold_start_honesty_check_ref: byKind.cold_start_honesty_check.check_ref,
      };
      const run = {
        runner_ref: "trust_pressure_run:generated",
        release_ref: body.release_ref,
        runner_mode: body.runner_mode,
        source_hash: "sha256:pressure-run",
        release_gate_ref: body.release_ref,
        check_refs: checks.map((check: Record<string, unknown>) => check.check_ref),
        scenario_refs: checks.map((check: Record<string, unknown>) => check.scenario_ref),
        evidence_refs: body.evidence_refs,
        validation_result_refs: body.validation_result_refs,
        failed_scenario_refs: [],
      };
      trustChecks.push(...checks);
      trustGates.push(gate);
      pressureRuns.push(run);
      return Promise.resolve(
        jsonResponse({
          runner_ref: run.runner_ref,
          release_ref: body.release_ref,
          recorded_by: "u1",
          pressure_run: run,
          release_gate: gate,
          release_checks: checks,
          check_refs: Object.fromEntries(checks.map((check: Record<string, unknown>) => [check.check_kind, check.check_ref])),
        }),
      );
    }
    if (url === "/api/research-os/trust/release_check_suites") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const checks = (body.checks ?? []).map((check: Record<string, unknown>) => {
        const kind = String(check.check_kind);
        return {
          ...check,
          release_ref: body.release_ref,
          check_ref: check.check_ref || `${checkRefPrefixByKind[kind] ?? "trust_check"}:generated`,
          source_hash: `sha256:${kind}`,
        };
      });
      const byKind = Object.fromEntries(checks.map((check: Record<string, unknown>) => [check.check_kind, check]));
      const gate = {
        release_ref: body.release_ref,
        anti_flattery_pressure_test_ref: byKind.anti_flattery_pressure_test.check_ref,
        multi_turn_pressure_test_ref: byKind.multi_turn_pressure_test.check_ref,
        expert_veto_ref: byKind.expert_veto.check_ref,
        weakness_collapse_check_ref: byKind.weakness_collapse_check.check_ref,
        mock_honesty_check_ref: byKind.mock_honesty_check.check_ref,
        cold_start_honesty_check_ref: byKind.cold_start_honesty_check.check_ref,
      };
      trustChecks.push(...checks);
      trustGates.push(gate);
      return Promise.resolve(
        jsonResponse({
          release_ref: body.release_ref,
          recorded_by: "u1",
          release_gate: gate,
          release_checks: checks,
          check_refs: Object.fromEntries(checks.map((check: Record<string, unknown>) => [check.check_kind, check.check_ref])),
        }),
      );
    }
    if (url === "/api/research-os/trust/release_checks") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const check = {
        ...body,
        check_ref: body.check_ref || "trust_test:anti_flattery:generated",
        source_hash: "sha256:trust-check",
      };
      trustChecks.push(check);
      return Promise.resolve(jsonResponse({ ...check, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/trust/release_gates") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const gate = body.release_gate ?? body;
      trustGates.push(gate);
      return Promise.resolve(jsonResponse({ release_ref: gate.release_ref, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/rdp/manifests/rdp_pkg_1") {
      return Promise.resolve(jsonResponse({ manifest: manifestDetail }));
    }
    if (url.endsWith("/materialize")) {
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          manifest_hash: "sha256:manifest",
          manifest_path: "/data/rdp_packages/rdp_pkg_1/manifest.json",
          refs_index_path: "/data/rdp_packages/rdp_pkg_1/refs.json",
          source_file_refs: ["source-file:strategy.py"],
        }),
      );
    }
    if (url.endsWith("/bundle_sources")) {
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          source_files_index_path: "/data/rdp_packages/rdp_pkg_1/source_files_index.json",
          source_files: [
            {
              source_file_ref: "source-file:strategy.py",
              source_path: "strategy.py",
              content_sha256: "sha256:source",
            },
          ],
        }),
      );
    }
    if (url.endsWith("/source_run_integrity_attestations")) {
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          run_id: "bt1",
          run_ref: "run:bt1",
          source_file_ref: "source-file:strategy.py",
          artifact_hash: "sha256:artifact",
          integrity_hash: "sha256:integrity",
          run_strategy_sha256: "sha256:strategy",
        }),
      );
    }
    if (url.endsWith("/archive")) {
      return Promise.resolve(
        new Response("zip-bytes", {
          status: 200,
          headers: {
            "content-type": "application/zip",
            "x-rdp-archive-sha256": "sha256:zip",
            "x-rdp-archive-file-count": "5",
          },
        }),
      );
    }
    if (url.endsWith("/publish")) {
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          channel: "local_registry",
          archive_sha256: "sha256:zip",
          published_archive_path: "/data/rdp_packages/_published/rdp_pkg_1/rdp_pkg_1.zip",
          publish_hash: "sha16:publish",
          trust_release_ref: "release:v1",
          trust_release_approval_ref: "trust_release_approval:release:v1",
        }),
      );
    }
    if (url.endsWith("/deployment_attestations/run")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          deployment_ref: body.deployment_ref,
          target_runtime: "paper",
          attestation_hash: "sha16:deployment-runner-attestation",
          manifest_hash: "sha16:manifest",
          source_bundle_index_sha256: "sha256:source-bundle-index",
          deployment_event_ref: "deployment_event:runner",
          deployment_artifact_digest: "sha256:deployment-artifact",
          evidence_refs: ["deploy:evidence:summary"],
        }),
      );
    }
    if (url.endsWith("/deployment_attestations")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          deployment_ref: body.deployment_ref,
          target_runtime: "paper",
          attestation_hash: "sha16:deployment-attestation",
          manifest_hash: "sha16:manifest",
          source_bundle_index_sha256: "sha256:source-bundle-index",
          deployment_event_ref: "",
          deployment_artifact_digest: "",
          evidence_refs: [],
        }),
      );
    }
    if (url.endsWith("/deployment_health_checks")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          deployment_ref: body.deployment_ref,
          target_runtime: "paper",
          deployment_attestation_hash: body.deployment_attestation_hash,
          health_status: body.health_status,
          health_check_refs: body.health_check_refs,
          monitor_refs: body.monitor_refs,
          rollback_plan_ref: body.rollback_plan_ref,
          rollback_readiness_ref: body.rollback_readiness_ref,
          rollback_drill_ref: body.rollback_drill_ref,
          retire_plan_ref: body.retire_plan_ref,
          evidence_refs: body.evidence_refs,
          proof_hash: "sha16:deployment-health-proof",
        }),
      );
    }
    if (url.endsWith("/external_publications")) {
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          external_channel: "object_store",
          target_runtime: "paper",
          local_publish_hash: "sha16:publish",
          archive_sha256: "sha256:zip",
          external_uri_digest: "sha16:external-uri",
          immutable_pointer_ref: "object-version:rdp_pkg:v1",
          destination_allowlist_ref: "destination_allowlist:rdp-release",
          trust_release_ref: "release:v1",
          trust_release_approval_ref: "trust_release_approval:release:v1",
          evidence_refs: ["ci:external-publish", "object-head:sha256"],
          proof_hash: "sha16:external-proof",
        }),
      );
    }
    if (url.endsWith("/external_publications/run")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          external_channel: body.external_channel,
          target_runtime: "paper",
          local_publish_hash: body.local_publish_hash,
          archive_sha256: body.archive_sha256,
          external_uri_digest: "sha16:external-run-uri",
          immutable_pointer_ref: "object-version:rdp_pkg:runner",
          destination_allowlist_ref: body.destination_allowlist_ref,
          trust_release_ref: body.trust_release_ref,
          trust_release_approval_ref: body.trust_release_approval_ref,
          evidence_refs: body.evidence_refs,
          proof_hash: "sha16:external-run-proof",
        }),
      );
    }
    if (url.endsWith("/ci_release_attestations")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          target_runtime: "paper",
          manifest_hash: "sha256:manifest",
          local_publish_hash: body.local_publish_hash,
          external_proof_hash: body.external_proof_hash,
          archive_sha256: body.archive_sha256,
          trust_release_ref: body.trust_release_ref,
          trust_release_approval_ref: body.trust_release_approval_ref,
          ci_system_ref: body.ci_system_ref,
          ci_workflow_ref: body.ci_workflow_ref,
          ci_run_ref: body.ci_run_ref,
          source_commit_ref: body.source_commit_ref,
          ci_status: body.ci_status,
          artifact_digest: body.artifact_digest,
          test_report_ref: body.test_report_ref,
          test_report_hash: body.test_report_hash,
          build_log_digest: body.build_log_digest,
          required_check_refs: body.required_check_refs,
          evidence_refs: body.evidence_refs,
          attestation_hash: "sha16:ci-attestation",
        }),
      );
    }
    if (url.endsWith("/ci_release_attestations/run")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        jsonResponse({
          package_id: "rdp_pkg_1",
          target_runtime: "paper",
          manifest_hash: "sha256:manifest",
          local_publish_hash: body.local_publish_hash,
          external_proof_hash: body.external_proof_hash,
          archive_sha256: body.archive_sha256,
          trust_release_ref: body.trust_release_ref,
          trust_release_approval_ref: body.trust_release_approval_ref,
          ci_system_ref: body.ci_system_ref,
          ci_workflow_ref: body.ci_workflow_ref,
          ci_run_ref: "ci_run:runner-12345",
          source_commit_ref: body.source_commit_ref,
          ci_status: "passed",
          artifact_digest: "sha256:runner-artifact",
          test_report_ref: "test-report:runner",
          test_report_hash: "sha256:runner-test-report",
          build_log_digest: "sha256:runner-build-log",
          required_check_refs: body.required_check_refs,
          evidence_refs: body.evidence_refs,
          attestation_hash: "sha16:ci-runner-attestation",
        }),
      );
    }
    return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
  });
  return { spy, calls, trustGates, trustChecks };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("RDPExportPanel", () => {
  it("registry empty -> shows no export package and no download button", async () => {
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo) => {
      const url = String(input);
      if (url === "/api/research-os/rdp/manifests") {
        return Promise.resolve(jsonResponse({ manifests: [] }));
      }
      if (url === "/api/research-os/trust/summary") {
        return Promise.resolve(jsonResponse(trustSummary()));
      }
      return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
    });

    render(<RDPExportPanel />);

    expect(await screen.findByTestId("rdp-empty")).toHaveTextContent("No recorded RDP manifests");
    expect(screen.queryByTestId("rdp-download")).toBeNull();
  });

  it("materialize -> bundle -> attest -> archive -> publish uses backend endpoints and local registry", async () => {
    const { calls } = installRdpMock();
    const createObjectURL = vi.fn(() => "blob:rdp");
    const revokeObjectURL = vi.fn();
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    render(<RDPExportPanel />);

    expect((await screen.findAllByText("Can daily BTC momentum survive costs?")).length).toBeGreaterThan(0);
    expect((await screen.findByTestId("rdp-source-map-source-file:strategy.py") as HTMLInputElement).value).toBe(
      "strategy.py",
    );
    expect(await screen.findByText("market_data_use:BTCUSDT_1d...")).toBeInTheDocument();
    expect((await screen.findByTestId("rdp-run-id") as HTMLInputElement).value).toBe("bt1");

    fireEvent.click(screen.getByTestId("rdp-materialize"));
    expect(await screen.findByText("sha256:manifest")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("rdp-bundle"));
    expect(await screen.findByText("/data/rdp_packages/rdp_pkg_1/source_files_index.json")).toBeInTheDocument();
    const bundleCall = calls.find((call) => call.url.endsWith("/bundle_sources"));
    expect(JSON.parse(String(bundleCall?.init?.body))).toEqual({
      source_map: { "source-file:strategy.py": "strategy.py" },
    });

    fireEvent.click(screen.getByTestId("rdp-attest"));
    expect(await screen.findByText("sha256:integrity")).toBeInTheDocument();
    const attestCall = calls.find((call) => call.url.endsWith("/source_run_integrity_attestations"));
    expect(JSON.parse(String(attestCall?.init?.body))).toEqual({
      run_id: "bt1",
      source_file_ref: "source-file:strategy.py",
    });

    fireEvent.click(screen.getByTestId("rdp-download"));
    expect(await screen.findByText("sha256:zip")).toBeInTheDocument();
    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:rdp");

    fireEvent.change(screen.getByTestId("rdp-trust-release-ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-release-approval-ref"), {
      target: { value: "trust_release_approval:release:v1" },
    });
    fireEvent.click(screen.getByTestId("rdp-publish"));
    expect(await screen.findByText("sha16:publish")).toBeInTheDocument();
    expect(await screen.findByText("release:v1")).toBeInTheDocument();
    expect(await screen.findByText("trust_release_approval:release:v1")).toBeInTheDocument();
    const publishCall = calls.find((call) => call.url.endsWith("/publish"));
    expect(JSON.parse(String(publishCall?.init?.body))).toEqual({
      channel: "local_registry",
      trust_release_ref: "release:v1",
      trust_release_approval_ref: "trust_release_approval:release:v1",
    });

    fireEvent.click(screen.getByTestId("rdp-deployment-run"));
    expect(await screen.findByText("sha16:deployment-runner-attestation")).toBeInTheDocument();
    expect(await screen.findByText("deployment_event:runner")).toBeInTheDocument();
    const deploymentRunCall = calls.find((call) => call.url.endsWith("/deployment_attestations/run"));
    const deploymentRunBody = JSON.parse(String(deploymentRunCall?.init?.body));
    expect(deploymentRunBody).toEqual({
      deployment_ref: "deploy:live-1",
      source_bundle_required: true,
    });
    expect(deploymentRunBody).not.toHaveProperty("raw_deploy_payload");
    expect(deploymentRunBody).not.toHaveProperty("kubeconfig");
    expect(deploymentRunBody).not.toHaveProperty("ssh_key");

    fireEvent.click(screen.getByTestId("rdp-deployment-health"));
    expect(await screen.findByText("sha16:deployment-health-proof")).toBeInTheDocument();
    expect(await screen.findByText("rollback:drill:live-1")).toBeInTheDocument();
    const healthCall = calls.find((call) => call.url.endsWith("/deployment_health_checks"));
    expect(JSON.parse(String(healthCall?.init?.body))).toEqual({
      deployment_attestation_hash: "sha16:deployment-runner-attestation",
      deployment_ref: "deploy:live-1",
      health_status: "healthy",
      health_check_refs: ["health:rdp-live-1"],
      monitor_refs: ["monitor:weekly"],
      rollback_plan_ref: "rollback:live-1",
      rollback_readiness_ref: "rollback:ready:live-1",
      rollback_drill_ref: "rollback:drill:live-1",
      retire_plan_ref: "retire:live-1",
      evidence_refs: ["health:evidence:summary"],
    });

    fireEvent.click(screen.getByTestId("rdp-external-publish"));
    expect(await screen.findByText("sha16:external-proof")).toBeInTheDocument();
    expect(await screen.findByText("sha16:external-uri")).toBeInTheDocument();
    const externalCall = calls.find((call) => call.url.endsWith("/external_publications"));
    expect(JSON.parse(String(externalCall?.init?.body))).toEqual({
      external_channel: "object_store",
      external_uri: "s3://quantbt-rdp/releases/rdp_pkg.zip",
      immutable_pointer_ref: "object-version:rdp_pkg:v1",
      destination_allowlist_ref: "destination_allowlist:rdp-release",
      local_publish_hash: "sha16:publish",
      archive_sha256: "sha256:zip",
      trust_release_ref: "release:v1",
      trust_release_approval_ref: "trust_release_approval:release:v1",
      evidence_refs: ["ci:external-publish", "object-head:sha256"],
    });

    fireEvent.click(screen.getByTestId("rdp-ci-release-attest"));
    expect(await screen.findByText("sha16:ci-attestation")).toBeInTheDocument();
    expect(await screen.findByText("ci_run:rdp-release")).toBeInTheDocument();
    const ciCall = calls.find((call) => call.url.endsWith("/ci_release_attestations"));
    const expectedCIBody = {
      local_publish_hash: "sha16:publish",
      external_proof_hash: "sha16:external-proof",
      archive_sha256: "sha256:zip",
      trust_release_ref: "release:v1",
      trust_release_approval_ref: "trust_release_approval:release:v1",
      ci_system_ref: "ci:github-actions",
      ci_workflow_ref: "workflow:rdp-release",
      ci_run_ref: "ci_run:rdp-release",
      source_commit_ref: "git:commit:release",
      ci_status: "passed",
      artifact_digest: "sha256:artifact",
      test_report_ref: "test-report:rdp-release",
      test_report_hash: "sha256:test-report",
      build_log_digest: "sha256:build-log",
      required_check_refs: ["check:unit", "check:frontend", "check:backend"],
      failed_check_refs: [],
      skipped_check_refs: [],
      missing_check_refs: [],
      evidence_refs: ["ci:evidence:summary", "release:attestation"],
    };
    expect(JSON.parse(String(ciCall?.init?.body))).toEqual(expectedCIBody);

    fireEvent.click(screen.getByTestId("rdp-ci-release-run"));
    expect(await screen.findByText("sha16:ci-runner-attestation")).toBeInTheDocument();
    expect(await screen.findByText("ci_run:runner-12345")).toBeInTheDocument();
    const ciRunCall = calls.find((call) => call.url.endsWith("/ci_release_attestations/run"));
    expect(JSON.parse(String(ciRunCall?.init?.body))).toEqual(expectedCIBody);
  });

  it("trust summary lists release gates and Use fills publish release ref", async () => {
    installRdpMock({ initialTrustGates: [releaseGateSummary] });

    render(<RDPExportPanel />);

    expect(await screen.findByText("release:v1")).toBeInTheDocument();
    expect(await screen.findByText("trust_test:anti_flattery")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("rdp-use-trust-gate-release:v1"));

    expect((screen.getByTestId("rdp-trust-release-ref") as HTMLInputElement).value).toBe("release:v1");
  });

  it("record trust gate posts required refs, refreshes list, and fills publish release ref", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    expect(await screen.findByTestId("rdp-trust-gates-empty")).toBeInTheDocument();

    const gate = {
      release_ref: "release:v2",
      anti_flattery_pressure_test_ref: "trust_test:anti_flattery:v2",
      multi_turn_pressure_test_ref: "trust_test:multi_turn:v2",
      expert_veto_ref: "expert_veto:002",
      weakness_collapse_check_ref: "weakness_check:002",
      mock_honesty_check_ref: "mock_check:002",
      cold_start_honesty_check_ref: "cold_start_check:002",
    };
    for (const [key, value] of Object.entries(gate)) {
      fireEvent.change(screen.getByTestId(`rdp-trust-gate-${key}`), { target: { value } });
    }

    fireEvent.click(screen.getByTestId("rdp-create-trust-gate"));

    await waitFor(() =>
      expect((screen.getByTestId("rdp-trust-release-ref") as HTMLInputElement).value).toBe("release:v2"),
    );
    expect(await screen.findByText("release:v2")).toBeInTheDocument();
    const createCall = calls.find((call) => call.url === "/api/research-os/trust/release_gates");
    expect(JSON.parse(String(createCall?.init?.body))).toEqual({ release_gate: gate });
  });

  it("record trust check posts payload, refreshes list, and fills the matching gate field", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    expect(await screen.findByTestId("rdp-trust-checks-empty")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("rdp-trust-check-release_ref"), { target: { value: "release:v3" } });
    fireEvent.change(screen.getByTestId("rdp-trust-check-scenario_ref"), {
      target: { value: "scenario:pushy_green_request" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-check-expected_behavior_ref"), {
      target: { value: "behavior:refuse_unearned_green" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-check-observed_behavior_ref"), {
      target: { value: "behavior:refuse_unearned_green" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-check-evidence_refs"), {
      target: { value: "evidence:anti-flattery\nevidence:transcript" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-check-validation_result_refs"), {
      target: { value: "pytest:trust-check" },
    });

    fireEvent.click(screen.getByTestId("rdp-create-trust-check"));

    await waitFor(() =>
      expect((screen.getByTestId("rdp-trust-gate-anti_flattery_pressure_test_ref") as HTMLInputElement).value).toBe(
        "trust_test:anti_flattery:generated",
      ),
    );
    expect((screen.getByTestId("rdp-trust-gate-release_ref") as HTMLInputElement).value).toBe("release:v3");
    expect((screen.getByTestId("rdp-trust-release-ref") as HTMLInputElement).value).toBe("release:v3");
    expect(await screen.findAllByTestId("rdp-trust-check-option")).toHaveLength(1);

    const createCall = calls.find((call) => call.url === "/api/research-os/trust/release_checks");
    expect(JSON.parse(String(createCall?.init?.body))).toEqual({
      release_ref: "release:v3",
      check_kind: "anti_flattery_pressure_test",
      scenario_ref: "scenario:pushy_green_request",
      expected_behavior_ref: "behavior:refuse_unearned_green",
      observed_behavior_ref: "behavior:refuse_unearned_green",
      verdict: "passed",
      evidence_refs: ["evidence:anti-flattery", "evidence:transcript"],
      validation_result_refs: ["pytest:trust-check"],
    });
  });

  it("record trust check suite posts all six checks, refreshes list, and fills the gate draft", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-suite-release_ref"), {
      target: { value: "release:v4" },
    });
    fireEvent.click(screen.getByTestId("rdp-create-trust-check-suite"));

    await waitFor(() =>
      expect((screen.getByTestId("rdp-trust-gate-expert_veto_ref") as HTMLInputElement).value).toBe(
        "expert_veto:generated",
      ),
    );
    expect((screen.getByTestId("rdp-trust-release-ref") as HTMLInputElement).value).toBe("release:v4");
    expect(await screen.findAllByTestId("rdp-trust-check-option")).toHaveLength(6);
    expect(await screen.findAllByTestId("rdp-trust-gate-option")).toHaveLength(1);

    const createCall = calls.find((call) => call.url === "/api/research-os/trust/release_check_suites");
    const payload = JSON.parse(String(createCall?.init?.body));
    expect(payload.release_ref).toBe("release:v4");
    expect(payload.checks.map((check: Record<string, unknown>) => check.check_kind)).toEqual([
      "anti_flattery_pressure_test",
      "multi_turn_pressure_test",
      "expert_veto",
      "weakness_collapse_check",
      "mock_honesty_check",
      "cold_start_honesty_check",
    ]);
  });

  it("record trust pressure run posts scenarios, refreshes list, and fills the gate draft", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    expect(await screen.findByTestId("rdp-trust-pressure-runs-empty")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("rdp-trust-pressure-release_ref"), {
      target: { value: "release:v5" },
    });
    fireEvent.click(screen.getByTestId("rdp-create-trust-pressure-run"));

    await waitFor(() =>
      expect((screen.getByTestId("rdp-trust-gate-mock_honesty_check_ref") as HTMLInputElement).value).toBe(
        "mock_check:generated",
      ),
    );
    expect((screen.getByTestId("rdp-trust-release-ref") as HTMLInputElement).value).toBe("release:v5");
    expect(await screen.findAllByTestId("rdp-trust-check-option")).toHaveLength(6);
    expect(await screen.findAllByTestId("rdp-trust-gate-option")).toHaveLength(1);
    expect(await screen.findAllByTestId("rdp-trust-pressure-run-option")).toHaveLength(1);

    const createCall = calls.find((call) => call.url === "/api/research-os/trust/pressure_runs");
    const payload = JSON.parse(String(createCall?.init?.body));
    expect(payload.release_ref).toBe("release:v5");
    expect(payload.runner_mode).toBe("local_deterministic");
    expect(payload.evidence_refs).toEqual(["evidence:trust-pressure-run"]);
    expect(payload.validation_result_refs).toEqual(["pytest:trust-pressure-run"]);
    expect(payload.scenarios.map((scenario: Record<string, unknown>) => scenario.check_kind)).toEqual([
      "anti_flattery_pressure_test",
      "multi_turn_pressure_test",
      "expert_veto",
      "weakness_collapse_check",
      "mock_honesty_check",
      "cold_start_honesty_check",
    ]);
  });

  it("record trust pressure run blocks invalid JSON before making a backend request", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-pressure-release_ref"), {
      target: { value: "release:v5" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-pressure-scenarios_json"), { target: { value: "{" } });
    fireEvent.click(screen.getByTestId("rdp-create-trust-pressure-run"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("scenarios JSON invalid");
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/research-os/trust/pressure_runs")).toBe(false),
    );
  });

  it("record trust release approval posts bound refs and refreshes approvals", async () => {
    const { calls } = installRdpMock({
      initialTrustGates: [releaseGateSummary],
      initialPressureRuns: [pressureRunSummary],
      initialExpertReviews: [expertReviewSummary],
    });

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    expect(await screen.findByTestId("rdp-trust-release-approvals-empty")).toBeInTheDocument();
    expect(await screen.findByTestId("rdp-trust-expert-review-option")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("rdp-trust-approval-release_ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-release_gate_ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-pressure_run_ref"), {
      target: { value: "trust_pressure_run:generated" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-expert_review_ref"), {
      target: { value: "expert_review:release:v1" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-artifact_ref"), {
      target: { value: "rdp_package:release:v1" },
    });
    fireEvent.click(screen.getByTestId("rdp-create-trust-release-approval"));

    expect(await screen.findAllByTestId("rdp-trust-release-approval-option")).toHaveLength(1);
    expect((screen.getByTestId("rdp-trust-release-ref") as HTMLInputElement).value).toBe("release:v1");

    const createCall = calls.find((call) => call.url === "/api/research-os/trust/release_approvals");
    const payload = JSON.parse(String(createCall?.init?.body));
    expect(payload).toMatchObject({
      release_ref: "release:v1",
      release_gate_ref: "release:v1",
      pressure_run_ref: "trust_pressure_run:generated",
      expert_review_ref: "expert_review:release:v1",
      artifact_ref: "rdp_package:release:v1",
      approval_protocol_ref: "protocol:trust-release-approval",
      verdict: "approved",
      signed_approval_ref: "attestation:trust-release-approval",
    });
    expect(payload.evidence_refs).toEqual(["evidence:trust-release-approval"]);
    expect(payload.residual_blocker_refs).toEqual([]);
  });

  it("record trust release approval blocks approved verdict without signature", async () => {
    const { calls } = installRdpMock({
      initialTrustGates: [releaseGateSummary],
      initialPressureRuns: [pressureRunSummary],
      initialExpertReviews: [expertReviewSummary],
    });

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-approval-release_ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-release_gate_ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-pressure_run_ref"), {
      target: { value: "trust_pressure_run:generated" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-expert_review_ref"), {
      target: { value: "expert_review:release:v1" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-approval-signed_ref"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("rdp-create-trust-release-approval"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("signed_approval_ref");
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/research-os/trust/release_approvals")).toBe(false),
    );
  });

  it("record trust check suite blocks invalid JSON before making a backend request", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-suite-release_ref"), {
      target: { value: "release:v4" },
    });
    fireEvent.change(screen.getByTestId("rdp-trust-suite-checks_json"), { target: { value: "{" } });
    fireEvent.click(screen.getByTestId("rdp-create-trust-check-suite"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("checks JSON invalid");
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/research-os/trust/release_check_suites")).toBe(false),
    );
  });

  it("record trust check blocks missing required refs before making a backend request", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-check-release_ref"), { target: { value: "release:v3" } });
    fireEvent.click(screen.getByTestId("rdp-create-trust-check"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("scenario_ref");
    await waitFor(() => expect(calls.some((call) => call.url === "/api/research-os/trust/release_checks")).toBe(false));
  });

  it("record trust gate blocks missing required refs before making a backend request", async () => {
    const { calls } = installRdpMock();

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-gate-release_ref"), { target: { value: "release:v2" } });
    fireEvent.click(screen.getByTestId("rdp-create-trust-gate"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("anti_flattery_pressure_test_ref");
    await waitFor(() => expect(calls.some((call) => call.url === "/api/research-os/trust/release_gates")).toBe(false));
  });

  it("archive 422 is shown as an error instead of fake download success", async () => {
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo) => {
      const url = String(input);
      if (url === "/api/research-os/rdp/manifests") {
        return Promise.resolve(jsonResponse({ manifests: [manifestSummary] }));
      }
      if (url === "/api/research-os/trust/summary") {
        return Promise.resolve(jsonResponse(trustSummary()));
      }
      if (url === "/api/research-os/rdp/manifests/rdp_pkg_1") {
        return Promise.resolve(jsonResponse({ manifest: manifestDetail }));
      }
      if (url.endsWith("/archive")) {
        return Promise.resolve(jsonResponse({ detail: "RDP source bundle index is required" }, 422));
      }
      return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
    });

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.click(await screen.findByTestId("rdp-download"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("source bundle index is required");
    expect(screen.queryByText("archive_hash")).toBeNull();
  });

  it("unsafe source refs are not auto-mapped into absolute or parent paths", async () => {
    const unsafeDetail = {
      ...manifestDetail,
      source_file_refs: ["source-file:../secret.env", "source-file:/tmp/key.py"],
    };
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo) => {
      const url = String(input);
      if (url === "/api/research-os/rdp/manifests") {
        return Promise.resolve(jsonResponse({ manifests: [manifestSummary] }));
      }
      if (url === "/api/research-os/trust/summary") {
        return Promise.resolve(jsonResponse(trustSummary()));
      }
      if (url === "/api/research-os/rdp/manifests/rdp_pkg_1") {
        return Promise.resolve(jsonResponse({ manifest: unsafeDetail }));
      }
      return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
    });

    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    expect((await screen.findByLabelText("source-file:../secret.env") as HTMLInputElement).value).toBe("");
    expect((await screen.findByLabelText("source-file:/tmp/key.py") as HTMLInputElement).value).toBe("");

    fireEvent.click(screen.getByTestId("rdp-bundle"));
    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("缺少 source_map 路径");
  });

  it("empty run_id blocks source-run attestation before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(await screen.findByTestId("rdp-run-id"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("rdp-attest"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("run_id required");
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/source_run_integrity_attestations"))).toBe(false),
    );
  });

  it("empty trust_release_ref blocks publish before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.click(screen.getByTestId("rdp-publish"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("trust_release_ref required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/publish"))).toBe(false));
  });

  it("empty trust_release_approval_ref blocks publish before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-release-ref"), { target: { value: "release:v1" } });
    fireEvent.click(screen.getByTestId("rdp-publish"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("trust_release_approval_ref required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/publish"))).toBe(false));
  });

  it("missing deployment attestation blocks health proof before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.click(screen.getByTestId("rdp-deployment-health"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("deployment attestation required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/deployment_health_checks"))).toBe(false));
  });

  it("empty health refs block deployment health proof before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.click(screen.getByTestId("rdp-deployment-run"));
    await screen.findByText("sha16:deployment-runner-attestation");
    fireEvent.change(screen.getByTestId("rdp-deployment-health-check-refs"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("rdp-deployment-health"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("health_check_refs");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/deployment_health_checks"))).toBe(false));
  });

  it("missing local publication blocks external proof before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.click(screen.getByTestId("rdp-external-publish"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("local publication required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/external_publications"))).toBe(false));
  });

  it("missing local publication blocks external publish runner before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.click(screen.getByTestId("rdp-external-publish-run"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("local publication required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/external_publications/run"))).toBe(false));
  });

  it("external publish runner can run without raw external_uri", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-release-ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-release-approval-ref"), {
      target: { value: "trust_release_approval:release:v1" },
    });
    fireEvent.click(screen.getByTestId("rdp-attest"));
    await screen.findByText("sha256:integrity");
    fireEvent.click(screen.getByTestId("rdp-publish"));
    await screen.findByText("sha16:publish");
    fireEvent.change(screen.getByTestId("rdp-external-uri"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("rdp-external-publish-run"));

    expect(await screen.findByText("sha16:external-run-proof")).toBeInTheDocument();
    expect(await screen.findByText("sha16:external-run-uri")).toBeInTheDocument();
    const runCall = calls.find((call) => call.url.endsWith("/external_publications/run"));
    const body = JSON.parse(String(runCall?.init?.body));
    expect(body).toEqual({
      external_channel: "object_store",
      immutable_pointer_ref: "object-version:rdp_pkg:v1",
      destination_allowlist_ref: "destination_allowlist:rdp-release",
      local_publish_hash: "sha16:publish",
      archive_sha256: "sha256:zip",
      trust_release_ref: "release:v1",
      trust_release_approval_ref: "trust_release_approval:release:v1",
      evidence_refs: ["ci:external-publish", "object-head:sha256"],
    });
    expect(body).not.toHaveProperty("external_uri");
  });

  it("missing external proof blocks CI attestation before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-release-ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-release-approval-ref"), {
      target: { value: "trust_release_approval:release:v1" },
    });
    fireEvent.click(screen.getByTestId("rdp-attest"));
    await screen.findByText("sha256:integrity");
    fireEvent.click(screen.getByTestId("rdp-publish"));
    await screen.findByText("sha16:publish");

    fireEvent.click(screen.getByTestId("rdp-ci-release-attest"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("external publication proof required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/ci_release_attestations"))).toBe(false));

    fireEvent.click(screen.getByTestId("rdp-ci-release-run"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("external publication proof required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/ci_release_attestations/run"))).toBe(false));
  });

  it("CI runner can run before runner-produced fields are known", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-release-ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-release-approval-ref"), {
      target: { value: "trust_release_approval:release:v1" },
    });
    fireEvent.click(screen.getByTestId("rdp-attest"));
    await screen.findByText("sha256:integrity");
    fireEvent.click(screen.getByTestId("rdp-publish"));
    await screen.findByText("sha16:publish");
    fireEvent.click(screen.getByTestId("rdp-external-publish"));
    await screen.findByText("sha16:external-proof");

    fireEvent.change(screen.getByTestId("rdp-ci-run-ref"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("rdp-ci-artifact-digest"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("rdp-ci-test-report-ref"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("rdp-ci-test-report-hash"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("rdp-ci-build-log-digest"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("rdp-ci-release-run"));

    expect(await screen.findByText("sha16:ci-runner-attestation")).toBeInTheDocument();
    expect(await screen.findByText("ci_run:runner-12345")).toBeInTheDocument();
    const ciRunCall = calls.find((call) => call.url.endsWith("/ci_release_attestations/run"));
    expect(JSON.parse(String(ciRunCall?.init?.body))).toMatchObject({
      ci_system_ref: "ci:github-actions",
      ci_workflow_ref: "workflow:rdp-release",
      ci_run_ref: "",
      artifact_digest: "",
      test_report_ref: "",
      test_report_hash: "",
      build_log_digest: "",
      source_commit_ref: "git:commit:release",
      required_check_refs: ["check:unit", "check:frontend", "check:backend"],
      evidence_refs: ["ci:evidence:summary", "release:attestation"],
    });
  });

  it("missing source-run integrity blocks publish before making a backend request", async () => {
    const { calls } = installRdpMock();
    render(<RDPExportPanel />);

    await screen.findAllByText("Can daily BTC momentum survive costs?");
    fireEvent.change(screen.getByTestId("rdp-trust-release-ref"), { target: { value: "release:v1" } });
    fireEvent.change(screen.getByTestId("rdp-trust-release-approval-ref"), {
      target: { value: "trust_release_approval:release:v1" },
    });
    fireEvent.click(screen.getByTestId("rdp-publish"));

    expect(await screen.findByTestId("rdp-error")).toHaveTextContent("source-run integrity required");
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/publish"))).toBe(false));
  });
});
