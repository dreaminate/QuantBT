import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent, within } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";
import { ModelDeskPage } from "../ModelDeskPage";
import { validateApprove } from "./modelMock";

/**
 * M1 Model台 对抗测试。
 * 必含三条本卡门：
 *   ① 晋级门「批准」缺 approver≠creator / reason / risk_restated 时禁止提交（对齐后端 422）
 *   ② 防泄露：Purged-CV / embargo / 未跑 walk-forward 不渲染成假绿
 *   ③ 构建台标注「DL 走子进程，主进程不碰 torch」(M6)
 * 外加：零硬编码色（hex 扫描）+ MockBadge 诚实角标 + data-desk="model" 蓝 accent。
 */

const here = dirname(fileURLToPath(import.meta.url));
const pageDir = join(here, "..");

function srcFiles(dir: string): string[] {
  return readdirSync(dir)
    .filter((f) => /\.tsx?$/.test(f) && !f.includes(".test."))
    .map((f) => join(dir, f));
}

describe("M1 Model台 · 渲染与导航", () => {
  it("DeskShell data-desk='model'（蓝 accent），四子台 SubTabBar 齐", () => {
    const { container } = renderWithDesk(<ModelDeskPage />, { route: "/models" });
    expect(container.querySelector('[data-desk="model"]')).not.toBeNull();
    expect(screen.getByText(/作业台/)).toBeInTheDocument();
    expect(screen.getByText(/模型库注册表/)).toBeInTheDocument();
    expect(screen.getByText(/构建台/)).toBeInTheDocument();
    expect(screen.getByText(/研究台/)).toBeInTheDocument();
  });

  it("作业台默认可见：实时曲线 epoch 进度条 + 算力 + CV folds + MockBadge", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    expect(screen.getAllByText(/Purged k-fold/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/算力/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("MOCK 数据").length).toBeGreaterThan(0);
  });

  it("子台切换：可切到注册表 / 构建台 / 研究台", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/模型库注册表/));
    expect(screen.getByText(/不可裸翻/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/构建台/));
    expect(screen.getByText(/组件库/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/研究台/));
    expect(screen.getByText(/FactorVAE · forward 推导/)).toBeInTheDocument();
  });
});

describe("M1 对抗① · 晋级审批门（缺字段禁止提交，对齐后端 422）", () => {
  it("validateApprove：空 approver / 空 reason / 未勾 risk_restated 各自阻止", () => {
    // 全空 → 三条阻止
    expect(validateApprove({ approver: "", reason: "", riskRestated: false }, "alice")).toHaveLength(3);
    // self-approve（approver == creator）→ 阻止
    expect(
      validateApprove({ approver: "alice", reason: "ok", riskRestated: true }, "alice"),
    ).toContain("approver 不可等于 creator（禁止自批 / self-approve）");
    // 缺 risk_restated → 阻止
    expect(
      validateApprove({ approver: "bob", reason: "ok", riskRestated: false }, "alice"),
    ).toHaveLength(1);
    // 三者齐 + approver≠creator → 放行
    expect(
      validateApprove({ approver: "bob", reason: "复述风险后晋级", riskRestated: true }, "alice"),
    ).toEqual([]);
  });

  it("UI：打开晋级门，批准按钮初始 disabled；缺字段时列出阻止原因", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/模型库注册表/));
    // lgbm_rank_6f 处于 staging，可晋级到 production
    fireEvent.click(screen.getByText(/晋级 → production/));
    const approve = screen.getByText("DEMO · 未提交后端") as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    // 阻止原因列出（approver 必填）
    expect(screen.getByText(/approver 必填/)).toBeInTheDocument();
  });

  it("UI：self-approve（approver = creator dreaminate）仍被阻止、按钮不可点", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/模型库注册表/));
    fireEvent.click(screen.getByText(/晋级 → production/));
    fireEvent.change(screen.getByLabelText("approver"), { target: { value: "dreaminate" } });
    fireEvent.change(screen.getByLabelText("reason"), { target: { value: "looks good" } });
    fireEvent.click(screen.getByLabelText("risk_restated"));
    const approve = screen.getByText("DEMO · 未提交后端") as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(screen.getByText(/禁止自批/)).toBeInTheDocument();
  });

  it("UI：表单齐全仅完成 DEMO 校验，仍不提交后端或报告成功", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/模型库注册表/));
    fireEvent.click(screen.getByText(/晋级 → production/));
    fireEvent.change(screen.getByLabelText("approver"), { target: { value: "reviewer-2" } });
    fireEvent.change(screen.getByLabelText("reason"), { target: { value: "staging 实测达标" } });
    fireEvent.click(screen.getByLabelText("risk_restated"));
    const approve = screen.getByText("DEMO · 未提交后端") as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(screen.getByTestId("promote-demo-only")).toHaveTextContent(/未调用后端晋级端点/);
    expect(screen.queryByText(/晋级请求已提交审批/)).toBeNull();
  });
});

describe("M1 对抗② · 防泄露（Purged-CV / embargo / 未跑 walk-forward 不假绿）", () => {
  it("作业台 CV 卡显式 Purged k-fold + embargo 1% + 防标签穿越", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    expect(screen.getByText(/Purged k-fold · embargo 1%/)).toBeInTheDocument();
    expect(screen.getByText(/防标签穿越/)).toBeInTheDocument();
  });

  it("DRILL-IN：未训完模型(tcn_alpha_v1) walk-forward 标『待跑』而非绿色通过", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/模型库注册表/));
    // 打开 tcn_alpha_v1（未注册、wf 待跑）详情
    const card = document.querySelector('[data-model-card="tcn_alpha_v1"]') as HTMLElement;
    expect(card).not.toBeNull();
    fireEvent.click(within(card).getByText("tcn_alpha_v1"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/walk-forward 待跑/)).toBeInTheDocument();
    // 不渲染成已通过：没有逐窗表格行
    expect(within(dialog).queryByText("W1")).toBeNull();
  });

  it("DRILL-IN：已训模型 walk-forward 负窗用 danger 色诚实标注（不一律绿）", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/模型库注册表/));
    const card = document.querySelector('[data-model-card="gbdt_baseline"]') as HTMLElement;
    fireEvent.click(within(card).getByText("gbdt_baseline"));
    const dialog = screen.getByRole("dialog");
    // gbdt W3/W4 为负超额，须出现负值
    expect(within(dialog).getByText("-0.6%")).toBeInTheDocument();
    expect(within(dialog).getByText("-1.2%")).toBeInTheDocument();
  });
});

describe("M1 对抗③ · 构建台 M6 子进程隔离标注", () => {
  it("构建台代码面板标注「DL 走子进程，主进程不碰 torch」", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/构建台/));
    // 默认代码面板未展开，点开「代码」
    fireEvent.click(screen.getByText(/‹ 代码/));
    const note = document.querySelector("[data-subprocess-note]");
    expect(note).not.toBeNull();
    expect(note!.textContent).toMatch(/主进程不碰 torch/);
    expect(note!.textContent).toMatch(/子进程/);
  });

  it("构建台用共享 GraphCanvas 引擎（data-graph-surface 存在）", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/构建台/));
    expect(document.querySelector("[data-graph-surface]")).not.toBeNull();
  });
});

describe("M1 对抗④ · token 不漂 + 诚实角标", () => {
  it("零硬编码 hex：Model台所有页面/组件实现禁裸 hex（须走 --desk-* token）", () => {
    const files = [...srcFiles(here), ...srcFiles(pageDir).filter((f) => f.includes("ModelDeskPage"))];
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(f, "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });

  it("研究台理论判定结论为隐患态（非假绿）：结论卡含 M11 因子门提醒", () => {
    renderWithDesk(<ModelDeskPage />, { route: "/models" });
    fireEvent.click(screen.getByText(/研究台/));
    const conc = document.querySelector("[data-rs-conclusion]");
    expect(conc).not.toBeNull();
    expect(conc!.textContent).toMatch(/因子台做 IC/);
  });
});
