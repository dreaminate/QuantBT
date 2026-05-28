import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch, getStoredUser } from "../../lib/auth";

interface SharedStrategy {
  share_id: string;
  run_id: string;
  author_id: string;
  author_username: string;
  author_display_name: string;
  title: string;
  description: string;
  tags: string[];
  asset_class: string;
  public: boolean;
  forks: number;
  likes: number;
  created_at_utc: string;
  metric_sharpe?: number | null;
  metric_total_return?: number | null;
  metric_max_drawdown?: number | null;
  metric_pbo?: number | null;
  metric_dsr?: number | null;
  fork_from_share_id?: string | null;
}

const ASSET_TABS = [
  { id: "", label: "全部" },
  { id: "equity_cn", label: "A股" },
  { id: "crypto_perp", label: "加密永续" },
  { id: "crypto_spot", label: "加密现货" },
];

const SORTS = [
  { id: "recent", label: "最新" },
  { id: "sharpe", label: "Sharpe" },
  { id: "total_return", label: "总收益" },
  { id: "likes", label: "最赞" },
  { id: "forks", label: "最多 fork" },
  { id: "pbo_low", label: "PBO 低 (健康)" },
];

export function SharedStrategiesPage() {
  const me = getStoredUser();
  const [asset, setAsset] = useState("");
  const [sortBy, setSortBy] = useState("recent");
  const [list, setList] = useState<SharedStrategy[]>([]);
  const [publishOpen, setPublishOpen] = useState(false);

  const reload = () => {
    const url = `/api/sharing/feed?sort_by=${sortBy}${asset ? `&asset_class=${asset}` : ""}`;
    fetch(url).then((r) => r.json()).then(setList).catch(() => setList([]));
  };
  useEffect(reload, [asset, sortBy]);

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title"><span className="cc-prompt">$</span>strategy-square</h1>
          <p className="cc-page-subtitle">
            社区策略广场 · 公开 run + fork + 排行 — 参考聚宽社区
          </p>
        </div>
        {me && (
          <button type="button" className="cc-btn cc-btn--accent" onClick={() => setPublishOpen(true)}>
            发布我的策略 →
          </button>
        )}
      </div>

      <div className="cc-row" style={{ gap: 16, marginBottom: 12 }}>
        <div className="cc-tabs" style={{ borderBottom: 0, margin: 0 }}>
          {ASSET_TABS.map((t) => (
            <button key={t.id} type="button" className={`cc-tab${asset === t.id ? " active" : ""}`} onClick={() => setAsset(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="cc-spacer" />
        <span className="cc-dim" style={{ fontSize: 12 }}>排序</span>
        <select className="cc-select" style={{ width: 160 }} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
          {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </div>

      {list.length === 0 ? (
        <div className="cc-card cc-dim">暂无公开策略 — 第一个发布的人就是你。</div>
      ) : (
        <div className="cc-grid">
          {list.map((s) => <StrategyCard key={s.share_id} s={s} canFork={!!me} onAfterFork={reload} />)}
        </div>
      )}

      {publishOpen && <PublishModal onClose={() => { setPublishOpen(false); reload(); }} />}
    </>
  );
}

function StrategyCard({ s, canFork, onAfterFork }: { s: SharedStrategy; canFork: boolean; onAfterFork: () => void }) {
  const fork = async () => {
    if (!canFork) { alert("请先登录"); return; }
    const res = await authFetch(`/api/sharing/${s.share_id}/fork`, { method: "POST", body: JSON.stringify({}) });
    const j = await res.json();
    if (res.ok) {
      alert(`✓ 已 fork 到你的策略：${j.title}`);
      onAfterFork();
    } else {
      alert(`✗ ${j.detail}`);
    }
  };
  const like = async () => {
    if (!canFork) { alert("请先登录"); return; }
    await authFetch(`/api/sharing/${s.share_id}/like`, { method: "POST" });
    onAfterFork();
  };
  return (
    <div className="cc-card cc-card--hover">
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
        <div className="cc-card-title">{s.title}</div>
        {s.asset_class && <span className="cc-chip cc-chip--info">{s.asset_class}</span>}
      </div>
      <div className="cc-mono cc-dim" style={{ fontSize: 11, marginBottom: 6 }}>
        <Link to={`/u/${s.author_username}`} style={{ color: "var(--cc-accent)" }}>@{s.author_username}</Link>
        {" · "}
        <Link to={`/runs/${s.run_id}`} style={{ color: "inherit" }}>run: {s.run_id}</Link>
        {s.fork_from_share_id && <span> · forked</span>}
      </div>
      {s.description && <div className="cc-soft" style={{ fontSize: 12, marginBottom: 8 }}>{s.description}</div>}
      <div className="cc-metrics" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        <Metric label="Sharpe" v={s.metric_sharpe} digits={2} />
        <Metric label="Total" v={s.metric_total_return} digits={3} pct />
        <Metric label="PBO" v={s.metric_pbo} digits={3} tone={s.metric_pbo != null ? (s.metric_pbo < 0.4 ? "good" : s.metric_pbo < 0.6 ? "warn" : "bad") : ""} />
        <Metric label="DSR" v={s.metric_dsr} digits={3} />
      </div>
      <div className="cc-row" style={{ gap: 6, marginTop: 8 }}>
        {s.tags.slice(0, 4).map((t) => <span key={t} className="cc-chip">#{t}</span>)}
      </div>
      <div className="cc-row" style={{ marginTop: 10, gap: 8 }}>
        <button type="button" className="cc-btn cc-btn--sm" onClick={like}>❤ {s.likes}</button>
        <span className="cc-dim" style={{ fontSize: 11 }}>🔀 {s.forks}</span>
        <div className="cc-spacer" />
        <button type="button" className="cc-btn cc-btn--accent cc-btn--sm" onClick={fork}>fork ↗</button>
      </div>
    </div>
  );
}

function Metric({ label, v, digits, pct, tone }: { label: string; v?: number | null; digits: number; pct?: boolean; tone?: string }) {
  return (
    <div className="cc-metric">
      <div className="cc-metric-label">{label}</div>
      <div className={`cc-metric-value ${tone ? `cc-${tone}` : ""}`}>
        {v == null ? "—" : pct ? `${(v * 100).toFixed(digits)}%` : v.toFixed(digits)}
      </div>
    </div>
  );
}

function PublishModal({ onClose }: { onClose: () => void }) {
  const [runId, setRunId] = useState("");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [tags, setTags] = useState("");
  const [asset, setAsset] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      const res = await authFetch("/api/sharing/publish", {
        method: "POST",
        body: JSON.stringify({
          run_id: runId,
          title: title || runId,
          description: desc,
          tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
          asset_class: asset,
        }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || "publish failed");
      onClose();
    } catch (e) {
      setErr(String(e));
    }
  };
  return (
    <div className="cc-modal-backdrop">
      <div className="cc-modal">
        <h3>发布我的策略</h3>
        <div className="cc-input-row"><label>run_id</label><input className="cc-input" value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="例：a_share_real_demo" /></div>
        <div className="cc-input-row"><label>title</label><input className="cc-input" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        <div className="cc-input-row"><label>description</label><input className="cc-input" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="一句话描述" /></div>
        <div className="cc-input-row"><label>tags（逗号分隔）</label><input className="cc-input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="mom, hs300" /></div>
        <div className="cc-input-row">
          <label>asset</label>
          <select className="cc-select" value={asset} onChange={(e) => setAsset(e.target.value)}>
            <option value="">（自动）</option>
            <option value="equity_cn">equity_cn</option>
            <option value="crypto_perp">crypto_perp</option>
            <option value="crypto_spot">crypto_spot</option>
          </select>
        </div>
        {err && <div className="cc-chip cc-chip--danger">{err}</div>}
        <div className="cc-modal-actions">
          <button type="button" className="cc-btn" onClick={onClose}>取消</button>
          <button type="button" className="cc-btn cc-btn--accent" onClick={submit} disabled={!runId}>发布</button>
        </div>
      </div>
    </div>
  );
}

export default SharedStrategiesPage;
