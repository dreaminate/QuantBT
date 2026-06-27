---
uuid: 44a1c3810ad849cfb082fa9fb0ddd6f1
title: RDP package archive export——开放交付包下载面
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: dev/GOAL.md §17 + dev/state/dreaminate/state.md Research Delivery Package gap
depends_on: [d5f0ff4114314ca0a1afb1d1ee243bdb]
---

# RDP package archive export

## Scope [必填]
为已通过 RDP manifest gate、已 materialize、且按需完成 source-file bundle 的本地 open package 增加确定性 zip 归档导出和后端下载 API；不做 live publish、外部部署、前端 UI 或 source-to-run integrity attestation。

## 上下文 / 动机 [按需]
`dev/state/dreaminate/state.md` 已确认 RDP manifest registry/API、open materializer、source-file content bundle/API、deployment attestation/API 存在，但 RDP 仍缺导出/发布/完整性链。当前 active board 4 张卡 `review_status:0`，不得直接实现，因此新建本卡推进 GOAL §17 的 package export 面。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/research_os/rdp.py` | RDP package records/helpers | 新增 deterministic archive exporter，拒绝 unsafe package、未物化包、tampered manifest、source bundle 缺失、symlink/path escape |
| `app/backend/app/main.py` | RDP endpoints | 新增 `GET /api/research-os/rdp/manifests/{package_id}/archive`，返回 `application/zip` |
| `app/backend/app/research_os/__init__.py` | package exports | 导出 archive record/exporter |
| `app/backend/tests/test_research_os_rdp_archive_export.py` | 新测试 | 覆盖 exporter 和 API 坏门 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 未 materialize 的 manifest 请求 archive → 422/ValueError，不能生成空 zip。
2. 声明了 `source_file_refs` 但没 `source_files_index.json` → 拒绝，不能把只有 refs 的包说成含源码交付。
3. 篡改 `manifest.json` 或 package 内 symlink 指向外部文件 → 拒绝，不能把本地任意文件卷入交付包。
4. 同一个 package 重复 export → zip 字节和 sha256 稳定，且不包含 `_archives` 缓存目录。

## 非目标 [按需]
不实现前端按钮、不发布到公网/对象存储、不做部署动作、不声明 CI/线上已生效，不替代后续 source-to-run integrity attestation。

## 验收一句话 [必填]
RDP 本地 open package 能被 API 下载为确定性 zip；未物化、源码 bundle 缺失、manifest 篡改、symlink 逃逸都被测试抓住；不破 RDP 分组和后端全量。

## 完成记录（2026-06-26）
- 新增 `RDPPackageArchiveRecord` / `RDPPackageArchiveExporter`，导出 deterministic zip，固定 zip timestamp/权限，重复导出 sha256 和字节稳定；archive cache 写 `DATA_ROOT/rdp_packages/_archives/`，不卷回 package。
- 新增 `GET /api/research-os/rdp/manifests/{package_id}/archive`，返回 `application/zip`，带 archive sha256/file count/user headers；unknown package 404，package guard 失败 422。
- 对抗测试覆盖：未物化包、reserved package id、声明 source refs 但缺 source bundle、tampered manifest、symlink escape、API zip 下载、unknown package 404、重复导出不含 `_archives`。
- 验证：`tests/test_research_os_rdp_archive_export.py -q` → 8 passed / 2 warnings；RDP package group → 39 passed / 2 warnings；Research OS scoped group → 169 passed / 2 warnings；后端全量 → 1485 passed / 13 skipped / 278 warnings。
- 边界：未实现前端导出 UI、live publish、外部部署、source-to-run integrity attestation。
