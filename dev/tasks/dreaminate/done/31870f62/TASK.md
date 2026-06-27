---
uuid: 31870f62e76940199bc06a23328e1a69
title: RDP manifest upstream compiler coverage and math spine gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: GOAL §0 Research-to-Execution OS; GOAL §1 object model; GOAL §6 Research/Document/Math; GOAL §8 governance spine; GOAL §13 trust layer; GOAL §17 delivery standard
depends_on: [173405ef47f942ba9929a4c356483d07, 41b7c9e2a0d5482a9f1e7a6b4c23d801, 0b3f6a918e904d96b8756f0c6c672bb9, e9c58149730a40109bc11eea5758f108]
completed_at: 2026-06-27
---

# RDP manifest upstream compiler coverage and math spine gate

## Scope [必填]
让 Research Delivery Package manifest 本身必须引用已登记的 compiler artifact、Mathematical Spine chain 和 GOAL entrypoint coverage，防止 RDP 只带 graph/data/math 字符串而绕过 QRO -> Graph -> Compiler -> Evidence/Mathematical Spine 的上游硬门。

## 上下文 / 动机 [按需]
`173405ef` 已有 entrypoint coverage registry/API，`41b7c9e2` 已让 compiler artifact 写 coverage，`0b3f6a91` 已让 compiler artifact 强制引用已登记 Mathematical Spine chain，`e9c58149` 已让 RDP publish 强制 trust release gate。剩余缺口是 RDP manifest registry/materialize/archive/publish 仍可只声明普通 refs，不要求引用上述已登记上游记录。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | `RDPManifest` 新增 `compiler_artifact_refs`、`mathematical_spine_chain_refs`、`goal_entrypoint_coverage_refs`；validator 要求非空；`refs.json` 打包这些 refs |
| `app/backend/app/main.py` | RDP manifest/API/materialize/bundle/attestation/archive/publish 前校验三类 refs 已在对应 registry/store 记录，并要求 coverage lifecycle refs 覆盖 compiler artifact + math chain |
| `app/backend/tests/test_research_os_rdp*.py` | 覆盖 missing refs、unknown upstream refs no-write、replay/detail/materialized refs |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 RDP upstream refs gate 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. RDP manifest 缺 `compiler_artifact_refs` / `mathematical_spine_chain_refs` / `goal_entrypoint_coverage_refs` 必须被 validator 拒绝。
2. RDP API 引用未登记的 compiler artifact 必须 422，且不写 RDP manifest JSONL。
3. RDP manifest replay/detail 必须保留三类 upstream refs。
4. materialized `refs.json` 必须包含 compiler artifact、Mathematical Spine chain 和 GOAL entrypoint coverage refs。
5. API downstream 操作必须在 materialize/bundle/archive/publish 前重新校验 upstream refs，避免绕过 record endpoint 的旧/手写 manifest。

## 红线 [按需]
- 不自动伪造 compiler artifact、Mathematical Spine chain 或 coverage record。
- 不声称 RDP 外部发布、CI、线上发版或用户验收已完成。
- 不声称所有 GOAL §0-§17 入口已闭合；这只是 RDP 交付包不能绕过已建上游 records。

## 非目标 [按需]
不实现外部 object-store publish、release gate 管理 UI、完整 compiler pass、策略代码生成、所有 producer 自动写 Mathematical Spine chain、所有入口 QRO/Graph/Compiler 强制接线。

## 验收一句话 [必填]
RDP manifest 现在必须引用已登记的 compiler artifact、Mathematical Spine chain 和 GOAL entrypoint coverage；缺 refs 或 unknown upstream ref 失败时不留下 RDP manifest partial record。

## 完成记录
- `RDPManifest` / `manifest_from_qro()` / payload parser / summary / materialized `refs.json` 均携带三类 upstream refs。
- `POST /api/research-os/rdp/manifests` 写入前先结构校验，再查 `COMPILER_IR_STORE`、`MATHEMATICAL_SPINE_CHAIN_REGISTRY`、`GOAL_ENTRYPOINT_COVERAGE_REGISTRY`，并要求 coverage lifecycle refs 覆盖 compiler artifact 和 chain refs。
- RDP materialize、bundle、deployment attestation、archive、source-run integrity 和 publish 入口复用 runtime upstream refs 校验。
- 验证：RDP scoped **56 passed / 2 warnings**；goal/compiler/trust/RDP adjacent **102 passed / 2 warnings**。
