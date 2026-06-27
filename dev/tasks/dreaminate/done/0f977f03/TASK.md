---
uuid: 0f977f0320dd44249f56bea2eed7ba84
title: Execution order intent requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §11 market data use gate -> §12 execution boundary
depends_on: [e29078914b9a448ba631837c548a4a16]
completed_at: 2026-06-27
---

# Execution order intent requires MarketDataUse validation

## Scope [必填]
让 paper/testnet/live `ExecutionOrderIntentRecord` 必须引用 accepted `MarketDataUseValidationRecord`，并在 API 层从 `MARKET_DATA_REGISTRY` 验证 ref；成功 QRO 记录该 ref。坏 ref 或缺 ref 不写 order intent，不写 Graph。

## 上下文 / 动机 [按需]
`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO，但执行意图仍可不引用它。GOAL §11 要求 Data/Policy 在 paper/testnet/live 可达环境内保持同一资产引用和 lineage；GOAL §12 要求执行边界不能绕过标的能力和权限语义。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | `ExecutionOrderIntentRecord` 增加 `market_data_use_validation_ref`；validator 要求 execution runtimes 引用 accepted ref |
| `app/backend/app/main.py` | order intent API 从 `MARKET_DATA_REGISTRY` 校验 use validation，并把 ref 写入 ExecutionPolicy QRO |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖缺 ref、unknown ref no-write、accepted ref success/QRO/summary |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. TESTNET/LIVE order intent 缺 `market_data_use_validation_ref` -> validator 拒。
2. API 引用 unknown market-data use validation -> 422，不写 order intent，不写 QRO。
3. API 引用 accepted market-data use validation -> 写 order intent + QRO，summary 暴露 ref。
4. QRO evidence/lineage/input/output contract 包含 market-data use validation ref，但不复制 market-data raw payload。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 通过说成真实数据已下载或 live permission 已验证。
- 不保存 raw data rows、raw order payload、quantity、price、notional 或 secret。

## 非目标 [按需]
不强制 StrategyBook/portfolio promote 引用 market-data use validation，不实现 strategy builder 接线，不实现真实 connector 或 venue permission check。

## 验收一句话 [必填]
ExecutionOrderIntent 进入 paper/testnet/live 前必须引用 accepted MarketDataUse validation；缺失/未知 ref fail-closed 且不写 partial。

## 完成记录
- `ExecutionOrderIntentRecord` 新增 `market_data_use_validation_ref`，hash identity、parser、summary 和 QRO input/output/evidence/lineage 均包含该 ref；仍不保存 raw data rows、raw order、quantity、price、notional 或 secret。
- `validate_execution_order_intent` 对 `paper/testnet/live` runtime 要求 `market_data_use_validation_ref`；传入 `known_market_data_use_validation_refs` 时，ref 不在 accepted set 会拒。
- `PersistentExecutionOrderIntentRegistry.record_intent` 支持 `known_market_data_use_validation_refs`，用于 API 层强校验；历史 replay 仍验证 ref 存在性，不尝试读取外部 registry。
- `POST /api/research-os/execution/order_intents` 在写入前调用 `MARKET_DATA_REGISTRY.use_validation(ref)`，要求 record `accepted=true`；unknown ref 或 not accepted 会 422，order intent JSONL 和 Research Graph 均不写。
- 测试覆盖：validator 缺 ref、unknown ref；API accepted ref success/QRO/summary；API unknown ref no-write。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_execution_boundary_contract.py` -> 78 passed / 2 warnings；market-data/execution/Graph/entrypoint/model/compiler/RDP adjacent scoped -> 228 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 execution order intent 对 accepted MarketDataUse validation 的 refs-only 强制引用，不是 strategy builder 接线、StrategyBook/portfolio promote 全入口强制引用、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或全资产自动同步。
