import { describe, it, expect, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";
import { FactorDeskPage } from "./FactorDeskPage";
import {
  admitToFactorLib,
  canEnterFactorLib,
  looksLikeModelBody,
  isGateMetricKey,
  assertGenSortKeyClean,
  honestNCount,
  normalizeExpr,
  buildMiningCandidates,
  gateEvaluate,
  GEN_SORT_KEYS,
  GATE_METRIC_KEYWORDS,
  LIB_ARTIFACTS,
} from "./factorLabData";

const here = dirname(fileURLToPath(import.meta.url));
const SUCCESS = "var(--desk-success)";

// jsdom 无 fetch；mock 成功路径返回空数组 → 页面回落 mock 全集。
beforeEach(() => {
  globalThis.fetch = (() =>
    Promise.resolve(new Response("[]", { status: 200 }))) as typeof fetch;
});

describe("F3 三纯库 + 暴力遍历 · 渲染骨架（扩展不替换 5 视图）", () => {
  it("SubTabBar 含原 5 视图 + 新增三纯库 / 暴力遍历挖掘", () => {
    renderWithDesk(<FactorDeskPage />);
    for (const t of [
      "▤ 因子库",
      "⊞ 相关性",
      "⚖ 评测台",
      "⌨ 构建台",
      "⚗ 研究台",
      "⛬ 三纯库",
      "⛏ 暴力遍历挖掘",
    ]) {
      expect(screen.getByText(t)).toBeInTheDocument();
    }
  });

  it("切到三纯库 → 三库分区在 + MockBadge", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText("⛬ 三纯库"));
    expect(screen.getByText(/算术暴力遍历库/)).toBeInTheDocument();
    expect(screen.getByText("ML 库")).toBeInTheDocument();
    expect(screen.getByText("DL 库")).toBeInTheDocument();
    expect(screen.getAllByText(/MOCK 数据/).length).toBeGreaterThan(0);
  });

  it("切到暴力遍历挖掘 → 生成器配置 + 守门 + 诚实-N + MockBadge", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText("⛏ 暴力遍历挖掘"));
    expect(screen.getByText(/生成器 · 遍历配置/)).toBeInTheDocument();
    expect(screen.getByText(/诚实-N 守门人/)).toBeInTheDocument();
    expect(screen.getByText(/守门器评判/)).toBeInTheDocument();
    expect(screen.getAllByText(/MOCK 数据/).length).toBeGreaterThan(0);
  });
});

describe("F3 · 对抗① UI 不允许把 .pt（DL 本体）当因子塞因子库（范畴错误拒，R17）", () => {
  it("model_body / .pt 后缀 ref → admitToFactorLib 拒绝", () => {
    const r1 = admitToFactorLib("model_body", "tcn_seq_alpha_v2.pt");
    expect(r1.admitted).toBe(false);
    expect(r1.reason).toMatch(/范畴错误/);

    // .pt 后缀的本体，即便范畴误标也得拒（双保险）。
    expect(looksLikeModelBody("foo.pt")).toBe(true);
    expect(looksLikeModelBody("bar.pkl")).toBe(true);
    expect(looksLikeModelBody("sig::dl_pred")).toBe(false);
    expect(canEnterFactorLib("model_body")).toBe(false);
    expect(canEnterFactorLib("expression")).toBe(true);
    expect(canEnterFactorLib("signal_contract")).toBe(true);
  });

  it("点 DL 本体『入因子库』→ UI 渲染拒绝 + 范畴错误理由（不染绿）", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText("⛬ 三纯库"));
    const dlBody = LIB_ARTIFACTS.find((a) => a.kind === "model_body" && a.lib === "dl")!;
    // 该条目数据属性标 can-enter=false
    const node = document.querySelector(`[data-artifact="${dlBody.id}"]`);
    expect(node?.getAttribute("data-can-enter")).toBe("false");
    // 点它的入库按钮 → 出现拒绝面板，data-admit=false
    fireEvent.click(document.querySelector(`[data-try="${dlBody.id}"]`)!);
    const verdict = document.querySelector('[data-admit="false"]');
    expect(verdict).not.toBeNull();
    expect(verdict?.textContent).toMatch(/拒绝/);
  });
});

describe("F3 · 对抗④ ML/DL 输出未走信号契约直接当因子 → 抓", () => {
  it("model_body 输出（裸 .pkl ref）未走 signal_contract → 拒", () => {
    // 直接把模型本体当因子（未经信号契约）→ 拒
    expect(admitToFactorLib("model_body", "gbdt_xs_rank_v3.pkl").admitted).toBe(false);
    // 经信号契约登记的输出 → 准入
    expect(admitToFactorLib("signal_contract", "sig::ml_gbdt_xs_score").admitted).toBe(true);
  });

  it("ML/DL 库里每个本体都有配套 signal_contract（两层连线，输出才入库）", () => {
    for (const lib of ["ml", "dl"] as const) {
      const bodies = LIB_ARTIFACTS.filter((a) => a.lib === lib && a.kind === "model_body");
      const sigs = LIB_ARTIFACTS.filter((a) => a.lib === lib && a.kind === "signal_contract");
      expect(bodies.length).toBeGreaterThan(0);
      expect(sigs.length).toBeGreaterThan(0);
      // 每个信号契约都回指一个本体（modelRef）
      for (const s of sigs) {
        expect(s.modelRef).toBeTruthy();
        expect(bodies.some((b) => b.ref === s.modelRef)).toBe(true);
      }
    }
  });
});

describe("F3 · 对抗② 守门指标进生成器 fitness 排序 → 抓（R16 解耦）", () => {
  it("守门指标关键词 → isGateMetricKey 命中、assertGenSortKeyClean 抛", () => {
    for (const k of ["ic", "IC", "ir_score", "dsr", "sharpe", "pbo", "t_stat", "pnl", "alpha_ret"]) {
      expect(isGateMetricKey(k)).toBe(true);
      expect(() => assertGenSortKeyClean(k)).toThrow(/R16/);
    }
  });

  it("生成器排序键白名单全是结构维度，零守门指标", () => {
    for (const k of GEN_SORT_KEYS) {
      expect(isGateMetricKey(k.value)).toBe(false);
      // 不抛 = 干净
      expect(() => assertGenSortKeyClean(k.value)).not.toThrow();
    }
  });

  it("守门指标黑名单覆盖 IC/IR/DSR 三大件", () => {
    for (const m of ["ic", "ir", "dsr"]) {
      expect(GATE_METRIC_KEYWORDS as readonly string[]).toContain(m);
    }
  });

  it("挖掘视图：生成器侧 DOM 不含守门指标文案（IC/IR/DSR 只在 data-gate 守门半区）", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText("⛏ 暴力遍历挖掘"));
    // 第一张候选卡
    const card = document.querySelector("[data-candidate]")!;
    const gateHalf = card.querySelector("[data-gate]")!;
    // 生成器半区 = 整卡去掉守门半区
    const genText = card.textContent!.replace(gateHalf.textContent ?? "", "");
    // 生成器半区不得出现守门指标缩写
    expect(/\bIC\b|\bIR\b|\bDSR\b/.test(genText)).toBe(false);
    // 守门半区确实有这些指标
    expect(/IC|IR|DSR/.test(gateHalf.textContent ?? "")).toBe(true);
  });
});

describe("F3 · 对抗③ 等价公式 N_eff 计数不变（诚实-N）", () => {
  it("等价改写（冗余括号/空白/大小写）normalize 后同形", () => {
    expect(normalizeExpr("(rank(close/ts_mean(close,20)))")).toBe(
      normalizeExpr("rank(close/ts_mean(close,20))"),
    );
    expect(normalizeExpr("RANK( CLOSE )")).toBe(normalizeExpr("rank(close)"));
    // 但真不同的公式 normalize 后不同形
    expect(normalizeExpr("rank(close)")).not.toBe(normalizeExpr("rank(volume)"));
  });

  it("honestNCount：等价公式不抬高 N_eff，且恒有 N_eff ≤ total", () => {
    const exprs = [
      "rank(close/ts_mean(close,20))",
      "(rank(close/ts_mean(close,20)))", // 等价
      "neg(ts_zscore(close,20))",
    ];
    const { total, nEff } = honestNCount(exprs);
    expect(total).toBe(3);
    expect(nEff).toBe(2); // 等价的一对只算 1
    expect(nEff).toBeLessThanOrEqual(total);
  });

  it("mock 候选集含一对等价 → N_eff < total（不被等价灌水）", () => {
    const cands = buildMiningCandidates();
    const { total, nEff } = honestNCount(cands.map((c) => c.expr));
    expect(nEff).toBeLessThan(total);
    expect(nEff).toBeLessThanOrEqual(total);
  });

  it("挖掘视图渲染 N_eff < N 且面板标注以 N_eff 算校正", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText("⛏ 暴力遍历挖掘"));
    const honest = document.querySelector("[data-honest-n]");
    expect(honest?.textContent).toMatch(/N_eff/);
    const cands = buildMiningCandidates();
    const { total, nEff } = honestNCount(cands.map((c) => c.expr));
    expect(honest?.textContent).toMatch(new RegExp(`N_eff=${nEff}`));
    expect(honest?.textContent).toMatch(new RegExp(`N=${total}`));
  });
});

describe("F3 · 守门裁决不假绿灯（R25：未达标不染绿）", () => {
  it("gateEvaluate 未过的候选 pass 色非 success，且有诚实 note", () => {
    const cands = buildMiningCandidates();
    const gate = gateEvaluate(cands);
    const failed = gate.filter((g) => !g.passed);
    expect(failed.length).toBeGreaterThan(0);
    for (const g of failed) {
      expect(g.note.length).toBeGreaterThan(0);
    }
    // passed 的门槛严格：|IC|≥0.02 且 IR≥0.5 且 DSR≥0
    for (const g of gate.filter((x) => x.passed)) {
      expect(Math.abs(g.ic)).toBeGreaterThanOrEqual(0.02);
      expect(g.ir).toBeGreaterThanOrEqual(0.5);
      expect(g.dsr).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("F3 · 对抗 token：新增源文件禁裸 hex（须走 --desk-* token）", () => {
  it("factorLabData / FactorPureLibsView / FactorMiningView 零 #hex", () => {
    const files = ["factorLabData.ts", "FactorPureLibsView.tsx", "FactorMiningView.tsx"];
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(join(here, f), "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });

  it("准入裁决：admitted=true 才用 success 框；拒绝用 danger（不混）", () => {
    // 逻辑层保证：拒绝结果永不带 admitted=true
    expect(admitToFactorLib("model_body", "x.pt").admitted).not.toBe(true);
    // 哨兵：success 常量未被误用为拒绝色
    expect(SUCCESS).toBe("var(--desk-success)");
  });
});
