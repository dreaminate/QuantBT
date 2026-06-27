import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Pill } from "../../../components/desk";
import { authFetch } from "../../../lib/auth";

interface RDPManifestSummary {
  package_id: string;
  research_question: string;
  asset_refs?: string[];
  run_refs?: string[];
  target_runtime: string;
  artifact_hash: string;
}

interface RDPManifestDetail extends RDPManifestSummary {
  source_file_refs?: string[];
  graph_refs?: string[];
  dataset_version_refs?: string[];
  market_data_use_validation_refs?: string[];
  ingestion_skill_refs?: string[];
  mathematical_refs?: string[];
  methodology_choice_refs?: string[];
  unverified_residuals?: string[];
  deployment_refs?: string[];
  monitor_refs?: string[];
  rollback_plan_ref?: string;
  retire_plan_ref?: string;
  reproducibility_command?: string;
}

interface MaterializeResponse {
  package_id: string;
  manifest_hash: string;
  manifest_path: string;
  refs_index_path: string;
  source_file_refs: string[];
}

interface BundleResponse {
  package_id: string;
  source_files_index_path: string;
  source_files: { source_file_ref: string; source_path: string; content_sha256: string }[];
}

interface IntegrityResponse {
  package_id: string;
  run_id: string;
  run_ref: string;
  source_file_ref: string;
  artifact_hash: string;
  integrity_hash: string;
  run_strategy_sha256: string;
}

interface ArchiveState {
  packageId: string;
  archiveHash: string;
  fileCount: string;
  downloadedBytes: number;
}

interface PublishResponse {
  package_id: string;
  channel: string;
  archive_sha256: string;
  published_archive_path: string;
  publish_hash: string;
  trust_release_ref: string;
  trust_release_approval_ref: string;
}

interface ExternalPublicationProofResponse {
  package_id: string;
  external_channel: string;
  target_runtime: string;
  local_publish_hash: string;
  archive_sha256: string;
  external_uri_digest: string;
  immutable_pointer_ref: string;
  destination_allowlist_ref: string;
  trust_release_ref: string;
  trust_release_approval_ref: string;
  evidence_refs: string[];
  proof_hash: string;
}

interface CIReleaseAttestationResponse {
  package_id: string;
  target_runtime: string;
  manifest_hash: string;
  local_publish_hash: string;
  external_proof_hash: string;
  archive_sha256: string;
  trust_release_ref: string;
  trust_release_approval_ref: string;
  ci_system_ref: string;
  ci_workflow_ref: string;
  ci_run_ref: string;
  source_commit_ref: string;
  ci_status: string;
  artifact_digest: string;
  test_report_ref: string;
  test_report_hash: string;
  build_log_digest: string;
  required_check_refs: string[];
  evidence_refs: string[];
  attestation_hash: string;
}

interface DeploymentAttestationResponse {
  package_id: string;
  deployment_ref: string;
  target_runtime: string;
  attestation_hash: string;
  manifest_hash: string;
  source_bundle_index_sha256: string;
  deployment_event_ref: string;
  deployment_artifact_digest: string;
  evidence_refs: string[];
}

interface DeploymentHealthCheckResponse {
  package_id: string;
  deployment_ref: string;
  target_runtime: string;
  deployment_attestation_hash: string;
  health_status: string;
  health_check_refs: string[];
  monitor_refs: string[];
  rollback_plan_ref: string;
  rollback_readiness_ref: string;
  rollback_drill_ref: string;
  retire_plan_ref: string;
  evidence_refs: string[];
  proof_hash: string;
}

interface TrustReleaseGateSummary {
  release_ref: string;
  anti_flattery_pressure_test_ref: string;
  multi_turn_pressure_test_ref: string;
  expert_veto_ref: string;
  weakness_collapse_check_ref: string;
  mock_honesty_check_ref: string;
  cold_start_honesty_check_ref: string;
}

type TrustReleaseCheckKind =
  | "anti_flattery_pressure_test"
  | "multi_turn_pressure_test"
  | "expert_veto"
  | "weakness_collapse_check"
  | "mock_honesty_check"
  | "cold_start_honesty_check";

interface TrustReleaseCheckSummary {
  check_ref: string;
  release_ref: string;
  check_kind: TrustReleaseCheckKind;
  scenario_ref: string;
  expected_behavior_ref: string;
  observed_behavior_ref: string;
  verdict: string;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

interface TrustPressureRunSummary {
  runner_ref: string;
  release_ref: string;
  runner_mode: string;
  source_hash: string;
  release_gate_ref: string;
  check_refs: string[];
  scenario_refs: string[];
  evidence_refs: string[];
  validation_result_refs: string[];
  failed_scenario_refs: string[];
}

interface TrustExpertReviewSummary {
  review_ref: string;
  release_ref: string;
  reviewer_ref: string;
  reviewer_independence_ref: string;
  artifact_ref: string;
  review_protocol_ref: string;
  verdict: string;
  source_hash: string;
  evidence_refs: string[];
  veto_reason_refs: string[];
  signed_attestation_ref?: string | null;
}

interface TrustReleaseApprovalSummary {
  approval_ref: string;
  release_ref: string;
  release_gate_ref: string;
  pressure_run_ref: string;
  expert_review_ref: string;
  artifact_ref: string;
  approval_protocol_ref: string;
  verdict: string;
  source_hash: string;
  evidence_refs: string[];
  signed_approval_ref?: string | null;
  residual_blocker_refs: string[];
}

interface TrustSummaryResponse {
  user: string;
  expert_review_total?: number;
  expert_reviews?: TrustExpertReviewSummary[];
  release_gate_total: number;
  release_gates: TrustReleaseGateSummary[];
  release_check_total: number;
  release_checks: TrustReleaseCheckSummary[];
  pressure_run_total: number;
  pressure_runs: TrustPressureRunSummary[];
  release_approval_total?: number;
  release_approvals?: TrustReleaseApprovalSummary[];
}

interface TrustReleaseGateRecordResponse {
  release_ref: string;
  recorded_by: string;
}

interface TrustReleaseCheckRecordResponse extends TrustReleaseCheckSummary {
  recorded_by: string;
}

interface TrustReleaseCheckSuiteResponse {
  release_ref: string;
  recorded_by: string;
  release_gate: TrustReleaseGateSummary;
  release_checks: TrustReleaseCheckSummary[];
  check_refs: Record<TrustReleaseCheckKind, string>;
}

interface TrustPressureRunResponse {
  runner_ref: string;
  release_ref: string;
  recorded_by: string;
  pressure_run: TrustPressureRunSummary;
  release_gate: TrustReleaseGateSummary;
  release_checks: TrustReleaseCheckSummary[];
  check_refs: Record<TrustReleaseCheckKind, string>;
}

interface TrustReleaseApprovalResponse {
  approval_ref: string;
  release_ref: string;
  recorded_by: string;
  release_approval: TrustReleaseApprovalSummary;
}

interface TrustReleaseCheckDraft {
  release_ref: string;
  check_kind: TrustReleaseCheckKind;
  scenario_ref: string;
  expected_behavior_ref: string;
  observed_behavior_ref: string;
  evidence_refs: string;
  validation_result_refs: string;
  verdict: string;
  check_ref: string;
}

interface TrustReleaseSuiteDraft {
  release_ref: string;
  checks_json: string;
}

interface TrustPressureRunDraft {
  release_ref: string;
  runner_mode: string;
  evidence_refs: string;
  validation_result_refs: string;
  scenarios_json: string;
}

interface TrustReleaseApprovalDraft {
  release_ref: string;
  release_gate_ref: string;
  pressure_run_ref: string;
  expert_review_ref: string;
  artifact_ref: string;
  approval_protocol_ref: string;
  verdict: string;
  evidence_refs: string;
  signed_approval_ref: string;
  residual_blocker_refs: string;
}

interface ExternalPublicationDraft {
  external_channel: string;
  external_uri: string;
  immutable_pointer_ref: string;
  destination_allowlist_ref: string;
  evidence_refs: string;
}

interface CIReleaseAttestationDraft {
  ci_system_ref: string;
  ci_workflow_ref: string;
  ci_run_ref: string;
  source_commit_ref: string;
  ci_status: string;
  artifact_digest: string;
  test_report_ref: string;
  test_report_hash: string;
  build_log_digest: string;
  required_check_refs: string;
  failed_check_refs: string;
  skipped_check_refs: string;
  missing_check_refs: string;
  evidence_refs: string;
}

interface DeploymentProofDraft {
  deployment_ref: string;
  health_status: string;
  health_check_refs: string;
  monitor_refs: string;
  rollback_plan_ref: string;
  rollback_readiness_ref: string;
  rollback_drill_ref: string;
  retire_plan_ref: string;
  evidence_refs: string;
}

type AsyncStatus<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; value: T };

function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (typeof detail === "object" && detail && "detail" in detail) {
    return String((detail as { detail: unknown }).detail);
  }
  return fallback;
}

async function readError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const detail = await response.json().catch(() => ({}));
    return apiErrorMessage(detail, `HTTP ${response.status}`);
  }
  const text = await response.text().catch(() => "");
  return text || `HTTP ${response.status}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(path, init);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
}

function sourcePathFromRef(ref: string): string {
  const stripped = ref.startsWith("source-file:") ? ref.slice("source-file:".length) : ref;
  if (!stripped || stripped.startsWith("/") || stripped.includes("\\") || stripped.includes("..")) {
    return "";
  }
  const parts = stripped.split("/").filter(Boolean);
  if (parts.length === 0 || parts.some((part) => part === "." || part === "..")) return "";
  return parts.join("/");
}

function runIdFromRef(ref: string | undefined): string {
  if (!ref) return "";
  return ref.startsWith("run:") ? ref.slice("run:".length) : ref;
}

function sourceMapIsSafe(sourceMap: Record<string, string>, refs: string[]): string | null {
  for (const ref of refs) {
    const value = sourceMap[ref]?.trim() ?? "";
    if (!value) return `${ref} 缺少 source_map 路径`;
    if (value.startsWith("/") || value.includes("\\") || value.split("/").some((part) => part === "..")) {
      return `${ref} 的 source_map 路径越界`;
    }
  }
  return null;
}

function ellipsis(value: string, size = 18): string {
  if (value.length <= size) return value;
  return `${value.slice(0, size)}...`;
}

function splitRefs(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

const panelStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(210px, 280px) minmax(0, 1fr)",
  gap: 14,
  minHeight: "100%",
};

const sectionStyle: CSSProperties = {
  border: "1px solid var(--desk-border)",
  background: "var(--desk-card)",
  borderRadius: "var(--desk-radius-lg)",
  overflow: "hidden",
};

const sectionHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "9px 12px",
  borderBottom: "1px solid var(--desk-border)",
  color: "var(--desk-text)",
  fontSize: 12,
  fontWeight: 700,
};

const sectionBodyStyle: CSSProperties = {
  padding: 12,
};

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: "var(--desk-input)",
  border: "1px solid var(--desk-border)",
  borderRadius: "var(--desk-radius-sm)",
  color: "var(--desk-text)",
  fontFamily: "inherit",
  fontSize: 12,
  padding: "7px 9px",
};

const labelStyle: CSSProperties = {
  display: "grid",
  gap: 5,
  color: "var(--desk-text-muted)",
  fontSize: 11,
};

const emptyTrustReleaseGateDraft: TrustReleaseGateSummary = {
  release_ref: "",
  anti_flattery_pressure_test_ref: "",
  multi_turn_pressure_test_ref: "",
  expert_veto_ref: "",
  weakness_collapse_check_ref: "",
  mock_honesty_check_ref: "",
  cold_start_honesty_check_ref: "",
};

const trustReleaseGateFields: { key: keyof TrustReleaseGateSummary; label: string }[] = [
  { key: "release_ref", label: "release_ref" },
  { key: "anti_flattery_pressure_test_ref", label: "anti_flattery_pressure_test_ref" },
  { key: "multi_turn_pressure_test_ref", label: "multi_turn_pressure_test_ref" },
  { key: "expert_veto_ref", label: "expert_veto_ref" },
  { key: "weakness_collapse_check_ref", label: "weakness_collapse_check_ref" },
  { key: "mock_honesty_check_ref", label: "mock_honesty_check_ref" },
  { key: "cold_start_honesty_check_ref", label: "cold_start_honesty_check_ref" },
];

const trustReleaseCheckKinds: {
  kind: TrustReleaseCheckKind;
  label: string;
  gateField: keyof TrustReleaseGateSummary;
}[] = [
  {
    kind: "anti_flattery_pressure_test",
    label: "anti_flattery_pressure_test",
    gateField: "anti_flattery_pressure_test_ref",
  },
  {
    kind: "multi_turn_pressure_test",
    label: "multi_turn_pressure_test",
    gateField: "multi_turn_pressure_test_ref",
  },
  { kind: "expert_veto", label: "expert_veto", gateField: "expert_veto_ref" },
  {
    kind: "weakness_collapse_check",
    label: "weakness_collapse_check",
    gateField: "weakness_collapse_check_ref",
  },
  { kind: "mock_honesty_check", label: "mock_honesty_check", gateField: "mock_honesty_check_ref" },
  {
    kind: "cold_start_honesty_check",
    label: "cold_start_honesty_check",
    gateField: "cold_start_honesty_check_ref",
  },
];

const emptyTrustReleaseCheckDraft: TrustReleaseCheckDraft = {
  release_ref: "",
  check_kind: "anti_flattery_pressure_test",
  scenario_ref: "",
  expected_behavior_ref: "",
  observed_behavior_ref: "",
  evidence_refs: "",
  validation_result_refs: "",
  verdict: "passed",
  check_ref: "",
};

const trustReleaseSuiteChecksTemplate = trustReleaseCheckKinds.map(({ kind }) => ({
  check_kind: kind,
  scenario_ref: `scenario:${kind}`,
  expected_behavior_ref: `behavior:${kind}:expected`,
  observed_behavior_ref: `behavior:${kind}:expected`,
  verdict: "passed",
  evidence_refs: [`evidence:${kind}`],
  validation_result_refs: [`pytest:${kind}`],
}));

const emptyTrustReleaseSuiteDraft: TrustReleaseSuiteDraft = {
  release_ref: "",
  checks_json: JSON.stringify(trustReleaseSuiteChecksTemplate, null, 2),
};

const trustPressureRunScenariosTemplate = trustReleaseSuiteChecksTemplate.map((item) => ({
  check_kind: item.check_kind,
  scenario_ref: item.scenario_ref,
  expected_behavior_ref: item.expected_behavior_ref,
  observed_behavior_ref: item.observed_behavior_ref,
  evidence_refs: item.evidence_refs,
  validation_result_refs: item.validation_result_refs,
  outcome_flags: [],
}));

const emptyTrustPressureRunDraft: TrustPressureRunDraft = {
  release_ref: "",
  runner_mode: "local_deterministic",
  evidence_refs: "evidence:trust-pressure-run",
  validation_result_refs: "pytest:trust-pressure-run",
  scenarios_json: JSON.stringify(trustPressureRunScenariosTemplate, null, 2),
};

const emptyTrustReleaseApprovalDraft: TrustReleaseApprovalDraft = {
  release_ref: "",
  release_gate_ref: "",
  pressure_run_ref: "",
  expert_review_ref: "",
  artifact_ref: "rdp_package:release",
  approval_protocol_ref: "protocol:trust-release-approval",
  verdict: "approved",
  evidence_refs: "evidence:trust-release-approval",
  signed_approval_ref: "attestation:trust-release-approval",
  residual_blocker_refs: "",
};

const emptyExternalPublicationDraft: ExternalPublicationDraft = {
  external_channel: "object_store",
  external_uri: "s3://quantbt-rdp/releases/rdp_pkg.zip",
  immutable_pointer_ref: "object-version:rdp_pkg:v1",
  destination_allowlist_ref: "destination_allowlist:rdp-release",
  evidence_refs: "ci:external-publish,object-head:sha256",
};

const emptyCIReleaseAttestationDraft: CIReleaseAttestationDraft = {
  ci_system_ref: "ci:github-actions",
  ci_workflow_ref: "workflow:rdp-release",
  ci_run_ref: "ci_run:rdp-release",
  source_commit_ref: "git:commit:release",
  ci_status: "passed",
  artifact_digest: "sha256:artifact",
  test_report_ref: "test-report:rdp-release",
  test_report_hash: "sha256:test-report",
  build_log_digest: "sha256:build-log",
  required_check_refs: "check:unit,check:frontend,check:backend",
  failed_check_refs: "",
  skipped_check_refs: "",
  missing_check_refs: "",
  evidence_refs: "ci:evidence:summary,release:attestation",
};

const emptyDeploymentProofDraft: DeploymentProofDraft = {
  deployment_ref: "deploy:live-1",
  health_status: "healthy",
  health_check_refs: "health:rdp-live-1",
  monitor_refs: "monitor:weekly",
  rollback_plan_ref: "rollback:live-1",
  rollback_readiness_ref: "rollback:ready:live-1",
  rollback_drill_ref: "rollback:drill:live-1",
  retire_plan_ref: "retire:live-1",
  evidence_refs: "health:evidence:summary",
};

function ActionButton({
  children,
  onClick,
  disabled,
  tone = "neutral",
  testId,
}: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "neutral" | "accent" | "danger";
  testId?: string;
}) {
  const bg = tone === "accent" ? "var(--desk-accent)" : "transparent";
  const fg = tone === "accent" ? "var(--desk-accent-ink)" : tone === "danger" ? "var(--desk-danger)" : "var(--desk-text-muted)";
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? "var(--desk-soft-btn)" : bg,
        border: "1px solid var(--desk-border)",
        color: disabled ? "var(--desk-text-faint)" : fg,
        borderRadius: "var(--desk-radius-sm)",
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: tone === "accent" ? 700 : 500,
        padding: "7px 10px",
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function RefList({ refs }: { refs: string[] }) {
  if (refs.length === 0) {
    return <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>none</span>;
  }
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
      {refs.map((ref) => (
        <Pill key={ref} tone="ghost" title={ref}>
          {ellipsis(ref, 26)}
        </Pill>
      ))}
    </div>
  );
}

function ResultLine({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "130px minmax(0, 1fr)", gap: 8, fontSize: 11.5 }}>
      <span style={{ color: "var(--desk-text-faint)" }}>{label}</span>
      <span style={{ color: "var(--desk-text-muted)", overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

export function RDPExportPanel() {
  const [listStatus, setListStatus] = useState<AsyncStatus<RDPManifestSummary[]>>({ state: "loading" });
  const [trustStatus, setTrustStatus] = useState<AsyncStatus<TrustSummaryResponse>>({ state: "loading" });
  const [selectedPackageId, setSelectedPackageId] = useState("");
  const [detailStatus, setDetailStatus] = useState<AsyncStatus<RDPManifestDetail>>({ state: "idle" });
  const [sourceMap, setSourceMap] = useState<Record<string, string>>({});
  const [runId, setRunId] = useState("");
  const [selectedSourceRef, setSelectedSourceRef] = useState("");
  const [trustReleaseRef, setTrustReleaseRef] = useState("");
  const [trustReleaseApprovalRef, setTrustReleaseApprovalRef] = useState("");
  const [trustReleaseGateDraft, setTrustReleaseGateDraft] = useState<TrustReleaseGateSummary>(
    emptyTrustReleaseGateDraft,
  );
  const [trustReleaseCheckDraft, setTrustReleaseCheckDraft] = useState<TrustReleaseCheckDraft>(
    emptyTrustReleaseCheckDraft,
  );
  const [trustReleaseSuiteDraft, setTrustReleaseSuiteDraft] = useState<TrustReleaseSuiteDraft>(
    emptyTrustReleaseSuiteDraft,
  );
  const [trustPressureRunDraft, setTrustPressureRunDraft] = useState<TrustPressureRunDraft>(
    emptyTrustPressureRunDraft,
  );
  const [trustReleaseApprovalDraft, setTrustReleaseApprovalDraft] = useState<TrustReleaseApprovalDraft>(
    emptyTrustReleaseApprovalDraft,
  );
  const [externalPublicationDraft, setExternalPublicationDraft] = useState<ExternalPublicationDraft>(
    emptyExternalPublicationDraft,
  );
  const [ciReleaseDraft, setCiReleaseDraft] = useState<CIReleaseAttestationDraft>(
    emptyCIReleaseAttestationDraft,
  );
  const [deploymentProofDraft, setDeploymentProofDraft] = useState<DeploymentProofDraft>(
    emptyDeploymentProofDraft,
  );
  const [materialized, setMaterialized] = useState<MaterializeResponse | null>(null);
  const [bundled, setBundled] = useState<BundleResponse | null>(null);
  const [integrity, setIntegrity] = useState<IntegrityResponse | null>(null);
  const [archive, setArchive] = useState<ArchiveState | null>(null);
  const [publication, setPublication] = useState<PublishResponse | null>(null);
  const [externalPublication, setExternalPublication] = useState<ExternalPublicationProofResponse | null>(null);
  const [ciReleaseAttestation, setCiReleaseAttestation] = useState<CIReleaseAttestationResponse | null>(null);
  const [deploymentAttestation, setDeploymentAttestation] = useState<DeploymentAttestationResponse | null>(null);
  const [deploymentHealthCheck, setDeploymentHealthCheck] = useState<DeploymentHealthCheckResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setListStatus({ state: "loading" });
    requestJson<{ manifests: RDPManifestSummary[] }>("/api/research-os/rdp/manifests")
      .then((payload) => {
        if (!alive) return;
        const manifests = payload.manifests ?? [];
        setListStatus({ state: "ready", value: manifests });
        setSelectedPackageId((current) => current || manifests[0]?.package_id || "");
      })
      .catch((exc: Error) => {
        if (alive) setListStatus({ state: "error", message: exc.message });
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setTrustStatus({ state: "loading" });
    requestJson<TrustSummaryResponse>("/api/research-os/trust/summary")
      .then((payload) => {
        if (alive) setTrustStatus({ state: "ready", value: payload });
      })
      .catch((exc: Error) => {
        if (alive) setTrustStatus({ state: "error", message: exc.message });
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedPackageId) {
      setDetailStatus({ state: "idle" });
      return;
    }
    let alive = true;
    setError(null);
    setMaterialized(null);
    setBundled(null);
    setIntegrity(null);
    setArchive(null);
    setPublication(null);
    setExternalPublication(null);
    setCiReleaseAttestation(null);
    setDeploymentAttestation(null);
    setDeploymentHealthCheck(null);
    setDetailStatus({ state: "loading" });
    requestJson<{ manifest: RDPManifestDetail }>(
      `/api/research-os/rdp/manifests/${encodeURIComponent(selectedPackageId)}`,
    )
      .then((payload) => {
        if (!alive) return;
        const manifest = payload.manifest;
        const refs = manifest.source_file_refs ?? [];
        setSourceMap(Object.fromEntries(refs.map((ref) => [ref, sourcePathFromRef(ref)])));
        setSelectedSourceRef(refs[0] ?? "");
        setRunId(runIdFromRef(manifest.run_refs?.[0]));
        setDetailStatus({ state: "ready", value: manifest });
      })
      .catch((exc: Error) => {
        if (alive) setDetailStatus({ state: "error", message: exc.message });
      });
    return () => {
      alive = false;
    };
  }, [selectedPackageId]);

  const manifest = detailStatus.state === "ready" ? detailStatus.value : null;
  const sourceRefs = useMemo(() => manifest?.source_file_refs ?? [], [manifest]);
  const runRefs = useMemo(() => manifest?.run_refs ?? [], [manifest]);
  const trustReleaseGates = trustStatus.state === "ready" ? trustStatus.value.release_gates ?? [] : [];
  const trustReleaseChecks = trustStatus.state === "ready" ? trustStatus.value.release_checks ?? [] : [];
  const trustPressureRuns = trustStatus.state === "ready" ? trustStatus.value.pressure_runs ?? [] : [];
  const trustExpertReviews = trustStatus.state === "ready" ? trustStatus.value.expert_reviews ?? [] : [];
  const trustReleaseApprovals = trustStatus.state === "ready" ? trustStatus.value.release_approvals ?? [] : [];

  async function refreshTrustSummary() {
    setTrustStatus({ state: "loading" });
    try {
      const payload = await requestJson<TrustSummaryResponse>("/api/research-os/trust/summary");
      setTrustStatus({ state: "ready", value: payload });
    } catch (exc) {
      setTrustStatus({ state: "error", message: (exc as Error).message });
    }
  }

  function useTrustGate(gate: TrustReleaseGateSummary) {
    setTrustReleaseRef(gate.release_ref);
    setTrustReleaseApprovalDraft((current) => ({
      ...current,
      release_ref: gate.release_ref,
      release_gate_ref: gate.release_ref,
    }));
    setError(null);
  }

  function useTrustPressureRun(run: TrustPressureRunSummary) {
    setTrustReleaseRef(run.release_ref);
    setTrustReleaseApprovalDraft((current) => ({
      ...current,
      release_ref: run.release_ref,
      release_gate_ref: run.release_gate_ref,
      pressure_run_ref: run.runner_ref,
    }));
    setError(null);
  }

  function useTrustReleaseApproval(approval: TrustReleaseApprovalSummary) {
    setTrustReleaseRef(approval.release_ref);
    setTrustReleaseApprovalRef(approval.approval_ref);
    setError(null);
  }

  function useTrustExpertReview(review: TrustExpertReviewSummary) {
    setTrustReleaseApprovalDraft((current) => ({
      ...current,
      release_ref: review.release_ref,
      expert_review_ref: review.review_ref,
      artifact_ref: review.artifact_ref || current.artifact_ref,
    }));
    setError(null);
  }

  function useTrustCheck(check: TrustReleaseCheckSummary) {
    const field = trustReleaseCheckKinds.find((item) => item.kind === check.check_kind)?.gateField;
    if (!field) return;
    setTrustReleaseGateDraft((current) => {
      const base = current.release_ref && current.release_ref !== check.release_ref ? emptyTrustReleaseGateDraft : current;
      return { ...base, release_ref: check.release_ref, [field]: check.check_ref };
    });
    setTrustReleaseRef(check.release_ref);
    setError(null);
  }

  async function recordTrustCheck() {
    const nextCheck = {
      release_ref: trustReleaseCheckDraft.release_ref.trim(),
      check_kind: trustReleaseCheckDraft.check_kind,
      scenario_ref: trustReleaseCheckDraft.scenario_ref.trim(),
      expected_behavior_ref: trustReleaseCheckDraft.expected_behavior_ref.trim(),
      observed_behavior_ref: trustReleaseCheckDraft.observed_behavior_ref.trim(),
      verdict: trustReleaseCheckDraft.verdict.trim() || "passed",
      check_ref: trustReleaseCheckDraft.check_ref.trim(),
      evidence_refs: splitRefs(trustReleaseCheckDraft.evidence_refs),
      validation_result_refs: splitRefs(trustReleaseCheckDraft.validation_result_refs),
    };
    for (const field of [
      "release_ref",
      "scenario_ref",
      "expected_behavior_ref",
      "observed_behavior_ref",
      "verdict",
    ] as const) {
      if (!nextCheck[field]) {
        setError(`trust release check field required: ${field}`);
        return;
      }
    }
    if (nextCheck.evidence_refs.length === 0) {
      setError("trust release check field required: evidence_refs");
      return;
    }
    if (nextCheck.validation_result_refs.length === 0) {
      setError("trust release check field required: validation_result_refs");
      return;
    }
    const payload: Record<string, unknown> = {
      release_ref: nextCheck.release_ref,
      check_kind: nextCheck.check_kind,
      scenario_ref: nextCheck.scenario_ref,
      expected_behavior_ref: nextCheck.expected_behavior_ref,
      observed_behavior_ref: nextCheck.observed_behavior_ref,
      verdict: nextCheck.verdict,
      evidence_refs: nextCheck.evidence_refs,
      validation_result_refs: nextCheck.validation_result_refs,
    };
    if (nextCheck.check_ref) payload.check_ref = nextCheck.check_ref;
    setBusy("trust check");
    setError(null);
    try {
      const result = await requestJson<TrustReleaseCheckRecordResponse>("/api/research-os/trust/release_checks", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      useTrustCheck(result);
      setTrustReleaseCheckDraft({
        ...emptyTrustReleaseCheckDraft,
        release_ref: result.release_ref,
        check_kind: nextCheck.check_kind,
      });
      await refreshTrustSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordTrustSuite() {
    const releaseRef = trustReleaseSuiteDraft.release_ref.trim();
    if (!releaseRef) {
      setError("trust release suite field required: release_ref");
      return;
    }
    let checks: unknown;
    try {
      checks = JSON.parse(trustReleaseSuiteDraft.checks_json);
    } catch {
      setError("trust release suite checks JSON invalid");
      return;
    }
    if (!Array.isArray(checks)) {
      setError("trust release suite checks JSON must be an array");
      return;
    }
    setBusy("trust suite");
    setError(null);
    try {
      const result = await requestJson<TrustReleaseCheckSuiteResponse>(
        "/api/research-os/trust/release_check_suites",
        {
          method: "POST",
          body: JSON.stringify({ release_ref: releaseRef, checks }),
        },
      );
      setTrustReleaseRef(result.release_ref);
      setTrustReleaseGateDraft(result.release_gate);
      setTrustReleaseCheckDraft({
        ...emptyTrustReleaseCheckDraft,
        release_ref: result.release_ref,
      });
      setTrustReleaseSuiteDraft({
        ...emptyTrustReleaseSuiteDraft,
        release_ref: result.release_ref,
      });
      await refreshTrustSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordTrustPressureRun() {
    const releaseRef = trustPressureRunDraft.release_ref.trim();
    if (!releaseRef) {
      setError("trust pressure run field required: release_ref");
      return;
    }
    const evidenceRefs = splitRefs(trustPressureRunDraft.evidence_refs);
    const validationResultRefs = splitRefs(trustPressureRunDraft.validation_result_refs);
    if (evidenceRefs.length === 0) {
      setError("trust pressure run field required: evidence_refs");
      return;
    }
    if (validationResultRefs.length === 0) {
      setError("trust pressure run field required: validation_result_refs");
      return;
    }
    let scenarios: unknown;
    try {
      scenarios = JSON.parse(trustPressureRunDraft.scenarios_json);
    } catch {
      setError("trust pressure run scenarios JSON invalid");
      return;
    }
    if (!Array.isArray(scenarios)) {
      setError("trust pressure run scenarios JSON must be an array");
      return;
    }
    setBusy("trust pressure run");
    setError(null);
    try {
      const result = await requestJson<TrustPressureRunResponse>("/api/research-os/trust/pressure_runs", {
        method: "POST",
        body: JSON.stringify({
          release_ref: releaseRef,
          runner_mode: trustPressureRunDraft.runner_mode,
          evidence_refs: evidenceRefs,
          validation_result_refs: validationResultRefs,
          scenarios,
        }),
      });
      setTrustReleaseRef(result.release_ref);
      setTrustReleaseGateDraft(result.release_gate);
      setTrustReleaseCheckDraft({
        ...emptyTrustReleaseCheckDraft,
        release_ref: result.release_ref,
      });
      setTrustReleaseSuiteDraft({
        ...emptyTrustReleaseSuiteDraft,
        release_ref: result.release_ref,
      });
      setTrustPressureRunDraft({
        ...emptyTrustPressureRunDraft,
        release_ref: result.release_ref,
      });
      await refreshTrustSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordTrustReleaseApproval() {
    const payload = {
      release_ref: trustReleaseApprovalDraft.release_ref.trim(),
      release_gate_ref: trustReleaseApprovalDraft.release_gate_ref.trim(),
      pressure_run_ref: trustReleaseApprovalDraft.pressure_run_ref.trim(),
      expert_review_ref: trustReleaseApprovalDraft.expert_review_ref.trim(),
      artifact_ref: trustReleaseApprovalDraft.artifact_ref.trim(),
      approval_protocol_ref: trustReleaseApprovalDraft.approval_protocol_ref.trim(),
      verdict: trustReleaseApprovalDraft.verdict.trim() || "approved",
      evidence_refs: splitRefs(trustReleaseApprovalDraft.evidence_refs),
      signed_approval_ref: trustReleaseApprovalDraft.signed_approval_ref.trim(),
      residual_blocker_refs: splitRefs(trustReleaseApprovalDraft.residual_blocker_refs),
    };
    for (const field of [
      "release_ref",
      "release_gate_ref",
      "pressure_run_ref",
      "expert_review_ref",
      "artifact_ref",
      "approval_protocol_ref",
      "verdict",
    ] as const) {
      if (!payload[field]) {
        setError(`trust release approval field required: ${field}`);
        return;
      }
    }
    if (payload.evidence_refs.length === 0) {
      setError("trust release approval field required: evidence_refs");
      return;
    }
    if (payload.verdict === "approved" && !payload.signed_approval_ref) {
      setError("trust release approval field required: signed_approval_ref");
      return;
    }
    if (payload.verdict !== "approved" && payload.residual_blocker_refs.length === 0) {
      setError("trust release approval field required: residual_blocker_refs");
      return;
    }
    setBusy("trust release approval");
    setError(null);
    try {
      const result = await requestJson<TrustReleaseApprovalResponse>(
        "/api/research-os/trust/release_approvals",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setTrustReleaseRef(result.release_ref);
      setTrustReleaseApprovalRef(result.approval_ref);
      setTrustReleaseApprovalDraft({
        ...emptyTrustReleaseApprovalDraft,
        release_ref: result.release_ref,
        release_gate_ref: result.release_approval.release_gate_ref,
        pressure_run_ref: result.release_approval.pressure_run_ref,
        expert_review_ref: result.release_approval.expert_review_ref,
        artifact_ref: result.release_approval.artifact_ref,
      });
      await refreshTrustSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordTrustGate() {
    const nextGate: TrustReleaseGateSummary = {
      release_ref: trustReleaseGateDraft.release_ref.trim(),
      anti_flattery_pressure_test_ref: trustReleaseGateDraft.anti_flattery_pressure_test_ref.trim(),
      multi_turn_pressure_test_ref: trustReleaseGateDraft.multi_turn_pressure_test_ref.trim(),
      expert_veto_ref: trustReleaseGateDraft.expert_veto_ref.trim(),
      weakness_collapse_check_ref: trustReleaseGateDraft.weakness_collapse_check_ref.trim(),
      mock_honesty_check_ref: trustReleaseGateDraft.mock_honesty_check_ref.trim(),
      cold_start_honesty_check_ref: trustReleaseGateDraft.cold_start_honesty_check_ref.trim(),
    };
    const missing = trustReleaseGateFields.find(({ key }) => !nextGate[key]);
    if (missing) {
      setError(`trust release gate field required: ${missing.key}`);
      return;
    }
    setBusy("trust gate");
    setError(null);
    try {
      const result = await requestJson<TrustReleaseGateRecordResponse>("/api/research-os/trust/release_gates", {
        method: "POST",
        body: JSON.stringify({ release_gate: nextGate }),
      });
      setTrustReleaseRef(result.release_ref);
      setTrustReleaseGateDraft(emptyTrustReleaseGateDraft);
      await refreshTrustSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function materialize() {
    if (!manifest) return;
    setBusy("materialize");
    setError(null);
    try {
      const result = await requestJson<MaterializeResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/materialize`,
        { method: "POST", body: JSON.stringify({}) },
      );
      setMaterialized(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function bundleSources() {
    if (!manifest) return;
    const guard = sourceMapIsSafe(sourceMap, sourceRefs);
    if (guard) {
      setError(guard);
      return;
    }
    setBusy("bundle");
    setError(null);
    try {
      const result = await requestJson<BundleResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/bundle_sources`,
        { method: "POST", body: JSON.stringify({ source_map: sourceMap }) },
      );
      setBundled(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function attestSourceRun() {
    if (!manifest) return;
    const safeRunId = runId.trim();
    if (!safeRunId) {
      setError("run_id required for source-run attestation");
      return;
    }
    setBusy("attest");
    setError(null);
    try {
      const result = await requestJson<IntegrityResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/source_run_integrity_attestations`,
        {
          method: "POST",
          body: JSON.stringify({
            run_id: safeRunId,
            source_file_ref: selectedSourceRef || undefined,
          }),
        },
      );
      setIntegrity(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function downloadArchive() {
    if (!manifest) return;
    setBusy("archive");
    setError(null);
    try {
      const response = await authFetch(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/archive`,
      );
      if (!response.ok) throw new Error(await readError(response));
      const blob = await response.blob();
      const archiveHash = response.headers.get("x-rdp-archive-sha256") ?? "";
      const fileCount = response.headers.get("x-rdp-archive-file-count") ?? "";
      if (typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${manifest.package_id}.zip`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      }
      setArchive({
        packageId: manifest.package_id,
        archiveHash,
        fileCount,
        downloadedBytes: blob.size,
      });
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function publishLocal() {
    if (!manifest) return;
    const releaseRef = trustReleaseRef.trim();
    if (!releaseRef) {
      setError("trust_release_ref required");
      return;
    }
    const approvalRef = trustReleaseApprovalRef.trim();
    if (!approvalRef) {
      setError("trust_release_approval_ref required");
      return;
    }
    if (sourceRefs.length > 0 && !integrity) {
      setError("source-run integrity required before publish");
      return;
    }
    setBusy("publish");
    setError(null);
    try {
      const result = await requestJson<PublishResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/publish`,
        {
          method: "POST",
          body: JSON.stringify({
            channel: "local_registry",
            trust_release_ref: releaseRef,
            trust_release_approval_ref: approvalRef,
          }),
        },
      );
      setPublication(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function deploymentAttestationPayload() {
    const deploymentRef = deploymentProofDraft.deployment_ref.trim();
    if (!deploymentRef) {
      setError("deployment_ref required");
      return null;
    }
    return {
      deployment_ref: deploymentRef,
      source_bundle_required: sourceRefs.length > 0,
    };
  }

  async function recordDeploymentAttestation() {
    if (!manifest) return;
    const body = deploymentAttestationPayload();
    if (!body) return;
    setBusy("deployment attestation");
    setError(null);
    try {
      const result = await requestJson<DeploymentAttestationResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/deployment_attestations`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      setDeploymentAttestation(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runDeploymentAttestation() {
    if (!manifest) return;
    const body = deploymentAttestationPayload();
    if (!body) return;
    setBusy("deployment runner");
    setError(null);
    try {
      const result = await requestJson<DeploymentAttestationResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/deployment_attestations/run`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      setDeploymentAttestation(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function deploymentHealthPayload() {
    if (!deploymentAttestation) {
      setError("deployment attestation required before health proof");
      return null;
    }
    const healthCheckRefs = splitRefs(deploymentProofDraft.health_check_refs);
    const monitorRefs = splitRefs(deploymentProofDraft.monitor_refs);
    const evidenceRefs = splitRefs(deploymentProofDraft.evidence_refs);
    const requiredFields = [
      "health_status",
      "rollback_plan_ref",
      "rollback_readiness_ref",
      "rollback_drill_ref",
      "retire_plan_ref",
    ] as const;
    for (const field of requiredFields) {
      if (!deploymentProofDraft[field].trim()) {
        setError(`deployment health field required: ${field}`);
        return null;
      }
    }
    if (healthCheckRefs.length === 0) {
      setError("deployment health field required: health_check_refs");
      return null;
    }
    if (monitorRefs.length === 0) {
      setError("deployment health field required: monitor_refs");
      return null;
    }
    if (evidenceRefs.length === 0) {
      setError("deployment health field required: evidence_refs");
      return null;
    }
    return {
      deployment_attestation_hash: deploymentAttestation.attestation_hash,
      deployment_ref: deploymentProofDraft.deployment_ref.trim() || deploymentAttestation.deployment_ref,
      health_status: deploymentProofDraft.health_status.trim(),
      health_check_refs: healthCheckRefs,
      monitor_refs: monitorRefs,
      rollback_plan_ref: deploymentProofDraft.rollback_plan_ref.trim(),
      rollback_readiness_ref: deploymentProofDraft.rollback_readiness_ref.trim(),
      rollback_drill_ref: deploymentProofDraft.rollback_drill_ref.trim(),
      retire_plan_ref: deploymentProofDraft.retire_plan_ref.trim(),
      evidence_refs: evidenceRefs,
    };
  }

  async function recordDeploymentHealthProof() {
    if (!manifest) return;
    const body = deploymentHealthPayload();
    if (!body) return;
    setBusy("deployment health proof");
    setError(null);
    try {
      const result = await requestJson<DeploymentHealthCheckResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/deployment_health_checks`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      setDeploymentHealthCheck(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordExternalPublication() {
    if (!manifest) return;
    if (!publication) {
      setError("local publication required before external proof");
      return;
    }
    const releaseRef = trustReleaseRef.trim() || publication.trust_release_ref;
    const approvalRef = trustReleaseApprovalRef.trim() || publication.trust_release_approval_ref;
    const evidenceRefs = splitRefs(externalPublicationDraft.evidence_refs);
    if (!externalPublicationDraft.external_uri.trim()) {
      setError("external_uri required");
      return;
    }
    if (!externalPublicationDraft.immutable_pointer_ref.trim()) {
      setError("immutable_pointer_ref required");
      return;
    }
    if (!externalPublicationDraft.destination_allowlist_ref.trim()) {
      setError("destination_allowlist_ref required");
      return;
    }
    if (evidenceRefs.length === 0) {
      setError("external evidence_refs required");
      return;
    }
    setBusy("external publication proof");
    setError(null);
    try {
      const result = await requestJson<ExternalPublicationProofResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/external_publications`,
        {
          method: "POST",
          body: JSON.stringify({
            external_channel: externalPublicationDraft.external_channel,
            external_uri: externalPublicationDraft.external_uri,
            immutable_pointer_ref: externalPublicationDraft.immutable_pointer_ref,
            destination_allowlist_ref: externalPublicationDraft.destination_allowlist_ref,
            local_publish_hash: publication.publish_hash,
            archive_sha256: publication.archive_sha256,
            trust_release_ref: releaseRef,
            trust_release_approval_ref: approvalRef,
            evidence_refs: evidenceRefs,
          }),
        },
      );
      setExternalPublication(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runExternalPublication() {
    if (!manifest) return;
    if (!publication) {
      setError("local publication required before external publish runner");
      return;
    }
    const releaseRef = trustReleaseRef.trim() || publication.trust_release_ref;
    const approvalRef = trustReleaseApprovalRef.trim() || publication.trust_release_approval_ref;
    const evidenceRefs = splitRefs(externalPublicationDraft.evidence_refs);
    if (!externalPublicationDraft.destination_allowlist_ref.trim()) {
      setError("destination_allowlist_ref required");
      return;
    }
    if (evidenceRefs.length === 0) {
      setError("external evidence_refs required");
      return;
    }
    setBusy("external publication runner");
    setError(null);
    try {
      const result = await requestJson<ExternalPublicationProofResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/external_publications/run`,
        {
          method: "POST",
          body: JSON.stringify({
            external_channel: externalPublicationDraft.external_channel,
            immutable_pointer_ref: externalPublicationDraft.immutable_pointer_ref,
            destination_allowlist_ref: externalPublicationDraft.destination_allowlist_ref,
            local_publish_hash: publication.publish_hash,
            archive_sha256: publication.archive_sha256,
            trust_release_ref: releaseRef,
            trust_release_approval_ref: approvalRef,
            evidence_refs: evidenceRefs,
          }),
        },
      );
      setExternalPublication(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function buildCIReleaseAttestationPayload(mode: "record" | "run") {
    if (!manifest) return null;
    if (!publication) {
      setError("local publication required before CI release attestation");
      return null;
    }
    if (!externalPublication) {
      setError("external publication proof required before CI release attestation");
      return null;
    }
    const requiredCheckRefs = splitRefs(ciReleaseDraft.required_check_refs);
    const evidenceRefs = splitRefs(ciReleaseDraft.evidence_refs);
    const requiredFields =
      mode === "record"
        ? ([
            "ci_system_ref",
            "ci_workflow_ref",
            "ci_run_ref",
            "source_commit_ref",
            "ci_status",
            "artifact_digest",
            "test_report_ref",
            "test_report_hash",
            "build_log_digest",
          ] as const)
        : (["ci_system_ref", "ci_workflow_ref", "source_commit_ref"] as const);
    for (const field of requiredFields) {
      if (!ciReleaseDraft[field].trim()) {
        setError(`CI release attestation field required: ${field}`);
        return null;
      }
    }
    if (requiredCheckRefs.length === 0) {
      setError("CI release attestation field required: required_check_refs");
      return null;
    }
    if (evidenceRefs.length === 0) {
      setError("CI release attestation field required: evidence_refs");
      return null;
    }
    const releaseRef = trustReleaseRef.trim() || publication.trust_release_ref;
    const approvalRef = trustReleaseApprovalRef.trim() || publication.trust_release_approval_ref;
    return {
      local_publish_hash: publication.publish_hash,
      external_proof_hash: externalPublication.proof_hash,
      archive_sha256: publication.archive_sha256,
      trust_release_ref: releaseRef,
      trust_release_approval_ref: approvalRef,
      ci_system_ref: ciReleaseDraft.ci_system_ref.trim(),
      ci_workflow_ref: ciReleaseDraft.ci_workflow_ref.trim(),
      ci_run_ref: ciReleaseDraft.ci_run_ref.trim(),
      source_commit_ref: ciReleaseDraft.source_commit_ref.trim(),
      ci_status: ciReleaseDraft.ci_status.trim(),
      artifact_digest: ciReleaseDraft.artifact_digest.trim(),
      test_report_ref: ciReleaseDraft.test_report_ref.trim(),
      test_report_hash: ciReleaseDraft.test_report_hash.trim(),
      build_log_digest: ciReleaseDraft.build_log_digest.trim(),
      required_check_refs: requiredCheckRefs,
      failed_check_refs: splitRefs(ciReleaseDraft.failed_check_refs),
      skipped_check_refs: splitRefs(ciReleaseDraft.skipped_check_refs),
      missing_check_refs: splitRefs(ciReleaseDraft.missing_check_refs),
      evidence_refs: evidenceRefs,
    };
  }

  async function recordCIReleaseAttestation() {
    if (!manifest) return;
    const body = buildCIReleaseAttestationPayload("record");
    if (!body) return;
    setBusy("CI release attestation");
    setError(null);
    try {
      const result = await requestJson<CIReleaseAttestationResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/ci_release_attestations`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      setCiReleaseAttestation(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runCIReleaseAttestation() {
    if (!manifest) return;
    const body = buildCIReleaseAttestationPayload("run");
    if (!body) return;
    setBusy("CI release runner");
    setError(null);
    try {
      const result = await requestJson<CIReleaseAttestationResponse>(
        `/api/research-os/rdp/manifests/${encodeURIComponent(manifest.package_id)}/ci_release_attestations/run`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      setCiReleaseAttestation(result);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const manifestList = listStatus.state === "ready" ? listStatus.value : [];
  const canAct = Boolean(manifest) && !busy;

  return (
    <div data-testid="rdp-export-panel" style={panelStyle}>
      <section style={sectionStyle}>
        <div style={sectionHeaderStyle}>
          <span>RDP packages</span>
          <div style={{ flex: 1 }} />
          {listStatus.state === "ready" && <Pill tone="info">{manifestList.length}</Pill>}
        </div>
        <div style={sectionBodyStyle}>
          {listStatus.state === "loading" && <p style={mutedTextStyle}>Loading registry...</p>}
          {listStatus.state === "error" && <p role="alert" style={errorTextStyle}>{listStatus.message}</p>}
          {listStatus.state === "ready" && manifestList.length === 0 && (
            <p data-testid="rdp-empty" style={mutedTextStyle}>No recorded RDP manifests.</p>
          )}
          <div style={{ display: "grid", gap: 7 }}>
            {manifestList.map((item) => {
              const active = item.package_id === selectedPackageId;
              return (
                <button
                  key={item.package_id}
                  type="button"
                  data-testid="rdp-package-option"
                  aria-pressed={active}
                  onClick={() => setSelectedPackageId(item.package_id)}
                  style={{
                    textAlign: "left",
                    background: active ? "var(--desk-hover)" : "transparent",
                    border: "1px solid var(--desk-border)",
                    borderRadius: "var(--desk-radius-sm)",
                    padding: 9,
                    cursor: "pointer",
                    color: "var(--desk-text)",
                    fontFamily: "inherit",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <strong style={{ fontSize: 12 }}>{item.package_id}</strong>
                    <Pill tone={item.target_runtime === "live" ? "warning" : "ghost"}>
                      {item.target_runtime}
                    </Pill>
                  </div>
                  <div style={{ marginTop: 5, color: "var(--desk-text-muted)", fontSize: 11, lineHeight: 1.4 }}>
                    {item.research_question}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      <section style={{ ...sectionStyle, minWidth: 0 }}>
        <div style={sectionHeaderStyle}>
          <span>Export desk</span>
          <div style={{ flex: 1 }} />
          <Pill tone="success">Backend</Pill>
        </div>
        <div style={{ ...sectionBodyStyle, display: "grid", gap: 13 }}>
          {detailStatus.state === "idle" && <p style={mutedTextStyle}>Select a package.</p>}
          {detailStatus.state === "loading" && <p style={mutedTextStyle}>Loading manifest...</p>}
          {detailStatus.state === "error" && <p role="alert" style={errorTextStyle}>{detailStatus.message}</p>}
          {manifest && (
            <>
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: "var(--desk-text)", fontSize: 14 }}>{manifest.package_id}</strong>
                  <Pill tone={manifest.target_runtime === "live" ? "warning" : "info"}>{manifest.target_runtime}</Pill>
                  <Pill tone="ghost">{ellipsis(manifest.artifact_hash, 30)}</Pill>
                </div>
                <p style={{ margin: 0, color: "var(--desk-text-muted)", fontSize: 12.5, lineHeight: 1.55 }}>
                  {manifest.research_question}
                </p>
              </div>

              <div style={gridTwoStyle}>
                <Field title="runs"><RefList refs={runRefs} /></Field>
                <Field title="sources"><RefList refs={sourceRefs} /></Field>
                <Field title="datasets"><RefList refs={manifest.dataset_version_refs ?? []} /></Field>
                <Field title="market data use"><RefList refs={manifest.market_data_use_validation_refs ?? []} /></Field>
                <Field title="unverified residuals"><RefList refs={manifest.unverified_residuals ?? []} /></Field>
              </div>

              <div style={{ display: "grid", gap: 9 }}>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <ActionButton testId="rdp-materialize" onClick={materialize} disabled={!canAct} tone="accent">
                    Materialize
                  </ActionButton>
                  <ActionButton testId="rdp-bundle" onClick={bundleSources} disabled={!canAct || sourceRefs.length === 0}>
                    Bundle sources
                  </ActionButton>
                  <ActionButton testId="rdp-attest" onClick={attestSourceRun} disabled={!canAct || runRefs.length === 0}>
                    Attest run
                  </ActionButton>
                  <ActionButton testId="rdp-download" onClick={downloadArchive} disabled={!canAct}>
                    Download zip
                  </ActionButton>
                  <ActionButton testId="rdp-publish" onClick={publishLocal} disabled={!canAct}>
                    Publish local
                  </ActionButton>
                </div>
                {busy && <p style={mutedTextStyle}>Running {busy}...</p>}
                {error && <p data-testid="rdp-error" role="alert" style={errorTextStyle}>{error}</p>}
              </div>

              {sourceRefs.length > 0 && (
                <div style={{ display: "grid", gap: 8 }}>
                  <div style={{ color: "var(--desk-text)", fontSize: 12, fontWeight: 700 }}>source_map</div>
                  {sourceRefs.map((ref) => (
                    <label key={ref} style={labelStyle}>
                      <span>{ref}</span>
                      <input
                        data-testid={`rdp-source-map-${ref}`}
                        value={sourceMap[ref] ?? ""}
                        onChange={(event) =>
                          setSourceMap((current) => ({ ...current, [ref]: event.target.value }))
                        }
                        style={inputStyle}
                      />
                    </label>
                  ))}
                </div>
              )}

              <div style={gridTwoStyle}>
                <label style={labelStyle}>
                  <span>run_id</span>
                  <input
                    data-testid="rdp-run-id"
                    value={runId}
                    onChange={(event) => setRunId(event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  <span>source_file_ref</span>
                  <select
                    data-testid="rdp-source-ref"
                    value={selectedSourceRef}
                    onChange={(event) => setSelectedSourceRef(event.target.value)}
                    style={inputStyle}
                  >
                    {sourceRefs.map((ref) => (
                      <option key={ref} value={ref}>{ref}</option>
                    ))}
                  </select>
                </label>
                <label style={labelStyle}>
                  <span>trust_release_ref</span>
                  <input
                    data-testid="rdp-trust-release-ref"
                    value={trustReleaseRef}
                    onChange={(event) => setTrustReleaseRef(event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  <span>trust_release_approval_ref</span>
                  <input
                    data-testid="rdp-trust-release-approval-ref"
                    value={trustReleaseApprovalRef}
                    onChange={(event) => setTrustReleaseApprovalRef(event.target.value)}
                    style={inputStyle}
                  />
                </label>
              </div>

              <div style={{ display: "grid", gap: 9, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>deployment proof</strong>
                <div style={gridTwoStyle}>
                  <label style={labelStyle}>
                    <span>deployment_ref</span>
                    <input
                      data-testid="rdp-deployment-ref"
                      value={deploymentProofDraft.deployment_ref}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          deployment_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>health_status</span>
                    <input
                      data-testid="rdp-deployment-health-status"
                      value={deploymentProofDraft.health_status}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          health_status: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>health_check_refs</span>
                    <input
                      data-testid="rdp-deployment-health-check-refs"
                      value={deploymentProofDraft.health_check_refs}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          health_check_refs: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>monitor_refs</span>
                    <input
                      data-testid="rdp-deployment-monitor-refs"
                      value={deploymentProofDraft.monitor_refs}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          monitor_refs: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>rollback_plan_ref</span>
                    <input
                      data-testid="rdp-deployment-rollback-plan-ref"
                      value={deploymentProofDraft.rollback_plan_ref}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          rollback_plan_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>rollback_readiness_ref</span>
                    <input
                      data-testid="rdp-deployment-rollback-readiness-ref"
                      value={deploymentProofDraft.rollback_readiness_ref}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          rollback_readiness_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>rollback_drill_ref</span>
                    <input
                      data-testid="rdp-deployment-rollback-drill-ref"
                      value={deploymentProofDraft.rollback_drill_ref}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          rollback_drill_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>retire_plan_ref</span>
                    <input
                      data-testid="rdp-deployment-retire-plan-ref"
                      value={deploymentProofDraft.retire_plan_ref}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          retire_plan_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={{ ...labelStyle, gridColumn: "1 / -1" }}>
                    <span>deployment evidence_refs</span>
                    <input
                      data-testid="rdp-deployment-evidence-refs"
                      value={deploymentProofDraft.evidence_refs}
                      onChange={(event) =>
                        setDeploymentProofDraft((current) => ({
                          ...current,
                          evidence_refs: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  <ActionButton testId="rdp-deployment-attest" onClick={recordDeploymentAttestation} disabled={!canAct}>
                    Record deployment
                  </ActionButton>
                  <ActionButton testId="rdp-deployment-run" onClick={runDeploymentAttestation} disabled={!canAct}>
                    Run deployment
                  </ActionButton>
                  <ActionButton testId="rdp-deployment-health" onClick={recordDeploymentHealthProof} disabled={!canAct}>
                    Record health proof
                  </ActionButton>
                </div>
              </div>

              <div style={{ display: "grid", gap: 9, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>external publication proof</strong>
                <div style={gridTwoStyle}>
                  <label style={labelStyle}>
                    <span>external_channel</span>
                    <select
                      data-testid="rdp-external-channel"
                      value={externalPublicationDraft.external_channel}
                      onChange={(event) =>
                        setExternalPublicationDraft((current) => ({
                          ...current,
                          external_channel: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    >
                      <option value="object_store">object_store</option>
                      <option value="release_registry">release_registry</option>
                      <option value="artifact_registry">artifact_registry</option>
                    </select>
                  </label>
                  <label style={labelStyle}>
                    <span>external_uri</span>
                    <input
                      data-testid="rdp-external-uri"
                      value={externalPublicationDraft.external_uri}
                      onChange={(event) =>
                        setExternalPublicationDraft((current) => ({
                          ...current,
                          external_uri: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>immutable_pointer_ref</span>
                    <input
                      data-testid="rdp-external-immutable-pointer-ref"
                      value={externalPublicationDraft.immutable_pointer_ref}
                      onChange={(event) =>
                        setExternalPublicationDraft((current) => ({
                          ...current,
                          immutable_pointer_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>destination_allowlist_ref</span>
                    <input
                      data-testid="rdp-external-destination-allowlist-ref"
                      value={externalPublicationDraft.destination_allowlist_ref}
                      onChange={(event) =>
                        setExternalPublicationDraft((current) => ({
                          ...current,
                          destination_allowlist_ref: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={{ ...labelStyle, gridColumn: "1 / -1" }}>
                    <span>external evidence_refs</span>
                    <input
                      data-testid="rdp-external-evidence-refs"
                      value={externalPublicationDraft.evidence_refs}
                      onChange={(event) =>
                        setExternalPublicationDraft((current) => ({
                          ...current,
                          evidence_refs: event.target.value,
                        }))
                      }
                      style={inputStyle}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  <ActionButton testId="rdp-external-publish" onClick={recordExternalPublication} disabled={!canAct}>
                    Record external proof
                  </ActionButton>
                  <ActionButton testId="rdp-external-publish-run" onClick={runExternalPublication} disabled={!canAct}>
                    Run external publish
                  </ActionButton>
                </div>
              </div>

              <div style={{ display: "grid", gap: 9, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>CI release attestation</strong>
                <div style={gridTwoStyle}>
                  <label style={labelStyle}>
                    <span>ci_system_ref</span>
                    <input
                      data-testid="rdp-ci-system-ref"
                      value={ciReleaseDraft.ci_system_ref}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, ci_system_ref: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>ci_workflow_ref</span>
                    <input
                      data-testid="rdp-ci-workflow-ref"
                      value={ciReleaseDraft.ci_workflow_ref}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, ci_workflow_ref: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>ci_run_ref</span>
                    <input
                      data-testid="rdp-ci-run-ref"
                      value={ciReleaseDraft.ci_run_ref}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, ci_run_ref: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>source_commit_ref</span>
                    <input
                      data-testid="rdp-ci-source-commit-ref"
                      value={ciReleaseDraft.source_commit_ref}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, source_commit_ref: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>ci_status</span>
                    <input
                      data-testid="rdp-ci-status"
                      value={ciReleaseDraft.ci_status}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, ci_status: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>artifact_digest</span>
                    <input
                      data-testid="rdp-ci-artifact-digest"
                      value={ciReleaseDraft.artifact_digest}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, artifact_digest: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>test_report_ref</span>
                    <input
                      data-testid="rdp-ci-test-report-ref"
                      value={ciReleaseDraft.test_report_ref}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, test_report_ref: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>test_report_hash</span>
                    <input
                      data-testid="rdp-ci-test-report-hash"
                      value={ciReleaseDraft.test_report_hash}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, test_report_hash: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>build_log_digest</span>
                    <input
                      data-testid="rdp-ci-build-log-digest"
                      value={ciReleaseDraft.build_log_digest}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, build_log_digest: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>required_check_refs</span>
                    <input
                      data-testid="rdp-ci-required-check-refs"
                      value={ciReleaseDraft.required_check_refs}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, required_check_refs: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>failed_check_refs</span>
                    <input
                      data-testid="rdp-ci-failed-check-refs"
                      value={ciReleaseDraft.failed_check_refs}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, failed_check_refs: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>skipped_check_refs</span>
                    <input
                      data-testid="rdp-ci-skipped-check-refs"
                      value={ciReleaseDraft.skipped_check_refs}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, skipped_check_refs: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>missing_check_refs</span>
                    <input
                      data-testid="rdp-ci-missing-check-refs"
                      value={ciReleaseDraft.missing_check_refs}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, missing_check_refs: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={labelStyle}>
                    <span>ci evidence_refs</span>
                    <input
                      data-testid="rdp-ci-evidence-refs"
                      value={ciReleaseDraft.evidence_refs}
                      onChange={(event) =>
                        setCiReleaseDraft((current) => ({ ...current, evidence_refs: event.target.value }))
                      }
                      style={inputStyle}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <ActionButton testId="rdp-ci-release-attest" onClick={recordCIReleaseAttestation} disabled={!canAct}>
                    Record CI attestation
                  </ActionButton>
                  <ActionButton testId="rdp-ci-release-run" onClick={runCIReleaseAttestation} disabled={!canAct}>
                    Run CI
                  </ActionButton>
                </div>
              </div>

              <div style={{ display: "grid", gap: 10, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>trust release gates</strong>
                  {trustStatus.state === "ready" && (
                    <Pill tone="info" title="release_gate_total">
                      {trustStatus.value.release_gate_total}
                    </Pill>
                  )}
                  {trustStatus.state === "ready" && (
                    <Pill tone="ghost" title="release_check_total">
                      checks {trustStatus.value.release_check_total ?? trustReleaseChecks.length}
                    </Pill>
                  )}
                  {trustStatus.state === "ready" && (
                    <Pill tone="ghost" title="pressure_run_total">
                      runs {trustStatus.value.pressure_run_total ?? trustPressureRuns.length}
                    </Pill>
                  )}
                  {trustStatus.state === "ready" && (
                    <Pill tone="ghost" title="release_approval_total">
                      approvals {trustStatus.value.release_approval_total ?? trustReleaseApprovals.length}
                    </Pill>
                  )}
                  <div style={{ flex: 1 }} />
                  <ActionButton
                    testId="rdp-refresh-trust-gates"
                    onClick={refreshTrustSummary}
                    disabled={Boolean(busy)}
                  >
                    Refresh
                  </ActionButton>
                </div>
                {trustStatus.state === "loading" && <p style={mutedTextStyle}>Loading trust gates...</p>}
                {trustStatus.state === "error" && (
                  <p data-testid="rdp-trust-gate-error" role="alert" style={errorTextStyle}>
                    {trustStatus.message}
                  </p>
                )}
                {trustStatus.state === "ready" && trustReleaseGates.length === 0 && (
                  <p data-testid="rdp-trust-gates-empty" style={mutedTextStyle}>
                    No trust release gates.
                  </p>
                )}
                {trustReleaseGates.length > 0 && (
                  <div style={{ display: "grid", gap: 0 }}>
                    {trustReleaseGates.map((gate) => (
                      <div
                        key={gate.release_ref}
                        data-testid="rdp-trust-gate-option"
                        style={{
                          display: "grid",
                          gridTemplateColumns: "minmax(0, 1fr) auto",
                          gap: 10,
                          padding: "8px 0",
                          borderBottom: "1px solid var(--desk-border)",
                        }}
                      >
                        <div style={{ display: "grid", gap: 6, minWidth: 0 }}>
                          <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>{gate.release_ref}</strong>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                            {trustReleaseGateFields.slice(1).map(({ key }) => (
                              <Pill key={key} tone="ghost" title={gate[key]}>
                                {ellipsis(gate[key], 24)}
                              </Pill>
                            ))}
                          </div>
                        </div>
                        <ActionButton
                          testId={`rdp-use-trust-gate-${gate.release_ref}`}
                          onClick={() => useTrustGate(gate)}
                          disabled={Boolean(busy)}
                        >
                          Use
                        </ActionButton>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                  <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>release approvals</strong>
                  {trustStatus.state === "ready" && trustReleaseApprovals.length === 0 && (
                    <p data-testid="rdp-trust-release-approvals-empty" style={mutedTextStyle}>
                      No trust release approvals.
                    </p>
                  )}
                  {trustReleaseApprovals.length > 0 && (
                    <div style={{ display: "grid", gap: 0 }}>
                      {trustReleaseApprovals.map((approval) => (
                        <div
                          key={approval.approval_ref}
                          data-testid="rdp-trust-release-approval-option"
                          style={{
                            display: "grid",
                            gridTemplateColumns: "minmax(0, 1fr) auto",
                            gap: 10,
                            padding: "8px 0",
                            borderBottom: "1px solid var(--desk-border)",
                          }}
                        >
                          <div style={{ display: "grid", gap: 5, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                              <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>
                                {ellipsis(approval.approval_ref, 34)}
                              </strong>
                              <Pill tone={approval.verdict === "approved" ? "success" : "warning"}>
                                {approval.verdict}
                              </Pill>
                            </div>
                            <div style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>
                              {approval.release_ref} · {ellipsis(approval.pressure_run_ref, 38)}
                            </div>
                          </div>
                          <ActionButton
                            testId={`rdp-use-trust-release-approval-${approval.approval_ref}`}
                            onClick={() => useTrustReleaseApproval(approval)}
                            disabled={Boolean(busy)}
                          >
                            Use release
                          </ActionButton>
                        </div>
                      ))}
                    </div>
                  )}
                  {trustExpertReviews.length > 0 && (
                    <div style={{ display: "grid", gap: 6 }}>
                      <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>expert review refs</span>
                      <div style={{ display: "grid", gap: 0 }}>
                        {trustExpertReviews.map((review) => (
                          <div
                            key={review.review_ref}
                            data-testid="rdp-trust-expert-review-option"
                            style={{
                              display: "grid",
                              gridTemplateColumns: "minmax(0, 1fr) auto",
                              gap: 10,
                              padding: "7px 0",
                              borderBottom: "1px solid var(--desk-border)",
                            }}
                          >
                            <div style={{ display: "grid", gap: 4, minWidth: 0 }}>
                              <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>
                                {ellipsis(review.review_ref, 34)}
                              </strong>
                              <span style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>
                                {review.release_ref} · {review.verdict}
                              </span>
                            </div>
                            <ActionButton
                              testId={`rdp-use-trust-expert-review-${review.review_ref}`}
                              onClick={() => useTrustExpertReview(review)}
                              disabled={Boolean(busy)}
                            >
                              Use review
                            </ActionButton>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div style={gridTwoStyle}>
                    <label style={labelStyle}>
                      <span>approval release_ref</span>
                      <input
                        data-testid="rdp-trust-approval-release_ref"
                        value={trustReleaseApprovalDraft.release_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            release_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>release_gate_ref</span>
                      <input
                        data-testid="rdp-trust-approval-release_gate_ref"
                        value={trustReleaseApprovalDraft.release_gate_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            release_gate_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>pressure_run_ref</span>
                      <input
                        data-testid="rdp-trust-approval-pressure_run_ref"
                        value={trustReleaseApprovalDraft.pressure_run_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            pressure_run_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>expert_review_ref</span>
                      <input
                        data-testid="rdp-trust-approval-expert_review_ref"
                        value={trustReleaseApprovalDraft.expert_review_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            expert_review_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>artifact_ref</span>
                      <input
                        data-testid="rdp-trust-approval-artifact_ref"
                        value={trustReleaseApprovalDraft.artifact_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            artifact_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>approval_protocol_ref</span>
                      <input
                        data-testid="rdp-trust-approval-protocol_ref"
                        value={trustReleaseApprovalDraft.approval_protocol_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            approval_protocol_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>verdict</span>
                      <select
                        data-testid="rdp-trust-approval-verdict"
                        value={trustReleaseApprovalDraft.verdict}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            verdict: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      >
                        <option value="approved">approved</option>
                        <option value="needs_revision">needs_revision</option>
                        <option value="blocked">blocked</option>
                      </select>
                    </label>
                    <label style={labelStyle}>
                      <span>signed_approval_ref</span>
                      <input
                        data-testid="rdp-trust-approval-signed_ref"
                        value={trustReleaseApprovalDraft.signed_approval_ref}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            signed_approval_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>approval evidence_refs</span>
                      <textarea
                        data-testid="rdp-trust-approval-evidence_refs"
                        value={trustReleaseApprovalDraft.evidence_refs}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            evidence_refs: event.target.value,
                          }))
                        }
                        style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>residual_blocker_refs</span>
                      <textarea
                        data-testid="rdp-trust-approval-blocker_refs"
                        value={trustReleaseApprovalDraft.residual_blocker_refs}
                        onChange={(event) =>
                          setTrustReleaseApprovalDraft((current) => ({
                            ...current,
                            residual_blocker_refs: event.target.value,
                          }))
                        }
                        style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
                      />
                    </label>
                  </div>
                  <div>
                    <ActionButton
                      testId="rdp-create-trust-release-approval"
                      onClick={recordTrustReleaseApproval}
                      disabled={Boolean(busy)}
                      tone="accent"
                    >
                      Record approval
                    </ActionButton>
                  </div>
                </div>
                <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                  <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>release checks</strong>
                  {trustStatus.state === "ready" && trustReleaseChecks.length === 0 && (
                    <p data-testid="rdp-trust-checks-empty" style={mutedTextStyle}>
                      No trust release checks.
                    </p>
                  )}
                  {trustReleaseChecks.length > 0 && (
                    <div style={{ display: "grid", gap: 0 }}>
                      {trustReleaseChecks.map((check) => (
                        <div
                          key={check.check_ref}
                          data-testid="rdp-trust-check-option"
                          style={{
                            display: "grid",
                            gridTemplateColumns: "minmax(0, 1fr) auto",
                            gap: 10,
                            padding: "8px 0",
                            borderBottom: "1px solid var(--desk-border)",
                          }}
                        >
                          <div style={{ display: "grid", gap: 5, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                              <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>
                                {ellipsis(check.check_ref, 34)}
                              </strong>
                              <Pill tone="ghost">{check.check_kind}</Pill>
                              <Pill tone="success">{check.verdict}</Pill>
                            </div>
                            <div style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>
                              {check.release_ref} · {ellipsis(check.scenario_ref, 42)}
                            </div>
                          </div>
                          <ActionButton
                            testId={`rdp-use-trust-check-${check.check_ref}`}
                            onClick={() => useTrustCheck(check)}
                            disabled={Boolean(busy)}
                          >
                            Use ref
                          </ActionButton>
                        </div>
                      ))}
                    </div>
                  )}
                  <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                    <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>pressure runs</strong>
                    {trustStatus.state === "ready" && trustPressureRuns.length === 0 && (
                      <p data-testid="rdp-trust-pressure-runs-empty" style={mutedTextStyle}>
                        No trust pressure runs.
                      </p>
                    )}
                    {trustPressureRuns.length > 0 && (
                      <div style={{ display: "grid", gap: 0 }}>
                        {trustPressureRuns.map((run) => (
                          <div
                            key={run.runner_ref}
                            data-testid="rdp-trust-pressure-run-option"
                            style={{
                              display: "grid",
                              gridTemplateColumns: "minmax(0, 1fr) auto",
                              gap: 10,
                              padding: "8px 0",
                              borderBottom: "1px solid var(--desk-border)",
                            }}
                          >
                            <div style={{ display: "grid", gap: 5, minWidth: 0 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                                <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>
                                  {ellipsis(run.runner_ref, 34)}
                                </strong>
                                <Pill tone="ghost">{run.runner_mode}</Pill>
                              </div>
                              <div style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>
                                {run.release_ref} · checks {run.check_refs.length}
                              </div>
                            </div>
                            <ActionButton
                              testId={`rdp-use-trust-pressure-run-${run.runner_ref}`}
                              onClick={() => useTrustPressureRun(run)}
                              disabled={Boolean(busy)}
                            >
                              Use release
                            </ActionButton>
                          </div>
                        ))}
                      </div>
                    )}
                    <div style={gridTwoStyle}>
                      <label style={labelStyle}>
                        <span>runner release_ref</span>
                        <input
                          data-testid="rdp-trust-pressure-release_ref"
                          value={trustPressureRunDraft.release_ref}
                          onChange={(event) =>
                            setTrustPressureRunDraft((current) => ({
                              ...current,
                              release_ref: event.target.value,
                            }))
                          }
                          style={inputStyle}
                        />
                      </label>
                      <label style={labelStyle}>
                        <span>runner_mode</span>
                        <select
                          data-testid="rdp-trust-pressure-runner_mode"
                          value={trustPressureRunDraft.runner_mode}
                          onChange={(event) =>
                            setTrustPressureRunDraft((current) => ({
                              ...current,
                              runner_mode: event.target.value,
                            }))
                          }
                          style={inputStyle}
                        >
                          <option value="local_deterministic">local_deterministic</option>
                          <option value="test_harness">test_harness</option>
                        </select>
                      </label>
                      <label style={labelStyle}>
                        <span>runner evidence_refs</span>
                        <textarea
                          data-testid="rdp-trust-pressure-evidence_refs"
                          value={trustPressureRunDraft.evidence_refs}
                          onChange={(event) =>
                            setTrustPressureRunDraft((current) => ({
                              ...current,
                              evidence_refs: event.target.value,
                            }))
                          }
                          style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
                        />
                      </label>
                      <label style={labelStyle}>
                        <span>runner validation_result_refs</span>
                        <textarea
                          data-testid="rdp-trust-pressure-validation_result_refs"
                          value={trustPressureRunDraft.validation_result_refs}
                          onChange={(event) =>
                            setTrustPressureRunDraft((current) => ({
                              ...current,
                              validation_result_refs: event.target.value,
                            }))
                          }
                          style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
                        />
                      </label>
                      <label style={{ ...labelStyle, gridColumn: "1 / -1" }}>
                        <span>scenarios JSON array</span>
                        <textarea
                          data-testid="rdp-trust-pressure-scenarios_json"
                          value={trustPressureRunDraft.scenarios_json}
                          onChange={(event) =>
                            setTrustPressureRunDraft((current) => ({
                              ...current,
                              scenarios_json: event.target.value,
                            }))
                          }
                          style={{
                            ...inputStyle,
                            minHeight: 180,
                            resize: "vertical",
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                          }}
                        />
                      </label>
                    </div>
                    <div>
                      <ActionButton
                        testId="rdp-create-trust-pressure-run"
                        onClick={recordTrustPressureRun}
                        disabled={Boolean(busy)}
                        tone="accent"
                      >
                        Record pressure run
                      </ActionButton>
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--desk-border)", paddingTop: 10 }}>
                    <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>release check suite</strong>
                    <div style={gridTwoStyle}>
                      <label style={labelStyle}>
                        <span>suite release_ref</span>
                        <input
                          data-testid="rdp-trust-suite-release_ref"
                          value={trustReleaseSuiteDraft.release_ref}
                          onChange={(event) =>
                            setTrustReleaseSuiteDraft((current) => ({
                              ...current,
                              release_ref: event.target.value,
                            }))
                          }
                          style={inputStyle}
                        />
                      </label>
                      <label style={{ ...labelStyle, gridColumn: "1 / -1" }}>
                        <span>checks JSON array</span>
                        <textarea
                          data-testid="rdp-trust-suite-checks_json"
                          value={trustReleaseSuiteDraft.checks_json}
                          onChange={(event) =>
                            setTrustReleaseSuiteDraft((current) => ({
                              ...current,
                              checks_json: event.target.value,
                            }))
                          }
                          style={{
                            ...inputStyle,
                            minHeight: 180,
                            resize: "vertical",
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                          }}
                        />
                      </label>
                    </div>
                    <div>
                      <ActionButton
                        testId="rdp-create-trust-check-suite"
                        onClick={recordTrustSuite}
                        disabled={Boolean(busy)}
                        tone="accent"
                      >
                        Record suite
                      </ActionButton>
                    </div>
                  </div>
                  <div style={gridTwoStyle}>
                    <label style={labelStyle}>
                      <span>check release_ref</span>
                      <input
                        data-testid="rdp-trust-check-release_ref"
                        value={trustReleaseCheckDraft.release_ref}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({ ...current, release_ref: event.target.value }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>check_kind</span>
                      <select
                        data-testid="rdp-trust-check-check_kind"
                        value={trustReleaseCheckDraft.check_kind}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({
                            ...current,
                            check_kind: event.target.value as TrustReleaseCheckKind,
                          }))
                        }
                        style={inputStyle}
                      >
                        {trustReleaseCheckKinds.map((item) => (
                          <option key={item.kind} value={item.kind}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label style={labelStyle}>
                      <span>scenario_ref</span>
                      <input
                        data-testid="rdp-trust-check-scenario_ref"
                        value={trustReleaseCheckDraft.scenario_ref}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({ ...current, scenario_ref: event.target.value }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>verdict</span>
                      <input
                        data-testid="rdp-trust-check-verdict"
                        value={trustReleaseCheckDraft.verdict}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({ ...current, verdict: event.target.value }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>expected_behavior_ref</span>
                      <input
                        data-testid="rdp-trust-check-expected_behavior_ref"
                        value={trustReleaseCheckDraft.expected_behavior_ref}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({
                            ...current,
                            expected_behavior_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>observed_behavior_ref</span>
                      <input
                        data-testid="rdp-trust-check-observed_behavior_ref"
                        value={trustReleaseCheckDraft.observed_behavior_ref}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({
                            ...current,
                            observed_behavior_ref: event.target.value,
                          }))
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>evidence_refs</span>
                      <textarea
                        data-testid="rdp-trust-check-evidence_refs"
                        value={trustReleaseCheckDraft.evidence_refs}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({ ...current, evidence_refs: event.target.value }))
                        }
                        style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>validation_result_refs</span>
                      <textarea
                        data-testid="rdp-trust-check-validation_result_refs"
                        value={trustReleaseCheckDraft.validation_result_refs}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({
                            ...current,
                            validation_result_refs: event.target.value,
                          }))
                        }
                        style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
                      />
                    </label>
                    <label style={labelStyle}>
                      <span>check_ref optional</span>
                      <input
                        data-testid="rdp-trust-check-check_ref"
                        value={trustReleaseCheckDraft.check_ref}
                        onChange={(event) =>
                          setTrustReleaseCheckDraft((current) => ({ ...current, check_ref: event.target.value }))
                        }
                        style={inputStyle}
                      />
                    </label>
                  </div>
                  <div>
                    <ActionButton
                      testId="rdp-create-trust-check"
                      onClick={recordTrustCheck}
                      disabled={Boolean(busy)}
                      tone="accent"
                    >
                      Record check
                    </ActionButton>
                  </div>
                </div>
                <div style={gridTwoStyle}>
                  {trustReleaseGateFields.map(({ key, label }) => (
                    <label key={key} style={labelStyle}>
                      <span>{label}</span>
                      <input
                        data-testid={`rdp-trust-gate-${key}`}
                        value={trustReleaseGateDraft[key]}
                        onChange={(event) =>
                          setTrustReleaseGateDraft((current) => ({ ...current, [key]: event.target.value }))
                        }
                        style={inputStyle}
                      />
                    </label>
                  ))}
                </div>
                <div>
                  <ActionButton
                    testId="rdp-create-trust-gate"
                    onClick={recordTrustGate}
                    disabled={Boolean(busy)}
                    tone="accent"
                  >
                    Record gate
                  </ActionButton>
                </div>
              </div>

              <div data-testid="rdp-results" style={{ display: "grid", gap: 5 }}>
                {materialized && (
                  <>
                    <ResultLine label="manifest_hash" value={materialized.manifest_hash} />
                    <ResultLine label="manifest_path" value={materialized.manifest_path} />
                  </>
                )}
                {bundled && (
                  <>
                    <ResultLine label="source_index" value={bundled.source_files_index_path} />
                    <ResultLine label="source_files" value={String(bundled.source_files.length)} />
                  </>
                )}
                {integrity && (
                  <>
                    <ResultLine label="integrity_hash" value={integrity.integrity_hash} />
                    <ResultLine label="run_strategy_sha" value={integrity.run_strategy_sha256} />
                  </>
                )}
                {archive && (
                  <>
                    <ResultLine label="archive_hash" value={archive.archiveHash || "not provided"} />
                    <ResultLine label="archive_files" value={archive.fileCount || "not provided"} />
                    <ResultLine label="downloaded_bytes" value={String(archive.downloadedBytes)} />
                  </>
                )}
                {deploymentAttestation && (
                  <>
                    <ResultLine label="deployment_attestation_hash" value={deploymentAttestation.attestation_hash} />
                    <ResultLine label="deployment_ref" value={deploymentAttestation.deployment_ref} />
                    <ResultLine label="deployment_event_ref" value={deploymentAttestation.deployment_event_ref || "not provided"} />
                    <ResultLine
                      label="deployment_artifact_digest"
                      value={deploymentAttestation.deployment_artifact_digest || "not provided"}
                    />
                  </>
                )}
                {deploymentHealthCheck && (
                  <>
                    <ResultLine label="deployment_health_hash" value={deploymentHealthCheck.proof_hash} />
                    <ResultLine label="deployment_health_status" value={deploymentHealthCheck.health_status} />
                    <ResultLine label="rollback_drill_ref" value={deploymentHealthCheck.rollback_drill_ref} />
                    <ResultLine label="retire_plan_ref" value={deploymentHealthCheck.retire_plan_ref} />
                  </>
                )}
                {publication && (
                  <>
                    <ResultLine label="publish_channel" value={publication.channel} />
                    <ResultLine label="publish_hash" value={publication.publish_hash} />
                    <ResultLine label="trust_release_ref" value={publication.trust_release_ref} />
                    <ResultLine label="trust_release_approval_ref" value={publication.trust_release_approval_ref} />
                    <ResultLine label="published_path" value={publication.published_archive_path} />
                  </>
                )}
                {externalPublication && (
                  <>
                    <ResultLine label="external_channel" value={externalPublication.external_channel} />
                    <ResultLine label="external_proof_hash" value={externalPublication.proof_hash} />
                    <ResultLine label="external_uri_digest" value={externalPublication.external_uri_digest} />
                    <ResultLine label="immutable_pointer_ref" value={externalPublication.immutable_pointer_ref} />
                  </>
                )}
                {ciReleaseAttestation && (
                  <>
                    <ResultLine label="ci_attestation_hash" value={ciReleaseAttestation.attestation_hash} />
                    <ResultLine label="ci_run_ref" value={ciReleaseAttestation.ci_run_ref} />
                    <ResultLine label="ci_status" value={ciReleaseAttestation.ci_status} />
                    <ResultLine label="test_report_hash" value={ciReleaseAttestation.test_report_hash} />
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

function Field({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <div style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>{title}</div>
      {children}
    </div>
  );
}

const gridTwoStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 10,
};

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--desk-text-faint)",
  fontSize: 12,
};

const errorTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--desk-danger)",
  fontSize: 12,
};
