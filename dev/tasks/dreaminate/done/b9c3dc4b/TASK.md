---
uuid: b9c3dc4b68614d079801e750e3071fee
title: Factor audit producer compiles into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§8/§9/§10/§14 Factor audit ValidationDossier QRO -> Graph -> Compiler -> Coverage
depends_on: [67a5e97c681b41a3a92327cb10d0b629, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Factor audit producer compiles into entrypoint coverage

## Scope [必填]
把 `POST /api/factors/{factor_id}/audit` 因子审查成功路径接到 ValidationDossier QRO、Research Graph command、governed compiler IR/pass 和 GOAL entrypoint coverage。不改 DSR/PBO/N_eff/bootstrap/IC-NW 计算原语、裁决算法、FactorRegistry 或 portfolio/execution promotion 语义。

## 上下文 / 动机 [按需]
`67a5e97c` 已让 `POST /api/factors` 因子注册成功路径写 Factor QRO 并生成 compiler coverage。剩余缺口是 factor audit 虽然已产多证据三角报告，但没有把报告作为 GOAL §9/§10 的 `ValidationDossier` producer 写入 QRO→Graph→Compiler→Coverage。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_record_factor_audit_qro`；`factor_audit_endpoint` 成功计算报告后写 ValidationDossier QRO，并返回 `validation_dossier_ref`、QRO/Graph/compiler/coverage refs |
| `app/backend/tests/test_factor_desk_f2.py` | 因子 audit 成功路径隔离 Graph/Compiler/Coverage store；断言 `api:factors.audit` entrypoint coverage、ValidationDossier QRO、公式原文和 raw panel/payload 不进 Graph/Compiler；invalid tier 失败路径不写 partial record |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 成功 audit 必须返回 `qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`、`validation_dossier_ref`。
2. Coverage entrypoint 必须是 `api:factors.audit`，QRO 类型必须是 `ValidationDossier`。
3. QRO/Compiler 只能保存 formula hash、report hash、threshold hash、check summary hash、verdict 和 refs，不保存公式原文、raw return panel、raw payload 或 secret marker。
4. invalid tier 等审查输入失败必须 422，且不写 Graph/Compiler/Coverage partial record。

## 红线 [按需]
- 不把 factor audit dossier 说成 alpha 已获批准。
- 不把 `consistent` 说成 strategy promotion、portfolio construction、runtime permission、order emission 或 live trading。
- 不把本地测试说成 CI、线上或用户验收。

## 非目标 [按需]
不做 layered/correlation QRO、strategy assembly、自动 signal contract、portfolio construction、runtime promotion、真实下单、CI、线上或用户验收。

## 验收一句话 [必填]
`POST /api/factors/{factor_id}/audit` 成功后会生成 ValidationDossier QRO、Research Graph command、governed compiler IR/pass 与 GOAL entrypoint coverage，且公式原文和 raw audit payload 不进入 Graph/Compiler。

## 完成记录（2026-06-27）
- 新增 `_record_factor_audit_qro`，只把 formula/report/threshold/check summary hash、verdict 和 refs 写入 QRO/Compiler。
- `POST /api/factors/{factor_id}/audit` 成功响应新增 `validation_dossier_ref`、QRO/Graph/compiler/coverage refs；endpoint 现在通过 `require_user_dependency` 记录真实 actor。
- invalid tier 失败路径保持 422，并新增 no partial Graph/Compiler/Coverage 断言。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_factor_desk_f2.py -q` -> 29 passed / 2 warnings。
  - `pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 203 passed / 2 warnings.
  - `pytest app/backend/tests -q` -> 1802 passed / 13 skipped / 283 warnings.
