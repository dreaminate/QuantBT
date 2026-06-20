---
uuid: 6403b9bfd46749bab7ef4885f5b763ad
title: 诚实残余核验——监控尾部闭环 + 组合层三角 + D2 四残余
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: verification
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow（D1/D2 open questions，防假绿灯）+ RULES §3
depends_on: []
---

# 诚实残余核验——监控尾部闭环 + 组合层三角 + D2 四残余

## Scope [必填]
坐实本次审计标注的"未验证"项（防假绿灯，RULES §3）：① 监控→自动降级/退役→问责尾部闭环是否被调度周期触发、漂移告警是否驱动 stop_rule；② 组合层（M7-M8）多证据三角缺口确认；③ D2 四残余。核验为主，缺口产 finding / 升级卡，不在本卡做大实现。

## 上下文 / 动机 [按需]
审计诚实标注一批未独立复验项；RULES §3 要求"未验证 ≠ 已验证"，须坐实而非假绿灯。D2 四残余 = 生产 venue fallback 是否 lease-only fail-closed / stacking meta-model 是否消费 purged OOF / PIT 全双时态 knowledge_date 轴 / JSONL 落盘篡改测试。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/monitor/cost_drift.py | 69 compute_weekly_cost_drift | 核验是否被调度周期触发 |
| app/backend/app/hypothesis/store.py | 207 retire | 核验是否自动触发 |
| app/backend/app/signals/ · portfolio/ | 组合层 | 三角缺口确认（state.md:38） |
| app/backend/app/execution/leased_binance.py | venue fallback | lease-only fail-closed |
| app/backend/app/training/ | stacking OOF | 是否消费 purged OOF |
| app/backend/app/lineage/ledger.py | JSONL append-only | 篡改检测测试 |
| app/backend/app/datasets/ · field_catalog/ | PIT 双时态 | knowledge_date 轴 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 每核验点配探针：种"JSONL 被篡改" → 篡改检测必抓；种"venue fallback 自取 key" → 必抓。
2. 尾部闭环：种"漂移超阈但不触发 stop_rule" → 若闭环真接则必抓；若没接则产诚实 finding（🟡缺口）。

## 复用 [按需]
各子系统已有测试；`ledger.py` hash chain 校验。

## 红线 [按需]
RULES §3 诚实——未验证就是未验证，核验结果如实落 `state/`/`findings/`，绝不假绿灯。

## 非目标 [按需]
不在本卡做缺口的大实现（核验定性优先，缺口升级独立卡）。

## 验收一句话 [必填]
每个残余项产出"已验证✅ / 缺口🟡"的诚实结论 + 对应探针；不破基线。
