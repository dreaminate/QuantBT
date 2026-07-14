/**
 * DS-2 · LLM Provider 配置页（接已有后端 POST /api/llm/configure + GET /api/llm/status）。
 *
 * 范围（复用单一源，绝不另造端点 / 不自实现 OAuth）：
 *   1. 选 provider（anthropic / openai / qwen / custom）+ 填 api_key / base_url / model → configure。
 *   2. **Hermes 预设**（Fork1）：一次性把 provider 切成 custom 并预填 `http://localhost:<port>/v1`，
 *      引导用户跑 Hermes 等本地 OAuth 代理、用 Claude Code/Codex 订阅额度——本页只配 OpenAI 兼容端点，
 *      OAuth 全程在 Hermes 侧，QuantBT 不碰 token。
 *   3. GET /api/llm/status 实时回显每个 provider 是否就绪（不回显 key）。
 *
 * 诚实状态（§3 不假绿灯）：configure 成功/失败都如实呈现后端响应；custom 缺 base_url/model 前端先拦，
 * 与后端 400 口径一致；不把「已写入 keystore」伪装成「已连通真模型」（连通要去测试连接）。
 */

import { useCallback, useEffect, useState } from "react";
import { authFetch, getStoredUser } from "../lib/auth";

type ProviderName = "anthropic" | "openai" | "qwen" | "custom";

interface ProviderStatus {
  provider: string;
  configured: boolean;
  base_url?: string;
  model?: string;
  default_model?: string;
  has_env_key?: boolean;
  settings_managed?: boolean;
  secret_ref?: string;
  credential_pool_ref?: string;
  routing_policy_ref?: string;
  auth_status?: string;
}

interface ConnectionTestResult {
  provider: string;
  ok: boolean;
  msg: string;
}

interface SettingsLLMProvider {
  provider_id: string;
  provider_type?: string;
  model_profiles?: string[];
  capability_tags?: string[];
  allowed_roles?: string[];
  allowed_desks?: string[];
  health_status?: string;
  quota_status?: string;
  auth_refs?: string[];
}

interface LLMProviderHealthSnapshot {
  snapshot_ref: string;
  provider_id: string;
  auth_ref: string;
  checked_at: string;
  checker_ref: string;
  health_status: string;
  quota_status: string;
  latency_ms: number;
  response_hash: string;
  capability_refs?: string[];
  evidence_refs?: string[];
  error_code?: string | null;
  snapshot_hash?: string;
}

interface HealthSnapshotForm {
  providerId: string;
  authRef: string;
  checkerRef: string;
  healthStatus: "ok" | "degraded" | "down" | "unknown";
  quotaStatus: "ok" | "limited" | "exhausted" | "unknown";
  latencyMs: string;
  responseHash: string;
  capabilityRefs: string;
  evidenceRefs: string;
  errorCode: string;
}

/** Hermes 本地代理默认端口（用户跑 Hermes 后 QuantBT 指这里；可在表单改）。 */
const HERMES_DEFAULT_PORT = 8787;
const HERMES_BASE_URL = `http://localhost:${HERMES_DEFAULT_PORT}/v1`;
/** Hermes 经 Claude Code 订阅常见的模型别名（占位引导，用户按自己 Hermes 配置改）。 */
const HERMES_MODEL_HINT = "claude-sonnet-4.5";

const PROVIDER_LABELS: Record<ProviderName, string> = {
  anthropic: "Anthropic（Claude · 官方 API key）",
  openai: "OpenAI（GPT · 官方 API key）",
  qwen: "Qwen（通义千问 · API key）",
  custom: "Custom（OpenAI 兼容端点 · 含 Hermes 本地代理 / Ollama）",
};

function splitRefs(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((ref) => ref.trim())
    .filter(Boolean);
}

function snapshotRefFor(providerId: string): string {
  return `llm_health:${providerId}:${Date.now()}`;
}

export function LLMSettingsPage() {
  const user = getStoredUser();

  const [provider, setProvider] = useState<ProviderName>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");

  const [statuses, setStatuses] = useState<ProviderStatus[]>([]);
  const [saving, setSaving] = useState(false);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  // 诚实回执：成功 / 失败都如实显示（不假绿灯）。
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [settingsProviders, setSettingsProviders] = useState<SettingsLLMProvider[]>([]);
  const [healthSnapshots, setHealthSnapshots] = useState<LLMProviderHealthSnapshot[]>([]);
  const [settingsSummaryError, setSettingsSummaryError] = useState<string | null>(null);
  const [recordingSnapshot, setRecordingSnapshot] = useState(false);
  const [snapshotResult, setSnapshotResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [snapshotForm, setSnapshotForm] = useState<HealthSnapshotForm>({
    providerId: "",
    authRef: "",
    checkerRef: "checker:settings-llm-manual",
    healthStatus: "ok",
    quotaStatus: "ok",
    latencyMs: "",
    responseHash: "",
    capabilityRefs: "",
    evidenceRefs: "",
    errorCode: "",
  });

  const isCustom = provider === "custom";
  // custom 必须同时填 base_url + model（与后端 400 口径一致，前端先拦）。
  const customIncomplete = isCustom && !(baseUrl.trim() && model.trim());
  const selectedSettingsProvider =
    settingsProviders.find((record) => record.provider_id === snapshotForm.providerId) ?? null;
  const selectedAuthRefs = selectedSettingsProvider?.auth_refs ?? [];
  const healthSnapshotIncomplete =
    !snapshotForm.providerId ||
    !snapshotForm.authRef ||
    !snapshotForm.checkerRef.trim() ||
    !snapshotForm.responseHash.trim();

  const loadStatus = useCallback(() => {
    // 走 authFetch（与 configure 同口径）：/api/llm/status 即便日后加鉴权也不漏。
    authFetch("/api/llm/status")
      .then((r) => r.json())
      .then((j) => {
        const list = Array.isArray(j) ? j : j.providers || [];
        setStatuses(list);
      })
      .catch(() => {
        /* best-effort：离线静默，不伪造状态 */
      });
  }, []);

  const loadSettingsSummary = useCallback(() => {
    authFetch("/api/research-os/settings/summary")
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(String(body.detail || `HTTP ${r.status}`));
        }
        return r.json();
      })
      .then((j) => {
        const providers = Array.isArray(j.llm_providers) ? j.llm_providers : [];
        const snapshots = Array.isArray(j.llm_provider_health_snapshots)
          ? j.llm_provider_health_snapshots
          : [];
        setSettingsProviders(providers);
        setHealthSnapshots(snapshots);
        setSettingsSummaryError(null);
        setSnapshotForm((current) => {
          const currentProvider =
            providers.find((record: SettingsLLMProvider) => record.provider_id === current.providerId) ??
            providers[0] ??
            null;
          const providerId = currentProvider?.provider_id ?? "";
          const authRefs = currentProvider?.auth_refs ?? [];
          const authRef = authRefs.includes(current.authRef) ? current.authRef : authRefs[0] ?? "";
          return { ...current, providerId, authRef };
        });
      })
      .catch((e) => {
        setSettingsSummaryError(String(e));
      });
  }, []);

  useEffect(() => {
    loadStatus();
    loadSettingsSummary();
  }, [loadStatus, loadSettingsSummary]);

  /** Hermes 预设：切 custom + 预填本地代理 base_url + 模型占位（引导用订阅额度）。 */
  const applyHermesPreset = useCallback(() => {
    setProvider("custom");
    setBaseUrl(HERMES_BASE_URL);
    setModel((m) => m.trim() || HERMES_MODEL_HINT);
    // Hermes 走 OAuth，下游不校验 key；给个占位让后端的「非 custom 才必填 key」逻辑无碍。
    setApiKey((k) => k.trim() || "hermes");
    setResult(null);
  }, []);

  const submit = useCallback(async () => {
    setResult(null);
    if (provider !== "custom" && !apiKey.trim()) {
      setResult({ ok: false, msg: `${provider} 必须填 api_key` });
      return;
    }
    if (customIncomplete) {
      setResult({ ok: false, msg: "custom 必须同时填 base_url 和 model" });
      return;
    }
    setSaving(true);
    try {
      const res = await authFetch("/api/llm/configure", {
        method: "POST",
        body: JSON.stringify({
          provider,
          api_key: apiKey.trim(),
          base_url: baseUrl.trim(),
          model: model.trim(),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        const refs = body.settings_refs || {};
        const refText = refs.secret_ref ? `，SecretRef=${refs.secret_ref}` : "";
        // 诚实口径：只确认「配置已写入」，不声称「已连通真模型」（连通要去测试连接）。
        setResult({
          ok: true,
          msg: `已写入配置：provider=${body.configured ?? provider}${
            body.model ? `，model=${body.model}` : ""
          }${refText}。配置已存 keystore 并登记 Settings metadata；是否真连通请点本页 provider 卡片里的测试连接。`,
        });
        loadStatus();
        loadSettingsSummary();
      } else {
        const detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail ?? body);
        setResult({ ok: false, msg: `配置失败 (${res.status})：${detail}` });
      }
    } catch (e) {
      setResult({ ok: false, msg: `配置失败：${String(e)}` });
    } finally {
      setSaving(false);
    }
  }, [provider, apiKey, baseUrl, model, customIncomplete, loadStatus, loadSettingsSummary]);

  const testConnection = useCallback(
    async (targetProvider: string) => {
      setTestingProvider(targetProvider);
      setTestResult({ provider: targetProvider, ok: false, msg: "连接测试中…" });
      try {
        const res = await authFetch("/api/llm/test", {
          method: "POST",
          body: JSON.stringify({ provider: targetProvider, ping: "回我一句 ok" }),
        });
        const body = await res.json().catch(() => ({}));
        if (res.ok && body.ok) {
          setTestResult({
            provider: body.provider ?? targetProvider,
            ok: true,
            msg: (body.reply_preview || "").slice(0, 120) || "ok",
          });
        } else {
          const detail =
            typeof body.error === "string"
              ? body.error
              : typeof body.detail === "string"
                ? body.detail
                : JSON.stringify(body.detail ?? body);
          setTestResult({
            provider: body.provider ?? targetProvider,
            ok: false,
            msg: detail || `HTTP ${res.status}`,
          });
        }
      } catch (e) {
        setTestResult({ provider: targetProvider, ok: false, msg: String(e) });
      } finally {
        setTestingProvider(null);
        loadStatus();
      }
    },
    [loadStatus],
  );

  const recordHealthSnapshot = useCallback(async () => {
    setSnapshotResult(null);
    if (!snapshotForm.providerId || !snapshotForm.authRef) {
      setSnapshotResult({ ok: false, msg: "缺 Settings provider 或 auth_ref，不能记录 health snapshot" });
      return;
    }
    if (!snapshotForm.checkerRef.trim()) {
      setSnapshotResult({ ok: false, msg: "checker_ref 必填" });
      return;
    }
    if (!snapshotForm.responseHash.trim()) {
      setSnapshotResult({ ok: false, msg: "response_hash 必填；只能填 hash/ref，不粘贴 provider 原始响应" });
      return;
    }
    const latencyMs = snapshotForm.latencyMs.trim()
      ? Number.parseInt(snapshotForm.latencyMs.trim(), 10)
      : 0;
    if (!Number.isFinite(latencyMs) || latencyMs < 0) {
      setSnapshotResult({ ok: false, msg: "latency_ms 不能为负数" });
      return;
    }

    const payload: Record<string, unknown> = {
      snapshot_ref: snapshotRefFor(snapshotForm.providerId),
      provider_id: snapshotForm.providerId,
      auth_ref: snapshotForm.authRef,
      checked_at: new Date().toISOString(),
      checker_ref: snapshotForm.checkerRef.trim(),
      health_status: snapshotForm.healthStatus,
      quota_status: snapshotForm.quotaStatus,
      latency_ms: latencyMs,
      response_hash: snapshotForm.responseHash.trim(),
      capability_refs: splitRefs(snapshotForm.capabilityRefs),
      evidence_refs: splitRefs(snapshotForm.evidenceRefs),
    };
    if (snapshotForm.errorCode.trim()) {
      payload.error_code = snapshotForm.errorCode.trim();
    }

    setRecordingSnapshot(true);
    try {
      const res = await authFetch("/api/research-os/settings/llm_provider_health_snapshots", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail ?? body);
        setSnapshotResult({ ok: false, msg: `记录失败 (${res.status})：${detail}` });
        return;
      }
      setSnapshotResult({
        ok: true,
        msg: `snapshot 已记录：${body.snapshot_ref || payload.snapshot_ref}，snapshot_hash=${
          body.snapshot_hash || "—"
        }`,
      });
      loadSettingsSummary();
    } catch (e) {
      setSnapshotResult({ ok: false, msg: `记录失败：${String(e)}` });
    } finally {
      setRecordingSnapshot(false);
    }
  }, [snapshotForm, loadSettingsSummary]);

  if (!user) {
    return (
      <div className="cc-card">
        <h2>需要登录</h2>
        <p>配置 LLM provider 需先登录。</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 900 }}>
      <h1>模型连接配置</h1>
      <p className="cc-dim" style={{ fontSize: 13, margin: 0 }}>
        填一个 LLM provider，研究执行台才会用真实模型参与意图结构化和候选实现。没填任何 provider
        时真实流会明确返回 NoLLMConfigured，不会静默回退到开发期模拟模型。需要演示时必须显式进入
        DEMO / 测试路径。
      </p>

      {/* === Hermes 预设（Fork1：用订阅额度，经本地 OAuth 代理）=== */}
      <section className="cc-card" data-hermes-preset>
        <h2 style={{ marginTop: 0 }}>用订阅额度（Hermes 本地 OAuth 代理）</h2>
        <p className="cc-dim" style={{ fontSize: 13 }}>
          已有 Claude Code / Codex 订阅？运行一个本地 OAuth 代理（如 Hermes），把订阅额度暴露成 OpenAI
          兼容端点，QuantBT 指向它即可——无需把 API key 交给本应用，OAuth 全程在代理侧。
        </p>
        <button
          type="button"
          className="cc-btn cc-btn--accent"
          data-hermes-apply
          onClick={applyHermesPreset}
        >
          套用 Hermes 预设（custom + {HERMES_BASE_URL}）
        </button>
        <p className="cc-dim" style={{ fontSize: 12, marginTop: 8 }}>
          套用后下方表单会切成 custom 并预填本地代理地址；按你的 Hermes 端口 / 模型别名修改后保存。
          完整步骤见仓库文档 <code>docs/hermes-subscription-proxy.md</code>。
        </p>
      </section>

      {/* === provider 配置表单 === */}
      <section className="cc-card">
        <h2 style={{ marginTop: 0 }}>Provider 配置</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 13 }}>Provider</span>
            <select
              className="cc-input"
              data-provider-select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value as ProviderName);
                setResult(null);
              }}
              style={{ padding: 8 }}
            >
              {(Object.keys(PROVIDER_LABELS) as ProviderName[]).map((p) => (
                <option key={p} value={p}>
                  {PROVIDER_LABELS[p]}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 13 }}>
              API key{isCustom ? "（custom 下可填代理占位，如 hermes / ollama）" : "（必填）"}
            </span>
            <input
              className="cc-input"
              data-api-key
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={isCustom ? "hermes" : "sk-..."}
              style={{ padding: 8 }}
            />
          </label>

          {isCustom && (
            <>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 13 }}>Base URL（OpenAI 兼容端点 · 必填）</span>
                <input
                  className="cc-input"
                  data-base-url
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={HERMES_BASE_URL}
                  style={{ padding: 8, fontFamily: "monospace" }}
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 13 }}>Model（必填）</span>
                <input
                  className="cc-input"
                  data-model
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder={HERMES_MODEL_HINT}
                  style={{ padding: 8, fontFamily: "monospace" }}
                />
              </label>
            </>
          )}

          <div className="cc-row" style={{ gap: 8, alignItems: "center" }}>
            <button
              type="button"
              className="cc-btn cc-btn--accent"
              data-configure-submit
              disabled={saving || customIncomplete}
              onClick={submit}
            >
              {saving ? "保存中…" : "保存配置"}
            </button>
            {customIncomplete && (
              <span className="cc-dim" style={{ fontSize: 12 }}>
                custom 须同时填 base_url 和 model
              </span>
            )}
          </div>

          {result && (
            <div
              data-configure-result
              className={`cc-chip ${result.ok ? "cc-chip--success" : "cc-chip--danger"}`}
              style={{ padding: "8px 12px", whiteSpace: "normal", lineHeight: 1.5 }}
            >
              {result.ok ? "✓ " : "✗ "}
              {result.msg}
            </div>
          )}
        </div>
      </section>

      {/* === provider health/quota snapshot（refs/hash-only 账本写入）=== */}
      <section className="cc-card" data-provider-health-snapshot-panel>
        <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Provider health snapshot</h2>
          <button type="button" className="cc-btn cc-btn--sm cc-btn--ghost" onClick={loadSettingsSummary}>
            ↻ 刷新
          </button>
        </div>
        <div className="cc-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 180, flex: "1 1 180px" }}>
            <span style={{ fontSize: 13 }}>Settings provider</span>
            <select
              className="cc-input"
              data-health-provider-select
              value={snapshotForm.providerId}
              disabled={settingsProviders.length === 0}
              onChange={(e) => {
                const providerId = e.target.value;
                const nextProvider = settingsProviders.find((record) => record.provider_id === providerId);
                setSnapshotForm((current) => ({
                  ...current,
                  providerId,
                  authRef: nextProvider?.auth_refs?.[0] ?? "",
                }));
                setSnapshotResult(null);
              }}
              style={{ padding: 8 }}
            >
              {settingsProviders.map((record) => (
                <option key={record.provider_id} value={record.provider_id}>
                  {record.provider_id}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 220, flex: "1 1 220px" }}>
            <span style={{ fontSize: 13 }}>auth_ref</span>
            <select
              className="cc-input"
              data-health-auth-ref
              value={snapshotForm.authRef}
              disabled={selectedAuthRefs.length === 0}
              onChange={(e) => {
                setSnapshotForm((current) => ({ ...current, authRef: e.target.value }));
                setSnapshotResult(null);
              }}
              style={{ padding: 8, fontFamily: "monospace" }}
            >
              {selectedAuthRefs.map((ref) => (
                <option key={ref} value={ref}>
                  {ref}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140, flex: "1 1 140px" }}>
            <span style={{ fontSize: 13 }}>health</span>
            <select
              className="cc-input"
              data-health-status
              value={snapshotForm.healthStatus}
              onChange={(e) =>
                setSnapshotForm((current) => ({
                  ...current,
                  healthStatus: e.target.value as HealthSnapshotForm["healthStatus"],
                }))
              }
              style={{ padding: 8 }}
            >
              <option value="ok">ok</option>
              <option value="degraded">degraded</option>
              <option value="down">down</option>
              <option value="unknown">unknown</option>
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140, flex: "1 1 140px" }}>
            <span style={{ fontSize: 13 }}>quota</span>
            <select
              className="cc-input"
              data-quota-status
              value={snapshotForm.quotaStatus}
              onChange={(e) =>
                setSnapshotForm((current) => ({
                  ...current,
                  quotaStatus: e.target.value as HealthSnapshotForm["quotaStatus"],
                }))
              }
              style={{ padding: 8 }}
            >
              <option value="ok">ok</option>
              <option value="limited">limited</option>
              <option value="exhausted">exhausted</option>
              <option value="unknown">unknown</option>
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 120, flex: "1 1 120px" }}>
            <span style={{ fontSize: 13 }}>latency_ms</span>
            <input
              className="cc-input"
              data-health-latency
              type="number"
              min={0}
              value={snapshotForm.latencyMs}
              onChange={(e) => setSnapshotForm((current) => ({ ...current, latencyMs: e.target.value }))}
              placeholder="0"
              style={{ padding: 8 }}
            />
          </label>
        </div>

        <div className="cc-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start", marginTop: 10 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 260, flex: "2 1 260px" }}>
            <span style={{ fontSize: 13 }}>response_hash</span>
            <input
              className="cc-input"
              data-health-response-hash
              type="text"
              value={snapshotForm.responseHash}
              onChange={(e) => setSnapshotForm((current) => ({ ...current, responseHash: e.target.value }))}
              placeholder="sha16:..."
              style={{ padding: 8, fontFamily: "monospace" }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 220, flex: "1 1 220px" }}>
            <span style={{ fontSize: 13 }}>checker_ref</span>
            <input
              className="cc-input"
              data-health-checker-ref
              type="text"
              value={snapshotForm.checkerRef}
              onChange={(e) => setSnapshotForm((current) => ({ ...current, checkerRef: e.target.value }))}
              style={{ padding: 8, fontFamily: "monospace" }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 180, flex: "1 1 180px" }}>
            <span style={{ fontSize: 13 }}>error_code</span>
            <input
              className="cc-input"
              data-health-error-code
              type="text"
              value={snapshotForm.errorCode}
              onChange={(e) => setSnapshotForm((current) => ({ ...current, errorCode: e.target.value }))}
              placeholder="optional"
              style={{ padding: 8, fontFamily: "monospace" }}
            />
          </label>
        </div>

        <div className="cc-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start", marginTop: 10 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 260, flex: "1 1 260px" }}>
            <span style={{ fontSize: 13 }}>capability_refs</span>
            <textarea
              className="cc-input"
              data-health-capability-refs
              value={snapshotForm.capabilityRefs}
              onChange={(e) => setSnapshotForm((current) => ({ ...current, capabilityRefs: e.target.value }))}
              placeholder="capability:tool_calling, capability:structured_output"
              style={{ padding: 8, minHeight: 64, fontFamily: "monospace" }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 260, flex: "1 1 260px" }}>
            <span style={{ fontSize: 13 }}>evidence_refs</span>
            <textarea
              className="cc-input"
              data-health-evidence-refs
              value={snapshotForm.evidenceRefs}
              onChange={(e) => setSnapshotForm((current) => ({ ...current, evidenceRefs: e.target.value }))}
              placeholder="evidence:llm-health-check"
              style={{ padding: 8, minHeight: 64, fontFamily: "monospace" }}
            />
          </label>
        </div>

        <div className="cc-row" style={{ gap: 8, alignItems: "center", marginTop: 10 }}>
          <button
            type="button"
            className="cc-btn cc-btn--accent"
            data-health-snapshot-submit
            disabled={recordingSnapshot || healthSnapshotIncomplete}
            onClick={recordHealthSnapshot}
          >
            {recordingSnapshot ? "记录中…" : "记录 snapshot"}
          </button>
          {healthSnapshotIncomplete && (
            <span className="cc-dim" style={{ fontSize: 12 }}>
              需要 Settings provider、auth_ref、checker_ref 和 response_hash
            </span>
          )}
        </div>

        {settingsSummaryError && (
          <div className="cc-chip cc-chip--danger" data-health-summary-error style={{ marginTop: 10 }}>
            ✗ Settings summary: {settingsSummaryError}
          </div>
        )}
        {snapshotResult && (
          <div
            data-health-snapshot-result
            className={`cc-chip ${snapshotResult.ok ? "cc-chip--success" : "cc-chip--danger"}`}
            style={{ padding: "8px 12px", whiteSpace: "normal", lineHeight: 1.5, marginTop: 10 }}
          >
            {snapshotResult.ok ? "✓ " : "✗ "}
            {snapshotResult.msg}
          </div>
        )}

        <div className="cc-row" style={{ flexWrap: "wrap", gap: 8, marginTop: 10 }} data-health-snapshot-list>
          {healthSnapshots.slice(0, 6).map((snapshot) => (
            <span key={snapshot.snapshot_ref} className="cc-chip" style={{ lineHeight: 1.5 }}>
              {snapshot.provider_id} · {snapshot.health_status}/{snapshot.quota_status} ·{" "}
              <code>{snapshot.snapshot_hash || snapshot.response_hash}</code>
            </span>
          ))}
          {healthSnapshots.length === 0 && (
            <span className="cc-dim" style={{ fontSize: 12 }}>
              暂无 health snapshot
            </span>
          )}
        </div>
      </section>

      {/* === 当前各 provider 状态（GET /api/llm/status，不回显 key）=== */}
      <section className="cc-card">
        <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>当前 provider 状态</h2>
          <button type="button" className="cc-btn cc-btn--sm cc-btn--ghost" onClick={loadStatus}>
            ↻ 刷新
          </button>
        </div>
        <div className="cc-row" style={{ flexWrap: "wrap", gap: 10 }}>
          {statuses.map((s) => (
            <div
              key={s.provider}
              className="cc-card"
              data-provider-status={s.provider}
              style={{ padding: 10, minWidth: 200, flex: "1 1 200px" }}
            >
              <div className="cc-row" style={{ justifyContent: "space-between" }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>{s.provider}</span>
                <span className={`cc-chip ${s.configured ? "cc-chip--success" : ""}`}>
                  {s.configured ? "已配置" : "未配置"}
                </span>
              </div>
              <div className="cc-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                <span className={`cc-chip ${s.settings_managed ? "cc-chip--success" : ""}`}>
                  {s.settings_managed ? "Gateway 管理" : "Settings metadata 缺失"}
                </span>
                <span className={`cc-chip ${s.auth_status === "active" ? "cc-chip--success" : ""}`}>
                  auth: {s.auth_status || "unknown"}
                </span>
              </div>
              <div className="cc-dim" style={{ fontSize: 11, marginTop: 4 }}>
                model: {s.model || s.default_model || "—"}
              </div>
              {s.base_url && (
                <div className="cc-dim" style={{ fontSize: 11, fontFamily: "monospace" }}>
                  {s.base_url}
                </div>
              )}
              <div className="cc-dim" style={{ fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
                <div data-secret-ref={s.provider}>secret: <code>{s.secret_ref || "—"}</code></div>
                <div data-pool-ref={s.provider}>pool: <code>{s.credential_pool_ref || "—"}</code></div>
                <div data-policy-ref={s.provider}>policy: <code>{s.routing_policy_ref || "—"}</code></div>
              </div>
              <button
                type="button"
                className="cc-btn cc-btn--sm"
                data-test-provider={s.provider}
                disabled={!s.configured || testingProvider === s.provider}
                onClick={() => testConnection(s.provider)}
                style={{ marginTop: 8, width: "100%" }}
              >
                {testingProvider === s.provider ? "测试中…" : "测试连接"}
              </button>
            </div>
          ))}
          {statuses.length === 0 && (
            <span className="cc-dim" style={{ fontSize: 12 }}>
              无 provider 状态（/api/llm/status 空或离线）
            </span>
          )}
        </div>
        {testResult && (
          <pre
            className="cc-code"
            data-connection-test-result
            style={{ marginTop: 12, fontSize: 11, whiteSpace: "pre-wrap" }}
          >
            {testResult.ok ? "✓" : "✗"} {testResult.provider}: {testResult.msg}
          </pre>
        )}
        <p className="cc-dim" style={{ fontSize: 12, marginTop: 10 }}>
          「已配置」只表示 key/端点已写入；「Gateway 管理」表示有 SecretRef / Pool / Policy 元数据。
          测试连接只证明当前后端能按这些 refs 调到 provider，不等于 CI 或线上部署已生效。
        </p>
      </section>
    </div>
  );
}

export default LLMSettingsPage;
