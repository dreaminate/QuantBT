---
uuid: b2682edc2c3b4170a28df7baf150a4ed
title: Model台前端 P0 — 4 子台像素还原 + mock(作业/注册表/构建draw.io/研究)
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871, b9af7c82ef4c4ea6bfd1e3b6fc4d9219, d5ea778c285a46e0872dba3a87ab1182]
---

# Model台前端 P0 — 4 子台像素还原 + mock(作业/注册表/构建draw.io/研究)

## Scope [必填]
在单路由 `/training` 内做 4 个互斥 sub-tab（作业台/模型库/构建台/研究台）的像素级还原：增强既有 TrainingBenchPage(作业看板)+ModelLibraryPage(注册表富卡+晋级门)、新建构建台(draw.io 式图编辑器，渲染用 G2)+研究台；蓝 accent(#6f9bd1)，全部数据走 mock 并打 MOCK 角标；**不做** 图→代码真 codegen(归 M2)、不在任何路径触发 torch、不补后端字段(P1 另卡)。

## 上下文 / 动机 [按需]
设计稿 `/tmp/qbt-handoff/quantbt-claude/project/Model台.dc.html`(1931 行)是四子台单页 SPA，用 `state.view` 在 `jobs/registry/build/research` 切换。落地选「单路由 `/training` 内 sub-tab」(贴合设计稿状态机、四子台共享 family/stage 配色与台切换器、App.tsx 路由不动)；`/models` 旧路由后续可重定向到 registry tab。Model台故意用蓝 `#6f9bd1` 作台标识主色(区别策略台橙)，橙降为辅色(✳/loss train 线/why 左边框/user `>`)。本卡是 P0 前端骨架：作业台/模型库走「复用已有后端 + 富卡」，构建台/研究台先做交互 + 前端 mock，治理三线(晋级门字段/防泄露诚实标注/M6 子进程)必须在前端就钉死，不能等后端。依赖 G1 d11d1426 / G2 b9af7c82 / G3 d5ea778c(布局/图渲染/设计 token 三个底座先就绪)。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/frontend/src/App.tsx` | L71 `<Route path="/training" element={<TrainingBenchPage/>}/>` | 不新增路由；TrainingBenchPage 内挂 4 sub-tab 视图开关(view=jobs/registry/build/research)；L72 `/models` 保留，后续重定向 registry(本卡不动) |
| `app/frontend/src/pages/models/TrainingBenchPage.tsx` | 整页(route `/training`) | 扩展为四子台容器 + 作业台看板(队列/实时曲线/算力卡/CV folds/动机文档/助手)；既有「配置→提交」三栏收进「＋新建训练」抽屉；复用 EvalCharts/codegen 预览并入 dashboard |
| `app/frontend/src/pages/models/ModelLibraryPage.tsx` | 整页 | 扩展为 registry 子台：2 列富卡 + stage 胶囊 + 晋级门面板 + DRILL-IN 浮窗(动机/IO/walk-forward 逐窗)；mock 数据填充，stage 默认展开不折叠 |
| `app/frontend/src/pages/models/ModelBuildPage.tsx` | 新建(build 子台组件) | draw.io 式图编辑器：节点/连线/缩放/平移/框选/模块嵌套/代码面板；图渲染用 G2(b9af7c82)；codegen 为前端 mock 动画(产 bdCodeSnap)，「▷跑训练」只落 mock 作业、**不发任何编译/训练请求** |
| `app/frontend/src/pages/models/ModelResearchPage.tsx` | 新建(research 子台组件) | 理论判定卡 + 论文列表 + 公式工作台；judgement/LLM 提炼全 mock；文章观点结论强制导向「先去因子台 IC+单调+OOS 检验」文案(对齐 M11) |
| `app/frontend/src/components/charts/EvalCharts.tsx` | 既有共享组件 | loss 双线(train 橙实线/val 蓝虚线)、val 面积图复用并入作业台 dashboard，按设计稿 viewBox/色值映射 |
| `app/backend/app/main.py` | L481 `promote_model` / L532 gate approve | 晋级门「批准」按钮的 payload 必须带 `approver`/`reason`/`risk_restated`(L535-536 读取)；前端不可省，否则后端 422 |
| `app/backend/app/approval/schema.py` | L22 `ApproverEqualsCreator` / L30 `EmptyReason` | 后端真红线锚点：approver==creator 或 reason 空 → 422；前端晋级门表单按此设计必填项 |
| `app/backend/app/training/runner.py` | L41 `run_code()`(子进程) | M6 锚点：本卡构建台「跑训练」是前端 mock，**不得**绕过此子进程入口直跑 torch；前端代码注释钉死「真编译走 runner 子进程，本卡不实装」 |

(色值映射依据：`#9bbd5a`→`--cc-success`、`#6f9bd1`→`--cc-info`/Model accent、`#d9b25f`→`--cc-warning`、`#d97066`→`--cc-danger`；G3 d5ea778c 提供 token 底座，新增机制青 `#6fb0c8`/模块紫 `#b89cd8`/TB 橙 `#e6883a` 走 G3。)

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种<晋级门「✓批准晋级」按钮发出的 payload 缺 `approver`(或 approver==creator)/`reason`/`risk_restated`> → 门必<后端 `main.py` L532 gate approve 返回 422(`ApproverEqualsCreator`/`EmptyReason`，schema.py L22/L30)，前端不静默吞错、不假装翻 stage 成功>。变异要杀：把前端表单这三个必填字段任一改成可选/默认透传 creator → 测试必红。
2. 种<防泄露元素 Purged k-fold/embargo 1%/walk-forward 逐窗 OOS 被渲染成假绿(染绿、折叠藏起、或缺「防标签穿越/严格无泄露」标注)> → 门必<弱点一等呈现门抓出:这些块默认展开、不染绿、保留诚实徽章(R25)，OOS/in-sample 区分可见>。变异要杀:把 walk-forward「8/8 窗口正」恒绿、或把 embargo 卡折叠默认隐藏 → 测试必红。
3. 种<构建台「▷跑训练」或图编译在主进程触发 torch / 发真编译训练请求> → 门必<M6 门抓出:本卡该按钮只落 mock 作业、零 torch import、不打 codegen/train 端点;真编译须走 `runner.py` L41 子进程(本卡非目标)>。变异要杀:把 mock codegen 偷偷换成调 `/api/training/codegen` 或 import torch → 测试必红。
4. 种<mock 数据(作业曲线/注册表卡/judgement)未打 MOCK 角标，混充真实后端数据> → 门必<MOCK 诚实角标门抓出:四子台所有 mock 来源可视标注>。变异要杀:删除某子台 MOCK 角标 → 测试必红。

## 复用 [按需]
- `EvalCharts.tsx`(loss/val 图)、既有 codegen 预览组件 → 并入作业台 dashboard。
- G1 d11d1426(布局骨架/折叠栏/分栏拖拽)、G2 b9af7c82(图渲染/节点/连线/缩放，构建台直接用)、G3 d5ea778c(设计 token/cc 变量 + 新增子台标识色)。
- 既有 `ModelLibraryPage` 的 `/api/models` 列表 + 版本表逻辑 → registry 富卡基座。

## 红线 [按需]
- 权限轴⟂治理轴:构建台/研究台的 agent「先确认再动手」绝不跳晋级审批门/过拟合门/血统门;agent 只能卡内选(对齐 `/api/training/agent_context`)。
- 弱点一等呈现(R25):red/PBO/DSR/血统/OOS/walk-forward 默认展开、不染绿、不折叠;裁决措辞禁「可信/安全/排除过拟合/保证」(R7)，文案走后端 `_verdict_note`，前端不自造结论。
- 默认止于模拟盘;实盘 key 不进 LLM(构建台 LLM 试一条仅 mock 文本)。
- 晋级 approver≠creator + reason + risk_restated(INV-5)，前端表单必填、不可裸翻。
- 主进程不碰 torch(M6):本卡零 torch、零真 codegen。

## 非目标 [按需]
- 图→代码真 codegen / 真编译训练(归 M2，须走 runner 子进程)。
- 后端补字段:JobDetail 富文档 / ModelCard IoSpec / walk-forward 逐窗端点 / pause 端点 / 研究台判定端点(P1 另卡)。
- TensorBoard 真 iframe 嵌入(本卡 SCALARS 为 mock 曲线，HISTOGRAMS/GRAPHS/HPARAMS 占位)。
- `/models` 旧路由重定向到 registry tab(后续)。
- RunDetailPage 任何改动(冻结)。

## Open Questions（已决 D/总）[按需]
- [已决] 路由用单 `/training` 内 sub-tab(方案 a)，非拆 4 路由 —— 贴合设计稿 view 状态机、共享配色/数据/台切换器，App.tsx 不动。
- [已决] 本卡所有数据 mock + MOCK 角标;真后端对接(jobs/eval/promote)与后端补字段为后续卡。
- [已决] 构建台 codegen「跑训练」为前端 mock，零 torch、不打编译/训练端点;真编译走 M2 + runner 子进程。

(D/总 = 3/3，主控跑 build_card_counters 重算)

## 验收一句话 [必填]
种「晋级门缺 approver≠creator/reason/risk_restated」「防泄露块假绿/折叠」「构建台跑训练触发 torch 或真 codegen」「mock 无角标」四类坏 → 对抗门必全抓(后端 422 / 弱点一等门 / M6 子进程门 / MOCK 角标门)，且不破现有 TrainingBenchPage·ModelLibraryPage·EvalCharts 测试基线。
