import { describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent, within } from "@testing-library/react";
import {
  renderWithDesk,
  assertNoForbiddenWords,
  assertNoFrozenPageImport,
  scanForbiddenWords,
} from "../test/harness";
import {
  RunVerdictCard,
  MOCK_RUN_VERDICT,
  type RunVerdictData,
  type Verdict,
} from "./RunVerdictCard";

const here = dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(join(here, "RunVerdictCard.tsx"), "utf8");

const ALLOWED_VERDICTS: Verdict[] = ["consistent", "concern", "blocked"];

function makeData(over: Partial<RunVerdictData> = {}): RunVerdictData {
  return { ...MOCK_RUN_VERDICT, ...over };
}

describe("R1 RunVerdictCard · 渲染 + mock 诚实", () => {
  it("渲染裁决卡 + MOCK 角标（mock 区块诚实，不假绿灯）", () => {
    renderWithDesk(<RunVerdictCard data={makeData()} />);
    expect(screen.getByTestId("run-verdict-card")).toBeInTheDocument();
    expect(screen.getAllByText("MOCK 数据").length).toBeGreaterThanOrEqual(1);
  });

  it("KPI/成本敏感性/PBO/DSR 区块齐备", () => {
    renderWithDesk(<RunVerdictCard data={makeData()} />);
    expect(screen.getByText("年化超额")).toBeInTheDocument();
    expect(screen.getByText("最大回撤")).toBeInTheDocument();
    expect(screen.getByText("Sharpe")).toBeInTheDocument();
    expect(screen.getByText("周胜率")).toBeInTheDocument();
    expect(screen.getByText("成本敏感性 · Sharpe / 年化超额")).toBeInTheDocument();
    expect(screen.getByText("PBO")).toBeInTheDocument();
    expect(screen.getByText("DSR")).toBeInTheDocument();
    expect(screen.getByText("optimistic")).toBeInTheDocument();
    expect(screen.getByText("pessimistic")).toBeInTheDocument();
  });
});

describe("R1 RunVerdictCard · 对抗测试①：禁止 import 冻结页", () => {
  it("源码不含 frontend-run-detail 冻结 RunDetailPage 的 import", () => {
    expect(() => assertNoFrozenPageImport(SOURCE)).not.toThrow();
    // 种坏门必抓：若源码真引用冻结页，守卫会抛
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
});

describe("R1 RunVerdictCard · 对抗测试②：R7 措辞门（无禁词）", () => {
  it("三态全渲染文本均无『可信/安全/保证/排除过拟合/可复现/组织独立』", () => {
    for (const v of ALLOWED_VERDICTS) {
      const { container, unmount } = renderWithDesk(
        <RunVerdictCard data={makeData({ verdict: v })} />,
      );
      // 打开 modal，让 modal 内全部裁决文案也进扫描面
      fireEvent.click(screen.getByText("卡内预览"));
      expect(() =>
        assertNoForbiddenWords(container.textContent ?? ""),
      ).not.toThrow();
      expect(() =>
        assertNoForbiddenWords(document.body.textContent ?? ""),
      ).not.toThrow();
      unmount();
    }
  });

  it("种坏门必抓：若 note 含『排除过拟合』，扫描器命中", () => {
    expect(scanForbiddenWords("PBO 0.18 排除过拟合，结论可信")).toEqual([
      "可信",
      "排除过拟合",
    ]);
  });

  it("MOCK 占位 note 用合规措辞（容差内/适用域/未验证项），非绝对化", () => {
    expect(scanForbiddenWords(MOCK_RUN_VERDICT.verdictNote)).toEqual([]);
    expect(MOCK_RUN_VERDICT.verdictNote).toMatch(/适用域/);
    expect(MOCK_RUN_VERDICT.verdictNote).toMatch(/未验证项/);
  });
});

describe("R1 RunVerdictCard · 对抗测试③：verdict 仅三态", () => {
  it("type/数据仅取 consistent/concern/blocked，且映射展示文案", () => {
    const expectLabel: Record<Verdict, string> = {
      consistent: "证据一致",
      concern: "证据存疑",
      blocked: "证据不一致",
    };
    for (const v of ALLOWED_VERDICTS) {
      const { unmount } = renderWithDesk(
        <RunVerdictCard data={makeData({ verdict: v })} />,
      );
      const pill = screen.getByTestId("verdict-pill");
      expect(pill).toHaveTextContent(expectLabel[v]);
      unmount();
    }
  });

  it("不混 overfit_gate『晋级候选』：源码无该词作 verdict 枚举值", () => {
    // 「晋级候选」只能出现在 promote 按钮文案，绝不作 verdict pill 的取值。
    // verdict pill 文案严格落在三态映射内。
    for (const v of ALLOWED_VERDICTS) {
      const { unmount } = renderWithDesk(
        <RunVerdictCard data={makeData({ verdict: v })} />,
      );
      expect(screen.getByTestId("verdict-pill")).not.toHaveTextContent(
        "晋级候选",
      );
      unmount();
    }
  });
});

describe("R1 RunVerdictCard · 对抗测试④：promote 受控、不前端伪造写盘", () => {
  it("点 promote 触发 onPromote(runId)，组件自身不改 promoteState", () => {
    const onPromote = vi.fn();
    const data = makeData({ promoteState: "candidate" });
    renderWithDesk(<RunVerdictCard data={data} onPromote={onPromote} />);
    const btn = screen.getByTestId("promote-btn");
    expect(btn).toHaveTextContent("登记为晋级候选");
    fireEvent.click(btn);
    expect(onPromote).toHaveBeenCalledTimes(1);
    expect(onPromote).toHaveBeenCalledWith(data.runId);
    // 受控：父层未回传 registered，按钮文案不自变（不伪造写盘成功）
    expect(screen.getByTestId("promote-btn")).toHaveTextContent(
      "登记为晋级候选",
    );
  });

  it("promoteState=registered 由父层传入才显示已登记，且按钮禁用", () => {
    const onPromote = vi.fn();
    renderWithDesk(
      <RunVerdictCard
        data={makeData({ promoteState: "registered" })}
        onPromote={onPromote}
      />,
    );
    const btn = screen.getByTestId("promote-btn");
    expect(btn).toHaveTextContent("已登记对比分析");
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onPromote).not.toHaveBeenCalled();
  });
});

describe("R1 RunVerdictCard · detail modal 交互", () => {
  it("卡内预览打开 modal → metrics/热力/交易/过拟合/成本/持仓齐", () => {
    renderWithDesk(<RunVerdictCard data={makeData()} />);
    fireEvent.click(screen.getByText("卡内预览"));
    const modal = screen.getByTestId("verdict-detail-modal");
    const q = within(modal);
    expect(q.getByText("月度超额收益热力图")).toBeInTheDocument();
    expect(q.getByText("交易统计")).toBeInTheDocument();
    expect(q.getByText("过拟合体检")).toBeInTheDocument();
    expect(q.getByText(/成本设置/)).toBeInTheDocument();
    expect(q.getByText("期末持仓 · top 8")).toBeInTheDocument();
  });

  it("可编辑成本：改输入即重算单边合计 bp（纯展示重算）", () => {
    renderWithDesk(<RunVerdictCard data={makeData()} />);
    fireEvent.click(screen.getByText("卡内预览"));
    const modal = screen.getByTestId("verdict-detail-modal");
    const q = within(modal);
    // 初始 commission2.5 + slippage5 + stamp5/2 + impact3 = 13.0
    expect(q.getByText("单边合计 13.0 bp")).toBeInTheDocument();
    const slippage = q.getByLabelText("滑点") as HTMLInputElement;
    fireEvent.change(slippage, { target: { value: "9" } });
    // 2.5 + 9 + 2.5 + 3 = 17.0
    expect(q.getByText("单边合计 17.0 bp")).toBeInTheDocument();
  });

  it("✕ 关闭 / 点遮罩关闭 modal", () => {
    renderWithDesk(<RunVerdictCard data={makeData()} />);
    fireEvent.click(screen.getByText("卡内预览"));
    expect(screen.getByTestId("verdict-detail-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByText("✕ 关闭"));
    expect(screen.queryByTestId("verdict-detail-modal")).toBeNull();
  });
});

describe("R1 RunVerdictCard · 对抗测试⑤：零裸 hex（须走 --desk-* token）", () => {
  it("源码无裸 hex 色值", () => {
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const hits = SOURCE.match(HEX);
    expect(hits).toBeNull();
  });
});

describe("R1 RunVerdictCard · 外链路由（不嵌冻结页）", () => {
  it("detailHref 提供时渲染外链；缺省不渲染（避免死链）", () => {
    const { unmount } = renderWithDesk(
      <RunVerdictCard data={makeData()} detailHref="/runs/run-20240601-a1b2" />,
    );
    const link = screen.getByText("完整回测详情页 ↗").closest("a");
    expect(link).toHaveAttribute("href", "/runs/run-20240601-a1b2");
    unmount();
    renderWithDesk(<RunVerdictCard data={makeData()} />);
    expect(screen.queryByText("完整回测详情页 ↗")).toBeNull();
  });
});
