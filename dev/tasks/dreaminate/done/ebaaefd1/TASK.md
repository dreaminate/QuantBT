---
uuid: ebaaefd17771473d9c3fdc9a14474bc2
title: Settings InstrumentSpec and CapabilityMatrix generation from DatasetSemantics
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-instrument-capability
source: goal-gap
source_ref: GOAL §4 Settings/IngestionSkill lifecycle; GOAL §11 InstrumentSpec/MarketCapabilityMatrix
depends_on: [6886f4e46d234ad7bf95264a458aabcc]
completed_at: 2026-06-27
---

# Settings InstrumentSpec and CapabilityMatrix generation from DatasetSemantics

## Scope [必填]
把 Settings 已登记的 DatasetSemantics 继续生成 `InstrumentSpec` 与 `MarketCapabilityMatrix`，写入 `MARKET_DATA_REGISTRY` 并复用现有 QRO 写入路径。Settings UI 必须显示 latest instrument/capability，并能从 Data Connectors panel 触发登记。

## 上下文 / 动机 [按需]
`6886f4e4` 已把 ingestion update + PIT rule 闭合到 DatasetSemantics，但 §11 的下游 MarketDataUse gate 还依赖 InstrumentSpec 和 CapabilityMatrix。只靠手工调用 `/api/research-os/market_data/*` 会让 Settings 链路断在 DatasetSemantics，无法从数据接入面继续形成可引用的标的/能力 metadata。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 Settings instrument/capability payload helpers、`POST /api/research-os/settings/instrument_specs`、`POST /api/research-os/settings/capability_matrices`，summary 返回 market_data_instruments / market_data_capability_matrices |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 Settings ingestion run -> DatasetSemantics -> InstrumentSpec -> CapabilityMatrix，缺 DatasetSemantics / A股 live capability no-write |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 instrument/capability totals/latest refs，并提供 Instrument / Capability 按钮 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 summary 渲染、InstrumentSpec POST body、CapabilityMatrix POST body |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 没有 recorded DatasetSemantics 时，Settings InstrumentSpec endpoint 422，不写 instrument/QRO。
2. InstrumentSpec 必须绑定 Settings skill/source/dataset，默认从 PIT rule 带 calendar ref。
3. live capability 对 A股 / `cn_equity` 必须 422，且不写 capability matrix/QRO。
4. 默认 capability 只声明 research/backtest/paper，不冒充 live/testnet。
5. 成功路径必须写对应 QRO；响应仍声明 raw_data_stored=false、connector_called=false、venue_called=false。

## 红线 [按需]
- 不跑 connector，不调用 venue，不保存 raw rows，不接触明文 secret。
- 不把 CapabilityMatrix 说成真实 provider/venue 权限验证。
- 不把本地 QRO/registry 写入说成 CI、线上或用户验收。

## 非目标 [按需]
不自动创建 MarketDataUseValidation，不证明策略/回测实际消费这些数据行，不实现真实 connector adapter、全资产自动同步、live provider/venue permission checks 或生产 scheduler。

## 验收一句话 [必填]
Settings DatasetSemantics 必须能生成 refs-only InstrumentSpec 和 paper-safe CapabilityMatrix；缺 DatasetSemantics 或 A股 live capability 必须 fail-closed 且不写 partial。

## 完成记录
- 新增 `POST /api/research-os/settings/instrument_specs`，从 recorded IngestionSkill/DataSourceAsset/DatasetSemantics/PIT rule 生成 `InstrumentSpec`，写 `MARKET_DATA_REGISTRY.record_instrument()` 并复用 Instrument QRO 写入。
- 新增 `POST /api/research-os/settings/capability_matrices`，从 recorded DatasetSemantics + InstrumentSpec 生成默认 research/backtest/paper capability，live/testnet 默认 false；A股 live 仍由现有 validator fail-closed。
- Settings summary 返回 `market_data_instrument_total` / `market_data_instruments` 和 `market_data_capability_matrix_total` / `market_data_capability_matrices`。
- Settings 安全页 Data Connectors panel 显示 latest instrument/capability，并新增 Instrument / Capability 按钮。
- 验证：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings 链路到 refs-only InstrumentSpec + CapabilityMatrix + QRO 的闭合，不是 MarketDataUseValidation 自动生成，不是实际策略消费数据行证明，不是真实 connector adapter、全资产自动同步、生产 scheduler、CI、线上或用户验收。
