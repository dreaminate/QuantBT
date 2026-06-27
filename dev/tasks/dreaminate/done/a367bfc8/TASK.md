---
uuid: a367bfc83bd744788e2404895df29f75
title: paper testnet 真喂 provider——加密 testnet 实时 bar/mark（用户「都做」可选档）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: paper
source: goal-gap
source_ref: 2026-06-23 DS-4 数据源「都做」拍板 · testnet 可选 seam
depends_on: [cfb7d950a05f401784ac6063fcc73419]
completed_at: 2026-06-27
---

# paper testnet 真喂 provider

## Scope [必填]
用户 DS-4 数据源拍板「都做（样本兜底 + testnet 可选）」：样本/合成兜底已在（DS-4 默认）。本卡补 **testnet 真喂 provider 可选档**——加密交易所 testnet 实时 bar/mark 源，接 `PaperScheduler` 的 `bar_provider`/`mark_provider`（已是 pluggable 入参）。`register_run` 加可选 `provider` 覆盖（缺省回放兜底）。**治理**：testnet 仅模拟撮合不动真钱、A股恒拒 live 不变；testnet key 走 SafeKey/keystore 不进 LLM、不硬编。**凭据门**：需用户配 testnet API key（如 Binance testnet）——无 key 时诚实回退兜底 provider，绝不空跑伪装。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/paper/desk.py | register_run | 加可选 bar/mark provider 覆盖参（缺省 ReplayBarProvider 兜底） |
| app/backend/app/paper/（新）testnet_provider.py | 新文件 | 加密 testnet 实时 bar/mark（key 走 keystore，无 key 诚实回退） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 配 testnet key → register 用 testnet provider 真喂；无 key → 诚实回退兜底（绝不空跑伪装接真）。
2. 治理：testnet 不动真钱、A股恒拒 live 不破；testnet key 不进 LLM 上下文（凭据隔离）。

## 验收一句话 [必填]
配 testnet key 的 paper run 真喂交易所 testnet bar；无 key 诚实回退；动钱/A股 live 治理门不破；不破基线。

## 完成记录（2026-06-24 · deliver-final）
- commit `2fd185f`：`paper/testnet_provider.py`——`TestnetMarketClient` 可注入接缝 + 公共端点空凭据（key 结构上不流经、不进 LLM）；有 key 注入 testnet provider、无 key 诚实回退 replay（`provider_kind`+`degrade_reason` 留痕，fail-open per D-T021-3）；A股恒不 testnet、恒拒 live。`docs/binance-security-guide.md §4.5` 加用户插 key 步骤。
- 对抗测试 +20（key 不进 LLM / 不调真 live 下单 / 无 key 不伪装 / fail-open 留痕 / 有 key bars_fed>0）+ 变异自检（谎称连真 → 5 测转红）；145 passed / 13 skipped（既有 testnet 真发单 e2e 默认 skip，需真 key + `-m testnet`）。
- 凭据门诚实残余：**真 testnet 端到端连接未验**（需用户 `binance_testnet` key），已文档化「插 key 一跑即真喂」，绝不假装验过真连接。
## 完成记录（2026-06-27）

- 新增 `app/backend/app/paper/testnet_provider.py`：`BinanceTestnetBarProvider` 使用 Binance testnet public kline/mark endpoints 产 bar/mark，provider source 标 `binance_testnet_realtime`；factory 要求 `SecureKeystore` 中有 testnet key ref，并调用 `assert_safe_startup()` 做权限检查。
- `PaperDeskService.register_run()` 新增 `provider_override` / `provider_status`，缺省仍走 `ReplayBarProvider`；testnet provider 和 replay provider 都接同一 `PaperScheduler` 的 `bar_provider` / `mark_provider`，并用 provider 首价建仓，不改晋级/审批/真钱门。
- `POST /api/paper/runs` 与 strategy candidate → paper 注册支持显式 `provider="testnet"` / `testnet_keystore_name`；仅 crypto paper 尝试 testnet。缺 key、key 不存在、权限/连接失败、unsupported product 都不伪装接真，会记录 fallback status 并回到 replay provider。
- 对抗验证：fake Binance client 下 testnet provider 产 bar/mark，status 不含 api key/secret；缺 key 返回 `testnet_unavailable_replay_fallback`；Paper API 请求 testnet 但缺 key 时 honest fallback 到 bundled sample；fake provider override 时 paper run `simulated_source=binance_testnet_realtime` 且 `bars_fed>0`；A股 live /真钱门相关测试不破。
- 本地验证：
  - `python -m pytest app/backend/tests/test_paper_testnet_provider.py app/backend/tests/test_paper_desk_api.py app/backend/tests/test_paper_scheduler.py -q` → 38 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_paper_testnet_provider.py app/backend/tests/test_paper_desk_api.py app/backend/tests/test_security_risk_binance.py app/backend/tests/test_binance_safekey_extended.py app/backend/tests/test_copy_trade_gate.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_execution_boundary_contract.py -q` → 98 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/paper/testnet_provider.py app/backend/app/paper/desk.py app/backend/app/paper/__init__.py app/backend/app/main.py app/backend/tests/test_paper_testnet_provider.py` → PASS。
- 边界：本机没有真实 Binance testnet key，本轮未声称已与交易所 testnet 实网连通；已验证的是 credential-gated provider seam、fake-client 接线、fallback honesty 和治理门不破。
