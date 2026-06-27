---
uuid: 951b443b9a3143b6b381f7b8cea05d63
title: Execution guarded submission runner seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 venue-backed order emission entry seam
depends_on: [7ace6793d4c74e0fae670a8728e8947c]
completed_at: 2026-06-27
---

# Execution guarded submission runner seam

## Scope [必填]
新增 refs-only guarded submission runner API：从 recorded ready `submit_request_ref` 解析 order intent、runtime promotion、materialization、venue capability，并构造 `ExecutionOrderSubmissionRecord`。默认 `EXECUTION_ORDER_SUBMITTER` disabled；只有注入 submitter 时才调用 guarded seam，输出仍走 submission validator、append-only registry 和 ExecutionPolicy QRO。

## 上下文 / 动机 [按需]
`7ace6793` 已让 submit request envelope 可以由 builder seam 生成，但实际 submission 仍要手工 POST 完整 refs。终态要有明确的 submit request → guarded submission 入口，同时继续阻断裸 `place_order`、raw venue payload 和未治理 submitter。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `POST /api/research-os/execution/order_submissions/run`；只接 `submit_request_ref`，默认 submitter disabled no-write，fake submitter success 写 submission/QRO |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 disabled no-write、fake submitter success/QRO、submitter raw payload/direct place_order report fail-closed |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与未验证边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 默认 submitter disabled -> 422，不写 submission JSONL，不写 QRO。
2. fake submitter success -> 写 `ExecutionOrderSubmissionRecord`、QRO，返回 `submitter_called=true`，但 `api_place_order_called=false` / `api_venue_call_called=false`。
3. submitter result 带 raw order、raw venue payload、quantity、price、notional、明文 secret -> 422 且不写。
4. submitter result 自报 direct `api_place_order_called` 或裸 venue call -> 422 且不写。
5. submit_request 非 ready 或 refs 与上游不一致 -> validator 拒。

## 红线 [按需]
- 不新增裸 `place_order`。
- 默认不触网、不读写真实 API key、不保存 raw order、raw venue payload、quantity、price、notional 或明文 secret。
- fake submitter 只证明 seam，不证明真实 Binance testnet key 连通、真实 order emission 或 broker connector。
- A股 live submit/runner 仍 unreachable。

## 非目标 [按需]
不实现真实 Binance submitter，不调用 testnet API，不解密 SecretRef，不提交订单，不证明 live broker connector。

## 验收一句话 [必填]
guarded submission runner 可以从 ready submit request 进入受控 submitter seam；默认 disabled 时不能假提交、不能写证据。

## 完成记录
- 新增 `/api/research-os/execution/order_submissions/run`；只接 `submit_request_ref`，解析 recorded submit request、order intent、runtime promotion、materialization、venue capability 后构造 `ExecutionOrderSubmissionRecord`。
- 默认 `EXECUTION_ORDER_SUBMITTER` disabled 时 422 且不写 JSONL/QRO；注入 fake submitter 成功时写 append-only submission registry 和 ExecutionPolicy QRO。
- runner 继续拒 raw order/raw venue payload/quantity/price/notional/secret，拒自报 direct `place_order` 或 direct venue API call。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 71 passed / 2 warnings；`PYTHONPATH=app/backend pytest -q app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py` -> 20 passed / 2 warnings；expanded Research OS/monitor/model/signal/execution/security scoped -> 203 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 refs-only guarded submission runner seam，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector 或资金执行。
