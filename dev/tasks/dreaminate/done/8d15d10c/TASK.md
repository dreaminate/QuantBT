---
uuid: 8d15d10c3b8e4781a99b5047b23a8dda
title: Execution venue connectivity checker seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue API connectivity readiness
depends_on: [ac0ad93d5f534a539dc1ad44ba2a6080]
completed_at: 2026-06-27
---

# Execution venue connectivity checker seam

## Scope [必填]
新增 refs-only venue connectivity checker seam/API：让 recorded order intent + runtime promotion 能请求一个注入式 checker 生成 `ExecutionVenueConnectivityCheckRecord`。默认 checker disabled；只有测试或后续真实 connector 显式注入 checker 时才会产出 connectivity refs/hash。所有输出仍走 connectivity check validator、append-only registry 和 ExecutionPolicy QRO。

## 上下文 / 动机 [按需]
`ac0ad93d` 已把 connectivity check 从裸 safety refs 变成可 replay record，但目前成功路径仍由用户手动提交 record。为了接近真实 Binance testnet key 连通验证，需要一个受控 checker seam：入口能调用 checker，但默认不触网、不读 key、不假称连通。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 disabled `EXECUTION_VENUE_CONNECTIVITY_CHECKER`、`POST /api/research-os/execution/venue_connectivity_checks/run`；checker result 只接受 refs/hash/status |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 disabled no-write、fake checker success/QRO、checker raw payload/direct venue call report fail-closed |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与未验证边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 默认 checker disabled -> 422，不写 connectivity JSONL，不写 QRO。
2. fake checker success -> 写 `ExecutionVenueConnectivityCheckRecord`、QRO，返回 `checker_called=true`，但 `api_place_order_called=false` / `api_venue_call_called=false`。
3. checker result 带 raw order、raw venue payload、quantity、price、notional、明文 secret -> 422 且不写。
4. checker result 自报 direct `api_place_order_called` 或 `api_venue_call_called` -> 422 且不写。
5. checker result refs 与 order intent/runtime promotion 不一致 -> validator 拒。

## 红线 [按需]
- 不新增裸 `place_order`。
- 默认不触网、不读写真实 API key、不保存 raw order、raw venue payload、quantity、price、notional 或明文 secret。
- fake checker 只证明 seam，不证明真实 Binance testnet key 连通。
- A股 live connectivity 仍 unreachable。

## 非目标 [按需]
不实现真实 Binance testnet checker，不做 SecretRef 解密，不调用 testnet API，不生成 venue-native order payload，不证明 live broker connector。

## 验收一句话 [必填]
connectivity checker seam 可以被注入并产出受治理的 refs-only connectivity check；默认 disabled 时不能假连通、不能写证据。

## 完成记录
- 新增 disabled `EXECUTION_VENUE_CONNECTIVITY_CHECKER` adapter；默认调用 `/api/research-os/execution/venue_connectivity_checks/run` 会 422 且不写 JSONL/QRO。
- 新增 run endpoint：读取 recorded order intent + runtime promotion，调用注入 checker，拒 raw order/raw venue payload/quantity/price/notional/secret 和 direct place_order/venue-call report，再把 refs/hash/status 归一成 `ExecutionVenueConnectivityCheckRecord`，写 append-only registry 和 ExecutionPolicy QRO。
- 测试注入 fake checker，证明 seam 可被调用且成功响应 `checker_called=true`、`api_place_order_called=false`、`api_venue_call_called=false`。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 63 passed / 2 warnings；`PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 20 passed / 2 warnings；expanded Research OS/monitor/model/signal/execution/security scoped -> 195 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 refs-only checker seam，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。
