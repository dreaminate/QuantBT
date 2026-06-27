---
uuid: 0d9a6e42a419429799a93c35b57e3908
title: Runtime promotion registry QRO API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 runtime promotion transition audit
depends_on: [8f2d4b0ca419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Runtime promotion registry QRO API

## Scope [必填]
把 research/backtest/paper/testnet/live runtime promotion 从纯 validator 升级成可持久化、可 replay、可进 Research Graph 的审计对象/API；只记录 transition decision 与 guard refs，不下单、不调用 venue、不改变账户状态。

## 上下文 / 动机 [按需]
`validate_runtime_promotion()` 已覆盖 live ladder、A股 live 禁止、OrderGuard/kill-switch/SecretRef/audit/idempotency 不可 waiver 等硬门，但没有 append-only record、API 或 QRO write-through。`8f2d4b0c` 已让 order intent 进入 ExecutionPolicy QRO，本卡补 runtime transition 这一段。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `RuntimePromotionRecord`、`PersistentRuntimePromotionRegistry`、`runtime_promotion_record_from_dict`、`validate_runtime_promotion_record` |
| `app/backend/app/research_os/__init__.py` | 导出 runtime promotion runtime objects |
| `app/backend/app/main.py` | 新增 app-level `RUNTIME_PROMOTIONS` JSONL registry、`/api/research-os/execution/runtime_promotions` record/summary API、RuntimePromotion ExecutionPolicy QRO write-through |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 registry replay、API 成功写 QRO、live ladder jump 失败不写 partial |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. live promotion 没有 paper/testnet evidence 必须拒，且不写 JSONL、不写 Research Graph command。
2. 成功 runtime promotion 必须能 replay。
3. 成功 API 必须返回 `qro_id` / `research_graph_command_id`，QRO 类型为 `ExecutionPolicy`。
4. QRO output contract 必须记录 `runtime_transition_recorded=true`、`place_order_called=false`、`venue_call_called=false`。

## 红线 [按需]
- 不调用 `place_order`。
- 不调用 venue，不创建 broker connector，不确认 ack/fill/reconcile。
- 不保存 API key、token、password、raw order 或 venue raw payload。
- 不把 runtime promotion record 说成 live order 已执行。

## 非目标 [按需]
不实现真实 testnet/live order emission，不验证真实 Binance testnet key，不接 fill reconciliation，不改 kill switch 运行逻辑。

## 验收一句话 [必填]
Runtime promotion 现在能被 append-only 记录、重放，并写入 ExecutionPolicy QRO；坏 ladder 拒绝且不写 partial，系统仍明确没有下单或 venue 调用。

## 完成记录（2026-06-27）
- `RuntimePromotionRecord` / `PersistentRuntimePromotionRegistry` 已落 runtime。
- `/api/research-os/execution/runtime_promotions` 成功路径写 JSONL registry + ExecutionPolicy QRO/ResearchGraph command。
- `/api/research-os/execution/runtime_promotions/summary` 只返回 transition refs 和 guard refs，不返回 raw order/secret material。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 15 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 62 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 129 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 159）。
