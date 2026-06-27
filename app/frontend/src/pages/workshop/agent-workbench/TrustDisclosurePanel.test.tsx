import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as auth from "../../../lib/auth";
import { TrustDisclosurePanel } from "./TrustDisclosurePanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function installTrustMock() {
  const calls: { url: string; init?: RequestInit }[] = [];
  const claims: Record<string, unknown>[] = [];
  const independence: Record<string, unknown>[] = [];
  const expertReviews: Record<string, unknown>[] = [];
  const expertIdentities: Record<string, unknown>[] = [];
  const expertSignatures: Record<string, unknown>[] = [];
  const autonomy: Record<string, unknown>[] = [];
  vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === "/api/research-os/trust/summary") {
      return Promise.resolve(
        jsonResponse({
          user: "u1",
          trust_claim_total: claims.length,
          trust_claims: claims,
          independence_disclosure_total: independence.length,
          independence_disclosures: independence,
          expert_review_total: expertReviews.length,
          expert_reviews: expertReviews,
          expert_identity_total: expertIdentities.length,
          expert_identities: expertIdentities,
          expert_signature_total: expertSignatures.length,
          expert_signatures: expertSignatures,
          user_autonomy_total: autonomy.length,
          user_autonomy_records: autonomy,
          release_gate_total: 0,
          release_gates: [],
          release_check_total: 0,
          release_checks: [],
        }),
      );
    }
    if (url === "/api/research-os/trust/claims") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const claim = body.trust_claim;
      if (!claim.evidence_refs?.length && claim.claim_label === "evidence_sufficient") {
        return Promise.resolve(jsonResponse({ detail: "strong_claim_without_evidence:evidence_refs" }, 422));
      }
      claims.push(claim);
      return Promise.resolve(jsonResponse({ ...claim, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/trust/independence_disclosures") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      independence.push(body.independence_disclosure);
      return Promise.resolve(jsonResponse({ ...body.independence_disclosure, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/trust/expert_reviews") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const review = {
        review_ref: body.external_expert_review.review_ref || "expert_review:generated",
        source_hash: "sha256:expert-review",
        ...body.external_expert_review,
      };
      expertReviews.push(review);
      return Promise.resolve(jsonResponse({ ...review, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/trust/expert_identities") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const identity = {
        ...body.external_reviewer_identity,
        public_key_fingerprint: "sha16:pub",
        identity_hash: "sha16:identity",
        status: "active",
      };
      expertIdentities.push({
        identity_ref: identity.identity_ref,
        reviewer_ref: identity.reviewer_ref,
        identity_provider_ref: identity.identity_provider_ref,
        public_key_ref: identity.public_key_ref,
        public_key_fingerprint: identity.public_key_fingerprint,
        reviewer_independence_ref: identity.reviewer_independence_ref,
        evidence_refs: identity.evidence_refs,
        status: identity.status,
        identity_hash: identity.identity_hash,
      });
      return Promise.resolve(jsonResponse({ ...identity, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/trust/expert_signatures") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const signature = {
        ...body.external_expert_signature,
        verified_signature_ref: "verified_signature:001",
        reviewer_ref: "expert:independent_quant_reviewer",
        public_key_ref: "public_key:expert:001",
        public_key_fingerprint: "sha16:pub",
        signed_payload_hash: "sha16:payload",
        verification_hash: "sha16:verification",
      };
      expertSignatures.push({
        verified_signature_ref: signature.verified_signature_ref,
        attestation_ref: signature.attestation_ref,
        review_ref: signature.review_ref,
        reviewer_ref: signature.reviewer_ref,
        identity_ref: signature.identity_ref,
        public_key_ref: signature.public_key_ref,
        public_key_fingerprint: signature.public_key_fingerprint,
        signed_payload_hash: signature.signed_payload_hash,
        verification_hash: signature.verification_hash,
      });
      return Promise.resolve(jsonResponse({ ...signature, recorded_by: "u1" }));
    }
    if (url === "/api/research-os/trust/user_autonomy") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      autonomy.push(body.user_autonomy);
      return Promise.resolve(jsonResponse({ ...body.user_autonomy, recorded_by: "u1" }));
    }
    return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
  });
  return { calls, claims, independence, expertReviews, expertIdentities, expertSignatures, autonomy };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TrustDisclosurePanel", () => {
  it("records trust claim, independence disclosure, and user autonomy via backend APIs", async () => {
    const { calls } = installTrustMock();
    render(<TrustDisclosurePanel />);

    expect(await screen.findByText("claims 0")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("trust-claim-claim_ref"), { target: { value: "claim:psr" } });
    fireEvent.change(screen.getByTestId("trust-claim-evidence_refs"), {
      target: { value: "validation_dossier:001" },
    });
    fireEvent.change(screen.getByTestId("trust-claim-weakness_refs"), {
      target: { value: "weakness:borrow_cost" },
    });
    fireEvent.click(screen.getByTestId("trust-record-claim"));

    expect(await screen.findByText("claims 1")).toBeInTheDocument();
    const claimCall = calls.find((call) => call.url === "/api/research-os/trust/claims");
    expect(JSON.parse(String(claimCall?.init?.body)).trust_claim).toMatchObject({
      claim_ref: "claim:psr",
      claim_label: "evidence_sufficient",
      evidence_refs: ["validation_dossier:001"],
      weakness_refs: ["weakness:borrow_cost"],
      weakness_visible_by_default: true,
    });

    fireEvent.change(screen.getByTestId("trust-independence-disclosure_ref"), {
      target: { value: "independence:single_user:001" },
    });
    fireEvent.change(screen.getByTestId("trust-independence-isolated_validation_ref"), {
      target: { value: "validation:isolated" },
    });
    fireEvent.change(screen.getByTestId("trust-independence-immutable_evidence_ref"), {
      target: { value: "artifact_hash:rdp" },
    });
    fireEvent.change(screen.getByTestId("trust-independence-second_confirmation_ref"), {
      target: { value: "confirmation:user" },
    });
    fireEvent.change(screen.getByTestId("trust-independence-alternate_model_verification_ref"), {
      target: { value: "llm_call:critic" },
    });
    fireEvent.click(screen.getByTestId("trust-record-independence"));

    expect(await screen.findByText("independence 1")).toBeInTheDocument();
    const independenceCall = calls.find((call) => call.url === "/api/research-os/trust/independence_disclosures");
    expect(JSON.parse(String(independenceCall?.init?.body)).independence_disclosure).toMatchObject({
      disclosure_ref: "independence:single_user:001",
      mode: "single_user",
      isolated_validation_ref: "validation:isolated",
    });

    fireEvent.change(screen.getByTestId("trust-expert-release_ref"), {
      target: { value: "release:v1" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-review_ref"), {
      target: { value: "expert_review:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-reviewer_ref"), {
      target: { value: "expert:independent_quant_reviewer" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-reviewer_independence_ref"), {
      target: { value: "independence:expert:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-artifact_ref"), {
      target: { value: "rdp_package:release:v1" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-review_protocol_ref"), {
      target: { value: "protocol:trust_release_review:v1" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-evidence_refs"), {
      target: { value: "evidence:expert-notes" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-signed_attestation_ref"), {
      target: { value: "attestation:expert-signature:001" },
    });
    fireEvent.click(screen.getByTestId("trust-record-expert"));

    expect(await screen.findByText("expert 1")).toBeInTheDocument();
    const expertCall = calls.find((call) => call.url === "/api/research-os/trust/expert_reviews");
    expect(JSON.parse(String(expertCall?.init?.body)).external_expert_review).toMatchObject({
      release_ref: "release:v1",
      reviewer_ref: "expert:independent_quant_reviewer",
      reviewer_independence_ref: "independence:expert:001",
      artifact_ref: "rdp_package:release:v1",
      verdict: "approved",
      evidence_refs: ["evidence:expert-notes"],
      signed_attestation_ref: "attestation:expert-signature:001",
      silent_mock_fallback_used: false,
    });

    const publicKeyPem = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAexample\n-----END PUBLIC KEY-----";
    fireEvent.change(screen.getByTestId("trust-expert-identity-identity_ref"), {
      target: { value: "expert_identity:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-identity-reviewer_ref"), {
      target: { value: "expert:independent_quant_reviewer" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-identity-identity_provider_ref"), {
      target: { value: "provider:quant-review-board" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-identity-public_key_ref"), {
      target: { value: "public_key:expert:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-identity-public_key_pem"), {
      target: { value: publicKeyPem },
    });
    fireEvent.change(screen.getByTestId("trust-expert-identity-reviewer_independence_ref"), {
      target: { value: "independence:expert:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-identity-evidence_refs"), {
      target: { value: "evidence:expert-profile" },
    });
    fireEvent.click(screen.getByTestId("trust-record-expert-identity"));

    expect(await screen.findByText("identities 1")).toBeInTheDocument();
    expect(await screen.findByText("expert_identity:001 · sha16:pub")).toBeInTheDocument();
    const identityCall = calls.find((call) => call.url === "/api/research-os/trust/expert_identities");
    expect(JSON.parse(String(identityCall?.init?.body)).external_reviewer_identity).toMatchObject({
      identity_ref: "expert_identity:001",
      reviewer_ref: "expert:independent_quant_reviewer",
      identity_provider_ref: "provider:quant-review-board",
      public_key_ref: "public_key:expert:001",
      public_key_pem: publicKeyPem,
      reviewer_independence_ref: "independence:expert:001",
      evidence_refs: ["evidence:expert-profile"],
    });

    fireEvent.change(screen.getByTestId("trust-expert-signature-review_ref"), {
      target: { value: "expert_review:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-signature-identity_ref"), {
      target: { value: "expert_identity:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-signature-signature_b64"), {
      target: { value: "base64-detached-signature" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-signature-attestation_ref"), {
      target: { value: "attestation:expert-signature:001" },
    });
    fireEvent.click(screen.getByTestId("trust-record-expert-signature"));

    expect(await screen.findByText("signatures 1")).toBeInTheDocument();
    expect(await screen.findByText("verified_signature:001 · expert_review:001")).toBeInTheDocument();
    const signatureCall = calls.find((call) => call.url === "/api/research-os/trust/expert_signatures");
    expect(JSON.parse(String(signatureCall?.init?.body)).external_expert_signature).toMatchObject({
      review_ref: "expert_review:001",
      identity_ref: "expert_identity:001",
      signature_b64: "base64-detached-signature",
      attestation_ref: "attestation:expert-signature:001",
    });

    fireEvent.change(screen.getByTestId("trust-autonomy-choice_ref"), {
      target: { value: "choice:methodology:001" },
    });
    fireEvent.change(screen.getByTestId("trust-autonomy-agent_recommendation_ref"), {
      target: { value: "recommendation:strict_path" },
    });
    fireEvent.change(screen.getByTestId("trust-autonomy-tradeoff_refs"), {
      target: { value: "tradeoff:longer_validation" },
    });
    fireEvent.change(screen.getByTestId("trust-autonomy-alternative_path_refs"), {
      target: { value: "path:exploratory,path:strict" },
    });
    fireEvent.change(screen.getByTestId("trust-autonomy-responsibility_boundary_ref"), {
      target: { value: "responsibility:user" },
    });
    fireEvent.change(screen.getByTestId("trust-autonomy-user_final_choice_ref"), {
      target: { value: "user_choice:strict" },
    });
    fireEvent.click(screen.getByTestId("trust-record-autonomy"));

    expect(await screen.findByText("autonomy 1")).toBeInTheDocument();
    const autonomyCall = calls.find((call) => call.url === "/api/research-os/trust/user_autonomy");
    expect(JSON.parse(String(autonomyCall?.init?.body)).user_autonomy).toMatchObject({
      choice_ref: "choice:methodology:001",
      agent_recommendation_ref: "recommendation:strict_path",
      tradeoff_refs: ["tradeoff:longer_validation"],
      alternative_path_refs: ["path:exploratory", "path:strict"],
      responsibility_boundary_ref: "responsibility:user",
      user_final_choice_ref: "user_choice:strict",
      agent_made_final_choice: false,
    });
  });

  it("blocks strong trust claim without evidence before making a backend request", async () => {
    const { calls } = installTrustMock();
    render(<TrustDisclosurePanel />);

    await screen.findByText("claims 0");
    fireEvent.change(screen.getByTestId("trust-claim-claim_ref"), { target: { value: "claim:bad" } });
    fireEvent.click(screen.getByTestId("trust-record-claim"));

    expect(await screen.findByTestId("trust-disclosure-error")).toHaveTextContent("evidence_refs");
    await waitFor(() => expect(calls.some((call) => call.url === "/api/research-os/trust/claims")).toBe(false));
  });

  it("blocks approved expert review without signed attestation before making a backend request", async () => {
    const { calls } = installTrustMock();
    render(<TrustDisclosurePanel />);

    await screen.findByText("claims 0");
    fireEvent.change(screen.getByTestId("trust-expert-release_ref"), {
      target: { value: "release:v1" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-reviewer_ref"), {
      target: { value: "expert:independent_quant_reviewer" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-reviewer_independence_ref"), {
      target: { value: "independence:expert:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-artifact_ref"), {
      target: { value: "rdp_package:release:v1" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-review_protocol_ref"), {
      target: { value: "protocol:trust_release_review:v1" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-evidence_refs"), {
      target: { value: "evidence:expert-notes" },
    });
    fireEvent.click(screen.getByTestId("trust-record-expert"));

    expect(await screen.findByTestId("trust-disclosure-error")).toHaveTextContent("signed_attestation_ref");
    await waitFor(() => expect(calls.some((call) => call.url === "/api/research-os/trust/expert_reviews")).toBe(false));
  });

  it("blocks expert signature verification without detached signature before making a backend request", async () => {
    const { calls } = installTrustMock();
    render(<TrustDisclosurePanel />);

    await screen.findByText("claims 0");
    fireEvent.change(screen.getByTestId("trust-expert-signature-review_ref"), {
      target: { value: "expert_review:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-signature-identity_ref"), {
      target: { value: "expert_identity:001" },
    });
    fireEvent.change(screen.getByTestId("trust-expert-signature-attestation_ref"), {
      target: { value: "attestation:expert-signature:001" },
    });
    fireEvent.click(screen.getByTestId("trust-record-expert-signature"));

    expect(await screen.findByTestId("trust-disclosure-error")).toHaveTextContent("signature_b64");
    await waitFor(() => expect(calls.some((call) => call.url === "/api/research-os/trust/expert_signatures")).toBe(false));
  });
});
