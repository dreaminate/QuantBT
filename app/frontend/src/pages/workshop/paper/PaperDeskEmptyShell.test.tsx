import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";

/**
 * DS-4 §3 对抗：空壳（bars_fed=0）run 的 run tab 绝不挂后端数据源角标——
 * 后端在场但未喂数据（未真跑）时不假绿灯。LIVE 角标硬绑真实 bars_fed>0。
 */
const { equityEmpty } = vi.hoisted(() => ({ equityEmpty: vi.fn(async () => ({ equity_log: [] })) }));

vi.mock("./paperApi", async () => {
  const actual = await vi.importActual<typeof import("./paperApi")>("./paperApi");
  return {
    ...actual,
    paperApi: {
      runs: vi.fn(async () => ({
        runs: [{ id: "shell_run", name: "shell_run", market: "crypto", running: false, bars_fed: 0, simulated_source: null }],
      })),
      status: vi.fn(async () => ({
        run_id: "shell_run", name: "shell_run", origin: "o", bench: "BTC", market: "crypto",
        running: false, bars_fed: 0, mtm_count: 0,
        // 独特可识别值：只有 live 数据就位后才会渲染——证明 status 真已 resolve（非首帧未加载）。
        last_bar_at_utc: "SHELL-LOADED-MARKER", last_mtm_at_utc: null,
        last_error: null, config: { interval_seconds: 60 }, simulated_source: null,
      })),
      positions: vi.fn(async () => ({ positions: [] })),
      balance: vi.fn(async () => ({ cash: 1000000, positions_value: 0, total_equity: 1000000, locked: 0 })),
      fills: vi.fn(async () => ({ fills: [] })),
      equityLog: equityEmpty,
      promotion: vi.fn(async () => ({
        run_id: "shell_run", eligible: false, promoted: false, gate_id: null, checks: [],
      })),
      riskGate: vi.fn(),
      openPromotionGate: vi.fn(),
      approvePromotion: vi.fn(),
    },
  };
});

import { PaperDeskPage } from "../PaperDeskPage";

describe("模拟台空壳（bars_fed=0）不假绿灯", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it("run tab：bars_fed=0 时不挂 LIVE 角标（空壳必红，§3）", async () => {
    renderWithDesk(<PaperDeskPage />);
    // 正向证明空壳请求确已完成，不是首帧 live=null 的退化通过。
    await waitFor(() => expect(equityEmpty).toHaveBeenCalled());
    // live 请求已就位但 bars_fed=0：整页保持 MOCK，连 scheduler 也不混入后端值。
    expect(screen.queryByTestId("paper-source-badge")).toBeNull();
    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
    expect(screen.queryByText("SHELL-LOADED-MARKER")).toBeNull();
  });
});
