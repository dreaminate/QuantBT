---
uuid: 3a8b23604bcd493e8dcdf8bee01c24a4
title: R28 全库双时态（known_at 轴 + as-of 重述基本面）（T-033 核验 gap）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: 数据
source: research
source_ref: 2026-06-20 T-033 核验（gap: pit_bitemporal）+ state.md:35 / R28
depends_on: []
---

# R28 全库双时态（known_at 轴 + as-of 重述基本面）

## Scope [必填]
落地 R28 全库双时态：当前连 first-seen `known_at` 都未在面板层落地（T-033 坐实 + state.md:35）。分阶段：① `known_at` 列（keep first）+ `load_panel` 的 `as_of_known` 参数；② `end_date × known_at` 双轴不折叠（支持基本面重述 as-of 查询）。

## 上下文 / 动机 [按需]
T-033：grep known_at/knowledge_date 全 0 命中（仅 ann_date）；catalog.py:233 `unique(subset=[ts,symbol],keep=last)` 把重述折叠成一行；resolver.py 的 PIT 是单轴 as-of（防 lookahead 非双时态）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/field_catalog/catalog.py | 44 _TS_CANDIDATES / 233 unique 折叠 | 加 known_at 轴、重述不折叠 |
| app/backend/app/connectors/tushare_provider.py | 1934-1953 ann_date | 落 first-seen known_at |
| app/backend/app/*/resolver.py | as-of | 加 as_of_known 双轴 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 同 (end_date, symbol) 两条重述（known_at=2024-01-30 值=10.0 / 2024-04-15 值=10.5）→ `as_of_known=2024-02-01` 读 10.0、`as_of_known=2024-05-01` 读 10.5；单轴折叠则读到 10.5 → 红。
2. 单轴 PIT 回归：universe 插未来 ts 行 → `resolve_universe(as_of)` 不纳入（守 lookahead 基线、防双时态改造回退）。

## 验收一句话 [必填]
as-of 重述读对应时点值；不破单轴 PIT 基线。
