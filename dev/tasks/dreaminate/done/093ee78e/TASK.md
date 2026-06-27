---
uuid: 093ee78e3a2249f7bb7a7c5cb5649e45
title: Execution QRO producers compile into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-compiler-coverage
source: goal-gap
source_ref: GOAL §0/§1/§8/§9/§12/§14 execution QRO -> Graph -> Compiler -> Coverage
depends_on: [8f2d4b0ca419429799a93c35b57e3908, 0d9a6e42a419429799a93c35b57e3908, 709450a48ad1491b82f16a76556ed107, ac0ad93d5f534a539dc1ad44ba2a6080, 8d15d10c3b8e4781a99b5047b23a8dda, 4393d50ab099412aa29542151381e7cd, 98d6bf4a940247f89e09e9bf01f70eb1, 9ca190206ba841f583ffe02215cbccbd, 23f80fa8125548cba15f9fba5227a466, 951b443b9a3143b6b381f7b8cea05d63, 3b6e9c12a419429799a93c35b57e3908, 4a7d2e90a419429799a93c35b57e3908, 0c4d71a9a419429799a93c35b57e3908, 6e4a9b21a419429799a93c35b57e3908, d4c9a2f0a419429799a93c35b57e3908, a91b0c63a419429799a93c35b57e3908, 9d175460a9f24650964a250304c44d83, 173405ef47f942ba9929a4c356483d07]
completed_at: 2026-06-27
---

# Execution QRO producers compile into entrypoint coverage

## Scope [必填]
把已有 execution boundary QRO producer 接到 governed compiler IR/pass 和 GOAL entrypoint coverage：order intent、runtime promotion、order materialization、venue connectivity check、venue safety attestation、venue capability、submit request、order submission、venue event、reconciliation、reconciliation action。只做 refs-only compiler coverage，不实现真实 venue connector、真实下单、资金执行、线上长期 scheduler 或完整 strategy compiler。

## 上下文 / 动机 [按需]
`8f2d4b0c` 到 `a91b0c63` 已把 execution ladder 写成 append-only registry、ExecutionPolicy QRO 和 Research Graph command。`9d175460` / `173405ef` 已有 compiler IR/pass 与 entrypoint coverage 基建。GOAL §12 当前缺口是 execution 成功路径还停在 QRO/Graph，没有把入口覆盖证据连到 compiler/coverage spine。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_compile_execution_boundary_qro`，并在 11 个 execution QRO producer 成功写 Graph 后生成 compiler IR/pass/entrypoint coverage refs |
| `app/backend/tests/test_execution_boundary_contract.py` | 隔离 compiler/coverage stores；覆盖 17 条成功路径的 response refs、store 回查、entrypoint_ref、refs-only audit flags |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 每个 execution API 成功响应必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
2. Coverage `entrypoint_ref` 必须匹配真实入口，例如 `api:research_os.execution.order_submissions`，不能全部写成一个泛化入口。
3. Compiler IR 必须绑定同一个 QRO 和同一个 Research Graph command。
4. Compiler pass 必须保持 `entry_source=api`，且 `direct_graph_mutation=false`、`bypassed_permission=false`、`raw_llm_output_embedded_as_ir=false`。
5. Coverage 必须保持 `silent_mock_fallback_used=false`、`raw_payload_persisted=false`；compiler audit 不得复制 raw order、raw event 或 secret material。

## 红线 [按需]
- 不把 refs-only compiler coverage 说成完整 compiler implementation、codegen、operation replay/revert、真实交易执行、真实 venue 连通、CI 通过、线上运行或用户验收。
- 不把 injected fake materializer/checker/builder/submitter/ingester 测试说成真实交易所 adapter。
- 不把 weekly monitor 本地 tick 说成部署级长期 scheduler 证明。

## 非目标 [按需]
不做 Binance testnet key 连通、venue-native payload、资金账户、order emission、真实 fill reconciliation worker、长期 scheduler 运行证明、生产部署或所有非 execution entrypoint 的 compiler coverage。

## 验收一句话 [必填]
Execution ladder 的 11 类 QRO producer 成功路径现在都会自动生成 governed compiler IR/pass 和 GOAL entrypoint coverage，且测试证明 coverage 可按入口回查，审计对象只保留 refs/hash/flags。

## 完成记录（2026-06-27）
- 新增 `_compile_execution_boundary_qro`，复用 `_compile_entrypoint_qro` 写 compiler IR/pass 与 entrypoint coverage。
- order intent、runtime promotion、materialization、connectivity、safety attestation、capability、submit request、order submission、venue event、reconciliation、reconciliation action 的 QRO producer 成功路径均返回 compiler/coverage refs。
- `test_execution_boundary_contract.py` 覆盖 17 条 execution 成功路径，检查 entrypoint_ref、QRO/Graph 绑定和 raw payload 不落 coverage。
- 本地验证：
  - `pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 78 passed / 2 warnings。
  - `pytest app/backend/tests/test_governed_compiler.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_monitor_production.py -q` -> 40 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
