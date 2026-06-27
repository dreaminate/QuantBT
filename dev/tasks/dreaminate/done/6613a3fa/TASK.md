---
uuid: 6613a3fabca6448d867227222dcebc8b
title: Execution venue event ingester seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue ack/fill evidence ingestion
depends_on: [951b443b9a3143b6b381f7b8cea05d63]
completed_at: 2026-06-27
---

# Execution venue event ingester seam

## Scope [必填]
新增 refs-only venue event ingester seam/API：从 recorded submission 触发注入式 ingester，生成单条 `ExecutionVenueEventRecord`（submitted/accepted/rejected/fill/cancel/reconcile refs）。默认 ingester disabled；fake ingester 只证明 seam，输出仍走 venue event validator、append-only registry 和 ExecutionPolicy QRO。

## 上下文 / 动机 [按需]
`951b443b` 已把 ready submit request 推进到 guarded submission runner，但 venue ack/fill event 仍只能手工 POST。终态需要 submission → venue event evidence 的受控入口，同时不能保存 raw venue payload 或假称真实交易所连通。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 disabled `EXECUTION_VENUE_EVENT_INGESTER`、`POST /api/research-os/execution/venue_events/run` |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 disabled no-write、fake ingester success/QRO、raw payload/direct venue call report fail-closed |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与未验证边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 默认 ingester disabled -> 422，不写 venue event JSONL，不写 QRO。
2. fake ingester success -> 写 `ExecutionVenueEventRecord`、QRO，返回 `ingester_called=true`，但 `api_place_order_called=false` / `api_venue_call_called=false`。
3. ingester result 带 raw venue payload、raw order、quantity、price、notional、明文 secret -> 422 且不写。
4. ingester result 自报 direct venue API call -> 422 且不写。
5. fill event 缺 fill/quantity/price refs -> validator 拒。

## 红线 [按需]
- 不新增裸 `place_order`。
- 默认不触网、不读写真实 API key、不保存 raw order、raw venue payload、quantity、price、notional 或明文 secret。
- fake ingester 只证明 seam，不证明真实 Binance testnet ack/fill ingest。
- A股 live venue event ingest 仍 unreachable。

## 非目标 [按需]
不实现真实 Binance event fetcher，不调用 testnet API，不解密 SecretRef，不做 websocket/streaming，不证明 live broker connector。

## 验收一句话 [必填]
venue event ingester seam 可以从 recorded submission 生成受治理的 refs-only venue event；默认 disabled 时不能假 ingest、不能写证据。

## 完成记录
- 新增 disabled `EXECUTION_VENUE_EVENT_INGESTER` adapter；默认调用 `/api/research-os/execution/venue_events/run` 会 422 且不写 JSONL/QRO。
- 新增 run endpoint：只接 `submission_ref`，解析 recorded submission、order intent、runtime promotion；调用注入 ingester 后，拒 raw order/raw venue payload/quantity/price/notional/secret 和 direct place_order/venue-call report，再把 refs/hash/status 归一成 `ExecutionVenueEventRecord`，写 append-only registry 和 ExecutionPolicy QRO。
- 测试注入 fake ingester，证明 seam 可被调用且成功响应 `ingester_called=true`、`api_place_order_called=false`、`api_venue_call_called=false`；fill event 缺 fill/quantity/price refs 会被 validator 拒绝。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 76 passed / 2 warnings；`PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 20 passed / 2 warnings；expanded Research OS/monitor/model/signal/execution/security scoped -> 208 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 refs-only venue event ingester seam，不是真实 Binance testnet ack/fill ingest、真实 venue API 连通、live trading、broker connector 或资金执行。
