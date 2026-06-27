---
uuid: 114709007e9048ec9fbeb1f9ed9fd310
title: Governed Compiler artifact manifest audit layer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-compiler
source: goal-gap
source_ref: GOAL §1/§8 governed compiler output artifact gap
depends_on: [9d175460a9f24650964a250304c44d83]
---

# Governed Compiler artifact manifest audit layer

## Scope [必填]
新增 Governed Compiler 的 artifact manifest 审计层：已记录的 Compiler IR/pass 可以产出一个非可执行、引用式 manifest record，要求绑定 IR、pass、Research Graph command、canonical command、run plan、environment lock、permission、output contract、manifest hash、evidence 和 validation refs。该层不生成策略源码，不声称策略可执行。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/compiler.py` | 新增 `CompilerArtifactRecord`、`validate_compiler_artifact`、persistent artifact event/replay 和悬空 IR/pass 引用校验 |
| `app/backend/app/research_os/__init__.py` | 导出 artifact record 与 validator |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/compiler/artifacts`，summary 返回 artifact_total/artifacts |
| `app/backend/tests/test_governed_compiler.py` | 覆盖 manifest refs、fake codegen 拒绝、store replay、API 成功和 API 拒绝 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. artifact manifest 缺 `source_ir_refs` / `compiler_pass_refs` / canonical/evidence/validation refs 必须拒绝。
2. `artifact_kind=strategy_source/executable_strategy`、`executable=true`、`contains_source_code=true` 必须拒绝，避免把 manifest 冒充 codegen。
3. `raw_llm_output_embedded`、`plaintext_secret_embedded`、`silent_mock_fallback` 必须拒绝。
4. artifact 引用未记录 IR/pass 必须拒绝，不写 partial event。
5. JSONL restart replay 后 artifact manifest 必须仍可查。

## 验收一句话 [必填]
Governed Compiler 现在能持久化、查询和重放非可执行 artifact manifest；这仍不是完整 compiler pass implementation、策略代码生成器、scheduler wiring 或 production compiler service。

## 完成记录（2026-06-27）
- 新增 `CompilerArtifactRecord` 与 artifact validator，拒绝 source generation claim、executable claim、embedded source code、raw LLM output、plaintext secret 和 silent mock fallback。
- `PersistentCompilerIRStore` 支持 `compiler_artifact_recorded` JSONL event；artifact 写入时要求 source IR 与 compiler pass 已存在，且 pass output IR 必须属于 artifact source IR。
- 新增 `POST /api/research-os/compiler/artifacts`；`GET /api/research-os/compiler/summary` 返回 `artifact_total` 和 artifact summaries。
- 已验证：
  - `python -m compileall -q app/backend/app/research_os/compiler.py app/backend/app/research_os/__init__.py app/backend/app/main.py app/backend/tests/test_governed_compiler.py` -> success。
  - `cd app/backend && python -m pytest tests/test_governed_compiler.py -q` -> 16 passed / 2 warnings。
  - `cd app/backend && python -m pytest tests/test_governed_compiler.py tests/test_research_graph_persistence.py tests/test_desk_projection.py tests/test_research_os_spine.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py -q` -> 80 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1539 passed / 13 skipped / 283 warnings。
- 边界：这不是完整 compiler pass implementation、策略代码生成、canvas mutation engine、scheduler wiring 或 production compiler service。
