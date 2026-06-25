import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent, within } from "@testing-library/react";
import { renderWithDesk, assertNoFrozenPageImport } from "../../../test/harness";
import { PaperDeskPage } from "../PaperDeskPage";
import { PaperBoardCard } from "../../../components/PaperBoardCard";

const here = dirname(fileURLToPath(import.meta.url));
const viewsDir = join(here, "views");
const boardCard = join(here, "..", "..", "..", "components", "PaperBoardCard.tsx");
const pagePath = join(here, "..", "PaperDeskPage.tsx");

/** 递归收集本卡所有非测试 tsx/ts 源（供 hex 扫描）。 */
function collectSources(dir: string): string[] {
  const out: string[] = [];
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) {
      out.push(...collectSources(p));
    } else if (/\.tsx?$/.test(f) && !f.includes(".test.")) {
      out.push(p);
    }
  }
  return out;
}

describe("模拟台 PaperDeskPage（DC→React · mock 驱动）", () => {
  it("渲染：paper accent（data-desk=paper）+ 默认运行盘视图 + MOCK 角标", () => {
    const { container } = renderWithDesk(<PaperDeskPage />, { route: "/paper" });
    const root = container.querySelector(".desk-root");
    expect(root).toHaveAttribute("data-desk", "paper");
    // 运行盘默认：调度器 KV 可见
    expect(screen.getByText("调度器 · PaperScheduler", { exact: false })).toBeInTheDocument();
    // MOCK 角标诚实常驻（不假绿灯）
    expect(screen.getAllByText("MOCK 数据").length).toBeGreaterThan(0);
  });

  it("子 tab 切换：5 视图互斥（运行盘→风险门→晋升通道）", () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("⛨ 风险门"));
    expect(screen.getByText("风险门 · 会话外不可改")).toBeInTheDocument();
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    expect(screen.getByText(/晋级判定/)).toBeInTheDocument();
    // 互斥：切到晋升后，调度器面板不再渲染
    expect(screen.queryByText("调度器 · PaperScheduler", { exact: false })).toBeNull();
  });

  it("市场切换：A股→加密，余额/clock 随之换 ¥↔$", () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("⊞ 持仓与成交"));
    expect(screen.getByText("¥1,041,200")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "加密" }));
    expect(screen.getByText("$108,300")).toBeInTheDocument();
  });

  it("选择 run：点侧栏切换当前 run（头部 name 随之变）", () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("crypto_perp_mom"));
    // 头部 17px name + 侧栏卡都叫此名；运行盘头部出现
    expect(screen.getAllByText("crypto_perp_mom").length).toBeGreaterThanOrEqual(1);
  });
});

describe("PaperBoardCard（可复用嵌入卡）", () => {
  it("渲染：metrics + 净值缩略 + 持仓 + 风险门 4 格 + MOCK 角标", () => {
    renderWithDesk(<PaperBoardCard />);
    expect(screen.getByText("今日盈亏")).toBeInTheDocument();
    expect(screen.getByText("超额(vs 500)")).toBeInTheDocument();
    expect(screen.getByLabelText("净值缩略图")).toBeInTheDocument();
    expect(screen.getByText("风险门 · 会话外不可改")).toBeInTheDocument();
    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
  });

  it("接入真实后端后可关角标：mock=false 不渲染 MOCK 角标", () => {
    renderWithDesk(<PaperBoardCard mock={false} />);
    expect(screen.queryByText("MOCK 数据")).toBeNull();
  });
});

// ════════════════ 本卡对抗测试 ════════════════
describe("对抗测试", () => {
  it("对抗#零硬编码色：本卡所有源禁裸 hex（须走 --desk-* token）", () => {
    const files = [...collectSources(here), boardCard];
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      // 容忍十六进制转义 \xNN 与 SVG marker id 引用（本卡无），仅查色值 #xxx
      const hits = src.match(HEX);
      if (hits) offenders.push(`${f.split("/paper/").pop()}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });

  it("对抗#1 A股永不 live 下单：UI 无任何 A股 live 下单路径（止于 paper）", () => {
    renderWithDesk(<PaperDeskPage />);
    // 全文不得出现「下单/真实下单/live 下单/真钱下单」等 A股实盘下单措辞
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/下单/);
    expect(body).not.toMatch(/live\s*order/i);
    // 须出现「A股止于 paper」的硬墙声明（诚实边界）
    expect(body).toContain("A股止于 paper");
    // 且页面无 type=submit / 下单按钮
    const buttons = screen.queryAllByRole("button");
    for (const b of buttons) {
      expect(b.textContent ?? "").not.toMatch(/下单|买入|卖出|建仓|平仓/);
    }
  });

  it("对抗#2 风险门会话外不可改：RISK 视图渲染为只读（无任何编辑控件）", () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("⛨ 风险门"));
    // 风险门区域内无 input / select / textarea / 可点编辑按钮
    const gates = screen.getAllByTestId("risk-gate");
    expect(gates.length).toBe(6);
    for (const g of gates) {
      expect(g.querySelectorAll("input,select,textarea,button").length).toBe(0);
    }
    // 冻结门（杠杆/回撤熔断）带 locked 标记
    const locked = gates.filter((g) => g.getAttribute("data-locked") === "true");
    expect(locked.length).toBe(2);
    for (const g of locked) {
      expect(within(g).getByText(/冻结/)).toBeInTheDocument();
    }
    // 「永不可改」措辞在场
    expect(screen.getByText("永不可改")).toBeInTheDocument();
  });

  it("对抗#3 晋升须人工+背书（INV-5）：表单未填→审批禁用、不一键自动晋级（§3 不假绿灯）", () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    // 默认 run 满 28 天且超额>0 → ready 态，但背书/理由未填 → 审批按钮禁用（裸翻必拒）。
    const btn = screen.getByRole("button", { name: /人工审批晋级/ });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/须填验证背书 \+ 理由/)).toBeInTheDocument();
    // 强行点禁用按钮不应晋级（无伪绿）。
    fireEvent.click(btn);
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("对抗#3a §3 无后端时填表提交 → 诚实失败、不伪「已晋级」", async () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    // 填背书 + 理由 → 按钮可点。
    fireEvent.change(screen.getByTestId("promote-endorsement"), {
      target: { value: "verdict_8f2a" },
    });
    fireEvent.change(screen.getByTestId("promote-reason"), {
      target: { value: "4 门全过，独立验证已背书" },
    });
    const btn = screen.getByRole("button", { name: /人工审批晋级/ });
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    // 无后端（openPromotionGate 抛）→ 显式失败态出现，绝不伪「已晋级」绿。
    expect(await screen.findByTestId("promote-error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("对抗#3b 不满足条件时审批不可点（blocked，禁用 + not-allowed）", () => {
    renderWithDesk(<PaperDeskPage />);
    // 切到 dividend_lowvol_cn：days=2 → daysIn=14 < 28 且 excess<0 → 不合格
    fireEvent.click(screen.getByText("dividend_lowvol_cn"));
    fireEvent.click(screen.getByText("⤴ 晋升通道"));
    const btn = screen.getByRole("button", { name: /人工审批晋级/ });
    expect(btn).toBeDisabled();
    // 点击禁用按钮不应晋级
    fireEvent.click(btn);
    expect(screen.queryByRole("button", { name: /已晋级/ })).toBeNull();
  });

  it("对抗#4 实盘衰减不折叠不染绿（R25）：劣化项保留黄/红 decay 色", () => {
    renderWithDesk(<PaperDeskPage />);
    fireEvent.click(screen.getByText("↺ 复盘归因"));
    // 年化收益衰减 −16% 不可染成功绿，须是 warning
    const decayCell = screen.getByText("−16%");
    expect(decayCell).toHaveStyle({ color: "var(--desk-warning)" });
    // 换手升 +4pt 染红（劣化），不折叠
    const turnover = screen.getByText("+4pt");
    expect(turnover).toHaveStyle({ color: "var(--desk-danger)" });
    // 衰减说明文案在场（不隐藏弱点）：note 段含「健康区间」诚实描述
    expect(screen.getByText(/落在「样本外打 7-8 折」的健康区间/)).toBeInTheDocument();
  });

  it("对抗#5 不嵌冻结页：源码未 import frontend-run-detail 的冻结 RunDetailPage", () => {
    const allSrc = [pagePath, boardCard, ...collectSources(here)]
      .map((f) => readFileSync(f, "utf8"))
      .join("\n");
    expect(() => assertNoFrozenPageImport(allSrc)).not.toThrow();
  });
});
