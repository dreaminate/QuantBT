---
uuid: cfb7d950a05f401784ac6063fcc73419
title: DS-4 paper 接真——submit→register_run + POST 端点 + 真 provider 产净值
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: paper-fullstack
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE · audit blocker #5/#6
depends_on: [f6bb5e8ea620412fa0c3e5a48011b74b]
---

# DS-4 paper 接真

## Scope [必填]
裁决→paper 接上 + paper 真跑：① `submit_candidate` 成功后调 `PAPER_DESK.register_run`（或新增 `POST /api/paper/runs`），把过裁决的候选注册成模拟台可跑 run；前端 PaperDeskPage 左栏改读真候选/真 paper run，不再用写死 `mock.ts RUNS`（blocker #5）；② `register_run` 注入**真 bar/mark provider**（A股 testnet/加密 paper 数据源），让 `PaperScheduler.tick_once` 真喂数据产净值序列（现 `_bar_provider=None` 直接 return 0、空壳）；前端 RunView 取真 equity/positions，「LIVE 已接真」角标与真实 `bars_fed>0` 绑定，不空壳盖绿（blocker #6）。治理门不动（D-PERM 止模拟盘 / A股恒拒 live / INV-5 审批）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/agent/business_tools.py submit_candidate | 只 append CANDIDATE_POOL | 调 register_run |
| app/backend/app/main.py | 无 POST /api/paper/runs | 新增注册端点 |
| app/backend/app/paper/desk.py | 254-256 register_run 不传 provider | 注入真 bar/mark provider |
| app/frontend/.../PaperDeskPage RunView | mock.ts RUNS | 接 paperApi 真 equity |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 过裁决候选 → register_run → 模拟台列表含该 run；scheduler tick 真喂 bars → equity_log 非空（bars_fed>0）。断 provider → 空壳必红。
2. A股 live 晋级仍恒拒（治理门不破）；INV-5 审批 approver≠creator 不破。

## 验收一句话 [必填]
陌生人晋级的策略进模拟台真跑出净值（非空壳/非 mock）；治理门红线不破；不破基线。

## 完成记录（2026-06-23 · PR #5 merged→delivery-slice · 实跑为准）
submit_candidate→register_run + POST /api/paper/runs；register_run 注真 bar/mark provider（新 replay_provider，确定性合成模拟·明确非实盘 key·非真样本）让 tick 真喂产移动净值；幂等 prime_run；seed_position 刻意不走 place_order 守绕门审计白名单。前端 PaperDeskPage 读真 /api/paper/runs、LIVE 标硬绑 bars_fed>0。**治理 §5 全不破**：A股恒拒 live(403)/INV-5/止模拟盘 e2e 实证。code-review 抓 prime_run 非幂等等 3 bug 全修。leader §3 复审：source 标签 bundled_sample_replay 过度声称→relabel deterministic_sim_walk（真样本回放=后续卡）。
整合后全量后端 **1292 passed / 13 skipped**、前端 **267 测 + tsc/build 绿**、validate_dev PASS。
