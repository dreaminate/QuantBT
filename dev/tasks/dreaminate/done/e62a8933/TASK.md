---
uuid: e62a8933815144b9824e2eb8eb683059
title: 方法学控制面 6 档——strict/standard/loose/exploratory/custom/user_waived + MethodologyChoiceRecord（§10·系统提供用户运行时选）
status: done
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

## 完成记录（2026-06-26 · deep-opus 任务线 · 分支 wave7/methodology-plane · 🟡 待中心整合/全量/land）

### 建了什么（greenfield·扩展不替换·绝不碰在飞线）
- 新包 `app/backend/app/methodology/`（`control_plane.py` + `__init__.py`）。零改动既有文件——git status 仅三个新增路径。
- **6 档枚举** `MethodologyTier(str, Enum)`：strict / standard / loose / exploratory / custom / user_waived（照 GOAL §10 行 1568-1575 命名，`ALL_TIER_VALUES` 与 GOAL 逐字对齐）。
- **每档元数据** `TierProfile`（`TIER_PROFILES` 6 条）：展示 GOAL §10 五面——代价 / 证据缺口 / 适用环境 / 推荐路径 / 责任边界，**全质性、不含统计阈值数值**（阈值=用户可配，本模块不烤死 PBO/DSR/t/CPCV 折数）。
- **MethodologyChoiceRecord 复用不另造**：`build_methodology_choice()` 物化的是 `app.lineage.spine.MethodologyChoiceRecord`（测试 `test_reuses_lineage_record_not_another` 断言 `cp.MethodologyChoiceRecord is spine.MethodologyChoiceRecord`；smoke 实证 `__module__ == app.lineage.spine`）。grep 实证 spine 已建该类 + 标签阶梯（STRONG_LABELS / WAIVER_LABELS / 各 LABEL_*），全 import 复用。
- **真实状态限制门**（GOAL §10 四面）：`constrain_promotion`（晋级）/ `effective_label`（展示+导出 cap 原语）/ `assert_label_honest_for_export`（导出硬挡）/ `production_eligible`+`runtime_environment_ceiling`（运行环境）。
- **互补不替换 spine_gate**（关键设计）：spine 的 proof-honest 子句只挡 PROOF_REQUIRING_LABELS（proof_backed/production_ready），**不挡 evidence_sufficient**；故放权全绿资产在 spine 单门下仍可拿 evidence_sufficient（测试 `test_spine_gate_alone_misses_evidence_sufficient_under_waiver_controlplane_catches` 实证 spine 单门 `promotable is True`）。控制面补上更宽一层：放宽档一律不得触及任一强标签。

### 验证（scoped·🟡 全量由中心跑）
- **新测试 `tests/test_methodology_control_plane.py`：68 passed / 0 failed**（含 4 条可证伪门 + 复用单一源 + spine 互补 + 裁决不越权 + effective_label 幂等）。
- **基线不破**：collect-only 2285（main 基线）→ 2353（+68，净增=新测试数，零回归）。spine+orchestrator 集成面 75 passed（我依赖/复用的面未破）。
- **MUT 实证门有真牙（绝不 git checkout·Edit 种坏→Edit 还原）**：① 关门① `if relaxed and strong and False` → 15 命门测试变红（放宽档被放过强标签）；② 门② `documentation_gaps` 提前 `return ()` → 4 留痕测试变红。两次还原后全绿、源码无 MUT 残留（grep `MUT:` clean）。
- compile OK；`validate_profiles()` 通过（6 档齐+结构一致，门④正路径不误伤）。

### 红线合规（逐条）
- 复用 MethodologyChoiceRecord 不另造 ✅（同一类对象，测试钉死）｜扩展不替换 ✅（仅新增三路径）｜阈值=用户可配不擅定 ✅（元数据全质性，无统计阈值）｜放宽结果不标强证据/生产可上线 ✅（cap+导出守门+裁决口径自检禁越权词）｜无新公式不强造 MathematicalArtifact ✅（本卡零 artifact）｜不碰 main.py/state/log/board/其他卡 ✅。

### 诚实残余（🟡≠✅）
- **未跑全量后端套件**（按卡「只跑 scoped 不跑全量」），全量绿由中心跑；当前证据=新测试 68 passed + 集成面 75 passed + collect 2353 无回归。
- **消费侧未接线**（本卡领地只到「后端框架」，非目标明列）：控制面尚未被 RDP / run 管线 / 前端档位选择器消费——`rdp.py` 已有 `methodology_choice_refs` 槽位但接线是另一条线/follow-on（碰 main.py 超本卡领地）。本模块不暗示已被生产消费。
- **standard 档不 cap 强标签**=设计取舍（非疏漏）：GOAL §10「放宽」语义只覆盖 loose 及更松；standard 是默认基线、strict 在其上，二者非「放宽」故不 cap，仅 recommended_path 提示真钱/对外升 strict（符合 memory「提供流程不强加选择」）。若中心认为 standard 也应 cap production_ready → 属阈值/政策面，留中心拍。
- **loose 与 exploratory 的诚实降级标签都落 LABEL_EXPLORATORY**：二者在 chosen_path（档名）层无损可分，仅输出标签上限同为 exploratory（loose 运行=探索级声明）。
