---
uuid: 9ca190206ba841f583ffe02215cbccbd
title: Execution submit request envelope registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 guarded venue-backed order emission readiness
depends_on: [4393d50ab099412aa29542151381e7cd]
completed_at: 2026-06-27
---

# Execution submit request envelope registry

## Scope [必填]
新增 refs-only execution submit request registry/API/QRO：在 `submit_enabled=true` 的 `ExecutionOrderSubmissionRecord` 之前，把 `order_intent_ref`、`runtime_promotion_ref`、`order_materialization_ref`、`venue_capability_ref`、guarded venue、submitter、permission、OrderGuard、idempotency、audit、kill switch、SecretRef、responsibility、order payload hash 和 submit request hash 锁成 append-only envelope。submission 必须引用 recorded `submit_request_ref` 才能进入 guarded submitter seam。

## 上下文 / 动机 [按需]
`98d6bf4a` 和 `4393d50a` 已把 materialized order payload 与 venue capability/safety attestation 做成 refs-only gate；但 `submit_request_ref` 仍只是裸字段。为了避免 submission 直接拿 materialization/capability 拼 seam，本卡把 submit request 本身变成可校验对象，并让 API/QRO 只记录 refs/hash，不保存 raw order 或 venue-native payload。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionSubmitRequestRecord`、parser、validator、append-only registry；submission validator 增加 recorded submit request gate |
| `app/backend/app/research_os/__init__.py` | 导出 submit request contract/registry/parser/validator |
| `app/backend/app/main.py` | 新增 `EXECUTION_SUBMIT_REQUESTS`、`/api/research-os/execution/submit_requests` record/summary API 和 ExecutionPolicy QRO；submission API 解析并校验 submit request ref |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 replay/API/QRO/raw no-write、submit_enabled without submit_request reject、mismatched request reject、fake submitter receives submit request |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `submit_enabled=true` 且没有 recorded `submit_request_ref` -> 422，submitter 不调用。
2. submit request 缺 materialized order payload hash、OrderGuard、idempotency、kill-switch、SecretRef 或 venue capability ref -> 拒。
3. submit request 与 order intent / runtime promotion / materialization / capability 的 venue、runtime、guard、secret、payload hash 不一致 -> 拒。
4. raw order、raw venue payload、quantity、price、notional、明文 secret 出现在 submit request payload -> API 拒且不写。
5. A股 live submit request 仍 unreachable。

## 红线 [按需]
- 不新增裸 `place_order`。
- 不调用真实交易所，不读写真实 API key，不保存 raw order、raw venue payload、quantity、price、notional、filled_qty、fill_price、commission 或明文 secret。
- submit request 只证明请求 envelope refs/hash 已锁定，不证明真实 Binance testnet key 已连通，也不证明 venue 已接单。
- A股 live submit request/submission 仍 unreachable。

## 非目标 [按需]
不接真实 Binance testnet key，不实现 venue-native payload builder，不调用真实 venue API，不证明 production scheduler 或 mainnet live。

## 验收一句话 [必填]
`submit_enabled` order submission 必须引用 recorded submit request envelope，且 envelope 必须与 materialized order、ready venue capability 和 execution safety refs 一致，才会进入 guarded submitter seam。

## 完成记录（2026-06-27）
- 新增 `ExecutionSubmitRequestRecord` / `PersistentExecutionSubmitRequestRegistry`。
- 新增 `/api/research-os/execution/submit_requests` 与 summary API；成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- `submit_enabled=true` 的 `ExecutionOrderSubmissionRecord` 现在必须引用 recorded `submit_request_ref`；submit request 必须绑定 order intent、runtime promotion、materialized order payload hash、ready venue capability、guarded venue、submitter、permission、OrderGuard、idempotency、audit、kill-switch、SecretRef、responsibility refs。
- submission API 会解析 recorded submit request，并要求 status 为 `ready`，且 submitter/venue/runtime/guard/payload hash/secret refs 与 materialization、capability、intent、promotion 和 submission 一致。
- submit request/API/QRO/summary 继续拒 raw order、quantity、price、notional、raw venue payload 和明文 secret；新增路径不产生裸 `place_order`，默认 submitter 仍 disabled。
- 本地验证：
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 54 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 20 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_execution.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_model_governance.py app/backend/tests/test_monitor_production.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_signals.py app/backend/tests/test_realmoney_audit_killswitch.py` -> 186 passed / 2 warnings。
  - `PYTHONPATH=app/backend python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/build_board.py && python dev/scripts/build_dev_map.py && python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️ PASS（DAG 170）。
