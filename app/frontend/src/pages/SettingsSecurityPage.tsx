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

      {/* === Data Connectors（Settings-managed SecretRef 连接测试）=== */}
      <DataConnectorSettingsPanel />

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
  settings_managed?: boolean;
  secret_ref?: string;
  credential_pool_ref?: string;
  routing_policy_ref?: string;
  auth_status?: string;
}

function LlmProvidersPanel() {
  const [providers, setProviders] = useState<LlmProviderStatus[]>([]);
  const [testResult, setTestResult] = useState<string | null>(null);

  const load = () => {
    authFetch("/api/llm/status")
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
      const res = await authFetch("/api/llm/test", {
        method: "POST",
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
    await authFetch("/api/security/reload_secrets", { method: "POST" });
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
                <span className="cc-chip cc-chip--success">configured</span>
              ) : (
                <span className="cc-chip">missing</span>
              )}
            </div>
            <div className="cc-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
              <span className={`cc-chip ${p.settings_managed ? "cc-chip--success" : ""}`}>
                {p.settings_managed ? "Gateway managed" : "no Settings metadata"}
              </span>
              <span className={`cc-chip ${p.auth_status === "active" ? "cc-chip--success" : ""}`}>
                auth: {p.auth_status || "unknown"}
              </span>
            </div>
            <div className="cc-dim" style={{ fontSize: 11, marginTop: 4 }}>
              {p.model || p.default_model || "—"}
            </div>
            <div className="cc-dim" style={{ fontSize: 11, marginTop: 6, lineHeight: 1.45 }}>
              <div>secret: <code>{p.secret_ref || "—"}</code></div>
              <div>pool: <code>{p.credential_pool_ref || "—"}</code></div>
              <div>policy: <code>{p.routing_policy_ref || "—"}</code></div>
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

interface DataSourceSummary {
  source_ref: string;
  license?: string | null;
  rate_limit?: string | null;
  retention_policy?: string | null;
  export_allowed?: boolean;
  share_allowed?: boolean;
  warning_codes?: string[];
}

interface SecretRefSummary {
  secret_ref: string;
  scope?: string;
  status?: string;
  affected_skills?: string[];
  keystore_refs?: string[];
  secret_value_stored?: boolean;
  keystore_backend?: string | null;
}

interface IngestionSkillSummary {
  skill_id: string;
  source_ref: string;
  source_type?: string;
  schema_mapping_ref?: string;
  secret_refs?: string[];
  lifecycle_state?: string;
  freshness_status?: string;
  permission_scope?: string;
  output_dataset_id?: string;
  schema_drift_status?: string;
}

interface DataConnectorCheckSummary {
  check_ref: string;
  skill_id: string;
  source_ref: string;
  checked_at?: string;
  checker_ref?: string;
  status?: string;
  health_status?: string;
  quota_status?: string;
  schema_probe_ref?: string | null;
  error_code?: string | null;
  error_message?: string | null;
}

interface IngestionSkillUpdateSummary {
  update_ref: string;
  skill_ref: string;
  skill_version?: string;
  source_ref?: string | null;
  secret_ref?: string | null;
  dataset_version_ref?: string | null;
  checksum?: string | null;
  lineage_ref?: string | null;
  quality_verdict_ref?: string | null;
  known_at_ref?: string | null;
  effective_at_ref?: string | null;
  freshness_status?: string | null;
  schema_drift_status?: string | null;
  row_count?: number | null;
}

interface DataConnectorSchemaProbeSummary {
  probe_ref: string;
  skill_id: string;
  source_ref: string;
  connector_check_ref?: string;
  probed_at?: string;
  schema_signature_hash?: string;
  columns?: string[];
  row_count?: number;
  dataset_version_ref?: string | null;
  drift_status?: string;
}

interface DataConnectorFieldMappingSummary {
  mapping_ref: string;
  skill_id: string;
  source_ref: string;
  schema_probe_ref: string;
  mapped_at?: string;
  schema_signature_hash?: string;
  source_to_canonical?: Record<string, string>;
  event_time_column?: string;
  known_at_column?: string | null;
  effective_at_column?: string | null;
  symbol_column?: string | null;
  unmapped_columns?: string[];
  mapping_hash?: string | null;
  mapping_method?: string;
  pit_bitemporal_candidate_ref?: string | null;
}

interface DataConnectorPitBitemporalRuleSummary {
  rule_ref: string;
  skill_id: string;
  source_ref: string;
  field_mapping_ref: string;
  schema_probe_ref: string;
  generated_at?: string;
  event_time_column?: string;
  known_at_column?: string | null;
  effective_at_column?: string | null;
  known_at_policy?: string;
  effective_at_policy?: string;
  asof_join_policy?: string;
  timezone?: string;
  calendar_ref?: string | null;
  lookahead_guard_ref?: string;
  monotonicity_check_ref?: string | null;
  restatement_policy?: string;
  rule_hash?: string | null;
  evidence_refs?: string[];
}

interface MarketDataDatasetSummary {
  dataset_ref: string;
  source_ref: string;
  version?: string;
  known_at_ref?: string | null;
  effective_at_ref?: string | null;
  pit_bitemporal_rules_ref?: string | null;
  quality_status?: string;
  freshness_status?: string;
  checksum?: string | null;
}

interface MarketDataInstrumentSummary {
  instrument_ref: string;
  asset_class: string;
  instrument_type: string;
  currency: string;
  exchange_calendar_ref?: string | null;
  symbol_mapping_ref?: string | null;
}

interface MarketDataCapabilitySummary {
  matrix_ref: string;
  asset_class: string;
  instrument_type: string;
  research?: boolean;
  backtest?: boolean;
  paper?: boolean;
  testnet?: boolean;
  live?: boolean;
  data_availability?: string | null;
  permission_requirement?: string | null;
}

interface MarketDataUseValidationSummary {
  validation_ref: string;
  request_ref: string;
  use_context: string;
  dataset_refs?: string[];
  instrument_refs?: string[];
  capability_matrix_ref: string;
  accepted?: boolean;
  violation_codes?: string[];
}

interface SettingsSummary {
  secret_ref_total?: number;
  data_source_total?: number;
  ingestion_skill_total?: number;
  data_connector_check_total?: number;
  data_connector_schema_probe_total?: number;
  data_connector_field_mapping_total?: number;
  data_connector_pit_bitemporal_rule_total?: number;
  ingestion_skill_update_total?: number;
  market_data_dataset_total?: number;
  market_data_instrument_total?: number;
  market_data_capability_matrix_total?: number;
  market_data_use_validation_total?: number;
  secret_refs?: SecretRefSummary[];
  data_sources?: DataSourceSummary[];
  ingestion_skills?: IngestionSkillSummary[];
  data_connector_checks?: DataConnectorCheckSummary[];
  data_connector_schema_probes?: DataConnectorSchemaProbeSummary[];
  data_connector_field_mappings?: DataConnectorFieldMappingSummary[];
  data_connector_pit_bitemporal_rules?: DataConnectorPitBitemporalRuleSummary[];
  ingestion_skill_updates?: IngestionSkillUpdateSummary[];
  market_data_datasets?: MarketDataDatasetSummary[];
  market_data_instruments?: MarketDataInstrumentSummary[];
  market_data_capability_matrices?: MarketDataCapabilitySummary[];
  market_data_use_validations?: MarketDataUseValidationSummary[];
}

function canonicalFieldForSourceColumn(column: string): string | null {
  const normalized = column.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  if (!normalized) return null;
  if (["ts", "date", "time", "datetime", "timestamp", "trade_date"].includes(normalized)) return "event_time";
  if (["symbol", "ticker", "code", "ts_code", "instrument", "instrument_id"].includes(normalized)) return "instrument_id";
  if (["open", "high", "low", "close", "volume", "amount", "turnover", "vwap"].includes(normalized)) return normalized;
  return null;
}

function inferAssetClassForSkill(skill: IngestionSkillSummary): string {
  const text = `${skill.output_dataset_id ?? ""} ${skill.source_ref ?? ""} ${skill.source_type ?? ""}`.toLowerCase();
  if (["cn_equity", "a_share", "ashare", "tushare", "china"].some((token) => text.includes(token))) return "cn_equity";
  if (["crypto", "binance", "okx", "coinbase", "usdt"].some((token) => text.includes(token))) return "crypto";
  if (["fx", "forex", "currency"].some((token) => text.includes(token))) return "fx";
  if (["future", "futures", "perpetual"].some((token) => text.includes(token))) return "futures";
  return "equity";
}

function defaultInstrumentTypeForAsset(assetClass: string): string {
  if (assetClass === "crypto") return "spot";
  if (assetClass === "futures") return "future";
  return "equity";
}

function defaultCurrencyForAsset(assetClass: string): string {
  if (["cn_equity", "a_share", "equity_cn", "stocks_cn"].includes(assetClass)) return "CNY";
  if (assetClass === "crypto") return "USDT";
  return "USD";
}

type FieldMappingDraft = {
  sourceToCanonical?: Record<string, string>;
  eventTimeColumn?: string;
  knownAtColumn?: string;
  effectiveAtColumn?: string;
  symbolColumn?: string;
  mappingMethod?: string;
};

type PitRuleDraft = {
  eventTimeColumn?: string;
  knownAtColumn?: string;
  effectiveAtColumn?: string;
  knownAtPolicy?: string;
  effectiveAtPolicy?: string;
  asofJoinPolicy?: string;
  timezone?: string;
  restatementPolicy?: string;
};

type GenericRestDraft = {
  sourceRef: string;
  sourceUrl: string;
  license: string;
  rateLimit: string;
  tosConstraints: string;
  commercialUseStatus: string;
  retentionPolicy: string;
  sourceOwner: string;
  skillId: string;
  outputDatasetId: string;
  schemaMappingRef: string;
  pitBitemporalRulesRef: string;
  dataKind: string;
  symbol: string;
  interval: string;
  market: string;
  start: string;
  end: string;
  permissionScope: string;
  genericRestYaml: string;
};

type StooqDraft = {
  sourceRef: string;
  sourceUrl: string;
  license: string;
  rateLimit: string;
  tosConstraints: string;
  commercialUseStatus: string;
  retentionPolicy: string;
  sourceOwner: string;
  skillId: string;
  outputDatasetId: string;
  schemaMappingRef: string;
  pitBitemporalRulesRef: string;
  symbol: string;
  interval: string;
  start: string;
  end: string;
  permissionScope: string;
};

type BinancePublicDraft = {
  sourceRef: string;
  sourceUrl: string;
  license: string;
  rateLimit: string;
  tosConstraints: string;
  commercialUseStatus: string;
  retentionPolicy: string;
  sourceOwner: string;
  skillId: string;
  outputDatasetId: string;
  schemaMappingRef: string;
  pitBitemporalRulesRef: string;
  symbol: string;
  interval: string;
  market: string;
  dataKind: string;
  start: string;
  end: string;
  permissionScope: string;
};

const CANONICAL_FIELD_OPTIONS = [
  "",
  "event_time",
  "instrument_id",
  "open",
  "high",
  "low",
  "close",
  "volume",
  "amount",
  "turnover",
  "vwap",
  "market",
  "interval",
  "adjusted_close",
  "corporate_action_adjustment",
];

const PIT_TIME_POLICY_OPTIONS = ["source_column", "connector_fetched_at", "event_time"];
const PIT_ASOF_POLICY_OPTIONS = [
  "known_at_lte_decision_time_latest",
  "known_at_lte_decision_time_first",
  "event_time_lte_decision_time_latest",
  "current_snapshot",
];
const PIT_RESTATEMENT_POLICY_OPTIONS = [
  "latest_known_at_before_decision_time",
  "first_known_at_after_event_time",
  "ignore_restatements",
];

const DEFAULT_GENERIC_REST_YAML = `connector_name: custom_bars
label: Custom Bars
asset_class: custom
base_url: https://example.invalid
supported_markets: [custom]
supported_intervals: [1d]
auth:
  mode: none
endpoints:
  ohlcv:
    method: GET
    path: /bars/{symbol}
    query:
      start: "{start_date}"
      end: "{end_date}"
    rate_limit_per_minute: 600
    response_mapping:
      records: "$.data[*]"
      fields:
        ts: t
        open: o
        high: h
        low: l
        close: c
        volume: v
      ts_unit: ms
      tz: UTC
schema_target: ohlcv`;

const DEFAULT_GENERIC_REST_DRAFT: GenericRestDraft = {
  sourceRef: "datasource:custom:rest",
  sourceUrl: "https://example.invalid",
  license: "user_provided",
  rateLimit: "600/min",
  tosConstraints: "user_supplied_terms",
  commercialUseStatus: "user_responsibility",
  retentionPolicy: "retain:research-cache",
  sourceOwner: "user",
  skillId: "ingest:custom:bars",
  outputDatasetId: "dataset:custom_bars",
  schemaMappingRef: "schema_map:custom:bars",
  pitBitemporalRulesRef: "pit:custom:bars",
  dataKind: "ohlcv",
  symbol: "DEMO",
  interval: "1d",
  market: "custom",
  start: "",
  end: "",
  permissionScope: "market_data:read",
  genericRestYaml: DEFAULT_GENERIC_REST_YAML,
};

const DEFAULT_STOOQ_DRAFT: StooqDraft = {
  sourceRef: "datasource:stooq:public",
  sourceUrl: "https://stooq.com/q/d/l/",
  license: "stooq_public_terms",
  rateLimit: "60/min",
  tosConstraints: "stooq_public_market_data_terms",
  commercialUseStatus: "user_responsibility",
  retentionPolicy: "retain:research-cache",
  sourceOwner: "stooq",
  skillId: "ingest:stooq:aapl:daily",
  outputDatasetId: "dataset:stooq_aapl_daily",
  schemaMappingRef: "schema_map:stooq:ohlcv",
  pitBitemporalRulesRef: "pit:stooq:daily",
  symbol: "AAPL.US",
  interval: "1d",
  start: "",
  end: "",
  permissionScope: "market_data:read",
};

const DEFAULT_BINANCE_PUBLIC_DRAFT: BinancePublicDraft = {
  sourceRef: "datasource:binance:public",
  sourceUrl: "https://api.binance.com/api/v3/klines",
  license: "binance_public_api_terms",
  rateLimit: "1200/min",
  tosConstraints: "binance_public_api_terms",
  commercialUseStatus: "user_responsibility",
  retentionPolicy: "retain:research-cache",
  sourceOwner: "binance",
  skillId: "ingest:binance:btcusdt:1m",
  outputDatasetId: "dataset:binance_spot_btcusdt_1m",
  schemaMappingRef: "schema_map:binance:ohlcv",
  pitBitemporalRulesRef: "pit:binance:klines",
  symbol: "BTCUSDT",
  interval: "1m",
  market: "binance_spot",
  dataKind: "ohlcv",
  start: "",
  end: "",
  permissionScope: "market_data:read",
};

function nullableColumn(value?: string | null): string | null {
  const text = String(value ?? "").trim();
  return text ? text : null;
}

function fieldMappingRoleForColumn(
  column: string,
  draft?: FieldMappingDraft,
  existing?: DataConnectorFieldMappingSummary,
): string {
  if (draft?.sourceToCanonical && Object.prototype.hasOwnProperty.call(draft.sourceToCanonical, column)) {
    return draft.sourceToCanonical[column] || "";
  }
  return existing?.source_to_canonical?.[column] ?? canonicalFieldForSourceColumn(column) ?? "";
}

function fieldMappingPayloadPreview(
  schemaProbe?: DataConnectorSchemaProbeSummary,
  existing?: DataConnectorFieldMappingSummary,
  draft?: FieldMappingDraft,
) {
  const sourceToCanonical: Record<string, string> = {};
  const unmappedColumns: string[] = [];
  for (const column of schemaProbe?.columns ?? []) {
    const canonical = fieldMappingRoleForColumn(column, draft, existing);
    if (canonical) sourceToCanonical[column] = canonical;
    else unmappedColumns.push(column);
  }
  const firstColumnFor = (canonical: string) =>
    Object.entries(sourceToCanonical).find(([, value]) => value === canonical)?.[0] ?? "";
  const eventTimeColumn =
    draft?.eventTimeColumn !== undefined
      ? draft.eventTimeColumn
      : existing?.event_time_column || firstColumnFor("event_time");
  const knownAtColumn =
    draft?.knownAtColumn !== undefined
      ? draft.knownAtColumn
      : existing?.known_at_column ?? eventTimeColumn;
  const effectiveAtColumn =
    draft?.effectiveAtColumn !== undefined
      ? draft.effectiveAtColumn
      : existing?.effective_at_column ?? eventTimeColumn;
  const symbolColumn =
    draft?.symbolColumn !== undefined
      ? draft.symbolColumn
      : existing?.symbol_column ?? firstColumnFor("instrument_id");
  return { sourceToCanonical, unmappedColumns, eventTimeColumn, knownAtColumn, effectiveAtColumn, symbolColumn };
}

function DataConnectorSettingsPanel() {
  const [summary, setSummary] = useState<SettingsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [testingSkill, setTestingSkill] = useState<string | null>(null);
  const [runningSkill, setRunningSkill] = useState<string | null>(null);
  const [mappingSkill, setMappingSkill] = useState<string | null>(null);
  const [pitRuleSkill, setPitRuleSkill] = useState<string | null>(null);
  const [semanticsSkill, setSemanticsSkill] = useState<string | null>(null);
  const [instrumentSkill, setInstrumentSkill] = useState<string | null>(null);
  const [capabilitySkill, setCapabilitySkill] = useState<string | null>(null);
  const [useValidationSkill, setUseValidationSkill] = useState<string | null>(null);
  const [onboardingSkill, setOnboardingSkill] = useState<string | null>(null);
  const [storingSecretRef, setStoringSecretRef] = useState<string | null>(null);
  const [secretValues, setSecretValues] = useState<Record<string, string>>({});
  const [fieldMappingDrafts, setFieldMappingDrafts] = useState<Record<string, FieldMappingDraft>>({});
  const [pitRuleDrafts, setPitRuleDrafts] = useState<Record<string, PitRuleDraft>>({});
  const [genericRestDraft, setGenericRestDraft] = useState<GenericRestDraft>(DEFAULT_GENERIC_REST_DRAFT);
  const [stooqDraft, setStooqDraft] = useState<StooqDraft>(DEFAULT_STOOQ_DRAFT);
  const [binancePublicDraft, setBinancePublicDraft] =
    useState<BinancePublicDraft>(DEFAULT_BINANCE_PUBLIC_DRAFT);
  const [registeringGenericRest, setRegisteringGenericRest] = useState(false);
  const [registeringStooq, setRegisteringStooq] = useState(false);
  const [registeringBinancePublic, setRegisteringBinancePublic] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    authFetch("/api/research-os/settings/summary")
      .then((r) => r.json())
      .then((j) => setSummary(j))
      .catch((e) => setResult(`✗ settings summary: ${String(e)}`))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const storeSecretValue = async (skill: IngestionSkillSummary, secretRef: string) => {
    const value = (secretValues[secretRef] || "").trim();
    if (!value) {
      setResult(`✗ ${secretRef}: secret value required`);
      return;
    }
    setStoringSecretRef(secretRef);
    setResult(`storing ${secretRef}…`);
    try {
      const res = await authFetch("/api/research-os/settings/secret_values", {
        method: "POST",
        body: JSON.stringify({
          secret_ref: secretRef,
          scope: skill.permission_scope || "market_data:read",
          secret_value: value,
          affected_skills: [skill.skill_id],
          connector_scope_review: skill.source_ref,
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setSecretValues((current) => ({ ...current, [secretRef]: "" }));
        setResult(`✓ ${j.secret_ref}: stored in ${j.keystore_ref} · ${j.keystore_backend}`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${secretRef}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${secretRef}: ${String(e)}`);
    } finally {
      setStoringSecretRef(null);
    }
  };

  const testConnector = async (skillId: string) => {
    setTestingSkill(skillId);
    setResult(`testing ${skillId}…`);
    try {
      const res = await authFetch("/api/research-os/settings/data_connector_checks", {
        method: "POST",
        body: JSON.stringify({ skill_id: skillId }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(
          `${j.ok ? "✓" : "✗"} ${j.skill_id}: ${j.status}/${j.health_status} · ${j.check_ref}${
            j.error_code ? ` · ${j.error_code}` : ""
          }`,
        );
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skillId}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skillId}: ${String(e)}`);
    } finally {
      setTestingSkill(null);
    }
  };

  const runIngestionSkill = async (skillId: string, connectorCheckRef?: string) => {
    if (!connectorCheckRef) return;
    setRunningSkill(skillId);
    setResult(`running ${skillId}…`);
    try {
      const res = await authFetch("/api/research-os/settings/ingestion_skill_runs", {
        method: "POST",
        body: JSON.stringify({ skill_id: skillId, connector_check_ref: connectorCheckRef }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(
          `✓ ${j.skill_id}: ${j.dataset_version_ref} · rows ${j.row_count} · ${j.update_ref}`,
        );
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skillId}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skillId}: ${String(e)}`);
    } finally {
      setRunningSkill(null);
    }
  };

  const updateFieldMappingRole = (skillId: string, column: string, canonical: string) => {
    setFieldMappingDrafts((current) => {
      const draft = current[skillId] ?? {};
      return {
        ...current,
        [skillId]: {
          ...draft,
          sourceToCanonical: {
            ...(draft.sourceToCanonical ?? {}),
            [column]: canonical,
          },
        },
      };
    });
  };

  const updateFieldMappingDraft = (skillId: string, key: keyof FieldMappingDraft, value: string) => {
    setFieldMappingDrafts((current) => ({
      ...current,
      [skillId]: {
        ...(current[skillId] ?? {}),
        [key]: value,
      },
    }));
  };

  const updatePitRuleDraft = (skillId: string, key: keyof PitRuleDraft, value: string) => {
    setPitRuleDrafts((current) => ({
      ...current,
      [skillId]: {
        ...(current[skillId] ?? {}),
        [key]: value,
      },
    }));
  };

  const updateGenericRestDraft = (key: keyof GenericRestDraft, value: string) => {
    setGenericRestDraft((current) => ({ ...current, [key]: value }));
  };

  const updateStooqDraft = (key: keyof StooqDraft, value: string) => {
    setStooqDraft((current) => ({ ...current, [key]: value }));
  };

  const updateBinancePublicDraft = (key: keyof BinancePublicDraft, value: string) => {
    setBinancePublicDraft((current) => ({ ...current, [key]: value }));
  };

  const registerGenericRestConnector = async () => {
    const draft = genericRestDraft;
    const sourceRef = draft.sourceRef.trim();
    const skillId = draft.skillId.trim();
    const yaml = draft.genericRestYaml.trim();
    if (!sourceRef || !skillId || !yaml) {
      setResult("✗ generic_rest: source_ref, skill_id, and YAML are required");
      return;
    }
    setRegisteringGenericRest(true);
    setResult(`registering ${skillId}…`);
    try {
      const sourceRes = await authFetch("/api/research-os/settings/data_sources", {
        method: "POST",
        body: JSON.stringify({
          source_ref: sourceRef,
          license: draft.license.trim() || "user_provided",
          redistribution_rights: "restricted:user_supplied",
          rate_limit: draft.rateLimit.trim() || null,
          tos_constraints: draft.tosConstraints.trim() || "user_supplied_terms",
          commercial_use_status: draft.commercialUseStatus.trim() || "user_responsibility",
          retention_policy: draft.retentionPolicy.trim() || "retain:research-cache",
          source_owner: draft.sourceOwner.trim() || "user",
          source_url_or_path: draft.sourceUrl.trim() || null,
        }),
      });
      const sourceBody = await sourceRes.json().catch(() => ({}));
      if (!sourceRes.ok) {
        const detail =
          typeof sourceBody.detail === "string" ? sourceBody.detail : JSON.stringify(sourceBody.detail ?? sourceBody);
        setResult(`✗ ${sourceRef}: ${detail || `HTTP ${sourceRes.status}`}`);
        return;
      }

      const connectorConfig: Record<string, string> = {
        connector_name: "generic_rest",
        auth_mode: "none",
        generic_rest_yaml: yaml,
        data_kind: draft.dataKind.trim() || "ohlcv",
        symbol: draft.symbol.trim() || "DEMO",
        market: draft.market.trim() || "custom",
      };
      if (draft.interval.trim()) connectorConfig.interval = draft.interval.trim();
      if (draft.start.trim()) connectorConfig.start = draft.start.trim();
      if (draft.end.trim()) connectorConfig.end = draft.end.trim();

      const skillRes = await authFetch("/api/research-os/settings/ingestion_skills", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skillId,
          source_type: "generic_rest_api",
          source_ref: sourceRef,
          connector_config: connectorConfig,
          schema_mapping_ref: draft.schemaMappingRef.trim() || `schema_map:${skillId}`,
          secret_refs: [],
          refresh_mode: "manual",
          data_quality_tests: ["not_null:ts", "not_null:close"],
          pit_bitemporal_rules_ref: draft.pitBitemporalRulesRef.trim() || `pit:${skillId}`,
          output_dataset_id: draft.outputDatasetId.trim() || `dataset:${skillId}`,
          owner: "settings",
          version: "1",
          lifecycle_state: "active",
          freshness_status: "unknown",
          permission_scope: draft.permissionScope.trim() || "market_data:read",
          dependency_lock_ref: `deps:generic-rest:${skillId}:v1`,
          schedule_owner: "scheduler:manual",
          rollback_plan_ref: `rollback:generic-rest:${skillId}:v1`,
        }),
      });
      const skillBody = await skillRes.json().catch(() => ({}));
      if (!skillRes.ok) {
        const detail =
          typeof skillBody.detail === "string" ? skillBody.detail : JSON.stringify(skillBody.detail ?? skillBody);
        setResult(`✗ ${skillId}: ${detail || `HTTP ${skillRes.status}`} · source recorded: ${sourceBody.source_ref}`);
        load();
        return;
      }

      setResult(`✓ ${skillBody.skill_id}: Generic REST metadata registered · source ${sourceBody.source_ref}`);
      load();
    } catch (e) {
      setResult(`✗ generic_rest: ${String(e)}`);
    } finally {
      setRegisteringGenericRest(false);
    }
  };

  const registerStooqConnector = async () => {
    const draft = stooqDraft;
    const sourceRef = draft.sourceRef.trim();
    const skillId = draft.skillId.trim();
    const symbol = draft.symbol.trim();
    if (!sourceRef || !skillId || !symbol) {
      setResult("✗ stooq: source_ref, skill_id, and symbol are required");
      return;
    }
    setRegisteringStooq(true);
    setResult(`registering ${skillId}…`);
    try {
      const sourceRes = await authFetch("/api/research-os/settings/data_sources", {
        method: "POST",
        body: JSON.stringify({
          source_ref: sourceRef,
          license: draft.license.trim() || "stooq_public_terms",
          redistribution_rights: "restricted:public_terms",
          rate_limit: draft.rateLimit.trim() || "60/min",
          tos_constraints: draft.tosConstraints.trim() || "stooq_public_market_data_terms",
          commercial_use_status: draft.commercialUseStatus.trim() || "user_responsibility",
          retention_policy: draft.retentionPolicy.trim() || "retain:research-cache",
          source_owner: draft.sourceOwner.trim() || "stooq",
          source_url_or_path: draft.sourceUrl.trim() || "https://stooq.com/q/d/l/",
        }),
      });
      const sourceBody = await sourceRes.json().catch(() => ({}));
      if (!sourceRes.ok) {
        const detail =
          typeof sourceBody.detail === "string" ? sourceBody.detail : JSON.stringify(sourceBody.detail ?? sourceBody);
        setResult(`✗ ${sourceRef}: ${detail || `HTTP ${sourceRes.status}`}`);
        return;
      }

      const connectorConfig: Record<string, string> = {
        connector_name: "stooq",
        auth_mode: "none",
        data_kind: "ohlcv",
        symbol,
        interval: draft.interval.trim() || "1d",
        market: "stooq",
      };
      if (draft.start.trim()) connectorConfig.start = draft.start.trim();
      if (draft.end.trim()) connectorConfig.end = draft.end.trim();

      const skillRes = await authFetch("/api/research-os/settings/ingestion_skills", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skillId,
          source_type: "public_csv",
          source_ref: sourceRef,
          connector_config: connectorConfig,
          schema_mapping_ref: draft.schemaMappingRef.trim() || `schema_map:${skillId}`,
          secret_refs: [],
          refresh_mode: "manual",
          data_quality_tests: ["not_null:ts", "not_null:close"],
          pit_bitemporal_rules_ref: draft.pitBitemporalRulesRef.trim() || `pit:${skillId}`,
          output_dataset_id: draft.outputDatasetId.trim() || `dataset:${skillId}`,
          owner: "settings",
          version: "1",
          lifecycle_state: "active",
          freshness_status: "unknown",
          permission_scope: draft.permissionScope.trim() || "market_data:read",
          dependency_lock_ref: `deps:stooq:${skillId}:v1`,
          schedule_owner: "scheduler:manual",
          rollback_plan_ref: `rollback:stooq:${skillId}:v1`,
        }),
      });
      const skillBody = await skillRes.json().catch(() => ({}));
      if (!skillRes.ok) {
        const detail =
          typeof skillBody.detail === "string" ? skillBody.detail : JSON.stringify(skillBody.detail ?? skillBody);
        setResult(`✗ ${skillId}: ${detail || `HTTP ${skillRes.status}`} · source recorded: ${sourceBody.source_ref}`);
        load();
        return;
      }

      setResult(`✓ ${skillBody.skill_id}: Stooq metadata registered · source ${sourceBody.source_ref}`);
      load();
    } catch (e) {
      setResult(`✗ stooq: ${String(e)}`);
    } finally {
      setRegisteringStooq(false);
    }
  };

  const registerBinancePublicConnector = async () => {
    const draft = binancePublicDraft;
    const sourceRef = draft.sourceRef.trim();
    const skillId = draft.skillId.trim();
    const symbol = draft.symbol.trim().toUpperCase();
    const marketValue = draft.market.trim().toLowerCase();
    const market =
      marketValue === "binanceusdm" || marketValue === "binance_usdm" || marketValue === "usdm"
        ? "binanceusdm"
        : "binance_spot";
    const connectorName = market === "binanceusdm" ? "binance_rest_usdm" : "binance_rest_spot";
    const defaultSourceUrl =
      market === "binanceusdm" ? "https://fapi.binance.com/fapi/v1/klines" : "https://api.binance.com/api/v3/klines";
    if (!sourceRef || !skillId || !symbol) {
      setResult("✗ binance_public: source_ref, skill_id, and symbol are required");
      return;
    }
    setRegisteringBinancePublic(true);
    setResult(`registering ${skillId}…`);
    try {
      const sourceRes = await authFetch("/api/research-os/settings/data_sources", {
        method: "POST",
        body: JSON.stringify({
          source_ref: sourceRef,
          license: draft.license.trim() || "binance_public_api_terms",
          redistribution_rights: "restricted:public_terms",
          rate_limit: draft.rateLimit.trim() || "1200/min",
          tos_constraints: draft.tosConstraints.trim() || "binance_public_api_terms",
          commercial_use_status: draft.commercialUseStatus.trim() || "user_responsibility",
          retention_policy: draft.retentionPolicy.trim() || "retain:research-cache",
          source_owner: draft.sourceOwner.trim() || "binance",
          source_url_or_path: draft.sourceUrl.trim() || defaultSourceUrl,
        }),
      });
      const sourceBody = await sourceRes.json().catch(() => ({}));
      if (!sourceRes.ok) {
        const detail =
          typeof sourceBody.detail === "string" ? sourceBody.detail : JSON.stringify(sourceBody.detail ?? sourceBody);
        setResult(`✗ ${sourceRef}: ${detail || `HTTP ${sourceRes.status}`}`);
        return;
      }

      const connectorConfig: Record<string, string> = {
        connector_name: connectorName,
        auth_mode: "none",
        data_kind: draft.dataKind.trim() || "ohlcv",
        symbol,
        interval: draft.interval.trim() || "1m",
        market,
      };
      if (draft.start.trim()) connectorConfig.start = draft.start.trim();
      if (draft.end.trim()) connectorConfig.end = draft.end.trim();

      const skillRes = await authFetch("/api/research-os/settings/ingestion_skills", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skillId,
          source_type: "public_api",
          source_ref: sourceRef,
          connector_config: connectorConfig,
          schema_mapping_ref: draft.schemaMappingRef.trim() || `schema_map:${skillId}`,
          secret_refs: [],
          refresh_mode: "manual",
          data_quality_tests: ["not_null:ts", "not_null:close"],
          pit_bitemporal_rules_ref: draft.pitBitemporalRulesRef.trim() || `pit:${skillId}`,
          output_dataset_id: draft.outputDatasetId.trim() || `dataset:${skillId}`,
          owner: "settings",
          version: "1",
          lifecycle_state: "active",
          freshness_status: "unknown",
          permission_scope: draft.permissionScope.trim() || "market_data:read",
          dependency_lock_ref: `deps:binance-public:${skillId}:v1`,
          schedule_owner: "scheduler:manual",
          rollback_plan_ref: `rollback:binance-public:${skillId}:v1`,
        }),
      });
      const skillBody = await skillRes.json().catch(() => ({}));
      if (!skillRes.ok) {
        const detail =
          typeof skillBody.detail === "string" ? skillBody.detail : JSON.stringify(skillBody.detail ?? skillBody);
        setResult(`✗ ${skillId}: ${detail || `HTTP ${skillRes.status}`} · source recorded: ${sourceBody.source_ref}`);
        load();
        return;
      }

      setResult(`✓ ${skillBody.skill_id}: Binance public metadata registered · source ${sourceBody.source_ref}`);
      load();
    } catch (e) {
      setResult(`✗ binance_public: ${String(e)}`);
    } finally {
      setRegisteringBinancePublic(false);
    }
  };

  const recordFieldMapping = async (
    skill: IngestionSkillSummary,
    schemaProbe?: DataConnectorSchemaProbeSummary,
    existingMapping?: DataConnectorFieldMappingSummary,
  ) => {
    if (!schemaProbe) return;
    const preview = fieldMappingPayloadPreview(schemaProbe, existingMapping, fieldMappingDrafts[skill.skill_id]);
    const eventTimeColumn = preview.eventTimeColumn || "";
    if (!eventTimeColumn) {
      setResult(`✗ ${skill.skill_id}: event_time column is required`);
      return;
    }
    setMappingSkill(skill.skill_id);
    setResult(`mapping ${skill.skill_id}…`);
    try {
      const res = await authFetch("/api/research-os/settings/data_connector_field_mappings", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skill.skill_id,
          source_ref: skill.source_ref,
          mapping_ref: skill.schema_mapping_ref,
          schema_probe_ref: schemaProbe.probe_ref,
          schema_signature_hash: schemaProbe.schema_signature_hash,
          source_to_canonical: preview.sourceToCanonical,
          event_time_column: eventTimeColumn,
          known_at_column: nullableColumn(preview.knownAtColumn),
          effective_at_column: nullableColumn(preview.effectiveAtColumn),
          symbol_column: nullableColumn(preview.symbolColumn),
          unmapped_columns: preview.unmappedColumns,
          mapping_method: fieldMappingDrafts[skill.skill_id]?.mappingMethod || "manual",
          pit_bitemporal_candidate_ref: `pit_candidate:${skill.skill_id}`,
          evidence_refs: [schemaProbe.probe_ref],
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(`✓ ${j.skill_id}: ${j.mapping_ref} · ${Object.keys(j.source_to_canonical ?? {}).length} fields`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skill.skill_id}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skill.skill_id}: ${String(e)}`);
    } finally {
      setMappingSkill(null);
    }
  };

  const recordPitRule = async (skill: IngestionSkillSummary, fieldMapping?: DataConnectorFieldMappingSummary) => {
    if (!fieldMapping) return;
    const draft = pitRuleDrafts[skill.skill_id] ?? {};
    const eventTimeColumn = draft.eventTimeColumn !== undefined ? draft.eventTimeColumn : fieldMapping.event_time_column;
    const knownAtColumn = draft.knownAtColumn !== undefined ? draft.knownAtColumn : fieldMapping.known_at_column ?? "";
    const effectiveAtColumn =
      draft.effectiveAtColumn !== undefined ? draft.effectiveAtColumn : fieldMapping.effective_at_column ?? "";
    const knownAtPolicy =
      draft.knownAtPolicy || (knownAtColumn ? "source_column" : "connector_fetched_at");
    const effectiveAtPolicy = draft.effectiveAtPolicy || (effectiveAtColumn ? "source_column" : "event_time");
    setPitRuleSkill(skill.skill_id);
    setResult(`generating PIT rules ${skill.skill_id}…`);
    try {
      const res = await authFetch("/api/research-os/settings/pit_bitemporal_rules", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skill.skill_id,
          source_ref: skill.source_ref,
          field_mapping_ref: fieldMapping.mapping_ref,
          schema_probe_ref: fieldMapping.schema_probe_ref,
          event_time_column: eventTimeColumn,
          known_at_column: nullableColumn(knownAtColumn),
          effective_at_column: nullableColumn(effectiveAtColumn),
          known_at_policy: knownAtPolicy,
          effective_at_policy: effectiveAtPolicy,
          asof_join_policy: draft.asofJoinPolicy || "known_at_lte_decision_time_latest",
          timezone: draft.timezone || "UTC",
          calendar_ref: `calendar:${skill.source_ref}:default`,
          lookahead_guard_ref: `lookahead_guard:${skill.skill_id}:pit`,
          monotonicity_check_ref: `monotonicity:${fieldMapping.mapping_ref}:event_known`,
          restatement_policy: draft.restatementPolicy || "latest_known_at_before_decision_time",
          evidence_refs: [fieldMapping.mapping_ref, fieldMapping.schema_probe_ref],
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(`✓ ${j.skill_id}: ${j.rule_ref} · ${j.asof_join_policy}`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skill.skill_id}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skill.skill_id}: ${String(e)}`);
    } finally {
      setPitRuleSkill(null);
    }
  };

  const recordDatasetSemantics = async (
    skill: IngestionSkillSummary,
    update?: IngestionSkillUpdateSummary,
    pitRule?: DataConnectorPitBitemporalRuleSummary,
  ) => {
    if (!update || !pitRule) return;
    setSemanticsSkill(skill.skill_id);
    setResult(`recording dataset semantics ${skill.skill_id}…`);
    try {
      const res = await authFetch("/api/research-os/settings/dataset_semantics", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skill.skill_id,
          update_ref: update.update_ref,
          pit_bitemporal_rules_ref: pitRule.rule_ref,
          use_context: "confirmatory_validation",
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(`✓ ${j.skill_id ?? skill.skill_id}: ${j.dataset_ref} · ${j.pit_bitemporal_rules_ref}`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skill.skill_id}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skill.skill_id}: ${String(e)}`);
    } finally {
      setSemanticsSkill(null);
    }
  };

  const recordInstrumentSpec = async (skill: IngestionSkillSummary, dataset?: MarketDataDatasetSummary) => {
    if (!dataset) return;
    const assetClass = inferAssetClassForSkill(skill);
    const instrumentType = defaultInstrumentTypeForAsset(assetClass);
    setInstrumentSkill(skill.skill_id);
    setResult(`recording instrument ${skill.skill_id}…`);
    try {
      const res = await authFetch("/api/research-os/settings/instrument_specs", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skill.skill_id,
          dataset_ref: dataset.dataset_ref,
          asset_class: assetClass,
          instrument_type: instrumentType,
          currency: defaultCurrencyForAsset(assetClass),
          exchange_calendar_ref: `calendar:${skill.source_ref}:default`,
          symbol_mapping_ref: skill.schema_mapping_ref,
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(`✓ ${j.skill_id ?? skill.skill_id}: ${j.instrument_ref} · ${j.asset_class}/${j.instrument_type}`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skill.skill_id}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skill.skill_id}: ${String(e)}`);
    } finally {
      setInstrumentSkill(null);
    }
  };

  const recordCapabilityMatrix = async (
    skill: IngestionSkillSummary,
    dataset?: MarketDataDatasetSummary,
    instrument?: MarketDataInstrumentSummary,
  ) => {
    if (!dataset || !instrument) return;
    setCapabilitySkill(skill.skill_id);
    setResult(`recording capability ${skill.skill_id}…`);
    try {
      const res = await authFetch("/api/research-os/settings/capability_matrices", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skill.skill_id,
          dataset_ref: dataset.dataset_ref,
          instrument_ref: instrument.instrument_ref,
          use_context: "confirmatory_validation",
          research: true,
          backtest: true,
          paper: true,
          testnet: false,
          live: false,
          long: true,
          short: false,
          leverage: false,
          options: instrument.instrument_type === "option",
          margin: ["future", "futures", "perpetual"].includes(instrument.instrument_type),
          borrow: false,
          data_availability: dataset.dataset_ref,
          cost_model_availability: `cost_model:${instrument.asset_class}:${instrument.instrument_type}:default`,
          execution_availability: "execution:paper_only",
          permission_requirement: skill.permission_scope,
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(`✓ ${j.skill_id ?? skill.skill_id}: ${j.matrix_ref} · ${j.use_context}`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skill.skill_id}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skill.skill_id}: ${String(e)}`);
    } finally {
      setCapabilitySkill(null);
    }
  };

  const recordMarketDataUseValidation = async (
    skill: IngestionSkillSummary,
    dataset?: MarketDataDatasetSummary,
    instrument?: MarketDataInstrumentSummary,
    capability?: MarketDataCapabilitySummary,
  ) => {
    if (!dataset || !instrument || !capability) return;
    setUseValidationSkill(skill.skill_id);
    setResult(`validating market data use ${skill.skill_id}…`);
    try {
      const res = await authFetch("/api/research-os/settings/market_data_use_validations", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skill.skill_id,
          dataset_ref: dataset.dataset_ref,
          instrument_ref: instrument.instrument_ref,
          capability_matrix_ref: capability.matrix_ref,
          use_context: "confirmatory_validation",
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(`✓ ${j.skill_id ?? skill.skill_id}: ${j.validation_ref} · ${j.use_context}`);
        load();
      } else {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
        setResult(`✗ ${skill.skill_id}: ${detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setResult(`✗ ${skill.skill_id}: ${String(e)}`);
    } finally {
      setUseValidationSkill(null);
    }
  };

  const runOnboarding = async (skillId: string) => {
    setOnboardingSkill(skillId);
    setResult(`onboarding ${skillId}…`);
    try {
      const res = await authFetch("/api/research-os/settings/data_connector_onboarding_runs", {
        method: "POST",
        body: JSON.stringify({ skill_id: skillId }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(
          `✓ ${skillId}: ${j.run_ref} · ${j.market_data_use_validation_ref} · steps ${(j.completed_steps || []).length}`,
        );
        load();
      } else {
        const detail = j.detail ?? j;
        const failedStep = typeof detail === "object" && detail ? detail.failed_step : "";
        const completed = typeof detail === "object" && detail ? detail.completed_steps : [];
        const error = typeof detail === "object" && detail ? detail.error : detail;
        setResult(
          `✗ ${skillId}: ${failedStep || "onboarding"} failed${
            Array.isArray(completed) && completed.length ? ` after ${completed.join(" → ")}` : ""
          } · ${typeof error === "string" ? error : JSON.stringify(error) || `HTTP ${res.status}`}`,
        );
      }
    } catch (e) {
      setResult(`✗ ${skillId}: ${String(e)}`);
    } finally {
      setOnboardingSkill(null);
    }
  };

  const checksBySkill = new Map<string, DataConnectorCheckSummary>();
  for (const check of summary?.data_connector_checks ?? []) {
    const existing = checksBySkill.get(check.skill_id);
    if (!existing || String(check.checked_at || "") > String(existing.checked_at || "")) {
      checksBySkill.set(check.skill_id, check);
    }
  }
  const updatesBySkill = new Map<string, IngestionSkillUpdateSummary>();
  for (const update of summary?.ingestion_skill_updates ?? []) {
    updatesBySkill.set(update.skill_ref, update);
  }
  const schemaProbesBySkill = new Map<string, DataConnectorSchemaProbeSummary>();
  for (const probe of summary?.data_connector_schema_probes ?? []) {
    const existing = schemaProbesBySkill.get(probe.skill_id);
    if (!existing || String(probe.probed_at || "") > String(existing.probed_at || "")) {
      schemaProbesBySkill.set(probe.skill_id, probe);
    }
  }
  const fieldMappingsBySkill = new Map<string, DataConnectorFieldMappingSummary>();
  for (const mapping of summary?.data_connector_field_mappings ?? []) {
    const existing = fieldMappingsBySkill.get(mapping.skill_id);
    if (!existing || String(mapping.mapped_at || "") > String(existing.mapped_at || "")) {
      fieldMappingsBySkill.set(mapping.skill_id, mapping);
    }
  }
  const pitRulesBySkill = new Map<string, DataConnectorPitBitemporalRuleSummary>();
  for (const rule of summary?.data_connector_pit_bitemporal_rules ?? []) {
    const existing = pitRulesBySkill.get(rule.skill_id);
    if (!existing || String(rule.generated_at || "") > String(existing.generated_at || "")) {
      pitRulesBySkill.set(rule.skill_id, rule);
    }
  }
  const marketDatasetsBySource = new Map<string, MarketDataDatasetSummary>();
  for (const dataset of summary?.market_data_datasets ?? []) {
    marketDatasetsBySource.set(dataset.source_ref, dataset);
  }
  const marketInstrumentsByMapping = new Map<string, MarketDataInstrumentSummary>();
  for (const instrument of summary?.market_data_instruments ?? []) {
    if (instrument.symbol_mapping_ref) marketInstrumentsByMapping.set(instrument.symbol_mapping_ref, instrument);
  }
  const marketCapabilitiesByShape = new Map<string, MarketDataCapabilitySummary>();
  for (const capability of summary?.market_data_capability_matrices ?? []) {
    marketCapabilitiesByShape.set(`${capability.asset_class}:${capability.instrument_type}`, capability);
  }
  const marketUseValidationsByCapability = new Map<string, MarketDataUseValidationSummary>();
  for (const validation of summary?.market_data_use_validations ?? []) {
    if (validation.capability_matrix_ref) {
      marketUseValidationsByCapability.set(validation.capability_matrix_ref, validation);
    }
  }
  const secretRefsByRef = new Map<string, SecretRefSummary>();
  for (const secret of summary?.secret_refs ?? []) {
    secretRefsByRef.set(secret.secret_ref, secret);
  }
  const storedSecretCount = (summary?.secret_refs ?? []).filter((secret) => secret.secret_value_stored).length;

  return (
    <section className="cc-card" data-data-connectors-panel>
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Data Connectors · Settings 连接测试</h2>
        <button type="button" className="cc-btn cc-btn--sm cc-btn--ghost" onClick={load}>
          ↻ refresh
        </button>
      </div>
      <div className="cc-row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <span className="cc-chip">secrets: {summary?.secret_ref_total ?? 0}</span>
        <span className="cc-chip">secret values: {storedSecretCount}</span>
        <span className="cc-chip">sources: {summary?.data_source_total ?? 0}</span>
        <span className="cc-chip">skills: {summary?.ingestion_skill_total ?? 0}</span>
        <span className="cc-chip">checks: {summary?.data_connector_check_total ?? 0}</span>
        <span className="cc-chip">schema probes: {summary?.data_connector_schema_probe_total ?? 0}</span>
        <span className="cc-chip">field mappings: {summary?.data_connector_field_mapping_total ?? 0}</span>
        <span className="cc-chip">PIT rules: {summary?.data_connector_pit_bitemporal_rule_total ?? 0}</span>
        <span className="cc-chip">updates: {summary?.ingestion_skill_update_total ?? 0}</span>
        <span className="cc-chip">dataset semantics: {summary?.market_data_dataset_total ?? 0}</span>
        <span className="cc-chip">instruments: {summary?.market_data_instrument_total ?? 0}</span>
        <span className="cc-chip">capabilities: {summary?.market_data_capability_matrix_total ?? 0}</span>
        <span className="cc-chip">use validations: {summary?.market_data_use_validation_total ?? 0}</span>
        {loading && <span className="cc-dim" style={{ fontSize: 12 }}>loading…</span>}
      </div>

      <div
        data-binance-public-draft
        style={{
          padding: 10,
          marginBottom: 12,
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: 8,
        }}
      >
        <div className="cc-row" style={{ justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          <strong>Binance public REST</strong>
          <span className="cc-chip">no-auth</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          <input
            className="cc-input"
            data-binance-source-ref
            value={binancePublicDraft.sourceRef}
            onChange={(e) => updateBinancePublicDraft("sourceRef", e.target.value)}
            placeholder="datasource:binance:public"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-skill-id
            value={binancePublicDraft.skillId}
            onChange={(e) => updateBinancePublicDraft("skillId", e.target.value)}
            placeholder="ingest:binance:btcusdt:1m"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-symbol
            value={binancePublicDraft.symbol}
            onChange={(e) => updateBinancePublicDraft("symbol", e.target.value)}
            placeholder="BTCUSDT"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-market
            value={binancePublicDraft.market}
            onChange={(e) => updateBinancePublicDraft("market", e.target.value)}
            placeholder="binance_spot or binanceusdm"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-interval
            value={binancePublicDraft.interval}
            onChange={(e) => updateBinancePublicDraft("interval", e.target.value)}
            placeholder="1m"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-output-dataset
            value={binancePublicDraft.outputDatasetId}
            onChange={(e) => updateBinancePublicDraft("outputDatasetId", e.target.value)}
            placeholder="dataset:binance_spot_btcusdt_1m"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-schema-map
            value={binancePublicDraft.schemaMappingRef}
            onChange={(e) => updateBinancePublicDraft("schemaMappingRef", e.target.value)}
            placeholder="schema_map:binance:ohlcv"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-pit-ref
            value={binancePublicDraft.pitBitemporalRulesRef}
            onChange={(e) => updateBinancePublicDraft("pitBitemporalRulesRef", e.target.value)}
            placeholder="pit:binance:klines"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-source-url
            value={binancePublicDraft.sourceUrl}
            onChange={(e) => updateBinancePublicDraft("sourceUrl", e.target.value)}
            placeholder="https://api.binance.com/api/v3/klines"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-rate-limit
            value={binancePublicDraft.rateLimit}
            onChange={(e) => updateBinancePublicDraft("rateLimit", e.target.value)}
            placeholder="1200/min"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-start
            value={binancePublicDraft.start}
            onChange={(e) => updateBinancePublicDraft("start", e.target.value)}
            placeholder="start optional"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-binance-end
            value={binancePublicDraft.end}
            onChange={(e) => updateBinancePublicDraft("end", e.target.value)}
            placeholder="end optional"
            style={{ padding: 6 }}
          />
        </div>
        <div className="cc-row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="cc-btn cc-btn--sm cc-btn--primary"
            data-register-binance-public
            disabled={registeringBinancePublic}
            onClick={registerBinancePublicConnector}
          >
            {registeringBinancePublic ? "登记中…" : "Register Binance"}
          </button>
        </div>
      </div>

      <div
        data-stooq-draft
        style={{
          padding: 10,
          marginBottom: 12,
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: 8,
        }}
      >
        <div className="cc-row" style={{ justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          <strong>Stooq public daily bars</strong>
          <span className="cc-chip">no-auth</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          <input
            className="cc-input"
            data-stooq-source-ref
            value={stooqDraft.sourceRef}
            onChange={(e) => updateStooqDraft("sourceRef", e.target.value)}
            placeholder="datasource:stooq:public"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-skill-id
            value={stooqDraft.skillId}
            onChange={(e) => updateStooqDraft("skillId", e.target.value)}
            placeholder="ingest:stooq:aapl:daily"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-symbol
            value={stooqDraft.symbol}
            onChange={(e) => updateStooqDraft("symbol", e.target.value)}
            placeholder="AAPL.US"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-output-dataset
            value={stooqDraft.outputDatasetId}
            onChange={(e) => updateStooqDraft("outputDatasetId", e.target.value)}
            placeholder="dataset:stooq_aapl_daily"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-schema-map
            value={stooqDraft.schemaMappingRef}
            onChange={(e) => updateStooqDraft("schemaMappingRef", e.target.value)}
            placeholder="schema_map:stooq:ohlcv"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-pit-ref
            value={stooqDraft.pitBitemporalRulesRef}
            onChange={(e) => updateStooqDraft("pitBitemporalRulesRef", e.target.value)}
            placeholder="pit:stooq:daily"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-source-url
            value={stooqDraft.sourceUrl}
            onChange={(e) => updateStooqDraft("sourceUrl", e.target.value)}
            placeholder="https://stooq.com/q/d/l/"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-rate-limit
            value={stooqDraft.rateLimit}
            onChange={(e) => updateStooqDraft("rateLimit", e.target.value)}
            placeholder="60/min"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-start
            value={stooqDraft.start}
            onChange={(e) => updateStooqDraft("start", e.target.value)}
            placeholder="start optional"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-stooq-end
            value={stooqDraft.end}
            onChange={(e) => updateStooqDraft("end", e.target.value)}
            placeholder="end optional"
            style={{ padding: 6 }}
          />
        </div>
        <div className="cc-row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="cc-btn cc-btn--sm cc-btn--primary"
            data-register-stooq
            disabled={registeringStooq}
            onClick={registerStooqConnector}
          >
            {registeringStooq ? "登记中…" : "Register Stooq"}
          </button>
        </div>
      </div>

      <div
        data-generic-rest-draft
        style={{
          padding: 10,
          marginBottom: 12,
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: 8,
        }}
      >
        <div className="cc-row" style={{ justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          <strong>Generic REST YAML</strong>
          <span className="cc-chip">no-auth</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          <input
            className="cc-input"
            data-generic-rest-source-ref
            value={genericRestDraft.sourceRef}
            onChange={(e) => updateGenericRestDraft("sourceRef", e.target.value)}
            placeholder="datasource:custom:rest"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-skill-id
            value={genericRestDraft.skillId}
            onChange={(e) => updateGenericRestDraft("skillId", e.target.value)}
            placeholder="ingest:custom:bars"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-source-url
            value={genericRestDraft.sourceUrl}
            onChange={(e) => updateGenericRestDraft("sourceUrl", e.target.value)}
            placeholder="https://example.invalid"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-output-dataset
            value={genericRestDraft.outputDatasetId}
            onChange={(e) => updateGenericRestDraft("outputDatasetId", e.target.value)}
            placeholder="dataset:custom_bars"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-schema-map
            value={genericRestDraft.schemaMappingRef}
            onChange={(e) => updateGenericRestDraft("schemaMappingRef", e.target.value)}
            placeholder="schema_map:custom:bars"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-pit-ref
            value={genericRestDraft.pitBitemporalRulesRef}
            onChange={(e) => updateGenericRestDraft("pitBitemporalRulesRef", e.target.value)}
            placeholder="pit:custom:bars"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-symbol
            value={genericRestDraft.symbol}
            onChange={(e) => updateGenericRestDraft("symbol", e.target.value)}
            placeholder="DEMO"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-market
            value={genericRestDraft.market}
            onChange={(e) => updateGenericRestDraft("market", e.target.value)}
            placeholder="custom"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-interval
            value={genericRestDraft.interval}
            onChange={(e) => updateGenericRestDraft("interval", e.target.value)}
            placeholder="1d"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-rate-limit
            value={genericRestDraft.rateLimit}
            onChange={(e) => updateGenericRestDraft("rateLimit", e.target.value)}
            placeholder="600/min"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-start
            value={genericRestDraft.start}
            onChange={(e) => updateGenericRestDraft("start", e.target.value)}
            placeholder="start optional"
            style={{ padding: 6 }}
          />
          <input
            className="cc-input"
            data-generic-rest-end
            value={genericRestDraft.end}
            onChange={(e) => updateGenericRestDraft("end", e.target.value)}
            placeholder="end optional"
            style={{ padding: 6 }}
          />
        </div>
        <textarea
          className="cc-input"
          data-generic-rest-yaml
          value={genericRestDraft.genericRestYaml}
          onChange={(e) => updateGenericRestDraft("genericRestYaml", e.target.value)}
          rows={12}
          style={{ width: "100%", marginTop: 8, padding: 8, fontFamily: "monospace", fontSize: 12 }}
        />
        <div className="cc-row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="cc-btn cc-btn--sm cc-btn--primary"
            data-register-generic-rest
            disabled={registeringGenericRest}
            onClick={registerGenericRestConnector}
          >
            {registeringGenericRest ? "登记中…" : "Register Generic REST"}
          </button>
        </div>
      </div>

      <div className="cc-row" style={{ flexWrap: "wrap", gap: 10 }}>
        {(summary?.ingestion_skills ?? []).map((skill) => {
          const latest = checksBySkill.get(skill.skill_id);
          const update = updatesBySkill.get(skill.skill_id);
          const schemaProbe = schemaProbesBySkill.get(skill.skill_id);
          const fieldMapping = fieldMappingsBySkill.get(skill.skill_id);
          const pitRule = pitRulesBySkill.get(skill.skill_id);
          const marketDataset = marketDatasetsBySource.get(skill.source_ref);
          const marketInstrument = marketInstrumentsByMapping.get(skill.schema_mapping_ref || "");
          const marketCapability = marketInstrument
            ? marketCapabilitiesByShape.get(`${marketInstrument.asset_class}:${marketInstrument.instrument_type}`)
            : undefined;
          const marketUseValidation = marketCapability
            ? marketUseValidationsByCapability.get(marketCapability.matrix_ref)
            : undefined;
          const mappingDraft = fieldMappingDrafts[skill.skill_id] ?? {};
          const mappingPreview = fieldMappingPayloadPreview(schemaProbe, fieldMapping, mappingDraft);
          const pitDraft = pitRuleDrafts[skill.skill_id] ?? {};
          const pitEventTimeColumn =
            pitDraft.eventTimeColumn !== undefined ? pitDraft.eventTimeColumn : fieldMapping?.event_time_column ?? "";
          const pitKnownAtColumn =
            pitDraft.knownAtColumn !== undefined ? pitDraft.knownAtColumn : fieldMapping?.known_at_column ?? "";
          const pitEffectiveAtColumn =
            pitDraft.effectiveAtColumn !== undefined
              ? pitDraft.effectiveAtColumn
              : fieldMapping?.effective_at_column ?? "";
          const pitKnownAtPolicy =
            pitDraft.knownAtPolicy || (pitKnownAtColumn ? "source_column" : "connector_fetched_at");
          const pitEffectiveAtPolicy =
            pitDraft.effectiveAtPolicy || (pitEffectiveAtColumn ? "source_column" : "event_time");
          const pitAsofPolicy = pitDraft.asofJoinPolicy || "known_at_lte_decision_time_latest";
          const pitRestatementPolicy = pitDraft.restatementPolicy || "latest_known_at_before_decision_time";
          const timeAxisColumns = schemaProbe?.columns ?? [];
          return (
            <div
              key={skill.skill_id}
              data-data-connector-skill={skill.skill_id}
              style={{
                padding: 10,
                minWidth: 260,
                flex: "1 1 260px",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: 8,
              }}
            >
              <div className="cc-row" style={{ justifyContent: "space-between", gap: 8 }}>
                <span className="cc-mono" style={{ fontSize: 12 }}>{skill.skill_id}</span>
                <span className={`cc-chip ${skill.lifecycle_state === "active" ? "cc-chip--success" : ""}`}>
                  {skill.lifecycle_state || "unknown"}
                </span>
              </div>
              <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                <div>source: <code>{skill.source_ref}</code></div>
                <div>mapping: <code>{skill.schema_mapping_ref || "—"}</code></div>
                <div>dataset: <code>{skill.output_dataset_id || "—"}</code></div>
                <div>scope: <code>{skill.permission_scope || "—"}</code></div>
                <div>secrets: <code>{(skill.secret_refs || []).join(", ") || "—"}</code></div>
              </div>
              {(skill.secret_refs || []).map((secretRef) => {
                const secret = secretRefsByRef.get(secretRef);
                const stored = Boolean(secret?.secret_value_stored);
                return (
                  <div
                    key={secretRef}
                    data-secret-value-row={secretRef}
                    style={{
                      marginTop: 8,
                      padding: 8,
                      border: "1px solid rgba(255,255,255,0.1)",
                      borderRadius: 6,
                    }}
                  >
                    <div className="cc-row" style={{ justifyContent: "space-between", gap: 8 }}>
                      <code style={{ fontSize: 11 }}>{secretRef}</code>
                      <span className={`cc-chip ${stored ? "cc-chip--success" : ""}`}>
                        value: {stored ? "stored" : "missing"}
                      </span>
                    </div>
                    <div className="cc-dim" style={{ fontSize: 11, marginTop: 4 }}>
                      backend: <code>{secret?.keystore_backend || "—"}</code> · refs:{" "}
                      <code>{(secret?.keystore_refs || []).join(", ") || "—"}</code>
                    </div>
                    <div className="cc-row" style={{ gap: 6, marginTop: 6 }}>
                      <input
                        className="cc-input"
                        data-secret-value-input={secretRef}
                        type="password"
                        value={secretValues[secretRef] || ""}
                        onChange={(e) =>
                          setSecretValues((current) => ({ ...current, [secretRef]: e.target.value }))
                        }
                        placeholder="secret value"
                        style={{ minWidth: 0, flex: "1 1 160px", padding: 6 }}
                      />
                      <button
                        type="button"
                        className="cc-btn cc-btn--sm"
                        data-store-secret-value={secretRef}
                        disabled={storingSecretRef === secretRef || !(secretValues[secretRef] || "").trim()}
                        onClick={() => storeSecretValue(skill, secretRef)}
                      >
                        {storingSecretRef === secretRef ? "存储中…" : "Store value"}
                      </button>
                    </div>
                  </div>
                );
              })}
              <div className="cc-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                <span className="cc-chip">freshness: {skill.freshness_status || "unknown"}</span>
                <span className="cc-chip">drift: {skill.schema_drift_status || "unknown"}</span>
                <span className={`cc-chip ${latest?.status === "ok" ? "cc-chip--success" : ""}`}>
                  health: {latest ? `${latest.status}/${latest.health_status}` : "untested"}
                </span>
              </div>
              {latest?.error_code && (
                <div className="cc-dim" style={{ fontSize: 11, marginTop: 6 }}>
                  last error: <code>{latest.error_code}</code>
                </div>
              )}
              {latest?.check_ref && (
                <div className="cc-dim" style={{ fontSize: 11, marginTop: 6 }}>
                  check: <code>{latest.check_ref}</code>
                </div>
              )}
              {schemaProbe && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>schema: <code>{schemaProbe.probe_ref}</code></div>
                  <div>drift: <code>{schemaProbe.drift_status || "unknown"}</code></div>
                  <div>columns: <code>{schemaProbe.columns?.length ?? "—"}</code></div>
                </div>
              )}
              {schemaProbe && (
                <div
                  data-field-mapping-wizard={skill.skill_id}
                  style={{
                    marginTop: 8,
                    padding: 8,
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 6,
                  }}
                >
                  <div className="cc-row" style={{ justifyContent: "space-between", gap: 8 }}>
                    <strong style={{ fontSize: 12 }}>Field mapping</strong>
                    <span className="cc-chip">unmapped: {mappingPreview.unmappedColumns.length}</span>
                  </div>
                  <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                    {(schemaProbe.columns ?? []).map((column) => (
                      <label
                        key={column}
                        className="cc-row"
                        style={{ alignItems: "center", justifyContent: "space-between", gap: 8 }}
                      >
                        <code style={{ fontSize: 11 }}>{column}</code>
                        <select
                          className="cc-input"
                          data-field-mapping-role={`${skill.skill_id}:${column}`}
                          value={fieldMappingRoleForColumn(column, mappingDraft, fieldMapping)}
                          onChange={(e) => updateFieldMappingRole(skill.skill_id, column, e.target.value)}
                          style={{ minWidth: 150, padding: 6 }}
                        >
                          {CANONICAL_FIELD_OPTIONS.map((option) => (
                            <option key={option || "ignore"} value={option}>
                              {option || "ignore"}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                  <div className="cc-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                    <select
                      className="cc-input"
                      data-field-mapping-event-time={skill.skill_id}
                      value={mappingPreview.eventTimeColumn}
                      onChange={(e) => updateFieldMappingDraft(skill.skill_id, "eventTimeColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">event time</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-field-mapping-known-at={skill.skill_id}
                      value={mappingPreview.knownAtColumn}
                      onChange={(e) => updateFieldMappingDraft(skill.skill_id, "knownAtColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">known at</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-field-mapping-effective-at={skill.skill_id}
                      value={mappingPreview.effectiveAtColumn}
                      onChange={(e) => updateFieldMappingDraft(skill.skill_id, "effectiveAtColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">effective at</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-field-mapping-symbol={skill.skill_id}
                      value={mappingPreview.symbolColumn}
                      onChange={(e) => updateFieldMappingDraft(skill.skill_id, "symbolColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">symbol</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
              {fieldMapping && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>field map: <code>{fieldMapping.mapping_ref}</code></div>
                  <div>event time: <code>{fieldMapping.event_time_column || "—"}</code></div>
                  <div>mapped: <code>{Object.keys(fieldMapping.source_to_canonical ?? {}).length}</code></div>
                  <div>unmapped: <code>{fieldMapping.unmapped_columns?.length ?? 0}</code></div>
                </div>
              )}
              {fieldMapping && (
                <div
                  data-pit-rule-wizard={skill.skill_id}
                  style={{
                    marginTop: 8,
                    padding: 8,
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 6,
                  }}
                >
                  <strong style={{ fontSize: 12 }}>PIT rule</strong>
                  <div className="cc-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    <select
                      className="cc-input"
                      data-pit-event-time={skill.skill_id}
                      value={pitEventTimeColumn}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "eventTimeColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">event time</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-pit-known-at={skill.skill_id}
                      value={pitKnownAtColumn}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "knownAtColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">known at</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-pit-effective-at={skill.skill_id}
                      value={pitEffectiveAtColumn}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "effectiveAtColumn", e.target.value)}
                      style={{ minWidth: 130, padding: 6 }}
                    >
                      <option value="">effective at</option>
                      {timeAxisColumns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-pit-known-policy={skill.skill_id}
                      value={pitKnownAtPolicy}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "knownAtPolicy", e.target.value)}
                      style={{ minWidth: 170, padding: 6 }}
                    >
                      {PIT_TIME_POLICY_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-pit-effective-policy={skill.skill_id}
                      value={pitEffectiveAtPolicy}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "effectiveAtPolicy", e.target.value)}
                      style={{ minWidth: 170, padding: 6 }}
                    >
                      {PIT_TIME_POLICY_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-pit-asof-policy={skill.skill_id}
                      value={pitAsofPolicy}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "asofJoinPolicy", e.target.value)}
                      style={{ minWidth: 220, padding: 6 }}
                    >
                      {PIT_ASOF_POLICY_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                    <select
                      className="cc-input"
                      data-pit-restatement-policy={skill.skill_id}
                      value={pitRestatementPolicy}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "restatementPolicy", e.target.value)}
                      style={{ minWidth: 220, padding: 6 }}
                    >
                      {PIT_RESTATEMENT_POLICY_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                    <input
                      className="cc-input"
                      data-pit-timezone={skill.skill_id}
                      value={pitDraft.timezone ?? "UTC"}
                      onChange={(e) => updatePitRuleDraft(skill.skill_id, "timezone", e.target.value)}
                      style={{ width: 90, padding: 6 }}
                    />
                  </div>
                </div>
              )}
              {pitRule && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>PIT: <code>{pitRule.rule_ref}</code></div>
                  <div>as-of: <code>{pitRule.asof_join_policy || "—"}</code></div>
                  <div>known: <code>{pitRule.known_at_column || pitRule.known_at_policy || "—"}</code></div>
                  <div>effective: <code>{pitRule.effective_at_column || pitRule.effective_at_policy || "—"}</code></div>
                </div>
              )}
              {marketDataset && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>semantics: <code>{marketDataset.dataset_ref}</code></div>
                  <div>known/effective: <code>{marketDataset.known_at_ref || "—"}</code> / <code>{marketDataset.effective_at_ref || "—"}</code></div>
                  <div>PIT ref: <code>{marketDataset.pit_bitemporal_rules_ref || "—"}</code></div>
                </div>
              )}
              {marketInstrument && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>instrument: <code>{marketInstrument.instrument_ref}</code></div>
                  <div>asset/type: <code>{marketInstrument.asset_class}</code> / <code>{marketInstrument.instrument_type}</code></div>
                  <div>calendar: <code>{marketInstrument.exchange_calendar_ref || "—"}</code></div>
                </div>
              )}
              {marketCapability && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>capability: <code>{marketCapability.matrix_ref}</code></div>
                  <div>research/backtest/paper: <code>{String(Boolean(marketCapability.research))}</code> / <code>{String(Boolean(marketCapability.backtest))}</code> / <code>{String(Boolean(marketCapability.paper))}</code></div>
                  <div>live: <code>{String(Boolean(marketCapability.live))}</code></div>
                </div>
              )}
              {marketUseValidation && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>use validation: <code>{marketUseValidation.validation_ref}</code></div>
                  <div>context: <code>{marketUseValidation.use_context}</code></div>
                  <div>accepted: <code>{String(Boolean(marketUseValidation.accepted))}</code></div>
                </div>
              )}
              {update && (
                <div className="cc-dim" style={{ fontSize: 11, lineHeight: 1.5, marginTop: 6 }}>
                  <div>dataset: <code>{update.dataset_version_ref || "—"}</code></div>
                  <div>quality: <code>{update.quality_verdict_ref || "—"}</code></div>
                  <div>time: <code>{update.known_at_ref || "—"}</code> / <code>{update.effective_at_ref || "—"}</code></div>
                  <div>rows: <code>{update.row_count ?? "—"}</code></div>
                </div>
              )}
              <div className="cc-row" style={{ gap: 8, marginTop: 8 }}>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm"
                  data-test-data-connector={skill.skill_id}
                  disabled={testingSkill === skill.skill_id}
                  onClick={() => testConnector(skill.skill_id)}
                  style={{ flex: "1 1 110px" }}
                >
                  {testingSkill === skill.skill_id ? "测试中…" : "测试连接"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--primary"
                  data-run-onboarding-skill={skill.skill_id}
                  disabled={onboardingSkill === skill.skill_id}
                  onClick={() => runOnboarding(skill.skill_id)}
                  style={{ flex: "1 1 140px" }}
                >
                  {onboardingSkill === skill.skill_id ? "接入中…" : "Run onboarding"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--ghost"
                  data-record-field-mapping={skill.skill_id}
                  disabled={mappingSkill === skill.skill_id || !schemaProbe?.probe_ref}
                  onClick={() => recordFieldMapping(skill, schemaProbe, fieldMapping)}
                  style={{ flex: "1 1 110px" }}
                >
                  {mappingSkill === skill.skill_id ? "映射中…" : "Record mapping"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--ghost"
                  data-record-pit-rule={skill.skill_id}
                  disabled={pitRuleSkill === skill.skill_id || !fieldMapping?.mapping_ref}
                  onClick={() => recordPitRule(skill, fieldMapping)}
                  style={{ flex: "1 1 110px" }}
                >
                  {pitRuleSkill === skill.skill_id ? "生成中…" : "PIT rules"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--ghost"
                  data-record-dataset-semantics={skill.skill_id}
                  disabled={semanticsSkill === skill.skill_id || !update?.update_ref || !pitRule?.rule_ref}
                  onClick={() => recordDatasetSemantics(skill, update, pitRule)}
                  style={{ flex: "1 1 130px" }}
                >
                  {semanticsSkill === skill.skill_id ? "登记中…" : "Dataset semantics"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--ghost"
                  data-record-instrument-spec={skill.skill_id}
                  disabled={instrumentSkill === skill.skill_id || !marketDataset?.dataset_ref}
                  onClick={() => recordInstrumentSpec(skill, marketDataset)}
                  style={{ flex: "1 1 120px" }}
                >
                  {instrumentSkill === skill.skill_id ? "登记中…" : "Instrument"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--ghost"
                  data-record-capability-matrix={skill.skill_id}
                  disabled={capabilitySkill === skill.skill_id || !marketDataset?.dataset_ref || !marketInstrument?.instrument_ref}
                  onClick={() => recordCapabilityMatrix(skill, marketDataset, marketInstrument)}
                  style={{ flex: "1 1 120px" }}
                >
                  {capabilitySkill === skill.skill_id ? "登记中…" : "Capability"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--ghost"
                  data-record-market-data-use={skill.skill_id}
                  disabled={
                    useValidationSkill === skill.skill_id ||
                    !marketDataset?.dataset_ref ||
                    !marketInstrument?.instrument_ref ||
                    !marketCapability?.matrix_ref
                  }
                  onClick={() => recordMarketDataUseValidation(skill, marketDataset, marketInstrument, marketCapability)}
                  style={{ flex: "1 1 130px" }}
                >
                  {useValidationSkill === skill.skill_id ? "验证中…" : "MarketDataUse"}
                </button>
                <button
                  type="button"
                  className="cc-btn cc-btn--sm cc-btn--primary"
                  data-run-ingestion-skill={skill.skill_id}
                  disabled={
                    runningSkill === skill.skill_id ||
                    latest?.status !== "ok" ||
                    !latest?.check_ref
                  }
                  onClick={() => runIngestionSkill(skill.skill_id, latest?.check_ref)}
                  style={{ flex: "1 1 110px" }}
                >
                  {runningSkill === skill.skill_id ? "更新中…" : "Run update"}
                </button>
              </div>
            </div>
          );
        })}
        {(summary?.ingestion_skills ?? []).length === 0 && (
          <span className="cc-dim" style={{ fontSize: 12 }}>
            无 IngestionSkill metadata（/api/research-os/settings/summary）
          </span>
        )}
      </div>

      {(summary?.data_sources ?? []).length > 0 && (
        <div style={{ marginTop: 12, overflowX: "auto" }}>
          <table style={{ width: "100%", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th>source</th>
                <th>license</th>
                <th>rate</th>
                <th>retention</th>
                <th>export/share</th>
              </tr>
            </thead>
            <tbody>
              {(summary?.data_sources ?? []).map((source) => (
                <tr key={source.source_ref}>
                  <td><code>{source.source_ref}</code></td>
                  <td>{source.license || "—"}</td>
                  <td>{source.rate_limit || "—"}</td>
                  <td>{source.retention_policy || "—"}</td>
                  <td>{source.export_allowed && source.share_allowed ? "allowed" : "restricted"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result && (
        <pre className="cc-code" data-data-connector-test-result style={{ marginTop: 12, fontSize: 11 }}>
          {result}
        </pre>
      )}
    </section>
  );
}

export default SettingsSecurityPage;
