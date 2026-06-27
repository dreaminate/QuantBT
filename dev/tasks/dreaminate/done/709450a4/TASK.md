---
uuid: 709450a48ad1491b82f16a76556ed107
title: Execution order materialization registry API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 order materialization before guarded submission
depends_on: [23f80fa8125548cba15f9fba5227a466]
completed_at: 2026-06-27
---

# Execution order materialization registry API

## Scope [必填]
新增 refs-only order materialization registry/API/QRO：在 guarded submission 之前，把 recorded order intent + runtime promotion 解析成可审计的 `order_schema_ref` / `order_payload_hash` / sizing-price-risk refs。默认 materializer disabled；只有显式注入 `materialize_order` 才会产出 materialized refs。

## 上下文 / 动机 [按需]
`23f80fa8` 已经有 guarded submission seam，但 submit_enabled 路径仍可能直接从 order intent 进入 submitter。§12 的真实边界需要先有 payload hash / risk / market snapshot / sizing-price resolution refs，再允许 submission seam 被调用；同时继续禁止 raw order、quantity、price、venue payload 和明文 secret 入库。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionOrderMaterializationRecord`、validator、parser、append-only registry；submission validator 增加 `order_materialization_ref` gate |
| `app/backend/app/research_os/__init__.py` | 导出 order materialization contract/registry/validator/parser |
| `app/backend/app/main.py` | 新增 `EXECUTION_ORDER_MATERIALIZATIONS`、disabled materializer、`/api/research-os/execution/order_materializations` record/summary API 和 ExecutionPolicy QRO；submission API 解析并校验 materialization ref |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 registry replay、record-only API、unknown intent no-write、injected materializer、submit-without-materialization reject、injected submitter requires materialization |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. unknown `order_intent_ref` -> 422，materialization JSONL/Graph 不写。
2. materialization refs 与 order intent / runtime promotion 的 permission、OrderGuard、SecretRef、responsibility refs 不一致 -> validator 拒。
3. materializer 返回 raw order/quantity/price/payload 或报告 place_order/venue API call -> API 拒。
4. `submit_enabled=true` 且没有 recorded `order_materialization_ref` -> 422，submitter 不调用。
5. `submit_enabled=true` 引用 status 非 `materialized` 的 materialization -> validator 拒。
6. QRO/summary 不得包含 raw order、quantity、price、raw venue payload 或明文 secret。

## 红线 [按需]
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、quantity、price、notional、filled_qty、fill_price、commission 或明文 secret。
- materialization 只保存 refs/hash，不保存 venue-native payload。
- A股 live materialization/submission 仍 unreachable。
- fake materializer / fake submitter 测试不能宣称真实 Binance testnet key、venue API 或资金执行已连通。

## 非目标 [按需]
不接真实 Binance testnet key，不调用真实交易所，不实现 live broker connector，不生成可反演的 venue-native payload，不证明线上长期 scheduler。

## 验收一句话 [必填]
order intent 现在必须先形成 refs-only order materialization 记录，`submit_enabled` submission 才能进入 guarded submitter seam；默认仍不动钱，注入 fake materializer/submitter 只证明 seam 调用和 hash/ref 门。

## 完成记录（2026-06-27）
- 新增 `ExecutionOrderMaterializationRecord` / `PersistentExecutionOrderMaterializationRegistry`。
- 新增 `/api/research-os/execution/order_materializations` 与 summary API。
- 新增 disabled default materializer；只有显式注入的 `materialize_order` seam 可被调用。
- `ExecutionOrderSubmissionRecord` 增加 `order_materialization_ref`；`submit_enabled=true` 必须引用 recorded 且 `materialized` 的 materialization。
- 成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command，output contract 只含 refs/hash/materializer 状态。
- 本地验证：
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 38 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py` -> 18 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_entrypoint_gate_coverage.py` -> 2 passed。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_execution.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_model_governance.py app/backend/tests/test_monitor_production.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_signals.py app/backend/tests/test_realmoney_audit_killswitch.py` -> 170 passed / 2 warnings。
  - `PYTHONPATH=app/backend python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 167）。
