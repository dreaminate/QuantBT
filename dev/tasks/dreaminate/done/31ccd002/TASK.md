---
uuid: 31ccd0028ff4446b9508e9b30f0ea7d9
title: RDP source-to-run integrity attestation——交付包源码绑定运行产物
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: dev/GOAL.md §17 + dev/state/dreaminate/state.md Research Delivery Package gap
depends_on: [44a1c3810ad849cfb082fa9fb0ddd6f1]
---

# RDP source-to-run integrity attestation

## Scope [必填]
为 RDP open package 增加 source-to-run integrity attestation：把 package 中声明并打包的源码文件、`RUN_ROOT/<run_id>/strategy.py`、`run.json`、`portfolio.csv` 和 manifest `artifact_hash` 绑定成 append-only 审计记录；不做 live publish、前端 UI、重新运行回测或外部部署。

## 上下文 / 动机 [按需]
`dev/state/dreaminate/state.md` 已确认 RDP manifest registry/API、open materializer、source-file content bundle/API、deployment attestation/API、archive export/API 存在，但仍明确缺 source-to-run integrity attestation。GOAL §17 要求正式晋级资产能追溯 RDP，且交付包含代码/环境/hash/seed、artifact hash、回测/验证运行。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/research_os/rdp.py` | RDP attestation helpers/stores | 新增 source-run integrity record/store，校验 package、source bundle、run artifacts 和 manifest artifact hash |
| `app/backend/app/main.py` | RDP endpoints | 新增 `POST /api/research-os/rdp/manifests/{package_id}/source_run_integrity_attestations` |
| `app/backend/app/research_os/__init__.py` | package exports | 导出 source-run integrity record/store |
| `app/backend/tests/test_research_os_rdp_source_run_integrity.py` | 新测试 | 覆盖 store/API 和坏门 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. package 未 materialize / 缺 source bundle → 拒，不得只凭 manifest refs 通过。
2. `run_id` 未在 `manifest.run_refs` 声明，或 `run.json.run_id` 不匹配 → 拒。
3. `manifest.artifact_hash` 与 `run.json + strategy.py + portfolio.csv` 内容哈希不一致 → 拒。
4. `RUN_ROOT/<run_id>/strategy.py` 与 source bundle 中指定 `source_file_ref` 内容哈希不一致 → 拒。
5. API 只收 `run_id`，不得用任意本地路径逃逸 `RUN_ROOT`。

## 非目标 [按需]
不实现前端按钮、不发布到公网/对象存储、不触发重新运行、不声明 CI/线上已生效，不替代 deployment attestation。

## 验收一句话 [必填]
RDP 能把 package source bundle 和真实 run artifacts 做 append-only 一致性证明；未声明 run、artifact hash mismatch、source mismatch、缺 source bundle、路径逃逸都被测试抓住；不破 RDP 分组和后端全量。

## 完成记录（2026-06-26）
- 新增 `RDPSourceRunIntegrityRecord` / `PersistentRDPSourceRunIntegrityStore`，以 append-only JSONL 记录 package source bundle 到 run artifact 的一致性证明。
- 新增 `rdp_run_artifact_hash`，把 `run.json`、`strategy.py`、`portfolio.csv` 三个文件 sha256 canonical 化为 manifest `artifact_hash`；attestation 要求 manifest artifact hash 与真实 run artifacts 一致。
- 新增 `POST /api/research-os/rdp/manifests/{package_id}/source_run_integrity_attestations`，API 只收 `run_id` 和可选 `source_file_ref`，从服务端 `RUN_ROOT` 定位 run，不接受任意本地路径。
- 对抗测试覆盖：缺 source bundle、run_id 未声明、run.json run_id mismatch、artifact_hash mismatch、source bundle 与 run strategy mismatch、run_id path escape、API success、unknown package 404。
- 验证：`tests/test_research_os_rdp_source_run_integrity.py -q` → 8 passed / 2 warnings；RDP package group → 47 passed / 2 warnings；Research OS scoped group → 177 passed / 2 warnings；后端全量 → 1493 passed / 13 skipped / 278 warnings。
- 边界：未实现前端导出 UI、live publish、外部部署、重新运行回测或 deployment attestation 替代。
