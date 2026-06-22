---
uuid: a11e2aa5ea0143c5bfca9204a921e516
title: 因子台三纯库 + 暴力遍历挖掘 — 前端设计+实装（GOAL §3，无 handoff 稿，D-DESK-EPIC F1=B 路 b）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend
source: interaction
source_ref: 2026-06-21 F1=B 用户拍板走 (b)（无 handoff 稿，leader 按 GOAL §3 + factor_factory 直接设计实装）
depends_on: [5e47b82f3ba847938f4000fadf9c2fb7, d11d1426c2a14372a12e655fcd459871, d5ea778c285a46e0872dba3a87ab1182, e2de3d323bef48f9a0cf5737aeb3a3b5]
---

# 因子台三纯库 + 暴力遍历挖掘 — 前端设计+实装（GOAL §3，无 handoff 稿，D-DESK-EPIC F1=B 路 b）

## Scope [必填]
handoff 设计稿缺 GOAL §3 两骨干；F1=B 用户拍板走 (b)，本卡按 §3 + 现有 `factor_factory` 后端**直接设计并实装**（不经 Claude Design）：① 三纯库分库 UI（算术暴力遍历库 / ML 库 / DL 库 三库纯净 + DL/ML 输出登记为「信号契约」进因子库的入口）；② 暴力遍历挖掘 view（生成器配置 + 守门器结果 + 诚实-N 计数，生成器/守门器严格解耦、守门指标绝不进生成 fitness）。视觉沿用因子台紫 accent + desk 地基，与 handoff 5 视图同源，挂进 F1 的因子台 sub-tab 框架。**不做**：后端三纯库/信号契约/挖掘引擎（归 F4 `51271d38`）、ML/DL 真训练（属 Model台）。

## 上下文 / 动机 [按需]
F1（`5e47b82f`）只还原 handoff 给的 5 视图（库/相关/评测/构建DSL/研究），缺 §3 骨干：三纯库结构（R17 两层 + 信号契约解耦：DL/ML 本体进模型注册表、输出登记为「信号」进因子库）、暴力遍历挖掘（R16 诚实-N 守门人，生成/守门解耦、守门指标不进 fitness）。用户拍板 F1=B 走 (b)：handoff 无稿，由 leader 按 §3 + factor_factory 现状直接设计实装、视觉同源。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/pages/workshop/factor/FactorDeskPage.tsx | F1 建的 5 sub-tab 框架 | 扩 2 sub-tab：三纯库 / 暴力遍历挖掘（不改现有 5 视图） |
| app/frontend/src/pages/workshop/factor/FactorPureLibsView.tsx | 新建 | 三库分库 UI + 信号契约登记入口 |
| app/frontend/src/pages/workshop/factor/FactorMiningView.tsx | 新建 | 暴力遍历挖掘：生成器配置 + 守门器结果 + 诚实-N 计数 |
| 后端缺口（实装在 F4 `51271d38`） | factor_factory 三纯库/信号契约/挖掘引擎 | F3 前端先 mock + MOCK 角标，真数据接 F4 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「把 .pt（DL 本体）当因子塞进因子库」→ 门必抓：拒（范畴错误，DL 本体进模型注册表，只有其输出登记为「信号」进因子库，R17）。变异要杀：UI 允许上传 .pt 直接入因子库。
2. 种「守门指标（IC/IR/DSR）泄进生成器 fitness 排序」→ 门必抓：生成器/守门器解耦，守门指标绝不出现在生成 fitness（R16 暴力遍历=诚实-N 守门人）。变异要杀：挖掘 view 用 IC 给生成候选排序。
3. 种「换等价公式 N_eff 计数不变」→ 门必抓：诚实-N 对等价写法收益聚类计数（沿用 T-015），不可被改写绕过。
4. 种「ML/DL 输出未走信号契约直接当因子用」→ 门必抓：两层解耦，必须经信号契约登记（R17）。

## 复用 [按需]
F1 的因子台 sub-tab 框架 + 紫 accent；G1 desk 壳件/token；G3 Inspector（挖掘结果详情）；现有 factor_factory 算术库（已建）；T-013/T-015 诚实-N 一本账概念。

## 红线 [按需]
三库纯净不混（算术/ML/DL）；守门指标不进生成 fitness（生成/守门解耦=架构红线）；诚实-N 不可手动改小；.pt 不入因子库（范畴红线）；MOCK 数据诚实角标。

## 非目标 [按需]
后端信号契约/ML-DL 登记/挖掘引擎守门归 F4；不实装 ML/DL 训练（Model台 M1/M2）；不碰算术 DSL 构建台（F1 已还原）。

## Open Questions（已决 2/2）[按需]
- [已决] 设计来源走 (b)：leader 按 GOAL §3 + factor_factory 直接设计实装，不经 Claude Design（D-DESK-EPIC F1=B）。
- [已决] 视觉沿用因子台紫 accent + desk 地基，与 handoff 5 视图同源；两骨干挂 F1 sub-tab 框架扩展。

## 验收一句话 [必填]
种「.pt 入因子库 / 守门指标进 fitness / 等价公式 N_eff 不变 / ML-DL 跳信号契约」四类坏 → 门必抓；三纯库+挖掘 view 落地不破因子台 5 视图（F1）基线。
