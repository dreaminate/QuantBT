import { describe, it, expect, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen, fireEvent } from "@testing-library/react";
import { ParamRow } from "./ParamRow";
import { InspectorTabs, type InspectorTab } from "./InspectorTabs";
import { Inspector } from "./Inspector";

const here = dirname(fileURLToPath(import.meta.url));

describe("G3 Inspector 组件", () => {
  it("ParamRow：受控 input + ?tip 渲染", () => {
    const onChange = vi.fn();
    render(
      <ParamRow
        label="lookback"
        value="20"
        onChange={onChange}
        tip="回看窗口长度"
      />,
    );
    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input.value).toBe("20");
    fireEvent.change(input, { target: { value: "30" } });
    expect(onChange).toHaveBeenCalledWith("30");
    expect(screen.getByText("?")).toBeInTheDocument();
  });

  it("对抗：ParamRow locked → input disabled（不可编辑）", () => {
    const onChange = vi.fn();
    render(<ParamRow label="kill_switch" value="armed" onChange={onChange} locked />);
    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });

  it("ParamRow readonly → input disabled（Live 只读态）", () => {
    render(<ParamRow label="rate" value="0.02" onChange={() => {}} readOnly />);
    expect((screen.getByRole("textbox") as HTMLInputElement).disabled).toBe(true);
  });

  it("InspectorTabs：复用 SegmentedControl，受控切 tab", () => {
    const onChange = vi.fn();
    render(<InspectorTabs value="params" onChange={onChange} />);
    const ports = screen.getByText("端口");
    expect(ports.closest('[role="tab"]')).not.toBeNull();
    fireEvent.click(ports);
    expect(onChange).toHaveBeenCalledWith<[InspectorTab]>("ports");
  });

  it("Inspector：CSS 变量宽度容器渲染标题 + selectionHead + tabs + 内容槽 + 折叠回调", () => {
    const onCollapse = vi.fn();
    render(
      <Inspector
        title="MomentumFactor"
        onCollapse={onCollapse}
        selectionHead={<div data-testid="head">头</div>}
        tabs={<div data-testid="tabs">tabs</div>}
      >
        <div data-testid="body">参数内容</div>
      </Inspector>,
    );
    expect(screen.getByText("MomentumFactor")).toBeInTheDocument();
    expect(screen.getByTestId("head")).toBeInTheDocument();
    expect(screen.getByTestId("tabs")).toBeInTheDocument();
    expect(screen.getByTestId("body")).toBeInTheDocument();
    const root = document.querySelector("[data-inspector]") as HTMLElement;
    expect(root.style.width).toBe("var(--desk-right-pane-width, 340px)");
    fireEvent.click(screen.getByLabelText("折叠 Inspector"));
    expect(onCollapse).toHaveBeenCalledTimes(1);
  });

  it("对抗#1 token 不漂：inspector 组件源码禁裸 hex 色值", () => {
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
