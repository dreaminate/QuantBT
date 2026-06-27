---
uuid: ee8040b930444d8f88b014dd4e62d91a
title: Model Registry promotion compiles Model QRO into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance-entrypoint
source: goal-gap
source_ref: GOAL §1/§7/§8/§14/§15 Model Registry promotion QRO -> Graph -> Compiler -> Evidence coverage
depends_on: [6c3d8f21c6f14d2d8f7f4c2b9a6e1d42, e4f2a1c9a0c54e0fb624b1dcb8a0c4d7, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83, 54b60744f2564ecc8fd9ef8733b26810]
completed_at: 2026-06-27
---

# Model Registry promotion compiles Model QRO into entrypoint coverage

## Scope [必填]
把 Model Registry promotion 的 pending、rejected、approved 三条 Model QRO 继续接到 Governed Compiler 和 GOAL entrypoint coverage。`/api/models/{model_id}/promote` 与 `/api/models/{model_id}/gates/{gate_id}/approve` 返回 QRO refs 的同时返回 compiler/coverage refs。

## 上下文 / 动机 [按需]
`6c3d8f21` 和 `e4f2a1c9` 已让 Model Registry promotion 成功开门、审批成功和拒绝路径写 Model QRO/Research Graph command，但这些入口仍未自动生成 compiler IR/pass 和 entrypoint coverage。GOAL §15 的模型治理对象需要进入统一 QRO -> Graph -> Compiler -> Evidence/Validation 链。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `_record_model_promotion_request_qro` 和 `_record_model_promotion_approval_qro` 写 Graph 后调用 `_compile_model_registry_qro` |
| `app/backend/tests/test_model_governance.py` | 隔离 compiler/coverage store；覆盖 pending、rejected、approved 三条路径返回 refs、绑定同一 QRO/command、不泄露 raw evidence/gaps/reason |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 Model Registry promotion compiler coverage 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. promotion pending 响应必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`，coverage entrypoint 是 `api:models.promote`。
2. promotion rejected 的 422 detail 必须同样返回 compiler/coverage refs，且不复制中文 gap/verdict、DSR/PBO 或 champion challenger raw evidence。
3. approval 响应必须返回 compiler/coverage refs，coverage entrypoint 是 `api:models.gates.approve`，且不复制 approval reason 或 risk restatement 正文。
4. compiler IR/pass/coverage 必须绑定同一个 Model QRO 与 Research Graph command，并保留 ModelPassport / ValidationDossier validation refs。

## 红线 [按需]
- 不允许把 promotion compiler coverage 说成 live serving、safe loading execution 或交易权限。
- 不允许把 raw evidence、gap text、approval reason、metrics 或 artifact path 放进 compiler/coverage。
- 不削弱 approver≠creator、passport、validation dossier 和 approval gate 既有门。

## 非目标 [按需]
不实现完整 compiler codegen、runtime auto-promotion、live model serving、container sandbox、remote artifact store、CI 或外部监控系统回路。

## 验收一句话 [必填]
Model Registry promotion 的 pending、rejected、approved 三条 API QRO 现在都会自动生成 governed compiler IR/pass 和 entrypoint coverage；响应可审计 refs，但不泄露 raw evidence、gap text 或 approval rationale。

## 完成记录（2026-06-27）
- 新增 `_compile_model_registry_qro`，复用既有 `_compile_qro_payload` 和 coverage validator。
- `_record_model_promotion_request_qro` 和 `_record_model_promotion_approval_qro` 返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- 本地验证：
  - `pytest app/backend/tests/test_model_governance.py -q` -> 31 passed / 2 warnings。
