---
uuid: 6886f4e46d234ad7bf95264a458aabcc
title: Settings DatasetSemantics generation from ingestion update and PIT rule
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-dataset-semantics
source: goal-gap
source_ref: GOAL §4 Settings/IngestionSkill lifecycle; GOAL §11 DatasetSemantics/PIT confirmatory validation
depends_on: [22682f6a8e5844cbb13300d350f046b2]
completed_at: 2026-06-27
---

# Settings DatasetSemantics generation from ingestion update and PIT rule

## Scope [必填]
把 Settings ingestion run 产出的 DatasetVersion / IngestionSkillUpdate 与已记录 PIT/bitemporal rule 组合成 `DatasetSemanticsRecord`，写入 `MARKET_DATA_REGISTRY` 并复用 Dataset QRO 写入路径。Settings UI 必须能触发该登记并显示 latest dataset semantics。

## 上下文 / 动机 [按需]
`22682f6a` 已让 `pit_bitemporal_rules_ref` 有了规则本体，但 GOAL §11 的下游 MarketDataUse gate 仍依赖 `DatasetSemanticsRecord`。如果 Settings 链路不能从已有 DatasetVersion/update/rule 生成 DatasetSemantics，用户还得手动重复录入 refs，且 GOAL §4 的 Data Onboarding 链路不能闭合到 §11。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `POST /api/research-os/settings/dataset_semantics`，从 IngestionSkillUpdate + DatasetVersion + PIT rule 生成 DatasetSemanticsRecord，写 MarketData registry + Dataset QRO；Settings summary 返回 market_data_datasets |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 Settings ingestion run -> mapping -> PIT rule -> DatasetSemantics/QRO，缺 rule/坏 update no partial |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 latest DatasetSemantics，并在 update+PIT rule 存在时可登记 semantics |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 DatasetSemantics summary 渲染和 POST body |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 没有 recorded PIT rule 时，Settings DatasetSemantics endpoint 422，不写 MarketData registry/QRO。
2. update_ref 不存在或不匹配 IngestionSkill/source 时 422。
3. DatasetVersion 不存在、dataset_id 不匹配或 checksum mismatch 时 422。
4. 记录成功后 `DatasetSemanticsRecord` 必须包含 known_at_ref、effective_at_ref、pit_bitemporal_rules_ref、lineage_refs、checksum。
5. 成功路径必须写 Dataset QRO；响应仍声明 raw_data_stored=false、connector_called=false。

## 红线 [按需]
- 不重新跑 connector，不保存 raw rows，不接触明文 secret。
- 不把 DatasetSemantics 登记说成 MarketDataUse validation 已通过。
- 不把本地 QRO/registry 写入说成 CI、线上或用户验收。

## 非目标 [按需]
不自动创建 InstrumentSpec、MarketCapabilityMatrix、MarketDataUseValidation，不证明策略/回测实际消费这些数据行，不实现真实 connector adapter、全资产自动同步或生产 scheduler。

## 验收一句话 [必填]
Settings ingestion update + PIT rule 必须能生成 refs-only DatasetSemantics 并写 Dataset QRO；缺 rule 或坏 update 必须 fail-closed 且不写 partial。

## 完成记录
- 新增 `POST /api/research-os/settings/dataset_semantics`，读取 recorded IngestionSkill、DataSourceAsset、IngestionSkillUpdate、DatasetVersion、PIT/bitemporal rule，组装 `DatasetSemanticsRecord` 并写 `MARKET_DATA_REGISTRY.record_dataset(..., use_context=confirmatory_validation)`。
- endpoint 复用 `_record_market_data_dataset_qro()`，成功路径写 Dataset QRO/ResearchGraph command；响应明确 `raw_data_stored=false`、`connector_called=false`。
- Settings summary 返回 `market_data_dataset_total` 和 `market_data_datasets`。
- Settings 安全页 Data Connectors panel 显示 latest dataset semantics，并在 latest update + PIT rule 存在时可调用 DatasetSemantics 登记。
- 验证：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings 链路到 refs-only DatasetSemantics + Dataset QRO 的闭合，不是 InstrumentSpec/Capability/MarketDataUseValidation 自动生成，不是实际策略消费数据行证明，不是真实 connector adapter、全资产自动同步、生产 scheduler、CI、线上或用户验收。
