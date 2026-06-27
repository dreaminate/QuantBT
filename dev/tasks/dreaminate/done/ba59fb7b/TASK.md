---
uuid: ba59fb7b858143ea8314c4853838398e
title: 组合 promote production 端点——组合三角 gate record=True 真记 honest-N
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: portfolio
source: goal-gap
source_ref: 2026-06-22 D-WAVE1A 残余① · C(46f1cb3c)/消费者(1e0e65b4) done 后的生产编排
depends_on: [46f1cb3c60c84a7cb49a87b4418591ea, 1e0e65b4385f4161a49cb73ec9e9f735]
completed_at: 2026-06-27
---

# 组合 promote production 端点——组合三角 gate record=True 真记 honest-N

## Scope [必填]
给组合三角 gate 一条 **production promote 流**：`gate_portfolio(record=True, ledger, returns_store)` 接进生产 ledger/returns_store（复用单策略 promote/risk_preview 已有的注入契约，main.py:127），使组合 promote 真记 honest-N（治理价值）。C 卡只落了 agent 预览消费者（record=False）；本卡补 production 记账面。

## 上下文 / 动机 [按需]
D-WAVE1A 残余①：`gate_portfolio` 的 record=True 能力已具备（C 卡建），但无 production 组合 promote 端点真调用 → 组合 gate 在生产里不记 honest-N。诚实依赖：需**组合已实现收益流**（weights × 标的逐期已实现收益，可经 D 的 `load_panel(as_of_known)` PIT join）+ 生产 ledger/returns_store 实例。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | 127 risk_preview / promote 注入契约 | 参照单策略，加组合 promote 路由 |
| app/backend/app/portfolio/gate.py | gate_portfolio(record=True) | 复用（已建） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 组合 promote → honest-N 真 +1（独立命名空间 portfolio:<id>）；重排成分同 config_hash 不重复 +1（复用 C 卡 ADV2）。
2. 过拟合组合 promote → 不达 green（复用 C 卡 strong_neg 兜底）+ 记账如实。

## 验收一句话 [必填]
组合 promote 在生产真记 honest-N + 走三角 gate；不破基线。

## 完成记录（2026-06-24 · deliver-final）
- commit `4082d5d`：`POST /api/portfolio/{id}/promote` 接 `gate_portfolio(record=True)` 复用一本账 `LEDGER`/`RETURNS_STORE` 单一源 → 组合 promote 真记 honest-N（独立 `portfolio:<id>` 命名空间）；config_hash 反作弊重排不复刷；过拟合不达 green；单策略路径零破坏；不可评分（净收益<2）入账前 422 拒（不污染不可逆账本）。
- 对抗测试 +8 + 变异自检（record=False 一翻 → 5 测 assert 0==1 转红）；`test_portfolio_gate` 14 passed；全量后端 1357 passed / 0 failed。
- 诚实残余：无持久组合 store（weights+已实现收益由调用方喂，防前视）；端点是 caller 证据记录者，PIT join 仍 caller 责任。
## 完成记录（2026-06-27）

- 新增 `POST /api/portfolios/{portfolio_id}/promote`：组合 production gate 固定 `record=True`，接全局 `LEDGER` / `RETURNS_STORE`，返回 `gate_verdict`、`config_hash`、`honest_n_before/after/delta`、`strategy_goal_ref=portfolio:<id>` 和边界声明。
- 输入 guard：`weights`、`asset_returns`、`markets` 必须按 symbol 精确对齐；收益序列必须同长、至少 2 点、有限数；`dataset_version` 必填；`record=false` 直接 422，避免把 production promote 端点降成 preview。
- 对抗验证：组合 promote honest-N 真 +1；同 portfolio 重排成分同 `config_hash` 不重复 +1；过拟合/负漂移组合仍记账但 `gate_verdict.color != green`；坏输入不写账。
- 本地验证：
  - `python -m pytest app/backend/tests/test_portfolio_gate.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_gate_wiring.py -q` → 17 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_portfolio.py app/backend/tests/test_portfolio_gate.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_gate_wiring.py app/backend/tests/test_run_verdict_card.py app/backend/tests/test_approval_gates.py -q` → 58 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/main.py app/backend/app/portfolio/gate.py app/backend/tests/test_portfolio_promote_api.py` → PASS。
- 边界：本端点只记录组合确证评估和三角 gate 证据，不下单、不动钱、不翻 production stage；调用方给的 `asset_returns` 仍需由上游 PIT/as-of-known 管道负责来源真实性。
