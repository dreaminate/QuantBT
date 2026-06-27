---
uuid: e29078914b9a448ba631837c548a4a16
title: Market data use gate registry and QRO write-through
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-market-data
source: goal-gap
source_ref: GOAL §11 market data use and §12 execution capability boundary
depends_on: [24baede133594736a514b47a23638047]
completed_at: 2026-06-27
---

# Market data use gate registry and QRO write-through

## Scope [必填]
新增 refs-only MarketDataUse gate/API：使用方必须引用已登记 DatasetSemanticsRecord、InstrumentSpec 和 MarketCapabilityMatrixRecord，gate 通过后写 append-only use validation record 和 Research Graph QRO；坏输入不写 partial。不接真实 strategy builder、connector 或 execution order emission。

## 上下文 / 动机 [按需]
`24baede1` 已把 §11 market data 对象落成 registry/API/QRO，但下游仍可以把裸 refs 拼成 MarketDataUseRequest。GOAL §11/§12 要求 dataset/instrument/capability 在 research/backtest/paper/testnet/live 可达环境内保持同一资产引用和能力边界。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/market_data_contract.py` | 增加 MarketDataUseValidationRecord、parser、registry event、capital/transform dict helpers |
| `app/backend/app/research_os/__init__.py` | 导出 use validation record/parser |
| `app/backend/app/main.py` | 增加 `POST /api/research-os/market_data/use_requests`，引用 registry objects 后 validate + QRO |
| `app/backend/tests/test_market_data_contract.py` | 覆盖 accepted use gate、unrecorded refs、cross-currency/option/live bad input no-write、QRO refs |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. use request 引用未登记 dataset/instrument/capability -> 422，不写 use validation，不写 QRO。
2. cross-currency use 缺 base_currency/fx_conversion_ref -> 422，不写。
3. live use 引用 live=false matrix -> 422，不写。
4. accepted paper use -> 写 use validation registry，写 Research Graph QRO，summary 可查。
5. raw rows/payload/secret 出现在 use request -> 422，不写。

## 红线 [按需]
- 不拉真实行情，不新增 connector，不触网。
- 不把 use gate 通过说成数据已下载、策略已绑定或可 live。
- 不保存 raw rows、raw payload、quantity、price、secret、token 或 provider credential。

## 非目标 [按需]
不实现 strategy builder 接线、execution order intent 强制引用 market-data use validation、真实 provider permission test 或全资产自动同步。

## 验收一句话 [必填]
MarketDataUseRequest 只能引用已登记 §11 market data 资产；坏 refs/坏 capability/坏跨币种资本账 fail-closed 且不写 partial。

## 完成记录
- 新增 `MarketDataUseValidationRecord`、parser、validator 和 `PersistentMarketDataRegistry.record_use_validation` event；use validation 只保存 refs、accepted 状态、violation codes、evidence refs、actor/time，不保存 raw rows、provider payload 或 credential。
- 新增 capital/transform dict helpers：`CrossCurrencyCapitalRecord.to_dict`、`DataTransformationClaim.to_dict`、`cross_currency_capital_record_from_dict`、`data_transformation_claim_from_dict`。
- 主 app 新增 `POST /api/research-os/market_data/use_requests`：只接受 dataset/instrument/capability refs，先从 `MARKET_DATA_REGISTRY` 解析已登记对象，再调用 `validate_market_data_use`。通过后写 use validation registry 和 Research Graph QRO；响应标明 `raw_data_stored=false`、`connector_called=false`、`strategy_builder_called=false`、`venue_called=false`。
- `GET /api/research-os/market_data/summary` 增加 `use_validations` 和 `use_validation_total`。
- 对抗门：未登记 dataset/instrument/capability refs、cross-currency 缺 capital record、live use 引用 live=false matrix、raw rows/payload/secret 均 422，且 use validation registry 和 Graph command 不增加。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_market_data_contract.py` -> 17 passed / 2 warnings；expanded Research OS/entrypoint/execution/model/RDP/compiler scoped -> 239 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 refs-only MarketDataUse gate，不是 strategy builder 接线、execution order intent 强制引用、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或全资产自动同步。
