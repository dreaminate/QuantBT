import { useEffect, useState } from "react";
import { authFetch, getStoredUser } from "../../lib/auth";

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
interface MainnetConfig {
  trusted_ips?: string[];
}

export function BinanceTradingPage() {
  const [keystoreInfo, setKeystoreInfo] = useState<KeystoreInfo | null>(null);
  const [alerts, setAlerts] = useState<RiskAlerts | null>(null);
  const [network, setNetwork] = useState<NetworkState | null>(null);
  const [name, setName] = useState("binance_testnet");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [msgError, setMsgError] = useState(false);
  const [confirmStatement, setConfirmStatement] = useState("");
  const [confirmingMainnet, setConfirmingMainnet] = useState(false);
  const [mainnetCfg, setMainnetCfg] = useState<MainnetConfig | null>(null);
  // Kill Switch 二次鉴权 modal（后端硬契约：IP 白名单 + 密码再校验，否则 403）
  const [killModalOpen, setKillModalOpen] = useState(false);
  const [killPassword, setKillPassword] = useState("");
  const [killBusy, setKillBusy] = useState(false);

  const refresh = () => {
    fetch("/api/security/keystore").then((r) => r.json()).then(setKeystoreInfo);
    fetch("/api/risk/alerts").then((r) => r.json()).then(setAlerts);
    fetch("/api/security/network").then((r) => r.json()).then(setNetwork);
    // mainnet 配置需登录态；拿不到（未登录/无后端）→ 留 null，急停前会诚实提示前置条件
    authFetch("/api/security/mainnet/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((c: MainnetConfig | null) => setMainnetCfg(c))
      .catch(() => setMainnetCfg(null));
  };
  useEffect(refresh, []);

  const setOk = (m: string) => {
    setMsg(m);
    setMsgError(false);
  };
  const setErr = (m: string) => {
    setMsg(m);
    setMsgError(true);
  };

  const store = async () => {
    // 真钱凭据写入：HTTP 失败绝不能假绿灯（对齐同文件 confirmMainnet/confirmKill 的 res.ok 守卫）。
    try {
      const res = await fetch("/api/security/keystore", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, api_key: apiKey, api_secret: apiSecret }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(`✗ 写入 keystore 失败（HTTP ${res.status}）：${json.detail || ""}`);
        return;
      }
      setOk(`✓ 写入 keystore (backend=${json.backend})`);
      setApiKey("");
      setApiSecret("");
      refresh();
    } catch (e) {
      setErr(`✗ 写入 keystore 失败：${String(e)}`);
    }
  };

  const switchToTestnet = async () => {
    // 切回 testnet 失败必须如实报错：否则用户以为已安全离开 mainnet 真钱模式。
    try {
      const res = await fetch("/api/security/network", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ binance_network: "testnet" }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(`✗ 切回 testnet 失败（HTTP ${res.status}）：${json.detail || ""}`);
        return;
      }
      refresh();
      setOk("✓ 已切回 testnet");
    } catch (e) {
      setErr(`✗ 切回 testnet 失败：${String(e)}`);
    }
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
      setErr(`✗ ${json.detail}`);
      return;
    }
    setConfirmingMainnet(false);
    setOk("⚠️ 已切到 mainnet · 所有下单为真钱");
    refresh();
  };

  // Kill Switch 真修（对齐后端 POST /api/risk/kill_switch 硬契约）：
  //   require_user_dependency  → 必须带 Bearer token（authFetch），否则 401「未登录」
  //   IP 白名单                → 后端从【连接】派生 source_ip（_client_ip），与该用户 trusted_ips 比对，否则 403。
  //                            服务端派生 = body 无法伪造旁路；前端无需也无法填 IP（你当前出口 IP 须已在安全设置加白）。
  //   password（服务端真校验）  → 后端 _verify_second_factor 用 AUTH_SERVICE.verify_password PBKDF2 真比对，
  //                            前端直接传明文密码（同源），不再传自证 bool password_verified（已废弃）。
  // 任一前置不满足 → 如实展示后端 403/401 原因，绝不假绿灯。
  const openKillSwitch = () => {
    setKillPassword("");
    setKillModalOpen(true);
  };

  const confirmKill = async () => {
    const me = getStoredUser();
    if (!me) {
      setErr("✗ Kill Switch 需登录态（后端 require_user_dependency）。请先在社区登录后再试。");
      setKillModalOpen(false);
      return;
    }
    if (!killPassword) {
      setErr("✗ 需输入账户密码做二次校验（后端要求 password_verified）。");
      return;
    }
    setKillBusy(true);
    try {
      // 带 Bearer + 真密码触发急停：后端 _verify_second_factor 服务端 PBKDF2 真比对（不再传自证 bool）；
      // source_ip 由后端从连接派生（前端不传 = 不可伪造）。密码错 → 后端 403，如实展示不假绿灯。
      const res = await authFetch("/api/risk/kill_switch", {
        method: "POST",
        body: JSON.stringify({
          close_positions: true,
          password: killPassword,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        // 403（IP 不在白名单 / 密码未验证）或其它 → 如实暴露后端原因，不假绿灯
        setErr(`✗ Kill Switch 被拒（HTTP ${res.status}）：${json.detail || JSON.stringify(json).slice(0, 160)}`);
        return;
      }
      // 后端 _killswitch_status 已派生诚实状态：含 venue 失败绝不报 ok
      if (json.ok) {
        setOk(`⚡ Kill Switch 已触发 · status=${json.status} · ${JSON.stringify(json.results).slice(0, 140)}`);
      } else {
        setErr(
          `⚠️ Kill Switch 部分/全部失败 · status=${json.status} · ${JSON.stringify(json.results).slice(0, 160)}`,
        );
      }
      setKillModalOpen(false);
      refresh();
    } catch (e) {
      setErr(`✗ Kill Switch 请求异常（未确认是否触发）：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setKillBusy(false);
    }
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

      {/* Kill Switch 二次鉴权 modal（对齐后端 IP 白名单 + 密码再校验硬契约） */}
      {killModalOpen && (
        <div className="cc-modal-backdrop">
          <div className="cc-modal">
            <h3 style={{ color: "var(--cc-danger)" }}>⚡ 急停二次鉴权</h3>
            <p style={{ color: "var(--cc-text-soft)" }}>
              触发后将 <b>撤销所有挂单 + 市价平所有仓位</b>。后端按 D-T025 硬鉴权「谁能按按钮」：
            </p>
            <ul style={{ color: "var(--cc-text-soft)", fontSize: 13 }}>
              <li>登录态（Bearer token）— 否则 401</li>
              <li>你当前出口 IP 须在 <code>trusted_ips</code> 白名单（服务端按真实连接 IP 校验，不可伪造）— 否则 403</li>
              <li>账户密码二次校验（服务端真比对，非前端伪造）— 否则 403</li>
            </ul>
            <div className="cc-input-row">
              <label>账户密码</label>
              <input
                className="cc-input"
                type="password"
                value={killPassword}
                onChange={(e) => setKillPassword(e.target.value)}
                placeholder="登录密码（服务端 PBKDF2 校验）"
              />
            </div>
            <div className="cc-dim" style={{ fontSize: 11, marginTop: 4 }}>
              {mainnetCfg && (mainnetCfg.trusted_ips || []).length === 0
                ? "⚠️ 你当前未配 IP 白名单 → 此次急停预计被服务端 403 拒绝；如实展示原因，不假绿灯。"
                : "急停以你当前真实出口 IP 为准（服务端派生）；若该 IP 未加白 / 密码错误，将如实显示后端 403 原因，不会显示成功。"}
            </div>
            <div className="cc-modal-actions">
              <button
                type="button"
                className="cc-btn"
                onClick={() => setKillModalOpen(false)}
                disabled={killBusy}
              >
                取消
              </button>
              <button
                type="button"
                className="cc-btn cc-btn--danger"
                disabled={killBusy || !killPassword}
                onClick={confirmKill}
              >
                {killBusy ? "执行中…" : "确认急停"}
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
            onClick={openKillSwitch}
            style={{ marginTop: 16, width: "100%" }}
          >
            ⚡ Kill Switch
          </button>
          <div className="cc-dim" style={{ fontSize: 11, marginTop: 8 }}>
            撤销所有挂单 + 市价平所有仓位（venue 未启用时为空操作）
          </div>
          <div className="cc-dim" style={{ fontSize: 11, marginTop: 6, lineHeight: 1.6 }}>
            ⚠️ 后端硬鉴权（D-T025「谁能按按钮」）：须 <b>登录态</b> + <b>出口 IP 已加白名单</b> +{" "}
            <b>账户密码二次校验</b>，缺一即被服务端 403 拒绝（不会假绿灯）。
            {mainnetCfg
              ? (mainnetCfg.trusted_ips || []).length > 0
                ? ` 已配白名单：${(mainnetCfg.trusted_ips || []).join(", ")}`
                : " 当前未配 IP 白名单 → 急停会被拒，请先到「安全设置」加白出口 IP。"
              : " （未取到白名单配置：可能未登录或后端不在）"}
          </div>
        </section>
      </div>

      {msg && (
        <div
          className={`cc-chip ${msgError ? "cc-chip--danger" : "cc-chip--success"}`}
          style={{ marginTop: 16 }}
        >
          {msg}
        </div>
      )}
    </>
  );
}

export default BinanceTradingPage;
