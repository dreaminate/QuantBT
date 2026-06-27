---
uuid: ae5237adb65440c1a1425085b8dc53de
title: Factor preview validate producer compiles into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§8/§9/§10/§14 Factor preview ValidationDossier QRO -> Graph -> Compiler -> Coverage
depends_on: [67a5e97c681b41a3a92327cb10d0b629, b9c3dc4b68614d079801e750e3071fee, 84c728cb7ed74e63b7194b791ebd7eac, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Factor preview validate producer compiles into entrypoint coverage

## Scope [必填]
把 `POST /api/factors/validate` 因子预览校验成功返回路径接到 ValidationDossier QRO、Research Graph command、governed compiler IR/pass 和 GOAL entrypoint coverage。不改预览 IC 算法、编译/前视门、FactorRegistry 注册语义或 audit/layered 语义。

## 上下文 / 动机 [按需]
`67a5e97c`、`b9c3dc4b`、`84c728cb` 已分别让因子注册、audit、layered backtest 进入 QRO→Graph→Compiler→Coverage。剩余缺口是 build desk 的即时 `validate` 预览仍只是 HTTP 返回，没有把 ok / compile reject / lookahead reject 作为 refs-only preview ValidationDossier 进入统一链路。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_record_factor_preview_validation_qro`；`factors_validate` 的 200 返回路径写 preview ValidationDossier QRO，并返回 `validation_dossier_ref`、QRO/Graph/compiler/coverage refs |
| `app/backend/tests/test_factor_desk_f2.py` | 因子预览 ok、compile reject、lookahead reject 三条路径隔离 Graph/Compiler/Coverage store；断言 `api:factors.validate` coverage、ValidationDossier QRO、公式原文和 raw IC 数值不进 Graph/Compiler |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. preview ok 必须返回 QRO/Graph/compiler/coverage refs，entrypoint 是 `api:factors.validate`。
2. compile reject 和 lookahead reject 仍然是 200 预览结果，但必须写 rejected preview dossier，不能假绿灯。
3. QRO/Compiler 只能保存 formula hash、result hash、reason hash、IC summary hash、stage/valid summary 和 refs，不保存公式原文、IC 数值、return panel 或 secret marker。
4. 空公式和 IC 计算异常仍按原 422 输入/计算失败语义处理，不把异常包装成 proof-backed 结果。

## 红线 [按需]
- 不把 preview validation 说成 factor registration。
- 不把即时 IC preview 说成 alpha approval、strategy promotion、portfolio construction、runtime permission 或 live trading。
- 不把本地测试说成 CI、线上或用户验收。

## 非目标 [按需]
不做 correlation GET 写 Graph、不做 factor registration、audit/layered 算法改造、自动 signal contract、portfolio construction、runtime promotion、真实下单、CI、线上或用户验收。

## 验收一句话 [必填]
`POST /api/factors/validate` 的 ok / compile reject / lookahead reject 预览结果会生成 ValidationDossier QRO、Research Graph command、governed compiler IR/pass 与 GOAL entrypoint coverage，且公式原文和 raw IC 数值不进入 Graph/Compiler。

## 完成记录（2026-06-27）
- 新增 `_record_factor_preview_validation_qro`，只把 formula/result/reason/IC summary hash、stage/valid summary 和 refs 写入 QRO/Compiler。
- `POST /api/factors/validate` 的 ok、compile reject、lookahead reject 200 返回路径新增 `validation_dossier_ref`、QRO/Graph/compiler/coverage refs；endpoint 现在通过 `require_user_dependency` 记录真实 actor。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_factor_desk_f2.py -q` -> 31 passed / 2 warnings。
  - `pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 205 passed / 2 warnings.
  - `pytest app/backend/tests -q` -> 1804 passed / 13 skipped / 283 warnings.
