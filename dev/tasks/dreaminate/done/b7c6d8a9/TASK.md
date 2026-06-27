---
uuid: b7c6d8a9ccce2a6a53904b97ab02303a
title: Signal performance validation registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-signal-boundary
source: goal-gap
source_ref: GOAL §9 Signal Contract performance validation
depends_on: [c8e2f4a0d6bb4d75b6d8e0127f5e1a2c]
completed_at: 2026-06-27
---

# Signal performance validation registry

## Scope [必填]
把 SignalContract 之后的 performance validation 升成 first-class append-only record/API；StrategyBook boundary 可选择强制要求每个 signal_ref 绑定 accepted validation ref 后才能被策略/组合消费。

## 上下文 / 动机 [按需]
`c8e2f4a0` 已让 SignalContract 可持久化，但它仍只证明“模型输出可以作为信号契约登记”，不证明信号可被策略/组合消费。§9 终态要求 model output → signal → portfolio/order 之间有 typed contract 和验证门。本卡补 signal performance validation 的审计对象，不把它说成 alpha proof。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/factor_strategy_boundary.py` | 新增 `SignalPerformanceValidationRecord`、`PersistentSignalValidationRegistry`、`validate_signal_performance_validation`；`validate_strategy_book(..., require_signal_validation=True)` 要求 accepted validation ref |
| `app/backend/app/research_os/__init__.py` | 导出 signal validation runtime objects |
| `app/backend/app/main.py` | 新增 app-level `SIGNAL_VALIDATIONS` JSONL registry 和 `/api/research-os/signal_validations` record/summary API |
| `app/backend/tests/test_factor_strategy_boundary.py` | 覆盖 validation record gate、registry replay、strategy accepted-validation gate |
| `app/backend/tests/test_factor_lab_endpoints.py` | 覆盖 API 成功记录、summary、unknown signal no-write |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. validation 缺 dataset/window/methodology/metric/evidence/leakage refs 必须拒。
2. unknown SignalContract ref 通过 API 登记 validation 必须拒，且不写 JSONL。
3. StrategyBook 开启 `require_signal_validation=True` 时，缺 validation 或 validation verdict=rejected 必须拒。

## 红线 [按需]
- 不允许把 accepted validation 说成 signal alpha proof。
- 不允许把 raw predictions/raw returns 写进 summary。
- 不允许绕过 SignalContract 直接登记孤儿 validation。

## 非目标 [按需]
不实现 alpha proof，不实现自动组合，不实现 order emission，不实现 live trading，不实现外部 signal registry。

## 验收一句话 [必填]
SignalContract 可绑定可重放的 performance validation record；StrategyBook boundary 可在需要时强制每个 signal_ref 绑定 accepted validation ref。

## 完成记录（2026-06-27）
- `SignalPerformanceValidationRecord` / `PersistentSignalValidationRegistry` 已落 runtime。
- `POST /api/research-os/signal_validations` 先确认 SignalContract 存在，再写 validation JSONL。
- `GET /api/research-os/signal_validations/summary` 只返回 refs/verdict，不返回 raw predictions/raw returns。
- 本地验证：
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py -q` -> 12 passed。
  - `python -m pytest app/backend/tests/test_factor_lab_endpoints.py -q` -> 18 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_portfolio_promote_api.py -q` -> 66 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 93 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 155）。
