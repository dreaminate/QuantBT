import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { type ReactNode } from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { Routes, Route, MemoryRouter, useLocation } from "react-router-dom";
import { assertNoFrozenPageImport } from "../../test/harness";
import { StrategyConsolePage } from "../StrategyConsolePage";
import {
  MOCK_NODES,
  MOCK_EDGES,
  MOCK_PROPOSAL,
  toNodeView,
  type DomainPort,
} from "./mockGraph";
import { validateGraph, canDelete, compat } from "./graphLogic";

const here = dirname(fileURLToPath(import.meta.url));
const pageSrcDir = dirname(here); // src/pages

function toDict() {
  const d: Record<string, (typeof MOCK_NODES)[number]> = {};
  for (const n of MOCK_NODES) d[n.id] = n;
  return d;
}

function LocationProbe({ onChange }: { onChange?: (p: string) => void }) {
  const loc = useLocation();
  if (onChange) onChange(loc.pathname);
  return <div data-testid="run-detail-probe">{loc.pathname}</div>;
}
function RouterHarness({ children, routeSpy }: { children: ReactNode; routeSpy?: (p: string) => void }) {
  return (
    <MemoryRouter initialEntries={["/strategy"]}>
      <Routes>
        <Route path="/strategy" element={children} />
        <Route path="/runs/:runId" element={<LocationProbe onChange={routeSpy} />} />
      </Routes>
    </MemoryRouter>
  );
}

/** 渲染策略台并挂一个 /runs/:runId 探针路由，捕获单段跳转。 */
function renderPage(routeSpy?: (path: string) => void) {
  return render(
    <RouterHarness routeSpy={routeSpy}>
      <StrategyConsolePage />
    </RouterHarness>,
  );
}

describe("S1 策略台 · 渲染骨架", () => {
  it("DeskShell data-desk='strategy'（橙 accent）+ 顶栏 DeskSwitcher current=strategy + 策略名/版本/runtime 段控", () => {
    const { container } = renderPage();
    const root = container.querySelector(".desk-root") as HTMLElement;
    expect(root.dataset.desk).toBe("strategy");
    // 台切换器当前态 = 策略台（实心 span，不是链接）
    expect(screen.getByText("策略台").tagName).toBe("SPAN");
    expect(screen.getByText("strat_wk_cn_01")).toBeInTheDocument();
    expect(screen.getByText(/v3 草稿/)).toBeInTheDocument();
    // runtime 三态段控
    expect(screen.getByRole("tab", { name: "Backtest" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Paper" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Live" })).toBeInTheDocument();
    // 顶栏动作
    expect(screen.getByText(/运行回测/)).toBeInTheDocument();
    expect(screen.getByText(/编译源码/)).toBeInTheDocument();
    expect(screen.getByText("发布 ▸")).toBeInTheDocument();
  });

  it("中区渲染 17 节点 + 19 连线（mock DAG · DC defs[] 真值，narration「16」off-by-one）", () => {
    const { container } = renderPage();
    // 先拒绝 Ask 提议，去掉 ghost 预览节点，得到纯初始图。
    fireEvent.click(screen.getByText("拒绝"));
    const nodeEls = container.querySelectorAll("[data-node-id]");
    expect(nodeEls.length).toBe(17);
    const edgeEls = container.querySelectorAll("[data-edge-id]");
    expect(edgeEls.length).toBe(19);
  });

  it("左 Agent(316 可折叠) / 右 Inspector(340) / 底 Dock 默认折叠", () => {
    const { container } = renderPage();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    const insp = container.querySelector("[data-inspector]") as HTMLElement;
    expect(insp.style.width).toBe("340px");
    // dock 默认折叠：出折叠条、无展开 dock
    expect(container.querySelector("[data-dock-collapsed]")).not.toBeNull();
    expect(container.querySelector("[data-dock]")).toBeNull();
  });
});

describe("S1 对抗①：节点「↗打开回测」用 navigate('/runs/:runId') 单段", () => {
  it("点开回测 → 路径命中 /^\\/runs\\/[^/]+$/（单段，不嵌 RunDetailPage）", () => {
    const seen: string[] = [];
    const { container } = renderPage((p) => seen.push(p));
    fireEvent.click(container.querySelector("[data-open-run]")!);
    const last = seen[seen.length - 1];
    expect(last).toMatch(/^\/runs\/[^/]+$/);
    expect(last).toBe("/runs/run_wk_cn_8f2a");
  });

  it("源码不 import 冻结 RunDetailPage（旁挂跳转，非嵌入）", () => {
    const src = readFileSync(join(pageSrcDir, "StrategyConsolePage.tsx"), "utf8");
    assertNoFrozenPageImport(src);
    expect(src).not.toMatch(/import[^;]*RunDetailPage/);
  });
});

describe("S1 对抗②：Final Risk Gate 节点 locked，不可删", () => {
  it("逻辑层 canDelete：gate=false（locked），普通节点=true", () => {
    const dict = toDict();
    expect(canDelete(dict.gate)).toBe(false);
    expect(canDelete(dict.signal)).toBe(true);
  });

  it("UI：选中 gate 按 Delete 后节点仍在（删除门跳过 locked）", () => {
    const { container } = renderPage();
    // 选中 Final Risk Gate（点节点卡 head，避开 desc 文本里的同名串）
    const gateCard = container.querySelector("[data-node-id='gate']") as HTMLElement;
    fireEvent.click(gateCard);
    fireEvent.keyDown(window, { key: "Delete" });
    expect(container.querySelector("[data-node-id='gate']")).not.toBeNull();
  });

  it("对照：选中普通节点（信号 Signal）按 Delete 可删", () => {
    const { container } = renderPage();
    const sigCard = container.querySelector("[data-node-id='signal']") as HTMLElement;
    fireEvent.click(sigCard);
    fireEvent.keyDown(window, { key: "Delete" });
    expect(container.querySelector("[data-node-id='signal']")).toBeNull();
  });
});

describe("S1 对抗③：runtime==='live' 时画布只读 + 参数 disabled + 🔒Live只读", () => {
  it("切 Live → 出现 🔒 Live 只读 + 画布只读 banner + Fork/Kill", () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    expect(screen.getByText("🔒 Live 只读")).toBeInTheDocument();
    expect(screen.getByText(/Live 只读 · 画布与参数已锁定/)).toBeInTheDocument();
    expect(screen.getByText("⑂ Fork 草稿")).toBeInTheDocument();
    expect(screen.getByLabelText("Kill Switch")).toBeInTheDocument();
  });

  it("Live 下选中节点 → Inspector 参数 input 全 disabled", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    fireEvent.click(screen.getByText("信号 Signal"));
    const inputs = container.querySelectorAll("[data-param-row] input");
    expect(inputs.length).toBeGreaterThan(0);
    inputs.forEach((i) => expect((i as HTMLInputElement).disabled).toBe(true));
  });

  it("Live 下节点不可拖（拖拽不改坐标）", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    const gateHead = container.querySelector("[data-node-head='signal']") as HTMLElement;
    const card = container.querySelector("[data-node-id='signal']") as HTMLElement;
    const x0 = card.style.left;
    fireEvent.pointerDown(gateHead, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 300, clientY: 300 });
    fireEvent.pointerUp(window);
    expect(card.style.left).toBe(x0);
  });
});

describe("S1 对抗④：agentMode='bypass' 时 UI 仍显治理门拦（权限轴 ⟂ 治理轴）", () => {
  it("Bypass 模式 + Live → 🔒Live只读治理门仍在（权限态不跳治理门）", () => {
    renderPage();
    // 切 bypass 权限
    fireEvent.click(screen.getByRole("tab", { name: "Bypass" }));
    // 状态行展示 bypass（受控展示，不可编辑）
    const status = document.querySelector("[data-status-row]") as HTMLElement;
    expect(within(status).getByText(/bypass/)).toBeInTheDocument();
    // 切 Live：治理门（Live 只读）仍出现，bypass 不绕过
    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    expect(screen.getByText("🔒 Live 只读")).toBeInTheDocument();
    expect(screen.getByText(/Live 只读 · 画布与参数已锁定/)).toBeInTheDocument();
  });

  it("Bypass 下 Final Risk Gate 仍 locked 不可删（治理轴独立于权限轴）", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Bypass" }));
    fireEvent.click(screen.getByText("Final Risk Gate"));
    const before = container.querySelectorAll("[data-node-id]").length;
    fireEvent.keyDown(window, { key: "Delete" });
    expect(container.querySelectorAll("[data-node-id]").length).toBe(before);
  });
});

describe("S1 对抗⑤：mock 区块带 MockBadge（B9 诚实，不假绿灯）", () => {
  it("画布工具条 + dock 历史 + Inspector 贡献卡均挂 MOCK 角标", () => {
    const { container } = renderPage();
    // 工具条 MOCK 数据角标
    expect(screen.getAllByText(/MOCK/).length).toBeGreaterThan(0);
    // 选中有贡献的节点 → 切版本/血缘 tab → 贡献卡带 MockBadge
    fireEvent.click(screen.getByText("信号 Signal"));
    fireEvent.click(screen.getByRole("tab", { name: "版本/血缘" }));
    const contrib = container.querySelector("[data-contribution]") as HTMLElement;
    expect(within(contrib).getByText(/MOCK/)).toBeInTheDocument();
  });
});

describe("S1 治理逻辑 · 连线门/校验门（B6 三层强制）", () => {
  it("连线门 compat：role='exec' 来源非 approvedPortfolio → bad（不可绕 Final Gate）", () => {
    // exec 入口 dt=approvedPortfolio（与 Final Gate 输出一致，DC exec.ins）。
    const execIn: DomainPort = { id: "ap", name: "approvedPortfolio", dt: "approvedPortfolio", freq: "W", scope: "", req: true, role: "exec", schema: "" };
    const fromGate: DomainPort = { id: "ap", name: "approvedPortfolio", dt: "approvedPortfolio", freq: "W", scope: "", req: true, role: "", schema: "" };
    const fromOther: DomainPort = { id: "rp", name: "riskedPortfolio", dt: "riskedPortfolio", freq: "W", scope: "", req: true, role: "", schema: "" };
    expect(compat(fromGate, execIn).s).toBe("ok");
    expect(compat(fromOther, execIn).s).toBe("bad");
    expect(compat(fromOther, execIn).reason).toMatch(/Final Risk Gate/);
  });

  it("校验门 validateGraph：完整初始图 ok（exec 经 gate，无 bad）", () => {
    const v = validateGraph(toDict(), MOCK_EDGES);
    expect(v.ok).toBe(true);
    expect(v.errorCount).toBe(0);
  });

  it("校验门：把 exec 入边改接 prisk（绕过 gate）→ error 违反 B6", () => {
    const broken = MOCK_EDGES.map((e) =>
      e.id === "e17" ? { ...e, from: { node: "prisk", port: "rp" } } : e,
    );
    const v = validateGraph(toDict(), broken);
    expect(v.ok).toBe(false);
    expect(v.issues.some((i) => /B6/.test(i.text))).toBe(true);
  });

  it("adapt 频率门：bench(D) → backtest(b) 日频→周频或类型适配（非 bad）", () => {
    const v = validateGraph(toDict(), MOCK_EDGES);
    // e19 是 adapt，不应产生 bad error
    expect(v.issues.some((i) => /不兼容/.test(i.text))).toBe(false);
  });
});

describe("S1 Agent 权限三态 · 提议/事务化", () => {
  it("Ask：默认挂 Ghost 提议卡 + 画布出 ghost 虚线边；接受后 patch 块入对话", () => {
    const { container } = renderPage();
    expect(container.querySelector("[data-proposal]")).not.toBeNull();
    // ghost 边渲染
    expect(container.querySelector("[data-ghost-edge-id='e_var']")).not.toBeNull();
    fireEvent.click(screen.getByText(/接受 Patch/));
    // 提议消失 + 新增 varcvar 节点
    expect(container.querySelector("[data-proposal]")).toBeNull();
    expect(container.querySelector("[data-node-id='varcvar']")).not.toBeNull();
    expect(screen.getByText(MOCK_PROPOSAL.patchId)).toBeInTheDocument();
  });

  it("拒绝提议 → 提议卡消失、不加节点", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByText("拒绝"));
    expect(container.querySelector("[data-proposal]")).toBeNull();
    expect(container.querySelector("[data-node-id='varcvar']")).toBeNull();
  });
});

describe("S1 视口 · 缩放/适应", () => {
  it("放大按钮 → zoom 上升（zoomPct 变化）", () => {
    const { container } = renderPage();
    const pct = () => (container.querySelector("[data-zoom-pct]") as HTMLElement).textContent;
    const before = pct();
    fireEvent.click(screen.getByLabelText("放大"));
    expect(pct()).not.toBe(before);
  });
});

describe("S1 对抗：mockGraph/页面源码禁裸 hex（须走 --desk-* token）", () => {
  it("strategy/ + StrategyConsolePage 不含 #hex 字面色", () => {
    const files: string[] = [];
    for (const f of readdirSync(here)) {
      if (/\.tsx?$/.test(f) && !f.includes(".test.")) files.push(join(here, f));
    }
    files.push(join(pageSrcDir, "StrategyConsolePage.tsx"));
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(f, "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });
});

describe("S1 mock 数据完整性（DC _build 对齐）", () => {
  it("17 节点含 gate(locked) / backtest(openRun) / 因子台·Model台 badge（DC defs[] 真值）", () => {
    expect(MOCK_NODES.length).toBe(17);
    expect(MOCK_NODES.find((n) => n.id === "gate")?.locked).toBe(true);
    expect(MOCK_NODES.find((n) => n.id === "backtest")?.openRun).toBe(true);
    expect(MOCK_NODES.find((n) => n.id === "factors")?.badge).toBe("← 因子台");
    expect(MOCK_NODES.find((n) => n.id === "model")?.badge).toBe("← Model台");
  });

  it("toNodeView 投影出渲染子集（含 locked/badge）", () => {
    const v = toNodeView(MOCK_NODES.find((n) => n.id === "gate")!);
    expect(v.locked).toBe(true);
    expect(v.title).toBe("Final Risk Gate");
    expect(v.ins.length).toBe(1);
  });

  it("19 连线 + 唯一 id", () => {
    expect(MOCK_EDGES.length).toBe(19);
    expect(new Set(MOCK_EDGES.map((e) => e.id)).size).toBe(19);
  });
});
