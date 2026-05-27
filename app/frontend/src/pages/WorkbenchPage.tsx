import { useEffect, useMemo, useState } from "react";

/**
 * 工坊 · 一个 SPA 子页面汇总 M15 在 GOAL 中列出的所有新功能入口：
 * - 策略工坊 (StrategyGoal slot-fill + JSON 预览)
 * - Agent 工作台 (与 DevLocalLLM 对话 + 工具调用 trace)
 * - 因子市场 (列 /api/factors + lifecycle_state)
 * - Binance 交易台 (keystore + risk alerts + Kill Switch)
 * - 实验追踪 (experiments + runs + lineage)
 *
 * **重要**：不动 frontend-run-detail/src/pages/RunDetailPage.tsx；本页面是新增的，
 * 通过现有 frontend SPA 的 /workbench 路由进入。
 */

type TabKey = "strategy" | "agent" | "factors" | "trading" | "experiments";

const TABS: { key: TabKey; label: string; emoji: string }[] = [
  { key: "strategy", label: "策略工坊", emoji: "📐" },
  { key: "agent", label: "Agent 工作台", emoji: "🤖" },
  { key: "factors", label: "因子市场", emoji: "📊" },
  { key: "trading", label: "Binance 交易台", emoji: "🔐" },
  { key: "experiments", label: "实验追踪", emoji: "🧪" },
];

export function WorkbenchPage() {
  const [active, setActive] = useState<TabKey>("strategy");
  return (
    <div className="jq-workbench">
      <div className="jq-workbench-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={t.key === active ? "jq-tab active" : "jq-tab"}
            onClick={() => setActive(t.key)}
          >
            <span style={{ marginRight: 6 }}>{t.emoji}</span>
            {t.label}
          </button>
        ))}
      </div>
      <div className="jq-workbench-body">
        {active === "strategy" && <StrategyPane />}
        {active === "agent" && <AgentPane />}
        {active === "factors" && <FactorsPane />}
        {active === "trading" && <TradingPane />}
        {active === "experiments" && <ExperimentsPane />}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 24, padding: 16, border: "1px solid #ddd", borderRadius: 6 }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      {children}
    </section>
  );
}

// ===================== 策略工坊 =====================

function StrategyPane() {
  const [text, setText] = useState("我想做 A股 周频 选股策略，回撤 15%，单标的 5%");
  const [goal, setGoal] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setError(null);
    try {
      const res = await fetch("/api/agent/slot_fill", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setGoal(await res.json());
    } catch (err) {
      setError(String(err));
    }
  };
  return (
    <div>
      <Section title="自然语言 → StrategyGoal">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          style={{ width: "100%" }}
        />
        <div style={{ marginTop: 8 }}>
          <button type="button" onClick={submit}>解析为 StrategyGoal</button>
        </div>
        {error && <pre style={{ color: "crimson" }}>{error}</pre>}
        {goal && (
          <pre style={{ background: "#fafafa", padding: 12 }}>
            {JSON.stringify(goal, null, 2)}
          </pre>
        )}
      </Section>
    </div>
  );
}

// ===================== Agent 工作台 =====================

interface AgentStep {
  role: string;
  content: string;
  tool_calls?: { name?: string; arguments?: string }[];
}

function AgentPane() {
  const [input, setInput] = useState("你能做什么");
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: input }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setSteps(json.steps || []);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <Section title="与 Agent 对话（开发期 LLM = DevLocalLLM 模板驱动）">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          rows={3}
          style={{ width: "100%" }}
        />
        <div style={{ marginTop: 8 }}>
          <button type="button" disabled={busy} onClick={send}>
            {busy ? "运行中…" : "发送"}
          </button>
        </div>
        {error && <pre style={{ color: "crimson" }}>{error}</pre>}
        <div style={{ marginTop: 12 }}>
          {steps.map((s, idx) => (
            <div key={idx} style={{ marginBottom: 8, padding: 8, background: "#fafafa", borderLeft: "3px solid #888" }}>
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
      </Section>
    </div>
  );
}

// ===================== 因子市场 =====================

interface FactorItem {
  factor_id: string;
  formula: string;
  lifecycle_state: string;
  description?: string;
}

function FactorsPane() {
  const [items, setItems] = useState<FactorItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/factors")
      .then((r) => r.json())
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);
  return (
    <Section title={`因子市场 (${items.length})`}>
      {err && <pre style={{ color: "crimson" }}>{err}</pre>}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #ddd" }}>
            <th align="left">factor_id</th>
            <th align="left">公式</th>
            <th align="left">生命周期</th>
            <th align="left">描述</th>
          </tr>
        </thead>
        <tbody>
          {items.map((f) => (
            <tr key={f.factor_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
              <td style={{ fontFamily: "monospace" }}>{f.factor_id}</td>
              <td style={{ fontFamily: "monospace" }}>{f.formula}</td>
              <td>{f.lifecycle_state}</td>
              <td style={{ color: "#666" }}>{f.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

// ===================== Binance 交易台 =====================

function TradingPane() {
  const [keystoreInfo, setKeystoreInfo] = useState<{ backend?: string; names?: string[] } | null>(null);
  const [alerts, setAlerts] = useState<{ paused?: boolean; alerts?: { level: string; message: string }[] } | null>(null);
  const [name, setName] = useState("binance_testnet");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = () => {
    fetch("/api/security/keystore").then((r) => r.json()).then(setKeystoreInfo);
    fetch("/api/risk/alerts").then((r) => r.json()).then(setAlerts);
  };
  useEffect(refresh, []);
  const store = async () => {
    const res = await fetch("/api/security/keystore", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, api_key: apiKey, api_secret: apiSecret }),
    });
    const json = await res.json();
    setMsg(`已写入 keystore (backend=${json.backend})`);
    setApiKey("");
    setApiSecret("");
    refresh();
  };
  const triggerKill = async () => {
    if (!confirm("确认触发 Kill Switch？将撤销所有挂单 + 平所有仓位")) return;
    const res = await fetch("/api/risk/kill_switch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ close_positions: true }),
    });
    setMsg(`Kill Switch 已触发: ${JSON.stringify(await res.json()).slice(0, 200)}`);
  };
  return (
    <div>
      <Section title="API key 管理（keystore 加密）">
        {keystoreInfo && (
          <div style={{ marginBottom: 12 }}>
            backend = <code>{keystoreInfo.backend}</code> · 已存名称 = {(keystoreInfo.names || []).join(", ") || "（无）"}
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
          <input placeholder="name (binance_testnet)" value={name} onChange={(e) => setName(e.target.value)} />
          <input placeholder="api_key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          <input placeholder="api_secret" type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} />
        </div>
        <div style={{ marginTop: 8 }}>
          <button type="button" onClick={store} disabled={!apiKey || !apiSecret}>写入 keystore</button>
        </div>
        <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
          ⚠️ 启动 BinanceClient 时会自动调 apiRestrictions 校验 withdraw=false；任何 withdraw 权限都会被拒绝。
        </div>
      </Section>
      <Section title="风控状态">
        {alerts && (
          <div>
            <div>
              状态：{alerts.paused ? <strong style={{ color: "crimson" }}>已暂停</strong> : <strong style={{ color: "seagreen" }}>正常</strong>}
            </div>
            <ul>
              {(alerts.alerts || []).map((a, i) => (
                <li key={i} style={{ color: a.level === "critical" ? "crimson" : "#a06" }}>
                  [{a.level}] {a.message}
                </li>
              ))}
            </ul>
          </div>
        )}
        <button type="button" style={{ background: "crimson", color: "white", padding: "8px 16px" }} onClick={triggerKill}>
          ⚡ Kill Switch
        </button>
      </Section>
      {msg && <pre style={{ color: "seagreen" }}>{msg}</pre>}
    </div>
  );
}

// ===================== 实验追踪 =====================

interface ExperimentItem {
  experiment_id: string;
  name: string;
  asset_class: string;
  created_at_utc: string;
}

function ExperimentsPane() {
  const [items, setItems] = useState<ExperimentItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const load = () => {
    fetch("/api/experiments").then((r) => r.json()).then(setItems).catch((e) => setErr(String(e)));
  };
  useEffect(load, []);
  return (
    <Section title={`实验追踪 (${items.length})`}>
      {err && <pre style={{ color: "crimson" }}>{err}</pre>}
      {items.length === 0 ? (
        <p style={{ color: "#666" }}>暂无实验。Agent 跑回测会自动建实验。</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ddd" }}>
              <th align="left">name</th>
              <th align="left">asset</th>
              <th align="left">created</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.experiment_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                <td>{e.name}</td>
                <td>{e.asset_class}</td>
                <td style={{ color: "#666" }}>{e.created_at_utc.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

export default WorkbenchPage;
