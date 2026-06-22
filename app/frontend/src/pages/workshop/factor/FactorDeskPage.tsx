import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  DeskShell,
  DeskSwitcher,
  DeskTopBar,
  MockBadge,
  SegmentedControl,
  SubTabBar,
} from "../../../components/desk";
import { authFetch } from "../../../lib/auth";
import {
  type ApiFactorItem,
  type LifecycleState,
  type Market,
  type MockFactor,
  MARKET_POOL,
  buildMockFactors,
} from "./factorData";
import { FactorLibraryView } from "./FactorLibraryView";
import { FactorCorrView, type CorrPair, type FactorCorrLive } from "./FactorCorrView";
import { FactorEvalView, type FactorEvalLive } from "./FactorEvalView";
import {
  FactorBuildView,
  type BuildChatMsg,
  type FactorValidateLive,
  isBalanced,
} from "./FactorBuildView";
import {
  FactorResearchView,
  type ResearchChatMsg,
  type FactorAuditLive,
} from "./FactorResearchView";
import { FactorPureLibsView } from "./FactorPureLibsView";
import { FactorMiningView } from "./FactorMiningView";
import {
  type GenSortKey,
  DEFAULT_GEN_CONFIG,
} from "./factorLabData";

type View = "library" | "corr" | "eval" | "build" | "research" | "purelibs" | "mining";

const TABS: { value: View; label: string }[] = [
  { value: "library", label: "▤ 因子库" },
  { value: "corr", label: "⊞ 相关性" },
  { value: "eval", label: "⚖ 评测台" },
  { value: "build", label: "⌨ 构建台" },
  { value: "research", label: "⚗ 研究台" },
  { value: "purelibs", label: "⛬ 三纯库" },
  { value: "mining", label: "⛏ 暴力遍历挖掘" },
];

const SUB_HINT: Record<View, string> = {
  library: "五态机生命周期 · 点因子看详情",
  corr: "拥挤度 · 去冗余",
  eval: "IC / 分层回测 · 硬指标",
  build: "表达式 DSL · 即代码",
  research: "alpha 真伪 · 学术审查",
  purelibs: "算术 / ML / DL 三库纯净 · 信号契约入口（R17）",
  mining: "生成 / 守门严格解耦 · 诚实-N（R16）",
};

const INITIAL_BUILD_CHAT: BuildChatMsg[] = [
  { role: "user", text: "想要一个能抓「放量突破」的因子，价量配合的那种" },
  { role: "think", text: "放量突破 = 价格创新高 + 成交量放大。可以用 close 相对 N 日高点的位置 × 量比。先给一个干净的截面版本。" },
  { role: "say", text: "建议表达式：rank(close / ts_max(close, 20)) × rank(volume / ts_mean(volume, 20))。我已填到编辑器，截面 rank 让两个量纲对齐，量比用 20 日均量。" },
  { role: "patch", text: "已写入编辑器", code: "rank(close/ts_max(close,20))\n  × rank(volume/ts_mean(volume,20))" },
];

const INITIAL_RESEARCH_CHAT: ResearchChatMsg[] = [
  { role: "user", text: "alpha_vol_adj_mom_20d 这个波动调整动量，IC 0.06 是不是 p-hacking 出来的？" },
  { role: "say", text: "做了多重检验校正后仍显著（见右侧）。它本质是 Sharpe 风格因子，有经济学先验支撑——不是纯数据挖掘。但 60 日动量在 A 股有反转风险，建议看 OBSERVATION 期的实盘衰减。" },
];

/**
 * F1 因子台容器（DC pixel-perfect · P0 mock + 可交互 + MOCK 角标）。
 * data-desk="factor"（紫 accent）。因子库列表接 GET /api/factors（authFetch）覆盖，
 * 其余视图 mock + MockBadge。路由由 App.tsx 主控统一接，本文件不碰 App.tsx。
 */
export function FactorDeskPage() {
  const mockFactors = useMemo(() => buildMockFactors(), []);

  const [view, setView] = useState<View>("library");
  const [market, setMarket] = useState<Market>("equity_cn");
  const [selFactorId, setSelFactorId] = useState<string>(mockFactors[0].id);
  const [listOpen, setListOpen] = useState(true);
  const [lifeFilter, setLifeFilter] = useState<LifecycleState | "ALL">("ALL");
  const [corrPair, setCorrPair] = useState<CorrPair | null>(null);
  const [evalHorizon, setEvalHorizon] = useState(5);

  // 构建台
  const [bdExpr, setBdExpr] = useState("ts_zscore(amount, 20)");
  const bdFactorId = "alpha_amount_z_20";
  const [bdDraft, setBdDraft] = useState("");
  const [bdGateOpen, setBdGateOpen] = useState(false);
  const [bdChat, setBdChat] = useState<BuildChatMsg[]>(INITIAL_BUILD_CHAT);

  // 研究台
  const [rsDraft, setRsDraft] = useState("");
  const [rsChat, setRsChat] = useState<ResearchChatMsg[]>(INITIAL_RESEARCH_CHAT);

  // 三纯库（R17 入库门演示）
  const [libTryId, setLibTryId] = useState<string | null>(null);

  // 暴力遍历挖掘（R16 生成器排序键，只允许结构维度）
  const [mineSortKey, setMineSortKey] = useState<GenSortKey>("complexity");

  // 因子库列表可接真后端：覆盖 mock 列表的「存在性」，详情仍 mock（后端无详情端点）。
  const [apiIds, setApiIds] = useState<Set<string> | null>(null);
  useEffect(() => {
    let cancelled = false;
    authFetch("/api/factors")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((rows: ApiFactorItem[]) => {
        if (cancelled || !Array.isArray(rows)) return;
        setApiIds(new Set(rows.map((r) => r.factor_id)));
      })
      .catch(() => {
        // 离线 / 未登录 → 静默回落 mock（列表仍可用，挂 MockBadge）。
        if (!cancelled) setApiIds(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 列表：若后端有数据，优先展示与后端交集 + 其余 mock（保证 5 视图都有料）。
  const factors: MockFactor[] = useMemo(() => {
    if (!apiIds || apiIds.size === 0) return mockFactors;
    const inApi = mockFactors.filter((f) => apiIds.has(f.id));
    return inApi.length > 0 ? inApi : mockFactors;
  }, [apiIds, mockFactors]);

  const selected =
    factors.find((f) => f.id === selFactorId) ?? factors[0];

  // 评测台接真：选中因子在后端注册表存在时，拉 IC / IC衰减 / 分层回测；
  // 404 / 离线 → 回落 mock + MockBadge（不假绿灯）。
  const [evalLive, setEvalLive] = useState<FactorEvalLive | null>(null);
  useEffect(() => {
    let cancelled = false;
    setEvalLive(null);
    if (!apiIds || !selected || !apiIds.has(selected.id)) return;
    const id = encodeURIComponent(selected.id);
    const qs = `market=${market}&horizon=${evalHorizon}`;
    Promise.allSettled([
      authFetch(`/api/factors/${id}/ic?${qs}`).then((r) => (r.ok ? r.json() : null)),
      authFetch(`/api/factors/${id}/ic_decay?market=${market}`).then((r) => (r.ok ? r.json() : null)),
      authFetch(`/api/factors/${id}/layered_backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ market, horizon: evalHorizon, n_quantiles: 5 }),
      }).then((r) => (r.ok ? r.json() : null)),
    ]).then(([icR, decayR, layR]) => {
      if (cancelled) return;
      const ic = icR.status === "fulfilled" ? icR.value : null;
      const decay = decayR.status === "fulfilled" ? decayR.value : null;
      const lay = layR.status === "fulfilled" ? layR.value : null;
      if (!ic && !decay && !lay) {
        setEvalLive(null);
        return;
      }
      setEvalLive({
        ic: ic
          ? {
              ic_mean: ic.ic_mean,
              rank_ic_mean: ic.rank_ic_mean,
              ic_ir: ic.ic_ir,
              ic_tstat_nw: ic.ic_tstat_nw,
              sample_count: ic.sample_count,
            }
          : null,
        decay: decay?.decay ?? null,
        layered: lay
          ? {
              effective_quantiles: lay.effective_quantiles,
              long_short_spread: lay.long_short_spread,
              monotonic: lay.monotonic,
              buckets: lay.buckets,
            }
          : null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [apiIds, selected, market, evalHorizon]);

  // 构建台接真：编辑器表达式（括号配平时）防抖后打 validate（编译/前视门 + 即时 IC）；
  // 离线/未登录 → mock + MockBadge。仅在 build 视图激活时打。
  const [buildLive, setBuildLive] = useState<FactorValidateLive | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (view !== "build" || !isBalanced(bdExpr) || !bdExpr.trim()) {
      setBuildLive(null);
      return;
    }
    const handle = setTimeout(() => {
      authFetch("/api/factors/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ formula: bdExpr.replace(/\s+/g, " ").trim(), market, horizon: 5 }),
      })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((rep: FactorValidateLive) => {
          if (!cancelled) setBuildLive(rep);
        })
        .catch(() => {
          if (!cancelled) setBuildLive(null);
        });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [view, bdExpr, market]);

  // 相关性接真：后端注册表有 ≥2 因子时拉 Spearman 矩阵；离线/不足 → mock + MockBadge。
  const [corrLive, setCorrLive] = useState<FactorCorrLive | null>(null);
  useEffect(() => {
    let cancelled = false;
    setCorrLive(null);
    if (view !== "corr" || !apiIds || apiIds.size < 2) return;
    authFetch(`/api/factors/correlation?market=${market}&threshold=0.8`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((rep: FactorCorrLive) => {
        if (cancelled) return;
        if (rep && Array.isArray(rep.factor_ids) && rep.factor_ids.length >= 2) setCorrLive(rep);
        else setCorrLive(null);
      })
      .catch(() => {
        if (!cancelled) setCorrLive(null);
      });
    return () => {
      cancelled = true;
    };
  }, [view, apiIds, market]);

  // 研究台接真：选中因子在后端注册表存在时拉 alpha 审查（多证据三角）；
  // 404/离线 → mock + MockBadge。仅在 research 视图激活时拉（audit 较重）。
  const [auditLive, setAuditLive] = useState<FactorAuditLive | null>(null);
  useEffect(() => {
    let cancelled = false;
    setAuditLive(null);
    if (view !== "research" || !apiIds || !selected || !apiIds.has(selected.id)) return;
    const id = encodeURIComponent(selected.id);
    authFetch(`/api/factors/${id}/audit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market, tier: "standard" }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((rep) => {
        if (!cancelled) setAuditLive(rep as FactorAuditLive);
      })
      .catch(() => {
        if (!cancelled) setAuditLive(null);
      });
    return () => {
      cancelled = true;
    };
  }, [view, apiIds, selected, market]);

  function bdAsk(text: string): void {
    const t = text.trim();
    if (!t) return;
    setBdChat((c) => [
      ...c,
      { role: "user", text: t },
      { role: "say", text: "收到。已据此调整表达式并刷新即时 IC 预览。" },
    ]);
    setBdDraft("");
  }

  function bdRegister(): void {
    setBdGateOpen(false);
    // 双保险：注册按钮已按 canRegister disable，但若接真校验未过仍被触发，绝不假报注册成功。
    if (buildLive && !buildLive.valid) {
      setBdChat((c) => [
        ...c,
        { role: "say", text: "✗ 未通过校验门（前视/编译未过），不能注册。请先修正表达式并重新校验。" },
      ]);
      return;
    }
    setBdChat((c) => [
      ...c,
      { role: "say", text: "✓ 已注册到因子库，初始状态 NEW，等待 IC 评估自动迁移。" },
    ]);
  }

  function bdInsert(token: string): void {
    setBdExpr((e) => (e ? e + (/[a-z0-9_]$/.test(e) ? " " : "") : "") + token);
  }

  function rsAsk(text: string): void {
    const t = text.trim();
    if (!t) return;
    setRsChat((c) => [
      ...c,
      { role: "user", text: t },
      { role: "say", text: "见右侧审查表：多重检验门槛已按 Harvey-Liu-Zhu 提到的更高 t 标准设置。" },
    ]);
    setRsDraft("");
  }

  const topbar = (
    <DeskTopBar>
      <DeskSwitcher current="factor" soon={["model", "paper"]} />
      <div style={{ flex: 1 }} />
      <SegmentedControl
        size="sm"
        value={market}
        onChange={(m) => {
          setMarket(m);
          setCorrPair(null);
        }}
        options={[
          { value: "equity_cn", label: "A股" },
          { value: "crypto", label: "加密" },
        ]}
      />
      <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>
        {MARKET_POOL[market]}
      </span>
    </DeskTopBar>
  );

  let center: ReactNode;
  if (view === "library") {
    center = (
      <FactorLibraryView
        factors={factors}
        selected={selected}
        onSelect={setSelFactorId}
        listOpen={listOpen}
        onToggleList={() => setListOpen((o) => !o)}
        lifeFilter={lifeFilter}
        onLifeFilter={setLifeFilter}
      />
    );
  } else if (view === "corr") {
    center = (
      <FactorCorrView
        factors={factors}
        market={market}
        pair={corrPair}
        onPair={setCorrPair}
        live={corrLive}
      />
    );
  } else if (view === "eval") {
    center = (
      <FactorEvalView
        factor={selected}
        horizon={evalHorizon}
        onHorizon={setEvalHorizon}
        live={evalLive}
      />
    );
  } else if (view === "build") {
    center = (
      <FactorBuildView
        expr={bdExpr}
        factorId={bdFactorId}
        chat={bdChat}
        draft={bdDraft}
        onDraft={setBdDraft}
        onSend={() => bdAsk(bdDraft)}
        onInsert={bdInsert}
        onChip={bdAsk}
        gateOpen={bdGateOpen}
        onGate={() => setBdGateOpen(true)}
        onGateClose={() => setBdGateOpen(false)}
        onGateConfirm={bdRegister}
        live={buildLive}
      />
    );
  } else if (view === "research") {
    center = (
      <FactorResearchView
        factor={selected}
        chat={rsChat}
        draft={rsDraft}
        onDraft={setRsDraft}
        onSend={() => rsAsk(rsDraft)}
        live={auditLive}
      />
    );
  } else if (view === "purelibs") {
    center = <FactorPureLibsView tryId={libTryId} onTry={setLibTryId} />;
  } else {
    center = (
      <FactorMiningView
        config={DEFAULT_GEN_CONFIG}
        sortKey={mineSortKey}
        onSortKey={setMineSortKey}
      />
    );
  }

  return (
    <DeskShell
      desk="factor"
      topbar={topbar}
      center={
        <>
          <SubTabBar
            tabs={TABS}
            value={view}
            onChange={setView}
            right={
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>
                  {SUB_HINT[view]}
                </span>
                <MockBadge />
              </span>
            }
          />
          {center}
        </>
      }
    />
  );
}

/** 暴露内部判定供测试复用（不改变运行行为）。 */
export const __test = { isBalanced };

export default FactorDeskPage;
