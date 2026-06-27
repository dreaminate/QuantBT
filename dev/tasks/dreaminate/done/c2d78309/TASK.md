---
uuid: c2d78309b3dd458b9dfb499abe4a51e9
title: Research Delivery Package open materializer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: dev/GOAL.md §17 + dev/state/dreaminate/state.md RDP row
depends_on: [0afc84c7369e4964ac651d93718873f4]
---

# Research Delivery Package open materializer

## Scope [必填]
Add the first open-format RDP materializer behind the persistent RDP manifest
registry. Given an accepted manifest, it must write a deterministic package
directory with `manifest.json` and a refs index, preserve only source file refs
instead of copying payloads, reject unsafe package ids, and be idempotent for
the same manifest hash.

This is not frontend export, source-file bundling, deployment attestation, or
live package publishing. It creates the durable open package surface those
later features must extend.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | Add open package materializer and package record |
| `app/backend/app/main.py` | Add app-level materializer and materialize endpoint |
| `app/backend/tests/test_research_os_rdp_materializer.py` | Prove deterministic package files, no payload copy, unsafe id rejection, and API |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Valid accepted manifest materializes `manifest.json` and refs index.
2. Re-running materialization for the same manifest is idempotent.
3. Unsafe package id with path traversal is rejected.
4. Package index keeps `source_file_refs` only and does not create source payload files.
5. API 404s for unknown package id.

## 验收一句话 [必填]
RDP can materialize an accepted manifest into deterministic open package files;
source-file bundling, frontend export, deployment attestation, and live publish
remain explicitly separate.

## 完成记录
- Runtime: added `RDPOpenPackageMaterializer` and `RDPPackageRecord` in `app/backend/app/research_os/rdp.py`. It writes deterministic `manifest.json` and `refs.json` package files, rejects unsafe package ids, and is idempotent for the same manifest hash.
- API: `app/backend/app/main.py` now owns `RDP_PACKAGE_MATERIALIZER` at `DATA_ROOT/rdp_packages` and exposes `POST /api/research-os/rdp/manifests/{package_id}/materialize`.
- Tests: added `app/backend/tests/test_research_os_rdp_materializer.py` for manifest/refs file output, no source payload copy, idempotency, unsafe package id rejection, API materialization, and unknown package 404.
- Validation: `python -m pytest tests/test_research_os_rdp.py tests/test_research_os_rdp_persistence.py tests/test_research_os_rdp_materializer.py -q` -> `16 passed, 2 warnings`.
- Validation: Research OS scoped group -> `70 passed, 2 warnings`.
- Validation: full backend `python -m pytest -q` -> `1462 passed, 13 skipped, 278 warnings`.
- Boundary: this does not implement frontend export, source-file content bundling, deployment attestation, or live package publishing.
