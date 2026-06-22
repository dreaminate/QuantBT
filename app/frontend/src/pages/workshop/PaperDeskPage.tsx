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
import { getStoredUser } from "../../lib/auth";
import {
  paperApi,
  statusToSchedRows,
  positionsToBook,
  fillsToView,
  balanceToCells,
  promotionToChecks,
  runsToList,
  runCountLabelLive,
  type PaperRunListItem,
} from "./paper/paperApi";
import { RunView } from "./paper/views/RunView";
import { BookView } from "./paper/views/BookView";
import { RiskView } from "./paper/views/RiskView";
import { ReviewView } from "./paper/views/ReviewView";
import { PromoView } from "./paper/views/PromoView";
import { BinanceTradingPage } from "./BinanceTradingPage";

/** 接真后的 LIVE 角标（绿，区别于 MOCK 蓝）。 */
function LiveBadge() {
  return (
    <span
      style={{
        fontSize: 9.5,
        color: "var(--desk-success)",
        border: "1px solid var(--desk-success)",
        borderRadius: "var(--desk-radius-pill)",
        padding: "1px 8px",
      }}
      title="已接 /api/paper/* 后端真数据"
    >
      LIVE 已接真
    </span>
  );
}

interface LiveData {
  sched: SchedRow[];
  running: boolean;
  positions: BookPosition[];
  fills: Fill[];
  balance: BalanceCell[];
  promoChecks: PromoCheck[];
  promoGateId: string | null;
  /** 真喂数据计数：>0 才算「接真跑出净值」（LIVE 角标硬绑此值，空壳不盖绿）。 */
  barsFed: number;
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

  const run = findRun(selRun);
  // 侧栏：后端可达（liveRuns 非 null，含空数组）一律用真数据——空后端就显示「0 个」，绝不退回 mock 假造 run。
  // 仅 fetch 失败/无后端（liveRuns === null，如单测）才回退 mock RUNS（诚实标 MockBadge）。
  const runList = liveRuns !== null ? runsToList(liveRuns, selRun) : buildRunList(selRun);

  // 侧栏列表接真：拉 /api/paper/runs（真候选/真 run）。失败/无后端 → 保留 mock 回退。
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

  // 接真：拉 status/positions/fills/balance/promotion，映射成视图形状。
  // 失败/无后端（如单测）→ live=null → 视图回退 mock + 保留 MockBadge（诚实不假绿灯）。
  useEffect(() => {
    let alive = true;
    setLive(null);
    (async () => {
      try {
        const [status, pos, fl, bal, promo] = await Promise.all([
          paperApi.status(selRun),
          paperApi.positions(selRun),
          paperApi.fills(selRun),
          paperApi.balance(selRun),
          paperApi.promotion(selRun),
        ]);
        if (!alive) return;
        setLive({
          sched: statusToSchedRows(status),
          running: status.running,
          positions: positionsToBook(pos.positions, market),
          fills: fillsToView(fl.fills, market),
          balance: balanceToCells(bal, market),
          promoChecks: promotionToChecks(promo),
          promoGateId: promo.gate_id,
          barsFed: status.bars_fed ?? 0,
        });
        setPromoted(promo.promoted);
      } catch {
        if (alive) setLive(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, [selRun, market]);

  // 人工审批晋级（INV-5）：开判定门 → POST 审批端点（approver≠creator + 背书）。
  // 乐观翻 promoted（人工显式动作，非自动循环）。
  // 仅当后端【明确返回非 ok】（按 INV-5 拒：缺背书 / 自审 / 不可跳级）才回滚——
  // 纯网络失败/无后端（dev/单测）保留乐观态，不把后端缺位当成晋级失败。
  async function handleApprove() {
    setPromoted(true);
    const me = getStoredUser();
    let gate: { gate_id: string };
    try {
      gate = live?.promoGateId
        ? { gate_id: live.promoGateId }
        : await paperApi.openPromotionGate(selRun);
    } catch {
      return; // 无后端：保留乐观态（demo 路径）
    }
    try {
      const res = await paperApi.approvePromotion(gate.gate_id, {
        approver: me?.username || "",
        endorsement_ref: "",
        reason: "",
      });
      if (!res.ok) setPromoted(false); // 后端按 INV-5 拒 → 回滚，须补验证背书走完整流程
    } catch {
      /* 网络失败：保留乐观态 */
    }
  }

  const topbar = (
    <DeskTopBar>
      <div style={{ marginLeft: 8 }}>
        <DeskSwitcher current="paper" soon={["factor", "model"]} />
      </div>
      <div style={{ flex: 1 }} />
      <SegmentedControl
        options={MARKETS}
        value={market}
        onChange={setMarket}
        size="sm"
      />
      <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>
        {clockLabel(market)}
      </span>
    </DeskTopBar>
  );

  // 已接真的 tab（run/book/promo）在 live 数据就位后挂 LIVE 角标；review/risk 仍 mock 挂 MockBadge。
  // run tab 的 LIVE 角标【硬绑 bars_fed>0】：真喂到模拟 bars 才算接真，空壳（bars_fed=0）不盖绿（§3）。
  const wiredTab = view === "run" || view === "book" || view === "promo";
  const liveReady = live !== null && (view !== "run" || live.barsFed > 0);
  const tabIsLive = wiredTab && liveReady;

  const subtabs = (
    <SubTabBar
      tabs={TABS}
      value={view}
      onChange={setView}
      right={
        <>
          <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>
            {subHint(view)}
          </span>
          {/* 实盘接入子页直连 /api/security|risk/*，自带真/mock 语义，不挂模拟台级角标避免误导 */}
          {view === "live_access" ? null : tabIsLive ? <LiveBadge /> : <MockBadge />}
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
            liveSched={live?.sched}
            liveRunning={live?.running}
          />
        )}
        {view === "book" && (
          <BookView
            market={market}
            liveBalance={live?.balance}
            livePositions={live?.positions}
            liveFills={live?.fills}
          />
        )}
        {view === "risk" && <RiskView />}
        {view === "review" && <ReviewView run={run} />}
        {view === "promo" && (
          <PromoView
            run={run}
            promoted={promoted}
            onApprove={handleApprove}
            liveChecks={live?.promoChecks}
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
