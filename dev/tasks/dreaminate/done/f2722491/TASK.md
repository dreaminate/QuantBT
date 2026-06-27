---
uuid: f2722491c6f6453aaf181bcc7b047cb3
title: Factor correlation report requires MarketDataUse PIT refs before panel reads
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: factor-correlation-market-data-pit-gate
source: goal-gap
source_ref: GOAL §9/§10/§11 factor correlation data timing/PIT gate
depends_on: [659eb22da9284a768fe589c5ab157b80]
completed_at: 2026-06-27
---

# Factor correlation report requires MarketDataUse PIT refs before panel reads

## Scope [必填]
把 `GET /api/factors/correlation` 从“可直接读 factor panel”升级为必须声明 `market_data_use_validation_refs`。endpoint 在选择 factor pair 和计算 correlation matrix 前回查 MarketData registry：accepted、无 violation、backtest/confirmatory use_context、DatasetSemantics timing refs、Instrument/Capability market coverage 和 Capability backtest permission 都必须通过。

## 上下文 / 动机 [按需]
Factor preview valid IC、IC/IC decay、layered backtest 和 audit 已接 MarketDataUse/PIT gate，但 factor correlation 仍是因子报告/数据 consumer 旁路。GOAL §10/§11 要求 report 与 estimator 绑定 data timing/PIT，不能让 correlation matrix 在无 refs 的情况下读 panel。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `factors_correlation` query 增加 `market_data_use_validation_refs`，在 pair selection / `correlation_matrix(...)` 前调用 `_factor_market_data_use_validation_refs`，成功响应回显 refs |
| `app/backend/tests/test_factor_desk_f2.py` | correlation 成功路径传 refs 并断言回显；新增缺 refs no-partial test |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. correlation report 缺 refs 时 422，且不写 Graph/Compiler/Coverage partial record。
2. 成功 correlation report 回显 deduped refs。
3. gate 必须在 factor panel / matrix 计算前执行。

## 红线 [按需]
- 不把 MarketDataUse refs 说成 correlation 已逐行证明每条行情 row 的真实消费。
- 不把 factor correlation report 说成 alpha approval、strategy promotion、portfolio construction 或 execution permission。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不实现所有因子数据 consumer、真实 provider 实网连通、alpha approval、策略晋级、线上或用户验收。

## 验收一句话 [必填]
Factor correlation report 现在必须先带 accepted/PIT MarketDataUse refs，才会读 panel 并返回 matrix。

## 完成记录（2026-06-27）
- `GET /api/factors/correlation` 在 panel/matrix 读取前强制 MarketDataUse/PIT hard gate。
- 成功响应回显 `market_data_use_validation_refs`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_factor_desk_f2.py -q` -> 42 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 200 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1827 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 passed / 0 errors / 0 warnings。
  - `git diff --check` -> PASS。
