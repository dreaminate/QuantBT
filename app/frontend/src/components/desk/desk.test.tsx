import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MockBadge } from "./primitives";
import { DeskSwitcher } from "./DeskTopBar";
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

  it("DeskSwitcher：当前台高亮(span)、可跳台(<a href>)、soon 台占位不死链", () => {
    render(
      <MemoryRouter>
        <DeskSwitcher current="strategy" soon={["factor", "paper"]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("策略台").tagName).toBe("SPAN"); // 当前台非链接
    expect(screen.getByText("Model台").closest("a")).toHaveAttribute(
      "href",
      "/models",
    ); // 可跳台
    expect(screen.getByText("因子台").closest("a")).toBeNull(); // soon 占位，不渲染链接（防死链）
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
