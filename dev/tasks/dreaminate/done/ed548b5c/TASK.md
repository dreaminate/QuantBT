---
uuid: ed548b5cd527410fb2227acc1acd1c73
title: Market data contract QRO producers compile into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-market-data-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§4/§8/§11/§14 Dataset/Instrument/Capability QRO -> Graph -> Compiler -> Coverage
depends_on: [11c209b2f4d34b0aba1fb5dbe830e74b, 24baede133594736a514b47a23638047, e29078914b9a448ba631837c548a4a16, 6886f4e46d234ad7bf95264a458aabcc, ebaaefd17771473d9c3fdc9a14474bc2, e65a6e9664d94103bcab30cf9ebd0996, 5d93d82e6e844f7db3403931c62054d8, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Market data contract QRO producers compile into entrypoint coverage

## Scope [必填]
把已有 DatasetSemantics、InstrumentSpec、MarketCapabilityMatrix QRO producer 接到 governed compiler IR/pass 和 GOAL entrypoint coverage；覆盖 direct `/api/research-os/market_data/*` 入口和 Settings 自动登记入口。不实现真实 provider 实网连通、全资产自动同步、下游 strategy auto-injection、venue permission proof 或完整 compiler pass。

## 上下文 / 动机 [按需]
`24baede1` 已让 market-data dataset/instrument/capability registry/API 写 QRO/Research Graph；`6886f4e4` / `ebaaefd1` 已让 Settings 自动生成 DatasetSemantics、InstrumentSpec 和 CapabilityMatrix；`5d93d82e` 已覆盖 MarketDataUseValidation 和 one-shot onboarding 最终 QRO。剩余缺口是前置 Dataset/Instrument/Capability 入口仍停在 QRO/Graph，缺 entrypoint-level compiler coverage。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_compile_market_data_contract_qro`；dataset/instrument/capability 三类 QRO producer 成功写 Graph 后自动生成 compiler IR/pass/entrypoint coverage refs；Settings 调用传入 settings-specific entrypoint |
| `app/backend/tests/test_market_data_contract.py` | direct market-data API 隔离 compiler/coverage stores；断言 dataset/instrument/capability response refs、store 回查和 direct entrypoint_ref |
| `app/backend/tests/test_onboarding_gateway.py` | Settings dataset_semantics/instrument_specs/capability_matrices 成功路径断言 settings entrypoint_ref，不与 direct API 混淆 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Direct dataset/instrument/capability API 成功响应必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
2. Direct coverage entrypoint 必须分别是 `api:research_os.market_data.datasets`、`api:research_os.market_data.instruments`、`api:research_os.market_data.capability_matrices`。
3. Settings coverage entrypoint 必须分别是 `api:research_os.settings.dataset_semantics`、`api:research_os.settings.instrument_specs`、`api:research_os.settings.capability_matrices`，不能误写 direct API 名。
4. Compiler IR/pass 必须绑定同一 QRO 和同一 Research Graph command，且不记录 raw rows、raw payload 或 secret material。

## 红线 [按需]
- 不把 DatasetSemantics/InstrumentSpec/CapabilityMatrix coverage 说成 provider 已拉数、数据行已被策略消费、venue permission 已验证或 live 能交易。
- 不把 Settings 自动登记说成完整 connector catalog、OAuth/device-code/account auth 或全资产同步。
- 不把 symbol/sample row/secret/raw payload 写进 compiler/coverage。

## 非目标 [按需]
不做真实 connector/provider adapter 覆盖、生产 keystore 后端、下游自动注入、live provider/venue permission check、CI、线上或用户验收。

## 验收一句话 [必填]
Market-data DatasetSemantics、InstrumentSpec 和 MarketCapabilityMatrix 的 direct API 与 Settings 自动登记成功路径现在都会自动生成 governed compiler IR/pass 与 GOAL entrypoint coverage，且 direct/settings entrypoint 不混淆。

## 完成记录（2026-06-27）
- 新增 `_compile_market_data_contract_qro`，复用 `_compile_entrypoint_qro` 写 compiler IR/pass 与 entrypoint coverage。
- Direct market-data dataset/instrument/capability API 用默认 direct entrypoint；Settings dataset_semantics/instrument_specs/capability_matrices 显式传 settings entrypoint。
- 本地验证：
  - `pytest app/backend/tests/test_market_data_contract.py app/backend/tests/test_onboarding_gateway.py -q` -> 62 passed / 2 warnings。
  - `pytest app/backend/tests/test_market_data_contract.py app/backend/tests/test_onboarding_gateway.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_execution_boundary_contract.py -q` -> 173 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
