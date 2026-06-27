---
uuid: 2c9f4e11035a9911d9814c9ab8fb77a2
title: Portfolio promote signal validation gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-signal-boundary
source: goal-gap
source_ref: GOAL §9 portfolio signal validation gate
depends_on: [b7c6d8a9ccce2a6a53904b97ab02303a]
completed_at: 2026-06-27
---

# Portfolio promote signal validation gate

## Scope [必填]
把组合 production promote 入口接到 signal validation gate：payload 只要声明 `signal_refs`，就必须提供对应 accepted `signal_validation_refs`，否则 422 且不消耗 honest-N。

## 上下文 / 动机 [按需]
`b7c6d8a9` 已提供可重放 SignalPerformanceValidationRecord，但若组合晋级入口不看它，signal validation 仍只是旁路 registry。本卡把组合 promote 的生产门与 signal validation 绑定，继续推进 §9 model→signal→portfolio contract。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `/api/portfolios/{portfolio_id}/promote` 增加 `signal_refs` / `signal_validation_refs` 门，坏 signal validation 在 `gate_portfolio` 前拒绝 |
| `app/backend/tests/test_portfolio_promote_api.py` | 覆盖 accepted validation 放行、缺 validation 拒绝、rejected validation 拒绝且不写 honest-N |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. portfolio payload 声明 `signal_refs` 但缺 `signal_validation_refs` 必须 422，honest-N 不增加。
2. `signal_validation_refs` 指向 rejected validation 必须 422，honest-N 不增加。
3. accepted validation 与 signal_ref 匹配时，portfolio promote 旧 gate 仍正常记录。

## 红线 [按需]
- 不允许把 signal validation 当成 signal alpha proof。
- 不允许 bad signal validation 消耗 honest-N。
- 不允许 portfolio promote 下单、动钱或翻 live stage。

## 非目标 [按需]
不实现自动组合，不实现 order emission，不实现 live trading，不实现外部 signal registry，不改变组合三角 gate 算法。

## 验收一句话 [必填]
组合 production promote 声明使用信号时，必须引用 matching accepted signal validation；缺失或 rejected 都不能进入组合 gate 记账。

## 完成记录（2026-06-27）
- `/api/portfolios/{portfolio_id}/promote` 新增 `signal_refs` / `signal_validation_refs` 可选输入。
- 声明 `signal_refs` 时，每个 signal 必须存在 SignalContract 且匹配 accepted SignalPerformanceValidationRecord。
- 本地验证：
  - `python -m pytest app/backend/tests/test_portfolio_promote_api.py -q` -> 8 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_portfolio_promote_api.py -q` -> 69 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 96 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 156）。
