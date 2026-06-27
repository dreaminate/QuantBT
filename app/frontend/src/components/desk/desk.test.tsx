import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MockBadge } from "./primitives";
import { CollapsiblePanel } from "./CollapsiblePanel";
import { DeskShell } from "./DeskShell";
import { DeskSwitcher } from "./DeskTopBar";
import { Inspector } from "./inspector";
import { cssToObj } from "../../lib/cssToObj";

const here = dirname(fileURLToPath(import.meta.url));

describe("G1 暗色台地基", () => {
  it("cssToObj：DC 动态样式串 → React style 对象（kebab→camel，--var 保留）", () => {
    expect(cssToObj("display:flex; gap:10px; --desk-accent:#d97757")).toEqual({
      display: "flex",
      gap: "10px",
      "--desk-accent": "#d97757",
    });
  });

  it("MockBadge 诚实角标渲染（默认『MOCK 数据』，不可缺）", () => {
    render(<MockBadge />);
    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
  });

  it("DeskSwitcher：六个台都渲染为可点击链接，当前台只用 aria-current 标记", () => {
    render(
      <MemoryRouter>
        <DeskSwitcher current="strategy" />
      </MemoryRouter>,
    );
    expect(screen.getByText("总览台").closest("a")).toHaveAttribute("href", "/overview");
    expect(screen.getByText("策略台").closest("a")).toHaveAttribute("href", "/strategy");
    expect(screen.getByText("策略台").closest("a")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("因子台").closest("a")).toHaveAttribute("href", "/factors");
    expect(screen.getByText("Model台").closest("a")).toHaveAttribute("href", "/models");
    expect(screen.getByText("模拟台").closest("a")).toHaveAttribute("href", "/paper");
    expect(screen.getByText("研究执行台").closest("a")).toHaveAttribute("href", "/agent-workbench");
  });

  it("DeskShell：左右分隔线可调面板宽度", () => {
    localStorage.clear();
    const { container } = render(
      <DeskShell
        desk="strategy"
        topbar={<div />}
        left={
          <CollapsiblePanel open onToggle={() => {}} side="left" label="左栏">
            left
          </CollapsiblePanel>
        }
        center={<div>center</div>}
        right={<Inspector title="右栏">right</Inspector>}
      />,
    );
    const root = container.querySelector(".desk-root") as HTMLElement;
    const leftSplitter = container.querySelector('[data-pane-splitter="left"]') as HTMLElement;
    const rightSplitter = container.querySelector('[data-pane-splitter="right"]') as HTMLElement;

    expect(root.style.getPropertyValue("--desk-left-pane-width")).toBe("316px");
    fireEvent.keyDown(leftSplitter, { key: "ArrowRight" });
    expect(root.style.getPropertyValue("--desk-left-pane-width")).toBe("332px");

    expect(root.style.getPropertyValue("--desk-right-pane-width")).toBe("340px");
    fireEvent.keyDown(rightSplitter, { key: "ArrowLeft" });
    expect(root.style.getPropertyValue("--desk-right-pane-width")).toBe("356px");
  });

  it("对抗#1 token 不漂：desk 组件实现禁裸 hex 色值（须走 --desk-* token）", () => {
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
