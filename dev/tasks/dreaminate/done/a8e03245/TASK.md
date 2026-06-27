---
uuid: a8e03245b9d244cc92d98dc5fe29d9c3
title: Trust release check producer API and RDP UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-release-check-producer
source: goal-gap
source_ref: GOAL §13 Trust Layer release checks; GOAL §17 RDP publish release gate
depends_on: [1058c62d585a4c3d8c00e42d1f67ac85, e9c58149730a40109bc11eea5758f108]
completed_at: 2026-06-27
---

# Trust release check producer API and RDP UI

## Scope [必填]
新增 §13 Trust Release Check producer seam：后端可记录 release gate 六类检查的 `check_ref`、scenario、expected/observed behavior、evidence refs、validation refs 和 source hash；summary 可 replay；RDP export desk 可提交 release check，并把返回的 `check_ref` 回填到对应 release gate 字段。

## 上下文 / 动机 [按需]
`1058c62d` 已给 RDP export desk 加了 Trust Release Gate 管理 UI，但六类检查 refs 仍只能手填。发布面可以登记 gate，却没有受控 producer 生成 anti-flattery、multi-turn、expert veto、weakness collapse、mock honesty、cold-start honesty 的 refs。本卡补 refs producer，不把它包装成外部专家工作流或真实 CI release。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 `TrustReleaseCheckRecord`、validator、producer、append-only registry/replay |
| `app/backend/app/main.py` | 新增 `TRUST_RELEASE_CHECK_REGISTRY`、`POST /api/research-os/trust/release_checks`、trust summary checks |
| `app/backend/app/research_os/__init__.py` | 导出 release check 类型/helper/registry |
| `app/backend/tests/test_trust_layer.py` | 覆盖 producer refs/hash/replay、坏 kind、行为 mismatch、silent mock no-write、API summary |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新增 release check 列表、Record check 表单、成功后回填 gate 字段 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 release check payload、summary 刷新、gate 字段回填、缺字段不打后端 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. unknown `check_kind` 必须拒绝。
2. `observed_behavior_ref` 与 `expected_behavior_ref` 不一致必须拒绝。
3. `silent_mock_fallback_used=true` 必须拒绝，registry 不写。
4. 缺 evidence refs 或 validation refs 必须拒绝。
5. 前端缺 required refs 时不调用 `/api/research-os/trust/release_checks`。
6. 成功记录 release check 后，UI 必须把 `check_ref` 填入对应 release gate 字段。

## 红线 [按需]
- 不声称 release check producer 已运行真实外部专家审查。
- 不声称 release check producer 已执行真实 CI release、线上发布或用户验收。
- 不允许 silent mock fallback 进入 release check 记录。

## 非目标 [按需]
不实现外部专家工作流、自动 agent 压力测试 runner、CI release、线上 release approval、外部 object store publish 或生产发布证明。

## 验收一句话 [必填]
RDP export desk 现在能从同一发布面生成 Trust Release Check refs，并把生成 refs 填入 release gate draft，减少手填未知 refs 的 release gate 缺口。

## 完成记录（2026-06-27）
- 新增 `TrustReleaseCheckRecord`、`validate_trust_release_check()`、`record_trust_release_check()` 和 `PersistentTrustReleaseCheckRegistry`。
- 新增 `/api/research-os/trust/release_checks`；trust summary 返回 `release_check_total` 与 `release_checks`。
- `validate_trust_layer` 可同时校验 release gates 与 release checks。
- RDP export desk 新增 release checks 列表和 Record check 表单；成功记录后刷新 summary，并把返回的 `check_ref` 回填到对应 release gate 字段。
- 本地验证：
  - `python -m pytest app/backend/tests/test_trust_layer.py -q` -> 16 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_os_rdp_publish.py -q` -> 8 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py -q` -> 24 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 12 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx --run` -> 4 files / 64 tests passed。
  - `cd app/frontend && npm test -- --run` -> 29 files / 318 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1841 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；240 cards）。
  - `git diff --check` -> PASS。
