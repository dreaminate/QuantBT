import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";

/**
 * 模拟台真实后端路径测试（mock /api/paper/* 响应）：
 * - run/book/promo tab 在 live 数据就位后挂 LIVE 角标（区别于 mock 蓝）。
 * - 运行盘头部 / 指标 / 净值 / 调度器 / 持仓与晋升判定只用后端值，不和 mock 重组。
 * - 人工审批走 POST /api/paper/promotion/{gate}/approve（INV-5：approver≠creator + 背书）。
 */

const { approveSpy, promotionSpy, openGateSpy } = vi.hoisted(() => ({
  approveSpy: vi.fn(async (
    gateId: string,
    runId: string,
    body: { endorsement_ref: string; reason: string },
  ) => ({
    gate_id: gateId,
    run_id: runId,
    creator: "alice",
    verification_target_ref: `paper_promotion_target:sha256:${"1".repeat(64)}`,
    eligible: true,
    decision: "approved" as const,
    approver: "bob",
    endorsement_ref: body.endorsement_ref,
    endorsement_evidence_sha256: `paper_promotion_endorsement:sha256:${"2".repeat(64)}`,
    reviewer_grant_id: `paper_reviewer_grant:sha256:${"3".repeat(64)}`,
    reviewer_grant_record_sha256: `paper_reviewer_grant_record:sha256:${"4".repeat(64)}`,
    reviewer_authority_ref: `paper_verifier_authority:sha256:${"5".repeat(64)}`,
  })),
  promotionSpy: vi.fn(async () => ({
    run_id: "weekly_cn_multifactor",
    eligible: true,
    promoted: false,
    gate_id: "promo_weekly_1" as string | null,
    checks: [
      { key: "days", label: "后端门：连续观测", value: "LIVE-CHECK-28", passed: true },
      { key: "excess", label: "模拟段年化 > 基准", value: "+1.80%", passed: true },
      { key: "zero_violation", label: "风险门 0 违规", value: "全绿", passed: true },
      { key: "decay", label: "实盘衰减 < 30%", value: "-16%", passed: true },
      { key: "data_source", label: "晋级数据源 · 加密市场 Binance testnet 实时 bar", value: "binance_testnet_live · provider=testnet", passed: true },
    ],
  })),
  openGateSpy: vi.fn(async () => ({
    gate_id: "promo_weekly_1",
    run_id: "weekly_cn_multifactor",
    creator: "bob",
    verification_target_ref: `paper_promotion_target:sha256:${"1".repeat(64)}`,
    eligible: true,
    decision: "pending" as const,
    approver: null,
    endorsement_ref: null,
    endorsement_evidence_sha256: null,
    reviewer_grant_id: null,
    reviewer_grant_record_sha256: null,
    reviewer_authority_ref: null,
  })),
}));

vi.mock("./paperApi", async () => {
  const actual = await vi.importActual<typeof import("./paperApi")>("./paperApi");
  return {
    ...actual,
    paperApi: {
      runs: vi.fn(async () => ({ runs: [{ id: "weekly_cn_multifactor", name: "weekly_cn_multifactor" }] })),
      status: vi.fn(async () => ({
        run_id: "weekly_cn_multifactor", name: "weekly_cn_multifactor", origin: "backend-origin-live-only",
        bench: "后端基准", market: "crypto", running: true, bars_fed: 4242, mtm_count: 28,
        last_bar_at_utc: "2026-06-21T07:00:02+00:00", last_mtm_at_utc: "2026-06-21T08:30:00+00:00",
        last_error: null, config: { interval_seconds: 60 },
        simulated_source: "binance_testnet_live", provider_kind: "testnet", degrade_reason: null,
      })),
      positions: vi.fn(async () => ({
        positions: [{ symbol: "BACKEND_ONLY_SYMBOL", quantity: 100, entry_price: 1500, mark_price: 1530, unrealized_pnl: 3000 }],
      })),
      balance: vi.fn(async () => ({ cash: 98601, positions_value: 944609, total_equity: 1043210, locked: 0 })),
      fills: vi.fn(async () => ({
        fills: [{ ts: "2026-06-21T06:50:00", symbol: "BACKEND_ONLY_SYMBOL", side: "buy", filled_qty: 100, fill_price: 1500, commission: 3.75, status: "filled" }],
      })),
      equityLog: vi.fn(async () => ({
        equity_log: [{ total_equity: 1000000 }, { total_equity: 1043210 }],
      })),
      promotion: promotionSpy,
      riskGate: vi.fn(),
      openPromotionGate: openGateSpy,
      approvePromotion: approveSpy,
    },
  };
});

import { PaperDeskPage } from "../PaperDeskPage";
import { assertPaperPromotionStatus, paperApi } from "./paperApi";

describe("模拟台真实后端（/api/paper/*）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    promotionSpy.mockImplementation(async () => ({
      run_id: "weekly_cn_multifactor",
      eligible: true,
      promoted: approveSpy.mock.calls.length > 0,
      gate_id: "promo_weekly_1",
      checks: [
        { key: "days", label: "后端门：连续观测", value: "LIVE-CHECK-28", passed: true },
        { key: "excess", label: "模拟段年化 > 基准", value: "+1.80%", passed: true },
        { key: "zero_violation", label: "风险门 0 违规", value: "全绿", passed: true },
        { key: "decay", label: "实盘衰减 < 30%", value: "-16%", passed: true },
        { key: "data_source", label: "晋级数据源 · 加密市场 Binance testnet 实时 bar", value: "binance_testnet_live · provider=testnet", passed: true },
      ],
    }));
    localStorage.setItem("qb-auth-user", JSON.stringify({ user_id: "u1", username: "bob", display_name: "Bob" }));
  });
  afterEach(() => localStorage.clear());

  it("promotion GET 的 malformed/truthy 200 不能被采用为绿态", () => {
    expect(() => assertPaperPromotionStatus({ promoted: true }, "weekly_cn_multifactor"))
      .toThrow("不采用 promoted 绿态");
    expect(() => assertPaperPromotionStatus({
      run_id: "weekly_cn_multifactor",
      promoted: true,
      eligible: true,
      gate_id: "promo_fake",
      checks: ["a", "b", "c", "d", "e"].map((key) => ({
        key, label: key, value: "green", passed: true,
      })),
    }, "weekly_cn_multifactor")).toThrow("不采用 promoted 绿态");
    expect(() => assertPaperPromotionStatus({
      run_id: "weekly_cn_multifactor",
      promoted: true,
      eligible: true,
      gate_id: "",
      checks: ["days", "excess", "zero_violation", "decay", "data_source"].map((key) => ({
        key, label: key, value: "green", passed: true,
      })),
    }, "weekly_cn_multifactor")).toThrow("不采用 promoted 绿态");
  });

  it("run tab：LIVE 只渲染后端头部/指标/净值/调度器/持仓，不重组 mock", async () => {
    renderWithDesk(<PaperDeskPage />);
    expect(await screen.findByTestId("paper-source-badge")).toHaveTextContent(/PAPER · Binance testnet 实时 bar · provider=testnet/);
    expect(screen.getAllByText("4242")).toHaveLength(2);
    expect(screen.getByText("backend-origin-live-only")).toBeInTheDocument();
    expect(screen.getByText("$1,043,210")).toBeInTheDocument();
    expect(screen.getByText("+4.32%")).toBeInTheDocument();
    expect(screen.getByLabelText("后端净值曲线")).toBeInTheDocument();
    expect(screen.getByText("BACKEND_ONLY_SYMBOL")).toBeInTheDocument();

    // 这些值只存在于 mock.ts；LIVE 下任何一个出现都属于重组假绿。
    expect(screen.queryByText("策略台 · strat_wk_cn_01")).toBeNull();
    expect(screen.queryByText("今日盈亏")).toBeNull();
    expect(screen.queryByText("年化 / 夏普")).toBeNull();
    expect(screen.queryByText("贵州茅台")).toBeNull();
    expect(screen.queryByText("← 回测段（样本外延伸）")).toBeNull();
  });

  it("run tab：后端 equity_log 为空时明确不可用，绝不回退 mock 净值", async () => {
    (paperApi.equityLog as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ equity_log: [] });
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    expect(await screen.findByTestId("live-equity-unavailable")).toHaveTextContent(
      "后端 equity_log 暂无可用记录",
    );
    expect(screen.queryByLabelText("净值曲线")).toBeNull();
    expect(screen.queryByText("← 回测段（样本外延伸）")).toBeNull();
    expect(screen.queryByText("今日盈亏")).toBeNull();
  });

  it("book tab：持仓/余额来自后端", async () => {
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⊞ 持仓与成交"));
    // 后端总权益为测试独有值（balanceToCells 千分位格式）。
    expect(await screen.findByText("$1,043,210")).toBeInTheDocument();
  });

  it("promo tab：人工审批走后端 approve 端点（INV-5 · 须填背书+理由才发请求）", async () => {
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    expect(screen.getByText("后端判定：满足晋级条件")).toBeInTheDocument();
    expect(screen.getByText("LIVE-CHECK-28")).toBeInTheDocument();
    expect(screen.getByTestId("live-promo-lifecycle-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("live-promo-factors-unavailable")).toBeInTheDocument();
    expect(screen.queryByText("alpha_vol_adj_mom_20d")).toBeNull();
    const btn = await screen.findByRole("button", { name: /人工审批晋级/ });
    // 空表单 → 按钮禁用、不发请求（裸翻必拒，§3 不假绿灯）。
    expect(btn).toBeDisabled();
    expect(approveSpy).not.toHaveBeenCalled();
    // 填验证背书 + 理由 → 才发请求，且携带真实背书（非空伪请求）。
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "4 门全过，独立验证已背书" },
    });
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    await waitFor(() => expect(approveSpy).toHaveBeenCalledTimes(1));
    const approveArgs = (approveSpy.mock.calls[0] ?? []) as unknown[];
    expect(approveArgs[0]).toBe("promo_weekly_1");
    expect(approveArgs[1]).toBe("weekly_cn_multifactor");
    const sent = approveArgs[2] as
      | { endorsement_ref?: string; reason?: string }
      | undefined;
    expect(sent).not.toHaveProperty("approver");
    expect(sent?.endorsement_ref).toBe("verdict_8f2a");
    expect((sent?.reason ?? "").length).toBeGreaterThan(0);
    // 后端 200 ok → 真翻「已晋级」（非乐观，须后端确认）。
    expect(await screen.findByRole("button", { name: /已晋级/ })).toBeInTheDocument();
  });

  it("promo tab：任意 2xx 空对象不能伪造已晋级", async () => {
    approveSpy.mockResolvedValueOnce({} as never);
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "malformed response must fail closed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    expect(await screen.findByTestId("promote-error")).toHaveTextContent(
      "晋级响应缺字段",
    );
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("promo tab：2xx 空字符串证据不能伪造已晋级", async () => {
    approveSpy.mockResolvedValueOnce({
      gate_id: "promo_weekly_1",
      run_id: "weekly_cn_multifactor",
      creator: "alice",
      verification_target_ref: `paper_promotion_target:sha256:${"1".repeat(64)}`,
      eligible: true,
      decision: "approved",
      approver: "",
      endorsement_ref: "",
      endorsement_evidence_sha256: "",
      reviewer_grant_id: "",
      reviewer_grant_record_sha256: "",
      reviewer_authority_ref: "",
    } as never);
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "empty evidence must fail closed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    expect(await screen.findByTestId("promote-error")).toHaveTextContent(
      "缺少审批、背书或 reviewer grant 证据",
    );
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("promo tab：canonical 状态未确认同一 gate 时不能伪绿", async () => {
    promotionSpy.mockResolvedValueOnce({
      run_id: "weekly_cn_multifactor",
      eligible: true,
      promoted: false,
      gate_id: "promo_weekly_1",
      checks: [
        { key: "days", label: "后端门：连续观测", value: "LIVE-CHECK-28", passed: true },
      ],
    }).mockResolvedValueOnce({
      run_id: "weekly_cn_multifactor",
      eligible: true,
      promoted: false,
      gate_id: "promo_weekly_1",
      checks: [],
    });
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "canonical status must confirm" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    expect(await screen.findByTestId("promote-error")).toHaveTextContent(
      "canonical promotion 状态确认",
    );
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("promo tab：没有现成 gate 时只开 pending 门，不在同一会话自批", async () => {
    promotionSpy.mockResolvedValueOnce({
      run_id: "weekly_cn_multifactor",
      eligible: true,
      promoted: false,
      gate_id: null,
      checks: [
        { key: "days", label: "后端门：连续观测", value: "LIVE-CHECK-28", passed: true },
      ],
    });
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "open gate only" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    await waitFor(() => expect(openGateSpy).toHaveBeenCalledTimes(1));
    expect(approveSpy).not.toHaveBeenCalled();
    expect(await screen.findByTestId("promote-error")).toHaveTextContent(
      "创建者不能自批",
    );
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("promo tab：审批可用性服从后端 eligible=false，不借 mock run 的合格状态", async () => {
    (paperApi.promotion as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      run_id: "weekly_cn_multifactor",
      eligible: false,
      promoted: false,
      gate_id: null,
      checks: [
        { key: "backend-block", label: "后端门：阻断", value: "blocked", passed: false },
      ],
    });
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    expect(screen.getByText("后端判定：不满足晋级条件")).toBeInTheDocument();
    expect(screen.getByText("后端门：阻断")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /人工审批晋级/ })).toBeDisabled();
    expect(screen.queryByTestId("promote-endorsement")).toBeNull();
    expect(screen.queryByText("alpha_vol_adj_mom_20d")).toBeNull();
  });

  it("promo tab：合成/降级来源即使旧 eligible=true 也 fail closed，不发晋级请求", async () => {
    (paperApi.status as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      run_id: "weekly_cn_multifactor", name: "weekly_cn_multifactor", origin: "backend-origin-live-only",
      bench: "后端基准", market: "equity_cn", running: true, bars_fed: 4242, mtm_count: 28,
      last_bar_at_utc: "2026-06-21T07:00:02+00:00", last_mtm_at_utc: "2026-06-21T08:30:00+00:00",
      last_error: null, config: { interval_seconds: 60 },
      simulated_source: "deterministic_sim_walk", provider_kind: "replay_fallback",
      degrade_reason: "testnet 连接失败，已降级回放",
    });
    renderWithDesk(<PaperDeskPage />);
    const badge = await screen.findByTestId("paper-source-badge");
    expect(badge).toHaveTextContent("DEMO · 确定性合成行情");
    expect(badge).toHaveTextContent("provider=replay_fallback");
    expect(badge).toHaveTextContent("degrade_reason=testnet 连接失败，已降级回放");
    expect(badge).toHaveAttribute("title", expect.stringContaining("simulated_source=deterministic_sim_walk"));

    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    expect(screen.getByText("后端判定：不满足晋级条件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /人工审批晋级/ })).toBeDisabled();
    expect(paperApi.openPromotionGate as ReturnType<typeof vi.fn>).not.toHaveBeenCalled();
    expect(approveSpy).not.toHaveBeenCalled();
  });

  it("§3 审批失败（后端按 INV-5 拒 422）→ 诚实失败、绝不伪「已晋级」", async () => {
    approveSpy.mockRejectedValueOnce(new Error("缺验证背书：裸翻必拒（INV-5）"));
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "试图晋级" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    // 失败态显式呈现、未晋级（不伪绿）。
    expect(await screen.findByTestId("promote-error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("§3 失败后重试成功：红错清掉、不与「已晋级」绿并存（无矛盾态）", async () => {
    // 第一次 422 拒 → 显红；第二次 200 ok → 翻绿且红错消失。
    approveSpy.mockRejectedValueOnce(new Error("缺验证背书"));
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "重试理由" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    expect(await screen.findByTestId("promote-error")).toBeInTheDocument();
    // 重试（approveSpy 回到默认 200）。
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    expect(await screen.findByRole("button", { name: /已晋级/ })).toBeInTheDocument();
    // 已晋级绿态下绝不并显红错（矛盾态）。
    expect(screen.queryByTestId("promote-error")).toBeNull();
  });

  it("接入真实后端后不再渲染 MOCK 角标于真实数据 tab（run）", async () => {
    renderWithDesk(<PaperDeskPage />);
    await screen.findByTestId("paper-source-badge");
    // run tab 头部右侧只有 LIVE，不再有 MOCK
    expect(screen.queryByText("MOCK 数据")).toBeNull();
  });

  it("§3 空壳净值（bars_fed=0）：接了端点但无数据 → 绝不展示后端来源角标，回退 MOCK", async () => {
    // 后端返回 0 喂入 bar（空壳）：接通端点但实质无数据。
    (paperApi.status as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      run_id: "weekly_cn_multifactor", name: "weekly_cn_multifactor", origin: "EMPTY-SHELL-BACKEND-ORIGIN",
      bench: "中证500", market: "equity_cn", running: false, bars_fed: 0, mtm_count: 0,
      last_bar_at_utc: "EMPTY-SHELL-SCHEDULER-ONLY", last_mtm_at_utc: null, last_error: null,
      config: { interval_seconds: 60 },
      simulated_source: "binance_testnet_live", provider_kind: "testnet", degrade_reason: null,
    });
    renderWithDesk(<PaperDeskPage />);
    // 等请求真正发出，不把首帧 live=null 当成通过。
    await waitFor(() =>
      expect(paperApi.status as ReturnType<typeof vi.fn>).toHaveBeenCalled(),
    );
    // bars_fed=0 → LIVE 绿标绝不出现；诚实回退 MOCK 角标。
    await waitFor(() => expect(screen.getByText("MOCK 数据")).toBeInTheDocument());
    expect(screen.queryByTestId("paper-source-badge")).toBeNull();
    expect(screen.queryByText("EMPTY-SHELL-BACKEND-ORIGIN")).toBeNull();
    expect(screen.queryByText("EMPTY-SHELL-SCHEDULER-ONLY")).toBeNull();
    expect(screen.queryByText("¥1,043,210")).toBeNull();
    expect(screen.queryByText("BACKEND_ONLY_SYMBOL")).toBeNull();

    fireEvent.click(screen.getByText("⊞ 持仓与成交"));
    expect(screen.queryByText("¥1,043,210")).toBeNull();
    expect(screen.queryByText("BACKEND_ONLY_SYMBOL")).toBeNull();
    expect(screen.getByText("¥1,041,200")).toBeInTheDocument();

    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    expect(screen.queryByText("LIVE-CHECK-28")).toBeNull();
    expect(screen.queryByTestId("live-promo-lifecycle-unavailable")).toBeNull();
    expect(screen.getByText("alpha_vol_adj_mom_20d")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "mock-verdict" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "mock shell must not promote" },
    });
    fireEvent.click(screen.getByRole("button", { name: /人工审批晋级/ }));
    expect(await screen.findByTestId("promote-error")).toHaveTextContent("当前为 MOCK 数据");
    expect(paperApi.openPromotionGate as ReturnType<typeof vi.fn>).not.toHaveBeenCalled();
    expect(approveSpy).not.toHaveBeenCalled();
  });

  it("§3 部分请求成功但 balance 失败：整组保持 MOCK，不混入已成功的后端值", async () => {
    (paperApi.balance as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("balance unavailable"),
    );
    renderWithDesk(<PaperDeskPage />);

    await waitFor(() =>
      expect(paperApi.balance as ReturnType<typeof vi.fn>).toHaveBeenCalled(),
    );
    await waitFor(() =>
      expect(paperApi.promotion as ReturnType<typeof vi.fn>).toHaveBeenCalled(),
    );

    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
    expect(screen.queryByTestId("paper-source-badge")).toBeNull();
    expect(screen.queryByText("backend-origin-live-only")).toBeNull();
    expect(screen.queryByText("4242")).toBeNull();
    expect(screen.queryByText("BACKEND_ONLY_SYMBOL")).toBeNull();

    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    expect(screen.queryByText("LIVE-CHECK-28")).toBeNull();
    expect(screen.queryByTestId("live-promo-lifecycle-unavailable")).toBeNull();
    expect(screen.getByText("alpha_vol_adj_mom_20d")).toBeInTheDocument();
  });
});
