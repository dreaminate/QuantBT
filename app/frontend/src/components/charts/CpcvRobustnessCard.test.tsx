import { describe, it, expect } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithDesk } from "../../test/harness";
import {
  CpcvRobustnessCard,
  type CpcvDistributionData,
} from "./CpcvRobustnessCard";

const ROBUST: CpcvDistributionData = {
  status: "ok", metric: "r2", baseline: 0.0, n_paths: 5, n_groups: 6, k_test_groups: 2,
  mean: 0.62, std: 0.05, q05: 0.41, min: 0.39, median: 0.63, max: 0.7, frac_below_0: 0.0,
};
const FRAGILE: CpcvDistributionData = {
  status: "ok", metric: "r2", baseline: 0.0, n_paths: 5, n_groups: 6, k_test_groups: 2,
  mean: 0.05, std: 0.2, q05: -0.18, min: -0.3, median: 0.06, max: 0.25, frac_below_0: 0.4,
};

describe("R4 CpcvRobustnessCard · 路径稳健性（report-only·不假绿灯）", () => {
  it("ok：渲染 q05/mean/min/median/max + report-only note", () => {
    renderWithDesk(<CpcvRobustnessCard dist={ROBUST} />);
    expect(screen.getByTestId("cpcv-card")).toBeInTheDocument();
    expect(screen.getByText("0.410")).toBeInTheDocument();   // q05
    expect(screen.getByText("0.620")).toBeInTheDocument();   // mean
    expect(screen.getByTestId("cpcv-note")).toHaveTextContent(/report-only/);
  });

  it("**不假绿灯①**：q05≥基线（稳健）→ q05 中性色，绝不上成功绿", () => {
    renderWithDesk(<CpcvRobustnessCard dist={ROBUST} />);
    const q05 = screen.getByText("0.410");
    expect(q05).toHaveStyle({ color: "var(--cc-text-soft, #a0a0a0)" });
    expect(q05).not.toHaveStyle({ color: "var(--cc-success)" });   // 路径稳≠策略好
  });

  it("**不假绿灯②**：q05<无技能基线（脆弱）→ q05 警示色 + 脆弱 note，绝不绿", () => {
    renderWithDesk(<CpcvRobustnessCard dist={FRAGILE} />);
    const q05 = screen.getByText("-0.180");
    expect(q05).toHaveStyle({ color: "var(--cc-warning, #d68910)" });
    expect(q05).not.toHaveStyle({ color: "var(--cc-success)" });
    expect(screen.getByTestId("cpcv-note")).toHaveTextContent(/无优于随机|脆弱|过拟合/);
  });

  it("**不假绿灯③**：status≠ok（unsupported/insufficient）→ 状态提示，绝不渲染假分布数字", () => {
    renderWithDesk(<CpcvRobustnessCard dist={{ ...ROBUST, status: "unsupported_task", reason: "task=lambdarank" }} />);
    const card = screen.getByTestId("cpcv-card");
    expect(within(card).getByTestId("cpcv-nostatus")).toHaveTextContent(/不适用/);
    expect(within(card).queryByText("0.410")).toBeNull();   // 无假分布数字
  });

  it("**不假绿灯④**：dist 缺省/null → 不渲染（未算≠已算·不编造）", () => {
    const { container, rerender } = renderWithDesk(<CpcvRobustnessCard dist={null} />);
    expect(screen.queryByTestId("cpcv-card")).toBeNull();
    rerender(<CpcvRobustnessCard dist={undefined} />);
    expect(container.textContent).toBe("");
  });
});
