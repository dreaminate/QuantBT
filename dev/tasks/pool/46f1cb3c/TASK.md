---
uuid: 46f1cb3c60c84a7cb49a87b4418591ea
title: 组合层 M8 多证据三角守门（T-033 核验 gap 升级）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: portfolio
source: research
source_ref: 2026-06-20 T-033 核验（gap: portfolio_triangle）+ state.md:38
depends_on: []
---

# 组合层 M8 多证据三角守门

## Scope [必填]
组合层（M7-M8）加多证据三角（PBO/DSR/bootstrap）守门：把组合权重×标的收益合成「组合净收益序列」→ 走既有单一源 `gate_runner.evaluate_overfit_gate`（勿自建第二条 gate）。当前组合/信号层 0 接入（T-033 坐实 + state.md:38）。

## 上下文 / 动机 [按需]
T-033：三角 gate 唯二真实调用者均作用单策略层（promote.py:142 / main.py:2495）；portfolio/signals 不 import eval/*。组合加权后合成收益从未喂进 PBO/DSR。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/portfolio/optimizers.py | 153 optimize_portfolio | 产组合净收益序列 |
| app/backend/app/eval/gate_runner.py | 89 evaluate_overfit_gate | 复用（勿自建第二 gate） |
| app/backend/app/ide/promote.py | 142/159-163 | 参照注入契约 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 组合曲线注入已知过拟合（成分高相关刷虚高 Sharpe）→ gate 不给绿、PBO 升高。
2. 等价改写（equal_weight 重排标的）→ 坍缩到同一 config_hash 簇、不重复刷 N。

## Open Questions（已决 0/3）[按需]
- [需拍板] 组合 strategy_goal_ref / 主题归属与 PBO returns_matrix「同主题历史试验」语义（组合 vs 成分因子不混算）。
- [需拍板] honest-N 记账粒度（组合独立 +1 还是继承成分）。
- [需拍板] asset_class 对多市场混合组合的判定。

## 验收一句话 [必填]
组合层过拟合 → 三角门必抓；不破基线。
