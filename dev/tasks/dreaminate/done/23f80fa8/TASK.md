---
uuid: 23f80fa8125548cba15f9fba5227a466
title: Guarded execution order submission seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 guarded order emission seam
depends_on: [a91b0c63a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Guarded execution order submission seam

## Scope [必填]
新增 refs-only guarded order submission registry/API/QRO：把已记录 order intent 与 runtime promotion 推进到受控 submitter seam。默认 submitter disabled，不调用交易所；只有显式注入 `submit_guarded_order` 才会记录 submitter 调用结果。

## 上下文 / 动机 [按需]
`a91b0c63` 已把 execution reconciliation action producer 接到 weekly monitor tick；§12 剩余缺口仍包括真实 order emission seam。本卡先闭合 `ExecutionOrderIntentRecord` 到 guarded submitter 的受控边界，保留 no raw order/no secret/no naked `place_order` 不变量。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionOrderSubmissionRecord`、validator、parser、append-only registry |
| `app/backend/app/research_os/__init__.py` | 导出 order submission contract/registry/validator |
| `app/backend/app/main.py` | 新增 `EXECUTION_ORDER_SUBMISSIONS`、disabled submitter、`/api/research-os/execution/order_submissions` record/summary API 和 ExecutionPolicy QRO |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 registry replay、record-only API、unknown intent no-write、injected guarded submitter 调用 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. unknown `order_intent_ref` -> 422，submission JSONL/Graph 不写。
2. submission refs 与 order intent / runtime promotion 的 permission、OrderGuard、SecretRef、responsibility refs 不一致 -> validator 拒。
3. `submit_enabled=true` 且没有注入 submitter -> fail-closed，不写 submission。
4. injected submitter 只能通过 `submit_guarded_order` seam 被调用；API 仍报告 `api_place_order_called=false`。
5. QRO/summary 不得包含 raw order、quantity、price、raw venue payload 或明文 secret。

## 红线 [按需]
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、quantity、price、notional、filled_qty、fill_price、commission 或明文 secret。
- A股 live submission 仍 unreachable。
- fake submitter 测试不能宣称真实 Binance testnet key、venue API 或资金执行已连通。

## 非目标 [按需]
不接真实 Binance testnet key，不调用真实交易所，不实现 live broker connector，不证明线上长期 scheduler，不自动 remediation。

## 验收一句话 [必填]
order intent 现在能进入 guarded order submission seam 并写 ExecutionPolicy QRO；默认不动钱，注入 fake submitter 只证明 seam 调用，不证明真实 venue 连通。

## 完成记录（2026-06-27）
- 新增 `ExecutionOrderSubmissionRecord` / `PersistentExecutionOrderSubmissionRegistry`。
- 新增 `/api/research-os/execution/order_submissions` 与 summary API。
- 新增 disabled default submitter；只有显式注入的 `submit_guarded_order` seam 可被调用。
- 成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command，output contract 只含 refs 和 submitter 状态。
- 本地验证：
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 31 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py` -> 18 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_entrypoint_gate_coverage.py` -> 2 passed。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_monitor_production.py app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 58 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_execution.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_model_governance.py app/backend/tests/test_monitor_production.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_signals.py app/backend/tests/test_realmoney_audit_killswitch.py` -> 163 passed / 2 warnings。
  - `PYTHONPATH=app/backend python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 166）。
