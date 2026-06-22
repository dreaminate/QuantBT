/**
 * DS-2 · LLM Provider 配置页（接已有后端 POST /api/llm/configure + GET /api/llm/status）。
 *
 * 范围（复用单一源，绝不另造端点 / 不自实现 OAuth）：
 *   1. 选 provider（anthropic / openai / qwen / custom）+ 填 api_key / base_url / model → configure。
 *   2. **Hermes 预设**（Fork1）：一键把 provider 切成 custom 并预填 `http://localhost:<port>/v1`，
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

export function LLMSettingsPage() {
  const user = getStoredUser();

  const [provider, setProvider] = useState<ProviderName>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");

  const [statuses, setStatuses] = useState<ProviderStatus[]>([]);
  const [saving, setSaving] = useState(false);
  // 诚实回执：成功 / 失败都如实显示（不假绿灯）。
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const isCustom = provider === "custom";
  // custom 必须同时填 base_url + model（与后端 400 口径一致，前端先拦）。
  const customIncomplete = isCustom && !(baseUrl.trim() && model.trim());

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

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

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
        // 诚实口径：只确认「配置已写入」，不声称「已连通真模型」（连通要去测试连接）。
        setResult({
          ok: true,
          msg: `已写入配置：provider=${body.configured ?? provider}${
            body.model ? `，model=${body.model}` : ""
          }。配置已存 keystore；是否真连通请到「安全设置 · LLM Providers」点测试连接。`,
        });
        loadStatus();
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
  }, [provider, apiKey, baseUrl, model, customIncomplete, loadStatus]);

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
      <h1>LLM 配置 · 接通对话生成策略</h1>
      <p className="cc-dim" style={{ fontSize: 13, margin: 0 }}>
        填一个 LLM provider，Agent 工作台的「接真」对话才会用真模型组装策略。没填任何 provider
        时后端自动回退到开发期本地模型（DevLocalLLM）—— 能跑通流程，但能力有限。
      </p>

      {/* === Hermes 预设（Fork1：用订阅额度，经本地 OAuth 代理）=== */}
      <section className="cc-card" data-hermes-preset>
        <h2 style={{ marginTop: 0 }}>用订阅额度（Hermes 本地 OAuth 代理）</h2>
        <p className="cc-dim" style={{ fontSize: 13 }}>
          已有 Claude Code / Codex 订阅？跑一个本地 OAuth 代理（如 Hermes），把订阅额度暴露成 OpenAI
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
          套用后下方表单会切成 custom 并预填本地代理地址；按你的 Hermes 端口 / 模型别名改，再点保存。
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
                {s.configured ? (
                  <span className="cc-chip cc-chip--success">已配置</span>
                ) : (
                  <span className="cc-chip">未配置</span>
                )}
              </div>
              <div className="cc-dim" style={{ fontSize: 11, marginTop: 4 }}>
                model: {s.model || s.default_model || "—"}
              </div>
              {s.base_url && (
                <div className="cc-dim" style={{ fontSize: 11, fontFamily: "monospace" }}>
                  {s.base_url}
                </div>
              )}
            </div>
          ))}
          {statuses.length === 0 && (
            <span className="cc-dim" style={{ fontSize: 12 }}>
              无 provider 状态（/api/llm/status 空或离线）
            </span>
          )}
        </div>
        <p className="cc-dim" style={{ fontSize: 12, marginTop: 10 }}>
          「已配置」只表示 key/端点已写入；要验证真连通，去{" "}
          <a href="/settings/security">安全设置 · LLM Providers</a> 点「测试连接」。
        </p>
      </section>
    </div>
  );
}

export default LLMSettingsPage;
