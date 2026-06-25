import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { OnboardingBanner } from "../features/onboarding/OnboardingBanner";

/**
 * 首页：quantpedia 风 hero + 三大类策略卡片 + 最近 runs + 终端感命令提示
 * 主调：Claude Code 深色 + 橙色 accent + 等宽字
 */

interface RunSummary {
  run_id: string;
  strategy_name?: string;
  instrument_type?: string;
  market?: string;
  status?: string;
  started_at?: string;
  metrics?: Record<string, number>;
}

interface FactorItem {
  factor_id: string;
  lifecycle_state: string;
}

interface NetState {
  binance_network: string;
  mode: string;
}

export function HomePage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [factors, setFactors] = useState<FactorItem[]>([]);
  const [net, setNet] = useState<NetState | null>(null);

  useEffect(() => {
    fetch("/api/runs").then((r) => r.json()).then(setRuns).catch(() => {});
    fetch("/api/factors").then((r) => r.json()).then(setFactors).catch(() => {});
    fetch("/api/security/network").then((r) => r.json()).then(setNet).catch(() => {});
  }, []);

  // group runs by asset class
  const groups: Record<string, RunSummary[]> = {
    equity_cn: [],
    crypto_perp: [],
    crypto_spot: [],
    other: [],
  };
  runs.forEach((r) => {
    const market = (r.market || "").toLowerCase();
    if (market.startsWith("stocks_cn")) groups.equity_cn.push(r);
    else if (market.includes("usdm") || (r.instrument_type || "").toLowerCase().includes("perp"))
      groups.crypto_perp.push(r);
    else if (market.includes("spot") || (r.instrument_type || "").toLowerCase() === "crypto")
      groups.crypto_spot.push(r);
    else groups.other.push(r);
  });

  return (
    <>
      <OnboardingBanner />
      <section className="cc-hero">
        <div className="cc-hero-eyebrow">v0.8.5.1 · 研究、验证、风控工作台</div>
        <h1 className="cc-hero-title">QuantBT · A股 + 加密量化研究工作台</h1>
        <p className="cc-hero-subtitle">
          因子工厂 · ML 模型 · Purged k-fold · HRP 组合 · BacktestVenue · Binance 受限实盘 ·
          研究执行台。所有正式产物以 Parquet / CSV / JSON / MD 落盘，可独立审计。
        </p>
        <div className="cc-hero-stats">
          <div className="cc-stat">
            <div className="cc-stat-value">{runs.length}</div>
            <div className="cc-stat-label">runs</div>
          </div>
          <div className="cc-stat">
            <div className="cc-stat-value">{factors.length}</div>
            <div className="cc-stat-label">factors</div>
          </div>
          <div className="cc-stat">
            <div className="cc-stat-value">{net?.binance_network || "—"}</div>
            <div className="cc-stat-label">network</div>
          </div>
          <div className="cc-stat">
            <div className="cc-stat-value">{net?.mode || "—"}</div>
            <div className="cc-stat-label">mode</div>
          </div>
        </div>
        <div style={{ marginTop: 20, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link to="/strategies" className="cc-btn cc-btn--accent">
            浏览策略索引 →
          </Link>
          <Link to="/agent" className="cc-btn cc-btn--ghost">
            研究执行台
          </Link>
          <Link to="/runs" className="cc-btn cc-btn--ghost">
            回测列表
          </Link>
        </div>
      </section>

      {/* 三大类策略 quantpedia 风 */}
      <section className="cc-section">
        <div className="cc-section-header">
          <h2 className="cc-section-title">// strategy categories</h2>
          <Link className="cc-section-extra" to="/strategies">
            全部策略索引 →
          </Link>
        </div>
        <div className="cc-grid-lg">
          <CategoryCard
            title="A股 · Equity CN"
            chip="equity_cn"
            chipKind="info"
            tagline="paper trading only — 不接券商。Tushare Pro 2000 积分数据源。"
            runs={groups.equity_cn}
            link="/strategies?asset=equity_cn"
          />
          <CategoryCard
            title="加密永续 · Crypto Perp"
            chip="crypto_perp"
            chipKind="warning"
            tagline="Binance USDM Futures · 资金费率 + maker/taker 分档全计入成本"
            runs={groups.crypto_perp}
            link="/strategies?asset=crypto_perp"
          />
          <CategoryCard
            title="加密现货 · Crypto Spot"
            chip="crypto_spot"
            chipKind="info"
            tagline="Binance Spot · 现货市场 · LIMIT/MARKET/STOP_LOSS_LIMIT/OCO 全订单类型"
            runs={groups.crypto_spot}
            link="/strategies?asset=crypto_spot"
          />
        </div>
      </section>

      {/* 终端提示 · 让用户感受 Claude Code 风 */}
      <section className="cc-section">
        <div className="cc-section-header">
          <h2 className="cc-section-title">// quick start</h2>
        </div>
        <div className="cc-card">
          <div className="cc-prompt-line">
            <span className="cc-prompt-sigil">$</span>
            <span>cp deploy/secrets.yaml.example ~/.quantbt/secrets.yaml</span>
          </div>
          <div className="cc-prompt-line">
            <span className="cc-prompt-sigil">$</span>
            <span>python examples/run_a_share_real_demo.py --n-symbols 30 --years 1</span>
          </div>
          <div className="cc-prompt-line">
            <span className="cc-prompt-output">
              ✅ a_share_real_demo done · sharpe=5.84 · pbo=0.00 · dsr=0.999
            </span>
          </div>
          <div className="cc-prompt-line">
            <span className="cc-prompt-sigil">$</span>
            <span>open http://localhost:5173/runs/a_share_real_demo</span>
          </div>
        </div>
      </section>

      {/* 因子分布 mini */}
      <section className="cc-section">
        <div className="cc-section-header">
          <h2 className="cc-section-title">// factor lifecycle distribution</h2>
          <Link className="cc-section-extra" to="/factors">
            因子市场 →
          </Link>
        </div>
        <LifecycleBar factors={factors} />
      </section>
    </>
  );
}

function CategoryCard({
  title,
  chip,
  chipKind,
  tagline,
  runs,
  link,
}: {
  title: string;
  chip: string;
  chipKind: "info" | "warning" | "accent";
  tagline: string;
  runs: RunSummary[];
  link: string;
}) {
  return (
    <Link to={link} className="cc-card cc-card--hover" style={{ display: "block" }}>
      <div className="cc-row" style={{ justifyContent: "space-between" }}>
        <div className="cc-card-title">{title}</div>
        <span className={`cc-chip cc-chip--${chipKind}`}>{chip}</span>
      </div>
      <div className="cc-soft" style={{ fontSize: 12, marginBottom: 12 }}>
        {tagline}
      </div>
      <div className="cc-divider" />
      <div className="cc-metric-label" style={{ marginBottom: 6 }}>
        最近 runs · {runs.length}
      </div>
      {runs.length === 0 ? (
        <div className="cc-dim" style={{ fontSize: 12 }}>
          暂无 run
        </div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {runs.slice(0, 3).map((r) => (
            <li key={r.run_id} style={{ marginBottom: 4 }}>
              <span className="cc-mono cc-soft" style={{ fontSize: 12 }}>
                {r.run_id}
              </span>
              {r.metrics?.sharpe != null && (
                <span className="cc-chip cc-chip--accent" style={{ marginLeft: 8 }}>
                  sharpe {r.metrics.sharpe.toFixed(2)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Link>
  );
}

function LifecycleBar({ factors }: { factors: FactorItem[] }) {
  const counts: Record<string, number> = {};
  factors.forEach((f) => {
    counts[f.lifecycle_state] = (counts[f.lifecycle_state] || 0) + 1;
  });
  const order = ["NEW", "QUALIFIED", "PROBATION", "OBSERVATION", "WARNING", "RETIRED"];
  return (
    <div className="cc-card">
      <div className="cc-row" style={{ gap: 6, flexWrap: "wrap" }}>
        {order.map((state) => (
          <span key={state} className={`cc-lifecycle cc-lifecycle--${state}`}>
            {state} · {counts[state] || 0}
          </span>
        ))}
      </div>
    </div>
  );
}

export default HomePage;
