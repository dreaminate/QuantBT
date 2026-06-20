---
uuid: 6e4eee5421ea4590bcbb711789c2810d
title: 入口×必经门覆盖矩阵回归 + 所有 venue 经 OrderGuard.wrap 的 CI 静态检查
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: security-invariant
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow（D1/top_rec #3，不可绕过结构性保证）+ GOAL §2 R10/M17
depends_on: []
---

# 入口×必经门覆盖矩阵回归 + 所有 venue 经 OrderGuard.wrap 的 CI 静态检查

## Scope [必填]
补一份"所有通往晋级/真钱的入口 × 必经门"覆盖矩阵测试（把"不可绕过"从架构推断升级为结构性保证）+ CI 静态检查"所有 venue 实例化路径都经 `OrderGuard.wrap`"；不改门本体。

## 上下文 / 动机 [按需]
审计结论：漏斗"不可绕过"不靠一条强制主干，而靠"每条通往晋级/真钱的入口各被某道门覆盖"——健壮但缺系统性覆盖证明，将来新增端点/venue 可能漏接门形成旁路。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/security/gate/enforcer.py | 46-106 OrderGuard.place_order | 被覆盖门（枚举校验） |
| app/backend/app/copy_trade/executor.py / execution/leased_binance.py / execution/generic_trading.py | 四 venue 路径 | 静态检查均经 wrap |
| app/backend/app/approval/gate.py | 70-131 审批门 | 晋级入口枚举 |
| app/backend/app/main.py | 各晋级/下单端点 | 枚举入口 |
| app/backend/tests/test_realmoney_audit_killswitch.py | T-025 审计不变量 | 扩展复用，不重造 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 覆盖矩阵：枚举每条通往晋级/真钱的端点入口，断言各被某道门覆盖；种"新增一个绕门端点" → 矩阵必抓。
2. venue wrap 静态检查：种"新增 venue 直接实例化、未经 OrderGuard.wrap" → CI 必红。

## 复用 [按需]
`tests/test_realmoney_audit_killswitch.py` 的绕门审计不变量 + 探针自检模式。

## 红线 [按需]
动钱不可绕过（RULES §5）；扩展现有审计测试、不替换。

## 非目标 [按需]
不改门实现；不改任何 venue 行为。

## 验收一句话 [必填]
种"新增绕门入口 / 未 wrap venue" → 矩阵或 CI 必抓；复用 T-025 审计模式、不破基线。
