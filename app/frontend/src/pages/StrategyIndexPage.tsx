import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

/**
 * 策略索引 · quantpedia 风
 * - 顶部 search/filter
 * - 按 asset_class 分组的卡片网格
 * - 每卡片显示 sharpe / pbo / dsr / max_dd / 链接
 *
 * 策略 = "可点开的 run"。后续若产品演进出"策略模板"概念，可在此页加入"模板"维度。
 */

interface RunSummary {
  run_id: string;
  strategy_name?: string;
  strategy_id?: string;
  market?: string;
  asset_class?: string;
  instrument_type?: string;
  benchmark?: string;
  status?: string;
  started_at?: string;
  metrics?: Record<string, number | Record<string, number>>;
}

type AssetClass = "equity_cn" | "crypto_perp" | "crypto_spot" | "other";

const ASSET_LABELS: Record<AssetClass, string> = {
  equity_cn: "A股 · Equity CN",
  crypto_perp: "加密永续 · Crypto Perp",
  crypto_spot: "加密现货 · Crypto Spot",
  other: "其它",
};

const ASSET_CHIPS: Record<AssetClass, "info" | "warning" | "accent"> = {
  equity_cn: "info",
  crypto_perp: "warning",
  crypto_spot: "accent",
  other: "accent",
};

export function StrategyIndexPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [search, setSearch] = useSearchParams();
  const [q, setQ] = useState("");

  useEffect(() => {
    fetch("/api/runs").then((r) => r.json()).then(setRuns).catch(() => {});
  }, []);

  const filterAsset = (search.get("asset") || "all") as AssetClass | "all";

  const grouped = useMemo(() => {
    const out: Record<AssetClass, RunSummary[]> = {
      equity_cn: [],
      crypto_perp: [],
      crypto_spot: [],
      other: [],
    };
    runs.forEach((r) => {
      const a = classifyAsset(r);
      out[a].push(r);
    });
    return out;
  }, [runs]);

  const visibleAssets: AssetClass[] =
    filterAsset === "all" ? ["equity_cn", "crypto_perp", "crypto_spot", "other"] : [filterAsset];

  const filteredQ = (xs: RunSummary[]) => {
    if (!q.trim()) return xs;
    const lower = q.toLowerCase();
    return xs.filter(
      (x) =>
        x.run_id.toLowerCase().includes(lower) ||
        (x.strategy_name || "").toLowerCase().includes(lower) ||
        (x.benchmark || "").toLowerCase().includes(lower),
    );
  };

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">
            <span className="cc-prompt">$</span>strategies
          </h1>
          <p className="cc-page-subtitle">
            按 asset_class 浏览所有上线/已跑策略 — 类比 quantpedia 的 strategy encyclopedia。
            点击卡片打开 run 详情查看 Brinson / PBO / DSR 全套指标。
          </p>
        </div>
        <div className="cc-row">
          <input
            className="cc-input"
            placeholder="搜 run_id / strategy_name / benchmark"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 320 }}
          />
        </div>
      </div>

      {/* asset filter tabs */}
      <div className="cc-tabs">
        <button
          type="button"
          className={`cc-tab${filterAsset === "all" ? " active" : ""}`}
          onClick={() => setSearch({})}
        >
          全部 ({runs.length})
        </button>
        {(["equity_cn", "crypto_perp", "crypto_spot", "other"] as AssetClass[]).map((a) => (
          <button
            key={a}
            type="button"
            className={`cc-tab${filterAsset === a ? " active" : ""}`}
            onClick={() => setSearch({ asset: a })}
          >
            {ASSET_LABELS[a]} ({grouped[a].length})
          </button>
        ))}
      </div>

      {visibleAssets.map((asset) => {
        const list = filteredQ(grouped[asset]);
        if (list.length === 0 && filterAsset !== "all") {
          return (
            <div key={asset} className="cc-card cc-dim">
              {ASSET_LABELS[asset]} · 无 run
            </div>
          );
        }
        if (list.length === 0) return null;
        return (
          <section key={asset} className="cc-section">
            <div className="cc-section-header">
              <h2 className="cc-section-title">
                {ASSET_LABELS[asset]} · {list.length}
              </h2>
              <span className={`cc-chip cc-chip--${ASSET_CHIPS[asset]}`}>{asset}</span>
            </div>
            <div className="cc-grid">
              {list.map((r) => (
                <StrategyCard key={r.run_id} run={r} assetClass={asset} />
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

function StrategyCard({ run, assetClass }: { run: RunSummary; assetClass: AssetClass }) {
  const m = run.metrics || {};
  const sharpe = typeof m.sharpe === "number" ? (m.sharpe as number) : null;
  const dsr =
    typeof m.deflated_sharpe === "number"
      ? (m.deflated_sharpe as number)
      : null;
  const pbo =
    m.pbo && typeof m.pbo === "object" && typeof (m.pbo as Record<string, number>).pbo === "number"
      ? (m.pbo as Record<string, number>).pbo
      : null;
  const dd = typeof m.max_drawdown === "number" ? Math.abs(m.max_drawdown as number) : null;

  const sharpeTone = sharpe == null ? "" : sharpe > 1 ? "cc-good" : sharpe > 0 ? "cc-warn" : "cc-bad";
  const pboTone = pbo == null ? "" : pbo < 0.4 ? "cc-good" : pbo < 0.6 ? "cc-warn" : "cc-bad";
  const dsrTone = dsr == null ? "" : dsr > 0.5 ? "cc-good" : "cc-warn";

  return (
    <Link to={`/runs/${run.run_id}`} className="cc-card cc-card--hover" style={{ display: "block" }}>
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div className="cc-card-title">{run.strategy_name || run.run_id}</div>
        <span className={`cc-chip cc-chip--${ASSET_CHIPS[assetClass]}`}>{assetClass}</span>
      </div>
      <div className="cc-mono cc-dim" style={{ fontSize: 11, marginBottom: 8 }}>
        {run.run_id}
      </div>
      <div className="cc-metrics" style={{ gridTemplateColumns: "repeat(2, 1fr)", marginBottom: 8 }}>
        <div className="cc-metric">
          <div className="cc-metric-label">Sharpe</div>
          <div className={`cc-metric-value ${sharpeTone}`}>{fmt(sharpe, 2)}</div>
        </div>
        <div className="cc-metric">
          <div className="cc-metric-label">Max DD</div>
          <div className="cc-metric-value">{dd != null ? `-${(dd * 100).toFixed(1)}%` : "—"}</div>
        </div>
        <div className="cc-metric">
          <div className="cc-metric-label">PBO</div>
          <div className={`cc-metric-value ${pboTone}`}>{fmt(pbo, 3)}</div>
        </div>
        <div className="cc-metric">
          <div className="cc-metric-label">DSR</div>
          <div className={`cc-metric-value ${dsrTone}`}>{fmt(dsr, 3)}</div>
        </div>
      </div>
      <div className="cc-row" style={{ gap: 6 }}>
        {run.benchmark && <span className="cc-chip">bench: {run.benchmark}</span>}
        {run.status && <span className="cc-chip">{run.status}</span>}
      </div>
    </Link>
  );
}

function fmt(v: number | null, digits: number): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(digits);
}

function classifyAsset(r: RunSummary): AssetClass {
  const ac = (r.asset_class || "").toLowerCase();
  if (ac.startsWith("equity")) return "equity_cn";
  if (ac.includes("perp")) return "crypto_perp";
  if (ac.includes("spot")) return "crypto_spot";
  const market = (r.market || "").toLowerCase();
  if (market.startsWith("stocks_cn") || market.startsWith("indices_cn")) return "equity_cn";
  if (market.includes("usdm")) return "crypto_perp";
  if (market.includes("spot") || (r.instrument_type || "").toLowerCase() === "crypto")
    return "crypto_spot";
  return "other";
}

export default StrategyIndexPage;
