---
uuid: 9d175460a9f24650964a250304c44d83
title: Governed Compiler compile QRO pass API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-compiler
source: goal-gap
source_ref: GOAL §1/§7/§8/§14/§16 compiler pass implementation gap
depends_on: [62fdfebdbd764c8f84ce527fed458e71, 7ba4a8b9cdce4d57b95d78406a57f129, 5bb5d9da2f75469580ebbc74edf456fd]
---

# Governed Compiler compile QRO pass API

## Scope [必填]
新增第一条真实 governed compiler pass：从已存在的 Research Graph QRO command 编译出 `CompilerIRRecord` 和 `CompilerPassRecord`。endpoint 必须先找 Graph 中的 QRO，不得接收 raw LLM output 直接成 IR；必须要求 validation refs、environment lock、permission/evidence refs，并先 validate IR/pass，再写 Compiler store，避免 partial write。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_compile_qro_payload` 和 `POST /api/research-os/compiler/compile_qro` |
| `app/backend/tests/test_governed_compiler.py` | 覆盖 Graph QRO→Compiler IR/pass 成功、未知 QRO fail-closed、缺 evidence_refs 不写 partial |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 成功路径必须从 `RESEARCH_GRAPH_STORE.commands()` 找到 QRO command，并把 qro id、graph command id、canonical command ref 写进 IR/pass。
2. `qro_id` 不在 Research Graph 时必须 422，Compiler store 不得创建 JSONL。
3. QRO/command 没有 evidence refs 时必须 422，不能把 command id 伪造成证据。
4. endpoint 必须要求 validation refs 和 environment lock，防止 compiler pass 被包装成已验证实现。

## 验收一句话 [必填]
Governed Compiler 现在有第一条从 Research Graph QRO 派生 IR/pass 的 deterministic compile pass；这仍不是完整策略代码生成器或全入口 compiler wiring。

## 完成记录（2026-06-27）
- 新增 `POST /api/research-os/compiler/compile_qro`。
- endpoint 从 Research Graph command log 查 `upsert_qro` payload，派生 `CompilerIRRecord` + `CompilerPassRecord`，写入同一 `PersistentCompilerIRStore`。
- 必填 `validation_refs` 和 `environment_lock_ref`；缺 QRO、缺 evidence refs、缺 permission ref 均 fail-closed。
- 写入前先跑 `validate_compiler_ir` 与 `validate_compiler_pass`，避免 partial write。
- 已验证：
  - `cd app/backend && python -m pytest tests/test_governed_compiler.py -q` -> 11 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/main.py app/backend/tests/test_governed_compiler.py` -> success.
  - `cd app/backend && python -m pytest tests/test_governed_compiler.py tests/test_research_graph_persistence.py tests/test_research_os_spine.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py -q` -> 66 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1531 passed / 13 skipped / 283 warnings。
- 边界：这不是完整 compiler pass implementation、策略代码生成、canvas mutation engine、scheduler wiring 或 production compiler service。
