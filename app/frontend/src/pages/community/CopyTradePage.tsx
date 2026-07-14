import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch, getStoredUser } from "../../lib/auth";

interface Master {
  master_id: string;
  user_id: string;
  display_name: string;
  description: string;
  asset_class: string;
  profit_share_pct: number;
  is_invite_only: boolean;
  invite_code?: string;
  follower_count: number;
  total_signals: number;
  metric_total_return?: number | null;
  metric_sharpe?: number | null;
  metric_max_drawdown?: number | null;
  author_username?: string;
  author_display_name?: string;
  created_at_utc: string;
}

interface Subscription {
  follower_id: string;
  master_id: string;
  invest_amount: number;
  per_order_max_usdt: number;
  status: string;
  master_display_name?: string;
  master_asset_class?: string;
  pnl_realized?: number;
}

interface Signal {
  signal_id: string;
  master_id: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number | null;
  order_type: string;
  status: string;
  published_at_utc: string;
}

interface RiskDisclosureProfile {
  profile_ref: string;
  required_acknowledgement_refs: string[];
  disclosures: Record<string, { ref: string; text: string }>;
  failure_modes: Record<string, { ref: string; text: string }>;
  recommendation: { ref: string; text: string };
  responsibility_boundary: {
    ref: string;
    parties: Record<string, string>;
  };
}

interface RiskConsentChallenge {
  challenge_ref: string;
  expires_at_utc: string;
  risk_profile: RiskDisclosureProfile;
}

interface RiskConsentResult {
  consent_event_ref: string;
  user_risk_choice_ref: string;
  activation_deadline_utc: string;
  runtime_promotion: Record<string, unknown> & {
    request_ref: string;
    subject_ref: string;
    asset_class: string;
    source_runtime: string;
    target_runtime: string;
    permission_gate_ref: string;
    order_guard_ref: string;
    idempotency_key: string;
    audit_record_ref: string;
    kill_switch_ref: string;
    secret_ref: string;
    responsibility_boundary_ref: string;
    mock_profile: string;
    required_evidence_refs: string[];
  };
}

interface RuntimePromotionResult {
  runtime_promotion_ref: string;
}

function responseError(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : (JSON.stringify(detail) ?? String(detail));
  }
  return fallback;
}

function disclosureItems(profile: RiskDisclosureProfile): Array<{ ref: string; text: string }> {
  return [
    ...Object.values(profile.disclosures),
    ...Object.values(profile.failure_modes),
    profile.recommendation,
    {
      ref: profile.responsibility_boundary.ref,
      text: Object.entries(profile.responsibility_boundary.parties)
        .map(([party, text]) => `${party}: ${text}`)
        .join(" "),
    },
  ];
}

export interface FillEconomics {
  event_ref: string;
  signal_ref: string;
  follower_ref: string;
  symbol: string;
  side: string;
  fill_status: string;
  filled_qty: number;
  cumulative_filled_qty: number;
  fill_price: number;
  commission: number;
  commission_asset: string;
  normalized_cost_usdt: number | null;
  cost_complete: boolean;
  realized_pnl_delta: number;
  realized_pnl_complete: boolean;
  fill_economics_complete: boolean;
  holding_cost_complete: boolean;
  total_economics_complete: boolean;
  occurred_at_utc: string;
}

const ASSETS = [
  { id: "", label: "全部" },
  { id: "crypto_perp", label: "加密永续" },
  { id: "crypto_spot", label: "加密现货" },
  { id: "equity_cn", label: "A股 (paper)" },
];

const SORTS = [
  { id: "followers", label: "粉丝数" },
  { id: "sharpe", label: "Sharpe" },
  { id: "return", label: "总收益" },
  { id: "signals", label: "信号数" },
  { id: "drawdown_low", label: "回撤低" },
  { id: "recent", label: "最新" },
];

export function CopyTradePage() {
  const me = getStoredUser();
  // 稳定身份代理：getStoredUser() 每次 render 返回新对象，直接进依赖数组会无限重拉。
  const userId = me?.user_id ?? null;
  const [asset, setAsset] = useState("");
  const [sortBy, setSortBy] = useState("followers");
  const [inviteOnly, setInviteOnly] = useState<string>(""); // "" / "public" / "invite"
  const [masters, setMasters] = useState<Master[]>([]);
  const [myMaster, setMyMaster] = useState<Master | null>(null);
  const [mySubs, setMySubs] = useState<Subscription[]>([]);
  const [myFills, setMyFills] = useState<FillEconomics[]>([]);
  const [fillsError, setFillsError] = useState<string | null>(null);
  const [recentSignals, setRecentSignals] = useState<Signal[]>([]);
  const [becomeOpen, setBecomeOpen] = useState(false);
  const [followOpen, setFollowOpen] = useState<Master | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);

  const reload = useCallback(() => {
    const q = new URLSearchParams({ sort_by: sortBy });
    if (asset) q.set("asset_class", asset);
    if (inviteOnly === "public") q.set("invite_only", "false");
    if (inviteOnly === "invite") q.set("invite_only", "true");
    fetch(`/api/copy_trade/masters?${q}`).then((r) => r.json()).then(setMasters).catch(() => setMasters([]));
    fetch(`/api/copy_trade/signals?limit=20`).then((r) => r.json()).then(setRecentSignals).catch(() => setRecentSignals([]));
    if (me) {
      authFetch("/api/copy_trade/me/master").then((r) => r.json()).then(setMyMaster).catch(() => setMyMaster(null));
      authFetch("/api/copy_trade/me/subscriptions").then((r) => r.json()).then(setMySubs).catch(() => setMySubs([]));
      authFetch("/api/copy_trade/fills?limit=50")
        .then(async (r) => {
          if (!r.ok) {
            const body = await r.json().catch(() => ({}));
            throw new Error(body.detail || `HTTP ${r.status}`);
          }
          const body = await r.json();
          if (!Array.isArray(body)) throw new Error("成交账本响应格式无效");
          setMyFills(body as FillEconomics[]);
          setFillsError(null);
        })
        .catch((error: unknown) => {
          setMyFills([]);
          setFillsError(error instanceof Error ? error.message : "成交账本不可用");
        });
    } else {
      setMyFills([]);
      setFillsError(null);
    }
  }, [asset, sortBy, inviteOnly, userId]);
  useEffect(reload, [reload]);

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title"><span className="cc-prompt">$</span>copy-trade</h1>
          <p className="cc-page-subtitle">
            带单大厅 · master 发信号 → follower 确认后跟随（走 follower 自己 keystore 真下单）· 私域支持 invite_code
          </p>
        </div>
        {me && !myMaster && (
          <button type="button" className="cc-btn cc-btn--accent" onClick={() => setBecomeOpen(true)}>
            注册成为 master →
          </button>
        )}
        {me && myMaster && (
          <button type="button" className="cc-btn cc-btn--accent" onClick={() => setPublishOpen(true)}>
            ⚡ 发布 signal
          </button>
        )}
      </div>

      {/* 我的 master / 我的跟单 简报 */}
      {me && (
        <>
          <div className="cc-grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 20 }}>
            <MasterSummaryCard master={myMaster} onClickPublish={() => setPublishOpen(true)} />
            <SubsSummaryCard subs={mySubs} />
          </div>
          <CopyTradeFillLedger fills={myFills} error={fillsError} />
        </>
      )}

      <div className="cc-row" style={{ gap: 16, marginBottom: 12 }}>
        <div className="cc-tabs" style={{ borderBottom: 0, margin: 0 }}>
          {ASSETS.map((a) => (
            <button key={a.id} type="button" className={`cc-tab${asset === a.id ? " active" : ""}`} onClick={() => setAsset(a.id)}>
              {a.label}
            </button>
          ))}
        </div>
        <div className="cc-spacer" />
        <select className="cc-select" style={{ width: 130 }} value={inviteOnly} onChange={(e) => setInviteOnly(e.target.value)}>
          <option value="">公开+私域</option>
          <option value="public">仅公开</option>
          <option value="invite">仅私域</option>
        </select>
        <select className="cc-select" style={{ width: 130 }} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
          {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </div>

      {masters.length === 0 ? (
        <div className="cc-card cc-dim">暂无 master · 第一个发布就是你。</div>
      ) : (
        <div className="cc-grid">
          {masters.map((m) => (
            <MasterCard key={m.master_id} master={m} canSubscribe={!!me} onSubscribe={() => setFollowOpen(m)} />
          ))}
        </div>
      )}

      {/* 最近 signals */}
      <section className="cc-section" style={{ marginTop: 24 }}>
        <div className="cc-section-header">
          <h2 className="cc-section-title">// 最新 signals</h2>
        </div>
        {recentSignals.length === 0 ? (
          <div className="cc-dim">尚未有 signal 发布</div>
        ) : (
          <table className="cc-table">
            <thead>
              <tr>
                <th>time</th>
                <th>master</th>
                <th>symbol</th>
                <th>side</th>
                <th align="right">qty</th>
                <th align="right">price</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {recentSignals.map((s) => (
                <tr key={s.signal_id}>
                  <td className="cc-dim" style={{ fontSize: 11 }}>{s.published_at_utc.slice(0, 19)}</td>
                  <td className="cc-mono" style={{ fontSize: 11 }}>{s.master_id.slice(0, 16)}</td>
                  <td className="cc-mono">{s.symbol}</td>
                  <td>
                    <span className={`cc-chip ${s.side === "buy" ? "cc-chip--success" : "cc-chip--danger"}`}>
                      {s.side}
                    </span>
                  </td>
                  <td align="right" className="cc-mono">{s.quantity}</td>
                  <td align="right" className="cc-mono">{s.price ?? "MKT"}</td>
                  <td><span className="cc-chip">{s.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {becomeOpen && <BecomeMasterModal onClose={() => { setBecomeOpen(false); reload(); }} />}
      {followOpen && <SubscribeModal master={followOpen} onClose={() => { setFollowOpen(null); reload(); }} />}
      {publishOpen && myMaster && <PublishSignalModal onClose={() => { setPublishOpen(false); reload(); }} />}
    </>
  );
}

export function CopyTradeFillLedger({ fills, error }: { fills: FillEconomics[]; error: string | null }) {
  return (
    <section className="cc-section" aria-label="我的正式成交" style={{ marginBottom: 20 }}>
      <div className="cc-section-header">
        <h2 className="cc-section-title">// 我的正式成交</h2>
      </div>
      <p className="cc-dim" style={{ fontSize: 11, marginTop: 0 }}>
        价格、手续费和已实现盈亏来自 HMAC 校验的逐笔成交账本。资金费、借贷等持仓成本尚未归因，因此不会显示“总经济性完整”。
      </p>
      {error ? (
        <div className="cc-card cc-chip--danger" role="alert">成交账本不可用：{error}</div>
      ) : fills.length === 0 ? (
        <div className="cc-dim">暂无经正式账本确认的成交。</div>
      ) : (
        <table className="cc-table">
          <thead>
            <tr>
              <th>time</th><th>symbol</th><th>side</th><th align="right">qty</th>
              <th align="right">price</th><th align="right">fee</th><th align="right">realized PnL</th><th>evidence</th>
            </tr>
          </thead>
          <tbody>
            {fills.map((fill) => (
              <tr key={fill.event_ref}>
                <td className="cc-dim" style={{ fontSize: 11 }}>{fill.occurred_at_utc.slice(0, 19)}</td>
                <td className="cc-mono">{fill.symbol}</td>
                <td><span className={`cc-chip ${fill.side === "buy" ? "cc-chip--success" : "cc-chip--danger"}`}>{fill.side}</span></td>
                <td align="right" className="cc-mono">{fill.filled_qty}</td>
                <td align="right" className="cc-mono">{fill.fill_price.toLocaleString()}</td>
                <td align="right" className="cc-mono">
                  {fill.cost_complete && fill.normalized_cost_usdt != null
                    ? `${fill.normalized_cost_usdt.toFixed(4)} USDT`
                    : `${fill.commission} ${fill.commission_asset} (未换算)`}
                </td>
                <td align="right" className="cc-mono">
                  {fill.realized_pnl_complete ? fill.realized_pnl_delta.toFixed(4) : "未证明"}
                </td>
                <td>
                  <span className={`cc-chip ${fill.fill_economics_complete ? "cc-chip--success" : "cc-chip--warning"}`}>
                    {fill.fill_economics_complete ? "逐笔完整" : "逐笔不完整"}
                  </span>
                  {!fill.total_economics_complete && <span className="cc-dim" style={{ marginLeft: 6, fontSize: 11 }}>持仓成本未归因</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function MasterSummaryCard({ master, onClickPublish }: { master: Master | null; onClickPublish: () => void }) {
  if (!master) {
    return (
      <div className="cc-card">
        <div className="cc-section-title" style={{ marginBottom: 8 }}>// 我作为 master</div>
        <div className="cc-dim" style={{ fontSize: 13 }}>你还不是 master。注册后可发布 signal、收 follower。</div>
      </div>
    );
  }
  return (
    <div className="cc-card">
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
        <div className="cc-card-title">{master.display_name}</div>
        <span className="cc-chip cc-chip--accent">{master.asset_class}</span>
      </div>
      <div className="cc-dim" style={{ fontSize: 11 }}>master_id: {master.master_id}</div>
      <div className="cc-row" style={{ gap: 16, marginTop: 8 }}>
        <span className="cc-mono"><b>{master.follower_count}</b> <span className="cc-dim">followers</span></span>
        <span className="cc-mono"><b>{master.total_signals}</b> <span className="cc-dim">signals</span></span>
        <span className="cc-mono"><b>{(master.profit_share_pct * 100).toFixed(0)}%</b> <span className="cc-dim">profit share</span></span>
        {master.is_invite_only && <span className="cc-chip cc-chip--warning">私域</span>}
      </div>
      <button type="button" className="cc-btn cc-btn--accent" style={{ marginTop: 12 }} onClick={onClickPublish}>
        ⚡ 发布新 signal
      </button>
      {master.is_invite_only && master.invite_code && (
        <div className="cc-dim" style={{ marginTop: 12, fontSize: 11 }}>
          私域 invite code: <code style={{ background: "var(--cc-bg-soft)", padding: "2px 6px", borderRadius: 4 }}>{master.invite_code}</code>
        </div>
      )}
    </div>
  );
}

function SubsSummaryCard({ subs }: { subs: Subscription[] }) {
  return (
    <div className="cc-card">
      <div className="cc-section-title" style={{ marginBottom: 8 }}>// 我跟的 master ({subs.length})</div>
      {subs.length === 0 ? (
        <div className="cc-dim" style={{ fontSize: 13 }}>你还没跟任何 master。在下面选择一个并确认跟随。</div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {subs.map((s) => (
            <li key={s.follower_id} style={{ marginBottom: 6 }}>
              <span className="cc-mono" style={{ fontSize: 13 }}>{s.master_display_name || s.master_id}</span>
              <span className="cc-dim" style={{ fontSize: 11, marginLeft: 8 }}>
                {s.master_asset_class} · ${s.invest_amount} · {s.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MasterCard({ master, canSubscribe, onSubscribe }: { master: Master; canSubscribe: boolean; onSubscribe: () => void }) {
  return (
    <div className="cc-card cc-card--hover">
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
        <div className="cc-card-title">{master.display_name}</div>
        <span className={`cc-chip cc-chip--${master.asset_class === "crypto_perp" ? "warning" : "info"}`}>{master.asset_class}</span>
      </div>
      <div className="cc-mono cc-dim" style={{ fontSize: 11, marginBottom: 6 }}>
        <Link to={`/u/${master.author_username}`} style={{ color: "var(--cc-accent)" }}>@{master.author_username}</Link>
      </div>
      {master.description && <div className="cc-soft" style={{ fontSize: 12, marginBottom: 8 }}>{master.description}</div>}
      <div className="cc-metrics" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        <div className="cc-metric">
          <div className="cc-metric-label">Followers</div>
          <div className="cc-metric-value">{master.follower_count}</div>
        </div>
        <div className="cc-metric">
          <div className="cc-metric-label">Signals</div>
          <div className="cc-metric-value">{master.total_signals}</div>
        </div>
        <div className="cc-metric">
          <div className="cc-metric-label">Sharpe</div>
          <div className="cc-metric-value">{master.metric_sharpe != null ? master.metric_sharpe.toFixed(2) : "—"}</div>
        </div>
        <div className="cc-metric">
          <div className="cc-metric-label">Profit share</div>
          <div className="cc-metric-value">{(master.profit_share_pct * 100).toFixed(0)}%</div>
        </div>
      </div>
      <div className="cc-row" style={{ marginTop: 10, gap: 6 }}>
        {master.is_invite_only && <span className="cc-chip cc-chip--warning">私域</span>}
        <div className="cc-spacer" />
        <button
          type="button"
          className="cc-btn cc-btn--accent cc-btn--sm"
          onClick={() => canSubscribe ? onSubscribe() : alert("请先登录")}
        >
          {master.is_invite_only ? "🔑 私域跟单" : "跟单 →"}
        </button>
      </div>
    </div>
  );
}

function BecomeMasterModal({ onClose }: { onClose: () => void }) {
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [assetClass, setAssetClass] = useState("crypto_perp");
  const [profitShare, setProfitShare] = useState("10");
  const [inviteOnly, setInviteOnly] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      const res = await authFetch("/api/copy_trade/masters", {
        method: "POST",
        body: JSON.stringify({
          display_name: displayName,
          description,
          asset_class: assetClass,
          profit_share_pct: Number(profitShare) / 100,
          is_invite_only: inviteOnly,
        }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || "failed");
      onClose();
    } catch (e) {
      setErr(String(e));
    }
  };
  return (
    <div className="cc-modal-backdrop">
      <div className="cc-modal">
        <h3>注册成为 master</h3>
        <div className="cc-input-row"><label>显示名</label><input className="cc-input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="例：Alpha BTC 趋势" /></div>
        <div className="cc-input-row"><label>策略描述</label><input className="cc-input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句话说明" /></div>
        <div className="cc-input-row">
          <label>asset class</label>
          <select className="cc-select" value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
            <option value="crypto_perp">crypto_perp</option>
            <option value="crypto_spot">crypto_spot</option>
            <option value="equity_cn">equity_cn (paper)</option>
          </select>
        </div>
        <div className="cc-input-row"><label>profit share %</label><input className="cc-input" type="number" min="0" max="50" value={profitShare} onChange={(e) => setProfitShare(e.target.value)} /></div>
        <div className="cc-input-row">
          <label>私域 invite-only</label>
          <input type="checkbox" checked={inviteOnly} onChange={(e) => setInviteOnly(e.target.checked)} />
        </div>
        {err && <div className="cc-chip cc-chip--danger">{err}</div>}
        <div className="cc-modal-actions">
          <button type="button" className="cc-btn" onClick={onClose}>取消</button>
          <button type="button" className="cc-btn cc-btn--accent" onClick={submit} disabled={!displayName}>创建</button>
        </div>
      </div>
    </div>
  );
}

export function SubscribeModal({ master, onClose }: { master: Master; onClose: () => void }) {
  const [invest, setInvest] = useState("500");
  const [keystoreName, setKeystoreName] = useState("binance_testnet");
  const [network, setNetwork] = useState<"testnet" | "mainnet">("testnet");
  const [perOrderMax, setPerOrderMax] = useState("100");
  const [dailyLossPct, setDailyLossPct] = useState("5");
  const [maxPositions, setMaxPositions] = useState("3");
  const [maxLeverage, setMaxLeverage] = useState("2");
  const [inviteCode, setInviteCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState<"redeem" | "subscribe">(master.is_invite_only ? "redeem" : "subscribe");
  const [challenge, setChallenge] = useState<RiskConsentChallenge | null>(null);
  const [acknowledgedRefs, setAcknowledgedRefs] = useState<Set<string>>(new Set());
  const [secondFactorMode, setSecondFactorMode] = useState<"password" | "totp">("password");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [consent, setConsent] = useState<RiskConsentResult | null>(null);
  const [testnetRunRef, setTestnetRunRef] = useState("");
  const [approvalRef, setApprovalRef] = useState("");
  const [promotion, setPromotion] = useState<RuntimePromotionResult | null>(null);
  const [busy, setBusy] = useState(false);

  const riskLimits = () => ({
    invest_amount: Number(invest),
    binance_keystore_name: keystoreName,
    per_order_max_usdt: Number(perOrderMax),
    daily_loss_limit_pct: Number(dailyLossPct) / 100,
    max_positions: Number(maxPositions),
    max_leverage: Number(maxLeverage),
  });

  const secondFactor = () => (
    secondFactorMode === "totp" ? { totp_code: totpCode } : { password }
  );

  const redeem = async () => {
    setErr(null);
    const res = await authFetch(`/api/copy_trade/masters/${master.master_id}/redeem`, {
      method: "POST",
      body: JSON.stringify({ invite_code: inviteCode }),
    });
    if (!res.ok) {
      const j = await res.json();
      setErr(j.detail || "redeem failed");
      return;
    }
    setStep("subscribe");
  };

  const subscribe = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await authFetch(`/api/copy_trade/masters/${master.master_id}/subscribe`, {
        method: "POST",
        body: JSON.stringify({
          ...riskLimits(),
          binance_network: network,
          ...(network === "mainnet" && consent && promotion ? {
            runtime_promotion_ref: promotion.runtime_promotion_ref,
            user_risk_choice_ref: consent.user_risk_choice_ref,
            user_risk_consent_event_ref: consent.consent_event_ref,
            ...secondFactor(),
          } : {}),
        }),
      });
      const body: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(responseError(body, "subscribe failed"));
        return;
      }
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const issueRiskChallenge = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await authFetch(`/api/copy_trade/masters/${master.master_id}/risk_consent/challenges`, {
        method: "POST",
        body: JSON.stringify({ ...riskLimits(), selected_risk_path: "small_live" }),
      });
      const body: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(responseError(body, "risk consent challenge failed"));
        return;
      }
      setChallenge(body as RiskConsentChallenge);
      setAcknowledgedRefs(new Set());
    } finally {
      setBusy(false);
    }
  };

  const recordRiskConsent = async () => {
    if (!challenge) return;
    setErr(null);
    setBusy(true);
    try {
      const res = await authFetch(`/api/copy_trade/masters/${master.master_id}/risk_consents`, {
        method: "POST",
        body: JSON.stringify({
          challenge_ref: challenge.challenge_ref,
          acknowledged_item_refs: challenge.risk_profile.required_acknowledgement_refs,
          ...secondFactor(),
        }),
      });
      const body: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(responseError(body, "risk consent failed"));
        return;
      }
      setConsent(body as RiskConsentResult);
    } finally {
      setBusy(false);
    }
  };

  const recordRuntimePromotion = async () => {
    if (!consent) return;
    setErr(null);
    setBusy(true);
    try {
      const draft = consent.runtime_promotion;
      const res = await authFetch("/api/research-os/execution/runtime_promotions", {
        method: "POST",
        body: JSON.stringify({
          request_ref: draft.request_ref,
          subject_ref: draft.subject_ref,
          asset_class: draft.asset_class,
          source_runtime: draft.source_runtime,
          target_runtime: draft.target_runtime,
          testnet_run_ref: testnetRunRef.trim(),
          approval_ref: approvalRef.trim(),
          permission_gate_ref: draft.permission_gate_ref,
          order_guard_ref: draft.order_guard_ref,
          idempotency_key: draft.idempotency_key,
          audit_record_ref: draft.audit_record_ref,
          kill_switch_ref: draft.kill_switch_ref,
          secret_ref: draft.secret_ref,
          responsibility_boundary_ref: draft.responsibility_boundary_ref,
          waiver_requests: [],
          mock_profile: "none",
          evidence_refs: Array.from(new Set([
            ...(draft.required_evidence_refs || []),
            testnetRunRef.trim(),
            approvalRef.trim(),
          ])),
        }),
      });
      const body: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(responseError(body, "runtime promotion failed"));
        return;
      }
      setPromotion(body as RuntimePromotionResult);
    } finally {
      setBusy(false);
    }
  };

  const resetMainnetFlow = () => {
    setChallenge(null);
    setAcknowledgedRefs(new Set());
    setConsent(null);
    setPromotion(null);
    setTestnetRunRef("");
    setApprovalRef("");
    setErr(null);
  };

  const allRiskItemsAcknowledged = !!challenge
    && challenge.risk_profile.required_acknowledgement_refs.every((ref) => acknowledgedRefs.has(ref));
  const hasSecondFactor = secondFactorMode === "totp" ? /^\d{6}$/.test(totpCode) : password.length > 0;
  const formalInputsLocked = challenge !== null;

  return (
    <div className="cc-modal-backdrop">
      <div className="cc-modal">
        <h3>跟单 · {master.display_name}</h3>
        {step === "redeem" && (
          <>
            <p className="cc-soft" style={{ fontSize: 13 }}>这是私域 master，需要 invite_code 才能跟单。</p>
            <div className="cc-input-row"><label>invite_code</label><input className="cc-input" value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} placeholder="向 master 索要" /></div>
            {err && <div className="cc-chip cc-chip--danger">{err}</div>}
            <div className="cc-modal-actions">
              <button type="button" className="cc-btn" onClick={onClose}>取消</button>
              <button type="button" className="cc-btn cc-btn--accent" onClick={redeem} disabled={!inviteCode}>验证 →</button>
            </div>
          </>
        )}
        {step === "subscribe" && (
          <>
            <div className="cc-input-row"><label>本金 (USDT)</label><input className="cc-input" type="number" value={invest} onChange={(e) => setInvest(e.target.value)} disabled={formalInputsLocked} /></div>
            <div className="cc-input-row"><label>keystore 名称</label><input className="cc-input" value={keystoreName} onChange={(e) => setKeystoreName(e.target.value)} placeholder="先去 /trading 写入" disabled={formalInputsLocked} /></div>
            <div className="cc-input-row">
              <label>network</label>
              <select
                className="cc-select"
                value={network}
                onChange={(e) => {
                  const selected = e.target.value as "testnet" | "mainnet";
                  setNetwork(selected);
                  if (selected === "mainnet" && keystoreName === "binance_testnet") {
                    setKeystoreName("binance_mainnet");
                  }
                  resetMainnetFlow();
                }}
                aria-label="network"
                disabled={formalInputsLocked}
              >
                <option value="testnet">testnet</option>
                {master.asset_class === "crypto_perp" && <option value="mainnet">mainnet · 真钱</option>}
              </select>
            </div>
            <div className="cc-input-row"><label>单笔上限 USDT</label><input className="cc-input" type="number" value={perOrderMax} onChange={(e) => setPerOrderMax(e.target.value)} disabled={formalInputsLocked} /></div>
            <div className="cc-input-row"><label>日内亏损 %</label><input className="cc-input" type="number" value={dailyLossPct} onChange={(e) => setDailyLossPct(e.target.value)} disabled={formalInputsLocked} /></div>
            <div className="cc-input-row"><label>最大持仓数</label><input className="cc-input" type="number" min="1" value={maxPositions} onChange={(e) => setMaxPositions(e.target.value)} disabled={formalInputsLocked} /></div>
            <div className="cc-input-row"><label>最大杠杆</label><input className="cc-input" type="number" min="1" step="0.1" value={maxLeverage} onChange={(e) => setMaxLeverage(e.target.value)} disabled={formalInputsLocked} /></div>
            <div className="cc-dim" style={{ fontSize: 11 }}>
              ⚠ master 发 signal 时走你 keystore 自己下单 + 风控重检。你的 key 永远不会发给 master。
            </div>
            {network === "mainnet" && !challenge && (
              <div className="cc-card" style={{ marginTop: 10 }}>
                <b>1 / 4 · 建立账户绑定的风险挑战</b>
                <p className="cc-dim" style={{ fontSize: 11 }}>
                  需要已配置的 Binance mainnet futures key、受信任来源 IP、可验证账户 UID 和可用紧急平仓能力。失败时不会创建同意或订阅。
                </p>
                <button type="button" className="cc-btn cc-btn--warning" onClick={issueRiskChallenge} disabled={busy || !keystoreName || Number(invest) <= 0}>
                  获取正式风险披露 →
                </button>
              </div>
            )}
            {network === "mainnet" && challenge && !consent && (
              <div className="cc-card" style={{ marginTop: 10 }} data-testid="copy-trade-risk-consent">
                <b>2 / 4 · 逐项阅读并确认</b>
                <p className="cc-dim" style={{ fontSize: 11 }}>
                  challenge 到期：{challenge.expires_at_utc}。不得用一个总开关代替逐项确认。
                </p>
                {disclosureItems(challenge.risk_profile).map((item) => (
                  <label key={item.ref} style={{ display: "flex", gap: 8, alignItems: "flex-start", margin: "8px 0", fontSize: 12 }}>
                    <input
                      type="checkbox"
                      checked={acknowledgedRefs.has(item.ref)}
                      onChange={(event) => setAcknowledgedRefs((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.add(item.ref); else next.delete(item.ref);
                        return next;
                      })}
                    />
                    <span>{item.text}</span>
                  </label>
                ))}
                <div className="cc-input-row">
                  <label>二次验证</label>
                  <select className="cc-select" value={secondFactorMode} onChange={(e) => setSecondFactorMode(e.target.value as "password" | "totp")}>
                    <option value="password">登录密码</option>
                    <option value="totp">TOTP</option>
                  </select>
                </div>
                {secondFactorMode === "password" ? (
                  <div className="cc-input-row"><label>password</label><input aria-label="password" className="cc-input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
                ) : (
                  <div className="cc-input-row"><label>TOTP</label><input aria-label="TOTP" className="cc-input" inputMode="numeric" maxLength={6} value={totpCode} onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))} /></div>
                )}
                <button type="button" className="cc-btn cc-btn--warning" onClick={recordRiskConsent} disabled={busy || !allRiskItemsAcknowledged || !hasSecondFactor}>
                  持久化风险选择与同意 →
                </button>
              </div>
            )}
            {network === "mainnet" && consent && !promotion && (
              <div className="cc-card" style={{ marginTop: 10 }} data-testid="copy-trade-runtime-promotion">
                <b>3 / 4 · 绑定已有的独立执行证据</b>
                <p className="cc-dim" style={{ fontSize: 11 }}>
                  页面不会伪造证据。testnet ref 必须是同一账户主体的终态 reconciliation；approval ref 必须是另一位获授权审批人的 approved live_order gate，不能 self-approve。
                </p>
                <div className="cc-input-row"><label>testnet_run_ref</label><input aria-label="testnet_run_ref" className="cc-input" value={testnetRunRef} onChange={(e) => setTestnetRunRef(e.target.value)} /></div>
                <div className="cc-input-row"><label>approval_ref</label><input aria-label="approval_ref" className="cc-input" value={approvalRef} onChange={(e) => setApprovalRef(e.target.value)} /></div>
                <button type="button" className="cc-btn cc-btn--warning" onClick={recordRuntimePromotion} disabled={busy || !testnetRunRef.trim() || !approvalRef.trim()}>
                  记录 testnet → live 晋级 →
                </button>
              </div>
            )}
            {network === "mainnet" && consent && promotion && (
              <div className="cc-card" style={{ marginTop: 10 }} data-testid="copy-trade-mainnet-ready">
                <b>4 / 4 · 后端终检并激活</b>
                <p className="cc-dim" style={{ fontSize: 11 }}>
                  consent 激活截止：{consent.activation_deadline_utc}。点击后后端仍会重查账户、凭据、独立审批、testnet 链、日限额、紧急平仓和 reconciler readiness；任一不满足即拒绝。
                </p>
                <code style={{ fontSize: 10 }}>{promotion.runtime_promotion_ref}</code>
              </div>
            )}
            {err && <div className="cc-chip cc-chip--danger">{err}</div>}
            <div className="cc-modal-actions">
              <button type="button" className="cc-btn" onClick={onClose}>取消</button>
              <button
                type="button"
                className="cc-btn cc-btn--accent"
                onClick={subscribe}
                disabled={busy || !keystoreName || Number(invest) <= 0 || (network === "mainnet" && (!consent || !promotion || !hasSecondFactor))}
              >
                {network === "mainnet" ? "确认真钱跟单" : "确认跟单"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function PublishSignalModal({ onClose }: { onClose: () => void }) {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("0.01");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [relayResult, setRelayResult] = useState<{ relay: Array<{ status: string; follower_id: string }> } | null>(null);

  const submit = async () => {
    setErr(null);
    const res = await authFetch("/api/copy_trade/signals", {
      method: "POST",
      body: JSON.stringify({
        symbol, side, quantity: Number(qty), order_type: orderType,
        price: orderType === "limit" ? Number(price) : null, note,
      }),
    });
    const j = await res.json();
    if (!res.ok) {
      setErr(j.detail || "publish failed");
      return;
    }
    setRelayResult(j);
  };

  return (
    <div className="cc-modal-backdrop">
      <div className="cc-modal">
        <h3>⚡ 发布 signal · 实时 relay 到所有 active follower</h3>
        {!relayResult ? (
          <>
            <div className="cc-input-row"><label>symbol</label><input className="cc-input" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></div>
            <div className="cc-input-row">
              <label>side</label>
              <select className="cc-select" value={side} onChange={(e) => setSide(e.target.value as "buy" | "sell")}>
                <option value="buy">buy ↑</option>
                <option value="sell">sell ↓</option>
              </select>
            </div>
            <div className="cc-input-row"><label>quantity</label><input className="cc-input" type="number" step="0.0001" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
            <div className="cc-input-row">
              <label>type</label>
              <select className="cc-select" value={orderType} onChange={(e) => setOrderType(e.target.value as "market" | "limit")}>
                <option value="market">market</option>
                <option value="limit">limit</option>
              </select>
            </div>
            {orderType === "limit" && (
              <div className="cc-input-row"><label>price</label><input className="cc-input" type="number" value={price} onChange={(e) => setPrice(e.target.value)} /></div>
            )}
            <div className="cc-input-row"><label>note</label><input className="cc-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="可选 · 给 follower 的说明" /></div>
            <div className="cc-dim" style={{ fontSize: 11 }}>
              发布后立即给每个 active follower 跑 RiskMonitor.pre_trade，通过后用 follower **自己 keystore** 下单。
            </div>
            {err && <div className="cc-chip cc-chip--danger">{err}</div>}
            <div className="cc-modal-actions">
              <button type="button" className="cc-btn" onClick={onClose}>取消</button>
              <button type="button" className="cc-btn cc-btn--accent" onClick={submit}>发布 + relay →</button>
            </div>
          </>
        ) : (
          <>
            <p className="cc-soft" style={{ fontSize: 13 }}>✓ signal 已发布。relay 结果：</p>
            <table className="cc-table" style={{ fontSize: 12 }}>
              <thead>
                <tr><th>follower</th><th>status</th></tr>
              </thead>
              <tbody>
                {relayResult.relay.length === 0 ? (
                  <tr><td colSpan={2} className="cc-dim">尚无 active follower</td></tr>
                ) : relayResult.relay.map((r, i) => (
                  <tr key={i}>
                    <td className="cc-mono" style={{ fontSize: 11 }}>{r.follower_id}</td>
                    <td>
                      <span className={`cc-chip ${r.status === "filled" || r.status === "placed" ? "cc-chip--success" : r.status === "rejected" ? "cc-chip--warning" : r.status === "failed" ? "cc-chip--danger" : ""}`}>
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="cc-modal-actions">
              <button type="button" className="cc-btn cc-btn--accent" onClick={onClose}>完成</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default CopyTradePage;
