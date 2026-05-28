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

/**
 * Binance 交易台 · 独立 SPA 页面
 * 路由：/trading
 * - testnet/mainnet 顶部色块（绿/红）
 * - mainnet 切换走二次确认弹窗 + 风险告知文案校验
 * - keystore 表单 / 风控状态 / Kill Switch
 */
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
    setMsg(`已写入 keystore (backend=${json.backend})`);
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
    setMsg("已切回 testnet");
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
      setMsg(`❌ ${json.detail}`);
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
    setMsg(`Kill Switch 已触发: ${JSON.stringify(await res.json()).slice(0, 200)}`);
  };

  const isMainnet = network?.binance_network === "mainnet";

  return (
    <div style={{ padding: 16 }}>
      {/* 网络色块 —— testnet 绿、mainnet 红，顶部明显 */}
      <div
        style={{
          padding: "12px 16px",
          marginBottom: 16,
          background: isMainnet ? "#fde7e7" : "#e7f7ee",
          border: `2px solid ${isMainnet ? "crimson" : "seagreen"}`,
          borderRadius: 6,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>
          <strong style={{ fontSize: 16, color: isMainnet ? "crimson" : "seagreen" }}>
            当前网络：{network?.binance_network || "loading"} {isMainnet ? "· 真钱模式" : ""}
          </strong>
          {network?.confirmed_at_utc && (
            <span style={{ marginLeft: 12, fontSize: 12, color: "#666" }}>
              切换于 {network.confirmed_at_utc.slice(0, 19)}
            </span>
          )}
        </span>
        {isMainnet ? (
          <button type="button" onClick={switchToTestnet}>切回 testnet</button>
        ) : (
          <button type="button" style={{ background: "crimson", color: "white", padding: "4px 12px" }} onClick={requestMainnet}>
            切到 mainnet（真钱）
          </button>
        )}
      </div>

      {/* mainnet 二次确认弹窗 */}
      {confirmingMainnet && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div style={{ background: "white", padding: 24, borderRadius: 8, maxWidth: 600 }}>
            <h3 style={{ color: "crimson" }}>⚠️ 风险确认</h3>
            <p>切换到 mainnet 后，下单会使用 <strong>真实资金</strong>。请确认：</p>
            <ul>
              <li>API key 已关闭 withdraw 权限</li>
              <li>已开 IP 白名单</li>
              <li>每笔下单上限 / 日内亏损上限已配好</li>
              <li>已通读 <code>docs/binance-security-guide.md</code></li>
            </ul>
            <p>请输入「<strong>我已阅读 Binance 安全指南</strong>」以确认：</p>
            <input
              type="text"
              value={confirmStatement}
              onChange={(e) => setConfirmStatement(e.target.value)}
              style={{ width: "100%", padding: 6 }}
              placeholder="我已阅读 Binance 安全指南"
            />
            <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button type="button" onClick={() => setConfirmingMainnet(false)}>取消</button>
              <button
                type="button"
                disabled={!confirmStatement.includes("我已阅读")}
                style={{
                  background: confirmStatement.includes("我已阅读") ? "crimson" : "#ccc",
                  color: "white",
                  padding: "6px 16px",
                }}
                onClick={confirmMainnet}
              >
                确认切到 mainnet
              </button>
            </div>
          </div>
        </div>
      )}

      <section style={{ marginBottom: 24, padding: 16, border: "1px solid #ddd", borderRadius: 6 }}>
        <h3 style={{ marginTop: 0 }}>API key 管理（keystore 加密）</h3>
        {keystoreInfo && (
          <div style={{ marginBottom: 12 }}>
            backend = <code>{keystoreInfo.backend}</code> · 已存名称 ={" "}
            {(keystoreInfo.names || []).join(", ") || "（无）"}
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
          <input placeholder="name (binance_testnet)" value={name} onChange={(e) => setName(e.target.value)} />
          <input placeholder="api_key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          <input
            placeholder="api_secret"
            type="password"
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
          />
        </div>
        <div style={{ marginTop: 8 }}>
          <button type="button" onClick={store} disabled={!apiKey || !apiSecret}>
            写入 keystore
          </button>
        </div>
        <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
          ⚠️ 启动 BinanceClient 时会自动调 apiRestrictions 校验 withdraw=false；任何 withdraw 权限都会被拒绝。
        </div>
      </section>

      <section style={{ marginBottom: 24, padding: 16, border: "1px solid #ddd", borderRadius: 6 }}>
        <h3 style={{ marginTop: 0 }}>风控状态</h3>
        {alerts && (
          <div>
            <div>
              状态：
              {alerts.paused ? (
                <strong style={{ color: "crimson" }}>已暂停</strong>
              ) : (
                <strong style={{ color: "seagreen" }}>正常</strong>
              )}
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
        <button
          type="button"
          style={{ background: "crimson", color: "white", padding: "8px 16px" }}
          onClick={triggerKill}
        >
          ⚡ Kill Switch
        </button>
      </section>

      {msg && <pre style={{ color: "seagreen" }}>{msg}</pre>}
    </div>
  );
}

export default BinanceTradingPage;
