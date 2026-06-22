---
uuid: 46f1cb3c60c84a7cb49a87b4418591ea
title: 组合层 M8 多证据三角守门（T-033 核验 gap 升级）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
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

## Open Questions（已决 3/3）[按需]
- [已决] 组合 strategy_goal_ref / 主题归属：**Q1=A1 独立命名空间 `portfolio:<id>`**（与成分因子主题隔离，`_theme_matrix` 按 ref 过滤）+ **A2 override R2**：冷启动 PBO 不可达时凭 DSR 保守端+CI 双正放行（PBO 显式 N/A），仍受 strong_neg→red 兜底（D-WAVE1A）。
- [已决] honest-N 记账粒度：**Q2=A 组合独立 +1**（默认；复用同一本账）。诚实限界：同 ref 下组合与重权成分被 n_eff 聚类→N_eff 低估，仅影响乐观展示端、过闸保守端 honest_n 兜底不受影响。
- [已决] asset_class：**Q3=A 取最严 min_T**（任一成分 a_share→a_share/504），C 接线侧预解析。

## 验收一句话 [必填]
组合层过拟合 → 三角**不达 green**（red 仅 DSR<0.2/CI 上界≤0/PBO>0.7 等 strong_neg；「必红」是假命题已重写）；不破基线。

## 实现落账（done · 2026-06-22 · D-WAVE1A · full-fat + 消费者）
**评审降级 + 验收重写**：`optimize_portfolio` 当前无产品消费者（scaffolding-ahead-of-demand）；SEQ-CONSUMER=A → C full-fat + 加组合消费者。**critical 红线**：原验收「组合层过拟合→gate 必红」是假命题（冷启动 N<10→PBO=None→至多 yellow，yellow≠red；低 honest_n DSR 通缩弱+CI 双正可能误绿）→ 重写为「不达 green，red 仅 strong_neg」。

**实装（扩展不替换，复用单一源）：**
- 新 `portfolio/gate.py`：`portfolio_net_returns`（weights×标的已实现收益，可经 D 的 `load_panel(as_of_known)` PIT join）+ `gate_portfolio`（复用 `eval.gate_runner.evaluate_overfit_gate` 单一源，绝不自建第二 gate）+ `portfolio_composition`（ADV2：排序 (symbol,weight) 入 config_hash，不改 `lineage.ids`）+ `strictest_asset_class`（Q3）。
- `eval/overfit_gate.py`：`_decide`/`run_overfit_gate` 加 `allow_pbo_absent_green`（**A2，默认 False 单策略逐字不变**）；A2-green 时 all_agree=False + 措辞明标 PBO N/A + override 留痕。`gate_runner.evaluate_overfit_gate` 透传。
- 消费者 `agent/business_tools.py`：新 `portfolio.gate` 工具（agent 真能调组合 gate，预览只读 side_effect=none）。

**门必抓（6+1 测试 + 2 变异）**：`test_portfolio_gate.py` ADV1（A2 放行只在 DSR+CI 双正 / 过拟合 strong_neg→red 误绿兜底 / 单策略 allow=False 不受影响）+ ADV2（重排标的同 config_hash）+ Q3 最严 + 无 alpha 不达 green；`test_agent_business_tools_a4.py::..._portfolio_gate_tool_no_alpha_not_green`。变异：禁 strong_neg → 误绿断言 + 既有 `test_decide_no_single_point_of_failure` 双红。**全量 1258 passed/13 skipped**（基线 1251+7 未破，136s）。

**诚实残余/限界**：① honest-N 记账走 promote 治理流（record=True 能力已具备：`gate_portfolio(record=True, ledger, returns_store)`），但**尚无 production 组合 promote 端点真调用**（agent 预览 record=False）——消费者的「promote 注入」面未接 production 端点（gate 路径+消费者已就绪）。② A2 反假绿灯护栏（honest-N 下限）= 用户可选档、默认未加（gate 松紧归用户，§0.1 研究侧旋钮）；A2-green 透明标 PBO N/A 为 §3 诚实表达。③ 组合净收益的 PIT join 由调用方喂已实现收益（gate 不自取数，避免前视）。
