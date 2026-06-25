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
        <div className="cc-grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 20 }}>
          <MasterSummaryCard master={myMaster} onClickPublish={() => setPublishOpen(true)} />
          <SubsSummaryCard subs={mySubs} />
        </div>
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

function SubscribeModal({ master, onClose }: { master: Master; onClose: () => void }) {
  const [invest, setInvest] = useState("500");
  const [keystoreName, setKeystoreName] = useState("binance_testnet");
  const [network, setNetwork] = useState("testnet");
  const [perOrderMax, setPerOrderMax] = useState("100");
  const [dailyLossPct, setDailyLossPct] = useState("5");
  const [inviteCode, setInviteCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState<"redeem" | "subscribe">(master.is_invite_only ? "redeem" : "subscribe");

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
    const res = await authFetch(`/api/copy_trade/masters/${master.master_id}/subscribe`, {
      method: "POST",
      body: JSON.stringify({
        invest_amount: Number(invest),
        binance_keystore_name: keystoreName,
        binance_network: network,
        per_order_max_usdt: Number(perOrderMax),
        daily_loss_limit_pct: Number(dailyLossPct) / 100,
      }),
    });
    const j = await res.json();
    if (!res.ok) {
      setErr(j.detail || "subscribe failed");
      return;
    }
    onClose();
  };

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
            <div className="cc-input-row"><label>本金 (USDT)</label><input className="cc-input" type="number" value={invest} onChange={(e) => setInvest(e.target.value)} /></div>
            <div className="cc-input-row"><label>keystore 名称</label><input className="cc-input" value={keystoreName} onChange={(e) => setKeystoreName(e.target.value)} placeholder="先去 /trading 写入" /></div>
            <div className="cc-input-row">
              <label>network</label>
              <select className="cc-select" value={network} onChange={(e) => setNetwork(e.target.value)}>
                <option value="testnet">testnet</option>
                <option value="mainnet">mainnet (真钱)</option>
              </select>
            </div>
            <div className="cc-input-row"><label>单笔上限 USDT</label><input className="cc-input" type="number" value={perOrderMax} onChange={(e) => setPerOrderMax(e.target.value)} /></div>
            <div className="cc-input-row"><label>日内亏损 %</label><input className="cc-input" type="number" value={dailyLossPct} onChange={(e) => setDailyLossPct(e.target.value)} /></div>
            <div className="cc-dim" style={{ fontSize: 11 }}>
              ⚠ master 发 signal 时走你 keystore 自己下单 + 风控重检。你的 key 永远不会发给 master。
            </div>
            {err && <div className="cc-chip cc-chip--danger">{err}</div>}
            <div className="cc-modal-actions">
              <button type="button" className="cc-btn" onClick={onClose}>取消</button>
              <button type="button" className="cc-btn cc-btn--accent" onClick={subscribe} disabled={!keystoreName || Number(invest) <= 0}>
                确认跟单
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
