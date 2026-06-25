import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, within } from "@testing-library/react";
import {
  renderWithDesk,
  assertNoForbiddenWords,
  assertNoFrozenPageImport,
  scanForbiddenWords,
} from "../test/harness";
import {
  FactorAttributionCard,
  MOCK_FACTOR_ATTRIBUTION,
  MOCK_FACTOR_ATTRIBUTION_INSUFFICIENT,
  MOCK_FACTOR_ATTRIBUTION_SPECIFIC,
  type FactorAttributionReport,
  type EvidenceState,
} from "./FactorAttributionCard";

const here = dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(join(here, "FactorAttributionCard.tsx"), "utf8");

function makeReport(
  over: Partial<FactorAttributionReport> = {},
): FactorAttributionReport {
  return { ...MOCK_FACTOR_ATTRIBUTION, ...over };
}

const collinearReport = makeReport({
  status: "collinear",
  evidence_state: "collinear",
  factor_contributions: {},
  betas: {},
  alpha: null,
  r_squared: null,
  specific_contribution: 0.02,
  total_return: 0.02,
  identity: { recomposed: 0.02, residual: 0, holds: true },
  note: "因子共线 / 设计阵秩亏：β 不可识别，未给出因子 β —— 证据不足（请检查所选因子集是否重复 / 线性相关）。",
});

const ALL_STATES: { name: EvidenceState; report: FactorAttributionReport }[] = [
  { name: "factor_explained", report: MOCK_FACTOR_ATTRIBUTION },
  { name: "specific_driven", report: MOCK_FACTOR_ATTRIBUTION_SPECIFIC },
  { name: "insufficient", report: MOCK_FACTOR_ATTRIBUTION_INSUFFICIENT },
  { name: "collinear", report: collinearReport },
];

describe("FactorAttributionCard · ok 态渲染（贡献分解 + R² + 特异）", () => {
  it("factor_explained：贡献行 + R² + 特异 + 恒等式 footer 齐备", () => {
    renderWithDesk(<FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION} />);
    expect(screen.getByTestId("factor-attribution-card")).toBeInTheDocument();
    // 三因子各一行贡献条 + 特异行。
    expect(screen.getAllByTestId("contrib-row").length).toBe(3);
    expect(screen.getAllByTestId("contrib-bar").length).toBe(3);
    expect(screen.getByTestId("specific-row")).toBeInTheDocument();
    expect(screen.getByTestId("r2-value")).toHaveTextContent("71.0%");
    expect(screen.getByTestId("identity-footer")).toBeInTheDocument();
    // β 标注出现（已识别）。
    expect(screen.getByText(/β=0.83/)).toBeInTheDocument();
  });

  it("mock 角标诚实：dataSource 缺省挂 MOCK；live 不挂", () => {
    const { rerender } = renderWithDesk(
      <FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION} />,
    );
    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
    rerender(
      <FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION} dataSource="live" />,
    );
    expect(screen.queryByText("MOCK 数据")).toBeNull();
  });
});

describe("FactorAttributionCard · 不假绿灯①：abstain 不出 β、不上绿（核心 MUT）", () => {
  it("insufficient：渲染证据不足面板 + 原样 note，**绝不**渲染贡献条 / β", () => {
    renderWithDesk(
      <FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION_INSUFFICIENT} />,
    );
    // abstain 面板在，且无任何贡献条 / 贡献行（后端 betas 已空，前端不二次编造 β）。
    expect(screen.getByTestId("abstain-panel")).toBeInTheDocument();
    expect(screen.queryAllByTestId("contrib-bar").length).toBe(0);
    expect(screen.queryAllByTestId("contrib-row").length).toBe(0);
    expect(screen.queryByTestId("specific-row")).toBeNull();
    expect(screen.getByText("未给出因子 β —— 证据不足")).toBeInTheDocument();
    // 种坏门必抓：evidence pill 警示色，**绝不**成功绿。
    const pill = screen.getByTestId("evidence-pill");
    expect(pill).toHaveStyle({ color: "var(--desk-warning)" });
    expect(pill).not.toHaveStyle({ color: "var(--desk-success)" });
  });

  it("collinear：同 abstain 处置（证据不足面板、无 β 条、非绿）", () => {
    renderWithDesk(<FactorAttributionCard report={collinearReport} />);
    expect(screen.getByTestId("abstain-panel")).toBeInTheDocument();
    expect(screen.queryAllByTestId("contrib-bar").length).toBe(0);
    const pill = screen.getByTestId("evidence-pill");
    expect(pill).not.toHaveStyle({ color: "var(--desk-success)" });
  });
});

describe("FactorAttributionCard · 不假绿灯②：低 R² 不标已归因", () => {
  it("specific_driven：R² 显示 + 「归因弱·特异驱动」警示，evidence ≠ factor_explained、非绿", () => {
    renderWithDesk(
      <FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION_SPECIFIC} />,
    );
    expect(screen.getByTestId("r2-value")).toHaveTextContent("6.0%");
    // R² 弱标注在（不掩盖弱点）。
    expect(screen.getByTestId("r2-weak-note")).toHaveTextContent("归因弱");
    const pill = screen.getByTestId("evidence-pill");
    // 种坏门必抓：低 R² 渲成 factor_explained / 成功绿 → 立红。
    expect(pill).toHaveTextContent("特异驱动");
    expect(pill).not.toHaveTextContent("因子可解释");
    expect(pill).toHaveStyle({ color: "var(--desk-warning)" });
    expect(pill).not.toHaveStyle({ color: "var(--desk-success)" });
    // R² 数值本身也走警示色、绝不成功绿。
    expect(screen.getByTestId("r2-value")).not.toHaveStyle({
      color: "var(--desk-success)",
    });
  });

  it("factor_explained 也只落中性 text-soft、**非成功绿**（解释占比≠策略质量）", () => {
    renderWithDesk(<FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION} />);
    const pill = screen.getByTestId("evidence-pill");
    expect(pill).toHaveTextContent("因子可解释");
    expect(pill).toHaveStyle({ color: "var(--desk-text-soft)" });
    expect(pill).not.toHaveStyle({ color: "var(--desk-success)" });
  });
});

describe("FactorAttributionCard · 不假绿灯③：anti-green 全态扫荡", () => {
  it("四态 evidence pill 无一处 var(--desk-success)（本卡绝不上成功绿）", () => {
    for (const { report } of ALL_STATES) {
      const { unmount } = renderWithDesk(
        <FactorAttributionCard report={report} />,
      );
      expect(screen.getByTestId("evidence-pill")).not.toHaveStyle({
        color: "var(--desk-success)",
      });
      unmount();
    }
  });

  it("源码无 --desk-success token（结构性杜绝假绿灯）", () => {
    expect(SOURCE.includes("--desk-success")).toBe(false);
  });
});

describe("FactorAttributionCard · 加总恒等式 footer（命门可见）", () => {
  it("holds=true → ✓ 闭合（中性陈述）；holds=false → ✗ 破（danger）", () => {
    const { rerender } = renderWithDesk(
      <FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION} />,
    );
    expect(screen.getByTestId("identity-flag")).toHaveTextContent("闭合");
    expect(screen.getByTestId("identity-flag")).not.toHaveStyle({
      color: "var(--desk-success)",
    });
    rerender(
      <FactorAttributionCard
        report={makeReport({
          identity: { recomposed: 0.2, residual: 0.09, holds: false },
        })}
      />,
    );
    const flag = screen.getByTestId("identity-flag");
    expect(flag).toHaveTextContent("破");
    expect(flag).toHaveStyle({ color: "var(--desk-danger)" });
  });
});

describe("FactorAttributionCard · note 单一源（原样渲染·不前端杜撰）", () => {
  it("note 由后端 report 供给、原样出现在卡内（前端不二次拼措辞）", () => {
    const custom = "因子解释占比 55.0%：各因子贡献见分解，剩余归特异部分。适用域取决于所选因子集与收益口径（用户方法学）；解释占比为因子模型拟合度。";
    renderWithDesk(
      <FactorAttributionCard report={makeReport({ note: custom })} />,
    );
    expect(screen.getByTestId("attribution-note")).toHaveTextContent(custom);
  });

  it("方法学口径原样回显（用户不替拍）：因子集 / 收益口径 / 回归窗", () => {
    renderWithDesk(<FactorAttributionCard report={MOCK_FACTOR_ATTRIBUTION} />);
    // 因子集在 header 标题 + 方法学回显行各一次（原样透传用户口径）。
    expect(screen.getAllByText(/风格三因子/).length).toBeGreaterThanOrEqual(2);
    // 收益口径 / 回归窗仅出现在方法学回显行（唯一）→ 证明回显行真渲染。
    expect(screen.getByText(/超额收益/)).toBeInTheDocument();
    expect(screen.getByText(/全样本/)).toBeInTheDocument();
  });
});

describe("FactorAttributionCard · 对抗测试：R7 措辞门（无禁词）", () => {
  it("四态全渲染文本均无『可信/安全/保证/排除过拟合/可复现/组织独立』", () => {
    for (const { report } of ALL_STATES) {
      const { container, unmount } = renderWithDesk(
        <FactorAttributionCard report={report} />,
      );
      expect(() =>
        assertNoForbiddenWords(container.textContent ?? ""),
      ).not.toThrow();
      unmount();
    }
  });

  it("种坏门必抓：若 note 含『排除过拟合/可信』，扫描器命中", () => {
    expect(
      scanForbiddenWords("R²71% 排除过拟合，因子归因可信"),
    ).toEqual(["可信", "排除过拟合"]);
  });

  it("三态 mock note 均无禁词（后端单一源已守，前端原样渲染才安全）", () => {
    expect(scanForbiddenWords(MOCK_FACTOR_ATTRIBUTION.note)).toEqual([]);
    expect(scanForbiddenWords(MOCK_FACTOR_ATTRIBUTION_SPECIFIC.note)).toEqual([]);
    expect(
      scanForbiddenWords(MOCK_FACTOR_ATTRIBUTION_INSUFFICIENT.note),
    ).toEqual([]);
  });
});

describe("FactorAttributionCard · 对抗测试：不嵌冻结页 + 零裸 hex", () => {
  it("源码不含 frontend-run-detail 冻结 RunDetailPage 的 import", () => {
    expect(() => assertNoFrozenPageImport(SOURCE)).not.toThrow();
    // 种坏门必抓：若真引用冻结页，守卫会抛。
    expect(() =>
      assertNoFrozenPageImport(
        SOURCE +
          '\nimport { RunDetailPage } from "../../frontend-run-detail/src/pages/RunDetailPage";',
      ),
    ).toThrow(/冻结红线/);
  });

  it("源码字面不出现 frontend-run-detail 路径", () => {
    expect(SOURCE.includes("frontend-run-detail")).toBe(false);
  });

  it("源码无裸 hex 色值（一律 var(--desk-*)）", () => {
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    expect(SOURCE.match(HEX)).toBeNull();
  });
});
