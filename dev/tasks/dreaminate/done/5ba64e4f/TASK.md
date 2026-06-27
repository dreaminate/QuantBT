---
uuid: 5ba64e4f8fd84834964da8c8afefbdf2
title: RDP manifests require MarketDataUse PIT refs before formal package actions
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: rdp-market-data-pit-formal-report-gate
source: goal-gap
source_ref: GOAL §11/§14/§17 formal RDP package data timing/PIT gate
depends_on: [bc412bbd06814e499c628197a7e2df2f, 0afc84c7369e4964ac651d93718873f4, ed548b5cd527410fb2227acc1acd1c73]
completed_at: 2026-06-27
---

# RDP manifests require MarketDataUse PIT refs before formal package actions

## Scope [必填]
把 Research Delivery Package manifest 从“有 data_refs / dataset_version_refs 即可登记正式交付包”升级为必须声明 `market_data_use_validation_refs`。API 在 record/materialize/bundle/archive/publish 复用同一 runtime validation：每个 ref 必须存在、accepted、无 violation、use_context 为 backtest 或 confirmatory_validation；其 DatasetSemantics 必须有 `known_at_ref`、`effective_at_ref`、`pit_bitemporal_rules_ref`；manifest 中 `dataset:*` data_refs 必须被这些 validation refs 覆盖。

## 上下文 / 动机 [按需]
RDP 是 §17 正式交付包/报告面。原 manifest gate 要求 data_refs、DatasetVersion、复现命令、run、honest-N、known limits 等字段，但没有把正式包绑定到 accepted MarketDataUse/PIT refs。这样正式包可以引用 dataset/run，却没有强制 event/known/effective time 证据。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | `RDPManifest` 增加 `market_data_use_validation_refs`；validator 要求非空；open manifest/package refs index 输出该字段；package id hash 纳入该字段 |
| `app/backend/app/main.py` | `_rdp_manifest_from_payload` 接收 refs；summary 回显 refs；`_validate_rdp_manifest_registered_refs` 回查 MarketData registry、DatasetSemantics timing refs 和 data_refs 覆盖 |
| `app/backend/tests/conftest.py` | RDP API tests 自动注入 accepted/PIT MarketDataUse registry stub |
| `app/backend/tests/test_research_os_rdp*.py` | 所有 RDP fixtures 增加 refs；新增缺 refs、unknown refs、data_ref 不覆盖的拒绝测试 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | RDP detail UI 显示 `market_data_use_validation_refs` |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 断言前端能看到 RDP market-data-use refs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 纯 manifest 缺 `market_data_use_validation_refs` 时 `validate_rdp_manifest` 返回 `missing_market_data_use_validation_refs`。
2. RDP API record manifest 引用 unknown MarketDataUse ref 时 422，且不落 JSONL。
3. RDP API record manifest 的 `data_refs` 未被 MarketDataUse validation 的 dataset refs 覆盖时 422，且不落 JSONL。
4. RDP package materialize/bundle/archive/publish 仍复用 `_validate_rdp_manifest_for_runtime`，因此同一 gate 作用于后续正式包动作。
5. 前端 RDP export panel 不隐藏这组 refs。

## 红线 [按需]
- 不把 RDP MarketDataUse refs 说成 source/run/artifact 已逐行消费真实行情 rows。
- 不把 local RDP materialize/archive/publish 说成外部发布、CI release、对象存储发布或线上验收。
- 不把本地 pytest/npm 结果说成 CI。

## 非目标 [按需]
不实现外部 package publish、对象存储/CI release、完整 release gate 管理 UI、所有非 RDP 报告入口、真实 provider 实网连通或全资产自动同步。

## 验收一句话 [必填]
RDP 正式交付包现在必须携带 accepted/PIT MarketDataUse refs，且 refs 要覆盖 manifest 的 dataset data_refs，才允许登记和后续本地 package 动作。

## 完成记录（2026-06-27）
- `RDPManifest` / API / package refs index 增加 `market_data_use_validation_refs`。
- RDP runtime validator 回查 MarketData registry，拒绝 unknown、未 accepted、violation、use_context 不符、DatasetSemantics 缺 timing refs、data_refs 未覆盖。
- RDP panel detail 显示 MarketDataUse refs。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - RDP focused -> `pytest app/backend/tests/test_research_os_rdp.py app/backend/tests/test_research_os_rdp_persistence.py app/backend/tests/test_research_os_rdp_materializer.py app/backend/tests/test_research_os_rdp_source_bundle.py app/backend/tests/test_research_os_rdp_archive_export.py app/backend/tests/test_research_os_rdp_source_run_integrity.py app/backend/tests/test_research_os_rdp_deployment_attestation.py app/backend/tests/test_research_os_rdp_publish.py -q` -> 60 passed / 2 warnings。
  - RDP/market-data/goal/compiler adjacent -> 168 passed / 2 warnings。
  - `pytest app/backend/tests -q` -> 1812 passed / 13 skipped / 283 warnings。
  - `npm run test:run -- RDPExportPanel.test.tsx` -> 1 file / 7 tests passed。
  - `npm run test:run` -> 28 files / 308 tests passed。
  - `npm run build` -> `tsc && vite build` PASS。
