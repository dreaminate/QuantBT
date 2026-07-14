import { useEffect, useState } from "react";
import {
  DeskShell,
  DeskTopBar,
  DeskSwitcher,
  SegmentedControl,
  SubTabBar,
  CollapsiblePanel,
  StatusDot,
  MockBadge,
} from "../../components/desk";
import { color } from "./paper/colors";
import {
  findRun,
  buildRunList,
  runCountLabel,
  clockLabel,
  subHint,
} from "./paper/mock";
import {
  type PaperView,
  type PaperMarket,
  type SchedRow,
  type BookPosition,
  type Fill,
  type BalanceCell,
  type PromoCheck,
} from "./paper/types";
import {
  assertApprovedPromotionGate,
  paperApi,
  statusToSchedRows,
  positionsToBook,
  fillsToView,
  balanceToCells,
  promotionToChecks,
  runsToList,
  runCountLabelLive,
  type PaperRunListItem,
  type PaperStatusResp,
  type PaperBalanceResp,
} from "./paper/paperApi";
import { RunView } from "./paper/views/RunView";
import { BookView } from "./paper/views/BookView";
import { RiskView } from "./paper/views/RiskView";
import { ReviewView } from "./paper/views/ReviewView";
import { PromoView } from "./paper/views/PromoView";
import { BinanceTradingPage } from "./BinanceTradingPage";

/** 后端 paper 数据源角标：精确区分 testnet、样本回放、确定性合成与未知来源。 */
function PaperSourceBadge({ status }: { status: PaperStatusResp }) {
  const source = status.simulated_source ?? "missing";
  const providerKind = status.provider_kind ?? "missing";
  const degradeDisplay = status.degrade_reason === undefined
    ? "missing"
    : status.degrade_reason === null
      ? "none"
      : status.degrade_reason || "empty";
  const label = source === "binance_testnet_live"
    ? "PAPER · Binance testnet 实时 bar"
    : source === "bundled_sample_replay"
      ? "PAPER · 捆绑样本回放"
      : source === "deterministic_sim_walk"
        ? "DEMO · 确定性合成行情"
        : "PAPER · 来源未声明";
  const tone = source === "binance_testnet_live" && providerKind === "testnet" && status.degrade_reason === null
    && status.market === "crypto"
    ? "var(--desk-success)"
    : "var(--desk-warning)";
  return (
    <span
      data-testid="paper-source-badge"
      style={{
        fontSize: 9.5,
        color: tone,
        border: `1px solid ${tone}`,
        borderRadius: "var(--desk-radius-pill)",
        padding: "1px 8px",
      }}
      title={`simulated_source=${source}; provider_kind=${providerKind}; degrade_reason=${degradeDisplay}`}
    >
      {label} · provider={providerKind} · degrade_reason={degradeDisplay}
    </span>
  );
}

interface LiveData {
  status: PaperStatusResp;
  sched: SchedRow[];
  /** 后端真实喂进的 bar 数（DS-4）。0 = 空壳（接了端点但无真数据），绝不盖 LIVE 绿标。 */
  barsFed: number;
  positions: BookPosition[];
  fills: Fill[];
  balance: BalanceCell[];
  rawBalance: PaperBalanceResp;
  equity: number[];
  promoChecks: PromoCheck[];
  promoEligible: boolean;
  promoGateId: string | null;
}

const TABS: { value: PaperView; label: string }[] = [
  { value: "run", label: "▦ 运行盘" },
  { value: "book", label: "⊞ 持仓与成交" },
  { value: "risk", label: "⛨ 风险门" },
  { value: "review", label: "↺ 复盘归因" },
  { value: "promo", label: "⤴ 晋升通道" },
  { value: "live_access", label: "🔌 实盘接入" },
];

const MARKETS: { value: PaperMarket; label: string }[] = [
  { value: "equity_cn", label: "A股" },
  { value: "crypto", label: "加密" },
];

/**
 * 模拟台（DC→React，paper accent 绿）。MOCK 数据 + 可交互 + MOCK 角标。
 * 5 视图：运行盘 / 持仓与成交 / 风险门 / 复盘归因 / 晋升通道。
 * 路由由 App.tsx 主控统一接（本文件不碰路由）。
 */
export function PaperDeskPage() {
  const [view, setView] = useState<PaperView>("run");
  const [market, setMarket] = useState<PaperMarket>("equity_cn");
  const [selRun, setSelRun] = useState("weekly_cn_multifactor");
  const [listOpen, setListOpen] = useState(true);
  const [promoted, setPromoted] = useState(false);
  const [live, setLive] = useState<LiveData | null>(null);
  const [liveRuns, setLiveRuns] = useState<PaperRunListItem[] | null>(null);
  // 审批在途 + 失败诚实态（§3：失败不伪绿，显式报错）。
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);

  const run = findRun(selRun);
  // 侧栏：后端可达（liveRuns 非 null，含空数组）一律用真数据——空后端就显示「0 个」，绝不退回 mock 假造 run。
  // 仅 fetch 失败/无后端（liveRuns === null，如单测）才回退 mock RUNS（诚实标 MockBadge）。
  const runList = liveRuns !== null ? runsToList(liveRuns, selRun) : buildRunList(selRun);

  // 侧栏列表真实后端：拉 /api/paper/runs（真候选/真 run）。失败/无后端 → 保留 mock 回退。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { runs } = await paperApi.runs();
        if (alive) setLiveRuns(runs);
      } catch {
        if (alive) setLiveRuns(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 真实后端：拉 status/positions/fills/balance/equity/promotion，映射成视图形状。
  // 失败/无后端（如单测）→ live=null → 视图回退 mock + 保留 MockBadge（诚实不假绿灯）。
  useEffect(() => {
    let alive = true;
    setLive(null);
    setPromoted(false);
    // 切 run/市场即清审批失败态，避免上一个 run 的红错串到下一个（诚实状态不串台）。
    setApproveError(null);
    setApproving(false);
    (async () => {
      try {
        const [status, pos, fl, bal, equity, promo] = await Promise.all([
          paperApi.status(selRun),
          paperApi.positions(selRun),
          paperApi.fills(selRun),
          paperApi.balance(selRun),
          paperApi.equityLog(selRun),
          paperApi.promotion(selRun),
        ]);
        if (!alive) return;
        setLive({
          status,
          sched: statusToSchedRows(status),
          barsFed: status.bars_fed ?? 0,
          positions: positionsToBook(pos.positions, status.market),
          fills: fillsToView(fl.fills, status.market),
          balance: balanceToCells(bal, status.market),
          rawBalance: bal,
          equity: equity.equity_log
            .map((row) => row.total_equity)
            .filter((value) => Number.isFinite(value)),
          promoChecks: promotionToChecks(promo),
          promoEligible: promo.eligible,
          promoGateId: promo.gate_id,
        });
        const currentSourceEligible = status.market === "crypto"
          && status.simulated_source === "binance_testnet_live"
          && status.provider_kind === "testnet"
          && status.degrade_reason === null;
        setPromoted(promo.promoted && promo.eligible && currentSourceEligible);
      } catch {
        if (alive) setLive(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, [selRun, market]);

  const liveReady = live !== null && live.barsFed > 0;
  const promotionSourceEligible = Boolean(
    liveReady
      && live.status.market === "crypto"
      && live.status.simulated_source === "binance_testnet_live"
      && live.status.provider_kind === "testnet"
      && live.status.degrade_reason === null,
  );

  // 人工审批晋级（INV-5）：开判定门 → POST 审批端点（approver≠creator + 背书 + 理由）。
  // §3 不假绿灯：promoted 只在后端【明确返回 ok】后才翻——绝不乐观伪成功。
  // 任一失败（缺背书 / 未审批 / 自审 / 不可跳级 / 网络 / 无后端）→ 显式报错，不 promoted。
  async function handleApprove(form: { endorsementRef: string; reason: string }) {
    if (!liveReady) {
      setApproveError("当前为 MOCK 数据：未调用后端晋级门，也未改变真实晋级状态。");
      return;
    }
    if (!promotionSourceEligible) {
      setApproveError("当前 paper 数据源不是未降级的 Binance testnet 实时 bar：未调用晋级端点，也未改变晋级状态。");
      return;
    }
    // 前端硬拦空背书/空理由（与后端 INV-5 同向，不发空请求伪成功）。
    // 防御性 trim：即便上游未 trim，纯空白也按空拒（裸翻必拒）。
    const endorsementRef = form.endorsementRef.trim();
    const reason = form.reason.trim();
    if (!endorsementRef || !reason) {
      setApproveError("缺验证背书或理由：裸翻必拒（INV-5，未验证≠已验证）。");
      return;
    }
    setApproving(true);
    setApproveError(null);
    try {
      if (!live?.promoGateId) {
        const opened = await paperApi.openPromotionGate(selRun);
        setLive((current) => current ? { ...current, promoGateId: opened.gate_id } : current);
        setApproveError(
          `晋级门 ${opened.gate_id} 已创建；创建者不能自批。须由创建者向另一个认证用户签发 reviewer grant，` +
          "再由该用户提交绑定 verification_target_ref 的验证背书。当前未晋级。",
        );
        return;
      }
      const gateId = live.promoGateId;
      const approved = await paperApi.approvePromotion(gateId, selRun, {
        endorsement_ref: endorsementRef,
        reason: reason,
      });
      assertApprovedPromotionGate(approved, gateId, selRun);
      const canonical = await paperApi.promotion(selRun);
      if (
        canonical.promoted !== true
        || canonical.eligible !== true
        || canonical.gate_id !== gateId
        || canonical.run_id !== selRun
      ) {
        throw new Error("后端批准响应未被 canonical promotion 状态确认：未晋级。");
      }
      setPromoted(true);
      setApproveError(null);
    } catch (error) {
      // 网络失败 / 无后端：诚实报错，绝不乐观伪「已晋级」。
      setPromoted(false);
      setApproveError(
        error instanceof Error && error.message
          ? error.message
          : "晋级门不可用（网络失败或后端未接）：未晋级，请重试或接后端。",
      );
    } finally {
      setApproving(false);
    }
  }

  const topbar = (
    <DeskTopBar>
      <div style={{ marginLeft: 8 }}>
        <DeskSwitcher current="paper" />
      </div>
      <div style={{ flex: 1 }} />
      <SegmentedControl
        options={MARKETS}
        value={market}
        onChange={setMarket}
        size="sm"
      />
      <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>
        {liveReady
          ? `最后 bar · ${live.status.last_bar_at_utc ?? "后端未返回"}`
          : clockLabel(market)}
      </span>
    </DeskTopBar>
  );

  // 已接入后端的 tab（run/book/promo）在数据就位后挂精确来源角标；review/risk 仍 mock 挂 MockBadge。
  // §3 空壳不假绿：仅当后端真喂进 bar（bars_fed>0）才展示来源角标——
  // 接了端点但 bars_fed===0（空壳净值）绝不盖 LIVE 绿标，回退 MockBadge 显诚实状态。
  // （run/book/promo 全 wired tab 一律 bars_fed>0 才 LIVE，取 DS-5 §3 严格版。）
  const wiredTab = view === "run" || view === "book" || view === "promo";
  const tabIsLive = wiredTab && liveReady;
  const tabHint = tabIsLive
    ? view === "run"
      ? "后端净值 · 调度器状态"
      : view === "promo"
        ? "后端晋级门 · 人工审批"
        : "后端持仓 / 成交 / 余额"
    : subHint(view);

  const subtabs = (
    <SubTabBar
      tabs={TABS}
      value={view}
      onChange={setView}
      right={
        <>
          <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>
            {tabHint}
          </span>
          {/* 实盘接入子页直连 /api/security|risk/*，自带真/mock 语义，不挂模拟台级角标避免误导 */}
          {view === "live_access" ? null : tabIsLive && live ? <PaperSourceBadge status={live.status} /> : <MockBadge />}
        </>
      }
    />
  );

  const left = (
    <CollapsiblePanel
      open={listOpen}
      onToggle={() => setListOpen((o) => !o)}
      side="left"
      width={288}
      label="模拟盘"
    >
      <div
        style={{
          flex: "none",
          padding: "9px 13px",
          borderBottom: "1px solid var(--desk-border-soft)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>模拟盘</span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--desk-text-faint)" }}>
          {liveRuns !== null ? runCountLabelLive(liveRuns) : runCountLabel()}
        </span>
        <span
          role="button"
          tabIndex={0}
          onClick={() => setListOpen(false)}
          onKeyDown={(e) => e.key === "Enter" && setListOpen(false)}
          title="折叠模拟盘列表"
          style={{
            marginLeft: 6,
            fontSize: 13,
            color: "var(--desk-text-faint)",
            cursor: "pointer",
          }}
        >
          ‹
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 8 }}>
        {runList.map((r) => (
          <div
            key={r.id}
            role="button"
            tabIndex={0}
            onClick={() => setSelRun(r.id)}
            onKeyDown={(e) => e.key === "Enter" && setSelRun(r.id)}
            style={{
              padding: "9px 11px",
              borderRadius: 9,
              marginBottom: 6,
              cursor: "pointer",
              border: `1px solid ${r.active ? "var(--desk-success)" : "var(--desk-border-soft)"}`,
              background: r.active ? "var(--desk-node-head)" : "var(--desk-card)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <StatusDot color={color(r.statColor)} pulse={r.pulse} size={7} />
              <span
                style={{
                  fontWeight: 600,
                  color: "var(--desk-text)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {r.name}
              </span>
              <span
                style={{ marginLeft: "auto", flex: "none", fontSize: 9, color: color(r.statColor) }}
              >
                {r.statText}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginTop: 6,
                fontSize: 10.5,
              }}
            >
              <span style={{ color: "var(--desk-text-faint)" }}>{r.marketLabel}</span>
              <span style={{ color: "var(--desk-text-faint)" }}>· 第 {r.days} 周</span>
              <span style={{ marginLeft: "auto", color: color(r.pnlColor), fontWeight: 600 }}>
                {r.total}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div
        style={{
          flex: "none",
          borderTop: "1px solid var(--desk-border-soft)",
          padding: "9px 13px",
          fontSize: 10,
          color: "var(--desk-text-faint)",
          lineHeight: 1.6,
        }}
      >
        A股止于 paper · 唯一硬墙在交易所侧远程信任域
      </div>
    </CollapsiblePanel>
  );

  const center = (
    <>
      {subtabs}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "var(--desk-canvas)" }}>
        {view === "run" && (
          <RunView
            run={run}
            market={market}
            liveStatus={liveReady ? live.status : undefined}
            liveSched={liveReady ? live.sched : undefined}
            liveBalance={liveReady ? live.rawBalance : undefined}
            liveEquity={liveReady ? live.equity : undefined}
            livePositions={liveReady ? live.positions : undefined}
          />
        )}
        {view === "book" && (
          <BookView
            market={market}
            liveBalance={liveReady ? live.balance : undefined}
            livePositions={liveReady ? live.positions : undefined}
            liveFills={liveReady ? live.fills : undefined}
          />
        )}
        {view === "risk" && <RiskView />}
        {view === "review" && <ReviewView run={run} />}
        {view === "promo" && (
          <PromoView
            run={run}
            promoted={liveReady ? promoted : false}
            onApprove={handleApprove}
            liveMode={liveReady}
            liveRunName={liveReady ? live.status.name : undefined}
            liveEligible={liveReady ? promotionSourceEligible && live.promoEligible : undefined}
            liveChecks={liveReady ? live.promoChecks : undefined}
            approving={approving}
            approveError={approveError}
          />
        )}
        {view === "live_access" && (
          <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 16 }}>
            <BinanceTradingPage />
          </div>
        )}
      </div>
    </>
  );

  return <DeskShell desk="paper" topbar={topbar} left={left} center={center} />;
}

export default PaperDeskPage;
