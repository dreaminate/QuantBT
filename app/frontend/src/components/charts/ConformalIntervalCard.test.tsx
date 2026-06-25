import { describe, it, expect } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithDesk } from "../../test/harness";
import {
  ConformalIntervalCard,
  type ConformalIntervalData,
} from "./ConformalIntervalCard";

const OK: ConformalIntervalData = {
  alpha: 0.1,
  target_coverage: 0.9,
  n_calib: 200,
  n_test: 200,
  abstained: false,
  band_half_width: 1.96,
  empirical_coverage: 0.885, // 略低于目标 0.9（单次带噪）——必须诚实显示、绝不渲成达标绿
  n_test_dropped_nonfinite: 0,
  note: "split-conformal 带 ±1.96（目标 90% 覆盖）；留出实测覆盖 88.5%（n_test=200）。单次覆盖含二项抽样噪声、跨多次训练取均值方判校准；覆盖保证依赖可交换，时序非平稳可能偏离。",
};

const ABSTAINED: ConformalIntervalData = {
  alpha: 0.1,
  target_coverage: 0.9,
  n_calib: 6,
  n_test: 6,
  abstained: true,
  band_half_width: null,
  empirical_coverage: null,
  note: "OOS 校准集不足（n_calib=6）：证据不足、不给校准区间。",
};

describe("R23 ConformalIntervalCard · OOS 留出覆盖披露（不假绿灯）", () => {
  it("正常：渲染半宽/目标/留出实测覆盖 + 后端 note 单一源", () => {
    renderWithDesk(<ConformalIntervalCard interval={OK} />);
    expect(screen.getByTestId("conformal-interval-card")).toBeInTheDocument();
    expect(screen.getByText("±1.96")).toBeInTheDocument();
    expect(screen.getByText("90.0%")).toBeInTheDocument(); // 目标覆盖
    expect(screen.getByText("88.5%")).toBeInTheDocument(); // 留出实测（诚实显示低于目标）
    expect(screen.getByTestId("conformal-note")).toHaveTextContent(/跨多次训练取均值方判校准/);
  });

  it("**不假绿灯①**：单次留出覆盖率中性色，绝不上成功绿当『达标』", () => {
    renderWithDesk(<ConformalIntervalCard interval={OK} />);
    const cov = screen.getByText("88.5%");
    expect(cov).toHaveStyle({ color: "var(--cc-text-soft, #a0a0a0)" });
    expect(cov).not.toHaveStyle({ color: "var(--cc-success)" }); // 种坏：单次覆盖渲成绿=假绿灯
  });

  it("**不假绿灯②**：abstained → 『证据不足』警示色，绝不渲染假区间/假覆盖", () => {
    renderWithDesk(<ConformalIntervalCard interval={ABSTAINED} />);
    const ab = screen.getByTestId("conformal-abstained");
    expect(ab).toHaveTextContent(/证据不足/);
    expect(ab).toHaveStyle({ color: "var(--cc-warning, #d68910)" });
    // 绝不出现假区间/假覆盖数字（band/coverage 为 null 时不渲染数值）。
    expect(screen.queryByText(/±/)).toBeNull();
    expect(screen.queryByText(/%$/)).toBeNull();
    // note（证据不足说明）仍原样渲染。
    expect(screen.getByTestId("conformal-note")).toHaveTextContent(/证据不足/);
  });

  it("**不假绿灯③**：interval 缺省/null → 不渲染（不编造校准结论）", () => {
    const { container, rerender } = renderWithDesk(
      <ConformalIntervalCard interval={null} />,
    );
    expect(screen.queryByTestId("conformal-interval-card")).toBeNull();
    rerender(<ConformalIntervalCard interval={undefined} />);
    expect(screen.queryByTestId("conformal-interval-card")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("band_half_width=null 但未 abstain（理论边角）→ 半宽显 N/A，不崩不造假", () => {
    renderWithDesk(
      <ConformalIntervalCard
        interval={{ ...OK, band_half_width: null, empirical_coverage: null }}
      />,
    );
    const card = screen.getByTestId("conformal-interval-card");
    expect(within(card).getAllByText("N/A").length).toBeGreaterThanOrEqual(1);
  });
});
