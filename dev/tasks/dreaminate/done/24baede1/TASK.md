---
uuid: 24baede133594736a514b47a23638047
title: Market data asset registry and QRO write-through
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-market-data
source: goal-gap
source_ref: GOAL §11 data layer and instrument onboarding
depends_on: []
completed_at: 2026-06-27
---

# Market data asset registry and QRO write-through

## Scope [必填]
新增 §11 refs-only market data registry/API：DatasetSemanticsRecord、InstrumentSpec、MarketCapabilityMatrixRecord 写入 append-only store，并在成功写入时生成对应 Research Graph QRO。坏输入不写 partial；不实现真实 connector、全域数据同步或外部数据拉取。

## 上下文 / 动机 [按需]
`market_data_contract.py` 已有 PIT、跨币种、期权语义、MarketCapabilityMatrix validator，但这些对象还没有统一持久化/API/QRO 写入面。GOAL §11 要求数据、标的和能力矩阵作为正式资产进入 Research Graph，并且 live/confirmatory 等场景不能绕过语义门。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/market_data_contract.py` | 增加 from_dict、to_dict、append-only registry 和 replay guards |
| `app/backend/app/research_os/__init__.py` | 导出 market data registry/record parser |
| `app/backend/app/main.py` | 增加 `MARKET_DATA_REGISTRY`、market data API、Dataset/MarketCapabilityMatrix QRO 写入 |
| `app/backend/tests/test_market_data_contract.py` | 覆盖 registry/API success、invalid no-write、malformed history fail-closed、QRO refs |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. confirmatory dataset 缺 known_at/effective_at/PIT -> API 422，不写 JSONL，不写 QRO。
2. option InstrumentSpec 缺 expiry/strike/multiplier/settlement -> API 422，不写。
3. live MarketCapabilityMatrix 缺 live permission -> API 422，不写。
4. append-only history malformed -> registry 初始化 fail-closed。
5. valid records -> 写 registry summary，写 Research Graph QRO，返回 QRO/command refs。

## 红线 [按需]
- 不拉真实行情，不新增 connector，不触网。
- 不把 dataset metadata 说成数据已下载或可用于 live。
- 不保存 raw dataset payload、secret、token 或 provider credential。
- 不把本地 registry/QRO 等同于全域数据接入完成。

## 非目标 [按需]
不实现 Settings UI、真实 data connector、dense catalog sync、全资产自动扫描、外部市场数据权限校验或 live broker connector。

## 验收一句话 [必填]
§11 market data 对象可作为受治理资产写入 registry 和 Research Graph；PIT/期权/live capability 坏输入 fail-closed 且不写 partial。

## 完成记录
- 新增 `PersistentMarketDataRegistry`：append-only JSONL 持久化 `DatasetSemanticsRecord`、`InstrumentSpec`、`MarketCapabilityMatrixRecord`，启动 replay 遇 malformed history fail-closed；记录只保存 refs/metadata，不保存 raw market data rows、provider payload 或凭据。
- 新增 record parser 和 `to_dict`：`dataset_semantics_record_from_dict`、`instrument_spec_from_dict`、`market_capability_matrix_record_from_dict`；registry 写入前复用 PIT/期权/live capability validators。
- 主 app 新增 `MARKET_DATA_REGISTRY` 与 API：`POST /api/research-os/market_data/datasets`、`POST /api/research-os/market_data/instruments`、`POST /api/research-os/market_data/capability_matrices`、`GET /api/research-os/market_data/summary`。
- 成功路径写 Research Graph QRO：DatasetSemantics -> `QROType.DATASET`，InstrumentSpec -> `QROType.DATA_SOURCE_ASSET`（当前 QRO type 表无专门 InstrumentSpec，QRO known_limits 已声明），MarketCapabilityMatrix -> `QROType.MARKET_CAPABILITY_MATRIX`。QRO output contract 标明 `raw_data_stored=false`、`connector_called=false`，capability 额外标明 `venue_called=false`。
- 对抗门：confirmatory dataset 缺 known_at/effective_at/PIT、option InstrumentSpec 缺 expiry/strike/multiplier/settlement、live capability matrix 缺 permission、raw rows/payload、plaintext secret 均 422 且 registry/Graph 不写。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_market_data_contract.py` -> 12 passed / 2 warnings；market data/onboarding/Graph/entrypoint adjacent scoped -> 63 passed / 2 warnings；expanded Research OS/entrypoint/execution/model/RDP/compiler scoped -> 234 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS；`python dev/scripts/validate_dev.py` PASS（DAG 176）。
- 边界：这是 §11 refs-only metadata registry/API/QRO，不是真实 data connector、行情下载、全资产自动同步、strategy builder 接线、execution path 接线、live provider permission proof 或真实 venue permission check。
