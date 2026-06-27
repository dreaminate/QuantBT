---
uuid: 0b3f6a918e904d96b8756f0c6c672bb9
title: Compiler artifact Mathematical Spine hard reference gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-mathematical-spine
source: goal-gap
source_ref: GOAL §6 Research/Document/Math; GOAL §8 governance spine; GOAL §9 factor/model/signal/strategy boundary; GOAL §14 platform compiler
depends_on: []
completed_at: 2026-06-27
---

# Compiler artifact Mathematical Spine hard reference gate

## Scope [必填]
让 `CompilerArtifactRecord` 必须携带 `mathematical_spine_chain_refs`，并让 artifact API 写入前确认每个 chain ref 已登记在 `MATHEMATICAL_SPINE_CHAIN_REGISTRY`，防止 compiler artifact manifest 绕过 Mathematical Spine full-chain refs。

## 上下文 / 动机 [按需]
`ecc6b957` 已有 MathematicalSpineChain registry/API，但 producer 路径还没有把它作为硬引用。`41b7c9e2` 已让 artifact manifest 写 entrypoint coverage，本卡继续把 artifact manifest 产物层绑定到已登记的 Mathematical Spine chain，不从 artifact 字段伪造 full-chain。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/compiler.py` | `CompilerArtifactRecord` 新增 `mathematical_spine_chain_refs`，validator 要求非空 |
| `app/backend/app/main.py` | artifact payload/summary/response 暴露 chain refs；写 artifact 前校验 chain ref 已登记 |
| `app/backend/tests/test_governed_compiler.py` | 覆盖 replay、summary、missing chain refs、unknown chain refs no-partial |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 compiler artifact math-spine hard ref gate 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `CompilerArtifactRecord` 缺 `mathematical_spine_chain_refs` 必须被 validator 拒绝。
2. artifact API 引用未登记的 chain ref 必须 422，且不写 artifact、不新增 coverage。
3. artifact replay/summary/response 必须保留 `mathematical_spine_chain_refs`。
4. artifact coverage lifecycle refs 必须带 artifact ref 和 mathematical spine chain ref。

## 红线 [按需]
- 不从 artifact manifest 自动生成 full-chain MathematicalSpineChain。
- 不声称所有 producer 或所有 promotion path 已经把 Mathematical Spine 作为硬门。
- 不把本地测试通过说成 CI、线上或用户验收。

## 非目标 [按需]
不实现全链数学推导、不实现所有 producer 自动写 chain record、不实现 strategy code generator、不实现完整 compiler pass 或前端管理 UI。

## 验收一句话 [必填]
compiler artifact manifest 现在必须引用已登记的 Mathematical Spine chain；缺 refs 或 unknown chain ref 失败时不留下 artifact/coverage partial record。

## 完成记录
- `CompilerArtifactRecord` 新增并持久化 `mathematical_spine_chain_refs`，validator 将其纳入 required refs。
- `POST /api/research-os/compiler/artifacts` 写入前校验每个 chain ref 已在 `MATHEMATICAL_SPINE_CHAIN_REGISTRY` 中登记。
- artifact response/summary/replay 暴露 chain refs，entrypoint coverage lifecycle refs 同步绑定 artifact ref + chain ref。
- 验证：`pytest app/backend/tests/test_governed_compiler.py -q` -> **20 passed / 2 warnings**；goal/compiler scoped -> **33 passed / 2 warnings**；goal/compiler/spine/methodology/trust adjacent -> **72 passed / 2 warnings**。
