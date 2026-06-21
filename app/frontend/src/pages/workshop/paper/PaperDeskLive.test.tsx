import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";

/**
 * 模拟台「接真」路径测试（mock /api/paper/* 响应）：
 * - run/book/promo tab 在 live 数据就位后挂 LIVE 角标（区别于 mock 蓝）。
 * - 调度器 KV / 持仓 / 余额 用后端值而非 mock。
 * - 人工审批走 POST /api/paper/promotion/{gate}/approve（INV-5：approver≠creator + 背书）。
 */

const { approveSpy } = vi.hoisted(() => ({
  approveSpy: vi.fn(async () => new Response(JSON.stringify({ decision: "approved" }), { status: 200 })),
}));

vi.mock("./paperApi", async () => {
  const actual = await vi.importActual<typeof import("./paperApi")>("./paperApi");
  return {
    ...actual,
    paperApi: {
      runs: vi.fn(async () => ({ runs: [{ id: "weekly_cn_multifactor", name: "weekly_cn_multifactor" }] })),
      status: vi.fn(async () => ({
        run_id: "weekly_cn_multifactor", name: "weekly_cn_multifactor", origin: "o",
        bench: "中证500", market: "equity_cn", running: true, bars_fed: 4242, mtm_count: 28,
        last_bar_at_utc: "2026-06-21T07:00:02+00:00", last_mtm_at_utc: "2026-06-21T08:30:00+00:00",
        last_error: null, config: { interval_seconds: 60 },
      })),
      positions: vi.fn(async () => ({
        positions: [{ symbol: "600519", quantity: 100, entry_price: 1500, mark_price: 1530, unrealized_pnl: 3000 }],
      })),
      balance: vi.fn(async () => ({ cash: 98600, positions_value: 942600, total_equity: 1041200, locked: 0 })),
      fills: vi.fn(async () => ({
        fills: [{ ts: "2026-06-21T06:50:00", symbol: "600519", side: "buy", filled_qty: 100, fill_price: 1500, commission: 3.75, status: "filled" }],
      })),
      equityLog: vi.fn(async () => ({ equity_log: [] })),
      promotion: vi.fn(async () => ({
        run_id: "weekly_cn_multifactor", eligible: true, promoted: false, gate_id: null,
        checks: [
          { key: "days", label: "模拟运行满 1 个月（≥28 天）", value: "28 / 28 天", passed: true },
          { key: "excess", label: "模拟段年化 > 基准", value: "+1.80%", passed: true },
          { key: "zero_violation", label: "风险门 0 违规", value: "全绿", passed: true },
          { key: "decay", label: "实盘衰减 < 30%", value: "-16%", passed: true },
        ],
      })),
      riskGate: vi.fn(),
      openPromotionGate: vi.fn(async () => ({ gate_id: "promo_weekly_1" })),
      approvePromotion: approveSpy,
    },
  };
});

import { PaperDeskPage } from "../PaperDeskPage";

describe("模拟台接真（/api/paper/*）", () => {
  beforeEach(() => {
    approveSpy.mockClear();
    localStorage.setItem("qb-auth-user", JSON.stringify({ user_id: "u1", username: "bob", display_name: "Bob" }));
  });
  afterEach(() => localStorage.clear());

  it("run tab：live 数据就位后挂 LIVE 角标 + 调度器用后端 bars_fed", async () => {
    renderWithDesk(<PaperDeskPage />);
    expect(await screen.findByText("LIVE 已接真")).toBeInTheDocument();
    // 后端 bars_fed=4242（mock 不会产生此值）
    expect(screen.getByText("4242")).toBeInTheDocument();
  });

  it("book tab：持仓/余额来自后端", async () => {
    renderWithDesk(<PaperDeskPage />);
    await screen.findByText("LIVE 已接真");
    fireEvent.click(screen.getByText("⊞ 持仓与成交"));
    // 后端总权益 ¥1,041,200（balanceToCells 千分位格式）
    expect(await screen.findByText("¥1,041,200")).toBeInTheDocument();
  });

  it("promo tab：人工审批走后端 approve 端点（INV-5）", async () => {
    renderWithDesk(<PaperDeskPage />);
    await screen.findByText("LIVE 已接真");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    const btn = await screen.findByRole("button", { name: /人工审批晋级/ });
    fireEvent.click(btn);
    await waitFor(() => expect(approveSpy).toHaveBeenCalledTimes(1));
    // approver 取登录用户（bob）；背书/理由由完整流程补（此处空 → 真后端会按 INV-5 拒，前端乐观态保留待补）
    const approveArgs = (approveSpy.mock.calls[0] ?? []) as unknown[];
    expect((approveArgs[1] as { approver?: string } | undefined)?.approver).toBe("bob");
  });

  it("接真后不再渲染 MOCK 角标于已接真 tab（run）", async () => {
    renderWithDesk(<PaperDeskPage />);
    await screen.findByText("LIVE 已接真");
    // run tab 头部右侧只有 LIVE，不再有 MOCK
    expect(screen.queryByText("MOCK 数据")).toBeNull();
  });
});
