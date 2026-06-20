---
uuid: 6403b9bfd46749bab7ef4885f5b763ad
title: 诚实残余核验——监控尾部闭环 + 组合层三角 + D2 四残余
status: done
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

## 完成记录（2026-06-20）
- **诚实核验（workflow 7 agent，逐项独立复证，无一假绿灯 §3）**：6 项残余 → **2 verified / 4 gap**。
  - ✅ **venue_lease**：INV-3 lease-only 生产做实——生产 crypto factory(main.py:209-225)只产 `LeasedBinanceVenue`(place_order 显含 `*,lease=None`→走 lease 通道)，`_kernel(None)` fail-closed，真 key venue 仅 `_kernel(lease)` 内构造；enforcer 退化分支对 broker-keyed venue 不可达。
  - ✅ **jsonl_tamper**：`ledger.py` 真 hash chain 防篡改（_ChainStore prev_hash 链 + verify_chain 重算 + verify_integrity 三道 + SQLite↔JSONL 对账），实跑 `test_lineage_ledger.py` 25 passed（含中间行/列篡改/截断/坏 payload 对抗套件）。
  - 🟡 **monitor_loop** → **pool d0e5d208**：尾部闭环未接线（cost_drift/retire/lifecycle 零生产调用方、Scheduler 生产未实例化、漂移仅 append-note）。
  - 🟡 **portfolio_triangle** → **pool 46f1cb3c**：组合层未上多证据三角（portfolio/signals 不 import eval/*）。
  - 🟡 **stacking_oof** → **pool 87ad21fc**：无 stacking/meta 对象，R18 控制项 N/A（待实现 stacking）。
  - 🟡 **pit_bitemporal** → **pool 3a8b2360**：全双时态未做（known_at/knowledge_date 全 0 命中）。
- **verified 防回归探针**（`test_venue_lease_invariant.py` 2 passed）：lease-only 签名 + fail-closed 默认 None；jsonl 已有 25 tests 充分。
- **gap 升级**：4 个 gap 诚实 mint 进 pool（tracked 进任务 DAG，绝不标绿）。

## 升级卡（gap → pool）
- d0e5d208 monitor 尾部闭环 · 46f1cb3c 组合三角 · 87ad21fc stacking-R18(N/A) · 3a8b2360 双时态-R28
