---
uuid: 98d6bf4a940247f89e09e9bf01f70eb1
title: Execution venue capability readiness gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue-backed order emission readiness
depends_on: [709450a48ad1491b82f16a76556ed107]
completed_at: 2026-06-27
---

# Execution venue capability readiness gate

## Scope [必填]
新增 refs-only execution venue capability registry/API/QRO：在 `submit_enabled=true` 的 guarded submission 之前，要求 recorded venue capability 证明当前 guarded venue / submitter / runtime / safety refs 已 ready。该层只证明 capability metadata 和安全 refs，不调用交易所、不保存凭据、不保存 raw order。

## 上下文 / 动机 [按需]
`709450a4` 已要求 submission 先引用 materialized order payload hash/ref，但 fake submitter 仍可能被误解成真实 venue 已可提交。本卡补 `venue_capability_ref` 门：没有 ready capability，submitter seam 不会被调用。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionVenueCapabilityRecord`、validator、parser、append-only registry；submission validator 增加 `venue_capability_ref` gate |
| `app/backend/app/research_os/__init__.py` | 导出 venue capability contract/registry/validator/parser |
| `app/backend/app/main.py` | 新增 `EXECUTION_VENUE_CAPABILITIES`、`/api/research-os/execution/venue_capabilities` record/summary API 和 ExecutionPolicy QRO；submission API 解析并校验 capability ref |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 registry replay、record-only API、unknown/mismatch/no-write、submit-without-capability reject、fake submitter requires ready capability |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `submit_enabled=true` 且没有 `venue_capability_ref` -> 422，submitter 不调用。
2. capability 非 `ready` -> submission validator 拒。
3. capability venue/guard/orderguard/secret/runtime 与 order intent / runtime promotion / submission 不一致 -> validator 拒。
4. live/testnet capability 缺 credential/IP allowlist/withdrawal disabled/HMAC/health refs -> validator 拒。
5. raw order、raw venue payload、secret、quantity、price 出现在 capability 或 submitter result -> API 拒且不写。

## 红线 [按需]
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、quantity、price、notional、filled_qty、fill_price、commission 或明文 secret。
- capability 只保存 refs/status，不证明真实 key 已连通，除非后续真实 adapter 给出可验证 evidence refs。
- A股 live capability/submission 仍 unreachable。

## 非目标 [按需]
不接真实 Binance testnet key，不调用真实交易所，不实现 live broker connector，不生成 venue-native payload，不证明线上长期 scheduler。

## 验收一句话 [必填]
`submit_enabled` order submission 现在必须同时引用 materialized order payload refs 和 ready venue capability refs，才会进入 guarded submitter seam。

## 完成记录（2026-06-27）
- 新增 `ExecutionVenueCapabilityRecord` / `PersistentExecutionVenueCapabilityRegistry`。
- 新增 `/api/research-os/execution/venue_capabilities` 与 summary API；成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- `ExecutionOrderSubmissionRecord` 增加 `venue_capability_ref`；`submit_enabled=true` 现在必须同时引用 `order_materialization_ref` 和 ready `venue_capability_ref`。
- ready capability 要求 guarded venue、submitter、runtime、permission、OrderGuard、credential check、IP allowlist、withdrawal disabled、HMAC/replay protection、health/rate-limit、kill-switch、SecretRef、responsibility refs。
- submission validator 会拒 capability 非 ready、ref 不存在、submitter/venue/guard/secret/runtime 与 order intent/runtime promotion/submission 不一致。
- API/QRO/summary 继续拒 raw order、quantity、price、notional、raw venue payload 和明文 secret；默认 submitter 仍 disabled。
- 本地验证：
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 44 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py` -> 18 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_entrypoint_gate_coverage.py` -> 2 passed。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_execution.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_model_governance.py app/backend/tests/test_monitor_production.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_signals.py app/backend/tests/test_realmoney_audit_killswitch.py` -> 176 passed / 2 warnings。
  - `PYTHONPATH=app/backend python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 168）。
