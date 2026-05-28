import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { authFetch, getStoredUser } from "../../lib/auth";

/**
 * v0.8.6 · Mode 2 教学型多轮 chat (/chat)
 *
 * - 左：thread 列表（按 updated_at 倒序）
 * - 中：当前 thread 消息流 + RAG hit 标记
 * - 右：active_run_id / active_strategy_id binding + market_mode selector
 * - 底部：输入框 (Enter 发送，Shift+Enter 换行)
 *
 * /chat?run=<run_id> 可直接绑 active_run_id 进入新 thread。
 */

interface ChatThread {
  thread_id: string;
  user_id: string | null;
  market_mode: string;
  active_run_id: string | null;
  active_strategy_id: string | null;
  title: string;
  state: string;
  created_at_utc: string;
  updated_at_utc: string;
}

interface ChatMessage {
  message_id: string;
  thread_id: string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  metadata: {
    rag_hits?: { kind: string; slug: string; title: string; score?: number }[];
    had_run_context?: boolean;
  };
  created_at_utc: string;
}

const MARKET_MODES = [
  { key: "ashare_research", label: "A股研究 (paper)" },
  { key: "binance_paper", label: "加密 paper" },
  { key: "binance_testnet", label: "Binance testnet" },
  { key: "binance_live", label: "Binance live (需 SafeKey)" },
];

export function Mode2ChatPage() {
  const me = getStoredUser();
  const [searchParams] = useSearchParams();
  const bindRunId = searchParams.get("run");
  const initialQuery = searchParams.get("q");

  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState(initialQuery ?? "");
  const [sending, setSending] = useState(false);
  const [marketMode, setMarketMode] = useState("ashare_research");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const autoOpenedRef = useRef(false);

  const reloadThreads = useCallback(async () => {
    if (!me) return;
    try {
      const r = await authFetch("/api/agent/chat/threads");
      const data = await r.json();
      setThreads(Array.isArray(data) ? data : []);
    } catch {
      setThreads([]);
    }
  }, [me]);

  const loadThread = useCallback(async (tid: string) => {
    try {
      const r = await authFetch(`/api/agent/chat/${tid}`);
      const data = await r.json();
      setActiveThread(data.thread);
      setMessages(data.messages || []);
    } catch {
      setActiveThread(null);
      setMessages([]);
    }
  }, []);

  useEffect(() => {
    reloadThreads();
  }, [reloadThreads]);

  // v0.9.x · 若 URL 带 ?run=&q= → 自动新建 thread + 填充 query (来自 CoachSuggestionBanner)
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (!me) return;
    if (!bindRunId && !initialQuery) return;
    autoOpenedRef.current = true;
    void (async () => {
      const body: Record<string, unknown> = { market_mode: marketMode };
      if (bindRunId) body.active_run_id = bindRunId;
      const r = await authFetch("/api/agent/chat/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (data.thread_id) {
        setActiveThreadId(data.thread_id);
        reloadThreads();
      }
    })();
  }, [me, bindRunId, initialQuery, marketMode, reloadThreads]);

  useEffect(() => {
    if (activeThreadId) loadThread(activeThreadId);
  }, [activeThreadId, loadThread]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const startNewThread = async () => {
    const body: Record<string, unknown> = { market_mode: marketMode };
    if (bindRunId) body.active_run_id = bindRunId;
    const r = await authFetch("/api/agent/chat/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.thread_id) {
      setActiveThreadId(data.thread_id);
      reloadThreads();
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || !activeThreadId || sending) return;
    setSending(true);
    const userText = input.trim();
    setInput("");
    // 乐观先渲染 user 消息
    const optimisticUser: ChatMessage = {
      message_id: "optimistic_user_" + Date.now(),
      thread_id: activeThreadId,
      role: "user",
      content: userText,
      metadata: {},
      created_at_utc: new Date().toISOString(),
    };
    setMessages((ms) => [...ms, optimisticUser]);

    // v0.9.8 · 真 SSE streaming
    const assistantId = "optimistic_assistant_" + Date.now();
    const optimisticAssistant: ChatMessage = {
      message_id: assistantId,
      thread_id: activeThreadId,
      role: "assistant",
      content: "",
      metadata: {},
      created_at_utc: new Date().toISOString(),
    };
    setMessages((ms) => [...ms, optimisticAssistant]);

    try {
      const token = localStorage.getItem("qb-token");
      const headers: Record<string, string> = {};
      if (token) headers["authorization"] = `Bearer ${token}`;
      const url = `/api/agent/chat/${activeThreadId}/stream?q=${encodeURIComponent(userText)}`;
      const res = await fetch(url, { headers });
      if (!res.ok || !res.body) {
        throw new Error(`SSE 启动失败: HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let ragHits: any[] = [];

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE 事件以 \n\n 分隔
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const evt of events) {
          if (!evt.trim()) continue;
          const lines = evt.split("\n");
          let eventName = "message";
          let dataStr = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) eventName = line.slice(7).trim();
            else if (line.startsWith("data: ")) dataStr += line.slice(6);
          }
          if (!dataStr) continue;
          try {
            const data = JSON.parse(dataStr);
            if (eventName === "rag") {
              ragHits = data.hits || [];
              setMessages((ms) => ms.map((m) =>
                m.message_id === assistantId
                  ? { ...m, metadata: { ...m.metadata, rag_hits: ragHits } }
                  : m,
              ));
            } else if (eventName === "done") {
              // 不动；最后 reloadThread 同步真正的 message_id
            } else if (data.chunk) {
              // 逐 token 拼接
              setMessages((ms) => ms.map((m) =>
                m.message_id === assistantId
                  ? { ...m, content: (m.content || "") + data.chunk }
                  : m,
              ));
            }
          } catch {
            // 单条 SSE 解析失败跳过
          }
        }
      }

      // 重新拉 thread 同步 server-side message_id
      await loadThread(activeThreadId);
    } catch (err) {
      // streaming 失败 fallback 到非流式
      try {
        await authFetch(`/api/agent/chat/${activeThreadId}/message`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ content: userText }),
        });
        await loadThread(activeThreadId);
      } catch {
        setMessages((ms) => ms.map((m) =>
          m.message_id === assistantId
            ? { ...m, content: `[流式失败] ${err}` }
            : m,
        ));
      }
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!me) {
    return (
      <div className="cc-card cc-dim" style={{ padding: 24 }}>
        请先登录后使用 Mode 2 教学型 agent。
      </div>
    );
  }

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// Mode 2 · 量化教练"}</h1>
          <div className="cc-soft">研究流程教练 + 风控副驾驶 · 多轮 Socratic · RAG glossary</div>
        </div>
        <div className="cc-page-actions">
          <select value={marketMode} onChange={(e) => setMarketMode(e.target.value)} className="cc-select cc-select--sm">
            {MARKET_MODES.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
          <button type="button" className="cc-btn cc-btn--accent" onClick={startNewThread}>+ 新对话</button>
        </div>
      </div>

      <div className="cc-row" style={{ alignItems: "stretch", gap: 12 }}>
        <aside className="cc-card" style={{ width: 240, padding: 12, flexShrink: 0, maxHeight: "75vh", overflow: "auto" }}>
          <div className="cc-section-title">历史对话 ({threads.length})</div>
          {threads.length === 0 ? (
            <div className="cc-dim" style={{ fontSize: 12 }}>无历史，点 + 开始新对话</div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {threads.map((t) => (
                <li key={t.thread_id} style={{ marginBottom: 4 }}>
                  <div
                    style={{
                      padding: "6px 8px",
                      borderRadius: 4,
                      cursor: "pointer",
                      background: activeThreadId === t.thread_id ? "var(--cc-bg-elev, rgba(255,255,255,0.05))" : "transparent",
                      fontSize: 12,
                    }}
                    onClick={() => setActiveThreadId(t.thread_id)}
                  >
                    <div className="cc-mono" style={{ fontSize: 11 }}>{t.title || t.thread_id.slice(0, 12)}</div>
                    <div className="cc-dim" style={{ fontSize: 10 }}>
                      {t.market_mode} · {t.updated_at_utc.slice(11, 16)}
                    </div>
                    {t.active_run_id && (
                      <div className="cc-dim" style={{ fontSize: 10 }}>run: {t.active_run_id.slice(0, 16)}</div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <div className="cc-card" style={{ flex: 1, padding: 0, minHeight: "75vh", display: "flex", flexDirection: "column" }}>
          {!activeThread ? (
            <div className="cc-dim" style={{ padding: 24, textAlign: "center", flex: 1 }}>
              选择左侧历史对话，或点右上 "+新对话" 开始。
              {bindRunId && (
                <div style={{ marginTop: 12 }}>
                  <button type="button" className="cc-btn cc-btn--accent" onClick={startNewThread}>
                    针对 run {bindRunId.slice(0, 16)} 开新对话
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--cc-border, rgba(255,255,255,0.08))" }}>
                <div className="cc-row" style={{ justifyContent: "space-between" }}>
                  <span className="cc-mono" style={{ fontSize: 12 }}>{activeThread.title || activeThread.thread_id}</span>
                  <span className="cc-dim" style={{ fontSize: 11 }}>
                    state: {activeThread.state} · {activeThread.market_mode}
                    {activeThread.active_run_id && ` · run=${activeThread.active_run_id.slice(0, 12)}`}
                  </span>
                </div>
              </div>
              <div style={{ flex: 1, overflow: "auto", padding: 12 }}>
                {messages.length === 0 ? (
                  <div className="cc-dim">空对话。提个问题开始（例：你能解释 PBO 吗？或：我这次 Sharpe 1.5 可信吗？）</div>
                ) : (
                  messages.map((m) => (
                    <MessageBubble key={m.message_id} m={m} />
                  ))
                )}
                <div ref={messagesEndRef} />
              </div>
              <div style={{ borderTop: "1px solid var(--cc-border, rgba(255,255,255,0.08))", padding: 8 }}>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="问任意量化问题（Enter 发送，Shift+Enter 换行）"
                  className="cc-input"
                  style={{ width: "100%", minHeight: 60, fontSize: 13, fontFamily: "inherit" }}
                  disabled={sending}
                />
                <div className="cc-row" style={{ justifyContent: "flex-end", marginTop: 4 }}>
                  <button
                    type="button"
                    className="cc-btn cc-btn--accent"
                    onClick={sendMessage}
                    disabled={!input.trim() || sending}
                  >
                    {sending ? "思考中..." : "发送"}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function MessageBubble({ m }: { m: ChatMessage }) {
  const isUser = m.role === "user";
  const bg = isUser ? "rgba(74,158,255,0.08)" : "rgba(255,255,255,0.03)";
  const align = isUser ? "flex-end" : "flex-start";
  return (
    <div style={{ display: "flex", justifyContent: align, marginBottom: 10 }}>
      <div
        style={{
          maxWidth: "85%",
          padding: 10,
          borderRadius: 8,
          background: bg,
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        <div className="cc-dim" style={{ fontSize: 10, marginBottom: 4 }}>
          {isUser ? "你" : "Mode 2 Agent"} · {m.created_at_utc.slice(11, 19)}
        </div>
        <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
        {m.metadata?.rag_hits && m.metadata.rag_hits.length > 0 && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--cc-border, rgba(255,255,255,0.06))" }}>
            <span className="cc-dim" style={{ fontSize: 10 }}>RAG: </span>
            {m.metadata.rag_hits.map((h) => (
              <a
                key={h.slug}
                href={`/glossary/${h.slug}`}
                className="cc-chip"
                style={{ fontSize: 10, marginRight: 4, textDecoration: "none" }}
              >
                {h.title || h.slug}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default Mode2ChatPage;
