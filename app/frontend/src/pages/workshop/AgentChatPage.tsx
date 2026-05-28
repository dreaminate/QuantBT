import { useEffect, useState } from "react";

interface AgentStep {
  role: string;
  content: string;
  tool_calls?: { name?: string; arguments?: string }[];
}

interface LLMProviderStatus {
  provider: string;
  configured: boolean;
  base_url: string;
  model: string;
  default_model?: string;
  has_env_key?: boolean;
}

/**
 * Agent 工作台 · 独立 SPA 页面
 * 路由：/agent
 */
export function AgentChatPage() {
  const [input, setInput] = useState("你能做什么");
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<LLMProviderStatus[]>([]);
  const [testResult, setTestResult] = useState<string | null>(null);

  const loadProviders = () => {
    fetch("/api/llm/status")
      .then((r) => r.json())
      .then(setProviders)
      .catch((e) => setError(String(e)));
  };
  useEffect(() => {
    loadProviders();
  }, []);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: input }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setSteps(json.steps || []);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const testLlm = async (provider: string) => {
    setTestResult(null);
    const res = await fetch("/api/llm/test", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider, ping: "回我一句 ok" }),
    });
    const json = await res.json();
    setTestResult(
      json.ok
        ? `✅ ${json.provider}: ${(json.reply_preview || "").slice(0, 80)}`
        : `❌ ${json.provider}: ${json.error}`,
    );
  };

  return (
    <div style={{ padding: 16 }}>
      <h2>Agent 工作台</h2>
      <div style={{ marginBottom: 16, padding: 12, background: "#f6f8fa", borderRadius: 6 }}>
        <strong>LLM provider 状态</strong>
        <ul style={{ marginTop: 8 }}>
          {providers.map((p) => (
            <li key={p.provider} style={{ marginBottom: 4 }}>
              <code>{p.provider}</code> ·{" "}
              {p.configured ? (
                <span style={{ color: "seagreen" }}>✓ 就绪</span>
              ) : (
                <span style={{ color: "#888" }}>未配置</span>
              )}
              {p.base_url && <span style={{ color: "#666" }}> · base={p.base_url}</span>}
              {p.model && <span style={{ color: "#666" }}> · model={p.model}</span>}
              <button
                type="button"
                style={{ marginLeft: 8 }}
                onClick={() => testLlm(p.provider)}
                disabled={!p.configured}
              >
                测试
              </button>
            </li>
          ))}
        </ul>
        {testResult && <pre style={{ marginTop: 8 }}>{testResult}</pre>}
        <div style={{ fontSize: 12, color: "#666" }}>
          编辑 <code>~/.quantbt/secrets.yaml</code> 然后{" "}
          <button
            type="button"
            onClick={() =>
              fetch("/api/security/reload_secrets", { method: "POST" })
                .then((r) => r.json())
                .then(() => loadProviders())
            }
          >
            热加载
          </button>
          ，或去「系统设置」表单填。
        </div>
      </div>
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        rows={3}
        style={{ width: "100%", maxWidth: 800 }}
      />
      <div style={{ marginTop: 8 }}>
        <button type="button" disabled={busy} onClick={send}>
          {busy ? "运行中…" : "发送"}
        </button>
      </div>
      {error && <pre style={{ color: "crimson" }}>{error}</pre>}
      <div style={{ marginTop: 12 }}>
        {steps.map((s, idx) => (
          <div
            key={idx}
            style={{
              marginBottom: 8,
              padding: 8,
              background: "#fafafa",
              borderLeft: "3px solid #888",
            }}
          >
            <strong>{s.role}</strong>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{s.content}</pre>
            {s.tool_calls && s.tool_calls.length > 0 && (
              <div style={{ fontSize: 12, color: "#555" }}>
                tool_calls: {s.tool_calls.map((c) => c.name).join(", ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default AgentChatPage;
