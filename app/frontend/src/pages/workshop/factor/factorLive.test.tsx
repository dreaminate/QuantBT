import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";
import { buildMockFactors } from "./factorData";
import { FactorEvalView } from "./FactorEvalView";
import { FactorCorrView } from "./FactorCorrView";
import { FactorResearchView, buildLiveChecks, type FactorAuditLive } from "./FactorResearchView";
import { FactorBuildView } from "./FactorBuildView";

const factors = buildMockFactors();
const sel = factors[0];

// F2 真实后端：注入 live props → 视图展示后端真数据 + LIVE 角标（不再 MOCK），不假绿灯。
describe("F2 视图真实后端 · live 注入覆盖 mock + 改挂 LIVE", () => {
  it("评测台：live IC/分层注入 → LIVE 角标 + NW t 卡 + 真实样本期", () => {
    renderWithDesk(
      <FactorEvalView
        factor={sel}
        horizon={5}
        onHorizon={() => {}}
        live={{
          ic: { ic_mean: 0.041, rank_ic_mean: 0.05, ic_ir: 0.9, ic_tstat_nw: 3.2, sample_count: 233 },
          decay: [
            { horizon: 1, ic_mean: 0.02, rank_ic_mean: 0.02, ic_ir: 0.5 },
            { horizon: 5, ic_mean: 0.041, rank_ic_mean: 0.05, ic_ir: 0.9 },
          ],
          layered: {
            effective_quantiles: 4,
            long_short_spread: 0.012,
            monotonic: true,
            buckets: [
              { quantile: 1, mean_return: -0.004, n_obs: 228 },
              { quantile: 2, mean_return: 0.001, n_obs: 228 },
              { quantile: 3, mean_return: 0.004, n_obs: 228 },
              { quantile: 4, mean_return: 0.008, n_obs: 228 },
            ],
          },
        }}
      />,
    );
    expect(screen.getByTestId("eval-live-badge")).toBeInTheDocument();
    // 真实后端：Newey-West t 卡出现（mock 路径是「胜率」）
    expect(screen.getByText("NW t")).toBeInTheDocument();
    // 真实样本期覆盖 mock 的 504
    expect(screen.getByText("233")).toBeInTheDocument();
    // 不再出现 MOCK 角标
    expect(screen.queryByText(/MOCK 数据 · 分层回测/)).toBeNull();
    expect(screen.getByText("后端 · IC / 分位均值 / 衰减")).toBeInTheDocument();
    expect(screen.getByTestId("layer-cumulative-unavailable")).toHaveTextContent(/累计净值序列不可用/);
    expect(screen.getByTestId("ic-series-unavailable")).toHaveTextContent(/后端仅返回汇总指标/);
  });

  it("评测台：后端 payload 部分缺失 → 缺失区块不可用，绝不回落 MOCK/504/0", () => {
    renderWithDesk(
      <FactorEvalView
        factor={sel}
        horizon={5}
        onHorizon={() => {}}
        live={{
          ic: { ic_mean: null, rank_ic_mean: null, ic_ir: null, ic_tstat_nw: null, sample_count: 0 },
          decay: null,
          layered: {
            effective_quantiles: 2,
            long_short_spread: 0.01,
            monotonic: false,
            buckets: [
              { quantile: 1, mean_return: -0.002, n_obs: 10 },
              { quantile: 2, mean_return: 0.008, n_obs: 10 },
            ],
          },
        }}
      />,
    );
    expect(screen.getByTestId("eval-partial-badge")).toHaveTextContent("后端数据不完整 · 不混入 MOCK");
    expect(screen.getAllByText("不可用").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByTestId("decay-unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/MOCK 数据 · 分层回测/)).toBeNull();
    expect(screen.queryByText("504")).toBeNull();
  });

  it("评测台：无 live → 回落 mock + MockBadge（诚实，不假绿灯）", () => {
    renderWithDesk(<FactorEvalView factor={sel} horizon={5} onHorizon={() => {}} live={null} />);
    expect(screen.queryByTestId("eval-live-badge")).toBeNull();
    expect(screen.getByText(/MOCK 数据 · 分层回测/)).toBeInTheDocument();
  });

  it("相关性：live 矩阵注入 → LIVE 角标 + 期数", () => {
    const ids = factors.slice(0, 3).map((f) => f.id);
    renderWithDesk(
      <FactorCorrView
        factors={factors}
        market="equity_cn"
        pair={null}
        onPair={() => {}}
        live={{
          factor_ids: ids,
          matrix: [
            [1, 0.85, 0.1],
            [0.85, 1, 0.2],
            [0.1, 0.2, 1],
          ],
          redundant_pairs: [{ a: ids[0], b: ids[1], spearman: 0.85 }],
          threshold: 0.8,
          sample_count: 233,
        }}
      />,
    );
    expect(screen.getByTestId("corr-live-badge")).toBeInTheDocument();
    expect(screen.queryByText(/MOCK 数据 · 相关矩阵/)).toBeNull();
  });

  it("研究台：live audit 注入 → LIVE 角标 + 后端裁决文案（concern→证据存疑）", () => {
    const audit: FactorAuditLive = {
      verdict: "concern",
      verdict_note: "存疑：['n_eff'] 未能复算（未验证不当 pass）",
      disclosure: "档位=standard；诚实-N 试验数 N=4。",
      tier: "standard",
      dsr: 0.62,
      sharpe: 0.4,
      n_trials: 4,
      pbo: { pbo: 0.31 },
      n_eff: { point: 4, low: 4, high: 4 },
      bootstrap_ci: { lower: -0.5, upper: 1.2, estimate: 0.4 },
      ic: { ic_tstat_nw: 2.1, nw_lag: 4 },
      checks: [
        { key: "dsr", value: 0.62, threshold: 0.9, passed: false, severe: true, direction: ">=" },
        { key: "n_eff", value: 4, threshold: 3, passed: true, severe: false, direction: ">=" },
      ],
    };
    renderWithDesk(
      <FactorResearchView factor={sel} chat={[]} draft="" onDraft={() => {}} onSend={() => {}} live={audit} />,
    );
    expect(screen.getByTestId("audit-live-badge")).toBeInTheDocument();
    // 后端 verdict 映射成展示裁决（不假绿灯：concern=证据存疑）
    expect(screen.getByText("证据存疑")).toBeInTheDocument();
    expect(screen.queryByText(/MOCK 数据 · 审查报告/)).toBeNull();
  });

  it("buildLiveChecks：未达标项 weak=true、严重→✕、达标→✓（R25 不染绿）", () => {
    const checks = buildLiveChecks({
      verdict: "blocked",
      verdict_note: "",
      disclosure: "",
      tier: "standard",
      dsr: 0,
      sharpe: 0,
      n_trials: 1,
      pbo: { pbo: 0.9 },
      n_eff: { point: 1, low: 1, high: 1 },
      bootstrap_ci: { lower: 0, upper: 0, estimate: 0 },
      ic: { ic_tstat_nw: null, nw_lag: 4 },
      checks: [
        { key: "dsr", value: null, threshold: 0.9, passed: false, severe: true, direction: ">=" },
        { key: "n_eff", value: 5, threshold: 3, passed: true, severe: false, direction: ">=" },
      ],
    });
    const dsr = checks.find((c) => c.title.startsWith("Deflated"))!;
    expect(dsr.weak).toBe(true);
    expect(dsr.icon).toBe("✕");
    expect(dsr.detail).toContain("缺失");
    const neff = checks.find((c) => c.title.startsWith("有效独立"))!;
    expect(neff.weak).toBe(false);
    expect(neff.icon).toBe("✓");
  });

  it("构建台：live 前视未过 → 校验红字 + 非 LIVE-成功角标（绝不假绿灯）", () => {
    renderWithDesk(
      <FactorBuildView
        expr="ts_lag(close, -1)"
        factorId="x"
        chat={[]}
        draft=""
        onDraft={() => {}}
        onSend={() => {}}
        onInsert={() => {}}
        onChip={() => {}}
        gateOpen={false}
        onGate={() => {}}
        onGateClose={() => {}}
        onGateConfirm={() => {}}
        live={{ valid: false, stage: "lookahead", reason: "前视门：引入未来函数", ic: null }}
      />,
    );
    expect(screen.getByText(/前视门未通过/)).toBeInTheDocument();
    expect(screen.getByText(/后端校验未过 · lookahead/)).toBeInTheDocument();
    expect(screen.getAllByText("不可用")).toHaveLength(2);
    expect(screen.getByText(/DEMO 合成波形 · 不代表后端 IC 序列/)).toBeInTheDocument();
  });

  it("构建台：live 校验通过 → LIVE 即时 IC 角标 + 真实 IC", () => {
    renderWithDesk(
      <FactorBuildView
        expr="ts_zscore(close, 20)"
        factorId="x"
        chat={[]}
        draft=""
        onDraft={() => {}}
        onSend={() => {}}
        onInsert={() => {}}
        onChip={() => {}}
        gateOpen={false}
        onGate={() => {}}
        onGateClose={() => {}}
        onGateConfirm={() => {}}
        live={{ valid: true, stage: "ok", reason: "前视门通过", ic: { ic_mean: 0.037, ic_ir: 0.82, ic_tstat_nw: 2.5 } }}
      />,
    );
    expect(screen.getByTestId("build-live-badge")).toBeInTheDocument();
    expect(screen.getByTestId("build-live-badge")).toHaveTextContent("后端校验 · 汇总 IC");
    expect(screen.getByText("0.037")).toBeInTheDocument();
  });

  it("构建台：后端校验通过但未返回 IC → 汇总值不可用，不以 DEMO 数值补洞", () => {
    renderWithDesk(
      <FactorBuildView
        expr="ts_zscore(close, 20)"
        factorId="x"
        chat={[]}
        draft=""
        onDraft={() => {}}
        onSend={() => {}}
        onInsert={() => {}}
        onChip={() => {}}
        gateOpen={false}
        onGate={() => {}}
        onGateClose={() => {}}
        onGateConfirm={() => {}}
        live={{ valid: true, stage: "ok", reason: "前视门通过", ic: null }}
      />,
    );
    expect(screen.getAllByText("不可用")).toHaveLength(2);
    expect(screen.getByText(/DEMO 合成波形 · 不代表后端 IC 序列/)).toBeInTheDocument();
    expect(screen.queryByText(/DEMO IC/)).toBeNull();
  });
});
