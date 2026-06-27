---
uuid: b1fdff40b8af4ef586e3d3ded73f7c3f
title: RDP source-file content bundle——开放交付包安全复制源码内容
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: GOAL §17 / TRACE §17 · RDP source-file content bundle residual after c2d78309
depends_on: [c2d78309b3dd458b9dfb499abe4a51e9]
---

# RDP source-file content bundle

## Scope [必填]
RDP 现有 `RDPOpenPackageMaterializer` 只写 deterministic `manifest.json` + `refs.json`，刻意不复制 source payload。GOAL §17 仍要求 Research Delivery Package 能导出开放格式源码内容。本卡补第一版 **source-file content bundle**：只复制 `manifest.source_file_refs` 明确声明的源码文件到包目录 `source_files/`，并写 `source_files_index.json`，记录原始 repo-relative path、bundle-relative path、sha256、byte size 和 encoding。

安全边界：不允许任意绝对路径、`..` 逃逸、未声明 ref、缺 mapping、超限文件、非 UTF-8 文本、明文 secret/API key/password/token 内容进入交付包。bundle 不把源码内容塞进 `manifest` 或 `refs.json`。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/research_os/rdp.py | RDP materializer 后 | 新增 `RDPSourceFileBundler`、bundle entry/record、安全路径/secret/大小/text 检查 |
| app/backend/app/main.py | RDP API 区 | 新增 `RDP_SOURCE_FILE_BUNDLER` 和 `/api/research-os/rdp/manifests/{package_id}/bundle_sources` |
| app/backend/app/research_os/__init__.py | exports | 导出新 bundle 类型 |
| app/backend/tests/test_research_os_rdp_source_bundle.py | 新测试 | 对抗测试 source bundle 安全边界和 API |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 声明 ref + repo-relative path → 复制内容到 `source_files/`，`source_files_index.json` 只含相对路径/hash/size，不含 `source_file_payload`。
2. `source_map` 包含 manifest 未声明 ref → 拒。
3. 缺 declared ref mapping → 拒。
4. `../secret.env` 或绝对路径 → 拒，包根外文件不被复制。
5. 源文件包含 `api_key` / `sk-...` / password/token 明文 → 拒。
6. 超过 `max_bytes` 或非 UTF-8 → 拒。
7. API 调用会先物化 manifest，再 bundle source files；未知 package 404。

## 验收一句话 [必填]
RDP 包能安全复制已声明源码内容并生成可审计 index；路径逃逸、未声明 ref、明文 secret、超限/非文本文件全部 fail-closed；不破 RDP 既有 materialize 不复制 payload 契约。
