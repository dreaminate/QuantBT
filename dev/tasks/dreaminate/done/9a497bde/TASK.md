---
uuid: 9a497bded262454bad03337b66e7e615
title: 交付门 e2e 集成测试——陌生人 chat→backtest→裁决→paper 全后端路径真
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: integration-test
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE 收口 · §9 交付总闸 e2e 闭合
depends_on: [cfb7d950a05f401784ac6063fcc73419]
---

# 交付门 e2e 集成测试

## Scope [必填]
后端集成测试覆盖陌生人完整路径**全程真产物、零 mock**：`strategy_goal.create`（→真 goal_id）→ `backtest.run`（→真 run_id 落 RUN_ROOT、真净值）→ `project_verdict`/`project_overfit`（→真裁决 + 真 PBO/DSR/Bootstrap）→ paper `register_run`（→真 bar provider 喂数据 `bars_fed>0` 产真 equity）。任一环若退化为 mock/伪造/空壳 → 测试红。这是 §9 交付总闸的 e2e 闭合证据（陌生人路径非演示剧场）。依赖 DS-4 paper 接真（register_run + 真 provider）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/tests/test_delivery_slice_e2e.py | 新文件 | 全链集成测试（复用 DS-1/DS-2/DS-4 真组件，隔离 data_root/RUN_ROOT） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 全链跑通：goal_id 非空 + run_id 落 RUN_ROOT（run.json+portfolio.csv 真净值）+ project_verdict 可消费 + paper run bars_fed>0 真 equity_log 非空。
2. 治理门不破：A股 live 晋级恒拒（D-PERM）；INV-5 审批 approver≠creator；§3 任一环空壳/mock→断言红。

## 验收一句话 [必填]
一条 e2e 测试证明陌生人 chat→backtest→裁决→paper 全程真产物、治理门不破；不破基线。

## 完成记录（2026-06-23 · leader commit merged→delivery-slice · 实跑为准）
新 test_delivery_slice_e2e（3 测）：陌生人 chat→backtest→裁决→paper 全链真产物一条龙（真 goal_id→真 run_id 落 RUN_ROOT→真 PBO/DSR/Bootstrap→paper bars_fed>0 真 equity）；空壳 simulate=False bars_fed=0 不假绿；A股 live 恒拒。leader 终验артефакт。
整合后全量后端 **1292 passed / 13 skipped**、前端 **267 测 + tsc/build 绿**、validate_dev PASS。
