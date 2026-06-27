---
uuid: e65a6e9664d94103bcab30cf9ebd0996
title: Settings MarketDataUseValidation generation from onboarding refs
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-market-data-use
source: goal-gap
source_ref: GOAL §4 Settings/IngestionSkill lifecycle; GOAL §11 MarketDataUse validation
depends_on: [ebaaefd17771473d9c3fdc9a14474bc2]
completed_at: 2026-06-27
---

# Settings MarketDataUseValidation generation from onboarding refs

## Scope [必填]
把 Settings 已登记的 DatasetSemantics、InstrumentSpec 和 CapabilityMatrix 组合成 accepted `MarketDataUseValidationRecord`，写入 `MARKET_DATA_REGISTRY` 并复用现有 MarketDataUse QRO 写入路径。Settings UI 必须显示 latest validation ref，并能从 Data Connectors panel 触发登记。

## 上下文 / 动机 [按需]
`ebaaefd1` 已让 Settings 链路生成 DatasetSemantics、InstrumentSpec 和 CapabilityMatrix，但 IDE/Agent/portfolio/execution 下游强制引用的是 accepted `MarketDataUseValidationRecord`。如果 Settings 不产出 validation ref，用户还要手工拼 `/api/research-os/market_data/use_requests` payload，接入链路仍没有从 Settings 到下游 gate 的完整 refs。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 Settings market data use payload helper、`POST /api/research-os/settings/market_data_use_validations`，summary 返回 market_data_use_validations |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 Settings DatasetSemantics -> InstrumentSpec -> CapabilityMatrix -> MarketDataUseValidation，缺 capability no-write |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 latest use validation，并提供 MarketDataUse 按钮 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 use validation summary 渲染和 POST body |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 CapabilityMatrix 时，Settings MarketDataUseValidation endpoint 422，不写 validation/QRO。
2. endpoint 必须复用 `validate_market_data_use`，不绕过 DatasetSemantics / InstrumentSpec / CapabilityMatrix validator。
3. 成功路径只写 refs-only accepted validation，不保存 rows、不跑 connector、不调用 strategy builder、不触 venue。
4. summary/UI 必须显示 validation ref，方便下游 IDE/Agent/portfolio/execution 引用。

## 红线 [按需]
- 不跑 connector，不调用 strategy builder，不调用 venue，不保存 raw rows，不接触明文 secret。
- 不把 accepted MarketDataUseValidation 说成策略实际消费数据行证明。
- 不把本地 QRO/registry 写入说成 CI、线上或用户验收。

## 非目标 [按需]
不自动把 validation ref 注入所有下游策略/执行入口，不实现真实 connector adapter、全资产自动同步、live provider/venue permission checks 或生产 scheduler。

## 验收一句话 [必填]
Settings 已有 DatasetSemantics + InstrumentSpec + CapabilityMatrix 时必须能生成 accepted MarketDataUseValidation；缺 capability 必须 fail-closed 且不写 partial。

## 完成记录
- 新增 `POST /api/research-os/settings/market_data_use_validations`，从 Settings skill 解析 recorded DatasetSemantics、InstrumentSpec、CapabilityMatrix，构造 `MarketDataUseRequest` 并复用 `validate_market_data_use()`。
- 成功路径写 `MarketDataUseValidationRecord` 和 MarketDataUse QRO；响应明确 `raw_data_stored=false`、`connector_called=false`、`strategy_builder_called=false`、`venue_called=false`。
- Settings summary 返回 `market_data_use_validation_total` 和 `market_data_use_validations`。
- Settings 安全页 Data Connectors panel 显示 latest use validation，并新增 MarketDataUse 按钮。
- 验证：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings 链路到 refs-only accepted MarketDataUseValidation + QRO 的闭合，不是下游自动注入，不是实际策略消费数据行证明，不是真实 connector adapter、全资产自动同步、生产 scheduler、CI、线上或用户验收。
