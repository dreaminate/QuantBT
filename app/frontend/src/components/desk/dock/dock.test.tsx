import { describe, it, expect, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen, fireEvent } from "@testing-library/react";
import { DockTabs, type DockTab } from "./DockTabs";
import { Dock } from "./Dock";
import { MockBadge } from "../primitives";

const here = dirname(fileURLToPath(import.meta.url));

describe("G3 Dock 工作台组件", () => {
  it("DockTabs：复用 SegmentedControl，6 tab 受控切换", () => {
    const onChange = vi.fn();
    render(<DockTabs value="preview" onChange={onChange} />);
    expect(screen.getByText("输出预览")).toBeInTheDocument();
    expect(screen.getByText("血缘溯源")).toBeInTheDocument();
    fireEvent.click(screen.getByText("日志"));
    expect(onChange).toHaveBeenCalledWith<[DockTab]>("logs");
  });

  it("Dock：228 容器渲染 tabs 槽 + right 槽 + 内容槽 + 折叠回调", () => {
    const onCollapse = vi.fn();
    render(
      <Dock
        tabs={<div data-testid="tabs">tabs</div>}
        right={<MockBadge />}
        onCollapse={onCollapse}
      >
        <div data-testid="body">日志内容</div>
      </Dock>,
    );
    expect(screen.getByTestId("tabs")).toBeInTheDocument();
    expect(screen.getByText("MOCK 数据")).toBeInTheDocument();
    expect(screen.getByTestId("body")).toBeInTheDocument();
    const root = document.querySelector("[data-dock]") as HTMLElement;
    expect(root.style.height).toBe("228px");
    fireEvent.click(screen.getByLabelText("收起工作台"));
    expect(onCollapse).toHaveBeenCalledTimes(1);
  });

  it("对抗#1 token 不漂：dock 组件源码禁裸 hex 色值", () => {
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
