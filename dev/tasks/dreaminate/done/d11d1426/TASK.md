---
uuid: d11d1426c2a14372a12e655fcd459871
title: 暗色台地基 — desk 壳件 + design tokens + per-desk accent + 路由边界
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: frontend-foundation
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（跨台共享地基分析）
depends_on: [e2de3d323bef48f9a0cf5737aeb3a3b5]
---

# 暗色台地基 — desk 壳件 + design tokens + per-desk accent + 路由边界

## Scope [必填]
建暗色 5 台（策略/因子/Model/模拟/Agent）共享的前端地基：① `components/desk/` 壳件（DeskShell 四栏壳 / DeskTopBar 含红绿灯点+字标 / DeskSwitcher 台切换 / SegmentedControl / SubTabBar / CollapsiblePanel 竖排折叠 / Pill / StatusDot 脉冲 / MockBadge）；② `theme-cc.css` 扩展 `--desk-*` token 子集（统一到 DC 精确值 `#1c1b19/#201f1c/#302d29/#1d1c19/#191815/#161512`）+ per-desk accent CSS 变量（`--desk-accent` 由路由注入：策略橙/因子紫/Model蓝/模拟绿/Agent橙）；③ `cssToObj` helper + `style-hover`→CSS `:hover` 方案；④ 定路由边界（哪些 path 进 DeskShell vs 现有 Shell）。**不做**：不实装任何具体台业务、不动现有 Shell 行为。

## 上下文 / 动机 [按需]
跨台共享分析：暗色 5 台共享一套 design system，唯一差异是 per-desk accent；现有 `Shell.tsx` 是路由式后台壳，与 IDE 四栏壳是两种壳，须平行新建不可改造复用。地基是全部台卡的前置。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/theme-cc.css | :root[data-theme] L17-83 | 新增 `--desk-*` token + per-desk accent（不改现有 `--cc-*`，统一深色精确值） |
| app/frontend/src/components/desk/ | 新建 | DeskShell/DeskTopBar/DeskSwitcher/SegmentedControl/SubTabBar/CollapsiblePanel/Pill/StatusDot/MockBadge |
| app/frontend/src/lib/ | 新建 cssToObj.ts | DC `style="{{s}}"` → React style 对象 helper（对齐 support.js cssToObj 语义） |
| app/frontend/src/App.tsx | 路由 L39 冻结正则 | 预留 DeskShell 路由分支（不动冻结分支） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. token 不漂：种「desk 组件硬编码十六进制色值绕过 `--desk-*` token」→ lint/测试必抓（防与全站主题双源漂移）。
2. accent 隔离：种「某台 accent 泄漏成全局 `--cc-accent` 污染其它路由」→ 抓（per-desk 必须 scoped）。
3. 不破现有 Shell：种「DeskShell 改动影响现有 `/runs //workshop` 等 Shell 路由渲染」→ 现有页快照测试必抓。

## 复用 [按需]
`theme-cc.css`（cc-* token 骨架、lifecycle pill、mono 字栈、响应式断点）；`StatusPill.tsx`（status→label map）。

## 红线 [按需]
扩展不替换（RULES §4）：theme-cc 只加不改现有 `--cc-*`；现有 Shell 零回归。

## 非目标 [按需]
不实装画布引擎（→ G2）、不实装 Agent 对话/Inspector/Dock（→ G3）、不实装任何具体台。

## Open Questions（已决 1/1）[按需]
- [已决] per-desk accent 用单 CSS 变量 `--desk-accent` 由路由注入（非 4 个静态 class），DeskSwitcher/StatusDot/Pill 全链读它。

## 验收一句话 [必填]
desk 壳件渲染像素对齐 DC token、accent per-desk 隔离、现有 Shell 路由零回归；种硬编码色值/accent 泄漏门必抓。
