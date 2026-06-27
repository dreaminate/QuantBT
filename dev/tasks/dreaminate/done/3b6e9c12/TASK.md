---
uuid: 3b6e9c12a419429799a93c35b57e3908
title: Execution venue event audit QRO API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue ack fill reconcile audit
depends_on: [0d9a6e42a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Execution venue event audit QRO API

## Scope [必填]
新增 execution venue event 的 append-only audit record/API，把 submitted/accepted/rejected/fill/cancel/reconciled 事件以 refs/hash 形式接入 Research Graph；API 只记录外部事件证据，不调用 venue、不发单、不保存 raw venue payload。

## 上下文 / 动机 [按需]
`0d9a6e42` 已让 runtime promotion 进入 registry/QRO，但 §12 仍缺 venue ack/fill/reconcile 的证据面。直接在 main 新增 `place_order` 会违反真钱路径审计；本卡只补 refs-only 事件记录，真实下单仍必须走既有 OrderGuard/venue 路径。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionVenueEventRecord`、`PersistentExecutionVenueEventRegistry`、`execution_venue_event_from_dict`、`validate_execution_venue_event` |
| `app/backend/app/research_os/__init__.py` | 导出 venue event runtime objects |
| `app/backend/app/main.py` | 新增 app-level `EXECUTION_VENUE_EVENTS` JSONL registry、`/api/research-os/execution/venue_events` record/summary API、venue event ExecutionPolicy QRO write-through |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 registry replay、API 成功写 QRO、invalid fill 不写 partial、raw venue payload 拒绝 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. fill event 缺 `fill_ref` / `quantity_ref` / `price_ref` 必须拒，且不写 JSONL/Graph。
2. payload 带 `raw_event`、`filled_qty`、`fill_price` 等 raw venue/order material 必须拒。
3. 成功 event 必须绑定已记录 `order_intent_ref` 和 `runtime_promotion_ref`。
4. 成功 event 必须写 `ExecutionPolicy` QRO，且 output contract 标明 `record_only=true`、`api_place_order_called=false`、`api_venue_call_called=false`。

## 红线 [按需]
- 不新增 main 里的 `place_order` 调用点。
- 不调用 venue、不请求交易所、不移动资金。
- 不保存 raw order、raw ack、raw fill、raw execution report、filled_qty、fill_price、commission 或明文 secret。
- 不把 venue event audit 说成真实 connector 已接通。

## 非目标 [按需]
不实现真实 order emission，不接 Binance testnet/live key，不实现 fill reconciliation worker，不改变 copy-trade relay 路径。

## 验收一句话 [必填]
Venue ack/fill/reconcile 现在有 refs-only 审计记录和 QRO 写入；该 API 自身不下单、不调 venue、坏事件不写 partial。

## 完成记录（2026-06-27）
- `ExecutionVenueEventRecord` / `PersistentExecutionVenueEventRegistry` 已落 runtime。
- `/api/research-os/execution/venue_events` 成功路径写 JSONL registry + ExecutionPolicy QRO/ResearchGraph command。
- `/api/research-os/execution/venue_events/summary` 只返回 event refs/hash，不返回 raw venue/order material。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 19 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 66 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 133 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 160）。
