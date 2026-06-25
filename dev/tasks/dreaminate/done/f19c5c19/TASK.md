---
uuid: f19c5c192f4a44cc95fd159ea04d94e5
title: QRO 统一对象信封 + 状态六轴（四核心轴不混单绿灯）——对象脊柱地基（A-QRO-1）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: qro
source: goal
source_ref: GOAL §1 统一对象模型（QRO/Quant Research Object）+ 头号 gap #1 + 施工图 LINE-A 首卡
depends_on: []
branch: wave2/line-a-qro-1
---

# QRO 统一对象信封 + 状态六轴（A-QRO-1）· 完成卡

## Scope（交付内容）
头号 gap #1 主轴第一砖。theory/methodology 对象（MathematicalArtifact/TheoryImplementationBinding/
ConsistencyCheck/MethodologyChoiceRecord）已在 `lineage/spine.py`，但资产（factor/model/signal/
strategy）散落、无共享信封。本卡交付 **QRO 统一信封** + **状态轴枚举** + **收编现有资产**，全部在
greenfield `app/backend/app/qro/`，**收编只读**（不改 spine/ids/verification/factor_factory）。

## 新建文件（greenfield·只动 qro/ + 自己的测试/done 卡）
- `app/backend/app/qro/envelope.py` — QRO 信封 dataclass（GOAL §1「必须包含」字段全列）+ actor 四类枚举
  + 状态六轴枚举 + 语义边界（库成员资格 + 复用 R17 范畴门）+ 单绿灯硬门 `axis_clearance` + 收编适配器。
- `app/backend/app/qro/__init__.py` — 公共 API 再导出。
- `app/backend/tests/test_qro_envelope.py` — 49 条对抗式测试。

## 实现要点

### 1. QRO 信封 `QualifiedResearchObject`（frozen·内容寻址·同 spine.py 范式）
- 字段照 GOAL §1「各对象共享。这些必须包含」全列：identity / version / owner / actor / typed_contract /
  market·universe·horizon·frequency / event_time·known_at·effective_at / lineage / implementation_hash /
  assumptions / known_limits / failure_modes / validation_plan / evidence_refs / mathematical_refs /
  methodology_choice_ref / responsibility_boundary / theory_implementation_binding / consistency_verdict /
  verdict / permission / approval / allowed_environment / monitor·alert·retire_rules / lifecycle。
- **身份单一源**：`identity = "qro_" + content_hash({object_type, natural_key})`，复用 `lineage.ids.content_hash`
  （决策 S1/S4），前缀范式同 spine.py 的 `math_`/`tib_`/`cc_`——**绝不另造哈希算法**。`natural_key` = 被收编
  资产既有 id（factor_id@v / signal_id / candidate_id / model key），复用不另造。
- **诚实 deny-by-default 默认**：新铸 QRO = draft / untested / unreviewed / offline（最保守态），permission 默认空=未授权。

### 2. Actor 四类枚举（GOAL §0）
`ACTOR_CLASSES = {user_manual, agent, user_confirmed_agent, scheduled_agent}`；非四类 → `QROValidationError`。

### 3. 状态轴分离（GOAL §1「状态轴分离」·六轴 verbatim）
六轴各自独立枚举字段，逐轴 `__post_init__` 校验：
- definition: draft/specified/implemented
- theory: not_required/required/drafted/derived/challenged/accepted/user_waived
- consistency: not_applicable/unbound/checked/mismatch/accepted/waived_for_exploratory
- evidence: untested/exploratory/challenged/sufficient/insufficient/unverified_residual
- governance: unreviewed/approved/rejected/revoked
- runtime: offline/paper/testnet/live/suspended/retired

**不混单绿灯硬门** `axis_clearance(qro)`：四**核心轴**（definition/evidence/governance/runtime）各自达强终态
的**合取**才放整体绿；任一轴弱（如 evidence 缺）即使 governance 绿也 `cleared=False`、该轴进 `blocking_axes`。
无任何融合单 bool / 无「单轴点绿」便利属性。theory/consistency 两轴如实承载，**强标签理论裁定归
`spine_gate.evaluate_promotion`**（本门不重算·避免双源）。

### 4. 语义边界（GOAL §1 + 决策 R17）
- 对象级：`LIBRARY_OF` 映射 + `assert_library_membership(object_type, lib)` — 模型→Model Registry、
  模型输出→Signal Contract、因子→Factor Library、策略→StrategyBook、组合/风控/执行→各 Policy 库。
- 文件级：`admit_factor_qro` **复用** `signal_contract.admit_artifact_to_factor_lib`（单一源范畴门，
  懒导入避免拖 factor_factory 重依赖），模型本体（.pt/.pkl…）塞因子库 → `QROBoundaryError`。

### 5. 收编适配器（duck-typed·只读·扩展不替换）
`from_factor` / `from_signal_contract`（复用 signal_id）/ `from_model_card` / `from_strategy_candidate`
（runtime 钉 paper·D-PERM 不跳级）/ `from_mathematical_artifact`（proof_status→theory 轴粗投影）。
factor.lifecycle_state **原样 carried 不重释**（M-AUTHORITY：registry 仍权威）。刻意 duck typing →
地基模块零重依赖（`import app.qro` = 0.039s，不拖 polars/sklearn）。

## 对抗测试（种坏门必抓·mutation 定点验证·RULES §2）
真测试汇总行：**`49 passed in 0.77s`**（`tests/test_qro_envelope.py`）。
基线：`pytest --collect-only` 1798 → 1847（+49，纯增量，零 collection error）。

5 次定点变异（反向 edit→必红、还原→必绿，全程 Edit/restore 不碰 git checkout）：
| MUT | 关掉的门 | 命中测试 | 结果 |
|---|---|---|---|
| #1 | actor 四类校验 | `test_illegal_actor_rejected` ×6 | 6 RED → 还原 GREEN |
| #2 | signal typed contract 强制 | `test_signal_without_typed_contract_rejected` ×2 | 2 RED → 还原 GREEN |
| #3 | **axis_clearance 漏 evidence 轴** | `..._single_weak_core_axis[evidence]` + `test_evidence_missing_but_governance_green_is_not_overall_green` | 2 RED（`evidence_ok=False 却 cleared=True`）→ 还原 GREEN |
| #4 | 模型本体范畴门绕过 | `test_model_body_*` ×5 | 5 RED → 还原 GREEN |
| #5 | 逐轴枚举校验 | `test_axis_value_out_of_enum_rejected` ×6（全六轴） | 6 RED → 还原 GREEN |

**四核心 MUT 对应卡四命门**：#1 actor 枚举 / #2 signal typed contract / #3 四轴分离不混单绿灯 / #4 模型本体进 Factor library。

## 红线合规（逐条）
- **单一身份源 ids.py 不另造**：identity = `qro_`+`content_hash(...)`，复用 lineage.ids；`from_signal_contract`
  直接复用 `signal_id`，`from_mathematical_artifact` 复用 `artifact_id`。✅（测试 `test_identity_is_content_addressed_via_single_source`）
- **扩展不替换**：spine/ids/verification/factor_factory/models/strategy 一字未改；只新增 qro/ + 测试。收编走 duck-typed 适配器。✅
- **四轴分离不假单绿灯**：`axis_clearance` 四轴合取，单轴不点绿；MUT #3 证门非纸。✅
- **R17 语义边界复用单一源**：模型本体范畴门复用 `admit_artifact_to_factor_lib`，不另造。✅
- **不破基线**：纯增量 1798→1847，0.039s import 不拖重依赖、不触 main.py / 其他在飞线领地。✅
- **不碰共享单文件**：未动 state/log/board/DEVMAP/GOAL/pool/其他卡/main.py。✅

## 拍板项命中（语义边界岔路·诚实点名）
- **轴数 4 vs 6（卡标题「四/五轴」）**：GOAL §1「状态轴分离」**逐字列 6 轴**（definition/theory/consistency/
  evidence/governance/runtime），卡正文对抗测试只点名 4 个核心轴。**裁定（未停工·GOAL §1 已不含糊地决）**：
  实现 GOAL §1 全 6 轴 verbatim，四核心轴（definition/evidence/governance/runtime）做 `axis_clearance`
  载荷面，theory/consistency 两轴如实承载、强标签裁定让给 spine_gate。6 ⊃ 4，对抗测试全过、向后无破坏。
  → **未升级为 [需拍板]**：源（GOAL §1）已唯一确定，无真歧义；如中心要收窄回纯 4 轴，theory/consistency
  默认 not_required/not_applicable，下游忽略即可、零破坏。**点名留痕供中心知悉。**

## 诚实残余（会变任务·非设计极限）
- **A-QRO-2 接续**：语义边界本卡只做「因子库准入 + 库成员资格断言」结构门；模型本体↔Factor library 的
  完整语义切分（模型台/信号台写路径接线）归 A-QRO-2。
- **axis_clearance 只判四核心轴结构**：theory/consistency 轴的强标签裁定仍走 `spine_gate`，QRO 侧与 spine_gate
  的「双门协同」接线（强标签同时要四轴绿 + 一致性门过）是后续卡（ResearchGraph/Compiler 写路径）的活。
- **收编适配器 duck-typed**：未对真 `ModelCard`/`candidate_pool` 端到端接线（只测真 `SignalContract` +
  真 `MathematicalArtifact`，其余用 duck 对象证解耦）；与真注册表的读路径接线随下游消费卡落地。
- **graphify 图未刷**：按任务线纪律不跑 /skill；图谱更新归中心整合期（graphify-out/ 本就 gitignore）。

## 诚实限界（设计极限·不会再改）
- 信封是「身份 + 状态轴 + 治理引用」容器；它**不**判 evidence 是否真充分、理论是否真证明——那是
  verification 验证官 + spine_gate 的活。`axis_clearance` 只保证「轴分离结构 + 四轴合取」，绝不把任一轴的
  绿渲染成整体可信。proof_status→theory 轴是**粗投影快照**，非理论裁定。

## 验证状态（🟡≠✅）
- ✅ 已验证（本地实跑）：scoped 49 测试绿、5 次 mutation 全红再还原绿、import 隔离 0.039s、collect 1798→1847。
- 🟡 未验证（归中心）：全量套件未跑（任务线纪律：只跑 scoped）；与下游 ResearchGraph/Compiler 集成未接线
  （本卡是地基，下游卡接续）。中心负责整合 + 全量 + land。
