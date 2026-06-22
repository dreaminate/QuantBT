/**
 * 模拟台后端接真客户端（/api/paper/*）。
 * 把后端响应映射成视图已用的 typed 形状（SchedRow / BookPosition / Fill / BalanceCell / PromoCheck），
 * 视图代码无需改。fetch 失败/未接处由调用方回退 mock 并保留 MockBadge（诚实不假绿灯）。
 */
import { authFetch } from "../../../lib/auth";
import { signColor, pnlColor, pct } from "./colors";
import type {
  SchedRow,
  BookPosition,
  Fill,
  BalanceCell,
  PromoCheck,
  PaperMarket,
  RunListItem,
  DeskColor,
} from "./types";

// ── 后端原始响应类型（与 app/paper/desk.py 对齐）──
/** 模拟台列表项（list_runs 派生：含 bars_fed / simulated_source 供「真/空壳」判定）。 */
export interface PaperRunListItem {
  id: string;
  name: string;
  origin?: string;
  market?: PaperMarket;
  bench?: string;
  running?: boolean;
  days?: number;
  promoted?: boolean;
  bars_fed?: number;
  simulated_source?: string | null;
}
export interface PaperStatusResp {
  run_id: string;
  name: string;
  origin: string;
  bench: string;
  market: PaperMarket;
  running: boolean;
  bars_fed: number;
  mtm_count: number;
  last_bar_at_utc: string | null;
  last_mtm_at_utc: string | null;
  last_error: string | null;
  config: { interval_seconds: number };
  /** 数据来源标注：非空=回放捆绑样本（模拟，非实盘 key）；null/缺=空壳。 */
  simulated_source?: string | null;
}
export interface PaperPositionResp {
  symbol: string;
  quantity: number;
  entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
}
export interface PaperFillResp {
  ts: string | null;
  symbol: string | null;
  side: string | null;
  filled_qty: number | null;
  fill_price: number | null;
  commission: number | null;
  status: string | null;
}
export interface PaperBalanceResp {
  cash: number;
  positions_value: number;
  total_equity: number;
  locked: number;
}
export interface PaperPromotionResp {
  run_id: string;
  checks: { key: string; label: string; value: string; passed: boolean }[];
  eligible: boolean;
  promoted: boolean;
  gate_id: string | null;
}

async function getJson<T>(url: string): Promise<T> {
  const r = await authFetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const paperApi = {
  runs: () => getJson<{ runs: PaperRunListItem[] }>("/api/paper/runs"),
  status: (id: string) => getJson<PaperStatusResp>(`/api/paper/runs/${id}/status`),
  positions: (id: string) =>
    getJson<{ positions: PaperPositionResp[] }>(`/api/paper/runs/${id}/positions`),
  balance: (id: string) => getJson<PaperBalanceResp>(`/api/paper/runs/${id}/balance`),
  fills: (id: string) => getJson<{ fills: PaperFillResp[] }>(`/api/paper/runs/${id}/fills`),
  equityLog: (id: string) =>
    getJson<{ equity_log: { total_equity: number }[] }>(`/api/paper/runs/${id}/equity_log`),
  promotion: (id: string) => getJson<PaperPromotionResp>(`/api/paper/runs/${id}/promotion`),
  riskGate: (id: string) => getJson<Record<string, unknown>>(`/api/paper/runs/${id}/risk_gate`),
  openPromotionGate: async (id: string): Promise<{ gate_id: string }> => {
    const r = await authFetch(`/api/paper/runs/${id}/promotion/open`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()) as { gate_id: string };
  },
  approvePromotion: async (
    gateId: string,
    body: { approver: string; endorsement_ref: string; reason: string },
  ): Promise<Response> =>
    authFetch(`/api/paper/promotion/${gateId}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** 过裁决候选 → 注册成模拟台可跑 run（喂模拟 bars 产净值；A股恒 paper、不绕审批）。 */
  registerRun: async (body: {
    run_id: string;
    name?: string;
    market?: PaperMarket;
    symbols?: string[];
    bench?: string;
  }): Promise<Response> =>
    authFetch("/api/paper/runs", { method: "POST", body: JSON.stringify(body) }),
};

// ════════════════ 真 run 列表 → 侧栏 RunListItem ════════════════
/** 后端 list_runs → 侧栏行（真候选/真 paper run，不再读 mock.ts RUNS）。 */
export function runsToList(runs: PaperRunListItem[], selRun: string): RunListItem[] {
  return runs.map((r) => {
    const running = r.running ?? false;
    const statColor: DeskColor = running ? "up" : "warn";
    return {
      id: r.id,
      name: r.name,
      marketLabel: r.market === "crypto" ? "加密" : "A股",
      days: r.days ?? 0,
      statText: running ? "运行中" : "已暂停",
      statColor,
      // 累计收益真值待对账接入前留占位（不假造涨绿）：bars_fed>0 才算真跑、否则空壳。
      total: (r.bars_fed ?? 0) > 0 ? "模拟中" : "空壳",
      pnlColor: "muted" as DeskColor,
      pulse: running,
      active: r.id === selRun,
    };
  });
}

/** 列表计数标签（N 个 · M 跑），真 run 派生。 */
export function runCountLabelLive(runs: PaperRunListItem[]): string {
  const running = runs.filter((r) => r.running).length;
  return `${runs.length} 个 · ${running} 跑`;
}

export { pct };

// ════════════════ 后端响应 → 视图 typed 形状映射 ════════════════
export function statusToSchedRows(s: PaperStatusResp): SchedRow[] {
  return [
    { k: "running", v: String(s.running), color: s.running ? "up" : "warn" },
    { k: "bar_interval", v: `${s.config.interval_seconds.toFixed(1)}s`, color: "flat" },
    { k: "bars_fed", v: String(s.bars_fed), color: "flat" },
    { k: "mtm_count", v: String(s.mtm_count), color: "flat" },
    { k: "last_bar_at", v: s.last_bar_at_utc ?? "—", color: "dim" },
    { k: "last_mtm_at", v: s.last_mtm_at_utc ?? "—", color: "dim" },
    { k: "last_error", v: s.last_error ?? "None", color: s.last_error ? "down" : "up" },
  ];
}

export function positionsToBook(
  positions: PaperPositionResp[],
  market: PaperMarket,
): BookPosition[] {
  const digits = market === "crypto" ? 2 : 2;
  const totalMv =
    positions.reduce((acc, p) => acc + Math.abs(p.quantity * p.mark_price), 0) || 1;
  return positions.map((p) => {
    const pnlFrac = p.entry_price ? (p.mark_price - p.entry_price) / p.entry_price : 0;
    return {
      name: p.symbol,
      sym: p.symbol,
      w: ((Math.abs(p.quantity * p.mark_price) / totalMv) * 100).toFixed(1) + "%",
      qty: p.quantity.toFixed(market === "crypto" ? 3 : 0),
      entry: p.entry_price.toFixed(digits),
      mark: p.mark_price.toFixed(digits),
      pnl: (pnlFrac >= 0 ? "+" : "") + (pnlFrac * 100).toFixed(2) + "%",
      pnlColor: pnlColor(pnlFrac),
    };
  });
}

export function fillsToView(fills: PaperFillResp[], market: PaperMarket): Fill[] {
  const cur = market === "crypto" ? "$" : "¥";
  return fills.map((f) => {
    const buy = (f.side ?? "").toLowerCase() === "buy";
    return {
      time: (f.ts ?? "").slice(0, 19).replace("T", " "),
      sym: f.symbol ?? "—",
      side: buy ? "买" : "卖",
      sideColor: buy ? "up" : "down",
      qty: (f.filled_qty ?? 0).toFixed(market === "crypto" ? 3 : 0),
      price: (f.fill_price ?? 0).toFixed(2),
      fee: cur + (f.commission ?? 0).toFixed(2),
    };
  });
}

export function balanceToCells(b: PaperBalanceResp, market: PaperMarket): BalanceCell[] {
  const cur = market === "crypto" ? "$" : "¥";
  const fmt = (v: number) => cur + Math.round(v).toLocaleString("en-US");
  return [
    { label: "总权益", value: fmt(b.total_equity) },
    { label: "可用现金", value: fmt(b.cash) },
    { label: "持仓市值", value: fmt(b.positions_value) },
    { label: "冻结(挂单)", value: fmt(b.locked) },
  ];
}

export function promotionToChecks(p: PaperPromotionResp): PromoCheck[] {
  return p.checks.map((c) => ({
    t: c.label,
    v: c.value,
    icon: c.passed ? "✓" : "✕",
    color: c.passed ? "up" : "down",
  }));
}

export { signColor };
