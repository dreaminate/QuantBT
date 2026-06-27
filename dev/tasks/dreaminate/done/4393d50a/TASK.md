---
uuid: 4393d50ab099412aa29542151381e7cd
title: Execution venue safety attestation backing registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue capability safety evidence backing
depends_on: [98d6bf4a940247f89e09e9bf01f70eb1]
completed_at: 2026-06-27
---

# Execution venue safety attestation backing registry

## Scope [必填]
新增 refs-only execution venue safety attestation registry/API/QRO：把 `venue_capability_ref` ready 所需的 credential check、IP allowlist、withdrawal disabled、HMAC/replay protection、health check、rate-limit、sandbox proof refs 先记录成独立 attestation。`capability_status=ready` 时必须引用 accepted attestation，且 attestation 的 venue/runtime/guard/secret/safety refs 必须与 capability、order intent、runtime promotion 一致。

## 上下文 / 动机 [按需]
`98d6bf4a` 已要求 ready capability 提供安全 refs，但这些 refs 仍是裸字符串。为了避免“随便填一串 ref 就 ready”的假绿，本卡把这些 refs 落成 append-only attestation，并让 venue capability ready gate 验证该 attestation。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionVenueSafetyAttestationRecord`、parser、validator、append-only registry；`ExecutionVenueCapabilityRecord` 增加 `venue_safety_attestation_ref` gate |
| `app/backend/app/research_os/__init__.py` | 导出 safety attestation contract/registry/parser/validator |
| `app/backend/app/main.py` | 新增 `EXECUTION_VENUE_SAFETY_ATTESTATIONS`、`/api/research-os/execution/venue_safety_attestations` record/summary API 和 ExecutionPolicy QRO；capability API 解析并校验 attestation ref |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 attestation replay/API/QRO/raw no-write、ready capability without attestation reject、mismatched attestation reject、submit path still needs accepted attestation-backed capability |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `capability_status=ready` 且没有 `venue_safety_attestation_ref` -> 422，capability 不写。
2. attestation 非 `accepted` -> ready capability validator 拒。
3. attestation venue/runtime/permission/OrderGuard/SecretRef/responsibility 或 safety refs 与 capability 不一致 -> 拒。
4. raw order、raw venue payload、secret、quantity、price 出现在 attestation 或 capability payload -> API 拒且不写。
5. A股 live attestation/capability 仍 unreachable。

## 红线 [按需]
- 不新增裸 `place_order`。
- 不调用真实交易所，不读写真实 API key，不保存明文凭据。
- attestation 只保存 refs/status/hash，不证明真实 Binance testnet key 已连通，除非后续真实 checker 给出可验证 evidence refs。

## 非目标 [按需]
不实现真实 Binance connectivity checker，不调用 testnet API，不生成 venue-native payload，不证明 live broker connector。

## 验收一句话 [必填]
ready venue capability 不再只靠裸字符串安全 refs；它必须引用 recorded accepted venue safety attestation，才可被 `submit_enabled` submission 使用。

## 完成记录（2026-06-27）
- 新增 `ExecutionVenueSafetyAttestationRecord` / `PersistentExecutionVenueSafetyAttestationRegistry`。
- 新增 `/api/research-os/execution/venue_safety_attestations` 与 summary API；成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- `ExecutionVenueCapabilityRecord` 增加 `venue_safety_attestation_ref`；`capability_status=ready` 现在必须引用 safety attestation ref。
- capability API 会解析 recorded safety attestation，并要求 status 为 `accepted`，且 venue/runtime/permission/OrderGuard/idempotency/credential/IP allowlist/withdrawal disabled/HMAC/health/rate-limit/kill-switch/SecretRef/responsibility refs 与 capability 匹配。
- attestation/API/QRO/summary 继续拒 raw order、quantity、price、notional、raw venue payload 和明文 secret；默认仍不调用 venue。
- 本地验证：
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 49 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py` -> 18 passed / 2 warnings。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_entrypoint_gate_coverage.py` -> 2 passed。
  - `PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_execution.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_model_governance.py app/backend/tests/test_monitor_production.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_signals.py app/backend/tests/test_realmoney_audit_killswitch.py` -> 181 passed / 2 warnings。
  - `PYTHONPATH=app/backend python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 169）。
