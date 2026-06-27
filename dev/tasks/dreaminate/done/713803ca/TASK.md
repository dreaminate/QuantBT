---
uuid: 713803cac5d346d0966d2da3a9c04efb
title: Factor audit requires MarketDataUse PIT refs before ValidationDossier report
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: factor-audit-market-data-pit-gate
source: goal-gap
source_ref: GOAL §9/§10/§11 factor audit ValidationDossier data timing/PIT gate
depends_on: [b9c3dc4b68614d079801e750e3071fee, 48f70fa3e9af4caebdffca604ea3df6f]
completed_at: 2026-06-27
---

# Factor audit requires MarketDataUse PIT refs before ValidationDossier report

## Scope [必填]
把 `POST /api/factors/{factor_id}/audit` 从“可只凭 market/horizon/tier 生成 FactorAuditReport + ValidationDossier QRO”升级为必须声明 `market_data_use_validation_refs`。endpoint 在运行 `run_factor_audit(...)` 前先回查 MarketData registry：每个 ref 必须存在、accepted、无 violation、use_context 为 `backtest` 或 `confirmatory_validation`；DatasetSemantics 必须有 `known_at_ref`、`effective_at_ref`、`pit_bitemporal_rules_ref`；Instrument/Capability asset_class 必须覆盖请求 market，Capability 必须允许 backtest。

## 上下文 / 动机 [按需]
`b9c3dc4b` 已把 factor audit 报告接成 ValidationDossier QRO/Graph/Compiler/Coverage，但该验证材料没有先绑定 MarketDataUse/PIT refs。GOAL §10/§11 要求验证材料不能脱离 event/known/effective time 证据。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 抽出 `_factor_market_data_use_validation_refs`；`_factor_audit_market_data_use_validation_refs` 与 layered 共用同一 gate；audit endpoint 在 report 运行前调用；`_record_factor_audit_qro` input/output/evidence/compiler validation refs 写入 refs |
| `app/backend/tests/test_factor_desk_f2.py` | 正常 audit 路径传 refs 并断言 QRO/IR/Coverage 记录 refs；新增缺 refs、unknown、rejected、violation、wrong market、timing 缺失 no-partial tests |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 `market_data_use_validation_refs` 时 422，且不写 Graph/Compiler/Coverage partial record。
2. unknown / rejected / violation refs 均 422，且不写 partial record。
3. refs 覆盖 crypto 但请求 `equity_cn` 时 422，且不写 partial record。
4. DatasetSemantics 缺 PIT/bitemporal timing refs 时 422，且不写 partial record。
5. 成功 audit QRO input/output、evidence refs 和 compiler IR validation refs 均包含 deduped refs。

## 红线 [按需]
- 不把 MarketDataUse refs 说成 factor audit 已逐行消费每条行情 row。
- 不把 FactorAuditReport 说成 alpha approval、strategy promotion、portfolio construction 或 execution permission。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不实现所有因子报告入口、所有数据 consumer、真实 provider 实网连通、alpha approval、策略晋级、线上或用户验收。

## 验收一句话 [必填]
Factor audit 现在必须先带 accepted/PIT MarketDataUse refs，才会运行报告并写 ValidationDossier QRO/Compiler/Coverage；坏 refs 不写 partial record。

## 完成记录（2026-06-27）
- Factor audit endpoint 在 report 运行前强制 MarketDataUse/PIT hard gate。
- Audit ValidationDossier QRO input/output、evidence refs、lineage、Compiler IR validation refs 写入 refs。
- Layered backtest 复用同一底层 helper，旧错误文案保持不变。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_factor_desk_f2.py -q` -> 39 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 197 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1824 passed / 13 skipped / 283 warnings.
  - `python dev/scripts/validate_dev.py` -> 49 passed / 0 errors / 0 warnings.
  - `git diff --check` -> PASS。
