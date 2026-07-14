import { describe, it, expect, beforeEach } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithDesk } from "../../../test/harness";
import { FactorDeskPage } from "./FactorDeskPage";
import {
  buildMockFactors,
  icThresholdColor,
  irThresholdColor,
  tThresholdColor,
  stateColorVar,
  eventsFor,
  LIFECYCLE_PATH,
} from "./factorData";
import {
  auditVerdict,
  buildChecks,
} from "./FactorResearchView";
import { isBalanced } from "./FactorBuildView";

const here = dirname(fileURLToPath(import.meta.url));
const SUCCESS = "var(--desk-success)";

// jsdom 无 fetch；mock 成功路径返回空数组 → 页面回落 mock 全集。
beforeEach(() => {
  globalThis.fetch = (() =>
    Promise.resolve(new Response("[]", { status: 200 }))) as typeof fetch;
});

describe("F1 因子台 · 渲染骨架", () => {
  it("DeskShell data-desk=factor（紫 accent 由 data-desk 注入）", () => {
    const { container } = renderWithDesk(<FactorDeskPage />);
    const root = container.querySelector(".desk-root");
    expect(root).not.toBeNull();
    expect(root).toHaveAttribute("data-desk", "factor");
  });

  it("5 视图 SubTabBar 全在 + 默认因子库 + 可切到全部视图", () => {
    renderWithDesk(<FactorDeskPage />);
    // SubTabBar 5 个 tab 按钮全在（用 ▤⊞⚖⌨⚗ glyph 锚定，避开同名面板标题）
    for (const t of ["▤ 因子库", "⊞ 相关性", "⚖ 评测台", "⌨ 构建台", "⚗ 研究台"]) {
      expect(screen.getByText(t)).toBeInTheDocument();
    }
    // 默认 library：五态机标题在
    expect(screen.getByText(/因子五态机/)).toBeInTheDocument();
    // 切相关性
    fireEvent.click(screen.getByText(/相关性/));
    expect(screen.getByText(/因子相关矩阵/)).toBeInTheDocument();
    // 切评测台
    fireEvent.click(screen.getByText(/评测台/));
    expect(screen.getByText(/五分位累计净值/)).toBeInTheDocument();
    // 切构建台
    fireEvent.click(screen.getByText(/构建台/));
    expect(screen.getByText(/表达式编辑器/)).toBeInTheDocument();
    // 切研究台
    fireEvent.click(screen.getByText(/研究台/));
    expect(screen.getByText(/alpha 真伪审查/)).toBeInTheDocument();
  });
});

describe("F1 · 对抗③ mock 区块必挂 MockBadge（诚实，不假绿灯）", () => {
  it("常驻 SubTabBar 角标 + 各 mock view 至少一个 MOCK 标注", () => {
    renderWithDesk(<FactorDeskPage />);
    // SubTabBar 常驻角标
    expect(screen.getAllByText(/MOCK 数据/).length).toBeGreaterThan(0);

    // 每个 mock 视图都得有 MOCK 标注
    for (const [tab, _marker] of [
      ["相关性", /相关矩阵合成/],
      ["评测台", /分层回测合成/],
      ["构建台", /即时 IC/],
      ["研究台", /审查报告合成/],
    ] as const) {
      fireEvent.click(screen.getByText(new RegExp(tab)));
      expect(screen.getAllByText(/MOCK 数据/).length).toBeGreaterThan(0);
    }
  });
});

describe("F1 · 对抗① 五态机阈值/前视：未验证不假绿灯", () => {
  it("RETIRED 因子的未达节点不染成 active 实心绿；连线阈值标注齐全", () => {
    renderWithDesk(<FactorDeskPage />);
    // 选 RETIRED 因子
    const retired = buildMockFactors().find((f) => f.state === "RETIRED")!;
    fireEvent.click(screen.getByRole("button", { pressed: false, name: new RegExp(retired.id) }));

    // 五态机 5 段阈值标注必须全渲染（阈值参数化，不省略）
    for (const th of ["IC>.03·IR>.5", "3月IC≥0", "实盘>基准", "衰减>50%", "2周未修复"]) {
      expect(screen.getByText(th)).toBeInTheDocument();
    }
  });

  it("阈值色映射：IC<=0 / 边际 不返回 success（未达标不染绿）", () => {
    // 达标才绿；负/边际绝不绿
    expect(icThresholdColor(0.05)).toBe(SUCCESS);
    expect(icThresholdColor(-0.01)).not.toBe(SUCCESS);
    expect(icThresholdColor(0.01)).not.toBe(SUCCESS);
    expect(irThresholdColor(0.6)).toBe(SUCCESS);
    expect(irThresholdColor(0.2)).not.toBe(SUCCESS);
    expect(irThresholdColor(-0.1)).not.toBe(SUCCESS);
    // |t|<3 证据不足 → 非绿
    expect(tThresholdColor(2.0)).not.toBe(SUCCESS);
    expect(tThresholdColor(3.5)).toBe(SUCCESS);
  });

  it("event_log 链：RETIRED 走完整迁移、NEW 仅入库一条（不杜撰跳态）", () => {
    const factors = buildMockFactors();
    const retired = factors.find((f) => f.state === "RETIRED")!;
    const ev = eventsFor(retired);
    // 退役因子事件链长度 = 路径长度 - 1（NEW→...→RETIRED 共 5 段）
    expect(ev.length).toBe(LIFECYCLE_PATH.length - 1);
    expect(ev[0].to).toBe("RETIRED");

    const fresh = factors.find((f) => f.state === "NEW")!;
    const evNew = eventsFor(fresh);
    expect(evNew.length).toBe(1);
    expect(evNew[0].to).toBe("NEW");
  });
});

describe("F1 · 对抗② IC/audit 弱点默认展开、不折叠、不染绿（R25）", () => {
  it("存疑/未通过裁决不返回 success 色；真 alpha 才绿", () => {
    const factors = buildMockFactors();
    const retired = factors.find((f) => f.state === "RETIRED")!;
    expect(auditVerdict(retired)).toBe("未通过");

    // 构造一个 IR/ t 不达标 → 存疑（非未通过、非真 alpha）
    const weak = { ...factors[0], state: "PROBATION" as const, icIr: 0.3, sampleT: 1.5 };
    expect(auditVerdict(weak)).toBe("存疑");

    const strong = factors.find((f) => f.icIr > 0.5 && Math.abs(f.sampleT) > 3 && f.state !== "RETIRED")!;
    expect(auditVerdict(strong)).toBe("真 alpha");
  });

  it("弱 check 标 weak=true、颜色绝不是 success（不染绿）", () => {
    const factors = buildMockFactors();
    const warning = factors.find((f) => f.state === "WARNING")!;
    const checks = buildChecks(warning, 15, 1);
    const weakChecks = checks.filter((c) => c.weak);
    expect(weakChecks.length).toBeGreaterThan(0);
    for (const c of weakChecks) {
      expect(c.color).not.toBe(SUCCESS);
      expect(c.icon).not.toBe("✓"); // 弱点不打勾
    }
  });

  it("研究台渲染：弱点 check 的 detail 常驻展开（不折叠藏起）", () => {
    renderWithDesk(<FactorDeskPage />);
    // 选 WARNING 因子（含快速衰减弱点）
    const warning = buildMockFactors().find((f) => f.state === "WARNING")!;
    fireEvent.click(screen.getByRole("button", { pressed: false, name: new RegExp(warning.id) }));
    fireEvent.click(screen.getByText(/研究台/));

    // 所有 check 的 detail 都直接在 DOM（无折叠态），弱点 border 用弱点色
    const checks = document.querySelectorAll("[data-check]");
    expect(checks.length).toBe(5);
    const details = document.querySelectorAll("[data-check-detail]");
    expect(details.length).toBe(5); // 每条 detail 都常驻渲染，未被折叠
    const weakChecks = document.querySelectorAll('[data-check][data-weak="true"]');
    expect(weakChecks.length).toBeGreaterThan(0);
  });
});

describe("F1 · 交互：构建台校验 + 注册 + 算子插入", () => {
  it("括号配平校验（mock 编译门）", () => {
    expect(isBalanced("ts_mean(close, 20)")).toBe(true);
    expect(isBalanced("ts_mean(close, 20")).toBe(false);
  });

  it("注册预检无后端端点时 fail closed，不报告写入成功", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText(/构建台/));
    fireEvent.click(screen.getByText(/注册预检/));
    expect(screen.getByRole("dialog", { name: /注册因子/ })).toBeInTheDocument();
    const register = screen.getByRole("button", { name: /未连接 · 不注册/ });
    expect(register).toBeDisabled();
    expect(screen.getByText(/当前未连接 registry 写入端点/)).toBeInTheDocument();
    expect(screen.queryByText(/已注册到因子库/)).toBeNull();
  });
});

describe("F1 · 相关性交互：点单元格开配对详情", () => {
  it("点矩阵单元格弹出配对详情，✕ 可关闭", () => {
    renderWithDesk(<FactorDeskPage />);
    fireEvent.click(screen.getByText(/相关性/));
    // 找一个非对角线单元格（title 含 ×）
    const cell = screen
      .getAllByRole("button")
      .find((b) => /×/.test(b.getAttribute("title") ?? ""));
    expect(cell).toBeTruthy();
    fireEvent.click(cell!);
    expect(screen.getByText("配对详情")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("关闭配对详情"));
    expect(screen.queryByText("配对详情")).toBeNull();
  });
});

describe("F1 · 对抗 token：本卡所有源文件禁裸 hex（须走 --desk-* token）", () => {
  it("pages/workshop/factor 下实现文件零 #hex", () => {
    const files = readdirSync(here).filter(
      (f) => /\.tsx?$/.test(f) && !f.includes(".test."),
    );
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(join(here, f), "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });
});

describe("F1 · 状态色映射零裸 hex（token 化）", () => {
  it("stateColorVar 全部返回 var(--desk-*) 引用", () => {
    for (const s of LIFECYCLE_PATH) {
      expect(stateColorVar(s)).toMatch(/^var\(--desk-/);
    }
  });
});
