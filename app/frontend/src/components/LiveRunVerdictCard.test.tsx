import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import {
  renderWithDesk,
  assertNoForbiddenWords,
  scanForbiddenWords,
} from "../test/harness";
import * as auth from "../lib/auth";
import { LiveRunVerdictCard } from "./LiveRunVerdictCard";
import { MOCK_RUN_VERDICT } from "./RunVerdictCard";

/**
 * R2 LiveRunVerdictCard · 切真对抗测试。
 * 校验：authFetch 拉真三端点；越界 verdict fail-closed；note 无禁词；
 *       live 不挂 mock 角标；promote 经审批门、422 缺口诚实展示（不假绿灯）。
 */

function jsonRes(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

let spy: ReturnType<typeof vi.spyOn>;

/** 按 URL 后缀路由 mock 响应。 */
function routeFetch(map: Record<string, Response>) {
  spy.mockImplementation((url: RequestInfo) => {
    const u = String(url);
    for (const suffix of Object.keys(map)) {
      if (u.includes(suffix)) return Promise.resolve(map[suffix]);
    }
    return Promise.resolve(jsonRes({ detail: "no route" }, false, 404));
  });
}

const VERDICT_OK = {
  run_id: "run_x",
  verdict: "consistent",
  verdictNote:
    "证据一致（容差内且独立性已度量）。适用域：该样本期；未验证项：实盘冲击成本。",
  has_authoritative_verdict: true,
};
const OVERFIT_OK = { pbo: 0.18, dsr_conservative: 1.34, color: "yellow", gate_label: "证据分歧" };
const COST_OK = {
  derived: true,
  cost: [
    { preset: "optimistic", sharpe: 2.0, excess: 0.19 },
    { preset: "neutral", sharpe: 1.8, excess: 0.17 },
    { preset: "pessimistic", sharpe: 1.5, excess: 0.14 },
  ],
};
const RUN_OK = {
  metrics: { sharpe: 1.8, excess_return: 0.17, max_drawdown: -0.15, information_ratio: 1.2, win_rate: 0.6, turnover: 0.4 },
};

function routeHappy(over: Partial<Record<string, Response>> = {}) {
  routeFetch({
    "/verdict": jsonRes(VERDICT_OK),
    "/overfit": jsonRes(OVERFIT_OK),
    "/cost-sensitivity": jsonRes(COST_OK),
    "/api/runs/run_x": jsonRes(RUN_OK),
    ...over,
  });
}

beforeEach(() => {
  spy = vi.spyOn(auth, "authFetch");
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("LiveRunVerdictCard · 切真拉端点", () => {
  it("拉 verdict/overfit/cost-sensitivity + run metrics 并渲染裁决卡", async () => {
    routeHappy();
    renderWithDesk(<LiveRunVerdictCard runId="run_x" />);
    await waitFor(() =>
      expect(screen.getByTestId("live-run-verdict-card")).toBeInTheDocument(),
    );
    // 三端点 + run 详情都经 authFetch 拉过。
    const urls = (spy.mock.calls as unknown[][]).map((c) => String(c[0]));
    expect(urls.some((u) => u.endsWith("/run_x/verdict"))).toBe(true);
    expect(urls.some((u) => u.endsWith("/run_x/overfit"))).toBe(true);
    expect(urls.some((u) => u.endsWith("/run_x/cost-sensitivity"))).toBe(true);
    // PBO/DSR 来自 overfit 端点真值。
    expect(screen.getByText("0.18")).toBeInTheDocument();
    expect(screen.getByText("1.34")).toBeInTheDocument();
  });

  it("dataSource=live：header 不再挂 MockBadge（卡顶已接真）", async () => {
    routeHappy();
    renderWithDesk(<LiveRunVerdictCard runId="run_x" />);
    await waitFor(() =>
      expect(screen.getByTestId("live-run-verdict-card")).toBeInTheDocument(),
    );
    // 卡顶（未打开 modal）不应出现 MOCK 角标。
    expect(screen.queryByText("MOCK 数据")).toBeNull();
  });

  it("note 由后端供给且无禁词（R7 措辞门）", async () => {
    routeHappy();
    renderWithDesk(<LiveRunVerdictCard runId="run_x" />);
    await waitFor(() =>
      expect(screen.getByTestId("verdict-note")).toBeInTheDocument(),
    );
    const note = screen.getByTestId("verdict-note").textContent ?? "";
    expect(() => assertNoForbiddenWords(note)).not.toThrow();
  });

  it("种坏门必抓：若后端 note 含『排除过拟合/可信』，扫描命中", () => {
    expect(scanForbiddenWords("PBO 低 排除过拟合，结论可信")).toEqual([
      "可信",
      "排除过拟合",
    ]);
  });
});

describe("LiveRunVerdictCard · 对抗：越界 verdict fail-closed", () => {
  it("后端给非三态 verdict → fail-closed 成 concern（不假绿灯）", async () => {
    routeHappy({
      "/verdict": jsonRes({
        ...VERDICT_OK,
        verdict: "晋级候选", // 越界：GateVerdict 标签混进 verdict
      }),
    });
    renderWithDesk(<LiveRunVerdictCard runId="run_x" />);
    await waitFor(() =>
      expect(screen.getByTestId("verdict-pill")).toBeInTheDocument(),
    );
    // 三态映射：concern → 「证据存疑」。绝不渲染「晋级候选」当 verdict pill。
    expect(screen.getByTestId("verdict-pill")).toHaveTextContent("证据存疑");
    expect(screen.getByTestId("verdict-pill")).not.toHaveTextContent("晋级候选");
  });
});

describe("LiveRunVerdictCard · 对抗：promote 经审批门，422 缺口诚实展示", () => {
  it("promote 被拒（缺口）→ 展示缺口、按钮不翻『已登记』", async () => {
    routeHappy();
    renderWithDesk(<LiveRunVerdictCard runId="run_x" />);
    await waitFor(() =>
      expect(screen.getByTestId("promote-btn")).toBeInTheDocument(),
    );
    // promote 端点：422 + gaps（绕审批/缺要件）。
    spy.mockImplementation((url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/run_x/promote") && init?.method === "POST") {
        return Promise.resolve(
          jsonRes(
            { detail: { rejected: true, gaps: ["缺独立验证记录", "honest-N 无法核验"] } },
            false,
            422,
          ),
        );
      }
      return Promise.resolve(jsonRes({}, false, 404));
    });
    fireEvent.click(screen.getByTestId("promote-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("live-promote-msg")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("live-promote-msg")).toHaveTextContent(
      "晋级门未放行",
    );
    // 受控：按钮仍是「登记为晋级候选」，绝不前端伪造「已登记」绿灯。
    expect(screen.getByTestId("promote-btn")).toHaveTextContent(
      "登记为晋级候选",
    );
  });

  it("promote 开门成功（pending）→ 展示『已开晋级审批门』，按钮仍 candidate", async () => {
    routeHappy();
    renderWithDesk(<LiveRunVerdictCard runId="run_x" />);
    await waitFor(() =>
      expect(screen.getByTestId("promote-btn")).toBeInTheDocument(),
    );
    spy.mockImplementation((url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/run_x/promote") && init?.method === "POST") {
        return Promise.resolve(
          jsonRes({
            decision: "pending",
            promoteState: "candidate",
            note: "已开晋级审批门（待 approver≠creator 审批）。",
          }),
        );
      }
      return Promise.resolve(jsonRes({}, false, 404));
    });
    fireEvent.click(screen.getByTestId("promote-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("live-promote-msg")).toHaveTextContent(
        "已开晋级审批门",
      ),
    );
    // 开门 ≠ 已晋级：按钮不自变 registered。
    expect(screen.getByTestId("promote-btn")).toHaveTextContent(
      "登记为晋级候选",
    );
  });
});

describe("LiveRunVerdictCard · 拉取失败回退 mock（诚实角标）", () => {
  it("某端点失败 + 提供 fallback → 回退 mock 卡 + MockBadge", async () => {
    routeFetch({
      "/verdict": jsonRes({ detail: "boom" }, false, 500),
    });
    renderWithDesk(
      <LiveRunVerdictCard runId="run_x" fallback={MOCK_RUN_VERDICT} />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("live-run-verdict-fallback"),
      ).toBeInTheDocument(),
    );
    // 回退卡是 mock → 挂 MockBadge（不假绿灯）。
    expect(screen.getAllByText("MOCK 数据").length).toBeGreaterThanOrEqual(1);
  });
});
