---
uuid: ac0ad93d5f534a539dc1ad44ba2a6080
title: Execution venue connectivity check registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue API connectivity readiness
depends_on: [9ca190206ba841f583ffe02215cbccbd]
completed_at: 2026-06-27
---

# Execution venue connectivity check registry

## Scope [必填]
新增 refs-only execution venue connectivity check registry/API/QRO：把 venue safety attestation 的 credential check、IP allowlist、withdrawal disabled、HMAC/replay protection、health check、rate-limit、sandbox proof 先落成可重放 connectivity check。`attestation_status=accepted` 时必须引用 accepted `venue_connectivity_check_ref`，并要求 checker refs 与 attestation、order intent、runtime promotion 一致。

## 上下文 / 动机 [按需]
`4393d50a` 已把 safety attestation 独立成 registry，但 accepted attestation 仍可以人工填 refs。为了避免“人工 accepted”变成假 ready，本卡补 connectivity check record。默认 checker disabled；只有后续显式注入 checker 才能产 evidence refs。本卡不验证真实 Binance testnet key 连通。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionVenueConnectivityCheckRecord`、parser、validator、append-only registry；safety attestation validator 增加 `venue_connectivity_check_ref` gate |
| `app/backend/app/research_os/__init__.py` | 导出 connectivity check contract/registry/parser/validator |
| `app/backend/app/main.py` | 新增 `EXECUTION_VENUE_CONNECTIVITY_CHECKS`、`/api/research-os/execution/venue_connectivity_checks` record/summary API 和 ExecutionPolicy QRO；safety attestation API 解析并校验 connectivity check ref |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 replay/API/QRO/raw no-write、accepted safety attestation without connectivity check reject、mismatched connectivity check reject |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `attestation_status=accepted` 且没有 `venue_connectivity_check_ref` -> 拒。
2. connectivity check 非 accepted -> safety attestation 拒。
3. connectivity check venue/runtime/credential/IP allowlist/withdrawal disabled/HMAC/health/rate-limit/secret refs 与 attestation 不一致 -> 拒。
4. raw order、raw venue payload、quantity、price、notional、明文 secret 出现在 connectivity check payload -> API 拒且不写。
5. A股 live connectivity check 仍 unreachable。

## 红线 [按需]
- 不新增裸 `place_order`。
- 不调用真实交易所，不读写真实 API key，不保存 raw order、raw venue payload、quantity、price、notional、filled_qty、fill_price、commission 或明文 secret。
- connectivity check 只保存 refs/status/hash，不证明真实 Binance testnet key 已连通，除非后续真实 checker 给出可验证 evidence refs。
- A股 live connectivity check/attestation 仍 unreachable。

## 非目标 [按需]
不接真实 Binance testnet key，不调用 testnet API，不实现 venue-native payload builder，不证明 production scheduler 或 live broker connector。

## 验收一句话 [必填]
accepted venue safety attestation 必须引用 recorded accepted venue connectivity check，才可继续支撑 ready venue capability。

## 完成记录
- 新增 `ExecutionVenueConnectivityCheckRecord`、parser、validator、`PersistentExecutionVenueConnectivityCheckRegistry`。
- 新增 `/api/research-os/execution/venue_connectivity_checks` record/summary API 和 ExecutionPolicy QRO。
- `venue_safety_attestations` API 现在解析 `venue_connectivity_check_ref`，accepted attestation 必须引用 recorded 且 accepted 的 connectivity check；缺失、unknown、非 accepted 或 refs 不一致均 fail-closed。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 59 passed / 2 warnings；`PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 20 passed / 2 warnings；expanded Research OS/monitor/model/signal/execution/security scoped -> 191 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 refs-only connectivity check registry，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。
