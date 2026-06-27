---
uuid: 659eb22da9284a768fe589c5ab157b80
title: Factor preview and IC reports require MarketDataUse PIT refs before panel reads
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: factor-preview-ic-market-data-pit-gate
source: goal-gap
source_ref: GOAL §9/§10/§11 factor preview and IC data timing/PIT gate
depends_on: [ae5237adb65440c1a1425085b8dc53de, 713803cac5d346d0966d2da3a9c04efb]
completed_at: 2026-06-27
---

# Factor preview and IC reports require MarketDataUse PIT refs before panel reads

## Scope [必填]
把 factor build preview 的 valid/IC 路径、`GET /api/factors/{factor_id}/ic` 和 `GET /api/factors/{factor_id}/ic_decay` 从“可直接读 panel”升级为必须声明 `market_data_use_validation_refs`。refs 在 `factor_panel(...)` 和 `compute_ic_report(...)` 前回查 MarketData registry：accepted、无 violation、backtest/confirmatory use_context、DatasetSemantics timing refs、Instrument/Capability market coverage 和 Capability backtest permission 都必须通过。

## 上下文 / 动机 [按需]
Factor audit 和 layered backtest 已接 MarketDataUse/PIT gate，但 factor preview valid path 与 IC/IC decay 报告仍直接读 panel。GOAL §10/§11 要求 estimator / report 绑定 data timing/PIT，不能让 preview/IC 成为旁路。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_factor_preview_market_data_use_validation_refs`；valid preview 在 IC 前要求 refs；IC/IC decay GET query 要求 refs；preview ValidationDossier QRO input/output/evidence/compiler validation refs 写入 refs |
| `app/backend/tests/test_factor_desk_f2.py` | valid preview、IC、IC decay 正常路径传 refs 并断言回显/QRO/IR refs；新增缺 refs no-partial tests；compile/lookahead rejected preview 继续允许无 refs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. valid preview 公式缺 refs 时 422，且不写 Graph/Compiler/Coverage partial record。
2. IC report 缺 refs 时 422，且不写新增 partial record。
3. IC decay report 缺 refs 时 422，且不写新增 partial record。
4. compile/lookahead rejected preview 不读行情，仍可无 refs 写 rejected preview dossier。
5. 成功 preview QRO input/output、evidence refs 和 compiler IR validation refs 均包含 deduped refs。

## 红线 [按需]
- 不把 MarketDataUse refs 说成 preview/IC 已逐行消费每条行情 row。
- 不把 factor preview 或 IC report 说成 factor registration、alpha approval、strategy promotion 或 execution permission。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不实现所有因子数据 consumer、真实 provider 实网连通、alpha approval、策略晋级、线上或用户验收。

## 验收一句话 [必填]
Factor preview 的 valid IC 路径、IC report 和 IC decay report 现在必须先带 accepted/PIT MarketDataUse refs，才会读 panel；compile/lookahead rejected preview 不受影响。

## 完成记录（2026-06-27）
- Factor preview valid path 在 IC 计算前强制 MarketDataUse/PIT hard gate。
- IC / IC decay GET endpoints 要求 query `market_data_use_validation_refs`。
- Preview ValidationDossier QRO input/output、evidence refs、lineage、Compiler IR validation refs 写入 refs；compile/lookahead rejected preview 保持无 refs 可写 rejected dossier。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_factor_desk_f2.py -q` -> 41 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 199 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1826 passed / 13 skipped / 283 warnings.
  - `python dev/scripts/validate_dev.py` -> 49 passed / 0 errors / 0 warnings.
  - `git diff --check` -> PASS。
