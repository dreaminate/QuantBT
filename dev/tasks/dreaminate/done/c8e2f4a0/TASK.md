---
uuid: c8e2f4a0d6bb4d75b6d8e0127f5e1a2c
title: Persistent signal contract registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-signal-boundary
source: goal-gap
source_ref: GOAL §9 Signal Contract persistence
depends_on: [4c0d9e1f2d7043fd950a7c35e8a42a6b]
completed_at: 2026-06-27
---

# Persistent signal contract registry

## Scope [必填]
把 `SignalContractRegistry` 从纯内存 dict 升级为可选 JSONL-backed registry；主 app 的 `SIGNAL_CONTRACTS` 落到 `DATA_ROOT/audit/signal_contracts.jsonl`，使 `/api/factors/signal_contracts` 和 `/api/models/{model_id}/versions/{version}/predict` 登记的信号契约能跨进程重放。

## 上下文 / 动机 [按需]
`4c0d9e1f` 已让 model prediction 可选登记 typed SignalContract，但 registry 仍是进程内存。§9 的 model→signal contract 不能只在请求周期内存在。本卡补持久化，不改变 R17/R18 范畴门和泄露声明门。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/factor_factory/signal_contract.py` | `SignalContractRegistry` 支持 path、JSONL append、startup replay、坏历史 fail-fast |
| `app/backend/app/main.py` | `SIGNAL_CONTRACTS` 改为 `DATA_ROOT/audit/signal_contracts.jsonl` backed |
| `app/backend/tests/test_factor_lab_endpoints.py` | 覆盖 signal contract persist/replay |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 登记 signal contract 后重建 registry 仍能按 `signal_ref` 读取。
2. 持久化只发生在 register 成功后，失败的 source_lib/model_ref/leakage 门不写。
3. 重放时坏 schema / 缺 payload 必须 fail-fast，不静默忽略。

## 红线 [按需]
- 不允许放松 model_ref 本体回指门。
- 不允许放松 OOF/purge/embargo 泄露声明门。
- 不允许把持久化 signal contract 说成 signal alpha 有效。

## 非目标 [按需]
不实现 signal performance validation，不实现 signal alpha proof，不实现自动组合，不实现 order emission，不实现外部 registry。

## 验收一句话 [必填]
成功登记的 SignalContract 会写入 JSONL 并可重放；信号契约持久化不改变现有范畴门、血统门和泄露声明门。

## 完成记录（2026-06-27）
- `SignalContractRegistry(path=...)` 支持 JSONL replay 和 append。
- 主 app `SIGNAL_CONTRACTS` 改为 `DATA_ROOT/audit/signal_contracts.jsonl` backed。
- 本地验证：
  - `python -m pytest app/backend/tests/test_factor_lab_endpoints.py -q` -> 16 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_model_governance.py -q` -> 39 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 163 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 154）。
