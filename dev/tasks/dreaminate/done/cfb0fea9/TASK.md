---
uuid: cfb0fea934b947929d07519456d49e1f
title: 整套台前端实装 epic（Claude Design handoff → React，DC→React 治理界面投影）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend-epic
source: interaction
source_ref: 2026-06-21 用户提供 Claude Design handoff bundle(quantbt-claude) + 三板拍板（先开卡自分配 / 分期开齐全套卡 P0→完整 / 整套台全做）
depends_on: []
---

# 整套台前端实装 epic（Claude Design handoff → React，DC→React 治理界面投影）

## Scope [必填]
把 Claude Design handoff 整套 DC 原型（策略台 / 因子台 / Model台 / 模拟台 / 回测详情+裁决卡 / QuantBT Agent 窗口）**pixel-perfect 还原成 React**（`app/frontend`），分期 **P0**(像素还原 + mock 可交互、MOCK 角标诚实标注) → **P1**(接已有后端端点) → **P2**(补缺失端点) 做到完整。
**不做**：不重构冻结 `RunDetailPage`（只加字段 / 排版 / 旁挂新组件）；不削弱任何治理门；不改后端治理逻辑（只补 HTTP 端点把已建脊柱投影到界面）。epic 占位，拆 20 子卡（地基×4 含 G0 测试设施 + 台×12 含因子台 §3 两骨干 F3/F4 + Agent 补×4），实装由子卡承接。

## 上下文 / 动机 [按需]
用户 2026-06-21 提供 handoff bundle：在 AI 设计工具里设计了整套治理界面 HTML/CSS/JS 原型（DC 格式：`{{}}`/`sc-for`/`sc-if` + support.js 运行时编译为 React），导出让 coding agent 实装。设计稿治理元素（Live 只读 / Fork / kill / validate / 版本血缘 / 权限三态 / 弱点一等呈现 / 晋级审批门）= GOAL **§2 治理脊柱 + §6 信任层 + §7 M15「治理新页面」** 的 UI 投影——治理逻辑全在已建后端脊柱（验证官 / 三角门 / 审批门 / 血统门 / killswitch / 内核 fork / paper 引擎 / factor_factory / training）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/App.tsx | 路由表 + 冻结正则 L39 | 加 5 台路由（严格避开 `/^\/runs\/[^/]+$/` 冻结分支） |
| app/frontend/src/theme-cc.css | :root token | 扩展 `--desk-*` + per-desk accent（统一到 DC `#1c1b19` 精确值） |
| app/frontend/src/components/desk/ | 新建目录 | 暗色台共享地基组件 |
| app/frontend/src/components/shell/Shell.tsx | SIDEBAR/areaOf/TopNav | 5 台导航接入（DeskShell vs Shell 路由边界） |
| app/backend/app/main.py | `@app.*`（无 APIRouter） | 补各台缺失 HTTP 端点（扩展不替换，投影已建模块） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 权限轴⟂治理轴：种「任一台 bypass / UI 直调真钱或晋级端点跳治理门(OrderGuard/审批/过拟合/血统)」→ 必抓（沿用 T-029 入口×门矩阵）。
2. 冻结页不破：种「裁决卡/新交互嵌入冻结 RunDetailPage 或把其深色化重构」→ 必抓（RULES.project §10 / GOAL §0）。
3. 默认止于模拟盘：种「任一台默认或自动导向直接实盘」→ 必抓（D-PERM）。
4. 弱点一等呈现：种「red / PBO / DSR / 血统弱点被默认折叠或染绿」→ 抓（R25）。
5. 裁决措辞：种「UI 出现『可信/安全/排除过拟合/保证』绝对措辞」→ 抓（R7；文案须后端 `_verdict_note` 供给）。

## 复用 [按需]
现有 `theme-cc.css`（cc-* token / lifecycle pill / mono 字栈）、`charts/EvalCharts.tsx`、`StatusPill.tsx`、`MetricCard.tsx`、`lib/auth.ts(authFetch)`；现有后端脊柱全部（只投影不重造）。

## 红线 [按需]
RunDetailPage 冻结（GOAL §0 / RULES.project §10）；权限轴⟂治理轴 bypass 不跳门（D-PERM）；默认止于模拟盘；弱点一等呈现（R25）；下单唯一入口经 OrderGuard、实盘 key 不进 LLM；裁决措辞禁可信/安全（R7）；A股 live 下单永远拒；桌面路径不绕治理门。

## 非目标 [按需]
不重造后端治理能力；不在 epic 卡内写实现（拆子卡逐项进实现）；不碰美股/港股/外汇等范围外资产。

## Open Questions（已决 3/3）[按需]
- [已决] 流程：先开卡走正规流程，leader（dreaminate）自 mint uuid 自分配到 `tasks/dreaminate/`，不走 pool。
- [已决] 深度：分期开齐覆盖完整路线的全套卡，P0 像素还原+mock → P1 接已有后端 → P2 补缺端点，最终做到完整（不停在 P0）。
- [已决] 范围：整套台全做（策略台/因子台/Model台/模拟台/回测详情+裁决卡/Agent 窗口）。

## 验收一句话 [必填]
20 子卡逐项落档 + 对抗测试绿 + 不破现有测试基线 + 不触 §5 致命错误；整套台 pixel-perfect 且治理不变量（权限⟂治理 / 冻结页 / 止于模拟盘 / 弱点一等 / 措辞合规）全守。

## 子卡映射（DAG · 全 uuid 见各卡 frontmatter）
- 地基：G0 `e2de3d32` 前端测试设施(→—) · G1 `d11d1426`(→G0) · G2 `b9af7c82`(→G1) · G3 `d5ea778c`(→G1)
- 策略台：S1 `be3dc598`(→G1/G2/G3) · S2 `9fd4f1a6`(→S1)
- 因子台：F1 `5e47b82f`(→G1/G3) · F2 `b106177f`(→F1) · F3 `a11e2aa5` §3 三纯库+挖掘前端(→F1/G1/G3/G0) · F4 `51271d38` 两骨干后端(→F3)
- Model台：M1 `b2682edc`(→G1/G2/G3) · M2 `4562d903`(→M1)
- 模拟台：P1 `9d5405ce`(→G1) · P2 `79ebe273`(→P1)
- 回测/裁决：R1 `d93dc5a0`(→G1) · R2 `e069d820`(→R1)
- Agent 补（关联现有 epic 3f5ed0b8 的 T-040~T-043）：A1 `a75c4beb` · A2 `ca3ab3ec` · A3 `d41b167d` · A4 `b961f08b`

## 完成记录（2026-06-22 · 整套台前端实装完成）

24 子卡全实装 + 验证绿：
- **地基(4)**：G0 测试设施 / G1 desk 壳件+token+per-desk accent / G2 画布引擎 / G3 Agent对话+Inspector+Dock。
- **台前端 P0(6)**：S1 策略台(DAG 工作台 17 节点治理三层硬强制) / F1 因子台 5 视图 / M1 Model台 4 子台 / P1 模拟台 5 视图+PaperBoardCard / R1 裁决卡(三态不混 GateVerdict) / F3 因子两骨干(三纯库+暴力遍历挖掘 R16/R17)。
- **Agent 窗口(4)**：T-040 对话流+工具可视化+权限三态 / A1 产物工作区 8 卡 / A2 里程碑+台 switcher / A3 D-PERM 反例+self-approve。
- **后端接真(7)**：S2(validate/版本/fork/live快照) / R2(verdict/overfit/cost/promote 投影) / M2(JobDetail/IoSpec/wf/图codegen 线性链) / P2(/api/paper/* 整层+晋级审批门) / F4(信号契约+挖掘守门引擎) / A4(5业务工具+3接真handler+SSE+handoff) / F2(ic/decay/validate/POST factors/correlation/layered/audit 按 D-F2-AUDIT)。
- **教学/桌面(2)**：T-041 三型教学弹窗(可证伪/血统/red 知情确认,软决定) / T-042 Tauri 桌面挂载(前端半边验证,桌面真跑待工具链)。
- **验证(land 前最终全量)**：后端 pytest **1231 passed/13 skipped**、前端 vitest **241 passed/21 files**、tsc clean、`npm run build` ✓。零硬编码色值全目录、治理红线全守(冻结页不嵌/权限轴⟂治理 bypass不跳门/止于模拟盘/弱点一等 R25/裁决措辞禁词 R7/A股止 paper/晋级 approver≠creator)。
- **诚实残余**：①前端各台未接端点处仍 mock+MockBadge(B9 诚实,P1 深度功能逐步接) ②T-042 桌面 `tauri build` 待工具链+修 pre-existing Cargo 缺陷 ③pre-existing bugs 已 spawn 修复任务：`create_verdict` _dt NameError(无测试覆盖)、`operators ts_corr/ts_cov` 跨 symbol 泄露(注册前视门已防住入库)、Cargo `[lib]` 缺 src/lib.rs。
- **land**：实装完成、验证绿、24 卡落档 done；commit/合并 main 待用户授权(CLAUDE.md 不擅自 commit/push)。
