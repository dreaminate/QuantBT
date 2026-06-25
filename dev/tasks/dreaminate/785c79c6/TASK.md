---
uuid: 785c79c6d2e84e84bd82f70e504c5b23
title: 发版门禁套件——工程标准 release gate（no silent mock/no template false success/required bindings→拒）（LINE-E·D-RELEASE-GATE）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: release-gate
source: goal
source_ref: GOAL §16 工程标准(行 1969-2032·no silent mock fallback/no template false success/dataset_version+checksum/TheoryImplementationBinding required/ConsistencyCheck required before promotion/MethodologyChoiceRecord required/LLM Gateway enforced/Mock 诚实)+§0 可上线七条；施工图 LINE-E 发版门禁
depends_on: []
---

# 发版门禁套件（LINE-E·D-RELEASE-GATE·§16 工程标准 release gate）

## Scope [必填·先读 GOAL §16+§0]
建 **发版门禁套件**——§16 工程标准作不可绕的 **release gate**：晋级/发版前强制核查 ① no silent mock fallback（mock block 必挂标识·fallback 显原因·template response 不生成 production success）② no template false success ③ dataset_version+checksum 在场 ④ TheoryImplementationBinding required for proof-backed ⑤ ConsistencyCheck required before theory-backed promotion ⑥ MethodologyChoiceRecord required for user-waived ⑦ LLM Gateway enforced + provider/model/auth_ref/cost/replay logged。任一缺→拒发版。**收编只读**已建门（spine_gate/verifier/approval/llm call_record/data_quality）·不重造·聚合成单一 release gate。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/release_gate/`（release_gate.py：工程标准核查清单 + 拒绝门 + 聚合已建证据）。**收编只读**：lineage/spine、verification/verifier、approval/gate、llm/call_record、data_quality、delivery/rdp_gate。**绝不碰** main.py、被收编模块内部、其他在飞线。

## 可证伪验收（种坏门必抓·§16）
1. silent mock fallback（mock 未挂标识 / fallback 无原因 / template 标 production success）→ 拒（MUT 放过→红）。
2. proof-backed 实现缺 TheoryImplementationBinding → 拒；theory-backed promotion 缺 ConsistencyCheck → 拒。
3. user-waived 路径缺 MethodologyChoiceRecord → 拒。
4. LLM 用了但未经 Gateway / LLMCallRecord 缺字段 → 拒。
5. 全标准齐 → 放行（正路径不误伤）。

## 红线 [按需]
no silent mock fallback·no template false success·复用已建门不另造·扩展不替换·先读 GOAL §16 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不重造 spine_gate/verifier/approval（收编只读聚合）；不接 main.py（发版编排接线另卡/中心）。本卡只工程标准 release gate 核查门。
