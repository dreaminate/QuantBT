/**
 * v1.0 · Mainnet 7 项防御 Settings UI
 *
 * 面板:
 *   1. TOTP 2FA: enable 拿 secret + otpauth_uri (QR 用 google chart api) → verify
 *   2. IP 白名单 (text area, 一行一个 IP，支持 1.2.3.* wildcard)
 *   3. 单日额度 (operations + notional USDT)
 *   4. require_password_per_order toggle
 *   5. 今日 usage 实时显示
 *   6. Audit log 最近 100 条
 *   7. Emergency close-all button (持仓清盘)
 */

import { useEffect, useState } from "react";
import { authFetch, getStoredUser } from "../lib/auth";

interface MainnetConfig {
  user_id: string;
  trusted_ips: string[];
  totp_enabled: boolean;
  daily_operation_limit: number;
  daily_notional_limit_usdt: number;
  require_password_per_order: boolean;
  updated_at_utc: string;
}

interface TodayUsage {
  date: string;
  operations_today: number;
  notional_today_usdt: number;
}

interface AuditEntry {
  id: number;
  operation: string;
  venue: string | null;
  symbol: string | null;
  side: string | null;
  notional_usdt: number | null;
  source_ip: string | null;
  totp_verified: number;
  password_verified: number;
  result: string;
  error: string | null;
  occurred_at_utc: string;
}

function QRCode({ otpauthUri, size = 180 }: { otpauthUri: string; size?: number }) {
  // 用 chart.googleapis 简单渲染 QR (生产可换成本地 qrcode.js)
  const src = `https://chart.googleapis.com/chart?cht=qr&chs=${size}x${size}&chl=${encodeURIComponent(otpauthUri)}`;
  return (
    <img
      src={src}
      alt="2FA QR"
      width={size}
      height={size}
      style={{ background: "#fff", padding: 8, borderRadius: 8 }}
    />
  );
}

export function SettingsSecurityPage() {
  const user = getStoredUser();
  const [cfg, setCfg] = useState<MainnetConfig | null>(null);
  const [usage, setUsage] = useState<TodayUsage | null>(null);
  const [log, setLog] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 2FA enrollment state
  const [enrolling, setEnrolling] = useState(false);
  const [enrollSecret, setEnrollSecret] = useState<string | null>(null);
  const [enrollUri, setEnrollUri] = useState<string | null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);

  // Editable form
  const [ipsText, setIpsText] = useState("");
  const [opLimit, setOpLimit] = useState(50);
  const [notionalLimit, setNotionalLimit] = useState(1000);
  const [requirePwd, setRequirePwd] = useState(true);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const [r1, r2, r3] = await Promise.all([
        authFetch("/api/security/mainnet/config"),
        authFetch("/api/security/mainnet/usage"),
        authFetch("/api/security/mainnet/audit_log?limit=100"),
      ]);
      if (!r1.ok || !r2.ok || !r3.ok) {
        throw new Error(`API failed: ${r1.status}/${r2.status}/${r3.status}`);
      }
      const c: MainnetConfig = await r1.json();
      const u: TodayUsage = await r2.json();
      const l: AuditEntry[] = await r3.json();
      setCfg(c);
      setUsage(u);
      setLog(l);
      setIpsText(c.trusted_ips.join("\n"));
      setOpLimit(c.daily_operation_limit);
      setNotionalLimit(c.daily_notional_limit_usdt);
      setRequirePwd(c.require_password_per_order);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (user) refresh();
  }, [user?.user_id]);

  async function saveConfig() {
    const ips = ipsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      trusted_ips: ips,
      daily_operation_limit: opLimit,
      daily_notional_limit_usdt: notionalLimit,
      require_password_per_order: requirePwd,
    };
    const r = await authFetch("/api/security/mainnet/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      setErr(`保存失败: ${r.status}`);
      return;
    }
    await refresh();
  }

  async function enable2FA() {
    setEnrolling(true);
    try {
      const r = await authFetch("/api/security/mainnet/2fa/enable", { method: "POST" });
      if (!r.ok) {
        setErr(`2FA enable 失败: ${r.status}`);
        setEnrolling(false);
        return;
      }
      const j = await r.json();
      setEnrollSecret(j.secret);
      setEnrollUri(j.otpauth_uri);
    } catch (e) {
      // 网络失败也要复位 enrolling，否则二维码区永久卡在加载态。
      setErr(`2FA enable 失败: ${String(e)}`);
      setEnrolling(false);
    }
  }

  async function verify2FA() {
    try {
      const r = await authFetch("/api/security/mainnet/2fa/verify", {
        method: "POST",
        body: JSON.stringify({ code: verifyCode }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.valid) {
        setVerifyMsg("✓ 2FA 验证通过，已激活");
        setEnrolling(false);
        setEnrollSecret(null);
        setEnrollUri(null);
        setVerifyCode("");
        await refresh();
      } else {
        setVerifyMsg(`✗ 验证失败 (code 错误或过期): ${j.detail || ""}`);
      }
    } catch (e) {
      setVerifyMsg(`✗ 验证失败: ${String(e)}`);
    }
  }

  async function emergencyCloseAll() {
    if (!confirm("⚠️ 紧急平仓将关闭所有 mainnet 持仓 + 撤所有挂单，无法撤回。确认?")) return;
    const code = prompt("输入当前 TOTP 6 位 code 以确认:");
    if (!code) return;
    const r = await authFetch("/api/security/mainnet/emergency_close_all", {
      method: "POST",
      body: JSON.stringify({ totp_code: code }),
    });
    const j = await r.json();
    alert(r.ok ? `已请求紧急平仓: ${JSON.stringify(j)}` : `失败: ${j.detail || r.status}`);
    await refresh();
  }

  if (!user) {
    return (
      <div className="cc-card">
        <h2>需要登录</h2>
        <p>访问安全设置需先登录。</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 980 }}>
      <h1>安全设置 · Mainnet 防御 7 层</h1>
      {err && (
        <div className="cc-card" style={{ background: "#3a1818", borderColor: "#8a2020" }}>
          错误: {err}
        </div>
      )}
      {loading && <div className="cc-card">加载中...</div>}

      {/* === 1. 2FA TOTP === */}
      <section className="cc-card">
        <h2>1. 2FA / TOTP (Google Authenticator)</h2>
        {cfg?.totp_enabled ? (
          <div>
            <span className="cc-chip cc-chip--ok">✓ 已启用</span>
            <p style={{ opacity: 0.7, fontSize: 13 }}>每次 mainnet 操作前都将要求输 6 位 code。</p>
          </div>
        ) : enrolling && enrollUri ? (
          <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
            <QRCode otpauthUri={enrollUri} />
            <div style={{ flex: 1 }}>
              <p>用 Google Authenticator / 1Password 扫码，然后输入 6 位 code 完成激活:</p>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                placeholder="123456"
                value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value.trim())}
                style={{ fontSize: 18, letterSpacing: 4, padding: 8, width: 160 }}
              />
              <div style={{ marginTop: 8 }}>
                <button className="cc-btn cc-btn--primary" onClick={verify2FA}>
                  验证并激活
                </button>
              </div>
              {verifyMsg && <div style={{ marginTop: 8, fontSize: 13 }}>{verifyMsg}</div>}
              <details style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
                <summary>无法扫码？手动输入 secret</summary>
                <code style={{ wordBreak: "break-all" }}>{enrollSecret}</code>
              </details>
            </div>
          </div>
        ) : (
          <button className="cc-btn cc-btn--primary" onClick={enable2FA}>
            开始 2FA 配对
          </button>
        )}
      </section>

      {/* === 2. IP 白名单 === */}
      <section className="cc-card">
        <h2>2. IP 白名单</h2>
        <p style={{ opacity: 0.7, fontSize: 13 }}>
          每行一个 IP。支持 wildcard (例: <code>192.168.1.*</code>)。<b>空白名单 → mainnet 一律拒绝。</b>
        </p>
        <textarea
          rows={4}
          value={ipsText}
          onChange={(e) => setIpsText(e.target.value)}
          style={{ width: "100%", fontFamily: "monospace", padding: 8 }}
          placeholder={`# 一行一个，如:\n203.0.113.42\n10.0.0.*`}
        />
      </section>

      {/* === 3. 单日额度 === */}
      <section className="cc-card">
        <h2>3. 单日额度</h2>
        <div className="cc-row" style={{ gap: 16, flexWrap: "wrap" }}>
          <label>
            操作次数上限:{" "}
            <input
              type="number"
              min={1}
              max={500}
              value={opLimit}
              onChange={(e) => setOpLimit(Number(e.target.value))}
              style={{ width: 80 }}
            />
            {usage && <span style={{ marginLeft: 8, opacity: 0.7 }}>今: {usage.operations_today}</span>}
          </label>
          <label>
            名义额度 (USDT):{" "}
            <input
              type="number"
              min={10}
              max={1000000}
              step={10}
              value={notionalLimit}
              onChange={(e) => setNotionalLimit(Number(e.target.value))}
              style={{ width: 120 }}
            />
            {usage && (
              <span style={{ marginLeft: 8, opacity: 0.7 }}>
                今: {usage.notional_today_usdt.toFixed(2)}
              </span>
            )}
          </label>
        </div>
      </section>

      {/* === 4. Per-order password === */}
      <section className="cc-card">
        <h2>4. Per-order 二次密码</h2>
        <label className="cc-row" style={{ gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={requirePwd}
            onChange={(e) => setRequirePwd(e.target.checked)}
          />
          <span>下每笔 mainnet 单前必须重新输入登录密码</span>
        </label>
        <p style={{ opacity: 0.6, fontSize: 12, marginTop: 4 }}>
          强烈推荐保留勾选 — 即便会话 token 被劫持，攻击者也下不了单。
        </p>
      </section>

      <div className="cc-row" style={{ gap: 8 }}>
        <button className="cc-btn cc-btn--primary" onClick={saveConfig}>
          保存上述 4 项设置
        </button>
        <button className="cc-btn cc-btn--ghost" onClick={refresh}>
          刷新
        </button>
        <span style={{ flex: 1 }} />
        <button
          className="cc-btn"
          style={{ background: "#7a1717", color: "#fff" }}
          onClick={emergencyCloseAll}
          title="紧急平仓 (需 TOTP)"
        >
          🚨 紧急平所有 mainnet 仓
        </button>
      </div>

      {/* === LLM Providers（研究执行台连接测试 + reload secrets）=== */}
      <LlmProvidersPanel />

      {/* === 5. Audit log === */}
      <section className="cc-card">
        <h2>Audit Log (最近 {log.length} 条)</h2>
        <div style={{ maxHeight: 360, overflowY: "auto" }}>
          <table style={{ width: "100%", fontSize: 12, fontFamily: "monospace" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th>time(UTC)</th>
                <th>op</th>
                <th>venue/sym</th>
                <th>side</th>
                <th>USDT</th>
                <th>IP</th>
                <th>2FA</th>
                <th>pwd</th>
                <th>result</th>
              </tr>
            </thead>
            <tbody>
              {log.map((e) => (
                <tr key={e.id} style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
                  <td>{e.occurred_at_utc.slice(11, 19)}</td>
                  <td>{e.operation}</td>
                  <td>
                    {e.venue}/{e.symbol}
                  </td>
                  <td>{e.side}</td>
                  <td>{e.notional_usdt?.toFixed(2)}</td>
                  <td>{e.source_ip}</td>
                  <td>{e.totp_verified ? "✓" : ""}</td>
                  <td>{e.password_verified ? "✓" : ""}</td>
                  <td style={{ color: e.result === "ok" ? "#4ade80" : "#f87171" }}>
                    {e.result}
                    {e.error ? ` (${e.error})` : ""}
                  </td>
                </tr>
              ))}
              {log.length === 0 && (
                <tr>
                  <td colSpan={9} style={{ opacity: 0.5, padding: 16, textAlign: "center" }}>
                    暂无 mainnet 操作记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/**
 * LLM Providers 面板：研究执行台(/agent)使用的「连接测试 + reload secrets」。
 * provider 实时状态在底部 StatusBar 也有；此处保留旧页独有的 /api/llm/test + reload_secrets 管理动作。
 */
interface LlmProviderStatus {
  provider: string;
  configured: boolean;
  base_url?: string;
  model?: string;
  default_model?: string;
}

function LlmProvidersPanel() {
  const [providers, setProviders] = useState<LlmProviderStatus[]>([]);
  const [testResult, setTestResult] = useState<string | null>(null);

  const load = () => {
    fetch("/api/llm/status")
      .then((r) => r.json())
      .then((j) => setProviders(Array.isArray(j) ? j : j.providers || []))
      .catch(() => {
        /* best-effort：离线静默 */
      });
  };
  useEffect(() => {
    load();
  }, []);

  const testLlm = async (provider: string) => {
    setTestResult(`pinging ${provider}…`);
    try {
      const res = await fetch("/api/llm/test", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ provider, ping: "回我一句 ok" }),
      });
      const j = await res.json();
      setTestResult(
        j.ok
          ? `✓ ${j.provider}: ${(j.reply_preview || "").slice(0, 80)}`
          : `✗ ${j.provider}: ${j.error}`,
      );
    } catch (e) {
      setTestResult(`✗ ${e}`);
    }
  };

  const reloadSecrets = async () => {
    setTestResult("reloading secrets…");
    await fetch("/api/security/reload_secrets", { method: "POST" });
    load();
    setTestResult("✓ secrets reloaded");
  };

  return (
    <section className="cc-card">
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>LLM Providers · 连接测试</h2>
        <button type="button" className="cc-btn cc-btn--sm cc-btn--ghost" onClick={reloadSecrets}>
          ↻ reload secrets
        </button>
      </div>
      <div className="cc-row" style={{ flexWrap: "wrap", gap: 10 }}>
        {providers.map((p) => (
          <div key={p.provider} className="cc-card" style={{ padding: 10, minWidth: 220, flex: "1 1 220px" }}>
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
        {providers.length === 0 && (
          <span className="cc-dim" style={{ fontSize: 12 }}>
            无 provider 信息（/api/llm/status 空或离线）
          </span>
        )}
      </div>
      {testResult && (
        <pre className="cc-code" style={{ marginTop: 12, fontSize: 11 }}>
          {testResult}
        </pre>
      )}
    </section>
  );
}

export default SettingsSecurityPage;
