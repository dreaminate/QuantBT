---
uuid: 8ab894cd3086452fa73fee92483f6925
title: 审批 SLA 与 leverage_cap 可配置；杠杆不设硬上限；真钱超时永远 default_reject
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: config
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow + D-LEVERAGE + GOAL §9
depends_on: []
---

# 审批 SLA 与 leverage_cap 可配置；杠杆不设硬上限；真钱超时永远 default_reject

## Scope [必填]
把审批 SLA(`_SLA_SECONDS`)+ `leverage_cap`(硬编码 3.0)改为用户可配档位。**杠杆不设系统硬上限**(用户自己的钱与风险偏好,D-LEVERAGE);但门不动——下单仍过 OrderGuard、杠杆仍须显式声明、deny-by-default 不变。**真钱审批超时永远 = `default_reject`,不可配成自动放行**(止损/降险类超时 default_allow 保留)。

## 上下文 / 动机 [按需]
审计:`channels.py` 注释自承"保守默认需实证标定";`leverage_cap=3.0` 硬编码对加密用户偏严。用户拍板:杠杆放开由用户定(已知高杠杆爆仓代价)、SLA 可配,但真钱超时兜底是铁律(D-LEVERAGE)。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/approval/channels.py | 26-29 _SLA_SECONDS | 硬编码 → 可配档位 |
| app/backend/app/approval/channels.py | 13-23 超时默认动作 | **真钱 default_reject 不可配** + 止损 default_allow 保留 |
| app/backend/app/main.py | 254 leverage_cap=3.0 | 硬编码 → 可配,无系统硬上限 |
| config/ + 客户端 | 档位配置 | 用户可设 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 真钱超时铁律:种"配置把真钱审批超时改成 default_allow / 自动放行" → 必抓(致命,§5)。
2. 杠杆放开不绕门:配置高杠杆后,下单仍过 OrderGuard + 须显式声明;种"高杠杆绕过 OrderGuard/未声明直发" → 抓。
3. 权限:只 leader/admin 能改档位。

## 复用 [按需]
`channels.py` 超时分流(动钱拒/止损放行)逻辑保持,仅参数外提。

## 红线 [按需]
可配 ≠ 可绕安全:真钱超时永远 default_reject(D-LEVERAGE);杠杆门不动(OrderGuard + 显式声明)。

## 非目标 [按需]
不改超时默认动作的分流语义;不放开 OrderGuard。

## Open Questions（已决 1/1）[按需]
- [已决] D-LEVERAGE:杠杆可配、不设硬上限(用户风险偏好);SLA 可配;真钱审批超时永远 default_reject 不可配。

## 验收一句话 [必填]
种"真钱超时配成自动放行 / 高杠杆绕 OrderGuard" → 门必抓;单人研究可调快 SLA、可设高杠杆(自负代价);不破基线。
