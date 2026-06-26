---
uuid: 0d7c951178574b31ae35146c7867df0f
title: 信任层硬约束门 + ResponsibilityDisclosureRecord——反谄媚/诚实硬约束/waiver 不绕 safety（§13）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: trust
source: goal
source_ref: GOAL §13 信任层(行 1816-1877·诚实硬约束:不伪造 proof-backed/evidence sufficient/production-ready·不隐藏 user waiver·waiver 不绕 secret/OrderGuard/kill switch/no-silent-mock·ResponsibilityDisclosureRecord·反谄媚·弱点一等呈现·可证伪:Agent 顺从 wishful thinking 输出强结论→拒·弱点默认隐藏→拒)
depends_on: []
---

# 信任层硬约束门 + ResponsibilityDisclosureRecord（§13·反谄媚+诚实硬约束）

## Scope [必填·先读 GOAL §13]
建 §13 **信任层硬约束门**：① **诚实硬约束**（不得伪造 proof-backed/evidence sufficient/production-ready·不得隐藏 user waiver·不得让理论↔实现不一致冒充一致·**不得让 secret/OrderGuard/kill switch/no-silent-mock 被 waiver 绕过**=命门）② **ResponsibilityDisclosureRecord**（responsibility boundary disclosure·user 承担风险写入）③ **反谄媚**（Agent 遇稳赢/越级实盘/忽略成本/忽略 N/忽略泄露给缺口+证据要求+下一步·不顺从 wishful thinking 输出强结论）④ 弱点一等呈现（风险/缺口/弱点默认可见不隐藏）。**收编只读**已建（methodology MethodologyChoiceRecord/release_gate mock honesty/verifier）·补 ResponsibilityDisclosureRecord + waiver-safety 边界 + 反谄媚门。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/trust/`（trust_constraints.py 诚实硬约束门 + ResponsibilityDisclosureRecord + 反谄媚检查 + waiver-safety 边界门）。**复用** methodology/MethodologyChoiceRecord、lineage/spine、lineage/ids。**绝不碰** main.py、被收编模块内部、其他在飞线。

## 可证伪验收（种坏门必抓·§13）
1. **waiver 绕过 secret/OrderGuard/kill switch/no-silent-mock** → 拒（命门·MUT 放过→红·安全不变量不可 waiver）。
2. Agent 顺从 user wishful thinking 输出强结论(稳赢/忽略 N/忽略泄露)→ 拒（反谄媚）。
3. 弱点风险默认隐藏 / user waiver 被隐藏 → 拒（弱点一等呈现+不隐藏 waiver）。
4. user 承担风险但缺 ResponsibilityDisclosureRecord → 拒；伪造 proof-backed/evidence sufficient/production-ready → 拒。

## 红线 [按需]
**安全不变量(secret/OrderGuard/kill switch/no-silent-mock)绝不可被 waiver 绕过**(§13 命门)·不伪造强标签·反谄媚不顺从 wishful thinking·复用 MethodologyChoiceRecord 不另造·扩展不替换·先读 GOAL §13 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不重造 MethodologyChoiceRecord/mock honesty/verifier(收编只读)；不接 main.py；不建前端渐进披露 UI(后端门即可)。本卡只信任层硬约束门+ResponsibilityDisclosureRecord+反谄媚门。
