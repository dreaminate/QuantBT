---
uuid: 9d5405ce121d4f98bf3dbc9e1014947b
title: 模拟台前端 P0 — 5 视图 + PaperBoardCard(运行/持仓成交/风险门/复盘/晋升)
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871]
---

# 模拟台前端 P0 — 5 视图 + PaperBoardCard(运行/持仓成交/风险门/复盘/晋升)

## Scope [必填]
新建 `app/frontend/src/pages/workshop/PaperDeskPage.tsx`（路由 `/paper`）像素还原 `模拟台.dc.html` 全 5 互斥视图（运行盘 / 持仓与成交 / 风险门 / 复盘归因 / 晋升通道）+ 抽 `components/PaperBoardCard.tsx` 共享卡（还原 `PaperBoard.dc.html`，供模拟台 RUN view 与他台复用），全部 mock 数据 + MOCK 角标、绿 accent `#9bbd5a`；**不做**：不塞进 BinanceTradingPage（职责=真钱密钥/网络切换，不同域）、不接任何 `/api/paper/*` 后端（归 P2）、不实装 start/stop/kill switch 运行控制（设计稿是只读 dashboard）。

## 上下文 / 动机 [按需]
模拟台是 live ladder 的 **paper 段**（运行/持仓/风险门/复盘/晋升），与 BinanceTradingPage 的真钱阶梯段（testnet→mainnet）相邻但不重叠。设计稿 `模拟台.dc.html`(44KB 全页) + `PaperBoard.dc.html`(6.5KB 嵌入卡) 视觉/数据语义同源（前者运行盘是后者的全页展开版），落地抽成共享卡复用。本卡只做前端像素还原 + mock，后端整层 `/api/paper/*` 路由属 P2。理解材料：`/tmp/qbt-paperDeck.md`；设计稿 `/tmp/qbt-handoff/quantbt-claude/project/模拟台.dc.html`、`PaperBoard.dc.html`。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/pages/workshop/PaperDeskPage.tsx | 新建 | 模拟台全页：DeskShell(模拟绿 accent) + 5 视图 sc-if 互斥(run/book/risk/review/promo) + run list 侧栏 + 台 switcher / market switch；本地 mock state(view/market/selRun/listOpen/promoted)，零后端调用 |
| app/frontend/src/components/PaperBoardCard.tsx | 新建 | 共享嵌入卡(metrics + 净值缩略 svg + top持仓 + 风险门 4 格 + 「会话外不可改」脚注)；纯展示无 handler；模拟台 RUN view 复用它，实盘段统一绿 `#9bbd5a` |
| app/frontend/src/App.tsx | route 表 L62-69(workshop 块) + 冻结正则 L39 | 在 workshop 块新增 `<Route path="/paper" element={<PaperDeskPage />} />` + 顶部 import；不动 `/runs/:runId` 冻结分支 |
| app/frontend/src/components/shell/Shell.tsx | `SIDEBAR_BY_AREA.workshop` L25-34 + `areaOf()` L390-400 | sidebar workshop 数组加 `{to:"/paper", label:"模拟台", icon:"▦"}`；`areaOf()` workshop 分支加 `pathname.startsWith("/paper")`（否则 `/paper` 落不到 workshop sidebar） |
| app/frontend/src/components/desk/ (G1 产出) | DeskShell/DeskTopBar/DeskSwitcher/SubTabBar/CollapsiblePanel/StatusDot/MockBadge/Pill | 直接 import 复用，不重造；`--desk-accent` 由 `/paper` 路由注入模拟绿 `#9bbd5a` |
| app/frontend/src/lib/cssToObj.ts (G1 产出) | helper | DC `style="{{s}}"` → React style 对象，svg 路径/动态门色用它 |

## 对抗测试设计（种已知 bug，门必抓）[必填]

1. 种「UI 出现 A股 live 下单按钮 / 任何把 paper 持仓导向真实交易所下单的入口」→ 门必抓：`/paper` 全 5 视图渲染后断言 DOM 无 live 下单 control，且侧栏/RISK footer/PaperBoardCard 脚注三处「A股止于 paper · 唯一硬墙在交易所侧远程信任域」文案在场（钉 R13 + RULES「A股 live 下单永远拒」=致命错误）。变异：把脚注删一处或文案弱化为「已安全放行」→ 必杀。
2. 种「RISK view 风险门 cur/limit 字段被做成 input / 可点编辑 + 缺 🔒冻结标记」→ 门必抓：断言门格全 readonly（无 input/contentEditable）、🔒冻结 在杠杆/回撤熔断硬门在场、`永不可改` 文案存在（钉 GOAL §2 deny-by-default + INV「不削弱安全不变量」=权限轴⟂治理轴）。变异：给某门加 onChange handler → 必杀。
3. 种「PROMO 晋级审批 `pm_approve` 在 `eligible` 时自动晋级 / 缺人工点击 / 缺验证背书显示」→ 门必抓：断言审批为显式人工三态按钮(可点/已晋级只读/灰禁)、自动不触发、UI 标注 approver≠creator + 验证背书(INV-5)；未点击时 `promoted` 恒 false（钉 INV-5「晋级 approver≠creator + 验证背书」+ §5 不可跳级）。变异：把 `pm_approve` 改成 useEffect 自动 setState({promoted:true}) → 必杀。
4. 种「REVIEW 实盘衰减(decay 劣化)/RISK 违规弱点被染绿或折叠藏起」→ 门必抓：断言 decay 劣化值用警告/红(`#d9b25f`/`#d97066`)非绿、违规日志默认展开不折叠、衰减/违规区不可被 collapse 隐藏（钉 R25 弱点一等呈现·不染绿不折叠）。变异：把劣化 decayColor 改成绿 `#9bbd5a` 或给违规日志套默认 collapsed CollapsiblePanel → 必杀。

## 复用 [按需]
G1 (d11d1426) 全部 desk 壳件（DeskShell 四栏 / DeskTopBar / DeskSwitcher / SubTabBar / CollapsiblePanel / StatusDot 脉冲 / MockBadge / Pill）、`theme-cc.css` 的 `--desk-*` token + `--desk-accent` 注入机制、`lib/cssToObj.ts`。沿用 `components/StatusPill.tsx`（status→label）与 `components/MetricCard.tsx` 语义（如适配）。净值 svg 缩略图逻辑由 PaperBoardCard 与 RUN view 共享一份。

## 红线 [按需]
- 权限轴⟂治理轴：任何 bypass / agent 自驱都不得跳 OrderGuard / 审批门 / 过拟合门 / 血统门——本卡 PROMO 审批必经人工 + 背书。
- 默认止于模拟盘：PROMO 终点 OBSERVATION，不在本页导向直接实盘下单。
- 弱点一等呈现(R25)：red/PBO/DSR/血统/实盘衰减/违规默认展开、不染绿、不折叠藏起。
- 裁决措辞(R7)：禁「可信/安全/排除过拟合/保证」；判定/衰减措辞走材料给定文案，不本地编正面话术。
- MOCK 诚实：全页 MockBadge 角标在场，不假装真实数据。

## 非目标 [按需]
- 不接 `/api/paper/*`（status/start/stop/runs/fills/equity/审批端点全归 P2）。
- 不实装 start/stop/重启调度器 / kill switch / 暂停 run 的 handler（设计稿无）。
- 不动 BinanceTradingPage（真钱阶梯段，独立卡）。
- 不动 RunDetailPage 冻结分支、不改现有 Shell 行为/`--cc-*` token。
- PROMO→真钱阶梯(testnet→mainnet)的衔接跳转设计稿未画，不在本卡。

## Open Questions（已决 D/总）[按需]
- [已决] 路由用 `/paper`（非 `/simulator`），落 workshop area sidebar（依 G1 路由边界 + 现有 workshop 分组）。
- [已决] 实盘净值段统一用绿 `#9bbd5a`（模拟台 vs PaperBoard 设计稿橙绿不一致，取绿，对齐「模拟盘运行中」语义）。
- [已决] PaperBoardCard 抽为独立共享卡、模拟台 RUN view 复用它（非各自自绘）。
- [已决] 全 mock + MockBadge，不接后端（P2 分界）。

## 验收一句话 [必填]
种「A股 live 下单入口出现 / 风险门可编辑 / 晋级一键自动 / 弱点染绿折叠」四类坏 → 对抗门各自必抓，且 `/paper` 上线后现有 Shell 路由(`/runs //workshop` 等)快照零回归、RunDetailPage 冻结分支与 `--cc-*` token 不破基线。
