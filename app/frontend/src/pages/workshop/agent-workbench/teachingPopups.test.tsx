import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent } from "@testing-library/react";
import {
  renderWithDesk,
  assertNoForbiddenWords,
  FORBIDDEN_VERDICT_WORDS,
} from "../../../test/harness";
import {
  FalsifiabilityGuide,
  ProvenanceAck,
  RedVerdictAck,
} from "./TeachingPopups";
import { AgentWorkbenchPage } from "./AgentWorkbenchPage";
import {
  MOCK_FALSIFIABILITY_GUIDE,
  MOCK_PROVENANCE_ACK,
  MOCK_RED_VERDICT,
} from "./agentMock";

const here = dirname(fileURLToPath(import.meta.url));

/** 三型弹窗的通用 noop props 工厂（按需覆盖回调）。 */
function falsProps(over: Partial<Parameters<typeof FalsifiabilityGuide>[0]> = {}) {
  return {
    tool: "backtest.run（confirmatory）",
    confidence: "low" as const,
    flags: ["缺可观测前置条件 X", "缺可观测阈值或方向"],
    cardMissing: false,
    onAcknowledge: () => {},
    onFillCard: () => {},
    onCancel: () => {},
    ...over,
  };
}
function provProps(over: Partial<Parameters<typeof ProvenanceAck>[0]> = {}) {
  return {
    destination: "paper_desk",
    unverified: [
      { id: "mom_resid_20d", stage: "未独立验证" },
      { id: "liq_amihud_z", stage: "假设卡未冻结" },
    ],
    onAcknowledge: () => {},
    onGoFactorDesk: () => {},
    onCancel: () => {},
    ...over,
  };
}
function redProps(over: Partial<Parameters<typeof RedVerdictAck>[0]> = {}) {
  return {
    subject: "run_wk_cn_8f2a",
    verdictNote: "证据不一致：样本外方向背离，适用域仅训练区间，未验证项 3。",
    weaknesses: ["walk-forward 末两窗超额转负", "成本敏感性收窄至接近 0"],
    onAcknowledge: () => {},
    onViewEvidence: () => {},
    onCancel: () => {},
    ...over,
  };
}

// ── ① 可证伪 409 引导（D-T024-FALS：硬透明 + 软决定） ────────────────────
describe("① 可证伪引导弹窗（D-T024-FALS · 硬透明 + 软决定）", () => {
  it("渲染：confidence 真值（来自后端）+ flags 逐条 + 引导填假设卡", () => {
    renderWithDesk(<FalsifiabilityGuide {...falsProps()} />);
    expect(screen.getByTestId("falsifiability-guide")).toBeInTheDocument();
    expect(screen.getByText(/confidence: low/)).toBeInTheDocument();
    const flags = screen.getByTestId("falsifiability-flags");
    expect(flags.querySelectorAll("li").length).toBe(2);
    expect(screen.getByTestId("falsifiability-fill")).toBeInTheDocument();
  });

  it("软决定（非死挡）：知情确认按钮恒可点 → 触发 onAcknowledge", () => {
    let acked = false;
    renderWithDesk(
      <FalsifiabilityGuide {...falsProps({ onAcknowledge: () => (acked = true) })} />,
    );
    const ack = screen.getByTestId("falsifiability-ack") as HTMLButtonElement;
    expect(ack.disabled).toBe(false);
    fireEvent.click(ack);
    expect(acked).toBe(true);
  });

  it("对抗：种「可证伪 low 把回测死挡（唯一出口禁用/无确认路径）」必抓", () => {
    let acked = false;
    renderWithDesk(
      <FalsifiabilityGuide
        {...falsProps({ confidence: "low", onAcknowledge: () => (acked = true) })}
      />,
    );
    // D-T024-FALS：启发式绝不自动硬挡晋级——确认仍要跑的出口必须存在且可点。
    const ack = screen.queryByTestId("falsifiability-ack") as HTMLButtonElement;
    expect(ack).not.toBeNull();
    expect(ack.disabled).toBe(false);
    fireEvent.click(ack);
    expect(acked).toBe(true);
  });
});

// ── ② 血统警告知情确认（D-PROVENANCE） ─────────────────────────────────
describe("② 血统警告弹窗（D-PROVENANCE · 警告 + 知情确认非死挡）", () => {
  it("渲染：列出未过治理流程的因子 + 各自卡在哪一步", () => {
    renderWithDesk(<ProvenanceAck {...provProps()} />);
    expect(screen.getByTestId("provenance-ack")).toBeInTheDocument();
    const items = screen.getAllByTestId("provenance-item");
    expect(items.length).toBe(2);
    expect(screen.getByText("mom_resid_20d")).toBeInTheDocument();
    expect(screen.getByText("未独立验证")).toBeInTheDocument();
  });

  it("软决定（非死挡）：知情确认留痕后可继续 → onAcknowledge 触发", () => {
    let acked = false;
    renderWithDesk(
      <ProvenanceAck {...provProps({ onAcknowledge: () => (acked = true) })} />,
    );
    const ack = screen.getByTestId("provenance-ack-btn") as HTMLButtonElement;
    expect(ack.disabled).toBe(false);
    fireEvent.click(ack);
    expect(acked).toBe(true);
  });

  it("文案不导向实盘直推（D-PERM：默认止于模拟盘）", () => {
    const { container } = renderWithDesk(<ProvenanceAck {...provProps()} />);
    const text = container.textContent ?? "";
    for (const banned of ["立即买入", "直接下单", "真实下单", "实盘直推"]) {
      expect(text).not.toContain(banned);
    }
  });
});

// ── ③ red 裁决知情确认（R25 一等呈现 + R7 措辞） ───────────────────────
describe("③ red 裁决弹窗（R25 一等呈现 + R7 措辞 + 软决定）", () => {
  it("渲染：red pill + 后端 verdictNote 原样 + 弱点逐条", () => {
    renderWithDesk(<RedVerdictAck {...redProps()} />);
    expect(screen.getByTestId("red-verdict-ack")).toBeInTheDocument();
    expect(screen.getByText("red")).toBeInTheDocument();
    expect(screen.getByTestId("red-verdict-note")).toHaveTextContent(
      /证据不一致/,
    );
    expect(screen.getAllByTestId("red-verdict-weakness").length).toBe(2);
  });

  it("软决定：知情确认按钮可点 → onAcknowledge", () => {
    let acked = false;
    renderWithDesk(
      <RedVerdictAck {...redProps({ onAcknowledge: () => (acked = true) })} />,
    );
    fireEvent.click(screen.getByTestId("red-verdict-ack-btn"));
    expect(acked).toBe(true);
  });
});

// ── 治理硬约束（对抗：弱点折叠必抓 / 禁词必抓） ────────────────────────
describe("治理硬约束 · R25 弱点常驻展开不可折叠（对抗：折叠必抓）", () => {
  it("三型弹窗皆 data-weakness-expanded=true 且无折叠控件", () => {
    for (const ui of [
      <FalsifiabilityGuide {...falsProps()} />,
      <ProvenanceAck {...provProps()} />,
      <RedVerdictAck {...redProps()} />,
    ]) {
      const { container, unmount } = renderWithDesk(ui);
      const shell = container.querySelector('[data-weakness-expanded]');
      expect(shell).not.toBeNull();
      // R25：弱点常驻展开——expanded 恒 true。
      expect(shell).toHaveAttribute("data-weakness-expanded", "true");
      // 绝不渲染折叠/收起控件——无从把弱点藏起。
      expect(container.querySelector('[aria-label="折叠"]')).toBeNull();
      expect(container.querySelector('[aria-label="收起"]')).toBeNull();
      expect(container.querySelector('[aria-label="展开"]')).toBeNull();
      unmount();
    }
  });

  it("对抗：种「弱点列表被折叠到 0 条/隐藏」必抓 —— 内容恒可见", () => {
    // 红裁决弱点必须在 DOM 中可见（非 display:none、非空列表）。
    renderWithDesk(<RedVerdictAck {...redProps()} />);
    const list = screen.getByTestId("red-verdict-weaknesses");
    expect(list.querySelectorAll("li").length).toBeGreaterThan(0);
    // 血统未过因子同理。
    renderWithDesk(<ProvenanceAck {...provProps()} />);
    expect(screen.getByTestId("provenance-list").querySelectorAll("li").length)
      .toBeGreaterThan(0);
  });
});

describe("治理硬约束 · R7 措辞（对抗：禁词必抓）", () => {
  it("三型弹窗渲染文本不含 R7 禁词（可信/安全/排除过拟合…）", () => {
    for (const ui of [
      <FalsifiabilityGuide {...falsProps()} />,
      <ProvenanceAck {...provProps()} />,
      <RedVerdictAck {...redProps()} />,
    ]) {
      const { container, unmount } = renderWithDesk(ui);
      assertNoForbiddenWords(container.textContent ?? "");
      unmount();
    }
  });

  it("red 裁决 note 走后端 prop（前端不杜撰）—— 注入禁词由后端口径负责，组件原样透传", () => {
    // 组件不自造措辞：传入什么 note 就显示什么（落地 note 来自 verifier._verdict_note，已过 R7）。
    renderWithDesk(
      <RedVerdictAck
        {...redProps({ verdictNote: "证据存疑：适用域受限，未验证项 2。" })}
      />,
    );
    expect(screen.getByTestId("red-verdict-note")).toHaveTextContent("证据存疑");
  });

  it("对抗：源码静态守卫 —— TeachingPopups.tsx 字符串字面量不含 R7 禁词", () => {
    const src = readFileSync(join(here, "TeachingPopups.tsx"), "utf8");
    // 抽出双引号字符串字面量（粗扫，足以抓住硬编码的绝对化措辞）。
    const literals = src.match(/"[^"\n]*"/g) ?? [];
    for (const lit of literals) {
      for (const w of FORBIDDEN_VERDICT_WORDS) {
        expect(lit.includes(w), `禁词「${w}」出现在字面量 ${lit}`).toBe(false);
      }
    }
  });

  it("agentMock 教学 mock 文案不含 R7 禁词（verdictNote / blurb 占位走合规口径）", () => {
    assertNoForbiddenWords(MOCK_RED_VERDICT.verdictNote);
    assertNoForbiddenWords(MOCK_RED_VERDICT.weaknesses.join(" "));
    assertNoForbiddenWords(MOCK_FALSIFIABILITY_GUIDE.flags.join(" "));
    assertNoForbiddenWords(
      MOCK_PROVENANCE_ACK.unverified.map((u) => u.stage).join(" "),
    );
  });
});

// ── 页面接线（触发器 → 弹窗 → 知情确认留痕） ───────────────────────────
describe("AgentWorkbench 接线 · 三型教学弹窗触发 + 软决定留痕", () => {
  it("触发器三按钮在状态行下方", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    expect(container.querySelector("[data-teach-falsifiability]")).not.toBeNull();
    expect(container.querySelector("[data-teach-provenance]")).not.toBeNull();
    expect(container.querySelector("[data-teach-red-verdict]")).not.toBeNull();
  });

  it("点「可证伪引导」→ 弹窗出现；知情确认 → 留痕回执（账本/needs_human_review）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    fireEvent.click(container.querySelector("[data-teach-falsifiability]")!);
    expect(screen.getByTestId("falsifiability-guide")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("falsifiability-ack"));
    // 弹窗收起，出现诚实留痕回执（非假绿灯）。
    expect(screen.queryByTestId("falsifiability-guide")).toBeNull();
    expect(screen.getByTestId("teach-note")).toHaveTextContent(/honest-N|账本/);
  });

  it("点「血统警告」→ 列出未过因子；知情确认 → acknowledge 留痕回执", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    fireEvent.click(container.querySelector("[data-teach-provenance]")!);
    expect(screen.getByTestId("provenance-ack")).toBeInTheDocument();
    expect(screen.getAllByTestId("provenance-item").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("provenance-ack-btn"));
    expect(screen.getByTestId("teach-note")).toHaveTextContent(/留痕|审计/);
  });

  it("点「red 裁决」→ 一等呈现弱点；知情确认留痕", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    fireEvent.click(container.querySelector("[data-teach-red-verdict]")!);
    expect(screen.getByTestId("red-verdict-ack")).toBeInTheDocument();
    expect(screen.getAllByTestId("red-verdict-weakness").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("red-verdict-ack-btn"));
    expect(screen.getByTestId("teach-note")).toHaveTextContent(/留痕/);
  });

  it("可证伪「去填假设卡」→ 切到立题 cowork（引导回正确路径，非死挡）", () => {
    const { container } = renderWithDesk(<AgentWorkbenchPage />);
    fireEvent.click(container.querySelector("[data-teach-falsifiability]")!);
    fireEvent.click(screen.getByTestId("falsifiability-fill"));
    expect(screen.queryByTestId("falsifiability-guide")).toBeNull();
    expect(screen.getByTestId("teach-note")).toHaveTextContent(/假设卡/);
  });
});
