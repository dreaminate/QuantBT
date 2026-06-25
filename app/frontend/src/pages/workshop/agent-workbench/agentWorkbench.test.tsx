import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent, within, waitFor } from "@testing-library/react";
import * as authModule from "../../../lib/auth";
import {
  renderWithDesk,
  assertNoForbiddenWords,
  assertNoFrozenPageImport,
} from "../../../test/harness";
import * as auth from "../../../lib/auth";
import { AgentWorkbenchPage } from "./AgentWorkbenchPage";
import { GatePanel } from "./GatePanel";
import { CoworkArea } from "./CoworkCards";
import { gateNeedsConfirm, isGovernanceWeakness } from "./permGate";
import {
  PERM_DEMO_GATES,
  type CoworkKind,
  AGENT_SCRIPT,
} from "./agentMock";

const here = dirname(fileURLToPath(import.meta.url));

// jsdom 无 layout；requestAnimationFrame 在 jsdom 有，剧本铺设是同步 setState，渲染即生效。
//
// DS-2：研究执行台默认真实流（liveMode=true），mock 剧本退居「看演示」显式入口。
// 凡断言 mock 剧本（首条 prompt / gate / 批准 / handoff）的用例，先点「看演示」进 demoMode。
function enterDemo(container: HTMLElement): void {
  const toggle = container.querySelector("[data-demo-toggle]") as HTMLElement;
  fireEvent.click(toggle);
}

describe("研究执行台 · 渲染骨架（T-040 / A2）", () => {
  it("DeskShell data-desk=agent（橙 accent 由 data-desk 注入）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    const root = container.querySelector(".desk-root");
    expect(root).not.toBeNull();
    expect(root).toHaveAttribute("data-desk", "agent");
  });

  it("常驻 MockBadge（P0 诚实角标，不假绿灯）", () => {
    renderWithDesk(<AgentWorkbenchPage />);
    expect(screen.getAllByText(/MOCK/).length).toBeGreaterThan(0);
  });

  it("里程碑进度线 7 节点全在（立题→市场→因子集→模型→信号→风控→回测）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    const ladder = container.querySelector("[data-milestone-ladder]");
    expect(ladder).not.toBeNull();
    for (const key of [
      "立题",
      "市场",
      "因子集",
      "模型",
      "信号",
      "仓位风控",
      "回测",
    ]) {
      expect(
        container.querySelector(`[data-ms-node="${key}"]`),
      ).not.toBeNull();
    }
  });

  it("台 switcher：研究执行台 active（正名后非伪策略台）+ 其余 6 台皆可跳（无 soon 占位、无死链）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    const links = Array.from(container.querySelectorAll("a")).map(
      (a) => a.textContent,
    );
    // 正名：active 台是研究执行台，渲染为实心 <span>，不是 <a> 链接。
    expect(links).not.toContain("研究执行台");
    // soon=[] → 其余台全部为可跳 <Link>（含此前被灰的因子台/模拟台）。
    expect(links).toContain("因子台");
    expect(links).toContain("模拟台");
    expect(links).toContain("Model台");
    expect(links).toContain("策略台");
  });

  it("双栏可折叠 + splitter 双开时在；收起工作区后 splitter 消失", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    expect(container.querySelector("[data-splitter]")).not.toBeNull();
    // 收起产物工作区（右栏）→ splitter 不再渲染（仅双开时出现）。
    fireEvent.click(screen.getByLabelText("收起产物工作区"));
    expect(container.querySelector("[data-splitter]")).toBeNull();
    // 折叠态出现竖排展开条。
    expect(screen.getByTitle("展开产物工作区")).toBeInTheDocument();
  });
});

describe("DS-2 · 研究执行台默认真实流（liveMode=true，mock 退居「看演示」）", () => {
  it("默认 liveMode=true：顶栏挂 LIVE 标、不自动放 mock 剧本（无首条 mock prompt）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    // 默认真实流 → LIVE 角标在、顶栏 MockBadge（「MOCK 数据」）不在。
    expect(container.querySelector("[data-live-badge]")).not.toBeNull();
    expect(screen.queryByText("MOCK 数据")).toBeNull();
    // 默认不铺 mock 剧本：首条 mock prompt 不在（不放假绿灯 mock）。
    expect(screen.queryByText(/组装一个 A股周频多因子策略/)).toBeNull();
  });

  it("点「看演示」→ 进 demoMode：挂 MockBadge + 铺 mock 剧本（显式演示入口）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    // 演示态：MockBadge（「MOCK 数据」）在、LIVE 角标不在。
    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
    expect(container.querySelector("[data-live-badge]")).toBeNull();
    // mock 剧本已铺：首条 prompt 出现。
    expect(screen.getByText(/组装一个 A股周频多因子策略/)).toBeInTheDocument();
  });

  it("对抗：种「默认就放 mock 剧本（假绿灯）」必抓 —— 默认态不得有 mock gate 面板", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    // 默认真实流：mock 剧本的 gate 面板不得自动出现（否则=默认放假绿灯 mock，blocker #1 回归）。
    expect(container.querySelector("[data-gate-panel]")).toBeNull();
  });
});

describe("研究执行台 · 对话流 + 产物（T-040 / A1 · 看演示 mock 剧本）", () => {
  it("剧本铺设：user 首条 prompt + tool 块渲染（进「看演示」后）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    expect(screen.getByText(/组装一个 A股周频多因子策略/)).toBeInTheDocument();
    // 第一道 gate 之前的 tool 已铺（hypothesis.create）。
    expect(screen.getByText(/hypothesis\.create/)).toBeInTheDocument();
  });

  it("剧本停在第一道 gate（ask 模式 · backtest.run 需确认）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    const gate = container.querySelector("[data-gate-panel]");
    expect(gate).not.toBeNull();
    expect(gate).toHaveAttribute("data-gate-side-effect", "none");
  });

  it("批准本次 gate → 继续铺到回测拍板 + RunVerdictCard 出现", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    fireEvent.click(screen.getByText("1. 批准本次"));
    // 回测产物卡解锁。
    expect(container.querySelector('[data-cowork-card="run"]')).not.toBeNull();
  });

  it("工作区 tab：产物 / Strategy.yaml；回测后 Report.md 出现", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    expect(screen.getByText("⌨ Strategy.yaml")).toBeInTheDocument();
    // 回测前无 Report.md。
    expect(screen.queryByText("▤ Report.md")).toBeNull();
    fireEvent.click(screen.getByText("1. 批准本次"));
    expect(screen.getByText("▤ Report.md")).toBeInTheDocument();
  });
});

describe("治理红线 ① — D-PERM：bypass/auto 也拦真钱/external（对抗 #1）", () => {
  it("纯逻辑：gateNeedsConfirm — realmoney 在任何模式恒须确认", () => {
    for (const mode of ["ask", "auto", "bypass"] as const) {
      expect(gateNeedsConfirm(mode, "realmoney")).toBe(true);
      expect(gateNeedsConfirm(mode, "external")).toBe(true);
    }
    // none：仅 ask 需确认，auto/bypass 自跑。
    expect(gateNeedsConfirm("ask", "none")).toBe(true);
    expect(gateNeedsConfirm("auto", "none")).toBe(false);
    expect(gateNeedsConfirm("bypass", "none")).toBe(false);
  });

  it("UI：bypass 模式 + realmoney gate 仍渲染确认变体（不自动放行）", () => {
    const { container } = renderWithDesk(
      <GatePanel
        permMode="bypass"
        gateTool={PERM_DEMO_GATES.realmoney.gateTool}
        sideEffect="realmoney"
        gateBlurb={PERM_DEMO_GATES.realmoney.gateBlurb}
        governanceWeakness
        onApproveOnce={() => {}}
        onApproveAlways={() => {}}
        onReject={() => {}}
      />,
    );
    // 须是确认变体，非「自动放行」。
    expect(container.querySelector("[data-gate-panel]")).not.toBeNull();
    expect(container.querySelector("[data-gate-auto-pass]")).toBeNull();
    expect(screen.getByText(/bypass 也不跳此门/)).toBeInTheDocument();
    expect(screen.getByText("side_effect: realmoney")).toBeInTheDocument();
  });

  it("UI：页内触发真钱反例（任意权限）→ 弹确认门，证 D-PERM 可见", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    // 先切到 bypass（最宽权限）。
    fireEvent.click(screen.getByText("bypass"));
    fireEvent.click(screen.getByText(/真钱反例/));
    const demo = container.querySelector("#blk-demo-gate [data-gate-panel]");
    expect(demo).not.toBeNull();
    expect(demo).toHaveAttribute("data-gate-side-effect", "realmoney");
  });

  it("对抗：若把 realmoney 当 none 放行（自动 pass）必抓——auto-pass 变体不可出现于真钱", () => {
    const { container } = renderWithDesk(
      <GatePanel
        permMode="bypass"
        gateTool="order.submit"
        sideEffect="realmoney"
        gateBlurb="真钱"
        onApproveOnce={() => {}}
        onApproveAlways={() => {}}
        onReject={() => {}}
      />,
    );
    // 种「真钱被当 none 自动放行」门：data-gate-auto-pass 必须不存在。
    expect(container.querySelector("[data-gate-auto-pass]")).toBeNull();
  });
});

describe("治理红线 ② — self-approve（→auto）加二次确认（T-030 · 对抗 #2）", () => {
  it("点「批准且不再问」不立即升 auto —— 先出二次确认步", () => {
    let upgraded = false;
    const { container } = renderWithDesk(
      <GatePanel
        permMode="ask"
        gateTool="backtest.run"
        sideEffect="none"
        gateBlurb="跑回测"
        onApproveOnce={() => {}}
        onApproveAlways={() => {
          upgraded = true;
        }}
        onReject={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("2. 批准且不再问"));
    // 二次确认步出现，onApproveAlways 尚未触发（没有一键自批）。
    expect(container.querySelector("[data-self-approve-confirm]")).not.toBeNull();
    expect(upgraded).toBe(false);
    // 再点确认才真正升级。
    fireEvent.click(screen.getByText("确认升级为 auto"));
    expect(upgraded).toBe(true);
  });

  it("对抗：种「self-approve 无二次确认」必抓 —— 一键点 always 不得直接 upgrade", () => {
    let upgraded = false;
    renderWithDesk(
      <GatePanel
        permMode="ask"
        gateTool="backtest.run"
        sideEffect="none"
        gateBlurb="跑回测"
        onApproveOnce={() => {}}
        onApproveAlways={() => {
          upgraded = true;
        }}
        onReject={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("2. 批准且不再问"));
    // 若实现是「一键直升」，此处 upgraded 已 true → 测试抓住缺二次确认的回归。
    expect(upgraded).toBe(false);
  });

  it("二次确认可取消——取消后 onApproveAlways 始终不触发", () => {
    let upgraded = false;
    const { container } = renderWithDesk(
      <GatePanel
        permMode="ask"
        gateTool="backtest.run"
        sideEffect="none"
        gateBlurb="跑回测"
        onApproveOnce={() => {}}
        onApproveAlways={() => {
          upgraded = true;
        }}
        onReject={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("2. 批准且不再问"));
    fireEvent.click(screen.getByText("取消"));
    expect(container.querySelector("[data-self-approve-confirm]")).toBeNull();
    expect(upgraded).toBe(false);
  });
});

describe("治理红线 ③ — side_effect 受控真值，不前端伪造（对抗 #3）", () => {
  it("GatePanel 渲染的 side_effect 来自 props（受控），改 prop 即改展示", () => {
    const { rerender } = renderWithDesk(
      <GatePanel
        permMode="ask"
        gateTool="t"
        sideEffect="none"
        gateBlurb="b"
        onApproveOnce={() => {}}
        onApproveAlways={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText("side_effect: none")).toBeInTheDocument();
    rerender(
      <GatePanel
        permMode="ask"
        gateTool="t"
        sideEffect="realmoney"
        gateBlurb="b"
        onApproveOnce={() => {}}
        onApproveAlways={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText("side_effect: realmoney")).toBeInTheDocument();
  });

  it("对抗：把 realmoney 伪造成 none 想绕治理门 → 仍恒须确认（治理逻辑不信前端伪 none）", () => {
    // gateNeedsConfirm 只认传入的 sideEffect 真值；若上游伪造成 none 想绕，
    // 后端 tool_status 真值才是依据——这里证明：只要真值是 realmoney，恒拦。
    expect(gateNeedsConfirm("bypass", "realmoney")).toBe(true);
    // 反面对照：none 真值在 bypass 才放行（正确放行不算伪造）。
    expect(gateNeedsConfirm("bypass", "none")).toBe(false);
  });

  it("源码不读 DOM 造 side_effect 默认（side_effect 必须由 props 进）", () => {
    const src = readFileSync(join(here, "permGate.ts"), "utf8");
    // permGate 是纯函数，不得出现 document/getElementById/querySelector 等读 DOM 造值。
    expect(/document\.|getElementById|querySelector/.test(src)).toBe(false);
  });
});

describe("治理红线 ④ — 治理弱点 block 常驻展开不可折叠（R25 · 对抗 #4）", () => {
  it("isGovernanceWeakness：realmoney/external/显式标记 → true", () => {
    expect(isGovernanceWeakness("realmoney")).toBe(true);
    expect(isGovernanceWeakness("external")).toBe(true);
    expect(isGovernanceWeakness("none", true)).toBe(true);
    expect(isGovernanceWeakness("none")).toBe(false);
  });

  it("真钱 gate：强制展开 + 无折叠控件（种折叠默认必抓）", () => {
    renderWithDesk(
      <GatePanel
        permMode="ask"
        gateTool="order.submit"
        sideEffect="realmoney"
        gateBlurb="真钱"
        onApproveOnce={() => {}}
        onApproveAlways={() => {}}
        onReject={() => {}}
      />,
    );
    const gate = document.querySelector('[data-block="gate"]') as HTMLElement;
    expect(gate.dataset.expanded).toBe("true");
    // 弱点类绝不渲染折叠控件——无从藏起。
    expect(screen.queryByLabelText("折叠")).toBeNull();
    expect(screen.queryByLabelText("展开")).toBeNull();
  });

  it("血统标记（因子集卡 ← 因子台）常驻渲染、无折叠控件", () => {
    const unlocked = new Set<CoworkKind>(["factorSet"]);
    const { container } = renderWithDesk(
      <CoworkArea cowork="factorSet" unlocked={unlocked} />,
    );
    const lineage = container.querySelectorAll("[data-lineage-badge]");
    expect(lineage.length).toBeGreaterThan(0);
    expect(within(lineage[0] as HTMLElement).queryByText(/因子台/)).not.toBeNull();
  });

  it("模型卡血统标记（← Model台 · staging）常驻渲染", () => {
    const unlocked = new Set<CoworkKind>(["model"]);
    const { container } = renderWithDesk(
      <CoworkArea cowork="model" unlocked={unlocked} />,
    );
    const badge = container.querySelector(
      "[data-lineage-badge]",
    ) as HTMLElement;
    expect(badge).not.toBeNull();
    expect(badge.textContent).toContain("Model台");
    expect(badge.textContent).toContain("staging");
  });
});

describe("治理红线 ⑤ — handoff 止于模拟盘，不导向实盘（D-PERM · 对抗 #5）", () => {
  it("跑完剧本 → handoff 卡出现，文案指向模拟台候选池", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    fireEvent.click(screen.getByText("1. 批准本次"));
    const handoff = container.querySelector("[data-handoff-card]");
    expect(handoff).not.toBeNull();
    const text = (handoff as HTMLElement).textContent ?? "";
    expect(text).toContain("模拟台");
    expect(text).toContain("候选");
  });

  it("对抗：handoff 文案种「直推实盘」必抓 —— 不得出现实盘直推语", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(container);
    fireEvent.click(screen.getByText("1. 批准本次"));
    const handoff = container.querySelector("[data-handoff-card]") as HTMLElement;
    const text = handoff.textContent ?? "";
    // handoff 默认导向绝不含「实盘/直接下单/动钱」等跳级实盘语。
    for (const banned of ["实盘", "直接下单", "动钱", "立即买入", "真实下单"]) {
      expect(text).not.toContain(banned);
    }
  });

  it("HandoffCard 源码不含直推实盘措辞（静态守卫）", () => {
    const src = readFileSync(join(here, "HandoffCard.tsx"), "utf8");
    for (const banned of ["实盘下单", "直接实盘", "立即下单"]) {
      expect(src).not.toContain(banned);
    }
  });
});

describe("DS-3 · liveRunId 贯穿裁决卡（真 run_id → LiveRunVerdictCard 非 mock · #4）", () => {
  function jsonRes(body: unknown, ok = true, status = 200): Response {
    return { ok, status, json: async () => body } as unknown as Response;
  }
  let spy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    spy = vi.spyOn(auth, "authFetch");
    // 真 run_id 贯穿 → 裁决卡真实后端三端点（不写死 mock 0.18/1.34）。
    spy.mockImplementation((url: RequestInfo) => {
      const u = String(url);
      if (u.includes("/overfit"))
        return Promise.resolve(
          jsonRes({ pbo: 0.42, dsr_conservative: 0.91, bootstrap_ci: [0.07, 1.22] }),
        );
      if (u.includes("/cost-sensitivity"))
        return Promise.resolve(jsonRes({ cost: [] }));
      if (u.includes("/verdict"))
        return Promise.resolve(
          jsonRes({ run_id: "run_live_z", verdict: "consistent", verdictNote: "证据一致；适用域：该样本期；未验证项：实盘冲击成本。" }),
        );
      return Promise.resolve(jsonRes({ metrics: {} }));
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("有真 liveRunId → CoworkArea 渲染 LiveRunVerdictCard（live testid），不退 mock", async () => {
    const unlocked = new Set<CoworkKind>(["run"]);
    renderWithDesk(
      <CoworkArea cowork="run" unlocked={unlocked} liveRunId="run_live_z" />,
    );
    // 走 live 卡（真实后端三端点），非写死 MOCK_AGENT_RUN。
    await waitFor(() =>
      expect(screen.getByTestId("live-run-verdict-card")).toBeInTheDocument(),
    );
    // run_id 真贯穿到 fetch（裁决/overfit/cost-sensitivity 都带该 id）。
    const urls = (spy.mock.calls as unknown[][]).map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/run_live_z/overfit"))).toBe(true);
    // PBO/DSR 来自该 run（0.42 / 0.91），非写死 mock（0.18 / 1.34）。
    expect(screen.getByText("0.42")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
    // 第三腿来自该 run 的 bootstrap_ci。
    expect(screen.getByText("[0.07, 1.22]")).toBeInTheDocument();
  });

  it("无 liveRunId → 退回 mock RunVerdictCard（恒挂 MockBadge，不假绿灯）", () => {
    const unlocked = new Set<CoworkKind>(["run"]);
    renderWithDesk(<CoworkArea cowork="run" unlocked={unlocked} />);
    // 无真 run_id → 不渲染 live 卡，走 mock（MOCK 角标 + 写死 0.18/1.34）。
    expect(screen.queryByTestId("live-run-verdict-card")).toBeNull();
    expect(screen.getByTestId("run-verdict-card")).toBeInTheDocument();
    expect(screen.getAllByText("MOCK 数据").length).toBeGreaterThanOrEqual(1);
    // mock 卡同样补齐三腿（第三格 Bootstrap CI 在）。
    expect(screen.getByText("Bootstrap CI")).toBeInTheDocument();
  });
});

describe("§3 handoff 提交失败诚实呈现（不假绿灯）", () => {
  afterEach(() => vi.restoreAllMocks());

  /** 跑完剧本铺出 handoff 卡（DS-2 默认真实流后先进「看演示」demoMode 才有 mock 剧本，再点「批准本次」解锁 report + handoff）。 */
  function openHandoff() {
    const r = renderWithDesk(<AgentWorkbenchPage />);
    enterDemo(r.container);
    fireEvent.click(screen.getByText("1. 批准本次"));
    return r;
  }

  it("后端非 ok（如未登录 401）→ 显式报错、不显「已提交」绿、不伪「（mock 回执）已提交」", async () => {
    vi.spyOn(authModule, "authFetch").mockResolvedValue(
      new Response("unauthorized", { status: 401 }),
    );
    openHandoff();
    fireEvent.click(screen.getByText(/提交进模拟台候选/));
    // 失败诚实态：handoff-error 出现。
    const err = await screen.findByTestId("handoff-error");
    expect(err.textContent ?? "").toMatch(/失败/);
    // 绝不出现「已提交」成功绿回执，也不出现旧的「（mock 回执）」伪成功文案。
    expect(screen.queryByText(/✓ 已提交/)).toBeNull();
    expect(screen.queryByText(/mock 回执/)).toBeNull();
    // 提交按钮仍在（未伪成功切到回执态）。
    expect(screen.getByText(/提交进模拟台候选/)).toBeInTheDocument();
  });

  it("网络失败（authFetch 抛）→ 显式报错、不伪「已提交」", async () => {
    vi.spyOn(authModule, "authFetch").mockRejectedValue(new Error("network down"));
    openHandoff();
    fireEvent.click(screen.getByText(/提交进模拟台候选/));
    const err = await screen.findByTestId("handoff-error");
    expect(err.textContent ?? "").toMatch(/网络不可用/);
    expect(screen.queryByText(/✓ 已提交/)).toBeNull();
    expect(screen.queryByText(/mock 回执/)).toBeNull();
  });

  it("后端 ok → 真显「已提交」绿回执（成功路径仍诚实可达）", async () => {
    vi.spyOn(authModule, "authFetch").mockResolvedValue(
      new Response(
        JSON.stringify({ candidate_id: "cand_1", destination: "paper_desk" }),
        { status: 200 },
      ),
    );
    openHandoff();
    fireEvent.click(screen.getByText(/提交进模拟台候选/));
    await waitFor(() =>
      expect(screen.getByText(/进入模拟台候选池/)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("handoff-error")).toBeNull();
  });

  it("源码守卫：handoff 失败分支不得再用「（mock 回执）...已提交」伪成功", () => {
    const src = readFileSync(join(here, "AgentWorkbenchPage.tsx"), "utf8");
    // 失败路径绝不再 setHandoffSubmitted(true) 配 mock 回执文案。
    expect(src).not.toContain("（mock 回执：真端点需登录");
    expect(src).not.toContain("（mock 回执：网络不可用");
  });
});

describe("研究执行台 · 措辞 / 冻结 / token 守卫", () => {
  it("RunVerdictCard verdictNote 不含 R7 禁词（裁决措辞走后端）", () => {
    // mock verdictNote 由 agentMock 持有——扫禁词。
    const src = readFileSync(join(here, "agentMock.ts"), "utf8");
    // 抽出 verdictNote 字符串内容做扫描（不扫注释/字段名）。
    const m = src.match(/verdictNote:\s*"([^"]*)"/);
    expect(m).not.toBeNull();
    assertNoForbiddenWords(m ? m[1] : "");
  });

  it("不引用冻结 RunDetailPage（裁决卡须旁挂、不嵌冻结页）", () => {
    const files = readdirSync(here).filter(
      (f) => /\.tsx?$/.test(f) && !f.includes(".test."),
    );
    for (const f of files) {
      assertNoFrozenPageImport(readFileSync(join(here, f), "utf8"));
    }
  });

  it("对抗：本台源码禁裸 hex 色值（须走 --desk-* token）", () => {
    const files = readdirSync(here).filter(
      (f) => /\.tsx?$/.test(f) && !f.includes(".test."),
    );
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(join(here, f), "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });

  it("不碰 App.tsx（本卡仅新建 agent-workbench，路由由主控接）", () => {
    const files = readdirSync(here);
    expect(files).not.toContain("App.tsx");
  });

  it("剧本里所有 gate 的 side_effect 都是受控真值（无 undefined 漏写）", () => {
    const gates = AGENT_SCRIPT.filter((e) => e.block.type === "gate");
    expect(gates.length).toBeGreaterThan(0);
    for (const g of gates) {
      expect(g.block.sideEffect).toBeDefined();
    }
  });
});
