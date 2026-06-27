import { useMemo, useState, type CSSProperties } from "react";
import { Pill, SegmentedControl } from "../../../components/desk";
import { authFetch } from "../../../lib/auth";

type SearchMode = "lexical" | "sparse_vector";

interface RAGHit {
  source_id: string;
  version: string;
  timestamp: string;
  permission: Record<string, string[]>;
  applicability: string;
  projection: string;
  asset_ref: string;
  title: string;
  snippet: string;
  score: number;
  evidence_label: string;
  context_role: string;
}

interface DocumentSourceSummary {
  source_ref: string;
  parser_sandbox_ref?: string | null;
  mime_magic_check_ref?: string | null;
  license_rights_ref?: string | null;
  no_network_parser?: boolean;
  source_hash?: string | null;
}

interface DocumentSpanSummary {
  span_ref: string;
  source_id: string;
  page?: number | null;
  block_id: string;
  parser_confidence: number;
  verified: boolean;
}

interface DocumentSummary {
  user: string;
  sources: DocumentSourceSummary[];
  spans: DocumentSpanSummary[];
  claims: unknown[];
  tool_requests: unknown[];
}

interface DocumentUploadResult {
  upload_ref: string;
  source_ref: string;
  source_path: string;
  mime_magic_check_ref: string;
  span_refs: string[];
  rag_document_ids: string[];
}

type SearchStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; hits: RAGHit[]; usageIds: string[]; endpoint: string };

type DocumentStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; summary: DocumentSummary };

type UploadStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; result: DocumentUploadResult };

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

function splitRefs(value: string): string[] {
  const seen = new Set<string>();
  const refs: string[] = [];
  for (const part of value.split(/[\n,]/)) {
    const ref = part.trim();
    if (!ref || seen.has(ref)) continue;
    seen.add(ref);
    refs.push(ref);
  }
  return refs;
}

function scoreLabel(value: number): string {
  if (!Number.isFinite(value)) return "0.000";
  return value.toFixed(3);
}

function short(value: string, size = 34): string {
  if (value.length <= size) return value;
  return `${value.slice(0, size)}...`;
}

const panelStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(220px, 300px) minmax(0, 1fr)",
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

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--desk-text-muted)",
  fontSize: 12,
  lineHeight: 1.55,
};

const errorTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--desk-danger)",
  fontSize: 12,
  lineHeight: 1.5,
};

export function ResearchRAGPanel() {
  const [mode, setMode] = useState<SearchMode>("sparse_vector");
  const [query, setQuery] = useState("");
  const [desk, setDesk] = useState("research");
  const [assetRefsRaw, setAssetRefsRaw] = useState("");
  const [permissionTagsRaw, setPermissionTagsRaw] = useState("research.read");
  const [topK, setTopK] = useState(5);
  const [status, setStatus] = useState<SearchStatus>({ state: "idle" });
  const [docStatus, setDocStatus] = useState<DocumentStatus>({ state: "idle" });
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>({ state: "idle" });
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadAssetRef, setUploadAssetRef] = useState("");
  const [uploadRightsRef, setUploadRightsRef] = useState("license:rights:user_supplied_upload");
  const [uploadSourceUrl, setUploadSourceUrl] = useState("");
  const [uploadAllowedHosts, setUploadAllowedHosts] = useState("");

  const visibleAssetRefs = useMemo(() => splitRefs(assetRefsRaw), [assetRefsRaw]);
  const permissionTags = useMemo(() => splitRefs(permissionTagsRaw), [permissionTagsRaw]);

  async function search() {
    const trimmedQuery = query.trim();
    const trimmedDesk = desk.trim();
    const safeTopK = Math.max(1, Math.min(20, Math.trunc(Number(topK) || 5)));
    setTopK(safeTopK);

    if (!trimmedQuery) {
      setStatus({ state: "error", message: "query required" });
      return;
    }
    if (!trimmedDesk) {
      setStatus({ state: "error", message: "desk required" });
      return;
    }
    if (visibleAssetRefs.length === 0) {
      setStatus({ state: "error", message: "visible_asset_refs required; no implicit full-library retrieval" });
      return;
    }

    const endpoint =
      mode === "sparse_vector"
        ? "/api/research-os/rag/vector_search"
        : "/api/research-os/rag/retrieve";
    setStatus({ state: "loading" });
    try {
      const payload = await requestJson<{ hits: RAGHit[]; agent_usage_ids?: string[] }>(endpoint, {
        method: "POST",
        body: JSON.stringify({
          query: trimmedQuery,
          desk: trimmedDesk,
          visible_asset_refs: visibleAssetRefs,
          permission_tags: permissionTags,
          projections: ["ResearchRAG"],
          actor: "user",
          top_k: safeTopK,
        }),
      });
      setStatus({
        state: "ready",
        hits: payload.hits ?? [],
        usageIds: payload.agent_usage_ids ?? [],
        endpoint,
      });
    } catch (exc) {
      setStatus({ state: "error", message: (exc as Error).message });
    }
  }

  async function loadDocumentSummary() {
    setDocStatus({ state: "loading" });
    try {
      const summary = await requestJson<DocumentSummary>("/api/research-os/documents/summary");
      setDocStatus({ state: "ready", summary });
    } catch (exc) {
      setDocStatus({ state: "error", message: (exc as Error).message });
    }
  }

  async function uploadDocument() {
    const safeDesk = desk.trim();
    const safeAssetRef = uploadAssetRef.trim() || visibleAssetRefs[0] || "";
    const safeRightsRef = uploadRightsRef.trim();
    if (!uploadFile) {
      setUploadStatus({ state: "error", message: "file required" });
      return;
    }
    if (!safeDesk) {
      setUploadStatus({ state: "error", message: "desk required" });
      return;
    }
    if (!safeAssetRef) {
      setUploadStatus({ state: "error", message: "asset_ref required" });
      return;
    }
    if (!safeRightsRef) {
      setUploadStatus({ state: "error", message: "license_rights_ref required" });
      return;
    }

    const form = new FormData();
    form.set("file", uploadFile);
    form.set("license_rights_ref", safeRightsRef);
    form.set("asset_ref", safeAssetRef);
    form.set("desk", safeDesk);
    form.set("permission_tags", permissionTagsRaw);
    form.set("ingest_to_rag", "true");
    form.set("projection", "ResearchRAG");
    if (uploadSourceUrl.trim()) form.set("source_url", uploadSourceUrl.trim());
    if (uploadAllowedHosts.trim()) form.set("allowed_url_hosts", uploadAllowedHosts.trim());

    setUploadStatus({ state: "loading" });
    try {
      const result = await requestJson<DocumentUploadResult>("/api/research-os/documents/parse_upload", {
        method: "POST",
        body: form,
      });
      setUploadStatus({ state: "ready", result });
    } catch (exc) {
      setUploadStatus({ state: "error", message: (exc as Error).message });
    }
  }

  return (
    <div data-testid="rag-search-panel" style={panelStyle}>
      <section style={sectionStyle}>
        <div style={sectionHeaderStyle}>
          <span>Research Asset RAG</span>
          <div style={{ flex: 1 }} />
          <Pill tone="success">Backend</Pill>
        </div>
        <div style={{ ...sectionBodyStyle, display: "grid", gap: 12 }}>
          <label style={labelStyle}>
            <span>query</span>
            <textarea
              data-testid="rag-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={4}
              style={{ ...inputStyle, resize: "vertical", lineHeight: 1.45 }}
            />
          </label>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 86px", gap: 8 }}>
            <label style={labelStyle}>
              <span>desk</span>
              <input
                data-testid="rag-desk"
                value={desk}
                onChange={(event) => setDesk(event.target.value)}
                style={inputStyle}
              />
            </label>
            <label style={labelStyle}>
              <span>top_k</span>
              <input
                data-testid="rag-top-k"
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
                style={inputStyle}
              />
            </label>
          </div>

          <label style={labelStyle}>
            <span>visible_asset_refs</span>
            <textarea
              data-testid="rag-assets"
              value={assetRefsRaw}
              onChange={(event) => setAssetRefsRaw(event.target.value)}
              rows={3}
              style={{ ...inputStyle, resize: "vertical", lineHeight: 1.45 }}
            />
          </label>

          <label style={labelStyle}>
            <span>permission_tags</span>
            <input
              data-testid="rag-tags"
              value={permissionTagsRaw}
              onChange={(event) => setPermissionTagsRaw(event.target.value)}
              style={inputStyle}
            />
          </label>

          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <SegmentedControl<SearchMode>
              size="sm"
              value={mode}
              onChange={setMode}
              options={[
                { value: "sparse_vector", label: "sparse vector" },
                { value: "lexical", label: "lexical" },
              ]}
            />
            <button
              data-testid="rag-submit"
              type="button"
              onClick={search}
              disabled={status.state === "loading"}
              style={{
                background: "var(--desk-accent)",
                border: "1px solid var(--desk-border)",
                color: "var(--desk-accent-ink)",
                borderRadius: "var(--desk-radius-sm)",
                fontFamily: "inherit",
                fontSize: 11,
                fontWeight: 700,
                padding: "7px 10px",
                cursor: status.state === "loading" ? "wait" : "pointer",
              }}
            >
              Search
            </button>
          </div>

          <div style={{ borderTop: "1px solid var(--desk-border)", paddingTop: 11, display: "grid", gap: 9 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "var(--desk-text)", fontSize: 12, fontWeight: 700 }}>Document evidence</span>
              <div style={{ flex: 1 }} />
              <button
                data-testid="doc-summary-load"
                type="button"
                onClick={loadDocumentSummary}
                disabled={docStatus.state === "loading"}
                style={{
                  background: "transparent",
                  border: "1px solid var(--desk-border)",
                  color: "var(--desk-text-muted)",
                  borderRadius: "var(--desk-radius-sm)",
                  fontFamily: "inherit",
                  fontSize: 11,
                  padding: "6px 9px",
                  cursor: docStatus.state === "loading" ? "wait" : "pointer",
                }}
              >
                Load
              </button>
            </div>
            {docStatus.state === "idle" && <p style={mutedTextStyle}>No source summary loaded.</p>}
            {docStatus.state === "loading" && <p style={mutedTextStyle}>Loading sources...</p>}
            {docStatus.state === "error" && (
              <p data-testid="doc-summary-error" role="alert" style={errorTextStyle}>
                {docStatus.message}
              </p>
            )}
            {docStatus.state === "ready" && (
              <div data-testid="doc-summary" style={{ display: "grid", gap: 8 }}>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Pill tone="ghost">sources {docStatus.summary.sources.length}</Pill>
                  <Pill tone="ghost">spans {docStatus.summary.spans.length}</Pill>
                  <Pill tone="ghost">claims {docStatus.summary.claims.length}</Pill>
                </div>
                {docStatus.summary.sources.length === 0 ? (
                  <p data-testid="doc-summary-empty" style={mutedTextStyle}>No recorded sources.</p>
                ) : (
                  <div style={{ display: "grid", gap: 7 }}>
                    {docStatus.summary.sources.slice(0, 6).map((source) => (
                      <div
                        key={source.source_ref}
                        data-testid="doc-source"
                        style={{
                          border: "1px solid var(--desk-border)",
                          borderRadius: "var(--desk-radius-sm)",
                          padding: 8,
                          display: "grid",
                          gap: 5,
                        }}
                      >
                        <strong style={{ color: "var(--desk-text)", fontSize: 11.5, overflowWrap: "anywhere" }}>
                          {source.source_ref}
                        </strong>
                        <span style={{ color: "var(--desk-text-muted)", fontSize: 11, overflowWrap: "anywhere" }}>
                          {source.parser_sandbox_ref ?? "parser_sandbox:none"}
                        </span>
                        <span style={{ color: "var(--desk-text-faint)", fontSize: 10.5, overflowWrap: "anywhere" }}>
                          {source.mime_magic_check_ref ?? "mime:none"}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div style={{ borderTop: "1px solid var(--desk-border)", paddingTop: 10, display: "grid", gap: 8 }}>
              <div style={{ color: "var(--desk-text)", fontSize: 12, fontWeight: 700 }}>Parser upload</div>
              <input
                data-testid="doc-upload-file"
                type="file"
                accept=".md,.markdown,.txt,.rst,.pdf,.html,.htm"
                onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
                style={{ ...inputStyle, padding: 6 }}
              />
              <label style={labelStyle}>
                <span>asset_ref</span>
                <input
                  data-testid="doc-upload-asset"
                  value={uploadAssetRef}
                  onChange={(event) => setUploadAssetRef(event.target.value)}
                  placeholder={visibleAssetRefs[0] ?? ""}
                  style={inputStyle}
                />
              </label>
              <label style={labelStyle}>
                <span>license_rights_ref</span>
                <input
                  data-testid="doc-upload-rights"
                  value={uploadRightsRef}
                  onChange={(event) => setUploadRightsRef(event.target.value)}
                  style={inputStyle}
                />
              </label>
              <label style={labelStyle}>
                <span>source_url</span>
                <input
                  data-testid="doc-upload-source-url"
                  value={uploadSourceUrl}
                  onChange={(event) => setUploadSourceUrl(event.target.value)}
                  style={inputStyle}
                />
              </label>
              <label style={labelStyle}>
                <span>allowed_url_hosts</span>
                <input
                  data-testid="doc-upload-hosts"
                  value={uploadAllowedHosts}
                  onChange={(event) => setUploadAllowedHosts(event.target.value)}
                  style={inputStyle}
                />
              </label>
              <button
                data-testid="doc-upload-submit"
                type="button"
                onClick={uploadDocument}
                disabled={uploadStatus.state === "loading"}
                style={{
                  background: "var(--desk-accent)",
                  border: "1px solid var(--desk-border)",
                  color: "var(--desk-accent-ink)",
                  borderRadius: "var(--desk-radius-sm)",
                  fontFamily: "inherit",
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "7px 10px",
                  cursor: uploadStatus.state === "loading" ? "wait" : "pointer",
                }}
              >
                Upload
              </button>
              {uploadStatus.state === "loading" && <p style={mutedTextStyle}>Uploading...</p>}
              {uploadStatus.state === "error" && (
                <p data-testid="doc-upload-error" role="alert" style={errorTextStyle}>
                  {uploadStatus.message}
                </p>
              )}
              {uploadStatus.state === "ready" && (
                <div data-testid="doc-upload-result" style={{ display: "grid", gap: 5, fontSize: 11 }}>
                  <span style={{ color: "var(--desk-text-muted)", overflowWrap: "anywhere" }}>
                    {uploadStatus.result.source_ref}
                  </span>
                  <span style={{ color: "var(--desk-text-faint)", overflowWrap: "anywhere" }}>
                    {uploadStatus.result.mime_magic_check_ref}
                  </span>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <Pill tone="ghost">spans {uploadStatus.result.span_refs.length}</Pill>
                    <Pill tone="ghost">rag {uploadStatus.result.rag_document_ids.length}</Pill>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      <section style={{ ...sectionStyle, minWidth: 0 }}>
        <div style={sectionHeaderStyle}>
          <span>Candidate context</span>
          <div style={{ flex: 1 }} />
          {status.state === "ready" && <Pill tone="info">{status.hits.length}</Pill>}
        </div>
        <div style={{ ...sectionBodyStyle, display: "grid", gap: 10 }}>
          {status.state === "idle" && <p style={mutedTextStyle}>No query run.</p>}
          {status.state === "loading" && <p style={mutedTextStyle}>Searching...</p>}
          {status.state === "error" && (
            <p data-testid="rag-error" role="alert" style={errorTextStyle}>
              {status.message}
            </p>
          )}
          {status.state === "ready" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <Pill tone="ghost" title={status.endpoint}>
                  {status.endpoint.endsWith("vector_search") ? "sparse vector" : "lexical"}
                </Pill>
                <Pill tone="ghost">candidate_context</Pill>
                {status.usageIds.length > 0 && <Pill tone="warning">usage {status.usageIds.length}</Pill>}
              </div>
              {status.hits.length === 0 ? (
                <p data-testid="rag-empty" style={mutedTextStyle}>No authorized candidate context.</p>
              ) : (
                <div style={{ display: "grid", gap: 9 }}>
                  {status.hits.map((hit) => (
                    <article
                      key={`${hit.source_id}:${hit.version}:${hit.asset_ref}`}
                      data-testid="rag-hit"
                      style={{
                        border: "1px solid var(--desk-border)",
                        borderRadius: "var(--desk-radius-sm)",
                        padding: 10,
                        background: "var(--desk-canvas)",
                        display: "grid",
                        gap: 7,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                        <strong style={{ color: "var(--desk-text)", fontSize: 12.5 }}>{hit.title}</strong>
                        <Pill tone="ghost">{short(hit.source_id)}</Pill>
                        <Pill tone="ghost">{hit.version}</Pill>
                        <Pill tone="info">{scoreLabel(hit.score)}</Pill>
                      </div>
                      <p style={{ margin: 0, color: "var(--desk-text-muted)", fontSize: 12, lineHeight: 1.55 }}>
                        {hit.snippet}
                      </p>
                      <div style={{ display: "grid", gridTemplateColumns: "100px minmax(0, 1fr)", gap: 6, fontSize: 11 }}>
                        <span style={{ color: "var(--desk-text-faint)" }}>asset_ref</span>
                        <span style={{ color: "var(--desk-text-muted)", overflowWrap: "anywhere" }}>{hit.asset_ref}</span>
                        <span style={{ color: "var(--desk-text-faint)" }}>projection</span>
                        <span style={{ color: "var(--desk-text-muted)" }}>{hit.projection}</span>
                        <span style={{ color: "var(--desk-text-faint)" }}>role</span>
                        <span style={{ color: "var(--desk-text-muted)" }}>{hit.context_role}</span>
                        <span style={{ color: "var(--desk-text-faint)" }}>label</span>
                        <span style={{ color: "var(--desk-text-muted)" }}>{hit.evidence_label}</span>
                        <span style={{ color: "var(--desk-text-faint)" }}>applicability</span>
                        <span style={{ color: "var(--desk-text-muted)", overflowWrap: "anywhere" }}>
                          {hit.applicability}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
