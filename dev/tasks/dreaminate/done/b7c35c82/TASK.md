---
uuid: b7c35c8294df484e847b71e33f2ee181
title: IDE AI complete requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: GOAL §11 market data use gate -> IDE AI strategy codegen entrypoint
depends_on: [84b1d0c60c2648bbb7a1436f1d151f93, 4b6f55dccf2748b692ebe43493979eff]
completed_at: 2026-06-27
---

# IDE AI complete requires MarketDataUse validation

## Scope [必填]
让 `POST /api/ide/ai_complete` 在调用 LLM 生成/解释/修复策略代码前强制要求 accepted/no-violation `market_data_use_validation_refs`。缺 refs、unknown ref、未 accepted ref 或 violation ref 都必须 422，且不调用 LLM、不写 LLMCallRecord QRO、不写 Research Graph command。

## 上下文 / 动机 [按需]
IDE save/run 与 Agent `backtest.run` strategy synthesis 已接 MarketDataUse gate，但 IDE AI complete 仍能在保存和运行之前调用 LLM 生成策略代码。这个路径不持久化策略，也不跑 sandbox，但它是 strategy codegen 入口；必须在 LLM 调用前绑定 accepted MarketDataUse validation，避免 codegen 层绕过 §11 数据使用门。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `ide_ai_complete` 在 LLM 调用前复用 IDE MarketDataUse refs validator；LLMCallRecord QRO input/output/lineage/hash 记录 refs |
| `app/backend/tests/test_strategy_console_s2.py` | 覆盖成功 QRO refs，以及缺 refs、violation refs no-LLM/no-QRO |
| `app/frontend/src/pages/workshop/IDEPage.tsx` | IDE AI complete payload 带 `market_data_use_validation_refs` |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. IDE AI complete 缺 `market_data_use_validation_refs` -> 422，不调用 LLM，不写 Graph command。
2. IDE AI complete 引用 violation MarketDataUse validation -> 422，不调用 LLM，不写 Graph command。
3. IDE AI complete 引用 accepted/no-violation validation -> 调 LLM，返回 refs，LLMCallRecord QRO input/output contract 记录 refs。
4. LLMCallRecord QRO 仍不泄露 prompt、context code 或 generated output。

## 红线 [按需]
- 不触网拉行情，不生成或发送真实 order。
- 不把 MarketDataUse validation 说成 LLM 生成代码已消费具体数据行。
- 不把 AI complete 说成策略已验证、sandboxed、promoted 或 evidence-backed。

## 非目标 [按需]
不实现真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator 验证、自动组合注入或 sandbox code 对具体数据行的强证明。

## 验收一句话 [必填]
IDE AI complete 必须先引用 accepted/no-violation MarketDataUse validation；否则 fail-closed 且不发生 LLM/QRO/Graph 副作用。

## 完成记录
- `ide_ai_complete` 在 prompt 非空后、LLM 调用前校验 `market_data_use_validation_refs`；缺 refs、unknown ref、未 accepted ref、violation ref 均 422。
- `LLMCallRecord` QRO input/output contract、lineage、implementation hash、assumptions/known_limits 记录 refs，仍不复制 prompt、context code 或 generated output。
- IDE 页面 AI complete payload 带同一组 MarketDataUse refs。
- 对抗测试证明缺 refs 与 violation refs 都不会调用 fake LLM，也不会写 Research Graph command；成功路径返回 refs，QRO 记录 refs且不泄露 prompt/context/output。
- 验证：`tests/test_strategy_console_s2.py` **38 passed / 2 warnings**；IDE/market-data/portfolio/execution adjacent **168 passed / 2 warnings**；Agent/DS/Chat adjacent **97 passed / 2 warnings**；`compileall app/backend/app` PASS；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- 边界：这是 IDE AI complete strategy codegen 的 refs-only MarketDataUse hard gate，不是真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator 验证、自动组合注入或 sandbox code 对真实数据行消费的强证明。
