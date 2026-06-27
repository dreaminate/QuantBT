---
uuid: 41b7c9e2a0d5482a9f1e7a6b4c23d801
title: Compiler artifact entrypoint coverage producer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-goal-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1 unified object model; GOAL §7 Agent Shell; GOAL §8 governance spine; GOAL §14 platform compiler
depends_on: []
completed_at: 2026-06-27
---

# Compiler artifact entrypoint coverage producer

## Scope [必填]
把 `POST /api/research-os/compiler/artifacts` 接到 `GoalEntrypointCoverageRecord`，让 artifact manifest 成功记录时同步写 refs-only entrypoint coverage；coverage 验证必须先于 artifact 持久化，避免 silent mock 或坏上游留下 partial artifact。

## 上下文 / 动机 [按需]
`173405ef` 已让 `compile_qro` 和 direct compiler pass 成功路径写 coverage，但 compiler artifact endpoint 仍只写 artifact audit。GOAL §1/§7/§8/§14 的当前缺口是 compiler 产物层也要能回到 QRO / Research Graph / Compiler / Evidence refs ledger，而不是只停在 IR/pass。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_goal_entrypoint_coverage_from_compiler_artifact()`；artifact endpoint 先验证 artifact + coverage candidate，再写 artifact 和 coverage |
| `app/backend/tests/test_governed_compiler.py` | 覆盖 artifact success coverage、response ref、silent mock IR no-partial write |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 artifact coverage producer、测试数字和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. artifact manifest 成功记录后必须返回 `entrypoint_coverage_ref`，并新增一条 artifact-level coverage record。
2. artifact coverage 必须绑定已记录 IR/pass、QRO refs、Research Graph command refs、evidence/validation/permission refs 和 replay refs。
3. 历史 store 里存在 silent mock IR 时，artifact endpoint 必须 422，且不写 artifact、不写 coverage。
4. codegen/executable artifact claim 仍必须 422，且不得因为先前 pass coverage 存在而新增 artifact coverage。

## 红线 [按需]
- 不声称 artifact manifest 是 executable strategy、strategy code generator 或完整 compiler pass。
- 不复制 raw source、raw LLM output、secret 或 runtime payload 到 coverage。
- 不把本地测试通过说成 CI、线上或用户验收。

## 非目标 [按需]
不实现策略代码生成、不实现完整 compiler backend、不实现 scheduler wiring、不实现外部 artifact publish 或前端 artifact coverage 管理 UI。

## 验收一句话 [必填]
compiler artifact manifest endpoint 现在会写 refs-only entrypoint coverage；silent mock IR 或 fake codegen artifact 失败时不留下 artifact/coverage partial record。

## 完成记录
- 新增 `_goal_entrypoint_coverage_from_compiler_artifact()`，从已记录 IR/pass 和 artifact manifest 派生 QRO、Graph command、Compiler IR/pass、evidence、validation、permission、canonical、lifecycle 和 replay refs。
- `POST /api/research-os/compiler/artifacts` 现在先验证 artifact，再预验证 artifact coverage candidate，随后才写 artifact JSONL 和 coverage JSONL，并返回 `entrypoint_coverage_ref`。
- 对抗测试覆盖 artifact success coverage、codegen claim 不新增 artifact coverage、silent mock IR artifact coverage no-partial。
- 验证：goal/compiler scoped -> **32 passed / 2 warnings**；goal/compiler/spine/methodology/trust adjacent -> **71 passed / 2 warnings**；`python -m compileall -q app/backend/app` -> PASS。
