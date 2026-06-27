import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import * as auth from "../../../lib/auth";
import { ResearchRAGPanel } from "./ResearchRAGPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const ragHit = {
  source_id: "doc:risk-parity",
  version: "v1",
  timestamp: "2026-06-27T00:00:00Z",
  permission: {
    allowed_users: ["wzy"],
    allowed_desks: ["research"],
    allowed_assets: ["qro:portfolio-risk"],
    permission_tags: ["research.read"],
  },
  applicability: "candidate research evidence for portfolio risk",
  projection: "ResearchRAG",
  asset_ref: "qro:portfolio-risk",
  title: "Risk parity covariance shrinkage note",
  snippet: "risk parity covariance shrinkage portfolio construction",
  score: 0.73,
  evidence_label: "candidate_context",
  context_role: "candidate_context",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ResearchRAGPanel", () => {
  it("requires explicit visible_asset_refs before hitting backend", async () => {
    const spy = vi.spyOn(auth, "authFetch");
    render(<ResearchRAGPanel />);

    fireEvent.change(screen.getByTestId("rag-query"), { target: { value: "covariance shrinkage" } });
    fireEvent.click(screen.getByTestId("rag-submit"));

    expect(await screen.findByTestId("rag-error")).toHaveTextContent("visible_asset_refs required");
    expect(spy).not.toHaveBeenCalled();
  });

  it("sparse vector search sends explicit permissions and renders candidate-context hits", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return Promise.resolve(jsonResponse({ hits: [ragHit], agent_usage_ids: [] }));
    });

    render(<ResearchRAGPanel />);

    fireEvent.change(screen.getByTestId("rag-query"), { target: { value: "covariance shrinkage risk" } });
    fireEvent.change(screen.getByTestId("rag-assets"), {
      target: { value: "qro:portfolio-risk\nqro:portfolio-risk" },
    });
    fireEvent.change(screen.getByTestId("rag-tags"), { target: { value: "research.read, internal" } });
    fireEvent.change(screen.getByTestId("rag-top-k"), { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("rag-submit"));

    expect(await screen.findByText("Risk parity covariance shrinkage note")).toBeInTheDocument();
    expect(screen.getByText("doc:risk-parity")).toBeInTheDocument();
    expect(screen.getByText("0.730")).toBeInTheDocument();
    expect(screen.getAllByText("candidate_context").length).toBeGreaterThan(0);

    expect(calls[0].url).toBe("/api/research-os/rag/vector_search");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      query: "covariance shrinkage risk",
      desk: "research",
      visible_asset_refs: ["qro:portfolio-risk"],
      permission_tags: ["research.read", "internal"],
      projections: ["ResearchRAG"],
      actor: "user",
      top_k: 7,
    });
  });

  it("lexical mode uses retrieve endpoint and clamps top_k", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return Promise.resolve(jsonResponse({ hits: [], agent_usage_ids: [] }));
    });

    render(<ResearchRAGPanel />);

    fireEvent.click(screen.getByText("lexical"));
    fireEvent.change(screen.getByTestId("rag-query"), { target: { value: "momentum" } });
    fireEvent.change(screen.getByTestId("rag-assets"), { target: { value: "qro:signal-momentum" } });
    fireEvent.change(screen.getByTestId("rag-top-k"), { target: { value: "99" } });
    fireEvent.click(screen.getByTestId("rag-submit"));

    expect(await screen.findByTestId("rag-empty")).toHaveTextContent("No authorized candidate context");
    expect(calls[0].url).toBe("/api/research-os/rag/retrieve");
    expect(JSON.parse(String(calls[0].init?.body)).top_k).toBe(20);
  });

  it("backend 422 is shown without fake hits", async () => {
    vi.spyOn(auth, "authFetch").mockResolvedValue(jsonResponse({ detail: "desk is required" }, 422));

    render(<ResearchRAGPanel />);

    fireEvent.change(screen.getByTestId("rag-query"), { target: { value: "risk" } });
    fireEvent.change(screen.getByTestId("rag-assets"), { target: { value: "qro:risk" } });
    fireEvent.change(screen.getByTestId("rag-desk"), { target: { value: "research" } });
    fireEvent.click(screen.getByTestId("rag-submit"));

    expect(await screen.findByTestId("rag-error")).toHaveTextContent("desk is required");
    await waitFor(() => expect(screen.queryByTestId("rag-hit")).toBeNull());
  });

  it("loads document source summary without raw document payload", async () => {
    const calls: string[] = [];
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/research-os/documents/summary") {
        return Promise.resolve(
          jsonResponse({
            user: "u1",
            sources: [
              {
                source_ref: "source:paper:001",
                parser_sandbox_ref: "parser_sandbox:local_pdf_pymupdf_layout_no_network_v1",
                mime_magic_check_ref: "mime:application/pdf:suffix:.pdf:magic:%PDF",
                source_hash: "sha256:doc",
                license_rights_ref: "license:rights:user_supplied_local",
                no_network_parser: true,
              },
            ],
            spans: [
              {
                span_ref: "span:001",
                source_id: "source:paper:001",
                page: 1,
                block_id: "block:001",
                parser_confidence: 0.99,
                verified: true,
              },
            ],
            claims: [],
            tool_requests: [],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ detail: "unexpected route" }, 500));
    });

    render(<ResearchRAGPanel />);

    fireEvent.click(screen.getByTestId("doc-summary-load"));

    expect(await screen.findByText("source:paper:001")).toBeInTheDocument();
    expect(screen.getByText("parser_sandbox:local_pdf_pymupdf_layout_no_network_v1")).toBeInTheDocument();
    expect(screen.getByText("spans 1")).toBeInTheDocument();
    expect(screen.queryByText("raw_document")).toBeNull();
    expect(calls).toEqual(["/api/research-os/documents/summary"]);
  });

  it("requires an upload file before calling parser upload", async () => {
    const spy = vi.spyOn(auth, "authFetch");
    render(<ResearchRAGPanel />);

    fireEvent.change(screen.getByTestId("doc-upload-asset"), { target: { value: "qro:research:upload" } });
    fireEvent.click(screen.getByTestId("doc-upload-submit"));

    expect(await screen.findByTestId("doc-upload-error")).toHaveTextContent("file required");
    expect(spy).not.toHaveBeenCalled();
  });

  it("uploads a document with FormData and renders only parser metadata", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(auth, "authFetch").mockImplementation((input: RequestInfo, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return Promise.resolve(
        jsonResponse({
          upload_ref: "document_upload:abc",
          source_ref: "source_doc:uploaded",
          source_path: "document_uploads/abc/upload.md",
          source_hash: "sha256:upload",
          doc_version_id: "doc_version:upload",
          parser_run_id: "parser_run:upload",
          mime_magic_check_ref: "mime:text/markdown:suffix:.md:utf8_no_nul",
          span_refs: ["span:uploaded"],
          rag_document_ids: ["ragdoc_uploaded"],
          rag_source_ids: ["span:uploaded"],
          raw_document: "must not render",
        }),
      );
    });

    render(<ResearchRAGPanel />);

    const file = new File(["Uploaded momentum note"], "upload.md", { type: "text/markdown" });
    fireEvent.change(screen.getByTestId("doc-upload-file"), { target: { files: [file] } });
    fireEvent.change(screen.getByTestId("doc-upload-asset"), { target: { value: "qro:research:upload" } });
    fireEvent.click(screen.getByTestId("doc-upload-submit"));

    expect(await screen.findByTestId("doc-upload-result")).toHaveTextContent("source_doc:uploaded");
    expect(screen.getByText("spans 1")).toBeInTheDocument();
    expect(screen.getByText("rag 1")).toBeInTheDocument();
    expect(screen.queryByText("must not render")).toBeNull();

    expect(calls[0].url).toBe("/api/research-os/documents/parse_upload");
    const body = calls[0].init?.body;
    expect(body).toBeInstanceOf(FormData);
    const form = body as FormData;
    expect((form.get("file") as File).name).toBe("upload.md");
    expect(form.get("license_rights_ref")).toBe("license:rights:user_supplied_upload");
    expect(form.get("asset_ref")).toBe("qro:research:upload");
    expect(form.get("permission_tags")).toBe("research.read");
    expect(calls[0].init?.headers).toBeUndefined();
  });
});
