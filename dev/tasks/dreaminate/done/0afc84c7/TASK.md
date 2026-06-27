---
uuid: 0afc84c7369e4964ac651d93718873f4
title: Research Delivery Package persistent store and backend API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: dev/GOAL.md §17 + dev/research/TRACE.md §17 + dev/state/dreaminate/state.md RDP row
depends_on: [bc412bbd06814e499c628197a7e2df2f, 5bb5d9da2f75469580ebbc74edf456fd]
---

# Research Delivery Package persistent store and backend API

## Scope [必填]
Turn the GOAL §17 RDP manifest gate into a durable package registry. The store
must persist accepted `RDPManifest` records through JSONL replay, reject invalid
manifests with the existing validator, fail closed on malformed history, and
expose backend APIs to create/list/read package manifests.

This is not a frontend exporter, source-file bundle writer, zip/package
materializer, or production deployment attestation. It creates the durable
manifest registry those later paths must use.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | Add JSONL-backed persistent RDP package store |
| `app/backend/app/main.py` | Add app-level RDP store and `/api/research-os/rdp/*` endpoints |
| `app/backend/tests/test_research_os_rdp_persistence.py` | Prove persistence, validator rejection, malformed history, and HTTP API |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Valid RDP manifest persists across store restart and keeps canonical package id.
2. Missing DatasetVersion / reproducibility command returns 422 and does not write JSONL.
3. Live RDP without deployment/monitor/rollback/retire refs is rejected.
4. Malformed persisted history fails closed at startup.
5. API summary returns manifest refs without source-file payload materialization.

## 验收一句话 [必填]
RDP has a durable manifest registry and backend read/write API; frontend export,
source-file bundling, and full package materialization remain explicitly
separate.

## 完成记录
- Runtime: `PersistentRDPStore` now appends/replays accepted `RDPManifest` records through JSONL, validates writes through `validate_rdp_manifest`, and fails closed on malformed persisted rows.
- API: `app/backend/app/main.py` now owns `RDP_STORE` at `DATA_ROOT/audit/rdp_manifests.jsonl` and exposes `POST /api/research-os/rdp/manifests`, `GET /api/research-os/rdp/manifests`, and `GET /api/research-os/rdp/manifests/{package_id}`.
- Tests: added `app/backend/tests/test_research_os_rdp_persistence.py` for restart replay, invalid manifest no-write, live runtime refs, malformed history, API list/read, and no source-file payload materialization.
- Validation: `python -m pytest tests/test_research_os_rdp.py tests/test_research_os_rdp_persistence.py -q` -> `11 passed, 2 warnings`.
- Validation: Research OS scoped group -> `57 passed, 2 warnings`.
- Validation: full backend `python -m pytest -q` -> `1449 passed, 13 skipped, 278 warnings`.
- Boundary: this does not implement frontend export, source-file bundle writing, zip/package materialization, deployment attestation, or live package publishing.
