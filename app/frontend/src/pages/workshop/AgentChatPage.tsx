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
 * Agent 工作台 · Codex 聊天气泡 + Claude Code 终端 sidebar
 * /agent
 */

export function AgentChatPage() {
  const [input, setInput] = useState("我想做 A股 周频 选股策略，回撤 20%。");
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
  useEffect(() => loadProviders(), []);

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
    setTestResult(`pinging ${provider}…`);
    try {
      const res = await fetch("/api/llm/test", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ provider, ping: "回我一句 ok" }),
      });
      const json = await res.json();
      setTestResult(
        json.ok
          ? `✓ ${json.provider}: ${(json.reply_preview || "").slice(0, 80)}`
          : `✗ ${json.provider}: ${json.error}`,
      );
    } catch (e) {
      setTestResult(`✗ ${e}`);
    }
  };

  const reloadSecrets = async () => {
    setTestResult("reloading secrets…");
    await fetch("/api/security/reload_secrets", { method: "POST" });
    loadProviders();
    setTestResult("✓ secrets reloaded");
  };

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">
            <span className="cc-prompt">$</span>agent
          </h1>
          <p className="cc-page-subtitle">
            13 工具 schema · reAct 状态机 · 真 LLM 多轮工具串联 · 5xx/timeout 自动指数退避重试。
          </p>
        </div>
      </div>

      {/* LLM provider 状态条 */}
      <section className="cc-card" style={{ marginBottom: 20 }}>
        <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <div className="cc-section-title">// llm providers</div>
          <button type="button" className="cc-btn cc-btn--sm cc-btn--ghost" onClick={reloadSecrets}>
            ↻ reload secrets
          </button>
        </div>
        <div className="cc-row" style={{ flexWrap: "wrap" }}>
          {providers.map((p) => (
            <div
              key={p.provider}
              className="cc-card"
              style={{
                padding: 10,
                minWidth: 220,
                flex: "1 1 220px",
                background: p.configured ? "var(--cc-accent-soft)" : "var(--cc-bg-soft)",
                borderColor: p.configured ? "var(--cc-accent-line)" : "var(--cc-border)",
              }}
            >
              <div className="cc-row" style={{ justifyContent: "space-between" }}>
                <span className="cc-mono" style={{ fontSize: 12 }}>{p.provider}</span>
                {p.configured ? (
                  <span className="cc-chip cc-chip--success">ready</span>
                ) : (
                  <span className="cc-chip">dim</span>
                )}
              </div>
              <div className="cc-dim" style={{ fontSize: 11, marginTop: 4 }}>
                {p.model || p.default_model || "—"}
              </div>
              <div className="cc-dim cc-mono" style={{ fontSize: 10, marginTop: 2 }}>
                {p.base_url || "(default)"}
              </div>
              <button
                type="button"
                className="cc-btn cc-btn--sm"
                disabled={!p.configured}
                onClick={() => testLlm(p.provider)}
                style={{ marginTop: 8, width: "100%" }}
              >
                测试连接
              </button>
            </div>
          ))}
        </div>
        {testResult && (
          <pre className="cc-code" style={{ marginTop: 12, fontSize: 11 }}>
            {testResult}
          </pre>
        )}
      </section>

      {/* chat thread */}
      <section className="cc-chat-container">
        {steps.length === 0 ? (
          <div className="cc-card cc-dim" style={{ textAlign: "center", padding: 32 }}>
            还没对话。试试输入：<br />
            <em>"我想做 A股 周频 选股策略，回撤 20%"</em>
            <br />
            <em>"加密永续 BTC/ETH 趋势策略，允许做空，杠杆 3x"</em>
            <br />
            <em>"你能做什么"</em>
          </div>
        ) : (
          steps.map((s, idx) => <ChatMsg key={idx} step={s} />)
        )}
      </section>

      {/* input */}
      <section
        style={{
          position: "sticky",
          bottom: 0,
          background: "var(--cc-bg)",
          padding: "16px 0",
          marginTop: 24,
          borderTop: "1px solid var(--cc-border)",
        }}
      >
        <div className="cc-chat-container">
          <div className="cc-card" style={{ padding: 12 }}>
            <textarea
              className="cc-textarea"
              rows={3}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="跟 Agent 说任何事…"
              style={{ border: 0, padding: 0, background: "transparent" }}
            />
            <div className="cc-row" style={{ justifyContent: "space-between", marginTop: 8 }}>
              {error ? (
                <span className="cc-chip cc-chip--danger">{error}</span>
              ) : (
                <span className="cc-dim" style={{ fontSize: 11 }}>
                  ⌘+Enter 发送 · LLM 真模型走 keystore 选 provider · 永远 fallback DevLocalLLM
                </span>
              )}
              <button
                type="button"
                className="cc-btn cc-btn--accent"
                disabled={busy || !input.trim()}
                onClick={send}
              >
                {busy ? "运行中…" : "发送 →"}
              </button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function ChatMsg({ step }: { step: AgentStep }) {
  const cls =
    step.role === "user"
      ? "cc-chat-msg cc-chat-msg--user"
      : step.role === "tool"
        ? "cc-chat-msg cc-chat-msg--tool"
        : "cc-chat-msg cc-chat-msg--assistant";
  const avatar = step.role === "user" ? "U" : step.role === "tool" ? "T" : "A";
  return (
    <div className={cls}>
      <div className="cc-chat-avatar">{avatar}</div>
      <div className="cc-chat-body">
        <div className="cc-chat-role">{step.role}</div>
        <div className="cc-chat-content">{step.content || "（empty）"}</div>
        {step.tool_calls && step.tool_calls.length > 0 && (
          <div className="cc-chat-toolcalls">
            {step.tool_calls.map((c, i) => (
              <span key={i} className="cc-chip cc-chip--accent">
                ⇒ {c.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default AgentChatPage;
