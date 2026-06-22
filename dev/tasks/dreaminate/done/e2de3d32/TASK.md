---
uuid: e2de3d323bef48f9a0cf5737aeb3a3b5
title: 前端测试设施基建 — vitest + React Testing Library + 对抗测试 harness
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: frontend-foundation
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（前端零测试设施缺口，进 P0 前必补）
depends_on: []
---

# 前端测试设施基建 — vitest + React Testing Library + 对抗测试 harness

## Scope [必填]
给 `app/frontend` 搭前端测试设施（vitest + @testing-library/react + jsdom + `test` script + CI 可跑），并约定「对抗测试 harness」规约（组件渲染断言 / 关键交互 / 快照基线），使整套台所有前端卡的「种已知 bug 门必抓」可落地。**不做**：不写各台业务测试（各卡自带）、不碰冻结的 `frontend-run-detail` 工程测试设施、不引入重型 e2e（playwright 留按需另卡）。

## 上下文 / 动机 [按需]
现状勘查：`app/frontend/package.json` 仅 `dev`/`build` script、devDeps 无任何测试框架（无 vitest/playwright/jest）、`src/` 下 0 测试文件。整套台 epic（cfb0fea9）每张前端卡的对抗测试（裁决卡不嵌冻结页 / bypass 不跳治理门 / 措辞禁词 / locked 不可删 / 弱点不折叠…）都需要可运行的前端测试才算「门必抓」——这是 dev OS「种已知 bug 门必抓」铁律的落地前提。本卡是所有前端实装卡（G1/G2/G3 及各台）的硬前置。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/package.json | scripts + devDependencies | 加 `"test": "vitest"`（+ `test:run`）；devDeps 加 vitest / @testing-library/react / @testing-library/jest-dom / jsdom（不动现有 dev/build） |
| app/frontend/vitest.config.ts | 新建 | jsdom 环境 + setup + 复用 vite 的 @vitejs/plugin-react |
| app/frontend/src/test/setup.ts | 新建 | jest-dom 扩展断言 + 全局清理 |
| app/frontend/src/test/harness.ts | 新建 | 对抗测试公共工具：renderWithDesk / 禁词扫描 assert / 冻结页 import 守卫 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「一条故意失败的 sample 断言（expect(1).toBe(2)）」→ `npm test` 必须 fail（证明 runner 真会红，非空跑绿）。变异要杀：把 test script 配成永远 exit 0。
2. 种「harness 禁词扫描器喂入含『可信/安全/排除过拟合/保证』的字符串」→ 扫描断言必抓（R7 措辞门的可复用工具，供 R1/R2 等裁决类卡用）。
3. 种「harness 冻结页 import 守卫：测试 import 了 frontend-run-detail 冻结 RunDetailPage」→ 守卫必抓（供 R1 卡复用，防裁决卡嵌冻结页）。

## 复用 [按需]
现有 `@vitejs/plugin-react`（vite 已用，vitest 复用同 plugin）；现有 tsconfig。

## 红线 [按需]
扩展不替换 package.json（只加 test script + devDeps，不动 dev/build）；不碰 frontend-run-detail 冻结工程；测试设施本身不得形同虚设（assert true / 永远 exit 0 = 假绿灯，违 §3 不假绿灯）。

## 非目标 [按需]
不写各台业务测试；不引 playwright/e2e（按需另卡）；不动后端 pytest（已有基线）。

## Open Questions（已决 2/2）[按需]
- [已决] 测试栈选 vitest + RTL + jsdom（与现有 vite 同源、零额外构建链，最轻量）；e2e/像素对比留按需另卡。
- [已决] 对抗 harness 提供 3 个公共工具（renderWithDesk / 禁词扫描 / 冻结页 import 守卫），供各台卡复用，避免每卡重造。

## 验收一句话 [必填]
`npm test` 能跑、种「故意失败断言」必红（非空跑绿）、禁词扫描与冻结页守卫工具可用；不破现有 build 与 frontend-run-detail 测试基线。
