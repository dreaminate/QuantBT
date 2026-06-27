---
uuid: 67a5e97c681b41a3a92327cb10d0b629
title: Factor registration producer compiles into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§8/§9/§14 Factor QRO -> Graph -> Compiler -> Coverage
depends_on: [b106177f560746f7b88f79bfee4bf70d, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Factor registration producer compiles into entrypoint coverage

## Scope [必填]
把 `POST /api/factors` 因子注册成功路径接到 Factor QRO、Research Graph command、governed compiler IR/pass 和 GOAL entrypoint coverage。不改 factor formula 编译、前视门、重名门、FactorRegistry 生命周期语义或 audit 算法。

## 上下文 / 动机 [按需]
`b106177f` 已让 Factor desk 后端真实暴露 `POST /api/factors`，注册前必须过编译、前视和重名三检查，成功后 Factor 初始 `NEW`。剩余缺口是成功注册只写 FactorRegistry，缺 GOAL §9 producer 的 QRO→Graph→Compiler→Coverage 入口证据。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_record_factor_qro`；`create_factor` 成功注册后写 Factor QRO，并返回 compiler/coverage refs |
| `app/backend/tests/test_factor_desk_f2.py` | 因子注册成功路径隔离 Graph/Compiler/Coverage store；断言 Factor QRO、`api:factors` entrypoint coverage、公式原文不进 Graph/Compiler |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 成功注册因子必须返回 `qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
2. Coverage entrypoint 必须是 `api:factors`。
3. Factor QRO 必须记录 formula hash / params hash / gates summary，不保存公式原文到 Graph/Compiler。
4. 原有失败路径仍先由编译、前视和重名门 422，不写 Graph/Compiler partial。

## 红线 [按需]
- 不把 Factor QRO 说成 alpha validation。
- 不把 formula registration 说成 strategy codegen、portfolio construction、runtime promotion、order emission 或 live trading。
- 不把本地测试说成 CI、线上或用户验收。

## 非目标 [按需]
不做 factor audit QRO、layered/correlation QRO、strategy assembly、完整 factor→signal 自动链、CI、线上或用户验收。

## 验收一句话 [必填]
`POST /api/factors` 成功注册因子后会生成 Factor QRO、Research Graph command、governed compiler IR/pass 与 GOAL entrypoint coverage，且公式原文不进入 Graph/Compiler。

## 完成记录（2026-06-27）
- 新增 `_record_factor_qro`，只把 formula/params hash、gate summary 和 Factor refs 写入 QRO/Compiler。
- `POST /api/factors` 成功响应新增 QRO/Graph/compiler/coverage refs，原注册门和初始 `NEW` 语义不变。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_factor_desk_f2.py -q` -> 28 passed / 2 warnings。
  - `pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 202 passed / 2 warnings。
