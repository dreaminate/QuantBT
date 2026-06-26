---
uuid: d904b8d998d249728db742a62d12c350
title: 治理脊柱收口门——§8 硬不变量统一核查（CanvasMutation⇒canonical command/SecretPlaintext⇒Settings/AgentDataAccess⇒SecretRef）（§8）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: governance
source: goal
source_ref: GOAL §8 治理脊柱(行 1346-1453·硬不变量:CanvasMutation⇒canonical versioned command·AgentAction⇒scoped permission+tool record+no secret exposure·AgentPlan⇒todo+deps+acceptance gates·AgentCodeChange⇒diff+test+rollback·RoleAgentAction⇒visible event+audit·SecretPlaintext⇒Settings/Secrets only·AgentDataAccess⇒SecretRef only)
depends_on: []
---

# 治理脊柱收口门（§8·硬不变量统一核查·收编已建 enforcement）

## Scope [必填·先读 GOAL §8]
建 §8 **治理脊柱硬不变量统一核查门**——把 §8 列的硬不变量聚合成一个可证伪门（收编已建 enforcement·不重造）：① CanvasMutation⇒canonical versioned command（A-CMD 已建·收编）② AgentAction⇒scoped permission+tool record+no secret exposure（Orchestrator 已建·收编）③ AgentPlan⇒todo+deps+acceptance gates·AgentCodeChange⇒diff+test+rollback（Orchestrator plan 已建·收编）④ RoleAgentAction⇒visible workflow event+audit record（24 事件·收编）⑤ SecretPlaintext⇒Settings/Secrets only·AgentDataAccess⇒SecretRef only（Gateway/keystore 已建·收编）。任一硬不变量违反→拒。**先 grep 实证每条已被哪建件 enforce·收编只读聚合·诚实标已 enforce vs 本门补的缺口。**

## 第一步（opus 必做·先实证）
grep 实证 §8 七条硬不变量各被哪已建件 enforce（command/orchestrator/gateway/approval/ledger）·哪些已强制哪些仅部分。结论写 done 卡·本门聚合核查·补真缺口·不重造已 enforce 的。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/governance/`（spine_invariants.py：§8 七条硬不变量统一核查门 + 聚合已建 enforcement）。**收编只读**：command/canonical_command、agent/orchestrator、llm/gateway、approval、lineage/ledger。**绝不碰** main.py、被收编模块内部、其他在飞线。

## 可证伪验收（种坏门必抓·§8）
1. CanvasMutation 未落 canonical versioned command → 拒（收编 A-CMD·MUT 放过→红）。
2. AgentAction 缺 scoped permission/tool record / 泄露 secret → 拒。
3. AgentPlan 缺 todo/deps/acceptance gates → 拒；AgentCodeChange 缺 diff/test/rollback → 拒。
4. SecretPlaintext 出 Settings/Secrets（进日志/导出/LLM）→ 拒；AgentDataAccess 非 SecretRef → 拒。
5. 全硬不变量齐 → 放行（正路径不误伤）。

## 红线 [按需]
secret 明文只在 Settings/Secrets(出则拒)·AgentDataAccess 只 SecretRef·复用已建门不另造·扩展不替换·先读 GOAL §8 再动手·诚实标已 enforce vs 本门补缺口(不冒充新建已有的)。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不重造 command/orchestrator/gateway enforcement(收编只读聚合)；不接 main.py；不建前端。本卡只 §8 硬不变量统一核查门。
