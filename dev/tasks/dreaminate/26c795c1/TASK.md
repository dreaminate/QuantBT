---
uuid: 26c795c1544547dab3378ae45dd834fd
title: Governed Compiler——canonical command+IR→deterministic run→evidence verdict（A-COMPILER·§1 链 capstone）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: compiler
source: goal
source_ref: GOAL §1(链 行60-75:Canvas/Command→QRO→Research Graph→Governed Compiler→Deterministic Run→Evidence Verdict→Promotion)·§7(行1315 role agent 受 deterministic DAG/governed compiler 管理·只经 canonical command/compiler 写图)·§8 治理脊柱
depends_on: [8abde88e406544e990d7cdf352740f23, 76a611d3d26c42f495a7d7a29d5e5319]
---

# Governed Compiler（A-COMPILER·LINE-A capstone·完成 QRO→Graph→Command→Compiler→Run→Verdict 整脊柱）

## Scope [必填·先读 GOAL §1 链+§7+§8]
A-QRO-1/A-GRAPH-1/A-CMD 已建 QRO 信封→Research Graph IR→CanonicalCommand。本卡建 **Governed Compiler**——§1 链「→Governed Compiler→Deterministic Run→Evidence Verdict→Promotion」那一段：① 消费 canonical command（A-CMD）+ ResearchGraph IR（A-GRAPH-1）② → **deterministic run**（**收编只读 dag/kernel.py DurableExecutor 确定性内核**·不重造·run 有确定性内核身份）③ → **evidence verdict**（**收编 verification/verifier 验证官 + eval/overfit_gate spine_gate**·不重造）④ governs promotion（**收编 approval/gate 审批门**·approver≠creator）。**这是范式载体 Quant Intent→QRO→Research Graph→Compiler→Evidence/Runtime 的 Compiler 段·完成整脊柱。**

## 领地（greenfield·只动·扩展不替换·收编不重造）
新 `app/backend/app/compiler/`（governed_compiler.py：command/IR→run→verdict→promotion 编译管线 + 治理门强制）。**收编只读**：dag/kernel(DurableExecutor 内核)、dag/engine、verification/verifier+schema、eval/overfit_gate(run_overfit_gate)、approval/gate、command/canonical_command、graph/research_graph、lineage/ids。**绝不碰** main.py、被收编模块内部（只读复用·不改）、其他在飞线（qro/training/monitor）。

## 可证伪验收（种坏门必抓·§1/§7/§8）
1. 命令未经 compiler 落 run → 拒（对抗：绕 compiler 直造 run→必抓；MUT 放过→红）。
2. run 无 deterministic 内核身份（未经 DurableExecutor 内核）→ 拒（§1·收编 dag/kernel 不重造）。
3. verdict 绕过 verifier/spine_gate → 拒（§7「verdict 绕过 verifier→拒」）。
4. promotion 未经 approval 门（approver≠creator）→ 拒（§8 治理脊柱）。
5. 正路径：合法 command+IR→deterministic run→verifier verdict→approval→正确编译·不误伤。

## 红线 [按需]
单一身份源 ids.py 不另造·扩展不替换(收编内核/门不改)·deterministic 内核身份不绕·verdict 经 verifier·promotion 经 approval(approver≠creator)·先读 GOAL §1/§7/§8 再动手·撞 decisions 未覆盖岔路停报中心。无新公式→不强造 MathematicalArtifact(编译管线是治理结构非数学)。

## 非目标 [按需]
不重造 DurableExecutor/verifier/overfit_gate/approval（收编只读复用）；不建前端；不接 main.py（领地外接线卡·中心做）。本卡只 Compiler 段：command/IR→run→verdict→promotion 管线 + 门强制。
