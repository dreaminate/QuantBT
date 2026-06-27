---
uuid: 7ace6793d4c74e0fae670a8728e8947c
title: Execution submit request builder seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue-native submit envelope generation
depends_on: [9ca190206ba841f583ffe02215cbccbd, 8d15d10c3b8e4781a99b5047b23a8dda]
completed_at: 2026-06-27
---

# Execution submit request builder seam

## Scope [必填]
新增 refs-only submit request builder seam/API：从 recorded order intent、runtime promotion、materialized order、ready venue capability 生成 `ExecutionSubmitRequestRecord`。默认 builder disabled；只有测试或后续真实 connector 显式注入 builder 时才会产出 submit request schema/hash/client-order refs。输出仍走 submit request validator、append-only registry 和 ExecutionPolicy QRO。

## 上下文 / 动机 [按需]
`9ca19020` 已把 submit request envelope 落成 registry/API/QRO，但成功路径仍靠用户手工提交 refs。终态的 venue-backed order emission 需要一个受控 builder seam：能把 materialized order hash 和 venue capability 变成 refs-only submit request envelope，同时不暴露 raw order/venue payload。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 disabled `EXECUTION_SUBMIT_REQUEST_BUILDER`、`POST /api/research-os/execution/submit_requests/run`；builder result 只接受 refs/hash/status |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 disabled no-write、fake builder success/QRO、builder raw payload/direct venue call report fail-closed |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与未验证边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 默认 builder disabled -> 422，不写 submit request JSONL，不写 QRO。
2. fake builder success -> 写 `ExecutionSubmitRequestRecord`、QRO，返回 `builder_called=true`，但 `api_place_order_called=false` / `api_venue_call_called=false`。
3. builder result 带 raw order、raw venue payload、quantity、price、notional、明文 secret -> 422 且不写。
4. builder result 自报 direct `api_place_order_called` 或 `api_venue_call_called` -> 422 且不写。
5. builder result refs 与 materialization/capability/order intent/runtime promotion 不一致 -> validator 拒。

## 红线 [按需]
- 不新增裸 `place_order`。
- 默认不触网、不读写真实 API key、不保存 raw order、raw venue payload、quantity、price、notional 或明文 secret。
- fake builder 只证明 seam，不证明真实 venue-native payload builder 或真实 Binance testnet key 连通。
- A股 live submit request 仍 unreachable。

## 非目标 [按需]
不实现真实 Binance submit request builder，不调用 testnet API，不解密 SecretRef，不提交订单，不证明 live broker connector。

## 验收一句话 [必填]
submit request builder seam 可以被注入并产出受治理的 refs-only submit request；默认 disabled 时不能假生成、不能写证据。

## 完成记录
- 新增 disabled `EXECUTION_SUBMIT_REQUEST_BUILDER` adapter；默认调用 `/api/research-os/execution/submit_requests/run` 会 422 且不写 JSONL/QRO。
- 新增 run endpoint：读取 recorded order materialization + ready venue capability，并解析对应 order intent/runtime promotion；调用注入 builder 后，拒 raw order/raw venue payload/quantity/price/notional/secret 和 direct place_order/venue-call report，再把 refs/hash/status 归一成 `ExecutionSubmitRequestRecord`，写 append-only registry 和 ExecutionPolicy QRO。
- 测试注入 fake builder，证明 seam 可被调用且成功响应 `builder_called=true`、`api_place_order_called=false`、`api_venue_call_called=false`。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 67 passed / 2 warnings；`PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 20 passed / 2 warnings；expanded Research OS/monitor/model/signal/execution/security scoped -> 199 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 refs-only submit request builder seam，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native raw payload 生成或资金执行。
