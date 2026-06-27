import { useEffect, useState, type CSSProperties } from "react";
import { Pill } from "../../../components/desk";
import { authFetch } from "../../../lib/auth";

interface TrustClaimSummary {
  claim_ref: string;
  claim_label: string;
  evidence_refs: string[];
  weakness_refs: string[];
  weakness_visible_by_default: boolean;
  cold_start_n?: number | null;
  pressure_context?: string;
  user_waiver_ref?: string | null;
  waiver_weakness_visible_by_default: boolean;
}

interface IndependenceDisclosureSummary {
  disclosure_ref: string;
  mode: string;
  claims_organizational_independence: boolean;
  isolated_validation_ref?: string | null;
  immutable_evidence_ref?: string | null;
  second_confirmation_ref?: string | null;
  alternate_model_verification_ref?: string | null;
  organization_process_ref?: string | null;
}

interface ExternalExpertReviewSummary {
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

interface ExternalReviewerIdentitySummary {
  identity_ref: string;
  reviewer_ref: string;
  identity_provider_ref: string;
  public_key_ref: string;
  public_key_fingerprint: string;
  reviewer_independence_ref: string;
  evidence_refs: string[];
  status: string;
  identity_hash: string;
}

interface ExternalExpertSignatureSummary {
  verified_signature_ref: string;
  attestation_ref: string;
  review_ref: string;
  reviewer_ref: string;
  identity_ref: string;
  public_key_ref: string;
  public_key_fingerprint: string;
  signed_payload_hash: string;
  verification_hash: string;
}

interface UserAutonomySummary {
  choice_ref: string;
  agent_recommendation_ref?: string | null;
  tradeoff_refs: string[];
  alternative_path_refs: string[];
  responsibility_boundary_ref?: string | null;
  user_final_choice_ref?: string | null;
  agent_made_final_choice: boolean;
  system_blocked_after_user_acceptance: boolean;
  redline_refs: string[];
}

interface TrustSummaryResponse {
  user: string;
  trust_claim_total: number;
  trust_claims: TrustClaimSummary[];
  independence_disclosure_total: number;
  independence_disclosures: IndependenceDisclosureSummary[];
  expert_review_total: number;
  expert_reviews: ExternalExpertReviewSummary[];
  expert_identity_total?: number;
  expert_identities?: ExternalReviewerIdentitySummary[];
  expert_signature_total?: number;
  expert_signatures?: ExternalExpertSignatureSummary[];
  user_autonomy_total: number;
  user_autonomy_records: UserAutonomySummary[];
}

type AsyncStatus<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; value: T };

const claimLabels = [
  "candidate_context",
  "prior_assertion",
  "unverified_result",
  "evidence_sufficient",
  "proof_backed",
  "production_ready",
];

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

const sectionStyle: CSSProperties = {
  border: "1px solid var(--desk-border)",
  background: "var(--desk-card)",
  borderRadius: "var(--desk-radius-lg)",
  overflow: "hidden",
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "9px 12px",
  borderBottom: "1px solid var(--desk-border)",
  color: "var(--desk-text)",
  fontSize: 12,
  fontWeight: 700,
};

function splitRefs(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function readError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const detail = await response.json().catch(() => ({}));
    if (typeof detail === "object" && detail && "detail" in detail) return String(detail.detail);
  }
  return (await response.text().catch(() => "")) || `HTTP ${response.status}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(path, init);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
}

function ActionButton({
  children,
  onClick,
  disabled,
  testId,
}: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? "var(--desk-soft-btn)" : "var(--desk-accent)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius-sm)",
        color: disabled ? "var(--desk-text-faint)" : "var(--desk-accent-ink)",
        cursor: disabled ? "not-allowed" : "pointer",
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: 700,
        padding: "7px 10px",
      }}
    >
      {children}
    </button>
  );
}

export function TrustDisclosurePanel() {
  const [status, setStatus] = useState<AsyncStatus<TrustSummaryResponse>>({ state: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [claimDraft, setClaimDraft] = useState({
    claim_ref: "",
    claim_label: "evidence_sufficient",
    evidence_refs: "",
    weakness_refs: "",
    weakness_visible_by_default: true,
    cold_start_n: "",
    pressure_context: "",
    user_waiver_ref: "",
    waiver_weakness_visible_by_default: true,
  });
  const [independenceDraft, setIndependenceDraft] = useState({
    disclosure_ref: "",
    mode: "single_user",
    claims_organizational_independence: false,
    isolated_validation_ref: "",
    immutable_evidence_ref: "",
    second_confirmation_ref: "",
    alternate_model_verification_ref: "",
    organization_process_ref: "",
  });
  const [expertDraft, setExpertDraft] = useState({
    review_ref: "",
    release_ref: "",
    reviewer_ref: "",
    reviewer_independence_ref: "",
    artifact_ref: "",
    review_protocol_ref: "",
    verdict: "approved",
    evidence_refs: "",
    veto_reason_refs: "",
    signed_attestation_ref: "",
  });
  const [expertIdentityDraft, setExpertIdentityDraft] = useState({
    identity_ref: "",
    reviewer_ref: "",
    identity_provider_ref: "",
    public_key_ref: "",
    public_key_pem: "",
    reviewer_independence_ref: "",
    evidence_refs: "",
  });
  const [expertSignatureDraft, setExpertSignatureDraft] = useState({
    review_ref: "",
    identity_ref: "",
    signature_b64: "",
    attestation_ref: "",
  });
  const [autonomyDraft, setAutonomyDraft] = useState({
    choice_ref: "",
    agent_recommendation_ref: "",
    tradeoff_refs: "",
    alternative_path_refs: "",
    responsibility_boundary_ref: "",
    user_final_choice_ref: "",
    agent_made_final_choice: false,
    system_blocked_after_user_acceptance: false,
    redline_refs: "",
  });

  async function refresh() {
    setStatus({ state: "loading" });
    try {
      const payload = await requestJson<TrustSummaryResponse>("/api/research-os/trust/summary");
      setStatus({ state: "ready", value: payload });
    } catch (exc) {
      setStatus({ state: "error", message: (exc as Error).message });
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function recordClaim() {
    const evidenceRefs = splitRefs(claimDraft.evidence_refs);
    const weaknessRefs = splitRefs(claimDraft.weakness_refs);
    if (!claimDraft.claim_ref.trim()) {
      setError("trust claim field required: claim_ref");
      return;
    }
    if (evidenceRefs.length === 0 && ["evidence_sufficient", "proof_backed", "production_ready"].includes(claimDraft.claim_label)) {
      setError("trust claim field required: evidence_refs");
      return;
    }
    setBusy("claim");
    setError(null);
    try {
      await requestJson("/api/research-os/trust/claims", {
        method: "POST",
        body: JSON.stringify({
          trust_claim: {
            claim_ref: claimDraft.claim_ref.trim(),
            claim_label: claimDraft.claim_label,
            evidence_refs: evidenceRefs,
            weakness_refs: weaknessRefs,
            weakness_visible_by_default: claimDraft.weakness_visible_by_default,
            cold_start_n: claimDraft.cold_start_n.trim() ? Number(claimDraft.cold_start_n) : undefined,
            pressure_context: claimDraft.pressure_context.trim(),
            user_waiver_ref: claimDraft.user_waiver_ref.trim() || undefined,
            waiver_weakness_visible_by_default: claimDraft.waiver_weakness_visible_by_default,
          },
        }),
      });
      setClaimDraft((current) => ({ ...current, claim_ref: "", evidence_refs: "", weakness_refs: "" }));
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordIndependence() {
    for (const field of [
      "disclosure_ref",
      "isolated_validation_ref",
      "immutable_evidence_ref",
      "second_confirmation_ref",
      "alternate_model_verification_ref",
    ] as const) {
      if (!independenceDraft[field].trim()) {
        setError(`independence field required: ${field}`);
        return;
      }
    }
    setBusy("independence");
    setError(null);
    try {
      await requestJson("/api/research-os/trust/independence_disclosures", {
        method: "POST",
        body: JSON.stringify({
          independence_disclosure: {
            disclosure_ref: independenceDraft.disclosure_ref.trim(),
            mode: independenceDraft.mode,
            claims_organizational_independence: independenceDraft.claims_organizational_independence,
            isolated_validation_ref: independenceDraft.isolated_validation_ref.trim(),
            immutable_evidence_ref: independenceDraft.immutable_evidence_ref.trim(),
            second_confirmation_ref: independenceDraft.second_confirmation_ref.trim(),
            alternate_model_verification_ref: independenceDraft.alternate_model_verification_ref.trim(),
            organization_process_ref: independenceDraft.organization_process_ref.trim() || undefined,
          },
        }),
      });
      setIndependenceDraft((current) => ({ ...current, disclosure_ref: "" }));
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordAutonomy() {
    const tradeoffRefs = splitRefs(autonomyDraft.tradeoff_refs);
    const alternativePathRefs = splitRefs(autonomyDraft.alternative_path_refs);
    for (const field of [
      "choice_ref",
      "agent_recommendation_ref",
      "responsibility_boundary_ref",
      "user_final_choice_ref",
    ] as const) {
      if (!autonomyDraft[field].trim()) {
        setError(`user autonomy field required: ${field}`);
        return;
      }
    }
    if (tradeoffRefs.length === 0 || alternativePathRefs.length === 0) {
      setError("user autonomy field required: tradeoff_refs and alternative_path_refs");
      return;
    }
    setBusy("autonomy");
    setError(null);
    try {
      await requestJson("/api/research-os/trust/user_autonomy", {
        method: "POST",
        body: JSON.stringify({
          user_autonomy: {
            choice_ref: autonomyDraft.choice_ref.trim(),
            agent_recommendation_ref: autonomyDraft.agent_recommendation_ref.trim(),
            tradeoff_refs: tradeoffRefs,
            alternative_path_refs: alternativePathRefs,
            responsibility_boundary_ref: autonomyDraft.responsibility_boundary_ref.trim(),
            user_final_choice_ref: autonomyDraft.user_final_choice_ref.trim(),
            agent_made_final_choice: autonomyDraft.agent_made_final_choice,
            system_blocked_after_user_acceptance: autonomyDraft.system_blocked_after_user_acceptance,
            redline_refs: splitRefs(autonomyDraft.redline_refs),
          },
        }),
      });
      setAutonomyDraft((current) => ({ ...current, choice_ref: "" }));
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordExpertReview() {
    const evidenceRefs = splitRefs(expertDraft.evidence_refs);
    const vetoReasonRefs = splitRefs(expertDraft.veto_reason_refs);
    for (const field of [
      "release_ref",
      "reviewer_ref",
      "reviewer_independence_ref",
      "artifact_ref",
      "review_protocol_ref",
      "verdict",
    ] as const) {
      if (!expertDraft[field].trim()) {
        setError(`expert review field required: ${field}`);
        return;
      }
    }
    if (evidenceRefs.length === 0) {
      setError("expert review field required: evidence_refs");
      return;
    }
    if (expertDraft.verdict === "approved" && !expertDraft.signed_attestation_ref.trim()) {
      setError("expert review field required: signed_attestation_ref");
      return;
    }
    if (["vetoed", "needs_revision"].includes(expertDraft.verdict) && vetoReasonRefs.length === 0) {
      setError("expert review field required: veto_reason_refs");
      return;
    }
    setBusy("expert review");
    setError(null);
    try {
      await requestJson("/api/research-os/trust/expert_reviews", {
        method: "POST",
        body: JSON.stringify({
          external_expert_review: {
            review_ref: expertDraft.review_ref.trim() || undefined,
            release_ref: expertDraft.release_ref.trim(),
            reviewer_ref: expertDraft.reviewer_ref.trim(),
            reviewer_independence_ref: expertDraft.reviewer_independence_ref.trim(),
            artifact_ref: expertDraft.artifact_ref.trim(),
            review_protocol_ref: expertDraft.review_protocol_ref.trim(),
            verdict: expertDraft.verdict,
            evidence_refs: evidenceRefs,
            veto_reason_refs: vetoReasonRefs,
            signed_attestation_ref: expertDraft.signed_attestation_ref.trim() || undefined,
            silent_mock_fallback_used: false,
          },
        }),
      });
      setExpertDraft((current) => ({ ...current, review_ref: "", evidence_refs: "", veto_reason_refs: "" }));
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordExpertIdentity() {
    const evidenceRefs = splitRefs(expertIdentityDraft.evidence_refs);
    for (const field of [
      "identity_ref",
      "reviewer_ref",
      "identity_provider_ref",
      "public_key_ref",
      "public_key_pem",
      "reviewer_independence_ref",
    ] as const) {
      if (!expertIdentityDraft[field].trim()) {
        setError(`expert identity field required: ${field}`);
        return;
      }
    }
    if (evidenceRefs.length === 0) {
      setError("expert identity field required: evidence_refs");
      return;
    }
    setBusy("expert identity");
    setError(null);
    try {
      await requestJson("/api/research-os/trust/expert_identities", {
        method: "POST",
        body: JSON.stringify({
          external_reviewer_identity: {
            identity_ref: expertIdentityDraft.identity_ref.trim(),
            reviewer_ref: expertIdentityDraft.reviewer_ref.trim(),
            identity_provider_ref: expertIdentityDraft.identity_provider_ref.trim(),
            public_key_ref: expertIdentityDraft.public_key_ref.trim(),
            public_key_pem: expertIdentityDraft.public_key_pem.trim(),
            reviewer_independence_ref: expertIdentityDraft.reviewer_independence_ref.trim(),
            evidence_refs: evidenceRefs,
          },
        }),
      });
      setExpertIdentityDraft((current) => ({ ...current, identity_ref: "", evidence_refs: "" }));
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordExpertSignature() {
    for (const field of ["review_ref", "identity_ref", "signature_b64", "attestation_ref"] as const) {
      if (!expertSignatureDraft[field].trim()) {
        setError(`expert signature field required: ${field}`);
        return;
      }
    }
    setBusy("expert signature");
    setError(null);
    try {
      await requestJson("/api/research-os/trust/expert_signatures", {
        method: "POST",
        body: JSON.stringify({
          external_expert_signature: {
            review_ref: expertSignatureDraft.review_ref.trim(),
            identity_ref: expertSignatureDraft.identity_ref.trim(),
            signature_b64: expertSignatureDraft.signature_b64.trim(),
            attestation_ref: expertSignatureDraft.attestation_ref.trim(),
          },
        }),
      });
      setExpertSignatureDraft((current) => ({ ...current, signature_b64: "" }));
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const summary = status.state === "ready" ? status.value : null;

  return (
    <div data-testid="trust-disclosure-panel" style={{ display: "grid", gap: 12 }}>
      <section style={sectionStyle}>
        <div style={headerStyle}>
          <span>Trust disclosures</span>
          <div style={{ flex: 1 }} />
          {summary && <Pill tone="info">claims {summary.trust_claim_total ?? 0}</Pill>}
          {summary && <Pill tone="ghost">independence {summary.independence_disclosure_total ?? 0}</Pill>}
          {summary && <Pill tone="ghost">expert {summary.expert_review_total ?? 0}</Pill>}
          {summary && <Pill tone="ghost">identities {summary.expert_identity_total ?? 0}</Pill>}
          {summary && <Pill tone="ghost">signatures {summary.expert_signature_total ?? 0}</Pill>}
          {summary && <Pill tone="ghost">autonomy {summary.user_autonomy_total ?? 0}</Pill>}
        </div>
        <div style={{ padding: 12, display: "grid", gap: 10 }}>
          {status.state === "loading" && <p style={mutedTextStyle}>Loading trust summary...</p>}
          {status.state === "error" && <p role="alert" style={errorTextStyle}>{status.message}</p>}
          {error && <p data-testid="trust-disclosure-error" role="alert" style={errorTextStyle}>{error}</p>}
          {busy && <p style={mutedTextStyle}>Recording {busy}...</p>}
          {summary && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
              <SummaryList
                title="claims"
                empty="No trust claims."
                items={summary.trust_claims ?? []}
                render={(record) => `${record.claim_ref} · ${record.claim_label}`}
              />
              <SummaryList
                title="independence"
                empty="No independence disclosures."
                items={summary.independence_disclosures ?? []}
                render={(record) => `${record.disclosure_ref} · ${record.mode}`}
              />
              <SummaryList
                title="expert reviews"
                empty="No expert reviews."
                items={summary.expert_reviews ?? []}
                render={(record) => `${record.release_ref} · ${record.verdict}`}
              />
              <SummaryList
                title="expert identities"
                empty="No expert identities."
                items={summary.expert_identities ?? []}
                render={(record) => `${record.identity_ref} · ${record.public_key_fingerprint}`}
              />
              <SummaryList
                title="expert signatures"
                empty="No expert signatures."
                items={summary.expert_signatures ?? []}
                render={(record) => `${record.verified_signature_ref} · ${record.review_ref}`}
              />
              <SummaryList
                title="autonomy"
                empty="No user autonomy records."
                items={summary.user_autonomy_records ?? []}
                render={(record) => `${record.choice_ref} · ${record.user_final_choice_ref ?? "no choice"}`}
              />
            </div>
          )}
        </div>
      </section>

      <section style={sectionStyle}>
        <div style={headerStyle}>Record trust claim</div>
        <div style={formGridStyle}>
          <TextInput id="trust-claim-claim_ref" label="claim_ref" value={claimDraft.claim_ref} onChange={(value) => setClaimDraft((current) => ({ ...current, claim_ref: value }))} />
          <label style={labelStyle}>
            <span>claim_label</span>
            <select
              data-testid="trust-claim-claim_label"
              value={claimDraft.claim_label}
              onChange={(event) => setClaimDraft((current) => ({ ...current, claim_label: event.target.value }))}
              style={inputStyle}
            >
              {claimLabels.map((label) => (
                <option key={label} value={label}>{label}</option>
              ))}
            </select>
          </label>
          <TextArea id="trust-claim-evidence_refs" label="evidence_refs" value={claimDraft.evidence_refs} onChange={(value) => setClaimDraft((current) => ({ ...current, evidence_refs: value }))} />
          <TextArea id="trust-claim-weakness_refs" label="weakness_refs" value={claimDraft.weakness_refs} onChange={(value) => setClaimDraft((current) => ({ ...current, weakness_refs: value }))} />
          <TextInput id="trust-claim-cold_start_n" label="cold_start_n" value={claimDraft.cold_start_n} onChange={(value) => setClaimDraft((current) => ({ ...current, cold_start_n: value }))} />
          <TextInput id="trust-claim-pressure_context" label="pressure_context" value={claimDraft.pressure_context} onChange={(value) => setClaimDraft((current) => ({ ...current, pressure_context: value }))} />
          <CheckInput id="trust-claim-weakness_visible_by_default" label="weakness_visible_by_default" checked={claimDraft.weakness_visible_by_default} onChange={(checked) => setClaimDraft((current) => ({ ...current, weakness_visible_by_default: checked }))} />
          <CheckInput id="trust-claim-waiver_weakness_visible_by_default" label="waiver_weakness_visible_by_default" checked={claimDraft.waiver_weakness_visible_by_default} onChange={(checked) => setClaimDraft((current) => ({ ...current, waiver_weakness_visible_by_default: checked }))} />
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <ActionButton testId="trust-record-claim" onClick={recordClaim} disabled={Boolean(busy)}>Record claim</ActionButton>
        </div>
      </section>

      <section style={sectionStyle}>
        <div style={headerStyle}>Record independence disclosure</div>
        <div style={formGridStyle}>
          <TextInput id="trust-independence-disclosure_ref" label="disclosure_ref" value={independenceDraft.disclosure_ref} onChange={(value) => setIndependenceDraft((current) => ({ ...current, disclosure_ref: value }))} />
          <label style={labelStyle}>
            <span>mode</span>
            <select
              data-testid="trust-independence-mode"
              value={independenceDraft.mode}
              onChange={(event) => setIndependenceDraft((current) => ({ ...current, mode: event.target.value }))}
              style={inputStyle}
            >
              <option value="single_user">single_user</option>
              <option value="organization">organization</option>
            </select>
          </label>
          <TextInput id="trust-independence-isolated_validation_ref" label="isolated_validation_ref" value={independenceDraft.isolated_validation_ref} onChange={(value) => setIndependenceDraft((current) => ({ ...current, isolated_validation_ref: value }))} />
          <TextInput id="trust-independence-immutable_evidence_ref" label="immutable_evidence_ref" value={independenceDraft.immutable_evidence_ref} onChange={(value) => setIndependenceDraft((current) => ({ ...current, immutable_evidence_ref: value }))} />
          <TextInput id="trust-independence-second_confirmation_ref" label="second_confirmation_ref" value={independenceDraft.second_confirmation_ref} onChange={(value) => setIndependenceDraft((current) => ({ ...current, second_confirmation_ref: value }))} />
          <TextInput id="trust-independence-alternate_model_verification_ref" label="alternate_model_verification_ref" value={independenceDraft.alternate_model_verification_ref} onChange={(value) => setIndependenceDraft((current) => ({ ...current, alternate_model_verification_ref: value }))} />
          <TextInput id="trust-independence-organization_process_ref" label="organization_process_ref" value={independenceDraft.organization_process_ref} onChange={(value) => setIndependenceDraft((current) => ({ ...current, organization_process_ref: value }))} />
          <CheckInput id="trust-independence-claims_organizational_independence" label="claims_organizational_independence" checked={independenceDraft.claims_organizational_independence} onChange={(checked) => setIndependenceDraft((current) => ({ ...current, claims_organizational_independence: checked }))} />
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <ActionButton testId="trust-record-independence" onClick={recordIndependence} disabled={Boolean(busy)}>Record independence</ActionButton>
        </div>
      </section>

      <section style={sectionStyle}>
        <div style={headerStyle}>Record expert review</div>
        <div style={formGridStyle}>
          <TextInput id="trust-expert-review_ref" label="review_ref optional" value={expertDraft.review_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, review_ref: value }))} />
          <TextInput id="trust-expert-release_ref" label="release_ref" value={expertDraft.release_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, release_ref: value }))} />
          <TextInput id="trust-expert-reviewer_ref" label="reviewer_ref" value={expertDraft.reviewer_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, reviewer_ref: value }))} />
          <TextInput id="trust-expert-reviewer_independence_ref" label="reviewer_independence_ref" value={expertDraft.reviewer_independence_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, reviewer_independence_ref: value }))} />
          <TextInput id="trust-expert-artifact_ref" label="artifact_ref" value={expertDraft.artifact_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, artifact_ref: value }))} />
          <TextInput id="trust-expert-review_protocol_ref" label="review_protocol_ref" value={expertDraft.review_protocol_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, review_protocol_ref: value }))} />
          <label style={labelStyle}>
            <span>verdict</span>
            <select
              data-testid="trust-expert-verdict"
              value={expertDraft.verdict}
              onChange={(event) => setExpertDraft((current) => ({ ...current, verdict: event.target.value }))}
              style={inputStyle}
            >
              <option value="approved">approved</option>
              <option value="vetoed">vetoed</option>
              <option value="needs_revision">needs_revision</option>
            </select>
          </label>
          <TextInput id="trust-expert-signed_attestation_ref" label="signed_attestation_ref" value={expertDraft.signed_attestation_ref} onChange={(value) => setExpertDraft((current) => ({ ...current, signed_attestation_ref: value }))} />
          <TextArea id="trust-expert-evidence_refs" label="evidence_refs" value={expertDraft.evidence_refs} onChange={(value) => setExpertDraft((current) => ({ ...current, evidence_refs: value }))} />
          <TextArea id="trust-expert-veto_reason_refs" label="veto_reason_refs" value={expertDraft.veto_reason_refs} onChange={(value) => setExpertDraft((current) => ({ ...current, veto_reason_refs: value }))} />
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <ActionButton testId="trust-record-expert" onClick={recordExpertReview} disabled={Boolean(busy)}>Record expert review</ActionButton>
        </div>
      </section>

      <section style={sectionStyle}>
        <div style={headerStyle}>Record expert identity</div>
        <div style={formGridStyle}>
          <TextInput id="trust-expert-identity-identity_ref" label="identity_ref" value={expertIdentityDraft.identity_ref} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, identity_ref: value }))} />
          <TextInput id="trust-expert-identity-reviewer_ref" label="reviewer_ref" value={expertIdentityDraft.reviewer_ref} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, reviewer_ref: value }))} />
          <TextInput id="trust-expert-identity-identity_provider_ref" label="identity_provider_ref" value={expertIdentityDraft.identity_provider_ref} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, identity_provider_ref: value }))} />
          <TextInput id="trust-expert-identity-public_key_ref" label="public_key_ref" value={expertIdentityDraft.public_key_ref} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, public_key_ref: value }))} />
          <TextArea id="trust-expert-identity-public_key_pem" label="public_key_pem" value={expertIdentityDraft.public_key_pem} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, public_key_pem: value }))} />
          <TextInput id="trust-expert-identity-reviewer_independence_ref" label="reviewer_independence_ref" value={expertIdentityDraft.reviewer_independence_ref} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, reviewer_independence_ref: value }))} />
          <TextArea id="trust-expert-identity-evidence_refs" label="evidence_refs" value={expertIdentityDraft.evidence_refs} onChange={(value) => setExpertIdentityDraft((current) => ({ ...current, evidence_refs: value }))} />
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <ActionButton testId="trust-record-expert-identity" onClick={recordExpertIdentity} disabled={Boolean(busy)}>Record identity</ActionButton>
        </div>
      </section>

      <section style={sectionStyle}>
        <div style={headerStyle}>Record expert signature</div>
        <div style={formGridStyle}>
          <TextInput id="trust-expert-signature-review_ref" label="review_ref" value={expertSignatureDraft.review_ref} onChange={(value) => setExpertSignatureDraft((current) => ({ ...current, review_ref: value }))} />
          <TextInput id="trust-expert-signature-identity_ref" label="identity_ref" value={expertSignatureDraft.identity_ref} onChange={(value) => setExpertSignatureDraft((current) => ({ ...current, identity_ref: value }))} />
          <TextArea id="trust-expert-signature-signature_b64" label="signature_b64" value={expertSignatureDraft.signature_b64} onChange={(value) => setExpertSignatureDraft((current) => ({ ...current, signature_b64: value }))} />
          <TextInput id="trust-expert-signature-attestation_ref" label="attestation_ref" value={expertSignatureDraft.attestation_ref} onChange={(value) => setExpertSignatureDraft((current) => ({ ...current, attestation_ref: value }))} />
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <ActionButton testId="trust-record-expert-signature" onClick={recordExpertSignature} disabled={Boolean(busy)}>Record signature</ActionButton>
        </div>
      </section>

      <section style={sectionStyle}>
        <div style={headerStyle}>Record user autonomy</div>
        <div style={formGridStyle}>
          <TextInput id="trust-autonomy-choice_ref" label="choice_ref" value={autonomyDraft.choice_ref} onChange={(value) => setAutonomyDraft((current) => ({ ...current, choice_ref: value }))} />
          <TextInput id="trust-autonomy-agent_recommendation_ref" label="agent_recommendation_ref" value={autonomyDraft.agent_recommendation_ref} onChange={(value) => setAutonomyDraft((current) => ({ ...current, agent_recommendation_ref: value }))} />
          <TextArea id="trust-autonomy-tradeoff_refs" label="tradeoff_refs" value={autonomyDraft.tradeoff_refs} onChange={(value) => setAutonomyDraft((current) => ({ ...current, tradeoff_refs: value }))} />
          <TextArea id="trust-autonomy-alternative_path_refs" label="alternative_path_refs" value={autonomyDraft.alternative_path_refs} onChange={(value) => setAutonomyDraft((current) => ({ ...current, alternative_path_refs: value }))} />
          <TextInput id="trust-autonomy-responsibility_boundary_ref" label="responsibility_boundary_ref" value={autonomyDraft.responsibility_boundary_ref} onChange={(value) => setAutonomyDraft((current) => ({ ...current, responsibility_boundary_ref: value }))} />
          <TextInput id="trust-autonomy-user_final_choice_ref" label="user_final_choice_ref" value={autonomyDraft.user_final_choice_ref} onChange={(value) => setAutonomyDraft((current) => ({ ...current, user_final_choice_ref: value }))} />
          <TextArea id="trust-autonomy-redline_refs" label="redline_refs" value={autonomyDraft.redline_refs} onChange={(value) => setAutonomyDraft((current) => ({ ...current, redline_refs: value }))} />
          <CheckInput id="trust-autonomy-agent_made_final_choice" label="agent_made_final_choice" checked={autonomyDraft.agent_made_final_choice} onChange={(checked) => setAutonomyDraft((current) => ({ ...current, agent_made_final_choice: checked }))} />
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <ActionButton testId="trust-record-autonomy" onClick={recordAutonomy} disabled={Boolean(busy)}>Record autonomy</ActionButton>
        </div>
      </section>
    </div>
  );
}

function SummaryList<T>({
  title,
  empty,
  items,
  render,
}: {
  title: string;
  empty: string;
  items: T[];
  render: (item: T) => string;
}) {
  return (
    <div style={{ display: "grid", gap: 6, minWidth: 0 }}>
      <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>{title}</strong>
      {items.length === 0 ? (
        <p style={mutedTextStyle}>{empty}</p>
      ) : (
        items.slice(0, 5).map((item, index) => (
          <Pill key={index} tone="ghost" title={render(item)}>
            {render(item)}
          </Pill>
        ))
      )}
    </div>
  );
}

function TextInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label style={labelStyle}>
      <span>{label}</span>
      <input data-testid={id} value={value} onChange={(event) => onChange(event.target.value)} style={inputStyle} />
    </label>
  );
}

function TextArea({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label style={labelStyle}>
      <span>{label}</span>
      <textarea
        data-testid={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{ ...inputStyle, minHeight: 58, resize: "vertical" }}
      />
    </label>
  );
}

function CheckInput({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label style={{ ...labelStyle, display: "flex", alignItems: "center", gap: 8 }}>
      <input data-testid={id} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

const formGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 10,
  padding: 12,
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
