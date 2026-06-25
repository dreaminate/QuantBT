---
uuid: e62a8933815144b9824e2eb8eb683059
title: 方法学控制面 6 档——strict/standard/loose/exploratory/custom/user_waived + MethodologyChoiceRecord（§10·系统提供用户运行时选）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: methodology
source: goal
source_ref: GOAL §10 方法学与验证(行 1543-1609·方法学控制面 6 档:strict/standard/loose/exploratory/custom/user_waived·系统给每个选择展示代价/证据缺口/适用环境/推荐路径/责任边界·user 选松紧或跳过·记 MethodologyChoiceRecord·按真实状态限制展示/晋级/导出/运行)
depends_on: []
---

# 方法学控制面 6 档（§10·系统提供·用户运行时选·不替用户拍）

## Scope [必填·先读 GOAL §10]
建 §10 **方法学控制面 6 档框架**——**系统提供给 user 运行时选的旋钮**（非我拍阈值）：① 6 档命名 strict/standard/loose/exploratory/custom/user_waived（GOAL 已命名·照建）② 每档展示**代价/证据缺口/适用环境/推荐路径/责任边界**（让 user 知情选）③ user 选松紧或跳过 → 记 **MethodologyChoiceRecord**（tradeoffs/recommendation/responsibility_boundary）④ **按真实状态限制展示/晋级/导出/运行环境**（user 放宽后系统继续交付·但不得把放宽结果标成强证据/理论已证明/生产可上线）。**阈值数值 = 用户可配（给文献默认·不替拍·不要管太宽）。**

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/methodology/`（control_plane.py：6 档枚举 + 每档代价/证据缺口/责任边界元数据 + MethodologyChoiceRecord + 真实状态限制门）。**复用** lineage/ids、已建 MethodologyChoiceRecord 若 spine 有(grep 实证·不另造)。**绝不碰** main.py、其他在飞线。

## 可证伪验收（种坏门必抓·§10）
1. user 选 loose/exploratory 后系统仍显 evidence sufficient/proof-backed/production-ready → 拒（MUT 放过→红·命门）。
2. 方法学松紧未记录 tradeoffs/recommendation/responsibility_boundary → 拒（MethodologyChoiceRecord 必含）。
3. user_waived 档资产进 proof-backed/evidence sufficient → 拒（§1 一致）。
4. 6 档齐 + 各档元数据齐 → 正常（系统提供 user 选·正路径不误伤）。

## 红线 [按需]
**方法学松紧=用户运行时选·系统提供不替拍**(不要管太宽)·放宽结果绝不标强证据/生产可上线(诚实)·复用 MethodologyChoiceRecord 不另造·扩展不替换·先读 GOAL §10 再动手·**阈值数值=用户可配不擅定**。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不替用户定阈值数值(给文献默认·可配)；不接 main.py；不建前端档位选择器(后端框架即可)。本卡只 6 档框架+MethodologyChoiceRecord+真实状态限制门。
