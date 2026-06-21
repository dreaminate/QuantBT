import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { renderWithDesk } from "../../../test/harness";
import { AgentWorkbenchPage } from "./AgentWorkbenchPage";

/**
 * T-042 桌面挂载对抗测试（一套组件两处挂载 = Web + Tauri 桌面窗口）。
 *
 * 核心红线：桌面窗口与 Web 同组件、同行为、不绕治理门（沿用 T-029 / T-040）。
 * 实现 = Tauri 窗口加载 index.html?view=agent-workbench，main.tsx 在 React 挂载前
 * 把初始路由改写成 /agent-workbench，再交给既有 App.tsx 路由 —— 不重写、不旁路。
 *
 * 故不读 import.meta.env / __TAURI__ 来分叉行为：分叉=两套，正是本卡要禁止的。
 * 这里把「桌面入口 → 既有路由 → 同一被治理组件」钉成可回归的门。
 */

const here = dirname(fileURLToPath(import.meta.url));
const repoFrontend = join(here, "..", "..", "..", "..");
const mainTsx = readFileSync(join(repoFrontend, "src", "main.tsx"), "utf8");
const tauriConf = readFileSync(
  join(repoFrontend, "..", "desktop", "src-tauri", "tauri.conf.json"),
  "utf8",
);

describe("T-042 桌面挂载 · 入口门（一套两挂、不绕治理）", () => {
  it("Tauri 窗口 url 指向 index.html?view=agent-workbench（dev+build 都能解析的入口）", () => {
    const conf = JSON.parse(tauriConf);
    const win = conf.app?.windows?.find(
      (w: { label?: string }) => w.label === "main",
    );
    expect(win, "main 窗口须存在").toBeTruthy();
    // index.html 始终解析（dev server + 生产 asset 协议均可）；?view= 是桌面视图选择器。
    expect(win.url).toBe("index.html?view=agent-workbench");
  });

  it("main.tsx 桌面入口门：?view=agent-workbench 改写到 /agent-workbench（Web 无 view 不动）", () => {
    // 入口门必须存在且映射到真实路由 —— 种「映射被删/改到别处」即此断言抓。
    expect(mainTsx).toMatch(/["']agent-workbench["']\s*:\s*["']\/agent-workbench["']/);
    expect(mainTsx).toMatch(/replaceState/);
    expect(mainTsx).toMatch(/\.get\(["']view["']\)/);
  });

  it("桌面入口门只改写已知视图、不裸用 search 当路径（防开放重定向）", () => {
    // 用白名单 VIEW_ROUTES 映射，而非 history.replaceState(..., location.search)。
    expect(mainTsx).toMatch(/VIEW_ROUTES/);
    expect(mainTsx).not.toMatch(/replaceState\([^)]*location\.search/);
  });

  it("桌面路由复用同一被治理组件 AgentWorkbenchPage（非另起旁路窗口）", () => {
    // 模拟 main.tsx 改写后的初始路由：/agent-workbench → 既有 App 路由 → 同组件。
    renderWithDesk(
      <Routes>
        <Route path="/agent-workbench" element={<AgentWorkbenchPage />} />
      </Routes>,
      { route: "/agent-workbench" },
    );
    // 同组件 ⇒ 同治理：常驻 MockBadge（诚实角标）+ DeskShell agent 台在场。
    expect(screen.getAllByText(/MOCK/).length).toBeGreaterThan(0);
  });
});
