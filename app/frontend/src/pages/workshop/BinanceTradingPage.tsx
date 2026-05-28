import { useEffect, useState } from "react";

interface KeystoreInfo {
  backend?: string;
  names?: string[];
}
interface RiskAlerts {
  paused?: boolean;
  alerts?: { level: string; message: string }[];
}
interface NetworkState {
  binance_network: string;
  mode: string;
  confirmed_at_utc?: string;
}

export function BinanceTradingPage() {
  const [keystoreInfo, setKeystoreInfo] = useState<KeystoreInfo | null>(null);
  const [alerts, setAlerts] = useState<RiskAlerts | null>(null);
  const [network, setNetwork] = useState<NetworkState | null>(null);
  const [name, setName] = useState("binance_testnet");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmStatement, setConfirmStatement] = useState("");
  const [confirmingMainnet, setConfirmingMainnet] = useState(false);

  const refresh = () => {
    fetch("/api/security/keystore").then((r) => r.json()).then(setKeystoreInfo);
    fetch("/api/risk/alerts").then((r) => r.json()).then(setAlerts);
    fetch("/api/security/network").then((r) => r.json()).then(setNetwork);
  };
  useEffect(refresh, []);

  const store = async () => {
    const res = await fetch("/api/security/keystore", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, api_key: apiKey, api_secret: apiSecret }),
    });
    const json = await res.json();
    setMsg(`✓ 写入 keystore (backend=${json.backend})`);
    setApiKey("");
    setApiSecret("");
    refresh();
  };

  const switchToTestnet = async () => {
    await fetch("/api/security/network", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ binance_network: "testnet" }),
    });
    refresh();
    setMsg("✓ 已切回 testnet");
  };

  const requestMainnet = () => {
    setConfirmingMainnet(true);
    setConfirmStatement("");
  };

  const confirmMainnet = async () => {
    const res = await fetch("/api/security/network", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        binance_network: "mainnet",
        acknowledged: true,
        statement: confirmStatement,
      }),
    });
    const json = await res.json();
    if (!res.ok) {
      setMsg(`✗ ${json.detail}`);
      return;
    }
    setConfirmingMainnet(false);
    setMsg("⚠️ 已切到 mainnet · 所有下单为真钱");
    refresh();
  };

  const triggerKill = async () => {
    if (!confirm("确认触发 Kill Switch？将撤销所有挂单 + 平所有仓位")) return;
    const res = await fetch("/api/risk/kill_switch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ close_positions: true }),
    });
    setMsg(`⚡ Kill Switch triggered: ${JSON.stringify(await res.json()).slice(0, 160)}`);
  };

  const isMainnet = network?.binance_network === "mainnet";

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">
            <span className="cc-prompt">$</span>binance-trading
          </h1>
          <p className="cc-page-subtitle">
            keystore 加密 · withdraw 权限启动校验 · testnet/mainnet 二次确认 · 三档风控 · Kill Switch
          </p>
        </div>
      </div>

      {/* 网络状态条 */}
      <div className={`cc-net-banner${isMainnet ? " cc-net-banner--mainnet" : ""}`}>
        <span className={`cc-status-dot ${isMainnet ? "cc-status-dot--red" : "cc-status-dot--green"}`} />
        <div style={{ flex: 1 }}>
          <strong style={{ color: isMainnet ? "var(--cc-danger)" : "var(--cc-success)" }}>
            net: {network?.binance_network || "loading"} {isMainnet && "· 真钱模式"}
          </strong>
          {network?.confirmed_at_utc && (
            <span className="cc-dim cc-mono" style={{ marginLeft: 12, fontSize: 11 }}>
              switched {network.confirmed_at_utc.slice(0, 19)}
            </span>
          )}
        </div>
        {isMainnet ? (
          <button type="button" className="cc-btn cc-btn--sm" onClick={switchToTestnet}>
            ← 切回 testnet
          </button>
        ) : (
          <button type="button" className="cc-btn cc-btn--sm cc-btn--danger" onClick={requestMainnet}>
            切到 mainnet（真钱）
          </button>
        )}
      </div>

      {/* 二次确认 modal */}
      {confirmingMainnet && (
        <div className="cc-modal-backdrop">
          <div className="cc-modal">
            <h3 style={{ color: "var(--cc-danger)" }}>⚠️ 风险确认</h3>
            <p style={{ color: "var(--cc-text-soft)" }}>切换到 mainnet 后，下单使用 <b>真实资金</b>。请确认：</p>
            <ul style={{ color: "var(--cc-text-soft)", fontSize: 13 }}>
              <li>API key 已关闭 withdraw 权限</li>
              <li>已开 IP 白名单</li>
              <li>每笔下单上限 / 日内亏损上限已配好</li>
              <li>已通读 <code>docs/binance-security-guide.md</code></li>
            </ul>
            <p>
              输入「<b>我已阅读 Binance 安全指南</b>」以确认：
            </p>
            <input
              className="cc-input"
              value={confirmStatement}
              onChange={(e) => setConfirmStatement(e.target.value)}
              placeholder="我已阅读 Binance 安全指南"
            />
            <div className="cc-modal-actions">
              <button type="button" className="cc-btn" onClick={() => setConfirmingMainnet(false)}>
                取消
              </button>
              <button
                type="button"
                className="cc-btn cc-btn--danger"
                disabled={!confirmStatement.includes("我已阅读")}
                onClick={confirmMainnet}
              >
                确认切到 mainnet
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="cc-grid-lg" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {/* keystore */}
        <section className="cc-card">
          <div className="cc-section-title" style={{ marginBottom: 12 }}>
            // api key 管理（keystore 加密）
          </div>
          {keystoreInfo && (
            <div className="cc-dim cc-mono" style={{ fontSize: 11, marginBottom: 8 }}>
              backend = {keystoreInfo.backend} · {(keystoreInfo.names || []).length} keys stored
            </div>
          )}
          <div className="cc-input-row">
            <label>name</label>
            <input className="cc-input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="cc-input-row">
            <label>api_key</label>
            <input className="cc-input" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </div>
          <div className="cc-input-row">
            <label>api_secret</label>
            <input
              className="cc-input"
              type="password"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="cc-btn cc-btn--accent"
            onClick={store}
            disabled={!apiKey || !apiSecret}
            style={{ marginTop: 8 }}
          >
            写入 keystore
          </button>
          <div className="cc-dim" style={{ fontSize: 11, marginTop: 8 }}>
            ⚠️ 启动 BinanceClient 时会调 apiRestrictions 校验 withdraw=false；有则拒绝运行。
          </div>
        </section>

        {/* risk */}
        <section className="cc-card">
          <div className="cc-section-title" style={{ marginBottom: 12 }}>
            // risk monitor
          </div>
          {alerts && (
            <div style={{ marginBottom: 12 }}>
              <span
                className={`cc-chip ${
                  alerts.paused ? "cc-chip--danger" : "cc-chip--success"
                }`}
              >
                {alerts.paused ? "已暂停" : "正常"}
              </span>
            </div>
          )}
          <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 12 }}>
            {(alerts?.alerts || []).map((a, i) => (
              <li
                key={i}
                style={{
                  marginBottom: 4,
                  color: a.level === "critical" ? "var(--cc-danger)" : "var(--cc-warning)",
                }}
              >
                <span className="cc-mono">[{a.level}]</span> {a.message}
              </li>
            ))}
            {(!alerts?.alerts || alerts.alerts.length === 0) && (
              <li className="cc-dim">no alerts</li>
            )}
          </ul>
          <button
            type="button"
            className="cc-btn cc-btn--danger"
            onClick={triggerKill}
            style={{ marginTop: 16, width: "100%" }}
          >
            ⚡ Kill Switch
          </button>
          <div className="cc-dim" style={{ fontSize: 11, marginTop: 8 }}>
            撤销所有挂单 + 市价平所有仓位（venue 未启用时为空操作）
          </div>
        </section>
      </div>

      {msg && (
        <div className="cc-chip cc-chip--success" style={{ marginTop: 16 }}>
          {msg}
        </div>
      )}
    </>
  );
}

export default BinanceTradingPage;
